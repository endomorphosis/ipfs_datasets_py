"""Mixed-corpus collision fences at the unchanged trainer's input boundary."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import rich_span_training as sut
from ipfs_datasets_py.logic.intent_ir.formalize import rich_span_targets
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import frame_to_intent_ir
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip_corpus import authored_intent_pairs
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip_training import _validated_samples
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip_training import build_training_pairs
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paired_text import _pairs


def _target(identifier, instruction, frame, split):
    return {"id": identifier, "span_id": identifier + "-span", "source_id": identifier + "-source",
            "split": split, "instruction": instruction,
            "target": {"kind": "action", "actions": [frame], "condition": None},
            "native_intent_ir": frame_to_intent_ir(frame, instruction=instruction).to_dict(),
            "qualification": {"training_supported": True},
            "provenance": {"source_id": identifier + "-source", "kind": "skillcenter_weak_rich_span",
                           "human_reviewed": False, "gold_source_semantics": False}}


def _opposite(split):
    return "test" if split != "test" else "train"


def _corpus(monkeypatch, targets):
    # Source-export replay has separate integration coverage. This fixture
    # isolates adding the real authored corpus to already admitted targets.
    monkeypatch.setattr(rich_span_targets, "load_skillcenter_rich_span_targets", lambda _: {"targets": targets})
    return sut.build_rich_span_pairs({"fixture": "already_admitted_targets"}, include_authored=True)


@pytest.mark.parametrize("instruction", [
    "The agent must read the report.",
    "The AGENT must read the report.",
    "The agent must  read the report.",
    "  The agent must read\n the report.  ",
])
def test_case_and_whitespace_collisions_with_different_opaque_frames_are_quarantined(monkeypatch, instruction):
    authored = next(row for row in authored_intent_pairs()
                    if row["instruction"] == "the agent must read the report.")
    # Public extraction retains the article in its opaque object. The authored
    # control uses object='report', so a frame-only fence cannot detect this.
    frame = {"actor": "agent", "action": "read", "object": "the report", "modality": "required"}
    public = _target("public", instruction, frame, _opposite(authored["split"]))
    before = deepcopy(public)
    corpus = _corpus(monkeypatch, [public])
    assert not any(row["provenance"].get("target_id") == "public" for row in corpus["samples"])
    assert authored["id"] not in {row["id"] for row in corpus["samples"]}
    assert len(corpus["quarantined"]) == 2
    assert {row["split"] for row in corpus["quarantined"]} == {public["split"], authored["split"]}
    assert public == before
    _validated_samples(corpus)
    sut.validate_rich_span_pairs(corpus)


def test_semantic_frame_collision_behavior_still_removes_all_paraphrases(monkeypatch):
    authored = next(row for row in authored_intent_pairs()
                    if row["instruction"] == "the agent must read the report.")
    frame = dict(authored["frame"])
    public = _target("public", "Agent shall read report.", frame, _opposite(authored["split"]))
    corpus = _corpus(monkeypatch, [public])
    assert not any(row["frame"] == frame for row in corpus["samples"])
    assert len(corpus["quarantined"]) == 4  # public + the three authored variants
    _validated_samples(corpus)


@pytest.mark.parametrize("instruction", [
    "The agent must read the report.", "The agent must read the report .",
])
@pytest.mark.parametrize("same_partition", [True, False])
def test_backend_identical_inputs_cannot_have_conflicting_labels_in_any_partition(monkeypatch, instruction, same_partition):
    authored = next(row for row in authored_intent_pairs()
                    if row["instruction"] == "the agent must read the report.")
    frame = {"actor": "agent", "action": "read", "object": "the report", "modality": "required"}
    split = authored["split"] if same_partition else _opposite(authored["split"])
    public = _target("public", instruction, frame, split)
    corpus = _corpus(monkeypatch, [public])
    assert not any(row["provenance"].get("target_id") == "public" for row in corpus["samples"])
    assert authored["id"] not in {row["id"] for row in corpus["samples"]}
    assert len(corpus["quarantined"]) == 2
    if same_partition or " ." in instruction:
        assert {row["reason"] for row in corpus["quarantined"]} == {"conflicting_model_input_targets"}
    for partition in ("train", "validation", "test"):
        _pairs(build_training_pairs([row for row in corpus["samples"] if row["split"] == partition]))
    _validated_samples(corpus)
    sut.validate_rich_span_pairs(corpus)


def test_collision_view_does_not_change_retained_text_native_labels_or_provenance(monkeypatch):
    frame = {"actor": "unspecified", "action": "review", "object": "scope", "modality": "intended"}
    public = _target("retained", "Review scope.", frame, "train")
    before = deepcopy(public)
    corpus = _corpus(monkeypatch, [public])
    row = next(row for row in corpus["samples"] if row["provenance"].get("target_id") == "retained")
    assert row["instruction"] == public["instruction"]
    assert row["frame"] == frame and row["native_intent_ir"] == public["native_intent_ir"]
    assert row["provenance"]["span_id"] == public["span_id"]
    assert row["provenance"]["source_id"] == public["source_id"]
    assert public == before
    assert corpus["quarantined"] == []
    _validated_samples(corpus)
    sut.validate_rich_span_pairs(corpus)
