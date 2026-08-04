"""Unit tests for USPTO guidance PDF inventory and extraction contracts.

PATLAW-184 / PATLAW-G217 acceptance:

* Schema binds URI, sha256, publication date/cutoff, and rights review
* Unpinned latest guidance selection is forbidden
* Page/count metadata and deterministic text-extraction contracts are defined
* Guidance never elevates to binding law
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.release_policy import (
    RightsReview,
    RightsReviewStatus,
)
from ipfs_datasets_py.processors.domains.patent.uspto_guidance_pdf_contracts import (
    AUTHORITY_TIER_GUIDANCE,
    CODE_VERSION,
    CONFIG_ID,
    DEFAULT_EXTRACTION_METHOD,
    DEFAULT_NORMALIZATION_PROFILE,
    GOAL_ID,
    INTERFACE,
    PRODUCER,
    REQUIRED_DOCUMENT_IDS,
    REQUIRED_GUIDANCE_DOCUMENTS,
    SCHEMA_VERSION,
    TASK_ID,
    BindingElevationError,
    ExtractionDeterminismError,
    GapKind,
    GuidancePinError,
    IncompleteInventoryError,
    InventoryEntryStatus,
    MissingCutoffError,
    PdfTextExtractionContract,
    PrivateOrNonPublicError,
    SchemaValidationError,
    SupersessionRelation,
    UnpinnedLatestSelectionError,
    UnreviewedRightsError,
    UsptoGuidanceDocumentPin,
    UsptoGuidanceInventoryGap,
    UsptoGuidancePdfInventoryEntry,
    UsptoGuidancePdfInventoryManifest,
    UsptoGuidanceSupersessionRecord,
    assert_guidance_not_elevated,
    assert_rights_reviewed_for_public,
    build_compact_guidance_pdf_fixture,
    build_uspto_guidance_pdf_manifest,
    canonical_json,
    content_digest_of,
    content_sha256,
    default_manifest_schema_path,
    default_public_rights_review,
    deterministic_text_digest,
    load_manifest_schema,
    normalize_extracted_text,
    parse_guidance_document_version,
    reject_unpinned_latest,
    stable_guidance_pdf_identity,
    validate_extraction_determinism,
    validate_manifest_against_json_schema,
    validate_manifest_dict,
    validate_uri,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None  # type: ignore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compact_manifest_dict() -> dict:
    return build_compact_guidance_pdf_fixture()


@pytest.fixture(scope="module")
def compact_manifest(
    compact_manifest_dict: dict,
) -> UsptoGuidancePdfInventoryManifest:
    return UsptoGuidancePdfInventoryManifest.from_dict(compact_manifest_dict)


@pytest.fixture(scope="module")
def schema_path() -> Path:
    return default_manifest_schema_path()


@pytest.fixture(scope="module")
def schema(schema_path: Path) -> dict:
    assert schema_path.is_file(), f"missing schema at {schema_path}"
    return load_manifest_schema(path=schema_path)


@pytest.fixture
def public_rights() -> RightsReview:
    return default_public_rights_review()


# ---------------------------------------------------------------------------
# Schema / pin constants
# ---------------------------------------------------------------------------


def test_schema_and_task_pins() -> None:
    assert SCHEMA_VERSION == "patent.uspto_guidance_pdfs.v1"
    assert INTERFACE == "UsptoGuidancePdfInventory@1"
    assert TASK_ID == "PATLAW-184"
    assert GOAL_ID == "PATLAW-G217"
    assert PRODUCER == "producer:uspto-guidance-pdf-inventory"
    assert CONFIG_ID == "config:uspto-guidance-pdfs/v1"
    assert CODE_VERSION == "1.0.0"
    assert AUTHORITY_TIER_GUIDANCE == "guidance"


def test_required_document_catalog_is_nonempty() -> None:
    ids = [d.document_id for d in REQUIRED_GUIDANCE_DOCUMENTS]
    assert len(ids) == len(set(ids))
    assert len(REQUIRED_GUIDANCE_DOCUMENTS) >= 5
    assert "sme-2019-peg" in REQUIRED_DOCUMENT_IDS
    assert "sme-2024-ai-examples" in REQUIRED_DOCUMENT_IDS


def test_manifest_schema_file_exists_and_is_draft_2020(
    schema_path: Path, schema: dict
) -> None:
    assert schema_path.name == "uspto_guidance_pdfs.manifest.schema.json"
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("patent-uspto-guidance-pdfs.manifest.v1.schema.json")
    required = set(schema["required"])
    assert "edition_pin" in required
    assert "inventory" in required
    assert "authority_tier" in required
    assert "is_binding" in required
    pin_required = set(schema["$defs"]["documentPin"]["required"])
    assert pin_required == {"document_id", "version", "cutoff"}
    entry_required = set(schema["$defs"]["inventoryEntry"]["required"])
    for field in (
        "uri",
        "sha256",
        "publication_date",
        "cutoff",
        "rights_review",
        "page_count",
    ):
        assert field in entry_required
    assert schema["properties"]["authority_tier"]["const"] == "guidance"
    assert schema["properties"]["is_binding"]["const"] is False
    ss = schema["$defs"]["supersession"]
    assert ss["properties"]["elevates_to_law"]["const"] is False
    assert ss["properties"]["remains_guidance"]["const"] is True


# ---------------------------------------------------------------------------
# Document + version pins / unpinned latest forbidden
# ---------------------------------------------------------------------------


def test_parse_document_version_requires_both_pins() -> None:
    doc_id, ver = parse_guidance_document_version(
        document_id="sme-2019-peg", version="2019-01-07"
    )
    assert doc_id == "sme-2019-peg"
    assert ver == "2019-01-07"

    with pytest.raises(GuidancePinError):
        parse_guidance_document_version(document_id="", version="2019-01-07")
    with pytest.raises(GuidancePinError):
        parse_guidance_document_version(document_id="sme-2019-peg", version="")
    with pytest.raises(GuidancePinError):
        parse_guidance_document_version(document_id=None, version="2019-01-07")
    with pytest.raises(GuidancePinError):
        parse_guidance_document_version(document_id="sme-2019-peg", version=None)


def test_hard_coded_latest_rejected_on_document_and_version() -> None:
    with pytest.raises(GuidancePinError):
        parse_guidance_document_version(document_id="latest", version="2019-01-07")
    with pytest.raises(GuidancePinError):
        parse_guidance_document_version(document_id="sme-2019-peg", version="latest")
    with pytest.raises(GuidancePinError):
        parse_guidance_document_version(document_id="LATEST", version="2024-07-17")
    with pytest.raises(GuidancePinError):
        UsptoGuidanceDocumentPin(
            document_id="latest",
            version="2019-01-07",
            cutoff=date(2019, 1, 7),
        )
    with pytest.raises(GuidancePinError):
        UsptoGuidanceDocumentPin(
            document_id="sme-2019-peg",
            version="latest",
            cutoff=date(2019, 1, 7),
        )


def test_reject_unpinned_latest_helper() -> None:
    assert reject_unpinned_latest("2024-07-17", field_name="version") == "2024-07-17"
    with pytest.raises(UnpinnedLatestSelectionError):
        reject_unpinned_latest("latest", field_name="version")
    with pytest.raises(UnpinnedLatestSelectionError):
        reject_unpinned_latest("LATEST", field_name="document_id")


def test_uri_rejects_latest_path_segment() -> None:
    ok = validate_uri(
        "https://www.uspto.gov/sites/default/files/documents/guide.pdf"
    )
    assert ok.startswith("https://")
    with pytest.raises(UnpinnedLatestSelectionError):
        validate_uri("https://www.uspto.gov/guidance/latest/sme.pdf")
    with pytest.raises(Exception):
        validate_uri("ftp://example.com/x.pdf")


def test_document_pin_requires_cutoff() -> None:
    with pytest.raises(MissingCutoffError):
        UsptoGuidanceDocumentPin.from_dict(
            {"document_id": "sme-2019-peg", "version": "2019-01-07"}
        )


def test_document_pin_round_trip() -> None:
    pin = UsptoGuidanceDocumentPin(
        document_id="sme-2024-ai-examples",
        version="2024-07-17",
        cutoff=date(2024, 7, 17),
        publication_date=date(2024, 7, 17),
        title="2024 AI SME Guidance",
        topic="subject_matter_eligibility",
        source_url=(
            "https://www.uspto.gov/sites/default/files/documents/"
            "2024-AI-Subject-Matter-Eligibility-Guidance.pdf"
        ),
        notes="Pinned 2024 AI SME PDF",
    )
    assert pin.pin_key == "sme-2024-ai-examples-v2024-07-17"
    assert "latest" not in pin.pin_key
    restored = UsptoGuidanceDocumentPin.from_dict(pin.to_dict())
    assert restored.to_dict() == pin.to_dict()


def test_manifest_rejects_missing_edition_pin() -> None:
    payload = build_compact_guidance_pdf_fixture()
    del payload["edition_pin"]
    with pytest.raises(GuidancePinError):
        validate_manifest_dict(payload)


def test_manifest_rejects_edition_pin_without_version() -> None:
    payload = build_compact_guidance_pdf_fixture()
    pin = dict(payload["edition_pin"])
    del pin["version"]
    payload["edition_pin"] = pin
    with pytest.raises(GuidancePinError):
        validate_manifest_dict(payload)


def test_schema_rejects_latest_pins(
    schema: dict, compact_manifest_dict: dict
) -> None:
    if jsonschema is None:  # pragma: no cover
        pytest.skip("jsonschema not installed")
    validator = jsonschema.Draft202012Validator(schema)

    latest_doc = copy.deepcopy(compact_manifest_dict)
    latest_doc["edition_pin"]["document_id"] = "latest"
    assert list(validator.iter_errors(latest_doc))

    latest_ver = copy.deepcopy(compact_manifest_dict)
    latest_ver["edition_pin"]["version"] = "latest"
    assert list(validator.iter_errors(latest_ver))

    latest_entry = copy.deepcopy(compact_manifest_dict)
    latest_entry["inventory"][0]["version"] = "latest"
    assert list(validator.iter_errors(latest_entry))


# ---------------------------------------------------------------------------
# URI, sha256, publication/cutoff, rights review bindings
# ---------------------------------------------------------------------------


def test_compact_fixture_binds_uri_sha256_dates_rights(
    compact_manifest: UsptoGuidancePdfInventoryManifest,
) -> None:
    assert len(compact_manifest.inventory) >= len(REQUIRED_GUIDANCE_DOCUMENTS)
    for entry in compact_manifest.inventory:
        assert entry.uri.startswith("https://")
        assert len(entry.sha256) == 64
        assert entry.publication_date is not None
        assert entry.cutoff is not None
        assert entry.rights_review.reviewed_for_release is True
        assert entry.page_count >= 1
        assert entry.authority_tier == "guidance"
        assert entry.is_binding is False
        d = entry.to_dict()
        assert "uri" in d
        assert "sha256" in d
        assert "publication_date" in d
        assert "cutoff" in d
        assert "rights_review" in d
        assert d["rights_review"]["review_status"] == "reviewed"
        assert d["rights_review"]["redistribution_allowed"] is True


def test_entry_requires_rights_review(public_rights: RightsReview) -> None:
    with pytest.raises(UnreviewedRightsError):
        UsptoGuidancePdfInventoryEntry.from_dict(
            {
                "entry_id": "pdf-test",
                "document_id": "sme-2019-peg",
                "version": "2019-01-07",
                "uri": "https://www.uspto.gov/sites/default/files/documents/x.pdf",
                "sha256": content_sha256("bytes"),
                "publication_date": "2019-01-07",
                "cutoff": "2019-01-07",
                "page_count": 1,
                # rights_review missing
            }
        )


def test_entry_rejects_unreviewed_rights() -> None:
    unreviewed = RightsReview(
        license_expression="US-Gov-Work",
        review_status=RightsReviewStatus.UNREVIEWED,
        reviewed_by="",
        reviewed_at="",
        redistribution_allowed=False,
    )
    with pytest.raises(UnreviewedRightsError):
        UsptoGuidancePdfInventoryEntry(
            entry_id="pdf-unreviewed",
            document_id="sme-2019-peg",
            version="2019-01-07",
            uri="https://www.uspto.gov/sites/default/files/documents/x.pdf",
            sha256=content_sha256("bytes"),
            publication_date=date(2019, 1, 7),
            cutoff=date(2019, 1, 7),
            rights_review=unreviewed,
            page_count=1,
        )


def test_entry_requires_publication_and_cutoff(public_rights: RightsReview) -> None:
    with pytest.raises(MissingCutoffError):
        UsptoGuidancePdfInventoryEntry(
            entry_id="pdf-no-pub",
            document_id="sme-2019-peg",
            version="2019-01-07",
            uri="https://www.uspto.gov/sites/default/files/documents/x.pdf",
            sha256=content_sha256("bytes"),
            publication_date="",  # type: ignore[arg-type]
            cutoff=date(2019, 1, 7),
            rights_review=public_rights,
            page_count=1,
        )
    with pytest.raises(MissingCutoffError):
        UsptoGuidancePdfInventoryEntry(
            entry_id="pdf-no-cutoff",
            document_id="sme-2019-peg",
            version="2019-01-07",
            uri="https://www.uspto.gov/sites/default/files/documents/x.pdf",
            sha256=content_sha256("bytes"),
            publication_date=date(2019, 1, 7),
            cutoff="",  # type: ignore[arg-type]
            rights_review=public_rights,
            page_count=1,
        )


def test_entry_requires_sha256_and_uri(public_rights: RightsReview) -> None:
    with pytest.raises(Exception):
        UsptoGuidancePdfInventoryEntry(
            entry_id="pdf-no-uri",
            document_id="sme-2019-peg",
            version="2019-01-07",
            uri="",
            sha256=content_sha256("bytes"),
            publication_date=date(2019, 1, 7),
            cutoff=date(2019, 1, 7),
            rights_review=public_rights,
            page_count=1,
        )
    with pytest.raises(Exception):
        UsptoGuidancePdfInventoryEntry(
            entry_id="pdf-bad-sha",
            document_id="sme-2019-peg",
            version="2019-01-07",
            uri="https://www.uspto.gov/sites/default/files/documents/x.pdf",
            sha256="not-a-digest",
            publication_date=date(2019, 1, 7),
            cutoff=date(2019, 1, 7),
            rights_review=public_rights,
            page_count=1,
        )


def test_schema_requires_bindings_on_inventory_entries(
    schema: dict, compact_manifest_dict: dict
) -> None:
    if jsonschema is None:  # pragma: no cover
        pytest.skip("jsonschema not installed")
    validator = jsonschema.Draft202012Validator(schema)

    for field in ("uri", "sha256", "publication_date", "cutoff", "rights_review"):
        payload = copy.deepcopy(compact_manifest_dict)
        del payload["inventory"][0][field]
        assert list(validator.iter_errors(payload)), f"expected errors without {field}"


def test_assert_rights_reviewed_for_public(public_rights: RightsReview) -> None:
    assert assert_rights_reviewed_for_public(public_rights).reviewed_for_release
    with pytest.raises(UnreviewedRightsError):
        assert_rights_reviewed_for_public(None)
    with pytest.raises(UnreviewedRightsError):
        assert_rights_reviewed_for_public(
            {
                "license_expression": "US-Gov-Work",
                "review_status": "unreviewed",
                "reviewed_by": "",
                "reviewed_at": "",
                "redistribution_allowed": False,
            }
        )


# ---------------------------------------------------------------------------
# Deterministic text extraction
# ---------------------------------------------------------------------------


def test_normalize_and_digest_are_deterministic() -> None:
    a = "Hello\r\n  world\t\tguidance  "
    b = "Hello\n world guidance"
    assert normalize_extracted_text(a) == normalize_extracted_text(b)
    assert deterministic_text_digest(a) == deterministic_text_digest(b)
    assert deterministic_text_digest(a) != deterministic_text_digest("other")


def test_extraction_contract_from_text_round_trip() -> None:
    contract = PdfTextExtractionContract.from_extracted_text(
        "USPTO SME Guidance\n\nExample text.",
        page_count=10,
        method=DEFAULT_EXTRACTION_METHOD,
    )
    assert contract.page_count == 10
    assert contract.method == DEFAULT_EXTRACTION_METHOD
    assert contract.normalization_profile == DEFAULT_NORMALIZATION_PROFILE
    assert len(contract.text_sha256) == 64
    restored = PdfTextExtractionContract.from_dict(contract.to_dict())
    assert restored.to_dict() == contract.to_dict()


def test_extraction_rejects_latest_method() -> None:
    with pytest.raises(UnpinnedLatestSelectionError):
        PdfTextExtractionContract(
            method="latest",
            text_sha256=content_sha256("x"),
            page_count=1,
        )


def test_validate_extraction_determinism() -> None:
    pdf = b"%PDF-1.4 fixture bytes"
    text = "same extraction"
    dig = validate_extraction_determinism(
        pdf_bytes=pdf, text_a=text, text_b="same   extraction"
    )
    assert dig == deterministic_text_digest(text)
    with pytest.raises(ExtractionDeterminismError):
        validate_extraction_determinism(
            pdf_bytes=pdf, text_a="alpha", text_b="beta"
        )


def test_compact_fixture_includes_extraction(
    compact_manifest: UsptoGuidancePdfInventoryManifest,
) -> None:
    with_ext = [e for e in compact_manifest.inventory if e.extraction is not None]
    assert len(with_ext) == len(compact_manifest.inventory)
    assert compact_manifest.counts.with_extraction == len(with_ext)
    for entry in with_ext:
        assert entry.extraction is not None
        assert entry.extraction.page_count == entry.page_count
        assert len(entry.extraction.text_sha256) == 64


# ---------------------------------------------------------------------------
# Guidance never elevates to binding law
# ---------------------------------------------------------------------------


def test_guidance_tier_forced_on_every_inventory_entry(
    compact_manifest: UsptoGuidancePdfInventoryManifest,
) -> None:
    for entry in compact_manifest.inventory:
        assert entry.authority_tier == "guidance"
        assert entry.is_binding is False
        d = entry.to_dict()
        assert d["authority_tier"] == "guidance"
        assert d["is_binding"] is False


def test_manifest_authority_is_guidance_not_binding(
    compact_manifest: UsptoGuidancePdfInventoryManifest,
) -> None:
    assert compact_manifest.authority_tier == "guidance"
    assert compact_manifest.is_binding is False
    d = compact_manifest.to_dict()
    assert d["authority_tier"] == "guidance"
    assert d["is_binding"] is False


def test_entry_rejects_binding_flag(public_rights: RightsReview) -> None:
    with pytest.raises(BindingElevationError):
        UsptoGuidancePdfInventoryEntry(
            entry_id="pdf-binding",
            document_id="sme-2019-peg",
            version="2019-01-07",
            uri="https://www.uspto.gov/sites/default/files/documents/x.pdf",
            sha256=content_sha256("bytes"),
            publication_date=date(2019, 1, 7),
            cutoff=date(2019, 1, 7),
            rights_review=public_rights,
            page_count=1,
            is_binding=True,
        )


def test_entry_rejects_non_guidance_tier(public_rights: RightsReview) -> None:
    with pytest.raises(BindingElevationError):
        UsptoGuidancePdfInventoryEntry(
            entry_id="pdf-elevated",
            document_id="sme-2019-peg",
            version="2019-01-07",
            uri="https://www.uspto.gov/sites/default/files/documents/x.pdf",
            sha256=content_sha256("bytes"),
            publication_date=date(2019, 1, 7),
            cutoff=date(2019, 1, 7),
            rights_review=public_rights,
            page_count=1,
            authority_tier="official-base",
        )


def test_supersession_rejects_elevation_to_law() -> None:
    with pytest.raises(BindingElevationError):
        UsptoGuidanceSupersessionRecord(
            successor_id="pdf-new",
            predecessor_id="pdf-old",
            elevates_to_law=True,
        )
    with pytest.raises(BindingElevationError):
        UsptoGuidanceSupersessionRecord(
            successor_id="pdf-new",
            predecessor_id="pdf-old",
            remains_guidance=False,
        )


def test_assert_guidance_not_elevated_helper() -> None:
    assert_guidance_not_elevated(authority_tier="guidance", is_binding=False)
    with pytest.raises(BindingElevationError):
        assert_guidance_not_elevated(authority_tier="statute")
    with pytest.raises(BindingElevationError):
        assert_guidance_not_elevated(is_binding=True)
    with pytest.raises(BindingElevationError):
        assert_guidance_not_elevated(elevates_to_law=True)


def test_manifest_rejects_binding_elevation_in_payload(
    compact_manifest_dict: dict,
) -> None:
    payload = copy.deepcopy(compact_manifest_dict)
    payload["is_binding"] = True
    with pytest.raises(BindingElevationError):
        validate_manifest_dict(payload)

    payload2 = copy.deepcopy(compact_manifest_dict)
    payload2["authority_tier"] = "official-base"
    with pytest.raises(BindingElevationError):
        validate_manifest_dict(payload2)

    payload3 = copy.deepcopy(compact_manifest_dict)
    payload3["supersessions"][0]["elevates_to_law"] = True
    with pytest.raises(BindingElevationError):
        validate_manifest_dict(payload3)


def test_schema_rejects_binding_or_non_guidance(
    schema: dict, compact_manifest_dict: dict
) -> None:
    if jsonschema is None:  # pragma: no cover
        pytest.skip("jsonschema not installed")
    validator = jsonschema.Draft202012Validator(schema)

    binding = copy.deepcopy(compact_manifest_dict)
    binding["is_binding"] = True
    assert list(validator.iter_errors(binding))

    elevated = copy.deepcopy(compact_manifest_dict)
    elevated["authority_tier"] = "regulation"
    assert list(validator.iter_errors(elevated))

    ss = copy.deepcopy(compact_manifest_dict)
    ss["supersessions"][0]["elevates_to_law"] = True
    assert list(validator.iter_errors(ss))


def test_private_classification_rejected(public_rights: RightsReview) -> None:
    with pytest.raises(PrivateOrNonPublicError):
        UsptoGuidancePdfInventoryEntry(
            entry_id="pdf-private",
            document_id="sme-2019-peg",
            version="2019-01-07",
            uri="https://www.uspto.gov/sites/default/files/documents/x.pdf",
            sha256=content_sha256("bytes"),
            publication_date=date(2019, 1, 7),
            cutoff=date(2019, 1, 7),
            rights_review=public_rights,
            page_count=1,
            classification="confidential_application",
        )


# ---------------------------------------------------------------------------
# Digests, round-trip, supersession retention, JSON Schema
# ---------------------------------------------------------------------------


def test_compact_manifest_round_trip(
    compact_manifest: UsptoGuidancePdfInventoryManifest,
) -> None:
    first = compact_manifest.to_dict()
    restored = UsptoGuidancePdfInventoryManifest.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert restored.inventory_digest_sha256 == content_digest_of(
        [e.to_dict() for e in restored.inventory]
    )


def test_inventory_digest_mismatch_rejected(compact_manifest_dict: dict) -> None:
    payload = copy.deepcopy(compact_manifest_dict)
    payload["inventory_digest_sha256"] = "0" * 64
    with pytest.raises(SchemaValidationError):
        validate_manifest_dict(payload)


def test_content_sha256_deterministic() -> None:
    assert content_sha256("abc") == content_sha256(b"abc")
    assert content_sha256("abc") != content_sha256("abd")


def test_valid_fixture_passes_json_schema(
    schema: dict, compact_manifest_dict: dict
) -> None:
    if jsonschema is None:  # pragma: no cover
        pytest.skip("jsonschema not installed")
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(compact_manifest_dict), key=lambda e: list(e.path)
    )
    assert errors == [], f"unexpected schema errors: {[e.message for e in errors[:5]]}"
    validate_manifest_against_json_schema(compact_manifest_dict, schema=schema)


def test_schema_rejects_empty_inventory(
    schema: dict, compact_manifest_dict: dict
) -> None:
    if jsonschema is None:  # pragma: no cover
        pytest.skip("jsonschema not installed")
    payload = copy.deepcopy(compact_manifest_dict)
    payload["inventory"] = []
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(payload))


def test_empty_inventory_rejected(public_rights: RightsReview) -> None:
    pin = UsptoGuidanceDocumentPin(
        document_id="uspto-guidance-inventory",
        version="2024-07-17",
        cutoff=date(2024, 7, 17),
    )
    with pytest.raises(IncompleteInventoryError):
        build_uspto_guidance_pdf_manifest(edition_pin=pin, inventory=[])


def test_supersession_and_gap_round_trips() -> None:
    edge = UsptoGuidanceSupersessionRecord(
        successor_id="pdf-sme-2024-ai-examples-v2024-07-17",
        predecessor_id="pdf-sme-2019-peg-october-update-v2019-10-17",
        relation=SupersessionRelation.UPDATES,
        effective_date=date(2024, 7, 17),
        reason="Later SME guidance updates earlier PDF; prior retained as evidence.",
    )
    assert edge.to_dict()["elevates_to_law"] is False
    assert edge.to_dict()["remains_guidance"] is True
    assert (
        UsptoGuidanceSupersessionRecord.from_dict(edge.to_dict()).to_dict()
        == edge.to_dict()
    )

    gap = UsptoGuidanceInventoryGap(
        gap_id="gap-unavailable-enablement",
        kind=GapKind.UNAVAILABLE,
        document_id="enablement-2024",
        reason="PDF temporarily unavailable (HTTP 404).",
        version="2024-01-10",
        uri="https://www.uspto.gov/sites/default/files/documents/enablement_guidelines.pdf",
    )
    assert gap.to_dict()["authority_tier"] == "guidance"
    assert UsptoGuidanceInventoryGap.from_dict(gap.to_dict()).to_dict() == gap.to_dict()


def test_supersession_retains_prior_editions_in_fixture(
    compact_manifest: UsptoGuidancePdfInventoryManifest,
) -> None:
    # Both predecessor and successor document ids appear in inventory.
    ids = {e.entry_id for e in compact_manifest.inventory}
    assert "pdf-sme-2019-peg-october-update-v2019-10-17" in ids
    assert "pdf-sme-2024-ai-examples-v2024-07-17" in ids
    assert compact_manifest.counts.supersession_edges >= 1
    for edge in compact_manifest.supersessions:
        assert edge.remains_guidance is True
        assert edge.elevates_to_law is False


def test_stable_identity_never_latest() -> None:
    ident = stable_guidance_pdf_identity(
        document_id="sme-2019-peg", version="2019-01-07"
    )
    assert ident == "uspto-guidance:us:sme-2019-peg:v2019-01-07"
    assert "latest" not in ident
    with pytest.raises(GuidancePinError):
        stable_guidance_pdf_identity(document_id="latest", version="2019-01-07")


def test_compact_fixture_is_bounded_size(compact_manifest_dict: dict) -> None:
    raw = json.dumps(compact_manifest_dict, sort_keys=True, separators=(",", ":"))
    assert len(raw.encode("utf-8")) < 200_000


def test_build_manifest_helper_matches_fixture_structure() -> None:
    payload = build_compact_guidance_pdf_fixture(
        include_extraction=False,
        include_supersession=False,
        inventory_cutoff="2024-01-01",
    )
    manifest = validate_manifest_dict(payload)
    assert manifest.edition_pin.version == "2024-01-01"
    assert manifest.counts.with_extraction == 0
    assert manifest.counts.supersession_edges == 0
    assert {e.document_id for e in manifest.inventory} == REQUIRED_DOCUMENT_IDS


def test_entry_status_gap_allows_unreviewed_rights() -> None:
    unreviewed = RightsReview(
        license_expression="US-Gov-Work",
        review_status=RightsReviewStatus.UNREVIEWED,
        reviewed_by="",
        reviewed_at="",
        redistribution_allowed=False,
    )
    entry = UsptoGuidancePdfInventoryEntry(
        entry_id="pdf-gap-row",
        document_id="enablement-2024",
        version="2024-01-10",
        uri="https://www.uspto.gov/sites/default/files/documents/enablement_guidelines.pdf",
        sha256=content_sha256("gap-placeholder"),
        publication_date=date(2024, 1, 10),
        cutoff=date(2024, 1, 10),
        rights_review=unreviewed,
        page_count=0,
        status=InventoryEntryStatus.GAP,
        gap_reason="PDF not yet acquired; rights review deferred until fetch.",
    )
    assert entry.status is InventoryEntryStatus.GAP
    assert entry.gap_reason is not None
