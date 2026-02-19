"""Logic MCP tool wrappers."""

from .temporal_deontic_logic_tools import (
    TEMPORAL_DEONTIC_LOGIC_TOOLS,
    add_theorem,
    bulk_process_caselaw,
    check_document_consistency,
    query_theorems,
)
from .tdfol_parse_tool import TDFOL_PARSE_TOOLS
from .tdfol_prove_tool import TDFOL_PROVE_TOOLS
from .tdfol_convert_tool import TDFOL_CONVERT_TOOLS
from .tdfol_visualize_tool import tools as TDFOL_VISUALIZE_TOOLS
from .tdfol_kb_tool import tools as TDFOL_KB_TOOLS

# Combine all logic tools
ALL_LOGIC_TOOLS = (
    TEMPORAL_DEONTIC_LOGIC_TOOLS +
    TDFOL_PARSE_TOOLS +
    TDFOL_PROVE_TOOLS +
    TDFOL_CONVERT_TOOLS +
    TDFOL_VISUALIZE_TOOLS +
    TDFOL_KB_TOOLS
)

__all__ = [
    "TEMPORAL_DEONTIC_LOGIC_TOOLS",
    "TDFOL_PARSE_TOOLS",
    "TDFOL_PROVE_TOOLS",
    "TDFOL_CONVERT_TOOLS",
    "TDFOL_VISUALIZE_TOOLS",
    "TDFOL_KB_TOOLS",
    "ALL_LOGIC_TOOLS",
    "check_document_consistency",
    "query_theorems",
    "bulk_process_caselaw",
    "add_theorem",
]
