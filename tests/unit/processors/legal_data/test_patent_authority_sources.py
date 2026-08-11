"""Unit tests for the patent authority source and receipt registry."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    SCHEMA_VERSION,
    AuthoritySourceRecord,
    AuthoritySourceRegistry,
    AuthoritySourceRegistryError,
    AuthorityTier,
    ArtifactIdentity,
    HardCodedLatestEditionError,
    IdentityRole,
    MissingAuthorityTierError,
    RetryCachePolicy,
    SourceReceipt,
    VerificationState,
    build_fixture_record,
    canonical_json_dumps,
    reject_hard_coded_latest,
)

_OFFICIAL_SHA = "a" * 64
_DERIVED_SHA = "b" * 64
_ALT_SHA = "c" * 64


def _official_identity(**overrides):
    base = dict(
        provider="govinfo",
        source_id="cfr-title-37-2024-official",
        artifact_sha256=_OFFICIAL_SHA,
        source_url="https://www.govinfo.gov/content/pkg/CFR-2024-title37-vol1/xml/CFR-2024-title37-vol1.xml",
        role=IdentityRole.OFFICIAL_ARTIFACT,
    )
    base.update(overrides)
    return ArtifactIdentity(**base)


def _derived_identity(**overrides):
    base = dict(
        provider="ecfr",
        source_id="cfr-title-37-presentation",
        artifact_sha256=_DERIVED_SHA,
        source_url="https://www.ecfr.gov/current/title-37",
        role=IdentityRole.DERIVED_PRESENTATION,
    )
    base.update(overrides)
    return ArtifactIdentity(**base)


def _receipt(**overrides):
    base = dict(
        endpoint="https://www.govinfo.gov/content/pkg/CFR-2024-title37-vol1/xml/CFR-2024-title37-vol1.xml",
        retrieved_at="2024-07-15T18:30:00Z",
        response_status=200,
        sanitized_request={"method": "GET", "headers": {"Accept": "application/xml"}},
        upstream_id="CFR-2024-title37-vol1",
        upstream_last_modified="Mon, 01 Jul 2024 00:00:00 GMT",
        etag='"abc123"',
        retry_count=1,
        cache_hit=False,
        content_sha256=_OFFICIAL_SHA,
    )
    base.update(overrides)
    return SourceReceipt(**base)


def _base_record(**overrides):
    base = dict(
        source_key="us-cfr-37-2024-base",
        authority_tier=AuthorityTier.OFFICIAL_BASE,
        collection="CFR",
        jurisdiction="US",
        title="37",
        citation="37 C.F.R.",
        edition="2024",
        version="2024-title37-vol1",
        release_point="CFR-2024-title37-vol1",
        date_issued=date(2024, 7, 1),
        publication_date=date(2024, 7, 1),
        effective_start=date(2024, 7, 1),
        official_artifact=_official_identity(),
        derived_presentation=_derived_identity(),
        receipt=_receipt(),
        verification_state=VerificationState.VERIFIED,
        signature_present=True,
        signature_valid=True,
        signature_algorithm="GPO-authenticity",
        retry_cache_policy=RetryCachePolicy(max_attempts=3),
    )
    base.update(overrides)
    return AuthoritySourceRecord(**base)


# ---------------------------------------------------------------------------
# Authority tier and latest rejection
# ---------------------------------------------------------------------------


def test_authority_tiers_are_closed_and_stable():
    assert [t.value for t in AuthorityTier] == [
        "official-base",
        "official-change",
        "unofficial-current",
        "guidance",
        "candidate",
    ]


def test_registry_rejects_missing_authority_tier_on_mapping():
    registry = AuthoritySourceRegistry()
    payload = {
        "source_key": "missing-tier",
        "collection": "CFR",
        "edition": "2024",
    }
    with pytest.raises(MissingAuthorityTierError, match="authority_tier is required"):
        registry.register(payload)


def test_registry_rejects_empty_authority_tier():
    registry = AuthoritySourceRegistry()
    with pytest.raises(MissingAuthorityTierError):
        registry.register(
            {
                "source_key": "empty-tier",
                "authority_tier": "",
                "collection": "CFR",
                "edition": "2024",
            }
        )


def test_record_from_dict_requires_authority_tier():
    with pytest.raises(MissingAuthorityTierError):
        AuthoritySourceRecord.from_dict(
            {
                "source_key": "x",
                "collection": "CFR",
                "edition": "2023",
            }
        )


@pytest.mark.parametrize(
    "field_name",
    ["edition", "version", "release_point", "revision"],
)
def test_registry_rejects_hard_coded_latest_editions(field_name):
    registry = AuthoritySourceRegistry()
    payload = {
        "source_key": f"latest-{field_name}",
        "authority_tier": "official-base",
        "collection": "USCODE",
        "edition": "2023",
        "version": "r1",
        "release_point": "pl-118-1",
        "revision": "1",
        field_name: "latest",
    }
    with pytest.raises(HardCodedLatestEditionError, match="latest"):
        registry.register(payload)


@pytest.mark.parametrize("token", ["latest", "Latest", " LATEST "])
def test_reject_hard_coded_latest_helper(token):
    with pytest.raises(HardCodedLatestEditionError):
        reject_hard_coded_latest(token, field_name="edition")


def test_record_rejects_latest_in_upstream_package_id():
    with pytest.raises(HardCodedLatestEditionError):
        ArtifactIdentity(
            provider="ushouse",
            source_id="t35",
            artifact_sha256=_OFFICIAL_SHA,
            source_url="https://uscode.house.gov/download/releasepoints/example.zip",
            upstream_package_id="latest",
        )


def test_record_rejects_latest_nested_in_metadata():
    with pytest.raises(HardCodedLatestEditionError):
        _base_record(metadata={"edition": "latest"})


def test_registry_accepts_concrete_edition():
    registry = AuthoritySourceRegistry()
    record = registry.register(_base_record())
    assert record.edition == "2024"
    assert record.authority_tier is AuthorityTier.OFFICIAL_BASE
    assert "us-cfr-37-2024-base" in registry


# ---------------------------------------------------------------------------
# Dual identity preservation
# ---------------------------------------------------------------------------


def test_connectors_preserve_official_and_derived_identities():
    registry = AuthoritySourceRegistry()
    registry.register(
        AuthoritySourceRecord(
            source_key="cfr-37-dual",
            authority_tier=AuthorityTier.OFFICIAL_BASE,
            collection="CFR",
            edition="2024",
            official_artifact=_official_identity(),
        )
    )
    updated = registry.preserve_dual_identities(
        "cfr-37-dual",
        derived_presentation=_derived_identity(),
    )
    assert updated.official_artifact is not None
    assert updated.derived_presentation is not None
    assert updated.official_artifact.role is IdentityRole.OFFICIAL_ARTIFACT
    assert updated.derived_presentation.role is IdentityRole.DERIVED_PRESENTATION
    assert updated.official_artifact.artifact_sha256 == _OFFICIAL_SHA
    assert updated.derived_presentation.artifact_sha256 == _DERIVED_SHA
    # Identities remain distinct.
    assert (
        updated.official_artifact.artifact_sha256
        != updated.derived_presentation.artifact_sha256
    )
    assert updated.official_artifact.source_url != updated.derived_presentation.source_url


def test_official_tier_cannot_have_only_derived_presentation():
    with pytest.raises(Exception, match="derived presentation"):
        AuthoritySourceRecord(
            source_key="bad-official",
            authority_tier=AuthorityTier.OFFICIAL_BASE,
            collection="CFR",
            edition="2024",
            derived_presentation=_derived_identity(),
        )


def test_unofficial_current_may_use_derived_only():
    record = AuthoritySourceRecord(
        source_key="ecfr-current-view",
        authority_tier=AuthorityTier.UNOFFICIAL_CURRENT,
        collection="CFR",
        edition="as-of-2024-06-01",
        derived_presentation=_derived_identity(),
    )
    assert record.official_artifact is None
    assert record.derived_presentation is not None
    assert record.authority_tier is AuthorityTier.UNOFFICIAL_CURRENT


def test_with_identity_helpers_set_roles():
    record = _base_record(official_artifact=None, derived_presentation=None)
    record = record.with_official_artifact(
        ArtifactIdentity(
            provider="govinfo",
            source_id="x",
            artifact_sha256=_ALT_SHA,
            source_url="https://www.govinfo.gov/example.xml",
            role=IdentityRole.DERIVED_PRESENTATION,  # will be coerced
        )
    )
    record = record.with_derived_presentation(
        ArtifactIdentity(
            provider="ecfr",
            source_id="y",
            artifact_sha256=_DERIVED_SHA,
            source_url="https://www.ecfr.gov/current/title-37",
            role=IdentityRole.OFFICIAL_ARTIFACT,  # will be coerced
        )
    )
    assert record.official_artifact.role is IdentityRole.OFFICIAL_ARTIFACT
    assert record.derived_presentation.role is IdentityRole.DERIVED_PRESENTATION


# ---------------------------------------------------------------------------
# Deterministic serialization
# ---------------------------------------------------------------------------


def test_fixture_serialize_deterministically_across_key_order():
    left = _base_record()
    right = AuthoritySourceRecord.from_dict(
        {
            # Deliberately different key insertion order from to_dict().
            "version": left.version,
            "source_key": left.source_key,
            "collection": left.collection,
            "authority_tier": left.authority_tier.value,
            "edition": left.edition,
            "jurisdiction": left.jurisdiction,
            "title": left.title,
            "citation": left.citation,
            "release_point": left.release_point,
            "date_issued": "2024-07-01",
            "publication_date": "2024-07-01",
            "effective_start": "2024-07-01",
            "official_artifact": left.official_artifact.to_dict(),
            "derived_presentation": left.derived_presentation.to_dict(),
            "receipt": left.receipt.to_dict(),
            "verification_state": "verified",
            "signature_present": True,
            "signature_valid": True,
            "signature_algorithm": "GPO-authenticity",
            "retry_cache_policy": left.retry_cache_policy.to_dict(),
        }
    )
    assert left.to_canonical_json() == right.to_canonical_json()
    assert left.to_canonical_bytes() == right.to_canonical_bytes()


def test_registry_fixture_round_trip_is_byte_identical():
    registry = AuthoritySourceRegistry(
        default_retry_cache_policy=RetryCachePolicy(max_attempts=4, jitter_ratio=0.1)
    )
    registry.register(_base_record())
    registry.register(
        build_fixture_record(
            source_key="uscode-35-2023",
            authority_tier=AuthorityTier.OFFICIAL_BASE,
            collection="USCODE",
            edition="2023",
            official_sha256=_ALT_SHA,
            official_url="https://uscode.house.gov/download/releasepoints/us/pl/118/1/htm_usc35@118-1.zip",
            provider="ushouse",
            title="35",
            citation="35 U.S.C.",
            release_point="118-1",
        )
    )
    # Register out of key order; fixture must still sort.
    blob1 = registry.to_canonical_json()
    restored = AuthoritySourceRegistry.from_canonical_json(blob1)
    blob2 = restored.to_canonical_json()
    assert blob1 == blob2
    assert json.loads(blob1)["schema_version"] == SCHEMA_VERSION
    # Sorted sources in fixture.
    keys = [s["source_key"] for s in json.loads(blob1)["sources"]]
    assert keys == sorted(keys)


def test_source_receipt_round_trip():
    receipt = _receipt(retry_count=2, cache_hit=True, cache_key="k1")
    again = SourceReceipt.from_dict(receipt.to_dict())
    assert again.to_dict() == receipt.to_dict()
    assert again.retrieved_at == datetime(2024, 7, 15, 18, 30, tzinfo=timezone.utc)
    assert again.content_sha256 == _OFFICIAL_SHA


def test_canonical_json_dumps_sorts_keys():
    text = canonical_json_dumps({"b": 1, "a": {"z": 2, "y": 3}})
    assert text == '{"a":{"y":3,"z":2},"b":1}'


# ---------------------------------------------------------------------------
# Receipts, retry/cache policy, registry operations
# ---------------------------------------------------------------------------


def test_attach_receipt_preserves_history():
    registry = AuthoritySourceRegistry()
    registry.register(_base_record())
    second = _receipt(
        retrieved_at="2024-08-01T00:00:00Z",
        retry_count=0,
        cache_hit=True,
        response_status=304,
    )
    registry.attach_receipt("us-cfr-37-2024-base", second)
    history = registry.receipts_for("us-cfr-37-2024-base")
    assert len(history) == 2
    assert history[-1].response_status == 304
    assert registry.get("us-cfr-37-2024-base").receipt.response_status == 304


def test_duplicate_source_key_rejected_unless_overwrite():
    registry = AuthoritySourceRegistry()
    registry.register(_base_record())
    with pytest.raises(AuthoritySourceRegistryError, match="already registered"):
        registry.register(_base_record())
    replaced = registry.register(
        _base_record(notes="updated"),
        overwrite=True,
    )
    assert replaced.notes == "updated"


def test_list_by_tier_and_iteration_order():
    registry = AuthoritySourceRegistry()
    registry.register(
        AuthoritySourceRecord(
            source_key="mpep-guidance",
            authority_tier=AuthorityTier.GUIDANCE,
            collection="MPEP",
            edition="9th-rev-2024.10",
            revision="2024.10",
        )
    )
    registry.register(_base_record())
    registry.register(
        AuthoritySourceRecord(
            source_key="fr-change",
            authority_tier=AuthorityTier.OFFICIAL_CHANGE,
            collection="FR",
            edition="89-FR-12345",
            official_artifact=_official_identity(
                source_id="fr-89-12345",
                source_url="https://www.govinfo.gov/content/pkg/FR-2024-01-01/pdf/2024-00001.pdf",
                artifact_sha256=_ALT_SHA,
            ),
        )
    )
    keys = [r.source_key for r in registry]
    assert keys == sorted(keys)
    assert len(registry.list_by_tier(AuthorityTier.OFFICIAL_BASE)) == 1
    assert len(registry.list_by_tier("guidance")) == 1
    assert len(registry.list_by_tier("official-change")) == 1


def test_retry_cache_policy_defaults_and_validation():
    policy = RetryCachePolicy()
    assert policy.honor_retry_after is True
    assert policy.enable_conditional_requests is True
    assert policy.max_attempts >= 1
    with pytest.raises(Exception):
        RetryCachePolicy(max_attempts=0)
    with pytest.raises(Exception):
        RetryCachePolicy(jitter_ratio=1.5)


def test_registry_applies_custom_default_policy():
    custom = RetryCachePolicy(max_attempts=7, base_backoff_seconds=1.0)
    registry = AuthoritySourceRegistry(default_retry_cache_policy=custom)
    record = registry.register(
        {
            "source_key": "candidate-extract",
            "authority_tier": "candidate",
            "collection": "EXTRACT",
            "edition": "parser-v1",
        }
    )
    assert record.retry_cache_policy.max_attempts == 7


def test_build_fixture_record_helper():
    record = build_fixture_record(
        source_key="helper-record",
        authority_tier="official-change",
        collection="FR",
        edition="89-FR-999",
        official_sha256=_OFFICIAL_SHA,
        official_url="https://www.govinfo.gov/content/pkg/FR-example/pdf/x.pdf",
        provider="govinfo",
        derived_sha256=_DERIVED_SHA,
        derived_url="https://www.federalregister.gov/documents/2024/01/01/2024-00001",
    )
    assert record.authority_tier is AuthorityTier.OFFICIAL_CHANGE
    assert record.official_artifact is not None
    assert record.derived_presentation is not None
    assert record.receipt is not None
    # Round-trip still deterministic.
    assert (
        AuthoritySourceRecord.from_dict(record.to_dict()).to_canonical_json()
        == record.to_canonical_json()
    )


def test_unknown_source_key_raises():
    registry = AuthoritySourceRegistry()
    with pytest.raises(AuthoritySourceRegistryError, match="unknown source_key"):
        registry.get("missing")


def test_verification_states_round_trip():
    for state in VerificationState:
        record = _base_record(verification_state=state)
        restored = AuthoritySourceRecord.from_dict(record.to_dict())
        assert restored.verification_state is state


def test_effective_interval_validation():
    with pytest.raises(Exception, match="effective_end"):
        _base_record(
            effective_start=date(2024, 6, 1),
            effective_end=date(2024, 1, 1),
        )


def test_sha256_must_be_lowercase_hex():
    with pytest.raises(Exception, match="SHA-256"):
        ArtifactIdentity(
            provider="x",
            source_id="y",
            artifact_sha256="ZZ" + "a" * 62,
            source_url="https://example.gov/a",
        )
