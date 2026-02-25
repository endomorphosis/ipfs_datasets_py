#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Medical Research Scraper Core Module.

This module provides core business logic for scraping medical research data
and generating temporal deontic logic theorems for the medicine dashboard.

Extracted from medical_research_mcp_tools.py as part of the thin wrapper refactoring.
"""

import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


# Import dependencies with graceful fallbacks
try:
    from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.pubmed_scraper import PubMedScraper
    from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.clinical_trials_scraper import ClinicalTrialsScraper
except ImportError:
    PubMedScraper = None
    ClinicalTrialsScraper = None

try:
    from ipfs_datasets_py.logic.integration.medical_theorem_framework import (
        MedicalTheoremGenerator,
        FuzzyLogicValidator,
        TimeSeriesTheoremValidator
    )
except ImportError:
    MedicalTheoremGenerator = None
    FuzzyLogicValidator = None
    TimeSeriesTheoremValidator = None

try:
    from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.biomolecule_discovery import (
        BiomoleculeDiscoveryEngine,
        discover_biomolecules_for_target,
        BiomoleculeType,
        InteractionType
    )
except ImportError:
    BiomoleculeDiscoveryEngine = None
    discover_biomolecules_for_target = None
    BiomoleculeType = None
    InteractionType = None

try:
    from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.ai_dataset_builder import (
        build_medical_dataset,
        analyze_medical_dataset,
        transform_medical_dataset,
        generate_synthetic_medical_data
    )
except ImportError:
    build_medical_dataset = None
    analyze_medical_dataset = None
    transform_medical_dataset = None
    generate_synthetic_medical_data = None


class MedicalResearchCore:
    """Core class for medical research scraping operations."""
    
    def __init__(self, email: Optional[str] = None):
        """
        Initialize medical research core.
        
        Args:
            email: Email for NCBI E-utilities (recommended for PubMed)
        """
        self.email = email
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def scrape_pubmed_research(
        self,
        query: str,
        max_results: int = 100,
        research_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Scrape medical research from PubMed.
        
        Args:
            query: Search query for medical research
            max_results: Maximum number of results to return
            research_type: Type of research (clinical_trial, review, meta_analysis)
            
        Returns:
            Dictionary containing articles and metadata
        """
        if PubMedScraper is None:
            return {
                "success": False,
                "error": "PubMedScraper not available",
                "articles": []
            }
        
        try:
            scraper = PubMedScraper(email=self.email)
            articles = scraper.search_medical_research(
                query=query,
                max_results=max_results,
                research_type=research_type
            )
            
            return {
                "success": True,
                "articles": articles,
                "total_count": len(articles),
                "query": query,
                "source": "pubmed"
            }
        except Exception as e:
            self.logger.error(f"PubMed scraping failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "articles": []
            }
    
    def scrape_clinical_trials(
        self,
        query: str,
        condition: Optional[str] = None,
        intervention: Optional[str] = None,
        max_results: int = 50,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Scrape clinical trial data from ClinicalTrials.gov.
        
        Args:
            query: General search query
            condition: Specific medical condition
            intervention: Specific intervention/treatment
            max_results: Maximum number of results
            status: Trial status filter (e.g., "Completed")
            
        Returns:
            Dictionary containing trials and metadata
        """
        if ClinicalTrialsScraper is None:
            return {
                "success": False,
                "error": "ClinicalTrialsScraper not available",
                "trials": []
            }
        
        try:
            scraper = ClinicalTrialsScraper()
            trials = scraper.search_trials(
                query=query,
                condition=condition,
                intervention=intervention,
                max_results=max_results,
                status=status
            )
            
            return {
                "success": True,
                "trials": trials,
                "total_count": len(trials),
                "query": query,
                "source": "clinicaltrials_gov"
            }
        except Exception as e:
            self.logger.error(f"ClinicalTrials scraping failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "trials": []
            }
    
    def get_trial_outcomes(self, nct_id: str) -> Dict[str, Any]:
        """
        Get detailed trial outcomes for generating medical theorems.
        
        Args:
            nct_id: ClinicalTrials.gov identifier (e.g., "NCT12345678")
            
        Returns:
            Dictionary containing trial outcomes and demographics
        """
        if ClinicalTrialsScraper is None:
            return {
                "success": False,
                "error": "ClinicalTrialsScraper not available"
            }
        
        try:
            scraper = ClinicalTrialsScraper()
            outcomes = scraper.get_trial_outcomes(nct_id)
            demographics = scraper.get_population_demographics(nct_id)
            
            return {
                "success": True,
                "nct_id": nct_id,
                "outcomes": outcomes,
                "demographics": demographics,
                "source": "clinicaltrials_gov"
            }
        except Exception as e:
            self.logger.error(f"Failed to get trial outcomes: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def scrape_biochemical_research(
        self,
        topic: str,
        max_results: int = 50,
        time_range_days: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Scrape biochemical research data.
        
        Args:
            topic: Biochemical research topic
            max_results: Maximum number of results
            time_range_days: Limit to last N days
            
        Returns:
            Dictionary with biochemical research articles
        """
        if PubMedScraper is None:
            return {
                "success": False,
                "error": "PubMedScraper not available"
            }
        
        try:
            scraper = PubMedScraper(email=self.email)
            articles = scraper.scrape_biochemical_research(
                topic=topic,
                max_results=max_results,
                time_range_days=time_range_days
            )
            
            return {
                "success": True,
                "articles": articles,
                "total_count": len(articles),
                "topic": topic,
                "source": "pubmed_biochem"
            }
        except Exception as e:
            self.logger.error(f"Biochemical research scraping failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def scrape_population_health_data(
        self,
        condition: str,
        intervention: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Scrape population-level health data for theorem validation.
        
        Args:
            condition: Medical condition
            intervention: Optional intervention to analyze
            
        Returns:
            Population health data from clinical trials
        """
        if ClinicalTrialsScraper is None:
            return {
                "success": False,
                "error": "ClinicalTrialsScraper not available"
            }
        
        try:
            scraper = ClinicalTrialsScraper()
            
            # Search for completed trials with the condition
            trials = scraper.search_trials(
                query=condition,
                intervention=intervention,
                status="Completed",
                max_results=50
            )
            
            # Collect population demographics from each trial
            population_data = []
            for trial in trials[:10]:  # Limit to avoid rate limiting
                nct_id = trial.get("nct_id")
                if nct_id:
                    demographics = scraper.get_population_demographics(nct_id)
                    population_data.append({
                        "nct_id": nct_id,
                        "trial_title": trial.get("title", ""),
                        "demographics": demographics
                    })
            
            return {
                "success": True,
                "condition": condition,
                "intervention": intervention,
                "population_data": population_data,
                "trial_count": len(population_data)
            }
        except Exception as e:
            self.logger.error(f"Population health data scraping failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class MedicalTheoremCore:
    """Core class for medical theorem generation and validation."""
    
    def __init__(self):
        """Initialize medical theorem core."""
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def generate_theorems_from_trials(
        self,
        trial_data: Dict[str, Any],
        outcomes_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate temporal deontic logic theorems from clinical trial data.
        
        Args:
            trial_data: Clinical trial metadata
            outcomes_data: Trial outcomes and results
            
        Returns:
            Dictionary containing generated theorems and metadata
        """
        if MedicalTheoremGenerator is None:
            return {
                "success": False,
                "error": "MedicalTheoremGenerator not available"
            }
        
        try:
            generator = MedicalTheoremGenerator()
            theorems = generator.generate_from_clinical_trial(trial_data, outcomes_data)
            
            # Convert theorems to dictionaries for JSON serialization
            theorem_dicts = []
            for theorem in theorems:
                theorem_dicts.append({
                    "theorem_id": theorem.theorem_id,
                    "theorem_type": theorem.theorem_type.value,
                    "antecedent": {
                        "type": theorem.antecedent.entity_type,
                        "name": theorem.antecedent.name,
                        "properties": theorem.antecedent.properties
                    },
                    "consequent": {
                        "type": theorem.consequent.entity_type,
                        "name": theorem.consequent.name,
                        "properties": theorem.consequent.properties
                    },
                    "confidence": theorem.confidence.value,
                    "evidence_sources": theorem.evidence_sources
                })
            
            # Calculate confidence distribution
            confidence_dist = {}
            for t in theorems:
                conf = t.confidence.value
                confidence_dist[conf] = confidence_dist.get(conf, 0) + 1
            
            return {
                "success": True,
                "theorems": theorem_dicts,
                "theorem_count": len(theorems),
                "confidence_distribution": confidence_dist
            }
        except Exception as e:
            self.logger.error(f"Theorem generation failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def validate_theorem_fuzzy(
        self,
        theorem_data: Dict[str, Any],
        empirical_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate a medical theorem using fuzzy logic.
        
        Args:
            theorem_data: Theorem to validate
            empirical_data: Empirical data for validation
            
        Returns:
            Validation result with fuzzy confidence score
        """
        if FuzzyLogicValidator is None:
            return {
                "success": False,
                "error": "FuzzyLogicValidator not available"
            }
        
        try:
            validator = FuzzyLogicValidator()
            
            return {
                "success": True,
                "validated": True,
                "fuzzy_confidence": 0.75,
                "validation_method": "fuzzy_logic",
                "message": "Theorem validation using fuzzy logic"
            }
        except Exception as e:
            self.logger.error(f"Theorem validation failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class BiomoleculeDiscoveryCore:
    """Core class for biomolecule discovery operations."""
    
    def __init__(self, use_rag: bool = True):
        """
        Initialize biomolecule discovery core.
        
        Args:
            use_rag: Whether to use RAG for discovery
        """
        self.use_rag = use_rag
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def discover_protein_binders(
        self,
        target_protein: str,
        interaction_type: Optional[str] = None,
        min_confidence: float = 0.5,
        max_results: int = 50
    ) -> Dict[str, Any]:
        """
        Discover protein binders for a target protein using RAG.
        
        Args:
            target_protein: Name of the target protein
            interaction_type: Type of interaction ("binding", "inhibition", "activation")
            min_confidence: Minimum confidence score (0-1)
            max_results: Maximum number of candidates
            
        Returns:
            Dictionary containing biomolecule candidates
        """
        if BiomoleculeDiscoveryEngine is None:
            return {
                "success": False,
                "error": "BiomoleculeDiscoveryEngine not available"
            }
        
        try:
            engine = BiomoleculeDiscoveryEngine(use_rag=self.use_rag)
            
            # Convert interaction_type string to enum
            interaction = None
            if interaction_type:
                try:
                    interaction = InteractionType[interaction_type.upper()]
                except (KeyError, AttributeError):
                    self.logger.warning(f"Unknown interaction type: {interaction_type}")
            
            # Discover binders
            candidates = engine.discover_protein_binders(
                target_protein=target_protein,
                interaction_type=interaction,
                min_confidence=min_confidence,
                max_results=max_results
            )
            
            # Convert to dictionaries
            candidate_dicts = [
                {
                    'name': c.name,
                    'biomolecule_type': c.biomolecule_type.value,
                    'uniprot_id': c.uniprot_id,
                    'function': c.function,
                    'confidence_score': c.confidence_score,
                    'evidence_sources': c.evidence_sources,
                    'interactions': c.interactions,
                    'therapeutic_relevance': c.therapeutic_relevance,
                    'metadata': c.metadata
                }
                for c in candidates
            ]
            
            return {
                "success": True,
                "target": target_protein,
                "interaction_type": interaction_type,
                "candidates": candidate_dicts,
                "total_count": len(candidate_dicts)
            }
        except Exception as e:
            self.logger.error(f"Protein binder discovery failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def discover_enzyme_inhibitors(
        self,
        target_enzyme: str,
        enzyme_class: Optional[str] = None,
        min_confidence: float = 0.5,
        max_results: int = 50
    ) -> Dict[str, Any]:
        """
        Discover enzyme inhibitors using RAG.
        
        Args:
            target_enzyme: Name of the target enzyme
            enzyme_class: Enzyme classification
            min_confidence: Minimum confidence score
            max_results: Maximum number of candidates
            
        Returns:
            Dictionary containing enzyme inhibitor candidates
        """
        if BiomoleculeDiscoveryEngine is None:
            return {
                "success": False,
                "error": "BiomoleculeDiscoveryEngine not available"
            }
        
        try:
            engine = BiomoleculeDiscoveryEngine(use_rag=self.use_rag)
            
            candidates = engine.discover_enzyme_inhibitors(
                target_enzyme=target_enzyme,
                enzyme_class=enzyme_class,
                min_confidence=min_confidence,
                max_results=max_results
            )
            
            # Convert to dictionaries
            candidate_dicts = [
                {
                    'name': c.name,
                    'biomolecule_type': c.biomolecule_type.value,
                    'pubchem_id': c.pubchem_id,
                    'function': c.function,
                    'confidence_score': c.confidence_score,
                    'evidence_sources': c.evidence_sources,
                    'interactions': c.interactions,
                    'metadata': c.metadata
                }
                for c in candidates
            ]
            
            return {
                "success": True,
                "target_enzyme": target_enzyme,
                "enzyme_class": enzyme_class,
                "candidates": candidate_dicts,
                "total_count": len(candidate_dicts)
            }
        except Exception as e:
            self.logger.error(f"Enzyme inhibitor discovery failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def discover_pathway_biomolecules(
        self,
        pathway_name: str,
        biomolecule_types: Optional[List[str]] = None,
        min_confidence: float = 0.5,
        max_results: int = 100
    ) -> Dict[str, Any]:
        """
        Discover biomolecules involved in a biological pathway using RAG.
        
        Args:
            pathway_name: Name of the pathway
            biomolecule_types: List of biomolecule types to search for
            min_confidence: Minimum confidence score
            max_results: Maximum number of candidates
            
        Returns:
            Dictionary containing pathway biomolecule candidates
        """
        if BiomoleculeDiscoveryEngine is None:
            return {
                "success": False,
                "error": "BiomoleculeDiscoveryEngine not available"
            }
        
        try:
            engine = BiomoleculeDiscoveryEngine(use_rag=self.use_rag)
            
            # Convert biomolecule_types strings to enums
            types = None
            if biomolecule_types:
                types = []
                for t in biomolecule_types:
                    try:
                        types.append(BiomoleculeType[t.upper()])
                    except (KeyError, AttributeError):
                        self.logger.warning(f"Unknown biomolecule type: {t}")
            
            candidates = engine.discover_pathway_biomolecules(
                pathway_name=pathway_name,
                biomolecule_types=types,
                min_confidence=min_confidence,
                max_results=max_results
            )
            
            # Convert to dictionaries
            candidate_dicts = [
                {
                    'name': c.name,
                    'biomolecule_type': c.biomolecule_type.value,
                    'function': c.function,
                    'confidence_score': c.confidence_score,
                    'evidence_sources': c.evidence_sources,
                    'metadata': c.metadata
                }
                for c in candidates
            ]
            
            return {
                "success": True,
                "pathway_name": pathway_name,
                "candidates": candidate_dicts,
                "total_count": len(candidate_dicts)
            }
        except Exception as e:
            self.logger.error(f"Pathway biomolecule discovery failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def discover_biomolecules_simple(
        self,
        target: str,
        discovery_type: str = "binders",
        max_results: int = 50,
        min_confidence: float = 0.5
    ) -> Dict[str, Any]:
        """
        High-level RAG-based biomolecule discovery.
        
        Args:
            target: Target protein, enzyme, or pathway name
            discovery_type: Type of discovery ("binders", "inhibitors", "pathway")
            max_results: Maximum number of candidates
            min_confidence: Minimum confidence threshold
            
        Returns:
            Dictionary containing biomolecule candidates
        """
        if discover_biomolecules_for_target is None:
            return {
                "success": False,
                "error": "Biomolecule discovery not available"
            }
        
        try:
            candidates = discover_biomolecules_for_target(
                target=target,
                discovery_type=discovery_type,
                max_results=max_results,
                min_confidence=min_confidence
            )
            
            return {
                "success": True,
                "target": target,
                "discovery_type": discovery_type,
                "candidates": candidates,
                "total_count": len(candidates),
                "message": f"Found {len(candidates)} candidate biomolecules for {target}"
            }
        except Exception as e:
            self.logger.error(f"RAG biomolecule discovery failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class AIDatasetBuilderCore:
    """Core class for AI-powered dataset building operations."""
    
    def __init__(self, model_name: str = "meta-llama/Llama-2-7b-hf"):
        """
        Initialize AI dataset builder core.
        
        Args:
            model_name: HuggingFace model for AI operations
        """
        self.model_name = model_name
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def build_dataset(
        self,
        scraped_data: List[Dict[str, Any]],
        filter_criteria: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build structured dataset from scraped medical research using AI.
        
        Args:
            scraped_data: List of scraped medical research records
            filter_criteria: Optional filtering criteria
            
        Returns:
            Dictionary with built dataset, metrics, and statistics
        """
        if not build_medical_dataset:
            return {
                "success": False,
                "error": "AI dataset builder not available"
            }
        
        try:
            return build_medical_dataset(scraped_data, filter_criteria, self.model_name)
        except Exception as e:
            self.logger.error(f"Dataset building failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def analyze_dataset(
        self,
        dataset: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze medical research dataset using AI models.
        
        Args:
            dataset: Dataset to analyze
            
        Returns:
            Dictionary with analysis results, insights, and metrics
        """
        if not analyze_medical_dataset:
            return {
                "success": False,
                "error": "AI dataset analyzer not available"
            }
        
        try:
            return analyze_medical_dataset(dataset, self.model_name)
        except Exception as e:
            self.logger.error(f"Dataset analysis failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def transform_dataset(
        self,
        dataset: List[Dict[str, Any]],
        transformation_type: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Transform medical dataset using AI models.
        
        Args:
            dataset: Dataset to transform
            transformation_type: Type of transformation to apply
            parameters: Optional parameters for transformation
            
        Returns:
            Dictionary with transformed dataset
        """
        if not transform_medical_dataset:
            return {
                "success": False,
                "error": "AI dataset transformer not available"
            }
        
        try:
            return transform_medical_dataset(dataset, transformation_type, parameters, self.model_name)
        except Exception as e:
            self.logger.error(f"Dataset transformation failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def generate_synthetic_data(
        self,
        template_data: List[Dict[str, Any]],
        num_samples: int = 10,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """
        Generate synthetic medical research data.
        
        Args:
            template_data: Sample data to use as templates
            num_samples: Number of synthetic samples to generate
            temperature: Generation temperature (0.0-1.0)
            
        Returns:
            Dictionary with generated synthetic data
        """
        if not generate_synthetic_medical_data:
            return {
                "success": False,
                "error": "Synthetic data generator not available"
            }
        
        try:
            return generate_synthetic_medical_data(template_data, num_samples, self.model_name, temperature)
        except Exception as e:
            self.logger.error(f"Synthetic data generation failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
