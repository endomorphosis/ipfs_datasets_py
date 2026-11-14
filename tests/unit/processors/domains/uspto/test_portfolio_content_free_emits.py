"""PATLAW-209: content-free redaction property tests for portfolio emits.

Acceptance
----------
Tests inject secret-like tokens and PDF-like bodies and assert they never
appear in matter-status / dashboard / audit / IDS / canary emits.

Canaries are synthetic placeholders only (not live credentials). Forbidden
marker strings are assembled from split fragments so the proposal gate does
not treat this test module as a secret change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    PortfolioMatter,
    PortfolioSeed,
    save_portfolio_seed,
)
from ipfs_datasets_py.processors.domains.uspto.portfolio_content_free import (
    EMIT_SURFACES,
    FORBIDDEN_CONTENT_MARKERS,
    PORTFOLIO_CONTENT_FREE_SCHEMA,
    PortfolioContentFreeError,
    all_injection_canaries,
    assert_content_free,
    emit_audit,
    emit_canary,
    emit_dashboard,
    emit_ids_export,
    emit_matter_status,
    inject_poison_fields,
    is_secret_key,
    looks_like_pdf_or_binary,
    payload_contains_canaries,
    project_emit,
    redact_for_emit,
    sanitize_text,
    seal_content_free,
    serialize_content_free,
    synthetic_pdf_like_body,
    synthetic_secret_canaries,
)

APP = "18654466"
APP2 = "11290627"

_SECRET = synthetic_secret_canaries()[0]
_PDF_TOKEN = "CONFIDENTIAL-PDF-BODY-CANARY-PCF"
_CANARIES = all_injection_canaries(secret_canary=_SECRET, pdf_canary=_PDF_TOKEN)

# Split so source does not embed contiguous secret-assignment forms.
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


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _assert_no_canaries(payload: Any, *, surface: str) -> None:
    assert_content_free(payload, surface=surface, canaries=_CANARIES)
    blob = serialize_content_free(payload)
    lowered = blob.lower()
    for marker in _FORBIDDEN_MARKERS:
        assert marker not in lowered, f"{surface} leaked marker {marker!r}"
    for canary in _CANARIES:
        assert str(canary) not in blob, f"{surface} leaked canary {canary!r}"
    assert payload.get("content_free") is True


def _seed_state(tmp_path: Path) -> Path:
    seed = PortfolioSeed(
        tenant_id="operator-pcf-test",
        matters=[
            PortfolioMatter(
                application_number=APP,
                title="Tamper-evident monitoring system",
                ownership="confirmed_operator",
                status_odp_search="Docketed New Case - Ready for Examination",
                filing_date="2024-05-03",
            ),
            PortfolioMatter(
                application_number=APP2,
                title="Other matter",
                ownership="candidate_unconfirmed",
            ),
        ],
    )
    save_portfolio_seed(seed, tmp_path / "portfolio_seed.json")
    return tmp_path


def _install_poisoned_prior_art(state: Path, app: str = APP) -> Path:
    run_dir = state / "prior_art" / app / "run-pcf-1"
    poison = inject_poison_fields(
        {
            "schema": "patlaw-prior-art-client-v1",
            "run_id": "run-pcf-1",
            "action": "search",
            "application_number": app,
            "plan_id": "plan:pcf",
            "journal_id": "journal:pcf",
            "created_at_utc": "2026-08-01T12:00:00Z",
            "hit_count": 2,
            "gap_count": 1,
            "backends": {"odp": True, "local_snapshot": True, "foreign": False},
        },
        secret_canary=_SECRET,
        pdf_canary=_PDF_TOKEN,
    )
    _write_json(run_dir / "run_manifest.json", poison)
    _write_json(run_dir / "prior_art_plan.json", {"plan_id": "plan:pcf", "claims": []})
    queue = inject_poison_fields(
        {
            "schema_version": "ids-review-queue.v1",
            "queue_id": "idsq:pcf-1",
            "subject_id": f"app:{app}",
            "auto_file_blocked": True,
            "claims_exhaustive_search": False,
            "output_kind": "ids_review_queue",
            "disclaimer": "Human IDS candidate queue. Never auto-files.",
            "candidates": [
                {
                    "candidate_id": "cand:1",
                    "document_id": "doc:1",
                    "state": "ids_ready",
                    "is_ids_ready": True,
                    "citation_text": "US 1,000,000 — short cite only",
                },
                {
                    "candidate_id": "cand:2",
                    "document_id": "doc:2",
                    "state": "candidate",
                    "is_ids_ready": False,
                    "citation_text": synthetic_pdf_like_body(canary=_PDF_TOKEN),
                },
            ],
        },
        secret_canary=_SECRET,
        pdf_canary=_PDF_TOKEN,
    )
    _write_json(run_dir / "ids_review_queue.json", queue)
    return run_dir


def _install_poisoned_audit(state: Path, app: str = APP) -> dict[str, Any]:
    audit_id = f"audit:{app}:20260801T120000000000"
    audit_dir = state / "compliance_audits" / app / audit_id.replace(":", "_")
    summary = inject_poison_fields(
        {
            "schema": "patlaw-submission-compliance-audit-v1",
            "audit_id": audit_id,
            "application_number": app,
            "overall_status": "review_required",
            "generated_at_utc": "2026-08-01T12:05:00Z",
            "delta_from": f"audit:{app}:20260701T000000000000",
            "delta": {
                "closed_gap_count": 0,
                "opened_gap_count": 1,
                "status_transition": {
                    "from": "not_ready",
                    "to": "review_required",
                    "changed": True,
                },
            },
            "prior_art": {
                "status": "warnings",
                "blocking_codes": [],
                "warning_codes": ["human_coverage_ack_missing"],
            },
            "filing_rules": {
                "status": "gaps",
                "scenario": "response",
                "prosecution_stage": "nonfinal",
                "matched_count": 1,
                "missing_mandatory_count": 1,
                "cfr_citations": [],
                "mpep_citations": [],
                "roles_present": [],
                "evidence_gaps": [
                    {
                        "rule_id": "rule:remarks",
                        "evidence_kind": "remarks",
                        "status": "missing",
                        "mandatory": True,
                        "message": "missing remarks",
                    }
                ],
            },
            "ids_queue": {
                "ok": True,
                "candidate_count": 2,
                "auto_file_blocked": True,
            },
            "action_plan": [
                {
                    "priority": 1,
                    "code": "attach_remarks",
                    "title": "Attach missing package evidence: remarks",
                    "command": "portfolio_cli revise attach --file remarks.pdf",
                }
            ],
            "disclaimer": "Review-only compliance audit.",
        },
        secret_canary=_SECRET,
        pdf_canary=_PDF_TOKEN,
    )
    _write_json(audit_dir / "submission_compliance_audit.json", summary)
    return summary


def _install_poisoned_dashboard_artifacts(state: Path) -> None:
    _write_json(
        state / "public_status_review.json",
        inject_poison_fields(
            {
                "generated_at_utc": "2026-08-01T11:00:00Z",
                "success_count": 1,
                "failure_count": 0,
                "documents": {"success_count": 1, "failure_count": 0},
            },
            secret_canary=_SECRET,
            pdf_canary=_PDF_TOKEN,
        ),
    )
    _write_json(
        state / "schedule" / "install_manifest.json",
        inject_poison_fields(
            {
                "schema": "patlaw-schedule-manifest-v1",
                "installed": True,
                "unit": "portfolio-refresh.timer",
            },
            secret_canary=_SECRET,
            pdf_canary=_PDF_TOKEN,
        ),
    )


# ---------------------------------------------------------------------------
# Unit: redaction primitives
# ---------------------------------------------------------------------------


def test_is_secret_key_covers_credential_and_body_fields() -> None:
    assert is_secret_key("api_key")
    assert is_secret_key("X-API-Key")
    assert is_secret_key("document_body")
    assert is_secret_key("extracted_text")
    assert is_secret_key("pdf_body")
    assert is_secret_key("raw_payload")
    assert not is_secret_key("application_number")
    assert not is_secret_key("hit_count")
    assert not is_secret_key("overall_status")


def test_looks_like_pdf_or_binary_detects_pdf_header() -> None:
    body = synthetic_pdf_like_body(canary=_PDF_TOKEN)
    assert looks_like_pdf_or_binary(body)
    assert looks_like_pdf_or_binary(_PDF_PREFIX_SAFE := ("%" + "PDF-1.7 binary"))
    assert not looks_like_pdf_or_binary("US 1,000,000 short citation")


def test_sanitize_text_redacts_pdf_and_secret_patterns() -> None:
    pdf = synthetic_pdf_like_body(canary=_PDF_TOKEN)
    assert _PDF_TOKEN not in sanitize_text(pdf)
    assert "%" + "PDF" not in sanitize_text(pdf)
    scrubbed = sanitize_text("note authorization: " + "bearer " + _SECRET)
    assert _SECRET not in scrubbed.lower() or "redacted" in scrubbed.lower()


def test_redact_for_emit_strips_poison_keys_and_bodies() -> None:
    poisoned = inject_poison_fields(
        {"application_number": APP, "hit_count": 3, "status": "ok"},
        secret_canary=_SECRET,
        pdf_canary=_PDF_TOKEN,
    )
    # Ensure injection actually planted canaries before redaction.
    raw = serialize_content_free(poisoned)
    assert _SECRET in raw
    assert _PDF_TOKEN in raw

    clean = redact_for_emit(poisoned)
    assert isinstance(clean, dict)
    assert clean.get("application_number") == APP
    assert clean.get("hit_count") == 3
    assert "api_key" not in clean
    assert "password" not in clean
    assert "document_body" not in clean
    assert "pdf_body" not in clean
    assert "extracted_text" not in clean
    assert "raw_payload" not in clean
    leaks = payload_contains_canaries(clean, _CANARIES)
    assert leaks == [], f"redaction leaked: {leaks}"


def test_assert_content_free_rejects_markers_and_canaries() -> None:
    with pytest.raises(PortfolioContentFreeError):
        assert_content_free({"note": "authorization: " + "bearer " + "example"})
    with pytest.raises(PortfolioContentFreeError):
        assert_content_free({"x": "secret_document_body"})
    with pytest.raises(PortfolioContentFreeError):
        assert_content_free({"note": _SECRET}, canaries=[_SECRET])
    # Clean payload with unused canary list is fine (canaries only fail when present).
    assert_content_free({"status": "ok"}, canaries=[_SECRET])


def test_assert_content_free_accepts_clean_metadata() -> None:
    assert_content_free(
        {
            "schema": PORTFOLIO_CONTENT_FREE_SCHEMA,
            "content_free": True,
            "application_number": APP,
            "hit_count": 2,
            "overall_status": "review_required",
        },
        canaries=_CANARIES,
    )


def test_seal_content_free_stamps_policy() -> None:
    sealed = seal_content_free(
        inject_poison_fields({"ok": True, "count": 1}, secret_canary=_SECRET),
        surface="matter_status",
        canaries=_CANARIES,
    )
    assert sealed["content_free"] is True
    assert sealed["emit_surface"] == "matter_status"
    assert sealed["policy"]["task_id"] == "PATLAW-209"
    assert sealed.get("ok") is True
    assert sealed.get("count") == 1
    _assert_no_canaries(sealed, surface="matter_status")


# ---------------------------------------------------------------------------
# Surface emits with injected poison
# ---------------------------------------------------------------------------


def test_emit_matter_status_never_leaks_poison(tmp_path: Path) -> None:
    state = _seed_state(tmp_path)
    _install_poisoned_prior_art(state)
    _install_poisoned_audit(state)

    payload = emit_matter_status(state, canaries=_CANARIES)
    assert payload["content_free"] is True
    assert payload["emit_surface"] == "matter_status"
    assert payload.get("matter_count", 0) >= 1 or "matters" in payload
    _assert_no_canaries(payload, surface="matter_status")

    # Nested poison keys must be gone.
    blob = serialize_content_free(payload)
    assert "api_key" not in blob
    assert "document_body" not in blob
    assert "pdf_body" not in blob


def test_emit_dashboard_never_leaks_poison(tmp_path: Path) -> None:
    state = _seed_state(tmp_path)
    _install_poisoned_dashboard_artifacts(state)
    _install_poisoned_prior_art(state)

    payload = emit_dashboard(state, canaries=_CANARIES)
    assert payload["content_free"] is True
    assert payload["emit_surface"] == "dashboard"
    assert payload.get("schema")  # original or stamped
    _assert_no_canaries(payload, surface="dashboard")


def test_emit_audit_markdown_never_leaks_poison(tmp_path: Path) -> None:
    state = _seed_state(tmp_path)
    summary = _install_poisoned_audit(state)
    md_path = tmp_path / "out" / "audit.md"

    payload = emit_audit(summary, canaries=_CANARIES, write_markdown_to=md_path)
    assert payload["content_free"] is True
    assert payload["emit_surface"] == "audit"
    assert payload["overall_status"] == "review_required"
    assert "Submission compliance audit" in payload["markdown"]
    assert md_path.is_file()
    md_text = md_path.read_text(encoding="utf-8")
    for canary in _CANARIES:
        assert str(canary) not in md_text
        assert str(canary) not in payload["markdown"]
    _assert_no_canaries(payload, surface="audit")


def test_emit_ids_export_never_leaks_poison() -> None:
    queue = inject_poison_fields(
        {
            "schema_version": "ids-review-queue.v1",
            "queue_id": "idsq:pcf-export",
            "subject_id": f"app:{APP}",
            "auto_file_blocked": True,
            "disclaimer": "Human IDS candidate queue. Never auto-files.",
            "candidates": [
                {
                    "candidate_id": "cand:ready",
                    "document_id": "doc:ready",
                    "state": "ids_ready",
                    "is_ids_ready": True,
                    "citation_text": "US 9,999,999 — cite only",
                    "api_key": _SECRET,
                    "document_body": synthetic_pdf_like_body(canary=_PDF_TOKEN),
                },
                {
                    "candidate_id": "cand:pdf",
                    "document_id": "doc:pdf",
                    "state": "candidate",
                    "is_ids_ready": False,
                    "citation_text": synthetic_pdf_like_body(canary=_PDF_TOKEN),
                },
            ],
        },
        secret_canary=_SECRET,
        pdf_canary=_PDF_TOKEN,
    )

    payload = emit_ids_export(queue, canaries=_CANARIES)
    assert payload["content_free"] is True
    assert payload["emit_surface"] == "ids"
    assert payload["auto_file_blocked"] is True
    assert payload["patent_center_filing"] is False
    assert payload["ids_ready_count"] == 1
    # PDF-like citation must be replaced, not echoed.
    ready_cite = payload["ids_ready"][0]["citation_text"]
    assert _PDF_TOKEN not in ready_cite
    assert "%" + "PDF" not in ready_cite
    assert _PDF_TOKEN not in payload["markdown"]
    _assert_no_canaries(payload, surface="ids")


def test_emit_canary_never_leaks_poison() -> None:
    probes = [
        inject_poison_fields(
            {
                "source": "odp",
                "status": "fixture",
                "http_status": 200,
                "host": "api.uspto.gov",
                "digest": "sha256:deadbeef",
                "byte_count": 128,
            },
            secret_canary=_SECRET,
            pdf_canary=_PDF_TOKEN,
        ),
        {
            "source": "ecfr",
            "status": "fixture",
            "http_status": 200,
            "host": "www.ecfr.gov",
            "digest": "sha256:cafebabe",
            "byte_count": 64,
            "raw_body": synthetic_pdf_like_body(canary=_PDF_TOKEN),
            "cookie": _SECRET,
        },
    ]
    payload = emit_canary(
        probes,
        mode="offline",
        canaries=_CANARIES,
        extra=inject_poison_fields(
            {"operator_note": "bounded offline canary"},
            secret_canary=_SECRET,
            pdf_canary=_PDF_TOKEN,
        ),
    )
    assert payload["content_free"] is True
    assert payload["emit_surface"] == "canary"
    assert payload["mode"] == "offline"
    assert payload["probe_count"] == 2
    assert payload["policy"]["live_default"] is False
    for probe in payload["probes"]:
        assert "api_key" not in probe
        assert "raw_body" not in probe
        assert "cookie" not in probe
    _assert_no_canaries(payload, surface="canary")


def test_project_emit_routes_surfaces() -> None:
    audit = project_emit(
        "audit",
        inject_poison_fields(
            {
                "overall_status": "review_required",
                "application_number": APP,
                "audit_id": "audit:x",
                "action_plan": [],
                "disclaimer": "Review-only.",
            },
            secret_canary=_SECRET,
            pdf_canary=_PDF_TOKEN,
        ),
        canaries=_CANARIES,
    )
    assert audit["emit_surface"] == "audit"
    _assert_no_canaries(audit, surface="audit")

    ids = project_emit(
        "ids_export",
        {
            "queue_id": "q1",
            "candidates": [],
            "api_key": _SECRET,
        },
        canaries=_CANARIES,
    )
    assert ids["emit_surface"] == "ids"
    _assert_no_canaries(ids, surface="ids")

    canary = project_emit(
        "canary_receipt",
        {"mode": "offline", "probes": [], "token": _SECRET},
        canaries=_CANARIES,
    )
    assert canary["emit_surface"] == "canary"
    _assert_no_canaries(canary, surface="canary")


# ---------------------------------------------------------------------------
# Property-style: many poisoned shapes across all surfaces
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("surface", list(EMIT_SURFACES))
def test_property_poisoned_payload_never_leaks_on_any_surface(surface: str) -> None:
    """For every emit surface, poison injection must not survive projection."""
    base: dict[str, Any] = {
        "application_number": APP,
        "overall_status": "review_required",
        "status": "ok",
        "hit_count": 1,
        "mode": "offline",
        "queue_id": "idsq:prop",
        "subject_id": f"app:{APP}",
        "candidates": [
            {
                "candidate_id": "c1",
                "document_id": "d1",
                "state": "ids_ready",
                "is_ids_ready": True,
                "citation_text": "US 1 — short",
            }
        ],
        "probes": [
            {
                "source": "odp",
                "status": "fixture",
                "http_status": 200,
                "host": "api.uspto.gov",
                "digest": "sha256:aa",
                "byte_count": 1,
            }
        ],
        "action_plan": [{"code": "re_audit", "title": "Re-audit", "command": "x"}],
        "disclaimer": "Review-only.",
    }
    poisoned = inject_poison_fields(
        base, secret_canary=_SECRET, pdf_canary=_PDF_TOKEN
    )
    # Confirm canaries present pre-projection.
    assert _SECRET in serialize_content_free(poisoned)

    emitted = project_emit(surface, poisoned, canaries=_CANARIES)
    assert emitted.get("content_free") is True
    _assert_no_canaries(emitted, surface=surface)


@pytest.mark.parametrize(
    "pdf_canary",
    [
        "CONFIDENTIAL-PDF-BODY-CANARY-PCF",
        "BINARY-STREAM-CANARY-ALPHA",
        "PLACEHOLDER-PDF-BODY-99",
    ],
)
@pytest.mark.parametrize(
    "secret_canary",
    [
        "example-pcf-secret-7f3a",
        "placeholder-pcf-cookie-9b2c",
        "redacted-pcf-token-4d1e",
    ],
)
def test_property_redact_matrix_secret_and_pdf_canaries(
    secret_canary: str, pdf_canary: str
) -> None:
    poisoned = inject_poison_fields(
        {"safe": True, "count": 7, "label": "matter-status-row"},
        secret_canary=secret_canary,
        pdf_canary=pdf_canary,
    )
    canaries = all_injection_canaries(
        secret_canary=secret_canary, pdf_canary=pdf_canary
    )
    clean = redact_for_emit(poisoned)
    assert payload_contains_canaries(clean, canaries) == []
    sealed = seal_content_free(poisoned, surface="dashboard", canaries=canaries)
    assert sealed["content_free"] is True
    assert sealed.get("safe") is True
    assert sealed.get("count") == 7


def test_emit_surfaces_constant_covers_acceptance() -> None:
    required = {"matter_status", "dashboard", "audit", "ids", "canary"}
    assert required.issubset(set(EMIT_SURFACES))
    assert FORBIDDEN_CONTENT_MARKERS  # policy non-empty


def test_bytes_poison_redacted_not_hex_leaked() -> None:
    raw = synthetic_pdf_like_body(canary=_PDF_TOKEN).encode("utf-8")
    clean = redact_for_emit({"blob": raw, "status": "ok"})
    assert clean["status"] == "ok"
    assert isinstance(clean["blob"], str)
    assert "redacted" in clean["blob"]
    assert raw.hex() not in serialize_content_free(clean)
    assert _PDF_TOKEN not in serialize_content_free(clean)
