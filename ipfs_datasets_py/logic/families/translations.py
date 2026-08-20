"""Unified translation preservation, loss, and authority contracts.

``TranslationContract@2`` makes every cross-family (or family-to-backend)
translation edge explicit: source/target endpoints, preservation relation,
independent proof-safe and counterexample-safe polarity, assumptions, total
node/symbol maps, loss dispositions, authority ceiling, and content identities
for compiler, profile, and configuration.

``TranslationCompositionReceipt@1`` records the weakest-link composition of one
or more contracts.  Composed routes inherit the weakest preservation guarantee
and the lowest authority ceiling; unknown nodes and assumptions never
disappear; silent node drops are rejected.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity

from .models import (
    DESCRIPTOR_VERSION,
    EvidenceAuthority,
    TaxonomyError,
    TranslationKind,
    _enum,
    _identifier,
    _strings,
    _text,
    _version,
)


CONTRACT_INTERFACE: Final = "TranslationContract@2"
COMPOSITION_INTERFACE: Final = "TranslationCompositionReceipt@1"
CONTRACT_SCHEMA_VERSION: Final = "logic-family-translation-contract/v2"
COMPOSITION_SCHEMA_VERSION: Final = "logic-family-translation-composition/v1"
ENDPOINT_SCHEMA_VERSION: Final = "logic-family-translation-endpoint/v1"
NODE_MAP_SCHEMA_VERSION: Final = "logic-family-translation-node-map/v1"
SYMBOL_MAP_SCHEMA_VERSION: Final = "logic-family-translation-symbol-map/v1"
ASSUMPTION_SET_SCHEMA_VERSION: Final = "logic-family-translation-assumptions/v1"
IDENTITY_BUNDLE_SCHEMA_VERSION: Final = "logic-family-translation-identities/v1"

CONTRACT_IDENTITY_DOMAIN: Final = "logic.family.translation.contract"
COMPOSITION_IDENTITY_DOMAIN: Final = "logic.family.translation.composition"


class TranslationContractError(TaxonomyError):
    """Raised when a translation contract or composition is invalid."""


class PreservationRelation(str, Enum):
    """Semantic guarantee claimed by one translation edge.

    Ordered from strongest (exact equivalence) to weakest (heuristic) for
    weakest-link composition.  Values match the plan vocabulary.
    """

    EXACT_EQUIVALENCE = "exact_equivalence"
    EQUISATISFIABLE = "equisatisfiable"
    THEOREM_PRESERVING = "theorem_preserving"
    MODEL_PRESERVING = "model_preserving"
    TRACE_PRESERVING = "trace_preserving"
    CONSERVATIVE_OVER_APPROXIMATION = "conservative_over_approximation"
    CONSERVATIVE_UNDER_APPROXIMATION = "conservative_under_approximation"
    BOUNDED = "bounded"
    APPROXIMATE = "approximate"
    HEURISTIC = "heuristic"


class NodeDisposition(str, Enum):
    """How a source node or symbol is treated by a translation.

    ``dropped`` is allowed only when declared explicitly.  Missing map entries
    are silent drops and are rejected.  ``unknown`` cannot be upgraded to a
    stronger disposition under composition.
    """

    PRESERVED = "preserved"
    MAPPED = "mapped"
    APPROXIMATED = "approximated"
    SYNTHESIZED = "synthesized"
    UNSUPPORTED = "unsupported"
    DROPPED = "dropped"
    UNKNOWN = "unknown"


class OpaqueDisposition(str, Enum):
    """Outcome for unknown or opaque semantics (never implicit success)."""

    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"
    APPROVAL_REQUIRED = "approval_required"


# Higher rank = stronger guarantee.  Composition takes the minimum.
_PRESERVATION_RANK: Final[dict[PreservationRelation, int]] = {
    PreservationRelation.EXACT_EQUIVALENCE: 9,
    PreservationRelation.EQUISATISFIABLE: 8,
    PreservationRelation.THEOREM_PRESERVING: 7,
    PreservationRelation.MODEL_PRESERVING: 6,
    PreservationRelation.TRACE_PRESERVING: 5,
    PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION: 4,
    PreservationRelation.CONSERVATIVE_UNDER_APPROXIMATION: 3,
    PreservationRelation.BOUNDED: 2,
    PreservationRelation.APPROXIMATE: 1,
    PreservationRelation.HEURISTIC: 0,
}

_AUTHORITY_RANK: Final[dict[EvidenceAuthority, int]] = {
    EvidenceAuthority.AUTHORITATIVE: 4,
    EvidenceAuthority.INDEPENDENTLY_CHECKABLE: 3,
    EvidenceAuthority.BOUNDED: 2,
    EvidenceAuthority.ADVISORY: 1,
    EvidenceAuthority.NONE: 0,
}

# Higher rank = less lossy.  Composition takes the minimum (more lossy wins).
_DISPOSITION_RANK: Final[dict[NodeDisposition, int]] = {
    NodeDisposition.PRESERVED: 6,
    NodeDisposition.MAPPED: 5,
    NodeDisposition.APPROXIMATED: 4,
    NodeDisposition.SYNTHESIZED: 3,
    NodeDisposition.UNSUPPORTED: 2,
    NodeDisposition.DROPPED: 1,
    NodeDisposition.UNKNOWN: 0,
}

_MAXIMUM_AUTHORITY: Final[dict[PreservationRelation, EvidenceAuthority]] = {
    PreservationRelation.EXACT_EQUIVALENCE: EvidenceAuthority.AUTHORITATIVE,
    PreservationRelation.EQUISATISFIABLE: EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    PreservationRelation.THEOREM_PRESERVING: EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    PreservationRelation.MODEL_PRESERVING: EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    PreservationRelation.TRACE_PRESERVING: EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION: EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    PreservationRelation.CONSERVATIVE_UNDER_APPROXIMATION: EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    PreservationRelation.BOUNDED: EvidenceAuthority.BOUNDED,
    PreservationRelation.APPROXIMATE: EvidenceAuthority.ADVISORY,
    PreservationRelation.HEURISTIC: EvidenceAuthority.NONE,
}

_TAXONOMY_KIND: Final[dict[PreservationRelation, TranslationKind]] = {
    PreservationRelation.EXACT_EQUIVALENCE: TranslationKind.LOSSLESS,
    PreservationRelation.EQUISATISFIABLE: TranslationKind.EQUISATISFIABLE,
    PreservationRelation.THEOREM_PRESERVING: TranslationKind.LOSSLESS,
    PreservationRelation.MODEL_PRESERVING: TranslationKind.EQUISATISFIABLE,
    PreservationRelation.TRACE_PRESERVING: TranslationKind.EQUISATISFIABLE,
    PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION: TranslationKind.SOUND_OVER_APPROXIMATION,
    PreservationRelation.CONSERVATIVE_UNDER_APPROXIMATION: TranslationKind.SOUND_UNDER_APPROXIMATION,
    PreservationRelation.BOUNDED: TranslationKind.SOUND_OVER_APPROXIMATION,
    PreservationRelation.APPROXIMATE: TranslationKind.SOUND_OVER_APPROXIMATION,
    PreservationRelation.HEURISTIC: TranslationKind.HEURISTIC,
}


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TranslationContractError(f"{field_name} must be a bool")
    return value


def _optional_text(value: object, field_name: str) -> str:
    if value is None or value == "":
        return ""
    return _text(value, field_name)


def _optional_identifier(value: object, field_name: str) -> str:
    if value is None or value == "":
        return ""
    return _identifier(value, field_name)


def _ordered_strings(
    value: Sequence[str] | None,
    field_name: str,
    *,
    identifiers: bool = False,
) -> tuple[str, ...]:
    """Validate a sequence while preserving caller order (composition chains)."""

    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TranslationContractError(f"{field_name} must be a sequence of strings")
    validator = _identifier if identifiers else _text
    result = tuple(validator(item, f"{field_name} item") for item in value)
    if len(set(result)) != len(result):
        raise TranslationContractError(f"{field_name} must not contain duplicates")
    return result


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TranslationContractError(f"{field_name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise TranslationContractError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _records(
    values: Sequence[Any] | object,
    record_type: type[Any],
    field_name: str,
) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise TranslationContractError(f"{field_name} must be a sequence")
    result: list[Any] = []
    for item in values:
        if isinstance(item, record_type):
            result.append(item)
        elif isinstance(item, Mapping):
            result.append(record_type.from_dict(item))
        else:
            raise TranslationContractError(
                f"{field_name} items must be {record_type.__name__} values"
            )
    return tuple(result)


def preservation_rank(relation: PreservationRelation | str) -> int:
    """Return the strength rank of a preservation relation (higher is stronger)."""

    selected = _enum(relation, PreservationRelation, "preservation_relation")
    return _PRESERVATION_RANK[selected]


def authority_rank(authority: EvidenceAuthority | str) -> int:
    """Return the strength rank of an evidence authority (higher is stronger)."""

    selected = _enum(authority, EvidenceAuthority, "authority")
    return _AUTHORITY_RANK[selected]


def disposition_rank(disposition: NodeDisposition | str) -> int:
    """Return the strength rank of a node disposition (higher is less lossy)."""

    selected = _enum(disposition, NodeDisposition, "disposition")
    return _DISPOSITION_RANK[selected]


def weaker_preservation(
    left: PreservationRelation | str,
    right: PreservationRelation | str,
) -> PreservationRelation:
    """Return the weaker of two preservation relations (weakest-link)."""

    a = _enum(left, PreservationRelation, "left")
    b = _enum(right, PreservationRelation, "right")
    if a is b:
        return a
    if _PRESERVATION_RANK[a] < _PRESERVATION_RANK[b]:
        return a
    if _PRESERVATION_RANK[b] < _PRESERVATION_RANK[a]:
        return b
    # Incomparable equal-rank kinds demote rather than invent a stronger meet.
    return PreservationRelation.APPROXIMATE


def weaker_authority(
    left: EvidenceAuthority | str,
    right: EvidenceAuthority | str,
) -> EvidenceAuthority:
    """Return the lower of two authority ceilings."""

    a = _enum(left, EvidenceAuthority, "left")
    b = _enum(right, EvidenceAuthority, "right")
    return a if _AUTHORITY_RANK[a] <= _AUTHORITY_RANK[b] else b


def weaker_disposition(
    left: NodeDisposition | str,
    right: NodeDisposition | str,
) -> NodeDisposition:
    """Return the more lossy of two node dispositions."""

    a = _enum(left, NodeDisposition, "left")
    b = _enum(right, NodeDisposition, "right")
    return a if _DISPOSITION_RANK[a] <= _DISPOSITION_RANK[b] else b


def maximum_authority_for(
    relation: PreservationRelation | str,
) -> EvidenceAuthority:
    """Return the hard authority ceiling for a preservation relation."""

    return _MAXIMUM_AUTHORITY[_enum(relation, PreservationRelation, "relation")]


def taxonomy_translation_kind(
    relation: PreservationRelation | str,
) -> TranslationKind:
    """Map a preservation relation onto the coarser taxonomy TranslationKind."""

    return _TAXONOMY_KIND[_enum(relation, PreservationRelation, "relation")]


def authority_at_most(
    authority: EvidenceAuthority | str,
    ceiling: EvidenceAuthority | str,
) -> bool:
    """Return whether *authority* is no stronger than *ceiling*."""

    return authority_rank(authority) <= authority_rank(ceiling)


@dataclass(frozen=True, slots=True)
class TranslationEndpoint:
    """Exact source or target endpoint of a translation edge."""

    family_id: str
    profile_id: str = ""
    fragment_id: str = ""
    schema_id: str = ""
    notation_id: str = ""
    content_identity: str = ""
    schema_version: str = ENDPOINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "family_id", _identifier(self.family_id, "family_id")
        )
        object.__setattr__(
            self, "profile_id", _optional_identifier(self.profile_id, "profile_id")
        )
        object.__setattr__(
            self, "fragment_id", _optional_identifier(self.fragment_id, "fragment_id")
        )
        object.__setattr__(
            self, "schema_id", _optional_identifier(self.schema_id, "schema_id")
        )
        object.__setattr__(
            self, "notation_id", _optional_identifier(self.notation_id, "notation_id")
        )
        object.__setattr__(
            self,
            "content_identity",
            _optional_text(self.content_identity, "content_identity"),
        )
        if self.schema_version != ENDPOINT_SCHEMA_VERSION:
            raise TranslationContractError(
                f"unsupported endpoint schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_identity": self.content_identity,
            "family_id": self.family_id,
            "fragment_id": self.fragment_id,
            "notation_id": self.notation_id,
            "profile_id": self.profile_id,
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TranslationEndpoint":
        value = _mapping(value, "translation endpoint")
        _reject_unknown(
            value,
            frozenset(
                {
                    "content_identity",
                    "family_id",
                    "fragment_id",
                    "notation_id",
                    "profile_id",
                    "schema_id",
                    "schema_version",
                }
            ),
            "translation endpoint",
        )
        return cls(
            family_id=value.get("family_id", ""),
            profile_id=value.get("profile_id", ""),
            fragment_id=value.get("fragment_id", ""),
            schema_id=value.get("schema_id", ""),
            notation_id=value.get("notation_id", ""),
            content_identity=value.get("content_identity", ""),
            schema_version=value.get("schema_version", ENDPOINT_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class TranslationIdentities:
    """Content identities that pin compiler, profile, and configuration."""

    compiler_identity: str
    profile_identity: str
    config_identity: str
    source_identity: str = ""
    target_identity: str = ""
    environment_identity: str = ""
    schema_version: str = IDENTITY_BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "compiler_identity",
            _text(self.compiler_identity, "compiler_identity"),
        )
        object.__setattr__(
            self,
            "profile_identity",
            _text(self.profile_identity, "profile_identity"),
        )
        object.__setattr__(
            self,
            "config_identity",
            _text(self.config_identity, "config_identity"),
        )
        for name in (
            "source_identity",
            "target_identity",
            "environment_identity",
        ):
            object.__setattr__(
                self, name, _optional_text(getattr(self, name), name)
            )
        if self.schema_version != IDENTITY_BUNDLE_SCHEMA_VERSION:
            raise TranslationContractError(
                f"unsupported identity bundle schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "compiler_identity": self.compiler_identity,
            "config_identity": self.config_identity,
            "environment_identity": self.environment_identity,
            "profile_identity": self.profile_identity,
            "schema_version": self.schema_version,
            "source_identity": self.source_identity,
            "target_identity": self.target_identity,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TranslationIdentities":
        value = _mapping(value, "translation identities")
        _reject_unknown(
            value,
            frozenset(
                {
                    "compiler_identity",
                    "config_identity",
                    "environment_identity",
                    "profile_identity",
                    "schema_version",
                    "source_identity",
                    "target_identity",
                }
            ),
            "translation identities",
        )
        return cls(
            compiler_identity=value.get("compiler_identity", ""),
            profile_identity=value.get("profile_identity", ""),
            config_identity=value.get("config_identity", ""),
            source_identity=value.get("source_identity", ""),
            target_identity=value.get("target_identity", ""),
            environment_identity=value.get("environment_identity", ""),
            schema_version=value.get(
                "schema_version", IDENTITY_BUNDLE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class TranslationAssumptionSet:
    """Explicit assumptions and semantic mutations introduced by translation."""

    axioms: tuple[str, ...] = ()
    closure_assumptions: tuple[str, ...] = ()
    fairness: tuple[str, ...] = ()
    bounds: tuple[str, ...] = ()
    attacker_model: tuple[str, ...] = ()
    domain_changes: tuple[str, ...] = ()
    other: tuple[str, ...] = ()
    schema_version: str = ASSUMPTION_SET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "axioms",
            "closure_assumptions",
            "fairness",
            "bounds",
            "attacker_model",
            "domain_changes",
            "other",
        ):
            object.__setattr__(
                self,
                name,
                _strings(getattr(self, name), name, identifiers=True),
            )
        if self.schema_version != ASSUMPTION_SET_SCHEMA_VERSION:
            raise TranslationContractError(
                f"unsupported assumption set schema {self.schema_version!r}"
            )

    @property
    def all_assumption_ids(self) -> tuple[str, ...]:
        """Return every declared assumption identifier in sorted order."""

        return tuple(
            sorted(
                {
                    *self.axioms,
                    *self.closure_assumptions,
                    *self.fairness,
                    *self.bounds,
                    *self.attacker_model,
                    *self.domain_changes,
                    *self.other,
                }
            )
        )

    def union(self, other: "TranslationAssumptionSet") -> "TranslationAssumptionSet":
        """Return the set-union of two assumption sets (never drops entries)."""

        if not isinstance(other, TranslationAssumptionSet):
            raise TranslationContractError(
                "assumption union requires TranslationAssumptionSet"
            )
        return TranslationAssumptionSet(
            axioms=tuple(sorted({*self.axioms, *other.axioms})),
            closure_assumptions=tuple(
                sorted({*self.closure_assumptions, *other.closure_assumptions})
            ),
            fairness=tuple(sorted({*self.fairness, *other.fairness})),
            bounds=tuple(sorted({*self.bounds, *other.bounds})),
            attacker_model=tuple(
                sorted({*self.attacker_model, *other.attacker_model})
            ),
            domain_changes=tuple(
                sorted({*self.domain_changes, *other.domain_changes})
            ),
            other=tuple(sorted({*self.other, *other.other})),
        )

    def issuperset(self, other: "TranslationAssumptionSet") -> bool:
        return set(other.all_assumption_ids).issubset(self.all_assumption_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attacker_model": list(self.attacker_model),
            "axioms": list(self.axioms),
            "bounds": list(self.bounds),
            "closure_assumptions": list(self.closure_assumptions),
            "domain_changes": list(self.domain_changes),
            "fairness": list(self.fairness),
            "other": list(self.other),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TranslationAssumptionSet":
        value = _mapping(value, "translation assumptions")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attacker_model",
                    "axioms",
                    "bounds",
                    "closure_assumptions",
                    "domain_changes",
                    "fairness",
                    "other",
                    "schema_version",
                }
            ),
            "translation assumptions",
        )
        return cls(
            axioms=tuple(value.get("axioms", ())),
            closure_assumptions=tuple(value.get("closure_assumptions", ())),
            fairness=tuple(value.get("fairness", ())),
            bounds=tuple(value.get("bounds", ())),
            attacker_model=tuple(value.get("attacker_model", ())),
            domain_changes=tuple(value.get("domain_changes", ())),
            other=tuple(value.get("other", ())),
            schema_version=value.get(
                "schema_version", ASSUMPTION_SET_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class NodeMapEntry:
    """One source-to-target node mapping with an explicit disposition."""

    source_node_id: str
    target_node_ids: tuple[str, ...] = ()
    disposition: NodeDisposition | str = NodeDisposition.MAPPED
    reason: str = ""
    schema_version: str = NODE_MAP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_node_id",
            _identifier(self.source_node_id, "source_node_id"),
        )
        object.__setattr__(
            self,
            "target_node_ids",
            _strings(self.target_node_ids, "target_node_ids", identifiers=True),
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, NodeDisposition, "disposition"),
        )
        object.__setattr__(
            self, "reason", _optional_text(self.reason, "reason")
        )
        if self.schema_version != NODE_MAP_SCHEMA_VERSION:
            raise TranslationContractError(
                f"unsupported node map schema {self.schema_version!r}"
            )
        if self.disposition is NodeDisposition.SYNTHESIZED:
            # Synthesized nodes are introduced by the translator; they may be
            # recorded with an empty source only via explicit synthesized maps
            # (source is still required as a stable handle).
            pass
        if (
            self.disposition
            in {
                NodeDisposition.PRESERVED,
                NodeDisposition.MAPPED,
                NodeDisposition.APPROXIMATED,
            }
            and not self.target_node_ids
        ):
            raise TranslationContractError(
                f"{self.disposition.value} node map entry requires target_node_ids"
            )
        if (
            self.disposition
            in {
                NodeDisposition.DROPPED,
                NodeDisposition.UNSUPPORTED,
                NodeDisposition.UNKNOWN,
            }
            and self.target_node_ids
        ):
            raise TranslationContractError(
                f"{self.disposition.value} node map entry cannot declare target_node_ids"
            )
        if self.disposition is NodeDisposition.DROPPED and not self.reason:
            raise TranslationContractError(
                "dropped nodes require an explicit reason (silent drops forbidden)"
            )
        if self.disposition is NodeDisposition.UNKNOWN and not self.reason:
            raise TranslationContractError(
                "unknown nodes require an explicit reason"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "source_node_id": self.source_node_id,
            "target_node_ids": list(self.target_node_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NodeMapEntry":
        value = _mapping(value, "node map entry")
        _reject_unknown(
            value,
            frozenset(
                {
                    "disposition",
                    "reason",
                    "schema_version",
                    "source_node_id",
                    "target_node_ids",
                }
            ),
            "node map entry",
        )
        return cls(
            source_node_id=value.get("source_node_id", ""),
            target_node_ids=tuple(value.get("target_node_ids", ())),
            disposition=value.get("disposition", NodeDisposition.MAPPED.value),
            reason=value.get("reason", ""),
            schema_version=value.get("schema_version", NODE_MAP_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class SymbolMapEntry:
    """One source-to-target symbol mapping with an explicit disposition."""

    source_symbol_id: str
    target_symbol_ids: tuple[str, ...] = ()
    disposition: NodeDisposition | str = NodeDisposition.MAPPED
    reason: str = ""
    schema_version: str = SYMBOL_MAP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_symbol_id",
            _identifier(self.source_symbol_id, "source_symbol_id"),
        )
        object.__setattr__(
            self,
            "target_symbol_ids",
            _strings(self.target_symbol_ids, "target_symbol_ids", identifiers=True),
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, NodeDisposition, "disposition"),
        )
        object.__setattr__(
            self, "reason", _optional_text(self.reason, "reason")
        )
        if self.schema_version != SYMBOL_MAP_SCHEMA_VERSION:
            raise TranslationContractError(
                f"unsupported symbol map schema {self.schema_version!r}"
            )
        if (
            self.disposition
            in {
                NodeDisposition.PRESERVED,
                NodeDisposition.MAPPED,
                NodeDisposition.APPROXIMATED,
            }
            and not self.target_symbol_ids
        ):
            raise TranslationContractError(
                f"{self.disposition.value} symbol map entry requires target_symbol_ids"
            )
        if (
            self.disposition
            in {
                NodeDisposition.DROPPED,
                NodeDisposition.UNSUPPORTED,
                NodeDisposition.UNKNOWN,
            }
            and self.target_symbol_ids
        ):
            raise TranslationContractError(
                f"{self.disposition.value} symbol map entry cannot declare target_symbol_ids"
            )
        if self.disposition is NodeDisposition.DROPPED and not self.reason:
            raise TranslationContractError(
                "dropped symbols require an explicit reason (silent drops forbidden)"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "source_symbol_id": self.source_symbol_id,
            "target_symbol_ids": list(self.target_symbol_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SymbolMapEntry":
        value = _mapping(value, "symbol map entry")
        _reject_unknown(
            value,
            frozenset(
                {
                    "disposition",
                    "reason",
                    "schema_version",
                    "source_symbol_id",
                    "target_symbol_ids",
                }
            ),
            "symbol map entry",
        )
        return cls(
            source_symbol_id=value.get("source_symbol_id", ""),
            target_symbol_ids=tuple(value.get("target_symbol_ids", ())),
            disposition=value.get("disposition", NodeDisposition.MAPPED.value),
            reason=value.get("reason", ""),
            schema_version=value.get(
                "schema_version", SYMBOL_MAP_SCHEMA_VERSION
            ),
        )


def _unique_node_map(
    entries: Sequence[NodeMapEntry], field_name: str = "node_map"
) -> tuple[NodeMapEntry, ...]:
    seen: set[str] = set()
    for entry in entries:
        if entry.source_node_id in seen:
            raise TranslationContractError(
                f"{field_name} must not contain duplicate source_node_id "
                f"{entry.source_node_id!r}"
            )
        seen.add(entry.source_node_id)
    return tuple(sorted(entries, key=lambda item: item.source_node_id))


def _unique_symbol_map(
    entries: Sequence[SymbolMapEntry], field_name: str = "symbol_map"
) -> tuple[SymbolMapEntry, ...]:
    seen: set[str] = set()
    for entry in entries:
        if entry.source_symbol_id in seen:
            raise TranslationContractError(
                f"{field_name} must not contain duplicate source_symbol_id "
                f"{entry.source_symbol_id!r}"
            )
        seen.add(entry.source_symbol_id)
    return tuple(sorted(entries, key=lambda item: item.source_symbol_id))


@dataclass(frozen=True, slots=True)
class TranslationContract:
    """Versioned preservation, loss, and authority contract (``TranslationContract@2``).

    Every field required by the plan is explicit.  Silent node drops are
    rejected: when ``required_source_node_ids`` is non-empty, every source node
    must appear in ``node_map`` with a declared disposition.
    """

    contract_id: str
    source: TranslationEndpoint
    target: TranslationEndpoint
    preservation: PreservationRelation | str
    identities: TranslationIdentities
    proof_safe: bool = False
    counterexample_safe: bool = False
    authority_ceiling: EvidenceAuthority | str = EvidenceAuthority.NONE
    assumptions: TranslationAssumptionSet = field(
        default_factory=TranslationAssumptionSet
    )
    node_map: tuple[NodeMapEntry, ...] = ()
    symbol_map: tuple[SymbolMapEntry, ...] = ()
    required_source_node_ids: tuple[str, ...] = ()
    required_source_symbol_ids: tuple[str, ...] = ()
    feature_preconditions: tuple[str, ...] = ()
    unsupported_constructs: tuple[str, ...] = ()
    opaque_disposition: OpaqueDisposition | str = OpaqueDisposition.UNSUPPORTED
    checker_route: str = ""
    reconstruction_route: str = ""
    description: str = ""
    version: str = DESCRIPTOR_VERSION
    contract_content_id: str = ""

    schema_version: ClassVar[str] = CONTRACT_SCHEMA_VERSION
    interface: ClassVar[str] = CONTRACT_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "contract_id", _identifier(self.contract_id, "contract_id")
        )
        source = self.source
        if isinstance(source, Mapping):
            source = TranslationEndpoint.from_dict(source)
        if not isinstance(source, TranslationEndpoint):
            raise TranslationContractError("source must be a TranslationEndpoint")
        object.__setattr__(self, "source", source)

        target = self.target
        if isinstance(target, Mapping):
            target = TranslationEndpoint.from_dict(target)
        if not isinstance(target, TranslationEndpoint):
            raise TranslationContractError("target must be a TranslationEndpoint")
        object.__setattr__(self, "target", target)

        object.__setattr__(
            self,
            "preservation",
            _enum(self.preservation, PreservationRelation, "preservation"),
        )
        object.__setattr__(self, "proof_safe", _bool(self.proof_safe, "proof_safe"))
        object.__setattr__(
            self,
            "counterexample_safe",
            _bool(self.counterexample_safe, "counterexample_safe"),
        )

        identities = self.identities
        if isinstance(identities, Mapping):
            identities = TranslationIdentities.from_dict(identities)
        if not isinstance(identities, TranslationIdentities):
            raise TranslationContractError(
                "identities must be a TranslationIdentities bundle"
            )
        object.__setattr__(self, "identities", identities)

        assumptions = self.assumptions
        if isinstance(assumptions, Mapping):
            assumptions = TranslationAssumptionSet.from_dict(assumptions)
        if not isinstance(assumptions, TranslationAssumptionSet):
            raise TranslationContractError(
                "assumptions must be a TranslationAssumptionSet"
            )
        object.__setattr__(self, "assumptions", assumptions)

        node_map = _unique_node_map(
            _records(self.node_map, NodeMapEntry, "node_map")
        )
        object.__setattr__(self, "node_map", node_map)
        symbol_map = _unique_symbol_map(
            _records(self.symbol_map, SymbolMapEntry, "symbol_map")
        )
        object.__setattr__(self, "symbol_map", symbol_map)

        object.__setattr__(
            self,
            "required_source_node_ids",
            _strings(
                self.required_source_node_ids,
                "required_source_node_ids",
                identifiers=True,
            ),
        )
        object.__setattr__(
            self,
            "required_source_symbol_ids",
            _strings(
                self.required_source_symbol_ids,
                "required_source_symbol_ids",
                identifiers=True,
            ),
        )
        object.__setattr__(
            self,
            "feature_preconditions",
            _strings(
                self.feature_preconditions,
                "feature_preconditions",
                identifiers=True,
            ),
        )
        object.__setattr__(
            self,
            "unsupported_constructs",
            _strings(
                self.unsupported_constructs,
                "unsupported_constructs",
                identifiers=True,
            ),
        )
        object.__setattr__(
            self,
            "opaque_disposition",
            _enum(
                self.opaque_disposition, OpaqueDisposition, "opaque_disposition"
            ),
        )
        object.__setattr__(
            self, "checker_route", _optional_text(self.checker_route, "checker_route")
        )
        object.__setattr__(
            self,
            "reconstruction_route",
            _optional_text(self.reconstruction_route, "reconstruction_route"),
        )
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description") if self.description else "",
        )
        object.__setattr__(self, "version", _version(self.version))

        authority = _enum(
            self.authority_ceiling, EvidenceAuthority, "authority_ceiling"
        )
        object.__setattr__(self, "authority_ceiling", authority)
        maximum = maximum_authority_for(self.preservation)
        if not authority_at_most(authority, maximum):
            raise TranslationContractError(
                f"{self.preservation.value} translations cannot carry "
                f"{authority.value} authority (ceiling is {maximum.value})"
            )

        self._validate_maps()
        self._validate_polarity()
        computed = self._compute_identity()
        if self.contract_content_id and self.contract_content_id != computed.cid:
            raise TranslationContractError(
                "contract_content_id does not match canonical contract content"
            )
        object.__setattr__(self, "contract_content_id", computed.cid)

    def _validate_maps(self) -> None:
        mapped_nodes = {entry.source_node_id for entry in self.node_map}
        missing_nodes = sorted(set(self.required_source_node_ids) - mapped_nodes)
        if missing_nodes:
            raise TranslationContractError(
                "silent node drop forbidden; missing node_map entries for: "
                + ", ".join(missing_nodes)
            )
        mapped_symbols = {entry.source_symbol_id for entry in self.symbol_map}
        missing_symbols = sorted(
            set(self.required_source_symbol_ids) - mapped_symbols
        )
        if missing_symbols:
            raise TranslationContractError(
                "silent symbol drop forbidden; missing symbol_map entries for: "
                + ", ".join(missing_symbols)
            )
        if self.preservation is PreservationRelation.EXACT_EQUIVALENCE:
            lossy = {
                NodeDisposition.DROPPED,
                NodeDisposition.UNSUPPORTED,
                NodeDisposition.UNKNOWN,
                NodeDisposition.APPROXIMATED,
            }
            for entry in self.node_map:
                if entry.disposition in lossy:
                    raise TranslationContractError(
                        "exact_equivalence cannot declare lossy node dispositions"
                    )
            for entry in self.symbol_map:
                if entry.disposition in lossy:
                    raise TranslationContractError(
                        "exact_equivalence cannot declare lossy symbol dispositions"
                    )
            if self.unsupported_constructs:
                raise TranslationContractError(
                    "exact_equivalence cannot declare unsupported constructs"
                )
            if self.assumptions.all_assumption_ids:
                raise TranslationContractError(
                    "exact_equivalence cannot introduce assumptions"
                )
        if self.preservation is PreservationRelation.BOUNDED:
            if not self.assumptions.bounds:
                raise TranslationContractError(
                    "bounded translations require explicit bounds assumptions"
                )

    def _validate_polarity(self) -> None:
        # Independent polarity is allowed, but exact equivalence must not claim
        # both polarities false (that would be a vacuous "exact" edge).
        if self.preservation is PreservationRelation.EXACT_EQUIVALENCE:
            if not (self.proof_safe and self.counterexample_safe):
                raise TranslationContractError(
                    "exact_equivalence requires proof_safe and counterexample_safe"
                )
        if self.preservation is PreservationRelation.HEURISTIC:
            if self.proof_safe or self.counterexample_safe:
                raise TranslationContractError(
                    "heuristic translations cannot claim proof_safe or "
                    "counterexample_safe polarity"
                )

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=CONTRACT_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def content_id(self) -> str:
        return self.contract_content_id

    @property
    def maximum_authority(self) -> EvidenceAuthority:
        return maximum_authority_for(self.preservation)

    @property
    def taxonomy_kind(self) -> TranslationKind:
        return taxonomy_translation_kind(self.preservation)

    @property
    def dropped_node_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.source_node_id
            for entry in self.node_map
            if entry.disposition is NodeDisposition.DROPPED
        )

    @property
    def unknown_node_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.source_node_id
            for entry in self.node_map
            if entry.disposition is NodeDisposition.UNKNOWN
        )

    @property
    def unsupported_node_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.source_node_id
            for entry in self.node_map
            if entry.disposition is NodeDisposition.UNSUPPORTED
        )

    @property
    def approximated_node_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.source_node_id
            for entry in self.node_map
            if entry.disposition is NodeDisposition.APPROXIMATED
        )

    def node_lookup(self) -> Mapping[str, NodeMapEntry]:
        return {entry.source_node_id: entry for entry in self.node_map}

    def symbol_lookup(self) -> Mapping[str, SymbolMapEntry]:
        return {entry.source_symbol_id: entry for entry in self.symbol_map}

    def semantic_dict(self) -> dict[str, Any]:
        """Return the canonical identity preimage (excludes content id)."""

        return {
            "assumptions": self.assumptions.to_dict(),
            "authority_ceiling": self.authority_ceiling.value,
            "checker_route": self.checker_route,
            "contract_id": self.contract_id,
            "counterexample_safe": self.counterexample_safe,
            "description": self.description,
            "feature_preconditions": list(self.feature_preconditions),
            "identities": self.identities.to_dict(),
            "interface": self.interface,
            "node_map": [entry.to_dict() for entry in self.node_map],
            "opaque_disposition": self.opaque_disposition.value,
            "preservation": self.preservation.value,
            "proof_safe": self.proof_safe,
            "reconstruction_route": self.reconstruction_route,
            "required_source_node_ids": list(self.required_source_node_ids),
            "required_source_symbol_ids": list(self.required_source_symbol_ids),
            "schema_version": self.schema_version,
            "source": self.source.to_dict(),
            "symbol_map": [entry.to_dict() for entry in self.symbol_map],
            "target": self.target.to_dict(),
            "unsupported_constructs": list(self.unsupported_constructs),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["contract_content_id"] = self.contract_content_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TranslationContract":
        value = _mapping(value, "translation contract")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumptions",
                    "authority_ceiling",
                    "checker_route",
                    "contract_content_id",
                    "contract_id",
                    "counterexample_safe",
                    "description",
                    "feature_preconditions",
                    "identities",
                    "interface",
                    "node_map",
                    "opaque_disposition",
                    "preservation",
                    "proof_safe",
                    "reconstruction_route",
                    "required_source_node_ids",
                    "required_source_symbol_ids",
                    "schema_version",
                    "source",
                    "symbol_map",
                    "target",
                    "unsupported_constructs",
                    "version",
                }
            ),
            "translation contract",
        )
        interface = value.get("interface", CONTRACT_INTERFACE)
        if interface != CONTRACT_INTERFACE:
            raise TranslationContractError(
                f"unsupported translation contract interface {interface!r}"
            )
        schema = value.get("schema_version", CONTRACT_SCHEMA_VERSION)
        if schema != CONTRACT_SCHEMA_VERSION:
            raise TranslationContractError(
                f"unsupported translation contract schema {schema!r}"
            )
        return cls(
            contract_id=value.get("contract_id", ""),
            source=value.get("source", {}),  # type: ignore[arg-type]
            target=value.get("target", {}),  # type: ignore[arg-type]
            preservation=value.get("preservation", ""),
            identities=value.get("identities", {}),  # type: ignore[arg-type]
            proof_safe=bool(value.get("proof_safe", False)),
            counterexample_safe=bool(value.get("counterexample_safe", False)),
            authority_ceiling=value.get(
                "authority_ceiling", EvidenceAuthority.NONE.value
            ),
            assumptions=value.get("assumptions", {}),  # type: ignore[arg-type]
            node_map=tuple(value.get("node_map", ())),
            symbol_map=tuple(value.get("symbol_map", ())),
            required_source_node_ids=tuple(
                value.get("required_source_node_ids", ())
            ),
            required_source_symbol_ids=tuple(
                value.get("required_source_symbol_ids", ())
            ),
            feature_preconditions=tuple(value.get("feature_preconditions", ())),
            unsupported_constructs=tuple(value.get("unsupported_constructs", ())),
            opaque_disposition=value.get(
                "opaque_disposition", OpaqueDisposition.UNSUPPORTED.value
            ),
            checker_route=value.get("checker_route", ""),
            reconstruction_route=value.get("reconstruction_route", ""),
            description=value.get("description", ""),
            version=value.get("version", DESCRIPTOR_VERSION),
            contract_content_id=value.get("contract_content_id", ""),
        )


def _compose_node_maps(
    first: Sequence[NodeMapEntry],
    second: Sequence[NodeMapEntry],
) -> tuple[NodeMapEntry, ...]:
    second_lookup = {entry.source_node_id: entry for entry in second}
    composed: list[NodeMapEntry] = []
    for entry in first:
        if entry.disposition in {
            NodeDisposition.DROPPED,
            NodeDisposition.UNSUPPORTED,
            NodeDisposition.UNKNOWN,
        }:
            composed.append(entry)
            continue
        if not entry.target_node_ids:
            composed.append(
                NodeMapEntry(
                    source_node_id=entry.source_node_id,
                    disposition=NodeDisposition.UNKNOWN,
                    reason="missing intermediate targets under composition",
                )
            )
            continue
        target_ids: list[str] = []
        disposition = entry.disposition
        reasons: list[str] = []
        if entry.reason:
            reasons.append(entry.reason)
        unresolved = False
        for intermediate in entry.target_node_ids:
            follow = second_lookup.get(intermediate)
            if follow is None:
                unresolved = True
                reasons.append(
                    f"unknown intermediate node {intermediate} under composition"
                )
                continue
            disposition = weaker_disposition(disposition, follow.disposition)
            if follow.reason:
                reasons.append(follow.reason)
            if follow.disposition in {
                NodeDisposition.DROPPED,
                NodeDisposition.UNSUPPORTED,
                NodeDisposition.UNKNOWN,
            }:
                continue
            target_ids.extend(follow.target_node_ids)
        if unresolved:
            disposition = weaker_disposition(disposition, NodeDisposition.UNKNOWN)
        unique_targets = tuple(sorted(set(target_ids)))
        if disposition in {
            NodeDisposition.DROPPED,
            NodeDisposition.UNSUPPORTED,
            NodeDisposition.UNKNOWN,
        }:
            unique_targets = ()
        elif not unique_targets:
            disposition = weaker_disposition(disposition, NodeDisposition.UNKNOWN)
            reasons.append("composition lost all target nodes")
        composed.append(
            NodeMapEntry(
                source_node_id=entry.source_node_id,
                target_node_ids=unique_targets,
                disposition=disposition,
                reason="; ".join(reasons) if reasons else "composed node map",
            )
        )
    return _unique_node_map(composed, "composed node_map")


def _compose_symbol_maps(
    first: Sequence[SymbolMapEntry],
    second: Sequence[SymbolMapEntry],
) -> tuple[SymbolMapEntry, ...]:
    second_lookup = {entry.source_symbol_id: entry for entry in second}
    composed: list[SymbolMapEntry] = []
    for entry in first:
        if entry.disposition in {
            NodeDisposition.DROPPED,
            NodeDisposition.UNSUPPORTED,
            NodeDisposition.UNKNOWN,
        }:
            composed.append(entry)
            continue
        if not entry.target_symbol_ids:
            composed.append(
                SymbolMapEntry(
                    source_symbol_id=entry.source_symbol_id,
                    disposition=NodeDisposition.UNKNOWN,
                    reason="missing intermediate targets under composition",
                )
            )
            continue
        target_ids: list[str] = []
        disposition = entry.disposition
        reasons: list[str] = []
        if entry.reason:
            reasons.append(entry.reason)
        unresolved = False
        for intermediate in entry.target_symbol_ids:
            follow = second_lookup.get(intermediate)
            if follow is None:
                unresolved = True
                reasons.append(
                    f"unknown intermediate symbol {intermediate} under composition"
                )
                continue
            disposition = weaker_disposition(disposition, follow.disposition)
            if follow.reason:
                reasons.append(follow.reason)
            if follow.disposition in {
                NodeDisposition.DROPPED,
                NodeDisposition.UNSUPPORTED,
                NodeDisposition.UNKNOWN,
            }:
                continue
            target_ids.extend(follow.target_symbol_ids)
        if unresolved:
            disposition = weaker_disposition(disposition, NodeDisposition.UNKNOWN)
        unique_targets = tuple(sorted(set(target_ids)))
        if disposition in {
            NodeDisposition.DROPPED,
            NodeDisposition.UNSUPPORTED,
            NodeDisposition.UNKNOWN,
        }:
            unique_targets = ()
        elif not unique_targets:
            disposition = weaker_disposition(disposition, NodeDisposition.UNKNOWN)
            reasons.append("composition lost all target symbols")
        composed.append(
            SymbolMapEntry(
                source_symbol_id=entry.source_symbol_id,
                target_symbol_ids=unique_targets,
                disposition=disposition,
                reason="; ".join(reasons) if reasons else "composed symbol map",
            )
        )
    return _unique_symbol_map(composed, "composed symbol_map")


def _endpoints_compatible(
    left_target: TranslationEndpoint, right_source: TranslationEndpoint
) -> None:
    if left_target.family_id != right_source.family_id:
        raise TranslationContractError(
            "composed translations require matching intermediate family: "
            f"{left_target.family_id!r} -> {right_source.family_id!r}"
        )
    if (
        left_target.profile_id
        and right_source.profile_id
        and left_target.profile_id != right_source.profile_id
    ):
        raise TranslationContractError(
            "composed translations require matching intermediate profile: "
            f"{left_target.profile_id!r} -> {right_source.profile_id!r}"
        )


@dataclass(frozen=True, slots=True)
class TranslationCompositionReceipt:
    """Weakest-link composition of one or more translation contracts.

    Interface: ``TranslationCompositionReceipt@1``.
    """

    composition_id: str
    component_contract_ids: tuple[str, ...]
    component_content_ids: tuple[str, ...]
    source: TranslationEndpoint
    target: TranslationEndpoint
    preservation: PreservationRelation | str
    authority_ceiling: EvidenceAuthority | str
    proof_safe: bool
    counterexample_safe: bool
    assumptions: TranslationAssumptionSet
    node_map: tuple[NodeMapEntry, ...]
    symbol_map: tuple[SymbolMapEntry, ...]
    identities: TranslationIdentities
    opaque_disposition: OpaqueDisposition | str = OpaqueDisposition.UNSUPPORTED
    unsupported_constructs: tuple[str, ...] = ()
    feature_preconditions: tuple[str, ...] = ()
    checker_route: str = ""
    reconstruction_route: str = ""
    description: str = ""
    composition_content_id: str = ""

    schema_version: ClassVar[str] = COMPOSITION_SCHEMA_VERSION
    interface: ClassVar[str] = COMPOSITION_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "composition_id",
            _identifier(self.composition_id, "composition_id"),
        )
        object.__setattr__(
            self,
            "component_contract_ids",
            _ordered_strings(
                self.component_contract_ids,
                "component_contract_ids",
                identifiers=True,
            ),
        )
        if not self.component_contract_ids:
            raise TranslationContractError(
                "composition requires at least one component contract id"
            )
        object.__setattr__(
            self,
            "component_content_ids",
            _ordered_strings(
                self.component_content_ids, "component_content_ids"
            ),
        )
        if len(self.component_content_ids) != len(self.component_contract_ids):
            raise TranslationContractError(
                "component_content_ids length must match component_contract_ids"
            )

        source = self.source
        if isinstance(source, Mapping):
            source = TranslationEndpoint.from_dict(source)
        if not isinstance(source, TranslationEndpoint):
            raise TranslationContractError("source must be a TranslationEndpoint")
        object.__setattr__(self, "source", source)

        target = self.target
        if isinstance(target, Mapping):
            target = TranslationEndpoint.from_dict(target)
        if not isinstance(target, TranslationEndpoint):
            raise TranslationContractError("target must be a TranslationEndpoint")
        object.__setattr__(self, "target", target)

        object.__setattr__(
            self,
            "preservation",
            _enum(self.preservation, PreservationRelation, "preservation"),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _enum(self.authority_ceiling, EvidenceAuthority, "authority_ceiling"),
        )
        object.__setattr__(self, "proof_safe", _bool(self.proof_safe, "proof_safe"))
        object.__setattr__(
            self,
            "counterexample_safe",
            _bool(self.counterexample_safe, "counterexample_safe"),
        )

        assumptions = self.assumptions
        if isinstance(assumptions, Mapping):
            assumptions = TranslationAssumptionSet.from_dict(assumptions)
        if not isinstance(assumptions, TranslationAssumptionSet):
            raise TranslationContractError(
                "assumptions must be a TranslationAssumptionSet"
            )
        object.__setattr__(self, "assumptions", assumptions)

        identities = self.identities
        if isinstance(identities, Mapping):
            identities = TranslationIdentities.from_dict(identities)
        if not isinstance(identities, TranslationIdentities):
            raise TranslationContractError(
                "identities must be a TranslationIdentities bundle"
            )
        object.__setattr__(self, "identities", identities)

        object.__setattr__(
            self,
            "node_map",
            _unique_node_map(_records(self.node_map, NodeMapEntry, "node_map")),
        )
        object.__setattr__(
            self,
            "symbol_map",
            _unique_symbol_map(
                _records(self.symbol_map, SymbolMapEntry, "symbol_map")
            ),
        )
        object.__setattr__(
            self,
            "opaque_disposition",
            _enum(
                self.opaque_disposition, OpaqueDisposition, "opaque_disposition"
            ),
        )
        object.__setattr__(
            self,
            "unsupported_constructs",
            _strings(
                self.unsupported_constructs,
                "unsupported_constructs",
                identifiers=True,
            ),
        )
        object.__setattr__(
            self,
            "feature_preconditions",
            _strings(
                self.feature_preconditions,
                "feature_preconditions",
                identifiers=True,
            ),
        )
        object.__setattr__(
            self, "checker_route", _optional_text(self.checker_route, "checker_route")
        )
        object.__setattr__(
            self,
            "reconstruction_route",
            _optional_text(self.reconstruction_route, "reconstruction_route"),
        )
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description") if self.description else "",
        )

        maximum = maximum_authority_for(self.preservation)
        if not authority_at_most(self.authority_ceiling, maximum):
            raise TranslationContractError(
                f"composed {self.preservation.value} cannot carry "
                f"{self.authority_ceiling.value} authority"
            )

        computed = self._compute_identity()
        if (
            self.composition_content_id
            and self.composition_content_id != computed.cid
        ):
            raise TranslationContractError(
                "composition_content_id does not match canonical composition content"
            )
        object.__setattr__(self, "composition_content_id", computed.cid)

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=COMPOSITION_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def content_id(self) -> str:
        return self.composition_content_id

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "assumptions": self.assumptions.to_dict(),
            "authority_ceiling": self.authority_ceiling.value,
            "checker_route": self.checker_route,
            "component_content_ids": list(self.component_content_ids),
            "component_contract_ids": list(self.component_contract_ids),
            "composition_id": self.composition_id,
            "counterexample_safe": self.counterexample_safe,
            "description": self.description,
            "feature_preconditions": list(self.feature_preconditions),
            "identities": self.identities.to_dict(),
            "interface": self.interface,
            "node_map": [entry.to_dict() for entry in self.node_map],
            "opaque_disposition": self.opaque_disposition.value,
            "preservation": self.preservation.value,
            "proof_safe": self.proof_safe,
            "reconstruction_route": self.reconstruction_route,
            "schema_version": self.schema_version,
            "source": self.source.to_dict(),
            "symbol_map": [entry.to_dict() for entry in self.symbol_map],
            "target": self.target.to_dict(),
            "unsupported_constructs": list(self.unsupported_constructs),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["composition_content_id"] = self.composition_content_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TranslationCompositionReceipt":
        value = _mapping(value, "translation composition receipt")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumptions",
                    "authority_ceiling",
                    "checker_route",
                    "component_content_ids",
                    "component_contract_ids",
                    "composition_content_id",
                    "composition_id",
                    "counterexample_safe",
                    "description",
                    "feature_preconditions",
                    "identities",
                    "interface",
                    "node_map",
                    "opaque_disposition",
                    "preservation",
                    "proof_safe",
                    "reconstruction_route",
                    "schema_version",
                    "source",
                    "symbol_map",
                    "target",
                    "unsupported_constructs",
                }
            ),
            "translation composition receipt",
        )
        interface = value.get("interface", COMPOSITION_INTERFACE)
        if interface != COMPOSITION_INTERFACE:
            raise TranslationContractError(
                f"unsupported composition interface {interface!r}"
            )
        schema = value.get("schema_version", COMPOSITION_SCHEMA_VERSION)
        if schema != COMPOSITION_SCHEMA_VERSION:
            raise TranslationContractError(
                f"unsupported composition schema {schema!r}"
            )
        return cls(
            composition_id=value.get("composition_id", ""),
            component_contract_ids=tuple(value.get("component_contract_ids", ())),
            component_content_ids=tuple(value.get("component_content_ids", ())),
            source=value.get("source", {}),  # type: ignore[arg-type]
            target=value.get("target", {}),  # type: ignore[arg-type]
            preservation=value.get("preservation", ""),
            authority_ceiling=value.get(
                "authority_ceiling", EvidenceAuthority.NONE.value
            ),
            proof_safe=bool(value.get("proof_safe", False)),
            counterexample_safe=bool(value.get("counterexample_safe", False)),
            assumptions=value.get("assumptions", {}),  # type: ignore[arg-type]
            node_map=tuple(value.get("node_map", ())),
            symbol_map=tuple(value.get("symbol_map", ())),
            identities=value.get("identities", {}),  # type: ignore[arg-type]
            opaque_disposition=value.get(
                "opaque_disposition", OpaqueDisposition.UNSUPPORTED.value
            ),
            unsupported_constructs=tuple(value.get("unsupported_constructs", ())),
            feature_preconditions=tuple(value.get("feature_preconditions", ())),
            checker_route=value.get("checker_route", ""),
            reconstruction_route=value.get("reconstruction_route", ""),
            description=value.get("description", ""),
            composition_content_id=value.get("composition_content_id", ""),
        )


def compose_translations(
    *contracts: TranslationContract,
    composition_id: str | None = None,
) -> TranslationCompositionReceipt:
    """Compose translation contracts under the weakest-link rule.

    The composed preservation relation and authority ceiling are the weakest
    among all components.  Proof-safe and counterexample-safe polarities are
    conjunctive.  Assumptions and unsupported constructs accumulate and never
    disappear.  Node and symbol maps are composed transitively; unresolved
    intermediates become ``unknown`` rather than vanishing.
    """

    if not contracts:
        raise TranslationContractError(
            "compose_translations requires at least one TranslationContract"
        )
    for index, contract in enumerate(contracts):
        if not isinstance(contract, TranslationContract):
            raise TranslationContractError(
                f"contracts[{index}] must be a TranslationContract"
            )

    if len(contracts) == 1:
        only = contracts[0]
        return TranslationCompositionReceipt(
            composition_id=composition_id or f"compose_{only.contract_id}",
            component_contract_ids=(only.contract_id,),
            component_content_ids=(only.contract_content_id,),
            source=only.source,
            target=only.target,
            preservation=only.preservation,
            authority_ceiling=only.authority_ceiling,
            proof_safe=only.proof_safe,
            counterexample_safe=only.counterexample_safe,
            assumptions=only.assumptions,
            node_map=only.node_map,
            symbol_map=only.symbol_map,
            identities=only.identities,
            opaque_disposition=only.opaque_disposition,
            unsupported_constructs=only.unsupported_constructs,
            feature_preconditions=only.feature_preconditions,
            checker_route=only.checker_route,
            reconstruction_route=only.reconstruction_route,
            description=only.description
            or f"identity composition of {only.contract_id}",
        )

    for left, right in zip(contracts, contracts[1:]):
        _endpoints_compatible(left.target, right.source)

    preservation = contracts[0].preservation
    authority = contracts[0].authority_ceiling
    proof_safe = contracts[0].proof_safe
    counterexample_safe = contracts[0].counterexample_safe
    assumptions = contracts[0].assumptions
    unsupported: set[str] = set(contracts[0].unsupported_constructs)
    preconditions: set[str] = set(contracts[0].feature_preconditions)
    node_map = contracts[0].node_map
    symbol_map = contracts[0].symbol_map
    opaque = contracts[0].opaque_disposition

    for contract in contracts[1:]:
        preservation = weaker_preservation(preservation, contract.preservation)
        authority = weaker_authority(authority, contract.authority_ceiling)
        proof_safe = proof_safe and contract.proof_safe
        counterexample_safe = counterexample_safe and contract.counterexample_safe
        assumptions = assumptions.union(contract.assumptions)
        unsupported.update(contract.unsupported_constructs)
        preconditions.update(contract.feature_preconditions)
        node_map = _compose_node_maps(node_map, contract.node_map)
        symbol_map = _compose_symbol_maps(symbol_map, contract.symbol_map)
        # Opaque disposition never becomes more permissive than unsupported.
        if opaque is not OpaqueDisposition.UNSUPPORTED:
            if contract.opaque_disposition is OpaqueDisposition.UNSUPPORTED:
                opaque = OpaqueDisposition.UNSUPPORTED
            elif (
                opaque is OpaqueDisposition.INCONCLUSIVE
                or contract.opaque_disposition is OpaqueDisposition.INCONCLUSIVE
            ):
                opaque = OpaqueDisposition.INCONCLUSIVE

    # Authority cannot exceed the composed preservation ceiling.
    authority = weaker_authority(authority, maximum_authority_for(preservation))

    first = contracts[0]
    last = contracts[-1]
    composed_identities = TranslationIdentities(
        compiler_identity="+".join(
            contract.identities.compiler_identity for contract in contracts
        ),
        profile_identity="+".join(
            contract.identities.profile_identity for contract in contracts
        ),
        config_identity="+".join(
            contract.identities.config_identity for contract in contracts
        ),
        source_identity=first.identities.source_identity
        or first.source.content_identity,
        target_identity=last.identities.target_identity
        or last.target.content_identity,
        environment_identity="+".join(
            filter(
                None,
                (contract.identities.environment_identity for contract in contracts),
            )
        ),
    )

    component_ids = tuple(contract.contract_id for contract in contracts)
    if composition_id is None:
        composition_id = "compose_" + "_".join(component_ids)

    checker_routes = [c.checker_route for c in contracts if c.checker_route]
    reconstruction_routes = [
        c.reconstruction_route for c in contracts if c.reconstruction_route
    ]

    return TranslationCompositionReceipt(
        composition_id=composition_id,
        component_contract_ids=component_ids,
        component_content_ids=tuple(
            contract.contract_content_id for contract in contracts
        ),
        source=first.source,
        target=last.target,
        preservation=preservation,
        authority_ceiling=authority,
        proof_safe=proof_safe,
        counterexample_safe=counterexample_safe,
        assumptions=assumptions,
        node_map=node_map,
        symbol_map=symbol_map,
        identities=composed_identities,
        opaque_disposition=opaque,
        unsupported_constructs=tuple(sorted(unsupported)),
        feature_preconditions=tuple(sorted(preconditions)),
        checker_route="|".join(checker_routes),
        reconstruction_route="|".join(reconstruction_routes),
        description=(
            f"weakest-link composition of {', '.join(component_ids)}"
        ),
    )


def contracts_from_sequence(
    values: Iterable[Mapping[str, Any] | TranslationContract],
) -> tuple[TranslationContract, ...]:
    """Coerce a sequence of mappings or contracts into validated contracts."""

    result: list[TranslationContract] = []
    for index, value in enumerate(values):
        if isinstance(value, TranslationContract):
            result.append(value)
        elif isinstance(value, Mapping):
            result.append(TranslationContract.from_dict(value))
        else:
            raise TranslationContractError(
                f"values[{index}] must be a TranslationContract or mapping"
            )
    return tuple(result)


__all__ = [
    "ASSUMPTION_SET_SCHEMA_VERSION",
    "COMPOSITION_IDENTITY_DOMAIN",
    "COMPOSITION_INTERFACE",
    "COMPOSITION_SCHEMA_VERSION",
    "CONTRACT_IDENTITY_DOMAIN",
    "CONTRACT_INTERFACE",
    "CONTRACT_SCHEMA_VERSION",
    "ENDPOINT_SCHEMA_VERSION",
    "IDENTITY_BUNDLE_SCHEMA_VERSION",
    "NODE_MAP_SCHEMA_VERSION",
    "SYMBOL_MAP_SCHEMA_VERSION",
    "NodeDisposition",
    "NodeMapEntry",
    "OpaqueDisposition",
    "PreservationRelation",
    "SymbolMapEntry",
    "TranslationAssumptionSet",
    "TranslationCompositionReceipt",
    "TranslationContract",
    "TranslationContractError",
    "TranslationEndpoint",
    "TranslationIdentities",
    "authority_at_most",
    "authority_rank",
    "compose_translations",
    "contracts_from_sequence",
    "disposition_rank",
    "maximum_authority_for",
    "preservation_rank",
    "taxonomy_translation_kind",
    "weaker_authority",
    "weaker_disposition",
    "weaker_preservation",
]
