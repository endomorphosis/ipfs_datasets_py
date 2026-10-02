"""Canonical Lean 4 kernel-checking backend (``LeanKernelBackend@1``).

This adapter is the production boundary for Lean theorem generation, native
and WASM capability probing, compilation, proof checking, diagnostics, and
kernel receipts.  It reuses the shared bounded process lifecycle and dual-plane
capability model without editing public exports or advisor code.

Fail-closed rules
-----------------
* an unavailable native or WASM kernel never yields ``PROVED``;
* Lean ``sorry`` / ``admit`` / ``sorryAx`` and ``unsafe`` axioms reject or
  explicitly downgrade authority to a non-theorem candidate;
* kernel receipts bind the exact theorem, imports, generated proof, toolchain,
  source tree, and translation;
* diagnostics are inert and length-bounded.
"""

from __future__ import annotations

import json
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

LEAN_KERNEL_BACKEND_VERSION: Final = "LeanKernelBackend@1"
LEAN_KERNEL_RECEIPT_VERSION: Final = "lean-kernel-receipt/v1"
LEAN_SOURCE_BINDING_VERSION: Final = "lean-source-binding/v1"
LEAN_AXIOM_REPORT_VERSION: Final = "lean-axiom-report/v1"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SORRY = re.compile(r"(?<![A-Za-z0-9_'])(?:sorry|admit|sorryAx)(?![A-Za-z0-9_'])")
_UNSAFE = re.compile(
    r"(?im)^\s*(?:unsafe\s+(?:def|theorem|inductive|structure|abbrev)|"
    r"axiom\s+|constant\s+)"
)
_IMPORT = re.compile(r"^\s*import\s+(\S+)\s*$", re.MULTILINE)
_DECL = re.compile(
    r"^\s*(?:theorem|lemma)\s+([A-Za-z_][A-Za-z0-9_'.]*)",
    re.MULTILINE,
)
_GENERATED_PROOF = re.compile(
    r"(?ims)^\s*(?:theorem|lemma)\s+[A-Za-z_][A-Za-z0-9_'.]*[^=]*=\s*by\b"
)


class LeanKernelError(ValueError):
    """Raised when a Lean kernel request or receipt violates the contract."""


class LeanAuthorityDisposition(StrEnum):
    """How incomplete or unsafe Lean constructs affect result authority."""

    REJECT = "reject"
    DOWNGRADE = "downgrade"


@dataclass(frozen=True, slots=True)
class LeanSourceBinding:
    """Identity of the exact Lean source submitted for one request."""

    request_digest: str
    source_digest: str
    source_format: str = "lean4"
    schema_version: str = LEAN_SOURCE_BINDING_VERSION

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
        if self.schema_version != LEAN_SOURCE_BINDING_VERSION:
            raise LeanKernelError(
                f"unsupported Lean source binding schema: {self.schema_version!r}"
            )

    @classmethod
    def bind(cls, request: BackendRequest, source: str) -> LeanSourceBinding:
        if not isinstance(request, BackendRequest):
            raise LeanKernelError("request must be a BackendRequest")
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
class LeanAxiomReport:
    """Parsed ``#print axioms`` outcome for one declaration."""

    declaration: str
    report_text: str
    axioms: tuple[str, ...]
    contains_sorry_ax: bool
    schema_version: str = LEAN_AXIOM_REPORT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "declaration", _text(self.declaration, "declaration")
        )
        object.__setattr__(
            self, "report_text", _text(self.report_text, "report_text", optional=True)
        )
        axioms = tuple(_text(item, "axioms item") for item in self.axioms)
        if len(axioms) != len(set(axioms)):
            raise LeanKernelError("axioms must not contain duplicates")
        object.__setattr__(self, "axioms", axioms)
        if not isinstance(self.contains_sorry_ax, bool):
            raise LeanKernelError("contains_sorry_ax must be a boolean")
        if self.schema_version != LEAN_AXIOM_REPORT_VERSION:
            raise LeanKernelError(
                f"unsupported axiom report schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "axioms": list(self.axioms),
            "contains_sorry_ax": self.contains_sorry_ax,
            "declaration": self.declaration,
            "report_text": self.report_text,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class LeanKernelReceipt:
    """Auditable receipt binding every trust-relevant Lean check input."""

    request_digest: str
    source_binding: LeanSourceBinding
    theorem_name: str
    theorem_digest: str
    imports: tuple[str, ...]
    generated_proof: str
    generated_proof_digest: str
    toolchain: KernelToolchainBinding
    source_tree: KernelSourceTreeBinding
    translation: KernelTranslationBinding | None
    axiom_report: LeanAxiomReport | None
    plane: CapabilityPlane
    accepted: bool
    authority_disposition: LeanAuthorityDisposition
    diagnostics: tuple[str, ...] = ()
    schema_version: str = LEAN_KERNEL_RECEIPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if not isinstance(self.source_binding, LeanSourceBinding):
            raise LeanKernelError("source_binding must be a LeanSourceBinding")
        if self.request_digest != self.source_binding.request_digest:
            raise LeanKernelError("receipt request does not match source binding")
        object.__setattr__(
            self, "theorem_name", _text(self.theorem_name, "theorem_name")
        )
        object.__setattr__(
            self, "theorem_digest", _digest(self.theorem_digest, "theorem_digest")
        )
        imports = tuple(_text(item, "imports item") for item in self.imports)
        if len(imports) != len(set(imports)):
            raise LeanKernelError("imports must not contain duplicates")
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
            raise LeanKernelError("toolchain must be a KernelToolchainBinding")
        if not isinstance(self.source_tree, KernelSourceTreeBinding):
            raise LeanKernelError("source_tree must be a KernelSourceTreeBinding")
        if self.translation is not None and not isinstance(
            self.translation, KernelTranslationBinding
        ):
            raise LeanKernelError("translation must be a KernelTranslationBinding")
        if self.axiom_report is not None and not isinstance(
            self.axiom_report, LeanAxiomReport
        ):
            raise LeanKernelError("axiom_report must be a LeanAxiomReport")
        object.__setattr__(self, "plane", _enum(self.plane, CapabilityPlane, "plane"))
        if not isinstance(self.accepted, bool):
            raise LeanKernelError("accepted must be a boolean")
        object.__setattr__(
            self,
            "authority_disposition",
            _enum(
                self.authority_disposition,
                LeanAuthorityDisposition,
                "authority_disposition",
            ),
        )
        object.__setattr__(
            self, "diagnostics", bound_diagnostics(self.diagnostics)
        )
        if self.schema_version != LEAN_KERNEL_RECEIPT_VERSION:
            raise LeanKernelError(
                f"unsupported Lean kernel receipt schema: {self.schema_version!r}"
            )
        if self.accepted and self.authority_disposition is not LeanAuthorityDisposition.REJECT:
            if self.axiom_report is None or self.axiom_report.contains_sorry_ax:
                raise LeanKernelError(
                    "accepted Lean receipts require a sorry-free axiom report"
                )

    def _payload(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "authority_disposition": self.authority_disposition.value,
            "axiom_report": (
                self.axiom_report.to_dict() if self.axiom_report is not None else None
            ),
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
        return f"lean-kernel-receipt:{stable_digest(self._payload())}"

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["receipt_id"] = self.receipt_id
        return payload


@dataclass(frozen=True, slots=True)
class LeanKernelOutcome:
    """Normalized result plus the exact kernel receipt for one request."""

    request_digest: str
    source_binding: LeanSourceBinding
    result: TypedBackendResult
    receipt: LeanKernelReceipt
    capability: DualPlaneCapability
    interface_version: str = LEAN_KERNEL_BACKEND_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if not isinstance(self.source_binding, LeanSourceBinding):
            raise LeanKernelError("source_binding must be a LeanSourceBinding")
        if not isinstance(self.result, TypedBackendResult):
            raise LeanKernelError("result must be a TypedBackendResult")
        if not isinstance(self.receipt, LeanKernelReceipt):
            raise LeanKernelError("receipt must be a LeanKernelReceipt")
        if not isinstance(self.capability, DualPlaneCapability):
            raise LeanKernelError("capability must be a DualPlaneCapability")
        if self.request_digest != self.source_binding.request_digest:
            raise LeanKernelError("outcome request does not match source binding")
        if self.request_digest != self.receipt.request_digest:
            raise LeanKernelError("outcome request does not match receipt")
        if self.interface_version != LEAN_KERNEL_BACKEND_VERSION:
            raise LeanKernelError(
                f"unsupported Lean kernel interface: {self.interface_version!r}"
            )
        if (
            self.result.status is ResultStatus.PROVED
            and not self.receipt.accepted
        ):
            raise LeanKernelError("proved results require an accepted kernel receipt")

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
        raise LeanKernelError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _digest(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if not _DIGEST.fullmatch(result):
        raise LeanKernelError(f"{field_name} must be a lowercase SHA-256 digest")
    return result


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise LeanKernelError(f"{field_name} must be one of {choices}") from error


def _source_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise LeanKernelError("Lean source must be non-empty text without NUL bytes")
    if len(value.encode("utf-8")) > DEFAULT_MAX_SOURCE_BYTES:
        raise LeanKernelError("Lean source exceeds the canonical byte bound")
    return value


def extract_lean_imports(source: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_IMPORT.findall(source)))


def extract_lean_theorem_name(source: str) -> str:
    match = _DECL.search(source)
    if match is None:
        raise LeanKernelError(
            "Lean source must contain a theorem/lemma declaration to check"
        )
    return match.group(1).rstrip(".")


def extract_generated_proof(source: str) -> str:
    """Best-effort extraction of the checked proof body for receipt binding."""

    match = _GENERATED_PROOF.search(source)
    if match is None:
        return source.strip()
    start = match.start()
    return source[start:].strip()


def scan_lean_incomplete_or_unsafe(source: str) -> tuple[str, ...]:
    """Return diagnostic codes for sorry/unsafe constructs in source text."""

    findings: list[str] = []
    if _SORRY.search(source):
        findings.append("lean_source_contains_sorry_or_admit")
    if _UNSAFE.search(source):
        findings.append("lean_source_contains_unsafe_or_unreviewed_axiom")
    return tuple(findings)


def instrument_lean_source_for_axioms(source: str, declaration: str) -> str:
    """Append a ``#print axioms`` command used to detect hidden ``sorryAx``."""

    decl = _text(declaration, "declaration")
    body = source.rstrip() + f"\n\n#print axioms {decl}\n"
    return body


def parse_lean_json_messages(stdout: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if not isinstance(stdout, str):
        return messages
    for raw_line in stdout.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            messages.append(payload)
    return messages


def parse_lean_axiom_report(
    stdout: str, declaration: str
) -> LeanAxiomReport | None:
    messages = parse_lean_json_messages(stdout)
    marker = f"'{declaration}'"
    for message in messages:
        data = str(message.get("data", ""))
        if marker not in data:
            continue
        if (
            "depends on axioms" not in data
            and "does not depend on any axioms" not in data
        ):
            continue
        axioms: list[str] = []
        if "depends on axioms:" in data:
            tail = data.split("depends on axioms:", 1)[1]
            for token in re.split(r"[\s,]+", tail.strip()):
                token = token.strip(" .")
                if token:
                    axioms.append(token)
        contains_sorry = "sorryAx" in data or any(
            axiom == "sorryAx" for axiom in axioms
        )
        return LeanAxiomReport(
            declaration=declaration,
            report_text=sanitize_diagnostic(data, max_chars=1024),
            axioms=tuple(dict.fromkeys(axioms)),
            contains_sorry_ax=contains_sorry,
        )
    # Non-JSON fallback for injected runners in tests.
    plain = stdout or ""
    if f"#print axioms {declaration}" in plain or f"'{declaration}'" in plain:
        if "does not depend on any axioms" in plain:
            return LeanAxiomReport(
                declaration=declaration,
                report_text=sanitize_diagnostic(plain, max_chars=1024),
                axioms=(),
                contains_sorry_ax=False,
            )
        if "depends on axioms" in plain or "sorryAx" in plain:
            axioms = tuple(
                token
                for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_'.]*\b", plain)
                if token not in {"depends", "on", "axioms", "print", declaration}
            )
            return LeanAxiomReport(
                declaration=declaration,
                report_text=sanitize_diagnostic(plain, max_chars=1024),
                axioms=axioms,
                contains_sorry_ax="sorryAx" in plain,
            )
    return None


def evaluate_lean_kernel_output(
    process: ToolRunResult,
    *,
    declaration: str,
) -> tuple[bool, LeanAxiomReport | None, tuple[str, ...]]:
    """Decide whether Lean accepted a proof without incomplete/unsafe axioms."""

    diagnostics: list[str] = []
    if process.error:
        diagnostics.append(sanitize_diagnostic(process.error))
    if process.timed_out:
        diagnostics.append("lean invocation timed out under its bounded wall-clock budget")
        return False, None, bound_diagnostics(diagnostics)
    if process.unavailable:
        diagnostics.append("lean kernel is unavailable")
        return False, None, bound_diagnostics(diagnostics)
    if process.cancelled:
        diagnostics.append("lean invocation was cancelled")
        return False, None, bound_diagnostics(diagnostics)
    if process.resource_exhausted or process.output_truncated:
        diagnostics.append("lean invocation exceeded a resource or output bound")
        return False, None, bound_diagnostics(diagnostics)

    messages = parse_lean_json_messages(process.stdout)
    error_messages = [m for m in messages if m.get("severity") == "error"]
    if error_messages:
        excerpt = "; ".join(
            sanitize_diagnostic(str(m.get("data", "")), max_chars=200)
            for m in error_messages[:4]
        )
        diagnostics.append(f"lean reported error diagnostics: {excerpt}")
        return False, None, bound_diagnostics(diagnostics)

    combined = f"{process.stdout}\n{process.stderr}"
    if re.search(r"(?i)\berror\b", combined) and process.returncode not in (0, None):
        diagnostics.append(
            sanitize_diagnostic(combined.splitlines()[0] if combined.strip() else "error")
        )

    if process.returncode not in (0, None) and process.returncode != 0:
        diagnostics.append(f"lean exited with non-zero status {process.returncode}")
        return False, None, bound_diagnostics(diagnostics)

    if process.returncode is None and not process.stdout and not process.stderr:
        diagnostics.append("lean produced no exit status or output")
        return False, None, bound_diagnostics(diagnostics)

    axiom_report = parse_lean_axiom_report(process.stdout, declaration)
    if axiom_report is None:
        # Allow plain successful text runners that emit the required markers.
        if (
            process.returncode == 0
            and "does not depend on any axioms" in process.stdout
            and "sorryAx" not in process.stdout
        ):
            axiom_report = LeanAxiomReport(
                declaration=declaration,
                report_text=sanitize_diagnostic(process.stdout, max_chars=1024),
                axioms=(),
                contains_sorry_ax=False,
            )
        else:
            diagnostics.append(
                f"lean produced no `#print axioms {declaration}` result; "
                "cannot confirm the proof is free of sorryAx"
            )
            return False, None, bound_diagnostics(diagnostics)

    if axiom_report.contains_sorry_ax:
        diagnostics.append(
            f"`#print axioms {declaration}` reports sorryAx; the proof still "
            "depends on an unresolved sorry"
        )
        return False, axiom_report, bound_diagnostics(diagnostics)

    if process.returncode != 0:
        diagnostics.append(f"lean exited with non-zero status {process.returncode}")
        return False, axiom_report, bound_diagnostics(diagnostics)

    return True, axiom_report, bound_diagnostics(diagnostics)


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


def _payload_source(request: BackendRequest) -> tuple[str, str, KernelTranslationBinding | None]:
    payload = request.payload.to_dict()
    source = payload.get("lean") or payload.get("source") or payload.get("checked_source")
    source_format = str(payload.get("encoding", "lean4")).strip().lower()
    if source_format not in {"lean", "lean4", "lean4-source"}:
        raise LeanKernelError(
            f"request encoding {source_format!r} is not a supported Lean source format"
        )
    normalized = _source_text(source)
    translation = None
    raw_translation = payload.get("translation")
    if isinstance(raw_translation, Mapping):
        translation = KernelTranslationBinding(
            translation_id=str(raw_translation.get("translation_id", "")),
            translation_digest=str(raw_translation.get("translation_digest", "")),
            source_family=str(raw_translation.get("source_family", "software_verification")),
            target_family=str(raw_translation.get("target_family", "lean4")),
            fidelity=str(raw_translation.get("fidelity", "exact")),
            metadata=FrozenMap(
                {
                    key: value
                    for key, value in raw_translation.items()
                    if key
                    not in {
                        "translation_id",
                        "translation_digest",
                        "source_family",
                        "target_family",
                        "fidelity",
                    }
                }
            )
            if any(
                key
                not in {
                    "translation_id",
                    "translation_digest",
                    "source_family",
                    "target_family",
                    "fidelity",
                }
                for key in raw_translation
            )
            else FrozenMap(),
        )
    return normalized, source_format, translation


class LeanKernelBackend:
    """Canonical Lean 4 kernel backend implementing ``LeanKernelBackend@1``."""

    interface_version: Final = LEAN_KERNEL_BACKEND_VERSION
    backend_id: Final = "lean"
    aliases: Final = frozenset({"lean4", "lean-kernel"})
    accepted_source_formats: Final = frozenset({"lean", "lean4", "lean4-source"})
    wasm_module_ids: Final = ("lean4-wasm",)

    def __init__(
        self,
        *,
        backend_version: str = "lean4",
        executable: str = "lean",
        runner: BoundedToolRunner | None = None,
        wasm_probe: WasmCapabilityProbe | None = None,
        native_probe: Callable[[], KernelCapabilityState] | None = None,
        incomplete_disposition: LeanAuthorityDisposition | str = LeanAuthorityDisposition.REJECT,
        logic_families: Sequence[str] = (
            "lean",
            "lean4",
            "dependent_type_theory",
            "higher_order",
            "software_verification",
        ),
    ) -> None:
        self.backend_version = _text(backend_version, "backend_version")
        self.executable = _text(executable, "executable")
        self._runner = runner or BoundedToolRunner()
        if not isinstance(self._runner, BoundedToolRunner):
            raise LeanKernelError("runner must be a BoundedToolRunner")
        self._wasm_probe = wasm_probe or WasmCapabilityProbe()
        if not isinstance(self._wasm_probe, WasmCapabilityProbe):
            raise LeanKernelError("wasm_probe must be a WasmCapabilityProbe")
        if native_probe is not None and not callable(native_probe):
            raise LeanKernelError("native_probe must be callable")
        self._native_probe = native_probe
        self.incomplete_disposition = _enum(
            incomplete_disposition,
            LeanAuthorityDisposition,
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
                raise LeanKernelError("native_probe must return KernelCapabilityState")
            if state.plane is not CapabilityPlane.NATIVE:
                raise LeanKernelError("native_probe must report the native plane")
            return state
        if self._runner.is_available(self.executable, runtime=ToolRuntime.NATIVE):
            return KernelCapabilityState.available_native(
                kernel_id=self.backend_id,
                executable=self.executable,
                version=self.backend_version,
            )
        return KernelCapabilityState.unavailable(
            plane=CapabilityPlane.NATIVE,
            kernel_id=self.backend_id,
            reason=f"native Lean executable {self.executable!r} was not found",
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
            raise LeanKernelError("request must be a BackendRequest")
        if request.requested_backend_id and request.requested_backend_id not in {
            self.backend_id,
            *self.aliases,
        }:
            raise LeanKernelError(
                f"request targets {request.requested_backend_id!r}, not {self.backend_id!r}"
            )
        if not self.capabilities.supports(request.logic_family, request.query_kind):
            raise LeanKernelError(
                f"{self.backend_id} does not support {request.logic_family}/"
                f"{request.query_kind.value}"
            )
        if request.query_kind is not QueryKind.THEOREM_PROOF:
            raise LeanKernelError("Lean kernel backend only answers theorem_proof queries")

    def _tool_request(self, source: str, bounds: ExecutionBounds) -> ToolRunRequest:
        instrumented = instrument_lean_source_for_axioms(
            source, extract_lean_theorem_name(source)
        )
        max_workspace_bytes = max(
            bounds.max_output_bytes * 2,
            len(instrumented.encode("utf-8")) + bounds.max_output_bytes + 1024,
        )
        return ToolRunRequest(
            argv=(self.executable, "--json", "{workspace}/Main.lean"),
            runtime=ToolRuntime.NATIVE,
            limits=ToolRunLimits(
                timeout_seconds=bounds.timeout_ms / 1000,
                cpu_seconds=bounds.timeout_ms / 1000,
                memory_bytes=bounds.max_memory_bytes,
                max_output_bytes=bounds.max_output_bytes,
                max_input_bytes=bounds.max_output_bytes,
                max_workspace_bytes=max_workspace_bytes,
            ),
            input_files={"Main.lean": instrumented},
        )

    def _build_result(
        self,
        *,
        request: BackendRequest,
        binding: LeanSourceBinding,
        status: ResultStatus,
        usage: ResourceUsage,
        receipt: LeanKernelReceipt,
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
                "adapter_interface": LEAN_KERNEL_BACKEND_VERSION,
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
            raise LeanKernelError("proved theorem results require an accepted receipt")
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
                "axiom_report": (
                    receipt.axiom_report.to_dict()
                    if receipt.axiom_report is not None
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
    ) -> LeanKernelOutcome:
        self._validate_request(request)
        source, _source_format, translation = _payload_source(request)
        binding = LeanSourceBinding.bind(request, source)
        capability = self.probe_capabilities()
        resolved_plane = _enum(plane, CapabilityPlane, "plane")

        theorem_name = extract_lean_theorem_name(source)
        imports = extract_lean_imports(source)
        generated_proof = extract_generated_proof(source)
        source_tree = KernelSourceTreeBinding.from_files(
            {"Main.lean": source},
            primary_path="Main.lean",
        )
        incomplete = scan_lean_incomplete_or_unsafe(source)

        if resolved_plane is CapabilityPlane.NATIVE:
            plane_state = capability.native
            toolchain = KernelToolchainBinding(
                toolchain_id=f"toolchain:lean:native:{self.backend_version}",
                kernel_id=self.backend_id,
                plane=CapabilityPlane.NATIVE,
                executable=plane_state.executable or self.executable,
                version=plane_state.version or self.backend_version,
                command_template="{lean} --json {source_file}",
            )
        else:
            plane_state = (
                capability.wasm
                if resolved_plane is CapabilityPlane.WASM
                else capability.browser or capability.wasm
            )
            toolchain = KernelToolchainBinding(
                toolchain_id=f"toolchain:lean:{resolved_plane.value}:{self.backend_version}",
                kernel_id=self.backend_id,
                plane=resolved_plane,
                executable=plane_state.executable,
                module_id=plane_state.module_id or "lean4-wasm",
                version=plane_state.version or self.backend_version,
                command_template="wasm-kernel://{module_id}",
            )

        usage = ResourceUsage()
        axiom_report: LeanAxiomReport | None = None
        diagnostics: list[str] = list(incomplete)

        if not plane_state.available:
            reason = plane_state.reason or f"Lean kernel plane {resolved_plane.value} is unavailable"
            receipt = LeanKernelReceipt(
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
                axiom_report=None,
                plane=resolved_plane,
                accepted=False,
                authority_disposition=LeanAuthorityDisposition.REJECT,
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
            return LeanKernelOutcome(
                request_digest=request.digest,
                source_binding=binding,
                result=result,
                receipt=receipt,
                capability=capability,
            )

        if incomplete:
            disposition = self.incomplete_disposition
            reason = "; ".join(incomplete)
            receipt = LeanKernelReceipt(
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
                axiom_report=None,
                plane=resolved_plane,
                accepted=False,
                authority_disposition=disposition,
                diagnostics=bound_diagnostics(diagnostics),
            )
            if disposition is LeanAuthorityDisposition.DOWNGRADE:
                result = self._build_result(
                    request=request,
                    binding=binding,
                    status=ResultStatus.CANDIDATE,
                    usage=usage,
                    receipt=receipt,
                    capability=capability,
                    reason=reason,
                    diagnostics=receipt.diagnostics,
                    candidate_kind="incomplete_or_unsafe_lean_proof",
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
            return LeanKernelOutcome(
                request_digest=request.digest,
                source_binding=binding,
                result=result,
                receipt=receipt,
                capability=capability,
            )

        if resolved_plane is not CapabilityPlane.NATIVE:
            reason = (
                f"Lean kernel plane {resolved_plane.value} is available as a capability "
                "probe only; proof checking remains native-bound until a reviewed WASM "
                "checker is injected"
            )
            receipt = LeanKernelReceipt(
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
                axiom_report=None,
                plane=resolved_plane,
                accepted=False,
                authority_disposition=LeanAuthorityDisposition.REJECT,
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
            return LeanKernelOutcome(
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
        accepted, axiom_report, eval_diagnostics = evaluate_lean_kernel_output(
            process, declaration=theorem_name
        )
        diagnostics.extend(eval_diagnostics)

        if process.unavailable:
            status = ResultStatus.UNAVAILABLE
            reason = process.error or "lean kernel became unavailable during execution"
            accepted = False
        elif process.timed_out:
            status = ResultStatus.TIMEOUT
            reason = process.error or "lean kernel exceeded its wall-clock bound"
            accepted = False
        elif process.cancelled:
            status = ResultStatus.ERROR
            reason = process.error or "lean kernel execution was cancelled"
            accepted = False
        elif not accepted:
            if axiom_report is not None and axiom_report.contains_sorry_ax:
                if self.incomplete_disposition is LeanAuthorityDisposition.DOWNGRADE:
                    status = ResultStatus.CANDIDATE
                    reason = "lean axiom report contains sorryAx"
                else:
                    status = ResultStatus.MALFORMED
                    reason = "lean axiom report contains sorryAx"
            else:
                status = ResultStatus.ERROR
                reason = next(iter(eval_diagnostics), "lean kernel rejected the proof")
        else:
            status = ResultStatus.PROVED
            reason = ""

        receipt = LeanKernelReceipt(
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
            axiom_report=axiom_report,
            plane=resolved_plane,
            accepted=accepted and status is ResultStatus.PROVED,
            authority_disposition=(
                LeanAuthorityDisposition.DOWNGRADE
                if status is ResultStatus.CANDIDATE
                else LeanAuthorityDisposition.REJECT
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
                "incomplete_or_unsafe_lean_proof"
                if status is ResultStatus.CANDIDATE
                else ""
            ),
        )
        return LeanKernelOutcome(
            request_digest=request.digest,
            source_binding=binding,
            result=result,
            receipt=receipt,
            capability=capability,
        )


__all__ = [
    "LEAN_KERNEL_BACKEND_VERSION",
    "LEAN_KERNEL_RECEIPT_VERSION",
    "LeanAuthorityDisposition",
    "LeanAxiomReport",
    "LeanKernelBackend",
    "LeanKernelError",
    "LeanKernelOutcome",
    "LeanKernelReceipt",
    "LeanSourceBinding",
    "evaluate_lean_kernel_output",
    "extract_generated_proof",
    "extract_lean_imports",
    "extract_lean_theorem_name",
    "instrument_lean_source_for_axioms",
    "parse_lean_axiom_report",
    "scan_lean_incomplete_or_unsafe",
]
