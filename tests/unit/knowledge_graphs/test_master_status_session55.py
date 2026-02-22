"""Session 55 – Verify numpy is a default (non-optional) dependency.

Checks that:
  * setup.py ``install_requires`` contains versioned numpy entries
  * ``pyproject.toml`` ``[project] dependencies`` contains numpy
  * ``requirements.txt`` contains numpy
  * The knowledge_graphs extras in setup.py do NOT duplicate numpy
    (it is now in the base deps)
  * numpy can actually be imported in this environment (since it is
    declared as a default dep)
"""

import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).parents[3]  # repo root

# How many characters of an extras block to scan for duplicate deps.
_EXTRAS_BLOCK_SIZE = 800
_TOML_EXTRAS_BLOCK_SIZE = 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(rel: str) -> str:
    return (ROOT / rel).read_text()


def _numpy_dep_lines(text: str) -> list[str]:
    """Return stripped non-comment lines that mention 'numpy'."""
    return [
        l.strip()
        for l in text.splitlines()
        if "numpy" in l and not l.strip().startswith("#")
    ]


# ---------------------------------------------------------------------------
# setup.py
# ---------------------------------------------------------------------------

class TestSetupPyNumpyDep:
    """numpy is in install_requires with proper version bounds."""

    def test_numpy_in_install_requires_lt_314(self):
        src = _read("setup.py")
        lines = _numpy_dep_lines(src)
        assert any(
            "numpy>=1.21.0" in l and "python_version < '3.14'" in l
            for l in lines
        ), f"Missing numpy<3.14 entry in setup.py install_requires; found: {lines}"

    def test_numpy_in_install_requires_gte_314(self):
        src = _read("setup.py")
        lines = _numpy_dep_lines(src)
        assert any(
            "numpy>=2.0.0" in l and "python_version >= '3.14'" in l
            for l in lines
        ), f"Missing numpy>=3.14 entry in setup.py install_requires; found: {lines}"

    def test_numpy_not_duplicated_in_knowledge_graphs_extras(self):
        src = _read("setup.py")
        # Isolate the knowledge_graphs block
        start = src.find("'knowledge_graphs'")
        assert start != -1, "knowledge_graphs extras block not found"
        block = src[start : start + _EXTRAS_BLOCK_SIZE]
        # numpy should not appear in the extras any more (moved to base deps)
        assert "numpy" not in block, (
            "numpy is still listed in knowledge_graphs extras — "
            "it should only appear in install_requires. Block: "
            + block[:300]
        )

    def test_setup_py_is_valid_python(self):
        import ast
        src = _read("setup.py")
        try:
            ast.parse(src)
        except SyntaxError as exc:
            pytest.fail(f"setup.py has a syntax error: {exc}")


# ---------------------------------------------------------------------------
# pyproject.toml
# ---------------------------------------------------------------------------

class TestPyprojectTomlNumpyDep:
    """pyproject.toml exists and declares numpy in [project] dependencies."""

    def test_pyproject_toml_exists(self):
        assert (ROOT / "pyproject.toml").exists(), "pyproject.toml not found in repo root"

    def test_numpy_in_project_dependencies_lt_314(self):
        toml = _read("pyproject.toml")
        lines = _numpy_dep_lines(toml)
        assert any(
            "numpy>=1.21.0" in l and "python_version < '3.14'" in l
            for l in lines
        ), f"Missing numpy<3.14 in pyproject.toml; found: {lines}"

    def test_numpy_in_project_dependencies_gte_314(self):
        toml = _read("pyproject.toml")
        lines = _numpy_dep_lines(toml)
        assert any(
            "numpy>=2.0.0" in l and "python_version >= '3.14'" in l
            for l in lines
        ), f"Missing numpy>=3.14 in pyproject.toml; found: {lines}"

    def test_pyproject_toml_has_build_system(self):
        toml = _read("pyproject.toml")
        assert "[build-system]" in toml, "pyproject.toml missing [build-system] table"
        assert "setuptools" in toml, "pyproject.toml missing setuptools build backend"

    def test_knowledge_graphs_extras_no_numpy_duplicate(self):
        toml = _read("pyproject.toml")
        start = toml.find("knowledge_graphs")
        if start == -1:
            return  # no knowledge_graphs extras in pyproject.toml — that's fine
        block = toml[start : start + _TOML_EXTRAS_BLOCK_SIZE]
        assert "numpy" not in block, (
            "numpy is duplicated in pyproject.toml knowledge_graphs extras"
        )


# ---------------------------------------------------------------------------
# requirements.txt
# ---------------------------------------------------------------------------

class TestRequirementsTxtNumpyDep:
    """requirements.txt has matching numpy entries."""

    def test_numpy_in_requirements_lt_314(self):
        reqs = _read("requirements.txt")
        numpy_lines = [l for l in reqs.splitlines() if l.startswith("numpy")]
        assert any(
            "python_version < '3.14'" in l for l in numpy_lines
        ), f"Missing numpy<3.14 in requirements.txt; found: {numpy_lines}"

    def test_numpy_in_requirements_gte_314(self):
        reqs = _read("requirements.txt")
        numpy_lines = [l for l in reqs.splitlines() if l.startswith("numpy")]
        assert any(
            "python_version >= '3.14'" in l for l in numpy_lines
        ), f"Missing numpy>=3.14 in requirements.txt; found: {numpy_lines}"


# ---------------------------------------------------------------------------
# Consistency
# ---------------------------------------------------------------------------

class TestNumpyVersionConsistency:
    """Version bounds are consistent across all three files."""

    def test_lower_bound_consistent(self):
        """All files use numpy>=1.21.0 as the Python<3.14 lower bound."""
        setup_lines = _numpy_dep_lines(_read("setup.py"))
        toml_lines = _numpy_dep_lines(_read("pyproject.toml"))
        req_lines = [l for l in _read("requirements.txt").splitlines() if "numpy" in l]
        for src_name, lines in [
            ("setup.py", setup_lines),
            ("pyproject.toml", toml_lines),
            ("requirements.txt", req_lines),
        ]:
            lt_line = next(
                (l for l in lines if "python_version < '3.14'" in l), None
            )
            assert lt_line is not None, f"{src_name}: missing python_version < '3.14' numpy entry"
            assert "numpy>=1.21.0" in lt_line, (
                f"{src_name}: python<3.14 entry should use numpy>=1.21.0; got: {lt_line}"
            )

    def test_numpy_importable(self):
        """Since numpy is now a default dep, it must be importable."""
        try:
            import numpy as np  # noqa: F401
        except ImportError:
            pytest.fail(
                "numpy is not importable even though it is a declared default dependency. "
                "Run: pip install -e . (or pip install numpy)"
            )
