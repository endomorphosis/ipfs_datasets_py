"""
T73 — enterprise_api.py TestClient integration tests
=====================================================
Exercises _setup_routes(), _setup_core_api_routes(), _setup_search_routes(),
_setup_analytics_routes() via httpx AsyncClient + ASGITransport.

Requires: fastapi, httpx (both installed in this env)
"""
from __future__ import annotations

import sys
import types
import pytest
import asyncio

# ---------------------------------------------------------------------------
# Stub the deep processor import BEFORE enterprise_api is loaded
# ---------------------------------------------------------------------------

def _inject_processor_stub():
    compl_mod = types.ModuleType(
        "ipfs_datasets_py.processors.graphrag.complete_advanced_graphrag"
    )
    class _FakeCGS:
        pass
    compl_mod.CompleteGraphRAGSystem = _FakeCGS
    compl_mod.CompleteProcessingConfiguration = _FakeCGS
    compl_mod.CompleteProcessingResult = _FakeCGS
    p_mod = types.ModuleType("ipfs_datasets_py.processors")
    g_mod = types.ModuleType("ipfs_datasets_py.processors.graphrag")
    sys.modules.setdefault("ipfs_datasets_py.processors", p_mod)
    sys.modules.setdefault("ipfs_datasets_py.processors.graphrag", g_mod)
    sys.modules.setdefault(
        "ipfs_datasets_py.processors.graphrag.complete_advanced_graphrag", compl_mod
    )


_inject_processor_stub()

from ipfs_datasets_py.mcp_server.enterprise_api import (
    EnterpriseGraphRAGAPI,
    WebsiteProcessingRequest,
    JobStatusResponse,
)

try:
    from httpx import AsyncClient, ASGITransport
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _HTTPX_AVAILABLE, reason="httpx not installed"
)


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def api() -> EnterpriseGraphRAGAPI:
    """Fresh enterprise API instance for each test."""
    return EnterpriseGraphRAGAPI()


@pytest.fixture()
async def auth_headers(api: EnterpriseGraphRAGAPI):
    """Obtain a Bearer token for the 'demo' user."""
    async with AsyncClient(
        transport=ASGITransport(app=api.app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/auth/login", params={"username": "demo", "password": "password"}
        )
        assert r.status_code == 200
        token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
async def admin_headers(api: EnterpriseGraphRAGAPI):
    """Obtain a Bearer token for the 'admin' user."""
    async with AsyncClient(
        transport=ASGITransport(app=api.app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/auth/login", params={"username": "admin", "password": "password"}
        )
        assert r.status_code == 200
        token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# /health endpoint
# ===========================================================================

class TestHealthEndpoint:

    async def test_health_returns_200(self, api):
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.get("/health")
        assert r.status_code == 200

    async def test_health_has_status_key(self, api):
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.get("/health")
        body = r.json()
        assert "status" in body
        assert body["status"] == "healthy"

    async def test_health_has_timestamp_key(self, api):
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.get("/health")
        assert "timestamp" in r.json()


# ===========================================================================
# /auth/login endpoint
# ===========================================================================

class TestAuthLogin:

    async def test_valid_credentials_returns_200(self, api):
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.post(
                "/auth/login", params={"username": "demo", "password": "password"}
            )
        assert r.status_code == 200

    async def test_login_returns_access_token(self, api):
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.post(
                "/auth/login", params={"username": "demo", "password": "password"}
            )
        body = r.json()
        assert "access_token" in body
        assert len(body["access_token"]) > 10

    async def test_invalid_credentials_returns_401(self, api):
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.post(
                "/auth/login", params={"username": "wrong", "password": "bad"}
            )
        assert r.status_code == 401

    async def test_admin_login_returns_200(self, api):
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.post(
                "/auth/login", params={"username": "admin", "password": "password"}
            )
        assert r.status_code == 200


# ===========================================================================
# /api/v1/jobs endpoints (core API routes)
# ===========================================================================

class TestJobsEndpoints:

    async def test_get_jobs_unauthenticated_returns_403_or_401(self, api):
        """No auth → FastAPI HTTPBearer returns 403."""
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.get("/api/v1/jobs")
        assert r.status_code in (401, 403)

    async def test_get_jobs_authenticated_returns_list(self, api, auth_headers):
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.get("/api/v1/jobs", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_get_job_status_not_found(self, api, auth_headers):
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.get("/api/v1/jobs/nonexistent-job-id", headers=auth_headers)
        assert r.status_code == 404

    async def test_process_website_missing_required_field_returns_422(self, api, auth_headers):
        """WebsiteProcessingRequest requires 'url'."""
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.post(
                "/api/v1/process-website",
                headers=auth_headers,
                json={"processing_mode": "fast"},  # missing 'url'
            )
        assert r.status_code == 422

    async def test_process_website_valid_returns_job_id(self, api, auth_headers):
        """Valid request → 200 with job_id."""
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.post(
                "/api/v1/process-website",
                headers=auth_headers,
                json={"url": "https://example.com"},
            )
        assert r.status_code == 200
        body = r.json()
        assert "job_id" in body
        assert body["status"] == "queued"


# ===========================================================================
# /api/v1/admin/analytics (analytics routes)
# ===========================================================================

class TestAnalyticsRoutes:

    async def test_admin_analytics_unauthenticated_returns_403(self, api):
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.get("/api/v1/admin/analytics")
        assert r.status_code in (401, 403)

    async def test_admin_analytics_non_admin_returns_403(self, api, auth_headers):
        """'demo' user does not have 'admin' role → 403."""
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.get("/api/v1/admin/analytics", headers=auth_headers)
        assert r.status_code == 403

    async def test_admin_analytics_admin_user_returns_200(self, api, admin_headers):
        """'admin' user has admin role → 200."""
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.get("/api/v1/admin/analytics", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert "total_jobs" in body
        assert "system_health" in body

    async def test_analytics_job_content_not_found(self, api, auth_headers):
        """GET /api/v1/analytics/<non-existent> → 404."""
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.get("/api/v1/analytics/no-such-job", headers=auth_headers)
        assert r.status_code == 404


# ===========================================================================
# /api/v1/search route
# ===========================================================================

class TestSearchRoute:

    async def test_search_unauthenticated_returns_403(self, api):
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.post(
                "/api/v1/search/some-job",
                json={"query": "test"},
            )
        assert r.status_code in (401, 403)

    async def test_search_job_not_completed_returns_404(self, api, auth_headers):
        """Search requires completed job in job_results."""
        async with AsyncClient(
            transport=ASGITransport(app=api.app), base_url="http://test"
        ) as c:
            r = await c.post(
                "/api/v1/search/no-such-job",
                headers=auth_headers,
                json={"query": "hello"},
            )
        assert r.status_code == 404


# ===========================================================================
# EnterpriseGraphRAGAPI setup helpers (direct)
# ===========================================================================

class TestSetupRoutesDirect:

    def test_setup_routes_called_during_init(self):
        """_create_app calls _setup_routes, so app.routes must have > 5 entries."""
        api = EnterpriseGraphRAGAPI()
        # FastAPI routes include the 4 custom routes + built-in /openapi.json etc.
        route_paths = [r.path for r in api.app.routes]
        assert "/health" in route_paths
        assert "/auth/login" in route_paths
        assert "/api/v1/jobs" in route_paths
        assert "/api/v1/admin/analytics" in route_paths

    def test_setup_health_and_auth_routes(self):
        """_setup_health_and_auth_routes must register /health and /auth/login."""
        from fastapi import FastAPI
        api = EnterpriseGraphRAGAPI()
        app2 = FastAPI()
        api._setup_health_and_auth_routes(app2)
        paths = {r.path for r in app2.routes}
        assert "/health" in paths
        assert "/auth/login" in paths

    def test_create_app_returns_fastapi_instance(self):
        from fastapi import FastAPI
        api = EnterpriseGraphRAGAPI()
        assert isinstance(api.app, FastAPI)
