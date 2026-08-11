"""Positive and parity tests for the evaluator-complete LCR-082 contract."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data import legal_source_rights_policy as policy
from ipfs_datasets_py.processors.legal_data.legal_source_rights_policy import (
    ADMISSIBLE_CONTENT_SCOPES,
    CATALOG_PRODUCER,
    CATALOG_SCHEMA_VERSION,
    CONDITION_EVIDENCE_SCHEMA_VERSION,
    CURRENTNESS_DISCLAIMER,
    DEFAULT_QUARANTINED_CONTENT_SCOPES,
    EVIDENCE_SCHEMA_VERSION,
    EXPECTED_FRONTIER_SIZE,
    EXPECTED_STATE_SOURCE_COUNT,
    FIXTURE_GOAL_ID,
    FIXTURE_TASK_ID,
    FIXTURE_VERIFIER_CLOCK_UTC,
    PROGRAM_ID,
    SCHEMA_VERSION,
    TARGET_DATASET_REPO_IDS,
    VERIFIER_ID,
    CatalogSchemaError,
    ContentScope,
    EvidenceMode,
    LicenseIdentityError,
    SourceRightsCatalog,
    admitted_records,
    assert_catalog_distinguishes_scopes,
    audit_fixture_catalog,
    build_fixture_compliance_projection,
    canonical_json,
    compute_artifact_digests,
    default_fixture_catalog_path,
    derive_expected_scope_frontier,
    evaluate_catalog,
    evaluate_scope_rights,
    fixture_verifier_now,
    frontier_digest_sha256,
    get_fixture_source_rights_catalog,
    load_source_rights_catalog,
    load_spdx_registry,
    normalize_spdx,
    parse_utc_timestamp,
    require_scope_rights,
    sha256_bytes,
    sha256_file,
    sha256_json,
    validate_catalog_against_schema,
)


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return json.loads(default_fixture_catalog_path().read_bytes())


@pytest.fixture(scope="module")
def fixture_catalog() -> SourceRightsCatalog:
    return load_source_rights_catalog()


def _audit_module():
    path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ops"
        / "legal_data"
        / "audit_legal_source_rights.py"
    )
    spec = importlib.util.spec_from_file_location("lcr082_audit_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_v2_identity_constants_and_fixed_clock() -> None:
    assert SCHEMA_VERSION == "legal-source-rights-policy-v2"
    assert CATALOG_SCHEMA_VERSION == "legal-source-rights-catalog-v2"
    assert CATALOG_PRODUCER == "audit_legal_source_rights.py@2"
    assert PROGRAM_ID == "legal-corpora-reindex-v1"
    assert (FIXTURE_TASK_ID, FIXTURE_GOAL_ID) == ("LCR-082", "LCR-G144")
    assert FIXTURE_VERIFIER_CLOCK_UTC == "2026-08-10T12:00:00Z"
    assert policy.MAX_EVIDENCE_AGE.days == 90
    assert policy.MAX_FUTURE_SKEW.total_seconds() == 0
    assert fixture_verifier_now() == parse_utc_timestamp(FIXTURE_VERIFIER_CLOCK_UTC)


def test_public_authorizing_surfaces_have_no_override_parameters() -> None:
    expected = {
        policy.evaluate_catalog: ("value",),
        policy.evaluate_scope_rights: ("value", "record_id"),
        policy.require_scope_rights: ("value", "record_id"),
        policy.admitted_records: ("value",),
        policy.require_live_source_evidence: (),
        policy.load_catalog_payload: (),
        policy.load_source_rights_catalog: (),
        policy.frontier_digest_sha256: (),
    }
    for function, names in expected.items():
        assert tuple(inspect.signature(function).parameters) == names
    assert "registry" not in inspect.signature(normalize_spdx).parameters
    forbidden = {
        "now",
        "verifier_now",
        "max_evidence_age",
        "max_future_skew",
        "verify_digests",
        "catalog_path",
        "schema_path",
        "registry_path",
        "frontier",
        "proven_conditions",
        "authorizing_mode",
    }
    for function in expected:
        assert forbidden.isdisjoint(inspect.signature(function).parameters)


def test_enum_parsers_are_exact_and_expose_no_alias_coercion() -> None:
    exact = (
        (policy.ContentScope, "statutory_text"),
        (policy.CorpusFamily, "state_laws"),
        (policy.RightsDisposition, "allowed"),
        (policy.RobotsAccessDisposition, "allowed"),
        (policy.ReviewStatus, "reviewed"),
        (policy.LegalBasis, "us_government_work"),
        (policy.EvidenceMode, "fixture"),
    )
    for enum_type, value in exact:
        assert enum_type.parse(value).value == value
        assert not hasattr(enum_type, "coerce")
    for enum_type, alias in (
        (policy.ContentScope, "layout"),
        (policy.CorpusFamily, "justicedao/ipfs_state_laws"),
        (policy.RightsDisposition, "denied"),
        (policy.RobotsAccessDisposition, "allow"),
        (policy.ReviewStatus, "approved"),
        (policy.LegalBasis, "17_usc_105"),
        (policy.EvidenceMode, "fixture_only"),
    ):
        with pytest.raises(CatalogSchemaError):
            enum_type.parse(alias)


def test_complete_spdx_snapshot_and_license_refs_are_byte_bound() -> None:
    registry_payload = json.loads(policy.default_spdx_registry_path().read_bytes())
    registry = load_spdx_registry()
    assert registry.source_release_identifier == "spdx-license-ids@3.0.12"
    assert len(registry.active_ids) == registry.active_license_count == 465
    assert len(registry.deprecated_ids) == registry.deprecated_license_count == 25
    assert not registry.active_ids.intersection(registry.deprecated_ids)
    assert set(registry.license_refs) == set(policy.CANONICAL_LICENSE_REF_DIGESTS)
    sources = (
        ("source_package", policy.CANONICAL_SPDX_PACKAGE_SHA256),
        ("active_ids_source", policy.CANONICAL_SPDX_ACTIVE_IDS_SHA256),
        ("deprecated_ids_source", policy.CANONICAL_SPDX_DEPRECATED_IDS_SHA256),
    )
    for prefix, expected_digest in sources:
        raw = base64.b64decode(
            registry_payload[f"{prefix}_bytes_base64"], validate=True
        )
        assert sha256_bytes(raw) == registry_payload[f"{prefix}_sha256"]
        assert sha256_bytes(raw) == expected_digest
    for license_id, definition in registry.license_refs.items():
        raw = base64.b64decode(definition.definition_bytes_base64, validate=True)
        assert sha256_bytes(raw) == definition.definition_sha256
        assert (
            definition.definition_digest_sha256
            == policy.CANONICAL_LICENSE_REF_DIGESTS[license_id]
        )


@pytest.mark.parametrize("license_id", ["MIT", "Apache-2.0", "CC0-1.0"])
def test_exact_active_spdx_identifiers_are_accepted(license_id: str) -> None:
    assert normalize_spdx(license_id) == license_id


@pytest.mark.parametrize(
    "license_id",
    ["GPL-2.0", "GPL-2.0+", "mit", "other", "unknown", "Invented-9.9"],
)
def test_deprecated_alias_case_card_and_invented_licenses_are_rejected(
    license_id: str,
) -> None:
    with pytest.raises(LicenseIdentityError):
        normalize_spdx(license_id)


def test_only_registered_licenserefs_are_accepted() -> None:
    assert (
        normalize_spdx("LicenseRef-US-State-Statutory-Text")
        == "LicenseRef-US-State-Statutory-Text"
    )
    with pytest.raises(LicenseIdentityError, match="unregistered"):
        normalize_spdx("LicenseRef-Caller-Invented")


def test_frontier_is_full_unique_and_independently_derived() -> None:
    frontier = derive_expected_scope_frontier()
    assert len(frontier) == EXPECTED_FRONTIER_SIZE == 57
    assert len({entry.key() for entry in frontier}) == 57
    state_text = [
        entry
        for entry in frontier
        if entry.content_scope == ContentScope.STATUTORY_TEXT.value
    ]
    assert len(state_text) == EXPECTED_STATE_SOURCE_COUNT == 51
    assert len({entry.jurisdiction_or_authority for entry in state_text}) == 51
    assert len({entry.source_id for entry in frontier}) == 52
    assert {entry.content_scope for entry in frontier} == {
        scope.value for scope in ContentScope
    }
    assert frontier_digest_sha256() == sha256_json(
        [entry.to_dict() for entry in sorted(frontier)]
    )


def test_frontier_exactly_binds_lcr002_and_pinned_lcr048() -> None:
    frontier = derive_expected_scope_frontier()
    assert sha256_file(policy.default_state_source_catalog_path()) == policy.CANONICAL_LCR002_SHA256
    assert sha256_file(policy.default_federal_baseline_path()) == policy.CANONICAL_LCR048_SHA256
    federal = [entry for entry in frontier if entry.corpus_family == "federal_register"]
    assert len(federal) == 4
    assert {entry.source_id for entry in federal} == {
        "fr-hf-baseline-720668ae016cc400916dda884c9005e03618edfa"
    }
    assert {entry.content_scope for entry in federal} == {
        "federal_government_text",
        "site_presentation",
        "editorial_enhancements",
        "database_content",
    }


def test_fixture_is_exact_deterministic_build(fixture_payload: dict) -> None:
    generated = _audit_module().build_fixture_catalog_payload()
    assert canonical_json(fixture_payload) == canonical_json(generated)
    expected_bytes = (
        json.dumps(generated, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode()
    assert default_fixture_catalog_path().read_bytes() == expected_bytes
    assert fixture_payload["catalog_digest_sha256"] == sha256_json(
        {k: v for k, v in fixture_payload.items() if k != "catalog_digest_sha256"}
    )


def test_fixture_schema_identity_frontier_and_artifacts(
    fixture_payload: dict,
    fixture_catalog: SourceRightsCatalog,
) -> None:
    assert validate_catalog_against_schema(fixture_payload) == []
    assert fixture_catalog.schema_version == CATALOG_SCHEMA_VERSION
    assert fixture_catalog.producer == CATALOG_PRODUCER
    assert fixture_catalog.program_id == PROGRAM_ID
    assert (
        fixture_catalog.task_id,
        fixture_catalog.goal_id,
        fixture_catalog.evidence_mode,
    ) == (FIXTURE_TASK_ID, FIXTURE_GOAL_ID, EvidenceMode.FIXTURE)
    assert fixture_catalog.target_dataset_repo_ids == TARGET_DATASET_REPO_IDS
    assert fixture_catalog.currentness_disclaimer == CURRENTNESS_DISCLAIMER
    assert len(fixture_catalog.records) == 57
    assert dict(fixture_catalog.artifact_digests) == compute_artifact_digests()
    assert fixture_catalog.expected_scope_frontier_sha256 == frontier_digest_sha256()
    assert_catalog_distinguishes_scopes(fixture_catalog)


def test_fixture_evidence_identity_bytes_and_digests_are_complete(
    fixture_catalog: SourceRightsCatalog,
) -> None:
    for record in fixture_catalog.records:
        for expected_kind, evidence in (("terms", record.terms), ("robots", record.robots)):
            assert evidence.schema_version == EVIDENCE_SCHEMA_VERSION
            assert evidence.evidence_kind == expected_kind
            assert evidence.producer == CATALOG_PRODUCER
            assert evidence.program_id == PROGRAM_ID
            assert (evidence.task_id, evidence.goal_id, evidence.evidence_mode) == (
                FIXTURE_TASK_ID,
                FIXTURE_GOAL_ID,
                "fixture",
            )
            assert evidence.verifier_id == VERIFIER_ID
            assert (evidence.source_id, evidence.content_scope, evidence.url) == (
                record.source_id,
                record.content_scope.value,
                record.source_url,
            )
            raw = base64.b64decode(evidence.content_bytes_base64, validate=True)
            assert hashlib.sha256(raw).hexdigest() == evidence.content_sha256
            body = evidence.to_dict()
            declared = body.pop("evidence_digest_sha256")
            assert declared == sha256_json(body)


def test_fixture_has_one_fully_bound_conditional_positive(
    fixture_catalog: SourceRightsCatalog,
) -> None:
    conditional = [record for record in fixture_catalog.records if record.access_conditions]
    assert [record.record_id for record in conditional] == [
        "ak-akleg-basis-statutory_text"
    ]
    record = conditional[0]
    assert record.rights_disposition.value == "conditional"
    assert record.robots_access_disposition.value == "conditional"
    assert len(record.condition_evidence) == 1
    receipt = record.condition_evidence[0]
    assert receipt.schema_version == CONDITION_EVIDENCE_SCHEMA_VERSION
    assert receipt.condition_id == record.access_conditions[0]
    assert (receipt.source_id, receipt.content_scope) == (
        record.source_id,
        record.content_scope.value,
    )
    assert sha256_bytes(base64.b64decode(receipt.request_bytes_base64, validate=True)) == receipt.request_sha256
    assert sha256_bytes(base64.b64decode(receipt.response_bytes_base64, validate=True)) == receipt.response_sha256
    body = receipt.to_dict()
    declared = body.pop("receipt_digest_sha256")
    assert declared == sha256_json(body)
    decision = evaluate_scope_rights(fixture_catalog, record.record_id)
    assert decision.admitted is True
    assert "conditional_evidence_verified" in decision.reason_codes


def test_evaluator_parity_covers_all_records(fixture_catalog: SourceRightsCatalog) -> None:
    report = evaluate_catalog(fixture_catalog)
    selected = admitted_records(fixture_catalog)
    selected_ids = tuple(record.record_id for record in selected)
    assert report["record_count"] == 57
    assert report["admitted_count"] == 52
    assert report["denied_count"] == 5
    assert selected_ids == fixture_catalog.admitted_record_ids
    assert selected_ids == tuple(report["admitted_record_ids"])
    assert len(report["decisions"]) == 57
    for decision in report["decisions"]:
        individual = evaluate_scope_rights(fixture_catalog, decision["record_id"])
        assert individual.to_dict() == decision
        if individual.admitted:
            assert require_scope_rights(fixture_catalog, individual.record_id) == individual


def test_typed_excluded_scopes_remain_present_and_noncontributing(
    fixture_catalog: SourceRightsCatalog,
) -> None:
    report = evaluate_catalog(fixture_catalog)
    denied = {item["record_id"]: item for item in report["decisions"] if not item["admitted"]}
    excluded = {
        record.record_id
        for record in fixture_catalog.records
        if record.content_scope in DEFAULT_QUARANTINED_CONTENT_SCOPES
    }
    assert len(excluded) == 5
    assert set(denied) == excluded
    assert all("out_of_release_scope" in denied[record_id]["reason_codes"] for record_id in excluded)
    assert all(record.content_scope in ADMISSIBLE_CONTENT_SCOPES for record in admitted_records(fixture_catalog))


def test_fixture_success_is_structural_and_never_authorizing(
    fixture_catalog: SourceRightsCatalog,
) -> None:
    report = evaluate_catalog(fixture_catalog)
    projection = build_fixture_compliance_projection(fixture_catalog)
    assert fixture_catalog.authorizing_for_publication is False
    assert report["fixture_only_non_authorizing"] is True
    assert report["authorizing_for_publication"] is False
    assert projection["authorizing_for_publication"] is False
    assert all(decision["authorizing"] is False for decision in report["decisions"])


def test_fixture_audit_and_cli_declared_validation_pass() -> None:
    report = audit_fixture_catalog()
    assert report["status"] == "passed"
    assert report["record_count"] == 57
    assert report["admitted_count"] == 52
    assert report["authorizing_for_publication"] is False
    assert _audit_module().main(["--fixture-only", "--check"]) == 0


def test_fixed_loaders_reparse_instead_of_caching() -> None:
    first = get_fixture_source_rights_catalog()
    second = get_fixture_source_rights_catalog()
    assert first is not second
    assert first.to_dict() == second.to_dict()
    assert not hasattr(SourceRightsCatalog, "get")


def test_complete_catalog_is_required_by_all_rights_selectors(fixture_catalog: SourceRightsCatalog) -> None:
    with pytest.raises(CatalogSchemaError, match="complete"):
        evaluate_catalog(fixture_catalog.records)
    with pytest.raises(CatalogSchemaError, match="complete"):
        evaluate_scope_rights(fixture_catalog.records, fixture_catalog.records[0].record_id)
    with pytest.raises(CatalogSchemaError, match="complete"):
        admitted_records(fixture_catalog.records)


def test_canonical_florida_http_url_is_preserved_not_rewritten(
    fixture_catalog: SourceRightsCatalog,
) -> None:
    record = next(record for record in fixture_catalog.records if record.source_id == "fl-leg-statutes")
    assert record.source_url == "http://www.leg.state.fl.us/Statutes/"
    assert record.terms.url == record.source_url
    assert record.robots.url == record.source_url


def test_utc_parser_is_strict() -> None:
    assert parse_utc_timestamp("2026-08-10T12:00:00Z") == fixture_verifier_now()
    for invalid in (
        "2026-08-10T12:00:00",
        "2026-08-10T12:00:00+00:00",
        " 2026-08-10T12:00:00Z",
        1786363200,
    ):
        with pytest.raises(CatalogSchemaError):
            parse_utc_timestamp(invalid)
