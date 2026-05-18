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


def _range_sample_document() -> ModalIRDocument:
    source_id = "us-code-45-228a to 228c-0123456789abcdef"
    formula = ModalIRFormula(
        formula_id="f-range",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_child_support_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=22,
            citation="45 U.S.C. 228a to 228c",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="45 U.S.C. 228a to 228c child support enforcement.",
        formulas=[formula],
    )


def _single_component_sample_document() -> ModalIRDocument:
    source_id = "us-code-2-190l-01dd1648c5b1588c"
    formula = ModalIRFormula(
        formula_id="f-single",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="preserve_library_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=17,
            citation="2 U.S.C. 190l",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="2 U.S.C. 190l preservation requirement.",
        formulas=[formula],
    )


def _trailing_punct_sample_document() -> ModalIRDocument:
    source_id = "us-code-46-60101.-6bea2346c1c5229c"
    formula = ModalIRFormula(
        formula_id="f-trailing-punct",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="board_arriving_vessels_before_inspection"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=29,
            citation="46 U.S.C. 60101.",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="46 U.S.C. 60101. Boarding arriving vessels before inspection.",
        formulas=[formula],
    )


def test_decode_modal_ir_document_emits_positional_citation_slots() -> None:
    decoded = decode_modal_ir_document(_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_title_number"] == ["21"]
    assert slot_map["citation_title_token_count"] == ["1"]
    assert slot_map["citation_title_stem"] == ["21"]
    assert slot_map["citation_section_component_positioned"] == ["1:360bbb", "2:0"]
    assert slot_map["citation_section_number_positioned"] == ["1:360", "2:0"]
    assert slot_map["citation_section_number_digit_count"] == ["3", "1"]
    assert slot_map["citation_section_number_digit_count_positioned"] == ["1:3", "2:1"]
    assert slot_map["citation_section_suffix_positioned"] == ["1:bbb"]
    assert slot_map["citation_section_suffix_char_count"] == ["3"]
    assert slot_map["citation_section_suffix_char_count_positioned"] == ["1:3"]
    assert slot_map["citation_section_suffix_profile"] == ["repeat"]
    assert slot_map["citation_section_suffix_profile_positioned"] == ["1:repeat"]
    assert slot_map["citation_section_suffix_normalized"] == ["bbb"]
    assert slot_map["citation_section_suffix_case"] == ["lower"]
    assert slot_map["citation_section_suffix_case_positioned"] == ["1:lower"]
    assert slot_map["citation_section_component_kind_positioned"] == [
        "1:alphanumeric",
        "2:numeric",
    ]
    assert slot_map["citation_section_primary_number"] == ["360"]
    assert slot_map["citation_section_primary_number_digit_count"] == ["3"]
    assert slot_map["citation_section_primary_suffix"] == ["bbb"]
    assert slot_map["citation_section_primary_suffix_char_count"] == ["3"]
    assert slot_map["citation_section_primary_suffix_profile"] == ["repeat"]
    assert slot_map["citation_section_primary_component_kind"] == ["alphanumeric"]
    assert slot_map["citation_section_terminal_number"] == ["0"]
    assert slot_map["citation_section_terminal_number_digit_count"] == ["1"]
    assert slot_map["citation_section_terminal_component_kind"] == ["numeric"]
    assert slot_map["citation_title_section_key"] == ["21:360bbb-0"]
    assert slot_map["citation_title_section_key_normalized"] == ["21:360bbb-0"]

    assert slot_map["source_id_section_component_positioned"] == ["1:360bbb", "2:0"]
    assert slot_map["source_id_section_number_positioned"] == ["1:360", "2:0"]
    assert slot_map["source_id_section_number_digit_count"] == ["3", "1"]
    assert slot_map["source_id_section_number_digit_count_positioned"] == ["1:3", "2:1"]
    assert slot_map["source_id_section_suffix_positioned"] == ["1:bbb"]
    assert slot_map["source_id_section_suffix_char_count"] == ["3"]
    assert slot_map["source_id_section_suffix_char_count_positioned"] == ["1:3"]
    assert slot_map["source_id_section_suffix_profile"] == ["repeat"]
    assert slot_map["source_id_section_suffix_profile_positioned"] == ["1:repeat"]
    assert slot_map["source_id_section_suffix_normalized"] == ["bbb"]
    assert slot_map["source_id_section_suffix_case"] == ["lower"]
    assert slot_map["source_id_section_suffix_case_positioned"] == ["1:lower"]
    assert slot_map["source_id_section_component_kind_positioned"] == [
        "1:alphanumeric",
        "2:numeric",
    ]
    assert slot_map["source_id_section_primary_number"] == ["360"]
    assert slot_map["source_id_section_primary_number_digit_count"] == ["3"]
    assert slot_map["source_id_section_primary_suffix"] == ["bbb"]
    assert slot_map["source_id_section_primary_suffix_char_count"] == ["3"]
    assert slot_map["source_id_section_primary_suffix_profile"] == ["repeat"]
    assert slot_map["source_id_section_primary_component_kind"] == ["alphanumeric"]
    assert slot_map["source_id_section_terminal_number"] == ["0"]
    assert slot_map["source_id_section_terminal_number_digit_count"] == ["1"]
    assert slot_map["source_id_section_terminal_component_kind"] == ["numeric"]
    assert slot_map["source_id_title_section_key"] == ["21:360bbb-0"]
    assert slot_map["source_id_title_section_key_normalized"] == ["21:360bbb-0"]


def test_modal_ir_to_flogic_triples_emits_positional_citation_components() -> None:
    triples = modal_ir_to_flogic_triples(_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_title_number") == ["21"]
    assert objects("citation_title_token_count") == ["1"]
    assert objects("citation_title_stem") == ["21"]
    assert objects("citation_section_component_positioned") == ["1:360bbb", "2:0"]
    assert objects("citation_section_number_positioned") == ["1:360", "2:0"]
    assert objects("citation_section_number_digit_count") == ["3", "1"]
    assert objects("citation_section_number_digit_count_positioned") == ["1:3", "2:1"]
    assert objects("citation_section_suffix_positioned") == ["1:bbb"]
    assert objects("citation_section_suffix_char_count") == ["3"]
    assert objects("citation_section_suffix_char_count_positioned") == ["1:3"]
    assert objects("citation_section_suffix_profile") == ["repeat"]
    assert objects("citation_section_suffix_profile_positioned") == ["1:repeat"]
    assert objects("citation_section_suffix_normalized") == ["bbb"]
    assert objects("citation_section_suffix_case") == ["lower"]
    assert objects("citation_section_suffix_case_positioned") == ["1:lower"]
    assert objects("citation_section_component_kind_positioned") == [
        "1:alphanumeric",
        "2:numeric",
    ]
    assert objects("citation_section_primary_number") == ["360"]
    assert objects("citation_section_primary_number_digit_count") == ["3"]
    assert objects("citation_section_primary_suffix") == ["bbb"]
    assert objects("citation_section_primary_suffix_char_count") == ["3"]
    assert objects("citation_section_primary_suffix_profile") == ["repeat"]
    assert objects("citation_section_primary_component_kind") == ["alphanumeric"]
    assert objects("citation_section_terminal_number") == ["0"]
    assert objects("citation_section_terminal_number_digit_count") == ["1"]
    assert objects("citation_section_terminal_component_kind") == ["numeric"]
    assert objects("citation_title_section_key") == ["21:360bbb-0"]
    assert objects("citation_title_section_key_normalized") == ["21:360bbb-0"]

    assert objects("source_id_section_component_positioned") == ["1:360bbb", "2:0"]
    assert objects("source_id_section_number_positioned") == ["1:360", "2:0"]
    assert objects("source_id_section_number_digit_count") == ["3", "1"]
    assert objects("source_id_section_number_digit_count_positioned") == ["1:3", "2:1"]
    assert objects("source_id_section_suffix_positioned") == ["1:bbb"]
    assert objects("source_id_section_suffix_char_count") == ["3"]
    assert objects("source_id_section_suffix_char_count_positioned") == ["1:3"]
    assert objects("source_id_section_suffix_profile") == ["repeat"]
    assert objects("source_id_section_suffix_profile_positioned") == ["1:repeat"]
    assert objects("source_id_section_suffix_normalized") == ["bbb"]
    assert objects("source_id_section_suffix_case") == ["lower"]
    assert objects("source_id_section_suffix_case_positioned") == ["1:lower"]
    assert objects("source_id_section_component_kind_positioned") == [
        "1:alphanumeric",
        "2:numeric",
    ]
    assert objects("source_id_section_primary_number") == ["360"]
    assert objects("source_id_section_primary_number_digit_count") == ["3"]
    assert objects("source_id_section_primary_suffix") == ["bbb"]
    assert objects("source_id_section_primary_suffix_char_count") == ["3"]
    assert objects("source_id_section_primary_suffix_profile") == ["repeat"]
    assert objects("source_id_section_primary_component_kind") == ["alphanumeric"]
    assert objects("source_id_section_terminal_number") == ["0"]
    assert objects("source_id_section_terminal_number_digit_count") == ["1"]
    assert objects("source_id_section_terminal_component_kind") == ["numeric"]
    assert objects("source_id_title_section_key") == ["21:360bbb-0"]
    assert objects("source_id_title_section_key_normalized") == ["21:360bbb-0"]


def test_decode_modal_ir_document_emits_single_component_section_role_slots() -> None:
    decoded = decode_modal_ir_document(_single_component_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_primary_number"] == ["190"]
    assert slot_map["citation_section_primary_number_digit_count"] == ["3"]
    assert slot_map["citation_section_terminal_number"] == ["190"]
    assert slot_map["citation_section_terminal_number_digit_count"] == ["3"]
    assert slot_map["citation_section_primary_suffix"] == ["l"]
    assert slot_map["citation_section_suffix_char_count"] == ["1"]
    assert slot_map["citation_section_primary_suffix_char_count"] == ["1"]
    assert slot_map["citation_section_terminal_suffix_char_count"] == ["1"]
    assert slot_map["citation_section_suffix_profile"] == ["single"]
    assert slot_map["citation_section_primary_suffix_profile"] == ["single"]
    assert slot_map["citation_section_terminal_suffix_profile"] == ["single"]
    assert slot_map["citation_section_terminal_suffix"] == ["l"]
    assert slot_map["citation_section_primary_component_kind"] == ["alphanumeric"]
    assert slot_map["citation_section_terminal_component_kind"] == ["alphanumeric"]

    assert slot_map["source_id_section_primary_number"] == ["190"]
    assert slot_map["source_id_section_primary_number_digit_count"] == ["3"]
    assert slot_map["source_id_section_terminal_number"] == ["190"]
    assert slot_map["source_id_section_terminal_number_digit_count"] == ["3"]
    assert slot_map["source_id_section_primary_suffix"] == ["l"]
    assert slot_map["source_id_section_suffix_char_count"] == ["1"]
    assert slot_map["source_id_section_primary_suffix_char_count"] == ["1"]
    assert slot_map["source_id_section_terminal_suffix_char_count"] == ["1"]
    assert slot_map["source_id_section_suffix_profile"] == ["single"]
    assert slot_map["source_id_section_primary_suffix_profile"] == ["single"]
    assert slot_map["source_id_section_terminal_suffix_profile"] == ["single"]
    assert slot_map["source_id_section_terminal_suffix"] == ["l"]
    assert slot_map["source_id_section_primary_component_kind"] == ["alphanumeric"]
    assert slot_map["source_id_section_terminal_component_kind"] == ["alphanumeric"]


def test_modal_ir_to_flogic_triples_emits_single_component_section_role_slots() -> None:
    triples = modal_ir_to_flogic_triples(_single_component_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_primary_number") == ["190"]
    assert objects("citation_section_primary_number_digit_count") == ["3"]
    assert objects("citation_section_terminal_number") == ["190"]
    assert objects("citation_section_terminal_number_digit_count") == ["3"]
    assert objects("citation_section_primary_suffix") == ["l"]
    assert objects("citation_section_suffix_char_count") == ["1"]
    assert objects("citation_section_primary_suffix_char_count") == ["1"]
    assert objects("citation_section_terminal_suffix_char_count") == ["1"]
    assert objects("citation_section_suffix_profile") == ["single"]
    assert objects("citation_section_primary_suffix_profile") == ["single"]
    assert objects("citation_section_terminal_suffix_profile") == ["single"]
    assert objects("citation_section_terminal_suffix") == ["l"]
    assert objects("citation_section_primary_component_kind") == ["alphanumeric"]
    assert objects("citation_section_terminal_component_kind") == ["alphanumeric"]

    assert objects("source_id_section_primary_number") == ["190"]
    assert objects("source_id_section_primary_number_digit_count") == ["3"]
    assert objects("source_id_section_terminal_number") == ["190"]
    assert objects("source_id_section_terminal_number_digit_count") == ["3"]
    assert objects("source_id_section_primary_suffix") == ["l"]
    assert objects("source_id_section_suffix_char_count") == ["1"]
    assert objects("source_id_section_primary_suffix_char_count") == ["1"]
    assert objects("source_id_section_terminal_suffix_char_count") == ["1"]
    assert objects("source_id_section_suffix_profile") == ["single"]
    assert objects("source_id_section_primary_suffix_profile") == ["single"]
    assert objects("source_id_section_terminal_suffix_profile") == ["single"]
    assert objects("source_id_section_terminal_suffix") == ["l"]
    assert objects("source_id_section_primary_component_kind") == ["alphanumeric"]
    assert objects("source_id_section_terminal_component_kind") == ["alphanumeric"]


def test_decode_modal_ir_document_emits_section_range_slots() -> None:
    decoded = decode_modal_ir_document(_range_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_range"] == ["228a to 228c"]
    assert slot_map["citation_section_range_start"] == ["228a"]
    assert slot_map["citation_section_range_end"] == ["228c"]
    assert slot_map["citation_section_range_connector"] == ["to"]
    assert slot_map["citation_section_component_positioned"] == ["1:228a", "2:228c"]
    assert slot_map["citation_section_number_positioned"] == ["1:228", "2:228"]
    assert slot_map["citation_section_number_digit_count"] == ["3"]
    assert slot_map["citation_section_number_digit_count_positioned"] == ["1:3", "2:3"]
    assert slot_map["citation_section_primary_number_digit_count"] == ["3"]
    assert slot_map["citation_section_terminal_number_digit_count"] == ["3"]
    assert slot_map["citation_section_suffix_positioned"] == ["1:a", "2:c"]
    assert slot_map["citation_section_suffix_char_count"] == ["1"]
    assert slot_map["citation_section_suffix_char_count_positioned"] == ["1:1", "2:1"]
    assert slot_map["citation_section_suffix_profile"] == ["single"]
    assert slot_map["citation_section_suffix_profile_positioned"] == [
        "1:single",
        "2:single",
    ]
    assert slot_map["citation_section_component_kind_positioned"] == [
        "1:alphanumeric",
        "2:alphanumeric",
    ]
    assert slot_map["citation_title_section_key"] == ["45:228a to 228c"]
    assert slot_map["citation_title_section_key_normalized"] == ["45:228a to 228c"]

    assert slot_map["source_id_section_range"] == ["228a to 228c"]
    assert slot_map["source_id_section_range_start"] == ["228a"]
    assert slot_map["source_id_section_range_end"] == ["228c"]
    assert slot_map["source_id_section_range_connector"] == ["to"]
    assert slot_map["source_id_section_component_positioned"] == ["1:228a", "2:228c"]
    assert slot_map["source_id_section_number_positioned"] == ["1:228", "2:228"]
    assert slot_map["source_id_section_number_digit_count"] == ["3"]
    assert slot_map["source_id_section_number_digit_count_positioned"] == ["1:3", "2:3"]
    assert slot_map["source_id_section_primary_number_digit_count"] == ["3"]
    assert slot_map["source_id_section_terminal_number_digit_count"] == ["3"]
    assert slot_map["source_id_section_suffix_positioned"] == ["1:a", "2:c"]
    assert slot_map["source_id_section_suffix_char_count"] == ["1"]
    assert slot_map["source_id_section_suffix_char_count_positioned"] == ["1:1", "2:1"]
    assert slot_map["source_id_section_suffix_profile"] == ["single"]
    assert slot_map["source_id_section_suffix_profile_positioned"] == [
        "1:single",
        "2:single",
    ]
    assert slot_map["source_id_section_component_kind_positioned"] == [
        "1:alphanumeric",
        "2:alphanumeric",
    ]
    assert slot_map["source_id_title_section_key"] == ["45:228a to 228c"]
    assert slot_map["source_id_title_section_key_normalized"] == ["45:228a to 228c"]


def test_modal_ir_to_flogic_triples_emits_section_range_slots() -> None:
    triples = modal_ir_to_flogic_triples(_range_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_range") == ["228a to 228c"]
    assert objects("citation_section_range_start") == ["228a"]
    assert objects("citation_section_range_end") == ["228c"]
    assert objects("citation_section_range_connector") == ["to"]
    assert objects("citation_section_component_positioned") == ["1:228a", "2:228c"]
    assert objects("citation_section_number_positioned") == ["1:228", "2:228"]
    assert objects("citation_section_number_digit_count") == ["3"]
    assert objects("citation_section_number_digit_count_positioned") == ["1:3", "2:3"]
    assert objects("citation_section_primary_number_digit_count") == ["3"]
    assert objects("citation_section_terminal_number_digit_count") == ["3"]
    assert objects("citation_section_suffix_positioned") == ["1:a", "2:c"]
    assert objects("citation_section_suffix_char_count") == ["1"]
    assert objects("citation_section_suffix_char_count_positioned") == ["1:1", "2:1"]
    assert objects("citation_section_suffix_profile") == ["single"]
    assert objects("citation_section_suffix_profile_positioned") == [
        "1:single",
        "2:single",
    ]
    assert objects("citation_section_component_kind_positioned") == [
        "1:alphanumeric",
        "2:alphanumeric",
    ]
    assert objects("citation_title_section_key") == ["45:228a to 228c"]
    assert objects("citation_title_section_key_normalized") == ["45:228a to 228c"]

    assert objects("source_id_section_range") == ["228a to 228c"]
    assert objects("source_id_section_range_start") == ["228a"]
    assert objects("source_id_section_range_end") == ["228c"]
    assert objects("source_id_section_range_connector") == ["to"]
    assert objects("source_id_section_component_positioned") == ["1:228a", "2:228c"]
    assert objects("source_id_section_number_positioned") == ["1:228", "2:228"]
    assert objects("source_id_section_number_digit_count") == ["3"]
    assert objects("source_id_section_number_digit_count_positioned") == ["1:3", "2:3"]
    assert objects("source_id_section_primary_number_digit_count") == ["3"]
    assert objects("source_id_section_terminal_number_digit_count") == ["3"]
    assert objects("source_id_section_suffix_positioned") == ["1:a", "2:c"]
    assert objects("source_id_section_suffix_char_count") == ["1"]
    assert objects("source_id_section_suffix_char_count_positioned") == ["1:1", "2:1"]
    assert objects("source_id_section_suffix_profile") == ["single"]
    assert objects("source_id_section_suffix_profile_positioned") == [
        "1:single",
        "2:single",
    ]
    assert objects("source_id_section_component_kind_positioned") == [
        "1:alphanumeric",
        "2:alphanumeric",
    ]
    assert objects("source_id_title_section_key") == ["45:228a to 228c"]
    assert objects("source_id_title_section_key_normalized") == ["45:228a to 228c"]


def test_decode_modal_ir_document_emits_trailing_punct_presence_slots() -> None:
    decoded = decode_modal_ir_document(_trailing_punct_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_trailing_punct"] == ["."]
    assert slot_map["citation_section_has_trailing_punct"] == ["true"]
    assert slot_map["citation_section_trailing_punct_count"] == ["1"]
    assert slot_map["source_id_section_trailing_punct"] == ["."]
    assert slot_map["source_id_section_has_trailing_punct"] == ["true"]
    assert slot_map["source_id_section_trailing_punct_count"] == ["1"]


def test_modal_ir_to_flogic_triples_emit_trailing_punct_presence_slots() -> None:
    triples = modal_ir_to_flogic_triples(_trailing_punct_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_trailing_punct") == ["."]
    assert objects("citation_section_has_trailing_punct") == ["true"]
    assert objects("citation_section_trailing_punct_count") == ["1"]
    assert objects("source_id_section_trailing_punct") == ["."]
    assert objects("source_id_section_has_trailing_punct") == ["true"]
    assert objects("source_id_section_trailing_punct_count") == ["1"]


def test_decode_modal_ir_document_emits_document_modal_family_count_slots() -> None:
    sample = _sample_document()
    document = ModalIRDocument(
        document_id=sample.document_id,
        source=sample.source,
        normalized_text=sample.normalized_text,
        formulas=list(sample.formulas),
        metadata={
            "modal_family_counts": {
                "deontic": 2,
                "temporal": 1,
            }
        },
    )
    decoded = decode_modal_ir_document(document)
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["modal_family_count"] == ["deontic:2", "temporal:1"]
    assert slot_map["modal_family_count_ranked"] == [
        "1:deontic:2",
        "2:temporal:1",
    ]
    assert slot_map["modal_family_count_family"] == ["deontic", "temporal"]
    assert slot_map["modal_family_count_value"] == ["2", "1"]
    assert slot_map["modal_family_count_deontic"] == ["2"]
    assert slot_map["modal_family_count_temporal"] == ["1"]


def test_modal_ir_to_flogic_triples_emits_document_modal_family_count_slots() -> None:
    sample = _sample_document()
    document = ModalIRDocument(
        document_id=sample.document_id,
        source=sample.source,
        normalized_text=sample.normalized_text,
        formulas=list(sample.formulas),
        metadata={
            "modal_family_counts": {
                "deontic": 2,
                "temporal": 1,
            }
        },
    )
    triples = modal_ir_to_flogic_triples(document)

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("modal_family_count") == ["deontic:2", "temporal:1"]
    assert objects("modal_family_count_ranked") == [
        "1:deontic:2",
        "2:temporal:1",
    ]
    assert objects("modal_family_count_family") == ["deontic", "temporal"]
    assert objects("modal_family_count_value") == ["2", "1"]
    assert objects("modal_family_count_deontic") == ["2"]
    assert objects("modal_family_count_temporal") == ["1"]
