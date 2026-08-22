"""Integration fail-closed tests for LCR-084 scrape acceptance."""

from __future__ import annotations

from pathlib import Path

import pytest

import scripts.ops.legal_data.audit_state_laws_full_scrape_acceptance as audit


def test_missing_acceptance_receipt_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit, "REPOSITORY_ROOT", tmp_path)
    with pytest.raises(audit.ScrapeAcceptanceError, match="required receipt is missing"):
        audit.inspect_full_scrape_acceptance(
            require_live_official=True,
            require_jurisdictions=51,
            require_production_candidate=True,
            repository_root=tmp_path,
        )
