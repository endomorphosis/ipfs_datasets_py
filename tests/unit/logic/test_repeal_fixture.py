"""The Twenty-First Amendment repeal is a fixture edge, not an admit."""

from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
from ipfs_datasets_py.logic.autoformal.repeal_fixture import RepealFixture, repeal_from_sentence

_TWENTY_FIRST = (
    "The eighteenth article of amendment to the Constitution of the United States "
    "is hereby repealed."
)


def test_amendment_21_slots_a_repeal_of_amendment_18() -> None:
    parsed = repeal_from_sentence(_TWENTY_FIRST, instrument_id="amend-21")
    assert parsed["target_id"] == "amend-18"
    assert parsed["admitted"] is False
    fixture = RepealFixture()
    stored = fixture.put(instrument_id="amend-21", text=_TWENTY_FIRST)
    assert stored["result"] == "yes"
    slotted = fixture.slot(_TWENTY_FIRST, instrument_id="amend-21")
    assert slotted["result"] == "yes"
    assert slotted["target_id"] == "amend-18"
    assert slotted["admitted"] is False
    frame = fixture.repository.blob_store.get_bytes(slotted["frame_cid"])
    edge = fixture.repository.blob_store.get_bytes(slotted["edge_cid"])
    assert b"amend-18" in frame
    assert b"repeals" in edge
    assert fixture.repository._connection is None
    row = fixture._by_instrument["amend-21"]
    assert "is hereby repealed" not in row


def test_amendment_21_builds_a_flogic_frame_and_a_knowledge_graph_edge() -> None:
    fixture = RepealFixture()
    fixture.put(instrument_id="amend-21", text=_TWENTY_FIRST)
    ontology = fixture.flogic("amend-21")
    frame = ontology.frames[0]
    assert frame.object_id == "amend-21"
    assert frame.isa == "repeal"
    assert frame.scalar_methods["repeals"] == "amend-18"
    graph = fixture.knowledge_graph("amend-21")
    predicates = {relationship.type for relationship in graph.relationships}
    assert any("REPEAL" in predicate.upper() for predicate in predicates)
    assert fixture.flogic("amend-99").frames == []
    assert fixture.knowledge_graph("amend-99").relationships == []


def test_a_missing_or_different_repeal_does_not_match() -> None:
    fixture = RepealFixture()
    fixture.put(instrument_id="amend-21", text=_TWENTY_FIRST)
    missing = fixture.slot(_TWENTY_FIRST, instrument_id="amend-18")
    assert missing["result"] == "abstain"
    assert missing["reason"] == "unmapped"
    other = "The first article of amendment is hereby repealed."
    mismatch = RepealFixture()
    mismatch.put(instrument_id="amend-21", text=_TWENTY_FIRST)
    # The stored target is amend-18. Asking amend-21 to slot a first-amendment
    # repeal is a mismatch, not a new edge.
    assert mismatch.slot(other, instrument_id="amend-21")["result"] == "no"
    assert repeal_from_sentence("Congress shall make no law.", instrument_id="amend-21")["target_id"] == ""


def test_an_id_string_is_not_the_repeal_sentence() -> None:
    from ipfs_datasets_py.logic.autoformal.autoencoder_router import (
        _repeal_surface_kept,
        agreement_census,
    )

    assert _repeal_surface_kept(_TWENTY_FIRST, "amend-21 repeals amend-18.") is False
    census = agreement_census(
        [{"id": "amend-21.sec-1.span-1", "text": _TWENTY_FIRST, "status": "uncompiled"}],
        {},
    )
    row = census["rows"][0]
    assert row["agrees"] is True
    assert "eighteenth article of amendment" in row["decompiled"].lower()
    assert "is hereby repealed" in row["decompiled"].lower()
    assert census["formalized"] is False
    assert census["admitted"] is False


def test_the_repeal_sentence_is_projected_and_not_an_opf_compile() -> None:
    from ipfs_datasets_py.logic.deontic import DeonticConverter

    converted = DeonticConverter(
        jurisdiction="us",
        document_type="statute",
        use_ml=False,
        use_cache=False,
        enable_monitoring=False,
    ).convert(_TWENTY_FIRST)
    element = list(converted.output.parser_elements)[0]
    assert element["extraction_method"] == "deterministic_hereby_repealed_v1"
    assert element["norm_type"] == "instrument_lifecycle"
    assert "eighteenth" in " ".join(element["subject"]).lower()
    assert element["subject"] != ["section"]
    out = compile_span(AutoformalSession(), _TWENTY_FIRST, "amend-21.sec-1.span-1")
    assert out["compiler_status"] == "repeal"
    assert out["compiler_status"] != "compiled"
    assert "unsupported_norm_type" in out["fields"]
    assert out["admitted"] is False
    assert "eighteenth article of amendment" in out["decompiled"].lower()
    assert "is hereby repealed" in out["decompiled"].lower()
    assert out["repeal"]["target_id"] == "amend-18"
    assert "amend-21 repeals amend-18" != out["decompiled"]


def test_a_us_code_repealed_note_is_not_a_constitutional_article() -> None:
    from ipfs_datasets_py.logic.deontic import DeonticConverter

    note = "§§7705, 7705a. Repealed. Pub. L. 105-47, §4, Oct. 1, 1997, 111 Stat. 1164"
    converted = DeonticConverter(
        jurisdiction="us",
        document_type="statute",
        use_ml=False,
        use_cache=False,
        enable_monitoring=False,
    ).convert(note)
    element = list(converted.output.parser_elements)[0]
    assert element["norm_type"] == "instrument_lifecycle"
    assert element["extraction_method"] == "deterministic_section_status_lifecycle_v1"
    out = compile_span(AutoformalSession(), note, "usc-7705")
    assert out["compiler_status"] == "abstain"
    assert out.get("decompiled") == ""
