"""Tests for deterministic local Solidity CPT release staging."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.ir_core.identity import cid_v1
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.evaluation import (
    build_offline_fixture_evaluation,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.hf_release import (
    LOCAL_OBSERVATION_MODE,
    SolidityCPTReleaseAuthorityError,
    SolidityCPTReleaseError,
    SolidityCPTReleaseIntegrityError,
    SolidityCPTReleaseManifest,
    build_solidity_cpt_release,
    validate_solidity_cpt_release,
)


def _config_cid() -> str:
    return cid_v1(b"test-solidity-cpt-release-config")


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.iterdir())
        if path.is_file()
    }


def _candidate() -> dict:
    return {
        "bridge_id": cid_v1(b"bridge"),
        "candidate_id": "candidate:reviewed-reentrancy",
        "formalization_cid": cid_v1(b"formalization"),
        "obligation_ids": ["obl:solidity-cpt:reentrancy"],
        "review_ids": ["review:security:17"],
        "rule_ids": ["rule:solidity-cpt:reentrancy"],
        "semantic_prerequisites": [
            "inert_solidity_parse",
            "exact_call_graph",
        ],
        "source_cids": [cid_v1(b"source")],
    }


def test_release_binds_all_governed_cids_and_has_no_authority(
    tmp_path: Path,
) -> None:
    evaluation = build_offline_fixture_evaluation()
    root = tmp_path / "release"
    result = build_solidity_cpt_release(
        root,
        evaluation=evaluation,
        config_cid=_config_cid(),
        candidates=(_candidate(),),
    )
    manifest = result.manifest

    assert manifest.source_cid == evaluation.source_cid
    assert manifest.graph_cid == evaluation.graph_cid
    assert manifest.index_cid == evaluation.index_cid
    assert manifest.partition_cid == evaluation.partition_cid
    assert manifest.model_cid == evaluation.model_or_checkpoint_cid
    assert manifest.evaluation_cid == evaluation.evaluation_cid
    assert manifest.license_cid == evaluation.license_cid
    assert manifest.config_cid == _config_cid()
    assert manifest.promotion_gate_id == evaluation.promotion_gate().gate_id
    assert manifest.integration_mode == LOCAL_OBSERVATION_MODE
    assert manifest.publication_enabled is False
    assert manifest.upload_enabled is False
    assert manifest.proof_authority is False
    assert manifest.transaction_authority is False
    assert manifest.candidate_count == 1
    assert validate_solidity_cpt_release(root).manifest_cid == manifest.manifest_cid

    candidate_payload = json.loads((root / "candidates.json").read_bytes())
    assert candidate_payload["proof_authority"] is False
    assert candidate_payload["transaction_authority"] is False
    assert "text" not in candidate_payload["candidates"][0]
    assert (root / "DATA_CARD.md").is_file()
    assert (root / "MODEL_CARD.md").is_file()


def test_two_local_builds_are_byte_identical(tmp_path: Path) -> None:
    evaluation = build_offline_fixture_evaluation()
    first = tmp_path / "first"
    second = tmp_path / "second"

    a = build_solidity_cpt_release(
        first,
        evaluation=evaluation,
        config_cid=_config_cid(),
        candidates=(_candidate(),),
    )
    b = build_solidity_cpt_release(
        second,
        evaluation=evaluation,
        config_cid=_config_cid(),
        candidates=(_candidate(),),
    )

    assert a.manifest.manifest_cid == b.manifest.manifest_cid
    assert _tree(first) == _tree(second)


@pytest.mark.parametrize("body_key", ["text", "source", "raw_source", "bytecode"])
def test_release_rejects_source_bodies(body_key: str, tmp_path: Path) -> None:
    candidate = _candidate()
    candidate[body_key] = "contract Unsafe {}"

    with pytest.raises(
        (SolidityCPTReleaseError, SolidityCPTReleaseAuthorityError),
        match="unsupported|source body",
    ):
        build_solidity_cpt_release(
            tmp_path / "rejected",
            evaluation=build_offline_fixture_evaluation(),
            config_cid=_config_cid(),
            candidates=(candidate,),
        )


def test_release_rejects_tampered_evaluation(tmp_path: Path) -> None:
    tampered = build_offline_fixture_evaluation().to_dict()
    tampered["diagnostics"] = ["tampered"]

    with pytest.raises(SolidityCPTReleaseError, match="release gate"):
        build_solidity_cpt_release(
            tmp_path / "rejected",
            evaluation=tampered,
            config_cid=_config_cid(),
        )


def test_release_verification_detects_corrupt_artifact(tmp_path: Path) -> None:
    root = tmp_path / "release"
    build_solidity_cpt_release(
        root,
        evaluation=build_offline_fixture_evaluation(),
        config_cid=_config_cid(),
    )
    (root / "MODEL_CARD.md").write_text("tampered", encoding="utf-8")

    with pytest.raises(
        SolidityCPTReleaseIntegrityError, match="artifact mismatch"
    ):
        validate_solidity_cpt_release(root)


def test_manifest_rejects_upload_or_transaction_authority(tmp_path: Path) -> None:
    root = tmp_path / "release"
    manifest = build_solidity_cpt_release(
        root,
        evaluation=build_offline_fixture_evaluation(),
        config_cid=_config_cid(),
    ).manifest.to_dict()
    manifest.pop("manifest_cid")
    manifest["upload_enabled"] = True

    with pytest.raises(SolidityCPTReleaseAuthorityError):
        SolidityCPTReleaseManifest.from_dict(manifest)
