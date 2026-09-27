"""Novel IR predicates map onto symbols the catalog already contains."""
from ipfs_datasets_py.logic.modal.ir_symbol_catalog import (
    alias_predicate,
    ir_compression_loss,
    known_ir_symbols,
)


def test_heading_predicate_uses_the_bluebook_uscode_key() -> None:
    from ipfs_datasets_py.logic.modal.ir_symbol_catalog import bluebook_symbol

    heading = "United States Code, 2024 Edition Title 10 - ARMED FORCES"
    assert bluebook_symbol(heading) == "usc:us:10"
    assert bluebook_symbol("42 U.S.C. § 1983") == "usc:us:42:1983"
    assert (
        alias_predicate(
            "united_states_code_edition_title_armed",
            source_text=heading,
            role="frame",
        )
        == "usc:us:10"
    )
    assert alias_predicate("criminal_penalty_enforcement") == "criminal_penalty_enforcement"


def test_section_citation_is_added_beside_the_duty_predicate() -> None:
    from ipfs_datasets_py.logic.modal.ir_symbol_catalog import append_bluebook_citation_formulas
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
        ModalIRDocument,
        ModalIRFormula,
        ModalIROperator,
        ModalIRPredicate,
        ModalIRProvenance,
    )

    text = "A person shall keep the record under 42 U.S.C. § 1983."
    document = ModalIRDocument(
        document_id="duty",
        source=text,
        normalized_text=text,
        formulas=[
            ModalIRFormula(
                formula_id="duty:f1",
                operator=ModalIROperator(family="deontic", system="SDL", symbol="O", label="obligation"),
                predicate=ModalIRPredicate(name="record", arguments=["actor:person"], role="clause"),
                provenance=ModalIRProvenance(source_id="duty", start_char=0, end_char=len(text)),
            )
        ],
    )
    updated = append_bluebook_citation_formulas(document, text)
    names = [formula.predicate.name for formula in updated.formulas]
    assert names == ["record", "usc:us:42:1983"]
    assert updated.formulas[1].operator.symbol == "Frame"


def test_other_bluebook_families_use_existing_citation_keys() -> None:
    from ipfs_datasets_py.logic.modal.ir_symbol_catalog import bluebook_symbols

    assert "40-cfr-1.1" in bluebook_symbols("See 40 C.F.R. § 1.1.")
    assert "85-fr-12345" in bluebook_symbols("Published at 85 FR 12345.")
    assert "pl-111-148" in bluebook_symbols("Enacted by Pub. L. 111-148.")
    assert "123-f3d-456" in bluebook_symbols("See 123 F.3d 456.")


def test_duplicate_duty_formulas_collapse() -> None:
    from ipfs_datasets_py.logic.modal.ir_symbol_catalog import dedupe_modal_ir_formulas
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
        ModalIRDocument,
        ModalIRFormula,
        ModalIROperator,
        ModalIRPredicate,
        ModalIRProvenance,
    )

    def duty(formula_id: str) -> ModalIRFormula:
        return ModalIRFormula(
            formula_id=formula_id,
            operator=ModalIROperator(family="deontic", system="SDL", symbol="O", label="obligation"),
            predicate=ModalIRPredicate(name="record", arguments=["actor:person"], role="clause"),
            provenance=ModalIRProvenance(source_id="duty", start_char=0, end_char=10),
        )

    document = ModalIRDocument(
        document_id="duty",
        source="text",
        normalized_text="text",
        formulas=[duty("a"), duty("b")],
    )
    updated = dedupe_modal_ir_formulas(document)
    assert [formula.formula_id for formula in updated.formulas] == ["a"]


def test_compression_loss_rises_when_the_ir_is_not_shorter_than_the_source() -> None:
    short_loss, short_ratio = ir_compression_loss("one two three four five", "duty")
    long_loss, long_ratio = ir_compression_loss("one two", "one two three four")
    assert short_loss < long_loss
    assert short_ratio > 1.0
    assert long_ratio < 1.0
    assert 0.0 <= long_loss <= 1.0
