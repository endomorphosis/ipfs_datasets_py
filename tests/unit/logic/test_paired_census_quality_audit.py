"""Pure census audit reporting and bounded private-reader controls.

Explicit loaders return private synthetic bundles here; they do not stand in
for native bundle authentication, semantic qualification or a Lake build.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


@pytest.fixture(scope="module")
def auditor():
    tree = Path(__file__).resolve().parents[3]
    path = tree / "scripts/ops/legal_ir/audit_paired_census_quality.py"
    name = "_test_paired_census_quality_auditor"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def formal(origin, family="typed_deontic", metadata=None):
    payload = {"modality": "prohibition", "actor": "agency", "action": "disclose", "object": "records"}
    if metadata is not None:
        payload["metadata"] = metadata
    encoded = json.dumps(payload, sort_keys=True)
    return {"origin": origin, "family": family, "format": "typed-deontic-rule/v1",
        "syntax_status": "compiler_accepted", "payload_json": encoded,
        "sha256": hashlib.sha256(encoded.encode()).hexdigest(), "target_conditioned": False}


def bundle(text="The agency shall not disclose records."):
    source = {"span_id": "usc:fixture:1", "legal_id": "usc:fixture", "text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "revision": "fixed-source-revision", "constitution": False}
    row = {"observation_id": "observation-1", "source": source,
        "compiler": {"status": "compiled", "reason": "", "canonical_complete": True, "complete": False,
            "canonical_formal_outputs": [formal("canonical_compiler")], "formal_outputs": [],
            "roundtrip_ok": False, "decompiled": "The agency must not disclose records.", "components_artifact_sha256": "c" * 64,
            "components_artifact_pointer": "/rows/0/compiler/components"},
        "autoencoder": {"status": "guided_no_formulas", "formal_outputs": [], "model_identity": "legacy8-fixture",
            "embedding_model": "mock:stable-sha256/8", "semantic_embeddings": False,
            "learned_formula_capture_verified": False},
        "comparison": {"status": "both_unavailable", "independent": False, "comparable": False,
            "agrees": None, "reason": "neither_comparison_producer_emitted_formal_output"},
        "goal_ids": ["goal-retained"], "lake": {"admitted": False, "status": "not_run"},
        "provenance": {"bridge_names": ["modal_frame_logic"], "parallel_workers": 1, "sample_count": 1},
        "source_target_artifact_sha256": "b" * 64, "source_target_artifact_pointer": "/rows/0/target",
        "admitted": False, "formalized": False}
    goal = {"goal_id": "goal-retained", "issue": "formal_output_unavailable", "record_kind": "repair_goal",
        "packet_artifact_sha256": "d" * 64, "source_span_ids": [source["span_id"]],
        "original_packet_field": {"must": "survive"}, "admitted": False, "enqueued": False}
    return {"paired_spans": [row], "goals": [goal], "artifacts": [],
        "manifest_sha256": "a" * 64, "repository_id": "fixture-repository",
        "manifest": {"path_in_repo": "autoformal/uscode/paired-v2/fixture/manifest.json"},
        "admitted": False, "formalized": False, "enqueued": False}


def manifest(tmp_path, name="manifest.json", declared_bytes=32):
    path = tmp_path / name
    path.write_text(json.dumps({"fixture_name": name, "tables": {"paired_spans": {"bytes": declared_bytes}}}))
    return path


def reader_for(value, calls):
    def read(path, **kwargs):
        calls.append((Path(path), kwargs))
        result = copy.deepcopy(value)
        result["manifest_sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return result
    return read


def test_canonical_compile_with_no_modal_comparison_outputs_is_reported_separately(auditor):
    value = bundle()
    untouched = copy.deepcopy(value)
    result = auditor.summarize_bundle(value, Path("/private/manifest.json"))
    assert result["totals"]["canonical_formal_outputs"] == 1
    assert result["totals"]["compiler_view_outputs"] == result["totals"]["autoencoder_formal_outputs"] == 0
    assert result["totals"]["canonical_compiled_rows"] == 1
    assert result["totals"]["producer_canonical_complete_rows"] == 1
    assert result["totals"]["canonical_output_with_comparison_unavailable_rows"] == 1
    observed = result["rows"][0]
    assert observed["producer_canonical_complete"] is True
    assert observed["canonical_output_comparison_unavailable"] is True
    assert observed["decompiled"] == value["paired_spans"][0]["compiler"]["decompiled"]
    assert observed["provenance"] == value["paired_spans"][0]["provenance"]
    assert observed["lake_observation"] == value["paired_spans"][0]["lake"]
    assert observed["formal_outputs"]["canonical_compiler"] == value["paired_spans"][0]["compiler"]["canonical_formal_outputs"]
    assert observed["formal_outputs"]["compiler_view"] == []
    assert observed["comparison"]["status"] == "both_unavailable"
    assert result["counts"]["formal_outputs"][0]["stream"] == "canonical_compiler"
    assert result["admitted"] is False and result["formalized"] is False
    assert value == untouched


def test_guided_agreement_remains_diagnostic_and_does_not_become_independent(auditor):
    value = bundle()
    row = value["paired_spans"][0]
    row["compiler"]["formal_outputs"] = [formal("direct_compiler", "fol")]
    row["autoencoder"]["formal_outputs"] = [formal("autoencoder_guided_compiler", "fol")]
    row["comparison"] = {"status": "diagnostic_agree", "independent": False, "comparable": True, "agrees": True}
    result = auditor.summarize_bundle(value, "/private/manifest.json")
    assert result["totals"]["diagnostic_comparable_rows"] == result["totals"]["diagnostic_agreement_rows"] == 1
    assert result["totals"]["independent_comparison_claims"] == 0
    assert result["totals"]["independent_comparable_rows"] == result["totals"]["independent_agreement_rows"] == 0
    assert result["rows"][0]["comparison"] == row["comparison"]
    assert result["rows"][0]["semantic_embeddings"] is False
    assert result["admitted"] is False


def test_independent_agreement_is_only_a_retained_comparison_claim(auditor):
    value = bundle()
    row = value["paired_spans"][0]
    row["comparison"] = {"status": "agree", "independent": True, "comparable": True, "agrees": True}
    row["compiler"]["formal_outputs"] = [formal("direct_compiler", "fol")]
    row["autoencoder"]["formal_outputs"] = [formal("autoencoder_decoder", "fol")]
    result = auditor.summarize_bundle(value, "/private/manifest.json")
    assert result["totals"]["independent_comparison_claims"] == result["totals"]["independent_agreement_rows"] == 1
    assert result["totals"]["diagnostic_agreement_rows"] == 0
    assert result["admitted"] is False and result["formalized"] is False
    assert result["goals"] == value["goals"]


def test_fallback_cues_do_not_replace_full_formulas_or_source_and_goal_references(auditor):
    value = bundle()
    metadata = {"cue": "inferred-recipient", "fallback_rule": "recipient-only", "residual_segment_role": "object",
        "residual_token_count": 7, "aliased_from": ["original_predicate"], "retained_unrecognized_field": {"value": 0.25}}
    output = formal("direct_compiler", "fol", metadata)
    value["paired_spans"][0]["compiler"]["formal_outputs"] = [output]
    original = copy.deepcopy(value)
    result = auditor.summarize_bundle(value, "/private/manifest.json")
    row = result["rows"][0]
    assert row["formal_outputs"]["compiler_view"] == [output]
    assert json.loads(row["formal_outputs"]["compiler_view"][0]["payload_json"])["metadata"] == metadata
    assert row["fallback_metadata"] == [{"stream": "compiler_view", "formula_sha256": output["sha256"],
        "metadata": {key: metadata[key] for key in ["cue", "fallback_rule", "residual_segment_role", "residual_token_count", "aliased_from"]}}]
    assert row["source"] == value["paired_spans"][0]["source"]
    assert row["source_target_artifact_pointer"] == "/rows/0/target"
    assert row["compiler_components_artifact_pointer"] == "/rows/0/compiler/components"
    assert row["goal_ids"] == ["goal-retained"] and result["goals"] == value["goals"]
    assert value == original


@pytest.mark.parametrize("text,kind", [
    ("Government Publishing Office, www.gpo.gov", "editorial_gpo_footer"),
    ("Statutory Notes and Related Subsidiaries", "editorial_notes_heading"),
    ("The section was added by Pub. L.", "truncated_public_law_reference"),
])
def test_source_quality_cues_only_request_review_and_never_drop_repair_goals(auditor, text, kind):
    value = bundle(text)
    result = auditor.summarize_bundle(value, "/private/manifest.json")
    hypotheses = result["rows"][0]["classification_review_hypotheses"]
    assert kind in {item["kind"] for item in hypotheses}
    assert all(item["requires_context_review"] is True and item["classification_proven"] is False for item in hypotheses)
    assert result["totals"]["spans"] == result["totals"]["goals"] == 1
    assert result["rows"][0]["source"]["text"] == text
    assert result["goals"] == value["goals"] and result["rows"][0]["goal_ids"] == ["goal-retained"]
    assert "non_operative" not in result["rows"][0]


@pytest.mark.parametrize("text", [
    "The agency shall submit a report to the Government Publishing Office.",
    "The section was added by Pub. L. 98-10, section 2.",
])
def test_ordinary_legal_sentence_or_complete_citation_is_not_an_editorial_cue(auditor, text):
    assert auditor.review_hypotheses(text) == []


def test_enumerated_source_and_recipient_shaped_object_request_context_without_rewriting(auditor):
    value = bundle("The Secretary shall submit (A) a report and (B) a record to Congress.")
    output = value["paired_spans"][0]["compiler"]["canonical_formal_outputs"][0]
    payload = json.loads(output["payload_json"])
    payload["object"] = "to Congress"
    output["payload_json"] = json.dumps(payload)
    original = copy.deepcopy(value)
    result = auditor.summarize_bundle(value, "/private/manifest.json")
    candidates = result["rows"][0]["classification_review_hypotheses"]
    assert len(candidates) == 1 and candidates[0]["kind"] == "enumerated_object_context_review"
    assert candidates[0]["requires_context_review"] is True and candidates[0]["classification_proven"] is False
    assert result["rows"][0]["formal_outputs"]["canonical_compiler"] == [output]
    assert result["goals"] == value["goals"] and value == original


@pytest.mark.parametrize("damage", ["no_enumeration", "full_object"])
def test_enumeration_hypothesis_requires_both_observed_cues(auditor, damage):
    text = "The Secretary shall submit (A) a report and (B) a record to Congress."
    value = bundle("The Secretary shall submit a report to Congress." if damage == "no_enumeration" else text)
    output = value["paired_spans"][0]["compiler"]["canonical_formal_outputs"][0]
    payload = json.loads(output["payload_json"])
    payload["object"] = "a report and a record to Congress" if damage == "full_object" else "to Congress"
    output["payload_json"] = json.dumps(payload)
    result = auditor.summarize_bundle(value, "/private/manifest.json")
    assert result["rows"][0]["classification_review_hypotheses"] == []


@pytest.mark.parametrize("damage", ["bundle", "row", "lake", "constitution_roundtrip"])
def test_authority_and_constitution_roundtrip_claims_are_rejected(auditor, damage):
    value = bundle()
    if damage == "bundle": value["admitted"] = True
    elif damage == "row": value["paired_spans"][0]["formalized"] = True
    elif damage == "lake": value["paired_spans"][0]["lake"]["admitted"] = True
    else:
        value["paired_spans"][0]["source"]["constitution"] = True
        value["paired_spans"][0]["compiler"]["roundtrip_ok"] = True
    with pytest.raises(ValueError):
        auditor.summarize_bundle(value, "/private/manifest.json")


@pytest.mark.parametrize("options", [
    {"max_manifests": True}, {"max_manifests": 17}, {"max_rows": 0}, {"max_rows": 65},
    {"max_total_bytes": 0}, {"max_total_bytes": 64 * 1024**2 + 1},
])
def test_invalid_limits_refuse_before_any_reader_call(auditor, tmp_path, options):
    calls = []
    with pytest.raises(ValueError):
        auditor.audit_manifests([tmp_path / "not-even-opened.json"], loader=reader_for(bundle(), calls), **options)
    assert calls == []


@pytest.mark.parametrize("alias", ["same_path", "hardlink"])
def test_duplicate_manifest_identity_refuses_before_loading(auditor, tmp_path, alias):
    path = manifest(tmp_path)
    other = path
    if alias == "hardlink":
        other = tmp_path / "hardlink.json"
        os.link(path, other)
    calls = []
    with pytest.raises(ValueError, match="duplicate"):
        auditor.audit_manifests([path, other], loader=reader_for(bundle(), calls))
    assert calls == []


def test_separate_copies_of_identical_manifest_bytes_refuse_before_loading(auditor, tmp_path):
    path = manifest(tmp_path)
    duplicate = tmp_path / "copied-content.json"
    duplicate.write_bytes(path.read_bytes())
    assert path.stat().st_ino != duplicate.stat().st_ino
    calls = []
    with pytest.raises(ValueError, match="duplicate"):
        auditor.audit_manifests([path, duplicate], loader=reader_for(bundle(), calls))
    assert calls == []


def test_selected_count_and_declared_byte_bounds_are_checked_before_loader(auditor, tmp_path):
    paths = [manifest(tmp_path, "first.json"), manifest(tmp_path, "second.json", declared_bytes=999)]
    calls = []
    with pytest.raises(ValueError):
        auditor.audit_manifests(paths, max_manifests=1, loader=reader_for(bundle(), calls))
    with pytest.raises(ValueError):
        auditor.audit_manifests(paths, max_total_bytes=256, loader=reader_for(bundle(), calls))
    assert calls == []


def test_injected_loader_retains_decompressed_ceiling_and_row_limit_with_no_report_authority(auditor, tmp_path):
    path = manifest(tmp_path)
    original = bundle()
    calls = []
    result = auditor.audit_manifests([path], max_rows=8, loader=reader_for(original, calls))
    expected_charge = path.stat().st_size + 32
    assert calls == [(path, {"max_bytes": 64 * 1024**2, "max_rows": 8})]
    assert result["bounded_input_bytes"] == expected_charge
    assert 0 < result["retained_record_json_bytes"] <= 64 * 1024**2
    assert result["totals"]["spans"] == result["totals"]["canonical_formal_outputs"] == 1
    assert result["totals"]["portable_goals"] == 1
    assert result["batches"][0]["manifest_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result["goals"] == original["goals"]
    assert all(result[key] is False for key in ["admitted", "Lean_admitted", "formalized", "enqueued",
        "Constitution_formalized", "model_executed", "compiler_executed", "goals_modified", "inputs_filtered"])


def test_different_manifest_returned_by_loader_is_not_accepted(auditor, tmp_path):
    path = manifest(tmp_path)
    calls = []
    def wrong_reader(path, **kwargs):
        calls.append(path)
        return bundle()
    with pytest.raises(ValueError, match="different manifest"):
        auditor.audit_manifests([path], loader=wrong_reader)
    assert calls == [path]


def test_two_selected_bundles_aggregate_counts_and_keep_every_goal_and_formula(auditor, tmp_path):
    paths = [manifest(tmp_path, "first.json"), manifest(tmp_path, "second.json")]
    value = bundle()
    calls = []
    result = auditor.audit_manifests(paths, loader=reader_for(value, calls))
    assert len(calls) == 2 and len(result["rows"]) == 2
    assert result["totals"]["spans"] == result["totals"]["goals"] == 2
    assert result["totals"]["canonical_formal_outputs"] == 2
    assert result["counts"]["formal_outputs"] == [{"stream": "canonical_compiler", "origin": "canonical_compiler",
        "format": "typed-deontic-rule/v1", "family": "typed_deontic", "syntax_status": "compiler_accepted", "count": 2}]
    assert result["goals"] == value["goals"] + value["goals"]


def test_aggregate_retained_record_ceiling_refuses_without_mutating_source_records(auditor, tmp_path, monkeypatch):
    path = manifest(tmp_path)
    before = path.read_bytes()
    value = bundle()
    original = copy.deepcopy(value)
    calls = []
    monkeypatch.setattr(auditor, "MAX_RETAINED_BYTES", 1)
    with pytest.raises(ValueError, match="retained"):
        auditor.audit_manifests([path], loader=reader_for(value, calls))
    assert len(calls) == 1
    assert value == original and path.read_bytes() == before
    assert sorted(q.name for q in tmp_path.iterdir()) == [path.name]


def test_final_serialized_report_ceiling_refuses_before_any_report_is_returned(auditor, tmp_path, monkeypatch):
    path = manifest(tmp_path)
    value = bundle()
    original = copy.deepcopy(value)
    calls = []
    monkeypatch.setattr(auditor, "MAX_REPORT_BYTES", 1)
    with pytest.raises(ValueError, match="report"):
        auditor.audit_manifests([path], loader=reader_for(value, calls))
    assert len(calls) == 1 and value == original
    assert sorted(q.name for q in tmp_path.iterdir()) == [path.name]
