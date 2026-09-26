"""Recipient sorts are satisfied by the graph, not by the keyword classifier."""

from __future__ import annotations

from ipfs_datasets_py.logic.autoformal.ontology_fragments import FragmentRegistry
from ipfs_datasets_py.logic.autoformal.recipient_reference import (
    FixtureGraph,
    RecipientSortIndex,
    recipient_reference,
    satisfies,
    sort_id_from_surface,
)
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import classify_legal_entity


def _fixture():
    graph = FixtureGraph([("dog", "animal"), ("fbi", "agency")])
    index = RecipientSortIndex()
    index.put(
        sort_id="person",
        graph_type_id="person",
        frame={"sort_id": "person", "isa": "legal_person", "capacity": "legal_person"},
        edge={"subject": "dog", "predicate": "type", "object": "animal"},
    )
    index.put(
        sort_id="agency",
        graph_type_id="agency",
        frame={"sort_id": "agency", "isa": "government_actor"},
        edge={"subject": "fbi", "predicate": "type", "object": "agency"},
    )
    return graph, index


def test_sort_lemmas_and_fbi_has_no_instance_until_the_graph_is_loaded() -> None:
    assert sort_id_from_surface("a person") == "person"
    assert sort_id_from_surface("an agency") == "agency"
    assert recipient_reference("FBI")["instance_id"] == ""
    assert recipient_reference("FBI")["sort_id"] == "fbi"
    assert recipient_reference("the requester")["surface"] == "the requester"
    assert recipient_reference("the requester")["admitted"] is False


def test_dog_is_not_a_person_and_fbi_is_an_agency_only_from_the_graph() -> None:
    graph, index = _fixture()
    assert satisfies("dog", "person", graph=graph, index=index) == {
        "result": "no",
        "admitted": False,
    }
    assert satisfies("fbi", "agency", graph=graph, index=index)["result"] == "yes"
    assert satisfies("fbi", "person", graph=graph, index=index)["result"] == "no"
    assert satisfies("", "agency", graph=graph, index=index)["reason"] == "unmapped"
    missing = FixtureGraph([])
    assert satisfies("fbi", "agency", graph=missing, index=index)["result"] == "abstain"
    assert classify_legal_entity("FBI") == "legal_entity"
    person_row = index.get("person")
    assert person_row is not None
    stored = index.repository.blob_store.get_bytes(person_row["graph_edge_cid"])
    assert b"dog" in stored
    assert "capacity" not in person_row
    assert index.repository._connection is None


def test_proposed_recipient_sorts_stay_invisible_to_the_compiler() -> None:
    registry = FragmentRegistry()
    for relation, lemma in (("person", "person"), ("agency", "agency")):
        proposed = registry.propose({
            "relation": relation,
            "domain": "norm",
            "range": "sort",
            "attachment": "recipient",
            "decompiler_phrase": "",
            "fixture_id": "",
        })
        assert proposed["status"] == "proposed"
        assert proposed["admitted"] is False
    assert registry.visible_to_compiler() == []


def test_a_requester_sentence_still_abstains_when_recipient_is_present() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
    from ipfs_datasets_py.logic.autoformal.recipient_reference import recipient_surface_from_sentence

    text = "The agency shall send the notice to the requester."
    surface = recipient_surface_from_sentence(text)
    assert surface.lower() == "requester"
    reference = recipient_reference(surface)
    assert reference["sort_id"] == "requester"
    assert reference["admitted"] is False
    out = compile_span(AutoformalSession(), text, "requester-only")
    assert out["compiler_status"] == "abstain"
    assert "recipient" in out["fields"]
    assert "procedure" in out["fields"]
    assert out["decompiled"] == ""
