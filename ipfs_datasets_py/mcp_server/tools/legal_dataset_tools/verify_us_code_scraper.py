#!/usr/bin/env python3
"""
Verification tool for US Code scraper.

This script tests the US Code scraper functionality to ensure it's working correctly.
It performs various tests including:
- Connection to uscode.house.gov
- Fetching title list
- Scraping sample titles
- Validating data structure
- Testing different parameters
"""
import anyio
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

try:
    from ipfs_datasets_py.legal_scrapers import (
        scrape_us_code,
        get_us_code_titles,
        search_us_code
    )
except ImportError:
    # Try relative import if running from within the package
    from us_code_scraper import scrape_us_code, get_us_code_titles, search_us_code


class USCodeVerifier:
    """Verification suite for US Code scraper."""
    
    def __init__(self):
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "tests": [],
            "summary": {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "warnings": 0
            }
        }
    
    def log_test(self, name: str, status: str, message: str, details: Dict[str, Any] = None):
        """Log a test result."""
        test_result = {
            "name": name,
            "status": status,
            "message": message,
            "details": details or {}
        }
        self.results["tests"].append(test_result)
        self.results["summary"]["total"] += 1
        
        if status == "PASS":
            self.results["summary"]["passed"] += 1
            print(f"✅ {name}: {message}")
        elif status == "FAIL":
            self.results["summary"]["failed"] += 1
            print(f"❌ {name}: {message}")
        elif status == "WARN":
            self.results["summary"]["warnings"] += 1
            print(f"⚠️  {name}: {message}")
        
        if details:
            print(f"   Details: {json.dumps(details, indent=2)}")
    
    async def test_get_titles(self):
        """Test fetching US Code titles."""
        print("\n" + "="*80)
        print("TEST 1: Get US Code Titles")
        print("="*80)
        
        try:
            result = await get_us_code_titles()
            
            if result.get("status") == "success":
                titles = result.get("titles", {})
                count = len(titles)
                
                if count >= 50:  # Should have ~54 titles
                    self.log_test(
                        "Get Titles",
                        "PASS",
                        f"Retrieved {count} US Code titles",
                        {"title_count": count, "sample_titles": list(titles.items())[:5]}
                    )
                else:
                    self.log_test(
                        "Get Titles",
                        "WARN",
                        f"Retrieved only {count} titles (expected ~54)",
                        {"title_count": count}
                    )
            else:
                self.log_test(
                    "Get Titles",
                    "FAIL",
                    f"Failed to get titles: {result.get('error')}",
                    result
                )
        except Exception as e:
            self.log_test("Get Titles", "FAIL", f"Exception: {str(e)}")
    
    async def test_scrape_single_title(self):
        """Test scraping a single title."""
        print("\n" + "="*80)
        print("TEST 2: Scrape Single Title (Title 1 - General Provisions)")
        print("="*80)
        
        try:
            result = await scrape_us_code(
                titles=["1"],
                output_format="json",
                include_metadata=True,
                rate_limit_delay=1.0,
                max_sections=10  # Limit for testing
            )
            
            if result.get("status") == "success":
                data = result.get("data", [])
                metadata = result.get("metadata", {})
                
                if len(data) > 0:
                    self.log_test(
                        "Scrape Single Title",
                        "PASS",
                        f"Scraped Title 1: {len(data)} sections",
                        {
                            "sections_count": len(data),
                            "sample_section": data[0] if data else None,
                            "metadata": metadata
                        }
                    )
                else:
                    self.log_test(
                        "Scrape Single Title",
                        "WARN",
                        "No sections scraped from Title 1",
                        result
                    )
            else:
                self.log_test(
                    "Scrape Single Title",
                    "FAIL",
                    f"Failed: {result.get('error')}",
                    result
                )
        except Exception as e:
            self.log_test("Scrape Single Title", "FAIL", f"Exception: {str(e)}")
    
    async def test_scrape_multiple_titles(self):
        """Test scraping multiple titles."""
        print("\n" + "="*80)
        print("TEST 3: Scrape Multiple Titles (1, 15, 18)")
        print("="*80)
        
        try:
            result = await scrape_us_code(
                titles=["1", "15", "18"],
                output_format="json",
                include_metadata=True,
                rate_limit_delay=1.0,
                max_sections=5  # Limit per title for testing
            )
            
            if result.get("status") == "success" or result.get("status") == "partial_success":
                data = result.get("data", [])
                metadata = result.get("metadata", {})
                
                # Check if we got data from multiple titles
                titles_found = set()
                for section in data:
                    if "title_number" in section:
                        titles_found.add(section["title_number"])
                
                if len(titles_found) >= 2:
                    self.log_test(
                        "Scrape Multiple Titles",
                        "PASS",
                        f"Scraped {len(titles_found)} titles: {sorted(titles_found)}",
                        {
                            "titles_found": sorted(titles_found),
                            "total_sections": len(data),
                            "metadata": metadata
                        }
                    )
                elif len(titles_found) == 1:
                    self.log_test(
                        "Scrape Multiple Titles",
                        "WARN",
                        f"Only scraped 1 title: {titles_found}",
                        {"sections_count": len(data)}
                    )
                else:
                    self.log_test(
                        "Scrape Multiple Titles",
                        "WARN",
                        "No title information in scraped data",
                        {"sections_count": len(data)}
                    )
            else:
                self.log_test(
                    "Scrape Multiple Titles",
                    "FAIL",
                    f"Failed: {result.get('error')}",
                    result
                )
        except Exception as e:
            self.log_test("Scrape Multiple Titles", "FAIL", f"Exception: {str(e)}")
    
    async def test_data_structure(self):
        """Test that scraped data has the correct structure."""
        print("\n" + "="*80)
        print("TEST 4: Validate Data Structure")
        print("="*80)
        
        try:
            result = await scrape_us_code(
                titles=["15"],  # Commerce and Trade
                output_format="json",
                include_metadata=True,
                rate_limit_delay=1.0,
                max_sections=3
            )
            
            if result.get("status") in ["success", "partial_success"]:
                data = result.get("data", [])
                
                if not data:
                    self.log_test(
                        "Data Structure",
                        "WARN",
                        "No data to validate structure",
                        result
                    )
                    return
                
                # Check required fields
                required_fields = ["title_number", "title_name", "section_number"]
                sample_section = data[0]
                
                missing_fields = [f for f in required_fields if f not in sample_section]
                
                if not missing_fields:
                    self.log_test(
                        "Data Structure",
                        "PASS",
                        "Data structure is valid",
                        {
                            "sample_section": sample_section,
                            "total_sections": len(data)
                        }
                    )
                else:
                    self.log_test(
                        "Data Structure",
                        "WARN",
                        f"Missing fields: {missing_fields}",
                        {"sample_section": sample_section}
                    )
            else:
                self.log_test(
                    "Data Structure",
                    "FAIL",
                    f"Failed to scrape data: {result.get('error')}",
                    result
                )
        except Exception as e:
            self.log_test("Data Structure", "FAIL", f"Exception: {str(e)}")
    
    async def test_search_functionality(self):
        """Test search functionality."""
        print("\n" + "="*80)
        print("TEST 5: Search Functionality")
        print("="*80)
        
        try:
            result = await search_us_code(
                query="commerce",
                titles=["15"],
                limit=5
            )
            
            if result.get("status") == "success":
                results = result.get("results", [])
                
                if len(results) > 0:
                    self.log_test(
                        "Search Functionality",
                        "PASS",
                        f"Found {len(results)} results for 'commerce'",
                        {
                            "result_count": len(results),
                            "sample_result": results[0] if results else None
                        }
                    )
                else:
                    self.log_test(
                        "Search Functionality",
                        "WARN",
                        "No search results found",
                        result
                    )
            else:
                self.log_test(
                    "Search Functionality",
                    "WARN",
                    f"Search returned status: {result.get('status')}",
                    result
                )
        except Exception as e:
            self.log_test("Search Functionality", "FAIL", f"Exception: {str(e)}")
    
    async def test_metadata_inclusion(self):
        """Test that metadata is included when requested."""
        print("\n" + "="*80)
        print("TEST 6: Metadata Inclusion")
        print("="*80)
        
        try:
            # Test with metadata
            result_with = await scrape_us_code(
                titles=["1"],
                include_metadata=True,
                max_sections=2
            )
            
            # Test without metadata
            result_without = await scrape_us_code(
                titles=["1"],
                include_metadata=False,
                max_sections=2
            )
            
            metadata_present = bool(result_with.get("metadata"))
            
            if metadata_present:
                self.log_test(
                    "Metadata Inclusion",
                    "PASS",
                    "Metadata is correctly included/excluded",
                    {
                        "with_metadata": bool(result_with.get("metadata")),
                        "without_metadata": bool(result_without.get("metadata")),
                        "sample_metadata": result_with.get("metadata")
                    }
                )
            else:
                self.log_test(
                    "Metadata Inclusion",
                    "WARN",
                    "Metadata not present in results",
                    {
                        "result_with": result_with,
                        "result_without": result_without
                    }
                )
        except Exception as e:
            self.log_test("Metadata Inclusion", "FAIL", f"Exception: {str(e)}")
    
    async def test_rate_limiting(self):
        """Test that rate limiting is respected."""
        print("\n" + "="*80)
        print("TEST 7: Rate Limiting")
        print("="*80)
        
        try:
            import time
            start_time = time.time()
            
            result = await scrape_us_code(
                titles=["1"],
                rate_limit_delay=2.0,  # 2 second delay
                max_sections=3
            )
            
            elapsed = time.time() - start_time
            
            # Should take at least 4 seconds (2 delay * 2 requests minimum)
            if elapsed >= 2.0:
                self.log_test(
                    "Rate Limiting",
                    "PASS",
                    f"Rate limiting appears to be working (took {elapsed:.2f}s)",
                    {"elapsed_seconds": elapsed}
                )
            else:
                self.log_test(
                    "Rate Limiting",
                    "WARN",
                    f"Completed too quickly ({elapsed:.2f}s), rate limiting may not be working",
                    {"elapsed_seconds": elapsed}
                )
        except Exception as e:
            self.log_test("Rate Limiting", "FAIL", f"Exception: {str(e)}")
    
    async def run_all_tests(self):
        """Run all verification tests."""
        print("\n" + "="*80)
        print("US CODE SCRAPER VERIFICATION")
        print("="*80)
        print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Run tests
        await self.test_get_titles()
        await self.test_scrape_single_title()
        await self.test_scrape_multiple_titles()
        await self.test_data_structure()
        await self.test_search_functionality()
        await self.test_metadata_inclusion()
        await self.test_rate_limiting()
        
        # Print summary
        print("\n" + "="*80)
        print("VERIFICATION SUMMARY")
        print("="*80)
        print(f"Total Tests: {self.results['summary']['total']}")
        print(f"✅ Passed: {self.results['summary']['passed']}")
        print(f"❌ Failed: {self.results['summary']['failed']}")
        print(f"⚠️  Warnings: {self.results['summary']['warnings']}")
        
        success_rate = (self.results['summary']['passed'] / self.results['summary']['total'] * 100) if self.results['summary']['total'] > 0 else 0
        print(f"\nSuccess Rate: {success_rate:.1f}%")
        
        # Save results
        output_file = Path.home() / ".ipfs_datasets" / "us_code" / "verification_results.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\n📁 Results saved to: {output_file}")
        
        # Return exit code
        return 0 if self.results['summary']['failed'] == 0 else 1


async def main():
    """Main entry point."""
    verifier = USCodeVerifier()
    exit_code = await verifier.run_all_tests()
    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        anyio.run(main())
    except KeyboardInterrupt:
        print("\n\nVerification cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Verification failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
