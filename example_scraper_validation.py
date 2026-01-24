#!/usr/bin/env python3
"""
Example: Quick Scraper Validation Test

This example demonstrates how to use the scraper testing framework
to validate a simple scraper function.

NOTE: This example works when run from a properly installed package.
For testing in GitHub Actions or after `pip install -e .`, this will work fine.
Due to an existing bug in ipfs_datasets_py/__init__.py (logger undefined at line 563),
this example may not work when run directly from source without installation.

See tests/scraper_tests/ for working examples used by the GitHub Actions workflow.
"""
import anyio
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))


async def example_scraper_test():
    """
    Example showing how to test a scraper with the framework.
    
    This bypasses package imports to work around existing __init__.py bugs.
    """
    print("=" * 70)
    print("SCRAPER TESTING FRAMEWORK - QUICK EXAMPLE")
    print("=" * 70)
    print()
    
    # Import framework components directly
    import importlib.util
    
    spec = importlib.util.spec_from_file_location(
        "framework",
        str(Path(__file__).parent / "ipfs_datasets_py" / "scraper_testing_framework.py")
    )
    framework = importlib.util.module_from_spec(spec)
    sys.modules['scraper_testing_framework'] = framework  # Register in sys.modules
    spec.loader.exec_module(framework)
    
    print("✅ Framework loaded successfully!")
    print()
    
    # Create a test scraper function
    async def example_scraper(query: str = "test", max_results: int = 5):
        """
        Example scraper that returns clean data.
        
        This would be replaced with your actual scraper implementation.
        """
        # Simulate scraping delay
        await anyio.sleep(0.1)
        
        # Return sample data
        return {
            'status': 'success',
            'data': [
                {
                    'title': f'Result {i+1}',
                    'text': f'Clean text content for result {i+1}',
                    'url': f'https://example.com/result{i+1}',
                    'date': '2024-10-30'
                }
                for i in range(max_results)
            ]
        }
    
    # Create bad scraper that includes HTML
    async def bad_scraper(query: str = "test", max_results: int = 3):
        """Example of a scraper with data quality issues."""
        await anyio.sleep(0.1)
        
        return {
            'status': 'success',
            'data': [
                {
                    'title': '<h1>Title with HTML</h1>',
                    'text': 'Home | About | Contact | Content text here',
                    'url': 'https://example.com',
                }
                for i in range(max_results)
            ]
        }
    
    # Test the good scraper
    print("Testing GOOD scraper (clean data):")
    print("-" * 70)
    
    test_runner = framework.ScraperTestRunner()
    
    result = await test_runner.run_scraper_test(
        scraper_func=example_scraper,
        scraper_name="example_clean_scraper",
        domain=framework.ScraperDomain.CASELAW,
        test_args={'query': 'test', 'max_results': 5}
    )
    
    print(f"Status: {result.status}")
    print(f"Records scraped: {result.records_scraped}")
    print(f"Quality score: {result.data_quality_score:.1f}/100")
    print(f"Quality issues: {len(result.quality_issues)}")
    print(f"Execution time: {result.execution_time_seconds:.2f}s")
    print()
    
    # Test the bad scraper
    print("Testing BAD scraper (HTML and menu content):")
    print("-" * 70)
    
    result2 = await test_runner.run_scraper_test(
        scraper_func=bad_scraper,
        scraper_name="example_bad_scraper",
        domain=framework.ScraperDomain.CASELAW,
        test_args={'query': 'test', 'max_results': 3}
    )
    
    print(f"Status: {result2.status}")
    print(f"Records scraped: {result2.records_scraped}")
    print(f"Quality score: {result2.data_quality_score:.1f}/100")
    print(f"Quality issues: {len(result2.quality_issues)}")
    
    if result2.quality_issues:
        print("\nIssue Details:")
        for i, issue in enumerate(result2.quality_issues[:3], 1):
            print(f"  {i}. Type: {issue['type']}, Severity: {issue['severity']}")
            if 'field' in issue:
                print(f"     Field: {issue['field']}")
            if 'patterns' in issue:
                print(f"     Patterns found: {issue['patterns'][:2]}")
    
    print()
    
    # Save results
    print("Saving results...")
    results = [result, result2]
    output_path = test_runner.save_results(results, "example_test_results.json")
    print(f"✅ Results saved to: {output_path}")
    print()
    
    # Generate summary
    print("Summary Report:")
    print("=" * 70)
    summary = test_runner.generate_summary_report(results)
    print(summary)
    
    print()
    print("=" * 70)
    print("EXAMPLE COMPLETE")
    print("=" * 70)
    print()
    print("Next steps:")
    print("1. Review the test_results/example_test_results.json file")
    print("2. Check how quality issues are detected and scored")
    print("3. Apply this pattern to your own scrapers")
    print()


if __name__ == '__main__':
    anyio.run(example_scraper_test())
