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


def test_gh_copilot_status_reports_extension_state():
    """Status should describe both gh availability and the extension state."""

    from ipfs_datasets_py.utils.copilot_cli import CopilotCLI

    with patch.object(CopilotCLI, "_verify_installation", return_value=True), patch.object(
        CopilotCLI, "_check_copilot_extension", return_value=True
    ), patch("ipfs_datasets_py.utils.cli_tools.copilot.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "gh version 2.0.0\n"
        mock_run.return_value.stderr = ""

        cli = CopilotCLI(github_cli_path="/usr/bin/gh", enable_cache=False)
        status = cli.get_status()

    assert status["installed"] is True
    assert status["github_cli_available"] is True
    assert status["copilot_extension_installed"] is True
    assert status["github_cli_path"] == "/usr/bin/gh"
    assert status["version_info"] == "gh version 2.0.0"


def test_standalone_copilot_command_template_prefers_resolved_binary():
    """Router defaults should point at the standalone local copilot binary."""

    from ipfs_datasets_py.utils.cli_tools.copilot import build_standalone_copilot_command_template

    template = build_standalone_copilot_command_template("/opt/copilot/bin/copilot")

    assert template.startswith("/opt/copilot/bin/copilot ")
    assert "--allow-all-tools" in template
    assert "--no-ask-user" in template
    assert "--model {model}" in template
    assert "-p {prompt}" in template


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
    assert args[-2:] == ["-p", "Summarize this repo"]
        content = f.read()
    
    # Check for key updates
    assert 'gh agent-task' in content, \
        "Workflow should mention gh agent-task"
    assert 'agent-task create' in content or 'gh agent-task create' in content, \
        "Workflow should document gh agent-task create"
    
    # Check that documentation was updated
    assert 'proper' in content.lower() or 'correctly' in content.lower(), \
        "Workflow should indicate proper method"
    
    print("✅ Workflow file properly updated")
    return True


def main():
    """Run all tests."""
    print("🧪 Testing GitHub Copilot agent-task functionality\n")
    
    tests = [
        test_copilot_cli_has_agent_methods,
        test_create_agent_task_signature,
        test_create_agent_task_returns_dict,
        test_invoke_copilot_uses_agent_task,
        test_batch_assign_uses_agent_task,
        test_gh_agent_task_available,
        test_workflow_updated,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            print(f"\n▶️  Running: {test.__name__}")
            if test():
                passed += 1
            else:
                print(f"❌ FAILED: {test.__name__}")
                failed += 1
        except AssertionError as e:
            print(f"❌ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ ERROR: {e}")
            failed += 1
    
    print(f"\n{'='*60}")
    print(f"Tests: {passed}/{len(tests)} passed")
    
    if failed > 0:
        print(f"❌ {failed} test(s) failed")
        sys.exit(1)
    else:
        print("✅ All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
