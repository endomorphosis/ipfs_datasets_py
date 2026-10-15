"""Current release-wrapper citation identity on real, private Parquet files.

The existing release encoder and citation consumer are exercised together.
The graph is authored transport evidence, not reviewed statutory semantics.
No hosted calls, models, training, source-cache migration or legal admission.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_data import uscode_hf_release as release


def citation_reader():
    path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/publish_kg_meta_ontology.py"
    spec = importlib.util.spec_from_file_location("_kg_current_wrapper_citation_identity", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_wrapped_graph_parquet_preserves_exact_citation_identity(tmp_path):
    families = release.fixture_family_rows()
    nodes = deepcopy(families["graph_nodes"])
    edges = deepcopy(families["graph_edges"])
    assert len(nodes) == 2 and len(edges) == 1
    # Equal display labels cannot replace distinct entry identities. Additional
    # source/role fields are opaque transport data, with no semantic authority.
    for node in nodes:
        node["label"] = "Same authored display label"
    edges[0].update(logic_role="reference", ordinal=0,
        source_evidence={"source_revision": "authored-release-2024",
                         "source_sha256": hashlib.sha256(b"Authored source evidence.").hexdigest()})
    before = deepcopy({"graph_nodes": nodes, "graph_edges": edges})
    tables = []
    file_bytes = {}
    for family, rows in {"graph_nodes": nodes, "graph_edges": edges}.items():
        raw = release._encode_parquet_rows(rows, family=family)
        path = tmp_path / (family + ".parquet")
        path.write_bytes(raw)
        file_bytes[path] = raw
        with pq.ParquetFile(path) as parquet:
            table = parquet.read(use_threads=False)
        assert table.num_rows == len(rows)
        wrappers = table.to_pylist()
        assert [json.loads(row["record_json"]) for row in wrappers] == [
            {**row, "family": family} for row in rows]
        assert all(hashlib.sha256(row["record_json"].encode("utf-8")).hexdigest()
                   == row["record_sha256"] for row in wrappers)
        tables.append(table)
    combined = pa.concat_tables(tables)
    original_wrappers = combined.to_pylist()
    result = citation_reader().read_graph_cites(combined)
    assert result == [{"source_legal_id": nodes[0]["legal_id"],
                       "target_legal_id": nodes[1]["legal_id"], "unresolved": False}]
    assert combined.to_pylist() == original_wrappers
    assert {"graph_nodes": nodes, "graph_edges": edges} == before
    assert all(path.read_bytes() == raw for path, raw in file_bytes.items())


def graph_bodies():
    families = release.fixture_family_rows()
    return deepcopy(families["graph_nodes"]), deepcopy(families["graph_edges"])


def wrapped_rows(nodes, edges):
    """Use the existing real release encoder, including its wrapper hashes."""
    result = []
    for family, rows in (("graph_nodes", nodes), ("graph_edges", edges)):
        if rows:
            raw = release._encode_parquet_rows(rows, family=family)
            with pq.ParquetFile(pa.BufferReader(raw)) as parquet:
                result.extend(parquet.read(use_threads=False).to_pylist())
    return result


def replace_body(wrapper, body):
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    wrapper["record_json"] = encoded
    wrapper["record_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def read_rows(rows):
    # PyArrow otherwise takes column names from the first mapping and can
    # silently omit a deliberately malformed field present on a later edge.
    keys = tuple(dict.fromkeys(key for row in rows for key in row))
    table = pa.Table.from_pylist([{key: row.get(key) for key in keys} for row in rows])
    before = table.to_pylist()
    try:
        return citation_reader().read_graph_cites(table)
    finally:
        assert table.to_pylist() == before


def expected_citation(nodes):
    return {"source_legal_id": nodes[0]["legal_id"],
            "target_legal_id": nodes[1]["legal_id"], "unresolved": False}


def test_current_unresolved_citation_retains_declared_structural_target_without_legal_id():
    nodes, edges = graph_bodies()
    nodes[1].pop("legal_id")
    nodes[1].update(node_type="unresolved_citation", label="Authored unresolved reference")
    edges[0]["edge_type"] = "CITES_UNRESOLVED"
    before = deepcopy((nodes, edges))
    rows = wrapped_rows(nodes, edges)
    assert read_rows(rows) == [{"source_legal_id": nodes[0]["legal_id"],
                               "target_legal_id": "", "unresolved": True}]
    assert json.loads(rows[-1]["record_json"])["target_entry_cid"] == nodes[1]["entry_cid"]
    assert (nodes, edges) == before


def test_current_noncitation_edge_is_validated_and_excluded_from_citation_closure():
    nodes, edges = graph_bodies()
    nodes[1].pop("legal_id")
    nodes[1]["node_type"] = "source_package"
    edges[0]["edge_type"] = "HAS_SOURCE"
    rows = wrapped_rows(nodes, edges)
    before = deepcopy(rows)
    assert read_rows(rows) == []
    assert rows == before


def test_current_unreferenced_structural_node_needs_no_invented_legal_identity():
    nodes, edges = graph_bodies()
    nodes.append({"entry_cid": "sha256:" + "9" * 64, "node_type": "source_package",
                  "label": "Authored retained provenance only"})
    assert read_rows(wrapped_rows(nodes, edges)) == [expected_citation(nodes)]


def test_current_distinct_edge_records_preserve_repeated_citation_occurrences_in_order():
    nodes, edges = graph_bodies()
    second = deepcopy(edges[0])
    second.update(entry_cid="sha256:" + "9" * 64,
                  source_evidence={"source_ordinal": 1})
    edges[0]["source_evidence"] = {"source_ordinal": 0}
    rows = wrapped_rows(nodes, [edges[0], second])
    assert read_rows(rows) == [expected_citation(nodes), expected_citation(nodes)]


PAYLOAD_DAMAGE = (
    ("missing_source", "missing_source_entry_cid"),
    ("missing_target", "missing_target_entry_cid"),
    ("missing_entry", "missing_entry_cid"),
    ("empty_source", "missing_source_entry_cid"),
    ("empty_target", "missing_target_entry_cid"),
    ("invalid_source", "invalid_source_entry_cid"),
    ("wrapper_entry", "entry_cid_parity_mismatch"),
    ("wrapper_legal", "legal_id_parity_mismatch"),
    ("wrapper_family", "family_parity_mismatch"),
    ("record_hash", "record_sha256_mismatch"),
    ("duplicate_json_key", "malformed_record_json"),
    ("nonobject_json", "unsupported_non_object_graph_body"),
)


@pytest.mark.parametrize("damage,code", PAYLOAD_DAMAGE, ids=[row[0] for row in PAYLOAD_DAMAGE])
def test_current_payload_problem_cannot_become_an_unresolved_or_legacy_success(damage, code):
    nodes, edges = graph_bodies()
    rows = wrapped_rows(nodes, edges)
    selected = rows[0] if damage == "wrapper_legal" else rows[-1]
    body = json.loads(selected["record_json"])
    if damage in {"missing_source", "missing_target", "missing_entry"}:
        field = {"missing_source": "source_entry_cid", "missing_target": "target_entry_cid",
                 "missing_entry": "entry_cid"}[damage]
        body.pop(field)
        replace_body(selected, body)
    elif damage in {"empty_source", "empty_target", "invalid_source"}:
        field = "target_entry_cid" if damage == "empty_target" else "source_entry_cid"
        body[field] = "same display label" if damage == "invalid_source" else ""
        replace_body(selected, body)
    elif damage == "wrapper_entry":
        selected["entry_cid"] = "sha256:" + "9" * 64
    elif damage == "wrapper_legal":
        selected["legal_id"] = "usc:us:1:999"
    elif damage == "wrapper_family":
        selected["family"] = "graph_nodes"
    elif damage == "record_hash":
        selected["record_sha256"] = "0" * 64
    elif damage == "duplicate_json_key":
        encoded = selected["record_json"]
        selected["record_json"] = '{"edge_type":"CITES",' + encoded[1:]
        selected["record_sha256"] = hashlib.sha256(selected["record_json"].encode()).hexdigest()
    else:
        assert damage == "nonobject_json"
        replace_body(selected, ["CITES", nodes[0]["entry_cid"], nodes[1]["entry_cid"]])
    before = deepcopy(rows)
    with pytest.raises(ValueError, match=code):
        read_rows(rows)
    assert rows == before


@pytest.mark.parametrize("alias", ("node_id", "src", "dst", "source_node_cid"))
def test_current_conflicting_identity_alias_never_overrides_the_explicit_namespace(alias):
    nodes, edges = graph_bodies()
    rows = wrapped_rows(nodes, edges)
    selected = rows[0] if alias == "node_id" else rows[-1]
    body = json.loads(selected["record_json"])
    body[alias] = "sha256:" + "9" * 64
    replace_body(selected, body)
    with pytest.raises(ValueError, match="conflicting_identity_alias"):
        read_rows(rows)


def test_current_agreeing_aliases_are_observations_and_do_not_change_endpoint_identity():
    nodes, edges = graph_bodies()
    for node in nodes:
        node["node_id"] = node["entry_cid"]
    edges[0].update(src=edges[0]["source_entry_cid"], dst=edges[0]["target_entry_cid"],
                    edge_cid=edges[0]["entry_cid"])
    assert read_rows(wrapped_rows(nodes, edges)) == [expected_citation(nodes)]


@pytest.mark.parametrize("origin", ("wrapper", "body"))
def test_current_unknown_explicit_schema_never_selects_a_different_transport(origin):
    nodes, edges = graph_bodies()
    rows = wrapped_rows(nodes, edges)
    if origin == "wrapper":
        rows[-1]["schema_version"] = "uscode-future-graph/v999"
    else:
        body = json.loads(rows[-1]["record_json"])
        body["schema_version"] = "uscode-future-graph/v999"
        replace_body(rows[-1], body)
    with pytest.raises(ValueError, match="unsupported_graph_schema_version"):
        read_rows(rows)


@pytest.mark.parametrize("missing", ("entry_cid", "legal_id", "family", "record_sha256", "record_json"))
def test_partial_current_wrapper_is_not_downgraded_to_a_legacy_projection(missing):
    nodes, edges = graph_bodies()
    table = pa.Table.from_pylist(wrapped_rows(nodes, edges)).drop([missing])
    before = table.to_pylist()
    with pytest.raises(ValueError):
        citation_reader().read_graph_cites(table)
    assert table.to_pylist() == before


@pytest.mark.parametrize("duplicate", ("node", "edge", "cross_family"))
def test_current_duplicate_record_identities_refuse_instead_of_silent_deduplication(duplicate):
    nodes, edges = graph_bodies()
    if duplicate == "node":
        nodes.append(deepcopy(nodes[0]))
    elif duplicate == "edge":
        edges.append(deepcopy(edges[0]))
    else:
        edges[0]["entry_cid"] = nodes[0]["entry_cid"]
    with pytest.raises(ValueError):
        read_rows(wrapped_rows(nodes, edges))


@pytest.mark.parametrize("endpoint", ("source_entry_cid", "target_entry_cid"))
def test_current_dangling_endpoint_cannot_masquerade_as_a_legal_id(endpoint):
    nodes, edges = graph_bodies()
    edges[0][endpoint] = "sha256:" + "9" * 64
    with pytest.raises(ValueError):
        read_rows(wrapped_rows(nodes, edges))


@pytest.mark.parametrize("endpoint_index", (0, 1), ids=("source", "target"))
def test_current_resolved_citation_requires_both_nodes_declared_legal_identities(endpoint_index):
    nodes, edges = graph_bodies()
    nodes[endpoint_index].pop("legal_id")
    nodes[endpoint_index]["node_type"] = "source_package"
    with pytest.raises(ValueError):
        read_rows(wrapped_rows(nodes, edges))


def test_legacy_flat_citations_keep_direct_legal_ids_and_explicit_unresolved_target():
    rows = [
        {"record_kind": "node", "node_type": "section", "label": "Section 9",
         "legal_id": "usc:us:1:9", "node_id": "legacy-node-9", "graph_kind": "", "src": "", "dst": ""},
        {"record_kind": "edge", "node_type": "", "label": "CITES", "legal_id": "", "node_id": "",
         "graph_kind": "CITES", "src": "usc:us:1:1", "dst": "legacy-node-9"},
        {"record_kind": "edge", "node_type": "", "label": "CITES", "legal_id": "", "node_id": "",
         "graph_kind": "CITES", "src": "usc:us:1:9", "dst": "usc:us:1:8"},
        {"record_kind": "edge", "node_type": "", "label": "CITES_UNRESOLVED", "legal_id": "", "node_id": "",
         "graph_kind": "CITES_UNRESOLVED", "src": "usc:us:1:1", "dst": ""},
        {"record_kind": "edge", "node_type": "", "label": "HAS_SOURCE", "legal_id": "", "node_id": "",
         "graph_kind": "HAS_SOURCE", "src": "usc:us:1:1", "dst": "legacy-package"},
    ]
    assert read_rows(rows) == [
        {"source_legal_id": "usc:us:1:1", "target_legal_id": "usc:us:1:9", "unresolved": False},
        {"source_legal_id": "usc:us:1:9", "target_legal_id": "usc:us:1:8", "unresolved": False},
        {"source_legal_id": "usc:us:1:1", "target_legal_id": "", "unresolved": True},
    ]


def test_legacy_wrapped_aliases_remain_separate_from_the_current_five_field_profile(tmp_path):
    bodies = [
        {"node_type": "section", "node_cid": "legacy-a", "legal_id": "usc:us:1:1"},
        {"node_type": "section", "node_cid": "legacy-b", "legal_id": "usc:us:1:2"},
        {"edge_type": "CITES", "source": "legacy-a", "target": "legacy-b"},
    ]
    table = pa.Table.from_pylist([{"record_json": json.dumps(row)} for row in bodies])
    path = tmp_path / "legacy-wrapped.parquet"
    pq.write_table(table, path)
    raw = path.read_bytes()
    with pq.ParquetFile(path) as parquet:
        replayed = parquet.read(use_threads=False)
    assert citation_reader().read_graph_cites(replayed) == [
        {"source_legal_id": "usc:us:1:1", "target_legal_id": "usc:us:1:2", "unresolved": False}]
    assert replayed.to_pylist() == table.to_pylist() and path.read_bytes() == raw
