#!/usr/bin/env python3
"""
Comprehensive test suite for all 51 state scrapers with parquet output.

This script:
1. Tests each of the 51 state scrapers by actually scraping data
2. Validates that each scraper can process real webpages
3. Saves results to individual parquet files for each state
4. Verifies normalized schema for all scraped data
5. Keeps samples saved on disk for inspection and validation

Test results are saved to: ~/.ipfs_datasets/state_laws/test_samples/
Each state gets its own parquet file: <state_code>_sample.parquet
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
import json

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
    HAS_PARQUET = True
except ImportError:
    HAS_PARQUET = False
    print("⚠️  Warning: pandas and pyarrow not installed. Will use JSON fallback.")
    print("   Install with: pip install pandas pyarrow")

from state_scrapers import (
    StateScraperRegistry,
    get_scraper_for_state,
    NormalizedStatute
)
from state_scrapers.base_scraper import BaseStateScraper


class StateLawsTester:
    """Comprehensive tester for all state law scrapers with parquet output."""
    
    def __init__(self, output_dir: str = None):
        """Initialize tester with output directory."""
        if output_dir is None:
            output_dir = os.path.expanduser("~/.ipfs_datasets/state_laws/test_samples")
        
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Also create JSON backup directory
        self.json_dir = self.output_dir / "json_backup"
        self.json_dir.mkdir(parents=True, exist_ok=True)
        
        self.results = {}
        self.test_start = datetime.now()
        
    def _save_to_parquet(self, state_code: str, data: List[Dict[str, Any]]):
        """Save scraped data to parquet file."""
        if not HAS_PARQUET or not data:
            return
        
        try:
            df = pd.DataFrame(data)
            parquet_file = self.output_dir / f"{state_code}_sample.parquet"
            df.to_parquet(parquet_file, engine='pyarrow', compression='snappy')
            print(f"   ✓ Saved {len(data)} records to {parquet_file}")
        except Exception as e:
            print(f"   ⚠️  Failed to save parquet for {state_code}: {e}")
    
    def _save_to_json(self, state_code: str, data: List[Dict[str, Any]]):
        """Save scraped data to JSON file as backup."""
        if not data:
            return
        
        try:
            json_file = self.json_dir / f"{state_code}_sample.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
            print(f"   ✓ Saved {len(data)} records to JSON backup")
        except Exception as e:
            print(f"   ⚠️  Failed to save JSON for {state_code}: {e}")
    
    async def test_state_scraper(self, state_code: str, state_name: str) -> Dict[str, Any]:
        """
        Test a single state scraper by actually scraping data.
        
        Args:
            state_code: Two-letter state code (e.g., "CA")
            state_name: Full state name (e.g., "California")
        
        Returns:
            Dictionary with test results
        """
        result = {
            "state_code": state_code,
            "state_name": state_name,
            "success": False,
            "scraped_count": 0,
            "error": None,
            "base_url": None,
            "codes_available": 0,
            "sample_data": []
        }
        
        try:
            # Get scraper for this state
            scraper = get_scraper_for_state(state_code, state_name)
            
            if scraper is None:
                result["error"] = "No scraper found"
                return result
            
            # Get base URL
            result["base_url"] = scraper.get_base_url()
            
            # Get available codes
            codes = scraper.get_code_list()
            result["codes_available"] = len(codes)
            
            print(f"\n{'='*80}")
            print(f"Testing: {state_name} ({state_code})")
            print(f"{'='*80}")
            print(f"Scraper: {scraper.__class__.__name__}")
            print(f"Base URL: {result['base_url']}")
            print(f"Codes Available: {result['codes_available']}")
            
            if not codes:
                result["error"] = "No codes available"
                print(f"⚠️  No codes available for {state_name}")
                return result
            
            # Scrape first code as a sample (limit to 10 statutes)
            print(f"\nScraping sample from first code: {codes[0]['name']}...")
            statutes = await scraper.scrape_code(
                code_name=codes[0]['name'],
                code_url=codes[0]['url']
            )
            
            # Limit to first 10 statutes for testing
            statutes = statutes[:10]
            
            result["scraped_count"] = len(statutes)
            print(f"✓ Scraped {result['scraped_count']} statutes (limited to 10 for testing)")
            
            # Convert to dictionaries
            for statute in statutes:
                if isinstance(statute, NormalizedStatute):
                    statute_dict = statute.to_dict()
                else:
                    statute_dict = statute
                result["sample_data"].append(statute_dict)
            
            # Validate schema
            if result["sample_data"]:
                print(f"\nValidating schema for {len(result['sample_data'])} statutes...")
                schema_valid = self._validate_schema(result["sample_data"])
                if schema_valid:
                    print("✓ Schema validation passed")
                    result["success"] = True
                    
                    # Save to parquet
                    print(f"\nSaving data for {state_code}...")
                    self._save_to_parquet(state_code, result["sample_data"])
                    self._save_to_json(state_code, result["sample_data"])
                else:
                    result["error"] = "Schema validation failed"
                    print("✗ Schema validation failed")
            else:
                result["error"] = "No data scraped"
                print("⚠️  No data scraped")
                
        except Exception as e:
            result["error"] = str(e)
            print(f"✗ Error testing {state_name}: {e}")
        
        return result
    
    def _validate_schema(self, data: List[Dict[str, Any]]) -> bool:
        """Validate that scraped data follows NormalizedStatute schema."""
        required_fields = [
            'state_code', 'state_name', 'statute_id', 'code_name',
            'section_number', 'full_text', 'legal_area', 'source_url',
            'official_cite', 'scraped_at', 'scraper_version'
        ]
        
        for statute in data:
            for field in required_fields:
                if field not in statute:
                    print(f"   ✗ Missing required field: {field}")
                    return False
        
        return True
    
    async def test_all_states(self, max_concurrent: int = 3):
        """
        Test all 51 state scrapers.
        
        Args:
            max_concurrent: Maximum number of concurrent scraping operations
        """
        print("="*80)
        print("COMPREHENSIVE STATE SCRAPER TESTING WITH PARQUET OUTPUT")
        print("Testing all 51 US jurisdictions (50 states + DC)")
        print("="*80)
        print(f"\nOutput directory: {self.output_dir}")
        print(f"JSON backup directory: {self.json_dir}")
        print(f"Max concurrent scrapers: {max_concurrent}")
        print(f"Test started: {self.test_start}")
        
        # Get all registered states
        all_states = StateScraperRegistry.get_all_registered_states()
        print(f"\nTotal states to test: {len(all_states)}")
        
        if len(all_states) != 51:
            print(f"⚠️  WARNING: Expected 51 states, found {len(all_states)}")
        
        # Create semaphore to limit concurrent operations
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def test_with_semaphore(state_code: str):
            async with semaphore:
                # Use get_scraper_for_state which handles state name lookup
                scraper = get_scraper_for_state(state_code, state_code)
                if scraper:
                    state_name = scraper.state_name
                else:
                    state_name = state_code
                return await self.test_state_scraper(state_code, state_name)
        
        # Test all states concurrently (but limited)
        tasks = [
            test_with_semaphore(state_code)
            for state_code in all_states
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for result in results:
            if isinstance(result, Exception):
                print(f"\n✗ Exception: {result}")
                continue
            
            state_code = result['state_code']
            self.results[state_code] = result
        
        # Generate summary report
        self._generate_summary_report()
    
    def _generate_summary_report(self):
        """Generate and display summary report."""
        test_end = datetime.now()
        duration = test_end - self.test_start
        
        print("\n" + "="*80)
        print("TEST SUMMARY REPORT")
        print("="*80)
        
        total = len(self.results)
        successful = sum(1 for r in self.results.values() if r['success'])
        failed = total - successful
        total_scraped = sum(r['scraped_count'] for r in self.results.values())
        
        print(f"\nTotal states tested: {total}")
        print(f"Successful: {successful} ({successful/total*100:.1f}%)")
        print(f"Failed: {failed} ({failed/total*100:.1f}%)")
        print(f"Total statutes scraped: {total_scraped}")
        print(f"Test duration: {duration}")
        
        # List successful states
        if successful > 0:
            print(f"\n✅ SUCCESSFUL STATES ({successful}):")
            for state_code, result in sorted(self.results.items()):
                if result['success']:
                    print(f"   {state_code}: {result['state_name']} - "
                          f"{result['scraped_count']} statutes from {result['codes_available']} codes")
        
        # List failed states
        if failed > 0:
            print(f"\n❌ FAILED STATES ({failed}):")
            for state_code, result in sorted(self.results.items()):
                if not result['success']:
                    error = result.get('error', 'Unknown error')
                    print(f"   {state_code}: {result['state_name']} - {error}")
        
        # Parquet files generated
        parquet_files = list(self.output_dir.glob("*.parquet"))
        json_files = list(self.json_dir.glob("*.json"))
        
        print(f"\n📁 FILES GENERATED:")
        print(f"   Parquet files: {len(parquet_files)}")
        print(f"   JSON backup files: {len(json_files)}")
        print(f"   Location: {self.output_dir}")
        
        # Save summary to JSON
        summary_file = self.output_dir / "test_summary.json"
        summary = {
            "test_start": self.test_start.isoformat(),
            "test_end": test_end.isoformat(),
            "duration_seconds": duration.total_seconds(),
            "total_states": total,
            "successful": successful,
            "failed": failed,
            "total_statutes_scraped": total_scraped,
            "parquet_files": len(parquet_files),
            "json_files": len(json_files),
            "results": self.results
        }
        
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, default=str)
        
        print(f"   Summary saved to: {summary_file}")
        
        print("\n" + "="*80)
        if failed == 0:
            print("🎉 ALL TESTS PASSED! 🎉")
            print("✅ All 51 state scrapers successfully processed real webpages")
            print("✅ All data saved to parquet files for inspection")
            print("✅ All schemas validated")
        else:
            print(f"⚠️  {failed} states failed. See details above.")
        print("="*80)


async def main():
    """Main entry point for testing."""
    # Create tester
    tester = StateLawsTester()
    
    # Test all states
    await tester.test_all_states(max_concurrent=3)
    
    return tester


if __name__ == "__main__":
    # Check for parquet support
    if not HAS_PARQUET:
        print("\n⚠️  WARNING: pandas and pyarrow not installed!")
        print("Installing required packages...")
        import subprocess
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pandas", "pyarrow"])
            print("✓ Packages installed. Please run the script again.")
            sys.exit(0)
        except Exception as e:
            print(f"✗ Failed to install packages: {e}")
            print("Will continue with JSON-only output...")
    
    # Run tests
    print("\nStarting comprehensive state scraper tests...")
    print("This will scrape real data from all 51 state legislative websites.")
    print("Results will be saved to parquet files for validation.\n")
    
    tester = asyncio.run(main())
    
    # Exit with appropriate code
    failed = sum(1 for r in tester.results.values() if not r['success'])
    sys.exit(0 if failed == 0 else 1)
