"""Fresh SQL/CAS observation equivalence, corruption and race controls."""

from contextlib import contextmanager
import json
import os
import subprocess
import re
import sys

import pytest

from ipfs_datasets_py.logic.software_contracts import ast_ir, codebase_ir as module
from ipfs_datasets_py.logic.software_contracts.ast_ir import ASTRecord
from ipfs_datasets_py.logic.software_contracts.cache import CacheIntegrityError, ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    DuckDBASTStore, DuckDBASTStoreIntegrityError,
)

from .test_codebase_current import (
    VIEW, current_index, publish, repository, rows, scheduler,
)


class HistoricalIndex(module.RepositoryCodebaseIndex):
    """Exercise the compatibility path without replacing any producer."""


def historical(index):
    return HistoricalIndex(ingestor=index.ingestor, artifacts=index.artifacts, catalog=index.catalog)


@contextmanager
def profile(callback):
    previous = sys.getprofile()
    sys.setprofile(callback)
    try:
        yield
    finally:
        sys.setprofile(previous)


def counted_observation(index, repository, head, owner):
    calls = []
    code = ASTRecord.from_dict.__func__.__code__

    def observe(frame, event, argument):
        if event == "call" and frame.f_code is code:
            calls.append(frame.f_locals["value"]["provenance"]["path"])

    with profile(observe):
        observation = index.observe_current(repository, expected_head=head, scheduler=owner)
    return observation, calls


def test_native_observation_reconstructs_once_per_ast_with_identical_output(repository, current_index, scheduler):
    index, connection, _ = current_index
    owner, _, _ = scheduler
    # Non-ASCII source exercises exact UTF-8 payload joining, not ASCII escaping.
    (repository / "counter.py").write_text('def increment(n: int) -> int:\n    """café λ"""\n    return n + 1\n')
    head = publish(index, repository, owner, "unicode-equivalence").head
    assert module._ast_observation_context(index, index.ingestor.store) is not None
    before = rows(connection)
    native, native_calls = counted_observation(index, repository, head, owner)
    replay, replay_calls = counted_observation(historical(index), repository, head, owner)
    assert native == replay
    assert sorted(native_calls) == ["counter.py", "other.py"]
    assert sorted(replay_calls) == ["counter.py", "counter.py", "other.py", "other.py"]
    assert rows(connection) == before
    # Historical loading still returns a fully reconstructed typed record.
    assert isinstance(index.load_ast_artifact(native.manifest, "counter.py"), ASTRecord)


@pytest.mark.parametrize("corruption", ["missing", "invalid-json", "noncanonical", "wrong-cid", "oversize"])
def test_native_observation_retains_fresh_bounded_cas_verification(repository, current_index, scheduler, corruption):
    index, connection, _ = current_index
    owner, _, _ = scheduler
    head = publish(index, repository, owner, "cas-corruption").head
    manifest = index.load(head.manifest_cid)
    unit = next(unit for unit in manifest.units if unit.ast_cid is not None)
    path = index.artifacts.path_for(unit.ast_cid)
    raw = path.read_bytes()
    if corruption == "missing":
        path.unlink()
    elif corruption == "invalid-json":
        path.write_bytes(b"{")
    elif corruption == "noncanonical":
        path.write_bytes(raw + b"\n")
    elif corruption == "wrong-cid":
        path.write_bytes(b"{}")
    else:
        maximum = max(file.stat().st_size for file in index.artifacts.root.rglob("*") if file.is_file()) + 1
        index.artifacts.max_object_bytes = maximum
        path.write_bytes(b" " * (maximum + 1))
    assert module._ast_observation_context(index, index.ingestor.store) is not None
    before = rows(connection)
    error = FileNotFoundError if corruption == "missing" else CacheIntegrityError
    messages = []
    for candidate in (index, historical(index)):
        with pytest.raises(error) as caught:
            candidate.observe_current(repository, expected_head=head, scheduler=owner)
        messages.append(str(caught.value))
    assert messages[0] == messages[1]
    assert rows(connection) == before
    assert index.current(VIEW) == head


@pytest.mark.parametrize("mutation", ["invalidate", "source", "producer"])
def test_native_observation_retains_fences_after_cas_read(repository, current_index, scheduler, monkeypatch, mutation):
    index, _, _ = current_index
    owner, _, _ = scheduler
    head = publish(index, repository, owner, "cas-read-race").head
    selected = index.lookup(index.load(head.manifest_cid), "counter.py")
    assert module._ast_observation_context(index, index.ingestor.store) is not None
    code = ImmutableCAS._decode_structured_payload.__code__
    changed = []

    def after_read(frame, event, argument):
        if (event == "return" and frame.f_code is code
                and frame.f_locals["cid"] == selected.ast_cid and not changed):
            changed.append(True)
            if mutation == "invalidate":
                index.ingestor.store.invalidate(blob_id=selected.blob_id, reason="manual")
            elif mutation == "source":
                (repository / "counter.py").write_text("def increment(n):\n    return n + 2\n")
            else:
                monkeypatch.setattr(ast_ir, "_ID_RE", re.compile("changed-producer"))

    error, message = {
        "invalidate": (DuckDBASTStoreIntegrityError, "no longer active"),
        "source": (module.StaleCodebaseError, "repository differs"),
        "producer": (module.CodebaseIRError, "reconstruction semantics changed"),
    }[mutation]
    with profile(after_read), pytest.raises(error, match=message):
        index.observe_current(repository, expected_head=head, scheduler=owner)
    assert changed == [True]
    assert index.current(VIEW) == head


def test_native_observation_rereads_cas_after_sql_reconstruction(repository, current_index, scheduler):
    index, _, _ = current_index
    owner, _, _ = scheduler
    head = publish(index, repository, owner, "sql-cas-race").head
    selected = index.lookup(index.load(head.manifest_cid), "counter.py")
    assert module._ast_observation_context(index, index.ingestor.store) is not None
    code = ASTRecord.from_dict.__func__.__code__
    changed = []

    def after_reconstruction(frame, event, record):
        if (event == "return" and frame.f_code is code and isinstance(record, ASTRecord)
                and record.provenance.path == "counter.py" and not changed):
            changed.append(True)
            index.artifacts.path_for(selected.ast_cid).write_bytes(b"{}")

    with profile(after_reconstruction), pytest.raises(CacheIntegrityError, match="CID mismatch"):
        index.observe_current(repository, expected_head=head, scheduler=owner)
    assert changed == [True]


@pytest.mark.parametrize("customization", ["index", "cas", "store", "instance-hook", "decoder", "memory"])
def test_custom_and_memory_observation_preserves_historical_loader(repository, current_index, scheduler, monkeypatch, customization):
    index, connection, _ = current_index
    owner, _, _ = scheduler
    head = publish(index, repository, owner, "compatibility").head
    expected = index.observe_current(repository, expected_head=head, scheduler=owner)
    if customization == "index":
        index = historical(index)
    elif customization == "cas":
        class CustomCAS(ImmutableCAS):
            pass
        index.artifacts = CustomCAS(index.artifacts.root)
    elif customization == "store":
        class CustomStore(DuckDBASTStore):
            pass
        index.ingestor = DuckDBASTIngestor(store=CustomStore(connection=connection))
    elif customization == "instance-hook":
        monkeypatch.setattr(index, "load_ast_artifact", index.load_ast_artifact)
    elif customization == "decoder":
        original = ASTRecord.from_dict.__func__
        monkeypatch.setattr(ASTRecord, "from_dict", classmethod(lambda cls, value: original(cls, value)))
    else:
        memory = DuckDBASTStore()
        for unit in expected.manifest.units:
            if unit.ast_cid is not None:
                memory.put_projection(index.ingestor.store.get_by_ast_cid(unit.ast_cid))
        index.ingestor = DuckDBASTIngestor(store=memory)
    assert module._ast_observation_context(index, index.ingestor.store) is None
    calls = []
    code = module.RepositoryCodebaseIndex.load_ast_artifact.__code__

    def observe(frame, event, argument):
        if event == "call" and frame.f_code is code:
            calls.append(frame.f_locals["path"])

    with profile(observe):
        actual = index.observe_current(repository, expected_head=head, scheduler=owner)
    assert actual == expected
    assert calls == ["counter.py", "other.py"]


@pytest.mark.parametrize("method", ["from_dict", "from_json"])
def test_preimport_schema_wrappers_preserve_ordinary_observation(tmp_path, method):
    script = r'''
import functools, json, sys
from pathlib import Path
from ipfs_datasets_py.logic.software_contracts.ast_ir import ASTRecord
original = getattr(ASTRecord, sys.argv[2]).__func__
@functools.wraps(original)
def wrapped(cls, value):
    return original(cls, value)
setattr(ASTRecord, sys.argv[2], classmethod(wrapped))
from ipfs_datasets_py.logic.software_contracts import codebase_ir as module
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
import duckdb
connection = duckdb.connect(str(Path(sys.argv[1]) / "preimport.duckdb"))
store = DuckDBASTStore(connection=connection)
index = module.RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=ImmutableCAS(Path(sys.argv[1]) / "cas"))
assert module._ast_observation_context(index, store) is None
assert getattr(ASTRecord, sys.argv[2]).__func__ is wrapped
connection.close()
print(json.dumps({"native_eligible": False, "wrapper_retained": True}))
'''
    run = subprocess.run([sys.executable, "-B", "-c", script, str(tmp_path), method],
                         capture_output=True, text=True, timeout=30, env=dict(os.environ))
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout.splitlines()[-1]) == {"native_eligible": False, "wrapper_retained": True}
