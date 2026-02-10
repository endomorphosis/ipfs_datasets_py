"""MCP wrapper for PDF relationship analysis.

Core implementation lives in `ipfs_datasets_py.processors.relationship_analysis_api`.
"""

from typing import Any, Dict, List, Optional

async def pdf_analyze_relationships(
    document_id: str,
    analysis_type: str = "comprehensive",
    include_cross_document: bool = True,
    relationship_types: Optional[List[str]] = None,
    min_confidence: float = 0.6,
    max_relationships: int = 100
) -> Dict[str, Any]:
    from ipfs_datasets_py.processors.relationship_analysis_api import (
        pdf_analyze_relationships as core_analyze,
    )

    return await core_analyze(
        document_id=document_id,
        analysis_type=analysis_type,
        include_cross_document=include_cross_document,
        relationship_types=relationship_types,
        min_confidence=min_confidence,
        max_relationships=max_relationships,
    )
