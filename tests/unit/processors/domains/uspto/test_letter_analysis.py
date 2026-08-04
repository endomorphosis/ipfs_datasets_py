"""Unit tests for letter OCR + office-action summary (no live USPTO)."""

from __future__ import annotations

from pathlib import Path

from ipfs_datasets_py.processors.domains.uspto.letter_analysis import (
    summarize_office_action,
    write_letter_analysis,
)


SAMPLE_OA = """
UNITED STATES PATENT AND TRADEMARK OFFICE
Office Action Summary
Application No. 16/000,001
Mailing Date: 05/03/2024

Claim Rejections - 35 U.S.C. § 103
Claims 1-10 are rejected under 35 U.S.C. 103 as being unpatentable over Smith in view of Jones.

Claim Objections
Claim 11 is objected to because of informalities.

Period for Reply
A shortened statutory period for reply to this action is set to expire 3 months from the mailing date of this communication.
"""


def test_summarize_office_action_extracts_rejections_and_period() -> None:
    summary = summarize_office_action(
        SAMPLE_OA,
        artifact_id="art:test-oa",
        mailing_date="2024-05-03",
        document_kind="CTNF",
        application_number="16000001",
    )
    assert summary["ok"] is True
    assert summary["action_kind"] in {
        "non_final_rejection",
        "unknown",
        "notice",
    } or "reject" in summary["action_kind"]
    assert summary["rejections"] or summary["claim_ranges"]
    assert summary["period_months_from_text"] == 3
    assert any("1-10" in c or "Claims 1" in c for c in (summary["claim_ranges"] or summary["rejections"]))


def test_write_letter_analysis(tmp_path: Path) -> None:
    summary = {
        "schema": "patlaw-letter-analysis-v1",
        "analysis": summarize_office_action(SAMPLE_OA, artifact_id="art:x"),
    }
    path = write_letter_analysis(summary, tmp_path / "letter_analysis.json")
    assert path.is_file()
    assert path.stat().st_size > 50
