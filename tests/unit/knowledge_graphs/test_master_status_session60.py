"""
Session 60 doc-integrity tests.

Verifies that MASTER_STATUS.md and ROADMAP.md accurately reflect the
current state of the knowledge_graphs module (session 60 changes).

Changes in session 60:
- MASTER_STATUS.md: stale "~89% (measured, session 26)" coverage section updated to
  99.99%; per-module table refreshed; sessions 54–60 added to test session list;
  total test count updated 3,614→3,725.
- ROADMAP.md: duplicate "Version 2.0.1 (Q2 2026)" section (with unchecked items)
  removed; "Last Updated" corrected to 2026-02-22.
"""

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
_KG_DIR = Path(__file__).resolve().parent.parent.parent.parent / \
    "ipfs_datasets_py" / "knowledge_graphs"
_MASTER_STATUS = _KG_DIR / "MASTER_STATUS.md"
_ROADMAP = _KG_DIR / "ROADMAP.md"
_CHANGELOG = _KG_DIR / "CHANGELOG_KNOWLEDGE_GRAPHS.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TestMasterStatusCoverageSection
# ---------------------------------------------------------------------------
class TestMasterStatusCoverageSection:
    """Verify the coverage table heading and content are up to date."""

    def test_coverage_heading_says_99_99(self):
        """Heading must say 99.99%, not ~89%."""
        text = _read(_MASTER_STATUS)
        assert "99.99%" in text, "MASTER_STATUS.md coverage heading should say 99.99%"

    def test_coverage_heading_no_longer_says_89(self):
        """Stale '~89%' heading must not appear."""
        text = _read(_MASTER_STATUS)
        assert "~89%" not in text, "Stale '~89%' coverage heading found in MASTER_STATUS.md"

    def test_coverage_heading_no_longer_says_session_26(self):
        """'measured, session 26' measurement note must be gone."""
        text = _read(_MASTER_STATUS)
        assert "measured, session 26" not in text, \
            "Stale 'measured, session 26' still in MASTER_STATUS.md"

    def test_coverage_heading_references_session_58(self):
        """Coverage section should say it was measured in session 58."""
        text = _read(_MASTER_STATUS)
        assert "measured, session 58" in text, \
            "Coverage section should reference 'measured, session 58'"

    def test_module_table_all_modules_excellent_or_complete(self):
        """All module rows in the coverage table must not show stale percentages below 90%."""
        text = _read(_MASTER_STATUS)
        # Old entries that were stale; none should appear
        bad_snippets = [
            "ir_executor **99%**",           # now 100%
            "cross_document **96%**",        # now 100%
            "visualization **94%**",         # now 100%
            "lineage/core **97%**",          # now 100%
        ]
        for bad in bad_snippets:
            assert bad not in text, \
                f"Stale coverage snippet '{bad}' still present in MASTER_STATUS.md"

    def test_remaining_1_missed_line_section(self):
        """MASTER_STATUS should document exactly 1 missed line (the defensive guard)."""
        text = _read(_MASTER_STATUS)
        assert "_entity_helpers.py:117" in text, \
            "Should document _entity_helpers.py:117 as the 1 remaining missed line"
        # Must not claim there are still 100+ missed lines
        assert "108 lines" not in text, \
            "Stale '108 lines' reference (spaCy paths) still in MASTER_STATUS.md coverage section"


# ---------------------------------------------------------------------------
# TestMasterStatusTestCount
# ---------------------------------------------------------------------------
class TestMasterStatusTestCount:
    """Verify total test count reflects sessions 47–59."""

    def test_total_tests_reflects_3725(self):
        """MASTER_STATUS should say 3,725 total passing tests."""
        text = _read(_MASTER_STATUS)
        assert "3,725" in text, \
            "MASTER_STATUS.md should report 3,725 total passing tests"

    def test_stale_3614_count_removed(self):
        """Old '3,614 passing' total line should be gone (replaced by 3,725)."""
        text = _read(_MASTER_STATUS)
        # The old "Total Tests: 3,614 passing" summary line should not appear
        assert "Total Tests:** 3,614" not in text, \
            "Stale 'Total Tests: 3,614' still in MASTER_STATUS.md"

    def test_session_54_to_59_in_session_list(self):
        """Sessions 54–59 must appear in the session log section."""
        text = _read(_MASTER_STATUS)
        for session in range(54, 60):
            assert f"session{session}:" in text, \
                f"Session {session} not found in MASTER_STATUS.md session list"

    def test_session_60_in_session_list(self):
        """Session 60 entry must be present."""
        text = _read(_MASTER_STATUS)
        assert "session60:" in text, "Session 60 entry missing from MASTER_STATUS.md"


# ---------------------------------------------------------------------------
# TestRoadmapDuplicateSection
# ---------------------------------------------------------------------------
class TestRoadmapDuplicateSection:
    """Verify the duplicate 'Version 2.0.1' section has been removed."""

    def test_version_201_appears_exactly_once(self):
        """'Version 2.0.1' heading must appear exactly once in ROADMAP.md."""
        text = _read(_ROADMAP)
        count = text.count("## Version 2.0.1")
        assert count == 1, \
            f"Expected 1 occurrence of '## Version 2.0.1' in ROADMAP.md, got {count}"

    def test_unchecked_increase_migration_item_gone(self):
        """The old unchecked '- [ ] Increase migration module test coverage' item must not exist."""
        text = _read(_ROADMAP)
        assert "- [ ] Increase migration module test coverage" not in text, \
            "Unchecked migration-coverage TODO item still present in ROADMAP.md (should be removed)"

    def test_unchecked_add_error_handling_tests_gone(self):
        """The old unchecked '- [ ] Add comprehensive error handling tests' item must not exist."""
        text = _read(_ROADMAP)
        assert "- [ ] Add comprehensive error handling tests" not in text, \
            "Unchecked error-handling TODO item still in ROADMAP.md"

    def test_roadmap_last_updated_2026_02_22(self):
        """The 'Last Updated' footer in ROADMAP.md must say 2026-02-22."""
        text = _read(_ROADMAP)
        assert "**Last Updated:** 2026-02-22" in text, \
            "ROADMAP.md 'Last Updated' should be 2026-02-22"

    def test_roadmap_last_updated_not_2026_02_20(self):
        """Stale 2026-02-20 Last Updated date must be replaced."""
        text = _read(_ROADMAP)
        assert "**Last Updated:** 2026-02-20" not in text, \
            "Stale '**Last Updated:** 2026-02-20' still in ROADMAP.md"


# ---------------------------------------------------------------------------
# TestThreeDocVersionAgreement
# ---------------------------------------------------------------------------
class TestThreeDocVersionAgreement:
    """MASTER_STATUS, ROADMAP, and CHANGELOG should all agree on v3.22.15 or later."""

    def test_master_status_version_is_3_22_15(self):
        """MASTER_STATUS.md version header must be 3.22.15 or later."""
        text = _read(_MASTER_STATUS)
        assert "**Version:** 3.22.15" in text or "**Version:** 3.22.16" in text, \
            "MASTER_STATUS.md **Version:** should be 3.22.15 or later"

    def test_roadmap_release_table_has_3_22_15(self):
        """ROADMAP.md release table should contain a 3.22.15 row."""
        text = _read(_ROADMAP)
        assert "3.22.15" in text, \
            "ROADMAP.md release table should have a v3.22.15 entry"

    def test_changelog_has_3_22_15_section(self):
        """CHANGELOG should have a ## [3.22.15] section."""
        text = _read(_CHANGELOG)
        assert "## [3.22.15]" in text, \
            "CHANGELOG_KNOWLEDGE_GRAPHS.md should have a ## [3.22.15] section"
