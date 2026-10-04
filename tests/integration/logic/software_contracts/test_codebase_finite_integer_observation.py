"""Independent native execution and integrity checks for finite observations.

These are authored qualification inputs. The Lean result certifies the saved
finite table, and no test treats it as a theorem about all Python execution.
"""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import threading

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_finite_integer_observation as observation
from ipfs_datasets_py.logic.software_contracts.cache import CacheIntegrityError
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract
from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes, cid_for_bytes, cid_for_structured,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    LeaseCancelledError, LeaseTimeoutError,
)
from .test_codebase_current import current_index, scheduler, git


INPUTS = [-2, -1, 0, 1, 2]
VIEW = "repository:finite-observation-independent"
PYTHON = Path("/home/barberb/.local/bin/python").resolve()
LEAN = Path("/home/barberb/.elan/toolchains/leanprover--lean4---v4.34.1/bin/lean")
FALSE_FIELDS = (
    "source_semantics_verified", "runtime_behavior_verified", "behavior_authority",
    "proof_authority", "execution_authority", "completion_authority", "mutation_authority",
)


def _source(offset=1):
    return f"def increment(n: int) -> int:\n    return n + {offset}\n".encode()


@pytest.fixture(scope="module")
def tools():
    for executable in (PYTHON, LEAN):
        assert executable.is_file(), f"required native tool unavailable: {executable}"
        assert executable.read_bytes()[:4] == b"\x7fELF"
    return observation.seal_finite_integer_tools(python_executable=PYTHON, lean_executable=LEAN)


@pytest.fixture
def prepared(tmp_path, current_index, scheduler):
    repository = tmp_path / "source"
    repository.mkdir()
    git(repository, "init", "-q")
    git(repository, "config", "user.name", "Finite Observation Fixture")
    git(repository, "config", "user.email", "fixture@example.invalid")
    (repository / "calc.py").write_bytes(_source())
    git(repository, "add", "calc.py")
    git(repository, "commit", "-qm", "authored finite source")
    index, connection, _ = current_index
    owner, _, _ = scheduler
    head = index.prepare_current(repository, repository_id=VIEW, operation_id="initial", expected_head=None, scheduler=owner).head
    return {"index": index, "repository": repository, "expected_head": head,
            "scheduler": owner, "output": tmp_path / "observation", "connection": connection}


def _observe(prepared, tools, **changes):
    arguments = {key: value for key, value in prepared.items() if key != "connection"}
    arguments.update(contract=IntegerOffsetContract("calc.py", "increment", "n", 2),
                     inputs=list(INPUTS), tool_policy=deepcopy(tools), timeout_seconds=30)
    arguments.update(changes)
    return observation.observe_finite_integer_source(**arguments)


def _validate(result, prepared, tools, **changes):
    arguments = {"expected_head": prepared["expected_head"],
                 "contract": IntegerOffsetContract("calc.py", "increment", "n", 2),
                 "inputs": list(INPUTS), "tool_policy": deepcopy(tools)}
    arguments.update(changes)
    return observation.validate_finite_integer_observation(result, **arguments)


def _assert_no_broad_authority(result):
    assert all(result[field] is False for field in FALSE_FIELDS)
    assert "finite" in result["scope"].lower()
    assert "universal" in result["scope"].lower()


def test_actual_python_and_lean_cover_exact_domain_without_universal_authority(prepared, tools):
    result = _observe(prepared, tools)
    assert result["status"] == "observed", result
    assert result["type_clause_satisfied"] is True
    assert result["offset_clause_satisfied"] is False
    assert result["runtime_observation_coverage_complete"] is True
    assert result["kernel_checked_model_table"] is True
    assert result["domain_inputs"] == INPUTS
    assert result["observations"] == [
        {"input": value, "output": value + 1, "input_type": "int", "output_type": "int"}
        for value in INPUTS
    ]
    assert result["counterexample"] == {"input": -2, "observed_output": -1, "required_output": 0}
    assert result["python_process"]["command"] == [str(PYTHON), "-I", "-S", "driver.py"]
    assert result["python_process"]["returncode"] == 0
    certificate = result["lean_certificate"]
    assert certificate["process"]["returncode"] == 0
    assert certificate["process"]["command"][0] == str(LEAN)
    assert "offset_counterexample" in certificate["theorems"]
    assert certificate["olean_cid"] == result["artifacts"]["lean_olean"]["cid"]
    assert result["source_sha256"] == hashlib.sha256(_source()).hexdigest()
    assert result["source_cid"] == cid_for_bytes(_source())
    body = {key: value for key, value in result.items() if key != "result_cid"}
    assert result["result_cid"] == cid_for_structured(body)
    assert prepared["index"].artifacts.get(cid_for_structured(result)) == result
    assert _validate(result, prepared, tools) == result
    for artifact in result["artifacts"].values():
        raw = Path(artifact["path"]).read_bytes()
        assert artifact["sha256"] == hashlib.sha256(raw).hexdigest()
        assert artifact["size_bytes"] == len(raw)
        assert artifact["cid"] == cid_for_bytes(raw)
    _assert_no_broad_authority(result)
    assert prepared["index"].current(VIEW) == prepared["expected_head"]


def test_same_head_edit_refuses_old_generation_then_real_successor_satisfies_finite_clauses(prepared, tools):
    original_head = prepared["expected_head"]
    commit = git(prepared["repository"], "rev-parse", "HEAD")
    (prepared["repository"] / "calc.py").write_bytes(_source(2))
    assert git(prepared["repository"], "rev-parse", "HEAD") == commit
    with pytest.raises(StaleCodebaseError):
        _observe(prepared, tools)
    successor = prepared["index"].prepare_current(
        prepared["repository"], repository_id=VIEW, operation_id="successor",
        expected_head=original_head, scheduler=prepared["scheduler"],
    ).head
    prepared["expected_head"] = successor
    result = _observe(prepared, tools)
    assert result["status"] == "observed"
    assert result["type_clause_satisfied"] is result["offset_clause_satisfied"] is True
    assert result["counterexample"] is None
    assert all(row["output"] == row["input"] + 2 for row in result["observations"])
    assert "offset_clause" in result["lean_certificate"]["theorems"]
    assert successor.generation == original_head.generation + 1
    _assert_no_broad_authority(result)


@pytest.mark.parametrize("inputs", [[], [-2, -1, 0, 1, 1], [0, -1], [False], [0.0], (0, 1), [2**31 + 1], list(range(33))])
def test_invalid_domain_is_rejected_before_native_execution(prepared, tools, monkeypatch, inputs):
    monkeypatch.setattr(observation.BoundedToolRunner, "run", lambda *args, **kwargs: pytest.fail("invalid domain executed a tool"))
    with pytest.raises(observation.FiniteIntegerObservationError, match="inputs|integer"):
        _observe(prepared, tools, inputs=inputs)
    assert not prepared["output"].exists()


def test_public_domain_constructor_detaches_inputs_and_has_exact_identity():
    inputs = list(INPUTS)
    domain = observation.build_finite_integer_domain(inputs)
    inputs.append(3)
    assert domain["inputs"] == INPUTS
    domain["inputs"].append(9)
    assert observation.build_finite_integer_domain(list(INPUTS))["inputs"] == INPUTS


@pytest.mark.parametrize("damage", ["python_hash", "lean_hash", "extra", "environment", "relative_path"])
def test_resealed_wrong_native_tool_policy_is_refused_before_process(prepared, tools, monkeypatch, damage):
    policy = deepcopy(tools)
    if damage in {"python_hash", "lean_hash"}:
        policy[damage.split("_")[0]]["sha256"] = "0" * 64
    elif damage == "extra":
        policy["caller_approved"] = True
    elif damage == "environment":
        policy["environment"]["PYTHONPATH"] = str(prepared["repository"])
    else:
        policy["python"]["path"] = "python3.12"
    policy["policy_cid"] = cid_for_structured({key: value for key, value in policy.items() if key != "policy_cid"})
    monkeypatch.setattr(observation.BoundedToolRunner, "run", lambda *args, **kwargs: pytest.fail("wrong binary policy executed"))
    with pytest.raises((observation.FiniteIntegerObservationError, FileNotFoundError)):
        _observe(prepared, tools, tool_policy=policy)


@pytest.mark.parametrize("source", [
    b"def increment(n):\n    return n + 1\n",
    b"def increment(n: int) -> int:\n    return n / 2\n",
    b"def increment(n: int) -> int:\n    return abs(n)\n",
    b"def increment(n: int = __import__('os').getpid()) -> int:\n    return n + 1\n",
    b"raise AssertionError('source executed')\ndef increment(n: int) -> int:\n    return n + 1\n",
])
def test_unsupported_source_effects_never_execute_python_or_lean(prepared, tools, monkeypatch, source):
    (prepared["repository"] / "calc.py").write_bytes(source)
    prepared["expected_head"] = prepared["index"].prepare_current(
        prepared["repository"], repository_id=VIEW, operation_id="unsupported",
        expected_head=prepared["expected_head"], scheduler=prepared["scheduler"],
    ).head
    monkeypatch.setattr(observation.BoundedToolRunner, "run", lambda *args, **kwargs: pytest.fail("unsupported source executed"))
    result = _observe(prepared, tools)
    assert result["status"] == "unsupported"
    assert result["python_process"] is result["lean_certificate"] is None
    assert result["type_clause_satisfied"] is result["runtime_observation_coverage_complete"] is False
    _assert_no_broad_authority(result)


@pytest.mark.parametrize("damage", ["missing", "duplicate", "bool_input", "source", "domain", "extra", "wrong_output"])
def test_forged_native_trace_cannot_create_eligible_finite_result(prepared, tools, monkeypatch, damage):
    native = observation.BoundedToolRunner.run
    def intercept(self, command, **options):
        raw = native(self, command, **options)
        if "driver.py" not in command:
            return raw
        trace = json.loads(raw.stdout)
        if damage == "missing":
            trace["observations"].pop()
        elif damage == "duplicate":
            trace["observations"][-1] = trace["observations"][0]
        elif damage == "bool_input":
            trace["observations"][2]["input"] = False
        elif damage == "source":
            trace["source_cid"] = cid_for_bytes(b"foreign source")
        elif damage == "domain":
            trace["domain_cid"] = cid_for_structured({"inputs": [0]})
        elif damage == "extra":
            trace["behavior_authority"] = True
        else:
            for row in trace["observations"]:
                row["output"] = row["input"] + 2
        return replace(raw, stdout=json.dumps(trace, sort_keys=True, separators=(",", ":")))
    monkeypatch.setattr(observation.BoundedToolRunner, "run", intercept)
    result = _observe(prepared, tools)
    assert result["status"] in {"python_failed", "lean_failed"}
    assert result["type_clause_satisfied"] is result["offset_clause_satisfied"] is False
    assert result["runtime_observation_coverage_complete"] is result["kernel_checked_model_table"] is False
    _assert_no_broad_authority(result)


@pytest.mark.parametrize("stage", ["python", "receipt"])
def test_source_mutation_during_observation_or_cas_seal_withholds_result(prepared, tools, monkeypatch, stage):
    if stage == "python":
        native = observation.BoundedToolRunner.run
        def intercept(self, command, **options):
            raw = native(self, command, **options)
            if "driver.py" in command:
                (prepared["repository"] / "calc.py").write_bytes(_source(2))
            return raw
        monkeypatch.setattr(observation.BoundedToolRunner, "run", intercept)
    else:
        native = prepared["index"].artifacts.put
        def intercept(value):
            cid = native(value)
            if value.get("schema") == observation.SCHEMA:
                (prepared["repository"] / "calc.py").write_bytes(_source(2))
            return cid
        monkeypatch.setattr(prepared["index"].artifacts, "put", intercept)
    with pytest.raises(StaleCodebaseError):
        _observe(prepared, tools)
    assert prepared["index"].current(VIEW) == prepared["expected_head"]


def test_corrupted_captured_source_cas_cannot_be_executed(prepared, tools, monkeypatch):
    manifest = prepared["index"].load(prepared["expected_head"].manifest_cid)
    source = next(entry for entry in manifest.snapshot.entries if entry.path == "calc.py")
    prepared["index"].artifacts.path_for(source.source_cid, source=True).write_bytes(_source(99))
    monkeypatch.setattr(observation.BoundedToolRunner, "run", lambda *args, **kwargs: pytest.fail("corrupted source executed"))
    with pytest.raises(CacheIntegrityError):
        _observe(prepared, tools)


def test_same_bytes_successor_generation_does_not_reauthorize_old_owner_head(prepared, tools, monkeypatch):
    old = prepared["expected_head"]
    newer = prepared["index"].prepare_current(prepared["repository"], repository_id=VIEW,
        operation_id="same-source-new-generation", expected_head=old, scheduler=prepared["scheduler"]).head
    assert newer.snapshot_cid == old.snapshot_cid
    assert newer.generation == old.generation + 1
    monkeypatch.setattr(observation.BoundedToolRunner, "run", lambda *args, **kwargs: pytest.fail("stale catalog head executed"))
    with pytest.raises(StaleCodebaseError):
        _observe(prepared, tools)
    assert prepared["index"].current(VIEW) == newer


def test_current_bottle_module_is_explicitly_unsupported_and_never_executed(prepared, tools, monkeypatch):
    bottle = Path("/home/barberb/lift_coding/artifacts/codebase_ir_terminal_bench/qualification-20261001-04/supervisor/repository/bottle.py")
    assert bottle.is_file(), "the exact retained public Bottle capture must be available"
    raw = bottle.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "761756ce31753e526c48d28ccbca13a5d2493b16fe37aff3e1e4d2efaf3a2bba"
    (prepared["repository"] / "calc.py").write_bytes(raw)
    prepared["expected_head"] = prepared["index"].prepare_current(prepared["repository"], repository_id=VIEW,
        operation_id="unsupported-public-bottle", expected_head=prepared["expected_head"], scheduler=prepared["scheduler"]).head
    monkeypatch.setattr(observation.BoundedToolRunner, "run", lambda *args, **kwargs: pytest.fail("Bottle executed"))
    result = _observe(prepared, tools)
    assert result["status"] == "unsupported"
    assert result["observations"] == []
    assert result["type_clause_satisfied"] is result["offset_clause_satisfied"] is False
    _assert_no_broad_authority(result)


@pytest.mark.parametrize("mode", ["cancelled", "deadline"])
def test_cancellation_and_expired_budget_prevent_processes_and_release_leases(prepared, tools, monkeypatch, mode):
    monkeypatch.setattr(observation.BoundedToolRunner, "run", lambda *args, **kwargs: pytest.fail("expired work executed"))
    changes = {}
    if mode == "cancelled":
        event = threading.Event()
        event.set()
        changes["cancel_event"] = event
    else:
        changes["timeout_seconds"] = 1e-9
    with pytest.raises((LeaseCancelledError, LeaseTimeoutError)):
        _observe(prepared, tools, **changes)
    assert prepared["scheduler"].snapshot()["active_lease_count"] == 0


@pytest.mark.parametrize("damage", ["domain", "contract", "authority", "trace", "artifact"])
def test_completed_record_validator_refuses_forged_bindings_and_artifact_bytes(prepared, tools, damage):
    result = _observe(prepared, tools)
    if damage == "domain":
        with pytest.raises(observation.FiniteIntegerObservationError):
            _validate(result, prepared, tools, inputs=[-1, 0, 1])
        return
    if damage == "contract":
        with pytest.raises(observation.FiniteIntegerObservationError):
            _validate(result, prepared, tools, contract=IntegerOffsetContract("calc.py", "increment", "n", 1))
        return
    if damage == "artifact":
        Path(result["artifacts"]["lean_olean"]["path"]).write_bytes(b"forged compiled Lean artifact")
    else:
        result["behavior_authority"] = True if damage == "authority" else result["behavior_authority"]
        if damage == "trace":
            result["observations"].pop()
        result["result_cid"] = cid_for_structured({key: value for key, value in result.items() if key != "result_cid"})
        Path(result["output"], "result.json").write_bytes(canonical_dag_json_bytes(result))
    with pytest.raises(observation.FiniteIntegerObservationError):
        _validate(result, prepared, tools)
