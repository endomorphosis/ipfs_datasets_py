"""Segmentation accounting remains independent of downstream abstention."""
import pytest

from scripts.ops.legal_ir import analyze_legal_construction_segmentation as audit


def test_artifact_reference_accepts_optional_bytes_but_verifies_any_commitment(tmp_path):
    path = tmp_path / "value.json"
    path.write_text('{"value": 3}')
    ref = audit.file_ref(path)
    assert audit.read_ref(ref) == {"value": 3}
    assert audit.read_ref({k: ref[k] for k in ("path", "sha256")}) == {"value": 3}
    with pytest.raises(ValueError, match="byte count"):
        audit.read_ref({**ref, "bytes": ref["bytes"] + 1})
    with pytest.raises(ValueError, match="hash differs"):
        audit.read_ref({**ref, "sha256": "0" * 64})


def fixture_case(*, supported=True):
    text = "Oak Office must retain records. Elm Office may inspect notices."
    end = text.index(".") + 1
    source = {"candidate_id": "case", "source_text": text, "source_sha256": audit.corpus.sha(text.encode())}
    clauses = [{"char_start": 0, "char_end": end, "rule": {"r": "first"}},
        {"char_start": end + 1, "char_end": len(text), "rule": {"r": "second"}}] if supported else []
    reference = {**source, "supported": supported, "construction": "fixture", "clauses": clauses}
    tokens = audit.boundary.tokenize(text)
    indices = [i for i, t in enumerate(tokens) if t["char_end"] in {end, len(text)}]
    prediction = {"candidate_id": "case", "source_sha256": source["source_sha256"],
        "boundary_token_indices": indices, "predicted_rule_count": 2,
        "raw_learned_scope_supported": True, "status": "segmented", "reason": None,
        "plan": {"source": source, "clauses": clauses}}
    return source, prediction, reference


def pipeline(reference, boundary_result, *, composed=False, wrong_rules=False):
    return {"candidate_id": reference["candidate_id"], "source_sha256": reference["source_sha256"],
        "status": "composed" if composed else "abstained", "segmentation_status": boundary_result["status"],
        "composition": {"source_plan": {"clauses": [{"char_start": a, "char_end": b} for a, b in boundary_result["delivered_intervals"]]},
            "source_rule_list": [{"r": "wrong"}] if wrong_rules else [c["rule"] for c in reference["clauses"]]} if composed else None,
        "reason": None if composed else "clause_decoder_abstained"}


def test_raw_exact_rejected_by_scope_still_has_raw_boundary_credit():
    source, prediction, reference = fixture_case()
    prediction.update(plan=None, status="abstained", raw_learned_scope_supported=False, reason="learned_scope_abstention")
    record = audit.boundary_record(source, prediction, reference)
    counts = audit.boundary_counts([record])
    assert counts["supported_raw_interval_exact"] == 1
    assert counts["supported_delivered_interval_exact"] == 0
    assert counts["supported_raw_exact_but_abstained"] == 1
    result = audit.pipeline_record(pipeline(reference, record), reference, record)
    assert result["attribution"] == "raw_intervals_exact_but_boundary_policy_abstained"


@pytest.mark.parametrize("kind", ["split", "merge", "shift"])
def test_extra_missing_and_equal_count_wrong_boundaries(kind):
    source, prediction, reference = fixture_case()
    ends = prediction["boundary_token_indices"]
    new = [1, *ends] if kind == "split" else ends[1:] if kind == "merge" else [1, ends[-1]]
    prediction.update(boundary_token_indices=new, predicted_rule_count=len(new), plan=None, status="abstained", reason="modal_policy")
    record = audit.boundary_record(source, prediction, reference)
    assert record["raw_error_type"] == {"split": "oversegmented_only", "merge": "undersegmented_only", "shift": "mixed_split_merge_or_shift"}[kind]
    assert record["raw_count_relation"] == {"split": "too_many", "merge": "too_few", "shift": "equal"}[kind]
    assert not record["raw_interval_exact"]


def test_exact_delivered_boundaries_are_retained_when_decoder_abstains():
    source, prediction, reference = fixture_case()
    record = audit.boundary_record(source, prediction, reference)
    outcome = audit.pipeline_record(pipeline(reference, record), reference, record)
    assert record["delivered_interval_exact"]
    assert outcome["attribution"] == "decoder_abstained_after_exact_boundaries"
    assert not outcome["occurrence_exact"] and not outcome["joint_exact"]


def test_correct_boundaries_with_wrong_canonical_rule_is_downstream_error():
    source, prediction, reference = fixture_case()
    record = audit.boundary_record(source, prediction, reference)
    outcome = audit.pipeline_record(pipeline(reference, record, composed=True, wrong_rules=True), reference, record)
    assert outcome["occurrence_exact"] and not outcome["canonical_exact"]
    assert outcome["attribution"] == "canonical_error_after_exact_boundaries"


def test_canonical_only_exact_does_not_count_joint_exact():
    source, prediction, reference = fixture_case()
    tokens = audit.boundary.tokenize(source["source_text"])
    prediction["boundary_token_indices"][0] -= 1
    cut = tokens[prediction["boundary_token_indices"][0]]["char_end"]
    prediction["plan"]["clauses"] = [{"char_start": 0, "char_end": cut}, {"char_start": cut, "char_end": len(source["source_text"])}]
    record = audit.boundary_record(source, prediction, reference)
    outcome = audit.pipeline_record(pipeline(reference, record, composed=True), reference, record)
    assert outcome["canonical_exact"] and outcome["canonical_only_exact"] and not outcome["joint_exact"]


def test_unsupported_scope_has_no_fabricated_boundary_accuracy():
    source, prediction, reference = fixture_case(supported=False)
    prediction.update(status="abstained", plan=None, reason="unsupported_scope")
    record = audit.boundary_record(source, prediction, reference)
    assert record["reference_intervals"] is None and record["extra_end_offsets"] is None
    outcome = audit.pipeline_record(pipeline(reference, record), reference, record)
    assert outcome["decision_exact"] and not outcome["canonical_exact"]
    assert audit.pipeline_counts([outcome])["unsupported"] == 1


def test_analysis_refuses_reference_access_before_qualification_gate(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(audit, "file_ref", lambda p: {"path": str(p), "sha256": "0" * 64})
    def read(reference):
        calls.append(reference["path"])
        return {"fresh_target_and_regression_references_opened_after_replay_and_build_freezes": False}
    monkeypatch.setattr(audit, "read_ref", read)
    with pytest.raises(ValueError, match="completed post-build"):
        audit.analyze(tmp_path)
    assert calls == [str(tmp_path / "qualification-01/summary.json")]
