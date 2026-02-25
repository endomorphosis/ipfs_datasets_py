"""
Coverage-boosting tests for enterprise_api.py targeting lines not yet
covered in existing test sessions (40, 68, 73).

Target: push enterprise_api.py from 77% → 80%+

Uncovered areas addressed:
  - Lines 176–177 : revoke_token() success path
  - Line 188      : is_token_revoked() returning True
  - Lines 370, 378, 386 : webhook calls in process_job exception handlers
  - Lines 828–843 : create_enterprise_api() singleton lazy init
"""

import sys
import pytest
import asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock


# ---------------------------------------------------------------------------
# Setup mocks for heavy dependencies before any import
# ---------------------------------------------------------------------------

def _setup_mocks():
    mock_graphrag = MagicMock()
    mock_graphrag.CompleteGraphRAGSystem = MagicMock()
    mock_graphrag.CompleteProcessingConfiguration = MagicMock()
    mock_graphrag.CompleteProcessingResult = MagicMock()

    sys.modules.setdefault(
        "ipfs_datasets_py.processors.graphrag.complete_advanced_graphrag",
        mock_graphrag,
    )
    sys.modules.setdefault("ipfs_datasets_py.processors", MagicMock())
    sys.modules.setdefault("ipfs_datasets_py.processors.graphrag", MagicMock())


_setup_mocks()

from ipfs_datasets_py.mcp_server.enterprise_api import (
    AuthenticationManager,
    ProcessingJobManager,
    WebsiteProcessingRequest,
    EnterpriseGraphRAGAPI,
)
from ipfs_datasets_py.mcp_server.exceptions import ToolExecutionError


# ---------------------------------------------------------------------------
# AuthenticationManager — revoke_token and is_token_revoked
# ---------------------------------------------------------------------------

class TestRevokeToken:
    """revoke_token() adds the token to the revocation set."""

    def setup_method(self):
        self.auth = AuthenticationManager(secret_key="test-secret-key")

    def test_revoke_valid_token_returns_true(self):
        """
        GIVEN: A valid JWT token
        WHEN: revoke_token() is called
        THEN: Returns True and adds token to _revoked_tokens
        """
        token = self.auth.create_access_token("alice")
        result = self.auth.revoke_token(token)
        assert result is True
        assert token in self.auth._revoked_tokens

    def test_revoke_invalid_token_returns_false(self):
        """
        GIVEN: A garbage string that is not a valid JWT
        WHEN: revoke_token() is called
        THEN: Returns False
        """
        result = self.auth.revoke_token("not.a.valid.jwt")
        assert result is False

    def test_is_token_revoked_returns_true_after_revoke(self):
        """
        GIVEN: A token that has been revoked
        WHEN: is_token_revoked() is called
        THEN: Returns True
        """
        token = self.auth.create_access_token("bob")
        self.auth.revoke_token(token)
        assert self.auth.is_token_revoked(token) is True

    @pytest.mark.asyncio
    async def test_authenticate_revoked_token_raises_http_exception(self):
        """
        GIVEN: A token that has been revoked
        WHEN: authenticate() is called with that token
        THEN: HTTPException 401 is raised with detail 'Token has been revoked'
        """
        from fastapi import HTTPException
        token = self.auth.create_access_token("alice")
        self.auth.revoke_token(token)
        with pytest.raises(HTTPException) as exc_info:
            await self.auth.authenticate(token)
        assert exc_info.value.status_code == 401
        assert "revoked" in exc_info.value.detail.lower()





# ---------------------------------------------------------------------------
# ProcessingJobManager.process_job — webhook paths in exception handlers
# ---------------------------------------------------------------------------

class TestProcessJobWebhookPaths:
    """process_job() sends webhook notifications in exception handler branches."""

    def _make_manager(self):
        return ProcessingJobManager()

    def _make_request(self, webhook_url: str) -> WebsiteProcessingRequest:
        return WebsiteProcessingRequest(url="https://example.com", notify_webhook=webhook_url)

    async def _submit_and_process_with_error(self, exc_to_raise, webhook_url="https://hook.example.com"):
        """Helper: submit a job, then run process_job with a mocked system that raises exc."""
        mgr = self._make_manager()
        req = self._make_request(webhook_url)
        job_id = await mgr.submit_job("user1", req)

        mock_system = MagicMock()
        mock_system.process_complete_website = AsyncMock(side_effect=exc_to_raise)

        send_mock = AsyncMock()

        with patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.CompleteGraphRAGSystem",
            return_value=mock_system,
        ), patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.CompleteProcessingConfiguration",
            return_value=MagicMock(),
        ), patch.object(mgr, "_send_webhook_notification", send_mock), patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.anyio.sleep",
            AsyncMock(),
        ):
            await mgr.process_job(job_id, req)

        return mgr, job_id, send_mock

    @pytest.mark.asyncio
    async def test_tool_execution_error_calls_webhook(self):
        """
        GIVEN: process_job raises ToolExecutionError with webhook configured
        WHEN: process_job() runs
        THEN: _send_webhook_notification is called with 'failed' status
        """
        mgr, job_id, send_mock = await self._submit_and_process_with_error(
            ToolExecutionError("test_tool", RuntimeError("test error"))
        )
        send_mock.assert_called_once_with("https://hook.example.com", job_id, "failed")
        assert mgr.jobs[job_id]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_value_error_calls_webhook(self):
        """
        GIVEN: process_job raises ValueError with webhook configured
        WHEN: process_job() runs
        THEN: _send_webhook_notification is called with 'failed' status
        """
        mgr, job_id, send_mock = await self._submit_and_process_with_error(
            ValueError("bad param")
        )
        send_mock.assert_called_once_with("https://hook.example.com", job_id, "failed")
        assert "Invalid parameters" in mgr.jobs[job_id]["error_message"]

    @pytest.mark.asyncio
    async def test_generic_exception_calls_webhook(self):
        """
        GIVEN: process_job raises a generic Exception with webhook configured
        WHEN: process_job() runs
        THEN: _send_webhook_notification is called with 'failed' status
        """
        mgr, job_id, send_mock = await self._submit_and_process_with_error(
            RuntimeError("unexpected failure")
        )
        send_mock.assert_called_once_with("https://hook.example.com", job_id, "failed")
        assert mgr.jobs[job_id]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_process_job_success_marks_completed(self):
        """
        GIVEN: process_job runs with a mocked GraphRAG system that succeeds
        WHEN: process_job() runs
        THEN: Job status is 'completed' and result is stored
        """
        mgr = self._make_manager()
        req = WebsiteProcessingRequest(url="https://example.com")
        job_id = await mgr.submit_job("user1", req)

        mock_result = MagicMock()
        mock_system = MagicMock()
        mock_system.process_complete_website = AsyncMock(return_value=mock_result)

        with patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.CompleteGraphRAGSystem",
            return_value=mock_system,
        ), patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.CompleteProcessingConfiguration",
            return_value=MagicMock(),
        ), patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.anyio.sleep",
            AsyncMock(),
        ):
            await mgr.process_job(job_id, req)

        assert mgr.jobs[job_id]["status"] == "completed"
        assert mgr.job_results[job_id] is mock_result

    @pytest.mark.asyncio
    async def test_tool_execution_error_no_webhook(self):
        """
        GIVEN: process_job raises ToolExecutionError but no webhook configured
        WHEN: process_job() runs
        THEN: _send_webhook_notification is NOT called
        """
        mgr = self._make_manager()
        req = WebsiteProcessingRequest(url="https://example.com")  # no webhook
        job_id = await mgr.submit_job("user1", req)

        mock_system = MagicMock()
        mock_system.process_complete_website = AsyncMock(
            side_effect=ToolExecutionError("no_webhook_tool", RuntimeError("no webhook"))
        )
        send_mock = AsyncMock()

        with patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.CompleteGraphRAGSystem",
            return_value=mock_system,
        ), patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.CompleteProcessingConfiguration",
            MagicMock(),
        ), patch.object(mgr, "_send_webhook_notification", send_mock), patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.anyio.sleep",
            AsyncMock(),
        ):
            await mgr.process_job(job_id, req)

        send_mock.assert_not_called()


# ---------------------------------------------------------------------------
# create_enterprise_api — singleton lazy init (lines 828–843)
# ---------------------------------------------------------------------------

class TestCreateEnterpriseAPISingleton:
    """create_enterprise_api() creates an instance on first call and caches it."""

    @pytest.mark.asyncio
    async def test_returns_enterprise_graphrag_api_instance(self):
        """
        GIVEN: api_instance is None
        WHEN: create_enterprise_api() is called
        THEN: Returns an EnterpriseGraphRAGAPI instance
        """
        import ipfs_datasets_py.mcp_server.enterprise_api as ea_mod
        from ipfs_datasets_py.mcp_server.enterprise_api import create_enterprise_api

        orig = ea_mod.api_instance
        try:
            ea_mod.api_instance = None
            result = await create_enterprise_api()
            assert isinstance(result, EnterpriseGraphRAGAPI)
        finally:
            ea_mod.api_instance = orig

    @pytest.mark.asyncio
    async def test_returns_same_instance_on_second_call(self):
        """
        GIVEN: api_instance is None
        WHEN: create_enterprise_api() is called twice
        THEN: Both calls return the same object
        """
        import ipfs_datasets_py.mcp_server.enterprise_api as ea_mod
        from ipfs_datasets_py.mcp_server.enterprise_api import create_enterprise_api

        orig = ea_mod.api_instance
        try:
            ea_mod.api_instance = None
            first = await create_enterprise_api()
            second = await create_enterprise_api()
            assert first is second
        finally:
            ea_mod.api_instance = orig

    @pytest.mark.asyncio
    async def test_does_not_replace_existing_instance(self):
        """
        GIVEN: api_instance is already set
        WHEN: create_enterprise_api() is called
        THEN: The existing instance is returned unchanged
        """
        import ipfs_datasets_py.mcp_server.enterprise_api as ea_mod
        from ipfs_datasets_py.mcp_server.enterprise_api import create_enterprise_api

        sentinel = MagicMock()
        orig = ea_mod.api_instance
        try:
            ea_mod.api_instance = sentinel
            result = await create_enterprise_api()
            assert result is sentinel
        finally:
            ea_mod.api_instance = orig


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
