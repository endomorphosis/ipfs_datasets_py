"""Compositional TranslationPath planner (``TranslationPathPlanner@1``).

The planner selects feature-total paths through registered
``TranslationContract@2`` edges and emits ``TranslationPathReceipt@1``
receipts.  Selection composes preservation, polarity, assumptions, losses,
bounds, reconstruction routes, and authority ceilings under the weakest-link
rule.

Unsupported features and authority/approximation laundering fail **before**
compilation: the planner never returns a receipt that could be dispatched to a
backend under a stronger claim than the composed path admits.  Path identity is
deterministic for identical edge registries and plan requests.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.translations import (
    PreservationRelation,
    TranslationAssumptionSet,
    TranslationCompositionReceipt,
    TranslationContract,
    TranslationContractError,
    TranslationEndpoint,
    authority_at_most,
    authority_rank,
    compose_translations,
    maximum_authority_for,
    preservation_rank,
    weaker_authority,
    weaker_preservation,
)
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity


PLANNER_INTERFACE: Final = "TranslationPathPlanner@1"
PATH_RECEIPT_INTERFACE: Final = "TranslationPathReceipt@1"
PATH_RECEIPT_SCHEMA_VERSION: Final = "logic-translation-path-receipt/v1"
FEATURE_SET_SCHEMA_VERSION: Final = "logic-translation-feature-set/v1"
PLAN_REQUEST_SCHEMA_VERSION: Final = "logic-translation-path-request/v1"
PATH_IDENTITY_DOMAIN: Final = "logic.translation.path"
DEFAULT_MAX_HOPS: Final = 8
PLANNER_ID: Final = "translation-path-planner@1"


class TranslationPathPlannerError(ValueError):
    """Raised when path planning is impossible or would launder claims."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise TranslationPathPlannerError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise TranslationPathPlannerError(f"{field_name} must not contain NUL bytes")
    return value


def _optional_text(value: object, field_name: str) -> str:
    if value is None or value == "":
        return ""
    return _text(value, field_name)


def _identifier(value: object, field_name: str) -> str:
    """Validate a stable non-empty identifier string."""

    return _text(value, field_name)


def _strings(
    values: Sequence[str] | object,
    field_name: str,
    *,
    identifiers: bool = False,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise TranslationPathPlannerError(
            f"{field_name} must be a sequence of strings"
        )
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _identifier(item, f"{field_name} item") if identifiers else _text(
            item, f"{field_name} item"
        )
        if text in seen:
            raise TranslationPathPlannerError(
                f"{field_name} must not contain duplicates"
            )
        seen.add(text)
        result.append(text)
    return tuple(result)


def _sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TranslationPathPlannerError(f"{field_name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise TranslationPathPlannerError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _enum(value: object, enum_type: type[Any], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise TranslationPathPlannerError(
            f"{field_name} must be one of {choices}"
        ) from error


@dataclass(frozen=True, slots=True)
class FeatureSet:
    """Canonical feature identifiers present in a source obligation.

    Feature sets are sorted and de-duplicated so plan identity does not depend
    on caller ordering.
    """

    features: tuple[str, ...] = ()
    schema_version: str = FEATURE_SET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        normalized = _sorted_unique(
            _strings(self.features, "features", identifiers=True)
        )
        object.__setattr__(self, "features", normalized)
        if self.schema_version != FEATURE_SET_SCHEMA_VERSION:
            raise TranslationPathPlannerError(
                f"unsupported feature set schema {self.schema_version!r}"
            )

    def __iter__(self):
        return iter(self.features)

    def __len__(self) -> int:
        return len(self.features)

    def __contains__(self, item: object) -> bool:
        return item in self.as_set()

    def as_set(self) -> frozenset[str]:
        return frozenset(self.features)

    def to_dict(self) -> dict[str, Any]:
        return {
            "features": list(self.features),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Sequence[str]) -> "FeatureSet":
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            return cls(features=tuple(value))
        value = _mapping(value, "feature set")
        _reject_unknown(
            value,
            frozenset({"features", "schema_version"}),
            "feature set",
        )
        return cls(
            features=tuple(value.get("features", ())),
            schema_version=value.get(
                "schema_version", FEATURE_SET_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_features(cls, features: Sequence[str] | None = None) -> "FeatureSet":
        return cls(features=tuple(features or ()))


@dataclass(frozen=True, slots=True)
class TranslationPathRequest:
    """Inputs to :meth:`TranslationPathPlanner.plan`.

    ``claimed_preservation`` / ``claimed_authority`` are optional caller claims.
    When set, the planner rejects any path whose composed receipt is weaker —
    this is the authority/approximation laundering gate.
    """

    source_family_id: str
    target_family_id: str
    features: FeatureSet = field(default_factory=FeatureSet)
    source_profile_id: str = ""
    target_profile_id: str = ""
    require_proof_safe: bool = False
    require_counterexample_safe: bool = False
    claimed_preservation: PreservationRelation | str | None = None
    claimed_authority: EvidenceAuthority | str | None = None
    max_hops: int = DEFAULT_MAX_HOPS
    description: str = ""
    schema_version: str = PLAN_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_family_id",
            _text(self.source_family_id, "source_family_id"),
        )
        object.__setattr__(
            self,
            "target_family_id",
            _text(self.target_family_id, "target_family_id"),
        )
        object.__setattr__(
            self,
            "source_profile_id",
            _optional_text(self.source_profile_id, "source_profile_id"),
        )
        object.__setattr__(
            self,
            "target_profile_id",
            _optional_text(self.target_profile_id, "target_profile_id"),
        )

        features = self.features
        if isinstance(features, (FeatureSet,)):
            pass
        elif isinstance(features, Mapping):
            features = FeatureSet.from_dict(features)
        elif isinstance(features, Sequence) and not isinstance(
            features, (str, bytes, bytearray)
        ):
            features = FeatureSet.from_features(features)
        else:
            raise TranslationPathPlannerError(
                "features must be a FeatureSet, mapping, or sequence of strings"
            )
        object.__setattr__(self, "features", features)

        if not isinstance(self.require_proof_safe, bool):
            raise TranslationPathPlannerError("require_proof_safe must be a bool")
        if not isinstance(self.require_counterexample_safe, bool):
            raise TranslationPathPlannerError(
                "require_counterexample_safe must be a bool"
            )

        claimed_preservation = self.claimed_preservation
        if claimed_preservation is not None and claimed_preservation != "":
            object.__setattr__(
                self,
                "claimed_preservation",
                _enum(
                    claimed_preservation,
                    PreservationRelation,
                    "claimed_preservation",
                ),
            )
        else:
            object.__setattr__(self, "claimed_preservation", None)

        claimed_authority = self.claimed_authority
        if claimed_authority is not None and claimed_authority != "":
            object.__setattr__(
                self,
                "claimed_authority",
                _enum(claimed_authority, EvidenceAuthority, "claimed_authority"),
            )
        else:
            object.__setattr__(self, "claimed_authority", None)

        if not isinstance(self.max_hops, int) or isinstance(self.max_hops, bool):
            raise TranslationPathPlannerError("max_hops must be an int")
        if self.max_hops < 1:
            raise TranslationPathPlannerError("max_hops must be >= 1")
        if self.max_hops > 32:
            raise TranslationPathPlannerError("max_hops must be <= 32")

        object.__setattr__(
            self,
            "description",
            _optional_text(self.description, "description"),
        )
        if self.schema_version != PLAN_REQUEST_SCHEMA_VERSION:
            raise TranslationPathPlannerError(
                f"unsupported plan request schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "claimed_authority": (
                self.claimed_authority.value
                if self.claimed_authority is not None
                else None
            ),
            "claimed_preservation": (
                self.claimed_preservation.value
                if self.claimed_preservation is not None
                else None
            ),
            "description": self.description,
            "features": self.features.to_dict(),
            "max_hops": self.max_hops,
            "require_counterexample_safe": self.require_counterexample_safe,
            "require_proof_safe": self.require_proof_safe,
            "schema_version": self.schema_version,
            "source_family_id": self.source_family_id,
            "source_profile_id": self.source_profile_id,
            "target_family_id": self.target_family_id,
            "target_profile_id": self.target_profile_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TranslationPathRequest":
        value = _mapping(value, "translation path request")
        _reject_unknown(
            value,
            frozenset(
                {
                    "claimed_authority",
                    "claimed_preservation",
                    "description",
                    "features",
                    "max_hops",
                    "require_counterexample_safe",
                    "require_proof_safe",
                    "schema_version",
                    "source_family_id",
                    "source_profile_id",
                    "target_family_id",
                    "target_profile_id",
                }
            ),
            "translation path request",
        )
        return cls(
            source_family_id=value.get("source_family_id", ""),
            target_family_id=value.get("target_family_id", ""),
            features=value.get("features", ()),  # type: ignore[arg-type]
            source_profile_id=value.get("source_profile_id", ""),
            target_profile_id=value.get("target_profile_id", ""),
            require_proof_safe=bool(value.get("require_proof_safe", False)),
            require_counterexample_safe=bool(
                value.get("require_counterexample_safe", False)
            ),
            claimed_preservation=value.get("claimed_preservation"),
            claimed_authority=value.get("claimed_authority"),
            max_hops=int(value.get("max_hops", DEFAULT_MAX_HOPS)),
            description=value.get("description", ""),
            schema_version=value.get(
                "schema_version", PLAN_REQUEST_SCHEMA_VERSION
            ),
        )


def edge_feature_compatibility(
    contract: TranslationContract,
    features: FeatureSet | Sequence[str],
) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    """Return whether *contract* is feature-compatible with *features*.

    Returns ``(compatible, missing_preconditions, unsupported_hits)``.
    """

    if not isinstance(contract, TranslationContract):
        raise TranslationPathPlannerError(
            "contract must be a TranslationContract"
        )
    feature_set = (
        features
        if isinstance(features, FeatureSet)
        else FeatureSet.from_features(features)
    )
    present = feature_set.as_set()
    preconditions = frozenset(contract.feature_preconditions)
    unsupported = frozenset(contract.unsupported_constructs)

    missing = tuple(sorted(preconditions - present))
    hits = tuple(sorted(present & unsupported))
    compatible = not missing and not hits
    return compatible, missing, hits


def path_is_feature_total(
    contracts: Sequence[TranslationContract],
    features: FeatureSet | Sequence[str],
) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    """Return whether *contracts* form a feature-total path for *features*.

    A path is feature-total when:

    * every edge is feature-compatible (no unsupported hits; preconditions met);
    * every requested feature is either unconstrained (no edge declares any
      feature preconditions) or appears in the union of edge preconditions
      along the path (explicitly handled).
    """

    feature_set = (
        features
        if isinstance(features, FeatureSet)
        else FeatureSet.from_features(features)
    )
    if not contracts:
        return False, tuple(feature_set.features), ()

    all_missing: list[str] = []
    all_hits: list[str] = []
    precondition_union: set[str] = set()
    any_preconditions = False
    for contract in contracts:
        compatible, missing, hits = edge_feature_compatibility(contract, feature_set)
        if missing:
            all_missing.extend(missing)
        if hits:
            all_hits.extend(hits)
        if contract.feature_preconditions:
            any_preconditions = True
            precondition_union.update(contract.feature_preconditions)
        if not compatible:
            # continue collecting diagnostics
            pass

    unhandled: list[str] = []
    if any_preconditions:
        unhandled = sorted(feature_set.as_set() - precondition_union)

    total = not all_missing and not all_hits and not unhandled
    return (
        total,
        tuple(sorted(set(all_missing + unhandled))),
        tuple(sorted(set(all_hits))),
    )


def _endpoint_key(endpoint: TranslationEndpoint) -> tuple[str, str]:
    return (endpoint.family_id, endpoint.profile_id or "")


def _matches_endpoint(
    endpoint: TranslationEndpoint,
    family_id: str,
    profile_id: str = "",
) -> bool:
    if endpoint.family_id != family_id:
        return False
    if profile_id and endpoint.profile_id and endpoint.profile_id != profile_id:
        return False
    return True


def _detect_authority_laundering(
    contracts: Sequence[TranslationContract],
    composition: TranslationCompositionReceipt,
    request: TranslationPathRequest,
) -> str | None:
    """Return an error message if the path would launder authority/approximation.

    Laundering includes:

    * claiming a stronger preservation than the weakest-link composition;
    * claiming a higher authority ceiling than the composition admits;
    * any component whose authority exceeds the maximum allowed by *its own*
      preservation (already rejected by ``TranslationContract``, re-checked);
    * composition authority exceeding the maximum for the composed preservation;
    * requiring proof/counterexample safety that the composition cannot provide.
    """

    # Component self-consistency (defensive; contracts validate at construction).
    for contract in contracts:
        maximum = maximum_authority_for(contract.preservation)
        if not authority_at_most(contract.authority_ceiling, maximum):
            return (
                f"authority laundering: edge {contract.contract_id!r} claims "
                f"{contract.authority_ceiling.value} under "
                f"{contract.preservation.value} (ceiling is {maximum.value})"
            )

    composed_maximum = maximum_authority_for(composition.preservation)
    if not authority_at_most(composition.authority_ceiling, composed_maximum):
        return (
            "authority laundering: composed path claims "
            f"{composition.authority_ceiling.value} under "
            f"{composition.preservation.value} "
            f"(ceiling is {composed_maximum.value})"
        )

    # Weakest-link must not be stronger than any component.
    for contract in contracts:
        if preservation_rank(composition.preservation) > preservation_rank(
            contract.preservation
        ):
            return (
                "approximation laundering: composed preservation "
                f"{composition.preservation.value} is stronger than edge "
                f"{contract.contract_id!r} ({contract.preservation.value})"
            )
        if authority_rank(composition.authority_ceiling) > authority_rank(
            contract.authority_ceiling
        ):
            return (
                "authority laundering: composed authority "
                f"{composition.authority_ceiling.value} is stronger than edge "
                f"{contract.contract_id!r} ({contract.authority_ceiling.value})"
            )

    if request.claimed_preservation is not None:
        if preservation_rank(request.claimed_preservation) > preservation_rank(
            composition.preservation
        ):
            return (
                "approximation laundering: claimed preservation "
                f"{request.claimed_preservation.value} is stronger than "
                f"composed {composition.preservation.value}"
            )

    if request.claimed_authority is not None:
        if not authority_at_most(
            request.claimed_authority, composition.authority_ceiling
        ):
            return (
                "authority laundering: claimed authority "
                f"{request.claimed_authority.value} exceeds composed ceiling "
                f"{composition.authority_ceiling.value}"
            )

    if request.require_proof_safe and not composition.proof_safe:
        return (
            "polarity laundering: path is not proof_safe but proof safety "
            "was required"
        )
    if request.require_counterexample_safe and not composition.counterexample_safe:
        return (
            "polarity laundering: path is not counterexample_safe but "
            "counterexample safety was required"
        )

    return None


@dataclass(frozen=True, slots=True)
class TranslationPathReceipt:
    """Reviewed compositional path receipt (``TranslationPathReceipt@1``).

    Binds the selected edge chain, feature accounting, weakest-link composition,
    and a deterministic content identity suitable for backend dispatch gates.
    """

    path_id: str
    edge_contract_ids: tuple[str, ...]
    edge_content_ids: tuple[str, ...]
    source: TranslationEndpoint
    target: TranslationEndpoint
    features: FeatureSet
    composition: TranslationCompositionReceipt
    preservation: PreservationRelation | str
    authority_ceiling: EvidenceAuthority | str
    proof_safe: bool
    counterexample_safe: bool
    assumptions: TranslationAssumptionSet
    unsupported_constructs: tuple[str, ...] = ()
    feature_preconditions: tuple[str, ...] = ()
    covered_features: tuple[str, ...] = ()
    checker_route: str = ""
    reconstruction_route: str = ""
    hop_count: int = 0
    planner_id: str = PLANNER_ID
    description: str = ""
    path_content_id: str = ""

    schema_version: ClassVar[str] = PATH_RECEIPT_SCHEMA_VERSION
    interface: ClassVar[str] = PATH_RECEIPT_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "path_id", _text(self.path_id, "path_id"))
        object.__setattr__(
            self,
            "edge_contract_ids",
            _strings(self.edge_contract_ids, "edge_contract_ids", identifiers=True),
        )
        if not self.edge_contract_ids:
            raise TranslationPathPlannerError(
                "path receipt requires at least one edge contract id"
            )
        object.__setattr__(
            self,
            "edge_content_ids",
            _strings(self.edge_content_ids, "edge_content_ids"),
        )
        if len(self.edge_content_ids) != len(self.edge_contract_ids):
            raise TranslationPathPlannerError(
                "edge_content_ids length must match edge_contract_ids"
            )

        source = self.source
        if isinstance(source, Mapping):
            source = TranslationEndpoint.from_dict(source)
        if not isinstance(source, TranslationEndpoint):
            raise TranslationPathPlannerError(
                "source must be a TranslationEndpoint"
            )
        object.__setattr__(self, "source", source)

        target = self.target
        if isinstance(target, Mapping):
            target = TranslationEndpoint.from_dict(target)
        if not isinstance(target, TranslationEndpoint):
            raise TranslationPathPlannerError(
                "target must be a TranslationEndpoint"
            )
        object.__setattr__(self, "target", target)

        features = self.features
        if isinstance(features, FeatureSet):
            pass
        elif isinstance(features, Mapping):
            features = FeatureSet.from_dict(features)
        elif isinstance(features, Sequence) and not isinstance(
            features, (str, bytes, bytearray)
        ):
            features = FeatureSet.from_features(features)
        else:
            raise TranslationPathPlannerError(
                "features must be a FeatureSet, mapping, or sequence"
            )
        object.__setattr__(self, "features", features)

        composition = self.composition
        if isinstance(composition, Mapping):
            composition = TranslationCompositionReceipt.from_dict(composition)
        if not isinstance(composition, TranslationCompositionReceipt):
            raise TranslationPathPlannerError(
                "composition must be a TranslationCompositionReceipt"
            )
        object.__setattr__(self, "composition", composition)

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
        if not isinstance(self.proof_safe, bool):
            raise TranslationPathPlannerError("proof_safe must be a bool")
        if not isinstance(self.counterexample_safe, bool):
            raise TranslationPathPlannerError(
                "counterexample_safe must be a bool"
            )

        assumptions = self.assumptions
        if isinstance(assumptions, Mapping):
            assumptions = TranslationAssumptionSet.from_dict(assumptions)
        if not isinstance(assumptions, TranslationAssumptionSet):
            raise TranslationPathPlannerError(
                "assumptions must be a TranslationAssumptionSet"
            )
        object.__setattr__(self, "assumptions", assumptions)

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
            self,
            "covered_features",
            _strings(self.covered_features, "covered_features", identifiers=True),
        )
        object.__setattr__(
            self, "checker_route", _optional_text(self.checker_route, "checker_route")
        )
        object.__setattr__(
            self,
            "reconstruction_route",
            _optional_text(self.reconstruction_route, "reconstruction_route"),
        )
        if not isinstance(self.hop_count, int) or isinstance(self.hop_count, bool):
            raise TranslationPathPlannerError("hop_count must be an int")
        if self.hop_count != len(self.edge_contract_ids):
            raise TranslationPathPlannerError(
                "hop_count must equal the number of edge contracts"
            )
        object.__setattr__(
            self, "planner_id", _text(self.planner_id, "planner_id")
        )
        object.__setattr__(
            self,
            "description",
            _optional_text(self.description, "description"),
        )

        # Receipt fields must match the composition (no silent upgrade).
        if self.preservation is not composition.preservation:
            raise TranslationPathPlannerError(
                "path preservation must match composition preservation"
            )
        if self.authority_ceiling is not composition.authority_ceiling:
            raise TranslationPathPlannerError(
                "path authority_ceiling must match composition authority_ceiling"
            )
        if self.proof_safe is not composition.proof_safe:
            raise TranslationPathPlannerError(
                "path proof_safe must match composition proof_safe"
            )
        if self.counterexample_safe is not composition.counterexample_safe:
            raise TranslationPathPlannerError(
                "path counterexample_safe must match composition "
                "counterexample_safe"
            )
        maximum = maximum_authority_for(self.preservation)
        if not authority_at_most(self.authority_ceiling, maximum):
            raise TranslationPathPlannerError(
                f"path {self.preservation.value} cannot carry "
                f"{self.authority_ceiling.value} authority"
            )

        computed = self._compute_identity()
        if self.path_content_id and self.path_content_id != computed.cid:
            raise TranslationPathPlannerError(
                "path_content_id does not match canonical path content"
            )
        object.__setattr__(self, "path_content_id", computed.cid)

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=PATH_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def content_id(self) -> str:
        return self.path_content_id

    def semantic_dict(self) -> dict[str, Any]:
        """Canonical identity preimage (excludes path_content_id)."""

        return {
            "assumptions": self.assumptions.to_dict(),
            "authority_ceiling": self.authority_ceiling.value,
            "checker_route": self.checker_route,
            "composition_content_id": self.composition.composition_content_id,
            "composition_id": self.composition.composition_id,
            "counterexample_safe": self.counterexample_safe,
            "covered_features": list(self.covered_features),
            "description": self.description,
            "edge_content_ids": list(self.edge_content_ids),
            "edge_contract_ids": list(self.edge_contract_ids),
            "feature_preconditions": list(self.feature_preconditions),
            "features": self.features.to_dict(),
            "hop_count": self.hop_count,
            "interface": self.interface,
            "path_id": self.path_id,
            "planner_id": self.planner_id,
            "preservation": self.preservation.value,
            "proof_safe": self.proof_safe,
            "reconstruction_route": self.reconstruction_route,
            "schema_version": self.schema_version,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "unsupported_constructs": list(self.unsupported_constructs),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["composition"] = self.composition.to_dict()
        payload["path_content_id"] = self.path_content_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TranslationPathReceipt":
        value = _mapping(value, "translation path receipt")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumptions",
                    "authority_ceiling",
                    "checker_route",
                    "composition",
                    "composition_content_id",
                    "composition_id",
                    "counterexample_safe",
                    "covered_features",
                    "description",
                    "edge_content_ids",
                    "edge_contract_ids",
                    "feature_preconditions",
                    "features",
                    "hop_count",
                    "interface",
                    "path_content_id",
                    "path_id",
                    "planner_id",
                    "preservation",
                    "proof_safe",
                    "reconstruction_route",
                    "schema_version",
                    "source",
                    "target",
                    "unsupported_constructs",
                }
            ),
            "translation path receipt",
        )
        interface = value.get("interface", PATH_RECEIPT_INTERFACE)
        if interface != PATH_RECEIPT_INTERFACE:
            raise TranslationPathPlannerError(
                f"unsupported path receipt interface {interface!r}"
            )
        schema = value.get("schema_version", PATH_RECEIPT_SCHEMA_VERSION)
        if schema != PATH_RECEIPT_SCHEMA_VERSION:
            raise TranslationPathPlannerError(
                f"unsupported path receipt schema {schema!r}"
            )
        return cls(
            path_id=value.get("path_id", ""),
            edge_contract_ids=tuple(value.get("edge_contract_ids", ())),
            edge_content_ids=tuple(value.get("edge_content_ids", ())),
            source=value.get("source", {}),  # type: ignore[arg-type]
            target=value.get("target", {}),  # type: ignore[arg-type]
            features=value.get("features", ()),  # type: ignore[arg-type]
            composition=value.get("composition", {}),  # type: ignore[arg-type]
            preservation=value.get("preservation", ""),
            authority_ceiling=value.get(
                "authority_ceiling", EvidenceAuthority.NONE.value
            ),
            proof_safe=bool(value.get("proof_safe", False)),
            counterexample_safe=bool(value.get("counterexample_safe", False)),
            assumptions=value.get("assumptions", {}),  # type: ignore[arg-type]
            unsupported_constructs=tuple(
                value.get("unsupported_constructs", ())
            ),
            feature_preconditions=tuple(value.get("feature_preconditions", ())),
            covered_features=tuple(value.get("covered_features", ())),
            checker_route=value.get("checker_route", ""),
            reconstruction_route=value.get("reconstruction_route", ""),
            hop_count=int(value.get("hop_count", 0)),
            planner_id=value.get("planner_id", PLANNER_ID),
            description=value.get("description", ""),
            path_content_id=value.get("path_content_id", ""),
        )


class TranslationPathPlanner:
    """Deterministic compositional path planner (``TranslationPathPlanner@1``).

    The planner holds only reviewed :class:`TranslationContract` edges.  It
    performs no compilation, provider execution, or network I/O.
    """

    interface: ClassVar[str] = PLANNER_INTERFACE
    planner_id: ClassVar[str] = PLANNER_ID

    def __init__(
        self,
        edges: Sequence[TranslationContract] | None = None,
        *,
        planner_id: str = PLANNER_ID,
    ) -> None:
        if not isinstance(planner_id, str) or not planner_id.strip():
            raise TranslationPathPlannerError(
                "planner_id must be a non-empty string"
            )
        self._planner_id = planner_id.strip()
        self._edges: list[TranslationContract] = []
        self._by_id: dict[str, TranslationContract] = {}
        # adjacency: (family, profile) -> list of contracts leaving that node
        self._adjacency: dict[tuple[str, str], list[TranslationContract]] = {}
        if edges:
            self.register_edges(edges)

    @property
    def registered_edges(self) -> tuple[TranslationContract, ...]:
        """Return registered edges in stable contract_id order."""

        return tuple(
            sorted(self._edges, key=lambda edge: (edge.contract_id, edge.contract_content_id))
        )

    def register_edge(self, edge: TranslationContract) -> None:
        """Register one reviewed translation edge descriptor."""

        if not isinstance(edge, TranslationContract):
            raise TranslationPathPlannerError(
                "edge must be a TranslationContract"
            )
        existing = self._by_id.get(edge.contract_id)
        if existing is not None:
            if existing.contract_content_id != edge.contract_content_id:
                raise TranslationPathPlannerError(
                    f"duplicate contract_id {edge.contract_id!r} with "
                    "different content identity"
                )
            return
        self._edges.append(edge)
        self._by_id[edge.contract_id] = edge
        key = _endpoint_key(edge.source)
        self._adjacency.setdefault(key, []).append(edge)
        # Also index under family-only (empty profile) for profile-flexible match.
        family_key = (edge.source.family_id, "")
        if key != family_key:
            self._adjacency.setdefault(family_key, []).append(edge)

    def register_edges(self, edges: Sequence[TranslationContract]) -> None:
        for index, edge in enumerate(edges):
            try:
                self.register_edge(edge)
            except TranslationPathPlannerError as error:
                raise TranslationPathPlannerError(
                    f"edges[{index}]: {error}"
                ) from error

    def edges_from(
        self, family_id: str, profile_id: str = ""
    ) -> tuple[TranslationContract, ...]:
        """Return outgoing edges for *family_id*/*profile_id* in stable order."""

        seen: set[str] = set()
        result: list[TranslationContract] = []
        keys = [(family_id, profile_id or "")]
        if profile_id:
            keys.append((family_id, ""))
        for key in keys:
            for edge in self._adjacency.get(key, ()):
                if edge.contract_id in seen:
                    continue
                if not _matches_endpoint(edge.source, family_id, profile_id):
                    continue
                seen.add(edge.contract_id)
                result.append(edge)
        result.sort(key=lambda edge: (edge.contract_id, edge.contract_content_id))
        return tuple(result)

    def plan(
        self,
        request: TranslationPathRequest | Mapping[str, Any],
    ) -> TranslationPathReceipt:
        """Select a feature-total path and return a deterministic receipt.

        Raises :class:`TranslationPathPlannerError` when:

        * no registered path connects source to target;
        * every candidate path has unsupported features or is not feature-total;
        * a path would launder authority, approximation, or polarity claims.
        """

        if isinstance(request, Mapping):
            request = TranslationPathRequest.from_dict(request)
        if not isinstance(request, TranslationPathRequest):
            raise TranslationPathPlannerError(
                "request must be a TranslationPathRequest or mapping"
            )

        # Enumerate structural candidates without dropping unsupported-feature
        # edges so diagnostics can fail closed with the right reason.
        candidates = self._enumerate_paths(request, respect_features=False)
        if not candidates:
            raise TranslationPathPlannerError(
                "no translation path from "
                f"{request.source_family_id!r} to {request.target_family_id!r} "
                f"within {request.max_hops} hops"
            )

        feature_failures: list[str] = []
        unsupported_failures: list[str] = []
        laundering_failures: list[str] = []
        valid: list[
            tuple[tuple[TranslationContract, ...], TranslationCompositionReceipt]
        ] = []

        for path in candidates:
            total, unhandled, unsupported = path_is_feature_total(
                path, request.features
            )
            if not total:
                if unsupported:
                    unsupported_failures.append(
                        "unsupported features on path "
                        f"{tuple(c.contract_id for c in path)}: "
                        + ", ".join(unsupported)
                    )
                if unhandled:
                    feature_failures.append(
                        "features not covered by path "
                        f"{tuple(c.contract_id for c in path)}: "
                        + ", ".join(unhandled)
                    )
                # Missing preconditions also surface as unhandled/missing.
                for edge in path:
                    compatible, missing, hits = edge_feature_compatibility(
                        edge, request.features
                    )
                    if missing:
                        feature_failures.append(
                            f"missing feature preconditions on {edge.contract_id!r}: "
                            + ", ".join(missing)
                        )
                    if hits:
                        unsupported_failures.append(
                            f"unsupported features on {edge.contract_id!r}: "
                            + ", ".join(hits)
                        )
                continue

            try:
                composition = compose_translations(*path)
            except TranslationContractError as error:
                laundering_failures.append(
                    f"composition failed for "
                    f"{tuple(c.contract_id for c in path)}: {error}"
                )
                continue

            laundering = _detect_authority_laundering(path, composition, request)
            if laundering is not None:
                laundering_failures.append(laundering)
                continue

            valid.append((path, composition))

        if not valid:
            # Fail-closed ordering matches acceptance criteria:
            # unsupported features, then authority/approximation laundering,
            # then generic feature-total / connectivity failure.
            if unsupported_failures:
                details = "; ".join(
                    dict.fromkeys(unsupported_failures + feature_failures)
                )
                raise TranslationPathPlannerError(
                    "unsupported features fail before compilation; " + details
                )
            if laundering_failures:
                details = "; ".join(
                    dict.fromkeys(laundering_failures + feature_failures)
                )
                raise TranslationPathPlannerError(
                    "authority/approximation laundering fails before "
                    "compilation; " + details
                )
            if feature_failures:
                details = "; ".join(dict.fromkeys(feature_failures))
                raise TranslationPathPlannerError(
                    "unsupported features fail before compilation; " + details
                )
            raise TranslationPathPlannerError(
                "no feature-total path from "
                f"{request.source_family_id!r} to {request.target_family_id!r}"
            )

        # Deterministic selection: fewest hops, then lexicographic contract ids,
        # then content ids, then composition content id.
        def sort_key(
            item: tuple[tuple[TranslationContract, ...], TranslationCompositionReceipt],
        ) -> tuple[Any, ...]:
            path, composition = item
            return (
                len(path),
                tuple(edge.contract_id for edge in path),
                tuple(edge.contract_content_id for edge in path),
                composition.composition_content_id,
            )

        path, composition = min(valid, key=sort_key)
        return self._build_receipt(path, composition, request)

    def _enumerate_paths(
        self,
        request: TranslationPathRequest,
        *,
        respect_features: bool = True,
    ) -> list[tuple[TranslationContract, ...]]:
        """BFS enumeration of simple paths (no repeated family+profile nodes).

        When *respect_features* is true, edges that reject requested features or
        whose preconditions are unsatisfied are not expanded.  When false, all
        structural edges are considered so the planner can emit precise
        fail-closed diagnostics for unsupported features.
        """

        start = (request.source_family_id, request.source_profile_id or "")
        goal_family = request.target_family_id
        goal_profile = request.target_profile_id or ""

        # Queue entries: (current_key, path_edges, visited_keys)
        queue: deque[
            tuple[
                tuple[str, str],
                tuple[TranslationContract, ...],
                frozenset[tuple[str, str]],
            ]
        ] = deque()
        queue.append((start, (), frozenset({start})))

        found: list[tuple[TranslationContract, ...]] = []
        # Enumerate every simple path up to max_hops.  Selection among
        # feature-total, non-laundering candidates is deterministic and prefers
        # fewer hops (see plan()).

        while queue:
            current, path, visited = queue.popleft()

            # Expand outgoing edges (only when under hop budget).
            if len(path) >= request.max_hops:
                continue

            family_id, profile_id = current
            outgoing = self.edges_from(family_id, profile_id)
            for edge in outgoing:
                if respect_features:
                    compatible, missing, hits = edge_feature_compatibility(
                        edge, request.features
                    )
                    if hits or missing or not compatible:
                        continue

                next_key = _endpoint_key(edge.target)
                # Cycles among intermediate nodes are rejected.
                if next_key in visited and next_key != current:
                    is_goal = _matches_endpoint(
                        edge.target, goal_family, goal_profile
                    )
                    if not is_goal:
                        continue

                new_path = path + (edge,)
                new_visited = visited | {next_key}

                if _matches_endpoint(edge.target, goal_family, goal_profile):
                    found.append(new_path)
                    # Do not expand beyond a completed goal path.
                    continue

                queue.append((next_key, new_path, new_visited))

        found.sort(
            key=lambda p: (
                len(p),
                tuple(e.contract_id for e in p),
                tuple(e.contract_content_id for e in p),
            )
        )
        return found

    def _build_receipt(
        self,
        path: Sequence[TranslationContract],
        composition: TranslationCompositionReceipt,
        request: TranslationPathRequest,
    ) -> TranslationPathReceipt:
        edge_ids = tuple(edge.contract_id for edge in path)
        edge_content_ids = tuple(edge.contract_content_id for edge in path)
        path_id = "path_" + "_".join(edge_ids)

        covered = _sorted_unique(
            feature
            for edge in path
            for feature in edge.feature_preconditions
        )
        if not covered:
            # Open edges: every requested feature is covered when not unsupported.
            covered = request.features.features

        description = request.description or (
            f"feature-total path {request.source_family_id} -> "
            f"{request.target_family_id} via {', '.join(edge_ids)}"
        )

        return TranslationPathReceipt(
            path_id=path_id,
            edge_contract_ids=edge_ids,
            edge_content_ids=edge_content_ids,
            source=composition.source,
            target=composition.target,
            features=request.features,
            composition=composition,
            preservation=composition.preservation,
            authority_ceiling=composition.authority_ceiling,
            proof_safe=composition.proof_safe,
            counterexample_safe=composition.counterexample_safe,
            assumptions=composition.assumptions,
            unsupported_constructs=composition.unsupported_constructs,
            feature_preconditions=composition.feature_preconditions,
            covered_features=covered,
            checker_route=composition.checker_route,
            reconstruction_route=composition.reconstruction_route,
            hop_count=len(path),
            planner_id=self._planner_id,
            description=description,
        )


def plan_translation_path(
    edges: Sequence[TranslationContract],
    request: TranslationPathRequest | Mapping[str, Any],
    *,
    planner_id: str = PLANNER_ID,
) -> TranslationPathReceipt:
    """Convenience wrapper: register *edges* and plan *request*."""

    planner = TranslationPathPlanner(edges, planner_id=planner_id)
    return planner.plan(request)


__all__ = [
    "DEFAULT_MAX_HOPS",
    "FEATURE_SET_SCHEMA_VERSION",
    "PATH_IDENTITY_DOMAIN",
    "PATH_RECEIPT_INTERFACE",
    "PATH_RECEIPT_SCHEMA_VERSION",
    "PLANNER_ID",
    "PLANNER_INTERFACE",
    "PLAN_REQUEST_SCHEMA_VERSION",
    "FeatureSet",
    "TranslationPathPlanner",
    "TranslationPathPlannerError",
    "TranslationPathReceipt",
    "TranslationPathRequest",
    "edge_feature_compatibility",
    "path_is_feature_total",
    "plan_translation_path",
    "weaker_authority",
    "weaker_preservation",
]
