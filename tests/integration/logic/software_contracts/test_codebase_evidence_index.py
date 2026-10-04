"""Native DuckDB/CAS evidence persistence, exact bindings and atomic refusal."""
from dataclasses import replace
import json
import os
import subprocess
import sys

import pytest

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHeadConflict
from ipfs_datasets_py.duckdb_control.codebase_evidence_index import (
    CodebaseEvidenceIndex, CodebaseEvidenceIndexError, CodebaseEvidenceIndexLimits,
)
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.codebase_property_cache import build_codebase_property_binding
from .test_codebase_integer_verification import NATIVE, contract, verifier
from .test_codebase_current import repository, scheduler, current_index, publish, change, VIEW

pytestmark = NATIVE


@pytest.fixture
def checked(repository, verifier, scheduler):
    owner, _, _ = scheduler
    head = publish(verifier.index, repository, owner, "first").head
    receipt = verifier.verify(repository, expected_head=head, contract=contract(), scheduler=owner)
    assert receipt["status"] == "proved"
    evidence = CodebaseEvidenceIndex(verifier.index.catalog)
    return evidence, head, receipt


def sealed(evidence, receipt, mutate):
    value = {key: value for key, value in receipt.items() if key != "receipt_cid"}
    value = json.loads(json.dumps(value))
    mutate(value)
    return evidence.artifacts.put(value)


def rebind(value):
    old = value["cache_binding"]
    value["cache_binding"] = build_codebase_property_binding(**{
        name: old[name] for name in ("source_cid", "snapshot_cid", "profile", "contract_cid", "compiled_cid",
                                   "bounds", "environment", "provider", "checker")})


def test_native_exact_persistence_reverse_dependencies_and_no_compiler_replay(checked, monkeypatch):
    evidence, head, receipt = checked
    record = evidence.publish(receipt["receipt_cid"], expected_head=head)
    assert evidence.publish(record.receipt_cid, expected_head=head).cid == record.cid
    from ipfs_datasets_py.logic.software_contracts import codebase_integer_profile as profile
    from ipfs_datasets_py.logic.backends.smt.compiler import SoftwareVerificationSMTCompiler
    def forbidden(*args, **kwargs):
        pytest.fail("historical lookup must not invoke native checking or source compilation")
    monkeypatch.setattr(profile, "compile_integer_offset", forbidden)
    monkeypatch.setattr(profile, "execute_integer_offset", forbidden)
    monkeypatch.setattr(SoftwareVerificationSMTCompiler, "compile", forbidden)
    assert evidence.get(record.receipt_cid, expected_head=head).cid == record.cid
    assert evidence.lookup(record.binding, expected_head=head) == (record,)
    for kind, value in record.dependencies:
        assert evidence.dependents(kind, value, expected_head=head) == (record,)
    payload = record.to_dict()
    assert payload["authority"] == "historical_conditional"
    assert payload["requires_fresh_native_checks"] is payload["requires_current_source_observation"] is True
    assert payload["kernel_checked"] is payload["behavior_authority"] is False
    assert payload["execution_authority"] is payload["completion_authority"] is False
    mutated = record.binding
    mutated["profile"].clear()
    assert record.binding == receipt["cache_binding"]


def test_fresh_process_exact_lookup_and_reverse_dependency(checked, current_index, tmp_path):
    evidence, head, receipt = checked
    record = evidence.publish(receipt["receipt_cid"], expected_head=head)
    _, connection, database = current_index
    connection.close()
    inputs = tmp_path / "evidence-input.json"
    inputs.write_text(json.dumps({"head": head.to_dict(), "receipt": record.receipt_cid,
                                 "binding": record.binding, "source": receipt["source_cid"]}))
    script = '''
import json, sys
import duckdb
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHead
from ipfs_datasets_py.duckdb_control.codebase_evidence_index import CodebaseEvidenceIndex
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts import codebase_integer_profile
def forbidden(*args, **kwargs):
    raise AssertionError("historical lookup executed compiler or solver")
codebase_integer_profile.compile_integer_offset = forbidden
codebase_integer_profile.execute_integer_offset = forbidden
data = json.load(open(sys.argv[3]))
cx = duckdb.connect(sys.argv[1], config={"threads":1,"memory_limit":"64MB"})
owner = CodebaseCatalog(DuckDBASTStore(connection=cx), ImmutableCAS(sys.argv[2]))
index = CodebaseEvidenceIndex(owner)
head = CodebaseHead.from_dict(data["head"])
record = index.get(data["receipt"], expected_head=head)
assert index.lookup(data["binding"], expected_head=head) == (record,)
assert index.dependents("source", data["source"], expected_head=head) == (record,)
print(json.dumps(record.to_dict()))
cx.close()
'''
    process = subprocess.run([sys.executable, "-c", script, str(database), str(evidence.artifacts.root), str(inputs)],
                             text=True, capture_output=True, timeout=30, env={**os.environ, "PYTHONPATH": os.getcwd()})
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == record.to_dict()


@pytest.mark.parametrize("kind", ["canonical_key", "source", "contract", "bounds", "environment", "authority", "solver", "compiled"])
def test_forged_receipt_bindings_refuse_before_any_sql_publication(checked, kind):
    evidence, head, receipt = checked
    def mutate(value):
        if kind == "canonical_key":
            value["cache_binding"]["canonical_key_id"] = cid_for_structured({"forged": True})
        elif kind == "source":
            value["source_cid"] = evidence.artifacts.put_bytes(b"different bytes")
        elif kind == "contract":
            value["contract"]["offset"] = 3
        elif kind == "bounds":
            value["checks"]["bounds"]["solver_memory_mb"] = 4096
        elif kind == "environment":
            value["checks"]["checker_identity"]["solvers"][0]["executable_sha256"] = "0" * 64
        elif kind == "authority":
            value["completion_authority"] = True
        elif kind == "solver":
            value["checks"]["solvers"][0]["status"] = "refuted"
        else:
            value["compiled_cid"] = cid_for_structured({"missing": True})
    cid = sealed(evidence, receipt, mutate)
    with pytest.raises((CodebaseEvidenceIndexError, ValueError)):
        evidence.publish(cid, expected_head=head)
    assert evidence._cx.execute("SELECT count(*) FROM codebase_evidence.records").fetchone() == (0,)
    assert evidence._cx.execute("SELECT count(*) FROM codebase_evidence.dependencies").fetchone() == (0,)


def test_recomputed_key_cannot_rebind_different_compilation(checked):
    evidence, head, receipt = checked
    compiled = evidence.artifacts.get(receipt["compiled_cid"])
    compiled["source_binding"]["content_sha256"] = "0" * 64
    wrong_cid = evidence.artifacts.put(compiled)
    def mutate(value):
        value["compiled_cid"] = value["checks"]["compiled_cid"] = value["cache_binding"]["compiled_cid"] = wrong_cid
        rebind(value)
    cid = sealed(evidence, receipt, mutate)
    with pytest.raises(CodebaseEvidenceIndexError, match="source binding"):
        evidence.publish(cid, expected_head=head)


@pytest.mark.parametrize("table", ["records", "dependencies", "receipt", "compilation", "source", "schema"])
def test_stored_corruption_is_rejected_on_exact_read(checked, table):
    evidence, head, receipt = checked
    evidence.publish(receipt["receipt_cid"], expected_head=head)
    if table == "records":
        evidence._cx.execute("UPDATE codebase_evidence.records SET canonical_key_id='corrupt'")
    elif table == "dependencies":
        evidence._cx.execute("DELETE FROM codebase_evidence.dependencies WHERE kind='contract'")
    elif table == "schema":
        evidence._cx.execute("ALTER TABLE codebase_evidence.records ADD COLUMN foreign_column INTEGER")
    else:
        cid = receipt[{"receipt": "receipt_cid", "compilation": "compiled_cid", "source": "source_cid"}[table]]
        evidence.artifacts.path_for(cid, source=table == "source").write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        evidence.get(receipt["receipt_cid"], expected_head=head)


def test_successor_and_restored_snapshot_cannot_rebind_old_receipt(checked, repository, verifier, scheduler):
    evidence, first, receipt = checked
    evidence.publish(receipt["receipt_cid"], expected_head=first)
    owner, _, _ = scheduler
    change(repository, 2)
    second = publish(verifier.index, repository, owner, "second", first).head
    with pytest.raises(CodebaseHeadConflict):
        evidence.get(receipt["receipt_cid"], expected_head=first)
    with pytest.raises(CodebaseHeadConflict):
        evidence.get(receipt["receipt_cid"], expected_head=second)
    change(repository, 1)
    restored = publish(verifier.index, repository, owner, "restored", second).head
    assert restored.snapshot_cid == first.snapshot_cid and restored.generation != first.generation
    assert evidence.lookup(receipt["cache_binding"], expected_head=restored) == ()
    with pytest.raises(CodebaseHeadConflict):
        evidence.publish(receipt["receipt_cid"], expected_head=restored)


def test_batch_late_cancellation_rolls_back_records_and_dependencies(checked, verifier, repository, scheduler):
    evidence, head, receipt = checked
    owner, _, _ = scheduler
    other = verifier.verify(repository, expected_head=head, contract=contract(2), scheduler=owner)
    class Cancelled(BaseException):
        pass
    def checkpoint():
        if evidence._cx.execute("SELECT count(*) FROM codebase_evidence.records").fetchone()[0] == 2:
            raise Cancelled()
    with pytest.raises(Cancelled):
        evidence.publish_many([receipt["receipt_cid"], other["receipt_cid"]], expected_head=head, checkpoint=checkpoint)
    assert evidence._cx.execute("SELECT count(*) FROM codebase_evidence.records").fetchone() == (0,)
    assert evidence._cx.execute("SELECT count(*) FROM codebase_evidence.dependencies").fetchone() == (0,)
    assert evidence.catalog.current(VIEW) == head
    records = evidence.publish_many([receipt["receipt_cid"], other["receipt_cid"]], expected_head=head)
    assert [record.status for record in records] == ["proved", "refuted"]


def test_capacity_and_query_overflow_refuse_without_silent_truncation(checked):
    evidence, head, receipt = checked
    evidence = CodebaseEvidenceIndex(evidence.catalog, limits=replace(CodebaseEvidenceIndexLimits(), max_records=2))
    first = evidence.publish(receipt["receipt_cid"], expected_head=head)
    second_cid = sealed(evidence, receipt, lambda value: value.update(cache_history_hit=True))
    evidence.publish(second_cid, expected_head=head)
    with pytest.raises(CodebaseEvidenceIndexError, match="result bound"):
        evidence.lookup(receipt["cache_binding"], expected_head=head, limit=1)
    with pytest.raises(CodebaseEvidenceIndexError, match="result bound"):
        evidence.dependents("source", receipt["source_cid"], expected_head=head, limit=1)
    third_cid = sealed(evidence, receipt, lambda value: value["checks"]["solvers"][0].update(elapsed_ms=1234567))
    with pytest.raises(CodebaseEvidenceIndexError, match="capacity"):
        evidence.publish(third_cid, expected_head=head)
    assert evidence.publish(first.receipt_cid, expected_head=head).cid == first.cid
    assert evidence._cx.execute("SELECT count(*) FROM codebase_evidence.records").fetchone() == (2,)


def test_oversized_compilation_reads_only_configured_bound(checked, monkeypatch):
    evidence, head, receipt = checked
    evidence.publish(receipt["receipt_cid"], expected_head=head)
    evidence.limits = replace(evidence.limits, max_compiled_bytes=128)
    with pytest.raises(ValueError, match="byte bound"):
        evidence.get(receipt["receipt_cid"], expected_head=head)


def test_query_preflights_oversized_sql_identifier_before_materializing(checked):
    evidence, head, receipt = checked
    evidence.publish(receipt["receipt_cid"], expected_head=head)
    evidence._cx.execute("UPDATE codebase_evidence.records SET receipt_cid=repeat('x', 1048576)")
    with pytest.raises(CodebaseEvidenceIndexError, match="queried receipt identifier.*byte bound"):
        evidence.lookup(receipt["cache_binding"], expected_head=head)


def test_index_current_head_does_not_claim_live_checkout_freshness(checked, repository):
    evidence, head, receipt = checked
    evidence.publish(receipt["receipt_cid"], expected_head=head)
    change(repository, 99)
    record = evidence.get(receipt["receipt_cid"], expected_head=head)
    assert record.to_dict()["requires_current_source_observation"] is True
    assert record.to_dict()["behavior_authority"] is False


def test_independent_catalog_writer_conflicts_with_index_publication(checked, current_index):
    import duckdb
    evidence, head, receipt = checked
    _, _, database = current_index
    other = duckdb.connect(str(database), config={"threads": 1, "memory_limit": "64MB"})
    attempts = []
    def checkpoint():
        if attempts:
            return
        attempts.append(True)
        other.execute("BEGIN")
        try:
            with pytest.raises(duckdb.TransactionException, match="Conflict"):
                other.execute("UPDATE codebase_control.heads SET generation=generation+1 WHERE repository_id=?", [head.repository_id])
        finally:
            other.execute("ROLLBACK")
    try:
        record = evidence.publish(receipt["receipt_cid"], expected_head=head, checkpoint=checkpoint)
        assert record.head == head and evidence.catalog.current(VIEW) == head
    finally:
        other.close()


def test_interrupted_write_guard_restores_exact_head_and_never_exposes_negative_generation(checked, current_index, monkeypatch):
    import duckdb
    evidence, head, receipt = checked
    _, connection, database = current_index
    before = connection.execute("SELECT * FROM codebase_control.heads").fetchall()
    other = duckdb.connect(str(database), config={"threads": 1, "memory_limit": "64MB"})
    class Cancelled(BaseException):
        pass
    class InterruptRestore:
        def execute(self, statement, *args):
            if statement == "UPDATE codebase_control.heads SET generation=? WHERE repository_id=?":
                assert connection.execute("SELECT generation FROM codebase_control.heads").fetchone() == (-head.generation,)
                assert other.execute("SELECT * FROM codebase_control.heads").fetchall() == before
                raise Cancelled()
            return connection.execute(statement, *args)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(evidence, "_cx", InterruptRestore())
            with pytest.raises(Cancelled):
                evidence.publish(receipt["receipt_cid"], expected_head=head)
        assert connection.execute("SELECT * FROM codebase_control.heads").fetchall() == before
        assert evidence.catalog.current(VIEW) == head
        assert evidence._cx.execute("SELECT count(*) FROM codebase_evidence.records").fetchone() == (0,)
        evidence.publish(receipt["receipt_cid"], expected_head=head)
        assert connection.execute("SELECT * FROM codebase_control.heads").fetchall() == before
    finally:
        other.close()


def test_index_rejects_inherited_owner_pid(checked, monkeypatch):
    import ipfs_datasets_py.duckdb_control.codebase_catalog as catalog_module
    evidence, head, receipt = checked
    original = os.getpid()
    monkeypatch.setattr(catalog_module.os, "getpid", lambda: original + 1)
    with pytest.raises(ValueError, match="another process"):
        evidence.get(receipt["receipt_cid"], expected_head=head)
