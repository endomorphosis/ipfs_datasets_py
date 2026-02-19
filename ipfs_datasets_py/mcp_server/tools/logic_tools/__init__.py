"""
Logic tools for the MCP server and CLI.

All tools are plain ``async`` functions auto-discovered by:

- ``ipfs_datasets_cli.py``  — CLI tool discovery (globs ``*.py`` files in
  each tool category directory and finds top-level async functions).
- MCP server tool registry  — calls functions directly by module path.
- Direct Python imports      — ``from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_prove``

Business logic lives in
:class:`~ipfs_datasets_py.core_operations.LogicProcessor`; the functions
here are thin wrappers that delegate to it.

Tools (24 functions across 10 modules)
---------------------------------------
temporal_deontic_logic_tools  check_document_consistency, query_theorems,
                              bulk_process_caselaw, add_theorem
tdfol_prove_tool              tdfol_prove, tdfol_batch_prove
tdfol_parse_tool              tdfol_parse
tdfol_convert_tool            tdfol_convert
tdfol_kb_tool                 tdfol_kb_add_axiom, tdfol_kb_add_theorem,
                              tdfol_kb_query, tdfol_kb_export
tdfol_visualize_tool          tdfol_visualize
cec_inference_tool            cec_list_rules, cec_apply_rule,
                              cec_check_rule, cec_rule_info
cec_prove_tool                cec_prove, cec_check_theorem
cec_parse_tool                cec_parse, cec_validate_formula
cec_analysis_tool             cec_analyze_formula, cec_formula_complexity
logic_capabilities_tool       logic_capabilities, logic_health
logic_graphrag_tool           logic_build_knowledge_graph, logic_verify_rag_output
"""

from .temporal_deontic_logic_tools import (
    check_document_consistency,
    query_theorems,
    bulk_process_caselaw,
    add_theorem,
)
from .tdfol_prove_tool import tdfol_prove, tdfol_batch_prove
from .tdfol_parse_tool import tdfol_parse
from .tdfol_convert_tool import tdfol_convert
from .tdfol_kb_tool import (
    tdfol_kb_add_axiom,
    tdfol_kb_add_theorem,
    tdfol_kb_query,
    tdfol_kb_export,
)
from .tdfol_visualize_tool import tdfol_visualize
from .cec_inference_tool import (
    cec_list_rules,
    cec_apply_rule,
    cec_check_rule,
    cec_rule_info,
)
from .cec_prove_tool import cec_prove, cec_check_theorem
from .cec_parse_tool import cec_parse, cec_validate_formula
from .cec_analysis_tool import cec_analyze_formula, cec_formula_complexity
from .logic_capabilities_tool import logic_capabilities, logic_health
from .logic_graphrag_tool import logic_build_knowledge_graph, logic_verify_rag_output

__all__ = [
    # temporal deontic logic
    "check_document_consistency",
    "query_theorems",
    "bulk_process_caselaw",
    "add_theorem",
    # tdfol proving
    "tdfol_prove",
    "tdfol_batch_prove",
    # tdfol utilities
    "tdfol_parse",
    "tdfol_convert",
    # tdfol knowledge base
    "tdfol_kb_add_axiom",
    "tdfol_kb_add_theorem",
    "tdfol_kb_query",
    "tdfol_kb_export",
    # tdfol visualization
    "tdfol_visualize",
    # cec inference rules
    "cec_list_rules",
    "cec_apply_rule",
    "cec_check_rule",
    "cec_rule_info",
    # cec proving and parsing
    "cec_prove",
    "cec_check_theorem",
    "cec_parse",
    "cec_validate_formula",
    # cec analysis
    "cec_analyze_formula",
    "cec_formula_complexity",
    # discovery
    "logic_capabilities",
    "logic_health",
    # graphrag
    "logic_build_knowledge_graph",
    "logic_verify_rag_output",
]
