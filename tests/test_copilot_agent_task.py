#!/usr/bin/env python3
"""Focused tests for the repo's maintained Copilot CLI integrations."""

from unittest.mock import patch


def test_backward_compatible_copilot_wrapper_supports_structured_methods():
    """The deprecated shim should still expose the structured gh-copilot helpers."""

    from ipfs_datasets_py.utils.copilot_cli import CopilotCLI

    with patch.object(CopilotCLI, "_verify_installation", return_value=True), patch.object(
        CopilotCLI, "_check_copilot_extension", return_value=True
    ):
        cli = CopilotCLI(github_cli_path="/usr/bin/gh", enable_cache=False)

    with patch.object(
        cli,
        "_run_command",
        return_value={"success": True, "stdout": "git status\n", "stderr": "", "returncode": 0},
    ):
        result = cli.suggest_command("show repository status", shell="bash")

    assert result["success"] is True
    assert result["suggestion"] == "git status"
    assert result["shell"] == "bash"


def test_gh_copilot_status_reports_extension_and_agent_task_state():
    """Status should describe gh availability, extension state, and agent-task support."""

    from ipfs_datasets_py.utils.copilot_cli import CopilotCLI

    with patch.object(CopilotCLI, "_verify_installation", return_value=True), patch.object(
        CopilotCLI, "_check_copilot_extension", return_value=True
    ), patch("ipfs_datasets_py.utils.cli_tools.copilot.subprocess.run") as mock_run:
        mock_run.side_effect = [
            type("Result", (), {"returncode": 0, "stdout": "gh version 2.0.0\n", "stderr": ""})(),
            type("Result", (), {"returncode": 1, "stdout": "", "stderr": "unknown command 'agent-task' for 'gh'"})(),
        ]

        cli = CopilotCLI(github_cli_path="/usr/bin/gh", enable_cache=False)
        status = cli.get_status()

    assert status["installed"] is True
    assert status["github_cli_available"] is True
    assert status["copilot_extension_installed"] is True
    assert status["github_cli_path"] == "/usr/bin/gh"
    assert status["version_info"] == "gh version 2.0.0"
    assert status["agent_task_available"] is False


def test_create_agent_task_returns_structured_unavailable_error():
    """Legacy callers should get a structured failure instead of AttributeError."""

    from ipfs_datasets_py.utils.copilot_cli import CopilotCLI

    with patch.object(CopilotCLI, "_verify_installation", return_value=True), patch.object(
        CopilotCLI, "_check_copilot_extension", return_value=True
    ):
        cli = CopilotCLI(github_cli_path="/usr/bin/gh", enable_cache=False)

    with patch.object(cli, "has_agent_task_support", return_value=False):
        result = cli.create_agent_task(task_description="Fix issue 123", base_branch="main")

    assert result["success"] is False
    assert "agent-task" in result["error"]


def test_create_agent_task_uses_gh_when_available():
    """Compatibility helper should call gh agent-task create when supported."""

    from ipfs_datasets_py.utils.copilot_cli import CopilotCLI

    with patch.object(CopilotCLI, "_verify_installation", return_value=True), patch.object(
        CopilotCLI, "_check_copilot_extension", return_value=True
    ):
        cli = CopilotCLI(github_cli_path="/usr/bin/gh", enable_cache=False)

    with patch.object(cli, "has_agent_task_support", return_value=True), patch.object(
        cli,
        "_run_command",
        return_value={"success": True, "stdout": "created\n", "stderr": "", "returncode": 0},
    ) as mock_run:
        result = cli.create_agent_task(task_description="Fix issue 123", base_branch="main", follow=True)

    assert result["success"] is True
    args = mock_run.call_args.args[0]
    assert args == ["agent-task", "create", "Fix issue 123", "--base", "main", "--follow"]


def test_standalone_copilot_command_template_prefers_resolved_binary():
    """Router defaults should point at the standalone local copilot binary."""

    from ipfs_datasets_py.utils.cli_tools.copilot import build_standalone_copilot_command_template

    template = build_standalone_copilot_command_template("/opt/copilot/bin/copilot")

    assert template.startswith("/opt/copilot/bin/copilot ")
    assert "--allow-all-tools" in template
    assert "--no-ask-user" in template
    assert "--model {model}" in template
    assert "--prompt {prompt}" in template


def test_standalone_copilot_prompt_returns_structured_result():
    """Standalone wrapper should build deterministic non-interactive prompt calls."""

    from ipfs_datasets_py.utils.cli_tools.copilot import StandaloneCopilot

    with patch.object(StandaloneCopilot, "_verify_installation", return_value=True):
        cli = StandaloneCopilot(copilot_cli_path="/usr/bin/copilot", enable_cache=False)

    with patch.object(
        cli,
        "_run_command",
        return_value={"success": True, "stdout": "summary\n", "stderr": "", "returncode": 0},
    ) as mock_run:
        result = cli.prompt("Summarize this repo", model="gpt-5.4", autopilot=True)

    assert result["success"] is True
    assert result["response"] == "summary"
    args = mock_run.call_args.args[0]
    assert args[:5] == ["--silent", "--stream", "off", "--allow-all-tools", "--no-ask-user"]
    assert "--autopilot" in args
    assert args[-2:] == ["--prompt", "Summarize this repo"]
