"""Regression tests for modal IR decompiler slot normalization."""

from __future__ import annotations

from dataclasses import replace

from ipfs_datasets_py.logic.modal import (
    DeterministicModalCompiler,
    ModalCompilerConfig,
    decode_modal_ir_document,
    decoded_modal_phrase_slot_text_map,
    modal_ir_to_flogic_triples,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIRFrame,
    ModalIRFrameLogic,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


def _predicate_values(sample_section: str, *, title: str) -> dict[str, list[str]]:
    sample = build_us_code_sample(
        title=title,
        section=sample_section,
        citation=f"{title} U.S.C. {sample_section}",
        text=f"Sec. {sample_section} - Administrative provisions.",
    )
    decoded = decode_modal_ir_document(sample.modal_ir)
    slot_map = decoded_modal_phrase_slot_text_map(decoded)
    predicate_values: dict[str, list[str]] = {}
    for triple in modal_ir_to_flogic_triples(sample.modal_ir):
        predicate = str(triple.get("predicate", "")).strip()
        value = str(triple.get("object", "")).strip()
        if not predicate or not value:
            continue
        values = predicate_values.setdefault(predicate, [])
        if value not in values:
            values.append(value)
    return {
        "citation_section_raw": slot_map.get("citation_section_raw", []),
        "citation_section_normalized": slot_map.get("citation_section_normalized", []),
        "citation_section_terminal": slot_map.get("citation_section_terminal", []),
        "citation_section_primary_equals_terminal": slot_map.get(
            "citation_section_primary_equals_terminal",
            [],
        ),
        "citation_section_primary_terminal_pair": slot_map.get(
            "citation_section_primary_terminal_pair",
            [],
        ),
        "source_id_section_raw": slot_map.get("source_id_section_raw", []),
        "source_id_section_normalized": slot_map.get(
            "source_id_section_normalized",
            [],
        ),
        "source_id_section_terminal": slot_map.get("source_id_section_terminal", []),
        "source_id_section_primary_equals_terminal": slot_map.get(
            "source_id_section_primary_equals_terminal",
            [],
        ),
        "source_id_section_primary_terminal_pair": slot_map.get(
            "source_id_section_primary_terminal_pair",
            [],
        ),
        "triple_citation_section_raw": predicate_values.get("citation_section_raw", []),
        "triple_citation_section_normalized": predicate_values.get(
            "citation_section_normalized",
            [],
        ),
        "triple_citation_section_terminal": predicate_values.get(
            "citation_section_terminal",
            [],
        ),
        "triple_citation_section_primary_equals_terminal": predicate_values.get(
            "citation_section_primary_equals_terminal",
            [],
        ),
        "triple_citation_section_primary_terminal_pair": predicate_values.get(
            "citation_section_primary_terminal_pair",
            [],
        ),
        "triple_source_id_section_raw": predicate_values.get("source_id_section_raw", []),
        "triple_source_id_section_normalized": predicate_values.get(
            "source_id_section_normalized",
            [],
        ),
        "triple_source_id_section_terminal": predicate_values.get(
            "source_id_section_terminal",
            [],
        ),
        "triple_source_id_section_primary_equals_terminal": predicate_values.get(
            "source_id_section_primary_equals_terminal",
            [],
        ),
        "triple_source_id_section_primary_terminal_pair": predicate_values.get(
            "source_id_section_primary_terminal_pair",
            [],
        ),
    }


def _slot_and_triple_values_for_predicate(
    sample_section: str,
    *,
    title: str,
    predicate: str,
) -> tuple[list[str], list[str]]:
    sample = build_us_code_sample(
        title=title,
        section=sample_section,
        citation=f"{title} U.S.C. {sample_section}",
        text=f"Sec. {sample_section} - Administrative provisions.",
    )
    decoded = decode_modal_ir_document(sample.modal_ir)
    slot_map = decoded_modal_phrase_slot_text_map(decoded)
    triple_values: list[str] = []
    for triple in modal_ir_to_flogic_triples(sample.modal_ir):
        if str(triple.get("predicate", "")).strip() != predicate:
            continue
        value = str(triple.get("object", "")).strip()
        if value and value not in triple_values:
            triple_values.append(value)
    return slot_map.get(predicate, []), triple_values


def test_modal_slots_emit_raw_and_normalized_section_values_for_trailing_punct() -> None:
    values = _predicate_values("1437q.", title="42")

    assert values["citation_section_raw"] == ["1437q."]
    assert values["citation_section_normalized"] == ["1437q"]
    assert values["citation_section_terminal"] == ["1437q"]
    assert values["citation_section_primary_equals_terminal"] == ["true"]
    assert values["citation_section_primary_terminal_pair"] == ["1437q|1437q"]
    assert values["source_id_section_raw"] == ["1437q."]
    assert values["source_id_section_normalized"] == ["1437q"]
    assert values["source_id_section_terminal"] == ["1437q"]
    assert values["source_id_section_primary_equals_terminal"] == ["true"]
    assert values["source_id_section_primary_terminal_pair"] == ["1437q|1437q"]

    assert values["triple_citation_section_raw"] == ["1437q."]
    assert values["triple_citation_section_normalized"] == ["1437q"]
    assert values["triple_citation_section_terminal"] == ["1437q"]
    assert values["triple_citation_section_primary_equals_terminal"] == ["true"]
    assert values["triple_citation_section_primary_terminal_pair"] == ["1437q|1437q"]
    assert values["triple_source_id_section_raw"] == ["1437q."]
    assert values["triple_source_id_section_normalized"] == ["1437q"]
    assert values["triple_source_id_section_terminal"] == ["1437q"]
    assert values["triple_source_id_section_primary_equals_terminal"] == ["true"]
    assert values["triple_source_id_section_primary_terminal_pair"] == ["1437q|1437q"]


def test_modal_slots_emit_raw_and_normalized_section_values_without_trailing_punct() -> None:
    values = _predicate_values("3902", title="38")

    assert values["citation_section_raw"] == ["3902"]
    assert values["citation_section_normalized"] == ["3902"]
    assert values["citation_section_terminal"] == ["3902"]
    assert values["citation_section_primary_equals_terminal"] == ["true"]
    assert values["citation_section_primary_terminal_pair"] == ["3902|3902"]
    assert values["source_id_section_raw"] == ["3902"]
    assert values["source_id_section_normalized"] == ["3902"]
    assert values["source_id_section_terminal"] == ["3902"]
    assert values["source_id_section_primary_equals_terminal"] == ["true"]
    assert values["source_id_section_primary_terminal_pair"] == ["3902|3902"]

    assert values["triple_citation_section_raw"] == ["3902"]
    assert values["triple_citation_section_normalized"] == ["3902"]
    assert values["triple_citation_section_terminal"] == ["3902"]
    assert values["triple_citation_section_primary_equals_terminal"] == ["true"]
    assert values["triple_citation_section_primary_terminal_pair"] == ["3902|3902"]
    assert values["triple_source_id_section_raw"] == ["3902"]
    assert values["triple_source_id_section_normalized"] == ["3902"]
    assert values["triple_source_id_section_terminal"] == ["3902"]
    assert values["triple_source_id_section_primary_equals_terminal"] == ["true"]
    assert values["triple_source_id_section_primary_terminal_pair"] == ["3902|3902"]


def test_modal_slots_emit_alignment_profile_slots_for_todo_cluster_citations() -> None:
    expected_by_section = {
        ("49", "47126."): (
            "raw_exact",
            "punct_exact",
            "exact_match_raw_exact_punct_exact",
        ),
        ("12", "639"): (
            "raw_exact",
            "punct_none",
            "exact_match_raw_exact_punct_none",
        ),
        ("22", "127"): (
            "raw_exact",
            "punct_none",
            "exact_match_raw_exact_punct_none",
        ),
        ("10", "10504"): (
            "raw_exact",
            "punct_none",
            "exact_match_raw_exact_punct_none",
        ),
    }
    predicates = (
        "citation_source_id_alignment_raw_relation",
        "citation_source_id_alignment_punctuation_relation",
        "citation_source_id_alignment_profile",
        "citation_source_id_alignment_profile_stem",
        "citation_source_id_alignment_profile_token_count",
    )

    for (title, section), (
        raw_relation,
        punctuation_relation,
        alignment_profile,
    ) in expected_by_section.items():
        expected = {
            "citation_source_id_alignment_raw_relation": [raw_relation],
            "citation_source_id_alignment_punctuation_relation": [punctuation_relation],
            "citation_source_id_alignment_profile": [alignment_profile],
            "citation_source_id_alignment_profile_stem": [alignment_profile],
            "citation_source_id_alignment_profile_token_count": ["6"],
        }
        for predicate in predicates:
            slot_values, triple_values = _slot_and_triple_values_for_predicate(
                section,
                title=title,
                predicate=predicate,
            )
            assert slot_values == expected[predicate]
            assert triple_values == expected[predicate]


def test_modal_slots_emit_numeric_magnitude_buckets_for_todo_cluster_sections() -> None:
    expected_by_section = {
        ("42", "665."): ("3_digit", "lt_1k"),
        ("48", "2146."): ("4_digit", "1k_to_9k"),
        ("42", "15113."): ("5_digit", "10k_to_99k"),
    }
    predicates = (
        "citation_section_primary_number_digit_count_bucket",
        "citation_section_primary_number_magnitude_bucket",
        "source_id_section_primary_number_digit_count_bucket",
        "source_id_section_primary_number_magnitude_bucket",
    )

    for (title, section), (digit_bucket, magnitude_bucket) in expected_by_section.items():
        expected = {
            "citation_section_primary_number_digit_count_bucket": [digit_bucket],
            "citation_section_primary_number_magnitude_bucket": [magnitude_bucket],
            "source_id_section_primary_number_digit_count_bucket": [digit_bucket],
            "source_id_section_primary_number_magnitude_bucket": [magnitude_bucket],
        }
        for predicate in predicates:
            slot_values, triple_values = _slot_and_triple_values_for_predicate(
                section,
                title=title,
                predicate=predicate,
            )
            assert slot_values == expected[predicate]
            assert triple_values == expected[predicate]


def test_modal_slots_emit_numeric_prefix_and_block_slots_for_todo_cluster_sections() -> None:
    expected_by_section = {
        ("28", "363"): ("36", "363", "3", "0"),
        ("7", "2143"): ("21", "214", "21", "2"),
        ("46", "31109."): ("31", "311", "311", "31"),
        ("25", "1300d-2"): ("13", "130", "13", "1"),
    }
    predicates = (
        "citation_section_primary_number_prefix_two_digits",
        "citation_section_primary_number_prefix_three_digits",
        "citation_section_primary_number_hundreds_block",
        "citation_section_primary_number_thousands_block",
        "source_id_section_primary_number_prefix_two_digits",
        "source_id_section_primary_number_prefix_three_digits",
        "source_id_section_primary_number_hundreds_block",
        "source_id_section_primary_number_thousands_block",
    )

    for (
        title,
        section,
    ), (
        prefix_two,
        prefix_three,
        hundreds_block,
        thousands_block,
    ) in expected_by_section.items():
        expected = {
            "citation_section_primary_number_prefix_two_digits": [prefix_two],
            "citation_section_primary_number_prefix_three_digits": [prefix_three],
            "citation_section_primary_number_hundreds_block": [hundreds_block],
            "citation_section_primary_number_thousands_block": [thousands_block],
            "source_id_section_primary_number_prefix_two_digits": [prefix_two],
            "source_id_section_primary_number_prefix_three_digits": [prefix_three],
            "source_id_section_primary_number_hundreds_block": [hundreds_block],
            "source_id_section_primary_number_thousands_block": [thousands_block],
        }
        for predicate in predicates:
            slot_values, triple_values = _slot_and_triple_values_for_predicate(
                section,
                title=title,
                predicate=predicate,
            )
            assert slot_values == expected[predicate]
            assert triple_values == expected[predicate]


def test_modal_slots_emit_alpha_repeat_shape_for_todo_cluster_suffix_sections() -> None:
    expected_by_section = {
        ("42", "300mm"): ("uniform_repeat", "2"),
        ("22", "283ff"): ("uniform_repeat", "2"),
        ("16", "21b"): ("single", "1"),
        ("20", "80p"): ("single", "1"),
    }
    predicates = (
        "citation_section_suffix_repeat_kind",
        "citation_section_suffix_max_run_length",
        "citation_section_primary_suffix_repeat_kind",
        "citation_section_primary_suffix_max_run_length",
        "source_id_section_suffix_repeat_kind",
        "source_id_section_suffix_max_run_length",
        "source_id_section_primary_suffix_repeat_kind",
        "source_id_section_primary_suffix_max_run_length",
    )

    for (title, section), (repeat_kind, max_run_length) in expected_by_section.items():
        expected = {
            "citation_section_suffix_repeat_kind": [repeat_kind],
            "citation_section_suffix_max_run_length": [max_run_length],
            "citation_section_primary_suffix_repeat_kind": [repeat_kind],
            "citation_section_primary_suffix_max_run_length": [max_run_length],
            "source_id_section_suffix_repeat_kind": [repeat_kind],
            "source_id_section_suffix_max_run_length": [max_run_length],
            "source_id_section_primary_suffix_repeat_kind": [repeat_kind],
            "source_id_section_primary_suffix_max_run_length": [max_run_length],
        }
        for predicate in predicates:
            slot_values, triple_values = _slot_and_triple_values_for_predicate(
                section,
                title=title,
                predicate=predicate,
            )
            assert slot_values == expected[predicate]
            assert triple_values == expected[predicate]


def test_modal_slots_emit_typed_title_section_coordinate_slots_for_todo_cluster_sections() -> None:
    expected_by_section = {
        ("42", "300gg"): {
            "section_normalized": "300gg",
            "has_mixed_token": "true",
            "mixed_token_count": "1",
            "alnum_segment_count": "3",
        },
        ("46", "7109."): {
            "section_normalized": "7109",
            "has_mixed_token": "false",
            "mixed_token_count": "0",
            "alnum_segment_count": "2",
        },
        ("43", "950."): {
            "section_normalized": "950",
            "has_mixed_token": "false",
            "mixed_token_count": "0",
            "alnum_segment_count": "2",
        },
        ("10", "2512"): {
            "section_normalized": "2512",
            "has_mixed_token": "false",
            "mixed_token_count": "0",
            "alnum_segment_count": "2",
        },
    }
    predicates = (
        "citation_title_section_key",
        "citation_title_section_key_token_count",
        "citation_title_section_key_token_prefix",
        "citation_title_section_key_token_suffix",
        "citation_title_section_key_stem",
        "citation_title_section_key_has_mixed_token",
        "citation_title_section_key_mixed_token_count",
        "citation_title_section_key_alnum_segment_count",
        "source_id_title_section_key",
        "source_id_title_section_key_token_count",
        "source_id_title_section_key_token_prefix",
        "source_id_title_section_key_token_suffix",
        "source_id_title_section_key_stem",
        "source_id_title_section_key_has_mixed_token",
        "source_id_title_section_key_mixed_token_count",
        "source_id_title_section_key_alnum_segment_count",
    )

    for (title, section), values in expected_by_section.items():
        section_normalized = values["section_normalized"]
        expected = {
            "citation_title_section_key": [f"{title}:{section_normalized}"],
            "citation_title_section_key_token_count": ["2"],
            "citation_title_section_key_token_prefix": [title],
            "citation_title_section_key_token_suffix": [section_normalized],
            "citation_title_section_key_stem": [f"{title}_{section_normalized}"],
            "citation_title_section_key_has_mixed_token": [values["has_mixed_token"]],
            "citation_title_section_key_mixed_token_count": [values["mixed_token_count"]],
            "citation_title_section_key_alnum_segment_count": [values["alnum_segment_count"]],
            "source_id_title_section_key": [f"{title}:{section_normalized}"],
            "source_id_title_section_key_token_count": ["2"],
            "source_id_title_section_key_token_prefix": [title],
            "source_id_title_section_key_token_suffix": [section_normalized],
            "source_id_title_section_key_stem": [f"{title}_{section_normalized}"],
            "source_id_title_section_key_has_mixed_token": [values["has_mixed_token"]],
            "source_id_title_section_key_mixed_token_count": [values["mixed_token_count"]],
            "source_id_title_section_key_alnum_segment_count": [values["alnum_segment_count"]],
        }
        for predicate in predicates:
            slot_values, triple_values = _slot_and_triple_values_for_predicate(
                section,
                title=title,
                predicate=predicate,
            )
            assert slot_values == expected[predicate]
            assert triple_values == expected[predicate]


def test_modal_slots_emit_title_section_span_signature_slots_for_todo_cluster_sections() -> None:
    expected_by_section = {
        ("43", "1."): {
            "span": "42",
            "digit_bucket": "2_digit",
            "magnitude_bucket": "lt_1k",
            "prefix_three_digits": "42",
            "has_zero_digit": "false",
        },
        ("49", "44114."): {
            "span": "44065",
            "digit_bucket": "5_digit",
            "magnitude_bucket": "10k_to_99k",
            "prefix_three_digits": "440",
            "has_zero_digit": "true",
        },
        ("2", "132a"): {
            "span": "130",
            "digit_bucket": "3_digit",
            "magnitude_bucket": "lt_1k",
            "prefix_three_digits": "130",
            "has_zero_digit": "true",
        },
    }
    predicates = (
        "citation_title_section_primary_number_span",
        "citation_title_section_primary_number_span_digit_count_bucket",
        "citation_title_section_primary_number_span_magnitude_bucket",
        "citation_title_section_primary_number_span_prefix_three_digits",
        "citation_title_section_primary_number_span_has_zero_digit",
        "citation_title_section_terminal_number_span",
        "citation_title_section_terminal_number_span_digit_count_bucket",
        "citation_title_section_terminal_number_span_magnitude_bucket",
        "citation_title_section_terminal_number_span_prefix_three_digits",
        "citation_title_section_terminal_number_span_has_zero_digit",
        "source_id_title_section_primary_number_span",
        "source_id_title_section_primary_number_span_digit_count_bucket",
        "source_id_title_section_primary_number_span_magnitude_bucket",
        "source_id_title_section_primary_number_span_prefix_three_digits",
        "source_id_title_section_primary_number_span_has_zero_digit",
        "source_id_title_section_terminal_number_span",
        "source_id_title_section_terminal_number_span_digit_count_bucket",
        "source_id_title_section_terminal_number_span_magnitude_bucket",
        "source_id_title_section_terminal_number_span_prefix_three_digits",
        "source_id_title_section_terminal_number_span_has_zero_digit",
    )

    for (title, section), values in expected_by_section.items():
        expected = {
            "citation_title_section_primary_number_span": [values["span"]],
            "citation_title_section_primary_number_span_digit_count_bucket": [
                values["digit_bucket"]
            ],
            "citation_title_section_primary_number_span_magnitude_bucket": [
                values["magnitude_bucket"]
            ],
            "citation_title_section_primary_number_span_prefix_three_digits": [
                values["prefix_three_digits"]
            ],
            "citation_title_section_primary_number_span_has_zero_digit": [
                values["has_zero_digit"]
            ],
            "citation_title_section_terminal_number_span": [values["span"]],
            "citation_title_section_terminal_number_span_digit_count_bucket": [
                values["digit_bucket"]
            ],
            "citation_title_section_terminal_number_span_magnitude_bucket": [
                values["magnitude_bucket"]
            ],
            "citation_title_section_terminal_number_span_prefix_three_digits": [
                values["prefix_three_digits"]
            ],
            "citation_title_section_terminal_number_span_has_zero_digit": [
                values["has_zero_digit"]
            ],
            "source_id_title_section_primary_number_span": [values["span"]],
            "source_id_title_section_primary_number_span_digit_count_bucket": [
                values["digit_bucket"]
            ],
            "source_id_title_section_primary_number_span_magnitude_bucket": [
                values["magnitude_bucket"]
            ],
            "source_id_title_section_primary_number_span_prefix_three_digits": [
                values["prefix_three_digits"]
            ],
            "source_id_title_section_primary_number_span_has_zero_digit": [
                values["has_zero_digit"]
            ],
            "source_id_title_section_terminal_number_span": [values["span"]],
            "source_id_title_section_terminal_number_span_digit_count_bucket": [
                values["digit_bucket"]
            ],
            "source_id_title_section_terminal_number_span_magnitude_bucket": [
                values["magnitude_bucket"]
            ],
            "source_id_title_section_terminal_number_span_prefix_three_digits": [
                values["prefix_three_digits"]
            ],
            "source_id_title_section_terminal_number_span_has_zero_digit": [
                values["has_zero_digit"]
            ],
        }
        for predicate in predicates:
            slot_values, triple_values = _slot_and_triple_values_for_predicate(
                section,
                title=title,
                predicate=predicate,
            )
            assert slot_values == expected[predicate]
            assert triple_values == expected[predicate]


def test_modal_ir_decompiler_emits_legal_action_semantic_atoms_for_packet_000122() -> None:
    text = (
        "The Secretary, acting through the Director, shall conduct local asthma "
        "surveillance activities to collect data on the prevalence of asthma. "
        "A master shall deliver to a seaman a full and true account at least "
        "48 hours before paying off or discharging the seaman."
    )
    second_start = text.index("A master")
    document = ModalIRDocument(
        document_id="us-code-packet-000122",
        source="42 U.S.C. 247b; 46 U.S.C. 10310",
        normalized_text=text,
        formulas=[
            ModalIRFormula(
                formula_id="f1",
                operator=ModalIROperator(
                    family="deontic",
                    system="KD",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(name="conduct"),
                provenance=ModalIRProvenance(
                    source_id="us-code-packet-000122",
                    start_char=0,
                    end_char=second_start - 1,
                    citation="42 U.S.C. 247b",
                ),
            ),
            ModalIRFormula(
                formula_id="f2",
                operator=ModalIROperator(
                    family="frame",
                    system="FLogic",
                    symbol="Frame",
                    label="frame",
                ),
                predicate=ModalIRPredicate(name="deliver"),
                provenance=ModalIRProvenance(
                    source_id="us-code-packet-000122",
                    start_char=second_start,
                    end_char=len(text),
                    citation="46 U.S.C. 10310",
                ),
            ),
        ],
    )

    decoded = decode_modal_ir_document(document)
    slot_map = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(document)
    triple_pairs = {
        (str(triple.get("predicate", "")), str(triple.get("object", "")))
        for triple in triples
    }

    assert "public_health_surveillance" in slot_map[
        "typed-decompiler-source-semantic-atom"
    ]
    assert "seaman_discharge" in slot_map["typed-decompiler-source-semantic-atom"]
    assert "wage_account_discharge" in slot_map[
        "typed-decompiler-source-semantic-atom"
    ]
    assert "deontic->conditional_normative" in slot_map[
        "typed-decompiler-target-reconstruction-pair"
    ]
    assert "frame->temporal" in slot_map["typed-decompiler-target-reconstruction-pair"]
    assert ("typed_decompiler_semantic_atom", "seaman_discharge") in triple_pairs
    assert (
        "typed_decompiler_family_pair_semantic_atom",
        "seaman_discharge:frame->temporal",
    ) in triple_pairs


def test_modal_slots_emit_terminal_and_profile_alignment_slots_for_todo_cluster_sections() -> None:
    expected_by_section = {
        ("50", "31 to 39."): {
            "terminal_suffix_pair": "none|none",
            "terminal_signature_pair": "N2|N2",
            "profile_pair": "range|range",
            "is_range_pair": "true|true",
        },
        ("50", "3352e."): {
            "terminal_suffix_pair": "e|e",
            "terminal_signature_pair": "N4A1|N4A1",
            "profile_pair": "single_alphanumeric|single_alphanumeric",
            "is_range_pair": "false|false",
        },
    }
    predicates = (
        "citation_source_id_section_terminal_number_relation",
        "citation_source_id_section_terminal_number_span",
        "citation_source_id_section_terminal_suffix_pair",
        "citation_source_id_section_terminal_suffix_match",
        "citation_source_id_section_terminal_suffix_presence_match",
        "citation_source_id_section_terminal_component_signature_pair",
        "citation_source_id_section_terminal_component_signature_match",
        "citation_source_id_section_component_profile_pair",
        "citation_source_id_section_component_profile_match",
        "citation_source_id_section_is_range_pair",
        "citation_source_id_section_is_range_match",
    )

    for (title, section), values in expected_by_section.items():
        expected = {
            "citation_source_id_section_terminal_number_relation": ["equal"],
            "citation_source_id_section_terminal_number_span": ["0"],
            "citation_source_id_section_terminal_suffix_pair": [values["terminal_suffix_pair"]],
            "citation_source_id_section_terminal_suffix_match": ["true"],
            "citation_source_id_section_terminal_suffix_presence_match": ["true"],
            "citation_source_id_section_terminal_component_signature_pair": [
                values["terminal_signature_pair"]
            ],
            "citation_source_id_section_terminal_component_signature_match": ["true"],
            "citation_source_id_section_component_profile_pair": [values["profile_pair"]],
            "citation_source_id_section_component_profile_match": ["true"],
            "citation_source_id_section_is_range_pair": [values["is_range_pair"]],
            "citation_source_id_section_is_range_match": ["true"],
        }
        for predicate in predicates:
            slot_values, triple_values = _slot_and_triple_values_for_predicate(
                section,
                title=title,
                predicate=predicate,
            )
            assert slot_values == expected[predicate]
            assert triple_values == expected[predicate]


def test_modal_ir_decompiler_emits_deontic_selected_frame_grounding_slots() -> None:
    document = ModalIRDocument(
        document_id="us-code-36-150404-32d16ea28c8d2940",
        source="36 U.S.C. 150404",
        normalized_text=(
            "The corporation may participate in patriotic and national "
            "observances, ceremonies, and organizations."
        ),
        formulas=[
            ModalIRFormula(
                formula_id="f1",
                operator=ModalIROperator(
                    family="deontic",
                    system="KD",
                    symbol="P",
                    label="permission",
                ),
                predicate=ModalIRPredicate(
                    name="participate",
                    arguments=["corporation", "patriotic observances"],
                ),
                provenance=ModalIRProvenance(
                    source_id="us-code-36-150404-32d16ea28c8d2940",
                    start_char=0,
                    end_char=99,
                    citation="36 U.S.C. 150404",
                ),
            )
        ],
        frame_candidates=[
            ModalIRFrame(
                frame_id="patriotic_observance",
                score=1.0,
                matched_terms=[
                    "patriotic",
                    "national observances",
                    "ceremonies",
                    "organizations",
                ],
            )
        ],
        frame_logic=ModalIRFrameLogic(selected_frame="patriotic_observance"),
        metadata={"modal_family_counts": {"deontic": 1}},
    )

    decoded = decode_modal_ir_document(document)
    slot_map = decoded_modal_phrase_slot_text_map(decoded)
    triple_values: dict[str, list[str]] = {}
    for triple in modal_ir_to_flogic_triples(document):
        predicate = str(triple.get("predicate", "")).strip()
        value = str(triple.get("object", "")).strip()
        if predicate.startswith("frame_grounding") and value:
            triple_values.setdefault(predicate, []).append(value)

    assert slot_map["selected_ontology_frame"] == ["patriotic_observance"]
    assert slot_map["frame_grounding_modal_family"] == ["deontic"]
    assert slot_map["frame_grounding_candidate_count"] == ["1"]
    assert slot_map["frame_grounding_profile"] == triple_values["frame_grounding_profile"]
    assert (
        slot_map["frame_grounding_selected_term_count"]
        == triple_values["frame_grounding_selected_term_count"]
    )
    assert (
        slot_map["frame_grounding_family_profile_deontic"]
        == triple_values["frame_grounding_family_profile_deontic"]
    )


def test_modal_slots_emit_primary_terminal_number_distance_profiles() -> None:
    expected_by_section = {
        ("42", "18791."): ("equal_lt_1k", "1k"),
        ("50", "31 to 39."): ("ascending_lt_1k", "1k"),
    }
    predicates = (
        "citation_section_primary_terminal_number_distance_profile",
        "citation_section_primary_terminal_number_distance_profile_token_suffix",
        "citation_section_primary_terminal_number_span_digit_count_bucket",
        "citation_section_primary_terminal_number_span_magnitude_bucket",
        "source_id_section_primary_terminal_number_distance_profile",
        "source_id_section_primary_terminal_number_distance_profile_token_suffix",
        "source_id_section_primary_terminal_number_span_digit_count_bucket",
        "source_id_section_primary_terminal_number_span_magnitude_bucket",
    )

    for (title, section), (distance_profile, token_suffix) in expected_by_section.items():
        expected = {
            "citation_section_primary_terminal_number_distance_profile": [
                distance_profile
            ],
            "citation_section_primary_terminal_number_distance_profile_token_suffix": [
                token_suffix
            ],
            "citation_section_primary_terminal_number_span_digit_count_bucket": [
                "1_digit"
            ],
            "citation_section_primary_terminal_number_span_magnitude_bucket": ["lt_1k"],
            "source_id_section_primary_terminal_number_distance_profile": [
                distance_profile
            ],
            "source_id_section_primary_terminal_number_distance_profile_token_suffix": [
                token_suffix
            ],
            "source_id_section_primary_terminal_number_span_digit_count_bucket": [
                "1_digit"
            ],
            "source_id_section_primary_terminal_number_span_magnitude_bucket": ["lt_1k"],
        }
        for predicate in predicates:
            slot_values, triple_values = _slot_and_triple_values_for_predicate(
                section,
                title=title,
                predicate=predicate,
            )
            assert slot_values == expected[predicate]
            assert triple_values == expected[predicate]


def test_modal_slots_emit_range_number_distance_profiles_for_range_sections() -> None:
    predicates = (
        "citation_section_range_number_distance_profile",
        "citation_section_range_number_distance_profile_token_suffix",
        "citation_section_range_number_span_digit_count_bucket",
        "citation_section_range_number_span_magnitude_bucket",
        "source_id_section_range_number_distance_profile",
        "source_id_section_range_number_distance_profile_token_suffix",
        "source_id_section_range_number_span_digit_count_bucket",
        "source_id_section_range_number_span_magnitude_bucket",
    )
    expected = {
        "citation_section_range_number_distance_profile": ["ascending_lt_1k"],
        "citation_section_range_number_distance_profile_token_suffix": ["1k"],
        "citation_section_range_number_span_digit_count_bucket": ["1_digit"],
        "citation_section_range_number_span_magnitude_bucket": ["lt_1k"],
        "source_id_section_range_number_distance_profile": ["ascending_lt_1k"],
        "source_id_section_range_number_distance_profile_token_suffix": ["1k"],
        "source_id_section_range_number_span_digit_count_bucket": ["1_digit"],
        "source_id_section_range_number_span_magnitude_bucket": ["lt_1k"],
    }

    for predicate in predicates:
        slot_values, triple_values = _slot_and_triple_values_for_predicate(
            "31 to 39.",
            title="50",
            predicate=predicate,
        )
        assert slot_values == expected[predicate]
        assert triple_values == expected[predicate]


def test_modal_slots_compact_status_surface_text_when_us_abbreviation_truncates_span() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    compiled = compiler.compile(
        "Sec. 606 - Transferred From the U.S. Government Publishing Office.",
        document_id="us-code-8-606-cdf17e327d28e2de",
        citation="8 U.S.C. 606",
        source="us_code",
    )

    decoded = decode_modal_ir_document(compiled.modal_ir)
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    triple_values: list[str] = []
    for triple in modal_ir_to_flogic_triples(compiled.modal_ir):
        if str(triple.get("predicate", "")).strip() != "fallback_surface_text":
            continue
        value = str(triple.get("object", "")).strip()
        if value and value not in triple_values:
            triple_values.append(value)

    assert slot_map["fallback_rule"] == ["uscode_transferred_heading_v1"]
    assert slot_map["status_keyword"] == ["transferred"]
    assert slot_map["fallback_surface_text"] == ["Transferred"]
    assert triple_values == ["Transferred"]


def test_modal_slots_emit_canonical_section_style_alignment_slots() -> None:
    expected_by_section = {
        ("42", "1962d"): "single_alphanumeric_alpha_lower_clean",
        ("26", "7520"): "single_numeric_none_none_clean",
        ("51", "40504."): "single_numeric_none_none_trailing_punct",
    }

    for (title, section), canonical_style in expected_by_section.items():
        for predicate in (
            "citation_section_style_canonical",
            "source_id_section_style_canonical",
        ):
            slot_values, triple_values = _slot_and_triple_values_for_predicate(
                section,
                title=title,
                predicate=predicate,
            )
            assert slot_values == [canonical_style]
            assert triple_values == [canonical_style]
        for predicate in (
            "citation_section_style_canonical_alnum_segment_kind_positioned",
            "source_id_section_style_canonical_alnum_segment_kind_positioned",
        ):
            slot_values, triple_values = _slot_and_triple_values_for_predicate(
                section,
                title=title,
                predicate=predicate,
            )
            assert "4:alpha" in slot_values
            assert "4:alpha" in triple_values
        pair_values, pair_triple_values = _slot_and_triple_values_for_predicate(
            section,
            title=title,
            predicate="citation_source_id_section_style_canonical_pair",
        )
        assert pair_values == [f"{canonical_style}|{canonical_style}"]
        assert pair_triple_values == [f"{canonical_style}|{canonical_style}"]
        match_values, match_triple_values = _slot_and_triple_values_for_predicate(
            section,
            title=title,
            predicate="citation_source_id_section_style_canonical_match",
        )
        assert match_values == ["true"]
        assert match_triple_values == ["true"]


def test_modal_slots_derive_modal_operator_label_and_signature_for_temporal_next() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    compiled = compiler.compile(
        "In the next fiscal year, the Administrator shall apply reporting standards.",
        document_id="us-code-26-7520-operator-label-fallback",
        citation="26 U.S.C. 7520",
        source="us_code",
    )
    temporal_formula = next(
        (formula for formula in compiled.modal_ir.formulas if formula.operator.symbol == "X"),
        None,
    )
    assert temporal_formula is not None
    patched_modal_ir = replace(
        compiled.modal_ir,
        formulas=[
            replace(
                formula,
                operator=replace(formula.operator, label=""),
            )
            if formula.formula_id == temporal_formula.formula_id
            else formula
            for formula in compiled.modal_ir.formulas
        ],
    )

    decoded = decode_modal_ir_document(patched_modal_ir)
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert "next" in slot_map["modal_operator_label"]
    assert "temporal:X:next" in slot_map["modal_operator_signature"]
    assert "next" in slot_map["modal_operator_label_token"]
    assert "temporal_x_next" in slot_map["modal_operator_signature_stem"]

    triple_values: dict[str, list[str]] = {}
    for triple in modal_ir_to_flogic_triples(patched_modal_ir):
        predicate = str(triple.get("predicate", "")).strip()
        value = str(triple.get("object", "")).strip()
        if not predicate or not value:
            continue
        values = triple_values.setdefault(predicate, [])
        if value not in values:
            values.append(value)

    assert "next" in triple_values["modal_operator_label"]
    assert "temporal:X:next" in triple_values["modal_operator_signature"]
    assert "next" in triple_values["modal_operator_label_token"]
    assert "temporal_x_next" in triple_values["modal_operator_signature_stem"]


def test_modal_decompiler_refines_condition_scope_bridge_slots() -> None:
    formula = ModalIRFormula(
        formula_id="f_condition_bridge",
        operator=ModalIROperator(
            family="deontic",
            system="D",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="provide_notice", arguments=[]),
        provenance=ModalIRProvenance(
            source_id="condition-bridge-doc",
            start_char=0,
            end_char=64,
            citation="5 U.S.C. 552",
        ),
        conditions=["not later than the hearing date"],
    )
    document = ModalIRDocument(
        document_id="condition-bridge-doc",
        source="us_code",
        normalized_text="Not later than the hearing date, the agency shall provide notice.",
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert "o_to_o" in slot_texts["condition_scope_refined_modal_operator_pair_key"]
    assert "not_later_than:deadline" in slot_texts[
        "condition_scope_refined_temporal_bridge_context"
    ]
    assert "condition:not_later_than:deadline" in slot_texts[
        "refined_temporal_bridge_context"
    ]


def test_modal_decompiler_refines_only_after_condition_as_deontic_temporal_scope() -> None:
    formula = ModalIRFormula(
        formula_id="f_only_after_bridge",
        operator=ModalIROperator(
            family="deontic",
            system="D",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="implement_flood_mapping_program", arguments=[]),
        provenance=ModalIRProvenance(
            source_id="only-after-bridge-doc",
            start_char=0,
            end_char=119,
            citation="42 U.S.C. 4101d",
        ),
        conditions=["only after review by the Technical Mapping Advisory Council"],
        metadata={"cue": "shall"},
    )
    document = ModalIRDocument(
        document_id="only-after-bridge-doc",
        source="us_code",
        normalized_text=(
            "The Administrator shall implement a flood mapping program only after "
            "review by the Technical Mapping Advisory Council."
        ),
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert slot_texts["condition_prefix_key"] == ["only_after"]
    assert slot_texts["condition_prefix_temporal_relation"] == ["after"]
    assert "temporal:X:only_after" in slot_texts["condition_modal_bridge_signature"]
    assert "temporal:X:only_after" in slot_texts[
        "condition_scope_refined_modal_bridge_signature"
    ]
    assert "deontic->temporal" in slot_texts[
        "condition_scope_refined_temporal_bridge_family_pair"
    ]
    assert "deontic_temporal" in slot_texts[
        "condition_scope_refined_temporal_bridge_family_pair"
    ]
    assert "o_to_f" in slot_texts[
        "condition_scope_refined_temporal_bridge_operator_pair_key"
    ]
    assert "only_after:after" in slot_texts[
        "condition_scope_refined_temporal_bridge_context"
    ]
    assert "condition:only_after:after" in slot_texts[
        "refined_temporal_bridge_context"
    ]


def test_modal_decompiler_emits_condition_role_slot_pair_prototypes() -> None:
    formula = ModalIRFormula(
        formula_id="f_condition_role_slot_pair",
        operator=ModalIROperator(
            family="deontic",
            system="D",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="provide_emergency_notice", arguments=[]),
        provenance=ModalIRProvenance(
            source_id="condition-role-slot-pair-doc",
            start_char=0,
            end_char=103,
            citation="29 U.S.C. 179",
        ),
        conditions=["not later than the Board shall file a petition"],
        metadata={"cue": "shall"},
    )
    document = ModalIRDocument(
        document_id="condition-role-slot-pair-doc",
        source="us_code",
        normalized_text=(
            "Not later than the Board shall file a petition, "
            "the court shall provide emergency notice."
        ),
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))
    semantic_slots = set(slot_texts["semantic_slot_prototype"])
    family_slots = set(slot_texts["family_semantic_slot_prototype"])
    legal_ir_slots = set(slot_texts["family_semantic_slot_legal_ir_view_prototype"])

    role_slot = "slot-pair:conditions:0|predicate-role:subject+action+object+temporal"

    assert role_slot in semantic_slots
    assert f"deontic||{role_slot}" in family_slots
    assert f"temporal||{role_slot}" in family_slots
    assert f"deontic||{role_slot}||deontic.ir" in legal_ir_slots
    assert f"temporal||{role_slot}||TDFOL.prover" in legal_ir_slots
    assert (
        "temporal||slot-pair:conditions:0|predicate-role:subject:board||deontic.ir"
        in legal_ir_slots
    )
    assert (
        "temporal||slot-pair:conditions:0|predicate-role:action:file||deontic.ir"
        in legal_ir_slots
    )


def test_modal_decompiler_projects_condition_scope_typed_roles_to_triples() -> None:
    formula = ModalIRFormula(
        formula_id="f_condition_typed_roles",
        operator=ModalIROperator(
            family="deontic",
            system="D",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_certification_records", arguments=[]),
        provenance=ModalIRProvenance(
            source_id="condition-typed-role-doc",
            start_char=0,
            end_char=96,
            citation="7 U.S.C. 6503",
        ),
        conditions=["if the Secretary shall establish a national organic program"],
    )
    document = ModalIRDocument(
        document_id="condition-typed-role-doc",
        source="us_code",
        normalized_text=(
            "If the Secretary shall establish a national organic program, "
            "certification records shall be maintained."
        ),
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))
    triple_values: dict[str, list[str]] = {}
    for triple in modal_ir_to_flogic_triples(document):
        predicate = str(triple.get("predicate", "")).strip()
        value = str(triple.get("object", "")).strip()
        if not predicate or not value:
            continue
        values = triple_values.setdefault(predicate, [])
        if value not in values:
            values.append(value)

    assert "subject" in slot_texts["condition_scope_typed_decompiler_role"]
    assert "secretary" in slot_texts["condition_scope_typed_decompiler_subject"]
    assert "establish" in slot_texts["condition_scope_typed_decompiler_action"]
    assert "national_organic_program" in slot_texts[
        "condition_scope_typed_decompiler_object"
    ]
    assert "deontic:subject+action+object" in slot_texts[
        "condition_scope_typed_decompiler_family_role_signature"
    ]
    assert "deontic->deontic:subject+action+object" in slot_texts[
        "condition_scope_typed_decompiler_family_pair_bridge"
    ]

    assert triple_values["condition_scope_typed_decompiler_role"] == [
        "subject",
        "action",
        "object",
    ]
    assert triple_values["condition_scope_typed_decompiler_subject"] == ["secretary"]
    assert triple_values["condition_scope_typed_decompiler_action"] == ["establish"]
    assert triple_values["condition_scope_typed_decompiler_object"] == [
        "national_organic_program"
    ]
    assert "deontic:subject+action+object" in triple_values[
        "condition_scope_typed_decompiler_family_role_signature"
    ]
    assert "deontic->deontic:subject+action+object" in triple_values[
        "condition_scope_typed_decompiler_family_pair_bridge"
    ]


def test_modal_decompiler_refines_deontic_exception_negative_scope_slots() -> None:
    formula = ModalIRFormula(
        formula_id="f_exception_negative",
        operator=ModalIROperator(
            family="deontic",
            system="D",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="disclose_records", arguments=[]),
        provenance=ModalIRProvenance(
            source_id="exception-negative-doc",
            start_char=0,
            end_char=56,
            citation="22 U.S.C. 282k",
        ),
        exceptions=["except as authorized"],
        metadata={"polarity": "negative_scope"},
    )
    document = ModalIRDocument(
        document_id="exception-negative-doc",
        source="us_code",
        normalized_text="The agency may not disclose records except as authorized.",
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert "o_to_o" in slot_texts["exception_scope_refined_modal_operator_pair_key"]
    assert "obligation:negative_scope:excepted" in slot_texts[
        "compiler_contract_force_polarity_exception"
    ]
    assert "mandatory:excepted" in slot_texts["normative_polarity_scope"]
    assert "negative_scope:excepted" in slot_texts["normative_polarity_scope"]


def test_modal_decompiler_refines_uscode_heading_fallback_typed_ir_slots() -> None:
    formula = ModalIRFormula(
        formula_id="f_heading_fallback_frame",
        operator=ModalIROperator(
            family="frame",
            system="Frame",
            symbol="Frame",
            label="frame",
        ),
        predicate=ModalIRPredicate(name="organization", role="clause"),
        provenance=ModalIRProvenance(
            source_id="us-code-42-3058c-heading-fallback",
            start_char=0,
            end_char=96,
            citation="42 U.S.C. 3058c",
        ),
        metadata={
            "cue": "__uscode_section_heading_fallback__",
            "fallback_rule": "uscode_section_heading_v1",
        },
    )
    document = ModalIRDocument(
        document_id="us-code-42-3058c-heading-fallback",
        source="us_code",
        normalized_text=(
            "§3058c. Organization In order for a State to be eligible to "
            "receive allotments under this part, the State shall demonstrate "
            "eligibility."
        ),
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert "uscode_section_heading_fallback" in slot_texts[
        "typed_ir_refined_modal_cue"
    ]
    assert "frame->conditional_normative:uscode_section_heading_fallback" in slot_texts[
        "typed_ir_refined_modal_pair_cue"
    ]
    assert "frame->deontic:uscode_section_heading_fallback" in slot_texts[
        "typed_ir_refined_modal_pair_cue"
    ]
    assert "frame->temporal:uscode_section_heading_fallback" in slot_texts[
        "typed_ir_refined_modal_pair_cue"
    ]


def test_modal_decompiler_refines_frame_status_heading_typed_ir_slots() -> None:
    formula = ModalIRFormula(
        formula_id="f_renumbered_heading_frame",
        operator=ModalIROperator(
            family="frame",
            system="Frame",
            symbol="Frame",
            label="frame",
        ),
        predicate=ModalIRPredicate(name="renumbered_heading", role="heading"),
        provenance=ModalIRProvenance(
            source_id="us-code-10-2417-c1989383090125cf",
            start_char=0,
            end_char=56,
            citation="10 U.S.C. 2417",
        ),
    )
    document = ModalIRDocument(
        document_id="us-code-10-2417-c1989383090125cf",
        source="us_code",
        normalized_text="Sec. 2417 - Renumbered §4961 From the U.S. Government Publishing Office.",
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert "renumbered" in slot_texts["typed_ir_refined_modal_cue"]
    assert "frame->deontic:renumbered" in slot_texts[
        "typed_ir_refined_modal_pair_cue"
    ]
    assert "frame->temporal:renumbered" in slot_texts[
        "typed_ir_refined_modal_pair_cue"
    ]
    assert "frame_to_o" in slot_texts["typed_ir_refined_modal_operator_pair_key"]


def test_modal_decompiler_uses_status_atoms_as_target_reconstruction_cues() -> None:
    text = (
        "Sec. 1180 - Transferred From the U.S. Government Publishing Office. "
        "Editorial Notes Codification Section 1180 was transferred to section "
        "290aa-5 of Title 42."
    )
    formula = ModalIRFormula(
        formula_id="f_transferred_heading_frame",
        operator=ModalIROperator(
            family="frame",
            system="Frame",
            symbol="Frame",
            label="frame",
        ),
        predicate=ModalIRPredicate(name="transferred_heading", role="heading"),
        provenance=ModalIRProvenance(
            source_id="us-code-21-1180-06cb70a4aa076ffd",
            start_char=0,
            end_char=len(text),
            citation="21 U.S.C. 1180",
        ),
        metadata={"fallback_rule": "uscode_editorial_status_heading_v1"},
    )
    document = ModalIRDocument(
        document_id="us-code-21-1180-06cb70a4aa076ffd",
        source="us_code",
        normalized_text=text,
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert "transferred" in slot_texts["typed-decompiler-target-semantic-atom"]
    assert "transferred:frame->temporal" in slot_texts[
        "typed-decompiler-target-semantic-family-pair"
    ]
    assert "frame->temporal:transferred" in slot_texts[
        "typed-decompiler-target-reconstruction-cue"
    ]
    assert "frame->conditional_normative:transferred" in slot_texts[
        "typed-decompiler-target-reconstruction-cue"
    ]


def test_modal_decompiler_uses_omitted_status_atom_for_deontic_reconstruction_cue() -> None:
    text = (
        "Sec. 752 - Omitted From the U.S. Government Publishing Office. "
        "Section was omitted as obsolete."
    )
    formula = ModalIRFormula(
        formula_id="f_omitted_heading_frame",
        operator=ModalIROperator(
            family="frame",
            system="Frame",
            symbol="Frame",
            label="frame",
        ),
        predicate=ModalIRPredicate(name="omitted_heading", role="heading"),
        provenance=ModalIRProvenance(
            source_id="us-code-25-752-715e6f2da21142e8",
            start_char=0,
            end_char=len(text),
            citation="25 U.S.C. 752",
        ),
        metadata={"fallback_rule": "uscode_editorial_status_heading_v1"},
    )
    document = ModalIRDocument(
        document_id="us-code-25-752-715e6f2da21142e8",
        source="us_code",
        normalized_text=text,
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert "omitted" in slot_texts["typed-decompiler-target-semantic-atom"]
    assert "omitted:frame->deontic" in slot_texts[
        "typed-decompiler-target-semantic-family-pair"
    ]
    assert "frame->deontic:omitted" in slot_texts[
        "typed-decompiler-target-reconstruction-cue"
    ]
    assert "frame->conditional_normative:omitted" in slot_texts[
        "typed-decompiler-target-reconstruction-cue"
    ]


def test_modal_decompiler_refines_frame_statutory_deontic_temporal_slots() -> None:
    text = (
        "The authority under this section shall apply to agricultural exports "
        "after the effective date."
    )
    formula = ModalIRFormula(
        formula_id="f_frame_statutory_deontic_temporal",
        operator=ModalIROperator(
            family="frame",
            system="Frame",
            symbol="Frame",
            label="frame",
        ),
        predicate=ModalIRPredicate(name="agricultural_exports", role="clause"),
        provenance=ModalIRProvenance(
            source_id="us-code-19-2466-aa56495a0897d693",
            start_char=0,
            end_char=len(text),
            citation="19 U.S.C. 2466",
        ),
    )
    document = ModalIRDocument(
        document_id="us-code-19-2466-aa56495a0897d693",
        source="us_code",
        normalized_text=text,
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert "shall" in slot_texts["typed_ir_refined_modal_cue"]
    assert "authority" in slot_texts["typed_ir_refined_modal_cue"]
    assert "section" in slot_texts["typed_ir_refined_modal_cue"]
    assert "frame->deontic:shall" in slot_texts["typed_ir_refined_modal_pair_cue"]
    assert "frame->deontic:authority" in slot_texts[
        "typed_ir_refined_modal_pair_cue"
    ]
    assert "frame->temporal:section" in slot_texts[
        "typed_ir_refined_modal_pair_cue"
    ]


def test_modal_decompiler_adds_bounded_source_semantic_summary_for_long_uscode_spans() -> None:
    text = (
        "§18726. Savings provision Nothing in this part affects the authority, "
        "existing on the day before November 15, 2021, of any other Federal "
        "department or agency, including the authority provided to the Secretary "
        "of Homeland Security. Editorial Notes References in Text The Homeland "
        "Security Act of 2002 is classified generally to Title 6."
    )
    formula = ModalIRFormula(
        formula_id="f_savings_provision",
        operator=ModalIROperator(
            family="frame",
            system="Frame",
            symbol="Frame",
            label="frame",
        ),
        predicate=ModalIRPredicate(name="savings_provision", role="clause"),
        provenance=ModalIRProvenance(
            source_id="us-code-42-18726-summary",
            start_char=0,
            end_char=len(text),
            citation="42 U.S.C. 18726.",
        ),
    )
    document = ModalIRDocument(
        document_id="us-code-42-18726-summary",
        source="us_code",
        normalized_text=text,
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    summaries = slot_texts["typed_ir_semantic_summary"]
    assert any("Savings provision Nothing in this part affects" in item for item in summaries)
    assert all("Editorial Notes" not in item for item in summaries)
    assert all("References in Text" not in item for item in summaries)


def test_modal_decompiler_projects_source_role_target_family_slots() -> None:
    formula = ModalIRFormula(
        formula_id="f_frame_role_target",
        operator=ModalIROperator(
            family="frame",
            system="Frame",
            symbol="Frame",
            label="frame",
        ),
        predicate=ModalIRPredicate(name="care_supervision", role="clause"),
        provenance=ModalIRProvenance(
            source_id="us-code-16-446-role-target",
            start_char=0,
            end_char=78,
            citation="16 U.S.C. 446",
        ),
        metadata={"cue": "__uscode_section_heading_fallback__"},
    )
    document = ModalIRDocument(
        document_id="us-code-16-446-role-target",
        source="us_code",
        normalized_text=(
            "Lands under the supervision or control of the Secretary are "
            "maintained for care and protection."
        ),
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert "supervision:deontic" in slot_texts["source_action_target_family"]
    assert "control:deontic" in slot_texts["source_object_target_family"]
    assert (
        "predicate-argument:source-action-target-family:supervision:deontic"
        in slot_texts["predicate_argument_feature"]
    )
    assert (
        "decompiler-plan:source-object-target-role:control:temporal:clause"
        in slot_texts["source_role_decompiler_plan"]
    )
    assert (
        "predicate-argument:source-action-source-target-family:supervision:frame->deontic"
        in slot_texts["predicate_argument_feature"]
    )
    assert (
        "decompiler-plan:source-action-family-pair-key:supervision:frame_temporal"
        in slot_texts["source_role_decompiler_plan"]
    )


def test_modal_decompiler_refines_packet_003430_frame_target_pairs() -> None:
    text = (
        "The Secretary may determine whether funding agreements provide "
        "adequate compliance examinations under this chapter."
    )
    formula = ModalIRFormula(
        formula_id="f_packet_003430_frame_pairs",
        operator=ModalIROperator(
            family="frame",
            system="FRAME_BM25",
            symbol="Frame",
            label="ontology_frame",
        ),
        predicate=ModalIRPredicate(name="funding_agreement_review", role="clause"),
        provenance=ModalIRProvenance(
            source_id="us-code-20-2102-packet-003430",
            start_char=0,
            end_char=len(text),
            citation="20 U.S.C. 2102",
        ),
        conditions=["under this chapter"],
        metadata={"cue": "may"},
    )
    document = ModalIRDocument(
        document_id="packet-003430-frame-target-pairs",
        source="us_code",
        normalized_text=text,
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))
    family_pairs = set(slot_texts["typed_decompiler_family_pair"])
    legal_ir_slots = set(slot_texts["family_semantic_slot_legal_ir_view_prototype"])

    assert {
        "frame->deontic",
        "frame->doxastic",
        "frame->frame",
    }.issubset(family_pairs)
    assert "Frame->O" in slot_texts["typed_decompiler_operator_pair"]
    assert "Frame->B" in slot_texts["typed_decompiler_operator_pair"]
    assert (
        "frame->doxastic||deontic.ir"
        in slot_texts["typed_decompiler_family_pair_view_contract"]
    )
    assert (
        "doxastic||slot:typed-decompiler-view-contract:"
        "frame:frame_doxastic||deontic.ir"
        in legal_ir_slots
    )


def test_modal_decompiler_refines_frame_epistemic_nominal_cues() -> None:
    text = (
        "The Secretary's determination and findings for the park boundary "
        "shall be published with supporting records."
    )
    formula = ModalIRFormula(
        formula_id="f_packet_000909_frame_epistemic",
        operator=ModalIROperator(
            family="frame",
            system="FRAME_BM25",
            symbol="Frame",
            label="ontology_frame",
        ),
        predicate=ModalIRPredicate(name="park_boundary_determination", role="clause"),
        provenance=ModalIRProvenance(
            source_id="us-code-16-410ccc-packet-000909",
            start_char=0,
            end_char=len(text),
            citation="16 U.S.C. 410ccc",
        ),
        metadata={"cue": "__uscode_section_heading_fallback__"},
    )
    document = ModalIRDocument(
        document_id="packet-000909-frame-epistemic-nominal-cues",
        source="us_code",
        normalized_text=text,
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert "frame->epistemic" in slot_texts["typed_decompiler_family_pair"]
    assert "Frame->K" in slot_texts["refined_modal_operator_pair"]
    assert (
        "frame->epistemic:determination"
        in slot_texts["refined_modal_pair_cue"]
    )


def test_modal_decompiler_refines_effective_date_temporal_typed_ir_slots() -> None:
    formula = ModalIRFormula(
        formula_id="f_effective_date_temporal",
        operator=ModalIROperator(
            family="temporal",
            system="LTL",
            symbol="F",
            label="eventually",
        ),
        predicate=ModalIRPredicate(name="effective_date", role="clause"),
        provenance=ModalIRProvenance(
            source_id="us-code-26-1451-effective-date",
            start_char=0,
            end_char=92,
            citation="26 U.S.C. 1451",
        ),
    )
    document = ModalIRDocument(
        document_id="us-code-26-1451-effective-date",
        source="us_code",
        normalized_text=(
            "§1451. Effective date On and after January 1, 2025, this "
            "subtitle shall apply to withholding."
        ),
        formulas=[formula],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert "effective_date" in slot_texts["typed_ir_refined_modal_cue"]
    assert "temporal->conditional_normative:effective_date" in slot_texts[
        "typed_ir_refined_modal_pair_cue"
    ]
    assert "temporal->frame:effective_date" in slot_texts[
        "typed_ir_refined_modal_pair_cue"
    ]
    assert "f_to_o_pipe" in slot_texts["typed_ir_refined_modal_operator_pair_key"]


def test_modal_decompiler_emits_family_pair_semantic_reconstruction_text() -> None:
    frame_text = (
        "The authority under this section shall apply after the effective date."
    )
    frame_document = ModalIRDocument(
        document_id="packet-002444-frame-semantic-reconstruction",
        source="us_code",
        normalized_text=frame_text,
        formulas=[
            ModalIRFormula(
                formula_id="packet-002444-frame",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="ontology_frame",
                ),
                predicate=ModalIRPredicate(name="authority_applies", role="clause"),
                provenance=ModalIRProvenance(
                    source_id="us-code-22-967-cdb9be2f8d36afa2",
                    start_char=0,
                    end_char=len(frame_text),
                    citation="22 U.S.C. 967",
                ),
                conditions=["after the effective date"],
                metadata={"cue": "shall"},
            )
        ],
    )
    temporal_text = (
        "On and after January 1, 2025, this section shall remain effective."
    )
    temporal_document = ModalIRDocument(
        document_id="packet-002444-temporal-semantic-reconstruction",
        source="us_code",
        normalized_text=temporal_text,
        formulas=[
            ModalIRFormula(
                formula_id="packet-002444-temporal",
                operator=ModalIROperator(
                    family="temporal",
                    system="LTL",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(name="remain_effective", role="clause"),
                provenance=ModalIRProvenance(
                    source_id="us-code-16-8305-98035776ea89e400",
                    start_char=0,
                    end_char=len(temporal_text),
                    citation="16 U.S.C. 8305",
                ),
                conditions=["on and after January 1, 2025"],
            )
        ],
    )

    frame_slots = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(frame_document)
    )
    temporal_slots = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(temporal_document)
    )

    frame_reconstructions = set(
        frame_slots["typed_ir_family_pair_semantic_reconstruction"]
    )
    assert any(
        value.startswith(
            "legal frame source reconstructs obligation permission prohibition"
        )
        and "authority" in value
        and "effective date" in value
        for value in frame_reconstructions
    )
    assert any(
        value.startswith("legal frame source reconstructs temporal deadline period")
        and "after effective date" in value
        for value in frame_reconstructions
    )
    assert {
        "frame->deontic",
        "frame->temporal",
    }.issubset(set(frame_slots["typed_ir_cross_family_semantic_support"]))

    temporal_reconstructions = set(
        temporal_slots["typed_ir_family_pair_semantic_reconstruction"]
    )
    assert any(
        value.startswith("temporal deadline period source reconstruction")
        and "on and after" in value.lower()
        and "january 1 2025" in value.lower()
        for value in temporal_reconstructions
    )
    assert "temporal->temporal" in temporal_slots[
        "typed_ir_cross_family_semantic_support"
    ]


def test_modal_decompiler_emits_domain_atoms_for_appropriation_and_research_sections() -> None:
    appropriation_sample = build_us_code_sample(
        title="42",
        section="6246.",
        citation="42 U.S.C. 6246.",
        text=(
            "§6246. Authorization of appropriations There are authorized to be "
            "appropriated to the Secretary such sums as are necessary to carry "
            "out this part and part D, to remain available until expended."
        ),
    )
    research_sample = build_us_code_sample(
        title="42",
        section="11271.",
        citation="42 U.S.C. 11271.",
        text=(
            "§11271. Research program and plan (a) Grants for research The "
            "Administrator of the Centers for Medicare & Medicaid Services "
            "shall conduct, or make grants for the conduct of, research relevant "
            "to appropriate services for individuals with disabilities."
        ),
    )

    appropriation_slots = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(appropriation_sample.modal_ir)
    )
    research_slots = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(research_sample.modal_ir)
    )

    assert "appropriation_authorization" in appropriation_slots["legal_semantic_atom"]
    assert "no_year_funding_availability" in appropriation_slots["legal_semantic_atom"]
    assert "research_program_plan" in research_slots["legal_semantic_atom"]
    assert "research_grant" in research_slots["legal_semantic_atom"]
    assert "disability_services" in research_slots["legal_semantic_atom"]


def test_modal_decompiler_emits_domain_atoms_for_heading_and_status_sections() -> None:
    heading_sample = build_us_code_sample(
        title="7",
        section="2239",
        citation="7 U.S.C. 2239",
        text=(
            "U.S.C. Title 7 - AGRICULTURE 7 U.S.C. United States Code, 2024 "
            "Edition Title 7 - AGRICULTURE CHAPTER 55 - DEPARTMENT OF "
            "AGRICULTURE Sec. 2239 - Funds for printing, binding, and "
            "scientific and technical article reprint purchases From the U.S. "
            "Government Publishing Office, www.gpo.gov"
        ),
    )
    status_sample = build_us_code_sample(
        title="42",
        section="5616.",
        citation="42 U.S.C. 5616.",
        text=(
            "§5616. Transferred Editorial Notes Codification Section 5616 was "
            "editorially reclassified as section 11116 of Title 34, Crime "
            "Control and Law Enforcement."
        ),
    )

    heading_slots = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(heading_sample.modal_ir)
    )
    status_slots = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(status_sample.modal_ir)
    )

    assert "printing_binding" in heading_slots["legal_semantic_atom"]
    assert "article_reprint_purchase" in heading_slots["legal_semantic_atom"]
    assert "technical_article" in heading_slots["legal_semantic_atom"]
    assert "editorial_reclassification" in status_slots["legal_semantic_atom"]


def test_modal_decompiler_adds_compact_uscode_semantic_support_for_packet_004087_shapes() -> None:
    compiler = DeterministicModalCompiler(ModalCompilerConfig(parser_backend="regex"))
    cases = [
        (
            "us-code-42-15244.-packet-004087-status",
            "42 U.S.C. 15244.",
            (
                "§15244. Transferred Editorial Notes Codification Section 15244 "
                "was editorially reclassified as section 50314 of Title 34, "
                "Crime Control and Law Enforcement."
            ),
            "Transferred",
            "frame||slot:source-semantic-token:codification||knowledge_graphs.neo4j_compat",
        ),
        (
            "us-code-42-1752.-packet-004087-appropriation",
            "42 U.S.C. 1752.",
            (
                "§1752. Authorization of appropriations; \"Secretary\" defined "
                "For each fiscal year, there is authorized to be appropriated, "
                "out of money in the Treasury not otherwise appropriated, such "
                "sums as may be necessary to enable the Secretary of Agriculture "
                "to carry out this section."
            ),
            "Authorization of appropriations",
            "temporal||slot:source-semantic-token:appropriated||TDFOL.prover",
        ),
        (
            "us-code-50-1514.-packet-004087-definition",
            "50 U.S.C. 1514.",
            (
                "§1514. \"United States\" defined Unless otherwise indicated, "
                "as used in this section [50 U.S.C. 1512, 1513-1515, 1517] "
                "the term \"United States\" means the several States, the "
                "District of Columbia, and the territories and possessions of "
                "the United States."
            ),
            "\"United States\" defined Unless otherwise indicated",
            "conditional_normative||slot:source-semantic-token:unless||deontic.ir",
        ),
    ]

    for document_id, citation, source_text, expected_support, expected_view in cases:
        compiled = compiler.compile(
            source_text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        decoded = decode_modal_ir_document(compiled.modal_ir)
        slot_texts = decoded_modal_phrase_slot_text_map(decoded)

        assert decoded.reconstruction_similarity == 1.0
        assert expected_support in slot_texts["typed_ir_compact_semantic_support"]
        assert expected_view in slot_texts["family_semantic_slot_legal_ir_view_prototype"]


def test_modal_decompiler_emits_frame_self_operator_transition_slots() -> None:
    source_text = (
        "Subject to section 282j, the Corporation may enter funding agreements "
        "except as otherwise provided by this chapter."
    )
    document = ModalIRDocument(
        document_id="packet-003520-frame-self-transition",
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id="packet-003520-frame",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="ontology_frame",
                ),
                predicate=ModalIRPredicate(
                    name="enter_funding_agreements",
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="us-code-22-282j-2f6c558ce63a36a4",
                    start_char=0,
                    end_char=len(source_text),
                    citation="22 U.S.C. 282j",
                ),
                conditions=["subject to section 282j"],
                exceptions=["except as otherwise provided by this chapter"],
                metadata={"cue": "may"},
            )
        ],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))
    legal_ir_slots = set(slot_texts["family_semantic_slot_legal_ir_view_prototype"])
    transition_signature = "frame:frame_bm25:frame->frame:frame:frame"
    ordered_edge = (
        f"{transition_signature}:clause:a0:c1:e1->"
        f"{transition_signature}:clause:a0:c1:e1"
    )

    assert "frame->frame" in slot_texts["typed_decompiler_family_pair"]
    assert (
        transition_signature
        in slot_texts["typed_decompiler_operator_transition_signature"]
    )
    assert ordered_edge in slot_texts["typed_decompiler_canonical_ir_ordered_edge"]
    assert (
        f"frame->frame:{transition_signature}"
        in slot_texts["typed_decompiler_family_pair_operator_transition_signature"]
    )
    assert (
        "frame||slot:operator-transition:"
        f"{transition_signature}||modal.frame_logic"
        in legal_ir_slots
    )
    assert (
        "frame||slot-pair:canonical-ir-ordered-edge:"
        f"{ordered_edge}|typed-decompiler-family-pair:frame->frame||modal.frame_logic"
        in legal_ir_slots
    )


def test_modal_decompiler_promotes_residual_fallback_as_target_reconstruction_cue() -> None:
    source_text = (
        "Sec. 410y-1 - Publication of regulations. The Secretary shall publish "
        "regulations in accordance with this section."
    )
    document = ModalIRDocument(
        document_id="packet-001764-frame-deontic-residual-cue",
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id="packet-001764-frame",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="ontology_frame",
                ),
                predicate=ModalIRPredicate(
                    name="pub_regulations",
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="us-code-16-410y-1-477101a2ff02bb17",
                    start_char=0,
                    end_char=len(source_text),
                    citation="16 U.S.C. 410y-1",
                ),
                conditions=["in accordance with this section"],
                metadata={
                    "cue": "publication",
                    "fallback_rule": "uscode_residual_span_coverage_v1",
                },
            )
        ],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))
    legal_ir_slots = set(slot_texts["family_semantic_slot_legal_ir_view_prototype"])
    residual_pair_cue = "frame->deontic:uscode_residual_span_coverage_v1"

    assert residual_pair_cue in slot_texts["typed_decompiler_family_pair_cue"]
    assert residual_pair_cue in slot_texts["typed_decompiler_target_reconstruction_cue"]
    assert (
        "deontic||slot:typed-decompiler-target-reconstruction-cue:"
        f"{residual_pair_cue}||deontic.ir"
        in legal_ir_slots
    )
    assert (
        "deontic||slot-pair:semantic-reconstruction-cue:"
        "uscode_residual_span_coverage_v1|typed-decompiler-family-pair:"
        "frame->deontic||deontic.ir"
        in legal_ir_slots
    )


def test_modal_decompiler_surfaces_epistemic_frame_pair_cues_for_statutory_scope() -> None:
    source_text = (
        "The Administrator determines that the agency shall provide mitigation "
        "assistance under this section."
    )
    document = ModalIRDocument(
        document_id="packet-003095-epistemic-frame-scope",
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id="packet-003095-epistemic",
                operator=ModalIROperator(
                    family="epistemic",
                    system="S5",
                    symbol="K",
                    label="knowledge",
                ),
                predicate=ModalIRPredicate(
                    name="administrator_determines_agency_shall_provide_mitigation",
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="us-code-42-4104c.-bd287c7c45a3de65",
                    start_char=0,
                    end_char=len(source_text),
                    citation="42 U.S.C. 4104c.",
                ),
                conditions=["under this section"],
                metadata={"cue": "determines"},
            )
        ],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert "epistemic->frame" in slot_texts["typed_decompiler_family_pair"]
    assert {
        "epistemic->frame:section",
        "epistemic->frame:shall",
    }.issubset(set(slot_texts["typed_decompiler_family_pair_cue"]))
    assert {
        "epistemic->frame:section",
        "epistemic->frame:shall",
    }.issubset(
        set(slot_texts["modal_source_span_typed_decompiler_family_pair_cue"])
    )


def test_modal_decompiler_reconstructs_heading_semantics_as_legal_ir_view_slots() -> None:
    source_text = (
        "Sec. 233 - Jurisdiction of New York State courts in civil actions. "
        "The State courts may hear civil actions under this section."
    )
    document = ModalIRDocument(
        document_id="packet-000153-jurisdiction-heading-semantics",
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id="packet-000153-jurisdiction",
                operator=ModalIROperator(
                    family="deontic",
                    system="KD",
                    symbol="P",
                    label="permission",
                ),
                predicate=ModalIRPredicate(
                    name="hear_civil_actions",
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="us-code-25-233-da029ae8d3664392",
                    start_char=0,
                    end_char=len(source_text),
                    citation="25 U.S.C. 233",
                ),
                conditions=["under this section"],
                metadata={"cue": "may"},
            )
        ],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))
    legal_ir_slots = set(slot_texts["family_semantic_slot_legal_ir_view_prototype"])

    assert {
        "state_court_civil_jurisdiction",
        "jurisdiction_authority",
        "civil_action",
    }.issubset(set(slot_texts["typed-decompiler-source-semantic-atom"]))
    assert "state_court_civil_jurisdiction:deontic->frame" in set(
        slot_texts["typed-decompiler-source-semantic-family-pair"]
    )
    assert (
        "deontic||slot:source-semantic-atom:"
        "state_court_civil_jurisdiction||knowledge_graphs.neo4j_compat"
        in legal_ir_slots
    )
    assert (
        "deontic||slot:source-semantic-atom:"
        "state_court_civil_jurisdiction||CEC.native"
        in legal_ir_slots
    )


def test_modal_decompiler_reconstructs_office_seal_as_cec_view_slot() -> None:
    source_text = (
        "Sec. 2322 - Seal. The Plant Variety Protection Office shall have an "
        "official seal."
    )
    document = ModalIRDocument(
        document_id="packet-000153-office-seal-semantics",
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id="packet-000153-seal",
                operator=ModalIROperator(
                    family="deontic",
                    system="KD",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="maintain_official_seal",
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="us-code-7-2322-8a47b18df0989404",
                    start_char=0,
                    end_char=len(source_text),
                    citation="7 U.S.C. 2322",
                ),
                metadata={"cue": "shall"},
            )
        ],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))
    legal_ir_slots = set(slot_texts["family_semantic_slot_legal_ir_view_prototype"])

    assert {
        "official_seal",
        "plant_variety_protection_office",
    }.issubset(set(slot_texts["typed-decompiler-source-semantic-atom"]))
    assert (
        "deontic||slot:source-semantic-atom:official_seal||CEC.native"
        in legal_ir_slots
    )
    assert (
        "deontic||slot:source-semantic-atom:"
        "plant_variety_protection_office||knowledge_graphs.neo4j_compat"
        in legal_ir_slots
    )


def test_modal_decompiler_reconstructs_foreign_relations_exchange_program_atoms() -> None:
    source_text = (
        "Sec. 2735 - Foreign relations exchange programs. The Secretary may "
        "provide exchange programs under this section."
    )
    document = ModalIRDocument(
        document_id="packet-000461-foreign-relations-exchange-program",
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id="packet-000461-foreign-exchange",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="ontology_frame",
                ),
                predicate=ModalIRPredicate(
                    name="foreign_relations_exchange_programs",
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="us-code-22-2735-6dca3bae4c640797",
                    start_char=0,
                    end_char=len(source_text),
                    citation="22 U.S.C. 2735",
                ),
                metadata={"cue": "may"},
            )
        ],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))
    legal_ir_slots = set(slot_texts["family_semantic_slot_legal_ir_view_prototype"])

    assert "foreign_relations_exchange_program" in slot_texts[
        "typed-decompiler-source-semantic-atom"
    ]
    assert "exchange_program" in slot_texts["typed-decompiler-source-semantic-atom"]
    assert "frame->deontic" in slot_texts[
        "typed-decompiler-target-reconstruction-pair"
    ]
    assert "frame->temporal" in slot_texts[
        "typed-decompiler-target-reconstruction-pair"
    ]
    assert (
        "frame||slot:source-semantic-atom:"
        "foreign_relations_exchange_program||CEC.native"
        in legal_ir_slots
    )
    assert (
        "frame||slot:source-semantic-atom:"
        "foreign_relations_exchange_program||knowledge_graphs.neo4j_compat"
        in legal_ir_slots
    )


def test_modal_decompiler_reconstructs_repealed_biological_product_history_atoms() -> None:
    source_text = (
        "§§141 to 148. Repealed. Section 141 provided for regulation of sale "
        "of and interstate traffic of viruses, serums, toxins, antitoxins."
    )
    document = ModalIRDocument(
        document_id="packet-000461-biological-products-repealed-history",
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id="packet-000461-biological-products",
                operator=ModalIROperator(
                    family="frame",
                    system="FRAME_BM25",
                    symbol="Frame",
                    label="ontology_frame",
                ),
                predicate=ModalIRPredicate(
                    name="biological_product_regulation_history",
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="us-code-42-141 to 148.-b4619e2a4060b8f9",
                    start_char=0,
                    end_char=len(source_text),
                    citation="42 U.S.C. 141 to 148.",
                ),
                metadata={"status_keyword": "repealed"},
            )
        ],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))
    legal_ir_slots = set(slot_texts["family_semantic_slot_legal_ir_view_prototype"])

    assert "repealed" in slot_texts["typed-decompiler-source-semantic-atom"]
    assert "biological_product_regulation" in slot_texts[
        "typed-decompiler-source-semantic-atom"
    ]
    assert "biological_product_interstate_traffic" in slot_texts[
        "typed-decompiler-source-semantic-atom"
    ]
    assert "frame->conditional_normative" in slot_texts[
        "typed-decompiler-target-reconstruction-pair"
    ]
    assert "frame->temporal" in slot_texts[
        "typed-decompiler-target-reconstruction-pair"
    ]
    assert (
        "frame||slot:source-semantic-atom:"
        "biological_product_regulation||deontic.ir"
        in legal_ir_slots
    )
    assert (
        "frame||slot:source-semantic-atom:"
        "biological_product_interstate_traffic||CEC.native"
        in legal_ir_slots
    )


def test_modal_decompiler_emits_directional_frame_target_reconstruction_pairs() -> None:
    source_text = "Sec. 799 - Regulation of power resources."
    document = ModalIRDocument(
        document_id="packet-000121-frame-directional-reconstruction",
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id="packet-000121-frame",
                operator=ModalIROperator(
                    family="frame",
                    system="frame",
                    symbol="Frame",
                    label="framed as",
                ),
                predicate=ModalIRPredicate(
                    name="regulation_of_power_resources",
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="us-code-16-799-ed4b744b4bed77ee",
                    start_char=0,
                    end_char=len(source_text),
                    citation="16 U.S.C. 799",
                ),
            )
        ],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert {
        "frame->frame",
        "frame->deontic",
        "frame->temporal",
    }.issubset(set(slot_texts["typed-decompiler-target-reconstruction-pair"]))
    assert {
        "frame",
        "deontic",
        "temporal",
    }.issubset(set(slot_texts["typed-decompiler-target-reconstruction-family"]))
    assert {
        "unconditioned:frame->frame",
        "unconditioned:frame->deontic",
        "unconditioned:frame->temporal",
    }.issubset(set(slot_texts["typed-decompiler-target-reconstruction-scope"]))


def test_modal_decompiler_emits_directional_temporal_deontic_reconstruction_pair() -> None:
    source_text = "The effective date applies after enactment."
    document = ModalIRDocument(
        document_id="packet-000121-temporal-directional-reconstruction",
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id="packet-000121-temporal",
                operator=ModalIROperator(
                    family="temporal",
                    system="ltl",
                    symbol="F",
                    label="eventually",
                ),
                predicate=ModalIRPredicate(
                    name="effective_date_applies",
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="us-code-42-300a-e57ccd658257dc26",
                    start_char=0,
                    end_char=len(source_text),
                    citation="42 U.S.C. 300a",
                ),
                conditions=["after enactment"],
                metadata={"cue": "after"},
            )
        ],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert "temporal->deontic" in set(
        slot_texts["typed-decompiler-target-reconstruction-pair"]
    )
    assert "deontic" in set(
        slot_texts["typed-decompiler-target-reconstruction-family"]
    )
    assert "conditioned+temporal:temporal->deontic" in set(
        slot_texts["typed-decompiler-target-reconstruction-scope"]
    )


def test_modal_decompiler_reconstructs_public_document_allotment_semantics() -> None:
    source_text = (
        "§731. Allotments of public documents printed after expiration of terms "
        "of Members of Congress; rights of retiring Members to documents. "
        "The Congressional allotment of public documents, other than the "
        "Congressional Record, printed after the expiration of a Member's term "
        "shall be available to the retiring Member."
    )
    document = ModalIRDocument(
        document_id="packet-001018-public-document-allotment",
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id="packet-001018-public-document-frame",
                operator=ModalIROperator(
                    family="frame",
                    system="frame",
                    symbol="Frame",
                    label="framed as",
                ),
                predicate=ModalIRPredicate(
                    name="public_document_allotment",
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="us-code-44-731.-0e92fb9cf6b137c3",
                    start_char=0,
                    end_char=len(source_text),
                    citation="44 U.S.C. 731.",
                ),
                metadata={"cue": "after"},
            )
        ],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert {
        "public_document_allotment",
        "post_term_member_right",
        "post_term_public_document_allotment",
        "retiring_member_document_right",
        "temporal_condition",
    }.issubset(set(slot_texts["typed-decompiler-source-semantic-atom"]))
    assert {
        "frame->conditional_normative",
        "frame->deontic",
        "frame->temporal",
    }.issubset(set(slot_texts["typed-decompiler-target-reconstruction-pair"]))
    assert {
        "legal frame source reconstructs conditional obligation",
        "legal frame source reconstructs temporal deadline period",
    }.issubset(set(slot_texts["typed_ir_family_pair_reconstruction_support"]))


def test_modal_decompiler_reconstructs_repealed_range_status_semantics() -> None:
    source_text = (
        "Secs. 262 to 297 - Repealed. Dec. 17, 1943, ch. 344, §1, "
        "57 Stat. 600."
    )
    document = ModalIRDocument(
        document_id="packet-001018-repealed-range",
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id="packet-001018-repealed-range-deontic",
                operator=ModalIROperator(
                    family="deontic",
                    system="kd",
                    symbol="O",
                    label="obligatory",
                ),
                predicate=ModalIRPredicate(
                    name="repealed_sections_status",
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="us-code-8-262-0a75e91cd7f00479",
                    start_char=0,
                    end_char=len(source_text),
                    citation="8 U.S.C. 262",
                ),
                metadata={"cue": "repealed"},
            )
        ],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert "repealed" in set(slot_texts["typed-decompiler-source-semantic-atom"])
    assert "deontic->temporal" in set(
        slot_texts["typed-decompiler-target-reconstruction-pair"]
    )
    assert "deontic->conditional_normative" in set(
        slot_texts["typed-decompiler-target-reconstruction-pair"]
    )
    assert "repealed" in set(slot_texts["source_status_clause_legal_semantic_atom"])


def test_modal_decompiler_anchors_frame_epistemic_residuals_to_knowledge_graph_view() -> None:
    source_text = "Elimination to permanently nonirrigable lands."
    document = ModalIRDocument(
        document_id="packet-000368-frame-epistemic-residual",
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id="packet-000368-frame-epistemic-residual-frame",
                operator=ModalIROperator(
                    family="frame",
                    system="frame",
                    symbol="Frame",
                    label="framed as",
                ),
                predicate=ModalIRPredicate(
                    name="elimination_to_permanently_nonirrigable_lands",
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="us-code-25-389b-2d50dabb4faf7ea6",
                    start_char=0,
                    end_char=len(source_text),
                    citation="25 U.S.C. 389b",
                ),
                metadata={
                    "cue": "__uscode_residual_span_fallback__",
                    "fallback_rule": "uscode_residual_span_coverage_v1",
                },
            )
        ],
    )

    slot_texts = decoded_modal_phrase_slot_text_map(decode_modal_ir_document(document))

    assert "frame->epistemic" in set(
        slot_texts["typed-decompiler-target-reconstruction-pair"]
    )
    assert "knowledge_graphs.neo4j_compat" in set(slot_texts["legal_ir_view_prototype"])
    assert (
        "frame->epistemic||knowledge_graphs.neo4j_compat"
        in set(slot_texts["typed-decompiler-target-reconstruction-view"])
    )
