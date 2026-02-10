# ipfs_datasets_py/mcp_server/tools/dataset_tools/text_to_fol.py
"""MCP tool wrapper for converting text to First-Order Logic (FOL).

Core conversion logic lives in the package layer:
- `ipfs_datasets_py.logic.tools.text_to_fol.convert_text_to_fol`

This MCP module should only provide the MCP-facing entrypoint.
"""

from typing import Any, Dict, List, Optional, Union

from ipfs_datasets_py.logic.tools.text_to_fol import convert_text_to_fol


async def text_to_fol(
    text_input: Union[str, Dict[str, Any]],
    domain_predicates: Optional[List[str]] = None,
    output_format: str = "json",
    include_metadata: bool = True,
    confidence_threshold: float = 0.5,
) -> Dict[str, Any]:
    """MCP tool function for converting text to FOL."""
    return await convert_text_to_fol(
        text_input=text_input,
        domain_predicates=domain_predicates,
        output_format=output_format,
        include_metadata=include_metadata,
        confidence_threshold=confidence_threshold,
    )


async def main() -> Dict[str, Any]:
    """Main function for MCP tool registration."""
    return {
        "status": "success",
        "message": "Text to FOL converter tool initialized",
        "tool": "text_to_fol",
        "description": "Converts natural language text to First-Order Logic formulas",
    }
