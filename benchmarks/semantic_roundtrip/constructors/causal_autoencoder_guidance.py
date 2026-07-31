"""CID-bound qualification for causal autoencoder guidance (PLAT-060).

The frozen modal autoencoder exposes a global, sample-free stable-feature
export.  That export is useful advisory / teacher-residual evidence, but it is
not itself an intervention on canonical L1.  This module keeps those concepts
separate:

* the state is loaded read-only and verified by its pinned CID;
* a guidance arm is supported only when an independently reviewed,
  preregistered feature-to-canonical-field contract and applicator are both
  present;
* every resulting canonical change must name its exact stable feature and
  canonical field path; and
* absent that contract, every historical guided arm remains explicit terminal
  unsupported evidence and is excluded from semantic scoring schedules.

Plateau-break role (PLAT-060): the autoencoder is a **teacher residual** source
only.  It is never the production default constructor.  Guided AE cells are
either ``scored_supported`` (when a reviewed causal L1 adapter is preregistered)
or explicitly ``not_measured`` / ``terminal_unsupported`` with
``schedule_for_semantic_scoring=false``.

The repository currently has no reviewed causal L1 adapter.  Consequently the
checked-in qualification artifact is intentionally
``unavailable_no_reviewed_causal_l1_adapter``.  The matrix planner API exposed
here keeps guided cells off the semantic schedule (``not_measured`` only).
Advisory diagnostics are never promoted into fabricated canonical mutations.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.semantic_roundtrip.contracts import (
    RULE_FIELDS,
    AllowedAtomVocabulary,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
    RoundTripConstructor,
)
from benchmarks.semantic_roundtrip.constructors.autoencoder_guided import (
    DEFAULT_AUTOENCODER_STATE_PATH,
    PINNED_AUTOENCODER_DECLARED_ARCHITECTURE,
    PINNED_AUTOENCODER_EFFECTIVE_ARCHITECTURE,
    PINNED_AUTOENCODER_STATE_CID,
    PINNED_AUTOENCODER_STATE_SCHEMA,
    PINNED_AUTOENCODER_STATE_SHA256,
    CanonicalFieldChange,
    FrozenAutoencoderGuidance,
    GuidanceLoader,
    canonical_field_changes,
    load_frozen_autoencoder_guidance,
)
from benchmarks.semantic_roundtrip_capabilities import REPO_ROOT


CAUSAL_AUTOENCODER_GUIDANCE_INTERFACE: Final = (
    "CausalAutoencoderGuidance@1"
)
CAUSAL_GUIDANCE_QUALIFICATION_INTERFACE: Final = (
    "CausalGuidanceQualification@1"
)
CAUSAL_GUIDANCE_QUALIFICATION_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-causal-guidance-qualification.v1"
)
REVIEWED_CAUSAL_L1_CONTRACT_INTERFACE: Final = (
    "ReviewedFeatureToCanonicalFieldIntervention@1"
)
CAUSAL_CHANGE_RECEIPT_INTERFACE: Final = "CausalGuidanceChangeReceipt@1"
CAUSAL_MATRIX_PLANNER_INTERFACE: Final = "CausalGuidanceMatrixPlanner@1"
TEACHER_RESIDUAL_INTERFACE: Final = "CausalAutoencoderTeacherResidual@1"
UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER: Final = (
    "unavailable_no_reviewed_causal_l1_adapter"
)
SCORED_SUPPORTED: Final = "scored_supported"
TERMINAL_UNSUPPORTED: Final = "terminal_unsupported"
EVALUATION_STATUS_NOT_MEASURED: Final = "not_measured"
SEMANTIC_SCHEDULE_EXCLUDED: Final = "excluded_from_semantic_schedule"
MATRIX_SCHEDULE_POLICY: Final = (
    "exclude_guided_without_reviewed_causal_l1_adapter"
)
TEACHER_RESIDUAL_ROLE: Final = "teacher_residual_only"
TEACHER_RESIDUAL_PROMOTION_REQUIRES: Final = "reviewed_causal_l1_adapter"
PLATEAU_BREAK_TASK_ID: Final = "PLAT-060"
PLATEAU_BREAK_BOARD_NAMESPACE: Final = "semantic-roundtrip-plateau-break-v1"

STABLE_EXPORT_SCHEMA: Final = (
    "legal-ir-stable-autoencoder-feature-export-v1"
)
SRT021_MANIFEST_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "no_eligible_remediation_manifest.json"
)
DEFAULT_QUALIFICATION_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "causal_autoencoder_guidance_qualification.json"
)
DEFAULT_QUALIFICATION_PATH: Final = (
    REPO_ROOT / DEFAULT_QUALIFICATION_RELATIVE_PATH
)
PINNED_SRT021_MANIFEST_CID: Final = (
    "baguqeerarr7ebjrzd3argtdekd7er3bqrnvhuzy2ogqzfi7h5nv37dbea52a"
)

MISSING_CAUSAL_CONTRACT_FIELDS: Final = (
    "independent_review_cid",
    "reviewed_adapter_identity",
    "preregistered_stable_feature_ids",
    "preregistered_feature_to_canonical_field_map",
    "source_grounding_preservation_review",
    "nonempty_causal_change_receipt",
)
FORBIDDEN_CAUSAL_INPUTS: Final = (
    "sample_memory",
    "gold_labels",
    "gold_rule_counts",
    "target_embeddings",
    "outcome_dependent_selection",
)
CAUSAL_SELECTION_RULE: Final = (
    "apply_preregistered_interventions_without_outcome_observation"
)
SOURCE_GROUNDING_RULE: Final = (
    "preserve_rule_cardinality_and_closed_source_vocabulary"
)

_REQUIRED_EXCLUDED_CATEGORIES: Final = frozenset(
    {
        "decoded_embeddings",
        "raw_source_text",
        "sample_identifiers",
        "sample_memory",
        "source_spans",
        "token_features",
    }
)
_FORBIDDEN_CONFIG_MARKERS: Final = (
    "sample_memory",
    "sample_specific_memory",
    "gold_label",
    "gold_labels",
    "gold_rule_count",
    "gold_rule_counts",
    "gold_ir",
    "expected_ir",
    "target_embedding",
    "target_embeddings",
    "target_vector",
    "target_vectors",
    "outcome_dependent",
    "outcome_selection",
    "selection_outcome",
)


class CausalQualificationStatus(str, Enum):
    """Terminal result of one causal-guidance qualification."""

    QUALIFIED = "qualified_causal_l1_adapter"
    UNAVAILABLE = UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER
    FAILED = "causal_guidance_qualification_failed"


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractError("value must be finite JSON data") from exc


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalized(value: object) -> str:
    text = str(value).strip()
    result: list[str] = []
    for index, character in enumerate(text):
        if (
            index
            and character.isupper()
            and text[index - 1].islower()
        ):
            result.append("_")
        result.append(character.lower() if character.isalnum() else "_")
    return "_".join(part for part in "".join(result).split("_") if part)


def _nonblank(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a nonblank string")
    return value.strip()


def _forbidden_config_path(
    value: object, path: str = "request.config"
) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _normalized(key)
            if any(marker in normalized for marker in _FORBIDDEN_CONFIG_MARKERS):
                return f"{path}.{key}"
            nested = _forbidden_config_path(item, f"{path}.{key}")
            if nested is not None:
                return nested
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            nested = _forbidden_config_path(item, f"{path}[{index}]")
            if nested is not None:
                return nested
    elif isinstance(value, str):
        normalized = _normalized(value)
        if any(marker in normalized for marker in _FORBIDDEN_CONFIG_MARKERS):
            return path
    return None


def _strict_json_object(path: Path) -> dict[str, object]:
    def reject_duplicates(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ContractError(
                    f"duplicate JSON key {key!r} in {path}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load strict JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{path} must contain a JSON object")
    return value


@dataclass(frozen=True, slots=True)
class StableExportEvidence:
    """Verified global and sample-free properties of the stable export."""

    export_id: str
    schema_version: str
    feature_count: int
    feature_ids: tuple[str, ...]
    feature_names: tuple[str, ...]
    excluded_categories: tuple[str, ...]
    sample_count: int
    sample_memory_included: bool
    global_export: bool = True
    sample_free: bool = True

    def __post_init__(self) -> None:
        _nonblank(self.export_id, "stable export ID")
        if self.schema_version != STABLE_EXPORT_SCHEMA:
            raise ContractError("stable export schema differs from the pin")
        if (
            isinstance(self.feature_count, bool)
            or not isinstance(self.feature_count, int)
            or self.feature_count < 1
        ):
            raise ContractError("stable export must contain stable features")
        if (
            len(self.feature_ids) != self.feature_count
            or len(self.feature_names) != self.feature_count
            or len(set(self.feature_ids)) != self.feature_count
            or len(set(self.feature_names)) != self.feature_count
        ):
            raise ContractError(
                "stable export feature identities are incomplete or duplicate"
            )
        if (
            isinstance(self.sample_count, bool)
            or self.sample_count != 0
            or self.sample_memory_included is not False
            or self.global_export is not True
            or self.sample_free is not True
        ):
            raise ContractError(
                "stable export is not global and sample-free"
            )
        if not _REQUIRED_EXCLUDED_CATEGORIES <= set(
            self.excluded_categories
        ):
            raise ContractError(
                "stable export does not exclude every sample-specific category"
            )

    @classmethod
    def from_guidance(
        cls, guidance: FrozenAutoencoderGuidance
    ) -> "StableExportEvidence":
        if not isinstance(guidance, FrozenAutoencoderGuidance):
            raise ContractError(
                "guidance loader did not return frozen guidance"
            )
        export = guidance.stable_export
        features = export.get("stable_features")
        if not isinstance(features, Sequence) or isinstance(
            features, (str, bytes, bytearray)
        ):
            raise ContractError("stable_features must be an array")
        feature_ids: list[str] = []
        feature_names: list[str] = []
        for index, item in enumerate(features):
            if not isinstance(item, Mapping):
                raise ContractError(
                    f"stable_features[{index}] must be an object"
                )
            if item.get("stable") is not True:
                raise ContractError(
                    f"stable_features[{index}] is not stable"
                )
            feature_ids.append(
                _nonblank(
                    item.get("feature_id"),
                    f"stable_features[{index}].feature_id",
                )
            )
            feature_names.append(
                _nonblank(
                    item.get("feature"),
                    f"stable_features[{index}].feature",
                )
            )
        excluded = export.get("excluded_categories")
        if not isinstance(excluded, Sequence) or isinstance(
            excluded, (str, bytes, bytearray)
        ):
            raise ContractError("excluded_categories must be an array")
        excluded_categories = tuple(
            _nonblank(item, "excluded category") for item in excluded
        )
        declared_count = export.get("feature_count")
        if declared_count != len(features):
            raise ContractError(
                "stable export feature_count does not match stable_features"
            )
        return cls(
            export_id=_nonblank(export.get("export_id"), "stable export ID"),
            schema_version=_nonblank(
                export.get("schema_version"), "stable export schema"
            ),
            feature_count=len(features),
            feature_ids=tuple(feature_ids),
            feature_names=tuple(feature_names),
            excluded_categories=excluded_categories,
            sample_count=export.get("sample_count"),  # type: ignore[arg-type]
            sample_memory_included=export.get(  # type: ignore[arg-type]
                "sample_memory_included"
            ),
        )

    @property
    def feature_identity_sha256(self) -> str:
        return _sha(
            [
                {"feature_id": feature_id, "feature": feature}
                for feature_id, feature in zip(
                    self.feature_ids, self.feature_names, strict=True
                )
            ]
        )

    def feature_map(self) -> dict[str, str]:
        return dict(
            zip(self.feature_ids, self.feature_names, strict=True)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "excluded_categories": list(self.excluded_categories),
            "export_id": self.export_id,
            "feature_count": self.feature_count,
            "feature_identity_sha256": self.feature_identity_sha256,
            "global": True,
            "sample_count": 0,
            "sample_free": True,
            "sample_memory_included": False,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class FeatureToCanonicalFieldIntervention:
    """One reviewed mapping from a stable feature to bounded L1 fields."""

    feature_id: str
    feature: str
    canonical_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        _nonblank(self.feature_id, "intervention feature_id")
        _nonblank(self.feature, "intervention feature")
        fields = tuple(self.canonical_fields)
        if (
            not fields
            or len(set(fields)) != len(fields)
            or any(field not in RULE_FIELDS for field in fields)
        ):
            raise ContractError(
                "intervention canonical_fields must be nonempty, unique, "
                "canonical fields"
            )
        object.__setattr__(self, "canonical_fields", fields)

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_fields": list(self.canonical_fields),
            "feature": self.feature,
            "feature_id": self.feature_id,
        }


@dataclass(frozen=True, slots=True)
class ReviewedCausalL1Contract:
    """Immutable preregistration for an independently reviewed adapter."""

    adapter_id: str
    independent_review_cid: str
    reviewed_by: str
    stable_export_id: str
    interventions: tuple[FeatureToCanonicalFieldIntervention, ...]
    selection_rule: str = CAUSAL_SELECTION_RULE
    source_grounding_rule: str = SOURCE_GROUNDING_RULE

    def __post_init__(self) -> None:
        _nonblank(self.adapter_id, "reviewed adapter ID")
        _nonblank(self.reviewed_by, "review authority")
        _nonblank(self.stable_export_id, "reviewed stable export ID")
        try:
            validate_cid(
                self.independent_review_cid, codecs=("dag-json",)
            )
        except (TypeError, ValueError) as exc:
            raise ContractError(
                "independent_review_cid must be a canonical DAG-JSON CID"
            ) from exc
        if self.selection_rule != CAUSAL_SELECTION_RULE:
            raise ContractError(
                "causal selection must be preregistered and outcome-independent"
            )
        if self.source_grounding_rule != SOURCE_GROUNDING_RULE:
            raise ContractError(
                "causal adapter must preserve the source-grounding rule"
            )
        interventions = tuple(self.interventions)
        if not interventions or not all(
            isinstance(item, FeatureToCanonicalFieldIntervention)
            for item in interventions
        ):
            raise ContractError(
                "reviewed contract requires feature-to-field interventions"
            )
        feature_ids = [item.feature_id for item in interventions]
        if len(set(feature_ids)) != len(feature_ids):
            raise ContractError(
                "reviewed intervention feature IDs must be unique"
            )
        object.__setattr__(self, "interventions", interventions)

    @property
    def identity(self) -> str:
        return f"{REVIEWED_CAUSAL_L1_CONTRACT_INTERFACE}:{self.adapter_id}"

    @property
    def digest(self) -> str:
        return _sha(self.to_dict())

    def intervention_map(
        self,
    ) -> dict[str, FeatureToCanonicalFieldIntervention]:
        return {item.feature_id: item for item in self.interventions}

    def validate_export(self, evidence: StableExportEvidence) -> None:
        if self.stable_export_id != evidence.export_id:
            raise ContractError(
                "reviewed contract targets a different stable export"
            )
        exported = evidence.feature_map()
        for intervention in self.interventions:
            if exported.get(intervention.feature_id) != intervention.feature:
                raise ContractError(
                    "reviewed contract contains an absent or renamed "
                    f"stable feature: {intervention.feature_id}"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "adapter_id": self.adapter_id,
            "forbidden_inputs": list(FORBIDDEN_CAUSAL_INPUTS),
            "independent_review_cid": self.independent_review_cid,
            "interface": REVIEWED_CAUSAL_L1_CONTRACT_INTERFACE,
            "interventions": [
                item.to_dict() for item in self.interventions
            ],
            "reviewed_by": self.reviewed_by,
            "selection_rule": self.selection_rule,
            "source_grounding_rule": self.source_grounding_rule,
            "stable_export_id": self.stable_export_id,
        }


@dataclass(frozen=True, slots=True)
class CausalFeatureAttribution:
    """One stable feature claimed as a cause of one exact field change."""

    feature_id: str
    feature: str
    changed_field_path: str

    def __post_init__(self) -> None:
        _nonblank(self.feature_id, "causal attribution feature_id")
        _nonblank(self.feature, "causal attribution feature")
        _nonblank(self.changed_field_path, "causal changed_field_path")

    def to_dict(self) -> dict[str, str]:
        return {
            "changed_field_path": self.changed_field_path,
            "feature": self.feature,
            "feature_id": self.feature_id,
        }


@dataclass(frozen=True, slots=True)
class CausalAdapterOutput:
    """Canonical output and the adapter's complete causal attribution."""

    canonical_ir: CanonicalRuleIR
    attributions: tuple[CausalFeatureAttribution, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_ir, CanonicalRuleIR):
            raise ContractError(
                "causal adapter output requires CanonicalRuleIR"
            )
        values = tuple(self.attributions)
        if not values or not all(
            isinstance(item, CausalFeatureAttribution) for item in values
        ):
            raise ContractError(
                "causal adapter output requires nonempty feature attribution"
            )
        if len(set(values)) != len(values):
            raise ContractError("causal attributions must be unique")
        object.__setattr__(self, "attributions", values)


@runtime_checkable
class ReviewedCausalL1Applicator(Protocol):
    """Narrow adapter boundary: no source, labels, targets, or outcomes."""

    def __call__(
        self,
        baseline_ir: CanonicalRuleIR,
        allowed_atom_vocabulary: AllowedAtomVocabulary,
        guidance: FrozenAutoencoderGuidance,
    ) -> CausalAdapterOutput:
        """Apply the preregistered intervention."""


@dataclass(frozen=True, slots=True)
class CausalGuidanceChangeReceipt:
    """Complete, nonempty causal change receipt for a supported adapter."""

    contract_identity: str
    contract_digest: str
    changes: tuple[CanonicalFieldChange, ...]
    attributions: tuple[CausalFeatureAttribution, ...]
    source_sha256: str
    vocabulary_sha256: str

    def __post_init__(self) -> None:
        _nonblank(self.contract_identity, "causal contract identity")
        _nonblank(self.contract_digest, "causal contract digest")
        if not self.changes or not all(
            isinstance(item, CanonicalFieldChange) for item in self.changes
        ):
            raise ContractError(
                "causal change receipt must contain canonical changes"
            )
        if not self.attributions or not all(
            isinstance(item, CausalFeatureAttribution)
            for item in self.attributions
        ):
            raise ContractError(
                "causal change receipt must name causal features"
            )
        for name in ("source_sha256", "vocabulary_sha256"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise ContractError(f"{name} must be a SHA-256 digest")

    @property
    def changed_fields(self) -> tuple[str, ...]:
        present = {change.canonical_field for change in self.changes}
        return tuple(field for field in RULE_FIELDS if field in present)

    @property
    def changed_field_paths(self) -> tuple[str, ...]:
        return tuple(change.path for change in self.changes)

    @property
    def causal_feature_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(item.feature_id for item in self.attributions)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "attributions": [
                item.to_dict() for item in self.attributions
            ],
            "causal_feature_ids": list(self.causal_feature_ids),
            "changed_field_paths": list(self.changed_field_paths),
            "changed_fields": list(self.changed_fields),
            "changes": [item.to_dict() for item in self.changes],
            "contract_digest": self.contract_digest,
            "contract_identity": self.contract_identity,
            "interface": CAUSAL_CHANGE_RECEIPT_INTERFACE,
            "source_sha256": self.source_sha256,
            "vocabulary_sha256": self.vocabulary_sha256,
        }


@dataclass(frozen=True, slots=True)
class NegativeControlReceipt:
    """Proof that disabling guidance leaves canonical L1 unchanged."""

    baseline_sha256: str
    no_guidance_sha256: str
    canonical_l1_changed: bool = False
    changed_fields: tuple[str, ...] = ()
    causal_feature_ids: tuple[str, ...] = ()
    guidance_enabled: bool = False

    def __post_init__(self) -> None:
        if (
            self.baseline_sha256 != self.no_guidance_sha256
            or self.canonical_l1_changed
            or self.changed_fields
            or self.causal_feature_ids
            or self.guidance_enabled
        ):
            raise ContractError(
                "disabled-guidance negative control must have zero change"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline_sha256": self.baseline_sha256,
            "canonical_l1_changed": False,
            "causal_feature_ids": [],
            "changed_fields": [],
            "guidance_enabled": False,
            "no_guidance_sha256": self.no_guidance_sha256,
            "passed": True,
        }


@dataclass(frozen=True, slots=True)
class CausalGuidancePairResult:
    """Paired outputs under one shared set of non-guidance inputs."""

    no_guidance: ConstructorResult
    guided: ConstructorResult
    status: CausalQualificationStatus
    negative_control: NegativeControlReceipt
    state_evidence: StableExportEvidence
    change_receipt: CausalGuidanceChangeReceipt | None = None
    missing_causal_contract: tuple[str, ...] = ()
    guided_disposition: str = "scored_supported"

    def __post_init__(self) -> None:
        if not isinstance(self.no_guidance, ConstructorResult) or not isinstance(
            self.guided, ConstructorResult
        ):
            raise ContractError("paired outputs must be ConstructorResult")
        if self.status is CausalQualificationStatus.QUALIFIED:
            if (
                self.change_receipt is None
                or self.guided.status is not ComponentStatus.SUCCESS
                or self.missing_causal_contract
                or self.guided_disposition != "scored_supported"
            ):
                raise ContractError(
                    "qualified guidance requires a successful changed output"
                )
        elif self.status is CausalQualificationStatus.UNAVAILABLE:
            if (
                self.change_receipt is not None
                or tuple(self.missing_causal_contract)
                != MISSING_CAUSAL_CONTRACT_FIELDS
                or self.guided.status is not ComponentStatus.FAILED
                or self.guided.failure_reason
                is not FailureReason.CAPABILITY_UNAVAILABLE
                or self.guided_disposition != "terminal_unsupported"
            ):
                raise ContractError(
                    "unavailable guidance must remain terminal unsupported"
                )


def _failure(reason: FailureReason, detail: str) -> ConstructorResult:
    return ConstructorResult(
        ComponentStatus.FAILED,
        failure_reason=reason,
        failure_detail=detail[:1000],
    )


class CausalAutoencoderGuidance:
    """Run a preregistered causal pair or fail closed without one."""

    interface: Final = CAUSAL_AUTOENCODER_GUIDANCE_INTERFACE

    def __init__(
        self,
        base_constructor: RoundTripConstructor | None = None,
        *,
        reviewed_contract: ReviewedCausalL1Contract | None = None,
        applicator: ReviewedCausalL1Applicator | None = None,
        guidance_loader: GuidanceLoader = load_frozen_autoencoder_guidance,
        state_path: Path = DEFAULT_AUTOENCODER_STATE_PATH,
    ) -> None:
        if base_constructor is None:
            from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
                TypedDeonticCanonicalConstructor,
            )

            base_constructor = TypedDeonticCanonicalConstructor()
        if not isinstance(base_constructor, RoundTripConstructor):
            raise ContractError(
                "base_constructor must implement RoundTripConstructor"
            )
        if (reviewed_contract is None) != (applicator is None):
            raise ContractError(
                "reviewed contract and causal applicator must be supplied "
                "together"
            )
        if reviewed_contract is not None and not isinstance(
            reviewed_contract, ReviewedCausalL1Contract
        ):
            raise ContractError(
                "reviewed_contract must be ReviewedCausalL1Contract"
            )
        if applicator is not None and not callable(applicator):
            raise ContractError("causal applicator must be callable")
        if not callable(guidance_loader):
            raise ContractError("guidance_loader must be callable")
        self._base_constructor = base_constructor
        self._reviewed_contract = reviewed_contract
        self._applicator = applicator
        self._guidance_loader = guidance_loader
        self._state_path = Path(state_path)

    @property
    def identity(self) -> str:
        adapter = (
            self._reviewed_contract.identity
            if self._reviewed_contract is not None
            else UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER
        )
        return (
            f"{self.interface}:{self._base_constructor.identity}:"
            f"{PINNED_AUTOENCODER_STATE_CID}:{adapter}"
        )

    def _load_evidence(
        self,
    ) -> tuple[FrozenAutoencoderGuidance, StableExportEvidence]:
        guidance = self._guidance_loader(self._state_path)
        if not isinstance(guidance, FrozenAutoencoderGuidance):
            raise ContractError(
                "guidance_loader must return FrozenAutoencoderGuidance"
            )
        return guidance, StableExportEvidence.from_guidance(guidance)

    def construct_pair(
        self, request: ConstructorRequest
    ) -> CausalGuidancePairResult:
        """Produce paired outputs from exactly one baseline construction."""

        if not isinstance(request, ConstructorRequest):
            raise ContractError("request must be ConstructorRequest")
        forbidden = _forbidden_config_path(request.config)
        if forbidden is not None:
            raise ContractError(
                f"{forbidden} is a forbidden causal-guidance input"
            )

        # Qualification always verifies the frozen state, including the
        # unavailable path.  The loader opens it read-only and checks both CID
        # and digest before this method observes the stable export.
        guidance, export_evidence = self._load_evidence()
        baseline = self._base_constructor.construct(request)
        if not isinstance(baseline, ConstructorResult):
            raise ContractError(
                "base constructor returned a non-ConstructorResult"
            )
        if baseline.status is ComponentStatus.FAILED:
            digest = _sha(
                {
                    "failure_reason": (
                        baseline.failure_reason.value
                        if baseline.failure_reason is not None
                        else None
                    ),
                    "failure_detail": baseline.failure_detail,
                }
            )
            return CausalGuidancePairResult(
                no_guidance=baseline,
                guided=baseline,
                status=CausalQualificationStatus.FAILED,
                negative_control=NegativeControlReceipt(digest, digest),
                state_evidence=export_evidence,
                guided_disposition="baseline_failed_before_intervention",
            )
        assert baseline.canonical_ir is not None
        baseline_payload = baseline.canonical_ir.to_dict()
        baseline_digest = _sha(baseline_payload)
        negative_control = NegativeControlReceipt(
            baseline_sha256=baseline_digest,
            no_guidance_sha256=baseline_digest,
        )

        if self._reviewed_contract is None:
            detail = (
                f"{UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER}: "
                "the stable export is advisory; no reviewed causal contract "
                "maps its features to canonical L1 fields"
            )
            return CausalGuidancePairResult(
                no_guidance=baseline,
                guided=_failure(
                    FailureReason.CAPABILITY_UNAVAILABLE, detail
                ),
                status=CausalQualificationStatus.UNAVAILABLE,
                negative_control=negative_control,
                state_evidence=export_evidence,
                missing_causal_contract=MISSING_CAUSAL_CONTRACT_FIELDS,
                guided_disposition="terminal_unsupported",
            )

        assert self._applicator is not None
        self._reviewed_contract.validate_export(export_evidence)
        try:
            application = self._applicator(
                baseline.canonical_ir,
                request.allowed_atom_vocabulary,
                guidance,
            )
            if not isinstance(application, CausalAdapterOutput):
                raise ContractError(
                    "causal applicator must return CausalAdapterOutput"
                )
            guided_ir = application.canonical_ir
            guided_ir.validate_vocabulary(request.allowed_atom_vocabulary)
            if guided_ir.is_empty:
                raise ContractError(
                    "causal applicator produced empty canonical L1"
                )
            if len(guided_ir.rules) != len(baseline.canonical_ir.rules):
                raise ContractError(
                    "causal applicator changed source-grounded rule cardinality"
                )
            changes = canonical_field_changes(
                baseline.canonical_ir, guided_ir
            )
            if not changes:
                raise ContractError(
                    "causal guidance requires a nonempty canonical change"
                )
            changed_by_path = {change.path: change for change in changes}
            attributed_paths = {
                item.changed_field_path for item in application.attributions
            }
            if attributed_paths != set(changed_by_path):
                raise ContractError(
                    "causal receipt must attribute every and only changed field"
                )
            intervention_map = self._reviewed_contract.intervention_map()
            for attribution in application.attributions:
                intervention = intervention_map.get(attribution.feature_id)
                if (
                    intervention is None
                    or intervention.feature != attribution.feature
                ):
                    raise ContractError(
                        "causal receipt names an unreviewed stable feature"
                    )
                changed = changed_by_path[attribution.changed_field_path]
                if changed.canonical_field not in (
                    intervention.canonical_fields
                ):
                    raise ContractError(
                        "causal receipt maps a feature to an unreviewed field"
                    )
            receipt = CausalGuidanceChangeReceipt(
                contract_identity=self._reviewed_contract.identity,
                contract_digest=self._reviewed_contract.digest,
                changes=changes,
                attributions=application.attributions,
                source_sha256=hashlib.sha256(
                    request.source_text.encode("utf-8")
                ).hexdigest(),
                vocabulary_sha256=_sha(
                    request.allowed_atom_vocabulary.to_dict()
                ),
            )
        except ContractError:
            raise
        except Exception as exc:
            raise ContractError(
                "causal applicator raised "
                f"{type(exc).__name__}"
            ) from exc

        return CausalGuidancePairResult(
            no_guidance=baseline,
            guided=ConstructorResult(
                ComponentStatus.SUCCESS, canonical_ir=guided_ir
            ),
            status=CausalQualificationStatus.QUALIFIED,
            negative_control=negative_control,
            state_evidence=export_evidence,
            change_receipt=receipt,
        )

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        """Return the guided member while retaining fail-closed semantics."""

        return self.construct_pair(request).guided


def _is_guided_arm_id(arm_id: object) -> bool:
    if not isinstance(arm_id, str) or not arm_id.strip():
        return False
    text = arm_id.strip()
    return "__guided__" in text or text.startswith("guided") or (
        ".guided." in text
    )


def _arm_id_from_candidate(candidate: object) -> str:
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    if isinstance(candidate, Mapping):
        for key in (
            "arm_id",
            "cell_id",
            "id",
            "coordinate_key",
            "name",
        ):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        composition = candidate.get("composition")
        if isinstance(composition, Mapping):
            guidance = composition.get("guidance")
            if _normalized(guidance) == "guided":
                # Preserve a stable synthetic id when only composition is given.
                cell = candidate.get("cell_id")
                if isinstance(cell, str) and cell.strip():
                    return cell.strip()
                return "guided"
    raise ContractError(
        "schedule candidate must provide a nonblank arm_id or cell_id"
    )


def _candidate_is_guided(candidate: object) -> bool:
    if isinstance(candidate, str):
        return _is_guided_arm_id(candidate)
    if isinstance(candidate, Mapping):
        arm_id = None
        for key in ("arm_id", "cell_id", "id", "coordinate_key", "name"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                arm_id = value.strip()
                break
        if arm_id is not None and _is_guided_arm_id(arm_id):
            return True
        composition = candidate.get("composition")
        if isinstance(composition, Mapping):
            if _normalized(composition.get("guidance")) == "guided":
                return True
        if _normalized(candidate.get("guidance")) == "guided":
            return True
    return False


def guided_scored_support_from_qualification(
    qualification: Mapping[str, object] | None,
) -> str:
    """Return ``scored_supported`` or ``terminal_unsupported`` for guided arms.

    A missing or unavailable causal contract is always fail-closed: guided
    arms remain terminal unsupported and must not enter semantic scoring.
    """

    if not isinstance(qualification, Mapping):
        return TERMINAL_UNSUPPORTED
    guided = qualification.get("guided_coordinates")
    disposition = None
    if isinstance(guided, Mapping):
        disposition = guided.get("disposition")
    if disposition is None:
        disposition = qualification.get("disposition")
    status = qualification.get("status")
    contract = qualification.get("causal_contract")
    preregistered = (
        isinstance(contract, Mapping)
        and contract.get("preregistered") is True
    )
    if disposition == SCORED_SUPPORTED or status == SCORED_SUPPORTED:
        return SCORED_SUPPORTED
    if (
        status == CausalQualificationStatus.QUALIFIED.value
        and preregistered
    ):
        return SCORED_SUPPORTED
    return TERMINAL_UNSUPPORTED


def teacher_residual_disposition_from_qualification(
    qualification: Mapping[str, object] | None,
) -> dict[str, object]:
    """Plateau-break teacher-residual summary for guided autoencoder arms.

    PLAT-060 keeps the autoencoder off the production default path.  Guided
    cells either become ``scored_supported`` teacher residuals (reviewed causal
    L1 adapter present) or stay ``not_measured`` / ``terminal_unsupported``
    with semantic scoring disabled.
    """

    support = guided_scored_support_from_qualification(qualification)
    scored = support == SCORED_SUPPORTED
    return {
        "evaluation_status": (
            SCORED_SUPPORTED if scored else EVALUATION_STATUS_NOT_MEASURED
        ),
        "interface": TEACHER_RESIDUAL_INTERFACE,
        "production_default": False,
        "promotion_requires": TEACHER_RESIDUAL_PROMOTION_REQUIRES,
        "role": TEACHER_RESIDUAL_ROLE,
        "schedule_for_semantic_scoring": scored,
        "scored_support": support,
        "task_id": PLATEAU_BREAK_TASK_ID,
    }


def plan_guided_semantic_schedule(
    candidates: Sequence[object],
    qualification: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Matrix planner: keep unsupported guided cells off semantic scoring.

    Guided candidates without a reviewed causal L1 adapter are returned under
    ``not_measured`` only.  They are never admitted to
    ``scheduled_for_semantic_scoring``.  Non-guided candidates pass through
    unchanged.
    """

    if not isinstance(candidates, Sequence) or isinstance(
        candidates, (str, bytes, bytearray)
    ):
        raise ContractError("candidates must be a sequence of arm specs")

    support = guided_scored_support_from_qualification(qualification)
    scheduled: list[object] = []
    not_measured: list[dict[str, object]] = []
    scheduled_ids: list[str] = []
    not_measured_ids: list[str] = []

    for candidate in candidates:
        arm_id = _arm_id_from_candidate(candidate)
        guided = _candidate_is_guided(candidate)
        if guided and support != SCORED_SUPPORTED:
            not_measured_ids.append(arm_id)
            not_measured.append(
                {
                    "arm_id": arm_id,
                    "evaluation_status": EVALUATION_STATUS_NOT_MEASURED,
                    "reason": UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER,
                    "schedule_for_semantic_scoring": False,
                    "status": TERMINAL_UNSUPPORTED,
                }
            )
            continue
        scheduled_ids.append(arm_id)
        scheduled.append(candidate)

    return {
        "evaluation_status_for_excluded_guided": (
            EVALUATION_STATUS_NOT_MEASURED
        ),
        "guided_disposition": support,
        "interface": CAUSAL_MATRIX_PLANNER_INTERFACE,
        "not_measured": not_measured,
        "not_measured_arm_ids": not_measured_ids,
        "policy": MATRIX_SCHEDULE_POLICY,
        "scheduled_arm_ids": scheduled_ids,
        "scheduled_for_semantic_scoring": scheduled,
        "semantic_schedule": (
            SCORED_SUPPORTED
            if support == SCORED_SUPPORTED
            else SEMANTIC_SCHEDULE_EXCLUDED
        ),
    }


def filter_semantic_schedule_candidates(
    candidates: Sequence[object],
    qualification: Mapping[str, object] | None = None,
) -> list[object]:
    """Return only candidates admitted to the semantic scoring schedule."""

    plan = plan_guided_semantic_schedule(candidates, qualification)
    scheduled = plan["scheduled_for_semantic_scoring"]
    if not isinstance(scheduled, list):
        raise ContractError("matrix planner returned a malformed schedule")
    return list(scheduled)


def _guided_coordinate_evidence(
    repo_root: Path,
) -> tuple[str, list[dict[str, object]]]:
    manifest = _strict_json_object(
        repo_root / SRT021_MANIFEST_RELATIVE_PATH
    )
    manifest_cid = manifest.get("manifest_cid")
    try:
        validate_cid(manifest_cid, codecs=("dag-json",))
    except (TypeError, ValueError) as exc:
        raise ContractError("SRT-021 manifest CID is invalid") from exc
    payload = dict(manifest)
    del payload["manifest_cid"]
    if (
        manifest_cid != PINNED_SRT021_MANIFEST_CID
        or cid_for_dag_json(payload) != manifest_cid
    ):
        raise ContractError("SRT-021 manifest differs from its frozen CID")
    remediation = manifest.get("remediation")
    if not isinstance(remediation, Mapping):
        raise ContractError("SRT-021 remediation evidence is missing")
    arms = remediation.get("arms")
    if not isinstance(arms, Mapping):
        raise ContractError("SRT-021 arm evidence is missing")
    evidence: list[dict[str, object]] = []
    for arm_id in sorted(arms):
        if "__guided__" not in arm_id:
            continue
        summary = arms[arm_id]
        if not isinstance(summary, Mapping):
            raise ContractError(f"SRT-021 arm {arm_id!r} is malformed")
        evidence.append(
            {
                "arm_id": arm_id,
                "evaluation_status": EVALUATION_STATUS_NOT_MEASURED,
                "historical_terminal_failure_count": summary.get(
                    "terminal_failure_count"
                ),
                "reason": UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER,
                "schedule_for_semantic_scoring": False,
                "status": TERMINAL_UNSUPPORTED,
            }
        )
    if not evidence:
        raise ContractError("SRT-021 has no guided coordinate evidence")
    return str(manifest_cid), evidence


def build_causal_guidance_qualification(
    repo_root: Path = REPO_ROOT,
    *,
    guidance_loader: GuidanceLoader = load_frozen_autoencoder_guidance,
    state_path: Path | None = None,
) -> dict[str, object]:
    """Build the repository-backed unavailable qualification receipt.

    Path (b) of the measurement-path contract: no reviewed causal L1 adapter
    is present, so guided coordinates stay terminal unsupported, are excluded
    from the semantic scoring schedule, and classify only as
    ``not_measured``.
    """

    root = Path(repo_root).resolve()
    resolved_state = (
        Path(state_path)
        if state_path is not None
        else root
        / DEFAULT_AUTOENCODER_STATE_PATH.relative_to(REPO_ROOT)
    )
    guidance = guidance_loader(resolved_state)
    evidence = StableExportEvidence.from_guidance(guidance)
    srt021_cid, coordinates = _guided_coordinate_evidence(root)
    arm_ids = [str(item["arm_id"]) for item in coordinates]
    unavailable_qualification = {
        "status": UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER,
        "guided_coordinates": {"disposition": TERMINAL_UNSUPPORTED},
        "causal_contract": {"preregistered": False},
    }
    schedule_plan = plan_guided_semantic_schedule(
        arm_ids,
        unavailable_qualification,
    )
    teacher_residual = teacher_residual_disposition_from_qualification(
        unavailable_qualification
    )
    payload: dict[str, object] = {
        "board_namespace": PLATEAU_BREAK_BOARD_NAMESPACE,
        "causal_contract": {
            "advisory_diagnostics_are_causal_guidance": False,
            "missing": list(MISSING_CAUSAL_CONTRACT_FIELDS),
            "preregistered": False,
            "reviewed_adapter_id": None,
            "reviewed_interventions": [],
        },
        "evaluation_status": EVALUATION_STATUS_NOT_MEASURED,
        "evaluation_status_reason": TERMINAL_UNSUPPORTED,
        "forbidden_inputs": {
            "fabricated_l1_mutations": False,
            "gold_labels": False,
            "gold_rule_counts": False,
            "outcome_dependent_selection": False,
            "sample_memory": False,
            "target_embeddings": False,
        },
        "guided_coordinates": {
            "coordinates": coordinates,
            "count": len(coordinates),
            "disposition": TERMINAL_UNSUPPORTED,
            "evaluation_status": EVALUATION_STATUS_NOT_MEASURED,
            "schedule_for_semantic_scoring": False,
            "source_manifest_cid": srt021_cid,
        },
        "interface": CAUSAL_GUIDANCE_QUALIFICATION_INTERFACE,
        "matrix_planner": {
            "excluded_guided_arm_ids": list(
                schedule_plan["not_measured_arm_ids"]
            ),
            "include_guided_in_semantic_schedule": False,
            "interface": CAUSAL_MATRIX_PLANNER_INTERFACE,
            "policy": MATRIX_SCHEDULE_POLICY,
            "scheduled_for_semantic_scoring_arm_ids": list(
                schedule_plan["scheduled_arm_ids"]
            ),
            "semantic_schedule": SEMANTIC_SCHEDULE_EXCLUDED,
        },
        "negative_control": {
            "canonical_l1_changed": False,
            "causal_feature_ids": [],
            "changed_fields": [],
            "guidance_enabled": False,
            "proof": (
                "no_guidance returns the exact single baseline construction"
            ),
            "status": "passed_zero_change",
        },
        "paired_output_contract": {
            "guided": "explicit_terminal_unsupported",
            "identical_non_guidance_inputs": True,
            "no_guidance": "exact_baseline",
            "schema_preserved": True,
            "source_grounding_rule": SOURCE_GROUNDING_RULE,
        },
        "schema_version": CAUSAL_GUIDANCE_QUALIFICATION_SCHEMA,
        "stable_export": evidence.to_dict(),
        "state": {
            "access": "read_only",
            "cid": PINNED_AUTOENCODER_STATE_CID,
            "cid_verified": True,
            "declared_architecture": (
                PINNED_AUTOENCODER_DECLARED_ARCHITECTURE
            ),
            "effective_architecture": (
                PINNED_AUTOENCODER_EFFECTIVE_ARCHITECTURE
            ),
            "schema": PINNED_AUTOENCODER_STATE_SCHEMA,
            "sha256": PINNED_AUTOENCODER_STATE_SHA256,
        },
        "status": UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER,
        "task_id": PLATEAU_BREAK_TASK_ID,
        "teacher_residual": teacher_residual,
    }
    payload["qualification_cid"] = cid_for_dag_json(payload)
    return payload


def validate_causal_guidance_qualification(
    value: Mapping[str, object],
    *,
    repo_root: Path = REPO_ROOT,
    guidance_loader: GuidanceLoader = load_frozen_autoencoder_guidance,
    state_path: Path | None = None,
) -> dict[str, object]:
    """Validate a qualification against fresh CID-bound repository evidence."""

    if not isinstance(value, Mapping):
        raise ContractError("causal guidance qualification must be an object")
    supplied = copy.deepcopy(dict(value))
    cid = supplied.get("qualification_cid")
    try:
        validate_cid(cid, codecs=("dag-json",))
    except (TypeError, ValueError) as exc:
        raise ContractError("qualification CID is invalid") from exc
    cid_payload = dict(supplied)
    del cid_payload["qualification_cid"]
    if cid_for_dag_json(cid_payload) != cid:
        raise ContractError(
            "qualification CID does not match its canonical payload"
        )
    expected = build_causal_guidance_qualification(
        repo_root,
        guidance_loader=guidance_loader,
        state_path=state_path,
    )
    if supplied != expected:
        raise ContractError(
            "qualification contradicts frozen causal-guidance evidence"
        )
    return expected


def load_causal_guidance_qualification(
    path: Path = DEFAULT_QUALIFICATION_PATH,
    *,
    repo_root: Path = REPO_ROOT,
    guidance_loader: GuidanceLoader = load_frozen_autoencoder_guidance,
    state_path: Path | None = None,
) -> dict[str, object]:
    """Load and validate the checked-in qualification receipt."""

    value = _strict_json_object(Path(path))
    return validate_causal_guidance_qualification(
        value,
        repo_root=repo_root,
        guidance_loader=guidance_loader,
        state_path=state_path,
    )


assert isinstance(CausalAutoencoderGuidance(), RoundTripConstructor)


__all__ = [
    "CAUSAL_AUTOENCODER_GUIDANCE_INTERFACE",
    "CAUSAL_CHANGE_RECEIPT_INTERFACE",
    "CAUSAL_GUIDANCE_QUALIFICATION_INTERFACE",
    "CAUSAL_GUIDANCE_QUALIFICATION_SCHEMA",
    "CAUSAL_MATRIX_PLANNER_INTERFACE",
    "CAUSAL_SELECTION_RULE",
    "DEFAULT_QUALIFICATION_PATH",
    "DEFAULT_QUALIFICATION_RELATIVE_PATH",
    "EVALUATION_STATUS_NOT_MEASURED",
    "FORBIDDEN_CAUSAL_INPUTS",
    "MATRIX_SCHEDULE_POLICY",
    "MISSING_CAUSAL_CONTRACT_FIELDS",
    "PINNED_SRT021_MANIFEST_CID",
    "PLATEAU_BREAK_BOARD_NAMESPACE",
    "PLATEAU_BREAK_TASK_ID",
    "REVIEWED_CAUSAL_L1_CONTRACT_INTERFACE",
    "SCORED_SUPPORTED",
    "SEMANTIC_SCHEDULE_EXCLUDED",
    "SOURCE_GROUNDING_RULE",
    "STABLE_EXPORT_SCHEMA",
    "TEACHER_RESIDUAL_INTERFACE",
    "TEACHER_RESIDUAL_PROMOTION_REQUIRES",
    "TEACHER_RESIDUAL_ROLE",
    "TERMINAL_UNSUPPORTED",
    "UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER",
    "CausalAdapterOutput",
    "CausalAutoencoderGuidance",
    "CausalFeatureAttribution",
    "CausalGuidanceChangeReceipt",
    "CausalGuidancePairResult",
    "CausalQualificationStatus",
    "FeatureToCanonicalFieldIntervention",
    "NegativeControlReceipt",
    "ReviewedCausalL1Applicator",
    "ReviewedCausalL1Contract",
    "StableExportEvidence",
    "build_causal_guidance_qualification",
    "filter_semantic_schedule_candidates",
    "guided_scored_support_from_qualification",
    "load_causal_guidance_qualification",
    "plan_guided_semantic_schedule",
    "teacher_residual_disposition_from_qualification",
    "validate_causal_guidance_qualification",
]
