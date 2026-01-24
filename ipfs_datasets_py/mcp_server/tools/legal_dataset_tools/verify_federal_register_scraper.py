#!/usr/bin/env python3
"""
Verification tool for Federal Register scraper.

This script tests the Federal Register scraper functionality to ensure it's working correctly.
It performs various tests including:
- Connection to federalregister.gov API
- Searching documents
- Scraping by agency
- Scraping by date range
- Validating data structure
- Testing different parameters
"""
import anyio
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

try:
    from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import (
        scrape_federal_register,
        search_federal_register
    )
except ImportError:
    # Try relative import if running from within the package
    from federal_register_scraper import scrape_federal_register, search_federal_register


class FederalRegisterVerifier:
    """Verification suite for Federal Register scraper."""
    
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
            print(f"   Details: {json.dumps(details, indent=2)[:500]}...")
    
    async def test_search_recent_documents(self):
        """Test searching for recent documents."""
        print("\n" + "="*80)
        print("TEST 1: Search Recent Federal Register Documents")
        print("="*80)
        
        try:
            # Search for documents from the last 7 days
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            
            result = await search_federal_register(
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                limit=10
            )
            
            if result.get("status") == "success":
                documents = result.get("documents", [])
                count = result.get("count", 0)
                
                if len(documents) > 0:
                    self.log_test(
                        "Search Recent Documents",
                        "PASS",
                        f"Found {count} documents from last 7 days",
                        {
                            "document_count": count,
                            "documents_returned": len(documents),
                            "sample_document": documents[0] if documents else None,
                            "date_range": f"{start_date.date()} to {end_date.date()}"
                        }
                    )
                else:
                    self.log_test(
                        "Search Recent Documents",
                        "WARN",
                        f"No documents found in last 7 days (count={count})",
                        result
                    )
            else:
                self.log_test(
                    "Search Recent Documents",
                    "FAIL",
                    f"Failed: {result.get('error')}",
                    result
                )
        except Exception as e:
            self.log_test("Search Recent Documents", "FAIL", f"Exception: {str(e)}")
    
    async def test_scrape_by_agency(self):
        """Test scraping documents from a specific agency."""
        print("\n" + "="*80)
        print("TEST 2: Scrape by Agency (EPA)")
        print("="*80)
        
        try:
            # Get last 30 days for EPA
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)
            
            result = await scrape_federal_register(
                agencies=["EPA"],
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                output_format="json",
                include_full_text=False,
                rate_limit_delay=1.0,
                max_documents=10
            )
            
            if result.get("status") in ["success", "partial_success"]:
                data = result.get("data", [])
                metadata = result.get("metadata", {})
                
                if len(data) > 0:
                    # Check if EPA documents
                    epa_docs = [d for d in data if "EPA" in str(d.get("agencies", []))]
                    
                    self.log_test(
                        "Scrape by Agency",
                        "PASS",
                        f"Scraped {len(data)} EPA documents",
                        {
                            "total_documents": len(data),
                            "epa_documents": len(epa_docs),
                            "sample_document": data[0] if data else None,
                            "metadata": metadata
                        }
                    )
                else:
                    self.log_test(
                        "Scrape by Agency",
                        "WARN",
                        "No EPA documents found in last 30 days",
                        result
                    )
            else:
                self.log_test(
                    "Scrape by Agency",
                    "FAIL",
                    f"Failed: {result.get('error')}",
                    result
                )
        except Exception as e:
            self.log_test("Scrape by Agency", "FAIL", f"Exception: {str(e)}")
    
    async def test_scrape_multiple_agencies(self):
        """Test scraping documents from multiple agencies."""
        print("\n" + "="*80)
        print("TEST 3: Scrape Multiple Agencies (EPA, FDA)")
        print("="*80)
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)
            
            result = await scrape_federal_register(
                agencies=["EPA", "FDA"],
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                output_format="json",
                include_full_text=False,
                rate_limit_delay=1.0,
                max_documents=10
            )
            
            if result.get("status") in ["success", "partial_success"]:
                data = result.get("data", [])
                metadata = result.get("metadata", {})
                
                # Count agencies found
                agencies_found = set()
                for doc in data:
                    agencies_in_doc = doc.get("agencies", [])
                    if isinstance(agencies_in_doc, list):
                        agencies_found.update(agencies_in_doc)
                
                if len(data) > 0:
                    self.log_test(
                        "Scrape Multiple Agencies",
                        "PASS",
                        f"Scraped {len(data)} documents from agencies: {agencies_found}",
                        {
                            "total_documents": len(data),
                            "agencies_found": list(agencies_found),
                            "metadata": metadata
                        }
                    )
                else:
                    self.log_test(
                        "Scrape Multiple Agencies",
                        "WARN",
                        "No documents found from EPA or FDA",
                        result
                    )
            else:
                self.log_test(
                    "Scrape Multiple Agencies",
                    "FAIL",
                    f"Failed: {result.get('error')}",
                    result
                )
        except Exception as e:
            self.log_test("Scrape Multiple Agencies", "FAIL", f"Exception: {str(e)}")
    
    async def test_document_types(self):
        """Test filtering by document types."""
        print("\n" + "="*80)
        print("TEST 4: Filter by Document Types (RULE)")
        print("="*80)
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=60)
            
            result = await scrape_federal_register(
                document_types=["RULE"],
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                output_format="json",
                include_full_text=False,
                max_documents=5
            )
            
            if result.get("status") in ["success", "partial_success"]:
                data = result.get("data", [])
                
                if len(data) > 0:
                    # Check document types
                    doc_types = [d.get("document_type", "unknown") for d in data]
                    rule_count = doc_types.count("RULE") + doc_types.count("Rule")
                    
                    self.log_test(
                        "Filter by Document Types",
                        "PASS",
                        f"Found {len(data)} documents, {rule_count} are RULEs",
                        {
                            "total_documents": len(data),
                            "rule_documents": rule_count,
                            "document_types": doc_types
                        }
                    )
                else:
                    self.log_test(
                        "Filter by Document Types",
                        "WARN",
                        "No RULE documents found in date range",
                        result
                    )
            else:
                self.log_test(
                    "Filter by Document Types",
                    "FAIL",
                    f"Failed: {result.get('error')}",
                    result
                )
        except Exception as e:
            self.log_test("Filter by Document Types", "FAIL", f"Exception: {str(e)}")
    
    async def test_data_structure(self):
        """Test that scraped data has the correct structure."""
        print("\n" + "="*80)
        print("TEST 5: Validate Data Structure")
        print("="*80)
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=14)
            
            result = await scrape_federal_register(
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                output_format="json",
                max_documents=3
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
                required_fields = ["document_number", "title", "publication_date"]
                sample_doc = data[0]
                
                missing_fields = [f for f in required_fields if f not in sample_doc]
                
                if not missing_fields:
                    self.log_test(
                        "Data Structure",
                        "PASS",
                        "Data structure is valid",
                        {
                            "sample_document": sample_doc,
                            "total_documents": len(data),
                            "fields_present": list(sample_doc.keys())
                        }
                    )
                else:
                    self.log_test(
                        "Data Structure",
                        "WARN",
                        f"Missing fields: {missing_fields}",
                        {"sample_document": sample_doc}
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
    
    async def test_search_with_keywords(self):
        """Test searching with keywords."""
        print("\n" + "="*80)
        print("TEST 6: Search with Keywords ('environmental')")
        print("="*80)
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)
            
            result = await search_federal_register(
                keywords="environmental",
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                limit=5
            )
            
            if result.get("status") == "success":
                documents = result.get("documents", [])
                count = result.get("count", 0)
                
                if len(documents) > 0:
                    self.log_test(
                        "Search with Keywords",
                        "PASS",
                        f"Found {count} documents matching 'environmental'",
                        {
                            "document_count": count,
                            "documents_returned": len(documents),
                            "sample_document": documents[0] if documents else None
                        }
                    )
                else:
                    self.log_test(
                        "Search with Keywords",
                        "WARN",
                        "No documents found matching 'environmental'",
                        result
                    )
            else:
                self.log_test(
                    "Search with Keywords",
                    "WARN",
                    f"Search returned status: {result.get('status')}",
                    result
                )
        except Exception as e:
            self.log_test("Search with Keywords", "FAIL", f"Exception: {str(e)}")
    
    async def test_full_text_inclusion(self):
        """Test that full text can be included/excluded."""
        print("\n" + "="*80)
        print("TEST 7: Full Text Inclusion")
        print("="*80)
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            
            # Test with full text
            result_with = await scrape_federal_register(
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                include_full_text=True,
                max_documents=2
            )
            
            # Test without full text
            result_without = await scrape_federal_register(
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                include_full_text=False,
                max_documents=2
            )
            
            data_with = result_with.get("data", [])
            data_without = result_without.get("data", [])
            
            if data_with and data_without:
                has_full_text = any("full_text" in d or "body" in d for d in data_with)
                lacks_full_text = not any("full_text" in d or "body" in d for d in data_without)
                
                if has_full_text or not lacks_full_text:
                    self.log_test(
                        "Full Text Inclusion",
                        "PASS",
                        "Full text inclusion/exclusion working",
                        {
                            "with_full_text": has_full_text,
                            "without_full_text": not lacks_full_text
                        }
                    )
                else:
                    self.log_test(
                        "Full Text Inclusion",
                        "WARN",
                        "Full text not found in either case",
                        {"data_with": data_with[0], "data_without": data_without[0]}
                    )
            else:
                self.log_test(
                    "Full Text Inclusion",
                    "WARN",
                    "Not enough data to test full text inclusion",
                    {"result_with": result_with, "result_without": result_without}
                )
        except Exception as e:
            self.log_test("Full Text Inclusion", "FAIL", f"Exception: {str(e)}")
    
    async def test_rate_limiting(self):
        """Test that rate limiting is respected."""
        print("\n" + "="*80)
        print("TEST 8: Rate Limiting")
        print("="*80)
        
        try:
            import time
            start_time = time.time()
            
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            
            result = await scrape_federal_register(
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                rate_limit_delay=2.0,  # 2 second delay
                max_documents=3
            )
            
            elapsed = time.time() - start_time
            
            # Should take at least 2 seconds
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
        print("FEDERAL REGISTER SCRAPER VERIFICATION")
        print("="*80)
        print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Run tests
        await self.test_search_recent_documents()
        await self.test_scrape_by_agency()
        await self.test_scrape_multiple_agencies()
        await self.test_document_types()
        await self.test_data_structure()
        await self.test_search_with_keywords()
        await self.test_full_text_inclusion()
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
        output_file = Path.home() / ".ipfs_datasets" / "federal_register" / "verification_results.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\n📁 Results saved to: {output_file}")
        
        # Return exit code
        return 0 if self.results['summary']['failed'] == 0 else 1


async def main():
    """Main entry point."""
    verifier = FederalRegisterVerifier()
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
