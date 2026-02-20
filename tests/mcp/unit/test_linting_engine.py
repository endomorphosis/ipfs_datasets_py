"""
Tests for linting_engine.py — Phase 5 core module extraction.

Validates that LintIssue, LintResult, PythonLinter, and DatasetLinter
work correctly after being extracted from linting_tools.py.
"""
import tempfile
from pathlib import Path
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def python_linter():
    from ipfs_datasets_py.mcp_server.tools.development_tools.linting_engine import PythonLinter
    return PythonLinter()


@pytest.fixture
def dataset_linter():
    from ipfs_datasets_py.mcp_server.tools.development_tools.linting_engine import DatasetLinter
    return DatasetLinter()


@pytest.fixture
def tmp_py_file():
    """Create a temporary Python file for tests."""
    with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False) as f:
        f.write("x = 1  \n")      # trailing whitespace
        f.write("y = 2\n")
        name = f.name
    yield Path(name)
    Path(name).unlink(missing_ok=True)


@pytest.fixture
def clean_py_file():
    """A clean Python file with no issues."""
    with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False) as f:
        f.write("x = 1\n")
        f.write("y = 2\n")
        name = f.name
    yield Path(name)
    Path(name).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# TestLintIssue
# ---------------------------------------------------------------------------

class TestLintIssue:
    """Tests for the LintIssue dataclass."""

    def test_lint_issue_construction(self):
        """
        GIVEN: Fields for a linting issue
        WHEN: Constructing a LintIssue
        THEN: All attributes are set correctly
        """
        from ipfs_datasets_py.mcp_server.tools.development_tools.linting_engine import LintIssue

        issue = LintIssue(
            file_path="myfile.py",
            line_number=10,
            column=5,
            rule_id="W291",
            severity="warning",
            message="Trailing whitespace",
            fix_suggestion="Remove trailing whitespace",
        )

        assert issue.file_path == "myfile.py"
        assert issue.line_number == 10
        assert issue.column == 5
        assert issue.rule_id == "W291"
        assert issue.severity == "warning"
        assert issue.fix_suggestion == "Remove trailing whitespace"

    def test_lint_issue_optional_fix_suggestion(self):
        """
        GIVEN: LintIssue without fix_suggestion
        WHEN: Constructing
        THEN: fix_suggestion defaults to None
        """
        from ipfs_datasets_py.mcp_server.tools.development_tools.linting_engine import LintIssue

        issue = LintIssue(
            file_path="f.py", line_number=1, column=None,
            rule_id="E101", severity="error", message="Indentation error",
        )
        assert issue.fix_suggestion is None


# ---------------------------------------------------------------------------
# TestLintResult
# ---------------------------------------------------------------------------

class TestLintResult:
    """Tests for the LintResult dataclass."""

    def test_lint_result_construction(self):
        """
        GIVEN: Fields for a lint result
        WHEN: Constructing a LintResult
        THEN: All attributes are set correctly
        """
        from ipfs_datasets_py.mcp_server.tools.development_tools.linting_engine import LintResult

        result = LintResult(
            total_files=3,
            issues_found=5,
            issues_fixed=2,
            files_modified=["a.py", "b.py"],
            issues=[],
            summary={"errors": 1, "warnings": 4},
        )

        assert result.total_files == 3
        assert result.issues_found == 5
        assert result.issues_fixed == 2
        assert len(result.files_modified) == 2


# ---------------------------------------------------------------------------
# TestPythonLinter
# ---------------------------------------------------------------------------

class TestPythonLinter:
    """Tests for PythonLinter core class."""

    def test_lint_file_detects_trailing_whitespace(self, python_linter, tmp_py_file):
        """
        GIVEN: A Python file with trailing whitespace
        WHEN: Linting with fix_issues=True (detection + fix combined)
        THEN: Returns a LintResult with W291 issue
        """
        tmp_py_file.write_text("x = 1   \ny = 2\n")

        result = python_linter.lint_file(tmp_py_file, fix_issues=True)

        assert result.total_files == 1
        rule_ids = [i.rule_id for i in result.issues]
        assert "W291" in rule_ids

    def test_lint_file_fixes_trailing_whitespace(self, python_linter, tmp_py_file):
        """
        GIVEN: A Python file with trailing whitespace
        WHEN: Linting with fix_issues=True
        THEN: File is modified on disk and fix is reported
        """
        tmp_py_file.write_text("x = 1   \ny = 2\n")

        result = python_linter.lint_file(tmp_py_file, fix_issues=True)

        # File should have been modified
        assert str(tmp_py_file) in result.files_modified
        # Content should have no trailing whitespace
        content = tmp_py_file.read_text()
        for line in content.splitlines():
            assert line == line.rstrip()

    def test_lint_clean_file_no_issues(self, python_linter, clean_py_file):
        """
        GIVEN: A clean Python file
        WHEN: Linting
        THEN: No basic formatting issues
        """
        result = python_linter.lint_file(clean_py_file, fix_issues=False)

        basic_rule_ids = {i.rule_id for i in result.issues
                         if i.rule_id in ("W291", "W292", "W293")}
        assert len(basic_rule_ids) == 0

    def test_lint_detects_missing_final_newline(self, python_linter):
        """
        GIVEN: A Python file without a final newline
        WHEN: Linting with fix_issues=True (detection + fix combined)
        THEN: Returns a W292 issue
        """
        with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False) as f:
            f.write("x = 1")  # no trailing newline
            path = Path(f.name)

        try:
            result = python_linter.lint_file(path, fix_issues=True)
            rule_ids = [i.rule_id for i in result.issues]
            assert "W292" in rule_ids
        finally:
            path.unlink(missing_ok=True)

    def test_create_summary_structure(self, python_linter):
        """
        GIVEN: A list of LintIssue objects
        WHEN: create_summary() is called
        THEN: Returns dict with expected keys
        """
        from ipfs_datasets_py.mcp_server.tools.development_tools.linting_engine import LintIssue

        issues = [
            LintIssue("f.py", 1, 1, "W291", "warning", "trailing ws"),
            LintIssue("f.py", 2, 1, "E101", "error", "indent"),
        ]
        summary = python_linter.create_summary(issues)

        assert "total_issues" in summary
        assert summary["total_issues"] == 2
        assert summary["errors"] == 1
        assert summary["warnings"] == 1
        assert "rules_triggered" in summary

    def test_lint_nonexistent_file_returns_empty_result(self, python_linter):
        """
        GIVEN: A path that does not exist
        WHEN: lint_file() is called
        THEN: Returns a LintResult with error in summary (no crash)
        """
        result = python_linter.lint_file(Path("/nonexistent_path/file.py"), fix_issues=False)

        assert result.total_files == 1
        assert result.issues_found == 0
        assert "error" in result.summary


# ---------------------------------------------------------------------------
# TestDatasetLinter
# ---------------------------------------------------------------------------

class TestDatasetLinter:
    """Tests for DatasetLinter core class."""

    def test_dataset_linter_detects_hardcoded_ipfs_hash(self, dataset_linter):
        """
        GIVEN: A Python file with a hard-coded IPFS hash
        WHEN: lint_dataset_code() is called
        THEN: Returns DS002 issue
        """
        with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False) as f:
            f.write('cid = "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG"\n')
            path = Path(f.name)

        try:
            issues = dataset_linter.lint_dataset_code(path)
            rule_ids = [i.rule_id for i in issues]
            assert "DS002" in rule_ids
        finally:
            path.unlink(missing_ok=True)

    def test_dataset_linter_clean_file_no_issues(self, dataset_linter):
        """
        GIVEN: A clean Python file with no dataset operations
        WHEN: lint_dataset_code() is called
        THEN: Returns no issues
        """
        with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False) as f:
            f.write("def add(a, b):\n    return a + b\n")
            path = Path(f.name)

        try:
            issues = dataset_linter.lint_dataset_code(path)
            assert issues == []
        finally:
            path.unlink(missing_ok=True)

    def test_dataset_linter_no_issue_with_error_handling(self, dataset_linter):
        """
        GIVEN: Python file with load_dataset inside a try/except
        WHEN: lint_dataset_code() is called
        THEN: No DS001 issue returned
        """
        with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False) as f:
            f.write(
                "try:\n"
                "    ds = obj.load_dataset('squad')\n"
                "except Exception as e:\n"
                "    pass\n"
            )
            path = Path(f.name)

        try:
            issues = dataset_linter.lint_dataset_code(path)
            rule_ids = [i.rule_id for i in issues]
            assert "DS001" not in rule_ids
        finally:
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# TestLintingEngineImports (Phase 5 backward compatibility)
# ---------------------------------------------------------------------------

class TestLintingEngineImports:
    """Verify backward-compatible imports from linting_tools still work."""

    def test_lint_issue_importable_from_tools(self):
        """
        GIVEN: Old import path (linting_tools)
        WHEN: Importing LintIssue from linting_tools
        THEN: Import succeeds (backward compatibility)
        """
        from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import LintIssue
        assert LintIssue is not None

    def test_python_linter_importable_from_tools(self):
        """
        GIVEN: Old import path (linting_tools)
        WHEN: Importing PythonLinter from linting_tools
        THEN: Import succeeds (backward compatibility)
        """
        from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import PythonLinter
        assert PythonLinter is not None

    def test_dataset_linter_importable_from_tools(self):
        """
        GIVEN: Old import path (linting_tools)
        WHEN: Importing DatasetLinter from linting_tools
        THEN: Import succeeds (backward compatibility)
        """
        from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import DatasetLinter
        assert DatasetLinter is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
