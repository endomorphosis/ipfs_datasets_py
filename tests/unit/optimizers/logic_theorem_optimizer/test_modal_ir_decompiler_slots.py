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
        "source_id_section_raw": slot_map.get("source_id_section_raw", []),
        "source_id_section_normalized": slot_map.get(
            "source_id_section_normalized",
            [],
        ),
        "triple_citation_section_raw": predicate_values.get("citation_section_raw", []),
        "triple_citation_section_normalized": predicate_values.get(
            "citation_section_normalized",
            [],
        ),
        "triple_source_id_section_raw": predicate_values.get("source_id_section_raw", []),
        "triple_source_id_section_normalized": predicate_values.get(
            "source_id_section_normalized",
            [],
        ),
    }


def test_modal_slots_emit_raw_and_normalized_section_values_for_trailing_punct() -> None:
    values = _predicate_values("1437q.", title="42")

    assert values["citation_section_raw"] == ["1437q."]
    assert values["citation_section_normalized"] == ["1437q"]
    assert values["source_id_section_raw"] == ["1437q."]
    assert values["source_id_section_normalized"] == ["1437q"]

    assert values["triple_citation_section_raw"] == ["1437q."]
    assert values["triple_citation_section_normalized"] == ["1437q"]
    assert values["triple_source_id_section_raw"] == ["1437q."]
    assert values["triple_source_id_section_normalized"] == ["1437q"]


def test_modal_slots_emit_raw_and_normalized_section_values_without_trailing_punct() -> None:
    values = _predicate_values("3902", title="38")

    assert values["citation_section_raw"] == ["3902"]
    assert values["citation_section_normalized"] == ["3902"]
    assert values["source_id_section_raw"] == ["3902"]
    assert values["source_id_section_normalized"] == ["3902"]

    assert values["triple_citation_section_raw"] == ["3902"]
    assert values["triple_citation_section_normalized"] == ["3902"]
    assert values["triple_source_id_section_raw"] == ["3902"]
    assert values["triple_source_id_section_normalized"] == ["3902"]
