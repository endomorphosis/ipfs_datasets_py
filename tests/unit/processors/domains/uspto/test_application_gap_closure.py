"""Unit tests for application gap-closure packages (no live network)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.application_gap_closure import (
    FOREIGN_GAP_ACCEPTANCE_SCHEMA,
    _normalize_person_name,
    accept_foreign_gap,
    build_family_pct_isr_pack,
    build_human_diligence_packs,
    close_application_gaps,
    confirm_human_diligence_items,
)


def test_normalize_person_name_strips_honorifics() -> None:
    assert _normalize_person_name("Mr. Tyrone Cunningham") == "tyrone cunningham"
    assert _normalize_person_name("Tyrone Cunningham") == "tyrone cunningham"
    assert _normalize_person_name("Dr. Jane A. Doe") == "jane a doe"


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _seed_export(state: Path, app: str = "18654466") -> Path:
    pkg = state / "exports" / app / "patent_center_ui" / "package"
    files = state / "exports" / app / "patent_center_ui" / "files"
    meta = state / "exports" / app / "patent_center_ui" / "metadata"
    files.mkdir(parents=True, exist_ok=True)
    meta.mkdir(parents=True, exist_ok=True)
    bag = {
        "applicationMetaData": {
            "inventionTitle": (
                "SYSTEMS AND METHODS FOR TAMPER EVIDENT SECURING OF A "
                "MONITORING DEVICE TO AN INDIVIDUAL"
            ),
            "filingDate": "2024-05-03T00:00:00",
            "applicationStatusDescriptionText": "Patented Case",
            "patentNumber": "12573280",
        },
        "parentContinuityBag": [
            {
                "parentApplicationNumberText": "63553043",
                "childApplicationNumberText": "63553043",
                "filingDate": "2024-02-13T00:00:00",
                "statusDescriptionText": "Provisional Application Expired",
            }
        ],
        "childContinuityBag": [
            {
                "parentApplicationNumberText": "18654466",
                "childApplicationNumberText": "PCT/US25/15067",
                "filingDate": "2025-02-07T00:00:00",
                "statusDescriptionText": (
                    "PCT - International Search Report Mailed to IB"
                ),
            }
        ],
        "inventorBag": [
            {"nameLineOneText": "Justin Cerutti", "firstName": "Justin", "lastName": "Cerutti"},
            {
                "nameLineOneText": "Tyrone Cunningham",
                "firstName": "Tyrone",
                "lastName": "Cunningham",
            },
            {
                "nameLineOneText": "Benjamin Barber",
                "firstName": "Benjamin",
                "lastName": "Barber",
            },
        ],
        "preGrantPublicationData": [
            {
                "publicationYear": 2025,
                "publicationSequenceNumber": "0259523",
                "publicationDate": "2025-08-14T00:00:00",
            }
        ],
        "status": "SUCCESS",
    }
    _write(pkg / "application_data.json", bag)
    _write(
        meta / "ifw_document_summary.json",
        {
            "count": 6,
            "documents": [
                {"documentCode": "OATH", "documentDescription": "Oath"},
                {"documentCode": "ADS", "documentDescription": "ADS"},
                {"documentCode": "IDS", "documentDescription": "IDS"},
                {"documentCode": "NTC.PUB", "documentDescription": "Notice of Publication"},
                {"documentCode": "CLM", "documentDescription": "Claims"},
                {"documentCode": "SPEC", "documentDescription": "Specification"},
                {"documentCode": "APP.FILE.REC", "documentDescription": "Filing Receipt"},
            ],
        },
    )
    for name in (
        "OATH_x.pdf",
        "ADS_x.pdf",
        "IDS_x.pdf",
        "NTC.PUB_x.pdf",
        "CLM_x.pdf",
        "SPEC_x.pdf",
        "APP.FILE.REC_x.pdf",
    ):
        (files / name).write_bytes(b"%PDF-1.4 test")
    return pkg


def _seed_prior_art_run(state: Path, app: str = "18654466") -> Path:
    run = state / "prior_art" / app / "run-testforeign01"
    run.mkdir(parents=True, exist_ok=True)
    package = {
        "schema": "patlaw-foreign-gap-package-v1",
        "package_id": "gap-package:foreign-patent-unsearched",
        "application_number": app,
        "run_id": run.name,
        "foreign_searched": False,
        "claims_foreign_searched": False,
        "reason": "unlicensed",
        "named_gaps": [
            {
                "gap_id": "gap:named:foreign-patent",
                "corpus": "foreign_patents",
                "reason": "unlicensed",
                "remains_visible": True,
            }
        ],
        "searched_corpora": ["us_patents", "npl"],
        "unsearched_corpora": ["foreign_patents"],
    }
    _write(run / "foreign_gap_package.json", package)
    _write(
        run / "coverage_declaration.json",
        {
            "subject_id": f"subject:app-{app}",
            "searched_corpora": ["us_patents", "npl"],
            "unsearched_corpora": ["foreign_patents"],
        },
    )
    return run


def test_accept_foreign_gap_keeps_unsearched(tmp_path: Path) -> None:
    run = _seed_prior_art_run(tmp_path)
    out = accept_foreign_gap(
        application_number="18654466",
        run_dir=run,
        acknowledger_name="operator:test",
    )
    assert out["ok"] is True
    acc = out["acceptance"]
    assert acc["schema"] == FOREIGN_GAP_ACCEPTANCE_SCHEMA
    assert acc["foreign_searched"] is False
    assert acc["claims_foreign_coverage"] is False
    assert acc["gap_remains_visible"] is True
    assert acc["acknowledger_name"] == "operator:test"
    assert (run / "foreign_gap_acceptance.json").is_file()


def test_accept_foreign_gap_requires_acknowledger(tmp_path: Path) -> None:
    run = _seed_prior_art_run(tmp_path)
    out = accept_foreign_gap(
        application_number="18654466",
        run_dir=run,
        acknowledger_name="  ",
    )
    assert out["ok"] is False
    assert out["code"] == "acknowledger_required"


def test_human_diligence_and_confirm(tmp_path: Path) -> None:
    _seed_export(tmp_path)
    family = build_family_pct_isr_pack(
        "18654466", state_root=tmp_path, fetch_odp=False
    )
    assert family["ok"] is True
    assert family["pct_children"]
    packs = build_human_diligence_packs(
        "18654466",
        state_root=tmp_path,
        family_pack=family,
        fetch_odp=False,
    )
    assert packs["ok"] is True
    assert "inventorship" in packs["packs"]
    assert "new_matter" in packs["packs"]
    assert packs["packs"]["nonpublication"]["evidence"]["published"] is True
    assert packs["packs"]["export_control"]["evidence"]["pct_family_member"] is True

    conf = confirm_human_diligence_items(
        packs,
        item_ids=["check:nonpublication", "check:export"],
        acknowledger_name="operator:test",
    )
    assert conf["ok"] is True
    assert len(conf["confirmations"]) == 2
    assert all(c["confirmed"] for c in conf["confirmations"])


def test_close_application_gaps_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_export(tmp_path)
    run = _seed_prior_art_run(tmp_path)

    # Stub reaudit to avoid heavy filing-pack deps.
    def _fake_audit(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "overall_status": "review_required",
            "severity_counts": {"pass": 1, "warning": 0},
            "paths": {"dir": str(tmp_path / "audit")},
            "operator_checklist_still_human": ["check:new-matter"],
            "operator_checklist_auto_confirmed": ["check:forms"],
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.domains.uspto.application_rules_audit.audit_application_rules",
        _fake_audit,
    )

    report = close_application_gaps(
        "18654466",
        state_root=tmp_path,
        run_id=run.name,
        acknowledger_name="operator:test",
        accept_foreign_gap_flag=True,
        confirm_human_items=[
            "check:nonpublication",
            "check:export",
            "check:inventorship",
            "check:new-matter",
        ],
        fetch_odp=False,
        reaudit=True,
        persist=True,
    )
    assert report["ok"] is True
    assert report["steps"]["foreign_gap_acceptance"]["ok"] is True
    acc = report["foreign_gap_acceptance"]
    assert acc["foreign_searched"] is False
    assert acc["gap_remains_visible"] is True
    paths = report["paths"]
    assert Path(paths["family_pct_isr"]).is_file()
    assert Path(paths["human_diligence"]).is_file()
    assert Path(paths["foreign_gap_acceptance"]).is_file()
    assert Path(paths["summary"]).is_file()
    confirmed = [
        i["item_id"]
        for i in (report.get("checklist") or {}).get("items") or []
        if i.get("confirmed")
    ]
    assert "check:nonpublication" in confirmed
    assert "check:export" in confirmed
    assert report["steps"]["reaudit"]["ok"] is True
