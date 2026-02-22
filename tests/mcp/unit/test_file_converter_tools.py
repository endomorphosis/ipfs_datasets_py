"""
Tests for file_converter_tools tool category (Phase B2 coverage audit).

Tests cover:
- convert_file_tool: convert a file or URL to text
- batch_convert_tool: convert multiple files concurrently
- file_info_tool: get format metadata about a file
- extract_archive_tool: extract archive contents
- generate_summary_tool: generate a text summary from a file
- download_url_tool: download a file from a URL

All tests use non-existent paths or deliberately invalid inputs so that
the tools degrade gracefully (error dict) without any real I/O.

Note: These tests require numpy to be installed.  If the dependency is
missing the entire test module is skipped automatically.
"""

import pytest

# Guard: the file_converter module requires numpy; skip all tests if unavailable.
numpy = pytest.importorskip("numpy", reason="numpy required for file_converter_tools")

try:
    from ipfs_datasets_py.mcp_server.tools.file_converter_tools.convert_file import convert_file_tool
    from ipfs_datasets_py.mcp_server.tools.file_converter_tools.batch_convert import batch_convert_tool
    from ipfs_datasets_py.mcp_server.tools.file_converter_tools.file_info import file_info_tool
    from ipfs_datasets_py.mcp_server.tools.file_converter_tools.extract_archive import extract_archive_tool
    from ipfs_datasets_py.mcp_server.tools.file_converter_tools.generate_summary import generate_summary_tool
    from ipfs_datasets_py.mcp_server.tools.file_converter_tools.download_url import download_url_tool
    _IMPORT_OK = True
except Exception:
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(
    not _IMPORT_OK,
    reason="file_converter_tools dependencies not available",
)


class TestConvertFileTool:
    """Tests for convert_file_tool."""

    @pytest.mark.asyncio
    async def test_convert_nonexistent_file_returns_dict(self):
        """
        GIVEN file_converter_tools.convert_file_tool
        WHEN called with a path that doesn't exist
        THEN the result is a dict (graceful error)
        """
        from ipfs_datasets_py.mcp_server.tools.file_converter_tools.convert_file import (
            convert_file_tool,
        )
        result = await convert_file_tool(input_path="/tmp/does_not_exist_b2.pdf")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_convert_with_backend_returns_dict(self):
        """
        GIVEN file_converter_tools.convert_file_tool
        WHEN called with an explicit backend
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.file_converter_tools.convert_file import (
            convert_file_tool,
        )
        result = await convert_file_tool(
            input_path="/tmp/does_not_exist_b2.docx",
            backend="native",
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_convert_with_json_output_format_returns_dict(self):
        """
        GIVEN file_converter_tools.convert_file_tool
        WHEN called with output_format='json'
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.file_converter_tools.convert_file import (
            convert_file_tool,
        )
        result = await convert_file_tool(
            input_path="/tmp/does_not_exist_b2.txt",
            output_format="json",
        )
        assert isinstance(result, dict)


class TestBatchConvertTool:
    """Tests for batch_convert_tool."""

    @pytest.mark.asyncio
    async def test_batch_empty_list_returns_dict(self):
        """
        GIVEN file_converter_tools.batch_convert_tool
        WHEN called with an empty list
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.file_converter_tools.batch_convert import (
            batch_convert_tool,
        )
        result = await batch_convert_tool(input_paths=[])
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_batch_nonexistent_files_returns_dict(self):
        """
        GIVEN file_converter_tools.batch_convert_tool
        WHEN called with paths that don't exist
        THEN the result is a dict (graceful errors per file)
        """
        from ipfs_datasets_py.mcp_server.tools.file_converter_tools.batch_convert import (
            batch_convert_tool,
        )
        result = await batch_convert_tool(
            input_paths=["/tmp/no_a.pdf", "/tmp/no_b.docx"],
            max_concurrent=2,
        )
        assert isinstance(result, dict)


class TestFileInfoTool:
    """Tests for file_info_tool."""

    @pytest.mark.asyncio
    async def test_file_info_nonexistent_returns_dict(self):
        """
        GIVEN file_converter_tools.file_info_tool
        WHEN called with a path that doesn't exist
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.file_converter_tools.file_info import (
            file_info_tool,
        )
        result = await file_info_tool(input_path="/tmp/does_not_exist_b2_info.dat")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_file_info_with_url_string_returns_dict(self):
        """
        GIVEN file_converter_tools.file_info_tool
        WHEN called with a URL string
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.file_converter_tools.file_info import (
            file_info_tool,
        )
        result = await file_info_tool(input_path="https://example.com/test.pdf")
        assert isinstance(result, dict)


class TestExtractArchiveTool:
    """Tests for extract_archive_tool."""

    @pytest.mark.asyncio
    async def test_extract_nonexistent_archive_returns_dict(self):
        """
        GIVEN file_converter_tools.extract_archive_tool
        WHEN called with an archive that doesn't exist
        THEN the result is a dict (graceful error)
        """
        from ipfs_datasets_py.mcp_server.tools.file_converter_tools.extract_archive import (
            extract_archive_tool,
        )
        result = await extract_archive_tool(archive_path="/tmp/no_archive_b2.zip")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_extract_with_max_depth_returns_dict(self):
        """
        GIVEN file_converter_tools.extract_archive_tool
        WHEN called with max_depth=2
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.file_converter_tools.extract_archive import (
            extract_archive_tool,
        )
        result = await extract_archive_tool(
            archive_path="/tmp/no_archive_b2.tar.gz",
            max_depth=2,
            recursive=False,
        )
        assert isinstance(result, dict)


class TestGenerateSummaryTool:
    """Tests for generate_summary_tool."""

    @pytest.mark.asyncio
    async def test_summary_nonexistent_file_returns_dict(self):
        """
        GIVEN file_converter_tools.generate_summary_tool
        WHEN called with a path that doesn't exist
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.file_converter_tools.generate_summary import (
            generate_summary_tool,
        )
        result = await generate_summary_tool(input_path="/tmp/no_summary_b2.pdf")
        assert isinstance(result, dict)


class TestDownloadUrlTool:
    """Tests for download_url_tool."""

    @pytest.mark.asyncio
    async def test_download_invalid_url_returns_dict(self):
        """
        GIVEN file_converter_tools.download_url_tool
        WHEN called with an unreachable URL
        THEN the result is a dict (graceful error; no network required)
        """
        from ipfs_datasets_py.mcp_server.tools.file_converter_tools.download_url import (
            download_url_tool,
        )
        # Use a clearly invalid/unreachable URL so the test doesn't make real requests
        result = await download_url_tool(
            url="http://127.0.0.1:19999/does_not_exist_b2.pdf",
            timeout=1,
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_download_non_http_url_returns_dict(self):
        """
        GIVEN file_converter_tools.download_url_tool
        WHEN called with a non-HTTP URL scheme
        THEN the result is a dict (graceful error)
        """
        from ipfs_datasets_py.mcp_server.tools.file_converter_tools.download_url import (
            download_url_tool,
        )
        result = await download_url_tool(url="ftp://example.com/file.dat")
        assert isinstance(result, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
