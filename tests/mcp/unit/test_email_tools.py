"""Tests for email_tools tool category."""
import asyncio
import pytest
from unittest.mock import patch, MagicMock


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestEmailTestConnection:
    """Tests for email_test_connection()."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.email_tools.email_connect import email_test_connection
        result = _run(email_test_connection(server=None))
        assert isinstance(result, dict)

    def test_no_credentials_returns_error_not_raise(self):
        """Missing credentials should return an error dict, not raise."""
        from ipfs_datasets_py.mcp_server.tools.email_tools.email_connect import email_test_connection
        result = _run(email_test_connection(server=None, username=None, password=None))
        assert isinstance(result, dict)

    def test_invalid_server_returns_error(self):
        from ipfs_datasets_py.mcp_server.tools.email_tools.email_connect import email_test_connection
        result = _run(email_test_connection(
            server="invalid.host.x99", port=993, username="u", password="p"
        ))
        assert isinstance(result, dict)


class TestEmailListFolders:
    """Tests for email_list_folders()."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.email_tools.email_connect import email_list_folders
        result = _run(email_list_folders())
        assert isinstance(result, dict)


class TestEmailParseEml:
    """Tests for email_parse_eml() — does not require network."""

    def test_returns_error_dict_on_nonexistent_path(self):
        """Providing a nonexistent file path should return an error, not raise."""
        from ipfs_datasets_py.mcp_server.tools.email_tools.email_export import email_parse_eml
        result = _run(email_parse_eml(file_path="/tmp/nonexistent_zzz.eml"))
        assert isinstance(result, dict)

    def test_status_key_present(self):
        from ipfs_datasets_py.mcp_server.tools.email_tools.email_export import email_parse_eml
        result = _run(email_parse_eml(file_path="/tmp/nonexistent_zzz.eml"))
        assert "status" in result or "error" in result

    def test_include_attachments_param(self):
        from ipfs_datasets_py.mcp_server.tools.email_tools.email_export import email_parse_eml
        result = _run(email_parse_eml(file_path="/tmp/nonexistent_zzz.eml", include_attachments=False))
        assert isinstance(result, dict)


class TestEmailFetchEmails:
    """Tests for email_fetch_emails()."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.email_tools.email_export import email_fetch_emails
        result = _run(email_fetch_emails(server=None, limit=1))
        assert isinstance(result, dict)


class TestEmailToolsImports:
    """Smoke-test that email_tools package is importable."""

    def test_email_connect_importable(self):
        from ipfs_datasets_py.mcp_server.tools.email_tools import email_connect  # noqa

    def test_email_export_importable(self):
        from ipfs_datasets_py.mcp_server.tools.email_tools import email_export  # noqa
