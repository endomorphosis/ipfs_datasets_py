"""Procedure chains are slotted from indexed law rows, not invented."""

from __future__ import annotations

from ipfs_datasets_py.logic.autoformal.ontology_fragments import FragmentRegistry
from ipfs_datasets_py.logic.autoformal.procedure_slot import (
    ProcedureLawIndex,
    procedure_from_sentence,
    procedure_id,
    slot_procedure,
)


def _index() -> ProcedureLawIndex:
    index = ProcedureLawIndex()
    index.put(
        citation="5 USC 552",
        events=["notice", "hearing"],
        frame={"procedure_id": "notice->hearing", "isa": "procedure", "events": ["notice", "hearing"]},
        edge={"subject": "5 USC 552", "predicate": "procedure", "object": "notice->hearing"},
    )
    return index


def test_a_matching_law_row_slots_the_chain_and_a_missing_chain_abstains() -> None:
    index = _index()
    slotted = slot_procedure(["notice", "hearing"], index)
    assert slotted["result"] == "yes"
    assert slotted["citation"] == "5 USC 552"
    assert slotted["admitted"] is False
    assert slotted["frame_cid"]
    stored = index.repository.blob_store.get_bytes(slotted["frame_cid"])
    assert b"notice" in stored
    row = index.get("notice->hearing")
    assert row is not None
    assert "events" not in row
    assert index.repository._connection is None
    missing = slot_procedure(["appeal"], index)
    assert missing["result"] == "abstain"
    assert missing["reason"] == "unmapped"
    assert slot_procedure([], index)["reason"] == "no_procedure"
    assert procedure_id(["notice", "hearing"]) == "notice->hearing"


def test_the_parser_chain_can_be_slotted_and_the_compiler_still_abstains() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = "The agency shall give notice and hold a hearing."
    found = procedure_from_sentence(text)
    assert found["events"] == ["notice", "hearing"]
    assert found["admitted"] is False
    slotted = slot_procedure(found["events"], _index())
    assert slotted["result"] == "yes"
    out = compile_span(AutoformalSession(), text, "notice-hearing")
    assert out["compiler_status"] == "abstain"
    assert "procedure" in out["fields"]
    registry = FragmentRegistry()
    proposed = registry.propose({
        "relation": "notice_hearing",
        "domain": "norm",
        "range": "procedure",
        "attachment": "procedure",
        "decompiler_phrase": "",
        "fixture_id": "",
    })
    assert proposed["admitted"] is False
    assert registry.visible_to_compiler() == []
