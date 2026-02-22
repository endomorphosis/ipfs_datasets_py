"""
Tests for ipfs_tools tool category.

Tests cover:
- pin_to_ipfs: pin content to IPFS node
- get_from_ipfs: retrieve content by CID
"""
import pytest

from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs
from ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs import get_from_ipfs


class TestPinToIPFS:
    """Tests for pin_to_ipfs tool function."""

    @pytest.mark.asyncio
    async def test_pin_string_content_returns_dict(self):
        """
        GIVEN the ipfs_tools module
        WHEN pin_to_ipfs is called with a string content source
        THEN the result must be a dict (success or graceful error)
        """
        result = await pin_to_ipfs(content_source="/tmp/nonexistent_test_file.txt")
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_pin_dict_content_returns_dict(self):
        """
        GIVEN the ipfs_tools module
        WHEN pin_to_ipfs is called with a dict content source
        THEN the result must be a dict
        """
        result = await pin_to_ipfs(
            content_source={"data": "hello ipfs", "type": "test"},
            recursive=False,
        )
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_pin_with_hash_algo_returns_dict(self):
        """
        GIVEN the ipfs_tools module
        WHEN pin_to_ipfs is called with a custom hash algorithm
        THEN the result must be a dict
        """
        result = await pin_to_ipfs(
            content_source={"data": "test"},
            hash_algo="sha2-256",
        )
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_pin_with_wrap_directory_returns_dict(self):
        """
        GIVEN the ipfs_tools module
        WHEN pin_to_ipfs is called with wrap_with_directory=True
        THEN the result must be a dict
        """
        result = await pin_to_ipfs(
            content_source={"data": "test"},
            wrap_with_directory=True,
        )
        assert result is not None
        assert isinstance(result, dict)


class TestGetFromIPFS:
    """Tests for get_from_ipfs tool function."""

    @pytest.mark.asyncio
    async def test_get_invalid_cid_returns_dict(self):
        """
        GIVEN the ipfs_tools module
        WHEN get_from_ipfs is called with an invalid CID
        THEN the result must be a dict (error response, not exception)
        """
        result = await get_from_ipfs(cid="QmInvalidCIDForTesting12345", timeout_seconds=5)
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_with_gateway_returns_dict(self):
        """
        GIVEN the ipfs_tools module
        WHEN get_from_ipfs is called with a custom gateway
        THEN the result must be a dict
        """
        result = await get_from_ipfs(
            cid="QmInvalidCIDForTesting12345",
            gateway="https://ipfs.io",
            timeout_seconds=5,
        )
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_with_output_path_returns_dict(self, tmp_path):
        """
        GIVEN the ipfs_tools module
        WHEN get_from_ipfs is called with an output path
        THEN the result must be a dict
        """
        out = str(tmp_path / "output")
        result = await get_from_ipfs(
            cid="QmInvalidCIDForTesting12345",
            output_path=out,
            timeout_seconds=5,
        )
        assert result is not None
        assert isinstance(result, dict)
