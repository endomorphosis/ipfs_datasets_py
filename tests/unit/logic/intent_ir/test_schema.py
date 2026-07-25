from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.intent_ir import (
    ControlEdgeKind,
    IntentAction,
    IntentControlEdge,
    IntentIRDocument,
    IntentIRValidationError,
    IntentKind,
    IntentModality,
    IntentStatement,
    ReviewStatus,
    SourceRef,
    StatementKind,
    canonical_intent_ir_json,
    intent_ir_sha256,
)


def _document() -> IntentIRDocument:
    source = SourceRef(
        ref_id="source:skill-1",
        source_uri="https://example.test/skills/one",
        source_id="skill-1",
        source_revision="snapshot-abc",
        content_sha256="a" * 64,
        container_uri="hf://datasets/example/skills@snapshot-abc/bundle.sqlite#skill-1",
        container_sha256="b" * 64,
        review_status=ReviewStatus.TRUSTED_FIXTURE,
    )
    statements = (
        IntentStatement(
            statement_id="statement:goal",
            kind=StatementKind.GOAL,
            modality=IntentModality.INTENDED,
            normalized_text="Produce a verified artifact.",
            predicate="produce",
            arguments=("artifact",),
            source_ref_ids=(source.ref_id,),
            review_status=ReviewStatus.TRUSTED_FIXTURE,
        ),
        IntentStatement(
            statement_id="statement:precondition",
            kind=StatementKind.PRECONDITION,
            modality=IntentModality.REQUIRED,
            normalized_text="The input exists.",
            source_ref_ids=(source.ref_id,),
            review_status=ReviewStatus.TRUSTED_FIXTURE,
        ),
        IntentStatement(
            statement_id="statement:effect",
            kind=StatementKind.EFFECT,
            modality=IntentModality.ASSERTED,
            normalized_text="The artifact exists.",
            source_ref_ids=(source.ref_id,),
            review_status=ReviewStatus.TRUSTED_FIXTURE,
        ),
        IntentStatement(
            statement_id="statement:verify",
            kind=StatementKind.VERIFICATION,
            modality=IntentModality.REQUIRED,
            normalized_text="The artifact passes validation.",
            source_ref_ids=(source.ref_id,),
            review_status=ReviewStatus.TRUSTED_FIXTURE,
        ),
    )
    actions = (
        IntentAction(
            action_id="action:build",
            actor="agent",
            verb="build",
            object_refs=("artifact",),
            source_ref_ids=(source.ref_id,),
            precondition_ids=("statement:precondition",),
            effect_ids=("statement:effect",),
        ),
        IntentAction(
            action_id="action:validate",
            actor="agent",
            verb="validate",
            object_refs=("artifact",),
            source_ref_ids=(source.ref_id,),
            verification_ids=("statement:verify",),
        ),
    )
    return IntentIRDocument(
        document_id="intent:skill-1",
        title="Build and validate an artifact",
        intent_kind=IntentKind.PROCEDURE,
        sources=(source,),
        statements=statements,
        actions=actions,
        control_edges=(
            IntentControlEdge(
                edge_id="edge:build-validate",
                source_action_id="action:build",
                target_action_id="action:validate",
                kind=ControlEdgeKind.ON_SUCCESS,
                source_ref_ids=(source.ref_id,),
            ),
        ),
        entry_action_ids=("action:build",),
        terminal_action_ids=("action:validate",),
        tags=("fixture", "intent"),
    )


def test_canonical_intent_ir_is_deterministic_and_source_grounded() -> None:
    document = _document()
    document.validate()

    reordered = replace(
        document,
        statements=tuple(reversed(document.statements)),
        actions=tuple(reversed(document.actions)),
        tags=tuple(reversed(document.tags)),
    )

    assert canonical_intent_ir_json(document) == canonical_intent_ir_json(reordered)
    assert intent_ir_sha256(document) == intent_ir_sha256(reordered)
    assert intent_ir_sha256(document).startswith("sha256:")


def test_intent_ir_rejects_dangling_action_references() -> None:
    document = _document()
    broken_action = replace(
        document.actions[0],
        precondition_ids=("statement:missing",),
    )

    with pytest.raises(IntentIRValidationError, match="unknown ids"):
        replace(
            document,
            actions=(broken_action, document.actions[1]),
        ).validate()


def test_intent_ir_rejects_wrong_statement_role() -> None:
    document = _document()
    broken_action = replace(
        document.actions[0],
        effect_ids=("statement:precondition",),
    )

    with pytest.raises(IntentIRValidationError, match="incompatible statement"):
        replace(
            document,
            actions=(broken_action, document.actions[1]),
        ).validate()


def test_procedure_requires_explicit_entry_and_terminal_actions() -> None:
    document = _document()

    with pytest.raises(IntentIRValidationError, match="entry_action_ids"):
        replace(document, entry_action_ids=()).validate()


def test_mapping_decoder_is_fail_closed_until_versioned_decoder_exists() -> None:
    from ipfs_datasets_py.logic.intent_ir import validate_intent_ir

    with pytest.raises(IntentIRValidationError, match="versioned decoder"):
        validate_intent_ir(_document().to_dict())


def test_schema_rejects_untyped_enum_values() -> None:
    with pytest.raises(
        IntentIRValidationError, match="IntentIRDocument.intent_kind"
    ):
        replace(_document(), intent_kind="procedure").validate()  # type: ignore[arg-type]


def test_schema_requires_normalized_lowercase_digests() -> None:
    document = _document()
    uppercase_source = replace(
        document.sources[0],
        content_sha256=document.sources[0].content_sha256.upper(),
    )

    with pytest.raises(IntentIRValidationError, match="lowercase"):
        replace(document, sources=(uppercase_source,)).validate()
