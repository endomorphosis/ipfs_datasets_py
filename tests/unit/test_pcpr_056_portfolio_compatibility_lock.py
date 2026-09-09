"""PCPR-056: Datasets binding to the portfolio compatibility lock."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.portfolio_compatibility_lock import (
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    LOCK_KIND,
    OutcomeProbe,
    PCPR_056_GOAL_ID,
    PCPR_056_TASK_ID,
    PINNED_LOCK_CID,
    SCHEMA,
    SEALED_PATH,
    SEALED_PYTHON,
    DatasetsPortfolioCompatibilityLockError,
    current_head_static_probes,
    pcpr_056_receipt_promotion,
    qualify_current_head_portfolio_compatibility_lock,
    qualify_portfolio_compatibility_lock,
    refuse_lock_remint,
    render_declared_binding,
    verify_portfolio_compatibility_lock_files,
)
from ipfs_datasets_py.logic.platform.manifest import DEFAULT_LOGIC_PLATFORM_MANIFEST


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_056_requirements() -> None:
    assert PCPR_056_TASK_ID == "PCPR-056"
    assert PCPR_056_GOAL_ID == "PCPR-G600"
    assert INTERFACE == "DatasetsPortfolioCompatibilityLockBinding@1"
    assert SCHEMA == (
        "ipfs_datasets_py/assurance/portfolio-compatibility-lock-binding@1"
    )
    assert LOCK_KIND == "declared_portfolio_compatibility_lock_binding"
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith(
        "test_pcpr_056_portfolio_compatibility_lock.py"
    )
    assert SEALED_PATH == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
    assert SEALED_PYTHON == "/usr/bin/python3.12"
    binding = render_declared_binding()
    assert binding["lock"] is True
    assert binding["frozen"] is False
    assert binding["live"] is False
    assert binding["release_claim"] is False
    assert binding["closed_release_outcome"] is None
    assert binding["signing"]["signed"] is False
    assert binding["source"]["mutable_main_reference"] is False
    assert binding["lock_cid"] == PINNED_LOCK_CID
    assert refuse_lock_remint(PINNED_LOCK_CID) == PINNED_LOCK_CID
    with pytest.raises(DatasetsPortfolioCompatibilityLockError, match="remints"):
        refuse_lock_remint(
            "baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_portfolio_compatibility_lock()
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
    assert verdict.live_signed_lock is False
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.blockers == ()
    section = pcpr_056_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_declared_lock_constraints() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["binding_files_match_generator"].present is True
    assert probes["core_release_profile_is_empty"].present is True
    assert probes["hashes_not_invented"].present is True
    assert probes["signatures_not_invented"].present is True
    assert probes["pyproject_portfolio_compatibility_lock_table"].present is True
    assert probes["manifest_advertises_portfolio_compatibility_lock"].present is True
    assert probes["lock_cid_matches_pin"].present is True
    assert probes["mutable_main_reference"].present is False
    assert probes["live_signed_lock"].evidence_kind == "unavailable"
    for probe in probes.values():
        assert probe.live is False
        assert probe.simulated_represented_as_live is False


def test_manifest_advertises_portfolio_compatibility_lock() -> None:
    versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
    assert versions["DatasetsPortfolioCompatibilityLockBinding@1"] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots[
        "datasets_portfolio_compatibility_lock"
    ].endswith("portfolio-compatibility-lock-binding@1")
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions[
        "portfolio_compatibility_lock"
    ] == "1"
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False
    assert DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_repository_layout() is False


def test_committed_files_match_generator() -> None:
    verified = verify_portfolio_compatibility_lock_files()
    assert verified["ok"] is True
    pyproject = (_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'interface = "DatasetsPortfolioCompatibilityLockBinding@1"' in pyproject


def test_simulated_live_probe_is_rejected() -> None:
    with pytest.raises(DatasetsPortfolioCompatibilityLockError, match="simulated"):
        qualify_portfolio_compatibility_lock(
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
            lock_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            binding_cid="baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
