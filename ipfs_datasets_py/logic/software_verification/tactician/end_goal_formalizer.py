"""End-goal formalizer: prose / controlled language → ``EndGoalSpec`` (FVT-G022).

``EndGoalFormalizer@1`` extends the prompt / Intent-IR path with a deterministic
extractor that produces *bounded end-goal candidates* only.  It never mutates
the frozen caller request, never admits a candidate, and never elevates learned
parsing above candidate authority.

Extracted bindings include actors, state variables, current/target state,
transitions, environment, quantifiers, property class, assumptions (by class),
resource bounds, assurance target, acceptance evidence, and phrase-to-clause
provenance with prompt/repository spans.

Acceptance invariants (enforced in this module and its unit tests):

* deterministic controlled-language cases round-trip;
* learned parsing remains candidate-only;
* every structured clause maps to prompt/repository spans;
* hidden assumptions and ungrounded identifiers are rejected; and
* unsupported or underspecified semantics remain explicit non-success fields.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from .contracts import (
    AmbiguityStatus,
    AssumptionBinding,
    AssumptionClass,
    AuthorityCeiling,
    EndGoalInterpretation,
    EndGoalSpec,
    PhraseProvenance,
    PropertyClass,
    QuantifierKind,
    ResourceBounds,
    SourceSpanBinding,
    TacticianContractError,
    content_identity,
)

# ---------------------------------------------------------------------------
# Interface / schema constants
# ---------------------------------------------------------------------------

END_GOAL_FORMALIZER_INTERFACE: Final = "EndGoalFormalizer@1"
END_GOAL_FORMALIZER_VERSION: Final = "1"
END_GOAL_FORMALIZER_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/end-goal-formalizer@1"
)
END_GOAL_FORMALIZER_REQUEST_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/end-goal-formalizer-request@1"
)
END_GOAL_FORMALIZER_RESULT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/end-goal-formalizer-result@1"
)
END_GOAL_FORMALIZER_PRODUCER_ID: Final = "end-goal-formalizer"

# Proposal claims the formalizer refuses on any path, including learned.
_FORBIDDEN_ADMISSION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "admitted",
        "admission_claimed",
        "proof_claimed",
        "proved",
        "complete",
        "completion_claimed",
        "implementation_conformance_claimed",
        "implementation_conformant",
        "attested",
        "kernel_verified",
        "selected",
        "confirmed",
    }
)

# Phrases that mark smuggled / hidden assumptions in free prose.
_HIDDEN_ASSUMPTION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bhidden\s+assumption\b", re.IGNORECASE),
    re.compile(r"\bimplicit(?:ly)?\s+assume\b", re.IGNORECASE),
    re.compile(r"\bwe\s+assume\s+without\s+(?:stating|declaring)\b", re.IGNORECASE),
    re.compile(r"\bobviously\s+(?:true|holds|assumed)\b", re.IGNORECASE),
    re.compile(r"\btake\s+for\s+granted\b", re.IGNORECASE),
    re.compile(r"\bwithout\s+loss\s+of\s+generality\b", re.IGNORECASE),
    re.compile(r"\bw\.?l\.?o\.?g\.?\b", re.IGNORECASE),
)

# Controlled-language directive lines: KEY rest…
_DIRECTIVE_RE: Final = re.compile(
    r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*(?::|\s+)\s*(?P<body>.+?)\s*$"
)
_KV_RE: Final = re.compile(r"^(?P<k>[A-Za-z_][A-Za-z0-9_.\-]*)\s*=\s*(?P<v>.+)$")
_ASSUME_RE: Final = re.compile(
    r"^(?:(?P<klass>trusted|must_prove|hypothetical)\s*:\s*)?(?P<body>.+)$",
    re.IGNORECASE,
)
_IDENT_RE: Final = re.compile(r"\b([A-Za-z_][A-Za-z0-9_\-]{0,127})\b")

# Free-prose property / quantifier detectors (deterministic, ordered).
_PROSE_PROPERTY_RULES: Final[tuple[tuple[re.Pattern[str], PropertyClass, tuple[QuantifierKind, ...]], ...]] = (
    (
        re.compile(
            r"\bevery\s+(?:execution|path|run|trace)\b.*\beventually\b",
            re.IGNORECASE,
        ),
        PropertyClass.UNIVERSAL_REACHABILITY,
        (QuantifierKind.FORALL, QuantifierKind.EVENTUALLY),
    ),
    (
        re.compile(
            r"\ball\s+(?:executions|paths|runs|traces)\b.*\beventually\b",
            re.IGNORECASE,
        ),
        PropertyClass.UNIVERSAL_REACHABILITY,
        (QuantifierKind.FORALL, QuantifierKind.EVENTUALLY),
    ),
    (
        re.compile(
            r"\b(?:inevitably|is\s+inevitable|must\s+eventually)\b",
            re.IGNORECASE,
        ),
        PropertyClass.INEVITABILITY,
        (QuantifierKind.EVENTUALLY,),
    ),
    (
        re.compile(
            r"\b(?:remains?\s+(?:an\s+)?invariant|is\s+invariant|always\s+holds|"
            r"invariance|safety\s+invariant)\b",
            re.IGNORECASE,
        ),
        PropertyClass.INVARIANCE,
        (QuantifierKind.ALWAYS,),
    ),
    (
        re.compile(r"\b(?:never\s+reaches?|safety)\b", re.IGNORECASE),
        PropertyClass.SAFETY,
        (QuantifierKind.ALWAYS,),
    ),
    (
        re.compile(r"\b(?:terminates?|termination)\b", re.IGNORECASE),
        PropertyClass.TERMINATION,
        (QuantifierKind.EVENTUALLY,),
    ),
    (
        re.compile(r"\b(?:refines?|refinement)\b", re.IGNORECASE),
        PropertyClass.REFINEMENT,
        (QuantifierKind.NONE,),
    ),
    (
        re.compile(r"\b(?:authorization|access\s+control)\b", re.IGNORECASE),
        PropertyClass.AUTHORIZATION,
        (QuantifierKind.FORALL,),
    ),
    (
        re.compile(r"\b(?:protocol|authentication|secrecy)\b", re.IGNORECASE),
        PropertyClass.PROTOCOL,
        (QuantifierKind.FORALL,),
    ),
    (
        re.compile(
            r"\b(?:some\s+execution|there\s+exists\s+a\s+(?:path|run|trace)|"
            r"can\s+reach|reaches?|reachability)\b",
            re.IGNORECASE,
        ),
        PropertyClass.EXISTENTIAL_REACHABILITY,
        (QuantifierKind.EXISTS, QuantifierKind.EVENTUALLY),
    ),
    (
        re.compile(r"\beventually\b", re.IGNORECASE),
        PropertyClass.LIVENESS,
        (QuantifierKind.EVENTUALLY,),
    ),
)

_PROPERTY_ALIASES: Final[dict[str, PropertyClass]] = {
    "existential_reachability": PropertyClass.EXISTENTIAL_REACHABILITY,
    "exists_reach": PropertyClass.EXISTENTIAL_REACHABILITY,
    "exists_reachability": PropertyClass.EXISTENTIAL_REACHABILITY,
    "reachability": PropertyClass.EXISTENTIAL_REACHABILITY,
    "existential": PropertyClass.EXISTENTIAL_REACHABILITY,
    "universal_reachability": PropertyClass.UNIVERSAL_REACHABILITY,
    "forall_reach": PropertyClass.UNIVERSAL_REACHABILITY,
    "universal": PropertyClass.UNIVERSAL_REACHABILITY,
    "inevitability": PropertyClass.INEVITABILITY,
    "inevitable": PropertyClass.INEVITABILITY,
    "liveness": PropertyClass.LIVENESS,
    "invariance": PropertyClass.INVARIANCE,
    "invariant": PropertyClass.INVARIANCE,
    "safety": PropertyClass.SAFETY,
    "termination": PropertyClass.TERMINATION,
    "terminates": PropertyClass.TERMINATION,
    "refinement": PropertyClass.REFINEMENT,
    "refines": PropertyClass.REFINEMENT,
    "hyperproperty": PropertyClass.HYPERPROPERTY,
    "authorization": PropertyClass.AUTHORIZATION,
    "protocol": PropertyClass.PROTOCOL,
    "theorem": PropertyClass.THEOREM,
    "contract": PropertyClass.CONTRACT,
    "unspecified": PropertyClass.UNSPECIFIED,
}

_QUANTIFIER_ALIASES: Final[dict[str, QuantifierKind]] = {
    "exists": QuantifierKind.EXISTS,
    "existential": QuantifierKind.EXISTS,
    "forall": QuantifierKind.FORALL,
    "universal": QuantifierKind.FORALL,
    "eventually": QuantifierKind.EVENTUALLY,
    "always": QuantifierKind.ALWAYS,
    "until": QuantifierKind.UNTIL,
    "none": QuantifierKind.NONE,
}

_ASSUMPTION_CLASS_ALIASES: Final[dict[str, AssumptionClass]] = {
    "trusted": AssumptionClass.TRUSTED,
    "must_prove": AssumptionClass.MUST_PROVE,
    "must-prove": AssumptionClass.MUST_PROVE,
    "prove": AssumptionClass.MUST_PROVE,
    "hypothetical": AssumptionClass.HYPOTHETICAL,
    "hypothesis": AssumptionClass.HYPOTHETICAL,
}

_ASSURANCE_ALIASES: Final[dict[str, AuthorityCeiling]] = {
    "none": AuthorityCeiling.NONE,
    "advisory": AuthorityCeiling.ADVISORY,
    "candidate": AuthorityCeiling.CANDIDATE,
    "bounded": AuthorityCeiling.BOUNDED,
    "satisfiability": AuthorityCeiling.SATISFIABILITY,
    "model_check": AuthorityCeiling.MODEL_CHECK,
    "monitor": AuthorityCeiling.MONITOR,
    "authorization": AuthorityCeiling.AUTHORIZATION,
    "protocol": AuthorityCeiling.PROTOCOL,
    "hyperproperty": AuthorityCeiling.HYPERPROPERTY,
    "reconstruction": AuthorityCeiling.RECONSTRUCTION,
    "attestation": AuthorityCeiling.ATTESTATION,
    "theorem": AuthorityCeiling.THEOREM,
    "declarative": AuthorityCeiling.DECLARATIVE,
}

_BOUND_FIELD_ALIASES: Final[dict[str, str]] = {
    "wall_time_ms": "wall_time_ms",
    "wall_time": "wall_time_ms",
    "timeout_ms": "wall_time_ms",
    "memory_bytes": "memory_bytes",
    "memory": "memory_bytes",
    "max_steps": "max_steps",
    "steps": "max_steps",
    "max_depth": "max_depth",
    "depth": "max_depth",
    "max_nodes": "max_nodes",
    "nodes": "max_nodes",
    "max_candidates": "max_candidates",
    "candidates": "max_candidates",
    "model_token_limit": "model_token_limit",
    "token_limit": "model_token_limit",
    "network_allowed": "network_allowed",
    "network": "network_allowed",
}

# Stopwords / reserved tokens that are not treated as free identifiers.
_RESERVED_IDENTIFIERS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "to",
        "of",
        "in",
        "on",
        "for",
        "with",
        "by",
        "from",
        "is",
        "are",
        "be",
        "as",
        "at",
        "it",
        "that",
        "this",
        "some",
        "every",
        "all",
        "must",
        "can",
        "may",
        "not",
        "no",
        "yes",
        "true",
        "false",
        "actor",
        "state",
        "current",
        "target",
        "transition",
        "environment",
        "interference",
        "property",
        "quantifier",
        "assume",
        "bound",
        "assurance",
        "accept",
        "receipt",
        "logic",
        "provider",
        "unsupported",
        "goal",
        "system",
        "program",
        "execution",
        "executions",
        "path",
        "paths",
        "run",
        "runs",
        "trace",
        "traces",
        "eventually",
        "always",
        "exists",
        "forall",
        "reaches",
        "reach",
        "remains",
        "invariant",
        "terminates",
        "termination",
        "refines",
        "refinement",
        "safety",
        "liveness",
        "trusted",
        "must_prove",
        "hypothetical",
        "hypothesis",
        "bounded",
        "candidate",
        "advisory",
        "none",
        "theorem",
        "contract",
        "protocol",
        "authorization",
        "unspecified",
        "network",
        "async",
        "sync",
        "fair",
        "phase",
        "owner",
        "ready",
        "init",
        "idle",
        "active",
    }
)


# ---------------------------------------------------------------------------
# Errors and enumerations
# ---------------------------------------------------------------------------


class EndGoalFormalizerError(TacticianContractError):
    """Raised when end-goal formalization fails closed."""


class FormalizationMode(StrEnum):
    """How the extractor obtained a candidate."""

    CONTROLLED_LANGUAGE = "controlled_language"
    PROSE = "prose"
    LEARNED_CANDIDATE = "learned_candidate"
    MIXED = "mixed"


class FormalizationStatus(StrEnum):
    """Outcome of a formalization attempt (never admission)."""

    CANDIDATE = "candidate"
    UNDERSPECIFIED = "underspecified"
    UNSUPPORTED = "unsupported"
    REJECTED = "rejected"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _text(
    value: object,
    label: str,
    *,
    optional: bool = False,
    maximum: int = 16384,
) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str):
        raise EndGoalFormalizerError(f"{label} must be a string")
    text = value.strip()
    if "\x00" in text:
        raise EndGoalFormalizerError(f"{label} must not contain NUL")
    if not optional and not text:
        raise EndGoalFormalizerError(f"{label} is required")
    if len(text) > maximum:
        raise EndGoalFormalizerError(
            f"{label} exceeds maximum length of {maximum}"
        )
    return text


def _string_tuple(
    value: object,
    label: str,
    *,
    preserve_order: bool = False,
) -> tuple[str, ...]:
    if value is None:
        items: Iterable[Any] = ()
    elif isinstance(value, str):
        items = (value,)
    elif isinstance(value, Sequence) and not isinstance(
        value, (bytes, bytearray, memoryview)
    ):
        items = value
    else:
        raise EndGoalFormalizerError(f"{label} must be a sequence of strings")
    result: list[str] = []
    for raw in items:
        item = _text(raw, label, maximum=512)
        if item and item not in result:
            result.append(item)
    return tuple(result if preserve_order else sorted(result))


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise EndGoalFormalizerError(f"{label} must be a boolean")
    return value


def _mapping(value: object, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise EndGoalFormalizerError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise EndGoalFormalizerError(f"{label} keys must be strings")
    return {str(k): value[k] for k in sorted(value)}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _find_span(haystack: str, needle: str, *, start: int = 0) -> tuple[int, int]:
    """Return ``(start, end)`` offsets for ``needle`` in ``haystack`` (or best effort)."""

    if not needle:
        return (start, start)
    idx = haystack.find(needle, start)
    if idx < 0:
        idx = haystack.lower().find(needle.lower(), start)
    if idx < 0:
        return (start, start)
    return (idx, idx + len(needle))


def _parse_boolish(raw: str) -> bool | None:
    lowered = raw.strip().lower()
    if lowered in {"true", "yes", "1", "on", "allowed"}:
        return True
    if lowered in {"false", "no", "0", "off", "denied", "disallowed"}:
        return False
    return None


def _parse_intish(raw: str) -> int | None:
    text = raw.strip().lower().replace("_", "")
    if not text:
        return None
    try:
        if text.endswith("k") and text[:-1].isdigit():
            return int(text[:-1]) * 1024
        if text.endswith("m") and text[:-1].isdigit():
            return int(text[:-1]) * 1024 * 1024
        return int(text, 10)
    except ValueError:
        return None


def _property_class(raw: object) -> PropertyClass:
    if isinstance(raw, PropertyClass):
        return raw
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    if key in _PROPERTY_ALIASES:
        return _PROPERTY_ALIASES[key]
    try:
        return PropertyClass(key)
    except ValueError as exc:
        raise EndGoalFormalizerError(
            f"unsupported property class: {raw!r}"
        ) from exc


def _quantifier(raw: object) -> QuantifierKind:
    if isinstance(raw, QuantifierKind):
        return raw
    key = str(raw).strip().lower().replace("-", "_")
    if key in _QUANTIFIER_ALIASES:
        return _QUANTIFIER_ALIASES[key]
    try:
        return QuantifierKind(key)
    except ValueError as exc:
        raise EndGoalFormalizerError(
            f"unsupported quantifier: {raw!r}"
        ) from exc


def _assumption_class(raw: object) -> AssumptionClass:
    if isinstance(raw, AssumptionClass):
        return raw
    key = str(raw).strip().lower().replace("-", "_")
    if key in _ASSUMPTION_CLASS_ALIASES:
        return _ASSUMPTION_CLASS_ALIASES[key]
    try:
        return AssumptionClass(key)
    except ValueError as exc:
        raise EndGoalFormalizerError(
            f"unsupported assumption class: {raw!r}"
        ) from exc


def _assurance(raw: object) -> AuthorityCeiling:
    if isinstance(raw, AuthorityCeiling):
        return raw
    key = str(raw).strip().lower().replace("-", "_")
    if key in _ASSURANCE_ALIASES:
        return _ASSURANCE_ALIASES[key]
    try:
        return AuthorityCeiling(key)
    except ValueError as exc:
        raise EndGoalFormalizerError(
            f"unsupported assurance target: {raw!r}"
        ) from exc


def _reject_forbidden_claims(
    payload: Mapping[str, Any], *, context: str
) -> None:
    for key in _FORBIDDEN_ADMISSION_KEYS:
        if key not in payload:
            continue
        value = payload[key]
        if value is True:
            raise EndGoalFormalizerError(
                f"{context} cannot claim {key.replace('_', ' ')}"
            )
        if isinstance(value, str) and value.strip().lower() in {
            "true",
            "yes",
            "1",
            "proved",
            "complete",
            "admitted",
            "selected",
            "confirmed",
        }:
            raise EndGoalFormalizerError(
                f"{context} cannot claim {key.replace('_', ' ')}"
            )


def _source_from_mapping(
    raw: object, *, fallback_tree: str = ""
) -> SourceSpanBinding:
    if isinstance(raw, SourceSpanBinding):
        return raw
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise EndGoalFormalizerError("source must be an object")
    tree_id = str(
        raw.get("tree_id")
        or raw.get("repository_tree_id")
        or raw.get("tree")
        or fallback_tree
        or ""
    )
    return SourceSpanBinding(
        tree_id=tree_id,
        source_ref_ids=tuple(
            str(x)
            for x in (
                raw.get("source_ref_ids")
                or raw.get("code_references")
                or ()
            )
        ),
        span_ids=tuple(str(x) for x in (raw.get("span_ids") or ())),
        ast_scope_ids=tuple(str(x) for x in (raw.get("ast_scope_ids") or ())),
        snapshot_id=str(raw.get("snapshot_id") or ""),
    )


def _clause_id(kind: str, index: int, token: str = "") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", token.lower()).strip("-")[:48]
    if slug:
        return f"clause:{kind}:{index}:{slug}"
    return f"clause:{kind}:{index}"


def _extract_identifiers(text: str) -> set[str]:
    found: set[str] = set()
    for match in _IDENT_RE.finditer(text):
        token = match.group(1)
        lowered = token.lower()
        if lowered in _RESERVED_IDENTIFIERS:
            continue
        if lowered in _PROPERTY_ALIASES or lowered in _QUANTIFIER_ALIASES:
            continue
        if lowered in _ASSUMPTION_CLASS_ALIASES or lowered in _ASSURANCE_ALIASES:
            continue
        if lowered in _BOUND_FIELD_ALIASES:
            continue
        found.add(token)
    return found


# ---------------------------------------------------------------------------
# Request / result contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EndGoalFormalizerRequest:
    """Frozen caller request for end-goal formalization.

    The formalizer treats this payload as immutable: it is hashed on intake and
    the hash is echoed on the result.  The request is never mutated in place.
    """

    SCHEMA: ClassVar[str] = END_GOAL_FORMALIZER_REQUEST_SCHEMA

    caller_text: str
    source: SourceSpanBinding
    goal_id: str = ""
    root_goal_id: str = ""
    known_identifiers: tuple[str, ...] = ()
    repository_source_ref_ids: tuple[str, ...] = ()
    # Optional structured Intent-IR / advisor overlay (never authoritative).
    intent_overlay: Mapping[str, Any] = field(default_factory=dict)
    # Optional learned / model proposal — absorbed as candidate-only only.
    learned_proposal: Mapping[str, Any] | None = None
    prefer_controlled_language: bool = True
    max_candidates: int = 8
    logic_family: str = ""
    provider_ids: tuple[str, ...] = ()
    bounds: ResourceBounds = field(default_factory=ResourceBounds)
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "caller_text",
            _text(self.caller_text, "caller_text", maximum=16384),
        )
        source = self.source
        if isinstance(source, Mapping):
            source = _source_from_mapping(source)
        elif not isinstance(source, SourceSpanBinding):
            raise EndGoalFormalizerError("source must be a SourceSpanBinding")
        object.__setattr__(self, "source", source)
        if not source.tree_id and not source.source_ref_ids and not source.span_ids:
            raise EndGoalFormalizerError(
                "request source must bind a tree_id or source/span identifiers"
            )
        object.__setattr__(
            self,
            "goal_id",
            _text(self.goal_id, "goal_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "root_goal_id",
            _text(
                self.root_goal_id or self.goal_id,
                "root_goal_id",
                optional=True,
                maximum=256,
            ),
        )
        object.__setattr__(
            self,
            "known_identifiers",
            _string_tuple(self.known_identifiers, "known_identifiers"),
        )
        object.__setattr__(
            self,
            "repository_source_ref_ids",
            _string_tuple(
                self.repository_source_ref_ids, "repository_source_ref_ids"
            ),
        )
        object.__setattr__(
            self, "intent_overlay", _mapping(self.intent_overlay, "intent_overlay")
        )
        learned = self.learned_proposal
        if learned is not None:
            if not isinstance(learned, Mapping):
                raise EndGoalFormalizerError(
                    "learned_proposal must be an object when provided"
                )
            object.__setattr__(self, "learned_proposal", dict(learned))
        object.__setattr__(
            self,
            "prefer_controlled_language",
            _bool(
                self.prefer_controlled_language, "prefer_controlled_language"
            ),
        )
        if (
            not isinstance(self.max_candidates, int)
            or isinstance(self.max_candidates, bool)
            or self.max_candidates < 1
            or self.max_candidates > 64
        ):
            raise EndGoalFormalizerError(
                "max_candidates must be an integer in [1, 64]"
            )
        object.__setattr__(
            self,
            "logic_family",
            _text(self.logic_family, "logic_family", optional=True, maximum=128),
        )
        object.__setattr__(
            self,
            "provider_ids",
            _string_tuple(self.provider_ids, "provider_ids"),
        )
        bounds = self.bounds
        if isinstance(bounds, Mapping):
            bounds = ResourceBounds.from_dict(bounds)
        elif not isinstance(bounds, ResourceBounds):
            raise EndGoalFormalizerError("bounds must be a ResourceBounds")
        object.__setattr__(self, "bounds", bounds)
        object.__setattr__(self, "meta", _mapping(self.meta, "meta"))
        _reject_forbidden_claims(self.meta, context="request meta")
        if self.learned_proposal is not None:
            _reject_forbidden_claims(
                self.learned_proposal, context="learned_proposal"
            )

    @property
    def request_digest(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": END_GOAL_FORMALIZER_INTERFACE,
            "formalizer_version": END_GOAL_FORMALIZER_VERSION,
            "caller_text": self.caller_text,
            "source": self.source.to_dict(),
            "goal_id": self.goal_id,
            "root_goal_id": self.root_goal_id,
            "known_identifiers": list(self.known_identifiers),
            "repository_source_ref_ids": list(self.repository_source_ref_ids),
            "intent_overlay": dict(self.intent_overlay),
            "learned_proposal": (
                dict(self.learned_proposal)
                if self.learned_proposal is not None
                else None
            ),
            "prefer_controlled_language": self.prefer_controlled_language,
            "max_candidates": self.max_candidates,
            "logic_family": self.logic_family,
            "provider_ids": list(self.provider_ids),
            "bounds": self.bounds.to_dict(),
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EndGoalFormalizerRequest":
        if not isinstance(payload, Mapping):
            raise EndGoalFormalizerError("request payload must be an object")
        _reject_forbidden_claims(payload, context="request")
        source_raw = payload.get("source") or {}
        bounds_raw = payload.get("bounds") or {}
        return cls(
            caller_text=payload.get("caller_text")
            or payload.get("prompt")
            or payload.get("text")
            or "",
            source=_source_from_mapping(source_raw),
            goal_id=str(payload.get("goal_id") or ""),
            root_goal_id=str(payload.get("root_goal_id") or ""),
            known_identifiers=tuple(payload.get("known_identifiers") or ()),
            repository_source_ref_ids=tuple(
                payload.get("repository_source_ref_ids") or ()
            ),
            intent_overlay=payload.get("intent_overlay") or {},
            learned_proposal=payload.get("learned_proposal"),
            prefer_controlled_language=bool(
                payload.get("prefer_controlled_language", True)
            ),
            max_candidates=int(payload.get("max_candidates") or 8),
            logic_family=str(payload.get("logic_family") or ""),
            provider_ids=tuple(payload.get("provider_ids") or ()),
            bounds=(
                ResourceBounds.from_dict(bounds_raw)
                if isinstance(bounds_raw, Mapping) and bounds_raw
                else ResourceBounds()
            ),
            meta=payload.get("meta") or {},
        )


@dataclass(frozen=True, slots=True)
class FormalizationDiagnostic:
    """Structured non-success or informational note from formalization."""

    code: str
    message: str
    severity: str = "error"
    clause_id: str = ""
    phrase: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "clause_id": self.clause_id,
            "phrase": self.phrase,
        }


@dataclass(frozen=True, slots=True)
class EndGoalCandidate:
    """One formalization candidate — never admitted or proof-authoritative."""

    candidate_id: str
    end_goal: EndGoalSpec
    mode: FormalizationMode
    controlled_english: str
    authority: AuthorityCeiling = AuthorityCeiling.CANDIDATE
    admitted: bool = False
    selected: bool = False
    diagnostics: tuple[FormalizationDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if self.admitted or self.selected:
            raise EndGoalFormalizerError(
                "end-goal candidates cannot be admitted or selected by the formalizer"
            )
        if self.authority not in {
            AuthorityCeiling.NONE,
            AuthorityCeiling.ADVISORY,
            AuthorityCeiling.CANDIDATE,
        }:
            raise EndGoalFormalizerError(
                "end-goal candidate authority cannot exceed candidate"
            )
        if self.end_goal.proof_claimed or self.end_goal.completion_claimed:
            raise EndGoalFormalizerError(
                "end-goal candidate cannot claim proof or completion"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "end_goal": self.end_goal.to_dict(),
            "mode": self.mode.value,
            "controlled_english": self.controlled_english,
            "authority": self.authority.value,
            "admitted": False,
            "selected": False,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "content_id": self.end_goal.content_id,
        }


@dataclass(frozen=True, slots=True)
class EndGoalFormalizerResult:
    """Result of formalization — candidates only; request remains frozen."""

    SCHEMA: ClassVar[str] = END_GOAL_FORMALIZER_RESULT_SCHEMA
    INTERFACE: ClassVar[str] = END_GOAL_FORMALIZER_INTERFACE

    status: FormalizationStatus
    request_digest: str
    frozen_caller_text: str
    candidates: tuple[EndGoalCandidate, ...] = ()
    rejections: tuple[FormalizationDiagnostic, ...] = ()
    unsupported_semantics: tuple[str, ...] = ()
    underspecified_fields: tuple[str, ...] = ()
    producer_id: str = END_GOAL_FORMALIZER_PRODUCER_ID
    formalizer_version: str = END_GOAL_FORMALIZER_VERSION
    admitted: bool = False

    def __post_init__(self) -> None:
        if self.admitted:
            raise EndGoalFormalizerError(
                "EndGoalFormalizerResult cannot admit a candidate"
            )
        object.__setattr__(self, "admitted", False)

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "status": self.status.value,
            "request_digest": self.request_digest,
            "frozen_caller_text": self.frozen_caller_text,
            "candidates": [item.to_dict() for item in self.candidates],
            "rejections": [item.to_dict() for item in self.rejections],
            "unsupported_semantics": list(self.unsupported_semantics),
            "underspecified_fields": list(self.underspecified_fields),
            "producer_id": self.producer_id,
            "formalizer_version": self.formalizer_version,
            "admitted": False,
        }


# ---------------------------------------------------------------------------
# Controlled-language rendering / round-trip
# ---------------------------------------------------------------------------


def render_controlled_language(spec: EndGoalSpec) -> str:
    """Render a deterministic controlled-language document from ``spec``.

    The rendering is stable under field order conventions used by the parser,
    enabling round-trip identity checks for semantic bindings.
    """

    lines: list[str] = []
    lines.append(f"PROPERTY {spec.property_class.value}")
    for quantifier in spec.quantifiers:
        lines.append(f"QUANTIFIER {quantifier.value}")
    for actor in sorted(spec.actors):
        lines.append(f"ACTOR {actor}")
    for variable in sorted(spec.state_variables):
        lines.append(f"STATE {variable}")
    for key in sorted(spec.current_state):
        lines.append(f"CURRENT {key}={spec.current_state[key]}")
    for key in sorted(spec.target_state):
        lines.append(f"TARGET {key}={spec.target_state[key]}")
    for transition in sorted(spec.transitions):
        lines.append(f"TRANSITION {transition}")
    for key in sorted(spec.environment):
        lines.append(f"ENVIRONMENT {key}={spec.environment[key]}")
    for key in sorted(spec.interference):
        lines.append(f"INTERFERENCE {key}={spec.interference[key]}")
    for assumption in sorted(spec.assumptions, key=lambda a: a.assumption_id):
        lines.append(
            f"ASSUME {assumption.assumption_class.value}: {assumption.statement}"
        )
    bounds = spec.bounds
    if bounds.wall_time_ms:
        lines.append(f"BOUND wall_time_ms={bounds.wall_time_ms}")
    if bounds.memory_bytes:
        lines.append(f"BOUND memory_bytes={bounds.memory_bytes}")
    if bounds.max_steps:
        lines.append(f"BOUND max_steps={bounds.max_steps}")
    if bounds.max_depth:
        lines.append(f"BOUND max_depth={bounds.max_depth}")
    if bounds.max_nodes:
        lines.append(f"BOUND max_nodes={bounds.max_nodes}")
    if bounds.max_candidates:
        lines.append(f"BOUND max_candidates={bounds.max_candidates}")
    if bounds.model_token_limit:
        lines.append(f"BOUND model_token_limit={bounds.model_token_limit}")
    if bounds.network_allowed:
        lines.append("BOUND network_allowed=true")
    for key in sorted(bounds.extra):
        lines.append(f"BOUND {key}={bounds.extra[key]}")
    lines.append(f"ASSURANCE {spec.assurance_target.value}")
    if spec.logic_family:
        lines.append(f"LOGIC {spec.logic_family}")
    for provider in sorted(spec.provider_ids):
        lines.append(f"PROVIDER {provider}")
    for evidence in sorted(spec.acceptance_evidence):
        lines.append(f"ACCEPT {evidence}")
    for receipt in sorted(spec.expected_receipt_classes):
        lines.append(f"RECEIPT {receipt}")
    for item in sorted(spec.unsupported_semantics):
        lines.append(f"UNSUPPORTED {item}")
    return "\n".join(lines) + ("\n" if lines else "")


def render_controlled_english(spec: EndGoalSpec) -> str:
    """Render a short controlled-English summary of ``spec``."""

    parts: list[str] = []
    prop = spec.property_class.value.replace("_", " ")
    if spec.actors:
        parts.append(
            f"Actors {', '.join(sorted(spec.actors))} participate."
        )
    if spec.current_state:
        state = ", ".join(
            f"{k}={v}" for k, v in sorted(spec.current_state.items())
        )
        parts.append(f"Current state: {state}.")
    if spec.target_state:
        state = ", ".join(
            f"{k}={v}" for k, v in sorted(spec.target_state.items())
        )
        parts.append(f"Target state: {state}.")
    quant = ", ".join(q.value for q in spec.quantifiers) or "unspecified"
    parts.append(
        f"Property class is {prop} under quantifiers [{quant}]."
    )
    if spec.transitions:
        parts.append(
            f"Transitions: {', '.join(sorted(spec.transitions))}."
        )
    if spec.environment:
        env = ", ".join(
            f"{k}={v}" for k, v in sorted(spec.environment.items())
        )
        parts.append(f"Environment: {env}.")
    if spec.assumptions:
        parts.append(
            "Assumptions: "
            + "; ".join(
                f"{a.assumption_class.value}:{a.statement}"
                for a in sorted(spec.assumptions, key=lambda x: x.assumption_id)
            )
            + "."
        )
    if spec.unsupported_semantics:
        parts.append(
            "Unsupported: " + ", ".join(sorted(spec.unsupported_semantics)) + "."
        )
    if not parts:
        parts.append(f"Underspecified end goal ({prop}).")
    return " ".join(parts)


def _semantic_fingerprint(spec: EndGoalSpec) -> str:
    """Content identity over the semantic bindings used for round-trip checks."""

    payload = {
        "property_class": spec.property_class.value,
        "quantifiers": [item.value for item in spec.quantifiers],
        "actors": list(spec.actors),
        "state_variables": list(spec.state_variables),
        "current_state": dict(spec.current_state),
        "target_state": dict(spec.target_state),
        "transitions": list(spec.transitions),
        "environment": dict(spec.environment),
        "interference": dict(spec.interference),
        "assumptions": [
            {
                "assumption_class": a.assumption_class.value,
                "statement": a.statement,
            }
            for a in sorted(spec.assumptions, key=lambda x: x.assumption_id)
        ],
        "logic_family": spec.logic_family,
        "provider_ids": list(spec.provider_ids),
        "assurance_target": spec.assurance_target.value,
        "bounds": {
            "wall_time_ms": spec.bounds.wall_time_ms,
            "memory_bytes": spec.bounds.memory_bytes,
            "max_steps": spec.bounds.max_steps,
            "max_depth": spec.bounds.max_depth,
            "max_nodes": spec.bounds.max_nodes,
            "max_candidates": spec.bounds.max_candidates,
            "model_token_limit": spec.bounds.model_token_limit,
            "network_allowed": spec.bounds.network_allowed,
            "extra": dict(spec.bounds.extra),
        },
        "acceptance_evidence": list(spec.acceptance_evidence),
        "expected_receipt_classes": list(spec.expected_receipt_classes),
        "unsupported_semantics": list(spec.unsupported_semantics),
    }
    return _digest(payload)


# ---------------------------------------------------------------------------
# Parser state
# ---------------------------------------------------------------------------


@dataclass
class _Extracted:
    property_class: PropertyClass = PropertyClass.UNSPECIFIED
    quantifiers: list[QuantifierKind] = field(default_factory=list)
    actors: list[str] = field(default_factory=list)
    state_variables: list[str] = field(default_factory=list)
    current_state: dict[str, Any] = field(default_factory=dict)
    target_state: dict[str, Any] = field(default_factory=dict)
    transitions: list[str] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    interference: dict[str, Any] = field(default_factory=dict)
    assumptions: list[AssumptionBinding] = field(default_factory=list)
    logic_family: str = ""
    provider_ids: list[str] = field(default_factory=list)
    assurance_target: AuthorityCeiling = AuthorityCeiling.BOUNDED
    bound_fields: dict[str, int] = field(default_factory=dict)
    network_allowed: bool = False
    extra_bounds: dict[str, int] = field(default_factory=dict)
    acceptance_evidence: list[str] = field(default_factory=list)
    expected_receipt_classes: list[str] = field(default_factory=list)
    unsupported_semantics: list[str] = field(default_factory=list)
    provenance: list[PhraseProvenance] = field(default_factory=list)
    diagnostics: list[FormalizationDiagnostic] = field(default_factory=list)
    mode: FormalizationMode = FormalizationMode.PROSE
    # Identifiers introduced by directives (grounded in the prompt text).
    declared_identifiers: set[str] = field(default_factory=set)
    # Identifiers referenced by learned overlays that must be grounded.
    required_identifiers: set[str] = field(default_factory=set)
    phrase_hits: list[tuple[str, str, int, int]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Formalizer
# ---------------------------------------------------------------------------


class EndGoalFormalizer:
    """Deterministic end-goal formalizer (``EndGoalFormalizer@1``).

    Public entry points:

    * :meth:`formalize` — main extraction path;
    * :meth:`round_trip` — controlled-language render → reparse check;
    * :meth:`render_controlled_language` / :meth:`render_controlled_english`.
    """

    INTERFACE: ClassVar[str] = END_GOAL_FORMALIZER_INTERFACE
    VERSION: ClassVar[str] = END_GOAL_FORMALIZER_VERSION

    def formalize(
        self,
        request: EndGoalFormalizerRequest | Mapping[str, Any],
    ) -> EndGoalFormalizerResult:
        """Extract bounded end-goal candidates without admitting any of them."""

        if isinstance(request, Mapping):
            request = EndGoalFormalizerRequest.from_dict(request)
        elif not isinstance(request, EndGoalFormalizerRequest):
            raise EndGoalFormalizerError(
                "request must be EndGoalFormalizerRequest or mapping"
            )

        # Freeze digest before any work so callers can detect mutation attempts.
        request_digest = request.request_digest
        frozen_text = request.caller_text

        rejections: list[FormalizationDiagnostic] = []
        try:
            hidden = self._scan_hidden_assumptions(frozen_text)
            if hidden:
                return EndGoalFormalizerResult(
                    status=FormalizationStatus.REJECTED,
                    request_digest=request_digest,
                    frozen_caller_text=frozen_text,
                    rejections=tuple(hidden),
                    admitted=False,
                )

            extracted = self._extract(request)
            grounding_errors = self._check_identifier_grounding(
                request, extracted
            )
            if grounding_errors:
                return EndGoalFormalizerResult(
                    status=FormalizationStatus.REJECTED,
                    request_digest=request_digest,
                    frozen_caller_text=frozen_text,
                    rejections=tuple(grounding_errors),
                    unsupported_semantics=tuple(
                        sorted(extracted.unsupported_semantics)
                    ),
                    admitted=False,
                )

            candidate = self._build_candidate(request, extracted)
            candidates = [candidate]

            # Optional learned path: candidate-only, never elevated.
            if request.learned_proposal is not None:
                learned = self._absorb_learned_proposal(
                    request, request.learned_proposal
                )
                if isinstance(learned, FormalizationDiagnostic):
                    rejections.append(learned)
                else:
                    candidates.append(learned)

            # Cap candidates without preferring learned over deterministic.
            candidates = candidates[: request.max_candidates]

            underspecified = self._underspecified_fields(extracted)
            unsupported = tuple(sorted(extracted.unsupported_semantics))
            if unsupported and not any(
                c.end_goal.property_class is not PropertyClass.UNSPECIFIED
                for c in candidates
            ):
                status = FormalizationStatus.UNSUPPORTED
            elif underspecified and extracted.property_class is PropertyClass.UNSPECIFIED:
                status = FormalizationStatus.UNDERSPECIFIED
            else:
                status = FormalizationStatus.CANDIDATE

            # Integrity: frozen request must be unchanged.
            if request.request_digest != request_digest:
                raise EndGoalFormalizerError(
                    "caller request was mutated during formalization"
                )
            if request.caller_text != frozen_text:
                raise EndGoalFormalizerError(
                    "caller text was mutated during formalization"
                )

            return EndGoalFormalizerResult(
                status=status,
                request_digest=request_digest,
                frozen_caller_text=frozen_text,
                candidates=tuple(candidates),
                rejections=tuple(rejections),
                unsupported_semantics=unsupported,
                underspecified_fields=tuple(underspecified),
                admitted=False,
            )
        except EndGoalFormalizerError as exc:
            return EndGoalFormalizerResult(
                status=FormalizationStatus.ERROR,
                request_digest=request_digest,
                frozen_caller_text=frozen_text,
                rejections=(
                    FormalizationDiagnostic(
                        code="formalizer_error",
                        message=str(exc),
                        severity="error",
                    ),
                ),
                admitted=False,
            )
        except TacticianContractError as exc:
            return EndGoalFormalizerResult(
                status=FormalizationStatus.ERROR,
                request_digest=request_digest,
                frozen_caller_text=frozen_text,
                rejections=(
                    FormalizationDiagnostic(
                        code="contract_error",
                        message=str(exc),
                        severity="error",
                    ),
                ),
                admitted=False,
            )

    def round_trip(
        self,
        request: EndGoalFormalizerRequest | Mapping[str, Any],
    ) -> tuple[EndGoalSpec, EndGoalSpec, str, str]:
        """Parse → render controlled language → reparse; return both specs + digests.

        Raises :class:`EndGoalFormalizerError` when the first pass does not
        produce a usable candidate.
        """

        first = self.formalize(request)
        if not first.candidates:
            raise EndGoalFormalizerError(
                "round_trip requires at least one candidate from the first pass"
            )
        original = first.candidates[0].end_goal
        rendered = render_controlled_language(original)
        if isinstance(request, Mapping):
            base = EndGoalFormalizerRequest.from_dict(request)
        else:
            base = request
        second_request = EndGoalFormalizerRequest(
            caller_text=rendered,
            source=base.source,
            goal_id=base.goal_id or original.goal_id,
            root_goal_id=base.root_goal_id or original.root_goal_id,
            known_identifiers=base.known_identifiers,
            repository_source_ref_ids=base.repository_source_ref_ids,
            prefer_controlled_language=True,
            max_candidates=base.max_candidates,
            logic_family=base.logic_family or original.logic_family,
            provider_ids=base.provider_ids or original.provider_ids,
            bounds=base.bounds,
        )
        second = self.formalize(second_request)
        if not second.candidates:
            raise EndGoalFormalizerError(
                "round_trip reparse produced no candidates"
            )
        replayed = second.candidates[0].end_goal
        return (
            original,
            replayed,
            _semantic_fingerprint(original),
            _semantic_fingerprint(replayed),
        )

    # -- rendering proxies -------------------------------------------------

    @staticmethod
    def render_controlled_language(spec: EndGoalSpec) -> str:
        return render_controlled_language(spec)

    @staticmethod
    def render_controlled_english(spec: EndGoalSpec) -> str:
        return render_controlled_english(spec)

    # -- extraction --------------------------------------------------------

    def _extract(self, request: EndGoalFormalizerRequest) -> _Extracted:
        text = request.caller_text
        extracted = _Extracted()

        controlled = self._looks_like_controlled_language(text)
        if request.prefer_controlled_language and controlled:
            self._parse_controlled_language(text, request, extracted)
            extracted.mode = FormalizationMode.CONTROLLED_LANGUAGE
        else:
            self._parse_prose(text, request, extracted)
            extracted.mode = FormalizationMode.PROSE

        # Intent overlay may supply additional grounded fields only.
        if request.intent_overlay:
            self._apply_intent_overlay(request, extracted)
            if extracted.mode is FormalizationMode.CONTROLLED_LANGUAGE:
                extracted.mode = FormalizationMode.MIXED
            elif extracted.mode is FormalizationMode.PROSE:
                extracted.mode = FormalizationMode.MIXED

        # Default quantifiers from property class when still empty.
        if not extracted.quantifiers:
            extracted.quantifiers.extend(
                self._default_quantifiers(extracted.property_class)
            )

        # Seed provenance for any collected phrase hits.
        prompt_ref = self._prompt_source_ref(request)
        for index, (kind, phrase, start, end) in enumerate(
            extracted.phrase_hits
        ):
            extracted.provenance.append(
                PhraseProvenance(
                    phrase=phrase,
                    clause_id=_clause_id(kind, index, phrase),
                    source_ref_ids=(prompt_ref,),
                    span_ids=(f"span:{kind}:{index}",),
                    start_offset=start,
                    end_offset=end,
                )
            )

        # Every non-empty structured field family must have at least one span.
        self._ensure_field_provenance(request, extracted)
        return extracted

    def _looks_like_controlled_language(self, text: str) -> bool:
        keys = {
            "ACTOR",
            "STATE",
            "CURRENT",
            "TARGET",
            "TRANSITION",
            "ENVIRONMENT",
            "PROPERTY",
            "QUANTIFIER",
            "ASSUME",
            "BOUND",
            "ASSURANCE",
            "ACCEPT",
            "RECEIPT",
            "LOGIC",
            "PROVIDER",
            "UNSUPPORTED",
            "INTERFERENCE",
        }
        hits = 0
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = _DIRECTIVE_RE.match(stripped)
            if match and match.group("key").upper() in keys:
                hits += 1
        return hits >= 1

    def _parse_controlled_language(
        self,
        text: str,
        request: EndGoalFormalizerRequest,
        extracted: _Extracted,
    ) -> None:
        assumption_index = 0
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = _DIRECTIVE_RE.match(stripped)
            if not match:
                extracted.diagnostics.append(
                    FormalizationDiagnostic(
                        code="unrecognized_line",
                        message=f"unrecognized controlled-language line: {stripped!r}",
                        severity="warning",
                        phrase=stripped,
                    )
                )
                continue
            key = match.group("key").upper()
            body = match.group("body").strip()
            start, end = _find_span(text, stripped)
            extracted.phrase_hits.append((key.lower(), stripped, start, end))

            if key == "ACTOR":
                extracted.actors.append(body)
                extracted.declared_identifiers.add(body)
            elif key == "STATE":
                extracted.state_variables.append(body)
                extracted.declared_identifiers.add(body)
            elif key == "CURRENT":
                k, v = self._split_kv(body, "CURRENT")
                extracted.current_state[k] = self._coerce_value(v)
                extracted.declared_identifiers.add(k)
                extracted.state_variables.append(k)
            elif key == "TARGET":
                k, v = self._split_kv(body, "TARGET")
                extracted.target_state[k] = self._coerce_value(v)
                extracted.declared_identifiers.add(k)
                extracted.state_variables.append(k)
            elif key == "TRANSITION":
                extracted.transitions.append(body)
                extracted.declared_identifiers.add(body)
            elif key == "ENVIRONMENT":
                k, v = self._split_kv(body, "ENVIRONMENT")
                extracted.environment[k] = self._coerce_value(v)
                extracted.declared_identifiers.add(k)
            elif key == "INTERFERENCE":
                k, v = self._split_kv(body, "INTERFERENCE")
                extracted.interference[k] = self._coerce_value(v)
                extracted.declared_identifiers.add(k)
            elif key == "PROPERTY":
                extracted.property_class = _property_class(body)
            elif key == "QUANTIFIER":
                extracted.quantifiers.append(_quantifier(body))
            elif key == "ASSUME":
                assumption_index += 1
                am = _ASSUME_RE.match(body)
                assert am is not None
                klass_raw = am.group("klass") or "hypothetical"
                statement = am.group("body").strip()
                klass = _assumption_class(klass_raw)
                assumption_id = f"assumption:{assumption_index}"
                prompt_ref = self._prompt_source_ref(request)
                extracted.assumptions.append(
                    AssumptionBinding(
                        assumption_id=assumption_id,
                        assumption_class=klass,
                        kind="semantic",
                        statement=statement,
                        source=SourceSpanBinding(
                            tree_id=request.source.tree_id,
                            source_ref_ids=(prompt_ref,),
                            span_ids=(f"span:assume:{assumption_index}",),
                            snapshot_id=request.source.snapshot_id,
                        ),
                        authority=AuthorityCeiling.NONE,
                        reviewable=True,
                    )
                )
            elif key == "BOUND":
                self._apply_bound(body, extracted)
            elif key == "ASSURANCE":
                extracted.assurance_target = _assurance(body)
            elif key == "ACCEPT":
                extracted.acceptance_evidence.append(body)
            elif key == "RECEIPT":
                extracted.expected_receipt_classes.append(body)
            elif key == "LOGIC":
                extracted.logic_family = body
            elif key == "PROVIDER":
                extracted.provider_ids.append(body)
            elif key == "UNSUPPORTED":
                extracted.unsupported_semantics.append(body)
            else:
                extracted.diagnostics.append(
                    FormalizationDiagnostic(
                        code="unknown_directive",
                        message=f"unknown directive {key}",
                        severity="warning",
                        phrase=stripped,
                    )
                )

    def _parse_prose(
        self,
        text: str,
        request: EndGoalFormalizerRequest,
        extracted: _Extracted,
    ) -> None:
        # Property / quantifier from ordered prose rules.
        for pattern, prop, quants in _PROSE_PROPERTY_RULES:
            match = pattern.search(text)
            if match:
                extracted.property_class = prop
                for q in quants:
                    if q not in extracted.quantifiers:
                        extracted.quantifiers.append(q)
                start, end = match.start(), match.end()
                extracted.phrase_hits.append(
                    ("property", match.group(0), start, end)
                )
                break
        else:
            extracted.unsupported_semantics.append(
                "underspecified_property_class"
            )
            extracted.diagnostics.append(
                FormalizationDiagnostic(
                    code="underspecified_property",
                    message="no property class recognized in prose",
                    severity="warning",
                )
            )

        # Target state: "... reaches ready" / "target ready" / "state ready".
        target_match = re.search(
            r"\b(?:reaches?|reach|to|target(?:\s+state)?|becomes?)\s+"
            r"([A-Za-z_][A-Za-z0-9_\-]*)\b",
            text,
            re.IGNORECASE,
        )
        if target_match:
            value = target_match.group(1)
            if value.lower() not in _RESERVED_IDENTIFIERS or value.lower() in {
                "ready",
                "init",
                "idle",
                "active",
            }:
                extracted.target_state["phase"] = value
                extracted.state_variables.append("phase")
                extracted.declared_identifiers.add(value)
                extracted.phrase_hits.append(
                    (
                        "target",
                        target_match.group(0),
                        target_match.start(),
                        target_match.end(),
                    )
                )

        current_match = re.search(
            r"\b(?:from|current(?:\s+state)?|starting(?:\s+from)?)\s+"
            r"([A-Za-z_][A-Za-z0-9_\-]*)\b",
            text,
            re.IGNORECASE,
        )
        if current_match:
            value = current_match.group(1)
            extracted.current_state["phase"] = value
            extracted.state_variables.append("phase")
            extracted.declared_identifiers.add(value)
            extracted.phrase_hits.append(
                (
                    "current",
                    current_match.group(0),
                    current_match.start(),
                    current_match.end(),
                )
            )

        # Explicit actor mentions: "actor scheduler" or "actors: a, b".
        for match in re.finditer(
            r"\bactors?\s*[:=]?\s*([A-Za-z_][A-Za-z0-9_\-]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_\-]*)*)",
            text,
            re.IGNORECASE,
        ):
            for actor in re.split(r"\s*,\s*", match.group(1)):
                if actor:
                    extracted.actors.append(actor)
                    extracted.declared_identifiers.add(actor)
            extracted.phrase_hits.append(
                ("actor", match.group(0), match.start(), match.end())
            )

        # Transitions: "via claim/release" or "transition claim".
        for match in re.finditer(
            r"\b(?:via|transition|transitions)\s+([A-Za-z_][A-Za-z0-9_\-/]*)",
            text,
            re.IGNORECASE,
        ):
            for token in re.split(r"[/,]", match.group(1)):
                token = token.strip()
                if token:
                    extracted.transitions.append(token)
                    extracted.declared_identifiers.add(token)
            extracted.phrase_hits.append(
                ("transition", match.group(0), match.start(), match.end())
            )

        # Environment: "environment network=async" or "under fair scheduling".
        env_match = re.search(
            r"\benvironment\s+([A-Za-z_][A-Za-z0-9_\-]*)\s*=\s*([A-Za-z0-9_\-]+)",
            text,
            re.IGNORECASE,
        )
        if env_match:
            extracted.environment[env_match.group(1)] = env_match.group(2)
            extracted.declared_identifiers.add(env_match.group(1))
            extracted.phrase_hits.append(
                (
                    "environment",
                    env_match.group(0),
                    env_match.start(),
                    env_match.end(),
                )
            )
        if re.search(r"\bfair\s+schedul", text, re.IGNORECASE):
            extracted.environment["scheduler"] = "fair"
            start, end = _find_span(text, "fair")
            extracted.phrase_hits.append(("environment", "fair", start, end))

        # Explicit ASSUME-like prose that is declared (not hidden).
        for match in re.finditer(
            r"\b(?:assume|assuming|assumption)\s*[:=]?\s*"
            r"(?:(trusted|must_prove|hypothetical)\s*:\s*)?"
            r"([^.!\n]+)",
            text,
            re.IGNORECASE,
        ):
            # Skip if it matched a hidden-assumption pattern earlier (already rejected).
            klass = _assumption_class(match.group(1) or "hypothetical")
            statement = match.group(2).strip()
            if not statement:
                continue
            index = len(extracted.assumptions) + 1
            prompt_ref = self._prompt_source_ref(request)
            extracted.assumptions.append(
                AssumptionBinding(
                    assumption_id=f"assumption:{index}",
                    assumption_class=klass,
                    kind="semantic",
                    statement=statement,
                    source=SourceSpanBinding(
                        tree_id=request.source.tree_id,
                        source_ref_ids=(prompt_ref,),
                        span_ids=(f"span:assume:{index}",),
                        snapshot_id=request.source.snapshot_id,
                    ),
                    authority=AuthorityCeiling.NONE,
                    reviewable=True,
                )
            )
            extracted.phrase_hits.append(
                ("assume", match.group(0), match.start(), match.end())
            )

        # Bounds in prose: "within 5000ms", "max_steps=32".
        for match in re.finditer(
            r"\b(wall_time_ms|timeout_ms|max_steps|max_depth|max_nodes|"
            r"max_candidates|memory_bytes)\s*=\s*(\d+)",
            text,
            re.IGNORECASE,
        ):
            self._apply_bound(f"{match.group(1)}={match.group(2)}", extracted)
            extracted.phrase_hits.append(
                ("bound", match.group(0), match.start(), match.end())
            )
        time_match = re.search(
            r"\bwithin\s+(\d+)\s*(ms|milliseconds|s|seconds)?\b",
            text,
            re.IGNORECASE,
        )
        if time_match:
            amount = int(time_match.group(1))
            unit = (time_match.group(2) or "ms").lower()
            if unit.startswith("s"):
                amount *= 1000
            extracted.bound_fields["wall_time_ms"] = amount
            extracted.phrase_hits.append(
                (
                    "bound",
                    time_match.group(0),
                    time_match.start(),
                    time_match.end(),
                )
            )

        # Acceptance evidence: "accept receipt:kernel".
        for match in re.finditer(
            r"\baccept(?:ance)?(?:\s+evidence)?\s*[:=]?\s*([A-Za-z0-9_:\-./]+)",
            text,
            re.IGNORECASE,
        ):
            token = match.group(1).rstrip(".,;:!?")
            if token:
                extracted.acceptance_evidence.append(token)
            extracted.phrase_hits.append(
                ("accept", match.group(0), match.start(), match.end())
            )

        # Unsupported markers.
        for match in re.finditer(
            r"\bunsupported\s*[:=]?\s*([A-Za-z0-9_\-./]+)",
            text,
            re.IGNORECASE,
        ):
            token = match.group(1).rstrip(".,;:!?")
            if token:
                extracted.unsupported_semantics.append(token)
            extracted.phrase_hits.append(
                ("unsupported", match.group(0), match.start(), match.end())
            )

        # Logic family.
        logic_match = re.search(
            r"\blogic(?:\s+family)?\s*[:=]?\s*([A-Za-z0-9_.\-]+)",
            text,
            re.IGNORECASE,
        )
        if logic_match:
            extracted.logic_family = logic_match.group(1)
            extracted.phrase_hits.append(
                (
                    "logic",
                    logic_match.group(0),
                    logic_match.start(),
                    logic_match.end(),
                )
            )

        # Assurance.
        assurance_match = re.search(
            r"\bassurance\s*[:=]?\s*([A-Za-z0-9_\-]+)",
            text,
            re.IGNORECASE,
        )
        if assurance_match:
            try:
                extracted.assurance_target = _assurance(assurance_match.group(1))
                extracted.phrase_hits.append(
                    (
                        "assurance",
                        assurance_match.group(0),
                        assurance_match.start(),
                        assurance_match.end(),
                    )
                )
            except EndGoalFormalizerError:
                extracted.unsupported_semantics.append(
                    f"unknown_assurance:{assurance_match.group(1)}"
                )

    def _apply_intent_overlay(
        self,
        request: EndGoalFormalizerRequest,
        extracted: _Extracted,
    ) -> None:
        overlay = request.intent_overlay
        _reject_forbidden_claims(overlay, context="intent_overlay")
        if "property_class" in overlay and extracted.property_class is PropertyClass.UNSPECIFIED:
            try:
                extracted.property_class = _property_class(
                    overlay["property_class"]
                )
            except EndGoalFormalizerError as exc:
                extracted.diagnostics.append(
                    FormalizationDiagnostic(
                        code="overlay_property_rejected",
                        message=str(exc),
                        severity="warning",
                    )
                )
        for actor in overlay.get("actors") or ():
            name = str(actor)
            extracted.actors.append(name)
            extracted.required_identifiers.add(name)
        for variable in overlay.get("state_variables") or ():
            name = str(variable)
            extracted.state_variables.append(name)
            extracted.required_identifiers.add(name)
        for transition in overlay.get("transitions") or ():
            name = str(transition)
            extracted.transitions.append(name)
            extracted.required_identifiers.add(name)
        if isinstance(overlay.get("current_state"), Mapping):
            for key, value in overlay["current_state"].items():
                extracted.current_state[str(key)] = value
                extracted.required_identifiers.add(str(key))
        if isinstance(overlay.get("target_state"), Mapping):
            for key, value in overlay["target_state"].items():
                extracted.target_state[str(key)] = value
                extracted.required_identifiers.add(str(key))
        if isinstance(overlay.get("environment"), Mapping):
            for key, value in overlay["environment"].items():
                extracted.environment[str(key)] = value
        for quant in overlay.get("quantifiers") or ():
            try:
                q = _quantifier(quant)
                if q not in extracted.quantifiers:
                    extracted.quantifiers.append(q)
            except EndGoalFormalizerError:
                extracted.unsupported_semantics.append(
                    f"overlay_quantifier:{quant}"
                )
        if overlay.get("logic_family") and not extracted.logic_family:
            extracted.logic_family = str(overlay["logic_family"])
        for item in overlay.get("unsupported_semantics") or ():
            extracted.unsupported_semantics.append(str(item))
        # Overlay assumptions must be explicitly listed; still require grounding.
        for index, item in enumerate(overlay.get("assumptions") or ()):
            if not isinstance(item, Mapping):
                extracted.diagnostics.append(
                    FormalizationDiagnostic(
                        code="overlay_assumption_rejected",
                        message="overlay assumptions must be objects with statement",
                        severity="error",
                    )
                )
                continue
            statement = str(item.get("statement") or "").strip()
            if not statement:
                continue
            # Grounding: statement text must appear in caller_text.
            if statement not in request.caller_text:
                extracted.diagnostics.append(
                    FormalizationDiagnostic(
                        code="hidden_assumption",
                        message=(
                            "overlay assumption statement is not present in "
                            "caller text"
                        ),
                        severity="error",
                        phrase=statement,
                    )
                )
                # Surface as rejection later via required check.
                extracted.required_identifiers.add(
                    f"__hidden_assumption__{index}"
                )
                continue
            klass = _assumption_class(
                item.get("assumption_class", AssumptionClass.HYPOTHETICAL)
            )
            extracted.assumptions.append(
                AssumptionBinding(
                    assumption_id=str(
                        item.get("assumption_id")
                        or f"assumption:overlay:{index + 1}"
                    ),
                    assumption_class=klass,
                    kind=str(item.get("kind") or "semantic"),
                    statement=statement,
                    source=SourceSpanBinding(
                        tree_id=request.source.tree_id,
                        source_ref_ids=(self._prompt_source_ref(request),),
                        span_ids=(f"span:overlay-assume:{index + 1}",),
                        snapshot_id=request.source.snapshot_id,
                    ),
                    authority=AuthorityCeiling.NONE,
                    reviewable=True,
                )
            )

    def _absorb_learned_proposal(
        self,
        request: EndGoalFormalizerRequest,
        proposal: Mapping[str, Any],
    ) -> EndGoalCandidate | FormalizationDiagnostic:
        """Absorb a learned/model proposal as a candidate-only artifact."""

        try:
            _reject_forbidden_claims(proposal, context="learned_proposal")
        except EndGoalFormalizerError as exc:
            return FormalizationDiagnostic(
                code="learned_admission_rejected",
                message=str(exc),
                severity="error",
            )

        # Learned proposals cannot inject ungrounded identifiers.
        proposed_ids = set()
        for key in ("actors", "state_variables", "transitions"):
            for item in proposal.get(key) or ():
                proposed_ids.add(str(item))
        grounded = self._grounded_identifier_set(request)
        ungrounded = sorted(
            ident
            for ident in proposed_ids
            if ident not in grounded
            and ident.lower() not in {g.lower() for g in grounded}
        )
        if ungrounded:
            return FormalizationDiagnostic(
                code="learned_ungrounded_identifier",
                message=(
                    "learned proposal references ungrounded identifiers: "
                    + ", ".join(ungrounded)
                ),
                severity="error",
            )

        # Hidden assumptions in learned proposals are rejected.
        for item in proposal.get("assumptions") or ():
            if isinstance(item, Mapping):
                statement = str(item.get("statement") or "")
            else:
                statement = str(item)
            if statement and statement not in request.caller_text:
                return FormalizationDiagnostic(
                    code="learned_hidden_assumption",
                    message=(
                        "learned proposal assumption is not present in caller text"
                    ),
                    severity="error",
                    phrase=statement,
                )

        extracted = _Extracted(mode=FormalizationMode.LEARNED_CANDIDATE)
        if proposal.get("property_class"):
            try:
                extracted.property_class = _property_class(
                    proposal["property_class"]
                )
            except EndGoalFormalizerError as exc:
                return FormalizationDiagnostic(
                    code="learned_property_rejected",
                    message=str(exc),
                    severity="error",
                )
        for q in proposal.get("quantifiers") or ():
            try:
                extracted.quantifiers.append(_quantifier(q))
            except EndGoalFormalizerError:
                extracted.unsupported_semantics.append(f"learned_quantifier:{q}")
        for actor in proposal.get("actors") or ():
            extracted.actors.append(str(actor))
        for variable in proposal.get("state_variables") or ():
            extracted.state_variables.append(str(variable))
        for transition in proposal.get("transitions") or ():
            extracted.transitions.append(str(transition))
        if isinstance(proposal.get("current_state"), Mapping):
            extracted.current_state.update(
                {str(k): v for k, v in proposal["current_state"].items()}
            )
        if isinstance(proposal.get("target_state"), Mapping):
            extracted.target_state.update(
                {str(k): v for k, v in proposal["target_state"].items()}
            )
        if isinstance(proposal.get("environment"), Mapping):
            extracted.environment.update(
                {str(k): v for k, v in proposal["environment"].items()}
            )
        for item in proposal.get("unsupported_semantics") or ():
            extracted.unsupported_semantics.append(str(item))
        if proposal.get("logic_family"):
            extracted.logic_family = str(proposal["logic_family"])
        if proposal.get("assurance_target"):
            try:
                extracted.assurance_target = _assurance(
                    proposal["assurance_target"]
                )
            except EndGoalFormalizerError:
                extracted.assurance_target = AuthorityCeiling.CANDIDATE
        # Force candidate authority for learned path.
        if extracted.assurance_target not in {
            AuthorityCeiling.NONE,
            AuthorityCeiling.ADVISORY,
            AuthorityCeiling.CANDIDATE,
        }:
            extracted.assurance_target = AuthorityCeiling.CANDIDATE

        # Provenance: map whole proposal to prompt span 0..len.
        prompt_ref = self._prompt_source_ref(request)
        extracted.provenance.append(
            PhraseProvenance(
                phrase=request.caller_text[:256] or "learned_proposal",
                clause_id="clause:learned:0",
                source_ref_ids=(prompt_ref,),
                span_ids=("span:learned:0",),
                start_offset=0,
                end_offset=min(len(request.caller_text), 256),
            )
        )
        self._ensure_field_provenance(request, extracted)
        candidate = self._build_candidate(
            request,
            extracted,
            mode=FormalizationMode.LEARNED_CANDIDATE,
            authority=AuthorityCeiling.CANDIDATE,
            goal_suffix="learned",
        )
        return candidate

    # -- candidate assembly ------------------------------------------------

    def _build_candidate(
        self,
        request: EndGoalFormalizerRequest,
        extracted: _Extracted,
        *,
        mode: FormalizationMode | None = None,
        authority: AuthorityCeiling = AuthorityCeiling.CANDIDATE,
        goal_suffix: str = "",
    ) -> EndGoalCandidate:
        mode = mode or extracted.mode
        goal_id = request.goal_id or "goal:end-goal"
        if goal_suffix:
            goal_id = f"{goal_id}:{goal_suffix}"
        root_goal_id = request.root_goal_id or request.goal_id or goal_id

        bounds_payload: dict[str, Any] = {
            "schema": ResourceBounds.SCHEMA,
            "wall_time_ms": extracted.bound_fields.get(
                "wall_time_ms", request.bounds.wall_time_ms
            ),
            "memory_bytes": extracted.bound_fields.get(
                "memory_bytes", request.bounds.memory_bytes
            ),
            "max_steps": extracted.bound_fields.get(
                "max_steps", request.bounds.max_steps
            ),
            "max_depth": extracted.bound_fields.get(
                "max_depth", request.bounds.max_depth
            ),
            "max_nodes": extracted.bound_fields.get(
                "max_nodes", request.bounds.max_nodes
            ),
            "max_candidates": extracted.bound_fields.get(
                "max_candidates", request.bounds.max_candidates
            ),
            "model_token_limit": extracted.bound_fields.get(
                "model_token_limit", request.bounds.model_token_limit
            ),
            "network_allowed": (
                extracted.network_allowed or request.bounds.network_allowed
            ),
            "extra": {
                **dict(request.bounds.extra),
                **extracted.extra_bounds,
            },
        }
        bounds = ResourceBounds.from_dict(bounds_payload)

        # Deduplicate sequences while preserving contract sorting rules.
        actors = tuple(dict.fromkeys(extracted.actors))
        state_variables = tuple(dict.fromkeys(extracted.state_variables))
        transitions = tuple(dict.fromkeys(extracted.transitions))
        provider_ids = tuple(
            dict.fromkeys(
                list(extracted.provider_ids) + list(request.provider_ids)
            )
        )
        quantifiers = tuple(dict.fromkeys(extracted.quantifiers))
        acceptance = tuple(dict.fromkeys(extracted.acceptance_evidence))
        receipts = tuple(dict.fromkeys(extracted.expected_receipt_classes))
        unsupported = tuple(dict.fromkeys(extracted.unsupported_semantics))

        source = SourceSpanBinding(
            tree_id=request.source.tree_id,
            source_ref_ids=tuple(
                dict.fromkeys(
                    list(request.source.source_ref_ids)
                    + list(request.repository_source_ref_ids)
                    + [self._prompt_source_ref(request)]
                )
            ),
            span_ids=tuple(
                dict.fromkeys(
                    list(request.source.span_ids)
                    + [p.span_ids[0] for p in extracted.provenance if p.span_ids]
                )
            ),
            ast_scope_ids=request.source.ast_scope_ids,
            snapshot_id=request.source.snapshot_id,
        )

        # Authority: learned path stays at candidate; controlled may be advisory.
        end_authority = authority
        if mode is FormalizationMode.LEARNED_CANDIDATE:
            end_authority = AuthorityCeiling.CANDIDATE
        elif mode is FormalizationMode.CONTROLLED_LANGUAGE:
            end_authority = AuthorityCeiling.ADVISORY
        else:
            end_authority = AuthorityCeiling.CANDIDATE

        # Ambiguity: single interpretation from formalizer; selection is out of scope.
        ambiguity = AmbiguityStatus.NONE
        if extracted.property_class is PropertyClass.UNSPECIFIED:
            ambiguity = AmbiguityStatus.UNSUPPORTED

        # Provisional controlled English (required non-empty by EndGoalInterpretation).
        controlled_english = self._provisional_controlled_english(
            property_class=extracted.property_class,
            quantifiers=quantifiers,
            actors=actors,
            current_state=extracted.current_state,
            target_state=extracted.target_state,
            transitions=transitions,
            environment=extracted.environment,
            assumptions=tuple(extracted.assumptions),
            unsupported=unsupported,
        )
        interpretation = EndGoalInterpretation(
            interpretation_id=f"interp:{goal_id}",
            controlled_english=controlled_english,
            property_class=extracted.property_class,
            quantifiers=quantifiers,
            current_state=dict(extracted.current_state),
            target_state=dict(extracted.target_state),
            environment=dict(extracted.environment),
            semantic_diff={},
            unresolved_fields=tuple(self._underspecified_fields(extracted)),
            selected=False,
        )

        end_goal = EndGoalSpec(
            goal_id=goal_id,
            root_goal_id=root_goal_id,
            caller_text=request.caller_text,
            source=source,
            property_class=extracted.property_class,
            quantifiers=quantifiers,
            actors=actors,
            state_variables=state_variables,
            current_state=dict(extracted.current_state),
            target_state=dict(extracted.target_state),
            transitions=transitions,
            environment=dict(extracted.environment),
            interference=dict(extracted.interference),
            assumptions=tuple(extracted.assumptions),
            logic_family=extracted.logic_family or request.logic_family,
            provider_ids=provider_ids,
            assurance_target=extracted.assurance_target,
            bounds=bounds,
            provenance=tuple(extracted.provenance),
            interpretations=(interpretation,),
            ambiguity_status=ambiguity,
            unsupported_semantics=unsupported,
            translation_loss=(),
            acceptance_evidence=acceptance,
            expected_receipt_classes=receipts,
            status="candidate",
            authority=end_authority,
            proof_claimed=False,
            completion_claimed=False,
        )
        # Prefer the full renderer once the EndGoalSpec is valid.
        controlled_english = render_controlled_english(end_goal)
        if controlled_english != interpretation.controlled_english:
            interpretation = EndGoalInterpretation(
                interpretation_id=interpretation.interpretation_id,
                controlled_english=controlled_english,
                property_class=interpretation.property_class,
                quantifiers=interpretation.quantifiers,
                current_state=interpretation.current_state,
                target_state=interpretation.target_state,
                environment=interpretation.environment,
                semantic_diff=interpretation.semantic_diff,
                unresolved_fields=interpretation.unresolved_fields,
                selected=False,
            )
            end_goal = EndGoalSpec(
                goal_id=end_goal.goal_id,
                root_goal_id=end_goal.root_goal_id,
                caller_text=end_goal.caller_text,
                source=end_goal.source,
                property_class=end_goal.property_class,
                quantifiers=end_goal.quantifiers,
                actors=end_goal.actors,
                state_variables=end_goal.state_variables,
                current_state=end_goal.current_state,
                target_state=end_goal.target_state,
                transitions=end_goal.transitions,
                environment=end_goal.environment,
                interference=end_goal.interference,
                assumptions=end_goal.assumptions,
                logic_family=end_goal.logic_family,
                provider_ids=end_goal.provider_ids,
                assurance_target=end_goal.assurance_target,
                bounds=end_goal.bounds,
                provenance=end_goal.provenance,
                interpretations=(interpretation,),
                ambiguity_status=end_goal.ambiguity_status,
                unsupported_semantics=end_goal.unsupported_semantics,
                translation_loss=end_goal.translation_loss,
                acceptance_evidence=end_goal.acceptance_evidence,
                expected_receipt_classes=end_goal.expected_receipt_classes,
                status=end_goal.status,
                authority=end_goal.authority,
                proof_claimed=False,
                completion_claimed=False,
            )

        candidate_id = (
            f"candidate:{mode.value}:{end_goal.content_id[7:23]}"
        )
        return EndGoalCandidate(
            candidate_id=candidate_id,
            end_goal=end_goal,
            mode=mode,
            controlled_english=controlled_english,
            authority=end_authority
            if end_authority
            in {
                AuthorityCeiling.NONE,
                AuthorityCeiling.ADVISORY,
                AuthorityCeiling.CANDIDATE,
            }
            else AuthorityCeiling.CANDIDATE,
            admitted=False,
            selected=False,
            diagnostics=tuple(extracted.diagnostics),
        )

    # -- policy checks -----------------------------------------------------

    def _scan_hidden_assumptions(
        self, text: str
    ) -> list[FormalizationDiagnostic]:
        findings: list[FormalizationDiagnostic] = []
        for pattern in _HIDDEN_ASSUMPTION_PATTERNS:
            match = pattern.search(text)
            if match:
                findings.append(
                    FormalizationDiagnostic(
                        code="hidden_assumption",
                        message=(
                            "hidden or implicit assumptions are rejected; "
                            "declare them with ASSUME and source spans"
                        ),
                        severity="error",
                        phrase=match.group(0),
                    )
                )
        return findings

    def _grounded_identifier_set(
        self, request: EndGoalFormalizerRequest
    ) -> set[str]:
        grounded = set(request.known_identifiers)
        grounded.update(_extract_identifiers(request.caller_text))
        # Tokens that appear literally in the prompt are grounded even if reserved.
        for match in _IDENT_RE.finditer(request.caller_text):
            grounded.add(match.group(1))
        for ref in request.repository_source_ref_ids:
            grounded.add(ref)
            grounded.update(_extract_identifiers(ref))
        for ref in request.source.source_ref_ids:
            grounded.add(ref)
            grounded.update(_extract_identifiers(ref))
        for scope in request.source.ast_scope_ids:
            grounded.add(scope)
            grounded.update(_extract_identifiers(scope))
        return grounded

    def _check_identifier_grounding(
        self,
        request: EndGoalFormalizerRequest,
        extracted: _Extracted,
    ) -> list[FormalizationDiagnostic]:
        errors: list[FormalizationDiagnostic] = []
        grounded = self._grounded_identifier_set(request)
        grounded_lower = {g.lower() for g in grounded}

        # Hidden assumption markers from overlay.
        for ident in sorted(extracted.required_identifiers):
            if ident.startswith("__hidden_assumption__"):
                errors.append(
                    FormalizationDiagnostic(
                        code="hidden_assumption",
                        message=(
                            "assumption statement is not grounded in caller text"
                        ),
                        severity="error",
                    )
                )
                continue
            if (
                ident not in grounded
                and ident.lower() not in grounded_lower
            ):
                errors.append(
                    FormalizationDiagnostic(
                        code="ungrounded_identifier",
                        message=(
                            f"identifier {ident!r} is not present in prompt "
                            "or repository bindings"
                        ),
                        severity="error",
                        phrase=ident,
                    )
                )

        # Free identifiers in assumptions statements are OK if the statement is grounded.
        # Reject known-identifiers denylist if provided via meta.
        denied = set(request.meta.get("denied_identifiers") or ())
        for ident in sorted(extracted.declared_identifiers):
            if ident in denied:
                errors.append(
                    FormalizationDiagnostic(
                        code="denied_identifier",
                        message=f"identifier {ident!r} is explicitly denied",
                        severity="error",
                        phrase=ident,
                    )
                )
        return errors

    def _underspecified_fields(self, extracted: _Extracted) -> list[str]:
        missing: list[str] = []
        if extracted.property_class is PropertyClass.UNSPECIFIED:
            missing.append("property_class")
        if not extracted.quantifiers:
            missing.append("quantifiers")
        if not extracted.target_state and extracted.property_class in {
            PropertyClass.EXISTENTIAL_REACHABILITY,
            PropertyClass.UNIVERSAL_REACHABILITY,
            PropertyClass.INEVITABILITY,
            PropertyClass.LIVENESS,
        }:
            missing.append("target_state")
        if not extracted.provenance:
            missing.append("provenance")
        return missing

    def _ensure_field_provenance(
        self,
        request: EndGoalFormalizerRequest,
        extracted: _Extracted,
    ) -> None:
        """Guarantee every populated clause family has at least one provenance row."""

        prompt_ref = self._prompt_source_ref(request)
        existing_kinds = {
            p.clause_id.split(":")[1]
            for p in extracted.provenance
            if p.clause_id.startswith("clause:")
        }
        # Also accept kinds from phrase_hits already converted.
        for p in extracted.provenance:
            parts = p.clause_id.split(":")
            if len(parts) >= 2:
                existing_kinds.add(parts[1])

        def _add(kind: str, phrase: str) -> None:
            if kind in existing_kinds:
                return
            start, end = _find_span(request.caller_text, phrase)
            if start == end and phrase:
                # Fall back to whole-prompt span when phrase is synthetic.
                start, end = 0, min(len(request.caller_text), max(len(phrase), 1))
            index = len(extracted.provenance)
            extracted.provenance.append(
                PhraseProvenance(
                    phrase=phrase[:2048] or kind,
                    clause_id=_clause_id(kind, index, phrase),
                    source_ref_ids=(prompt_ref,),
                    span_ids=(f"span:{kind}:{index}",),
                    start_offset=start,
                    end_offset=end,
                )
            )
            existing_kinds.add(kind)

        if extracted.property_class is not PropertyClass.UNSPECIFIED:
            _add("property", extracted.property_class.value)
        if extracted.quantifiers:
            _add(
                "quantifier",
                ",".join(q.value for q in extracted.quantifiers),
            )
        if extracted.actors:
            _add("actor", ",".join(sorted(set(extracted.actors))))
        if extracted.state_variables:
            _add(
                "state",
                ",".join(sorted(set(extracted.state_variables))),
            )
        if extracted.current_state:
            _add("current", json.dumps(extracted.current_state, sort_keys=True))
        if extracted.target_state:
            _add("target", json.dumps(extracted.target_state, sort_keys=True))
        if extracted.transitions:
            _add("transition", ",".join(sorted(set(extracted.transitions))))
        if extracted.environment:
            _add(
                "environment",
                json.dumps(extracted.environment, sort_keys=True, default=str),
            )
        if extracted.assumptions:
            _add(
                "assume",
                ";".join(a.statement for a in extracted.assumptions)[:256],
            )
        if extracted.bound_fields or extracted.extra_bounds or extracted.network_allowed:
            _add("bound", "bounds")
        if extracted.acceptance_evidence:
            _add(
                "accept",
                ",".join(sorted(set(extracted.acceptance_evidence))),
            )
        if extracted.assurance_target is not AuthorityCeiling.BOUNDED or any(
            hit[0] == "assurance" for hit in extracted.phrase_hits
        ):
            _add("assurance", extracted.assurance_target.value)
        if extracted.logic_family:
            _add("logic", extracted.logic_family)
        if extracted.unsupported_semantics:
            _add(
                "unsupported",
                ",".join(sorted(set(extracted.unsupported_semantics))),
            )
        # Always bind the full prompt as a root provenance span.
        if "prompt" not in existing_kinds:
            extracted.provenance.insert(
                0,
                PhraseProvenance(
                    phrase=request.caller_text[:2048],
                    clause_id="clause:prompt:0",
                    source_ref_ids=(prompt_ref,),
                    span_ids=("span:prompt:0",),
                    start_offset=0,
                    end_offset=len(request.caller_text),
                ),
            )

    # -- utilities ---------------------------------------------------------

    @staticmethod
    def _prompt_source_ref(request: EndGoalFormalizerRequest) -> str:
        if request.source.source_ref_ids:
            # Prefer an explicit prompt ref if present.
            for ref in request.source.source_ref_ids:
                if "prompt" in ref.lower() or "caller" in ref.lower():
                    return ref
            return request.source.source_ref_ids[0]
        return "source:prompt"

    @staticmethod
    def _split_kv(body: str, label: str) -> tuple[str, str]:
        match = _KV_RE.match(body)
        if not match:
            raise EndGoalFormalizerError(
                f"{label} expects key=value, got {body!r}"
            )
        return match.group("k"), match.group("v")

    @staticmethod
    def _coerce_value(raw: str) -> Any:
        text = raw.strip()
        as_bool = _parse_boolish(text)
        if as_bool is not None:
            return as_bool
        as_int = _parse_intish(text)
        if as_int is not None:
            return as_int
        return text

    def _apply_bound(self, body: str, extracted: _Extracted) -> None:
        key, value = self._split_kv(body, "BOUND")
        field_name = _BOUND_FIELD_ALIASES.get(
            key.strip().lower().replace("-", "_"), key.strip()
        )
        if field_name == "network_allowed":
            parsed = _parse_boolish(value)
            if parsed is None:
                raise EndGoalFormalizerError(
                    f"BOUND network_allowed expects a boolean, got {value!r}"
                )
            extracted.network_allowed = parsed
            return
        number = _parse_intish(value)
        if number is None:
            raise EndGoalFormalizerError(
                f"BOUND {key} expects a non-negative integer, got {value!r}"
            )
        if field_name in {
            "wall_time_ms",
            "memory_bytes",
            "max_steps",
            "max_depth",
            "max_nodes",
            "max_candidates",
            "model_token_limit",
        }:
            extracted.bound_fields[field_name] = number
        else:
            extracted.extra_bounds[field_name] = number

    @staticmethod
    def _default_quantifiers(
        property_class: PropertyClass,
    ) -> list[QuantifierKind]:
        defaults: dict[PropertyClass, list[QuantifierKind]] = {
            PropertyClass.EXISTENTIAL_REACHABILITY: [
                QuantifierKind.EXISTS,
                QuantifierKind.EVENTUALLY,
            ],
            PropertyClass.UNIVERSAL_REACHABILITY: [
                QuantifierKind.FORALL,
                QuantifierKind.EVENTUALLY,
            ],
            PropertyClass.INEVITABILITY: [QuantifierKind.EVENTUALLY],
            PropertyClass.LIVENESS: [QuantifierKind.EVENTUALLY],
            PropertyClass.INVARIANCE: [QuantifierKind.ALWAYS],
            PropertyClass.SAFETY: [QuantifierKind.ALWAYS],
            PropertyClass.TERMINATION: [QuantifierKind.EVENTUALLY],
            PropertyClass.REFINEMENT: [QuantifierKind.NONE],
            PropertyClass.AUTHORIZATION: [QuantifierKind.FORALL],
            PropertyClass.PROTOCOL: [QuantifierKind.FORALL],
            PropertyClass.UNSPECIFIED: [],
        }
        return list(defaults.get(property_class, []))

    @staticmethod
    def _provisional_controlled_english(
        *,
        property_class: PropertyClass,
        quantifiers: Sequence[QuantifierKind],
        actors: Sequence[str],
        current_state: Mapping[str, Any],
        target_state: Mapping[str, Any],
        transitions: Sequence[str],
        environment: Mapping[str, Any],
        assumptions: Sequence[AssumptionBinding],
        unsupported: Sequence[str],
    ) -> str:
        """Build a non-empty controlled-English summary before EndGoalSpec exists."""

        parts: list[str] = []
        prop = property_class.value.replace("_", " ")
        if actors:
            parts.append(f"Actors {', '.join(sorted(actors))} participate.")
        if current_state:
            state = ", ".join(
                f"{k}={v}" for k, v in sorted(current_state.items())
            )
            parts.append(f"Current state: {state}.")
        if target_state:
            state = ", ".join(
                f"{k}={v}" for k, v in sorted(target_state.items())
            )
            parts.append(f"Target state: {state}.")
        quant = ", ".join(q.value for q in quantifiers) or "unspecified"
        parts.append(
            f"Property class is {prop} under quantifiers [{quant}]."
        )
        if transitions:
            parts.append(
                f"Transitions: {', '.join(sorted(transitions))}."
            )
        if environment:
            env = ", ".join(
                f"{k}={v}" for k, v in sorted(environment.items())
            )
            parts.append(f"Environment: {env}.")
        if assumptions:
            parts.append(
                "Assumptions: "
                + "; ".join(
                    f"{a.assumption_class.value}:{a.statement}"
                    for a in sorted(
                        assumptions, key=lambda x: x.assumption_id
                    )
                )
                + "."
            )
        if unsupported:
            parts.append(
                "Unsupported: " + ", ".join(sorted(unsupported)) + "."
            )
        if not parts:
            parts.append(f"Underspecified end goal ({prop}).")
        return " ".join(parts)


__all__ = [
    "END_GOAL_FORMALIZER_INTERFACE",
    "END_GOAL_FORMALIZER_VERSION",
    "END_GOAL_FORMALIZER_SCHEMA",
    "END_GOAL_FORMALIZER_REQUEST_SCHEMA",
    "END_GOAL_FORMALIZER_RESULT_SCHEMA",
    "END_GOAL_FORMALIZER_PRODUCER_ID",
    "EndGoalFormalizerError",
    "FormalizationMode",
    "FormalizationStatus",
    "EndGoalFormalizerRequest",
    "FormalizationDiagnostic",
    "EndGoalCandidate",
    "EndGoalFormalizerResult",
    "EndGoalFormalizer",
    "render_controlled_language",
    "render_controlled_english",
]
