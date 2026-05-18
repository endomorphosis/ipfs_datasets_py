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


def _provenance_alignment_mismatch_sample_document() -> ModalIRDocument:
    source_id = "us-code-20-1131d-2a8fb06a45e3babe"
    formula = ModalIRFormula(
        formula_id="f-alignment-mismatch",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="publish_education_program_notice"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=17,
            citation="20 U.S.C. 1131e",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="20 U.S.C. 1131d compliance requirement.",
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


def _numeric_range_sample_document() -> ModalIRDocument:
    source_id = "us-code-50-1381 to 1398.-83310e751ed0d7a2"
    formula = ModalIRFormula(
        formula_id="f-numeric-range",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_homeland_security_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=24,
            citation="50 U.S.C. 1381 to 1398.",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="50 U.S.C. 1381 to 1398. Homeland security records are retained.",
        formulas=[formula],
    )


def _section_marker_sample_document() -> ModalIRDocument:
    source_id = "us-code-2-190l-01dd1648c5b1588c"
    formula = ModalIRFormula(
        formula_id="f-section-marker",
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
            end_char=18,
            citation="2 U.S.C. §190l",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="2 U.S.C. 190l preservation requirement.",
        formulas=[formula],
    )


def _plural_section_marker_range_sample_document() -> ModalIRDocument:
    source_id = "us-code-45-228a to 228c-0123456789abcdef"
    formula = ModalIRFormula(
        formula_id="f-plural-section-marker-range",
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
            end_char=24,
            citation="45 U.S.C. §§ 228a to 228c.",
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


def _dot_delimited_sample_document() -> ModalIRDocument:
    source_id = "us-code-42-1396.1-8fb22f17ff2a43cd"
    formula = ModalIRFormula(
        formula_id="f-dot-delimited",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="publish_healthcare_rule_update"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=20,
            citation="42 U.S.C. 1396.1",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="42 U.S.C. 1396.1 publication rule update applies.",
        formulas=[formula],
    )


def _roman_suffix_hyphen_sample_document() -> ModalIRDocument:
    source_id = "us-code-16-460iii-4-aa834016adcc86bf"
    formula = ModalIRFormula(
        formula_id="f-roman-suffix",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_national_park_access"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=23,
            citation="16 U.S.C. 460iii-4",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="16 U.S.C. 460iii-4 national park access requirement.",
        formulas=[formula],
    )


def _noncanonical_romanlike_suffix_sample_document() -> ModalIRDocument:
    source_id = "us-code-21-360ll-11684335ce2f2caa"
    formula = ModalIRFormula(
        formula_id="f-noncanonical-romanlike",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_drug_device_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=18,
            citation="21 U.S.C. 360ll",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="21 U.S.C. 360ll recordkeeping requirement.",
        formulas=[formula],
    )


def _repeat_roman_token_suffix_sample_document() -> ModalIRDocument:
    source_id = "us-code-42-3797cc-445d9bb6c7d68792"
    formula = ModalIRFormula(
        formula_id="f-repeat-roman-token",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_federal_program_reporting"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=20,
            citation="42 U.S.C. 3797cc",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="42 U.S.C. 3797cc reporting requirements apply.",
        formulas=[formula],
    )


def _zero_formula_sample_document() -> ModalIRDocument:
    source_id = "us-code-50-3091.-8130665c952dd22a"
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="This section is transferred.",
        formulas=[],
        metadata={
            "citation": "50 U.S.C. 3091.",
        },
    )


def _coarse_heading_tail_sample_document() -> ModalIRDocument:
    source_id = "us-code-20-741-d9743e9c6ae8213e"
    formula = ModalIRFormula(
        formula_id="f-coarse-heading-tail",
        operator=ModalIROperator(
            family="frame",
            system="frame",
            symbol="Frame",
            label="framed as",
        ),
        predicate=ModalIRPredicate(name="uscode_section_heading_fallback"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=8,
            citation="20 U.S.C. 741",
        ),
        metadata={"fallback_rule": "uscode_section_heading_coarse_v1"},
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="Sec. 741. Student aid program improvements.",
        formulas=[formula],
    )


def _zero_digit_signature_sample_document() -> ModalIRDocument:
    source_id = "us-code-43-1470.-845d9dceb9d264ab"
    formula = ModalIRFormula(
        formula_id="f-zero-digit-signature",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="preserve_land_patent_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=18,
            citation="43 U.S.C. 1470.",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="43 U.S.C. 1470. Land patent adjustment applies.",
        formulas=[formula],
    )


def test_decode_modal_ir_document_emits_positional_citation_slots() -> None:
    decoded = decode_modal_ir_document(_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_title_number"] == ["21"]
    assert slot_map["citation_title_token_count"] == ["1"]
    assert slot_map["citation_title_stem"] == ["21"]
    assert slot_map["citation_section_has_mixed_token"] == ["true"]
    assert slot_map["citation_section_mixed_token_count"] == ["1"]
    assert slot_map["citation_section_alnum_segment_count"] == ["3"]
    assert slot_map["citation_section_alnum_segment_prefix"] == ["360"]
    assert slot_map["citation_section_alnum_segment_suffix"] == ["0"]
    assert slot_map["citation_section_alnum_segment_positioned"] == [
        "1:360",
        "2:bbb",
        "3:0",
    ]
    assert slot_map["citation_section_alnum_segment_kind_positioned"] == [
        "1:numeric",
        "2:alpha",
        "3:numeric",
    ]
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
    assert slot_map["citation_section_has_suffix"] == ["true"]
    assert slot_map["citation_section_has_roman_suffix"] == ["false"]
    assert slot_map["citation_section_primary_has_suffix"] == ["true"]
    assert slot_map["citation_section_primary_suffix_is_roman"] == ["false"]
    assert slot_map["citation_section_terminal_has_suffix"] == ["false"]
    assert slot_map["citation_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["citation_section_roman_suffix_component_count"] == ["0"]
    assert slot_map["citation_section_primary_component_kind"] == ["alphanumeric"]
    assert slot_map["citation_section_terminal_number"] == ["0"]
    assert slot_map["citation_section_terminal_number_digit_count"] == ["1"]
    assert slot_map["citation_section_terminal_component_kind"] == ["numeric"]
    assert slot_map["citation_section_has_delimiter"] == ["true"]
    assert slot_map["citation_section_delimiter"] == ["hyphen"]
    assert slot_map["citation_section_delimiter_positioned"] == ["1:hyphen"]
    assert slot_map["citation_section_delimiter_token"] == ["-"]
    assert slot_map["citation_section_delimiter_token_positioned"] == ["1:-"]
    assert slot_map["citation_section_delimiter_count"] == ["1"]
    assert slot_map["citation_section_delimiter_char_count"] == ["1"]
    assert slot_map["citation_section_delimiter_char_count_positioned"] == ["1:1"]
    assert slot_map["citation_section_delimiter_pattern"] == ["hyphen"]
    assert slot_map["citation_section_delimiter_distinct_count"] == ["1"]
    assert slot_map["citation_section_is_range"] == ["false"]
    assert slot_map["citation_section_has_trailing_punct"] == ["false"]
    assert slot_map["citation_section_trailing_punct_count"] == ["0"]
    assert slot_map["citation_title_section_key"] == ["21:360bbb-0"]
    assert slot_map["citation_title_section_key_normalized"] == ["21:360bbb-0"]

    assert slot_map["source_id_section_component_positioned"] == ["1:360bbb", "2:0"]
    assert slot_map["source_id_section_has_mixed_token"] == ["true"]
    assert slot_map["source_id_section_mixed_token_count"] == ["1"]
    assert slot_map["source_id_section_alnum_segment_count"] == ["3"]
    assert slot_map["source_id_section_alnum_segment_prefix"] == ["360"]
    assert slot_map["source_id_section_alnum_segment_suffix"] == ["0"]
    assert slot_map["source_id_section_alnum_segment_positioned"] == [
        "1:360",
        "2:bbb",
        "3:0",
    ]
    assert slot_map["source_id_section_alnum_segment_kind_positioned"] == [
        "1:numeric",
        "2:alpha",
        "3:numeric",
    ]
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
    assert slot_map["source_id_section_has_suffix"] == ["true"]
    assert slot_map["source_id_section_has_roman_suffix"] == ["false"]
    assert slot_map["source_id_section_primary_has_suffix"] == ["true"]
    assert slot_map["source_id_section_primary_suffix_is_roman"] == ["false"]
    assert slot_map["source_id_section_terminal_has_suffix"] == ["false"]
    assert slot_map["source_id_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["source_id_section_roman_suffix_component_count"] == ["0"]
    assert slot_map["source_id_section_primary_component_kind"] == ["alphanumeric"]
    assert slot_map["source_id_section_terminal_number"] == ["0"]
    assert slot_map["source_id_section_terminal_number_digit_count"] == ["1"]
    assert slot_map["source_id_section_terminal_component_kind"] == ["numeric"]
    assert slot_map["source_id_section_has_delimiter"] == ["true"]
    assert slot_map["source_id_section_delimiter"] == ["hyphen"]
    assert slot_map["source_id_section_delimiter_positioned"] == ["1:hyphen"]
    assert slot_map["source_id_section_delimiter_token"] == ["-"]
    assert slot_map["source_id_section_delimiter_token_positioned"] == ["1:-"]
    assert slot_map["source_id_section_delimiter_count"] == ["1"]
    assert slot_map["source_id_section_delimiter_char_count"] == ["1"]
    assert slot_map["source_id_section_delimiter_char_count_positioned"] == ["1:1"]
    assert slot_map["source_id_section_delimiter_pattern"] == ["hyphen"]
    assert slot_map["source_id_section_delimiter_distinct_count"] == ["1"]
    assert slot_map["source_id_section_is_range"] == ["false"]
    assert slot_map["source_id_section_has_trailing_punct"] == ["false"]
    assert slot_map["source_id_section_trailing_punct_count"] == ["0"]
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
    assert objects("citation_section_has_mixed_token") == ["true"]
    assert objects("citation_section_mixed_token_count") == ["1"]
    assert objects("citation_section_alnum_segment_count") == ["3"]
    assert objects("citation_section_alnum_segment_prefix") == ["360"]
    assert objects("citation_section_alnum_segment_suffix") == ["0"]
    assert objects("citation_section_alnum_segment_positioned") == [
        "1:360",
        "2:bbb",
        "3:0",
    ]
    assert objects("citation_section_alnum_segment_kind_positioned") == [
        "1:numeric",
        "2:alpha",
        "3:numeric",
    ]
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
    assert objects("citation_section_has_suffix") == ["true"]
    assert objects("citation_section_has_roman_suffix") == ["false"]
    assert objects("citation_section_primary_has_suffix") == ["true"]
    assert objects("citation_section_primary_suffix_is_roman") == ["false"]
    assert objects("citation_section_terminal_has_suffix") == ["false"]
    assert objects("citation_section_terminal_suffix_is_roman") == ["false"]
    assert objects("citation_section_roman_suffix_component_count") == ["0"]
    assert objects("citation_section_primary_component_kind") == ["alphanumeric"]
    assert objects("citation_section_terminal_number") == ["0"]
    assert objects("citation_section_terminal_number_digit_count") == ["1"]
    assert objects("citation_section_terminal_component_kind") == ["numeric"]
    assert objects("citation_section_has_delimiter") == ["true"]
    assert objects("citation_section_delimiter") == ["hyphen"]
    assert objects("citation_section_delimiter_positioned") == ["1:hyphen"]
    assert objects("citation_section_delimiter_token") == ["-"]
    assert objects("citation_section_delimiter_token_positioned") == ["1:-"]
    assert objects("citation_section_delimiter_count") == ["1"]
    assert objects("citation_section_delimiter_char_count") == ["1"]
    assert objects("citation_section_delimiter_char_count_positioned") == ["1:1"]
    assert objects("citation_section_delimiter_pattern") == ["hyphen"]
    assert objects("citation_section_delimiter_distinct_count") == ["1"]
    assert objects("citation_section_is_range") == ["false"]
    assert objects("citation_section_has_trailing_punct") == ["false"]
    assert objects("citation_section_trailing_punct_count") == ["0"]
    assert objects("citation_title_section_key") == ["21:360bbb-0"]
    assert objects("citation_title_section_key_normalized") == ["21:360bbb-0"]

    assert objects("source_id_section_component_positioned") == ["1:360bbb", "2:0"]
    assert objects("source_id_section_has_mixed_token") == ["true"]
    assert objects("source_id_section_mixed_token_count") == ["1"]
    assert objects("source_id_section_alnum_segment_count") == ["3"]
    assert objects("source_id_section_alnum_segment_prefix") == ["360"]
    assert objects("source_id_section_alnum_segment_suffix") == ["0"]
    assert objects("source_id_section_alnum_segment_positioned") == [
        "1:360",
        "2:bbb",
        "3:0",
    ]
    assert objects("source_id_section_alnum_segment_kind_positioned") == [
        "1:numeric",
        "2:alpha",
        "3:numeric",
    ]
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
    assert objects("source_id_section_has_suffix") == ["true"]
    assert objects("source_id_section_has_roman_suffix") == ["false"]
    assert objects("source_id_section_primary_has_suffix") == ["true"]
    assert objects("source_id_section_primary_suffix_is_roman") == ["false"]
    assert objects("source_id_section_terminal_has_suffix") == ["false"]
    assert objects("source_id_section_terminal_suffix_is_roman") == ["false"]
    assert objects("source_id_section_roman_suffix_component_count") == ["0"]
    assert objects("source_id_section_primary_component_kind") == ["alphanumeric"]
    assert objects("source_id_section_terminal_number") == ["0"]
    assert objects("source_id_section_terminal_number_digit_count") == ["1"]
    assert objects("source_id_section_terminal_component_kind") == ["numeric"]
    assert objects("source_id_section_has_delimiter") == ["true"]
    assert objects("source_id_section_delimiter") == ["hyphen"]
    assert objects("source_id_section_delimiter_positioned") == ["1:hyphen"]
    assert objects("source_id_section_delimiter_token") == ["-"]
    assert objects("source_id_section_delimiter_token_positioned") == ["1:-"]
    assert objects("source_id_section_delimiter_count") == ["1"]
    assert objects("source_id_section_delimiter_char_count") == ["1"]
    assert objects("source_id_section_delimiter_char_count_positioned") == ["1:1"]
    assert objects("source_id_section_delimiter_pattern") == ["hyphen"]
    assert objects("source_id_section_delimiter_distinct_count") == ["1"]
    assert objects("source_id_section_is_range") == ["false"]
    assert objects("source_id_section_has_trailing_punct") == ["false"]
    assert objects("source_id_section_trailing_punct_count") == ["0"]
    assert objects("source_id_title_section_key") == ["21:360bbb-0"]
    assert objects("source_id_title_section_key_normalized") == ["21:360bbb-0"]


def test_decode_modal_ir_document_emits_single_component_section_role_slots() -> None:
    decoded = decode_modal_ir_document(_single_component_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_terminal"] == ["190l"]
    assert slot_map["citation_section_primary_equals_terminal"] == ["true"]
    assert slot_map["citation_section_primary_terminal_pair"] == ["190l|190l"]
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
    assert slot_map["citation_section_has_suffix"] == ["true"]
    assert slot_map["citation_section_primary_has_suffix"] == ["true"]
    assert slot_map["citation_section_terminal_has_suffix"] == ["true"]
    assert slot_map["citation_section_terminal_suffix"] == ["l"]
    assert slot_map["citation_section_primary_component_kind"] == ["alphanumeric"]
    assert slot_map["citation_section_terminal_component_kind"] == ["alphanumeric"]

    assert slot_map["source_id_section_terminal"] == ["190l"]
    assert slot_map["source_id_section_primary_equals_terminal"] == ["true"]
    assert slot_map["source_id_section_primary_terminal_pair"] == ["190l|190l"]
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
    assert slot_map["source_id_section_has_suffix"] == ["true"]
    assert slot_map["source_id_section_primary_has_suffix"] == ["true"]
    assert slot_map["source_id_section_terminal_has_suffix"] == ["true"]
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

    assert objects("citation_section_terminal") == ["190l"]
    assert objects("citation_section_primary_equals_terminal") == ["true"]
    assert objects("citation_section_primary_terminal_pair") == ["190l|190l"]
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
    assert objects("citation_section_has_suffix") == ["true"]
    assert objects("citation_section_primary_has_suffix") == ["true"]
    assert objects("citation_section_terminal_has_suffix") == ["true"]
    assert objects("citation_section_terminal_suffix") == ["l"]
    assert objects("citation_section_primary_component_kind") == ["alphanumeric"]
    assert objects("citation_section_terminal_component_kind") == ["alphanumeric"]

    assert objects("source_id_section_terminal") == ["190l"]
    assert objects("source_id_section_primary_equals_terminal") == ["true"]
    assert objects("source_id_section_primary_terminal_pair") == ["190l|190l"]
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
    assert objects("source_id_section_has_suffix") == ["true"]
    assert objects("source_id_section_primary_has_suffix") == ["true"]
    assert objects("source_id_section_terminal_has_suffix") == ["true"]
    assert objects("source_id_section_terminal_suffix") == ["l"]
    assert objects("source_id_section_primary_component_kind") == ["alphanumeric"]
    assert objects("source_id_section_terminal_component_kind") == ["alphanumeric"]


def test_decode_modal_ir_document_emits_roman_suffix_slots() -> None:
    decoded = decode_modal_ir_document(_roman_suffix_hyphen_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_suffix_kind"] == ["roman"]
    assert slot_map["citation_section_suffix_kind_positioned"] == ["1:roman"]
    assert slot_map["citation_section_primary_suffix_kind"] == ["roman"]
    assert "citation_section_terminal_suffix_kind" not in slot_map
    assert slot_map["citation_section_has_roman_suffix"] == ["true"]
    assert slot_map["citation_section_primary_suffix_is_roman"] == ["true"]
    assert slot_map["citation_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["citation_section_roman_suffix_component_count"] == ["1"]

    assert slot_map["source_id_section_suffix_kind"] == ["roman"]
    assert slot_map["source_id_section_suffix_kind_positioned"] == ["1:roman"]
    assert slot_map["source_id_section_primary_suffix_kind"] == ["roman"]
    assert "source_id_section_terminal_suffix_kind" not in slot_map
    assert slot_map["source_id_section_has_roman_suffix"] == ["true"]
    assert slot_map["source_id_section_primary_suffix_is_roman"] == ["true"]
    assert slot_map["source_id_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["source_id_section_roman_suffix_component_count"] == ["1"]


def test_modal_ir_to_flogic_triples_emits_roman_suffix_slots() -> None:
    triples = modal_ir_to_flogic_triples(_roman_suffix_hyphen_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_suffix_kind") == ["roman"]
    assert objects("citation_section_suffix_kind_positioned") == ["1:roman"]
    assert objects("citation_section_primary_suffix_kind") == ["roman"]
    assert objects("citation_section_terminal_suffix_kind") == []
    assert objects("citation_section_has_roman_suffix") == ["true"]
    assert objects("citation_section_primary_suffix_is_roman") == ["true"]
    assert objects("citation_section_terminal_suffix_is_roman") == ["false"]
    assert objects("citation_section_roman_suffix_component_count") == ["1"]

    assert objects("source_id_section_suffix_kind") == ["roman"]
    assert objects("source_id_section_suffix_kind_positioned") == ["1:roman"]
    assert objects("source_id_section_primary_suffix_kind") == ["roman"]
    assert objects("source_id_section_terminal_suffix_kind") == []
    assert objects("source_id_section_has_roman_suffix") == ["true"]
    assert objects("source_id_section_primary_suffix_is_roman") == ["true"]
    assert objects("source_id_section_terminal_suffix_is_roman") == ["false"]
    assert objects("source_id_section_roman_suffix_component_count") == ["1"]


def test_decode_modal_ir_document_emits_suffix_alpha_signature_slots() -> None:
    sample_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_sample_document())
    )
    assert sample_slot_map["citation_section_suffix_initial"] == ["b"]
    assert sample_slot_map["citation_section_suffix_terminal"] == ["b"]
    assert sample_slot_map["citation_section_suffix_initial_ordinal"] == ["2"]
    assert sample_slot_map["citation_section_suffix_terminal_ordinal"] == ["2"]
    assert sample_slot_map["citation_section_suffix_vowel_count"] == ["0"]
    assert sample_slot_map["citation_section_suffix_consonant_count"] == ["3"]
    assert sample_slot_map["citation_section_suffix_has_vowel"] == ["false"]
    assert sample_slot_map["citation_section_suffix_has_consonant"] == ["true"]
    assert sample_slot_map["citation_section_suffix_unique_char_count"] == ["1"]
    assert sample_slot_map["citation_section_primary_suffix_initial"] == ["b"]
    assert sample_slot_map["citation_section_primary_suffix_initial_ordinal"] == ["2"]
    assert sample_slot_map["citation_section_primary_suffix_has_consonant"] == ["true"]

    assert sample_slot_map["source_id_section_suffix_initial"] == ["b"]
    assert sample_slot_map["source_id_section_suffix_terminal"] == ["b"]
    assert sample_slot_map["source_id_section_suffix_initial_ordinal"] == ["2"]
    assert sample_slot_map["source_id_section_suffix_terminal_ordinal"] == ["2"]
    assert sample_slot_map["source_id_section_suffix_vowel_count"] == ["0"]
    assert sample_slot_map["source_id_section_suffix_consonant_count"] == ["3"]
    assert sample_slot_map["source_id_section_suffix_has_vowel"] == ["false"]
    assert sample_slot_map["source_id_section_suffix_has_consonant"] == ["true"]
    assert sample_slot_map["source_id_section_suffix_unique_char_count"] == ["1"]
    assert sample_slot_map["source_id_section_primary_suffix_initial"] == ["b"]
    assert sample_slot_map["source_id_section_primary_suffix_initial_ordinal"] == ["2"]
    assert sample_slot_map["source_id_section_primary_suffix_has_consonant"] == ["true"]

    range_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_range_sample_document())
    )
    assert range_slot_map["citation_section_suffix_initial_positioned"] == [
        "1:a",
        "2:c",
    ]
    assert range_slot_map["citation_section_suffix_initial_ordinal_positioned"] == [
        "1:1",
        "2:3",
    ]
    assert range_slot_map["citation_section_suffix_has_vowel_positioned"] == [
        "1:true",
        "2:false",
    ]
    assert range_slot_map["citation_section_suffix_has_consonant_positioned"] == [
        "1:false",
        "2:true",
    ]
    assert range_slot_map["citation_section_primary_suffix_has_vowel"] == ["true"]
    assert range_slot_map["citation_section_terminal_suffix_has_vowel"] == ["false"]

    assert range_slot_map["source_id_section_suffix_initial_positioned"] == [
        "1:a",
        "2:c",
    ]
    assert range_slot_map["source_id_section_suffix_initial_ordinal_positioned"] == [
        "1:1",
        "2:3",
    ]
    assert range_slot_map["source_id_section_suffix_has_vowel_positioned"] == [
        "1:true",
        "2:false",
    ]
    assert range_slot_map["source_id_section_suffix_has_consonant_positioned"] == [
        "1:false",
        "2:true",
    ]
    assert range_slot_map["source_id_section_primary_suffix_has_vowel"] == ["true"]
    assert range_slot_map["source_id_section_terminal_suffix_has_vowel"] == ["false"]


def test_modal_ir_to_flogic_triples_emits_suffix_alpha_signature_slots() -> None:
    sample_triples = modal_ir_to_flogic_triples(_sample_document())
    range_triples = modal_ir_to_flogic_triples(_range_sample_document())

    def objects(triples: list[dict[str, str]], predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects(sample_triples, "citation_section_suffix_initial") == ["b"]
    assert objects(sample_triples, "citation_section_suffix_terminal") == ["b"]
    assert objects(sample_triples, "citation_section_suffix_initial_ordinal") == ["2"]
    assert objects(sample_triples, "citation_section_suffix_terminal_ordinal") == ["2"]
    assert objects(sample_triples, "citation_section_suffix_vowel_count") == ["0"]
    assert objects(sample_triples, "citation_section_suffix_consonant_count") == ["3"]
    assert objects(sample_triples, "citation_section_suffix_has_vowel") == ["false"]
    assert objects(sample_triples, "citation_section_suffix_has_consonant") == ["true"]
    assert objects(sample_triples, "citation_section_suffix_unique_char_count") == ["1"]
    assert objects(sample_triples, "citation_section_primary_suffix_initial") == ["b"]
    assert objects(sample_triples, "citation_section_primary_suffix_initial_ordinal") == ["2"]
    assert objects(sample_triples, "citation_section_primary_suffix_has_consonant") == [
        "true"
    ]

    assert objects(sample_triples, "source_id_section_suffix_initial") == ["b"]
    assert objects(sample_triples, "source_id_section_suffix_terminal") == ["b"]
    assert objects(sample_triples, "source_id_section_suffix_initial_ordinal") == ["2"]
    assert objects(sample_triples, "source_id_section_suffix_terminal_ordinal") == ["2"]
    assert objects(sample_triples, "source_id_section_suffix_vowel_count") == ["0"]
    assert objects(sample_triples, "source_id_section_suffix_consonant_count") == ["3"]
    assert objects(sample_triples, "source_id_section_suffix_has_vowel") == ["false"]
    assert objects(sample_triples, "source_id_section_suffix_has_consonant") == ["true"]
    assert objects(sample_triples, "source_id_section_suffix_unique_char_count") == ["1"]
    assert objects(sample_triples, "source_id_section_primary_suffix_initial") == ["b"]
    assert objects(sample_triples, "source_id_section_primary_suffix_initial_ordinal") == [
        "2"
    ]
    assert objects(
        sample_triples,
        "source_id_section_primary_suffix_has_consonant",
    ) == ["true"]

    assert objects(range_triples, "citation_section_suffix_initial_positioned") == [
        "1:a",
        "2:c",
    ]
    assert objects(
        range_triples,
        "citation_section_suffix_initial_ordinal_positioned",
    ) == ["1:1", "2:3"]
    assert objects(range_triples, "citation_section_suffix_has_vowel_positioned") == [
        "1:true",
        "2:false",
    ]
    assert objects(
        range_triples,
        "citation_section_suffix_has_consonant_positioned",
    ) == ["1:false", "2:true"]
    assert objects(range_triples, "citation_section_primary_suffix_has_vowel") == ["true"]
    assert objects(range_triples, "citation_section_terminal_suffix_has_vowel") == [
        "false"
    ]

    assert objects(range_triples, "source_id_section_suffix_initial_positioned") == [
        "1:a",
        "2:c",
    ]
    assert objects(
        range_triples,
        "source_id_section_suffix_initial_ordinal_positioned",
    ) == ["1:1", "2:3"]
    assert objects(range_triples, "source_id_section_suffix_has_vowel_positioned") == [
        "1:true",
        "2:false",
    ]
    assert objects(
        range_triples,
        "source_id_section_suffix_has_consonant_positioned",
    ) == ["1:false", "2:true"]
    assert objects(range_triples, "source_id_section_primary_suffix_has_vowel") == [
        "true"
    ]
    assert objects(range_triples, "source_id_section_terminal_suffix_has_vowel") == [
        "false"
    ]


def test_decode_modal_ir_document_does_not_misclassify_noncanonical_roman_suffix() -> None:
    decoded = decode_modal_ir_document(_noncanonical_romanlike_suffix_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_suffix_kind"] == ["alpha"]
    assert slot_map["citation_section_primary_suffix_kind"] == ["alpha"]
    assert slot_map["citation_section_terminal_suffix_kind"] == ["alpha"]
    assert slot_map["citation_section_has_roman_suffix"] == ["false"]
    assert slot_map["citation_section_primary_suffix_is_roman"] == ["false"]
    assert slot_map["citation_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["citation_section_roman_suffix_component_count"] == ["0"]

    assert slot_map["source_id_section_suffix_kind"] == ["alpha"]
    assert slot_map["source_id_section_primary_suffix_kind"] == ["alpha"]
    assert slot_map["source_id_section_terminal_suffix_kind"] == ["alpha"]
    assert slot_map["source_id_section_has_roman_suffix"] == ["false"]
    assert slot_map["source_id_section_primary_suffix_is_roman"] == ["false"]
    assert slot_map["source_id_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["source_id_section_roman_suffix_component_count"] == ["0"]


def test_modal_ir_to_flogic_triples_does_not_misclassify_noncanonical_roman_suffix() -> None:
    triples = modal_ir_to_flogic_triples(_noncanonical_romanlike_suffix_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_suffix_kind") == ["alpha"]
    assert objects("citation_section_primary_suffix_kind") == ["alpha"]
    assert objects("citation_section_terminal_suffix_kind") == ["alpha"]
    assert objects("citation_section_has_roman_suffix") == ["false"]
    assert objects("citation_section_primary_suffix_is_roman") == ["false"]
    assert objects("citation_section_terminal_suffix_is_roman") == ["false"]
    assert objects("citation_section_roman_suffix_component_count") == ["0"]

    assert objects("source_id_section_suffix_kind") == ["alpha"]
    assert objects("source_id_section_primary_suffix_kind") == ["alpha"]
    assert objects("source_id_section_terminal_suffix_kind") == ["alpha"]
    assert objects("source_id_section_has_roman_suffix") == ["false"]
    assert objects("source_id_section_primary_suffix_is_roman") == ["false"]
    assert objects("source_id_section_terminal_suffix_is_roman") == ["false"]
    assert objects("source_id_section_roman_suffix_component_count") == ["0"]


def test_decode_modal_ir_document_treats_repeat_roman_tokens_as_alpha_suffixes() -> None:
    decoded = decode_modal_ir_document(_repeat_roman_token_suffix_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_suffix_kind"] == ["alpha"]
    assert slot_map["citation_section_primary_suffix_kind"] == ["alpha"]
    assert slot_map["citation_section_terminal_suffix_kind"] == ["alpha"]
    assert slot_map["citation_section_has_roman_suffix"] == ["false"]
    assert slot_map["citation_section_primary_suffix_is_roman"] == ["false"]
    assert slot_map["citation_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["citation_section_roman_suffix_component_count"] == ["0"]

    assert slot_map["source_id_section_suffix_kind"] == ["alpha"]
    assert slot_map["source_id_section_primary_suffix_kind"] == ["alpha"]
    assert slot_map["source_id_section_terminal_suffix_kind"] == ["alpha"]
    assert slot_map["source_id_section_has_roman_suffix"] == ["false"]
    assert slot_map["source_id_section_primary_suffix_is_roman"] == ["false"]
    assert slot_map["source_id_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["source_id_section_roman_suffix_component_count"] == ["0"]


def test_modal_ir_to_flogic_triples_treats_repeat_roman_tokens_as_alpha_suffixes() -> None:
    triples = modal_ir_to_flogic_triples(_repeat_roman_token_suffix_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_suffix_kind") == ["alpha"]
    assert objects("citation_section_primary_suffix_kind") == ["alpha"]
    assert objects("citation_section_terminal_suffix_kind") == ["alpha"]
    assert objects("citation_section_has_roman_suffix") == ["false"]
    assert objects("citation_section_primary_suffix_is_roman") == ["false"]
    assert objects("citation_section_terminal_suffix_is_roman") == ["false"]
    assert objects("citation_section_roman_suffix_component_count") == ["0"]

    assert objects("source_id_section_suffix_kind") == ["alpha"]
    assert objects("source_id_section_primary_suffix_kind") == ["alpha"]
    assert objects("source_id_section_terminal_suffix_kind") == ["alpha"]
    assert objects("source_id_section_has_roman_suffix") == ["false"]
    assert objects("source_id_section_primary_suffix_is_roman") == ["false"]
    assert objects("source_id_section_terminal_suffix_is_roman") == ["false"]
    assert objects("source_id_section_roman_suffix_component_count") == ["0"]


def test_decode_modal_ir_document_emits_section_range_slots() -> None:
    decoded = decode_modal_ir_document(_range_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_terminal"] == ["228c"]
    assert slot_map["citation_section_primary_equals_terminal"] == ["false"]
    assert slot_map["citation_section_primary_terminal_pair"] == ["228a|228c"]
    assert slot_map["citation_section_range"] == ["228a to 228c"]
    assert slot_map["citation_section_range_start"] == ["228a"]
    assert slot_map["citation_section_range_end"] == ["228c"]
    assert slot_map["citation_section_range_connector"] == ["to"]
    assert slot_map["citation_section_is_range"] == ["true"]
    assert slot_map["citation_section_range_has_suffix"] == ["true"]
    assert slot_map["citation_section_range_number_relation"] == ["equal"]
    assert slot_map["citation_section_range_number_span"] == ["0"]
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
    assert slot_map["citation_section_has_suffix"] == ["true"]
    assert slot_map["citation_section_primary_has_suffix"] == ["true"]
    assert slot_map["citation_section_terminal_has_suffix"] == ["true"]
    assert slot_map["citation_section_component_kind_positioned"] == [
        "1:alphanumeric",
        "2:alphanumeric",
    ]
    assert slot_map["citation_section_has_delimiter"] == ["false"]
    assert slot_map["citation_section_delimiter_count"] == ["0"]
    assert slot_map["citation_title_section_key"] == ["45:228a to 228c"]
    assert slot_map["citation_title_section_key_normalized"] == ["45:228a to 228c"]

    assert slot_map["source_id_section_terminal"] == ["228c"]
    assert slot_map["source_id_section_primary_equals_terminal"] == ["false"]
    assert slot_map["source_id_section_primary_terminal_pair"] == ["228a|228c"]
    assert slot_map["source_id_section_range"] == ["228a to 228c"]
    assert slot_map["source_id_section_range_start"] == ["228a"]
    assert slot_map["source_id_section_range_end"] == ["228c"]
    assert slot_map["source_id_section_range_connector"] == ["to"]
    assert slot_map["source_id_section_is_range"] == ["true"]
    assert slot_map["source_id_section_range_has_suffix"] == ["true"]
    assert slot_map["source_id_section_range_number_relation"] == ["equal"]
    assert slot_map["source_id_section_range_number_span"] == ["0"]
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
    assert slot_map["source_id_section_has_suffix"] == ["true"]
    assert slot_map["source_id_section_primary_has_suffix"] == ["true"]
    assert slot_map["source_id_section_terminal_has_suffix"] == ["true"]
    assert slot_map["source_id_section_component_kind_positioned"] == [
        "1:alphanumeric",
        "2:alphanumeric",
    ]
    assert slot_map["source_id_section_has_delimiter"] == ["false"]
    assert slot_map["source_id_section_delimiter_count"] == ["0"]
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

    assert objects("citation_section_terminal") == ["228c"]
    assert objects("citation_section_primary_equals_terminal") == ["false"]
    assert objects("citation_section_primary_terminal_pair") == ["228a|228c"]
    assert objects("citation_section_range") == ["228a to 228c"]
    assert objects("citation_section_range_start") == ["228a"]
    assert objects("citation_section_range_end") == ["228c"]
    assert objects("citation_section_range_connector") == ["to"]
    assert objects("citation_section_is_range") == ["true"]
    assert objects("citation_section_range_has_suffix") == ["true"]
    assert objects("citation_section_range_number_relation") == ["equal"]
    assert objects("citation_section_range_number_span") == ["0"]
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
    assert objects("citation_section_has_suffix") == ["true"]
    assert objects("citation_section_primary_has_suffix") == ["true"]
    assert objects("citation_section_terminal_has_suffix") == ["true"]
    assert objects("citation_section_component_kind_positioned") == [
        "1:alphanumeric",
        "2:alphanumeric",
    ]
    assert objects("citation_section_has_delimiter") == ["false"]
    assert objects("citation_section_delimiter_count") == ["0"]
    assert objects("citation_title_section_key") == ["45:228a to 228c"]
    assert objects("citation_title_section_key_normalized") == ["45:228a to 228c"]

    assert objects("source_id_section_terminal") == ["228c"]
    assert objects("source_id_section_primary_equals_terminal") == ["false"]
    assert objects("source_id_section_primary_terminal_pair") == ["228a|228c"]
    assert objects("source_id_section_range") == ["228a to 228c"]
    assert objects("source_id_section_range_start") == ["228a"]
    assert objects("source_id_section_range_end") == ["228c"]
    assert objects("source_id_section_range_connector") == ["to"]
    assert objects("source_id_section_is_range") == ["true"]
    assert objects("source_id_section_range_has_suffix") == ["true"]
    assert objects("source_id_section_range_number_relation") == ["equal"]
    assert objects("source_id_section_range_number_span") == ["0"]
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
    assert objects("source_id_section_has_suffix") == ["true"]
    assert objects("source_id_section_primary_has_suffix") == ["true"]
    assert objects("source_id_section_terminal_has_suffix") == ["true"]
    assert objects("source_id_section_component_kind_positioned") == [
        "1:alphanumeric",
        "2:alphanumeric",
    ]
    assert objects("source_id_section_has_delimiter") == ["false"]
    assert objects("source_id_section_delimiter_count") == ["0"]
    assert objects("source_id_title_section_key") == ["45:228a to 228c"]
    assert objects("source_id_title_section_key_normalized") == ["45:228a to 228c"]


def test_decode_modal_ir_document_emits_numeric_section_range_relation_slots() -> None:
    decoded = decode_modal_ir_document(_numeric_range_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_range"] == ["1381 to 1398"]
    assert slot_map["citation_section_is_range"] == ["true"]
    assert slot_map["citation_section_range_has_suffix"] == ["false"]
    assert slot_map["citation_section_range_number_relation"] == ["ascending"]
    assert slot_map["citation_section_range_number_span"] == ["17"]
    assert slot_map["source_id_section_range"] == ["1381 to 1398"]
    assert slot_map["source_id_section_is_range"] == ["true"]
    assert slot_map["source_id_section_range_has_suffix"] == ["false"]
    assert slot_map["source_id_section_range_number_relation"] == ["ascending"]
    assert slot_map["source_id_section_range_number_span"] == ["17"]


def test_modal_ir_to_flogic_triples_emits_numeric_section_range_relation_slots() -> None:
    triples = modal_ir_to_flogic_triples(_numeric_range_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_range") == ["1381 to 1398"]
    assert objects("citation_section_is_range") == ["true"]
    assert objects("citation_section_range_has_suffix") == ["false"]
    assert objects("citation_section_range_number_relation") == ["ascending"]
    assert objects("citation_section_range_number_span") == ["17"]
    assert objects("source_id_section_range") == ["1381 to 1398"]
    assert objects("source_id_section_is_range") == ["true"]
    assert objects("source_id_section_range_has_suffix") == ["false"]
    assert objects("source_id_section_range_number_relation") == ["ascending"]
    assert objects("source_id_section_range_number_span") == ["17"]


def test_decode_modal_ir_document_emits_dot_delimiter_slots() -> None:
    decoded = decode_modal_ir_document(_dot_delimited_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_has_delimiter"] == ["true"]
    assert slot_map["citation_section_delimiter"] == ["dot"]
    assert slot_map["citation_section_delimiter_positioned"] == ["1:dot"]
    assert slot_map["citation_section_delimiter_token"] == ["."]
    assert slot_map["citation_section_delimiter_token_positioned"] == ["1:."]
    assert slot_map["citation_section_delimiter_count"] == ["1"]
    assert slot_map["citation_section_delimiter_char_count"] == ["1"]
    assert slot_map["citation_section_delimiter_char_count_positioned"] == ["1:1"]
    assert slot_map["citation_section_delimiter_pattern"] == ["dot"]
    assert slot_map["citation_section_delimiter_distinct_count"] == ["1"]

    assert slot_map["source_id_section_has_delimiter"] == ["true"]
    assert slot_map["source_id_section_delimiter"] == ["dot"]
    assert slot_map["source_id_section_delimiter_positioned"] == ["1:dot"]
    assert slot_map["source_id_section_delimiter_token"] == ["."]
    assert slot_map["source_id_section_delimiter_token_positioned"] == ["1:."]
    assert slot_map["source_id_section_delimiter_count"] == ["1"]
    assert slot_map["source_id_section_delimiter_char_count"] == ["1"]
    assert slot_map["source_id_section_delimiter_char_count_positioned"] == ["1:1"]
    assert slot_map["source_id_section_delimiter_pattern"] == ["dot"]
    assert slot_map["source_id_section_delimiter_distinct_count"] == ["1"]


def test_modal_ir_to_flogic_triples_emits_dot_delimiter_slots() -> None:
    triples = modal_ir_to_flogic_triples(_dot_delimited_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_has_delimiter") == ["true"]
    assert objects("citation_section_delimiter") == ["dot"]
    assert objects("citation_section_delimiter_positioned") == ["1:dot"]
    assert objects("citation_section_delimiter_token") == ["."]
    assert objects("citation_section_delimiter_token_positioned") == ["1:."]
    assert objects("citation_section_delimiter_count") == ["1"]
    assert objects("citation_section_delimiter_char_count") == ["1"]
    assert objects("citation_section_delimiter_char_count_positioned") == ["1:1"]
    assert objects("citation_section_delimiter_pattern") == ["dot"]
    assert objects("citation_section_delimiter_distinct_count") == ["1"]

    assert objects("source_id_section_has_delimiter") == ["true"]
    assert objects("source_id_section_delimiter") == ["dot"]
    assert objects("source_id_section_delimiter_positioned") == ["1:dot"]
    assert objects("source_id_section_delimiter_token") == ["."]
    assert objects("source_id_section_delimiter_token_positioned") == ["1:."]
    assert objects("source_id_section_delimiter_count") == ["1"]
    assert objects("source_id_section_delimiter_char_count") == ["1"]
    assert objects("source_id_section_delimiter_char_count_positioned") == ["1:1"]
    assert objects("source_id_section_delimiter_pattern") == ["dot"]
    assert objects("source_id_section_delimiter_distinct_count") == ["1"]


def test_decode_modal_ir_document_emits_trailing_punct_presence_slots() -> None:
    decoded = decode_modal_ir_document(_trailing_punct_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_trailing_punct"] == ["."]
    assert slot_map["citation_section_has_trailing_punct"] == ["true"]
    assert slot_map["citation_section_trailing_punct_count"] == ["1"]
    assert slot_map["citation_section_trailing_punct_kind"] == ["dot"]
    assert slot_map["citation_section_has_suffix"] == ["false"]
    assert slot_map["citation_section_primary_has_suffix"] == ["false"]
    assert slot_map["citation_section_terminal_has_suffix"] == ["false"]
    assert slot_map["source_id_section_trailing_punct"] == ["."]
    assert slot_map["source_id_section_has_trailing_punct"] == ["true"]
    assert slot_map["source_id_section_trailing_punct_count"] == ["1"]
    assert slot_map["source_id_section_trailing_punct_kind"] == ["dot"]
    assert slot_map["source_id_section_has_suffix"] == ["false"]
    assert slot_map["source_id_section_primary_has_suffix"] == ["false"]
    assert slot_map["source_id_section_terminal_has_suffix"] == ["false"]


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
    assert objects("citation_section_trailing_punct_kind") == ["dot"]
    assert objects("citation_section_has_suffix") == ["false"]
    assert objects("citation_section_primary_has_suffix") == ["false"]
    assert objects("citation_section_terminal_has_suffix") == ["false"]
    assert objects("source_id_section_trailing_punct") == ["."]
    assert objects("source_id_section_has_trailing_punct") == ["true"]
    assert objects("source_id_section_trailing_punct_count") == ["1"]
    assert objects("source_id_section_trailing_punct_kind") == ["dot"]
    assert objects("source_id_section_has_suffix") == ["false"]
    assert objects("source_id_section_primary_has_suffix") == ["false"]
    assert objects("source_id_section_terminal_has_suffix") == ["false"]


def test_decode_modal_ir_document_emits_section_profile_and_number_relation_slots() -> None:
    mixed_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_sample_document())
    )
    assert mixed_slot_map["citation_section_component_profile"] == ["compound_mixed"]
    assert mixed_slot_map["citation_section_primary_terminal_number_relation"] == [
        "descending"
    ]
    assert mixed_slot_map["citation_section_primary_terminal_number_span"] == ["360"]
    assert mixed_slot_map["source_id_section_component_profile"] == ["compound_mixed"]
    assert mixed_slot_map["source_id_section_primary_terminal_number_relation"] == [
        "descending"
    ]
    assert mixed_slot_map["source_id_section_primary_terminal_number_span"] == ["360"]

    single_alnum_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_single_component_sample_document())
    )
    assert single_alnum_slot_map["citation_section_component_profile"] == [
        "single_alphanumeric"
    ]
    assert single_alnum_slot_map["citation_section_primary_terminal_number_relation"] == [
        "equal"
    ]
    assert single_alnum_slot_map["citation_section_primary_terminal_number_span"] == ["0"]
    assert single_alnum_slot_map["source_id_section_component_profile"] == [
        "single_alphanumeric"
    ]
    assert single_alnum_slot_map["source_id_section_primary_terminal_number_relation"] == [
        "equal"
    ]
    assert single_alnum_slot_map["source_id_section_primary_terminal_number_span"] == [
        "0"
    ]

    single_numeric_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_trailing_punct_sample_document())
    )
    assert single_numeric_slot_map["citation_section_component_profile"] == [
        "single_numeric"
    ]
    assert single_numeric_slot_map["source_id_section_component_profile"] == [
        "single_numeric"
    ]

    range_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_range_sample_document())
    )
    assert range_slot_map["citation_section_component_profile"] == ["range"]
    assert range_slot_map["citation_section_primary_terminal_number_relation"] == [
        "equal"
    ]
    assert range_slot_map["citation_section_primary_terminal_number_span"] == ["0"]
    assert range_slot_map["source_id_section_component_profile"] == ["range"]
    assert range_slot_map["source_id_section_primary_terminal_number_relation"] == [
        "equal"
    ]
    assert range_slot_map["source_id_section_primary_terminal_number_span"] == ["0"]


def test_modal_ir_to_flogic_triples_emit_section_profile_and_number_relation_slots() -> None:
    mixed_triples = modal_ir_to_flogic_triples(_sample_document())
    single_alnum_triples = modal_ir_to_flogic_triples(_single_component_sample_document())
    single_numeric_triples = modal_ir_to_flogic_triples(_trailing_punct_sample_document())
    range_triples = modal_ir_to_flogic_triples(_range_sample_document())

    def objects(triples: list[dict[str, str]], predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects(mixed_triples, "citation_section_component_profile") == [
        "compound_mixed"
    ]
    assert objects(mixed_triples, "citation_section_primary_terminal_number_relation") == [
        "descending"
    ]
    assert objects(mixed_triples, "citation_section_primary_terminal_number_span") == [
        "360"
    ]
    assert objects(mixed_triples, "source_id_section_component_profile") == [
        "compound_mixed"
    ]
    assert objects(mixed_triples, "source_id_section_primary_terminal_number_relation") == [
        "descending"
    ]
    assert objects(mixed_triples, "source_id_section_primary_terminal_number_span") == [
        "360"
    ]

    assert objects(single_alnum_triples, "citation_section_component_profile") == [
        "single_alphanumeric"
    ]
    assert objects(single_alnum_triples, "citation_section_primary_terminal_number_relation") == [
        "equal"
    ]
    assert objects(single_alnum_triples, "citation_section_primary_terminal_number_span") == [
        "0"
    ]
    assert objects(single_alnum_triples, "source_id_section_component_profile") == [
        "single_alphanumeric"
    ]
    assert objects(single_alnum_triples, "source_id_section_primary_terminal_number_relation") == [
        "equal"
    ]
    assert objects(single_alnum_triples, "source_id_section_primary_terminal_number_span") == [
        "0"
    ]

    assert objects(single_numeric_triples, "citation_section_component_profile") == [
        "single_numeric"
    ]
    assert objects(single_numeric_triples, "source_id_section_component_profile") == [
        "single_numeric"
    ]

    assert objects(range_triples, "citation_section_component_profile") == ["range"]
    assert objects(range_triples, "citation_section_primary_terminal_number_relation") == [
        "equal"
    ]
    assert objects(range_triples, "citation_section_primary_terminal_number_span") == [
        "0"
    ]
    assert objects(range_triples, "source_id_section_component_profile") == ["range"]
    assert objects(range_triples, "source_id_section_primary_terminal_number_relation") == [
        "equal"
    ]
    assert objects(range_triples, "source_id_section_primary_terminal_number_span") == [
        "0"
    ]


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


def test_modal_ir_to_flogic_triples_emits_document_citation_slots_when_no_formulas() -> None:
    triples = modal_ir_to_flogic_triples(_zero_formula_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation") == ["50 U.S.C. 3091."]
    assert objects("citation_canonical") == ["50 U.S.C. 3091"]
    assert objects("citation_section") == ["3091"]
    assert objects("citation_section_trailing_punct") == ["."]
    assert objects("citation_section_trailing_punct_count") == ["1"]
    assert objects("source_id_section") == ["3091."]
    assert objects("source_id_section_normalized") == ["3091"]
    assert objects("source_id_section_trailing_punct") == ["."]
    assert objects("source_id_section_trailing_punct_count") == ["1"]
    assert objects("source_id_citation_canonical") == ["50 U.S.C. 3091"]


def test_decode_modal_ir_document_emits_numeric_signature_slots() -> None:
    slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_dot_delimited_sample_document())
    )

    assert slot_map["citation_title_number_parity"] == ["even"]
    assert slot_map["citation_title_number_leading_digit"] == ["4"]
    assert slot_map["citation_title_number_trailing_two_digits"] == ["42"]
    assert slot_map["citation_title_number_zero_digit_count"] == ["0"]
    assert slot_map["citation_title_number_has_zero_digit"] == ["false"]
    assert slot_map["citation_title_number_trailing_zero_count"] == ["0"]
    assert slot_map["source_id_title_number_parity"] == ["even"]
    assert slot_map["source_id_title_number_leading_digit"] == ["4"]
    assert slot_map["source_id_title_number_trailing_two_digits"] == ["42"]
    assert slot_map["source_id_title_number_zero_digit_count"] == ["0"]
    assert slot_map["source_id_title_number_has_zero_digit"] == ["false"]
    assert slot_map["source_id_title_number_trailing_zero_count"] == ["0"]

    assert slot_map["citation_section_number_parity"] == ["even", "odd"]
    assert slot_map["citation_section_number_parity_positioned"] == ["1:even", "2:odd"]
    assert slot_map["citation_section_number_leading_digit_positioned"] == ["1:1", "2:1"]
    assert slot_map["citation_section_number_trailing_two_digits_positioned"] == [
        "1:96",
        "2:1",
    ]
    assert slot_map["citation_section_number_zero_digit_count"] == ["0"]
    assert slot_map["citation_section_number_zero_digit_count_positioned"] == [
        "1:0",
        "2:0",
    ]
    assert slot_map["citation_section_number_has_zero_digit"] == ["false"]
    assert slot_map["citation_section_number_has_zero_digit_positioned"] == [
        "1:false",
        "2:false",
    ]
    assert slot_map["citation_section_number_trailing_zero_count"] == ["0"]
    assert slot_map["citation_section_number_trailing_zero_count_positioned"] == [
        "1:0",
        "2:0",
    ]
    assert slot_map["citation_section_primary_number_parity"] == ["even"]
    assert slot_map["citation_section_primary_number_leading_digit"] == ["1"]
    assert slot_map["citation_section_primary_number_trailing_two_digits"] == ["96"]
    assert slot_map["citation_section_primary_number_zero_digit_count"] == ["0"]
    assert slot_map["citation_section_primary_number_has_zero_digit"] == ["false"]
    assert slot_map["citation_section_primary_number_trailing_zero_count"] == ["0"]
    assert slot_map["citation_section_terminal_number_parity"] == ["odd"]
    assert slot_map["citation_section_terminal_number_leading_digit"] == ["1"]
    assert slot_map["citation_section_terminal_number_trailing_two_digits"] == ["1"]
    assert slot_map["citation_section_terminal_number_zero_digit_count"] == ["0"]
    assert slot_map["citation_section_terminal_number_has_zero_digit"] == ["false"]
    assert slot_map["citation_section_terminal_number_trailing_zero_count"] == ["0"]

    assert slot_map["source_id_section_number_parity"] == ["even", "odd"]
    assert slot_map["source_id_section_number_parity_positioned"] == ["1:even", "2:odd"]
    assert slot_map["source_id_section_number_leading_digit_positioned"] == [
        "1:1",
        "2:1",
    ]
    assert slot_map["source_id_section_number_trailing_two_digits_positioned"] == [
        "1:96",
        "2:1",
    ]
    assert slot_map["source_id_section_number_zero_digit_count"] == ["0"]
    assert slot_map["source_id_section_number_zero_digit_count_positioned"] == [
        "1:0",
        "2:0",
    ]
    assert slot_map["source_id_section_number_has_zero_digit"] == ["false"]
    assert slot_map["source_id_section_number_has_zero_digit_positioned"] == [
        "1:false",
        "2:false",
    ]
    assert slot_map["source_id_section_number_trailing_zero_count"] == ["0"]
    assert slot_map["source_id_section_number_trailing_zero_count_positioned"] == [
        "1:0",
        "2:0",
    ]
    assert slot_map["source_id_section_primary_number_parity"] == ["even"]
    assert slot_map["source_id_section_primary_number_leading_digit"] == ["1"]
    assert slot_map["source_id_section_primary_number_trailing_two_digits"] == ["96"]
    assert slot_map["source_id_section_primary_number_zero_digit_count"] == ["0"]
    assert slot_map["source_id_section_primary_number_has_zero_digit"] == ["false"]
    assert slot_map["source_id_section_primary_number_trailing_zero_count"] == ["0"]
    assert slot_map["source_id_section_terminal_number_parity"] == ["odd"]
    assert slot_map["source_id_section_terminal_number_leading_digit"] == ["1"]
    assert slot_map["source_id_section_terminal_number_trailing_two_digits"] == ["1"]
    assert slot_map["source_id_section_terminal_number_zero_digit_count"] == ["0"]
    assert slot_map["source_id_section_terminal_number_has_zero_digit"] == ["false"]
    assert slot_map["source_id_section_terminal_number_trailing_zero_count"] == ["0"]

    zero_digit_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_zero_digit_signature_sample_document())
    )
    assert zero_digit_slot_map["citation_title_number_zero_digit_count"] == ["0"]
    assert zero_digit_slot_map["citation_title_number_has_zero_digit"] == ["false"]
    assert zero_digit_slot_map["citation_title_number_trailing_zero_count"] == ["0"]
    assert zero_digit_slot_map["citation_section_number_zero_digit_count"] == ["1"]
    assert zero_digit_slot_map["citation_section_number_has_zero_digit"] == ["true"]
    assert zero_digit_slot_map["citation_section_number_trailing_zero_count"] == ["1"]
    assert zero_digit_slot_map["citation_section_number_zero_digit_count_positioned"] == [
        "1:1"
    ]
    assert zero_digit_slot_map["citation_section_number_has_zero_digit_positioned"] == [
        "1:true"
    ]
    assert zero_digit_slot_map[
        "citation_section_number_trailing_zero_count_positioned"
    ] == ["1:1"]
    assert zero_digit_slot_map["citation_section_primary_number_zero_digit_count"] == [
        "1"
    ]
    assert zero_digit_slot_map["citation_section_primary_number_has_zero_digit"] == [
        "true"
    ]
    assert zero_digit_slot_map["citation_section_primary_number_trailing_zero_count"] == [
        "1"
    ]
    assert zero_digit_slot_map["source_id_section_number_zero_digit_count"] == ["1"]
    assert zero_digit_slot_map["source_id_section_number_has_zero_digit"] == ["true"]
    assert zero_digit_slot_map["source_id_section_number_trailing_zero_count"] == ["1"]
    assert zero_digit_slot_map["source_id_section_primary_number_zero_digit_count"] == [
        "1"
    ]
    assert zero_digit_slot_map["source_id_section_primary_number_has_zero_digit"] == [
        "true"
    ]
    assert zero_digit_slot_map["source_id_section_primary_number_trailing_zero_count"] == [
        "1"
    ]

    odd_title_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_sample_document())
    )
    assert odd_title_slot_map["citation_title_number_parity"] == ["odd"]
    assert odd_title_slot_map["source_id_title_number_parity"] == ["odd"]


def test_modal_ir_to_flogic_triples_emits_numeric_signature_slots() -> None:
    triples = modal_ir_to_flogic_triples(_dot_delimited_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_title_number_parity") == ["even"]
    assert objects("citation_title_number_leading_digit") == ["4"]
    assert objects("citation_title_number_trailing_two_digits") == ["42"]
    assert objects("citation_title_number_zero_digit_count") == ["0"]
    assert objects("citation_title_number_has_zero_digit") == ["false"]
    assert objects("citation_title_number_trailing_zero_count") == ["0"]
    assert objects("source_id_title_number_parity") == ["even"]
    assert objects("source_id_title_number_leading_digit") == ["4"]
    assert objects("source_id_title_number_trailing_two_digits") == ["42"]
    assert objects("source_id_title_number_zero_digit_count") == ["0"]
    assert objects("source_id_title_number_has_zero_digit") == ["false"]
    assert objects("source_id_title_number_trailing_zero_count") == ["0"]

    assert objects("citation_section_number_parity") == ["even", "odd"]
    assert objects("citation_section_number_parity_positioned") == ["1:even", "2:odd"]
    assert objects("citation_section_number_leading_digit_positioned") == ["1:1", "2:1"]
    assert objects("citation_section_number_trailing_two_digits_positioned") == [
        "1:96",
        "2:1",
    ]
    assert objects("citation_section_number_zero_digit_count") == ["0"]
    assert objects("citation_section_number_zero_digit_count_positioned") == [
        "1:0",
        "2:0",
    ]
    assert objects("citation_section_number_has_zero_digit") == ["false"]
    assert objects("citation_section_number_has_zero_digit_positioned") == [
        "1:false",
        "2:false",
    ]
    assert objects("citation_section_number_trailing_zero_count") == ["0"]
    assert objects("citation_section_number_trailing_zero_count_positioned") == [
        "1:0",
        "2:0",
    ]
    assert objects("citation_section_primary_number_parity") == ["even"]
    assert objects("citation_section_primary_number_leading_digit") == ["1"]
    assert objects("citation_section_primary_number_trailing_two_digits") == ["96"]
    assert objects("citation_section_primary_number_zero_digit_count") == ["0"]
    assert objects("citation_section_primary_number_has_zero_digit") == ["false"]
    assert objects("citation_section_primary_number_trailing_zero_count") == ["0"]
    assert objects("citation_section_terminal_number_parity") == ["odd"]
    assert objects("citation_section_terminal_number_leading_digit") == ["1"]
    assert objects("citation_section_terminal_number_trailing_two_digits") == ["1"]
    assert objects("citation_section_terminal_number_zero_digit_count") == ["0"]
    assert objects("citation_section_terminal_number_has_zero_digit") == ["false"]
    assert objects("citation_section_terminal_number_trailing_zero_count") == ["0"]

    assert objects("source_id_section_number_parity") == ["even", "odd"]
    assert objects("source_id_section_number_parity_positioned") == ["1:even", "2:odd"]
    assert objects("source_id_section_number_leading_digit_positioned") == ["1:1", "2:1"]
    assert objects("source_id_section_number_trailing_two_digits_positioned") == [
        "1:96",
        "2:1",
    ]
    assert objects("source_id_section_number_zero_digit_count") == ["0"]
    assert objects("source_id_section_number_zero_digit_count_positioned") == [
        "1:0",
        "2:0",
    ]
    assert objects("source_id_section_number_has_zero_digit") == ["false"]
    assert objects("source_id_section_number_has_zero_digit_positioned") == [
        "1:false",
        "2:false",
    ]
    assert objects("source_id_section_number_trailing_zero_count") == ["0"]
    assert objects("source_id_section_number_trailing_zero_count_positioned") == [
        "1:0",
        "2:0",
    ]
    assert objects("source_id_section_primary_number_parity") == ["even"]
    assert objects("source_id_section_primary_number_leading_digit") == ["1"]
    assert objects("source_id_section_primary_number_trailing_two_digits") == ["96"]
    assert objects("source_id_section_primary_number_zero_digit_count") == ["0"]
    assert objects("source_id_section_primary_number_has_zero_digit") == ["false"]
    assert objects("source_id_section_primary_number_trailing_zero_count") == ["0"]
    assert objects("source_id_section_terminal_number_parity") == ["odd"]
    assert objects("source_id_section_terminal_number_leading_digit") == ["1"]
    assert objects("source_id_section_terminal_number_trailing_two_digits") == ["1"]
    assert objects("source_id_section_terminal_number_zero_digit_count") == ["0"]
    assert objects("source_id_section_terminal_number_has_zero_digit") == ["false"]
    assert objects("source_id_section_terminal_number_trailing_zero_count") == ["0"]

    zero_digit_triples = modal_ir_to_flogic_triples(_zero_digit_signature_sample_document())

    def zero_digit_objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in zero_digit_triples
            if triple.get("predicate") == predicate
        ]

    assert zero_digit_objects("citation_title_number_zero_digit_count") == ["0"]
    assert zero_digit_objects("citation_title_number_has_zero_digit") == ["false"]
    assert zero_digit_objects("citation_title_number_trailing_zero_count") == ["0"]
    assert zero_digit_objects("citation_section_number_zero_digit_count") == ["1"]
    assert zero_digit_objects("citation_section_number_has_zero_digit") == ["true"]
    assert zero_digit_objects("citation_section_number_trailing_zero_count") == ["1"]
    assert zero_digit_objects("citation_section_number_zero_digit_count_positioned") == [
        "1:1"
    ]
    assert zero_digit_objects("citation_section_number_has_zero_digit_positioned") == [
        "1:true"
    ]
    assert zero_digit_objects("citation_section_number_trailing_zero_count_positioned") == [
        "1:1"
    ]
    assert zero_digit_objects("citation_section_primary_number_zero_digit_count") == ["1"]
    assert zero_digit_objects("citation_section_primary_number_has_zero_digit") == ["true"]
    assert zero_digit_objects("citation_section_primary_number_trailing_zero_count") == [
        "1"
    ]
    assert zero_digit_objects("source_id_section_number_zero_digit_count") == ["1"]
    assert zero_digit_objects("source_id_section_number_has_zero_digit") == ["true"]
    assert zero_digit_objects("source_id_section_number_trailing_zero_count") == ["1"]
    assert zero_digit_objects("source_id_section_primary_number_zero_digit_count") == [
        "1"
    ]
    assert zero_digit_objects("source_id_section_primary_number_has_zero_digit") == [
        "true"
    ]
    assert zero_digit_objects("source_id_section_primary_number_trailing_zero_count") == [
        "1"
    ]

    odd_title_triples = modal_ir_to_flogic_triples(_sample_document())

    def odd_title_objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in odd_title_triples
            if triple.get("predicate") == predicate
        ]

    assert odd_title_objects("citation_title_number_parity") == ["odd"]
    assert odd_title_objects("source_id_title_number_parity") == ["odd"]


def test_decode_modal_ir_document_emits_usc_section_marker_variant_slots() -> None:
    section_marker_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_section_marker_sample_document())
    )
    assert section_marker_slot_map["citation"] == ["2 U.S.C. §190l"]
    assert section_marker_slot_map["citation_canonical"] == ["2 U.S.C. 190l"]
    assert section_marker_slot_map["citation_section"] == ["190l"]
    assert section_marker_slot_map["citation_section_primary"] == ["190l"]
    assert section_marker_slot_map["citation_section_component_profile"] == [
        "single_alphanumeric"
    ]
    assert section_marker_slot_map["citation_section_has_delimiter"] == ["false"]
    assert section_marker_slot_map["citation_section_delimiter_count"] == ["0"]
    assert section_marker_slot_map["citation_section_primary_suffix"] == ["l"]
    assert section_marker_slot_map["citation_section_suffix_kind"] == ["alpha"]

    plural_marker_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_plural_section_marker_range_sample_document())
    )
    assert plural_marker_slot_map["citation"] == ["45 U.S.C. §§ 228a to 228c."]
    assert plural_marker_slot_map["citation_canonical"] == ["45 U.S.C. 228a to 228c"]
    assert plural_marker_slot_map["citation_section"] == ["228a to 228c"]
    assert plural_marker_slot_map["citation_section_range"] == ["228a to 228c"]
    assert plural_marker_slot_map["citation_section_range_start"] == ["228a"]
    assert plural_marker_slot_map["citation_section_range_end"] == ["228c"]
    assert plural_marker_slot_map["citation_section_range_connector"] == ["to"]
    assert plural_marker_slot_map["citation_section_trailing_punct"] == ["."]
    assert plural_marker_slot_map["citation_section_has_trailing_punct"] == ["true"]
    assert plural_marker_slot_map["citation_section_trailing_punct_count"] == ["1"]
    assert plural_marker_slot_map["citation_section_trailing_punct_kind"] == ["dot"]


def test_modal_ir_to_flogic_triples_emits_usc_section_marker_variant_slots() -> None:
    section_marker_triples = modal_ir_to_flogic_triples(_section_marker_sample_document())
    plural_marker_triples = modal_ir_to_flogic_triples(
        _plural_section_marker_range_sample_document()
    )

    def objects(triples: list[dict[str, str]], predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects(section_marker_triples, "citation") == ["2 U.S.C. §190l"]
    assert objects(section_marker_triples, "citation_canonical") == ["2 U.S.C. 190l"]
    assert objects(section_marker_triples, "citation_section") == ["190l"]
    assert objects(section_marker_triples, "citation_section_primary") == ["190l"]
    assert objects(section_marker_triples, "citation_section_component_profile") == [
        "single_alphanumeric"
    ]
    assert objects(section_marker_triples, "citation_section_has_delimiter") == ["false"]
    assert objects(section_marker_triples, "citation_section_delimiter_count") == ["0"]
    assert objects(section_marker_triples, "citation_section_primary_suffix") == ["l"]
    assert objects(section_marker_triples, "citation_section_suffix_kind") == ["alpha"]

    assert objects(plural_marker_triples, "citation") == ["45 U.S.C. §§ 228a to 228c."]
    assert objects(plural_marker_triples, "citation_canonical") == [
        "45 U.S.C. 228a to 228c"
    ]
    assert objects(plural_marker_triples, "citation_section") == ["228a to 228c"]
    assert objects(plural_marker_triples, "citation_section_range") == ["228a to 228c"]
    assert objects(plural_marker_triples, "citation_section_range_start") == ["228a"]
    assert objects(plural_marker_triples, "citation_section_range_end") == ["228c"]
    assert objects(plural_marker_triples, "citation_section_range_connector") == ["to"]
    assert objects(plural_marker_triples, "citation_section_trailing_punct") == ["."]
    assert objects(plural_marker_triples, "citation_section_has_trailing_punct") == [
        "true"
    ]
    assert objects(plural_marker_triples, "citation_section_trailing_punct_count") == [
        "1"
    ]
    assert objects(plural_marker_triples, "citation_section_trailing_punct_kind") == [
        "dot"
    ]


def test_decode_modal_ir_document_emits_section_heading_tail_for_coarse_fallback() -> None:
    decoded = decode_modal_ir_document(_coarse_heading_tail_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["fallback_rule"] == ["uscode_section_heading_coarse_v1"]
    assert slot_map["section_heading_tail"] == ["Student aid program improvements"]
    assert slot_map["fallback_surface_text"] == ["Student aid program improvements"]
    assert slot_map["section_heading_tail_token_count"] == ["4"]
    assert slot_map["section_heading_tail_token_suffix"] == ["improvements"]
    assert slot_map["fallback_surface_text_token_count"] == ["4"]
    assert slot_map["fallback_surface_text_token_suffix"] == ["improvements"]


def test_modal_ir_to_flogic_triples_emits_section_heading_tail_for_coarse_fallback() -> None:
    triples = modal_ir_to_flogic_triples(_coarse_heading_tail_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("fallback_rule") == ["uscode_section_heading_coarse_v1"]
    assert objects("section_heading_tail") == ["Student aid program improvements"]
    assert objects("fallback_surface_text") == ["Student aid program improvements"]
    assert objects("section_heading_tail_token_count") == ["4"]
    assert objects("section_heading_tail_token_suffix") == ["improvements"]
    assert objects("fallback_surface_text_token_count") == ["4"]
    assert objects("fallback_surface_text_token_suffix") == ["improvements"]


def test_decode_modal_ir_document_emits_citation_source_id_alignment_slots() -> None:
    aligned_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_sample_document())
    )
    mismatch_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_provenance_alignment_mismatch_sample_document())
    )

    assert aligned_slot_map["citation_source_id_alignment"] == ["exact_match"]
    assert aligned_slot_map["citation_source_id_title_match"] == ["true"]
    assert aligned_slot_map["citation_source_id_section_match"] == ["true"]
    assert aligned_slot_map["citation_source_id_title_section_key_match"] == ["true"]
    assert aligned_slot_map["citation_source_id_canonical_match"] == ["true"]

    assert mismatch_slot_map["citation_source_id_alignment"] == ["title_only_match"]
    assert mismatch_slot_map["citation_source_id_title_match"] == ["true"]
    assert mismatch_slot_map["citation_source_id_section_match"] == ["false"]
    assert mismatch_slot_map["citation_source_id_title_section_key_match"] == ["false"]
    assert mismatch_slot_map["citation_source_id_canonical_match"] == ["false"]


def test_modal_ir_to_flogic_triples_emits_citation_source_id_alignment_slots() -> None:
    aligned_triples = modal_ir_to_flogic_triples(_sample_document())
    mismatch_triples = modal_ir_to_flogic_triples(
        _provenance_alignment_mismatch_sample_document()
    )

    def objects(triples: list[dict[str, str]], predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects(aligned_triples, "citation_source_id_alignment") == ["exact_match"]
    assert objects(aligned_triples, "citation_source_id_title_match") == ["true"]
    assert objects(aligned_triples, "citation_source_id_section_match") == ["true"]
    assert objects(aligned_triples, "citation_source_id_title_section_key_match") == [
        "true"
    ]
    assert objects(aligned_triples, "citation_source_id_canonical_match") == ["true"]

    assert objects(mismatch_triples, "citation_source_id_alignment") == [
        "title_only_match"
    ]
    assert objects(mismatch_triples, "citation_source_id_title_match") == ["true"]
    assert objects(mismatch_triples, "citation_source_id_section_match") == ["false"]
    assert objects(
        mismatch_triples,
        "citation_source_id_title_section_key_match",
    ) == ["false"]
    assert objects(mismatch_triples, "citation_source_id_canonical_match") == ["false"]
