#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper Testing Framework for IPFS Datasets MCP Dashboards.

This module provides a comprehensive framework for testing and validating
web scrapers across all MCP dashboard domains (caselaw, finance, medicine, software).

Key Features:
- Standardized test result reporting
- Data quality validation (DOM cleanup, coherence checks)
- HTML/XML stripping verification
- Content coherence validation
- Performance metrics tracking
- Support for all four MCP dashboard domains
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class ScraperDomain(str, Enum):
    """MCP Dashboard domains."""
    CASELAW = "caselaw"
    FINANCE = "finance"
    MEDICINE = "medicine"
    SOFTWARE = "software"


class DataQualityIssue(str, Enum):
    """Types of data quality issues that can be detected."""
    DOM_STYLING = "dom_styling"  # HTML/CSS styling present in data
    MENU_CONTENT = "menu_content"  # Navigation menu content in data
    INCOHERENT_DATA = "incoherent_data"  # Disconnected or nonsensical data
    EMPTY_FIELDS = "empty_fields"  # Required fields are empty
    MALFORMED_DATA = "malformed_data"  # Data structure is invalid
    DUPLICATE_DATA = "duplicate_data"  # Duplicate records detected


@dataclass
class ScraperTestResult:
    """
    Standardized test result for a scraper.
    
    Attributes:
        scraper_name: Name of the scraper being tested
        domain: MCP dashboard domain (caselaw, finance, medicine, software)
        status: Test status (success, failed, error)
        records_scraped: Number of records successfully scraped
        execution_time_seconds: Time taken to execute scraper
        data_quality_score: Score from 0-100 indicating data quality
        quality_issues: List of data quality issues found
        sample_data: Sample of scraped data for validation
        error_message: Error message if scraper failed
        metadata: Additional metadata about the test
        timestamp: When the test was executed
    """
    scraper_name: str
    domain: ScraperDomain
    status: str  # "success", "failed", "error"
    records_scraped: int = 0
    execution_time_seconds: float = 0.0
    data_quality_score: float = 0.0
    quality_issues: List[Dict[str, Any]] = field(default_factory=list)
    sample_data: List[Dict[str, Any]] = field(default_factory=list)
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        result['domain'] = self.domain.value if isinstance(self.domain, ScraperDomain) else self.domain
        return result
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


class ScraperValidator:
    """
    Base validator for scraper data quality checks.
    
    Validates that scraped data:
    - Does not contain DOM styling (HTML tags, CSS classes, etc.)
    - Does not include menu/navigation content
    - Is coherent and properly structured
    - Contains expected fields
    """
    
    # Patterns that indicate DOM/HTML content
    HTML_PATTERNS = [
        r'<[^>]+>',  # HTML tags
        r'class\s*=\s*["\'][^"\']+["\']',  # CSS class attributes
        r'id\s*=\s*["\'][^"\']+["\']',  # HTML id attributes
        r'style\s*=\s*["\'][^"\']+["\']',  # Inline styles
        r'&nbsp;|&lt;|&gt;|&amp;',  # HTML entities
        r'<script|<style|<div|<span|<p>|</p>',  # Common HTML tags
    ]
    
    # Patterns that indicate menu/navigation content
    MENU_PATTERNS = [
        r'(?i)(home|about|contact|login|logout|register|sign\s*in|sign\s*up)',
        r'(?i)(menu|navigation|nav|sidebar|header|footer)',
        r'(?i)(previous|next|page\s*\d+|back\s*to\s*top)',
    ]
    
    # Common menu phrases to detect
    MENU_PHRASES = {
        'home', 'about', 'contact', 'login', 'logout', 'register',
        'sign in', 'sign up', 'menu', 'navigation', 'sidebar',
        'header', 'footer', 'previous', 'next', 'back to top'
    }
    
    def __init__(self, domain: ScraperDomain):
        """
        Initialize scraper validator.
        
        Args:
            domain: The MCP dashboard domain this validator is for
        """
        self.domain = domain
        self.html_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.HTML_PATTERNS]
        self.menu_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.MENU_PATTERNS]
    
    def validate_no_html_content(self, text: str) -> Tuple[bool, List[str]]:
        """
        Check if text contains HTML/DOM content.
        
        Args:
            text: Text to validate
            
        Returns:
            Tuple of (is_valid, list of found HTML patterns)
        """
        if not text:
            return True, []
        
        found_patterns = []
        for pattern in self.html_regex:
            matches = pattern.findall(text)
            if matches:
                found_patterns.extend(matches[:3])  # Limit to first 3 matches per pattern
        
        return len(found_patterns) == 0, found_patterns
    
    def validate_no_menu_content(self, text: str) -> Tuple[bool, List[str]]:
        """
        Check if text contains menu/navigation content.
        
        Args:
            text: Text to validate
            
        Returns:
            Tuple of (is_valid, list of found menu patterns)
        """
        if not text:
            return True, []
        
        text_lower = text.lower()
        found_patterns = []
        
        # Check for menu phrases
        for phrase in self.MENU_PHRASES:
            if phrase in text_lower:
                found_patterns.append(phrase)
        
        # Check regex patterns
        for pattern in self.menu_regex:
            matches = pattern.findall(text)
            if matches:
                found_patterns.extend(matches[:2])  # Limit matches
        
        return len(found_patterns) == 0, found_patterns
    
    def validate_data_coherence(self, data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate that data is coherent and properly structured.
        
        Args:
            data: Dictionary of scraped data
            
        Returns:
            Tuple of (is_coherent, list of issues found)
        """
        issues = []
        
        # Check for empty or whitespace-only values
        for key, value in data.items():
            if isinstance(value, str):
                if not value or value.strip() == '':
                    issues.append(f"Empty field: {key}")
                elif len(value.strip()) < 3:
                    issues.append(f"Suspiciously short value for {key}: '{value}'")
        
        # Check for minimum expected fields (domain-specific)
        expected_min_fields = self._get_expected_min_fields()
        if len(data.keys()) < expected_min_fields:
            issues.append(f"Too few fields: {len(data.keys())} (expected at least {expected_min_fields})")
        
        return len(issues) == 0, issues
    
    def _get_expected_min_fields(self) -> int:
        """Get minimum expected number of fields for this domain."""
        domain_minimums = {
            ScraperDomain.CASELAW: 3,  # e.g., title, text, citation
            ScraperDomain.FINANCE: 4,  # e.g., symbol, price, volume, date
            ScraperDomain.MEDICINE: 3,  # e.g., title, abstract, authors
            ScraperDomain.SOFTWARE: 3,  # e.g., name, description, url
        }
        return domain_minimums.get(self.domain, 2)
    
    def validate_record(self, record: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Validate a single scraped record.
        
        Args:
            record: Dictionary containing scraped data
            
        Returns:
            List of quality issues found
        """
        issues = []
        
        # Validate each field for HTML content
        for key, value in record.items():
            if isinstance(value, str):
                # Check for HTML
                is_valid, html_patterns = self.validate_no_html_content(value)
                if not is_valid:
                    issues.append({
                        'type': DataQualityIssue.DOM_STYLING.value,
                        'field': key,
                        'patterns': html_patterns[:3],
                        'severity': 'high'
                    })
                
                # Check for menu content
                is_valid, menu_patterns = self.validate_no_menu_content(value)
                if not is_valid:
                    issues.append({
                        'type': DataQualityIssue.MENU_CONTENT.value,
                        'field': key,
                        'patterns': menu_patterns[:3],
                        'severity': 'medium'
                    })
        
        # Validate data coherence
        is_coherent, coherence_issues = self.validate_data_coherence(record)
        if not is_coherent:
            issues.append({
                'type': DataQualityIssue.INCOHERENT_DATA.value,
                'details': coherence_issues,
                'severity': 'high'
            })
        
        return issues
    
    def validate_dataset(self, records: List[Dict[str, Any]]) -> ScraperTestResult:
        """
        Validate an entire dataset of scraped records.
        
        Args:
            records: List of scraped data records
            
        Returns:
            ScraperTestResult with validation details
        """
        all_issues = []
        
        # Validate each record
        for i, record in enumerate(records[:10]):  # Sample first 10 records
            record_issues = self.validate_record(record)
            for issue in record_issues:
                issue['record_index'] = i
                all_issues.append(issue)
        
        # Check for duplicates
        seen_records = set()
        duplicates = []
        for i, record in enumerate(records):
            # Create a simple hash of the record (excluding varying fields like timestamps)
            record_str = json.dumps(record, sort_keys=True)
            if record_str in seen_records:
                duplicates.append(i)
            seen_records.add(record_str)
        
        if duplicates:
            all_issues.append({
                'type': DataQualityIssue.DUPLICATE_DATA.value,
                'count': len(duplicates),
                'indices': duplicates[:5],  # Sample first 5
                'severity': 'medium'
            })
        
        # Calculate quality score (0-100)
        quality_score = self._calculate_quality_score(len(records), all_issues)
        
        return ScraperTestResult(
            scraper_name="unknown",  # Will be set by caller
            domain=self.domain,
            status="success" if quality_score >= 70 else "failed",
            records_scraped=len(records),
            data_quality_score=quality_score,
            quality_issues=all_issues,
            sample_data=records[:3]  # Include first 3 records as samples
        )
    
    def _calculate_quality_score(self, total_records: int, issues: List[Dict[str, Any]]) -> float:
        """
        Calculate data quality score from 0-100.
        
        Args:
            total_records: Total number of records
            issues: List of quality issues
            
        Returns:
            Quality score (0-100)
        """
        if total_records == 0:
            return 0.0
        
        # Base score
        score = 100.0
        
        # Deduct points for each issue based on severity
        severity_deductions = {
            'high': 10.0,
            'medium': 5.0,
            'low': 2.0
        }
        
        for issue in issues:
            severity = issue.get('severity', 'medium')
            deduction = severity_deductions.get(severity, 5.0)
            score -= deduction
        
        # Don't go below 0
        return max(0.0, score)


class ScraperTestRunner:
    """
    Test runner for executing scraper tests and collecting results.
    """
    
    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialize test runner.
        
        Args:
            output_dir: Directory to save test results (default: ./test_results)
        """
        self.output_dir = output_dir or Path("./test_results")
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    async def run_scraper_test(
        self,
        scraper_func,
        scraper_name: str,
        domain: ScraperDomain,
        test_args: Optional[Dict[str, Any]] = None
    ) -> ScraperTestResult:
        """
        Run a single scraper test.
        
        Args:
            scraper_func: Async function to run the scraper
            scraper_name: Name of the scraper
            domain: MCP dashboard domain
            test_args: Arguments to pass to scraper function
            
        Returns:
            ScraperTestResult with test details
        """
        validator = ScraperValidator(domain)
        test_args = test_args or {}
        
        start_time = time.time()
        
        try:
            # Run the scraper
            result = await scraper_func(**test_args)
            execution_time = time.time() - start_time
            
            # Extract data from result
            if isinstance(result, dict):
                if result.get('status') == 'error':
                    return ScraperTestResult(
                        scraper_name=scraper_name,
                        domain=domain,
                        status="error",
                        error_message=result.get('error', 'Unknown error'),
                        execution_time_seconds=execution_time
                    )
                
                # Get records from result
                records = result.get('data', [])
                if not isinstance(records, list):
                    records = [records] if records else []
            else:
                records = result if isinstance(result, list) else [result]
            
            # Validate the data
            validation_result = validator.validate_dataset(records)
            validation_result.scraper_name = scraper_name
            validation_result.execution_time_seconds = execution_time
            validation_result.metadata = {
                'test_args': test_args,
                'result_type': type(result).__name__
            }
            
            return validation_result
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Error testing {scraper_name}: {e}", exc_info=True)
            return ScraperTestResult(
                scraper_name=scraper_name,
                domain=domain,
                status="error",
                error_message=str(e),
                execution_time_seconds=execution_time
            )
    
    def save_results(self, results: List[ScraperTestResult], filename: str = "scraper_test_results.json"):
        """
        Save test results to file.
        
        Args:
            results: List of test results
            filename: Output filename
        """
        output_path = self.output_dir / filename
        
        results_dict = {
            'timestamp': datetime.utcnow().isoformat(),
            'total_tests': len(results),
            'passed': sum(1 for r in results if r.status == 'success'),
            'failed': sum(1 for r in results if r.status == 'failed'),
            'errors': sum(1 for r in results if r.status == 'error'),
            'results': [r.to_dict() for r in results]
        }
        
        with open(output_path, 'w') as f:
            json.dump(results_dict, f, indent=2)
        
        logger.info(f"Test results saved to {output_path}")
        return output_path
    
    def generate_summary_report(self, results: List[ScraperTestResult]) -> str:
        """
        Generate a human-readable summary report.
        
        Args:
            results: List of test results
            
        Returns:
            Summary report as string
        """
        total = len(results)
        passed = sum(1 for r in results if r.status == 'success')
        failed = sum(1 for r in results if r.status == 'failed')
        errors = sum(1 for r in results if r.status == 'error')
        
        avg_quality_score = sum(r.data_quality_score for r in results) / total if total > 0 else 0
        total_records = sum(r.records_scraped for r in results)
        
        report = [
            "=" * 70,
            "SCRAPER TEST SUMMARY REPORT",
            "=" * 70,
            f"Timestamp: {datetime.utcnow().isoformat()}",
            f"",
            f"Overall Results:",
            f"  Total Tests: {total}",
            f"  Passed: {passed} ({passed*100//total if total > 0 else 0}%)",
            f"  Failed: {failed} ({failed*100//total if total > 0 else 0}%)",
            f"  Errors: {errors} ({errors*100//total if total > 0 else 0}%)",
            f"",
            f"Data Quality:",
            f"  Average Quality Score: {avg_quality_score:.1f}/100",
            f"  Total Records Scraped: {total_records}",
            f"",
            f"Results by Domain:",
        ]
        
        # Group by domain
        by_domain = {}
        for result in results:
            domain = result.domain.value if isinstance(result.domain, ScraperDomain) else result.domain
            if domain not in by_domain:
                by_domain[domain] = []
            by_domain[domain].append(result)
        
        for domain, domain_results in sorted(by_domain.items()):
            domain_passed = sum(1 for r in domain_results if r.status == 'success')
            domain_total = len(domain_results)
            domain_quality = sum(r.data_quality_score for r in domain_results) / domain_total if domain_total > 0 else 0
            
            report.append(f"  {domain.upper()}:")
            report.append(f"    Tests: {domain_total}, Passed: {domain_passed}, Quality: {domain_quality:.1f}/100")
            
            for result in domain_results:
                status_icon = "✓" if result.status == 'success' else "✗"
                report.append(f"      {status_icon} {result.scraper_name}: "
                            f"{result.records_scraped} records, "
                            f"quality={result.data_quality_score:.1f}, "
                            f"time={result.execution_time_seconds:.2f}s")
                
                if result.quality_issues:
                    issue_summary = {}
                    for issue in result.quality_issues:
                        issue_type = issue.get('type', 'unknown')
                        issue_summary[issue_type] = issue_summary.get(issue_type, 0) + 1
                    
                    issue_str = ", ".join(f"{k}={v}" for k, v in issue_summary.items())
                    report.append(f"        Issues: {issue_str}")
        
        report.append("=" * 70)
        
        return "\n".join(report)
