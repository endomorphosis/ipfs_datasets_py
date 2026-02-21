"""
PDF LLM Optimization Tool - thin MCP wrapper.

Business logic is in:
    ipfs_datasets_py.processors.specialized.pdf.llm_optimize_engine
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Union

try:
    from ipfs_datasets_py.processors.specialized.pdf.llm_optimize_engine import (
        pdf_optimize_for_llm as _engine_fn,
    )
    _ENGINE_AVAILABLE = True
except ImportError:
    _engine_fn = None
    _ENGINE_AVAILABLE = False


async def pdf_optimize_for_llm(
    pdf_source: Union[str, dict, None] = None,
    target_llm: str = "gpt-4",
    chunk_strategy: str = "semantic",
    max_chunk_size: int = 4000,
    overlap_size: int = 200,
    preserve_structure: bool = True,
    include_metadata: bool = True,
) -> Dict[str, Any]:
    """Thin MCP wrapper — see llm_optimize_engine.pdf_optimize_for_llm."""
    if not _ENGINE_AVAILABLE:
        return {"status": "error", "message": "LLM optimization engine not available"}
    return await _engine_fn(
        pdf_source=pdf_source,
        target_llm=target_llm,
        chunk_strategy=chunk_strategy,
        max_chunk_size=max_chunk_size,
        overlap_size=overlap_size,
        preserve_structure=preserve_structure,
        include_metadata=include_metadata,
    )
