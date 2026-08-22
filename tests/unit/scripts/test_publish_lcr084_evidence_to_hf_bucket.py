"""Tests for LCR-084 bucket evidence publication."""

from __future__ import annotations

import scripts.ops.legal_data.publish_lcr084_evidence_to_hf_bucket as pub


def test_plan_is_namespaced_and_non_authorizing() -> None:
    plan = pub.build_plan()
    assert plan["bucket_id"] == "justicedao/open-us-law-bucket"
    assert plan["prefix"].startswith("legal-corpora-reindex/lcr-084/")
    assert plan["bundle"]["authorizing_for_publication"] is False
    assert plan["bundle"]["satisfies_exact_51_official"] is False
    assert plan["bundle"]["scrape_acceptance"]["status"] == "blocked"


def test_cli_refuses_protected_dataset_repo() -> None:
    assert pub.main(["--bucket", "justicedao/ipfs_state_laws", "--check"]) == 1


def test_cli_dry_check_exits_zero() -> None:
    assert pub.main(["--check"]) == 0
