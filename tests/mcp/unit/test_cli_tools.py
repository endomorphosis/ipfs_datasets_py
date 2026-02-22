"""
Tests for CLI tools.

Tests cover:
- execute_command: security stub that logs but does not execute commands
"""
import asyncio

import pytest


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestExecuteCommand:
    """Tests for the execute_command security stub (cli/execute_command.py)."""

    def setup_method(self):
        from ipfs_datasets_py.mcp_server.tools.cli.execute_command import execute_command
        self.fn = execute_command

    def test_returns_dict(self):
        """GIVEN any command WHEN execute_command is called THEN it returns a dict."""
        result = _run(self.fn("ls"))
        assert isinstance(result, dict)

    def test_status_is_success(self):
        """GIVEN a valid command THEN status is 'success' (security stub always succeeds)."""
        result = _run(self.fn("ls"))
        assert result.get("status") == "success"

    def test_command_echoed_in_result(self):
        """GIVEN command='echo' THEN result['command'] == 'echo'."""
        result = _run(self.fn("echo"))
        assert result.get("command") == "echo"

    def test_args_echoed_in_result(self):
        """GIVEN args=['-la'] THEN result['args'] == ['-la']."""
        result = _run(self.fn("ls", args=["-la"]))
        assert result.get("args") == ["-la"]

    def test_default_args_is_empty_list(self):
        """GIVEN no args argument THEN result['args'] == []."""
        result = _run(self.fn("pwd"))
        assert result.get("args") == []

    def test_message_key_is_present(self):
        """GIVEN any command THEN result contains a 'message' key."""
        result = _run(self.fn("rm"))
        assert "message" in result

    def test_timeout_param_accepted(self):
        """GIVEN timeout_seconds=30 THEN the call succeeds (param is accepted)."""
        result = _run(self.fn("sleep", args=["1"], timeout_seconds=30))
        assert isinstance(result, dict)

    def test_security_message_explains_no_exec(self):
        """GIVEN any command THEN message explains command was not actually executed."""
        result = _run(self.fn("malicious_script"))
        msg = result.get("message", "").lower()
        assert "security" in msg or "not executed" in msg or "received" in msg
