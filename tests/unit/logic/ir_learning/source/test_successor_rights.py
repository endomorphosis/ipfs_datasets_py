"""Regression coverage for the immutable PGIR-200 JusticeDAO rights no-go."""

from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
SUCCESSOR_ROOT = REPO_ROOT / "data" / "ir_learning" / "corpora" / "successor-v1"
INVENTORY_PATH = REPO_ROOT / "data" / "ir_learning" / "source_inventory" / "release_inventory.json"


def _load(name: str) -> dict:
    return json.loads((SUCCESSOR_ROOT / name).read_text(encoding="utf-8"))


def _expanded_row_ids(row: dict) -> list[str]:
    bounds = row["record_id_range"]
    return [row["record_id_format"] % index for index in range(bounds["first"], bounds["last"] + 1)]


def test_successor_rights_is_a_permanent_zero_decision() -> None:
    rights = _load("rights_manifest.json")
    assert rights["admission_decision"] == "permanent_zero_for_jdao_pinset_1"
    assert rights["training_admitted_rows"] == 0
    assert rights["admitted_source_record_ids"] == []
    assert rights["training_eligible"] is False
    assert rights["permanent_no_go"]["reason_code"] == (
        "missing_exact_source_and_transformation_rights_authority"
    )
    assert "new exact release revision" in rights["permanent_no_go"]["supersession_rule"]


def test_every_inventory_release_has_a_fresh_exact_revision_citation() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    source_releases = _load("source_releases.json")
    expected = {item["id"]: item["revision"] for item in inventory["repositories"]}
    actual = {item["id"]: item for item in source_releases["releases"]}
    expected_dispositions = {
        item["id"]: (
            "permanently_quarantined_for_this_pinset"
            if item["disposition"] == "quarantine"
            else "permanently_rejected_for_this_pinset"
        )
        for item in inventory["repositories"]
    }

    assert set(actual) == set(expected)
    assert source_releases["fresh_reviewed_at"] == "2026-08-25T00:00:00Z"
    assert source_releases["training_admitted_rows"] == 0
    for release_id, revision in expected.items():
        entry = actual[release_id]
        citation = entry["citation"]
        assert entry["revision"] == revision == citation["observed_revision"]
        assert citation["id"].endswith(f"@{revision}")
        assert citation["url"].endswith(f"/revision/{revision}")
        assert re.fullmatch(r"[0-9a-f]{64}", citation["response_sha256"])
        assert entry["training_admitted_rows"] == 0
        assert entry["disposition"] == expected_dispositions[release_id]
        assert entry["reason_code"]


def test_every_quarantined_source_row_has_a_cited_range_disposition() -> None:
    quarantine = _load("quarantine_manifest.json")
    source_releases = _load("source_releases.json")
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    citations = {entry["citation"]["id"] for entry in source_releases["releases"]}
    rows = [record_id for row in quarantine["row_dispositions"] for record_id in _expanded_row_ids(row)]

    assert quarantine["all_quarantined_rows_have_a_citation"] is True
    assert set(quarantine["quarantined_release_ids"]) == {
        item["id"] for item in inventory["repositories"] if item["disposition"] == "quarantine"
    }
    assert set(quarantine["rejected_release_ids"]) == {
        item["id"] for item in inventory["repositories"] if item["disposition"] == "reject"
    }
    assert len(rows) == 7173
    assert len(set(rows)) == 7173
    assert rows[0] == "src:patent:0000"
    assert "src:patent:2173" in rows
    assert "src:dutch-law:0000" in rows
    assert rows[-1] == "src:dutch-law:4998"
    for row in quarantine["row_dispositions"]:
        assert row["disposition"] == "permanently_quarantined_for_this_pinset"
        assert row["citation_id"] in citations
        assert row["row_count"] == len(_expanded_row_ids(row))
        assert row["residual_rights_gaps"]
    assert quarantine["training_eligible_rows"] == 0


def test_replay_receipt_binds_the_immutable_inventory_and_zero_count() -> None:
    receipt = _load("replay_receipt.json")
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

    assert receipt["result_identity"] == "RESULT(PGIR-200)"
    assert receipt["training_admitted_rows"] == 0
    assert receipt["input_inventory"]["pinset_id"] == "JDAO-PINSET-1"
    assert receipt["input_inventory"]["canonical_inventory_sha256"] == inventory["inventory_sha256"]
    assert receipt["citation_replay"]["expected_exact_revision_count"] == len(
        inventory["repositories"]
    )
    assert receipt["decision_replay"]["expected_source_rows"] == 7173
    assert receipt["decision_replay"]["expected_training_admitted_rows"] == 0
