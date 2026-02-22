"""
Session 37 — B2 tests for development_tools/vscode_cli_tools.py
(all 8 functions mocked via patch on VSCodeCLI).
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch, PropertyMock


# All functions are sync (not async)
from ipfs_datasets_py.mcp_server.tools.development_tools.vscode_cli_tools import (
    vscode_cli_status,
    vscode_cli_install,
    vscode_cli_execute,
    vscode_cli_list_extensions,
    vscode_cli_install_extension,
    vscode_cli_uninstall_extension,
    vscode_cli_tunnel_login,
    vscode_cli_tunnel_install_service,
)

_PATCH = "ipfs_datasets_py.mcp_server.tools.development_tools.vscode_cli_tools.VSCodeCLI"


def _mock_cli(**kwargs):
    """Return a MagicMock standing in for a VSCodeCLI instance."""
    m = MagicMock()
    m.get_status.return_value = {"installed": True, "version": "1.86.0"}
    m.download_and_install.return_value = True
    m.is_installed.return_value = True
    execute_result = MagicMock()
    execute_result.returncode = 0
    execute_result.stdout = "output"
    execute_result.stderr = ""
    m.execute.return_value = execute_result
    m.list_extensions.return_value = ["ms-python.python", "ms-toolsai.jupyter"]
    m.install_extension.return_value = True
    m.uninstall_extension.return_value = True
    m.tunnel_login.return_value = True
    m.install_tunnel_service.return_value = True
    for k, v in kwargs.items():
        setattr(m, k, v)
    return m


class TestVscodeCLIStatus(unittest.TestCase):
    def test_returns_dict(self):
        with patch(_PATCH, return_value=_mock_cli()) as MockCLI:
            MockCLI.return_value = _mock_cli()
            result = vscode_cli_status()
        self.assertIsInstance(result, dict)

    def test_success_key_present(self):
        with patch(_PATCH, return_value=_mock_cli()):
            result = vscode_cli_status()
        self.assertIn("success", result)

    def test_status_key_when_success(self):
        with patch(_PATCH, return_value=_mock_cli()):
            result = vscode_cli_status()
        if result.get("success"):
            self.assertIn("status", result)

    def test_install_dir_param_accepted(self):
        with patch(_PATCH, return_value=_mock_cli()):
            result = vscode_cli_status(install_dir="/tmp/vscode")
        self.assertIsInstance(result, dict)

    def test_exception_returns_error_dict(self):
        m = _mock_cli()
        m.get_status.side_effect = RuntimeError("no vscode")
        with patch(_PATCH, return_value=m):
            result = vscode_cli_status()
        self.assertFalse(result.get("success"))
        self.assertIn("error", result)


class TestVscodeCLIInstall(unittest.TestCase):
    def test_returns_dict(self):
        with patch(_PATCH, return_value=_mock_cli()):
            result = vscode_cli_install()
        self.assertIsInstance(result, dict)

    def test_success_on_happy_path(self):
        with patch(_PATCH, return_value=_mock_cli()):
            result = vscode_cli_install()
        self.assertTrue(result.get("success"))

    def test_force_and_commit_params_accepted(self):
        with patch(_PATCH, return_value=_mock_cli()):
            result = vscode_cli_install(force=True, commit="abc123")
        self.assertIsInstance(result, dict)

    def test_install_failure_returns_error(self):
        m = _mock_cli()
        m.download_and_install.return_value = False
        with patch(_PATCH, return_value=m):
            result = vscode_cli_install()
        self.assertFalse(result.get("success"))


class TestVscodeCLIExecute(unittest.TestCase):
    def test_returns_dict(self):
        with patch(_PATCH, return_value=_mock_cli()):
            result = vscode_cli_execute(["--version"])
        self.assertIsInstance(result, dict)

    def test_empty_command_returns_error(self):
        with patch(_PATCH, return_value=_mock_cli()):
            result = vscode_cli_execute([])
        self.assertFalse(result.get("success"))

    def test_timeout_param_accepted(self):
        with patch(_PATCH, return_value=_mock_cli()):
            result = vscode_cli_execute(["--version"], timeout=30)
        self.assertIsInstance(result, dict)

    def test_not_installed_returns_error(self):
        m = _mock_cli()
        m.is_installed.return_value = False
        with patch(_PATCH, return_value=m):
            result = vscode_cli_execute(["--version"])
        self.assertFalse(result.get("success"))


class TestVscodeCLIListExtensions(unittest.TestCase):
    def test_returns_dict(self):
        with patch(_PATCH, return_value=_mock_cli()):
            result = vscode_cli_list_extensions()
        self.assertIsInstance(result, dict)


class TestVscodeCLIExtensionManagement(unittest.TestCase):
    def test_install_extension_returns_dict(self):
        with patch(_PATCH, return_value=_mock_cli()):
            result = vscode_cli_install_extension("ms-python.python")
        self.assertIsInstance(result, dict)

    def test_uninstall_extension_returns_dict(self):
        with patch(_PATCH, return_value=_mock_cli()):
            result = vscode_cli_uninstall_extension("ms-python.python")
        self.assertIsInstance(result, dict)


class TestVscodeCLITunnel(unittest.TestCase):
    def test_tunnel_login_returns_dict(self):
        with patch(_PATCH, return_value=_mock_cli()):
            result = vscode_cli_tunnel_login()
        self.assertIsInstance(result, dict)

    def test_tunnel_install_service_returns_dict(self):
        with patch(_PATCH, return_value=_mock_cli()):
            result = vscode_cli_tunnel_install_service()
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
