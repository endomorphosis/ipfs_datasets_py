"""
Medical Research Data Scrapers for Medicine Dashboard.

This module provides scrapers for collecting medical, biochemical, and population health
data from various research databases and repositories to support the medicine dashboard's
temporal deontic logic reasoning system.

Available scrapers:
- PubMed medical literature
- ClinicalTrials.gov trial data
- NIH research databases
- arXiv medical papers
- CDC population health data
- WHO health statistics
- Biomolecule discovery engine (RAG-powered)
"""

from typing import List, Dict, Any, Optional

# Import scrapers
try:
    from .pubmed_scraper import PubMedScraper
except ImportError:
    PubMedScraper = None

try:
    from .clinical_trials_scraper import ClinicalTrialsScraper
except ImportError:
    ClinicalTrialsScraper = None

try:
    from .nih_data_scraper import NIHDataScraper
except ImportError:
    NIHDataScraper = None

try:
    from .arxiv_medical_scraper import ArXivMedicalScraper
except ImportError:
    ArXivMedicalScraper = None

try:
    from .cdc_health_data_scraper import CDCHealthDataScraper
except ImportError:
    CDCHealthDataScraper = None

try:
    from .who_stats_scraper import WHOStatsScraper
except ImportError:
    WHOStatsScraper = None

try:
    from .biomolecule_discovery import (
        BiomoleculeDiscoveryEngine,
        BiomoleculeCandidate,
        BiomoleculeType,
        InteractionType,
        discover_biomolecules_for_target
    )
except ImportError:
    BiomoleculeDiscoveryEngine = None
    BiomoleculeCandidate = None
    BiomoleculeType = None
    InteractionType = None
    discover_biomolecules_for_target = None

# Import MCP tools for unified access
try:
    from .medical_research_mcp_tools import (
        scrape_pubmed_medical_research,
        scrape_clinical_trials,
        get_trial_outcomes_for_theorems,
        generate_medical_theorems_from_trials,
        validate_medical_theorem_fuzzy,
        scrape_biochemical_research,
        scrape_population_health_data,
        discover_protein_binders,
        discover_enzyme_inhibitors,
        discover_pathway_biomolecules,
        discover_biomolecules_rag
    )
except ImportError:
    scrape_pubmed_medical_research = None
    scrape_clinical_trials = None
    get_trial_outcomes_for_theorems = None
    generate_medical_theorems_from_trials = None
    validate_medical_theorem_fuzzy = None
    scrape_biochemical_research = None
    scrape_population_health_data = None
    discover_protein_binders = None
    discover_enzyme_inhibitors = None
    discover_pathway_biomolecules = None
    discover_biomolecules_rag = None

__all__ = [
    # Scraper classes
    'PubMedScraper',
    'ClinicalTrialsScraper',
    'NIHDataScraper',
    'ArXivMedicalScraper',
    'CDCHealthDataScraper',
    'WHOStatsScraper',
    # Biomolecule discovery
    'BiomoleculeDiscoveryEngine',
    'BiomoleculeCandidate',
    'BiomoleculeType',
    'InteractionType',
    'discover_biomolecules_for_target',
    # MCP tool functions (for unified access)
    'scrape_pubmed_medical_research',
    'scrape_clinical_trials',
    'get_trial_outcomes_for_theorems',
    'generate_medical_theorems_from_trials',
    'validate_medical_theorem_fuzzy',
    'scrape_biochemical_research',
    'scrape_population_health_data',
    'discover_protein_binders',
    'discover_enzyme_inhibitors',
    'discover_pathway_biomolecules',
    'discover_biomolecules_rag',
]
