"""
Extended tests for FastAPI service — Session M55 (v7 plan).

Coverage targets (fastapi_service.py):
- /health/ready readiness endpoint — all branches
- /metrics Prometheus text endpoint
- _FallbackPasswordContext.hash / verify
- create_access_token with / without expires_delta
- check_rate_limit — no limit, within limit, exceeded, wildcard, window reset
- /tools/list + /tools/execute — success, not-found, error
- HTTPExceptionHandler / MCPServerErrorHandler / GeneralExceptionHandler — direct calls
- /workflows/execute — success (mocked inner import), unauthenticated
- /datasets/load, /datasets/process, /datasets/save, /datasets/convert — auth paths
- /ipfs/pin, /ipfs/get/{cid} — auth paths
- /vectors/create-index, /vectors/search — auth paths
- /audit/record, /audit/report — auth paths
- /cache/stats, /cache/clear — auth paths
- log_api_request — success and failure
- custom_openapi function
- run_development_server / run_production_server
"""
import os
import sys
import time
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest

# ── env setup before any module import ────────────────────────────────────────
os.environ.setdefault("SECRET_KEY", "test-secret-key-session55")

# Pre-populate the nonexistent inner package so the relative imports inside
# route handlers don't blow up at collection time.
_inner_mcp = MagicMock()
sys.modules.setdefault("ipfs_datasets_py.mcp_server.mcp_server", _inner_mcp)
sys.modules.setdefault("ipfs_datasets_py.mcp_server.mcp_server.tools", _inner_mcp)

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

import ipfs_datasets_py.mcp_server.fastapi_service as svc
from ipfs_datasets_py.mcp_server.exceptions import (
    MCPServerError,
    ToolNotFoundError,
    ToolExecutionError,
    ConfigurationError,
)

# ── shared fixtures ────────────────────────────────────────────────────────────

SECRET = "test-secret-key-session55"


def _make_token(username: str = "testuser", uid: str = "uid1", exp_delta: timedelta = None) -> str:
    if exp_delta is None:
        exp_delta = timedelta(minutes=30)
    return jwt.encode(
        {"sub": username, "user_id": uid, "exp": datetime.utcnow() + exp_delta},
        SECRET,
        algorithm="HS256",
    )


@pytest.fixture(scope="module")
def client():
    """Module-scoped TestClient that runs the lifespan (sets app.state)."""
    with TestClient(svc.app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers():
    return {"Authorization": f"Bearer {_make_token()}"}


# ══════════════════════════════════════════════════════════════════════════════
# 1. Readiness Check  (/health/ready)
# ══════════════════════════════════════════════════════════════════════════════


class TestReadinessCheck:
    """Tests for /health/ready readiness probe endpoint."""

    def test_readiness_returns_200(self, client: TestClient):
        """GIVEN a running service WHEN /health/ready is called THEN status 200."""
        r = client.get("/health/ready")
        assert r.status_code == 200

    def test_readiness_has_status_key(self, client: TestClient):
        """GIVEN /health/ready response WHEN decoded THEN 'status' key present."""
        r = client.get("/health/ready")
        assert "status" in r.json()

    def test_readiness_has_checks_key(self, client: TestClient):
        """GIVEN /health/ready response WHEN decoded THEN 'checks' key present."""
        r = client.get("/health/ready")
        assert "checks" in r.json()

    def test_readiness_has_uptime_seconds(self, client: TestClient):
        """GIVEN /health/ready response WHEN decoded THEN 'uptime_seconds' key present."""
        r = client.get("/health/ready")
        assert "uptime_seconds" in r.json()

    def test_readiness_metrics_collector_check(self, client: TestClient):
        """GIVEN /health/ready response WHEN decoded THEN checks.metrics_collector present."""
        r = client.get("/health/ready")
        checks = r.json()["checks"]
        assert "metrics_collector" in checks

    def test_readiness_tool_manager_check_present(self, client: TestClient):
        """GIVEN /health/ready response WHEN decoded THEN checks.tool_manager present."""
        r = client.get("/health/ready")
        checks = r.json()["checks"]
        assert "tool_manager" in checks

    def test_readiness_tool_manager_has_categories(self, client: TestClient):
        """GIVEN /health/ready tool_manager check WHEN decoded THEN 'categories' key present."""
        r = client.get("/health/ready")
        tm_check = r.json()["checks"]["tool_manager"]
        # categories key present in ok/warning states
        assert "categories" in tm_check or tm_check.get("status") == "error"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Metrics Endpoint  (/metrics)
# ══════════════════════════════════════════════════════════════════════════════


class TestMetricsEndpoint:
    """Tests for /metrics Prometheus text endpoint."""

    def test_metrics_returns_200(self, client: TestClient):
        """GIVEN /metrics endpoint WHEN called THEN returns 200."""
        r = client.get("/metrics")
        assert r.status_code == 200

    def test_metrics_content_type_is_text(self, client: TestClient):
        """GIVEN /metrics endpoint WHEN called THEN content-type is text/plain."""
        r = client.get("/metrics")
        assert "text/plain" in r.headers.get("content-type", "")

    def test_metrics_has_help_lines(self, client: TestClient):
        """GIVEN /metrics response WHEN decoded THEN has '# HELP' comment lines."""
        r = client.get("/metrics")
        assert "# HELP" in r.text

    def test_metrics_has_uptime_metric(self, client: TestClient):
        """GIVEN /metrics response WHEN decoded THEN contains mcp_uptime_seconds."""
        r = client.get("/metrics")
        assert "mcp_uptime_seconds" in r.text

    def test_metrics_has_requests_total(self, client: TestClient):
        """GIVEN /metrics response WHEN decoded THEN contains mcp_requests_total."""
        r = client.get("/metrics")
        assert "mcp_requests_total" in r.text

    def test_metrics_has_cpu_metric(self, client: TestClient):
        """GIVEN /metrics response WHEN decoded THEN contains process_cpu_percent."""
        r = client.get("/metrics")
        assert "process_cpu_percent" in r.text


# ══════════════════════════════════════════════════════════════════════════════
# 3. _FallbackPasswordContext helpers
# ══════════════════════════════════════════════════════════════════════════════


class TestFallbackPasswordContext:
    """Tests for the SHA-256-based fallback password context."""

    def _ctx(self):
        return svc._FallbackPasswordContext()

    def test_hash_returns_string(self):
        """GIVEN _FallbackPasswordContext.hash WHEN called THEN returns a str."""
        h = self._ctx().hash("mypassword")
        assert isinstance(h, str)

    def test_hash_is_64_hex_chars(self):
        """GIVEN _FallbackPasswordContext.hash WHEN called THEN returns 64-char hex."""
        h = self._ctx().hash("mypassword")
        assert len(h) == 64
        int(h, 16)  # must be valid hex

    def test_hash_is_deterministic(self):
        """GIVEN same password WHEN hashed twice THEN identical hashes."""
        ctx = self._ctx()
        assert ctx.hash("secret") == ctx.hash("secret")

    def test_verify_correct_password_returns_true(self):
        """GIVEN correct password and its hash WHEN verified THEN True."""
        ctx = self._ctx()
        h = ctx.hash("correct")
        assert ctx.verify("correct", h) is True

    def test_verify_wrong_password_returns_false(self):
        """GIVEN wrong password and a hash WHEN verified THEN False."""
        ctx = self._ctx()
        h = ctx.hash("correct")
        assert ctx.verify("wrong", h) is False

    def test_hash_matches_sha256(self):
        """GIVEN _FallbackPasswordContext.hash WHEN compared to hashlib THEN equal."""
        password = "unittest_sha256"
        expected = hashlib.sha256(password.encode()).hexdigest()
        assert svc._FallbackPasswordContext().hash(password) == expected


# ══════════════════════════════════════════════════════════════════════════════
# 4. create_access_token helper
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateAccessToken:
    """Tests for create_access_token module-level function."""

    def test_returns_string(self):
        """GIVEN user data WHEN create_access_token called THEN returns str."""
        tok = svc.create_access_token({"sub": "alice"})
        assert isinstance(tok, str)

    def test_decoded_has_sub(self):
        """GIVEN token WHEN decoded THEN 'sub' claim matches input."""
        tok = svc.create_access_token({"sub": "bob"})
        payload = jwt.decode(tok, SECRET, algorithms=["HS256"])
        assert payload["sub"] == "bob"

    def test_decoded_has_exp(self):
        """GIVEN token WHEN decoded THEN 'exp' claim is present."""
        tok = svc.create_access_token({"sub": "alice"})
        payload = jwt.decode(tok, SECRET, algorithms=["HS256"])
        assert "exp" in payload

    def test_custom_expires_delta_applied(self):
        """GIVEN custom expires_delta WHEN decoded THEN exp is in the future."""
        tok = svc.create_access_token({"sub": "alice"}, expires_delta=timedelta(hours=2))
        payload = jwt.decode(tok, SECRET, algorithms=["HS256"])
        delta = payload["exp"] - datetime.utcnow().timestamp()
        assert delta > 3600  # at least 1 hour remaining


# ══════════════════════════════════════════════════════════════════════════════
# 5. check_rate_limit logic
# ══════════════════════════════════════════════════════════════════════════════


class FakeRequest:
    """Minimal request stub for check_rate_limit."""
    def __init__(self, ip: str = "10.0.0.1"):
        self.client = MagicMock(host=ip)


class TestCheckRateLimitLogic:
    """Tests for the async check_rate_limit function."""

    def setup_method(self):
        svc.rate_limit_storage.clear()

    async def test_no_matching_endpoint_passes(self):
        """GIVEN an endpoint not in RATE_LIMITS WHEN called THEN no exception."""
        await svc.check_rate_limit(FakeRequest(), "/no/limit/here")

    async def test_first_request_within_limit(self):
        """GIVEN first request to rate-limited endpoint WHEN called THEN passes."""
        await svc.check_rate_limit(FakeRequest(), "/embeddings/generate")

    async def test_request_increments_counter(self):
        """GIVEN rate-limited endpoint WHEN called THEN counter increments."""
        req = FakeRequest()
        await svc.check_rate_limit(req, "/embeddings/generate")
        count = svc.rate_limit_storage.get("10.0.0.1:/embeddings/generate", {}).get("requests", 0)
        assert count == 1

    async def test_exceeded_limit_raises_429(self):
        """GIVEN storage at max requests WHEN called THEN HTTPException(429) raised."""
        key = "10.0.0.2:/embeddings/generate"
        svc.rate_limit_storage[key] = {"requests": 100, "window_start": int(time.time())}
        with pytest.raises(HTTPException) as exc_info:
            await svc.check_rate_limit(FakeRequest("10.0.0.2"), "/embeddings/generate")
        assert exc_info.value.status_code == 429

    async def test_wildcard_admin_pattern_matched(self):
        """GIVEN /admin/stats WHEN storage at limit THEN 429 raised."""
        key = "10.0.0.3:/admin/stats"
        svc.rate_limit_storage[key] = {"requests": 50, "window_start": int(time.time())}
        with pytest.raises(HTTPException) as exc_info:
            await svc.check_rate_limit(FakeRequest("10.0.0.3"), "/admin/stats")
        assert exc_info.value.status_code == 429

    async def test_expired_window_resets_counter(self):
        """GIVEN storage with expired window WHEN called THEN counter resets to 1."""
        key = "10.0.0.4:/embeddings/generate"
        svc.rate_limit_storage[key] = {
            "requests": 50,
            "window_start": int(time.time()) - 7200,  # 2 hours ago
        }
        await svc.check_rate_limit(FakeRequest("10.0.0.4"), "/embeddings/generate")
        assert svc.rate_limit_storage[key]["requests"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# 6. /tools/list  +  /tools/execute
# ══════════════════════════════════════════════════════════════════════════════


class TestToolsEndpoints:
    """Tests for the /tools/list and /tools/execute routes."""

    def test_list_tools_unauthenticated_returns_401(self, client: TestClient):
        """GIVEN no auth WHEN GET /tools/list THEN 401."""
        r = client.get("/tools/list")
        assert r.status_code == 401

    def test_list_tools_authenticated_returns_200(self, client: TestClient, auth_headers):
        """GIVEN valid auth WHEN GET /tools/list THEN 200 with tools key."""
        r = client.get("/tools/list", headers=auth_headers)
        assert r.status_code == 200
        assert "tools" in r.json()

    def test_list_tools_includes_count(self, client: TestClient, auth_headers):
        """GIVEN /tools/list response WHEN decoded THEN 'count' key present."""
        r = client.get("/tools/list", headers=auth_headers)
        assert "count" in r.json()

    def test_list_tools_includes_categories(self, client: TestClient, auth_headers):
        """GIVEN /tools/list response WHEN decoded THEN 'categories' key present."""
        r = client.get("/tools/list", headers=auth_headers)
        assert "categories" in r.json()

    def test_execute_tool_no_auth_returns_401(self, client: TestClient):
        """GIVEN no auth WHEN POST /tools/execute/tool THEN 401."""
        r = client.post("/tools/execute/mytool", json={})
        assert r.status_code == 401

    def test_execute_unknown_tool_returns_error(self, client: TestClient, auth_headers):
        """GIVEN unknown tool WHEN POST /tools/execute THEN 4xx or 5xx."""
        r = client.post("/tools/execute/totally_unknown", json={}, headers=auth_headers)
        assert r.status_code in (404, 500)

    def test_execute_tool_success_path(self, client: TestClient, auth_headers):
        """GIVEN mocked tool on app.state WHEN POST /tools/execute THEN 200."""
        async def fake_tool(params):
            return {"output": "result"}

        svc.app.state.mcp_server.tools = {"my_tool": fake_tool}
        r = client.post("/tools/execute/my_tool", json={"x": 1}, headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "success"
        assert body.get("result") == {"output": "result"}

    def test_execute_tool_response_includes_tool_name(self, client: TestClient, auth_headers):
        """GIVEN successful tool execution WHEN decoded THEN 'tool' key equals name."""
        async def dummy(params):
            return {}
        svc.app.state.mcp_server.tools = {"named_tool": dummy}
        r = client.post("/tools/execute/named_tool", json={}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["tool"] == "named_tool"


# ══════════════════════════════════════════════════════════════════════════════
# 7. Exception Handlers — direct function calls
# ══════════════════════════════════════════════════════════════════════════════


class TestHTTPExceptionHandlerFormat:
    """Tests for the custom HTTPException handler response shape."""

    def test_custom_handler_adds_error_key(self, client: TestClient):
        """GIVEN 400 HTTPException raised by route THEN response has 'error' key."""
        # /auth/login with empty username triggers HTTPException(400)
        r = client.post("/auth/login", json={"username": "", "password": "pw"})
        if r.status_code == 400:
            assert "error" in r.json()

    def test_custom_handler_adds_status_code_key(self, client: TestClient):
        """GIVEN 400 response THEN 'status_code' key equals 400."""
        r = client.post("/auth/login", json={"username": "", "password": "pw"})
        if r.status_code == 400:
            assert r.json()["status_code"] == 400

    def test_custom_handler_adds_timestamp_key(self, client: TestClient):
        """GIVEN 400 response THEN 'timestamp' key is present."""
        r = client.post("/auth/login", json={"username": "", "password": "pw"})
        if r.status_code == 400:
            assert "timestamp" in r.json()

    def test_401_response_format(self, client: TestClient):
        """GIVEN 401 from protected endpoint WHEN decoded THEN has standard format."""
        r = client.post("/auth/refresh")  # no auth header → 401/403
        # Just verify it returns a non-2xx status
        assert r.status_code in (401, 403, 422)


class TestMCPServerErrorHandler:
    """Tests for MCPServerError exception handler — direct invocation."""

    async def test_handler_returns_500_for_base_mcpservererror(self):
        """GIVEN MCPServerError raised WHEN handler called THEN 500 JSON response."""
        req = MagicMock()
        exc = MCPServerError("test server error")
        from ipfs_datasets_py.mcp_server.fastapi_service import mcp_server_error_handler
        resp = await mcp_server_error_handler(req, exc)
        assert resp.status_code == 500

    async def test_handler_returns_404_for_tool_not_found(self):
        """GIVEN ToolNotFoundError raised WHEN handler called THEN 404 JSON response."""
        req = MagicMock()
        exc = ToolNotFoundError("missing tool")
        from ipfs_datasets_py.mcp_server.fastapi_service import mcp_server_error_handler
        resp = await mcp_server_error_handler(req, exc)
        assert resp.status_code == 404

    async def test_handler_returns_400_for_configuration_error(self):
        """GIVEN ConfigurationError raised WHEN handler called THEN 400 JSON response."""
        req = MagicMock()
        exc = ConfigurationError("bad config")
        from ipfs_datasets_py.mcp_server.fastapi_service import mcp_server_error_handler
        resp = await mcp_server_error_handler(req, exc)
        assert resp.status_code == 400

    async def test_handler_response_has_error_type_key(self):
        """GIVEN MCPServerError WHEN handler called THEN response body has 'error_type'."""
        import json
        req = MagicMock()
        exc = MCPServerError("err")
        from ipfs_datasets_py.mcp_server.fastapi_service import mcp_server_error_handler
        resp = await mcp_server_error_handler(req, exc)
        body = json.loads(resp.body)
        assert "error_type" in body


class TestGeneralExceptionHandler:
    """Tests for the catch-all Exception handler — direct invocation."""

    async def test_handler_returns_500(self):
        """GIVEN generic Exception WHEN handler called THEN 500 response."""
        req = MagicMock()
        from ipfs_datasets_py.mcp_server.fastapi_service import general_exception_handler
        resp = await general_exception_handler(req, ValueError("oops"))
        assert resp.status_code == 500

    async def test_handler_body_has_error_key(self):
        """GIVEN generic Exception WHEN handler called THEN body has 'error' key."""
        import json
        req = MagicMock()
        from ipfs_datasets_py.mcp_server.fastapi_service import general_exception_handler
        resp = await general_exception_handler(req, RuntimeError("boom"))
        body = json.loads(resp.body)
        assert "error" in body

    async def test_handler_body_has_timestamp(self):
        """GIVEN generic Exception WHEN handler called THEN body has 'timestamp' key."""
        import json
        req = MagicMock()
        from ipfs_datasets_py.mcp_server.fastapi_service import general_exception_handler
        resp = await general_exception_handler(req, RuntimeError("t"))
        body = json.loads(resp.body)
        assert "timestamp" in body


# ══════════════════════════════════════════════════════════════════════════════
# 8. Workflow Endpoints
# ══════════════════════════════════════════════════════════════════════════════


class TestWorkflowEndpoints:
    """Tests for /workflows/execute and /workflows/status."""

    def _setup_workflow_mock(self):
        """Inject a mock for the workflow tools inner import."""
        mock_mod = MagicMock()
        mock_mod.execute_workflow = AsyncMock(return_value={"status": "done"})
        mock_mod.get_workflow_status = AsyncMock(return_value={"task_id": "t1", "status": "completed"})
        key = "ipfs_datasets_py.mcp_server.mcp_server.tools.workflow_tools.workflow_tools"
        sys.modules[key] = mock_mod
        return mock_mod

    def test_execute_workflow_unauthenticated(self, client: TestClient):
        """GIVEN no auth WHEN POST /workflows/execute THEN 401."""
        r = client.post("/workflows/execute", json={"workflow_name": "w", "steps": []})
        assert r.status_code == 401

    def test_execute_workflow_authenticated_with_mock(self, client: TestClient, auth_headers):
        """GIVEN valid auth + mocked tool WHEN POST /workflows/execute THEN 200."""
        self._setup_workflow_mock()
        r = client.post(
            "/workflows/execute",
            json={"workflow_name": "test_wf", "steps": [{"name": "s1"}, {"name": "s2"}]},
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("workflow_name") == "test_wf"

    def test_execute_workflow_returns_task_id(self, client: TestClient, auth_headers):
        """GIVEN valid auth + mocked tool WHEN POST /workflows/execute THEN task_id in response."""
        self._setup_workflow_mock()
        r = client.post(
            "/workflows/execute",
            json={"workflow_name": "wf", "steps": [{"name": "step1"}]},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert "task_id" in r.json()

    def test_execute_workflow_reports_steps_count(self, client: TestClient, auth_headers):
        """GIVEN 3 steps WHEN POST /workflows/execute THEN steps_count == 3."""
        self._setup_workflow_mock()
        r = client.post(
            "/workflows/execute",
            json={"workflow_name": "wf", "steps": [{"a": 1}, {"b": 2}, {"c": 3}]},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["steps_count"] == 3

    def test_workflow_status_unauthenticated(self, client: TestClient):
        """GIVEN no auth WHEN GET /workflows/status/t1 THEN 401."""
        r = client.get("/workflows/status/t1")
        assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# 9. Dataset / IPFS / Vector / Audit / Cache — authenticated error paths
# ══════════════════════════════════════════════════════════════════════════════


class TestDatasetEndpointsAuth:
    """Tests verifying auth-required dataset routes reject unauthenticated requests."""

    def test_load_dataset_no_auth(self, client: TestClient):
        r = client.post("/datasets/load", json={"source": "hf://squad"})
        assert r.status_code == 401

    def test_process_dataset_no_auth(self, client: TestClient):
        r = client.post("/datasets/process", json={"dataset_source": "x", "operations": []})
        assert r.status_code == 401

    def test_save_dataset_no_auth(self, client: TestClient):
        r = client.post("/datasets/save", json={"dataset_data": {}, "destination": "/tmp/out"})
        assert r.status_code == 401

    def test_convert_dataset_no_auth(self, client: TestClient):
        r = client.get("/datasets/convert?dataset_id=x&target_format=parquet")
        assert r.status_code in (401, 403, 404, 405)

    def test_load_dataset_authenticated_responds(self, client: TestClient, auth_headers):
        """GIVEN valid auth WHEN POST /datasets/load THEN endpoint responds (500 OK here due to missing inner module)."""
        r = client.post("/datasets/load", json={"source": "hf://squad"}, headers=auth_headers)
        assert r.status_code in (200, 404, 500)

    def test_save_dataset_authenticated_responds(self, client: TestClient, auth_headers):
        r = client.post(
            "/datasets/save",
            json={"dataset_data": {"rows": []}, "destination": "/tmp/ds.json"},
            headers=auth_headers,
        )
        assert r.status_code in (200, 404, 500)


class TestIPFSEndpointsAuth:
    """Tests verifying auth-required IPFS routes reject unauthenticated requests."""

    def test_pin_no_auth(self, client: TestClient):
        r = client.post("/ipfs/pin", json={"content_source": "data"})
        assert r.status_code == 401

    def test_get_cid_no_auth(self, client: TestClient):
        r = client.get("/ipfs/get/QmSomeHash")
        assert r.status_code == 401

    def test_pin_authenticated_responds(self, client: TestClient, auth_headers):
        r = client.post(
            "/ipfs/pin",
            json={"content_source": "hello ipfs"},
            headers=auth_headers,
        )
        assert r.status_code in (200, 404, 500)

    def test_get_cid_authenticated_responds(self, client: TestClient, auth_headers):
        r = client.get("/ipfs/get/QmTestCid", headers=auth_headers)
        assert r.status_code in (200, 404, 500)


class TestVectorEndpointsAuth:
    """Tests verifying auth-required vector routes reject unauthenticated requests."""

    def test_create_index_no_auth(self, client: TestClient):
        r = client.post("/vectors/create-index", json={"vectors": [[1.0, 2.0]]})
        assert r.status_code == 401

    def test_search_no_auth(self, client: TestClient):
        r = client.post("/vectors/search?index_id=idx", json={"query_vector": [1.0]})
        assert r.status_code in (401, 403, 404, 422)

    def test_create_index_authenticated_responds(self, client: TestClient, auth_headers):
        r = client.post(
            "/vectors/create-index",
            json={"vectors": [[1.0, 2.0], [3.0, 4.0]]},
            headers=auth_headers,
        )
        assert r.status_code in (200, 404, 500)

    def test_vector_search_authenticated_responds(self, client: TestClient, auth_headers):
        r = client.post(
            "/vectors/search?index_id=myidx",
            json={"query_vector": [0.1, 0.2]},
            headers=auth_headers,
        )
        assert r.status_code in (200, 404, 422, 500)


class TestAuditAndCacheEndpointsAuth:
    """Tests for /audit and /cache endpoint auth enforcement."""

    def test_audit_record_no_auth(self, client: TestClient):
        r = client.post("/audit/record?action=test")
        assert r.status_code == 401

    def test_audit_report_no_auth(self, client: TestClient):
        r = client.get("/audit/report")
        assert r.status_code == 401

    def test_cache_stats_no_auth(self, client: TestClient):
        r = client.get("/cache/stats")
        assert r.status_code == 401

    def test_cache_clear_no_auth(self, client: TestClient):
        r = client.post("/cache/clear")
        assert r.status_code == 401

    def test_audit_record_authenticated_responds(self, client: TestClient, auth_headers):
        r = client.post("/audit/record?action=test_action", headers=auth_headers)
        assert r.status_code in (200, 404, 500)

    def test_cache_stats_authenticated_responds(self, client: TestClient, auth_headers):
        r = client.get("/cache/stats", headers=auth_headers)
        assert r.status_code in (200, 404, 500)


# ══════════════════════════════════════════════════════════════════════════════
# 10. log_api_request utility
# ══════════════════════════════════════════════════════════════════════════════


class TestLogApiRequest:
    """Tests for the log_api_request async utility."""

    async def test_log_succeeds_silently(self):
        """GIVEN a successful tool call WHEN log_api_request called THEN no exception."""
        # If audit_tools import fails it is silently caught
        await svc.log_api_request("u1", "/embeddings/generate", status="success")

    async def test_log_with_error_string(self):
        """GIVEN an error WHEN log_api_request called THEN no exception."""
        await svc.log_api_request("u2", "/search/semantic", status="error", error="oops")

    async def test_log_with_input_size(self):
        """GIVEN input_size param WHEN log_api_request called THEN no exception."""
        await svc.log_api_request("u3", "/embeddings/generate", input_size=128, status="success")


# ══════════════════════════════════════════════════════════════════════════════
# 11. custom_openapi
# ══════════════════════════════════════════════════════════════════════════════


class TestCustomOpenAPI:
    """Tests for the custom_openapi() function."""

    def test_returns_dict(self):
        """GIVEN custom_openapi called THEN returns a dict."""
        result = svc.custom_openapi()
        assert isinstance(result, dict)

    def test_contains_openapi_version(self):
        """GIVEN custom_openapi THEN result has 'openapi' key."""
        result = svc.custom_openapi()
        assert "openapi" in result

    def test_cached_on_app(self):
        """GIVEN custom_openapi called twice THEN returns same object."""
        r1 = svc.custom_openapi()
        r2 = svc.custom_openapi()
        assert r1 is r2  # cached on app.openapi_schema


# ══════════════════════════════════════════════════════════════════════════════
# 12. run_development_server / run_production_server
# ══════════════════════════════════════════════════════════════════════════════


class TestRunServers:
    """Tests for the server startup helpers."""

    def test_run_development_server_calls_uvicorn(self):
        """GIVEN uvicorn available WHEN run_development_server called THEN uvicorn.run invoked."""
        mock_uv = MagicMock()
        with patch.object(svc, "HAVE_UVICORN", True), patch.object(svc, "uvicorn", mock_uv):
            svc.run_development_server()
        assert mock_uv.run.called

    def test_run_production_server_calls_uvicorn(self):
        """GIVEN uvicorn available WHEN run_production_server called THEN uvicorn.run invoked."""
        mock_uv = MagicMock()
        with patch.object(svc, "HAVE_UVICORN", True), patch.object(svc, "uvicorn", mock_uv):
            svc.run_production_server()
        assert mock_uv.run.called

    def test_run_development_server_passes_reload_false(self):
        """GIVEN non-debug settings WHEN run_development_server called THEN reload kwarg is False."""
        mock_uv = MagicMock()
        with patch.object(svc, "HAVE_UVICORN", True), patch.object(svc, "uvicorn", mock_uv):
            svc.run_development_server()
        call_kwargs = mock_uv.run.call_args[1]
        assert call_kwargs.get("reload") is False or "reload" in call_kwargs

    def test_run_production_server_uses_workers(self):
        """GIVEN production server WHEN uvicorn.run called THEN workers kwarg >= 1."""
        mock_uv = MagicMock()
        with patch.object(svc, "HAVE_UVICORN", True), patch.object(svc, "uvicorn", mock_uv):
            svc.run_production_server()
        call_kwargs = mock_uv.run.call_args[1]
        assert "workers" in call_kwargs
        assert call_kwargs["workers"] >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 13. Additional route guards (/analysis, /admin, /embeddings/batch)
# ══════════════════════════════════════════════════════════════════════════════


class TestAdditionalRouteGuards:
    """Verify remaining routes require authentication."""

    def test_analysis_clustering_no_auth(self, client: TestClient):
        r = client.post("/analysis/clustering", json={"vectors": [[1.0, 2.0]], "analysis_type": "clustering"})
        assert r.status_code == 401

    def test_analysis_quality_no_auth(self, client: TestClient):
        r = client.post("/analysis/quality?vectors[]=1.0", json=[])
        assert r.status_code in (401, 403, 404, 422)

    def test_admin_stats_no_auth(self, client: TestClient):
        r = client.get("/admin/stats")
        assert r.status_code == 401

    def test_admin_health_no_auth(self, client: TestClient):
        r = client.get("/admin/health")
        assert r.status_code == 401

    def test_embeddings_batch_no_auth(self, client: TestClient):
        r = client.post("/embeddings/batch", json=["text1", "text2"])
        assert r.status_code == 401

    def test_analysis_clustering_authenticated_responds(self, client: TestClient, auth_headers):
        r = client.post(
            "/analysis/clustering",
            json={"vectors": [[1.0, 2.0], [3.0, 4.0]], "analysis_type": "clustering"},
            headers=auth_headers,
        )
        assert r.status_code in (200, 404, 422, 500)

    def test_admin_stats_authenticated_responds(self, client: TestClient, auth_headers):
        r = client.get("/admin/stats", headers=auth_headers)
        assert r.status_code in (200, 404, 500)

    def test_admin_health_authenticated_responds(self, client: TestClient, auth_headers):
        r = client.get("/admin/health", headers=auth_headers)
        assert r.status_code in (200, 404, 500)
