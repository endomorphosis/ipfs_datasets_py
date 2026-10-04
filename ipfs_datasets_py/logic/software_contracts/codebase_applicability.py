"""Native input-domain and premise checks linked to conditional source evidence.

SAT(P), SAT(D) and D => P describe the selected typed input model. A fourth
query checks the parent property under D with the same source-body encoding.
These queries do not enforce Python argument types. This separate
sidecar preserves the original verification schema and never issues runtime,
kernel, cache, admission or completion authority. Historical loading rederives
queries and parses recorded process observations; it does not attest execution.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import importlib
import inspect
import json
import math
from pathlib import Path
import time
import types
from typing import Any

from . import codebase_verification as bridge
from .cache import ImmutableCAS
from .codebase_ir import RepositoryCodebaseIndex, StaleCodebaseError
from .content import canonical_dag_json_bytes, cid_for_structured
from .codebase_smt_compat import (
    LEGACY_APPLICABILITY_SCHEMA, LEGACY_APPLICABILITY_PROFILE, validate_legacy_module_pins,
)

CODEBASE_APPLICABILITY_SCHEMA = "codebase-input-applicability@2"
CODEBASE_APPLICABILITY_PROFILE = "current-python-int-bool-domain-applicability@2"
_AUTHORITY = dict(bridge._AUTHORITY)
_AUTHORITY["typed_model_evidence_only"] = True
_AUTHORITY["source_runtime_postcondition_verified"] = False
_EXTRA_MODULES = (__name__, "ipfs_datasets_py.logic.software_verification.applicability")
_EXTRA_PINS: dict[str, Any] = {}
_native_backends = bridge._native_backends
_FIELDS = frozenset({"schema", "profile", "authority", "verification_cid", "source_binding",
    "fence", "limits", "requested_domains", "requested_bounds", "effective_bounds", "environment",
    "checks", "process_observations", "canonical_keys", "contract_results", "status",
    "model_applicability_established", "conditional_proved", "conditional_refuted"})


class CodebaseApplicabilityError(bridge.CodebaseVerificationError):
    """Domain evidence is outside the bounded native profile or lost a binding."""


@dataclass(frozen=True, slots=True)
class CodebaseApplicabilityRecord:
    artifact_cid: str
    _payload: bytes
    observed_live: bool = False

    def __post_init__(self) -> None:
        if type(self._payload) is not bytes or type(self.observed_live) is not bool:
            raise CodebaseApplicabilityError("record requires immutable bytes and an exact origin bool")
        value = json.loads(self._payload)
        if (canonical_dag_json_bytes(value) != self._payload or cid_for_structured(value) != self.artifact_cid
                or value.get("schema") not in {CODEBASE_APPLICABILITY_SCHEMA, LEGACY_APPLICABILITY_SCHEMA}):
            raise CodebaseApplicabilityError("record identity does not recompute")

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._payload)

    @property
    def model_applicability_established(self) -> bool:
        return self.to_dict()["model_applicability_established"] is True

    @property
    def conditional_proved(self) -> bool:
        return self.to_dict()["conditional_proved"] is True

    @property
    def conditional_refuted(self) -> bool:
        return self.to_dict()["conditional_refuted"] is True


def _pins() -> list[dict[str, str]]:
    """Extend the existing limited loaded-code/source guard for these owners."""
    result = bridge._module_pins()
    for name in _EXTRA_MODULES:
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        if Path(__file__).resolve().parents[2] not in path.parents:
            raise CodebaseApplicabilityError("applicability owner resolved outside this package")
        raw = path.read_bytes()
        owned = {}

        def add(label: str, value: Any) -> None:
            if isinstance(value, (classmethod, staticmethod)):
                value = value.__func__
            try:
                value = inspect.unwrap(value)
            except ValueError:
                return
            code = getattr(value, "__code__", None)
            if isinstance(code, types.CodeType) and Path(code.co_filename).resolve() == path:
                owned[label] = code

        for label, value in vars(module).items():
            add(label, value)
            if isinstance(value, type) and value.__module__ == name:
                for member, method in vars(value).items():
                    add(label + "." + member, method.fget if isinstance(method, property) else method)
        identity = {"sha256": hashlib.sha256(raw).hexdigest(), "owned_code": owned}
        previous = _EXTRA_PINS.get(name)
        if previous is not None and previous != identity:
            raise CodebaseApplicabilityError("imported applicability source/code changed: " + name)
        if previous is None:
            candidates = set()

            def visit(code: Any) -> None:
                candidates.add(code)
                for child in code.co_consts:
                    if isinstance(child, types.CodeType):
                        visit(child)

            visit(compile(raw, str(path), "exec", dont_inherit=True))
            if any(code not in candidates for code in owned.values()):
                raise CodebaseApplicabilityError("loaded applicability code differs from disk: " + name)
            _EXTRA_PINS[name] = identity
        result.append({"module": name, "sha256": identity["sha256"]})
    return result


def _limits(value: Any, artifacts: ImmutableCAS) -> bridge.CodebaseVerificationLimits:
    value = bridge.CodebaseVerificationLimits() if value is None else value
    if type(value) is not bridge.CodebaseVerificationLimits:
        raise CodebaseApplicabilityError("limits must be native CodebaseVerificationLimits")
    value = bridge.CodebaseVerificationLimits(**value.to_dict())
    if value.max_artifact_bytes > artifacts.max_object_bytes:
        raise CodebaseApplicabilityError("artifact retention exceeds the CAS envelope")
    return value


def _domains(values: Any, limits: Any) -> tuple[Any, ...]:
    from ipfs_datasets_py.logic.software_verification.applicability import RequestedInputDomain
    if type(values) not in {list, tuple} or not 0 < len(values) <= limits.max_contracts:
        raise CodebaseApplicabilityError("a bounded nonempty list/tuple of native input domains is required")
    copied = []
    for domain in values:
        if type(domain) is not RequestedInputDomain:
            raise CodebaseApplicabilityError("only native RequestedInputDomain values are admitted")
        data = domain.to_dict()
        snapshot = RequestedInputDomain(data["function_name"], tuple(data["predicates"]), data["domain_id"])
        if canonical_dag_json_bytes(snapshot.to_dict()) != canonical_dag_json_bytes(data) or len(snapshot.predicates) > 32:
            raise CodebaseApplicabilityError("input domain changed during normalization or exceeds predicate count")
        copied.append(snapshot)
    if (len({domain.function_name for domain in copied}) != len(copied)
            or len({domain.domain_id for domain in copied}) != len(copied)):
        raise CodebaseApplicabilityError("duplicate domain function or identity")
    copied.sort(key=lambda domain: domain.function_name)
    if len(canonical_dag_json_bytes([domain.to_dict() for domain in copied])) > limits.max_condition_bytes:
        raise CodebaseApplicabilityError("domain predicate byte limit exceeded")
    return tuple(copied)


def _prepare(index: Any, verification_cid: str, head: Any, domains: Any, limits: Any):
    from ipfs_datasets_py.logic.software_verification.program import ProgramIR
    from ipfs_datasets_py.logic.software_verification.contracts import ProgramContract
    from ipfs_datasets_py.logic.software_verification.applicability import derive_contract_domain_obligations
    from ipfs_datasets_py.logic.backends.smt.compiler import SoftwareVerificationSMTCompiler
    parent = bridge.load_codebase_verification(index, verification_cid).to_dict()
    if (parent["source_binding"]["head"] != head.to_dict() or parent["execution_stage"] != "native_smt"
            or parent["post_contract_program"] is None):
        raise CodebaseApplicabilityError("parent must bind this exact head and a native source translation")
    program = ProgramIR.from_dict(parent["post_contract_program"])
    contracts = tuple(ProgramContract.from_dict(data) for data in parent["pipeline_result"]["contracts"])
    by_function = {function.function_id: function.name for function in program.functions}
    by_domain = {domain.function_name: domain for domain in domains}
    if (not contracts or len(contracts) > limits.max_contracts
            or set(by_domain) != {by_function[contract.function_id] for contract in contracts}):
        raise CodebaseApplicabilityError("domains must cover every contracted function exactly once")
    entry, _, raw = bridge._source_member(index, head, parent["source_binding"]["path"])
    if len(raw) > limits.max_source_bytes:
        raise CodebaseApplicabilityError("captured source exceeds applicability bounds")
    bridge._check_program(program, parent["source_binding"], raw)
    compiler = SoftwareVerificationSMTCompiler()
    prepared = []
    for contract in sorted(contracts, key=lambda contract: contract.contract_id):
        function_name = by_function[contract.function_id]
        domain = by_domain[function_name]
        contract_cid = cid_for_structured(contract.to_dict())
        domain_cid = cid_for_structured(domain.to_dict())
        try:
            definitions = derive_contract_domain_obligations(program, contract, domain)
        except ValueError as error:
            raise CodebaseApplicabilityError("entry applicability query is outside the native profile") from error
        if [definition.kind for definition in definitions] != [
            "premises_satisfiable", "domain_satisfiable", "domain_implies_preconditions",
            "property_on_requested_domain"]:
            raise CodebaseApplicabilityError("native applicability obligation inventory changed")
        for definition in definitions:
            compilation = compiler.compile(definition.smt_obligation)
            if len(compilation.smtlib.encode("utf-8")) > limits.max_script_bytes:
                raise CodebaseApplicabilityError("applicability script byte limit exceeded")
            metadata = {"parent_contract_id": contract.contract_id, "contract_cid": contract_cid,
                "function_name": function_name, "domain_id": domain.domain_id, "domain_cid": domain_cid,
                "kind": definition.kind, "obligation": definition.to_dict(),
                "compilation": compilation.to_dict()}
            prepared.append((metadata, compilation))
    if len(prepared) > limits.max_obligations:
        raise CodebaseApplicabilityError("applicability obligation count exceeds bounds")
    if len(canonical_dag_json_bytes([data for data, _ in prepared])) > limits.max_artifact_bytes // 2:
        raise CodebaseApplicabilityError("applicability preflight exceeds retention bounds")
    return parent, compiler, prepared


def _summaries(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for start in range(0, len(checks), 4):
        group = checks[start:start + 4]
        classes = [check["differential"]["classification"] for check in group]
        established = classes[:3] == ["agree_satisfiable", "agree_satisfiable", "agree_proved"]
        status = ("disagreement_quarantined" if "disagree" in classes else
            "inconsistent_premises" if classes[0] == "agree_unsatisfiable" else
            "empty_domain" if classes[1] == "agree_unsatisfiable" else
            "domain_not_covered" if classes[2] == "agree_disproved" else
            "established" if established else "inconclusive")
        results.append({key: group[0][key] for key in (
            "parent_contract_id", "contract_cid", "function_name", "domain_id", "domain_cid")}
            | {"status": status, "classifications": classes,
               "premises_satisfiable": classes[0] == "agree_satisfiable",
               "requested_domain_satisfiable": classes[1] == "agree_satisfiable",
               "requested_domain_within_preconditions": classes[2] == "agree_proved",
               "model_applicability_established": established,
               "domain_property_classification": classes[3],
               "conditional_proved": established and classes[3] == "agree_proved",
               "conditional_refuted": established and classes[3] == "agree_disproved"})
    return results


def _keys(payload: dict[str, Any]) -> list[dict[str, Any]]:
    from ipfs_datasets_py.logic.common.canonical_cache_key import CanonicalProofCacheKey
    return [CanonicalProofCacheKey.build(
        source={"binding": payload["source_binding"], "verification_cid": payload["verification_cid"]},
        expression=check["obligation"], formalization=check["compilation"],
        slice={"profile": payload["profile"], "contract_cid": check["contract_cid"], "domain_cid": check["domain_cid"]},
        obligation={"kind": check["kind"], "obligation": check["obligation"]},
        assumptions={"profile": payload["profile"], "requested_domains": payload["requested_domains"]},
        bounds=payload["effective_bounds"], translation=check["compilation"]["receipt"],
        provider="native-z3-cvc5-differential", environment=payload["environment"],
        policy={"profile": payload["profile"], "authority": payload["authority"]},
        schema={"sidecar": payload["schema"]}, checker="datasets-native-input-applicability",
        network_policy={"network": False}, evidence_kind="solver_result", authority_ceiling="bounded",
        source_cid=payload["source_binding"]["entry"]["source_cid"],
    ).to_dict() for check in payload["checks"]]


def verify_current_codebase_applicability(
    index: RepositoryCodebaseIndex, repository: str | Path, *, expected_head: Any,
    verification_cid: str, domains: Sequence[Any], bounds: Any = None, limits: Any = None,
    scheduler: Any = None, parent_lease: Any = None, cancel_event: Any = None,
    admission_timeout_seconds: float = 30, timeout_seconds: float = 120, memory_mb: int = 512,
) -> CodebaseApplicabilityRecord:
    """Run native input and requested-domain property queries; fence current source.

    The linked verification is independently rederived from immutable source.
    Its solvers are not rerun here. No caller-provided result or checker can
    replace the native applicability queries. Bounds reuse the existing bridge
    profile. Each @2 native phase obtains a pressure-checked child lease and
    shares cancellation and the overall deadline. Historical @1 is replay only.
    """
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    from ipfs_datasets_py.logic.backends.smt.differential import run_z3_cvc5_differential
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError
    from .codebase_resources import acquire_codebase_resources
    if type(index) is not RepositoryCodebaseIndex or type(index.artifacts) is not ImmutableCAS or index.catalog is None:
        raise CodebaseApplicabilityError("native current catalog and ImmutableCAS required")
    if type(expected_head) is not CodebaseHead:
        raise CodebaseApplicabilityError("exact native CodebaseHead required")
    head = CodebaseHead.from_dict(expected_head.to_dict())
    for name, value, positive in (("timeout_seconds", timeout_seconds, True),
                                  ("admission_timeout_seconds", admission_timeout_seconds, False)):
        if (type(value) not in {int, float} or not math.isfinite(value)
                or value < 0 or (positive and value == 0)):
            raise CodebaseApplicabilityError(f"{name} must be finite and within its positive/nonnegative bound")
    if type(memory_mb) is not int or memory_mb <= 0:
        raise CodebaseApplicabilityError("memory_mb must be a positive exact integer")
    limits = _limits(limits, index.artifacts)
    if limits.max_artifact_bytes > memory_mb * 1024 * 1024 // 8:
        raise CodebaseApplicabilityError("artifact bounds exceed admission envelope")
    requested = bridge._bounds(bounds)
    if requested.max_memory_bytes > memory_mb * 1024 * 1024:
        raise CodebaseApplicabilityError("solver memory declaration exceeds reservation")
    domains = _domains(domains, limits)
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, timeout_seconds=min(admission_timeout_seconds, timeout_seconds),
            memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)

        def checkpoint():
            if signal.is_set():
                raise LeaseCancelledError("codebase applicability cancelled")
            if time.monotonic() >= deadline:
                raise LeaseTimeoutError("codebase applicability deadline exceeded")

        def observe():
            checkpoint()
            remaining = deadline - time.monotonic()
            return index.observe_current(repository, expected_head=head, parent_lease=lease,
                cancel_event=signal, admission_timeout_seconds=min(admission_timeout_seconds, remaining),
                timeout_seconds=remaining, memory_mb=memory_mb)

        before = observe()
        pins = _pins()
        parent, compiler, prepared = _prepare(index, verification_cid, head, domains, limits)
        checkpoint()
        per_call_ms = int((deadline - time.monotonic() - 2) / (2 * len(prepared)) * 1000)
        if per_call_ms <= 0:
            raise LeaseTimeoutError("insufficient remaining deadline for applicability solver pairs")
        from dataclasses import replace
        effective = replace(requested, timeout_ms=min(requested.timeout_ms, per_call_ms))
        observations = []
        left, right, executables = _native_backends(compiler, observations, checkpoint,
            parent_lease=lease, cancel_event=signal, deadline=deadline,
            max_script_bytes=limits.max_script_bytes)
        checks = []
        for metadata, compilation in prepared:
            checkpoint()
            report = run_z3_cvc5_differential(compilation, bounds=effective,
                z3_backend=left, cvc5_backend=right, compiler=compiler)
            bridge._raise_execution_failure(left, right)
            checks.append(metadata | {"differential": report.to_dict()})
        checkpoint()
        if len(observations) != len(checks) * 2 or pins != _pins() or any(
            bridge._digest_file(Path(pin["path"])) != pin["sha256"] or
            (pin["launcher_sha256"] and bridge._digest_file(Path(pin["launcher_path"])) != pin["launcher_sha256"])
            for pin in executables):
            raise CodebaseApplicabilityError("applicability implementation/process/tool identities drifted")
        after = observe()
        summaries = _summaries(checks)
        established = all(item["model_applicability_established"] for item in summaries)
        proved = established and all(item["conditional_proved"] for item in summaries)
        refuted = established and any(item["conditional_refuted"] for item in summaries)
        payload = {"schema": CODEBASE_APPLICABILITY_SCHEMA, "profile": CODEBASE_APPLICABILITY_PROFILE,
            "authority": dict(_AUTHORITY), "verification_cid": verification_cid,
            "source_binding": parent["source_binding"], "fence": {"before": before.head.to_dict(),
                "after": after.head.to_dict(), "scope": "point_in_time_current_head_and_admitted_source"},
            "limits": limits.to_dict(), "requested_domains": [domain.to_dict() for domain in domains],
            "requested_bounds": requested.to_dict(), "effective_bounds": effective.to_dict(),
            "environment": {"module_pins": pins, "executables": executables, "network": False,
                "solver_versions": [{"backend_id": pin["backend_id"], "versions": sorted({
                    item["solver_version"] for item in observations if item["backend_id"] == pin["backend_id"]})}
                    for pin in executables]}, "checks": checks, "process_observations": observations,
            "canonical_keys": [], "contract_results": summaries,
            "status": "established" if established else "not_established",
            "model_applicability_established": established, "conditional_proved": proved,
            "conditional_refuted": refuted}
        payload["canonical_keys"] = _keys(payload)
        encoded = canonical_dag_json_bytes(payload)
        if len(encoded) > limits.max_artifact_bytes:
            raise CodebaseApplicabilityError("complete applicability artifact exceeds retention bounds")
        checkpoint()
        if index.current(head.repository_id) != head:
            raise StaleCodebaseError("catalog head changed before applicability publication")
        artifact_cid = index.artifacts.put(payload)
        observe()
        checkpoint()
        return CodebaseApplicabilityRecord(artifact_cid, encoded, observed_live=True)


def load_codebase_applicability(index: RepositoryCodebaseIndex, artifact_cid: str) -> CodebaseApplicabilityRecord:
    """Integrity/parsed-classification replay only; no tools or current assertion."""
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    from ipfs_datasets_py.logic.software_verification.applicability import RequestedInputDomain
    from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
    from ipfs_datasets_py.logic.backends.smt.differential import (
        SmtRawSolverOutput, SmtDifferentialVerifier, normalize_smtlib_for_solver,
    )
    from ipfs_datasets_py.logic.backends.z3.compiler import Z3SoftwareVerificationBackend
    from ipfs_datasets_py.logic.backends.cvc5.compiler import CVC5SoftwareVerificationBackend
    if type(index) is not RepositoryCodebaseIndex or type(index.artifacts) is not ImmutableCAS:
        raise CodebaseApplicabilityError("native codebase index and ImmutableCAS required")
    payload = index.artifacts.get(artifact_cid)
    legacy = payload.get("schema") == LEGACY_APPLICABILITY_SCHEMA
    expected_profile = LEGACY_APPLICABILITY_PROFILE if legacy else CODEBASE_APPLICABILITY_PROFILE
    if (payload.get("schema") not in {LEGACY_APPLICABILITY_SCHEMA, CODEBASE_APPLICABILITY_SCHEMA}
            or set(payload) != _FIELDS or payload["profile"] != expected_profile
            or canonical_dag_json_bytes(payload["authority"]) != canonical_dag_json_bytes(_AUTHORITY)):
        raise CodebaseApplicabilityError("invalid applicability schema/profile/authority")
    limits = _limits(bridge.CodebaseVerificationLimits(**payload["limits"]), index.artifacts)
    encoded = canonical_dag_json_bytes(payload)
    if len(encoded) > limits.max_artifact_bytes:
        raise CodebaseApplicabilityError("historical applicability retention exceeded")
    head = CodebaseHead.from_dict(payload["source_binding"]["head"])
    requested = ExecutionBounds.from_dict(payload["requested_bounds"])
    effective = ExecutionBounds.from_dict(payload["effective_bounds"])
    if (effective.timeout_ms > requested.timeout_ms or any(getattr(effective, name) != getattr(requested, name)
            for name in ("max_memory_bytes", "max_steps", "max_output_bytes"))):
        raise CodebaseApplicabilityError("historical applicability bounds differ from approved envelope")
    domains = _domains([RequestedInputDomain(data["function_name"], tuple(data["predicates"]), data["domain_id"])
                       for data in payload["requested_domains"]], limits)
    if canonical_dag_json_bytes([domain.to_dict() for domain in domains]) != canonical_dag_json_bytes(payload["requested_domains"]):
        raise CodebaseApplicabilityError("historical domains are not canonical")
    environment = payload["environment"]
    if (set(environment) != {"module_pins", "executables", "solver_versions", "network"}
            or environment["network"] is not False):
        raise CodebaseApplicabilityError("historical execution environment is invalid")
    current_pins = _pins()
    if legacy:
        try:
            validate_legacy_module_pins(environment["module_pins"], current_pins, applicability=True)
        except (TypeError, ValueError, KeyError) as error:
            raise CodebaseApplicabilityError(str(error)) from error
    elif environment["module_pins"] != current_pins:
        raise CodebaseApplicabilityError("historical implementation generation differs; explicit migration required")
    parent, compiler, prepared = _prepare(index, payload["verification_cid"], head, domains, limits)
    if (canonical_dag_json_bytes(payload["source_binding"]) != canonical_dag_json_bytes(parent["source_binding"])
            or payload["fence"] != {"before": head.to_dict(), "after": head.to_dict(),
                                    "scope": "point_in_time_current_head_and_admitted_source"}):
        raise CodebaseApplicabilityError("historical source/head/verification binding is invalid")
    executable_pins = environment["executables"]
    if (len(executable_pins) != 2 or [pin["backend_id"] for pin in executable_pins] != ["z3", "cvc5"]
            or any(set(pin) != {"backend_id", "path", "sha256", "launcher_path", "launcher_sha256"}
                or any(type(pin[name]) is not str or not pin[name] for name in ("path", "launcher_path", "sha256"))
                or type(pin["launcher_sha256"]) is not str
                or any(len(pin[name]) != 64 or any(char not in "0123456789abcdef" for char in pin[name])
                    for name in ("sha256", "launcher_sha256") if pin[name]) for pin in executable_pins)):
        raise CodebaseApplicabilityError("historical applicability executable pins are invalid")
    observations = payload["process_observations"]
    if len(observations) != 2 * len(prepared):
        raise CodebaseApplicabilityError("historical applicability process inventory is invalid")
    left = Z3SoftwareVerificationBackend(compiler=compiler, version_probe=lambda: "")
    right = CVC5SoftwareVerificationBackend(compiler=compiler, version_probe=lambda: "")
    verifier = SmtDifferentialVerifier(left=left, right=right, compiler=compiler)
    checks = []
    for ordinal, (metadata, compilation) in enumerate(prepared):
        outcomes = []
        for offset, backend in enumerate((left, right)):
            observation = observations[2 * ordinal + offset]
            fields = {"backend_id", "executable_sha256", "input_sha256", "bounds",
                "stdout", "stderr", "returncode", "elapsed_ms", "solver_version", "timed_out", "unavailable"}
            if not legacy:
                fields.add("execution")
            if (set(observation) != fields
                    or observation["backend_id"] != backend.backend_id
                    or observation["executable_sha256"] != executable_pins[offset]["sha256"]
                    or canonical_dag_json_bytes(observation["bounds"]) != canonical_dag_json_bytes(effective.to_dict())
                    or observation["input_sha256"] != hashlib.sha256(normalize_smtlib_for_solver(
                        compilation.smtlib).encode("utf-8")).hexdigest()):
                raise CodebaseApplicabilityError("historical applicability script/process/bounds binding is invalid")
            raw = SmtRawSolverOutput(**{name: observation[name] for name in (
                "stdout", "stderr", "returncode", "elapsed_ms", "solver_version", "timed_out", "unavailable")})
            if not legacy:
                from .codebase_smt_execution import validate_execution_receipt
                try:
                    validate_execution_receipt(observation["execution"], solver=backend.backend_id,
                        executable=executable_pins[offset]["path"],
                        smtlib=normalize_smtlib_for_solver(compilation.smtlib), bounds=effective, raw=raw)
                    if any(phase["limits"]["max_input_bytes"] != limits.max_script_bytes
                           for phase in observation["execution"]["phases"]):
                        raise ValueError("native phase input cap differs from sidecar script limit")
                except (TypeError, ValueError, KeyError) as error:
                    raise CodebaseApplicabilityError("historical bounded execution receipt is invalid: " + str(error)) from error
            outcomes.append(backend._outcome_from_raw(compilation=compilation, bounds=effective, raw=raw))
        checks.append(metadata | {"differential": verifier._report(compilation, *outcomes).to_dict()})
    versions = [{"backend_id": pin["backend_id"], "versions": sorted({item["solver_version"]
        for item in observations if item["backend_id"] == pin["backend_id"]})} for pin in executable_pins]
    if canonical_dag_json_bytes(checks) != canonical_dag_json_bytes(payload["checks"]) or versions != environment["solver_versions"]:
        raise CodebaseApplicabilityError("historical applicability obligations/classifications do not recompute")
    summaries = _summaries(checks)
    established = all(item["model_applicability_established"] for item in summaries)
    if (canonical_dag_json_bytes(summaries) != canonical_dag_json_bytes(payload["contract_results"])
            or payload["model_applicability_established"] is not established
            or payload["status"] != ("established" if established else "not_established")
            or payload["conditional_proved"] is not (established and all(item["conditional_proved"] for item in summaries))
            or payload["conditional_refuted"] is not (established and any(item["conditional_refuted"] for item in summaries))
            or canonical_dag_json_bytes(_keys(payload)) != canonical_dag_json_bytes(payload["canonical_keys"])):
        raise CodebaseApplicabilityError("historical applicability summaries/keys do not recompute")
    return CodebaseApplicabilityRecord(artifact_cid, encoded)


__all__ = ["CODEBASE_APPLICABILITY_SCHEMA", "CODEBASE_APPLICABILITY_PROFILE", "CodebaseApplicabilityError",
    "CodebaseApplicabilityRecord", "verify_current_codebase_applicability", "load_codebase_applicability"]
