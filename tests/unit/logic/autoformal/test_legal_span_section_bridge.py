"""Exact source fixtures through the real primary index and public span intake."""
from copy import deepcopy
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_span_section_bridge as bridge
from ipfs_datasets_py.logic.autoformal import legal_span_cache_intake as intake
from ipfs_datasets_py.logic.autoformal import legal_primary_graph_manifest as manifests
from ipfs_datasets_py.logic.autoformal import legal_primary_graph_reconstruction as reconstruction
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
from ipfs_datasets_py.logic.autoformal import legal_semantic_graph as graphs
from ipfs_datasets_py.logic.autoformal import span_cache

PRIMARY_REVISION = "a" * 40
SOURCE_REVISION = "b" * 40
LEGAL_ID = "usc:us:10:1"
TEXT = "Agency must file café notice."
RAW = (f'<meta charset="utf-8"><h3 class="section-head">§1. Fictional bridge fixture</h3>'
       f'<p class="statutory-body">(a) {TEXT}</p><p class="statutory-body">(b) {TEXT}</p>').encode()
RULE = {"modality": "O", "actor": "Agency", "action": "file", "object": "café notice",
        "conditions": [], "exceptions": [], "temporal": []}
CACHE = {"repository": "fixture/span-cache", "revision": "c" * 40, "artifact_sha256": "d" * 64}


def cid(text):
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def wrapped(body):
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    return {"entry_cid": body["entry_cid"], "legal_id": body.get("legal_id") or "", "family": body["family"],
            "record_sha256": hashlib.sha256(raw.encode()).hexdigest(), "record_json": raw}


def primary_fixture(tmp_path, *, duplicate=False, missing=False):
    root = tmp_path / "primary"
    root.mkdir()
    nodes = [wrapped({"entry_cid": cid("section"), "family": "graph_nodes", "node_type": "section",
                      "legal_id": "usc:us:10:999" if missing else LEGAL_ID}),
             wrapped({"entry_cid": cid("package"), "family": "graph_nodes", "node_type": "source_package",
                      "label": "declared source metadata, not raw HTML checksum"})]
    if duplicate:
        nodes.append(wrapped({"entry_cid": cid("other-section"), "family": "graph_nodes", "node_type": "section", "legal_id": LEGAL_ID}))
    edges = [wrapped({"entry_cid": cid("relation"), "family": "graph_edges", "edge_type": "HAS_SOURCE",
                      "source_entry_cid": cid("section"), "target_entry_cid": cid("package")})]
    descriptors = []
    for family, rows in (("graph_nodes", nodes), ("graph_edges", edges)):
        relative = "data/graph/" + ("nodes" if family == "graph_nodes" else "edges") + "/part-000000.parquet"
        path = root / relative
        path.parent.mkdir(parents=True)
        pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema([(key, pa.string()) for key in manifests.FIELDS])), path)
        descriptors.append({"family": family, "first_key": None, "last_key": None,
            "media_type": "application/vnd.apache.parquet", "relative_path": relative, "row_count": len(rows),
            "schema_id": "uscode-graph-node/v1" if family == "graph_nodes" else "uscode-graph-edge/v1",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size})
    manifest = {"schema_version": "uscode-sparse-graphrag-release-schema-v2", "hf_release_schema_version": "uscode-hf-release/v1",
        "release_profile": "publicus-ir-graphrag/v2", "dataset_repo_id": "fixture/primary",
        "release_point": "us/pl/119/102", "release_root_cid": cid("release"), "source_revision": SOURCE_REVISION,
        "graph_ontology_version": "uscode-legal-graph-ontology/v1", "producer": "uscode_hf_release.py", "artifacts": descriptors}
    manifest["manifest_digest"] = manifests.digest(manifest)
    raw = json.dumps(manifest).encode()
    selection = manifests.select_primary_graph_manifest(raw, expected_manifest_sha256=hashlib.sha256(raw).hexdigest(),
        repository="fixture/primary", revision=PRIMARY_REVISION,
        expected_release_identity={key: manifest[key] for key in manifests.RELEASE_FIELDS},
        expected_graph_population={"graph_nodes": {"files": 1, "rows": len(nodes)}, "graph_edges": {"files": 1, "rows": 1}})
    candidate = tmp_path / "candidate.jsonl"
    report = reconstruction.reconstruct_to_jsonl(selection, root, candidate, expected_selection_sha256=selection["selection_sha256"])
    return candidate, report


def span_fixture():
    document = context.extract_document(RAW, url="https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-sec1.htm",
                                        edition=2024, legal_id=LEGAL_ID)
    selectors = context.exact_view_occurrences(document, RAW, text=TEXT)
    row = span_cache.span_export_fields({"source_span_id": "span:1", "source_text": TEXT,
        "source_sha256": context.sha(TEXT), "legal_id": LEGAL_ID, "status": "sealed", "rule": RULE})
    row.update(source_revision=SOURCE_REVISION, unknown_future={"retain": [None, "é", True]})
    scope = graphs.bind_scope(jurisdiction="US", instrument="USCode", edition=2024,
                              applicability="fixture-only", definition_scope=LEGAL_ID)
    bindings = {"span:1": intake.make_source_binding(document, RAW, document_revision=SOURCE_REVISION,
        scope=scope, candidate_selectors=[selectors[0]], context_observation={"claimed_closed": True})}
    return row, bindings, selectors


def policy(rows, bindings, *, mappings=True):
    entries = []
    if mappings:
        for index, row in enumerate(rows):
            entries.append({"record_sha256": intake.record_sha256(row, ordinal=9 + index, cache_identity=CACHE),
                "source_span_id": row["source_span_id"], "source_sha256": row["source_sha256"], "legal_id": row["legal_id"],
                "primary_revision": PRIMARY_REVISION, "source_revision": SOURCE_REVISION, "document_revision": SOURCE_REVISION,
                "document_view_id": bindings[row["source_span_id"]]["candidate_selectors"][0]["view_id"],
                "section_entry_cid": cid("section"), "source_package_entry_cid": cid("package")})
    return {"schema": bridge.POLICY_SCHEMA, "identity_profiles": bridge.PROFILES,
        "legal_id_profile": "literal_declared_usc_legal_id/v1", "revision_profile": "exact_full_git_source_revision/v1",
        "coordinate_profile": "independently_pinned_legal_view_occurrence/v2", "record_mappings": entries}


def trusted(rows, bindings, index, mapping_policy):
    return {"cache_identity": CACHE, "start_ordinal": 9, "section_index": index,
        "expected_section_index_sha256": index.index_sha256, "identity_policy": mapping_policy,
        "expected_identity_policy_sha256": bridge.identity_policy_sha256(mapping_policy), "source_bindings": bindings,
        "expected_source_bindings_sha256": intake.source_bindings_sha256(bindings),
        "expected_row_sha256s": [intake.row_sha256(row) for row in rows],
        "expected_record_sha256s": [intake.record_sha256(row, ordinal=9 + i, cache_identity=CACHE) for i, row in enumerate(rows)]}


def open_index(tmp_path, **fixture_options):
    from ipfs_datasets_py.logic.autoformal.legal_primary_section_index import PrimarySectionIndex
    candidate, report = primary_fixture(tmp_path, **fixture_options)
    return PrimarySectionIndex(candidate, reconstruction_report=report,
        expected_candidate_sha256=report["candidate_sha256"], expected_reconstruction_sha256=report["reconstruction_sha256"])


def test_real_index_and_existing_span_intake_bind_a_proposal_with_context_and_correspondence_open(tmp_path):
    row, bindings, _ = span_fixture()
    with open_index(tmp_path) as index:
        args = trusted([row], bindings, index, policy([row], bindings))
        report = bridge.reconcile_span_sections([row], **args)
        observed = report["rows"][0]
        assert observed["graph_proposal"] is not None
        assert graphs.graph_to_ast(observed["graph_proposal"]) == {"rules": [RULE]}
        assert observed["candidate_section"]["entry_cid"] == cid("section")
        assert observed["primary_binding"] == args["identity_policy"]["record_mappings"][0]
        assert observed["raw_row"] == row and observed["row_ordinal"] == 9
        assert observed["original_span_intake"]["disposition"] == "proposed_unreviewed_graph"
        assert observed["obligations"]["context"].startswith("open_")
        assert observed["obligations"]["primary_source_correspondence"].startswith("open_")
        assert all(value is False for value in observed["authority"].values())
        assert bridge.validate_span_section_bridge(report, [row], **args) == report


@pytest.mark.parametrize("damage", ["short_revision", "no_revision", "case_legal_id", "whitespace_legal_id", "bad_text_hash", "alias", "pending", "malformed_rule"])
def test_identity_and_formal_transport_gaps_never_use_section_match_as_source_evidence(tmp_path, damage):
    row, bindings, _ = span_fixture()
    if damage == "short_revision": row["source_revision"] = "ipfs-uscode-5016b86a"
    elif damage == "no_revision": row.pop("source_revision")
    elif damage == "case_legal_id": row["legal_id"] = row["legal_id"].upper()
    elif damage == "whitespace_legal_id": row["legal_id"] += " "
    elif damage == "bad_text_hash": row["source_sha256"] = "0" * 64
    elif damage == "alias": row["id"] = "foreign-span"
    elif damage == "pending": row["status"] = "pending"
    else: row["rule_json"] = '{"x":1,"x":2}'
    with open_index(tmp_path) as index:
        report = bridge.reconcile_span_sections([row], **trusted([row], bindings, index, policy([row], bindings, mappings=False)))
        assert report["rows"][0]["graph_proposal"] is None
        assert report["rows"][0]["raw_row"] == row
        assert report["rows"][0]["issues"]


@pytest.mark.parametrize("kind", ["duplicate", "missing"])
def test_all_exact_section_matches_are_retained_without_first_match(tmp_path, kind):
    row, bindings, _ = span_fixture()
    with open_index(tmp_path, **{kind: True}) as index:
        result = bridge.reconcile_span_sections([row], **trusted([row], bindings, index, policy([row], bindings)))
        observed = result["rows"][0]
        assert len(observed["section_lookup"]["sections"]) == (2 if kind == "duplicate" else 0)
        assert observed["candidate_section"] is None and observed["graph_proposal"] is None


@pytest.mark.parametrize("damage", ["view", "primary_revision", "source_revision", "section", "package", "selector", "missing_binding", "ambiguous_binding"])
def test_independent_mapping_and_occurrence_dimensions_are_not_supplied_by_unique_section(tmp_path, damage):
    row, bindings, selectors = span_fixture()
    mapping_policy = policy([row], bindings)
    mapping = mapping_policy["record_mappings"][0]
    if damage == "view": mapping["document_view_id"] = "legal-normalized-view:sha256:" + "0" * 64
    elif damage == "primary_revision": mapping["primary_revision"] = "9" * 40
    elif damage == "source_revision": mapping.update(source_revision="9" * 40, document_revision="9" * 40)
    elif damage == "section": mapping["section_entry_cid"] = cid("other")
    elif damage == "package": mapping["source_package_entry_cid"] = cid("other")
    elif damage == "selector": bindings["span:1"]["candidate_selectors"][0]["utf8_byte_start"] += 1
    elif damage == "missing_binding": bindings = {}
    else: bindings["span:1"]["candidate_selectors"] = selectors
    with open_index(tmp_path) as index:
        result = bridge.reconcile_span_sections([row], **trusted([row], bindings, index, mapping_policy))
        assert result["rows"][0]["candidate_section"] is not None
        assert result["rows"][0]["graph_proposal"] is None


def test_real_paired_shape_with_short_revision_mock_and_admission_flags_stays_unresolved(tmp_path):
    row = {"schema_version": "uscode-paired-span-census/v1", "repository_id": CACHE["repository"],
        "source": {"span_id": "paired:1", "text": "L.", "text_sha256": context.sha("L."), "legal_id": LEGAL_ID,
                   "revision": "ipfs-uscode-5016b86a", "constitution": False},
        "autoencoder": {"model_identity": "legacy-mock-diagnostic:sha256:fixture", "complete": True,
                        "formal_outputs": [{"target_conditioned": True, "family": "frame", "payload_json": "{}"}]},
        "compiler": {"complete": True, "canonical_complete": False}, "admitted": True, "formalized": True}
    with open_index(tmp_path) as index:
        result = bridge.reconcile_span_sections([row], **trusted([row], {}, index, policy([], {}, mappings=False)))
        observed = result["rows"][0]
        assert observed["candidate_section"] is not None
        assert observed["raw_row"] == row and observed["graph_proposal"] is None
        assert {"paired_formal_transport_unsupported", "unsupported_or_missing_full_source_revision"} <= {x["code"] for x in observed["issues"]}
        assert observed["original_span_intake"]["graph"] is None
        assert all(value is False for value in observed["authority"].values())


def test_paired_transport_remains_unsupported_even_with_full_revision_mapping_and_exact_occurrence(tmp_path):
    flat, bindings, _ = span_fixture()
    row = {"schema_version": "uscode-paired-span-census/v1", "status": "sealed",
        "source": {"span_id": flat["source_span_id"], "text": TEXT, "text_sha256": context.sha(TEXT),
                   "legal_id": LEGAL_ID, "revision": SOURCE_REVISION},
        "autoencoder": {"complete": True, "model_identity": "mock:diagnostic",
                        "formal_outputs": [{"family": "frame", "target_conditioned": True}]},
        "compiler": {"canonical_complete": True}, "admitted": True, "formalized": True}
    mapping_policy = policy([flat], bindings)
    mapping_policy["record_mappings"][0]["record_sha256"] = intake.record_sha256(row, ordinal=9, cache_identity=CACHE)
    with open_index(tmp_path) as index:
        result = bridge.reconcile_span_sections([row], **trusted([row], bindings, index, mapping_policy))
        observed = result["rows"][0]
        assert observed["candidate_section"] is not None
        assert observed["original_span_intake"]["source_binding"] is not None
        assert observed["primary_binding"] == mapping_policy["record_mappings"][0]
        assert observed["graph_proposal"] is None
        assert "paired_formal_transport_unsupported" in {issue["code"] for issue in observed["issues"]}


def test_independent_index_pin_cannot_be_replaced_by_section_legal_id_uniqueness(tmp_path):
    row, bindings, _ = span_fixture()
    with open_index(tmp_path) as index:
        args = trusted([row], bindings, index, policy([row], bindings))
        args["expected_section_index_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="independent section index pin"):
            bridge.reconcile_span_sections([row], **args)


@pytest.mark.parametrize("full_revision_supplied", [False, True])
def test_explicit_flat_evidence_profile_preserves_every_unknown_metric_and_inert_flag(tmp_path, full_revision_supplied):
    row, bindings, _ = span_fixture()
    row.update(schema_version=bridge.EVIDENCE_PROFILE, record_kind="span", repository_id=CACHE["repository"],
        dataset_id="fixture/primary", sealed=True, admitted=True, formalized=True, wrote_compiler=False,
        code_identity="sha256:" + "5" * 64, decoded_text=TEXT, structural="declared diagnostic text",
        formulas_json='[{"op":"O","lake":"duty"}]', citations_json="[]", compiler_status="compiled",
        compiler_reason="", compiler_fields_json="[]", decompiled="Agency must file café notice.",
        repair_error="", repair_fix="", repair_diagnostic="", edit_paths_json="[]", symbols_json="[]",
        repair_json='{"lake":{"command":"lake build Legal"},"census":{"agree":true}}',
        cosine_similarity=0.7302967433402214, embedding_cosine_similarity=0.8390006578569956,
        embedding_cosine_loss=0.16099934214300438, reconstruction_loss=0.0, ir_compression_loss=1/3,
        ir_compression_ratio=3.0, cross_entropy_loss=1.9824436902928904,
        round_trip_cross_entropy_loss=2.0104316130135804, formula_cross_entropy_loss=1.9357971524250737,
        family_cross_entropy_loss=1.1624350255286717, view_cross_entropy_loss=None, measurements=8,
        formula_matches=True, consensus="agree", agrees=True, census_agree=True, lake_ok=True,
        lake_disposition="duty", train=True)
    if not full_revision_supplied:
        row.pop("source_revision")
    with open_index(tmp_path) as index:
        mapping_policy = policy([row], bindings) if full_revision_supplied else policy([], {}, mappings=False)
        supplied = bindings if full_revision_supplied else {}
        result = bridge.reconcile_span_sections([row], **trusted([row], supplied, index, mapping_policy))
        observed = result["rows"][0]
        assert observed["raw_row"] == row
        assert observed["source_identity"]["profile"] == bridge.EVIDENCE_PROFILE
        assert observed["candidate_section"] is not None
        assert (observed["graph_proposal"] is not None) is full_revision_supplied
        assert observed["authority"]["training_qualified"] is False
        assert observed["authority"]["proof_authority"] is False
        assert observed["authority"]["primary_source_correspondence_verified"] is False


def test_order_multiplicity_and_independent_replay_pins_cover_every_raw_row(tmp_path):
    row, bindings, _ = span_fixture()
    rows = [row, deepcopy(row), {**row, "status": "gap"}]
    with open_index(tmp_path) as index:
        args = trusted(rows, bindings, index, policy(rows, bindings))
        report = bridge.reconcile_span_sections(rows, **args)
        assert report["row_count"] == len(report["rows"]) == 3
        assert [r["raw_row"] for r in report["rows"]] == rows
        assert [r["row_ordinal"] for r in report["rows"]] == [9, 10, 11]
        assert report["rows"][0]["record_sha256"] != report["rows"][1]["record_sha256"]
        for changed in (rows[:2], list(reversed(rows))):
            with pytest.raises(ValueError): bridge.reconcile_span_sections(changed, **args)
        args["identity_policy"]["record_mappings"][0]["section_entry_cid"] = cid("retarget")
        with pytest.raises(ValueError, match="identity policy pin"):
            bridge.reconcile_span_sections(rows, **args)


def test_resealed_output_cannot_promote_correspondence_or_drop_unresolved_record(tmp_path):
    row, bindings, _ = span_fixture()
    rows = [row, {**row, "status": "gap"}]
    with open_index(tmp_path) as index:
        args = trusted(rows, bindings, index, policy(rows, bindings))
        report = bridge.reconcile_span_sections(rows, **args)
        report["rows"].pop()
        report["authority"]["primary_source_correspondence_verified"] = True
        report["bridge_sha256"] = bridge._digest({k: v for k, v in report.items() if k != "bridge_sha256"})
        with pytest.raises(ValueError, match="independent complete replay"):
            bridge.validate_span_section_bridge(report, rows, **args)


def test_closed_policy_refuses_alias_revision_expansion_and_duplicate_mapping_pins():
    row, bindings, _ = span_fixture()
    mapping_policy = policy([row], bindings)
    mapping_policy["record_mappings"][0]["source_revision"] = "ipfs-uscode-5016b86a"
    with pytest.raises(ValueError, match="complete literal git revisions"):
        bridge.identity_policy_sha256(mapping_policy)
    mapping_policy = policy([row], bindings)
    mapping_policy["record_mappings"].append(deepcopy(mapping_policy["record_mappings"][0]))
    with pytest.raises(ValueError, match="duplicate source mapping"):
        bridge.identity_policy_sha256(mapping_policy)
