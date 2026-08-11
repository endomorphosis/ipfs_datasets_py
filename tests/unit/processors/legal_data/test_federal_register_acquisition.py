"""Unit tests for cutoff-bound Federal Register inventory acquisition (LCR-052).

Acceptance: Every partition/page is closed with stable response evidence; the
union is duplicate-free by official identity and has no gap, unexplained drift,
failed-final item, or secret.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_acquisition import (
    FIXTURE_RANGE_END,
    FIXTURE_RANGE_START,
    GOAL_ID,
    MODE_FIXTURE,
    POST_ENDPOINT_DELTA_DOCUMENTS_MIN,
    REPORT_SCHEMA,
    SCHEMA_VERSION,
    TASK_ID,
    AcquisitionConfig,
    AcquisitionMode,
    FederalRegisterAcquisitionError,
    FixtureApiTransport,
    InventoryDriftError,
    InventoryGapError,
    PartitionPlanError,
    SecretInReceiptError,
    acquire_federal_register_inventory,
    assert_inventory_closed,
    assert_no_secrets,
    build_compact_inventory_recipe,
    build_completion_receipt,
    build_default_fixture_recipe,
    build_documents_api_url,
    build_fixture_inventory_report,
    check_inventory_report,
    default_report_path,
    expand_inventory_payload,
    find_secret_surfaces,
    is_inventory_recipe,
    plan_delta_partitions,
    plan_full_history_partitions,
    plan_monthly_partitions,
    write_inventory_report,
)
from ipfs_datasets_py.processors.legal_data.federal_register_completeness import (
    CompletenessVerdict,
    evaluate_completion_receipt,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    DEFAULT_OBSERVATION_CUTOFF,
    DEFAULT_OBSERVATION_CUTOFF_DATE,
    FEDERAL_REGISTER_DOCUMENTS_API,
    LEGACY_BASELINE_END_INCLUSIVE,
    LEGACY_BASELINE_START_INCLUSIVE,
    LEGACY_DELTA_START_INCLUSIVE,
    PREVIOUS_PUBLIC_PIN,
    MutableCutoffError,
    build_legal_id,
    content_sha256,
)


# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "federal-register-acquisition-v1"
    assert REPORT_SCHEMA == (
        "ipfs_datasets_py/legal-corpora-reindex-federal-inventory@1"
    )
    assert TASK_ID == "LCR-052"
    assert GOAL_ID == "LCR-G110"
    assert FIXTURE_RANGE_START == LEGACY_DELTA_START_INCLUSIVE
    assert FIXTURE_RANGE_END == DEFAULT_OBSERVATION_CUTOFF_DATE
    assert POST_ENDPOINT_DELTA_DOCUMENTS_MIN == 11_784


# ---------------------------------------------------------------------------
# Partition planning
# ---------------------------------------------------------------------------


def test_monthly_partitions_cover_range_without_gaps_or_overlaps() -> None:
    specs = plan_monthly_partitions("2026-03-03", "2026-08-10")
    assert specs[0].start_date == "2026-03-03"
    assert specs[-1].end_date == "2026-08-10"
    assert specs[0].year_month == "2026-03"
    assert specs[-1].year_month == "2026-08"
    # Adjacent partitions abut.
    for idx in range(len(specs) - 1):
        left = specs[idx]
        right = specs[idx + 1]
        assert (left.end.toordinal() + 1) == right.start.toordinal()
    # No overlaps.
    for idx in range(len(specs) - 1):
        assert specs[idx + 1].start > specs[idx].end


def test_partition_plan_rejects_inverted_range() -> None:
    with pytest.raises(PartitionPlanError):
        plan_monthly_partitions("2026-08-10", "2026-03-03")


def test_delta_and_full_history_partition_plans() -> None:
    delta = plan_delta_partitions()
    assert delta[0].start_date == LEGACY_DELTA_START_INCLUSIVE
    assert delta[-1].end_date == DEFAULT_OBSERVATION_CUTOFF_DATE

    full = plan_full_history_partitions()
    assert full[0].start_date == LEGACY_BASELINE_START_INCLUSIVE
    assert full[-1].end_date == DEFAULT_OBSERVATION_CUTOFF_DATE
    assert len(full) > len(delta)


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------


def test_documents_api_url_is_official_and_bounded() -> None:
    url = build_documents_api_url(
        start_date="2026-03-03",
        end_date="2026-03-31",
        page=1,
        per_page=100,
    )
    assert url.startswith(FEDERAL_REGISTER_DOCUMENTS_API)
    assert "conditions%5Bpublication_date%5D%5Bgte%5D=2026-03-03" in url or (
        "conditions[publication_date][gte]=2026-03-03" in url
    )
    assert "per_page=100" in url
    assert "page=1" in url


# ---------------------------------------------------------------------------
# Fixture transport and acquisition
# ---------------------------------------------------------------------------


def test_default_fixture_recipe_is_compact_and_sealed() -> None:
    recipe = build_default_fixture_recipe()
    assert recipe["schema_version"] == SCHEMA_VERSION
    assert recipe["task_id"] == TASK_ID
    assert recipe["mode"] == MODE_FIXTURE
    assert recipe["observation_cutoff"] == DEFAULT_OBSERVATION_CUTOFF
    assert recipe["range_start"] == LEGACY_DELTA_START_INCLUSIVE
    assert recipe["range_end"] == DEFAULT_OBSERVATION_CUTOFF_DATE
    assert recipe["delta_start_inclusive"] == LEGACY_DELTA_START_INCLUSIVE
    assert recipe["legacy_baseline_end_inclusive"] == LEGACY_BASELINE_END_INCLUSIVE
    assert recipe["previous_public_pin"] == PREVIOUS_PUBLIC_PIN
    assert len(recipe["partitions"]) >= 5  # Mar..Aug 2026
    # Compact: few docs per partition.
    total_docs = sum(
        sum(len(page["documents"]) for page in part["pages"])
        for part in recipe["partitions"]
    )
    assert 10 <= total_docs <= 40


def test_fixture_transport_returns_stable_response_hashes() -> None:
    recipe = build_default_fixture_recipe()
    transport = FixtureApiTransport(recipe)
    part = recipe["partitions"][0]
    url = build_documents_api_url(
        start_date=part["start_date"],
        end_date=part["end_date"],
        page=1,
        per_page=int(recipe["per_page"]),
    )
    body1, payload1 = transport(url, {"User-Agent": "test"})
    body2, payload2 = transport(url, {"User-Agent": "test"})
    assert body1 == body2
    assert content_sha256(body1) == content_sha256(body2)
    assert payload1["results"]
    assert payload1["count"] == payload2["count"]


def test_fixture_acquisition_closes_every_partition_and_page() -> None:
    result = acquire_federal_register_inventory(
        config=AcquisitionConfig(
            mode=AcquisitionMode.FIXTURE,
            resume=False,
            checkpoint_dir=None,
        )
    )
    assert result.errors == []
    assert result.frontier_closed is True
    assert result.open_page_count == 0
    assert result.failed_final == 0
    assert result.mode is AcquisitionMode.FIXTURE
    assert len(result.partitions) >= 5
    for partition in result.partitions:
        assert partition.status.value == "closed"
        assert partition.failed_final == 0
        if partition.enumerated > 0:
            assert partition.pages
        for page in partition.pages:
            assert page.status.value in {"verified", "fetched"}
            assert page.response_hash
            assert len(page.response_hash) == 64


def test_identity_union_is_duplicate_free_by_legal_id() -> None:
    result = acquire_federal_register_inventory(
        config=AcquisitionConfig(mode=AcquisitionMode.FIXTURE, resume=False)
    )
    legal_ids = list(result.documents_by_legal_id.keys())
    assert legal_ids
    assert len(legal_ids) == len(set(legal_ids))
    pairs = {
        (d.document_number, d.publication_date)
        for d in result.documents_by_legal_id.values()
    }
    assert len(pairs) == len(legal_ids)
    for doc in result.documents_by_legal_id.values():
        assert doc.legal_id == build_legal_id(
            doc.document_number, doc.publication_date
        )


def test_no_coverage_gap_and_no_unexplained_drift() -> None:
    result = acquire_federal_register_inventory(
        config=AcquisitionConfig(mode=AcquisitionMode.FIXTURE, resume=False)
    )
    assert result.config.range_start == result.partitions[0].spec.start_date
    assert result.config.range_end == result.partitions[-1].spec.end_date
    assert result.official_total == (
        result.fetched + result.duplicate_count + result.failed_final
    )
    assert result.enumerated == (
        result.fetched + result.duplicate_count + result.failed_final
    )
    assert_inventory_closed(result)


def test_completeness_oracle_accepts_closed_inventory() -> None:
    result = acquire_federal_register_inventory(
        config=AcquisitionConfig(mode=AcquisitionMode.FIXTURE, resume=False)
    )
    receipt = build_completion_receipt(result)
    completeness = evaluate_completion_receipt(receipt)
    assert completeness.verdict is CompletenessVerdict.PASS
    assert completeness.passed is True
    assert completeness.failed_final == 0
    assert completeness.open_page_count == 0


def test_mutable_cutoff_is_rejected() -> None:
    with pytest.raises(MutableCutoffError):
        AcquisitionConfig(observation_cutoff="latest", mode=AcquisitionMode.FIXTURE)


def test_secrets_are_rejected_in_inventory_report() -> None:
    result = acquire_federal_register_inventory(
        config=AcquisitionConfig(mode=AcquisitionMode.FIXTURE, resume=False)
    )
    report = copy.deepcopy(result.inventory_report)
    assert_no_secrets(report)
    assert find_secret_surfaces(report) == []

    poisoned = copy.deepcopy(report)
    poisoned["api_key"] = "sk-thisisafakesecretvalue12"
    with pytest.raises(SecretInReceiptError):
        assert_no_secrets(poisoned)

    poisoned2 = copy.deepcopy(report)
    poisoned2["notes"] = "token=Bearer supersecrettokenvalue"
    with pytest.raises(SecretInReceiptError):
        assert_no_secrets(poisoned2)

    poisoned3 = copy.deepcopy(report)
    poisoned3["path"] = "/home/operator/.ssh/id_rsa"
    with pytest.raises(SecretInReceiptError):
        assert_no_secrets(poisoned3)


def test_check_inventory_report_accepts_fixture_report() -> None:
    report = build_fixture_inventory_report()
    result = check_inventory_report(report)
    assert result["ok"] is True
    assert result["frontier_closed"] is True
    assert result["acceptance"]["all_partitions_closed"] is True
    assert result["acceptance"]["all_pages_closed"] is True
    assert result["acceptance"]["duplicate_free_by_official_identity"] is True
    assert result["acceptance"]["no_coverage_gap"] is True
    assert result["acceptance"]["failed_final_zero"] is True
    assert result["acceptance"]["secrets_absent"] is True
    assert result["acceptance"]["unexplained_count_drift"] == 0
    assert result["acceptance"]["completeness_oracle_passed"] is True
    assert result["acceptance"]["mode"] == MODE_FIXTURE
    assert result["acceptance"]["previous_public_pin"] == PREVIOUS_PUBLIC_PIN
    assert (
        result["acceptance"]["range_start"] == LEGACY_DELTA_START_INCLUSIVE
    )
    assert result["acceptance"]["range_end"] == DEFAULT_OBSERVATION_CUTOFF_DATE


def test_check_rejects_open_page_and_failed_final() -> None:
    report = build_fixture_inventory_report()
    broken = copy.deepcopy(report)
    broken["partitions"][0]["pages"][0]["status"] = "open"
    broken["partitions"][0]["pages_closed"] = False
    broken["acceptance"]["all_pages_closed"] = False
    # Digest will also fail; either path is fine.
    with pytest.raises(FederalRegisterAcquisitionError):
        check_inventory_report(broken)

    broken2 = copy.deepcopy(report)
    broken2["acceptance"]["failed_final"] = 1
    broken2["acceptance"]["failed_final_zero"] = False
    with pytest.raises(FederalRegisterAcquisitionError):
        check_inventory_report(broken2)

    broken3 = copy.deepcopy(report)
    broken3["acceptance"]["unexplained_count_drift"] = 3
    with pytest.raises(InventoryDriftError):
        check_inventory_report(broken3)


def test_resume_from_checkpoint_is_deterministic(tmp_path: Path) -> None:
    ckpt = tmp_path / "checkpoints"
    first = acquire_federal_register_inventory(
        config=AcquisitionConfig(
            mode=AcquisitionMode.FIXTURE,
            resume=True,
            checkpoint_dir=ckpt,
        )
    )
    assert first.frontier_closed is True
    # Second run should resume closed partitions from checkpoints.
    second = acquire_federal_register_inventory(
        config=AcquisitionConfig(
            mode=AcquisitionMode.FIXTURE,
            resume=True,
            checkpoint_dir=ckpt,
        )
    )
    assert second.frontier_closed is True
    assert second.unique_document_count == first.unique_document_count
    assert second.official_total == first.official_total
    assert sorted(second.unique_document_numbers()) == sorted(
        first.unique_document_numbers()
    )
    # Checkpoint files exist per partition.
    ckpt_files = list(ckpt.glob("*.json"))
    assert len(ckpt_files) == len(first.partitions)


def test_duplicate_identity_is_tracked_not_double_counted() -> None:
    recipe = build_default_fixture_recipe()
    # Inject a duplicate of the first document into the second page of the
    # first partition (or append a second page with the same identity).
    part = recipe["partitions"][0]
    first_doc = copy.deepcopy(part["pages"][0]["documents"][0])
    if len(part["pages"]) == 1:
        part["pages"].append(
            {
                "page_number": 2,
                "documents": [first_doc],
                "api_total": part["pages"][0]["api_total"] + 1,
            }
        )
        part["pages"][0]["api_total"] = part["pages"][0]["api_total"] + 1
        for page in part["pages"]:
            page["api_total"] = part["pages"][0]["api_total"]
    else:
        part["pages"][1]["documents"].append(first_doc)
        new_total = part["pages"][0]["api_total"] + 1
        for page in part["pages"]:
            page["api_total"] = new_total

    result = acquire_federal_register_inventory(
        config=AcquisitionConfig(
            mode=AcquisitionMode.FIXTURE,
            resume=False,
            per_page=int(recipe["per_page"]),
            range_start=str(recipe["range_start"]),
            range_end=str(recipe["range_end"]),
        ),
        fixture_recipe=recipe,
    )
    assert result.duplicate_count >= 1
    # Unique identity set still has one entry for that legal_id.
    legal_id = build_legal_id(
        first_doc["document_number"], first_doc["publication_date"]
    )
    assert legal_id in result.documents_by_legal_id
    assert result.frontier_closed is True


def test_delta_section_records_legacy_endpoint() -> None:
    report = build_fixture_inventory_report()
    delta = report["delta"]
    assert delta["legacy_baseline_end_inclusive"] == LEGACY_BASELINE_END_INCLUSIVE
    assert delta["delta_start_inclusive"] == LEGACY_DELTA_START_INCLUSIVE
    assert delta["post_endpoint_documents_min"] == POST_ENDPOINT_DELTA_DOCUMENTS_MIN
    assert delta["covers_delta_window"] is True


def test_write_and_reload_inventory_report(tmp_path: Path) -> None:
    report = build_fixture_inventory_report()
    path = tmp_path / "federal_inventory.json"
    written = write_inventory_report(report, path)
    assert written == path
    loaded = json.loads(path.read_text(encoding="utf-8"))
    check_inventory_report(loaded)
    assert loaded["task_id"] == TASK_ID
    assert loaded["goal_id"] == GOAL_ID
    assert loaded["schema"] == REPORT_SCHEMA


def test_default_report_path_points_at_docs_reports() -> None:
    path = default_report_path()
    assert path.name == "federal_inventory.json"
    assert "legal_corpora_reindex" in path.parts


def test_open_partition_status_fails_assert_inventory_closed() -> None:
    result = acquire_federal_register_inventory(
        config=AcquisitionConfig(mode=AcquisitionMode.FIXTURE, resume=False)
    )
    # Mutate a closed partition to open.
    from ipfs_datasets_py.processors.legal_data.federal_register_completeness import (
        PartitionStatus,
    )

    result.partitions[0].status = PartitionStatus.IN_PROGRESS
    result.frontier_closed = False
    with pytest.raises(InventoryGapError):
        assert_inventory_closed(result)


def test_inventory_report_has_no_secrets_or_absolute_home_paths() -> None:
    report = build_fixture_inventory_report()
    blob = json.dumps(report, sort_keys=True)
    assert find_secret_surfaces(report) == []
    assert "/home/" not in blob
    assert "Bearer " not in blob


def test_compact_recipe_expands_and_passes_check() -> None:
    recipe = build_compact_inventory_recipe()
    assert is_inventory_recipe(recipe) is True
    assert recipe["report_kind"] == "fixture_recipe"
    assert recipe["task_id"] == TASK_ID
    assert recipe["range"]["partition_count"] == 6
    expanded = expand_inventory_payload(recipe)
    assert is_inventory_recipe(expanded) is False
    assert expanded["frontier_closed"] is True
    assert expanded["acceptance"]["all_partitions_closed"] is True
    result = check_inventory_report(recipe)
    assert result["ok"] is True
    assert result["frontier_closed"] is True


def test_on_disk_federal_inventory_recipe_passes_check() -> None:
    path = default_report_path()
    assert path.is_file(), f"missing committed inventory recipe: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert is_inventory_recipe(payload) is True
    result = check_inventory_report(payload)
    assert result["ok"] is True
    assert result["acceptance"]["failed_final_zero"] is True
    assert result["acceptance"]["no_coverage_gap"] is True
    assert result["acceptance"]["duplicate_free_by_official_identity"] is True
    assert result["acceptance"]["secrets_absent"] is True
