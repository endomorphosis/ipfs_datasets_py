"""Canonical Rocq/Coq kernel-checking backend (``RocqKernelBackend@1``).

This adapter is the production boundary for Rocq/Coq theorem generation,
native and WASM capability probing, compilation, proof checking, diagnostics,
and kernel receipts.  It reuses the shared bounded process lifecycle and
dual-plane capability model without editing public exports or advisor code.

Fail-closed rules
-----------------
* an unavailable native or WASM kernel never yields ``PROVED``;
* Rocq/Coq ``admit`` / ``Admitted`` and unclosed assumption reports reject or
  explicitly downgrade authority to a non-theorem candidate;
* kernel receipts bind the exact theorem, imports, generated proof, toolchain,
  source tree, and translation;
* diagnostics are inert and length-bounded.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from ...families.models import EvidenceAuthority
from ...ir_core.claims import FrozenMap, stable_digest
from ...ir_core.protocols import (
    BackendCapabilities,
    BackendRequest,
    ExecutionBounds,
    QueryKind,
    ResourceUsage,
)
from ..process import (
    BoundedToolRunner,
    CancellationSignal,
    ToolRunLimits,
    ToolRunRequest,
    ToolRunResult,
    ToolRuntime,
)
from ..results import (
    CandidateResult,
    ResultAuthority,
    ResultStatus,
    TheoremResult,
    TypedBackendResult,
)
from .wasm import (
    DEFAULT_MAX_SOURCE_BYTES,
    CapabilityPlane,
    DualPlaneCapability,
    KernelCapabilityState,
    KernelSourceTreeBinding,
    KernelToolchainBinding,
    KernelTranslationBinding,
    WasmCapabilityProbe,
    bound_diagnostics,
    content_digest,
    sanitize_diagnostic,
)

ROCQ_KERNEL_BACKEND_VERSION: Final = "RocqKernelBackend@1"
ROCQ_KERNEL_RECEIPT_VERSION: Final = "rocq-kernel-receipt/v1"
ROCQ_SOURCE_BINDING_VERSION: Final = "rocq-source-binding/v1"
ROCQ_ASSUMPTION_REPORT_VERSION: Final = "rocq-assumption-report/v1"

_CLOSED_UNDER_GLOBAL_CONTEXT = "Closed under the global context"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ADMIT = re.compile(r"(?i)\b(?:admit\s*\.|Admitted\s*\.|Abort\s*\.)")
_AXIOM = re.compile(r"(?im)^\s*Axiom\s+")
_IMPORT = re.compile(
    r"^\s*((?:Require\s+(?:Import|Export)\s+.+?\.)|(?:From\s+\S+\s+Require\s+"
    r"(?:Import|Export)\s+.+?\.))\s*$",
    re.MULTILINE,
)
_DECL = re.compile(
    r"^\s*(?:Theorem|Lemma|Fact|Corollary|Remark|Proposition|Example)\s+"
    r"([A-Za-z_][A-Za-z0-9_']*)",
    re.MULTILINE,
)
_GENERATED_PROOF = re.compile(
    r"(?ims)^\s*(?:Theorem|Lemma|Fact|Corollary|Remark|Proposition|Example)\s+"
    r"[A-Za-z_][A-Za-z0-9_']*"
)


class RocqKernelError(ValueError):
    """Raised when a Rocq/Coq kernel request or receipt violates the contract."""


class RocqAuthorityDisposition(StrEnum):
    """How incomplete Rocq/Coq constructs affect result authority."""

    REJECT = "reject"
    DOWNGRADE = "downgrade"


@dataclass(frozen=True, slots=True)
class RocqSourceBinding:
    """Identity of the exact Rocq/Coq source submitted for one request."""

    request_digest: str
    source_digest: str
    source_format: str = "rocq"
    schema_version: str = ROCQ_SOURCE_BINDING_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self, "source_digest", _digest(self.source_digest, "source_digest")
        )
        object.__setattr__(
            self, "source_format", _text(self.source_format, "source_format")
        )
        if self.schema_version != ROCQ_SOURCE_BINDING_VERSION:
            raise RocqKernelError(
                f"unsupported Rocq source binding schema: {self.schema_version!r}"
            )

    @classmethod
    def bind(cls, request: BackendRequest, source: str) -> RocqSourceBinding:
        if not isinstance(request, BackendRequest):
            raise RocqKernelError("request must be a BackendRequest")
        normalized = _source_text(source)
        return cls(
            request_digest=request.digest,
            source_digest=content_digest(normalized),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_format": self.source_format,
        }


@dataclass(frozen=True, slots=True)
class RocqAssumptionReport:
    """Parsed ``Print Assumptions`` outcome for one declaration."""

    declaration: str
    report_text: str
    closed_under_global_context: bool
    schema_version: str = ROCQ_ASSUMPTION_REPORT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "declaration", _text(self.declaration, "declaration")
        )
        object.__setattr__(
            self, "report_text", _text(self.report_text, "report_text", optional=True)
        )
        if not isinstance(self.closed_under_global_context, bool):
            raise RocqKernelError("closed_under_global_context must be a boolean")
        if self.schema_version != ROCQ_ASSUMPTION_REPORT_VERSION:
            raise RocqKernelError(
                f"unsupported assumption report schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "closed_under_global_context": self.closed_under_global_context,
            "declaration": self.declaration,
            "report_text": self.report_text,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class RocqKernelReceipt:
    """Auditable receipt binding every trust-relevant Rocq/Coq check input."""

    request_digest: str
    source_binding: RocqSourceBinding
    theorem_name: str
    theorem_digest: str
    imports: tuple[str, ...]
    generated_proof: str
    generated_proof_digest: str
    toolchain: KernelToolchainBinding
    source_tree: KernelSourceTreeBinding
    translation: KernelTranslationBinding | None
    assumption_report: RocqAssumptionReport | None
    plane: CapabilityPlane
    accepted: bool
    authority_disposition: RocqAuthorityDisposition
    diagnostics: tuple[str, ...] = ()
    schema_version: str = ROCQ_KERNEL_RECEIPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if not isinstance(self.source_binding, RocqSourceBinding):
            raise RocqKernelError("source_binding must be a RocqSourceBinding")
        if self.request_digest != self.source_binding.request_digest:
            raise RocqKernelError("receipt request does not match source binding")
        object.__setattr__(
            self, "theorem_name", _text(self.theorem_name, "theorem_name")
        )
        object.__setattr__(
            self, "theorem_digest", _digest(self.theorem_digest, "theorem_digest")
        )
        imports = tuple(_text(item, "imports item") for item in self.imports)
        if len(imports) != len(set(imports)):
            raise RocqKernelError("imports must not contain duplicates")
        object.__setattr__(self, "imports", imports)
        object.__setattr__(
            self,
            "generated_proof",
            _text(self.generated_proof, "generated_proof", optional=True),
        )
        object.__setattr__(
            self,
            "generated_proof_digest",
            _digest(self.generated_proof_digest, "generated_proof_digest"),
        )
        if not isinstance(self.toolchain, KernelToolchainBinding):
            raise RocqKernelError("toolchain must be a KernelToolchainBinding")
        if not isinstance(self.source_tree, KernelSourceTreeBinding):
            raise RocqKernelError("source_tree must be a KernelSourceTreeBinding")
        if self.translation is not None and not isinstance(
            self.translation, KernelTranslationBinding
        ):
            raise RocqKernelError("translation must be a KernelTranslationBinding")
        if self.assumption_report is not None and not isinstance(
            self.assumption_report, RocqAssumptionReport
        ):
            raise RocqKernelError("assumption_report must be a RocqAssumptionReport")
        object.__setattr__(self, "plane", _enum(self.plane, CapabilityPlane, "plane"))
        if not isinstance(self.accepted, bool):
            raise RocqKernelError("accepted must be a boolean")
        object.__setattr__(
            self,
            "authority_disposition",
            _enum(
                self.authority_disposition,
                RocqAuthorityDisposition,
                "authority_disposition",
            ),
        )
        object.__setattr__(
            self, "diagnostics", bound_diagnostics(self.diagnostics)
        )
        if self.schema_version != ROCQ_KERNEL_RECEIPT_VERSION:
            raise RocqKernelError(
                f"unsupported Rocq kernel receipt schema: {self.schema_version!r}"
            )
        if self.accepted and (
            self.assumption_report is None
            or not self.assumption_report.closed_under_global_context
        ):
            raise RocqKernelError(
                "accepted Rocq receipts require a closed-under-global-context assumption report"
            )

    def _payload(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "assumption_report": (
                self.assumption_report.to_dict()
                if self.assumption_report is not None
                else None
            ),
            "authority_disposition": self.authority_disposition.value,
            "diagnostics": list(self.diagnostics),
            "generated_proof": self.generated_proof,
            "generated_proof_digest": self.generated_proof_digest,
            "imports": list(self.imports),
            "plane": self.plane.value,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "source_binding": self.source_binding.to_dict(),
            "source_tree": self.source_tree.to_dict(),
            "theorem_digest": self.theorem_digest,
            "theorem_name": self.theorem_name,
            "toolchain": self.toolchain.to_dict(),
            "translation": (
                self.translation.to_dict() if self.translation is not None else None
            ),
        }

    @property
    def receipt_id(self) -> str:
        return f"rocq-kernel-receipt:{stable_digest(self._payload())}"

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["receipt_id"] = self.receipt_id
        return payload


@dataclass(frozen=True, slots=True)
class RocqKernelOutcome:
    """Normalized result plus the exact kernel receipt for one request."""

    request_digest: str
    source_binding: RocqSourceBinding
    result: TypedBackendResult
    receipt: RocqKernelReceipt
    capability: DualPlaneCapability
    interface_version: str = ROCQ_KERNEL_BACKEND_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if not isinstance(self.source_binding, RocqSourceBinding):
            raise RocqKernelError("source_binding must be a RocqSourceBinding")
        if not isinstance(self.result, TypedBackendResult):
            raise RocqKernelError("result must be a TypedBackendResult")
        if not isinstance(self.receipt, RocqKernelReceipt):
            raise RocqKernelError("receipt must be a RocqKernelReceipt")
        if not isinstance(self.capability, DualPlaneCapability):
            raise RocqKernelError("capability must be a DualPlaneCapability")
        if self.request_digest != self.source_binding.request_digest:
            raise RocqKernelError("outcome request does not match source binding")
        if self.request_digest != self.receipt.request_digest:
            raise RocqKernelError("outcome request does not match receipt")
        if self.interface_version != ROCQ_KERNEL_BACKEND_VERSION:
            raise RocqKernelError(
                f"unsupported Rocq kernel interface: {self.interface_version!r}"
            )
        if self.result.status is ResultStatus.PROVED and not self.receipt.accepted:
            raise RocqKernelError("proved results require an accepted kernel receipt")

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability.to_dict(),
            "interface_version": self.interface_version,
            "receipt": self.receipt.to_dict(),
            "request_digest": self.request_digest,
            "result": self.result.to_dict(),
            "source_binding": self.source_binding.to_dict(),
        }


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        qualifier = "an empty or " if optional else "a "
        raise RocqKernelError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _digest(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if not _DIGEST.fullmatch(result):
        raise RocqKernelError(f"{field_name} must be a lowercase SHA-256 digest")
    return result


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise RocqKernelError(f"{field_name} must be one of {choices}") from error


def _source_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise RocqKernelError("Rocq source must be non-empty text without NUL bytes")
    if len(value.encode("utf-8")) > DEFAULT_MAX_SOURCE_BYTES:
        raise RocqKernelError("Rocq source exceeds the canonical byte bound")
    return value


def extract_rocq_imports(source: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.strip() for match in _IMPORT.findall(source)))


def extract_rocq_theorem_name(source: str) -> str:
    match = _DECL.search(source)
    if match is None:
        raise RocqKernelError(
            "Rocq/Coq source must contain a Theorem/Lemma-style declaration to check"
        )
    return match.group(1)


def extract_generated_proof(source: str) -> str:
    match = _GENERATED_PROOF.search(source)
    if match is None:
        return source.strip()
    return source[match.start() :].strip()


def scan_rocq_incomplete(source: str) -> tuple[str, ...]:
    findings: list[str] = []
    if _ADMIT.search(source):
        findings.append("rocq_source_contains_admit_or_admitted")
    if _AXIOM.search(source):
        findings.append("rocq_source_contains_unreviewed_axiom")
    return tuple(findings)


def instrument_rocq_source_for_assumptions(source: str, declaration: str) -> str:
    decl = _text(declaration, "declaration")
    return source.rstrip() + f"\n\nPrint Assumptions {decl}.\n"


def parse_rocq_assumption_report(
    stdout: str, declaration: str
) -> RocqAssumptionReport | None:
    text = stdout or ""
    if not text.strip():
        return None
    closed = _CLOSED_UNDER_GLOBAL_CONTEXT in text
    if (
        closed
        or f"Print Assumptions {declaration}" in text
        or declaration in text
        or "Axioms:" in text
        or "Assumptions:" in text
    ):
        return RocqAssumptionReport(
            declaration=declaration,
            report_text=sanitize_diagnostic(text, max_chars=1024),
            closed_under_global_context=closed,
        )
    return None


def evaluate_rocq_kernel_output(
    process: ToolRunResult,
    *,
    declaration: str,
) -> tuple[bool, RocqAssumptionReport | None, tuple[str, ...]]:
    """Decide whether Rocq/Coq accepted a proof without admitted axioms."""

    diagnostics: list[str] = []
    if process.error:
        diagnostics.append(sanitize_diagnostic(process.error))
    if process.timed_out:
        diagnostics.append(
            "rocq/coq invocation timed out under its bounded wall-clock budget"
        )
        return False, None, bound_diagnostics(diagnostics)
    if process.unavailable:
        diagnostics.append("rocq/coq kernel is unavailable")
        return False, None, bound_diagnostics(diagnostics)
    if process.cancelled:
        diagnostics.append("rocq/coq invocation was cancelled")
        return False, None, bound_diagnostics(diagnostics)
    if process.resource_exhausted or process.output_truncated:
        diagnostics.append("rocq/coq invocation exceeded a resource or output bound")
        return False, None, bound_diagnostics(diagnostics)

    combined = f"{process.stdout}\n{process.stderr}"
    if "Error:" in combined:
        excerpt = next(
            (
                sanitize_diagnostic(line, max_chars=200)
                for line in combined.splitlines()
                if "Error:" in line
            ),
            "Error:",
        )
        diagnostics.append(f"rocq/coq reported a compilation error: {excerpt}")
        return False, None, bound_diagnostics(diagnostics)

    if process.returncode not in (0, None) and process.returncode != 0:
        diagnostics.append(
            f"rocq/coq exited with non-zero status {process.returncode}"
        )
        return False, None, bound_diagnostics(diagnostics)

    report = parse_rocq_assumption_report(process.stdout, declaration)
    if report is None:
        if (
            process.returncode == 0
            and _CLOSED_UNDER_GLOBAL_CONTEXT in process.stdout
        ):
            report = RocqAssumptionReport(
                declaration=declaration,
                report_text=sanitize_diagnostic(process.stdout, max_chars=1024),
                closed_under_global_context=True,
            )
        else:
            diagnostics.append(
                "rocq/coq Print Assumptions output did not confirm "
                f"{_CLOSED_UNDER_GLOBAL_CONTEXT!r}; the proof may depend on "
                "an admitted or otherwise extra axiom"
            )
            return False, None, bound_diagnostics(diagnostics)

    if not report.closed_under_global_context:
        diagnostics.append(
            "rocq/coq Print Assumptions did not report "
            f"{_CLOSED_UNDER_GLOBAL_CONTEXT!r}"
        )
        return False, report, bound_diagnostics(diagnostics)

    if process.returncode != 0:
        diagnostics.append(
            f"rocq/coq exited with non-zero status {process.returncode}"
        )
        return False, report, bound_diagnostics(diagnostics)

    return True, report, bound_diagnostics(diagnostics)


def _usage_from_process(process: ToolRunResult) -> ResourceUsage:
    output_bytes = len(process.stdout.encode("utf-8")) + len(
        process.stderr.encode("utf-8")
    )
    return ResourceUsage(
        elapsed_ms=max(0, round(process.elapsed_seconds * 1000)),
        output_bytes=output_bytes,
    )


def _result_id(backend_id: str, request: BackendRequest) -> str:
    return f"result:{backend_id}:{request.digest[:24]}"


def _payload_source(
    request: BackendRequest,
) -> tuple[str, str, KernelTranslationBinding | None]:
    payload = request.payload.to_dict()
    source = (
        payload.get("rocq")
        or payload.get("coq")
        or payload.get("source")
        or payload.get("checked_source")
    )
    source_format = str(payload.get("encoding", "rocq")).strip().lower()
    if source_format not in {"rocq", "coq", "gallina", "vernacular"}:
        raise RocqKernelError(
            f"request encoding {source_format!r} is not a supported Rocq/Coq source format"
        )
    normalized = _source_text(source)
    translation = None
    raw_translation = payload.get("translation")
    if isinstance(raw_translation, Mapping):
        translation = KernelTranslationBinding(
            translation_id=str(raw_translation["translation_id"]),
            translation_digest=str(raw_translation["translation_digest"]),
            source_family=str(
                raw_translation.get("source_family", "software_verification")
            ),
            target_family=str(raw_translation.get("target_family", "rocq")),
            fidelity=str(raw_translation.get("fidelity", "exact")),
        )
    return normalized, source_format, translation


class RocqKernelBackend:
    """Canonical Rocq/Coq kernel backend implementing ``RocqKernelBackend@1``."""

    interface_version: Final = ROCQ_KERNEL_BACKEND_VERSION
    backend_id: Final = "rocq"
    aliases: Final = frozenset({"coq", "rocq-kernel", "coq-kernel"})
    accepted_source_formats: Final = frozenset({"rocq", "coq", "gallina", "vernacular"})
    wasm_module_ids: Final = ("rocq-wasm", "coq-wasm")

    def __init__(
        self,
        *,
        backend_version: str = "rocq",
        executable: str = "coqtop",
        runner: BoundedToolRunner | None = None,
        wasm_probe: WasmCapabilityProbe | None = None,
        native_probe: Callable[[], KernelCapabilityState] | None = None,
        incomplete_disposition: RocqAuthorityDisposition | str = RocqAuthorityDisposition.REJECT,
        logic_families: Sequence[str] = (
            "rocq",
            "coq",
            "cic",
            "dependent_type_theory",
            "higher_order",
            "software_verification",
        ),
    ) -> None:
        self.backend_version = _text(backend_version, "backend_version")
        self.executable = _text(executable, "executable")
        self._runner = runner or BoundedToolRunner()
        if not isinstance(self._runner, BoundedToolRunner):
            raise RocqKernelError("runner must be a BoundedToolRunner")
        self._wasm_probe = wasm_probe or WasmCapabilityProbe()
        if not isinstance(self._wasm_probe, WasmCapabilityProbe):
            raise RocqKernelError("wasm_probe must be a WasmCapabilityProbe")
        if native_probe is not None and not callable(native_probe):
            raise RocqKernelError("native_probe must be callable")
        self._native_probe = native_probe
        self.incomplete_disposition = _enum(
            incomplete_disposition,
            RocqAuthorityDisposition,
            "incomplete_disposition",
        )
        self.capabilities = BackendCapabilities(
            logic_families=tuple(logic_families),
            query_kinds=(QueryKind.THEOREM_PROOF,),
            deterministic=True,
        )

    def supports(self, logic_family: str, query_kind: QueryKind) -> bool:
        return self.capabilities.supports(logic_family, query_kind)

    def probe_native(self) -> KernelCapabilityState:
        if self._native_probe is not None:
            state = self._native_probe()
            if not isinstance(state, KernelCapabilityState):
                raise RocqKernelError("native_probe must return KernelCapabilityState")
            if state.plane is not CapabilityPlane.NATIVE:
                raise RocqKernelError("native_probe must report the native plane")
            return state
        # Prefer coqtop; accept rocq as an informational alias when coqtop is missing.
        if self._runner.is_available(self.executable, runtime=ToolRuntime.NATIVE):
            return KernelCapabilityState.available_native(
                kernel_id=self.backend_id,
                executable=self.executable,
                version=self.backend_version,
            )
        if self.executable != "rocq" and self._runner.is_available(
            "rocq", runtime=ToolRuntime.NATIVE
        ):
            return KernelCapabilityState.available_native(
                kernel_id=self.backend_id,
                executable="rocq",
                version=self.backend_version,
                metadata={"resolved_via": "rocq_alias"},
            )
        return KernelCapabilityState.unavailable(
            plane=CapabilityPlane.NATIVE,
            kernel_id=self.backend_id,
            reason=(
                f"native Rocq/Coq executable {self.executable!r} was not found"
            ),
            executable=self.executable,
        )

    def probe_wasm(self) -> KernelCapabilityState:
        return self._wasm_probe.probe_kernel(
            kernel_id=self.backend_id,
            preferred_module_ids=self.wasm_module_ids,
            plane=CapabilityPlane.WASM,
        )

    def probe_capabilities(self) -> DualPlaneCapability:
        return DualPlaneCapability(
            kernel_id=self.backend_id,
            native=self.probe_native(),
            wasm=self.probe_wasm(),
            browser=self._wasm_probe.probe_kernel(
                kernel_id=self.backend_id,
                preferred_module_ids=self.wasm_module_ids,
                plane=CapabilityPlane.BROWSER,
            ),
        )

    def is_available(self) -> bool:
        """Native availability only — WASM is never collapsed into this flag."""

        return self.probe_native().available

    def _validate_request(self, request: BackendRequest) -> None:
        if not isinstance(request, BackendRequest):
            raise RocqKernelError("request must be a BackendRequest")
        if request.requested_backend_id and request.requested_backend_id not in {
            self.backend_id,
            *self.aliases,
        }:
            raise RocqKernelError(
                f"request targets {request.requested_backend_id!r}, not {self.backend_id!r}"
            )
        if not self.capabilities.supports(request.logic_family, request.query_kind):
            raise RocqKernelError(
                f"{self.backend_id} does not support {request.logic_family}/"
                f"{request.query_kind.value}"
            )
        if request.query_kind is not QueryKind.THEOREM_PROOF:
            raise RocqKernelError(
                "Rocq kernel backend only answers theorem_proof queries"
            )

    def _tool_request(self, source: str, bounds: ExecutionBounds) -> ToolRunRequest:
        instrumented = instrument_rocq_source_for_assumptions(
            source, extract_rocq_theorem_name(source)
        )
        max_workspace_bytes = max(
            bounds.max_output_bytes * 2,
            len(instrumented.encode("utf-8")) + bounds.max_output_bytes + 1024,
        )
        return ToolRunRequest(
            argv=(
                self.executable,
                "-batch",
                "-load-vernac-source",
                "{workspace}/Main.v",
            ),
            runtime=ToolRuntime.NATIVE,
            limits=ToolRunLimits(
                timeout_seconds=bounds.timeout_ms / 1000,
                cpu_seconds=bounds.timeout_ms / 1000,
                memory_bytes=bounds.max_memory_bytes,
                max_output_bytes=bounds.max_output_bytes,
                max_input_bytes=bounds.max_output_bytes,
                max_workspace_bytes=max_workspace_bytes,
            ),
            input_files={"Main.v": instrumented},
        )

    def _build_result(
        self,
        *,
        request: BackendRequest,
        binding: RocqSourceBinding,
        status: ResultStatus,
        usage: ResourceUsage,
        receipt: RocqKernelReceipt,
        capability: DualPlaneCapability,
        reason: str = "",
        diagnostics: Sequence[str] = (),
        candidate_kind: str = "",
    ) -> TypedBackendResult:
        common = {
            "assumptions": request.assumption_ids,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "bounds": request.bounds,
            "diagnostics": bound_diagnostics(diagnostics),
            "metadata": {
                "adapter_interface": ROCQ_KERNEL_BACKEND_VERSION,
                "capability": capability.to_dict(),
                "kernel_receipt": receipt.to_dict(),
                "source_binding": binding.to_dict(),
            },
            "reason": sanitize_diagnostic(reason) if reason else "",
            "result_id": _result_id(self.backend_id, request),
            "status": status,
            "usage": usage,
        }
        if candidate_kind:
            return CandidateResult(
                authority=ResultAuthority.CANDIDATE,
                translation_ceiling=EvidenceAuthority.ADVISORY,
                witness={
                    "candidate_kind": candidate_kind,
                    "receipt_id": receipt.receipt_id,
                    "theorem_name": receipt.theorem_name,
                },
                **common,
            )
        if status is ResultStatus.PROVED and not receipt.accepted:
            raise RocqKernelError("proved theorem results require an accepted receipt")
        return TheoremResult(
            authority=ResultAuthority.THEOREM,
            translation_ceiling=(
                EvidenceAuthority.INDEPENDENTLY_CHECKABLE
                if status is ResultStatus.PROVED
                else EvidenceAuthority.BOUNDED
            ),
            witness={
                "receipt_id": receipt.receipt_id,
                "theorem_name": receipt.theorem_name,
                "theorem_digest": receipt.theorem_digest,
                "generated_proof_digest": receipt.generated_proof_digest,
                "source_tree": receipt.source_tree.to_dict(),
                "toolchain": receipt.toolchain.to_dict(),
                "translation": (
                    receipt.translation.to_dict()
                    if receipt.translation is not None
                    else None
                ),
                "assumption_report": (
                    receipt.assumption_report.to_dict()
                    if receipt.assumption_report is not None
                    else None
                ),
            },
            **common,
        )

    def run(
        self,
        request: BackendRequest,
        *,
        cancellation: CancellationSignal | Any | None = None,
        plane: CapabilityPlane | str = CapabilityPlane.NATIVE,
    ) -> RocqKernelOutcome:
        self._validate_request(request)
        source, _source_format, translation = _payload_source(request)
        binding = RocqSourceBinding.bind(request, source)
        capability = self.probe_capabilities()
        resolved_plane = _enum(plane, CapabilityPlane, "plane")

        theorem_name = extract_rocq_theorem_name(source)
        imports = extract_rocq_imports(source)
        generated_proof = extract_generated_proof(source)
        source_tree = KernelSourceTreeBinding.from_files(
            {"Main.v": source},
            primary_path="Main.v",
        )
        incomplete = scan_rocq_incomplete(source)

        if resolved_plane is CapabilityPlane.NATIVE:
            plane_state = capability.native
            executable = plane_state.executable or self.executable
            toolchain = KernelToolchainBinding(
                toolchain_id=f"toolchain:rocq:native:{self.backend_version}",
                kernel_id=self.backend_id,
                plane=CapabilityPlane.NATIVE,
                executable=executable,
                version=plane_state.version or self.backend_version,
                command_template="{coqtop} -batch -load-vernac-source {source_file}",
            )
        else:
            plane_state = (
                capability.wasm
                if resolved_plane is CapabilityPlane.WASM
                else capability.browser or capability.wasm
            )
            toolchain = KernelToolchainBinding(
                toolchain_id=f"toolchain:rocq:{resolved_plane.value}:{self.backend_version}",
                kernel_id=self.backend_id,
                plane=resolved_plane,
                executable=plane_state.executable,
                module_id=plane_state.module_id or "rocq-wasm",
                version=plane_state.version or self.backend_version,
                command_template="wasm-kernel://{module_id}",
            )

        usage = ResourceUsage()
        diagnostics: list[str] = list(incomplete)

        if not plane_state.available:
            reason = (
                plane_state.reason
                or f"Rocq/Coq kernel plane {resolved_plane.value} is unavailable"
            )
            receipt = RocqKernelReceipt(
                request_digest=request.digest,
                source_binding=binding,
                theorem_name=theorem_name,
                theorem_digest=content_digest(source),
                imports=imports,
                generated_proof=generated_proof,
                generated_proof_digest=content_digest(generated_proof),
                toolchain=toolchain,
                source_tree=source_tree,
                translation=translation,
                assumption_report=None,
                plane=resolved_plane,
                accepted=False,
                authority_disposition=RocqAuthorityDisposition.REJECT,
                diagnostics=bound_diagnostics((*diagnostics, reason)),
            )
            result = self._build_result(
                request=request,
                binding=binding,
                status=ResultStatus.UNAVAILABLE,
                usage=usage,
                receipt=receipt,
                capability=capability,
                reason=reason,
                diagnostics=receipt.diagnostics,
            )
            return RocqKernelOutcome(
                request_digest=request.digest,
                source_binding=binding,
                result=result,
                receipt=receipt,
                capability=capability,
            )

        if incomplete:
            disposition = self.incomplete_disposition
            reason = "; ".join(incomplete)
            receipt = RocqKernelReceipt(
                request_digest=request.digest,
                source_binding=binding,
                theorem_name=theorem_name,
                theorem_digest=content_digest(source),
                imports=imports,
                generated_proof=generated_proof,
                generated_proof_digest=content_digest(generated_proof),
                toolchain=toolchain,
                source_tree=source_tree,
                translation=translation,
                assumption_report=None,
                plane=resolved_plane,
                accepted=False,
                authority_disposition=disposition,
                diagnostics=bound_diagnostics(diagnostics),
            )
            if disposition is RocqAuthorityDisposition.DOWNGRADE:
                result = self._build_result(
                    request=request,
                    binding=binding,
                    status=ResultStatus.CANDIDATE,
                    usage=usage,
                    receipt=receipt,
                    capability=capability,
                    reason=reason,
                    diagnostics=receipt.diagnostics,
                    candidate_kind="incomplete_or_admitted_rocq_proof",
                )
            else:
                result = self._build_result(
                    request=request,
                    binding=binding,
                    status=ResultStatus.MALFORMED,
                    usage=usage,
                    receipt=receipt,
                    capability=capability,
                    reason=reason,
                    diagnostics=receipt.diagnostics,
                )
            return RocqKernelOutcome(
                request_digest=request.digest,
                source_binding=binding,
                result=result,
                receipt=receipt,
                capability=capability,
            )

        if resolved_plane is not CapabilityPlane.NATIVE:
            reason = (
                f"Rocq/Coq kernel plane {resolved_plane.value} is available as a "
                "capability probe only; proof checking remains native-bound until "
                "a reviewed WASM checker is injected"
            )
            receipt = RocqKernelReceipt(
                request_digest=request.digest,
                source_binding=binding,
                theorem_name=theorem_name,
                theorem_digest=content_digest(source),
                imports=imports,
                generated_proof=generated_proof,
                generated_proof_digest=content_digest(generated_proof),
                toolchain=toolchain,
                source_tree=source_tree,
                translation=translation,
                assumption_report=None,
                plane=resolved_plane,
                accepted=False,
                authority_disposition=RocqAuthorityDisposition.REJECT,
                diagnostics=bound_diagnostics((reason,)),
            )
            result = self._build_result(
                request=request,
                binding=binding,
                status=ResultStatus.UNSUPPORTED,
                usage=usage,
                receipt=receipt,
                capability=capability,
                reason=reason,
                diagnostics=receipt.diagnostics,
            )
            return RocqKernelOutcome(
                request_digest=request.digest,
                source_binding=binding,
                result=result,
                receipt=receipt,
                capability=capability,
            )

        process = self._runner.run(
            self._tool_request(source, request.bounds),
            cancellation=cancellation,
            runtime=ToolRuntime.NATIVE,
        )
        usage = _usage_from_process(process)
        accepted, assumption_report, eval_diagnostics = evaluate_rocq_kernel_output(
            process, declaration=theorem_name
        )
        diagnostics.extend(eval_diagnostics)

        if process.unavailable:
            status = ResultStatus.UNAVAILABLE
            reason = process.error or "rocq/coq kernel became unavailable during execution"
            accepted = False
        elif process.timed_out:
            status = ResultStatus.TIMEOUT
            reason = process.error or "rocq/coq kernel exceeded its wall-clock bound"
            accepted = False
        elif process.cancelled:
            status = ResultStatus.ERROR
            reason = process.error or "rocq/coq kernel execution was cancelled"
            accepted = False
        elif not accepted:
            if (
                assumption_report is not None
                and not assumption_report.closed_under_global_context
            ):
                if self.incomplete_disposition is RocqAuthorityDisposition.DOWNGRADE:
                    status = ResultStatus.CANDIDATE
                    reason = "rocq/coq assumptions report is not closed under the global context"
                else:
                    status = ResultStatus.MALFORMED
                    reason = "rocq/coq assumptions report is not closed under the global context"
            else:
                status = ResultStatus.ERROR
                reason = next(
                    iter(eval_diagnostics), "rocq/coq kernel rejected the proof"
                )
        else:
            status = ResultStatus.PROVED
            reason = ""

        receipt = RocqKernelReceipt(
            request_digest=request.digest,
            source_binding=binding,
            theorem_name=theorem_name,
            theorem_digest=content_digest(source),
            imports=imports,
            generated_proof=generated_proof,
            generated_proof_digest=content_digest(generated_proof),
            toolchain=toolchain,
            source_tree=source_tree,
            translation=translation,
            assumption_report=assumption_report,
            plane=resolved_plane,
            accepted=accepted and status is ResultStatus.PROVED,
            authority_disposition=(
                RocqAuthorityDisposition.DOWNGRADE
                if status is ResultStatus.CANDIDATE
                else RocqAuthorityDisposition.REJECT
            ),
            diagnostics=bound_diagnostics(diagnostics),
        )
        result = self._build_result(
            request=request,
            binding=binding,
            status=status,
            usage=usage,
            receipt=receipt,
            capability=capability,
            reason=reason,
            diagnostics=receipt.diagnostics,
            candidate_kind=(
                "incomplete_or_admitted_rocq_proof"
                if status is ResultStatus.CANDIDATE
                else ""
            ),
        )
        return RocqKernelOutcome(
            request_digest=request.digest,
            source_binding=binding,
            result=result,
            receipt=receipt,
            capability=capability,
        )


__all__ = [
    "ROCQ_KERNEL_BACKEND_VERSION",
    "ROCQ_KERNEL_RECEIPT_VERSION",
    "RocqAssumptionReport",
    "RocqAuthorityDisposition",
    "RocqKernelBackend",
    "RocqKernelError",
    "RocqKernelOutcome",
    "RocqKernelReceipt",
    "RocqSourceBinding",
    "evaluate_rocq_kernel_output",
    "extract_generated_proof",
    "extract_rocq_imports",
    "extract_rocq_theorem_name",
    "instrument_rocq_source_for_assumptions",
    "parse_rocq_assumption_report",
    "scan_rocq_incomplete",
]
