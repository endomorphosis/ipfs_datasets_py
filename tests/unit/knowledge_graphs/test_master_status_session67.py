"""
Session 67 doc integrity tests.

Validates the fixes applied to:
- tests/knowledge_graphs/TEST_STATUS.md  (stale v2.0.0 metrics → v3.22.21)
- tests/knowledge_graphs/TEST_GUIDE.md   (stale metrics, broken links, stale coverage table)
- archive/README.md                       (**NEW** tag removed; IMPLEMENTATION_STATUS.md link fixed)
- MASTER_REFACTORING_PLAN_2026.md        (session 63→66; 3,782→3,856+; 95→108+; Doc Version 1.0→3.22.21)
- DOCUMENTATION_GUIDE.md                 (TEST_GUIDE.md TODO ticked [x])
"""

import pathlib
import pytest

_KG = pathlib.Path(__file__).parents[3] / "ipfs_datasets_py" / "knowledge_graphs"
_TESTS_KG = pathlib.Path(__file__).parents[3] / "tests" / "knowledge_graphs"

_TEST_STATUS = _TESTS_KG / "TEST_STATUS.md"
_TEST_GUIDE = _TESTS_KG / "TEST_GUIDE.md"
_ARCHIVE_README = _KG / "archive" / "README.md"
_REFACTORING_PLAN = _KG / "MASTER_REFACTORING_PLAN_2026.md"
_DOC_GUIDE = _KG / "DOCUMENTATION_GUIDE.md"
_MASTER_STATUS = _KG / "MASTER_STATUS.md"
_CHANGELOG = _KG / "CHANGELOG_KNOWLEDGE_GRAPHS.md"
_ROADMAP = _KG / "ROADMAP.md"


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TEST_STATUS.md — stale metrics fixed
# ---------------------------------------------------------------------------
class TestTestStatusMdUpdated:
    """TEST_STATUS.md: stale v2.0.0 metrics replaced with v3.22.21 metrics."""

    def test_module_version_updated(self):
        """Module Version header must say 3.22.21, not stale 2.0.0."""
        content = _read(_TEST_STATUS)
        assert "3.22.21" in content, "TEST_STATUS.md must show Module Version 3.22.21"
        assert "Module Version:** 2.0.0" not in content, "Stale v2.0.0 header must be gone"

    def test_coverage_updated(self):
        """Coverage must show 99.99%, not stale ~75%."""
        content = _read(_TEST_STATUS)
        assert "99.99%" in content, "TEST_STATUS.md must show 99.99% coverage"
        assert "~75%" not in content, "Stale ~75% coverage must be gone"

    def test_test_count_updated(self):
        """Test count must mention 3,856+, not stale 647+."""
        content = _read(_TEST_STATUS)
        assert "3,856+" in content, "TEST_STATUS.md must show 3,856+ tests"
        assert "647+" not in content, "Stale 647+ test count must be gone"

    def test_test_files_updated(self):
        """Test file count must be 108+, not stale 47."""
        content = _read(_TEST_STATUS)
        assert "108+" in content, "TEST_STATUS.md must mention 108+ test files"

    def test_migration_coverage_updated(self):
        """Migration coverage must be 100%, not stale ~40%."""
        content = _read(_TEST_STATUS)
        assert "~40%" not in content, "Stale ~40% migration coverage must be gone"

    def test_broken_link_fixed(self):
        """IMPLEMENTATION_STATUS.md link in See Also must be replaced with MASTER_STATUS.md."""
        content = _read(_TEST_STATUS)
        assert "IMPLEMENTATION_STATUS.md" not in content, \
            "Stale IMPLEMENTATION_STATUS.md link must be removed from TEST_STATUS.md"


# ---------------------------------------------------------------------------
# TEST_GUIDE.md — stale metrics + links fixed
# ---------------------------------------------------------------------------
class TestTestGuideMdUpdated:
    """TEST_GUIDE.md: stale v2.0.0 metrics and broken links replaced."""

    def test_overview_test_count_updated(self):
        """Overview paragraph must say 3,856+ tests, not 116+."""
        content = _read(_TEST_GUIDE)
        assert "3,856+" in content, "TEST_GUIDE.md overview must say 3,856+ tests"
        assert "116+ tests" not in content, "Stale 116+ tests must be removed from overview"

    def test_overview_coverage_updated(self):
        """Overview must say 99.99% coverage, not 75%."""
        content = _read(_TEST_GUIDE)
        assert "99.99%" in content, "TEST_GUIDE.md must show 99.99% coverage"
        assert "75% coverage" not in content, "Stale 75% coverage must be gone"

    def test_coverage_table_migration_row_updated(self):
        """Coverage table Migration row must show 100%, not 40%."""
        content = _read(_TEST_GUIDE)
        assert "40%" not in content, "Stale 40% migration coverage must be gone from TEST_GUIDE.md"

    def test_stale_not_implemented_notes_removed(self):
        """Stale 'not yet implemented - v2.1.0' notes must be removed."""
        content = _read(_TEST_GUIDE)
        assert "not yet implemented - v2.1.0" not in content, \
            "Stale 'not yet implemented' notes must be removed from TEST_GUIDE.md"

    def test_broken_links_fixed(self):
        """Broken IMPLEMENTATION_STATUS.md and NEW_COMPREHENSIVE_IMPROVEMENT_PLAN links must be gone."""
        content = _read(_TEST_GUIDE)
        assert "IMPLEMENTATION_STATUS.md" not in content, \
            "Stale IMPLEMENTATION_STATUS.md link must be removed from TEST_GUIDE.md"
        assert "NEW_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_18" not in content, \
            "Stale NEW_COMPREHENSIVE_IMPROVEMENT_PLAN link must be removed from TEST_GUIDE.md"

    def test_last_updated_date(self):
        """Last Updated must say 2026-02-22."""
        content = _read(_TEST_GUIDE)
        assert "2026-02-22" in content, "TEST_GUIDE.md must have Last Updated 2026-02-22"
        assert "2026-02-18" not in content, "Stale 2026-02-18 date must be gone"


# ---------------------------------------------------------------------------
# archive/README.md — stale **NEW** tag and broken link fixed
# ---------------------------------------------------------------------------
class TestArchiveReadmeUpdated:
    """archive/README.md: **NEW** tag removed; IMPLEMENTATION_STATUS.md link fixed."""

    def test_new_tag_removed(self):
        """**NEW** tag on COMPREHENSIVE_ANALYSIS link must be removed."""
        content = _read(_ARCHIVE_README)
        assert "⭐ **NEW**" not in content, \
            "Stale **NEW** tag must be removed from archive/README.md"

    def test_implementation_status_link_fixed(self):
        """IMPLEMENTATION_STATUS.md link must be replaced (file was archived)."""
        content = _read(_ARCHIVE_README)
        assert "IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS" not in content, \
            "Broken IMPLEMENTATION_STATUS.md parent link must be removed from archive/README.md"

    def test_last_updated_date(self):
        """Last Updated must say 2026-02-22."""
        content = _read(_ARCHIVE_README)
        assert "2026-02-22" in content, "archive/README.md must have Last Updated 2026-02-22"

    def test_comprehensive_analysis_has_historical_note(self):
        """COMPREHENSIVE_ANALYSIS entry must mention 'historical'."""
        content = _read(_ARCHIVE_README)
        assert "historical" in content.lower(), \
            "archive/README.md must note that COMPREHENSIVE_ANALYSIS is historical"


# ---------------------------------------------------------------------------
# MASTER_REFACTORING_PLAN_2026.md — session/count stale values fixed
# ---------------------------------------------------------------------------
class TestMasterRefactoringPlanUpdated:
    """MASTER_REFACTORING_PLAN_2026.md: stale session 63/95 test files/3782 counts fixed."""

    def test_section_1_session_updated(self):
        """Section 1 Module Snapshot heading must say session 66 or later."""
        content = _read(_REFACTORING_PLAN)
        assert any(f"session {n}" in content for n in range(66, 80)), \
            "MASTER_REFACTORING_PLAN_2026.md section 1 must say session 66 or later"

    def test_section_1_old_session_gone(self):
        """Stale 'session 63)' heading (not multi-session refs) must be replaced."""
        content = _read(_REFACTORING_PLAN)
        # Remove multi-session reference lines to check only the section heading
        filtered = "\n".join(
            line for line in content.splitlines()
            if "sessions 63-64" not in line and "session 63-64" not in line
        )
        assert "session 63)" not in filtered, \
            "Stale 'session 63)' heading must be replaced in MASTER_REFACTORING_PLAN_2026.md"

    def test_test_count_updated(self):
        """Test count must say 3,856+ or higher (not stale 3,782)."""
        content = _read(_REFACTORING_PLAN)
        assert any(f"{n}+" in content for n in ["3,856", "3,939", "3,971"]), \
            "MASTER_REFACTORING_PLAN_2026.md must show 3,856+ or higher test count"

    def test_test_files_updated(self):
        """Test files count must say 108+ or higher (not stale 95+)."""
        content = _read(_REFACTORING_PLAN)
        assert any(f"{n}+" in content for n in ["108", "110"]), \
            "MASTER_REFACTORING_PLAN_2026.md must show 108+ or higher test files"

    def test_document_version_updated(self):
        """Footer Document Version must say 3.22.21 or later (not stale 1.0)."""
        content = _read(_REFACTORING_PLAN)
        assert any(f"Document Version:** {v}" in content
                   for v in ["3.22.21", "3.22.22", "3.22.23", "3.22.24"]), \
            "MASTER_REFACTORING_PLAN_2026.md Document Version must be 3.22.21 or later"
        assert "Document Version:** 1.0" not in content, \
            "Stale Document Version: 1.0 must be gone"

    def test_next_review_section_present(self):
        """'Next scheduled review' line must be present in the document."""
        content = _read(_REFACTORING_PLAN)
        assert "Next scheduled review" in content, \
            "MASTER_REFACTORING_PLAN_2026.md must have a 'Next scheduled review' line"

    def test_next_review_no_stale_v201(self):
        """Next scheduled review must not reference stale v2.0.1."""
        content = _read(_REFACTORING_PLAN)
        assert "Next scheduled review" in content, \
            "MASTER_REFACTORING_PLAN_2026.md must have a 'Next scheduled review' line"
        review_line = next(
            (line for line in content.splitlines() if "Next scheduled review" in line), ""
        )
        assert "v2.0.1" not in review_line, \
            f"Stale 'v2.0.1' must be removed from Next scheduled review line: {review_line!r}"


# ---------------------------------------------------------------------------
# DOCUMENTATION_GUIDE.md — TEST_GUIDE.md TODO ticked
# ---------------------------------------------------------------------------
class TestDocumentationGuideTODOTicked:
    """DOCUMENTATION_GUIDE.md: TEST_GUIDE.md update TODO ticked [x]."""

    def test_test_guide_todo_ticked(self):
        """The [ ] Update tests/knowledge_graphs/TEST_GUIDE.md item must now be [x]."""
        content = _read(_DOC_GUIDE)
        assert "- [x] Update tests/knowledge_graphs/TEST_GUIDE.md" in content, \
            "DOCUMENTATION_GUIDE.md must have TEST_GUIDE.md TODO ticked [x]"
        assert "- [ ] Update tests/knowledge_graphs/TEST_GUIDE.md" not in content, \
            "Stale unchecked TEST_GUIDE.md TODO must be gone"


# ---------------------------------------------------------------------------
# Cross-doc version agreement
# ---------------------------------------------------------------------------
class TestVersionAgreement:
    """MASTER_STATUS / CHANGELOG / ROADMAP must agree on v3.22.21."""

    def test_master_status_version(self):
        content = _read(_MASTER_STATUS)
        assert "3.22.21" in content, "MASTER_STATUS.md must reference v3.22.21"

    def test_changelog_version(self):
        content = _read(_CHANGELOG)
        assert "3.22.21" in content, "CHANGELOG must have v3.22.21 section"

    def test_roadmap_version(self):
        content = _read(_ROADMAP)
        assert "3.22.21" in content, "ROADMAP.md must reference v3.22.21"
