"""PCPR-054: produce Datasets SBOMs and provenance."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.sbom_and_provenance import (
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    OutcomeProbe,
    PCPR_054_GOAL_ID,
    PCPR_054_TASK_ID,
    PROVENANCE_KIND,
    SBOM_KIND,
    SCHEMA,
    SEALED_PATH,
    SEALED_PYTHON,
    SbomProvenanceError,
    current_head_static_probes,
    pcpr_054_receipt_promotion,
    qualify_current_head_sbom_and_provenance,
    qualify_sbom_and_provenance,
    render_build_provenance,
    render_declared_sbom,
    verify_sbom_and_provenance_files,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_054_requirements() -> None:
    assert PCPR_054_TASK_ID == "PCPR-054"
    assert PCPR_054_GOAL_ID == "PCPR-G600"
    assert INTERFACE == "DatasetsSbomAndProvenance@1"
    assert SCHEMA == "ipfs_datasets_py/assurance/sbom-and-provenance@1"
    assert SBOM_KIND == "declared_release_profile"
    assert PROVENANCE_KIND == "declared_build_binding"
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith("test_pcpr_054_sbom_and_provenance.py")
    assert SEALED_PATH == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
    assert SEALED_PYTHON == "/usr/bin/python3.12"
    document = render_declared_sbom()
    assert document["direct_package_count"] == 0
    assert document["direct_packages"] == []
    assert document["files_analyzed"] is False
    assert document["hashes_invented"] is False
    assert document["live"] is False
    assert document["release_claim"] is False
    assert document["closed_release_outcome"] is None
    assert document["requirements_authority"] == "setup.py:install_requires"
    provenance = render_build_provenance(sbom=document)
    assert provenance["slsa"]["status"] == "unavailable"
    assert provenance["source"]["mutable_main_reference"] is False


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_sbom_and_provenance()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.sibling_source_required is False
    assert verdict.hashes_invented is False
    assert verdict.files_analyzed is False
    assert verdict.live_scanner_qualified is False
    assert verdict.live_scanner_evidence_kind == "unavailable"
    assert verdict.slsa_attestation_live is False
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.blockers == ()
    section = pcpr_054_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_declared_sbom_constraints() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["sbom_files_match_generator"].present is True
    assert probes["core_release_profile_is_empty"].present is True
    assert probes["hashes_not_invented"].present is True
    assert probes["files_not_analyzed"].present is True
    assert probes["pyproject_sbom_and_provenance_table"].present is True
    assert probes["development_requirements_are_not_sbom"].present is True
    assert probes["manifest_advertises_sbom_and_provenance"].present is True
    assert probes["mutable_main_reference"].present is False
    assert probes["live_scanner"].evidence_kind == "unavailable"
    for probe in probes.values():
        assert probe.live is False
        assert probe.simulated_represented_as_live is False


def test_manifest_advertises_sbom_and_provenance() -> None:
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions["DatasetsSbomAndProvenance@1"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots[
        "datasets_sbom_and_provenance"
    ].endswith("sbom-and-provenance@1")
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions["sbom_and_provenance"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_repository_layout() is False


def test_committed_files_match_generator() -> None:
    verified = verify_sbom_and_provenance_files()
    assert verified["ok"] is True
    pyproject = (_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'interface = "DatasetsSbomAndProvenance@1"' in pyproject


def test_simulated_live_probe_is_rejected() -> None:
    with pytest.raises(SbomProvenanceError, match="simulated"):
        qualify_sbom_and_provenance(
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
            sbom_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            provenance_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            lock_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
