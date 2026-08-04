"""Unit tests for deficiency / revision response workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.revision_response import (
    TriggerKind,
    attach_to_revision,
    candidate_reply_window,
    classify_trigger,
    close_revision_case,
    list_revision_cases,
    mark_revision_submitted,
    open_revision_case,
    prepare_revision_package,
    scan_response_triggers,
)


def test_classify_office_action_codes() -> None:
    kind, months, reasons = classify_trigger(document_code="CTNF")
    assert kind is TriggerKind.OFFICE_ACTION_NONFINAL
    assert months == 3
    assert any("CTNF" in r for r in reasons)

    kind, months, _ = classify_trigger(document_code="CTFR")
    assert kind is TriggerKind.OFFICE_ACTION_FINAL

    kind, months, _ = classify_trigger(
        document_description="Notice to File Missing Parts of Nonprovisional Application"
    )
    assert kind is TriggerKind.MISSING_PARTS
    assert months == 2

    kind, _, reasons = classify_trigger(
        document_code="SPEC", direction="INCOMING"
    )
    assert kind is None


def test_candidate_reply_window_weekend() -> None:
    # 2024-05-03 + 3 months = 2024-08-03 (Saturday) → Monday 2024-08-05
    win = candidate_reply_window(official_date="2024-05-03", period_months=3)
    assert win["status"] == "review_only_candidate"
    assert win["candidate_date"] == "2024-08-03"
    assert win["candidate_date_adjusted"] == "2024-08-05"
    assert "disclaimer" in win


def test_open_prepare_attach_submit(tmp_path: Path) -> None:
    # Seed fake IFW inventory
    meta = (
        tmp_path
        / "exports"
        / "18654466"
        / "patent_center_ui"
        / "metadata"
    )
    meta.mkdir(parents=True)
    (meta / "ifw_document_summary.json").write_text(
        json.dumps(
            {
                "count": 1,
                "documents": [
                    {
                        "documentIdentifier": "OA123",
                        "documentCode": "CTNF",
                        "documentDescription": "Non-Final Rejection",
                        "officialDate": "2024-05-03T00:00:00.000Z",
                        "directionCategory": "OUTGOING",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    scan = scan_response_triggers("18654466", state_root=tmp_path)
    assert scan["trigger_count"] == 1
    assert scan["triggers"][0]["kind"] == "office_action_nonfinal"

    case = open_revision_case(
        "18654466",
        state_root=tmp_path,
        document_identifier="OA123",
        document_code="CTNF",
        document_description="Non-Final Rejection",
        official_date="2024-05-03",
    )
    assert case.state == "open"
    assert Path(case.case_dir).is_dir()
    assert case.candidate_reply.get("candidate_date_adjusted")

    # Attach a revised claims PDF
    claims = tmp_path / "claims_amended.pdf"
    claims.write_bytes(b"%PDF-1.4 amended claims")
    case = attach_to_revision(
        case.revision_id,
        claims,
        role="amended_claims",
        state_root=tmp_path,
    )
    assert case.state == "prepared"
    assert len(case.attachments) == 1
    assert Path(case.attachments[0].path).is_file()

    prepared = prepare_revision_package(case.revision_id, state_root=tmp_path)
    assert prepared["ok"] is True
    assert Path(prepared["checklist_path"]).is_file()
    assert prepared["case"]["package_digest"]

    submitted = mark_revision_submitted(
        case.revision_id,
        authorizing_user="operator:test",
        state_root=tmp_path,
    )
    assert submitted.state == "submitted"
    assert submitted.submitted_by == "operator:test"

    with pytest.raises(Exception):
        mark_revision_submitted(
            case.revision_id,
            authorizing_user="automation",
            state_root=tmp_path,
        )

    closed = close_revision_case(case.revision_id, state_root=tmp_path)
    assert closed.state == "closed"

    open_only = list_revision_cases(state_root=tmp_path, application_number="18654466")
    assert open_only == []
    all_cases = list_revision_cases(
        state_root=tmp_path,
        application_number="18654466",
        include_closed=True,
    )
    assert len(all_cases) == 1


def test_manual_open_missing_parts(tmp_path: Path) -> None:
    case = open_revision_case(
        "16000001",
        state_root=tmp_path,
        document_description="Notice of Incomplete Application",
        official_date="2025-01-15",
    )
    assert case.trigger.kind == "incomplete_application"
    assert case.candidate_reply.get("period_months") == 2
