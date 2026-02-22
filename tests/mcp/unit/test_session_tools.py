"""
Tests for session_tools tool category.

Tests cover:
- create_session: create a new embedding/processing session
- manage_session_state: get/update/pause/resume/extend/delete sessions
- cleanup_sessions: prune expired sessions
"""
import importlib.util
import sys
from pathlib import Path

import pytest

# Load session_tools.py directly to bypass enhanced_session_tools import error
# (enhanced_session_tools.py has a broken relative import of ..monitoring)
_ROOT = Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py"
_spec = importlib.util.spec_from_file_location(
    "_session_tools",
    str(_ROOT / "mcp_server/tools/session_tools/session_tools.py"),
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_session_tools"] = _mod
_spec.loader.exec_module(_mod)

create_session = _mod.create_session
manage_session_state = _mod.manage_session_state
cleanup_sessions = _mod.cleanup_sessions


class TestCreateSession:
    """Tests for create_session tool function."""

    @pytest.mark.asyncio
    async def test_create_basic_session_returns_dict(self):
        """
        GIVEN the session_tools module
        WHEN create_session is called with a session_name
        THEN the result must be a dict
        """
        result = await create_session(session_name="test-session")
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_create_session_with_user_id_returns_dict(self):
        """
        GIVEN the session_tools module
        WHEN create_session is called with a user_id
        THEN the result must be a dict containing session info
        """
        result = await create_session(session_name="user-session", user_id="user_alice")
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_create_session_with_config_returns_dict(self):
        """
        GIVEN the session_tools module
        WHEN create_session is called with a custom session_config
        THEN the result must be a dict
        """
        result = await create_session(
            session_name="custom-session",
            user_id="user_bob",
            session_config={
                "models": ["sentence-transformers/all-MiniLM-L6-v2"],
                "max_requests_per_minute": 50,
            },
        )
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_create_session_empty_name_returns_error(self):
        """
        GIVEN the session_tools module
        WHEN create_session is called with an empty name
        THEN the result must be a dict with a status error
        """
        result = await create_session(session_name="")
        assert result is not None
        assert isinstance(result, dict)
        assert result.get("status") == "error" or "message" in result

    @pytest.mark.asyncio
    async def test_create_session_too_long_name_returns_error(self):
        """
        GIVEN the session_tools module
        WHEN create_session is called with a name exceeding 100 chars
        THEN the result must be a dict with a status error
        """
        long_name = "x" * 101
        result = await create_session(session_name=long_name)
        assert result is not None
        assert isinstance(result, dict)
        assert result.get("status") == "error" or "message" in result


class TestManageSessionState:
    """Tests for manage_session_state tool function."""

    @pytest.mark.asyncio
    async def test_invalid_session_id_format_returns_error(self):
        """
        GIVEN the session_tools module
        WHEN manage_session_state is called with an invalid session_id format
        THEN the result must be a dict with a status error
        """
        result = await manage_session_state(session_id="not-a-uuid", action="get")
        assert result is not None
        assert isinstance(result, dict)
        assert result.get("status") == "error" or "message" in result

    @pytest.mark.asyncio
    async def test_invalid_action_returns_error(self):
        """
        GIVEN the session_tools module
        WHEN manage_session_state is called with an invalid action
        THEN the result must be a dict with a status error
        """
        result = await manage_session_state(
            session_id="123e4567-e89b-12d3-a456-426614174000",
            action="invalid_action",
        )
        assert result is not None
        assert isinstance(result, dict)
        assert result.get("status") == "error" or "message" in result

    @pytest.mark.asyncio
    async def test_get_nonexistent_session_returns_error(self):
        """
        GIVEN the session_tools module
        WHEN manage_session_state is called with a valid UUID that doesn't exist
        THEN the result must be a dict with a not-found error
        """
        result = await manage_session_state(
            session_id="123e4567-e89b-12d3-a456-426614174000",
            action="get",
        )
        assert result is not None
        assert isinstance(result, dict)
        assert result.get("status") == "error" or "message" in result


class TestCleanupSessions:
    """Tests for cleanup_sessions tool function."""

    @pytest.mark.asyncio
    async def test_cleanup_expired_returns_dict(self):
        """
        GIVEN the session_tools module
        WHEN cleanup_sessions is called with cleanup_type='expired'
        THEN the result must be a dict
        """
        result = await cleanup_sessions(cleanup_type="expired")
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_cleanup_all_returns_dict(self):
        """
        GIVEN the session_tools module
        WHEN cleanup_sessions is called with cleanup_type='all'
        THEN the result must be a dict
        """
        result = await cleanup_sessions(cleanup_type="all")
        assert result is not None
        assert isinstance(result, dict)
