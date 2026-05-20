"""Regression tests for positional citation/source-id decompiler slots."""

from ipfs_datasets_py.logic.modal.codec import modal_ir_to_flogic_triples
from ipfs_datasets_py.logic.modal.decompiler import (
    decode_modal_ir_document,
    decoded_modal_phrase_slot_text_map,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFrameLogic,
    ModalIRFormula,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


def _sample_document() -> ModalIRDocument:
    source_id = "us-code-21-360bbb-0-98e14cf1a6e12d46"
    formula = ModalIRFormula(
        formula_id="f-1",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_drug_approval"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=18,
            citation="21 U.S.C. 360bbb-0",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="21 U.S.C. 360bbb-0 temporary approval applies.",
        formulas=[formula],
    )


def _provenance_alignment_mismatch_sample_document() -> ModalIRDocument:
    source_id = "us-code-20-1131d-2a8fb06a45e3babe"
    formula = ModalIRFormula(
        formula_id="f-alignment-mismatch",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="publish_education_program_notice"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=17,
            citation="20 U.S.C. 1131e",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="20 U.S.C. 1131d compliance requirement.",
        formulas=[formula],
    )


def _provenance_alignment_trailing_punct_mismatch_sample_document() -> ModalIRDocument:
    source_id = "us-code-46-10318.-fce306c016fdd990"
    formula = ModalIRFormula(
        formula_id="f-alignment-trailing-punct-mismatch",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="publish_maritime_notice"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=18,
            citation="46 U.S.C. 10318",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="46 U.S.C. 10318 maritime notice requirement.",
        formulas=[formula],
    )


def _range_sample_document() -> ModalIRDocument:
    source_id = "us-code-45-228a to 228c-0123456789abcdef"
    formula = ModalIRFormula(
        formula_id="f-range",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_child_support_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=22,
            citation="45 U.S.C. 228a to 228c",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="45 U.S.C. 228a to 228c child support enforcement.",
        formulas=[formula],
    )


def _numeric_range_sample_document() -> ModalIRDocument:
    source_id = "us-code-50-1381 to 1398.-83310e751ed0d7a2"
    formula = ModalIRFormula(
        formula_id="f-numeric-range",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_homeland_security_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=24,
            citation="50 U.S.C. 1381 to 1398.",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="50 U.S.C. 1381 to 1398. Homeland security records are retained.",
        formulas=[formula],
    )


def _range_connector_mismatch_sample_document() -> ModalIRDocument:
    source_id = "us-code-50-4605 to 4610.-d52505ec5c91561e"
    formula = ModalIRFormula(
        formula_id="f-range-connector-mismatch",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_emergency_preparedness_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=27,
            citation="50 U.S.C. 4605 through 4610.",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=(
            "50 U.S.C. 4605 through 4610. Emergency preparedness records are retained."
        ),
        formulas=[formula],
    )


def _long_alpha_range_sample_document() -> ModalIRDocument:
    source_id = "us-code-43-616tttt to 616yyyy.-1e019a04fbdab0cb"
    formula = ModalIRFormula(
        formula_id="f-long-alpha-range",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_land_management_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=29,
            citation="43 U.S.C. 616tttt to 616yyyy.",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=(
            "43 U.S.C. 616tttt to 616yyyy. Land management records are retained."
        ),
        formulas=[formula],
    )


def _section_marker_sample_document() -> ModalIRDocument:
    source_id = "us-code-2-190l-01dd1648c5b1588c"
    formula = ModalIRFormula(
        formula_id="f-section-marker",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="preserve_library_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=18,
            citation="2 U.S.C. §190l",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="2 U.S.C. 190l preservation requirement.",
        formulas=[formula],
    )


def _plural_section_marker_range_sample_document() -> ModalIRDocument:
    source_id = "us-code-45-228a to 228c-0123456789abcdef"
    formula = ModalIRFormula(
        formula_id="f-plural-section-marker-range",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_child_support_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=24,
            citation="45 U.S.C. §§ 228a to 228c.",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="45 U.S.C. 228a to 228c child support enforcement.",
        formulas=[formula],
    )


def _single_component_sample_document() -> ModalIRDocument:
    source_id = "us-code-2-190l-01dd1648c5b1588c"
    formula = ModalIRFormula(
        formula_id="f-single",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="preserve_library_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=17,
            citation="2 U.S.C. 190l",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="2 U.S.C. 190l preservation requirement.",
        formulas=[formula],
    )


def _trailing_punct_sample_document() -> ModalIRDocument:
    source_id = "us-code-46-60101.-6bea2346c1c5229c"
    formula = ModalIRFormula(
        formula_id="f-trailing-punct",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="board_arriving_vessels_before_inspection"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=29,
            citation="46 U.S.C. 60101.",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="46 U.S.C. 60101. Boarding arriving vessels before inspection.",
        formulas=[formula],
    )


def _dot_delimited_sample_document() -> ModalIRDocument:
    source_id = "us-code-42-1396.1-8fb22f17ff2a43cd"
    formula = ModalIRFormula(
        formula_id="f-dot-delimited",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="publish_healthcare_rule_update"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=20,
            citation="42 U.S.C. 1396.1",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="42 U.S.C. 1396.1 publication rule update applies.",
        formulas=[formula],
    )


def _roman_suffix_hyphen_sample_document() -> ModalIRDocument:
    source_id = "us-code-16-460iii-4-aa834016adcc86bf"
    formula = ModalIRFormula(
        formula_id="f-roman-suffix",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_national_park_access"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=23,
            citation="16 U.S.C. 460iii-4",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="16 U.S.C. 460iii-4 national park access requirement.",
        formulas=[formula],
    )


def _compound_alpha_suffix_hyphen_sample_document() -> ModalIRDocument:
    source_id = "us-code-16-460eee-2-151f071e709ab648"
    formula = ModalIRFormula(
        formula_id="f-compound-alpha-suffix",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_federal_land_withdrawal_notice"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=23,
            citation="16 U.S.C. 460eee-2",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="16 U.S.C. 460eee-2 federal land withdrawal notice requirement.",
        formulas=[formula],
    )


def _noncanonical_romanlike_suffix_sample_document() -> ModalIRDocument:
    source_id = "us-code-21-360ll-11684335ce2f2caa"
    formula = ModalIRFormula(
        formula_id="f-noncanonical-romanlike",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_drug_device_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=18,
            citation="21 U.S.C. 360ll",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="21 U.S.C. 360ll recordkeeping requirement.",
        formulas=[formula],
    )


def _repeat_roman_token_suffix_sample_document() -> ModalIRDocument:
    source_id = "us-code-42-3797cc-445d9bb6c7d68792"
    formula = ModalIRFormula(
        formula_id="f-repeat-roman-token",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_federal_program_reporting"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=20,
            citation="42 U.S.C. 3797cc",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="42 U.S.C. 3797cc reporting requirements apply.",
        formulas=[formula],
    )


def _zero_formula_sample_document() -> ModalIRDocument:
    source_id = "us-code-50-3091.-8130665c952dd22a"
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="This section is transferred.",
        formulas=[],
        metadata={
            "citation": "50 U.S.C. 3091.",
        },
    )


def _zero_formula_source_id_only_sample_document() -> ModalIRDocument:
    source_id = "us-code-22-7636-27b6423bb5340be0"
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="State Department reporting requirement.",
        formulas=[],
    )


def _formula_missing_citation_sample_document() -> ModalIRDocument:
    source_id = "us-code-18-1719-6841cc7ab2076858"
    formula = ModalIRFormula(
        formula_id="f-missing-citation",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_mailing_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=18,
            citation=None,
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="18 U.S.C. 1719 mailing records requirement.",
        formulas=[formula],
    )


def _coarse_heading_tail_sample_document() -> ModalIRDocument:
    source_id = "us-code-20-741-d9743e9c6ae8213e"
    formula = ModalIRFormula(
        formula_id="f-coarse-heading-tail",
        operator=ModalIROperator(
            family="frame",
            system="frame",
            symbol="Frame",
            label="framed as",
        ),
        predicate=ModalIRPredicate(name="uscode_section_heading_fallback"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=8,
            citation="20 U.S.C. 741",
        ),
        metadata={"fallback_rule": "uscode_section_heading_coarse_v1"},
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="Sec. 741. Student aid program improvements.",
        formulas=[formula],
    )


def _procedural_keyword_fallback_sample_document() -> ModalIRDocument:
    source_id = "us-code-10-1095c-95cb9940fa4690f6"
    formula = ModalIRFormula(
        formula_id="f-procedural-keyword",
        operator=ModalIROperator(
            family="frame",
            system="frame",
            symbol="Frame",
            label="framed as",
        ),
        predicate=ModalIRPredicate(name="uscode_procedural_clause_fallback"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=82,
            citation="10 U.S.C. 1095c",
        ),
        metadata={
            "cue": "__uscode_procedural_clause_fallback__",
            "fallback_rule": "uscode_procedural_clause_v1",
            "procedural_keyword": "review",
        },
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=(
            "Administrative review procedures are established for health care "
            "collection actions."
        ),
        formulas=[formula],
    )


def _typed_clause_scope_sample_document() -> ModalIRDocument:
    source_id = "us-code-7-6409-502d7cea35400f08"
    normalized_text = (
        "Provided that the applicant submits annual reports, assistance is "
        "available, except as otherwise provided in subsection (b)."
    )
    formula = ModalIRFormula(
        formula_id="f-typed-clause-scope",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="provide_assistance"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(normalized_text),
            citation="7 U.S.C. 6409",
        ),
        conditions=["provided that the applicant submits annual reports"],
        exceptions=["except as otherwise provided in subsection (b)"],
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=normalized_text,
        formulas=[formula],
    )


def _exception_only_condition_proxy_sample_document() -> ModalIRDocument:
    source_id = "us-code-42-1395c.-da5383050c7a2c5e"
    normalized_text = (
        "A plan may provide coverage except as such a determination applies."
    )
    formula = ModalIRFormula(
        formula_id="f-exception-only-condition-proxy",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O|",
            label="conditionally obligatory",
        ),
        predicate=ModalIRPredicate(name="provide_coverage"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(normalized_text),
            citation="42 U.S.C. 1395c.",
        ),
        exceptions=["except as such a determination applies"],
        metadata={"cue": "may"},
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=normalized_text,
        formulas=[formula],
    )


def _cue_signature_temporal_clause_sample_document() -> ModalIRDocument:
    source_id = "us-code-10-864-47dfb7b7e13861a9"
    sentence_one = "The applicant shall submit a report if requested."
    sentence_two = "By March 1 the agency shall publish findings after review."
    normalized_text = f"{sentence_one} {sentence_two}"
    deontic_formula = ModalIRFormula(
        formula_id="f-cue-1",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="submit_report"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(sentence_one),
            citation="10 U.S.C. 864",
        ),
        conditions=["if requested"],
        metadata={"cue": "shall"},
    )
    temporal_start = len(sentence_one) + 1
    temporal_formula = ModalIRFormula(
        formula_id="f-cue-2",
        operator=ModalIROperator(
            family="temporal",
            system="ltl",
            symbol="F",
            label="eventually",
        ),
        predicate=ModalIRPredicate(name="publish_findings"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=temporal_start,
            end_char=len(normalized_text),
            citation="10 U.S.C. 864",
        ),
        conditions=[
            "after the agency receives notice",
            "by march 1",
        ],
        metadata={"cue": "by"},
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=normalized_text,
        formulas=[deontic_formula, temporal_formula],
    )


def _temporal_until_clause_sample_document() -> ModalIRDocument:
    source_id = "us-code-5-8123-1b66f2d0a8c10984"
    normalized_text = "The agency shall maintain records until final review is complete."
    formula = ModalIRFormula(
        formula_id="f-temporal-until",
        operator=ModalIROperator(
            family="temporal",
            system="ltl",
            symbol="F",
            label="eventually",
        ),
        predicate=ModalIRPredicate(name="maintain_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=len(normalized_text),
            citation="5 U.S.C. 8123",
        ),
        conditions=["until final review is complete"],
        metadata={"cue": "until"},
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=normalized_text,
        formulas=[formula],
    )


def _zero_digit_signature_sample_document() -> ModalIRDocument:
    source_id = "us-code-43-1470.-845d9dceb9d264ab"
    formula = ModalIRFormula(
        formula_id="f-zero-digit-signature",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="preserve_land_patent_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=18,
            citation="43 U.S.C. 1470.",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="43 U.S.C. 1470. Land patent adjustment applies.",
        formulas=[formula],
    )


def _upper_alpha_suffix_sample_document() -> ModalIRDocument:
    source_id = "us-code-26-1400L-f8d163d7baa2349b"
    formula = ModalIRFormula(
        formula_id="f-upper-alpha-suffix",
        operator=ModalIROperator(
            family="deontic",
            system="kd",
            symbol="O",
            label="obligatory",
        ),
        predicate=ModalIRPredicate(name="maintain_economic_records"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=20,
            citation="26 U.S.C. 1400L",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="26 U.S.C. 1400L recordkeeping requirement.",
        formulas=[formula],
    )


def _citation_suffix_kind_residual_samples() -> list[ModalIRDocument]:
    cases = [
        (
            "us-code-16-198a-69c109aec60f214a",
            "16 U.S.C. 198a",
            "maintain_national_memorial_records",
        ),
        (
            "us-code-22-1642e-0a4a6e0aa906f829",
            "22 U.S.C. 1642e",
            "maintain_foreign_relations_records",
        ),
        (
            "us-code-25-450a-1-b25ed1d7e3a8d3a7",
            "25 U.S.C. 450a-1",
            "maintain_tribal_contract_records",
        ),
        (
            "us-code-46-12107.-ac993296d58346dd",
            "46 U.S.C. 12107.",
            "maintain_vessel_documentation_records",
        ),
    ]
    documents: list[ModalIRDocument] = []
    for source_id, citation, predicate_name in cases:
        documents.append(
            ModalIRDocument(
                document_id=source_id,
                source="us_code",
                normalized_text=f"{citation} records requirement.",
                formulas=[
                    ModalIRFormula(
                        formula_id=f"f-{source_id}",
                        operator=ModalIROperator(
                            family="deontic",
                            system="kd",
                            symbol="O",
                            label="obligatory",
                        ),
                        predicate=ModalIRPredicate(name=predicate_name),
                        provenance=ModalIRProvenance(
                            source_id=source_id,
                            start_char=0,
                            end_char=len(citation),
                            citation=citation,
                        ),
                    )
                ],
            )
        )
    return documents


def _span_metrics_sample_document() -> ModalIRDocument:
    source_id = "us-code-42-12782.-01f3026e32e90a63"
    source_text = "ABCDEFGHIJKLMNOPQRST"
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id="f-span-1",
                operator=ModalIROperator(
                    family="deontic",
                    system="kd",
                    symbol="O",
                    label="obligatory",
                ),
                predicate=ModalIRPredicate(name="first_span"),
                provenance=ModalIRProvenance(
                    source_id=source_id,
                    start_char=0,
                    end_char=6,
                    citation="42 U.S.C. 12782.",
                ),
            ),
            ModalIRFormula(
                formula_id="f-span-2",
                operator=ModalIROperator(
                    family="deontic",
                    system="kd",
                    symbol="O",
                    label="obligatory",
                ),
                predicate=ModalIRPredicate(name="second_span"),
                provenance=ModalIRProvenance(
                    source_id=source_id,
                    start_char=9,
                    end_char=14,
                    citation="42 U.S.C. 12782.",
                ),
            ),
        ],
    )


def _single_formula_temporal_family_sample_document() -> ModalIRDocument:
    source_id = "us-code-7-8758-6c50bb2c1676bbf9"
    formula = ModalIRFormula(
        formula_id="f-temporal-family-only",
        operator=ModalIROperator(
            family="temporal",
            system="ltl",
            symbol="F",
            label="eventually",
        ),
        predicate=ModalIRPredicate(name="publish_notice"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=22,
            citation="7 U.S.C. 8758",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="7 U.S.C. 8758 notice publication requirement.",
        formulas=[formula],
    )


def _fallback_frame_authority_cue_sample_document() -> ModalIRDocument:
    source_id = "us-code-46-2104.-968c80c773abaeae"
    formula = ModalIRFormula(
        formula_id="f-fallback-frame-authority-cue",
        operator=ModalIROperator(
            family="frame",
            system="frame",
            symbol="Frame",
            label="framed as",
        ),
        predicate=ModalIRPredicate(name="authorities_personnel_relating"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=42,
            citation="46 U.S.C. 2104.",
        ),
        metadata={
            "cue": "__uscode_section_heading_fallback__",
            "fallback_rule": "uscode_section_heading_v1",
        },
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="Authorities and personnel relating to vessel documentation.",
        formulas=[formula],
    )


def _metadata_only_frame_terms_sample_document() -> ModalIRDocument:
    source_id = "us-code-26-646-0cfbbfe0c86b90ae"
    formula = ModalIRFormula(
        formula_id="f-frame-metadata-only",
        operator=ModalIROperator(
            family="temporal",
            system="ltl",
            symbol="F",
            label="eventually",
        ),
        predicate=ModalIRPredicate(name="publish_deadline_notice"),
        provenance=ModalIRProvenance(
            source_id=source_id,
            start_char=0,
            end_char=38,
            citation="26 U.S.C. 646",
        ),
    )
    return ModalIRDocument(
        document_id=source_id,
        source="us_code",
        normalized_text="26 U.S.C. 646 agency notice and deadline appeal process.",
        formulas=[formula],
        frame_logic=ModalIRFrameLogic(selected_frame="administrative_notice_hearing"),
        metadata={
            "frame_ontology_terms": {
                "administrative_notice_hearing": [
                    "administrative",
                    "administrative_notice_hearing",
                    "agency",
                    "appeal",
                    "deadline",
                ],
                "criminal_penalty_enforcement": [
                    "criminal",
                    "enforcement",
                    "penalty",
                ],
                "housing_voucher_benefits": [
                    "accommodation",
                    "housing",
                    "voucher",
                ],
            }
        },
    )


def test_decode_modal_ir_document_emits_positional_citation_slots() -> None:
    decoded = decode_modal_ir_document(_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_title_number"] == ["21"]
    assert slot_map["citation_title_token_count"] == ["1"]
    assert slot_map["citation_title_stem"] == ["21"]
    assert slot_map["citation_section_has_mixed_token"] == ["true"]
    assert slot_map["citation_section_mixed_token_count"] == ["1"]
    assert slot_map["citation_section_alnum_segment_count"] == ["3"]
    assert slot_map["citation_section_alnum_segment_prefix"] == ["360"]
    assert slot_map["citation_section_alnum_segment_suffix"] == ["0"]
    assert slot_map["citation_section_alnum_segment_positioned"] == [
        "1:360",
        "2:bbb",
        "3:0",
    ]
    assert slot_map["citation_section_alnum_segment_kind_positioned"] == [
        "1:numeric",
        "2:alpha",
        "3:numeric",
    ]
    assert slot_map["citation_section_component_positioned"] == ["1:360bbb", "2:0"]
    assert slot_map["citation_section_number_positioned"] == ["1:360", "2:0"]
    assert slot_map["citation_section_number_digit_count"] == ["3", "1"]
    assert slot_map["citation_section_number_digit_count_positioned"] == ["1:3", "2:1"]
    assert slot_map["citation_section_suffix_positioned"] == ["1:bbb"]
    assert slot_map["citation_section_suffix_char_count"] == ["3"]
    assert slot_map["citation_section_suffix_char_count_positioned"] == ["1:3"]
    assert slot_map["citation_section_suffix_profile"] == ["repeat"]
    assert slot_map["citation_section_suffix_profile_positioned"] == ["1:repeat"]
    assert slot_map["citation_section_suffix_normalized"] == ["bbb"]
    assert slot_map["citation_section_suffix_case"] == ["lower"]
    assert slot_map["citation_section_suffix_case_positioned"] == ["1:lower"]
    assert slot_map["citation_section_component_kind_positioned"] == [
        "1:alphanumeric",
        "2:numeric",
    ]
    assert slot_map["citation_section_primary_number"] == ["360"]
    assert slot_map["citation_section_primary_number_digit_count"] == ["3"]
    assert slot_map["citation_section_primary_suffix"] == ["bbb"]
    assert slot_map["citation_section_primary_suffix_char_count"] == ["3"]
    assert slot_map["citation_section_primary_suffix_profile"] == ["repeat"]
    assert slot_map["citation_section_has_suffix"] == ["true"]
    assert slot_map["citation_section_has_roman_suffix"] == ["false"]
    assert slot_map["citation_section_primary_has_suffix"] == ["true"]
    assert slot_map["citation_section_primary_suffix_is_roman"] == ["false"]
    assert slot_map["citation_section_terminal_has_suffix"] == ["false"]
    assert slot_map["citation_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["citation_section_roman_suffix_component_count"] == ["0"]
    assert slot_map["citation_section_primary_component_kind"] == ["alphanumeric"]
    assert slot_map["citation_section_terminal_number"] == ["0"]
    assert slot_map["citation_section_terminal_number_digit_count"] == ["1"]
    assert slot_map["citation_section_terminal_component_kind"] == ["numeric"]
    assert slot_map["citation_section_has_delimiter"] == ["true"]
    assert slot_map["citation_section_delimiter"] == ["hyphen"]
    assert slot_map["citation_section_delimiter_positioned"] == ["1:hyphen"]
    assert slot_map["citation_section_delimiter_token"] == ["-"]
    assert slot_map["citation_section_delimiter_token_positioned"] == ["1:-"]
    assert slot_map["citation_section_delimiter_count"] == ["1"]
    assert slot_map["citation_section_delimiter_char_count"] == ["1"]
    assert slot_map["citation_section_delimiter_char_count_positioned"] == ["1:1"]
    assert slot_map["citation_section_delimiter_pattern"] == ["hyphen"]
    assert slot_map["citation_section_delimiter_distinct_count"] == ["1"]
    assert slot_map["citation_section_is_range"] == ["false"]
    assert slot_map["citation_section_has_trailing_punct"] == ["false"]
    assert slot_map["citation_section_trailing_punct_count"] == ["0"]
    assert slot_map["citation_title_section_key"] == ["21:360bbb-0"]
    assert slot_map["citation_title_section_key_normalized"] == ["21:360bbb-0"]
    assert slot_map["citation_title_section_primary_number_relation"] == ["ascending"]
    assert slot_map["citation_title_section_primary_number_span"] == ["339"]
    assert slot_map["citation_title_section_terminal_number_relation"] == ["descending"]
    assert slot_map["citation_title_section_terminal_number_span"] == ["21"]

    assert slot_map["source_id_section_component_positioned"] == ["1:360bbb", "2:0"]
    assert slot_map["source_id_section_has_mixed_token"] == ["true"]
    assert slot_map["source_id_section_mixed_token_count"] == ["1"]
    assert slot_map["source_id_section_alnum_segment_count"] == ["3"]
    assert slot_map["source_id_section_alnum_segment_prefix"] == ["360"]
    assert slot_map["source_id_section_alnum_segment_suffix"] == ["0"]
    assert slot_map["source_id_section_alnum_segment_positioned"] == [
        "1:360",
        "2:bbb",
        "3:0",
    ]
    assert slot_map["source_id_section_alnum_segment_kind_positioned"] == [
        "1:numeric",
        "2:alpha",
        "3:numeric",
    ]
    assert slot_map["source_id_section_number_positioned"] == ["1:360", "2:0"]
    assert slot_map["source_id_section_number_digit_count"] == ["3", "1"]
    assert slot_map["source_id_section_number_digit_count_positioned"] == ["1:3", "2:1"]
    assert slot_map["source_id_section_suffix_positioned"] == ["1:bbb"]
    assert slot_map["source_id_section_suffix_char_count"] == ["3"]
    assert slot_map["source_id_section_suffix_char_count_positioned"] == ["1:3"]
    assert slot_map["source_id_section_suffix_profile"] == ["repeat"]
    assert slot_map["source_id_section_suffix_profile_positioned"] == ["1:repeat"]
    assert slot_map["source_id_section_suffix_normalized"] == ["bbb"]
    assert slot_map["source_id_section_suffix_case"] == ["lower"]
    assert slot_map["source_id_section_suffix_case_positioned"] == ["1:lower"]
    assert slot_map["source_id_section_component_kind_positioned"] == [
        "1:alphanumeric",
        "2:numeric",
    ]
    assert slot_map["source_id_section_primary_number"] == ["360"]
    assert slot_map["source_id_section_primary_number_digit_count"] == ["3"]
    assert slot_map["source_id_section_primary_suffix"] == ["bbb"]
    assert slot_map["source_id_section_primary_suffix_char_count"] == ["3"]
    assert slot_map["source_id_section_primary_suffix_profile"] == ["repeat"]
    assert slot_map["source_id_section_has_suffix"] == ["true"]
    assert slot_map["source_id_section_has_roman_suffix"] == ["false"]
    assert slot_map["source_id_section_primary_has_suffix"] == ["true"]
    assert slot_map["source_id_section_primary_suffix_is_roman"] == ["false"]
    assert slot_map["source_id_section_terminal_has_suffix"] == ["false"]
    assert slot_map["source_id_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["source_id_section_roman_suffix_component_count"] == ["0"]
    assert slot_map["source_id_section_primary_component_kind"] == ["alphanumeric"]
    assert slot_map["source_id_section_terminal_number"] == ["0"]
    assert slot_map["source_id_section_terminal_number_digit_count"] == ["1"]
    assert slot_map["source_id_section_terminal_component_kind"] == ["numeric"]
    assert slot_map["source_id_section_has_delimiter"] == ["true"]
    assert slot_map["source_id_section_delimiter"] == ["hyphen"]
    assert slot_map["source_id_section_delimiter_positioned"] == ["1:hyphen"]
    assert slot_map["source_id_section_delimiter_token"] == ["-"]
    assert slot_map["source_id_section_delimiter_token_positioned"] == ["1:-"]
    assert slot_map["source_id_section_delimiter_count"] == ["1"]
    assert slot_map["source_id_section_delimiter_char_count"] == ["1"]
    assert slot_map["source_id_section_delimiter_char_count_positioned"] == ["1:1"]
    assert slot_map["source_id_section_delimiter_pattern"] == ["hyphen"]
    assert slot_map["source_id_section_delimiter_distinct_count"] == ["1"]
    assert slot_map["source_id_section_is_range"] == ["false"]
    assert slot_map["source_id_section_has_trailing_punct"] == ["false"]
    assert slot_map["source_id_section_trailing_punct_count"] == ["0"]
    assert slot_map["source_id_title_section_key"] == ["21:360bbb-0"]
    assert slot_map["source_id_title_section_key_normalized"] == ["21:360bbb-0"]
    assert slot_map["source_id_title_section_primary_number_relation"] == ["ascending"]
    assert slot_map["source_id_title_section_primary_number_span"] == ["339"]
    assert slot_map["source_id_title_section_terminal_number_relation"] == ["descending"]
    assert slot_map["source_id_title_section_terminal_number_span"] == ["21"]


def test_modal_ir_to_flogic_triples_emits_positional_citation_components() -> None:
    triples = modal_ir_to_flogic_triples(_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_title_number") == ["21"]
    assert objects("citation_title_token_count") == ["1"]
    assert objects("citation_title_stem") == ["21"]
    assert objects("citation_section_has_mixed_token") == ["true"]
    assert objects("citation_section_mixed_token_count") == ["1"]
    assert objects("citation_section_alnum_segment_count") == ["3"]
    assert objects("citation_section_alnum_segment_prefix") == ["360"]
    assert objects("citation_section_alnum_segment_suffix") == ["0"]
    assert objects("citation_section_alnum_segment_positioned") == [
        "1:360",
        "2:bbb",
        "3:0",
    ]
    assert objects("citation_section_alnum_segment_kind_positioned") == [
        "1:numeric",
        "2:alpha",
        "3:numeric",
    ]
    assert objects("citation_section_component_positioned") == ["1:360bbb", "2:0"]
    assert objects("citation_section_number_positioned") == ["1:360", "2:0"]
    assert objects("citation_section_number_digit_count") == ["3", "1"]
    assert objects("citation_section_number_digit_count_positioned") == ["1:3", "2:1"]
    assert objects("citation_section_suffix_positioned") == ["1:bbb"]
    assert objects("citation_section_suffix_char_count") == ["3"]
    assert objects("citation_section_suffix_char_count_positioned") == ["1:3"]
    assert objects("citation_section_suffix_profile") == ["repeat"]
    assert objects("citation_section_suffix_profile_positioned") == ["1:repeat"]
    assert objects("citation_section_suffix_normalized") == ["bbb"]
    assert objects("citation_section_suffix_case") == ["lower"]
    assert objects("citation_section_suffix_case_positioned") == ["1:lower"]
    assert objects("citation_section_component_kind_positioned") == [
        "1:alphanumeric",
        "2:numeric",
    ]
    assert objects("citation_section_primary_number") == ["360"]
    assert objects("citation_section_primary_number_digit_count") == ["3"]
    assert objects("citation_section_primary_suffix") == ["bbb"]
    assert objects("citation_section_primary_suffix_char_count") == ["3"]
    assert objects("citation_section_primary_suffix_profile") == ["repeat"]
    assert objects("citation_section_has_suffix") == ["true"]
    assert objects("citation_section_has_roman_suffix") == ["false"]
    assert objects("citation_section_primary_has_suffix") == ["true"]
    assert objects("citation_section_primary_suffix_is_roman") == ["false"]
    assert objects("citation_section_terminal_has_suffix") == ["false"]
    assert objects("citation_section_terminal_suffix_is_roman") == ["false"]
    assert objects("citation_section_roman_suffix_component_count") == ["0"]
    assert objects("citation_section_primary_component_kind") == ["alphanumeric"]
    assert objects("citation_section_terminal_number") == ["0"]
    assert objects("citation_section_terminal_number_digit_count") == ["1"]
    assert objects("citation_section_terminal_component_kind") == ["numeric"]
    assert objects("citation_section_has_delimiter") == ["true"]
    assert objects("citation_section_delimiter") == ["hyphen"]
    assert objects("citation_section_delimiter_positioned") == ["1:hyphen"]
    assert objects("citation_section_delimiter_token") == ["-"]
    assert objects("citation_section_delimiter_token_positioned") == ["1:-"]
    assert objects("citation_section_delimiter_count") == ["1"]
    assert objects("citation_section_delimiter_char_count") == ["1"]
    assert objects("citation_section_delimiter_char_count_positioned") == ["1:1"]
    assert objects("citation_section_delimiter_pattern") == ["hyphen"]
    assert objects("citation_section_delimiter_distinct_count") == ["1"]
    assert objects("citation_section_is_range") == ["false"]
    assert objects("citation_section_has_trailing_punct") == ["false"]
    assert objects("citation_section_trailing_punct_count") == ["0"]
    assert objects("citation_title_section_key") == ["21:360bbb-0"]
    assert objects("citation_title_section_key_normalized") == ["21:360bbb-0"]
    assert objects("citation_title_section_primary_number_relation") == ["ascending"]
    assert objects("citation_title_section_primary_number_span") == ["339"]
    assert objects("citation_title_section_terminal_number_relation") == ["descending"]
    assert objects("citation_title_section_terminal_number_span") == ["21"]

    assert objects("source_id_section_component_positioned") == ["1:360bbb", "2:0"]
    assert objects("source_id_section_has_mixed_token") == ["true"]
    assert objects("source_id_section_mixed_token_count") == ["1"]
    assert objects("source_id_section_alnum_segment_count") == ["3"]
    assert objects("source_id_section_alnum_segment_prefix") == ["360"]
    assert objects("source_id_section_alnum_segment_suffix") == ["0"]
    assert objects("source_id_section_alnum_segment_positioned") == [
        "1:360",
        "2:bbb",
        "3:0",
    ]
    assert objects("source_id_section_alnum_segment_kind_positioned") == [
        "1:numeric",
        "2:alpha",
        "3:numeric",
    ]
    assert objects("source_id_section_number_positioned") == ["1:360", "2:0"]
    assert objects("source_id_section_number_digit_count") == ["3", "1"]
    assert objects("source_id_section_number_digit_count_positioned") == ["1:3", "2:1"]
    assert objects("source_id_section_suffix_positioned") == ["1:bbb"]
    assert objects("source_id_section_suffix_char_count") == ["3"]
    assert objects("source_id_section_suffix_char_count_positioned") == ["1:3"]
    assert objects("source_id_section_suffix_profile") == ["repeat"]
    assert objects("source_id_section_suffix_profile_positioned") == ["1:repeat"]
    assert objects("source_id_section_suffix_normalized") == ["bbb"]
    assert objects("source_id_section_suffix_case") == ["lower"]
    assert objects("source_id_section_suffix_case_positioned") == ["1:lower"]
    assert objects("source_id_section_component_kind_positioned") == [
        "1:alphanumeric",
        "2:numeric",
    ]
    assert objects("source_id_section_primary_number") == ["360"]
    assert objects("source_id_section_primary_number_digit_count") == ["3"]
    assert objects("source_id_section_primary_suffix") == ["bbb"]
    assert objects("source_id_section_primary_suffix_char_count") == ["3"]
    assert objects("source_id_section_primary_suffix_profile") == ["repeat"]
    assert objects("source_id_section_has_suffix") == ["true"]
    assert objects("source_id_section_has_roman_suffix") == ["false"]
    assert objects("source_id_section_primary_has_suffix") == ["true"]
    assert objects("source_id_section_primary_suffix_is_roman") == ["false"]
    assert objects("source_id_section_terminal_has_suffix") == ["false"]
    assert objects("source_id_section_terminal_suffix_is_roman") == ["false"]
    assert objects("source_id_section_roman_suffix_component_count") == ["0"]
    assert objects("source_id_section_primary_component_kind") == ["alphanumeric"]
    assert objects("source_id_section_terminal_number") == ["0"]
    assert objects("source_id_section_terminal_number_digit_count") == ["1"]
    assert objects("source_id_section_terminal_component_kind") == ["numeric"]
    assert objects("source_id_section_has_delimiter") == ["true"]
    assert objects("source_id_section_delimiter") == ["hyphen"]
    assert objects("source_id_section_delimiter_positioned") == ["1:hyphen"]
    assert objects("source_id_section_delimiter_token") == ["-"]
    assert objects("source_id_section_delimiter_token_positioned") == ["1:-"]
    assert objects("source_id_section_delimiter_count") == ["1"]
    assert objects("source_id_section_delimiter_char_count") == ["1"]
    assert objects("source_id_section_delimiter_char_count_positioned") == ["1:1"]
    assert objects("source_id_section_delimiter_pattern") == ["hyphen"]
    assert objects("source_id_section_delimiter_distinct_count") == ["1"]
    assert objects("source_id_section_is_range") == ["false"]
    assert objects("source_id_section_has_trailing_punct") == ["false"]
    assert objects("source_id_section_trailing_punct_count") == ["0"]
    assert objects("source_id_title_section_key") == ["21:360bbb-0"]
    assert objects("source_id_title_section_key_normalized") == ["21:360bbb-0"]
    assert objects("source_id_title_section_primary_number_relation") == ["ascending"]
    assert objects("source_id_title_section_primary_number_span") == ["339"]
    assert objects("source_id_title_section_terminal_number_relation") == ["descending"]
    assert objects("source_id_title_section_terminal_number_span") == ["21"]


def test_decode_modal_ir_document_emits_single_component_section_role_slots() -> None:
    decoded = decode_modal_ir_document(_single_component_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_terminal"] == ["190l"]
    assert slot_map["citation_section_primary_equals_terminal"] == ["true"]
    assert slot_map["citation_section_primary_terminal_pair"] == ["190l|190l"]
    assert slot_map["citation_section_primary_number"] == ["190"]
    assert slot_map["citation_section_primary_number_digit_count"] == ["3"]
    assert slot_map["citation_section_terminal_number"] == ["190"]
    assert slot_map["citation_section_terminal_number_digit_count"] == ["3"]
    assert slot_map["citation_section_primary_suffix"] == ["l"]
    assert slot_map["citation_section_suffix_char_count"] == ["1"]
    assert slot_map["citation_section_primary_suffix_char_count"] == ["1"]
    assert slot_map["citation_section_terminal_suffix_char_count"] == ["1"]
    assert slot_map["citation_section_suffix_profile"] == ["single"]
    assert slot_map["citation_section_primary_suffix_profile"] == ["single"]
    assert slot_map["citation_section_terminal_suffix_profile"] == ["single"]
    assert slot_map["citation_section_has_suffix"] == ["true"]
    assert slot_map["citation_section_primary_has_suffix"] == ["true"]
    assert slot_map["citation_section_terminal_has_suffix"] == ["true"]
    assert slot_map["citation_section_terminal_suffix"] == ["l"]
    assert slot_map["citation_section_primary_component_kind"] == ["alphanumeric"]
    assert slot_map["citation_section_terminal_component_kind"] == ["alphanumeric"]
    assert slot_map["citation_section_primary_terminal_component_signature_pair"] == [
        "N3A1|N3A1"
    ]
    assert slot_map["citation_section_primary_terminal_component_signature_match"] == [
        "true"
    ]
    assert slot_map["citation_section_primary_terminal_component_kind_pair"] == [
        "alphanumeric|alphanumeric"
    ]
    assert slot_map["citation_section_primary_terminal_component_kind_match"] == ["true"]

    assert slot_map["source_id_section_terminal"] == ["190l"]
    assert slot_map["source_id_section_primary_equals_terminal"] == ["true"]
    assert slot_map["source_id_section_primary_terminal_pair"] == ["190l|190l"]
    assert slot_map["source_id_section_primary_number"] == ["190"]
    assert slot_map["source_id_section_primary_number_digit_count"] == ["3"]
    assert slot_map["source_id_section_terminal_number"] == ["190"]
    assert slot_map["source_id_section_terminal_number_digit_count"] == ["3"]
    assert slot_map["source_id_section_primary_suffix"] == ["l"]
    assert slot_map["source_id_section_suffix_char_count"] == ["1"]
    assert slot_map["source_id_section_primary_suffix_char_count"] == ["1"]
    assert slot_map["source_id_section_terminal_suffix_char_count"] == ["1"]
    assert slot_map["source_id_section_suffix_profile"] == ["single"]
    assert slot_map["source_id_section_primary_suffix_profile"] == ["single"]
    assert slot_map["source_id_section_terminal_suffix_profile"] == ["single"]
    assert slot_map["source_id_section_has_suffix"] == ["true"]
    assert slot_map["source_id_section_primary_has_suffix"] == ["true"]
    assert slot_map["source_id_section_terminal_has_suffix"] == ["true"]
    assert slot_map["source_id_section_terminal_suffix"] == ["l"]
    assert slot_map["source_id_section_primary_component_kind"] == ["alphanumeric"]
    assert slot_map["source_id_section_terminal_component_kind"] == ["alphanumeric"]
    assert slot_map["source_id_section_primary_terminal_component_signature_pair"] == [
        "N3A1|N3A1"
    ]
    assert slot_map["source_id_section_primary_terminal_component_signature_match"] == [
        "true"
    ]
    assert slot_map["source_id_section_primary_terminal_component_kind_pair"] == [
        "alphanumeric|alphanumeric"
    ]
    assert slot_map["source_id_section_primary_terminal_component_kind_match"] == ["true"]


def test_modal_ir_to_flogic_triples_emits_single_component_section_role_slots() -> None:
    triples = modal_ir_to_flogic_triples(_single_component_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_terminal") == ["190l"]
    assert objects("citation_section_primary_equals_terminal") == ["true"]
    assert objects("citation_section_primary_terminal_pair") == ["190l|190l"]
    assert objects("citation_section_primary_number") == ["190"]
    assert objects("citation_section_primary_number_digit_count") == ["3"]
    assert objects("citation_section_terminal_number") == ["190"]
    assert objects("citation_section_terminal_number_digit_count") == ["3"]
    assert objects("citation_section_primary_suffix") == ["l"]
    assert objects("citation_section_suffix_char_count") == ["1"]
    assert objects("citation_section_primary_suffix_char_count") == ["1"]
    assert objects("citation_section_terminal_suffix_char_count") == ["1"]
    assert objects("citation_section_suffix_profile") == ["single"]
    assert objects("citation_section_primary_suffix_profile") == ["single"]
    assert objects("citation_section_terminal_suffix_profile") == ["single"]
    assert objects("citation_section_has_suffix") == ["true"]
    assert objects("citation_section_primary_has_suffix") == ["true"]
    assert objects("citation_section_terminal_has_suffix") == ["true"]
    assert objects("citation_section_terminal_suffix") == ["l"]
    assert objects("citation_section_primary_component_kind") == ["alphanumeric"]
    assert objects("citation_section_terminal_component_kind") == ["alphanumeric"]
    assert objects("citation_section_primary_terminal_component_signature_pair") == [
        "N3A1|N3A1"
    ]
    assert objects("citation_section_primary_terminal_component_signature_match") == [
        "true"
    ]
    assert objects("citation_section_primary_terminal_component_kind_pair") == [
        "alphanumeric|alphanumeric"
    ]
    assert objects("citation_section_primary_terminal_component_kind_match") == ["true"]

    assert objects("source_id_section_terminal") == ["190l"]
    assert objects("source_id_section_primary_equals_terminal") == ["true"]
    assert objects("source_id_section_primary_terminal_pair") == ["190l|190l"]
    assert objects("source_id_section_primary_number") == ["190"]
    assert objects("source_id_section_primary_number_digit_count") == ["3"]
    assert objects("source_id_section_terminal_number") == ["190"]
    assert objects("source_id_section_terminal_number_digit_count") == ["3"]
    assert objects("source_id_section_primary_suffix") == ["l"]
    assert objects("source_id_section_suffix_char_count") == ["1"]
    assert objects("source_id_section_primary_suffix_char_count") == ["1"]
    assert objects("source_id_section_terminal_suffix_char_count") == ["1"]
    assert objects("source_id_section_suffix_profile") == ["single"]
    assert objects("source_id_section_primary_suffix_profile") == ["single"]
    assert objects("source_id_section_terminal_suffix_profile") == ["single"]
    assert objects("source_id_section_has_suffix") == ["true"]
    assert objects("source_id_section_primary_has_suffix") == ["true"]
    assert objects("source_id_section_terminal_has_suffix") == ["true"]
    assert objects("source_id_section_terminal_suffix") == ["l"]
    assert objects("source_id_section_primary_component_kind") == ["alphanumeric"]
    assert objects("source_id_section_terminal_component_kind") == ["alphanumeric"]
    assert objects("source_id_section_primary_terminal_component_signature_pair") == [
        "N3A1|N3A1"
    ]
    assert objects("source_id_section_primary_terminal_component_signature_match") == [
        "true"
    ]
    assert objects("source_id_section_primary_terminal_component_kind_pair") == [
        "alphanumeric|alphanumeric"
    ]
    assert objects("source_id_section_primary_terminal_component_kind_match") == ["true"]


def test_decode_modal_ir_document_emits_roman_suffix_slots() -> None:
    decoded = decode_modal_ir_document(_roman_suffix_hyphen_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_suffix_kind"] == ["roman"]
    assert slot_map["citation_section_suffix_kind_positioned"] == ["1:roman"]
    assert slot_map["citation_section_primary_suffix_kind"] == ["roman"]
    assert "citation_section_terminal_suffix_kind" not in slot_map
    assert slot_map["citation_section_has_roman_suffix"] == ["true"]
    assert slot_map["citation_section_primary_suffix_is_roman"] == ["true"]
    assert slot_map["citation_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["citation_section_roman_suffix_component_count"] == ["1"]

    assert slot_map["source_id_section_suffix_kind"] == ["roman"]
    assert slot_map["source_id_section_suffix_kind_positioned"] == ["1:roman"]
    assert slot_map["source_id_section_primary_suffix_kind"] == ["roman"]
    assert "source_id_section_terminal_suffix_kind" not in slot_map
    assert slot_map["source_id_section_has_roman_suffix"] == ["true"]
    assert slot_map["source_id_section_primary_suffix_is_roman"] == ["true"]
    assert slot_map["source_id_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["source_id_section_roman_suffix_component_count"] == ["1"]


def test_modal_ir_to_flogic_triples_emits_roman_suffix_slots() -> None:
    triples = modal_ir_to_flogic_triples(_roman_suffix_hyphen_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_suffix_kind") == ["roman"]
    assert objects("citation_section_suffix_kind_positioned") == ["1:roman"]
    assert objects("citation_section_primary_suffix_kind") == ["roman"]
    assert objects("citation_section_terminal_suffix_kind") == []
    assert objects("citation_section_has_roman_suffix") == ["true"]
    assert objects("citation_section_primary_suffix_is_roman") == ["true"]
    assert objects("citation_section_terminal_suffix_is_roman") == ["false"]
    assert objects("citation_section_roman_suffix_component_count") == ["1"]

    assert objects("source_id_section_suffix_kind") == ["roman"]
    assert objects("source_id_section_suffix_kind_positioned") == ["1:roman"]
    assert objects("source_id_section_primary_suffix_kind") == ["roman"]
    assert objects("source_id_section_terminal_suffix_kind") == []
    assert objects("source_id_section_has_roman_suffix") == ["true"]
    assert objects("source_id_section_primary_suffix_is_roman") == ["true"]
    assert objects("source_id_section_terminal_suffix_is_roman") == ["false"]
    assert objects("source_id_section_roman_suffix_component_count") == ["1"]


def test_decode_modal_ir_document_emits_section_component_signature_slots() -> None:
    mixed_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_sample_document())
    )
    assert mixed_slot_map["citation_section_component_signature"] == ["N3A3", "N1"]
    assert mixed_slot_map["citation_section_component_signature_positioned"] == [
        "1:N3A3",
        "2:N1",
    ]
    assert mixed_slot_map["citation_section_primary_component_signature"] == ["N3A3"]
    assert mixed_slot_map["citation_section_terminal_component_signature"] == ["N1"]
    assert mixed_slot_map["citation_section_signature"] == ["N3A3-N1"]
    assert mixed_slot_map["citation_section_primary_terminal_component_signature_pair"] == [
        "N3A3|N1"
    ]
    assert mixed_slot_map["citation_section_primary_terminal_component_signature_match"] == [
        "false"
    ]
    assert mixed_slot_map["citation_section_primary_terminal_component_kind_pair"] == [
        "alphanumeric|numeric"
    ]
    assert mixed_slot_map["citation_section_primary_terminal_component_kind_match"] == [
        "false"
    ]
    assert mixed_slot_map["source_id_section_signature"] == ["N3A3-N1"]
    assert mixed_slot_map["source_id_section_primary_terminal_component_signature_pair"] == [
        "N3A3|N1"
    ]
    assert mixed_slot_map["source_id_section_primary_terminal_component_signature_match"] == [
        "false"
    ]
    assert mixed_slot_map["source_id_section_primary_terminal_component_kind_pair"] == [
        "alphanumeric|numeric"
    ]
    assert mixed_slot_map["source_id_section_primary_terminal_component_kind_match"] == [
        "false"
    ]

    roman_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_roman_suffix_hyphen_sample_document())
    )
    assert roman_slot_map["citation_section_signature"] == ["N3R3-N1"]
    assert roman_slot_map["source_id_section_signature"] == ["N3R3-N1"]

    todo_cluster_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_compound_alpha_suffix_hyphen_sample_document())
    )
    assert todo_cluster_slot_map["citation_section_signature"] == ["N3A3-N1"]
    assert todo_cluster_slot_map["source_id_section_signature"] == ["N3A3-N1"]

    numeric_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_trailing_punct_sample_document())
    )
    assert numeric_slot_map["citation_section_signature"] == ["N5"]
    assert numeric_slot_map["citation_section_primary_terminal_component_signature_pair"] == [
        "N5|N5"
    ]
    assert numeric_slot_map["citation_section_primary_terminal_component_signature_match"] == [
        "true"
    ]
    assert numeric_slot_map["citation_section_primary_terminal_component_kind_pair"] == [
        "numeric|numeric"
    ]
    assert numeric_slot_map["citation_section_primary_terminal_component_kind_match"] == [
        "true"
    ]
    assert numeric_slot_map["source_id_section_signature"] == ["N5"]
    assert numeric_slot_map["source_id_section_primary_terminal_component_signature_pair"] == [
        "N5|N5"
    ]
    assert numeric_slot_map["source_id_section_primary_terminal_component_signature_match"] == [
        "true"
    ]
    assert numeric_slot_map["source_id_section_primary_terminal_component_kind_pair"] == [
        "numeric|numeric"
    ]
    assert numeric_slot_map["source_id_section_primary_terminal_component_kind_match"] == [
        "true"
    ]


def test_modal_ir_to_flogic_triples_emits_section_component_signature_slots() -> None:
    mixed_triples = modal_ir_to_flogic_triples(_sample_document())
    roman_triples = modal_ir_to_flogic_triples(_roman_suffix_hyphen_sample_document())
    todo_cluster_triples = modal_ir_to_flogic_triples(
        _compound_alpha_suffix_hyphen_sample_document()
    )
    numeric_triples = modal_ir_to_flogic_triples(_trailing_punct_sample_document())

    def objects(triples: list[dict[str, str]], predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects(mixed_triples, "citation_section_component_signature") == ["N3A3", "N1"]
    assert objects(
        mixed_triples,
        "citation_section_component_signature_positioned",
    ) == ["1:N3A3", "2:N1"]
    assert objects(mixed_triples, "citation_section_primary_component_signature") == [
        "N3A3"
    ]
    assert objects(mixed_triples, "citation_section_terminal_component_signature") == [
        "N1"
    ]
    assert objects(mixed_triples, "citation_section_signature") == ["N3A3-N1"]
    assert objects(
        mixed_triples,
        "citation_section_primary_terminal_component_signature_pair",
    ) == ["N3A3|N1"]
    assert objects(
        mixed_triples,
        "citation_section_primary_terminal_component_signature_match",
    ) == ["false"]
    assert objects(
        mixed_triples,
        "citation_section_primary_terminal_component_kind_pair",
    ) == ["alphanumeric|numeric"]
    assert objects(
        mixed_triples,
        "citation_section_primary_terminal_component_kind_match",
    ) == ["false"]
    assert objects(mixed_triples, "source_id_section_signature") == ["N3A3-N1"]
    assert objects(
        mixed_triples,
        "source_id_section_primary_terminal_component_signature_pair",
    ) == ["N3A3|N1"]
    assert objects(
        mixed_triples,
        "source_id_section_primary_terminal_component_signature_match",
    ) == ["false"]
    assert objects(
        mixed_triples,
        "source_id_section_primary_terminal_component_kind_pair",
    ) == ["alphanumeric|numeric"]
    assert objects(
        mixed_triples,
        "source_id_section_primary_terminal_component_kind_match",
    ) == ["false"]

    assert objects(roman_triples, "citation_section_signature") == ["N3R3-N1"]
    assert objects(roman_triples, "source_id_section_signature") == ["N3R3-N1"]

    assert objects(todo_cluster_triples, "citation_section_signature") == ["N3A3-N1"]
    assert objects(todo_cluster_triples, "source_id_section_signature") == ["N3A3-N1"]

    assert objects(numeric_triples, "citation_section_signature") == ["N5"]
    assert objects(
        numeric_triples,
        "citation_section_primary_terminal_component_signature_pair",
    ) == ["N5|N5"]
    assert objects(
        numeric_triples,
        "citation_section_primary_terminal_component_signature_match",
    ) == ["true"]
    assert objects(
        numeric_triples,
        "citation_section_primary_terminal_component_kind_pair",
    ) == ["numeric|numeric"]
    assert objects(
        numeric_triples,
        "citation_section_primary_terminal_component_kind_match",
    ) == ["true"]
    assert objects(numeric_triples, "source_id_section_signature") == ["N5"]
    assert objects(
        numeric_triples,
        "source_id_section_primary_terminal_component_signature_pair",
    ) == ["N5|N5"]
    assert objects(
        numeric_triples,
        "source_id_section_primary_terminal_component_signature_match",
    ) == ["true"]
    assert objects(
        numeric_triples,
        "source_id_section_primary_terminal_component_kind_pair",
    ) == ["numeric|numeric"]
    assert objects(
        numeric_triples,
        "source_id_section_primary_terminal_component_kind_match",
    ) == ["true"]


def test_decode_modal_ir_document_emits_suffix_alpha_signature_slots() -> None:
    sample_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_sample_document())
    )
    assert sample_slot_map["citation_section_suffix_initial"] == ["b"]
    assert sample_slot_map["citation_section_suffix_terminal"] == ["b"]
    assert sample_slot_map["citation_section_suffix_initial_ordinal"] == ["2"]
    assert sample_slot_map["citation_section_suffix_terminal_ordinal"] == ["2"]
    assert sample_slot_map["citation_section_suffix_vowel_count"] == ["0"]
    assert sample_slot_map["citation_section_suffix_consonant_count"] == ["3"]
    assert sample_slot_map["citation_section_suffix_has_vowel"] == ["false"]
    assert sample_slot_map["citation_section_suffix_has_consonant"] == ["true"]
    assert sample_slot_map["citation_section_suffix_unique_char_count"] == ["1"]
    assert sample_slot_map["citation_section_primary_suffix_initial"] == ["b"]
    assert sample_slot_map["citation_section_primary_suffix_initial_ordinal"] == ["2"]
    assert sample_slot_map["citation_section_primary_suffix_has_consonant"] == ["true"]

    assert sample_slot_map["source_id_section_suffix_initial"] == ["b"]
    assert sample_slot_map["source_id_section_suffix_terminal"] == ["b"]
    assert sample_slot_map["source_id_section_suffix_initial_ordinal"] == ["2"]
    assert sample_slot_map["source_id_section_suffix_terminal_ordinal"] == ["2"]
    assert sample_slot_map["source_id_section_suffix_vowel_count"] == ["0"]
    assert sample_slot_map["source_id_section_suffix_consonant_count"] == ["3"]
    assert sample_slot_map["source_id_section_suffix_has_vowel"] == ["false"]
    assert sample_slot_map["source_id_section_suffix_has_consonant"] == ["true"]
    assert sample_slot_map["source_id_section_suffix_unique_char_count"] == ["1"]
    assert sample_slot_map["source_id_section_primary_suffix_initial"] == ["b"]
    assert sample_slot_map["source_id_section_primary_suffix_initial_ordinal"] == ["2"]
    assert sample_slot_map["source_id_section_primary_suffix_has_consonant"] == ["true"]

    range_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_range_sample_document())
    )
    assert range_slot_map["citation_section_suffix_initial_positioned"] == [
        "1:a",
        "2:c",
    ]
    assert range_slot_map["citation_section_suffix_initial_ordinal_positioned"] == [
        "1:1",
        "2:3",
    ]
    assert range_slot_map["citation_section_suffix_has_vowel_positioned"] == [
        "1:true",
        "2:false",
    ]
    assert range_slot_map["citation_section_suffix_has_consonant_positioned"] == [
        "1:false",
        "2:true",
    ]
    assert range_slot_map["citation_section_primary_suffix_has_vowel"] == ["true"]
    assert range_slot_map["citation_section_terminal_suffix_has_vowel"] == ["false"]

    assert range_slot_map["source_id_section_suffix_initial_positioned"] == [
        "1:a",
        "2:c",
    ]
    assert range_slot_map["source_id_section_suffix_initial_ordinal_positioned"] == [
        "1:1",
        "2:3",
    ]
    assert range_slot_map["source_id_section_suffix_has_vowel_positioned"] == [
        "1:true",
        "2:false",
    ]
    assert range_slot_map["source_id_section_suffix_has_consonant_positioned"] == [
        "1:false",
        "2:true",
    ]
    assert range_slot_map["source_id_section_primary_suffix_has_vowel"] == ["true"]
    assert range_slot_map["source_id_section_terminal_suffix_has_vowel"] == ["false"]


def test_modal_ir_to_flogic_triples_emits_suffix_alpha_signature_slots() -> None:
    sample_triples = modal_ir_to_flogic_triples(_sample_document())
    range_triples = modal_ir_to_flogic_triples(_range_sample_document())

    def objects(triples: list[dict[str, str]], predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects(sample_triples, "citation_section_suffix_initial") == ["b"]
    assert objects(sample_triples, "citation_section_suffix_terminal") == ["b"]
    assert objects(sample_triples, "citation_section_suffix_initial_ordinal") == ["2"]
    assert objects(sample_triples, "citation_section_suffix_terminal_ordinal") == ["2"]
    assert objects(sample_triples, "citation_section_suffix_vowel_count") == ["0"]
    assert objects(sample_triples, "citation_section_suffix_consonant_count") == ["3"]
    assert objects(sample_triples, "citation_section_suffix_has_vowel") == ["false"]
    assert objects(sample_triples, "citation_section_suffix_has_consonant") == ["true"]
    assert objects(sample_triples, "citation_section_suffix_unique_char_count") == ["1"]
    assert objects(sample_triples, "citation_section_primary_suffix_initial") == ["b"]
    assert objects(sample_triples, "citation_section_primary_suffix_initial_ordinal") == ["2"]
    assert objects(sample_triples, "citation_section_primary_suffix_has_consonant") == [
        "true"
    ]

    assert objects(sample_triples, "source_id_section_suffix_initial") == ["b"]
    assert objects(sample_triples, "source_id_section_suffix_terminal") == ["b"]
    assert objects(sample_triples, "source_id_section_suffix_initial_ordinal") == ["2"]
    assert objects(sample_triples, "source_id_section_suffix_terminal_ordinal") == ["2"]
    assert objects(sample_triples, "source_id_section_suffix_vowel_count") == ["0"]
    assert objects(sample_triples, "source_id_section_suffix_consonant_count") == ["3"]
    assert objects(sample_triples, "source_id_section_suffix_has_vowel") == ["false"]
    assert objects(sample_triples, "source_id_section_suffix_has_consonant") == ["true"]
    assert objects(sample_triples, "source_id_section_suffix_unique_char_count") == ["1"]
    assert objects(sample_triples, "source_id_section_primary_suffix_initial") == ["b"]
    assert objects(sample_triples, "source_id_section_primary_suffix_initial_ordinal") == [
        "2"
    ]
    assert objects(
        sample_triples,
        "source_id_section_primary_suffix_has_consonant",
    ) == ["true"]

    assert objects(range_triples, "citation_section_suffix_initial_positioned") == [
        "1:a",
        "2:c",
    ]
    assert objects(
        range_triples,
        "citation_section_suffix_initial_ordinal_positioned",
    ) == ["1:1", "2:3"]
    assert objects(range_triples, "citation_section_suffix_has_vowel_positioned") == [
        "1:true",
        "2:false",
    ]
    assert objects(
        range_triples,
        "citation_section_suffix_has_consonant_positioned",
    ) == ["1:false", "2:true"]
    assert objects(range_triples, "citation_section_primary_suffix_has_vowel") == ["true"]
    assert objects(range_triples, "citation_section_terminal_suffix_has_vowel") == [
        "false"
    ]

    assert objects(range_triples, "source_id_section_suffix_initial_positioned") == [
        "1:a",
        "2:c",
    ]
    assert objects(
        range_triples,
        "source_id_section_suffix_initial_ordinal_positioned",
    ) == ["1:1", "2:3"]
    assert objects(range_triples, "source_id_section_suffix_has_vowel_positioned") == [
        "1:true",
        "2:false",
    ]
    assert objects(
        range_triples,
        "source_id_section_suffix_has_consonant_positioned",
    ) == ["1:false", "2:true"]
    assert objects(range_triples, "source_id_section_primary_suffix_has_vowel") == [
        "true"
    ]
    assert objects(range_triples, "source_id_section_terminal_suffix_has_vowel") == [
        "false"
    ]


def test_decode_modal_ir_document_does_not_misclassify_noncanonical_roman_suffix() -> None:
    decoded = decode_modal_ir_document(_noncanonical_romanlike_suffix_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_suffix_kind"] == ["alpha"]
    assert slot_map["citation_section_primary_suffix_kind"] == ["alpha"]
    assert slot_map["citation_section_terminal_suffix_kind"] == ["alpha"]
    assert slot_map["citation_section_has_roman_suffix"] == ["false"]
    assert slot_map["citation_section_primary_suffix_is_roman"] == ["false"]
    assert slot_map["citation_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["citation_section_roman_suffix_component_count"] == ["0"]

    assert slot_map["source_id_section_suffix_kind"] == ["alpha"]
    assert slot_map["source_id_section_primary_suffix_kind"] == ["alpha"]
    assert slot_map["source_id_section_terminal_suffix_kind"] == ["alpha"]
    assert slot_map["source_id_section_has_roman_suffix"] == ["false"]
    assert slot_map["source_id_section_primary_suffix_is_roman"] == ["false"]
    assert slot_map["source_id_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["source_id_section_roman_suffix_component_count"] == ["0"]


def test_modal_ir_to_flogic_triples_does_not_misclassify_noncanonical_roman_suffix() -> None:
    triples = modal_ir_to_flogic_triples(_noncanonical_romanlike_suffix_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_suffix_kind") == ["alpha"]
    assert objects("citation_section_primary_suffix_kind") == ["alpha"]
    assert objects("citation_section_terminal_suffix_kind") == ["alpha"]
    assert objects("citation_section_has_roman_suffix") == ["false"]
    assert objects("citation_section_primary_suffix_is_roman") == ["false"]
    assert objects("citation_section_terminal_suffix_is_roman") == ["false"]
    assert objects("citation_section_roman_suffix_component_count") == ["0"]

    assert objects("source_id_section_suffix_kind") == ["alpha"]
    assert objects("source_id_section_primary_suffix_kind") == ["alpha"]
    assert objects("source_id_section_terminal_suffix_kind") == ["alpha"]
    assert objects("source_id_section_has_roman_suffix") == ["false"]
    assert objects("source_id_section_primary_suffix_is_roman") == ["false"]
    assert objects("source_id_section_terminal_suffix_is_roman") == ["false"]
    assert objects("source_id_section_roman_suffix_component_count") == ["0"]


def test_decode_modal_ir_document_treats_repeat_roman_tokens_as_alpha_suffixes() -> None:
    decoded = decode_modal_ir_document(_repeat_roman_token_suffix_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_suffix_kind"] == ["alpha"]
    assert slot_map["citation_section_primary_suffix_kind"] == ["alpha"]
    assert slot_map["citation_section_terminal_suffix_kind"] == ["alpha"]
    assert slot_map["citation_section_has_roman_suffix"] == ["false"]
    assert slot_map["citation_section_primary_suffix_is_roman"] == ["false"]
    assert slot_map["citation_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["citation_section_roman_suffix_component_count"] == ["0"]

    assert slot_map["source_id_section_suffix_kind"] == ["alpha"]
    assert slot_map["source_id_section_primary_suffix_kind"] == ["alpha"]
    assert slot_map["source_id_section_terminal_suffix_kind"] == ["alpha"]
    assert slot_map["source_id_section_has_roman_suffix"] == ["false"]
    assert slot_map["source_id_section_primary_suffix_is_roman"] == ["false"]
    assert slot_map["source_id_section_terminal_suffix_is_roman"] == ["false"]
    assert slot_map["source_id_section_roman_suffix_component_count"] == ["0"]


def test_modal_ir_to_flogic_triples_treats_repeat_roman_tokens_as_alpha_suffixes() -> None:
    triples = modal_ir_to_flogic_triples(_repeat_roman_token_suffix_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_suffix_kind") == ["alpha"]
    assert objects("citation_section_primary_suffix_kind") == ["alpha"]
    assert objects("citation_section_terminal_suffix_kind") == ["alpha"]
    assert objects("citation_section_has_roman_suffix") == ["false"]
    assert objects("citation_section_primary_suffix_is_roman") == ["false"]
    assert objects("citation_section_terminal_suffix_is_roman") == ["false"]
    assert objects("citation_section_roman_suffix_component_count") == ["0"]

    assert objects("source_id_section_suffix_kind") == ["alpha"]
    assert objects("source_id_section_primary_suffix_kind") == ["alpha"]
    assert objects("source_id_section_terminal_suffix_kind") == ["alpha"]
    assert objects("source_id_section_has_roman_suffix") == ["false"]
    assert objects("source_id_section_primary_suffix_is_roman") == ["false"]
    assert objects("source_id_section_terminal_suffix_is_roman") == ["false"]
    assert objects("source_id_section_roman_suffix_component_count") == ["0"]


def test_decode_modal_ir_document_emits_section_range_slots() -> None:
    decoded = decode_modal_ir_document(_range_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_terminal"] == ["228c"]
    assert slot_map["citation_section_primary_equals_terminal"] == ["false"]
    assert slot_map["citation_section_primary_terminal_pair"] == ["228a|228c"]
    assert slot_map["citation_section_range"] == ["228a to 228c"]
    assert slot_map["citation_section_range_start"] == ["228a"]
    assert slot_map["citation_section_range_end"] == ["228c"]
    assert slot_map["citation_section_range_connector"] == ["to"]
    assert slot_map["citation_section_is_range"] == ["true"]
    assert slot_map["citation_section_range_has_suffix"] == ["true"]
    assert slot_map["citation_section_range_number_relation"] == ["equal"]
    assert slot_map["citation_section_range_number_span"] == ["0"]
    assert slot_map["citation_section_component_positioned"] == ["1:228a", "2:228c"]
    assert slot_map["citation_section_number_positioned"] == ["1:228", "2:228"]
    assert slot_map["citation_section_number_digit_count"] == ["3"]
    assert slot_map["citation_section_number_digit_count_positioned"] == ["1:3", "2:3"]
    assert slot_map["citation_section_primary_number_digit_count"] == ["3"]
    assert slot_map["citation_section_terminal_number_digit_count"] == ["3"]
    assert slot_map["citation_section_suffix_positioned"] == ["1:a", "2:c"]
    assert slot_map["citation_section_suffix_char_count"] == ["1"]
    assert slot_map["citation_section_suffix_char_count_positioned"] == ["1:1", "2:1"]
    assert slot_map["citation_section_suffix_profile"] == ["single"]
    assert slot_map["citation_section_suffix_profile_positioned"] == [
        "1:single",
        "2:single",
    ]
    assert slot_map["citation_section_has_suffix"] == ["true"]
    assert slot_map["citation_section_primary_has_suffix"] == ["true"]
    assert slot_map["citation_section_terminal_has_suffix"] == ["true"]
    assert slot_map["citation_section_component_kind_positioned"] == [
        "1:alphanumeric",
        "2:alphanumeric",
    ]
    assert slot_map["citation_section_has_delimiter"] == ["false"]
    assert slot_map["citation_section_delimiter_count"] == ["0"]
    assert slot_map["citation_title_section_key"] == ["45:228a to 228c"]
    assert slot_map["citation_title_section_key_normalized"] == ["45:228a to 228c"]

    assert slot_map["source_id_section_terminal"] == ["228c"]
    assert slot_map["source_id_section_primary_equals_terminal"] == ["false"]
    assert slot_map["source_id_section_primary_terminal_pair"] == ["228a|228c"]
    assert slot_map["source_id_section_range"] == ["228a to 228c"]
    assert slot_map["source_id_section_range_start"] == ["228a"]
    assert slot_map["source_id_section_range_end"] == ["228c"]
    assert slot_map["source_id_section_range_connector"] == ["to"]
    assert slot_map["source_id_section_is_range"] == ["true"]
    assert slot_map["source_id_section_range_has_suffix"] == ["true"]
    assert slot_map["source_id_section_range_number_relation"] == ["equal"]
    assert slot_map["source_id_section_range_number_span"] == ["0"]
    assert slot_map["source_id_section_component_positioned"] == ["1:228a", "2:228c"]
    assert slot_map["source_id_section_number_positioned"] == ["1:228", "2:228"]
    assert slot_map["source_id_section_number_digit_count"] == ["3"]
    assert slot_map["source_id_section_number_digit_count_positioned"] == ["1:3", "2:3"]
    assert slot_map["source_id_section_primary_number_digit_count"] == ["3"]
    assert slot_map["source_id_section_terminal_number_digit_count"] == ["3"]
    assert slot_map["source_id_section_suffix_positioned"] == ["1:a", "2:c"]
    assert slot_map["source_id_section_suffix_char_count"] == ["1"]
    assert slot_map["source_id_section_suffix_char_count_positioned"] == ["1:1", "2:1"]
    assert slot_map["source_id_section_suffix_profile"] == ["single"]
    assert slot_map["source_id_section_suffix_profile_positioned"] == [
        "1:single",
        "2:single",
    ]
    assert slot_map["source_id_section_has_suffix"] == ["true"]
    assert slot_map["source_id_section_primary_has_suffix"] == ["true"]
    assert slot_map["source_id_section_terminal_has_suffix"] == ["true"]
    assert slot_map["source_id_section_component_kind_positioned"] == [
        "1:alphanumeric",
        "2:alphanumeric",
    ]
    assert slot_map["source_id_section_has_delimiter"] == ["false"]
    assert slot_map["source_id_section_delimiter_count"] == ["0"]
    assert slot_map["source_id_title_section_key"] == ["45:228a to 228c"]
    assert slot_map["source_id_title_section_key_normalized"] == ["45:228a to 228c"]


def test_modal_ir_to_flogic_triples_emits_section_range_slots() -> None:
    triples = modal_ir_to_flogic_triples(_range_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_terminal") == ["228c"]
    assert objects("citation_section_primary_equals_terminal") == ["false"]
    assert objects("citation_section_primary_terminal_pair") == ["228a|228c"]
    assert objects("citation_section_range") == ["228a to 228c"]
    assert objects("citation_section_range_start") == ["228a"]
    assert objects("citation_section_range_end") == ["228c"]
    assert objects("citation_section_range_connector") == ["to"]
    assert objects("citation_section_is_range") == ["true"]
    assert objects("citation_section_range_has_suffix") == ["true"]
    assert objects("citation_section_range_number_relation") == ["equal"]
    assert objects("citation_section_range_number_span") == ["0"]
    assert objects("citation_section_component_positioned") == ["1:228a", "2:228c"]
    assert objects("citation_section_number_positioned") == ["1:228", "2:228"]
    assert objects("citation_section_number_digit_count") == ["3"]
    assert objects("citation_section_number_digit_count_positioned") == ["1:3", "2:3"]
    assert objects("citation_section_primary_number_digit_count") == ["3"]
    assert objects("citation_section_terminal_number_digit_count") == ["3"]
    assert objects("citation_section_suffix_positioned") == ["1:a", "2:c"]
    assert objects("citation_section_suffix_char_count") == ["1"]
    assert objects("citation_section_suffix_char_count_positioned") == ["1:1", "2:1"]
    assert objects("citation_section_suffix_profile") == ["single"]
    assert objects("citation_section_suffix_profile_positioned") == [
        "1:single",
        "2:single",
    ]
    assert objects("citation_section_has_suffix") == ["true"]
    assert objects("citation_section_primary_has_suffix") == ["true"]
    assert objects("citation_section_terminal_has_suffix") == ["true"]
    assert objects("citation_section_component_kind_positioned") == [
        "1:alphanumeric",
        "2:alphanumeric",
    ]
    assert objects("citation_section_has_delimiter") == ["false"]
    assert objects("citation_section_delimiter_count") == ["0"]
    assert objects("citation_title_section_key") == ["45:228a to 228c"]
    assert objects("citation_title_section_key_normalized") == ["45:228a to 228c"]

    assert objects("source_id_section_terminal") == ["228c"]
    assert objects("source_id_section_primary_equals_terminal") == ["false"]
    assert objects("source_id_section_primary_terminal_pair") == ["228a|228c"]
    assert objects("source_id_section_range") == ["228a to 228c"]
    assert objects("source_id_section_range_start") == ["228a"]
    assert objects("source_id_section_range_end") == ["228c"]
    assert objects("source_id_section_range_connector") == ["to"]
    assert objects("source_id_section_is_range") == ["true"]
    assert objects("source_id_section_range_has_suffix") == ["true"]
    assert objects("source_id_section_range_number_relation") == ["equal"]
    assert objects("source_id_section_range_number_span") == ["0"]
    assert objects("source_id_section_component_positioned") == ["1:228a", "2:228c"]
    assert objects("source_id_section_number_positioned") == ["1:228", "2:228"]
    assert objects("source_id_section_number_digit_count") == ["3"]
    assert objects("source_id_section_number_digit_count_positioned") == ["1:3", "2:3"]
    assert objects("source_id_section_primary_number_digit_count") == ["3"]
    assert objects("source_id_section_terminal_number_digit_count") == ["3"]
    assert objects("source_id_section_suffix_positioned") == ["1:a", "2:c"]
    assert objects("source_id_section_suffix_char_count") == ["1"]
    assert objects("source_id_section_suffix_char_count_positioned") == ["1:1", "2:1"]
    assert objects("source_id_section_suffix_profile") == ["single"]
    assert objects("source_id_section_suffix_profile_positioned") == [
        "1:single",
        "2:single",
    ]
    assert objects("source_id_section_has_suffix") == ["true"]
    assert objects("source_id_section_primary_has_suffix") == ["true"]
    assert objects("source_id_section_terminal_has_suffix") == ["true"]
    assert objects("source_id_section_component_kind_positioned") == [
        "1:alphanumeric",
        "2:alphanumeric",
    ]
    assert objects("source_id_section_has_delimiter") == ["false"]
    assert objects("source_id_section_delimiter_count") == ["0"]
    assert objects("source_id_title_section_key") == ["45:228a to 228c"]
    assert objects("source_id_title_section_key_normalized") == ["45:228a to 228c"]


def test_decode_modal_ir_document_emits_suffix_relation_slots() -> None:
    range_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_range_sample_document())
    )
    long_alpha_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_long_alpha_range_sample_document())
    )

    assert range_slot_map["citation_section_primary_terminal_suffix_pair"] == ["a|c"]
    assert range_slot_map["citation_section_primary_terminal_suffix_match"] == ["false"]
    assert range_slot_map["citation_section_primary_terminal_suffix_presence_match"] == [
        "true"
    ]
    assert range_slot_map["citation_section_primary_terminal_suffix_length_relation"] == [
        "equal"
    ]
    assert range_slot_map["citation_section_primary_terminal_suffix_length_span"] == ["0"]
    assert range_slot_map["citation_section_primary_terminal_suffix_alpha_relation"] == [
        "ascending"
    ]
    assert range_slot_map["citation_section_primary_terminal_suffix_alpha_span"] == ["2"]
    assert range_slot_map["citation_section_range_suffix_alpha_relation"] == [
        "ascending"
    ]
    assert range_slot_map["citation_section_range_suffix_alpha_span"] == ["2"]

    assert range_slot_map["source_id_section_primary_terminal_suffix_pair"] == ["a|c"]
    assert range_slot_map["source_id_section_primary_terminal_suffix_match"] == ["false"]
    assert range_slot_map["source_id_section_primary_terminal_suffix_presence_match"] == [
        "true"
    ]
    assert range_slot_map["source_id_section_primary_terminal_suffix_length_relation"] == [
        "equal"
    ]
    assert range_slot_map["source_id_section_primary_terminal_suffix_length_span"] == ["0"]
    assert range_slot_map["source_id_section_primary_terminal_suffix_alpha_relation"] == [
        "ascending"
    ]
    assert range_slot_map["source_id_section_primary_terminal_suffix_alpha_span"] == ["2"]
    assert range_slot_map["source_id_section_range_suffix_alpha_relation"] == [
        "ascending"
    ]
    assert range_slot_map["source_id_section_range_suffix_alpha_span"] == ["2"]

    assert long_alpha_slot_map["citation_section_primary_terminal_suffix_pair"] == [
        "tttt|yyyy"
    ]
    assert long_alpha_slot_map["citation_section_primary_terminal_suffix_match"] == [
        "false"
    ]
    assert long_alpha_slot_map["citation_section_primary_terminal_suffix_presence_match"] == [
        "true"
    ]
    assert (
        long_alpha_slot_map["citation_section_primary_terminal_suffix_length_relation"]
        == ["equal"]
    )
    assert long_alpha_slot_map["citation_section_primary_terminal_suffix_length_span"] == [
        "0"
    ]
    assert long_alpha_slot_map["citation_section_primary_terminal_suffix_alpha_relation"] == [
        "ascending"
    ]
    assert long_alpha_slot_map["citation_section_primary_terminal_suffix_alpha_span"] == [
        "91395"
    ]
    assert long_alpha_slot_map["citation_section_range_suffix_alpha_relation"] == [
        "ascending"
    ]
    assert long_alpha_slot_map["citation_section_range_suffix_alpha_span"] == ["91395"]

    assert long_alpha_slot_map["source_id_section_primary_terminal_suffix_pair"] == [
        "tttt|yyyy"
    ]
    assert long_alpha_slot_map["source_id_section_primary_terminal_suffix_match"] == [
        "false"
    ]
    assert long_alpha_slot_map["source_id_section_primary_terminal_suffix_presence_match"] == [
        "true"
    ]
    assert (
        long_alpha_slot_map["source_id_section_primary_terminal_suffix_length_relation"]
        == ["equal"]
    )
    assert long_alpha_slot_map["source_id_section_primary_terminal_suffix_length_span"] == [
        "0"
    ]
    assert long_alpha_slot_map["source_id_section_primary_terminal_suffix_alpha_relation"] == [
        "ascending"
    ]
    assert long_alpha_slot_map["source_id_section_primary_terminal_suffix_alpha_span"] == [
        "91395"
    ]
    assert long_alpha_slot_map["source_id_section_range_suffix_alpha_relation"] == [
        "ascending"
    ]
    assert long_alpha_slot_map["source_id_section_range_suffix_alpha_span"] == ["91395"]


def test_modal_ir_to_flogic_triples_emits_suffix_relation_slots() -> None:
    range_triples = modal_ir_to_flogic_triples(_range_sample_document())
    long_alpha_triples = modal_ir_to_flogic_triples(_long_alpha_range_sample_document())

    def objects(triples: list[dict[str, str]], predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects(range_triples, "citation_section_primary_terminal_suffix_pair") == [
        "a|c"
    ]
    assert objects(range_triples, "citation_section_primary_terminal_suffix_match") == [
        "false"
    ]
    assert objects(
        range_triples,
        "citation_section_primary_terminal_suffix_presence_match",
    ) == ["true"]
    assert objects(
        range_triples,
        "citation_section_primary_terminal_suffix_length_relation",
    ) == ["equal"]
    assert objects(
        range_triples,
        "citation_section_primary_terminal_suffix_length_span",
    ) == ["0"]
    assert objects(
        range_triples,
        "citation_section_primary_terminal_suffix_alpha_relation",
    ) == ["ascending"]
    assert objects(
        range_triples,
        "citation_section_primary_terminal_suffix_alpha_span",
    ) == ["2"]
    assert objects(range_triples, "citation_section_range_suffix_alpha_relation") == [
        "ascending"
    ]
    assert objects(range_triples, "citation_section_range_suffix_alpha_span") == ["2"]

    assert objects(range_triples, "source_id_section_primary_terminal_suffix_pair") == [
        "a|c"
    ]
    assert objects(range_triples, "source_id_section_primary_terminal_suffix_match") == [
        "false"
    ]
    assert objects(
        range_triples,
        "source_id_section_primary_terminal_suffix_presence_match",
    ) == ["true"]
    assert objects(
        range_triples,
        "source_id_section_primary_terminal_suffix_length_relation",
    ) == ["equal"]
    assert objects(
        range_triples,
        "source_id_section_primary_terminal_suffix_length_span",
    ) == ["0"]
    assert objects(
        range_triples,
        "source_id_section_primary_terminal_suffix_alpha_relation",
    ) == ["ascending"]
    assert objects(
        range_triples,
        "source_id_section_primary_terminal_suffix_alpha_span",
    ) == ["2"]
    assert objects(range_triples, "source_id_section_range_suffix_alpha_relation") == [
        "ascending"
    ]
    assert objects(range_triples, "source_id_section_range_suffix_alpha_span") == ["2"]

    assert objects(
        long_alpha_triples,
        "citation_section_primary_terminal_suffix_pair",
    ) == ["tttt|yyyy"]
    assert objects(
        long_alpha_triples,
        "citation_section_primary_terminal_suffix_match",
    ) == ["false"]
    assert objects(
        long_alpha_triples,
        "citation_section_primary_terminal_suffix_presence_match",
    ) == ["true"]
    assert objects(
        long_alpha_triples,
        "citation_section_primary_terminal_suffix_length_relation",
    ) == ["equal"]
    assert objects(
        long_alpha_triples,
        "citation_section_primary_terminal_suffix_length_span",
    ) == ["0"]
    assert objects(
        long_alpha_triples,
        "citation_section_primary_terminal_suffix_alpha_relation",
    ) == ["ascending"]
    assert objects(
        long_alpha_triples,
        "citation_section_primary_terminal_suffix_alpha_span",
    ) == ["91395"]
    assert objects(
        long_alpha_triples,
        "citation_section_range_suffix_alpha_relation",
    ) == ["ascending"]
    assert objects(
        long_alpha_triples,
        "citation_section_range_suffix_alpha_span",
    ) == ["91395"]

    assert objects(
        long_alpha_triples,
        "source_id_section_primary_terminal_suffix_pair",
    ) == ["tttt|yyyy"]
    assert objects(
        long_alpha_triples,
        "source_id_section_primary_terminal_suffix_match",
    ) == ["false"]
    assert objects(
        long_alpha_triples,
        "source_id_section_primary_terminal_suffix_presence_match",
    ) == ["true"]
    assert objects(
        long_alpha_triples,
        "source_id_section_primary_terminal_suffix_length_relation",
    ) == ["equal"]
    assert objects(
        long_alpha_triples,
        "source_id_section_primary_terminal_suffix_length_span",
    ) == ["0"]
    assert objects(
        long_alpha_triples,
        "source_id_section_primary_terminal_suffix_alpha_relation",
    ) == ["ascending"]
    assert objects(
        long_alpha_triples,
        "source_id_section_primary_terminal_suffix_alpha_span",
    ) == ["91395"]
    assert objects(
        long_alpha_triples,
        "source_id_section_range_suffix_alpha_relation",
    ) == ["ascending"]
    assert objects(
        long_alpha_triples,
        "source_id_section_range_suffix_alpha_span",
    ) == ["91395"]


def test_decode_modal_ir_document_emits_numeric_section_range_relation_slots() -> None:
    decoded = decode_modal_ir_document(_numeric_range_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_range"] == ["1381 to 1398"]
    assert slot_map["citation_section_is_range"] == ["true"]
    assert slot_map["citation_section_range_has_suffix"] == ["false"]
    assert slot_map["citation_section_range_number_relation"] == ["ascending"]
    assert slot_map["citation_section_range_number_span"] == ["17"]
    assert slot_map["source_id_section_range"] == ["1381 to 1398"]
    assert slot_map["source_id_section_is_range"] == ["true"]
    assert slot_map["source_id_section_range_has_suffix"] == ["false"]
    assert slot_map["source_id_section_range_number_relation"] == ["ascending"]
    assert slot_map["source_id_section_range_number_span"] == ["17"]


def test_modal_ir_to_flogic_triples_emits_numeric_section_range_relation_slots() -> None:
    triples = modal_ir_to_flogic_triples(_numeric_range_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_range") == ["1381 to 1398"]
    assert objects("citation_section_is_range") == ["true"]
    assert objects("citation_section_range_has_suffix") == ["false"]
    assert objects("citation_section_range_number_relation") == ["ascending"]
    assert objects("citation_section_range_number_span") == ["17"]
    assert objects("source_id_section_range") == ["1381 to 1398"]
    assert objects("source_id_section_is_range") == ["true"]
    assert objects("source_id_section_range_has_suffix") == ["false"]
    assert objects("source_id_section_range_number_relation") == ["ascending"]
    assert objects("source_id_section_range_number_span") == ["17"]


def test_decode_modal_ir_document_emits_dot_delimiter_slots() -> None:
    decoded = decode_modal_ir_document(_dot_delimited_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_has_delimiter"] == ["true"]
    assert slot_map["citation_section_delimiter"] == ["dot"]
    assert slot_map["citation_section_delimiter_positioned"] == ["1:dot"]
    assert slot_map["citation_section_delimiter_token"] == ["."]
    assert slot_map["citation_section_delimiter_token_positioned"] == ["1:."]
    assert slot_map["citation_section_delimiter_count"] == ["1"]
    assert slot_map["citation_section_delimiter_char_count"] == ["1"]
    assert slot_map["citation_section_delimiter_char_count_positioned"] == ["1:1"]
    assert slot_map["citation_section_delimiter_pattern"] == ["dot"]
    assert slot_map["citation_section_delimiter_distinct_count"] == ["1"]

    assert slot_map["source_id_section_has_delimiter"] == ["true"]
    assert slot_map["source_id_section_delimiter"] == ["dot"]
    assert slot_map["source_id_section_delimiter_positioned"] == ["1:dot"]
    assert slot_map["source_id_section_delimiter_token"] == ["."]
    assert slot_map["source_id_section_delimiter_token_positioned"] == ["1:."]
    assert slot_map["source_id_section_delimiter_count"] == ["1"]
    assert slot_map["source_id_section_delimiter_char_count"] == ["1"]
    assert slot_map["source_id_section_delimiter_char_count_positioned"] == ["1:1"]
    assert slot_map["source_id_section_delimiter_pattern"] == ["dot"]
    assert slot_map["source_id_section_delimiter_distinct_count"] == ["1"]


def test_modal_ir_to_flogic_triples_emits_dot_delimiter_slots() -> None:
    triples = modal_ir_to_flogic_triples(_dot_delimited_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_has_delimiter") == ["true"]
    assert objects("citation_section_delimiter") == ["dot"]
    assert objects("citation_section_delimiter_positioned") == ["1:dot"]
    assert objects("citation_section_delimiter_token") == ["."]
    assert objects("citation_section_delimiter_token_positioned") == ["1:."]
    assert objects("citation_section_delimiter_count") == ["1"]
    assert objects("citation_section_delimiter_char_count") == ["1"]
    assert objects("citation_section_delimiter_char_count_positioned") == ["1:1"]
    assert objects("citation_section_delimiter_pattern") == ["dot"]
    assert objects("citation_section_delimiter_distinct_count") == ["1"]

    assert objects("source_id_section_has_delimiter") == ["true"]
    assert objects("source_id_section_delimiter") == ["dot"]
    assert objects("source_id_section_delimiter_positioned") == ["1:dot"]
    assert objects("source_id_section_delimiter_token") == ["."]
    assert objects("source_id_section_delimiter_token_positioned") == ["1:."]
    assert objects("source_id_section_delimiter_count") == ["1"]
    assert objects("source_id_section_delimiter_char_count") == ["1"]
    assert objects("source_id_section_delimiter_char_count_positioned") == ["1:1"]
    assert objects("source_id_section_delimiter_pattern") == ["dot"]
    assert objects("source_id_section_delimiter_distinct_count") == ["1"]


def test_decode_modal_ir_document_emits_trailing_punct_presence_slots() -> None:
    decoded = decode_modal_ir_document(_trailing_punct_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_section_trailing_punct"] == ["."]
    assert slot_map["citation_section_has_trailing_punct"] == ["true"]
    assert slot_map["citation_section_trailing_punct_count"] == ["1"]
    assert slot_map["citation_section_trailing_punct_kind"] == ["dot"]
    assert slot_map["citation_section_has_suffix"] == ["false"]
    assert slot_map["citation_section_primary_has_suffix"] == ["false"]
    assert slot_map["citation_section_terminal_has_suffix"] == ["false"]
    assert slot_map["source_id_section_trailing_punct"] == ["."]
    assert slot_map["source_id_section_has_trailing_punct"] == ["true"]
    assert slot_map["source_id_section_trailing_punct_count"] == ["1"]
    assert slot_map["source_id_section_trailing_punct_kind"] == ["dot"]
    assert slot_map["source_id_section_has_suffix"] == ["false"]
    assert slot_map["source_id_section_primary_has_suffix"] == ["false"]
    assert slot_map["source_id_section_terminal_has_suffix"] == ["false"]


def test_modal_ir_to_flogic_triples_emit_trailing_punct_presence_slots() -> None:
    triples = modal_ir_to_flogic_triples(_trailing_punct_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_section_trailing_punct") == ["."]
    assert objects("citation_section_has_trailing_punct") == ["true"]
    assert objects("citation_section_trailing_punct_count") == ["1"]
    assert objects("citation_section_trailing_punct_kind") == ["dot"]
    assert objects("citation_section_has_suffix") == ["false"]
    assert objects("citation_section_primary_has_suffix") == ["false"]
    assert objects("citation_section_terminal_has_suffix") == ["false"]
    assert objects("source_id_section_trailing_punct") == ["."]
    assert objects("source_id_section_has_trailing_punct") == ["true"]
    assert objects("source_id_section_trailing_punct_count") == ["1"]
    assert objects("source_id_section_trailing_punct_kind") == ["dot"]
    assert objects("source_id_section_has_suffix") == ["false"]
    assert objects("source_id_section_primary_has_suffix") == ["false"]
    assert objects("source_id_section_terminal_has_suffix") == ["false"]


def test_decode_modal_ir_document_emits_section_profile_and_number_relation_slots() -> None:
    mixed_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_sample_document())
    )
    assert mixed_slot_map["citation_section_number_suffix_pair"] == ["360|bbb", "0|none"]
    assert mixed_slot_map["citation_section_number_suffix_pair_positioned"] == [
        "1:360|bbb",
        "2:0|none",
    ]
    assert mixed_slot_map["citation_section_primary_number_suffix_pair"] == ["360|bbb"]
    assert mixed_slot_map["citation_section_terminal_number_suffix_pair"] == ["0|none"]
    assert mixed_slot_map["source_id_section_number_suffix_pair"] == ["360|bbb", "0|none"]
    assert mixed_slot_map["source_id_section_number_suffix_pair_positioned"] == [
        "1:360|bbb",
        "2:0|none",
    ]
    assert mixed_slot_map["source_id_section_primary_number_suffix_pair"] == ["360|bbb"]
    assert mixed_slot_map["source_id_section_terminal_number_suffix_pair"] == ["0|none"]
    assert mixed_slot_map["citation_section_component_profile"] == ["compound_mixed"]
    assert mixed_slot_map["citation_section_primary_terminal_number_relation"] == [
        "descending"
    ]
    assert mixed_slot_map["citation_section_primary_terminal_number_span"] == ["360"]
    assert mixed_slot_map["source_id_section_component_profile"] == ["compound_mixed"]
    assert mixed_slot_map["source_id_section_primary_terminal_number_relation"] == [
        "descending"
    ]
    assert mixed_slot_map["source_id_section_primary_terminal_number_span"] == ["360"]
    assert mixed_slot_map["citation_section_has_hyphen_subsection"] == ["true"]
    assert mixed_slot_map["citation_section_hyphen_subsection_primary_number"] == ["360"]
    assert mixed_slot_map["citation_section_hyphen_subsection_primary_suffix"] == ["bbb"]
    assert mixed_slot_map["citation_section_hyphen_subsection_terminal_number"] == ["0"]
    assert mixed_slot_map["citation_section_hyphen_subsection_signature"] == ["360bbb-0"]
    assert mixed_slot_map["source_id_section_has_hyphen_subsection"] == ["true"]
    assert mixed_slot_map["source_id_section_hyphen_subsection_primary_number"] == ["360"]
    assert mixed_slot_map["source_id_section_hyphen_subsection_primary_suffix"] == ["bbb"]
    assert mixed_slot_map["source_id_section_hyphen_subsection_terminal_number"] == ["0"]
    assert mixed_slot_map["source_id_section_hyphen_subsection_signature"] == ["360bbb-0"]

    single_alnum_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_single_component_sample_document())
    )
    assert single_alnum_slot_map["citation_section_number_suffix_pair"] == ["190|l"]
    assert single_alnum_slot_map["citation_section_number_suffix_pair_positioned"] == [
        "1:190|l"
    ]
    assert single_alnum_slot_map["citation_section_primary_number_suffix_pair"] == [
        "190|l"
    ]
    assert single_alnum_slot_map["citation_section_terminal_number_suffix_pair"] == [
        "190|l"
    ]
    assert single_alnum_slot_map["source_id_section_number_suffix_pair"] == ["190|l"]
    assert single_alnum_slot_map["source_id_section_number_suffix_pair_positioned"] == [
        "1:190|l"
    ]
    assert single_alnum_slot_map["source_id_section_primary_number_suffix_pair"] == [
        "190|l"
    ]
    assert single_alnum_slot_map["source_id_section_terminal_number_suffix_pair"] == [
        "190|l"
    ]
    assert single_alnum_slot_map["citation_section_component_profile"] == [
        "single_alphanumeric"
    ]
    assert single_alnum_slot_map["citation_section_primary_terminal_number_relation"] == [
        "equal"
    ]
    assert single_alnum_slot_map["citation_section_primary_terminal_number_span"] == ["0"]
    assert single_alnum_slot_map["source_id_section_component_profile"] == [
        "single_alphanumeric"
    ]
    assert single_alnum_slot_map["source_id_section_primary_terminal_number_relation"] == [
        "equal"
    ]
    assert single_alnum_slot_map["source_id_section_primary_terminal_number_span"] == [
        "0"
    ]
    assert single_alnum_slot_map["citation_section_has_hyphen_subsection"] == ["false"]
    assert single_alnum_slot_map["source_id_section_has_hyphen_subsection"] == ["false"]

    single_numeric_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_trailing_punct_sample_document())
    )
    assert single_numeric_slot_map["citation_section_number_suffix_pair"] == ["60101|none"]
    assert single_numeric_slot_map["citation_section_number_suffix_pair_positioned"] == [
        "1:60101|none"
    ]
    assert single_numeric_slot_map["citation_section_primary_number_suffix_pair"] == [
        "60101|none"
    ]
    assert single_numeric_slot_map["citation_section_terminal_number_suffix_pair"] == [
        "60101|none"
    ]
    assert single_numeric_slot_map["source_id_section_number_suffix_pair"] == ["60101|none"]
    assert single_numeric_slot_map["source_id_section_number_suffix_pair_positioned"] == [
        "1:60101|none"
    ]
    assert single_numeric_slot_map["source_id_section_primary_number_suffix_pair"] == [
        "60101|none"
    ]
    assert single_numeric_slot_map["source_id_section_terminal_number_suffix_pair"] == [
        "60101|none"
    ]
    assert single_numeric_slot_map["citation_section_component_profile"] == [
        "single_numeric"
    ]
    assert single_numeric_slot_map["source_id_section_component_profile"] == [
        "single_numeric"
    ]
    assert single_numeric_slot_map["citation_section_has_hyphen_subsection"] == [
        "false"
    ]
    assert single_numeric_slot_map["source_id_section_has_hyphen_subsection"] == [
        "false"
    ]

    range_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_range_sample_document())
    )
    assert range_slot_map["citation_section_number_suffix_pair"] == ["228|a", "228|c"]
    assert range_slot_map["citation_section_number_suffix_pair_positioned"] == [
        "1:228|a",
        "2:228|c",
    ]
    assert range_slot_map["citation_section_primary_number_suffix_pair"] == ["228|a"]
    assert range_slot_map["citation_section_terminal_number_suffix_pair"] == ["228|c"]
    assert range_slot_map["source_id_section_number_suffix_pair"] == ["228|a", "228|c"]
    assert range_slot_map["source_id_section_number_suffix_pair_positioned"] == [
        "1:228|a",
        "2:228|c",
    ]
    assert range_slot_map["source_id_section_primary_number_suffix_pair"] == ["228|a"]
    assert range_slot_map["source_id_section_terminal_number_suffix_pair"] == ["228|c"]
    assert range_slot_map["citation_section_component_profile"] == ["range"]
    assert range_slot_map["citation_section_primary_terminal_number_relation"] == [
        "equal"
    ]
    assert range_slot_map["citation_section_primary_terminal_number_span"] == ["0"]
    assert range_slot_map["source_id_section_component_profile"] == ["range"]
    assert range_slot_map["source_id_section_primary_terminal_number_relation"] == [
        "equal"
    ]
    assert range_slot_map["source_id_section_primary_terminal_number_span"] == ["0"]


def test_modal_ir_to_flogic_triples_emit_section_profile_and_number_relation_slots() -> None:
    mixed_triples = modal_ir_to_flogic_triples(_sample_document())
    single_alnum_triples = modal_ir_to_flogic_triples(_single_component_sample_document())
    single_numeric_triples = modal_ir_to_flogic_triples(_trailing_punct_sample_document())
    range_triples = modal_ir_to_flogic_triples(_range_sample_document())

    def objects(triples: list[dict[str, str]], predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects(mixed_triples, "citation_section_component_profile") == [
        "compound_mixed"
    ]
    assert objects(mixed_triples, "citation_section_number_suffix_pair") == [
        "360|bbb",
        "0|none",
    ]
    assert objects(mixed_triples, "citation_section_number_suffix_pair_positioned") == [
        "1:360|bbb",
        "2:0|none",
    ]
    assert objects(mixed_triples, "citation_section_primary_number_suffix_pair") == [
        "360|bbb"
    ]
    assert objects(mixed_triples, "citation_section_terminal_number_suffix_pair") == [
        "0|none"
    ]
    assert objects(mixed_triples, "source_id_section_number_suffix_pair") == [
        "360|bbb",
        "0|none",
    ]
    assert objects(mixed_triples, "source_id_section_number_suffix_pair_positioned") == [
        "1:360|bbb",
        "2:0|none",
    ]
    assert objects(mixed_triples, "source_id_section_primary_number_suffix_pair") == [
        "360|bbb"
    ]
    assert objects(mixed_triples, "source_id_section_terminal_number_suffix_pair") == [
        "0|none"
    ]
    assert objects(mixed_triples, "citation_section_primary_terminal_number_relation") == [
        "descending"
    ]
    assert objects(mixed_triples, "citation_section_primary_terminal_number_span") == [
        "360"
    ]
    assert objects(mixed_triples, "source_id_section_component_profile") == [
        "compound_mixed"
    ]
    assert objects(mixed_triples, "source_id_section_primary_terminal_number_relation") == [
        "descending"
    ]
    assert objects(mixed_triples, "source_id_section_primary_terminal_number_span") == [
        "360"
    ]
    assert objects(mixed_triples, "citation_section_has_hyphen_subsection") == ["true"]
    assert objects(
        mixed_triples,
        "citation_section_hyphen_subsection_primary_number",
    ) == ["360"]
    assert objects(
        mixed_triples,
        "citation_section_hyphen_subsection_primary_suffix",
    ) == ["bbb"]
    assert objects(
        mixed_triples,
        "citation_section_hyphen_subsection_terminal_number",
    ) == ["0"]
    assert objects(
        mixed_triples,
        "citation_section_hyphen_subsection_signature",
    ) == ["360bbb-0"]
    assert objects(mixed_triples, "source_id_section_has_hyphen_subsection") == ["true"]
    assert objects(
        mixed_triples,
        "source_id_section_hyphen_subsection_primary_number",
    ) == ["360"]
    assert objects(
        mixed_triples,
        "source_id_section_hyphen_subsection_primary_suffix",
    ) == ["bbb"]
    assert objects(
        mixed_triples,
        "source_id_section_hyphen_subsection_terminal_number",
    ) == ["0"]
    assert objects(
        mixed_triples,
        "source_id_section_hyphen_subsection_signature",
    ) == ["360bbb-0"]

    assert objects(single_alnum_triples, "citation_section_component_profile") == [
        "single_alphanumeric"
    ]
    assert objects(single_alnum_triples, "citation_section_number_suffix_pair") == ["190|l"]
    assert objects(
        single_alnum_triples,
        "citation_section_number_suffix_pair_positioned",
    ) == ["1:190|l"]
    assert objects(single_alnum_triples, "citation_section_primary_number_suffix_pair") == [
        "190|l"
    ]
    assert objects(single_alnum_triples, "citation_section_terminal_number_suffix_pair") == [
        "190|l"
    ]
    assert objects(single_alnum_triples, "source_id_section_number_suffix_pair") == ["190|l"]
    assert objects(
        single_alnum_triples,
        "source_id_section_number_suffix_pair_positioned",
    ) == ["1:190|l"]
    assert objects(single_alnum_triples, "source_id_section_primary_number_suffix_pair") == [
        "190|l"
    ]
    assert objects(single_alnum_triples, "source_id_section_terminal_number_suffix_pair") == [
        "190|l"
    ]
    assert objects(single_alnum_triples, "citation_section_primary_terminal_number_relation") == [
        "equal"
    ]
    assert objects(single_alnum_triples, "citation_section_primary_terminal_number_span") == [
        "0"
    ]
    assert objects(single_alnum_triples, "source_id_section_component_profile") == [
        "single_alphanumeric"
    ]
    assert objects(single_alnum_triples, "source_id_section_primary_terminal_number_relation") == [
        "equal"
    ]
    assert objects(single_alnum_triples, "source_id_section_primary_terminal_number_span") == [
        "0"
    ]
    assert objects(single_alnum_triples, "citation_section_has_hyphen_subsection") == [
        "false"
    ]
    assert objects(single_alnum_triples, "source_id_section_has_hyphen_subsection") == [
        "false"
    ]

    assert objects(single_numeric_triples, "citation_section_component_profile") == [
        "single_numeric"
    ]
    assert objects(single_numeric_triples, "citation_section_number_suffix_pair") == [
        "60101|none"
    ]
    assert objects(
        single_numeric_triples,
        "citation_section_number_suffix_pair_positioned",
    ) == ["1:60101|none"]
    assert objects(single_numeric_triples, "citation_section_primary_number_suffix_pair") == [
        "60101|none"
    ]
    assert objects(single_numeric_triples, "citation_section_terminal_number_suffix_pair") == [
        "60101|none"
    ]
    assert objects(single_numeric_triples, "source_id_section_number_suffix_pair") == [
        "60101|none"
    ]
    assert objects(
        single_numeric_triples,
        "source_id_section_number_suffix_pair_positioned",
    ) == ["1:60101|none"]
    assert objects(single_numeric_triples, "source_id_section_primary_number_suffix_pair") == [
        "60101|none"
    ]
    assert objects(single_numeric_triples, "source_id_section_terminal_number_suffix_pair") == [
        "60101|none"
    ]
    assert objects(single_numeric_triples, "source_id_section_component_profile") == [
        "single_numeric"
    ]
    assert objects(single_numeric_triples, "citation_section_has_hyphen_subsection") == [
        "false"
    ]
    assert objects(single_numeric_triples, "source_id_section_has_hyphen_subsection") == [
        "false"
    ]

    assert objects(range_triples, "citation_section_component_profile") == ["range"]
    assert objects(range_triples, "citation_section_number_suffix_pair") == [
        "228|a",
        "228|c",
    ]
    assert objects(range_triples, "citation_section_number_suffix_pair_positioned") == [
        "1:228|a",
        "2:228|c",
    ]
    assert objects(range_triples, "citation_section_primary_number_suffix_pair") == ["228|a"]
    assert objects(range_triples, "citation_section_terminal_number_suffix_pair") == ["228|c"]
    assert objects(range_triples, "source_id_section_number_suffix_pair") == [
        "228|a",
        "228|c",
    ]
    assert objects(range_triples, "source_id_section_number_suffix_pair_positioned") == [
        "1:228|a",
        "2:228|c",
    ]
    assert objects(range_triples, "source_id_section_primary_number_suffix_pair") == ["228|a"]
    assert objects(range_triples, "source_id_section_terminal_number_suffix_pair") == ["228|c"]
    assert objects(range_triples, "citation_section_primary_terminal_number_relation") == [
        "equal"
    ]
    assert objects(range_triples, "citation_section_primary_terminal_number_span") == [
        "0"
    ]
    assert objects(range_triples, "source_id_section_component_profile") == ["range"]
    assert objects(range_triples, "source_id_section_primary_terminal_number_relation") == [
        "equal"
    ]
    assert objects(range_triples, "source_id_section_primary_terminal_number_span") == [
        "0"
    ]


def test_decode_modal_ir_document_emits_document_modal_family_count_slots() -> None:
    sample = _sample_document()
    document = ModalIRDocument(
        document_id=sample.document_id,
        source=sample.source,
        normalized_text=sample.normalized_text,
        formulas=list(sample.formulas),
        metadata={
            "modal_family_counts": {
                "deontic": 2,
                "temporal": 1,
            }
        },
    )
    decoded = decode_modal_ir_document(document)
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["modal_family_count"] == ["deontic:2", "temporal:1"]
    assert slot_map["modal_family_count_ranked"] == [
        "1:deontic:2",
        "2:temporal:1",
    ]
    assert slot_map["modal_family_count_family"] == ["deontic", "temporal"]
    assert slot_map["modal_family_count_value"] == ["2", "1"]
    assert slot_map["modal_family_count_value_parity"] == ["even", "odd"]
    assert slot_map["modal_family_count_value_digit_count_bucket"] == ["1_digit"]
    assert slot_map["modal_family_count_value_has_zero_digit"] == ["false"]
    assert slot_map["modal_family_count_deontic"] == ["2"]
    assert slot_map["modal_family_count_deontic_parity"] == ["even"]
    assert slot_map["modal_family_count_temporal"] == ["1"]
    assert slot_map["modal_family_count_temporal_parity"] == ["odd"]


def test_modal_ir_to_flogic_triples_emits_document_modal_family_count_slots() -> None:
    sample = _sample_document()
    document = ModalIRDocument(
        document_id=sample.document_id,
        source=sample.source,
        normalized_text=sample.normalized_text,
        formulas=list(sample.formulas),
        metadata={
            "modal_family_counts": {
                "deontic": 2,
                "temporal": 1,
            }
        },
    )
    triples = modal_ir_to_flogic_triples(document)

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("modal_family_count") == ["deontic:2", "temporal:1"]
    assert objects("modal_family_count_ranked") == [
        "1:deontic:2",
        "2:temporal:1",
    ]
    assert objects("modal_family_count_family") == ["deontic", "temporal"]
    assert objects("modal_family_count_value") == ["2", "1"]
    assert objects("modal_family_count_value_parity") == ["even", "odd"]
    assert objects("modal_family_count_value_digit_count_bucket") == ["1_digit"]
    assert objects("modal_family_count_value_has_zero_digit") == ["false"]
    assert objects("modal_family_count_deontic") == ["2"]
    assert objects("modal_family_count_deontic_parity") == ["even"]
    assert objects("modal_family_count_temporal") == ["1"]
    assert objects("modal_family_count_temporal_parity") == ["odd"]


def test_decode_modal_ir_document_derives_modal_family_count_slots_from_formulas() -> None:
    decoded = decode_modal_ir_document(_single_formula_temporal_family_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["modal_family_count"] == ["temporal:1"]
    assert slot_map["modal_family_count_ranked"] == ["1:temporal:1"]
    assert slot_map["modal_family_count_family"] == ["temporal"]
    assert slot_map["modal_family_count_value"] == ["1"]
    assert slot_map["modal_family_count_value_parity"] == ["odd"]
    assert slot_map["modal_family_count_temporal_parity"] == ["odd"]
    assert slot_map["modal_family_count_temporal"] == ["1"]


def test_modal_ir_to_flogic_triples_derives_modal_family_count_slots_from_formulas() -> None:
    triples = modal_ir_to_flogic_triples(_single_formula_temporal_family_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("modal_family_count") == ["temporal:1"]
    assert objects("modal_family_count_ranked") == ["1:temporal:1"]
    assert objects("modal_family_count_family") == ["temporal"]
    assert objects("modal_family_count_value") == ["1"]
    assert objects("modal_family_count_value_parity") == ["odd"]
    assert objects("modal_family_count_temporal_parity") == ["odd"]
    assert objects("modal_family_count_temporal") == ["1"]


def test_modal_ir_to_flogic_triples_infers_selected_frame_and_candidates_from_metadata() -> None:
    triples = modal_ir_to_flogic_triples(_metadata_only_frame_terms_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("selected_ontology_frame") == ["administrative_notice_hearing"]
    assert objects("candidate_ontology_frame") == [
        "administrative_notice_hearing",
        "criminal_penalty_enforcement",
        "housing_voucher_benefits",
    ]
    assert objects("candidate_ontology_frame_rank") == ["1", "2", "3"]
    assert objects("candidate_ontology_frame_ranked") == [
        "1:administrative_notice_hearing",
        "2:criminal_penalty_enforcement",
        "3:housing_voucher_benefits",
    ]
    assert objects("candidate_ontology_frame_rank_parity") == ["odd", "even", "odd"]
    assert objects("candidate_ontology_frame_rank_digit_count_bucket") == [
        "1_digit",
        "1_digit",
        "1_digit",
    ]
    assert objects("candidate_ontology_frame_ranked_token_prefix") == [
        "1:administrative",
        "2:criminal",
        "3:housing",
    ]
    assert objects("candidate_ontology_term") == [
        "administrative",
        "administrative_notice_hearing",
        "agency",
        "appeal",
        "deadline",
        "criminal",
        "enforcement",
        "penalty",
        "accommodation",
        "housing",
        "voucher",
    ]
    assert objects("selected_ontology_term") == [
        "administrative",
        "administrative_notice_hearing",
        "agency",
        "appeal",
        "deadline",
    ]
    assert objects("interpreted_in_frame") == ["administrative_notice_hearing"]
    assert objects("interpreted_in_frame_term") == [
        "administrative",
        "administrative_notice_hearing",
        "agency",
        "appeal",
        "deadline",
    ]


def test_modal_ir_to_flogic_triples_emits_document_citation_slots_when_no_formulas() -> None:
    triples = modal_ir_to_flogic_triples(_zero_formula_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation") == ["50 U.S.C. 3091."]
    assert objects("citation_canonical") == ["50 U.S.C. 3091"]
    assert objects("citation_section") == ["3091"]
    assert objects("citation_section_trailing_punct") == ["."]
    assert objects("citation_section_trailing_punct_count") == ["1"]
    assert objects("source_id_section") == ["3091."]
    assert objects("source_id_section_normalized") == ["3091"]
    assert objects("source_id_section_trailing_punct") == ["."]
    assert objects("source_id_section_trailing_punct_count") == ["1"]
    assert objects("source_id_citation_canonical") == ["50 U.S.C. 3091"]
    assert objects("citation_source_id_alignment") == ["exact_match"]
    assert objects("citation_source_id_title_match") == ["true"]
    assert objects("citation_source_id_section_match") == ["true"]
    assert objects("citation_source_id_title_section_key_match") == ["true"]
    assert objects("citation_source_id_canonical_match") == ["true"]
    assert objects("citation_source_id_section_raw_match") == ["true"]
    assert objects("citation_source_id_section_raw_pair") == ["3091.|3091."]
    assert objects("citation_source_id_section_trailing_punct_presence_match") == ["true"]
    assert objects("citation_source_id_section_trailing_punct_match") == ["true"]
    assert objects("citation_source_id_section_trailing_punct_pair") == [".|."]


def test_decode_modal_ir_document_emits_document_citation_source_id_alignment_slots_when_no_formulas() -> None:
    decoded = decode_modal_ir_document(_zero_formula_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation_source_id_alignment"] == ["exact_match"]
    assert slot_map["citation_source_id_title_match"] == ["true"]
    assert slot_map["citation_source_id_section_match"] == ["true"]
    assert slot_map["citation_source_id_title_section_key_match"] == ["true"]
    assert slot_map["citation_source_id_canonical_match"] == ["true"]
    assert slot_map["citation_source_id_section_raw_match"] == ["true"]
    assert slot_map["citation_source_id_section_raw_pair"] == ["3091.|3091."]
    assert slot_map["citation_source_id_section_trailing_punct_presence_match"] == ["true"]
    assert slot_map["citation_source_id_section_trailing_punct_match"] == ["true"]
    assert slot_map["citation_source_id_section_trailing_punct_pair"] == [".|."]


def test_decode_modal_ir_document_infers_document_citation_slots_from_source_id_without_metadata() -> None:
    decoded = decode_modal_ir_document(_zero_formula_source_id_only_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation"] == ["22 U.S.C. 7636"]
    assert slot_map["citation_derivation"] == ["source_id_inferred"]
    assert slot_map["citation_canonical"] == ["22 U.S.C. 7636"]
    assert slot_map["citation_section"] == ["7636"]
    assert slot_map["citation_source_id_alignment"] == ["exact_match"]
    assert slot_map["citation_source_id_section_raw_pair"] == ["7636|7636"]


def test_modal_ir_to_flogic_triples_infers_document_citation_slots_from_source_id_without_metadata() -> None:
    triples = modal_ir_to_flogic_triples(_zero_formula_source_id_only_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation") == ["22 U.S.C. 7636"]
    assert objects("citation_derivation") == ["source_id_inferred"]
    assert objects("citation_canonical") == ["22 U.S.C. 7636"]
    assert objects("citation_section") == ["7636"]
    assert objects("citation_source_id_alignment") == ["exact_match"]
    assert objects("citation_source_id_section_raw_pair") == ["7636|7636"]


def test_decode_modal_ir_document_infers_formula_citation_slots_from_source_id_when_missing() -> None:
    decoded = decode_modal_ir_document(_formula_missing_citation_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["citation"] == ["18 U.S.C. 1719"]
    assert slot_map["citation_derivation"] == ["source_id_inferred"]
    assert slot_map["citation_canonical"] == ["18 U.S.C. 1719"]
    assert slot_map["citation_section"] == ["1719"]
    assert slot_map["citation_source_id_alignment"] == ["exact_match"]
    assert slot_map["citation_source_id_section_raw_pair"] == ["1719|1719"]


def test_modal_ir_to_flogic_triples_infers_formula_citation_slots_from_source_id_when_missing() -> None:
    triples = modal_ir_to_flogic_triples(_formula_missing_citation_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation") == ["18 U.S.C. 1719"]
    assert objects("citation_derivation") == ["source_id_inferred"]
    assert objects("citation_canonical") == ["18 U.S.C. 1719"]
    assert objects("citation_section") == ["1719"]
    assert objects("citation_source_id_alignment") == ["exact_match"]
    assert objects("citation_source_id_section_raw_pair") == ["1719|1719"]


def test_decode_modal_ir_document_emits_numeric_signature_slots() -> None:
    slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_dot_delimited_sample_document())
    )

    assert slot_map["citation_title_number_parity"] == ["even"]
    assert slot_map["citation_title_number_leading_digit"] == ["4"]
    assert slot_map["citation_title_number_trailing_two_digits"] == ["42"]
    assert slot_map["citation_title_number_zero_digit_count"] == ["0"]
    assert slot_map["citation_title_number_has_zero_digit"] == ["false"]
    assert slot_map["citation_title_number_trailing_zero_count"] == ["0"]
    assert slot_map["source_id_title_number_parity"] == ["even"]
    assert slot_map["source_id_title_number_leading_digit"] == ["4"]
    assert slot_map["source_id_title_number_trailing_two_digits"] == ["42"]
    assert slot_map["source_id_title_number_zero_digit_count"] == ["0"]
    assert slot_map["source_id_title_number_has_zero_digit"] == ["false"]
    assert slot_map["source_id_title_number_trailing_zero_count"] == ["0"]

    assert slot_map["citation_section_number_parity"] == ["even", "odd"]
    assert slot_map["citation_section_number_parity_positioned"] == ["1:even", "2:odd"]
    assert slot_map["citation_section_number_leading_digit_positioned"] == ["1:1", "2:1"]
    assert slot_map["citation_section_number_trailing_two_digits_positioned"] == [
        "1:96",
        "2:1",
    ]
    assert slot_map["citation_section_number_zero_digit_count"] == ["0"]
    assert slot_map["citation_section_number_zero_digit_count_positioned"] == [
        "1:0",
        "2:0",
    ]
    assert slot_map["citation_section_number_has_zero_digit"] == ["false"]
    assert slot_map["citation_section_number_has_zero_digit_positioned"] == [
        "1:false",
        "2:false",
    ]
    assert slot_map["citation_section_number_trailing_zero_count"] == ["0"]
    assert slot_map["citation_section_number_trailing_zero_count_positioned"] == [
        "1:0",
        "2:0",
    ]
    assert slot_map["citation_section_primary_number_parity"] == ["even"]
    assert slot_map["citation_section_primary_number_leading_digit"] == ["1"]
    assert slot_map["citation_section_primary_number_trailing_two_digits"] == ["96"]
    assert slot_map["citation_section_primary_number_zero_digit_count"] == ["0"]
    assert slot_map["citation_section_primary_number_has_zero_digit"] == ["false"]
    assert slot_map["citation_section_primary_number_trailing_zero_count"] == ["0"]
    assert slot_map["citation_section_terminal_number_parity"] == ["odd"]
    assert slot_map["citation_section_terminal_number_leading_digit"] == ["1"]
    assert slot_map["citation_section_terminal_number_trailing_two_digits"] == ["1"]
    assert slot_map["citation_section_terminal_number_zero_digit_count"] == ["0"]
    assert slot_map["citation_section_terminal_number_has_zero_digit"] == ["false"]
    assert slot_map["citation_section_terminal_number_trailing_zero_count"] == ["0"]

    assert slot_map["source_id_section_number_parity"] == ["even", "odd"]
    assert slot_map["source_id_section_number_parity_positioned"] == ["1:even", "2:odd"]
    assert slot_map["source_id_section_number_leading_digit_positioned"] == [
        "1:1",
        "2:1",
    ]
    assert slot_map["source_id_section_number_trailing_two_digits_positioned"] == [
        "1:96",
        "2:1",
    ]
    assert slot_map["source_id_section_number_zero_digit_count"] == ["0"]
    assert slot_map["source_id_section_number_zero_digit_count_positioned"] == [
        "1:0",
        "2:0",
    ]
    assert slot_map["source_id_section_number_has_zero_digit"] == ["false"]
    assert slot_map["source_id_section_number_has_zero_digit_positioned"] == [
        "1:false",
        "2:false",
    ]
    assert slot_map["source_id_section_number_trailing_zero_count"] == ["0"]
    assert slot_map["source_id_section_number_trailing_zero_count_positioned"] == [
        "1:0",
        "2:0",
    ]
    assert slot_map["source_id_section_primary_number_parity"] == ["even"]
    assert slot_map["source_id_section_primary_number_leading_digit"] == ["1"]
    assert slot_map["source_id_section_primary_number_trailing_two_digits"] == ["96"]
    assert slot_map["source_id_section_primary_number_zero_digit_count"] == ["0"]
    assert slot_map["source_id_section_primary_number_has_zero_digit"] == ["false"]
    assert slot_map["source_id_section_primary_number_trailing_zero_count"] == ["0"]
    assert slot_map["source_id_section_terminal_number_parity"] == ["odd"]
    assert slot_map["source_id_section_terminal_number_leading_digit"] == ["1"]
    assert slot_map["source_id_section_terminal_number_trailing_two_digits"] == ["1"]
    assert slot_map["source_id_section_terminal_number_zero_digit_count"] == ["0"]
    assert slot_map["source_id_section_terminal_number_has_zero_digit"] == ["false"]
    assert slot_map["source_id_section_terminal_number_trailing_zero_count"] == ["0"]

    zero_digit_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_zero_digit_signature_sample_document())
    )
    assert zero_digit_slot_map["citation_title_number_zero_digit_count"] == ["0"]
    assert zero_digit_slot_map["citation_title_number_has_zero_digit"] == ["false"]
    assert zero_digit_slot_map["citation_title_number_trailing_zero_count"] == ["0"]
    assert zero_digit_slot_map["citation_section_number_zero_digit_count"] == ["1"]
    assert zero_digit_slot_map["citation_section_number_has_zero_digit"] == ["true"]
    assert zero_digit_slot_map["citation_section_number_trailing_zero_count"] == ["1"]
    assert zero_digit_slot_map["citation_section_number_zero_digit_count_positioned"] == [
        "1:1"
    ]
    assert zero_digit_slot_map["citation_section_number_has_zero_digit_positioned"] == [
        "1:true"
    ]
    assert zero_digit_slot_map[
        "citation_section_number_trailing_zero_count_positioned"
    ] == ["1:1"]
    assert zero_digit_slot_map["citation_section_primary_number_zero_digit_count"] == [
        "1"
    ]
    assert zero_digit_slot_map["citation_section_primary_number_has_zero_digit"] == [
        "true"
    ]
    assert zero_digit_slot_map["citation_section_primary_number_trailing_zero_count"] == [
        "1"
    ]
    assert zero_digit_slot_map["source_id_section_number_zero_digit_count"] == ["1"]
    assert zero_digit_slot_map["source_id_section_number_has_zero_digit"] == ["true"]
    assert zero_digit_slot_map["source_id_section_number_trailing_zero_count"] == ["1"]
    assert zero_digit_slot_map["source_id_section_primary_number_zero_digit_count"] == [
        "1"
    ]
    assert zero_digit_slot_map["source_id_section_primary_number_has_zero_digit"] == [
        "true"
    ]
    assert zero_digit_slot_map["source_id_section_primary_number_trailing_zero_count"] == [
        "1"
    ]

    odd_title_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_sample_document())
    )
    assert odd_title_slot_map["citation_title_number_parity"] == ["odd"]
    assert odd_title_slot_map["source_id_title_number_parity"] == ["odd"]


def test_modal_ir_to_flogic_triples_emits_numeric_signature_slots() -> None:
    triples = modal_ir_to_flogic_triples(_dot_delimited_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_title_number_parity") == ["even"]
    assert objects("citation_title_number_leading_digit") == ["4"]
    assert objects("citation_title_number_trailing_two_digits") == ["42"]
    assert objects("citation_title_number_zero_digit_count") == ["0"]
    assert objects("citation_title_number_has_zero_digit") == ["false"]
    assert objects("citation_title_number_trailing_zero_count") == ["0"]
    assert objects("source_id_title_number_parity") == ["even"]
    assert objects("source_id_title_number_leading_digit") == ["4"]
    assert objects("source_id_title_number_trailing_two_digits") == ["42"]
    assert objects("source_id_title_number_zero_digit_count") == ["0"]
    assert objects("source_id_title_number_has_zero_digit") == ["false"]
    assert objects("source_id_title_number_trailing_zero_count") == ["0"]

    assert objects("citation_section_number_parity") == ["even", "odd"]
    assert objects("citation_section_number_parity_positioned") == ["1:even", "2:odd"]
    assert objects("citation_section_number_leading_digit_positioned") == ["1:1", "2:1"]
    assert objects("citation_section_number_trailing_two_digits_positioned") == [
        "1:96",
        "2:1",
    ]
    assert objects("citation_section_number_zero_digit_count") == ["0"]
    assert objects("citation_section_number_zero_digit_count_positioned") == [
        "1:0",
        "2:0",
    ]
    assert objects("citation_section_number_has_zero_digit") == ["false"]
    assert objects("citation_section_number_has_zero_digit_positioned") == [
        "1:false",
        "2:false",
    ]
    assert objects("citation_section_number_trailing_zero_count") == ["0"]
    assert objects("citation_section_number_trailing_zero_count_positioned") == [
        "1:0",
        "2:0",
    ]
    assert objects("citation_section_primary_number_parity") == ["even"]
    assert objects("citation_section_primary_number_leading_digit") == ["1"]
    assert objects("citation_section_primary_number_trailing_two_digits") == ["96"]
    assert objects("citation_section_primary_number_zero_digit_count") == ["0"]
    assert objects("citation_section_primary_number_has_zero_digit") == ["false"]
    assert objects("citation_section_primary_number_trailing_zero_count") == ["0"]
    assert objects("citation_section_terminal_number_parity") == ["odd"]
    assert objects("citation_section_terminal_number_leading_digit") == ["1"]
    assert objects("citation_section_terminal_number_trailing_two_digits") == ["1"]
    assert objects("citation_section_terminal_number_zero_digit_count") == ["0"]
    assert objects("citation_section_terminal_number_has_zero_digit") == ["false"]
    assert objects("citation_section_terminal_number_trailing_zero_count") == ["0"]

    assert objects("source_id_section_number_parity") == ["even", "odd"]
    assert objects("source_id_section_number_parity_positioned") == ["1:even", "2:odd"]
    assert objects("source_id_section_number_leading_digit_positioned") == ["1:1", "2:1"]
    assert objects("source_id_section_number_trailing_two_digits_positioned") == [
        "1:96",
        "2:1",
    ]
    assert objects("source_id_section_number_zero_digit_count") == ["0"]
    assert objects("source_id_section_number_zero_digit_count_positioned") == [
        "1:0",
        "2:0",
    ]
    assert objects("source_id_section_number_has_zero_digit") == ["false"]
    assert objects("source_id_section_number_has_zero_digit_positioned") == [
        "1:false",
        "2:false",
    ]
    assert objects("source_id_section_number_trailing_zero_count") == ["0"]
    assert objects("source_id_section_number_trailing_zero_count_positioned") == [
        "1:0",
        "2:0",
    ]
    assert objects("source_id_section_primary_number_parity") == ["even"]
    assert objects("source_id_section_primary_number_leading_digit") == ["1"]
    assert objects("source_id_section_primary_number_trailing_two_digits") == ["96"]
    assert objects("source_id_section_primary_number_zero_digit_count") == ["0"]
    assert objects("source_id_section_primary_number_has_zero_digit") == ["false"]
    assert objects("source_id_section_primary_number_trailing_zero_count") == ["0"]
    assert objects("source_id_section_terminal_number_parity") == ["odd"]
    assert objects("source_id_section_terminal_number_leading_digit") == ["1"]
    assert objects("source_id_section_terminal_number_trailing_two_digits") == ["1"]
    assert objects("source_id_section_terminal_number_zero_digit_count") == ["0"]
    assert objects("source_id_section_terminal_number_has_zero_digit") == ["false"]
    assert objects("source_id_section_terminal_number_trailing_zero_count") == ["0"]

    zero_digit_triples = modal_ir_to_flogic_triples(_zero_digit_signature_sample_document())

    def zero_digit_objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in zero_digit_triples
            if triple.get("predicate") == predicate
        ]

    assert zero_digit_objects("citation_title_number_zero_digit_count") == ["0"]
    assert zero_digit_objects("citation_title_number_has_zero_digit") == ["false"]
    assert zero_digit_objects("citation_title_number_trailing_zero_count") == ["0"]
    assert zero_digit_objects("citation_section_number_zero_digit_count") == ["1"]
    assert zero_digit_objects("citation_section_number_has_zero_digit") == ["true"]
    assert zero_digit_objects("citation_section_number_trailing_zero_count") == ["1"]
    assert zero_digit_objects("citation_section_number_zero_digit_count_positioned") == [
        "1:1"
    ]
    assert zero_digit_objects("citation_section_number_has_zero_digit_positioned") == [
        "1:true"
    ]
    assert zero_digit_objects("citation_section_number_trailing_zero_count_positioned") == [
        "1:1"
    ]
    assert zero_digit_objects("citation_section_primary_number_zero_digit_count") == ["1"]
    assert zero_digit_objects("citation_section_primary_number_has_zero_digit") == ["true"]
    assert zero_digit_objects("citation_section_primary_number_trailing_zero_count") == [
        "1"
    ]
    assert zero_digit_objects("source_id_section_number_zero_digit_count") == ["1"]
    assert zero_digit_objects("source_id_section_number_has_zero_digit") == ["true"]
    assert zero_digit_objects("source_id_section_number_trailing_zero_count") == ["1"]
    assert zero_digit_objects("source_id_section_primary_number_zero_digit_count") == [
        "1"
    ]
    assert zero_digit_objects("source_id_section_primary_number_has_zero_digit") == [
        "true"
    ]
    assert zero_digit_objects("source_id_section_primary_number_trailing_zero_count") == [
        "1"
    ]

    odd_title_triples = modal_ir_to_flogic_triples(_sample_document())

    def odd_title_objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in odd_title_triples
            if triple.get("predicate") == predicate
        ]

    assert odd_title_objects("citation_title_number_parity") == ["odd"]
    assert odd_title_objects("source_id_title_number_parity") == ["odd"]


def test_decode_modal_ir_document_emits_usc_section_marker_variant_slots() -> None:
    section_marker_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_section_marker_sample_document())
    )
    assert section_marker_slot_map["citation"] == ["2 U.S.C. §190l"]
    assert section_marker_slot_map["citation_canonical"] == ["2 U.S.C. 190l"]
    assert section_marker_slot_map["citation_section"] == ["190l"]
    assert section_marker_slot_map["citation_section_primary"] == ["190l"]
    assert section_marker_slot_map["citation_section_component_profile"] == [
        "single_alphanumeric"
    ]
    assert section_marker_slot_map["citation_section_has_delimiter"] == ["false"]
    assert section_marker_slot_map["citation_section_delimiter_count"] == ["0"]
    assert section_marker_slot_map["citation_section_primary_suffix"] == ["l"]
    assert section_marker_slot_map["citation_section_suffix_kind"] == ["alpha"]

    plural_marker_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_plural_section_marker_range_sample_document())
    )
    assert plural_marker_slot_map["citation"] == ["45 U.S.C. §§ 228a to 228c."]
    assert plural_marker_slot_map["citation_canonical"] == ["45 U.S.C. 228a to 228c"]
    assert plural_marker_slot_map["citation_section"] == ["228a to 228c"]
    assert plural_marker_slot_map["citation_section_range"] == ["228a to 228c"]
    assert plural_marker_slot_map["citation_section_range_start"] == ["228a"]
    assert plural_marker_slot_map["citation_section_range_end"] == ["228c"]
    assert plural_marker_slot_map["citation_section_range_connector"] == ["to"]
    assert plural_marker_slot_map["citation_section_trailing_punct"] == ["."]
    assert plural_marker_slot_map["citation_section_has_trailing_punct"] == ["true"]
    assert plural_marker_slot_map["citation_section_trailing_punct_count"] == ["1"]
    assert plural_marker_slot_map["citation_section_trailing_punct_kind"] == ["dot"]


def test_modal_ir_to_flogic_triples_emits_usc_section_marker_variant_slots() -> None:
    section_marker_triples = modal_ir_to_flogic_triples(_section_marker_sample_document())
    plural_marker_triples = modal_ir_to_flogic_triples(
        _plural_section_marker_range_sample_document()
    )

    def objects(triples: list[dict[str, str]], predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects(section_marker_triples, "citation") == ["2 U.S.C. §190l"]
    assert objects(section_marker_triples, "citation_canonical") == ["2 U.S.C. 190l"]
    assert objects(section_marker_triples, "citation_section") == ["190l"]
    assert objects(section_marker_triples, "citation_section_primary") == ["190l"]
    assert objects(section_marker_triples, "citation_section_component_profile") == [
        "single_alphanumeric"
    ]
    assert objects(section_marker_triples, "citation_section_has_delimiter") == ["false"]
    assert objects(section_marker_triples, "citation_section_delimiter_count") == ["0"]
    assert objects(section_marker_triples, "citation_section_primary_suffix") == ["l"]
    assert objects(section_marker_triples, "citation_section_suffix_kind") == ["alpha"]

    assert objects(plural_marker_triples, "citation") == ["45 U.S.C. §§ 228a to 228c."]
    assert objects(plural_marker_triples, "citation_canonical") == [
        "45 U.S.C. 228a to 228c"
    ]
    assert objects(plural_marker_triples, "citation_section") == ["228a to 228c"]
    assert objects(plural_marker_triples, "citation_section_range") == ["228a to 228c"]
    assert objects(plural_marker_triples, "citation_section_range_start") == ["228a"]
    assert objects(plural_marker_triples, "citation_section_range_end") == ["228c"]
    assert objects(plural_marker_triples, "citation_section_range_connector") == ["to"]
    assert objects(plural_marker_triples, "citation_section_trailing_punct") == ["."]
    assert objects(plural_marker_triples, "citation_section_has_trailing_punct") == [
        "true"
    ]
    assert objects(plural_marker_triples, "citation_section_trailing_punct_count") == [
        "1"
    ]
    assert objects(plural_marker_triples, "citation_section_trailing_punct_kind") == [
        "dot"
    ]


def test_decode_modal_ir_document_emits_section_heading_tail_for_coarse_fallback() -> None:
    decoded = decode_modal_ir_document(_coarse_heading_tail_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["fallback_rule"] == ["uscode_section_heading_coarse_v1"]
    assert slot_map["section_heading_tail"] == ["Student aid program improvements"]
    assert slot_map["fallback_surface_text"] == ["Student aid program improvements"]
    assert slot_map["section_heading_tail_token_count"] == ["4"]
    assert slot_map["section_heading_tail_token_suffix"] == ["improvements"]
    assert slot_map["fallback_surface_text_token_count"] == ["4"]
    assert slot_map["fallback_surface_text_token_suffix"] == ["improvements"]


def test_modal_ir_to_flogic_triples_emits_section_heading_tail_for_coarse_fallback() -> None:
    triples = modal_ir_to_flogic_triples(_coarse_heading_tail_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("fallback_rule") == ["uscode_section_heading_coarse_v1"]
    assert objects("section_heading_tail") == ["Student aid program improvements"]
    assert objects("fallback_surface_text") == ["Student aid program improvements"]
    assert objects("section_heading_tail_token_count") == ["4"]
    assert objects("section_heading_tail_token_suffix") == ["improvements"]
    assert objects("fallback_surface_text_token_count") == ["4"]
    assert objects("fallback_surface_text_token_suffix") == ["improvements"]


def test_decode_modal_ir_document_emits_procedural_keyword_slots() -> None:
    decoded = decode_modal_ir_document(_procedural_keyword_fallback_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["procedural_keyword"] == ["review"]
    assert slot_map["procedural_keyword_token_count"] == ["1"]
    assert slot_map["procedural_keyword_token_prefix"] == ["review"]
    assert slot_map["procedural_keyword_token_suffix"] == ["review"]
    assert slot_map["procedural_keyword_stem"] == ["review"]


def test_modal_ir_to_flogic_triples_emits_procedural_keyword_slots() -> None:
    triples = modal_ir_to_flogic_triples(_procedural_keyword_fallback_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("procedural_keyword") == ["review"]
    assert objects("procedural_keyword_token_count") == ["1"]
    assert objects("procedural_keyword_token_prefix") == ["review"]
    assert objects("procedural_keyword_token_suffix") == ["review"]
    assert objects("procedural_keyword_stem") == ["review"]


def test_decode_modal_ir_document_emits_condition_exception_scope_slots() -> None:
    decoded = decode_modal_ir_document(_typed_clause_scope_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["condition"] == ["provided that the applicant submits annual reports"]
    assert slot_map["condition_token_count"] == ["7"]
    assert slot_map["condition_prefix"] == ["provided that"]
    assert slot_map["condition_prefix_key"] == ["provided_that"]
    assert slot_map["condition_modal_signature"] == ["deontic:O:provided_that"]
    assert slot_map["condition_modal_family"] == ["deontic"]
    assert slot_map["condition_modal_operator"] == ["O"]
    assert slot_map["condition_modal_lexeme"] == ["provided_that"]
    assert slot_map["condition_provided_that"] == ["the applicant submits annual reports"]
    assert slot_map["condition_scope"] == ["the applicant submits annual reports"]
    assert slot_map["condition_scope_token_suffix"] == ["reports"]
    assert slot_map["exception"] == ["except as otherwise provided in subsection (b)"]
    assert slot_map["exception_token_count"] == ["7"]
    assert slot_map["exception_prefix"] == ["except as otherwise provided"]
    assert slot_map["exception_prefix_key"] == ["except_as_otherwise_provided"]
    assert slot_map["exception_modal_signature"] == [
        "deontic:O:except_as_otherwise_provided"
    ]
    assert slot_map["exception_modal_family"] == ["deontic"]
    assert slot_map["exception_modal_operator"] == ["O"]
    assert slot_map["exception_modal_lexeme"] == ["except_as_otherwise_provided"]
    assert slot_map["exception_except_as_otherwise_provided"] == ["in subsection (b)"]
    assert slot_map["exception_scope"] == ["in subsection (b)"]
    assert slot_map["exception_scope_token_count"] == ["3"]
    assert slot_map["exception_scope_token_suffix"] == ["(b)"]


def test_modal_ir_to_flogic_triples_emits_condition_exception_scope_slots() -> None:
    triples = modal_ir_to_flogic_triples(_typed_clause_scope_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("condition") == ["provided that the applicant submits annual reports"]
    assert objects("condition_token_count") == ["7"]
    assert objects("condition_prefix") == ["provided that"]
    assert objects("condition_prefix_key") == ["provided_that"]
    assert objects("condition_modal_signature") == ["deontic:O:provided_that"]
    assert objects("condition_modal_family") == ["deontic"]
    assert objects("condition_modal_operator") == ["O"]
    assert objects("condition_modal_lexeme") == ["provided_that"]
    assert objects("condition_provided_that") == ["the applicant submits annual reports"]
    assert objects("condition_scope") == ["the applicant submits annual reports"]
    assert objects("condition_scope_token_suffix") == ["reports"]
    assert objects("exception") == ["except as otherwise provided in subsection (b)"]
    assert objects("exception_token_count") == ["7"]
    assert objects("exception_prefix") == ["except as otherwise provided"]
    assert objects("exception_prefix_key") == ["except_as_otherwise_provided"]
    assert objects("exception_modal_signature") == [
        "deontic:O:except_as_otherwise_provided"
    ]
    assert objects("exception_modal_family") == ["deontic"]
    assert objects("exception_modal_operator") == ["O"]
    assert objects("exception_modal_lexeme") == ["except_as_otherwise_provided"]
    assert objects("exception_except_as_otherwise_provided") == ["in subsection (b)"]
    assert objects("exception_scope") == ["in subsection (b)"]
    assert objects("exception_scope_token_count") == ["3"]
    assert objects("exception_scope_token_suffix") == ["(b)"]


def test_decode_modal_ir_document_emits_condition_proxy_slots_for_exception_only_formula() -> None:
    decoded = decode_modal_ir_document(_exception_only_condition_proxy_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["condition"] == ["except as such a determination applies"]
    assert slot_map["condition_prefix"] == ["except as"]
    assert slot_map["condition_prefix_key"] == ["except_as"]
    assert slot_map["condition_modal_signature"] == ["deontic:O|:except_as"]
    assert slot_map["condition_scope"] == ["such a determination applies"]
    assert slot_map["condition_scope_alnum_segment"] == [
        "such",
        "a",
        "determination",
        "applies",
    ]
    assert slot_map["condition_scope_alnum_segment_count"] == ["4"]
    assert slot_map["cue_modal_conditional_normative"] == ["O|:may"]
    assert slot_map["cue_conditional_normative"] == ["O|:may"]
    assert slot_map["modal_cue_conditional_normative"] == ["O|:may"]
    assert slot_map["condition_modal_conditional_normative"] == ["O|:except_as"]
    assert slot_map["condition_conditional_normative"] == ["O|:except_as"]


def test_modal_ir_to_flogic_triples_emits_condition_proxy_slots_for_exception_only_formula() -> None:
    triples = modal_ir_to_flogic_triples(_exception_only_condition_proxy_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("condition") == ["except as such a determination applies"]
    assert objects("condition_prefix") == ["except as"]
    assert objects("condition_prefix_key") == ["except_as"]
    assert objects("condition_modal_signature") == ["deontic:O|:except_as"]
    assert objects("condition_scope") == ["such a determination applies"]
    assert objects("condition_scope_alnum_segment") == [
        "such",
        "a",
        "determination",
        "applies",
    ]
    assert objects("condition_scope_alnum_segment_count") == ["4"]
    assert objects("cue_modal_conditional_normative") == ["O|:may"]
    assert objects("cue_conditional_normative") == ["O|:may"]
    assert objects("modal_cue_conditional_normative") == ["O|:may"]
    assert objects("condition_modal_conditional_normative") == ["O|:except_as"]
    assert objects("condition_conditional_normative") == ["O|:except_as"]


def test_decode_modal_ir_document_emits_cue_modal_signature_and_temporal_prefix_slots() -> None:
    decoded = decode_modal_ir_document(_cue_signature_temporal_clause_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["cue_modal_signature"] == [
        "deontic:O:shall",
        "temporal:F:by",
        "temporal:F:after",
    ]
    assert slot_map["cue_modal_canonical_signature"] == [
        "deontic:O:shall",
        "temporal:F:by",
        "temporal:X:after",
    ]
    assert slot_map["cue_modal_family"] == ["deontic", "temporal"]
    assert slot_map["cue_modal_operator"] == ["O", "F"]
    assert slot_map["cue_modal_canonical_operator"] == ["O", "F", "X"]
    assert slot_map["cue_modal_lexeme"] == ["shall", "by", "after"]
    assert slot_map["cue_modal_operator_alignment"] == ["aligned", "divergent"]
    assert slot_map["cue_modal_temporal_relation"] == ["deadline", "after"]
    assert slot_map["modal_cue"] == ["shall", "by", "after"]
    assert slot_map["modal_cue_signature"] == [
        "deontic:O:shall",
        "temporal:F:by",
        "temporal:F:after",
    ]
    assert slot_map["modal_cue_canonical_signature"] == [
        "deontic:O:shall",
        "temporal:F:by",
        "temporal:X:after",
    ]
    assert slot_map["modal_cue_family"] == ["deontic", "temporal"]
    assert slot_map["modal_cue_operator"] == ["O", "F"]
    assert slot_map["modal_cue_canonical_operator"] == ["O", "F", "X"]
    assert slot_map["modal_cue_lexeme"] == ["shall", "by", "after"]
    assert slot_map["modal_cue_operator_alignment"] == ["aligned", "divergent"]
    assert slot_map["modal_cue_temporal_relation"] == ["deadline", "after"]
    assert slot_map["condition_prefix_key"] == ["if", "after", "by"]
    assert slot_map["condition_modal_signature"] == [
        "deontic:O:if",
        "temporal:F:after",
        "temporal:F:by",
    ]
    assert slot_map["condition_modal_canonical_signature"] == [
        "temporal:X:after",
        "temporal:F:by",
    ]
    assert slot_map["condition_modal_family"] == ["deontic", "temporal"]
    assert slot_map["condition_modal_operator"] == ["O", "F"]
    assert slot_map["condition_modal_canonical_operator"] == ["X", "F"]
    assert slot_map["condition_modal_lexeme"] == ["if", "after", "by"]
    assert slot_map["condition_modal_operator_alignment"] == ["divergent", "aligned"]
    assert slot_map["condition_modal_temporal_relation"] == ["after", "deadline"]
    assert slot_map["condition_after"] == ["the agency receives notice"]
    assert slot_map["condition_by"] == ["march 1"]
    assert slot_map["condition_prefix_family"] == ["temporal"]
    assert slot_map["condition_prefix_temporal_relation"] == ["after", "deadline"]


def test_modal_ir_to_flogic_triples_emits_cue_modal_signature_and_temporal_prefix_slots() -> None:
    triples = modal_ir_to_flogic_triples(_cue_signature_temporal_clause_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("cue_modal_signature") == [
        "deontic:O:shall",
        "temporal:F:by",
        "temporal:F:after",
    ]
    assert objects("cue_modal_canonical_signature") == [
        "deontic:O:shall",
        "temporal:F:by",
        "temporal:X:after",
    ]
    assert objects("cue_modal_family") == ["deontic", "temporal"]
    assert objects("cue_modal_operator") == ["O", "F"]
    assert objects("cue_modal_canonical_operator") == ["O", "F", "X"]
    assert objects("cue_modal_lexeme") == ["shall", "by", "after"]
    assert objects("cue_modal_operator_alignment") == [
        "aligned",
        "aligned",
        "divergent",
    ]
    assert objects("cue_modal_temporal_relation") == ["deadline", "after"]
    assert objects("modal_cue") == ["shall", "by", "after"]
    assert objects("modal_cue_signature") == [
        "deontic:O:shall",
        "temporal:F:by",
        "temporal:F:after",
    ]
    assert objects("modal_cue_canonical_signature") == [
        "deontic:O:shall",
        "temporal:F:by",
        "temporal:X:after",
    ]
    assert objects("modal_cue_family") == ["deontic", "temporal"]
    assert objects("modal_cue_operator") == ["O", "F"]
    assert objects("modal_cue_canonical_operator") == ["O", "F", "X"]
    assert objects("modal_cue_lexeme") == ["shall", "by", "after"]
    assert objects("modal_cue_operator_alignment") == [
        "aligned",
        "aligned",
        "divergent",
    ]
    assert objects("modal_cue_temporal_relation") == ["deadline", "after"]
    assert objects("condition_prefix_key") == ["if", "after", "by"]
    assert objects("condition_modal_signature") == [
        "deontic:O:if",
        "temporal:F:after",
        "temporal:F:by",
    ]
    assert objects("condition_modal_canonical_signature") == [
        "temporal:X:after",
        "temporal:F:by",
    ]
    assert objects("condition_modal_family") == ["deontic", "temporal"]
    assert objects("condition_modal_operator") == ["O", "F"]
    assert objects("condition_modal_canonical_operator") == ["X", "F"]
    assert objects("condition_modal_lexeme") == ["if", "after", "by"]
    assert objects("condition_modal_operator_alignment") == ["divergent", "aligned"]
    assert objects("condition_modal_temporal_relation") == ["after", "deadline"]
    assert objects("condition_after") == ["the agency receives notice"]
    assert objects("condition_by") == ["march 1"]
    assert objects("condition_prefix_family") == ["temporal"]
    assert objects("condition_prefix_temporal_relation") == ["after", "deadline"]


def test_decode_modal_ir_document_emits_temporal_until_canonical_slots() -> None:
    decoded = decode_modal_ir_document(_temporal_until_clause_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["condition_prefix_key"] == ["until"]
    assert slot_map["condition_prefix_temporal_relation"] == ["until"]
    assert slot_map["condition_modal_signature"] == ["temporal:F:until"]
    assert slot_map["condition_modal_canonical_signature"] == ["temporal:G:until"]
    assert slot_map["condition_modal_operator"] == ["F"]
    assert slot_map["condition_modal_canonical_operator"] == ["G"]
    assert slot_map["condition_modal_operator_alignment"] == ["divergent"]
    assert slot_map["cue_modal_signature"] == ["temporal:F:until"]
    assert slot_map["cue_modal_canonical_signature"] == ["temporal:G:until"]
    assert slot_map["cue_modal_operator"] == ["F"]
    assert slot_map["cue_modal_canonical_operator"] == ["G"]
    assert slot_map["cue_modal_operator_alignment"] == ["divergent"]


def test_modal_ir_to_flogic_triples_emits_temporal_until_canonical_slots() -> None:
    triples = modal_ir_to_flogic_triples(_temporal_until_clause_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("condition_prefix_key") == ["until"]
    assert objects("condition_prefix_temporal_relation") == ["until"]
    assert objects("condition_modal_signature") == ["temporal:F:until"]
    assert objects("condition_modal_canonical_signature") == ["temporal:G:until"]
    assert objects("condition_modal_operator") == ["F"]
    assert objects("condition_modal_canonical_operator") == ["G"]
    assert objects("condition_modal_operator_alignment") == ["divergent"]
    assert objects("cue_modal_signature") == ["temporal:F:until"]
    assert objects("cue_modal_canonical_signature") == ["temporal:G:until"]
    assert objects("cue_modal_operator") == ["F"]
    assert objects("cue_modal_canonical_operator") == ["G"]
    assert objects("cue_modal_operator_alignment") == ["divergent"]


def test_decode_modal_ir_document_derives_modal_cue_from_fallback_frame_predicate() -> None:
    decoded = decode_modal_ir_document(_fallback_frame_authority_cue_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["cue"] == ["__uscode_section_heading_fallback__", "authority"]
    assert slot_map["modal_cue"] == ["__uscode_section_heading_fallback__", "authority"]
    assert slot_map["modal_cue_signature"] == [
        "frame:Frame:__uscode_section_heading_fallback__",
        "frame:Frame:authority",
    ]
    assert slot_map["modal_cue_lexeme"] == ["__uscode_section_heading_fallback__", "authority"]


def test_modal_ir_to_flogic_triples_derives_modal_cue_from_fallback_frame_predicate() -> None:
    triples = modal_ir_to_flogic_triples(_fallback_frame_authority_cue_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("modal_cue") == ["__uscode_section_heading_fallback__", "authority"]
    assert objects("modal_cue_signature") == [
        "frame:Frame:__uscode_section_heading_fallback__",
        "frame:Frame:authority",
    ]
    assert objects("modal_cue_lexeme") == ["__uscode_section_heading_fallback__", "authority"]


def test_decode_modal_ir_document_emits_citation_source_id_alignment_slots() -> None:
    aligned_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_sample_document())
    )
    mismatch_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_provenance_alignment_mismatch_sample_document())
    )
    punct_mismatch_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(
            _provenance_alignment_trailing_punct_mismatch_sample_document()
        )
    )
    range_aligned_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_numeric_range_sample_document())
    )
    range_connector_mismatch_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_range_connector_mismatch_sample_document())
    )

    assert aligned_slot_map["citation_source_id_alignment"] == ["exact_match"]
    assert aligned_slot_map["citation_source_id_title_match"] == ["true"]
    assert aligned_slot_map["citation_source_id_section_match"] == ["true"]
    assert aligned_slot_map["citation_source_id_title_section_key_match"] == ["true"]
    assert aligned_slot_map["citation_source_id_canonical_match"] == ["true"]
    assert aligned_slot_map["citation_source_id_title_pair"] == ["21|21"]
    assert aligned_slot_map["citation_source_id_section_pair"] == ["360bbb-0|360bbb-0"]
    assert aligned_slot_map["citation_source_id_title_section_key_pair"] == [
        "21:360bbb-0|21:360bbb-0"
    ]
    assert aligned_slot_map["citation_source_id_canonical_pair"] == [
        "21 U.S.C. 360bbb-0|21 U.S.C. 360bbb-0"
    ]
    assert aligned_slot_map["citation_source_id_title_number_relation"] == ["equal"]
    assert aligned_slot_map["citation_source_id_title_number_span"] == ["0"]
    assert (
        aligned_slot_map[
            "citation_source_id_title_number_signature_leading_digit_pair"
        ]
        == ["2|2"]
    )
    assert (
        aligned_slot_map[
            "citation_source_id_title_number_signature_leading_digit_match"
        ]
        == ["true"]
    )
    assert aligned_slot_map["citation_source_id_section_primary_number_relation"] == [
        "equal"
    ]
    assert aligned_slot_map["citation_source_id_section_primary_number_span"] == ["0"]
    assert (
        aligned_slot_map[
            "citation_source_id_section_primary_number_signature_zero_digit_count_pair"
        ]
        == ["1|1"]
    )
    assert (
        aligned_slot_map[
            "citation_source_id_section_primary_number_signature_zero_digit_count_match"
        ]
        == ["true"]
    )
    assert aligned_slot_map["citation_source_id_section_primary_suffix_pair"] == [
        "bbb|bbb"
    ]
    assert aligned_slot_map["citation_source_id_section_primary_suffix_match"] == ["true"]
    assert (
        aligned_slot_map["citation_source_id_section_primary_suffix_presence_match"]
        == ["true"]
    )
    assert (
        aligned_slot_map["citation_source_id_section_primary_component_signature_match"]
        == ["true"]
    )
    assert (
        aligned_slot_map["citation_source_id_section_primary_component_signature_pair"]
        == ["N3A3|N3A3"]
    )
    assert aligned_slot_map["citation_source_id_section_raw_match"] == ["true"]
    assert aligned_slot_map["citation_source_id_section_raw_pair"] == [
        "360bbb-0|360bbb-0"
    ]
    assert (
        aligned_slot_map["citation_source_id_section_trailing_punct_presence_match"]
        == ["true"]
    )
    assert aligned_slot_map["citation_source_id_section_trailing_punct_match"] == [
        "true"
    ]
    assert aligned_slot_map["citation_source_id_section_trailing_punct_pair"] == [
        "none|none"
    ]
    assert aligned_slot_map["citation_source_id_section_style_pair"] == [
        (
            f"{aligned_slot_map['source_id_section_style'][0]}|"
            f"{aligned_slot_map['citation_section_style'][0]}"
        )
    ]
    assert aligned_slot_map["citation_source_id_section_style_match"] == ["true"]
    assert aligned_slot_map["citation_source_id_section_style_presence_match"] == [
        "true"
    ]
    assert aligned_slot_map["citation_source_id_section_suffix_style_pair"] == [
        (
            f"{aligned_slot_map['source_id_section_suffix_style'][0]}|"
            f"{aligned_slot_map['citation_section_suffix_style'][0]}"
        )
    ]
    assert aligned_slot_map["citation_source_id_section_suffix_style_match"] == [
        "true"
    ]
    assert aligned_slot_map[
        "citation_source_id_section_suffix_style_presence_match"
    ] == ["true"]
    assert aligned_slot_map["citation_source_id_section_punctuation_style_pair"] == [
        (
            f"{aligned_slot_map['source_id_section_punctuation_style'][0]}|"
            f"{aligned_slot_map['citation_section_punctuation_style'][0]}"
        )
    ]
    assert aligned_slot_map["citation_source_id_section_punctuation_style_match"] == [
        "true"
    ]
    assert aligned_slot_map[
        "citation_source_id_section_punctuation_style_presence_match"
    ] == ["true"]

    assert mismatch_slot_map["citation_source_id_alignment"] == ["title_only_match"]
    assert mismatch_slot_map["citation_source_id_title_match"] == ["true"]
    assert mismatch_slot_map["citation_source_id_section_match"] == ["false"]
    assert mismatch_slot_map["citation_source_id_title_section_key_match"] == ["false"]
    assert mismatch_slot_map["citation_source_id_canonical_match"] == ["false"]
    assert mismatch_slot_map["citation_source_id_title_pair"] == ["20|20"]
    assert mismatch_slot_map["citation_source_id_section_pair"] == ["1131d|1131e"]
    assert mismatch_slot_map["citation_source_id_title_section_key_pair"] == [
        "20:1131d|20:1131e"
    ]
    assert mismatch_slot_map["citation_source_id_canonical_pair"] == [
        "20 U.S.C. 1131d|20 U.S.C. 1131e"
    ]
    assert mismatch_slot_map["citation_source_id_title_number_relation"] == ["equal"]
    assert mismatch_slot_map["citation_source_id_title_number_span"] == ["0"]
    assert (
        mismatch_slot_map[
            "citation_source_id_title_number_signature_parity_pair"
        ]
        == ["even|even"]
    )
    assert (
        mismatch_slot_map[
            "citation_source_id_title_number_signature_parity_match"
        ]
        == ["true"]
    )
    assert mismatch_slot_map["citation_source_id_section_primary_number_relation"] == [
        "equal"
    ]
    assert mismatch_slot_map["citation_source_id_section_primary_number_span"] == ["0"]
    assert (
        mismatch_slot_map[
            "citation_source_id_section_primary_number_signature_has_zero_digit_pair"
        ]
        == ["false|false"]
    )
    assert (
        mismatch_slot_map[
            "citation_source_id_section_primary_number_signature_has_zero_digit_match"
        ]
        == ["true"]
    )
    assert mismatch_slot_map["citation_source_id_section_primary_suffix_pair"] == [
        "d|e"
    ]
    assert mismatch_slot_map["citation_source_id_section_primary_suffix_match"] == [
        "false"
    ]
    assert (
        mismatch_slot_map["citation_source_id_section_primary_suffix_presence_match"]
        == ["true"]
    )
    assert (
        mismatch_slot_map["citation_source_id_section_primary_component_signature_match"]
        == ["true"]
    )
    assert (
        mismatch_slot_map["citation_source_id_section_primary_component_signature_pair"]
        == ["N4A1|N4A1"]
    )
    assert mismatch_slot_map["citation_source_id_section_raw_match"] == ["false"]
    assert mismatch_slot_map["citation_source_id_section_raw_pair"] == ["1131d|1131e"]
    assert (
        mismatch_slot_map["citation_source_id_section_trailing_punct_presence_match"]
        == ["true"]
    )
    assert mismatch_slot_map["citation_source_id_section_trailing_punct_match"] == [
        "true"
    ]
    assert mismatch_slot_map["citation_source_id_section_trailing_punct_pair"] == [
        "none|none"
    ]
    assert mismatch_slot_map["citation_source_id_section_style_pair"] == [
        (
            f"{mismatch_slot_map['source_id_section_style'][0]}|"
            f"{mismatch_slot_map['citation_section_style'][0]}"
        )
    ]
    assert mismatch_slot_map["citation_source_id_section_style_match"] == ["true"]
    assert mismatch_slot_map["citation_source_id_section_style_presence_match"] == [
        "true"
    ]
    assert mismatch_slot_map["citation_source_id_section_suffix_style_pair"] == [
        (
            f"{mismatch_slot_map['source_id_section_suffix_style'][0]}|"
            f"{mismatch_slot_map['citation_section_suffix_style'][0]}"
        )
    ]
    assert mismatch_slot_map["citation_source_id_section_suffix_style_match"] == [
        "true"
    ]
    assert mismatch_slot_map[
        "citation_source_id_section_suffix_style_presence_match"
    ] == ["true"]
    assert mismatch_slot_map["citation_source_id_section_punctuation_style_pair"] == [
        (
            f"{mismatch_slot_map['source_id_section_punctuation_style'][0]}|"
            f"{mismatch_slot_map['citation_section_punctuation_style'][0]}"
        )
    ]
    assert mismatch_slot_map["citation_source_id_section_punctuation_style_match"] == [
        "true"
    ]
    assert mismatch_slot_map[
        "citation_source_id_section_punctuation_style_presence_match"
    ] == ["true"]

    assert punct_mismatch_slot_map["citation_source_id_alignment"] == ["exact_match"]
    assert punct_mismatch_slot_map["citation_source_id_title_match"] == ["true"]
    assert punct_mismatch_slot_map["citation_source_id_section_match"] == ["true"]
    assert punct_mismatch_slot_map["citation_source_id_title_section_key_match"] == [
        "true"
    ]
    assert punct_mismatch_slot_map["citation_source_id_canonical_match"] == ["true"]
    assert punct_mismatch_slot_map["citation_source_id_title_pair"] == ["46|46"]
    assert punct_mismatch_slot_map["citation_source_id_section_pair"] == ["10318|10318"]
    assert punct_mismatch_slot_map["citation_source_id_title_section_key_pair"] == [
        "46:10318|46:10318"
    ]
    assert punct_mismatch_slot_map["citation_source_id_canonical_pair"] == [
        "46 U.S.C. 10318|46 U.S.C. 10318"
    ]
    assert punct_mismatch_slot_map["citation_source_id_title_number_relation"] == [
        "equal"
    ]
    assert punct_mismatch_slot_map["citation_source_id_title_number_span"] == ["0"]
    assert (
        punct_mismatch_slot_map["citation_source_id_section_primary_number_relation"]
        == ["equal"]
    )
    assert punct_mismatch_slot_map["citation_source_id_section_primary_number_span"] == [
        "0"
    ]
    assert (
        punct_mismatch_slot_map[
            "citation_source_id_section_primary_number_signature_magnitude_bucket_pair"
        ]
        == ["10k_to_99k|10k_to_99k"]
    )
    assert (
        punct_mismatch_slot_map[
            "citation_source_id_section_primary_number_signature_magnitude_bucket_match"
        ]
        == ["true"]
    )
    assert punct_mismatch_slot_map["citation_source_id_section_primary_suffix_pair"] == [
        "none|none"
    ]
    assert punct_mismatch_slot_map["citation_source_id_section_primary_suffix_match"] == [
        "true"
    ]
    assert (
        punct_mismatch_slot_map[
            "citation_source_id_section_primary_suffix_presence_match"
        ]
        == ["true"]
    )
    assert (
        punct_mismatch_slot_map[
            "citation_source_id_section_primary_component_signature_match"
        ]
        == ["true"]
    )
    assert (
        punct_mismatch_slot_map[
            "citation_source_id_section_primary_component_signature_pair"
        ]
        == ["N5|N5"]
    )
    assert punct_mismatch_slot_map["citation_source_id_section_raw_match"] == ["false"]
    assert punct_mismatch_slot_map["citation_source_id_section_raw_pair"] == [
        "10318.|10318"
    ]
    assert (
        punct_mismatch_slot_map[
            "citation_source_id_section_trailing_punct_presence_match"
        ]
        == ["false"]
    )
    assert punct_mismatch_slot_map["citation_source_id_section_trailing_punct_match"] == [
        "false"
    ]
    assert punct_mismatch_slot_map["citation_source_id_section_trailing_punct_pair"] == [
        ".|none"
    ]
    assert punct_mismatch_slot_map["citation_source_id_section_style_pair"] == [
        (
            f"{punct_mismatch_slot_map['source_id_section_style'][0]}|"
            f"{punct_mismatch_slot_map['citation_section_style'][0]}"
        )
    ]
    assert punct_mismatch_slot_map["citation_source_id_section_style_match"] == [
        "false"
    ]
    assert punct_mismatch_slot_map["citation_source_id_section_style_presence_match"] == [
        "true"
    ]
    assert punct_mismatch_slot_map["citation_source_id_section_suffix_style_pair"] == [
        (
            f"{punct_mismatch_slot_map['source_id_section_suffix_style'][0]}|"
            f"{punct_mismatch_slot_map['citation_section_suffix_style'][0]}"
        )
    ]
    assert punct_mismatch_slot_map["citation_source_id_section_suffix_style_match"] == [
        "true"
    ]
    assert punct_mismatch_slot_map[
        "citation_source_id_section_suffix_style_presence_match"
    ] == ["true"]
    assert (
        punct_mismatch_slot_map["citation_source_id_section_punctuation_style_pair"]
        == [
            (
                f"{punct_mismatch_slot_map['source_id_section_punctuation_style'][0]}|"
                f"{punct_mismatch_slot_map['citation_section_punctuation_style'][0]}"
            )
        ]
    )
    assert (
        punct_mismatch_slot_map["citation_source_id_section_punctuation_style_match"]
        == ["false"]
    )
    assert (
        punct_mismatch_slot_map[
            "citation_source_id_section_punctuation_style_presence_match"
        ]
        == ["true"]
    )

    assert range_aligned_slot_map["citation_source_id_section_is_range_pair"] == [
        "true|true"
    ]
    assert range_aligned_slot_map["citation_source_id_section_is_range_match"] == [
        "true"
    ]
    assert range_aligned_slot_map["citation_source_id_section_range_start_pair"] == [
        "1381|1381"
    ]
    assert range_aligned_slot_map["citation_source_id_section_range_start_match"] == [
        "true"
    ]
    assert (
        range_aligned_slot_map["citation_source_id_section_range_start_presence_match"]
        == ["true"]
    )
    assert range_aligned_slot_map["citation_source_id_section_range_end_pair"] == [
        "1398|1398"
    ]
    assert range_aligned_slot_map["citation_source_id_section_range_end_match"] == [
        "true"
    ]
    assert (
        range_aligned_slot_map["citation_source_id_section_range_end_presence_match"]
        == ["true"]
    )
    assert range_aligned_slot_map["citation_source_id_section_range_connector_pair"] == [
        "to|to"
    ]
    assert range_aligned_slot_map["citation_source_id_section_range_connector_match"] == [
        "true"
    ]
    assert (
        range_aligned_slot_map[
            "citation_source_id_section_range_connector_presence_match"
        ]
        == ["true"]
    )
    assert range_aligned_slot_map["citation_source_id_section_style_match"] == ["true"]
    assert (
        range_aligned_slot_map["citation_source_id_section_suffix_style_match"]
        == ["true"]
    )
    assert (
        range_aligned_slot_map["citation_source_id_section_punctuation_style_match"]
        == ["true"]
    )

    assert range_connector_mismatch_slot_map["citation_source_id_alignment"] == [
        "title_only_match"
    ]
    assert (
        range_connector_mismatch_slot_map[
            "citation_source_id_section_range_start_pair"
        ]
        == ["4605|4605"]
    )
    assert (
        range_connector_mismatch_slot_map[
            "citation_source_id_section_range_start_match"
        ]
        == ["true"]
    )
    assert (
        range_connector_mismatch_slot_map[
            "citation_source_id_section_range_end_pair"
        ]
        == ["4610|4610"]
    )
    assert (
        range_connector_mismatch_slot_map[
            "citation_source_id_section_range_end_match"
        ]
        == ["true"]
    )
    assert (
        range_connector_mismatch_slot_map[
            "citation_source_id_section_range_connector_pair"
        ]
        == ["to|through"]
    )
    assert (
        range_connector_mismatch_slot_map[
            "citation_source_id_section_range_connector_match"
        ]
        == ["false"]
    )
    assert (
        range_connector_mismatch_slot_map[
            "citation_source_id_section_range_connector_presence_match"
        ]
        == ["true"]
    )
    assert range_connector_mismatch_slot_map[
        "citation_source_id_section_style_match"
    ] == ["true"]
    assert range_connector_mismatch_slot_map[
        "citation_source_id_section_suffix_style_match"
    ] == ["true"]
    assert range_connector_mismatch_slot_map[
        "citation_source_id_section_punctuation_style_match"
    ] == ["true"]


def test_modal_ir_to_flogic_triples_emits_citation_source_id_alignment_slots() -> None:
    aligned_triples = modal_ir_to_flogic_triples(_sample_document())
    mismatch_triples = modal_ir_to_flogic_triples(
        _provenance_alignment_mismatch_sample_document()
    )
    punct_mismatch_triples = modal_ir_to_flogic_triples(
        _provenance_alignment_trailing_punct_mismatch_sample_document()
    )
    range_aligned_triples = modal_ir_to_flogic_triples(_numeric_range_sample_document())
    range_connector_mismatch_triples = modal_ir_to_flogic_triples(
        _range_connector_mismatch_sample_document()
    )

    def objects(triples: list[dict[str, str]], predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects(aligned_triples, "citation_source_id_alignment") == ["exact_match"]
    assert objects(aligned_triples, "citation_source_id_title_match") == ["true"]
    assert objects(aligned_triples, "citation_source_id_section_match") == ["true"]
    assert objects(aligned_triples, "citation_source_id_title_section_key_match") == [
        "true"
    ]
    assert objects(aligned_triples, "citation_source_id_canonical_match") == ["true"]
    assert objects(aligned_triples, "citation_source_id_title_pair") == ["21|21"]
    assert objects(aligned_triples, "citation_source_id_section_pair") == [
        "360bbb-0|360bbb-0"
    ]
    assert objects(aligned_triples, "citation_source_id_title_section_key_pair") == [
        "21:360bbb-0|21:360bbb-0"
    ]
    assert objects(aligned_triples, "citation_source_id_canonical_pair") == [
        "21 U.S.C. 360bbb-0|21 U.S.C. 360bbb-0"
    ]
    assert objects(aligned_triples, "citation_source_id_title_number_relation") == [
        "equal"
    ]
    assert objects(aligned_triples, "citation_source_id_title_number_span") == ["0"]
    assert objects(
        aligned_triples,
        "citation_source_id_title_number_signature_leading_digit_pair",
    ) == ["2|2"]
    assert objects(
        aligned_triples,
        "citation_source_id_title_number_signature_leading_digit_match",
    ) == ["true"]
    assert objects(
        aligned_triples,
        "citation_source_id_section_primary_number_relation",
    ) == ["equal"]
    assert objects(aligned_triples, "citation_source_id_section_primary_number_span") == [
        "0"
    ]
    assert objects(
        aligned_triples,
        "citation_source_id_section_primary_number_signature_zero_digit_count_pair",
    ) == ["1|1"]
    assert objects(
        aligned_triples,
        "citation_source_id_section_primary_number_signature_zero_digit_count_match",
    ) == ["true"]
    assert objects(aligned_triples, "citation_source_id_section_primary_suffix_pair") == [
        "bbb|bbb"
    ]
    assert objects(aligned_triples, "citation_source_id_section_primary_suffix_match") == [
        "true"
    ]
    assert objects(
        aligned_triples,
        "citation_source_id_section_primary_suffix_presence_match",
    ) == ["true"]
    assert objects(
        aligned_triples,
        "citation_source_id_section_primary_component_signature_match",
    ) == ["true"]
    assert objects(
        aligned_triples,
        "citation_source_id_section_primary_component_signature_pair",
    ) == ["N3A3|N3A3"]
    assert objects(aligned_triples, "citation_source_id_section_raw_match") == ["true"]
    assert objects(aligned_triples, "citation_source_id_section_raw_pair") == [
        "360bbb-0|360bbb-0"
    ]
    assert objects(
        aligned_triples,
        "citation_source_id_section_trailing_punct_presence_match",
    ) == ["true"]
    assert objects(aligned_triples, "citation_source_id_section_trailing_punct_match") == [
        "true"
    ]
    assert objects(aligned_triples, "citation_source_id_section_trailing_punct_pair") == [
        "none|none"
    ]
    assert objects(aligned_triples, "citation_source_id_section_style_match") == [
        "true"
    ]
    assert objects(
        aligned_triples,
        "citation_source_id_section_style_presence_match",
    ) == ["true"]
    assert objects(
        aligned_triples,
        "citation_source_id_section_suffix_style_match",
    ) == ["true"]
    assert objects(
        aligned_triples,
        "citation_source_id_section_suffix_style_presence_match",
    ) == ["true"]
    assert objects(
        aligned_triples,
        "citation_source_id_section_punctuation_style_match",
    ) == ["true"]
    assert objects(
        aligned_triples,
        "citation_source_id_section_punctuation_style_presence_match",
    ) == ["true"]

    assert objects(mismatch_triples, "citation_source_id_alignment") == [
        "title_only_match"
    ]
    assert objects(mismatch_triples, "citation_source_id_title_match") == ["true"]
    assert objects(mismatch_triples, "citation_source_id_section_match") == ["false"]
    assert objects(
        mismatch_triples,
        "citation_source_id_title_section_key_match",
    ) == ["false"]
    assert objects(mismatch_triples, "citation_source_id_canonical_match") == ["false"]
    assert objects(mismatch_triples, "citation_source_id_title_pair") == ["20|20"]
    assert objects(mismatch_triples, "citation_source_id_section_pair") == [
        "1131d|1131e"
    ]
    assert objects(
        mismatch_triples,
        "citation_source_id_title_section_key_pair",
    ) == ["20:1131d|20:1131e"]
    assert objects(mismatch_triples, "citation_source_id_canonical_pair") == [
        "20 U.S.C. 1131d|20 U.S.C. 1131e"
    ]
    assert objects(mismatch_triples, "citation_source_id_title_number_relation") == [
        "equal"
    ]
    assert objects(mismatch_triples, "citation_source_id_title_number_span") == ["0"]
    assert objects(
        mismatch_triples,
        "citation_source_id_title_number_signature_parity_pair",
    ) == ["even|even"]
    assert objects(
        mismatch_triples,
        "citation_source_id_title_number_signature_parity_match",
    ) == ["true"]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_primary_number_relation",
    ) == ["equal"]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_primary_number_span",
    ) == ["0"]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_primary_number_signature_has_zero_digit_pair",
    ) == ["false|false"]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_primary_number_signature_has_zero_digit_match",
    ) == ["true"]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_primary_suffix_pair",
    ) == ["d|e"]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_primary_suffix_match",
    ) == ["false"]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_primary_suffix_presence_match",
    ) == ["true"]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_primary_component_signature_match",
    ) == ["true"]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_primary_component_signature_pair",
    ) == ["N4A1|N4A1"]
    assert objects(mismatch_triples, "citation_source_id_section_raw_match") == ["false"]
    assert objects(mismatch_triples, "citation_source_id_section_raw_pair") == [
        "1131d|1131e"
    ]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_trailing_punct_presence_match",
    ) == ["true"]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_trailing_punct_match",
    ) == ["true"]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_trailing_punct_pair",
    ) == ["none|none"]
    assert objects(mismatch_triples, "citation_source_id_section_style_match") == [
        "true"
    ]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_style_presence_match",
    ) == ["true"]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_suffix_style_match",
    ) == ["true"]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_suffix_style_presence_match",
    ) == ["true"]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_punctuation_style_match",
    ) == ["true"]
    assert objects(
        mismatch_triples,
        "citation_source_id_section_punctuation_style_presence_match",
    ) == ["true"]

    assert objects(punct_mismatch_triples, "citation_source_id_alignment") == [
        "exact_match"
    ]
    assert objects(punct_mismatch_triples, "citation_source_id_title_match") == ["true"]
    assert objects(punct_mismatch_triples, "citation_source_id_section_match") == ["true"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_title_section_key_match",
    ) == ["true"]
    assert objects(punct_mismatch_triples, "citation_source_id_canonical_match") == [
        "true"
    ]
    assert objects(punct_mismatch_triples, "citation_source_id_title_pair") == ["46|46"]
    assert objects(punct_mismatch_triples, "citation_source_id_section_pair") == [
        "10318|10318"
    ]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_title_section_key_pair",
    ) == ["46:10318|46:10318"]
    assert objects(punct_mismatch_triples, "citation_source_id_canonical_pair") == [
        "46 U.S.C. 10318|46 U.S.C. 10318"
    ]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_title_number_relation",
    ) == ["equal"]
    assert objects(punct_mismatch_triples, "citation_source_id_title_number_span") == [
        "0"
    ]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_primary_number_relation",
    ) == ["equal"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_primary_number_span",
    ) == ["0"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_primary_number_signature_magnitude_bucket_pair",
    ) == ["10k_to_99k|10k_to_99k"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_primary_number_signature_magnitude_bucket_match",
    ) == ["true"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_primary_suffix_pair",
    ) == ["none|none"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_primary_suffix_match",
    ) == ["true"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_primary_suffix_presence_match",
    ) == ["true"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_primary_component_signature_match",
    ) == ["true"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_primary_component_signature_pair",
    ) == ["N5|N5"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_raw_match",
    ) == ["false"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_raw_pair",
    ) == ["10318.|10318"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_trailing_punct_presence_match",
    ) == ["false"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_trailing_punct_match",
    ) == ["false"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_trailing_punct_pair",
    ) == [".|none"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_style_match",
    ) == ["false"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_style_presence_match",
    ) == ["true"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_suffix_style_match",
    ) == ["true"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_suffix_style_presence_match",
    ) == ["true"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_punctuation_style_match",
    ) == ["false"]
    assert objects(
        punct_mismatch_triples,
        "citation_source_id_section_punctuation_style_presence_match",
    ) == ["true"]

    assert objects(
        range_aligned_triples,
        "citation_source_id_section_is_range_pair",
    ) == ["true|true"]
    assert objects(
        range_aligned_triples,
        "citation_source_id_section_is_range_match",
    ) == ["true"]
    assert objects(
        range_aligned_triples,
        "citation_source_id_section_range_start_pair",
    ) == ["1381|1381"]
    assert objects(
        range_aligned_triples,
        "citation_source_id_section_range_start_match",
    ) == ["true"]
    assert objects(
        range_aligned_triples,
        "citation_source_id_section_range_start_presence_match",
    ) == ["true"]
    assert objects(
        range_aligned_triples,
        "citation_source_id_section_range_end_pair",
    ) == ["1398|1398"]
    assert objects(
        range_aligned_triples,
        "citation_source_id_section_range_end_match",
    ) == ["true"]
    assert objects(
        range_aligned_triples,
        "citation_source_id_section_range_end_presence_match",
    ) == ["true"]
    assert objects(
        range_aligned_triples,
        "citation_source_id_section_range_connector_pair",
    ) == ["to|to"]
    assert objects(
        range_aligned_triples,
        "citation_source_id_section_range_connector_match",
    ) == ["true"]
    assert objects(
        range_aligned_triples,
        "citation_source_id_section_range_connector_presence_match",
    ) == ["true"]
    assert objects(
        range_aligned_triples,
        "citation_source_id_section_style_match",
    ) == ["true"]
    assert objects(
        range_aligned_triples,
        "citation_source_id_section_suffix_style_match",
    ) == ["true"]
    assert objects(
        range_aligned_triples,
        "citation_source_id_section_punctuation_style_match",
    ) == ["true"]

    assert objects(
        range_connector_mismatch_triples,
        "citation_source_id_alignment",
    ) == ["title_only_match"]
    assert objects(
        range_connector_mismatch_triples,
        "citation_source_id_section_range_start_pair",
    ) == ["4605|4605"]
    assert objects(
        range_connector_mismatch_triples,
        "citation_source_id_section_range_start_match",
    ) == ["true"]
    assert objects(
        range_connector_mismatch_triples,
        "citation_source_id_section_range_end_pair",
    ) == ["4610|4610"]
    assert objects(
        range_connector_mismatch_triples,
        "citation_source_id_section_range_end_match",
    ) == ["true"]
    assert objects(
        range_connector_mismatch_triples,
        "citation_source_id_section_range_connector_pair",
    ) == ["to|through"]
    assert objects(
        range_connector_mismatch_triples,
        "citation_source_id_section_range_connector_match",
    ) == ["false"]
    assert objects(
        range_connector_mismatch_triples,
        "citation_source_id_section_range_connector_presence_match",
    ) == ["true"]
    assert objects(
        range_connector_mismatch_triples,
        "citation_source_id_section_style_match",
    ) == ["true"]
    assert objects(
        range_connector_mismatch_triples,
        "citation_source_id_section_suffix_style_match",
    ) == ["true"]
    assert objects(
        range_connector_mismatch_triples,
        "citation_source_id_section_punctuation_style_match",
    ) == ["true"]


def test_decode_modal_ir_document_emits_section_structure_composite_slots() -> None:
    single_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_single_component_sample_document())
    )
    assert single_slot_map["citation_section_profile_signature"] == [
        "single_alphanumeric:N3A1"
    ]
    assert single_slot_map["citation_section_profile_signature_normalized"] == [
        "single_alphanumeric:n3a1"
    ]
    assert single_slot_map["citation_title_section_signature"] == ["2:N3A1"]
    assert single_slot_map["citation_title_section_signature_normalized"] == ["2:n3a1"]
    assert single_slot_map["citation_title_section_profile"] == [
        "2:single_alphanumeric"
    ]
    assert single_slot_map["citation_section_profile_signature_token_count"] == ["3"]
    assert single_slot_map["citation_section_profile_signature_token_prefix"] == [
        "single"
    ]
    assert single_slot_map["citation_title_section_signature_token_count"] == ["2"]
    assert single_slot_map["citation_title_section_signature_has_mixed_token"] == [
        "true"
    ]
    assert single_slot_map["citation_title_section_profile_token_suffix"] == [
        "alphanumeric"
    ]
    assert single_slot_map["source_id_section_profile_signature"] == [
        "single_alphanumeric:N3A1"
    ]
    assert single_slot_map["source_id_title_section_signature"] == ["2:N3A1"]
    assert single_slot_map["source_id_title_section_profile"] == [
        "2:single_alphanumeric"
    ]
    assert single_slot_map["source_id_section_profile_signature_token_count"] == ["3"]
    assert single_slot_map["source_id_title_section_signature_token_count"] == ["2"]
    assert single_slot_map["source_id_title_section_profile_token_suffix"] == [
        "alphanumeric"
    ]
    assert single_slot_map["citation_source_id_section_signature_pair"] == [
        "N3A1|N3A1"
    ]
    assert single_slot_map["citation_source_id_section_signature_match"] == ["true"]
    assert single_slot_map["citation_source_id_section_profile_pair"] == [
        "single_alphanumeric|single_alphanumeric"
    ]
    assert single_slot_map["citation_source_id_section_profile_match"] == ["true"]
    assert single_slot_map["citation_source_id_title_section_signature_pair"] == [
        "2:n3a1|2:n3a1"
    ]
    assert single_slot_map["citation_source_id_title_section_signature_match"] == [
        "true"
    ]
    assert single_slot_map["citation_source_id_title_section_profile_pair"] == [
        "2:single_alphanumeric|2:single_alphanumeric"
    ]
    assert single_slot_map["citation_source_id_title_section_profile_match"] == [
        "true"
    ]

    compound_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_compound_alpha_suffix_hyphen_sample_document())
    )
    assert compound_slot_map["citation_section_profile_signature"] == [
        "compound_mixed:N3A3-N1"
    ]
    assert compound_slot_map["citation_title_section_signature"] == ["16:N3A3-N1"]
    assert compound_slot_map["citation_title_section_profile"] == ["16:compound_mixed"]
    assert compound_slot_map["citation_title_section_signature_token_count"] == ["3"]
    assert compound_slot_map["citation_title_section_signature_token_suffix"] == [
        "n1"
    ]
    assert compound_slot_map["citation_title_section_profile_token_suffix"] == [
        "mixed"
    ]
    assert compound_slot_map["source_id_section_profile_signature"] == [
        "compound_mixed:N3A3-N1"
    ]
    assert compound_slot_map["source_id_title_section_signature"] == ["16:N3A3-N1"]
    assert compound_slot_map["source_id_title_section_profile"] == ["16:compound_mixed"]
    assert compound_slot_map["source_id_title_section_signature_token_count"] == ["3"]
    assert compound_slot_map["source_id_title_section_profile_token_suffix"] == [
        "mixed"
    ]


def test_modal_ir_to_flogic_triples_emits_section_structure_composite_slots() -> None:
    single_triples = modal_ir_to_flogic_triples(_single_component_sample_document())
    compound_triples = modal_ir_to_flogic_triples(
        _compound_alpha_suffix_hyphen_sample_document()
    )

    def objects(triples: list[dict[str, str]], predicate: str) -> list[str]:
        return [triple["object"] for triple in triples if triple.get("predicate") == predicate]

    assert objects(single_triples, "citation_section_profile_signature") == [
        "single_alphanumeric:N3A1"
    ]
    assert objects(single_triples, "citation_section_profile_signature_normalized") == [
        "single_alphanumeric:n3a1"
    ]
    assert objects(single_triples, "citation_title_section_signature") == ["2:N3A1"]
    assert objects(single_triples, "citation_title_section_signature_normalized") == [
        "2:n3a1"
    ]
    assert objects(single_triples, "citation_title_section_profile") == [
        "2:single_alphanumeric"
    ]
    assert objects(single_triples, "citation_section_profile_signature_token_count") == [
        "3"
    ]
    assert objects(single_triples, "citation_section_profile_signature_token_prefix") == [
        "single"
    ]
    assert objects(single_triples, "citation_title_section_signature_token_count") == [
        "2"
    ]
    assert objects(single_triples, "citation_title_section_signature_has_mixed_token") == [
        "true"
    ]
    assert objects(single_triples, "citation_title_section_profile_token_suffix") == [
        "alphanumeric"
    ]
    assert objects(single_triples, "source_id_section_profile_signature") == [
        "single_alphanumeric:N3A1"
    ]
    assert objects(single_triples, "source_id_title_section_signature") == ["2:N3A1"]
    assert objects(single_triples, "source_id_title_section_profile") == [
        "2:single_alphanumeric"
    ]
    assert objects(single_triples, "source_id_section_profile_signature_token_count") == [
        "3"
    ]
    assert objects(single_triples, "source_id_title_section_signature_token_count") == [
        "2"
    ]
    assert objects(single_triples, "source_id_title_section_profile_token_suffix") == [
        "alphanumeric"
    ]
    assert objects(single_triples, "citation_source_id_section_signature_pair") == [
        "N3A1|N3A1"
    ]
    assert objects(single_triples, "citation_source_id_section_signature_match") == [
        "true"
    ]
    assert objects(single_triples, "citation_source_id_section_profile_pair") == [
        "single_alphanumeric|single_alphanumeric"
    ]
    assert objects(single_triples, "citation_source_id_section_profile_match") == [
        "true"
    ]
    assert objects(single_triples, "citation_source_id_title_section_signature_pair") == [
        "2:n3a1|2:n3a1"
    ]
    assert objects(single_triples, "citation_source_id_title_section_signature_match") == [
        "true"
    ]
    assert objects(single_triples, "citation_source_id_title_section_profile_pair") == [
        "2:single_alphanumeric|2:single_alphanumeric"
    ]
    assert objects(single_triples, "citation_source_id_title_section_profile_match") == [
        "true"
    ]

    assert objects(compound_triples, "citation_section_profile_signature") == [
        "compound_mixed:N3A3-N1"
    ]
    assert objects(compound_triples, "citation_title_section_signature") == ["16:N3A3-N1"]
    assert objects(compound_triples, "citation_title_section_profile") == [
        "16:compound_mixed"
    ]
    assert objects(compound_triples, "citation_title_section_signature_token_count") == [
        "3"
    ]
    assert objects(compound_triples, "citation_title_section_signature_token_suffix") == [
        "n1"
    ]
    assert objects(compound_triples, "citation_title_section_profile_token_suffix") == [
        "mixed"
    ]
    assert objects(compound_triples, "source_id_section_profile_signature") == [
        "compound_mixed:N3A3-N1"
    ]
    assert objects(compound_triples, "source_id_title_section_signature") == [
        "16:N3A3-N1"
    ]
    assert objects(compound_triples, "source_id_title_section_profile") == [
        "16:compound_mixed"
    ]
    assert objects(compound_triples, "source_id_title_section_signature_token_count") == [
        "3"
    ]
    assert objects(compound_triples, "source_id_title_section_profile_token_suffix") == [
        "mixed"
    ]


def test_decode_modal_ir_document_emits_section_style_slots() -> None:
    lower_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_single_component_sample_document())
    )
    upper_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_upper_alpha_suffix_sample_document())
    )
    punct_slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_trailing_punct_sample_document())
    )

    assert lower_slot_map["citation_section_style"] == [
        "single_alphanumeric_alpha_lower_clean"
    ]
    assert lower_slot_map["citation_title_section_style"] == [
        "2:single_alphanumeric_alpha_lower_clean"
    ]
    assert lower_slot_map["citation_title_section_style_canonical"] == [
        "2:single_alphanumeric_alpha_lower_clean"
    ]
    assert lower_slot_map["citation_section_suffix_style"] == ["alpha_lower"]
    assert lower_slot_map["citation_section_punctuation_style"] == ["clean"]
    assert lower_slot_map["source_id_section_style"] == [
        "single_alphanumeric_alpha_lower_clean"
    ]
    assert lower_slot_map["source_id_title_section_style"] == [
        "2:single_alphanumeric_alpha_lower_clean"
    ]
    assert lower_slot_map["source_id_title_section_style_canonical"] == [
        "2:single_alphanumeric_alpha_lower_clean"
    ]
    assert lower_slot_map["source_id_section_suffix_style"] == ["alpha_lower"]
    assert lower_slot_map["source_id_section_punctuation_style"] == ["clean"]

    assert upper_slot_map["citation_section_style"] == [
        "single_alphanumeric_alpha_upper_clean"
    ]
    assert upper_slot_map["citation_title_section_style"] == [
        "26:single_alphanumeric_alpha_upper_clean"
    ]
    assert upper_slot_map["citation_title_section_style_canonical"] == [
        "26:single_alphanumeric_alpha_upper_clean"
    ]
    assert upper_slot_map["citation_section_suffix_style"] == ["alpha_upper"]
    assert upper_slot_map["citation_section_punctuation_style"] == ["clean"]
    assert upper_slot_map["source_id_section_style"] == [
        "single_alphanumeric_alpha_upper_clean"
    ]
    assert upper_slot_map["source_id_title_section_style"] == [
        "26:single_alphanumeric_alpha_upper_clean"
    ]
    assert upper_slot_map["source_id_title_section_style_canonical"] == [
        "26:single_alphanumeric_alpha_upper_clean"
    ]
    assert upper_slot_map["source_id_section_suffix_style"] == ["alpha_upper"]
    assert upper_slot_map["source_id_section_punctuation_style"] == ["clean"]

    assert punct_slot_map["citation_section_style"] == ["single_numeric_trailing_punct"]
    assert punct_slot_map["citation_title_section_style"] == [
        "46:single_numeric_trailing_punct"
    ]
    assert punct_slot_map["citation_title_section_style_canonical"] == [
        "46:single_numeric_none_none_trailing_punct"
    ]
    assert punct_slot_map["citation_section_suffix_style"] == ["none"]
    assert punct_slot_map["citation_section_punctuation_style"] == ["trailing_punct"]
    assert punct_slot_map["source_id_section_style"] == ["single_numeric_trailing_punct"]
    assert punct_slot_map["source_id_title_section_style"] == [
        "46:single_numeric_trailing_punct"
    ]
    assert punct_slot_map["source_id_title_section_style_canonical"] == [
        "46:single_numeric_none_none_trailing_punct"
    ]
    assert punct_slot_map["source_id_section_suffix_style"] == ["none"]
    assert punct_slot_map["source_id_section_punctuation_style"] == ["trailing_punct"]


def test_modal_ir_to_flogic_triples_emits_section_style_slots() -> None:
    lower_triples = modal_ir_to_flogic_triples(_single_component_sample_document())
    upper_triples = modal_ir_to_flogic_triples(_upper_alpha_suffix_sample_document())
    punct_triples = modal_ir_to_flogic_triples(_trailing_punct_sample_document())

    def objects(triples: list[dict[str, str]], predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects(lower_triples, "citation_section_style") == [
        "single_alphanumeric_alpha_lower_clean"
    ]
    assert objects(lower_triples, "citation_title_section_style") == [
        "2:single_alphanumeric_alpha_lower_clean"
    ]
    assert objects(lower_triples, "citation_title_section_style_canonical") == [
        "2:single_alphanumeric_alpha_lower_clean"
    ]
    assert objects(lower_triples, "citation_section_suffix_style") == ["alpha_lower"]
    assert objects(lower_triples, "citation_section_punctuation_style") == ["clean"]
    assert objects(lower_triples, "source_id_section_style") == [
        "single_alphanumeric_alpha_lower_clean"
    ]
    assert objects(lower_triples, "source_id_title_section_style") == [
        "2:single_alphanumeric_alpha_lower_clean"
    ]
    assert objects(lower_triples, "source_id_title_section_style_canonical") == [
        "2:single_alphanumeric_alpha_lower_clean"
    ]
    assert objects(lower_triples, "source_id_section_suffix_style") == ["alpha_lower"]
    assert objects(lower_triples, "source_id_section_punctuation_style") == ["clean"]

    assert objects(upper_triples, "citation_section_style") == [
        "single_alphanumeric_alpha_upper_clean"
    ]
    assert objects(upper_triples, "citation_title_section_style") == [
        "26:single_alphanumeric_alpha_upper_clean"
    ]
    assert objects(upper_triples, "citation_title_section_style_canonical") == [
        "26:single_alphanumeric_alpha_upper_clean"
    ]
    assert objects(upper_triples, "citation_section_suffix_style") == ["alpha_upper"]
    assert objects(upper_triples, "citation_section_punctuation_style") == ["clean"]
    assert objects(upper_triples, "source_id_section_style") == [
        "single_alphanumeric_alpha_upper_clean"
    ]
    assert objects(upper_triples, "source_id_title_section_style") == [
        "26:single_alphanumeric_alpha_upper_clean"
    ]
    assert objects(upper_triples, "source_id_title_section_style_canonical") == [
        "26:single_alphanumeric_alpha_upper_clean"
    ]
    assert objects(upper_triples, "source_id_section_suffix_style") == ["alpha_upper"]
    assert objects(upper_triples, "source_id_section_punctuation_style") == ["clean"]

    assert objects(punct_triples, "citation_section_style") == [
        "single_numeric_trailing_punct"
    ]
    assert objects(punct_triples, "citation_title_section_style") == [
        "46:single_numeric_trailing_punct"
    ]
    assert objects(punct_triples, "citation_title_section_style_canonical") == [
        "46:single_numeric_none_none_trailing_punct"
    ]
    assert objects(punct_triples, "citation_section_suffix_style") == ["none"]
    assert objects(punct_triples, "citation_section_punctuation_style") == [
        "trailing_punct"
    ]
    assert objects(punct_triples, "source_id_section_style") == [
        "single_numeric_trailing_punct"
    ]
    assert objects(punct_triples, "source_id_title_section_style") == [
        "46:single_numeric_trailing_punct"
    ]
    assert objects(punct_triples, "source_id_title_section_style_canonical") == [
        "46:single_numeric_none_none_trailing_punct"
    ]
    assert objects(punct_triples, "source_id_section_suffix_style") == ["none"]
    assert objects(punct_triples, "source_id_section_punctuation_style") == [
        "trailing_punct"
    ]


def test_decode_modal_ir_document_emits_suffix_kind_coarse_and_alignment_slots() -> None:
    expected = {
        "us-code-16-198a-69c109aec60f214a": {
            "section_pair": "alpha|alpha",
            "section_match": "true",
            "primary_alignment_pair": "alpha|alpha",
            "terminal_alignment_pair": "alpha|alpha",
        },
        "us-code-22-1642e-0a4a6e0aa906f829": {
            "section_pair": "alpha|alpha",
            "section_match": "true",
            "primary_alignment_pair": "alpha|alpha",
            "terminal_alignment_pair": "alpha|alpha",
        },
        "us-code-25-450a-1-b25ed1d7e3a8d3a7": {
            "section_pair": "alpha|none",
            "section_match": "false",
            "primary_alignment_pair": "alpha|alpha",
            "terminal_alignment_pair": "none|none",
        },
        "us-code-46-12107.-ac993296d58346dd": {
            "section_pair": "none|none",
            "section_match": "true",
            "primary_alignment_pair": "none|none",
            "terminal_alignment_pair": "none|none",
        },
    }

    for document in _citation_suffix_kind_residual_samples():
        slot_map = decoded_modal_phrase_slot_text_map(
            decode_modal_ir_document(document)
        )
        doc_expected = expected[document.document_id]
        section_primary_kind, section_terminal_kind = doc_expected["section_pair"].split("|")

        assert slot_map["citation_section_primary_suffix_kind_coarse"] == [section_primary_kind]
        assert slot_map["citation_section_terminal_suffix_kind_coarse"] == [section_terminal_kind]
        assert slot_map["citation_section_primary_terminal_suffix_kind_pair"] == [
            doc_expected["section_pair"]
        ]
        assert slot_map["citation_section_primary_terminal_suffix_kind_match"] == [
            doc_expected["section_match"]
        ]

        assert slot_map["source_id_section_primary_suffix_kind_coarse"] == [section_primary_kind]
        assert slot_map["source_id_section_terminal_suffix_kind_coarse"] == [section_terminal_kind]
        assert slot_map["source_id_section_primary_terminal_suffix_kind_pair"] == [
            doc_expected["section_pair"]
        ]
        assert slot_map["source_id_section_primary_terminal_suffix_kind_match"] == [
            doc_expected["section_match"]
        ]

        assert slot_map["citation_source_id_section_primary_suffix_kind_pair"] == [
            doc_expected["primary_alignment_pair"]
        ]
        assert slot_map["citation_source_id_section_primary_suffix_kind_match"] == ["true"]
        assert slot_map["citation_source_id_section_primary_suffix_kind_presence_match"] == [
            "true"
        ]
        assert slot_map["citation_source_id_section_terminal_suffix_kind_pair"] == [
            doc_expected["terminal_alignment_pair"]
        ]
        assert slot_map["citation_source_id_section_terminal_suffix_kind_match"] == ["true"]
        assert slot_map["citation_source_id_section_terminal_suffix_kind_presence_match"] == [
            "true"
        ]


def test_modal_ir_to_flogic_triples_emits_suffix_kind_coarse_and_alignment_slots() -> None:
    expected = {
        "us-code-16-198a-69c109aec60f214a": {
            "section_pair": "alpha|alpha",
            "section_match": "true",
            "primary_alignment_pair": "alpha|alpha",
            "terminal_alignment_pair": "alpha|alpha",
        },
        "us-code-22-1642e-0a4a6e0aa906f829": {
            "section_pair": "alpha|alpha",
            "section_match": "true",
            "primary_alignment_pair": "alpha|alpha",
            "terminal_alignment_pair": "alpha|alpha",
        },
        "us-code-25-450a-1-b25ed1d7e3a8d3a7": {
            "section_pair": "alpha|none",
            "section_match": "false",
            "primary_alignment_pair": "alpha|alpha",
            "terminal_alignment_pair": "none|none",
        },
        "us-code-46-12107.-ac993296d58346dd": {
            "section_pair": "none|none",
            "section_match": "true",
            "primary_alignment_pair": "none|none",
            "terminal_alignment_pair": "none|none",
        },
    }

    for document in _citation_suffix_kind_residual_samples():
        triples = modal_ir_to_flogic_triples(document)
        doc_expected = expected[document.document_id]
        section_primary_kind, section_terminal_kind = doc_expected["section_pair"].split("|")

        def objects(predicate: str) -> list[str]:
            return [
                triple["object"]
                for triple in triples
                if triple.get("predicate") == predicate
            ]

        assert objects("citation_section_primary_suffix_kind_coarse") == [section_primary_kind]
        assert objects("citation_section_terminal_suffix_kind_coarse") == [section_terminal_kind]
        assert objects("citation_section_primary_terminal_suffix_kind_pair") == [
            doc_expected["section_pair"]
        ]
        assert objects("citation_section_primary_terminal_suffix_kind_match") == [
            doc_expected["section_match"]
        ]

        assert objects("source_id_section_primary_suffix_kind_coarse") == [section_primary_kind]
        assert objects("source_id_section_terminal_suffix_kind_coarse") == [section_terminal_kind]
        assert objects("source_id_section_primary_terminal_suffix_kind_pair") == [
            doc_expected["section_pair"]
        ]
        assert objects("source_id_section_primary_terminal_suffix_kind_match") == [
            doc_expected["section_match"]
        ]

        assert objects("citation_source_id_section_primary_suffix_kind_pair") == [
            doc_expected["primary_alignment_pair"]
        ]
        assert objects("citation_source_id_section_primary_suffix_kind_match") == ["true"]
        assert objects("citation_source_id_section_primary_suffix_kind_presence_match") == [
            "true"
        ]
        assert objects("citation_source_id_section_terminal_suffix_kind_pair") == [
            doc_expected["terminal_alignment_pair"]
        ]
        assert objects("citation_source_id_section_terminal_suffix_kind_match") == ["true"]
        assert objects("citation_source_id_section_terminal_suffix_kind_presence_match") == [
            "true"
        ]


def test_decode_modal_ir_document_emits_number_distance_profile_slots() -> None:
    slot_map = decoded_modal_phrase_slot_text_map(
        decode_modal_ir_document(_trailing_punct_sample_document())
    )

    assert slot_map["citation_title_section_primary_number_distance_profile"] == [
        "ascending_10k_to_99k"
    ]
    assert slot_map["citation_title_section_terminal_number_distance_profile"] == [
        "ascending_10k_to_99k"
    ]
    assert slot_map["source_id_title_section_primary_number_distance_profile"] == [
        "ascending_10k_to_99k"
    ]
    assert slot_map["source_id_title_section_terminal_number_distance_profile"] == [
        "ascending_10k_to_99k"
    ]
    assert slot_map["citation_source_id_title_number_distance_profile"] == [
        "equal_lt_1k"
    ]
    assert slot_map["citation_source_id_section_primary_number_distance_profile"] == [
        "equal_lt_1k"
    ]
    assert slot_map["citation_source_id_section_terminal_number_distance_profile"] == [
        "equal_lt_1k"
    ]
    assert slot_map["citation_source_id_title_number_span_digit_count_bucket"] == [
        "1_digit"
    ]
    assert (
        slot_map["citation_source_id_section_primary_number_span_digit_count_bucket"]
        == ["1_digit"]
    )
    assert (
        slot_map["citation_source_id_section_terminal_number_span_digit_count_bucket"]
        == ["1_digit"]
    )


def test_modal_ir_to_flogic_triples_emits_number_distance_profile_slots() -> None:
    triples = modal_ir_to_flogic_triples(_trailing_punct_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("citation_title_section_primary_number_distance_profile") == [
        "ascending_10k_to_99k"
    ]
    assert objects("citation_title_section_terminal_number_distance_profile") == [
        "ascending_10k_to_99k"
    ]
    assert objects("source_id_title_section_primary_number_distance_profile") == [
        "ascending_10k_to_99k"
    ]
    assert objects("source_id_title_section_terminal_number_distance_profile") == [
        "ascending_10k_to_99k"
    ]
    assert objects("citation_source_id_title_number_distance_profile") == [
        "equal_lt_1k"
    ]
    assert objects("citation_source_id_section_primary_number_distance_profile") == [
        "equal_lt_1k"
    ]
    assert objects("citation_source_id_section_terminal_number_distance_profile") == [
        "equal_lt_1k"
    ]
    assert objects("citation_source_id_title_number_span_digit_count_bucket") == [
        "1_digit"
    ]
    assert objects(
        "citation_source_id_section_primary_number_span_digit_count_bucket"
    ) == ["1_digit"]
    assert objects(
        "citation_source_id_section_terminal_number_span_digit_count_bucket"
    ) == ["1_digit"]


def test_decode_modal_ir_document_emits_span_metric_slots() -> None:
    decoded = decode_modal_ir_document(_span_metrics_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)

    assert slot_map["modal_formula_count"] == ["2"]
    assert slot_map["source_text_char_count"] == ["20"]
    assert slot_map["modal_span_count"] == ["2"]
    assert slot_map["modal_span_char_count"] == ["11"]
    assert slot_map["source_context_span_count"] == ["2"]
    assert slot_map["source_context_span_char_count"] == ["9"]
    assert slot_map["support_span_start_char"] == ["0"]
    assert slot_map["support_span_end_char"] == ["14"]
    assert slot_map["support_span_width"] == ["14"]
    assert slot_map["modal_span_coverage_percent"] == ["55"]
    assert slot_map["modal_span_coverage_bucket"] == ["majority_coverage"]
    assert slot_map["modal_span_char_count_digit_count_bucket"] == ["2_digit"]
    assert slot_map["modal_span_coverage_percent_prefix_two_digits"] == ["55"]
    assert slot_map["source_context_span_count_parity"] == ["even"]


def test_modal_ir_to_flogic_triples_emits_span_metric_slots() -> None:
    triples = modal_ir_to_flogic_triples(_span_metrics_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert objects("modal_formula_count") == ["2"]
    assert objects("source_text_char_count") == ["20"]
    assert objects("modal_span_count") == ["2"]
    assert objects("modal_span_char_count") == ["11"]
    assert objects("source_context_span_count") == ["2"]
    assert objects("source_context_span_char_count") == ["9"]
    assert objects("support_span_start_char") == ["0"]
    assert objects("support_span_end_char") == ["14"]
    assert objects("support_span_width") == ["14"]
    assert objects("modal_span_coverage_percent") == ["55"]
    assert objects("modal_span_coverage_bucket") == ["majority_coverage"]
    assert objects("modal_span_char_count_digit_count_bucket") == ["2_digit"]
    assert objects("modal_span_coverage_percent_prefix_two_digits") == ["55"]
    assert objects("source_context_span_count_parity") == ["even"]


def test_decode_and_triples_emit_no_modal_span_bucket_for_zero_formula_documents() -> None:
    decoded = decode_modal_ir_document(_zero_formula_sample_document())
    slot_map = decoded_modal_phrase_slot_text_map(decoded)
    triples = modal_ir_to_flogic_triples(_zero_formula_sample_document())

    def objects(predicate: str) -> list[str]:
        return [
            triple["object"]
            for triple in triples
            if triple.get("predicate") == predicate
        ]

    assert slot_map["modal_formula_count"] == ["0"]
    assert slot_map["modal_span_count"] == ["0"]
    assert slot_map["source_context_span_count"] == ["1"]
    assert slot_map["modal_span_coverage_percent"] == ["0"]
    assert slot_map["modal_span_coverage_bucket"] == ["no_modal_span"]

    assert objects("modal_formula_count") == ["0"]
    assert objects("modal_span_count") == ["0"]
    assert objects("source_context_span_count") == ["1"]
    assert objects("modal_span_coverage_percent") == ["0"]
    assert objects("modal_span_coverage_bucket") == ["no_modal_span"]
