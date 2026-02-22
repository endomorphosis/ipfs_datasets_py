"""
Session 61 – Stale version/coverage numbers fixed in INDEX.md, README.md, ROADMAP.md.

GIVEN three documentation files that contained stale version/coverage data (v2.0.0 / 75%
      / 116+ tests / "Next Version v2.0.1 Q2 2026") after 15 sessions of improvements
WHEN session 61 updates INDEX.md (v2.0.0→3.22.15; 75%→99.99%; 116+→3,743+ tests; stale
     module-status section → current state), README.md (v2.1.0→3.22.15; last-updated corrected),
     and ROADMAP.md (Current Version 3.22.14→3.22.15)
THEN:
  - INDEX.md reports v3.22.15 and 99.99% coverage
  - INDEX.md "Module Status" section no longer shows v2.0.0 / 75% / stale migration warning
  - INDEX.md "Version History" table includes a v3.22.15 row
  - README.md version header says 3.22.15
  - ROADMAP.md "Current Version" header says 3.22.15
  - All three files agree on v3.22.15 as the current version
  - No existing tests are broken (session59: "3.22.14" still appears in ROADMAP release table)
"""

import pathlib
import unittest

_KG_DIR = pathlib.Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py" / "knowledge_graphs"

_INDEX_PATH = _KG_DIR / "INDEX.md"
_README_PATH = _KG_DIR / "README.md"
_ROADMAP_PATH = _KG_DIR / "ROADMAP.md"
_MASTER_PATH = _KG_DIR / "MASTER_STATUS.md"
_CHANGELOG_PATH = _KG_DIR / "CHANGELOG_KNOWLEDGE_GRAPHS.md"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


class TestIndexMdVersionUpdate(unittest.TestCase):
    """INDEX.md must report v3.22.15 and not the stale v2.0.0 values."""

    def setUp(self):
        self._text = _read(_INDEX_PATH)

    def test_index_has_current_module_version(self):
        """INDEX.md must declare Module Version 3.22.15 (updated from 2.0.0 in session 61)."""
        self.assertIn("3.22.15", self._text,
                      "INDEX.md must contain '3.22.15' after session 61 update")

    def test_index_stale_version_2_0_0_not_in_version_header(self):
        """The old stale 'Module Version: 2.0.0' heading should no longer appear."""
        # Check the specific header line (could appear in version history row as '2.0.0' — that is OK)
        for line in self._text.splitlines():
            if "Module Version" in line and "**" in line:
                self.assertNotIn("2.0.0", line,
                                 "INDEX.md 'Module Version' heading should not say 2.0.0")
                break

    def test_index_footer_not_v2_0_0(self):
        """INDEX.md footer 'Module Version' should not say 2.0.0."""
        lines = self._text.splitlines()
        for i, line in enumerate(lines):
            if "Module Version" in line and "2.0.0" in line:
                # Allow in version-history table rows (contains pipe chars)
                if "|" not in line:
                    self.fail(
                        f"INDEX.md line {i+1}: non-table 'Module Version: 2.0.0' should be gone: {line!r}"
                    )


class TestIndexMdCoverageUpdate(unittest.TestCase):
    """INDEX.md must reflect 99.99% coverage and 3,743+ tests."""

    def setUp(self):
        self._text = _read(_INDEX_PATH)

    def test_index_has_99_99_coverage(self):
        """INDEX.md must say 99.99% somewhere (test coverage stat)."""
        self.assertIn("99.99%", self._text,
                      "INDEX.md must contain '99.99%' test coverage stat")

    def test_index_has_3743_tests(self):
        """INDEX.md must reference 3,743+ tests."""
        self.assertIn("3,743", self._text,
                      "INDEX.md must mention 3,743+ tests in statistics section")

    def test_index_stale_75_percent_gone_from_stats(self):
        """The old '75% overall, 116+ tests' stat line should be gone."""
        self.assertNotIn("75% overall", self._text,
                         "INDEX.md should not still say '75% overall' test coverage")

    def test_index_stale_116_plus_tests_gone(self):
        """The old '116+ tests' stat should be gone."""
        self.assertNotIn("116+ tests", self._text,
                         "INDEX.md should not still say '116+ tests'")


class TestIndexMdModuleStatusSection(unittest.TestCase):
    """INDEX.md Module Status section must reflect current v3.22.15 state."""

    def setUp(self):
        self._text = _read(_INDEX_PATH)

    def test_index_current_state_header_is_updated(self):
        """'Current State' heading in INDEX.md must reference v3.22.15."""
        self.assertIn("v3.22.15", self._text,
                      "INDEX.md 'Current State' heading should reference v3.22.15")

    def test_index_stale_migration_warning_removed(self):
        """The stale '⚠️ Migration Module: Needs test coverage improvement' line must be gone."""
        self.assertNotIn("Needs test coverage improvement", self._text,
                         "INDEX.md should not show stale migration warning (migration is 100%)")

    def test_index_no_stale_next_version_v2_0_1(self):
        """The stale 'Next Version (v2.0.1 - Q2 2026)' heading must be gone."""
        self.assertNotIn("v2.0.1 - Q2 2026", self._text,
                         "INDEX.md should not still list v2.0.1 as next version")

    def test_index_version_history_has_3_22_15(self):
        """INDEX.md version history table should include a v3.22.15 row."""
        self.assertIn("3.22.15", self._text,
                      "INDEX.md version history should contain a v3.22.15 row")

    def test_index_last_updated_is_2026_02_22(self):
        """INDEX.md 'Last Updated' footer must be 2026-02-22."""
        self.assertIn("2026-02-22", self._text,
                      "INDEX.md Last Updated footer should say 2026-02-22")


class TestReadmeMdVersionUpdate(unittest.TestCase):
    """README.md must report v3.22.15 (updated from v2.1.0 in session 61)."""

    def setUp(self):
        self._text = _read(_README_PATH)

    def test_readme_has_current_version(self):
        """README.md must declare **Version:** 3.22.15."""
        self.assertIn("3.22.15", self._text,
                      "README.md must contain '3.22.15' after session 61 update")

    def test_readme_stale_version_2_1_0_not_in_version_line(self):
        """README.md version header should not say 2.1.0."""
        for line in self._text.splitlines():
            if line.strip().startswith("**Version:**"):
                self.assertNotIn("2.1.0", line,
                                 "README.md **Version:** header should not say 2.1.0")
                break

    def test_readme_last_updated_is_2026_02_22(self):
        """README.md 'Last Updated' must be 2026-02-22."""
        self.assertIn("2026-02-22", self._text,
                      "README.md Last Updated should say 2026-02-22")


class TestRoadmapCurrentVersionUpdate(unittest.TestCase):
    """ROADMAP.md 'Current Version' header must say 3.22.15 (was 3.22.14)."""

    def setUp(self):
        self._text = _read(_ROADMAP_PATH)

    def _current_version_line(self) -> str:
        for line in self._text.splitlines():
            if "Current Version" in line:
                return line
        return ""

    def test_roadmap_current_version_header_is_3_22_15(self):
        """ROADMAP.md 'Current Version' header line must say 3.22.15 or later."""
        cv_line = self._current_version_line()
        self.assertTrue("3.22.15" in cv_line or "3.22.16" in cv_line,
                        f"ROADMAP.md 'Current Version' should be 3.22.15 or later; got: {cv_line!r}")

    def test_roadmap_current_version_not_still_3_22_14(self):
        """ROADMAP.md 'Current Version' header line must not still say 3.22.14."""
        cv_line = self._current_version_line()
        self.assertNotIn("3.22.14", cv_line,
                         f"ROADMAP.md 'Current Version' should be updated from 3.22.14; got: {cv_line!r}")

    def test_roadmap_3_22_14_still_in_release_table(self):
        """3.22.14 must still appear in ROADMAP.md release table (backward-compat for session59 test)."""
        self.assertIn("3.22.14", self._text,
                      "3.22.14 must still appear in ROADMAP.md release table")


class TestThreeDocVersionAgreement(unittest.TestCase):
    """INDEX.md, README.md, and ROADMAP.md must all agree on v3.22.15 or later."""

    def test_index_md_version_3_22_15(self):
        """INDEX.md must contain '3.22.15' (set in session 61; may be higher in later sessions)."""
        self.assertIn("3.22.15", _read(_INDEX_PATH))

    def test_readme_md_version_3_22_15(self):
        """README.md must contain '3.22.15' (set in session 61; may be higher in later sessions)."""
        self.assertIn("3.22.15", _read(_README_PATH))

    def test_roadmap_current_version_3_22_15(self):
        """ROADMAP.md 'Current Version' header must say 3.22.15 or later."""
        for line in _read(_ROADMAP_PATH).splitlines():
            if "Current Version" in line:
                self.assertTrue("3.22.15" in line or "3.22.16" in line,
                                f"ROADMAP.md 'Current Version' should be 3.22.15+; got: {line!r}")
                return
        self.fail("ROADMAP.md has no 'Current Version' line")


if __name__ == "__main__":
    unittest.main()
