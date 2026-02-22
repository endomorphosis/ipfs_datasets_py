"""
Session 59 — Documentation Consistency Tests
==============================================

Verifies that ROADMAP.md, CHANGELOG_KNOWLEDGE_GRAPHS.md, and MASTER_STATUS.md
are internally consistent and contain all expected entries.

Changes made in session 59:
- ROADMAP.md: header version updated to 3.22.14; release table extended with
  v3.22.1 through v3.22.14 entries (was only listing 3.22.0 then jumping to 4.0)
- CHANGELOG_KNOWLEDGE_GRAPHS.md: three missing section headers added:
  - v3.22.5 (session 50: numpy-via-networkx skip guards)
  - v3.22.7 (session 52: ImportError except branches, 17 tests)
  - v3.22.11 (session 56: dead code removal from cross_document+ir_executor)
- MASTER_STATUS.md: version 3.22.13 → 3.22.14; session 59 logged

No production code changes.  All tests are documentation invariants.
"""

import re
import pytest
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers: locate the docs
# ---------------------------------------------------------------------------

_KG_DIR = Path(__file__).parents[3] / "ipfs_datasets_py" / "knowledge_graphs"
_ROADMAP = _KG_DIR / "ROADMAP.md"
_CHANGELOG = _KG_DIR / "CHANGELOG_KNOWLEDGE_GRAPHS.md"
_MASTER = _KG_DIR / "MASTER_STATUS.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Class 1: ROADMAP.md header consistency
# ---------------------------------------------------------------------------

class TestRoadmapHeaderVersion:
    """ROADMAP.md must declare the current version in its header block."""

    def test_roadmap_header_contains_version_field(self):
        """ROADMAP.md starts with a 'Current Version:' line."""
        content = _read(_ROADMAP)
        assert "Current Version:" in content, (
            "ROADMAP.md must contain a 'Current Version:' header line"
        )

    def test_roadmap_header_version_is_3_22_14(self):
        """ROADMAP.md header must declare version 3.22.14 (updated in session 59)."""
        content = _read(_ROADMAP)
        # Expect either "**Current Version:** 3.22.14" or "Current Version: 3.22.14"
        assert "3.22.14" in content, (
            "ROADMAP.md 'Current Version' should be 3.22.14"
        )

    def test_roadmap_status_is_production_ready(self):
        """ROADMAP.md should declare 'Production Ready' status."""
        content = _read(_ROADMAP)
        assert "Production Ready" in content

    def test_roadmap_version_higher_than_3_22_3(self):
        """Verify ROADMAP.md no longer shows the stale 3.22.3 version as current."""
        content = _read(_ROADMAP)
        # The old stale value was "**Current Version:** 3.22.3"
        # It may still appear in the release table, but NOT as the current-version header
        lines = content.splitlines()
        current_version_lines = [
            l for l in lines if "Current Version:" in l
        ]
        assert current_version_lines, "ROADMAP.md must have a Current Version line"
        cv_line = current_version_lines[0]
        assert "3.22.3" not in cv_line, (
            "ROADMAP.md 'Current Version' header should not still say 3.22.3"
        )

    def test_roadmap_coverage_reflects_99_99(self):
        """ROADMAP.md status line should reflect 99.99% coverage, not '99%'."""
        content = _read(_ROADMAP)
        assert "99.99" in content, (
            "ROADMAP.md status should mention 99.99% test coverage (updated in s59)"
        )


# ---------------------------------------------------------------------------
# Class 2: ROADMAP.md release table completeness
# ---------------------------------------------------------------------------

class TestRoadmapReleaseTable:
    """All 3.22.x versions from 3.22.0 through 3.22.14 must appear in the
    release schedule table."""

    # The full set of expected version strings that must appear in the table.
    _EXPECTED_VERSIONS = [
        "3.22.0", "3.22.1", "3.22.2", "3.22.3", "3.22.4", "3.22.5",
        "3.22.6", "3.22.7", "3.22.8", "3.22.9", "3.22.10", "3.22.11",
        "3.22.12", "3.22.13", "3.22.14",
    ]

    def _table_section(self) -> str:
        content = _read(_ROADMAP)
        # Extract the Release Schedule section
        start = content.find("## Release Schedule")
        assert start != -1, "ROADMAP.md must contain a '## Release Schedule' section"
        return content[start:]

    def test_release_table_has_3_22_0(self):
        assert "3.22.0" in self._table_section()

    def test_release_table_has_3_22_4_through_3_22_9(self):
        table = self._table_section()
        for v in ["3.22.4", "3.22.5", "3.22.6", "3.22.7", "3.22.8", "3.22.9"]:
            assert v in table, (
                f"ROADMAP.md release table is missing version {v}"
            )

    def test_release_table_has_3_22_10_through_3_22_14(self):
        table = self._table_section()
        for v in ["3.22.10", "3.22.11", "3.22.12", "3.22.13", "3.22.14"]:
            assert v in table, (
                f"ROADMAP.md release table is missing version {v}"
            )

    def test_release_table_all_3_22_versions_present(self):
        table = self._table_section()
        missing = [v for v in self._EXPECTED_VERSIONS if v not in table]
        assert not missing, (
            f"ROADMAP.md release table is missing versions: {missing}"
        )

    def test_future_4_0_entry_still_present(self):
        """The v4.0 future entry should still be in the table."""
        table = self._table_section()
        assert "4.0" in table, "ROADMAP.md release table should still list v4.0 (future)"


# ---------------------------------------------------------------------------
# Class 3: CHANGELOG version coverage
# ---------------------------------------------------------------------------

class TestChangelogVersionCoverage:
    """All 3.22.x versions must have proper section headings in the CHANGELOG."""

    _EXPECTED_VERSIONS = [
        "3.22.0", "3.22.1", "3.22.2", "3.22.3", "3.22.4", "3.22.5",
        "3.22.6", "3.22.7", "3.22.8", "3.22.9", "3.22.10", "3.22.11",
        "3.22.12", "3.22.13", "3.22.14",
    ]

    def _section_headings(self) -> list[str]:
        """Return list of version strings found in CHANGELOG section headings."""
        content = _read(_CHANGELOG)
        # Match "## [X.Y.Z]" headings
        return re.findall(r"^## \[(\d+\.\d+\.\d+)\]", content, re.MULTILINE)

    def test_changelog_has_3_22_0(self):
        assert "3.22.0" in self._section_headings()

    def test_changelog_has_3_22_5_section(self):
        """v3.22.5 was the previously-missing session 50 section."""
        headings = self._section_headings()
        assert "3.22.5" in headings, (
            "CHANGELOG must have a ## [3.22.5] section (added in session 59)"
        )

    def test_changelog_has_3_22_7_section(self):
        """v3.22.7 was the previously-missing session 52 section."""
        headings = self._section_headings()
        assert "3.22.7" in headings, (
            "CHANGELOG must have a ## [3.22.7] section (added in session 59)"
        )

    def test_changelog_has_3_22_11_section(self):
        """v3.22.11 was the previously-missing session 56 section."""
        headings = self._section_headings()
        assert "3.22.11" in headings, (
            "CHANGELOG must have a ## [3.22.11] section (added in session 59)"
        )

    def test_changelog_all_expected_versions_present(self):
        headings = self._section_headings()
        missing = [v for v in self._EXPECTED_VERSIONS if v not in headings]
        assert not missing, (
            f"CHANGELOG is missing version sections: {missing}"
        )

    def test_changelog_headings_are_descending(self):
        """CHANGELOG follows Keep-a-Changelog convention: newest version first."""
        headings = self._section_headings()
        # Convert to tuples for comparison
        tuples = [tuple(int(x) for x in v.split(".")) for v in headings
                  if re.match(r"\d+\.\d+\.\d+", v)]
        assert tuples == sorted(tuples, reverse=True), (
            "CHANGELOG version headings should be in descending order (newest first)"
        )


# ---------------------------------------------------------------------------
# Class 4: MASTER_STATUS.md version consistency
# ---------------------------------------------------------------------------

class TestMasterStatusVersion:
    """MASTER_STATUS.md must reflect the current version (3.22.14)."""

    def test_master_status_version_is_3_22_14(self):
        content = _read(_MASTER)
        assert "3.22.14" in content, (
            "MASTER_STATUS.md must declare version 3.22.14"
        )

    def test_master_status_version_header_line(self):
        """The '**Version:**' line should say 3.22.14 or later."""
        content = _read(_MASTER)
        version_lines = [l for l in content.splitlines() if l.startswith("**Version:**")]
        assert version_lines, "MASTER_STATUS.md must have a **Version:** line"
        # Accept 3.22.14 (set in session 59), 3.22.15 or 3.22.16+ (advanced in subsequent sessions)
        assert "3.22.14" in version_lines[0] or "3.22.15" in version_lines[0] or "3.22.16" in version_lines[0], (
            f"**Version:** line should be 3.22.14 or later, got: {version_lines[0]}"
        )

    def test_master_status_not_stale_3_22_13(self):
        """The **Version:** header should NOT still say 3.22.13."""
        content = _read(_MASTER)
        version_lines = [l for l in content.splitlines() if l.startswith("**Version:**")]
        assert version_lines, "MASTER_STATUS.md must have a **Version:** line"
        assert "3.22.13" not in version_lines[0], (
            "MASTER_STATUS.md **Version:** header should have been updated to 3.22.14"
        )

    def test_master_status_production_ready(self):
        content = _read(_MASTER)
        assert "Production Ready" in content

    def test_three_docs_agree_on_version(self):
        """ROADMAP.md, CHANGELOG.md, and MASTER_STATUS.md all mention 3.22.14."""
        for path, name in [
            (_ROADMAP, "ROADMAP.md"),
            (_CHANGELOG, "CHANGELOG_KNOWLEDGE_GRAPHS.md"),
            (_MASTER, "MASTER_STATUS.md"),
        ]:
            content = _read(path)
            assert "3.22.14" in content, (
                f"{name} should mention version 3.22.14"
            )
