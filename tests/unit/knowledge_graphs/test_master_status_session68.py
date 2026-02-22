"""
Session 68 doc integrity tests.

Validates the fixes applied to:
- cypher/README.md      (❌ Not Supported table → ✅ Implemented; Last Updated updated)
- core/README.md        (~80% → 100%; Phase 5 Planned → v4.0+; Version 2.0.0 → 3.22.22)
- docs/knowledge_graphs/MIGRATION_GUIDE.md  (NOT/CREATE/MERGE/DELETE workarounds → ✅ Implemented;
                                              Future Extraction Enhancements → ✅ Delivered;
                                              Version/Last Updated updated; planned versions updated)
- docs/knowledge_graphs/API_REFERENCE.md    (Known Limitations NOT/CREATE removed; version updated)
"""

import pathlib
import pytest

_KG = pathlib.Path(__file__).parents[3] / "ipfs_datasets_py" / "knowledge_graphs"
_DOCS = pathlib.Path(__file__).parents[3] / "docs" / "knowledge_graphs"

_CYPHER_README = _KG / "cypher" / "README.md"
_CORE_README   = _KG / "core" / "README.md"
_MIGRATION     = _DOCS / "MIGRATION_GUIDE.md"
_API_REF       = _DOCS / "API_REFERENCE.md"
_MASTER_STATUS = _KG / "MASTER_STATUS.md"
_CHANGELOG     = _KG / "CHANGELOG_KNOWLEDGE_GRAPHS.md"
_ROADMAP       = _KG / "ROADMAP.md"


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# cypher/README.md — stale ❌ Not Supported table replaced
# ---------------------------------------------------------------------------
class TestCypherReadmeNotSupportedFixed:
    """cypher/README.md: stale 'Not implemented' table replaced with ✅ Implemented."""

    def test_not_implemented_label_removed(self):
        """No bare 'Not implemented' cells should remain in the cypher README."""
        content = _read(_CYPHER_README)
        assert "Not implemented" not in content, \
            "cypher/README.md still contains stale 'Not implemented' text"

    def test_not_operator_shown_as_implemented(self):
        """`NOT` operator row should say ✅ Implemented."""
        content = _read(_CYPHER_README)
        assert "✅ Implemented" in content, \
            "cypher/README.md should contain '✅ Implemented' for NOT/CREATE/MERGE/DELETE"

    def test_create_relationships_shown_as_implemented(self):
        """`CREATE` relationships row should mention v2.1.0 implementation."""
        content = _read(_CYPHER_README)
        assert "v2.1.0" in content, \
            "cypher/README.md should reference v2.1.0 implementation"

    def test_last_updated_bumped(self):
        """Last Updated should be 2026-02-22."""
        content = _read(_CYPHER_README)
        assert "2026-02-22" in content, \
            "cypher/README.md Last Updated should be 2026-02-22"

    def test_stale_date_removed(self):
        """Stale 2026-02-17 date should be gone from footer."""
        content = _read(_CYPHER_README)
        # The old Last Updated: 2026-02-17 line should be gone
        assert "**Last Updated:** 2026-02-17" not in content, \
            "cypher/README.md still has stale Last Updated: 2026-02-17"


# ---------------------------------------------------------------------------
# core/README.md — stale coverage % and roadmap fixed
# ---------------------------------------------------------------------------
class TestCoreReadmeCoverageFixed:
    """core/README.md: ~80% test coverage fixed to 100%; Phase 5 Planned → v4.0+."""

    def test_coverage_updated_to_100(self):
        """Test Coverage should say 100%, not ~80%."""
        content = _read(_CORE_README)
        assert "100%" in content, \
            "core/README.md should say '100%' test coverage"

    def test_stale_80_percent_removed(self):
        """Stale ~80% coverage note should be gone."""
        content = _read(_CORE_README)
        assert "~80%" not in content, \
            "core/README.md still shows stale '~80%' test coverage"

    def test_phase5_not_just_planned(self):
        """Phase 5 should not say just 'Planned' — should say 'Deferred to v4.0+'."""
        content = _read(_CORE_README)
        assert "(Planned)" not in content, \
            "core/README.md still has stale 'Phase 5: Advanced optimization (Planned)'"

    def test_phase5_deferred_to_v4(self):
        """Phase 5 should reference v4.0+."""
        content = _read(_CORE_README)
        assert "v4.0+" in content, \
            "core/README.md should say 'Deferred to v4.0+' for Phase 5"

    def test_version_updated(self):
        """Version header should say 3.22.22."""
        content = _read(_CORE_README)
        assert "3.22.22" in content, \
            "core/README.md Version should be 3.22.22"


# ---------------------------------------------------------------------------
# docs/knowledge_graphs/MIGRATION_GUIDE.md — stale "Not implemented" rows removed
# ---------------------------------------------------------------------------
class TestMigrationGuideFixed:
    """MIGRATION_GUIDE.md: NOT/CREATE/MERGE/DELETE workarounds replaced with ✅ rows."""

    def test_not_implemented_workarounds_removed(self):
        """Stale 'Not implemented' workaround rows must be gone."""
        content = _read(_MIGRATION)
        assert "Not implemented" not in content, \
            "MIGRATION_GUIDE.md still has stale 'Not implemented' text"

    def test_all_features_shown_as_implemented(self):
        """The NOT/CREATE/MERGE/DELETE features should all show ✅ Implemented."""
        content = _read(_MIGRATION)
        assert "✅ Implemented" in content, \
            "MIGRATION_GUIDE.md should contain '✅ Implemented' for Cypher features"

    def test_future_extraction_table_replaced(self):
        """'Planned' extraction enhancements should be replaced by ✅ delivered entries."""
        content = _read(_MIGRATION)
        assert "Planned | v2.5.0" not in content, \
            "MIGRATION_GUIDE.md still has stale 'Planned | v2.5.0' extraction row"

    def test_extraction_shown_as_delivered(self):
        """Extraction features should show ✅ Implemented."""
        content = _read(_MIGRATION)
        assert "SRL" in content and "✅ Implemented" in content, \
            "MIGRATION_GUIDE.md should show SRL as ✅ Implemented"

    def test_version_updated(self):
        """Version header should say 3.22.22."""
        content = _read(_MIGRATION)
        assert "3.22.22" in content, \
            "MIGRATION_GUIDE.md Version should be 3.22.22"

    def test_last_updated_bumped(self):
        """Last Updated should be 2026-02-22."""
        content = _read(_MIGRATION)
        assert "2026-02-22" in content, \
            "MIGRATION_GUIDE.md Last Updated should be 2026-02-22"

    def test_stale_planned_versions_removed(self):
        """'Planned Q3 2026' in Version table should be gone."""
        content = _read(_MIGRATION)
        assert "Planned Q3 2026" not in content, \
            "MIGRATION_GUIDE.md still has stale 'Planned Q3 2026' in version table"


# ---------------------------------------------------------------------------
# docs/knowledge_graphs/API_REFERENCE.md — stale Known Limitations fixed
# ---------------------------------------------------------------------------
class TestAPIReferenceLimitationsFixed:
    """API_REFERENCE.md: NOT/CREATE 'Not Yet Supported' removed."""

    def test_not_yet_supported_list_removed(self):
        """Stale 'NOT operator — Workaround' bullet should be gone."""
        content = _read(_API_REF)
        # The specific "NOT operator in WHERE clauses - Workaround" pattern
        assert "- `NOT` operator in WHERE clauses - **Workaround:**" not in content, \
            "API_REFERENCE.md still has stale NOT workaround bullet"

    def test_create_workaround_removed(self):
        """Stale CREATE workaround bullet should be gone."""
        content = _read(_API_REF)
        assert "- `CREATE` for relationships - **Workaround:**" not in content, \
            "API_REFERENCE.md still has stale CREATE workaround bullet"

    def test_limitations_now_mention_subqueries(self):
        """Known Limitations section should mention subqueries as the remaining limit."""
        content = _read(_API_REF)
        assert "Subqueries" in content or "subqueries" in content, \
            "API_REFERENCE.md Known Limitations should note remaining subquery limitation"

    def test_version_updated(self):
        """Version header should say 3.22.22."""
        content = _read(_API_REF)
        assert "3.22.22" in content, \
            "API_REFERENCE.md Version should be 3.22.22"


# ---------------------------------------------------------------------------
# Version agreement across tracking docs
# ---------------------------------------------------------------------------
class TestVersionAgreement:
    """All three tracking docs should agree on v3.22.22."""

    def test_master_status_on_v3_22_22(self):
        content = _read(_MASTER_STATUS)
        assert "3.22.22" in content, \
            "MASTER_STATUS.md should contain 3.22.22"

    def test_changelog_has_3_22_22(self):
        content = _read(_CHANGELOG)
        assert "3.22.22" in content, \
            "CHANGELOG_KNOWLEDGE_GRAPHS.md should have [3.22.22] section"

    def test_roadmap_has_3_22_22(self):
        content = _read(_ROADMAP)
        assert "3.22.22" in content, \
            "ROADMAP.md should contain 3.22.22"
