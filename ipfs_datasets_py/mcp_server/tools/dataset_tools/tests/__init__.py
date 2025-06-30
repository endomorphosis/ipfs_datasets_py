# ipfs_datasets_py/mcp_server/tools/dataset_tools/tests/__init__.py
"""
Tests for dataset tools logic conversion functionality.
"""

from .test_text_to_fol import test_text_to_fol_basic, test_text_to_fol_complex
from .test_legal_text_to_deontic import test_legal_text_basic, test_deontic_obligations
from .test_logic_utils import test_predicate_extraction, test_fol_parsing, test_deontic_parsing

__all__ = [
    "test_text_to_fol_basic",
    "test_text_to_fol_complex", 
    "test_legal_text_basic",
    "test_deontic_obligations",
    "test_predicate_extraction",
    "test_fol_parsing",
    "test_deontic_parsing"
]
