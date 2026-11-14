"""PAAR MPEP / 37 C.F.R. obligation catalog (PAAR-050 / PAAR-G060).

Versioned, content-addressed obligations mapping statute / regulation /
guidance cites to applicability filters, evidence predicates, severities,
and fail-closed behavior for package conformance evaluation.

Design invariants
-----------------
* **Not legal advice**; not a completeness or patentability certification.
* Never signs, pays, files, or mutates a docket.
* **MPEP is guidance tier** — never silently elevated above 37 C.F.R. or
  Title 35 (statute). Controlling authority wins when present.
* Unknown authority or missing catalog entry → ``unknown`` status (fail closed).
* Form instructions are not controlling law.
* Catalog content is content-addressed (sha256 of canonical obligation set).

Conflict policy (PAAR-050): own obligation_catalog* only; import
filing_rule_packs read-only when seeding helpers need them.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------

OBLIGATION_CATALOG_SCHEMA: Final = "paar.obligation-catalog.v1"
OBLIGATION_CATALOG_INTERFACE: Final = "ObligationCatalog@1"
OBLIGATION_CATALOG_CODE_VERSION: Final = "1.1.0"
SEED_CATALOG_ID: Final = "paar.obligation-catalog.seed"
SEED_CATALOG_VERSION: Final = "1.1.0"

SEED_FILENAME: Final = "obligation_catalog_seed.json"

REVIEW_ONLY_CATALOG_DISCLAIMER: Final = (
    "This obligation catalog is a versioned decision-support draft pending independent review "
    "for package conformance screening. It is not legal advice, not a "
    "completeness certification, and does not authorize filing, payment, "
    "signature, or docket mutation. MPEP entries are guidance tier and are "
    "never silently elevated above 37 C.F.R. or Title 35. Form instructions "
    "are not controlling law. Unknown authority fails closed to unknown. "
    "Named human review is required before any export or assurance disposition."
)

_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")

# Authority tier ordering (higher = more controlling). MPEP is lowest.
AUTHORITY_TIER_RANK: Final[Mapping[str, int]] = MappingProxyType(
    {
        "statute": 100,
        "regulation": 80,
        "guidance": 20,
        "form_instruction": 10,
        "unknown": 0,
    }
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class AuthorityTier(str, Enum):
    """Legal authority tier — MPEP is guidance, never above CFR/statute."""

    STATUTE = "statute"
    REGULATION = "regulation"
    GUIDANCE = "guidance"  # MPEP and similar
    FORM_INSTRUCTION = "form_instruction"
    UNKNOWN = "unknown"


class ObligationSeverity(str, Enum):
    BLOCKING = "blocking"
    MAJOR = "major"
    MINOR = "minor"
    INFORMATIONAL = "informational"
    HUMAN_ONLY = "human_only"


class FailClosedBehavior(str, Enum):
    """What to do when evidence or authority is missing."""

    UNKNOWN = "unknown"
    UNSATISFIED = "unsatisfied"
    HUMAN_ONLY = "human_only"
    REVIEW_REQUIRED = "review_required"


class ApplicationTypeScope(str, Enum):
    UTILITY = "utility"
    DESIGN = "design"
    PLANT = "plant"
    ANY = "any"
    UNKNOWN = "unknown"


class ScenarioScope(str, Enum):
    NEW_APPLICATION = "new_application"
    OFFICE_ACTION_RESPONSE = "office_action_response"
    INFORMATION_DISCLOSURE = "information_disclosure"
    AMENDMENT = "amendment"
    RCE = "rce"
    ANY = "any"
    UNKNOWN = "unknown"


class EvidencePredicateKind(str, Enum):
    """Machine-checkable evidence predicates (not legal judgments)."""

    DOCUMENT_PRESENT = "document_present"
    IFW_CODE_PRESENT = "ifw_code_present"
    TEXT_PRESENT = "text_present"
    WORD_COUNT_MAX = "word_count_max"
    WORD_COUNT_MIN = "word_count_min"
    FIELD_PRESENT = "field_present"
    HEURISTIC_FORMAT = "heuristic_format"
    HUMAN_PROCESS = "human_process"
    AUTHORITY_CORPUS_BOUND = "authority_corpus_bound"
    # Prior-art diligence: named corpus must be in searched_corpora (or accepted
    # residual gap). Never asserts "no prior art exists" or patentability.
    CORPUS_SEARCHED = "corpus_searched"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ObligationCatalogError(ValueError):
    """Bounded obligation catalog failure (fail-closed)."""

    def __init__(
        self, message: str, *, code: str = "obligation_catalog_error"
    ) -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise ObligationCatalogError(
            f"{field} must be str, got {type(value).__name__}",
            code="invalid_type",
        )
    text = value.strip()
    if not text:
        raise ObligationCatalogError(f"{field} must be non-empty", code="empty_field")
    if len(text) > max_len:
        raise ObligationCatalogError(
            f"{field} exceeds max length {max_len}", code="field_too_long"
        )
    return text


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _NONEMPTY_ID_RE.match(text):
        raise ObligationCatalogError(
            f"{field} is not a valid identifier: {text!r}", code="invalid_id"
        )
    return text


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    text = _require_str(str(value), field, max_len=64).lower()
    try:
        return enum_cls(text)
    except ValueError as exc:
        raise ObligationCatalogError(
            f"{field} invalid value {value!r}", code="invalid_enum"
        ) from exc


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorityCite:
    """A single authority citation with explicit tier."""

    citation: str
    tier: AuthorityTier
    is_controlling: bool = False
    source_id: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "citation", _require_str(self.citation, "citation", max_len=512)
        )
        object.__setattr__(
            self, "tier", _coerce_enum(AuthorityTier, self.tier, "tier")
        )
        # Fail closed: MPEP / guidance cannot be controlling
        if self.tier is AuthorityTier.GUIDANCE and self.is_controlling:
            object.__setattr__(self, "is_controlling", False)
        if self.tier is AuthorityTier.FORM_INSTRUCTION and self.is_controlling:
            object.__setattr__(self, "is_controlling", False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "tier": self.tier.value,
            "is_controlling": bool(self.is_controlling),
            "source_id": self.source_id,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorityCite":
        return cls(
            citation=str(value.get("citation") or ""),
            tier=str(value.get("tier") or "unknown"),
            is_controlling=bool(value.get("is_controlling", False)),
            source_id=value.get("source_id"),
            notes=str(value.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class Applicability:
    """When an obligation applies."""

    application_types: tuple[str, ...] = ("utility",)
    scenarios: tuple[str, ...] = ("new_application",)
    components: tuple[str, ...] = ()
    notes: str = ""

    def matches(
        self,
        *,
        application_type: str,
        scenario: str,
    ) -> bool:
        types = {t.lower() for t in self.application_types}
        scenarios = {s.lower() for s in self.scenarios}
        at = application_type.lower().strip()
        sc = scenario.lower().strip()
        type_ok = "any" in types or at in types
        scenario_ok = "any" in scenarios or sc in scenarios
        return type_ok and scenario_ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_types": list(self.application_types),
            "scenarios": list(self.scenarios),
            "components": list(self.components),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Applicability":
        return cls(
            application_types=tuple(
                str(x) for x in (value.get("application_types") or ("utility",))
            ),
            scenarios=tuple(
                str(x) for x in (value.get("scenarios") or ("new_application",))
            ),
            components=tuple(str(x) for x in (value.get("components") or ())),
            notes=str(value.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class EvidencePredicate:
    """Machine-checkable predicate for package evaluation."""

    kind: EvidencePredicateKind
    target: str
    description: str = ""
    parameters: Mapping[str, Any] = field(default_factory=dict)
    mandatory: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _coerce_enum(EvidencePredicateKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "target", _require_str(self.target, "target", max_len=256)
        )
        object.__setattr__(
            self, "parameters", MappingProxyType(dict(self.parameters or {}))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "target": self.target,
            "description": self.description,
            "parameters": dict(self.parameters),
            "mandatory": bool(self.mandatory),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidencePredicate":
        return cls(
            kind=str(value.get("kind") or "unknown"),
            target=str(value.get("target") or "unknown"),
            description=str(value.get("description") or ""),
            parameters=dict(value.get("parameters") or {}),
            mandatory=bool(value.get("mandatory", True)),
        )


@dataclass(frozen=True, slots=True)
class Obligation:
    """One content-addressable filing / package obligation."""

    obligation_id: str
    title: str
    description: str
    authority_cites: tuple[AuthorityCite, ...]
    applicability: Applicability
    evidence_predicates: tuple[EvidencePredicate, ...]
    severity: ObligationSeverity
    fail_closed: FailClosedBehavior
    version: str = "1.0.0"
    component: str = ""
    guidance_cites: tuple[AuthorityCite, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self, "title", _require_str(self.title, "title", max_len=512)
        )
        object.__setattr__(
            self,
            "severity",
            _coerce_enum(ObligationSeverity, self.severity, "severity"),
        )
        object.__setattr__(
            self,
            "fail_closed",
            _coerce_enum(FailClosedBehavior, self.fail_closed, "fail_closed"),
        )
        if not self.authority_cites and not self.guidance_cites:
            raise ObligationCatalogError(
                f"{self.obligation_id}: at least one authority or guidance cite required",
                code="missing_authority",
            )
        # Ensure guidance cites are never controlling
        fixed_guidance: list[AuthorityCite] = []
        for g in self.guidance_cites:
            if g.tier is not AuthorityTier.GUIDANCE:
                fixed_guidance.append(
                    AuthorityCite(
                        citation=g.citation,
                        tier=AuthorityTier.GUIDANCE,
                        is_controlling=False,
                        source_id=g.source_id,
                        notes=g.notes,
                    )
                )
            else:
                fixed_guidance.append(g)
        object.__setattr__(self, "guidance_cites", tuple(fixed_guidance))

    @property
    def content_digest(self) -> str:
        return sha256_hex(canonical_json(self.to_dict()))

    def primary_authority_tier(self) -> AuthorityTier:
        """Highest-rank authority tier among controlling cites; else max tier."""
        if not self.authority_cites:
            return AuthorityTier.UNKNOWN
        controlling = [c for c in self.authority_cites if c.is_controlling]
        pool = controlling or list(self.authority_cites)
        best = max(pool, key=lambda c: AUTHORITY_TIER_RANK.get(c.tier.value, 0))
        return best.tier

    def mpep_elevated_above_cfr(self) -> bool:
        """True if a guidance cite is incorrectly marked controlling over CFR/statute.

        Catalog construction forbids this; used as a safety assertion.
        """
        for g in self.guidance_cites:
            if g.is_controlling:
                return True
        for c in self.authority_cites:
            if c.tier is AuthorityTier.GUIDANCE and c.is_controlling:
                return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "obligation_id": self.obligation_id,
            "title": self.title,
            "description": self.description,
            "authority_cites": [c.to_dict() for c in self.authority_cites],
            "applicability": self.applicability.to_dict(),
            "evidence_predicates": [p.to_dict() for p in self.evidence_predicates],
            "severity": self.severity.value,
            "fail_closed": self.fail_closed.value,
            "version": self.version,
            "component": self.component,
            "guidance_cites": [c.to_dict() for c in self.guidance_cites],
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Obligation":
        return cls(
            obligation_id=str(value.get("obligation_id") or ""),
            title=str(value.get("title") or ""),
            description=str(value.get("description") or ""),
            authority_cites=tuple(
                AuthorityCite.from_dict(c)
                for c in (value.get("authority_cites") or ())
            ),
            applicability=Applicability.from_dict(
                value.get("applicability") or {}
            ),
            evidence_predicates=tuple(
                EvidencePredicate.from_dict(p)
                for p in (value.get("evidence_predicates") or ())
            ),
            severity=str(value.get("severity") or "major"),
            fail_closed=str(value.get("fail_closed") or "unknown"),
            version=str(value.get("version") or "1.0.0"),
            component=str(value.get("component") or ""),
            guidance_cites=tuple(
                AuthorityCite.from_dict(c)
                for c in (value.get("guidance_cites") or ())
            ),
            notes=str(value.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class ObligationCatalog:
    """Content-addressed obligation registry."""

    catalog_id: str
    version: str
    obligations: tuple[Obligation, ...]
    schema: str = OBLIGATION_CATALOG_SCHEMA
    disclaimer: str = REVIEW_ONLY_CATALOG_DISCLAIMER
    notes: str = ""
    content_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "catalog_id", _identifier(self.catalog_id, "catalog_id")
        )
        ids = [o.obligation_id for o in self.obligations]
        if len(ids) != len(set(ids)):
            raise ObligationCatalogError(
                "duplicate obligation_id in catalog", code="duplicate_id"
            )
        for obl in self.obligations:
            if obl.mpep_elevated_above_cfr():
                raise ObligationCatalogError(
                    f"{obl.obligation_id}: MPEP/guidance must not be controlling",
                    code="guidance_elevated",
                )
        digest = self.content_digest or self.compute_digest()
        object.__setattr__(self, "content_digest", digest)

    def compute_digest(self) -> str:
        payload = {
            "catalog_id": self.catalog_id,
            "version": self.version,
            "obligations": [o.to_dict() for o in self.obligations],
            "schema": self.schema,
        }
        return sha256_hex(canonical_json(payload))

    def get(self, obligation_id: str) -> Obligation | None:
        for obl in self.obligations:
            if obl.obligation_id == obligation_id:
                return obl
        return None

    def resolve(
        self, obligation_id: str
    ) -> Obligation | None:
        """Resolve obligation by id; missing → None (caller fails closed to unknown)."""
        return self.get(obligation_id)

    def applicable(
        self,
        *,
        application_type: str = "utility",
        scenario: str = "new_application",
    ) -> tuple[Obligation, ...]:
        return tuple(
            o
            for o in self.obligations
            if o.applicability.matches(
                application_type=application_type, scenario=scenario
            )
        )

    def unknown_authority_status(self, obligation_id: str) -> str:
        """Fail-closed status when obligation or its authority is unknown."""
        obl = self.get(obligation_id)
        if obl is None:
            return "unknown"
        if not obl.authority_cites:
            return "unknown"
        if any(c.tier is AuthorityTier.UNKNOWN for c in obl.authority_cites):
            return "unknown"
        return "resolved"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "catalog_id": self.catalog_id,
            "version": self.version,
            "content_digest": self.content_digest,
            "disclaimer": self.disclaimer,
            "notes": self.notes,
            "interface": OBLIGATION_CATALOG_INTERFACE,
            "code_version": OBLIGATION_CATALOG_CODE_VERSION,
            "obligations": [o.to_dict() for o in self.obligations],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ObligationCatalog":
        return cls(
            catalog_id=str(value.get("catalog_id") or ""),
            version=str(value.get("version") or "1.0.0"),
            obligations=tuple(
                Obligation.from_dict(o) for o in (value.get("obligations") or ())
            ),
            schema=str(value.get("schema") or OBLIGATION_CATALOG_SCHEMA),
            disclaimer=str(
                value.get("disclaimer") or REVIEW_ONLY_CATALOG_DISCLAIMER
            ),
            notes=str(value.get("notes") or ""),
            content_digest=str(value.get("content_digest") or ""),
        )


# ---------------------------------------------------------------------------
# Load / seed path resolution
# ---------------------------------------------------------------------------


def resolve_seed_path(base: Path | None = None) -> Path:
    """Locate obligation_catalog_seed.json next to this module (or under base)."""
    if base is not None:
        candidate = Path(base)
        if candidate.is_file():
            return candidate
        nested = candidate / SEED_FILENAME
        if nested.is_file():
            return nested
    here = Path(__file__).resolve().parent
    local = here / SEED_FILENAME
    if local.is_file():
        return local
    raise ObligationCatalogError(
        f"seed file not found: {SEED_FILENAME}", code="seed_missing"
    )


def load_catalog_from_path(path: Path | str) -> ObligationCatalog:
    path = Path(path)
    if not path.is_file():
        raise ObligationCatalogError(
            f"catalog file not found: {path}", code="catalog_missing"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ObligationCatalogError(
            f"invalid catalog JSON: {exc}", code="invalid_json"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ObligationCatalogError(
            "catalog root must be object", code="invalid_json"
        )
    return ObligationCatalog.from_dict(payload)


def load_seed_catalog(path: Path | str | None = None) -> ObligationCatalog:
    """Load the versioned seed obligation catalog; review remains pending."""
    seed_path = resolve_seed_path(Path(path) if path else None)
    return load_catalog_from_path(seed_path)


def guidance_never_above_regulation(catalog: ObligationCatalog) -> bool:
    """Safety check: no guidance cite is controlling; statute/CFR outrank MPEP."""
    for obl in catalog.obligations:
        if obl.mpep_elevated_above_cfr():
            return False
        for cite in obl.authority_cites:
            if cite.tier is AuthorityTier.GUIDANCE and cite.is_controlling:
                return False
        # If both guidance and regulation present, regulation must be controlling-capable
        tiers = {c.tier for c in obl.authority_cites}
        if AuthorityTier.GUIDANCE in tiers and AuthorityTier.REGULATION in tiers:
            regs = [
                c
                for c in obl.authority_cites
                if c.tier is AuthorityTier.REGULATION
            ]
            if regs and not any(c.is_controlling for c in regs):
                # Soft check: regulation should be preferred as controlling when present
                # Allow non-controlling regulation only if statute is controlling
                statutes = [
                    c
                    for c in obl.authority_cites
                    if c.tier is AuthorityTier.STATUTE and c.is_controlling
                ]
                if not statutes:
                    return False
    return True


__all__ = [
    "OBLIGATION_CATALOG_SCHEMA",
    "OBLIGATION_CATALOG_INTERFACE",
    "OBLIGATION_CATALOG_CODE_VERSION",
    "SEED_CATALOG_ID",
    "SEED_CATALOG_VERSION",
    "SEED_FILENAME",
    "REVIEW_ONLY_CATALOG_DISCLAIMER",
    "AUTHORITY_TIER_RANK",
    "Applicability",
    "AuthorityCite",
    "AuthorityTier",
    "EvidencePredicate",
    "EvidencePredicateKind",
    "FailClosedBehavior",
    "Obligation",
    "ObligationCatalog",
    "ObligationCatalogError",
    "ObligationSeverity",
    "ApplicationTypeScope",
    "ScenarioScope",
    "canonical_json",
    "guidance_never_above_regulation",
    "load_catalog_from_path",
    "load_seed_catalog",
    "resolve_seed_path",
    "sha256_hex",
]
