"""
Phase B2 unit tests — medical_research_scrapers category.

All functions are sync (not async).  They delegate immediately to
MedicalResearchCore / BiomoleculeDiscoveryCore / AIDatasetBuilderCore,
so we mock those classes at the module level to avoid hitting real APIs.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Module-level path
# ---------------------------------------------------------------------------

_MOD = "ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools"


# ---------------------------------------------------------------------------
# scrape_pubmed_medical_research
# ---------------------------------------------------------------------------

class TestScrapePubmedMedicalResearch:
    """Tests for scrape_pubmed_medical_research()."""

    def setup_method(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import (
            scrape_pubmed_medical_research,
        )
        self.fn = scrape_pubmed_medical_research

    def test_returns_dict_with_mock(self) -> None:
        with patch(f"{_MOD}.MedicalResearchCore") as mock_cls:
            mock_cls.return_value.scrape_pubmed_research.return_value = {
                "articles": [], "total_count": 0
            }
            result = self.fn("diabetes")
        assert isinstance(result, dict)

    def test_passes_max_results(self) -> None:
        with patch(f"{_MOD}.MedicalResearchCore") as mock_cls:
            instance = mock_cls.return_value
            instance.scrape_pubmed_research.return_value = {"articles": [], "total_count": 0}
            self.fn("diabetes", max_results=5)
            instance.scrape_pubmed_research.assert_called_once_with("diabetes", 5, None)

    def test_empty_query(self) -> None:
        with patch(f"{_MOD}.MedicalResearchCore") as mock_cls:
            mock_cls.return_value.scrape_pubmed_research.return_value = {
                "articles": [], "total_count": 0
            }
            result = self.fn("")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# scrape_clinical_trials
# ---------------------------------------------------------------------------

class TestScrapeClinicalTrials:
    """Tests for scrape_clinical_trials()."""

    def setup_method(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import (
            scrape_clinical_trials,
        )
        self.fn = scrape_clinical_trials

    def test_returns_dict_with_mock(self) -> None:
        with patch(f"{_MOD}.MedicalResearchCore") as mock_cls:
            mock_cls.return_value.scrape_clinical_trials.return_value = {
                "trials": [], "total_count": 0
            }
            result = self.fn("cancer")
        assert isinstance(result, dict)

    def test_condition_param(self) -> None:
        with patch(f"{_MOD}.MedicalResearchCore") as mock_cls:
            mock_cls.return_value.scrape_clinical_trials.return_value = {"trials": []}
            result = self.fn("cancer", condition="lung cancer")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# scrape_biochemical_research
# ---------------------------------------------------------------------------

class TestScrapeBiochemicalResearch:
    """Tests for scrape_biochemical_research()."""

    def setup_method(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import (
            scrape_biochemical_research,
        )
        self.fn = scrape_biochemical_research

    def test_returns_dict_with_mock(self) -> None:
        with patch(f"{_MOD}.MedicalResearchCore") as mock_cls:
            mock_cls.return_value.scrape_biochemical_research.return_value = {
                "papers": [], "total_count": 0
            }
            result = self.fn("CRISPR")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# discover_protein_binders
# ---------------------------------------------------------------------------

class TestDiscoverProteinBinders:
    """Tests for discover_protein_binders()."""

    def setup_method(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import (
            discover_protein_binders,
        )
        self.fn = discover_protein_binders

    def test_returns_dict_with_mock(self) -> None:
        with patch(f"{_MOD}.BiomoleculeDiscoveryCore") as mock_cls:
            mock_cls.return_value.discover_protein_binders.return_value = {
                "binders": [], "target_protein": "ACE2"
            }
            result = self.fn("ACE2")
        assert isinstance(result, dict)

    def test_min_confidence_param(self) -> None:
        with patch(f"{_MOD}.BiomoleculeDiscoveryCore") as mock_cls:
            mock_cls.return_value.discover_protein_binders.return_value = {"binders": []}
            result = self.fn("ACE2", min_confidence=0.8)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# build_dataset_from_scraped_data
# ---------------------------------------------------------------------------

class TestBuildDatasetFromScrapedData:
    """Tests for build_dataset_from_scraped_data()."""

    def setup_method(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import (
            build_dataset_from_scraped_data,
        )
        self.fn = build_dataset_from_scraped_data

    def test_returns_dict_with_mock(self) -> None:
        with patch(f"{_MOD}.AIDatasetBuilderCore") as mock_cls:
            mock_cls.return_value.build_dataset.return_value = {
                "dataset": [], "record_count": 0
            }
            result = self.fn([{"title": "paper1"}])
        assert isinstance(result, dict)

    def test_empty_list(self) -> None:
        with patch(f"{_MOD}.AIDatasetBuilderCore") as mock_cls:
            mock_cls.return_value.build_dataset.return_value = {"dataset": []}
            result = self.fn([])
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# generate_synthetic_dataset
# ---------------------------------------------------------------------------

class TestGenerateSyntheticDataset:
    """Tests for generate_synthetic_dataset()."""

    def setup_method(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.medical_research_mcp_tools import (
            generate_synthetic_dataset,
        )
        self.fn = generate_synthetic_dataset

    def test_returns_dict_with_mock(self) -> None:
        with patch(f"{_MOD}.AIDatasetBuilderCore") as mock_cls:
            mock_cls.return_value.generate_synthetic_data.return_value = {
                "samples": [], "num_samples": 3
            }
            result = self.fn([{"title": "template"}], num_samples=3)
        assert isinstance(result, dict)
