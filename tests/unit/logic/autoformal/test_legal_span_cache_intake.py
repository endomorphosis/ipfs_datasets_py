"""Direct authentic cache shapes, strict source custody, and all-row retention."""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.autoformal import legal_span_cache_intake as subject
from ipfs_datasets_py.logic.autoformal import legal_semantic_graph as graphs
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
from ipfs_datasets_py.logic.autoformal import span_cache

URL = "https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-sec1.htm"
TEXT = "Agency must file notice."
RAW = (f'<meta charset="utf-8"><h3 class="section-head">§1. Fictional source fixture</h3>'
       f'<p class="statutory-body">(a) {TEXT}</p>'
       f'<p class="statutory-body">(b) {TEXT}</p>').encode()
RULE = {"modality": "O", "actor": "Agency", "action": "file", "object": "notice",
        "conditions": [], "exceptions": [], "temporal": []}
CACHE = {"repository": "justicedao/uscode-autoformal-span-cache", "revision": "a" * 40,
         "artifact_sha256": "b" * 64}


def fixture():
    document = context.extract_document(RAW, url=URL, edition=2024, legal_id="usc:us:10:1")
    selectors = context.exact_view_occurrences(document, RAW, text=TEXT)
    scope = graphs.bind_scope(jurisdiction="US-federal", instrument="USCode", edition=2024,
                              applicability="section-local", definition_scope="usc:us:10:1")
    row = span_cache.span_export_fields({"source_span_id": "span-0", "source_sha256": context.sha(TEXT),
        "source_text": TEXT, "legal_id": document["legal_id"], "status": "sealed", "rule": deepcopy(RULE)})
    row["unknown_future_metadata"] = {"preserve": [None, True, "é"]}
    binding = subject.make_source_binding(document, RAW, document_revision="source-release-2024",
        scope=scope, candidate_selectors=[selectors[0]], context_observation={"status": "unreviewed"})
    return row, {row["source_span_id"]: binding}, selectors


def trusted(rows, bindings, *, start=11):
    return {"cache_identity": deepcopy(CACHE), "start_ordinal": start,
        "expected_row_sha256s": [subject.row_sha256(row) for row in rows],
        "expected_record_sha256s": [subject.record_sha256(row, ordinal=start + index, cache_identity=CACHE)
                                     for index, row in enumerate(rows)],
        "source_bindings": bindings, "expected_source_bindings_sha256": subject.source_bindings_sha256(bindings)}


def intake(rows, bindings):
    return subject.prepare_span_cache_intake(rows, **trusted(rows, bindings))


def test_direct_span_export_row_produces_real_source_bound_proposal_without_manual_ast():
    row, bindings, _ = fixture()
    assert set(span_cache.SPAN_EXPORT_COLUMNS) <= set(row)
    row.update(admitted=True, formalized=True)
    result = intake([row], bindings)
    observed = result["rows"][0]
    assert observed["raw_row"] == row
    assert observed["raw_row"]["unknown_future_metadata"] == row["unknown_future_metadata"]
    assert observed["row_ordinal"] == 11
    assert observed["disposition"] == "proposed_unreviewed_graph"
    assert graphs.graph_to_ast(observed["graph"]) == {"rules": [RULE]}
    assert observed["graph_request"]["source"]["selector"]["text"] == TEXT
    assert all(result[key] is False and observed[key] is False for key in subject._FALSE)


@pytest.mark.parametrize("status", ["pending", "gap", "unsealed", None, "unexpected_status"])
def test_every_unresolved_status_is_retained_with_original_raw_data(status):
    row, bindings, _ = fixture()
    if status is None: row.pop("status")
    else: row["status"] = status
    result = intake([row], bindings)
    observed = result["rows"][0]
    assert observed["raw_row"] == row
    assert observed["graph"] is None and observed["disposition"] == "unresolved"
    assert observed["rule_assessment"]["ast"] == {"rules": [RULE]}
    assert result["row_count"] == 1


def test_conflicting_explicit_status_and_boolean_cannot_override_custody():
    row, bindings, _ = fixture()
    row.update(sealed=False, admitted=True, formalized=True)
    result = intake([row], bindings)["rows"][0]
    assert result["graph"] is None
    assert "conflicting_cache_status_flags" in {x["code"] for x in result["issues"]}


@pytest.mark.parametrize("raw", ['{"modality":"O","modality":"F"}', '{"rules":NaN}',
                                '{"rules":Infinity}', '{broken', '[1,2]', '{"invented":"structure"}'])
def test_malformed_duplicate_nonfinite_or_unsupported_rule_is_never_coerced_to_empty(raw):
    row, bindings, _ = fixture()
    row["rule_json"] = raw
    result = intake([row], bindings)["rows"][0]
    assert result["raw_row"]["rule_json"] == raw
    assert result["rule_assessment"]["status"] in ("malformed_rule_json", "unsupported_rule_ast")
    assert result["graph"] is None


def test_rule_and_qualifier_order_multiplicity_and_case_are_not_validator_normalized():
    row, bindings, _ = fixture()
    first = {**RULE, "modality": "P", "conditions": ["z", "a", "z"], "exceptions": ["later", "earlier"]}
    ast = {"rules": [first, deepcopy(RULE), deepcopy(RULE)]}
    row["rule_json"] = json.dumps(ast)
    report = intake([row], bindings)["rows"][0]
    assert report["rule_assessment"]["ast"] == ast
    assert graphs.graph_to_ast(report["graph"]) == ast


def test_legacy_rule_object_and_aliases_are_explicit_and_conflicts_remain_unresolved():
    row, bindings, _ = fixture()
    row["rule"] = json.loads(row.pop("rule_json"))
    row["id"] = row.pop("source_span_id")
    row["text"] = row.pop("source_text")
    report = intake([row], bindings)["rows"][0]
    assert report["graph"] is not None
    assert report["raw_row"] == row
    row["source_span_id"] = "different-span"
    assert intake([row], bindings)["rows"][0]["graph"] is None


def test_two_rule_channels_must_agree_without_preference_or_repair():
    row, bindings, _ = fixture()
    row["rule"] = {**RULE, "modality": "F"}
    report = intake([row], bindings)["rows"][0]
    assert report["rule_assessment"]["status"] == "conflicting_rule_channels"
    assert report["graph"] is None


def test_ambiguous_physical_occurrences_are_not_selected_by_first_match():
    row, bindings, selectors = fixture()
    bindings["span-0"]["candidate_selectors"] = selectors
    observed = intake([row], bindings)["rows"][0]
    assert observed["source_binding"] is None and observed["graph"] is None
    issue = next(x for x in observed["issues"] if x["code"] == "ambiguous_physical_occurrence_candidates")
    assert issue["occurrence_ids"] == [s["occurrence_id"] for s in selectors]


@pytest.mark.parametrize("damage", ["text", "hash", "legal_id", "revision", "revision_alias", "selector", "scope"])
def test_source_revision_scope_unicode_geometry_and_complete_text_must_match(damage):
    row, bindings, _ = fixture()
    if damage == "text": row["source_text"] += " "
    elif damage == "hash": row["source_sha256"] = "0" * 64
    elif damage == "legal_id": row["legal_id"] = "usc:us:10:2"
    elif damage == "revision": row["source_revision"] = "different-source-release"
    elif damage == "revision_alias":
        row["source_revision"] = "source-release-2024"
        row["revision"] = "different-source-release"
    elif damage == "selector": bindings["span-0"]["candidate_selectors"][0]["utf8_byte_start"] += 1
    else: bindings["span-0"]["scope"]["edition"] = 2025
    assert intake([row], bindings)["rows"][0]["graph"] is None


def test_unicode_source_requires_exact_complete_text_without_normalization_or_copying():
    text = "Agéncy must file café notice."
    raw = RAW.replace(TEXT.encode(), text.encode())
    document = context.extract_document(raw, url=URL, edition=2024, legal_id="usc:us:10:1")
    selectors = context.exact_view_occurrences(document, raw, text=text)
    row, bindings, _ = fixture()
    row.update(source_text=text, source_sha256=context.sha(text))
    bindings["span-0"] = subject.make_source_binding(document, raw, document_revision="source-release-2024",
        scope=bindings["span-0"]["scope"], candidate_selectors=[selectors[0]])
    report = intake([row], bindings)["rows"][0]
    assert report["graph"] is not None
    assert report["source_binding"]["selector"]["utf8_byte_end"] > report["source_binding"]["selector"]["char_end"]
    row.update(source_text=text.replace("é", "e\u0301"), source_sha256=context.sha(text.replace("é", "e\u0301")))
    assert intake([row], bindings)["rows"][0]["graph"] is None


def test_raw_rows_repeated_presentations_ordinals_and_unknown_fields_are_never_deduplicated():
    row, bindings, _ = fixture()
    rows = [row, deepcopy(row), {**row, "status": "gap"}]
    report = intake(rows, bindings)
    assert report["row_count"] == len(report["rows"]) == 3
    assert [x["raw_row"] for x in report["rows"]] == rows
    assert [x["row_ordinal"] for x in report["rows"]] == [11, 12, 13]
    assert report["rows"][0]["raw_row_sha256"] == report["rows"][1]["raw_row_sha256"]
    assert report["rows"][0]["record_id"] != report["rows"][1]["record_id"]
    assert report["rows"][2]["graph"] is None


def test_independent_population_and_binding_pins_reject_omission_reordering_and_retargeting():
    row, bindings, selectors = fixture()
    rows = [row, {**row, "status": "pending"}]
    original = trusted(rows, bindings)
    for altered in (rows[:1], list(reversed(rows))):
        with pytest.raises(ValueError): subject.prepare_span_cache_intake(altered, **original)
    wrong_ordinal = {**original, "start_ordinal": 12}
    with pytest.raises(ValueError, match="ordinal or revision"):
        subject.prepare_span_cache_intake(rows, **wrong_ordinal)
    bindings["span-0"]["candidate_selectors"] = [selectors[1]]
    with pytest.raises(ValueError, match="binding map pin"):
        subject.prepare_span_cache_intake(rows, **original)


def test_report_resealing_cannot_promote_authority_or_drop_unresolved_rows():
    row, bindings, _ = fixture()
    rows = [row, {**row, "status": "gap"}]
    args = trusted(rows, bindings)
    report = subject.prepare_span_cache_intake(rows, **args)
    report["rows"].pop()
    report["admitted"] = True
    report["intake_sha256"] = subject._digest({k: v for k, v in report.items() if k != "intake_sha256"})
    with pytest.raises(ValueError, match="independently pinned regeneration"):
        subject.validate_span_cache_intake(report, rows, **args)


def test_empty_missing_or_malformed_binding_is_explicit_not_a_row_drop():
    row, _, _ = fixture()
    for bindings in ({}, {"span-0": {}}, {"span-0": "malformed declaration"}):
        report = intake([row], bindings)
        assert report["row_count"] == 1 and report["rows"][0]["graph"] is None


def paired_row():
    return {"schema_version": "uscode-paired-span-census/v1", "repository_id": CACHE["repository"],
        "source": {"span_id": "paired-0", "text": TEXT, "text_sha256": context.sha(TEXT),
                   "legal_id": "usc:us:10:1", "revision": "source-release-2024", "constitution": False},
        "autoencoder": {"status": "guided_output", "model_identity": "legacy-mock-diagnostic:sha256:fixture",
                        "embedding_model": "mock:stable-sha256", "complete": True,
                        "formal_outputs": [{"family": "frame", "format": "modal-ir-formula/v1",
                                            "payload_json": "{}", "target_conditioned": True}]},
        "compiler": {"status": "abstain", "complete": True, "canonical_complete": False},
        "comparison": {"status": "diagnostic_agree", "independent": False},
        "admitted": True, "formalized": True, "unknown_future_paired": ["preserved"]}


def test_actual_paired_transport_is_observation_only_even_with_complete_or_admitted_flags():
    row = paired_row()
    report = intake([row], {})
    observed = report["rows"][0]
    assert observed["raw_row"] == row
    assert observed["row_transport"] == "uscode-paired-span-census/v1"
    assert observed["graph"] is None and observed["disposition"] == "unresolved"
    assert {"paired_cache_observation_only_no_span_rule_transport", "mock_or_diagnostic_producer_observation",
            "target_conditioned_formal_output_observation", "canonical_source_coverage_unverified"} <= {
                issue["code"] for issue in observed["issues"]}
    assert report["admitted"] is False


def test_entity_cache_boundary_retains_unresolved_and_repeated_populations_without_calling_cache():
    class NoCalls:
        def build_proposed_graphs(self, *args, **kwargs):
            raise AssertionError("must not filter unresolved or repeated rows into EntityCache")

    row, bindings, _ = fixture()
    rows = [row, {**row, "status": "gap"}]
    result = subject.prepare_entity_cache_graphs(NoCalls(), "section:1", rows, **trusted(rows, bindings))
    assert result["entity_cache_proposal"] is None and result["intake"]["row_count"] == 2
    rows = [row, deepcopy(row)]
    result = subject.prepare_entity_cache_graphs(NoCalls(), "section:1", rows, **trusted(rows, bindings))
    assert result["disposition"] == "unresolved_repeated_physical_binding"


def test_bounded_batch_and_nonfinite_raw_fields_refuse_without_prefix_or_coercion(monkeypatch):
    row, bindings, _ = fixture()
    rows = [row, deepcopy(row)]
    args = trusted(rows, bindings)
    monkeypatch.setattr(subject, "MAX_ROWS", 1)
    with pytest.raises(ValueError, match="bounded nonempty"):
        subject.prepare_span_cache_intake(rows, **args)
    with pytest.raises(ValueError, match="finite"):
        subject.row_sha256({"future_metric": float("nan")})


@pytest.mark.parametrize("value", [{1: "would-be-coerced", "1": "collision"}, ("would", "be", "coerced")])
def test_nested_non_json_values_are_rejected_without_silent_raw_row_conversion(value):
    with pytest.raises(ValueError, match="plain JSON"):
        subject.row_sha256({"unknown_future_field": value})


def test_actual_entity_cache_entrypoint_receives_the_complete_direct_row_population(tmp_path):
    from ipfs_datasets_py.logic.autoformal.entity_cache import EntityCache, INPUT_SCHEMA, DATASET_ID, SCHEMA

    row, bindings, selectors = fixture()
    second = {**row, "source_span_id": "span-1"}
    bindings["span-1"] = deepcopy(bindings["span-0"])
    bindings["span-1"]["candidate_selectors"] = [selectors[1]]
    cache = EntityCache(tmp_path / "entity.duckdb")
    entities = [{"id": key, "type": kind, "label": key, "properties_json": "{}"} for key, kind in (
        ("doc:1", "legal_document"), ("section:1", "section"), ("title:10", "usc_title"))]
    links = [{"type": "IN_TITLE", "source": "doc:1", "target": "title:10"},
             {"type": "HAS_SECTION", "source": "doc:1", "target": "section:1"}]
    cache.bind_inputs({"schema_version": INPUT_SCHEMA, "dataset_id": DATASET_ID,
        "entity_identity_schema": SCHEMA, "entities": {"sha256": "a" * 64, "bytes": 100, "row_count": 3},
        "relationships": {"sha256": "b" * 64, "bytes": 100, "row_count": 2}}, resume=False)
    cache.enqueue_source_batch(entities, 0, 3, verify_inputs=lambda: None)
    cache.prepare_containment_batches([links], verify_inputs=lambda: None)
    before = cache._db.execute("SELECT * FROM entity_queue ORDER BY entity_id").fetchall()
    try:
        result = subject.prepare_entity_cache_graphs(cache, "section:1", [row, second],
                                                     **trusted([row, second], bindings))
        assert result["disposition"] == "proposed_unreviewed_entity_graphs"
        assert result["entity_cache_proposal"]["occurrence_count"] == 2
        assert all(graphs.graph_to_ast(r["graph"]) == {"rules": [RULE]}
                   for r in result["entity_cache_proposal"]["rows"])
        assert cache._db.execute("SELECT * FROM entity_queue ORDER BY entity_id").fetchall() == before
    finally:
        cache.close()
