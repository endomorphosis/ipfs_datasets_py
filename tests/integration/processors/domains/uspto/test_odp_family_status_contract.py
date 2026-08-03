"""Integration tests: continuity/foreign-priority + status vocabulary (PATLAW-124).

Continuity and foreign-priority facts are immutable and source-bound.
Unknown numeric status codes return unknown/quarantine rather than known.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.application_status_processor import (
    ApplicationStatusProcessor,
    InMemoryStatusSnapshotStore,
    normalize_status_from_meta,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    SourceReceipt,
)
from ipfs_datasets_py.processors.domains.uspto.durable_stores import (
    DurableMatterState,
    IdempotencyDisposition,
)
from ipfs_datasets_py.processors.domains.uspto.matter_events import (
    ApplicationLifecyclePhase,
)
from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    ProviderOutcomeKind,
    RecordedExchange,
    RecordedHttpTransport,
    RetryPolicy,
    build_source_receipt,
    HttpRequest,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
    PATH_CONTINUITY,
    PATH_FOREIGN_PRIORITY,
    PATENT_FILE_WRAPPER_SCHEMA_VERSION,
    OdpContinuitySnapshot,
    OdpForeignPrioritySnapshot,
    PatentFileWrapperClient,
    build_application_identity,
    parse_continuity,
    parse_foreign_priority,
)
from ipfs_datasets_py.processors.domains.uspto.status_vocabulary import (
    STATUS_VOCABULARY_SCHEMA_VERSION,
    StatusCodeRecognition,
    classify_status_code,
    is_status_code_known,
    protected_status_codes,
    vocabulary_manifest,
)


APP = "16123456"


class FixedClock:
    def __init__(self) -> None:
        self.when = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.when


def _receipt(endpoint: str) -> SourceReceipt:
    digest = "a" * 64
    return SourceReceipt(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        receipt_id="receipt:family:test",
        endpoint=endpoint,
        retrieval_utc="2026-08-03T12:00:00Z",
        response_status=200,
        upstream_id=APP,
        last_modified=None,
        request_digest=digest,
        response_digest=digest,
        cache_hit=False,
        retry_count=0,
        metadata={"provider": "odp_patent_file_wrapper"},
    )


def _continuity_body() -> dict:
    return {
        "count": 1,
        "patentFileWrapperDataBag": [
            {
                "applicationNumberText": APP,
                "parentContinuityBag": [
                    {
                        "parentApplicationNumberText": "15000001",
                        "claimParentageTypeCode": "CON",
                        "filingDate": "2018-05-01",
                    }
                ],
                "childContinuityBag": [
                    {
                        "childApplicationNumberText": "17000002",
                        "claimParentageTypeCode": "DIV",
                        "filingDate": "2021-03-15",
                    }
                ],
            }
        ],
        "requestIdentifier": "continuity-fixture",
    }


def _foreign_priority_body() -> dict:
    return {
        "count": 1,
        "patentFileWrapperDataBag": [
            {
                "applicationNumberText": APP,
                "foreignPriorityBag": [
                    {
                        "ipOfficeName": "Japan",
                        "applicationNumberText": "2020-123456",
                        "filingDate": "2020-02-20",
                    },
                    {
                        "countryCode": "EP",
                        "priorityApplicationNumberText": "EP20123456",
                        "priorityDate": "2020-03-01",
                    },
                ],
            }
        ],
        "requestIdentifier": "foreign-priority-fixture",
    }


def test_continuity_facts_immutable_and_source_bound() -> None:
    transport = RecordedHttpTransport(
        [
            RecordedExchange(
                method="GET",
                path=f"/api/v1/patent/applications/{APP}/continuity",
                status=200,
                body=_continuity_body(),
            )
        ]
    )
    client = PatentFileWrapperClient(
        transport,
        api_key="test-key",
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
    )
    result = client.get_continuity(APP)
    assert result.ok
    assert isinstance(result.payload, OdpContinuitySnapshot)
    snap: OdpContinuitySnapshot = result.payload
    assert snap.application_number == APP
    assert snap.receipt is not None
    assert snap.receipt.endpoint  # source-bound
    assert len(snap.parents) == 1
    assert snap.parents[0].related_application_number == "15000001"
    assert snap.parents[0].relation_role == "parent"
    assert snap.parents[0].continuity_type == "CON"
    assert len(snap.children) == 1
    assert snap.children[0].related_application_number == "17000002"
    # Frozen dataclasses: mutation must fail
    with pytest.raises(Exception):
        snap.parents[0].related_application_number = "hack"  # type: ignore[misc]


def test_foreign_priority_facts_immutable_and_source_bound() -> None:
    transport = RecordedHttpTransport(
        [
            RecordedExchange(
                method="GET",
                path=f"/api/v1/patent/applications/{APP}/foreign-priority",
                status=200,
                body=_foreign_priority_body(),
            )
        ]
    )
    client = PatentFileWrapperClient(
        transport,
        api_key="test-key",
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
    )
    result = client.get_foreign_priority(APP)
    assert result.ok
    snap = result.payload
    assert isinstance(snap, OdpForeignPrioritySnapshot)
    assert snap.receipt is not None
    assert len(snap.claims) == 2
    assert snap.claims[0].priority_country == "Japan"
    assert snap.claims[0].priority_application_number == "2020-123456"
    assert snap.claims[1].priority_country == "EP"
    with pytest.raises(Exception):
        snap.claims[0].priority_date = "2099-01-01"  # type: ignore[misc]


def test_parse_continuity_empty_bag() -> None:
    receipt = _receipt("https://api.uspto.gov" + PATH_CONTINUITY.format(applicationNumberText=APP))
    snap = parse_continuity(
        {"count": 0, "patentFileWrapperDataBag": []},
        receipt=receipt,
        requested_application_number=APP,
    )
    assert snap.parents == ()
    assert snap.children == ()
    assert snap.receipt is receipt


def test_processor_fetch_continuity_and_foreign_priority() -> None:
    transport = RecordedHttpTransport(
        [
            RecordedExchange(
                method="GET",
                path=f"/api/v1/patent/applications/{APP}/continuity",
                status=200,
                body=_continuity_body(),
            ),
            RecordedExchange(
                method="GET",
                path=f"/api/v1/patent/applications/{APP}/foreign-priority",
                status=200,
                body=_foreign_priority_body(),
            ),
        ]
    )
    client = PatentFileWrapperClient(
        transport,
        api_key="test-key",
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
    )
    proc = ApplicationStatusProcessor(
        client=client,
        store=InMemoryStatusSnapshotStore(),
        wall_clock=FixedClock(),
        max_freshness_age=timedelta(days=365 * 20),
    )
    cont = proc.fetch_continuity(APP)
    assert cont.ok and isinstance(cont.payload, OdpContinuitySnapshot)
    fp = proc.fetch_foreign_priority(APP)
    assert fp.ok and isinstance(fp.payload, OdpForeignPrioritySnapshot)


def test_durable_store_preserves_family_facts_immutably(tmp_path: Path) -> None:
    store = DurableMatterState(tmp_path / "family", tenant_id="family-t")
    receipt = _receipt("https://api.uspto.gov/continuity")
    cont = parse_continuity(
        _continuity_body(), receipt=receipt, requested_application_number=APP
    )
    payload = cont.to_dict()
    r1 = store.put_continuity(application_number=APP, snapshot=payload)
    r2 = store.put_continuity(application_number=APP, snapshot=payload)
    assert r1.disposition is IdempotencyDisposition.CREATED
    assert r2.disposition is IdempotencyDisposition.DUPLICATE
    loaded = store.get_continuity(APP)
    assert loaded is not None
    assert loaded["parents"][0]["related_application_number"] == "15000001"
    # Receipt identity retained (source-bound)
    assert "receipt" in loaded


def test_known_status_code_from_protected_vocabulary() -> None:
    assert is_status_code_known(150) is True
    assert is_status_code_known("150") is True
    c = classify_status_code(150)
    assert c.recognition is StatusCodeRecognition.KNOWN
    assert c.quarantine is False
    assert c.entry is not None
    assert c.entry.lifecycle_phase is ApplicationLifecyclePhase.PRE_EXAMINATION

    snap = normalize_status_from_meta(
        {
            "applicationStatusCode": 150,
            "applicationStatusDescriptionText": "Docketed New Case - Ready for Examination",
        },
        retrieval_utc="2026-08-03T12:00:00Z",
    )
    assert snap is not None
    assert snap.status_code == "150"
    assert snap.lifecycle_phase is ApplicationLifecyclePhase.PRE_EXAMINATION


def test_unknown_numeric_status_code_quarantines_not_known() -> None:
    """Acceptance: unknown numeric codes return unknown/quarantine rather than known."""

    # Previously the processor treated 0 < code < 1000 as known; 88888 and 99991
    # must never be admitted as known.
    for code in (88888, 99991, 777, 1, 999):
        if str(code) in protected_status_codes() or str(int(code)) in {
            e for e in protected_status_codes() if e.isdigit()
        }:
            # Skip codes that are intentionally in the protected set.
            if is_status_code_known(code):
                continue
        c = classify_status_code(code)
        assert c.is_known is False, f"{code} must not be known"
        assert c.recognition in {
            StatusCodeRecognition.UNKNOWN,
            StatusCodeRecognition.QUARANTINE,
        }
        assert c.quarantine is True

    # 777 is not in the protected vocabulary → quarantine
    c777 = classify_status_code(777)
    assert c777.quarantine is True
    assert c777.recognition is StatusCodeRecognition.QUARANTINE

    snap = normalize_status_from_meta(
        {
            "applicationStatusCode": 88888,
            "applicationStatusDescriptionText": "Unknown Future Status",
            "mysteryField": "preserve",
        },
        retrieval_utc="2026-08-03T12:00:00Z",
    )
    assert snap is not None
    assert snap.status_code == "88888"
    assert snap.raw_fields["mysteryField"] == "preserve"
    assert snap.raw_fields["applicationStatusCode"] == "88888"
    assert any("quarantine" in n.lower() or "unknown" in n.lower() for n in snap.notes)
    assert "status_code_quarantined" in snap.notes


def test_unknown_status_surfaces_in_processor_snapshot_notes() -> None:
    from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
        OdpApplicationSnapshot,
        OdpTransactionRecord,
    )

    digest = "b" * 64
    receipt = SourceReceipt(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        receipt_id="receipt:unknown-status",
        endpoint=f"https://api.uspto.gov/api/v1/patent/applications/{APP}",
        retrieval_utc="2026-08-03T12:00:00Z",
        response_status=200,
        upstream_id=APP,
        last_modified=None,
        request_digest=digest,
        response_digest=digest,
        cache_hit=False,
        retry_count=0,
        metadata={"provider": "odp_patent_file_wrapper"},
    )
    app = OdpApplicationSnapshot(
        schema_version=PATENT_FILE_WRAPPER_SCHEMA_VERSION,
        application_number=APP,
        identity=build_application_identity(APP),
        application_meta_data={
            "applicationStatusCode": 88888,
            "applicationStatusDescriptionText": "Unknown Future Status",
        },
        raw_bag={"applicationNumberText": APP},
        receipt=receipt,
        event_data=(),
        last_ingestion_datetime="2026-08-01T12:00:00",
    )
    proc = ApplicationStatusProcessor(
        client=PatentFileWrapperClient(
            RecordedHttpTransport([]),
            api_key="k",
            retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
        ),
        store=InMemoryStatusSnapshotStore(),
        wall_clock=FixedClock(),
        max_freshness_age=timedelta(days=365 * 20),
    )
    snap = proc.build_snapshot_from_provider(
        application_snapshot=app,
        transaction_records=(),
        application_receipt=receipt,
        transactions_receipt=None,
    )
    assert snap.status is not None
    assert snap.status.status_code == "88888"
    assert any("QUARANTINE" in n or "quarantine" in n.lower() for n in snap.notes)
    # Must not claim the code is known via vocabulary
    assert is_status_code_known("88888") is False


def test_vocabulary_manifest_versioned() -> None:
    manifest = vocabulary_manifest()
    assert manifest["schema_version"] == STATUS_VOCABULARY_SCHEMA_VERSION
    assert manifest["code_count"] >= 10
    assert "150" in manifest["codes"] or "150" in {c for c in protected_status_codes()}


def test_paths_exported() -> None:
    assert "continuity" in PATH_CONTINUITY
    assert "foreign-priority" in PATH_FOREIGN_PRIORITY
