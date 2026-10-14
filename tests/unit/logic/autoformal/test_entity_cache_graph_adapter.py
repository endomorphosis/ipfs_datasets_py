"""Real source graphs from prepared queues; legacy admission never authorizes them."""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.autoformal import entity_cache as cache_module
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_semantic_graph as graphs
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context


URL = "https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-sec1.htm"
TEXT = "Agency must file notice."
RAW = ('<meta charset="utf-8">'
       f'<h3 class="section-head">§1. Fictional graph fixture</h3>'
       f'<p class="statutory-body">(a) {TEXT}</p>'
       f'<p class="statutory-body">(b) {TEXT}</p>').encode()
AST = {"rules": [{"modality": "O", "actor": "Agency", "action": "file", "object": "notice",
                  "conditions": [], "exceptions": [], "temporal": []}]}


def scope(section=1):
    return graphs.bind_scope(jurisdiction="US-federal", instrument="USCode-title10", edition=2024,
                             applicability="section-local", definition_scope=f"usc:us:10:{section}")


def inputs(section=1):
    raw = RAW if section == 1 else RAW.replace("§1".encode(), "§2".encode())
    url = URL if section == 1 else URL.replace("sec1", "sec2")
    document = context.extract_document(raw, url=url, edition=2024, legal_id=f"usc:us:10:{section}")
    selectors = context.exact_view_occurrences(document, raw, text=TEXT)
    occurrences = [{"source_span_id": f"archived:{section}:{index}", "source_sha256": s["text_sha256"],
                    "selector": s, "ast": deepcopy(AST), "profile": "canonical_rules_v1"}
                   for index, s in enumerate(selectors)]
    expected = [{"source_span_id": row["source_span_id"], "occurrence_id": row["selector"]["occurrence_id"],
                 "source_sha256": row["source_sha256"]} for row in occurrences]
    return {"document": document, "raw_html": raw, "document_revision": "release-2024",
            "scope": scope(section), "occurrences": occurrences, "expected_population": expected}


@pytest.fixture
def cache(tmp_path):
    result = cache_module.EntityCache(tmp_path / "cache.duckdb")
    rows = [{"id": key, "type": kind, "label": key, "properties_json": "{}"} for key, kind in (
        ("doc:1", "legal_document"), ("section:1", "section"), ("title:10", "usc_title"),
        ("doc:2", "legal_document"), ("section:2", "section"))]
    edges = [{"type": kind, "source": source, "target": target} for kind, source, target in (
        ("IN_TITLE", "doc:1", "title:10"), ("HAS_SECTION", "doc:1", "section:1"),
        ("IN_TITLE", "doc:2", "title:10"), ("HAS_SECTION", "doc:2", "section:2"))]
    manifest = {"schema_version": cache_module.INPUT_SCHEMA, "dataset_id": cache_module.DATASET_ID,
                "entity_identity_schema": cache_module.SCHEMA,
                "entities": {"sha256": "a" * 64, "bytes": 100, "row_count": len(rows)},
                "relationships": {"sha256": "b" * 64, "bytes": 100, "row_count": len(edges)}}
    result.bind_inputs(manifest, resume=False)
    result.enqueue_source_batch(rows, 0, len(rows), verify_inputs=lambda: None)
    result.prepare_containment_batches([edges], verify_inputs=lambda: None)
    yield result
    result.close()


def cache_state(cache):
    return {table: cache._db.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall()
            for table in ("entity_queue", "agent_lease", "task_board", "cache_meta")}


def test_real_proposed_graphs_preserve_repeated_occurrences_without_legacy_population_filter(cache):
    before = cache_state(cache)
    request = inputs()
    report = cache.build_proposed_graphs("section:1", **request)
    assert report["occurrence_count"] == 2
    assert report["prepared_context"].get("contained_span_ids", []) == []
    first, second = [row["graph"] for row in report["rows"]]
    assert first["graph_id"] != second["graph_id"]
    assert graphs.graph_to_ast(first) == graphs.graph_to_ast(second) == AST
    assert report["observed_population"] == request["expected_population"]
    assert report["population_complete"] is True
    assert report["complete_section_coverage_verified"] is False
    assert report["coverage_scope"] == "exact_supplied_occurrence_population_only"
    assert all(report[key] is False for key in ("admitted", "formalized", "source_semantics_verified",
        "global_consistency_verified", "proof_authority", "training_qualified", "legacy_admission_flags_used"))
    assert cache_state(cache) == before


def test_export_import_roundtrip_revalidates_without_queue_or_resume_mutation(cache):
    request = inputs()
    report = cache.build_proposed_graphs("section:1", **request)
    before = cache_state(cache)
    payload = cache.export_proposed_graphs(report, "section:1", **request)
    assert cache.import_proposed_graphs(payload, "section:1", **request) == report
    assert cache_state(cache) == before


def test_legacy_sealed_and_admission_flags_have_no_graph_authority(cache):
    request = inputs()
    original = cache.build_proposed_graphs("section:1", **request)
    for row in request["occurrences"]:
        row.update(sealed=True, admitted=True, formalized=True, status="sealed")
    assert cache.build_proposed_graphs("section:1", **request) == original
    request["occurrences"][0]["ast"] = {"invented": "invalid despite sealed flag"}
    with pytest.raises(ValueError):
        cache.build_proposed_graphs("section:1", **request)


def test_caller_strictly_adapts_real_span_cache_row_shape_without_rule_field_loss(cache):
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule

    request = inputs()
    supplied = request["occurrences"][0]
    row = {"source_span_id": supplied["source_span_id"], "source_sha256": supplied["source_sha256"],
           "source_text": TEXT, "status": "sealed", "sealed": True,
           "rule_json": json.dumps(AST["rules"][0])}
    # This is an explicit caller adapter, not an implicit legacy queue/HF-row
    # ingest. The existing CanonicalRule contract rejects every unknown field.
    parsed = CanonicalRule.from_dict(json.loads(row["rule_json"])).to_dict()
    supplied.update(source_text=row["source_text"], ast={"rules": [parsed]}, status=row["status"], sealed=True)
    report = cache.build_proposed_graphs("section:1", **request)
    assert graphs.graph_to_ast(report["rows"][0]["graph"]) == {"rules": [parsed]}
    assert report["admitted"] is False
    supplied["source_text"] = "Different text despite a legacy sealed flag."
    with pytest.raises(ValueError, match="source text differs"):
        cache.build_proposed_graphs("section:1", **request)
    unsupported = {**json.loads(row["rule_json"]), "unhandled_temporal_origin": "unknown"}
    with pytest.raises(ValueError):
        CanonicalRule.from_dict(unsupported)


@pytest.mark.parametrize("damage", ["omit", "shuffle", "duplicate", "wrong_hash"])
def test_independent_population_rejects_missing_reordered_or_duplicate_bindings(cache, damage):
    request = inputs()
    if damage == "omit": request["occurrences"].pop()
    elif damage == "shuffle": request["occurrences"].reverse()
    elif damage == "duplicate":
        request["occurrences"][1] = deepcopy(request["occurrences"][0])
        request["expected_population"][1] = deepcopy(request["expected_population"][0])
    else: request["occurrences"][0]["source_sha256"] = "0" * 64
    before = cache_state(cache)
    with pytest.raises(ValueError):
        cache.build_proposed_graphs("section:1", **request)
    assert cache_state(cache) == before


def test_repaired_identical_text_occurrence_cannot_retarget_trusted_population(cache):
    request = inputs()
    request["occurrences"][0]["selector"] = deepcopy(request["occurrences"][1]["selector"])
    with pytest.raises(ValueError, match="expected source population"):
        cache.build_proposed_graphs("section:1", **request)


def test_unresolved_source_without_ast_is_preserved_and_cannot_be_promoted(cache):
    request = inputs()
    request["occurrences"][1].update(ast=None, profile=None, sealed=True, admitted=True)
    report = cache.build_proposed_graphs("section:1", **request)
    assert report["occurrence_count"] == 2
    assert report["rows"][1]["graph"] is None
    assert report["rows"][1]["disposition"] == "unresolved_no_typed_ast"
    assert report["unresolved_occurrence_ids"] == [request["expected_population"][1]["occurrence_id"]]
    assert report["admitted"] is False


def test_scope_edition_document_revision_and_prepared_entity_are_exact(cache):
    request = inputs()
    report = cache.build_proposed_graphs("section:1", **request)
    request["document_revision"] = "release-2025"
    with pytest.raises(ValueError, match="trusted regeneration"):
        cache.import_proposed_graphs(json.dumps(report), "section:1", **request)
    request = inputs()
    request["scope"] = graphs.bind_scope(jurisdiction="US-federal", instrument="USCode-title10", edition=2025,
                                         applicability="section-local", definition_scope="usc:us:10:1")
    with pytest.raises(ValueError, match="edition differs"):
        cache.build_proposed_graphs("section:1", **request)
    with pytest.raises(ValueError, match="legal identity"):
        cache.build_proposed_graphs("section:1", **inputs(2))


def test_claimed_section_cannot_be_repurposed_or_release_its_foreign_lease(cache):
    cache._db.execute("UPDATE entity_queue SET status='claimed',claim_worker='foreign',claim_token='foreign' "
                      "WHERE entity_id='section:1'")
    before = cache_state(cache)
    with pytest.raises(ValueError, match="unclaimed prepared"):
        cache.build_proposed_graphs("section:1", **inputs())
    assert cache_state(cache) == before


def test_changed_prepared_context_and_resealed_admission_are_refused_on_import(cache):
    request = inputs()
    report = cache.build_proposed_graphs("section:1", **request)
    tampered = deepcopy(report)
    tampered["admitted"] = True
    tampered["proposal_sha256"] = cache_module._sha(cache_module._json(
        {k: v for k, v in tampered.items() if k != "proposal_sha256"}))
    with pytest.raises(ValueError, match="trusted regeneration"):
        cache.import_proposed_graphs(json.dumps(tampered), "section:1", **request)
    value = json.loads(cache._db.execute("SELECT context_json FROM entity_queue WHERE entity_id='section:1'").fetchone()[0])
    value["definition_targets"] = ["changed:definition"]
    cache._db.execute("UPDATE entity_queue SET context_json=? WHERE entity_id='section:1'", [json.dumps(value)])
    with pytest.raises(ValueError, match="trusted regeneration"):
        cache.validate_proposed_graphs(report, "section:1", **request)


def test_import_duplicate_json_keys_and_output_bounds_fail_without_partial_queue_mutation(cache, monkeypatch):
    request = inputs()
    report = cache.build_proposed_graphs("section:1", **request)
    payload = json.dumps(report).replace('"schema":', '"schema":"duplicate","schema":', 1)
    with pytest.raises(ValueError):
        cache.import_proposed_graphs(payload, "section:1", **request)
    before = cache_state(cache)
    monkeypatch.setattr(cache_module, "MAX_GRAPH_OCCURRENCES", 1)
    with pytest.raises(ValueError, match="bounded nonempty"):
        cache.build_proposed_graphs("section:1", **request)
    assert cache_state(cache) == before


@pytest.mark.parametrize("changed_kind", ["revision", "definition"])
def test_real_source_graph_dependency_invalidation_preserves_unrelated_graph(cache, changed_kind):
    first = cache.build_proposed_graphs("section:1", **inputs())
    second = cache.build_proposed_graphs("section:2", **inputs(2))
    graph_a, graph_b = first["rows"][0]["graph"], second["rows"][0]["graph"]
    records = []
    for envelope, graph in ((first, graph_a), (second, graph_b)):
        binding = envelope["rows"][0]["source_binding"]
        pins = {kind: [] for kind in dependencies.PIN_KINDS}
        for kind, key, value in (
            ("root", "constructed-campaign", "e" * 64),
            ("source", binding["document_id"], binding["selector"]["text_sha256"]),
            ("revision", binding["document_id"], hashlib.sha256(binding["document_revision"].encode()).hexdigest()),
            ("context", envelope["entity_id"], envelope["prepared_context_sha256"]),
            ("definition", envelope["entity_id"] + ":declared-definition", "b" * 64),
            ("policy", "canonical_rules_v1", hashlib.sha256(b"canonical_rules_v1").hexdigest())):
            pins[kind].append({"key": key, "sha256": value})
        records.append({"artifact_id": graph["graph_id"],
                        "artifact_sha256": hashlib.sha256(cache_module._json(graph).encode()).hexdigest(),
                        "dependency_pins": pins})
    doctrine = {"artifact_id": "constructed:dependent-doctrine-proposal", "artifact_sha256": "d" * 64,
                "dependency_pins": {kind: [] for kind in dependencies.PIN_KINDS}}
    records.append(doctrine)
    manifest = dependencies.build_dependency_manifest(records,
        [{"dependent_id": doctrine["artifact_id"], "dependency_id": graph_a["graph_id"]}],
        expected_artifact_ids=[row["artifact_id"] for row in records])
    observations = {kind: {} for kind in dependencies.PIN_KINDS}
    for row in records:
        for kind, pins in row["dependency_pins"].items():
            observations[kind].update({p["key"]: p["sha256"] for p in pins})
    changed_key = (first["rows"][0]["source_binding"]["document_id"] if changed_kind == "revision"
                   else first["entity_id"] + ":declared-definition")
    observations[changed_kind][changed_key] = "c" * 64
    result = dependencies.invalidate_dependencies(manifest, expected_manifest_sha256=manifest["manifest_sha256"],
        observed_artifact_sha256s={row["artifact_id"]: row["artifact_sha256"] for row in records},
        observed_pins=observations)
    assert result["stale_artifact_ids"] == [graph_a["graph_id"], doctrine["artifact_id"]]
    assert result["reusable_under_declared_dependencies"] == [graph_b["graph_id"]]
    assert result["global_consistency_verified"] is False
