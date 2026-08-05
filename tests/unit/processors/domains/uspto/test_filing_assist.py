"""Unit tests for safe filing assist (hard barriers; no sign/pay/submit)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.filing_assist import (
    FORBIDDEN_FILING_ASSIST_CAPABILITIES,
    ForbiddenFilingAssistError,
    assert_click_allowed,
    assert_filing_assist_capability,
    build_filing_checklist,
    classify_receipt_filename,
    compute_package_digest,
    is_hard_barrier_label,
    prepare_receipt_inbox,
    scan_receipt_folder,
    write_filing_checklist,
)


def test_hard_barrier_labels() -> None:
    assert is_hard_barrier_label("Sign Application")
    assert is_hard_barrier_label("Pay Fees")
    assert is_hard_barrier_label("Submit")
    assert is_hard_barrier_label("Certify under Rule 11.18")
    assert not is_hard_barrier_label("Workbench")
    assert not is_hard_barrier_label("Download acknowledgement receipt")
    # "design" must not trip "sign"
    assert not is_hard_barrier_label("Design patent workbench")


def test_assert_click_refuses_submit() -> None:
    with pytest.raises(ForbiddenFilingAssistError):
        assert_click_allowed("Final Submit")


def test_forbidden_capabilities() -> None:
    for cap in (
        "apply_signature",
        "pay_fee",
        "perform_final_submission",
        "store_payment_instrument",
    ):
        assert cap in FORBIDDEN_FILING_ASSIST_CAPABILITIES
        with pytest.raises(ForbiddenFilingAssistError):
            assert_filing_assist_capability(cap)


def test_build_checklist_and_digest(tmp_path: Path) -> None:
    pkg = tmp_path / "package"
    pkg.mkdir()
    (pkg / "spec.pdf").write_bytes(b"%PDF-1.4 fake")
    (pkg / "claims.pdf").write_bytes(b"%PDF-1.4 claims")
    digest = compute_package_digest(pkg)
    assert len(digest) == 64

    checklist = build_filing_checklist(
        application_number="18654466",
        package_dir=pkg,
        package_digest=digest,
        state_root=tmp_path / "state",
    )
    assert checklist.package_digest == digest
    hard = [s for s in checklist.steps if s.hard_barrier]
    assert len(hard) >= 3
    assert all(not s.automation_allowed for s in hard)
    barrier_ids = {s.step_id for s in hard}
    assert "human-sign-certify" in barrier_ids
    assert "human-pay" in barrier_ids
    assert "human-submit" in barrier_ids

    out = write_filing_checklist(checklist, tmp_path / "checklist.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == "patlaw-filing-checklist-v1"
    assert data["application_number"] == "18654466"


def test_digest_mismatch_warning(tmp_path: Path) -> None:
    pkg = tmp_path / "package"
    pkg.mkdir()
    (pkg / "a.pdf").write_bytes(b"abc")
    checklist = build_filing_checklist(
        application_number="18654466",
        package_dir=pkg,
        package_digest="0" * 64,
        state_root=tmp_path / "state",
    )
    assert any("does not match" in w for w in checklist.warnings)


def test_classify_receipts() -> None:
    assert classify_receipt_filename("EAR_acknowledgement.pdf") == "acknowledgement"
    assert classify_receipt_filename("payment_receipt.pdf") == "payment"
    assert classify_receipt_filename("converted_spec.pdf") == "other"


def test_prepare_and_scan_receipt_inbox(tmp_path: Path) -> None:
    folder = prepare_receipt_inbox(
        application_number="18654466", state_root=tmp_path
    )
    assert folder.is_dir()
    (folder / "Electronic_Acknowledgement_Receipt.pdf").write_bytes(b"%PDF")
    (folder / "payment_receipt.pdf").write_bytes(b"%PDF")
    status = scan_receipt_folder(folder)
    assert status["file_count"] == 2
    assert status["has_acknowledgement_hint"]
    assert status["has_payment_hint"]
