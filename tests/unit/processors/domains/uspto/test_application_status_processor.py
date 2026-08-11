"""Unit tests for ApplicationStatusProcessor (PATLAW-022)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

import pytest

from ipfs_datasets_py.processors.domains.uspto.application_status_processor import (
    APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION,
    PUBLIC_ACCESS_LIMITATIONS,
    ApplicationStatusProcessor,
    ApplicationStatusProcessorError,
    EvidentiaryRestriction,
    FreshnessAssessment,
    FreshnessClass,
    InMemoryStatusSnapshotStore,
    NormalizedTransactionEvent,
    PublicAccessLimitation,
    StatusSyncOutcome,
    VersionedStatusEventSnapshot,
    assess_freshness,
    compute_status_content_digest,
    normalize_status_from_meta,
    normalize_transaction_event,
    public_access_limitations_dict,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    ApplicationIdentity,
    MatterEventKind,
    SourceReceipt,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.matter_events import (
    MATTER_EVENTS_SCHEMA_VERSION,
    ApplicationLifecyclePhase,
    ApplicationStatusSnapshot,
)
from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    HttpRequest,
    ProviderError,
    RetryPolicy,
    load_recorded_exchanges,
    sanitize_headers,
    sanitize_url,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
    PATENT_FILE_WRAPPER_SCHEMA_VERSION,
    OdpApplicationSnapshot,
    PatentFileWrapperClient,
    build_application_identity,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[4] / "fixtures" / "uspto" / "odp" / "http"
)
RECIPE_PATH = FIXTURE_DIR / "odp_http_recipe.json"
APP_OK = "16123456"
DIGEST_A = "a" * 64


class FixedClock:
    def __init__(self, when: datetime | None = None) -> None:
        self.when = when or datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.when


class StickyRecordedHttpTransport:
    """Replay matching fixture exchanges without consuming them.

    The stock :class:`RecordedHttpTransport` pops matches so ordered multi-status
    sequences work. Idempotent re-sync needs stable repeated 200 responses for
    the same paths; this sticky variant provides that for multi-sync tests.
    """

    def __init__(self, recipe_path: Path) -> None:
        with recipe_path.open(encoding="utf-8") as handle:
            recipe = json.load(handle)
        self._exchanges = load_recorded_exchanges(recipe)
        self.requests: list[HttpRequest] = []

    def request(self, request: HttpRequest):
        self.requests.append(
            HttpRequest(
                method=request.method,
                url=request.url,
                headers=sanitize_headers(request.headers),
                body=request.body,
                timeout_seconds=request.timeout_seconds,
            )
        )
        # Prefer the first *successful* (2xx) match for stable re-sync, falling
        # back to the first match of any status.
        first_any = None
        for exchange in self._exchanges:
            if not exchange.matches(request):
                continue
            if first_any is None:
                first_any = exchange
            if 200 <= int(exchange.status) < 300:
                return exchange.as_response()
        if first_any is not None:
            return first_any.as_response()
        raise ProviderError(
            f"no recorded exchange for {request.method} {sanitize_url(request.url)}",
            code="fixture_miss",
        )


def _client(*, sticky: bool = False) -> PatentFileWrapperClient:
    clock = FixedClock()
    if sticky:
        return PatentFileWrapperClient(
            StickyRecordedHttpTransport(RECIPE_PATH),
            api_key="synthetic-api-key",
            retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
            wall_clock=clock,
            sleep=lambda _s: None,
            random_sample=lambda: 0.0,
        )
    return PatentFileWrapperClient.from_recorded_recipe(
        RECIPE_PATH,
        api_key="synthetic-api-key",
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
        wall_clock=clock,
        sleep=lambda _s: None,
        random_sample=lambda: 0.0,
    )


def _processor(**kwargs: object) -> ApplicationStatusProcessor:
    store = kwargs.pop("store", InMemoryStatusSnapshotStore())
    return ApplicationStatusProcessor(
        client=kwargs.pop("client", _client()),  # type: ignore[arg-type]
        store=store,  # type: ignore[arg-type]
        wall_clock=kwargs.pop("wall_clock", FixedClock()),  # type: ignore[arg-type]
        max_freshness_age=kwargs.pop(  # type: ignore[arg-type]
            "max_freshness_age", timedelta(hours=24 * 365 * 50)
        ),
        **kwargs,  # type: ignore[arg-type]
    )


def _assert_round_trip(record: object) -> None:
    assert hasattr(record, "to_dict") and hasattr(type(record), "from_dict")
    first = record.to_dict()  # type: ignore[attr-defined]
    restored = type(record).from_dict(first)  # type: ignore[attr-defined]
    second = restored.to_dict()  # type: ignore[attr-defined]
    assert first == second
    assert canonical_json(first) == canonical_json(second)


def _receipt(*, receipt_id: str = "receipt:test:1") -> SourceReceipt:
    return SourceReceipt(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        receipt_id=receipt_id,
        endpoint="https://api.uspto.gov/api/v1/patent/applications/16123456",
        retrieval_utc="2026-08-03T12:00:00Z",
        response_status=200,
        upstream_id=APP_OK,
        last_modified=None,
        request_digest=DIGEST_A,
        response_digest=DIGEST_A,
        cache_hit=False,
        retry_count=0,
        metadata={"provider": "odp_patent_file_wrapper"},
    )


# ---------------------------------------------------------------------------
# Public-access limitations are explicit
# ---------------------------------------------------------------------------


def test_public_access_limitations_catalog_is_explicit_and_nonempty() -> None:
    catalog = public_access_limitations_dict()
    assert len(catalog) >= 6
    assert PublicAccessLimitation.ODP_PUBLIC_ONLY.value in catalog
    assert PublicAccessLimitation.NOT_PROOF_OF_FILING.value in catalog
    assert PublicAccessLimitation.NOT_PROOF_OF_NONRECEIPT.value in catalog
    assert PublicAccessLimitation.NO_PRIVATE_PATENT_CENTER.value in catalog
    for lim in PUBLIC_ACCESS_LIMITATIONS:
        assert lim.value in catalog
        assert catalog[lim.value].strip()


def test_sync_result_always_carries_public_access_limitations() -> None:
    proc = _processor()
    result = proc.sync(APP_OK)
    assert result.ok
    assert result.public_access_limitations == PUBLIC_ACCESS_LIMITATIONS
    assert PublicAccessLimitation.NOT_PROOF_OF_NONRECEIPT in result.public_access_limitations
    assert result.snapshot is not None
    assert result.snapshot.public_access_limitations == PUBLIC_ACCESS_LIMITATIONS
    # Notes explain each limitation.
    for lim in PUBLIC_ACCESS_LIMITATIONS:
        assert lim.value in result.public_access_notes
        assert result.public_access_notes[lim.value]


def test_snapshot_rejects_empty_public_access_limitations() -> None:
    status = normalize_status_from_meta(
        {
            "applicationStatusCode": 150,
            "applicationStatusDescriptionText": "Docketed New Case",
        },
        retrieval_utc="2026-08-03T12:00:00Z",
    )
    freshness = assess_freshness(
        retrieval_utc="2026-08-03T12:00:00Z",
        source_as_of_utc="2026-08-01T12:00:00Z",
        last_ingestion_datetime="2026-08-01T12:00:00Z",
        max_age=timedelta(days=30),
        now=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(ApplicationStatusProcessorError) as excinfo:
        VersionedStatusEventSnapshot(
            schema_version=APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION,
            version_id="status-v1:deadbeefdeadbeef",
            content_digest=DIGEST_A,
            sync_key=f"{APP_OK}:{DIGEST_A}",
            application_number=APP_OK,
            identity=build_application_identity(APP_OK),
            status=status,
            transactions=(),
            ordered_events=(),
            raw_application_meta={},
            raw_events=(),
            application_receipt=None,
            transactions_receipt=None,
            public_access_limitations=(),
            public_access_notes={},
            freshness=freshness,
            provider_schema_version=PATENT_FILE_WRAPPER_SCHEMA_VERSION,
            last_ingestion_datetime=None,
            notes=(),
        )
    assert excinfo.value.code == "missing_public_access_limitations"


# ---------------------------------------------------------------------------
# Status / event snapshots are versioned
# ---------------------------------------------------------------------------


def test_status_event_snapshots_are_versioned_and_content_addressed() -> None:
    proc = _processor()
    result = proc.sync(APP_OK)
    assert result.snapshot is not None
    snap = result.snapshot
    assert snap.schema_version == APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION
    assert snap.version_id.startswith("status-v1:")
    assert len(snap.content_digest) == 64
    assert snap.sync_key == f"{APP_OK}:{snap.content_digest}"
    assert snap.provider_schema_version == PATENT_FILE_WRAPPER_SCHEMA_VERSION
    _assert_round_trip(snap)
    _assert_round_trip(result)


def test_content_digest_changes_when_status_changes() -> None:
    meta_a = {
        "applicationStatusCode": 150,
        "applicationStatusDescriptionText": "Docketed New Case",
    }
    meta_b = {
        "applicationStatusCode": 160,
        "applicationStatusDescriptionText": "Non Final Action Mailed",
    }
    status_a = normalize_status_from_meta(meta_a, retrieval_utc="2026-08-03T12:00:00Z")
    status_b = normalize_status_from_meta(meta_b, retrieval_utc="2026-08-03T12:00:00Z")
    dig_a = compute_status_content_digest(
        application_number=APP_OK,
        status=status_a,
        raw_application_meta=meta_a,
        raw_events=[],
    )
    dig_b = compute_status_content_digest(
        application_number=APP_OK,
        status=status_b,
        raw_application_meta=meta_b,
        raw_events=[],
    )
    assert dig_a != dig_b


# ---------------------------------------------------------------------------
# Unknown codes are preserved
# ---------------------------------------------------------------------------


def test_unknown_status_code_preserved_in_snapshot() -> None:
    meta = {
        "applicationStatusCode": 99991,
        "applicationStatusDescriptionText": "Future Experimental Status",
        "customUpstreamField": "keep-me",
    }
    snap = normalize_status_from_meta(meta, retrieval_utc="2026-08-03T12:00:00Z")
    assert snap is not None
    assert snap.status_code == "99991"
    assert snap.status_text == "Future Experimental Status"
    assert snap.raw_fields["applicationStatusCode"] == "99991"
    assert snap.raw_fields["customUpstreamField"] == "keep-me"
    # Never collapsed to a lone rejected flag.
    assert "rejected" not in snap.to_dict()


def test_unknown_event_code_preserved_verbatim() -> None:
    event = {
        "eventCode": "ZZZ.FUTURE.CODE",
        "eventDescriptionText": "Hypothetical future office action",
        "eventDate": "2024-03-15",
        "extraField": {"nested": True},
    }
    tx = normalize_transaction_event(
        event,
        application_number=APP_OK,
        retrieval_utc="2026-08-03T12:00:00Z",
        index=0,
    )
    assert tx.event_code == "ZZZ.FUTURE.CODE"
    assert tx.code_recognized is False
    assert tx.raw_event["eventCode"] == "ZZZ.FUTURE.CODE"
    assert tx.raw_event["extraField"] == {"nested": True}
    assert any("not in known vocabulary" in n for n in tx.notes)
    _assert_round_trip(tx)

    matter = tx.to_normalized_matter_event(matter_id=f"matter:app:{APP_OK}")
    assert matter.metadata["event_code"] == "ZZZ.FUTURE.CODE"
    assert matter.metadata["code_recognized"] == "false"
    assert "raw.eventCode" in matter.metadata


def test_known_event_code_recognized() -> None:
    tx = normalize_transaction_event(
        {
            "eventCode": "CTNF",
            "eventDescriptionText": "Non-Final Rejection",
            "eventDate": "2020-06-01",
        },
        application_number=APP_OK,
        retrieval_utc="2026-08-03T12:00:00Z",
    )
    assert tx.code_recognized is True
    assert tx.kind is MatterEventKind.TRANSACTION
    assert tx.event_code == "CTNF"


# ---------------------------------------------------------------------------
# Stale / missing API data is not proof of filing / nonreceipt
# ---------------------------------------------------------------------------


def test_freshness_never_claims_filing_or_nonreceipt_proof() -> None:
    for missing in (True, False):
        for partial in (True, False):
            assessment = assess_freshness(
                retrieval_utc="2026-08-03T12:00:00Z",
                source_as_of_utc="2019-01-15T00:00:00Z",
                last_ingestion_datetime=None,
                max_age=timedelta(hours=1),
                now=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
                partial=partial,
                missing=missing,
            )
            assert assessment.is_proof_of_filing is False
            assert assessment.is_proof_of_nonreceipt is False
            assert EvidentiaryRestriction.PROOF_OF_FILING in assessment.evidentiary_restrictions
            assert (
                EvidentiaryRestriction.PROOF_OF_NONRECEIPT
                in assessment.evidentiary_restrictions
            )


def test_stale_snapshot_restricts_current_status_use() -> None:
    assessment = assess_freshness(
        retrieval_utc="2026-08-03T12:00:00Z",
        source_as_of_utc="2019-01-15T00:00:00Z",
        last_ingestion_datetime="2019-01-15T00:00:00Z",
        max_age=timedelta(hours=1),
        now=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert assessment.freshness_class is FreshnessClass.STALE
    assert (
        EvidentiaryRestriction.CURRENT_STATUS_WHEN_STALE
        in assessment.evidentiary_restrictions
    )
    assert any("not proof" in n.lower() for n in assessment.notes)


def test_freshness_assessment_rejects_true_proof_flags() -> None:
    with pytest.raises(ApplicationStatusProcessorError) as excinfo:
        FreshnessAssessment(
            schema_version=APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION,
            freshness_class=FreshnessClass.MISSING,
            retrieval_utc="2026-08-03T12:00:00Z",
            source_as_of_utc=None,
            max_age_seconds=3600.0,
            age_seconds=None,
            is_proof_of_filing=True,
            is_proof_of_nonreceipt=False,
            evidentiary_restrictions=(),
            notes=(),
        )
    assert excinfo.value.code == "invalid_evidentiary_claim"


def test_not_found_is_retrieval_gap_not_nonreceipt() -> None:
    proc = _processor()
    result = proc.sync("99999999")
    assert not result.ok
    assert result.outcome is StatusSyncOutcome.NOT_FOUND
    assert result.snapshot is None
    assert result.freshness.freshness_class is FreshnessClass.RETRIEVAL_GAP
    assert result.freshness.is_proof_of_nonreceipt is False
    assert result.freshness.is_proof_of_filing is False
    assert result.message is not None
    assert "not proof" in result.message.lower()
    assert "nonreceipt" in result.message.lower() or "not receive" in result.message.lower()
    assert PublicAccessLimitation.NOT_PROOF_OF_NONRECEIPT in result.public_access_limitations


def test_identity_rejected_before_provider_io() -> None:
    proc = _processor()
    result = proc.sync("")
    assert result.outcome is StatusSyncOutcome.IDENTITY_REJECTED
    assert result.snapshot is None
    assert result.freshness.is_proof_of_nonreceipt is False


# ---------------------------------------------------------------------------
# Repeated sync is idempotent
# ---------------------------------------------------------------------------


def test_repeated_sync_is_idempotent() -> None:
    store = InMemoryStatusSnapshotStore()
    # Sticky transport replays the same 200 bodies so content is stable.
    proc = _processor(store=store, client=_client(sticky=True))
    first = proc.sync(APP_OK)
    second = proc.sync(APP_OK)
    assert first.ok and second.ok
    assert first.snapshot is not None and second.snapshot is not None
    assert first.snapshot.sync_key == second.snapshot.sync_key
    assert first.snapshot.version_id == second.snapshot.version_id
    assert first.snapshot.content_digest == second.snapshot.content_digest
    assert second.idempotent_hit is True
    assert second.outcome is StatusSyncOutcome.IDEMPOTENT_HIT
    # Store holds a single version for identical content.
    versions = proc.list_versions(APP_OK)
    assert len(versions) == 1
    assert len(store) == 1


def test_idempotent_store_put_returns_existing() -> None:
    store = InMemoryStatusSnapshotStore()
    proc = _processor(store=store)
    first = proc.sync(APP_OK)
    assert first.snapshot is not None
    twin = VersionedStatusEventSnapshot.from_dict(first.snapshot.to_dict())
    again = store.put(twin)
    assert again.sync_key == first.snapshot.sync_key
    assert again.version_id == first.snapshot.version_id
    assert len(store) == 1


# ---------------------------------------------------------------------------
# End-to-end normalize from recorded provider (unit, fixture-backed)
# ---------------------------------------------------------------------------


def test_sync_normalizes_status_and_transactions_from_fixture() -> None:
    proc = _processor()
    result = proc.sync("16/123,456")
    assert result.ok
    assert result.application_number == APP_OK
    assert result.snapshot is not None
    snap = result.snapshot
    assert snap.status is not None
    assert snap.status.status_code == "150"
    assert "Docketed" in (snap.status.status_text or "")
    assert snap.status.lifecycle_phase is ApplicationLifecyclePhase.PRE_EXAMINATION
    # Transactions from dedicated endpoint (2 events in fixture).
    assert len(snap.transactions) == 2
    codes = [t.event_code for t in snap.transactions]
    assert "APP.FILE.REC" in codes
    assert "CTNF" in codes
    # Raw upstream retained.
    assert "applicationStatusCode" in snap.raw_application_meta
    assert snap.application_receipt is not None
    assert snap.transactions_receipt is not None
    # Ordered events include transactions + projected status event.
    assert len(snap.ordered_events) >= 2
    kinds = {e.kind for e in snap.ordered_events}
    assert MatterEventKind.STATUS in kinds


def test_build_snapshot_from_provider_without_network() -> None:
    clock = FixedClock()
    proc = _processor(wall_clock=clock)
    receipt = _receipt()
    app_snap = OdpApplicationSnapshot(
        schema_version=PATENT_FILE_WRAPPER_SCHEMA_VERSION,
        application_number=APP_OK,
        identity=build_application_identity(APP_OK),
        application_meta_data=MappingProxyType(
            {
                "applicationStatusCode": 150,
                "applicationStatusDescriptionText": "Docketed New Case - Ready for Examination",
                "filingDate": "2019-01-15",
            }
        ),
        raw_bag=MappingProxyType({"applicationNumberText": APP_OK}),
        receipt=receipt,
        event_data=(
            MappingProxyType(
                {
                    "eventCode": "APP.FILE.REC",
                    "eventDescriptionText": "Application filed",
                    "eventDate": "2019-01-15",
                }
            ),
        ),
        last_ingestion_datetime="2026-08-01T12:00:00",
    )
    built = proc.build_snapshot_from_provider(
        application_snapshot=app_snap,
        transaction_records=(),
        application_receipt=receipt,
        transactions_receipt=None,
    )
    assert built.application_number == APP_OK
    assert built.status is not None
    assert len(built.transactions) == 1  # fell back to bag event_data
    assert built.transactions[0].event_code == "APP.FILE.REC"
    assert built.freshness.is_proof_of_filing is False


def test_unauthorized_and_forbidden_do_not_fabricate_status() -> None:
    proc = _processor()
    unauth = proc.sync("00000001")
    assert unauth.outcome is StatusSyncOutcome.UNAUTHORIZED
    assert unauth.snapshot is None
    assert unauth.freshness.is_proof_of_nonreceipt is False

    forbidden = proc.sync("00000002")
    assert forbidden.outcome is StatusSyncOutcome.FORBIDDEN
    assert forbidden.snapshot is None


def test_status_snapshot_multi_dimensional_not_rejected_flag() -> None:
    status = normalize_status_from_meta(
        {
            "applicationStatusCode": "CTFR",
            "applicationStatusDescriptionText": "Final Rejection Mailed",
        },
        retrieval_utc="2026-08-03T12:00:00Z",
    )
    assert status is not None
    payload = status.to_dict()
    assert "rejected" not in payload
    assert isinstance(status, ApplicationStatusSnapshot)
    assert status.schema_version == MATTER_EVENTS_SCHEMA_VERSION


def test_resolve_identity_display_and_compact() -> None:
    proc = _processor()
    resolved = proc.resolve_identity("16/123,456")
    assert resolved is not None
    compact, identity = resolved
    assert compact == APP_OK
    assert identity.application_number == APP_OK
    assert isinstance(identity, ApplicationIdentity)


def test_transaction_event_round_trip_and_source_utc_from_date() -> None:
    tx = normalize_transaction_event(
        {
            "eventCode": "APP.FILE.REC",
            "eventDescriptionText": "Application filed",
            "eventDate": "2019-01-15",
        },
        application_number=APP_OK,
        retrieval_utc="2026-08-03T12:00:00Z",
    )
    assert tx.source_event_utc == "2019-01-15T00:00:00Z"
    assert tx.retrieval_utc == "2026-08-03T12:00:00Z"
    _assert_round_trip(tx)
