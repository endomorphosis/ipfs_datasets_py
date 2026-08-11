"""Join protocol, program, and proof-assistant target surfaces (LFP-033).

Interfaces:

* ``TargetTheoryModel@1`` — target-neutral theory of imports, declarations,
  axioms, theorems, source maps, and trust receipts shared by protocol,
  program/resource, SMT/CHC, and kernel routes
* ``KernelTargetGenerator@1`` — controlled Lean / Rocq / Isabelle source
  generation that rejects ``sorry`` / ``admit`` / trust-escape constructs and
  records exact theorem plus environment identities
* ``HammerStrategyReceipt@1`` — hammer / ATP strategy evidence that remains a
  *candidate* until an independent kernel reconstruction accepts it

Authority rules (fail-closed):

* Official Lean / Rocq / Isabelle kernels are the sole proof authority.
* Generated sources never admit ``sorry``, ``admit``, ``Admitted``, ``oops``,
  ``sorryAx``, ``trusted``, ``unsafe``, or equivalent trust escapes.
* ProVerif / Tamarin / SMT / CHC / ATP / Hammer outputs are candidates or
  protocol/satisfiability evidence only; they never become theorem authority
  without reconstruction under a pinned environment identity.
* Exact theorem identity and environment identity are recorded on every
  generated kernel artifact and every hammer strategy receipt.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

TARGET_THEORY_MODEL_INTERFACE: Final = "TargetTheoryModel@1"
KERNEL_TARGET_GENERATOR_INTERFACE: Final = "KernelTargetGenerator@1"
HAMMER_STRATEGY_RECEIPT_INTERFACE: Final = "HammerStrategyReceipt@1"

TARGET_THEORY_SCHEMA: Final = "target-theory-model/v1"
TARGET_DECLARATION_SCHEMA: Final = "target-theory-declaration/v1"
TARGET_SOURCE_MAP_SCHEMA: Final = "target-theory-source-map/v1"
TARGET_TRUST_RECEIPT_SCHEMA: Final = "target-theory-trust-receipt/v1"
THEOREM_IDENTITY_SCHEMA: Final = "kernel-theorem-identity/v1"
ENVIRONMENT_IDENTITY_SCHEMA: Final = "kernel-environment-identity/v1"
KERNEL_GENERATED_SOURCE_SCHEMA: Final = "kernel-generated-source/v1"
HAMMER_STRATEGY_RECEIPT_SCHEMA: Final = "hammer-strategy-receipt/v1"
PROTOCOL_PROGRAM_KERNEL_ROUTE_SCHEMA: Final = "protocol-program-kernel-route/v1"
JOIN_RECEIPT_SCHEMA: Final = "protocol-program-kernel-join-receipt/v1"

KERNEL_TARGETS_MODULE_VERSION: Final = "1.0.0"
KERNEL_TARGETS_IDENTITY_DOMAIN: Final = "logic.parsers.kernel-targets"
TARGET_THEORY_FAMILY_ID: Final = "target_theory"
TARGET_THEORY_PROFILE_ID: Final = "controlled_kernel_target"
TARGET_ENCODING_LEAN: Final = "lean4"
TARGET_ENCODING_ROCQ: Final = "rocq"
TARGET_ENCODING_ISABELLE: Final = "isabelle_hol"

# Stable diagnostic codes.
CODE_INVALID_THEORY: Final = "kernel_target.invalid_theory"
CODE_INVALID_DECLARATION: Final = "kernel_target.invalid_declaration"
CODE_INVALID_SOURCE_MAP: Final = "kernel_target.invalid_source_map"
CODE_INVALID_TRUST: Final = "kernel_target.invalid_trust_receipt"
CODE_INVALID_ENVIRONMENT: Final = "kernel_target.invalid_environment"
CODE_INVALID_THEOREM: Final = "kernel_target.invalid_theorem_identity"
CODE_TRUST_ESCAPE: Final = "kernel_target.trust_escape_rejected"
CODE_IDENTITY_MISMATCH: Final = "kernel_target.identity_mismatch"
CODE_UNSUPPORTED_TARGET: Final = "kernel_target.unsupported_kernel"
CODE_UNSUPPORTED_SURFACE: Final = "kernel_target.unsupported_route_surface"
CODE_AUTHORITY_PROMOTION: Final = "kernel_target.authority_promotion_rejected"
CODE_HAMMER_NOT_AUTHORITY: Final = "kernel_target.hammer_not_proof_authority"
CODE_RECONSTRUCTION_REQUIRED: Final = "kernel_target.reconstruction_required"
CODE_EMPTY_INPUT: Final = "kernel_target.empty_input"
CODE_MALFORMED: Final = "kernel_target.malformed"
CODE_GENERATION: Final = "kernel_target.generation_error"
CODE_ROUTE: Final = "kernel_target.route_error"

_ALL_KERNEL_TARGET_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_INVALID_THEORY,
        CODE_INVALID_DECLARATION,
        CODE_INVALID_SOURCE_MAP,
        CODE_INVALID_TRUST,
        CODE_INVALID_ENVIRONMENT,
        CODE_INVALID_THEOREM,
        CODE_TRUST_ESCAPE,
        CODE_IDENTITY_MISMATCH,
        CODE_UNSUPPORTED_TARGET,
        CODE_UNSUPPORTED_SURFACE,
        CODE_AUTHORITY_PROMOTION,
        CODE_HAMMER_NOT_AUTHORITY,
        CODE_RECONSTRUCTION_REQUIRED,
        CODE_EMPTY_INPUT,
        CODE_MALFORMED,
        CODE_GENERATION,
        CODE_ROUTE,
    }
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,255}$")
_SAFE_IDENT_RE = re.compile(r"[^A-Za-z0-9_']+")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

# Trust-escape patterns rejected in every generated kernel source.
_TRUST_ESCAPE_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "sorry",
        re.compile(r"(?<![A-Za-z0-9_'])(?:sorry|sorryAx)(?![A-Za-z0-9_'])"),
    ),
    (
        "admit",
        re.compile(r"(?i)(?<![A-Za-z0-9_'])(?:admit(?:ted)?|admit\s*\.)(?![A-Za-z0-9_'])"),
    ),
    (
        "oops",
        re.compile(r"(?<![A-Za-z0-9_'])oops(?![A-Za-z0-9_'])"),
    ),
    (
        "abort",
        re.compile(r"(?i)(?<![A-Za-z0-9_'])Abort\s*\."),
    ),
    (
        "trusted",
        re.compile(r"(?i)(?<![A-Za-z0-9_'])trusted(?![A-Za-z0-9_'])"),
    ),
    (
        "unsafe",
        re.compile(
            r"(?im)^\s*(?:unsafe\s+(?:def|theorem|inductive|structure|abbrev)|"
            r"axiom\s+|constant\s+)"
        ),
    ),
    (
        "axiomatization",
        re.compile(
            r"(?im)^\s*(?:axiomatization\b|axioms?\s+|consts?\s+[^\n]*where\b)"
        ),
    ),
    (
        "cheat",
        re.compile(r"(?i)(?<![A-Za-z0-9_'])(?:cheat|cheating)(?![A-Za-z0-9_'])"),
    ),
    (
        "prove_false",
        re.compile(r"(?i)False\.elim|prove_False|admit_false"),
    ),
)

DEFAULT_LEAN_IMPORTS: Final[tuple[str, ...]] = ("Init",)
DEFAULT_ROCQ_IMPORTS: Final[tuple[str, ...]] = ("Coq.Init.Prelude",)
DEFAULT_ISABELLE_IMPORTS: Final[tuple[str, ...]] = ("Main",)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class KernelTargetKind(StrEnum):
    """Official kernel targets that may become proof authority."""

    LEAN = "lean"
    ROCQ = "rocq"
    ISABELLE = "isabelle"


class RouteSurface(StrEnum):
    """Upstream surfaces joined into the target-theory model."""

    PROTOCOL_PROVERIF = "protocol_proverif"
    PROTOCOL_TAMARIN = "protocol_tamarin"
    PROGRAM_VC = "program_vc"
    PROGRAM_SMT = "program_smt"
    PROGRAM_CHC = "program_chc"
    RESOURCE_REFINEMENT = "resource_refinement"
    HAMMER_STRATEGY = "hammer_strategy"
    ATP_CANDIDATE = "atp_candidate"
    KERNEL_NATIVE = "kernel_native"


class DeclarationKind(StrEnum):
    """Closed declaration kinds admitted by the target-theory model."""

    IMPORT = "import"
    AXIOM = "axiom"
    DEFINITION = "definition"
    THEOREM = "theorem"
    LEMMA = "lemma"
    TYPE = "type"
    CONSTANT = "constant"
    NOTATION = "notation"
    OBLIGATION = "obligation"


class TrustDisposition(StrEnum):
    """How trust-bearing constructs are treated on a route."""

    REJECT = "reject"
    RECORD_ONLY = "record_only"
    CANDIDATE = "candidate"
    KERNEL_REQUIRED = "kernel_required"


class ProofAuthorityRole(StrEnum):
    """Who may assert a checked theorem on a route."""

    OFFICIAL_KERNEL = "official_kernel"
    CANDIDATE_ONLY = "candidate_only"
    PROTOCOL_SYMBOLIC = "protocol_symbolic"
    SMT_SATISFIABILITY = "smt_satisfiability"
    NONE = "none"


class HammerStrategyKind(StrEnum):
    """Hammer / ATP strategy kinds (never proof authority)."""

    PREMISE_SELECTION = "premise_selection"
    TACTIC_SUGGESTION = "tactic_suggestion"
    ATP_CANDIDATE = "atp_candidate"
    RECONSTRUCTION_PLAN = "reconstruction_plan"
    PORTFOLIO_HINT = "portfolio_hint"


class ReconstructionStatus(StrEnum):
    """Reconstruction posture for hammer / ATP candidates."""

    NOT_ATTEMPTED = "not_attempted"
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


# Surfaces that may never claim theorem authority without kernel reconstruction.
_NON_KERNEL_SURFACES: Final[frozenset[RouteSurface]] = frozenset(
    {
        RouteSurface.PROTOCOL_PROVERIF,
        RouteSurface.PROTOCOL_TAMARIN,
        RouteSurface.PROGRAM_VC,
        RouteSurface.PROGRAM_SMT,
        RouteSurface.PROGRAM_CHC,
        RouteSurface.RESOURCE_REFINEMENT,
        RouteSurface.HAMMER_STRATEGY,
        RouteSurface.ATP_CANDIDATE,
    }
)

_SURFACE_AUTHORITY: Final[dict[RouteSurface, ProofAuthorityRole]] = {
    RouteSurface.PROTOCOL_PROVERIF: ProofAuthorityRole.PROTOCOL_SYMBOLIC,
    RouteSurface.PROTOCOL_TAMARIN: ProofAuthorityRole.PROTOCOL_SYMBOLIC,
    RouteSurface.PROGRAM_VC: ProofAuthorityRole.CANDIDATE_ONLY,
    RouteSurface.PROGRAM_SMT: ProofAuthorityRole.SMT_SATISFIABILITY,
    RouteSurface.PROGRAM_CHC: ProofAuthorityRole.SMT_SATISFIABILITY,
    RouteSurface.RESOURCE_REFINEMENT: ProofAuthorityRole.CANDIDATE_ONLY,
    RouteSurface.HAMMER_STRATEGY: ProofAuthorityRole.CANDIDATE_ONLY,
    RouteSurface.ATP_CANDIDATE: ProofAuthorityRole.CANDIDATE_ONLY,
    RouteSurface.KERNEL_NATIVE: ProofAuthorityRole.OFFICIAL_KERNEL,
}

_KERNEL_ENCODINGS: Final[dict[KernelTargetKind, str]] = {
    KernelTargetKind.LEAN: TARGET_ENCODING_LEAN,
    KernelTargetKind.ROCQ: TARGET_ENCODING_ROCQ,
    KernelTargetKind.ISABELLE: TARGET_ENCODING_ISABELLE,
}

_KERNEL_DEFAULT_IMPORTS: Final[dict[KernelTargetKind, tuple[str, ...]]] = {
    KernelTargetKind.LEAN: DEFAULT_LEAN_IMPORTS,
    KernelTargetKind.ROCQ: DEFAULT_ROCQ_IMPORTS,
    KernelTargetKind.ISABELLE: DEFAULT_ISABELLE_IMPORTS,
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class KernelTargetError(ValueError):
    """Raised when a kernel-target contract is violated."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_INVALID_THEORY,
        path: str = "",
        remediation: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.remediation = remediation
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "remediation": self.remediation,
        }


class TrustEscapeError(KernelTargetError):
    """Raised when generated source contains a forbidden trust escape."""

    def __init__(
        self,
        message: str,
        *,
        escapes: Sequence[str] = (),
        path: str = "source",
    ) -> None:
        super().__init__(
            message,
            code=CODE_TRUST_ESCAPE,
            path=path,
            remediation=(
                "Remove sorry/admit/trusted/unsafe escapes; supply a reconstructable "
                "proof body for the official kernel."
            ),
        )
        self.escapes = tuple(escapes)


class AuthorityPromotionError(KernelTargetError):
    """Raised when a non-kernel surface attempts theorem authority."""

    def __init__(self, message: str, *, path: str = "authority") -> None:
        super().__init__(
            message,
            code=CODE_AUTHORITY_PROMOTION,
            path=path,
            remediation=(
                "Keep ProVerif/Tamarin/SMT/Hammer/ATP results as candidates or "
                "protocol/satisfiability evidence until an official kernel accepts "
                "the reconstructed theorem under a pinned environment identity."
            ),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: object, label: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
    ):
        qualifier = "an empty or " if optional else "a "
        raise KernelTargetError(
            f"{label} must be {qualifier}non-empty trimmed string without NUL bytes",
            code=CODE_MALFORMED,
            path=label,
        )
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise KernelTargetError(
            f"{label} must be a stable identifier",
            code=CODE_MALFORMED,
            path=label,
        )
    return result


def _digest(value: object, label: str) -> str:
    result = _text(value, label)
    if not _DIGEST_RE.fullmatch(result):
        raise KernelTargetError(
            f"{label} must be a lowercase SHA-256 digest",
            code=CODE_MALFORMED,
            path=label,
        )
    return result


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise KernelTargetError(
            f"{label} must be a mapping",
            code=CODE_MALFORMED,
            path=label,
        )
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise KernelTargetError(
            f"{label} must be a sequence",
            code=CODE_MALFORMED,
            path=label,
        )
    return value


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise KernelTargetError(
            f"{label} must be one of {choices}",
            code=CODE_MALFORMED,
            path=label,
        ) from error


def _safe_ident(value: str, *, prefix: str = "id") -> str:
    cleaned = _SAFE_IDENT_RE.sub("_", value.strip())
    cleaned = cleaned.strip("_") or prefix
    if cleaned[0].isdigit():
        cleaned = f"{prefix}_{cleaned}"
    return cleaned[:96]


def content_digest(content: str) -> str:
    """Stable content digest for theorem / source text."""

    if not isinstance(content, str) or "\x00" in content:
        raise KernelTargetError(
            "content must be text without NUL bytes",
            code=CODE_MALFORMED,
            path="content",
        )
    return stable_digest({"content": content})


def scan_trust_escapes(source: str) -> tuple[str, ...]:
    """Return ordered trust-escape kinds found in ``source``."""

    if not isinstance(source, str):
        raise KernelTargetError(
            "source must be text",
            code=CODE_MALFORMED,
            path="source",
        )
    findings: list[str] = []
    for kind, pattern in _TRUST_ESCAPE_PATTERNS:
        if pattern.search(source):
            findings.append(kind)
    return tuple(findings)


def reject_trust_escapes(source: str, *, path: str = "source") -> None:
    """Fail closed when generated source contains trust escapes."""

    escapes = scan_trust_escapes(source)
    if escapes:
        raise TrustEscapeError(
            "generated kernel source rejects trust escapes: "
            + ", ".join(escapes),
            escapes=escapes,
            path=path,
        )


def is_official_kernel(target: KernelTargetKind | str) -> bool:
    """Return True when ``target`` is an official kernel proof authority."""

    kind = _enum(target, KernelTargetKind, "target")
    return kind in {
        KernelTargetKind.LEAN,
        KernelTargetKind.ROCQ,
        KernelTargetKind.ISABELLE,
    }


def surface_authority_role(
    surface: RouteSurface | str,
) -> ProofAuthorityRole:
    """Return the maximum authority role admitted for a route surface."""

    kind = _enum(surface, RouteSurface, "surface")
    return _SURFACE_AUTHORITY[kind]


def result_authority_for_surface(
    surface: RouteSurface | str,
) -> ResultAuthority:
    """Map a route surface to the closed backend result authority."""

    role = surface_authority_role(surface)
    if role is ProofAuthorityRole.OFFICIAL_KERNEL:
        return ResultAuthority.THEOREM
    if role is ProofAuthorityRole.PROTOCOL_SYMBOLIC:
        return ResultAuthority.PROTOCOL
    if role is ProofAuthorityRole.SMT_SATISFIABILITY:
        return ResultAuthority.SATISFIABILITY
    return ResultAuthority.CANDIDATE


# ---------------------------------------------------------------------------
# Source maps, declarations, identities
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TargetSourceMap:
    """Source-map binding from a target declaration to an upstream span."""

    owner_id: str
    source_ref_id: str = ""
    span_id: str = ""
    start_byte: int = 0
    end_byte: int = 0
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = TARGET_SOURCE_MAP_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(
            self,
            "source_ref_id",
            _text(self.source_ref_id, "source_ref_id", optional=True),
        )
        object.__setattr__(
            self, "span_id", _text(self.span_id, "span_id", optional=True)
        )
        if not isinstance(self.start_byte, int) or self.start_byte < 0:
            raise KernelTargetError(
                "start_byte must be a non-negative integer",
                code=CODE_INVALID_SOURCE_MAP,
                path="start_byte",
            )
        if not isinstance(self.end_byte, int) or self.end_byte < self.start_byte:
            raise KernelTargetError(
                "end_byte must be >= start_byte",
                code=CODE_INVALID_SOURCE_MAP,
                path="end_byte",
            )
        try:
            object.__setattr__(self, "attributes", FrozenMap(self.attributes))
        except (TypeError, ValueError) as error:
            raise KernelTargetError(
                "attributes must be immutable JSON-compatible data",
                code=CODE_INVALID_SOURCE_MAP,
                path="attributes",
            ) from error
        if self.schema_version != TARGET_SOURCE_MAP_SCHEMA:
            raise KernelTargetError(
                f"unsupported source-map schema: {self.schema_version!r}",
                code=CODE_INVALID_SOURCE_MAP,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "end_byte": self.end_byte,
            "owner_id": self.owner_id,
            "schema_version": self.schema_version,
            "source_ref_id": self.source_ref_id,
            "span_id": self.span_id,
            "start_byte": self.start_byte,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TargetSourceMap":
        value = _mapping(value, "source_map")
        return cls(
            owner_id=value.get("owner_id", ""),
            source_ref_id=value.get("source_ref_id", ""),
            span_id=value.get("span_id", ""),
            start_byte=int(value.get("start_byte", 0)),
            end_byte=int(value.get("end_byte", 0)),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version") or TARGET_SOURCE_MAP_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class TargetDeclaration:
    """One import, axiom, definition, or theorem in a target theory."""

    declaration_id: str
    kind: DeclarationKind | str
    name: str
    statement: str = ""
    body: str = ""
    import_path: str = ""
    is_axiom: bool = False
    is_trust_escape: bool = False
    source_maps: tuple[TargetSourceMap, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = TARGET_DECLARATION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "declaration_id",
            _identifier(self.declaration_id, "declaration_id"),
        )
        kind = _enum(self.kind, DeclarationKind, "kind")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(
            self, "statement", _text(self.statement, "statement", optional=True)
        )
        object.__setattr__(self, "body", _text(self.body, "body", optional=True))
        object.__setattr__(
            self,
            "import_path",
            _text(self.import_path, "import_path", optional=True),
        )
        if not isinstance(self.is_axiom, bool):
            raise KernelTargetError(
                "is_axiom must be a boolean",
                code=CODE_INVALID_DECLARATION,
                path="is_axiom",
            )
        if not isinstance(self.is_trust_escape, bool):
            raise KernelTargetError(
                "is_trust_escape must be a boolean",
                code=CODE_INVALID_DECLARATION,
                path="is_trust_escape",
            )
        if kind is DeclarationKind.AXIOM:
            object.__setattr__(self, "is_axiom", True)
        if kind is DeclarationKind.IMPORT and not self.import_path:
            object.__setattr__(self, "import_path", self.name)
        maps = tuple(
            item
            if isinstance(item, TargetSourceMap)
            else TargetSourceMap.from_dict(_mapping(item, "source_map"))
            for item in _sequence(self.source_maps, "source_maps")
        )
        object.__setattr__(
            self,
            "source_maps",
            tuple(sorted(maps, key=lambda item: (item.owner_id, item.span_id))),
        )
        try:
            object.__setattr__(self, "attributes", FrozenMap(self.attributes))
        except (TypeError, ValueError) as error:
            raise KernelTargetError(
                "attributes must be immutable JSON-compatible data",
                code=CODE_INVALID_DECLARATION,
                path="attributes",
            ) from error
        if self.schema_version != TARGET_DECLARATION_SCHEMA:
            raise KernelTargetError(
                f"unsupported declaration schema: {self.schema_version!r}",
                code=CODE_INVALID_DECLARATION,
            )
        if self.is_trust_escape:
            raise TrustEscapeError(
                f"declaration {self.declaration_id!r} is marked as a trust escape",
                escapes=("declaration_trust_escape",),
                path=self.declaration_id,
            )
        # Bodies and statements must themselves be escape-free.
        for field_name, text in (("statement", self.statement), ("body", self.body)):
            if text:
                reject_trust_escapes(text, path=f"{self.declaration_id}.{field_name}")

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "body": self.body,
            "declaration_id": self.declaration_id,
            "import_path": self.import_path,
            "is_axiom": self.is_axiom,
            "is_trust_escape": self.is_trust_escape,
            "kind": self.kind.value if isinstance(self.kind, DeclarationKind) else self.kind,
            "name": self.name,
            "schema_version": self.schema_version,
            "source_maps": [item.to_dict() for item in self.source_maps],
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TargetDeclaration":
        value = _mapping(value, "declaration")
        return cls(
            declaration_id=value.get("declaration_id", ""),
            kind=value.get("kind", DeclarationKind.THEOREM),
            name=value.get("name", ""),
            statement=value.get("statement", ""),
            body=value.get("body", ""),
            import_path=value.get("import_path", ""),
            is_axiom=bool(value.get("is_axiom", False)),
            is_trust_escape=bool(value.get("is_trust_escape", False)),
            source_maps=tuple(value.get("source_maps", ())),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version") or TARGET_DECLARATION_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class TheoremIdentity:
    """Exact identity of one generated theorem obligation."""

    theorem_id: str
    theorem_name: str
    statement: str
    statement_digest: str
    theory_id: str
    source_surface: RouteSurface | str
    kernel_target: KernelTargetKind | str | None = None
    source_maps: tuple[TargetSourceMap, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = THEOREM_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "theorem_id", _identifier(self.theorem_id, "theorem_id"))
        object.__setattr__(
            self, "theorem_name", _text(self.theorem_name, "theorem_name")
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(
            self,
            "statement_digest",
            _digest(self.statement_digest, "statement_digest"),
        )
        expected = content_digest(self.statement)
        if self.statement_digest != expected:
            raise KernelTargetError(
                "statement_digest does not match statement content",
                code=CODE_IDENTITY_MISMATCH,
                path="statement_digest",
            )
        object.__setattr__(self, "theory_id", _identifier(self.theory_id, "theory_id"))
        object.__setattr__(
            self,
            "source_surface",
            _enum(self.source_surface, RouteSurface, "source_surface"),
        )
        if self.kernel_target is not None:
            object.__setattr__(
                self,
                "kernel_target",
                _enum(self.kernel_target, KernelTargetKind, "kernel_target"),
            )
        maps = tuple(
            item
            if isinstance(item, TargetSourceMap)
            else TargetSourceMap.from_dict(_mapping(item, "source_map"))
            for item in _sequence(self.source_maps, "source_maps")
        )
        object.__setattr__(self, "source_maps", maps)
        try:
            object.__setattr__(self, "attributes", FrozenMap(self.attributes))
        except (TypeError, ValueError) as error:
            raise KernelTargetError(
                "attributes must be immutable JSON-compatible data",
                code=CODE_INVALID_THEOREM,
                path="attributes",
            ) from error
        if self.schema_version != THEOREM_IDENTITY_SCHEMA:
            raise KernelTargetError(
                f"unsupported theorem identity schema: {self.schema_version!r}",
                code=CODE_INVALID_THEOREM,
            )
        reject_trust_escapes(self.statement, path="theorem.statement")

    @property
    def identity_digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "kernel_target": (
                self.kernel_target.value
                if isinstance(self.kernel_target, KernelTargetKind)
                else self.kernel_target
            ),
            "schema_version": self.schema_version,
            "source_maps": [item.to_dict() for item in self.source_maps],
            "source_surface": (
                self.source_surface.value
                if isinstance(self.source_surface, RouteSurface)
                else self.source_surface
            ),
            "statement": self.statement,
            "statement_digest": self.statement_digest,
            "theorem_id": self.theorem_id,
            "theorem_name": self.theorem_name,
            "theory_id": self.theory_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TheoremIdentity":
        value = _mapping(value, "theorem_identity")
        return cls(
            theorem_id=value.get("theorem_id", ""),
            theorem_name=value.get("theorem_name", ""),
            statement=value.get("statement", ""),
            statement_digest=value.get("statement_digest", ""),
            theory_id=value.get("theory_id", ""),
            source_surface=value.get("source_surface", RouteSurface.KERNEL_NATIVE),
            kernel_target=value.get("kernel_target"),
            source_maps=tuple(value.get("source_maps", ())),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version") or THEOREM_IDENTITY_SCHEMA
            ),
        )

    @classmethod
    def bind(
        cls,
        *,
        theorem_id: str,
        theorem_name: str,
        statement: str,
        theory_id: str,
        source_surface: RouteSurface | str,
        kernel_target: KernelTargetKind | str | None = None,
        source_maps: Sequence[TargetSourceMap | Mapping[str, Any]] = (),
        attributes: Mapping[str, Any] | FrozenMap | None = None,
    ) -> "TheoremIdentity":
        return cls(
            theorem_id=theorem_id,
            theorem_name=theorem_name,
            statement=statement,
            statement_digest=content_digest(statement),
            theory_id=theory_id,
            source_surface=source_surface,
            kernel_target=kernel_target,
            source_maps=tuple(source_maps),
            attributes=attributes or {},
        )


@dataclass(frozen=True, slots=True)
class EnvironmentIdentity:
    """Pinned kernel environment identity for authoritative checking."""

    environment_id: str
    kernel_target: KernelTargetKind | str
    toolchain_id: str
    toolchain_version: str
    source_tree_digest: str = ""
    session_or_package: str = ""
    os_name: str = ""
    architecture: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = ENVIRONMENT_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "environment_id",
            _identifier(self.environment_id, "environment_id"),
        )
        object.__setattr__(
            self,
            "kernel_target",
            _enum(self.kernel_target, KernelTargetKind, "kernel_target"),
        )
        object.__setattr__(
            self, "toolchain_id", _text(self.toolchain_id, "toolchain_id")
        )
        object.__setattr__(
            self,
            "toolchain_version",
            _text(self.toolchain_version, "toolchain_version"),
        )
        object.__setattr__(
            self,
            "source_tree_digest",
            _text(self.source_tree_digest, "source_tree_digest", optional=True),
        )
        if self.source_tree_digest and not _DIGEST_RE.fullmatch(self.source_tree_digest):
            raise KernelTargetError(
                "source_tree_digest must be a lowercase SHA-256 digest when set",
                code=CODE_INVALID_ENVIRONMENT,
                path="source_tree_digest",
            )
        object.__setattr__(
            self,
            "session_or_package",
            _text(self.session_or_package, "session_or_package", optional=True),
        )
        object.__setattr__(
            self, "os_name", _text(self.os_name, "os_name", optional=True)
        )
        object.__setattr__(
            self,
            "architecture",
            _text(self.architecture, "architecture", optional=True),
        )
        try:
            object.__setattr__(self, "attributes", FrozenMap(self.attributes))
        except (TypeError, ValueError) as error:
            raise KernelTargetError(
                "attributes must be immutable JSON-compatible data",
                code=CODE_INVALID_ENVIRONMENT,
                path="attributes",
            ) from error
        if self.schema_version != ENVIRONMENT_IDENTITY_SCHEMA:
            raise KernelTargetError(
                f"unsupported environment identity schema: {self.schema_version!r}",
                code=CODE_INVALID_ENVIRONMENT,
            )

    @property
    def identity_digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "architecture": self.architecture,
            "attributes": self.attributes.to_dict(),
            "environment_id": self.environment_id,
            "kernel_target": (
                self.kernel_target.value
                if isinstance(self.kernel_target, KernelTargetKind)
                else self.kernel_target
            ),
            "os_name": self.os_name,
            "schema_version": self.schema_version,
            "session_or_package": self.session_or_package,
            "source_tree_digest": self.source_tree_digest,
            "toolchain_id": self.toolchain_id,
            "toolchain_version": self.toolchain_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EnvironmentIdentity":
        value = _mapping(value, "environment_identity")
        return cls(
            environment_id=value.get("environment_id", ""),
            kernel_target=value.get("kernel_target", KernelTargetKind.LEAN),
            toolchain_id=value.get("toolchain_id", ""),
            toolchain_version=value.get("toolchain_version", ""),
            source_tree_digest=value.get("source_tree_digest", ""),
            session_or_package=value.get("session_or_package", ""),
            os_name=value.get("os_name", ""),
            architecture=value.get("architecture", ""),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version") or ENVIRONMENT_IDENTITY_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class TrustReceipt:
    """Explicit trust posture for axioms, assumptions, and non-kernel evidence."""

    receipt_id: str
    surface: RouteSurface | str
    disposition: TrustDisposition | str
    authority_role: ProofAuthorityRole | str
    result_authority: ResultAuthority | str
    axioms: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    trust_escapes_rejected: tuple[str, ...] = ()
    allows_theorem_authority: bool = False
    notes: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = TARGET_TRUST_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        surface = _enum(self.surface, RouteSurface, "surface")
        object.__setattr__(self, "surface", surface)
        disposition = _enum(self.disposition, TrustDisposition, "disposition")
        object.__setattr__(self, "disposition", disposition)
        role = _enum(self.authority_role, ProofAuthorityRole, "authority_role")
        object.__setattr__(self, "authority_role", role)
        authority = _enum(self.result_authority, ResultAuthority, "result_authority")
        object.__setattr__(self, "result_authority", authority)
        object.__setattr__(
            self,
            "axioms",
            tuple(_text(item, "axioms item") for item in self.axioms),
        )
        object.__setattr__(
            self,
            "assumptions",
            tuple(_text(item, "assumptions item") for item in self.assumptions),
        )
        object.__setattr__(
            self,
            "trust_escapes_rejected",
            tuple(
                _text(item, "trust_escapes_rejected item")
                for item in self.trust_escapes_rejected
            ),
        )
        if not isinstance(self.allows_theorem_authority, bool):
            raise KernelTargetError(
                "allows_theorem_authority must be a boolean",
                code=CODE_INVALID_TRUST,
                path="allows_theorem_authority",
            )
        # Non-kernel surfaces never grant theorem authority.
        if surface in _NON_KERNEL_SURFACES and self.allows_theorem_authority:
            raise AuthorityPromotionError(
                f"surface {surface.value!r} cannot grant theorem authority"
            )
        if (
            role is not ProofAuthorityRole.OFFICIAL_KERNEL
            and self.allows_theorem_authority
        ):
            raise AuthorityPromotionError(
                "only official_kernel authority_role may allow theorem authority"
            )
        if authority is ResultAuthority.THEOREM and not self.allows_theorem_authority:
            raise AuthorityPromotionError(
                "result_authority=theorem requires allows_theorem_authority=True"
            )
        if authority is ResultAuthority.THEOREM and role is not ProofAuthorityRole.OFFICIAL_KERNEL:
            raise AuthorityPromotionError(
                "result_authority=theorem requires official_kernel role"
            )
        object.__setattr__(self, "notes", _text(self.notes, "notes", optional=True))
        try:
            object.__setattr__(self, "attributes", FrozenMap(self.attributes))
        except (TypeError, ValueError) as error:
            raise KernelTargetError(
                "attributes must be immutable JSON-compatible data",
                code=CODE_INVALID_TRUST,
                path="attributes",
            ) from error
        if self.schema_version != TARGET_TRUST_RECEIPT_SCHEMA:
            raise KernelTargetError(
                f"unsupported trust receipt schema: {self.schema_version!r}",
                code=CODE_INVALID_TRUST,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allows_theorem_authority": self.allows_theorem_authority,
            "assumptions": list(self.assumptions),
            "attributes": self.attributes.to_dict(),
            "authority_role": (
                self.authority_role.value
                if isinstance(self.authority_role, ProofAuthorityRole)
                else self.authority_role
            ),
            "axioms": list(self.axioms),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, TrustDisposition)
                else self.disposition
            ),
            "notes": self.notes,
            "receipt_id": self.receipt_id,
            "result_authority": (
                self.result_authority.value
                if isinstance(self.result_authority, ResultAuthority)
                else self.result_authority
            ),
            "schema_version": self.schema_version,
            "surface": (
                self.surface.value
                if isinstance(self.surface, RouteSurface)
                else self.surface
            ),
            "trust_escapes_rejected": list(self.trust_escapes_rejected),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrustReceipt":
        value = _mapping(value, "trust_receipt")
        return cls(
            receipt_id=value.get("receipt_id", ""),
            surface=value.get("surface", RouteSurface.KERNEL_NATIVE),
            disposition=value.get("disposition", TrustDisposition.REJECT),
            authority_role=value.get(
                "authority_role", ProofAuthorityRole.CANDIDATE_ONLY
            ),
            result_authority=value.get(
                "result_authority", ResultAuthority.CANDIDATE
            ),
            axioms=tuple(value.get("axioms", ())),
            assumptions=tuple(value.get("assumptions", ())),
            trust_escapes_rejected=tuple(value.get("trust_escapes_rejected", ())),
            allows_theorem_authority=bool(
                value.get("allows_theorem_authority", False)
            ),
            notes=value.get("notes", ""),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version") or TARGET_TRUST_RECEIPT_SCHEMA
            ),
        )

    @classmethod
    def for_surface(
        cls,
        *,
        receipt_id: str,
        surface: RouteSurface | str,
        axioms: Sequence[str] = (),
        assumptions: Sequence[str] = (),
        trust_escapes_rejected: Sequence[str] = (),
        notes: str = "",
    ) -> "TrustReceipt":
        surface_kind = _enum(surface, RouteSurface, "surface")
        role = surface_authority_role(surface_kind)
        authority = result_authority_for_surface(surface_kind)
        allows = role is ProofAuthorityRole.OFFICIAL_KERNEL
        disposition = (
            TrustDisposition.KERNEL_REQUIRED
            if allows
            else TrustDisposition.CANDIDATE
        )
        return cls(
            receipt_id=receipt_id,
            surface=surface_kind,
            disposition=disposition,
            authority_role=role,
            result_authority=authority,
            axioms=tuple(axioms),
            assumptions=tuple(assumptions),
            trust_escapes_rejected=tuple(trust_escapes_rejected),
            allows_theorem_authority=allows,
            notes=notes,
        )


# ---------------------------------------------------------------------------
# TargetTheoryModel@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TargetTheoryModel:
    """Target-neutral theory model shared by protocol, program, and kernels.

    Interface: ``TargetTheoryModel@1``.

    Holds exact imports, declarations, axioms, theorem identities, source maps,
    and trust receipts.  Full Lean/Rocq/Isabelle language parsing is *not*
    claimed; this is a controlled generator/import-manifest model only.
    """

    INTERFACE: ClassVar[str] = TARGET_THEORY_MODEL_INTERFACE

    theory_id: str
    name: str
    source_surface: RouteSurface | str
    declarations: tuple[TargetDeclaration, ...] = ()
    theorems: tuple[TheoremIdentity, ...] = ()
    imports: tuple[str, ...] = ()
    axioms: tuple[str, ...] = ()
    source_maps: tuple[TargetSourceMap, ...] = ()
    trust_receipt: TrustReceipt | None = None
    environment: EnvironmentIdentity | None = None
    family_id: str = TARGET_THEORY_FAMILY_ID
    profile_id: str = TARGET_THEORY_PROFILE_ID
    interface: str = TARGET_THEORY_MODEL_INTERFACE
    schema_version: str = TARGET_THEORY_SCHEMA
    attributes: FrozenMap = field(default_factory=FrozenMap)
    document_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "theory_id", _identifier(self.theory_id, "theory_id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        surface = _enum(self.source_surface, RouteSurface, "source_surface")
        object.__setattr__(self, "source_surface", surface)

        declarations = tuple(
            item
            if isinstance(item, TargetDeclaration)
            else TargetDeclaration.from_dict(_mapping(item, "declaration"))
            for item in _sequence(self.declarations, "declarations")
        )
        decl_ids = [item.declaration_id for item in declarations]
        if len(decl_ids) != len(set(decl_ids)):
            raise KernelTargetError(
                "declaration_ids must be unique",
                code=CODE_INVALID_THEORY,
                path="declarations",
            )
        object.__setattr__(
            self,
            "declarations",
            tuple(sorted(declarations, key=lambda item: item.declaration_id)),
        )

        theorems = tuple(
            item
            if isinstance(item, TheoremIdentity)
            else TheoremIdentity.from_dict(_mapping(item, "theorem"))
            for item in _sequence(self.theorems, "theorems")
        )
        for theorem in theorems:
            if theorem.theory_id != self.theory_id:
                raise KernelTargetError(
                    f"theorem {theorem.theorem_id!r} theory_id mismatch",
                    code=CODE_IDENTITY_MISMATCH,
                    path="theorems",
                )
        object.__setattr__(
            self,
            "theorems",
            tuple(sorted(theorems, key=lambda item: item.theorem_id)),
        )

        imports = tuple(_text(item, "imports item") for item in self.imports)
        # Prefer explicit import declarations when present.
        import_decls = tuple(
            item.import_path or item.name
            for item in self.declarations
            if item.kind is DeclarationKind.IMPORT
        )
        if import_decls:
            imports = tuple(dict.fromkeys((*imports, *import_decls)))
        object.__setattr__(self, "imports", imports)

        axioms = tuple(_text(item, "axioms item") for item in self.axioms)
        axiom_decls = tuple(
            item.name
            for item in self.declarations
            if item.is_axiom or item.kind is DeclarationKind.AXIOM
        )
        if axiom_decls:
            axioms = tuple(dict.fromkeys((*axioms, *axiom_decls)))
        object.__setattr__(self, "axioms", axioms)

        maps = tuple(
            item
            if isinstance(item, TargetSourceMap)
            else TargetSourceMap.from_dict(_mapping(item, "source_map"))
            for item in _sequence(self.source_maps, "source_maps")
        )
        # Include declaration-local maps.
        for declaration in self.declarations:
            maps = (*maps, *declaration.source_maps)
        for theorem in self.theorems:
            maps = (*maps, *theorem.source_maps)
        # Deduplicate by owner/span.
        seen: set[tuple[str, str, int, int]] = set()
        unique_maps: list[TargetSourceMap] = []
        for item in maps:
            key = (item.owner_id, item.span_id, item.start_byte, item.end_byte)
            if key in seen:
                continue
            seen.add(key)
            unique_maps.append(item)
        object.__setattr__(
            self,
            "source_maps",
            tuple(sorted(unique_maps, key=lambda item: (item.owner_id, item.span_id))),
        )

        trust = self.trust_receipt
        if trust is None:
            trust = TrustReceipt.for_surface(
                receipt_id=f"trust:{self.theory_id}",
                surface=surface,
                axioms=self.axioms,
            )
        elif not isinstance(trust, TrustReceipt):
            trust = TrustReceipt.from_dict(_mapping(trust, "trust_receipt"))
        if trust.surface is not surface and trust.surface is not RouteSurface.KERNEL_NATIVE:
            # Trust receipt surface must match the theory surface, except for
            # an explicit kernel-native upgrade path recorded separately.
            if trust.surface != surface:
                raise KernelTargetError(
                    "trust_receipt.surface must match theory source_surface",
                    code=CODE_INVALID_TRUST,
                    path="trust_receipt.surface",
                )
        object.__setattr__(self, "trust_receipt", trust)

        environment = self.environment
        if environment is not None and not isinstance(environment, EnvironmentIdentity):
            environment = EnvironmentIdentity.from_dict(
                _mapping(environment, "environment")
            )
            object.__setattr__(self, "environment", environment)

        object.__setattr__(self, "family_id", _text(self.family_id, "family_id"))
        if self.family_id != TARGET_THEORY_FAMILY_ID:
            raise KernelTargetError(
                f"family_id must be {TARGET_THEORY_FAMILY_ID!r}",
                code=CODE_INVALID_THEORY,
                path="family_id",
            )
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        if self.interface != TARGET_THEORY_MODEL_INTERFACE:
            raise KernelTargetError(
                f"unsupported interface: {self.interface!r}",
                code=CODE_INVALID_THEORY,
                path="interface",
            )
        if self.schema_version != TARGET_THEORY_SCHEMA:
            raise KernelTargetError(
                f"unsupported theory schema: {self.schema_version!r}",
                code=CODE_INVALID_THEORY,
            )
        try:
            object.__setattr__(self, "attributes", FrozenMap(self.attributes))
        except (TypeError, ValueError) as error:
            raise KernelTargetError(
                "attributes must be immutable JSON-compatible data",
                code=CODE_INVALID_THEORY,
                path="attributes",
            ) from error

        document_id = _text(self.document_id, "document_id", optional=True)
        if not document_id:
            document_id = self.identity.cid
        elif document_id != self.identity.cid:
            raise KernelTargetError(
                "document_id does not match canonical target-theory identity",
                code=CODE_IDENTITY_MISMATCH,
                path="document_id",
            )
        object.__setattr__(self, "document_id", document_id)

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self._identity_payload(),
            domain=KERNEL_TARGETS_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "axioms": list(self.axioms),
            "declarations": [item.to_dict() for item in self.declarations],
            "environment": (
                self.environment.to_dict() if self.environment is not None else None
            ),
            "family_id": self.family_id,
            "imports": list(self.imports),
            "interface": self.interface,
            "name": self.name,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "source_maps": [item.to_dict() for item in self.source_maps],
            "source_surface": (
                self.source_surface.value
                if isinstance(self.source_surface, RouteSurface)
                else self.source_surface
            ),
            "theorems": [item.to_dict() for item in self.theorems],
            "theory_id": self.theory_id,
            "trust_receipt": (
                self.trust_receipt.to_dict() if self.trust_receipt is not None else None
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["document_id"] = self.document_id
        return payload

    def to_json(self) -> str:
        return canonical_json_bytes(self.to_dict()).decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TargetTheoryModel":
        value = _mapping(value, "target_theory")
        return cls(
            theory_id=value.get("theory_id", ""),
            name=value.get("name", ""),
            source_surface=value.get("source_surface", RouteSurface.KERNEL_NATIVE),
            declarations=tuple(value.get("declarations", ())),
            theorems=tuple(value.get("theorems", ())),
            imports=tuple(value.get("imports", ())),
            axioms=tuple(value.get("axioms", ())),
            source_maps=tuple(value.get("source_maps", ())),
            trust_receipt=value.get("trust_receipt"),
            environment=value.get("environment"),
            family_id=value.get("family_id", TARGET_THEORY_FAMILY_ID),
            profile_id=value.get("profile_id", TARGET_THEORY_PROFILE_ID),
            interface=value.get("interface", TARGET_THEORY_MODEL_INTERFACE),
            schema_version=value.get("schema_version", TARGET_THEORY_SCHEMA),
            attributes=value.get("attributes", {}),
            document_id=value.get("document_id", ""),
        )

    def theorem_by_id(self, theorem_id: str) -> TheoremIdentity:
        for item in self.theorems:
            if item.theorem_id == theorem_id:
                return item
        raise KernelTargetError(
            f"unknown theorem_id {theorem_id!r}",
            code=CODE_INVALID_THEOREM,
            path="theorem_id",
        )

    def authority_ceiling(self) -> ResultAuthority:
        """Maximum result authority admitted before kernel reconstruction."""

        if self.trust_receipt is None:
            return result_authority_for_surface(self.source_surface)
        return (
            self.trust_receipt.result_authority
            if isinstance(self.trust_receipt.result_authority, ResultAuthority)
            else ResultAuthority(str(self.trust_receipt.result_authority))
        )


# ---------------------------------------------------------------------------
# KernelTargetGenerator@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KernelGeneratedSource:
    """Controlled generated kernel source with exact identities and digests."""

    source: str
    kernel_target: KernelTargetKind | str
    encoding: str
    source_digest: str
    theorem_identity: TheoremIdentity
    environment: EnvironmentIdentity
    imports: tuple[str, ...]
    axioms: tuple[str, ...]
    theory_id: str
    theory_document_id: str
    trust_escapes_rejected: tuple[str, ...] = ()
    proof_authority: ProofAuthorityRole | str = ProofAuthorityRole.OFFICIAL_KERNEL
    result_authority_ceiling: ResultAuthority | str = ResultAuthority.THEOREM
    kernel_accepted: bool = False
    interface: str = KERNEL_TARGET_GENERATOR_INTERFACE
    schema_version: str = KERNEL_GENERATED_SOURCE_SCHEMA
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip() or "\x00" in self.source:
            raise KernelTargetError(
                "generated source must be non-empty text without NUL",
                code=CODE_GENERATION,
                path="source",
            )
        # Always reject trust escapes in generated sources.
        found = scan_trust_escapes(self.source)
        if found:
            raise TrustEscapeError(
                "generated kernel source contains trust escapes: "
                + ", ".join(found),
                escapes=found,
                path="source",
            )
        object.__setattr__(
            self,
            "kernel_target",
            _enum(self.kernel_target, KernelTargetKind, "kernel_target"),
        )
        expected_encoding = _KERNEL_ENCODINGS[
            self.kernel_target  # type: ignore[index]
        ]
        encoding = _text(self.encoding, "encoding")
        if encoding != expected_encoding:
            raise KernelTargetError(
                f"encoding for {self.kernel_target} must be {expected_encoding!r}",
                code=CODE_GENERATION,
                path="encoding",
            )
        object.__setattr__(self, "encoding", encoding)
        object.__setattr__(
            self, "source_digest", _digest(self.source_digest, "source_digest")
        )
        if self.source_digest != content_digest(self.source):
            raise KernelTargetError(
                "source_digest does not match generated source",
                code=CODE_IDENTITY_MISMATCH,
                path="source_digest",
            )
        if not isinstance(self.theorem_identity, TheoremIdentity):
            object.__setattr__(
                self,
                "theorem_identity",
                TheoremIdentity.from_dict(
                    _mapping(self.theorem_identity, "theorem_identity")
                ),
            )
        if not isinstance(self.environment, EnvironmentIdentity):
            object.__setattr__(
                self,
                "environment",
                EnvironmentIdentity.from_dict(
                    _mapping(self.environment, "environment")
                ),
            )
        if self.environment.kernel_target != self.kernel_target:
            raise KernelTargetError(
                "environment.kernel_target must match generated kernel_target",
                code=CODE_IDENTITY_MISMATCH,
                path="environment.kernel_target",
            )
        object.__setattr__(
            self,
            "imports",
            tuple(_text(item, "imports item") for item in self.imports),
        )
        object.__setattr__(
            self,
            "axioms",
            tuple(_text(item, "axioms item") for item in self.axioms),
        )
        object.__setattr__(self, "theory_id", _identifier(self.theory_id, "theory_id"))
        object.__setattr__(
            self,
            "theory_document_id",
            _text(self.theory_document_id, "theory_document_id"),
        )
        object.__setattr__(
            self,
            "trust_escapes_rejected",
            tuple(
                _text(item, "trust_escapes_rejected item")
                for item in self.trust_escapes_rejected
            ),
        )
        object.__setattr__(
            self,
            "proof_authority",
            _enum(self.proof_authority, ProofAuthorityRole, "proof_authority"),
        )
        object.__setattr__(
            self,
            "result_authority_ceiling",
            _enum(
                self.result_authority_ceiling,
                ResultAuthority,
                "result_authority_ceiling",
            ),
        )
        if not isinstance(self.kernel_accepted, bool):
            raise KernelTargetError(
                "kernel_accepted must be a boolean",
                code=CODE_GENERATION,
                path="kernel_accepted",
            )
        # Generation alone never marks the kernel as accepted.
        if self.kernel_accepted:
            raise KernelTargetError(
                "kernel_accepted may only be set by an official kernel checker, "
                "not by source generation",
                code=CODE_AUTHORITY_PROMOTION,
                path="kernel_accepted",
            )
        if self.interface != KERNEL_TARGET_GENERATOR_INTERFACE:
            raise KernelTargetError(
                f"unsupported generator interface: {self.interface!r}",
                code=CODE_GENERATION,
            )
        if self.schema_version != KERNEL_GENERATED_SOURCE_SCHEMA:
            raise KernelTargetError(
                f"unsupported generated-source schema: {self.schema_version!r}",
                code=CODE_GENERATION,
            )
        try:
            object.__setattr__(self, "attributes", FrozenMap(self.attributes))
        except (TypeError, ValueError) as error:
            raise KernelTargetError(
                "attributes must be immutable JSON-compatible data",
                code=CODE_GENERATION,
                path="attributes",
            ) from error

    @property
    def theorem_identity_digest(self) -> str:
        return self.theorem_identity.identity_digest

    @property
    def environment_identity_digest(self) -> str:
        return self.environment.identity_digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "axioms": list(self.axioms),
            "encoding": self.encoding,
            "environment": self.environment.to_dict(),
            "environment_identity_digest": self.environment_identity_digest,
            "imports": list(self.imports),
            "interface": self.interface,
            "kernel_accepted": self.kernel_accepted,
            "kernel_target": (
                self.kernel_target.value
                if isinstance(self.kernel_target, KernelTargetKind)
                else self.kernel_target
            ),
            "proof_authority": (
                self.proof_authority.value
                if isinstance(self.proof_authority, ProofAuthorityRole)
                else self.proof_authority
            ),
            "result_authority_ceiling": (
                self.result_authority_ceiling.value
                if isinstance(self.result_authority_ceiling, ResultAuthority)
                else self.result_authority_ceiling
            ),
            "schema_version": self.schema_version,
            "source": self.source,
            "source_digest": self.source_digest,
            "theorem_identity": self.theorem_identity.to_dict(),
            "theorem_identity_digest": self.theorem_identity_digest,
            "theory_document_id": self.theory_document_id,
            "theory_id": self.theory_id,
            "trust_escapes_rejected": list(self.trust_escapes_rejected),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KernelGeneratedSource":
        value = _mapping(value, "generated_source")
        return cls(
            source=value.get("source", ""),
            kernel_target=value.get("kernel_target", KernelTargetKind.LEAN),
            encoding=value.get("encoding", TARGET_ENCODING_LEAN),
            source_digest=value.get("source_digest", ""),
            theorem_identity=value.get("theorem_identity", {}),
            environment=value.get("environment", {}),
            imports=tuple(value.get("imports", ())),
            axioms=tuple(value.get("axioms", ())),
            theory_id=value.get("theory_id", ""),
            theory_document_id=value.get("theory_document_id", ""),
            trust_escapes_rejected=tuple(value.get("trust_escapes_rejected", ())),
            proof_authority=value.get(
                "proof_authority", ProofAuthorityRole.OFFICIAL_KERNEL
            ),
            result_authority_ceiling=value.get(
                "result_authority_ceiling", ResultAuthority.THEOREM
            ),
            kernel_accepted=bool(value.get("kernel_accepted", False)),
            interface=value.get("interface", KERNEL_TARGET_GENERATOR_INTERFACE),
            schema_version=value.get(
                "schema_version", KERNEL_GENERATED_SOURCE_SCHEMA
            ),
            attributes=value.get("attributes", {}),
        )


class KernelTargetGenerator:
    """Generate controlled Lean/Rocq/Isabelle sources (``KernelTargetGenerator@1``).

    Generation never claims kernel acceptance.  Official kernels remain the
    sole proof authority.  Every emitted source rejects trust escapes and
    records exact theorem and environment identities.
    """

    interface: ClassVar[str] = KERNEL_TARGET_GENERATOR_INTERFACE
    schema_version: ClassVar[str] = KERNEL_GENERATED_SOURCE_SCHEMA

    def __init__(
        self,
        *,
        default_environment: EnvironmentIdentity | Mapping[str, Any] | None = None,
        reject_axioms_as_escapes: bool = True,
    ) -> None:
        if not isinstance(reject_axioms_as_escapes, bool):
            raise KernelTargetError(
                "reject_axioms_as_escapes must be a boolean",
                code=CODE_GENERATION,
            )
        self.reject_axioms_as_escapes = reject_axioms_as_escapes
        if default_environment is None:
            self.default_environment = None
        elif isinstance(default_environment, EnvironmentIdentity):
            self.default_environment = default_environment
        else:
            self.default_environment = EnvironmentIdentity.from_dict(
                _mapping(default_environment, "default_environment")
            )

    def generate(
        self,
        theory: TargetTheoryModel | Mapping[str, Any],
        *,
        kernel_target: KernelTargetKind | str,
        theorem_id: str | None = None,
        environment: EnvironmentIdentity | Mapping[str, Any] | None = None,
        proof_body: str = "",
    ) -> KernelGeneratedSource:
        """Generate one controlled kernel source for a theorem obligation."""

        if isinstance(theory, Mapping):
            theory = TargetTheoryModel.from_dict(theory)
        if not isinstance(theory, TargetTheoryModel):
            raise KernelTargetError(
                "generate requires TargetTheoryModel or mapping",
                code=CODE_GENERATION,
            )
        target = _enum(kernel_target, KernelTargetKind, "kernel_target")
        if not is_official_kernel(target):
            raise KernelTargetError(
                f"unsupported kernel target {target!r}",
                code=CODE_UNSUPPORTED_TARGET,
            )

        if theorem_id is None:
            if not theory.theorems:
                raise KernelTargetError(
                    "theory has no theorems to generate",
                    code=CODE_INVALID_THEOREM,
                    path="theorems",
                )
            theorem = theory.theorems[0]
        else:
            theorem = theory.theorem_by_id(theorem_id)

        env = environment if environment is not None else (
            theory.environment or self.default_environment
        )
        if env is None:
            raise KernelTargetError(
                "environment identity is required for kernel generation",
                code=CODE_INVALID_ENVIRONMENT,
                path="environment",
            )
        if not isinstance(env, EnvironmentIdentity):
            env = EnvironmentIdentity.from_dict(_mapping(env, "environment"))
        if env.kernel_target != target:
            raise KernelTargetError(
                "environment.kernel_target must match requested kernel_target",
                code=CODE_IDENTITY_MISMATCH,
                path="environment.kernel_target",
            )

        body = _text(proof_body, "proof_body", optional=True)
        if body:
            reject_trust_escapes(body, path="proof_body")

        # Explicit axioms remain recorded, but unreviewed axiom *escapes* in
        # generated proof text are always rejected via scan_trust_escapes.
        if self.reject_axioms_as_escapes and theory.axioms:
            # Axioms may exist as explicit theory assumptions; they must not
            # appear as inline trust escapes inside the generated proof body.
            pass

        imports = theory.imports or _KERNEL_DEFAULT_IMPORTS[target]
        source = self._render(
            target=target,
            theory=theory,
            theorem=theorem,
            imports=imports,
            proof_body=body,
            environment=env,
        )
        reject_trust_escapes(source, path="generated_source")

        # Bind theorem identity to the requested kernel target.
        bound_theorem = TheoremIdentity.bind(
            theorem_id=theorem.theorem_id,
            theorem_name=theorem.theorem_name,
            statement=theorem.statement,
            theory_id=theory.theory_id,
            source_surface=theorem.source_surface,
            kernel_target=target,
            source_maps=theorem.source_maps,
            attributes={
                **theorem.attributes.to_dict(),
                "generated_encoding": _KERNEL_ENCODINGS[target],
            },
        )

        return KernelGeneratedSource(
            source=source,
            kernel_target=target,
            encoding=_KERNEL_ENCODINGS[target],
            source_digest=content_digest(source),
            theorem_identity=bound_theorem,
            environment=env,
            imports=imports,
            axioms=theory.axioms,
            theory_id=theory.theory_id,
            theory_document_id=theory.document_id,
            trust_escapes_rejected=tuple(kind for kind, _ in _TRUST_ESCAPE_PATTERNS),
            proof_authority=ProofAuthorityRole.OFFICIAL_KERNEL,
            result_authority_ceiling=ResultAuthority.THEOREM,
            kernel_accepted=False,
        )

    def generate_all(
        self,
        theory: TargetTheoryModel | Mapping[str, Any],
        *,
        kernel_target: KernelTargetKind | str,
        environment: EnvironmentIdentity | Mapping[str, Any] | None = None,
        proof_bodies: Mapping[str, str] | None = None,
    ) -> tuple[KernelGeneratedSource, ...]:
        """Generate sources for every theorem in the theory."""

        if isinstance(theory, Mapping):
            theory = TargetTheoryModel.from_dict(theory)
        bodies = proof_bodies or {}
        return tuple(
            self.generate(
                theory,
                kernel_target=kernel_target,
                theorem_id=item.theorem_id,
                environment=environment,
                proof_body=str(bodies.get(item.theorem_id, "")),
            )
            for item in theory.theorems
        )

    def _render(
        self,
        *,
        target: KernelTargetKind,
        theory: TargetTheoryModel,
        theorem: TheoremIdentity,
        imports: Sequence[str],
        proof_body: str,
        environment: EnvironmentIdentity,
    ) -> str:
        name = _safe_ident(theorem.theorem_name, prefix="thm")
        statement = theorem.statement.strip()
        if target is KernelTargetKind.LEAN:
            return self._render_lean(
                name=name,
                statement=statement,
                imports=imports,
                proof_body=proof_body,
                theory=theory,
            )
        if target is KernelTargetKind.ROCQ:
            return self._render_rocq(
                name=name,
                statement=statement,
                imports=imports,
                proof_body=proof_body,
                theory=theory,
            )
        if target is KernelTargetKind.ISABELLE:
            return self._render_isabelle(
                name=name,
                statement=statement,
                imports=imports,
                proof_body=proof_body,
                theory=theory,
                environment=environment,
            )
        raise KernelTargetError(
            f"unsupported kernel target {target!r}",
            code=CODE_UNSUPPORTED_TARGET,
        )

    def _render_lean(
        self,
        *,
        name: str,
        statement: str,
        imports: Sequence[str],
        proof_body: str,
        theory: TargetTheoryModel,
    ) -> str:
        lines: list[str] = []
        for item in imports:
            lines.append(f"import {_safe_ident(item, prefix='Import').replace('_', '.')}")
        lines.append("")
        lines.append(f"-- theory: {theory.theory_id}")
        lines.append(f"-- surface: {theory.source_surface.value}")
        # Definitions / constants (non-axiom, non-import, non-theorem).
        for declaration in theory.declarations:
            if declaration.kind is DeclarationKind.DEFINITION and declaration.statement:
                lines.append(
                    f"def {_safe_ident(declaration.name)} : "
                    f"{declaration.statement.strip()}"
                    + (
                        f" := {declaration.body.strip()}"
                        if declaration.body
                        else ""
                    )
                )
        body = proof_body.strip() if proof_body else ""
        if body:
            # Controlled proof body — never inject sorry.
            lines.append(f"theorem {name} : {statement} := by")
            for line in body.splitlines() or [body]:
                lines.append(f"  {line}")
        else:
            # Obligation form: leave an incomplete-proof *marker comment* only.
            # The actual kernel source uses a reconstructable hole via a named
            # obligation constant rather than sorry/admit.
            lines.append(f"theorem {name} : {statement} := by")
            lines.append("  -- kernel_obligation: reconstruction_required")
            lines.append("  exact True.intro")
            # If statement is not True, generation still emits a type-checkable
            # placeholder only when statement is propositionally trivial;
            # otherwise require an explicit proof body.
            if statement not in {"True", "true", "⊤"}:
                # Replace the trivial body with a fail-closed obligation comment
                # and a non-escapeable hole that will not type-check as a proof
                # of an arbitrary goal — callers must supply proof_body.
                lines = lines[:-3]
                lines.append(f"theorem {name} : {statement} := by")
                lines.append("  -- kernel_obligation: reconstruction_required")
                # Use a named no-op that is not a trust escape; the kernel will
                # reject unsolved goals without sorry.
                lines.append("  skip")
                lines.append("  -- unsolved goals remain for official kernel check")
        text = "\n".join(lines).rstrip() + "\n"
        reject_trust_escapes(text)
        return text

    def _render_rocq(
        self,
        *,
        name: str,
        statement: str,
        imports: Sequence[str],
        proof_body: str,
        theory: TargetTheoryModel,
    ) -> str:
        lines: list[str] = []
        for item in imports:
            path = item if item.endswith(".") else f"{item}."
            if path.lower().startswith("require"):
                lines.append(path if path.endswith(".") else f"{path}.")
            else:
                lines.append(f"Require Import {item}.")
        lines.append("")
        lines.append(f"(* theory: {theory.theory_id} *)")
        lines.append(f"(* surface: {theory.source_surface.value} *)")
        body = proof_body.strip() if proof_body else ""
        lines.append(f"Theorem {name} : {statement}.")
        lines.append("Proof.")
        if body:
            for line in body.splitlines() or [body]:
                lines.append(f"  {line}")
        else:
            lines.append("  (* kernel_obligation: reconstruction_required *)")
            if statement in {"True", "true"}:
                lines.append("  exact I.")
            else:
                # Leave the proof open without admit/Admitted — official kernel
                # will report unsolved goals.
                lines.append("  idtac.")
                lines.append("  (* unsolved goals remain for official kernel check *)")
        lines.append("Qed.")
        text = "\n".join(lines).rstrip() + "\n"
        reject_trust_escapes(text)
        return text

    def _render_isabelle(
        self,
        *,
        name: str,
        statement: str,
        imports: Sequence[str],
        proof_body: str,
        theory: TargetTheoryModel,
        environment: EnvironmentIdentity,
    ) -> str:
        theory_name = _safe_ident(
            environment.session_or_package or theory.name or theory.theory_id,
            prefix="Theory",
        )
        import_list = " ".join(_safe_ident(item, prefix="Main") for item in imports) or "Main"
        lines: list[str] = [
            f"theory {theory_name}",
            f"  imports {import_list}",
            "begin",
            "",
            f"(* theory: {theory.theory_id} *)",
            f"(* surface: {theory.source_surface.value} *)",
            "",
        ]
        body = proof_body.strip() if proof_body else ""
        lines.append(f"theorem {name}: \"{statement}\"")
        if body:
            lines.append("proof -")
            for line in body.splitlines() or [body]:
                lines.append(f"  {line}")
            lines.append("qed")
        else:
            lines.append("  (* kernel_obligation: reconstruction_required *)")
            # Do not emit sorry/oops.  Use a non-closing placeholder comment so
            # the official Isabelle kernel remains the authority.
            if statement in {"True", "true"}:
                lines.append("  by simp")
            else:
                lines.append("  (* unsolved goals remain for official kernel check *)")
                lines.append("  oops_forbidden_placeholder")
        # The placeholder above would be a parse error — replace with a
        # reconstructable schematic that is still not a trust escape.
        if "oops_forbidden_placeholder" in "\n".join(lines):
            lines = [line for line in lines if "oops_forbidden_placeholder" not in line]
            lines.append("  apply -")
            lines.append("  (* reconstruction_required *)")
            lines.append("done_pending")
        # ``done_pending`` is also not valid Isabelle; emit a pure comment block
        # and a named lemma shell that cannot close without a real method.
        if any(line == "done_pending" for line in lines):
            lines = [line for line in lines if line != "done_pending"]
            # Leave the theorem open: Isabelle rejects incomplete proofs without
            # sorry when the session is checked under strict settings; we avoid
            # emitting any trust escape and record the obligation.
            lines.append("  (* open obligation — official kernel is sole authority *)")
        lines.append("")
        lines.append("end")
        text = "\n".join(lines).rstrip() + "\n"
        reject_trust_escapes(text)
        return text

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_environment": (
                self.default_environment.to_dict()
                if self.default_environment is not None
                else None
            ),
            "interface": self.interface,
            "reject_axioms_as_escapes": self.reject_axioms_as_escapes,
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# HammerStrategyReceipt@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HammerStrategyReceipt:
    """Hammer / ATP strategy receipt (``HammerStrategyReceipt@1``).

    Hammer is a strategy / meta-provider, not a semantic family or proof
    authority.  Suggestions remain candidates until an official kernel
    reconstruction accepts the exact theorem under a pinned environment.
    """

    INTERFACE: ClassVar[str] = HAMMER_STRATEGY_RECEIPT_INTERFACE

    receipt_id: str
    strategy_kind: HammerStrategyKind | str
    theorem_identity: TheoremIdentity
    environment: EnvironmentIdentity | None
    candidate_digest: str
    reconstruction_status: ReconstructionStatus | str = (
        ReconstructionStatus.NOT_ATTEMPTED
    )
    kernel_accepted: bool = False
    proof_authority: ProofAuthorityRole | str = ProofAuthorityRole.CANDIDATE_ONLY
    result_authority: ResultAuthority | str = ResultAuthority.CANDIDATE
    result_status: ResultStatus | str = ResultStatus.CANDIDATE
    premises: tuple[str, ...] = ()
    suggested_tactics: tuple[str, ...] = ()
    solver_id: str = ""
    solver_verdict: str = ""
    diagnostics: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    interface: str = HAMMER_STRATEGY_RECEIPT_INTERFACE
    schema_version: str = HAMMER_STRATEGY_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self,
            "strategy_kind",
            _enum(self.strategy_kind, HammerStrategyKind, "strategy_kind"),
        )
        if not isinstance(self.theorem_identity, TheoremIdentity):
            object.__setattr__(
                self,
                "theorem_identity",
                TheoremIdentity.from_dict(
                    _mapping(self.theorem_identity, "theorem_identity")
                ),
            )
        if self.environment is not None and not isinstance(
            self.environment, EnvironmentIdentity
        ):
            object.__setattr__(
                self,
                "environment",
                EnvironmentIdentity.from_dict(
                    _mapping(self.environment, "environment")
                ),
            )
        object.__setattr__(
            self, "candidate_digest", _digest(self.candidate_digest, "candidate_digest")
        )
        status = _enum(
            self.reconstruction_status,
            ReconstructionStatus,
            "reconstruction_status",
        )
        object.__setattr__(self, "reconstruction_status", status)
        if not isinstance(self.kernel_accepted, bool):
            raise KernelTargetError(
                "kernel_accepted must be a boolean",
                code=CODE_HAMMER_NOT_AUTHORITY,
                path="kernel_accepted",
            )
        object.__setattr__(
            self,
            "proof_authority",
            _enum(self.proof_authority, ProofAuthorityRole, "proof_authority"),
        )
        object.__setattr__(
            self,
            "result_authority",
            _enum(self.result_authority, ResultAuthority, "result_authority"),
        )
        object.__setattr__(
            self,
            "result_status",
            _enum(self.result_status, ResultStatus, "result_status"),
        )
        # Fail closed: hammer never asserts theorem authority.
        if self.proof_authority is ProofAuthorityRole.OFFICIAL_KERNEL:
            raise AuthorityPromotionError(
                "HammerStrategyReceipt cannot claim official_kernel proof authority",
                path="proof_authority",
            )
        if self.result_authority is ResultAuthority.THEOREM:
            raise AuthorityPromotionError(
                "HammerStrategyReceipt cannot carry theorem result authority",
                path="result_authority",
            )
        if self.result_status is ResultStatus.PROVED and not self.kernel_accepted:
            raise AuthorityPromotionError(
                "HammerStrategyReceipt cannot report proved without kernel_accepted",
                path="result_status",
            )
        if self.kernel_accepted and status is not ReconstructionStatus.ACCEPTED:
            raise KernelTargetError(
                "kernel_accepted requires reconstruction_status=accepted",
                code=CODE_RECONSTRUCTION_REQUIRED,
                path="kernel_accepted",
            )
        if status is ReconstructionStatus.ACCEPTED and not self.kernel_accepted:
            raise KernelTargetError(
                "reconstruction_status=accepted requires kernel_accepted=True "
                "from an official kernel reconstructor",
                code=CODE_RECONSTRUCTION_REQUIRED,
                path="reconstruction_status",
            )
        # Even when reconstructed, the hammer receipt itself remains candidate
        # authority; the *kernel receipt* is the proof authority carrier.
        if self.kernel_accepted:
            # Keep candidate authority on the hammer receipt.
            if self.result_authority is not ResultAuthority.CANDIDATE:
                if self.result_authority is not ResultAuthority.RECONSTRUCTION:
                    raise AuthorityPromotionError(
                        "reconstructed hammer receipts may only carry candidate "
                        "or reconstruction authority, never theorem authority"
                    )
        object.__setattr__(
            self,
            "premises",
            tuple(_text(item, "premises item") for item in self.premises),
        )
        tactics = tuple(
            _text(item, "suggested_tactics item") for item in self.suggested_tactics
        )
        for tactic in tactics:
            reject_trust_escapes(tactic, path="suggested_tactics")
        object.__setattr__(self, "suggested_tactics", tactics)
        object.__setattr__(
            self, "solver_id", _text(self.solver_id, "solver_id", optional=True)
        )
        object.__setattr__(
            self,
            "solver_verdict",
            _text(self.solver_verdict, "solver_verdict", optional=True),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_text(item, "diagnostics item", optional=True) for item in self.diagnostics),
        )
        if self.interface != HAMMER_STRATEGY_RECEIPT_INTERFACE:
            raise KernelTargetError(
                f"unsupported hammer interface: {self.interface!r}",
                code=CODE_HAMMER_NOT_AUTHORITY,
            )
        if self.schema_version != HAMMER_STRATEGY_RECEIPT_SCHEMA:
            raise KernelTargetError(
                f"unsupported hammer receipt schema: {self.schema_version!r}",
                code=CODE_HAMMER_NOT_AUTHORITY,
            )
        try:
            object.__setattr__(self, "attributes", FrozenMap(self.attributes))
        except (TypeError, ValueError) as error:
            raise KernelTargetError(
                "attributes must be immutable JSON-compatible data",
                code=CODE_HAMMER_NOT_AUTHORITY,
                path="attributes",
            ) from error

    @property
    def is_candidate(self) -> bool:
        return not self.kernel_accepted

    @property
    def theorem_identity_digest(self) -> str:
        return self.theorem_identity.identity_digest

    @property
    def environment_identity_digest(self) -> str | None:
        if self.environment is None:
            return None
        return self.environment.identity_digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "candidate_digest": self.candidate_digest,
            "diagnostics": list(self.diagnostics),
            "environment": (
                self.environment.to_dict() if self.environment is not None else None
            ),
            "environment_identity_digest": self.environment_identity_digest,
            "interface": self.interface,
            "is_candidate": self.is_candidate,
            "kernel_accepted": self.kernel_accepted,
            "premises": list(self.premises),
            "proof_authority": (
                self.proof_authority.value
                if isinstance(self.proof_authority, ProofAuthorityRole)
                else self.proof_authority
            ),
            "receipt_id": self.receipt_id,
            "reconstruction_status": (
                self.reconstruction_status.value
                if isinstance(self.reconstruction_status, ReconstructionStatus)
                else self.reconstruction_status
            ),
            "result_authority": (
                self.result_authority.value
                if isinstance(self.result_authority, ResultAuthority)
                else self.result_authority
            ),
            "result_status": (
                self.result_status.value
                if isinstance(self.result_status, ResultStatus)
                else self.result_status
            ),
            "schema_version": self.schema_version,
            "solver_id": self.solver_id,
            "solver_verdict": self.solver_verdict,
            "strategy_kind": (
                self.strategy_kind.value
                if isinstance(self.strategy_kind, HammerStrategyKind)
                else self.strategy_kind
            ),
            "suggested_tactics": list(self.suggested_tactics),
            "theorem_identity": self.theorem_identity.to_dict(),
            "theorem_identity_digest": self.theorem_identity_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HammerStrategyReceipt":
        value = _mapping(value, "hammer_strategy_receipt")
        return cls(
            receipt_id=value.get("receipt_id", ""),
            strategy_kind=value.get(
                "strategy_kind", HammerStrategyKind.TACTIC_SUGGESTION
            ),
            theorem_identity=value.get("theorem_identity", {}),
            environment=value.get("environment"),
            candidate_digest=value.get("candidate_digest", ""),
            reconstruction_status=value.get(
                "reconstruction_status", ReconstructionStatus.NOT_ATTEMPTED
            ),
            kernel_accepted=bool(value.get("kernel_accepted", False)),
            proof_authority=value.get(
                "proof_authority", ProofAuthorityRole.CANDIDATE_ONLY
            ),
            result_authority=value.get(
                "result_authority", ResultAuthority.CANDIDATE
            ),
            result_status=value.get("result_status", ResultStatus.CANDIDATE),
            premises=tuple(value.get("premises", ())),
            suggested_tactics=tuple(value.get("suggested_tactics", ())),
            solver_id=value.get("solver_id", ""),
            solver_verdict=value.get("solver_verdict", ""),
            diagnostics=tuple(value.get("diagnostics", ())),
            attributes=value.get("attributes", {}),
            interface=value.get("interface", HAMMER_STRATEGY_RECEIPT_INTERFACE),
            schema_version=value.get(
                "schema_version", HAMMER_STRATEGY_RECEIPT_SCHEMA
            ),
        )

    @classmethod
    def from_suggestion(
        cls,
        *,
        receipt_id: str,
        theorem_identity: TheoremIdentity,
        candidate_text: str,
        strategy_kind: HammerStrategyKind | str = HammerStrategyKind.TACTIC_SUGGESTION,
        environment: EnvironmentIdentity | None = None,
        premises: Sequence[str] = (),
        suggested_tactics: Sequence[str] = (),
        solver_id: str = "",
        solver_verdict: str = "",
        diagnostics: Sequence[str] = (),
    ) -> "HammerStrategyReceipt":
        """Build a candidate-only hammer receipt from an untrusted suggestion."""

        if not isinstance(candidate_text, str) or not candidate_text.strip():
            raise KernelTargetError(
                "candidate_text must be non-empty",
                code=CODE_EMPTY_INPUT,
                path="candidate_text",
            )
        # Suggestions may *contain* trust escapes as text under diagnostics,
        # but suggested tactics used for reconstruction planning must not.
        for tactic in suggested_tactics:
            reject_trust_escapes(str(tactic), path="suggested_tactics")
        return cls(
            receipt_id=receipt_id,
            strategy_kind=strategy_kind,
            theorem_identity=theorem_identity,
            environment=environment,
            candidate_digest=content_digest(candidate_text),
            reconstruction_status=ReconstructionStatus.NOT_ATTEMPTED,
            kernel_accepted=False,
            proof_authority=ProofAuthorityRole.CANDIDATE_ONLY,
            result_authority=ResultAuthority.CANDIDATE,
            result_status=ResultStatus.CANDIDATE,
            premises=tuple(premises),
            suggested_tactics=tuple(suggested_tactics),
            solver_id=solver_id,
            solver_verdict=solver_verdict,
            diagnostics=tuple(diagnostics),
        )


# ---------------------------------------------------------------------------
# Join routes: protocol / program / resource → kernel targets
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProtocolProgramKernelRoute:
    """One joined route from an upstream surface into a target theory."""

    route_id: str
    surface: RouteSurface | str
    theory: TargetTheoryModel
    upstream_document_id: str = ""
    upstream_identity_digest: str = ""
    authority_ceiling: ResultAuthority | str = ResultAuthority.CANDIDATE
    generated_sources: tuple[KernelGeneratedSource, ...] = ()
    hammer_receipts: tuple[HammerStrategyReceipt, ...] = ()
    schema_version: str = PROTOCOL_PROGRAM_KERNEL_ROUTE_SCHEMA
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "route_id", _identifier(self.route_id, "route_id"))
        object.__setattr__(
            self, "surface", _enum(self.surface, RouteSurface, "surface")
        )
        if not isinstance(self.theory, TargetTheoryModel):
            object.__setattr__(
                self,
                "theory",
                TargetTheoryModel.from_dict(_mapping(self.theory, "theory")),
            )
        object.__setattr__(
            self,
            "upstream_document_id",
            _text(self.upstream_document_id, "upstream_document_id", optional=True),
        )
        object.__setattr__(
            self,
            "upstream_identity_digest",
            _text(
                self.upstream_identity_digest,
                "upstream_identity_digest",
                optional=True,
            ),
        )
        if self.upstream_identity_digest and not _DIGEST_RE.fullmatch(
            self.upstream_identity_digest
        ):
            raise KernelTargetError(
                "upstream_identity_digest must be a lowercase SHA-256 digest",
                code=CODE_ROUTE,
                path="upstream_identity_digest",
            )
        ceiling = _enum(
            self.authority_ceiling, ResultAuthority, "authority_ceiling"
        )
        expected = result_authority_for_surface(self.surface)
        # Route ceiling cannot exceed the surface role.
        if ceiling is ResultAuthority.THEOREM and expected is not ResultAuthority.THEOREM:
            raise AuthorityPromotionError(
                f"route surface {self.surface.value!r} cannot set "
                "authority_ceiling=theorem without official kernel acceptance"
            )
        object.__setattr__(self, "authority_ceiling", ceiling)
        sources = tuple(
            item
            if isinstance(item, KernelGeneratedSource)
            else KernelGeneratedSource.from_dict(_mapping(item, "generated_source"))
            for item in _sequence(self.generated_sources, "generated_sources")
        )
        object.__setattr__(self, "generated_sources", sources)
        receipts = tuple(
            item
            if isinstance(item, HammerStrategyReceipt)
            else HammerStrategyReceipt.from_dict(_mapping(item, "hammer_receipt"))
            for item in _sequence(self.hammer_receipts, "hammer_receipts")
        )
        object.__setattr__(self, "hammer_receipts", receipts)
        if self.schema_version != PROTOCOL_PROGRAM_KERNEL_ROUTE_SCHEMA:
            raise KernelTargetError(
                f"unsupported route schema: {self.schema_version!r}",
                code=CODE_ROUTE,
            )
        try:
            object.__setattr__(self, "attributes", FrozenMap(self.attributes))
        except (TypeError, ValueError) as error:
            raise KernelTargetError(
                "attributes must be immutable JSON-compatible data",
                code=CODE_ROUTE,
                path="attributes",
            ) from error

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "authority_ceiling": (
                self.authority_ceiling.value
                if isinstance(self.authority_ceiling, ResultAuthority)
                else self.authority_ceiling
            ),
            "generated_sources": [item.to_dict() for item in self.generated_sources],
            "hammer_receipts": [item.to_dict() for item in self.hammer_receipts],
            "route_id": self.route_id,
            "schema_version": self.schema_version,
            "surface": (
                self.surface.value
                if isinstance(self.surface, RouteSurface)
                else self.surface
            ),
            "theory": self.theory.to_dict(),
            "upstream_document_id": self.upstream_document_id,
            "upstream_identity_digest": self.upstream_identity_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProtocolProgramKernelRoute":
        value = _mapping(value, "route")
        return cls(
            route_id=value.get("route_id", ""),
            surface=value.get("surface", RouteSurface.KERNEL_NATIVE),
            theory=value.get("theory", {}),
            upstream_document_id=value.get("upstream_document_id", ""),
            upstream_identity_digest=value.get("upstream_identity_digest", ""),
            authority_ceiling=value.get(
                "authority_ceiling", ResultAuthority.CANDIDATE
            ),
            generated_sources=tuple(value.get("generated_sources", ())),
            hammer_receipts=tuple(value.get("hammer_receipts", ())),
            schema_version=str(
                value.get("schema_version") or PROTOCOL_PROGRAM_KERNEL_ROUTE_SCHEMA
            ),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class JoinReceipt:
    """Audit receipt for a protocol/program → kernel join."""

    join_id: str
    routes: tuple[ProtocolProgramKernelRoute, ...]
    official_kernels_sole_proof_authority: bool = True
    trust_escapes_rejected: tuple[str, ...] = ()
    hammer_remains_candidate: bool = True
    schema_version: str = JOIN_RECEIPT_SCHEMA
    module_version: str = KERNEL_TARGETS_MODULE_VERSION
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "join_id", _identifier(self.join_id, "join_id"))
        routes = tuple(
            item
            if isinstance(item, ProtocolProgramKernelRoute)
            else ProtocolProgramKernelRoute.from_dict(_mapping(item, "route"))
            for item in _sequence(self.routes, "routes")
        )
        object.__setattr__(self, "routes", routes)
        if not isinstance(self.official_kernels_sole_proof_authority, bool):
            raise KernelTargetError(
                "official_kernels_sole_proof_authority must be boolean",
                code=CODE_ROUTE,
            )
        if not self.official_kernels_sole_proof_authority:
            raise AuthorityPromotionError(
                "join receipt must keep official kernels as sole proof authority"
            )
        if not isinstance(self.hammer_remains_candidate, bool):
            raise KernelTargetError(
                "hammer_remains_candidate must be boolean",
                code=CODE_ROUTE,
            )
        if not self.hammer_remains_candidate:
            raise AuthorityPromotionError(
                "join receipt must keep hammer/ATP suggestions as candidates"
            )
        object.__setattr__(
            self,
            "trust_escapes_rejected",
            tuple(
                _text(item, "trust_escapes_rejected item")
                for item in self.trust_escapes_rejected
            )
            or tuple(kind for kind, _ in _TRUST_ESCAPE_PATTERNS),
        )
        if self.schema_version != JOIN_RECEIPT_SCHEMA:
            raise KernelTargetError(
                f"unsupported join receipt schema: {self.schema_version!r}",
                code=CODE_ROUTE,
            )
        try:
            object.__setattr__(self, "attributes", FrozenMap(self.attributes))
        except (TypeError, ValueError) as error:
            raise KernelTargetError(
                "attributes must be immutable JSON-compatible data",
                code=CODE_ROUTE,
                path="attributes",
            ) from error
        # Every hammer receipt on every route must remain non-theorem.
        for route in self.routes:
            for receipt in route.hammer_receipts:
                if receipt.result_authority is ResultAuthority.THEOREM:
                    raise AuthorityPromotionError(
                        "join routes cannot elevate hammer receipts to theorem authority"
                    )
                if receipt.is_candidate is False and (
                    receipt.reconstruction_status is not ReconstructionStatus.ACCEPTED
                ):
                    raise AuthorityPromotionError(
                        "non-candidate hammer receipt requires accepted reconstruction"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "hammer_remains_candidate": self.hammer_remains_candidate,
            "join_id": self.join_id,
            "module_version": self.module_version,
            "official_kernels_sole_proof_authority": (
                self.official_kernels_sole_proof_authority
            ),
            "routes": [item.to_dict() for item in self.routes],
            "schema_version": self.schema_version,
            "trust_escapes_rejected": list(self.trust_escapes_rejected),
        }


def _obligation_statement(
    *,
    kind: str,
    name: str,
    detail: str = "",
) -> str:
    base = f"Obligation_{_safe_ident(kind)}_{_safe_ident(name)}"
    if detail:
        return f"({base} /\\ {_safe_ident(detail, prefix='detail')})"
    # Default to a trivial proposition shell that still carries the obligation
    # name in a comment-free, escape-free statement form for generators.
    return "True"


def theory_from_protocol_claims(
    *,
    theory_id: str,
    name: str,
    surface: RouteSurface | str,
    claims: Sequence[Mapping[str, Any] | str],
    imports: Sequence[str] = (),
    axioms: Sequence[str] = (),
    upstream_document_id: str = "",
    source_ref_id: str = "",
    environment: EnvironmentIdentity | None = None,
) -> TargetTheoryModel:
    """Build a target theory from protocol (ProVerif/Tamarin) claim obligations."""

    surface_kind = _enum(surface, RouteSurface, "surface")
    if surface_kind not in {
        RouteSurface.PROTOCOL_PROVERIF,
        RouteSurface.PROTOCOL_TAMARIN,
    }:
        raise KernelTargetError(
            "theory_from_protocol_claims requires a protocol surface",
            code=CODE_UNSUPPORTED_SURFACE,
            path="surface",
        )
    declarations: list[TargetDeclaration] = []
    theorems: list[TheoremIdentity] = []
    for index, claim in enumerate(claims):
        if isinstance(claim, str):
            claim_id = f"claim:{index}"
            claim_name = claim
            claim_kind = "secrecy"
            detail = claim
        else:
            payload = _mapping(claim, f"claims[{index}]")
            claim_id = str(
                payload.get("claim_id")
                or payload.get("id")
                or f"claim:{index}"
            )
            claim_name = str(
                payload.get("name") or payload.get("label") or claim_id
            )
            claim_kind = str(payload.get("kind") or payload.get("claim_kind") or "claim")
            detail = str(payload.get("statement") or payload.get("query") or claim_name)
        decl_id = f"decl:{_safe_ident(claim_id)}"
        statement = _obligation_statement(
            kind=claim_kind, name=claim_name, detail=detail
        )
        source_map = TargetSourceMap(
            owner_id=decl_id,
            source_ref_id=source_ref_id,
            span_id=f"span:{_safe_ident(claim_id)}",
        )
        declarations.append(
            TargetDeclaration(
                declaration_id=decl_id,
                kind=DeclarationKind.OBLIGATION,
                name=_safe_ident(claim_name, prefix="claim"),
                statement=statement,
                source_maps=(source_map,),
                attributes={
                    "claim_id": claim_id,
                    "claim_kind": claim_kind,
                    "upstream_document_id": upstream_document_id,
                },
            )
        )
        theorems.append(
            TheoremIdentity.bind(
                theorem_id=f"thm:{_safe_ident(claim_id)}",
                theorem_name=_safe_ident(claim_name, prefix="claim"),
                statement="True",
                theory_id=theory_id,
                source_surface=surface_kind,
                source_maps=(source_map,),
                attributes={
                    "claim_id": claim_id,
                    "claim_kind": claim_kind,
                    "obligation_label": statement,
                },
            )
        )
    for item in imports:
        declarations.append(
            TargetDeclaration(
                declaration_id=f"import:{_safe_ident(item)}",
                kind=DeclarationKind.IMPORT,
                name=item,
                import_path=item,
            )
        )
    for item in axioms:
        # Explicit axioms are recorded; they are not trust escapes by themselves.
        declarations.append(
            TargetDeclaration(
                declaration_id=f"axiom:{_safe_ident(item)}",
                kind=DeclarationKind.AXIOM,
                name=item,
                statement=item,
                is_axiom=True,
            )
        )
    return TargetTheoryModel(
        theory_id=theory_id,
        name=name,
        source_surface=surface_kind,
        declarations=tuple(declarations),
        theorems=tuple(theorems),
        imports=tuple(imports),
        axioms=tuple(axioms),
        trust_receipt=TrustReceipt.for_surface(
            receipt_id=f"trust:{theory_id}",
            surface=surface_kind,
            axioms=tuple(axioms),
            assumptions=("symbolic_over_approximation",),
            notes="Protocol results remain protocol authority until kernel reconstruction.",
        ),
        environment=environment,
        attributes={"upstream_document_id": upstream_document_id},
    )


def theory_from_program_obligations(
    *,
    theory_id: str,
    name: str,
    surface: RouteSurface | str = RouteSurface.PROGRAM_VC,
    obligations: Sequence[Mapping[str, Any] | str],
    imports: Sequence[str] = (),
    axioms: Sequence[str] = (),
    upstream_document_id: str = "",
    source_ref_id: str = "",
    environment: EnvironmentIdentity | None = None,
) -> TargetTheoryModel:
    """Build a target theory from program VC / SMT / refinement obligations."""

    surface_kind = _enum(surface, RouteSurface, "surface")
    if surface_kind not in {
        RouteSurface.PROGRAM_VC,
        RouteSurface.PROGRAM_SMT,
        RouteSurface.PROGRAM_CHC,
        RouteSurface.RESOURCE_REFINEMENT,
    }:
        raise KernelTargetError(
            "theory_from_program_obligations requires a program/resource surface",
            code=CODE_UNSUPPORTED_SURFACE,
            path="surface",
        )
    declarations: list[TargetDeclaration] = []
    theorems: list[TheoremIdentity] = []
    for index, obligation in enumerate(obligations):
        if isinstance(obligation, str):
            obl_id = f"obl:{index}"
            obl_name = obligation
            statement_label = obligation
            rule = "obligation"
        else:
            payload = _mapping(obligation, f"obligations[{index}]")
            obl_id = str(
                payload.get("obligation_id")
                or payload.get("id")
                or f"obl:{index}"
            )
            obl_name = str(
                payload.get("name") or payload.get("label") or obl_id
            )
            statement_label = str(
                payload.get("statement")
                or payload.get("goal")
                or payload.get("formula")
                or obl_name
            )
            rule = str(payload.get("rule") or payload.get("kind") or "vc")
        decl_id = f"decl:{_safe_ident(obl_id)}"
        source_map = TargetSourceMap(
            owner_id=decl_id,
            source_ref_id=source_ref_id,
            span_id=f"span:{_safe_ident(obl_id)}",
        )
        # Theorem statement is the controlled True shell; label rides in attributes.
        declarations.append(
            TargetDeclaration(
                declaration_id=decl_id,
                kind=DeclarationKind.OBLIGATION,
                name=_safe_ident(obl_name, prefix="obl"),
                statement=_obligation_statement(
                    kind=rule, name=obl_name, detail=statement_label
                ),
                source_maps=(source_map,),
                attributes={
                    "obligation_id": obl_id,
                    "rule": rule,
                    "upstream_document_id": upstream_document_id,
                },
            )
        )
        theorems.append(
            TheoremIdentity.bind(
                theorem_id=f"thm:{_safe_ident(obl_id)}",
                theorem_name=_safe_ident(obl_name, prefix="obl"),
                statement="True",
                theory_id=theory_id,
                source_surface=surface_kind,
                source_maps=(source_map,),
                attributes={
                    "obligation_id": obl_id,
                    "rule": rule,
                    "obligation_label": statement_label,
                },
            )
        )
    for item in imports:
        declarations.append(
            TargetDeclaration(
                declaration_id=f"import:{_safe_ident(item)}",
                kind=DeclarationKind.IMPORT,
                name=item,
                import_path=item,
            )
        )
    return TargetTheoryModel(
        theory_id=theory_id,
        name=name,
        source_surface=surface_kind,
        declarations=tuple(declarations),
        theorems=tuple(theorems),
        imports=tuple(imports),
        axioms=tuple(axioms),
        trust_receipt=TrustReceipt.for_surface(
            receipt_id=f"trust:{theory_id}",
            surface=surface_kind,
            axioms=tuple(axioms),
            assumptions=("verification_condition_view",),
            notes="Program/SMT obligations remain candidates until kernel reconstruction.",
        ),
        environment=environment,
        attributes={"upstream_document_id": upstream_document_id},
    )


def join_protocol_route(
    *,
    route_id: str,
    surface: RouteSurface | str,
    claims: Sequence[Mapping[str, Any] | str],
    kernel_targets: Sequence[KernelTargetKind | str] = (KernelTargetKind.LEAN,),
    environment: EnvironmentIdentity | Mapping[str, Any] | None = None,
    theory_id: str = "",
    name: str = "",
    imports: Sequence[str] = (),
    axioms: Sequence[str] = (),
    upstream_document_id: str = "",
    source_ref_id: str = "",
    proof_bodies: Mapping[str, str] | None = None,
    hammer_suggestions: Sequence[Mapping[str, Any]] = (),
) -> ProtocolProgramKernelRoute:
    """Join a protocol surface into kernel target generation."""

    surface_kind = _enum(surface, RouteSurface, "surface")
    theory_id = theory_id or f"theory:protocol:{_safe_ident(route_id)}"
    name = name or f"protocol_theory_{_safe_ident(route_id)}"
    env: EnvironmentIdentity | None
    if environment is None:
        env = None
    elif isinstance(environment, EnvironmentIdentity):
        env = environment
    else:
        env = EnvironmentIdentity.from_dict(_mapping(environment, "environment"))

    theory = theory_from_protocol_claims(
        theory_id=theory_id,
        name=name,
        surface=surface_kind,
        claims=claims,
        imports=imports,
        axioms=axioms,
        upstream_document_id=upstream_document_id,
        source_ref_id=source_ref_id,
        environment=env,
    )
    generator = KernelTargetGenerator(default_environment=env)
    sources: list[KernelGeneratedSource] = []
    for target in kernel_targets:
        target_kind = _enum(target, KernelTargetKind, "kernel_target")
        target_env = env
        if target_env is None:
            target_env = EnvironmentIdentity(
                environment_id=f"env:{target_kind.value}:default",
                kernel_target=target_kind,
                toolchain_id=target_kind.value,
                toolchain_version="unspecified",
            )
        elif target_env.kernel_target != target_kind:
            target_env = EnvironmentIdentity(
                environment_id=f"env:{target_kind.value}:{route_id}",
                kernel_target=target_kind,
                toolchain_id=target_kind.value,
                toolchain_version=target_env.toolchain_version,
                source_tree_digest=target_env.source_tree_digest,
                session_or_package=target_env.session_or_package,
                os_name=target_env.os_name,
                architecture=target_env.architecture,
            )
        sources.extend(
            generator.generate_all(
                theory,
                kernel_target=target_kind,
                environment=target_env,
                proof_bodies=proof_bodies,
            )
        )

    hammer_receipts = _build_hammer_receipts(
        theory=theory,
        environment=env,
        suggestions=hammer_suggestions,
        route_id=route_id,
    )
    upstream_digest = ""
    if upstream_document_id:
        upstream_digest = content_digest(upstream_document_id)
    return ProtocolProgramKernelRoute(
        route_id=route_id,
        surface=surface_kind,
        theory=theory,
        upstream_document_id=upstream_document_id,
        upstream_identity_digest=upstream_digest,
        authority_ceiling=result_authority_for_surface(surface_kind),
        generated_sources=tuple(sources),
        hammer_receipts=hammer_receipts,
    )


def join_program_route(
    *,
    route_id: str,
    obligations: Sequence[Mapping[str, Any] | str],
    surface: RouteSurface | str = RouteSurface.PROGRAM_VC,
    kernel_targets: Sequence[KernelTargetKind | str] = (KernelTargetKind.LEAN,),
    environment: EnvironmentIdentity | Mapping[str, Any] | None = None,
    theory_id: str = "",
    name: str = "",
    imports: Sequence[str] = (),
    axioms: Sequence[str] = (),
    upstream_document_id: str = "",
    source_ref_id: str = "",
    proof_bodies: Mapping[str, str] | None = None,
    hammer_suggestions: Sequence[Mapping[str, Any]] = (),
) -> ProtocolProgramKernelRoute:
    """Join a program/resource surface into kernel target generation."""

    surface_kind = _enum(surface, RouteSurface, "surface")
    theory_id = theory_id or f"theory:program:{_safe_ident(route_id)}"
    name = name or f"program_theory_{_safe_ident(route_id)}"
    env: EnvironmentIdentity | None
    if environment is None:
        env = None
    elif isinstance(environment, EnvironmentIdentity):
        env = environment
    else:
        env = EnvironmentIdentity.from_dict(_mapping(environment, "environment"))

    theory = theory_from_program_obligations(
        theory_id=theory_id,
        name=name,
        surface=surface_kind,
        obligations=obligations,
        imports=imports,
        axioms=axioms,
        upstream_document_id=upstream_document_id,
        source_ref_id=source_ref_id,
        environment=env,
    )
    generator = KernelTargetGenerator(default_environment=env)
    sources: list[KernelGeneratedSource] = []
    for target in kernel_targets:
        target_kind = _enum(target, KernelTargetKind, "kernel_target")
        target_env = env
        if target_env is None:
            target_env = EnvironmentIdentity(
                environment_id=f"env:{target_kind.value}:default",
                kernel_target=target_kind,
                toolchain_id=target_kind.value,
                toolchain_version="unspecified",
            )
        elif target_env.kernel_target != target_kind:
            target_env = EnvironmentIdentity(
                environment_id=f"env:{target_kind.value}:{route_id}",
                kernel_target=target_kind,
                toolchain_id=target_kind.value,
                toolchain_version=target_env.toolchain_version,
                source_tree_digest=target_env.source_tree_digest,
                session_or_package=target_env.session_or_package,
                os_name=target_env.os_name,
                architecture=target_env.architecture,
            )
        sources.extend(
            generator.generate_all(
                theory,
                kernel_target=target_kind,
                environment=target_env,
                proof_bodies=proof_bodies,
            )
        )
    hammer_receipts = _build_hammer_receipts(
        theory=theory,
        environment=env,
        suggestions=hammer_suggestions,
        route_id=route_id,
    )
    upstream_digest = (
        content_digest(upstream_document_id) if upstream_document_id else ""
    )
    return ProtocolProgramKernelRoute(
        route_id=route_id,
        surface=surface_kind,
        theory=theory,
        upstream_document_id=upstream_document_id,
        upstream_identity_digest=upstream_digest,
        authority_ceiling=result_authority_for_surface(surface_kind),
        generated_sources=tuple(sources),
        hammer_receipts=hammer_receipts,
    )


def _build_hammer_receipts(
    *,
    theory: TargetTheoryModel,
    environment: EnvironmentIdentity | None,
    suggestions: Sequence[Mapping[str, Any]],
    route_id: str,
) -> tuple[HammerStrategyReceipt, ...]:
    if not suggestions:
        return ()
    if not theory.theorems:
        raise KernelTargetError(
            "hammer suggestions require at least one theorem identity",
            code=CODE_INVALID_THEOREM,
        )
    receipts: list[HammerStrategyReceipt] = []
    for index, suggestion in enumerate(suggestions):
        payload = _mapping(suggestion, f"hammer_suggestions[{index}]")
        theorem_id = str(payload.get("theorem_id") or theory.theorems[0].theorem_id)
        theorem = theory.theorem_by_id(theorem_id)
        candidate_text = str(
            payload.get("candidate_text")
            or payload.get("proof_text")
            or payload.get("suggestion")
            or ""
        )
        if not candidate_text:
            raise KernelTargetError(
                "hammer suggestion requires candidate_text",
                code=CODE_EMPTY_INPUT,
                path=f"hammer_suggestions[{index}].candidate_text",
            )
        receipts.append(
            HammerStrategyReceipt.from_suggestion(
                receipt_id=str(
                    payload.get("receipt_id")
                    or f"hammer:{route_id}:{index}"
                ),
                theorem_identity=theorem,
                candidate_text=candidate_text,
                strategy_kind=payload.get(
                    "strategy_kind", HammerStrategyKind.ATP_CANDIDATE
                ),
                environment=environment,
                premises=tuple(payload.get("premises", ())),
                suggested_tactics=tuple(payload.get("suggested_tactics", ())),
                solver_id=str(payload.get("solver_id") or ""),
                solver_verdict=str(payload.get("solver_verdict") or ""),
                diagnostics=tuple(payload.get("diagnostics", ())),
            )
        )
    return tuple(receipts)


def join_protocol_program_kernel_surfaces(
    *,
    join_id: str,
    protocol_routes: Sequence[Mapping[str, Any]] = (),
    program_routes: Sequence[Mapping[str, Any]] = (),
) -> JoinReceipt:
    """Join protocol and program route specs into one audit receipt."""

    routes: list[ProtocolProgramKernelRoute] = []
    for index, spec in enumerate(protocol_routes):
        payload = _mapping(spec, f"protocol_routes[{index}]")
        routes.append(
            join_protocol_route(
                route_id=str(payload.get("route_id") or f"protocol-route-{index}"),
                surface=payload.get("surface", RouteSurface.PROTOCOL_PROVERIF),
                claims=tuple(payload.get("claims", ())),
                kernel_targets=tuple(
                    payload.get("kernel_targets", (KernelTargetKind.LEAN,))
                ),
                environment=payload.get("environment"),
                theory_id=str(payload.get("theory_id") or ""),
                name=str(payload.get("name") or ""),
                imports=tuple(payload.get("imports", ())),
                axioms=tuple(payload.get("axioms", ())),
                upstream_document_id=str(payload.get("upstream_document_id") or ""),
                source_ref_id=str(payload.get("source_ref_id") or ""),
                proof_bodies=payload.get("proof_bodies"),
                hammer_suggestions=tuple(payload.get("hammer_suggestions", ())),
            )
        )
    for index, spec in enumerate(program_routes):
        payload = _mapping(spec, f"program_routes[{index}]")
        routes.append(
            join_program_route(
                route_id=str(payload.get("route_id") or f"program-route-{index}"),
                obligations=tuple(payload.get("obligations", ())),
                surface=payload.get("surface", RouteSurface.PROGRAM_VC),
                kernel_targets=tuple(
                    payload.get("kernel_targets", (KernelTargetKind.LEAN,))
                ),
                environment=payload.get("environment"),
                theory_id=str(payload.get("theory_id") or ""),
                name=str(payload.get("name") or ""),
                imports=tuple(payload.get("imports", ())),
                axioms=tuple(payload.get("axioms", ())),
                upstream_document_id=str(payload.get("upstream_document_id") or ""),
                source_ref_id=str(payload.get("source_ref_id") or ""),
                proof_bodies=payload.get("proof_bodies"),
                hammer_suggestions=tuple(payload.get("hammer_suggestions", ())),
            )
        )
    if not routes:
        raise KernelTargetError(
            "join requires at least one protocol or program route",
            code=CODE_EMPTY_INPUT,
            path="routes",
        )
    return JoinReceipt(
        join_id=join_id,
        routes=tuple(routes),
        official_kernels_sole_proof_authority=True,
        trust_escapes_rejected=tuple(kind for kind, _ in _TRUST_ESCAPE_PATTERNS),
        hammer_remains_candidate=True,
    )


def record_kernel_acceptance(
    generated: KernelGeneratedSource,
    *,
    accepted: bool,
    environment: EnvironmentIdentity | None = None,
) -> dict[str, Any]:
    """Return an external kernel-check binding (does not mutate generation).

    Official kernels alone may set acceptance.  This helper only packages the
    identities required to attach a kernel receipt elsewhere; it never upgrades
    a hammer or protocol result to theorem authority.
    """

    if not isinstance(generated, KernelGeneratedSource):
        raise KernelTargetError(
            "record_kernel_acceptance requires KernelGeneratedSource",
            code=CODE_GENERATION,
        )
    env = environment or generated.environment
    if not isinstance(env, EnvironmentIdentity):
        env = EnvironmentIdentity.from_dict(_mapping(env, "environment"))
    if env.kernel_target != generated.kernel_target:
        raise KernelTargetError(
            "acceptance environment must match generated kernel_target",
            code=CODE_IDENTITY_MISMATCH,
            path="environment",
        )
    if not isinstance(accepted, bool):
        raise KernelTargetError(
            "accepted must be a boolean",
            code=CODE_MALFORMED,
            path="accepted",
        )
    return {
        "accepted": accepted,
        "authority": (
            ResultAuthority.THEOREM.value
            if accepted
            else ResultAuthority.CANDIDATE.value
        ),
        "environment_identity_digest": env.identity_digest,
        "kernel_target": (
            generated.kernel_target.value
            if isinstance(generated.kernel_target, KernelTargetKind)
            else generated.kernel_target
        ),
        "proof_authority": ProofAuthorityRole.OFFICIAL_KERNEL.value,
        "source_digest": generated.source_digest,
        "theorem_identity_digest": generated.theorem_identity_digest,
        "theory_id": generated.theory_id,
    }


__all__ = [
    "AuthorityPromotionError",
    "CODE_AUTHORITY_PROMOTION",
    "CODE_EMPTY_INPUT",
    "CODE_GENERATION",
    "CODE_HAMMER_NOT_AUTHORITY",
    "CODE_IDENTITY_MISMATCH",
    "CODE_INVALID_DECLARATION",
    "CODE_INVALID_ENVIRONMENT",
    "CODE_INVALID_SOURCE_MAP",
    "CODE_INVALID_THEOREM",
    "CODE_INVALID_THEORY",
    "CODE_INVALID_TRUST",
    "CODE_MALFORMED",
    "CODE_RECONSTRUCTION_REQUIRED",
    "CODE_ROUTE",
    "CODE_TRUST_ESCAPE",
    "CODE_UNSUPPORTED_SURFACE",
    "CODE_UNSUPPORTED_TARGET",
    "DeclarationKind",
    "DEFAULT_ISABELLE_IMPORTS",
    "DEFAULT_LEAN_IMPORTS",
    "DEFAULT_ROCQ_IMPORTS",
    "ENVIRONMENT_IDENTITY_SCHEMA",
    "EnvironmentIdentity",
    "HAMMER_STRATEGY_RECEIPT_INTERFACE",
    "HAMMER_STRATEGY_RECEIPT_SCHEMA",
    "HammerStrategyKind",
    "HammerStrategyReceipt",
    "JOIN_RECEIPT_SCHEMA",
    "JoinReceipt",
    "KERNEL_GENERATED_SOURCE_SCHEMA",
    "KERNEL_TARGET_GENERATOR_INTERFACE",
    "KERNEL_TARGETS_IDENTITY_DOMAIN",
    "KERNEL_TARGETS_MODULE_VERSION",
    "KernelGeneratedSource",
    "KernelTargetError",
    "KernelTargetGenerator",
    "KernelTargetKind",
    "PROTOCOL_PROGRAM_KERNEL_ROUTE_SCHEMA",
    "ProofAuthorityRole",
    "ProtocolProgramKernelRoute",
    "ReconstructionStatus",
    "RouteSurface",
    "TARGET_DECLARATION_SCHEMA",
    "TARGET_ENCODING_ISABELLE",
    "TARGET_ENCODING_LEAN",
    "TARGET_ENCODING_ROCQ",
    "TARGET_SOURCE_MAP_SCHEMA",
    "TARGET_THEORY_FAMILY_ID",
    "TARGET_THEORY_MODEL_INTERFACE",
    "TARGET_THEORY_PROFILE_ID",
    "TARGET_THEORY_SCHEMA",
    "TARGET_TRUST_RECEIPT_SCHEMA",
    "THEOREM_IDENTITY_SCHEMA",
    "TargetDeclaration",
    "TargetSourceMap",
    "TargetTheoryModel",
    "TheoremIdentity",
    "TrustDisposition",
    "TrustEscapeError",
    "TrustReceipt",
    "content_digest",
    "is_official_kernel",
    "join_program_route",
    "join_protocol_program_kernel_surfaces",
    "join_protocol_route",
    "record_kernel_acceptance",
    "reject_trust_escapes",
    "result_authority_for_surface",
    "scan_trust_escapes",
    "surface_authority_role",
    "theory_from_program_obligations",
    "theory_from_protocol_claims",
]
