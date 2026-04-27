"""
Unit tests for DeonticConverter.

Tests the unified deontic converter with integrated features.
"""

import pytest
from ipfs_datasets_py.logic.deontic import DeonticConverter
from ipfs_datasets_py.logic.common.converters import ConversionStatus


class TestDeonticConverter:
    """Test suite for DeonticConverter."""
    
    def test_initialization_default(self):
        """Test DeonticConverter initializes with default settings."""
        # GIVEN: Default initialization
        # WHEN: Creating converter
        converter = DeonticConverter()
        
        # THEN: Should initialize successfully
        assert converter is not None
        assert converter.jurisdiction == "us"
        assert converter.document_type == "statute"
        assert converter.confidence_threshold == 0.7
    
    def test_initialization_custom_settings(self):
        """Test DeonticConverter with custom settings."""
        # GIVEN: Custom settings
        # WHEN: Creating converter with custom options
        converter = DeonticConverter(
            jurisdiction="eu",
            document_type="regulation",
            use_cache=True,
            use_ml=False,
            confidence_threshold=0.8
        )
        
        # THEN: Settings should be applied
        assert converter.jurisdiction == "eu"
        assert converter.document_type == "regulation"
        assert converter.confidence_threshold == 0.8
        assert converter.use_ml is False
    
    def test_simple_obligation_conversion(self):
        """Test converting a simple obligation statement."""
        # GIVEN: A simple obligation text
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        text = "The tenant must pay rent monthly"
        
        # WHEN: Converting to deontic logic
        result = converter.convert(text)
        
        # THEN: Should successfully convert
        assert result.success
        assert result.status == ConversionStatus.SUCCESS
        assert result.output is not None
        assert result.output.confidence > 0
    
    def test_permission_conversion(self):
        """Test converting a permission statement."""
        # GIVEN: A permission text
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        text = "The defendant may appeal the decision"
        
        # WHEN: Converting to deontic logic
        result = converter.convert(text)
        
        # THEN: Should successfully convert with permission operator
        assert result.success
        assert result.output is not None
    
    def test_prohibition_conversion(self):
        """Test converting a prohibition statement."""
        # GIVEN: A prohibition text
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        text = "The contractor shall not subcontract without approval"
        
        # WHEN: Converting to deontic logic
        result = converter.convert(text)
        
        # THEN: Should successfully convert with prohibition operator
        assert result.success
        assert result.output is not None
        assert result.output.operator.value == "F"

    def test_shall_not_is_not_misclassified_as_obligation(self):
        """Regression: 'shall not' must be parsed as prohibition before bare 'shall'."""
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        result = converter.convert("The contractor shall not subcontract without approval")

        assert result.success
        assert result.output is not None
        assert result.output.operator.value == "F"
        assert result.output.proposition == "∀x (Contractor(x) ∧ ¬Approval(x) → Subcontract(x))"
        assert result.output.formula == "F[contractor](∀x (Contractor(x) ∧ ¬Approval(x) → Subcontract(x)))"

    def test_structured_modal_clause_extraction_preserves_condition_and_exception(self):
        """The deterministic scaffold should expose useful legal clause structure."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            "The Secretary shall submit a report to Congress within 30 days unless disclosure is classified."
        )

        assert len(elements) == 1
        element = elements[0]
        assert element["deontic_operator"] == "O"
        assert element["subject"] == ["Secretary"]
        assert element["action"] == ["submit a report to Congress"]
        assert element["temporal_constraints"] == [{"type": "deadline", "value": "30 days"}]
        assert element["exceptions"] == ["disclosure is classified"]

    def test_non_normative_text_gets_low_confidence_unparsed_scaffold(self):
        """Do not pretend arbitrary descriptive text is a high-quality obligation."""
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        result = converter.convert("This section contains historical notes and editorial references.")

        assert result.success
        assert result.output is not None
        assert result.output.proposition == "UnparsedNonNormativeOrAmbiguousText"
        assert result.output.confidence <= 0.1

    def test_without_clause_is_exception_not_action_tail(self):
        """'Without approval' should qualify the norm instead of becoming the action."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("The contractor shall not subcontract without written approval.")

        assert len(elements) == 1
        assert elements[0]["deontic_operator"] == "F"
        assert elements[0]["action"] == ["subcontract"]
        assert elements[0]["exceptions"] == ["written approval"]

    def test_not_later_than_deadline_with_anchor(self):
        """Federal statutes often express deadlines as 'not later than N days after ...'."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            "The Secretary shall issue regulations not later than 180 days after enactment."
        )

        assert len(elements) == 1
        assert elements[0]["action"] == ["issue regulations"]
        assert elements[0]["temporal_constraints"] == [
            {"type": "deadline", "value": "180 days after enactment"}
        ]

    def test_subject_to_condition_is_preserved(self):
        """'Subject to' clauses should appear as conditions for downstream review."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            "Subject to appropriations, the Administrator may award grants to eligible entities."
        )

        assert len(elements) == 1
        assert elements[0]["deontic_operator"] == "P"
        assert elements[0]["subject"] == ["Administrator"]
        assert elements[0]["conditions"] == ["appropriations"]

    def test_no_person_shall_is_prohibition(self):
        """'No person shall' is a prohibition even without an explicit 'not' after shall."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("No person shall knowingly make a false statement.")

        assert len(elements) == 1
        assert elements[0]["deontic_operator"] == "F"
        assert elements[0]["subject"] == ["person"]
        assert elements[0]["action"] == ["knowingly make a false statement"]
        assert elements[0]["mental_state"] == "knowingly"
        assert elements[0]["action_verb"] == "make"
        assert elements[0]["action_object"] == "a false statement"

    def test_implicit_repeated_subject_modal_clause(self):
        """A second modal joined by 'and shall' should inherit the prior subject."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            "The Secretary may award grants and shall submit an annual report to Congress."
        )

        assert [element["deontic_operator"] for element in elements] == ["P", "O"]
        assert [element["subject"] for element in elements] == [["Secretary"], ["Secretary"]]
        assert [element["action"] for element in elements] == [
            ["award grants"],
            ["submit an annual report to Congress"],
        ]

    def test_passive_by_agent_clause_normalizes_actor_and_action(self):
        """Passive duties should not make the object look like the regulated actor."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("A report shall be submitted by the Secretary within 90 days.")

        assert len(elements) == 1
        assert elements[0]["subject"] == ["Secretary"]
        assert elements[0]["action"] == ["submit report"]
        assert elements[0]["temporal_constraints"] == [{"type": "deadline", "value": "90 days"}]

    def test_quoted_defined_term_extraction(self):
        """Quoted statutory terms should become the definition subject."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            'In this section, the term "covered entity" means a provider of covered services.'
        )

        assert len(elements) == 1
        assert elements[0]["deontic_operator"] == "DEF"
        assert elements[0]["subject"] == ["covered entity"]

    def test_cross_reference_exception_is_structured(self):
        """Cross-reference exceptions should be available as KG/provenance hooks."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )

        assert len(elements) == 1
        assert elements[0]["action"] == ["publish the notice"]
        assert elements[0]["exceptions"] == ["as provided in section 552"]
        assert {"type": "section", "value": "552"} in elements[0]["cross_references"]

    def test_notwithstanding_override_and_usc_reference(self):
        """Override clauses and U.S.C. references should be explicit metadata."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            "Notwithstanding section 301, the Secretary may waive requirements under 10 U.S.C. 123."
        )

        assert len(elements) == 1
        assert elements[0]["deontic_operator"] == "P"
        assert elements[0]["override_clauses"] == ["section 301"]
        assert {"type": "section", "value": "301"} in elements[0]["cross_references"]
        assert {"type": "usc", "value": "10 123"} in elements[0]["cross_references"]

    def test_enumerated_items_are_preserved(self):
        """Enumeration text is noisy for regex logic but useful for LLM repair prompts."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            "The Secretary shall (1) establish procedures; (2) submit a report; and (3) maintain records."
        )

        assert len(elements) == 1
        assert elements[0]["action"] == ["establish procedures"]
        assert elements[0]["enumerated_items"] == [
            {"label": "1", "text": "establish procedures"},
            {"label": "2", "text": "submit a report"},
            {"label": "3", "text": "maintain records"},
        ]

    def test_scaffold_quality_metadata_guides_theorem_promotion(self):
        """Deterministic parses should expose quality gates for downstream provers."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("The tenant must pay rent monthly.")

        assert len(elements) == 1
        assert elements[0]["slot_coverage"] == 1.0
        assert elements[0]["quality_label"] == "high"
        assert elements[0]["scaffold_quality"] >= 0.75
        assert elements[0]["promotable_to_theorem"] is True
        assert elements[0]["parser_warnings"] == []
        assert elements[0]["actor_type"] == "legal_person"

    def test_complex_scaffold_warns_before_theorem_promotion(self):
        """Cross refs/exceptions/enumerations should route to LLM repair/review first."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            "The Secretary shall (1) establish procedures; (2) submit reports except as provided in section 552."
        )

        assert len(elements) == 1
        assert elements[0]["actor_type"] == "government_actor"
        assert "enumerated_clause_requires_item_level_review" in elements[0]["parser_warnings"]
        assert "cross_reference_requires_resolution" in elements[0]["parser_warnings"]
        assert "exception_requires_scope_review" in elements[0]["parser_warnings"]
        assert elements[0]["promotable_to_theorem"] is False

    def test_action_recipient_becomes_beneficiary_agent(self):
        """Recipients like Congress are useful KG edges and deontic beneficiaries."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        elements = extract_normative_elements("The Secretary shall submit a report to Congress.")
        result = converter.convert("The Secretary shall submit a report to Congress.")

        assert elements[0]["action_recipient"] == "Congress"
        assert result.success
        assert result.output.beneficiary is not None
        assert result.output.beneficiary.name == "Congress"

    def test_definition_body_and_quality_are_structured(self):
        """Definitions need the term and body for ontology/frame-logic generation."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            'In this section, the term "covered entity" means a provider of covered services.'
        )

        assert len(elements) == 1
        assert elements[0]["defined_term"] == "covered entity"
        assert elements[0]["definition_body"] == "a provider of covered services"
        assert elements[0]["slot_coverage"] == 1.0

    def test_parser_schema_contract_is_validated(self):
        """Every extracted norm should satisfy the stable downstream schema."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            PARSER_SCHEMA_VERSION,
            extract_normative_elements,
            validate_parser_element,
        )

        elements = extract_normative_elements("The tenant must pay rent monthly.")

        assert len(elements) == 1
        assert elements[0]["schema_version"] == PARSER_SCHEMA_VERSION
        assert elements[0]["schema_valid"] is True
        assert validate_parser_element(elements[0])["valid"] is True

    def test_field_level_condition_exception_temporal_and_ref_details(self):
        """Detailed slots should preserve normalized text, raw text, spans, and types."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        text = (
            "Subject to approval, the Director shall issue a permit within 10 days after application "
            "unless the application is incomplete except as provided in section 5.01.020."
        )
        element = extract_normative_elements(text)[0]

        assert element["condition_details"] == [
            {
                "type": "condition",
                "clause_type": "subject_to",
                "raw_text": "approval",
                "normalized_text": "approval",
                "span": [11, 19],
                "clause_span": [0, 20],
            }
        ]
        assert element["temporal_constraint_details"] == [
            {
                "type": "deadline",
                "temporal_kind": "within_duration",
                "value": "10 days after application",
                "anchor": "application",
                "raw_text": "within 10 days after application",
                "normalized_text": "10 days after application",
                "span": [55, 87],
            }
        ]
        assert element["exception_details"] == [
            {
                "type": "exception",
                "clause_type": "unless",
                "raw_text": "the application is incomplete except as provided in section 5.01.020",
                "normalized_text": "the application is incomplete except as provided in section 5.01.020",
                "span": [95, 163],
                "clause_span": [88, 163],
            },
            {
                "type": "exception",
                "clause_type": "except",
                "raw_text": "as provided in section 5.01.020",
                "normalized_text": "as provided in section 5.01.020",
                "span": [132, 163],
                "clause_span": [125, 163],
            },
        ]
        assert element["cross_reference_details"] == [
            {
                "type": "section",
                "value": "5.01.020",
                "raw_text": "section 5.01.020",
                "normalized_text": "section 5.01.020",
                "span": [147, 163],
            }
        ]

    def test_override_and_money_details_are_schema_fields(self):
        """Override and money details should be available for LLM repair prompts."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        element = extract_normative_elements(
            "Notwithstanding section 5.01.020, a violation is punishable by a fine of $1,000."
        )[0]

        assert element["override_clause_details"] == [
            {
                "type": "override",
                "clause_type": "notwithstanding",
                "raw_text": "section 5.01.020",
                "normalized_text": "section 5.01.020",
                "span": [16, 32],
                "clause_span": [0, 33],
            }
        ]
        assert element["monetary_amount_details"] == [
            {
                "type": "money",
                "raw_text": "$1,000",
                "normalized_text": "$1,000",
                "numeric_value": "1000",
                "currency": "USD",
                "span": [73, 79],
            }
        ]

    def test_statute_segmentation_preserves_section_context(self):
        """Section headings should be carried into each extracted norm."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        text = """5.01.010 Permits required.
The applicant shall file an application with the Bureau."""
        elements = extract_normative_elements(text)

        assert len(elements) == 1
        assert elements[0]["section_context"] == {
            "section": "5.01.010",
            "heading": "Permits required",
        }
        assert "section:5.01.010" in elements[0]["hierarchy_path"]

    def test_standalone_enumerated_segments_preserve_hierarchy(self):
        """Standalone municipal list items should expose paragraph hierarchy."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import segment_legal_text

        segments = segment_legal_text(
            """5.01.010 Duties.
(1) The applicant shall file an application.
(2) The applicant shall pay the fee."""
        )

        assert [segment["hierarchy_path"][-1] for segment in segments] == [
            "paragraph:1",
            "paragraph:2",
        ]
        assert segments[0]["section_context"]["section"] == "5.01.010"

    def test_implicit_unlawful_clause_is_prohibition(self):
        """Municipal codes often say 'It is unlawful to' instead of 'shall not'."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("It is unlawful for any person to block a sidewalk.")

        assert len(elements) == 1
        assert elements[0]["deontic_operator"] == "F"
        assert elements[0]["subject"] == ["person"]
        assert elements[0]["action"] == ["block a sidewalk"]

    def test_required_permit_clause_is_structured(self):
        """Permit/license required clauses should not disappear as descriptive text."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("A permit is required to operate a food cart.")

        assert len(elements) == 1
        assert elements[0]["deontic_operator"] == "O"
        assert elements[0]["subject"] == ["permit"]
        assert elements[0]["entity_type"] == "legal_instrument"
        assert elements[0]["action"] == ["operate a food cart"]
        assert elements[0]["legal_frame"]["category"] == "permit_or_license"
        assert {
            "subject": "operate a food cart",
            "predicate": "requiresLegalInstrument",
            "object": "permit",
        } in elements[0]["kg_relationship_hints"]

    def test_no_person_may_is_prohibition(self):
        """'No person may' is a prohibition even though may is usually permission."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("No person may discharge pollutants into the sewer.")

        assert len(elements) == 1
        assert elements[0]["deontic_operator"] == "F"
        assert elements[0]["subject"] == ["person"]

    def test_failure_to_clause_becomes_violation_frame(self):
        """Violation clauses should be explicit KG/formal-logic hooks."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("Failure to comply with this section is a violation.")

        assert len(elements) == 1
        assert elements[0]["norm_type"] == "violation"
        assert elements[0]["deontic_operator"] == "F"
        assert elements[0]["legal_frame"]["category"] == "violation"
        assert elements[0]["action"] == ["fail to comply with this section"]
        assert {
            "subject": "law",
            "predicate": "definesViolationFor",
            "object": "person",
        } in elements[0]["kg_relationship_hints"]

    def test_penalty_clause_extracts_money_and_sanction_frame(self):
        """Fines/penalties need structured amounts and review warnings."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("A violation is punishable by a fine of $500.")

        assert len(elements) == 1
        assert elements[0]["norm_type"] == "penalty"
        assert elements[0]["legal_frame"]["category"] == "penalty"
        assert elements[0]["entity_type"] == "legal_event"
        assert elements[0]["monetary_amounts"] == [{"raw_text": "$500", "span": [39, 43]}]
        assert elements[0]["penalty"]["has_fine"] is True
        assert {"subject": "law", "predicate": "mentionsAmount", "object": "$500"} in elements[0]["kg_relationship_hints"]

    def test_appeal_clause_gets_procedure_frame_and_timeline_warning(self):
        """Appeal windows are procedural event chains, not just generic permissions."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("An appeal may be filed within 10 days after the decision.")

        assert len(elements) == 1
        assert elements[0]["deontic_operator"] == "P"
        assert elements[0]["legal_frame"]["category"] == "procedure"
        assert "appeal" in elements[0]["procedure"]["events"]
        assert elements[0]["temporal_constraints"] == [
            {"type": "deadline", "value": "10 days after the decision"}
        ]
        assert "procedure_timeline_requires_event_order_review" in elements[0]["parser_warnings"]

    def test_notice_hearing_decision_appeal_chain_is_ordered(self):
        """Procedural clauses should expose an ordered municipal workflow chain."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            "The Director shall provide notice of the hearing and issue a decision that may be appealed."
        )

        assert len(elements) == 1
        first = elements[0]
        assert first["legal_frame"]["category"] == "procedure"
        assert [item["event"] for item in first["procedure"]["event_chain"]] == ["notice", "hearing", "decision", "issuance", "appeal"]
        assert first["procedure"]["trigger_event"] == "notice"
        assert first["procedure"]["terminal_event"] == "appeal"
        assert {"subject": "Director", "predicate": "providesNoticeTo", "object": "provide notice of the hearing and issue a decision that may be appealed"} in first["kg_relationship_hints"]
        assert {"subject": "Director", "predicate": "holdsHearingFor", "object": "provide notice of the hearing and issue a decision that may be appealed"} in first["kg_relationship_hints"]
        assert {"subject": "Director", "predicate": "issuesDecision", "object": "provide notice of the hearing and issue a decision that may be appealed"} in first["kg_relationship_hints"]

    def test_revocation_and_suspension_emit_instrument_relationships(self):
        """Permit enforcement workflows should become KG hints."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("The Director may revoke or suspend the permit after notice.")

        assert len(elements) == 1
        assert elements[0]["legal_frame"]["category"] == "procedure"
        assert elements[0]["procedure"]["events"] == ["notice", "suspension", "revocation"]
        assert {"subject": "Director", "predicate": "mayRevokeInstrument", "object": "permit"} in elements[0]["kg_relationship_hints"]
        assert {"subject": "Director", "predicate": "maySuspendInstrument", "object": "permit"} in elements[0]["kg_relationship_hints"]

    def test_inspection_clause_emits_property_relationship(self):
        """Inspection powers are central to municipal enforcement."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("The Bureau may inspect the premises during business hours.")

        assert len(elements) == 1
        assert elements[0]["legal_frame"]["category"] == "procedure"
        assert elements[0]["procedure"]["events"] == ["inspection"]
        assert {"subject": "Bureau", "predicate": "mayInspect", "object": "the premises during business hours"} in elements[0]["kg_relationship_hints"]
    
    def test_empty_input_validation(self):
        """Test that empty input is handled properly."""
        # GIVEN: Empty text
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        text = ""
        
        # WHEN: Attempting to convert
        result = converter.convert(text)
        
        # THEN: Should fail validation
        assert not result.success
        assert result.status == ConversionStatus.FAILED
    
    def test_whitespace_input_validation(self):
        """Test that whitespace-only input is handled properly."""
        # GIVEN: Whitespace-only text
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        text = "   \n\t   "
        
        # WHEN: Attempting to convert
        result = converter.convert(text)
        
        # THEN: Should fail validation
        assert not result.success
        assert result.status == ConversionStatus.FAILED
    
    def test_caching_functionality(self):
        """Test that caching works correctly."""
        # GIVEN: Converter with caching enabled
        converter = DeonticConverter(use_cache=True, use_ml=False, enable_monitoring=False)
        text = "The employee must report to work on time"
        
        # WHEN: Converting same text twice
        result1 = converter.convert(text)
        result2 = converter.convert(text)
        
        # THEN: Both should succeed and second should be from cache
        assert result1.success
        assert result2.success
        # Cache stats should show hits
        cache_stats = converter.get_cache_stats()
        # At minimum, we converted twice, so there should be activity
        assert result1.output.formula == result2.output.formula
    
    def test_batch_conversion(self):
        """Test batch conversion of multiple legal texts."""
        # GIVEN: Multiple legal texts
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        texts = [
            "The tenant must pay rent",
            "The landlord may inspect the premises",
            "The party shall not disclose confidential information"
        ]
        
        # WHEN: Converting in batch
        results = converter.convert_batch(texts, max_workers=2)
        
        # THEN: All should be processed
        assert len(results) == 3
        successful = [r for r in results if r.success]
        assert len(successful) > 0  # At least some should succeed
    
    @pytest.mark.asyncio
    async def test_async_conversion(self):
        """Test async conversion interface."""
        # GIVEN: Legal text
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        text = "The borrower must repay the loan"
        
        # WHEN: Converting asynchronously
        result = await converter.convert_async(text)
        
        # THEN: Should complete successfully
        assert result.success
        assert result.output is not None
    
    def test_confidence_calculation(self):
        """Test confidence score calculation."""
        # GIVEN: Legal text with clear normative content
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        text = "The seller must deliver the goods by the agreed date"
        
        # WHEN: Converting
        result = converter.convert(text)
        
        # THEN: Should have reasonable confidence
        assert result.success
        assert 0 <= result.output.confidence <= 1.0
        # Obligation with clear subject and action should have decent confidence
        assert result.output.confidence > 0.5
    
    def test_multiple_jurisdictions(self):
        """Test conversion with different jurisdictions."""
        # GIVEN: Converters for different jurisdictions
        converter_us = DeonticConverter(jurisdiction="us", use_ml=False, enable_monitoring=False)
        converter_eu = DeonticConverter(jurisdiction="eu", use_ml=False, enable_monitoring=False)
        text = "The data controller must obtain consent"
        
        # WHEN: Converting with different jurisdictions
        result_us = converter_us.convert(text)
        result_eu = converter_eu.convert(text)
        
        # THEN: Both should succeed
        assert result_us.success
        assert result_eu.success
    
    def test_stats_tracking(self):
        """Test statistics tracking."""
        # GIVEN: Converter with stats tracking
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        
        # WHEN: Performing conversions
        converter.convert("Must comply")
        converter.convert("May appeal")
        
        # THEN: Stats should be available
        stats = converter.get_stats()
        assert stats is not None
        assert isinstance(stats, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
