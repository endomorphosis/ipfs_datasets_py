"""Bounded integer-tick schedule synthesis and independent witness replay.

Only explicit finite feasibility is supported. The resource-admitted SMT solver
proposes start times; a separate endpoint sweep checks the supplied witness.
Neither a model nor this finite check proves optimality, inferred intent,
universal program semantics, or authority to execute, publish or complete work.
No clock, timezone, recurrence, preemption or preference semantics are inferred.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from . import content

CONTRACT_SCHEMA = "finite-interval-schedule-contract@1"
INPUT_SCHEMA = "finite-interval-schedule-input@1"
OUTPUT_SCHEMA = "finite-interval-schedule-witness@1"
CHECK_SCHEMA = "finite-interval-schedule-check@1"
POLICY = "integer-tick-half-open-capacity-feasibility@1"
MAX_BYTES = 262_144
MAX_JOBS = 32
MAX_RESOURCES = 16
MAX_WINDOWS = 16
MAX_INTEGER = 1_000_000_000
MAX_JSON_DEPTH = 5
SOLVER_TIMEOUT_MS = 5_000
SOLVER_MEMORY_BYTES = 256 * 1024 * 1024
SOLVER_OUTPUT_BYTES = 65_536
SOLVER_MAX_STEPS = 1_000_000
_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}\Z", re.ASCII)
_SCOPE = (
    "Exact finite integer-tick witness under explicit half-open intervals, "
    "availability, duration, release/deadline and resource capacity constraints. "
    "No inferred intent alignment, optimality, kernel theorem, universal program "
    "semantics, execution, publication or task completion authority."
)


class FiniteIntervalScheduleError(ValueError):
    """The source, witness or receipt is outside the closed finite contract."""

    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


def _fail(reason: str) -> None:
    raise FiniteIntervalScheduleError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _equal(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return (all(type(key) is str for key in actual) and actual.keys() == expected.keys()
                and all(_equal(actual[key], value) for key, value in expected.items()))
    if type(expected) is list:
        return len(actual) == len(expected) and all(map(_equal, actual, expected))
    return actual == expected


@dataclass(frozen=True, slots=True)
class FiniteIntervalScheduleContract:
    """Fixed feasibility semantics; callers cannot relax checker bounds/policy."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_SCHEMA, "policy": POLICY,
            "input_schema": INPUT_SCHEMA, "output_schema": OUTPUT_SCHEMA,
            "time_domain": "nonnegative-integer-ticks", "intervals": "half-open",
            "objective": "feasibility-only", "preemption": "forbidden",
            "availability": "job-contained-in-one-explicit-resource-window",
            "availability_order": "ascending-disjoint-windows-touching-allowed",
            "assignment_order": "exact-input-job-order",
            "identity_policy": "unique-bounded-ASCII-resource-and-job-identifiers",
            "bounds": {"max_input_bytes": MAX_BYTES, "max_output_bytes": MAX_BYTES,
                "max_jobs": MAX_JOBS, "max_resources": MAX_RESOURCES,
                "max_windows_per_resource": MAX_WINDOWS, "max_integer": MAX_INTEGER,
                "max_json_depth": MAX_JSON_DEPTH},
            "solver_bounds": {"timeout_ms": SOLVER_TIMEOUT_MS,
                "max_memory_bytes": SOLVER_MEMORY_BYTES, "max_output_bytes": SOLVER_OUTPUT_BYTES,
                "max_steps": SOLVER_MAX_STEPS},
        }

    @classmethod
    def from_dict(cls, value: Any) -> FiniteIntervalScheduleContract:
        result = cls()
        if not _equal(value, result.to_dict()):
            _fail("invalid_schedule_contract")
        return result

    @property
    def cid(self) -> str:
        return content.cid_for_structured(self.to_dict())


def _contract(value: Any) -> FiniteIntervalScheduleContract:
    if type(value) is not FiniteIntervalScheduleContract:
        _fail("typed_schedule_contract_required")
    return value


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            _fail("duplicate_json_key")
        result[key] = value
    return result


def _integer(text: str) -> int:
    if not text.isascii() or not text.isdecimal() or len(text) > 10:
        _fail("schedule_integer_bound")
    value = int(text)
    if value > MAX_INTEGER:
        _fail("schedule_integer_bound")
    return value


def _number(_: str) -> None:
    _fail("non_integer_schedule_number")


def _document(raw: bytes) -> dict:
    if type(raw) is not bytes:
        _fail("exact_schedule_bytes_required")
    if not 1 <= len(raw) <= MAX_BYTES:
        _fail("schedule_bytes_bound")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        _fail("invalid_schedule_utf8")
    # Bound recursion before the standard JSON parser constructs any containers.
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                _fail("schedule_json_depth_bound")
        elif char in "]}":
            depth -= 1
            if depth < 0:
                _fail("invalid_schedule_json")
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_int=_integer,
                           parse_float=_number, parse_constant=_number)
    except (json.JSONDecodeError, RecursionError):
        _fail("invalid_schedule_json")
    if type(value) is not dict:
        _fail("schedule_object_required")
    return value


def _keys(value, keys, reason):
    if type(value) is not dict or set(value) != set(keys):
        _fail(reason)


def _tick(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= MAX_INTEGER:
        _fail("schedule_integer_bound")
    return value


def _identifier(value):
    if type(value) is not str or not _ID.fullmatch(value):
        _fail("invalid_schedule_identifier")
    return value


def _input(raw: bytes) -> dict:
    data = _document(raw)
    _keys(data, {"schema", "horizon_start", "horizon_end", "resources", "jobs"},
          "invalid_schedule_input_fields")
    if data["schema"] != INPUT_SCHEMA:
        _fail("invalid_schedule_input_schema")
    lower, upper = _tick(data["horizon_start"]), _tick(data["horizon_end"])
    if lower >= upper:
        _fail("empty_schedule_horizon")
    resources, jobs = data["resources"], data["jobs"]
    if type(resources) is not list or not 1 <= len(resources) <= MAX_RESOURCES:
        _fail("schedule_resource_count_bound")
    by_id = {}
    for resource in resources:
        _keys(resource, {"id", "capacity", "availability"}, "invalid_schedule_resource_fields")
        name = _identifier(resource["id"])
        if name in by_id:
            _fail("duplicate_schedule_resource")
        by_id[name] = resource
        _tick(resource["capacity"], positive=True)
        windows = resource["availability"]
        if type(windows) is not list or not 1 <= len(windows) <= MAX_WINDOWS:
            _fail("schedule_availability_count_bound")
        previous_end = lower
        for window in windows:
            if type(window) is not list or len(window) != 2:
                _fail("invalid_schedule_availability")
            start, end = map(_tick, window)
            if not lower <= start < end <= upper or start < previous_end:
                _fail("invalid_schedule_availability")
            previous_end = end
    if type(jobs) is not list or not 1 <= len(jobs) <= MAX_JOBS:
        _fail("schedule_job_count_bound")
    names = set()
    for job in jobs:
        _keys(job, {"id", "resource", "duration", "release", "deadline", "demand"},
              "invalid_schedule_job_fields")
        name = _identifier(job["id"])
        if name in names:
            _fail("duplicate_schedule_job")
        names.add(name)
        if _identifier(job["resource"]) not in by_id:
            _fail("unknown_schedule_resource")
        _tick(job["duration"], positive=True)
        _tick(job["demand"], positive=True)
        release, deadline = _tick(job["release"]), _tick(job["deadline"])
        if not lower <= release <= deadline <= upper:
            _fail("invalid_schedule_release_deadline")
    return data


def _checker_provenance():
    sources = []
    for path, name in ((Path(__file__), "finite_interval_schedule.py"),
                       (Path(content.__file__), "content.py")):
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
        except OSError:
            _fail("schedule_checker_provenance_unavailable")
        if not 1 <= len(raw) <= MAX_BYTES:
            _fail("schedule_checker_provenance_bound")
        sources.append({"module": "ipfs_datasets_py/logic/software_contracts/" + name,
                        "sha256": _sha(raw), "source_cid": content.cid_for_bytes(raw)})
    return {"schema": "finite-schedule-native-checker@1",
        "implementation": "independent-endpoint-capacity-sweep@1", "sources": sources,
        "identity_profile": content.PROFILE_ID,
        "dependency_scope": "Exact checker and identity module bytes; Python runtime, standard library "
            "and multiformats dependencies are not transitively attested. Owner must pin loaded source."}


def check_finite_interval_schedule(input_bytes: bytes, output_bytes: bytes,
                                   contract: FiniteIntervalScheduleContract) -> dict[str, Any]:
    """Check supplied assignments without running or consulting the synthesizer."""
    contract = _contract(contract)
    data, witness = _input(input_bytes), _document(output_bytes)
    _keys(witness, {"schema", "assignments"}, "invalid_schedule_witness_fields")
    if witness["schema"] != OUTPUT_SCHEMA:
        _fail("invalid_schedule_witness_schema")
    assignments = witness["assignments"]
    if type(assignments) is not list or len(assignments) != len(data["jobs"]):
        _fail("schedule_assignment_cardinality")
    resources = {row["id"]: row for row in data["resources"]}
    events = {name: [] for name in resources}
    for job, assignment in zip(data["jobs"], assignments):
        _keys(assignment, {"id", "start", "end"}, "invalid_schedule_assignment_fields")
        if _identifier(assignment["id"]) != job["id"]:
            _fail("schedule_assignment_identity")
        start, end = _tick(assignment["start"]), _tick(assignment["end"])
        if end - start != job["duration"]:
            _fail("schedule_duration_mismatch")
        if not job["release"] <= start < end <= job["deadline"]:
            _fail("schedule_release_deadline_violation")
        resource = resources[job["resource"]]
        if not any(left <= start and end <= right for left, right in resource["availability"]):
            _fail("schedule_availability_violation")
        # End events sort before start events. Every occupancy increase is
        # checked; this also handles capacity > 1 and heterogeneous demands.
        events[job["resource"]].extend(((start, 1, job["demand"]), (end, 0, -job["demand"])))
    for name, endpoints in events.items():
        load = 0
        for _, _, delta in sorted(endpoints):
            load += delta
            if not 0 <= load <= resources[name]["capacity"]:
                _fail("schedule_capacity_violation")
        if load != 0:
            _fail("schedule_capacity_sweep_incomplete")
    declaration = contract.to_dict()
    receipt = {"schema": CHECK_SCHEMA, "status": "checked", "evidence_kind": "finite_schedule_check",
        "policy": POLICY, "contract": declaration, "contract_cid": contract.cid,
        "contract_sha256": _sha(content.canonical_dag_json_bytes(declaration)),
        "input_sha256": _sha(input_bytes), "input_cid": content.cid_for_bytes(input_bytes),
        "input_size_bytes": len(input_bytes), "output_sha256": _sha(output_bytes),
        "output_cid": content.cid_for_bytes(output_bytes), "output_size_bytes": len(output_bytes),
        "job_count": len(data["jobs"]), "resource_count": len(resources),
        "checker_provenance": _checker_provenance(), "scope": _SCOPE,
        "semantic_alignment_verified": False, "kernel_checked": False,
        "optimality_verified": False, "proof_authority": False, "execution_authority": False,
        "publication_authority": False, "completion_authority": False}
    receipt["receipt_cid"] = content.cid_for_structured(receipt)
    return receipt


def verify_finite_schedule_check(receipt: Any, *, input_bytes: bytes, output_bytes: bytes,
                                contract: FiniteIntervalScheduleContract) -> dict[str, Any]:
    """Replay exact current input, witness, policy and checker, ignoring old verdicts."""
    fresh = check_finite_interval_schedule(input_bytes, output_bytes, contract)
    if not _equal(receipt, fresh):
        _fail("finite_schedule_check_binding_mismatch")
    return fresh


def _compile(data: dict) -> str:
    resources = {row["id"]: row for row in data["resources"]}
    lines = ["(set-logic QF_LIA)", "(set-option :produce-models true)"]
    for index in range(len(data["jobs"])):
        lines.append(f"(declare-const s{index} Int)")
    for index, job in enumerate(data["jobs"]):
        start, end = f"s{index}", f"(+ s{index} {job['duration']})"
        lines.extend((f"(assert (>= {start} {job['release']}))",
                      f"(assert (<= {end} {job['deadline']}))"))
        windows = [f"(and (>= {start} {left}) (<= {end} {right}))"
                   for left, right in resources[job["resource"]]["availability"]]
        lines.append("(assert (or " + " ".join(windows) + "))")
        # Occupancy can increase only at a job start. Checking all such
        # instants suffices over half-open intervals without discretizing time.
        loads = [f"(ite (and (<= s{other} {start}) (< {start} (+ s{other} {row['duration']}))) {row['demand']} 0)"
                 for other, row in enumerate(data["jobs"]) if row["resource"] == job["resource"]]
        lines.append(f"(assert (<= (+ {' '.join(loads)}) {resources[job['resource']]['capacity']}))")
    lines.extend(("(check-sat)", "(get-model)"))
    script = "\n".join(lines) + "\n"
    if len(script.encode()) > MAX_BYTES:
        _fail("schedule_compilation_bytes_bound")
    return script


def compile_finite_interval_schedule(input_bytes: bytes,
                                     contract: FiniteIntervalScheduleContract) -> str:
    """Pure bounded QF_LIA compilation, using generated symbols only."""
    _contract(contract)
    return _compile(_input(input_bytes))


def _model_starts(stdout: str, count: int) -> list[int]:
    from ..parsers.smtlib import SAtom, SList, read_sexprs
    from ..syntax_core.contracts import ParseLimits
    from .codebase_smt_protocol import SmtProtocolError, validate_artifact_response

    if type(stdout) is not str or not stdout or len(stdout) > SOLVER_OUTPUT_BYTES:
        _fail("schedule_model_bytes_bound")
    try:
        if len(stdout.encode()) > SOLVER_OUTPUT_BYTES:
            _fail("schedule_model_bytes_bound")
        validate_artifact_response(stdout, "sat", "model")
    except (UnicodeError, SmtProtocolError):
        _fail("invalid_schedule_model_protocol")
    forms, diagnostics = read_sexprs(stdout, limits=ParseLimits(
        max_input_bytes=SOLVER_OUTPUT_BYTES, max_tokens=4096, max_depth=8))
    if diagnostics:
        _fail("invalid_schedule_model_protocol")
    forms = [form for form in forms if not (isinstance(form, SAtom) and form.kind == "symbol"
                                            and form.value == "success")]
    if len(forms) != 2 or not isinstance(forms[1], SList):
        _fail("invalid_schedule_model_protocol")
    definitions = forms[1].items
    if definitions and isinstance(definitions[0], SAtom) and definitions[0].value == "model":
        definitions = definitions[1:]
    values = {}
    expected = {f"s{index}" for index in range(count)}
    for definition in definitions:
        # Protocol already checks define-fun framing; constrain its semantics
        # to exactly the generated nullary nonnegative integer constants.
        if not isinstance(definition, SList) or len(definition.items) != 5:
            _fail("invalid_schedule_model_definition")
        _, name, parameters, sort, value = definition.items
        if (not isinstance(name, SAtom) or name.kind != "symbol" or name.value not in expected
                or name.value in values or not isinstance(parameters, SList) or parameters.items
                or not isinstance(sort, SAtom) or sort.kind != "symbol" or sort.value != "Int"
                or not isinstance(value, SAtom) or value.kind != "numeral"):
            _fail("invalid_schedule_model_definition")
        values[name.value] = _integer(value.value)
    if set(values) != expected:
        _fail("schedule_model_identity_mismatch")
    return [values[f"s{index}"] for index in range(count)]


def _backend(*, scheduler, parent_lease, cancellation):
    from ..backends.smt.admitted import Z3Backend
    return Z3Backend(scheduler=scheduler, parent_lease=parent_lease,
                     cancellation=cancellation, max_input_bytes=MAX_BYTES)


def solve_finite_interval_schedule(input_bytes: bytes, contract: FiniteIntervalScheduleContract,
                                   *, scheduler=None, parent_lease=None, cancellation=None) -> dict[str, Any]:
    """Run admitted bounded synthesis; only independently checked SAT has bytes.

    Unsupported source raises FiniteIntervalScheduleError. Native solver states
    are observations, including UNSAT (not an independently checked proof of
    impossibility). Unknown, timeout, cancellation and failures have no candidate.
    """
    from ..backends.process import _is_cancelled
    from ..ir_core.protocols import (AttemptStatus, BackendAttempt, BackendRequest,
        ExecutionBounds, QueryKind, ResultStatus, SatisfiabilityResult)

    contract = _contract(contract)
    data = _input(input_bytes)
    if _is_cancelled(cancellation):
        return {"status": "cancelled", "reason_code": "schedule_solver_cancelled"}
    source = _compile(data)
    source_digest = _sha(source.encode())
    binding = _sha(content.canonical_dag_json_bytes({"input_sha256": _sha(input_bytes),
                                                   "contract": contract.to_dict()}))
    bounds = ExecutionBounds(**contract.to_dict()["solver_bounds"])
    request = BackendRequest(request_id="request:schedule:" + binding,
        claim_id="claim:schedule:" + binding, declaration_id=contract.cid,
        claim_digest=binding, obligation_id="obligation:schedule:" + source_digest,
        obligation_digest=source_digest, assumption_ids=(), logic_family="smtlib2",
        query_kind=QueryKind.SATISFIABILITY, requested_backend_id="z3", bounds=bounds,
        payload={"encoding": "smtlib2", "source": source})
    try:
        backend = _backend(scheduler=scheduler, parent_lease=parent_lease, cancellation=cancellation)
        attempt, result = backend.run(request, cancellation=cancellation)
        if _is_cancelled(cancellation):
            return {"status": "cancelled", "reason_code": "schedule_solver_cancelled"}
        if (type(attempt) is not BackendAttempt or type(result) is not SatisfiabilityResult
                or attempt.request_digest != request.digest or result.request_digest != request.digest
                or result.attempt_digest != attempt.digest or result.bounds != bounds
                or attempt.bounds != bounds or result.backend_id != "z3" or attempt.backend_id != "z3"
                or result.claim_digest != binding or result.obligation_digest != source_digest
                or result.declaration_id != request.declaration_id
                or result.obligation_id != request.obligation_id
                or result.assumption_ids != request.assumption_ids
                or result.backend_version != attempt.backend_version
                or result.usage != attempt.usage or result.output_digest != attempt.output_digest):
            _fail("schedule_solver_binding_mismatch")
        states = {AttemptStatus.TIMED_OUT: "timeout", AttemptStatus.UNAVAILABLE: "unavailable",
                  AttemptStatus.CANCELLED: "cancelled", AttemptStatus.FAILED: "error"}
        metadata = {"request_digest": request.digest, "attempt_digest": attempt.digest,
            "compiled_source_sha256": source_digest, "bounds": bounds.to_dict(),
            "elapsed_ms": attempt.usage.elapsed_ms, "proof_authority": False}
        if attempt.status in states:
            status = states[attempt.status]
            return {"status": status, "reason_code": "schedule_solver_" + status, "solver": metadata}
        if attempt.status is not AttemptStatus.SUCCEEDED:
            _fail("schedule_solver_invalid_status")
        payload = result.payload.to_dict()
        if (payload.get("solver_stderr") or type(payload.get("returncode")) is not int
                or payload["returncode"] != 0):
            _fail("schedule_solver_dirty_observation")
        if result.status in {ResultStatus.UNSATISFIABLE, ResultStatus.UNKNOWN}:
            from .codebase_smt_protocol import SmtProtocolError, parse_verdict
            expected = "unsat" if result.status is ResultStatus.UNSATISFIABLE else "unknown"
            try:
                if (parse_verdict(payload.get("solver_output")) != expected
                        or payload.get("solver_result") != expected):
                    _fail("invalid_schedule_solver_verdict")
            except SmtProtocolError:
                _fail("invalid_schedule_solver_verdict")
        if result.status is ResultStatus.UNSATISFIABLE:
            return {"status": "unsat", "reason_code": "schedule_solver_reported_unsat", "solver": metadata}
        if result.status is ResultStatus.UNKNOWN:
            return {"status": "unknown", "reason_code": "schedule_solver_unknown", "solver": metadata}
        if result.status is not ResultStatus.SATISFIABLE:
            _fail("schedule_solver_invalid_status")
        if payload.get("solver_result") != "sat":
            _fail("invalid_schedule_solver_verdict")
        starts = _model_starts(payload.get("solver_output"), len(data["jobs"]))
        output = content.canonical_dag_json_bytes({"schema": OUTPUT_SCHEMA, "assignments": [
            {"id": job["id"], "start": start, "end": start + job["duration"]}
            for job, start in zip(data["jobs"], starts)]}) + b"\n"
        check = check_finite_interval_schedule(input_bytes, output, contract)
        if _is_cancelled(cancellation):
            return {"status": "cancelled", "reason_code": "schedule_solver_cancelled"}
        return {"status": "sat", "output_bytes": output, "check": check, "solver": metadata}
    except FiniteIntervalScheduleError as error:
        return {"status": "error", "reason_code": error.reason_code}
    except TimeoutError:
        return {"status": "timeout", "reason_code": "schedule_solver_timeout"}
    except OSError:
        return {"status": "unavailable", "reason_code": "schedule_solver_unavailable"}
    except Exception:
        return {"status": "error", "reason_code": "schedule_solver_error"}


__all__ = ["FiniteIntervalScheduleContract", "FiniteIntervalScheduleError",
           "compile_finite_interval_schedule", "solve_finite_interval_schedule",
           "check_finite_interval_schedule", "verify_finite_schedule_check"]
