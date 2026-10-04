"""Document coverage cannot turn contextual fragments into independent intent."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import document_roundtrip as sut
from ipfs_datasets_py.logic.intent_ir.formalize import roundtrip


def frame(**changes):
    return {"actor": "unspecified", "action": "delete", "object": "cache",
            "modality": "intended", **changes}


@pytest.mark.parametrize("source,prediction,accepted", [
    ("Delete cache.", frame(), True),
    ("Do not delete cache.", frame(), False),
    ("Do not delete cache.", frame(modality="prohibited"), True),
    ("The agent must delete the cache.", frame(actor="agent", modality="required"), True),
    ("The agent must delete the cache.", frame(actor="operator", modality="required"), False),
    ("Delete cache.", frame(action="read"), False),
    ("Delete cache.", frame(object="report"), False),
    ("Delete cache if tests pass.", frame(), False),
    ("Delete cache and report.", frame(), False),
    ("Delete Cache.", frame(), False),
    ("the agent may delete cache.", frame(actor="agent", modality="required"), False),
    ("please ask the agent to delete cache.", frame(actor="agent"), True),
    ("must not do: delete cache.", frame(modality="prohibited"), True),
])
def test_independent_source_agreement_preserves_slots_and_scope(source, prediction, accepted):
    report = sut.assess_frame_source_agreement(source, prediction)
    assert report["matched"] is accepted
    assert not report["source_semantics_verified"]
    assert not report["proof_authority"]


def _mock_prediction(monkeypatch, prediction):
    calls = []
    def infer(source, descriptor):
        calls.append(source)
        candidate = roundtrip.frame_to_intent_ir(prediction, instruction=source)
        return {"status": "semantic_candidate_advice", "learned": {
            "encoder": {"fake": True}, "decoder": {"fake": True}, "frame": dict(prediction)},
            "candidate_intent_ir": candidate.to_dict(), "projections": {},
            "extended_projections": {}, "report_sha256": "a" * 64}
    monkeypatch.setattr(sut.copy_roundtrip, "prepare_copy_intent_instruction", infer)
    return calls


def test_long_document_reuses_complete_source_clauses(monkeypatch):
    calls = _mock_prediction(monkeypatch, frame())
    source = "Delete cache.\n\n" * 50
    report = sut.prepare_intent_document(source, search_recovery=False)
    assert calls == ["Delete cache."] * 50
    assert len(report["candidates"]) == 50
    assert "".join(u["text"] for u in report["units"]) == source
    assert report["complete_document_formalization"] is False


@pytest.mark.parametrize("source", [
    "```text\nDelete cache.\n```\n",
    "| instruction |\n| -- |\n| Delete cache. |\n",
    "> Delete cache.\n",
    "## Must Not Do\n\nDelete cache.\n",
    "**Must not do**\n\n- Delete cache.\n",
    "## Anti-patterns\n\nDelete cache.\n",
    "## Examples\n\nDelete cache.\n",
    "If validation fails:\n\n- Delete cache.\n",
    "- If validation fails:\n  - Delete cache.\n",
    "Do not perform the following operations.\n\nDelete cache.\n",
])
def test_opaque_or_contextual_instructions_never_reach_model(source, monkeypatch):
    calls = _mock_prediction(monkeypatch, frame())
    report = sut.prepare_intent_document(source, search_recovery=False)
    assert calls == []
    assert report["candidates"] == []
    assert "".join(u["text"] for u in report["units"]) == source


def test_window_inside_fence_uses_whole_source_context(monkeypatch):
    calls = _mock_prediction(monkeypatch, frame())
    source = "```text\nDelete cache.\n```\n\nDelete cache."
    start = source.index("Delete")
    report = sut.prepare_intent_document(source, start_char=start, end_char=start + len("Delete cache."),
                                          search_recovery=False)
    assert calls == []
    assert report["units"][0]["block_kind"] == "fenced_code"
    assert report["units"][0]["status"] == "unsupported_partial_unit"


def test_window_crossing_sentence_boundary_does_not_decode_suffix(monkeypatch):
    calls = _mock_prediction(monkeypatch, frame())
    source = "Delete cache. Delete cache."
    report = sut.prepare_intent_document(source, start_char=7, search_recovery=False)
    assert calls == ["Delete cache."]
    assert len(report["candidates"]) == 1
    assert report["units"][0]["status"] == "unsupported_partial_unit"


def test_source_disagreement_does_not_pass_native_validity(monkeypatch):
    calls = _mock_prediction(monkeypatch, frame())
    report = sut.prepare_intent_document("Do not delete cache.", search_recovery=False)
    assert calls == ["Do not delete cache."]
    assert report["candidates"] == []
    assert report["units"][0]["status"] == "rejected_source_disagreement"


def test_actual_inverse_input_is_predicted_frame_with_no_expected_target(monkeypatch):
    from ipfs_datasets_py.logic.intent_ir.formalize import copy_search
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paired_search
    prediction = frame(modality="prohibited")
    calls = []
    descriptor = {"schema": "fake", "path": "/fake", "sha256": "c" * 64}
    monkeypatch.setattr(copy_search.copy_roundtrip, "load_intent_copy_checkpoint",
                        lambda _: {"backend_descriptor": descriptor})
    def beam(selected, source, direction, **kwargs):
        calls.append((source, direction))
        output = (roundtrip.frame_to_sequence(prediction) if direction == "encode"
                  else roundtrip.canonical_frame_text(prediction))
        return {"rows": [{"generated_text": output, "status": "generated", "ended": True,
                "tokens": output.split(), "input_coverage_complete": True, "uncovered_input_tokens": []}]}
    monkeypatch.setattr(autoencoder_paired_search, "infer_paired_copy_beam", beam)
    report = copy_search.prepare_copy_intent_search("Do not delete cache.", descriptor)
    assert report["status"] == "semantic_candidate_advice"
    assert calls == [("do not delete cache.", "encode"),
                     (roundtrip.frame_to_sequence(prediction), "decode")]
    assert report["learned"]["frame"] == prediction
    assert report["source_semantics_verified"] is False


def test_numeric_and_selector_tampering_requires_replay(monkeypatch):
    _mock_prediction(monkeypatch, frame())
    source = "Delete cache."
    report = sut.prepare_intent_document(source, search_recovery=False)
    assert sut.validate_intent_document_report(report, source_text=source) is report
    tampered = deepcopy(report)
    tampered["candidates"][0]["proof_authority"] = True
    tampered.pop("report_sha256")
    tampered["report_sha256"] = sut._sha(sut._wire(tampered))
    with pytest.raises(ValueError, match="differs"):
        sut.validate_intent_document_report(tampered, source_text=source)


def test_missing_checkpoint_keeps_full_unicode_source():
    source = "## 信息\n\nDelete cache."
    report = sut.prepare_intent_document(source)
    assert report["candidates"] == []
    assert report["counts"]["source_characters"] == len(source)
    assert report["selection"]["end_byte"] == len(source.encode())
    assert report["raw_instruction_preserved"] and report["continue_planning"]


@pytest.mark.parametrize("separator", ["\v", "\f", "\x1c", "\x85", "\u2028", "\u2029"])
def test_unicode_line_separators_cannot_escape_fence_scope(monkeypatch, separator):
    calls = _mock_prediction(monkeypatch, frame())
    source = "```text\ntext" + separator + "```" + separator + "Delete cache.\n```\n"
    report = sut.prepare_intent_document(source, search_recovery=False)
    assert calls == []
    assert report["candidates"] == []
    assert report["units"][0]["reason"] == "nonphysical_line_separator_requires_safe_parser"
    assert "".join(u["text"] for u in report["units"]) == source
