"""
Session 66 — Historical doc banners + DOCUMENTATION_GUIDE tier fixes

Changes validated:
1. COMPREHENSIVE_ANALYSIS_2026_02_18.md: historical banner added, footer updated
2. EXECUTIVE_SUMMARY_FINAL_2026_02_18.md: historical banner added, [ ] items→[x]
3. REFACTORING_COMPLETE_2026_02_18.md: historical banner added
4. DOCUMENTATION_GUIDE.md: item-7 **NEW** removed + "Historical reference";
   EXECUTIVE_SUMMARY_FINAL + REFACTORING_COMPLETE added to Tier 6
"""

import pathlib
import pytest

KG = pathlib.Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py" / "knowledge_graphs"

COMPREHENSIVE = KG / "COMPREHENSIVE_ANALYSIS_2026_02_18.md"
EXEC_SUMMARY  = KG / "EXECUTIVE_SUMMARY_FINAL_2026_02_18.md"
REFACTORING   = KG / "REFACTORING_COMPLETE_2026_02_18.md"
DOC_GUIDE     = KG / "DOCUMENTATION_GUIDE.md"
MASTER_STATUS = KG / "MASTER_STATUS.md"
CHANGELOG     = KG / "CHANGELOG_KNOWLEDGE_GRAPHS.md"
ROADMAP       = KG / "ROADMAP.md"


# ---------------------------------------------------------------------------
# TestComprehensiveAnalysisHistoricalBanner
# ---------------------------------------------------------------------------
class TestComprehensiveAnalysisHistoricalBanner:
    """COMPREHENSIVE_ANALYSIS_2026_02_18.md now has a historical-notice banner."""

    @pytest.fixture(scope="class")
    def text(self):
        return COMPREHENSIVE.read_text()

    def test_historical_banner_present(self, text):
        assert "⚠️" in text, "historical warning emoji must be present"

    def test_historical_banner_says_historical_document(self, text):
        assert "Historical Document" in text

    def test_next_action_updated_from_stale(self, text):
        assert "Proceed with Phase 1 (Documentation Consolidation)" not in text, \
            "stale 'Proceed with Phase 1' action must be removed"

    def test_next_action_notes_completion(self, text):
        assert "complete as of v3.22" in text.lower() or \
               "All action items complete" in text or \
               "all action items resolved" in text.lower() or \
               "action items now complete" in text.lower(), \
            "footer must note that action items are complete"

    def test_next_review_updated_from_stale(self, text):
        assert "After Phase 1 & 2 completion (3-4 hours from now)" not in text, \
            "stale next-review wording must be removed"


# ---------------------------------------------------------------------------
# TestExecutiveSummaryHistoricalBanner
# ---------------------------------------------------------------------------
class TestExecutiveSummaryHistoricalBanner:
    """EXECUTIVE_SUMMARY_FINAL_2026_02_18.md now has a historical banner
    and its stale open [ ] items have been ticked [x]."""

    @pytest.fixture(scope="class")
    def text(self):
        return EXEC_SUMMARY.read_text()

    def test_historical_banner_present(self, text):
        assert "⚠️" in text and "Historical Document" in text

    def test_stale_unchecked_short_term_item_gone(self, text):
        assert "- [ ] Improve migration module test coverage 40% → 70%+" not in text, \
            "stale unchecked migration coverage item must be completed [x]"

    def test_stale_unchecked_medium_term_item_gone(self, text):
        assert "- [ ] Implement NOT operator" not in text, \
            "stale unchecked NOT-operator item must be completed [x]"

    def test_stale_unchecked_long_term_item_gone(self, text):
        assert "- [ ] Additional formats per ROADMAP.md" not in text, \
            "stale unchecked long-term item must be completed [x]"

    def test_all_items_checked(self, text):
        import re
        # All short/medium/long-term list items must be [x]
        unchecked = re.findall(r"^- \[ \] .+", text, re.MULTILINE)
        assert len(unchecked) == 0, \
            f"found {len(unchecked)} unchecked items in EXECUTIVE_SUMMARY: {unchecked}"


# ---------------------------------------------------------------------------
# TestRefactoringCompleteHistoricalBanner
# ---------------------------------------------------------------------------
class TestRefactoringCompleteHistoricalBanner:
    """REFACTORING_COMPLETE_2026_02_18.md now has a historical banner."""

    @pytest.fixture(scope="class")
    def text(self):
        return REFACTORING.read_text()

    def test_historical_banner_present(self, text):
        assert "⚠️" in text and "Historical Document" in text

    def test_master_status_ref_present(self, text):
        assert "MASTER_STATUS.md" in text, "must reference MASTER_STATUS.md"

    def test_current_version_mentioned(self, text):
        assert "v3.22" in text, "current version reference must be present in banner"


# ---------------------------------------------------------------------------
# TestDocumentationGuideUpdated
# ---------------------------------------------------------------------------
class TestDocumentationGuideUpdated:
    """DOCUMENTATION_GUIDE.md item-7 updated; Tier 6 now lists the 3 historical docs."""

    @pytest.fixture(scope="class")
    def text(self):
        return DOC_GUIDE.read_text()

    def test_stale_new_tag_removed_from_item7(self, text):
        assert "COMPREHENSIVE_ANALYSIS_2026_02_18.md)** (47KB) **NEW**" not in text, \
            "stale **NEW** tag must be removed from COMPREHENSIVE_ANALYSIS item"

    def test_item7_says_historical(self, text):
        # The item-7 description must now say "Historical"
        lines = text.splitlines()
        in_item7 = False
        for line in lines:
            if "COMPREHENSIVE_ANALYSIS_2026_02_18.md" in line and "**[" in line:
                in_item7 = True
            if in_item7 and ("Historical" in line or "historical" in line):
                return
            if in_item7 and line.startswith("8."):
                break
        pytest.fail("Item 7 (COMPREHENSIVE_ANALYSIS) must describe it as historical")

    def test_executive_summary_final_in_tier6(self, text):
        assert "EXECUTIVE_SUMMARY_FINAL_2026_02_18.md" in text, \
            "EXECUTIVE_SUMMARY_FINAL must be listed in DOCUMENTATION_GUIDE Tier 6"

    def test_refactoring_complete_in_tier6(self, text):
        assert "REFACTORING_COMPLETE_2026_02_18.md" in text, \
            "REFACTORING_COMPLETE must be listed in DOCUMENTATION_GUIDE Tier 6"

    def test_tier6_section_present(self, text):
        assert "Tier 6" in text or "Historical & Archived" in text


# ---------------------------------------------------------------------------
# TestVersionAgreement
# ---------------------------------------------------------------------------
class TestVersionAgreement:
    """MASTER_STATUS / CHANGELOG / ROADMAP agree on current version."""

    @pytest.fixture(scope="class")
    def ms(self): return MASTER_STATUS.read_text()

    @pytest.fixture(scope="class")
    def cl(self): return CHANGELOG.read_text()

    @pytest.fixture(scope="class")
    def rm(self): return ROADMAP.read_text()

    def test_master_status_version(self, ms):
        assert "3.22.20" in ms, "MASTER_STATUS must reference v3.22.20"

    def test_changelog_version(self, cl):
        assert "3.22.20" in cl, "CHANGELOG must have a 3.22.20 section"

    def test_roadmap_version(self, rm):
        assert "3.22.20" in rm, "ROADMAP must reference v3.22.20"
