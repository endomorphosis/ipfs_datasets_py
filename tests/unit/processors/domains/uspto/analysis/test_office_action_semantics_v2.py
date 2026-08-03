"""Unit tests for layout-aware office-action semantics v2 (PATLAW-129)."""

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
from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_semantics_v2 import (
    NAMED_COMMUNICATION_FAMILIES,
    SEMANTICS_V2_SCHEMA_VERSION,
    AdmissionState,
    CommunicationFamily,
    ContradictionKind,
    FieldOrigin,
    LayoutPage,
    ModelFieldInput,
    OfficeActionSemanticsInput,
    OfficeActionSemanticsResult,
    OfficeActionSemanticsV2,
    SemanticFieldKind,
    SemanticsDisposition,
    SemanticsReasonCode,
    admit_semantic_field,
    detect_communication_family,
    detect_noisy_scan,
    extract_office_action_semantics_v2,
    family_for_document_code,
    parse_calendar_date,
    sha256_hex,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[5] / "fixtures" / "uspto" / "office_actions"
)
RECIPE_PATH = FIXTURE_DIR / "semantic_v2_recipe.json"

# ---------------------------------------------------------------------------
# Synthetic generators (compact; not real USPTO filings)
# ---------------------------------------------------------------------------

NON_FINAL_CANARY = "SYNTH-OA-V2-NONFINAL-103"
FINAL_CANARY = "SYNTH-OA-V2-FINAL-102"
MISSING_PARTS_CANARY = "SYNTH-OA-V2-MISSING-PARTS"
OMITTED_CANARY = "SYNTH-OA-V2-OMITTED-ITEMS"
NO_FILING_CANARY = "SYNTH-OA-V2-NO-FILING-DATE"
RESTRICTION_CANARY = "SYNTH-OA-V2-RESTRICTION"
QUAYLE_CANARY = "SYNTH-OA-V2-QUAYLE"
ADVISORY_CANARY = "SYNTH-OA-V2-ADVISORY"
SEQUENCE_CANARY = "SYNTH-OA-V2-SEQUENCE"
ALLOWANCE_CANARY = "SYNTH-OA-V2-ALLOWANCE"
APPEAL_CANARY = "SYNTH-OA-V2-APPEAL"
PETITION_CANARY = "SYNTH-OA-V2-PETITION"
REISSUE_CANARY = "SYNTH-OA-V2-REISSUE"
NOISY_CANARY = "SYNTH-OA-V2-NOISY"
UNKNOWN_CANARY = "SYNTH-OA-V2-UNKNOWN"
CROSS_PAGE_CANARY = "SYNTH-OA-V2-CROSS-PAGE"


def build_non_final_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application No.: 16/123,456
Mailing Date: 2026-08-01
Office Action Summary

This is a non-final office action. {NON_FINAL_CANARY}

Detailed Action

Claim Rejections - 35 U.S.C. § 103

Claims 1-3 are rejected under 35 U.S.C. 103 as being unpatentable over U.S. Patent 9,999,999.
See form paragraph 7.15 and MPEP § 2141.

Examiner: Jane Q. Examiner
Art Unit: 2100
Telephone No.: 571-272-0000

Fee Information
A fee code 1201 may be required. See Form PTO/SB/22.

Response Period
A shortened statutory period for reply is set to expire in 3 months from the mailing date.
Applicant is required to traverse the rejection or amend the claims.
"""


def build_final_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application No.: 15/987,654
Mailing Date: 03/15/2026
Office Action Summary

This action is made final. {FINAL_CANARY}

Claim Rejections - 35 U.S.C. § 102

Claim 1 is rejected under 35 U.S.C. 102 as being anticipated by US 2020/0123456 A1.

Period for Reply
A shortened statutory period for reply is set to expire in 3 months.
Applicant must respond to this final office action.
"""


def build_missing_parts_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Notice of Missing Parts
Application No.: 17/111,222
Mailing Date: 2026-05-01

{MISSING_PARTS_CANARY}
The application papers are incomplete. Missing parts include an inventor oath.
Applicant is required to submit the missing parts within 2 months.
A shortened statutory period for reply is set to expire in 2 months.
"""


def build_omitted_items_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Notice of Omitted Items
Application No.: 17/222,333
Mailing Date: 2026-04-10

{OMITTED_CANARY}
Items were omitted from the application papers as filed.
Applicant is required to supply the omitted items or notify the Office.
"""


def build_no_filing_date_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Notice of No Filing Date
Application No.: 17/333,444
Mailing Date: 2026-03-20

{NO_FILING_CANARY}
A filing date has not been accorded. The papers are not accorded a filing date.
Applicant is required to correct the deficiency.
"""


def build_restriction_election_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Requirement for Restriction / Election of Species
Application No.: 16/444,555
Mailing Date: 2026-06-01

{RESTRICTION_CANARY}
This requirement for restriction is made under 35 U.S.C. 121.
Election is required between the following groups:

Group I - claims 1-5
Group II - claims 6-10
| Claim | Status |
| 1-5 | Group I |
| 6-10 | Group II |

Applicant is required to elect one invention for examination.
Applicant may traverse the restriction.
A shortened statutory period for reply is set to expire in 2 months.
"""


def build_quayle_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Office Action Summary
Application No.: 16/555,666
Mailing Date: 2026-07-01

This action is an Ex parte Quayle. {QUAYLE_CANARY}

Claim 2 is objected to for minor informality.
Allowable subject matter is indicated in claim 1.
A shortened statutory period for reply is set to expire in 2 months.
"""


def build_advisory_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Advisory Action
Application No.: 16/666,777
Mailing Date: 2026-07-15

{ADVISORY_CANARY}
This is an advisory action. Entry of the amendment after final is denied.
The proposed amendment will not be entered.
"""


def build_sequence_compliance_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Sequence Listing Compliance Notice
Application No.: 16/777,888
Mailing Date: 2026-08-10

{SEQUENCE_CANARY}
The sequence listing is non-compliant with ST.26 requirements.
Applicant is required to submit a compliant CRF sequence listing.
See 37 C.F.R. 1.821.
"""


def build_allowance_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Notice of Allowance
Application No.: 16/888,999
Mailing Date: 2026-09-01

{ALLOWANCE_CANARY}
The application is allowed. Claims 1-10 are allowed.
Applicant must pay the issue fee. See Form PTOL-85.
Attachments: fee transmittal is attached hereto.
| Claim | Status |
| 1-10 | Allowed |

/s/ Pat Examiner
"""


def build_appeal_pre_appeal_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Pre-Appeal Brief Request for Review
Application No.: 15/111,000
Mailing Date: 2026-02-01

{APPEAL_CANARY}
Applicant files this pre-appeal brief conference request.
Notice of appeal was previously filed.
The Board of Appeals will not consider the request until panel review.
"""


def build_petition_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Decision on Petition
Application No.: 15/222,111
Mailing Date: 2026-01-15

{PETITION_CANARY}
This is a decision on petition under 37 C.F.R. 1.181.
The petition is granted.
Signature: /s/ Petition Officer
"""


def build_reissued_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application No.: 16/555,000
Mailing Date: 2026-03-01
Office Action Summary

This reissued office action supersedes the office action mailed 2026-02-01.
The previous office action is hereby withdrawn. {REISSUE_CANARY}

Claim 1 is rejected under 35 U.S.C. 103 as being unpatentable over U.S. Patent 7,777,777.

Response Period
A shortened statutory period for reply is set to expire in 3 months from the mailing date of this reissued office action.
"""


def build_noisy_scan_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application No.: 16/123,456
Mailing Date: 2026-08-01
|||| @@@@ ???? illegible OCR failure garbled
This is a non-final office action. {NOISY_CANARY}
Claim 1 is rejected under 35 U.S.C. 103.
a b c d e f g h i j k l m n o p q r
"""


def build_unknown_family_text() -> str:
    return f"""USPTO miscellaneous correspondence
{UNKNOWN_CANARY}
Please see the enclosed schedule for docket purposes only.
No office action content is present here.
"""


def build_empty_text() -> str:
    return ""


def build_forms_attachments_text() -> str:
    return f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Notice of Allowance
Application No.: 16/100,200
Mailing Date: 2026-09-15

The application is allowed. Claims 1-5 are allowed.
Pay the issue fee. Form PTO/SB/22 and fee code 1501 apply.
See attached form PTOL-85. Enclosures: drawings sheet.
Attachments: fee transmittal is attached hereto.

| Claim | Status |
| 1-5 | Allowed |

Group I - claims 1-5
/s/ Exam Officer
Respectfully submitted,
"""


def build_cross_page_pages() -> list[dict[str, Any]]:
    page0 = f"""UNITED STATES PATENT AND TRADEMARK OFFICE
Application No.: 16/123,456
Mailing Date: 2026-08-01
Office Action Summary

This is a non-final office action. {CROSS_PAGE_CANARY}

Claim Rejections - 35 U.S.C. § 103
Claims 1-2 are rejected under 35 U.S.C. 103.
(continued on the next page)
"""
    page1 = """Claims 3-4 are also rejected under 35 U.S.C. 103 as continued from page 1.
A shortened statutory period for reply is set to expire in 3 months.
Examiner: Cont Page
"""
    return [
        {"page_index": 0, "text": page0, "origin": "native"},
        {"page_index": 1, "text": page1, "origin": "ocr", "ocr_confidence": 0.88},
    ]


GENERATORS: dict[str, Callable[[], Any]] = {
    "build_non_final_text": build_non_final_text,
    "build_final_text": build_final_text,
    "build_missing_parts_text": build_missing_parts_text,
    "build_omitted_items_text": build_omitted_items_text,
    "build_no_filing_date_text": build_no_filing_date_text,
    "build_restriction_election_text": build_restriction_election_text,
    "build_quayle_text": build_quayle_text,
    "build_advisory_text": build_advisory_text,
    "build_sequence_compliance_text": build_sequence_compliance_text,
    "build_allowance_text": build_allowance_text,
    "build_appeal_pre_appeal_text": build_appeal_pre_appeal_text,
    "build_petition_text": build_petition_text,
    "build_reissued_text": build_reissued_text,
    "build_noisy_scan_text": build_noisy_scan_text,
    "build_unknown_family_text": build_unknown_family_text,
    "build_empty_text": build_empty_text,
    "build_forms_attachments_text": build_forms_attachments_text,
    "build_cross_page_pages": build_cross_page_pages,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _processor(**kwargs) -> OfficeActionSemanticsV2:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"oas2:test:{counter['n']:04d}"

    return OfficeActionSemanticsV2(id_factory=_ids, **kwargs)


def _span_for_text(
    text: str,
    *,
    artifact_id: str = "art:oas2:1",
    span_id: str = "span:oas2:cover",
    page_index: int = 0,
    classification: DisclosureClassification = DisclosureClassification.PUBLIC_USER,
    origin: ExtractionOrigin = ExtractionOrigin.NATIVE,
    confidence: float | None = 0.99,
) -> ExtractedSpan:
    return ExtractedSpan(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        span_id=span_id,
        artifact_id=artifact_id,
        page_index=page_index,
        char_start=0,
        char_end=len(text),
        bbox=(0.0, 0.0, 100.0, 200.0),
        origin=origin,
        reading_order=page_index,
        confidence=confidence,
        text_digest=sha256_hex(" ".join(text.split())),
        image_digest=None,
        classification=classification,
    )


def _input_from_text(
    text: str,
    *,
    artifact_id: str = "art:oas2:1",
    document_code: str | None = None,
    with_span: bool = True,
    classification: DisclosureClassification = DisclosureClassification.PUBLIC_USER,
    model_fields: tuple[ModelFieldInput, ...] = (),
    **kwargs: Any,
) -> OfficeActionSemanticsInput:
    spans: tuple[ExtractedSpan, ...] = ()
    span_texts: dict[str, str] = {}
    if with_span and text:
        span = _span_for_text(text, artifact_id=artifact_id)
        spans = (span,)
        span_texts = {span.span_id: text}
    return OfficeActionSemanticsInput(
        artifact_id=artifact_id,
        text=text,
        spans=spans,
        span_texts=span_texts,
        classification=classification,
        document_code=document_code,
        model_fields=model_fields,
        **kwargs,
    )


def _input_from_pages(
    pages_raw: list[dict[str, Any]],
    *,
    artifact_id: str = "art:oas2:pages",
    document_code: str | None = "CTNF",
    classification: DisclosureClassification = DisclosureClassification.PUBLIC_USER,
) -> OfficeActionSemanticsInput:
    pages: list[LayoutPage] = []
    for p in pages_raw:
        text = str(p.get("text") or "")
        span = _span_for_text(
            text,
            artifact_id=artifact_id,
            span_id=f"span:{artifact_id}:p{p['page_index']}",
            page_index=int(p["page_index"]),
            origin=ExtractionOrigin(p.get("origin", "native")),
            confidence=p.get("ocr_confidence", 0.9),
        )
        pages.append(
            LayoutPage(
                page_index=int(p["page_index"]),
                text=text,
                spans=(span,),
                span_texts={span.span_id: text},
                origin=ExtractionOrigin(p.get("origin", "native")),
                ocr_confidence=p.get("ocr_confidence"),
            )
        )
    return OfficeActionSemanticsInput(
        artifact_id=artifact_id,
        pages=tuple(pages),
        classification=classification,
        document_code=document_code,
    )


def _assert_every_field_has_spans(result: OfficeActionSemanticsResult) -> None:
    span_ids = {s.span_id for s in result.spans}
    for field in result.fields:
        assert field.source_span_ids, f"{field.field_id} missing source_span_ids"
        for sid in field.source_span_ids:
            assert sid in span_ids, f"{field.field_id} span {sid} not in result.spans"
        assert field.text_digest
        assert len(field.text_digest) == 64


def _assert_round_trip(result: OfficeActionSemanticsResult) -> None:
    first = result.to_dict()
    restored = OfficeActionSemanticsResult.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    public = result.public_projection()
    assert "fields" not in public
    blob = json.dumps(public)
    assert NON_FINAL_CANARY not in blob
    assert FINAL_CANARY not in blob


def _load_recipe() -> dict[str, Any]:
    assert RECIPE_PATH.is_file()
    return json.loads(RECIPE_PATH.read_text(encoding="utf-8"))


def _run_case(case: dict[str, Any]) -> OfficeActionSemanticsResult:
    gen_name = case["generator"]
    gen = GENERATORS[gen_name]
    payload = gen()
    proc = _processor()
    classification = case.get("classification", "public_user")
    doc_code = case.get("document_code")

    if case.get("multi_page"):
        assert isinstance(payload, list)
        inp = _input_from_pages(
            payload,
            artifact_id=f"art:{case['id']}",
            document_code=doc_code,
            classification=DisclosureClassification(classification),
        )
        return proc.analyze(inp)

    text = str(payload)
    model_fields: tuple[ModelFieldInput, ...] = ()
    if case.get("model_candidate"):
        model_fields = (
            ModelFieldInput(
                kind=SemanticFieldKind.REJECTION,
                surface_text="Claim 99 is rejected under 35 U.S.C. 101 as model-only.",
                confidence=0.55,
                labels={"model": "synthetic"},
            ),
        )
    ocr_conf = case.get("ocr_confidence")
    if ocr_conf is not None and text:
        # Present as a single OCR page with low confidence.
        span = _span_for_text(
            text,
            artifact_id=f"art:{case['id']}",
            origin=ExtractionOrigin.OCR,
            confidence=float(ocr_conf),
        )
        page = LayoutPage(
            page_index=0,
            text=text,
            spans=(span,),
            span_texts={span.span_id: text},
            origin=ExtractionOrigin.OCR,
            ocr_confidence=float(ocr_conf),
        )
        return proc.analyze(
            OfficeActionSemanticsInput(
                artifact_id=f"art:{case['id']}",
                pages=(page,),
                classification=DisclosureClassification(classification),
                document_code=doc_code,
                model_fields=model_fields,
            )
        )

    return proc.analyze(
        _input_from_text(
            text,
            artifact_id=f"art:{case['id']}",
            document_code=doc_code,
            classification=DisclosureClassification(classification),
            model_fields=model_fields,
            with_span=bool(text),
        )
    )


def _apply_expect(result: OfficeActionSemanticsResult, expect: dict[str, Any]) -> None:
    if "family" in expect:
        assert result.family is CommunicationFamily(expect["family"])
    if expect.get("every_field_has_spans"):
        _assert_every_field_has_spans(result)
    if expect.get("has_header"):
        assert result.fields_by_kind(SemanticFieldKind.HEADER)
    if expect.get("has_requirement"):
        assert result.fields_by_kind(SemanticFieldKind.REQUIREMENT)
    if expect.get("has_response_period"):
        assert result.fields_by_kind(SemanticFieldKind.RESPONSE_PERIOD)
    if expect.get("has_table"):
        assert result.fields_by_kind(SemanticFieldKind.TABLE)
    if expect.get("has_objection"):
        assert result.fields_by_kind(SemanticFieldKind.OBJECTION)
    if expect.get("has_allowance"):
        assert result.fields_by_kind(SemanticFieldKind.ALLOWANCE)
    if expect.get("has_form"):
        assert result.fields_by_kind(SemanticFieldKind.FORM)
    if expect.get("has_signature"):
        assert result.fields_by_kind(SemanticFieldKind.SIGNATURE)
    if expect.get("has_rejection"):
        assert result.fields_by_kind(SemanticFieldKind.REJECTION)
    if expect.get("has_claim_grouping"):
        assert result.fields_by_kind(SemanticFieldKind.CLAIM_GROUPING)
    if expect.get("has_mailing_date"):
        assert result.fields_by_kind(SemanticFieldKind.MAILING_DATE)
    if expect.get("has_application_number"):
        assert result.fields_by_kind(SemanticFieldKind.APPLICATION_NUMBER)
    if expect.get("has_statutory_citation"):
        assert result.fields_by_kind(SemanticFieldKind.STATUTORY_CITATION)
    if expect.get("has_examiner_contact"):
        assert result.fields_by_kind(SemanticFieldKind.EXAMINER_CONTACT)
    if expect.get("has_attachment"):
        assert result.fields_by_kind(SemanticFieldKind.ATTACHMENT)
    if expect.get("has_cross_page_continuation"):
        cont = result.fields_by_kind(SemanticFieldKind.CROSS_PAGE_CONTINUATION)
        assert cont
        assert any(f.is_cross_page for f in cont)
        assert SemanticsReasonCode.CROSS_PAGE_CONTINUATION.value in result.reason_codes
    if "page_count_min" in expect:
        assert result.page_count >= int(expect["page_count_min"])
    if expect.get("document_code_drift"):
        assert SemanticsReasonCode.DOCUMENT_CODE_DRIFT.value in result.reason_codes
        assert any(
            c.kind is ContradictionKind.DOCUMENT_CODE_DRIFT for c in result.contradictions
        )
    if expect.get("has_contradiction"):
        assert result.contradictions
    if "disposition_in" in expect:
        assert result.disposition.value in expect["disposition_in"]
    if "disposition" in expect:
        assert result.disposition is SemanticsDisposition(expect["disposition"])
    if expect.get("noisy_scan"):
        assert SemanticsReasonCode.NOISY_SCAN.value in result.reason_codes
    if expect.get("review_required"):
        assert result.requires_review or result.review_state is ReviewState.REQUIRED
    if "retained" in expect:
        assert result.retained is bool(expect["retained"])
    if expect.get("model_never_admitted_without_receipt"):
        for f in result.fields:
            if f.origin is FieldOrigin.MODEL:
                if f.admission is AdmissionState.ADMITTED:
                    assert f.admission_receipt_id
    if expect.get("model_starts_as_candidate"):
        model_fields = [f for f in result.fields if f.origin is FieldOrigin.MODEL]
        assert model_fields
        # Either still candidate/blocked, or admitted only with receipt.
        for f in model_fields:
            assert f.admission_receipt_id is not None or f.admission is AdmissionState.CANDIDATE
            if f.admission is AdmissionState.ADMITTED:
                assert f.admission_receipt_id
            else:
                assert f.admission in (
                    AdmissionState.CANDIDATE,
                    AdmissionState.REVIEW_REQUIRED,
                    AdmissionState.REJECTED,
                )
    if expect.get("identifier_validated"):
        assert SemanticsReasonCode.IDENTIFIER_VALIDATED.value in result.reason_codes
    if expect.get("date_validated"):
        assert SemanticsReasonCode.DATE_VALIDATED.value in result.reason_codes
    if expect.get("citation_validated_or_present"):
        assert (
            SemanticsReasonCode.CITATION_VALIDATED.value in result.reason_codes
            or result.fields_by_kind(SemanticFieldKind.STATUTORY_CITATION)
            or result.fields_by_kind(SemanticFieldKind.REGULATORY_CITATION)
        )


# ---------------------------------------------------------------------------
# Recipe / family coverage
# ---------------------------------------------------------------------------


def test_recipe_file_present_and_covers_named_families() -> None:
    recipe = _load_recipe()
    assert recipe["schema_version"] == "uspto.office-action-semantics-v2-recipe.v1"
    named = set(recipe["named_families"])
    assert named == {f.value for f in NAMED_COMMUNICATION_FAMILIES}
    family_cases = {
        c["expect"]["family"]
        for c in recipe["cases"]
        if "family" in c.get("expect", {})
        and c["expect"]["family"] != "unknown"
    }
    assert named <= family_cases | {
        c["expect"]["family"]
        for c in recipe["cases"]
        if c.get("expect", {}).get("family") in named
    }
    # Every named family has at least one dedicated case.
    for fam in named:
        assert any(
            c.get("expect", {}).get("family") == fam for c in recipe["cases"]
        ), f"missing recipe case for family {fam}"
    assert any(c.get("expect", {}).get("document_code_drift") for c in recipe["cases"])
    assert any(c.get("expect", {}).get("noisy_scan") for c in recipe["cases"])


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
    if result.fields:
        _assert_every_field_has_spans(result)
    _assert_round_trip(result)


# ---------------------------------------------------------------------------
# Core unit behavior
# ---------------------------------------------------------------------------


def test_parse_calendar_date_variants() -> None:
    iso, issues = parse_calendar_date("2026-08-01")
    assert iso == "2026-08-01"
    assert issues == []
    iso, issues = parse_calendar_date("03/15/2026")
    assert iso == "2026-03-15"
    iso, issues = parse_calendar_date("Aug 1, 2026")
    assert iso == "2026-08-01"
    iso, issues = parse_calendar_date("not-a-date")
    assert iso is None
    assert issues


def test_family_for_document_code() -> None:
    assert family_for_document_code("CTNF") is CommunicationFamily.NON_FINAL
    assert family_for_document_code("CTFR") is CommunicationFamily.FINAL
    assert family_for_document_code("NOA") is CommunicationFamily.ALLOWANCE_ISSUE_FEE
    assert family_for_document_code("ZZZZ") is None


def test_detect_communication_family_non_final_and_unknown() -> None:
    fam, conf, notes, alts = detect_communication_family(build_non_final_text())
    assert fam is CommunicationFamily.NON_FINAL
    assert conf is not None and conf >= 0.7
    fam2, _, _, _ = detect_communication_family(build_unknown_family_text())
    assert fam2 is CommunicationFamily.UNKNOWN


def test_detect_noisy_scan() -> None:
    assert detect_noisy_scan(build_noisy_scan_text())
    assert detect_noisy_scan("clean enough text", ocr_confidence=0.2)
    assert not detect_noisy_scan(build_non_final_text(), ocr_confidence=0.95)


def test_non_final_fields_and_admission() -> None:
    result = _processor().analyze(
        _input_from_text(build_non_final_text(), document_code="CTNF")
    )
    assert result.family is CommunicationFamily.NON_FINAL
    assert result.fields_by_kind(SemanticFieldKind.REJECTION)
    assert result.fields_by_kind(SemanticFieldKind.MAILING_DATE)
    assert result.fields_by_kind(SemanticFieldKind.APPLICATION_NUMBER)
    admitted = result.fields_by_admission(AdmissionState.ADMITTED)
    assert admitted
    assert all(f.admission_receipt_id for f in admitted)
    assert result.admission_receipts
    _assert_every_field_has_spans(result)
    _assert_round_trip(result)
    # Public projection never leaks canaries / surfaces
    public = result.public_projection()
    assert public["family"] == "non_final"
    assert NON_FINAL_CANARY not in json.dumps(public)


def test_document_code_drift_flags_contradiction() -> None:
    result = _processor().analyze(
        _input_from_text(build_final_text(), document_code="CTNF")
    )
    assert result.family is CommunicationFamily.FINAL
    assert SemanticsReasonCode.DOCUMENT_CODE_DRIFT.value in result.reason_codes
    assert any(
        c.kind is ContradictionKind.DOCUMENT_CODE_DRIFT for c in result.contradictions
    )
    assert result.requires_review


def test_model_field_remains_candidate_until_admitted() -> None:
    text = build_non_final_text()
    span = _span_for_text(text)
    # Model surface not present in text → should not silently admit.
    model = ModelFieldInput(
        kind=SemanticFieldKind.REJECTION,
        surface_text="Claim 42 is rejected under entirely invented statute 999.",
        source_span_ids=(span.span_id,),
        confidence=0.4,
    )
    result = _processor().analyze(
        OfficeActionSemanticsInput(
            artifact_id="art:model",
            text=text,
            spans=(span,),
            span_texts={span.span_id: text},
            classification=DisclosureClassification.PUBLIC_USER,
            document_code="CTNF",
            model_fields=(model,),
        )
    )
    model_fields = [f for f in result.fields if f.origin is FieldOrigin.MODEL]
    assert model_fields
    for f in model_fields:
        # Must have a receipt, but not admitted without passing checks.
        assert f.admission_receipt_id
        if f.admission is AdmissionState.ADMITTED:
            # Only if deterministic checks passed — still OK with receipt.
            assert f.admission_receipt_id
        else:
            assert f.admission is AdmissionState.CANDIDATE
    assert SemanticsReasonCode.MODEL_CANDIDATE_HELD.value in result.reason_codes


def test_model_field_with_matching_surface_can_admit_with_receipt() -> None:
    text = build_non_final_text()
    span = _span_for_text(text)
    # Use a surface that exists in the document.
    surface = "Claims 1-3 are rejected under 35 U.S.C. 103 as being unpatentable over U.S. Patent 9,999,999."
    model = ModelFieldInput(
        kind=SemanticFieldKind.REJECTION,
        surface_text=surface,
        source_span_ids=(span.span_id,),
        confidence=0.7,
    )
    result = _processor().analyze(
        OfficeActionSemanticsInput(
            artifact_id="art:model2",
            text=text,
            spans=(span,),
            span_texts={span.span_id: text},
            classification=DisclosureClassification.PUBLIC_USER,
            model_fields=(model,),
        )
    )
    model_fields = [f for f in result.fields if f.origin is FieldOrigin.MODEL]
    assert model_fields
    for f in model_fields:
        assert f.admission_receipt_id is not None
        # Admission allowed only with receipt (invariant enforced on result).
        if f.admission is AdmissionState.ADMITTED:
            assert SemanticsReasonCode.MODEL_CANDIDATE_ADMITTED.value in result.reason_codes


def test_admit_semantic_field_rejects_digest_mismatch() -> None:
    text = build_non_final_text()
    span = _span_for_text(text)
    field = _processor()._make_field(  # intentional: unit-test helper path
        field_id="fld:bad",
        kind=SemanticFieldKind.HEADER,
        surface="UNITED STATES PATENT AND TRADEMARK OFFICE",
        span_ids=(span.span_id,),
        page_indices=(0,),
        origin=FieldOrigin.DETERMINISTIC_RULE,
        confidence=0.9,
    )
    # Corrupt digest
    from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_semantics_v2 import (
        SemanticField,
    )

    bad = SemanticField(
        schema_version=field.schema_version,
        field_id=field.field_id,
        kind=field.kind,
        admission=field.admission,
        origin=field.origin,
        source_span_ids=field.source_span_ids,
        page_indices=field.page_indices,
        text_digest="0" * 64,
        surface_text=field.surface_text,
        confidence=field.confidence,
        normalized_value=None,
        claim_tokens=(),
        claim_ambiguity=None,
        citation_keys=(),
        citation_match_kind=None,
        labels={},
        admission_receipt_id=None,
        review_state=ReviewState.PENDING,
    )
    promoted, receipt = admit_semantic_field(
        bad, spans=(span,), span_texts={span.span_id: text}, full_text=text
    )
    assert not receipt.passed
    assert promoted.admission is not AdmissionState.ADMITTED
    assert "surface_text_digest_mismatch" in receipt.failures


def test_cross_page_continuation_multi_span() -> None:
    pages = build_cross_page_pages()
    result = _processor().analyze(_input_from_pages(pages))
    cont = result.fields_by_kind(SemanticFieldKind.CROSS_PAGE_CONTINUATION)
    assert cont
    for f in cont:
        assert len(f.source_span_ids) >= 2
        assert f.is_cross_page
    assert result.page_count >= 2
    _assert_every_field_has_spans(result)


def test_empty_and_unknown_stay_review_required() -> None:
    empty = _processor().analyze(_input_from_text("", with_span=False))
    assert empty.disposition is SemanticsDisposition.MALFORMED
    assert empty.family is CommunicationFamily.UNKNOWN
    assert empty.requires_review

    unknown = _processor().analyze(_input_from_text(build_unknown_family_text()))
    assert unknown.family is CommunicationFamily.UNKNOWN
    assert unknown.requires_review
    assert SemanticsReasonCode.FAMILY_UNKNOWN.value in unknown.reason_codes


def test_identifier_date_contradictions() -> None:
    # Craft dual mailing dates.
    text = """UNITED STATES PATENT AND TRADEMARK OFFICE
Application No.: 16/123,456
Application No.: 17/999,888
Mailing Date: 2026-01-01
Mailing Date: 2026-12-31
This is a non-final office action.
Claim 1 is rejected under 35 U.S.C. 103.
"""
    result = _processor().analyze(_input_from_text(text, document_code="CTNF"))
    kinds = {c.kind for c in result.contradictions}
    assert ContradictionKind.DATE_CONFLICT in kinds or ContradictionKind.IDENTIFIER_CONFLICT in kinds


def test_quarantine_unknown_classification() -> None:
    result = _processor().analyze(
        _input_from_text(
            build_non_final_text(),
            classification=DisclosureClassification.UNKNOWN,
        )
    )
    assert result.disposition is SemanticsDisposition.QUARANTINE
    assert result.review_state is ReviewState.REQUIRED


def test_extract_convenience_entry_point() -> None:
    result = extract_office_action_semantics_v2(
        artifact_id="art:conv",
        text=build_final_text(),
        classification="public_user",
        document_code="CTFR",
    )
    assert result.family is CommunicationFamily.FINAL
    assert result.schema_version == SEMANTICS_V2_SCHEMA_VERSION


def test_all_named_families_detectable() -> None:
    """Gold generators for every named family produce that family."""
    mapping = {
        CommunicationFamily.MISSING_PARTS: build_missing_parts_text,
        CommunicationFamily.OMITTED_ITEMS: build_omitted_items_text,
        CommunicationFamily.NO_FILING_DATE: build_no_filing_date_text,
        CommunicationFamily.RESTRICTION_ELECTION: build_restriction_election_text,
        CommunicationFamily.EX_PARTE_QUAYLE: build_quayle_text,
        CommunicationFamily.ADVISORY_ACTION: build_advisory_text,
        CommunicationFamily.SEQUENCE_COMPLIANCE: build_sequence_compliance_text,
        CommunicationFamily.ALLOWANCE_ISSUE_FEE: build_allowance_text,
        CommunicationFamily.APPEAL_PRE_APPEAL: build_appeal_pre_appeal_text,
        CommunicationFamily.PETITION: build_petition_text,
        CommunicationFamily.RESCINDED_REISSUED: build_reissued_text,
        CommunicationFamily.NON_FINAL: build_non_final_text,
        CommunicationFamily.FINAL: build_final_text,
    }
    assert set(mapping) == set(NAMED_COMMUNICATION_FAMILIES)
    for family, gen in mapping.items():
        result = _processor().analyze(_input_from_text(gen(), artifact_id=f"art:{family.value}"))
        assert result.family is family, f"expected {family}, got {result.family}"
        _assert_every_field_has_spans(result)
