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
* diagnostics are inert and length-bounded;
* v3 checks the instantiated expected-obligation theorem and observed native
  executable/version identity; v1/v2 receipts remain archival, never upgraded;
* availability probes remain metadata-only; trusted identity fixture callbacks
  are explicit and establish no genuine native execution or corpus admission.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
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
    _is_cancelled as _tool_is_cancelled,
)
from ..results import (
    CandidateResult,
    ResultAuthority,
    ResultStatus,
    TheoremResult,
    TypedBackendResult,
)
from ..resource_admission import ResourceAdmittedToolRunner
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
LEAN_KERNEL_RECEIPT_VERSION: Final = "lean-kernel-receipt/v3"
LEAN_SOURCE_BINDING_VERSION: Final = "lean-source-binding/v1"
LEAN_AXIOM_REPORT_VERSION: Final = "lean-axiom-report/v2"
LEAN_NATIVE_ADDRESS_SPACE_FLOOR_BYTES: Final = 4 * 1024**3
LEAN_NATIVE_THREAD_STACK_KIB: Final = 65_536
LEAN_DEFAULT_APPROVED_IMPORTS: Final = ("Init", "Init.Classical", "Init.Prelude")
LEAN_NATIVE_IDENTITY_VERSION: Final = "lean-native-identity/v1"
LEAN_NATIVE_LIBRARY_SCOPE: Final = "installed runtime and approved imports are trusted; transitive libraries are not independently authenticated"
LEAN_MAX_EXECUTABLE_BYTES: Final = 128 * 1024**2

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SORRY = re.compile(r"(?<![A-Za-z0-9_'])(?:sorry|admit|sorryAx)(?![A-Za-z0-9_'])")
_UNSAFE = re.compile(r"(?<![A-Za-z0-9_'])(?:unsafe|axiom|constant)(?![A-Za-z0-9_'])")
_UNSUPPORTED_COMMAND = re.compile(
    r"#|@\s*\[|(?<![A-Za-z0-9_'])(?:elab|elab_rules|macro|macro_rules|syntax|"
    r"initialize|builtin_initialize|run_cmd|run_tac|notation|infix|infixl|infixr|"
    r"prefix|postfix|attribute|instance|set_option|open|local|scoped|export|alias|"
    r"variable|variables|parameter|parameters|include|omit|universe|universes|prelude|module)(?![A-Za-z0-9_'])"
)
_DECL = re.compile(r"^\s*(?:theorem|lemma)\s+([^\s:(=]+)", re.MULTILINE)
_LEAN_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z0-9_][A-Za-z0-9_']*)*\Z")
_AXIOM_MARKER = re.compile(r"\b(?:axioms?|sorryAx)\b")
_AXIOM_MESSAGE = re.compile(
    r"'(?P<name>[A-Za-z_][A-Za-z0-9_'.]*)' "
    r"(?:(?P<empty>does not depend on any axioms)|depends on axioms:\s*\[(?P<deps>[^\[\]]*)\])\Z",
    re.DOTALL,
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
    source_path: str = ""
    source_line: int | None = None
    source_column: int | None = None
    schema_version: str = LEAN_AXIOM_REPORT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "declaration", _lean_name(self.declaration, "declaration")
        )
        report_text = _text(self.report_text, "report_text")
        if len(report_text) > 1024 or sanitize_diagnostic(report_text, max_chars=1024) != report_text:
            raise LeanKernelError("axiom report must be a complete bounded compiler message")
        object.__setattr__(self, "report_text", report_text)
        observed_name, observed_axioms = _decode_axiom_report_text(report_text)
        if observed_name != self.declaration:
            raise LeanKernelError("axiom report text belongs to another declaration")
        axioms = tuple(_text(item, "axioms item") for item in self.axioms)
        if len(axioms) != len(set(axioms)):
            raise LeanKernelError("axioms must not contain duplicates")
        object.__setattr__(self, "axioms", axioms)
        if axioms != observed_axioms:
            raise LeanKernelError("axiom dependencies must equal the complete compiler report text")
        if not isinstance(self.contains_sorry_ax, bool):
            raise LeanKernelError("contains_sorry_ax must be a boolean")
        if self.contains_sorry_ax != any(name.rsplit(".", 1)[-1] == "sorryAx" for name in axioms):
            raise LeanKernelError("sorryAx flag must match the elaborated dependency list")
        object.__setattr__(self, "source_path", _text(self.source_path, "source_path", optional=True))
        for field_name in ("source_line", "source_column"):
            value = getattr(self, field_name)
            if value is not None and (type(value) is not int or value < (1 if field_name == "source_line" else 0)):
                raise LeanKernelError(f"{field_name} must be a valid compiler position")
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
            "source_path": self.source_path,
            "source_line": self.source_line,
            "source_column": self.source_column,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class LeanNativeIdentity:
    """Observed selected executable/version; imported libraries remain trusted.

    A trusted constructor-only observer can supply an explicitly fictional
    identity for software fixtures. Such fixtures establish no native result.
    """
    resolved_executable: str
    executable_sha256: str
    executable_bytes: int
    executable_stat_before: FrozenMap
    executable_stat_after: FrozenMap
    actual_version: str
    version_stdout: str
    version_stderr: str
    version_command: tuple[str, ...]
    version_returncode: int
    observation_kind: str = "bounded_native_version_probe"
    library_scope: str = LEAN_NATIVE_LIBRARY_SCOPE
    schema_version: str = LEAN_NATIVE_IDENTITY_VERSION

    def __post_init__(self) -> None:
        path = _text(self.resolved_executable, "resolved_executable")
        if not Path(path).is_absolute() or any(part in {".", ".."} for part in path.split("/")):
            raise LeanKernelError("native executable identity requires an exact absolute path")
        object.__setattr__(self, "resolved_executable", path)
        object.__setattr__(self, "executable_sha256", _digest(self.executable_sha256, "executable_sha256"))
        if type(self.executable_bytes) is not int or not 0 < self.executable_bytes <= LEAN_MAX_EXECUTABLE_BYTES:
            raise LeanKernelError("native executable byte bound is invalid")
        for field in ("executable_stat_before", "executable_stat_after"):
            value = getattr(self, field)
            if not isinstance(value, Mapping) or set(value) != {"device", "inode", "size", "mtime_ns", "ctime_ns"}:
                raise LeanKernelError("closed native executable stat record required")
            if any(type(value[key]) is not int or value[key] < 0 for key in value):
                raise LeanKernelError("native executable stat values must be nonnegative integers")
            if value["size"] != self.executable_bytes:
                raise LeanKernelError("native executable size differs from its stat record")
            object.__setattr__(self, field, FrozenMap(value))
        if self.executable_stat_before != self.executable_stat_after:
            raise LeanKernelError("native executable changed across its observation")
        stdout = _text(self.version_stdout, "version_stdout")
        stderr = _text(self.version_stderr, "version_stderr", optional=True)
        if len(stdout.encode("utf-8")) > 8192 or stderr:
            raise LeanKernelError("native version observation must be bounded and error-free")
        match = re.fullmatch(r"Lean \(version ([A-Za-z0-9][A-Za-z0-9.+_-]*)(?:, [^\r\n]+)?\)", stdout)
        if match is None or match.group(1) != self.actual_version:
            raise LeanKernelError("actual native version is not established by Lean version output")
        object.__setattr__(self, "version_stdout", stdout)
        object.__setattr__(self, "version_stderr", stderr)
        object.__setattr__(self, "version_command", tuple(self.version_command))
        if self.version_command != (path, "--version") or type(self.version_returncode) is not int or self.version_returncode != 0:
            raise LeanKernelError("exact successful native version command required")
        if self.observation_kind not in {"bounded_native_version_probe", "trusted_fictional_identity_fixture"}:
            raise LeanKernelError("unknown native identity observation kind")
        if self.library_scope != LEAN_NATIVE_LIBRARY_SCOPE or self.schema_version != LEAN_NATIVE_IDENTITY_VERSION:
            raise LeanKernelError("unsupported native identity or library trust scope")

    def to_dict(self) -> dict[str, Any]:
        return {name: (value.to_dict() if isinstance(value, FrozenMap) else list(value) if isinstance(value, tuple) else value)
                for name in self.__dataclass_fields__ for value in (getattr(self, name),)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LeanNativeIdentity:
        data = _closed_mapping(value, set(cls.__dataclass_fields__), "native identity")
        if type(data["version_command"]) is not list:
            raise LeanKernelError("native version command must serialize as a list")
        return cls(**dict(data, version_command=tuple(data["version_command"])))

    @property
    def identity_digest(self) -> str:
        return stable_digest(self.to_dict())


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
    submitted_source: str = ""
    expected_obligation_declaration: str = ""
    native_identity: LeanNativeIdentity | None = None
    native_identity_checked_after_compile: bool = False
    expected_proposition: str = ""
    expected_proposition_digest: str = ""
    expected_proposition_checked: bool = False
    compiled_source_digest: str = ""
    approved_axioms: tuple[str, ...] = ()
    approved_imports: tuple[str, ...] = LEAN_DEFAULT_APPROVED_IMPORTS
    axiom_policy_digest: str = ""
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
            self, "theorem_name", _lean_name(self.theorem_name, "theorem_name")
        )
        object.__setattr__(
            self, "theorem_digest", _digest(self.theorem_digest, "theorem_digest")
        )
        imports = tuple(_lean_name(item, "imports item") for item in self.imports)
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
        proposition = _text(self.expected_proposition, "expected_proposition", optional=True)
        if proposition:
            _expected_proposition(proposition)
        object.__setattr__(self, "expected_proposition", proposition)
        expected_digest = content_digest(proposition)
        _text(self.expected_proposition_digest, "expected_proposition_digest", optional=True)
        if self.expected_proposition_digest and self.expected_proposition_digest != expected_digest:
            raise LeanKernelError("expected proposition digest does not match its exact text")
        object.__setattr__(self, "expected_proposition_digest", expected_digest)
        if type(self.expected_proposition_checked) is not bool:
            raise LeanKernelError("expected_proposition_checked must be a boolean")
        approved = _approved_axioms(self.approved_axioms)
        object.__setattr__(self, "approved_axioms", approved)
        approved_imports = _approved_imports(self.approved_imports)
        object.__setattr__(self, "approved_imports", approved_imports)
        policy_digest = lean_axiom_policy_digest(approved, approved_imports)
        _text(self.axiom_policy_digest, "axiom_policy_digest", optional=True)
        if self.axiom_policy_digest and self.axiom_policy_digest != policy_digest:
            raise LeanKernelError("axiom policy digest does not match its trusted allowlist")
        object.__setattr__(self, "axiom_policy_digest", policy_digest)
        _text(self.compiled_source_digest, "compiled_source_digest", optional=True)
        if self.compiled_source_digest:
            _digest(self.compiled_source_digest, "compiled_source_digest")
        if self.generated_proof_digest != content_digest(self.generated_proof):
            raise LeanKernelError("generated proof digest does not match its text")
        if self.theorem_digest != self.source_binding.source_digest:
            raise LeanKernelError("theorem source digest differs from the submitted source")
        if self.source_tree.files[self.source_tree.primary_path] != self.source_binding.source_digest:
            raise LeanKernelError("primary source tree entry differs from submitted source")
        if self.source_tree.root_digest != stable_digest({
            "files": self.source_tree.files.to_dict(), "primary_path": self.source_tree.primary_path
        }):
            raise LeanKernelError("source tree root digest differs from its exact file map")
        if not isinstance(self.submitted_source, str):
            raise LeanKernelError("submitted_source must be exact Lean text")
        submitted = _source_text(self.submitted_source) if self.submitted_source else ""
        object.__setattr__(self, "submitted_source", submitted)
        if submitted:
            if content_digest(submitted) != self.source_binding.source_digest:
                raise LeanKernelError("submitted source text differs from its exact source binding")
            if extract_lean_imports(submitted) != imports:
                raise LeanKernelError("receipt imports differ from the complete submitted source header")
            if extract_generated_proof(submitted, self.theorem_name) != self.generated_proof:
                raise LeanKernelError("generated proof differs from the selected source declaration")
            instrumented = instrument_lean_source_for_axioms(submitted, self.theorem_name,
                expected_proposition=proposition)
            if self.compiled_source_digest != content_digest(instrumented):
                raise LeanKernelError("compiled source differs from the exact verification recipe")
            report_line = instrumented[:instrumented.rfind("#print axioms")].count("\n") + 1
            if self.axiom_report is not None and self.axiom_report.source_line != report_line:
                raise LeanKernelError("compiler dependency report is not bound to the verification command")
        guard = _text(self.expected_obligation_declaration, "expected_obligation_declaration", optional=True)
        if guard:
            _lean_name(guard, "expected_obligation_declaration")
        object.__setattr__(self, "expected_obligation_declaration", guard)
        if submitted and guard != (lean_expected_obligation_declaration(submitted, self.theorem_name, proposition) if proposition else ""):
            raise LeanKernelError("expected-obligation guard differs from the exact source/declaration/proposition recipe")
        if self.native_identity is not None and not isinstance(self.native_identity, LeanNativeIdentity):
            raise LeanKernelError("native_identity must be a canonical LeanNativeIdentity")
        if type(self.native_identity_checked_after_compile) is not bool:
            raise LeanKernelError("native identity post-compile check must be an exact boolean")
        if self.native_identity_checked_after_compile and self.native_identity is None:
            raise LeanKernelError("native identity post-compile check requires its observed identity")
        if self.expected_proposition_checked and (not proposition or not self.compiled_source_digest):
            raise LeanKernelError("type checking requires an explicit expected proposition and compiled source identity")
        if self.accepted:
            if submitted and scan_lean_incomplete_or_unsafe(submitted):
                raise LeanKernelError("accepted receipts cannot bypass the supported source verification profile")
            if (not submitted or self.source_binding.source_format != "lean4"
                    or self.source_tree.primary_path != "Main.lean"
                    or set(self.source_tree.files) != {"Main.lean"}):
                raise LeanKernelError("accepted v2 receipts require their complete exact Lean source")
            if not set(imports).issubset(approved_imports) or "Main" in imports:
                raise LeanKernelError("accepted receipts require trusted imports without source-tree shadowing")
            if not self.generated_proof:
                raise LeanKernelError("accepted receipts require the selected generated proof source")
            if not proposition or not self.expected_proposition_checked or not self.compiled_source_digest:
                raise LeanKernelError("accepted v2 receipts require a compiler-checked expected proposition")
            if not guard or self.axiom_report is None or self.axiom_report.declaration != guard:
                raise LeanKernelError("accepted receipts require the instantiated expected-obligation guard dependency report")
            if self.axiom_report.contains_sorry_ax or not set(self.axiom_report.axioms).issubset(approved):
                raise LeanKernelError("accepted receipts cannot depend on sorryAx or unapproved axioms")
            if (self.axiom_report.source_path != "Main.lean" or self.axiom_report.source_line is None
                    or self.axiom_report.source_column != 0):
                raise LeanKernelError("accepted receipts require source-bound compiler dependency evidence")
            if (self.native_identity is None or not self.native_identity_checked_after_compile
                    or self.toolchain.executable != self.native_identity.resolved_executable
                    or self.toolchain.version != self.native_identity.actual_version
                    or self.toolchain.metadata.get("native_identity_digest") != self.native_identity.identity_digest
                    or self.toolchain.metadata.get("native_library_scope") != self.native_identity.library_scope):
                raise LeanKernelError("accepted v3 receipts require observed native executable/version identity and a post-compile check")
            if (self.plane is not CapabilityPlane.NATIVE or self.toolchain.plane is not self.plane
                    or self.toolchain.kernel_id != "lean"
                    or self.toolchain.metadata.get("axiom_policy_digest") != policy_digest
                    or tuple(self.toolchain.metadata.get("approved_axioms", ())) != approved
                    or tuple(self.toolchain.metadata.get("approved_imports", ())) != approved_imports):
                raise LeanKernelError("accepted receipts require the exact native toolchain and approved-axiom profile")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LeanKernelReceipt:
        """Replay a complete v2 receipt and its identity; v1 stays archival."""
        data = _closed_mapping(value, set(cls.__dataclass_fields__) | {"receipt_id"}, "Lean receipt")
        source = _closed_mapping(data["source_binding"],
            {"request_digest", "source_digest", "source_format", "schema_version"}, "source binding")
        tree = _closed_mapping(data["source_tree"],
            {"tree_id", "root_digest", "files", "primary_path"}, "source tree")
        toolchain = _closed_mapping(data["toolchain"],
            {"toolchain_id", "kernel_id", "plane", "executable", "module_id", "version", "command_template", "metadata"},
            "toolchain binding")
        if not isinstance(tree["files"], Mapping) or not isinstance(toolchain["metadata"], Mapping):
            raise LeanKernelError("source files and toolchain metadata must be mappings")
        data["native_identity"] = (LeanNativeIdentity.from_dict(data["native_identity"]) if data["native_identity"] is not None else None)
        axiom = data["axiom_report"]
        if axiom is not None:
            axiom = _closed_mapping(axiom,
                {"declaration", "report_text", "axioms", "contains_sorry_ax", "source_path", "source_line", "source_column", "schema_version"},
                "axiom report")
            if type(axiom["axioms"]) is not list:
                raise LeanKernelError("serialized axiom dependencies must be a list")
            axiom = LeanAxiomReport(**dict(axiom, axioms=tuple(axiom["axioms"])))
        translation = data["translation"]
        if translation is not None:
            translation = _closed_mapping(translation,
                {"translation_id", "translation_digest", "source_family", "target_family", "fidelity", "metadata"},
                "translation binding")
            if not isinstance(translation["metadata"], Mapping):
                raise LeanKernelError("translation metadata must be a mapping")
            translation = KernelTranslationBinding(**dict(translation, metadata=FrozenMap(translation["metadata"])))
        for name in ("imports", "diagnostics", "approved_axioms", "approved_imports"):
            if type(data[name]) is not list:
                raise LeanKernelError(f"serialized {name} must be a list")
        identifier = _text(data.pop("receipt_id"), "receipt_id")
        data.update(source_binding=LeanSourceBinding(**source),
            source_tree=KernelSourceTreeBinding(**dict(tree, files=FrozenMap(tree["files"]))),
            toolchain=KernelToolchainBinding(**dict(toolchain, metadata=FrozenMap(toolchain["metadata"]))),
            translation=translation, axiom_report=axiom)
        for name in ("imports", "diagnostics", "approved_axioms", "approved_imports"):
            data[name] = tuple(data[name])
        result = cls(**data)
        if result.receipt_id != identifier:
            raise LeanKernelError("supplied Lean receipt identity does not match its exact contents")
        return result

    def _payload(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "submitted_source": self.submitted_source,
            "expected_obligation_declaration": self.expected_obligation_declaration,
            "native_identity": self.native_identity.to_dict() if self.native_identity is not None else None,
            "native_identity_checked_after_compile": self.native_identity_checked_after_compile,
            "expected_proposition": self.expected_proposition,
            "expected_proposition_digest": self.expected_proposition_digest,
            "expected_proposition_checked": self.expected_proposition_checked,
            "compiled_source_digest": self.compiled_source_digest,
            "approved_axioms": list(self.approved_axioms),
            "approved_imports": list(self.approved_imports),
            "axiom_policy_digest": self.axiom_policy_digest,
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


def _closed_mapping(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise LeanKernelError(f"{label} must contain exactly its canonical v2 fields")
    return dict(value)


def _lean_name(value: object, field_name: str = "declaration") -> str:
    name = _text(value, field_name)
    if not _LEAN_NAME.fullmatch(name) or name == "_" or name.startswith("_root_."):
        raise LeanKernelError(f"{field_name} must be an explicit canonical Lean name")
    return name


def _approved_axioms(values: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise LeanKernelError("approved_axioms must be a sequence of explicit names")
    names = tuple(_lean_name(value, "approved axiom") for value in values)
    if len(names) != len(set(names)) or any(name.rsplit(".", 1)[-1] == "sorryAx" for name in names):
        raise LeanKernelError("axiom policy must be distinct and can never approve sorryAx")
    return tuple(sorted(names))


def _mask_lean_comments_and_strings(source: str, *, allow_comments: bool = True) -> str:
    """Lexical diagnostics only; this does not establish elaborated dependencies."""
    chars = list(source)
    i, length = 0, len(source)
    while i < length:
        start = i
        if source.startswith("--", i):
            if not allow_comments:
                raise LeanKernelError("comments are unsupported in the explicit expected proposition")
            end = source.find("\n", i)
            i = length if end < 0 else end
        elif source.startswith("/-", i):
            if not allow_comments:
                raise LeanKernelError("comments are unsupported in the explicit expected proposition")
            depth, i = 1, i + 2
            while i < length and depth:
                if source.startswith("/-", i):
                    depth += 1; i += 2
                elif source.startswith("-/", i):
                    depth -= 1; i += 2
                else:
                    i += 1
            if depth:
                raise LeanKernelError("unterminated Lean block comment")
        elif source[i] == '"':
            i += 1
            while i < length:
                if source[i] == "\\":
                    i += 2
                elif source[i] == '"':
                    i += 1; break
                else:
                    i += 1
            else:
                raise LeanKernelError("unterminated Lean string")
        else:
            i += 1; continue
        for index in range(start, min(i, length)):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


def _expected_proposition(value: object) -> str:
    text = _text(value, "expected_proposition")
    _source_text(text)
    masked = _mask_lean_comments_and_strings(text, allow_comments=False)
    if (_SORRY.search(masked) or _UNSAFE.search(masked) or _UNSUPPORTED_COMMAND.search(masked)
            or re.search(r"(?<![A-Za-z0-9_'])_(?![A-Za-z0-9_'])|\?|\b(?:by|theorem|lemma|def|example)\b", masked)
            or ":=" in masked or ";" in masked):
        raise LeanKernelError("expected proposition must be complete and contain no holes or commands")
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    for char in masked:
        if char in "([{":
            stack.append(char)
        elif char in pairs:
            if not stack or stack.pop() != pairs[char]:
                raise LeanKernelError("unbalanced delimiters in expected proposition")
    if stack:
        raise LeanKernelError("unbalanced delimiters in expected proposition")
    return text


def _declared_theorems(source: str) -> tuple[tuple[str, int], ...]:
    masked = _mask_lean_comments_and_strings(source)
    namespace, scopes, declarations, offset = "", [], [], 0
    for line in masked.splitlines(keepends=True):
        stripped = line.strip()
        opening = re.fullmatch(r"namespace\s+([A-Za-z_][A-Za-z0-9_'.]*)", stripped)
        if opening:
            scopes.append(namespace)
            name = opening.group(1)
            namespace = name.removeprefix("_root_.") if name.startswith("_root_.") else ".".join(filter(None, (namespace, name)))
        elif re.fullmatch(r"(?:public\s+|private\s+)?section(?:\s+[A-Za-z_][A-Za-z0-9_']*)?", stripped):
            scopes.append(namespace)
        elif re.fullmatch(r"end(?:\s+[A-Za-z_][A-Za-z0-9_'.]*)?", stripped):
            if not scopes:
                raise LeanKernelError("unbalanced Lean namespace/section scope")
            namespace = scopes.pop()
        match = _DECL.match(line)
        if match is not None:
            name = _lean_name(match.group(1), "source theorem")
            declarations.append((".".join(filter(None, (namespace, name))), offset + match.start()))
        offset += len(line)
    if scopes:
        raise LeanKernelError("Lean namespace/section must close before verification commands")
    return tuple(declarations)


def _approved_imports(values: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise LeanKernelError("approved_imports must be a sequence of explicit module names")
    names = tuple(_lean_name(value, "approved import") for value in values)
    if len(names) != len(set(names)) or "Main" in names:
        raise LeanKernelError("import policy must be distinct and cannot shadow the submitted Main module")
    return tuple(sorted(names))


def lean_axiom_policy_digest(
    approved_axioms: Sequence[str],
    approved_imports: Sequence[str] = LEAN_DEFAULT_APPROVED_IMPORTS,
) -> str:
    """Identity of the trusted dependency and module policy, never payload advice."""
    return stable_digest({"approved_axioms": list(_approved_axioms(approved_axioms)),
                          "approved_imports": list(_approved_imports(approved_imports))})


def extract_lean_imports(source: str) -> tuple[str, ...]:
    """Parse the limited bare header grammar; never silently drop an import.

    A header line may import one or more explicit ASCII module names. Modified,
    escaped, multiline, duplicate and non-header import syntax is unsupported.
    Comments and strings are masked for diagnostics; Lean elaboration remains
    the authority for the supported source's meaning.
    """
    modules: list[str] = []
    header = True
    for line in _mask_lean_comments_and_strings(source).splitlines():
        text = line.strip()
        if not text:
            continue
        if re.search(r"(?<![A-Za-z0-9_'])import(?![A-Za-z0-9_'])", text):
            if not header or not text.startswith("import "):
                raise LeanKernelError("unsupported Lean import syntax or non-header import")
            names = text[len("import "):].split()
            if not names:
                raise LeanKernelError("Lean import requires explicit module names")
            for name in names:
                module = _lean_name(name, "import module")
                if module in modules:
                    raise LeanKernelError("duplicate Lean imports are unsupported")
                modules.append(module)
        else:
            header = False
    return tuple(modules)


def extract_lean_theorem_name(source: str) -> str:
    declarations = _declared_theorems(source)
    if len(declarations) != 1:
        raise LeanKernelError("exactly one source theorem is required without an explicit expected_declaration")
    return declarations[0][0]


def extract_generated_proof(source: str, declaration: str | None = None) -> str:
    """Bind the selected declaration's source suffix, retaining its context."""
    declarations = _declared_theorems(source)
    selected = declaration if declaration is not None else extract_lean_theorem_name(source)
    matches = [offset for name, offset in declarations if name == selected]
    if len(matches) != 1:
        raise LeanKernelError("expected declaration must identify one source theorem")
    return source[matches[0]:].strip()


def scan_lean_incomplete_or_unsafe(source: str) -> tuple[str, ...]:
    """Source diagnostics are separate from authoritative compiler dependencies."""
    masked = _mask_lean_comments_and_strings(source)
    findings: list[str] = []
    if _SORRY.search(masked):
        findings.append("lean_source_contains_sorry_or_admit")
    if _UNSAFE.search(masked):
        findings.append("lean_source_contains_unsafe_or_unreviewed_axiom")
    if _UNSUPPORTED_COMMAND.search(masked):
        findings.append("lean_source_contains_unsupported_metaprogramming_or_output")
    return tuple(findings)


def _native_executable_snapshot(executable: str) -> tuple[str, str, int, FrozenMap]:
    try:
        path = Path(executable).resolve(strict=True)
        if not path.is_absolute():
            raise LeanKernelError("absolute native executable required")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            first = os.fstat(stream.fileno())
            if not stat.S_ISREG(first.st_mode) or first.st_nlink != 1 or not 0 < first.st_size <= LEAN_MAX_EXECUTABLE_BYTES:
                raise LeanKernelError("bounded ordinary native executable required")
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            last = os.fstat(stream.fileno())
        stamp = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if stamp(first) != stamp(last) or stamp(last) != stamp(path.lstat()):
            raise LeanKernelError("native executable changed during hashing")
        observed = FrozenMap(dict(device=last.st_dev, inode=last.st_ino, size=last.st_size,
                                  mtime_ns=last.st_mtime_ns, ctime_ns=last.st_ctime_ns))
        return str(path), digest, last.st_size, observed
    except (OSError, ValueError) as error:
        raise LeanKernelError("native executable identity could not be observed") from error


def lean_expected_obligation_declaration(source: str, declaration: str, expected_proposition: str) -> str:
    """Name the exact instantiated goal whose elaborated dependencies matter."""
    _source_text(source)
    name = "_ipfs_expected_obligation_" + stable_digest({"source": source,
        "declaration": _lean_name(declaration), "proposition": _expected_proposition(expected_proposition)})
    if re.search(r"(?<![A-Za-z0-9_'])" + re.escape(name) + r"(?![A-Za-z0-9_'])",
                 _mask_lean_comments_and_strings(source)):
        raise LeanKernelError("source collides with the generated expected-obligation declaration")
    return name


def instrument_lean_source_for_axioms(
    source: str, declaration: str, *, expected_proposition: str = ""
) -> str:
    """Audit the named expected goal, including inferred instances/coercions."""
    decl = _lean_name(declaration)
    body = source.rstrip() + "\n\nset_option pp.fullNames true\n"
    if expected_proposition:
        proposition = _expected_proposition(expected_proposition)
        guard = lean_expected_obligation_declaration(source, decl, proposition)
        body += f"set_option autoImplicit false in\ntheorem {guard} : ({proposition}) := _root_.{decl}\n\n"
        decl = guard
    return body + f"#print axioms _root_.{decl}\n"


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


def _decode_axiom_report_text(text: str) -> tuple[str, tuple[str, ...]]:
    """One canonical interpretation shared by parsing and receipt replay."""
    match = _AXIOM_MESSAGE.fullmatch(text)
    if match is None:
        raise LeanKernelError("malformed or ambiguous Lean dependency report text")
    dependencies: tuple[str, ...] = ()
    if match.group("empty") is None:
        dependencies = tuple(name.strip() for name in match.group("deps").split(","))
        if (not dependencies or any(not _LEAN_NAME.fullmatch(name) for name in dependencies)
                or len(set(dependencies)) != len(dependencies)):
            raise LeanKernelError("malformed or duplicate Lean dependency names")
    return _lean_name(match.group("name")), dependencies


def parse_lean_axiom_report(
    stdout: str, declaration: str, *, expected_source_path: str | None = None,
    expected_source_line: int | None = None,
) -> LeanAxiomReport | None:
    """Require exactly one complete named report; never scan unrelated prose."""
    expected = _lean_name(declaration)
    reports: list[tuple[dict[str, Any], re.Match[str]]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            def unique_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate compiler JSON key")
                    result[key] = value
                return result
            message = json.loads(line, object_pairs_hook=unique_pairs,
                                 parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        except (json.JSONDecodeError, ValueError):
            if expected_source_path is not None:
                return None
            message = {"severity": "information", "data": line.strip()}
        if type(message) is not dict:
            return None
        data = message.get("data", "")
        if not isinstance(data, str) or not _AXIOM_MARKER.search(data):
            continue
        match = _AXIOM_MESSAGE.fullmatch(data.strip())
        if match is None or match.group("name") != expected or message.get("severity") not in {"info", "information"}:
            return None
        reports.append((message, match))
    if len(reports) != 1:
        return None
    message, match = reports[0]
    position = message.get("pos", {})
    path = message.get("fileName", "")
    if expected_source_path is not None:
        if (not expected_source_path or not isinstance(path, str) or not path or len(path) > 4096 or "\x00" in path
                or type(position) is not dict or type(position.get("line")) is not int
                or position.get("line") != expected_source_line or type(position.get("column")) is not int
                or position.get("column") != 0):
            return None
        # The bounded process result retains the requested argv, not its private
        # workspace expansion. Invoke the sole submitted file by its exact
        # relative CLI name and bind Lean's unchanged input-context filename.
        if path != expected_source_path:
            return None
    try:
        text = match.group(0)
        name, dependencies = _decode_axiom_report_text(text)
        return LeanAxiomReport(declaration=name, report_text=text,
            axioms=dependencies, contains_sorry_ax=any(name.rsplit(".", 1)[-1] == "sorryAx" for name in dependencies),
            source_path=path if isinstance(path, str) else "",
            source_line=position.get("line") if type(position) is dict else None,
            source_column=position.get("column") if type(position) is dict else None)
    except LeanKernelError:
        return None


def evaluate_lean_kernel_output(
    process: ToolRunResult,
    *,
    declaration: str,
    approved_axioms: Sequence[str] = (),
    expected_source_path: str | None = None,
    expected_source_line: int | None = None,
) -> tuple[bool, LeanAxiomReport | None, tuple[str, ...]]:
    """Decide whether Lean accepted a proof without incomplete/unsafe axioms."""

    diagnostics: list[str] = []
    if process.error:
        diagnostics.append(sanitize_diagnostic(process.error))
        return False, None, bound_diagnostics(diagnostics)
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

    axiom_report = parse_lean_axiom_report(process.stdout, declaration,
        expected_source_path=expected_source_path, expected_source_line=expected_source_line)
    if axiom_report is None:
        diagnostics.append("missing, ambiguous or incorrectly bound Lean declaration dependency report")
        return False, None, bound_diagnostics(diagnostics)
    if _AXIOM_MARKER.search(process.stderr):
        diagnostics.append("stderr cannot establish or replace Lean dependency evidence")
        return False, axiom_report, bound_diagnostics(diagnostics)

    if axiom_report.contains_sorry_ax:
        diagnostics.append(
            f"`#print axioms {declaration}` reports sorryAx; the proof still "
            "depends on an unresolved sorry"
        )
        return False, axiom_report, bound_diagnostics(diagnostics)

    unapproved = set(axiom_report.axioms) - set(_approved_axioms(approved_axioms))
    if unapproved:
        diagnostics.append("Lean proof depends on unapproved axioms")
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
        approved_axioms: Sequence[str] = (),
        approved_imports: Sequence[str] = LEAN_DEFAULT_APPROVED_IMPORTS,
        native_identity_probe: Callable[[], LeanNativeIdentity] | None = None,
        logic_families: Sequence[str] = (
            "lean",
            "lean4",
            "dependent_type_theory",
            "higher_order",
            "software_verification",
        ),
    ) -> None:
        self.approved_axioms = _approved_axioms(approved_axioms)
        self.approved_imports = _approved_imports(approved_imports)
        self.axiom_policy_digest = lean_axiom_policy_digest(self.approved_axioms, self.approved_imports)
        self.backend_version = _text(backend_version, "backend_version")
        self.executable = _text(executable, "executable")
        self._runner = runner if runner is not None else ResourceAdmittedToolRunner()
        self._managed_resource_runner = isinstance(self._runner, ResourceAdmittedToolRunner)
        if not isinstance(self._runner, BoundedToolRunner):
            raise LeanKernelError("runner must be a BoundedToolRunner")
        self._wasm_probe = wasm_probe or WasmCapabilityProbe()
        if not isinstance(self._wasm_probe, WasmCapabilityProbe):
            raise LeanKernelError("wasm_probe must be a WasmCapabilityProbe")
        if native_probe is not None and not callable(native_probe):
            raise LeanKernelError("native_probe must be callable")
        self._native_probe = native_probe
        if native_identity_probe is not None and not callable(native_identity_probe):
            raise LeanKernelError("native_identity_probe must be a trusted callable")
        self._native_identity_probe = native_identity_probe
        self._native_identity_cache: LeanNativeIdentity | None = None
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

    def _observe_native_identity(self, bounds: ExecutionBounds | None = None, *,
                                 cancellation: CancellationSignal | Any | None = None,
                                 deadline: float | None = None,
                                 observation_usage: dict[str, int] | None = None) -> LeanNativeIdentity:
        if _tool_is_cancelled(cancellation):
            raise LeanKernelError("native identity observation cancelled before version execution")
        if deadline is not None and time.monotonic() >= deadline:
            raise LeanKernelError("native identity observation exhausted the request deadline")
        if self._native_identity_probe is not None:
            identity = self._native_identity_probe()
            if not isinstance(identity, LeanNativeIdentity):
                raise LeanKernelError("trusted native identity probe must return LeanNativeIdentity")
        else:
            probe = self._runner.probe(self.executable, runtime=ToolRuntime.NATIVE)
            if not probe.available:
                raise LeanKernelError("native Lean executable is unavailable")
            path, digest, size, before = _native_executable_snapshot(probe.executable_path)
            cached = self._native_identity_cache
            if cached is not None and (path, digest, size, before) == (
                    cached.resolved_executable, cached.executable_sha256, cached.executable_bytes, cached.executable_stat_after):
                identity = cached
            else:
                budget = bounds or ExecutionBounds(timeout_ms=10000, max_memory_bytes=512*1024**2, max_output_bytes=65536)
                if _tool_is_cancelled(cancellation):
                    raise LeanKernelError("native identity observation cancelled before version execution")
                timeout = min(10.0, budget.timeout_ms / 1000,
                              max(0.0, deadline - time.monotonic()) if deadline is not None else 10.0)
                if timeout <= 0:
                    raise LeanKernelError("native identity observation exhausted the request deadline")
                result = self._runner.run(ToolRunRequest(argv=(path, "--version"), runtime=ToolRuntime.NATIVE,
                    limits=ToolRunLimits(timeout_seconds=timeout, cpu_seconds=timeout,
                        memory_bytes=(max(LEAN_NATIVE_ADDRESS_SPACE_FLOOR_BYTES, budget.max_memory_bytes)
                                      if self._managed_resource_runner else budget.max_memory_bytes),
                        resident_memory_bytes=budget.max_memory_bytes if self._managed_resource_runner else None,
                        max_output_bytes=min(65536, budget.max_output_bytes), max_input_bytes=65536,
                        max_workspace_bytes=131072), environment=self._native_resource_environment()), cancellation=cancellation)
                if observation_usage is not None:
                    observation_usage["output_bytes"] = len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8"))
                if not result.ok or result.stderr:
                    raise LeanKernelError("bounded native Lean version probe failed")
                match = re.fullmatch(r"Lean \(version ([A-Za-z0-9][A-Za-z0-9.+_-]*)(?:, [^\r\n]+)?\)", result.stdout.strip())
                if match is None:
                    raise LeanKernelError("native executable did not produce a Lean version observation")
                after_path, after_digest, after_size, after = _native_executable_snapshot(path)
                if (path, digest, size, before) != (after_path, after_digest, after_size, after):
                    raise LeanKernelError("native executable changed across its version probe")
                identity = LeanNativeIdentity(path, digest, size, before, after, match.group(1),
                    result.stdout.strip(), result.stderr, tuple(result.command), result.returncode)
                self._native_identity_cache = identity
        if self.backend_version not in {"lean", "lean4", "unknown"} and self.backend_version != identity.actual_version:
            raise LeanKernelError("configured Lean version does not match the observed native version")
        return identity

    def _recheck_native_identity(self, identity: LeanNativeIdentity) -> bool:
        if self._native_identity_probe is not None:
            return self._native_identity_probe() == identity
        probe = self._runner.probe(self.executable, runtime=ToolRuntime.NATIVE)
        if not probe.available:
            return False
        return _native_executable_snapshot(probe.executable_path) == (identity.resolved_executable,
            identity.executable_sha256, identity.executable_bytes, identity.executable_stat_after)

    def probe_native(self) -> KernelCapabilityState:
        """Cheap availability only; configured labels are not observations."""
        if self._native_probe is not None:
            state = self._native_probe()
            if not isinstance(state, KernelCapabilityState) or state.plane is not CapabilityPlane.NATIVE:
                raise LeanKernelError("native_probe must report a native KernelCapabilityState")
            return state
        if self._runner.is_available(self.executable, runtime=ToolRuntime.NATIVE):
            return KernelCapabilityState.available_native(kernel_id=self.backend_id,
                executable=self.executable, metadata={"configured_version_label": self.backend_version,
                                                     "native_version_observed": False})
        return KernelCapabilityState.unavailable(plane=CapabilityPlane.NATIVE,
            kernel_id=self.backend_id, reason="native Lean executable is unavailable", executable=self.executable)

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

    def _native_resource_arguments(self) -> tuple[str, ...]:
        if not self._managed_resource_runner:
            return ()
        return (f"-s{LEAN_NATIVE_THREAD_STACK_KIB}", f"-j{self._runner.cpu_slots}")

    def _native_resource_environment(self) -> dict[str, str]:
        if not self._managed_resource_runner:
            return {}
        return {"LEAN_NUM_THREADS": str(self._runner.cpu_slots),
                "LEAN_STACK_SIZE_KB": str(LEAN_NATIVE_THREAD_STACK_KIB),
                "LEAN_MAIN_USE_THREAD": "0"}

    def _tool_request(self, source: str, bounds: ExecutionBounds, *,
                      declaration: str | None = None, expected_proposition: str = "",
                      executable: str | None = None) -> ToolRunRequest:
        instrumented = instrument_lean_source_for_axioms(source,
            declaration or extract_lean_theorem_name(source), expected_proposition=expected_proposition)
        max_workspace_bytes = max(
            bounds.max_output_bytes * 2,
            len(instrumented.encode("utf-8")) + bounds.max_output_bytes + 1024,
        )
        return ToolRunRequest(
            argv=(executable or self.executable, *self._native_resource_arguments(),
                  "--json", "Main.lean"),
            runtime=ToolRuntime.NATIVE,
            limits=ToolRunLimits(
                timeout_seconds=bounds.timeout_ms / 1000,
                cpu_seconds=bounds.timeout_ms / 1000,
                # Lean reserves large virtual regions during runtime startup.
                # Keep a finite AS ceiling and charge the requested RSS ceiling;
                # the existing process-tree RSS guard remains sampled, not a
                # kernel-enforced aggregate memory limit.
                memory_bytes=(max(LEAN_NATIVE_ADDRESS_SPACE_FLOOR_BYTES, bounds.max_memory_bytes)
                              if self._managed_resource_runner else bounds.max_memory_bytes),
                resident_memory_bytes=(bounds.max_memory_bytes if self._managed_resource_runner else None),
                max_output_bytes=bounds.max_output_bytes,
                max_input_bytes=bounds.max_output_bytes,
                max_workspace_bytes=max_workspace_bytes,
            ),
            input_files={"Main.lean": instrumented},
            environment=self._native_resource_environment(),
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
            "backend_version": receipt.native_identity.actual_version if receipt.native_identity is not None else self.backend_version,
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
        execution_started = time.monotonic()
        request_deadline = execution_started + request.bounds.timeout_ms / 1000
        native_observation_usage: dict[str, int] = {}
        source, _source_format, translation = _payload_source(request)
        binding = LeanSourceBinding.bind(request, source)
        pre_cancelled = _tool_is_cancelled(cancellation)
        capability = (DualPlaneCapability(kernel_id=self.backend_id,
            native=KernelCapabilityState.unavailable(plane=CapabilityPlane.NATIVE, kernel_id=self.backend_id,
                reason="request cancelled before native identity or proof execution"),
            wasm=KernelCapabilityState.unavailable(plane=CapabilityPlane.WASM, kernel_id=self.backend_id,
                reason="request cancelled before capability callbacks")) if pre_cancelled else self.probe_capabilities())
        resolved_plane = _enum(plane, CapabilityPlane, "plane")

        payload = request.payload.to_dict()
        raw_name, raw_proposition = payload.get("expected_declaration"), payload.get("expected_proposition")
        if (raw_name is None) != (raw_proposition is None):
            raise LeanKernelError("expected_declaration and expected_proposition must be provided together")
        bound_obligation = raw_name is not None
        theorem_name = _lean_name(raw_name, "expected_declaration") if bound_obligation else extract_lean_theorem_name(source)
        expected_proposition = _expected_proposition(raw_proposition) if bound_obligation else ""
        if sum(name == theorem_name for name, _ in _declared_theorems(source)) != 1:
            raise LeanKernelError("expected_declaration must identify exactly one source theorem")
        instrumented_source = instrument_lean_source_for_axioms(source, theorem_name,
            expected_proposition=expected_proposition)
        axiom_line = instrumented_source[:instrumented_source.rfind("#print axioms")].count("\n") + 1
        guard = lean_expected_obligation_declaration(source, theorem_name, expected_proposition) if bound_obligation else ""
        receipt_bindings = dict(submitted_source=source, expected_obligation_declaration=guard,
            native_identity=None, native_identity_checked_after_compile=False, expected_proposition=expected_proposition,
            expected_proposition_digest=content_digest(expected_proposition), expected_proposition_checked=False,
            compiled_source_digest=content_digest(instrumented_source), approved_axioms=self.approved_axioms,
            approved_imports=self.approved_imports,
            axiom_policy_digest=self.axiom_policy_digest)
        imports = extract_lean_imports(source)
        generated_proof = extract_generated_proof(source, theorem_name)
        source_tree = KernelSourceTreeBinding.from_files(
            {"Main.lean": source},
            primary_path="Main.lean",
        )
        incomplete = scan_lean_incomplete_or_unsafe(source)
        if not set(imports).issubset(self.approved_imports) or "Main" in imports:
            incomplete += ("lean_source_contains_unapproved_import",)

        identity: LeanNativeIdentity | None = None
        if resolved_plane is CapabilityPlane.NATIVE and capability.native.available and not incomplete:
            try:
                identity = self._observe_native_identity(request.bounds, cancellation=cancellation,
                    deadline=request_deadline, observation_usage=native_observation_usage)
                if _tool_is_cancelled(cancellation):
                    raise LeanKernelError("native identity observation cancelled before proof execution")
                if time.monotonic() >= request_deadline:
                    raise LeanKernelError("native identity observation exhausted the request deadline")
                if native_observation_usage.get("output_bytes", 0) >= request.bounds.max_output_bytes:
                    raise LeanKernelError("native version observation exhausted the aggregate request output allowance")
                receipt_bindings["native_identity"] = identity
            except LeanKernelError as error:
                identity = None
                capability = replace(capability, native=KernelCapabilityState.unavailable(
                    plane=CapabilityPlane.NATIVE, kernel_id=self.backend_id,
                    reason=str(error), executable=self.executable))
        if resolved_plane is CapabilityPlane.NATIVE:
            plane_state = capability.native
            toolchain = KernelToolchainBinding(
                toolchain_id=f"toolchain:lean:native:{self.backend_version}",
                kernel_id=self.backend_id,
                plane=CapabilityPlane.NATIVE,
                executable=identity.resolved_executable if identity is not None else plane_state.executable or self.executable,
                version=identity.actual_version if identity is not None else plane_state.version or self.backend_version,
                command_template=" ".join(("{lean}", *self._native_resource_arguments(),
                                           "--json", "{source_file}")),
                metadata=FrozenMap({"approved_axioms": list(self.approved_axioms),
                    "approved_imports": list(self.approved_imports),
                    "native_identity_digest": identity.identity_digest if identity is not None else "",
                    "native_library_scope": LEAN_NATIVE_LIBRARY_SCOPE,
                    "axiom_policy_digest": self.axiom_policy_digest, "native_resource_profile": {
                    "cpu_slots": self._runner.cpu_slots,
                    "child_process_slots": self._runner.child_process_slots,
                    "address_space_bytes": max(LEAN_NATIVE_ADDRESS_SPACE_FLOOR_BYTES, request.bounds.max_memory_bytes),
                    "resident_memory_bytes": request.bounds.max_memory_bytes,
                    "environment": self._native_resource_environment(),
                    "resident_memory_enforcement": "sampled_process_tree_rss",
                }} if self._managed_resource_runner else {"approved_axioms": list(self.approved_axioms),
                    "approved_imports": list(self.approved_imports),
                    "native_identity_digest": identity.identity_digest if identity is not None else "",
                    "native_library_scope": LEAN_NATIVE_LIBRARY_SCOPE,
                    "axiom_policy_digest": self.axiom_policy_digest}),
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

        usage = ResourceUsage(elapsed_ms=max(0, round((time.monotonic() - execution_started) * 1000)),
            output_bytes=native_observation_usage.get("output_bytes", 0))
        axiom_report: LeanAxiomReport | None = None
        diagnostics: list[str] = list(incomplete)

        if not plane_state.available:
            reason = plane_state.reason or f"Lean kernel plane {resolved_plane.value} is unavailable"
            receipt = LeanKernelReceipt(
                **receipt_bindings,
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
                status=(ResultStatus.ERROR if (_tool_is_cancelled(cancellation)
                        or native_observation_usage.get("output_bytes", 0) >= request.bounds.max_output_bytes)
                        else ResultStatus.TIMEOUT if time.monotonic() >= request_deadline else ResultStatus.UNAVAILABLE),
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
                **receipt_bindings,
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
                **receipt_bindings,
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

        remaining_ms = request.bounds.timeout_ms - int((time.monotonic() - execution_started) * 1000)
        if remaining_ms <= 0:
            raise LeanKernelError("native identity observation exhausted the requested execution deadline")
        remaining_output_bytes = request.bounds.max_output_bytes - native_observation_usage.get("output_bytes", 0)
        tool_request = self._tool_request(source, replace(request.bounds, timeout_ms=remaining_ms),
            declaration=theorem_name, expected_proposition=expected_proposition,
            executable=identity.resolved_executable if identity is not None else None)
        # Output accounting must not reduce the original complete-source input
        # or workspace allowance. The existing owner derives those separately.
        tool_request = replace(tool_request, limits=replace(tool_request.limits,
            max_output_bytes=remaining_output_bytes))
        process = self._runner.run(tool_request, cancellation=cancellation, runtime=ToolRuntime.NATIVE)
        usage = _usage_from_process(process)
        accepted, axiom_report, eval_diagnostics = evaluate_lean_kernel_output(
            process, declaration=guard or theorem_name, approved_axioms=self.approved_axioms,
            expected_source_path=process.command[-1] if process.command else "",
            expected_source_line=axiom_line,
        )
        diagnostics.extend(eval_diagnostics)
        try:
            identity_unchanged = identity is not None and self._recheck_native_identity(identity)
        except (LeanKernelError, OSError, ValueError):
            identity_unchanged = False
        receipt_bindings["native_identity_checked_after_compile"] = identity_unchanged
        request_deadline_expired = time.monotonic() >= request_deadline
        usage = replace(usage, elapsed_ms=max(0, round((time.monotonic() - execution_started) * 1000)),
            output_bytes=usage.output_bytes + native_observation_usage.get("output_bytes", 0))
        aggregate_output_exhausted = usage.output_bytes > request.bounds.max_output_bytes
        if aggregate_output_exhausted:
            accepted = False
            diagnostics.append("aggregate backend request output allowance exceeded")
        if request_deadline_expired:
            accepted = False
            diagnostics.append("backend request deadline exhausted including identity and verification work")
        if not identity_unchanged:
            accepted = False
            eval_diagnostics = ("native executable identity changed or could not be rechecked after compilation", *eval_diagnostics)
            diagnostics.append(eval_diagnostics[0])

        if process.unavailable:
            status = ResultStatus.UNAVAILABLE
            reason = process.error or "lean kernel became unavailable during execution"
            accepted = False
        elif process.timed_out or request_deadline_expired:
            status = ResultStatus.TIMEOUT
            reason = process.error or "lean kernel exceeded its aggregate request wall-clock bound"
            accepted = False
        elif process.cancelled:
            status = ResultStatus.ERROR
            reason = process.error or "lean kernel execution was cancelled"
            accepted = False
        elif aggregate_output_exhausted:
            status = ResultStatus.ERROR
            reason = "aggregate backend request output allowance exceeded"
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
        elif not bound_obligation:
            status = ResultStatus.CANDIDATE
            reason = "source declaration compiled, but the requested obligation has no explicit declaration/proposition binding"
        else:
            status = ResultStatus.PROVED
            reason = ""

        receipt = LeanKernelReceipt(
            **dict(receipt_bindings, expected_proposition_checked=accepted and bound_obligation),
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
                ("source_only_lean_declaration" if not bound_obligation else "incomplete_or_unsafe_lean_proof")
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
    "LeanNativeIdentity",
    "LEAN_NATIVE_LIBRARY_SCOPE",
    "lean_expected_obligation_declaration",
    "LeanSourceBinding",
    "evaluate_lean_kernel_output",
    "extract_generated_proof",
    "extract_lean_imports",
    "LEAN_DEFAULT_APPROVED_IMPORTS",
    "lean_axiom_policy_digest",
    "extract_lean_theorem_name",
    "instrument_lean_source_for_axioms",
    "parse_lean_axiom_report",
    "scan_lean_incomplete_or_unsafe",
]
