"""
Compact synthetic submission generators for PATLAW-033.

Produces text recipes (not bulk golden dumps) that exercise:
  - claim sets and currently-amended claim reconstruction
  - remarks, declarations, forms, fees
  - signature *presence* (never reusable signing material)
  - acknowledgement + payment receipt fields
  - authoritative DOCX vs converted-PDF differences
  - missing/mismatched metadata

Canaries are synthetic markers — not real confidential filings.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Mapping

CLAIM_CANARY = "SYNTHETIC-CLAIM-1-TEMPERATURE-SENSOR"
AMEND_CANARY = "SYNTHETIC-AMENDMENT-CLAIM-1-CURRENTLY-AMENDED"
REMARKS_CANARY = "SYNTHETIC-REMARKS-TRAVERSE-112"
DECLARATION_CANARY = "SYNTHETIC-DECLARATION-37CFR-1.63"
RECEIPT_CANARY = "SYNTHETIC-ACK-RECEIPT-ID-A1B2C3D4"
FEE_CANARY = "SYNTHETIC-FEE-CODE-1011"
SIGNATURE_MARKER = "Electronically signed"
# Material that must never be retained as reusable signing data:
SIGNATURE_MATERIAL_CANARY = "/s/ Jane Q. Inventor"


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def build_amendment_claims_text(
    *,
    application_number: str = "16/123,456",
    include_signature_material: bool = True,
) -> str:
    """Preliminary amendment with currently-amended claim + remarks."""
    sig_block = (
        f"{SIGNATURE_MARKER}\n{SIGNATURE_MATERIAL_CANARY}\n"
        if include_signature_material
        else f"{SIGNATURE_MARKER}\n"
    )
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application Number: {application_number}
Confirmation Number: 5678
Attorney Docket: SYN-2026-001
Document Description: Preliminary Amendment
Form PTO/SB/08

AMENDMENTS TO THE CLAIMS

Please amend claim 1 as follows:

Claim 1 (currently amended): {CLAIM_CANARY} {AMEND_CANARY} A device comprising a temperature sensor.
Claim 2 (original): The device of claim 1 further comprising a filter.

REMARKS

{REMARKS_CANARY}
Applicants respectfully traverse the rejection under 35 U.S.C. 112.
Claim 1 has been amended to clarify the sensor limitation.

Fee Item | Amount
Basic Filing | 320
Fee Code: {FEE_CANARY} $80.00

Attachment: IDS-SB08.pdf
Document Description: Information Disclosure Statement

Respectfully submitted,
{sig_block}
"""


def build_as_filed_claims_text(
    *,
    application_number: str = "16/123,456",
) -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application Number: {application_number}

WHAT IS CLAIMED IS:

1. A device comprising a sensor.
2. The device of claim 1 further comprising a filter.
"""


def build_docx_authoritative_text(
    *,
    application_number: str = "16/900,001",
) -> str:
    """Authoritative DOCX body with equation marker for difference tests."""
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application Number: {application_number}
Document Description: Specification

1. A synthetic apparatus comprising a processor configured to run tests.
EQUATION_PLACEHOLDER: E=mc^2

{CLAIM_CANARY}
"""


def build_converted_pdf_text(
    *,
    application_number: str = "16/900,001",
    diverge_claim: bool = True,
) -> str:
    """USPTO-converted PDF text; optional claim divergence from DOCX."""
    claim = (
        "1. A synthetic apparatus comprising a processor configured to run tests (PDF)."
        if diverge_claim
        else "1. A synthetic apparatus comprising a processor configured to run tests."
    )
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application Number: {application_number}
Document Description: Specification

{claim}
# equation pagination differs — no EQUATION_PLACEHOLDER here

{CLAIM_CANARY}
"""


def build_acknowledgement_receipt_text(
    *,
    application_number: str = "16/900,001",
    confirmation_number: str = "1234",
    receipt_id: str = RECEIPT_CANARY,
    receipt_date: str = "2026-01-15T18:22:00Z",
) -> str:
    return f"""ELECTRONIC ACKNOWLEDGEMENT RECEIPT
Application Number: {application_number}
Confirmation Number: {confirmation_number}
Receipt ID: {receipt_id}
Receipt Date: {receipt_date}
Document Description: Electronic Acknowledgement Receipt
"""


def build_payment_receipt_fields(
    *,
    amount_usd: str = "80.00",
    fee_code: str = "1011",
    paid_utc: str = "2026-01-15T18:22:05Z",
) -> Dict[str, str]:
    return {
        "amount_usd": amount_usd,
        "fee_code": fee_code,
        "paid_utc": paid_utc,
        "payment_method": "deposit_account_last4_masked",
    }


def build_declaration_text(
    *,
    application_number: str = "16/123,456",
) -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application Number: {application_number}
Form PTO/AIA/01

I hereby declare that I believe I am the original inventor of the claimed invention.
{DECLARATION_CANARY}
Declaration under 37 C.F.R. 1.63

{SIGNATURE_MARKER}
"""


def build_mismatched_metadata_text(
    *,
    application_number: str = "16/999,999",
) -> str:
    return f"""Application Number: {application_number}
Document Description: Response to Office Action
1. A device comprising a sensor.
"""


def fixture_recipe_cases() -> list[Dict[str, Any]]:
    """Compact case descriptors for the submission recipe (no bulk dumps)."""
    return [
        {
            "id": "amendment_current_claims",
            "generator": "build_amendment_claims_text",
            "expect": {
                "has_claims": True,
                "has_amendment": True,
                "has_remarks": True,
                "has_signature_presence": True,
                "signature_material_suppressed": True,
                "current_claim_1_contains": "temperature sensor",
            },
        },
        {
            "id": "docx_authoritative_over_pdf",
            "generator": "build_docx_authoritative_text",
            "compare_generator": "build_converted_pdf_text",
            "expect": {
                "docx_authoritative": True,
                "docx_pdf_difference_explicit": True,
            },
        },
        {
            "id": "filing_receipts",
            "generators": [
                "build_acknowledgement_receipt_text",
                "build_payment_receipt_fields",
            ],
            "expect": {
                "has_ack_id": True,
                "payment_receipt_present": True,
            },
        },
        {
            "id": "declaration_and_form",
            "generator": "build_declaration_text",
            "expect": {
                "has_declaration": True,
                "has_form": True,
            },
        },
        {
            "id": "missing_receipt",
            "generator": "build_as_filed_claims_text",
            "require_ack_receipt": True,
            "expect": {
                "missing_receipt_explicit": True,
            },
        },
        {
            "id": "mismatched_metadata",
            "generator": "build_mismatched_metadata_text",
            "expected_application_number": "16/123,456",
            "expect": {
                "mismatched_metadata_explicit": True,
            },
        },
    ]


def canaries() -> Mapping[str, str]:
    return {
        "claim": CLAIM_CANARY,
        "amendment": AMEND_CANARY,
        "remarks": REMARKS_CANARY,
        "declaration": DECLARATION_CANARY,
        "receipt": RECEIPT_CANARY,
        "fee": FEE_CANARY,
        "signature_marker": SIGNATURE_MARKER,
        "signature_material": SIGNATURE_MATERIAL_CANARY,
    }
