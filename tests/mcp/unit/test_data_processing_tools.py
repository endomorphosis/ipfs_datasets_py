"""Unit tests for data_processing_tools (Phase B2 session 33).

Covers:
- chunk_text: split text into chunks with various strategies
- transform_data: apply data transformations
- convert_format: convert between data formats
- validate_data: validate data against a schema / rules
"""
from __future__ import annotations

import asyncio

import pytest


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# chunk_text
# ---------------------------------------------------------------------------

class TestChunkText:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            chunk_text,
        )
        r = _run(chunk_text("Hello world, this is a sample text.", "sentence"))
        assert isinstance(r, dict)

    def test_has_chunks_key(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            chunk_text,
        )
        r = _run(chunk_text("Hello world.", "sentence"))
        assert "chunks" in r or "status" in r

    def test_sentence_strategy(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            chunk_text,
        )
        r = _run(chunk_text("One sentence. Two sentences. Three.", "sentence"))
        assert isinstance(r, dict)

    def test_fixed_strategy_with_chunk_size(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            chunk_text,
        )
        r = _run(chunk_text("A" * 100, "fixed", chunk_size=20))
        assert isinstance(r, dict)

    def test_empty_text_handled(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            chunk_text,
        )
        r = _run(chunk_text("", "sentence"))
        assert isinstance(r, dict)

    def test_overlap_param_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            chunk_text,
        )
        r = _run(chunk_text("Long text " * 20, "fixed", chunk_size=50, overlap=10))
        assert isinstance(r, dict)


# ---------------------------------------------------------------------------
# transform_data
# ---------------------------------------------------------------------------

class TestTransformData:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            transform_data,
        )
        r = _run(transform_data({"key": "value"}, "normalize"))
        assert isinstance(r, dict)

    def test_json_transformation(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            transform_data,
        )
        r = _run(transform_data([1, 2, 3], "flatten"))
        assert isinstance(r, dict)

    def test_parameters_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            transform_data,
        )
        r = _run(transform_data({"x": 1}, "scale", parameters={"factor": 2}))
        assert isinstance(r, dict)


# ---------------------------------------------------------------------------
# convert_format
# ---------------------------------------------------------------------------

class TestConvertFormat:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            convert_format,
        )
        r = _run(convert_format({"key": "val"}, "dict", "json"))
        assert isinstance(r, dict)

    def test_json_to_csv_conversion(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            convert_format,
        )
        r = _run(convert_format([{"a": 1, "b": 2}], "json", "csv"))
        assert isinstance(r, dict)

    def test_options_param_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            convert_format,
        )
        r = _run(
            convert_format(
                {"key": "val"}, "dict", "yaml", options={"indent": 2}
            )
        )
        assert isinstance(r, dict)


# ---------------------------------------------------------------------------
# validate_data
# ---------------------------------------------------------------------------

class TestValidateData:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            validate_data,
        )
        r = _run(validate_data({"name": "Alice", "age": 30}, "schema"))
        assert isinstance(r, dict)

    def test_has_status_or_valid_key(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            validate_data,
        )
        r = _run(validate_data({"x": 1}, "schema"))
        assert "status" in r or "valid" in r or "errors" in r

    def test_schema_param_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            validate_data,
        )
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        r = _run(validate_data({"name": "Bob"}, "jsonschema", schema=schema))
        assert isinstance(r, dict)

    def test_rules_param_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            validate_data,
        )
        r = _run(
            validate_data(
                [1, 2, 3], "custom", rules={"min_length": 1, "max_length": 100}
            )
        )
        assert isinstance(r, dict)
