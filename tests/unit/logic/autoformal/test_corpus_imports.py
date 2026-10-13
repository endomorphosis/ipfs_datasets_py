"""Actual package imports stay separate from compiler session construction."""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from ipfs_datasets_py.logic import autoformal


def test_actual_public_imports_need_no_compiler_or_numerical_runtime():
    program = '''
import json, sys
from ipfs_datasets_py.logic.autoformal import corpus_contracts, corpus_graph, corpus_source, corpus_qualification
from ipfs_datasets_py.logic import autoformal
assert "SESSION" not in vars(autoformal)
assert "SESSION" in dir(autoformal)
blocked = [name for name in sys.modules if name == "torch" or name == "transformers"
           or name.endswith("canonical_compiler") or name.endswith("deontic_parser")]
assert not blocked, blocked
print(json.dumps([m.__file__ for m in (corpus_contracts, corpus_graph, corpus_source, corpus_qualification)]))
'''
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, check=True)
    root = Path(__file__).resolve().parents[5]
    assert all(Path(path).resolve().is_relative_to(root) for path in json.loads(result.stdout))


def test_real_public_session_is_deferred_pinned_cached_and_resettable():
    program = '''
from pathlib import Path
from ipfs_datasets_py.logic import autoformal
assert "SESSION" not in vars(autoformal)
first = autoformal.SESSION
assert isinstance(first, autoformal.AutoformalSession)
assert autoformal.SESSION is first
assert autoformal.dispatch("clause_get", {"document_id":"missing","clause_id":"missing"}) == {"error":"not_found"}
autoformal.reset_session()
assert isinstance(autoformal.SESSION, autoformal.AutoformalSession)
assert autoformal.SESSION is not first
from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
root = Path(autoformal.__file__).resolve().parents[3]
assert all(Path(path).is_relative_to(root) for path in require_workspace_logic_tree().values())
'''
    subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, check=True)


def _fake_session(monkeypatch):
    made = []

    class Session:
        def __init__(self):
            made.append(self)

        def clause_get(self, *args):
            return {"args": args}

    # Avoid monkeypatch.delattr's module getattr, which would construct SESSION.
    monkeypatch.delitem(vars(autoformal), "SESSION", raising=False)
    monkeypatch.setattr(autoformal, "AutoformalSession", Session)
    return made


def test_session_attribute_constructs_once_and_dispatch_uses_same_instance(monkeypatch):
    made = _fake_session(monkeypatch)
    try:
        first = autoformal.SESSION
        assert autoformal.SESSION is first
        assert made == [first]
        assert autoformal.dispatch("clause_get", {"document_id": "d", "clause_id": "c"}) == {"args": ("d", "c")}
        assert made == [first]
    finally:
        vars(autoformal).pop("SESSION", None)


def test_reset_explicitly_replaces_the_session(monkeypatch):
    made = _fake_session(monkeypatch)
    try:
        first = autoformal.SESSION
        assert autoformal.reset_session() is None
        assert autoformal.SESSION is made[1]
        assert autoformal.SESSION is not first
    finally:
        vars(autoformal).pop("SESSION", None)


def test_failed_initialization_is_not_cached_or_hidden(monkeypatch):
    _fake_session(monkeypatch)

    def failure():
        raise RuntimeError("compiler tree mismatch")

    monkeypatch.setattr(autoformal, "AutoformalSession", failure)
    with pytest.raises(RuntimeError, match="compiler tree mismatch"):
        _ = autoformal.SESSION
    assert "SESSION" not in vars(autoformal)


def test_unknown_dispatch_does_not_construct_a_session(monkeypatch):
    made = _fake_session(monkeypatch)
    assert autoformal.dispatch("missing", {}) == {"error": "unknown_tool", "name": "missing"}
    assert not made
    with pytest.raises(AttributeError):
        _ = autoformal.not_a_session


def test_concurrent_first_consumers_share_one_session(monkeypatch):
    made = _fake_session(monkeypatch)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            sessions = list(pool.map(lambda _: autoformal.SESSION, range(32)))
        assert len(made) == 1
        assert all(session is made[0] for session in sessions)
    finally:
        vars(autoformal).pop("SESSION", None)
