#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Medical Theorem Framework for Temporal Deontic Logic.

This module extends the temporal deontic logic system to support medical reasoning,
including causal relationships, fuzzy logic validation, and time-series based
theorem validation.

Example theorems:
- "If a person eats tide pods, they are likely to get sick"
- "If a patient takes medication X for condition Y, outcome Z is expected within time T"
- "Population P exposed to factor F has increased risk of disease D"
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum


logger = logging.getLogger(__name__)


class MedicalTheoremType(Enum):
    """Types of medical theorems."""
    CAUSAL_RELATIONSHIP = "causal"  # A causes B
    RISK_ASSESSMENT = "risk"  # A increases/decreases risk of B
    TREATMENT_OUTCOME = "treatment"  # Treatment A leads to outcome B
    POPULATION_EFFECT = "population"  # Effect observed in population
    TEMPORAL_PROGRESSION = "temporal"  # Progression over time
    ADVERSE_EVENT = "adverse"  # Adverse event relationship


class ConfidenceLevel(Enum):
    """Confidence levels for theorem validation."""
    VERY_HIGH = "very_high"  # >90% confidence
    HIGH = "high"  # 75-90% confidence
    MODERATE = "moderate"  # 50-75% confidence
    LOW = "low"  # 25-50% confidence
    VERY_LOW = "very_low"  # <25% confidence


@dataclass
class MedicalEntity:
    """
    Represents a medical entity in a theorem.
    
    Attributes:
        entity_type: Type of entity (substance, condition, treatment, outcome)
        name: Entity name
        properties: Additional properties (dosage, duration, severity, etc.)
    """
    entity_type: str
    name: str
    properties: Dict[str, Any]


@dataclass
class TemporalConstraint:
    """
    Represents temporal constraints in a medical theorem.
    
    Attributes:
        time_to_effect: Time until effect manifests
        duration: Duration of effect
        time_window: Valid time window for observation
        temporal_operator: Temporal logic operator (before, after, during, etc.)
    """
    time_to_effect: Optional[timedelta] = None
    duration: Optional[timedelta] = None
    time_window: Optional[Tuple[datetime, datetime]] = None
    temporal_operator: Optional[str] = None


@dataclass
class MedicalTheorem:
    """
    Represents a medical theorem in temporal deontic logic.
    
    A theorem captures a medical relationship that can be validated against
    empirical data (clinical trials, population studies, etc.).
    
    Example:
        theorem = MedicalTheorem(
            theorem_id="TIDE_POD_001",
            theorem_type=MedicalTheoremType.CAUSAL_RELATIONSHIP,
            antecedent=MedicalEntity("substance", "tide pods", {"route": "ingestion"}),
            consequent=MedicalEntity("condition", "poisoning", {"severity": "severe"}),
            confidence=ConfidenceLevel.VERY_HIGH,
            temporal_constraint=TemporalConstraint(time_to_effect=timedelta(hours=1))
        )
    """
    theorem_id: str
    theorem_type: MedicalTheoremType
    antecedent: MedicalEntity  # If this happens...
    consequent: MedicalEntity  # Then this is expected...
    confidence: ConfidenceLevel
    temporal_constraint: Optional[TemporalConstraint] = None
    population_scope: Optional[Dict[str, Any]] = None
    evidence_sources: List[str] = None
    validation_data: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.evidence_sources is None:
            self.evidence_sources = []


class MedicalTheoremGenerator:
    """
    Generates medical theorems from research data.
    
    This class analyzes clinical trials, research papers, and population data
    to automatically generate and validate medical theorems for the temporal
    deontic logic system.
    """
    
    def __init__(self):
        """Initialize the theorem generator."""
        self.theorems = []
        self.validation_threshold = 0.5  # Minimum confidence for theorem acceptance
    
    def generate_from_clinical_trial(
        self,
        trial_data: Dict[str, Any],
        outcomes_data: Dict[str, Any]
    ) -> List[MedicalTheorem]:
        """
        Generate theorems from clinical trial data.
        
        Args:
            trial_data: Clinical trial metadata
            outcomes_data: Trial outcomes and results
            
        Returns:
            List of generated medical theorems
        """
        theorems = []
        
        # Extract intervention and outcomes
        interventions = trial_data.get("interventions", [])
        conditions = trial_data.get("conditions", [])
        
        primary_outcomes = outcomes_data.get("primary_outcomes", [])
        
        # Generate treatment-outcome theorems
        for intervention in interventions:
            for outcome in primary_outcomes:
                theorem = self._create_treatment_theorem(
                    intervention=intervention,
                    condition=conditions[0] if conditions else "Unknown",
                    outcome=outcome,
                    trial_id=trial_data.get("nct_id", "")
                )
                if theorem:
                    theorems.append(theorem)
        
        # Generate adverse event theorems
        adverse_events = outcomes_data.get("adverse_events", [])
        for event in adverse_events:
            theorem = self._create_adverse_event_theorem(
                intervention=interventions[0] if interventions else "Unknown",
                adverse_event=event,
                trial_id=trial_data.get("nct_id", "")
            )
            if theorem:
                theorems.append(theorem)
        
        return theorems
    
    def _create_treatment_theorem(
        self,
        intervention: str,
        condition: str,
        outcome: Dict[str, Any],
        trial_id: str
    ) -> Optional[MedicalTheorem]:
        """Create a treatment-outcome theorem."""
        try:
            # Extract temporal information
            time_frame = outcome.get("time_frame", "")
            temporal_constraint = self._parse_time_frame(time_frame)
            
            # Create antecedent (treatment for condition)
            antecedent = MedicalEntity(
                entity_type="treatment",
                name=intervention,
                properties={"condition": condition}
            )
            
            # Create consequent (expected outcome)
            consequent = MedicalEntity(
                entity_type="outcome",
                name=outcome.get("measure", ""),
                properties={
                    "description": outcome.get("description", ""),
                    "time_frame": time_frame
                }
            )
            
            theorem = MedicalTheorem(
                theorem_id=f"TREAT_{trial_id}_{intervention[:20]}",
                theorem_type=MedicalTheoremType.TREATMENT_OUTCOME,
                antecedent=antecedent,
                consequent=consequent,
                confidence=ConfidenceLevel.MODERATE,  # Would be calculated from data
                temporal_constraint=temporal_constraint,
                evidence_sources=[trial_id]
            )
            
            return theorem
        except Exception as e:
            logger.error(f"Error creating treatment theorem: {e}")
            return None
    
    def _create_adverse_event_theorem(
        self,
        intervention: str,
        adverse_event: Dict[str, Any],
        trial_id: str
    ) -> Optional[MedicalTheorem]:
        """Create an adverse event theorem."""
        try:
            antecedent = MedicalEntity(
                entity_type="treatment",
                name=intervention,
                properties={}
            )
            
            consequent = MedicalEntity(
                entity_type="adverse_event",
                name=adverse_event.get("term", ""),
                properties={
                    "organ_system": adverse_event.get("organ_system", ""),
                    "frequency": adverse_event.get("frequency", 0)
                }
            )
            
            # Calculate confidence based on frequency
            frequency = adverse_event.get("frequency", 0)
            confidence = self._calculate_confidence_from_frequency(frequency)
            
            theorem = MedicalTheorem(
                theorem_id=f"AE_{trial_id}_{adverse_event.get('term', '')[:20]}",
                theorem_type=MedicalTheoremType.ADVERSE_EVENT,
                antecedent=antecedent,
                consequent=consequent,
                confidence=confidence,
                evidence_sources=[trial_id]
            )
            
            return theorem
        except Exception as e:
            logger.error(f"Error creating adverse event theorem: {e}")
            return None
    
    def _parse_time_frame(self, time_frame: str) -> Optional[TemporalConstraint]:
        """Parse time frame string into temporal constraint."""
        # Simplified parsing - would need more sophisticated NLP
        if not time_frame:
            return None
        
        # Try to extract duration (e.g., "6 months", "1 year")
        # This is a placeholder - real implementation would use regex/NLP
        return TemporalConstraint()
    
    def _calculate_confidence_from_frequency(self, frequency: int) -> ConfidenceLevel:
        """Calculate confidence level based on event frequency."""
        if frequency > 100:
            return ConfidenceLevel.VERY_HIGH
        elif frequency > 50:
            return ConfidenceLevel.HIGH
        elif frequency > 20:
            return ConfidenceLevel.MODERATE
        elif frequency > 5:
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.VERY_LOW
    
    def generate_from_pubmed_research(
        self,
        articles: List[Dict[str, Any]]
    ) -> List[MedicalTheorem]:
        """
        Generate theorems from PubMed research articles.
        
        This would use NLP to extract causal relationships from abstracts.
        
        Args:
            articles: List of PubMed articles
            
        Returns:
            List of generated theorems
        """
        theorems = []
        
        for article in articles:
            # Extract MeSH terms for entities
            mesh_terms = article.get("mesh_terms", [])
            
            # Simple heuristic: look for causal language in abstract
            abstract = article.get("abstract", "")
            
            # This is a placeholder - real implementation would use NLP
            # to extract causal relationships from text
            if "cause" in abstract.lower() or "leads to" in abstract.lower():
                # Would extract entities and relationships here
                pass
        
        return theorems


class FuzzyLogicValidator:
    """
    Validates medical theorems using fuzzy logic.
    
    Traditional boolean logic is insufficient for medical reasoning, as
    relationships are probabilistic rather than deterministic. This class
    implements fuzzy logic validation to support reasoning like:
    "Person X has HIGH likelihood of outcome Y given intervention Z"
    """
    
    def __init__(self):
        """Initialize fuzzy logic validator."""
        self.membership_functions = {}
    
    def validate_theorem(
        self,
        theorem: MedicalTheorem,
        empirical_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate a theorem against empirical data using fuzzy logic.
        
        Args:
            theorem: Medical theorem to validate
            empirical_data: Empirical data (clinical trials, population studies)
            
        Returns:
            Validation result with fuzzy confidence score
        """
        # Extract relevant data for validation
        if theorem.theorem_type == MedicalTheoremType.TREATMENT_OUTCOME:
            return self._validate_treatment_theorem(theorem, empirical_data)
        elif theorem.theorem_type == MedicalTheoremType.ADVERSE_EVENT:
            return self._validate_adverse_event_theorem(theorem, empirical_data)
        else:
            return {"validated": False, "reason": "Unsupported theorem type"}
    
    def _validate_treatment_theorem(
        self,
        theorem: MedicalTheorem,
        empirical_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate treatment-outcome theorem."""
        # This would calculate fuzzy membership based on:
        # - Effect size in clinical trials
        # - Statistical significance
        # - Population-level validation
        # - Time-series consistency
        
        return {
            "validated": True,
            "fuzzy_confidence": 0.75,  # Placeholder
            "evidence_count": len(theorem.evidence_sources),
            "validation_method": "fuzzy_logic"
        }
    
    def _validate_adverse_event_theorem(
        self,
        theorem: MedicalTheorem,
        empirical_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate adverse event theorem."""
        # Calculate fuzzy membership based on frequency and severity
        return {
            "validated": True,
            "fuzzy_confidence": 0.60,  # Placeholder
            "evidence_count": len(theorem.evidence_sources),
            "validation_method": "fuzzy_logic"
        }


class TimeSeriesTheoremValidator:
    """
    Validates theorems using time-series data.
    
    This class validates temporal aspects of medical theorems by analyzing
    time-series data from clinical trials and population studies.
    """
    
    def __init__(self):
        """Initialize time-series validator."""
        self.temporal_patterns = {}
    
    def validate_temporal_theorem(
        self,
        theorem: MedicalTheorem,
        time_series_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Validate temporal aspects of a theorem.
        
        Args:
            theorem: Medical theorem with temporal constraints
            time_series_data: Time-series measurements
            
        Returns:
            Validation result with temporal consistency score
        """
        if not theorem.temporal_constraint:
            return {"validated": False, "reason": "No temporal constraint"}
        
        # Analyze time-series data for consistency with theorem
        # This would involve:
        # - Checking time-to-effect matches observations
        # - Validating duration of effect
        # - Ensuring temporal window is correct
        
        return {
            "validated": True,
            "temporal_consistency": 0.80,  # Placeholder
            "time_to_effect_match": True,
            "duration_match": True
        }
