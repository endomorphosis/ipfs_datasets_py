"""Bounded, source-bound conditional SMT evidence for an existing codebase head.

This joins the native structural catalog/CAS to the native verification pipeline.
It does not prepare a head, execute repository code, issue a kernel receipt, or
write the authoritative proof cache. A successful SMT query describes the
translated Int/Bool model under recorded assumptions, not Python runtime
behavior. Every public authority/admission/completion flag remains false.

The historical loader verifies immutable identities and internal bindings. It
does not attest that a stored observation was produced by a trusted checker and
does not re-run solvers. Consumers must reobserve the checkout at their own
admission boundary. Native @2 phases use shared admission, bounded process-tree
execution and cancellation; Python translation and replay remain cooperative.
The exact reviewed @1 generation remains readable with its original limitations.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
import hashlib
import importlib
import inspect
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import time
import types
from typing import Any

from .cache import ImmutableCAS
from .codebase_ir import CodebaseIRError, RepositoryCodebaseIndex, StaleCodebaseError
from .content import canonical_dag_json_bytes, cid_for_structured
from .codebase_smt_compat import (
    LEGACY_VERIFICATION_SCHEMA, LEGACY_VERIFICATION_PROFILE, validate_legacy_module_pins,
)

CODEBASE_VERIFICATION_SCHEMA = "codebase-conditional-verification@2"
CODEBASE_VERIFICATION_PROFILE = "current-python-int-bool-native-smt@2"
_AUTHORITY = {
    "conditional_model_evidence": True,
    "kernel_checked": False,
    "source_runtime_semantics_verified": False,
    "behavioral_satisfaction": False,
    "authoritative_cache_eligible": False,
    "admission_authority": False,
    "completion_authority": False,
}
_FIELDS = frozenset({
    "schema", "profile", "authority", "source_binding", "fence", "limits",
    "requested_contracts", "requested_bounds", "effective_bounds", "environment",
    "pipeline", "pipeline_result", "post_contract_program", "solver_artifacts",
    "process_observations", "canonical_keys", "coverage", "execution_stage",
})
_MODULES = (
    __name__,
    "ipfs_datasets_py.logic.software_contracts.codebase_integer_profile",
    "ipfs_datasets_py.logic.software_verification.pipeline",
    "ipfs_datasets_py.logic.software_verification.source_adapters",
    "ipfs_datasets_py.logic.software_verification.program",
    "ipfs_datasets_py.logic.software_verification.contracts",
    "ipfs_datasets_py.logic.software_verification.vc",
    "ipfs_datasets_py.logic.software_verification.ir",
    "ipfs_datasets_py.logic.software_verification.properties",
    "ipfs_datasets_py.logic.software_verification.receipts",
    "ipfs_datasets_py.logic.software_verification.translations",
    "ipfs_datasets_py.logic.backends.results",
    "ipfs_datasets_py.logic.backends.smt.compiler",
    "ipfs_datasets_py.logic.backends.smt.differential",
    "ipfs_datasets_py.logic.backends.z3.compiler",
    "ipfs_datasets_py.logic.backends.cvc5.compiler",
    "ipfs_datasets_py.logic.ir_core.provenance",
    "ipfs_datasets_py.logic.ir_core.protocols",
    "ipfs_datasets_py.logic.ir_core.claims",
    "ipfs_datasets_py.logic.ir_core.identity",
    "ipfs_datasets_py.logic.common.canonical_cache_key",
    "ipfs_datasets_py.logic.software_contracts.codebase_smt_execution",
    "ipfs_datasets_py.logic.software_contracts.codebase_smt_protocol",
    "ipfs_datasets_py.logic.backends.process",
    "ipfs_datasets_py.logic.software_contracts.codebase_smt_compat",
    "ipfs_datasets_py.logic.parsers.smtlib",
    "ipfs_datasets_py.logic.syntax_core.contracts",
)
_IMPORTED_SOURCE_PINS: dict[str, Any] = {}


class CodebaseVerificationError(CodebaseIRError):
    """An evidence binding or the bounded verification profile is invalid."""


@dataclass(frozen=True, slots=True)
class CodebaseVerificationLimits:
    max_source_bytes: int = 64 * 1024
    max_contracts: int = 8
    max_condition_bytes: int = 16 * 1024
    max_obligations: int = 32
    max_script_bytes: int = 256 * 1024
    max_artifact_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise CodebaseVerificationError(f"{name} must be a positive exact integer")

    def to_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class CodebaseVerificationRecord:
    """Immutable sidecar view; historical integrity alone is not execution trust."""

    artifact_cid: str
    _payload: bytes
    observed_live: bool = False

    def __post_init__(self) -> None:
        if type(self._payload) is not bytes or type(self.observed_live) is not bool:
            raise CodebaseVerificationError("record payload must be immutable bytes and origin an exact bool")
        value = json.loads(self._payload)
        if (canonical_dag_json_bytes(value) != self._payload
                or cid_for_structured(value) != self.artifact_cid
                or value.get("schema") not in {CODEBASE_VERIFICATION_SCHEMA, LEGACY_VERIFICATION_SCHEMA}):
            raise CodebaseVerificationError("record content identity does not recompute")

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._payload)

    @property
    def conditional_proved(self) -> bool:
        return self.to_dict()["pipeline_result"]["proved"] is True

    @property
    def conditional_disproved(self) -> bool:
        return self.to_dict()["pipeline_result"]["disproved"] is True


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _module_pins() -> list[dict[str, str]]:
    # Same loaded-code/source check as the native schema-lake producer guard.
    # Generated dataclass methods and arbitrary dependency/global state remain
    # outside this limited pin; it is not a cryptographic checker attestation.
    pins = []
    package = Path(__file__).resolve().parents[2]
    for name in _MODULES:
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        if package not in path.parents:
            raise CodebaseVerificationError("verification owner resolved outside this package")
        raw = path.read_bytes()
        owned = {}

        def add(label: str, value: Any) -> None:
            if isinstance(value, (staticmethod, classmethod)):
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
        previous = _IMPORTED_SOURCE_PINS.get(name)
        if previous is not None and previous != identity:
            raise CodebaseVerificationError("imported verification source/code changed: " + name)
        if previous is None:
            candidates = set()

            def visit(code: Any) -> None:
                candidates.add(code)
                for child in code.co_consts:
                    if isinstance(child, types.CodeType):
                        visit(child)

            visit(compile(raw, str(path), "exec", dont_inherit=True))
            if any(code not in candidates for code in owned.values()):
                raise CodebaseVerificationError("loaded verification code differs from disk: " + name)
            _IMPORTED_SOURCE_PINS[name] = identity
        pins.append({"module": name, "sha256": identity["sha256"]})
    return pins


def _bounds(value: Any) -> Any:
    from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
    if value is None:
        return ExecutionBounds(timeout_ms=5000, max_steps=100000,
                               max_memory_bytes=128 * 1024 * 1024,
                               max_output_bytes=256 * 1024)
    if type(value) is not ExecutionBounds:
        raise CodebaseVerificationError("bounds must be native ExecutionBounds")
    return ExecutionBounds.from_dict(value.to_dict())


def _contracts(values: Sequence[Any], limits: CodebaseVerificationLimits) -> tuple[Any, ...]:
    from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec
    if type(values) not in {tuple, list} or not 0 < len(values) <= limits.max_contracts:
        raise CodebaseVerificationError("a bounded nonempty list/tuple of ContractSpec is required")
    copied = []
    for item in values:
        if type(item) is not ContractSpec:
            raise CodebaseVerificationError("only native declarative ContractSpec values are admitted")
        data = item.to_dict()
        if any(type(data[name]) is not str for name in ("function_name", "contract_id")):
            raise CodebaseVerificationError("contract identities must be exact strings")
        conditions = data["preconditions"] + data["postconditions"]
        if len(conditions) > 32 or any(type(value) is not str for value in conditions):
            raise CodebaseVerificationError("contract condition inventory is invalid or oversized")
        copied.append(ContractSpec(data["function_name"], tuple(data["preconditions"]),
                                   tuple(data["postconditions"]), data["contract_id"]))
        if copied[-1].to_dict() != data:
            raise CodebaseVerificationError("contract normalization changed supplied values")
    if len({item.contract_id for item in copied}) != len(copied):
        raise CodebaseVerificationError("duplicate contract identities")
    if len(canonical_dag_json_bytes([item.to_dict() for item in copied])) > limits.max_condition_bytes:
        raise CodebaseVerificationError("contract byte limit exceeded")
    return tuple(copied)


def _source_member(index: RepositoryCodebaseIndex, head: Any, path: str) -> tuple[Any, Any, bytes]:
    manifest = index.load(head.manifest_cid)
    if (manifest.snapshot.repository_id != head.repository_id
            or manifest.snapshot.snapshot_cid != head.snapshot_cid
            or manifest.ast_revision_id != head.ast_revision_id):
        raise CodebaseVerificationError("head does not bind its structural manifest")
    entry = next((entry for entry in manifest.snapshot.entries if entry.path == path), None)
    if entry is None or entry.is_opaque:
        raise CodebaseVerificationError("path must be a captured, nonopaque manifest member")
    unit = next(unit for unit in manifest.units if unit.source_key == entry.source_key)
    if unit.ast_cid is None or unit.parse_status not in {"ok", "partial"}:
        raise CodebaseVerificationError("source must have an admitted structural AST")
    index.load_ast_artifact(manifest, path)
    raw = index.artifacts.get_bytes(entry.source_cid)
    if len(raw) != entry.size_bytes:
        raise CodebaseVerificationError("source byte length does not bind the captured entry")
    return entry, unit, raw


def _check_program(program: Any, source: dict[str, Any], raw: bytes) -> None:
    if program is None:
        return
    if len(program.sources) != 1:
        raise CodebaseVerificationError("profile requires exactly one source reference")
    ref = program.sources[0]
    ref.validate()
    if (ref.source_revision != source["source_revision"]
            or ref.content_sha256 != source["content_sha256"]
            or ref.metadata.get("path") != source["path"]
            or ref.source_uri != "file:///" + source["path"]
            or (ref.content_cid and ref.content_cid != source["entry"]["source_cid"])):
        raise CodebaseVerificationError("ProgramIR source identity does not match captured bytes")
    text = raw.decode("utf-8", errors="strict")
    for span in program.spans:
        span.validate()
        if span.source_ref_id != ref.ref_id or not 0 <= span.start_byte <= span.end_byte <= len(raw):
            raise CodebaseVerificationError("ProgramIR span is outside captured source")
        try:
            raw[:span.start_byte].decode("utf-8", errors="strict")
            raw[:span.end_byte].decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise CodebaseVerificationError("ProgramIR span cuts a UTF-8 coordinate") from error
        if span.start_char is not None and (
            len(text[:span.start_char].encode("utf-8")) != span.start_byte
            or len(text[:span.end_char].encode("utf-8")) != span.end_byte
        ):
            raise CodebaseVerificationError("ProgramIR character/byte coordinates disagree")


def _check_result(result: Any, source: dict[str, Any], raw: bytes) -> None:
    _check_program(result.program, source, raw)
    if result.adapter is None or result.adapter.path != source["path"] or result.adapter.language != "python":
        raise CodebaseVerificationError("native adapter binding is missing")
    _check_program(result.adapter.program, source, raw)
    document = result.adapter.document
    if (document is None or len(document.sources) != 1
            or document.sources[0].content_sha256 != source["content_sha256"]
            or document.sources[0].source_revision != source["source_revision"]
            or document.sources[0].metadata.get("path") != source["path"]):
        raise CodebaseVerificationError("adapter document does not bind captured source")
    if result.bindings is not None:
        binding = result.bindings.source
        if (result.program is None or binding.path != source["path"]
                or binding.content_sha256 != source["content_sha256"]
                or binding.source_revision != source["source_revision"]
                or binding.program_id != result.program.program_id
                or binding.source_ref_ids != tuple(item.ref_id for item in result.program.sources)
                or binding.span_ids != tuple(item.span_id for item in result.program.spans)):
            raise CodebaseVerificationError("pipeline source/result bindings disagree")
    elif result.obligation_results:
        raise CodebaseVerificationError("solver result lacks mandatory source bindings")
    if result.program is not None:
        by_vc = {item.obligation_id: item for group in result.vc_sets for item in group.obligations}
        contracts = {item.contract_id for item in result.contracts}
        refs = {item.ref_id for item in result.program.sources}
        spans = {item.span_id for item in result.program.spans}
        for group in result.vc_sets:
            if group.program_id != result.program.program_id or group.parent_contract_id not in contracts:
                raise CodebaseVerificationError("VC set does not bind the post-contract ProgramIR")
        for item in result.obligation_results:
            vc = item.vc_obligation
            if (by_vc.get(vc.obligation_id) != vc or vc.parent_contract_id not in contracts
                    or not set(vc.source_ref_ids) <= refs or not set(vc.span_ids) <= spans
                    or item.compilation.obligation_id != item.smt_obligation.obligation_id
                    or item.smt_obligation.attributes.get("vc_obligation_id") != vc.obligation_id
                    or item.smt_obligation.attributes.get("parent_contract_id") != vc.parent_contract_id):
                raise CodebaseVerificationError("solver obligation lost its exact VC/source binding")


def _solver_artifacts(result: Any) -> list[dict[str, Any]]:
    return [{"property_id": item.property_id,
             "smt_obligation": item.smt_obligation.to_dict(),
             "compilation": item.compilation.to_dict()}
            for item in result.obligation_results]


def _canonical_keys(payload: dict[str, Any]) -> list[dict[str, Any]]:
    from ipfs_datasets_py.logic.common.canonical_cache_key import CanonicalProofCacheKey
    result = payload["pipeline_result"]
    return [CanonicalProofCacheKey.build(
        source=payload["source_binding"], expression=artifact["smt_obligation"],
        formalization=payload["post_contract_program"],
        slice={"profile": payload["profile"], "property_id": artifact["property_id"],
               "selected_rules": payload["pipeline"]["solver_rules"]},
        obligation=item["vc_obligation"],
        assumptions={"language_and_contract_ids": result["bindings"]["assumption_ids"],
                     "smt_assumptions": artifact["smt_obligation"]["assumptions"]},
        bounds=payload["effective_bounds"], translation=artifact["compilation"]["receipt"],
        provider="native-z3-cvc5-differential", environment=payload["environment"],
        policy={"profile": payload["profile"], "authority": payload["authority"]},
        schema={"sidecar": payload["schema"], "pipeline": result["schema_version"]},
        checker="datasets-native-smt-process-observation", network_policy={"network": False},
        evidence_kind="solver_result", authority_ceiling="bounded",
        source_cid=payload["source_binding"]["entry"]["source_cid"],
    ).to_dict() for artifact, item in zip(payload["solver_artifacts"], result["obligation_results"])]


def _native_backends(compiler: Any, observations: list[dict[str, Any]], checkpoint: Any, *,
                     parent_lease: Any, cancel_event: Any, deadline: float,
                     max_script_bytes: int) -> tuple[Any, Any, list[dict[str, str]]]:
    """Audit native semantic backends through the owned bounded transport."""
    from ipfs_datasets_py.logic.backends.z3.compiler import Z3SoftwareVerificationBackend
    from ipfs_datasets_py.logic.backends.cvc5.compiler import CVC5SoftwareVerificationBackend
    # Reuse the existing native profile's executable/installer-launcher owner.
    from .codebase_integer_profile import _native_executable, _binary_digest
    from .codebase_smt_execution import make_codebase_smt_runner
    backends, pins = [], []
    # The generic semantic pipeline intentionally converts Exception into a
    # failed result, and its backend converts OSError into unavailability. Keep
    # the first owned execution failure separately so these conversions cannot
    # discard diagnostics or allow another native invocation in this operation.
    failures: list[BaseException] = []
    for executable, backend_type in (("z3", Z3SoftwareVerificationBackend), ("cvc5", CVC5SoftwareVerificationBackend)):
        resolved = shutil.which(executable)
        if resolved is None:
            raise CodebaseVerificationError(f"native {executable} executable is unavailable")
        launcher_path = str(Path(resolved).resolve())
        resolved, launcher_digest = _native_executable(resolved)
        real_runner = make_codebase_smt_runner(executable, resolved, parent_lease=parent_lease,
            cancel_event=cancel_event, deadline=deadline, max_script_bytes=max_script_bytes)
        # Every process, including version discovery, belongs to the same
        # admitted operation. Historical parsing never launches a fallback.
        backend = backend_type(executable=resolved, compiler=compiler,
                               runner=real_runner, version_probe=lambda: "")
        backend._codebase_execution_failures = failures
        pin = {"backend_id": backend.backend_id, "path": resolved,
               "sha256": _binary_digest(resolved), "launcher_path": launcher_path,
               "launcher_sha256": launcher_digest}
        pins.append(pin)

        def observed(smtlib: str, bounds: Any, *, runner=real_runner, owner=backend, executable_pin=pin):
            if failures:
                raise failures[0]
            try:
                checkpoint()
                raw = runner(smtlib, bounds)
                observations.append({"backend_id": owner.backend_id,
                    "executable_sha256": executable_pin["sha256"],
                    "input_sha256": hashlib.sha256(smtlib.encode("utf-8")).hexdigest(),
                    "bounds": bounds.to_dict(), "stdout": raw.stdout, "stderr": raw.stderr,
                    "returncode": raw.returncode, "elapsed_ms": raw.elapsed_ms,
                    "solver_version": raw.solver_version, "timed_out": raw.timed_out,
                    "unavailable": raw.unavailable, "execution": raw.execution.to_dict()})
                checkpoint()
                return raw
            except BaseException as error:
                failures.append(error)
                raise

        backend._runner = observed
        backends.append(backend)
    return backends[0], backends[1], pins


def _raise_execution_failure(*backends: Any) -> None:
    """Restore an owned failure after generic semantic diagnostic conversion."""
    for backend in backends:
        failures = backend._codebase_execution_failures
        if failures:
            raise failures[0]


def verify_current_codebase_unit(
    index: RepositoryCodebaseIndex, repository: str | Path, *, expected_head: Any,
    path: str, contracts: Sequence[Any], bounds: Any = None,
    limits: CodebaseVerificationLimits | None = None, scheduler: Any = None,
    parent_lease: Any = None, cancel_event: Any = None,
    admission_timeout_seconds: float = 30.0, timeout_seconds: float = 120.0,
    memory_mb: int = 512,
) -> CodebaseVerificationRecord:
    """Verify captured source internally, fence the current head, seal a sidecar.

    Only declarative native ContractSpec values are accepted. There is no public
    result, pipeline, backend or checker callback injection. Unsupported sources
    produce a source-bound rejection artifact without launching a solver when
    their native result fits the strict CAS scalar profile. Nonrepresentable
    native results (such as float-literal metadata) fail closed without a codec
    conversion or solver execution.
    A racing edit can leave a historical CAS object, but cannot return a current
    completion. As with structural observation, the fence does not lock source.
    """
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    from ipfs_datasets_py.logic.software_verification.pipeline import SourceToVerificationPipeline, PipelineStatus
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError
    from .codebase_resources import acquire_codebase_resources

    if type(index) is not RepositoryCodebaseIndex or type(index.artifacts) is not ImmutableCAS or index.catalog is None:
        raise CodebaseVerificationError("native codebase index, durable catalog and ImmutableCAS are required")
    if type(expected_head) is not CodebaseHead:
        raise CodebaseVerificationError("expected_head must be an exact native CodebaseHead")
    expected_head = CodebaseHead.from_dict(expected_head.to_dict())
    if (type(path) is not str or not path or PurePosixPath(path).is_absolute()
            or PurePosixPath(path).as_posix() != path or ".." in PurePosixPath(path).parts
            or not path.endswith(".py")):
        raise CodebaseVerificationError("path must be a canonical captured relative Python path")
    if type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise CodebaseVerificationError("timeout_seconds must be finite and positive")
    if (type(admission_timeout_seconds) not in {int, float}
            or not math.isfinite(admission_timeout_seconds) or admission_timeout_seconds < 0):
        raise CodebaseVerificationError("admission_timeout_seconds must be finite and nonnegative")
    if type(memory_mb) is not int or memory_mb <= 0:
        raise CodebaseVerificationError("memory_mb must be a positive exact integer")
    limits = CodebaseVerificationLimits() if limits is None else limits
    if type(limits) is not CodebaseVerificationLimits:
        raise CodebaseVerificationError("limits must be native CodebaseVerificationLimits")
    limits = CodebaseVerificationLimits(**limits.to_dict())
    if limits.max_artifact_bytes > min(index.artifacts.max_object_bytes, memory_mb * 1024 * 1024 // 8):
        raise CodebaseVerificationError("artifact limits exceed the CAS/admission envelope")
    requested_bounds = _bounds(bounds)
    if requested_bounds.max_memory_bytes > memory_mb * 1024 * 1024:
        raise CodebaseVerificationError("solver memory declaration exceeds admission reservation")
    specs = _contracts(contracts, limits)
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, timeout_seconds=min(admission_timeout_seconds, timeout_seconds),
            memory_mb=memory_mb) as lease:
        cancelled = lease.combined_cancellation_signal(cancel_event)

        def checkpoint() -> None:
            if cancelled.is_set():
                raise LeaseCancelledError("codebase verification cancelled")
            if time.monotonic() >= deadline:
                raise LeaseTimeoutError("codebase verification deadline exceeded")

        def observe() -> Any:
            checkpoint()
            return index.observe_current(repository, expected_head=expected_head,
                parent_lease=lease, cancel_event=cancelled, memory_mb=memory_mb,
                admission_timeout_seconds=min(admission_timeout_seconds, deadline - time.monotonic()),
                timeout_seconds=deadline - time.monotonic())

        initial = observe()
        entry, unit, raw = _source_member(index, expected_head, path)
        if len(raw) > limits.max_source_bytes:
            raise CodebaseVerificationError("source byte limit exceeded")
        try:
            source = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise CodebaseVerificationError("captured Python source must be strict UTF-8") from error
        source_binding = {"head": expected_head.to_dict(), "path": path,
            "entry": entry.to_dict(), "ast_cid": unit.ast_cid,
            "content_sha256": hashlib.sha256(raw).hexdigest(),
            "source_revision": "snapshot:" + expected_head.snapshot_cid}
        module_pins = _module_pins()
        checkpoint()
        preflight_pipeline = SourceToVerificationPipeline(bounds=requested_bounds, execute_solvers=False,
                                                         include_supervisor_evidence=False)
        preflight = preflight_pipeline.run(source, path=path, language="python",
            contracts=specs, revision=source_binding["source_revision"])
        _check_result(preflight, source_binding, raw)
        checkpoint()
        artifacts = _solver_artifacts(preflight)
        if (len(artifacts) > limits.max_obligations
                or sum(len(group.obligations) for group in preflight.vc_sets) > limits.max_obligations * 8):
            raise CodebaseVerificationError("verification-condition count exceeds bounds")
        if any(len(item["compilation"]["smtlib"].encode("utf-8")) > limits.max_script_bytes for item in artifacts):
            raise CodebaseVerificationError("SMT script byte limit exceeded")
        try:
            preflight_bytes = canonical_dag_json_bytes(preflight.to_dict())
        except (TypeError, ValueError, RecursionError) as error:
            raise CodebaseVerificationError("native result is outside the strict CAS scalar profile") from error
        if len(preflight_bytes) > limits.max_artifact_bytes // 2:
            raise CodebaseVerificationError("preflight representation exceeds retention bounds")
        observations: list[dict[str, Any]] = []
        executable_pins: list[dict[str, str]] = []
        effective_bounds = requested_bounds
        pipeline = preflight_pipeline
        result = preflight
        stage = "translation_rejected"
        if preflight.status is PipelineStatus.SUCCESS and artifacts:
            # Each call includes admission, version, verdict and applicable
            # model/core phases. Reserve a final source/head fence separately.
            per_call_ms = int((deadline - time.monotonic() - 2) / (2 * len(artifacts)) * 1000)
            if per_call_ms <= 0:
                raise LeaseTimeoutError("insufficient remaining deadline for native solver pair")
            effective_bounds = replace(requested_bounds, timeout_ms=min(requested_bounds.timeout_ms, per_call_ms))
            z3, cvc5, executable_pins = _native_backends(preflight_pipeline.compiler, observations, checkpoint,
                parent_lease=lease, cancel_event=cancelled, deadline=deadline,
                max_script_bytes=limits.max_script_bytes)
            pipeline = SourceToVerificationPipeline(compiler=preflight_pipeline.compiler,
                z3_backend=z3, cvc5_backend=cvc5, bounds=effective_bounds,
                include_supervisor_evidence=False)
            result = pipeline.run(source, path=path, language="python", contracts=specs,
                                  revision=source_binding["source_revision"])
            _raise_execution_failure(z3, cvc5)
            checkpoint()
            _check_result(result, source_binding, raw)
            if (result.program != preflight.program or result.contracts != preflight.contracts
                    or result.vc_sets != preflight.vc_sets or _solver_artifacts(result) != artifacts
                    or len(observations) != len(artifacts) * 2):
                raise CodebaseVerificationError("execution drifted from the bounded native preflight")
            stage = "native_smt"
        if module_pins != _module_pins() or any(
            _digest_file(Path(pin["path"])) != pin["sha256"] or
            (pin["launcher_sha256"] and _digest_file(Path(pin["launcher_path"])) != pin["launcher_sha256"])
            for pin in executable_pins
        ):
            raise CodebaseVerificationError("verification implementation or executable changed during execution")
        final = observe()
        solved_ids = {item.vc_obligation.obligation_id for item in result.obligation_results}
        versions = [{"backend_id": pin["backend_id"], "versions": sorted({
            item["solver_version"] for item in observations if item["backend_id"] == pin["backend_id"]})}
            for pin in executable_pins]
        payload = {"schema": CODEBASE_VERIFICATION_SCHEMA, "profile": CODEBASE_VERIFICATION_PROFILE,
            "authority": dict(_AUTHORITY), "source_binding": source_binding,
            "fence": {"before": initial.head.to_dict(), "after": final.head.to_dict(),
                      "scope": "point_in_time_current_head_and_admitted_source"},
            "limits": limits.to_dict(), "requested_contracts": [item.to_dict() for item in specs],
            "requested_bounds": requested_bounds.to_dict(), "effective_bounds": effective_bounds.to_dict(),
            "environment": {"module_pins": module_pins, "executables": executable_pins,
                            "solver_versions": versions, "network": False},
            "pipeline": pipeline.to_dict(), "pipeline_result": result.to_dict(),
            "post_contract_program": None if result.program is None else result.program.to_dict(),
            "solver_artifacts": _solver_artifacts(result), "process_observations": observations,
            "canonical_keys": [], "coverage": {"selected_obligations": len(solved_ids),
                "unselected_obligation_ids": [item.obligation_id for group in result.vc_sets
                    for item in group.obligations if item.obligation_id not in solved_ids],
                "complete_repository_verification": False}, "execution_stage": stage}
        payload["canonical_keys"] = _canonical_keys(payload)
        encoded = canonical_dag_json_bytes(payload)
        if len(encoded) > limits.max_artifact_bytes:
            raise CodebaseVerificationError("complete evidence artifact exceeds retention bounds")
        checkpoint()
        if index.current(expected_head.repository_id) != expected_head:
            raise StaleCodebaseError("catalog head changed before evidence publication")
        artifact_cid = index.artifacts.put(payload)
        # Publication itself is not an atomic checkout lock. A final reobserve
        # prevents an edit during publication from returning current evidence.
        observe()
        checkpoint()
        return CodebaseVerificationRecord(artifact_cid, encoded, observed_live=True)


def load_codebase_verification(index: RepositoryCodebaseIndex, artifact_cid: str) -> CodebaseVerificationRecord:
    """Replay internal bindings without executing solvers or attesting history.

    Historical source/head generations remain readable after checkout changes.
    Replay requires the current generation or the explicitly reviewed @1 pin
    inventory, with unchanged semantic dependencies and original payload bytes.
    Process observations remain recorded claims, even when parsing them again
    yields the same native classification. ``observed_live`` stays false.
    """
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    from ipfs_datasets_py.logic.software_verification.pipeline import (
        ContractSpec, SourceToVerificationPipeline, PipelineStatus,
    )
    from ipfs_datasets_py.logic.backends.smt.differential import (
        SmtRawSolverOutput, SmtDifferentialVerifier, DifferentialClassification,
        normalize_smtlib_for_solver,
    )
    from ipfs_datasets_py.logic.backends.z3.compiler import Z3SoftwareVerificationBackend
    from ipfs_datasets_py.logic.backends.cvc5.compiler import CVC5SoftwareVerificationBackend
    from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
    if type(index) is not RepositoryCodebaseIndex or type(index.artifacts) is not ImmutableCAS:
        raise CodebaseVerificationError("native codebase index and ImmutableCAS are required")
    payload = index.artifacts.get(artifact_cid)
    legacy = payload.get("schema") == LEGACY_VERIFICATION_SCHEMA
    expected_profile = LEGACY_VERIFICATION_PROFILE if legacy else CODEBASE_VERIFICATION_PROFILE
    if (payload.get("schema") not in {LEGACY_VERIFICATION_SCHEMA, CODEBASE_VERIFICATION_SCHEMA}
            or set(payload) != _FIELDS or payload["profile"] != expected_profile
            or canonical_dag_json_bytes(payload["authority"]) != canonical_dag_json_bytes(_AUTHORITY)):
        raise CodebaseVerificationError("invalid sidecar schema/profile/authority")
    limits = CodebaseVerificationLimits(**payload["limits"])
    encoded = canonical_dag_json_bytes(payload)
    if len(encoded) > min(limits.max_artifact_bytes, index.artifacts.max_object_bytes):
        raise CodebaseVerificationError("historical artifact retention bounds exceeded")
    source = payload["source_binding"]
    path = source["path"]
    if (type(path) is not str or not path or PurePosixPath(path).is_absolute()
            or PurePosixPath(path).as_posix() != path or ".." in PurePosixPath(path).parts
            or not path.endswith(".py")):
        raise CodebaseVerificationError("historical path is outside the Python profile")
    head = CodebaseHead.from_dict(source["head"])
    entry, unit, raw = _source_member(index, head, path)
    if len(raw) > limits.max_source_bytes:
        raise CodebaseVerificationError("historical source byte limit exceeded")
    if source != {"head": head.to_dict(), "path": entry.path, "entry": entry.to_dict(),
                   "ast_cid": unit.ast_cid, "content_sha256": hashlib.sha256(raw).hexdigest(),
                   "source_revision": "snapshot:" + head.snapshot_cid}:
        raise CodebaseVerificationError("historical source binding does not recompute")
    if payload["fence"] != {"before": head.to_dict(), "after": head.to_dict(),
                             "scope": "point_in_time_current_head_and_admitted_source"}:
        raise CodebaseVerificationError("historical fence does not bind the exact head")
    environment = payload["environment"]
    if set(environment) != {"module_pins", "executables", "solver_versions", "network"} or environment["network"] is not False:
        raise CodebaseVerificationError("historical execution environment is invalid")
    current_pins = _module_pins()
    if legacy:
        try:
            validate_legacy_module_pins(environment["module_pins"], current_pins)
        except (TypeError, ValueError, KeyError) as error:
            raise CodebaseVerificationError(str(error)) from error
    elif environment["module_pins"] != current_pins:
        raise CodebaseVerificationError("historical implementation generation differs; explicit migration required")
    requested = ExecutionBounds.from_dict(payload["requested_bounds"])
    effective = ExecutionBounds.from_dict(payload["effective_bounds"])
    if (effective.timeout_ms > requested.timeout_ms or any(
        getattr(effective, name) != getattr(requested, name)
        for name in ("max_steps", "max_memory_bytes", "max_output_bytes")
    )):
        raise CodebaseVerificationError("historical effective bounds differ from the approved envelope")
    specs = _contracts([ContractSpec(**data) for data in payload["requested_contracts"]], limits)
    if [spec.to_dict() for spec in specs] != payload["requested_contracts"]:
        raise CodebaseVerificationError("historical contract fields are not canonical")
    pipeline = SourceToVerificationPipeline(bounds=effective, execute_solvers=False,
                                            include_supervisor_evidence=False)
    replay = pipeline.run(raw.decode("utf-8", errors="strict"), path=path, language="python",
                          contracts=specs, revision=source["source_revision"])
    _check_result(replay, source, raw)
    artifacts = _solver_artifacts(replay)
    if (len(artifacts) > limits.max_obligations
            or sum(len(group.obligations) for group in replay.vc_sets) > limits.max_obligations * 8
            or any(len(item["compilation"]["smtlib"].encode("utf-8")) > limits.max_script_bytes for item in artifacts)
            or artifacts != payload["solver_artifacts"]
            or (None if replay.program is None else replay.program.to_dict()) != payload["post_contract_program"]):
        raise CodebaseVerificationError("historical ProgramIR/VC/SMT/receipt inventory does not recompute")
    observations = payload["process_observations"]
    if payload["execution_stage"] == "native_smt":
        if replay.status is not PipelineStatus.SUCCESS or not artifacts or len(observations) != 2 * len(artifacts):
            raise CodebaseVerificationError("historical native execution inventory is invalid")
        pins = environment["executables"]
        if (len(pins) != 2 or [pin["backend_id"] for pin in pins] != ["z3", "cvc5"]
                or any(set(pin) != {"backend_id", "path", "sha256", "launcher_path", "launcher_sha256"}
                    or type(pin["path"]) is not str or not pin["path"]
                    or type(pin["launcher_path"]) is not str or not pin["launcher_path"]
                    or type(pin["sha256"]) is not str or len(pin["sha256"]) != 64
                    or any(char not in "0123456789abcdef" for char in pin["sha256"])
                    or type(pin["launcher_sha256"]) is not str
                    or (pin["launcher_sha256"] and (len(pin["launcher_sha256"]) != 64
                        or any(char not in "0123456789abcdef" for char in pin["launcher_sha256"]))) for pin in pins)):
            raise CodebaseVerificationError("historical executable pins are invalid")
        # Constructors and raw parsing are inert. A missing recorded version
        # must not cause the native fallback to launch a version probe.
        left = Z3SoftwareVerificationBackend(compiler=pipeline.compiler, version_probe=lambda: "")
        right = CVC5SoftwareVerificationBackend(compiler=pipeline.compiler, version_probe=lambda: "")
        verifier = SmtDifferentialVerifier(left=left, right=right, compiler=pipeline.compiler)
        solved = []
        for ordinal, item in enumerate(replay.obligation_results):
            outcomes = []
            for offset, backend in enumerate((left, right)):
                observation = observations[ordinal * 2 + offset]
                fields = {"backend_id", "executable_sha256", "input_sha256", "bounds",
                    "stdout", "stderr", "returncode", "elapsed_ms", "solver_version", "timed_out", "unavailable"}
                if not legacy:
                    fields.add("execution")
                if (set(observation) != fields
                        or observation["backend_id"] != backend.backend_id
                        or observation["executable_sha256"] != pins[offset]["sha256"]
                        or canonical_dag_json_bytes(observation["bounds"]) != canonical_dag_json_bytes(effective.to_dict())
                        or observation["input_sha256"] != hashlib.sha256(normalize_smtlib_for_solver(
                            item.compilation.smtlib).encode("utf-8")).hexdigest()):
                    raise CodebaseVerificationError("historical process/script/bounds binding is invalid")
                raw_result = SmtRawSolverOutput(**{name: observation[name] for name in (
                    "stdout", "stderr", "returncode", "elapsed_ms", "solver_version", "timed_out", "unavailable")})
                if not legacy:
                    from .codebase_smt_execution import validate_execution_receipt
                    try:
                        validate_execution_receipt(observation["execution"], solver=backend.backend_id,
                            executable=pins[offset]["path"], smtlib=normalize_smtlib_for_solver(item.compilation.smtlib),
                            bounds=effective, raw=raw_result)
                        if any(phase["limits"]["max_input_bytes"] != limits.max_script_bytes
                               for phase in observation["execution"]["phases"]):
                            raise ValueError("native phase input cap differs from sidecar script limit")
                    except (TypeError, ValueError, KeyError) as error:
                        raise CodebaseVerificationError("historical bounded execution receipt is invalid: " + str(error)) from error
                outcomes.append(backend._outcome_from_raw(compilation=item.compilation, bounds=effective, raw=raw_result))
            solved.append(replace(item, differential=verifier._report(item.compilation, *outcomes), solver_executed=True))
        pipeline = replace(pipeline, execute_solvers=True)
        quarantined = any(item.differential.classification is DifferentialClassification.DISAGREE for item in solved)
        replay = replace(replay, obligation_results=tuple(solved), disagreement_quarantined=quarantined,
            status=PipelineStatus.DISAGREEMENT_QUARANTINED if quarantined else PipelineStatus.SUCCESS,
            bindings=pipeline._bindings(adapter=replay.adapter, program=replay.program,
                contracts=replay.contracts, vc_sets=replay.vc_sets, obligation_results=tuple(solved)))
        versions = [{"backend_id": pin["backend_id"], "versions": sorted({
            item["solver_version"] for item in observations if item["backend_id"] == pin["backend_id"]})} for pin in pins]
        if environment["solver_versions"] != versions:
            raise CodebaseVerificationError("historical solver versions do not bind recorded processes")
    elif (payload["execution_stage"] != "translation_rejected" or observations
            or environment["executables"] or environment["solver_versions"]
            or (replay.status is PipelineStatus.SUCCESS and artifacts)):
        raise CodebaseVerificationError("historical translation-only execution inventory is invalid")
    if (canonical_dag_json_bytes(replay.to_dict()) != canonical_dag_json_bytes(payload["pipeline_result"])
            or canonical_dag_json_bytes(pipeline.to_dict()) != canonical_dag_json_bytes(payload["pipeline"])):
        raise CodebaseVerificationError("historical result/classification/bindings do not recompute")
    selected = {item.vc_obligation.obligation_id for item in replay.obligation_results}
    coverage = {"selected_obligations": len(selected), "unselected_obligation_ids": [
        item.obligation_id for group in replay.vc_sets for item in group.obligations
        if item.obligation_id not in selected], "complete_repository_verification": False}
    if canonical_dag_json_bytes(payload["coverage"]) != canonical_dag_json_bytes(coverage):
        raise CodebaseVerificationError("historical coverage does not recompute")
    if payload["canonical_keys"] != _canonical_keys(payload):
        raise CodebaseVerificationError("historical canonical proof keys do not recompute")
    if cid_for_structured(payload) != artifact_cid:
        raise CodebaseVerificationError("historical artifact identity/bounds are invalid")
    return CodebaseVerificationRecord(artifact_cid, encoded)


__all__ = ["CODEBASE_VERIFICATION_SCHEMA", "CODEBASE_VERIFICATION_PROFILE",
           "CodebaseVerificationError", "CodebaseVerificationLimits", "CodebaseVerificationRecord",
           "verify_current_codebase_unit", "load_codebase_verification"]
