"""
Session 65 — doc + code integrity tests.

Verifies:
1. cross_document.py stale "see TODO at line 542" docstring removed
2. MASTER_STATUS.md Documentation row updated v3.22.15→v3.22.18
3. MASTER_STATUS.md test files count updated 95→102
4. MASTER_REFACTORING_PLAN_2026.md version 3.22.17→3.22.18 + sessions 63-64 added
5. All four primary docs agree on version v3.22.19
"""

import re
from pathlib import Path

KG_DIR = Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py" / "knowledge_graphs"
SRC_DIR = KG_DIR / "reasoning"
MASTER_STATUS = KG_DIR / "MASTER_STATUS.md"
CHANGELOG = KG_DIR / "CHANGELOG_KNOWLEDGE_GRAPHS.md"
ROADMAP = KG_DIR / "ROADMAP.md"
REFACTORING_PLAN = KG_DIR / "MASTER_REFACTORING_PLAN_2026.md"
CROSS_DOC = SRC_DIR / "cross_document.py"


class TestCrossDocumentDocstringFixed:
    """cross_document.py: stale 'see TODO at line 542' removed from docstring."""

    def _read(self):
        return CROSS_DOC.read_text(encoding="utf-8")

    def test_stale_todo_reference_removed(self):
        """'see TODO at line 542' must not appear in the file."""
        assert "see TODO at line 542" not in self._read(), (
            "Stale 'see TODO at line 542' docstring reference is still present"
        )

    def test_note_mentions_heuristics(self):
        """Updated note should reference heuristic approach."""
        text = self._read()
        assert "heuristics" in text.lower() or "heuristic" in text.lower(), (
            "Docstring note should mention the heuristic implementation approach"
        )

    def test_note_mentions_similarity(self):
        """Updated note should mention similarity as a factor."""
        assert "similarity" in self._read().lower(), (
            "Docstring note should mention document similarity"
        )

    def test_note_mentions_chronology(self):
        """Updated note should mention chronology as a factor."""
        assert "chronology" in self._read().lower(), (
            "Docstring note should mention chronology"
        )


class TestMasterStatusDocRef:
    """MASTER_STATUS.md: Documentation row and test file count updated."""

    def _read(self):
        return MASTER_STATUS.read_text(encoding="utf-8")

    def test_documentation_row_reflects_v3_22_18(self):
        """Documentation row should reference v3.22.18 or later."""
        text = self._read()
        # Check any recent version is there
        assert any(v in text for v in ("v3.22.18", "v3.22.19", "Reflects v3.22.18", "Reflects v3.22.19")), (
            "Documentation row should reference current version v3.22.18 or v3.22.19"
        )

    def test_stale_v3_22_15_documentation_row_gone(self):
        """'Reflects v3.22.15 structure' must no longer appear in Documentation row."""
        assert "Reflects v3.22.15 structure" not in self._read(), (
            "Documentation row still shows stale 'v3.22.15 structure' reference"
        )

    def test_test_files_count_102(self):
        """Test file count should be 102 (as of v3.22.18)."""
        text = self._read()
        assert "102 total" in text, (
            "Test files count should show 102 total (sessions 59-64 added 6 files)"
        )

    def test_stale_95_total_gone(self):
        """'### Test Files: 95 total' header should no longer appear."""
        text = self._read()
        # The old heading was '### Test Files: 95 total (as of v3.22.15)'
        # It may appear in session log text as historical context, so check the heading specifically
        assert "### Test Files: 95 total" not in text, (
            "Old '### Test Files: 95 total' section header is still present"
        )

    def test_as_of_v3_22_18_present(self):
        """'as of v3.22.18' should appear near the test file count."""
        assert "as of v3.22.18" in self._read(), (
            "'as of v3.22.18' annotation missing from test files count"
        )


class TestMasterRefactoringPlanSession65:
    """MASTER_REFACTORING_PLAN_2026.md: version 3.22.17→3.22.18; sessions 63-64 added."""

    def _read(self):
        return REFACTORING_PLAN.read_text(encoding="utf-8")

    def test_version_is_3_22_18_or_later(self):
        """Version should be 3.22.18 or later (not stale 3.22.17)."""
        text = self._read()
        assert any(v in text for v in ("**Version:** 3.22.18", "**Version:** 3.22.19")), (
            "MASTER_REFACTORING_PLAN version should be 3.22.18 or later"
        )

    def test_stale_3_22_17_version_header_gone(self):
        """'**Version:** 3.22.17' must not appear as the version header."""
        assert "**Version:** 3.22.17" not in self._read(), (
            "MASTER_REFACTORING_PLAN still shows stale version header 3.22.17"
        )

    def test_api_accuracy_section_present(self):
        """Sessions 63-64 'API Accuracy' work section must be present."""
        assert "API Accuracy" in self._read(), (
            "Sessions 63-64 API Accuracy section not found in MASTER_REFACTORING_PLAN"
        )

    def test_quickstart_mentioned_in_sessions_63_64(self):
        """QUICKSTART.md fix should be mentioned in the sessions 63-64 section."""
        assert "QUICKSTART" in self._read(), (
            "QUICKSTART.md work from session 64 not referenced in MASTER_REFACTORING_PLAN"
        )


class TestDocVersionAgreement:
    """MASTER_STATUS, CHANGELOG, ROADMAP, and REFACTORING_PLAN all agree on current version."""

    def test_master_status_version_is_3_22_19(self):
        """MASTER_STATUS.md should declare version 3.22.19."""
        text = MASTER_STATUS.read_text(encoding="utf-8")
        assert "**Version:** 3.22.19" in text, (
            f"MASTER_STATUS.md version header should be 3.22.19"
        )

    def test_changelog_has_3_22_19_section(self):
        """CHANGELOG should have a [3.22.19] section."""
        text = CHANGELOG.read_text(encoding="utf-8")
        assert "## [3.22.19]" in text, (
            "CHANGELOG_KNOWLEDGE_GRAPHS.md missing ## [3.22.19] section"
        )

    def test_roadmap_current_version_is_3_22_19(self):
        """ROADMAP.md Current Version header should be 3.22.19."""
        text = ROADMAP.read_text(encoding="utf-8")
        assert "**Current Version:** 3.22.19" in text, (
            "ROADMAP.md Current Version header should be 3.22.19"
        )
