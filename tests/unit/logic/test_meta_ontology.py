"""Meta-ontology classifies participants, acts, states, and objects."""
from ipfs_datasets_py.logic.autoformal.meta_ontology import (
    classify_surface,
    deontic_formula,
    graph_edge_category,
    graph_node_category,
    logical_relation,
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
