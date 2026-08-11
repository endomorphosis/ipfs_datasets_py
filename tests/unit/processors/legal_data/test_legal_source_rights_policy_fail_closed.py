"""Adversarial denial matrix for the evaluator-complete LCR-082 contract."""

from __future__ import annotations

import base64
import copy
import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType

import pytest

from ipfs_datasets_py.processors.legal_data import legal_source_rights_policy as policy
from ipfs_datasets_py.processors.legal_data.legal_source_rights_policy import (
    CatalogSchemaError,
    DigestMismatchError,
    FrontierMismatchError,
    IdentityError,
    LegalSourceRightsPolicyError,
    LicenseIdentityError,
    LiveEvidenceRequiredError,
    RightsAdmissionError,
    SourceRightsCatalog,
    SpdxLicenseRegistry,
    admitted_records,
    build_fixture_compliance_projection,
    default_fixture_catalog_path,
    derive_expected_scope_frontier,
    evaluate_catalog,
    evaluate_scope_rights,
    frontier_digest_sha256,
    load_source_rights_catalog,
    normalize_spdx,
    require_live_source_evidence,
    require_scope_rights,
    sha256_bytes,
    sha256_json,
)


@pytest.fixture()
def payload() -> dict:
    return json.loads(default_fixture_catalog_path().read_bytes())


def _record(payload: dict, record_id: str) -> dict:
    return next(item for item in payload["records"] if item["record_id"] == record_id)


def _seal_catalog(payload: dict) -> dict:
    body = {k: v for k, v in payload.items() if k != "catalog_digest_sha256"}
    payload["catalog_digest_sha256"] = sha256_json(body)
    return payload


def _seal_evidence(evidence: dict) -> None:
    body = {k: v for k, v in evidence.items() if k != "evidence_digest_sha256"}
    evidence["evidence_digest_sha256"] = sha256_json(body)


def _seal_receipt(receipt: dict) -> None:
    body = {k: v for k, v in receipt.items() if k != "receipt_digest_sha256"}
    receipt["receipt_digest_sha256"] = sha256_json(body)


def _seal_registry(registry: dict) -> None:
    body = {k: v for k, v in registry.items() if k != "registry_digest_sha256"}
    registry["registry_digest_sha256"] = sha256_json(body)


def _remove_admission(payload: dict, record_id: str) -> None:
    payload["admitted_record_ids"] = [
        item for item in payload["admitted_record_ids"] if item != record_id
    ]


def _semantic_denial(payload: dict, record_id: str) -> dict:
    _remove_admission(payload, record_id)
    _seal_catalog(payload)
    return evaluate_catalog(payload)


def _decision(report: dict, record_id: str) -> dict:
    return next(item for item in report["decisions"] if item["record_id"] == record_id)


def _as_fresh_live(payload: dict) -> dict:
    now = datetime.now(UTC)
    payload.update(
        {
            "task_id": "LCR-078",
            "goal_id": "LCR-G141",
            "evidence_mode": "live",
            "authorizing_for_publication": True,
            "sealed_at": policy.format_utc_timestamp(now - timedelta(days=1)),
        }
    )
    for record in payload["records"]:
        record["reviewed_at"] = policy.format_utc_timestamp(now - timedelta(days=3))
        record["sealed_at"] = policy.format_utc_timestamp(now - timedelta(days=2))
        for offset, kind in ((timedelta(days=5), "terms"), (timedelta(days=4), "robots")):
            evidence = record[kind]
            evidence.update(
                {
                    "task_id": "LCR-078",
                    "goal_id": "LCR-G141",
                    "evidence_mode": "live",
                    "verifier_observed_at": policy.format_utc_timestamp(now - offset),
                }
            )
            _seal_evidence(evidence)
        for receipt in record["condition_evidence"]:
            receipt.update(
                {
                    "task_id": "LCR-078",
                    "goal_id": "LCR-G141",
                    "evidence_mode": "live",
                    "verifier_observed_at": policy.format_utc_timestamp(
                        now - timedelta(days=4)
                    ),
                }
            )
            _seal_receipt(receipt)
    return _seal_catalog(payload)


ROOT_IDENTITY_FIELDS = (
    "schema_version",
    "producer",
    "program_id",
    "task_id",
    "goal_id",
    "evidence_mode",
    "policy_schema_version",
)


@pytest.mark.parametrize("field", ROOT_IDENTITY_FIELDS)
def test_each_missing_catalog_identity_field_denies(payload: dict, field: str) -> None:
    del payload[field]
    _seal_catalog(payload)
    with pytest.raises(CatalogSchemaError):
        evaluate_catalog(payload)


def test_all_missing_catalog_identity_fields_deny(payload: dict) -> None:
    for field in ROOT_IDENTITY_FIELDS:
        del payload[field]
    _seal_catalog(payload)
    with pytest.raises(CatalogSchemaError):
        evaluate_catalog(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "legal-source-rights-catalog-v1"),
        ("producer", "caller.py@2"),
        ("program_id", "legal-corpora-reindex"),
        ("task_id", "LCR-078"),
        ("goal_id", "LCR-G141"),
        ("evidence_mode", "fixture_only"),
        ("policy_schema_version", "legal-source-rights-policy-v1"),
    ],
)
def test_wrong_aliased_or_swapped_catalog_identity_denies(
    payload: dict, field: str, value: str
) -> None:
    payload[field] = value
    _seal_catalog(payload)
    with pytest.raises((CatalogSchemaError, IdentityError)):
        evaluate_catalog(payload)


@pytest.mark.parametrize("value", [1, True, ["LCR-082"], {"value": "LCR-082"}, None])
def test_identity_types_are_not_coerced(payload: dict, value: object) -> None:
    payload["task_id"] = value
    _seal_catalog(payload)
    with pytest.raises(CatalogSchemaError):
        evaluate_catalog(payload)


def test_non_dict_mapping_is_not_coerced(payload: dict) -> None:
    with pytest.raises(CatalogSchemaError, match="exact JSON object"):
        evaluate_catalog(MappingProxyType(payload))


def test_extra_catalog_or_record_fields_deny(payload: dict) -> None:
    payload["verify_digests"] = False
    _seal_catalog(payload)
    with pytest.raises(CatalogSchemaError):
        evaluate_catalog(payload)
    payload = json.loads(default_fixture_catalog_path().read_bytes())
    _record(payload, "al-alison-code-statutory_text")["proven_conditions"] = []
    _seal_catalog(payload)
    with pytest.raises(CatalogSchemaError):
        evaluate_catalog(payload)


@pytest.mark.parametrize("field", ["producer", "program_id", "task_id", "goal_id", "evidence_mode", "verifier_id"])
@pytest.mark.parametrize("kind", ["terms", "robots"])
def test_nested_evidence_identity_is_explicit_and_exact(
    payload: dict, field: str, kind: str
) -> None:
    evidence = _record(payload, "al-alison-code-statutory_text")[kind]
    del evidence[field]
    _seal_evidence(evidence)
    _seal_catalog(payload)
    with pytest.raises(CatalogSchemaError):
        evaluate_catalog(payload)


def test_nested_evidence_tuple_cannot_be_swapped(payload: dict) -> None:
    evidence = _record(payload, "al-alison-code-statutory_text")["terms"]
    evidence.update({"task_id": "LCR-078", "goal_id": "LCR-G141", "evidence_mode": "live"})
    _seal_evidence(evidence)
    _seal_catalog(payload)
    with pytest.raises(IdentityError):
        evaluate_catalog(payload)


def test_fixture_cannot_claim_publication_authority(payload: dict) -> None:
    payload["authorizing_for_publication"] = True
    _seal_catalog(payload)
    with pytest.raises(IdentityError, match="fixture"):
        evaluate_catalog(payload)


@pytest.mark.parametrize(
    "license_id",
    ["Made-Up-1.0", "GPL-2.0", "GPL-2.0+", "mit", "other", "LicenseRef-Unregistered"],
)
def test_bad_license_identity_in_record_denies(payload: dict, license_id: str) -> None:
    record = _record(payload, "al-alison-code-statutory_text")
    record["license_spdx"] = license_id
    record["license_ref_digest_sha256"] = (
        "0" * 64 if license_id.startswith("LicenseRef-") else None
    )
    _seal_catalog(payload)
    with pytest.raises(LicenseIdentityError):
        evaluate_catalog(payload)


def test_registered_licenseref_requires_exact_definition_digest(payload: dict) -> None:
    record = _record(payload, "al-alison-code-statutory_text")
    record["license_ref_digest_sha256"] = "0" * 64
    _seal_catalog(payload)
    with pytest.raises(LicenseIdentityError):
        evaluate_catalog(payload)


def test_canonical_spdx_source_list_cannot_be_self_resealed() -> None:
    registry = json.loads(policy.default_spdx_registry_path().read_bytes())
    active = json.loads(base64.b64decode(registry["active_ids_source_bytes_base64"]))
    active.append("ZZZ-Caller-Invented")
    active.sort()
    raw = json.dumps(active, indent=1).replace(" ", "\t").encode() + b"\n"
    registry["active_ids_source_bytes_base64"] = base64.b64encode(raw).decode()
    registry["active_ids_source_sha256"] = sha256_bytes(raw)
    registry["active_license_count"] = len(active)
    _seal_registry(registry)
    with pytest.raises(DigestMismatchError, match="canonical release digest"):
        SpdxLicenseRegistry.from_mapping(registry)


def test_canonical_spdx_package_cannot_be_self_resealed() -> None:
    registry = json.loads(policy.default_spdx_registry_path().read_bytes())
    package = json.loads(base64.b64decode(registry["source_package_bytes_base64"]))
    package["description"] = "caller replacement"
    raw = json.dumps(package).encode()
    registry["source_package_bytes_base64"] = base64.b64encode(raw).decode()
    registry["source_package_sha256"] = sha256_bytes(raw)
    _seal_registry(registry)
    with pytest.raises(DigestMismatchError, match="canonical release digest"):
        SpdxLicenseRegistry.from_mapping(registry)


def test_licenseref_definition_cannot_be_mutated_and_self_resealed() -> None:
    registry = json.loads(policy.default_spdx_registry_path().read_bytes())
    definition = registry["license_refs"][0]
    raw = b"caller replacement definition"
    definition["definition_bytes_base64"] = base64.b64encode(raw).decode()
    definition["definition_sha256"] = sha256_bytes(raw)
    definition["definition_digest_sha256"] = sha256_json(
        {k: v for k, v in definition.items() if k != "definition_digest_sha256"}
    )
    _seal_registry(registry)
    with pytest.raises(LicenseIdentityError, match="canonical registered definitions"):
        SpdxLicenseRegistry.from_mapping(registry)


@pytest.mark.parametrize("kind", ["terms", "robots"])
def test_mutated_evidence_bytes_with_unchanged_hash_denies(payload: dict, kind: str) -> None:
    evidence = _record(payload, "al-alison-code-statutory_text")[kind]
    raw = base64.b64decode(evidence["content_bytes_base64"])
    evidence["content_bytes_base64"] = base64.b64encode(b"X" + raw[1:]).decode()
    _seal_catalog(payload)
    with pytest.raises(DigestMismatchError):
        evaluate_catalog(payload)


@pytest.mark.parametrize("kind", ["terms", "robots"])
def test_mutated_evidence_bytes_and_content_hash_still_require_evidence_seal(
    payload: dict, kind: str
) -> None:
    evidence = _record(payload, "al-alison-code-statutory_text")[kind]
    raw = b"replacement evidence bytes"
    evidence["content_bytes_base64"] = base64.b64encode(raw).decode()
    evidence["content_sha256"] = sha256_bytes(raw)
    _seal_catalog(payload)
    with pytest.raises(DigestMismatchError, match="evidence_digest"):
        evaluate_catalog(payload)


@pytest.mark.parametrize("kind", ["terms", "robots"])
def test_missing_evidence_digest_denies(payload: dict, kind: str) -> None:
    del _record(payload, "al-alison-code-statutory_text")[kind]["evidence_digest_sha256"]
    _seal_catalog(payload)
    with pytest.raises(CatalogSchemaError):
        evaluate_catalog(payload)


@pytest.mark.parametrize("field,value", [("source_id", "ak-akleg-basis"), ("content_scope", "annotations"), ("url", "https://example.invalid/")])
@pytest.mark.parametrize("kind", ["terms", "robots"])
def test_evidence_must_bind_exact_source_scope_and_url(
    payload: dict, field: str, value: str, kind: str
) -> None:
    evidence = _record(payload, "al-alison-code-statutory_text")[kind]
    evidence[field] = value
    _seal_evidence(evidence)
    _seal_catalog(payload)
    with pytest.raises(IdentityError):
        evaluate_catalog(payload)


@pytest.mark.parametrize("byte_field", ["request_bytes_base64", "response_bytes_base64"])
def test_conditional_receipt_bytes_are_independently_rehashed(
    payload: dict, byte_field: str
) -> None:
    receipt = _record(payload, "ak-akleg-basis-statutory_text")["condition_evidence"][0]
    raw = base64.b64decode(receipt[byte_field])
    receipt[byte_field] = base64.b64encode(b"X" + raw[1:]).decode()
    _seal_catalog(payload)
    with pytest.raises(DigestMismatchError):
        evaluate_catalog(payload)


def test_bare_condition_name_never_proves_acquisition(payload: dict) -> None:
    record_id = "ak-akleg-basis-statutory_text"
    _record(payload, record_id)["condition_evidence"] = []
    report = _semantic_denial(payload, record_id)
    decision = _decision(report, record_id)
    assert decision["admitted"] is False
    assert "conditional_evidence_set_mismatch" in decision["reason_codes"]


def test_condition_receipt_must_match_exact_condition(payload: dict) -> None:
    record_id = "ak-akleg-basis-statutory_text"
    receipt = _record(payload, record_id)["condition_evidence"][0]
    receipt["condition_id"] = "caller-claimed-complete"
    _seal_receipt(receipt)
    report = _semantic_denial(payload, record_id)
    assert "conditional_evidence_set_mismatch" in _decision(report, record_id)["reason_codes"]


@pytest.mark.parametrize("field,value", [("source_id", "al-alison-code"), ("content_scope", "annotations")])
def test_condition_receipt_must_match_source_scope(
    payload: dict, field: str, value: str
) -> None:
    receipt = _record(payload, "ak-akleg-basis-statutory_text")["condition_evidence"][0]
    receipt[field] = value
    _seal_receipt(receipt)
    _seal_catalog(payload)
    with pytest.raises(IdentityError):
        evaluate_catalog(payload)


@pytest.mark.parametrize("field", ["request_sha256", "response_sha256", "receipt_digest_sha256"])
def test_missing_conditional_digest_denies(payload: dict, field: str) -> None:
    del _record(payload, "ak-akleg-basis-statutory_text")["condition_evidence"][0][field]
    _seal_catalog(payload)
    with pytest.raises(CatalogSchemaError):
        evaluate_catalog(payload)


@pytest.mark.parametrize("disposition", ["prohibited", "unknown", "unsupported", "quarantined"])
def test_nonadmissible_rights_dispositions_deny_and_suppress(
    payload: dict, disposition: str
) -> None:
    record_id = "al-alison-code-statutory_text"
    _record(payload, record_id)["rights_disposition"] = disposition
    report = _semantic_denial(payload, record_id)
    assert _decision(report, record_id)["admitted"] is False
    assert report["authority_suppressed"] is True
    assert record_id in report["denied_in_scope_record_ids"]


@pytest.mark.parametrize("disposition", ["denied", "unknown", "unavailable"])
def test_robots_denied_unknown_or_unavailable_suppresses(
    payload: dict, disposition: str
) -> None:
    record_id = "al-alison-code-statutory_text"
    _record(payload, record_id)["robots_access_disposition"] = disposition
    report = _semantic_denial(payload, record_id)
    assert f"robots_{disposition}" in _decision(report, record_id)["reason_codes"]
    assert report["authority_suppressed"] is True


def test_conditional_robots_without_receipt_denies(payload: dict) -> None:
    record_id = "al-alison-code-statutory_text"
    _record(payload, record_id)["robots_access_disposition"] = "conditional"
    report = _semantic_denial(payload, record_id)
    assert "conditional_without_requirements" in _decision(report, record_id)["reason_codes"]


@pytest.mark.parametrize("permission", ["redistribution", "derivatives", "archive"])
def test_every_release_operation_is_required(payload: dict, permission: str) -> None:
    record_id = "al-alison-code-statutory_text"
    _record(payload, record_id)["permissions"][permission] = False
    report = _semantic_denial(payload, record_id)
    decision = _decision(report, record_id)
    assert decision["admitted"] is False
    assert permission in decision["reason_codes"]
    assert report["authority_suppressed"] is True


@pytest.mark.parametrize("permission", ["redistribution", "derivatives", "archive"])
def test_missing_release_operation_denies_at_parse(payload: dict, permission: str) -> None:
    del _record(payload, "al-alison-code-statutory_text")["permissions"][permission]
    _seal_catalog(payload)
    with pytest.raises(CatalogSchemaError):
        evaluate_catalog(payload)


@pytest.mark.parametrize("status", ["unreviewed", "rejected", "expired"])
def test_nonreviewed_records_deny(payload: dict, status: str) -> None:
    record_id = "al-alison-code-statutory_text"
    _record(payload, record_id)["review_status"] = status
    report = _semantic_denial(payload, record_id)
    assert f"review_{status}" in _decision(report, record_id)["reason_codes"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("corpus_family", "federal_register"),
        ("dataset_repo_id", "justicedao/ipfs_federal_register"),
        ("source_id", "caller-source"),
        ("content_scope", "annotations"),
        ("source_url", "https://example.invalid/"),
        ("jurisdiction_or_authority", "ZZ"),
    ],
)
def test_wrong_corpus_repository_source_scope_or_authority_denies(
    payload: dict, field: str, value: str
) -> None:
    _record(payload, "al-alison-code-statutory_text")[field] = value
    _seal_catalog(payload)
    with pytest.raises((CatalogSchemaError, IdentityError, FrontierMismatchError)):
        evaluate_catalog(payload)


def test_card_label_cannot_be_authority(payload: dict) -> None:
    record = _record(payload, "al-alison-code-statutory_text")
    record["card_label_is_not_authority"] = False
    record["dataset_card_label"] = "other"
    _seal_catalog(payload)
    with pytest.raises(policy.CardOnlyEvidenceError):
        evaluate_catalog(payload)


@pytest.mark.parametrize("record_id", ["al-alison-code-statutory_text", "or-legislature-ors-annotations"])
def test_deleting_admitted_or_excluded_expected_record_fails_frontier_equality(
    payload: dict, record_id: str
) -> None:
    payload["records"] = [item for item in payload["records"] if item["record_id"] != record_id]
    _remove_admission(payload, record_id)
    _seal_catalog(payload)
    with pytest.raises(FrontierMismatchError):
        evaluate_catalog(payload)


def test_adding_unrecognized_or_duplicate_record_fails_frontier_equality(payload: dict) -> None:
    extra = copy.deepcopy(payload["records"][0])
    extra["record_id"] = "caller-extra-record"
    extra["source_id"] = "caller-extra-source"
    payload["records"].append(extra)
    _seal_catalog(payload)
    with pytest.raises((IdentityError, FrontierMismatchError)):
        evaluate_catalog(payload)
    payload = json.loads(default_fixture_catalog_path().read_bytes())
    duplicate = copy.deepcopy(payload["records"][0])
    duplicate["record_id"] = "duplicate-record-id"
    payload["records"].append(duplicate)
    _seal_catalog(payload)
    with pytest.raises(FrontierMismatchError):
        evaluate_catalog(payload)


def test_admitted_subset_cannot_hide_a_denied_expected_record(payload: dict) -> None:
    record_id = "al-alison-code-statutory_text"
    payload["admitted_record_ids"].remove(record_id)
    _seal_catalog(payload)
    with pytest.raises(RightsAdmissionError, match="exactly equal"):
        evaluate_catalog(payload)


def test_record_id_is_deterministically_bound_to_source_and_scope(payload: dict) -> None:
    record = _record(payload, "al-alison-code-statutory_text")
    old_id = record["record_id"]
    record["record_id"] = "caller-shadow-id"
    payload["admitted_record_ids"] = [
        "caller-shadow-id" if item == old_id else item
        for item in payload["admitted_record_ids"]
    ]
    _seal_catalog(payload)
    with pytest.raises(FrontierMismatchError, match="record_id mismatch"):
        evaluate_catalog(payload)


def test_bare_record_iterable_and_self_declared_frontier_are_not_accepted(payload: dict) -> None:
    catalog = SourceRightsCatalog.from_mapping(payload)
    with pytest.raises(CatalogSchemaError):
        evaluate_catalog(catalog.records)
    with pytest.raises(TypeError):
        frontier_digest_sha256(derive_expected_scope_frontier())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        load_source_rights_catalog(Path("caller.json"))  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "artifact",
    [
        "policy_module_sha256",
        "schema_sha256",
        "spdx_registry_sha256",
        "lcr002_source_catalog_sha256",
        "lcr048_federal_baseline_sha256",
        "expected_scope_frontier_sha256",
    ],
)
def test_missing_or_wrong_artifact_digest_denies(payload: dict, artifact: str) -> None:
    del payload["artifact_digests"][artifact]
    _seal_catalog(payload)
    with pytest.raises(CatalogSchemaError):
        evaluate_catalog(payload)
    payload = json.loads(default_fixture_catalog_path().read_bytes())
    payload["artifact_digests"][artifact] = "0" * 64
    _seal_catalog(payload)
    with pytest.raises((DigestMismatchError, FrontierMismatchError)):
        evaluate_catalog(payload)


def test_root_frontier_digest_cannot_be_self_declared(payload: dict) -> None:
    payload["expected_scope_frontier_sha256"] = "0" * 64
    payload["artifact_digests"]["expected_scope_frontier_sha256"] = "0" * 64
    _seal_catalog(payload)
    with pytest.raises((DigestMismatchError, FrontierMismatchError)):
        evaluate_catalog(payload)


def test_mutated_policy_bytes_with_unchanged_catalog_digest_binding_deny(
    payload: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mutated = tmp_path / "policy.py"
    mutated.write_bytes(policy.default_policy_module_path().read_bytes() + b"\n# mutation\n")
    monkeypatch.setattr(policy, "default_policy_module_path", lambda: mutated)
    with pytest.raises(DigestMismatchError):
        evaluate_catalog(payload)


def test_mutated_schema_bytes_with_unchanged_catalog_digest_binding_deny(
    payload: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mutated = tmp_path / "schema.json"
    mutated.write_bytes(policy.default_schema_path().read_bytes() + b" ")
    monkeypatch.setattr(policy, "default_schema_path", lambda: mutated)
    with pytest.raises(DigestMismatchError):
        evaluate_catalog(payload)


@pytest.mark.parametrize("source", ["state", "federal"])
def test_mutated_canonical_frontier_evidence_bytes_deny_before_derivation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    if source == "state":
        original = policy.default_state_source_catalog_path()
        attribute = "default_state_source_catalog_path"
    else:
        original = policy.default_federal_baseline_path()
        attribute = "default_federal_baseline_path"
    mutated = tmp_path / original.name
    mutated.write_bytes(original.read_bytes() + b" ")
    monkeypatch.setattr(policy, attribute, lambda: mutated)
    with pytest.raises(DigestMismatchError):
        derive_expected_scope_frontier()


def test_exact_ninety_day_boundary_is_accepted(payload: dict) -> None:
    evidence = _record(payload, "al-alison-code-statutory_text")["terms"]
    evidence["verifier_observed_at"] = "2026-05-12T12:00:00Z"
    _seal_evidence(evidence)
    _seal_catalog(payload)
    assert evaluate_scope_rights(payload, "al-alison-code-statutory_text").admitted is True


@pytest.mark.parametrize(
    "kind,timestamp",
    [
        ("terms", "2026-05-12T11:59:59.999999Z"),
        ("robots", "2026-08-10T12:00:00.000001Z"),
    ],
)
def test_evidence_one_microsecond_stale_or_future_denies(
    payload: dict, kind: str, timestamp: str
) -> None:
    record_id = "al-alison-code-statutory_text"
    evidence = _record(payload, record_id)[kind]
    evidence["verifier_observed_at"] = timestamp
    _seal_evidence(evidence)
    report = _semantic_denial(payload, record_id)
    assert _decision(report, record_id)["reason_codes"][0] in {
        "stale_evidence",
        "future_timestamp",
    }


@pytest.mark.parametrize(
    "field,timestamp",
    [
        ("reviewed_at", "2026-05-12T11:59:59.999999Z"),
        ("reviewed_at", "2026-08-10T12:00:00.000001Z"),
        ("sealed_at", "2026-05-12T11:59:59.999999Z"),
        ("sealed_at", "2026-08-10T12:00:00.000001Z"),
    ],
)
def test_review_and_record_seal_stale_or_future_deny(
    payload: dict, field: str, timestamp: str
) -> None:
    record_id = "al-alison-code-statutory_text"
    _record(payload, record_id)[field] = timestamp
    report = _semantic_denial(payload, record_id)
    assert _decision(report, record_id)["reason_codes"][0] in {
        "stale_evidence",
        "future_timestamp",
    }


@pytest.mark.parametrize(
    "kind,timestamp,reason",
    [
        ("terms", "2026-08-06T00:00:00Z", "terms_after_review"),
        ("robots", "2026-08-06T00:00:00Z", "robots_after_review"),
    ],
)
def test_evidence_observed_after_review_denies(
    payload: dict, kind: str, timestamp: str, reason: str
) -> None:
    record_id = "al-alison-code-statutory_text"
    evidence = _record(payload, record_id)[kind]
    evidence["verifier_observed_at"] = timestamp
    _seal_evidence(evidence)
    report = _semantic_denial(payload, record_id)
    assert reason in _decision(report, record_id)["reason_codes"]


def test_condition_evidence_observed_after_review_denies(payload: dict) -> None:
    record_id = "ak-akleg-basis-statutory_text"
    receipt = _record(payload, record_id)["condition_evidence"][0]
    receipt["verifier_observed_at"] = "2026-08-05T12:00:00.000001Z"
    _seal_receipt(receipt)
    report = _semantic_denial(payload, record_id)
    assert "condition_evidence_after_review" in _decision(report, record_id)["reason_codes"]


def test_review_after_record_seal_denies(payload: dict) -> None:
    record_id = "al-alison-code-statutory_text"
    _record(payload, record_id)["reviewed_at"] = "2026-08-08T12:00:00.000001Z"
    report = _semantic_denial(payload, record_id)
    assert "review_after_record_seal" in _decision(report, record_id)["reason_codes"]


def test_record_after_catalog_seal_denies(payload: dict) -> None:
    record_id = "al-alison-code-statutory_text"
    _record(payload, record_id)["sealed_at"] = "2026-08-09T12:00:00.000001Z"
    report = _semantic_denial(payload, record_id)
    assert "record_after_catalog_seal" in _decision(report, record_id)["reason_codes"]


@pytest.mark.parametrize("timestamp", ["2026-05-12T11:59:59.999999Z", "2026-08-10T12:00:00.000001Z"])
def test_catalog_seal_stale_or_future_denies_every_admission(
    payload: dict, timestamp: str
) -> None:
    payload["sealed_at"] = timestamp
    payload["admitted_record_ids"] = []
    _seal_catalog(payload)
    report = evaluate_catalog(payload)
    assert report["admitted_count"] == 0
    assert report["authority_suppressed"] is True


def test_callers_cannot_widen_time_or_disable_verification(payload: dict) -> None:
    with pytest.raises(TypeError):
        evaluate_catalog(payload, now=policy.fixture_verifier_now())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        evaluate_catalog(payload, max_evidence_age=policy.MAX_EVIDENCE_AGE * 2)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        evaluate_catalog(payload, max_future_skew=policy.MAX_EVIDENCE_AGE)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        evaluate_catalog(payload, verify_digests=False)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        normalize_spdx("Caller-1.0", registry=object())  # type: ignore[call-arg]


def test_every_public_rights_helper_rejects_invalid_complete_catalog(payload: dict) -> None:
    del payload["producer"]
    _seal_catalog(payload)
    record_id = "al-alison-code-statutory_text"
    calls = (
        lambda: evaluate_catalog(payload),
        lambda: evaluate_scope_rights(payload, record_id),
        lambda: require_scope_rights(payload, record_id),
        lambda: admitted_records(payload),
        lambda: build_fixture_compliance_projection(payload),
    )
    for call in calls:
        with pytest.raises(LegalSourceRightsPolicyError):
            call()


def test_denied_in_scope_record_is_suppressed_by_every_selector(payload: dict) -> None:
    record_id = "al-alison-code-statutory_text"
    _record(payload, record_id)["permissions"]["archive"] = False
    report = _semantic_denial(payload, record_id)
    assert report["authority_suppressed"] is True
    assert evaluate_scope_rights(payload, record_id).admitted is False
    with pytest.raises(RightsAdmissionError):
        require_scope_rights(payload, record_id)
    assert record_id not in {record.record_id for record in admitted_records(payload)}


def test_fixture_path_cannot_be_substituted_as_live_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy, "default_live_catalog_path", default_fixture_catalog_path)
    with pytest.raises(LiveEvidenceRequiredError, match="wrong identity tuple"):
        require_live_source_evidence()


def test_fresh_exact_live_catalog_is_the_only_authorizing_positive(
    payload: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = _as_fresh_live(payload)
    caller_report = evaluate_catalog(live)
    assert caller_report["authorizing_for_publication"] is False
    assert all(decision["authorizing"] is False for decision in caller_report["decisions"])
    path = tmp_path / "legal_source_rights_catalog.json"
    path.write_text(json.dumps(live, sort_keys=True))
    monkeypatch.setattr(policy, "default_live_catalog_path", lambda: path)
    report = require_live_source_evidence()
    assert report["authorizing_for_publication"] is True
    assert report["authority_suppressed"] is False
    assert report["admitted_count"] == 52
    assert all(
        decision["authorizing"] is decision["admitted"]
        for decision in report["decisions"]
    )


def test_denied_release_scope_suppresses_otherwise_valid_live_authority(
    payload: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record_id = "al-alison-code-statutory_text"
    live = _as_fresh_live(payload)
    _record(live, record_id)["permissions"]["archive"] = False
    _remove_admission(live, record_id)
    _seal_catalog(live)
    path = tmp_path / "legal_source_rights_catalog.json"
    path.write_text(json.dumps(live, sort_keys=True))
    monkeypatch.setattr(policy, "default_live_catalog_path", lambda: path)
    with pytest.raises(LiveEvidenceRequiredError, match="not authoritative"):
        require_live_source_evidence()


def test_live_gate_has_no_path_or_clock_arguments() -> None:
    assert tuple(inspect.signature(require_live_source_evidence).parameters) == ()
    with pytest.raises(TypeError):
        require_live_source_evidence(catalog_path=Path("caller.json"))  # type: ignore[call-arg]


def test_cli_rejects_path_clock_subset_and_digest_bypass_flags() -> None:
    import importlib.util

    path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ops"
        / "legal_data"
        / "audit_legal_source_rights.py"
    )
    spec = importlib.util.spec_from_file_location("lcr082_audit_fail_closed", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for flag in (
        "--catalog",
        "--schema",
        "--registry",
        "--now",
        "--max-evidence-age",
        "--max-future-skew",
        "--verify-digests",
        "--record-id",
        "--proven-condition",
    ):
        with pytest.raises(SystemExit):
            module.build_parser().parse_args(["--fixture-only", "--check", flag, "caller"])


def test_fixture_loader_rejects_duplicate_json_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    malformed = tmp_path / "fixture.json"
    malformed.write_bytes(b'{"schema_version":"one","schema_version":"two"}')
    monkeypatch.setattr(policy, "default_fixture_catalog_path", lambda: malformed)
    with pytest.raises(CatalogSchemaError, match="duplicate JSON key"):
        policy.load_catalog_payload()


@pytest.mark.parametrize("token", [b"NaN", b"Infinity", b"-Infinity", b"1e9999"])
def test_fixture_loader_rejects_nonfinite_json_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, token: bytes
) -> None:
    malformed = tmp_path / "fixture.json"
    malformed.write_bytes(b'{"value":' + token + b"}")
    monkeypatch.setattr(policy, "default_fixture_catalog_path", lambda: malformed)
    with pytest.raises(CatalogSchemaError, match="non-finite"):
        policy.load_catalog_payload()


def test_fixture_loader_rejects_escaped_unicode_surrogate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    malformed = tmp_path / "fixture.json"
    malformed.write_bytes(b'{"value":"\\ud800"}')
    monkeypatch.setattr(policy, "default_fixture_catalog_path", lambda: malformed)
    with pytest.raises(CatalogSchemaError, match="surrogate"):
        policy.load_catalog_payload()


def test_registry_loader_rejects_duplicate_keys_before_semantic_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = policy.default_spdx_registry_path().read_bytes()
    malformed = tmp_path / "registry.json"
    malformed.write_bytes(
        original.replace(
            b"{\n",
            b'{\n  "schema_version": "duplicate",\n',
            1,
        )
    )
    monkeypatch.setattr(policy, "default_spdx_registry_path", lambda: malformed)
    with pytest.raises(CatalogSchemaError, match="duplicate JSON key"):
        policy.load_spdx_registry()


def test_registry_loader_rejects_nonfinite_surrogate_and_wrong_root_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    malformed = tmp_path / "registry.json"
    monkeypatch.setattr(policy, "default_spdx_registry_path", lambda: malformed)
    for raw, match in (
        (b'{"value":NaN}', "non-finite"),
        (b'{"value":"\\udfff"}', "surrogate"),
        (b"[]", "exact JSON object"),
    ):
        malformed.write_bytes(raw)
        with pytest.raises(CatalogSchemaError, match=match):
            policy.load_spdx_registry()


def test_frontier_loader_strictly_rejects_duplicate_json_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = policy.default_state_source_catalog_path().read_bytes()
    malformed_bytes = original.replace(
        b"{\n",
        b'{\n  "schema_version": "duplicate",\n',
        1,
    )
    malformed = tmp_path / "state.json"
    malformed.write_bytes(malformed_bytes)
    monkeypatch.setattr(policy, "default_state_source_catalog_path", lambda: malformed)
    monkeypatch.setattr(policy, "CANONICAL_LCR002_SHA256", sha256_bytes(malformed_bytes))
    with pytest.raises(CatalogSchemaError, match="duplicate JSON key"):
        derive_expected_scope_frontier()


@pytest.mark.parametrize(
    "suffix,match",
    [
        (b'{"value":NaN}', "non-finite"),
        (b'{"value":"\\ud800"}', "surrogate"),
        (b"[]", "exact JSON object"),
    ],
)
def test_frontier_loader_rejects_nonfinite_surrogate_and_wrong_root_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: bytes,
    match: str,
) -> None:
    malformed = tmp_path / "state.json"
    malformed.write_bytes(suffix)
    monkeypatch.setattr(policy, "default_state_source_catalog_path", lambda: malformed)
    monkeypatch.setattr(policy, "CANONICAL_LCR002_SHA256", sha256_bytes(suffix))
    with pytest.raises(CatalogSchemaError, match=match):
        derive_expected_scope_frontier()


@pytest.mark.parametrize("target_kind", ["fixture", "registry", "schema", "state", "policy"])
def test_canonical_inputs_reject_symlink_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_kind: str,
) -> None:
    cases = {
        "fixture": (
            policy.default_fixture_catalog_path,
            "default_fixture_catalog_path",
            policy.load_catalog_payload,
        ),
        "registry": (
            policy.default_spdx_registry_path,
            "default_spdx_registry_path",
            policy.load_spdx_registry,
        ),
        "schema": (
            policy.default_schema_path,
            "default_schema_path",
            policy.load_schema_document,
        ),
        "state": (
            policy.default_state_source_catalog_path,
            "default_state_source_catalog_path",
            derive_expected_scope_frontier,
        ),
        "policy": (
            policy.default_policy_module_path,
            "default_policy_module_path",
            policy.compute_artifact_digests,
        ),
    }
    path_function, attribute, action = cases[target_kind]
    link = tmp_path / f"{target_kind}.link"
    link.symlink_to(path_function())
    monkeypatch.setattr(policy, attribute, lambda: link)
    with pytest.raises(CatalogSchemaError, match="symlink"):
        action()


def test_single_descriptor_reader_rejects_path_replacement_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "input.json"
    target.write_bytes(b"{}")
    real_stat = policy.os.stat
    calls = 0

    def racing_stat(path: object, *, follow_symlinks: bool = True):
        nonlocal calls
        observed = real_stat(path, follow_symlinks=follow_symlinks)
        calls += 1
        if calls == 2:
            fields = list(observed)
            fields[1] += 1
            return policy.os.stat_result(fields)
        return observed

    monkeypatch.setattr(policy.os, "stat", racing_stat)
    with pytest.raises(CatalogSchemaError, match="changed during read"):
        policy._read_regular_file_once(target, context="race-test")


def test_direct_nonfinite_or_surrogate_mapping_never_reaches_evaluator(payload: dict) -> None:
    payload["description"] = float("nan")
    with pytest.raises(CatalogSchemaError, match="canonical JSON"):
        evaluate_catalog(payload)
    payload = json.loads(default_fixture_catalog_path().read_bytes())
    payload["description"] = "\ud800"
    with pytest.raises(CatalogSchemaError, match="canonical JSON"):
        evaluate_catalog(payload)


def test_fixture_only_check_cannot_return_authorizing() -> None:
    import importlib.util

    path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ops"
        / "legal_data"
        / "audit_legal_source_rights.py"
    )
    spec = importlib.util.spec_from_file_location("lcr082_fixture_authority", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.run_fixture_check()
    assert report["status"] == "passed"
    assert report["fixture_only_non_authorizing"] is True
    assert report["authorizing_for_publication"] is False
    assert all(decision["authorizing"] is False for decision in report["decisions"])


def test_fixture_check_rejects_even_whitespace_only_byte_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib.util

    mutated = tmp_path / "fixture.json"
    mutated.write_bytes(default_fixture_catalog_path().read_bytes() + b" ")
    monkeypatch.setattr(policy, "default_fixture_catalog_path", lambda: mutated)
    path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ops"
        / "legal_data"
        / "audit_legal_source_rights.py"
    )
    spec = importlib.util.spec_from_file_location("lcr082_fixture_bytes", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(module.AuditError, match="fixture bytes differ"):
        module.run_fixture_check()
