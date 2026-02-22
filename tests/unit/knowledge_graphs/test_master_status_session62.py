"""
Session 62: Doc integrity tests for DOCUMENTATION_GUIDE.md, DEFERRED_FEATURES.md,
and IMPROVEMENT_TODO.md stale metadata fixes.

Changes covered:
1. DOCUMENTATION_GUIDE.md: Version 1.0→3.22.16; Last Updated 2026-02-18→2026-02-22;
   duplicate MASTER_STATUS.md entry removed; items renumbered 5–23 (from 6–24);
   Next Review updated; no-longer-stale document version at footer.
2. DEFERRED_FEATURES.md: Last Updated 2026-02-20→2026-02-22; stale v2.5.0 ref removed.
3. IMPROVEMENT_TODO.md: scope path double-prefix fixed.
"""

import os
import pathlib

import pytest

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
_KG_DIR = pathlib.Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py" / "knowledge_graphs"

def _read(filename: str) -> str:
    path = _KG_DIR / filename
    assert path.exists(), f"File not found: {path}"
    return path.read_text(encoding="utf-8")


# ===========================================================================
# TestDocumentationGuideVersion
# ===========================================================================
class TestDocumentationGuideVersion:
    """DOCUMENTATION_GUIDE.md version + date fixes."""

    def setup_method(self):
        self.content = _read("DOCUMENTATION_GUIDE.md")

    def test_version_header_is_current(self):
        """Version header should now be 3.22.16, not the stale 1.0."""
        assert "3.22.16" in self.content, \
            "DOCUMENTATION_GUIDE.md must show Version: 3.22.16"

    def test_stale_version_1_0_absent_in_header(self):
        """'Version: 1.0' (header form) should no longer appear."""
        assert "**Version:** 1.0" not in self.content, \
            "Stale '**Version:** 1.0' must be removed from DOCUMENTATION_GUIDE.md"

    def test_last_updated_is_current(self):
        """Last Updated should be 2026-02-22."""
        assert "2026-02-22" in self.content, \
            "DOCUMENTATION_GUIDE.md must contain Last Updated: 2026-02-22"

    def test_stale_date_2026_02_18_absent(self):
        """Stale date 2026-02-18 should no longer appear (replaced by 2026-02-22)."""
        assert "2026-02-18" not in self.content, \
            "Stale date 2026-02-18 must be removed from DOCUMENTATION_GUIDE.md"

    def test_next_review_not_stale_q2_2026(self):
        """'Next Review: Q2 2026' should be replaced with a non-time-bound statement."""
        assert "**Next Review:** Q2 2026" not in self.content, \
            "Stale '**Next Review:** Q2 2026' must be replaced"


# ===========================================================================
# TestDocumentationGuideDuplicateEntry
# ===========================================================================
class TestDocumentationGuideDuplicateEntry:
    """DOCUMENTATION_GUIDE.md duplicate MASTER_STATUS.md entry removed."""

    def setup_method(self):
        self.content = _read("DOCUMENTATION_GUIDE.md")

    def test_master_status_listed_exactly_once_as_numbered_item(self):
        """MASTER_STATUS.md should appear as a numbered list item exactly once."""
        import re
        # Numbered items that link to MASTER_STATUS.md: e.g. "4. **[MASTER_STATUS.md]..."
        numbered_refs = re.findall(r'\d+\. \*\*\[MASTER_STATUS\.md\]', self.content)
        assert len(numbered_refs) == 1, \
            f"Expected 1 numbered MASTER_STATUS.md entry, got {len(numbered_refs)}"

    def test_item_23_exists(self):
        """After renumbering, item 23 should be the last numbered doc entry."""
        assert "\n23. **" in self.content, \
            "Item 23 should exist after renumbering (was 24 before duplicate removal)"

    def test_item_24_absent(self):
        """Item 24 should not exist (was removed via duplicate elimination)."""
        assert "\n24. **" not in self.content, \
            "Item 24 should not exist after duplicate removal reduced list to 23 items"

    def test_old_duplicate_item_description_absent(self):
        """The duplicate item's unique description ('Coverage and priority information') should be gone."""
        assert "Coverage and priority information" not in self.content, \
            "The duplicate MASTER_STATUS.md entry description must be removed"

    def test_deferred_features_description_updated(self):
        """DEFERRED_FEATURES.md description should note all features are now implemented."""
        assert "all ✅ implemented" in self.content, \
            "DEFERRED_FEATURES.md description in guide should note 'all ✅ implemented'"


# ===========================================================================
# TestDeferredFeaturesMetadata
# ===========================================================================
class TestDeferredFeaturesMetadata:
    """DEFERRED_FEATURES.md stale date and v2.5.0 reference fixes."""

    def setup_method(self):
        self.content = _read("DEFERRED_FEATURES.md")

    def test_last_updated_is_current(self):
        """Last Updated footer should now be 2026-02-22."""
        assert "2026-02-22" in self.content, \
            "DEFERRED_FEATURES.md must show Last Updated: 2026-02-22"

    def test_stale_last_updated_session4_absent(self):
        """Old 'Last Updated: 2026-02-20 (session 4)' must be replaced."""
        assert "2026-02-20 (session 4)" not in self.content, \
            "Stale 'Last Updated: 2026-02-20 (session 4)' must be removed"

    def test_stale_v2_5_0_review_reference_absent(self):
        """'before v2.5.0 release' is a stale reference and must be removed."""
        assert "before v2.5.0 release" not in self.content, \
            "Stale 'before v2.5.0 release' text must be removed from Next Review"

    def test_next_review_q3_2026_present(self):
        """Next Review Q3 2026 line should still be present (just without v2.5.0 ref)."""
        assert "Q3 2026" in self.content, \
            "DEFERRED_FEATURES.md Next Review should still reference Q3 2026"


# ===========================================================================
# TestImprovementTodoPath
# ===========================================================================
class TestImprovementTodoPath:
    """IMPROVEMENT_TODO.md scope path double-prefix fix."""

    def setup_method(self):
        self.content = _read("IMPROVEMENT_TODO.md")

    def test_correct_scope_path_present(self):
        """Scope statement must reference the correct path: ipfs_datasets_py/knowledge_graphs/."""
        assert "ipfs_datasets_py/knowledge_graphs/" in self.content, \
            "IMPROVEMENT_TODO.md scope path must be ipfs_datasets_py/knowledge_graphs/"

    def test_double_prefix_scope_path_absent(self):
        """Old double-prefix path in the **Scope:** line must be gone (session log docs may mention it)."""
        # Only check the Scope/Note-on-pathing lines (not the session log which documents the fix)
        header_lines = [line for line in self.content.split("\n")
                        if line.startswith("**Scope:**") or line.startswith("**Note on pathing:**")]
        for line in header_lines:
            assert "ipfs_datasets_py/ipfs_datasets_py/knowledge_graphs/" not in line, \
                f"Double-prefix path found in header line: {line!r}"

    def test_old_pathing_note_fixed(self):
        """The Note-on-pathing line must not contain the old double-prefix."""
        lines = self.content.split("\n")
        for line in lines:
            if "Note on pathing" in line or "ipfs_datasets_py/ipfs_datasets_py/logic" in line:
                assert "ipfs_datasets_py/ipfs_datasets_py/logic/knowledge_graphs" not in line, \
                    "Old double-prefix path in Note-on-pathing must be cleaned up"

    def test_logic_subpath_corrected(self):
        """The corrected pathing note should reference 'ipfs_datasets_py/logic/knowledge_graphs' (no double prefix)."""
        assert "ipfs_datasets_py/logic/knowledge_graphs" in self.content, \
            "Note-on-pathing should mention ipfs_datasets_py/logic/knowledge_graphs as the old wrong path"
