"""Unit tests for the source-rights and redistribution admission contract (LCR-077).

Acceptance: fixtures distinguish statutory or Federal government text from site
presentation, annotations, editorial enhancements, and databases; malformed,
stale, unknown, prohibited, scope-mismatched, or unsupported evidence fails
closed; and no dataset-card label alone proves admissibility.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.legal_source_rights_policy import (
    ADMISSIBLE_CONTENT_SCOPES,
    CATALOG_SCHEMA_VERSION,
    DEFAULT_QUARANTINED_CONTENT_SCOPES,
    FEDERAL_DATASET_REPO_ID,
    FIXTURE_VERIFIER_CLOCK_UTC,
    GOAL_ID,
    SCHEMA_VERSION,
    STATE_DATASET_REPO_ID,
    TASK_ID,
    CardOnlyEvidenceError,
    CatalogSchemaError,
    ContentScope,
    CorpusFamily,
    EvidenceMode,
    LegalBasis,
    LiveEvidenceRequiredError,
    ProhibitedScopeError,
    RightsDisposition,
    RobotsAccessDisposition,
    ReviewStatus,
    ScopeMismatchError,
    SourceRightsCatalog,
    SourceRightsRecord,
    StaleEvidenceError,
    UnknownRightsError,
    admitted_records,
    assert_catalog_distinguishes_scopes,
    audit_fixture_catalog,
    build_fixture_compliance_projection,
    clear_catalog_cache,
    default_fixture_catalog_path,
    default_schema_path,
    evaluate_catalog,
    evaluate_scope_rights,
    fixture_verifier_now,
    get_fixture_source_rights_catalog,
    load_schema_document,
    load_source_rights_catalog,
    normalize_spdx,
    parse_utc_timestamp,
    require_live_source_evidence,
    require_scope_rights,
    sha256_json,
    validate_catalog_against_schema,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_catalog_cache()
    yield
    clear_catalog_cache()


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    path = default_fixture_catalog_path()
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fixture_catalog() -> SourceRightsCatalog:
    return load_source_rights_catalog(default_fixture_catalog_path())


def _record_payload(fixture_payload: dict, record_id: str) -> dict:
    for item in fixture_payload["records"]:
        if item["record_id"] == record_id:
            return copy.deepcopy(item)
    raise KeyError(record_id)


# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "legal-source-rights-policy-v1"
    assert CATALOG_SCHEMA_VERSION == "legal-source-rights-catalog-v1"
    assert TASK_ID == "LCR-077"
    assert GOAL_ID == "LCR-G141"
    assert FIXTURE_VERIFIER_CLOCK_UTC == "2026-08-10T12:00:00Z"


def test_schema_document_exists_and_declares_content_scopes() -> None:
    path = default_schema_path()
    assert path.is_file()
    schema = load_schema_document(path)
    assert schema["properties"]["schema_version"]["const"] == CATALOG_SCHEMA_VERSION
    scopes = schema["$defs"]["sourceRightsRecord"]["properties"]["content_scope"]["enum"]
    for required in (
        "statutory_text",
        "federal_government_text",
        "site_presentation",
        "annotations",
        "editorial_enhancements",
        "database_content",
    ):
        assert required in scopes
    assert schema["$defs"]["sourceRightsRecord"]["properties"][
        "card_label_is_not_authority"
    ]["const"] is True


def test_fixture_catalog_path_exists() -> None:
    path = default_fixture_catalog_path()
    assert path.is_file()
    assert path.as_posix().endswith("tests/fixtures/legal_ir/legal_source_rights_catalog.json")


# ---------------------------------------------------------------------------
# Fixture catalog: content-scope distinction
# ---------------------------------------------------------------------------


def test_fixture_catalog_loads_and_is_non_authorizing(
    fixture_catalog: SourceRightsCatalog,
) -> None:
    assert fixture_catalog.schema_version == CATALOG_SCHEMA_VERSION
    assert fixture_catalog.task_id == TASK_ID
    assert fixture_catalog.goal_id == GOAL_ID
    assert fixture_catalog.evidence_mode is EvidenceMode.FIXTURE
    assert fixture_catalog.authorizing_for_publication is False
    assert set(fixture_catalog.target_dataset_repo_ids) == {
        STATE_DATASET_REPO_ID,
        FEDERAL_DATASET_REPO_ID,
    }
    assert_catalog_distinguishes_scopes(fixture_catalog)


def test_fixture_distinguishes_government_text_from_enhancements(
    fixture_catalog: SourceRightsCatalog,
) -> None:
    scopes = {record.content_scope for record in fixture_catalog.records}
    assert ContentScope.STATUTORY_TEXT in scopes
    assert ContentScope.FEDERAL_GOVERNMENT_TEXT in scopes
    assert ContentScope.SITE_PRESENTATION in scopes
    assert ContentScope.ANNOTATIONS in scopes
    assert ContentScope.EDITORIAL_ENHANCEMENTS in scopes
    assert ContentScope.DATABASE_CONTENT in scopes
    assert DEFAULT_QUARANTINED_CONTENT_SCOPES.issubset(scopes)


def test_fixture_schema_validation_passes(fixture_payload: dict) -> None:
    errors = validate_catalog_against_schema(fixture_payload)
    assert errors == []


def test_cached_fixture_loader_matches_disk() -> None:
    a = get_fixture_source_rights_catalog()
    b = get_fixture_source_rights_catalog()
    assert a is b
    assert a.catalog_digest_sha256() == sha256_json(
        {
            k: v
            for k, v in json.loads(default_fixture_catalog_path().read_text(encoding="utf-8")).items()
            if k != "catalog_digest_sha256"
        }
    )


# ---------------------------------------------------------------------------
# Admission: government / statutory text allowed
# ---------------------------------------------------------------------------


def test_statutory_text_is_admitted(fixture_catalog: SourceRightsCatalog) -> None:
    record = fixture_catalog.get("or-statutes-statutory-text")
    decision = evaluate_scope_rights(record, now=fixture_verifier_now())
    assert decision.admitted is True
    assert decision.authorizing is False  # no authorizing_mode
    assert record.content_scope is ContentScope.STATUTORY_TEXT
    assert record.rights_disposition is RightsDisposition.ALLOWED


def test_federal_government_text_is_admitted(fixture_catalog: SourceRightsCatalog) -> None:
    record = fixture_catalog.get("fr-govinfo-federal-text")
    decision = evaluate_scope_rights(record, now=fixture_verifier_now())
    assert decision.admitted is True
    assert record.content_scope is ContentScope.FEDERAL_GOVERNMENT_TEXT
    assert record.legal_basis is LegalBasis.US_GOVERNMENT_WORK


def test_card_label_present_does_not_block_when_full_evidence_exists(
    fixture_catalog: SourceRightsCatalog,
) -> None:
    """Mirrored card labels are fine as audit metadata; they are not authority."""
    record = fixture_catalog.get("card-label-only-not-authority")
    assert record.dataset_card_label == "other"
    assert record.card_label_is_not_authority is True
    decision = evaluate_scope_rights(record, now=fixture_verifier_now())
    assert decision.admitted is True


def test_normalize_spdx_rejects_card_only_labels() -> None:
    for label in ("other", "unknown", "proprietary", "custom", "none", "all-rights-reserved"):
        with pytest.raises(CardOnlyEvidenceError):
            normalize_spdx(label)


def test_normalize_spdx_accepts_spdx_and_licenseref() -> None:
    assert normalize_spdx("CC0-1.0") == "CC0-1.0"
    assert normalize_spdx("LicenseRef-OR-Government-Edicts") == "LicenseRef-OR-Government-Edicts"


# ---------------------------------------------------------------------------
# Fail closed: presentation / annotations / editorial / database
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "record_id,scope",
    [
        ("or-statutes-site-presentation", ContentScope.SITE_PRESENTATION),
        ("or-statutes-annotations", ContentScope.ANNOTATIONS),
        ("fr-site-editorial-enhancements", ContentScope.EDITORIAL_ENHANCEMENTS),
        ("fr-api-database-content", ContentScope.DATABASE_CONTENT),
    ],
)
def test_presentation_and_enhancement_scopes_are_denied(
    fixture_catalog: SourceRightsCatalog,
    record_id: str,
    scope: ContentScope,
) -> None:
    record = fixture_catalog.get(record_id)
    assert record.content_scope is scope
    decision = evaluate_scope_rights(record, now=fixture_verifier_now())
    assert decision.admitted is False
    assert "presentation_or_enhancement_scope" in decision.reason_codes
    with pytest.raises(ProhibitedScopeError):
        require_scope_rights(record, now=fixture_verifier_now())


def test_unknown_disposition_fails_closed(fixture_catalog: SourceRightsCatalog) -> None:
    record = fixture_catalog.get("unknown-secondary-mirror")
    decision = evaluate_scope_rights(record, now=fixture_verifier_now())
    assert decision.admitted is False
    assert "unknown_rights" in decision.reason_codes
    with pytest.raises(UnknownRightsError):
        require_scope_rights(record, now=fixture_verifier_now())


def test_stale_evidence_fails_closed(fixture_catalog: SourceRightsCatalog) -> None:
    record = fixture_catalog.get("stale-evidence-example")
    decision = evaluate_scope_rights(record, now=fixture_verifier_now())
    assert decision.admitted is False
    assert "stale_evidence" in decision.reason_codes
    with pytest.raises(StaleEvidenceError):
        require_scope_rights(record, now=fixture_verifier_now())


# ---------------------------------------------------------------------------
# Fail closed: mutated / malformed / mismatched evidence
# ---------------------------------------------------------------------------


def test_scope_mismatch_fails_closed(fixture_catalog: SourceRightsCatalog) -> None:
    record = fixture_catalog.get("or-statutes-statutory-text")
    decision = evaluate_scope_rights(
        record,
        expected_content_scope=ContentScope.FEDERAL_GOVERNMENT_TEXT,
        now=fixture_verifier_now(),
    )
    assert decision.admitted is False
    assert "scope_mismatch" in decision.reason_codes
    with pytest.raises(ScopeMismatchError):
        require_scope_rights(
            record,
            expected_content_scope="federal_government_text",
            now=fixture_verifier_now(),
        )


def test_corpus_and_repo_mismatch_fail_closed(fixture_catalog: SourceRightsCatalog) -> None:
    record = fixture_catalog.get("or-statutes-statutory-text")
    d1 = evaluate_scope_rights(
        record,
        expected_corpus=CorpusFamily.FEDERAL_REGISTER,
        now=fixture_verifier_now(),
    )
    assert d1.admitted is False
    assert "corpus_mismatch" in d1.reason_codes
    d2 = evaluate_scope_rights(
        record,
        expected_dataset_repo_id=FEDERAL_DATASET_REPO_ID,
        now=fixture_verifier_now(),
    )
    assert d2.admitted is False
    assert "dataset_repo_mismatch" in d2.reason_codes


def test_prohibited_disposition_fails_closed(fixture_payload: dict) -> None:
    payload = _record_payload(fixture_payload, "or-statutes-statutory-text")
    payload["rights_disposition"] = "prohibited"
    decision = evaluate_scope_rights(payload, now=fixture_verifier_now())
    assert decision.admitted is False
    assert "prohibited" in decision.reason_codes


def test_unsupported_disposition_fails_closed(fixture_payload: dict) -> None:
    payload = _record_payload(fixture_payload, "or-statutes-statutory-text")
    payload["rights_disposition"] = "unsupported"
    decision = evaluate_scope_rights(payload, now=fixture_verifier_now())
    assert decision.admitted is False
    assert "unsupported_rights" in decision.reason_codes


def test_missing_permissions_fail_closed(fixture_payload: dict) -> None:
    payload = _record_payload(fixture_payload, "or-statutes-statutory-text")
    payload["permissions"] = {
        "redistribution": True,
        "derivatives": False,
        "archive": True,
    }
    decision = evaluate_scope_rights(payload, now=fixture_verifier_now())
    assert decision.admitted is False
    assert "permissions_incomplete" in decision.reason_codes
    assert "derivatives" in decision.reason_codes


def test_robots_denied_fails_closed(fixture_payload: dict) -> None:
    payload = _record_payload(fixture_payload, "or-statutes-statutory-text")
    payload["robots"]["access_disposition"] = "denied"
    decision = evaluate_scope_rights(payload, now=fixture_verifier_now())
    assert decision.admitted is False
    assert "robots_denied" in decision.reason_codes


def test_robots_unknown_fails_closed(fixture_payload: dict) -> None:
    payload = _record_payload(fixture_payload, "or-statutes-statutory-text")
    payload["robots"]["access_disposition"] = "unknown"
    decision = evaluate_scope_rights(payload, now=fixture_verifier_now())
    assert decision.admitted is False
    assert "robots_unknown" in decision.reason_codes


def test_unreviewed_fails_closed(fixture_payload: dict) -> None:
    payload = _record_payload(fixture_payload, "or-statutes-statutory-text")
    payload["review_status"] = "unreviewed"
    decision = evaluate_scope_rights(payload, now=fixture_verifier_now())
    assert decision.admitted is False
    assert "unreviewed" in decision.reason_codes


def test_future_seal_fails_closed(fixture_payload: dict) -> None:
    payload = _record_payload(fixture_payload, "or-statutes-statutory-text")
    payload["sealed_at"] = "2099-01-01T00:00:00Z"
    payload["reviewed_at"] = "2099-01-01T00:00:00Z"
    decision = evaluate_scope_rights(payload, now=fixture_verifier_now())
    assert decision.admitted is False
    assert any(
        code in decision.reason_codes
        for code in ("future_timestamp", "seal_after_verifier")
    )


def test_terms_after_review_fails_closed(fixture_payload: dict) -> None:
    payload = _record_payload(fixture_payload, "or-statutes-statutory-text")
    payload["terms"]["observed_at"] = "2026-08-09T00:00:00Z"
    payload["reviewed_at"] = "2026-08-05T12:00:00Z"
    decision = evaluate_scope_rights(payload, now=fixture_verifier_now())
    assert decision.admitted is False
    assert "terms_after_review" in decision.reason_codes


def test_licenseref_requires_definition(fixture_payload: dict) -> None:
    payload = _record_payload(fixture_payload, "or-statutes-statutory-text")
    del payload["license_ref"]
    with pytest.raises(CatalogSchemaError, match="license_ref"):
        SourceRightsRecord.from_mapping(payload)


def test_malformed_catalog_missing_records_fails() -> None:
    with pytest.raises(CatalogSchemaError):
        SourceRightsCatalog.from_mapping(
            {
                "schema_version": CATALOG_SCHEMA_VERSION,
                "task_id": TASK_ID,
                "goal_id": GOAL_ID,
                "evidence_mode": "fixture",
                "producer": "test",
                "sealed_at": "2026-08-10T11:00:00Z",
                "policy_schema_version": SCHEMA_VERSION,
                "authorizing_for_publication": False,
                "target_dataset_repo_ids": [
                    STATE_DATASET_REPO_ID,
                    FEDERAL_DATASET_REPO_ID,
                ],
                "records": [],
            }
        )


def test_fixture_cannot_claim_publication_authority(fixture_payload: dict) -> None:
    payload = copy.deepcopy(fixture_payload)
    payload["authorizing_for_publication"] = True
    with pytest.raises(CatalogSchemaError, match="authorizing_for_publication"):
        SourceRightsCatalog.from_mapping(payload)


def test_wrong_task_id_fails(fixture_payload: dict) -> None:
    payload = copy.deepcopy(fixture_payload)
    payload["task_id"] = "LCR-000"
    with pytest.raises(CatalogSchemaError, match="task_id"):
        SourceRightsCatalog.from_mapping(payload)


def test_card_label_as_spdx_fails() -> None:
    with pytest.raises(CardOnlyEvidenceError):
        normalize_spdx("other")


# ---------------------------------------------------------------------------
# admitted_records parity with evaluator
# ---------------------------------------------------------------------------


def test_admitted_records_matches_evaluator(fixture_catalog: SourceRightsCatalog) -> None:
    now = fixture_verifier_now()
    admitted = admitted_records(fixture_catalog, now=now)
    admitted_ids = {r.record_id for r in admitted}
    for record in fixture_catalog.records:
        decision = evaluate_scope_rights(record, now=now)
        if decision.admitted:
            assert record.record_id in admitted_ids
            assert record.content_scope in ADMISSIBLE_CONTENT_SCOPES
        else:
            assert record.record_id not in admitted_ids
    # At least the two government/statutory fixtures + card-label-with-evidence.
    assert len(admitted) >= 2
    assert all(r.content_scope in ADMISSIBLE_CONTENT_SCOPES for r in admitted)


def test_evaluate_catalog_summary(fixture_catalog: SourceRightsCatalog) -> None:
    report = evaluate_catalog(fixture_catalog, now=fixture_verifier_now())
    assert report["task_id"] == TASK_ID
    assert report["admitted_count"] >= 2
    assert report["denied_count"] >= 4
    assert report["authorizing_for_publication"] is False
    assert report["fixture_only_non_authorizing"] is True
    assert set(report["admitted_content_scopes"]).issubset(
        {s.value for s in ADMISSIBLE_CONTENT_SCOPES}
    )


# ---------------------------------------------------------------------------
# Audit fixture path
# ---------------------------------------------------------------------------


def test_audit_fixture_catalog_passes() -> None:
    report = audit_fixture_catalog()
    assert report["status"] == "passed"
    assert report["admitted_count"] >= 2
    assert report["denied_count"] >= 1
    assert report["authorizing_for_publication"] is False
    assert report["fixture_only_non_authorizing"] is True


def test_build_fixture_compliance_projection_is_non_authorizing(
    fixture_catalog: SourceRightsCatalog,
) -> None:
    projection = build_fixture_compliance_projection(fixture_catalog)
    assert projection["mode"] == "fixture_only"
    assert projection["authorizing_for_publication"] is False


def test_require_live_source_evidence_fails_when_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing_live_catalog.json"
    with pytest.raises(LiveEvidenceRequiredError):
        require_live_source_evidence(catalog_path=missing)


def test_authorizing_mode_requires_trusted_clock(
    fixture_catalog: SourceRightsCatalog,
) -> None:
    record = fixture_catalog.get("or-statutes-statutory-text")
    decision = evaluate_scope_rights(record, authorizing_mode=True, now=None)
    assert decision.admitted is False
    assert "missing_trusted_clock" in decision.reason_codes


def test_authorizing_mode_with_clock_admits_but_fixture_catalog_not_live(
    fixture_catalog: SourceRightsCatalog,
) -> None:
    record = fixture_catalog.get("fr-govinfo-federal-text")
    decision = evaluate_scope_rights(
        record,
        authorizing_mode=True,
        now=fixture_verifier_now(),
    )
    assert decision.admitted is True
    assert decision.authorizing is True
    # Catalog-level projection remains non-authorizing for fixture mode.
    report = evaluate_catalog(
        fixture_catalog,
        now=fixture_verifier_now(),
        authorizing_mode=True,
    )
    assert report["authorizing_for_publication"] is False


# ---------------------------------------------------------------------------
# Enum coerce helpers
# ---------------------------------------------------------------------------


def test_enum_coerce_helpers() -> None:
    assert ContentScope.coerce("annotations") is ContentScope.ANNOTATIONS
    assert ContentScope.coerce("layout") is ContentScope.SITE_PRESENTATION
    assert RightsDisposition.coerce("denied") is RightsDisposition.PROHIBITED
    assert RobotsAccessDisposition.coerce("allow") is RobotsAccessDisposition.ALLOWED
    assert ReviewStatus.coerce("approved") is ReviewStatus.REVIEWED
    assert LegalBasis.coerce("17_usc_105") is LegalBasis.US_GOVERNMENT_WORK
    assert CorpusFamily.coerce("justicedao/ipfs_state_laws") is CorpusFamily.STATE_LAWS
    assert EvidenceMode.coerce("fixture_only") is EvidenceMode.FIXTURE


def test_parse_utc_timestamp_rejects_naive() -> None:
    with pytest.raises(CatalogSchemaError):
        parse_utc_timestamp("2026-08-10T12:00:00", name="t")
    ts = parse_utc_timestamp("2026-08-10T12:00:00Z")
    assert ts == datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def test_stale_boundary_uses_max_age(fixture_payload: dict) -> None:
    payload = _record_payload(fixture_payload, "or-statutes-statutory-text")
    # Make terms just outside a 1-day window relative to verifier clock.
    payload["terms"]["observed_at"] = "2026-08-08T11:00:00Z"
    payload["robots"]["observed_at"] = "2026-08-08T11:00:00Z"
    payload["reviewed_at"] = "2026-08-08T12:00:00Z"
    decision = evaluate_scope_rights(
        payload,
        now=fixture_verifier_now(),
        max_evidence_age=timedelta(days=1),
    )
    assert decision.admitted is False
    assert "stale_evidence" in decision.reason_codes


# ---------------------------------------------------------------------------
# CLI smoke (import / main)
# ---------------------------------------------------------------------------


def _load_audit_cli():
    import importlib.util

    module_path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ops"
        / "legal_data"
        / "audit_legal_source_rights.py"
    )
    spec = importlib.util.spec_from_file_location(
        "audit_legal_source_rights_under_test", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_cli_fixture_only_check() -> None:
    module = _load_audit_cli()
    rc = module.main(["--fixture-only", "--check"])
    assert rc == 0


def test_audit_cli_live_fails_closed_without_catalog(tmp_path: Path) -> None:
    module = _load_audit_cli()
    rc = module.main(
        [
            "--require-live-source-evidence",
            "--check",
            "--catalog",
            str(tmp_path / "nope.json"),
        ]
    )
    assert rc == 1
