"""Real native SMT, exact-source replay and stale-head qualification of the bridge."""

import shutil
import subprocess
import sys
import threading

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_verification as module
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex, StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers


@pytest.fixture
def prepared(tmp_path):
    # Independent adversarial tests patch private audit hooks. Production pins
    # retain first-use identities; each test begins a fresh logical process.
    module._IMPORTED_SOURCE_PINS.clear()
    duckdb = pytest.importorskip("duckdb")
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    repository = tmp_path / "source"
    repository.mkdir()
    source = repository / "counter.py"
    source.write_text("def increment(n: int) -> int:\n    return n + 1\n", encoding="utf-8")
    for arguments in (("init", "-q"), ("config", "user.name", "Bridge Fixture"),
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
    publication = index.prepare_current(repository, repository_id="repository:verification-fixture",
        operation_id="initial", expected_head=None, scheduler=owner)
    yield index, repository, publication.head, owner, connection
    assert owner.snapshot()["active_lease_count"] == 0
    connection.close()


@pytest.fixture
def native_solvers():
    for name in ("z3", "cvc5"):
        if shutil.which(name) is None:
            pytest.skip(f"real {name} executable unavailable")


def verify(prepared, **kwargs):
    index, repository, head, owner, _ = prepared
    options = dict(expected_head=head, path="counter.py", scheduler=owner,
        contracts=[ContractSpec("increment", postconditions=("result == n + 1",))])
    options.update(kwargs)
    return module.verify_current_codebase_unit(index, repository, **options)


def count_rows(connection):
    return connection.execute("SELECT generation, manifest_cid FROM codebase_control.heads").fetchall()


def test_real_native_pair_seals_full_source_bound_evidence_and_readonly_history(prepared, native_solvers):
    index, repository, head, _, connection = prepared
    before = count_rows(connection)
    record = verify(prepared)
    assert record.observed_live and record.conditional_proved and not record.conditional_disproved
    payload = record.to_dict()
    assert payload["execution_stage"] == "native_smt"
    assert payload["pipeline"]["include_supervisor_evidence"] is False
    assert payload["pipeline_result"]["adapter"]["evidence"] is None
    assert payload["source_binding"]["source_revision"] == "snapshot:" + head.snapshot_cid
    assert payload["fence"]["before"] == payload["fence"]["after"] == head.to_dict()
    assert len(payload["solver_artifacts"]) == len(payload["canonical_keys"]) == 1
    assert len(payload["process_observations"]) == 2
    assert payload["schema"] == "codebase-conditional-verification@2"
    assert all(item["returncode"] == 0 and "unsat" in item["stdout"] for item in payload["process_observations"])
    for item in payload["process_observations"]:
        execution = item["execution"]
        assert execution["status"] == "completed"
        assert [phase["kind"] for phase in execution["phases"]] == ["version", "verdict", "unsat_core"]
        assert all(phase["returncode"] == 0 and phase["workspace_cleaned"] is True
                   and not phase["cancelled"] and not phase["resource_exhausted"] for phase in execution["phases"])
        assert execution["policy"]["historical_execution_attested"] is False
    assert all(item["solver_version"] for item in payload["process_observations"])
    artifact = payload["solver_artifacts"][0]
    assert artifact["compilation"]["smtlib"].endswith("\n")
    assert artifact["compilation"]["receipt"]["receipt_id"]
    assert payload["post_contract_program"]["program_id"] == payload["pipeline_result"]["program_id"]
    assert payload["post_contract_program"] != payload["pipeline_result"]["adapter"]["program"]
    assert payload["coverage"]["complete_repository_verification"] is False
    assert payload["authority"]["conditional_model_evidence"] is True
    assert all(value is False for name, value in payload["authority"].items() if name != "conditional_model_evidence")
    loaded = module.load_codebase_verification(index, record.artifact_cid)
    assert not loaded.observed_live and loaded.to_dict() == payload
    assert count_rows(connection) == before
    # Returned views do not mutate the immutable record or its stored artifact.
    payload["authority"]["kernel_checked"] = True
    assert record.to_dict()["authority"]["kernel_checked"] is False
    (repository / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 2\n")
    assert module.load_codebase_verification(index, record.artifact_cid).to_dict() == loaded.to_dict()
    with pytest.raises(StaleCodebaseError):
        verify(prepared)


def test_real_counterexample_remains_conditional(prepared, native_solvers):
    record = verify(prepared, contracts=[ContractSpec("increment", postconditions=("result == n + 2",))])
    assert record.conditional_disproved and not record.conditional_proved
    assert all(item["returncode"] in {0, 1} and "sat" in item["stdout"] for item in record.to_dict()["process_observations"])
    assert record.to_dict()["authority"]["behavioral_satisfaction"] is False


def test_real_boolean_and_unicode_source_uses_native_typed_profile(prepared, native_solvers):
    index, repository, head, owner, _ = prepared
    (repository / "counter.py").write_text("# café λ\ndef positive(n: int) -> bool:\n    return n > 0\n", encoding="utf-8")
    publication = index.prepare_current(repository, repository_id=head.repository_id,
        operation_id="boolean", expected_head=head, scheduler=owner)
    record = verify(prepared, expected_head=publication.head,
                    contracts=[ContractSpec("positive", postconditions=("result == (n > 0)",))])
    assert record.conditional_proved
    assert module.load_codebase_verification(index, record.artifact_cid).conditional_proved


def test_two_contracts_for_one_function_preserve_independent_native_outcomes(prepared, native_solvers):
    record = verify(prepared, contracts=[
        ContractSpec("increment", postconditions=("result == n + 1",), contract_id="correct"),
        ContractSpec("increment", postconditions=("result == n + 2",), contract_id="incorrect"),
    ])
    assert record.conditional_disproved and not record.conditional_proved
    payload = record.to_dict()
    assert len(payload["solver_artifacts"]) == len(payload["canonical_keys"]) == 2
    assert len(payload["process_observations"]) == 4
    assert [item["verdict_classification"] for item in payload["pipeline_result"]["obligation_results"]] == [
        "agree_proved", "agree_disproved"]
    assert module.load_codebase_verification(prepared[0], record.artifact_cid).to_dict() == payload


@pytest.mark.parametrize("source", [
    "def increment(n: float) -> float:\n    return n + 1\n",
    "def increment(n: int) -> int:\n    return n // 2\n",
    "def increment(n: int) -> int:\n    return n * n\n",
])
def test_unsupported_translation_is_source_bound_and_launches_no_solver(prepared, monkeypatch, source):
    index, repository, head, owner, _ = prepared
    (repository / "counter.py").write_text(source)
    publication = index.prepare_current(repository, repository_id=head.repository_id,
        operation_id="unsupported", expected_head=head, scheduler=owner)
    monkeypatch.setattr(module, "_native_backends", lambda *args: pytest.fail("unsupported source launched solvers"))
    record = verify(prepared, expected_head=publication.head)
    payload = record.to_dict()
    assert payload["execution_stage"] == "translation_rejected"
    assert payload["pipeline_result"]["status"] == "unsupported"
    assert not record.conditional_proved and not record.conditional_disproved
    assert payload["process_observations"] == payload["canonical_keys"] == []
    assert module.load_codebase_verification(index, record.artifact_cid).to_dict() == payload


def test_mutation_after_real_solver_pair_cannot_publish_current_completion(prepared, native_solvers, monkeypatch):
    original = module._native_backends
    def real_then_mutate(compiler, observations, checkpoint, **execution):
        left, right, pins = original(compiler, observations, checkpoint, **execution)
        runner = right._runner
        def mutate(smtlib, bounds):
            result = runner(smtlib, bounds)
            (prepared[1] / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 9\n")
            return result
        right._runner = mutate
        return left, right, pins
    monkeypatch.setattr(module, "_native_backends", real_then_mutate)
    with pytest.raises(StaleCodebaseError, match="repository differs"):
        verify(prepared)
    assert prepared[0].current(prepared[2].repository_id) == prepared[2]


def test_source_edit_during_cas_publication_is_caught_by_final_reobservation(prepared, native_solvers, monkeypatch):
    original = prepared[0].artifacts.put
    published = []
    def publish_then_edit(value):
        cid = original(value)
        if value.get("schema") == module.CODEBASE_VERIFICATION_SCHEMA:
            published.append(cid)
            (prepared[1] / "counter.py").write_text("def increment(n: int) -> int:\n    return n - 1\n")
        return cid
    monkeypatch.setattr(prepared[0].artifacts, "put", publish_then_edit)
    with pytest.raises(StaleCodebaseError, match="repository differs"):
        verify(prepared)
    assert len(published) == 1
    assert not module.load_codebase_verification(prepared[0], published[0]).observed_live


def test_same_snapshot_new_head_during_execution_fails_full_head_fence(prepared, native_solvers, monkeypatch):
    original = module._native_backends
    def real_then_advance(compiler, observations, checkpoint, **execution):
        left, right, pins = original(compiler, observations, checkpoint, **execution)
        runner = right._runner
        def advance(smtlib, bounds):
            result = runner(smtlib, bounds)
            prepared[0].prepare_current(prepared[1], repository_id=prepared[2].repository_id,
                operation_id="advance", expected_head=prepared[2], scheduler=prepared[3])
            return result
        right._runner = advance
        return left, right, pins
    monkeypatch.setattr(module, "_native_backends", real_then_advance)
    with pytest.raises(StaleCodebaseError, match="catalog head"):
        verify(prepared)
    assert prepared[0].current(prepared[2].repository_id).generation == prepared[2].generation + 1


@pytest.mark.parametrize("option", [
    {"path": "../counter.py"}, {"path": "./counter.py"}, {"contracts": []},
    {"contracts": [{"function_name": "increment"}]}, {"timeout_seconds": True},
    {"admission_timeout_seconds": float("nan")}, {"admission_timeout_seconds": True},
    {"admission_timeout_seconds": -1},
    {"memory_mb": True}, {"bounds": {"timeout_ms": 1}},
    {"limits": module.CodebaseVerificationLimits(max_source_bytes=1)},
    {"bounds": ExecutionBounds(max_memory_bytes=1024 * 1024 * 1024)},
])
def test_invalid_or_oversized_inputs_do_not_launch_native_solvers(prepared, monkeypatch, option):
    monkeypatch.setattr(module, "_native_backends", lambda *args: pytest.fail("invalid input launched solvers"))
    with pytest.raises(module.CodebaseVerificationError):
        verify(prepared, **option)


def test_obligation_bound_checked_before_native_launch(prepared, monkeypatch):
    index, repository, head, owner, _ = prepared
    (repository / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 1\n\ndef decrement(n: int) -> int:\n    return n - 1\n")
    publication = index.prepare_current(repository, repository_id=head.repository_id,
        operation_id="two-functions", expected_head=head, scheduler=owner)
    monkeypatch.setattr(module, "_native_backends", lambda *args: pytest.fail("oversized VCs launched solvers"))
    with pytest.raises(module.CodebaseVerificationError, match="count exceeds"):
        verify(prepared, expected_head=publication.head, limits=module.CodebaseVerificationLimits(max_obligations=1),
               contracts=[ContractSpec("increment", postconditions=("result == n + 1",), contract_id="first"),
                          ContractSpec("decrement", postconditions=("result == n - 1",), contract_id="second")])


def test_duplicate_contract_identities_are_rejected_before_native_pipeline(prepared):
    with pytest.raises(module.CodebaseVerificationError, match="contract identities"):
        verify(prepared, contracts=[ContractSpec("increment", postconditions=("result == n + 1",), contract_id="first"),
                                   ContractSpec("increment", postconditions=("result > n",), contract_id="first")])


def test_nonrepresentable_float_native_metadata_fails_closed_before_solver(prepared, monkeypatch):
    index, repository, head, owner, _ = prepared
    (repository / "counter.py").write_text("def increment(n: float) -> float:\n    return n + 1.0\n")
    publication = index.prepare_current(repository, repository_id=head.repository_id,
        operation_id="float-literal", expected_head=head, scheduler=owner)
    monkeypatch.setattr(module, "_native_backends", lambda *args: pytest.fail("float metadata launched solver"))
    with pytest.raises(module.CodebaseVerificationError, match="CAS scalar"):
        verify(prepared, expected_head=publication.head)


def test_loaded_module_code_drift_cannot_be_pinned_to_unchanged_disk(prepared, monkeypatch):
    import types
    from ipfs_datasets_py.logic.software_verification import pipeline
    original = pipeline.SourceToVerificationPipeline.run
    changed = original.__code__.replace(co_consts=original.__code__.co_consts + ("drifted-loaded-code",))
    monkeypatch.setattr(pipeline.SourceToVerificationPipeline, "run", types.FunctionType(
        changed, original.__globals__, original.__name__, original.__defaults__, original.__closure__))
    with pytest.raises(module.CodebaseVerificationError, match="loaded verification code differs"):
        verify(prepared)


def test_record_rejects_mutable_alias_payload(prepared, native_solvers):
    record = verify(prepared)
    with pytest.raises(module.CodebaseVerificationError, match="immutable bytes"):
        module.CodebaseVerificationRecord(record.artifact_cid, bytearray(record._payload))


def test_owned_backends_disable_unrecorded_fallback_version_subprocess(prepared, native_solvers, monkeypatch):
    from ipfs_datasets_py.logic.backends.smt.compiler import SoftwareVerificationSMTCompiler
    import time
    from ipfs_datasets_py.logic.software_contracts.codebase_resources import acquire_codebase_resources
    with acquire_codebase_resources(scheduler=prepared[3]) as lease:
        left, right, _ = module._native_backends(SoftwareVerificationSMTCompiler(), [], lambda: None,
            parent_lease=lease, cancel_event=None, deadline=time.monotonic() + 10, max_script_bytes=262144)
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("unrecorded fallback version probe"))
        assert left.solver_version() == right.solver_version() == ""


def test_fresh_process_historical_loader_uses_no_subprocess_or_live_checkout(prepared, native_solvers):
    import json
    record = verify(prepared)
    (prepared[1] / "counter.py").unlink()
    script = '''
import json, subprocess, sys
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.codebase_verification import load_codebase_verification
def forbidden(*args, **kwargs):
    raise AssertionError("historical replay launched a process")
subprocess.run = forbidden
index = RepositoryCodebaseIndex(artifacts=ImmutableCAS(sys.argv[1]))
record = load_codebase_verification(index, sys.argv[2])
print(json.dumps({'cid': record.artifact_cid, 'observed_live': record.observed_live, 'conditional_proved': record.conditional_proved}))
'''
    run = subprocess.run([sys.executable, "-c", script, str(prepared[0].artifacts.root), record.artifact_cid],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout.splitlines()[-1]) == {
        "cid": record.artifact_cid, "observed_live": False, "conditional_proved": True}


def test_cancelled_admission_and_insufficient_execution_deadline_release_resources(prepared):
    event = threading.Event()
    event.set()
    with pytest.raises(schedulers.LeaseCancelledError):
        verify(prepared, cancel_event=event)
    with pytest.raises(schedulers.LeaseTimeoutError):
        verify(prepared, timeout_seconds=0.5)


@pytest.mark.parametrize("mutation", ["authority", "source", "key", "script", "receipt", "proved", "process", "bounds", "contracts", "coverage", "boolean_authority", "boolean_process_bounds", "module_generation"])
def test_historical_loader_rejects_readdressed_internal_binding_tampering(prepared, native_solvers, mutation):
    index = prepared[0]
    value = verify(prepared).to_dict()
    if mutation == "authority":
        value["authority"]["kernel_checked"] = True
    elif mutation == "source":
        value["source_binding"]["content_sha256"] = "0" * 64
    elif mutation == "key":
        value["canonical_keys"][0]["environment"] = "sha256:" + "0" * 64
    elif mutation == "script":
        value["solver_artifacts"][0]["compilation"]["script"]["lines"][-1] = "(check-sat)"
    elif mutation == "receipt":
        value["solver_artifacts"][0]["compilation"]["receipt"]["receipt_id"] = "sha256:" + "0" * 64
    elif mutation == "proved":
        value["pipeline_result"]["proved"] = False
    elif mutation == "process":
        value["process_observations"][0]["stdout"] = "sat\n"
    elif mutation == "bounds":
        value["effective_bounds"]["max_steps"] += 1
    elif mutation == "contracts":
        value["requested_contracts"][0]["postconditions"] = ["result == n + 2"]
    elif mutation == "coverage":
        value["coverage"]["complete_repository_verification"] = True
    elif mutation == "boolean_authority":
        value["authority"]["kernel_checked"] = 0
    elif mutation == "boolean_process_bounds":
        value["process_observations"][0]["bounds"]["max_steps"] = True
    else:
        value["environment"]["module_pins"][0]["sha256"] = "0" * 64
    cid = index.artifacts.put(value)
    with pytest.raises((module.CodebaseVerificationError, ValueError)):
        module.load_codebase_verification(index, cid)
