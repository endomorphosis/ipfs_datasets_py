"""Bind one real US Code definition and a second statutory spelling.

The rows come from justicedao/ipfs_uscode revision
5016b86a273ce5e4ffd066c5ae9f5fe494dd417e. The caller declaration is
unreviewed. A successful ``lake build Legal`` locks fingerprints only.
"""

import hashlib
import importlib.util
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import corpus_parent_occurrence_adapter as parent_owner
from ipfs_datasets_py.logic.autoformal import legal_semantic_graph as graph
from ipfs_datasets_py.logic.autoformal import legal_source_definition_bridge_v2 as bridge
from ipfs_datasets_py.logic.autoformal.lean_units import probe_lean_source, render_term_lean


REVISION = "5016b86a273ce5e4ffd066c5ae9f5fe494dd417e"
PARQUET = Path.home() / ".cache/huggingface/hub/datasets--justicedao--ipfs_uscode/snapshots" / REVISION / "uscode_parquet/laws.parquet"
DEFINITION = {
    "ipfs_cid": "bafkreig4hls5clk3wa5iec5oa575e7gcpnyn3smiicsxgucu4yl654cvnu",
    "title_number": "1",
    "section_number": "8",
    "sha256": "fb6eb7e04f50bdba72b954864e4cdc9dcf0a0857e6cc9a5b6e1544b234c64c2a",
    "legal_id": "usc:us:1:8",
}
SECOND_USE = {
    "ipfs_cid": "bafkreihd2kvpadnqo2bwhjti7sq3kunzamoicottjgy32kva6eduqkcvru",
    "title_number": "10",
    "section_number": "1059",
    "sha256": "6e1086c76b41205ed5caafe80a80ff240b68f6c89484b9d6b3d78f8db8c67bf2",
    "legal_id": "usc:us:10:1059",
}
HEAD = "born alive"
BODY = "the complete expulsion or extraction"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_rows():
    if not PARQUET.is_file():
        pytest.skip("pinned ipfs_uscode snapshot is not in the local Hugging Face cache")
    wanted = {DEFINITION["ipfs_cid"]: DEFINITION, SECOND_USE["ipfs_cid"]: SECOND_USE}
    found = {}
    for batch in pq.ParquetFile(PARQUET).iter_batches(
        batch_size=8000, columns=["ipfs_cid", "title_number", "section_number", "text"]
    ):
        cids = batch.column("ipfs_cid").to_pylist()
        titles = batch.column("title_number").to_pylist()
        sections = batch.column("section_number").to_pylist()
        texts = batch.column("text").to_pylist()
        for index, cid in enumerate(cids):
            pin = wanted.get(cid)
            if pin is None:
                continue
            text = texts[index]
            assert str(titles[index]) == pin["title_number"]
            assert str(sections[index]) == pin["section_number"]
            assert sha(text.encode()) == pin["sha256"]
            found[cid] = text
        if len(found) == len(wanted):
            break
    assert set(found) == set(wanted)
    return found[DEFINITION["ipfs_cid"]], found[SECOND_USE["ipfs_cid"]]


def span(text, literal, start):
    end = start + len(literal)
    assert text[start:end] == literal
    return {"char_start": start, "char_end": end, "text": literal}


def graph_helpers():
    path = Path(__file__).with_name("test_plaintext_graph_custody.py")
    spec = importlib.util.spec_from_file_location("uscode_born_alive_graph_helpers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pinned_born_alive_definition_and_second_spelling_stay_unadmitted(tmp_path):
    definition_text, second_text = load_rows()
    scope_at = definition_text.find("in this section")
    head_at = definition_text.find('"born alive"', scope_at) + 1
    means_at = definition_text.find("means", head_at)
    body_at = definition_text.find(BODY, means_at)
    assert 0 <= scope_at < head_at < means_at < body_at
    helpers = graph_helpers()
    data = helpers.helper("test_corpus_parent_occurrence_adapter").case(
        tmp_path, source_text=HEAD, parent_texts=[definition_text, second_text]
    )
    bundle = parent_owner.build_parent_occurrence_corpus(**data["arguments"])
    parent = {"data": data, "bundle": bundle,
        "records": {record["record_cid"]: record for record in bundle["records"]}}
    regions = bundle["manifest"]["populations"]["roles"]["region"]
    assert len(regions) >= 2
    companion = parent["records"][regions[0]]
    inputs = helpers.binding_arguments(parent, companion)
    bound = helpers.bind(parent, companion)
    scope = graph.bind_parent_scope(source=bound, jurisdiction="declared-US-federal",
        instrument="ipfs_uscode@5016b86a", applicability="unreviewed caller scope",
        definition_scope="unreviewed literal section declaration")
    contributor = span(definition_text, definition_text[scope_at:body_at + len(BODY)], scope_at)
    request = {"schema": bridge.PARENT_REQUEST_SCHEMA, "profile": bridge.PARENT_PROFILE,
        "family": "fol", "declaration": {
            "declaration_id": "usc-1-8-born-alive",
            "interpretation_status": "unreviewed_caller_declaration",
            "source_binding_sha256": bound["source_binding_sha256"],
            "scope": scope, "scope_kind": "section",
            "scope_span": span(definition_text, "in this section", scope_at),
            "contributor_spans": [contributor],
            "head": span(definition_text, HEAD, head_at),
            "definition_cue": span(definition_text, "means", means_at),
            "body": {"op": "atom", "span": span(definition_text, BODY, body_at)}}}
    report = bridge.prepare_parent_definition_v1(request, **inputs)
    assert report["source_version"]["edition"] == parent_owner.UNDECLARED_EDITION
    assert report["native"]["exact_native_ast_roundtrip"] is True
    assert "∀" in report["lean_body"] and "↔" in report["lean_body"]
    assert all(value is False for value in report["authority"].values())
    assert report["governing_scope_verified"] is False
    assert bridge.validate_parent_definition_v1(report, request, **inputs)
    second_at = second_text.find(HEAD)
    assert second_at >= 0 and second_text[second_at:second_at + len(HEAD)] == HEAD
    assert sha(second_text.encode()) == SECOND_USE["sha256"]
    source = render_term_lean("object", HEAD, statute_ids=[DEFINITION["legal_id"], SECOND_USE["legal_id"]])
    probed = probe_lean_source(source)
    assert probed["lake_ok"] is True
    assert probed["admitted"] is False
    assert probed["formalized"] is False
    assert "sorry" not in source and "axiom" not in source
