#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Comprehensive tests for Medical Theorem Framework.

This test suite covers:
- MedicalEntity and theorem types
- Causal relationship validation
- Treatment outcome processing
- Temporal progression analysis
- Confidence level calculations
- Fuzzy logic validation
- Time-series validation
"""

import pytest
from datetime import datetime, timedelta
from typing import Dict, Any

try:
    from ipfs_datasets_py.logic.integration.medical_theorem_framework import (
        MedicalTheoremType,
        ConfidenceLevel,
        MedicalEntity,
        TemporalConstraint,
        MedicalTheorem,
        MedicalTheoremGenerator,
        FuzzyLogicValidator,
        TimeSeriesTheoremValidator
    )
    MEDICAL_THEOREM_AVAILABLE = True
    SKIP_REASON = ""
except ImportError as e:
    MEDICAL_THEOREM_AVAILABLE = False
    SKIP_REASON = f"Medical theorem framework not available: {e}"


@pytest.mark.skipif(not MEDICAL_THEOREM_AVAILABLE, reason=SKIP_REASON)
class TestMedicalEntity:
    """Test MedicalEntity dataclass."""
    
    def test_medical_entity_creation_substance(self):
        """
        GIVEN entity parameters for a substance
        WHEN MedicalEntity is created
        THEN entity should be properly initialized with correct attributes
        """
        entity = MedicalEntity(
            entity_type="substance",
            name="tide pods",
            properties={"route": "ingestion", "dose": "unknown"}
        )
        
        assert entity.entity_type == "substance"
        assert entity.name == "tide pods"
        assert entity.properties["route"] == "ingestion"
        assert entity.properties["dose"] == "unknown"
    
    def test_medical_entity_creation_condition(self):
        """
        GIVEN entity parameters for a medical condition
        WHEN MedicalEntity is created
        THEN entity should be properly initialized
        """
        entity = MedicalEntity(
            entity_type="condition",
            name="poisoning",
            properties={"severity": "severe", "onset": "acute"}
        )
        
        assert entity.entity_type == "condition"
        assert entity.name == "poisoning"
        assert entity.properties["severity"] == "severe"
    
    def test_medical_entity_creation_treatment(self):
        """
        GIVEN entity parameters for a treatment
        WHEN MedicalEntity is created
        THEN entity should be properly initialized
        """
        entity = MedicalEntity(
            entity_type="treatment",
            name="aspirin",
            properties={"dosage": "100mg", "frequency": "daily"}
        )
        
        assert entity.entity_type == "treatment"
        assert entity.name == "aspirin"
        assert entity.properties["dosage"] == "100mg"
    
    def test_medical_entity_empty_properties(self):
        """
        GIVEN entity with empty properties
        WHEN MedicalEntity is created
        THEN entity should accept empty properties dict
        """
        entity = MedicalEntity(
            entity_type="outcome",
            name="recovery",
            properties={}
        )
        
        assert entity.entity_type == "outcome"
        assert entity.name == "recovery"
        assert len(entity.properties) == 0


@pytest.mark.skipif(not MEDICAL_THEOREM_AVAILABLE, reason=SKIP_REASON)
class TestTemporalConstraint:
    """Test TemporalConstraint dataclass."""
    
    def test_temporal_constraint_with_time_to_effect(self):
        """
        GIVEN temporal parameters with time_to_effect
        WHEN TemporalConstraint is created
        THEN constraint should be properly initialized
        """
        constraint = TemporalConstraint(
            time_to_effect=timedelta(hours=2),
            duration=timedelta(days=7)
        )
        
        assert constraint.time_to_effect == timedelta(hours=2)
        assert constraint.duration == timedelta(days=7)
        assert constraint.time_window is None
        assert constraint.temporal_operator is None
    
    def test_temporal_constraint_with_time_window(self):
        """
        GIVEN temporal parameters with time_window
        WHEN TemporalConstraint is created
        THEN constraint should store time window correctly
        """
        start = datetime(2024, 1, 1)
        end = datetime(2024, 12, 31)
        constraint = TemporalConstraint(
            time_window=(start, end),
            temporal_operator="during"
        )
        
        assert constraint.time_window == (start, end)
        assert constraint.temporal_operator == "during"
    
    def test_temporal_constraint_all_parameters(self):
        """
        GIVEN all temporal parameters
        WHEN TemporalConstraint is created
        THEN all fields should be properly set
        """
        start = datetime(2024, 1, 1)
        end = datetime(2024, 12, 31)
        constraint = TemporalConstraint(
            time_to_effect=timedelta(minutes=30),
            duration=timedelta(hours=6),
            time_window=(start, end),
            temporal_operator="after"
        )
        
        assert constraint.time_to_effect == timedelta(minutes=30)
        assert constraint.duration == timedelta(hours=6)
        assert constraint.time_window == (start, end)
        assert constraint.temporal_operator == "after"


@pytest.mark.skipif(not MEDICAL_THEOREM_AVAILABLE, reason=SKIP_REASON)
class TestMedicalTheorem:
    """Test MedicalTheorem dataclass."""
    
    def test_medical_theorem_causal_relationship(self):
        """
        GIVEN a causal relationship theorem
        WHEN MedicalTheorem is created
        THEN theorem should be properly initialized with all attributes
        """
        antecedent = MedicalEntity("substance", "tide pods", {"route": "ingestion"})
        consequent = MedicalEntity("condition", "poisoning", {"severity": "severe"})
        
        theorem = MedicalTheorem(
            theorem_id="TIDE_POD_001",
            theorem_type=MedicalTheoremType.CAUSAL_RELATIONSHIP,
            antecedent=antecedent,
            consequent=consequent,
            confidence=ConfidenceLevel.VERY_HIGH,
            temporal_constraint=TemporalConstraint(time_to_effect=timedelta(hours=1))
        )
        
        assert theorem.theorem_id == "TIDE_POD_001"
        assert theorem.theorem_type == MedicalTheoremType.CAUSAL_RELATIONSHIP
        assert theorem.antecedent.name == "tide pods"
        assert theorem.consequent.name == "poisoning"
        assert theorem.confidence == ConfidenceLevel.VERY_HIGH
        assert theorem.temporal_constraint.time_to_effect == timedelta(hours=1)
        assert theorem.evidence_sources == []  # __post_init__ default
    
    def test_medical_theorem_treatment_outcome(self):
        """
        GIVEN a treatment-outcome theorem
        WHEN MedicalTheorem is created
        THEN theorem should represent treatment relationship
        """
        antecedent = MedicalEntity("treatment", "aspirin", {"dosage": "100mg"})
        consequent = MedicalEntity("outcome", "reduced_risk", {"condition": "heart_attack"})
        
        theorem = MedicalTheorem(
            theorem_id="ASPIRIN_001",
            theorem_type=MedicalTheoremType.TREATMENT_OUTCOME,
            antecedent=antecedent,
            consequent=consequent,
            confidence=ConfidenceLevel.HIGH,
            evidence_sources=["NCT12345", "NCT67890"]
        )
        
        assert theorem.theorem_type == MedicalTheoremType.TREATMENT_OUTCOME
        assert len(theorem.evidence_sources) == 2
        assert "NCT12345" in theorem.evidence_sources
    
    def test_medical_theorem_risk_assessment(self):
        """
        GIVEN a risk assessment theorem
        WHEN MedicalTheorem is created
        THEN theorem should represent risk relationship
        """
        antecedent = MedicalEntity("behavior", "smoking", {"frequency": "daily"})
        consequent = MedicalEntity("condition", "lung_cancer", {"risk": "increased"})
        
        theorem = MedicalTheorem(
            theorem_id="SMOKE_RISK_001",
            theorem_type=MedicalTheoremType.RISK_ASSESSMENT,
            antecedent=antecedent,
            consequent=consequent,
            confidence=ConfidenceLevel.VERY_HIGH,
            population_scope={"age_range": "30-70", "sample_size": 10000}
        )
        
        assert theorem.theorem_type == MedicalTheoremType.RISK_ASSESSMENT
        assert theorem.population_scope["sample_size"] == 10000
    
    def test_medical_theorem_with_validation_data(self):
        """
        GIVEN a theorem with validation data
        WHEN MedicalTheorem is created
        THEN validation data should be stored correctly
        """
        antecedent = MedicalEntity("treatment", "drug_x", {})
        consequent = MedicalEntity("outcome", "cure", {})
        
        validation_data = {
            "p_value": 0.001,
            "effect_size": 0.85,
            "sample_size": 500
        }
        
        theorem = MedicalTheorem(
            theorem_id="TEST_001",
            theorem_type=MedicalTheoremType.TREATMENT_OUTCOME,
            antecedent=antecedent,
            consequent=consequent,
            confidence=ConfidenceLevel.HIGH,
            validation_data=validation_data
        )
        
        assert theorem.validation_data["p_value"] == 0.001
        assert theorem.validation_data["effect_size"] == 0.85


@pytest.mark.skipif(not MEDICAL_THEOREM_AVAILABLE, reason=SKIP_REASON)
class TestMedicalTheoremGenerator:
    """Test MedicalTheoremGenerator class."""
    
    def test_generator_initialization(self):
        """
        GIVEN no parameters
        WHEN MedicalTheoremGenerator is created
        THEN generator should be initialized with defaults
        """
        generator = MedicalTheoremGenerator()
        
        assert generator.theorems == []
        assert generator.validation_threshold == 0.5
    
    def test_generate_from_clinical_trial_basic(self):
        """
        GIVEN basic clinical trial data
        WHEN generate_from_clinical_trial is called
        THEN theorems should be generated
        """
        generator = MedicalTheoremGenerator()
        
        trial_data = {
            "nct_id": "NCT12345",
            "interventions": ["Drug A"],
            "conditions": ["Diabetes"]
        }
        
        outcomes_data = {
            "primary_outcomes": [
                {
                    "measure": "HbA1c reduction",
                    "description": "Reduction in blood glucose",
                    "time_frame": "6 months"
                }
            ],
            "adverse_events": []
        }
        
        theorems = generator.generate_from_clinical_trial(trial_data, outcomes_data)
        
        assert len(theorems) >= 1
        assert theorems[0].theorem_type == MedicalTheoremType.TREATMENT_OUTCOME
        assert theorems[0].antecedent.name == "Drug A"
        assert "NCT12345" in theorems[0].evidence_sources
    
    def test_generate_from_clinical_trial_with_adverse_events(self):
        """
        GIVEN clinical trial with adverse events
        WHEN generate_from_clinical_trial is called
        THEN adverse event theorems should be generated
        """
        generator = MedicalTheoremGenerator()
        
        trial_data = {
            "nct_id": "NCT99999",
            "interventions": ["Drug B"],
            "conditions": ["Hypertension"]
        }
        
        outcomes_data = {
            "primary_outcomes": [],
            "adverse_events": [
                {
                    "term": "Headache",
                    "organ_system": "Nervous System",
                    "frequency": 25
                }
            ]
        }
        
        theorems = generator.generate_from_clinical_trial(trial_data, outcomes_data)
        
        assert len(theorems) >= 1
        adverse_theorems = [t for t in theorems if t.theorem_type == MedicalTheoremType.ADVERSE_EVENT]
        assert len(adverse_theorems) >= 1
        assert adverse_theorems[0].consequent.name == "Headache"
    
    def test_generate_from_clinical_trial_multiple_interventions(self):
        """
        GIVEN clinical trial with multiple interventions and outcomes
        WHEN generate_from_clinical_trial is called
        THEN multiple theorems should be generated
        """
        generator = MedicalTheoremGenerator()
        
        trial_data = {
            "nct_id": "NCT11111",
            "interventions": ["Drug A", "Drug B"],
            "conditions": ["Cancer"]
        }
        
        outcomes_data = {
            "primary_outcomes": [
                {"measure": "Survival rate", "description": "5-year survival", "time_frame": "5 years"},
                {"measure": "Tumor size", "description": "Reduction in tumor", "time_frame": "6 months"}
            ],
            "adverse_events": []
        }
        
        theorems = generator.generate_from_clinical_trial(trial_data, outcomes_data)
        
        # Should generate at least 4 theorems (2 interventions x 2 outcomes)
        assert len(theorems) >= 4
    
    def test_calculate_confidence_from_frequency(self):
        """
        GIVEN various frequency values
        WHEN _calculate_confidence_from_frequency is called
        THEN correct confidence levels should be returned
        """
        generator = MedicalTheoremGenerator()
        
        assert generator._calculate_confidence_from_frequency(150) == ConfidenceLevel.VERY_HIGH
        assert generator._calculate_confidence_from_frequency(75) == ConfidenceLevel.HIGH
        assert generator._calculate_confidence_from_frequency(30) == ConfidenceLevel.MODERATE
        assert generator._calculate_confidence_from_frequency(10) == ConfidenceLevel.LOW
        assert generator._calculate_confidence_from_frequency(2) == ConfidenceLevel.VERY_LOW
    
    def test_generate_from_pubmed_research(self):
        """
        GIVEN PubMed article data
        WHEN generate_from_pubmed_research is called
        THEN theorems should be generated (currently placeholder)
        """
        generator = MedicalTheoremGenerator()
        
        articles = [
            {
                "pmid": "12345",
                "mesh_terms": ["Smoking", "Lung Cancer"],
                "abstract": "This study shows that smoking causes lung cancer in population studies."
            }
        ]
        
        theorems = generator.generate_from_pubmed_research(articles)
        
        # Currently returns empty list (placeholder implementation)
        assert isinstance(theorems, list)


@pytest.mark.skipif(not MEDICAL_THEOREM_AVAILABLE, reason=SKIP_REASON)
class TestFuzzyLogicValidator:
    """Test FuzzyLogicValidator class."""
    
    def test_validator_initialization(self):
        """
        GIVEN no parameters
        WHEN FuzzyLogicValidator is created
        THEN validator should be initialized
        """
        validator = FuzzyLogicValidator()
        
        assert validator.membership_functions == {}
    
    def test_validate_treatment_theorem(self):
        """
        GIVEN a treatment theorem and empirical data
        WHEN validate_theorem is called
        THEN validation result should be returned
        """
        validator = FuzzyLogicValidator()
        
        antecedent = MedicalEntity("treatment", "aspirin", {"dosage": "100mg"})
        consequent = MedicalEntity("outcome", "pain_relief", {})
        
        theorem = MedicalTheorem(
            theorem_id="ASPIRIN_TEST",
            theorem_type=MedicalTheoremType.TREATMENT_OUTCOME,
            antecedent=antecedent,
            consequent=consequent,
            confidence=ConfidenceLevel.HIGH,
            evidence_sources=["NCT1", "NCT2"]
        )
        
        empirical_data = {"trial_results": []}
        
        result = validator.validate_theorem(theorem, empirical_data)
        
        assert result["validated"] is True
        assert "fuzzy_confidence" in result
        assert result["evidence_count"] == 2
        assert result["validation_method"] == "fuzzy_logic"
    
    def test_validate_adverse_event_theorem(self):
        """
        GIVEN an adverse event theorem
        WHEN validate_theorem is called
        THEN validation result should be returned
        """
        validator = FuzzyLogicValidator()
        
        antecedent = MedicalEntity("treatment", "drug_x", {})
        consequent = MedicalEntity("adverse_event", "nausea", {"frequency": 15})
        
        theorem = MedicalTheorem(
            theorem_id="AE_TEST",
            theorem_type=MedicalTheoremType.ADVERSE_EVENT,
            antecedent=antecedent,
            consequent=consequent,
            confidence=ConfidenceLevel.MODERATE,
            evidence_sources=["NCT3"]
        )
        
        empirical_data = {}
        
        result = validator.validate_theorem(theorem, empirical_data)
        
        assert result["validated"] is True
        assert "fuzzy_confidence" in result
    
    def test_validate_unsupported_theorem_type(self):
        """
        GIVEN a theorem with unsupported type
        WHEN validate_theorem is called
        THEN validation should return unsupported message
        """
        validator = FuzzyLogicValidator()
        
        antecedent = MedicalEntity("population", "elderly", {})
        consequent = MedicalEntity("condition", "dementia", {})
        
        theorem = MedicalTheorem(
            theorem_id="POP_TEST",
            theorem_type=MedicalTheoremType.POPULATION_EFFECT,
            antecedent=antecedent,
            consequent=consequent,
            confidence=ConfidenceLevel.MODERATE
        )
        
        result = validator.validate_theorem(theorem, {})
        
        assert result["validated"] is False
        assert "Unsupported theorem type" in result["reason"]


@pytest.mark.skipif(not MEDICAL_THEOREM_AVAILABLE, reason=SKIP_REASON)
class TestTimeSeriesTheoremValidator:
    """Test TimeSeriesTheoremValidator class."""
    
    def test_validator_initialization(self):
        """
        GIVEN no parameters
        WHEN TimeSeriesTheoremValidator is created
        THEN validator should be initialized
        """
        validator = TimeSeriesTheoremValidator()
        
        assert validator.temporal_patterns == {}
    
    def test_validate_temporal_theorem_with_constraint(self):
        """
        GIVEN a theorem with temporal constraint and time-series data
        WHEN validate_temporal_theorem is called
        THEN temporal validation should be performed
        """
        validator = TimeSeriesTheoremValidator()
        
        antecedent = MedicalEntity("treatment", "insulin", {"dosage": "10 units"})
        consequent = MedicalEntity("outcome", "glucose_reduction", {})
        
        temporal_constraint = TemporalConstraint(
            time_to_effect=timedelta(hours=2),
            duration=timedelta(hours=6)
        )
        
        theorem = MedicalTheorem(
            theorem_id="INSULIN_TEST",
            theorem_type=MedicalTheoremType.TREATMENT_OUTCOME,
            antecedent=antecedent,
            consequent=consequent,
            confidence=ConfidenceLevel.HIGH,
            temporal_constraint=temporal_constraint
        )
        
        time_series_data = [
            {"time": 0, "glucose": 180},
            {"time": 2, "glucose": 140},
            {"time": 4, "glucose": 120},
            {"time": 6, "glucose": 110}
        ]
        
        result = validator.validate_temporal_theorem(theorem, time_series_data)
        
        assert result["validated"] is True
        assert "temporal_consistency" in result
        assert result["time_to_effect_match"] is True
        assert result["duration_match"] is True
    
    def test_validate_temporal_theorem_without_constraint(self):
        """
        GIVEN a theorem without temporal constraint
        WHEN validate_temporal_theorem is called
        THEN validation should fail with reason
        """
        validator = TimeSeriesTheoremValidator()
        
        antecedent = MedicalEntity("treatment", "drug", {})
        consequent = MedicalEntity("outcome", "cure", {})
        
        theorem = MedicalTheorem(
            theorem_id="NO_TEMPORAL",
            theorem_type=MedicalTheoremType.TREATMENT_OUTCOME,
            antecedent=antecedent,
            consequent=consequent,
            confidence=ConfidenceLevel.MODERATE
        )
        
        result = validator.validate_temporal_theorem(theorem, [])
        
        assert result["validated"] is False
        assert result["reason"] == "No temporal constraint"
    
    def test_validate_temporal_theorem_empty_time_series(self):
        """
        GIVEN a theorem with temporal constraint but empty time-series
        WHEN validate_temporal_theorem is called
        THEN validation should still work (placeholder implementation)
        """
        validator = TimeSeriesTheoremValidator()
        
        antecedent = MedicalEntity("treatment", "test", {})
        consequent = MedicalEntity("outcome", "result", {})
        
        temporal_constraint = TemporalConstraint(time_to_effect=timedelta(hours=1))
        
        theorem = MedicalTheorem(
            theorem_id="EMPTY_TS",
            theorem_type=MedicalTheoremType.TREATMENT_OUTCOME,
            antecedent=antecedent,
            consequent=consequent,
            confidence=ConfidenceLevel.LOW,
            temporal_constraint=temporal_constraint
        )
        
        result = validator.validate_temporal_theorem(theorem, [])
        
        assert result["validated"] is True


@pytest.mark.skipif(not MEDICAL_THEOREM_AVAILABLE, reason=SKIP_REASON)
class TestTheoremTypeEnums:
    """Test theorem type enumerations."""
    
    def test_medical_theorem_type_values(self):
        """
        GIVEN MedicalTheoremType enum
        WHEN accessing enum values
        THEN all expected types should be available
        """
        assert MedicalTheoremType.CAUSAL_RELATIONSHIP.value == "causal"
        assert MedicalTheoremType.RISK_ASSESSMENT.value == "risk"
        assert MedicalTheoremType.TREATMENT_OUTCOME.value == "treatment"
        assert MedicalTheoremType.POPULATION_EFFECT.value == "population"
        assert MedicalTheoremType.TEMPORAL_PROGRESSION.value == "temporal"
        assert MedicalTheoremType.ADVERSE_EVENT.value == "adverse"
    
    def test_confidence_level_values(self):
        """
        GIVEN ConfidenceLevel enum
        WHEN accessing enum values
        THEN all confidence levels should be available
        """
        assert ConfidenceLevel.VERY_HIGH.value == "very_high"
        assert ConfidenceLevel.HIGH.value == "high"
        assert ConfidenceLevel.MODERATE.value == "moderate"
        assert ConfidenceLevel.LOW.value == "low"
        assert ConfidenceLevel.VERY_LOW.value == "very_low"
