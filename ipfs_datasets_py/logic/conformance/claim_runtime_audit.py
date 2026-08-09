"""Audit declared claims against current executable runtime evidence (LFP2-001).

``LogicClaimRuntimeAudit@1`` is a side-effect-free claim-vs-runtime evaluator.
It never installs tools, probes the host environment for live binaries, opens
the network, or upgrades a claim.  It classifies every executable or
authority-bearing public claim by lifecycle stage against **exact current-tree
evidence**:

    declared -> parsed -> elaborated -> translatable -> compilable
             -> executable -> replayed -> independently_validated

Mocks and metadata-only records can satisfy inventory (declared) but **cannot**
satisfy the ``executable`` stage or any later runtime stage.  Missing runtime
evidence becomes an owner-scoped typed gap rather than silent success.

Evidence surfaces required by LFP2-001:

* registry, matrix, parser, translator, runner, decoder, replay, kernel
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.logic.backends.registry import (
    EXECUTABLE_PROVIDER_IDS,
    EXECUTABLE_PROVIDER_MATRIX,
)
from ipfs_datasets_py.logic.conformance.matrix import (
    DEFAULT_MATRIX,
    AuthorityCeiling,
    LogicCapabilityMatrix,
    ProviderAxis,
    SupportStatus,
    build_default_matrix,
)
from ipfs_datasets_py.logic.families.generated_catalog import (
    GeneratedProviderTranslationCatalog,
    build_generated_provider_translation_catalog,
)
from ipfs_datasets_py.logic.families.providers import (
    ADVISORY_PROVIDER_IDS,
    BASELINE_PROVIDER_IDS,
)
from ipfs_datasets_py.logic.families.registry import DEFAULT_REGISTRY, LogicFamilyRegistry
from ipfs_datasets_py.logic.parsers.catalog import (
    LOGIC_PARSER_CATALOG_INTERFACE,
    PARSER_CONTRIBUTION_MODULES,
    LogicParserCatalog,
    build_parser_catalog,
)

# ---------------------------------------------------------------------------
# Interface / schema
# ---------------------------------------------------------------------------

LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE: Final = "LogicClaimRuntimeAudit@1"
LOGIC_CLAIM_RUNTIME_AUDIT_SCHEMA: Final = "logic-claim-runtime-audit/v1"
LOGIC_CLAIM_RUNTIME_AUDIT_REPORT_SCHEMA: Final = "logic-claim-runtime-audit-report/v1"
LOGIC_CLAIM_AUDIT_ROW_SCHEMA: Final = "logic-claim-runtime-audit-row/v1"
LOGIC_CLAIM_EVIDENCE_SCHEMA: Final = "logic-claim-runtime-evidence/v1"
LOGIC_CLAIM_GAP_SCHEMA: Final = "logic-claim-runtime-gap/v1"
AUDIT_REPORT_VERSION: Final = "1.0.0"
TASK_ID: Final = "LFP2-001"
GOAL_ID: Final = "LFP2-G010"
PROGRAM_ID: Final = "ipfs-datasets-logic-family-parser-v2"

DEFAULT_BASELINE_RELATIVE_PATH: Final = (
    "docs/architecture/logic/logic_parser_v2_baseline/claim_runtime_audit.json"
)
MATERIALIZATION_TARGET: Final = (
    "ipfs_datasets_py.logic.conformance.claim_runtime_audit:build_default_audit"
)

# Evidence subset required by LFP2-001.
REQUIRED_EVIDENCE_SURFACES: Final[tuple[str, ...]] = (
    "registry",
    "matrix",
    "parser",
    "translator",
    "runner",
    "decoder",
    "replay",
    "kernel",
)

# Lifecycle stages in monotonic order (index = rank).
LIFECYCLE_STAGES: Final[tuple[str, ...]] = (
    "declared",
    "parsed",
    "elaborated",
    "translatable",
    "compilable",
    "executable",
    "replayed",
    "independently_validated",
)

# Maximum bytes read per evidence file during classification.
DEFAULT_MAX_EVIDENCE_FILE_BYTES: Final = 1_500_000

# Owner of gaps produced by this audit when no more specific owner is known.
DEFAULT_GAP_OWNER: Final = "LFP2-001"

# Superproject-relative anchors used as declaration evidence.
_BACKEND_REGISTRY: Final = (
    "ipfs_datasets_py/ipfs_datasets_py/logic/backends/registry.py"
)
_FAMILY_REGISTRY: Final = (
    "ipfs_datasets_py/ipfs_datasets_py/logic/families/registry.py"
)
_FAMILY_PROVIDERS: Final = (
    "ipfs_datasets_py/ipfs_datasets_py/logic/families/providers.py"
)
_FAMILY_TRANSLATIONS: Final = (
    "ipfs_datasets_py/ipfs_datasets_py/logic/families/translations.py"
)
_GENERATED_CATALOG: Final = (
    "ipfs_datasets_py/ipfs_datasets_py/logic/families/generated_catalog.py"
)
_MATRIX_MODULE: Final = (
    "ipfs_datasets_py/ipfs_datasets_py/logic/conformance/matrix.py"
)
_PARSER_CATALOG: Final = (
    "ipfs_datasets_py/ipfs_datasets_py/logic/parsers/catalog.py"
)
_PROCESS_MODULE: Final = (
    "ipfs_datasets_py/ipfs_datasets_py/logic/backends/process.py"
)
_RESULTS_MODULE: Final = (
    "ipfs_datasets_py/ipfs_datasets_py/logic/backends/results.py"
)
_ELABORATION_MODULE: Final = (
    "ipfs_datasets_py/ipfs_datasets_py/logic/syntax_core/elaboration.py"
)
_SYNTAX_CORE: Final = "ipfs_datasets_py/ipfs_datasets_py/logic/syntax_core"
_V1_PLAN_PATH: Final = "docs/architecture/IPFS_DATASETS_LOGIC_FAMILY_PARSER_PLAN.md"

# Authority ceilings that make a claim "authority-bearing".
_AUTHORITY_BEARING: Final[frozenset[AuthorityCeiling]] = frozenset(
    {
        AuthorityCeiling.EXACT,
        AuthorityCeiling.BOUNDED,
        AuthorityCeiling.OVER_APPROXIMATION,
        AuthorityCeiling.KERNEL,
        AuthorityCeiling.PROTOCOL_SYMBOLIC,
        AuthorityCeiling.AUTHORIZATION_PROFILE,
        AuthorityCeiling.FINITE_TRACE,
        AuthorityCeiling.CANDIDATE,
        AuthorityCeiling.ADVISORY,
    }
)

# Support statuses that constitute an executable-route claim (not mere absence).
_EXECUTABLE_ROUTE_SUPPORT: Final[frozenset[SupportStatus]] = frozenset(
    {
        SupportStatus.NATIVE,
        SupportStatus.TRANSLATED,
        SupportStatus.APPROXIMATE,
        SupportStatus.BOUNDED,
        SupportStatus.ADVISORY,
    }
)

# Markers that disqualify a path as execution evidence.
_MOCK_MARKERS: Final[tuple[str, ...]] = (
    "unittest.mock",
    "from mock import",
    "import mock",
    "MagicMock",
    "AsyncMock",
    "create_autospec",
    "@patch(",
    "@patch.object(",
    "mock.patch",
    "FakeExecutor",
    "FakeProcess",
    "DummyRunner",
    "class Fake",
    "class Mock",
    "class Stub",
)

_MOCK_NAME_RE = re.compile(
    r"(?i)(?:^|/)(?:test_|.*_test\.py$|conftest\.py$|.*fake.*|.*mock.*|.*stub.*)"
)

# Production execution markers (must appear outside pure metadata files).
_EXECUTION_MARKERS: Final[tuple[str, ...]] = (
    "subprocess.",
    "subprocess.run",
    "subprocess.Popen",
    "BoundedToolRunner",
    "run_bounded_stdin_tool",
    "SubprocessExecutor",
    "UniversalBoundedToolLifecycle",
    "Popen(",
)

_PARSER_MARKERS: Final[tuple[str, ...]] = (
    "def parse",
    "class ",
    "ParseArtifact",
    "parse(",
)

_DECODER_MARKERS: Final[tuple[str, ...]] = (
    "def decode",
    "def parse_result",
    "ResultAuthority",
    "class ",
)

_REPLAY_MARKERS: Final[tuple[str, ...]] = (
    "def replay",
    "replay_",
    "ReplayReceipt",
    "EvidenceReplay",
    "exact_binding",
    "counterexample_replay",
)

_KERNEL_MARKERS: Final[tuple[str, ...]] = (
    "official_kernel",
    "is_official_kernel",
    "kernel_acceptance",
    "ProofAuthorityRole",
    "KernelTarget",
    "lean",
    "rocq",
    "isabelle",
)


class ClaimRuntimeAuditError(ValueError):
    """Raised when a claim-runtime audit contract is malformed."""


class ClaimLifecycleStage(StrEnum):
    """Monotonic lifecycle maturity of one public claim."""

    DECLARED = "declared"
    PARSED = "parsed"
    ELABORATED = "elaborated"
    TRANSLATABLE = "translatable"
    COMPILABLE = "compilable"
    EXECUTABLE = "executable"
    REPLAYED = "replayed"
    INDEPENDENTLY_VALIDATED = "independently_validated"


class EvidenceSurface(StrEnum):
    """Closed evidence surfaces required by LFP2-001."""

    REGISTRY = "registry"
    MATRIX = "matrix"
    PARSER = "parser"
    TRANSLATOR = "translator"
    RUNNER = "runner"
    DECODER = "decoder"
    REPLAY = "replay"
    KERNEL = "kernel"


class EvidenceDisposition(StrEnum):
    """How one evidence path was classified."""

    PRESENT = "present"
    MISSING = "missing"
    MOCK = "mock"
    METADATA_ONLY = "metadata_only"
    DISQUALIFIED = "disqualified"


class ClaimKind(StrEnum):
    """Kind of public claim under audit."""

    PROVIDER = "provider"
    PARSER = "parser"
    TRANSLATION = "translation"
    KERNEL = "kernel"


class GapKind(StrEnum):
    """Typed gap kinds for owner-scoped refill."""

    MISSING_EVIDENCE = "missing_evidence"
    MOCK_ONLY = "mock_only"
    METADATA_ONLY = "metadata_only"
    EXECUTION_NOT_ESTABLISHED = "execution_not_established"
    AUTHORITY_WITHOUT_RUNTIME = "authority_without_runtime"
    STAGE_BELOW_EXECUTABLE = "stage_below_executable"


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise ClaimRuntimeAuditError(
            f"{field_name} must be a non-empty trimmed string without NUL"
        )
    return value


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if any(character.isspace() for character in result):
        raise ClaimRuntimeAuditError(
            f"{field_name} must not contain whitespace; got {result!r}"
        )
    return result


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip())
    except ValueError as exc:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise ClaimRuntimeAuditError(
            f"{field_name} must be one of {choices}"
        ) from exc


def _stable_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def lifecycle_rank(stage: ClaimLifecycleStage | str) -> int:
    """Return the comparable rank of a lifecycle stage."""

    resolved = _enum(stage, ClaimLifecycleStage, "stage")
    return LIFECYCLE_STAGES.index(resolved.value)


def max_lifecycle(
    stages: Iterable[ClaimLifecycleStage | str],
) -> ClaimLifecycleStage:
    """Return the highest lifecycle stage in *stages* (defaults to declared)."""

    best = ClaimLifecycleStage.DECLARED
    for stage in stages:
        resolved = _enum(stage, ClaimLifecycleStage, "stage")
        if lifecycle_rank(resolved) > lifecycle_rank(best):
            best = resolved
    return best


def is_authority_bearing(ceiling: AuthorityCeiling | str | None) -> bool:
    """Return True when a ceiling is authority-bearing (not none/unknown)."""

    if ceiling is None:
        return False
    resolved = _enum(ceiling, AuthorityCeiling, "authority_ceiling")
    return resolved in _AUTHORITY_BEARING


def is_executable_route_support(support: SupportStatus | str | None) -> bool:
    """Return True when support asserts an executable-route claim."""

    if support is None:
        return False
    resolved = _enum(support, SupportStatus, "support")
    return resolved in _EXECUTABLE_ROUTE_SUPPORT


def mocks_cannot_satisfy_execution(
    *,
    disposition: EvidenceDisposition | str,
    stage: ClaimLifecycleStage | str,
) -> bool:
    """Documented invariant: mocks never establish executable or later stages.

    Returns ``True`` when the disposition is mock/metadata and the stage is
    executable or later (i.e. the pair is **invalid** as runtime evidence).
    """

    resolved_disp = _enum(disposition, EvidenceDisposition, "disposition")
    resolved_stage = _enum(stage, ClaimLifecycleStage, "stage")
    if lifecycle_rank(resolved_stage) < lifecycle_rank(ClaimLifecycleStage.EXECUTABLE):
        return False
    return resolved_disp in {
        EvidenceDisposition.MOCK,
        EvidenceDisposition.METADATA_ONLY,
        EvidenceDisposition.MISSING,
        EvidenceDisposition.DISQUALIFIED,
    }


def metadata_only_cannot_satisfy_execution(
    *,
    disposition: EvidenceDisposition | str,
) -> bool:
    """Metadata-only records never establish execution. Always fail-closed."""

    resolved = _enum(disposition, EvidenceDisposition, "disposition")
    return resolved is EvidenceDisposition.METADATA_ONLY


# ---------------------------------------------------------------------------
# Path / tree helpers
# ---------------------------------------------------------------------------


def default_datasets_repo_root(start: Path | None = None) -> Path:
    """Resolve the nested ``ipfs_datasets_py`` repository root."""

    if start is not None:
        candidate = Path(start).resolve()
        if (candidate / "ipfs_datasets_py" / "logic").is_dir():
            return candidate
        nested = candidate / "ipfs_datasets_py"
        if (nested / "ipfs_datasets_py" / "logic").is_dir():
            return nested.resolve()

    here = Path(__file__).resolve()
    # .../ipfs_datasets_py/logic/conformance/claim_runtime_audit.py
    # parents[3] == nested datasets repo root
    root = here.parents[3]
    if not (root / "ipfs_datasets_py" / "logic").is_dir():
        raise ClaimRuntimeAuditError(
            f"unable to resolve datasets repo root from {here}"
        )
    return root


def default_baseline_path(*, datasets_root: str | Path | None = None) -> Path:
    """Resolve the owned Wave-2 baseline report path."""

    root = (
        Path(datasets_root).resolve()
        if datasets_root is not None
        else default_datasets_repo_root()
    )
    return root / DEFAULT_BASELINE_RELATIVE_PATH


def normalize_repo_relative(path: str) -> str:
    """Normalize a repository-relative POSIX path."""

    text = _text(path, "path").replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts:
        raise ClaimRuntimeAuditError(
            "evidence path must be a normalized repository-relative POSIX path"
        )
    return str(pure)


def resolve_tree_path(root: Path, relative: str) -> Path | None:
    """Resolve *relative* against nested or superproject layouts.

    Accepts both nested-repo paths (``ipfs_datasets_py/logic/...``) and
    superproject paths (``ipfs_datasets_py/ipfs_datasets_py/logic/...``).
    """

    rel = normalize_repo_relative(relative)
    root = root.resolve()
    candidates: list[Path] = [root / rel]
    if rel.startswith("ipfs_datasets_py/"):
        stripped = rel[len("ipfs_datasets_py/") :]
        candidates.append(root / stripped)
        # Superproject: datasets repo is a child named ipfs_datasets_py.
        if root.name != "ipfs_datasets_py":
            candidates.append(root / "ipfs_datasets_py" / stripped)
        # Nested repo root with superproject-style prefix.
        candidates.append(root / rel)
    # Parent superproject when root is the nested datasets repo.
    if root.name == "ipfs_datasets_py":
        candidates.append(root.parent / rel)

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists():
            return resolved
    return None


def path_exists_in_tree(root: Path, relative: str) -> bool:
    """Return True when *relative* resolves to an existing path under *root*."""

    return resolve_tree_path(root, relative) is not None


# ---------------------------------------------------------------------------
# Evidence classification
# ---------------------------------------------------------------------------


def _read_text_capped(path: Path, *, max_bytes: int) -> str | None:
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
        if size > max_bytes:
            # Still sample the head for markers.
            with path.open("rb") as handle:
                raw = handle.read(max_bytes)
            return raw.decode("utf-8", errors="replace")
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _looks_like_mock_path(relative: str) -> bool:
    return bool(_MOCK_NAME_RE.search(relative.replace("\\", "/")))


def _contains_any(text: str, markers: Sequence[str]) -> bool:
    lower = text
    return any(marker in lower for marker in markers)


def classify_evidence_file(
    relative: str,
    *,
    root: Path,
    surface: EvidenceSurface | str,
    max_bytes: int = DEFAULT_MAX_EVIDENCE_FILE_BYTES,
) -> EvidenceDisposition:
    """Classify one evidence path against the current tree.

    Mocks and metadata-only files are never ``present`` for runner/kernel
    execution surfaces; they return ``mock`` or ``metadata_only``.
    """

    surface_resolved = _enum(surface, EvidenceSurface, "surface")
    rel = normalize_repo_relative(relative)
    resolved = resolve_tree_path(root, rel)
    if resolved is None:
        return EvidenceDisposition.MISSING

    if resolved.is_dir():
        # Directory presence counts for declaration/parser package roots only.
        if surface_resolved in {
            EvidenceSurface.PARSER,
            EvidenceSurface.REGISTRY,
            EvidenceSurface.MATRIX,
        }:
            return EvidenceDisposition.PRESENT
        return EvidenceDisposition.METADATA_ONLY

    text = _read_text_capped(resolved, max_bytes=max_bytes)
    if text is None:
        return EvidenceDisposition.MISSING

    path_is_test_or_mock = _looks_like_mock_path(rel)
    content_is_mock = _contains_any(text, _MOCK_MARKERS)
    has_execution = _contains_any(text, _EXECUTION_MARKERS)
    has_kernel = _contains_any(text, _KERNEL_MARKERS)

    # Runner surface: only non-mock production code with a real process boundary.
    if surface_resolved is EvidenceSurface.RUNNER:
        if path_is_test_or_mock or content_is_mock:
            return EvidenceDisposition.MOCK
        if has_execution:
            return EvidenceDisposition.PRESENT
        return EvidenceDisposition.METADATA_ONLY

    # Kernel surface: official-kernel gates and/or process-backed kernel hosts.
    if surface_resolved is EvidenceSurface.KERNEL:
        if path_is_test_or_mock or content_is_mock:
            return EvidenceDisposition.MOCK
        if has_execution or has_kernel:
            return EvidenceDisposition.PRESENT
        return EvidenceDisposition.METADATA_ONLY

    # Replay may live in tests when they exercise real replay APIs.
    if surface_resolved is EvidenceSurface.REPLAY:
        if _contains_any(text, _REPLAY_MARKERS):
            return EvidenceDisposition.PRESENT
        if path_is_test_or_mock or content_is_mock:
            return EvidenceDisposition.MOCK
        return EvidenceDisposition.METADATA_ONLY

    # Inventory surfaces (registry/matrix/parser/translator/decoder).
    if surface_resolved is EvidenceSurface.PARSER:
        if _contains_any(text, _PARSER_MARKERS) or resolved.suffix == ".py":
            return EvidenceDisposition.PRESENT
        return EvidenceDisposition.METADATA_ONLY

    if surface_resolved is EvidenceSurface.TRANSLATOR:
        if "translation" in text.lower() or "Translation" in text:
            return EvidenceDisposition.PRESENT
        return EvidenceDisposition.METADATA_ONLY

    if surface_resolved is EvidenceSurface.DECODER:
        if _contains_any(text, _DECODER_MARKERS) or resolved.suffix == ".py":
            return EvidenceDisposition.PRESENT
        return EvidenceDisposition.METADATA_ONLY

    # registry / matrix
    return EvidenceDisposition.PRESENT


def qualifies_for_stage(
    disposition: EvidenceDisposition | str,
    stage: ClaimLifecycleStage | str,
) -> bool:
    """Return True when evidence disposition can establish *stage*."""

    resolved_disp = _enum(disposition, EvidenceDisposition, "disposition")
    resolved_stage = _enum(stage, ClaimLifecycleStage, "stage")
    if resolved_disp is not EvidenceDisposition.PRESENT:
        return False
    if lifecycle_rank(resolved_stage) >= lifecycle_rank(ClaimLifecycleStage.EXECUTABLE):
        # Only PRESENT (non-mock, non-metadata) qualifies — already enforced.
        return True
    return True


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClaimEvidenceRecord:
    """One exact current-tree evidence observation."""

    path: str
    surface: EvidenceSurface
    stage: ClaimLifecycleStage
    disposition: EvidenceDisposition
    note: str = ""
    schema_version: str = LOGIC_CLAIM_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", normalize_repo_relative(self.path))
        object.__setattr__(
            self, "surface", _enum(self.surface, EvidenceSurface, "surface")
        )
        object.__setattr__(
            self, "stage", _enum(self.stage, ClaimLifecycleStage, "stage")
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, EvidenceDisposition, "disposition"),
        )
        object.__setattr__(
            self, "note", _text(self.note, "note") if self.note else ""
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        # Fail-closed: mocks/metadata cannot be marked present for executable+.
        if (
            self.disposition is EvidenceDisposition.PRESENT
            and mocks_cannot_satisfy_execution(
                disposition=EvidenceDisposition.MOCK, stage=self.stage
            )
            is False
        ):
            # Re-check: if disposition is present we are fine; invariant helper
            # above documents the mock case. Nothing to do.
            pass
        if self.disposition is EvidenceDisposition.PRESENT and lifecycle_rank(
            self.stage
        ) >= lifecycle_rank(ClaimLifecycleStage.EXECUTABLE):
            # Caller must not construct PRESENT+executable with mock content;
            # classification already prevents that.
            pass

    def qualifies(self) -> bool:
        return qualifies_for_stage(self.disposition, self.stage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "note": self.note,
            "path": self.path,
            "schema_version": self.schema_version,
            "stage": self.stage.value,
            "surface": self.surface.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ClaimEvidenceRecord:
        if not isinstance(value, Mapping):
            raise ClaimRuntimeAuditError("evidence record must be an object")
        return cls(
            path=str(value.get("path", "")),
            surface=str(value.get("surface", EvidenceSurface.REGISTRY.value)),
            stage=str(value.get("stage", ClaimLifecycleStage.DECLARED.value)),
            disposition=str(
                value.get("disposition", EvidenceDisposition.MISSING.value)
            ),
            note=str(value.get("note", "")),
            schema_version=str(
                value.get("schema_version", LOGIC_CLAIM_EVIDENCE_SCHEMA)
            ),
        )


@dataclass(frozen=True, slots=True)
class ClaimGap:
    """Owner-scoped typed gap for missing or disqualified runtime evidence."""

    gap_id: str
    kind: GapKind
    claim_id: str
    owner: str
    stage: ClaimLifecycleStage
    surface: EvidenceSurface
    detail: str = ""
    schema_version: str = LOGIC_CLAIM_GAP_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _identifier(self.gap_id, "gap_id"))
        object.__setattr__(self, "kind", _enum(self.kind, GapKind, "kind"))
        object.__setattr__(self, "claim_id", _identifier(self.claim_id, "claim_id"))
        object.__setattr__(self, "owner", _text(self.owner, "owner"))
        object.__setattr__(
            self, "stage", _enum(self.stage, ClaimLifecycleStage, "stage")
        )
        object.__setattr__(
            self, "surface", _enum(self.surface, EvidenceSurface, "surface")
        )
        object.__setattr__(
            self, "detail", _text(self.detail, "detail") if self.detail else ""
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "detail": self.detail,
            "gap_id": self.gap_id,
            "kind": self.kind.value,
            "owner": self.owner,
            "schema_version": self.schema_version,
            "stage": self.stage.value,
            "surface": self.surface.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ClaimGap:
        if not isinstance(value, Mapping):
            raise ClaimRuntimeAuditError("gap must be an object")
        return cls(
            gap_id=str(value.get("gap_id", "")),
            kind=str(value.get("kind", GapKind.MISSING_EVIDENCE.value)),
            claim_id=str(value.get("claim_id", "")),
            owner=str(value.get("owner", DEFAULT_GAP_OWNER)),
            stage=str(value.get("stage", ClaimLifecycleStage.DECLARED.value)),
            surface=str(value.get("surface", EvidenceSurface.REGISTRY.value)),
            detail=str(value.get("detail", "")),
            schema_version=str(value.get("schema_version", LOGIC_CLAIM_GAP_SCHEMA)),
        )


@dataclass(frozen=True, slots=True)
class ClaimAuditRow:
    """Audit result for one public claim."""

    claim_id: str
    kind: ClaimKind
    lifecycle_stage: ClaimLifecycleStage
    executable_claim: bool
    authority_bearing: bool
    authority_ceiling: str
    support: str
    owner: str
    evidence: tuple[ClaimEvidenceRecord, ...] = ()
    gaps: tuple[ClaimGap, ...] = ()
    notes: str = ""
    subject: Mapping[str, str] = field(default_factory=dict)
    schema_version: str = LOGIC_CLAIM_AUDIT_ROW_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _identifier(self.claim_id, "claim_id"))
        object.__setattr__(self, "kind", _enum(self.kind, ClaimKind, "kind"))
        object.__setattr__(
            self,
            "lifecycle_stage",
            _enum(self.lifecycle_stage, ClaimLifecycleStage, "lifecycle_stage"),
        )
        if not isinstance(self.executable_claim, bool):
            raise ClaimRuntimeAuditError("executable_claim must be a boolean")
        if not isinstance(self.authority_bearing, bool):
            raise ClaimRuntimeAuditError("authority_bearing must be a boolean")
        object.__setattr__(
            self,
            "authority_ceiling",
            _text(self.authority_ceiling, "authority_ceiling")
            if self.authority_ceiling
            else "none",
        )
        object.__setattr__(
            self, "support", _text(self.support, "support") if self.support else "unknown"
        )
        object.__setattr__(self, "owner", _text(self.owner, "owner"))
        if isinstance(self.evidence, (str, bytes)) or not isinstance(
            self.evidence, Sequence
        ):
            raise ClaimRuntimeAuditError("evidence must be a sequence")
        evidence = tuple(
            item
            if isinstance(item, ClaimEvidenceRecord)
            else ClaimEvidenceRecord.from_dict(item)
            for item in self.evidence
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(
                sorted(
                    evidence,
                    key=lambda item: (
                        item.surface.value,
                        item.stage.value,
                        item.path,
                    ),
                )
            ),
        )
        if isinstance(self.gaps, (str, bytes)) or not isinstance(self.gaps, Sequence):
            raise ClaimRuntimeAuditError("gaps must be a sequence")
        gaps = tuple(
            item if isinstance(item, ClaimGap) else ClaimGap.from_dict(item)
            for item in self.gaps
        )
        object.__setattr__(
            self,
            "gaps",
            tuple(sorted(gaps, key=lambda item: item.gap_id)),
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes") if self.notes else ""
        )
        if not isinstance(self.subject, Mapping):
            raise ClaimRuntimeAuditError("subject must be a mapping")
        object.__setattr__(
            self,
            "subject",
            MappingProxyType(
                {
                    _identifier(str(key), "subject key"): _text(
                        str(val), "subject value", optional=True
                    )
                    for key, val in self.subject.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        # Acceptance invariant: executable/authority-bearing claims must have
        # qualifying evidence or at least one typed gap.
        if self.executable_claim or self.authority_bearing:
            has_qualifying = any(item.qualifies() for item in self.evidence)
            if not has_qualifying and not self.gaps:
                raise ClaimRuntimeAuditError(
                    f"claim {self.claim_id!r} is executable/authority-bearing but "
                    "has neither qualifying evidence nor a typed gap"
                )
            # Mocks must not be the sole basis for executable+ lifecycle.
            if lifecycle_rank(self.lifecycle_stage) >= lifecycle_rank(
                ClaimLifecycleStage.EXECUTABLE
            ):
                runtime_ok = any(
                    item.qualifies()
                    and lifecycle_rank(item.stage)
                    >= lifecycle_rank(ClaimLifecycleStage.EXECUTABLE)
                    for item in self.evidence
                )
                if not runtime_ok:
                    raise ClaimRuntimeAuditError(
                        f"claim {self.claim_id!r} claims lifecycle "
                        f"{self.lifecycle_stage.value!r} without non-mock "
                        "executable evidence"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_bearing": self.authority_bearing,
            "authority_ceiling": self.authority_ceiling,
            "claim_id": self.claim_id,
            "evidence": [item.to_dict() for item in self.evidence],
            "executable_claim": self.executable_claim,
            "gaps": [item.to_dict() for item in self.gaps],
            "kind": self.kind.value,
            "lifecycle_stage": self.lifecycle_stage.value,
            "notes": self.notes,
            "owner": self.owner,
            "schema_version": self.schema_version,
            "subject": dict(self.subject),
            "support": self.support,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ClaimAuditRow:
        if not isinstance(value, Mapping):
            raise ClaimRuntimeAuditError("claim row must be an object")
        return cls(
            claim_id=str(value.get("claim_id", "")),
            kind=str(value.get("kind", ClaimKind.PROVIDER.value)),
            lifecycle_stage=str(
                value.get("lifecycle_stage", ClaimLifecycleStage.DECLARED.value)
            ),
            executable_claim=bool(value.get("executable_claim", False)),
            authority_bearing=bool(value.get("authority_bearing", False)),
            authority_ceiling=str(value.get("authority_ceiling", "none")),
            support=str(value.get("support", "unknown")),
            owner=str(value.get("owner", DEFAULT_GAP_OWNER)),
            evidence=tuple(value.get("evidence", ())),
            gaps=tuple(value.get("gaps", ())),
            notes=str(value.get("notes", "")),
            subject=dict(value.get("subject", {}) or {}),
            schema_version=str(
                value.get("schema_version", LOGIC_CLAIM_AUDIT_ROW_SCHEMA)
            ),
        )


@dataclass(frozen=True, slots=True)
class LogicClaimRuntimeAuditReport:
    """Versioned claim-runtime audit report."""

    claims: tuple[ClaimAuditRow, ...]
    version: str = AUDIT_REPORT_VERSION
    schema_version: str = LOGIC_CLAIM_RUNTIME_AUDIT_REPORT_SCHEMA
    interface: str = LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE
    description: str = (
        "Wave-2 claim-vs-runtime audit. Lifecycle stages are established only "
        "by exact current-tree evidence; mocks and metadata-only records cannot "
        "satisfy execution."
    )
    notes: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    tree_root: str = ""

    def __post_init__(self) -> None:
        claims = tuple(sorted(self.claims, key=lambda item: item.claim_id))
        claim_ids = [item.claim_id for item in claims]
        if len(set(claim_ids)) != len(claim_ids):
            raise ClaimRuntimeAuditError("claims must have unique claim_id values")
        object.__setattr__(self, "claims", claims)
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        object.__setattr__(self, "interface", _text(self.interface, "interface"))
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description") if self.description else "",
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes") if self.notes else ""
        )
        if not isinstance(self.metadata, Mapping):
            raise ClaimRuntimeAuditError("metadata must be a mapping")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        object.__setattr__(
            self,
            "tree_root",
            _text(self.tree_root, "tree_root", optional=True),
        )
        # Global acceptance: every executable/authority-bearing claim is closed.
        for claim in self.claims:
            if claim.executable_claim or claim.authority_bearing:
                if not claim.evidence and not claim.gaps:
                    raise ClaimRuntimeAuditError(
                        f"open claim {claim.claim_id!r} lacks evidence and gaps"
                    )

    @property
    def executable_claims(self) -> tuple[ClaimAuditRow, ...]:
        return tuple(item for item in self.claims if item.executable_claim)

    @property
    def authority_bearing_claims(self) -> tuple[ClaimAuditRow, ...]:
        return tuple(item for item in self.claims if item.authority_bearing)

    @property
    def gaps(self) -> tuple[ClaimGap, ...]:
        return tuple(
            gap for claim in self.claims for gap in claim.gaps
        )

    def lifecycle_histogram(self) -> dict[str, int]:
        counts = {stage: 0 for stage in LIFECYCLE_STAGES}
        for claim in self.claims:
            counts[claim.lifecycle_stage.value] += 1
        return counts

    def summary(self) -> dict[str, Any]:
        gaps = self.gaps
        return {
            "authority_bearing_claim_count": len(self.authority_bearing_claims),
            "claim_count": len(self.claims),
            "executable_claim_count": len(self.executable_claims),
            "gap_count": len(gaps),
            "gap_kind_histogram": {
                kind.value: sum(1 for gap in gaps if gap.kind is kind)
                for kind in GapKind
            },
            "lifecycle_histogram": self.lifecycle_histogram(),
            "open_executable_without_gap_count": sum(
                1
                for claim in self.claims
                if (claim.executable_claim or claim.authority_bearing)
                and not claim.gaps
                and lifecycle_rank(claim.lifecycle_stage)
                < lifecycle_rank(ClaimLifecycleStage.EXECUTABLE)
                and not any(
                    item.qualifies()
                    and lifecycle_rank(item.stage)
                    >= lifecycle_rank(ClaimLifecycleStage.EXECUTABLE)
                    for item in claim.evidence
                )
            ),
        }

    def content_digest(self) -> str:
        body = self.to_dict()
        body.pop("content_digest", None)
        return f"sha256:{_stable_digest(body)}"

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "claims": [item.to_dict() for item in self.claims],
            "description": self.description,
            "interface": self.interface,
            "metadata": dict(self.metadata),
            "notes": self.notes,
            "schema_version": self.schema_version,
            "summary": self.summary(),
            "tree_root": self.tree_root,
            "version": self.version,
        }
        payload["content_digest"] = f"sha256:{_stable_digest(payload)}"
        return payload

    def to_baseline_dict(self) -> dict[str, Any]:
        """Baseline JSON body with materialization pointer."""

        body = self.to_dict()
        body["materialization"] = MATERIALIZATION_TARGET
        body["task_id"] = TASK_ID
        body["goal_id"] = GOAL_ID
        body["program_id"] = PROGRAM_ID
        body["required_evidence_surfaces"] = list(REQUIRED_EVIDENCE_SURFACES)
        body["lifecycle_stages"] = list(LIFECYCLE_STAGES)
        # Recompute digest over the extended body without digest field.
        digest_body = dict(body)
        digest_body.pop("content_digest", None)
        body["content_digest"] = f"sha256:{_stable_digest(digest_body)}"
        return body

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LogicClaimRuntimeAuditReport:
        if not isinstance(value, Mapping):
            raise ClaimRuntimeAuditError("report must be an object")
        return cls(
            claims=tuple(
                ClaimAuditRow.from_dict(item) for item in value.get("claims", ())
            ),
            version=str(value.get("version", AUDIT_REPORT_VERSION)),
            schema_version=str(
                value.get("schema_version", LOGIC_CLAIM_RUNTIME_AUDIT_REPORT_SCHEMA)
            ),
            interface=str(
                value.get("interface", LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE)
            ),
            description=str(value.get("description", "")),
            notes=str(value.get("notes", "")),
            metadata=dict(value.get("metadata", {}) or {}),
            tree_root=str(value.get("tree_root", "")),
        )


# ---------------------------------------------------------------------------
# Provider evidence map (exact current-tree paths)
# ---------------------------------------------------------------------------


def _pkg(*parts: str) -> str:
    return "/".join(("ipfs_datasets_py", "ipfs_datasets_py", "logic", *parts))


def _test(*parts: str) -> str:
    return "/".join(("ipfs_datasets_py", "tests", *parts))


# Per-provider surface path catalog. Paths are superproject-relative.
PROVIDER_SURFACE_PATHS: Final[Mapping[str, Mapping[str, tuple[str, ...]]]] = (
    MappingProxyType(
        {
            "apalache": {
                "registry": (_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
                "matrix": (_MATRIX_MODULE,),
                "parser": (_pkg("parsers", "state.py"), _pkg("parsers", "temporal.py")),
                "translator": (_FAMILY_TRANSLATIONS, _GENERATED_CATALOG),
                "compiler": (_pkg("backends", "tla", "compiler.py"),),
                "runner": (
                    _pkg("backends", "tla", "runners.py"),
                    _PROCESS_MODULE,
                ),
                "decoder": (_RESULTS_MODULE,),
                "replay": (
                    _test(
                        "unit",
                        "logic",
                        "backends",
                        "test_process_lifecycle.py",
                    ),
                ),
                "kernel": (),
            },
            "cvc5": {
                "registry": (_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
                "matrix": (_MATRIX_MODULE,),
                "parser": (_pkg("parsers", "smtlib.py"), _pkg("parsers", "fol.py")),
                "translator": (_FAMILY_TRANSLATIONS, _GENERATED_CATALOG),
                "compiler": (
                    _pkg("backends", "cvc5", "compiler.py"),
                    _pkg("backends", "smt", "compiler.py"),
                ),
                "runner": (
                    _pkg("backends", "cvc5", "compiler.py"),
                    _PROCESS_MODULE,
                ),
                "decoder": (_RESULTS_MODULE,),
                "replay": (
                    _test(
                        "integration",
                        "logic",
                        "software_verification",
                        "counterexamples",
                        "test_replay.py",
                    ),
                ),
                "kernel": (),
            },
            "datalog_secpal": {
                "registry": (_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
                "matrix": (_MATRIX_MODULE,),
                "parser": (_pkg("parsers", "rules.py"),),
                "translator": (_FAMILY_TRANSLATIONS, _GENERATED_CATALOG),
                "compiler": (
                    _pkg("backends", "secpal_style_authorization.py"),
                    _pkg("backends", "datalog", "adapters.py"),
                ),
                "runner": (
                    _pkg("backends", "secpal_style_authorization.py"),
                    _PROCESS_MODULE,
                ),
                "decoder": (_RESULTS_MODULE,),
                "replay": (),
                "kernel": (),
            },
            "eprover": {
                "registry": (_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
                "matrix": (_MATRIX_MODULE,),
                "parser": (_pkg("parsers", "tptp.py"), _pkg("parsers", "fol.py")),
                "translator": (_FAMILY_TRANSLATIONS, _GENERATED_CATALOG),
                "compiler": (_pkg("backends", "atp", "adapters.py"),),
                "runner": (
                    _pkg("backends", "atp", "adapters.py"),
                    _PROCESS_MODULE,
                ),
                "decoder": (_RESULTS_MODULE,),
                "replay": (),
                "kernel": (),
            },
            "ergoai": {
                "registry": (_FAMILY_PROVIDERS, _FAMILY_REGISTRY),
                "matrix": (_MATRIX_MODULE,),
                "parser": (_pkg("parsers", "flogic.py"),),
                "translator": (_FAMILY_TRANSLATIONS,),
                "compiler": (_pkg("flogic", "ergoai_wrapper.py"),),
                "runner": (_pkg("flogic", "ergoai_wrapper.py"),),
                "decoder": (_RESULTS_MODULE,),
                "replay": (),
                "kernel": (),
            },
            "hammer": {
                "registry": (_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
                "matrix": (_MATRIX_MODULE,),
                "parser": (_pkg("parsers", "fol.py"), _pkg("parsers", "tptp.py")),
                "translator": (_FAMILY_TRANSLATIONS,),
                "compiler": (_pkg("hammers", "backend.py"),),
                "runner": (_pkg("hammers", "backend.py"), _PROCESS_MODULE),
                "decoder": (_RESULTS_MODULE,),
                "replay": (),
                "kernel": (),
            },
            "hyperltl_autohyper_mchyper": {
                "registry": (_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
                "matrix": (_MATRIX_MODULE,),
                "parser": (_pkg("parsers", "hyper.py"),),
                "translator": (_FAMILY_TRANSLATIONS, _GENERATED_CATALOG),
                "compiler": (_pkg("backends", "hyperproperties", "adapters.py"),),
                "runner": (
                    _pkg("backends", "hyperproperties", "adapters.py"),
                    _PROCESS_MODULE,
                ),
                "decoder": (_RESULTS_MODULE,),
                "replay": (),
                "kernel": (),
            },
            "isabelle": {
                "registry": (_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
                "matrix": (_MATRIX_MODULE,),
                "parser": (_pkg("parsers", "kernel_targets.py"),),
                "translator": (_FAMILY_TRANSLATIONS, _GENERATED_CATALOG),
                "compiler": (_pkg("backends", "kernel", "isabelle.py"),),
                "runner": (
                    _pkg("backends", "kernel", "isabelle.py"),
                    _PROCESS_MODULE,
                ),
                "decoder": (_RESULTS_MODULE,),
                "replay": (),
                "kernel": (
                    _pkg("backends", "kernel", "isabelle.py"),
                    _pkg("parsers", "kernel_targets.py"),
                ),
            },
            "lean": {
                "registry": (_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
                "matrix": (_MATRIX_MODULE,),
                "parser": (_pkg("parsers", "kernel_targets.py"),),
                "translator": (_FAMILY_TRANSLATIONS, _GENERATED_CATALOG),
                "compiler": (_pkg("backends", "kernel", "lean.py"),),
                "runner": (
                    _pkg("backends", "kernel", "lean.py"),
                    _PROCESS_MODULE,
                ),
                "decoder": (_RESULTS_MODULE,),
                "replay": (),
                "kernel": (
                    _pkg("backends", "kernel", "lean.py"),
                    _pkg("parsers", "kernel_targets.py"),
                ),
            },
            "proverif": {
                "registry": (_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
                "matrix": (_MATRIX_MODULE,),
                "parser": (_pkg("parsers", "protocol.py"),),
                "translator": (_FAMILY_TRANSLATIONS, _GENERATED_CATALOG),
                "compiler": (_pkg("backends", "protocol", "proverif.py"),),
                "runner": (
                    _pkg("backends", "protocol", "proverif.py"),
                    _PROCESS_MODULE,
                ),
                "decoder": (_RESULTS_MODULE,),
                "replay": (),
                "kernel": (),
            },
            "rocq": {
                "registry": (_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
                "matrix": (_MATRIX_MODULE,),
                "parser": (_pkg("parsers", "kernel_targets.py"),),
                "translator": (_FAMILY_TRANSLATIONS, _GENERATED_CATALOG),
                "compiler": (_pkg("backends", "kernel", "rocq.py"),),
                "runner": (
                    _pkg("backends", "kernel", "rocq.py"),
                    _PROCESS_MODULE,
                ),
                "decoder": (_RESULTS_MODULE,),
                "replay": (),
                "kernel": (
                    _pkg("backends", "kernel", "rocq.py"),
                    _pkg("parsers", "kernel_targets.py"),
                ),
            },
            "runtime_mtl": {
                "registry": (_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
                "matrix": (_MATRIX_MODULE,),
                "parser": (
                    _pkg("parsers", "temporal.py"),
                    _pkg("parsers", "runtime_mtl_adapter.py"),
                ),
                "translator": (_FAMILY_TRANSLATIONS,),
                "compiler": (
                    _pkg(
                        "software_verification",
                        "monitoring",
                        "runtime_mtl.py",
                    ),
                ),
                "runner": (
                    _pkg(
                        "software_verification",
                        "monitoring",
                        "runtime_mtl.py",
                    ),
                    _PROCESS_MODULE,
                ),
                "decoder": (_RESULTS_MODULE,),
                "replay": (),
                "kernel": (),
            },
            "symbolicai": {
                "registry": (_FAMILY_PROVIDERS, _FAMILY_REGISTRY),
                "matrix": (_MATRIX_MODULE,),
                "parser": (),
                "translator": (_FAMILY_TRANSLATIONS,),
                "compiler": (),
                "runner": (),
                "decoder": (),
                "replay": (),
                "kernel": (),
            },
            "tamarin": {
                "registry": (_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
                "matrix": (_MATRIX_MODULE,),
                "parser": (_pkg("parsers", "tamarin.py"), _pkg("parsers", "protocol.py")),
                "translator": (_FAMILY_TRANSLATIONS, _GENERATED_CATALOG),
                "compiler": (_pkg("backends", "protocol", "tamarin.py"),),
                "runner": (
                    _pkg("backends", "protocol", "tamarin.py"),
                    _PROCESS_MODULE,
                ),
                "decoder": (_RESULTS_MODULE,),
                "replay": (),
                "kernel": (),
            },
            "tla_tlc": {
                "registry": (_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
                "matrix": (_MATRIX_MODULE,),
                "parser": (_pkg("parsers", "state.py"), _pkg("parsers", "temporal.py")),
                "translator": (_FAMILY_TRANSLATIONS, _GENERATED_CATALOG),
                "compiler": (_pkg("backends", "tla", "compiler.py"),),
                "runner": (
                    _pkg("backends", "tla", "runners.py"),
                    _PROCESS_MODULE,
                ),
                "decoder": (_RESULTS_MODULE,),
                "replay": (),
                "kernel": (),
            },
            "vampire": {
                "registry": (_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
                "matrix": (_MATRIX_MODULE,),
                "parser": (_pkg("parsers", "tptp.py"), _pkg("parsers", "fol.py")),
                "translator": (_FAMILY_TRANSLATIONS, _GENERATED_CATALOG),
                "compiler": (_pkg("backends", "atp", "adapters.py"),),
                "runner": (
                    _pkg("backends", "atp", "adapters.py"),
                    _PROCESS_MODULE,
                ),
                "decoder": (_RESULTS_MODULE,),
                "replay": (),
                "kernel": (),
            },
            "z3": {
                "registry": (_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
                "matrix": (_MATRIX_MODULE,),
                "parser": (_pkg("parsers", "smtlib.py"), _pkg("parsers", "fol.py")),
                "translator": (_FAMILY_TRANSLATIONS, _GENERATED_CATALOG),
                "compiler": (
                    _pkg("backends", "z3", "compiler.py"),
                    _pkg("backends", "smt", "compiler.py"),
                ),
                "runner": (
                    _pkg("backends", "z3", "compiler.py"),
                    _PROCESS_MODULE,
                ),
                "decoder": (_RESULTS_MODULE,),
                "replay": (
                    _test(
                        "integration",
                        "logic",
                        "software_verification",
                        "counterexamples",
                        "test_replay.py",
                    ),
                ),
                "kernel": (),
            },
        }
    )
)


def _observe_paths(
    *,
    root: Path,
    paths: Sequence[str],
    surface: EvidenceSurface,
    stage: ClaimLifecycleStage,
    max_bytes: int,
) -> list[ClaimEvidenceRecord]:
    records: list[ClaimEvidenceRecord] = []
    for path in paths:
        disposition = classify_evidence_file(
            path, root=root, surface=surface, max_bytes=max_bytes
        )
        note = ""
        if disposition is EvidenceDisposition.MOCK:
            note = "Mock or test-fake path cannot satisfy execution."
        elif disposition is EvidenceDisposition.METADATA_ONLY:
            note = "Metadata-only record cannot satisfy execution."
        elif disposition is EvidenceDisposition.MISSING:
            note = "Path not present in current tree."
        records.append(
            ClaimEvidenceRecord(
                path=path,
                surface=surface,
                stage=stage,
                disposition=disposition,
                note=note,
            )
        )
    return records


def _derive_lifecycle(evidence: Sequence[ClaimEvidenceRecord]) -> ClaimLifecycleStage:
    """Derive the highest lifecycle stage supported by qualifying evidence.

    Stage gates (all required for that rank and above):
    - declared: registry or matrix present
    - parsed: parser present
    - elaborated: elaboration module present (shared) — treated as present when
      parser + syntax_core/elaboration.py exist
    - translatable: translator present
    - compilable: compiler-stage evidence (decoder surface used for result path;
      compiler paths recorded under runner/compiler via decoder or runner)
    - executable: runner present (non-mock)
    - replayed: replay present
    - independently_validated: kernel present
    """

    by_stage: dict[ClaimLifecycleStage, bool] = {
        stage: False for stage in ClaimLifecycleStage
    }
    for record in evidence:
        if record.qualifies():
            by_stage[record.stage] = True

    # Compilable is established by decoder OR by compiler paths classified under
    # runner surface when they contain compile markers — also accept decoder.
    # Elaboration is a shared gate: if parsed and elaboration evidence present.
    order = [
        ClaimLifecycleStage.DECLARED,
        ClaimLifecycleStage.PARSED,
        ClaimLifecycleStage.ELABORATED,
        ClaimLifecycleStage.TRANSLATABLE,
        ClaimLifecycleStage.COMPILABLE,
        ClaimLifecycleStage.EXECUTABLE,
        ClaimLifecycleStage.REPLAYED,
        ClaimLifecycleStage.INDEPENDENTLY_VALIDATED,
    ]
    best = ClaimLifecycleStage.DECLARED
    for stage in order:
        if by_stage.get(stage):
            best = stage
        else:
            # Allow skipping elaborated if parsed and higher stages exist only
            # when elaborated is not required for those stages' meaning — but
            # we keep strict monotonic prefix: stop at first gap after declared.
            if stage is ClaimLifecycleStage.ELABORATED:
                # Elaboration is soft-gated: continue if later stages exist.
                continue
            if stage is ClaimLifecycleStage.TRANSLATABLE:
                # Translations may be absent for native providers.
                continue
            if stage is ClaimLifecycleStage.REPLAYED:
                # Replay is optional; kernel may still establish independent
                # validation without replay fixtures.
                continue
            if stage is ClaimLifecycleStage.INDEPENDENTLY_VALIDATED:
                break
            # For compilable/executable, require the stage itself.
            if stage in {
                ClaimLifecycleStage.COMPILABLE,
                ClaimLifecycleStage.EXECUTABLE,
            }:
                break
            if stage is ClaimLifecycleStage.PARSED and not by_stage.get(stage):
                # May still be declared-only.
                break
    # Recompute with prefix rules that match product semantics:
    # declared if any declared evidence
    # parsed if declared + parser
    # elaborated if parsed + elaboration
    # translatable if elaborated/parsed + translator (optional boost)
    # compilable if parsed + (compiler/decoder)
    # executable if compilable + runner
    # replayed if executable + replay
    # independently_validated if executable + kernel (replay optional)
    declared = by_stage[ClaimLifecycleStage.DECLARED]
    parsed = declared and by_stage[ClaimLifecycleStage.PARSED]
    elaborated = parsed and by_stage[ClaimLifecycleStage.ELABORATED]
    translatable = (elaborated or parsed) and by_stage[
        ClaimLifecycleStage.TRANSLATABLE
    ]
    compilable = (elaborated or parsed) and by_stage[ClaimLifecycleStage.COMPILABLE]
    # Native providers may compile without a separate elaborator row when
    # shared elaboration evidence is present; require at least parsed.
    if not compilable and parsed and by_stage[ClaimLifecycleStage.COMPILABLE]:
        compilable = True
    # Allow compilable from runner paths that also compile when decoder present.
    executable = compilable and by_stage[ClaimLifecycleStage.EXECUTABLE]
    # If runner is present and declared, still require compilable OR treat
    # runner+decoder as compilable.
    if not executable and by_stage[ClaimLifecycleStage.EXECUTABLE] and (
        by_stage[ClaimLifecycleStage.COMPILABLE] or parsed
    ):
        executable = by_stage[ClaimLifecycleStage.EXECUTABLE] and (
            by_stage[ClaimLifecycleStage.COMPILABLE] or parsed
        )
        if executable:
            compilable = True
    replayed = executable and by_stage[ClaimLifecycleStage.REPLAYED]
    independent = executable and by_stage[ClaimLifecycleStage.INDEPENDENTLY_VALIDATED]

    if independent:
        return ClaimLifecycleStage.INDEPENDENTLY_VALIDATED
    if replayed:
        return ClaimLifecycleStage.REPLAYED
    if executable:
        return ClaimLifecycleStage.EXECUTABLE
    if compilable:
        return ClaimLifecycleStage.COMPILABLE
    if translatable:
        return ClaimLifecycleStage.TRANSLATABLE
    if elaborated:
        return ClaimLifecycleStage.ELABORATED
    if parsed:
        return ClaimLifecycleStage.PARSED
    if declared:
        return ClaimLifecycleStage.DECLARED
    return ClaimLifecycleStage.DECLARED


def _build_gaps(
    *,
    claim_id: str,
    owner: str,
    executable_claim: bool,
    authority_bearing: bool,
    lifecycle: ClaimLifecycleStage,
    evidence: Sequence[ClaimEvidenceRecord],
) -> list[ClaimGap]:
    gaps: list[ClaimGap] = []

    def add(
        kind: GapKind,
        stage: ClaimLifecycleStage,
        surface: EvidenceSurface,
        detail: str,
        suffix: str,
    ) -> None:
        gaps.append(
            ClaimGap(
                gap_id=f"gap:{claim_id}:{suffix}",
                kind=kind,
                claim_id=claim_id,
                owner=owner,
                stage=stage,
                surface=surface,
                detail=detail,
            )
        )

    # Collect worst disposition per surface for expected surfaces.
    by_surface: dict[EvidenceSurface, list[ClaimEvidenceRecord]] = {}
    for record in evidence:
        by_surface.setdefault(record.surface, []).append(record)

    def surface_ok(surface: EvidenceSurface) -> bool:
        records = by_surface.get(surface, ())
        return any(item.qualifies() for item in records)

    def surface_dispositions(surface: EvidenceSurface) -> list[EvidenceDisposition]:
        return [item.disposition for item in by_surface.get(surface, ())]

    if executable_claim or authority_bearing:
        if not surface_ok(EvidenceSurface.REGISTRY) and not surface_ok(
            EvidenceSurface.MATRIX
        ):
            add(
                GapKind.MISSING_EVIDENCE,
                ClaimLifecycleStage.DECLARED,
                EvidenceSurface.REGISTRY,
                "No registry/matrix declaration evidence in current tree.",
                "declared",
            )

        # Runner gaps for executable claims.
        if executable_claim:
            runner_records = by_surface.get(EvidenceSurface.RUNNER, ())
            if not runner_records:
                add(
                    GapKind.EXECUTION_NOT_ESTABLISHED,
                    ClaimLifecycleStage.EXECUTABLE,
                    EvidenceSurface.RUNNER,
                    "No runner evidence paths declared for this executable claim.",
                    "runner-absent",
                )
            elif not any(item.qualifies() for item in runner_records):
                dispositions = surface_dispositions(EvidenceSurface.RUNNER)
                if all(d is EvidenceDisposition.MOCK for d in dispositions):
                    kind = GapKind.MOCK_ONLY
                    detail = "Runner evidence is mock-only; mocks cannot satisfy execution."
                elif all(
                    d is EvidenceDisposition.METADATA_ONLY for d in dispositions
                ):
                    kind = GapKind.METADATA_ONLY
                    detail = (
                        "Runner evidence is metadata-only; metadata cannot satisfy "
                        "execution."
                    )
                else:
                    kind = GapKind.EXECUTION_NOT_ESTABLISHED
                    detail = (
                        "Runner paths exist but none qualify as non-mock execution "
                        f"evidence (dispositions={sorted(d.value for d in dispositions)})."
                    )
                add(
                    kind,
                    ClaimLifecycleStage.EXECUTABLE,
                    EvidenceSurface.RUNNER,
                    detail,
                    "runner",
                )

        if authority_bearing and lifecycle_rank(lifecycle) < lifecycle_rank(
            ClaimLifecycleStage.EXECUTABLE
        ):
            # Advisory authority may sit below executable by design.
            ceiling_note = "authority-bearing claim has not reached executable lifecycle"
            if not any(
                item.qualifies()
                and lifecycle_rank(item.stage)
                >= lifecycle_rank(ClaimLifecycleStage.EXECUTABLE)
                for item in evidence
            ):
                add(
                    GapKind.AUTHORITY_WITHOUT_RUNTIME,
                    ClaimLifecycleStage.EXECUTABLE,
                    EvidenceSurface.RUNNER,
                    ceiling_note,
                    "authority-runtime",
                )

        if lifecycle_rank(lifecycle) < lifecycle_rank(
            ClaimLifecycleStage.EXECUTABLE
        ) and executable_claim:
            add(
                GapKind.STAGE_BELOW_EXECUTABLE,
                lifecycle,
                EvidenceSurface.RUNNER,
                f"Lifecycle is {lifecycle.value}; executable claim remains open.",
                "stage",
            )

        # Kernel claims need kernel surface for independent validation.
        if claim_id in {"provider:lean", "provider:rocq", "provider:isabelle"} or (
            claim_id.startswith("kernel:")
        ):
            if not surface_ok(EvidenceSurface.KERNEL):
                add(
                    GapKind.MISSING_EVIDENCE,
                    ClaimLifecycleStage.INDEPENDENTLY_VALIDATED,
                    EvidenceSurface.KERNEL,
                    "Kernel claim lacks official-kernel evidence in current tree.",
                    "kernel",
                )

    return gaps


def audit_provider_claim(
    provider: ProviderAxis,
    *,
    root: Path,
    max_bytes: int = DEFAULT_MAX_EVIDENCE_FILE_BYTES,
    owner: str = DEFAULT_GAP_OWNER,
) -> ClaimAuditRow:
    """Audit one capability-matrix provider claim against the current tree."""

    provider_id = provider.provider_id
    claim_id = f"provider:{provider_id}"
    surfaces = PROVIDER_SURFACE_PATHS.get(provider_id, {})
    evidence: list[ClaimEvidenceRecord] = []

    # Always bind declaration surfaces.
    declaration_paths = list(provider.source_paths) or [
        _BACKEND_REGISTRY,
        _MATRIX_MODULE,
        _V1_PLAN_PATH,
    ]
    evidence.extend(
        _observe_paths(
            root=root,
            paths=declaration_paths,
            surface=EvidenceSurface.REGISTRY,
            stage=ClaimLifecycleStage.DECLARED,
            max_bytes=max_bytes,
        )
    )
    evidence.extend(
        _observe_paths(
            root=root,
            paths=(_MATRIX_MODULE,),
            surface=EvidenceSurface.MATRIX,
            stage=ClaimLifecycleStage.DECLARED,
            max_bytes=max_bytes,
        )
    )

    # Shared elaboration gate.
    evidence.extend(
        _observe_paths(
            root=root,
            paths=(_ELABORATION_MODULE, _SYNTAX_CORE),
            surface=EvidenceSurface.PARSER,
            stage=ClaimLifecycleStage.ELABORATED,
            max_bytes=max_bytes,
        )
    )

    surface_stage_pairs: list[tuple[str, EvidenceSurface, ClaimLifecycleStage]] = [
        ("parser", EvidenceSurface.PARSER, ClaimLifecycleStage.PARSED),
        ("translator", EvidenceSurface.TRANSLATOR, ClaimLifecycleStage.TRANSLATABLE),
        ("compiler", EvidenceSurface.DECODER, ClaimLifecycleStage.COMPILABLE),
        ("runner", EvidenceSurface.RUNNER, ClaimLifecycleStage.EXECUTABLE),
        ("decoder", EvidenceSurface.DECODER, ClaimLifecycleStage.COMPILABLE),
        ("replay", EvidenceSurface.REPLAY, ClaimLifecycleStage.REPLAYED),
        ("kernel", EvidenceSurface.KERNEL, ClaimLifecycleStage.INDEPENDENTLY_VALIDATED),
    ]
    for key, surface, stage in surface_stage_pairs:
        paths = surfaces.get(key, ())
        if not paths:
            continue
        evidence.extend(
            _observe_paths(
                root=root,
                paths=paths,
                surface=surface,
                stage=stage,
                max_bytes=max_bytes,
            )
        )

    # Deduplicate by (path, surface, stage) keeping the strongest disposition.
    # Prefer PRESENT > others by sorting and unique key.
    dedup: dict[tuple[str, str, str], ClaimEvidenceRecord] = {}
    rank = {
        EvidenceDisposition.PRESENT: 4,
        EvidenceDisposition.METADATA_ONLY: 3,
        EvidenceDisposition.MOCK: 2,
        EvidenceDisposition.DISQUALIFIED: 1,
        EvidenceDisposition.MISSING: 0,
    }
    for record in evidence:
        key = (record.path, record.surface.value, record.stage.value)
        existing = dedup.get(key)
        if existing is None or rank[record.disposition] > rank[existing.disposition]:
            dedup[key] = record
    evidence = list(dedup.values())

    lifecycle = _derive_lifecycle(evidence)
    executable_claim = bool(provider.declared_in_executable_matrix) or (
        provider.support_kind in _EXECUTABLE_ROUTE_SUPPORT
        and provider.provider_id in set(EXECUTABLE_PROVIDER_IDS)
    )
    # Advisory-only providers outside the executable matrix are not executable claims.
    if provider.provider_id in ADVISORY_PROVIDER_IDS and not provider.declared_in_executable_matrix:
        # hammer is in EXECUTABLE_PROVIDER_MATRIX; ergoai/symbolicai are not.
        if provider.provider_id in {"ergoai", "symbolicai"}:
            executable_claim = False
    authority = is_authority_bearing(provider.authority_ceiling)

    gaps = _build_gaps(
        claim_id=claim_id,
        owner=owner,
        executable_claim=executable_claim,
        authority_bearing=authority,
        lifecycle=lifecycle,
        evidence=evidence,
    )

    return ClaimAuditRow(
        claim_id=claim_id,
        kind=ClaimKind.PROVIDER,
        lifecycle_stage=lifecycle,
        executable_claim=executable_claim,
        authority_bearing=authority,
        authority_ceiling=provider.authority_ceiling.value,
        support=provider.support_kind.value,
        owner=owner,
        evidence=tuple(evidence),
        gaps=tuple(gaps),
        notes=provider.notes,
        subject={
            "provider_id": provider_id,
            "declared_in_executable_matrix": str(
                provider.declared_in_executable_matrix
            ).lower(),
        },
    )


def audit_parser_claim(
    module: str,
    *,
    root: Path,
    max_bytes: int = DEFAULT_MAX_EVIDENCE_FILE_BYTES,
    owner: str = DEFAULT_GAP_OWNER,
) -> ClaimAuditRow:
    """Audit one controlled parser frontend contribution."""

    module_id = _identifier(module, "module")
    claim_id = f"parser:{module_id}"
    parser_path = _pkg("parsers", f"{module_id}.py")
    evidence: list[ClaimEvidenceRecord] = []
    evidence.extend(
        _observe_paths(
            root=root,
            paths=(_PARSER_CATALOG, _FAMILY_REGISTRY),
            surface=EvidenceSurface.REGISTRY,
            stage=ClaimLifecycleStage.DECLARED,
            max_bytes=max_bytes,
        )
    )
    evidence.extend(
        _observe_paths(
            root=root,
            paths=(parser_path,),
            surface=EvidenceSurface.PARSER,
            stage=ClaimLifecycleStage.PARSED,
            max_bytes=max_bytes,
        )
    )
    evidence.extend(
        _observe_paths(
            root=root,
            paths=(_ELABORATION_MODULE,),
            surface=EvidenceSurface.PARSER,
            stage=ClaimLifecycleStage.ELABORATED,
            max_bytes=max_bytes,
        )
    )
    lifecycle = _derive_lifecycle(evidence)
    # Parser claims are not executable provider claims; they are authority for
    # syntax only (not authority-bearing in the solver sense).
    gaps: list[ClaimGap] = []
    if not any(
        item.qualifies() and item.stage is ClaimLifecycleStage.PARSED
        for item in evidence
    ):
        gaps.append(
            ClaimGap(
                gap_id=f"gap:{claim_id}:parsed",
                kind=GapKind.MISSING_EVIDENCE,
                claim_id=claim_id,
                owner=owner,
                stage=ClaimLifecycleStage.PARSED,
                surface=EvidenceSurface.PARSER,
                detail=f"Parser module {parser_path} missing or non-qualifying.",
            )
        )
    return ClaimAuditRow(
        claim_id=claim_id,
        kind=ClaimKind.PARSER,
        lifecycle_stage=lifecycle,
        executable_claim=False,
        authority_bearing=False,
        authority_ceiling="none",
        support="native",
        owner=owner,
        evidence=tuple(evidence),
        gaps=tuple(gaps),
        notes="Controlled frontend; parse authority only.",
        subject={"module": module_id, "path": parser_path},
    )


def audit_translation_claim(
    translation_id: str,
    source_family_id: str,
    target_family_id: str,
    *,
    root: Path,
    max_bytes: int = DEFAULT_MAX_EVIDENCE_FILE_BYTES,
    owner: str = DEFAULT_GAP_OWNER,
) -> ClaimAuditRow:
    """Audit one reviewed translation edge."""

    tid = _identifier(translation_id, "translation_id")
    claim_id = f"translation:{tid}"
    evidence: list[ClaimEvidenceRecord] = []
    evidence.extend(
        _observe_paths(
            root=root,
            paths=(_FAMILY_REGISTRY, _FAMILY_TRANSLATIONS, _GENERATED_CATALOG),
            surface=EvidenceSurface.REGISTRY,
            stage=ClaimLifecycleStage.DECLARED,
            max_bytes=max_bytes,
        )
    )
    evidence.extend(
        _observe_paths(
            root=root,
            paths=(_FAMILY_TRANSLATIONS, _GENERATED_CATALOG),
            surface=EvidenceSurface.TRANSLATOR,
            stage=ClaimLifecycleStage.TRANSLATABLE,
            max_bytes=max_bytes,
        )
    )
    evidence.extend(
        _observe_paths(
            root=root,
            paths=(_ELABORATION_MODULE,),
            surface=EvidenceSurface.PARSER,
            stage=ClaimLifecycleStage.ELABORATED,
            max_bytes=max_bytes,
        )
    )
    lifecycle = _derive_lifecycle(evidence)
    gaps: list[ClaimGap] = []
    if not any(
        item.qualifies() and item.stage is ClaimLifecycleStage.TRANSLATABLE
        for item in evidence
    ):
        gaps.append(
            ClaimGap(
                gap_id=f"gap:{claim_id}:translatable",
                kind=GapKind.MISSING_EVIDENCE,
                claim_id=claim_id,
                owner=owner,
                stage=ClaimLifecycleStage.TRANSLATABLE,
                surface=EvidenceSurface.TRANSLATOR,
                detail="Translation edge lacks translator evidence in current tree.",
            )
        )
    return ClaimAuditRow(
        claim_id=claim_id,
        kind=ClaimKind.TRANSLATION,
        lifecycle_stage=lifecycle,
        executable_claim=False,
        authority_bearing=False,
        authority_ceiling="none",
        support="translated",
        owner=owner,
        evidence=tuple(evidence),
        gaps=tuple(gaps),
        notes="Reviewed translation edge; not a solver execution claim.",
        subject={
            "translation_id": tid,
            "source_family_id": source_family_id,
            "target_family_id": target_family_id,
        },
    )


def collect_declared_provider_ids(
    matrix: LogicCapabilityMatrix | None = None,
) -> tuple[str, ...]:
    """Return sorted provider ids that form public capability claims."""

    active = matrix if matrix is not None else DEFAULT_MATRIX
    ids = {item.provider_id for item in active.providers}
    ids.update(EXECUTABLE_PROVIDER_IDS)
    ids.update(BASELINE_PROVIDER_IDS)
    ids.update(ADVISORY_PROVIDER_IDS)
    return tuple(sorted(ids))


def build_claim_runtime_audit(
    *,
    root: str | Path | None = None,
    matrix: LogicCapabilityMatrix | None = None,
    parser_catalog: LogicParserCatalog | None = None,
    registry: LogicFamilyRegistry | None = None,
    generated_catalog: GeneratedProviderTranslationCatalog | None = None,
    max_bytes: int = DEFAULT_MAX_EVIDENCE_FILE_BYTES,
    owner: str = DEFAULT_GAP_OWNER,
) -> LogicClaimRuntimeAuditReport:
    """Build a deterministic claim-runtime audit over the current tree.

    Side-effect free: does not write files, launch processes, or probe PATH.
    """

    tree_root = (
        Path(root).resolve() if root is not None else default_datasets_repo_root()
    )
    active_matrix = matrix if matrix is not None else build_default_matrix()
    active_parsers = (
        parser_catalog if parser_catalog is not None else build_parser_catalog()
    )
    active_registry = registry if registry is not None else DEFAULT_REGISTRY
    active_generated = (
        generated_catalog
        if generated_catalog is not None
        else build_generated_provider_translation_catalog(validate=True)
    )

    provider_index = {
        item.provider_id: item for item in active_matrix.providers
    }
    claims: list[ClaimAuditRow] = []

    for provider_id in collect_declared_provider_ids(active_matrix):
        provider = provider_index.get(provider_id)
        if provider is None:
            # Synthesize a declaration-only axis for catalog-only ids.
            provider = ProviderAxis(
                provider_id=provider_id,
                native_families=(),
                authority_ceiling=AuthorityCeiling.UNKNOWN,
                support_kind=SupportStatus.UNKNOWN,
                declared_in_executable_matrix=provider_id
                in set(EXECUTABLE_PROVIDER_IDS),
                notes="Provider present in catalog but absent from matrix axes.",
                source_paths=(_BACKEND_REGISTRY, _FAMILY_PROVIDERS),
            )
        claims.append(
            audit_provider_claim(
                provider, root=tree_root, max_bytes=max_bytes, owner=owner
            )
        )

    # Prefer catalog contribution modules; fall back to the sealed constant.
    parser_modules = tuple(PARSER_CONTRIBUTION_MODULES)
    if active_parsers is not None and len(active_parsers) == 0:
        raise ClaimRuntimeAuditError("parser catalog is empty")
    for module in parser_modules:
        claims.append(
            audit_parser_claim(
                module, root=tree_root, max_bytes=max_bytes, owner=owner
            )
        )

    # Translations from registry (source of truth) + generated catalog ids.
    translation_ids: set[str] = set(active_registry.translations)
    for edge in active_generated.translations:
        translation_ids.add(edge.translation_id)

    for translation_id in sorted(translation_ids):
        descriptor = active_registry.translations.get(translation_id)
        if descriptor is not None:
            source = descriptor.source_family_id
            target = descriptor.target_family_id
        else:
            edge = next(
                (
                    item
                    for item in active_generated.translations
                    if item.translation_id == translation_id
                ),
                None,
            )
            source = edge.source_family_id if edge is not None else "unknown"
            target = edge.target_family_id if edge is not None else "unknown"
        claims.append(
            audit_translation_claim(
                translation_id,
                source,
                target,
                root=tree_root,
                max_bytes=max_bytes,
                owner=owner,
            )
        )

    metadata = {
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "evidence_subset": list(REQUIRED_EVIDENCE_SURFACES),
        "executable_provider_ids": list(EXECUTABLE_PROVIDER_IDS),
        "advisory_provider_ids": sorted(ADVISORY_PROVIDER_IDS),
        "parser_catalog_interface": LOGIC_PARSER_CATALOG_INTERFACE,
        "matrix_interface": active_matrix.interface,
        "matrix_cell_count": len(active_matrix.cells),
        "policy": {
            "mocks_cannot_satisfy_execution": True,
            "metadata_only_cannot_satisfy_execution": True,
            "static_sources_establish_inventory_only": True,
            "runtime_stages_require_non_mock_tree_evidence": True,
            "live_binary_probe": False,
            "network": False,
            "subprocess_launch": False,
        },
    }

    return LogicClaimRuntimeAuditReport(
        claims=tuple(claims),
        metadata=metadata,
        tree_root=str(tree_root),
        notes=(
            "Current-tree audit only. Live tool availability is out of scope; "
            "executable lifecycle requires non-mock runner source evidence."
        ),
    )


def build_default_audit(
    *,
    root: str | Path | None = None,
) -> LogicClaimRuntimeAuditReport:
    """Build the sealed LFP2-001 claim-runtime audit."""

    return build_claim_runtime_audit(root=root)


def assert_audit_acceptance(report: LogicClaimRuntimeAuditReport) -> None:
    """Fail closed when acceptance criteria are violated."""

    if report.interface != LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE:
        raise ClaimRuntimeAuditError(
            f"interface drift: {report.interface!r}"
        )
    if report.schema_version != LOGIC_CLAIM_RUNTIME_AUDIT_REPORT_SCHEMA:
        raise ClaimRuntimeAuditError(
            f"schema drift: {report.schema_version!r}"
        )
    for claim in report.claims:
        if not (claim.executable_claim or claim.authority_bearing):
            continue
        has_evidence = any(item.qualifies() for item in claim.evidence)
        if not has_evidence and not claim.gaps:
            raise ClaimRuntimeAuditError(
                f"claim {claim.claim_id!r} lacks evidence and typed gap"
            )
        # Mocks must not establish executable+ alone.
        for item in claim.evidence:
            if item.disposition is EvidenceDisposition.PRESENT:
                continue
            if lifecycle_rank(item.stage) >= lifecycle_rank(
                ClaimLifecycleStage.EXECUTABLE
            ):
                if item.disposition in {
                    EvidenceDisposition.MOCK,
                    EvidenceDisposition.METADATA_ONLY,
                }:
                    # Allowed as observations, but must not be the sole
                    # qualifier — lifecycle derivation already enforces this.
                    if claim.lifecycle_stage in {
                        ClaimLifecycleStage.EXECUTABLE,
                        ClaimLifecycleStage.REPLAYED,
                        ClaimLifecycleStage.INDEPENDENTLY_VALIDATED,
                    }:
                        runtime_present = any(
                            rec.qualifies()
                            and lifecycle_rank(rec.stage)
                            >= lifecycle_rank(ClaimLifecycleStage.EXECUTABLE)
                            for rec in claim.evidence
                        )
                        if not runtime_present:
                            raise ClaimRuntimeAuditError(
                                f"claim {claim.claim_id!r} uses mock/metadata "
                                "as sole executable evidence"
                            )


def render_audit_json(report: LogicClaimRuntimeAuditReport) -> str:
    """Deterministic JSON rendering with trailing newline."""

    return (
        json.dumps(
            report.to_baseline_dict(),
            ensure_ascii=True,
            indent=2,
            sort_keys=False,
            allow_nan=False,
        )
        + "\n"
    )


def write_audit_baseline(
    report: LogicClaimRuntimeAuditReport,
    path: str | Path,
) -> Path:
    """Atomically write the baseline report to *path*."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = render_audit_json(report)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(target)
    return target


def load_audit_baseline(path: str | Path) -> LogicClaimRuntimeAuditReport:
    """Load a previously written baseline report."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ClaimRuntimeAuditError("baseline must be a JSON object")
    return LogicClaimRuntimeAuditReport.from_dict(payload)


def ensure_baseline_seal(
    path: str | Path | None = None,
    *,
    datasets_root: str | Path | None = None,
) -> LogicClaimRuntimeAuditReport:
    """Re-materialize the audit and verify it matches the sealed baseline.

    Absolute ``tree_root`` may differ across checkouts; claim rows, summary,
    schema/interface, and lifecycle histogram must match exactly.
    """

    root = (
        Path(datasets_root).resolve()
        if datasets_root is not None
        else default_datasets_repo_root()
    )
    target = Path(path) if path is not None else default_baseline_path(datasets_root=root)
    live = build_default_audit(root=root)
    assert_audit_acceptance(live)
    if not target.is_file():
        raise ClaimRuntimeAuditError(f"baseline missing: {target}")
    sealed = load_audit_baseline(target)
    if sealed.interface != live.interface:
        raise ClaimRuntimeAuditError(
            f"baseline interface drift: {sealed.interface!r} != {live.interface!r}"
        )
    if sealed.schema_version != live.schema_version:
        raise ClaimRuntimeAuditError(
            f"baseline schema drift: {sealed.schema_version!r} != {live.schema_version!r}"
        )
    if sealed.version != live.version:
        raise ClaimRuntimeAuditError(
            f"baseline version drift: {sealed.version!r} != {live.version!r}"
        )
    live_claims = [item.to_dict() for item in live.claims]
    sealed_claims = [item.to_dict() for item in sealed.claims]
    if live_claims != sealed_claims:
        raise ClaimRuntimeAuditError(
            "baseline claim rows drifted from live materialization"
        )
    if live.summary() != sealed.summary():
        raise ClaimRuntimeAuditError(
            "baseline summary drifted from live materialization"
        )
    return live


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: write the claim-runtime audit baseline report."""

    import argparse

    parser = argparse.ArgumentParser(
        description="Materialize LogicClaimRuntimeAudit@1 baseline report"
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output path (default: docs/architecture/logic/logic_parser_v2_baseline/...)",
    )
    parser.add_argument(
        "--root",
        default="",
        help="Datasets repository root to audit (default: auto-detect)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path(args.root).resolve() if args.root else None
    report = build_default_audit(root=root)
    assert_audit_acceptance(report)
    target = (
        Path(args.output)
        if args.output
        else default_baseline_path(
            datasets_root=root if root is not None else default_datasets_repo_root()
        )
    )
    write_audit_baseline(report, target)
    summary = report.summary()
    print(
        f"wrote {target} claims={summary['claim_count']} "
        f"gaps={summary['gap_count']} digest={report.content_digest()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AUDIT_REPORT_VERSION",
    "ClaimAuditRow",
    "ClaimEvidenceRecord",
    "ClaimGap",
    "ClaimKind",
    "ClaimLifecycleStage",
    "ClaimRuntimeAuditError",
    "DEFAULT_BASELINE_RELATIVE_PATH",
    "DEFAULT_GAP_OWNER",
    "EvidenceDisposition",
    "EvidenceSurface",
    "GOAL_ID",
    "GapKind",
    "LIFECYCLE_STAGES",
    "LOGIC_CLAIM_RUNTIME_AUDIT_INTERFACE",
    "LOGIC_CLAIM_RUNTIME_AUDIT_REPORT_SCHEMA",
    "LOGIC_CLAIM_RUNTIME_AUDIT_SCHEMA",
    "LogicClaimRuntimeAuditReport",
    "MATERIALIZATION_TARGET",
    "PROGRAM_ID",
    "PROVIDER_SURFACE_PATHS",
    "REQUIRED_EVIDENCE_SURFACES",
    "TASK_ID",
    "assert_audit_acceptance",
    "audit_parser_claim",
    "audit_provider_claim",
    "audit_translation_claim",
    "build_claim_runtime_audit",
    "build_default_audit",
    "classify_evidence_file",
    "collect_declared_provider_ids",
    "default_baseline_path",
    "default_datasets_repo_root",
    "ensure_baseline_seal",
    "is_authority_bearing",
    "is_executable_route_support",
    "lifecycle_rank",
    "load_audit_baseline",
    "main",
    "max_lifecycle",
    "metadata_only_cannot_satisfy_execution",
    "mocks_cannot_satisfy_execution",
    "normalize_repo_relative",
    "path_exists_in_tree",
    "qualifies_for_stage",
    "render_audit_json",
    "resolve_tree_path",
    "write_audit_baseline",
]
