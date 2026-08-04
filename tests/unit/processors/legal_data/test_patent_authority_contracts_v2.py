"""Unit tests for patent authority contracts v2 (PATLAW-127).

Covers independent authority kind/tier/rendition dimensions, content-addressed
receipts, temporal roles, and the fail-closed parser-input acquisition gate.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from ipfs_datasets_py.processors.legal_data.patent_authority_contracts_v2 import (
    ACCEPTANCE_AUTHORITY_CLASSES,
    AcquisitionOutcome,
    AcquisitionOutcomeKind,
    AcquisitionReceipt,
    AuthorityDimensionCollapseError,
    AuthorityIdentityV2,
    AuthorityKind,
    AuthorityTier,
    ContentAddress,
    DocumentPackageGranuleIds,
    HardCodedLatestEditionError,
    MissingAcquisitionOutcomeError,
    MissingRequiredIdentityFieldError,
    PARSER_ADMISSIBLE_OUTCOMES,
    ParserInputEnvelope,
    ReleasePointExclusions,
    RenditionLegalStatus,
    SignatureFixityEvidence,
    TemporalRole,
    TemporalRoleSet,
    VerificationState,
    acceptance_class_for_kind,
    assert_dimensions_independent,
    canonical_json_bytes,
    content_address_bytes,
    default_tier_for_kind,
    non_collapsible_acceptance_matrix,
    require_acquisition_outcome,
)


RETRIEVED = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)


def _body(text: str = "<section>37 CFR 1.56</section>") -> bytes:
    return text.encode("utf-8")


def _fixity_for(data: bytes) -> SignatureFixityEvidence:
    addr = content_address_bytes(data)
    return SignatureFixityEvidence.from_content_address(addr)


def _identity(
    *,
    kind: AuthorityKind = AuthorityKind.PROMULGATED_REGULATION,
    tier: AuthorityTier | None = None,
    rendition: RenditionLegalStatus = RenditionLegalStatus.OFFICIAL_ELECTRONIC,
    body: bytes | None = None,
) -> AuthorityIdentityV2:
    raw = body if body is not None else _body()
    addr = content_address_bytes(raw)
    resolved_tier = tier if tier is not None else default_tier_for_kind(kind)
    return AuthorityIdentityV2(
        provider="govinfo",
        source_id="cfr-title-37-2024",
        artifact_sha256=addr.sha256,
        artifact_cid=addr.cid,
        source_url="https://www.govinfo.gov/content/pkg/CFR-2024-title37-vol1",
        retrieved_at=RETRIEVED,
        authority_kind=kind,
        authority_tier=resolved_tier,
        rendition_legal_status=rendition,
        jurisdiction="US",
        media_type="application/xml",
        release_point=ReleasePointExclusions(
            edition_or_release_point="CFR-2024-title37-vol1",
            exclusions=("appendix-reserved",),
        ),
        document_ids=DocumentPackageGranuleIds(
            package_id="CFR-2024-title37-vol1",
            granule_id="CFR-2024-title37-vol1-sec1-56",
            collection_code="CFR",
            title_number="37",
            part_or_section="1.56",
        ),
        fixity=SignatureFixityEvidence.from_content_address(addr),
        temporal=TemporalRoleSet(
            assignments={
                TemporalRole.EDITION.value: "2024-07-01",
                TemporalRole.EFFECTIVE.value: "2024-07-01",
                TemporalRole.RETRIEVAL.value: "2026-08-03T12:00:00Z",
            }
        ),
        title="Duty of disclosure",
        citation="37 CFR 1.56",
    )


def _fetched_outcome(body: bytes | None = None) -> AcquisitionOutcome:
    raw = body if body is not None else _body()
    content = content_address_bytes(raw)
    receipt = AcquisitionReceipt(
        endpoint="https://www.govinfo.gov/content/pkg/CFR-2024-title37-vol1",
        retrieved_at=RETRIEVED,
        outcome_kind=AcquisitionOutcomeKind.FETCHED,
        response_status=200,
        sanitized_request={"method": "GET", "url": "https://www.govinfo.gov/x"},
        content=content,
        media_type="application/xml",
        etag='"v1"',
        source_timestamp="Mon, 01 Jul 2024 00:00:00 GMT",
    )
    return AcquisitionOutcome(
        kind=AcquisitionOutcomeKind.FETCHED,
        receipt=receipt,
        body=raw,
        network_used=True,
    )


# ---------------------------------------------------------------------------
# Non-collapsible kind / tier / rendition dimensions
# ---------------------------------------------------------------------------


def test_six_acceptance_classes_are_distinct_and_non_collapsible() -> None:
    matrix = non_collapsible_acceptance_matrix()
    assert set(matrix) == ACCEPTANCE_AUTHORITY_CLASSES
    assert len(matrix) == 6

    kinds = {row["authority_kind"] for row in matrix.values()}
    tiers = {row["authority_tier"] for row in matrix.values()}
    classes = {row["acceptance_class"] for row in matrix.values()}

    assert classes == ACCEPTANCE_AUTHORITY_CLASSES
    # Kinds remain distinct across the six representatives.
    assert len(kinds) == 6
    # Tiers must not collapse every class into a single shared tier token.
    assert len(tiers) >= 4

    # Round-trip each representative as an identity; acceptance_class stable.
    for cls, row in matrix.items():
        identity = _identity(
            kind=AuthorityKind(row["authority_kind"]),
            tier=AuthorityTier(row["authority_tier"]),
            rendition=RenditionLegalStatus(row["rendition_legal_status"]),
        )
        assert identity.acceptance_class == cls
        assert identity.authority_kind.value == row["authority_kind"]
        assert identity.authority_tier.value == row["authority_tier"]
        # Kind is not equal to tier string — independent fields.
        assert identity.authority_kind.value != identity.authority_tier.value


def test_statute_regulation_adjudicatory_guidance_editorial_candidate_separate() -> None:
    samples = [
        (
            AuthorityKind.CODIFIED_STATUTE,
            AuthorityTier.OFFICIAL_BASE,
            RenditionLegalStatus.OFFICIAL_SOURCE_ARTIFACT,
            "statute",
        ),
        (
            AuthorityKind.PROMULGATED_REGULATION,
            AuthorityTier.OFFICIAL_BASE,
            RenditionLegalStatus.OFFICIAL_ELECTRONIC,
            "regulation",
        ),
        (
            AuthorityKind.BINDING_ADJUDICATORY_AUTHORITY,
            AuthorityTier.OFFICIAL_CHANGE,
            RenditionLegalStatus.OFFICIAL_ELECTRONIC,
            "adjudicatory_authority",
        ),
        (
            AuthorityKind.OFFICIAL_AGENCY_GUIDANCE,
            AuthorityTier.GUIDANCE,
            RenditionLegalStatus.OFFICIAL_ELECTRONIC,
            "guidance",
        ),
        (
            AuthorityKind.UNOFFICIAL_EDITORIAL_AID,
            AuthorityTier.UNOFFICIAL_CURRENT,
            RenditionLegalStatus.UNOFFICIAL_EDITORIAL_PRESENTATION,
            "editorial_aid",
        ),
        (
            AuthorityKind.EXTRACTED_CANDIDATE,
            AuthorityTier.CANDIDATE,
            RenditionLegalStatus.CANDIDATE_ONLY,
            "extracted_candidate",
        ),
    ]
    seen_classes: set[str] = set()
    payloads: list[dict] = []
    for kind, tier, rendition, expected_class in samples:
        kind_c, tier_c, rend_c = assert_dimensions_independent(
            authority_kind=kind,
            authority_tier=tier,
            rendition_legal_status=rendition,
        )
        assert acceptance_class_for_kind(kind_c) == expected_class
        seen_classes.add(expected_class)
        payloads.append(
            {
                "kind": kind_c.value,
                "tier": tier_c.value,
                "rendition": rend_c.value,
                "class": expected_class,
            }
        )
    assert seen_classes == ACCEPTANCE_AUTHORITY_CLASSES
    # Collapsing all kinds into one tier would make all tier values identical;
    # prove at least guidance and official-base remain distinct.
    tier_values = {p["tier"] for p in payloads}
    assert AuthorityTier.GUIDANCE.value in tier_values
    assert AuthorityTier.OFFICIAL_BASE.value in tier_values
    assert AuthorityTier.CANDIDATE.value in tier_values


def test_guidance_cannot_collapse_to_official_base_tier() -> None:
    with pytest.raises(AuthorityDimensionCollapseError):
        assert_dimensions_independent(
            authority_kind=AuthorityKind.OFFICIAL_AGENCY_GUIDANCE,
            authority_tier=AuthorityTier.OFFICIAL_BASE,
            rendition_legal_status=RenditionLegalStatus.OFFICIAL_ELECTRONIC,
        )


def test_editorial_aid_cannot_collapse_to_official_tier() -> None:
    with pytest.raises(AuthorityDimensionCollapseError):
        assert_dimensions_independent(
            authority_kind=AuthorityKind.UNOFFICIAL_EDITORIAL_AID,
            authority_tier=AuthorityTier.OFFICIAL_BASE,
            rendition_legal_status=RenditionLegalStatus.UNOFFICIAL_EDITORIAL_PRESENTATION,
        )


def test_extracted_candidate_cannot_wear_official_rendition() -> None:
    with pytest.raises(AuthorityDimensionCollapseError):
        assert_dimensions_independent(
            authority_kind=AuthorityKind.EXTRACTED_CANDIDATE,
            authority_tier=AuthorityTier.CANDIDATE,
            rendition_legal_status=RenditionLegalStatus.OFFICIAL_SOURCE_ARTIFACT,
        )


def test_default_tier_for_kind_is_recommendation_not_identity() -> None:
    for kind in AuthorityKind:
        tier = default_tier_for_kind(kind)
        assert isinstance(tier, AuthorityTier)
        # Kind string and tier string remain different vocabularies.
        assert kind.value != tier.value


# ---------------------------------------------------------------------------
# Content addressing
# ---------------------------------------------------------------------------


def test_content_address_bytes_stable_and_cid_present() -> None:
    data = b"hello-authority-bytes"
    a = content_address_bytes(data)
    b = content_address_bytes(data)
    assert a == b
    assert a.sha256 == hashlib.sha256(data).hexdigest()
    assert a.byte_size == len(data)
    assert a.cid.startswith("baf") or a.cid.startswith("sha256:")
    again = ContentAddress.from_bytes(data)
    assert again.sha256 == a.sha256
    assert again.cid == a.cid


def test_acquisition_receipt_is_content_addressed() -> None:
    raw = _body()
    content = content_address_bytes(raw)
    receipt = AcquisitionReceipt(
        endpoint="https://www.ecfr.gov/api/versioner/v1/full/2024-07-01/title-37.xml",
        retrieved_at=RETRIEVED,
        outcome_kind=AcquisitionOutcomeKind.FETCHED,
        response_status=200,
        content=content,
        sanitized_request={"method": "GET"},
        etag='"abc"',
        media_type="application/xml",
    )
    assert len(receipt.receipt_sha256) == 64
    assert receipt.receipt_cid
    # Rebuilding from dict recomputes the same digests.
    rebuilt = AcquisitionReceipt.from_dict(receipt.to_dict())
    assert rebuilt.receipt_sha256 == receipt.receipt_sha256
    assert rebuilt.receipt_cid == receipt.receipt_cid
    # Digests address the payload excluding the digest fields themselves.
    addr = receipt.content_address()
    assert addr.sha256 == receipt.receipt_sha256
    assert addr.cid == receipt.receipt_cid


def test_acquisition_outcome_body_must_match_receipt_content() -> None:
    raw = _body()
    content = content_address_bytes(raw)
    receipt = AcquisitionReceipt(
        endpoint="https://www.govinfo.gov/x",
        retrieved_at=RETRIEVED,
        outcome_kind=AcquisitionOutcomeKind.FETCHED,
        response_status=200,
        content=content,
    )
    ok = AcquisitionOutcome(
        kind=AcquisitionOutcomeKind.FETCHED, receipt=receipt, body=raw
    )
    assert ok.is_parser_admissible
    with pytest.raises(Exception):
        AcquisitionOutcome(
            kind=AcquisitionOutcomeKind.FETCHED,
            receipt=receipt,
            body=b"tampered-bytes",
        )


# ---------------------------------------------------------------------------
# Identity + temporal roles + release point
# ---------------------------------------------------------------------------


def test_authority_identity_round_trip_and_content_address() -> None:
    identity = _identity()
    payload = identity.to_dict()
    assert payload["schema_version"]
    assert payload["authority_kind"] == AuthorityKind.PROMULGATED_REGULATION.value
    assert payload["release_point_exclusions"]["exclusions"] == ["appendix-reserved"]
    assert payload["document_package_granule_ids"]["package_id"]
    assert payload["signature_or_fixity_evidence"]["content_sha256"]
    assert payload["temporal_roles"][TemporalRole.RETRIEVAL.value]
    restored = AuthorityIdentityV2.from_dict(payload)
    assert restored.to_dict() == identity.to_dict()
    assert restored.content_address().sha256 == identity.content_address().sha256


def test_hard_coded_latest_release_point_rejected() -> None:
    with pytest.raises(HardCodedLatestEditionError):
        ReleasePointExclusions(edition_or_release_point="latest")


def test_missing_required_identity_fields_fail_closed() -> None:
    with pytest.raises(MissingRequiredIdentityFieldError):
        AuthorityIdentityV2.from_dict(
            {
                "provider": "govinfo",
                # source_id missing
                "artifact_sha256": "a" * 64,
                "source_url": "https://www.govinfo.gov/x",
                "retrieved_at": "2026-08-03T12:00:00Z",
                "authority_kind": "promulgated_regulation",
                "authority_tier": "official-base",
                "rendition_legal_status": "official_electronic",
                "jurisdiction": "US",
                "media_type": "application/xml",
            }
        )


def test_temporal_role_set_keeps_roles_distinct() -> None:
    roles = TemporalRoleSet(
        assignments={
            "edition": "2024-07-01",
            "effective": "2024-08-01",
            "retrieval": "2026-08-03T12:00:00Z",
            "upstream_last_modified": "2024-06-15T00:00:00Z",
        }
    )
    assert roles.get(TemporalRole.EDITION) == "2024-07-01"
    assert roles.get(TemporalRole.EFFECTIVE) == "2024-08-01"
    assert roles.get(TemporalRole.EDITION) != roles.get(TemporalRole.EFFECTIVE)
    full = roles.to_dict()
    # All known roles are present keys (absent -> null).
    assert set(full) == {r.value for r in TemporalRole}
    roles.require_roles(TemporalRole.EDITION, TemporalRole.RETRIEVAL)
    with pytest.raises(MissingRequiredIdentityFieldError):
        roles.require_roles(TemporalRole.ENACTMENT)


# ---------------------------------------------------------------------------
# Parser input gate — never without acquisition outcome
# ---------------------------------------------------------------------------


def test_parser_input_requires_acquisition_outcome() -> None:
    with pytest.raises(MissingAcquisitionOutcomeError):
        ParserInputEnvelope.admit(None)
    with pytest.raises(MissingAcquisitionOutcomeError):
        require_acquisition_outcome(None)
    with pytest.raises(MissingAcquisitionOutcomeError):
        ParserInputEnvelope.from_dict({})


def test_parser_input_rejects_throttled_and_unavailable_outcomes() -> None:
    for kind in (
        AcquisitionOutcomeKind.THROTTLED,
        AcquisitionOutcomeKind.UNAVAILABLE,
        AcquisitionOutcomeKind.TRUNCATED,
        AcquisitionOutcomeKind.MISLABELED,
    ):
        receipt = AcquisitionReceipt(
            endpoint="https://www.ecfr.gov/x",
            retrieved_at=RETRIEVED,
            outcome_kind=kind,
            response_status=429 if kind is AcquisitionOutcomeKind.THROTTLED else 503,
            error_code=kind.value,
        )
        outcome = AcquisitionOutcome(kind=kind, receipt=receipt, body=None)
        assert not outcome.is_parser_admissible
        with pytest.raises(MissingAcquisitionOutcomeError):
            ParserInputEnvelope.admit(outcome)
        with pytest.raises(MissingAcquisitionOutcomeError):
            require_acquisition_outcome(outcome)


def test_parser_input_admits_fetched_outcome_with_bytes() -> None:
    outcome = _fetched_outcome()
    assert outcome.kind in PARSER_ADMISSIBLE_OUTCOMES
    envelope = ParserInputEnvelope.admit(
        outcome,
        authority=_identity(body=outcome.body),
        parser_name="ecfr_title37",
    )
    assert envelope.body == outcome.body
    assert envelope.content_address is not None
    assert envelope.content_address.sha256 == outcome.receipt.content.sha256
    payload = envelope.to_dict()
    assert payload["acquisition"]["kind"] == "fetched"
    assert payload["authority"]["authority_kind"] == "promulgated_regulation"


def test_parser_input_admits_unchanged_with_cached_body() -> None:
    raw = _body("cached")
    content = content_address_bytes(raw)
    receipt = AcquisitionReceipt(
        endpoint="https://www.govinfo.gov/x",
        retrieved_at=RETRIEVED,
        outcome_kind=AcquisitionOutcomeKind.UNCHANGED,
        response_status=304,
        content=content,
        cache_hit=True,
        conditional_request=True,
    )
    outcome = AcquisitionOutcome(
        kind=AcquisitionOutcomeKind.UNCHANGED,
        receipt=receipt,
        body=raw,
        network_used=True,
    )
    envelope = ParserInputEnvelope.admit(outcome, parser_name="govinfo")
    assert envelope.body == raw


def test_verification_state_independent_of_kind() -> None:
    identity = _identity()
    assert identity.verification_state is VerificationState.UNVERIFIED
    # HTTP success does not imply verified.
    payload = identity.to_dict()
    payload["verification_state"] = "verified"
    verified = AuthorityIdentityV2.from_dict(payload)
    assert verified.verification_state is VerificationState.VERIFIED
    assert verified.authority_kind is AuthorityKind.PROMULGATED_REGULATION


def test_canonical_json_is_deterministic() -> None:
    identity = _identity()
    a = canonical_json_bytes(identity.to_dict())
    b = canonical_json_bytes(identity.to_dict())
    assert a == b
    assert a == a  # stable
