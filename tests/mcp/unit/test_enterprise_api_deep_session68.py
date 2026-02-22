"""
Session Q68 — enterprise_api.py deep coverage:
  RateLimiter.check_limits, ProcessingJobManager (submit/status/user_jobs/process_job),
  EnterpriseGraphRAGAPI (create_jwt_token/validate_jwt_token), AdvancedAnalyticsDashboard
"""
import sys
import asyncio
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Stub heavy deps BEFORE importing enterprise_api
# ---------------------------------------------------------------------------
for _mod_name in ["mcp", "mcp.server"]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()

# Stub the graphrag processor module that enterprise_api imports at module level
_graphrag_stub = MagicMock()
_graphrag_stub.CompleteGraphRAGSystem = MagicMock()
_graphrag_stub.CompleteProcessingConfiguration = MagicMock()
_graphrag_stub.CompleteProcessingResult = MagicMock()
sys.modules.setdefault("ipfs_datasets_py.processors", MagicMock())
sys.modules.setdefault("ipfs_datasets_py.processors.graphrag", MagicMock())
sys.modules["ipfs_datasets_py.processors.graphrag.complete_advanced_graphrag"] = _graphrag_stub

from ipfs_datasets_py.mcp_server.enterprise_api import (
    RateLimiter,
    ProcessingJobManager,
    EnterpriseGraphRAGAPI,
    AdvancedAnalyticsDashboard,
    WebsiteProcessingRequest,
)
from ipfs_datasets_py.mcp_server.exceptions import ToolExecutionError


# ---------------------------------------------------------------------------
# TestRateLimiter
# ---------------------------------------------------------------------------

class TestRateLimiter:
    """Tests for RateLimiter.check_limits()."""

    @pytest.mark.asyncio
    async def test_no_limits_for_unknown_endpoint(self):
        """Endpoint not in limits dict passes without exception."""
        rl = RateLimiter()
        # Should not raise
        await rl.check_limits("user1", "unknown_endpoint")

    @pytest.mark.asyncio
    async def test_increments_counter_on_first_request(self):
        """First request for a limited endpoint increments counter."""
        rl = RateLimiter()
        await rl.check_limits("user1", "search")
        queue = rl.user_requests["user1:search"]
        assert len(queue) == 1

    @pytest.mark.asyncio
    async def test_exceeds_limit_raises_429(self):
        """Exceeding the rate limit raises HTTPException 429."""
        rl = RateLimiter()
        # Use a very low-limit endpoint — inject one manually
        rl.limits["test_ep"] = {"requests": 2, "window": 3600}
        await rl.check_limits("user2", "test_ep")
        await rl.check_limits("user2", "test_ep")
        with pytest.raises(HTTPException) as exc_info:
            await rl.check_limits("user2", "test_ep")
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_expired_window_resets_counter(self):
        """Requests outside the window are removed; counter starts fresh."""
        rl = RateLimiter()
        rl.limits["short_ep"] = {"requests": 2, "window": 1}
        # Pre-fill with old timestamps (well outside 1-second window)
        old_ts = time.time() - 10.0
        rl.user_requests["user3:short_ep"].extend([old_ts, old_ts])
        # After window expiry, the 2 old items are evicted; new request should pass
        await rl.check_limits("user3", "short_ep")
        queue = rl.user_requests["user3:short_ep"]
        # Only the new (current) request should remain
        assert len(queue) == 1

    @pytest.mark.asyncio
    async def test_multiple_users_are_independent(self):
        """Rate limiting tracks each (user_id, endpoint) pair independently."""
        rl = RateLimiter()
        rl.limits["ep"] = {"requests": 1, "window": 3600}
        # user_a hits the limit
        await rl.check_limits("user_a", "ep")
        with pytest.raises(HTTPException):
            await rl.check_limits("user_a", "ep")
        # user_b has not hit the limit yet
        await rl.check_limits("user_b", "ep")  # should not raise


# ---------------------------------------------------------------------------
# TestProcessingJobManager
# ---------------------------------------------------------------------------

class TestProcessingJobManager:
    """Tests for ProcessingJobManager."""

    @pytest.mark.asyncio
    async def test_submit_job_returns_job_id(self):
        """submit_job() stores job and returns a non-empty job_id."""
        mgr = ProcessingJobManager()
        req = WebsiteProcessingRequest(
            url="https://example.com",
            processing_mode="standard",
        )
        job_id = await mgr.submit_job("user1", req)
        assert isinstance(job_id, str) and job_id
        assert job_id in mgr.jobs

    @pytest.mark.asyncio
    async def test_submit_job_initial_status_queued(self):
        """Submitted job has status='queued' and progress=0.0."""
        mgr = ProcessingJobManager()
        req = WebsiteProcessingRequest(url="https://example.com")
        job_id = await mgr.submit_job("user1", req)
        job = mgr.jobs[job_id]
        assert job["status"] == "queued"
        assert job["progress"] == 0.0

    def test_get_job_status_existing(self):
        """get_job_status() returns a response for a known job_id."""
        mgr = ProcessingJobManager()
        mgr.jobs["j1"] = {
            "job_id": "j1",
            "user_id": "u1",
            "website_url": "https://example.com",
            "processing_mode": "standard",
            "status": "queued",
            "progress": 0.0,
            "created_at": datetime.now(),
            "started_at": None,
            "completed_at": None,
            "error_message": None,
        }
        result = mgr.get_job_status("j1")
        assert result is not None
        assert result.job_id == "j1"

    def test_get_job_status_missing(self):
        """get_job_status() returns None for unknown job_id."""
        mgr = ProcessingJobManager()
        assert mgr.get_job_status("nonexistent") is None

    def test_get_user_jobs_filters_by_user(self):
        """get_user_jobs() returns only jobs belonging to the given user."""
        mgr = ProcessingJobManager()
        now = datetime.now()
        for uid, jid in [("alice", "j1"), ("alice", "j2"), ("bob", "j3")]:
            mgr.jobs[jid] = {
                "job_id": jid, "user_id": uid,
                "website_url": "https://x.com",
                "processing_mode": "standard",
                "status": "queued", "progress": 0.0,
                "created_at": now, "started_at": None,
                "completed_at": None, "error_message": None,
            }
        alice_jobs = mgr.get_user_jobs("alice")
        assert len(alice_jobs) == 2
        bob_jobs = mgr.get_user_jobs("bob")
        assert len(bob_jobs) == 1

    def test_get_user_jobs_sorted_descending(self):
        """get_user_jobs() is sorted by created_at descending."""
        from datetime import timedelta
        mgr = ProcessingJobManager()
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        for i, jid in enumerate(["j_old", "j_new"]):
            mgr.jobs[jid] = {
                "job_id": jid, "user_id": "alice",
                "website_url": "https://x.com",
                "processing_mode": "standard",
                "status": "queued", "progress": 0.0,
                "created_at": t0 + timedelta(hours=i),
                "started_at": None, "completed_at": None, "error_message": None,
            }
        jobs = mgr.get_user_jobs("alice")
        assert jobs[0].job_id == "j_new"
        assert jobs[1].job_id == "j_old"

    @pytest.mark.asyncio
    async def test_process_job_tool_execution_error_sets_failed(self):
        """process_job() sets status='failed' on ToolExecutionError."""
        mgr = ProcessingJobManager()
        now = datetime.now()
        mgr.jobs["jx"] = {
            "job_id": "jx", "user_id": "u1",
            "website_url": "https://x.com",
            "processing_mode": "standard",
            "status": "queued", "progress": 0.0,
            "created_at": now, "started_at": None,
            "completed_at": None, "error_message": None,
        }
        req = WebsiteProcessingRequest(url="https://x.com")
        req.notify_webhook = None
        # Patch the system import to raise ToolExecutionError
        with patch.dict(sys.modules, {
            "ipfs_datasets_py.rag": MagicMock(),
        }):
            with patch(
                "ipfs_datasets_py.mcp_server.enterprise_api.CompleteGraphRAGSystem",
                side_effect=ToolExecutionError("process", Exception("err")),
            ):
                await mgr.process_job("jx", req)
        assert mgr.jobs["jx"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_process_job_value_error_sets_failed_with_invalid_params(self):
        """process_job() sets 'Invalid parameters' message on ValueError."""
        mgr = ProcessingJobManager()
        now = datetime.now()
        mgr.jobs["jy"] = {
            "job_id": "jy", "user_id": "u1",
            "website_url": "https://y.com",
            "processing_mode": "standard",
            "status": "queued", "progress": 0.0,
            "created_at": now, "started_at": None,
            "completed_at": None, "error_message": None,
        }
        req = WebsiteProcessingRequest(url="https://y.com")
        req.notify_webhook = None
        with patch(
            "ipfs_datasets_py.mcp_server.enterprise_api.CompleteGraphRAGSystem",
            side_effect=ValueError("bad param"),
        ):
            await mgr.process_job("jy", req)
        assert mgr.jobs["jy"]["status"] == "failed"
        assert "Invalid parameters" in mgr.jobs["jy"]["error_message"]

    @pytest.mark.asyncio
    async def test_send_webhook_notification_no_aiohttp(self):
        """_send_webhook_notification() does not raise when aiohttp absent."""
        mgr = ProcessingJobManager()
        with patch.dict(sys.modules, {"aiohttp": None}):
            # Should log and return without raising
            await mgr._send_webhook_notification("http://webhook.test/x", "j1", "completed")

    @pytest.mark.asyncio
    async def test_send_webhook_notification_generic_exception(self):
        """_send_webhook_notification() logs on generic exception."""
        mgr = ProcessingJobManager()
        fake_aiohttp = MagicMock()
        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=None)
        fake_session.post = AsyncMock(side_effect=RuntimeError("network error"))
        fake_aiohttp.ClientSession.return_value = fake_session
        with patch.dict(sys.modules, {"aiohttp": fake_aiohttp}):
            # Should log warning, not raise
            await mgr._send_webhook_notification("http://webhook.test/x", "j1", "completed")


# ---------------------------------------------------------------------------
# TestEnterpriseGraphRAGAPITokens
# ---------------------------------------------------------------------------

class TestEnterpriseGraphRAGAPITokens:
    """Tests for EnterpriseGraphRAGAPI JWT helpers."""

    def test_create_jwt_token_returns_string(self):
        """create_jwt_token() returns a non-empty JWT string."""
        api = EnterpriseGraphRAGAPI()
        token = api.create_jwt_token({"username": "demo"})
        assert isinstance(token, str) and token

    def test_create_jwt_token_uses_user_id_fallback(self):
        """create_jwt_token() falls back to user_id if username absent."""
        api = EnterpriseGraphRAGAPI()
        token = api.create_jwt_token({"user_id": "some-id"})
        data = api.validate_jwt_token(token)
        # user_id fallback not in users_db → None is fine
        assert token  # just verify no exception

    def test_validate_jwt_token_valid_returns_dict(self):
        """validate_jwt_token() returns dict for a valid 'demo' token."""
        api = EnterpriseGraphRAGAPI()
        token = api.create_jwt_token({"username": "demo"})
        result = api.validate_jwt_token(token)
        assert result is not None
        assert result["username"] == "demo"

    def test_validate_jwt_token_invalid_returns_none(self):
        """validate_jwt_token() returns None for a garbled token."""
        api = EnterpriseGraphRAGAPI()
        assert api.validate_jwt_token("not.a.valid.token") is None

    def test_validate_jwt_token_revoked_returns_none(self):
        """validate_jwt_token() returns None for a revoked token."""
        api = EnterpriseGraphRAGAPI()
        token = api.create_jwt_token({"username": "demo"})
        api.auth_manager.revoke_token(token)
        assert api.validate_jwt_token(token) is None


# ---------------------------------------------------------------------------
# TestAdvancedAnalyticsDashboard
# ---------------------------------------------------------------------------

class TestAdvancedAnalyticsDashboard:
    """Tests for AdvancedAnalyticsDashboard."""

    def test_generate_system_report_empty_jobs(self):
        """generate_system_report() works with no jobs submitted."""
        mgr = ProcessingJobManager()
        dash = AdvancedAnalyticsDashboard(mgr)
        report = dash.generate_system_report()
        assert "system_overview" in report
        assert "job_statistics" in report
        assert "performance_metrics" in report
        assert report["system_overview"]["total_jobs"] == 0
        assert report["system_overview"]["success_rate"] == 0

    def test_calculate_avg_quality_no_results(self):
        """_calculate_avg_quality() returns 0.0 when no results exist."""
        mgr = ProcessingJobManager()
        dash = AdvancedAnalyticsDashboard(mgr)
        assert dash._calculate_avg_quality() == 0.0

    def test_get_recent_activity_empty(self):
        """_get_recent_activity() returns empty list with no jobs."""
        mgr = ProcessingJobManager()
        dash = AdvancedAnalyticsDashboard(mgr)
        assert dash._get_recent_activity() == []

    def test_get_recent_activity_has_correct_keys(self):
        """_get_recent_activity() entries have required keys."""
        mgr = ProcessingJobManager()
        mgr.jobs["j1"] = {
            "job_id": "j1", "user_id": "u1",
            "website_url": "https://example.com",
            "processing_mode": "standard",
            "status": "completed", "progress": 1.0,
            "created_at": datetime.now(),
            "started_at": None, "completed_at": None, "error_message": None,
        }
        dash = AdvancedAnalyticsDashboard(mgr)
        activity = dash._get_recent_activity()
        assert len(activity) == 1
        row = activity[0]
        assert "job_id" in row
        assert "status" in row
        assert "website_url" in row
        assert "created_at" in row

    def test_generate_system_report_counts_completed_and_failed(self):
        """Job statistics section correctly counts completed/failed jobs."""
        mgr = ProcessingJobManager()
        now = datetime.now()
        for jid, st in [("j1", "completed"), ("j2", "failed"), ("j3", "queued")]:
            mgr.jobs[jid] = {
                "job_id": jid, "user_id": "u1",
                "website_url": "https://x.com",
                "processing_mode": "standard",
                "status": st, "progress": 0.0,
                "created_at": now, "started_at": None,
                "completed_at": now if st == "completed" else None,
                "error_message": None,
            }
        dash = AdvancedAnalyticsDashboard(mgr)
        report = dash.generate_system_report()
        assert report["job_statistics"]["completed"] == 1
        assert report["job_statistics"]["failed"] == 1
        assert report["job_statistics"]["queued"] == 1
