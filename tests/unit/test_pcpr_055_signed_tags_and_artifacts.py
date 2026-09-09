"""PCPR-055: produce Datasets signed tags and artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.signed_tags_and_artifacts import (
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    INTENDED_TAG_NAME,
    OutcomeProbe,
    PCPR_055_GOAL_ID,
    PCPR_055_TASK_ID,
    CHECKSUM_KIND,
    TAG_KIND,
    SCHEMA,
    SEALED_PATH,
    SEALED_PYTHON,
    SignedTagsError,
    current_head_static_probes,
    pcpr_055_receipt_promotion,
    qualify_current_head_signed_tags_and_artifacts,
    qualify_signed_tags_and_artifacts,
    render_declared_checksums,
    render_declared_tag_policy,
    verify_signed_tags_and_artifacts_files,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_055_requirements() -> None:
    assert PCPR_055_TASK_ID == "PCPR-055"
    assert PCPR_055_GOAL_ID == "PCPR-G600"
    assert INTERFACE == "DatasetsSignedTagsAndArtifacts@1"
    assert SCHEMA == "ipfs_datasets_py/assurance/signed-tags-and-artifacts@1"
    assert TAG_KIND == "declared_signed_tag_policy"
    assert CHECKSUM_KIND == "declared_artifact_checksum_manifest"
    assert INTENDED_TAG_NAME == "ipfs_datasets_py-v0.2.0"
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith(
        "test_pcpr_055_signed_tags_and_artifacts.py"
    )
    assert SEALED_PATH == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
    assert SEALED_PYTHON == "/usr/bin/python3.12"
    policy = render_declared_tag_policy()
    assert policy["signing"]["signed"] is False
    assert policy["live"] is False
    assert policy["release_claim"] is False
    assert policy["closed_release_outcome"] is None
    assert policy["source"]["mutable_main_reference"] is False
    checksums = render_declared_checksums(tag_policy=policy)
    assert checksums["hashes_invented"] is False
    assert checksums["artifacts"]["wheel"]["status"] == "unavailable"


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_signed_tags_and_artifacts()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.sibling_source_required is False
    assert verdict.hashes_invented is False
    assert verdict.signatures_invented is False
    assert verdict.live_signed_tag is False
    assert verdict.live_signed_tag_evidence_kind == "unavailable"
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.blockers == ()
    section = pcpr_055_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_declared_signed_tag_constraints() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["tag_policy_files_match_generator"].present is True
    assert probes["core_release_profile_is_empty"].present is True
    assert probes["hashes_not_invented"].present is True
    assert probes["signatures_not_invented"].present is True
    assert probes["pyproject_signed_tags_and_artifacts_table"].present is True
    assert probes["development_requirements_are_not_signed_release"].present is True
    assert probes["manifest_advertises_signed_tags_and_artifacts"].present is True
    assert probes["mutable_main_reference"].present is False
    assert probes["live_signed_tag"].evidence_kind == "unavailable"
    for probe in probes.values():
        assert probe.live is False
        assert probe.simulated_represented_as_live is False


def test_manifest_advertises_signed_tags_and_artifacts() -> None:
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions["DatasetsSignedTagsAndArtifacts@1"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots[
        "datasets_signed_tags_and_artifacts"
    ].endswith("signed-tags-and-artifacts@1")
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions[
        "signed_tags_and_artifacts"
    ] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_repository_layout() is False


def test_committed_files_match_generator() -> None:
    verified = verify_signed_tags_and_artifacts_files()
    assert verified["ok"] is True
    pyproject = (_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'interface = "DatasetsSignedTagsAndArtifacts@1"' in pyproject


def test_simulated_live_probe_is_rejected() -> None:
    with pytest.raises(SignedTagsError, match="simulated"):
        qualify_signed_tags_and_artifacts(
            (
                OutcomeProbe(
                    probe_id="bogus",
                    present=False,
                    evidence_kind="simulated",
                    live=False,
                    simulated_represented_as_live=True,
                    reason="must fail",
                ),
            ),
            tag_policy_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            checksums_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            sbom_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            provenance_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            lock_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
