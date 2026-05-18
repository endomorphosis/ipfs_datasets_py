"""Regression tests for modal IR decompiler slot normalization."""

from __future__ import annotations

from ipfs_datasets_py.logic.modal import (
    decode_modal_ir_document,
    decoded_modal_phrase_slot_text_map,
    modal_ir_to_flogic_triples,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
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
