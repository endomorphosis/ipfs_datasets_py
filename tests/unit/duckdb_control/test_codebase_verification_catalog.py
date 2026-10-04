"""Actual durable owner restart, exact current evidence and adversarial drift."""

from dataclasses import replace
import json
import shutil
import subprocess
import sys
import threading

import pytest

from ipfs_datasets_py.duckdb_control import codebase_verification_catalog as module
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex, StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts import codebase_verification as verifier
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig


@pytest.fixture
def prepared(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    verifier._IMPORTED_SOURCE_PINS.clear()
    repository = tmp_path / "source"
    repository.mkdir()
    (repository / "counter.py").write_text("def increment(n: float) -> float:\n    return n + 1\n", encoding="utf-8")
    for args in (("init", "-q"), ("config", "user.name", "Projection Fixture"),
                 ("config", "user.email", "fixture@example.invalid"), ("add", "."), ("commit", "-qm", "fixture")):
        subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True)
    connection = duckdb.connect(str(tmp_path / "catalog.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    artifacts = ImmutableCAS(tmp_path / "artifacts")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
                                   catalog=CodebaseCatalog(store, artifacts))
    owner = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8, 8192, 8192),
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=0.005))
    head = index.prepare_current(repository, repository_id="repository:projection-fixture", operation_id="initial",
                                 expected_head=None, scheduler=owner).head
    contract = ContractSpec("increment", postconditions=("result == n + 1",))
    record = verifier.verify_current_codebase_unit(index, repository, expected_head=head, path="counter.py",
                                                  contracts=[contract], scheduler=owner)
    catalog = module.CodebaseVerificationCatalog(index)
    yield catalog, index, repository, head, record, contract, owner, connection, tmp_path
    assert owner.snapshot()["active_lease_count"] == 0
    connection.close()


def publish(prepared, **kwargs):
    catalog, _, repository, head, record, _, owner, _, _ = prepared
    options = dict(expected_head=head, verification_cid=record.artifact_cid, operation_id="project", scheduler=owner)
    options.update(kwargs)
    return catalog.publish(repository, **options)


def lookup(prepared, **kwargs):
    catalog, _, repository, head, _, contract, owner, _, _ = prepared
    options = dict(expected_head=head, path="counter.py", contract_id=contract.contract_id, scheduler=owner)
    options.update(kwargs)
    return catalog.lookup_current(repository, **options)


def test_native_projection_retains_conditional_unknown_and_exact_detached_refs(prepared):
    catalog, index, _, head, record, contract, _, connection, _ = prepared
    before = connection.execute("SELECT * FROM codebase_control.heads").fetchall()
    assert lookup(prepared) == ()
    projected = publish(prepared)
    assert projected.verification.artifact_cid == record.artifact_cid
    assert projected.verification.observed_live is False
    assert not projected.verification.conditional_proved
    assert projected.applicability is None
    value = projected.to_dict()
    assert value["head"] == head.to_dict()
    assert value["dependencies"]["source_cid"] == record.to_dict()["source_binding"]["entry"]["source_cid"]
    assert value["contracts"][0]["contract_cid"] == cid_for_structured(contract.to_dict())
    assert value["contracts"][0]["canonical_keys"] == []
    assert all(flag is False for name, flag in value["authority"].items() if name != "historical_conditional_evidence")
    found = lookup(prepared, verification_cid=record.artifact_cid, expected_contract_cid=cid_for_structured(contract.to_dict()))
    assert len(found) == 1 and found[0].to_dict() == value
    value["authority"]["kernel_checked"] = True
    assert projected.to_dict()["authority"]["kernel_checked"] is False
    assert index.artifacts.get(projected.projection_cid)["authority"]["kernel_checked"] is False
    assert connection.execute("SELECT * FROM codebase_control.heads").fetchall() == before
    assert connection.execute("SELECT count(*) FROM codebase_verification_control.operations").fetchone()[0] == 1


def test_native_real_keys_select_complete_exact_identity_without_rerunning_solvers(prepared, monkeypatch):
    if any(shutil.which(name) is None for name in ("z3", "cvc5")):
        pytest.skip("native solver pair unavailable")
    _, index, repository, head, _, contract, owner, _, _ = prepared
    (repository / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 1\n")
    new_head = index.prepare_current(repository, repository_id=head.repository_id, operation_id="typed", expected_head=head, scheduler=owner).head
    record = verifier.verify_current_codebase_unit(index, repository, expected_head=new_head, path="counter.py", contracts=[contract], scheduler=owner)
    projected = publish(prepared, expected_head=new_head, verification_cid=record.artifact_cid)
    key = projected.to_dict()["contracts"][0]["canonical_keys"][0]
    assert key["key_id"].startswith("canonical-proof-cache-key:")
    assert key["key"]["source_cid"] == record.to_dict()["source_binding"]["entry"]["source_cid"]
    # Both compile-only historical replay and Git observation remain allowed;
    # any native solver/version executable launched by lookup is a failure.
    original = subprocess.run
    def git_only(args, *a, **kw):
        assert args[0] == "git"
        return original(args, *a, **kw)
    monkeypatch.setattr(subprocess, "run", git_only)
    found = lookup(prepared, expected_head=new_head, expected_key_id=key["key_id"])
    assert len(found) == 1 and found[0].verification.conditional_proved
    assert not found[0].verification.observed_live
    assert lookup(prepared, expected_head=new_head, expected_key_id="canonical-proof-cache-key:sha256:" + "0" * 64) == ()


def test_operation_replay_and_conflict_preserve_immutable_history(prepared):
    first = publish(prepared)
    replay = publish(prepared)
    assert replay.to_dict() == first.to_dict()
    catalog, index, repository, head, _, _, owner, connection, _ = prepared
    other = verifier.verify_current_codebase_unit(index, repository, expected_head=head, path="counter.py",
        contracts=[ContractSpec("increment", postconditions=("result == n + 9",))], scheduler=owner)
    with pytest.raises(module.CodebaseVerificationOperationConflict):
        publish(prepared, verification_cid=other.artifact_cid)
    assert connection.execute("SELECT count(*) FROM codebase_verification_control.records").fetchone()[0] == 1
    assert lookup(prepared)[0].projection_cid == first.projection_cid


@pytest.mark.parametrize("linked", [False, True])
def test_fresh_process_restart_reads_native_refs_and_conditional_authority(prepared, linked):
    _, _, repository, head, _, contract, _, connection, root = prepared
    app_cid = ""
    if linked:
        head, parent, app, _ = typed_applicability(prepared)
        app_cid = app.artifact_cid
        projected = publish(prepared, expected_head=head, verification_cid=parent.artifact_cid, applicability_cid=app_cid)
    else:
        projected = publish(prepared)
    connection.close()
    code = """
import json,sys
from pathlib import Path
import duckdb
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog,CodebaseHead
from ipfs_datasets_py.duckdb_control.codebase_verification_catalog import CodebaseVerificationCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler,ResourceSchedulerConfig
root=Path(sys.argv[1]); head=CodebaseHead.from_dict(json.loads(sys.argv[2]))
cx=duckdb.connect(str(root/'catalog.duckdb'),config={'threads':1,'memory_limit':'64MB'})
store=DuckDBASTStore(connection=cx); cas=ImmutableCAS(root/'artifacts')
index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
owner=GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(state_path=root/'restart-admission.json',proof_resource_sampler=lambda:ProofHostResources(8,8192,8192),lane_reservations={},auto_renew_leases=False))
catalog=CodebaseVerificationCatalog(index)
rows=catalog.lookup_current(root/'source',expected_head=head,path='counter.py',contract_id=sys.argv[3],scheduler=owner)
assert len(rows)==1 and rows[0].projection_cid==sys.argv[4]
assert not rows[0].verification.observed_live and rows[0].to_dict()['authority']['kernel_checked'] is False
if sys.argv[5]:
    assert rows[0].applicability.artifact_cid==sys.argv[5] and not rows[0].applicability.observed_live
assert owner.snapshot()['active_lease_count']==0
cx.close()
"""
    subprocess.run([sys.executable, "-c", code, str(root), json.dumps(head.to_dict()), contract.contract_id, projected.projection_cid, app_cid], check=True, capture_output=True, timeout=30)


def test_source_drift_and_same_snapshot_successor_remove_current_eligibility(prepared):
    projected = publish(prepared)
    _, index, repository, head, record, _, owner, _, _ = prepared
    original = (repository / "counter.py").read_bytes()
    (repository / "counter.py").write_bytes(original + b"# edited\n")
    with pytest.raises(StaleCodebaseError):
        lookup(prepared)
    with pytest.raises(StaleCodebaseError):
        publish(prepared)
    assert verifier.load_codebase_verification(index, record.artifact_cid).artifact_cid == record.artifact_cid
    (repository / "counter.py").write_bytes(original)
    successor = index.prepare_current(repository, repository_id=head.repository_id, operation_id="successor", expected_head=head, scheduler=owner).head
    assert successor.snapshot_cid == head.snapshot_cid and successor.generation > head.generation
    with pytest.raises(StaleCodebaseError):
        lookup(prepared)
    assert lookup(prepared, expected_head=successor) == ()
    with pytest.raises(StaleCodebaseError, match="another complete head"):
        publish(prepared, expected_head=successor)
    assert index.artifacts.get(projected.projection_cid)["head"] == head.to_dict()


@pytest.mark.parametrize("statement", [
    "UPDATE codebase_verification_control.records SET payload='{}'",
    "UPDATE codebase_verification_control.records SET path='wrong.py'",
    "UPDATE codebase_verification_control.entries SET keys_json='[{}]'",
    "UPDATE codebase_verification_control.entries SET dependencies_json='{}'",
    "UPDATE codebase_verification_control.entries SET entry_id='invented'",
    "UPDATE codebase_verification_control.entries SET projection_cid=repeat('x', 1025)",
    "DELETE FROM codebase_verification_control.records",
    "DELETE FROM codebase_verification_control.operations",
    "UPDATE codebase_verification_control.operations SET request_cid='invented'",
    "UPDATE codebase_verification_control.meta SET schema_cid='invented'",
    "CREATE TABLE codebase_verification_control.foreign_rows (value INTEGER)",
])
def test_projection_tamper_fails_closed(prepared, statement):
    publish(prepared)
    prepared[7].execute(statement)
    with pytest.raises((module.CodebaseVerificationCatalogError, ValueError)):
        lookup(prepared)


@pytest.mark.parametrize("target", ["projection", "verification", "source"])
def test_missing_or_corrupted_cas_objects_fail_closed(prepared, target):
    projected = publish(prepared)
    _, index, _, _, record, _, _, _, _ = prepared
    cid = {"projection": projected.projection_cid, "verification": record.artifact_cid,
           "source": record.to_dict()["source_binding"]["entry"]["source_cid"]}[target]
    path = index.artifacts.path_for(cid, source=target == "source")
    path.unlink()
    with pytest.raises((module.CodebaseVerificationCatalogError, ValueError, FileNotFoundError)):
        lookup(prepared)


def test_exact_contract_and_domain_selectors_do_not_infer_a_match(prepared):
    publish(prepared)
    assert lookup(prepared, expected_contract_cid=cid_for_structured(ContractSpec("increment", postconditions=("result == n + 2",)).to_dict())) == ()
    assert lookup(prepared, domain_id="domain:unpublished") == ()
    assert lookup(prepared, contract_id="contract:missing") == ()


def test_row_bound_and_requested_result_bound_are_explicit(prepared):
    publish(prepared)
    catalog, index, repository, head, _, _, owner, connection, _ = prepared
    bounded = module.CodebaseVerificationCatalog(index, limits=replace(catalog.limits, max_operations=1))
    with pytest.raises(module.CodebaseVerificationCatalogError, match="row bounds"):
        bounded.publish(repository, expected_head=head, verification_cid=prepared[4].artifact_cid, operation_id="second", scheduler=owner)
    assert connection.execute("SELECT count(*) FROM codebase_verification_control.operations").fetchone()[0] == 1
    record = verifier.verify_current_codebase_unit(index, repository, expected_head=head, path="counter.py",
        contracts=[ContractSpec("increment", postconditions=("result == n + 7",))], scheduler=owner)
    publish(prepared, verification_cid=record.artifact_cid, operation_id="different")
    assert len(lookup(prepared)) == 2
    with pytest.raises(module.CodebaseVerificationCatalogError, match="result limit"):
        lookup(prepared, limit=1)
    assert len(lookup(prepared, verification_cid=record.artifact_cid, limit=1)) == 1


def test_aggregate_retention_bound_fails_closed_before_return(prepared):
    publish(prepared)
    catalog, index, repository, head, _, contract, owner, _, _ = prepared
    bounded = module.CodebaseVerificationCatalog(index, limits=replace(catalog.limits, max_result_bytes=1))
    with pytest.raises(module.CodebaseVerificationCatalogError, match="aggregate exact results"):
        bounded.lookup_current(repository, expected_head=head, path="counter.py", contract_id=contract.contract_id, scheduler=owner)


def typed_applicability(prepared, predicates=("True",), domain_id="domain:fixture"):
    if any(shutil.which(name) is None for name in ("z3", "cvc5")):
        pytest.skip("native solver pair unavailable")
    from ipfs_datasets_py.logic.software_contracts import codebase_applicability as applicability
    from ipfs_datasets_py.logic.software_verification.applicability import RequestedInputDomain
    applicability._EXTRA_PINS.clear()
    _, index, repository, head, _, contract, owner, _, _ = prepared
    (repository / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 1\n")
    head = index.prepare_current(repository, repository_id=head.repository_id, operation_id="typed-domain", expected_head=head, scheduler=owner).head
    parent = verifier.verify_current_codebase_unit(index, repository, expected_head=head,
        path="counter.py", contracts=[contract], scheduler=owner)
    domain = RequestedInputDomain("increment", predicates, domain_id)
    record = applicability.verify_current_codebase_applicability(index, repository, expected_head=head,
        verification_cid=parent.artifact_cid, domains=[domain], scheduler=owner)
    return head, parent, record, domain


def test_native_linked_domain_keys_and_distinct_authored_lowered_contracts(prepared, monkeypatch):
    head, parent, applicability, domain = typed_applicability(prepared)
    projected = publish(prepared, expected_head=head, verification_cid=parent.artifact_cid,
                        applicability_cid=applicability.artifact_cid)
    assert projected.applicability is not None and projected.applicability.observed_live is False
    assert projected.applicability.model_applicability_established
    value = projected.to_dict()
    contract = value["contracts"][0]
    assert contract["contract_cid"] == cid_for_structured(prepared[5].to_dict())
    assert contract["lowered_contract_cid"] == applicability.to_dict()["contract_results"][0]["contract_cid"]
    assert contract["contract_cid"] != contract["lowered_contract_cid"]
    assert contract["domain_id"] == domain.domain_id and contract["domain_cid"] == cid_for_structured(domain.to_dict())
    assert len(contract["canonical_keys"]) == 1 and len(contract["applicability_keys"]) == 4
    assert value["dependencies"]["requested_domains"] == [domain.to_dict()]
    original = subprocess.run
    def git_only(args, *a, **kw):
        assert args[0] == "git"
        return original(args, *a, **kw)
    monkeypatch.setattr(subprocess, "run", git_only)
    rows = lookup(prepared, expected_head=head, domain_id=domain.domain_id,
        expected_domain_cid=cid_for_structured(domain.to_dict()),
        expected_contract_cid=contract["contract_cid"], expected_key_id=contract["applicability_keys"][0]["key_id"])
    assert len(rows) == 1 and rows[0].applicability.conditional_proved
    assert rows[0].applicability.to_dict() == applicability.to_dict()
    assert lookup(prepared, expected_head=head, expected_contract_cid=contract["lowered_contract_cid"]) == ()


def test_reused_logical_domain_id_requires_exact_domain_content_identity(prepared):
    from ipfs_datasets_py.logic.software_contracts import codebase_applicability as applicability
    from ipfs_datasets_py.logic.software_verification.applicability import RequestedInputDomain
    head, parent, first, domain = typed_applicability(prepared, predicates=("n >= 0",))
    publish(prepared, expected_head=head, verification_cid=parent.artifact_cid, applicability_cid=first.artifact_cid)
    _, index, repository, _, _, _, owner, _, _ = prepared
    changed = RequestedInputDomain("increment", ("n >= 10",), domain.domain_id)
    assert lookup(prepared, expected_head=head, domain_id=domain.domain_id,
                  expected_domain_cid=cid_for_structured(changed.to_dict())) == ()
    second = applicability.verify_current_codebase_applicability(index, repository, expected_head=head,
        verification_cid=parent.artifact_cid, domains=[changed], scheduler=owner)
    publish(prepared, expected_head=head, verification_cid=parent.artifact_cid,
            applicability_cid=second.artifact_cid, operation_id="changed-domain")
    assert len(lookup(prepared, expected_head=head, domain_id=domain.domain_id)) == 2
    rows = lookup(prepared, expected_head=head, domain_id=domain.domain_id,
                  expected_domain_cid=cid_for_structured(changed.to_dict()), limit=1)
    assert len(rows) == 1 and rows[0].applicability.artifact_cid == second.artifact_cid


def test_linked_applicability_rejects_other_verification_and_missing_cas(prepared):
    head, parent, applicability, _ = typed_applicability(prepared)
    _, index, repository, _, _, _, owner, connection, _ = prepared
    other = verifier.verify_current_codebase_unit(index, repository, expected_head=head,
        path="counter.py", contracts=[ContractSpec("increment", postconditions=("result == n + 2",))], scheduler=owner)
    with pytest.raises(module.CodebaseVerificationCatalogError, match="exact verification/source"):
        publish(prepared, expected_head=head, verification_cid=other.artifact_cid, applicability_cid=applicability.artifact_cid)
    assert connection.execute("SELECT count(*) FROM codebase_verification_control.records").fetchone()[0] == 0
    publish(prepared, expected_head=head, verification_cid=parent.artifact_cid, applicability_cid=applicability.artifact_cid)
    index.artifacts.path_for(applicability.artifact_cid).unlink()
    with pytest.raises(module.CodebaseVerificationCatalogError):
        lookup(prepared, expected_head=head)


def test_publication_rolls_back_on_cancellation_inside_transaction(prepared, monkeypatch):
    catalog, _, _, _, _, _, owner, connection, _ = prepared
    cancelled = threading.Event()
    original = catalog._entry_rows
    def cancel_at_insert(projection):
        rows = original(projection)
        cancelled.set()
        return rows
    monkeypatch.setattr(catalog, "_entry_rows", cancel_at_insert)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError
    with pytest.raises(LeaseCancelledError):
        publish(prepared, cancel_event=cancelled)
    assert connection.execute("SELECT count(*) FROM codebase_verification_control.records").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM codebase_verification_control.entries").fetchone()[0] == 0
    assert owner.snapshot()["active_lease_count"] == 0


def test_final_source_observation_rejects_edit_after_sql_commit(prepared, monkeypatch):
    catalog, index, repository, _, _, _, _, connection, _ = prepared
    original = index.observe_current
    observations = []
    def observe_then_edit(*args, **kwargs):
        result = original(*args, **kwargs)
        observations.append(result)
        if len(observations) == 2:
            (repository / "counter.py").write_text("# changed after precommit observation\n")
        return result
    monkeypatch.setattr(index, "observe_current", observe_then_edit)
    with pytest.raises(StaleCodebaseError):
        publish(prepared)
    assert connection.execute("SELECT count(*) FROM codebase_verification_control.records").fetchone()[0] == 1
    with pytest.raises(StaleCodebaseError):
        lookup(prepared)


def test_lookup_final_observation_rejects_edit_after_native_artifact_replay(prepared, monkeypatch):
    publish(prepared)
    catalog, _, repository, _, _, _, _, _, _ = prepared
    original = catalog._read
    def replay_then_edit(identity):
        record = original(identity)
        (repository / "counter.py").write_text("# source drift during exact lookup\n")
        return record
    monkeypatch.setattr(catalog, "_read", replay_then_edit)
    with pytest.raises(StaleCodebaseError):
        lookup(prepared)


@pytest.mark.parametrize("options", [{"limit": True}, {"limit": 0}, {"path": "../counter.py"},
    {"timeout_seconds": True}, {"admission_timeout_seconds": float("nan")}, {"memory_mb": True}])
def test_invalid_lookup_controls_fail_closed(prepared, options):
    with pytest.raises(module.CodebaseVerificationCatalogError):
        lookup(prepared, **options)


def test_limits_reject_bool_and_no_current_owner_can_be_substituted(prepared):
    with pytest.raises(module.CodebaseVerificationCatalogError):
        module.CodebaseVerificationCatalogLimits(max_records=True)
    with pytest.raises(module.CodebaseVerificationCatalogError):
        module.CodebaseVerificationCatalog(RepositoryCodebaseIndex())
    prepared[1].catalog = None
    with pytest.raises(module.CodebaseVerificationCatalogError):
        lookup(prepared)
