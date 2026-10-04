"""Training pair semantics and immutable source-family split contracts."""
from collections import defaultdict
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import roundtrip_corpus as sut


def sample(text, *, id="source-one", split="train"):
    return {"instruction": text, "id": id, "split": split,
            "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "license_expression": "MIT", "source_record": {"source_url": "https://example.org/source"}}


def test_authored_contrast_families_preserve_all_modalities_and_paraphrases():
    pairs = sut.authored_intent_pairs()
    assert len(pairs) == 720
    families = defaultdict(list)
    for pair in pairs:
        families[pair["group_id"]].append(pair)
        assert pair["provenance"]["human_reviewed"] is False
        assert pair["provenance"]["gold_source_semantics"] is False
        assert pair["canonical_text"] == sut.canonical_intent_text(pair["frame"])
    assert len(families) == 48
    assert {p["split"] for p in pairs} == {"train", "validation", "test"}
    for group in families.values():
        assert len({p["split"] for p in group}) == 1
        assert len(group) == 15
        assert {p["frame"]["modality"] for p in group} == set(sut.MODALITIES)
    train = [p for p in pairs if p["split"] == "train"]
    for slot in ("actor", "action", "object", "modality"):
        assert {p["frame"][slot] for p in train} == {p["frame"][slot] for p in pairs}
    frames = defaultdict(set)
    for pair in pairs:
        frames[json.dumps(pair["frame"], sort_keys=True)].add(pair["split"])
    assert all(len(splits) == 1 for splits in frames.values())


def test_prohibition_and_positive_headings_preserved_in_input_and_label():
    text = "# Constraints\n## MUST NOT DO\n- Delete cache.\n## MUST DO\n- Validate report.\n"
    pairs, _ = sut.extract_skillcenter_pairs(sample(text, split="test"))
    assert [p["frame"]["modality"] for p in pairs] == ["prohibited", "required"]
    assert pairs[0]["instruction"] == "must not do: delete cache."
    assert pairs[0]["canonical_text"] == "unspecified must not delete cache."
    for pair in pairs:
        assert pair["split"] == "test"
        assert pair["provenance"]["source_fragments"] == [
            text[s["start_char"]:s["end_char"]] for s in pair["provenance"]["spans"]]


@pytest.mark.parametrize("text,modality", [
    ("Never delete cache.", "prohibited"),
    ("The agent must not delete cache.", "prohibited"),
    ("The agent must validate report.", "required"),
    ("The developer may update fixture.", "permitted"),
    ("The operator should read report.", "recommended"),
])
def test_explicit_actor_and_modality_are_not_misread_as_verbs(text, modality):
    pairs, _ = sut.extract_skillcenter_pairs(sample(text))
    assert len(pairs) == 1
    assert pairs[0]["frame"]["modality"] == modality
    assert pairs[0]["frame"]["action"] not in {"must", "not", "never", "may", "should"}


def test_fences_examples_conditions_quantifiers_and_compounds_remain_unsupported():
    text = ("```sh\nDelete cache.\n```\n# Examples\nDelete fixture.\n"
            "# Steps\nDelete cache and report.\nDelete all fixtures.\n"
            "If tests pass, update cache.\nThe agent read report.\nRead report.\n")
    pairs, omitted = sut.extract_skillcenter_pairs(sample(text))
    assert len(pairs) == 1
    assert pairs[0]["instruction"] == "read report."
    reasons = {r["reason"] for r in omitted}
    assert {"code_fence_content", "example_or_non_applicable_section",
            "compound_or_conditional_object", "descriptive_actor_clause"} <= reasons


def test_explicit_modal_conflict_does_not_select_convenient_target():
    pairs, omitted = sut.extract_skillcenter_pairs(sample("# MUST NOT DO\nThe agent may delete cache."))
    assert pairs == []
    assert omitted[-1]["reason"] == "conflicting_explicit_modalities"


def test_cross_split_instruction_and_frame_duplicates_quarantined():
    left = sut.extract_skillcenter_pairs(sample("Read report.", id="one", split="train"))[0][0]
    right = sut.extract_skillcenter_pairs(sample("Read report.", id="two", split="test"))[0][0]
    kept, rejected = sut._quarantine_collisions([left, right])
    assert kept == [] and len(rejected) == 2
    assert {r["split"] for r in rejected} == {"train", "test"}


def test_paired_report_replay_rejects_promoted_gold_and_forged_split():
    report = sut.build_intent_roundtrip_corpus(None)
    sut.validate_intent_roundtrip_corpus(report)
    report["samples"][0]["split"] = "test" if report["samples"][0]["split"] == "train" else "train"
    with pytest.raises(ValueError, match="reproducible source replay"):
        sut.validate_intent_roundtrip_corpus(report)
    report = sut.build_intent_roundtrip_corpus(None)
    report["human_reviewed_pair_count"] = 720
    with pytest.raises(ValueError, match="reproducible source replay"):
        sut.validate_intent_roundtrip_corpus(report)


def test_frame_requires_exact_typed_fields_and_wire_bounds():
    frame = {"actor": "agent", "action": "read", "object": "report", "modality": "required"}
    sut.validate_intent_frame(frame)
    for bad in ({**frame, "proof": True}, {**frame, "modality": "authorized"},
                {**frame, "object": "CaseSensitiveFile.py"}, {**frame, "action": "read and delete"},
                {**frame, "object": "a " * 13}):
        with pytest.raises(ValueError):
            sut.validate_intent_frame(bad)


def test_source_body_hash_checked_before_pairing():
    row = sample("Read report.")
    row["instruction"] = "Delete report."
    with pytest.raises(ValueError, match="digest"):
        sut.extract_skillcenter_pairs(row)


def test_full_pinned_fixture_preserves_native_source_splits(tmp_path):
    from tests.unit.logic.intent_ir.test_skillcenter_training import _fixture
    from ipfs_datasets_py.logic.intent_ir.formalize.skillcenter_training import (
        export_skillcenter_training_corpus, load_skillcenter_training_corpus)
    args = _fixture(tmp_path / "release", records=[
        ("first", "MIT", "allow", "# Instructions\nRead report.\n"),
        ("second", "Apache-2.0", "allow", "# Instructions\nUpdate cache.\n"),
        ("excluded", "NOASSERTION", "needs_review", "Delete fixture.\n")])
    descriptor = export_skillcenter_training_corpus(**args, output=tmp_path / "corpus")
    original = load_skillcenter_training_corpus(descriptor)
    report = sut.build_intent_roundtrip_corpus(descriptor, include_authored=False)
    sut.validate_intent_roundtrip_corpus(report)
    assert report["counts"]["pairs"] == 2
    assignments = {r["id"]: r["split"] for r in original["samples"]}
    assert all(p["split"] == assignments[p["provenance"]["source_id"]] for p in report["samples"])
    assert report["human_reviewed_pair_count"] == 0
    assert report["semantic_correctness_verified"] is False
    assert all(p["provenance"]["kind"] == "skillcenter_weak_clause" for p in report["samples"])
