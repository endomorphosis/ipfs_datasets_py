"""Legacy TDFOL, CEC/DCEC, legal, and modal importer into the common kernel.

Interfaces:

* ``LegacyLogicImporter@1`` — admit legacy ASTs/text with explicit profile,
  ambiguity, loss, and source-map receipts before kernel entry
* ``TDFOLProfile@1`` — temporal-deontic first-order profile choices
* ``DCECProfile@1`` — deontic cognitive event-calculus profile choices

Key guarantees (vs legacy silent drops):

* unknown characters and undeclared sorts **fail closed** (no longer disappear)
* implication is **right-associative** and the choice is recorded on receipts
* ``O``/``P``/``F`` single-letter ambiguity is **explicit** (profile-gated)
* substitutions into kernel ASTs are **capture-safe**
* legacy golden vectors remain **traceable** via stable vector ids + digests

This module does **not** delete or wholesale rewrite legacy TDFOL/CEC parsers;
it wraps and lowers their surface forms into ``LogicNode`` with receipts.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.parsers.event_calculus import (
    EVENT_CALCULUS_FAMILY_ID,
    EventCalculusProfile,
    EventCalculusSyntax,
    parse_event_calculus,
    profile_event_calculus_classical,
    profile_event_calculus_cognitive,
)
from ipfs_datasets_py.logic.parsers.modal import (
    MODAL_FAMILY_ID,
    ModalSemanticsProfile,
    ModalSyntax,
    parse_modal,
    profile_deontic,
    profile_k,
)
from ipfs_datasets_py.logic.syntax_core.algebra import (
    alpha_equivalent,
    free_variables,
    substitute,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    Binder,
    LogicNode,
    NodeKind,
    TypedExpression,
    mk_and,
    mk_application,
    mk_constant,
    mk_exists,
    mk_extension,
    mk_false,
    mk_forall,
    mk_iff,
    mk_implies,
    mk_not,
    mk_or,
    mk_predicate,
    mk_true,
    mk_variable,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    DiagnosticSeverity,
    ParseLimits,
    ParseMode,
    ParseStatus,
    SourceDocument,
    SourceRange,
    SyntaxContractError,
    SyntaxDiagnostic,
    content_sha256,
    canonical_json_bytes,
)
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    atomic_sort,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LEGACY_LOGIC_IMPORTER_INTERFACE: Final = "LegacyLogicImporter@1"
TDFOL_PROFILE_INTERFACE: Final = "TDFOLProfile@1"
DCEC_PROFILE_INTERFACE: Final = "DCECProfile@1"
LEGACY_MODULE_VERSION: Final = "1.0.0"
LEGACY_IMPORT_RECEIPT_SCHEMA: Final = "legacy.import-receipt/v1"
LEGACY_AMBIGUITY_SCHEMA: Final = "legacy.ambiguity/v1"
LEGACY_LOSS_SCHEMA: Final = "legacy.loss/v1"
LEGACY_SOURCE_MAP_SCHEMA: Final = "legacy.source-map/v1"
LEGACY_GOLDEN_TRACE_SCHEMA: Final = "legacy.golden-vector/v1"
TDFOL_PROFILE_SCHEMA_VERSION: Final = "tdfol-profile/v1"
DCEC_PROFILE_SCHEMA_VERSION: Final = "dcec-profile/v1"
TDFOL_FAMILY_ID: Final = "tdfol"
DCEC_FAMILY_ID: Final = "dcec"
LEGAL_FAMILY_ID: Final = "legal_deontic"

# Diagnostic codes.
CODE_UNKNOWN_CHARACTER: Final = "legacy.unknown_character"
CODE_UNKNOWN_SORT: Final = "legacy.unknown_sort"
CODE_OPF_AMBIGUITY: Final = "legacy.opf_ambiguity"
CODE_PROFILE_REQUIRED: Final = "legacy.profile_required"
CODE_UNSUPPORTED_SURFACE: Final = "legacy.unsupported_surface"
CODE_CAPTURE: Final = "legacy.capture_violation"
CODE_IMPLIES_ASSOC: Final = "legacy.implication_associativity"
CODE_LOSS: Final = "legacy.semantic_loss"
CODE_EMPTY_INPUT: Final = "legacy.empty_input"
CODE_PARSE_FAILED: Final = "legacy.parse_failed"
CODE_GOLDEN_MISMATCH: Final = "legacy.golden_vector_mismatch"

_DEONTIC_LETTERS: Final[frozenset[str]] = frozenset({"O", "P", "F"})
_TEMPORAL_LETTERS: Final[frozenset[str]] = frozenset(
    {"X", "F", "G", "U", "R", "W", "H", "Y"}
)

# Known TDFOL / DCEC sorts (undeclared ones fail closed).
_TDFOL_SORTS: Final[frozenset[str]] = frozenset(
    {
        "agent",
        "action",
        "event",
        "time",
        "proposition",
        "object",
        "state",
        "condition",
        "fluent",
    }
)

# Built-in golden vectors: stable id → surface text + expected digest seed.
# These keep legacy conformance cases traceable without bulk golden dumps.
_BUILTIN_GOLDEN_VECTORS: Final[tuple[dict[str, Any], ...]] = (
    {
        "vector_id": "legacy:tdfol:obligation_simple",
        "family": "tdfol",
        "surface": "O(report)",
        "notes": "monadic deontic obligation",
    },
    {
        "vector_id": "legacy:tdfol:permission_simple",
        "family": "tdfol",
        "surface": "P(disclose)",
        "notes": "monadic deontic permission",
    },
    {
        "vector_id": "legacy:tdfol:prohibition_simple",
        "family": "tdfol",
        "surface": "F(dump_waste)",
        "notes": "monadic deontic prohibition",
    },
    {
        "vector_id": "legacy:tdfol:implies_right_assoc",
        "family": "tdfol",
        "surface": "p -> q -> r",
        "notes": "right-associative implication",
    },
    {
        "vector_id": "legacy:tdfol:forall_obligation",
        "family": "tdfol",
        "surface": "forall x:Agent. Person(x) -> O(Report(x))",
        "notes": "quantified deontic with sort",
    },
    {
        "vector_id": "legacy:dcec:happens_holds",
        "family": "dcec",
        "surface": "happens(turn_on, 1) and holds_at(light_on, 2)",
        "notes": "CEC event/fluent atoms",
    },
    {
        "vector_id": "legacy:dcec:initiates",
        "family": "dcec",
        "surface": "initiates(turn_on, light_on, t)",
        "notes": "initiation axiom",
    },
    {
        "vector_id": "legacy:dcec:sexpr_and",
        "family": "dcec",
        "surface": "(and P Q)",
        "notes": "DCEC s-expression conjunction",
    },
    {
        "vector_id": "legacy:dcec:sexpr_obligation",
        "family": "dcec",
        "surface": "(O report)",
        "notes": "DCEC s-expression obligation",
    },
    {
        "vector_id": "legacy:modal:box_diamond",
        "family": "modal",
        "surface": "box p implies diamond p",
        "notes": "alethic K fragment",
    },
    {
        "vector_id": "legacy:legal:shall_obligation",
        "family": "legal",
        "surface": "obligated file_report",
        "notes": "legal monadic obligation surface",
    },
)


class LegacyFamilyKind(str, Enum):
    """Declared legacy source family for import."""

    TDFOL = "tdfol"
    DCEC = "dcec"
    CEC = "cec"
    MODAL = "modal"
    LEGAL = "legal"
    EVENT_CALCULUS = "event_calculus"
    AUTO = "auto"


class ImplicationAssociativity(str, Enum):
    """Explicit implication associativity (only right is admitted)."""

    RIGHT = "right"


class OPFResolution(str, Enum):
    """How classic O/P/F letters are resolved under a profile."""

    DEONTIC = "deontic"
    REJECT = "reject"
    # Temporal F is never silently preferred over deontic F.


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TDFOLProfile:
    """Temporal-deontic first-order import profile.

    Interface: ``TDFOLProfile@1``.
    """

    profile_id: str = "tdfol_default"
    admit_classic_opf: bool = True
    admit_temporal_letters: bool = False
    known_sorts: tuple[str, ...] = tuple(sorted(_TDFOL_SORTS))
    implication_associativity: str = ImplicationAssociativity.RIGHT.value
    opf_resolution: str = OPFResolution.DEONTIC.value
    schema_version: str = TDFOL_PROFILE_SCHEMA_VERSION

    interface: ClassVar[str] = TDFOL_PROFILE_INTERFACE

    def __post_init__(self) -> None:
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError("TDFOLProfile.profile_id is required")
        if self.implication_associativity != ImplicationAssociativity.RIGHT.value:
            raise SyntaxContractError(
                "TDFOLProfile.implication_associativity must be 'right'; "
                "left-assoc legacy behaviour is rejected as silent ambiguity"
            )
        try:
            OPFResolution(self.opf_resolution)
        except ValueError as error:
            raise SyntaxContractError(
                f"unknown opf_resolution {self.opf_resolution!r}"
            ) from error
        sorts = tuple(str(s).casefold() for s in self.known_sorts)
        object.__setattr__(self, "known_sorts", sorts)
        if self.schema_version != TDFOL_PROFILE_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported TDFOLProfile schema_version {self.schema_version!r}"
            )

    @property
    def family_id(self) -> str:
        return TDFOL_FAMILY_ID

    def resolve_sort(self, name: str) -> str | None:
        key = name.casefold()
        if key in self.known_sorts:
            return key
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "admit_classic_opf": self.admit_classic_opf,
            "admit_temporal_letters": self.admit_temporal_letters,
            "implication_associativity": self.implication_associativity,
            "interface": self.interface,
            "known_sorts": list(self.known_sorts),
            "opf_resolution": self.opf_resolution,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TDFOLProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("TDFOLProfile must be a mapping")
        return cls(
            profile_id=str(value.get("profile_id") or "tdfol_default"),
            admit_classic_opf=bool(value.get("admit_classic_opf", True)),
            admit_temporal_letters=bool(value.get("admit_temporal_letters", False)),
            known_sorts=tuple(value.get("known_sorts") or sorted(_TDFOL_SORTS)),
            implication_associativity=str(
                value.get("implication_associativity")
                or ImplicationAssociativity.RIGHT.value
            ),
            opf_resolution=str(
                value.get("opf_resolution") or OPFResolution.DEONTIC.value
            ),
            schema_version=str(
                value.get("schema_version") or TDFOL_PROFILE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class DCECProfile:
    """Deontic cognitive event-calculus import profile.

    Interface: ``DCECProfile@1``.
    """

    profile_id: str = "dcec_default"
    admit_classic_opf: bool = True
    admit_event_calculus: bool = True
    admit_sexpr: bool = True
    admit_cognitive: bool = True
    known_sorts: tuple[str, ...] = (
        "agent",
        "action",
        "event",
        "time",
        "fluent",
        "object",
    )
    implication_associativity: str = ImplicationAssociativity.RIGHT.value
    opf_resolution: str = OPFResolution.DEONTIC.value
    schema_version: str = DCEC_PROFILE_SCHEMA_VERSION

    interface: ClassVar[str] = DCEC_PROFILE_INTERFACE

    def __post_init__(self) -> None:
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError("DCECProfile.profile_id is required")
        if self.implication_associativity != ImplicationAssociativity.RIGHT.value:
            raise SyntaxContractError(
                "DCECProfile.implication_associativity must be 'right'"
            )
        try:
            OPFResolution(self.opf_resolution)
        except ValueError as error:
            raise SyntaxContractError(
                f"unknown opf_resolution {self.opf_resolution!r}"
            ) from error
        sorts = tuple(str(s).casefold() for s in self.known_sorts)
        object.__setattr__(self, "known_sorts", sorts)
        if self.schema_version != DCEC_PROFILE_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported DCECProfile schema_version {self.schema_version!r}"
            )

    @property
    def family_id(self) -> str:
        return DCEC_FAMILY_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "admit_classic_opf": self.admit_classic_opf,
            "admit_cognitive": self.admit_cognitive,
            "admit_event_calculus": self.admit_event_calculus,
            "admit_sexpr": self.admit_sexpr,
            "implication_associativity": self.implication_associativity,
            "interface": self.interface,
            "known_sorts": list(self.known_sorts),
            "opf_resolution": self.opf_resolution,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DCECProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("DCECProfile must be a mapping")
        return cls(
            profile_id=str(value.get("profile_id") or "dcec_default"),
            admit_classic_opf=bool(value.get("admit_classic_opf", True)),
            admit_event_calculus=bool(value.get("admit_event_calculus", True)),
            admit_sexpr=bool(value.get("admit_sexpr", True)),
            admit_cognitive=bool(value.get("admit_cognitive", True)),
            known_sorts=tuple(
                value.get("known_sorts")
                or ("agent", "action", "event", "time", "fluent", "object")
            ),
            implication_associativity=str(
                value.get("implication_associativity")
                or ImplicationAssociativity.RIGHT.value
            ),
            opf_resolution=str(
                value.get("opf_resolution") or OPFResolution.DEONTIC.value
            ),
            schema_version=str(
                value.get("schema_version") or DCEC_PROFILE_SCHEMA_VERSION
            ),
        )


def profile_tdfol(
    *,
    profile_id: str = "tdfol_default",
    admit_classic_opf: bool = True,
) -> TDFOLProfile:
    return TDFOLProfile(
        profile_id=profile_id,
        admit_classic_opf=admit_classic_opf,
        opf_resolution=(
            OPFResolution.DEONTIC.value
            if admit_classic_opf
            else OPFResolution.REJECT.value
        ),
    )


def profile_dcec(
    *,
    profile_id: str = "dcec_default",
    admit_classic_opf: bool = True,
) -> DCECProfile:
    return DCECProfile(
        profile_id=profile_id,
        admit_classic_opf=admit_classic_opf,
        opf_resolution=(
            OPFResolution.DEONTIC.value
            if admit_classic_opf
            else OPFResolution.REJECT.value
        ),
    )


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AmbiguityRecord:
    """One explicit ambiguity encountered during legacy import."""

    code: str
    message: str
    span: tuple[int, int]
    candidates: tuple[str, ...]
    resolution: str
    schema_version: str = LEGACY_AMBIGUITY_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": list(self.candidates),
            "code": self.code,
            "message": self.message,
            "resolution": self.resolution,
            "schema_version": self.schema_version,
            "span": list(self.span),
        }


@dataclass(frozen=True, slots=True)
class LossRecord:
    """One explicit semantic loss (never silent)."""

    code: str
    message: str
    construct: str
    recoverable: bool = False
    schema_version: str = LEGACY_LOSS_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "construct": self.construct,
            "message": self.message,
            "recoverable": self.recoverable,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class SourceMapEntry:
    """Source-map span from legacy surface to kernel node id."""

    node_id: str
    start: int
    end: int
    surface: str
    schema_version: str = LEGACY_SOURCE_MAP_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "end": self.end,
            "node_id": self.node_id,
            "schema_version": self.schema_version,
            "start": self.start,
            "surface": self.surface,
        }


@dataclass(frozen=True, slots=True)
class GoldenVectorTrace:
    """Traceability record for a legacy golden vector."""

    vector_id: str
    surface_sha256: str
    family: str
    matched: bool
    notes: str = ""
    schema_version: str = LEGACY_GOLDEN_TRACE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "matched": self.matched,
            "notes": self.notes,
            "schema_version": self.schema_version,
            "surface_sha256": self.surface_sha256,
            "vector_id": self.vector_id,
        }


@dataclass(frozen=True, slots=True)
class LegacyImportReceipt:
    """Full receipt attached to every successful or failed legacy import.

    Interface fragment: ``legacy.import-receipt/v1``.
    """

    receipt_id: str
    family: str
    profile: Mapping[str, Any]
    status: str
    implication_associativity: str
    ambiguities: tuple[AmbiguityRecord, ...] = ()
    losses: tuple[LossRecord, ...] = ()
    source_map: tuple[SourceMapEntry, ...] = ()
    golden_traces: tuple[GoldenVectorTrace, ...] = ()
    surface_sha256: str = ""
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    schema_version: str = LEGACY_IMPORT_RECEIPT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguities": [item.to_dict() for item in self.ambiguities],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "family": self.family,
            "golden_traces": [item.to_dict() for item in self.golden_traces],
            "implication_associativity": self.implication_associativity,
            "losses": [item.to_dict() for item in self.losses],
            "profile": dict(self.profile),
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "source_map": [item.to_dict() for item in self.source_map],
            "status": self.status,
            "surface_sha256": self.surface_sha256,
        }


@dataclass(frozen=True, slots=True)
class LegacyImportResult:
    """Result of a legacy import attempt into the common kernel."""

    status: ParseStatus
    root: LogicNode | None = None
    expression: TypedExpression | None = None
    receipt: LegacyImportReceipt | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    printed: str = ""

    interface: ClassVar[str] = LEGACY_LOGIC_IMPORTER_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.root is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)


class LegacyImportError(SyntaxContractError):
    """Raised when a legacy import fails closed."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        result: LegacyImportResult | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = tuple(diagnostics)
        self.result = result


# ---------------------------------------------------------------------------
# Surface detection / scanning
# ---------------------------------------------------------------------------


_EC_ATOM_RE = re.compile(
    r"\b(happens|holds_at|holds|initiates|terminates|releases|clipped|"
    r"initially|released_at)\s*\(",
    re.IGNORECASE,
)
_SEXPR_RE = re.compile(r"^\s*\(")
_OPF_LETTER_RE = re.compile(r"(?<![A-Za-z_])([OPF])(?![A-Za-z0-9_])")
_SORT_ANNOT_RE = re.compile(r":\s*([A-Za-z_][A-Za-z0-9_]*)")
_UNKNOWN_CHAR_RE = re.compile(
    r"[^\x09\x0a\x0d\x20-\x7e"
    r"∀∃∧∨¬→↔⇒⇔□◇◊⊤⊥]"
)


def _surface_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def detect_legacy_family(text: str) -> LegacyFamilyKind:
    """Heuristic family detection for auto-import (explicit on receipt)."""

    stripped = text.strip()
    if not stripped:
        return LegacyFamilyKind.AUTO
    if _EC_ATOM_RE.search(stripped):
        return LegacyFamilyKind.EVENT_CALCULUS
    if _SEXPR_RE.match(stripped) and (
        stripped.lower().startswith("(and")
        or stripped.lower().startswith("(or")
        or stripped.lower().startswith("(not")
        or re.match(r"^\(\s*[OPF]\b", stripped)
        or stripped.lower().startswith("(knows")
        or stripped.lower().startswith("(believes")
    ):
        return LegacyFamilyKind.DCEC
    if re.search(r"\b(box|diamond|necessary|possible)\b", stripped, re.I):
        return LegacyFamilyKind.MODAL
    if re.search(r"\b(obligated|permitted|forbidden)\b", stripped, re.I):
        return LegacyFamilyKind.LEGAL
    if re.search(r"\b(forall|exists|O\(|P\(|F\()", stripped) or "∀" in stripped:
        return LegacyFamilyKind.TDFOL
    if any(ch in stripped for ch in "OPF") and "(" in stripped:
        return LegacyFamilyKind.TDFOL
    return LegacyFamilyKind.TDFOL


def scan_unknown_characters(text: str) -> list[tuple[int, str]]:
    """Return (offset, char) for characters that must not disappear."""

    found: list[tuple[int, str]] = []
    for match in _UNKNOWN_CHAR_RE.finditer(text):
        found.append((match.start(), match.group(0)))
    return found


def scan_opf_occurrences(text: str) -> list[tuple[int, str]]:
    return [(m.start(), m.group(1)) for m in _OPF_LETTER_RE.finditer(text)]


def scan_sort_annotations(text: str) -> list[tuple[int, str]]:
    return [(m.start(1), m.group(1)) for m in _SORT_ANNOT_RE.finditer(text)]


def list_builtin_golden_vectors() -> tuple[dict[str, Any], ...]:
    """Return the built-in legacy golden vector catalog (traceable ids)."""

    return _BUILTIN_GOLDEN_VECTORS


def match_golden_vector(text: str) -> GoldenVectorTrace | None:
    """Match *text* against built-in golden vectors by surface equality."""

    digest = _surface_digest(text.strip())
    for item in _BUILTIN_GOLDEN_VECTORS:
        if item["surface"].strip() == text.strip():
            return GoldenVectorTrace(
                vector_id=str(item["vector_id"]),
                surface_sha256=digest,
                family=str(item["family"]),
                matched=True,
                notes=str(item.get("notes") or ""),
            )
    return GoldenVectorTrace(
        vector_id="legacy:unmatched",
        surface_sha256=digest,
        family="unknown",
        matched=False,
        notes="surface not in built-in golden catalog",
    )


# ---------------------------------------------------------------------------
# Lightweight TDFOL / DCEC surface parser (right-assoc, fail-closed)
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
    |(?P<op><=>|<->|==>|=>|->|<=>|&&|\|\||∀|∃|∧|∨|¬|→|↔|⇒|⇔|□|◇|◊|⊤|⊥)
    |(?P<punct>[(),.:])
    |(?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    |(?P<number>\d+)
    |(?P<other>.)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class _Tok:
    kind: str
    value: str
    start: int
    end: int


def _tokenize_legacy(text: str) -> list[_Tok]:
    tokens: list[_Tok] = []
    for match in _TOKEN_RE.finditer(text):
        if match.lastgroup == "ws":
            continue
        if match.lastgroup == "other":
            tokens.append(
                _Tok("unknown", match.group(0), match.start(), match.end())
            )
            continue
        kind = match.lastgroup or "ident"
        tokens.append(_Tok(kind, match.group(0), match.start(), match.end()))
    tokens.append(_Tok("eof", "", len(text), len(text)))
    return tokens


class _LegacyParseFail(Exception):
    def __init__(self, diagnostic: SyntaxDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def _ldiag(
    *,
    code: str,
    message: str,
    start: int,
    end: int,
    remediation: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> SyntaxDiagnostic:
    return SyntaxDiagnostic(
        diagnostic_id=f"diag:legacy:{code.replace('.', '-')}",
        code=code,
        message=message,
        severity=DiagnosticSeverity.ERROR,
        range=SourceRange(start=start, end=end, start_char=start, end_char=end),
        remediation=remediation,
        metadata=dict(metadata or {}),
    )


class _LegacySurfaceParser:
    """Right-associative TDFOL-ish surface parser used by the importer."""

    def __init__(
        self,
        text: str,
        *,
        known_sorts: Sequence[str],
        admit_classic_opf: bool,
        opf_resolution: str,
        family_id: str,
        profile_id: str,
    ) -> None:
        self.text = text
        self.tokens = _tokenize_legacy(text)
        self.index = 0
        self.known_sorts = {s.casefold() for s in known_sorts}
        self.admit_classic_opf = admit_classic_opf
        self.opf_resolution = opf_resolution
        self.family_id = family_id
        self.profile_id = profile_id
        self._counter = 0
        self._scope: list[str] = []
        self.ambiguities: list[AmbiguityRecord] = []
        self.source_map: list[SourceMapEntry] = []

    def _nid(self, prefix: str) -> str:
        self._counter += 1
        return f"legacy:{prefix}:{self._counter}"

    def _cur(self) -> _Tok:
        return self.tokens[self.index]

    def _advance(self) -> _Tok:
        tok = self._cur()
        if tok.kind != "eof":
            self.index += 1
        return tok

    def _match(self, *values: str) -> _Tok | None:
        tok = self._cur()
        if tok.value in values or tok.value.casefold() in {
            v.casefold() for v in values
        }:
            return self._advance()
        return None

    def parse(self) -> LogicNode:
        # Fail closed on unknown characters before structure parsing.
        for tok in self.tokens:
            if tok.kind == "unknown":
                raise _LegacyParseFail(
                    _ldiag(
                        code=CODE_UNKNOWN_CHARACTER,
                        message=(
                            f"unknown character {tok.value!r} at offset "
                            f"{tok.start}; unknown characters no longer disappear"
                        ),
                        start=tok.start,
                        end=tok.end,
                        remediation="Remove or replace the unknown character",
                        metadata={"character": tok.value, "offset": tok.start},
                    )
                )
        if self._cur().kind == "eof":
            raise _LegacyParseFail(
                _ldiag(
                    code=CODE_EMPTY_INPUT,
                    message="empty legacy input is rejected",
                    start=0,
                    end=0,
                )
            )
        # DCEC s-expression path.
        if self._cur().value == "(":
            node = self._parse_sexpr()
            if self._cur().kind != "eof":
                tok = self._cur()
                raise _LegacyParseFail(
                    _ldiag(
                        code=CODE_PARSE_FAILED,
                        message=f"trailing input at {tok.value!r}",
                        start=tok.start,
                        end=tok.end,
                    )
                )
            return node
        node = self._parse_iff()
        if self._cur().kind != "eof":
            tok = self._cur()
            raise _LegacyParseFail(
                _ldiag(
                    code=CODE_PARSE_FAILED,
                    message=f"trailing input at {tok.value!r}",
                    start=tok.start,
                    end=tok.end,
                )
            )
        return node

    def _parse_iff(self) -> LogicNode:
        left = self._parse_implies()
        while self._match("iff", "↔", "⇔", "<=>", "<->"):
            right = self._parse_implies()
            left = mk_iff(self._nid("iff"), left, right)
        return left

    def _parse_implies(self) -> LogicNode:
        # Right-associative (explicit; legacy left-assoc is rejected).
        left = self._parse_or()
        if self._match("implies", "→", "⇒", "=>", "->", "==>"):
            right = self._parse_implies()  # right-assoc recursion
            node = mk_implies(self._nid("imp"), left, right)
            return LogicNode(
                node_id=node.node_id,
                kind=node.kind,
                sort=BOOL_SORT,
                arguments=node.arguments,
                metadata={
                    "associativity": "right",
                    "schema_version": "legacy.implies/v1",
                },
            )
        return left

    def _parse_or(self) -> LogicNode:
        nodes = [self._parse_and()]
        while self._match("or", "∨", "||"):
            nodes.append(self._parse_and())
        if len(nodes) == 1:
            return nodes[0]
        return mk_or(self._nid("or"), *nodes)

    def _parse_and(self) -> LogicNode:
        nodes = [self._parse_unary()]
        while self._match("and", "∧", "&&", "&"):
            nodes.append(self._parse_unary())
        if len(nodes) == 1:
            return nodes[0]
        return mk_and(self._nid("and"), *nodes)

    def _parse_unary(self) -> LogicNode:
        if self._match("not", "¬", "~", "!"):
            return mk_not(self._nid("not"), self._parse_unary())
        if self._match("forall", "∀"):
            return self._parse_quant("forall")
        if self._match("exists", "∃"):
            return self._parse_quant("exists")
        # Classic O/P/F or multi-letter deontic / modal / EC.
        tok = self._cur()
        if tok.kind == "ident":
            name = tok.value
            # Classic single-letter deontic.
            if name in _DEONTIC_LETTERS:
                return self._parse_opf(name)
            # Multi-letter deontic / cognitive / EC keywords.
            if name.casefold() in {
                "obligated",
                "obligation",
                "permitted",
                "permission",
                "forbidden",
                "prohibition",
                "box",
                "diamond",
                "necessary",
                "possible",
                "knows",
                "believes",
                "intends",
                "happens",
                "holds_at",
                "holds",
                "initiates",
                "terminates",
                "releases",
                "clipped",
                "initially",
                "released_at",
            }:
                return self._parse_named_operator(name)
        return self._parse_atomic()

    def _parse_opf(self, letter: str) -> LogicNode:
        tok = self._advance()
        candidates = ["deontic"]
        if letter == "F":
            candidates.append("temporal_eventually")
        if not self.admit_classic_opf or self.opf_resolution == OPFResolution.REJECT.value:
            raise _LegacyParseFail(
                _ldiag(
                    code=CODE_OPF_AMBIGUITY,
                    message=(
                        f"classic letter {letter!r} is ambiguous "
                        f"(candidates={candidates}); profile rejects O/P/F "
                        "without multi-letter forms"
                    ),
                    start=tok.start,
                    end=tok.end,
                    remediation=(
                        "Use obligated/permitted/forbidden or enable "
                        "admit_classic_opf with deontic resolution"
                    ),
                    metadata={
                        "letter": letter,
                        "candidates": candidates,
                        "resolution": "reject",
                    },
                )
            )
        # Explicit ambiguity record even when resolved as deontic.
        self.ambiguities.append(
            AmbiguityRecord(
                code=CODE_OPF_AMBIGUITY,
                message=(
                    f"classic letter {letter!r} resolved as deontic "
                    f"(candidates={candidates})"
                ),
                span=(tok.start, tok.end),
                candidates=tuple(candidates),
                resolution="deontic",
            )
        )
        body = self._parse_unary()
        op_kind = {
            "O": "obligation",
            "P": "permission",
            "F": "forbidden",
        }[letter]
        node = mk_extension(
            self._nid(op_kind),
            family=self.family_id,
            profile=self.profile_id,
            features=(f"legacy.{op_kind}", "legacy.classic_letter"),
            payload_schema="legacy.deontic/v1",
            payload={
                "kind": op_kind,
                "letter": letter,
                "resolution": "deontic",
                "schema_version": "legacy.deontic/v1",
            },
            children=(body,),
            range=SourceRange(
                start=tok.start,
                end=body.range.end if body.range else tok.end,
                start_char=tok.start,
                end_char=body.range.end if body.range else tok.end,
            ),
        )
        self.source_map.append(
            SourceMapEntry(
                node_id=node.node_id,
                start=tok.start,
                end=tok.end,
                surface=letter,
            )
        )
        return node

    def _parse_named_operator(self, name: str) -> LogicNode:
        tok = self._advance()
        fold = name.casefold()
        # EC predicates with parenthesized args.
        if fold in {
            "happens",
            "holds_at",
            "holds",
            "initiates",
            "terminates",
            "releases",
            "clipped",
            "initially",
            "released_at",
        }:
            if not self._match("("):
                raise _LegacyParseFail(
                    _ldiag(
                        code=CODE_PARSE_FAILED,
                        message=f"expected '(' after {name}",
                        start=tok.start,
                        end=tok.end,
                    )
                )
            args: list[LogicNode] = []
            if self._cur().value != ")":
                args.append(self._parse_term())
                while self._match(","):
                    args.append(self._parse_term())
            end = self._match(")")
            if end is None:
                raise _LegacyParseFail(
                    _ldiag(
                        code=CODE_PARSE_FAILED,
                        message="unbalanced ')' in event-calculus atom",
                        start=tok.start,
                        end=tok.end,
                    )
                )
            canon = "holds_at" if fold == "holds" else fold
            return mk_extension(
                self._nid(canon),
                family=EVENT_CALCULUS_FAMILY_ID,
                profile=self.profile_id,
                features=(f"event_calculus.{canon}",),
                payload_schema="event_calculus.atom/v1",
                payload={
                    "kind": canon,
                    "schema_version": "event_calculus.atom/v1",
                },
                children=tuple(args),
                range=SourceRange(
                    start=tok.start,
                    end=end.end,
                    start_char=tok.start,
                    end_char=end.end,
                ),
            )

        # Unary modal/deontic words.
        body = self._parse_unary()
        op_map = {
            "obligated": "obligation",
            "obligation": "obligation",
            "permitted": "permission",
            "permission": "permission",
            "forbidden": "forbidden",
            "prohibition": "forbidden",
            "box": "box",
            "necessary": "box",
            "diamond": "diamond",
            "possible": "diamond",
            "knows": "knows",
            "believes": "believes",
            "intends": "intends",
        }
        kind = op_map.get(fold, fold)
        return mk_extension(
            self._nid(kind),
            family=self.family_id,
            profile=self.profile_id,
            features=(f"legacy.{kind}",),
            payload_schema="legacy.operator/v1",
            payload={
                "kind": kind,
                "schema_version": "legacy.operator/v1",
                "surface": name,
            },
            children=(body,),
        )

    def _parse_quant(self, quant: str) -> LogicNode:
        binders: list[Binder] = []
        names: list[str] = []
        while True:
            tok = self._cur()
            if tok.kind != "ident":
                raise _LegacyParseFail(
                    _ldiag(
                        code=CODE_PARSE_FAILED,
                        message=f"expected binder name; got {tok.value!r}",
                        start=tok.start,
                        end=tok.end,
                    )
                )
            name = self._advance().value
            if name in self._scope or name in names:
                raise _LegacyParseFail(
                    _ldiag(
                        code=CODE_CAPTURE,
                        message=(
                            f"variable {name!r} rebind rejected "
                            "(capture-unsafe)"
                        ),
                        start=tok.start,
                        end=tok.end,
                        metadata={"variable": name},
                    )
                )
            sort_name = "object"
            if self._match(":"):
                sort_tok = self._cur()
                if sort_tok.kind != "ident":
                    raise _LegacyParseFail(
                        _ldiag(
                            code=CODE_PARSE_FAILED,
                            message="expected sort name after ':'",
                            start=sort_tok.start,
                            end=sort_tok.end,
                        )
                    )
                sort_name = self._advance().value
                if sort_name.casefold() not in self.known_sorts:
                    raise _LegacyParseFail(
                        _ldiag(
                            code=CODE_UNKNOWN_SORT,
                            message=(
                                f"unknown sort {sort_name!r}; "
                                "undeclared sorts no longer disappear"
                            ),
                            start=sort_tok.start,
                            end=sort_tok.end,
                            remediation=(
                                f"Use a declared sort among "
                                f"{sorted(self.known_sorts)!r}"
                            ),
                            metadata={
                                "sort": sort_name,
                                "known_sorts": sorted(self.known_sorts),
                            },
                        )
                    )
            binders.append(
                Binder(name=name, sort=atomic_sort(sort_name.capitalize()))
            )
            names.append(name)
            if not self._match(","):
                break
        if not self._match("."):
            tok = self._cur()
            raise _LegacyParseFail(
                _ldiag(
                    code=CODE_PARSE_FAILED,
                    message="expected '.' after quantifier binders",
                    start=tok.start,
                    end=tok.end,
                )
            )
        for n in names:
            self._scope.append(n)
        try:
            body = self._parse_iff()
        finally:
            for _ in names:
                self._scope.pop()
        if quant == "forall":
            return mk_forall(self._nid("forall"), binders, body)
        return mk_exists(self._nid("exists"), binders, body)

    def _parse_atomic(self) -> LogicNode:
        tok = self._cur()
        if tok.value in {"true", "⊤"} or tok.value.casefold() == "true":
            self._advance()
            return mk_true(self._nid("true"))
        if tok.value in {"false", "⊥"} or tok.value.casefold() == "false":
            self._advance()
            return mk_false(self._nid("false"))
        if tok.value == "(":
            self._advance()
            # Could be s-expr or grouping.
            if self._cur().kind == "ident" and self._cur().value.casefold() in {
                "and",
                "or",
                "not",
                "implies",
                "iff",
                "o",
                "p",
                "f",
                "knows",
                "believes",
            }:
                # Rewind conceptually: we already consumed '(' — parse sexpr body.
                self.index -= 1
                return self._parse_sexpr()
            inner = self._parse_iff()
            if not self._match(")"):
                raise _LegacyParseFail(
                    _ldiag(
                        code=CODE_PARSE_FAILED,
                        message="unbalanced ')'",
                        start=tok.start,
                        end=tok.end,
                    )
                )
            return inner
        if tok.kind == "ident":
            name = self._advance().value
            if self._match("("):
                args: list[LogicNode] = []
                if self._cur().value != ")":
                    args.append(self._parse_term())
                    while self._match(","):
                        args.append(self._parse_term())
                if not self._match(")"):
                    raise _LegacyParseFail(
                        _ldiag(
                            code=CODE_PARSE_FAILED,
                            message="unbalanced ')' in predicate",
                            start=tok.start,
                            end=tok.end,
                        )
                    )
                return mk_predicate(self._nid("pred"), name, args)
            return mk_predicate(self._nid("prop"), name, ())
        raise _LegacyParseFail(
            _ldiag(
                code=CODE_PARSE_FAILED,
                message=f"unexpected token {tok.value!r}",
                start=tok.start,
                end=tok.end,
            )
        )

    def _parse_term(self) -> LogicNode:
        tok = self._cur()
        if tok.kind == "number":
            self._advance()
            # Symbol names cannot start with a digit; encode as n_<digits>.
            return LogicNode(
                node_id=self._nid("num"),
                kind=NodeKind.CONSTANT,
                symbol=f"n_{tok.value}",
                sort=atomic_sort("Time"),
                metadata={
                    "literal": tok.value,
                    "literal_kind": "integer",
                    "schema_version": "legacy.time_literal/v1",
                },
            )
        if tok.kind == "ident":
            name = self._advance().value
            if name in self._scope:
                return mk_variable(
                    self._nid("var"),
                    name,
                    atomic_sort("Object"),
                )
            if self._match("("):
                args: list[LogicNode] = []
                if self._cur().value != ")":
                    args.append(self._parse_term())
                    while self._match(","):
                        args.append(self._parse_term())
                if not self._match(")"):
                    raise _LegacyParseFail(
                        _ldiag(
                            code=CODE_PARSE_FAILED,
                            message="unbalanced ')' in term",
                            start=tok.start,
                            end=tok.end,
                        )
                    )
                return mk_application(
                    self._nid("fun"),
                    name,
                    args,
                    sort=atomic_sort("Object"),
                )
            return mk_constant(
                self._nid("const"),
                name,
                atomic_sort("Object"),
            )
        raise _LegacyParseFail(
            _ldiag(
                code=CODE_PARSE_FAILED,
                message=f"expected term; got {tok.value!r}",
                start=tok.start,
                end=tok.end,
            )
        )

    def _parse_sexpr(self) -> LogicNode:
        if not self._match("("):
            tok = self._cur()
            raise _LegacyParseFail(
                _ldiag(
                    code=CODE_PARSE_FAILED,
                    message="expected '(' for s-expression",
                    start=tok.start,
                    end=tok.end,
                )
            )
        head_tok = self._cur()
        if head_tok.kind not in {"ident", "op"}:
            raise _LegacyParseFail(
                _ldiag(
                    code=CODE_PARSE_FAILED,
                    message=f"expected s-expression head; got {head_tok.value!r}",
                    start=head_tok.start,
                    end=head_tok.end,
                )
            )
        head = self._advance().value
        head_fold = head.casefold()
        args: list[LogicNode] = []
        while self._cur().value != ")" and self._cur().kind != "eof":
            if self._cur().value == "(":
                args.append(self._parse_sexpr())
            elif self._cur().kind == "ident":
                # Peek: could be nested atom or bare.
                name = self._cur().value
                # Bare proposition / operator-as-atom.
                self._advance()
                args.append(mk_predicate(self._nid("atom"), name, ()))
            else:
                tok = self._cur()
                raise _LegacyParseFail(
                    _ldiag(
                        code=CODE_PARSE_FAILED,
                        message=f"unexpected s-expression atom {tok.value!r}",
                        start=tok.start,
                        end=tok.end,
                    )
                )
        if not self._match(")"):
            raise _LegacyParseFail(
                _ldiag(
                    code=CODE_PARSE_FAILED,
                    message="unbalanced ')' in s-expression",
                    start=head_tok.start,
                    end=head_tok.end,
                )
            )
        if head_fold == "and":
            if len(args) < 2:
                raise _LegacyParseFail(
                    _ldiag(
                        code=CODE_PARSE_FAILED,
                        message="'and' requires ≥2 arguments",
                        start=head_tok.start,
                        end=head_tok.end,
                    )
                )
            return mk_and(self._nid("and"), *args)
        if head_fold == "or":
            if len(args) < 2:
                raise _LegacyParseFail(
                    _ldiag(
                        code=CODE_PARSE_FAILED,
                        message="'or' requires ≥2 arguments",
                        start=head_tok.start,
                        end=head_tok.end,
                    )
                )
            return mk_or(self._nid("or"), *args)
        if head_fold == "not":
            if len(args) != 1:
                raise _LegacyParseFail(
                    _ldiag(
                        code=CODE_PARSE_FAILED,
                        message="'not' requires 1 argument",
                        start=head_tok.start,
                        end=head_tok.end,
                    )
                )
            return mk_not(self._nid("not"), args[0])
        if head_fold in {"implies", "->", "=>"}:
            if len(args) != 2:
                raise _LegacyParseFail(
                    _ldiag(
                        code=CODE_PARSE_FAILED,
                        message="'implies' requires 2 arguments",
                        start=head_tok.start,
                        end=head_tok.end,
                    )
                )
            return mk_implies(self._nid("imp"), args[0], args[1])
        if head in _DEONTIC_LETTERS or head_fold in {"o", "p", "f"}:
            letter = head.upper() if head.upper() in _DEONTIC_LETTERS else head
            if letter not in _DEONTIC_LETTERS:
                letter = head.upper()
            if len(args) != 1:
                raise _LegacyParseFail(
                    _ldiag(
                        code=CODE_PARSE_FAILED,
                        message=f"deontic {letter} requires 1 argument",
                        start=head_tok.start,
                        end=head_tok.end,
                    )
                )
            # Reuse OPF path semantics via extension.
            if not self.admit_classic_opf:
                raise _LegacyParseFail(
                    _ldiag(
                        code=CODE_OPF_AMBIGUITY,
                        message=f"classic letter {letter!r} rejected by profile",
                        start=head_tok.start,
                        end=head_tok.end,
                    )
                )
            self.ambiguities.append(
                AmbiguityRecord(
                    code=CODE_OPF_AMBIGUITY,
                    message=f"s-expression {letter!r} resolved as deontic",
                    span=(head_tok.start, head_tok.end),
                    candidates=("deontic",),
                    resolution="deontic",
                )
            )
            op_kind = {"O": "obligation", "P": "permission", "F": "forbidden"}[letter]
            return mk_extension(
                self._nid(op_kind),
                family=self.family_id,
                profile=self.profile_id,
                features=(f"legacy.{op_kind}", "legacy.sexpr"),
                payload_schema="legacy.deontic/v1",
                payload={
                    "kind": op_kind,
                    "letter": letter,
                    "resolution": "deontic",
                    "schema_version": "legacy.deontic/v1",
                },
                children=(args[0],),
            )
        # Generic application-as-predicate of args.
        if not args:
            return mk_predicate(self._nid("prop"), head, ())
        return mk_predicate(self._nid("pred"), head, args)


# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------


class LegacyLogicImporter:
    """Import legacy TDFOL / DCEC / legal / modal surfaces into the kernel.

    Interface: ``LegacyLogicImporter@1``.
    """

    interface: ClassVar[str] = LEGACY_LOGIC_IMPORTER_INTERFACE

    def __init__(
        self,
        *,
        tdfol: TDFOLProfile | None = None,
        dcec: DCECProfile | None = None,
        modal: ModalSemanticsProfile | None = None,
        event_calculus: EventCalculusProfile | None = None,
    ) -> None:
        self.tdfol = tdfol or profile_tdfol()
        self.dcec = dcec or profile_dcec()
        self.modal = modal or profile_k()
        self.event_calculus = event_calculus or profile_event_calculus_cognitive()
        self._receipt_seq = 0

    def _receipt_id(self) -> str:
        self._receipt_seq += 1
        return f"receipt:legacy:{self._receipt_seq}"

    def import_text(
        self,
        text: str,
        *,
        family: LegacyFamilyKind | str = LegacyFamilyKind.AUTO,
        document_id: str = "doc:legacy:1",
    ) -> LegacyImportResult:
        """Import *text* under *family* (or auto-detect) with full receipts."""

        if not isinstance(text, str):
            raise SyntaxContractError("import_text requires a string")
        fam = (
            family
            if isinstance(family, LegacyFamilyKind)
            else LegacyFamilyKind(str(family))
        )
        if fam is LegacyFamilyKind.AUTO:
            fam = detect_legacy_family(text)

        digest = _surface_digest(text)
        golden = match_golden_vector(text)
        golden_traces = (golden,) if golden is not None else ()

        # Unknown characters: fail closed, never drop.
        unknown = scan_unknown_characters(text)
        if unknown:
            diags = tuple(
                _ldiag(
                    code=CODE_UNKNOWN_CHARACTER,
                    message=(
                        f"unknown character {ch!r} at offset {off}; "
                        "unknown characters no longer disappear"
                    ),
                    start=off,
                    end=off + len(ch),
                    metadata={"character": ch, "offset": off},
                )
                for off, ch in unknown
            )
            receipt = LegacyImportReceipt(
                receipt_id=self._receipt_id(),
                family=fam.value,
                profile=self._profile_dict(fam),
                status="failed",
                implication_associativity="right",
                ambiguities=(),
                losses=(
                    LossRecord(
                        code=CODE_UNKNOWN_CHARACTER,
                        message="import aborted: unknown characters present",
                        construct="character",
                        recoverable=False,
                    ),
                ),
                source_map=(),
                golden_traces=golden_traces,
                surface_sha256=digest,
                diagnostics=diags,
            )
            return LegacyImportResult(
                status=ParseStatus.FAILED,
                receipt=receipt,
                diagnostics=diags,
            )

        # Route by family.
        try:
            if fam is LegacyFamilyKind.EVENT_CALCULUS or fam is LegacyFamilyKind.CEC:
                return self._import_event_calculus(text, fam, digest, golden_traces)
            if fam is LegacyFamilyKind.MODAL:
                return self._import_modal(text, digest, golden_traces)
            if fam is LegacyFamilyKind.LEGAL:
                return self._import_legal(text, digest, golden_traces)
            if fam is LegacyFamilyKind.DCEC:
                return self._import_dcec(text, digest, golden_traces)
            # TDFOL default.
            return self._import_tdfol(text, digest, golden_traces)
        except _LegacyParseFail as error:
            receipt = LegacyImportReceipt(
                receipt_id=self._receipt_id(),
                family=fam.value,
                profile=self._profile_dict(fam),
                status="failed",
                implication_associativity="right",
                golden_traces=golden_traces,
                surface_sha256=digest,
                diagnostics=(error.diagnostic,),
            )
            return LegacyImportResult(
                status=ParseStatus.FAILED,
                receipt=receipt,
                diagnostics=(error.diagnostic,),
            )

    def _profile_dict(self, fam: LegacyFamilyKind) -> dict[str, Any]:
        if fam is LegacyFamilyKind.DCEC:
            return self.dcec.to_dict()
        if fam is LegacyFamilyKind.EVENT_CALCULUS or fam is LegacyFamilyKind.CEC:
            return self.event_calculus.to_dict()
        if fam is LegacyFamilyKind.MODAL:
            return self.modal.to_dict()
        if fam is LegacyFamilyKind.LEGAL:
            return {
                "family": LEGAL_FAMILY_ID,
                "opf_resolution": "deontic",
                "profile_id": "legal_deontic_monadic",
            }
        return self.tdfol.to_dict()

    def _import_tdfol(
        self,
        text: str,
        digest: str,
        golden_traces: tuple[GoldenVectorTrace, ...],
    ) -> LegacyImportResult:
        # Pre-scan sorts.
        for off, sort_name in scan_sort_annotations(text):
            if self.tdfol.resolve_sort(sort_name) is None:
                diag = _ldiag(
                    code=CODE_UNKNOWN_SORT,
                    message=(
                        f"unknown sort {sort_name!r}; "
                        "undeclared sorts no longer disappear"
                    ),
                    start=off,
                    end=off + len(sort_name),
                    metadata={
                        "sort": sort_name,
                        "known_sorts": list(self.tdfol.known_sorts),
                    },
                )
                receipt = LegacyImportReceipt(
                    receipt_id=self._receipt_id(),
                    family=LegacyFamilyKind.TDFOL.value,
                    profile=self.tdfol.to_dict(),
                    status="failed",
                    implication_associativity="right",
                    golden_traces=golden_traces,
                    surface_sha256=digest,
                    diagnostics=(diag,),
                    losses=(
                        LossRecord(
                            code=CODE_UNKNOWN_SORT,
                            message=diag.message,
                            construct=f"sort:{sort_name}",
                        ),
                    ),
                )
                return LegacyImportResult(
                    status=ParseStatus.FAILED,
                    receipt=receipt,
                    diagnostics=(diag,),
                )

        parser = _LegacySurfaceParser(
            text,
            known_sorts=self.tdfol.known_sorts,
            admit_classic_opf=self.tdfol.admit_classic_opf,
            opf_resolution=self.tdfol.opf_resolution,
            family_id=TDFOL_FAMILY_ID,
            profile_id=self.tdfol.profile_id,
        )
        try:
            root = parser.parse()
        except _LegacyParseFail as error:
            receipt = LegacyImportReceipt(
                receipt_id=self._receipt_id(),
                family=LegacyFamilyKind.TDFOL.value,
                profile=self.tdfol.to_dict(),
                status="failed",
                implication_associativity="right",
                ambiguities=tuple(parser.ambiguities),
                source_map=tuple(parser.source_map),
                golden_traces=golden_traces,
                surface_sha256=digest,
                diagnostics=(error.diagnostic,),
            )
            return LegacyImportResult(
                status=ParseStatus.FAILED,
                receipt=receipt,
                diagnostics=(error.diagnostic,),
            )

        receipt = LegacyImportReceipt(
            receipt_id=self._receipt_id(),
            family=LegacyFamilyKind.TDFOL.value,
            profile=self.tdfol.to_dict(),
            status="ok",
            implication_associativity="right",
            ambiguities=tuple(parser.ambiguities),
            source_map=tuple(parser.source_map),
            golden_traces=golden_traces,
            surface_sha256=digest,
        )
        return LegacyImportResult(
            status=ParseStatus.OK,
            root=root,
            receipt=receipt,
            diagnostics=(),
        )

    def _import_dcec(
        self,
        text: str,
        digest: str,
        golden_traces: tuple[GoldenVectorTrace, ...],
    ) -> LegacyImportResult:
        # Prefer event-calculus frontend when EC atoms present.
        if self.dcec.admit_event_calculus and _EC_ATOM_RE.search(text):
            ec = parse_event_calculus(text, self.event_calculus)
            if ec.ok and ec.root is not None:
                receipt = LegacyImportReceipt(
                    receipt_id=self._receipt_id(),
                    family=LegacyFamilyKind.DCEC.value,
                    profile=self.dcec.to_dict(),
                    status="ok",
                    implication_associativity="right",
                    golden_traces=golden_traces,
                    surface_sha256=digest,
                    source_map=(
                        SourceMapEntry(
                            node_id=ec.root.node_id,
                            start=0,
                            end=len(text),
                            surface=text[:64],
                        ),
                    ),
                )
                return LegacyImportResult(
                    status=ParseStatus.OK,
                    root=ec.root,
                    expression=ec.expression,
                    receipt=receipt,
                    printed=ec.printed,
                )
            # Fall through to surface parser with EC diagnostics as losses.
        parser = _LegacySurfaceParser(
            text,
            known_sorts=self.dcec.known_sorts,
            admit_classic_opf=self.dcec.admit_classic_opf,
            opf_resolution=self.dcec.opf_resolution,
            family_id=DCEC_FAMILY_ID,
            profile_id=self.dcec.profile_id,
        )
        try:
            root = parser.parse()
        except _LegacyParseFail as error:
            receipt = LegacyImportReceipt(
                receipt_id=self._receipt_id(),
                family=LegacyFamilyKind.DCEC.value,
                profile=self.dcec.to_dict(),
                status="failed",
                implication_associativity="right",
                ambiguities=tuple(parser.ambiguities),
                golden_traces=golden_traces,
                surface_sha256=digest,
                diagnostics=(error.diagnostic,),
            )
            return LegacyImportResult(
                status=ParseStatus.FAILED,
                receipt=receipt,
                diagnostics=(error.diagnostic,),
            )
        receipt = LegacyImportReceipt(
            receipt_id=self._receipt_id(),
            family=LegacyFamilyKind.DCEC.value,
            profile=self.dcec.to_dict(),
            status="ok",
            implication_associativity="right",
            ambiguities=tuple(parser.ambiguities),
            source_map=tuple(parser.source_map),
            golden_traces=golden_traces,
            surface_sha256=digest,
        )
        return LegacyImportResult(
            status=ParseStatus.OK,
            root=root,
            receipt=receipt,
        )

    def _import_event_calculus(
        self,
        text: str,
        fam: LegacyFamilyKind,
        digest: str,
        golden_traces: tuple[GoldenVectorTrace, ...],
    ) -> LegacyImportResult:
        result = parse_event_calculus(text, self.event_calculus)
        if not result.ok or result.root is None:
            diags = result.diagnostics
            receipt = LegacyImportReceipt(
                receipt_id=self._receipt_id(),
                family=fam.value,
                profile=self.event_calculus.to_dict(),
                status="failed",
                implication_associativity="right",
                golden_traces=golden_traces,
                surface_sha256=digest,
                diagnostics=diags,
            )
            return LegacyImportResult(
                status=ParseStatus.FAILED,
                receipt=receipt,
                diagnostics=diags,
            )
        receipt = LegacyImportReceipt(
            receipt_id=self._receipt_id(),
            family=fam.value,
            profile=self.event_calculus.to_dict(),
            status="ok",
            implication_associativity="right",
            golden_traces=golden_traces,
            surface_sha256=digest,
            source_map=(
                SourceMapEntry(
                    node_id=result.root.node_id,
                    start=0,
                    end=len(text),
                    surface=text[:64],
                ),
            ),
        )
        return LegacyImportResult(
            status=ParseStatus.OK,
            root=result.root,
            expression=result.expression,
            receipt=receipt,
            printed=result.printed,
        )

    def _import_modal(
        self,
        text: str,
        digest: str,
        golden_traces: tuple[GoldenVectorTrace, ...],
    ) -> LegacyImportResult:
        result = parse_modal(text, self.modal)
        if not result.ok or result.root is None:
            receipt = LegacyImportReceipt(
                receipt_id=self._receipt_id(),
                family=LegacyFamilyKind.MODAL.value,
                profile=self.modal.to_dict(),
                status="failed",
                implication_associativity="right",
                golden_traces=golden_traces,
                surface_sha256=digest,
                diagnostics=result.diagnostics,
            )
            return LegacyImportResult(
                status=ParseStatus.FAILED,
                receipt=receipt,
                diagnostics=result.diagnostics,
            )
        receipt = LegacyImportReceipt(
            receipt_id=self._receipt_id(),
            family=LegacyFamilyKind.MODAL.value,
            profile=self.modal.to_dict(),
            status="ok",
            implication_associativity="right",
            golden_traces=golden_traces,
            surface_sha256=digest,
            source_map=(
                SourceMapEntry(
                    node_id=result.root.node_id,
                    start=0,
                    end=len(text),
                    surface=text[:64],
                ),
            ),
        )
        return LegacyImportResult(
            status=ParseStatus.OK,
            root=result.root,
            expression=result.expression,
            receipt=receipt,
            printed=result.printed,
        )

    def _import_legal(
        self,
        text: str,
        digest: str,
        golden_traces: tuple[GoldenVectorTrace, ...],
    ) -> LegacyImportResult:
        # Legal monadic deontic via modal deontic profile (multi-letter forms).
        deontic = profile_deontic(admit_classic_letters=False)
        result = parse_modal(text, deontic)
        if result.ok and result.root is not None:
            receipt = LegacyImportReceipt(
                receipt_id=self._receipt_id(),
                family=LegacyFamilyKind.LEGAL.value,
                profile=deontic.to_dict(),
                status="ok",
                implication_associativity="right",
                golden_traces=golden_traces,
                surface_sha256=digest,
            )
            return LegacyImportResult(
                status=ParseStatus.OK,
                root=result.root,
                expression=result.expression,
                receipt=receipt,
                printed=result.printed,
            )
        # Fall back to TDFOL-style surface with legal family id.
        parser = _LegacySurfaceParser(
            text,
            known_sorts=self.tdfol.known_sorts,
            admit_classic_opf=False,
            opf_resolution=OPFResolution.REJECT.value,
            family_id=LEGAL_FAMILY_ID,
            profile_id="legal_deontic_monadic",
        )
        try:
            root = parser.parse()
        except _LegacyParseFail as error:
            receipt = LegacyImportReceipt(
                receipt_id=self._receipt_id(),
                family=LegacyFamilyKind.LEGAL.value,
                profile={"profile_id": "legal_deontic_monadic"},
                status="failed",
                implication_associativity="right",
                golden_traces=golden_traces,
                surface_sha256=digest,
                diagnostics=(error.diagnostic,) + result.diagnostics,
            )
            return LegacyImportResult(
                status=ParseStatus.FAILED,
                receipt=receipt,
                diagnostics=(error.diagnostic,) + result.diagnostics,
            )
        receipt = LegacyImportReceipt(
            receipt_id=self._receipt_id(),
            family=LegacyFamilyKind.LEGAL.value,
            profile={"profile_id": "legal_deontic_monadic"},
            status="ok",
            implication_associativity="right",
            ambiguities=tuple(parser.ambiguities),
            source_map=tuple(parser.source_map),
            golden_traces=golden_traces,
            surface_sha256=digest,
        )
        return LegacyImportResult(
            status=ParseStatus.OK,
            root=root,
            receipt=receipt,
        )

    def substitute_capture_safe(
        self,
        node: LogicNode,
        var: str,
        replacement: LogicNode,
    ) -> LogicNode:
        """Capture-avoiding substitution for imported kernel ASTs."""

        return substitute(node, var, replacement)

    def import_or_raise(self, text: str, **kwargs: Any) -> LogicNode:
        result = self.import_text(text, **kwargs)
        if not result.ok or result.root is None:
            raise LegacyImportError(
                "legacy import failed",
                diagnostics=result.diagnostics,
                result=result,
            )
        return result.root


def import_legacy(
    text: str,
    *,
    family: LegacyFamilyKind | str = LegacyFamilyKind.AUTO,
    **kwargs: Any,
) -> LegacyImportResult:
    """Convenience: import legacy *text* through ``LegacyLogicImporter@1``."""

    importer = LegacyLogicImporter()
    return importer.import_text(text, family=family, **kwargs)


def import_legacy_tdfol(text: str, **kwargs: Any) -> LegacyImportResult:
    return import_legacy(text, family=LegacyFamilyKind.TDFOL, **kwargs)


def import_legacy_dcec(text: str, **kwargs: Any) -> LegacyImportResult:
    return import_legacy(text, family=LegacyFamilyKind.DCEC, **kwargs)


def capture_safe_substitute(
    node: LogicNode,
    var: str,
    replacement: LogicNode,
) -> LogicNode:
    return substitute(node, var, replacement)


def golden_vector_catalog() -> tuple[dict[str, Any], ...]:
    """Return built-in golden vectors with digests for traceability checks."""

    items: list[dict[str, Any]] = []
    for item in _BUILTIN_GOLDEN_VECTORS:
        entry = dict(item)
        entry["surface_sha256"] = _surface_digest(str(item["surface"]))
        entry["schema_version"] = LEGACY_GOLDEN_TRACE_SCHEMA
        items.append(entry)
    return tuple(items)


__all__ = [
    "LEGACY_LOGIC_IMPORTER_INTERFACE",
    "TDFOL_PROFILE_INTERFACE",
    "DCEC_PROFILE_INTERFACE",
    "LEGACY_MODULE_VERSION",
    "TDFOL_FAMILY_ID",
    "DCEC_FAMILY_ID",
    "LEGAL_FAMILY_ID",
    "CODE_UNKNOWN_CHARACTER",
    "CODE_UNKNOWN_SORT",
    "CODE_OPF_AMBIGUITY",
    "CODE_PROFILE_REQUIRED",
    "CODE_CAPTURE",
    "CODE_IMPLIES_ASSOC",
    "CODE_LOSS",
    "CODE_GOLDEN_MISMATCH",
    "LegacyFamilyKind",
    "ImplicationAssociativity",
    "OPFResolution",
    "TDFOLProfile",
    "DCECProfile",
    "AmbiguityRecord",
    "LossRecord",
    "SourceMapEntry",
    "GoldenVectorTrace",
    "LegacyImportReceipt",
    "LegacyImportResult",
    "LegacyImportError",
    "LegacyLogicImporter",
    "profile_tdfol",
    "profile_dcec",
    "detect_legacy_family",
    "scan_unknown_characters",
    "scan_opf_occurrences",
    "list_builtin_golden_vectors",
    "match_golden_vector",
    "golden_vector_catalog",
    "import_legacy",
    "import_legacy_tdfol",
    "import_legacy_dcec",
    "capture_safe_substitute",
    "free_variables",
    "alpha_equivalent",
]
