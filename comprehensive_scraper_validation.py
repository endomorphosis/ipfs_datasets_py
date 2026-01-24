#!/usr/bin/env python3
"""
Comprehensive Scraper Validation with HuggingFace Dataset Integration.

This script validates that:
1. Scrapers actually run and produce data
2. Output is compatible with HuggingFace datasets
3. Schemas match expected structure
4. Data quality meets standards
"""
import anyio
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from ipfs_datasets_py.scraper_testing_framework import (
    ScraperTestRunner,
    ScraperDomain,
    ScraperTestResult
)


@dataclass
class HuggingFaceDatasetSchema:
    """Expected schema for HuggingFace dataset."""
    domain: str
    fields: Dict[str, str]  # field_name -> field_type
    required_fields: List[str]
    description: str


# Define expected schemas for each domain
EXPECTED_SCHEMAS = {
    ScraperDomain.CASELAW: HuggingFaceDatasetSchema(
        domain="caselaw",
        fields={
            "title": "string",
            "text": "string",
            "citation": "string",
            "date": "string",
            "url": "string",
            "metadata": "dict"
        },
        required_fields=["title", "text"],
        description="Legal documents, statutes, and case law"
    ),
    ScraperDomain.FINANCE: HuggingFaceDatasetSchema(
        domain="finance",
        fields={
            "title": "string",
            "text": "string",
            "ticker": "string",
            "date": "string",
            "price": "float",
            "volume": "float",
            "url": "string",
            "metadata": "dict"
        },
        required_fields=["title", "text"],
        description="Financial data including stock prices and news"
    ),
    ScraperDomain.MEDICINE: HuggingFaceDatasetSchema(
        domain="medicine",
        fields={
            "title": "string",
            "abstract": "string",
            "text": "string",
            "pmid": "string",
            "doi": "string",
            "date": "string",
            "authors": "list",
            "url": "string",
            "metadata": "dict"
        },
        required_fields=["title", "text"],
        description="Medical research papers and clinical trials"
    ),
    ScraperDomain.SOFTWARE: HuggingFaceDatasetSchema(
        domain="software",
        fields={
            "name": "string",
            "description": "string",
            "url": "string",
            "stars": "int",
            "language": "string",
            "topics": "list",
            "metadata": "dict"
        },
        required_fields=["name", "description"],
        description="Software repositories and documentation"
    )
}


@dataclass
class ValidationResult:
    """Result of comprehensive scraper validation."""
    scraper_name: str
    domain: str
    execution_success: bool
    data_produced: bool
    record_count: int
    schema_valid: bool
    schema_issues: List[str]
    hf_compatible: bool
    hf_issues: List[str]
    quality_score: float
    quality_issues: List[Dict[str, Any]]
    sample_records: List[Dict[str, Any]]
    execution_time: float
    timestamp: str
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    def is_valid(self) -> bool:
        """Check if validation passed all criteria."""
        return (
            self.execution_success and
            self.data_produced and
            self.record_count > 0 and
            self.schema_valid and
            self.hf_compatible and
            self.quality_score >= 50
        )


class ComprehensiveScraperValidator:
    """Validates scrapers comprehensively including HuggingFace compatibility."""
    
    def __init__(self, output_dir: Path = Path("validation_results")):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.test_runner = ScraperTestRunner(output_dir=output_dir)
    
    def validate_schema(
        self,
        data: List[Dict[str, Any]],
        expected_schema: HuggingFaceDatasetSchema
    ) -> tuple[bool, List[str]]:
        """
        Validate that scraped data matches expected schema.
        
        Returns:
            (is_valid, list_of_issues)
        """
        if not data:
            return False, ["No data to validate"]
        
        issues = []
        
        # Check first record for schema compliance
        sample = data[0]
        
        # Check required fields
        for field in expected_schema.required_fields:
            if field not in sample:
                issues.append(f"Missing required field: {field}")
        
        # Validate field types (basic check)
        for field_name, field_type in expected_schema.fields.items():
            if field_name in sample:
                value = sample[field_name]
                
                if field_type == "string" and not isinstance(value, str):
                    issues.append(f"Field '{field_name}' should be string, got {type(value).__name__}")
                elif field_type == "int" and not isinstance(value, int):
                    issues.append(f"Field '{field_name}' should be int, got {type(value).__name__}")
                elif field_type == "float" and not isinstance(value, (int, float)):
                    issues.append(f"Field '{field_name}' should be float, got {type(value).__name__}")
                elif field_type == "list" and not isinstance(value, list):
                    issues.append(f"Field '{field_name}' should be list, got {type(value).__name__}")
                elif field_type == "dict" and not isinstance(value, dict):
                    issues.append(f"Field '{field_name}' should be dict, got {type(value).__name__}")
        
        return len(issues) == 0, issues
    
    def validate_hf_compatibility(
        self,
        data: List[Dict[str, Any]]
    ) -> tuple[bool, List[str]]:
        """
        Validate that data is compatible with HuggingFace datasets.
        
        Returns:
            (is_compatible, list_of_issues)
        """
        if not data:
            return False, ["No data to validate"]
        
        issues = []
        
        try:
            # Try to import datasets library
            try:
                import datasets
                hf_available = True
            except ImportError:
                hf_available = False
                issues.append("HuggingFace datasets library not available for full validation")
            
            # Check all records have consistent schema
            if len(data) > 1:
                first_keys = set(data[0].keys())
                for i, record in enumerate(data[1:], 1):
                    if set(record.keys()) != first_keys:
                        issues.append(f"Record {i} has inconsistent keys with first record")
            
            # Check for None/null values in required fields
            for i, record in enumerate(data):
                for key, value in record.items():
                    if value is None:
                        issues.append(f"Record {i} has null value for field '{key}'")
            
            # Check for nested structures that might be problematic
            for i, record in enumerate(data):
                for key, value in record.items():
                    if isinstance(value, (set, tuple)):
                        issues.append(f"Record {i} field '{key}' uses {type(value).__name__}, should use list or dict")
            
            # If HF is available, try to create a dataset
            if hf_available and not issues:
                try:
                    from datasets import Dataset
                    # Try to create dataset (this validates structure)
                    _ = Dataset.from_list(data[:min(10, len(data))])
                except Exception as e:
                    issues.append(f"Failed to create HuggingFace Dataset: {str(e)}")
        
        except Exception as e:
            issues.append(f"Validation error: {str(e)}")
        
        return len(issues) == 0, issues
    
    async def validate_scraper(
        self,
        scraper_func,
        scraper_name: str,
        domain: ScraperDomain,
        test_args: Dict[str, Any]
    ) -> ValidationResult:
        """
        Comprehensively validate a scraper.
        
        Args:
            scraper_func: The scraper function to test
            scraper_name: Name of the scraper
            domain: MCP domain
            test_args: Arguments to pass to scraper
        
        Returns:
            ValidationResult with complete validation information
        """
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Run the scraper test
            result = await self.test_runner.run_scraper_test(
                scraper_func=scraper_func,
                scraper_name=scraper_name,
                domain=domain,
                test_args=test_args
            )
            
            execution_time = asyncio.get_event_loop().time() - start_time
            
            # Extract data from result
            data = result.sample_data if result.sample_data else []
            
            # Validate schema
            expected_schema = EXPECTED_SCHEMAS.get(domain)
            if expected_schema:
                schema_valid, schema_issues = self.validate_schema(data, expected_schema)
            else:
                schema_valid, schema_issues = False, [f"No schema defined for domain {domain}"]
            
            # Validate HuggingFace compatibility
            hf_compatible, hf_issues = self.validate_hf_compatibility(data)
            
            return ValidationResult(
                scraper_name=scraper_name,
                domain=domain.value,
                execution_success=(result.status == "success"),
                data_produced=len(data) > 0,
                record_count=result.records_scraped,
                schema_valid=schema_valid,
                schema_issues=schema_issues,
                hf_compatible=hf_compatible,
                hf_issues=hf_issues,
                quality_score=result.data_quality_score,
                quality_issues=result.quality_issues,
                sample_records=data[:3],  # First 3 records as samples
                execution_time=execution_time,
                timestamp=datetime.utcnow().isoformat()
            )
        
        except Exception as e:
            execution_time = asyncio.get_event_loop().time() - start_time
            return ValidationResult(
                scraper_name=scraper_name,
                domain=domain.value,
                execution_success=False,
                data_produced=False,
                record_count=0,
                schema_valid=False,
                schema_issues=[],
                hf_compatible=False,
                hf_issues=[],
                quality_score=0.0,
                quality_issues=[],
                sample_records=[],
                execution_time=execution_time,
                timestamp=datetime.utcnow().isoformat(),
                error=str(e)
            )
    
    def save_validation_report(
        self,
        results: List[ValidationResult],
        filename: str = "comprehensive_validation_report.json"
    ) -> Path:
        """Save validation results to JSON file."""
        output_path = self.output_dir / filename
        
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "total_scrapers": len(results),
            "passed": sum(1 for r in results if r.is_valid()),
            "failed": sum(1 for r in results if not r.is_valid()),
            "results": [r.to_dict() for r in results]
        }
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        return output_path
    
    def generate_summary(self, results: List[ValidationResult]) -> str:
        """Generate human-readable summary."""
        passed = [r for r in results if r.is_valid()]
        failed = [r for r in results if not r.is_valid()]
        
        summary = ["=" * 70]
        summary.append("COMPREHENSIVE SCRAPER VALIDATION SUMMARY")
        summary.append("=" * 70)
        summary.append("")
        summary.append(f"Total Scrapers Tested: {len(results)}")
        summary.append(f"✅ Passed: {len(passed)}")
        summary.append(f"❌ Failed: {len(failed)}")
        summary.append("")
        
        if failed:
            summary.append("FAILED SCRAPERS:")
            summary.append("-" * 70)
            for r in failed:
                summary.append(f"\n{r.scraper_name} ({r.domain}):")
                if not r.execution_success:
                    summary.append(f"  ❌ Execution failed: {r.error}")
                if not r.data_produced:
                    summary.append(f"  ❌ No data produced")
                if not r.schema_valid:
                    summary.append(f"  ❌ Schema invalid: {', '.join(r.schema_issues)}")
                if not r.hf_compatible:
                    summary.append(f"  ❌ HuggingFace incompatible: {', '.join(r.hf_issues)}")
                if r.quality_score < 50:
                    summary.append(f"  ❌ Low quality score: {r.quality_score:.1f}/100")
        
        if passed:
            summary.append("\nPASSED SCRAPERS:")
            summary.append("-" * 70)
            for r in passed:
                summary.append(f"✅ {r.scraper_name} ({r.domain})")
                summary.append(f"   Records: {r.record_count}, Quality: {r.quality_score:.1f}/100")
        
        summary.append("")
        summary.append("=" * 70)
        
        return "\n".join(summary)


async def main():
    """Run comprehensive validation."""
    print("=" * 70)
    print("COMPREHENSIVE SCRAPER VALIDATION")
    print("Testing execution, schema compliance, and HuggingFace compatibility")
    print("=" * 70)
    print()
    
    validator = ComprehensiveScraperValidator()
    results = []
    
    # Define scrapers to test
    scrapers_to_test = []
    
    # Caselaw scrapers
    try:
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import (
            scrape_us_code,
            scrape_federal_register,
        )
        scrapers_to_test.extend([
            (scrape_us_code, "us_code_scraper", ScraperDomain.CASELAW, {
                'titles': ["1"], 'max_sections': 5, 'output_format': 'json'
            }),
            (scrape_federal_register, "federal_register_scraper", ScraperDomain.CASELAW, {
                'agencies': ["EPA"], 'max_documents': 3, 'output_format': 'json'
            }),
        ])
    except ImportError as e:
        print(f"⚠️  Could not import caselaw scrapers: {e}")
    
    # Finance scrapers
    try:
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.stock_scrapers import fetch_stock_data
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.news_scrapers import fetch_financial_news
        
        scrapers_to_test.extend([
            (fetch_stock_data, "stock_data_scraper", ScraperDomain.FINANCE, {
                'ticker': 'AAPL', 'period': '1d'
            }),
            (fetch_financial_news, "financial_news_scraper", ScraperDomain.FINANCE, {
                'query': 'tech stocks', 'max_results': 5
            }),
        ])
    except ImportError as e:
        print(f"⚠️  Could not import finance scrapers: {e}")
    
    # Medicine scrapers
    try:
        from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.pubmed_scraper import scrape_pubmed
        scrapers_to_test.append(
            (scrape_pubmed, "pubmed_scraper", ScraperDomain.MEDICINE, {
                'query': 'cancer', 'max_results': 5
            })
        )
    except ImportError as e:
        print(f"⚠️  Could not import medicine scrapers: {e}")
    
    # Software scrapers
    try:
        from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.github_repository_scraper import scrape_github_repository
        scrapers_to_test.append(
            (scrape_github_repository, "github_scraper", ScraperDomain.SOFTWARE, {
                'owner': 'python', 'repo': 'cpython'
            })
        )
    except ImportError as e:
        print(f"⚠️  Could not import software scrapers: {e}")
    
    # Run validation for each scraper
    for scraper_func, name, domain, args in scrapers_to_test:
        print(f"Testing {name} ({domain.value})...")
        result = await validator.validate_scraper(scraper_func, name, domain, args)
        results.append(result)
        
        # Print immediate result
        if result.is_valid():
            print(f"  ✅ PASSED")
        else:
            print(f"  ❌ FAILED")
            if result.error:
                print(f"     Error: {result.error}")
        print()
    
    # Save report
    if results:
        report_path = validator.save_validation_report(results)
        print(f"📄 Full report saved to: {report_path}")
        print()
        
        # Print summary
        summary = validator.generate_summary(results)
        print(summary)
        
        # Save summary
        summary_path = validator.output_dir / "validation_summary.txt"
        with open(summary_path, 'w') as f:
            f.write(summary)
        print(f"\n📄 Summary saved to: {summary_path}")
        
        # Exit with appropriate code
        passed_count = sum(1 for r in results if r.is_valid())
        if passed_count == len(results):
            print("\n✅ ALL VALIDATIONS PASSED")
            return 0
        else:
            print(f"\n❌ {len(results) - passed_count} VALIDATIONS FAILED")
            return 1
    else:
        print("❌ No scrapers could be tested")
        return 1


if __name__ == "__main__":
    exit_code = anyio.run(main())
    sys.exit(exit_code)
