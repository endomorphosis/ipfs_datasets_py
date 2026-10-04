"""Real nonvacuity, domain coverage and requested-domain model qualification."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_applicability as module
from ipfs_datasets_py.logic.software_contracts import codebase_verification as bridge
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex, StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec
from ipfs_datasets_py.logic.software_verification.applicability import RequestedInputDomain
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


@pytest.fixture
def prepared(tmp_path):
    for solver in ("z3", "cvc5"):
        if shutil.which(solver) is None:
            pytest.skip(f"real {solver} executable unavailable")
    duckdb = pytest.importorskip("duckdb")
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    bridge._IMPORTED_SOURCE_PINS.clear()
    module._EXTRA_PINS.clear()
    repository = tmp_path / "source"
    repository.mkdir()
    (repository / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 1\n")
    for arguments in (("init", "-q"), ("config", "user.name", "Applicability Fixture"),
                      ("config", "user.email", "fixture@example.invalid"),
                      ("add", "."), ("commit", "-qm", "fixture")):
        subprocess.run(["git", "-C", str(repository), *arguments], check=True, capture_output=True)
    connection = duckdb.connect(str(tmp_path / "catalog.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    artifacts = ImmutableCAS(tmp_path / "artifacts")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
                                   catalog=CodebaseCatalog(store, artifacts))
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8,8192,8192),
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=0.005))
    head = index.prepare_current(repository, repository_id="repository:applicability-fixture",
        operation_id="initial", expected_head=None, scheduler=owner).head
    yield index, repository, head, owner, connection
    assert owner.snapshot()["active_lease_count"] == 0
    connection.close()


def parent(prepared, preconditions=(), postconditions=("result == n + 1",), contracts=None):
    index, repository, head, owner, _ = prepared
    return bridge.verify_current_codebase_unit(index, repository, expected_head=head, path="counter.py",
        contracts=contracts or [ContractSpec("increment", preconditions, postconditions)], scheduler=owner)


def verify(prepared, verification, predicates=("True",), **changes):
    index, repository, head, owner, _ = prepared
    options = dict(expected_head=head, verification_cid=verification.artifact_cid,
                   domains=[RequestedInputDomain("increment", predicates)], scheduler=owner)
    options.update(changes)
    return module.verify_current_codebase_applicability(index, repository, **options)


@pytest.mark.parametrize("premises,domain,status,classes,proved,refuted", [
    ((), ("True",), "established", ["agree_satisfiable", "agree_satisfiable", "agree_proved", "agree_proved"], True, False),
    (("n >= 0",), ("n >= 10",), "established", ["agree_satisfiable", "agree_satisfiable", "agree_proved", "agree_proved"], True, False),
    (("n > 0", "n < 0"), ("n >= 0",), "inconsistent_premises", ["agree_unsatisfiable", "agree_satisfiable", "agree_disproved", "agree_proved"], False, False),
    ((), ("False",), "empty_domain", ["agree_satisfiable", "agree_unsatisfiable", "agree_proved", "agree_proved"], False, False),
    (("n >= 0",), ("n < 0",), "domain_not_covered", ["agree_satisfiable", "agree_satisfiable", "agree_disproved", "agree_proved"], False, False),
])
def test_real_premise_domain_and_property_queries_are_independent(prepared, premises, domain, status, classes, proved, refuted):
    original = parent(prepared, preconditions=premises)
    record = verify(prepared, original, domain)
    value = record.to_dict()
    assert record.observed_live
    assert value["contract_results"][0]["status"] == status
    assert value["contract_results"][0]["classifications"] == classes
    assert record.conditional_proved is proved and record.conditional_refuted is refuted
    assert len(value["checks"]) == len(value["canonical_keys"]) == 4
    assert len(value["process_observations"]) == 8
    assert value["schema"] == "codebase-input-applicability@2"
    assert all(row["returncode"] == 0 and row["execution"]["status"] == "completed"
               for row in value["process_observations"])
    assert all(phase["workspace_cleaned"] is True and phase["returncode"] == 0
               for row in value["process_observations"] for phase in row["execution"]["phases"])
    assert [item["kind"] for item in value["checks"]] == [
        "premises_satisfiable", "domain_satisfiable", "domain_implies_preconditions", "property_on_requested_domain"]
    assert [item["compilation"]["query_mode"] for item in value["checks"]] == [
        "satisfiability", "satisfiability", "theorem_by_negation", "theorem_by_negation"]
    assert value["verification_cid"] == original.artifact_cid
    assert value["source_binding"] == original.to_dict()["source_binding"]
    assert all(value["authority"][name] is False for name in (
        "kernel_checked", "source_runtime_semantics_verified", "behavioral_satisfaction",
        "authoritative_cache_eligible", "admission_authority", "completion_authority"))
    loaded = module.load_codebase_applicability(prepared[0], record.artifact_cid)
    assert not loaded.observed_live and loaded.to_dict() == value


def test_parent_counterexample_outside_domain_does_not_refute_requested_domain(prepared):
    original = parent(prepared, postconditions=("result > 0",))
    assert original.conditional_disproved
    record = verify(prepared, original, ("n >= 0",))
    assert record.model_applicability_established and record.conditional_proved
    assert not record.conditional_refuted
    assert record.to_dict()["contract_results"][0]["domain_property_classification"] == "agree_proved"


def test_real_refutation_countermodel_is_within_requested_domain(prepared):
    original = parent(prepared, postconditions=("result > 0",))
    record = verify(prepared, original, ("n >= -1",))
    assert record.model_applicability_established and record.conditional_refuted
    assert not record.conditional_proved
    check = record.to_dict()["checks"][-1]
    assert check["differential"]["classification"] == "agree_disproved"
    assert all(check["differential"][side]["model_text"] for side in ("left", "right"))


def test_one_domain_is_reused_for_multiple_contracts_of_same_function(prepared):
    original = parent(prepared, contracts=[
        ContractSpec("increment", postconditions=("result == n + 1",), contract_id="correct"),
        ContractSpec("increment", postconditions=("result == n + 2",), contract_id="incorrect"),
    ])
    record = verify(prepared, original)
    value = record.to_dict()
    assert len(value["requested_domains"]) == 1 and len(value["checks"]) == 8
    assert len({item["domain_cid"] for item in value["contract_results"]}) == 1
    assert len({item["contract_cid"] for item in value["contract_results"]}) == 2
    assert [item["domain_property_classification"] for item in value["contract_results"]] == ["agree_proved", "agree_disproved"]
    assert record.conditional_refuted and not record.conditional_proved
    assert module.load_codebase_applicability(prepared[0], record.artifact_cid).to_dict() == value


@pytest.mark.parametrize("domain", ["result > 0", "unknown > 0", "n / 2 > 0", "n * n >= 0", "n"])
def test_unsupported_or_nonentry_domain_never_launches_checker(prepared, monkeypatch, domain):
    original = parent(prepared)
    monkeypatch.setattr(module, "_native_backends", lambda *args: pytest.fail("unsupported domain launched checker"))
    with pytest.raises(module.CodebaseApplicabilityError):
        verify(prepared, original, (domain,))


def test_poststate_precondition_cannot_be_relabelled_as_input_premise(prepared, monkeypatch):
    original = parent(prepared, preconditions=("result > n",))
    monkeypatch.setattr(module, "_native_backends", lambda *args: pytest.fail("poststate premise launched checker"))
    with pytest.raises(module.CodebaseApplicabilityError):
        verify(prepared, original)


@pytest.mark.parametrize("change", [
    {"domains": []}, {"domains": [{"function_name": "increment"}]},
    {"domains": [RequestedInputDomain("other")]},
    {"domains": [RequestedInputDomain("increment"), RequestedInputDomain("increment", ("n > 0",))]},
    {"timeout_seconds": True}, {"admission_timeout_seconds": float("nan")},
    {"memory_mb": True}, {"bounds": {"timeout_ms": 1}},
    {"bounds": ExecutionBounds(max_memory_bytes=1024 * 1024 * 1024)},
    {"limits": bridge.CodebaseVerificationLimits(max_obligations=3)},
    {"limits": bridge.CodebaseVerificationLimits(max_script_bytes=1)},
])
def test_invalid_or_oversized_request_stops_before_native_execution(prepared, monkeypatch, change):
    original = parent(prepared)
    monkeypatch.setattr(module, "_native_backends", lambda *args: pytest.fail("invalid applicability request launched checker"))
    with pytest.raises((module.CodebaseApplicabilityError, bridge.CodebaseVerificationError)):
        verify(prepared, original, **change)


def test_source_edit_after_actual_applicability_checks_cannot_return_current_result(prepared, monkeypatch):
    original = parent(prepared)
    backends = module._native_backends
    def real_then_edit(compiler, observations, checkpoint, **execution):
        left, right, pins = backends(compiler, observations, checkpoint, **execution)
        runner = right._runner
        def edited(smtlib, bounds):
            result = runner(smtlib, bounds)
            (prepared[1] / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 9\n")
            return result
        right._runner = edited
        return left, right, pins
    monkeypatch.setattr(module, "_native_backends", real_then_edit)
    with pytest.raises(StaleCodebaseError):
        verify(prepared, original)


def test_edit_during_applicability_cas_publication_is_fenced(prepared, monkeypatch):
    original = parent(prepared)
    put = prepared[0].artifacts.put
    published = []
    def mutate(value):
        cid = put(value)
        if value.get("schema") == module.CODEBASE_APPLICABILITY_SCHEMA:
            published.append(cid)
            (prepared[1] / "counter.py").unlink()
        return cid
    monkeypatch.setattr(prepared[0].artifacts, "put", mutate)
    with pytest.raises(StaleCodebaseError):
        verify(prepared, original)
    assert len(published) == 1
    assert not module.load_codebase_applicability(prepared[0], published[0]).observed_live


def test_historical_restart_never_executes_native_tools_or_asserts_live_source(prepared):
    record = verify(prepared, parent(prepared))
    (prepared[1] / "counter.py").unlink()
    script = '''
import json, subprocess, sys
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.codebase_applicability import load_codebase_applicability
def forbidden(*args, **kwargs):
    raise AssertionError("historical applicability replay launched tool")
subprocess.run = forbidden
record = load_codebase_applicability(RepositoryCodebaseIndex(artifacts=ImmutableCAS(sys.argv[1])), sys.argv[2])
print(json.dumps({'cid':record.artifact_cid, 'live':record.observed_live, 'proved':record.conditional_proved}))
'''
    result = subprocess.run([sys.executable, "-c", script, str(prepared[0].artifacts.root), record.artifact_cid],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {"cid": record.artifact_cid, "live": False, "proved": True}


def test_cancelled_or_insufficient_deadline_releases_admission(prepared):
    original = parent(prepared)
    event = threading.Event()
    event.set()
    with pytest.raises(schedulers.LeaseCancelledError):
        verify(prepared, original, cancel_event=event)
    with pytest.raises(schedulers.LeaseTimeoutError):
        verify(prepared, original, timeout_seconds=0.5)


@pytest.mark.parametrize("damage", ["authority", "domain", "verification", "raw", "summary", "key", "bounds", "module", "inventory"])
def test_readdressed_historical_tampering_is_rejected(prepared, damage):
    original = parent(prepared)
    value = verify(prepared, original).to_dict()
    if damage == "authority":
        value["authority"]["kernel_checked"] = 0
    elif damage == "domain":
        value["requested_domains"][0]["predicates"] = ["n < 0"]
    elif damage == "verification":
        value["verification_cid"] = prepared[2].manifest_cid
    elif damage == "raw":
        value["process_observations"][0]["stdout"] = "unsat\n"
    elif damage == "summary":
        value["conditional_proved"] = False
    elif damage == "key":
        value["canonical_keys"][0]["environment"] = "sha256:" + "0" * 64
    elif damage == "bounds":
        value["effective_bounds"]["max_steps"] += 1
    elif damage == "module":
        value["environment"]["module_pins"][-1]["sha256"] = "0" * 64
    else:
        value["checks"].pop()
    cid = prepared[0].artifacts.put(value)
    with pytest.raises((ValueError, TypeError)):
        module.load_codebase_applicability(prepared[0], cid)
