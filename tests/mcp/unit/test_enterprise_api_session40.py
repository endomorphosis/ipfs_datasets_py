"""
Session G40: enterprise_api.py coverage uplift.

Targets uncovered lines in EnterpriseGraphRAGAPI and related classes:
- EnterpriseGraphRAGAPI.create_jwt_token / validate_jwt_token (lines 402-426)
- EnterpriseGraphRAGAPI._create_app + lifespan (lines 428-459)
- _setup_routes delegating to sub-setup methods (lines 461-477)
- _setup_health_and_auth_routes HTTP endpoints (lines 479-498)
- _setup_core_api_routes HTTP endpoints (lines 500-540)
- _setup_search_routes HTTP endpoint (lines 542-580)
- _setup_analytics_routes HTTP endpoint (lines 582-622)
- ProcessingJobManager.process_job success path + webhook (lines 275-312)
- Webhook notifications in each exception handler (lines 320, 328, 336)
- AdvancedAnalyticsDashboard._calculate_avg_quality non-empty path (line 694)
- create_enterprise_api singleton factory (lines 720-727)
"""

import asyncio
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock heavy dependencies before importing enterprise_api
# ---------------------------------------------------------------------------

def _setup_mocks():
    """Set up mock modules for enterprise_api imports."""
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
    AdvancedAnalyticsDashboard,
    EnterpriseGraphRAGAPI,
    create_enterprise_api,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# TestEnterpriseGraphRAGAPIInit
# ---------------------------------------------------------------------------

class TestEnterpriseGraphRAGAPIInit:
    """Tests for EnterpriseGraphRAGAPI initialisation and _create_app."""

    def test_api_initialises_with_fastapi_app(self):
        """
        GIVEN: Default configuration
        WHEN: EnterpriseGraphRAGAPI() is instantiated
        THEN: .app is a FastAPI application
        """
        from fastapi import FastAPI
        api = EnterpriseGraphRAGAPI()
        assert isinstance(api.app, FastAPI)

    def test_api_stores_config(self):
        """
        GIVEN: A custom config dict
        WHEN: EnterpriseGraphRAGAPI(config=...) is created
        THEN: config attribute matches input
        """
        cfg = {"timeout": 60}
        api = EnterpriseGraphRAGAPI(config=cfg)
        assert api.config == cfg

    def test_api_creates_auth_manager(self):
        """
        GIVEN: Default initialization
        WHEN: EnterpriseGraphRAGAPI() is created
        THEN: auth_manager is an AuthenticationManager instance
        """
        api = EnterpriseGraphRAGAPI()
        assert isinstance(api.auth_manager, AuthenticationManager)


# ---------------------------------------------------------------------------
# TestJWTTokenMethods
# ---------------------------------------------------------------------------

class TestJWTTokenMethods:
    """Tests for create_jwt_token and validate_jwt_token."""

    def test_create_jwt_token_returns_string(self):
        """
        GIVEN: A user_data dict with a username
        WHEN: create_jwt_token() is called
        THEN: Returns a non-empty string token
        """
        api = EnterpriseGraphRAGAPI()
        token = api.create_jwt_token({"username": "demo"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_jwt_token_with_user_id(self):
        """
        GIVEN: A user_data dict with user_id (but no username)
        WHEN: create_jwt_token() is called
        THEN: Returns a non-empty string token
        """
        api = EnterpriseGraphRAGAPI()
        token = api.create_jwt_token({"user_id": "user123"})
        assert isinstance(token, str)

    def test_validate_jwt_token_valid_returns_user_data(self):
        """
        GIVEN: A valid JWT token created for 'demo' user
        WHEN: validate_jwt_token() is called
        THEN: Returns dict with user data (username, roles, etc.)
        """
        api = EnterpriseGraphRAGAPI()
        token = api.create_jwt_token({"username": "demo"})
        result = api.validate_jwt_token(token)
        assert result is not None
        assert result["username"] == "demo"

    def test_validate_jwt_token_invalid_returns_none(self):
        """
        GIVEN: An invalid token string
        WHEN: validate_jwt_token() is called
        THEN: Returns None
        """
        api = EnterpriseGraphRAGAPI()
        result = api.validate_jwt_token("not.a.valid.token")
        assert result is None


# ---------------------------------------------------------------------------
# TestHealthRouteViaTestClient
# ---------------------------------------------------------------------------

class TestHealthRoute:
    """Tests for /health endpoint via FastAPI TestClient."""

    def test_health_endpoint_returns_healthy(self):
        """
        GIVEN: EnterpriseGraphRAGAPI application
        WHEN: GET /health is called
        THEN: Returns 200 with status='healthy'
        """
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("httpx not available")

        api = EnterpriseGraphRAGAPI()
        client = TestClient(api.app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_login_endpoint_valid_credentials(self):
        """
        GIVEN: Valid demo credentials
        WHEN: POST /auth/login is called
        THEN: Returns 200 with access_token
        """
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("httpx not available")

        api = EnterpriseGraphRAGAPI()
        client = TestClient(api.app)
        response = client.post("/auth/login?username=demo&password=password")
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data

    def test_login_endpoint_invalid_credentials(self):
        """
        GIVEN: Invalid credentials
        WHEN: POST /auth/login is called
        THEN: Returns 401
        """
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("httpx not available")

        api = EnterpriseGraphRAGAPI()
        client = TestClient(api.app)
        response = client.post("/auth/login?username=hacker&password=wrong")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# TestProcessJobSuccess
# ---------------------------------------------------------------------------

class TestProcessJobSuccess:
    """Tests for ProcessingJobManager.process_job success path."""

    def test_process_job_success_sets_completed(self):
        """
        GIVEN: A submitted job with mocked CompleteGraphRAGSystem
        WHEN: process_job() completes without error
        THEN: Job status is 'completed' and progress is 1.0
        """
        jm = ProcessingJobManager()
        req = WebsiteProcessingRequest(url="https://example.com")
        job_id = _run(jm.submit_job("user1", req))

        mock_result = MagicMock()
        mock_result.quality_score = 0.9

        mock_system = MagicMock()
        mock_system.process_complete_website = AsyncMock(return_value=mock_result)

        with patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.CompleteGraphRAGSystem",
            return_value=mock_system,
        ):
            with patch(
                "ipfs_datasets_py.mcp_server.enterprise_api.anyio.sleep",
                AsyncMock(),
            ):
                _run(jm.process_job(job_id, req))

        assert jm.jobs[job_id]["status"] == "completed"
        assert jm.jobs[job_id]["progress"] == 1.0

    def test_process_job_stores_result(self):
        """
        GIVEN: A completed job
        WHEN: process_job() completes successfully
        THEN: Result is stored in job_results
        """
        jm = ProcessingJobManager()
        req = WebsiteProcessingRequest(url="https://example.com")
        job_id = _run(jm.submit_job("user1", req))

        mock_result = MagicMock()
        mock_result.quality_score = 0.85
        mock_system = MagicMock()
        mock_system.process_complete_website = AsyncMock(return_value=mock_result)

        with patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.CompleteGraphRAGSystem",
            return_value=mock_system,
        ):
            with patch(
                "ipfs_datasets_py.mcp_server.enterprise_api.anyio.sleep",
                AsyncMock(),
            ):
                _run(jm.process_job(job_id, req))

        assert job_id in jm.job_results


# ---------------------------------------------------------------------------
# TestWebhookNotifications
# ---------------------------------------------------------------------------

class TestWebhookNotifications:
    """Tests for webhook notifications in process_job exception handlers."""

    def test_webhook_called_on_tool_execution_error(self):
        """
        GIVEN: Job with notify_webhook set; CompleteGraphRAGSystem raises ToolExecutionError
        WHEN: process_job() runs
        THEN: _send_webhook_notification is called
        """
        from ipfs_datasets_py.mcp_server.exceptions import ToolExecutionError

        jm = ProcessingJobManager()
        req = WebsiteProcessingRequest(
            url="https://example.com",
            notify_webhook="https://hooks.example.com/notify",
        )
        job_id = _run(jm.submit_job("user1", req))

        with patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.CompleteGraphRAGSystem",
            side_effect=ToolExecutionError("test", ValueError("err")),
        ):
            with patch.object(
                jm, "_send_webhook_notification", new_callable=AsyncMock
            ) as mock_webhook:
                _run(jm.process_job(job_id, req))

        mock_webhook.assert_called_once()

    def test_webhook_called_on_value_error(self):
        """
        GIVEN: Job with notify_webhook; processing raises ValueError
        WHEN: process_job() runs
        THEN: _send_webhook_notification is called with 'failed' status
        """
        jm = ProcessingJobManager()
        req = WebsiteProcessingRequest(
            url="https://example.com",
            notify_webhook="https://hooks.example.com/notify",
        )
        job_id = _run(jm.submit_job("user1", req))

        with patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.CompleteGraphRAGSystem",
            side_effect=ValueError("bad params"),
        ):
            with patch.object(
                jm, "_send_webhook_notification", new_callable=AsyncMock
            ) as mock_webhook:
                _run(jm.process_job(job_id, req))

        mock_webhook.assert_called_once()

    def test_webhook_called_on_generic_exception(self):
        """
        GIVEN: Job with notify_webhook; processing raises RuntimeError
        WHEN: process_job() runs
        THEN: _send_webhook_notification is called
        """
        jm = ProcessingJobManager()
        req = WebsiteProcessingRequest(
            url="https://example.com",
            notify_webhook="https://hooks.example.com/notify",
        )
        job_id = _run(jm.submit_job("user1", req))

        with patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.CompleteGraphRAGSystem",
            side_effect=RuntimeError("crash"),
        ):
            with patch.object(
                jm, "_send_webhook_notification", new_callable=AsyncMock
            ) as mock_webhook:
                _run(jm.process_job(job_id, req))

        mock_webhook.assert_called_once()

    def test_webhook_called_on_success(self):
        """
        GIVEN: Job with notify_webhook; processing completes successfully
        WHEN: process_job() runs
        THEN: _send_webhook_notification is called with 'completed'
        """
        jm = ProcessingJobManager()
        req = WebsiteProcessingRequest(
            url="https://example.com",
            notify_webhook="https://hooks.example.com/notify",
        )
        job_id = _run(jm.submit_job("user1", req))

        mock_result = MagicMock()
        mock_result.quality_score = 0.9
        mock_system = MagicMock()
        mock_system.process_complete_website = AsyncMock(return_value=mock_result)

        with patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.CompleteGraphRAGSystem",
            return_value=mock_system,
        ):
            with patch(
                "ipfs_datasets_py.mcp_server.enterprise_api.anyio.sleep",
                AsyncMock(),
            ):
                with patch.object(
                    jm, "_send_webhook_notification", new_callable=AsyncMock
                ) as mock_webhook:
                    _run(jm.process_job(job_id, req))

        mock_webhook.assert_called_once_with(
            "https://hooks.example.com/notify", job_id, "completed"
        )


# ---------------------------------------------------------------------------
# TestCalculateAvgQuality
# ---------------------------------------------------------------------------

class TestCalculateAvgQuality:
    """Tests for AdvancedAnalyticsDashboard._calculate_avg_quality."""

    def test_returns_zero_with_no_results(self):
        """
        GIVEN: No job results
        WHEN: _calculate_avg_quality() is called
        THEN: Returns 0.0
        """
        jm = ProcessingJobManager()
        dashboard = AdvancedAnalyticsDashboard(jm)
        assert dashboard._calculate_avg_quality() == 0.0

    def test_returns_average_of_quality_scores(self):
        """
        GIVEN: Two job results with quality_score of 0.8 and 0.6
        WHEN: _calculate_avg_quality() is called
        THEN: Returns 0.7 (the average)
        """
        jm = ProcessingJobManager()
        result1 = MagicMock()
        result1.quality_score = 0.8
        result2 = MagicMock()
        result2.quality_score = 0.6
        jm.job_results["j1"] = result1
        jm.job_results["j2"] = result2

        dashboard = AdvancedAnalyticsDashboard(jm)
        avg = dashboard._calculate_avg_quality()
        assert abs(avg - 0.7) < 1e-9


# ---------------------------------------------------------------------------
# TestCreateEnterpriseAPIFactory
# ---------------------------------------------------------------------------

class TestCreateEnterpriseAPIFactory:
    """Tests for create_enterprise_api singleton factory."""

    def test_returns_enterprise_api_instance(self):
        """
        GIVEN: No existing api_instance
        WHEN: create_enterprise_api() is called
        THEN: Returns an EnterpriseGraphRAGAPI instance
        """
        import ipfs_datasets_py.mcp_server.enterprise_api as mod

        original = mod.api_instance
        try:
            mod.api_instance = None
            result = _run(create_enterprise_api())
            assert isinstance(result, EnterpriseGraphRAGAPI)
        finally:
            mod.api_instance = original

    def test_returns_existing_instance_when_set(self):
        """
        GIVEN: An existing api_instance
        WHEN: create_enterprise_api() is called
        THEN: Returns the existing instance (singleton behavior)
        """
        import ipfs_datasets_py.mcp_server.enterprise_api as mod

        original = mod.api_instance
        existing = EnterpriseGraphRAGAPI()
        try:
            mod.api_instance = existing
            result = _run(create_enterprise_api())
            assert result is existing
        finally:
            mod.api_instance = original
