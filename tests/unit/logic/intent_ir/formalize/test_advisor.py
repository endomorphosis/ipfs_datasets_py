"""Intent advisor head, checkpoint, and authority-boundary tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.formalization.advisor import (
    AdvisorConfig,
    AdvisorValidationError,
    RepairScope,
)
from ipfs_datasets_py.logic.formalization.checkpoints import CheckpointManifest
from ipfs_datasets_py.logic.intent_ir.formalize.advisor import (
    INTENT_FORMALIZATION_ADVISOR_ID,
    INTENT_FORMALIZATION_ADVISOR_VERSION,
    IntentAdvisorPath,
    IntentAdvisorValidationError,
    IntentFormalizationAdvisor,
    build_intent_advisor_features,
    default_intent_repair_scope,
)
from ipfs_datasets_py.logic.intent_ir.formalize.checkpoint_policy import (
    INTENT_ADVISOR_CHECKPOINT_POLICY_VERSION,
    INTENT_CHECKPOINT_POLICY,
    INTENT_FORMALIZATION_ONTOLOGY_IDENTITY,
    INTENT_MODAL_HEAD_ID,
    INTENT_MULTIVIEW_HEAD_ID,
    create_intent_checkpoint_manifest,
)
from ipfs_datasets_py.logic.intent_ir.formalize.compiler import (
    INTENT_FACT_VIEW_ID,
    INTENT_MODAL_VIEW_ID,
    IntentFormalizationCompiler,
)
from ipfs_datasets_py.logic.intent_ir.schema import (
    IntentIRDocument,
    IntentKind,
    IntentModality,
    IntentStatement,
    SourceRef,
    StatementKind,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _document() -> IntentIRDocument:
    result = IntentIRDocument(
        document_id="intent:advisor-fixture",
        title="Publish a result",
        intent_kind=IntentKind.DECLARATIVE,
        sources=(
            SourceRef(
                ref_id="source:one",
                source_uri="urn:test:advisor",
                source_id="advisor-fixture",
                source_revision="v1",
                content_sha256=SHA_A,
            ),
        ),
        statements=(
            IntentStatement(
                statement_id="statement:goal",
                kind=StatementKind.GOAL,
                modality=IntentModality.INTENDED,
                normalized_text="Publish the result",
                predicate="publish",
                arguments=("result",),
                source_ref_ids=("source:one",),
            ),
        ),
    )
    result.validate()
    return result


def _checkpoint(
    *,
    head_id: str = INTENT_MULTIVIEW_HEAD_ID,
) -> CheckpointManifest:
    return create_intent_checkpoint_manifest(
        checkpoint_id="intent:checkpoint:advisor-fixture:v1",
        head_id=head_id,
        model_id="intent:advisor-fixture-model",
        model_version="1",
        weights_digest=f"sha256:{SHA_C}",
        training_config_identity=f"sha256:{SHA_B}",
    )


class _FakeModel:
    def __init__(self, mutate=None) -> None:
        self.mutate = mutate
        self.requests = []

    def generate_candidates(self, request):
        self.requests.append(request)
        if self.mutate is None:
            return ()
        formula = request.to_dict()["formulas"][0]
        expression = deepcopy(formula["expression"])
        self.mutate(expression)
        return (
            {
                "candidate_id": "candidate:intent:1",
                "kind": "formula_candidate",
                "repairs": [],
                "suggestions": [
                    {
                        "formula_id": formula["formula_id"],
                        "expression": expression,
                    }
                ],
            },
        )


def _modal_scope(document: IntentIRDocument) -> RepairScope:
    artifact = IntentFormalizationCompiler().compile(document)
    formula = next(
        item for item in artifact.formulas if item.view_id == INTENT_MODAL_VIEW_ID
    )
    return RepairScope(
        formula_ids=(formula.formula_id,),
        allowed_paths=("/body",),
    )


def test_no_advisor_and_candidate_paths_share_the_exact_baseline() -> None:
    document = _document()
    model = _FakeModel(
        lambda expression: expression["body"].update(predicate="submit")
    )
    advisor = IntentFormalizationAdvisor(model, checkpoint=_checkpoint())

    baseline = advisor.formalize(document, use_advisor=False)
    candidate = advisor.formalize(
        document,
        repair_scope=_modal_scope(document),
        use_advisor=True,
    )

    assert baseline.path is IntentAdvisorPath.DETERMINISTIC_ONLY
    assert baseline.advice is None
    assert model.requests and candidate.path is IntentAdvisorPath.CANDIDATE
    assert baseline.artifact.canonical_bytes() == candidate.artifact.canonical_bytes()
    assert candidate.advice is not None
    assert (
        next(
            item
            for item in candidate.candidates[0].formulas
            if item.view_id == INTENT_MODAL_VIEW_ID
        ).expression["body"]["predicate"]
        == "submit"
    )
    assert candidate.authority == "unverified_candidate_only"
    assert candidate.advice.input_artifact_identity == candidate.artifact.digest


def test_features_are_rebound_to_the_deterministic_compiler_sample() -> None:
    document = _document()
    artifact = IntentFormalizationCompiler().compile(document)
    features = build_intent_advisor_features(document, artifact)

    assert features.sample_id == artifact.sample_id
    assert features.declaration_digest == artifact.declaration_digest
    assert features.model_input


@pytest.mark.parametrize(
    ("name", "mutate"),
    (
        (
            "source",
            lambda expression: expression["body"].update(
                source_ref_ids=["source:model"]
            ),
        ),
        (
            "provenance",
            lambda expression: expression["body"].update(
                provenance={"producer": "model"}
            ),
        ),
        (
            "modality",
            lambda expression: expression["body"].update(
                modality=IntentModality.PROHIBITED.value
            ),
        ),
        (
            "assumption",
            lambda expression: expression["body"].update(
                assumptions=["model-invented"]
            ),
        ),
    ),
)
def test_candidate_cannot_mutate_frozen_intent_semantics(name, mutate) -> None:
    advisor = IntentFormalizationAdvisor(
        _FakeModel(mutate), checkpoint=_checkpoint()
    )

    with pytest.raises(AdvisorValidationError, match="cannot alter"):
        advisor.formalize(
            _document(),
            repair_scope=_modal_scope(_document()),
            use_advisor=True,
        )


def test_unsupported_view_and_wrong_head_scope_are_rejected() -> None:
    artifact = IntentFormalizationCompiler().compile(_document())
    with pytest.raises(
        IntentAdvisorValidationError, match="unsupported.*view"
    ):
        default_intent_repair_scope(
            artifact, view_ids=("intent-ir-view/unknown/v1",)
        )

    fact = next(
        item for item in artifact.formulas if item.view_id == INTENT_FACT_VIEW_ID
    )
    features = build_intent_advisor_features(_document(), artifact)
    advisor = IntentFormalizationAdvisor(
        _FakeModel(), checkpoint=_checkpoint(head_id=INTENT_MODAL_HEAD_ID)
    )
    with pytest.raises(AdvisorValidationError, match="does not cover"):
        advisor.advise_artifact(
            artifact,
            features=features,
            repair_scope=RepairScope(
                formula_ids=(fact.formula_id,),
                allowed_paths=("/predicate",),
            ),
        )


def test_oversized_output_and_invalid_formula_types_fail_closed() -> None:
    small = AdvisorConfig(
        advisor_id=INTENT_FORMALIZATION_ADVISOR_ID,
        advisor_version=INTENT_FORMALIZATION_ADVISOR_VERSION,
        max_expression_bytes=128,
    )
    oversized = IntentFormalizationAdvisor(
        _FakeModel(
            lambda expression: expression["body"].update(
                predicate="x" * 1024
            )
        ),
        checkpoint=_checkpoint(),
        config=small,
    )
    with pytest.raises(AdvisorValidationError, match="byte bound"):
        oversized.formalize(
            _document(),
            repair_scope=_modal_scope(_document()),
            use_advisor=True,
        )

    invalid_type = IntentFormalizationAdvisor(
        _FakeModel(
            lambda expression: expression["body"].update(
                predicate=["not", "a", "string"]
            )
        ),
        checkpoint=_checkpoint(),
    )
    with pytest.raises(
        IntentAdvisorValidationError, match="must be a string"
    ):
        invalid_type.formalize(
            _document(),
            repair_scope=_modal_scope(_document()),
            use_advisor=True,
        )


def test_stale_ontology_checkpoint_metadata_and_unknown_heads_fail_closed() -> None:
    checkpoint = _checkpoint()
    assert (
        checkpoint.ontology_identity
        == INTENT_FORMALIZATION_ONTOLOGY_IDENTITY
    )
    assert (
        checkpoint.metadata["policy_version"]
        == INTENT_ADVISOR_CHECKPOINT_POLICY_VERSION
    )
    assert INTENT_CHECKPOINT_POLICY.validate(checkpoint) == checkpoint

    with pytest.raises(AdvisorValidationError, match="incompatible"):
        INTENT_CHECKPOINT_POLICY.validate(
            replace(
                checkpoint,
                ontology_identity=f"sha256:{'0' * 64}",
            )
        )

    metadata = checkpoint.metadata.to_dict()
    metadata["policy_version"] = "intent-advisor-checkpoint-policy/v0"
    with pytest.raises(AdvisorValidationError, match="stale or incomplete"):
        INTENT_CHECKPOINT_POLICY.validate(
            replace(checkpoint, metadata=metadata)
        )

    with pytest.raises(AdvisorValidationError, match="unsupported.*head"):
        create_intent_checkpoint_manifest(
            checkpoint_id="intent:checkpoint:unknown:v1",
            head_id="intent:head:unknown",
            model_id="intent:model",
            model_version="1",
            weights_digest=f"sha256:{SHA_C}",
            training_config_identity=f"sha256:{SHA_B}",
        )


def test_candidates_cannot_claim_proof_or_execution_authority() -> None:
    advisor = IntentFormalizationAdvisor(
        _FakeModel(
            lambda expression: expression["body"].update(
                proof_status="proved"
            )
        ),
        checkpoint=_checkpoint(),
    )

    with pytest.raises(AdvisorValidationError, match="authority"):
        advisor.formalize(
            _document(),
            repair_scope=_modal_scope(_document()),
            use_advisor=True,
        )
