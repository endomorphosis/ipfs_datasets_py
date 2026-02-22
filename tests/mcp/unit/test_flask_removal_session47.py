"""
Session 47 — Phases M2/M3/O4 completion tests.

Verifies that:
- requirements-docker.txt no longer contains Flask (M3)
- Dockerfile.simple uses python -m ipfs_datasets_py.mcp_server (O4/M2)
- Dockerfile.simple no longer EXPOSEs HTTP ports 8000/8080 (O4)
- start_simple_server.sh no longer calls simple_server (M2)
- start_simple_server.sh uses python -m ipfs_datasets_py.mcp_server (M2)
- simple_server.py has the TODO removal comment (M2)
"""

import pathlib

MCP_ROOT = pathlib.Path(__file__).parents[3] / "ipfs_datasets_py" / "mcp_server"


class TestRequirementsDockerFlaskRemoved:
    """Phase M3: Flask must be absent from requirements-docker.txt."""

    def test_flask_not_in_requirements_docker(self):
        txt = (MCP_ROOT / "requirements-docker.txt").read_text()
        assert "Flask" not in txt, "Flask is still listed in requirements-docker.txt"
        assert "flask" not in txt.lower(), "Flask (lowercase) still in requirements-docker.txt"

    def test_anyio_present_in_requirements_docker(self):
        txt = (MCP_ROOT / "requirements-docker.txt").read_text()
        assert "anyio" in txt, "anyio should be listed in requirements-docker.txt"

    def test_mcp_present_in_requirements_docker(self):
        txt = (MCP_ROOT / "requirements-docker.txt").read_text()
        assert "mcp" in txt.lower(), "mcp package should still be listed"


class TestDockerfileSimpleFlaskRemoved:
    """Phase M2/O4: Dockerfile.simple must not expose HTTP ports and must use MCP stdio."""

    def test_no_expose_8000(self):
        txt = (MCP_ROOT / "Dockerfile.simple").read_text()
        assert "EXPOSE 8000" not in txt, "Dockerfile.simple still EXPOSEs port 8000"

    def test_no_expose_8080(self):
        txt = (MCP_ROOT / "Dockerfile.simple").read_text()
        assert "EXPOSE 8080" not in txt, "Dockerfile.simple still EXPOSEs port 8080"

    def test_cmd_uses_mcp_server_module(self):
        txt = (MCP_ROOT / "Dockerfile.simple").read_text()
        # The CMD must launch the MCP stdio server, not a Flask app
        assert "python -m ipfs_datasets_py.mcp_server" in txt or \
               'CMD ["python", "-m", "ipfs_datasets_py.mcp_server"]' in txt, \
               "Dockerfile.simple CMD should use python -m ipfs_datasets_py.mcp_server"

    def test_no_flask_reference(self):
        txt = (MCP_ROOT / "Dockerfile.simple").read_text()
        assert "flask" not in txt.lower(), "Dockerfile.simple still references flask"

    def test_process_based_healthcheck_present(self):
        txt = (MCP_ROOT / "Dockerfile.simple").read_text()
        assert "HEALTHCHECK" in txt, "HEALTHCHECK should be present"
        # Should NOT use HTTP curl
        assert "curl -f http" not in txt, "HEALTHCHECK should not use HTTP curl"


class TestStartSimpleServerShellScript:
    """Phase M2: start_simple_server.sh must no longer invoke Flask simple_server."""

    def test_no_flask_simple_server_call(self):
        txt = (MCP_ROOT / "start_simple_server.sh").read_text()
        # The specific Flask invocation must be gone
        assert "from ipfs_datasets_py.mcp_server.simple_server import start_simple_server" not in txt, \
               "start_simple_server.sh still contains the Flask invocation"
        assert "import start_simple_server" not in txt, \
               "start_simple_server.sh still imports start_simple_server"

    def test_uses_mcp_stdio_module(self):
        txt = (MCP_ROOT / "start_simple_server.sh").read_text()
        assert "python -m ipfs_datasets_py.mcp_server" in txt, \
               "start_simple_server.sh should use python -m ipfs_datasets_py.mcp_server"

    def test_has_deprecation_notice(self):
        txt = (MCP_ROOT / "start_simple_server.sh").read_text()
        assert "DEPRECATED" in txt or "deprecated" in txt.lower(), \
               "start_simple_server.sh should note that Flask mode is deprecated"


class TestSimpleServerTodoComment:
    """Phase M2: simple_server.py must have the removal TODO comment."""

    def test_todo_remove_comment_present(self):
        txt = (MCP_ROOT / "simple_server.py").read_text()
        assert "TODO: remove in v2.0" in txt, \
               "simple_server.py is missing the '# TODO: remove in v2.0' comment"

    def test_deprecation_warning_in_module_docstring(self):
        txt = (MCP_ROOT / "simple_server.py").read_text()
        assert "deprecated" in txt.lower(), \
               "simple_server.py module docstring should mention deprecation"
