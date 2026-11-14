"""PAAR-142: content-free emit tests for review status surfaces.

Status / dashboard-like JSON must not leak secret-like strings or PDF
body-like blobs. Portfolio review status (PAAR-120) may not be implemented
yet; this suite covers:

* UnifiedApplicationReview compact_summary + full to_dict
* Conflict review report payloads
* Optional portfolio content-free seal when available

Hermetic offline only. Canaries are synthetic placeholders (not live secrets).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.application_review_orchestrator import (
    run_unified_application_review,
)
from ipfs_datasets_py.processors.domains.uspto.conflict_review_report import (
    build_conflict_review_report,
    report_to_payload,
)

FIXTURES = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "uspto"
    / "paar_review"
)

# Split fragments so source does not embed contiguous secret-assignment forms.
_SECRET_CANARY = "example-paar-secret-7f3a-pcf"
_PDF_CANARY = "CONFIDENTIAL-PDF-BODY-CANARY-PAAR142"
_PDF_BLOB = "%" + "PDF-1.4\n1 0 obj\n<<" + _PDF_CANARY + ">>\nstream\n" + ("X" * 64)

_FORBIDDEN_MARKERS = (
    "api" + "_key=",
    "x-" + "api-key:",
    "-----" + "begin ",
    "%" + "pdf-",
    "pass" + "word=",
    "authorization: " + "bearer",
    "secret_document_body",
    "set-cookie:",
)

_CANARIES = (
    _SECRET_CANARY,
    _PDF_CANARY,
    "bearer " + _SECRET_CANARY,
)


def _assert_content_free(payload: Any, *, surface: str) -> None:
    blob = json.dumps(payload, sort_keys=True, default=str)
    lowered = blob.lower()
    for marker in _FORBIDDEN_MARKERS:
        assert marker not in lowered, f"{surface} leaked marker {marker!r}"
    for canary in _CANARIES:
        assert str(canary) not in blob, f"{surface} leaked canary {canary!r}"
    # PDF header must never appear
    assert "%" + "PDF" not in blob
    assert "%" + "pdf" not in lowered
    # Common secret key names should not appear as emitted keys with values
    if isinstance(payload, dict):
        for key in payload:
            kl = str(key).lower().replace("-", "_")
            assert kl not in {
                "api_key",
                "password",
                "document_body",
                "pdf_body",
                "extracted_text",
                "raw_body",
            }, f"{surface} exposed secret key {key!r}"


def test_orchestrator_compact_summary_content_free(tmp_path: Path) -> None:
    """Compact summary is operator-safe (no claim/hit bodies, no secrets)."""
    if not (FIXTURES / "clean_package").is_dir():
        pytest.skip("paar_review fixtures missing")

    report = run_unified_application_review(
        fixture_dir=FIXTURES / "clean_package",
        state_root=tmp_path,
        persist=False,
        include_diligence=False,
        include_search=False,
        generated_at_utc="2026-08-06T00:00:00Z",
        metadata={
            # Poisoned metadata keys should not leak if redacted at emit; raw
            # metadata may pass through — inject into fields we control.
            "operator_note": "status-only",
        },
    )
    summary = report.compact_summary()
    assert summary.get("auto_file_blocked") is True
    assert summary.get("schema")
    assert "disclaimer" in summary
    _assert_content_free(summary, surface="compact_summary")

    full = report.to_dict()
    _assert_content_free(full, surface="unified_application_review")
    # Compact must not carry large claim text
    blob = json.dumps(summary)
    assert "temperature signal from a probe" not in blob
    assert "cooling valve" not in blob


def test_orchestrator_rejects_poison_in_serialized_status(tmp_path: Path) -> None:
    """Inject secret/PDF canaries into a status-like dict and ensure seal strips them."""
    try:
        from ipfs_datasets_py.processors.domains.uspto.portfolio_content_free import (
            assert_content_free,
            inject_poison_fields,
            redact_for_emit,
            seal_content_free,
        )
    except ImportError:
        pytest.skip("portfolio_content_free not available")

    if not (FIXTURES / "planted_conflict").is_dir():
        pytest.skip("paar_review fixtures missing")

    report = run_unified_application_review(
        fixture_dir=FIXTURES / "planted_conflict",
        state_root=tmp_path,
        persist=False,
        include_diligence=False,
        include_search=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    status_like = dict(report.compact_summary())
    # Secret-bearing keys + PDF bodies (keys dropped; canaries must not leak)
    status_like = inject_poison_fields(
        status_like,
        secret_canary=_SECRET_CANARY,
        pdf_canary=_PDF_CANARY,
    )
    status_like["nested"] = {
        "authorization": "Bearer " + _SECRET_CANARY,
        "ok_field": "matter_status",
        "document_body": _PDF_BLOB,
    }

    sealed = seal_content_free(
        status_like,
        surface="dashboard",
        canaries=_CANARIES,
    )
    assert sealed.get("content_free") is True
    _assert_content_free(sealed, surface="sealed_dashboard")
    assert "api_key" not in sealed
    assert "document_body" not in sealed
    assert "extracted_text" not in sealed
    assert "password" not in sealed
    # Nested secret keys dropped; safe field retained
    nested = sealed.get("nested") or {}
    assert "authorization" not in nested
    assert "document_body" not in nested
    assert nested.get("ok_field") == "matter_status"

    redacted = redact_for_emit(status_like)
    assert_content_free(
        redacted,
        surface="redacted_status",
        canaries=_CANARIES,
    )


def test_conflict_report_dump_content_free(tmp_path: Path) -> None:
    """Conflict review report payloads must not include PDF/secret bodies."""
    from ipfs_datasets_py.processors.domains.patent.conflict_risk_engine import (
        score_conflict_risk,
    )
    from ipfs_datasets_py.processors.domains.uspto.claim_limitation_model import (
        build_claim_limitation_graph,
    )

    claims = (
        "1. A method comprising receiving a temperature signal from a probe "
        "and activating a cooling valve when the temperature signal exceeds "
        "a safety threshold."
    )
    graph = build_claim_limitation_graph(claims_text=claims)
    hits = [
        {
            "hit_id": "hit:cf:1",
            "text": (
                "Controller receives a temperature signal from a probe and "
                "activates a cooling valve when the temperature signal exceeds "
                "a safety threshold."
            ),
            "publication_number": "US9999901B2",
        }
    ]
    engine = score_conflict_risk(
        claim_graph=graph,
        hits=hits,
        application_number="16990001",
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    crr = build_conflict_review_report(
        application_number="16990001",
        engine_report=engine,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    payload = report_to_payload(crr)
    # Inject poison paths that must not survive a content-free seal
    poisoned = dict(payload)
    poisoned["pdf_body"] = _PDF_BLOB
    poisoned["api_key"] = _SECRET_CANARY
    poisoned["cells_poison"] = [
        {
            "limitation_id": "L1",
            "document_body": _PDF_BLOB,
            "score": 0.9,
        }
    ]

    try:
        from ipfs_datasets_py.processors.domains.uspto.portfolio_content_free import (
            seal_content_free,
        )

        sealed = seal_content_free(poisoned, surface="conflict_report")
        _assert_content_free(sealed, surface="conflict_report_sealed")
        assert "pdf_body" not in sealed
        assert "api_key" not in sealed
        cells = sealed.get("cells_poison") or []
        if cells:
            assert "document_body" not in cells[0]
    except ImportError:
        # Without seal helper, raw engine payload should still avoid secret keys
        # we did not inject into the real report path
        clean = report_to_payload(crr)
        assert clean.get("auto_file_blocked") is True
        _assert_content_free(clean, surface="conflict_report_raw")

    # Real (unpoisoned) payload content-free for markers
    clean = report_to_payload(crr)
    assert clean.get("auto_file_blocked") is True
    blob = json.dumps(clean, default=str).lower()
    for marker in _FORBIDDEN_MARKERS:
        assert marker not in blob


def test_persisted_summary_json_content_free(tmp_path: Path) -> None:
    """Persisted summary.json under review run dir stays content-free."""
    if not (FIXTURES / "clean_package").is_dir():
        pytest.skip("paar_review fixtures missing")

    report = run_unified_application_review(
        fixture_dir=FIXTURES / "clean_package",
        state_root=tmp_path,
        persist=True,
        include_diligence=False,
        include_search=False,
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.persist_path
    summary_path = Path(report.persist_path) / "summary.json"
    assert summary_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    _assert_content_free(summary, surface="persisted_summary")
    assert summary.get("auto_file_blocked") is True


def test_no_secret_assignment_forms_in_status_builders() -> None:
    """Source modules for status surfaces avoid contiguous secret forms."""
    modules = [
        "ipfs_datasets_py.processors.domains.uspto.application_review_orchestrator",
        "ipfs_datasets_py.processors.domains.uspto.conflict_review_report",
    ]
    for mod_name in modules:
        mod = __import__(mod_name, fromlist=["*"])
        src_path = Path(mod.__file__)
        text = src_path.read_text(encoding="utf-8").lower()
        for marker in ("api" + "_key=", "pass" + "word=", "authorization: " + "bearer"):
            assert marker not in text, f"{mod_name} embeds {marker!r}"
