"""Authored curriculum labels, leakage fences, and replay boundaries."""
from collections import Counter, defaultdict
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import compositional_curriculum as sut
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import (
    canonical_frame_text, frame_to_sequence, intent_ir_to_frame)
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip_corpus import authored_intent_pairs
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paired_text import tokenize


def row(identity, *, split="train", group=None, actor="agent", action="inspect",
        obj="sample", modality="required", instruction=None):
    frame = {"actor": actor, "action": action, "object": obj, "modality": modality}
    return {"id": identity, "split": split, "group_id": group or identity,
            "instruction": instruction or canonical_frame_text(frame), "frame": frame,
            "canonical_text": canonical_frame_text(frame),
            "provenance": {"kind": "skillcenter_rich_weak_span", "source_id": identity}}


@pytest.fixture(scope="module")
def curriculum():
    return sut.authored_compositional_pairs()


@pytest.fixture
def base(monkeypatch):
    from ipfs_datasets_py.logic.intent_ir.formalize import rich_span_training
    report = {"samples": authored_intent_pairs() + [
        row("public-" + split, split=split, obj="publicartifact" + split)
        for split in ("train", "validation", "test")],
        "report_sha256": "a" * 64, "omitted": [], "quarantined": []}
    def build(descriptor, *, include_authored):
        assert descriptor == {"unit_fixture": True}
        assert include_authored is True
        return deepcopy(report)
    monkeypatch.setattr(rich_span_training, "build_rich_span_pairs", build)
    return report


def test_fixed_counts_and_deterministic_generation(curriculum):
    assert len(curriculum) == 1960
    assert Counter(r["split"] for r in curriculum) == {"train": 1600, "validation": 180, "test": 180}
    assert curriculum == sut.authored_compositional_pairs()
    assert len({r["id"] for r in curriculum}) == 1960


def test_generated_lexical_banks_are_disjoint_and_familiar_actions_explicit():
    banks = sut.lexical_banks()
    assert banks["train"]["actions"][:4] == ["read", "update", "validate", "write"]
    assert len(banks["train"]["actions"]) == 8
    symbols = {split: set(bank["actors"] + bank["actions"] + [t for o in bank["objects"] for t in o.split()])
               for split, bank in banks.items()}
    assert not symbols["train"] & symbols["validation"]
    assert not symbols["train"] & symbols["test"]
    assert not symbols["validation"] & symbols["test"]
    legacy_tokens = {t for r in authored_intent_pairs() for t in tokenize(r["instruction"])}
    assert not symbols["validation"] & legacy_tokens
    assert not symbols["test"] & legacy_tokens


def test_all_modalities_and_paraphrases_stay_in_one_source_family(curriculum):
    groups = defaultdict(list)
    for example in curriculum:
        groups[example["group_id"]].append(example)
    assert len(groups) == 196
    for group in groups.values():
        assert len(group) == 10
        assert len({r["split"] for r in group}) == 1
        assert {r["frame"]["modality"] for r in group} == set(sut._MODALITIES)
        assert Counter(r["provenance"]["template_variant"] for r in group) == {0: 5, 1: 5}


def test_all_declared_native_frames_and_bounds_roundtrip(curriculum):
    for example in curriculum:
        assert intent_ir_to_frame(example["native_intent_ir"]) == example["frame"]
        assert example["canonical_text"] == canonical_frame_text(example["frame"])
        assert len(example["instruction"].split()) <= 48
        assert len(tokenize(example["instruction"])) < 192
        assert len(tokenize(frame_to_sequence(example["frame"]))) < 96
        assert len(tokenize(example["canonical_text"])) < 96


def test_actor_absent_templates_never_invent_named_actor(curriculum):
    absent = [r for r in curriculum if r["provenance"]["template_family"] == "actor_absent_imperative"]
    assert Counter(r["split"] for r in absent) == {"train": 320, "validation": 60, "test": 60}
    for example in absent:
        assert example["frame"]["actor"] == example["provenance"]["actor_default"] == "unspecified"
        assert "unspecified" not in example["instruction"]


def test_object_phrase_is_never_stripped_or_augmented(curriculum):
    assert {len(r["frame"]["object"].split()) for r in curriculum if r["split"] == "train"} == {1, 2, 3, 4}
    for example in curriculum:
        assert example["instruction"].endswith(example["frame"]["object"] + ".")
        assert " the " + example["frame"]["object"] not in example["instruction"]
        assert example["provenance"]["object_phrase_preserved_exactly"] is True
        if example["provenance"]["actor_article_removed_by_template"]:
            assert example["instruction"].startswith("the " + example["frame"]["actor"] + " ")


def test_curriculum_labels_are_explicit_authored_not_public_or_diagnostic(curriculum):
    for example in curriculum:
        provenance = example["provenance"]
        assert provenance["kind"] == "authored_compositional_curriculum"
        assert provenance["label_rule"] == sut.POLICY
        assert provenance["human_reviewed"] is provenance["gold_source_semantics"] is False
        assert provenance["public_source_derived"] is provenance["diagnostic_example_derived"] is False
        assert provenance["source_sha256"] == sut._sha(example["instruction"].encode())


def test_base_controls_and_sources_preserved_byte_for_byte(base):
    result = sut.build_compositional_corpus({"unit_fixture": True})
    old = {r["id"]: r for r in base["samples"]}
    kept = {r["id"]: r for r in result["samples"]}
    assert all(kept[key] == value for key, value in old.items())
    assert result["counts"]["base_pairs"] == 723
    assert result["counts"]["pairs"] == 2683
    assert result["counts"]["curriculum_quarantined"] == 0
    assert result["base_rows_and_partitions_preserved"] is True
    assert result["counts"]["by_source"][sut.KIND] == {"train": 1600, "validation": 180, "test": 180}
    sut.validate_compositional_corpus(result)


@pytest.mark.parametrize("field", ["frame", "instruction", "split", "producer_sha256", "counts", "policy"])
def test_resigned_corpus_tampering_fails_replay(base, field):
    report = sut.build_compositional_corpus({"unit_fixture": True})
    if field == "frame": report["samples"][0]["frame"]["action"] = "alter"
    elif field == "instruction": report["samples"][0]["instruction"] += " altered"
    elif field == "split": report["samples"][0]["split"] = "test" if report["samples"][0]["split"] != "test" else "train"
    elif field == "producer_sha256": report[field] = {}
    elif field == "counts": report[field]["pairs"] += 1
    else: report[field] = "different-policy"
    report.pop("report_sha256")
    report["report_sha256"] = sut._sha(sut._wire(report))
    with pytest.raises(ValueError, match="differs from deterministic"):
        sut.validate_compositional_corpus(report)


def test_cross_partition_frame_collision_quarantines_whole_new_family():
    base = row("existing", obj="capsule")
    conflict = row("new-conflict", split="test", group="new-family", obj="capsule", instruction="please inspect capsule.")
    sibling = row("new-sibling", split="test", group="new-family", obj="capsule", modality="prohibited")
    kept, quarantined = sut._combine([base], [conflict, sibling])
    assert kept == [base]
    assert {r["id"] for r in quarantined} == {"new-conflict", "new-sibling"}
    assert any("semantic_frame:cross_partition" in r["collision_categories"] for r in quarantined)


def test_token_equivalent_conflicting_labels_quarantine_even_within_training():
    base = row("existing", actor="agent", instruction="must inspect capsule.")
    new = row("new", actor="operator", instruction="must inspect capsule .")
    kept, quarantined = sut._combine([base], [new])
    assert kept == [base]
    assert quarantined[0]["collision_categories"] == ["tokenized_input:conflicting_labels"]


def test_normalized_input_collision_across_partitions_quarantines_new_rows():
    base = row("existing", instruction="must inspect sample.")
    new = row("new", split="validation", instruction="MUST   inspect sample.")
    kept, quarantined = sut._combine([base], [new])
    assert kept == [base]
    assert "normalized_input:cross_partition" in quarantined[0]["collision_categories"]


def test_cross_partition_family_identity_is_not_reassigned():
    base = row("existing", group="family", obj="first")
    new = row("new", group="family", obj="second", split="test")
    kept, quarantined = sut._combine([base], [new])
    assert kept == [base]
    assert "source_family:cross_partition" in quarantined[0]["collision_categories"]


def test_inconsistent_existing_corpus_is_rejected_instead_of_rewritten():
    base = [row("one", obj="same"), row("two", obj="same", split="test")]
    with pytest.raises(ValueError, match="existing paired corpus"):
        sut._combine(base, [])


@pytest.mark.parametrize("mode", ["duplicate_id", "over_limit"])
def test_closed_identity_and_size_bounds(mode):
    rows = [row("same"), row("same")] if mode == "duplicate_id" else [row(str(i)) for i in range(4097)]
    with pytest.raises(ValueError, match="row bounds or repeats"):
        sut._combine([], rows)
