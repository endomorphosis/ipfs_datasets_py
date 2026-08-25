"""Tests for additive LCR-083 Open US Law bucket publication."""

from __future__ import annotations

import pytest

import scripts.ops.legal_data.publish_lcr083_source_rights_to_hf_bucket as pub


def test_plan_binds_sealed_digests_under_namespaced_prefix() -> None:
    plan = pub.build_plan()
    assert plan["bucket_id"] == "justicedao/open-us-law-bucket"
    assert plan["authorizing_hub_dataset_upload"] is False
    assert plan["prefix"].startswith("legal-corpora-reindex/lcr-083/")
    assert len(plan["objects"]) == 2
    for item in plan["objects"]:
        assert item["remote_path"].startswith(plan["prefix"] + "/")
        assert not item["remote_path"].startswith("us_")
        assert item["remote_path"] != "LATEST.json"


def test_cli_refuses_protected_dataset_repo() -> None:
    assert (
        pub.main(["--bucket", "justicedao/ipfs_state_laws", "--check"]) == 1
    )


def test_cli_dry_check_exits_zero() -> None:
    assert pub.main(["--check"]) == 0
