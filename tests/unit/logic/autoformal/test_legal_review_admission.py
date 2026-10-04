"""Clearly synthetic review fixtures exercise structure, never reviewer truth."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_review_admission as admission

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location("admission_packet_builder", ROOT / "scripts/ops/legal_ir/build_legal_decoder_review_packet.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return admission.read_json(path)


@pytest.fixture
def fixture(tmp_path):
    # Names, identities, receipts and text in this fixture are fictional.
    text = "The Café Officer shall file the record if notified."
    text_hash = admission.sha256(text)
    group_id = "source-text-sha256:" + text_hash
    observations = [{"source_span_id": identity, "source_text_variants": [text], "legal_ids": ["synthetic:section:1"],
                     "training_qualified": False, "gold_target": None, "occurrences": []}
                    for identity in ("synthetic-span-A", "synthetic-span-B")]
    group = {"text_group_id": group_id, "source_text": text, "source_text_sha256": text_hash,
             "source_observations": observations, "review_status": "unreviewed", "training_qualified": False,
             "gold_target": None, "model_predictions_by_seed": [{"predictions": [{"prediction_id": "synthetic-prediction-A"}]}]}
    packet, packet_receipt = write(tmp_path / "synthetic-packet.json", {
        "schema": admission.PACKET_SCHEMA, "status": "unreviewed", "training_qualified": False,
        "review_submission_schema": builder.review_submission_schema(), "groups": [group],
        "deduplication": {"source_observations": 2, "unique_text_groups": 1, "contexts_merged": False}})
    context, context_receipt = write(tmp_path / "synthetic-context.json", {
        "schema": "legal-review-source-context/v1", "source_span_id": "synthetic-span-A",
        "source_text": text, "source_text_sha256": text_hash, "legal_ids": ["synthetic:section:1"],
        "document_version": "synthetic fixture version", "source_locator": "synthetic://fixture/section-1",
        "context_text": "Heading. " + text + " Next section.", "span_start": 9, "span_end": 9 + len(text)})

    def grounded(value):
        start = text.index(value)
        return {"value": value, "source_refs": [{"source_span_id": "synthetic-span-A", "source_text_sha256": text_hash,
                "char_start": start, "char_end": start + len(value), "text": value,
                "context_artifact_sha256": context_receipt["sha256"]}]}

    condition = grounded("if notified") | {"attachment_rule_ids": ["synthetic-rule-1"], "scope_explanation": "Synthetic condition attaches to this rule."}
    interpretation = {"interpretation_id": "synthetic-interpretation-1", "family": admission.SUPPORTED_FAMILY,
                      "profile": admission.SUPPORTED_PROFILE, "coverage_explanation": "Synthetic annotation only.",
                      "unrepresented_meaning": [], "rules": [{"rule_id": "synthetic-rule-1", "modality": "O",
                      "actor": grounded("The Café Officer"), "action": grounded("file"), "object": grounded("the record"),
                      "conditions": [condition], "exceptions": [], "temporal": [],
                      "quantifier_and_negation_scope": "Synthetic unquantified example; no negation.", "cross_references": []}]}
    reviews = [{"reviewer_id": identity, "role": role, "independent_of_model_and_annotation_author": True,
                "reviewed_at": "2026-10-02T12:00:00Z", "evidence_receipt": "synthetic receipt; not an authenticated review",
                "decision": "accept", "reason": "Synthetic fixture for validator testing only.",
                "prediction_ids_considered": ["synthetic-prediction-A"], "proposed_interpretations": [deepcopy(interpretation)]}
               for identity, role in (("synthetic-legal-reviewer", "legal_semantic"), ("synthetic-formal-reviewer", "formal_methods"))]
    submission = {"schema": "legal-decoder-independent-review-submission/v1", "packet_sha256": packet_receipt["sha256"],
                  "text_group_id": group_id, "source_text_sha256": text_hash, "source_span_ids_reviewed": ["synthetic-span-A"],
                  "context_receipts": ["sha256:" + context_receipt["sha256"]], "reviews": reviews, "training_qualified": False,
                  "adjudication": {"adjudicator_id": "synthetic-adjudicator", "independent_of_model_and_annotation_author": True,
                  "adjudicated_at": "2026-10-02T13:00:00Z", "evidence_receipt": "synthetic adjudication receipt",
                  "decision": "accept", "reason": "Synthetic fixture only.",
                  "accepted_interpretation_ids": [interpretation["interpretation_id"]], "eligible_use": "positive_candidate"}}
    return packet, packet_receipt, submission, [(context, context_receipt)]


def validate(fixture):
    packet, receipt, submission, contexts = fixture
    return admission.validate_submission(packet, packet_receipt=receipt, submission=submission, context_artifacts=contexts)


def test_structural_success_never_claims_review_truth_or_training_qualification(fixture):
    before = deepcopy(fixture)
    result = validate(fixture)
    assert result["status"] == "structurally_valid_pending_external_verification"
    for key in ("reviewer_identity_verified", "reviewer_independence_verified", "review_receipt_authenticity_verified",
                "semantic_correctness_verified", "family_compliance_verified", "lake_build_executed", "training_qualified", "admitted"):
        assert result[key] is False
    assert result["gold_target"] is None
    assert fixture == before


@pytest.mark.parametrize("edit,match", [
    (lambda s: s.update(packet_sha256="0" * 64), "packet hash"),
    (lambda s: s.update(source_text_sha256="0" * 64), "text group or source hash"),
    (lambda s: s.update(source_span_ids_reviewed=["synthetic-other"]), "observation"),
    (lambda s: s.update(source_span_ids_reviewed=["synthetic-span-A", "synthetic-span-B"]), "one source observation"),
    (lambda s: s["reviews"][1].update(reviewer_id="SYNTHETIC-LEGAL-REVIEWER"), "duplicate reviewer identity"),
    (lambda s: s["reviews"][1].update(role="legal_semantic"), "schema violation"),
    (lambda s: s["reviews"][1].update(reviewer_id=" synthetic-formal-reviewer"), "invalid reviewer identity"),
    (lambda s: s["adjudication"].update(adjudicator_id="synthetic-legal-reviewer"), "distinct from reviewers"),
    (lambda s: s["adjudication"].update(adjudicated_at="2026-10-02T11:00:00Z"), "predates"),
    (lambda s: s["reviews"][0].update(reviewed_at="2026-10-02"), "time and time zone"),
    (lambda s: s["reviews"][0].update(prediction_ids_considered=["invented-prediction"]), "unknown prediction"),
    (lambda s: s["reviews"][0].update(decision="reject"), "negative or pending"),
    (lambda s: s["reviews"][0].update(decision="multiple_interpretations"), "requires alternatives"),
    (lambda s: s["adjudication"].update(accepted_interpretation_ids=["missing"]), "unknown interpretation"),
    (lambda s: s["adjudication"].update(decision="reject"), "nonaccept"),
    (lambda s: s["adjudication"].update(eligible_use="repair_candidate"), "candidate use contradicts"),
    (lambda s: s.update(training_qualified=True), "schema violation"),
    (lambda s: s.update(gold_target="invented"), "schema violation"),
    (lambda s: s.update(context_receipts=[]), "context binding"),
    (lambda s: s.update(context_receipts=["unverified-url"]), "must use sha256"),
    (lambda s: s.update(context_receipts=["sha256:" + "0" * 64]), "unavailable"),
])
def test_invalid_identity_decision_and_authority_claims_fail(fixture, edit, match):
    edit(fixture[2])
    with pytest.raises(admission.ReviewAdmissionError, match=match):
        validate(fixture)


@pytest.mark.parametrize("edit,match", [
    (lambda i: i.update(family="fol"), "unsupported interpretation"),
    (lambda i: i.update(profile="arbitrary"), "unsupported interpretation"),
    (lambda i: i["rules"][0]["actor"]["source_refs"][0].update(text="forged"), "offset slice differs"),
    (lambda i: i["rules"][0]["actor"]["source_refs"][0].update(char_end=17), "offset slice differs"),
    (lambda i: i["rules"][0]["actor"]["source_refs"][0].update(char_start=True), "schema violation"),
    (lambda i: i["rules"][0]["actor"]["source_refs"][0].update(source_text_sha256="0" * 64), "identity or hash differs"),
    (lambda i: i["rules"][0]["actor"]["source_refs"][0].update(source_span_id="synthetic-span-B"), "identity or hash differs"),
    (lambda i: i["rules"][0]["conditions"][0].update(attachment_rule_ids=["unknown"]), "unknown rule"),
    (lambda i: i["rules"].append(deepcopy(i["rules"][0])), "duplicate rule identity"),
    (lambda i: i.update(unrepresented_meaning=["Unresolved omitted exception"]), "unrepresented meaning"),
])
def test_source_ranges_and_scope_fail_closed(fixture, edit, match):
    for review in fixture[2]["reviews"]:
        edit(review["proposed_interpretations"][0])
    with pytest.raises(admission.ReviewAdmissionError, match=match):
        validate(fixture)


def test_conflicting_interpretation_ids_are_rejected(fixture):
    fixture[2]["reviews"][1]["proposed_interpretations"][0]["rules"][0]["modality"] = "P"
    with pytest.raises(admission.ReviewAdmissionError, match="conflicting content"):
        validate(fixture)


def test_distinct_review_interpretations_do_not_silently_merge(fixture):
    fixture[2]["reviews"][1]["proposed_interpretations"][0]["interpretation_id"] = "synthetic-alternative"
    with pytest.raises(admission.ReviewAdmissionError, match="consistent support"):
        validate(fixture)


def test_shared_attachment_must_be_present_at_each_referenced_rule(fixture):
    for review in fixture[2]["reviews"]:
        rules = review["proposed_interpretations"][0]["rules"]
        extra = deepcopy(rules[0]); extra["rule_id"] = "synthetic-rule-2"; extra["conditions"] = []
        rules.append(extra)
        rules[0]["conditions"][0]["attachment_rule_ids"].append("synthetic-rule-2")
    with pytest.raises(admission.ReviewAdmissionError, match="shared attachment missing"):
        validate(fixture)
    for review in fixture[2]["reviews"]:
        rules = review["proposed_interpretations"][0]["rules"]
        rules[1]["conditions"] = deepcopy(rules[0]["conditions"])
    assert validate(fixture)["admitted"] is False


@pytest.mark.parametrize("decision,use", [("reject", "exclude"), ("abstain", "abstention_candidate"),
                                         ("needs_context", "pending"), ("unresolved", "pending")])
def test_negative_and_pending_decisions_are_retained_without_context(fixture, decision, use):
    for review in fixture[2]["reviews"]:
        review.update(decision="needs_context", proposed_interpretations=[])
    fixture[2]["context_receipts"] = []
    fixture[2]["adjudication"].update(decision=decision, eligible_use=use, accepted_interpretation_ids=[])
    result = admission.validate_submission(fixture[0], packet_receipt=fixture[1], submission=fixture[2])
    assert result["declared_adjudication"] == decision and result["training_qualified"] is False


def test_correction_requires_repair_candidate_use(fixture):
    fixture[2]["reviews"][0]["decision"] = "correct"
    with pytest.raises(admission.ReviewAdmissionError, match="candidate use contradicts"):
        validate(fixture)
    fixture[2]["adjudication"]["eligible_use"] = "repair_candidate"
    assert validate(fixture)["declared_candidate_use"] == "repair_candidate"


def test_context_bytes_and_offsets_revalidated(fixture):
    path = Path(fixture[3][0][1]["path"])
    path.write_text(path.read_text() + " ")
    with pytest.raises(admission.ReviewAdmissionError, match="context artifact bytes differ"):
        validate(fixture)
    context, receipt = admission.read_json(path)
    context["span_start"] += 1
    fixture[3][0] = write(path, context)
    fixture[2]["context_receipts"] = ["sha256:" + fixture[3][0][1]["sha256"]]
    with pytest.raises(admission.ReviewAdmissionError, match="context source offset slice"):
        validate(fixture)


def test_context_for_duplicate_text_cannot_be_inherited(fixture):
    context, receipt = fixture[3][0]
    context["source_span_id"] = "synthetic-span-B"
    fixture[3][0] = write(Path(receipt["path"]), context)
    fixture[2]["context_receipts"] = ["sha256:" + fixture[3][0][1]["sha256"]]
    with pytest.raises(admission.ReviewAdmissionError, match="another observation"):
        validate(fixture)


def test_packet_schema_cannot_be_weakened(fixture):
    fixture[0]["review_submission_schema"] = {}
    with pytest.raises(admission.ReviewAdmissionError, match="pinned schema"):
        validate(fixture)


def test_packet_bytes_are_reverified(fixture):
    path = Path(fixture[1]["path"])
    path.write_text(path.read_text() + " ")
    with pytest.raises(admission.ReviewAdmissionError, match="packet receipt differs"):
        validate(fixture)


def test_empty_intake_is_pending_not_a_review(fixture):
    report = admission.intake_report(Path(fixture[1]["path"]))
    assert report["counts"]["source_observations"] == 2
    assert report["counts"]["unique_text_groups"] == 1
    assert report["counts"]["submissions"] == 0
    assert all(row["status"] == "no_external_submission" for row in report["observations"])
    assert report["gold_targets_created"] == 0 and report["reviewers_contacted"] is False


def test_intake_reports_invalid_submission_without_promoting_valid_one(fixture, tmp_path):
    good = tmp_path / "synthetic-submission-good.json"; bad = tmp_path / "synthetic-submission-bad.json"
    write(good, fixture[2])
    invalid = deepcopy(fixture[2]); invalid["training_qualified"] = True
    write(bad, invalid)
    report = admission.intake_report(Path(fixture[1]["path"]), submission_paths=[good, bad],
                                     context_paths=[Path(fixture[3][0][1]["path"])])
    assert report["counts"]["structurally_valid"] == 1
    assert report["counts"]["rejected_structurally"] == 1
    assert report["counts"]["training_qualified_observations"] == 0


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_strict_json_loader(raw, tmp_path):
    path = tmp_path / "bad.json"; path.write_text(raw)
    with pytest.raises(admission.ReviewAdmissionError):
        admission.read_json(path)


def test_input_size_limit(tmp_path):
    path = tmp_path / "bounded.json"; path.write_text('{"x": "long"}')
    with pytest.raises(admission.ReviewAdmissionError, match="byte budget"):
        admission.read_json(path, max_bytes=4)


def test_non_utf8_json_is_rejected(tmp_path):
    path = tmp_path / "utf16.json"; path.write_bytes('{"x":1}'.encode("utf-16"))
    with pytest.raises(admission.ReviewAdmissionError, match="UTF-8"):
        admission.read_json(path)


def test_two_adjudications_for_one_observation_do_not_silently_combine(fixture, tmp_path):
    first = tmp_path / "synthetic-first.json"; second = tmp_path / "synthetic-second.json"
    write(first, fixture[2])
    changed = deepcopy(fixture[2]); changed["adjudication"]["reason"] = "Distinct synthetic second adjudication."
    write(second, changed)
    report = admission.intake_report(Path(fixture[1]["path"]), submission_paths=[first, second],
                                     context_paths=[Path(fixture[3][0][1]["path"])])
    assert report["counts"]["structurally_valid"] == 1
    assert report["counts"]["rejected_structurally"] == 1
    assert "multiple submissions" in report["submissions"][1]["result"]["reason"]
