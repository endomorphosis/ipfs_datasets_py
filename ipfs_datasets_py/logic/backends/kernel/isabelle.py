"""Canonical Isabelle/HOL kernel-checking backend (``IsabelleKernelBackend@1``).

This adapter is the production boundary for Isabelle theorem checking, native
capability probing, path-metadata correction, proof checking, diagnostics, and
kernel receipts.  It reuses the shared bounded process lifecycle and dual-plane
capability model without editing public exports or advisor code.

Fail-closed rules
-----------------
* an unavailable native kernel never yields ``PROVED``;
* Isabelle ``sorry`` / ``oops`` and unreviewed ``axiomatization`` reject or
  explicitly downgrade authority to a non-theorem candidate;
* kernel receipts bind the exact theorem, imports, generated proof, toolchain,
  source tree (with **corrected** theory/session path metadata), and
  translation;
* diagnostics are inert and length-bounded.

Path metadata correction
------------------------
Isabelle requires the theory file name to match the ``theory NAME`` header
exactly (``NAME.thy``). Callers historically pass placeholder names such as
``Goal.thy``.  This backend always derives:

* ``theory_name`` from the theory header;
* ``theory_path`` as ``{theory_name}.thy``;
* ``session_dir`` as the workspace root that hosts that theory file;
* the process argv ``isabelle process -T {theory_name} -d {session_dir}``.

Those corrected fields are what appear on receipts and source-tree bindings.
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

ISABELLE_KERNEL_BACKEND_VERSION: Final = "IsabelleKernelBackend@1"
ISABELLE_KERNEL_RECEIPT_VERSION: Final = "isabelle-kernel-receipt/v1"
ISABELLE_SOURCE_BINDING_VERSION: Final = "isabelle-source-binding/v1"
ISABELLE_PATH_METADATA_VERSION: Final = "isabelle-path-metadata/v1"
ISABELLE_AXIOM_REPORT_VERSION: Final = "isabelle-axiom-report/v1"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SORRY = re.compile(r"(?<![A-Za-z0-9_'])(?:sorry|oops)(?![A-Za-z0-9_'])")
_AXIOMATIZATION = re.compile(
    r"(?im)^\s*(?:axiomatization\b|axioms?\s+|consts?\s+[^\n]*where\b)"
)
_THEORY = re.compile(r"^\s*theory\s+([A-Za-z_][A-Za-z0-9_'.]*)", re.MULTILINE)
_IMPORTS = re.compile(r"^\s*imports\s+(.+)$", re.MULTILINE)
_DECL = re.compile(
    r"^\s*(?:theorem|lemma|corollary|proposition)\s+([A-Za-z_][A-Za-z0-9_'.]*)",
    re.MULTILINE,
)
_ERROR_MARKER = re.compile(r"\*\*\*")
_GENERATED_PROOF = re.compile(
    r"(?ims)^\s*(?:theorem|lemma|corollary|proposition)\s+[A-Za-z_][A-Za-z0-9_'.]*"
)


class IsabelleKernelError(ValueError):
    """Raised when an Isabelle kernel request or receipt violates the contract."""


class IsabelleAuthorityDisposition(StrEnum):
    """How incomplete or unreviewed Isabelle constructs affect result authority."""

    REJECT = "reject"
    DOWNGRADE = "downgrade"


@dataclass(frozen=True, slots=True)
class IsabellePathMetadata:
    """Corrected Isabelle theory/session path identity for one check.

    Historical callers often supply a placeholder path such as ``Goal.thy``
    that does not match the theory header.  This record always reflects the
    *corrected* identity Isabelle requires.
    """

    theory_name: str
    theory_path: str
    session_dir: str
    command_template: str = "{isabelle} process -T {theory_name} -d {session_dir}"
    caller_path: str = ""
    corrected: bool = False
    schema_version: str = ISABELLE_PATH_METADATA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "theory_name", _text(self.theory_name, "theory_name")
        )
        theory_path = _text(self.theory_path, "theory_path")
        expected = f"{self.theory_name}.thy"
        if theory_path != expected and not theory_path.endswith(f"/{expected}"):
            raise IsabelleKernelError(
                f"theory_path must be {expected!r} (or a path ending with it); "
                f"got {theory_path!r}"
            )
        object.__setattr__(self, "theory_path", theory_path)
        object.__setattr__(
            self, "session_dir", _text(self.session_dir, "session_dir")
        )
        object.__setattr__(
            self,
            "command_template",
            _text(self.command_template, "command_template"),
        )
        object.__setattr__(
            self, "caller_path", _text(self.caller_path, "caller_path", optional=True)
        )
        if not isinstance(self.corrected, bool):
            raise IsabelleKernelError("corrected must be a boolean")
        if self.schema_version != ISABELLE_PATH_METADATA_VERSION:
            raise IsabelleKernelError(
                f"unsupported Isabelle path metadata schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "caller_path": self.caller_path,
            "command_template": self.command_template,
            "corrected": self.corrected,
            "schema_version": self.schema_version,
            "session_dir": self.session_dir,
            "theory_name": self.theory_name,
            "theory_path": self.theory_path,
        }


@dataclass(frozen=True, slots=True)
class IsabelleSourceBinding:
    """Identity of the exact Isabelle source submitted for one request."""

    request_digest: str
    source_digest: str
    source_format: str = "isabelle"
    path_metadata: IsabellePathMetadata | None = None
    schema_version: str = ISABELLE_SOURCE_BINDING_VERSION

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
        if self.path_metadata is not None and not isinstance(
            self.path_metadata, IsabellePathMetadata
        ):
            raise IsabelleKernelError(
                "path_metadata must be an IsabellePathMetadata when provided"
            )
        if self.schema_version != ISABELLE_SOURCE_BINDING_VERSION:
            raise IsabelleKernelError(
                f"unsupported Isabelle source binding schema: {self.schema_version!r}"
            )

    @classmethod
    def bind(
        cls,
        request: BackendRequest,
        source: str,
        *,
        path_metadata: IsabellePathMetadata | None = None,
    ) -> IsabelleSourceBinding:
        if not isinstance(request, BackendRequest):
            raise IsabelleKernelError("request must be a BackendRequest")
        normalized = _source_text(source)
        return cls(
            request_digest=request.digest,
            source_digest=content_digest(normalized),
            path_metadata=path_metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_metadata": (
                self.path_metadata.to_dict() if self.path_metadata is not None else None
            ),
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_format": self.source_format,
        }


@dataclass(frozen=True, slots=True)
class IsabelleAxiomReport:
    """Parsed residual-axiom / sorry outcome for one declaration."""

    declaration: str
    report_text: str
    residual_axioms: tuple[str, ...]
    contains_sorry: bool
    contains_unreviewed_axiomatization: bool
    schema_version: str = ISABELLE_AXIOM_REPORT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "declaration", _text(self.declaration, "declaration")
        )
        object.__setattr__(
            self, "report_text", _text(self.report_text, "report_text", optional=True)
        )
        axioms = tuple(_text(item, "residual_axioms item") for item in self.residual_axioms)
        if len(axioms) != len(set(axioms)):
            raise IsabelleKernelError("residual_axioms must not contain duplicates")
        object.__setattr__(self, "residual_axioms", axioms)
        if not isinstance(self.contains_sorry, bool):
            raise IsabelleKernelError("contains_sorry must be a boolean")
        if not isinstance(self.contains_unreviewed_axiomatization, bool):
            raise IsabelleKernelError(
                "contains_unreviewed_axiomatization must be a boolean"
            )
        if self.schema_version != ISABELLE_AXIOM_REPORT_VERSION:
            raise IsabelleKernelError(
                f"unsupported axiom report schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contains_sorry": self.contains_sorry,
            "contains_unreviewed_axiomatization": self.contains_unreviewed_axiomatization,
            "declaration": self.declaration,
            "report_text": self.report_text,
            "residual_axioms": list(self.residual_axioms),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class IsabelleKernelReceipt:
    """Auditable receipt binding every trust-relevant Isabelle check input."""

    request_digest: str
    source_binding: IsabelleSourceBinding
    theorem_name: str
    theorem_digest: str
    imports: tuple[str, ...]
    generated_proof: str
    generated_proof_digest: str
    toolchain: KernelToolchainBinding
    source_tree: KernelSourceTreeBinding
    path_metadata: IsabellePathMetadata
    translation: KernelTranslationBinding | None
    axiom_report: IsabelleAxiomReport | None
    plane: CapabilityPlane
    accepted: bool
    authority_disposition: IsabelleAuthorityDisposition
    diagnostics: tuple[str, ...] = ()
    schema_version: str = ISABELLE_KERNEL_RECEIPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if not isinstance(self.source_binding, IsabelleSourceBinding):
            raise IsabelleKernelError("source_binding must be an IsabelleSourceBinding")
        if self.request_digest != self.source_binding.request_digest:
            raise IsabelleKernelError("receipt request does not match source binding")
        object.__setattr__(
            self, "theorem_name", _text(self.theorem_name, "theorem_name")
        )
        object.__setattr__(
            self, "theorem_digest", _digest(self.theorem_digest, "theorem_digest")
        )
        imports = tuple(_text(item, "imports item") for item in self.imports)
        if len(imports) != len(set(imports)):
            raise IsabelleKernelError("imports must not contain duplicates")
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
            raise IsabelleKernelError("toolchain must be a KernelToolchainBinding")
        if not isinstance(self.source_tree, KernelSourceTreeBinding):
            raise IsabelleKernelError("source_tree must be a KernelSourceTreeBinding")
        if not isinstance(self.path_metadata, IsabellePathMetadata):
            raise IsabelleKernelError("path_metadata must be an IsabellePathMetadata")
        if self.path_metadata.theory_path != self.source_tree.primary_path:
            raise IsabelleKernelError(
                "source_tree.primary_path must equal corrected path_metadata.theory_path"
            )
        if self.translation is not None and not isinstance(
            self.translation, KernelTranslationBinding
        ):
            raise IsabelleKernelError("translation must be a KernelTranslationBinding")
        if self.axiom_report is not None and not isinstance(
            self.axiom_report, IsabelleAxiomReport
        ):
            raise IsabelleKernelError("axiom_report must be an IsabelleAxiomReport")
        object.__setattr__(self, "plane", _enum(self.plane, CapabilityPlane, "plane"))
        if not isinstance(self.accepted, bool):
            raise IsabelleKernelError("accepted must be a boolean")
        object.__setattr__(
            self,
            "authority_disposition",
            _enum(
                self.authority_disposition,
                IsabelleAuthorityDisposition,
                "authority_disposition",
            ),
        )
        object.__setattr__(self, "diagnostics", bound_diagnostics(self.diagnostics))
        if self.schema_version != ISABELLE_KERNEL_RECEIPT_VERSION:
            raise IsabelleKernelError(
                f"unsupported Isabelle kernel receipt schema: {self.schema_version!r}"
            )
        if self.accepted and self.authority_disposition is not IsabelleAuthorityDisposition.REJECT:
            if (
                self.axiom_report is None
                or self.axiom_report.contains_sorry
                or self.axiom_report.contains_unreviewed_axiomatization
            ):
                raise IsabelleKernelError(
                    "accepted Isabelle receipts require a sorry-free, "
                    "axiomatization-reviewed axiom report"
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
            "path_metadata": self.path_metadata.to_dict(),
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
        return f"isabelle-kernel-receipt:{stable_digest(self._payload())}"

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["receipt_id"] = self.receipt_id
        return payload


@dataclass(frozen=True, slots=True)
class IsabelleKernelOutcome:
    """Normalized result plus the exact kernel receipt for one request."""

    request_digest: str
    source_binding: IsabelleSourceBinding
    result: TypedBackendResult
    receipt: IsabelleKernelReceipt
    capability: DualPlaneCapability
    interface_version: str = ISABELLE_KERNEL_BACKEND_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if not isinstance(self.source_binding, IsabelleSourceBinding):
            raise IsabelleKernelError("source_binding must be an IsabelleSourceBinding")
        if not isinstance(self.result, TypedBackendResult):
            raise IsabelleKernelError("result must be a TypedBackendResult")
        if not isinstance(self.receipt, IsabelleKernelReceipt):
            raise IsabelleKernelError("receipt must be an IsabelleKernelReceipt")
        if not isinstance(self.capability, DualPlaneCapability):
            raise IsabelleKernelError("capability must be a DualPlaneCapability")
        if self.request_digest != self.source_binding.request_digest:
            raise IsabelleKernelError("outcome request does not match source binding")
        if self.request_digest != self.receipt.request_digest:
            raise IsabelleKernelError("outcome request does not match receipt")
        if self.interface_version != ISABELLE_KERNEL_BACKEND_VERSION:
            raise IsabelleKernelError(
                f"unsupported Isabelle kernel interface: {self.interface_version!r}"
            )
        if self.result.status is ResultStatus.PROVED and not self.receipt.accepted:
            raise IsabelleKernelError("proved results require an accepted kernel receipt")

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
        raise IsabelleKernelError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _digest(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if not _DIGEST.fullmatch(result):
        raise IsabelleKernelError(f"{field_name} must be a lowercase SHA-256 digest")
    return result


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise IsabelleKernelError(f"{field_name} must be one of {choices}") from error


def _source_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise IsabelleKernelError(
            "Isabelle source must be non-empty text without NUL bytes"
        )
    if len(value.encode("utf-8")) > DEFAULT_MAX_SOURCE_BYTES:
        raise IsabelleKernelError("Isabelle source exceeds the canonical byte bound")
    return value


def extract_isabelle_theory_name(source: str) -> str:
    match = _THEORY.search(source)
    if match is None:
        raise IsabelleKernelError(
            "Isabelle source must contain a `theory NAME` header to correct path metadata"
        )
    return match.group(1).rstrip(".")


def extract_isabelle_imports(source: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _IMPORTS.finditer(source):
        for token in re.split(r"[\s,]+", match.group(1).strip()):
            token = token.strip()
            if token and token not in found:
                found.append(token)
    return tuple(found)


def extract_isabelle_theorem_name(source: str) -> str:
    match = _DECL.search(source)
    if match is None:
        raise IsabelleKernelError(
            "Isabelle source must contain a theorem/lemma declaration to check"
        )
    return match.group(1).rstrip(".")


def extract_generated_proof(source: str) -> str:
    """Best-effort extraction of the checked proof body for receipt binding."""

    match = _GENERATED_PROOF.search(source)
    if match is None:
        return source.strip()
    return source[match.start() :].strip()


def scan_isabelle_incomplete_or_unreviewed(source: str) -> tuple[str, ...]:
    """Return diagnostic codes for sorry/oops/unreviewed axiomatization."""

    findings: list[str] = []
    if _SORRY.search(source):
        findings.append("isabelle_source_contains_sorry_or_oops")
    if _AXIOMATIZATION.search(source):
        findings.append("isabelle_source_contains_unreviewed_axiomatization")
    return tuple(findings)


def correct_isabelle_path_metadata(
    source: str,
    *,
    caller_path: str = "",
    session_dir: str = ".",
) -> IsabellePathMetadata:
    """Derive the corrected theory path Isabelle requires from the source.

    If ``caller_path`` already matches ``{theory_name}.thy`` (basename), the
    record is marked ``corrected=False``.  Any other path (including the
    historical default ``Goal.thy``) is rewritten and marked ``corrected=True``.
    """

    theory_name = extract_isabelle_theory_name(source)
    theory_path = f"{theory_name}.thy"
    session = _text(session_dir or ".", "session_dir")
    caller = _text(caller_path, "caller_path", optional=True)
    caller_base = caller.rsplit("/", 1)[-1] if caller else ""
    needs_correction = not caller or caller_base != theory_path
    return IsabellePathMetadata(
        theory_name=theory_name,
        theory_path=theory_path,
        session_dir=session,
        caller_path=caller,
        corrected=needs_correction,
    )


def evaluate_isabelle_kernel_output(
    process: ToolRunResult,
    *,
    declaration: str,
    source: str,
) -> tuple[bool, IsabelleAxiomReport | None, tuple[str, ...]]:
    """Decide whether Isabelle accepted a proof without incomplete constructs."""

    diagnostics: list[str] = []
    if process.error:
        diagnostics.append(sanitize_diagnostic(process.error))
    if process.timed_out:
        diagnostics.append(
            "isabelle invocation timed out under its bounded wall-clock budget"
        )
        return False, None, bound_diagnostics(diagnostics)
    if process.unavailable:
        diagnostics.append("isabelle kernel is unavailable")
        return False, None, bound_diagnostics(diagnostics)
    if process.cancelled:
        diagnostics.append("isabelle invocation was cancelled")
        return False, None, bound_diagnostics(diagnostics)
    if process.resource_exhausted or process.output_truncated:
        diagnostics.append("isabelle invocation exceeded a resource or output bound")
        return False, None, bound_diagnostics(diagnostics)

    combined = f"{process.stdout}\n{process.stderr}"
    residual_sorry = bool(_SORRY.search(combined)) or bool(_SORRY.search(source))
    residual_axioms = tuple(
        sorted(
            {
                token
                for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_'.]*\b", combined)
                if token
                in {
                    "sorry",
                    "oops",
                    "undefined",
                    "axiomatization",
                }
            }
        )
    )
    contains_unreviewed = bool(_AXIOMATIZATION.search(source)) or (
        "axiomatization" in residual_axioms
    )
    report = IsabelleAxiomReport(
        declaration=declaration,
        report_text=sanitize_diagnostic(combined, max_chars=1024),
        residual_axioms=residual_axioms,
        contains_sorry=residual_sorry,
        contains_unreviewed_axiomatization=contains_unreviewed,
    )

    if process.returncode not in (0, None) and process.returncode != 0:
        diagnostics.append(f"isabelle exited with non-zero status {process.returncode}")
        return False, report, bound_diagnostics(diagnostics)

    if _ERROR_MARKER.search(combined):
        diagnostics.append("isabelle reported an error diagnostic (`*** ...`)")
        return False, report, bound_diagnostics(diagnostics)

    if "Failed" in combined:
        diagnostics.append("isabelle reported a failure diagnostic")
        return False, report, bound_diagnostics(diagnostics)

    if residual_sorry:
        diagnostics.append(
            f"isabelle output or source still references sorry/oops for {declaration}"
        )
        return False, report, bound_diagnostics(diagnostics)

    if contains_unreviewed:
        diagnostics.append(
            "isabelle source contains unreviewed axiomatization; "
            "cannot grant theorem authority"
        )
        return False, report, bound_diagnostics(diagnostics)

    if process.returncode is None and not process.stdout and not process.stderr:
        diagnostics.append("isabelle produced no exit status or output")
        return False, None, bound_diagnostics(diagnostics)

    if process.returncode != 0:
        diagnostics.append(f"isabelle exited with non-zero status {process.returncode}")
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
) -> tuple[str, str, str, KernelTranslationBinding | None]:
    payload = request.payload.to_dict()
    source = (
        payload.get("isabelle")
        or payload.get("source")
        or payload.get("checked_source")
        or payload.get("theory")
    )
    source_format = str(payload.get("encoding", "isabelle")).strip().lower()
    if source_format not in {
        "isabelle",
        "isabelle-hol",
        "isar",
        "thy",
        "isabelle-source",
    }:
        raise IsabelleKernelError(
            f"request encoding {source_format!r} is not a supported Isabelle source format"
        )
    normalized = _source_text(source)
    caller_path = str(
        payload.get("path")
        or payload.get("file_name")
        or payload.get("theory_path")
        or payload.get("primary_path")
        or ""
    ).strip()
    translation = None
    raw_translation = payload.get("translation")
    if isinstance(raw_translation, Mapping):
        translation = KernelTranslationBinding(
            translation_id=str(raw_translation.get("translation_id", "")),
            translation_digest=str(raw_translation.get("translation_digest", "")),
            source_family=str(
                raw_translation.get("source_family", "software_verification")
            ),
            target_family=str(raw_translation.get("target_family", "isabelle")),
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
    return normalized, source_format, caller_path, translation


class IsabelleKernelBackend:
    """Canonical Isabelle/HOL kernel backend implementing ``IsabelleKernelBackend@1``."""

    interface_version: Final = ISABELLE_KERNEL_BACKEND_VERSION
    backend_id: Final = "isabelle"
    aliases: Final = frozenset({"isabelle-hol", "isabelle-kernel", "isar"})
    accepted_source_formats: Final = frozenset(
        {"isabelle", "isabelle-hol", "isar", "thy", "isabelle-source"}
    )
    wasm_module_ids: Final = ("isabelle-wasm",)

    def __init__(
        self,
        *,
        backend_version: str = "isabelle",
        executable: str = "isabelle",
        runner: BoundedToolRunner | None = None,
        wasm_probe: WasmCapabilityProbe | None = None,
        native_probe: Callable[[], KernelCapabilityState] | None = None,
        incomplete_disposition: IsabelleAuthorityDisposition
        | str = IsabelleAuthorityDisposition.REJECT,
        logic_families: Sequence[str] = (
            "isabelle",
            "isabelle-hol",
            "higher_order",
            "hol",
            "software_verification",
        ),
        session_dir: str = ".",
    ) -> None:
        self.backend_version = _text(backend_version, "backend_version")
        self.executable = _text(executable, "executable")
        self.session_dir = _text(session_dir or ".", "session_dir")
        self._runner = runner or BoundedToolRunner()
        if not isinstance(self._runner, BoundedToolRunner):
            raise IsabelleKernelError("runner must be a BoundedToolRunner")
        self._wasm_probe = wasm_probe or WasmCapabilityProbe()
        if not isinstance(self._wasm_probe, WasmCapabilityProbe):
            raise IsabelleKernelError("wasm_probe must be a WasmCapabilityProbe")
        if native_probe is not None and not callable(native_probe):
            raise IsabelleKernelError("native_probe must be callable")
        self._native_probe = native_probe
        self.incomplete_disposition = _enum(
            incomplete_disposition,
            IsabelleAuthorityDisposition,
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
                raise IsabelleKernelError(
                    "native_probe must return KernelCapabilityState"
                )
            if state.plane is not CapabilityPlane.NATIVE:
                raise IsabelleKernelError("native_probe must report the native plane")
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
            reason=f"native Isabelle executable {self.executable!r} was not found",
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
            raise IsabelleKernelError("request must be a BackendRequest")
        if request.requested_backend_id and request.requested_backend_id not in {
            self.backend_id,
            *self.aliases,
        }:
            raise IsabelleKernelError(
                f"request targets {request.requested_backend_id!r}, not {self.backend_id!r}"
            )
        if not self.capabilities.supports(request.logic_family, request.query_kind):
            raise IsabelleKernelError(
                f"{self.backend_id} does not support {request.logic_family}/"
                f"{request.query_kind.value}"
            )
        if request.query_kind is not QueryKind.THEOREM_PROOF:
            raise IsabelleKernelError(
                "Isabelle kernel backend only answers theorem_proof queries"
            )

    def _tool_request(
        self, source: str, bounds: ExecutionBounds, path_metadata: IsabellePathMetadata
    ) -> ToolRunRequest:
        max_workspace_bytes = max(
            bounds.max_output_bytes * 2,
            len(source.encode("utf-8")) + bounds.max_output_bytes + 1024,
        )
        # Isabelle requires the theory file basename to match the theory header.
        # Path metadata is already corrected; write under the corrected name and
        # point -d at the private workspace (session root).
        return ToolRunRequest(
            argv=(
                self.executable,
                "process",
                "-T",
                path_metadata.theory_name,
                "-d",
                "{workspace}",
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
            input_files={path_metadata.theory_path: source},
        )

    def _build_result(
        self,
        *,
        request: BackendRequest,
        binding: IsabelleSourceBinding,
        status: ResultStatus,
        usage: ResourceUsage,
        receipt: IsabelleKernelReceipt,
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
                "adapter_interface": ISABELLE_KERNEL_BACKEND_VERSION,
                "capability": capability.to_dict(),
                "kernel_receipt": receipt.to_dict(),
                "path_metadata": receipt.path_metadata.to_dict(),
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
                    "path_metadata": receipt.path_metadata.to_dict(),
                },
                **common,
            )
        if status is ResultStatus.PROVED and not receipt.accepted:
            raise IsabelleKernelError("proved theorem results require an accepted receipt")
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
                "path_metadata": receipt.path_metadata.to_dict(),
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
    ) -> IsabelleKernelOutcome:
        self._validate_request(request)
        source, _source_format, caller_path, translation = _payload_source(request)
        path_metadata = correct_isabelle_path_metadata(
            source,
            caller_path=caller_path,
            session_dir=self.session_dir,
        )
        binding = IsabelleSourceBinding.bind(
            request, source, path_metadata=path_metadata
        )
        capability = self.probe_capabilities()
        resolved_plane = _enum(plane, CapabilityPlane, "plane")

        theorem_name = extract_isabelle_theorem_name(source)
        imports = extract_isabelle_imports(source)
        generated_proof = extract_generated_proof(source)
        source_tree = KernelSourceTreeBinding.from_files(
            {path_metadata.theory_path: source},
            primary_path=path_metadata.theory_path,
        )
        incomplete = scan_isabelle_incomplete_or_unreviewed(source)

        if resolved_plane is CapabilityPlane.NATIVE:
            plane_state = capability.native
            toolchain = KernelToolchainBinding(
                toolchain_id=f"toolchain:isabelle:native:{self.backend_version}",
                kernel_id=self.backend_id,
                plane=CapabilityPlane.NATIVE,
                executable=plane_state.executable or self.executable,
                version=plane_state.version or self.backend_version,
                command_template=path_metadata.command_template,
                metadata=FrozenMap(
                    {
                        "theory_name": path_metadata.theory_name,
                        "theory_path": path_metadata.theory_path,
                        "session_dir": path_metadata.session_dir,
                        "path_metadata_corrected": path_metadata.corrected,
                    }
                ),
            )
        else:
            plane_state = (
                capability.wasm
                if resolved_plane is CapabilityPlane.WASM
                else capability.browser or capability.wasm
            )
            toolchain = KernelToolchainBinding(
                toolchain_id=(
                    f"toolchain:isabelle:{resolved_plane.value}:{self.backend_version}"
                ),
                kernel_id=self.backend_id,
                plane=resolved_plane,
                executable=plane_state.executable,
                module_id=plane_state.module_id or "isabelle-wasm",
                version=plane_state.version or self.backend_version,
                command_template="wasm-kernel://{module_id}",
            )

        usage = ResourceUsage()
        axiom_report: IsabelleAxiomReport | None = None
        diagnostics: list[str] = list(incomplete)
        if path_metadata.corrected:
            diagnostics.append(
                sanitize_diagnostic(
                    "isabelle path metadata corrected: "
                    f"caller_path={path_metadata.caller_path or '<empty>'} -> "
                    f"{path_metadata.theory_path}"
                )
            )

        if not plane_state.available:
            reason = (
                plane_state.reason
                or f"Isabelle kernel plane {resolved_plane.value} is unavailable"
            )
            receipt = IsabelleKernelReceipt(
                request_digest=request.digest,
                source_binding=binding,
                theorem_name=theorem_name,
                theorem_digest=content_digest(source),
                imports=imports,
                generated_proof=generated_proof,
                generated_proof_digest=content_digest(generated_proof),
                toolchain=toolchain,
                source_tree=source_tree,
                path_metadata=path_metadata,
                translation=translation,
                axiom_report=None,
                plane=resolved_plane,
                accepted=False,
                authority_disposition=IsabelleAuthorityDisposition.REJECT,
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
            return IsabelleKernelOutcome(
                request_digest=request.digest,
                source_binding=binding,
                result=result,
                receipt=receipt,
                capability=capability,
            )

        if incomplete:
            disposition = self.incomplete_disposition
            reason = "; ".join(incomplete)
            receipt = IsabelleKernelReceipt(
                request_digest=request.digest,
                source_binding=binding,
                theorem_name=theorem_name,
                theorem_digest=content_digest(source),
                imports=imports,
                generated_proof=generated_proof,
                generated_proof_digest=content_digest(generated_proof),
                toolchain=toolchain,
                source_tree=source_tree,
                path_metadata=path_metadata,
                translation=translation,
                axiom_report=None,
                plane=resolved_plane,
                accepted=False,
                authority_disposition=disposition,
                diagnostics=bound_diagnostics(diagnostics),
            )
            if disposition is IsabelleAuthorityDisposition.DOWNGRADE:
                result = self._build_result(
                    request=request,
                    binding=binding,
                    status=ResultStatus.CANDIDATE,
                    usage=usage,
                    receipt=receipt,
                    capability=capability,
                    reason=reason,
                    diagnostics=receipt.diagnostics,
                    candidate_kind="incomplete_or_unreviewed_isabelle_proof",
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
            return IsabelleKernelOutcome(
                request_digest=request.digest,
                source_binding=binding,
                result=result,
                receipt=receipt,
                capability=capability,
            )

        if resolved_plane is not CapabilityPlane.NATIVE:
            reason = (
                f"Isabelle kernel plane {resolved_plane.value} is available as a "
                "capability probe only; proof checking remains native-bound until a "
                "reviewed WASM checker is injected"
            )
            receipt = IsabelleKernelReceipt(
                request_digest=request.digest,
                source_binding=binding,
                theorem_name=theorem_name,
                theorem_digest=content_digest(source),
                imports=imports,
                generated_proof=generated_proof,
                generated_proof_digest=content_digest(generated_proof),
                toolchain=toolchain,
                source_tree=source_tree,
                path_metadata=path_metadata,
                translation=translation,
                axiom_report=None,
                plane=resolved_plane,
                accepted=False,
                authority_disposition=IsabelleAuthorityDisposition.REJECT,
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
            return IsabelleKernelOutcome(
                request_digest=request.digest,
                source_binding=binding,
                result=result,
                receipt=receipt,
                capability=capability,
            )

        process = self._runner.run(
            self._tool_request(source, request.bounds, path_metadata),
            cancellation=cancellation,
            runtime=ToolRuntime.NATIVE,
        )
        usage = _usage_from_process(process)
        accepted, axiom_report, eval_diagnostics = evaluate_isabelle_kernel_output(
            process, declaration=theorem_name, source=source
        )
        diagnostics.extend(eval_diagnostics)

        if process.unavailable:
            status = ResultStatus.UNAVAILABLE
            reason = process.error or "isabelle kernel became unavailable during execution"
            accepted = False
        elif process.timed_out:
            status = ResultStatus.TIMEOUT
            reason = process.error or "isabelle kernel exceeded its wall-clock bound"
            accepted = False
        elif process.cancelled:
            status = ResultStatus.ERROR
            reason = process.error or "isabelle kernel execution was cancelled"
            accepted = False
        elif not accepted:
            if axiom_report is not None and (
                axiom_report.contains_sorry
                or axiom_report.contains_unreviewed_axiomatization
            ):
                if self.incomplete_disposition is IsabelleAuthorityDisposition.DOWNGRADE:
                    status = ResultStatus.CANDIDATE
                    reason = (
                        "isabelle proof still contains sorry/oops or unreviewed "
                        "axiomatization"
                    )
                else:
                    status = ResultStatus.MALFORMED
                    reason = (
                        "isabelle proof still contains sorry/oops or unreviewed "
                        "axiomatization"
                    )
            else:
                status = ResultStatus.ERROR
                reason = next(
                    iter(eval_diagnostics), "isabelle kernel rejected the proof"
                )
        else:
            status = ResultStatus.PROVED
            reason = ""

        receipt = IsabelleKernelReceipt(
            request_digest=request.digest,
            source_binding=binding,
            theorem_name=theorem_name,
            theorem_digest=content_digest(source),
            imports=imports,
            generated_proof=generated_proof,
            generated_proof_digest=content_digest(generated_proof),
            toolchain=toolchain,
            source_tree=source_tree,
            path_metadata=path_metadata,
            translation=translation,
            axiom_report=axiom_report,
            plane=resolved_plane,
            accepted=accepted and status is ResultStatus.PROVED,
            authority_disposition=(
                IsabelleAuthorityDisposition.DOWNGRADE
                if status is ResultStatus.CANDIDATE
                else IsabelleAuthorityDisposition.REJECT
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
                "incomplete_or_unreviewed_isabelle_proof"
                if status is ResultStatus.CANDIDATE
                else ""
            ),
        )
        return IsabelleKernelOutcome(
            request_digest=request.digest,
            source_binding=binding,
            result=result,
            receipt=receipt,
            capability=capability,
        )


__all__ = [
    "ISABELLE_KERNEL_BACKEND_VERSION",
    "ISABELLE_KERNEL_RECEIPT_VERSION",
    "ISABELLE_PATH_METADATA_VERSION",
    "IsabelleAuthorityDisposition",
    "IsabelleAxiomReport",
    "IsabelleKernelBackend",
    "IsabelleKernelError",
    "IsabelleKernelOutcome",
    "IsabelleKernelReceipt",
    "IsabellePathMetadata",
    "IsabelleSourceBinding",
    "correct_isabelle_path_metadata",
    "evaluate_isabelle_kernel_output",
    "extract_generated_proof",
    "extract_isabelle_imports",
    "extract_isabelle_theorem_name",
    "extract_isabelle_theory_name",
    "scan_isabelle_incomplete_or_unreviewed",
]
