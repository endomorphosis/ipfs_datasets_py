"""Unit tests for documentation_generator tool."""

import tempfile

from ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator import (
    documentation_generator,
)


def test_documentation_generator_default_format():
    """Ensure default format_type is used when format is unset."""
    with tempfile.TemporaryDirectory() as temp_dir:
        result = documentation_generator(
            input_path=".",
            output_path=temp_dir,
        )

    assert result["success"] is True
    assert result["result"]["format_type"] == "markdown"
    assert result["metadata"]["format_type"] == "markdown"


def test_documentation_generator_format_alias_overrides():
    """Ensure format alias overrides format_type."""
    with tempfile.TemporaryDirectory() as temp_dir:
        result = documentation_generator(
            input_path=".",
            output_path=temp_dir,
            format_type="markdown",
            format="html",
            include_private=False,
        )

    assert result["success"] is True
    assert result["result"]["format_type"] == "html"
    assert result["metadata"]["format_type"] == "html"
    assert result["metadata"]["include_private"] is False
