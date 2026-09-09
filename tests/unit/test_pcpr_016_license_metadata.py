"""PCPR-016: resolve Datasets license metadata."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.license_metadata import (
    AUTHORITATIVE_SURFACES,
    CANONICAL_CLASSIFIER,
    CANONICAL_LICENSE_FILE,
    CANONICAL_SPDX,
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    DUAL_LICENSE_AUTHORITY,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    OutcomeProbe,
    PCPR_016_GOAL_ID,
    PCPR_016_TASK_ID,
    SCHEMA,
    LicenseMetadataError,
    current_head_static_probes,
    license_authority_manifest,
    parse_egg_info_license,
    parse_license_file,
    parse_pyproject_license,
    parse_readme_license,
    parse_setup_license,
    pcpr_016_receipt_promotion,
    qualify_current_head_license_metadata,
    qualify_license_metadata,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_016_requirements() -> None:
    assert PCPR_016_TASK_ID == "PCPR-016"
    assert PCPR_016_GOAL_ID == "PCPR-G230"
    assert INTERFACE == "DatasetsLicenseMetadata@1"
    assert SCHEMA == "ipfs_datasets_py/assurance/license-authority@1"
    assert CANONICAL_SPDX == "AGPL-3.0-only"
    assert CANONICAL_LICENSE_FILE == "LICENSE"
    assert DUAL_LICENSE_AUTHORITY == "none"
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith(
        "test_pcpr_016_license_metadata.py"
    )
    assert AUTHORITATIVE_SURFACES == (
        "LICENSE",
        "pyproject.toml",
        "setup.py",
        "README.md",
    )
    manifest = license_authority_manifest()
    assert manifest["dual_license_authority"] == "none"
    assert manifest["spdx"] == CANONICAL_SPDX
    assert manifest["import_side_effects"] == "none"


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_license_metadata()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.license_surfaces_agree is True
    assert verdict.dual_license_authority == "none"
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.live_solver_qualified is False
    assert verdict.live_solver_evidence_kind == "unavailable"
    assert verdict.built_wheel_evidence_kind == "unavailable"
    assert verdict.built_sdist_evidence_kind == "unavailable"
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.blockers == ()
    section = pcpr_016_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["license_surfaces_agree"] is True
    assert section["dual_license_authority"] == "none"
    assert section["live_solver_qualified"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_agpl_agreement() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["license_file_is_agpl_v3"].present is True
    assert probes["pyproject_license_agrees"].present is True
    assert probes["setup_classifier_agrees"].present is True
    assert probes["setup_license_field_agrees"].present is True
    assert probes["readme_license_agrees"].present is True
    assert probes["dual_license_not_granted"].present is True
    assert probes["dual_license_granted"].present is False
    assert probes["mit_not_authoritative"].present is True
    assert probes["mit_authoritative"].present is False
    assert probes["manifest_in_includes_license"].present is True
    assert probes["setuptools_ships_license_file"].present is True
    assert probes["distribution_metadata_declared_to_agree"].present is True
    assert probes["egg_info_license_agrees"].present is True
    assert probes["manifest_advertises_license_metadata"].present is True
    assert probes["simulated_results_represented_as_live"].present is False
    assert probes["built_wheel_represented_as_live"].present is False
    assert probes["built_sdist_represented_as_live"].present is False
    assert probes["live_solver_qualification"].evidence_kind == "unavailable"
    assert probes["live_solver_qualification"].present is None
    assert probes["built_wheel_metadata"].evidence_kind == "unavailable"
    assert probes["built_sdist_metadata"].evidence_kind == "unavailable"
    for probe in probes.values():
        assert probe.live is False
        assert probe.simulated_represented_as_live is False


def test_authoritative_files_agree_on_agpl() -> None:
    license_text = (_PACKAGE_ROOT / "LICENSE").read_text(encoding="utf-8")
    pyproject = (_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    setup = (_PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")
    readme = (_PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    manifest = (_PACKAGE_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    egg = (
        _PACKAGE_ROOT / "ipfs_datasets_py.egg-info" / "PKG-INFO"
    ).read_text(encoding="utf-8")
    parsed_license = parse_license_file(license_text)
    parsed_pyproject = parse_pyproject_license(pyproject)
    parsed_setup = parse_setup_license(setup)
    parsed_readme = parse_readme_license(readme)
    parsed_egg = parse_egg_info_license(egg)
    assert parsed_license["agrees"] is True
    assert parsed_license["spdx"] == CANONICAL_SPDX
    assert parsed_pyproject["agrees"] is True
    assert parsed_pyproject["spdx"] == CANONICAL_SPDX
    assert parsed_pyproject["license_files"] == ["LICENSE"]
    assert parsed_setup["agrees"] is True
    assert parsed_setup["license_field"] == CANONICAL_SPDX
    assert parsed_setup["classifiers"] == [CANONICAL_CLASSIFIER]
    assert parsed_readme["agrees"] is True
    assert parsed_readme["dual_license_negated"] is True
    assert parsed_egg["agrees"] is True
    assert parsed_egg["license_field"] == CANONICAL_SPDX
    assert "include LICENSE" in manifest
    assert 'license = {text = "AGPL-3.0-only"}' in pyproject
    assert "License :: OSI Approved :: MIT License" not in setup
    assert "license = {text = \"MIT\"}" not in pyproject
    assert "License: MIT\n" not in egg


def test_manifest_advertises_license_metadata() -> None:
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions["DatasetsLicenseMetadata@1"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots[
        "datasets_license_metadata"
    ].endswith("license-authority@1")
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions["license_metadata"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_repository_layout() is False


def test_mit_pyproject_does_not_agree() -> None:
    parsed = parse_pyproject_license(
        "[project]\nname = 'x'\nlicense = {text = 'MIT'}\n"
    )
    assert parsed["agrees"] is False
    assert parsed["spdx"] == "MIT"


def test_mit_setup_classifier_does_not_agree() -> None:
    parsed = parse_setup_license(
        'setup(\n    license="MIT",\n    classifiers=["License :: OSI Approved :: MIT License"],\n)\n'
    )
    assert parsed["agrees"] is False
    assert parsed["mit_classifier_present"] is True


def test_simulated_live_probe_is_rejected() -> None:
    with pytest.raises(LicenseMetadataError, match="simulated"):
        qualify_license_metadata(
            (
                OutcomeProbe(
                    probe_id="bogus",
                    present=False,
                    evidence_kind="simulated",
                    live=False,
                    simulated_represented_as_live=True,
                    reason="must fail",
                ),
            )
        )


def test_live_claim_without_measured_live_evidence_is_rejected() -> None:
    with pytest.raises(LicenseMetadataError, match="measured_live"):
        qualify_license_metadata(
            (
                OutcomeProbe(
                    probe_id="bogus",
                    present=True,
                    evidence_kind="measured",
                    live=True,
                    simulated_represented_as_live=False,
                    reason="must fail",
                ),
            )
        )


def test_receipt_promotion_rejects_closed_release() -> None:
    verdict = qualify_current_head_license_metadata()
    mutated = replace(
        verdict, closed_release_outcome="release_candidate_qualified"
    )
    with pytest.raises(LicenseMetadataError, match="closed release"):
        pcpr_016_receipt_promotion(mutated)


def test_source_files_exist_under_datasets_root() -> None:
    assert (
        _PACKAGE_ROOT / "ipfs_datasets_py" / "assurance" / "license_metadata.py"
    ).is_file()
    assert (_PACKAGE_ROOT / "LICENSE").is_file()
    assert (_PACKAGE_ROOT / "pyproject.toml").is_file()
    assert (_PACKAGE_ROOT / "setup.py").is_file()
    assert (_PACKAGE_ROOT / "README.md").is_file()
