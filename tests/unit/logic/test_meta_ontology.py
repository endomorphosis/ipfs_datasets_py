"""Meta-ontology classifies participants, acts, states, and objects."""
import pytest

from ipfs_datasets_py.logic.autoformal.meta_ontology import (
    classify_surface,
    contains_lookup_phrase,
    deontic_formula,
    graph_edge_category,
    graph_node_category,
    logical_relation,
    lookup_logic,
    mention_for_span,
    normalize_lookup,
    occurrences_for_span,
    ontology_rows,
    read_span,
)


def test_graph_nodes_map_into_the_meta_ontology() -> None:
    assert graph_node_category("section") == "scope"
    assert graph_node_category("title") == "scope"
    assert graph_node_category("public_law") == "instrument"
    assert graph_node_category("unresolved_citation") == "citation"
    assert graph_node_category("source_package") == "provenance"
    assert graph_edge_category("CITES") == "citation"
    assert graph_edge_category("CITES_UNRESOLVED") == "citation"
    assert graph_edge_category("CODIFIES") == "instrument"
    assert graph_edge_category("DERIVED_FROM") == "provenance"
    assert graph_edge_category("CONTAINS") == "scope"


def test_logical_relations_keep_citation_in_the_formula_only() -> None:
    cites = logical_relation("CITES")
    assert cites["in_formula"] is True
    assert cites["logic_role"] == "reference"
    assert logical_relation("CITES_UNRESOLVED")["in_formula"] is False
    assert logical_relation("CONTAINS")["in_formula"] is False
    assert logical_relation("DERIVED_FROM")["meta_category"] == "provenance"
    assert classify_surface("theft") == "act"
    assert classify_surface("marriage") == "state"
    assert classify_surface("signature") == "object"


def test_reclassified_terms_and_named_participants() -> None:
    assert classify_surface("theft") == "act"
    assert classify_surface("marriage") == "state"
    assert classify_surface("signature") == "object"
    assert classify_surface("police") == "participant"
    assert classify_surface("the president") == "participant"
    assert classify_surface("congress") == "participant"
    assert classify_surface("a person") == "participant"
    assert classify_surface("Title 1") == ""


def test_deontic_link_uses_roles_and_does_not_admit() -> None:
    read = read_span(
        "A person shall not commit theft of a signature.",
        legal_id="usc:us:18:1001",
        span_id="span-1",
    )
    assert read["modality"] == "prohibition"
    assert read["participant"] == "a person"
    assert read["act"] == "theft"
    assert read["object"] == "signature"
    assert read["formula"] == deontic_formula(
        "prohibition", participant="a person", act="theft", object_="signature"
    )
    assert read["admitted"] is False
    rows = ontology_rows(
        [{"legal_id": "usc:us:18:1001", "source_span_id": "span-1", "text": "A person shall not commit theft of a signature."}]
    )
    kinds = {row["record_kind"] for row in rows}
    assert {"category", "term", "link"} <= kinds
    assert all(row["admitted"] is False and row["formalized"] is False for row in rows)
    assert all(row["meta_category"] != "scope" or row["record_kind"] == "category" for row in rows)


def test_lookup_normalizes_president_and_keeps_theft_distinct_from_steal() -> None:
    assert normalize_lookup("President") == normalize_lookup("the president") == "president"
    assert normalize_lookup("theft") != normalize_lookup("steal")
    assert normalize_lookup("habeas corpus") == "habeas corpus"
    assert contains_lookup_phrase("corpus", "habeas corpus") is False
    assert contains_lookup_phrase("the writ of habeas corpus", "habeas corpus") is True

    president = occurrences_for_span(
        {
            "legal_id": "usc:us:1:1",
            "rule": {"action": "publish", "actor": "The President", "modality": "obligation", "object": "notice"},
            "source_span_id": "span-president",
            "source_text": "The President shall publish notice.",
        }
    )
    actor = next(row for row in president if row["kind"] == "actor")
    assert actor["hit_kind"] == "role"
    assert actor["category"] == "participant"
    assert "participant:The President" in actor["formula"]
    assert actor["admitted"] is False and actor["formalized"] is False
    assert lookup_logic(president, "President")["category"] == "participant"
    senate = occurrences_for_span(
        {
            "legal_id": "usc:us:1:2",
            "rule": {
                "action": "sign",
                "actor": "The President of the Senate",
                "modality": "obligation",
                "object": "a bill",
            },
            "source_span_id": "span-senate",
            "source_text": "The President of the Senate shall sign a bill.",
        }
    )
    assert any(row["kind"] == "actor" for row in lookup_logic(senate, "President")["roles"])

    theft = occurrences_for_span(
        {
            "legal_id": "usc:us:18:1",
            "rule": {"action": "theft", "actor": "A person", "modality": "prohibition", "object": "signature"},
            "source_span_id": "span-theft",
            "source_text": "A person shall not commit theft of a signature.",
        }
    )
    steal = occurrences_for_span(
        {
            "legal_id": "usc:us:18:2",
            "rule": {"action": "steal", "actor": "A person", "modality": "prohibition", "object": "property"},
            "source_span_id": "span-steal",
            "source_text": "A person shall not steal property.",
        }
    )
    found = lookup_logic(theft + steal, "theft")
    assert found["kinds"] == ["action"]
    assert found["category"] == "act"
    assert found["roles"] and all("act:theft" in row["formula"] for row in found["roles"])
    assert all(row["normalized"] != "steal" for row in found["rows"])
    assert found["admitted"] is False and found["formalized"] is False

    habeas = {
        "legal_id": "usc:us:28:2241",
        "rule": {"action": "grant", "actor": "The court", "modality": "obligation", "object": "relief"},
        "source_span_id": "span-habeas",
        "source_text": "The court shall grant habeas corpus.",
    }
    habeas_rows = occurrences_for_span(habeas)
    assert not any(row["hit_kind"] == "role" and "habeas" in row["normalized"] for row in habeas_rows)
    mention = mention_for_span(habeas, "habeas corpus")
    assert mention is not None
    assert mention["hit_kind"] == "mention"
    assert mention["normalized"] == "habeas corpus"
    assert mention["kind"] == ""
    assert "participant:The court" in mention["formula"]
    assert mention["admitted"] is False and mention["formalized"] is False
    assert lookup_logic([mention], "habeas corpus")["mentions"]
    lone = dict(mention)
    lone["surface"] = "corpus"
    lone["normalized"] = "corpus"
    assert lookup_logic([lone], "habeas corpus")["rows"] == []
    with pytest.raises(ValueError, match="three"):
        lookup_logic([], "co")


def test_lookup_orders_exact_roles_before_labels_and_mentions() -> None:
    rows = [
        {
            "admitted": True,
            "hit_kind": "mention",
            "kind": "",
            "legal_id": "usc:us:1:3",
            "normalized": "theft",
            "span_id": "m",
            "surface": "theft",
            "term_id": "",
        },
        {
            "hit_kind": "label",
            "kind": "",
            "legal_id": "usc:us:1:2",
            "normalized": "theft chapter",
            "section_label": "Theft chapter",
            "span_id": "",
            "surface": "Theft chapter",
            "term_id": "",
        },
        {
            "category": "act",
            "hit_kind": "role",
            "kind": "action",
            "legal_id": "usc:us:1:2",
            "normalized": "theft of property",
            "span_id": "b",
            "surface": "theft of property",
            "term_id": "2",
        },
        {
            "category": "act",
            "hit_kind": "role",
            "kind": "action",
            "legal_id": "usc:us:1:1",
            "normalized": "theft",
            "span_id": "a",
            "surface": "theft",
            "term_id": "1",
        },
    ]
    found = lookup_logic(rows, "theft")
    assert [row["hit_kind"] for row in found["rows"]] == ["role", "role", "label", "mention"]
    assert found["rows"][0]["normalized"] == "theft"
    assert found["rows"][1]["normalized"] == "theft of property"
    assert found["rows"][0]["admitted"] is False and found["formalized"] is False
    assert found["category"] == "act"
    assert found["kinds"] == ["action"]
