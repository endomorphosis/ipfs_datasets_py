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

    def test_conversion_result_exposes_deterministic_parser_ir(self):
        """Converter metadata should expose source-grounded parser slots."""
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)

        result = converter.convert("The tenant must pay rent monthly.")

        assert result.success
        assert result.output is not None
        assert result.metadata["deterministic_parser"]["enabled"] is True
        assert result.metadata["deterministic_parser"]["element_count"] == 1
        assert result.metadata["deterministic_parser"]["ir_count"] == 1
        assert result.metadata["deterministic_parser"]["formula_record_count"] == 1
        assert result.metadata["deterministic_parser"]["formula_record_proof_ready_count"] == 1
        assert result.metadata["deterministic_parser"]["proof_ready"] is True
        assert result.metadata["deterministic_parser"]["blockers"] == []

        parser_element = result.metadata["parser_element"]
        legal_norm_ir = result.metadata["legal_norm_ir"]
        assert parser_element["source_id"] == legal_norm_ir["source_id"]
        assert legal_norm_ir["modality"] == "O"
        assert legal_norm_ir["actor"] == "tenant"
        assert legal_norm_ir["action"] == "pay rent monthly"
        assert legal_norm_ir["proof_ready"] is True
        assert result.metadata["legal_norm_irs"] == [legal_norm_ir]
        assert result.metadata["legal_formula_records"][0]["source_id"] == parser_element["source_id"]
        assert result.metadata["legal_formula_records"][0]["proof_ready"] is True

    def test_non_normative_conversion_exposes_empty_parser_metadata(self):
        """Unparsed text should not pretend to have a legal IR."""
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)

        result = converter.convert("This section contains historical notes.")

        assert result.success
        assert result.metadata["parser_elements"] == []
        assert result.metadata["deterministic_parser"]["element_count"] == 0
        assert result.metadata["deterministic_parser"]["ir_count"] == 0
        assert result.metadata["deterministic_parser"]["formula_record_count"] == 0
        assert result.metadata["deterministic_parser"]["formula_record_proof_ready_count"] == 0
        assert result.metadata["legal_norm_irs"] == []
        assert result.metadata["legal_formula_records"] == []
        assert "parser_element" not in result.metadata
        assert "legal_norm_ir" not in result.metadata

    def test_converter_can_expand_enumerated_items_for_formalization(self):
        """Converter callers can opt into item-level enumerated parser elements."""
        converter = DeonticConverter(
            use_ml=False,
            enable_monitoring=False,
            expand_enumerations=True,
        )

        result = converter.convert(
            "The Secretary shall (1) establish procedures; (2) submit a report; and (3) maintain records."
        )

        assert result.success
        assert result.metadata["deterministic_parser"]["element_count"] == 3
        assert result.metadata["deterministic_parser"]["ir_count"] == 3
        assert result.metadata["deterministic_parser"]["formula_record_count"] == 3
        assert result.metadata["deterministic_parser"]["formula_record_proof_ready_count"] == 3
        assert [element["action"][0] for element in result.metadata["parser_elements"]] == [
            "establish procedures",
            "submit a report",
            "maintain records",
        ]
        assert result.metadata["legal_norm_ir"]["action"] == "establish procedures"
        assert result.metadata["legal_norm_ir"]["is_enumerated_child"] is True
        assert result.metadata["legal_norm_ir"]["parent_source_id"]
        assert result.metadata["legal_norm_ir"]["enumeration_label"] == "1"
        assert result.metadata["legal_norm_ir"]["enumeration_index"] == 1
        assert result.output is not None
        assert result.output.proposition == "∀x (Secretary(x) → EstablishProcedures(x))"
        assert [norm["action"] for norm in result.metadata["legal_norm_irs"]] == [
            "establish procedures",
            "submit a report",
            "maintain records",
        ]
        assert [norm["enumeration_index"] for norm in result.metadata["legal_norm_irs"]] == [1, 2, 3]
        assert [record["formula"] for record in result.metadata["legal_formula_records"]] == [
            "O(∀x (Secretary(x) → EstablishProcedures(x)))",
            "O(∀x (Secretary(x) → SubmitReport(x)))",
            "O(∀x (Secretary(x) → MaintainRecords(x)))",
        ]
        assert [record["proof_ready"] for record in result.metadata["legal_formula_records"]] == [
            True,
            True,
            True,
        ]

    def test_converter_maps_scope_rules_to_non_obligation_operators(self):
        """Scope rules should not be exposed as ordinary obligations."""
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)

        applicability = converter.convert("This section applies to food carts.")
        exemption = converter.convert("Emergency repairs are exempt from permit requirements.")

        assert applicability.success
        assert exemption.success
        assert applicability.output is not None
        assert exemption.output is not None
        assert applicability.output.operator.value == "POW"
        assert exemption.output.operator.value == "IMM"
        assert applicability.metadata["legal_norm_ir"]["norm_type"] == "applicability"
        assert exemption.metadata["legal_norm_ir"]["norm_type"] == "exemption"

    def test_converter_exposes_local_applicability_formula_record_resolution(self):
        """Formula records may resolve local self-scope while IR stays conservative."""
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)

        result = converter.convert("This section applies to food carts.")

        assert result.success
        norm = result.metadata["legal_norm_ir"]
        record = result.metadata["legal_formula_records"][0]
        assert norm["proof_ready"] is False
        assert "cross_reference_requires_resolution" in norm["blockers"]
        assert record["formula"] == "AppliesTo(ThisSection, FoodCarts)"
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["deterministic_resolution"]["type"] == "local_scope_applicability"
        assert "cross_reference_requires_resolution" in record["blockers"]
        assert result.metadata["deterministic_parser"]["proof_ready"] is False
        assert result.metadata["deterministic_parser"]["formula_record_proof_ready_count"] == 1

    def test_converter_parser_metadata_clears_formula_resolved_repair_noise(self):
        """Converter-facing parser metadata should use deterministic IR readiness."""
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)

        examples = [
            (
                "This section applies to food carts.",
                "local_scope_applicability",
            ),
            (
                "The applicant shall obtain a permit unless approval is denied.",
                "standard_substantive_exception",
            ),
            (
                "Notwithstanding section 5.01.020, the Director may issue a variance.",
                "pure_precedence_override",
            ),
        ]

        for text, resolution_type in examples:
            result = converter.convert(text)

            assert result.success
            parser_element = result.metadata["parser_elements"][0]
            formula_record = result.metadata["legal_formula_records"][0]
            assert parser_element["promotable_to_theorem"] is False
            assert parser_element["llm_repair"]["required"] is False
            assert parser_element["llm_repair"]["allow_llm_repair"] is False
            assert parser_element["llm_repair"]["deterministically_resolved"] is True
            assert parser_element["llm_repair"]["deterministic_resolution"]["type"] == resolution_type
            assert parser_element["export_readiness"]["parser_proof_ready"] is False
            assert parser_element["export_readiness"]["formula_proof_ready"] is True
            assert parser_element["export_readiness"]["proof_ready"] is True
            assert parser_element["export_readiness"]["formula_requires_validation"] is False
            assert parser_element["export_readiness"]["formula_repair_required"] is False
            assert parser_element["export_readiness"]["deterministic_resolution"]["type"] == resolution_type
            assert formula_record["proof_ready"] is True
            assert formula_record["requires_validation"] is False
            assert formula_record["deterministic_resolution"]["type"] == resolution_type

    def test_converter_parser_metadata_keeps_unresolved_reference_repair_required(self):
        """Unresolved numbered cross-reference exceptions must stay blocked."""
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)

        result = converter.convert(
            "The Secretary shall publish the notice except as provided in section 552."
        )

        assert result.success
        parser_element = result.metadata["parser_elements"][0]
        formula_record = result.metadata["legal_formula_records"][0]
        assert parser_element["promotable_to_theorem"] is False
        assert parser_element["llm_repair"]["required"] is True
        assert "cross_reference_requires_resolution" in parser_element["llm_repair"]["reasons"]
        assert parser_element["export_readiness"]["formula_proof_ready"] is False
        assert parser_element["export_readiness"]["formula_requires_validation"] is True
        assert parser_element["export_readiness"]["formula_repair_required"] is True
        assert parser_element["export_readiness"]["deterministic_resolution"] == {}
        assert formula_record["proof_ready"] is False
        assert formula_record["requires_validation"] is True
        assert formula_record["repair_required"] is True
        assert formula_record["deterministic_resolution"] == {}

    def test_converter_exposes_substantive_exception_formula_record_resolution(self):
        """Formula records may resolve simple exceptions while IR stays conservative."""
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)

        result = converter.convert(
            "The applicant shall obtain a permit unless approval is denied."
        )

        assert result.success
        norm = result.metadata["legal_norm_ir"]
        record = result.metadata["legal_formula_records"][0]
        assert norm["proof_ready"] is False
        assert "exception_requires_scope_review" in norm["blockers"]
        assert record["formula"] == "O(∀x (Applicant(x) ∧ ¬ApprovalIsDenied(x) → ObtainPermit(x)))"
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["deterministic_resolution"]["type"] == "standard_substantive_exception"
        assert record["deterministic_resolution"]["exception"] == "approval is denied"
        assert "exception_requires_scope_review" in record["blockers"]
        assert result.metadata["deterministic_parser"]["proof_ready"] is False
        assert result.metadata["deterministic_parser"]["formula_record_proof_ready_count"] == 1

    def test_converter_keeps_external_applicability_formula_record_blocked(self):
        """External applicability scopes still require citation resolution."""
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)

        result = converter.convert("The chapter applies to food carts.")

        assert result.success
        record = result.metadata["legal_formula_records"][0]
        assert record["formula"] == "AppliesTo(Chapter, FoodCarts)"
        assert record["proof_ready"] is False
        assert record["requires_validation"] is True
        assert record["deterministic_resolution"] == {}
        assert result.metadata["deterministic_parser"]["formula_record_proof_ready_count"] == 0

    def test_converter_excludes_override_clause_from_formula_but_preserves_ir(self):
        """Override clauses are precedence provenance, not factual antecedents."""
        converter = DeonticConverter(use_ml=False, enable_monitoring=False)

        result = converter.convert(
            "Notwithstanding section 5.01.020, the Director may issue a variance."
        )

        assert result.success
        assert result.output is not None
        assert result.output.formula == "P[director](∀x (Director(x) → IssueVariance(x)))"
        assert "Section501020" not in result.output.formula

        parser_element = result.metadata["parser_element"]
        legal_norm_ir = result.metadata["legal_norm_ir"]
        assert legal_norm_ir["overrides"][0]["value"] == "section 5.01.020"
        assert legal_norm_ir["overrides"][0]["span"] == [16, 32]
        assert legal_norm_ir["overrides"][0]["clause_span"] == [0, 33]
        assert parser_element["override_clauses"] == ["section 5.01.020"]
        assert "override_clause_requires_precedence_review" in legal_norm_ir["quality"]["parser_warnings"]
        assert result.metadata["deterministic_parser"]["proof_ready"] is False
        assert "override_clause_requires_precedence_review" in result.metadata["deterministic_parser"]["blockers"]
    
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

    def test_maliciously_mens_rea_is_structured_and_formula_grounded(self):
        """Malicious mens rea should be a slot, not part of the action predicate."""
        from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_from_ir
        from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements("No person shall maliciously damage property.")

        assert len(elements) == 1
        element = elements[0]
        assert element["deontic_operator"] == "F"
        assert element["subject"] == ["person"]
        assert element["action"] == ["maliciously damage property"]
        assert element["mental_state"] == "maliciously"
        assert element["action_verb"] == "damage"
        assert element["action_object"] == "property"
        assert element["llm_repair"]["required"] is False

        norm = LegalNormIR.from_parser_element(element)
        assert norm.mental_state == "maliciously"
        assert build_deontic_formula_from_ir(norm) == (
            "F(∀x (Person(x) ∧ Maliciously(x) → DamageProperty(x)))"
        )

    def test_wilfully_spelling_mens_rea_is_structured(self):
        """British spelling should follow the same deterministic mens rea path."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        element = extract_normative_elements("No person shall wilfully obstruct an inspection.")[0]

        assert element["deontic_operator"] == "F"
        assert element["mental_state"] == "wilfully"
        assert element["action_verb"] == "obstruct"
        assert element["action_object"] == "an inspection"

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

    def test_enumerated_items_can_expand_to_child_norms(self):
        """Formal exporters can opt into one deterministic norm per list item."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_deontic_formula,
            extract_normative_elements,
        )

        elements = extract_normative_elements(
            "The Secretary shall (1) establish procedures; (2) submit a report; and (3) maintain records.",
            expand_enumerations=True,
        )

        assert len(elements) == 3
        assert [element["enumeration_label"] for element in elements] == ["1", "2", "3"]
        assert [element["action"] for element in elements] == [
            ["establish procedures"],
            ["submit a report"],
            ["maintain records"],
        ]
        assert [element["subject"] for element in elements] == [
            ["Secretary"],
            ["Secretary"],
            ["Secretary"],
        ]
        assert all(element["parent_source_id"] for element in elements)
        assert len({element["parent_source_id"] for element in elements}) == 1
        assert len({element["source_id"] for element in elements}) == 3
        assert all(element["promotable_to_theorem"] for element in elements)
        assert all("enumerated_clause_requires_item_level_review" not in element["parser_warnings"] for element in elements)
        assert build_deontic_formula(elements[1]) == "O(∀x (Secretary(x) → SubmitReport(x)))"

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

    def test_defined_terms_resolve_against_later_norms(self):
        """Defined statutory terms should become reusable ontology/KG anchors."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            'In this section, the term "food cart" means a mobile food vending unit. '
            "A food cart shall obtain a permit."
        )

        assert len(elements) == 2
        definition, norm = elements
        assert definition["norm_type"] == "definition"
        assert definition["definition_scope"] == {"scope_type": "section", "raw_text": "in this section"}
        assert norm["defined_term_refs"] == [
            {
                "term": "food cart",
                "definition_body": "a mobile food vending unit",
                "definition_text": 'In this section, the term "food cart" means a mobile food vending unit',
                "definition_scope": {"scope_type": "section", "raw_text": "in this section"},
                "span": [2, 11],
            }
        ]
        assert {
            "subject": "food cart",
            "predicate": "definedBy",
            "object": "a mobile food vending unit",
        } in norm["kg_relationship_hints"]
        assert {
            "subject": "obtain a permit",
            "predicate": "requiresLegalInstrument",
            "object": "permit",
        } in norm["kg_relationship_hints"]
        assert {
            "term": "food cart",
            "type": "defined_term",
            "definition_body": "a mobile food vending unit",
            "span": [2, 11],
        } in norm["ontology_terms"]

    def test_ontology_terms_capture_municipal_entities(self):
        """Ontology hints should expose common municipal actors and instruments."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        element = extract_normative_elements("The Director may issue a permit after inspection of the premises.")[0]

        assert {"term": "Director", "type": "government_actor", "span": [4, 12]} in element["ontology_terms"]
        assert {"term": "permit", "type": "legal_instrument", "span": [25, 31]} in element["ontology_terms"]
        assert {"term": "inspection", "type": "legal_event", "span": [38, 48]} in element["ontology_terms"]
        assert {"term": "premises", "type": "regulated_property", "span": [56, 64]} in element["ontology_terms"]

    def test_ontology_terms_capture_portland_municipal_vocabulary(self):
        """Portland-style offices, instruments, and properties should be grounded."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        element = extract_normative_elements(
            "The Code Hearings Officer may issue a variance to the permittee for work in the right-of-way."
        )[0]

        assert element["actor_type"] == "government_actor"
        assert {"term": "Code Hearings Officer", "type": "government_actor", "span": [4, 25]} in element["ontology_terms"]
        assert {"term": "variance", "type": "legal_instrument", "span": [38, 46]} in element["ontology_terms"]
        assert {"term": "permittee", "type": "legal_person", "span": [54, 63]} in element["ontology_terms"]
        assert {"term": "right-of-way", "type": "regulated_property", "span": [80, 92]} in element["ontology_terms"]
        assert {
            "subject": "issue a variance to the permittee for work in the right-of-way",
            "predicate": "requiresLegalInstrument",
            "object": "variance",
        } in element["kg_relationship_hints"]

    def test_clean_clause_has_non_required_llm_repair_payload(self):
        """Clean deterministic scaffolds should still carry a stable repair payload."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        element = extract_normative_elements("The tenant must pay rent monthly.")[0]

        assert element["llm_repair"]["required"] is False
        assert element["llm_repair"]["reasons"] == []
        assert element["llm_repair"]["target_schema_version"] == element["schema_version"]
        assert len(element["llm_repair"]["prompt_hash"]) == 64
        assert element["llm_repair"]["prompt_context"]["source_text"] == "The tenant must pay rent monthly"

    def test_warning_clause_routes_to_llm_repair_with_context(self):
        """Warnings should become actionable llm_router repair metadata."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        element = extract_normative_elements(
            "The Secretary shall (1) establish procedures; (2) submit reports except as provided in section 552."
        )[0]

        assert element["llm_repair"]["required"] is True
        assert "enumerated_clause_requires_item_level_review" in element["llm_repair"]["reasons"]
        assert "cross_reference_requires_resolution" in element["llm_repair"]["reasons"]
        assert "exception_requires_scope_review" in element["llm_repair"]["reasons"]
        assert element["llm_repair"]["suggested_router"] == "llm_router"
        assert element["llm_repair"]["prompt_template"] == "legal_deontic_parser_repair_v1"
        context = element["llm_repair"]["prompt_context"]
        assert context["legal_frame"]["actor"] == "Secretary"
        assert context["cross_references"] == [{"type": "section", "value": "552", "raw_text": "section 552", "normalized_text": "section 552", "span": [87, 98]}]
        assert context["parser_warnings"] == element["llm_repair"]["reasons"]

    def test_internal_cross_reference_resolution_removes_resolution_warning(self):
        """Known in-document section references should become resolved KG links."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            """5.01.010 Permits.
The applicant shall comply with section 5.01.020.
5.01.020 Applications.
The applicant shall file an application."""
        )

        assert len(elements) == 2
        referrer = elements[0]
        assert referrer["resolved_cross_references"] == [
            {
                "type": "section",
                "value": "5.01.020",
                "raw_text": "section 5.01.020",
                "normalized_text": "section 5.01.020",
                "span": [32, 48],
                "resolution_status": "resolved",
                "target_exists": True,
                "target_section": "5.01.020",
                "target_heading": "Applications",
                "target_hierarchy_path": ["section:5.01.020", "heading:Applications"],
            }
        ]
        assert "cross_reference_requires_resolution" not in referrer["parser_warnings"]
        assert {
            "subject": "law",
            "predicate": "referencesResolvedSection",
            "object": "section:5.01.020",
        } in referrer["kg_relationship_hints"]

    def test_unresolved_cross_reference_still_routes_to_repair(self):
        """Missing in-document section references should remain explicit blockers."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        element = extract_normative_elements(
            """5.01.010 Permits.
The applicant shall comply with section 9.99.999."""
        )[0]

        assert element["resolved_cross_references"][0]["resolution_status"] == "unresolved"
        assert element["resolved_cross_references"][0]["target_exists"] is False
        assert "cross_reference_requires_resolution" in element["parser_warnings"]
        assert "cross_reference_requires_resolution" in element["llm_repair"]["reasons"]
        assert {
            "subject": "law",
            "predicate": "referencesUnresolvedSection",
            "object": "section:9.99.999",
        } in element["kg_relationship_hints"]

    def test_section_range_cross_reference_resolves_known_sections(self):
        """Applicability clauses often cite section ranges in municipal code."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            """5.01.010 General.
The applicant shall comply with sections 5.01.020 through 5.01.030.
5.01.020 Applications.
The applicant shall file an application.
5.01.030 Fees.
The applicant shall pay a fee."""
        )

        referrer = elements[0]
        assert referrer["cross_reference_details"] == [
            {
                "type": "section_range",
                "value": "5.01.020-5.01.030",
                "raw_text": "sections 5.01.020 through 5.01.030",
                "normalized_text": "section_range 5.01.020-5.01.030",
                "span": [32, 66],
                "start_section": "5.01.020",
                "end_section": "5.01.030",
            }
        ]
        assert referrer["resolved_cross_references"][0]["resolution_status"] == "resolved"
        assert [target["section"] for target in referrer["resolved_cross_references"][0]["target_sections"]] == [
            "5.01.020",
            "5.01.030",
        ]
        assert "cross_reference_requires_resolution" not in referrer["parser_warnings"]
        assert {
            "subject": "law",
            "predicate": "referencesResolvedSectionRange",
            "object": "5.01.020-5.01.030",
        } in referrer["kg_relationship_hints"]

    def test_reference_records_flatten_resolved_section_ranges(self):
        """Citation graph exports should get one row per resolved target."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_reference_records,
            extract_normative_elements,
        )

        elements = extract_normative_elements(
            """5.01.010 General.
The applicant shall comply with sections 5.01.020 through 5.01.030.
5.01.020 Applications.
The applicant shall file an application.
5.01.030 Fees.
The applicant shall pay a fee."""
        )
        records = build_reference_records(elements[0])

        assert [record["target_section"] for record in records] == ["5.01.020", "5.01.030"]
        assert records[0]["reference_id"].startswith("ref:")
        assert records[0]["source_id"] == elements[0]["source_id"]
        assert records[0]["reference_type"] == "section_range"
        assert records[0]["resolution_status"] == "resolved"
        assert records[0]["target_exists"] is True
        assert records[1]["target_heading"] == "Fees"

    def test_section_scoped_definition_does_not_leak_to_other_section(self):
        """Definitions scoped to a section should not populate later sections."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            """5.01.010 Definitions.
In this section, the term "food cart" means a mobile food vending unit.
5.01.020 Permits.
A food cart shall obtain a permit."""
        )

        assert len(elements) == 2
        assert elements[0]["definition_scope"] == {"scope_type": "section", "raw_text": "in this section"}
        assert elements[1]["section_context"]["section"] == "5.01.020"
        assert elements[1]["defined_term_refs"] == []

    def test_unquoted_chapter_scoped_definition_applies_within_chapter_only(self):
        """Common municipal definition syntax should not require quoted terms."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            """Chapter 5.01 Food Carts
5.01.010 Definitions.
As used in this chapter, food cart means a mobile food vending unit.
5.01.020 Permits.
A food cart shall obtain a permit.
Chapter 5.02 Restaurants
5.02.010 Permits.
A food cart shall post a notice."""
        )

        definition, same_chapter_norm, other_chapter_norm = elements
        assert definition["defined_term"] == "food cart"
        assert definition["definition_scope"] == {"scope_type": "chapter", "raw_text": "as used in this chapter"}
        assert same_chapter_norm["defined_term_refs"][0]["term"] == "food cart"
        assert same_chapter_norm["defined_term_refs"][0]["definition_body"] == "a mobile food vending unit"
        assert other_chapter_norm["defined_term_refs"] == []

    def test_clean_clause_export_readiness_allows_proof_candidate(self):
        """Clean deterministic parses may become proof candidates."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        element = extract_normative_elements("The tenant must pay rent.")[0]

        readiness = element["export_readiness"]
        assert readiness["kg_ready"] is True
        assert readiness["logic_ready"] is True
        assert readiness["proof_ready"] is True
        assert readiness["theorem_promotable"] is True
        assert "formal_logic_scaffold" in readiness["allowed_exports"]
        assert "proof_candidate" in readiness["allowed_exports"]
        assert readiness["formal_logic_targets"] == ["deontic", "fol", "frame_logic"]
        assert readiness["blockers"] == []

    def test_temporal_clause_export_readiness_adds_temporal_targets(self):
        """Temporal/procedural clauses should advertise temporal/event-calculus exports."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        element = extract_normative_elements("An appeal may be filed within 10 days after the decision.")[0]

        readiness = element["export_readiness"]
        assert readiness["kg_ready"] is True
        assert readiness["proof_ready"] is False
        assert readiness["logic_ready"] is True
        assert "temporal_logic" in readiness["formal_logic_targets"]
        assert "event_calculus" in readiness["formal_logic_targets"]
        assert "llm_repair_queue" in readiness["allowed_exports"]
        assert "procedure_timeline_requires_event_order_review" in readiness["blockers"]
        assert "llm_router_repair" in readiness["requires_validation"]

    def test_warning_clause_export_readiness_blocks_proof_candidate(self):
        """Warned clauses should stay KG/index-ready but not proof-ready."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        element = extract_normative_elements(
            "The Secretary shall (1) establish procedures; (2) submit reports except as provided in section 552."
        )[0]

        readiness = element["export_readiness"]
        assert readiness["kg_ready"] is True
        assert readiness["logic_ready"] is False
        assert readiness["proof_ready"] is False
        assert "knowledge_graph" in readiness["allowed_exports"]
        assert "llm_repair_queue" in readiness["allowed_exports"]
        assert "proof_candidate" not in readiness["allowed_exports"]
        assert "llm_repair_required" in readiness["blockers"]

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

    def test_legacy_parser_element_migrates_to_current_schema(self):
        """Older parser artifacts should be upgraded before exporter use."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            PARSER_SCHEMA_VERSION,
            migrate_parser_element,
            validate_parser_element,
        )

        migrated = migrate_parser_element(
            {
                "schema_version": "deterministic_deontic_v4",
                "text": "The tenant must pay rent monthly",
                "norm_type": "obligation",
                "deontic_operator": "O",
                "modal": "must",
                "subject": ["tenant"],
                "action": ["pay rent monthly"],
                "conditions": ["lease is active"],
                "temporal_constraints": [{"type": "period", "value": "monthly"}],
            }
        )

        assert migrated["schema_version"] == PARSER_SCHEMA_VERSION
        assert migrated["previous_schema_version"] == "deterministic_deontic_v4"
        assert migrated["schema_valid"] is True
        assert validate_parser_element(migrated)["valid"] is True
        assert migrated["condition_details"][0]["normalized_text"] == "lease is active"
        assert migrated["temporal_constraint_details"][0]["temporal_kind"] == "legacy"
        assert migrated["logic_frame"]["action_predicate"] == "PayRentMonthly"
        assert migrated["source_id"].startswith("deontic:")
        assert migrated["formal_terms"]["actor_id"] == "tenant"
        assert migrated["logic_frame"]["source_id"] == migrated["source_id"]
        assert migrated["export_readiness"]["kg_ready"] is True

    def test_core_field_spans_and_logic_frame_are_present(self):
        """Core slots should carry spans and a formal-export bridge frame."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        element = extract_normative_elements("The tenant must pay rent.")[0]

        assert element["field_spans"]["subject"] == [4, 10]
        assert element["field_spans"]["modal"] == [11, 15]
        assert element["field_spans"]["action"] == [16, 24]
        assert element["field_spans"]["action_verb"] == [16, 19]
        assert element["field_spans"]["action_object"] == [20, 24]
        assert element["logic_frame"]["actor"] == "tenant"
        assert element["logic_frame"]["modality"] == "O"
        assert element["logic_frame"]["action_predicate"] == "PayRent"
        assert element["logic_frame"]["field_spans"] == element["field_spans"]
        assert element["logic_frame"]["readiness"]["schema_valid"] is True
        assert element["logic_frame"]["readiness"]["promotable_to_theorem"] is True

    def test_source_id_citation_and_formal_terms_are_stable(self):
        """Parquet/KG/proof exports need deterministic join keys and symbols."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        text = """Chapter 5.01 Food Carts
5.01.020 Permits.
The applicant shall obtain a permit."""
        first = extract_normative_elements(text)[0]
        second = extract_normative_elements(text)[0]

        assert first["source_id"].startswith("deontic:")
        assert first["source_id"] == second["source_id"]
        assert first["canonical_citation"] == "chapter 5.01 / section 5.01.020"
        assert first["formal_terms"]["source_id"] == first["source_id"]
        assert first["formal_terms"]["section_id"] == "5_01_020"
        assert first["formal_terms"]["actor_id"] == "applicant"
        assert first["formal_terms"]["actor_predicate"] == "Applicant"
        assert first["formal_terms"]["action_predicate"] == "ObtainPermit"
        assert first["formal_terms"]["category_predicate"] == "PermitOrLicense"
        assert first["logic_frame"]["source_id"] == first["source_id"]
        assert first["logic_frame"]["canonical_citation"] == first["canonical_citation"]
        assert first["logic_frame"]["formal_terms"] == first["formal_terms"]

    def test_kg_triples_are_parquet_friendly_and_stable(self):
        """Relationship hints should become normalized rows with provenance."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_kg_triples,
            extract_normative_elements,
        )

        element = extract_normative_elements(
            """5.01.020 Permits.
The applicant shall obtain a permit."""
        )[0]
        triples = build_kg_triples(element)
        repeated = build_kg_triples(element)

        assert triples == repeated
        assert triples[0]["triple_id"].startswith("kg:")
        assert triples[0]["source_id"] == element["source_id"]
        assert triples[0]["canonical_citation"] == "section 5.01.020"
        assert triples[0]["subject_id"] == "law"
        assert triples[0]["predicate_id"] == "imposesdutyon"
        assert triples[0]["object_id"] == "applicant"
        assert triples[0]["provenance"]["source_span"] == element["source_span"]
        assert {
            "subject": "obtain a permit",
            "predicate": "requiresLegalInstrument",
            "object": "permit",
        } in [
            {"subject": row["subject"], "predicate": row["predicate"], "object": row["object"]}
            for row in triples
        ]

    def test_formal_logic_record_is_parquet_friendly_and_readiness_aware(self):
        """Formal exporters should receive one stable row per parser element."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_formal_logic_record,
            extract_normative_elements,
        )

        element = extract_normative_elements("The tenant must pay rent.")[0]
        record = build_formal_logic_record(element)
        repeated = build_formal_logic_record(element)

        assert record == repeated
        assert record["formula_id"].startswith("formula:")
        assert record["source_id"] == element["source_id"]
        assert record["logic_family"] == "deontic"
        assert record["formula"] == "O(∀x (Tenant(x) → PayRent(x)))"
        assert record["formal_terms"]["action_predicate"] == "PayRent"
        assert record["proof_candidate"] is True
        assert record["formal_logic_targets"] == ["deontic", "fol", "frame_logic"]
        assert record["parser_warnings"] == []
        assert record["provenance"]["text"] == "The tenant must pay rent"

    def test_proof_obligation_record_separates_candidates_from_blocked_rows(self):
        """Proof queues should include deterministic blockers for repair routing."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_proof_obligation_record,
            extract_normative_elements,
        )

        clean = extract_normative_elements("The tenant must pay rent.")[0]
        blocked = extract_normative_elements(
            "The Secretary shall (1) establish procedures; (2) submit reports except as provided in section 552."
        )[0]

        clean_record = build_proof_obligation_record(clean)
        blocked_record = build_proof_obligation_record(blocked)

        assert clean_record["proof_obligation_id"].startswith("proof:")
        assert clean_record["proof_candidate"] is True
        assert clean_record["blocked"] is False
        assert "fol_resolution" in clean_record["proof_systems"]
        assert blocked_record["proof_candidate"] is False
        assert blocked_record["blocked"] is True
        assert "llm_repair_required" in blocked_record["blockers"]
        assert "human_or_llm_semantic_review" in blocked_record["requires_validation"]

    def test_export_record_bundle_collects_all_parquet_tables(self):
        """Processors should be able to request all export rows at once."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_export_record_bundle,
            extract_normative_elements,
        )

        element = extract_normative_elements(
            "The Director shall issue a permit within 10 business days after application unless the application is incomplete."
        )[0]
        bundle = build_export_record_bundle(element)

        assert bundle["source_id"] == element["source_id"]
        assert bundle["canonical"]["source_id"] == element["source_id"]
        assert bundle["formal_logic"][0]["source_id"] == element["source_id"]
        assert bundle["proof_obligations"][0]["source_id"] == element["source_id"]
        assert bundle["knowledge_graph_triples"]
        assert [record["slot_type"] for record in bundle["clause_records"]] == ["exception"]
        assert bundle["procedure_event_records"]
        assert bundle["sanction_records"] == []

    def test_ontology_entity_records_are_parquet_friendly(self):
        """Ontology terms should flatten into entity rows with stable IDs."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_ontology_entity_records,
            extract_normative_elements,
        )

        element = extract_normative_elements(
            "The Code Hearings Officer may issue a variance to the permittee."
        )[0]
        records = build_ontology_entity_records(element)

        assert records[0]["entity_id"].startswith("entity:")
        assert records[0]["source_id"] == element["source_id"]
        assert {
            "term": "Code Hearings Officer",
            "term_id": "code_hearings_officer",
            "entity_type": "government_actor",
        } in [
            {
                "term": record["term"],
                "term_id": record["term_id"],
                "entity_type": record["entity_type"],
            }
            for record in records
        ]
        assert {
            "term": "permittee",
            "term_id": "permittee",
            "entity_type": "legal_person",
        } in [
            {
                "term": record["term"],
                "term_id": record["term_id"],
                "entity_type": record["entity_type"],
            }
            for record in records
        ]

    def test_repair_queue_record_is_stable_for_warned_clause(self):
        """LLM repair queues should be first-class parquet rows."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_repair_queue_record,
            extract_normative_elements,
        )

        element = extract_normative_elements(
            "The Secretary shall (1) establish procedures; (2) submit reports except as provided in section 552."
        )[0]
        record = build_repair_queue_record(element)
        repeated = build_repair_queue_record(element)

        assert record == repeated
        assert record["repair_id"].startswith("repair:")
        assert record["source_id"] == element["source_id"]
        assert record["required"] is True
        assert record["suggested_router"] == "llm_router"
        assert "exception_requires_scope_review" in record["reasons"]
        assert record["prompt_hash"] == element["llm_repair"]["prompt_hash"]

    def test_document_export_tables_aggregate_multiple_elements(self):
        """Document processors should receive table-shaped exports for all elements."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_document_export_tables,
            extract_normative_elements,
        )

        elements = extract_normative_elements(
            """5.01.010 Permit duties.
The applicant shall obtain a permit unless approval is denied.
Failure to comply with this section is a violation.
A violation of this section is punishable by a fine of $500."""
        )
        tables = build_document_export_tables(elements)

        assert len(tables["canonical"]) == 3
        assert len(tables["formal_logic"]) == 3
        assert len(tables["proof_obligations"]) == 3
        assert tables["knowledge_graph_triples"]
        assert tables["reference_records"]
        assert tables["sanction_records"][0]["sanction_type"] == "fine"
        assert all(row["source_id"] for row in tables["canonical"])
        assert tables["repair_queue"] == []

    def test_document_export_manifest_summarizes_table_counts_and_quality(self):
        """Dataset uploads should carry deterministic export metadata."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            PARSER_SCHEMA_VERSION,
            build_document_export_manifest,
            build_document_export_tables,
            extract_normative_elements,
        )

        elements = extract_normative_elements(
            "The tenant must pay rent. The tenant shall not pay rent."
        )
        tables = build_document_export_tables(elements)
        manifest = build_document_export_manifest(elements, tables)
        repeated = build_document_export_manifest(elements, tables)

        assert manifest == repeated
        assert manifest["manifest_id"].startswith("manifest:")
        assert manifest["schema_version"] == PARSER_SCHEMA_VERSION
        assert manifest["element_count"] == 2
        assert manifest["table_counts"]["canonical"] == 2
        assert manifest["table_counts"]["proof_obligations"] == 2
        assert manifest["quality"]["schema_valid"] == 2
        assert manifest["quality"]["repair_required"] == 2
        assert manifest["quality"]["proof_candidates"] == 0

    def test_document_export_table_validation_catches_integrity_errors(self):
        """Parquet writers should be able to fail fast on malformed tables."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_document_export_tables,
            extract_normative_elements,
            validate_document_export_tables,
        )

        elements = extract_normative_elements("The tenant must pay rent.")
        tables = build_document_export_tables(elements)
        validation = validate_document_export_tables(tables)

        assert validation["valid"] is True
        assert validation["errors"] == []
        broken = dict(tables)
        broken["formal_logic"] = []
        broken_validation = validate_document_export_tables(broken)
        assert broken_validation["valid"] is False
        assert "formal_logic_count_mismatch" in broken_validation["errors"]

    def test_export_table_specs_and_validation_check_primary_keys(self):
        """Every export table should declare and validate stable row IDs."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_document_export_tables,
            extract_normative_elements,
            get_export_table_specs,
            validate_document_export_tables,
        )

        elements = extract_normative_elements("The tenant must pay rent.")
        tables = build_document_export_tables(elements)
        specs = get_export_table_specs()

        assert specs["canonical"]["primary_key"] == "source_id"
        assert specs["formal_logic"]["primary_key"] == "formula_id"
        assert specs["proof_obligations"]["primary_key"] == "proof_obligation_id"
        assert validate_document_export_tables(tables)["valid"] is True
        broken = {name: list(rows) for name, rows in tables.items()}
        broken["formal_logic"] = [dict(broken["formal_logic"][0]), dict(broken["formal_logic"][0])]
        broken_validation = validate_document_export_tables(broken)
        assert broken_validation["valid"] is False
        assert "formal_logic_formula_id_not_unique" in broken_validation["errors"]

    def test_export_tables_serialize_nested_fields_for_parquet(self):
        """Simple parquet writers can request deterministic scalar cells."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_document_export_tables,
            extract_normative_elements,
            serialize_export_tables_for_parquet,
        )

        elements = extract_normative_elements("The tenant must pay rent.")
        tables = build_document_export_tables(elements)
        serialized = serialize_export_tables_for_parquet(tables)

        assert isinstance(serialized["canonical"][0]["logic_frame"], str)
        assert serialized["canonical"][0]["logic_frame"].startswith("{")
        assert isinstance(serialized["formal_logic"][0]["formal_terms"], str)
        assert '"action_predicate": "PayRent"' in serialized["formal_logic"][0]["formal_terms"]
        assert serialized["formal_logic"][0]["source_id"] == elements[0]["source_id"]

    def test_document_export_parquet_writer_when_dependencies_available(self, tmp_path):
        """The optional writer should create one parquet file per export table."""
        pytest.importorskip("pandas")
        pytest.importorskip("pyarrow")
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            extract_normative_elements,
            write_document_export_parquet,
        )

        elements = extract_normative_elements("The tenant must pay rent.")
        result = write_document_export_parquet(elements, str(tmp_path))

        assert result["validation"]["valid"] is True
        assert result["manifest"]["element_count"] == 1
        assert result["manifest_path"].endswith("manifest.json")
        assert set(result["parquet_paths"]) >= {"canonical", "formal_logic", "proof_obligations"}
        for path in result["parquet_paths"].values():
            assert tmp_path.joinpath(path.split("/")[-1]).exists()

    def test_definition_field_spans_feed_logic_frame(self):
        """Definition terms and bodies should be span-addressable."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        element = extract_normative_elements(
            'In this section, the term "food cart" means a mobile food vending unit.'
        )[0]

        assert element["field_spans"]["defined_term"] == [27, 36]
        assert element["field_spans"]["definition_body"] == [44, 70]
        assert element["logic_frame"]["norm_type"] == "definition"
        assert element["logic_frame"]["actor"] == "food cart"

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
                "quantity": 10,
                "unit": "day",
                "calendar": "calendar",
                "anchor_event": "application",
                "direction": "after",
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

    def test_clause_records_flatten_conditions_exceptions_and_overrides(self):
        """Formal exporters should not need to unpack every clause list manually."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_clause_records,
            extract_normative_elements,
        )

        element = extract_normative_elements(
            "Notwithstanding section 5.01.020, subject to approval, the Director shall issue a permit unless the application is incomplete."
        )[0]
        records = build_clause_records(element)

        assert [record["slot_type"] for record in records] == ["condition", "exception", "override"]
        assert records[0]["clause_id"].startswith("clause:")
        assert records[0]["source_id"] == element["source_id"]
        assert records[0]["effect"] == "antecedent"
        assert records[0]["predicate"] == "Approval"
        assert records[1]["effect"] == "negated_antecedent"
        assert records[1]["predicate"] == "ApplicationIsIncomplete"
        assert records[2]["effect"] == "precedence_modifier"
        assert records[2]["normalized_text"] == "section 5.01.020"

    def test_business_day_deadline_is_normalized_for_temporal_logic(self):
        """Municipal appeal windows often use business-day deadlines."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        element = extract_normative_elements(
            "The permittee may appeal within 10 business days after notice."
        )[0]

        assert element["temporal_constraints"] == [
            {"type": "deadline", "value": "10 business days after notice"}
        ]
        assert element["temporal_constraint_details"] == [
            {
                "type": "deadline",
                "temporal_kind": "within_duration",
                "value": "10 business days after notice",
                "anchor": "notice",
                "quantity": 10,
                "unit": "day",
                "calendar": "business",
                "anchor_event": "notice",
                "direction": "after",
                "raw_text": "within 10 business days after notice",
                "normalized_text": "10 business days after notice",
                "span": [25, 61],
            }
        ]
        assert "temporal_logic" in element["export_readiness"]["formal_logic_targets"]

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

    def test_title_chapter_section_hierarchy_details_are_preserved(self):
        """Municipal hierarchy should include title/chapter/section details with spans."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        text = """Title 5 Business Licenses
Chapter 5.01 Food Carts
5.01.010 Permits required.
The applicant shall obtain a permit."""
        element = extract_normative_elements(text)[0]

        assert element["hierarchy_path"] == [
            "title:5",
            "chapter:5.01",
            "section:5.01.010",
            "heading:Permits required",
        ]
        assert element["section_context"] == {"section": "5.01.010", "heading": "Permits required"}
        assert element["hierarchy_details"] == [
            {"level": "title", "value": "5", "heading": "Business Licenses", "span": [0, 25]},
            {"level": "chapter", "value": "5.01", "heading": "Food Carts", "span": [26, 49]},
            {"level": "section", "value": "5.01.010", "heading": "Permits required", "span": [50, 76]},
        ]

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

    def test_applicability_clause_is_scope_rule_not_obligation(self):
        """Applicability clauses should produce scope logic, not fake duties."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_deontic_formula,
            extract_normative_elements,
        )

        elements = extract_normative_elements("This section applies to food carts and mobile vendors.")

        assert len(elements) == 1
        element = elements[0]
        assert element["norm_type"] == "applicability"
        assert element["deontic_operator"] == "APP"
        assert element["subject"] == ["this section"]
        assert element["action"] == ["apply to food carts and mobile vendors"]
        assert element["legal_frame"]["category"] == "applicability"
        assert build_deontic_formula(element) == "AppliesTo(ThisSection, FoodCartsAndMobileVendors)"
        assert {
            "subject": "law",
            "predicate": "appliesTo",
            "object": "this section",
        } in element["kg_relationship_hints"]

    def test_non_applicability_clause_is_exemption_scope_rule(self):
        """Non-applicability clauses should become deterministic exemptions."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_deontic_formula,
            extract_normative_elements,
        )

        elements = extract_normative_elements("This chapter does not apply to emergency work.")

        assert len(elements) == 1
        element = elements[0]
        assert element["norm_type"] == "exemption"
        assert element["deontic_operator"] == "EXEMPT"
        assert element["subject"] == ["this chapter"]
        assert element["action"] == ["not apply to emergency work"]
        assert element["legal_frame"]["category"] == "exemption"
        assert build_deontic_formula(element) == "ExemptFrom(ThisChapter, NotApplyEmergencyWork)"

    def test_exempt_from_clause_is_exemption_scope_rule(self):
        """Direct exempt-from syntax should be parsed without LLM repair."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_deontic_formula,
            extract_normative_elements,
        )

        elements = extract_normative_elements("Emergency repairs are exempt from permit requirements.")

        assert len(elements) == 1
        element = elements[0]
        assert element["norm_type"] == "exemption"
        assert element["deontic_operator"] == "EXEMPT"
        assert element["subject"] == ["Emergency repairs"]
        assert element["action"] == ["exempt from permit requirements"]
        assert element["legal_frame"]["category"] == "exemption"
        assert build_deontic_formula(element) == "ExemptFrom(EmergencyRepairs, PermitRequirements)"

    def test_not_required_permit_clause_is_exemption_scope_rule(self):
        """Not-required instrument clauses should become explicit exemptions."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_deontic_formula,
            extract_normative_elements,
        )

        elements = extract_normative_elements("A permit is not required for emergency work.")

        assert len(elements) == 1
        element = elements[0]
        assert element["norm_type"] == "exemption"
        assert element["deontic_operator"] == "EXEMPT"
        assert element["subject"] == ["emergency work"]
        assert element["action"] == ["exempt from permit"]
        assert element["llm_repair"]["required"] is False
        assert element["export_readiness"]["proof_ready"] is True
        assert build_deontic_formula(element) == "ExemptFrom(EmergencyWork, Permit)"

    def test_instrument_validity_clause_is_lifecycle_logic(self):
        """Instrument duration clauses should not be dropped as non-normative text."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_deontic_formula,
            extract_normative_elements,
        )

        elements = extract_normative_elements("The license is valid for 30 days.")

        assert len(elements) == 1
        element = elements[0]
        assert element["norm_type"] == "instrument_lifecycle"
        assert element["deontic_operator"] == "LIFE"
        assert element["subject"] == ["license"]
        assert element["action"] == ["valid for 30 days"]
        assert element["legal_frame"]["category"] == "instrument_lifecycle"
        assert element["llm_repair"]["required"] is False
        assert build_deontic_formula(element) == "ValidFor(License, 30Days)"

    def test_instrument_expiration_clause_is_lifecycle_logic(self):
        """Expiration clauses should become deterministic lifecycle formulas."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_deontic_formula,
            extract_normative_elements,
        )

        elements = extract_normative_elements("The permit expires one year after issuance.")

        assert len(elements) == 1
        element = elements[0]
        assert element["norm_type"] == "instrument_lifecycle"
        assert element["subject"] == ["permit"]
        assert element["action"] == ["expires one year after issuance"]
        assert {
            "subject": "law",
            "predicate": "setsLifecycleFor",
            "object": "permit",
        } in element["kg_relationship_hints"]
        assert build_deontic_formula(element) == "ExpiresAfter(Permit, OneYearAfterIssuance)"

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

    def test_this_section_reference_resolves_to_current_section(self):
        """Local self-references should be explicit for violation and penalty linking."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            """5.01.010 Duties.
Failure to comply with this section is a violation."""
        )

        assert elements[0]["resolved_cross_references"] == [
            {
                "type": "section",
                "value": "this section",
                "raw_text": "this section",
                "normalized_text": "section this section",
                "span": [23, 35],
                "resolution_status": "resolved",
                "target_exists": True,
                "target_section": "5.01.010",
                "target_heading": "Duties",
                "target_hierarchy_path": ["section:5.01.010", "heading:Duties"],
            }
        ]
        assert "cross_reference_requires_resolution" not in elements[0]["parser_warnings"]
        assert {
            "subject": "law",
            "predicate": "referencesResolvedSection",
            "object": "section:5.01.010",
        } in elements[0]["kg_relationship_hints"]

    def test_this_paragraph_reference_resolves_to_current_paragraph(self):
        """Paragraph-local self-references should be resolved in hierarchy metadata."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            """5.01.010 Duties.
(1) Failure to comply with this paragraph is a violation."""
        )

        assert elements[0]["resolved_cross_references"][0]["resolution_status"] == "resolved"
        assert elements[0]["resolved_cross_references"][0]["target_section"] == "5.01.010"
        assert elements[0]["resolved_cross_references"][0]["target_hierarchy_path"] == ["paragraph:1"]
        assert "cross_reference_requires_resolution" not in elements[0]["parser_warnings"]

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

    def test_violation_and_penalty_link_to_enforced_section(self):
        """Enforcement clauses should point to the section they make provable."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            """5.01.010 Permit duties.
The applicant shall obtain a permit.
Failure to comply with this section is a violation.
A violation of this section is punishable by a fine of $500."""
        )

        assert len(elements) == 3
        violation = elements[1]
        penalty = elements[2]
        assert violation["enforcement_links"] == [
            {
                "type": "defines_violation_of",
                "target_type": "section",
                "target_section": "5.01.010",
                "target_heading": "Permit duties",
                "target_hierarchy_path": ["section:5.01.010", "heading:Permit duties"],
                "resolution_status": "resolved",
                "source": "cross_reference",
            }
        ]
        assert penalty["enforcement_links"] == [
            {
                "type": "penalizes_violation_of",
                "target_type": "section",
                "target_section": "5.01.010",
                "target_heading": "Permit duties",
                "target_hierarchy_path": ["section:5.01.010", "heading:Permit duties"],
                "resolution_status": "resolved",
                "source": "cross_reference",
                "target_violation_text": "Failure to comply with this section is a violation",
                "target_violation_span": [61, 111],
            }
        ]
        assert {
            "subject": "violation",
            "predicate": "violatesSection",
            "object": "5.01.010",
        } in violation["kg_relationship_hints"]
        assert {
            "subject": "penalty",
            "predicate": "penalizesViolationOf",
            "object": "5.01.010",
        } in penalty["kg_relationship_hints"]
        assert penalty["logic_frame"]["enforcement_links"] == penalty["enforcement_links"]

    def test_penalty_infers_same_section_violation_target(self):
        """Penalties without explicit refs can still link to a same-section violation."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            """5.01.010 Permit duties.
Failure to comply with this section is a violation.
A violation is punishable by a fine of $500."""
        )

        penalty = elements[1]
        assert penalty["enforcement_links"][0]["type"] == "penalizes_violation_of"
        assert penalty["enforcement_links"][0]["target_section"] == "5.01.010"
        assert penalty["enforcement_links"][0]["resolution_status"] == "inferred"
        assert penalty["enforcement_links"][0]["source"] == "same_section_violation"
        assert penalty["enforcement_links"][0]["target_violation_text"] == "Failure to comply with this section is a violation"

    def test_penalty_bounds_and_recurrence_are_normalized(self):
        """Municipal penalty ranges and recurring violations should be structured."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        element = extract_normative_elements(
            "A violation is punishable by a fine of not less than $100 and not more than $1,000. "
            "Each day constitutes a separate violation."
        )[0]

        assert element["penalty"]["minimum_amount"]["raw_text"] == "$100"
        assert element["penalty"]["minimum_amount"]["numeric_value"] == "100"
        assert element["penalty"]["maximum_amount"]["raw_text"] == "$1,000"
        assert element["penalty"]["maximum_amount"]["numeric_value"] == "1000"
        assert element["penalty"]["recurrence"] == {
            "type": "per_day",
            "raw_text": "Each day constitutes a separate violation",
            "span": [84, 125],
        }

    def test_civil_penalty_range_classification_is_structured(self):
        """Civil/criminal penalty class and modality should be deterministic slots."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_sanction_records,
            extract_normative_elements,
        )

        element = extract_normative_elements(
            "A violation is punishable by a civil fine of not less than $100 and not more than $500 per violation."
        )[0]

        penalty = element["penalty"]
        assert penalty["sanction_class"] == "civil"
        assert penalty["sanction_modality"] == "mandatory"
        assert penalty["has_range"] is True
        assert penalty["minimum_amount"]["numeric_value"] == "100"
        assert penalty["maximum_amount"]["numeric_value"] == "500"
        assert penalty["recurrence"]["type"] == "per_violation"

        records = build_sanction_records(element)
        assert records[0]["sanction_class"] == "civil"
        assert records[0]["sanction_modality"] == "mandatory"
        assert records[0]["has_range"] is True
        assert records[0]["recurrence"]["type"] == "per_violation"

    def test_penalty_imprisonment_duration_is_normalized(self):
        """Jail/imprisonment sanctions should expose duration atoms."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        element = extract_normative_elements(
            "A violation is punishable by imprisonment for not more than 30 days."
        )[0]

        assert element["penalty"]["has_imprisonment"] is True
        assert element["penalty"]["imprisonment_duration"] == {
            "raw_text": "imprisonment for not more than 30 days",
            "quantity": 30,
            "unit": "day",
            "span": [29, 67],
        }

    def test_sanction_records_flatten_fines_imprisonment_and_recurrence(self):
        """Penalty exporters should get sanction-level rows."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_sanction_records,
            extract_normative_elements,
        )

        element = extract_normative_elements(
            "A violation is punishable by a fine of not more than $500 or imprisonment for not more than 30 days. "
            "Each day constitutes a separate violation."
        )[0]
        records = build_sanction_records(element)

        assert [record["sanction_type"] for record in records] == [
            "fine",
            "fine",
            "imprisonment",
            "recurrence",
        ]
        assert records[0]["sanction_id"].startswith("sanction:")
        assert records[0]["source_id"] == element["source_id"]
        assert records[1]["role"] == "maximum"
        assert records[1]["detail"]["numeric_value"] == "500"
        assert records[2]["detail"]["quantity"] == 30
        assert records[3]["detail"]["type"] == "per_day"

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

    def test_procedure_event_records_flatten_event_chain(self):
        """Event-calculus exporters should get stable event rows."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_procedure_event_records,
            extract_normative_elements,
        )

        element = extract_normative_elements(
            "The Director shall provide notice and hold a hearing within 10 business days after notice."
        )[0]
        records = build_procedure_event_records(element)

        assert [record["event"] for record in records] == ["notice", "hearing"]
        assert records[0]["event_id"].startswith("event:")
        assert records[0]["source_id"] == element["source_id"]
        assert records[0]["event_symbol"] == "Notice"
        assert records[0]["event_order"] == 1
        assert records[0]["is_trigger"] is True
        assert records[1]["is_terminal"] is True
        assert records[0]["temporal_anchors"][0]["calendar"] == "business"
        assert records[0]["temporal_anchors"][0]["quantity"] == 10
        assert records[0]["actor_id"] == "director"

    def test_procedure_relations_capture_upon_after_and_before_connectors(self):
        """Procedural connectors should become event-ordering atoms."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            build_procedure_event_records,
            extract_normative_elements,
        )

        element = extract_normative_elements(
            "Upon receipt of an application, the Bureau shall inspect the premises before approval."
        )[0]

        assert element["procedure"]["trigger_event"] == "application"
        assert element["procedure"]["terminal_event"] == "inspection"
        assert {
            "event": "inspection",
            "relation": "triggered_by_receipt_of",
            "anchor_event": "application",
            "raw_text": "Upon receipt of an application",
            "span": [0, 30],
        } in element["procedure"]["event_relations"]
        assert any(
            relation["event"] == "inspection"
            and relation["relation"] == "before"
            and relation["anchor_event"] == "issuance"
            for relation in element["procedure"]["event_relations"]
        )

        records = build_procedure_event_records(element)
        inspection_record = next(record for record in records if record["event"] == "inspection")
        assert "triggered_by_receipt_of" in inspection_record["relation_types"]
        assert "application" in inspection_record["anchor_events"]
        assert "issuance" in inspection_record["anchor_events"]

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

    def test_conflict_detection_handles_parser_element_lists(self):
        """Conflict detection should work on current parser element schema."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
            detect_normative_conflicts,
            extract_normative_elements,
        )

        elements = extract_normative_elements(
            "The applicant shall file an application. The applicant shall not file an application."
        )
        conflicts = detect_normative_conflicts(elements)

        assert len(conflicts) == 1
        assert conflicts[0]["type"] == "direct_conflict"
        assert conflicts[0]["severity"] == "high"
        assert conflicts[0]["element_indices"] == [0, 1]

    def test_conflicting_norms_block_proof_export_readiness(self):
        """Contradictory norms should carry conflict links and require repair."""
        from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

        elements = extract_normative_elements(
            "The applicant shall file an application. The applicant shall not file an application."
        )

        assert elements[0]["conflict_links"][0]["type"] == "direct_conflict"
        assert elements[1]["conflict_links"][0]["type"] == "direct_conflict"
        assert "normative_conflict_requires_resolution" in elements[0]["parser_warnings"]
        assert "normative_conflict_requires_resolution" in elements[1]["llm_repair"]["reasons"]
        assert elements[0]["export_readiness"]["proof_ready"] is False
        assert "proof_candidate" not in elements[1]["export_readiness"]["allowed_exports"]
    
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
