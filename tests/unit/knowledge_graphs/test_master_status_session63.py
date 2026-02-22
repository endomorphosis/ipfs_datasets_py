"""
Session 63 – Doc integrity tests.

Covers:
1. ROADMAP.md: stale "Status: Planned" items inside CANCELLED sections updated
2. MASTER_REFACTORING_PLAN_2026.md: version/date/snapshot/sessions 59-62/§3.3.2 status
3. Version agreement across MASTER_STATUS.md / ROADMAP.md / CHANGELOG / REFACTORING_PLAN
"""

from pathlib import Path
import re
import pytest

_KG = Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py" / "knowledge_graphs"
_ROADMAP = _KG / "ROADMAP.md"
_REFPLAN = _KG / "MASTER_REFACTORING_PLAN_2026.md"
_MASTER = _KG / "MASTER_STATUS.md"
_CHANGELOG = _KG / "CHANGELOG_KNOWLEDGE_GRAPHS.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. ROADMAP "Planned" items inside CANCELLED sections now resolved
# ---------------------------------------------------------------------------

class TestRoadmapPlannedItemsFixed:
    """GIVEN the ROADMAP.md WHEN checking items in CANCELLED sections
    THEN no bare 'Status: Planned' should remain (all resolved or deferred to v4.0+).
    """

    def test_migration_performance_delivered(self):
        """Migration Performance item now shows Delivered status."""
        text = _read(_ROADMAP)
        # After the fix, "Migration Performance" section should not say "Status: Planned"
        # It should say "Delivered in v2.1.0"
        assert "#### 4. Migration Performance" in text
        # Find the section
        idx = text.index("#### 4. Migration Performance")
        section = text[idx : idx + 400]
        assert "Status: Planned" not in section, (
            "Migration Performance still has stale 'Status: Planned' in ROADMAP.md"
        )
        assert "Delivered" in section or "v2.1.0" in section, (
            "Migration Performance section should show Delivered status"
        )

    def test_spacy_dependency_parsing_delivered(self):
        """spaCy Dependency Parsing section now shows Delivered status."""
        text = _read(_ROADMAP)
        assert "#### 2. spaCy Dependency Parsing Integration" in text
        idx = text.index("#### 2. spaCy Dependency Parsing Integration")
        section = text[idx : idx + 400]
        assert "Status: Planned" not in section, (
            "spaCy Dependency Parsing still has stale 'Status: Planned' in ROADMAP.md"
        )
        assert "Delivered" in section or "v2.1.0" in section, (
            "spaCy Dependency Parsing section should show Delivered status"
        )

    def test_confidence_scoring_deferred_to_v4(self):
        """Confidence Scoring Improvements is now Deferred to v4.0+."""
        text = _read(_ROADMAP)
        assert "#### 4. Confidence Scoring Improvements" in text
        idx = text.index("#### 4. Confidence Scoring Improvements")
        section = text[idx : idx + 500]
        assert "Status: Planned" not in section, (
            "Confidence Scoring Improvements still has bare 'Status: Planned'"
        )
        assert "v4.0" in section or "Deferred" in section, (
            "Confidence Scoring Improvements should be deferred to v4.0+"
        )

    def test_no_bare_status_planned_in_cancelled_sections(self):
        """No 'Status: Planned' lines should appear inside CANCELLED version sections."""
        text = _read(_ROADMAP)
        # Find the CANCELLED sections (v2.2.0 and v2.5.0 only)
        cancelled_start = text.find("## Version 2.2.0")
        # The CANCELLED sections end before Version 3.0.0
        cancelled_end = text.find("## Version 3.0.0")
        if cancelled_start == -1 or cancelled_end == -1:
            pytest.skip("CANCELLED section boundaries not found")
        cancelled_region = text[cancelled_start:cancelled_end]
        assert "**Status:** Planned" not in cancelled_region, (
            "Found bare 'Status: Planned' inside CANCELLED version sections in ROADMAP.md"
        )

    def test_migration_performance_streaming_mentioned(self):
        """Migration Performance section mentions the actual streaming implementation."""
        text = _read(_ROADMAP)
        idx = text.index("#### 4. Migration Performance")
        section = text[idx : idx + 600]
        assert "export_streaming" in section or "streaming" in section.lower(), (
            "Migration Performance section should mention the streaming export implementation"
        )


# ---------------------------------------------------------------------------
# 2. MASTER_REFACTORING_PLAN_2026.md version and date
# ---------------------------------------------------------------------------

class TestMasterRefactoringPlanVersion:
    """GIVEN the MASTER_REFACTORING_PLAN_2026.md WHEN checking metadata
    THEN version and date should reflect current state.
    """

    def test_version_updated(self):
        """Version should not be stale 1.0."""
        text = _read(_REFPLAN)
        assert "**Version:** 1.0" not in text, (
            "MASTER_REFACTORING_PLAN_2026.md still shows stale Version: 1.0"
        )

    def test_version_current(self):
        """Version should be 3.22.17."""
        text = _read(_REFPLAN)
        assert "3.22.17" in text, (
            "MASTER_REFACTORING_PLAN_2026.md should show current version 3.22.17"
        )

    def test_last_updated_current(self):
        """Last Updated should be 2026-02-22."""
        text = _read(_REFPLAN)
        assert "2026-02-22" in text, (
            "MASTER_REFACTORING_PLAN_2026.md Last Updated should be 2026-02-22"
        )

    def test_stale_last_updated_gone(self):
        """Stale 'Last Updated: 2026-02-20' should not be the only date."""
        text = _read(_REFPLAN)
        # 2026-02-20 may appear in historical references but not as the Last Updated header
        lines = text.split("\n")
        last_updated_lines = [l for l in lines if "Last Updated:" in l and "2026-02-20" in l]
        # The header line should not be the only "Last Updated" line with 2026-02-20
        # (it may still appear in the completed work summary as a historical date)
        header_stale = any(
            "**Last Updated:** 2026-02-20" in l for l in last_updated_lines
        )
        assert not header_stale, (
            "MASTER_REFACTORING_PLAN_2026.md still has stale **Last Updated:** 2026-02-20"
        )


# ---------------------------------------------------------------------------
# 3. MASTER_REFACTORING_PLAN §1 snapshot and §2 sessions 59-62
# ---------------------------------------------------------------------------

class TestMasterRefactoringPlanContent:
    """GIVEN MASTER_REFACTORING_PLAN_2026.md WHEN checking content
    THEN snapshot and sessions 59-62 should be present.
    """

    def test_snapshot_coverage_updated(self):
        """§1 snapshot should show 99.99% not old ~78%."""
        text = _read(_REFPLAN)
        assert "~78%" not in text or "99.99%" in text, (
            "MASTER_REFACTORING_PLAN_2026.md still shows stale ~78% overall coverage"
        )
        assert "99.99%" in text, (
            "MASTER_REFACTORING_PLAN_2026.md should show current 99.99% coverage"
        )

    def test_sessions_59_to_62_mentioned(self):
        """Sessions 59-62 documentation work should appear in completed summary."""
        text = _read(_REFPLAN)
        assert "session 59" in text.lower() or "Session 59" in text or "sessions 59" in text.lower(), (
            "MASTER_REFACTORING_PLAN_2026.md should mention session 59 doc work"
        )

    def test_validator_split_deferred_to_v4(self):
        """§3.3.2 Extraction Validation Split should be deferred to v4.0+, not just 🟡."""
        text = _read(_REFPLAN)
        assert "#### 3.3.2 Extraction Validation Split" in text
        idx = text.index("#### 3.3.2 Extraction Validation Split")
        section = text[idx : idx + 400]
        assert "🟡 Deferred" not in section, (
            "§3.3.2 still has ambiguous 🟡 Deferred status — should say v4.0+"
        )
        assert "v4.0" in section or "Deferred to v4" in section, (
            "§3.3.2 should explicitly say deferred to v4.0+"
        )

    def test_test_count_updated(self):
        """§1 snapshot should show 3,782+ tests, not old 1,075+."""
        text = _read(_REFPLAN)
        assert "1,075+" not in text or "3,782" in text, (
            "MASTER_REFACTORING_PLAN_2026.md still shows stale 1,075+ test count"
        )


# ---------------------------------------------------------------------------
# 4. Four-document version agreement
# ---------------------------------------------------------------------------

class TestFourDocVersionAgreement:
    """GIVEN all four tracking documents WHEN checking version references
    THEN they should all agree on the current version (3.22.17).
    """

    def test_master_status_on_v3_22_17(self):
        """MASTER_STATUS.md should reference v3.22.17."""
        text = _read(_MASTER)
        assert "3.22.17" in text, "MASTER_STATUS.md should have been updated to v3.22.17"

    def test_changelog_has_v3_22_17(self):
        """CHANGELOG should have a ## [3.22.17] section."""
        text = _read(_CHANGELOG)
        assert "## [3.22.17]" in text, "CHANGELOG_KNOWLEDGE_GRAPHS.md should have a [3.22.17] section"

    def test_refactoring_plan_on_v3_22_17(self):
        """MASTER_REFACTORING_PLAN_2026.md should reference v3.22.17."""
        text = _read(_REFPLAN)
        assert "3.22.17" in text, "MASTER_REFACTORING_PLAN_2026.md should reference v3.22.17"
