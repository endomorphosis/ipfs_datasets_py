# Medical Research Scrapers

MCP tools for scraping and analysing biomedical data: PubMed literature, ClinicalTrials.gov,
biomolecule discovery, and AI-powered dataset construction.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `pubmed_scraper.py` | `scrape_pubmed()`, `search_pubmed()`, `fetch_pubmed_abstract()` | Scrape PubMed articles; full-text and abstract retrieval |
| `clinical_trials_scraper.py` | `scrape_clinical_trials()`, `search_trials()`, `get_trial_details()` | Scrape ClinicalTrials.gov data; search by condition, drug, phase |
| `biomolecule_engine.py` | `BiomoleculeDiscoveryEngine` class | Business logic for biomolecule discovery workflows (not MCP-facing) |
| `biomolecule_discovery.py` | `discover_biomolecules()`, `analyze_protein_interactions()` | MCP wrapper: biomolecule discovery and analysis |
| `ai_dataset_builder.py` | `build_medical_dataset()`, `filter_medical_data()`, `generate_synthetic_data()` | AI-powered biomedical dataset construction and augmentation |
| `medical_research_mcp_tools.py` | `run_literature_search()`, `analyze_clinical_data()`, `generate_research_summary()` | High-level MCP tools for the medicine dashboard |

## Usage

### PubMed search and scrape

```python
from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers import (
    search_pubmed, scrape_pubmed
)

# Search
results = await search_pubmed(
    query="CRISPR cancer therapy",
    max_results=100,
    date_from="2023-01-01",
    fields=["title", "abstract", "authors", "doi"]
)

# Scrape full articles
articles = await scrape_pubmed(
    pmids=results["pmids"],
    include_full_text=False,
    output_format="jsonl",
    output_path="/data/pubmed_cancer.jsonl"
)
```

### ClinicalTrials.gov

```python
from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers import scrape_clinical_trials

trials = await scrape_clinical_trials(
    condition="Alzheimer's Disease",
    phase=["PHASE3", "PHASE4"],
    status="RECRUITING",
    max_results=200
)
```

### AI dataset builder

```python
from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers import build_medical_dataset

dataset = await build_medical_dataset(
    sources=["pubmed", "clinical_trials"],
    topic="diabetes treatment",
    max_records=5000,
    filter_by_impact=True,  # Filter by journal impact factor
    output_path="/data/diabetes_dataset.parquet"
)
```

## API Access

| Scraper | API Key Required | Rate Limit |
|---------|-----------------|------------|
| PubMed | No (NCBI key for higher limits) | 3/s without key, 10/s with key |
| ClinicalTrials.gov | No | Standard web crawl limits |
| Biomolecule (UniProt, PDB) | No | Per-source limits |

## Dependencies

- `requests` — HTTP scraping
- `biopython` — PubMed API (`Entrez`)
- `ipfs_accelerate_py` — AI model integration for dataset builder

## Status

| Tool | Status |
|------|--------|
| `pubmed_scraper` | ✅ Production ready |
| `clinical_trials_scraper` | ✅ Production ready |
| `biomolecule_discovery` | ✅ Production ready |
| `ai_dataset_builder` | ✅ Production ready (requires ipfs_accelerate_py) |
| `medical_research_mcp_tools` | ✅ Production ready |
