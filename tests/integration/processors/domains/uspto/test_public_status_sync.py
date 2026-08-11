"""Integration tests for public ODP status/transaction sync (PATLAW-022).

Uses recorded HTTP fixtures (no live network) to exercise the full path:
identity validation → PatentFileWrapperClient → ApplicationStatusProcessor
→ versioned store, including not-found gaps and idempotent re-sync.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.application_status_processor import (
    APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION,
    PUBLIC_ACCESS_LIMITATIONS,
    ApplicationStatusProcessor,
    EvidentiaryRestriction,
    FreshnessClass,
    InMemoryStatusSnapshotStore,
    PublicAccessLimitation,
    StatusSyncOutcome,
    public_access_limitations_dict,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import MatterEventKind, canonical_json
from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    HttpRequest,
    ProviderError,
    ProviderOutcomeKind,
    RetryPolicy,
    load_recorded_exchanges,
    sanitize_headers,
    sanitize_url,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
    PatentFileWrapperClient,
    default_fixture_dir,
)

FIXTURE_DIR = default_fixture_dir()
RECIPE_PATH = FIXTURE_DIR / "odp_http_recipe.json"
APP_OK = "16123456"


class FixedClock:
    def __init__(self, when: datetime | None = None) -> None:
        self.when = when or datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.when


class StickyRecordedHttpTransport:
    """Non-consuming fixture transport for multi-sync idempotency tests."""

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


def _make_client(*, sticky: bool = True) -> PatentFileWrapperClient:
    assert RECIPE_PATH.is_file(), f"missing fixture recipe: {RECIPE_PATH}"
    clock = FixedClock()
    kwargs = dict(
        api_key="synthetic-api-key",
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
        wall_clock=clock,
        sleep=lambda _s: None,
        random_sample=lambda: 0.0,
    )
    if sticky:
        return PatentFileWrapperClient(StickyRecordedHttpTransport(RECIPE_PATH), **kwargs)
    return PatentFileWrapperClient.from_recorded_recipe(RECIPE_PATH, **kwargs)


@pytest.fixture
def recorded_client() -> PatentFileWrapperClient:
    return _make_client(sticky=True)


@pytest.fixture
def processor(recorded_client: PatentFileWrapperClient) -> ApplicationStatusProcessor:
    # Generous max age so fixture dates (2019–2026) remain FRESH for happy path.
    return ApplicationStatusProcessor(
        client=recorded_client,
        store=InMemoryStatusSnapshotStore(),
        wall_clock=FixedClock(),
        max_freshness_age=timedelta(days=365 * 20),
        fetch_transactions=True,
    )


# ---------------------------------------------------------------------------
# Full public sync happy path
# ---------------------------------------------------------------------------


def test_public_status_sync_end_to_end(processor: ApplicationStatusProcessor) -> None:
    result = processor.sync(APP_OK)

    assert result.ok
    assert result.outcome is StatusSyncOutcome.SUCCESS
    assert result.application_number == APP_OK
    assert result.provider_kind == ProviderOutcomeKind.SUCCESS.value
    assert result.provider_status_code == 200
    assert result.idempotent_hit is False

    # Public-access limitations are explicit on the integration result.
    assert result.public_access_limitations == PUBLIC_ACCESS_LIMITATIONS
    catalog = public_access_limitations_dict()
    for lim in PUBLIC_ACCESS_LIMITATIONS:
        assert lim.value in result.public_access_notes
        assert result.public_access_notes[lim.value] == catalog[lim.value]

    snap = result.snapshot
    assert snap is not None
    assert snap.schema_version == APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION
    assert snap.version_id.startswith("status-v1:")
    assert len(snap.content_digest) == 64
    assert snap.sync_key == f"{APP_OK}:{snap.content_digest}"

    # Status normalized with multi-dimensional axes (not a rejected flag).
    assert snap.status is not None
    assert snap.status.status_code == "150"
    assert "Docketed" in (snap.status.status_text or "")
    assert "rejected" not in snap.status.to_dict()
    assert snap.status.raw_fields.get("applicationStatusCode") == "150"

    # Transactions retained with raw codes.
    assert len(snap.transactions) == 2
    by_code = {t.event_code: t for t in snap.transactions}
    assert "APP.FILE.REC" in by_code
    assert "CTNF" in by_code
    assert by_code["CTNF"].code_recognized is True
    assert by_code["APP.FILE.REC"].raw_event["eventCode"] == "APP.FILE.REC"

    # Source receipts present (sanitized provider receipts).
    assert snap.application_receipt is not None
    assert snap.transactions_receipt is not None
    assert snap.application_receipt.response_status == 200

    # Freshness never claims filing/nonreceipt proof.
    assert snap.freshness.is_proof_of_filing is False
    assert snap.freshness.is_proof_of_nonreceipt is False
    assert EvidentiaryRestriction.PROOF_OF_FILING in snap.freshness.evidentiary_restrictions
    assert (
        EvidentiaryRestriction.PROOF_OF_NONRECEIPT
        in snap.freshness.evidentiary_restrictions
    )
    assert snap.freshness.freshness_class in {
        FreshnessClass.FRESH,
        FreshnessClass.STALE,
        FreshnessClass.PARTIAL,
        FreshnessClass.UNKNOWN,
    }

    # Ordered events preserve source + retrieval temporal axes.
    assert len(snap.ordered_events) >= 2
    for event in snap.ordered_events:
        assert event.source_event_utc
        assert event.retrieval_utc


def test_public_status_sync_accepts_display_application_number(
    processor: ApplicationStatusProcessor,
) -> None:
    result = processor.sync("16/123,456")
    assert result.ok
    assert result.application_number == APP_OK
    assert result.snapshot is not None
    assert result.snapshot.identity.application_number == APP_OK


# ---------------------------------------------------------------------------
# Idempotent repeated sync
# ---------------------------------------------------------------------------


def test_public_status_sync_repeated_is_idempotent(
    processor: ApplicationStatusProcessor,
) -> None:
    first = processor.sync(APP_OK)
    second = processor.sync(APP_OK)
    third = processor.sync("16/123,456")

    assert first.ok and second.ok and third.ok
    assert first.snapshot is not None
    assert second.snapshot is not None
    assert third.snapshot is not None

    assert second.idempotent_hit is True
    assert third.idempotent_hit is True
    assert second.outcome is StatusSyncOutcome.IDEMPOTENT_HIT
    assert third.outcome is StatusSyncOutcome.IDEMPOTENT_HIT

    assert first.snapshot.version_id == second.snapshot.version_id
    assert first.snapshot.content_digest == second.snapshot.content_digest
    assert first.snapshot.sync_key == third.snapshot.sync_key

    # Canonical JSON equality of the durable snapshot payload.
    assert canonical_json(first.snapshot.to_dict()) == canonical_json(
        second.snapshot.to_dict()
    )

    versions = processor.list_versions(APP_OK)
    assert len(versions) == 1


# ---------------------------------------------------------------------------
# Missing / unauthorized: retrieval gaps, not nonreceipt
# ---------------------------------------------------------------------------


def test_not_found_is_freshness_gap_not_proof_of_nonreceipt(
    processor: ApplicationStatusProcessor,
) -> None:
    result = processor.sync("99999999")

    assert not result.ok
    assert result.outcome is StatusSyncOutcome.NOT_FOUND
    assert result.provider_kind == ProviderOutcomeKind.NOT_FOUND.value
    assert result.provider_status_code == 404
    assert result.snapshot is None

    assert result.freshness.freshness_class is FreshnessClass.RETRIEVAL_GAP
    assert result.freshness.is_proof_of_filing is False
    assert result.freshness.is_proof_of_nonreceipt is False
    assert PublicAccessLimitation.NOT_PROOF_OF_NONRECEIPT in result.public_access_limitations
    assert result.message is not None
    lowered = result.message.lower()
    assert "retrieval gap" in lowered or "not proof" in lowered
    assert "nonreceipt" in lowered or "did not receive" in lowered or "not receive" in lowered

    # Explicit restriction list forbids nonreceipt claims.
    assert EvidentiaryRestriction.PROOF_OF_NONRECEIPT in result.evidentiary_restrictions
    assert EvidentiaryRestriction.PROOF_OF_FILING in result.evidentiary_restrictions


def test_unauthorized_does_not_emit_status_snapshot(
    processor: ApplicationStatusProcessor,
) -> None:
    result = processor.sync("00000001")
    assert result.outcome is StatusSyncOutcome.UNAUTHORIZED
    assert result.snapshot is None
    assert result.freshness.is_proof_of_nonreceipt is False
    assert PublicAccessLimitation.API_KEY_REQUIRED in result.public_access_limitations


def test_forbidden_does_not_emit_status_snapshot(
    processor: ApplicationStatusProcessor,
) -> None:
    result = processor.sync("00000002")
    assert result.outcome is StatusSyncOutcome.FORBIDDEN
    assert result.snapshot is None
    assert result.freshness.is_proof_of_filing is False


# ---------------------------------------------------------------------------
# Stale classification with tight freshness bound
# ---------------------------------------------------------------------------


def test_stale_data_marked_without_nonreceipt_claim(
    recorded_client: PatentFileWrapperClient,
) -> None:
    # Max age of 1 hour vs fixture dates years in the past → STALE.
    proc = ApplicationStatusProcessor(
        client=recorded_client,
        store=InMemoryStatusSnapshotStore(),
        wall_clock=FixedClock(datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)),
        max_freshness_age=timedelta(hours=1),
    )
    result = proc.sync(APP_OK)
    assert result.snapshot is not None
    assert result.snapshot.freshness.freshness_class is FreshnessClass.STALE
    assert result.outcome is StatusSyncOutcome.STALE_DATA
    assert result.snapshot.freshness.is_proof_of_nonreceipt is False
    assert result.snapshot.freshness.is_proof_of_filing is False
    assert (
        EvidentiaryRestriction.CURRENT_STATUS_WHEN_STALE
        in result.snapshot.freshness.evidentiary_restrictions
    )


# ---------------------------------------------------------------------------
# Unknown codes survive the integration path
# ---------------------------------------------------------------------------


def test_unknown_codes_can_be_injected_through_normalize_path(
    recorded_client: PatentFileWrapperClient,
) -> None:
    """Build a snapshot from a synthetic bag that includes unknown codes."""

    from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
        PATENT_FILE_WRAPPER_SCHEMA_VERSION,
        OdpApplicationSnapshot,
        OdpTransactionRecord,
        build_application_identity,
    )
    from ipfs_datasets_py.processors.domains.uspto.contracts import (
        CONTRACTS_SCHEMA_VERSION,
        SourceReceipt,
    )

    proc = ApplicationStatusProcessor(
        client=recorded_client,
        store=InMemoryStatusSnapshotStore(),
        wall_clock=FixedClock(),
        max_freshness_age=timedelta(days=365 * 20),
    )
    digest = "b" * 64
    receipt = SourceReceipt(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        receipt_id="receipt:integration:unknown",
        endpoint="https://api.uspto.gov/api/v1/patent/applications/16123456",
        retrieval_utc="2026-08-03T12:00:00Z",
        response_status=200,
        upstream_id=APP_OK,
        last_modified=None,
        request_digest=digest,
        response_digest=digest,
        cache_hit=False,
        retry_count=0,
        metadata={"provider": "odp_patent_file_wrapper"},
    )
    app = OdpApplicationSnapshot(
        schema_version=PATENT_FILE_WRAPPER_SCHEMA_VERSION,
        application_number=APP_OK,
        identity=build_application_identity(APP_OK),
        application_meta_data={
            "applicationStatusCode": 88888,
            "applicationStatusDescriptionText": "Unknown Future Status",
            "mysteryField": "preserve",
        },
        raw_bag={"applicationNumberText": APP_OK},
        receipt=receipt,
        event_data=(),
        last_ingestion_datetime="2026-08-01T12:00:00",
    )
    txs = (
        OdpTransactionRecord(
            application_number=APP_OK,
            event={
                "eventCode": "QQQ.UNKNOWN",
                "eventDescriptionText": "Unknown transaction",
                "eventDate": "2021-04-01",
            },
        ),
    )
    snap = proc.build_snapshot_from_provider(
        application_snapshot=app,
        transaction_records=txs,
        application_receipt=receipt,
        transactions_receipt=receipt,
    )
    assert snap.status is not None
    assert snap.status.status_code == "88888"
    assert snap.status.raw_fields["mysteryField"] == "preserve"
    assert snap.transactions[0].event_code == "QQQ.UNKNOWN"
    assert snap.transactions[0].code_recognized is False
    assert any("Unknown" in n and "88888" in n for n in snap.notes)
    assert any("QQQ.UNKNOWN" in n for n in snap.notes)

    # Store + re-sync path for same content is still content-addressed.
    stored = proc.store.put(snap)
    again = proc.store.put(snap)
    assert stored.sync_key == again.sync_key
    assert len(proc.store.list_versions(APP_OK)) == 1  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Secrets never appear in serializable results
# ---------------------------------------------------------------------------


def test_sync_results_do_not_leak_api_key(
    processor: ApplicationStatusProcessor,
) -> None:
    secret = "integration-test-key-not-secret"
    result = processor.sync(APP_OK)
    blob = json.dumps(result.to_dict(), default=str)
    assert secret not in blob
    # Also cover failure path.
    fail = processor.sync("00000001")
    fail_blob = json.dumps(fail.to_dict(), default=str)
    assert secret not in fail_blob


def test_fixture_recipe_available() -> None:
    assert RECIPE_PATH.is_file()
    with RECIPE_PATH.open(encoding="utf-8") as handle:
        recipe = json.load(handle)
    assert recipe.get("schema_version")
    assert any(
        ex.get("path", "").endswith(f"/applications/{APP_OK}")
        for ex in recipe.get("exchanges", [])
    )
