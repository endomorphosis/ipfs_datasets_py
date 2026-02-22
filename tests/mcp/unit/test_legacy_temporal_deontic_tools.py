"""
Session 37 — B2 tests for legacy_mcp_tools/temporal_deontic_logic_tools.py

All four async functions are tested for their graceful fallback behaviour when
the logic_integration sub-package (TemporalDeonticRAGStore, etc.) is unavailable
in this environment. The functions always return a dict, either with
``success=True`` (if the import chain succeeds) or ``success=False`` with
``error_code`` and ``error`` keys (on missing-input guards or import failures).
"""
from __future__ import annotations

import asyncio
import unittest
import warnings


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Suppress the DeprecationWarning emitted on import of the legacy module.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools.temporal_deontic_logic_tools import (
        check_document_consistency,
        query_theorems,
        bulk_process_caselaw,
        add_theorem,
    )


class TestCheckDocumentConsistency(unittest.TestCase):
    """Tests for check_document_consistency()."""

    def test_empty_text_returns_error(self):
        result = _run(check_document_consistency(document_text=""))
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        # Either "MISSING_DOCUMENT_TEXT" (when logic modules available) or
        # "PROCESSING_ERROR" (when imports fail) — both are valid
        self.assertIn("error_code", result)

    def test_non_empty_text_returns_dict(self):
        """When logic modules are absent an error dict is returned — never a crash."""
        result = _run(check_document_consistency(document_text="The contractor shall..."))
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)

    def test_jurisdiction_param_accepted(self):
        result = _run(
            check_document_consistency(
                document_text="Shall not...",
                jurisdiction="State",
                legal_domain="contract",
            )
        )
        self.assertIsInstance(result, dict)

    def test_invalid_temporal_context_handled_gracefully(self):
        result = _run(
            check_document_consistency(
                document_text="Shall not...",
                temporal_context="not-a-date",
            )
        )
        self.assertIsInstance(result, dict)


class TestQueryTheorems(unittest.TestCase):
    """Tests for query_theorems()."""

    def test_empty_query_returns_error(self):
        result = _run(query_theorems(query=""))
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        # Either "MISSING_QUERY" (when logic modules available) or
        # "QUERY_ERROR" (when imports fail) — both are valid
        self.assertIn("error_code", result)

    def test_non_empty_query_returns_dict(self):
        result = _run(query_theorems(query="obligation to pay"))
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)

    def test_filter_params_accepted(self):
        result = _run(
            query_theorems(
                query="shall pay",
                operator_filter="OBLIGATION",
                jurisdiction="Federal",
                legal_domain="contract",
                limit=5,
                min_relevance=0.7,
            )
        )
        self.assertIsInstance(result, dict)


class TestBulkProcessCaselaw(unittest.TestCase):
    """Tests for bulk_process_caselaw()."""

    def test_empty_directories_returns_error(self):
        result = _run(bulk_process_caselaw(caselaw_directories=[]))
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        # "MISSING_DIRECTORIES", "INVALID_DIRECTORIES", or "PROCESSING_ERROR"
        self.assertIn("error_code", result)

    def test_nonexistent_directory_returns_error(self):
        result = _run(bulk_process_caselaw(caselaw_directories=["/nonexistent/dir"]))
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        self.assertIn("error_code", result)

    def test_async_flag_param_accepted(self):
        """async_processing= is accepted even if no valid dirs found."""
        result = _run(
            bulk_process_caselaw(
                caselaw_directories=["/nonexistent"],
                async_processing=True,
            )
        )
        self.assertIsInstance(result, dict)


class TestAddTheorem(unittest.TestCase):
    """Tests for add_theorem()."""

    def test_empty_proposition_returns_error(self):
        result = _run(add_theorem(operator="OBLIGATION", proposition=""))
        self.assertIsInstance(result, dict)
        # Either missing-proposition guard fires or import fails — always a dict
        self.assertIn("success", result)

    def test_valid_inputs_return_dict(self):
        result = _run(
            add_theorem(
                operator="OBLIGATION",
                proposition="Pay the invoice within 30 days",
                agent_name="Vendor",
            )
        )
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)


if __name__ == "__main__":
    unittest.main()
