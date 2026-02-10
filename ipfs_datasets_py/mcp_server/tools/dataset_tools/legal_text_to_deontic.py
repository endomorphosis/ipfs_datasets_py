# ipfs_datasets_py/mcp_server/tools/dataset_tools/legal_text_to_deontic.py
"""MCP tool wrapper for converting legal text to deontic logic.

Core conversion logic lives in the package layer:
- `ipfs_datasets_py.logic.deontic.legal_text_to_deontic.convert_legal_text_to_deontic`

This MCP module should only provide the MCP-facing entrypoint.
"""

from typing import Any, Dict, Union

from ipfs_datasets_py.logic.deontic.legal_text_to_deontic import convert_legal_text_to_deontic


async def legal_text_to_deontic(
    text_input: Union[str, Dict[str, Any]],
    jurisdiction: str = "us",
    document_type: str = "statute",
    output_format: str = "json",
    extract_obligations: bool = True,
    include_exceptions: bool = True,
) -> Dict[str, Any]:
    """MCP tool function for converting legal text to deontic logic."""
    return await convert_legal_text_to_deontic(
        legal_text=text_input,
        jurisdiction=jurisdiction,
        document_type=document_type,
        output_format=output_format,
        extract_obligations=extract_obligations,
        include_exceptions=include_exceptions,
    )


async def main() -> Dict[str, Any]:
    """Main function for MCP tool registration."""
    return {
        "status": "success",
        "message": "Legal text to deontic logic converter tool initialized",
        "tool": "legal_text_to_deontic",
        "description": "Converts legal text into deontic logic formulas",
    }
