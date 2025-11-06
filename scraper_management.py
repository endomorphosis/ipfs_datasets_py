#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper Management CLI Tool.

This tool provides command-line management for MCP dashboard scrapers:
- List all scrapers by domain
- Run tests for specific domains or all
- Generate test reports
- Validate data quality
- Monitor scraper health

Usage:
    python scraper_management.py list --domain all
    python scraper_management.py test --domain caselaw
    python scraper_management.py test --domain all --output-dir ./reports
    python scraper_management.py validate --input test_results/caselaw_scrapers_test.json
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from ipfs_datasets_py.scraper_testing_framework import (
    ScraperDomain,
    ScraperTestRunner,
    ScraperTestResult,
)


class ScraperManager:
    """Manager for scraper operations and testing."""
    
    # Define all available scrapers by domain
    SCRAPERS = {
        ScraperDomain.CASELAW: [
            ('us_code_scraper', 'Scrapes US Code titles and sections'),
            ('federal_register_scraper', 'Scrapes Federal Register documents'),
            ('state_laws_scraper', 'Scrapes state statutes and laws'),
            ('municipal_laws_scraper', 'Scrapes municipal codes'),
            ('recap_archive_scraper', 'Scrapes RECAP court documents'),
        ],
        ScraperDomain.FINANCE: [
            ('stock_data_scraper', 'Scrapes stock market data'),
            ('financial_news_scraper', 'Scrapes financial news articles'),
        ],
        ScraperDomain.MEDICINE: [
            ('clinical_trials_scraper', 'Scrapes ClinicalTrials.gov data'),
            ('pubmed_scraper', 'Scrapes PubMed research articles'),
        ],
        ScraperDomain.SOFTWARE: [
            ('github_repository_scraper', 'Scrapes GitHub repository data'),
        ],
    }
    
    def __init__(self):
        """Initialize scraper manager."""
        self.test_runner = ScraperTestRunner()
    
    def list_scrapers(self, domain: Optional[str] = None) -> None:
        """
        List all available scrapers.
        
        Args:
            domain: Specific domain to list, or None for all
        """
        print("\n" + "=" * 70)
        print("AVAILABLE SCRAPERS BY MCP DASHBOARD DOMAIN")
        print("=" * 70 + "\n")
        
        if domain and domain != "all":
            try:
                domain_enum = ScraperDomain(domain)
                self._print_domain_scrapers(domain_enum)
            except ValueError:
                print(f"Error: Unknown domain '{domain}'")
                print(f"Valid domains: {', '.join(d.value for d in ScraperDomain)}")
                return
        else:
            for domain_enum in ScraperDomain:
                self._print_domain_scrapers(domain_enum)
                print()
    
    def _print_domain_scrapers(self, domain: ScraperDomain) -> None:
        """Print scrapers for a specific domain."""
        print(f"📊 {domain.value.upper()} Dashboard")
        print(f"   URL: http://localhost:8899/mcp/{domain.value}")
        print(f"   Scrapers: {len(self.SCRAPERS[domain])}")
        print()
        
        for name, description in self.SCRAPERS[domain]:
            print(f"   • {name}")
            print(f"     {description}")
        
        print()
    
    async def test_domain_scrapers(
        self,
        domain: str,
        output_dir: Optional[str] = None,
        quick: bool = True
    ) -> List[ScraperTestResult]:
        """
        Test all scrapers for a domain.
        
        Args:
            domain: Domain to test
            output_dir: Output directory for results
            quick: Run quick tests (fewer records)
            
        Returns:
            List of test results
        """
        try:
            domain_enum = ScraperDomain(domain)
        except ValueError:
            print(f"Error: Unknown domain '{domain}'")
            return []
        
        # Set up test runner
        if output_dir:
            self.test_runner.output_dir = Path(output_dir)
            self.test_runner.output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\n🧪 Testing {domain.upper()} scrapers...")
        print(f"Mode: {'Quick' if quick else 'Comprehensive'}")
        print(f"Output: {self.test_runner.output_dir}")
        print()
        
        # Import and test scrapers based on domain
        results = []
        
        if domain_enum == ScraperDomain.CASELAW:
            results = await self._test_caselaw_scrapers(quick)
        elif domain_enum == ScraperDomain.FINANCE:
            results = await self._test_finance_scrapers(quick)
        elif domain_enum == ScraperDomain.MEDICINE:
            results = await self._test_medicine_scrapers(quick)
        elif domain_enum == ScraperDomain.SOFTWARE:
            results = await self._test_software_scrapers(quick)
        
        # Save and report results
        if results:
            output_file = f"{domain}_scrapers_test.json"
            output_path = self.test_runner.save_results(results, output_file)
            print(f"\n✅ Results saved to: {output_path}")
            
            # Generate and print summary
            summary = self.test_runner.generate_summary_report(results)
            print("\n" + summary)
        else:
            print("\n⚠️ No scrapers were tested")
        
        return results
    
    async def _test_caselaw_scrapers(self, quick: bool) -> List[ScraperTestResult]:
        """Test caselaw domain scrapers."""
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import (
                scrape_us_code,
                scrape_federal_register,
                scrape_state_laws,
            )
        except ImportError as e:
            print(f"❌ Could not import caselaw scrapers: {e}")
            return []
        
        max_items = 3 if quick else 10
        
        scrapers = [
            (scrape_us_code, "us_code", {
                'titles': ["1"],
                'max_sections': max_items,
                'output_format': 'json'
            }),
            (scrape_federal_register, "federal_register", {
                'agencies': ["EPA"],
                'max_documents': max_items,
                'output_format': 'json'
            }),
            (scrape_state_laws, "state_laws", {
                'states': ["DE"],
                'max_statutes': max_items,
                'output_format': 'json'
            }),
        ]
        
        results = []
        for scraper_func, name, args in scrapers:
            print(f"  Testing {name}...")
            result = await self.test_runner.run_scraper_test(
                scraper_func=scraper_func,
                scraper_name=name,
                domain=ScraperDomain.CASELAW,
                test_args=args
            )
            results.append(result)
            
            status_icon = "✓" if result.status == "success" else "✗"
            print(f"    {status_icon} {result.status} - "
                  f"{result.records_scraped} records, "
                  f"quality={result.data_quality_score:.1f}")
        
        return results
    
    async def _test_finance_scrapers(self, quick: bool) -> List[ScraperTestResult]:
        """Test finance domain scrapers."""
        try:
            from ipfs_datasets_py.mcp_server.tools.finance_data_tools.stock_scrapers import (
                scrape_stock_data,
            )
            from ipfs_datasets_py.mcp_server.tools.finance_data_tools.news_scrapers import (
                scrape_financial_news,
            )
        except ImportError as e:
            print(f"❌ Could not import finance scrapers: {e}")
            return []
        
        max_items = 3 if quick else 10
        
        scrapers = [
            (scrape_stock_data, "stock_data", {
                'symbols': ["AAPL"],
                'days': max_items,
            }),
            (scrape_financial_news, "financial_news", {
                'topics': ["stocks"],
                'max_articles': max_items,
            }),
        ]
        
        results = []
        for scraper_func, name, args in scrapers:
            print(f"  Testing {name}...")
            result = await self.test_runner.run_scraper_test(
                scraper_func=scraper_func,
                scraper_name=name,
                domain=ScraperDomain.FINANCE,
                test_args=args
            )
            results.append(result)
            
            status_icon = "✓" if result.status == "success" else "✗"
            print(f"    {status_icon} {result.status}")
        
        return results
    
    async def _test_medicine_scrapers(self, quick: bool) -> List[ScraperTestResult]:
        """Test medicine domain scrapers."""
        try:
            from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.clinical_trials_scraper import (
                ClinicalTrialsScraper
            )
            from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.pubmed_scraper import (
                PubMedScraper
            )
        except ImportError as e:
            print(f"❌ Could not import medicine scrapers: {e}")
            return []
        
        max_items = 3 if quick else 10
        
        clinical_scraper = ClinicalTrialsScraper()
        pubmed_scraper = PubMedScraper()
        
        async def scrape_clinical(**kwargs):
            trials = clinical_scraper.search_trials(
                query=kwargs.get('query', 'test'),
                max_results=kwargs.get('max_results', 3)
            )
            return {'status': 'success', 'data': trials}
        
        async def scrape_pubmed(**kwargs):
            articles = pubmed_scraper.search_articles(
                query=kwargs.get('query', 'test'),
                max_results=kwargs.get('max_results', 3)
            )
            return {'status': 'success', 'data': articles}
        
        scrapers = [
            (scrape_clinical, "clinical_trials", {
                'query': 'diabetes',
                'max_results': max_items
            }),
            (scrape_pubmed, "pubmed", {
                'query': 'diabetes',
                'max_results': max_items
            }),
        ]
        
        results = []
        for scraper_func, name, args in scrapers:
            print(f"  Testing {name}...")
            result = await self.test_runner.run_scraper_test(
                scraper_func=scraper_func,
                scraper_name=name,
                domain=ScraperDomain.MEDICINE,
                test_args=args
            )
            results.append(result)
            
            status_icon = "✓" if result.status == "success" else "✗"
            print(f"    {status_icon} {result.status}")
        
        return results
    
    async def _test_software_scrapers(self, quick: bool) -> List[ScraperTestResult]:
        """Test software domain scrapers."""
        try:
            from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.github_repository_scraper import (
                GitHubRepositoryScraper
            )
        except ImportError as e:
            print(f"❌ Could not import software scrapers: {e}")
            return []
        
        max_items = 3 if quick else 10
        scraper = GitHubRepositoryScraper()
        
        async def scrape_github(**kwargs):
            repos = scraper.search_repositories(
                query=kwargs.get('query', 'test'),
                max_results=kwargs.get('max_results', 3)
            )
            return {'status': 'success', 'data': repos}
        
        scrapers = [
            (scrape_github, "github_repositories", {
                'query': 'python pandas',
                'max_results': max_items
            }),
        ]
        
        results = []
        for scraper_func, name, args in scrapers:
            print(f"  Testing {name}...")
            result = await self.test_runner.run_scraper_test(
                scraper_func=scraper_func,
                scraper_name=name,
                domain=ScraperDomain.SOFTWARE,
                test_args=args
            )
            results.append(result)
            
            status_icon = "✓" if result.status == "success" else "✗"
            print(f"    {status_icon} {result.status}")
        
        return results
    
    def validate_results(self, results_file: str) -> None:
        """
        Validate test results from a file.
        
        Args:
            results_file: Path to test results JSON file
        """
        results_path = Path(results_file)
        
        if not results_path.exists():
            print(f"❌ Results file not found: {results_file}")
            return
        
        try:
            with open(results_path) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON in results file: {e}")
            return
        
        print("\n" + "=" * 70)
        print("SCRAPER TEST RESULTS VALIDATION")
        print("=" * 70 + "\n")
        
        print(f"File: {results_file}")
        print(f"Timestamp: {data.get('timestamp', 'N/A')}")
        print()
        
        total = data.get('total_tests', 0)
        passed = data.get('passed', 0)
        failed = data.get('failed', 0)
        errors = data.get('errors', 0)
        
        print(f"Total Tests: {total}")
        print(f"✅ Passed: {passed} ({passed*100//total if total > 0 else 0}%)")
        print(f"❌ Failed: {failed} ({failed*100//total if total > 0 else 0}%)")
        print(f"⚠️ Errors: {errors} ({errors*100//total if total > 0 else 0}%)")
        print()
        
        # Analyze quality issues
        results = data.get('results', [])
        if results:
            print("Quality Analysis:")
            print()
            
            all_issues = []
            for result in results:
                all_issues.extend(result.get('quality_issues', []))
            
            if all_issues:
                issue_counts = {}
                for issue in all_issues:
                    issue_type = issue.get('type', 'unknown')
                    issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1
                
                print("Issues by Type:")
                for issue_type, count in sorted(issue_counts.items(), key=lambda x: x[1], reverse=True):
                    print(f"  • {issue_type}: {count}")
                print()
            else:
                print("✅ No quality issues detected!")
                print()
            
            # Average quality score
            avg_quality = sum(r.get('data_quality_score', 0) for r in results) / len(results)
            print(f"Average Quality Score: {avg_quality:.1f}/100")
            print()
        
        print("=" * 70)


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Scraper Management CLI for MCP Dashboards",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all scrapers
  python scraper_management.py list --domain all
  
  # List scrapers for specific domain
  python scraper_management.py list --domain caselaw
  
  # Test all caselaw scrapers (quick mode)
  python scraper_management.py test --domain caselaw
  
  # Test all scrapers (comprehensive mode)
  python scraper_management.py test --domain all --comprehensive
  
  # Validate existing test results
  python scraper_management.py validate --input test_results/caselaw_scrapers_test.json
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List available scrapers')
    list_parser.add_argument(
        '--domain',
        choices=['all', 'caselaw', 'finance', 'medicine', 'software'],
        default='all',
        help='Domain to list scrapers for'
    )
    
    # Test command
    test_parser = subparsers.add_parser('test', help='Test scrapers')
    test_parser.add_argument(
        '--domain',
        choices=['all', 'caselaw', 'finance', 'medicine', 'software'],
        default='all',
        help='Domain to test'
    )
    test_parser.add_argument(
        '--output-dir',
        help='Output directory for test results',
        default='./test_results'
    )
    test_parser.add_argument(
        '--comprehensive',
        action='store_true',
        help='Run comprehensive tests (more records, slower)'
    )
    
    # Validate command
    validate_parser = subparsers.add_parser('validate', help='Validate test results')
    validate_parser.add_argument(
        '--input',
        required=True,
        help='Path to test results JSON file'
    )
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    manager = ScraperManager()
    
    if args.command == 'list':
        manager.list_scrapers(args.domain)
    
    elif args.command == 'test':
        if args.domain == 'all':
            domains = ['caselaw', 'finance', 'medicine', 'software']
        else:
            domains = [args.domain]
        
        for domain in domains:
            asyncio.run(manager.test_domain_scrapers(
                domain=domain,
                output_dir=args.output_dir,
                quick=not args.comprehensive
            ))
    
    elif args.command == 'validate':
        manager.validate_results(args.input)


if __name__ == '__main__':
    main()
