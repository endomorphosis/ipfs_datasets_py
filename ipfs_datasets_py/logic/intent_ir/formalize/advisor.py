"""Intent-specific bounded advisor over deterministic formalization.

The deterministic compiler is always the baseline.  An optional learned
backend receives source-free features and scoped formula expressions through
the generic advisor contract.  Its output is reconstructed from the baseline,
checked against the current Intent checkpoint/head policy, validated against
the exact Intent view expression types, and returned only as an unverified
candidate comparison.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from ...formalization.advisor import (
    AdviceKind,
    AdvisorConfig,
    AdvisorModel,
    AdvisorResult,
    AdvisorValidationError,
    BoundedFormalizationAdvisor,
    FormalizationAdvisorRequest,
    RepairScope,
)
from ...formalization.checkpoints import CheckpointManifest
from ...formalization.compiler import (
    FormalizationArtifact,
    FormalizationCompilerConfig,
)
from ...formalization.features import FormalizationFeatures
from ...formalization.views import FormalFormula
from ...ir_core.claims import thaw_json
from ..schema import (
    ControlEdgeKind,
    IntentAction,
    IntentControlEdge,
    IntentIRDocument,
    IntentModality,
    IntentStatement,
    NodeGrounding,
    ReviewStatus,
    StatementKind,
)
from .checkpoint_policy import (
    INTENT_CHECKPOINT_POLICY,
    INTENT_FORMALIZATION_ONTOLOGY_IDENTITY,
    IntentCheckpointPolicy,
)
from .compiler import (
    INTENT_ACTION_VIEW_ID,
    INTENT_FACT_VIEW_ID,
    INTENT_FAILURE_VIEW_ID,
    INTENT_FORMALIZATION_COMPILER_VERSION,
    INTENT_FORMALIZATION_PRODUCER_ID,
    INTENT_FORMALIZATION_VIEW_REGISTRY,
    INTENT_INVARIANT_VIEW_ID,
    INTENT_MODAL_VIEW_ID,
    INTENT_VERIFICATION_VIEW_ID,
    INTENT_WORKFLOW_VIEW_ID,
    IntentFormalizationCompiler,
)
from .features import extract_intent_features


INTENT_FORMALIZATION_ADVISOR_VERSION: Final = (
    "intent-formalization-advisor/v1"
)
INTENT_FORMALIZATION_ADVISOR_ID: Final = "intent:formalization-advisor"
INTENT_FORMALIZATION_ADVISOR_CONFIG_ID: Final = (
    "intent:formalization-advisor:bounded-default"
)

_MODAL_OPERATORS: Final = frozenset(item.value for item in IntentModality)
_EDGE_OPERATORS: Final = frozenset(item.value for item in ControlEdgeKind)
_GROUNDING_VALUES: Final = frozenset(item.value for item in NodeGrounding)
_REVIEW_VALUES: Final = frozenset(item.value for item in ReviewStatus)
_STATEMENT_KINDS: Final = frozenset(item.value for item in StatementKind)

_VIEW_KINDS: Final[dict[str, frozenset[str]]] = {
    INTENT_FACT_VIEW_ID: frozenset({"typed_fact", "typed_action_fact"}),
    INTENT_MODAL_VIEW_ID: frozenset({"intention_deontic_formula"}),
    INTENT_ACTION_VIEW_ID: frozenset({"hoare_action_contract"}),
    INTENT_WORKFLOW_VIEW_ID: frozenset(
        {"workflow_boundary", "workflow_temporal_transition"}
    ),
    INTENT_INVARIANT_VIEW_ID: frozenset({"safety_invariant"}),
    INTENT_FAILURE_VIEW_ID: frozenset({"failure_condition"}),
    INTENT_VERIFICATION_VIEW_ID: frozenset({"verification_condition"}),
}


class IntentAdvisorPath(str, Enum):
    """Whether a run stopped at deterministic output or added candidates."""

    DETERMINISTIC_ONLY = "deterministic_only"
    NO_ADVISOR = "deterministic_only"
    CANDIDATE = "candidate"
    CANDIDATE_ONLY = "candidate"


class IntentAdvisorValidationError(AdvisorValidationError):
    """Raised when an Intent advisor input or candidate fails closed."""


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntentAdvisorValidationError(f"{field_name} must be a mapping")
    return value


def _string(value: Any, field_name: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        qualifier = "non-empty " if nonempty else ""
        raise IntentAdvisorValidationError(
            f"{field_name} must be a {qualifier}string"
        )
    return value


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IntentAdvisorValidationError(f"{field_name} must be numeric")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise IntentAdvisorValidationError(
            f"{field_name} must be between zero and one"
        )
    return result


def _sequence(value: Any, field_name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise IntentAdvisorValidationError(f"{field_name} must be a sequence")
    return value


def _strings(value: Any, field_name: str) -> tuple[str, ...]:
    values = _sequence(value, field_name)
    result = tuple(
        _string(item, field_name, nonempty=True) for item in values
    )
    return result


def _exact_keys(
    value: Mapping[str, Any],
    required: frozenset[str],
    field_name: str,
) -> None:
    missing = required - set(value)
    unknown = set(value) - required
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unknown " + ", ".join(sorted(unknown)))
        raise IntentAdvisorValidationError(
            f"{field_name} has invalid formula fields: {'; '.join(details)}"
        )


_STATEMENT_BODY_FIELDS: Final = frozenset(
    {
        "arguments",
        "confidence",
        "grounding",
        "modality",
        "predicate",
        "review_status",
        "statement_kind",
        "text",
    }
)
_STATEMENT_RECORD_FIELDS: Final = frozenset(
    IntentStatement.__dataclass_fields__
)
_ACTION_FIELDS: Final = frozenset(IntentAction.__dataclass_fields__)
_EDGE_FIELDS: Final = frozenset(IntentControlEdge.__dataclass_fields__)


def _validate_statement_body(value: Any, field_name: str) -> None:
    body = _mapping(value, field_name)
    _exact_keys(body, _STATEMENT_BODY_FIELDS, field_name)
    _strings(body["arguments"], f"{field_name}.arguments")
    _number(body["confidence"], f"{field_name}.confidence")
    if _string(body["grounding"], f"{field_name}.grounding") not in _GROUNDING_VALUES:
        raise IntentAdvisorValidationError(
            f"{field_name}.grounding is not an Intent grounding value"
        )
    if _string(body["modality"], f"{field_name}.modality") not in _MODAL_OPERATORS:
        raise IntentAdvisorValidationError(
            f"{field_name}.modality is not an Intent modality"
        )
    _string(body["predicate"], f"{field_name}.predicate")
    if (
        _string(body["review_status"], f"{field_name}.review_status")
        not in _REVIEW_VALUES
    ):
        raise IntentAdvisorValidationError(
            f"{field_name}.review_status is not an Intent review status"
        )
    if (
        _string(body["statement_kind"], f"{field_name}.statement_kind")
        not in _STATEMENT_KINDS
    ):
        raise IntentAdvisorValidationError(
            f"{field_name}.statement_kind is not an Intent statement kind"
        )
    _string(body["text"], f"{field_name}.text", nonempty=True)


def _validate_action(value: Any, field_name: str) -> None:
    action = _mapping(value, field_name)
    _exact_keys(action, _ACTION_FIELDS, field_name)
    _string(action["action_id"], f"{field_name}.action_id", nonempty=True)
    _string(action["actor"], f"{field_name}.actor", nonempty=True)
    _string(action["verb"], f"{field_name}.verb", nonempty=True)
    for name in (
        "effect_ids",
        "input_refs",
        "object_refs",
        "output_refs",
        "precondition_ids",
        "source_ref_ids",
        "tool_refs",
        "verification_ids",
    ):
        _strings(action[name], f"{field_name}.{name}")
    if _string(action["grounding"], f"{field_name}.grounding") not in _GROUNDING_VALUES:
        raise IntentAdvisorValidationError(
            f"{field_name}.grounding is not an Intent grounding value"
        )


def _validate_statement_record(value: Any, field_name: str) -> None:
    """Validate a full Intent statement embedded in an action/transition."""

    statement = _mapping(value, field_name)
    _exact_keys(statement, _STATEMENT_RECORD_FIELDS, field_name)
    _strings(statement["arguments"], f"{field_name}.arguments")
    _strings(statement["source_ref_ids"], f"{field_name}.source_ref_ids")
    try:
        IntentStatement(
            statement_id=statement["statement_id"],
            kind=StatementKind(statement["kind"]),
            modality=IntentModality(statement["modality"]),
            normalized_text=statement["normalized_text"],
            predicate=statement["predicate"],
            arguments=tuple(statement["arguments"]),
            source_ref_ids=tuple(statement["source_ref_ids"]),
            confidence=statement["confidence"],
            review_status=ReviewStatus(statement["review_status"]),
            grounding=NodeGrounding(statement["grounding"]),
        ).validate()
    except (KeyError, TypeError, ValueError) as exc:
        raise IntentAdvisorValidationError(
            f"{field_name} is not a valid embedded Intent statement"
        ) from exc


def _validate_edge(value: Any, field_name: str) -> None:
    edge = _mapping(value, field_name)
    _exact_keys(edge, _EDGE_FIELDS, field_name)
    try:
        IntentControlEdge(
            edge_id=edge["edge_id"],
            source_action_id=edge["source_action_id"],
            target_action_id=edge["target_action_id"],
            kind=ControlEdgeKind(edge["kind"]),
            guard_statement_id=edge["guard_statement_id"],
            source_ref_ids=tuple(edge["source_ref_ids"]),
            grounding=NodeGrounding(edge["grounding"]),
        ).validate()
    except (KeyError, TypeError, ValueError) as exc:
        raise IntentAdvisorValidationError(
            f"{field_name} is not a valid embedded Intent control edge"
        ) from exc


def _validate_formula_expression(formula: FormalFormula) -> None:
    if formula.view_id not in _VIEW_KINDS:
        raise IntentAdvisorValidationError(
            f"unsupported Intent advisor view ID: {formula.view_id!r}"
        )
    expression = _mapping(
        thaw_json(formula.expression),
        f"formula {formula.formula_id!r} expression",
    )
    kind = _string(
        expression.get("kind"),
        f"formula {formula.formula_id!r}.kind",
        nonempty=True,
    )
    if kind not in _VIEW_KINDS[formula.view_id]:
        raise IntentAdvisorValidationError(
            f"formula {formula.formula_id!r} has invalid type {kind!r} "
            f"for view {formula.view_id!r}"
        )

    if kind == "typed_fact":
        _exact_keys(
            expression,
            _STATEMENT_BODY_FIELDS | {"kind"},
            f"formula {formula.formula_id!r}",
        )
        _validate_statement_body(
            {key: expression[key] for key in _STATEMENT_BODY_FIELDS},
            f"formula {formula.formula_id!r}",
        )
    elif kind == "typed_action_fact":
        _exact_keys(
            expression,
            frozenset({"action", "kind"}),
            f"formula {formula.formula_id!r}",
        )
        _validate_action(
            expression["action"], f"formula {formula.formula_id!r}.action"
        )
    elif kind in {
        "intention_deontic_formula",
        "safety_invariant",
        "failure_condition",
        "verification_condition",
    }:
        _exact_keys(
            expression,
            frozenset({"body", "kind", "operator"}),
            f"formula {formula.formula_id!r}",
        )
        _validate_statement_body(
            expression["body"], f"formula {formula.formula_id!r}.body"
        )
        operator = _string(
            expression["operator"],
            f"formula {formula.formula_id!r}.operator",
        )
        expected = {
            "safety_invariant": "always",
            "failure_condition": "avoid",
            "verification_condition": "observe",
        }.get(kind)
        if (expected is not None and operator != expected) or (
            expected is None and operator not in _MODAL_OPERATORS
        ):
            raise IntentAdvisorValidationError(
                f"formula {formula.formula_id!r} has invalid operator"
            )
    elif kind == "hoare_action_contract":
        _exact_keys(
            expression,
            frozenset(
                {
                    "action",
                    "effects",
                    "kind",
                    "postcondition",
                    "precondition",
                    "verification",
                }
            ),
            f"formula {formula.formula_id!r}",
        )
        _validate_action(
            expression["action"], f"formula {formula.formula_id!r}.action"
        )
        for name in (
            "effects",
            "postcondition",
            "precondition",
            "verification",
        ):
            for index, item in enumerate(
                _sequence(
                    expression[name],
                    f"formula {formula.formula_id!r}.{name}",
                )
            ):
                _validate_statement_record(
                    item, f"formula {formula.formula_id!r}.{name}[{index}]"
                )
    elif kind == "workflow_boundary":
        _exact_keys(
            expression,
            frozenset(
                {"entry_action_ids", "kind", "terminal_action_ids"}
            ),
            f"formula {formula.formula_id!r}",
        )
        _strings(
            expression["entry_action_ids"],
            f"formula {formula.formula_id!r}.entry_action_ids",
        )
        _strings(
            expression["terminal_action_ids"],
            f"formula {formula.formula_id!r}.terminal_action_ids",
        )
    elif kind == "workflow_temporal_transition":
        _exact_keys(
            expression,
            frozenset({"edge", "guard", "kind", "operator"}),
            f"formula {formula.formula_id!r}",
        )
        _validate_edge(
            expression["edge"], f"formula {formula.formula_id!r}.edge"
        )
        if expression["guard"] is not None:
            _validate_statement_record(
                expression["guard"], f"formula {formula.formula_id!r}.guard"
            )
        if (
            _string(
                expression["operator"],
                f"formula {formula.formula_id!r}.operator",
            )
            not in _EDGE_OPERATORS
        ):
            raise IntentAdvisorValidationError(
                f"formula {formula.formula_id!r} has invalid workflow operator"
            )


def validate_intent_advisor_artifact(
    artifact: FormalizationArtifact,
) -> FormalizationArtifact:
    """Require a current deterministic Intent artifact with typed views."""

    if not isinstance(artifact, FormalizationArtifact):
        raise IntentAdvisorValidationError(
            "Intent advisor input must be a FormalizationArtifact"
        )
    artifact.validate()
    if artifact.domain != "intent":
        raise IntentAdvisorValidationError(
            "Intent advisor requires an Intent formalization artifact"
        )
    if (
        artifact.compiler_config.compiler_id
        != INTENT_FORMALIZATION_PRODUCER_ID
        or artifact.compiler_config.compiler_version
        != INTENT_FORMALIZATION_COMPILER_VERSION
    ):
        raise IntentAdvisorValidationError(
            "Intent advisor requires a current deterministic Intent compiler "
            "artifact"
        )
    if (
        artifact.view_registry.identity.digest
        != INTENT_FORMALIZATION_VIEW_REGISTRY.identity.digest
    ):
        raise IntentAdvisorValidationError(
            "Intent advisor artifact uses a stale or unsupported view registry"
        )
    unsupported = set(artifact.compiler_config.target_view_ids) - set(
        INTENT_FORMALIZATION_VIEW_REGISTRY.view_ids
    )
    if unsupported:
        raise IntentAdvisorValidationError(
            "Intent advisor artifact targets unsupported view IDs: "
            + ", ".join(sorted(unsupported))
        )
    for formula in artifact.formulas:
        _validate_formula_expression(formula)
    return artifact


def build_intent_advisor_features(
    document: IntentIRDocument,
    artifact: FormalizationArtifact,
    *,
    context_snapshot_ids: Sequence[str] = (),
) -> FormalizationFeatures:
    """Bind structural Intent features to the compiler's sample identity."""

    artifact = validate_intent_advisor_artifact(artifact)
    extracted = extract_intent_features(
        document, context_snapshot_ids=context_snapshot_ids
    )
    if extracted.declaration_digest != artifact.declaration_digest:
        raise IntentAdvisorValidationError(
            "Intent document does not identify the deterministic artifact"
        )
    return FormalizationFeatures(
        sample_id=artifact.sample_id,
        domain=artifact.domain,
        declaration_digest=artifact.declaration_digest,
        feature_names=extracted.feature_names,
        feature_values=extracted.feature_values,
        extractor_id=extracted.extractor_id,
        extractor_version=extracted.extractor_version,
        context_snapshot_ids=extracted.context_snapshot_ids,
        schema_version=extracted.schema_version,
    )


_SAFE_REPAIR_PATHS: Final = (
    "/action/actor",
    "/action/verb",
    "/arguments",
    "/body/arguments",
    "/body/predicate",
    "/body/text",
    "/guard/arguments",
    "/guard/normalized_text",
    "/guard/predicate",
    "/predicate",
    "/text",
)


def _path_exists(expression: Any, path: str) -> bool:
    current = expression
    for token in path[1:].split("/"):
        if not isinstance(current, Mapping) or token not in current:
            return False
        current = current[token]
    return True


def default_intent_repair_scope(
    artifact: FormalizationArtifact,
    *,
    view_ids: Sequence[str] = (),
    max_operations: int = 4,
) -> RepairScope:
    """Build a conservative scope over editable Intent expression leaves."""

    artifact = validate_intent_advisor_artifact(artifact)
    if isinstance(view_ids, (str, bytes, bytearray)):
        raise IntentAdvisorValidationError("view_ids must be a sequence")
    requested = tuple(view_ids) or artifact.compiler_config.target_view_ids
    unknown = set(requested) - set(INTENT_FORMALIZATION_VIEW_REGISTRY.view_ids)
    if unknown:
        raise IntentAdvisorValidationError(
            "unsupported Intent advisor view IDs: "
            + ", ".join(sorted(unknown))
        )
    formulas = tuple(
        item for item in artifact.formulas if item.view_id in set(requested)
    )
    if not formulas:
        raise IntentAdvisorValidationError(
            "no Intent formulas match the requested advisor views"
        )
    paths = {
        path
        for formula in formulas
        for path in _SAFE_REPAIR_PATHS
        if _path_exists(thaw_json(formula.expression), path)
    }
    if not paths:
        raise IntentAdvisorValidationError(
            "selected Intent formulas expose no safe repair paths"
        )
    return RepairScope(
        formula_ids=tuple(item.formula_id for item in formulas),
        allowed_paths=tuple(paths),
        max_operations=max_operations,
    )


@dataclass(frozen=True, slots=True)
class IntentAdvisorRun:
    """Paired deterministic baseline and optional unverified advisor result."""

    deterministic_artifact: FormalizationArtifact
    advice: AdvisorResult | None = None
    path: IntentAdvisorPath = IntentAdvisorPath.DETERMINISTIC_ONLY

    def __post_init__(self) -> None:
        artifact = validate_intent_advisor_artifact(
            self.deterministic_artifact
        )
        object.__setattr__(self, "deterministic_artifact", artifact)
        try:
            path = (
                self.path
                if isinstance(self.path, IntentAdvisorPath)
                else IntentAdvisorPath(self.path)
            )
        except (TypeError, ValueError) as exc:
            raise IntentAdvisorValidationError(
                f"unsupported Intent advisor path: {self.path!r}"
            ) from exc
        object.__setattr__(self, "path", path)
        if path is IntentAdvisorPath.DETERMINISTIC_ONLY:
            if self.advice is not None:
                raise IntentAdvisorValidationError(
                    "deterministic-only path cannot contain advisor output"
                )
        else:
            if not isinstance(self.advice, AdvisorResult):
                raise IntentAdvisorValidationError(
                    "candidate path requires an AdvisorResult"
                )
            if self.advice.input_artifact_identity != artifact.digest:
                raise IntentAdvisorValidationError(
                    "advisor result does not identify the deterministic baseline"
                )
            if self.advice.authority != "unverified_candidate_only":
                raise IntentAdvisorValidationError(
                    "Intent candidates cannot claim proof or execution authority"
                )

    @property
    def artifact(self) -> FormalizationArtifact:
        """Compatibility spelling for the immutable deterministic baseline."""

        return self.deterministic_artifact

    @property
    def advisor_result(self) -> AdvisorResult | None:
        return self.advice

    @property
    def candidates(self) -> tuple[Any, ...]:
        return () if self.advice is None else self.advice.candidates

    @property
    def authority(self) -> str:
        return (
            "deterministic_compiler_output"
            if self.advice is None
            else "unverified_candidate_only"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "advice": None if self.advice is None else self.advice.to_dict(),
            "authority": self.authority,
            "deterministic_artifact_identity": self.deterministic_artifact.digest,
            "path": self.path.value,
        }


class IntentFormalizationAdvisor:
    """Compile first, then optionally validate bounded Intent candidates."""

    def __init__(
        self,
        model: AdvisorModel | None = None,
        *,
        checkpoint: CheckpointManifest | None = None,
        compiler: IntentFormalizationCompiler | None = None,
        config: AdvisorConfig | None = None,
        checkpoint_policy: IntentCheckpointPolicy = INTENT_CHECKPOINT_POLICY,
    ) -> None:
        if model is not None and not callable(
            getattr(model, "generate_candidates", None)
        ):
            raise TypeError("model must implement generate_candidates")
        if compiler is not None and not isinstance(
            compiler, IntentFormalizationCompiler
        ):
            raise TypeError("compiler must be an IntentFormalizationCompiler")
        if not isinstance(checkpoint_policy, IntentCheckpointPolicy):
            raise TypeError(
                "checkpoint_policy must be an IntentCheckpointPolicy"
            )
        self._model = model
        self._checkpoint = checkpoint
        self.compiler = compiler or IntentFormalizationCompiler()
        self.checkpoint_policy = checkpoint_policy
        self.config = config or AdvisorConfig(
            advisor_id=INTENT_FORMALIZATION_ADVISOR_ID,
            advisor_version=INTENT_FORMALIZATION_ADVISOR_VERSION,
            config_id=INTENT_FORMALIZATION_ADVISOR_CONFIG_ID,
            max_candidates=4,
            max_formulas_per_candidate=8,
            max_expression_nodes=512,
            max_expression_depth=24,
            max_expression_bytes=16_384,
            protected_field_names=(
                "intent_node_id",
                "intent_node_ids",
                "intent_node_kind",
                "intent_node_kinds",
            ),
        )
        if not isinstance(self.config, AdvisorConfig):
            raise TypeError("config must be an AdvisorConfig")
        self._bounded = (
            None
            if model is None
            else BoundedFormalizationAdvisor(model, self.config)
        )

    def advise(self, request: FormalizationAdvisorRequest) -> AdvisorResult:
        """Validate one pre-built request and return candidate-only output."""

        if not isinstance(request, FormalizationAdvisorRequest):
            raise IntentAdvisorValidationError(
                "request must be a FormalizationAdvisorRequest"
            )
        artifact = validate_intent_advisor_artifact(request.artifact)
        scoped = set(request.repair_scope.formula_ids)
        scoped_views = tuple(
            sorted(
                {
                    formula.view_id
                    for formula in artifact.formulas
                    if formula.formula_id in scoped
                }
            )
        )
        self.checkpoint_policy.validate(
            request.checkpoint, requested_view_ids=scoped_views
        )
        if request.ontology_identity != INTENT_FORMALIZATION_ONTOLOGY_IDENTITY:
            raise IntentAdvisorValidationError(
                "Intent advisor request uses a stale ontology identity"
            )
        if self._bounded is None:
            raise IntentAdvisorValidationError(
                "candidate path requires an advisor model backend"
            )
        baseline_identity = artifact.digest
        result = self._bounded.advise(request)
        if artifact.digest != baseline_identity:
            raise IntentAdvisorValidationError(
                "advisor mutated the deterministic artifact"
            )
        for candidate in result.candidates:
            self.checkpoint_policy.validate(
                request.checkpoint,
                requested_view_ids=tuple(
                    sorted(
                        {
                            formula.view_id
                            for formula in candidate.formulas
                            if formula.formula_id
                            in set(candidate.changed_formula_ids)
                        }
                    )
                ),
                advice_kind=candidate.kind,
            )
            for formula in candidate.formulas:
                _validate_formula_expression(formula)
        return result

    def advise_artifact(
        self,
        artifact: FormalizationArtifact,
        *,
        features: FormalizationFeatures,
        checkpoint: CheckpointManifest | None = None,
        repair_scope: RepairScope,
    ) -> AdvisorResult:
        """Build the generic request after enforcing Intent dependencies."""

        selected = checkpoint or self._checkpoint
        if selected is None:
            raise IntentAdvisorValidationError(
                "candidate path requires an Intent checkpoint manifest"
            )
        artifact = validate_intent_advisor_artifact(artifact)
        request = FormalizationAdvisorRequest(
            artifact=artifact,
            features=features,
            checkpoint=selected,
            ontology_identity=INTENT_FORMALIZATION_ONTOLOGY_IDENTITY,
            repair_scope=repair_scope,
        )
        return self.advise(request)

    def formalize(
        self,
        document: IntentIRDocument,
        *,
        compiler_config: FormalizationCompilerConfig | None = None,
        graph_context: Any = None,
        checkpoint: CheckpointManifest | None = None,
        repair_scope: RepairScope | None = None,
        context_snapshot_ids: Sequence[str] = (),
        use_advisor: bool | None = None,
    ) -> IntentAdvisorRun:
        """Compare deterministic-only and optional candidate paths.

        ``use_advisor=False`` always returns the deterministic path and never
        calls the model.  With ``None``, the candidate path is selected only
        when a checkpoint is supplied either here or at construction.
        """

        if use_advisor is not None and not isinstance(use_advisor, bool):
            raise IntentAdvisorValidationError(
                "use_advisor must be a boolean or None"
            )
        artifact = self.compiler.compile(
            document,
            compiler_config,
            graph_context=graph_context,
        )
        validate_intent_advisor_artifact(artifact)
        selected = checkpoint or self._checkpoint
        should_advise = selected is not None if use_advisor is None else use_advisor
        if not should_advise:
            return IntentAdvisorRun(artifact)
        if selected is None:
            raise IntentAdvisorValidationError(
                "candidate path requires an Intent checkpoint manifest"
            )
        head = self.checkpoint_policy.validate(selected)
        head_spec = self.checkpoint_policy.resolve_head(head.head_id)
        scope = repair_scope or default_intent_repair_scope(
            artifact, view_ids=head_spec.view_ids
        )
        features = build_intent_advisor_features(
            document,
            artifact,
            context_snapshot_ids=context_snapshot_ids,
        )
        advice = self.advise_artifact(
            artifact,
            features=features,
            checkpoint=head,
            repair_scope=scope,
        )
        return IntentAdvisorRun(
            artifact,
            advice=advice,
            path=IntentAdvisorPath.CANDIDATE,
        )

    # Domain terminology aliases for pipeline callers.
    compile_and_advise = formalize
    compare_paths = formalize


IntentFormalizationAdvice = IntentAdvisorRun


__all__ = [
    "INTENT_FORMALIZATION_ADVISOR_CONFIG_ID",
    "INTENT_FORMALIZATION_ADVISOR_ID",
    "INTENT_FORMALIZATION_ADVISOR_VERSION",
    "IntentAdvisorPath",
    "IntentAdvisorRun",
    "IntentAdvisorValidationError",
    "IntentFormalizationAdvisor",
    "IntentFormalizationAdvice",
    "build_intent_advisor_features",
    "default_intent_repair_scope",
    "validate_intent_advisor_artifact",
]
