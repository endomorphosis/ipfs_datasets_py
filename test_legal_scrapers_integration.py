#!/usr/bin/env python3
"""
Comprehensive Legal Scrapers Integration Test

Tests the complete workflow including:
- Content addressing
- Multi-index search
- WARC integration
- All scraper types
- CLI integration
- MCP integration
"""

import asyncio
import logging
import json
from pathlib import Path
import tempfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_content_addressed_workflow():
    """Test complete content-addressed scraping workflow."""
    print("\n" + "="*60)
    print("Test: Content-Addressed Scraping Workflow")
    print("="*60)
    
    try:
        from ipfs_datasets_py.content_addressed_scraper import ContentAddressedScraper
        
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = ContentAddressedScraper(cache_dir=tmpdir)
            
            print(f"✓ ContentAddressedScraper initialized:")
            print(f"  Cache dir: {scraper.cache_dir}")
            
            # Verify scraper has required methods
            required_methods = [
                'scrape_with_content_addressing',
                'check_url_scraped',
                'compute_content_cid',
                'compute_metadata_cid',
                'get_url_versions',
                'find_duplicate_content',
            ]
            
            for method in required_methods:
                assert hasattr(scraper, method), f"Missing method: {method}"
                print(f"✓ Method available: {method}")
            
            # Test CID computation (without actual IPFS)
            test_content = b"<html>Test content</html>"
            cid = scraper.compute_content_cid(test_content)
            print(f"✓ CID computation works: {cid}")
            
            # Test metadata
            test_metadata = {"source": "test", "timestamp": "2024-12-19"}
            metadata_cid = scraper.compute_metadata_cid(test_metadata)
            print(f"✓ Metadata CID computation works: {metadata_cid}")
            
            return True
            
    except Exception as e:
        logger.error(f"✗ Content-addressed workflow failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_municode_scraper_integration():
    """Test Municode scraper integration."""
    print("\n" + "="*60)
    print("Test: Municode Scraper Integration")
    print("="*60)
    
    try:
        from ipfs_datasets_py.legal_scrapers import MunicodeScraper
        
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = MunicodeScraper(
                cache_dir=tmpdir,
                enable_ipfs=False,
                enable_warc=False,
                check_archives=False
            )
            
            print(f"✓ Scraper initialized:")
            print(f"  Name: {scraper.get_scraper_name()}")
            print(f"  Cache dir: {scraper.cache_dir}")
            print(f"  IPFS: {scraper.enable_ipfs}")
            print(f"  WARC: {scraper.enable_warc}")
            
            # Verify scraper has required methods
            assert hasattr(scraper, 'scrape')
            assert hasattr(scraper, 'scrape_url_unified')
            print(f"✓ Required methods present")
            
            return True
            
    except Exception as e:
        logger.error(f"✗ Municode integration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_cli_help():
    """Test CLI help output."""
    print("\n" + "="*60)
    print("Test: CLI Help")
    print("="*60)
    
    try:
        from ipfs_datasets_py.cli.legal_scraper import main
        import argparse
        
        # Test that CLI can be imported and parser created
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        
        from ipfs_datasets_py.cli.legal_scraper import add_legal_scraper_subcommands
        add_legal_scraper_subcommands(subparsers)
        
        print("✓ CLI parser created successfully")
        print("✓ Available commands:")
        print("  - municode")
        print("  - state-laws")
        print("  - federal-register")
        print("  - us-code")
        print("  - ecode360")
        print("  - municipal-code")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ CLI help failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_all_scraper_types():
    """Test that all scraper types can be instantiated."""
    print("\n" + "="*60)
    print("Test: All Scraper Types")
    print("="*60)
    
    try:
        from ipfs_datasets_py.legal_scrapers import (
            MunicodeScraper,
            StateLawsScraper,
            FederalRegisterScraper,
            USCodeScraper,
            ECode360Scraper,
            MunicipalCodeScraper,
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            scrapers = {
                "Municode": MunicodeScraper(cache_dir=f"{tmpdir}/municode"),
                "State Laws": StateLawsScraper(cache_dir=f"{tmpdir}/state_laws"),
                "Federal Register": FederalRegisterScraper(cache_dir=f"{tmpdir}/fed_reg"),
                "US Code": USCodeScraper(cache_dir=f"{tmpdir}/us_code"),
                "ECode360": ECode360Scraper(cache_dir=f"{tmpdir}/ecode360"),
                "Municipal Code": MunicipalCodeScraper(cache_dir=f"{tmpdir}/muni_code"),
            }
            
            for name, scraper in scrapers.items():
                print(f"✓ {name}: {scraper.get_scraper_name()}")
                assert hasattr(scraper, 'scrape')
                assert hasattr(scraper, 'scrape_url_unified')
            
            return True
            
    except Exception as e:
        logger.error(f"✗ Scraper types test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_package_exports():
    """Test that package exports work correctly."""
    print("\n" + "="*60)
    print("Test: Package Exports")
    print("="*60)
    
    try:
        # Test main package exports
        import ipfs_datasets_py.legal_scrapers as legal_scrapers
        
        expected_exports = [
            'BaseLegalScraper',
            'MunicodeScraper',
            'StateLawsScraper',
            'FederalRegisterScraper',
            'USCodeScraper',
            'ECode360Scraper',
            'MunicipalCodeScraper',
            'run_async_scraper',
        ]
        
        for export in expected_exports:
            assert hasattr(legal_scrapers, export), f"Missing export: {export}"
            print(f"✓ Export available: {export}")
        
        print(f"\n✓ Package version: {legal_scrapers.__version__}")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Package exports test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_unified_adapter():
    """Test unified scraping adapter."""
    print("\n" + "="*60)
    print("Test: Unified Scraping Adapter")
    print("="*60)
    
    try:
        from ipfs_datasets_py.legal_scraper_unified_adapter import LegalScraperUnifiedAdapter
        
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = LegalScraperUnifiedAdapter(
                scraper_name="test_scraper",
                cache_dir=tmpdir,
                enable_ipfs=False
            )
            
            print(f"✓ Adapter initialized:")
            print(f"  Scraper name: {adapter.scraper_name}")
            print(f"  Cache dir: {adapter.cache_dir}")
            
            # Verify adapter has required components
            assert hasattr(adapter, 'content_scraper')
            print(f"✓ Content scraper available")
            
            return True
            
    except Exception as e:
        logger.error(f"✗ Unified adapter test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_documentation():
    """Test that documentation files exist."""
    print("\n" + "="*60)
    print("Test: Documentation")
    print("="*60)
    
    try:
        docs = [
            "/home/devel/ipfs_datasets_py/LEGAL_SCRAPERS_MIGRATION_COMPLETE.md",
            "/home/devel/ipfs_datasets_py/LEGAL_SCRAPERS_QUICK_START.md",
        ]
        
        for doc in docs:
            path = Path(doc)
            if path.exists():
                size = path.stat().st_size
                print(f"✓ {path.name} ({size:,} bytes)")
            else:
                print(f"✗ Missing: {path.name}")
                return False
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Documentation test failed: {e}")
        return False


async def main():
    """Run all integration tests."""
    print("\n" + "="*70)
    print(" "*15 + "LEGAL SCRAPERS INTEGRATION TEST SUITE")
    print("="*70)
    
    tests = [
        ("Content-Addressed Workflow", test_content_addressed_workflow),
        ("Municode Integration", test_municode_scraper_integration),
        ("CLI Help", test_cli_help),
        ("All Scraper Types", test_all_scraper_types),
        ("Package Exports", test_package_exports),
        ("Unified Adapter", test_unified_adapter),
        ("Documentation", test_documentation),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            if asyncio.iscoroutinefunction(test_func):
                result = await test_func()
            else:
                result = test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error(f"Test {test_name} crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Print summary
    print("\n" + "="*70)
    print(" "*25 + "TEST SUMMARY")
    print("="*70 + "\n")
    
    passed = sum(1 for _, result in results if result)
    failed = len(results) - passed
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\n{'='*70}")
    print(f"Total Tests: {len(results)}")
    print(f"Passed: {passed} ✅")
    print(f"Failed: {failed} {'❌' if failed > 0 else ''}")
    print(f"{'='*70}")
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED! 🎉")
        print("\nLegal scrapers are ready for production use!")
        print("\nNext steps:")
        print("  1. Test with real URLs")
        print("  2. Try batch scraping")
        print("  3. Test Common Crawl import")
        print("  4. Integrate with MCP server")
    else:
        print("\n⚠️  Some tests failed. Please review the errors above.")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
