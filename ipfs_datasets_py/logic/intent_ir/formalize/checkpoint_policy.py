"""Current-version checkpoint policy for Intent formalization advisor heads.

The generic checkpoint contract records immutable identities.  This module
adds the Intent-specific selection policy: only registered Intent heads may be
used, each head is restricted to exact formalization view IDs, and manifests
must bind the current Intent schema, corpus ontology, compiler, feature
extractor, and policy versions.

No weights are loaded here.  A valid manifest only authorizes an untrusted
model backend to propose bounded, unverified candidates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from ...formalization.advisor import AdviceKind, AdvisorValidationError
from ...formalization.checkpoints import (
    CheckpointManifest,
    validate_checkpoint_manifest,
)
from ...formalization.features import FORMALIZATION_FEATURES_SCHEMA_VERSION
from ...ir_core.identity import canonical_identity
from ..graphrag.ontology import CORPUS_ONTOLOGY, CORPUS_ONTOLOGY_VERSION
from ..schema import (
    ControlEdgeKind,
    INTENT_IR_SCHEMA_VERSION,
    IntentKind,
    IntentModality,
    NodeGrounding,
    ReviewStatus,
    StatementKind,
)
from .compiler import (
    INTENT_ACTION_VIEW_ID,
    INTENT_FACT_VIEW_ID,
    INTENT_FAILURE_VIEW_ID,
    INTENT_FORMALIZATION_COMPILER_VERSION,
    INTENT_FORMALIZATION_VIEW_REGISTRY,
    INTENT_INVARIANT_VIEW_ID,
    INTENT_MODAL_VIEW_ID,
    INTENT_VERIFICATION_VIEW_ID,
    INTENT_WORKFLOW_VIEW_ID,
)
from .features import (
    INTENT_FEATURE_EXTRACTOR_ID,
    INTENT_FEATURE_EXTRACTOR_VERSION,
)


INTENT_ADVISOR_CHECKPOINT_POLICY_VERSION: Final = (
    "intent-advisor-checkpoint-policy/v1"
)
INTENT_ADVISOR_HEAD_SCHEMA_VERSION: Final = "intent-advisor-head/v1"
INTENT_FORMALIZATION_ONTOLOGY_VERSION: Final = (
    "intent-formalization-ontology/v1"
)

INTENT_FACT_HEAD_ID: Final = "intent:head:facts"
INTENT_MODAL_HEAD_ID: Final = "intent:head:intention-deontic"
INTENT_ACTION_HEAD_ID: Final = "intent:head:action-hoare"
INTENT_WORKFLOW_HEAD_ID: Final = "intent:head:workflow-temporal"
INTENT_INVARIANT_HEAD_ID: Final = "intent:head:invariant"
INTENT_FAILURE_HEAD_ID: Final = "intent:head:failure"
INTENT_VERIFICATION_HEAD_ID: Final = "intent:head:verification"
INTENT_MULTIVIEW_HEAD_ID: Final = "intent:head:multiview"


def _intent_ontology_payload() -> dict[str, Any]:
    """Return the closed, versioned vocabulary consumed by Intent heads."""

    return {
        "control_edge_kinds": [item.value for item in ControlEdgeKind],
        "corpus_ontology": CORPUS_ONTOLOGY.to_dict(),
        "corpus_ontology_version": CORPUS_ONTOLOGY_VERSION,
        "grounding_kinds": [item.value for item in NodeGrounding],
        "intent_ir_schema_version": INTENT_IR_SCHEMA_VERSION,
        "intent_kinds": [item.value for item in IntentKind],
        "modalities": [item.value for item in IntentModality],
        "review_statuses": [item.value for item in ReviewStatus],
        "statement_kinds": [item.value for item in StatementKind],
        "version": INTENT_FORMALIZATION_ONTOLOGY_VERSION,
    }


INTENT_FORMALIZATION_ONTOLOGY_IDENTITY: Final = canonical_identity(
    _intent_ontology_payload(),
    domain="intent-formalization-ontology",
    schema_version=INTENT_FORMALIZATION_ONTOLOGY_VERSION,
).digest
INTENT_ADVISOR_ONTOLOGY_IDENTITY: Final = (
    INTENT_FORMALIZATION_ONTOLOGY_IDENTITY
)
INTENT_VIEW_REGISTRY_IDENTITY: Final = (
    INTENT_FORMALIZATION_VIEW_REGISTRY.identity.digest
)


@dataclass(frozen=True, slots=True)
class IntentAdvisorHead:
    """One namespaced Intent output head and its exact view coverage."""

    head_id: str
    view_ids: tuple[str, ...]
    advice_kinds: tuple[AdviceKind, ...] = (
        AdviceKind.FORMULA_CANDIDATE,
        AdviceKind.REPAIR,
    )
    schema_version: str = INTENT_ADVISOR_HEAD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.head_id, str) or not self.head_id.startswith(
            "intent:head:"
        ):
            raise AdvisorValidationError(
                "Intent advisor head IDs must be namespaced under 'intent:head:'"
            )
        views = tuple(sorted(self.view_ids))
        if not views or len(views) != len(set(views)):
            raise AdvisorValidationError(
                "Intent advisor heads require unique view IDs"
            )
        unknown = set(views) - set(INTENT_FORMALIZATION_VIEW_REGISTRY.view_ids)
        if unknown:
            raise AdvisorValidationError(
                "Intent advisor head references unsupported view IDs: "
                + ", ".join(sorted(unknown))
            )
        kinds: list[AdviceKind] = []
        for value in self.advice_kinds:
            try:
                kinds.append(
                    value if isinstance(value, AdviceKind) else AdviceKind(value)
                )
            except (TypeError, ValueError) as exc:
                raise AdvisorValidationError(
                    f"unsupported Intent advice kind: {value!r}"
                ) from exc
        if not kinds or len(kinds) != len(set(kinds)):
            raise AdvisorValidationError(
                "Intent advisor heads require unique advice kinds"
            )
        if self.schema_version != INTENT_ADVISOR_HEAD_SCHEMA_VERSION:
            raise AdvisorValidationError(
                f"unsupported Intent advisor head schema: {self.schema_version!r}"
            )
        object.__setattr__(self, "view_ids", views)
        object.__setattr__(
            self, "advice_kinds", tuple(sorted(kinds, key=lambda item: item.value))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "advice_kinds": [item.value for item in self.advice_kinds],
            "head_id": self.head_id,
            "schema_version": self.schema_version,
            "view_ids": list(self.view_ids),
        }


_HEADS = (
    IntentAdvisorHead(INTENT_FACT_HEAD_ID, (INTENT_FACT_VIEW_ID,)),
    IntentAdvisorHead(INTENT_MODAL_HEAD_ID, (INTENT_MODAL_VIEW_ID,)),
    IntentAdvisorHead(INTENT_ACTION_HEAD_ID, (INTENT_ACTION_VIEW_ID,)),
    IntentAdvisorHead(INTENT_WORKFLOW_HEAD_ID, (INTENT_WORKFLOW_VIEW_ID,)),
    IntentAdvisorHead(INTENT_INVARIANT_HEAD_ID, (INTENT_INVARIANT_VIEW_ID,)),
    IntentAdvisorHead(INTENT_FAILURE_HEAD_ID, (INTENT_FAILURE_VIEW_ID,)),
    IntentAdvisorHead(
        INTENT_VERIFICATION_HEAD_ID, (INTENT_VERIFICATION_VIEW_ID,)
    ),
    IntentAdvisorHead(
        INTENT_MULTIVIEW_HEAD_ID,
        INTENT_FORMALIZATION_VIEW_REGISTRY.view_ids,
    ),
)
INTENT_ADVISOR_HEADS: Final[Mapping[str, IntentAdvisorHead]] = (
    MappingProxyType({item.head_id: item for item in _HEADS})
)
INTENT_HEAD_ID_BY_VIEW: Final[Mapping[str, str]] = MappingProxyType(
    {
        INTENT_FACT_VIEW_ID: INTENT_FACT_HEAD_ID,
        INTENT_MODAL_VIEW_ID: INTENT_MODAL_HEAD_ID,
        INTENT_ACTION_VIEW_ID: INTENT_ACTION_HEAD_ID,
        INTENT_WORKFLOW_VIEW_ID: INTENT_WORKFLOW_HEAD_ID,
        INTENT_INVARIANT_VIEW_ID: INTENT_INVARIANT_HEAD_ID,
        INTENT_FAILURE_VIEW_ID: INTENT_FAILURE_HEAD_ID,
        INTENT_VERIFICATION_VIEW_ID: INTENT_VERIFICATION_HEAD_ID,
    }
)


def _view_ids(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise AdvisorValidationError(f"{field_name} must be a sequence")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise AdvisorValidationError(
            f"{field_name} must contain non-empty strings"
        )
    if len(result) != len(set(result)):
        raise AdvisorValidationError(f"{field_name} must be unique")
    return tuple(sorted(result))


@dataclass(frozen=True, slots=True)
class IntentCheckpointPolicy:
    """Fail-closed selector for current Intent advisor checkpoints."""

    policy_version: str = INTENT_ADVISOR_CHECKPOINT_POLICY_VERSION
    ontology_identity: str = INTENT_FORMALIZATION_ONTOLOGY_IDENTITY
    view_registry_identity: str = INTENT_VIEW_REGISTRY_IDENTITY
    feature_schema_version: str = FORMALIZATION_FEATURES_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.policy_version != INTENT_ADVISOR_CHECKPOINT_POLICY_VERSION:
            raise AdvisorValidationError(
                f"stale Intent checkpoint policy: {self.policy_version!r}"
            )
        expected = (
            INTENT_FORMALIZATION_ONTOLOGY_IDENTITY,
            INTENT_VIEW_REGISTRY_IDENTITY,
            FORMALIZATION_FEATURES_SCHEMA_VERSION,
        )
        actual = (
            self.ontology_identity,
            self.view_registry_identity,
            self.feature_schema_version,
        )
        if actual != expected:
            raise AdvisorValidationError(
                "Intent checkpoint policy dependencies are stale"
            )

    def resolve_head(self, head_id: str) -> IntentAdvisorHead:
        try:
            return INTENT_ADVISOR_HEADS[head_id]
        except KeyError:
            raise AdvisorValidationError(
                f"unsupported Intent advisor head: {head_id!r}"
            ) from None

    def validate(
        self,
        checkpoint: CheckpointManifest | Mapping[str, Any],
        *,
        requested_view_ids: Sequence[str] = (),
        advice_kind: AdviceKind | str | None = None,
    ) -> CheckpointManifest:
        """Validate all manifest dependencies and the selected head scope."""

        manifest = validate_checkpoint_manifest(checkpoint)
        try:
            manifest.require_compatible(
                domain="intent",
                ontology_identity=self.ontology_identity,
                view_registry_identity=self.view_registry_identity,
                feature_schema_version=self.feature_schema_version,
            )
        except ValueError as exc:
            raise AdvisorValidationError(str(exc)) from exc

        head = self.resolve_head(manifest.head_id)
        requested = _view_ids(requested_view_ids, "requested_view_ids")
        unsupported = set(requested) - set(
            INTENT_FORMALIZATION_VIEW_REGISTRY.view_ids
        )
        if unsupported:
            raise AdvisorValidationError(
                "unsupported Intent advisor view IDs: "
                + ", ".join(sorted(unsupported))
            )
        outside_head = set(requested) - set(head.view_ids)
        if outside_head:
            raise AdvisorValidationError(
                f"checkpoint head {head.head_id!r} does not cover view IDs: "
                + ", ".join(sorted(outside_head))
            )

        if advice_kind is not None:
            try:
                kind = (
                    advice_kind
                    if isinstance(advice_kind, AdviceKind)
                    else AdviceKind(advice_kind)
                )
            except (TypeError, ValueError) as exc:
                raise AdvisorValidationError(
                    f"unsupported Intent advice kind: {advice_kind!r}"
                ) from exc
            if kind not in head.advice_kinds:
                raise AdvisorValidationError(
                    f"checkpoint head {head.head_id!r} does not support "
                    f"{kind.value!r}"
                )

        metadata = manifest.metadata.to_dict()
        required = {
            "authority": "unverified_candidate_only",
            "compiler_version": INTENT_FORMALIZATION_COMPILER_VERSION,
            "corpus_ontology_version": CORPUS_ONTOLOGY_VERSION,
            "feature_extractor_id": INTENT_FEATURE_EXTRACTOR_ID,
            "feature_extractor_version": INTENT_FEATURE_EXTRACTOR_VERSION,
            "intent_ir_schema_version": INTENT_IR_SCHEMA_VERSION,
            "ontology_version": INTENT_FORMALIZATION_ONTOLOGY_VERSION,
            "policy_version": self.policy_version,
        }
        stale = [
            name
            for name, expected in required.items()
            if metadata.get(name) != expected
        ]
        if stale:
            raise AdvisorValidationError(
                "Intent checkpoint metadata is stale or incomplete: "
                + ", ".join(sorted(stale))
            )
        declared_views = _view_ids(
            metadata.get("target_view_ids"),
            "checkpoint target_view_ids",
        )
        if declared_views != head.view_ids:
            raise AdvisorValidationError(
                "Intent checkpoint target_view_ids do not match its head"
            )
        return manifest

    # Descriptive spelling used by callers that treat policies as selectors.
    require_current = validate


INTENT_CHECKPOINT_POLICY: Final = IntentCheckpointPolicy()


def create_intent_checkpoint_manifest(
    *,
    checkpoint_id: str,
    head_id: str,
    model_id: str,
    model_version: str,
    weights_digest: str,
    training_config_identity: str,
    metadata: Mapping[str, Any] | None = None,
) -> CheckpointManifest:
    """Construct a manifest with every current Intent policy binding."""

    head = INTENT_CHECKPOINT_POLICY.resolve_head(head_id)
    supplied = dict(metadata or {})
    protected = {
        "authority": "unverified_candidate_only",
        "compiler_version": INTENT_FORMALIZATION_COMPILER_VERSION,
        "corpus_ontology_version": CORPUS_ONTOLOGY_VERSION,
        "feature_extractor_id": INTENT_FEATURE_EXTRACTOR_ID,
        "feature_extractor_version": INTENT_FEATURE_EXTRACTOR_VERSION,
        "intent_ir_schema_version": INTENT_IR_SCHEMA_VERSION,
        "ontology_version": INTENT_FORMALIZATION_ONTOLOGY_VERSION,
        "policy_version": INTENT_ADVISOR_CHECKPOINT_POLICY_VERSION,
        "target_view_ids": list(head.view_ids),
    }
    conflicts = [
        name
        for name, value in protected.items()
        if name in supplied and supplied[name] != value
    ]
    if conflicts:
        raise AdvisorValidationError(
            "checkpoint metadata cannot override policy fields: "
            + ", ".join(sorted(conflicts))
        )
    supplied.update(protected)
    manifest = CheckpointManifest(
        checkpoint_id=checkpoint_id,
        domain="intent",
        head_id=head.head_id,
        model_id=model_id,
        model_version=model_version,
        weights_digest=weights_digest,
        training_config_identity=training_config_identity,
        ontology_identity=INTENT_FORMALIZATION_ONTOLOGY_IDENTITY,
        view_registry_identity=INTENT_VIEW_REGISTRY_IDENTITY,
        feature_schema_version=FORMALIZATION_FEATURES_SCHEMA_VERSION,
        metadata=supplied,
    )
    return INTENT_CHECKPOINT_POLICY.validate(manifest)


build_intent_checkpoint_manifest = create_intent_checkpoint_manifest
validate_intent_checkpoint = INTENT_CHECKPOINT_POLICY.validate
IntentAdvisorCheckpointPolicy = IntentCheckpointPolicy


__all__ = [
    "INTENT_ACTION_HEAD_ID",
    "INTENT_ADVISOR_CHECKPOINT_POLICY_VERSION",
    "INTENT_ADVISOR_HEADS",
    "INTENT_ADVISOR_HEAD_SCHEMA_VERSION",
    "INTENT_ADVISOR_ONTOLOGY_IDENTITY",
    "INTENT_CHECKPOINT_POLICY",
    "INTENT_FACT_HEAD_ID",
    "INTENT_FAILURE_HEAD_ID",
    "INTENT_FORMALIZATION_ONTOLOGY_IDENTITY",
    "INTENT_FORMALIZATION_ONTOLOGY_VERSION",
    "INTENT_HEAD_ID_BY_VIEW",
    "INTENT_INVARIANT_HEAD_ID",
    "INTENT_MODAL_HEAD_ID",
    "INTENT_MULTIVIEW_HEAD_ID",
    "INTENT_VERIFICATION_HEAD_ID",
    "INTENT_VIEW_REGISTRY_IDENTITY",
    "INTENT_WORKFLOW_HEAD_ID",
    "IntentAdvisorHead",
    "IntentAdvisorCheckpointPolicy",
    "IntentCheckpointPolicy",
    "build_intent_checkpoint_manifest",
    "create_intent_checkpoint_manifest",
    "validate_intent_checkpoint",
]
