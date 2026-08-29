"""Rhode Island nested-catalog source-readiness closure receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    rhode_island_section,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "legal_corpora_reindex"
    / "rhode_island_source_readiness_v2.md"
)
EVIDENCE_ROOT = Path(
    "/home/barberb/.ipfs_datasets/state_laws/"
    "legal-corpora-reindex-20260829-ri-readiness-NycEJa"
)
FRONTIER_MANIFEST_SHA256 = (
    "23edd033d64e2bcfc95fd9703190e3e44e11f4515d652d3d6906ff599f5d1038"
)
COMPLETE_URL_ARRAY_SHA256 = (
    "4c2fa02dde61ed6ca3871b1ac2c9c615b5c8155bb8c324c07a8aa66cf3351985"
)
MISSING_URL_ARRAY_SHA256 = (
    "f9813a1a727d99d694ce7118d33dafa69544dacf378f8fde3192bfb2370d9729"
)
CATALOG_DIGEST = (
    "d63b33c61f1abf9650be1e9761a314a1ddda6d8d11dd55ac5e335ee66de09c3e"
)
ENCODED_LOCATOR = "%C2%A7_6A-9-102"
ENCODED_LABEL = "§ 6A-9-102. Definitions."


def _report_table() -> dict[str, str]:
    rows: dict[str, str] = {}
    for raw_line in REPORT_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 2 or cells[0] in {"Field", "---"}:
            continue
        rows[cells[0]] = cells[1].strip("`")
    return rows


def test_rhode_island_source_readiness_report_pins_exact_held_wave() -> None:
    report = REPORT_PATH.read_text(encoding="utf-8")
    table = _report_table()

    assert table["jurisdiction"] == "RI"
    assert table["source_seed_parser_inputs"] == "3018"
    assert table["nested_catalog_count"] == "29"
    assert table["nested_catalog_direct_successes"] == "29"
    assert table["nested_catalog_archive_fallbacks"] == "0"
    assert table["catalog_parser_inputs_after_closure"] == "3047"
    assert table["bounded_current_body_proofs"] == "1"
    assert table["retained_parser_inputs_now"] == "3048"
    assert table["complete_section_frontier_count"] == "34419"
    assert table["known_pre_nested_sections"] == "34184"
    assert table["newly_exposed_nested_sections"] == "235"
    assert table["complete_section_url_array_sha256"] == COMPLETE_URL_ARRAY_SHA256
    assert table["missing_body_count"] == "34418"
    assert table["missing_body_url_array_sha256"] == MISSING_URL_ARRAY_SHA256
    assert table["known_current_source_gap_count"] == "0"
    assert table["unobserved_missing_body_status_count"] == "34418"
    assert table["catalog_replay_network_requests"] == "0"
    assert table["large_body_acquisition_started"] == "false"
    assert table["expected_complete_parser_inputs"] == "37466"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["authoritative_frontier_manifest_sha256"] == (
        FRONTIER_MANIFEST_SHA256
    )

    assert 3047 + 34419 == 37466
    assert 3048 + 34418 == 37466
    assert "--retained-replay-only" in report
    assert "--no-incremental-state-publish" in report
    assert "--publish-to-hf" not in report
    assert "above 30 GiB" in report
    assert "No part of that large wave was launched" in report


def test_rhode_island_encoded_locator_binding_pins_final_parser_bytes() -> None:
    assert rhode_island_section._SOURCE_BOUND_ENCODED_SECTION_LOCATOR_CORRECTIONS[
        ("6A", "6A-9", ENCODED_LOCATOR, ENCODED_LABEL)
    ] == ("6A-9-102", "6A-9-102")
    assert (
        "6A",
        "6A-9",
        "6A-1",
        "6A-1",
        CATALOG_DIGEST,
        ENCODED_LOCATOR,
        ENCODED_LABEL,
    ) in rhode_island_section._SOURCE_BOUND_SUBPART_SECTION_CATALOG_CORRECTIONS

    scraper_path = (
        REPO_ROOT
        / "ipfs_datasets_py"
        / "processors"
        / "legal_scrapers"
        / "state_scrapers"
        / "rhode_island.py"
    )
    section_path = scraper_path.with_name("rhode_island_section.py")
    assert hashlib.sha256(scraper_path.read_bytes()).hexdigest() == (
        "b06b85d8e7dc12a880e6e5e4d5319151a515da228dbfee6be4bb8dddd231ec5a"
    )
    assert hashlib.sha256(section_path.read_bytes()).hexdigest() == (
        "7b828bdd09fd499626e8dc063f94f2fcd7551f38b868421fbd1dce5af93ee35a"
    )


def test_rhode_island_installed_frontier_manifest_replays_exact_difference() -> None:
    path = (
        EVIDENCE_ROOT
        / "RI"
        / "audits"
        / "source-derived-frontiers"
        / f"{FRONTIER_MANIFEST_SHA256}.json"
    )
    if not path.is_file():
        pytest.skip("exact retained Rhode Island source-readiness root is absent")
    payload = path.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == FRONTIER_MANIFEST_SHA256
    manifest = json.loads(payload)

    complete = manifest["complete_frontier_urls"]
    missing = manifest["missing_body_urls"]
    assert len(complete) == len(set(complete)) == 34419
    assert len(missing) == len(set(missing)) == 34418
    assert manifest["retained_body_proofs"][0]["logical_section"] == "6A-9-102"
    assert manifest["known_current_source_gaps"] == []
    assert manifest["unobserved_missing_body_status_count"] == 34418
    assert manifest["catalog_replay_network_requests"] == 0
    assert manifest["large_body_acquisition_started"] is False
    assert hashlib.sha256(
        json.dumps(
            complete,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest() == COMPLETE_URL_ARRAY_SHA256
    assert hashlib.sha256(
        json.dumps(
            missing,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest() == MISSING_URL_ARRAY_SHA256
