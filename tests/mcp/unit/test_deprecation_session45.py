"""
Session 45 — Flask deprecation warnings and anyio migration tests.
====================================================================
Validates the architectural constraints introduced in session 45:

1. ``simple_server.py`` — hard Flask import made conditional; DeprecationWarning
   emitted on class instantiation and ``start_simple_server()``.
2. ``standalone_server.py`` — DeprecationWarning emitted on MinimalMCPServer,
   MinimalMCPDashboard, and main().
3. ``__main__.py`` — Flask fallback removed; ``--http`` emits DeprecationWarning.
4. ``executor.py`` — no "Fallback to asyncio" comments; anyio used throughout.
5. ``README.md`` / ``DUAL_RUNTIME_ARCHITECTURE.md`` — no ``asyncio.run(`` in
   code examples.

All tests are pure-unit; no actual servers are started.
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import sys
import warnings
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module root (for file-content tests)
# ---------------------------------------------------------------------------
MCP_ROOT = pathlib.Path(__file__).parents[3] / "ipfs_datasets_py" / "mcp_server"


# ===========================================================================
# 1 — simple_server.py: deprecation warnings
# ===========================================================================

class TestSimpleServerDeprecation:
    """simple_server.py emits DeprecationWarning on class/function use."""

    def _import_simple_server(self):
        """Import (or re-use already-imported) simple_server module."""
        mod_name = "ipfs_datasets_py.mcp_server.simple_server"
        if mod_name in sys.modules:
            return sys.modules[mod_name]
        return importlib.import_module(mod_name)

    def test_simple_server_class_emits_deprecation_warning(self):
        """SimpleIPFSDatasetsMCPServer.__init__ emits DeprecationWarning."""
        mod = self._import_simple_server()

        # Patch Flask inside the module so the constructor doesn't fail on
        # the Flask() call itself (we only care about the warning).
        fake_flask_app = MagicMock()
        fake_flask_cls = MagicMock(return_value=fake_flask_app)
        with patch.object(mod, "Flask", fake_flask_cls, create=True), \
             patch.object(mod, "FLASK_AVAILABLE", True, create=True):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                # Suppress the register_routes call so we don't need full Flask
                with patch.object(
                    mod.SimpleIPFSDatasetsMCPServer, "_register_routes", return_value=None
                ):
                    mod.SimpleIPFSDatasetsMCPServer()

        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert deprecations, "Expected at least one DeprecationWarning"
        assert any("SimpleIPFSDatasetsMCPServer" in str(w.message) or
                   "Flask" in str(w.message) or
                   "deprecated" in str(w.message).lower()
                   for w in deprecations)

    def test_start_simple_server_emits_deprecation_warning(self):
        """start_simple_server() emits DeprecationWarning."""
        mod = self._import_simple_server()

        fake_server = MagicMock()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with patch.object(mod, "load_config_from_yaml", return_value=MagicMock(), create=True), \
                 patch.object(mod, "SimpleIPFSDatasetsMCPServer", return_value=fake_server):
                try:
                    mod.start_simple_server()
                except Exception:
                    pass  # The function may fail after the warning; that's OK

        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert deprecations, "Expected at least one DeprecationWarning from start_simple_server()"

    def test_flask_unavailable_raises_import_error(self):
        """When Flask is unavailable, SimpleIPFSDatasetsMCPServer raises ImportError."""
        mod = self._import_simple_server()
        with patch.object(mod, "FLASK_AVAILABLE", False, create=True):
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                with pytest.raises(ImportError, match="Flask"):
                    mod.SimpleIPFSDatasetsMCPServer()

    def test_flask_import_is_conditional(self):
        """simple_server module can be imported even when Flask is absent."""
        # The module has already been imported; verify FLASK_AVAILABLE attribute exists
        mod = self._import_simple_server()
        assert hasattr(mod, "FLASK_AVAILABLE"), (
            "simple_server should expose FLASK_AVAILABLE after conditional import"
        )


# ===========================================================================
# 2 — standalone_server.py: deprecation warnings
# ===========================================================================

class TestStandaloneServerDeprecation:
    """standalone_server.py emits DeprecationWarning on class/function use."""

    def _import_standalone(self):
        mod_name = "ipfs_datasets_py.mcp_server.standalone_server"
        if mod_name in sys.modules:
            return sys.modules[mod_name]
        # Pre-inject Flask mock so module-level import succeeds
        if "flask" not in sys.modules:
            mock_flask = MagicMock()
            mock_flask.Flask = MagicMock(return_value=MagicMock())
            mock_flask.jsonify = MagicMock()
            mock_flask.request = MagicMock()
            sys.modules.setdefault("flask", mock_flask)
        return importlib.import_module(mod_name)

    def test_minimal_mcp_server_emits_deprecation(self):
        """MinimalMCPServer.__init__ emits DeprecationWarning."""
        mod = self._import_standalone()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                mod.MinimalMCPServer()
            except Exception:
                pass
        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert deprecations, "Expected DeprecationWarning from MinimalMCPServer()"
        assert any("MinimalMCPServer" in str(w.message) or
                   "deprecated" in str(w.message).lower()
                   for w in deprecations)

    def test_minimal_mcp_dashboard_emits_deprecation(self):
        """MinimalMCPDashboard.__init__ emits DeprecationWarning."""
        mod = self._import_standalone()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                mod.MinimalMCPDashboard()
            except Exception:
                pass
        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert deprecations, "Expected DeprecationWarning from MinimalMCPDashboard()"

    def test_standalone_main_emits_deprecation(self):
        """standalone_server.main() emits DeprecationWarning."""
        mod = self._import_standalone()
        fake_server = MagicMock()
        fake_dashboard = MagicMock()
        with warnings.catch_warnings(record=True) as caught, \
             patch.object(mod, "MinimalMCPServer", return_value=fake_server), \
             patch.object(mod, "MinimalMCPDashboard", return_value=fake_dashboard), \
             patch("sys.argv", ["standalone_server.py", "--server-only"]):
            warnings.simplefilter("always")
            # Prevent the inner MinimalMCPServer() from blocking via run()
            fake_server.run.side_effect = lambda: None
            try:
                mod.main()
            except Exception:
                pass
        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert deprecations, "Expected DeprecationWarning from standalone_server.main()"


# ===========================================================================
# 3 — __main__.py: Flask fallback removed, --http emits DeprecationWarning
# ===========================================================================

class TestMainModuleHttpDeprecation:
    """__main__.py --http mode emits DeprecationWarning; no Flask fallback."""

    def test_http_mode_emits_deprecation_warning(self):
        """--http flag triggers DeprecationWarning about deprecated HTTP mode."""
        mod_name = "ipfs_datasets_py.mcp_server.__main__"
        if mod_name in sys.modules:
            main_mod = sys.modules[mod_name]
        else:
            main_mod = importlib.import_module(mod_name)

        # Patch sys.argv to simulate --http
        fake_start_server = MagicMock(side_effect=RuntimeError("stop after warning"))
        with warnings.catch_warnings(record=True) as caught, \
             patch("sys.argv", ["ipfs_datasets_py.mcp_server", "--http"]), \
             patch("ipfs_datasets_py.mcp_server.start_server", fake_start_server, create=True), \
             patch("ipfs_datasets_py.mcp_server.start_stdio_server", MagicMock(), create=True), \
             patch("ipfs_datasets_py.mcp_server.configs", MagicMock(), create=True):
            warnings.simplefilter("always")
            try:
                main_mod.main()
            except (RuntimeError, SystemExit, Exception):
                pass  # stop after the warning has been issued

        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert deprecations, (
            "Expected a DeprecationWarning when --http is passed to __main__.main()"
        )
        warning_text = " ".join(str(w.message) for w in deprecations).lower()
        assert "http" in warning_text or "deprecated" in warning_text or "flask" in warning_text

    def test_no_simple_server_import_in_main(self):
        """__main__.py must not fall back to SimpleIPFSDatasetsMCPServer (Flask)."""
        main_src = (MCP_ROOT / "__main__.py").read_text()
        assert "SimpleIPFSDatasetsMCPServer" not in main_src, (
            "__main__.py still references SimpleIPFSDatasetsMCPServer — "
            "the Flask fallback must be removed"
        )


# ===========================================================================
# 4 — executor.py: no misleading "asyncio" comments; anyio used
# ===========================================================================

class TestExecutorAnyioComments:
    """executor.py uses anyio language throughout (no misleading 'asyncio' comments)."""

    def _executor_source(self) -> str:
        return (MCP_ROOT / "mcplusplus" / "executor.py").read_text()

    def test_no_fallback_to_asyncio_comment(self):
        """executor.py must not contain 'Fallback to asyncio' comments."""
        src = self._executor_source()
        assert "Fallback to asyncio" not in src, (
            "Found misleading 'Fallback to asyncio' comment in executor.py — "
            "replace with 'anyio fallback'"
        )

    def test_anyio_fallback_comment_present(self):
        """executor.py should say 'anyio fallback' (not asyncio)."""
        src = self._executor_source()
        assert "anyio fallback" in src, (
            "executor.py should have 'anyio fallback' comments where async "
            "execution falls back to anyio (not asyncio)"
        )

    def test_no_import_asyncio_in_executor(self):
        """executor.py must not import asyncio."""
        src = self._executor_source()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in getattr(node, "names", [])]
                module = getattr(node, "module", "") or ""
                assert "asyncio" not in names and not module.startswith("asyncio"), (
                    f"executor.py imports asyncio at line {node.lineno}"
                )


# ===========================================================================
# 5 — Documentation: README.md / DUAL_RUNTIME_ARCHITECTURE.md
# ===========================================================================

class TestDocumentationAnyio:
    """Key documentation files use anyio in code examples, not asyncio."""

    def test_readme_no_asyncio_run(self):
        """README.md code examples must not contain asyncio.run(."""
        readme = (MCP_ROOT / "README.md").read_text()
        # Find all fenced code blocks
        in_block = False
        violations: list[str] = []
        for i, line in enumerate(readme.splitlines(), 1):
            if line.strip().startswith("```"):
                in_block = not in_block
            elif in_block and "asyncio.run(" in line:
                violations.append(f"line {i}: {line.strip()}")
        assert not violations, (
            f"README.md still has asyncio.run() in code blocks: {violations}"
        )

    def test_readme_has_anyio_run(self):
        """README.md code examples should use anyio.run(."""
        readme = (MCP_ROOT / "README.md").read_text()
        assert "anyio.run(" in readme, (
            "README.md should use anyio.run() in code examples"
        )

    def test_dual_runtime_arch_no_asyncio_get_event_loop(self):
        """DUAL_RUNTIME_ARCHITECTURE.md must not use asyncio.get_event_loop()."""
        arch = (MCP_ROOT / "docs" / "architecture" / "DUAL_RUNTIME_ARCHITECTURE.md").read_text()
        in_block = False
        violations: list[str] = []
        for i, line in enumerate(arch.splitlines(), 1):
            if line.strip().startswith("```"):
                in_block = not in_block
            elif in_block and "asyncio.get_event_loop()" in line:
                violations.append(f"line {i}: {line.strip()}")
        assert not violations, (
            f"DUAL_RUNTIME_ARCHITECTURE.md still has asyncio.get_event_loop() in code blocks: {violations}"
        )

    def test_dual_runtime_arch_uses_anyio_import(self):
        """DUAL_RUNTIME_ARCHITECTURE.md code examples should import anyio."""
        arch = (MCP_ROOT / "docs" / "architecture" / "DUAL_RUNTIME_ARCHITECTURE.md").read_text()
        assert "import anyio" in arch, (
            "DUAL_RUNTIME_ARCHITECTURE.md should have 'import anyio' in code examples"
        )
