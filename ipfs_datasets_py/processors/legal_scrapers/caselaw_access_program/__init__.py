"""Caselaw Access Program integrations.

This package contains helpers for loading CAP-related datasets and integrating
them with the vector search stack in ``ipfs_datasets_py.vector_stores``.
"""

from .vector_search_integration import (
	CAPIngestionResult,
	CAPRetrievalPlan,
	CAPVectorSearchConfig,
	CaselawAccessVectorSearch,
	KGSeedGraph,
	create_caselaw_access_vector_search,
)

__all__ = [
	"CAPIngestionResult",
	"CAPRetrievalPlan",
	"CAPVectorSearchConfig",
	"CaselawAccessVectorSearch",
	"KGSeedGraph",
	"create_caselaw_access_vector_search",
]
