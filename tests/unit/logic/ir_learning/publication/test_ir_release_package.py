"""Package validation for append-only IR release packaging (PGIR-090)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.huggingface.ir_release import (
    P1_CONFIGS,
    P4_EVIDENCE_KEYS,
    IRPublicationPolicy,
    IRReleaseError,
    QualifiedReleaseInputs,
    default_releases_data_dir,
    load_publication_policy,
    load_qualified_inputs,
    package_from_official_recipe,
    package_ir_release,
    validate_ir_release_package,
)


def _inputs(**overrides: object) -> dict:
    payload = {
        "checkpoint_authority": True,
        "checkpoint_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "checkpoint_id": "irck:test-admitted",
        "checkpoint_lifecycle_state": "promoted",
        "compiler_identity": "COMPILER-CURRENT-1",
        "corpus_root": "bafkreiha35x7mcukzzb5x67hmykwsny5wipf5jb4do5gpsl24mxvix55n4",
        "decompiler_identity": "DECOMPILER-CURRENT-1",
        "derived_count": 9,
        "evaluation_count": 1,
        "evaluation_root": "baguqeeraf3mevd4zrpkcy6hmsamfyszkq5zeisq2ipu6bvupquprtfqi53ta",
        "loss_configuration_identity": "IRLossConfiguration@1",
        "pairs_negative_count": 2,
        "pairs_positive_count": 2,
        "promotion_decision": "promote",
        "promotion_receipt": "RESULT(PGIR-072)",
        "proof_count": 1,
        "proof_root": "bafkreiedk7zooeftd4qnhysbuazs6ulntis3ixn5vye6q7bgtxgrdlrfna",
        "source_count": 3,
        "split_root": "sha256:047b263b85067aa3dad6760f623c2855fbaf776d565ec9c273c49425fcc14eb4",
        "training_admitted_rows": 0,
    }
    payload.update(overrides)
    return payload


def test_package_declares_every_p1_config_and_both_cards(tmp_path: Path) -> None:
    package = package_ir_release(output_dir=tmp_path, inputs=_inputs())
    receipt = validate_ir_release_package(tmp_path)

    assert package.configs == P1_CONFIGS
    assert receipt["configs"] == list(P1_CONFIGS)
    card = Path(package.dataset_card_path).read_text(encoding="utf-8")
    checkpoint_card = Path(package.checkpoint_card_path).read_text(encoding="utf-8")
    assert "configs:" in card
    assert "trust_remote_code: false" in card
    for name in P1_CONFIGS:
        assert f"config_name: {name}" in card
        assert (tmp_path / "configs" / name / "config.json").is_file()
        config = json.loads((tmp_path / "configs" / name / "config.json").read_text())
        assert config["auto_detected"] is False
        assert config["schema_homogeneous"] is True
    assert "Lifecycle:" in checkpoint_card
    assert "P4 evidence" in checkpoint_card
    assert "compiler:" in checkpoint_card


def test_p4_evidence_binds_required_identities(tmp_path: Path) -> None:
    package = package_ir_release(output_dir=tmp_path, inputs=_inputs())
    evidence = json.loads((tmp_path / "evidence" / "p4_evidence.json").read_text())
    for key in P4_EVIDENCE_KEYS:
        assert key in evidence
    assert evidence["compiler_identity"] == "COMPILER-CURRENT-1"
    assert evidence["promotion_decision"]["decision"] == "promote"
    assert evidence["evidence_cid"] == package.evidence_cid
    assert evidence["schema"] == "IRPublicationEvidence@1"


def test_source_and_derived_counts_are_distinct_fields(tmp_path: Path) -> None:
    package = package_ir_release(output_dir=tmp_path, inputs=_inputs())
    assert package.source_count == 3
    assert package.derived_count == 9
    assert package.source_count != package.derived_count
    counts = json.loads((tmp_path / "counts" / "source_derived.json").read_text())
    assert counts["source_count"] == 3
    assert counts["derived_count"] == 9
    card = Path(package.dataset_card_path).read_text(encoding="utf-8")
    assert "source rows: `3`" in card
    assert "derived rows: `9`" in card


def test_rebuild_is_byte_identical(tmp_path: Path) -> None:
    left = tmp_path / "a"
    right = tmp_path / "b"
    first = package_ir_release(output_dir=left, inputs=_inputs())
    second = package_ir_release(output_dir=right, inputs=_inputs())
    assert first.release_sha256 == second.release_sha256
    assert first.release_cid == second.release_cid
    assert first.evidence_cid == second.evidence_cid
    for relative in (
        "README.md",
        "CHECKPOINT_CARD.md",
        "evidence/p4_evidence.json",
        "release_manifest.json",
        "configs/source/train/source-00000-of-00001.json",
    ):
        assert (left / relative).read_bytes() == (right / relative).read_bytes()


def test_unpromoted_checkpoint_and_reject_decision_fail_closed() -> None:
    with pytest.raises(IRReleaseError, match="promoted"):
        QualifiedReleaseInputs.from_dict(_inputs(checkpoint_lifecycle_state="created"))
    with pytest.raises(IRReleaseError, match="authority"):
        QualifiedReleaseInputs.from_dict(_inputs(checkpoint_authority=False))
    with pytest.raises(IRReleaseError, match="promote"):
        QualifiedReleaseInputs.from_dict(_inputs(promotion_decision="reject"))


def test_policy_refuses_unrestricted_and_auto_detected_schema() -> None:
    with pytest.raises(IRReleaseError, match="auto-detected"):
        IRPublicationPolicy(allow_auto_detected_schema=True)
    with pytest.raises(IRReleaseError, match="unrestricted"):
        IRPublicationPolicy(require_human_approval=False)
    with pytest.raises(IRReleaseError, match="trust_remote_code"):
        IRPublicationPolicy(trust_remote_code=True)
    with pytest.raises(IRReleaseError, match="lease"):
        IRPublicationPolicy(require_publication_lease=False)


def test_secrets_in_inputs_fail_closed() -> None:
    with pytest.raises(Exception, match="credentials"):
        QualifiedReleaseInputs.from_dict(_inputs(metadata={"hf_token": "hf_not_a_real_token_value"}))


def test_official_recipe_rebuilds_and_validates(tmp_path: Path) -> None:
    releases = default_releases_data_dir()
    assert (releases / "publication_policy.json").is_file()
    assert (releases / "recipe.json").is_file()
    policy = load_publication_policy()
    inputs = load_qualified_inputs()
    assert policy.lease_fence == "hf-publication:Publicus/proof-grounded-ir-learning"
    assert inputs.source_count == 7173
    assert inputs.derived_count == 38690
    first = package_from_official_recipe(tmp_path / "a")
    second = package_from_official_recipe(tmp_path / "b")
    assert first.release_sha256 == second.release_sha256
    assert first.source_count == 7173
    assert first.derived_count == 38690
    validate_ir_release_package(tmp_path / "a")
    sealed = releases / "sealed"
    if sealed.is_dir():
        sealed_receipt = validate_ir_release_package(sealed)
        assert sealed_receipt["release_sha256"] == first.release_sha256
        assert sealed_receipt["source_count"] == 7173
        assert sealed_receipt["derived_count"] == 38690


def test_missing_p1_config_fails_validation(tmp_path: Path) -> None:
    package_ir_release(output_dir=tmp_path, inputs=_inputs())
    shard = tmp_path / "configs" / "proofs" / "train" / "proofs-00000-of-00001.json"
    shard.unlink()
    with pytest.raises(IRReleaseError, match="missing rows"):
        validate_ir_release_package(tmp_path)
