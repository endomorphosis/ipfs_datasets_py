"""Unit tests for canonical public-patent models (PATLAW-019).

No live network calls: models are pure value objects.
"""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.patent.models import (
    MODELS_SCHEMA_VERSION,
    Citation,
    CitationKind,
    ClaimKind,
    DisclosureClassification,
    DisclosurePolicyError,
    PatentClaim,
    PatentDocument,
    ProsecutionEvent,
    PublicApplication,
    PublicPatent,
    Rejection,
    RejectionBasis,
    canonical_json,
    deterministic_id,
    enforce_public_disclosure,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import requires_quarantine

DIGEST_A = "a" * 64


def _assert_round_trip(record: object) -> None:
    assert hasattr(record, "to_dict") and hasattr(type(record), "from_dict")
    first = record.to_dict()  # type: ignore[attr-defined]
    restored = type(record).from_dict(first)  # type: ignore[attr-defined]
    second = restored.to_dict()  # type: ignore[attr-defined]
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert restored == record


def test_schema_version_pinned() -> None:
    assert MODELS_SCHEMA_VERSION == "public-patent.models.v1"


def test_public_patent_round_trip() -> None:
    record = PublicPatent.build(
        patent_number="US1234567",
        title="Method for processing data",
        abstract="An abstract",
        grant_date="2024-01-15",
        application_number="16/123456",
        inventors=("John Smith",),
        assignees=("TechCorp Inc",),
        cpc_classifications=("G06F",),
        content_sha256=DIGEST_A,
    )
    _assert_round_trip(record)
    assert record.stable_id.startswith("urn:public-patent:patent:sha256:")


def test_stable_id_independent_of_retrieval_metadata() -> None:
    """Identical content yields the same ID across time/path/token/mutable URL."""
    base_kwargs = dict(
        patent_number="US1234567",
        title="Method for processing data",
        abstract="An abstract",
        grant_date="2024-01-15",
        content_sha256=DIGEST_A,
    )
    a = PublicPatent.build(
        **base_kwargs,
        retrieved_at="2020-01-01T00:00:00Z",
        source_path="/tmp/cache/a.bin",
        request_url="https://api.example/patents?token=alpha",
        access_token="synthetic-access-token",
    )
    b = PublicPatent.build(
        **base_kwargs,
        retrieved_at="2026-08-03T12:00:00Z",
        source_path="/var/data/other/path.bin",
        request_url="https://cdn.example/v2/patents?session=beta&sig=zzz",
        access_token="synthetic-access-token-value",
    )
    assert a.stable_id == b.stable_id
    assert a.identity_dict() == b.identity_dict()
    # Observation fields remain available but do not affect identity.
    assert a.retrieved_at != b.retrieved_at
    assert a.source_path != b.source_path
    assert a.request_url != b.request_url
    assert a.access_token != b.access_token


def test_deterministic_id_strips_volatile_keys_from_payload() -> None:
    identity = {
        "patent_number": "US1",
        "title": "T",
        "retrieved_at": "2026-01-01T00:00:00Z",
        "source_path": "/tmp/x",
        "request_url": "https://example/x?token=1",
        "access_token": "secret",
        "token": "also-secret",
        "url": "https://mutable.example/x",
    }
    left = deterministic_id("patent", identity)
    right = deterministic_id(
        "patent",
        {
            "patent_number": "US1",
            "title": "T",
            "retrieved_at": "2099-12-31T23:59:59Z",
            "source_path": "/other",
            "request_url": "https://other/y?token=2",
            "access_token": "different",
            "token": "changed",
            "url": "https://other.example/y",
        },
    )
    assert left == right


def test_content_change_changes_stable_id() -> None:
    a = PublicPatent.build(patent_number="US1", title="Alpha")
    b = PublicPatent.build(patent_number="US1", title="Beta")
    assert a.stable_id != b.stable_id


def test_unknown_disclosure_fails_closed() -> None:
    with pytest.raises(DisclosurePolicyError, match="fails closed"):
        PublicPatent.build(
            patent_number="US1",
            title="Secret?",
            classification=DisclosureClassification.UNKNOWN,
        )
    with pytest.raises(DisclosurePolicyError, match="fails closed"):
        enforce_public_disclosure(DisclosureClassification.UNKNOWN)
    assert requires_quarantine(DisclosureClassification.UNKNOWN)


def test_private_disclosure_fails_closed() -> None:
    with pytest.raises(DisclosurePolicyError, match="non-public"):
        PublicPatent.build(
            patent_number="US1",
            title="Private",
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        )
    with pytest.raises(DisclosurePolicyError, match="non-public"):
        PublicApplication.build(
            application_number="16/1",
            title="Private app",
            classification=DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
        )


def test_unrecognized_disclosure_string_fails_closed() -> None:
    with pytest.raises(DisclosurePolicyError, match="unknown disclosure"):
        PublicPatent.build(
            patent_number="US1",
            title="Bad class",
            classification="not_a_real_class",
        )


def test_public_classifications_accepted() -> None:
    official = PublicPatent.build(
        patent_number="US1",
        title="Official",
        classification=DisclosureClassification.PUBLIC_OFFICIAL,
    )
    user = PublicPatent.build(
        patent_number="US2",
        title="User",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert official.classification is DisclosureClassification.PUBLIC_OFFICIAL
    assert user.classification is DisclosureClassification.PUBLIC_USER


def test_application_document_claim_prosecution_rejection_citation() -> None:
    app = PublicApplication.build(
        application_number="16/123456",
        title="Published application",
        publication_number="US2024/0123456",
        publication_date="2024-06-01",
    )
    _assert_round_trip(app)

    doc = PatentDocument.build(
        document_code="SPEC",
        document_title="Specification",
        parent_application_number="16/123456",
        media_type="application/pdf",
        page_count=42,
        content_sha256=DIGEST_A,
    )
    _assert_round_trip(doc)

    claim = PatentClaim.build(
        claim_number=1,
        claim_text="A method comprising processing data.",
        claim_kind=ClaimKind.INDEPENDENT,
        parent_patent_number="US1234567",
    )
    _assert_round_trip(claim)

    event = ProsecutionEvent.build(
        event_code="NOA",
        event_description="Notice of Allowance",
        event_date="2023-11-01",
        parent_patent_number="US1234567",
        sequence=12,
    )
    _assert_round_trip(event)

    rejection = Rejection.build(
        basis=RejectionBasis.SECTION_103,
        claim_numbers=(1, 2, 3),
        parent_application_number="16/123456",
        description="Obvious over Smith in view of Jones",
        cited_references=("US9876543", "US1111111"),
    )
    _assert_round_trip(rejection)

    citation = Citation.build(
        citation_kind=CitationKind.PATENT,
        cited_id="US9876543",
        citing_patent_number="US1234567",
        cited_title="Prior art patent",
        category="X",
    )
    _assert_round_trip(citation)

    # All stable IDs are URN-shaped and type-scoped.
    assert app.stable_id.startswith("urn:public-patent:application:sha256:")
    assert doc.stable_id.startswith("urn:public-patent:document:sha256:")
    assert claim.stable_id.startswith("urn:public-patent:claim:sha256:")
    assert event.stable_id.startswith("urn:public-patent:prosecution:sha256:")
    assert rejection.stable_id.startswith("urn:public-patent:rejection:sha256:")
    assert citation.stable_id.startswith("urn:public-patent:citation:sha256:")


def test_document_claim_require_parent() -> None:
    with pytest.raises(ValueError, match="parent_"):
        PatentDocument.build(document_code="SPEC", document_title="Spec")
    with pytest.raises(ValueError, match="parent_"):
        PatentClaim.build(claim_number=1, claim_text="text")
    with pytest.raises(ValueError, match="parent_"):
        ProsecutionEvent.build(
            event_code="X", event_description="Y", event_date="2020-01-01"
        )
    with pytest.raises(ValueError, match="parent_"):
        Rejection.build(basis=RejectionBasis.SECTION_101, claim_numbers=(1,))
    with pytest.raises(ValueError, match="citing_"):
        Citation.build(citation_kind=CitationKind.PATENT, cited_id="US1")


def test_mismatched_stable_id_rejected() -> None:
    with pytest.raises(ValueError, match="does not match content identity"):
        PublicPatent(
            schema_version=MODELS_SCHEMA_VERSION,
            stable_id="urn:public-patent:patent:sha256:" + ("0" * 64),
            patent_number="US1",
            title="Title",
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
        )


def test_canonical_json_is_byte_stable() -> None:
    record = PublicPatent.build(patent_number="US1", title="T")
    payload = record.to_dict()
    assert (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        == canonical_json(payload)
    )


def test_models_module_import_has_no_network_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing models must not open sockets or call requests."""

    def _deny(*_args, **_kwargs):  # pragma: no cover - defensive
        raise AssertionError("network I/O is forbidden in unit tests")

    monkeypatch.setattr("socket.socket.connect", _deny, raising=False)
    # Re-import path already loaded; construction alone must not network.
    PublicPatent.build(patent_number="US9", title="Offline")
    PublicApplication.build(application_number="16/9", title="Offline app")
