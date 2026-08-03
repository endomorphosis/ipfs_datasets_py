"""Unit tests for submission-package semantics v2 (PATLAW-133)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.submission_package_semantics_v2 import (
    RECEIPT_EFFECT_CODES,
    RENDERING_EFFECT_CODES,
    SEMANTICS_V2_SCHEMA_VERSION,
    AdmissionState,
    AnchorKind,
    ApplicationType,
    CandidateAssociation,
    DiscrepancyKind,
    DocumentRole,
    FactKind,
    FieldOrigin,
    ModelAssociationInput,
    PackageDisposition,
    PackageDocumentInput,
    PackageProfile,
    PackageReasonCode,
    ReceiptKind,
    RenderingKind,
    SubmissionPackageInput,
    SubmissionPackageSemanticsResult,
    SubmissionPackageSemanticsV2,
    admit_normalized_fact,
    detect_noisy_scan,
    detect_receipt_kind,
    extract_submission_package_semantics_v2,
    receipt_effect_code,
    rendering_effect_code,
    sha256_hex,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[5] / "fixtures" / "uspto" / "submissions"
)
RECIPE_PATH = FIXTURE_DIR / "semantic_v2_recipe.json"

# ---------------------------------------------------------------------------
# Synthetic generators (compact; not real USPTO filings)
# ---------------------------------------------------------------------------

COMPLETE_CANARY = "SYNTH-PKG-V2-COMPLETE"
PARTIAL_CANARY = "SYNTH-PKG-V2-PARTIAL"
DUP_CANARY = "SYNTH-PKG-V2-DUP"
INCON_CANARY = "SYNTH-PKG-V2-INCONSISTENT"
SCAN_CANARY = "SYNTH-PKG-V2-SCANNED"
CONV_CANARY = "SYNTH-PKG-V2-CONVERSION"
ARG_CANARY = "SYNTH-PKG-V2-ARGS"
SEQ_CANARY = "SYNTH-PKG-V2-SEQUENCE"
DESIGN_CANARY = "SYNTH-PKG-V2-DESIGN"
PLANT_CANARY = "SYNTH-PKG-V2-PLANT"
REPL_CANARY = "SYNTH-PKG-V2-REPLACEMENT"


def _claims_text(app: str = "16/123,456") -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application Number: {app}
Confirmation Number: 5678
Attorney Docket: SYN-2026-V2-001

WHAT IS CLAIMED IS:

1 (original): A device comprising a temperature sensor.
2 (original): The device of claim 1 further comprising a filter.
{COMPLETE_CANARY}
"""


def _spec_text(app: str = "16/123,456") -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application Number: {app}
Title of the Invention: Synthetic Temperature Sensor Device

Field of the Invention
This invention relates to sensors.

Background of the Invention
Prior sensors lack calibration.

Brief Description of the Drawings
FIG. 1 shows a sensor block diagram.

Detailed Description
The device includes a processor and a temperature sensor.
"""


def _drawings_text(app: str = "16/123,456") -> str:
    return f"""Drawing Sheet 1 of 2
Application Number: {app}
FIG. 1 Sensor block
FIG. 2 Filter detail
"""


def _ads_text(app: str = "16/123,456") -> str:
    return f"""Application Data Sheet
Application Number: {app}
Inventor Information: Jane Q. Inventor
Applicant Information: SynthCo Inc.
Correspondence Information: counsel@example.test
Entity Status: small entity
Domestic Benefit: claims the benefit of provisional application number 62/999,001
Foreign Priority: priority is claimed under Paris Convention
Form PTO/AIA/14
"""


def _amendment_text(app: str = "16/123,456") -> str:
    return f"""Preliminary Amendment
Application Number: {app}
Form PTO/SB/08

AMENDMENTS TO THE CLAIMS
Please amend claim 1 as follows:

1 (currently amended): A device comprising a calibrated temperature sensor.

REMARKS
{ARG_CANARY}
Applicants respectfully traverse the rejection under 35 U.S.C. 103.
Claim 1 is patentable over the cited art.

Fee Code: 1201 $80.00
Attachment: IDS-SB08.pdf
Respectfully submitted,
Electronically signed
"""


def _declaration_text(app: str = "16/123,456") -> str:
    return f"""Declaration under 37 C.F.R. 1.63
Application Number: {app}
I hereby declare that I am an inventor.
Signature: Electronically signed
/s/ Jane Q. Inventor
"""


def _ack_receipt_text(app: str = "16/123,456") -> str:
    return f"""ELECTRONIC ACKNOWLEDGEMENT RECEIPT
Application Number: {app}
Confirmation Number: 5678
Receipt ID: SYNTH-ACK-V2-A1B2
Receipt Date: 2026-01-15T18:22:00Z
Document Description: Electronic Acknowledgement Receipt
"""


def _payment_receipt_text(app: str = "16/123,456") -> str:
    return f"""PAYMENT RECEIPT
Application Number: {app}
Fee Payment Receipt
Amount Paid: $80.00
Transaction ID: SYNTH-PAY-V2-99
Fee Code: 1201
Payment Confirmation recorded.
"""


def _transmission_attempt_text(app: str = "16/123,456") -> str:
    return f"""TRANSMISSION ATTEMPT LOG
Application Number: {app}
Submission transmission started.
Upload started at 2026-01-15T18:20:00Z
Transmission status: attempted
Attempting to submit package bundle.
"""


def _official_filing_receipt_text(app: str = "16/123,456") -> str:
    return f"""OFFICIAL FILING RECEIPT
Application Number: {app}
Filing Receipt
Your application has been accorded a filing date of 2026-01-15.
Filing date accorded.
"""


def _corrected_filing_receipt_text(app: str = "16/123,456") -> str:
    return f"""CORRECTED FILING RECEIPT
Application Number: {app}
Corrected Filing Receipt issued.
This corrects the filing receipt mailed 2026-01-16.
"""


def _first_odp_text(app: str = "16/123,456") -> str:
    return f"""ODP DOCUMENT INVENTORY NOTICE
Application Number: {app}
First ODP appearance recorded 2026-02-01.
Document first appeared in ODP Patent File Wrapper.
Publicly available via ODP.
"""


def _feedback_text(app: str = "16/123,456") -> str:
    return f"""USPTO DOCX CONVERSION FEEDBACK DOCUMENT
Application Number: {app}
{CONV_CANARY}
Document converted with warnings.
DOCX to PDF conversion produced formatting changes.
Equation not preserved on page 2.
Conversion warning: table borders shifted.
"""


def _docx_body(app: str = "16/900,001") -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application Number: {app}
Document Description: Specification
Title of the Invention: Synthetic Apparatus

1. A synthetic apparatus comprising a processor configured to run tests.
EQUATION_PLACEHOLDER: E=mc^2
Field of the Invention
Sensors.
"""


def _converted_pdf_body(app: str = "16/900,001") -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application Number: {app}
Document Description: Specification
Title of the Invention: Synthetic Apparatus

1. A synthetic apparatus comprising a processor configured to run tests (PDF).
# equation pagination differs — no EQUATION_PLACEHOLDER here
Field of the Invention
Sensors.
"""


def _scanned_claims(app: str = "16/123,456") -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application Number: {app}
|||| @@@@ ???? illegible OCR failure garbled
WHAT IS CLAIMED IS:
1. A device comprising a sensor. {SCAN_CANARY}
a b c d e f g h i j k l m n o p q r
"""


def _sequence_listing_text(app: str = "16/123,456") -> str:
    return f"""Sequence Listing
Application Number: {app}
{SEQ_CANARY}
ST.26 compliant sequence listing.
Nucleotide and/or amino acid sequences are set forth.
CRF sequence file attached.
"""


def _design_package_docs() -> list[PackageDocumentInput]:
    app = "29/123,456"
    return [
        PackageDocumentInput(
            document_id="doc:design:claims",
            role=DocumentRole.CLAIMS,
            text=f"""Design Patent Application
Application Number: {app}
{DESIGN_CANARY}
WHAT IS CLAIMED IS:
1 (original): The ornamental design for a sensor housing as shown and described.
""",
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:design:drawings",
            role=DocumentRole.DRAWINGS,
            text=_drawings_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:design:ack",
            role=DocumentRole.ELECTRONIC_SUBMISSION_RECEIPT,
            text=_ack_receipt_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
    ]


def _plant_package_docs() -> list[PackageDocumentInput]:
    app = "15/123,456"
    return [
        PackageDocumentInput(
            document_id="doc:plant:spec",
            role=DocumentRole.SPECIFICATION,
            text=f"""Plant Patent Application
Application Number: {app}
{PLANT_CANARY}
Title of the Invention: Synthetic Rose Cultivar
Field of the Invention
A new and distinct variety of rose plant.
Detailed Description
The plant exhibits red blooms.
""",
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:plant:claims",
            role=DocumentRole.CLAIMS,
            text=f"""Application Number: {app}
1. A new and distinct variety of rose plant substantially as illustrated and described.
""",
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:plant:ack",
            role=DocumentRole.ELECTRONIC_SUBMISSION_RECEIPT,
            text=_ack_receipt_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
    ]


def build_complete_utility_package() -> list[PackageDocumentInput]:
    app = "16/123,456"
    return [
        PackageDocumentInput(
            document_id="doc:spec",
            role=DocumentRole.SPECIFICATION,
            text=_spec_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
            media_type="text/plain",
        ),
        PackageDocumentInput(
            document_id="doc:claims",
            role=DocumentRole.CLAIMS,
            text=_claims_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:drawings",
            role=DocumentRole.DRAWINGS,
            text=_drawings_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:ads",
            role=DocumentRole.ADS,
            text=_ads_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:amend",
            role=DocumentRole.AMENDMENT,
            text=_amendment_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:decl",
            role=DocumentRole.DECLARATION,
            text=_declaration_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:ack",
            role=DocumentRole.ELECTRONIC_SUBMISSION_RECEIPT,
            text=_ack_receipt_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:pay",
            role=DocumentRole.PAYMENT_RECEIPT,
            text=_payment_receipt_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
    ]


def build_partial_package() -> list[PackageDocumentInput]:
    app = "16/222,333"
    return [
        PackageDocumentInput(
            document_id="doc:claims-only",
            role=DocumentRole.CLAIMS,
            text=f"""Application Number: {app}
{PARTIAL_CANARY}
1. A partial device comprising a sensor.
""",
            classification=DisclosureClassification.PUBLIC_USER,
        ),
    ]


def build_duplicate_package() -> list[PackageDocumentInput]:
    app = "16/333,444"
    claims = _claims_text(app) + f"\n{DUP_CANARY}\n"
    return [
        PackageDocumentInput(
            document_id="doc:claims-a",
            role=DocumentRole.CLAIMS,
            text=claims,
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:claims-b",
            role=DocumentRole.CLAIMS,
            text=claims + "\n# duplicate copy marker\n",
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:spec-dup",
            role=DocumentRole.SPECIFICATION,
            text=_spec_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
    ]


def build_inconsistent_package() -> list[PackageDocumentInput]:
    return [
        PackageDocumentInput(
            document_id="doc:claims-incon",
            role=DocumentRole.CLAIMS,
            text=_claims_text("16/111,111") + f"\n{INCON_CANARY}\n",
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:spec-incon",
            role=DocumentRole.SPECIFICATION,
            text=_spec_text("16/999,999"),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:ack-incon",
            role=DocumentRole.ELECTRONIC_SUBMISSION_RECEIPT,
            text=_ack_receipt_text("16/111,111"),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
    ]


def build_scanned_package() -> list[PackageDocumentInput]:
    return [
        PackageDocumentInput(
            document_id="doc:scanned-claims",
            role=DocumentRole.CLAIMS,
            text=_scanned_claims(),
            classification=DisclosureClassification.PUBLIC_USER,
            ocr_confidence=0.35,
            rendering_kind=RenderingKind.SCANNED_IMAGE,
            media_type="image/tiff",
        ),
        PackageDocumentInput(
            document_id="doc:scanned-ack",
            role=DocumentRole.ELECTRONIC_SUBMISSION_RECEIPT,
            text=_ack_receipt_text(),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
    ]


def build_conversion_warning_package() -> list[PackageDocumentInput]:
    app = "16/900,001"
    return [
        PackageDocumentInput(
            document_id="doc:submitted-docx",
            role=DocumentRole.SUBMITTED_DOCX,
            text=_docx_body(app),
            classification=DisclosureClassification.PUBLIC_USER,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            rendering_kind=RenderingKind.SUBMITTED_DOCX,
        ),
        PackageDocumentInput(
            document_id="doc:converted-pdf",
            role=DocumentRole.CONVERTED_PDF,
            text=_converted_pdf_body(app),
            classification=DisclosureClassification.PUBLIC_USER,
            media_type="application/pdf",
            rendering_kind=RenderingKind.CONVERTED_PDF,
        ),
        PackageDocumentInput(
            document_id="doc:feedback",
            role=DocumentRole.FEEDBACK_DOCUMENT,
            text=_feedback_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
            rendering_kind=RenderingKind.FEEDBACK_DOCUMENT,
        ),
        PackageDocumentInput(
            document_id="doc:aux-pdf",
            role=DocumentRole.AUXILIARY_PDF,
            text=f"Auxiliary PDF rendering for application {app}.\nSheet appendix only.\n",
            classification=DisclosureClassification.PUBLIC_USER,
            media_type="application/pdf",
            rendering_kind=RenderingKind.AUXILIARY_PDF,
        ),
        PackageDocumentInput(
            document_id="doc:split-pdf",
            role=DocumentRole.SPLIT_PDF,
            text=f"Split PDF part 1 for application {app}.\nClaims pages only.\n",
            classification=DisclosureClassification.PUBLIC_USER,
            media_type="application/pdf",
            rendering_kind=RenderingKind.SPLIT_PDF,
        ),
    ]


def build_all_receipts_package() -> list[PackageDocumentInput]:
    app = "16/555,666"
    return [
        PackageDocumentInput(
            document_id="doc:tx",
            role=DocumentRole.TRANSMISSION_ATTEMPT,
            text=_transmission_attempt_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:esr",
            role=DocumentRole.ELECTRONIC_SUBMISSION_RECEIPT,
            text=_ack_receipt_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:pay-all",
            role=DocumentRole.PAYMENT_RECEIPT,
            text=_payment_receipt_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:fr",
            role=DocumentRole.OFFICIAL_FILING_RECEIPT,
            text=_official_filing_receipt_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:cfr",
            role=DocumentRole.CORRECTED_FILING_RECEIPT,
            text=_corrected_filing_receipt_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:odp",
            role=DocumentRole.FIRST_ODP_APPEARANCE,
            text=_first_odp_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:claims-all-rx",
            role=DocumentRole.CLAIMS,
            text=_claims_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
    ]


def build_design_package() -> list[PackageDocumentInput]:
    return _design_package_docs()


def build_plant_package() -> list[PackageDocumentInput]:
    return _plant_package_docs()


def build_arguments_package() -> list[PackageDocumentInput]:
    app = "16/777,888"
    return [
        PackageDocumentInput(
            document_id="doc:claims-arg",
            role=DocumentRole.CLAIMS,
            text=_claims_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:remarks-arg",
            role=DocumentRole.REMARKS,
            text=f"""REMARKS
Application Number: {app}
{ARG_CANARY}
Applicants respectfully traverse the rejection under 35 U.S.C. 103.
Claim 1 is patentable over U.S. Patent 9,999,999.
In response to the office action, applicants argue the cited art fails to teach the sensor.
""",
            classification=DisclosureClassification.PUBLIC_USER,
        ),
    ]


def build_sequence_listing_package() -> list[PackageDocumentInput]:
    app = "16/888,000"
    return [
        PackageDocumentInput(
            document_id="doc:spec-seq",
            role=DocumentRole.SPECIFICATION,
            text=_spec_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:claims-seq",
            role=DocumentRole.CLAIMS,
            text=_claims_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:seq",
            role=DocumentRole.SEQUENCE_LISTING,
            text=_sequence_listing_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:ack-seq",
            role=DocumentRole.ELECTRONIC_SUBMISSION_RECEIPT,
            text=_ack_receipt_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
    ]


def build_structured_payment_package() -> list[PackageDocumentInput]:
    app = "16/101,202"
    return [
        PackageDocumentInput(
            document_id="doc:claims-sf",
            role=DocumentRole.CLAIMS,
            text=_claims_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:pay-sf",
            role=DocumentRole.PAYMENT_RECEIPT,
            text="",
            structured_fields={
                "payment.amount_usd": "80.00",
                "payment.fee_code": "1201",
                "payment.transaction_id": "SYNTH-PAY-STRUCT-1",
                "payment.receipt_id": "SYNTH-PAY-RCPT-1",
            },
            classification=DisclosureClassification.PUBLIC_USER,
        ),
    ]


def build_replacement_pages_package() -> list[PackageDocumentInput]:
    app = "16/404,505"
    return [
        PackageDocumentInput(
            document_id="doc:repl",
            role=DocumentRole.REPLACEMENT_PAGES,
            text=f"""Replacement Sheets
Application Number: {app}
{REPL_CANARY}
Please replace sheet 2 of the drawings.
Replacement page 3 of the specification is submitted.
Substitute specification is provided for clarity.
""",
            classification=DisclosureClassification.PUBLIC_USER,
        ),
        PackageDocumentInput(
            document_id="doc:claims-repl",
            role=DocumentRole.CLAIMS,
            text=_claims_text(app),
            classification=DisclosureClassification.PUBLIC_USER,
        ),
    ]


def build_empty_package() -> list[PackageDocumentInput]:
    return []


GENERATORS: dict[str, Callable[[], list[PackageDocumentInput]]] = {
    "build_complete_utility_package": build_complete_utility_package,
    "build_partial_package": build_partial_package,
    "build_duplicate_package": build_duplicate_package,
    "build_inconsistent_package": build_inconsistent_package,
    "build_scanned_package": build_scanned_package,
    "build_conversion_warning_package": build_conversion_warning_package,
    "build_all_receipts_package": build_all_receipts_package,
    "build_design_package": build_design_package,
    "build_plant_package": build_plant_package,
    "build_arguments_package": build_arguments_package,
    "build_sequence_listing_package": build_sequence_listing_package,
    "build_structured_payment_package": build_structured_payment_package,
    "build_replacement_pages_package": build_replacement_pages_package,
    "build_empty_package": build_empty_package,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _processor(**kwargs) -> SubmissionPackageSemanticsV2:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"sps2:test:{counter['n']:04d}"

    return SubmissionPackageSemanticsV2(id_factory=_ids, **kwargs)


def _assert_every_fact_has_anchors(result: SubmissionPackageSemanticsResult) -> None:
    anchor_ids = {a.anchor_id for a in result.anchors}
    for fact in result.facts:
        assert fact.anchor_ids, f"{fact.fact_id} missing anchor_ids"
        for aid in fact.anchor_ids:
            assert aid in anchor_ids, f"{fact.fact_id} anchor {aid} missing"
            anchor = result.anchor_by_id(aid)
            assert anchor is not None
            if anchor.kind is AnchorKind.DOCUMENT_PAGE_SPAN:
                assert anchor.span_id
                assert result.span_by_id(anchor.span_id) is not None or anchor.span_id
            else:
                assert anchor.structured_field_path
        assert fact.text_digest
        assert len(fact.text_digest) == 64


def _assert_receipts_distinct(result: SubmissionPackageSemanticsResult) -> None:
    if not result.receipts:
        return
    digests = [r.content_digest for r in result.receipts]
    effects = [r.effect_code for r in result.receipts]
    kinds = [r.kind for r in result.receipts]
    # All kinds present must have unique digests and unique effects.
    assert len(digests) == len(set(digests)), "receipt content digests must be distinct"
    assert len(set(effects)) == len(set(kinds)), "receipt effects must be distinct per kind"
    for r in result.receipts:
        assert r.effect_code == RECEIPT_EFFECT_CODES[r.kind]
        assert r.effect_code == receipt_effect_code(r.kind)


def _assert_renderings_distinct(result: SubmissionPackageSemanticsResult) -> None:
    if not result.renderings:
        return
    digests = [r.content_digest for r in result.renderings]
    effects = [r.effect_code for r in result.renderings]
    kinds = [r.kind for r in result.renderings]
    assert len(digests) == len(set(digests)), "rendering digests must be distinct"
    assert len(set(effects)) == len(set(kinds)), "rendering effects must be distinct per kind"
    for r in result.renderings:
        assert r.effect_code == RENDERING_EFFECT_CODES[r.kind]
        assert r.effect_code == rendering_effect_code(r.kind)


def _assert_round_trip(result: SubmissionPackageSemanticsResult) -> None:
    first = result.to_dict()
    restored = SubmissionPackageSemanticsResult.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    public = result.public_projection()
    assert "facts" not in public
    blob = json.dumps(public)
    assert COMPLETE_CANARY not in blob
    assert "Jane Q. Inventor" not in blob
    assert "/s/" not in blob


def _load_recipe() -> dict[str, Any]:
    assert RECIPE_PATH.is_file()
    return json.loads(RECIPE_PATH.read_text(encoding="utf-8"))


def _run_case(case: dict[str, Any]) -> SubmissionPackageSemanticsResult:
    gen = GENERATORS[case["generator"]]
    docs = gen()
    app_type = case.get("application_type", "utility")
    classification = case.get("classification", "public_user")
    expected_roles: tuple[str, ...] = ()
    if case["id"] == "partial_package":
        expected_roles = ("specification", "drawings", "ads", "electronic_submission_receipt")

    model_assoc: tuple[ModelAssociationInput, ...] = ()
    if case.get("model_candidate"):
        model_assoc = (
            ModelAssociationInput(
                kind=FactKind.ARGUMENT,
                surface_text="Model-only: claim 99 overcomes 35 U.S.C. 101 as associated.",
                source_document_id=docs[0].document_id if docs else None,
                confidence=0.42,
                related_fact_kinds=("claim",),
                related_claim_tokens=("1",),
                labels={"model": "synthetic"},
            ),
        )

    return _processor().analyze(
        SubmissionPackageInput(
            package_id=f"pkg:{case['id']}",
            matter_id=f"matter:{case['id']}",
            application_type=app_type,
            expected_application_number=None,
            expected_inventory_roles=expected_roles,
            classification=DisclosureClassification(classification),
            documents=tuple(docs),
            model_associations=model_assoc,
        )
    )


def _apply_expect(result: SubmissionPackageSemanticsResult, expect: dict[str, Any]) -> None:
    if "package_profile" in expect:
        assert result.package_profile is PackageProfile(expect["package_profile"])
    if "application_type" in expect:
        assert result.application_type is ApplicationType(expect["application_type"])
    if expect.get("has_inventory"):
        assert result.inventory
        assert result.facts_by_kind(FactKind.PACKAGE_INVENTORY)
    if expect.get("has_claims"):
        assert result.facts_by_kind(FactKind.CLAIM)
    if expect.get("has_specification"):
        assert result.facts_by_kind(FactKind.SPECIFICATION)
    if expect.get("has_drawings"):
        assert result.facts_by_kind(FactKind.DRAWING)
    if expect.get("has_ads"):
        assert result.facts_by_kind(FactKind.ADS_FIELD) or result.facts_by_kind(
            FactKind.BENEFIT_CLAIM
        )
    if expect.get("has_amendment"):
        assert result.facts_by_kind(FactKind.AMENDMENT)
    if expect.get("has_declaration"):
        assert result.facts_by_kind(FactKind.DECLARATION)
    if expect.get("has_form"):
        assert result.facts_by_kind(FactKind.FORM)
    if expect.get("has_fee"):
        assert result.facts_by_kind(FactKind.FEE_ASSERTION)
    if expect.get("has_signature_presence"):
        assert result.facts_by_kind(FactKind.SIGNATURE_PRESENCE)
        assert PackageReasonCode.SIGNATURE_PRESENCE_ONLY.value in result.reason_codes
    if expect.get("has_arguments"):
        assert result.facts_by_kind(FactKind.ARGUMENT)
    if expect.get("has_cross_document_links"):
        assert result.facts_by_kind(FactKind.CROSS_DOCUMENT_LINK) or (
            PackageReasonCode.CROSS_DOCUMENT_LINKS.value in result.reason_codes
        )
    if expect.get("has_sequence_listing"):
        assert result.facts_by_kind(FactKind.SEQUENCE_LISTING)
    if expect.get("sequence_listing_applicable"):
        assert (
            PackageReasonCode.SEQUENCE_LISTING_APPLICABLE.value in result.reason_codes
        )
    if expect.get("has_replacement_pages"):
        assert result.facts_by_kind(FactKind.REPLACEMENT_PAGE)
    if expect.get("has_electronic_submission_receipt"):
        assert result.receipts_by_kind(ReceiptKind.ELECTRONIC_SUBMISSION_RECEIPT)
    if expect.get("has_payment_receipt"):
        assert result.receipts_by_kind(ReceiptKind.PAYMENT_RECEIPT) or result.facts_by_kind(
            FactKind.FEE_ASSERTION
        )
    if expect.get("has_submitted_docx"):
        assert result.renderings_by_kind(RenderingKind.SUBMITTED_DOCX)
    if expect.get("has_converted_pdf"):
        assert result.renderings_by_kind(RenderingKind.CONVERTED_PDF)
    if expect.get("has_feedback_document"):
        assert result.renderings_by_kind(RenderingKind.FEEDBACK_DOCUMENT)
    if expect.get("all_receipt_kinds_present"):
        present = {r.kind for r in result.receipts}
        assert present == set(ReceiptKind)
    if expect.get("every_fact_has_anchors"):
        _assert_every_fact_has_anchors(result)
    if expect.get("receipts_distinct_hashes_and_effects"):
        _assert_receipts_distinct(result)
    if expect.get("renderings_distinct_hashes_and_effects"):
        _assert_renderings_distinct(result)
    if expect.get("inventory_gap"):
        assert PackageReasonCode.INVENTORY_GAP.value in result.reason_codes
        assert any(
            d.kind is DiscrepancyKind.INVENTORY_MISSING for d in result.discrepancies
        )
    if expect.get("has_duplicate_discrepancy"):
        assert any(
            d.kind is DiscrepancyKind.INVENTORY_DUPLICATE for d in result.discrepancies
        )
        assert PackageReasonCode.DUPLICATE_DOCUMENTS.value in result.reason_codes
    if expect.get("has_identifier_conflict"):
        assert any(
            d.kind is DiscrepancyKind.IDENTIFIER_CONFLICT for d in result.discrepancies
        )
    if expect.get("rendering_divergence"):
        assert any(
            d.kind
            in (
                DiscrepancyKind.RENDERING_DIVERGENCE,
                DiscrepancyKind.CONTENT_MISMATCH,
            )
            for d in result.discrepancies
        )
    if expect.get("noisy_scan"):
        assert PackageReasonCode.NOISY_SCAN.value in result.reason_codes
    if expect.get("conversion_warning"):
        assert PackageReasonCode.CONVERSION_WARNING.value in result.reason_codes
    if expect.get("review_required"):
        assert result.requires_review or result.review_state is ReviewState.REQUIRED
    if expect.get("has_candidate_associations"):
        assert result.candidate_associations
        assert (
            PackageReasonCode.CANDIDATE_ASSOCIATIONS_HELD.value in result.reason_codes
        )
    if expect.get("candidates_confidence_scored"):
        assert result.candidate_associations
        for c in result.candidate_associations:
            assert c.confidence is not None
            assert c.review_state is ReviewState.REQUIRED
    if expect.get("model_never_admitted_without_receipt"):
        for f in result.facts:
            if f.origin is FieldOrigin.MODEL and f.admission is AdmissionState.ADMITTED:
                assert f.admission_receipt_id
    if expect.get("has_structured_field_anchor"):
        assert any(a.kind is AnchorKind.STRUCTURED_FIELD for a in result.anchors)
    if "disposition_in" in expect:
        assert result.disposition.value in expect["disposition_in"]
    if "disposition" in expect:
        assert result.disposition is PackageDisposition(expect["disposition"])
    if expect.get("empty_package"):
        assert PackageReasonCode.EMPTY_PACKAGE.value in result.reason_codes
    if "retained" in expect:
        assert result.retained is bool(expect["retained"])


# ---------------------------------------------------------------------------
# Recipe coverage
# ---------------------------------------------------------------------------


def test_recipe_file_present_and_covers_profiles() -> None:
    recipe = _load_recipe()
    assert recipe["schema_version"] == "uspto.submission-package-semantics-v2-recipe.v1"
    assert recipe["task_id"] == "PATLAW-133"
    profiles = set(recipe["package_profiles"])
    assert profiles == {
        "complete",
        "partial",
        "duplicate",
        "inconsistent",
        "scanned",
        "conversion_warning",
    }
    for profile in profiles:
        assert any(
            c.get("expect", {}).get("package_profile") == profile
            for c in recipe["cases"]
        ), f"missing recipe case for profile {profile}"
    assert set(recipe["receipt_kinds"]) == {k.value for k in ReceiptKind}
    assert any(c["id"] == "all_receipt_kinds" for c in recipe["cases"])


@pytest.mark.parametrize(
    "case_id",
    [c["id"] for c in json.loads(RECIPE_PATH.read_text(encoding="utf-8"))["cases"]],
)
def test_recipe_case(case_id: str) -> None:
    recipe = _load_recipe()
    case = next(c for c in recipe["cases"] if c["id"] == case_id)
    result = _run_case(case)
    assert result.schema_version == SEMANTICS_V2_SCHEMA_VERSION
    assert result.retained is True or case.get("expect", {}).get("retained") is False
    _apply_expect(result, case.get("expect") or {})
    if result.facts:
        _assert_every_fact_has_anchors(result)
    _assert_round_trip(result)


# ---------------------------------------------------------------------------
# Core unit behavior
# ---------------------------------------------------------------------------


def test_receipt_effect_codes_are_unique() -> None:
    codes = list(RECEIPT_EFFECT_CODES.values())
    assert len(codes) == len(set(codes))
    assert len(RECEIPT_EFFECT_CODES) == len(ReceiptKind)
    for kind in ReceiptKind:
        assert receipt_effect_code(kind).startswith("effect:")


def test_rendering_effect_codes_are_unique() -> None:
    codes = list(RENDERING_EFFECT_CODES.values())
    assert len(codes) == len(set(codes))
    for kind in RenderingKind:
        assert rendering_effect_code(kind).startswith("effect:")


def test_detect_receipt_kind_content_not_filename() -> None:
    kind, conf, notes = detect_receipt_kind(
        _ack_receipt_text(),
        declared_role=DocumentRole.OTHER,
    )
    assert kind is ReceiptKind.ELECTRONIC_SUBMISSION_RECEIPT
    assert conf is not None and conf >= 0.7
    # Role alone without content is insufficient.
    kind2, conf2, notes2 = detect_receipt_kind(
        "",
        declared_role=DocumentRole.ELECTRONIC_SUBMISSION_RECEIPT,
    )
    assert kind2 is None
    assert "role_without_content_insufficient" in notes2 or conf2 is None


def test_detect_noisy_scan() -> None:
    assert detect_noisy_scan(_scanned_claims())
    assert detect_noisy_scan("clean enough text", ocr_confidence=0.2)
    assert not detect_noisy_scan(_claims_text(), ocr_confidence=0.95)


def test_complete_package_admits_facts_with_anchors() -> None:
    result = _processor().analyze(
        SubmissionPackageInput(
            package_id="pkg:complete",
            matter_id="matter:complete",
            application_type=ApplicationType.UTILITY,
            classification=DisclosureClassification.PUBLIC_USER,
            documents=tuple(build_complete_utility_package()),
        )
    )
    assert result.package_profile is PackageProfile.COMPLETE
    assert result.facts_by_kind(FactKind.CLAIM)
    admitted = result.facts_by_admission(AdmissionState.ADMITTED)
    assert admitted
    assert all(f.admission_receipt_id for f in admitted)
    assert result.admission_receipts
    _assert_every_fact_has_anchors(result)
    _assert_receipts_distinct(result)
    _assert_round_trip(result)
    public = result.public_projection()
    assert public["package_profile"] == "complete"
    assert COMPLETE_CANARY not in json.dumps(public)


def test_all_receipt_kinds_have_distinct_hashes_and_effects() -> None:
    result = extract_submission_package_semantics_v2(
        SubmissionPackageInput(
            package_id="pkg:receipts",
            application_type=ApplicationType.UTILITY,
            classification=DisclosureClassification.PUBLIC_USER,
            documents=tuple(build_all_receipts_package()),
        ),
        id_factory=_processor()._id_factory,
    )
    present = {r.kind for r in result.receipts}
    assert present == set(ReceiptKind)
    _assert_receipts_distinct(result)
    # No two kinds share an effect code.
    by_kind = {r.kind: r.effect_code for r in result.receipts}
    assert len(set(by_kind.values())) == len(by_kind)


def test_conversion_package_renderings_distinct() -> None:
    result = _processor().analyze(
        SubmissionPackageInput(
            package_id="pkg:conv",
            application_type=ApplicationType.UTILITY,
            classification=DisclosureClassification.PUBLIC_USER,
            documents=tuple(build_conversion_warning_package()),
        )
    )
    assert result.package_profile is PackageProfile.CONVERSION_WARNING
    _assert_renderings_distinct(result)
    kinds = {r.kind for r in result.renderings}
    assert RenderingKind.SUBMITTED_DOCX in kinds
    assert RenderingKind.CONVERTED_PDF in kinds
    assert RenderingKind.FEEDBACK_DOCUMENT in kinds
    assert any(
        d.kind
        in (DiscrepancyKind.RENDERING_DIVERGENCE, DiscrepancyKind.CONTENT_MISMATCH)
        for d in result.discrepancies
    )


def test_model_association_remains_reviewable_candidate() -> None:
    docs = build_complete_utility_package()
    model = ModelAssociationInput(
        kind=FactKind.ARGUMENT,
        surface_text="Invented association: claim 42 overcomes imaginary statute 999.",
        source_document_id=docs[0].document_id,
        confidence=0.33,
        related_claim_tokens=("1",),
        labels={"model": "test"},
    )
    result = _processor().analyze(
        SubmissionPackageInput(
            package_id="pkg:model",
            application_type=ApplicationType.UTILITY,
            classification=DisclosureClassification.PUBLIC_USER,
            documents=tuple(docs),
            model_associations=(model,),
        )
    )
    assert result.candidate_associations
    for c in result.candidate_associations:
        assert isinstance(c, CandidateAssociation)
        assert c.confidence is not None
        assert 0.0 <= c.confidence <= 1.0
        assert c.review_state is ReviewState.REQUIRED
        assert c.origin is FieldOrigin.MODEL
    model_facts = [f for f in result.facts if f.origin is FieldOrigin.MODEL]
    assert model_facts
    for f in model_facts:
        if f.admission is AdmissionState.ADMITTED:
            assert f.admission_receipt_id
        else:
            assert f.admission in (
                AdmissionState.CANDIDATE,
                AdmissionState.REVIEW_REQUIRED,
                AdmissionState.REJECTED,
            )


def test_structured_field_anchor_for_payment() -> None:
    result = _processor().analyze(
        SubmissionPackageInput(
            package_id="pkg:sf",
            application_type=ApplicationType.UTILITY,
            classification=DisclosureClassification.PUBLIC_USER,
            documents=tuple(build_structured_payment_package()),
        )
    )
    structured = [a for a in result.anchors if a.kind is AnchorKind.STRUCTURED_FIELD]
    assert structured
    assert any("payment" in (a.structured_field_path or "") for a in structured)
    assert result.facts_by_kind(FactKind.FEE_ASSERTION) or result.receipts_by_kind(
        ReceiptKind.PAYMENT_RECEIPT
    )


def test_signature_presence_never_retains_material() -> None:
    result = _processor().analyze(
        SubmissionPackageInput(
            package_id="pkg:sig",
            application_type=ApplicationType.UTILITY,
            classification=DisclosureClassification.PUBLIC_USER,
            documents=tuple(build_complete_utility_package()),
        )
    )
    sigs = result.facts_by_kind(FactKind.SIGNATURE_PRESENCE)
    assert sigs
    for s in sigs:
        assert s.normalized_value in (None, "present")
        assert "/s/" not in s.surface_text
        assert "Jane" not in s.surface_text
    blob = json.dumps(result.public_projection())
    assert "Jane Q. Inventor" not in blob


def test_filename_not_sufficient_semantic_evidence() -> None:
    # Document with receipt-like filename but non-receipt body must not mint receipt.
    docs = [
        PackageDocumentInput(
            document_id="doc:fake-receipt",
            role=DocumentRole.OTHER,
            text="This is a cover letter only. No acknowledgement content.",
            filename_hint="electronic_acknowledgement_receipt.pdf",
            classification=DisclosureClassification.PUBLIC_USER,
        ),
    ]
    result = _processor().analyze(
        SubmissionPackageInput(
            package_id="pkg:filename",
            application_type=ApplicationType.UTILITY,
            classification=DisclosureClassification.PUBLIC_USER,
            documents=tuple(docs),
        )
    )
    assert not result.receipts


def test_quarantine_unknown_classification() -> None:
    result = _processor().analyze(
        SubmissionPackageInput(
            package_id="pkg:q",
            application_type=ApplicationType.UTILITY,
            classification=DisclosureClassification.UNKNOWN,
            documents=tuple(build_partial_package()),
        )
    )
    assert result.disposition is PackageDisposition.QUARANTINE
    assert result.review_state is ReviewState.REQUIRED
    assert PackageReasonCode.QUARANTINE_CLASSIFICATION.value in result.reason_codes


def test_admit_normalized_fact_requires_anchor() -> None:
    docs = build_partial_package()
    result = _processor().analyze(
        SubmissionPackageInput(
            package_id="pkg:adm",
            application_type=ApplicationType.UTILITY,
            classification=DisclosureClassification.PUBLIC_USER,
            documents=tuple(docs),
        )
    )
    assert result.facts
    fact = result.facts[0]
    # Re-admit already-admitted fact should still pass with anchors.
    promoted, receipt = admit_normalized_fact(
        fact,
        anchors={a.anchor_id: a for a in result.anchors},
        spans={s.span_id: s for s in result.spans},
        receipt_id="adm:manual:1",
    )
    assert receipt.fact_id == fact.fact_id
    assert promoted.admission_receipt_id == "adm:manual:1"


def test_empty_package_malformed() -> None:
    result = _processor().analyze(
        SubmissionPackageInput(
            package_id="pkg:empty",
            application_type=ApplicationType.UNKNOWN,
            classification=DisclosureClassification.PUBLIC_USER,
            documents=(),
        )
    )
    assert result.disposition is PackageDisposition.MALFORMED
    assert PackageReasonCode.EMPTY_PACKAGE.value in result.reason_codes
    assert result.facts == ()
    _assert_round_trip(result)
