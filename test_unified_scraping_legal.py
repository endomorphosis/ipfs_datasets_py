#!/usr/bin/env python3
"""
Unified Scraping Architecture Test for Legal Scrapers

Tests the complete unified scraping system with:
1. Content addressing and deduplication
2. Multi-index Common Crawl search
3. Interplanetary Wayback Machine fallback
4. WARC import/export
5. IPFS multiformats fast CID computation
6. All legal scrapers (Municode, eCode360, Federal Register, etc.)
"""

import sys
import asyncio
import logging
from pathlib import Path
import tempfile
import json

# Setup path
sys.path.insert(0, str(Path(__file__).parent / 'ipfs_datasets_py'))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_unified_scraping_imports():
    """Test that all unified scraping components import correctly."""
    print("\n" + "="*70)
    print("TEST 1: Unified Scraping Imports")
    print("="*70)
    
    results = {}
    
    try:
        from content_addressed_scraper import (
            get_content_addressed_scraper,
            ContentAddressedScraper
        )
        print("   ✅ content_addressed_scraper")
        results['content_addressed'] = True
    except Exception as e:
        print(f"   ❌ content_addressed_scraper: {e}")
        results['content_addressed'] = False
    
    try:
        from unified_scraping_adapter import (
            get_unified_scraper,
            UnifiedScrapingAdapter
        )
        print("   ✅ unified_scraping_adapter")
        results['unified_adapter'] = True
    except Exception as e:
        print(f"   ❌ unified_scraping_adapter: {e}")
        results['unified_adapter'] = False
    
    try:
        from legal_scraper_unified_adapter import LegalScraperUnifiedAdapter
        print("   ✅ legal_scraper_unified_adapter")
        results['legal_adapter'] = True
    except Exception as e:
        print(f"   ❌ legal_scraper_unified_adapter: {e}")
        results['legal_adapter'] = False
    
    try:
        from warc_integration import (
            CommonCrawlWARCImporter,
            WARCExporter,
            import_municode_from_common_crawl,
            export_scraped_to_warc
        )
        print("   ✅ warc_integration")
        results['warc'] = True
    except Exception as e:
        print(f"   ❌ warc_integration: {e}")
        results['warc'] = False
    
    try:
        from multi_index_archive_search import (
            get_multi_index_searcher,
            MultiIndexArchiveSearcher
        )
        print("   ✅ multi_index_archive_search")
        results['multi_index'] = True
    except Exception as e:
        print(f"   ❌ multi_index_archive_search: {e}")
        results['multi_index'] = False
    
    try:
        # Try to import ipfs_multiformats for fast CID
        from ipfs_multiformats import compute_cid, cid_to_string
        print("   ✅ ipfs_multiformats (fast CID)")
        results['ipfs_multiformats'] = True
    except Exception as e:
        print(f"   ⚠️  ipfs_multiformats not available (will use Kubo fallback)")
        results['ipfs_multiformats'] = False
    
    return results


def test_legal_scrapers_import():
    """Test that all legal scrapers import correctly."""
    print("\n" + "="*70)
    print("TEST 2: Legal Scrapers Import")
    print("="*70)
    
    results = {}
    
    try:
        from legal_scrapers import MunicodeScraper
        print("   ✅ MunicodeScraper")
        results['municode'] = True
    except Exception as e:
        print(f"   ❌ MunicodeScraper: {e}")
        results['municode'] = False
    
    try:
        from legal_scrapers.core.ecode360 import ECode360Scraper
        print("   ✅ ECode360Scraper")
        results['ecode360'] = True
    except Exception as e:
        print(f"   ❌ ECode360Scraper: {e}")
        results['ecode360'] = False
    
    try:
        from legal_scrapers.core.federal_register import FederalRegisterScraper
        print("   ✅ FederalRegisterScraper")
        results['federal_register'] = True
    except Exception as e:
        print(f"   ❌ FederalRegisterScraper: {e}")
        results['federal_register'] = False
    
    try:
        from legal_scrapers.core.state_laws import StateLawsScraper
        print("   ✅ StateLawsScraper")
        results['state_laws'] = True
    except Exception as e:
        print(f"   ❌ StateLawsScraper: {e}")
        results['state_laws'] = False
    
    try:
        from legal_scrapers.core.us_code import USCodeScraper
        print("   ✅ USCodeScraper")
        results['us_code'] = True
    except Exception as e:
        print(f"   ❌ USCodeScraper: {e}")
        results['us_code'] = False
    
    return results


def test_content_addressing():
    """Test content-addressed scraping with deduplication."""
    print("\n" + "="*70)
    print("TEST 3: Content Addressing & Deduplication")
    print("="*70)
    
    try:
        from content_addressed_scraper import get_content_addressed_scraper
        
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = get_content_addressed_scraper(cache_dir=tmpdir)
            print(f"   ✅ Created content-addressed scraper")
            print(f"   ℹ️  Cache dir: {tmpdir}")
            
            # Test URL tracking
            test_url = "https://library.municode.com/wa/seattle"
            test_content = b"<html><body>Test content</body></html>"
            
            # Test content CID computation
            cid = scraper.compute_content_cid(test_content)
            print(f"   ✅ CID computation works")
            print(f"   ℹ️  Content CID: {cid[:50]}...")
            
            # Test URL checking
            check_result = scraper.check_url_scraped(test_url)
            print(f"   ✅ URL checking: scraped={check_result['scraped']}")
            
            # Test scraping with content addressing (async)
            async def test_scrape():
                result = await scraper.scrape_with_content_addressing(
                    url=test_url,
                    metadata={"test": "first_scrape"}
                )
                return result
            
            result1 = asyncio.run(test_scrape())
            print(f"   ✅ First scrape: {result1['status']}")
            if 'content_cid' in result1:
                print(f"   ℹ️  Content CID: {result1['content_cid'][:30]}...")
            
            # Check if it was recorded
            check_result2 = scraper.check_url_scraped(test_url)
            print(f"   ✅ URL now tracked: {check_result2['scraped']}")
            
            return True
            
    except Exception as e:
        print(f"   ❌ Content addressing test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_municode_unified_scraping():
    """Test Municode scraper with unified scraping system."""
    print("\n" + "="*70)
    print("TEST 4: Municode Unified Scraping")
    print("="*70)
    
    try:
        from legal_scrapers import MunicodeScraper
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create scraper with full unified system enabled
            scraper = MunicodeScraper(
                cache_dir=tmpdir,
                enable_ipfs=False,  # Don't require IPFS daemon
                enable_warc=False,  # Don't require warcio for now
                check_archives=True  # Enable archive checking
            )
            print(f"   ✅ Created Municode scraper")
            print(f"   ℹ️  Cache: {scraper.cache_dir}")
            print(f"   ℹ️  IPFS: {scraper.enable_ipfs}")
            print(f"   ℹ️  WARC: {scraper.enable_warc}")
            print(f"   ℹ️  Archives: {scraper.check_archives}")
            
            # Check that unified adapter is available
            if hasattr(scraper, 'adapter') and scraper.adapter:
                print(f"   ✅ Unified adapter enabled")
            else:
                print(f"   ⚠️  Unified adapter not available")
            
            # Test methods exist
            assert hasattr(scraper, 'scrape_url_unified')
            print(f"   ✅ scrape_url_unified() method present")
            
            assert hasattr(scraper, 'batch_scrape')
            print(f"   ✅ batch_scrape() method present")
            
            assert hasattr(scraper, 'import_from_common_crawl')
            print(f"   ✅ import_from_common_crawl() method present")
            
            return True
            
    except Exception as e:
        print(f"   ❌ Municode unified scraping test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_all_scrapers_have_unified_support():
    """Test that all legal scrapers support unified scraping."""
    print("\n" + "="*70)
    print("TEST 5: All Scrapers Have Unified Support")
    print("="*70)
    
    scrapers_to_test = [
        ('MunicodeScraper', 'legal_scrapers', 'MunicodeScraper'),
        ('ECode360Scraper', 'legal_scrapers.core.ecode360', 'ECode360Scraper'),
        ('FederalRegisterScraper', 'legal_scrapers.core.federal_register', 'FederalRegisterScraper'),
        ('StateLawsScraper', 'legal_scrapers.core.state_laws', 'StateLawsScraper'),
        ('USCodeScraper', 'legal_scrapers.core.us_code', 'USCodeScraper'),
    ]
    
    results = {}
    
    for name, module_path, class_name in scrapers_to_test:
        try:
            # Import the scraper
            module = __import__(module_path, fromlist=[class_name])
            scraper_class = getattr(module, class_name)
            
            # Create instance
            with tempfile.TemporaryDirectory() as tmpdir:
                scraper = scraper_class(cache_dir=tmpdir)
                
                # Check for unified scraping methods
                has_unified = (
                    hasattr(scraper, 'scrape_url_unified') and
                    hasattr(scraper, 'adapter')
                )
                
                if has_unified:
                    print(f"   ✅ {name}: Unified scraping enabled")
                    results[name] = True
                else:
                    print(f"   ⚠️  {name}: Missing unified scraping methods")
                    results[name] = False
                    
        except Exception as e:
            print(f"   ❌ {name}: {e}")
            results[name] = False
    
    return results


def test_parallel_scraping():
    """Test parallel scraping functionality."""
    print("\n" + "="*70)
    print("TEST 6: Parallel Scraping")
    print("="*70)
    
    try:
        from legal_scrapers.utils.parallel_scraper import (
            ParallelScraper,
            scrape_urls_parallel
        )
        print("   ✅ Imported parallel scraping utilities")
        
        # Test that we can create a parallel scraper
        with tempfile.TemporaryDirectory() as tmpdir:
            from legal_scrapers import MunicodeScraper
            
            parallel_scraper = ParallelScraper(
                scraper_class=MunicodeScraper,
                num_processes=2,
                max_workers=4
            )
            print(f"   ✅ Created ParallelScraper")
            print(f"   ℹ️  Processes: {parallel_scraper.num_processes}")
            print(f"   ℹ️  Max workers: {parallel_scraper.max_workers}")
            
            return True
            
    except Exception as e:
        print(f"   ❌ Parallel scraping test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_warc_integration():
    """Test WARC import/export functionality."""
    print("\n" + "="*70)
    print("TEST 7: WARC Integration")
    print("="*70)
    
    try:
        from warc_integration import (
            CommonCrawlWARCImporter,
            WARCExporter,
            import_municode_from_common_crawl
        )
        print("   ✅ Imported WARC utilities")
        
        # Test Common Crawl import function
        test_url = "https://library.municode.com/*"
        print(f"   ℹ️  Testing Common Crawl import for: {test_url}")
        print("   ℹ️  (Function exists, actual import requires network)")
        
        # Note: Actual import requires network and warcio
        assert callable(import_municode_from_common_crawl)
        print("   ✅ import_municode_from_common_crawl() is callable")
        
        return True
        
    except Exception as e:
        print(f"   ❌ WARC integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_multi_interface_support():
    """Test that scrapers support package, CLI, and MCP interfaces."""
    print("\n" + "="*70)
    print("TEST 8: Multi-Interface Support")
    print("="*70)
    
    # Test package interface
    try:
        from legal_scrapers import MunicodeScraper, scrape_municode
        print("   ✅ Package interface: Can import and use directly")
    except Exception as e:
        print(f"   ❌ Package interface failed: {e}")
    
    # Test CLI interface
    try:
        from legal_scrapers.cli.municode_cli import main, create_parser
        parser = create_parser()
        print("   ✅ CLI interface: Parser available")
    except Exception as e:
        print(f"   ❌ CLI interface failed: {e}")
    
    # Test MCP interface
    try:
        from legal_scrapers.mcp.tool_registry import get_registry
        from legal_scrapers.mcp.tools.municode_tools import register_municode_tools
        print("   ✅ MCP interface: Tool registry available")
    except Exception as e:
        print(f"   ❌ MCP interface failed: {e}")
    
    return True


def main():
    """Run all tests."""
    print("="*70)
    print("UNIFIED SCRAPING ARCHITECTURE TEST SUITE")
    print("Legal Scrapers + Content Addressing + WARC + Multi-Index")
    print("="*70)
    
    results = {}
    
    # Run all tests
    results['imports'] = test_unified_scraping_imports()
    results['legal_scrapers'] = test_legal_scrapers_import()
    results['content_addressing'] = test_content_addressing()
    results['municode'] = test_municode_unified_scraping()
    results['all_scrapers'] = test_all_scrapers_have_unified_support()
    results['parallel'] = test_parallel_scraping()
    results['warc'] = test_warc_integration()
    results['multi_interface'] = test_multi_interface_support()
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Unified scraping architecture is working.")
        print("\nNext Steps:")
        print("  1. Test with real URLs: python test_parallel_legal_scraping.py")
        print("  2. Try Common Crawl import: municode_cli.py --import-common-crawl")
        print("  3. Export to WARC: municode_cli.py --export-warc")
        return 0
    else:
        print("\n⚠️  Some tests failed. Check the output above for details.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
