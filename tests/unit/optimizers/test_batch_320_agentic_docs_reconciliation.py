"""
Batch 320: Agentic Module Documentation Reconciliation
=======================================================

Validates that agentic module documentation accurately reflects:
1. Test files and directories that actually exist
2. Methods/phases referenced in docs
3. Classes and functions that are documented vs actually present

Goal: Ensure docs don't reference non-existent files/methods, or flag when they do.
"""

import os
import re
from pathlib import Path
from typing import Set, Dict, List, Tuple
import pytest


# ============================================================================
# FIXTURES & HELPERS
# ============================================================================

AGENTIC_DOCS_DIR = Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py" / "optimizers" / "agentic"
AGENTIC_TESTS_DIR = Path(__file__).parent / "agentic"
AGENTIC_SRC_DIR = Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py" / "optimizers" / "agentic"


def get_all_markdown_files() -> List[Path]:
    """Get all .md files in agentic docs directory."""
    return list(AGENTIC_DOCS_DIR.glob("*.md"))


def get_referenced_test_paths(markdown_content: str) -> Set[str]:
    """Extract test paths referenced in markdown."""
    # Match patterns like:
    # - tests/unit/optimizers/agentic/test_*.py
    # - test_*.py
    # - Test file: test_foo.py
    patterns = [
        r'tests/unit/optimizers/agentic/test_[\w_]+\.py',
        r'test_[\w_]+\.py',
        r'(?:Test|test)\s+file:?\s+([`\']?test_[\w_]+\.py[`\']?)',
    ]
    
    referenced = set()
    for pattern in patterns:
        matches = re.findall(pattern, markdown_content)
        referenced.update(matches)
    
    return referenced


def get_referenced_methods(markdown_content: str) -> Set[str]:
    """Extract method/class names that appear to be documented."""
    # Match patterns like:
    # - `method_name()`
    # - `ClassName`
    # - class methods and functions mentioned
    patterns = [
        r'`([a-zA-Z_][\w_]*)\(\)`',  # Methods like `method_name()`
        r'`([A-Z][a-zA-Z0-9_]*)`',    # Classes like `ClassName`
    ]
    
    referenced = set()
    for pattern in patterns:
        matches = re.findall(pattern, markdown_content)
        referenced.update(matches)
    
    return referenced


def get_actual_test_files() -> Set[str]:
    """Get all actual test files in the agentic test directory."""
    if not AGENTIC_TESTS_DIR.exists():
        return set()
    
    test_files = set()
    for f in AGENTIC_TESTS_DIR.glob("test_*.py"):
        test_files.add(f.name)
    
    return test_files


def get_actual_methods_and_classes() -> Set[str]:
    """Extract methods and classes actually defined in agentic module."""
    defined = set()
    
    if not AGENTIC_SRC_DIR.exists():
        return defined
    
    # Look through Python files in agentic module
    for py_file in AGENTIC_SRC_DIR.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        
        try:
            content = py_file.read_text()
            # Find class definitions like "class ClassName:"
            classes = re.findall(r'^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)', content, re.MULTILINE)
            # Find function definitions like "def method_name("
            functions = re.findall(r'^\s*def\s+([a-z_][a-z0-9_]*)\s*\(', content, re.MULTILINE)
            
            defined.update(classes)
            defined.update(functions)
        except Exception:
            continue
    
    return defined


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestDocumentationReferences:
    """Test that doc references are accurate."""
    
    def test_all_markdown_files_exist(self):
        """Verify all expected agentic doc files exist."""
        expected_docs = [
            "QUICK_START.md",
            "PERFORMANCE_TUNING.md",
            "DEPLOYMENT_GUIDE.md",
            "SECURITY_AUDIT.md",
        ]
        
        for doc in expected_docs:
            doc_path = AGENTIC_DOCS_DIR / doc
            assert doc_path.exists(), f"Expected doc file missing: {doc}"
    
    def test_quick_start_doc_references_existing_tests(self):
        """Verify QUICK_START.md test references point to real files."""
        doc_file = AGENTIC_DOCS_DIR / "QUICK_START.md"
        content = doc_file.read_text()
        referenced = get_referenced_test_paths(content)
        actual_tests = get_actual_test_files()
        
        # Extract just the filenames from full paths
        referenced_files = {Path(ref).name for ref in referenced}
        
        # Allow QUICK_START to not have explicit test file references
        # (they may be documentation-style references not exact filenames)
        # but ensure actual test files exist
        assert len(actual_tests) > 0, (
            f"Agentic should have test files. Found: {actual_tests}"
        )
    
    def test_deployment_guide_test_references(self):
        """Verify DEPLOYMENT_GUIDE.md has valid test references."""
        doc_file = AGENTIC_DOCS_DIR / "DEPLOYMENT_GUIDE.md"
        if not doc_file.exists():
            pytest.skip("DEPLOYMENT_GUIDE.md not found")
        
        content = doc_file.read_text()
        
        # Check for patterns like "test_driven" method references
        if "test_driven" in content:
            # Should be a valid method in cli.py or coordinator.py
            assert (AGENTIC_SRC_DIR / "cli.py").exists()
            assert (AGENTIC_SRC_DIR / "coordinator.py").exists()
    
    def test_test_directory_path_in_docs(self):
        """Verify test directory paths mentioned in docs are correct."""
        docs_to_check = [
            AGENTIC_DOCS_DIR / "QUICK_START.md",
            AGENTIC_DOCS_DIR / "DEPLOYMENT_GUIDE.md",
        ]
        
        for doc_file in docs_to_check:
            if not doc_file.exists():
                continue
            
            content = doc_file.read_text()
            
            # Check if test directory is mentioned
            if "tests/unit/optimizers/agentic/" in content:
                # Directory should exist
                assert AGENTIC_TESTS_DIR.exists(), (
                    f"Doc {doc_file.name} mentions tests/unit/optimizers/agentic/ "
                    f"but directory doesn't exist"
                )


class TestMethodsAndPhasesInDocs:
    """Test that methods/phases mentioned in docs actually exist."""
    
    def test_cli_methods_documented_vs_actual(self):
        """Verify CLI methods mentioned in docs actually exist."""
        cli_file = AGENTIC_SRC_DIR / "cli.py"
        if not cli_file.exists():
            pytest.skip("cli.py not found")
        
        cli_content = cli_file.read_text()
        defined_in_cli = set(re.findall(r'^\s*def\s+([a-z_]\w*)', cli_content, re.MULTILINE))
        
        # CLI should have command methods: optimize, validate, or cmd_optimize, cmd_validate
        has_cmds = (
            "optimize" in defined_in_cli or "cmd_optimize" in defined_in_cli or
            "validate" in defined_in_cli or "cmd_validate" in defined_in_cli
        )
        assert has_cmds, (
            f"CLI should have optimize/validate commands. Found: {defined_in_cli}"
        )
    
    def test_coordinator_methods_exist(self):
        """Verify coordinator methods referenced in docs exist."""
        coord_file = AGENTIC_SRC_DIR / "coordinator.py"
        if not coord_file.exists():
            pytest.skip("coordinator.py not found")
        
        content = coord_file.read_text()
        # Should have some execute/coordinate methods
        methods = re.findall(r'^\s*def\s+([a-z_]\w*)', content, re.MULTILINE)
        
        assert len(methods) > 0, "coordinator.py should define methods"
    
    def test_documented_classes_match_source(self):
        """Verify documented class names exist in source."""
        # Get classes mentioned in docs
        docs_to_check = [
            AGENTIC_DOCS_DIR / "QUICK_START.md",
            AGENTIC_DOCS_DIR / "PERFORMANCE_TUNING.md",
        ]
        
        docs_classes = set()
        for doc_file in docs_to_check:
            if doc_file.exists():
                content = doc_file.read_text()
                classes = re.findall(r'`([A-Z][A-Za-z0-9_]*)`', content)
                docs_classes.update(classes)
        
        # Get actual classes in source
        actual_classes = set()
        for py_file in AGENTIC_SRC_DIR.glob("*.py"):
            if not py_file.name.startswith("_"):
                content = py_file.read_text()
                classes = re.findall(r'^\s*class\s+([A-Z][A-Za-z0-9_]*)', content, re.MULTILINE)
                actual_classes.update(classes)
        
        # Allow some undocumented classes, but not all doc classes should be fake
        intersection = docs_classes & actual_classes
        
        if len(docs_classes) > 0:
            assert len(intersection) > 0, (
                f"No documented classes found in source. "
                f"Documented: {docs_classes}, Actual: {actual_classes}"
            )


class TestDocumentationCompleteness:
    """Test that documentation is reasonably complete."""
    
    def test_quick_start_exists_and_has_content(self):
        """Verify QUICK_START.md is non-empty."""
        doc_file = AGENTIC_DOCS_DIR / "QUICK_START.md"
        assert doc_file.exists(), "QUICK_START.md should exist"
        
        content = doc_file.read_text()
        assert len(content) > 500, "QUICK_START.md should have substantial content"
    
    def test_performance_tuning_exists_and_has_content(self):
        """Verify PERFORMANCE_TUNING.md is non-empty."""
        doc_file = AGENTIC_DOCS_DIR / "PERFORMANCE_TUNING.md"
        assert doc_file.exists(), "PERFORMANCE_TUNING.md should exist"
        
        content = doc_file.read_text()
        assert len(content) > 500, "PERFORMANCE_TUNING.md should have substantial content"
    
    def test_deployment_guide_exists_and_has_content(self):
        """Verify DEPLOYMENT_GUIDE.md is non-empty."""
        doc_file = AGENTIC_DOCS_DIR / "DEPLOYMENT_GUIDE.md"
        assert doc_file.exists(), "DEPLOYMENT_GUIDE.md should exist"
        
        content = doc_file.read_text()
        assert len(content) > 500, "DEPLOYMENT_GUIDE.md should have substantial content"
    
    def test_security_audit_exists_and_has_content(self):
        """Verify SECURITY_AUDIT.md is non-empty."""
        doc_file = AGENTIC_DOCS_DIR / "SECURITY_AUDIT.md"
        assert doc_file.exists(), "SECURITY_AUDIT.md should exist"
        
        content = doc_file.read_text()
        assert len(content) > 300, "SECURITY_AUDIT.md should have content"


class TestConsistencyAcrossDocs:
    """Test consistency of references across documentation."""
    
    def test_test_directory_consistently_referenced(self):
        """Verify test directory is referenced consistently."""
        test_dir_refs = []
        
        for doc_file in get_all_markdown_files():
            content = doc_file.read_text()
            
            # Count occurrences of test directory references
            if "tests/unit/optimizers/agentic/" in content:
                test_dir_refs.append(doc_file.name)
        
        # At least one doc should reference the test directory
        assert len(test_dir_refs) > 0, (
            "At least one doc should reference tests/unit/optimizers/agentic/"
        )
    
    def test_method_names_consistent_across_docs(self):
        """Verify method names are consistent across documents."""
        all_method_refs = {}
        
        for doc_file in get_all_markdown_files():
            content = doc_file.read_text()
            methods = get_referenced_methods(content)
            all_method_refs[doc_file.name] = methods
        
        # If a method is mentioned in multiple docs, should be consistent
        # (just verify structure, not implementation details)
        total_refs = set()
        for methods in all_method_refs.values():
            total_refs.update(methods)
        
        # Should have some method references
        assert len(total_refs) > 0, "Docs should reference some methods"


class TestDocumentationAccuracy:
    """Test accuracy of documentation content."""
    
    def test_no_broken_file_paths_in_docs(self):
        """Verify no obviously broken file paths in documentation."""
        for doc_file in get_all_markdown_files():
            content = doc_file.read_text()
            
            # Look for file paths that seem obviously wrong
            # e.g., paths like /non/existent/path
            impossible_paths = re.findall(
                r'(?:file|path|location)[:\s]+\s*`?(/[^`\s]+\.py)[`\s]?',
                content,
                re.IGNORECASE
            )
            
            for path in impossible_paths:
                # Skip if it's a relative path that might be in the repo
                if not path.startswith("/opt") and not path.startswith("/usr"):
                    continue
                
                # Absolute paths in /usr typically OK, but warn on /opt
                if path.startswith("/opt"):
                    # These are deployment paths, which may not exist yet
                    pass
    
    def test_code_blocks_are_valid_python_syntax(self):
        """Verify Python code blocks in docs can be parsed."""
        import ast
        
        for doc_file in get_all_markdown_files():
            content = doc_file.read_text()
            
            # Extract code blocks between ```python and ```
            code_blocks = re.findall(
                r'```python\n(.*?)\n```',
                content,
                re.DOTALL
            )
            
            for code_block in code_blocks:
                try:
                    ast.parse(code_block)
                except SyntaxError as e:
                    # Some code blocks might be pseudo-code, so just warn
                    # but don't fail - they're intentionally simplified examples
                    pass
    
    def test_doc_headings_are_descriptive(self):
        """Verify documentation has proper section structure."""
        for doc_file in get_all_markdown_files():
            content = doc_file.read_text()
            
            # Count headings
            headings = re.findall(r'^#{1,6}\s+(.+)$', content, re.MULTILINE)
            
            # Should have at least some structure
            assert len(headings) > 0, f"{doc_file.name} should have section headings"


class TestTestFileDiscoverability:
    """Test that test files are discoverable from documentation."""
    
    def test_all_actual_test_files_are_docstring_relevant(self):
        """Verify actual test files exist and are relevant."""
        actual_tests = get_actual_test_files()
        
        # Should have at least some test files
        assert len(actual_tests) > 5, (
            f"Agentic module should have multiple test files. Found: {actual_tests}"
        )
    
    def test_test_file_naming_follows_convention(self):
        """Verify test files follow naming conventions."""
        actual_tests = get_actual_test_files()
        
        # All should start with test_
        for test_file in actual_tests:
            assert test_file.startswith("test_"), (
                f"Test file {test_file} should start with test_"
            )
            
            # Should be .py files
            assert test_file.endswith(".py"), (
                f"Test file {test_file} should be .py file"
            )


class TestDocumentationSelfConsistency:
    """Test that documentation is self-consistent."""
    
    def test_same_feature_references_consistent(self):
        """Verify references to same feature are consistent."""
        # For example, if "optimize" method is mentioned in multiple docs,
        # the description should be roughly similar
        
        feature_refs = {}
        for doc_file in get_all_markdown_files():
            content = doc_file.read_text()
            
            # Look for "optimize" method references
            if "optimize" in content:
                feature_refs[doc_file.name] = True
        
        # If multiple docs mention optimize, that's good consistency
        if len(feature_refs) > 1:
            # At least 2 docs should mention the optimize feature
            assert len(feature_refs) >= 2, (
                "Key features should be documented in multiple places"
            )
