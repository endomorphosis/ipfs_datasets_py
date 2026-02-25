#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Biomolecule Discovery Engine — reusable business logic.

Contains the core data classes and ``BiomoleculeDiscoveryEngine`` that can be
imported independently of MCP.  The MCP tool wrapper lives in
``biomolecule_discovery.py`` and imports from here.

Designed to work with generative-protein-binder-design for model inference downstream.
"""

import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass
from enum import Enum
import re


logger = logging.getLogger(__name__)


class BiomoleculeType(Enum):
    """Types of biomolecules that can be discovered."""
    PROTEIN = "protein"
    ENZYME = "enzyme"
    ANTIBODY = "antibody"
    PEPTIDE = "peptide"
    SMALL_MOLECULE = "small_molecule"
    NUCLEIC_ACID = "nucleic_acid"
    LIGAND = "ligand"
    RECEPTOR = "receptor"
    INHIBITOR = "inhibitor"
    AGONIST = "agonist"
    ANTAGONIST = "antagonist"


class InteractionType(Enum):
    """Types of biomolecular interactions."""
    BINDING = "binding"
    INHIBITION = "inhibition"
    ACTIVATION = "activation"
    PHOSPHORYLATION = "phosphorylation"
    CATALYSIS = "catalysis"
    REGULATION = "regulation"
    TRANSPORT = "transport"
    SIGNAL_TRANSDUCTION = "signal_transduction"


@dataclass
class BiomoleculeCandidate:
    """
    Represents a discovered biomolecule candidate.
    
    Attributes:
        name: Biomolecule name
        biomolecule_type: Type of biomolecule
        uniprot_id: UniProt identifier (if protein)
        pubchem_id: PubChem identifier (if small molecule)
        sequence: Amino acid or nucleotide sequence (if applicable)
        structure: Structure information (PDB ID, SMILES, etc.)
        function: Biological function description
        interactions: Known interactions with other biomolecules
        therapeutic_relevance: Therapeutic application information
        confidence_score: Confidence in the recommendation (0-1)
        evidence_sources: List of PMIDs or other evidence sources
        metadata: Additional metadata
    """
    name: str
    biomolecule_type: BiomoleculeType
    uniprot_id: Optional[str] = None
    pubchem_id: Optional[str] = None
    sequence: Optional[str] = None
    structure: Optional[Dict[str, str]] = None
    function: Optional[str] = None
    interactions: List[Dict[str, Any]] = None
    therapeutic_relevance: Optional[str] = None
    confidence_score: float = 0.0
    evidence_sources: List[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.interactions is None:
            self.interactions = []
        if self.evidence_sources is None:
            self.evidence_sources = []
        if self.metadata is None:
            self.metadata = {}
        if self.structure is None:
            self.structure = {}


class BiomoleculeDiscoveryEngine:
    """
    Engine for discovering and recommending biomolecule candidates from research data.
    
    This class uses RAG (Retrieval Augmented Generation) to find relevant biomolecules
    from the scraped medical research datasets. It can identify proteins, enzymes,
    small molecules, and other biomolecules relevant to specific targets or processes.
    
    Example:
        >>> engine = BiomoleculeDiscoveryEngine()
        >>> candidates = engine.discover_protein_binders(
        ...     target_protein="SARS-CoV-2 spike protein",
        ...     interaction_type=InteractionType.BINDING,
        ...     min_confidence=0.7
        ... )
        >>> for candidate in candidates:
        ...     print(f"{candidate.name}: {candidate.confidence_score}")
    """
    
    def __init__(self, use_rag: bool = True):
        """
        Initialize the biomolecule discovery engine.
        
        Args:
            use_rag: Whether to use RAG for enhanced discovery (default: True)
        """
        self.use_rag = use_rag
        self.discovered_biomolecules = {}
        
        # Common protein/enzyme name patterns
        self.protein_patterns = [
            r'\b[A-Z][a-z]+-?\d+[a-z]?\b',  # e.g., Akt1, p53
            r'\b[A-Z]{2,}[0-9]+\b',  # e.g., ACE2, TMPRSS2
            r'\b[A-Z][a-z]+\s+[A-Z][a-z]+\b',  # e.g., Protein Kinase
        ]
        
        # Common small molecule patterns
        self.compound_patterns = [
            r'\b[A-Z][a-z]+\s*-?\s*\d+\b',  # e.g., Compound-1, Drug123
            r'\b[A-Z]{2,}-\d+\b',  # e.g., AB-123
        ]
    
    def discover_protein_binders(
        self,
        target_protein: str,
        interaction_type: Optional[InteractionType] = None,
        min_confidence: float = 0.5,
        max_results: int = 50
    ) -> List[BiomoleculeCandidate]:
        """
        Discover protein binders for a specific target protein.
        
        This method searches medical research for proteins, antibodies, or peptides
        that bind to the specified target protein. Useful for finding candidates
        for generative protein binder design.
        
        Args:
            target_protein: Name of the target protein (e.g., "SARS-CoV-2 spike")
            interaction_type: Type of interaction to search for
            min_confidence: Minimum confidence score for candidates
            max_results: Maximum number of results to return
            
        Returns:
            List of BiomoleculeCandidate objects sorted by confidence
            
        Example:
            >>> candidates = engine.discover_protein_binders(
            ...     "PD-L1",
            ...     interaction_type=InteractionType.BINDING,
            ...     min_confidence=0.7
            ... )
        """
        logger.info(f"Discovering protein binders for: {target_protein}")
        
        # Import scrapers
        try:
            from .pubmed_scraper import PubMedScraper
            from .clinical_trials_scraper import ClinicalTrialsScraper
        except ImportError:
            logger.warning("Scrapers not available, using mock data")
            return self._generate_mock_binders(target_protein, max_results)
        
        candidates = []
        
        # Search PubMed for binding studies
        pubmed_scraper = PubMedScraper()
        
        # Build search query
        interaction_term = interaction_type.value if interaction_type else "binding"
        query = f"{target_protein} AND {interaction_term} AND (antibody OR protein OR peptide)"
        
        try:
            articles = pubmed_scraper.search_medical_research(
                query=query,
                max_results=max_results,
                research_type="research article"
            )
            
            # Extract biomolecule candidates from articles
            for article in articles:
                extracted = self._extract_biomolecules_from_article(
                    article,
                    target_protein,
                    interaction_type
                )
                candidates.extend(extracted)
            
        except Exception as e:
            logger.error(f"Error searching PubMed: {e}")
        
        # Search clinical trials for therapeutic candidates
        try:
            trials_scraper = ClinicalTrialsScraper()
            trials = trials_scraper.search_trials(
                query=target_protein,
                max_results=20
            )
            
            for trial in trials:
                extracted = self._extract_biomolecules_from_trial(
                    trial,
                    target_protein
                )
                candidates.extend(extracted)
                
        except Exception as e:
            logger.error(f"Error searching clinical trials: {e}")
        
        # Deduplicate and score candidates
        candidates = self._deduplicate_and_score(candidates, min_confidence)
        
        # Sort by confidence score
        candidates.sort(key=lambda x: x.confidence_score, reverse=True)
        
        return candidates[:max_results]
    
    def discover_enzyme_inhibitors(
        self,
        target_enzyme: str,
        enzyme_class: Optional[str] = None,
        min_confidence: float = 0.5,
        max_results: int = 50
    ) -> List[BiomoleculeCandidate]:
        """
        Discover enzyme inhibitors for a specific target enzyme.
        
        Searches for small molecules, peptides, or proteins that inhibit
        the specified enzyme.
        
        Args:
            target_enzyme: Name of the target enzyme (e.g., "ACE2", "protease")
            enzyme_class: Enzyme classification (e.g., "kinase", "protease")
            min_confidence: Minimum confidence score
            max_results: Maximum number of results
            
        Returns:
            List of BiomoleculeCandidate inhibitors
        """
        logger.info(f"Discovering inhibitors for: {target_enzyme}")
        
        try:
            from .pubmed_scraper import PubMedScraper
        except ImportError:
            return self._generate_mock_inhibitors(target_enzyme, max_results)
        
        candidates = []
        pubmed_scraper = PubMedScraper()
        
        # Build search query
        query = f"{target_enzyme} AND inhibitor"
        if enzyme_class:
            query += f" AND {enzyme_class}"
        
        try:
            articles = pubmed_scraper.search_medical_research(
                query=query,
                max_results=max_results,
                research_type="research article"
            )
            
            for article in articles:
                extracted = self._extract_inhibitors_from_article(
                    article,
                    target_enzyme
                )
                candidates.extend(extracted)
                
        except Exception as e:
            logger.error(f"Error searching for inhibitors: {e}")
        
        candidates = self._deduplicate_and_score(candidates, min_confidence)
        candidates.sort(key=lambda x: x.confidence_score, reverse=True)
        
        return candidates[:max_results]
    
    def discover_pathway_biomolecules(
        self,
        pathway_name: str,
        biomolecule_types: Optional[List[BiomoleculeType]] = None,
        min_confidence: float = 0.5,
        max_results: int = 100
    ) -> List[BiomoleculeCandidate]:
        """
        Discover biomolecules involved in a specific biological pathway.
        
        Useful for understanding pathway components and finding intervention targets.
        
        Args:
            pathway_name: Name of the pathway (e.g., "mTOR signaling", "glycolysis")
            biomolecule_types: Types of biomolecules to search for
            min_confidence: Minimum confidence score
            max_results: Maximum number of results
            
        Returns:
            List of BiomoleculeCandidate objects in the pathway
        """
        logger.info(f"Discovering pathway biomolecules for: {pathway_name}")
        
        try:
            from .pubmed_scraper import PubMedScraper
        except ImportError:
            return []
        
        candidates = []
        pubmed_scraper = PubMedScraper()
        
        # Search for pathway components
        query = f"{pathway_name} AND pathway AND (protein OR enzyme OR receptor)"
        
        try:
            articles = pubmed_scraper.scrape_biochemical_research(
                topic=pathway_name,
                max_results=max_results
            )
            
            for article in articles:
                extracted = self._extract_pathway_components(
                    article,
                    pathway_name,
                    biomolecule_types
                )
                candidates.extend(extracted)
                
        except Exception as e:
            logger.error(f"Error discovering pathway biomolecules: {e}")
        
        candidates = self._deduplicate_and_score(candidates, min_confidence)
        candidates.sort(key=lambda x: x.confidence_score, reverse=True)
        
        return candidates[:max_results]
    
    def _extract_biomolecules_from_article(
        self,
        article: Dict[str, Any],
        target: str,
        interaction_type: Optional[InteractionType]
    ) -> List[BiomoleculeCandidate]:
        """Extract biomolecule candidates from a research article."""
        candidates = []
        
        # Combine title and abstract for analysis
        text = f"{article.get('title', '')} {article.get('abstract', '')}"
        
        # Extract protein names using patterns
        protein_names = self._extract_protein_names(text)
        
        for name in protein_names:
            # Skip if it's the target itself
            if name.lower() in target.lower():
                continue
            
            # Determine biomolecule type
            biomol_type = self._classify_biomolecule(name, text)
            
            # Calculate confidence based on context
            confidence = self._calculate_confidence(name, text, target, interaction_type)
            
            candidate = BiomoleculeCandidate(
                name=name,
                biomolecule_type=biomol_type,
                function=self._extract_function(name, text),
                confidence_score=confidence,
                evidence_sources=[article.get('pmid', '')],
                metadata={
                    'source_type': 'pubmed',
                    'title': article.get('title', ''),
                    'journal': article.get('journal', ''),
                    'publication_date': article.get('publication_date', '')
                }
            )
            
            candidates.append(candidate)
        
        return candidates
    
    def _extract_biomolecules_from_trial(
        self,
        trial: Dict[str, Any],
        target: str
    ) -> List[BiomoleculeCandidate]:
        """Extract biomolecule candidates from clinical trial data."""
        candidates = []
        
        # Extract from interventions
        for intervention in trial.get('interventions', []):
            if isinstance(intervention, str):
                name = intervention
            else:
                name = intervention.get('name', '') if isinstance(intervention, dict) else str(intervention)
            
            # Skip if it's the target
            if name.lower() in target.lower() or not name:
                continue
            
            biomol_type = self._classify_biomolecule(name, trial.get('title', ''))
            
            candidate = BiomoleculeCandidate(
                name=name,
                biomolecule_type=biomol_type,
                therapeutic_relevance=trial.get('title', ''),
                confidence_score=0.7,  # Clinical trial data has high confidence
                evidence_sources=[trial.get('nct_id', '')],
                metadata={
                    'source_type': 'clinical_trial',
                    'phase': trial.get('phase', ''),
                    'status': trial.get('status', ''),
                    'conditions': trial.get('conditions', [])
                }
            )
            
            candidates.append(candidate)
        
        return candidates
    
    def _extract_inhibitors_from_article(
        self,
        article: Dict[str, Any],
        target_enzyme: str
    ) -> List[BiomoleculeCandidate]:
        """Extract enzyme inhibitors from article."""
        candidates = []
        
        text = f"{article.get('title', '')} {article.get('abstract', '')}"
        
        # Look for inhibitor mentions
        inhibitor_pattern = r'(\b[A-Z][a-z]+[-\s]?\d*\b)\s+inhibit'
        matches = re.findall(inhibitor_pattern, text, re.IGNORECASE)
        
        for name in matches:
            name = name.strip()
            if not name or len(name) < 3:
                continue
            
            confidence = 0.6 if 'specific' in text.lower() or 'selective' in text.lower() else 0.4
            
            candidate = BiomoleculeCandidate(
                name=name,
                biomolecule_type=BiomoleculeType.INHIBITOR,
                function=f"Inhibitor of {target_enzyme}",
                confidence_score=confidence,
                evidence_sources=[article.get('pmid', '')],
                interactions=[{
                    'type': InteractionType.INHIBITION.value,
                    'target': target_enzyme
                }]
            )
            
            candidates.append(candidate)
        
        return candidates
    
    def _extract_pathway_components(
        self,
        article: Dict[str, Any],
        pathway_name: str,
        biomolecule_types: Optional[List[BiomoleculeType]]
    ) -> List[BiomoleculeCandidate]:
        """Extract pathway component biomolecules."""
        candidates = []
        
        text = f"{article.get('title', '')} {article.get('abstract', '')}"
        protein_names = self._extract_protein_names(text)
        
        for name in protein_names:
            biomol_type = self._classify_biomolecule(name, text)
            
            # Filter by requested types if specified
            if biomolecule_types and biomol_type not in biomolecule_types:
                continue
            
            candidate = BiomoleculeCandidate(
                name=name,
                biomolecule_type=biomol_type,
                function=f"Component of {pathway_name} pathway",
                confidence_score=0.5,
                evidence_sources=[article.get('pmid', '')]
            )
            
            candidates.append(candidate)
        
        return candidates
    
    def _extract_protein_names(self, text: str) -> Set[str]:
        """Extract potential protein names from text using patterns."""
        names = set()
        
        for pattern in self.protein_patterns:
            matches = re.findall(pattern, text)
            names.update(matches)
        
        return names
    
    def _classify_biomolecule(self, name: str, context: str) -> BiomoleculeType:
        """Classify a biomolecule based on its name and context."""
        name_lower = name.lower()
        context_lower = context.lower()
        
        if 'antibody' in context_lower or name_lower.startswith(('mab', 'igg')):
            return BiomoleculeType.ANTIBODY
        elif 'enzyme' in context_lower or name.endswith('ase'):
            return BiomoleculeType.ENZYME
        elif 'peptide' in context_lower or len(name) < 10:
            return BiomoleculeType.PEPTIDE
        elif 'receptor' in context_lower or 'R' in name:
            return BiomoleculeType.RECEPTOR
        elif 'inhibitor' in context_lower:
            return BiomoleculeType.INHIBITOR
        else:
            return BiomoleculeType.PROTEIN
    
    def _calculate_confidence(
        self,
        name: str,
        text: str,
        target: str,
        interaction_type: Optional[InteractionType]
    ) -> float:
        """Calculate confidence score for a biomolecule candidate."""
        confidence = 0.5  # Base confidence
        
        # Boost if interaction type is mentioned
        if interaction_type:
            if interaction_type.value in text.lower():
                confidence += 0.2
        
        # Boost if both name and target appear close together
        if name in text and target in text:
            # Simple proximity check
            name_pos = text.find(name)
            target_pos = text.find(target)
            if abs(name_pos - target_pos) < 200:  # Within 200 characters
                confidence += 0.2
        
        # Boost if specific terms are present
        if any(term in text.lower() for term in ['specific', 'selective', 'high affinity']):
            confidence += 0.1
        
        return min(confidence, 1.0)
    
    def _extract_function(self, name: str, text: str) -> Optional[str]:
        """Extract function description for a biomolecule."""
        # Simple extraction: look for sentences containing the name
        sentences = text.split('.')
        for sentence in sentences:
            if name in sentence:
                # Return first sentence mentioning the name
                return sentence.strip()[:200]  # Limit length
        return None
    
    def _deduplicate_and_score(
        self,
        candidates: List[BiomoleculeCandidate],
        min_confidence: float
    ) -> List[BiomoleculeCandidate]:
        """Deduplicate candidates and filter by confidence."""
        # Group by name
        candidate_map = {}
        
        for candidate in candidates:
            name = candidate.name
            if name not in candidate_map:
                candidate_map[name] = candidate
            else:
                # Merge evidence and update confidence
                existing = candidate_map[name]
                existing.evidence_sources.extend(candidate.evidence_sources)
                existing.confidence_score = max(existing.confidence_score, candidate.confidence_score)
        
        # Filter by confidence
        filtered = [c for c in candidate_map.values() if c.confidence_score >= min_confidence]
        
        return filtered
    
    def _generate_mock_binders(self, target: str, max_results: int) -> List[BiomoleculeCandidate]:
        """Generate mock binder candidates for testing."""
        logger.info(f"Generating mock binders for {target}")
        
        mock_binders = [
            BiomoleculeCandidate(
                name=f"Antibody-{i}",
                biomolecule_type=BiomoleculeType.ANTIBODY,
                function=f"Binds to {target}",
                confidence_score=0.8 - (i * 0.1),
                evidence_sources=[f"PMID:123456{i}"],
                metadata={'mock': True}
            )
            for i in range(min(5, max_results))
        ]
        
        return mock_binders
    
    def _generate_mock_inhibitors(self, target: str, max_results: int) -> List[BiomoleculeCandidate]:
        """Generate mock inhibitor candidates for testing."""
        logger.info(f"Generating mock inhibitors for {target}")
        
        mock_inhibitors = [
            BiomoleculeCandidate(
                name=f"Compound-{i}",
                biomolecule_type=BiomoleculeType.INHIBITOR,
                function=f"Inhibits {target}",
                confidence_score=0.7 - (i * 0.1),
                evidence_sources=[f"PMID:789012{i}"],
                metadata={'mock': True}
            )
            for i in range(min(5, max_results))
        ]
        
        return mock_inhibitors



__all__ = [
    "BiomoleculeType",
    "InteractionType",
    "BiomoleculeCandidate",
    "BiomoleculeDiscoveryEngine",
]

