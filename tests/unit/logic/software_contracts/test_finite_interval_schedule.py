"""Authored finite scheduling instances and independent adversarial witnesses."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import itertools
import json
import shutil
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.software_contracts import finite_interval_schedule as p
from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured


CONTRACT = p.FiniteIntervalScheduleContract()


def encode(value):
    return json.dumps(value, separators=(",", ":")).encode()


def problem(*, capacity=1, windows=None, durations=(5, 5), horizon=10):
    return {"schema": p.INPUT_SCHEMA, "horizon_start": 0, "horizon_end": horizon,
        "resources": [{"id": "machine", "capacity": capacity,
                       "availability": windows if windows is not None else [[0, horizon]]}],
        "jobs": [{"id": f"job{index}", "resource": "machine", "duration": duration,
                  "release": 0, "deadline": horizon, "demand": 1}
                 for index, duration in enumerate(durations)]}


def witness(data, starts):
    return {"schema": p.OUTPUT_SCHEMA, "assignments": [
        {"id": row["id"], "start": start, "end": start + row["duration"]}
        for row, start in zip(data["jobs"], starts)]}


def checked(data=None, starts=(0, 5)):
    data = problem() if data is None else data
    source, output = encode(data), encode(witness(data, starts))
    return p.check_finite_interval_schedule(source, output, CONTRACT)


def rejected(call, reason=None):
    with pytest.raises(p.FiniteIntervalScheduleError) as error:
        call()
    if reason:
        assert error.value.reason_code == reason


def test_authored_boundary_touching_witness_bound_to_exact_bytes_and_policy():
    data = problem()
    source, output = encode(data), encode(witness(data, (0, 5)))
    receipt = p.check_finite_interval_schedule(source, output, CONTRACT)
    assert receipt["evidence_kind"] == "finite_schedule_check"
    assert receipt["status"] == "checked"
    assert receipt["job_count"] == 2 and receipt["resource_count"] == 1
    assert receipt["input_sha256"] == hashlib.sha256(source).hexdigest()
    assert receipt["output_sha256"] == hashlib.sha256(output).hexdigest()
    assert receipt["contract_cid"] == CONTRACT.cid
    assert receipt["receipt_cid"] == cid_for_structured({k: v for k, v in receipt.items() if k != "receipt_cid"})
    assert p.verify_finite_schedule_check(receipt, input_bytes=source, output_bytes=output, contract=CONTRACT) == receipt
    for key in ("semantic_alignment_verified", "kernel_checked", "optimality_verified", "proof_authority",
                "execution_authority", "publication_authority", "completion_authority"):
        assert receipt[key] is False


def test_checker_has_no_dependency_on_solver_compiler_or_candidate_serializer(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("checker called synthesis")
    monkeypatch.setattr(p, "solve_finite_interval_schedule", forbidden)
    monkeypatch.setattr(p, "_compile", forbidden)
    output = b'{ "schema": "finite-interval-schedule-witness@1", "assignments": [{"start":0,"end":5,"id":"job0"},{"id":"job1","end":10,"start":5}] }'
    assert p.check_finite_interval_schedule(encode(problem()), output, CONTRACT)["job_count"] == 2


@pytest.mark.parametrize("field,value", [("schema", "different"), ("objective", "optimal"),
    ("intervals", "closed"), ("preemption", "allowed"), ("bounds", {}), ("extra", False)])
def test_contract_policy_cannot_be_relaxed(field, value):
    body = CONTRACT.to_dict()
    body[field] = value
    rejected(lambda: p.FiniteIntervalScheduleContract.from_dict(body), "invalid_schedule_contract")


def test_exact_typed_contract_required():
    class Derived(p.FiniteIntervalScheduleContract):
        pass
    for contract in (None, {}, CONTRACT.to_dict(), Derived()):
        rejected(lambda: p.check_finite_interval_schedule(encode(problem()), b"{}", contract),
                 "typed_schedule_contract_required")
    assert p.FiniteIntervalScheduleContract.from_dict(CONTRACT.to_dict()) == CONTRACT


@pytest.mark.parametrize("raw", [b"", b"null", b"[]", b"true", b"{", b"{} {}", b"\xff", b"\xef\xbb\xbf{}",
    b'{"schema":1,"schema":2}', b'{"x":1e0}', b'{"x":1.0}', b'{"x":NaN}',
    b'{"x":-1}', b'{"x":1000000001}', b'{"x":99999999999999999999999999}',
    b'{"x":' + b"[" * 1000 + b"0" + b"]" * 1000 + b"}", b" " * (p.MAX_BYTES + 1)])
def test_malformed_or_unbounded_documents_are_rejected_before_solver(raw, monkeypatch):
    monkeypatch.setattr(p, "_backend", lambda **kwargs: pytest.fail("unsupported input reached solver"))
    rejected(lambda: p.solve_finite_interval_schedule(raw, CONTRACT))


@pytest.mark.parametrize("raw", [None, "{}", bytearray(b"{}"), memoryview(b"{}")])
def test_input_requires_exact_bytes(raw):
    rejected(lambda: p.compile_finite_interval_schedule(raw, CONTRACT), "exact_schedule_bytes_required")


@pytest.mark.parametrize("section,field,value", [
    ("root", "schema", "wrong"), ("root", "horizon_start", 10), ("root", "horizon_start", True),
    ("root", "horizon_end", 0), ("root", "horizon_end", 1_000_000_001), ("root", "resources", []),
    ("root", "jobs", []), ("root", "jobs", {}), ("root", "extra", 1),
    ("resource", "id", ""), ("resource", "id", "quoted | (exit)"), ("resource", "id", "é"),
    ("resource", "id", "a" * 65), ("resource", "capacity", 0), ("resource", "capacity", False),
    ("resource", "availability", []), ("resource", "availability", [[0, 0]]),
    ("resource", "availability", [[0, 11]]), ("resource", "availability", [[3, 8], [0, 3]]),
    ("resource", "availability", [[0, 6], [5, 10]]), ("resource", "availability", [[0, 5], [0, 5]]),
    ("resource", "availability", [[0, 2, 3]]), ("resource", "availability", [[False, 10]]),
    ("resource", "extra", 1), ("job", "id", "job\n0"), ("job", "resource", "missing"),
    ("job", "duration", 0), ("job", "duration", False), ("job", "demand", 0),
    ("job", "release", 11), ("job", "deadline", True), ("job", "deadline", 11),
    ("job", "extra", 1),
])
def test_closed_input_fields_and_integer_policy(section, field, value):
    data = problem()
    target = data if section == "root" else data["resources" if section == "resource" else "jobs"][0]
    target[field] = value
    rejected(lambda: p.compile_finite_interval_schedule(encode(data), CONTRACT))


def test_identity_and_cardinality_bounds():
    for category in ("jobs", "resources"):
        data = problem()
        data[category].append(deepcopy(data[category][0]))
        rejected(lambda: p.compile_finite_interval_schedule(encode(data), CONTRACT),
                 "duplicate_schedule_job" if category == "jobs" else "duplicate_schedule_resource")
    data = problem(durations=(1,) * 33, horizon=100)
    rejected(lambda: p.compile_finite_interval_schedule(encode(data), CONTRACT), "schedule_job_count_bound")
    data = problem()
    data["resources"] = [{"id": f"r{i}", "capacity": 1, "availability": [[0, 10]]} for i in range(17)]
    rejected(lambda: p.compile_finite_interval_schedule(encode(data), CONTRACT), "schedule_resource_count_bound")
    data = problem(horizon=100)
    data["resources"][0]["availability"] = [[i, i + 1] for i in range(17)]
    rejected(lambda: p.compile_finite_interval_schedule(encode(data), CONTRACT), "schedule_availability_count_bound")


@pytest.mark.parametrize("change,reason", [
    (lambda value: value.update(schema="wrong"), "invalid_schedule_witness_schema"),
    (lambda value: value.update(extra=1), "invalid_schedule_witness_fields"),
    (lambda value: value["assignments"].pop(), "schedule_assignment_cardinality"),
    (lambda value: value["assignments"].append(value["assignments"][0]), "schedule_assignment_cardinality"),
    (lambda value: value["assignments"].reverse(), "schedule_assignment_identity"),
    (lambda value: value["assignments"][1].update(id="job0"), "schedule_assignment_identity"),
    (lambda value: value["assignments"][0].update(resource="machine"), "invalid_schedule_assignment_fields"),
    (lambda value: value["assignments"][0].update(end=4), "schedule_duration_mismatch"),
    (lambda value: value["assignments"][0].update(start=True), "schedule_integer_bound"),
    (lambda value: value["assignments"][1].update(start=6, end=11), "schedule_release_deadline_violation"),
    (lambda value: value["assignments"][1].update(start=4, end=9), "schedule_capacity_violation"),
])
def test_mutated_candidate_is_rejected(change, reason):
    data = problem()
    value = witness(data, (0, 5))
    change(value)
    rejected(lambda: p.check_finite_interval_schedule(encode(data), encode(value), CONTRACT), reason)


def test_capacity_more_than_one_and_heterogeneous_demands():
    data = problem(capacity=2, durations=(5, 5, 5), horizon=10)
    assert checked(data, (0, 0, 5))["job_count"] == 3
    rejected(lambda: checked(data, (0, 0, 0)), "schedule_capacity_violation")
    data["jobs"][0]["demand"] = 2
    rejected(lambda: checked(data, (0, 0, 5)), "schedule_capacity_violation")
    assert checked(data, (0, 5, 5))["job_count"] == 3


def test_windows_are_explicit_and_jobs_cannot_cross_a_gap_or_adjacent_windows():
    data = problem(windows=[[0, 4], [6, 10]], durations=(3, 3))
    assert checked(data, (0, 6))["job_count"] == 2
    rejected(lambda: checked(data, (2, 6)), "schedule_availability_violation")
    data = problem(windows=[[0, 5], [5, 10]], durations=(6,))
    rejected(lambda: checked(data, (0,)), "schedule_availability_violation")


def test_multiple_resources_have_independent_capacity_and_nonzero_horizon():
    data = problem()
    data["resources"].append({"id": "other", "capacity": 1, "availability": [[0, 10]]})
    data["jobs"][1]["resource"] = "other"
    assert checked(data, (0, 0))["resource_count"] == 2
    data["horizon_start"], data["horizon_end"] = 100, 110
    for resource in data["resources"]:
        resource["availability"] = [[100, 110]]
    for job in data["jobs"]:
        job.update(release=100, deadline=110)
    assert checked(data, (100, 100))["job_count"] == 2


@pytest.mark.parametrize("change", [lambda r: r.update(job_count=9), lambda r: r.update(job_count=True),
    lambda r: r.update(input_sha256="0" * 64), lambda r: r.update(output_sha256="0" * 64),
    lambda r: r.update(proof_authority=True), lambda r: r.update(extra=False),
    lambda r: r["checker_provenance"]["sources"][0].update(sha256="0" * 64)])
def test_forged_self_consistent_receipts_do_not_replace_fresh_replay(change):
    data = problem()
    source, output = encode(data), encode(witness(data, (0, 5)))
    receipt = p.check_finite_interval_schedule(source, output, CONTRACT)
    change(receipt)
    receipt["receipt_cid"] = cid_for_structured({k: v for k, v in receipt.items() if k != "receipt_cid"})
    rejected(lambda: p.verify_finite_schedule_check(receipt, input_bytes=source,
             output_bytes=output, contract=CONTRACT), "finite_schedule_check_binding_mismatch")


def test_changed_source_and_equivalent_output_bytes_invalidate_receipt():
    data = problem()
    source, output = encode(data), encode(witness(data, (0, 5)))
    receipt = p.check_finite_interval_schedule(source, output, CONTRACT)
    for changed_source, changed_output in ((source + b"\n", output), (source, output + b"\n")):
        rejected(lambda: p.verify_finite_schedule_check(receipt, input_bytes=changed_source,
                 output_bytes=changed_output, contract=CONTRACT), "finite_schedule_check_binding_mismatch")
    data["resources"][0]["capacity"] = 2
    rejected(lambda: p.verify_finite_schedule_check(receipt, input_bytes=encode(data),
             output_bytes=output, contract=CONTRACT), "finite_schedule_check_binding_mismatch")


def inject(monkeypatch, stdout=None, error=None, available=True, transform=None):
    from ipfs_datasets_py.logic.backends.smt.admitted import Z3Backend
    from ipfs_datasets_py.logic.backends.registry import BackendRunnerOutput

    def runner(compiled, request):
        if error:
            raise error
        return BackendRunnerOutput(stdout=stdout, solver_version="authored-fixture")

    def factory(**kwargs):
        backend = Z3Backend(runner=runner, availability_probe=lambda: available)
        if transform:
            original = backend.run
            return SimpleNamespace(run=lambda request, **options: transform(original(request, **options)))
        return backend

    monkeypatch.setattr(p, "_backend", factory)


VALID_MODEL = "sat\n((define-fun s0 () Int 0) (define-fun s1 () Int 5))\n"


def test_checked_solver_model_returns_canonical_candidate(monkeypatch):
    inject(monkeypatch, VALID_MODEL)
    result = p.solve_finite_interval_schedule(encode(problem()), CONTRACT)
    assert result["status"] == "sat"
    assert result["output_bytes"].endswith(b"\n")
    assert json.loads(result["output_bytes"]) == witness(problem(), (0, 5))
    assert result["check"]["job_count"] == 2
    assert result["solver"]["proof_authority"] is False


@pytest.mark.parametrize("stdout", [
    "sat\n", "sat\n()", "sat\n((define-fun s0 () Int 0))", VALID_MODEL + "sat\n",
    VALID_MODEL.replace("s1", "s0"), VALID_MODEL.replace("s1", "extra"),
    VALID_MODEL.replace("() Int 5", "((x Int)) Int 5"), VALID_MODEL.replace("Int 5", "Real 5.0"),
    VALID_MODEL.replace("Int 5", "Int (+ 2 3)"), VALID_MODEL.replace("Int 5", "Int (- 5)"),
    VALID_MODEL.replace("s1", "|s1|"), VALID_MODEL.replace("Int 5", "Int 1000000001"),
    VALID_MODEL.replace("Int 5", "Int 0"), VALID_MODEL + '(error "bad")',
    "sat\n" + " " * p.SOLVER_OUTPUT_BYTES,
])
def test_malformed_partial_forged_or_infeasible_models_never_produce_candidate(monkeypatch, stdout):
    inject(monkeypatch, stdout)
    result = p.solve_finite_interval_schedule(encode(problem()), CONTRACT)
    assert result["status"] == "error"
    assert "output_bytes" not in result and "check" not in result


@pytest.mark.parametrize("stdout,status", [("unsat\n", "unsat"), ("unknown\n", "unknown"),
    ("garbage\n", "error"), ("sat\nunsat\n", "error")])
def test_solver_states_are_distinct_and_without_candidate(monkeypatch, stdout, status):
    inject(monkeypatch, stdout)
    result = p.solve_finite_interval_schedule(encode(problem()), CONTRACT)
    assert result["status"] == status
    assert "output_bytes" not in result


@pytest.mark.parametrize("stdout", ["unsat\n(error bad)", "unknown\n()", "unsat\njunk"])
def test_non_sat_verdict_diagnostics_or_artifacts_are_not_clean_outcomes(monkeypatch, stdout):
    inject(monkeypatch, stdout)
    result = p.solve_finite_interval_schedule(encode(problem()), CONTRACT)
    assert result["status"] == "error" and "output_bytes" not in result


def test_timeout_unavailable_and_cancelled_have_distinct_statuses(monkeypatch):
    inject(monkeypatch, error=TimeoutError("authored timeout"))
    assert p.solve_finite_interval_schedule(encode(problem()), CONTRACT)["status"] == "timeout"
    inject(monkeypatch, available=False)
    assert p.solve_finite_interval_schedule(encode(problem()), CONTRACT)["status"] == "unavailable"
    signal = threading.Event()
    signal.set()
    monkeypatch.setattr(p, "_backend", lambda **kwargs: pytest.fail("cancelled request launched"))
    result = p.solve_finite_interval_schedule(encode(problem()), CONTRACT, cancellation=signal)
    assert result["status"] == "cancelled" and "output_bytes" not in result


def test_foreign_result_binding_is_rejected(monkeypatch):
    inject(monkeypatch, VALID_MODEL, transform=lambda pair: (pair[0], replace(pair[1], obligation_digest="0" * 64)))
    result = p.solve_finite_interval_schedule(encode(problem()), CONTRACT)
    assert result == {"status": "error", "reason_code": "schedule_solver_binding_mismatch"}


@pytest.mark.parametrize("field,value", [("declaration_id", "foreign"), ("obligation_id", "foreign"),
                                        ("claim_digest", "0" * 64), ("assumption_ids", ("extra",))])
def test_foreign_solver_contract_bindings_never_produce_candidate(monkeypatch, field, value):
    inject(monkeypatch, VALID_MODEL, transform=lambda pair: (pair[0], replace(pair[1], **{field: value})))
    assert p.solve_finite_interval_schedule(encode(problem()), CONTRACT) == {
        "status": "error", "reason_code": "schedule_solver_binding_mismatch"}


def test_missing_payload_model_is_fail_closed(monkeypatch):
    from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
    def omit_model(pair):
        payload = pair[1].payload.to_dict()
        payload.pop("solver_output")
        return pair[0], replace(pair[1], payload=FrozenMap(payload))
    inject(monkeypatch, VALID_MODEL, transform=omit_model)
    result = p.solve_finite_interval_schedule(encode(problem()), CONTRACT)
    assert result["status"] == "error" and "output_bytes" not in result


def test_cancellation_after_model_observation_does_not_return_candidate(monkeypatch):
    signal = threading.Event()
    def cancel(pair):
        signal.set()
        return pair
    inject(monkeypatch, VALID_MODEL, transform=cancel)
    result = p.solve_finite_interval_schedule(encode(problem()), CONTRACT, cancellation=signal)
    assert result["status"] == "cancelled" and "output_bytes" not in result


def test_generated_symbols_do_not_depend_on_external_job_names():
    first = problem()
    second = deepcopy(first)
    second["jobs"][0]["id"] = "different_name"
    assert p.compile_finite_interval_schedule(encode(first), CONTRACT) == p.compile_finite_interval_schedule(encode(second), CONTRACT)
    assert "job0" not in p.compile_finite_interval_schedule(encode(first), CONTRACT)


@pytest.fixture
def native_scheduler(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    config = schedulers.ResourceSchedulerConfig.for_proof_host(state_path=tmp_path / "schedule-pool.json",
        proof_resource_sampler=lambda: healthy, total_cpu_slots=2, total_memory_mb=1024,
        total_child_process_slots=2, proof_memory_headroom_mb=64, lane_reservations={},
        auto_renew_leases=False, proof_backoff_seconds=0.025, poll_interval_seconds=0.002)
    scheduler = schedulers.GlobalResourceScheduler(config)
    yield scheduler
    snapshot = scheduler.snapshot()
    assert snapshot["active_lease_count"] == snapshot["waiting_request_count"] == 0


@pytest.mark.parametrize("data,status", [
    (problem(), "sat"), (problem(durations=(6, 6)), "unsat"),
    (problem(capacity=2, durations=(5, 5, 5), horizon=5), "unsat"),
    (problem(capacity=2, durations=(5, 5, 5)), "sat"),
    (problem(windows=[[0, 4], [6, 10]], durations=(3, 3)), "sat"),
    (problem(windows=[[0, 4], [6, 10]], durations=(5,)), "unsat"),
    (problem(windows=[[0, 5], [5, 10]], durations=(6,)), "unsat"),
])
def test_actual_admitted_z3_feasibility_and_independent_replay(data, status, native_scheduler):
    assert shutil.which("z3"), "native Z3 is required for this qualification"
    source = encode(data)
    result = p.solve_finite_interval_schedule(source, CONTRACT, scheduler=native_scheduler)
    assert result["status"] == status, result
    if status == "sat":
        assert p.verify_finite_schedule_check(result["check"], input_bytes=source,
            output_bytes=result["output_bytes"], contract=CONTRACT)["job_count"] == len(data["jobs"])
    else:
        assert "output_bytes" not in result and "check" not in result


def test_exhaustive_small_witnesses_match_independent_tick_reference():
    data = problem(capacity=2, durations=(1, 2, 2), horizon=4)
    for starts in itertools.product(range(4), repeat=3):
        valid = all(start + job["duration"] <= 4 for job, start in zip(data["jobs"], starts))
        valid = valid and all(sum(start <= tick < start + job["duration"]
            for job, start in zip(data["jobs"], starts)) <= 2 for tick in range(4))
        if valid:
            assert checked(data, starts)["job_count"] == 3
        else:
            rejected(lambda: checked(data, starts))
