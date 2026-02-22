#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Medical Scrapers Package.

This package provides core business logic for medical research scraping,
theorem generation, and biomolecule discovery.

Exported Classes:
    - MedicalResearchCore: Core medical research scraping operations
    - MedicalTheoremCore: Medical theorem generation and validation
    - BiomoleculeDiscoveryCore: Biomolecule discovery operations
    - AIDatasetBuilderCore: AI-powered dataset building (research_scraper_core)
    - AIDatasetBuilder: Full AI dataset builder with HuggingFace model support
    - DatasetMetrics: Metrics dataclass for dataset quality evaluation
    - SyntheticDataConfig: Configuration dataclass for synthetic data generation
    - ClinicalTrialsScraper: Scraper for ClinicalTrials.gov
    - PubMedScraper: Scraper for PubMed medical literature
"""

from .research_scraper_core import (
    MedicalResearchCore,
    MedicalTheoremCore,
    BiomoleculeDiscoveryCore,
    AIDatasetBuilderCore
)
from .ai_dataset_builder_engine import (
    AIDatasetBuilder,
    DatasetMetrics,
    SyntheticDataConfig,
)
from .clinical_trials_engine import ClinicalTrialsScraper
from .pubmed_engine import PubMedScraper

__all__ = [
    'MedicalResearchCore',
    'MedicalTheoremCore',
    'BiomoleculeDiscoveryCore',
    'AIDatasetBuilderCore',
    'AIDatasetBuilder',
    'DatasetMetrics',
    'SyntheticDataConfig',
    'ClinicalTrialsScraper',
    'PubMedScraper',
]
