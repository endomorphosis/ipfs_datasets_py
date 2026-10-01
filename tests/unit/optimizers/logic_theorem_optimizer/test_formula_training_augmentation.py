"""Training variants preserve source lineage, not independent semantic gold."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import formula_curriculum as curriculum
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import formula_training_augmentation as augmentation

ROOT = Path(__file__).resolve().parents[4]
FIXTURE = ROOT / "tests/fixtures/logic/actor_composition_must_training.json"
PARENT_SHA = "2e8c4e2726e97b5faf87f9d7aa52e98354ce2385fc8d4a44f231d8967c1c2095"
AUGMENTATION_SHA = "3ebc1121a80f1780c632fca404be4350feda1db2fd1ad20091d62cf691f2b88d"


@pytest.fixture
def parent():
    old = json.loads((ROOT / "tests/fixtures/logic/legacy_teacher_distillation.json").read_text())
    return curriculum.prepare_curriculum(curriculum.build_authored_panel(),
        excluded_source_texts=[row["text"] for row in old["rows"]],
        excluded_evaluation_actor_actions=[("officer", "disclose"), ("agency", "retain"),
                                          ("Company A", "disclose"), ("officer", "submit")],
        expected_manifest_sha256=PARENT_SHA)


def prepare(parent):
    return augmentation.prepare_must_augmentation(parent, expected_curriculum_manifest_sha256=PARENT_SHA)


def load(path, parent):
    return augmentation.load_must_augmentation(path, parent,
        expected_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        expected_curriculum_manifest_sha256=PARENT_SHA)


def test_fixed_fixture_exactly_matches_training_only_derivation(parent):
    result = prepare(parent)
    assert result.manifest_sha256 == AUGMENTATION_SHA
    assert load(FIXTURE, parent).manifest == result.manifest
    originals = {row["id"]: row for row in parent.rows("training")}
    all_source_rows = parent.manifest["rows"]
    assert len(result.rows()) == len(originals) == 24
    for row in result.rows():
        original = originals[row["parent_id"]]
        assert row["id"] == original["id"] + "-must-v1"
        assert row["text"] == original["text"].replace(" shall ", " must ")
        assert row["parent_source_sha256"] == hashlib.sha256(original["text"].encode()).hexdigest()
        assert all(row[key] == original[key] for key in ("actor", "norm_template_id", "split", "corpus"))
        assert row["split"] == "training"
        assert not any(row["text"].casefold() == item["text"].casefold() for item in all_source_rows)
    augmented_pairs = {(row["actor"], row["norm_template_id"]) for row in result.rows()}
    assert augmented_pairs == {(row["actor"], row["norm_template_id"]) for row in originals.values()}
    assert augmented_pairs.isdisjoint((row["actor"], row["norm_template_id"])
        for row in all_source_rows if row["split"] != "training")
    assert result.receipt["combined_training_count"] == 48
    assert not result.receipt["compiler_consistency_checked"]
    assert not result.receipt["compiler_labels_supplied"]
    assert not result.receipt["target_vocabulary_equality_checked"]
    assert all(result.manifest[key] is False and result.receipt[key] is False for key in augmentation.FALSE)


def test_public_rows_manifest_and_receipt_are_copy_safe(parent):
    prepared = prepare(parent)
    prepared.rows()[0]["text"] = "changed"
    prepared.manifest["rows"].clear()
    prepared.receipt["required_downstream_checks"].clear()
    assert prepared.manifest_sha256 == AUGMENTATION_SHA
    assert len(prepared.rows()) == 24
    assert prepared.receipt["required_downstream_checks"]


@pytest.mark.parametrize("pin", [None, "not-a-hash", "0" * 64, PARENT_SHA.upper()])
def test_parent_pin_must_be_exact(parent, pin):
    with pytest.raises(augmentation.AugmentationError, match="SHA-256"):
        augmentation.prepare_must_augmentation(parent, expected_curriculum_manifest_sha256=pin)


@pytest.mark.parametrize("mutation", ["split", "source", "order", "authority_type"])
def test_even_consistently_rehashed_parent_cannot_change_authoring_version(parent, mutation):
    panel = parent.manifest
    if mutation == "split":
        panel["rows"][0]["split"] = "tuning"
    elif mutation == "source":
        panel["rows"][0]["text"] += " Extra duty."
    elif mutation == "order":
        panel["rows"].reverse()
    else:
        panel["admitted"] = 0
    forged = curriculum.PreparedCurriculum(json.dumps(panel).encode(), b"{}")
    with pytest.raises(augmentation.AugmentationError, match="unsupported parent"):
        augmentation.prepare_must_augmentation(forged, expected_curriculum_manifest_sha256=forged.manifest_sha256)


@pytest.mark.parametrize("mutation", ["parent_id", "parent_hash", "source", "split", "formula", "qualification"])
def test_rehashed_fixture_cannot_smuggle_other_rows_labels_or_authority(parent, tmp_path, mutation):
    value = prepare(parent).manifest
    row = value["rows"][0]
    if mutation == "parent_id":
        row["parent_id"] = parent.rows("tuning")[0]["id"]
    elif mutation == "parent_hash":
        row["parent_source_sha256"] = "0" * 64
    elif mutation == "source":
        row["text"] = row["text"].replace("must", "may")
    elif mutation == "split":
        row["split"] = "tuning"
    elif mutation == "formula":
        row["formula_target"] = {"rules": []}
    else:
        value["qualified"] = True
    path = tmp_path / "augmentation.json"
    path.write_text(json.dumps(value))
    with pytest.raises(augmentation.AugmentationError, match="differs from the declared"):
        load(path, parent)


def test_fixture_byte_pin_size_and_duplicate_keys_are_checked(parent, tmp_path):
    path = tmp_path / "augmentation.json"
    path.write_bytes(FIXTURE.read_bytes())
    with pytest.raises(augmentation.AugmentationError, match="file SHA-256 differs"):
        augmentation.load_must_augmentation(path, parent, expected_file_sha256="0" * 64,
                                           expected_curriculum_manifest_sha256=PARENT_SHA)
    value = path.read_text().replace('"schema":', '"schema": "duplicate", "schema":', 1)
    path.write_text(value)
    with pytest.raises(augmentation.AugmentationError, match="valid JSON"):
        load(path, parent)
    path.write_bytes(b" " * (augmentation.MAX_BYTES + 1))
    with pytest.raises(augmentation.AugmentationError, match="bounded augmentation"):
        load(path, parent)


def test_all_training_paraphrases_preserve_screened_canonical_rules_and_temporal_sidecars(parent):
    """Actual compiler checks, with no teacher weights or model predictions."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_teacher import LegacyLinguisticTeacher
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_formula_codec import fit_codec
    originals = {row["id"]: row for row in parent.rows("training")}
    parent_targets, augmented_targets = [], []
    for row in prepare(parent).rows():
        results = [LegacyLinguisticTeacher._prepare(None,
            SimpleNamespace(sample_id=item["id"], text=item["text"]), "authored_fixture")
            for item in (originals[row["parent_id"]], row)]
        assert all(result["candidate"] for result in results), (row["id"], results)
        left, right = (result["compiler"] for result in results)
        assert left["rules"] == right["rules"]
        assert left["temporal_records"] == right["temporal_records"]
        # Match the latent head's target-only codec construction. Its sentinel
        # source vocabulary must not grow when input paraphrases are added.
        parent_targets.append({"id": row["parent_id"], "source_text": "latent",
                               "canonical_ir": {"rules": left["rules"]}})
        augmented_targets.append({"id": row["id"], "source_text": "latent",
                                  "canonical_ir": {"rules": right["rules"]}})
    assert fit_codec(parent_targets) == fit_codec(parent_targets + augmented_targets)
