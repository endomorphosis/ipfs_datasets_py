"""Regression tests for positional citation/source-id decompiler slots."""

from ipfs_datasets_py.logic.modal.codec import modal_ir_to_flogic_triples
from ipfs_datasets_py.logic.modal.decompiler import (
    decode_modal_ir_document,
    decoded_modal_phrase_slot_text_map,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


def _sample_document() -> ModalIRDocument:
    source_id = "us-code-21-360bbb-0-98e14cf1a6e12d46"
    formula = ModalIRFormula(
        formula_id="f-1",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_drug_approval"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=18,
            citation="21 U.S.C. 360bbb-0",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="21 U.S.C. 360bbb-0 temporary approval applies.",
        formulas=[formula],
    )


def test_decode_modal_ir_document_emits_positional_citation_slots() -> None:
    decoded = decode_modal_ir_document(_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_component_positioned"] == ["1:360bbb", "2:0"]
    assert slot_map["citation_section_number_positioned"] == ["1:360", "2:0"]
    assert slot_map["citation_section_suffix_positioned"] == ["1:bbb"]
    assert slot_map["citation_section_component_kind_positioned"] == [
        "1:alphanumeric",
        "2:numeric",
    ]

    assert slot_map["source_id_section_component_positioned"] == ["1:360bbb", "2:0"]
    assert slot_map["source_id_section_number_positioned"] == ["1:360", "2:0"]
    assert slot_map["source_id_section_suffix_positioned"] == ["1:bbb"]
    assert slot_map["source_id_section_component_kind_positioned"] == [
        "1:alphanumeric",
        "2:numeric",
    ]


def test_modal_ir_to_flogic_triples_emits_positional_citation_components() -> None:
    triples = modal_ir_to_flogic_triples(_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_component_positioned") == ["1:360bbb", "2:0"]
    assert objects("citation_section_number_positioned") == ["1:360", "2:0"]
    assert objects("citation_section_suffix_positioned") == ["1:bbb"]
    assert objects("citation_section_component_kind_positioned") == [
        "1:alphanumeric",
        "2:numeric",
    ]

    assert objects("source_id_section_component_positioned") == ["1:360bbb", "2:0"]
    assert objects("source_id_section_number_positioned") == ["1:360", "2:0"]
    assert objects("source_id_section_suffix_positioned") == ["1:bbb"]
    assert objects("source_id_section_component_kind_positioned") == [
        "1:alphanumeric",
        "2:numeric",
    ]
