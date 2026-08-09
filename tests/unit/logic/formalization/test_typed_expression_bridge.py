"""Bridge tests: FormalFormula / ConstraintStatement dual-read and typed write.

Acceptance (LFP-016):

* typed expressions validate family / profile / schema
* constraint contracts dual-read legacy payloads but write TypedExpression and
  TranslationContract@2 when those are supplied
* arbitrary JSON/text and a boolean loss flag cannot masquerade as elaborated
  syntax or a preservation receipt
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.translations import (
    CONTRACT_INTERFACE,
    NodeDisposition,
    NodeMapEntry,
    PreservationRelation,
    SymbolMapEntry,
    TranslationContract,
    TranslationEndpoint,
    TranslationIdentities,
)
from ipfs_datasets_py.logic.formalization.constraint_contracts import (
    CONSTRAINT_CONTRACT_INTERFACE,
    TRANSLATION_CONTRACT_INTERFACE,
    ConstraintRole,
    ConstraintStatement,
    ConstraintValidationError,
    TranslationReceipt,
    coerce_constraint_expression,
    coerce_translation_payload,
    serialize_constraint_expression,
    serialize_translation_payload,
)
from ipfs_datasets_py.logic.formalization.views import (
    FORMALIZATION_ARTIFACT_V2_INTERFACE,
    FormalFormula,
    FormalizationValidationError,
    coerce_formula_expression,
    is_typed_expression,
    serialize_formula_expression,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    TYPED_EXPRESSION_INTERFACE,
    TYPED_EXPRESSION_SCHEMA_VERSION,
    TypedExpression,
    mk_predicate,
)
from ipfs_datasets_py.logic.syntax_core.signatures import propositional_signature


def _typed_expression(
    *,
    expression_id: str = "expr:bridge-1",
    predicate: str = "P",
) -> TypedExpression:
    signature = propositional_signature(
        "sig:bridge",
        (predicate, "Q"),
        family="propositional",
        profile="classical",
    )
    return TypedExpression(
        expression_id=expression_id,
        root=mk_predicate(f"n:{predicate}", predicate),
        signature=signature,
        family="propositional",
        profile="classical",
    )


def _translation_contract() -> TranslationContract:
    return TranslationContract(
        contract_id="bridge_deontic_to_fol",
        source=TranslationEndpoint(
            family_id="deontic",
            profile_id="deontic_default",
            fragment_id="deontic_core",
            schema_id="deontic_schema",
            notation_id="deontic_notation",
            content_identity="sha256:deontic",
        ),
        target=TranslationEndpoint(
            family_id="first_order",
            profile_id="first_order_default",
            fragment_id="first_order_core",
            schema_id="first_order_schema",
            notation_id="first_order_notation",
            content_identity="sha256:first_order",
        ),
        preservation=PreservationRelation.HEURISTIC,
        identities=TranslationIdentities(
            compiler_identity="sha256:" + "a" * 64,
            profile_identity="sha256:" + "b" * 64,
            config_identity="sha256:" + "c" * 64,
            source_identity=(
                "bafkreiaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
            target_identity=(
                "bafkreibbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            ),
            environment_identity="sha256:" + "d" * 64,
        ),
        proof_safe=False,
        counterexample_safe=False,
        authority_ceiling=EvidenceAuthority.NONE,
        node_map=(
            NodeMapEntry(
                source_node_id="n_grant",
                target_node_ids=("t_fact",),
                disposition=NodeDisposition.APPROXIMATED,
                reason="heuristic lowering",
            ),
        ),
        symbol_map=(
            SymbolMapEntry(
                source_symbol_id="publish",
                target_symbol_ids=("publish_fol",),
                disposition=NodeDisposition.MAPPED,
            ),
        ),
        required_source_node_ids=("n_grant",),
        required_source_symbol_ids=("publish",),
        description="Reviewed heuristic deontic-to-FOL bridge edge.",
    )


# ---------------------------------------------------------------------------
# FormalFormula dual-read / typed write
# ---------------------------------------------------------------------------


def test_formal_formula_dual_reads_legacy_json_and_writes_legacy() -> None:
    formula = FormalFormula(
        formula_id="formula:legacy",
        view_id="view:facts",
        expression={"predicate": "holds", "arguments": ["x"]},
        source_ref_ids=("source:1",),
        span_ids=("span:1",),
    )
    assert formula.is_typed is False
    assert is_typed_expression(formula.expression) is False
    payload = formula.to_dict()
    assert payload["expression"] == {"arguments": ["x"], "predicate": "holds"}
    restored = FormalFormula.from_dict(payload)
    assert restored.expression == formula.expression
    assert FORMALIZATION_ARTIFACT_V2_INTERFACE == "FormalizationArtifact@2"


def test_formal_formula_accepts_typed_expression_and_writes_typed_envelope() -> None:
    typed = _typed_expression()
    formula = FormalFormula(
        formula_id="formula:typed",
        view_id="view:prop",
        expression=typed,
        source_ref_ids=("source:1",),
        span_ids=("span:1",),
    )
    assert formula.is_typed is True
    assert isinstance(formula.expression, TypedExpression)
    assert formula.expression.family.value == "propositional"
    assert formula.expression.profile.value == "classical"
    assert formula.expression.schema_version == TYPED_EXPRESSION_SCHEMA_VERSION

    payload = formula.to_dict()
    expression = payload["expression"]
    assert expression["interface"] == TYPED_EXPRESSION_INTERFACE
    assert expression["schema_version"] == TYPED_EXPRESSION_SCHEMA_VERSION
    assert expression["family"]["value"] == "propositional"
    assert expression["profile"]["value"] == "classical"

    restored = FormalFormula.from_dict(payload)
    assert restored.is_typed is True
    assert restored.expression.content_digest == typed.content_digest


def test_typed_expression_validates_family_profile_schema() -> None:
    with pytest.raises(FormalizationValidationError, match="TypedExpression"):
        coerce_formula_expression(
            {
                "interface": TYPED_EXPRESSION_INTERFACE,
                "schema_version": TYPED_EXPRESSION_SCHEMA_VERSION,
                "expression_id": "expr:bad",
                # Missing root/signature — cannot masquerade as elaborated syntax.
                "family": "propositional",
                "profile": "classical",
            }
        )

    with pytest.raises(FormalizationValidationError, match="TypedExpression"):
        FormalFormula(
            formula_id="formula:masquerade",
            view_id="view:prop",
            expression={
                "interface": TYPED_EXPRESSION_INTERFACE,
                "expression_id": "expr:masquerade",
                "root": {"not": "a logic node"},
                "signature": {"not": "a signature"},
            },
            source_ref_ids=("source:1",),
        )


def test_arbitrary_json_text_cannot_masquerade_as_typed_expression() -> None:
    # Unclaimed legacy JSON is dual-read as non-typed.
    legacy = coerce_formula_expression({"operator": "and", "args": []})
    assert is_typed_expression(legacy) is False
    assert serialize_formula_expression(legacy) == {"args": [], "operator": "and"}

    # Claiming TypedExpression without valid structure fails closed.
    with pytest.raises(FormalizationValidationError):
        coerce_formula_expression(
            {
                "interface": "TypedExpression@1",
                "expression_id": "x",
                "root": {},
                "signature": {},
            }
        )


# ---------------------------------------------------------------------------
# ConstraintStatement dual-read / typed write
# ---------------------------------------------------------------------------


def test_constraint_statement_dual_reads_legacy_and_writes_typed() -> None:
    legacy = ConstraintStatement(
        statement_id="stmt:legacy",
        role=ConstraintRole.CLAIM,
        logic_family="first_order",
        expression={"predicate": "p", "arguments": ["x"]},
        source_ref_ids=("source:1",),
        span_ids=("span:1",),
    )
    assert legacy.is_typed is False
    assert legacy.to_dict()["expression"]["predicate"] == "p"

    typed = _typed_expression(predicate="P")
    # propositional family matches TypedExpression
    statement = ConstraintStatement(
        statement_id="stmt:typed",
        role=ConstraintRole.CLAIM,
        logic_family="propositional",
        expression=typed,
        source_ref_ids=("source:1",),
        span_ids=("span:1",),
    )
    assert statement.is_typed is True
    wire = statement.to_dict()["expression"]
    assert wire["interface"] == TYPED_EXPRESSION_INTERFACE
    restored = ConstraintStatement.from_dict(statement.to_dict())
    assert restored.is_typed is True
    assert CONSTRAINT_CONTRACT_INTERFACE == "ConstraintContract@2"


def test_constraint_expression_rejects_text_masquerade() -> None:
    with pytest.raises(ConstraintValidationError, match="elaborated syntax"):
        coerce_constraint_expression("just some text")
    with pytest.raises(ConstraintValidationError, match="elaborated syntax"):
        coerce_constraint_expression(True)
    with pytest.raises(ConstraintValidationError, match="TypedExpression"):
        coerce_constraint_expression(
            {
                "interface": TYPED_EXPRESSION_INTERFACE,
                "schema_version": TYPED_EXPRESSION_SCHEMA_VERSION,
                "expression_id": "bad",
            }
        )


def test_constraint_statement_rejects_family_disagreement_with_typed() -> None:
    typed = _typed_expression()
    with pytest.raises(ConstraintValidationError, match="disagrees with TypedExpression"):
        ConstraintStatement(
            statement_id="stmt:mismatch",
            role=ConstraintRole.CLAIM,
            logic_family="deontic",
            expression=typed,
            source_ref_ids=("source:1",),
        )


# ---------------------------------------------------------------------------
# Translation dual-read: TranslationContract@2 vs legacy receipt / loss flag
# ---------------------------------------------------------------------------


def test_translation_dual_reads_legacy_receipt_and_contract() -> None:
    legacy = TranslationReceipt(
        translation_id="translation:legacy",
        source_logic_family="deontic",
        target_logic_family="first_order",
        source_view_id="view:deontic",
        target_view_id="view:fol",
        lossy=True,
    )
    assert coerce_translation_payload(legacy.to_dict()) == legacy
    wire = serialize_translation_payload(legacy)
    assert wire["lossy"] is True
    assert "preservation" not in wire

    contract = _translation_contract()
    parsed = coerce_translation_payload(contract.to_dict())
    assert isinstance(parsed, TranslationContract)
    assert parsed.interface == CONTRACT_INTERFACE == TRANSLATION_CONTRACT_INTERFACE
    written = serialize_translation_payload(parsed)
    assert written["interface"] == "TranslationContract@2"
    assert written["preservation"] == "heuristic"
    assert "lossy" not in written or written.get("lossy") is not True


def test_boolean_loss_flag_cannot_masquerade_as_preservation_receipt() -> None:
    with pytest.raises(ConstraintValidationError, match="boolean loss flag"):
        coerce_translation_payload(True)
    with pytest.raises(ConstraintValidationError, match="boolean loss flag"):
        coerce_translation_payload(False)
    with pytest.raises(ConstraintValidationError, match="boolean loss flag"):
        coerce_translation_payload({"lossy": True})
    with pytest.raises(ConstraintValidationError, match="boolean loss flag"):
        coerce_translation_payload({"lossy": False})


def test_claimed_translation_contract_must_validate_fully() -> None:
    with pytest.raises(ConstraintValidationError, match="TranslationContract@2"):
        coerce_translation_payload(
            {
                "interface": "TranslationContract@2",
                "contract_id": "incomplete",
                "preservation": "exact_equivalence",
                # Missing source/target/identities — not a preservation receipt.
            }
        )


def test_serialize_helpers_round_trip_typed_surfaces() -> None:
    typed = _typed_expression()
    assert serialize_constraint_expression(typed)["interface"] == TYPED_EXPRESSION_INTERFACE
    assert coerce_constraint_expression(
        serialize_constraint_expression(typed)
    ).content_digest == typed.content_digest

    contract = _translation_contract()
    assert (
        serialize_translation_payload(contract)["interface"]
        == TRANSLATION_CONTRACT_INTERFACE
    )
