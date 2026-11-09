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


# Coordinate graph intake is a distinct, opt-in contract. These authored inputs
# run the selected coordinate/Arrow/join/eligibility owners and the existing
# official-HTML graph binder. They do not establish a statutory crosswalk.
from html import escape as _html_escape
from pathlib import Path

from ipfs_datasets_py.logic.autoformal import legal_source_span_target_eligibility_v1 as eligibility
from ipfs_datasets_py.logic.autoformal import legal_source_span_entity_join_v1 as coordinate_join_owner
from tests.unit.logic.autoformal.test_legal_source_span_entity_coordinate_join_v2 import (
    coordinate_join, prepare as _prepare_coordinate_join,
)


_COORDINATE_GRAPH_RULE = {
    "modality": "O", "actor": "Clerk", "action": "file", "object": "report",
    "conditions": [], "exceptions": [], "temporal": [],
}
_COORDINATE_GRAPH_DOCUMENT = {
    "z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551",
    "text": "Unselected Ω context. Clerk shall file report.",
}
_supported_coordinate_graph = pytest.mark.parametrize("coordinate_join", [{
    "documents": [_COORDINATE_GRAPH_DOCUMENT], "selected_indices": (1,),
    "compiler_rule": _COORDINATE_GRAPH_RULE,
}], ids=["authored-supported-coordinate"], indirect=True)
_repeated_coordinate_graph = pytest.mark.parametrize("coordinate_join", [{
    "documents": [_COORDINATE_GRAPH_DOCUMENT, _COORDINATE_GRAPH_DOCUMENT],
    "selected_indices": (1, 3), "compiler_rule": _COORDINATE_GRAPH_RULE,
}], ids=["authored-repeated-coordinate"], indirect=True)


def _coordinate_graph_wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _coordinate_graph_sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def coordinate_graph_case(coordinate_join):
    case = coordinate_join
    join_raw = _coordinate_graph_wire(_prepare_coordinate_join(case))
    joined = json.loads(join_raw)
    original_request_raw = _coordinate_graph_wire(case["request"])
    originals = {
        "request_raw": original_request_raw, "source_request_raw": case["source_raw"],
        "source_metadata_bytes": case["metadata"],
        "paired_inventory_request_raw": _coordinate_graph_wire(case["paired_request"]),
        "paired_manifest_bytes": case["manifests"], "entity_info_raw": case["info_raw"],
        "expected_request_sha256": _coordinate_graph_sha(original_request_raw),
        "legacy_join_inputs": None,
    }
    eligibility_request = {
        "schema": eligibility.REQUEST_SCHEMA_V2,
        "join_manifest_raw_sha256": _coordinate_graph_sha(join_raw),
        "join_manifest_sha256": coordinate_join_owner.source_span_entity_join_manifest_sha256(joined),
        "expected_physical_ids": [row["physical_identity_sha256"] for row in joined["physical_rows"]],
        "decoder_profile": eligibility.DECODER_PROFILE, "latent_dimension": 0,
        "join_originals_sha256": eligibility.source_span_target_join_originals_sha256(originals),
        "source_coordinate_report_sha256": case["coordinate"]["pin"],
    }
    eligibility_request_raw = _coordinate_graph_wire(eligibility_request)
    observed = eligibility.prepare_source_span_target_eligibility_v2(
        eligibility_request_raw, join_raw,
        expected_request_sha256=_coordinate_graph_sha(eligibility_request_raw),
        join_originals=originals)
    # Preserve deliberately noncanonical artifact bytes independently of its
    # semantic report seal; an outer canonical serialization must not replace it.
    eligibility_raw = json.dumps(observed, ensure_ascii=False, indent=2).encode("utf-8")
    scope = graphs.bind_scope(jurisdiction="US-federal", instrument="USCode", edition=2024,
        applicability="section-local", definition_scope="usc:us:5:551")
    bindings = {}
    revision = case["coordinate"]["report"]["release_id"]
    payload_rows = joined["paired_bundles"][0]["payload_intake"]["rows"]
    for physical, payload in zip(observed["physical_rows"], payload_rows):
        source = json.loads(payload["derived_row_json"])["source"]
        text = source["text"]
        raw_html = (
            '<meta charset="utf-8"><h3 class="section-head">§551. Authored graph fixture</h3>'
            '<p class="statutory-body">(a) ' + _html_escape(text) + '</p>'
            '<p class="statutory-body">(b) ' + _html_escape(text) + '</p>'
        ).encode("utf-8")
        document = context.extract_document(raw_html,
            url="https://www.govinfo.gov/content/pkg/USCODE-2024-title5/html/USCODE-2024-title5-sec551.htm",
            edition=2024, legal_id=source["legal_id"])
        selectors = context.exact_view_occurrences(document, raw_html, text=text)
        bindings[physical["physical_identity_sha256"]] = subject.make_source_binding(
            document, raw_html, document_revision=revision, scope=scope,
            candidate_selectors=[selectors[physical["physical_identity"]["row_ordinal"] % 2]],
            context_observation={"status": "authored_unreviewed_no_edition_crosswalk"})
    return {
        "case": case, "joined": joined, "join_raw": join_raw, "originals": originals,
        "eligibility": observed, "eligibility_raw": eligibility_raw,
        "eligibility_request_raw": eligibility_request_raw, "bindings": bindings,
    }


def _coordinate_graph_request(case, **changes):
    request = {
        "schema": "legal-coordinate-source-graph-intake-request/v1",
        "graph_profile": "canonical_rules_v1",
        "eligibility_report_raw_sha256": _coordinate_graph_sha(case["eligibility_raw"]),
        "eligibility_report_sha256": eligibility.source_span_target_eligibility_sha256(case["eligibility"]),
        "eligibility_request_sha256": _coordinate_graph_sha(case["eligibility_request_raw"]),
        "join_manifest_raw_sha256": _coordinate_graph_sha(case["join_raw"]),
        "join_manifest_sha256": coordinate_join_owner.source_span_entity_join_manifest_sha256(case["joined"]),
        "join_originals_sha256": eligibility.source_span_target_join_originals_sha256(case["originals"]),
        "source_bindings_sha256": subject.source_bindings_sha256(case["bindings"]),
        "expected_physical_ids": [row["physical_identity_sha256"] for row in case["eligibility"]["physical_rows"]],
        **changes,
    }
    return _coordinate_graph_wire(request)


def _prepare_coordinate_graph(case, *, request_raw=None):
    raw = _coordinate_graph_request(case) if request_raw is None else request_raw
    return subject.prepare_coordinate_source_graph_intake_v1(
        raw, case["eligibility_raw"], case["eligibility_request_raw"], case["join_raw"],
        expected_request_sha256=_coordinate_graph_sha(raw),
        join_originals=case["originals"], source_bindings=case["bindings"])


def _validate_coordinate_graph(case, report, *, expected_report_sha256=None):
    raw = _coordinate_graph_request(case)
    value = json.loads(report) if type(report) is bytes else report
    pin = (subject.coordinate_source_graph_intake_sha256(value)
           if expected_report_sha256 is None else expected_report_sha256)
    return subject.validate_coordinate_source_graph_intake_v1(
        report, raw, case["eligibility_raw"], case["eligibility_request_raw"], case["join_raw"],
        expected_request_sha256=_coordinate_graph_sha(raw), expected_report_sha256=pin,
        join_originals=case["originals"], source_bindings=case["bindings"])


def _assert_coordinate_graph_authority_absent(report):
    for row in [report, *report["output_occurrences"]]:
        assert all(type(row[key]) is bool and row[key] is False for key in subject._FALSE)
        assert type(row["training_mask"]) is int and row["training_mask"] == 0
        assert type(row["evaluation_gold_mask"]) is int and row["evaluation_gold_mask"] == 0
    for row in report["physical_rows"] + report["row_references"]:
        assert type(row["training_mask"]) is int and row["training_mask"] == 0
        assert type(row["evaluation_gold_mask"]) is int and row["evaluation_gold_mask"] == 0
    for row in report["output_occurrences"]:
        assert all(type(mask) is int and mask == 0 for mask in row["field_masks"].values())
        assert row["eligibility_output"]["consumer_eligible"] is False
        assert row["selected_occurrence"] is None
        assert type(row["source_binding_mask"]) is int and row["source_binding_mask"] == 0
        assert row["coordinate_to_graph_source_correspondence"] == "unverified_no_independent_crosswalk"
        assert row["graph_source_relationship"] == "independently_nominated_exact_source_occurrence_crosswalk_unverified"
        if row["graph"] is not None:
            assert all(type(flag) is bool and flag is False for flag in row["graph"]["authority"].values())


@_supported_coordinate_graph
def test_coordinate_graph_genuine_supported_targets_roundtrip_without_authority(coordinate_graph_case, monkeypatch):
    case = coordinate_graph_case
    actual_graph = graphs.build_graph
    actual_eligibility = eligibility.validate_source_span_target_eligibility_v2
    graph_calls, eligibility_calls = [], []

    def observe_graph(*args, **kwargs):
        result = actual_graph(*args, **kwargs)
        graph_calls.append(result["graph_id"])
        return result

    def observe_eligibility(*args, **kwargs):
        result = actual_eligibility(*args, **kwargs)
        eligibility_calls.append(eligibility.source_span_target_eligibility_sha256(result))
        return result

    monkeypatch.setattr(graphs, "build_graph", observe_graph)
    monkeypatch.setattr(eligibility, "validate_source_span_target_eligibility_v2", observe_eligibility)
    before = deepcopy(case["bindings"])
    original_inputs = deepcopy(case["originals"])
    report = _prepare_coordinate_graph(case)
    assert len(graph_calls) == 2 and len(eligibility_calls) == 2
    assert report["schema"] == "legal-coordinate-source-graph-intake/v1"
    assert report["source_compatibility_profile"] == "paired-coordinate-source-graph-intake/v1"
    assert report["eligibility_report_raw_utf8"].encode("utf-8") == case["eligibility_raw"]
    assert report["eligibility_report"] == case["eligibility"]
    assert report["join_manifest_raw_utf8"].encode("utf-8") == case["join_raw"]
    assert _coordinate_graph_sha(case["eligibility_raw"]) != eligibility.source_span_target_eligibility_sha256(case["eligibility"])
    assert report["physical_rows"] == case["eligibility"]["physical_rows"]
    assert report["row_references"] == case["eligibility"]["row_references"]
    assert [row["output_occurrence_ordinal"] for row in report["output_occurrences"]] == [0, 1]
    assert [row["eligibility_output"] for row in report["output_occurrences"]] == case["eligibility"]["output_occurrences"]
    assert [(row["eligibility_output"]["route"], row["eligibility_output"]["ordinal"])
            for row in report["output_occurrences"]] == [
        ("compiler.formal_outputs", 0), ("compiler.canonical_formal_outputs", 0)]
    for row in report["output_occurrences"]:
        original = row["eligibility_output"]
        assert row["disposition"] == "proposed_unreviewed_graph"
        assert graphs.graph_to_ast(row["graph"]) == original["canonical_ir"] == {"rules": [_COORDINATE_GRAPH_RULE]}
        assert row["graph_request"]["ast"] == original["canonical_ir"]
        assert row["source_binding"]["selector"]["text"] == "Clerk shall file report."
        assert row["source_binding"]["document_revision"] == "authored-source-release"
        assert original["source_coordinate_span_index"] == 1
        assert original["source_provenance_json"] == case["case"]["coordinate"]["references"][0]
    assert _validate_coordinate_graph(case, _coordinate_graph_wire(report)) == report
    assert len(graph_calls) == 4 and len(eligibility_calls) == 4
    assert case["bindings"] == before and case["originals"] == original_inputs
    _assert_coordinate_graph_authority_absent(report)


def test_coordinate_graph_unsupported_outputs_keep_complete_population_without_graphs(coordinate_graph_case):
    case = coordinate_graph_case
    report = _prepare_coordinate_graph(case)
    assert len(report["physical_rows"]) == 2
    assert report["physical_rows"] == case["eligibility"]["physical_rows"]
    assert report["row_references"] == case["eligibility"]["row_references"]
    assert [row["eligibility_output"] for row in report["output_occurrences"]] == case["eligibility"]["output_occurrences"]
    assert all(row["eligibility_output"]["target_status"] != "mechanically_supported"
               and row["graph"] is None and row["disposition"] == "unresolved"
               for row in report["output_occurrences"])
    assert len(report["output_occurrences"]) > 0
    _assert_coordinate_graph_authority_absent(report)


@_supported_coordinate_graph
@pytest.mark.parametrize("damage", ["missing", "revision", "legal_id", "text", "ambiguous"])
def test_coordinate_graph_independent_binding_mismatch_retains_each_unresolved_output(coordinate_graph_case, damage):
    case = coordinate_graph_case
    identity = case["eligibility"]["physical_rows"][0]["physical_identity_sha256"]
    binding = case["bindings"][identity]
    if damage == "missing":
        case["bindings"].clear()
    elif damage == "revision":
        binding["document_revision"] = "different-authored-release"
    elif damage == "legal_id":
        binding["document"]["legal_id"] = "usc:us:5:552"
    elif damage == "text":
        binding["candidate_selectors"][0]["text"] += " "
    else:
        raw = __import__("base64").b64decode(binding["raw_html_base64"])
        binding["candidate_selectors"] = context.exact_view_occurrences(
            binding["document"], raw, text="Clerk shall file report.")
        assert len(binding["candidate_selectors"]) == 2
    report = _prepare_coordinate_graph(case)
    assert len(report["output_occurrences"]) == 2
    assert all(row["graph"] is None and row["disposition"] == "unresolved" and row["issues"]
               for row in report["output_occurrences"])
    assert [row["eligibility_output"] for row in report["output_occurrences"]] == case["eligibility"]["output_occurrences"]
    _assert_coordinate_graph_authority_absent(report)


@_supported_coordinate_graph
@pytest.mark.parametrize("pin", ["eligibility_report_raw_sha256", "eligibility_report_sha256",
                                  "join_originals_sha256", "source_bindings_sha256"])
def test_coordinate_graph_outer_resealing_cannot_replace_independent_input_pins(coordinate_graph_case, pin):
    case = coordinate_graph_case
    request_raw = _coordinate_graph_request(case, **{pin: "0" * 64})
    with pytest.raises(ValueError):
        _prepare_coordinate_graph(case, request_raw=request_raw)


@_repeated_coordinate_graph
@pytest.mark.parametrize("damage", ["drop_output", "reverse_outputs", "reverse_references"])
def test_coordinate_graph_rehashed_report_cannot_drop_or_reorder_occurrences(coordinate_graph_case, damage):
    case = coordinate_graph_case
    report = _prepare_coordinate_graph(case)
    if damage == "drop_output":
        report["output_occurrences"].pop()
    elif damage == "reverse_outputs":
        report["output_occurrences"].reverse()
    else:
        report["row_references"].reverse()
    with pytest.raises(ValueError):
        _validate_coordinate_graph(case, report)


@_repeated_coordinate_graph
def test_coordinate_graph_repeated_text_keeps_physical_and_output_occurrences_distinct(coordinate_graph_case):
    case = coordinate_graph_case
    report = _prepare_coordinate_graph(case)
    physical = report["physical_rows"]
    assert len(physical) == 2 and physical[0]["source_text"] == physical[1]["source_text"]
    assert len({row["physical_identity_sha256"] for row in physical}) == 2
    assert [row["source_coordinate_span_index"] for row in physical] == [1, 3]
    outputs = report["output_occurrences"]
    assert len(outputs) == 4
    assert [row["output_occurrence_ordinal"] for row in outputs] == [0, 1, 2, 3]
    assert [row["physical_identity_sha256"] for row in outputs] == [
        physical[0]["physical_identity_sha256"], physical[0]["physical_identity_sha256"],
        physical[1]["physical_identity_sha256"], physical[1]["physical_identity_sha256"]]
    assert [row["eligibility_output"]["source_coordinate_span_index"] for row in outputs] == [1, 1, 3, 3]
    assert all(graphs.graph_to_ast(row["graph"]) == {"rules": [_COORDINATE_GRAPH_RULE]} for row in outputs)
    assert len({row["source_binding"]["selector"]["occurrence_id"] for row in outputs}) == 2
    _assert_coordinate_graph_authority_absent(report)


@_supported_coordinate_graph
def test_coordinate_graph_wrong_report_pin_refuses_before_graph_execution(coordinate_graph_case, monkeypatch):
    case = coordinate_graph_case
    report = _prepare_coordinate_graph(case)
    monkeypatch.setattr(graphs, "build_graph", lambda *args, **kwargs: pytest.fail("wrong report pin reached graph"))
    with pytest.raises(ValueError):
        _validate_coordinate_graph(case, report, expected_report_sha256="0" * 64)


def _coordinate_graph_retained_table(case):
    selected = case["case"]["coordinate"]
    return (Path(selected["request"]["repository_root"])
            / selected["written"]["paired_spans"]["path_in_repo"])


@_supported_coordinate_graph
def test_coordinate_graph_closing_eligibility_catches_live_table_drift_after_genuine_graph(coordinate_graph_case, monkeypatch):
    case = coordinate_graph_case
    actual = graphs.build_graph
    calls = []

    def drift_after_real_graph(*args, **kwargs):
        graph = actual(*args, **kwargs)
        calls.append(graph["graph_id"])
        path = _coordinate_graph_retained_table(case)
        path.write_bytes(path.read_bytes() + b"changed after genuine graph")
        return graph

    monkeypatch.setattr(graphs, "build_graph", drift_after_real_graph)
    with pytest.raises(ValueError):
        _prepare_coordinate_graph(case)
    assert calls


@_supported_coordinate_graph
@pytest.mark.parametrize("offered", ["bindings", "originals"])
def test_coordinate_graph_offered_input_mutation_after_genuine_graph_is_refused(coordinate_graph_case, monkeypatch, offered):
    case = coordinate_graph_case
    actual = graphs.build_graph
    calls = []

    def mutate_after_real_graph(*args, **kwargs):
        graph = actual(*args, **kwargs)
        calls.append(graph["graph_id"])
        if offered == "bindings":
            next(iter(case["bindings"].values()))["context_observation"]["status"] = "changed"
        else:
            case["originals"]["source_metadata_bytes"]["README.md"] += b"changed after graph"
        return graph

    monkeypatch.setattr(graphs, "build_graph", mutate_after_real_graph)
    with pytest.raises(ValueError):
        _prepare_coordinate_graph(case)
    assert calls


@_supported_coordinate_graph
def test_coordinate_graph_primary_callback_error_preserves_secondary_closing_custody_failure(coordinate_graph_case, monkeypatch):
    case = coordinate_graph_case
    actual = graphs.build_graph
    primary = RuntimeError("authored graph callback primary failure")
    calls = []

    def fail_after_real_graph(*args, **kwargs):
        graph = actual(*args, **kwargs)
        calls.append(graph["graph_id"])
        path = _coordinate_graph_retained_table(case)
        path.write_bytes(path.read_bytes() + b"changed before primary error")
        raise primary

    monkeypatch.setattr(graphs, "build_graph", fail_after_real_graph)
    with pytest.raises(RuntimeError, match="authored graph callback primary failure") as observed:
        _prepare_coordinate_graph(case)
    assert observed.value is primary and calls
    assert any("custody" in note or "closing" in note for note in getattr(primary, "__notes__", ()))


@_supported_coordinate_graph
def test_coordinate_graph_validator_detects_offered_report_mutation_after_real_graph(coordinate_graph_case, monkeypatch):
    case = coordinate_graph_case
    report = _prepare_coordinate_graph(case)
    actual = graphs.build_graph
    calls = []

    def mutate_offered_after_real_graph(*args, **kwargs):
        graph = actual(*args, **kwargs)
        calls.append(graph["graph_id"])
        report["output_occurrences"][0]["context_observation"] = {"late": "offered-report-mutation"}
        return graph

    monkeypatch.setattr(graphs, "build_graph", mutate_offered_after_real_graph)
    with pytest.raises(ValueError):
        _validate_coordinate_graph(case, report)
    assert calls


@_supported_coordinate_graph
def test_coordinate_graph_callback_cannot_mutate_the_typed_ast_after_genuine_graph_success(coordinate_graph_case, monkeypatch):
    case = coordinate_graph_case
    actual = graphs.build_graph
    calls = []

    def mutate_ast_after_real_graph(*args, **kwargs):
        graph = actual(*args, **kwargs)
        calls.append(graph["graph_id"])
        ast = kwargs["ast"] if "ast" in kwargs else args[0]
        ast["rules"].append(deepcopy(ast["rules"][0]))
        return graph

    monkeypatch.setattr(graphs, "build_graph", mutate_ast_after_real_graph)
    with pytest.raises(ValueError):
        _prepare_coordinate_graph(case)
    assert calls


# Explicit graph-v2 original-input replay port. Historical graph-v1 tests and
# fixture ASTs above remain unchanged and are retained under their old producer.
# The selected new cohort uses the same authored source/transport fixtures and
# delegates every successful integration step to the genuine current owners.
@pytest.fixture
def coordinate_graph_v2_case(coordinate_join):
    case = coordinate_join
    join_raw = _coordinate_graph_wire(_prepare_coordinate_join(case))
    joined = json.loads(join_raw)
    original_request_raw = _coordinate_graph_wire(case["request"])
    originals = {
        "request_raw": original_request_raw, "source_request_raw": case["source_raw"],
        "source_metadata_bytes": case["metadata"],
        "paired_inventory_request_raw": _coordinate_graph_wire(case["paired_request"]),
        "paired_manifest_bytes": case["manifests"], "entity_info_raw": case["info_raw"],
        "expected_request_sha256": _coordinate_graph_sha(original_request_raw),
        "legacy_join_inputs": None,
    }
    eligibility_request = {
        "schema": eligibility.REQUEST_SCHEMA_V3,
        "source_compatibility_profile": "original-input-coordinate-target-eligibility/v1",
        "join_manifest_raw_sha256": _coordinate_graph_sha(join_raw),
        "join_manifest_sha256": coordinate_join_owner.source_span_entity_join_manifest_sha256(joined),
        "expected_physical_ids": [row["physical_identity_sha256"] for row in joined["physical_rows"]],
        "decoder_profile": eligibility.DECODER_PROFILE, "latent_dimension": 0,
        "join_originals_sha256": eligibility.source_span_target_join_originals_sha256(originals),
        "source_coordinate_report_sha256": case["coordinate"]["pin"],
    }
    eligibility_request_raw = _coordinate_graph_wire(eligibility_request)
    observed = eligibility.prepare_source_span_target_eligibility_v3(
        eligibility_request_raw, join_raw,
        expected_request_sha256=_coordinate_graph_sha(eligibility_request_raw),
        join_originals=originals)
    # Preserve deliberately noncanonical artifact bytes independently of its
    # semantic report seal; an outer canonical serialization must not replace it.
    eligibility_raw = json.dumps(observed, ensure_ascii=False, indent=2).encode("utf-8")
    scope = graphs.bind_scope(jurisdiction="US-federal", instrument="USCode", edition=2024,
        applicability="section-local", definition_scope="usc:us:5:551")
    bindings = {}
    revision = case["coordinate"]["report"]["release_id"]
    payload_rows = joined["paired_bundles"][0]["payload_intake"]["rows"]
    for physical, payload in zip(observed["physical_rows"], payload_rows):
        source = json.loads(payload["derived_row_json"])["source"]
        text = source["text"]
        raw_html = (
            '<meta charset="utf-8"><h3 class="section-head">§551. Authored graph fixture</h3>'
            '<p class="statutory-body">(a) ' + _html_escape(text) + '</p>'
            '<p class="statutory-body">(b) ' + _html_escape(text) + '</p>'
        ).encode("utf-8")
        document = context.extract_document(raw_html,
            url="https://www.govinfo.gov/content/pkg/USCODE-2024-title5/html/USCODE-2024-title5-sec551.htm",
            edition=2024, legal_id=source["legal_id"])
        selectors = context.exact_view_occurrences(document, raw_html, text=text)
        bindings[physical["physical_identity_sha256"]] = subject.make_source_binding(
            document, raw_html, document_revision=revision, scope=scope,
            candidate_selectors=[selectors[physical["physical_identity"]["row_ordinal"] % 2]],
            context_observation={"status": "authored_unreviewed_no_edition_crosswalk"})
    return {
        "case": case, "joined": joined, "join_raw": join_raw, "originals": originals,
        "eligibility": observed, "eligibility_raw": eligibility_raw,
        "eligibility_request_raw": eligibility_request_raw, "bindings": bindings,
    }


def _coordinate_graph_v2_request(case, **changes):
    request = {
        "schema": "legal-coordinate-source-graph-intake-request/v2",
        "source_compatibility_profile": "original-input-coordinate-source-graph-intake/v1",
        "graph_profile": "canonical_rules_v1",
        "eligibility_report_raw_sha256": _coordinate_graph_sha(case["eligibility_raw"]),
        "eligibility_report_sha256": eligibility.source_span_target_eligibility_sha256(case["eligibility"]),
        "eligibility_request_sha256": _coordinate_graph_sha(case["eligibility_request_raw"]),
        "join_manifest_raw_sha256": _coordinate_graph_sha(case["join_raw"]),
        "join_manifest_sha256": coordinate_join_owner.source_span_entity_join_manifest_sha256(case["joined"]),
        "join_originals_sha256": eligibility.source_span_target_join_originals_sha256(case["originals"]),
        "source_bindings_sha256": subject.source_bindings_sha256(case["bindings"]),
        "expected_physical_ids": [row["physical_identity_sha256"] for row in case["eligibility"]["physical_rows"]],
        **changes,
    }
    return _coordinate_graph_wire(request)


def _prepare_coordinate_graph_v2(case, *, request_raw=None):
    raw = _coordinate_graph_v2_request(case) if request_raw is None else request_raw
    return subject.prepare_coordinate_source_graph_intake_v2(
        raw, case["eligibility_raw"], case["eligibility_request_raw"], case["join_raw"],
        expected_request_sha256=_coordinate_graph_sha(raw),
        join_originals=case["originals"], source_bindings=case["bindings"])


def _validate_coordinate_graph_v2(case, report, *, expected_report_sha256=None):
    raw = _coordinate_graph_v2_request(case)
    value = json.loads(report) if type(report) is bytes else report
    pin = (subject.coordinate_source_graph_intake_sha256(value)
           if expected_report_sha256 is None else expected_report_sha256)
    return subject.validate_coordinate_source_graph_intake_v2(
        report, raw, case["eligibility_raw"], case["eligibility_request_raw"], case["join_raw"],
        expected_request_sha256=_coordinate_graph_sha(raw), expected_report_sha256=pin,
        join_originals=case["originals"], source_bindings=case["bindings"])


@_supported_coordinate_graph
def test_coordinate_graph_v2_genuine_supported_targets_roundtrip_without_authority(coordinate_graph_v2_case, monkeypatch):
    case = coordinate_graph_v2_case
    actual_graph = graphs.build_graph
    actual_eligibility = eligibility.validate_source_span_target_eligibility_v3
    graph_calls, eligibility_calls = ([], [])

    def observe_graph(*args, **kwargs):
        result = actual_graph(*args, **kwargs)
        graph_calls.append(result['graph_id'])
        return result

    def observe_eligibility(*args, **kwargs):
        result = actual_eligibility(*args, **kwargs)
        eligibility_calls.append(eligibility.source_span_target_eligibility_sha256(result))
        return result
    monkeypatch.setattr(graphs, 'build_graph', observe_graph)
    monkeypatch.setattr(eligibility, 'validate_source_span_target_eligibility_v3', observe_eligibility)
    before = deepcopy(case['bindings'])
    original_inputs = deepcopy(case['originals'])
    report = _prepare_coordinate_graph_v2(case)
    assert len(graph_calls) == 2 and len(eligibility_calls) == 2
    assert report['schema'] == 'legal-coordinate-source-graph-intake/v2'
    assert report['source_compatibility_profile'] == 'original-input-coordinate-source-graph-intake/v1'
    assert report['eligibility_report_raw_utf8'].encode('utf-8') == case['eligibility_raw']
    assert 'eligibility_report' not in report and 'join_manifest_raw_utf8' not in report
    assert report['eligibility_report_reference'] == {'schema': 'legal-coordinate-source-graph-eligibility-reference/v1', 'container': 'eligibility_report_raw_utf8', 'report_artifact_sha256': _coordinate_graph_sha(case['eligibility_raw']), 'report_sha256': eligibility.source_span_target_eligibility_sha256(case['eligibility']), 'report_bytes': len(case['eligibility_raw'])}
    assert report['join_manifest_reference'] == {'schema': 'legal-coordinate-source-graph-join-reference/v1', 'container': 'eligibility_report_raw_utf8', 'json_pointer': '/join_manifest_raw_utf8', 'join_manifest_raw_sha256': _coordinate_graph_sha(case['join_raw']), 'join_manifest_sha256': coordinate_join_owner.source_span_entity_join_manifest_sha256(case['joined']), 'join_manifest_bytes': len(case['join_raw'])}
    retained_eligibility = json.loads(report['eligibility_report_raw_utf8'])
    assert retained_eligibility == case['eligibility']
    assert retained_eligibility['join_manifest_raw_utf8'].encode('utf-8') == case['join_raw']
    assert _coordinate_graph_sha(case['eligibility_raw']) != eligibility.source_span_target_eligibility_sha256(case['eligibility'])
    assert report['physical_rows'] == case['eligibility']['physical_rows']
    assert report['row_references'] == case['eligibility']['row_references']
    assert [row['output_occurrence_ordinal'] for row in report['output_occurrences']] == [0, 1]
    assert [row['eligibility_output'] for row in report['output_occurrences']] == case['eligibility']['output_occurrences']
    assert [(row['eligibility_output']['route'], row['eligibility_output']['ordinal']) for row in report['output_occurrences']] == [('compiler.formal_outputs', 0), ('compiler.canonical_formal_outputs', 0)]
    for row in report['output_occurrences']:
        original = row['eligibility_output']
        assert row['disposition'] == 'proposed_unreviewed_graph'
        assert graphs.graph_to_ast(row['graph']) == original['canonical_ir'] == {'rules': [_COORDINATE_GRAPH_RULE]}
        assert row['graph_request']['ast'] == original['canonical_ir']
        assert row['source_binding']['selector']['text'] == 'Clerk shall file report.'
        assert row['source_binding']['document_revision'] == 'authored-source-release'
        assert original['source_coordinate_span_index'] == 1
        assert original['source_provenance_json'] == case['case']['coordinate']['references'][0]
    assert _validate_coordinate_graph_v2(case, _coordinate_graph_wire(report)) == report
    assert len(graph_calls) == 4 and len(eligibility_calls) == 4
    assert case['bindings'] == before and case['originals'] == original_inputs
    _assert_coordinate_graph_authority_absent(report)

def test_coordinate_graph_v2_unsupported_outputs_keep_complete_population_without_graphs(coordinate_graph_v2_case):
    case = coordinate_graph_v2_case
    report = _prepare_coordinate_graph_v2(case)
    assert len(report['physical_rows']) == 2
    assert report['physical_rows'] == case['eligibility']['physical_rows']
    assert report['row_references'] == case['eligibility']['row_references']
    assert [row['eligibility_output'] for row in report['output_occurrences']] == case['eligibility']['output_occurrences']
    assert all((row['eligibility_output']['target_status'] != 'mechanically_supported' and row['graph'] is None and (row['disposition'] == 'unresolved') for row in report['output_occurrences']))
    assert len(report['output_occurrences']) > 0
    _assert_coordinate_graph_authority_absent(report)

@_supported_coordinate_graph
@pytest.mark.parametrize('damage', ['missing', 'revision', 'legal_id', 'text', 'ambiguous'], ids=['missing', 'revision', 'legal_id', 'text', 'ambiguous'])
def test_coordinate_graph_v2_independent_binding_mismatch_retains_each_unresolved_output(coordinate_graph_v2_case, damage):
    case = coordinate_graph_v2_case
    identity = case['eligibility']['physical_rows'][0]['physical_identity_sha256']
    binding = case['bindings'][identity]
    if damage == 'missing':
        case['bindings'].clear()
    elif damage == 'revision':
        binding['document_revision'] = 'different-authored-release'
    elif damage == 'legal_id':
        binding['document']['legal_id'] = 'usc:us:5:552'
    elif damage == 'text':
        binding['candidate_selectors'][0]['text'] += ' '
    else:
        raw = __import__('base64').b64decode(binding['raw_html_base64'])
        binding['candidate_selectors'] = context.exact_view_occurrences(binding['document'], raw, text='Clerk shall file report.')
        assert len(binding['candidate_selectors']) == 2
    report = _prepare_coordinate_graph_v2(case)
    assert len(report['output_occurrences']) == 2
    assert all((row['graph'] is None and row['disposition'] == 'unresolved' and row['issues'] for row in report['output_occurrences']))
    assert [row['eligibility_output'] for row in report['output_occurrences']] == case['eligibility']['output_occurrences']
    _assert_coordinate_graph_authority_absent(report)

@_supported_coordinate_graph
@pytest.mark.parametrize('pin', ['eligibility_report_raw_sha256', 'eligibility_report_sha256', 'join_originals_sha256', 'source_bindings_sha256'], ids=['eligibility_report_raw_sha256', 'eligibility_report_sha256', 'join_originals_sha256', 'source_bindings_sha256'])
def test_coordinate_graph_v2_outer_resealing_cannot_replace_independent_input_pins(coordinate_graph_v2_case, pin):
    case = coordinate_graph_v2_case
    request_raw = _coordinate_graph_v2_request(case, **{pin: '0' * 64})
    with pytest.raises(ValueError):
        _prepare_coordinate_graph_v2(case, request_raw=request_raw)

@_repeated_coordinate_graph
@pytest.mark.parametrize('damage', ['drop_output', 'reverse_outputs', 'reverse_references'], ids=['drop_output', 'reverse_outputs', 'reverse_references'])
def test_coordinate_graph_v2_rehashed_report_cannot_drop_or_reorder_occurrences(coordinate_graph_v2_case, damage):
    case = coordinate_graph_v2_case
    report = _prepare_coordinate_graph_v2(case)
    if damage == 'drop_output':
        report['output_occurrences'].pop()
    elif damage == 'reverse_outputs':
        report['output_occurrences'].reverse()
    else:
        report['row_references'].reverse()
    with pytest.raises(ValueError):
        _validate_coordinate_graph_v2(case, report)

@_repeated_coordinate_graph
def test_coordinate_graph_v2_repeated_text_keeps_physical_and_output_occurrences_distinct(coordinate_graph_v2_case):
    case = coordinate_graph_v2_case
    report = _prepare_coordinate_graph_v2(case)
    physical = report['physical_rows']
    assert len(physical) == 2 and physical[0]['source_text'] == physical[1]['source_text']
    assert len({row['physical_identity_sha256'] for row in physical}) == 2
    assert [row['source_coordinate_span_index'] for row in physical] == [1, 3]
    outputs = report['output_occurrences']
    assert len(outputs) == 4
    assert [row['output_occurrence_ordinal'] for row in outputs] == [0, 1, 2, 3]
    assert [row['physical_identity_sha256'] for row in outputs] == [physical[0]['physical_identity_sha256'], physical[0]['physical_identity_sha256'], physical[1]['physical_identity_sha256'], physical[1]['physical_identity_sha256']]
    assert [row['eligibility_output']['source_coordinate_span_index'] for row in outputs] == [1, 1, 3, 3]
    assert all((graphs.graph_to_ast(row['graph']) == {'rules': [_COORDINATE_GRAPH_RULE]} for row in outputs))
    assert len({row['source_binding']['selector']['occurrence_id'] for row in outputs}) == 2
    _assert_coordinate_graph_authority_absent(report)

@_supported_coordinate_graph
def test_coordinate_graph_v2_wrong_report_pin_refuses_before_graph_execution(coordinate_graph_v2_case, monkeypatch):
    case = coordinate_graph_v2_case
    report = _prepare_coordinate_graph_v2(case)
    monkeypatch.setattr(graphs, 'build_graph', lambda *args, **kwargs: pytest.fail('wrong report pin reached graph'))
    with pytest.raises(ValueError):
        _validate_coordinate_graph_v2(case, report, expected_report_sha256='0' * 64)

@_supported_coordinate_graph
def test_coordinate_graph_v2_closing_eligibility_catches_live_table_drift_after_genuine_graph(coordinate_graph_v2_case, monkeypatch):
    case = coordinate_graph_v2_case
    actual = graphs.build_graph
    calls = []

    def drift_after_real_graph(*args, **kwargs):
        graph = actual(*args, **kwargs)
        calls.append(graph['graph_id'])
        path = _coordinate_graph_retained_table(case)
        path.write_bytes(path.read_bytes() + b'changed after genuine graph')
        return graph
    monkeypatch.setattr(graphs, 'build_graph', drift_after_real_graph)
    with pytest.raises(ValueError):
        _prepare_coordinate_graph_v2(case)
    assert calls

@_supported_coordinate_graph
@pytest.mark.parametrize('offered', ['bindings', 'originals'], ids=['bindings', 'originals'])
def test_coordinate_graph_v2_offered_input_mutation_after_genuine_graph_is_refused(coordinate_graph_v2_case, monkeypatch, offered):
    case = coordinate_graph_v2_case
    actual = graphs.build_graph
    calls = []

    def mutate_after_real_graph(*args, **kwargs):
        graph = actual(*args, **kwargs)
        calls.append(graph['graph_id'])
        if offered == 'bindings':
            next(iter(case['bindings'].values()))['context_observation']['status'] = 'changed'
        else:
            case['originals']['source_metadata_bytes']['README.md'] += b'changed after graph'
        return graph
    monkeypatch.setattr(graphs, 'build_graph', mutate_after_real_graph)
    with pytest.raises(ValueError):
        _prepare_coordinate_graph_v2(case)
    assert calls

@_supported_coordinate_graph
def test_coordinate_graph_v2_primary_callback_error_preserves_secondary_closing_custody_failure(coordinate_graph_v2_case, monkeypatch):
    case = coordinate_graph_v2_case
    actual = graphs.build_graph
    primary = RuntimeError('authored graph callback primary failure')
    calls = []

    def fail_after_real_graph(*args, **kwargs):
        graph = actual(*args, **kwargs)
        calls.append(graph['graph_id'])
        path = _coordinate_graph_retained_table(case)
        path.write_bytes(path.read_bytes() + b'changed before primary error')
        raise primary
    monkeypatch.setattr(graphs, 'build_graph', fail_after_real_graph)
    with pytest.raises(RuntimeError, match='authored graph callback primary failure') as observed:
        _prepare_coordinate_graph_v2(case)
    assert observed.value is primary and calls
    assert any(('custody' in note or 'closing' in note for note in getattr(primary, '__notes__', ())))

@_supported_coordinate_graph
def test_coordinate_graph_v2_validator_detects_offered_report_mutation_after_real_graph(coordinate_graph_v2_case, monkeypatch):
    case = coordinate_graph_v2_case
    report = _prepare_coordinate_graph_v2(case)
    actual = graphs.build_graph
    calls = []

    def mutate_offered_after_real_graph(*args, **kwargs):
        graph = actual(*args, **kwargs)
        calls.append(graph['graph_id'])
        report['output_occurrences'][0]['context_observation'] = {'late': 'offered-report-mutation'}
        return graph
    monkeypatch.setattr(graphs, 'build_graph', mutate_offered_after_real_graph)
    with pytest.raises(ValueError):
        _validate_coordinate_graph_v2(case, report)
    assert calls

@_supported_coordinate_graph
def test_coordinate_graph_v2_callback_cannot_mutate_the_typed_ast_after_genuine_graph_success(coordinate_graph_v2_case, monkeypatch):
    case = coordinate_graph_v2_case
    actual = graphs.build_graph
    calls = []

    def mutate_ast_after_real_graph(*args, **kwargs):
        graph = actual(*args, **kwargs)
        calls.append(graph['graph_id'])
        ast = kwargs['ast'] if 'ast' in kwargs else args[0]
        ast['rules'].append(deepcopy(ast['rules'][0]))
        return graph
    monkeypatch.setattr(graphs, 'build_graph', mutate_ast_after_real_graph)
    with pytest.raises(ValueError):
        _prepare_coordinate_graph_v2(case)
    assert calls

@_supported_coordinate_graph
@pytest.mark.parametrize("profile", ["retained-v1", "historical-original-v2"],
                         ids=["retained-v1", "historical-original-v2"])
def test_coordinate_graph_v2_refuses_other_eligibility_profiles_before_graph(coordinate_graph_v2_case, monkeypatch, profile):
    case = coordinate_graph_v2_case
    request = json.loads(case["eligibility_request_raw"])
    request["schema"] = "legal-source-span-target-eligibility-request/v2"
    request.pop("source_compatibility_profile")
    if profile == "retained-v1":
        request["schema"] = eligibility.RETAINED_REQUEST_SCHEMA_V1
        request["source_compatibility_profile"] = eligibility.RETAINED_PROFILE_V1
        request.pop("join_originals_sha256")
        request_raw = _coordinate_graph_wire(request)
        observed = eligibility.prepare_retained_source_span_target_eligibility_v1(
            request_raw, case["join_raw"], expected_request_sha256=_coordinate_graph_sha(request_raw))
        assert observed["upstream_reexecution_performed"] is False
    else:
        # Declared historical schema/profile ancestry must be refused even when
        # every outer raw/canonical pin is independently updated. This is an
        # adversarial offered artifact, not a claimed execution of old c8b code.
        request_raw = _coordinate_graph_wire(request)
        observed = deepcopy(case["eligibility"])
        observed.update(schema="legal-source-span-target-eligibility/v2",
                        source_compatibility_profile="paired-coordinate-target-eligibility/v1")
    case["eligibility_request_raw"] = request_raw
    case["eligibility"] = observed
    case["eligibility_raw"] = _coordinate_graph_wire(observed)
    actual = graphs.build_graph
    calls = []
    def observe(*args, **kwargs):
        result = actual(*args, **kwargs)
        calls.append(result["graph_id"])
        return result
    monkeypatch.setattr(graphs, "build_graph", observe)
    with pytest.raises(ValueError):
        _prepare_coordinate_graph_v2(case)
    assert calls == []


@_supported_coordinate_graph
@pytest.mark.parametrize("damage", ["missing-profile", "retained-profile", "old-schema", "extra-field", "wrong-request-pin"],
                         ids=["missing-profile", "retained-profile", "old-schema", "extra-field", "wrong-request-pin"])
def test_coordinate_graph_v2_explicit_request_profile_is_required(coordinate_graph_v2_case, monkeypatch, damage):
    case = coordinate_graph_v2_case
    request = json.loads(_coordinate_graph_v2_request(case))
    if damage == "missing-profile":
        request.pop("source_compatibility_profile")
    elif damage == "retained-profile":
        request["source_compatibility_profile"] = "paired-coordinate-source-graph-intake/v1"
    elif damage == "old-schema":
        request["schema"] = "legal-coordinate-source-graph-intake-request/v1"
    elif damage == "extra-field":
        request["undeclared_profile_hint"] = "original-input-coordinate-source-graph-intake/v1"
    raw = _coordinate_graph_wire(request)
    actual = graphs.build_graph
    calls = []
    def observe(*args, **kwargs):
        result = actual(*args, **kwargs)
        calls.append(result["graph_id"])
        return result
    monkeypatch.setattr(graphs, "build_graph", observe)
    with pytest.raises(ValueError):
        subject.prepare_coordinate_source_graph_intake_v2(
            raw, case["eligibility_raw"], case["eligibility_request_raw"], case["join_raw"],
            expected_request_sha256="0" * 64 if damage == "wrong-request-pin" else _coordinate_graph_sha(raw),
            join_originals=case["originals"], source_bindings=case["bindings"])
    assert calls == []


@_supported_coordinate_graph
@pytest.mark.parametrize("damage", ["bindings", "originals", "graph-callable", "eligibility-callable", "runtime-describer"],
                         ids=["bindings", "originals", "graph-callable", "eligibility-callable", "runtime-describer"])
def test_coordinate_graph_v2_closing_replay_fences_live_changes(coordinate_graph_v2_case, monkeypatch, damage):
    case = coordinate_graph_v2_case
    actual_validate = eligibility.validate_source_span_target_eligibility_v3
    actual_graph = graphs.build_graph
    runtime = eligibility._owners()[4]
    actual_describe = runtime.describe_runtime
    calls = []
    def replacement_graph(*args, **kwargs):
        return actual_graph(*args, **kwargs)
    def replacement_validate(*args, **kwargs):
        return actual_validate(*args, **kwargs)
    def replacement_describe(*args, **kwargs):
        return actual_describe(*args, **kwargs)
    def mutate_after_real_closing_replay(*args, **kwargs):
        result = actual_validate(*args, **kwargs)
        calls.append(eligibility.source_span_target_eligibility_sha256(result))
        if len(calls) == 2:
            if damage == "bindings":
                next(iter(case["bindings"].values()))["context_observation"]["status"] = "changed after closing replay"
            elif damage == "originals":
                case["originals"]["source_metadata_bytes"]["README.md"] += b"changed after closing replay"
            elif damage == "graph-callable":
                monkeypatch.setattr(graphs, "build_graph", replacement_graph)
            elif damage == "eligibility-callable":
                monkeypatch.setattr(eligibility, "validate_source_span_target_eligibility_v3", replacement_validate)
            else:
                monkeypatch.setattr(runtime, "describe_runtime", replacement_describe)
        return result
    monkeypatch.setattr(eligibility, "validate_source_span_target_eligibility_v3", mutate_after_real_closing_replay)
    with pytest.raises(ValueError):
        _prepare_coordinate_graph_v2(case)
    assert len(calls) == 2


@_supported_coordinate_graph
@pytest.mark.parametrize("damage", ["eligibility-artifact-pin", "join-pointer", "global-span-index", "output-provenance", "training-mask"],
                         ids=["eligibility-artifact-pin", "join-pointer", "global-span-index", "output-provenance", "training-mask"])
def test_coordinate_graph_v2_resealed_reference_or_provenance_change_is_rejected(coordinate_graph_v2_case, damage):
    case = coordinate_graph_v2_case
    report = _prepare_coordinate_graph_v2(case)
    if damage == "eligibility-artifact-pin":
        report["eligibility_report_reference"]["report_artifact_sha256"] = "0" * 64
    elif damage == "join-pointer":
        report["join_manifest_reference"]["json_pointer"] = "/invented_join_manifest"
    elif damage == "global-span-index":
        report["physical_rows"][0]["source_coordinate_span_index"] = 0
    elif damage == "output-provenance":
        report["output_occurrences"][0]["eligibility_output"]["source_provenance_json"] += " "
    else:
        report["output_occurrences"][0]["training_mask"] = 1
    # The helper supplies this altered report's fresh complete canonical pin.
    # Independent regeneration must still reject the changed commitment.
    with pytest.raises(ValueError):
        _validate_coordinate_graph_v2(case, report)


@_supported_coordinate_graph
def test_coordinate_graph_v2_request_cannot_silently_enter_historical_v1_api(coordinate_graph_v2_case):
    case = coordinate_graph_v2_case
    raw = _coordinate_graph_v2_request(case)
    with pytest.raises(ValueError):
        subject.prepare_coordinate_source_graph_intake_v1(
            raw, case["eligibility_raw"], case["eligibility_request_raw"], case["join_raw"],
            expected_request_sha256=_coordinate_graph_sha(raw),
            join_originals=case["originals"], source_bindings=case["bindings"])


# Explicit graph-v3 consumes the qualified wire eligibility-v4 operation.  The
# upstream fixture remains an authored local Parquet/metadata fixture; importing
# its helpers does not collect or repeat the upstream qualification suites.
from tests.unit.logic.autoformal.test_legal_source_span_entity_coordinate_join_v2 import wire_coordinate_join
from tests.unit.logic.autoformal.test_legal_source_span_target_eligibility_v1 import (
    wire_original_replay_v4, wire_original_inputs_v4, prepare_wire_eligibility_v4,
)

_WIRE_GRAPH_PROFILE = "original-input-wire-coordinate-source-graph-intake/v1"
_WIRE_GRAPH_METADATA = "hf-default-parquet-envelope/v1"


@pytest.fixture
def wire_graph_v3_case(wire_original_replay_v4):
    original = wire_original_replay_v4
    request_raw, join_raw = wire_original_inputs_v4(original)
    observed = prepare_wire_eligibility_v4(original)
    eligibility_raw = (json.dumps(observed, ensure_ascii=False, indent=2) + "\n").encode()
    joined, transport = original["join"], original["case"]
    scope = graphs.bind_scope(jurisdiction="US-federal", instrument="USCode", edition=2024,
        applicability="section-local", definition_scope="usc:us:5:551")
    bindings = {}
    revision = transport["coordinate"]["report"]["release_id"]
    # These are independently nominated authored HTML occurrences, not a
    # source/edition correspondence inferred from the HF logical config alias.
    for physical, payload in zip(observed["physical_rows"], joined["paired_bundles"][0]["payload_intake"]["rows"]):
        source = json.loads(payload["derived_row_json"])["source"]
        text = source["text"]
        raw_html = ('<meta charset="utf-8"><h3 class="section-head">§551. Authored wire graph fixture</h3>'
            '<p class="statutory-body">(a) ' + _html_escape(text) + '</p>'
            '<p class="statutory-body">(b) ' + _html_escape(text) + '</p>').encode()
        document = context.extract_document(raw_html,
            url="https://www.govinfo.gov/content/pkg/USCODE-2024-title5/html/USCODE-2024-title5-sec551.htm",
            edition=2024, legal_id=source["legal_id"])
        selectors = context.exact_view_occurrences(document, raw_html, text=text)
        bindings[physical["physical_identity_sha256"]] = subject.make_source_binding(
            document, raw_html, document_revision=revision, scope=scope,
            candidate_selectors=[selectors[physical["physical_identity"]["row_ordinal"] % 2]],
            context_observation={"status": "authored_unreviewed_no_edition_crosswalk"})
    return {"case": transport, "joined": joined, "join_raw": join_raw,
        "originals": original["originals"], "eligibility": observed,
        "eligibility_raw": eligibility_raw, "eligibility_request_raw": request_raw, "bindings": bindings}


def _wire_graph_v3_request(case, **changes):
    return _coordinate_graph_wire({
        "schema": "legal-coordinate-source-graph-intake-request/v3",
        "source_compatibility_profile": _WIRE_GRAPH_PROFILE,
        "metadata_profile": _WIRE_GRAPH_METADATA, "graph_profile": "canonical_rules_v1",
        "eligibility_report_raw_sha256": _coordinate_graph_sha(case["eligibility_raw"]),
        "eligibility_report_sha256": eligibility.source_span_target_eligibility_sha256(case["eligibility"]),
        "eligibility_request_sha256": _coordinate_graph_sha(case["eligibility_request_raw"]),
        "join_manifest_raw_sha256": _coordinate_graph_sha(case["join_raw"]),
        "join_manifest_sha256": coordinate_join_owner.source_span_entity_join_manifest_sha256(case["joined"]),
        "join_originals_sha256": eligibility.source_span_target_join_originals_sha256(case["originals"]),
        "source_bindings_sha256": subject.source_bindings_sha256(case["bindings"]),
        "expected_physical_ids": [row["physical_identity_sha256"] for row in case["eligibility"]["physical_rows"]],
        **changes})


def _prepare_wire_graph_v3(case, *, request_raw=None):
    raw = _wire_graph_v3_request(case) if request_raw is None else request_raw
    return subject.prepare_coordinate_source_graph_intake_v3(raw, case["eligibility_raw"],
        case["eligibility_request_raw"], case["join_raw"],
        expected_request_sha256=_coordinate_graph_sha(raw),
        join_originals=case["originals"], source_bindings=case["bindings"])


def _validate_wire_graph_v3(case, report):
    raw = _wire_graph_v3_request(case)
    value = json.loads(report) if type(report) is bytes else report
    return subject.validate_coordinate_source_graph_intake_v3(report, raw, case["eligibility_raw"],
        case["eligibility_request_raw"], case["join_raw"],
        expected_request_sha256=_coordinate_graph_sha(raw),
        expected_report_sha256=subject.coordinate_source_graph_intake_sha256(value),
        join_originals=case["originals"], source_bindings=case["bindings"])


def _assert_wire_graph_v3_unqualified(report, case):
    assert report["schema"] == "legal-coordinate-source-graph-intake/v3"
    assert report["source_compatibility_profile"] == _WIRE_GRAPH_PROFILE
    assert report["metadata_profile"] == _WIRE_GRAPH_METADATA
    assert report["source_metadata_intake_sha256"] == case["joined"]["source_metadata_intake_sha256"]
    assert report["selected_occurrence"] is None and report["source_binding_mask"] == 0
    assert report["entity_binding"] == "unavailable_semantic_companions_not_supplied"
    assert report["current_source_release_correspondence"] == "unverified_no_independent_crosswalk"
    assert report["checkpoint_status"] == "not_assessed"
    assert all(type(value) is bool and value is False for value in report["authority"].values())
    _assert_coordinate_graph_authority_absent(report)


@_supported_coordinate_graph
def test_wire_graph_v3_genuine_complete_roundtrip_keeps_unreviewed_carrier(wire_graph_v3_case, monkeypatch):
    case = wire_graph_v3_case
    genuine_graph, genuine_eligibility = graphs.build_graph, eligibility.validate_source_span_target_eligibility_v4
    graph_calls, replay_calls = [], []
    def observe_graph(*args, **kwargs):
        result = genuine_graph(*args, **kwargs); graph_calls.append(result); return result
    def observe_eligibility(*args, **kwargs):
        result = genuine_eligibility(*args, **kwargs); replay_calls.append(result)
        assert kwargs["expected_report_sha256"] == eligibility.source_span_target_eligibility_sha256(case["eligibility"])
        return result
    monkeypatch.setattr(graphs, "build_graph", observe_graph)
    monkeypatch.setattr(eligibility, "validate_source_span_target_eligibility_v4", observe_eligibility)
    before = deepcopy(case["originals"]), deepcopy(case["bindings"])
    report = _prepare_wire_graph_v3(case)
    assert len(graph_calls) == len(replay_calls) == 2
    assert len(json.loads(_wire_graph_v3_request(case))) == 12
    assert report["physical_rows"] == case["eligibility"]["physical_rows"]
    assert report["row_references"] == case["eligibility"]["row_references"]
    assert [row["eligibility_output"] for row in report["output_occurrences"]] == case["eligibility"]["output_occurrences"]
    assert report["eligibility_report_raw_utf8"].encode() == case["eligibility_raw"]
    assert "eligibility_report" not in report and "join_manifest_raw_utf8" not in report
    assert _coordinate_graph_sha(case["eligibility_raw"]) != eligibility.source_span_target_eligibility_sha256(case["eligibility"])
    assert report["eligibility_report_reference"]["report_artifact_sha256"] == _coordinate_graph_sha(case["eligibility_raw"])
    assert report["join_manifest_reference"]["json_pointer"] == "/join_manifest_raw_utf8"
    retained = json.loads(report["eligibility_report_raw_utf8"])
    assert retained["join_manifest_raw_utf8"].encode() == case["join_raw"]
    assert json.loads(retained["join_manifest_raw_utf8"])["paired_bundles"][0]["payload_intake"]["source_coordinates"]["report_sha256"] == case["case"]["coordinate"]["pin"]
    assert case["joined"]["source_metadata_intake"]["source_identity"]["aliases_mapped"] is False
    assert [row["output_occurrence_ordinal"] for row in report["output_occurrences"]] == [0, 1]
    for row in report["output_occurrences"]:
        assert row["disposition"] == "proposed_unreviewed_graph"
        assert graphs.graph_to_ast(row["graph"]) == row["eligibility_output"]["canonical_ir"] == {"rules": [_COORDINATE_GRAPH_RULE]}
        assert row["graph_request"]["ast"] == row["eligibility_output"]["canonical_ir"]
        assert row["eligibility_output"]["source_coordinate_span_index"] == 1
        assert row["eligibility_output"]["source_provenance_json"] == case["case"]["coordinate"]["references"][0]
    assert _validate_wire_graph_v3(case, _coordinate_graph_wire(report)) == report
    assert len(graph_calls) == len(replay_calls) == 4
    assert (case["originals"], case["bindings"]) == before
    _assert_wire_graph_v3_unqualified(report, case)


def test_wire_graph_v3_unsupported_targets_remain_lossless_without_graphs(wire_graph_v3_case):
    case = wire_graph_v3_case; report = _prepare_wire_graph_v3(case)
    assert report["physical_rows"] == case["eligibility"]["physical_rows"]
    assert report["row_references"] == case["eligibility"]["row_references"]
    assert [row["eligibility_output"] for row in report["output_occurrences"]] == case["eligibility"]["output_occurrences"]
    assert report["output_occurrences"] and all(row["graph"] is None and row["disposition"] == "unresolved" for row in report["output_occurrences"])
    _assert_wire_graph_v3_unqualified(report, case)


@_repeated_coordinate_graph
def test_wire_graph_v3_equal_text_keeps_two_physical_sources_and_four_outputs(wire_graph_v3_case):
    case = wire_graph_v3_case; report = _prepare_wire_graph_v3(case)
    rows = report["physical_rows"]
    assert len(rows) == 2 and rows[0]["source_text"] == rows[1]["source_text"]
    assert len({row["physical_identity_sha256"] for row in rows}) == 2
    assert [row["source_coordinate_span_index"] for row in rows] == [1, 3]
    assert [row["output_occurrence_ordinal"] for row in report["output_occurrences"]] == [0, 1, 2, 3]
    assert [row["eligibility_output"]["source_coordinate_span_index"] for row in report["output_occurrences"]] == [1, 1, 3, 3]
    assert len({row["source_binding"]["selector"]["occurrence_id"] for row in report["output_occurrences"]}) == 2
    assert all(graphs.graph_to_ast(row["graph"]) == {"rules": [_COORDINATE_GRAPH_RULE]} for row in report["output_occurrences"])
    _assert_wire_graph_v3_unqualified(report, case)


@_supported_coordinate_graph
@pytest.mark.parametrize("old_profile", ["public-v2", "original-v3"])
def test_wire_graph_v3_refuses_genuine_older_eligibility_profiles_before_graph(request, coordinate_join, monkeypatch, old_profile):
    case = request.getfixturevalue("coordinate_graph_case" if old_profile == "public-v2" else "coordinate_graph_v2_case")
    monkeypatch.setattr(graphs, "build_graph", lambda *a, **kw: pytest.fail("foreign eligibility profile reached graph"))
    with pytest.raises(ValueError): _prepare_wire_graph_v3(case)


@_supported_coordinate_graph
@pytest.mark.parametrize("old_graph", ["v1", "v2"])
def test_wire_graph_v3_carrier_cannot_enter_either_old_graph_api(wire_graph_v3_case, monkeypatch, old_graph):
    case = wire_graph_v3_case
    monkeypatch.setattr(graphs, "build_graph", lambda *a, **kw: pytest.fail("wire eligibility silently entered old graph profile"))
    prepare = _prepare_coordinate_graph if old_graph == "v1" else _prepare_coordinate_graph_v2
    with pytest.raises(ValueError): prepare(case)


@_supported_coordinate_graph
@pytest.mark.parametrize("damage", ["missing-metadata", "foreign-profile", "extra-field"])
def test_wire_graph_v3_requires_exact_closed_profile_declarations(wire_graph_v3_case, monkeypatch, damage):
    case = wire_graph_v3_case; request = json.loads(_wire_graph_v3_request(case))
    if damage == "missing-metadata": request.pop("metadata_profile")
    elif damage == "foreign-profile": request["source_compatibility_profile"] = subject.COORDINATE_GRAPH_PROFILE_V2
    else: request["undeclared_wire_hint"] = True
    monkeypatch.setattr(graphs, "build_graph", lambda *a, **kw: pytest.fail("malformed graph declaration reached graph"))
    with pytest.raises(ValueError): _prepare_wire_graph_v3(case, request_raw=_coordinate_graph_wire(request))


@_supported_coordinate_graph
@pytest.mark.parametrize("pin", ["eligibility_report_raw_sha256", "eligibility_report_sha256", "join_originals_sha256", "source_bindings_sha256"])
def test_wire_graph_v3_independent_pins_cannot_be_repaired_by_outer_resealing(wire_graph_v3_case, pin):
    case = wire_graph_v3_case
    with pytest.raises(ValueError): _prepare_wire_graph_v3(case, request_raw=_wire_graph_v3_request(case, **{pin: "0" * 64}))


@_supported_coordinate_graph
@pytest.mark.parametrize("damage", ["eligibility-pointer", "global-index", "output-provenance", "training-mask"])
def test_wire_graph_v3_resealed_reference_provenance_or_mask_changes_refuse(wire_graph_v3_case, damage):
    case = wire_graph_v3_case; report = _prepare_wire_graph_v3(case)
    if damage == "eligibility-pointer": report["join_manifest_reference"]["json_pointer"] = "/unselected_join"
    elif damage == "global-index": report["physical_rows"][0]["source_coordinate_span_index"] = 0
    elif damage == "output-provenance": report["output_occurrences"][0]["eligibility_output"]["source_provenance_json"] += " "
    else: report["output_occurrences"][0]["training_mask"] = 1
    with pytest.raises(ValueError): _validate_wire_graph_v3(case, report)


@_repeated_coordinate_graph
@pytest.mark.parametrize("damage", ["drop-physical", "reverse-outputs", "reverse-references"])
def test_wire_graph_v3_resealed_population_order_or_omission_refuses(wire_graph_v3_case, damage):
    case = wire_graph_v3_case; report = _prepare_wire_graph_v3(case)
    if damage == "drop-physical": report["physical_rows"].pop()
    elif damage == "reverse-outputs": report["output_occurrences"].reverse()
    else: report["row_references"].reverse()
    with pytest.raises(ValueError): _validate_wire_graph_v3(case, report)


@_supported_coordinate_graph
@pytest.mark.parametrize("damage", ["revision", "ambiguous"])
def test_wire_graph_v3_independent_html_nomination_never_repairs_source_crosswalk(wire_graph_v3_case, damage):
    case = wire_graph_v3_case; binding = next(iter(case["bindings"].values()))
    if damage == "revision": binding["document_revision"] = "different-authored-release"
    else:
        raw = __import__("base64").b64decode(binding["raw_html_base64"])
        binding["candidate_selectors"] = context.exact_view_occurrences(binding["document"], raw, text="Clerk shall file report.")
        assert len(binding["candidate_selectors"]) == 2
    report = _prepare_wire_graph_v3(case)
    assert all(row["graph"] is None and row["disposition"] == "unresolved" and row["issues"] for row in report["output_occurrences"])
    assert [row["eligibility_output"] for row in report["output_occurrences"]] == case["eligibility"]["output_occurrences"]
    _assert_wire_graph_v3_unqualified(report, case)


@_supported_coordinate_graph
@pytest.mark.parametrize("damage", ["bindings", "originals", "eligibility-callable", "table"])
def test_wire_graph_v3_closing_replay_refuses_live_original_and_owner_changes(wire_graph_v3_case, monkeypatch, damage):
    case = wire_graph_v3_case; actual_graph = graphs.build_graph
    actual_validator = eligibility.validate_source_span_target_eligibility_v4; calls = []
    def replacement(*args, **kwargs): return actual_validator(*args, **kwargs)
    def mutate_after_genuine_graph(*args, **kwargs):
        result = actual_graph(*args, **kwargs); calls.append(result)
        if damage == "bindings": next(iter(case["bindings"].values()))["context_observation"]["status"] = "changed after graph"
        elif damage == "originals": case["originals"]["source_metadata_bytes"]["README.md"] += b"changed after graph"
        elif damage == "eligibility-callable": monkeypatch.setattr(eligibility, "validate_source_span_target_eligibility_v4", replacement)
        else:
            table = _coordinate_graph_retained_table(case); table.write_bytes(table.read_bytes() + b"changed after graph")
        return result
    monkeypatch.setattr(graphs, "build_graph", mutate_after_genuine_graph)
    with pytest.raises(ValueError): _prepare_wire_graph_v3(case)
    assert calls


@_supported_coordinate_graph
def test_wire_graph_v3_primary_error_preserves_genuine_closing_original_custody_failure(wire_graph_v3_case, monkeypatch):
    case = wire_graph_v3_case; actual_graph = graphs.build_graph
    actual_validator = eligibility.validate_source_span_target_eligibility_v4
    sentinel, calls, replays = RuntimeError("negative wire graph callback boundary"), [], []
    def observe_replay(*args, **kwargs):
        result = actual_validator(*args, **kwargs); replays.append(result); return result
    def fail_after_genuine_graph(*args, **kwargs):
        result = actual_graph(*args, **kwargs); calls.append(result)
        case["originals"]["source_metadata_bytes"]["README.md"] += b"changed before primary error"
        raise sentinel
    monkeypatch.setattr(eligibility, "validate_source_span_target_eligibility_v4", observe_replay)
    monkeypatch.setattr(graphs, "build_graph", fail_after_genuine_graph)
    with pytest.raises(RuntimeError) as caught: _prepare_wire_graph_v3(case)
    assert caught.value is sentinel and calls and len(replays) == 2
    assert any("original" in note and "changed" in note for note in getattr(sentinel, "__notes__", ()))


@_supported_coordinate_graph
def test_wire_graph_v3_validator_retains_offered_report_through_genuine_graph(wire_graph_v3_case, monkeypatch):
    case = wire_graph_v3_case; report = _prepare_wire_graph_v3(case)
    actual = graphs.build_graph; reached = []
    def mutate_offered(*args, **kwargs):
        graph = actual(*args, **kwargs); reached.append(graph)
        report["output_occurrences"][0]["context_observation"] = {"late": "offered-report-mutation"}
        return graph
    monkeypatch.setattr(graphs, "build_graph", mutate_offered)
    with pytest.raises(ValueError): _validate_wire_graph_v3(case, report)
    assert reached


@_supported_coordinate_graph
def test_wire_graph_v3_final_serialization_keeps_original_inputs_guarded(wire_graph_v3_case, monkeypatch):
    case = wire_graph_v3_case; genuine = subject._coordinate_graph_wire; reached = []
    genuine_validate = eligibility.validate_source_span_target_eligibility_v4; replays = []
    def observe_replay(*args, **kwargs):
        result = genuine_validate(*args, **kwargs); replays.append(result); return result
    def mutate_after_wire(value, *args, **kwargs):
        raw = genuine(value, *args, **kwargs)
        if len(replays) == 2 and not reached and type(value) is dict and value.get("schema") == "legal-coordinate-source-graph-intake/v3":
            reached.append(True); case["originals"]["source_metadata_bytes"]["README.md"] += b"changed after graph serialization"
        return raw
    monkeypatch.setattr(eligibility, "validate_source_span_target_eligibility_v4", observe_replay)
    monkeypatch.setattr(subject, "_coordinate_graph_wire", mutate_after_wire)
    with pytest.raises(ValueError): _prepare_wire_graph_v3(case)
    assert reached == [True] and len(replays) == 2


@_supported_coordinate_graph
def test_wire_graph_v3_nested_foreign_owner_path_refuses_before_body_read(wire_graph_v3_case, monkeypatch, tmp_path):
    case = wire_graph_v3_case; foreign = tmp_path / "foreign-graph-checkout"
    original_read = Path.read_bytes; original_file = graphs.__file__
    def refuse_foreign_read(path):
        assert foreign not in path.parents, "foreign graph owner read before canonical-path refusal"
        return original_read(path)
    monkeypatch.setattr(graphs, "__file__", str(foreign / "ipfs_datasets_py/logic/autoformal/legal_semantic_graph.py"))
    monkeypatch.setattr(Path, "read_bytes", refuse_foreign_read)
    with pytest.raises(ValueError): _prepare_wire_graph_v3(case)
    assert graphs.__file__ != original_file and not foreign.exists()


@_supported_coordinate_graph
def test_wire_graph_v3_keeps_genuine_graph_objects_guarded_after_closing_replay(wire_graph_v3_case, monkeypatch):
    case = wire_graph_v3_case
    genuine_graph = graphs.build_graph
    genuine_validate = eligibility.validate_source_span_target_eligibility_v4
    returned_graphs, replay_calls, changed = [], [], []
    def capture_graph(*args, **kwargs):
        graph = genuine_graph(*args, **kwargs); returned_graphs.append(graph); return graph
    def mutate_after_genuine_closing(*args, **kwargs):
        result = genuine_validate(*args, **kwargs); replay_calls.append(result)
        if len(replay_calls) == 2:
            assert len(returned_graphs) == 2
            returned_graphs[0]["graph_id"] = "0" * 64
            changed.append(True)
        return result
    monkeypatch.setattr(graphs, "build_graph", capture_graph)
    monkeypatch.setattr(eligibility, "validate_source_span_target_eligibility_v4", mutate_after_genuine_closing)
    with pytest.raises(ValueError): _prepare_wire_graph_v3(case)
    assert changed == [True] and len(replay_calls) == len(returned_graphs) == 2


@_supported_coordinate_graph
@pytest.mark.parametrize("damage", ["originals", "bindings"])
def test_wire_graph_v3_outer_validator_keeps_caller_inputs_after_genuine_inner_prepare(wire_graph_v3_case, monkeypatch, damage):
    case = wire_graph_v3_case; report = _prepare_wire_graph_v3(case)
    genuine_prepare = subject._prepare_coordinate_source_graph_intake
    changed = []
    def mutate_after_genuine_inner(*args, **kwargs):
        result = genuine_prepare(*args, **kwargs)
        assert kwargs["profile_version"] == 3
        if damage == "originals": case["originals"]["source_metadata_bytes"]["README.md"] += b"changed after complete inner graph prepare"
        else: next(iter(case["bindings"].values()))["context_observation"]["status"] = "changed after complete inner graph prepare"
        changed.append(True)
        return result
    monkeypatch.setattr(subject, "_prepare_coordinate_source_graph_intake", mutate_after_genuine_inner)
    with pytest.raises(ValueError): _validate_wire_graph_v3(case, report)
    assert changed == [True]


@_supported_coordinate_graph
def test_wire_graph_v3_outer_parsed_retained_cannot_nominate_a_foreign_file(wire_graph_v3_case, monkeypatch):
    case = wire_graph_v3_case; report = _prepare_wire_graph_v3(case)
    genuine_preflight = subject._coordinate_graph_preflight
    genuine_prepare = subject._prepare_coordinate_source_graph_intake
    genuine_files = coordinate_join_owner._coordinate_file_witnesses
    outer, changed, file_calls = [], [], []
    sentinel = "unselected/outer-wire-graph-validator.parquet"
    def observe_preflight(*args, **kwargs):
        result = genuine_preflight(*args, **kwargs)
        if kwargs.get("profile_version") == 3: outer.append(result)
        return result
    def mutate_after_genuine_inner(*args, **kwargs):
        result = genuine_prepare(*args, **kwargs)
        assert kwargs["profile_version"] == 3 and len(outer) >= 2
        outer[0][2]["span_inventory"]["manifests"][0]["manifest"]["tables"]["paired_spans"]["path_in_repo"] = sentinel
        changed.append(True)
        return result
    def observe_files(location, selected):
        assert sentinel not in [row["path_in_repo"] for row in selected["manifest"]["tables"].values()], \
            "mutated outer retained graph state nominated an unselected file"
        file_calls.append(True)
        return genuine_files(location, selected)
    monkeypatch.setattr(subject, "_coordinate_graph_preflight", observe_preflight)
    monkeypatch.setattr(subject, "_prepare_coordinate_source_graph_intake", mutate_after_genuine_inner)
    monkeypatch.setattr(coordinate_join_owner, "_coordinate_file_witnesses", observe_files)
    with pytest.raises(ValueError): _validate_wire_graph_v3(case, report)
    assert changed == [True] and file_calls


@_supported_coordinate_graph
def test_wire_graph_v3_detached_returned_report_stays_guarded_after_serialization(wire_graph_v3_case, monkeypatch):
    case = wire_graph_v3_case
    genuine_read, genuine_wire = subject._coordinate_graph_read, subject._coordinate_graph_wire
    genuine_validate = eligibility.validate_source_span_target_eligibility_v4
    detached, changed, replays = [], [], []
    def observe_replay(*args, **kwargs):
        result = genuine_validate(*args, **kwargs); replays.append(result); return result
    def capture_detached(*args, **kwargs):
        value = genuine_read(*args, **kwargs)
        if type(value) is dict and value.get("schema") == "legal-coordinate-source-graph-intake/v3": detached.append(value)
        return value
    def mutate_after_wire(value, *args, **kwargs):
        raw = genuine_wire(value, *args, **kwargs)
        if len(replays) == 2 and not changed and any(value is observed for observed in detached):
            value["counts"]["proposed_unreviewed_graphs"] += 1
            changed.append(True)
        return raw
    monkeypatch.setattr(subject, "_coordinate_graph_read", capture_detached)
    monkeypatch.setattr(subject, "_coordinate_graph_wire", mutate_after_wire)
    monkeypatch.setattr(eligibility, "validate_source_span_target_eligibility_v4", observe_replay)
    with pytest.raises(ValueError): _prepare_wire_graph_v3(case)
    assert changed == [True] and detached and len(replays) == 2
