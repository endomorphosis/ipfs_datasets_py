"""
CLI tools for IPFS Datasets MCP Server.
"""

# Export medical research CLI commands
try:
    from .medical_research_cli import (
        scrape_pubmed_cli,
        scrape_clinical_trials_cli,
        discover_protein_binders_cli,
        discover_enzyme_inhibitors_cli,
        discover_biomolecules_rag_cli
    )
    __all__ = [
        'scrape_pubmed_cli',
        'scrape_clinical_trials_cli',
        'discover_protein_binders_cli',
        'discover_enzyme_inhibitors_cli',
        'discover_biomolecules_rag_cli'
    ]
except ImportError as e:
    # Medical research tools not available
    __all__ = []

