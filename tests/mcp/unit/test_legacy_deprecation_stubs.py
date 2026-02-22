"""
Session 38 — tests for legacy_mcp_tools deprecated stub files.

Many files in legacy_mcp_tools/ are pure deprecation wrappers:
  - They emit DeprecationWarning on import
  - They re-export the canonical class/function from the new module

We verify both behaviours for a representative set of stubs.
"""
import unittest
import warnings


def _reload_with_warning_capture(module_path: str):
    """Import (or reload) a module and collect any DeprecationWarnings emitted."""
    import importlib
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        mod = importlib.import_module(module_path)
    dep_warnings = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    return mod, dep_warnings


class TestLegacyAdminToolsStub(unittest.TestCase):
    """legacy_mcp_tools.admin_tools is a pure deprecation stub."""

    def setUp(self):
        self.mod, self.warnings = _reload_with_warning_capture(
            "ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools.admin_tools"
        )

    def test_deprecation_warning_emitted(self):
        # Re-import with warnings enabled to confirm the module fires DeprecationWarning.
        # Warnings may already be cached from earlier collection, so we force a reload.
        import importlib
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            importlib.reload(self.mod)
        dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        self.assertGreater(len(dep_warnings), 0)


class TestLegacyCreateEmbeddingsStub(unittest.TestCase):
    """legacy_mcp_tools.create_embeddings_tool is a pure deprecation stub."""

    def setUp(self):
        self.mod, self.warnings = _reload_with_warning_capture(
            "ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools.create_embeddings_tool"
        )

    def test_module_importable(self):
        self.assertIsNotNone(self.mod)


class TestLegacyShardEmbeddingsStub(unittest.TestCase):

    def test_module_importable(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools.shard_embeddings_tool as m
            self.assertIsNotNone(m)


class TestLegacyPatentScraperReExport(unittest.TestCase):
    """patent_scraper.py re-exports Patent, USPTOPatentScraper, etc."""

    def test_module_importable(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools.patent_scraper as m
            self.assertIsNotNone(m)

    def test_re_exports_patent_class(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools.patent_scraper as m
            self.assertTrue(hasattr(m, "Patent"))

    def test_re_exports_scraper_class(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools.patent_scraper as m
            self.assertTrue(hasattr(m, "USPTOPatentScraper"))

    def test_re_exports_criteria_class(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools.patent_scraper as m
            self.assertTrue(hasattr(m, "PatentSearchCriteria"))


class TestLegacyMunicipalScraperFallbacks(unittest.TestCase):
    """municipal_scraper_fallbacks.py re-exports from municipal_scraper_engine."""

    def test_module_importable(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools.municipal_scraper_fallbacks as m
            self.assertIsNotNone(m)

    def test_has_fallback_scraper_instance(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools.municipal_scraper_fallbacks as m
            self.assertTrue(hasattr(m, "fallback_scraper"))

    def test_has_scrape_with_fallbacks(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools.municipal_scraper_fallbacks as m
            self.assertTrue(hasattr(m, "scrape_with_fallbacks"))


class TestLegacyMigrationGuide(unittest.TestCase):
    """MIGRATION_GUIDE.md should exist next to the legacy tools."""

    def test_migration_guide_exists(self):
        from pathlib import Path
        import ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools as pkg
        guide = Path(pkg.__file__).parent / "MIGRATION_GUIDE.md"
        self.assertTrue(guide.exists(), f"MIGRATION_GUIDE.md not found at {guide}")

    def test_migration_guide_mentions_legal_dataset_tools(self):
        from pathlib import Path
        import ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools as pkg
        guide = Path(pkg.__file__).parent / "MIGRATION_GUIDE.md"
        if guide.exists():
            content = guide.read_text()
            self.assertIn("legal_dataset_tools", content)


if __name__ == "__main__":
    unittest.main()
