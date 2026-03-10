"""Corpus Gap Analysis for State Administrative Rules.

This module analyzes coverage gaps in the legal corpus for each state,
comparing what has been scraped against what should be present based on:
- Common Crawl index analysis
- State agency domain inventories
- Link relationship graphs
- PDF availability detection
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class DomainCoverageSummary:
    """Coverage summary for a single domain."""
    
    domain: str
    state_code: str
    
    total_urls_known: int = 0
    urls_fetched: int = 0
    coverage_percent: float = 0.0
    
    rules_discovered: int = 0
    pdfs_identified: int = 0
    indexing_pages: int = 0  # Pages that look like indexes
    
    last_checked: Optional[str] = None
    status: str = "unknown"  # "good", "partial", "poor", "unreachable"


@dataclass
class CorpusGapReport:
    """Gap analysis report for a state."""
    
    state_code: str
    state_name: str
    
    total_domains_required: int = 0
    domains_discovered: int = 0
    domains_with_rules: int = 0
    domains_with_gaps: int = 0
    
    domain_coverage: Dict[str, DomainCoverageSummary] = field(default_factory=dict)
    
    estimated_missing_rules: int = 0
    estimated_missing_pdfs: int = 0
    
    weak_points: List[str] = field(default_factory=list)  # Domain URLs that need attention
    strong_points: List[str] = field(default_factory=list)  # Domains with good coverage
    
    recommendations: List[str] = field(default_factory=list)
    
    generated_at: Optional[str] = None


@dataclass
class StateAgencyCatalog:
    """Known state agencies and their typical rule publication domains."""
    
    state_code: str
    agency_name: str
    domain: str
    rule_index_url: Optional[str] = None
    pdf_archive_url: Optional[str] = None
    api_endpoint: Optional[str] = None


# Known state agency domains and their rule locations
STATE_AGENCY_CATALOG = {
    "UT": [
        StateAgencyCatalog(
            state_code="UT",
            agency_name="Utah State Legislature",
            domain="le.utah.gov",
            rule_index_url="https://le.utah.gov/xcode/Title%203C/Chapter%202/Part%201/3C-2-101.html",
        ),
        StateAgencyCatalog(
            state_code="UT",
            agency_name="Utah Admin Rules",
            domain="adminrules.utah.gov",
            rule_index_url="https://adminrules.utah.gov/",
            api_endpoint="https://adminrules.utah.gov/api/public/",
        ),
        StateAgencyCatalog(
            state_code="UT",
            agency_name="Utah Office of Administrative Rules",
            domain="oar.utah.gov",
            rule_index_url="https://oar.utah.gov/",
        ),
    ],
    "AZ": [
        StateAgencyCatalog(
            state_code="AZ",
            agency_name="Arizona Secretary of State",
            domain="azsos.gov",
            rule_index_url="https://apps.azsos.gov/public_services/",
        ),
        StateAgencyCatalog(
            state_code="AZ",
            agency_name="Arizona Legislature",
            domain="azleg.gov",
            rule_index_url="https://www.azleg.gov/",
        ),
    ],
    "IN": [
        StateAgencyCatalog(
            state_code="IN",
            agency_name="Indiana General Assembly",
            domain="iga.in.gov",
            rule_index_url="https://iga.in.gov/legislative/laws/",
        ),
        StateAgencyCatalog(
            state_code="IN",
            agency_name="Indiana Administrative Code",
            domain="admin.in.gov",
            rule_index_url="https://admin.in.gov/",
        ),
    ],
}


class CorpusGapAnalyzer:
    """Analyzes gaps in the legal document corpus."""
    
    def __init__(self):
        """Initialize analyzer."""
        self.catalog = STATE_AGENCY_CATALOG
    
    async def analyze_state_gaps(
        self,
        state_code: str,
        discovered_rules: List[Dict[str, Any]],
        discovered_domains: Optional[Set[str]] = None,
    ) -> CorpusGapReport:
        """Analyze coverage gaps for a state.
        
        Args:
            state_code: State code (e.g., "UT")
            discovered_rules: List of discovered rule documents
            discovered_domains: Set of domains that were visited
        
        Returns:
            CorpusGapReport with gap analysis and recommendations
        """
        report = CorpusGapReport(
            state_code=state_code,
            state_name=state_code,
        )
        
        # Get known agencies for this state
        agencies = self.catalog.get(state_code, [])
        report.total_domains_required = len(agencies)
        
        # Analyze discovered domains
        discovered_domains = discovered_domains or set()
        report.domains_discovered = len(discovered_domains)
        
        # Build domain coverage map
        rules_by_domain = defaultdict(list)
        for rule in discovered_rules:
            domain = rule.get("domain", "unknown")
            rules_by_domain[domain].append(rule)
        
        report.domains_with_rules = len(rules_by_domain)
        
        # Check each known agency domain
        for agency in agencies:
            coverage = DomainCoverageSummary(
                domain=agency.domain,
                state_code=state_code,
            )
            
            # Check if domain was visited
            was_visited = any(agency.domain in d for d in discovered_domains)
            coverage.urls_fetched = 1 if was_visited else 0
            coverage.total_urls_known = 1
            coverage.coverage_percent = 100.0 if was_visited else 0.0
            
            # Count rules from this domain
            rules_from_domain = rules_by_domain.get(agency.domain, [])
            coverage.rules_discovered = len(rules_from_domain)
            
            # Determine status
            if len(rules_from_domain) >= 5:
                coverage.status = "good"
                report.strong_points.append(agency.domain)
            elif len(rules_from_domain) > 0:
                coverage.status = "partial"
            else:
                coverage.status = "poor"
                if was_visited:
                    report.weak_points.append(agency.domain)
            
            report.domain_coverage[agency.domain] = coverage
        
        # Identify missing domains (in catalog but not discovered)
        report.domains_with_gaps = sum(
            1 for domain_cov in report.domain_coverage.values()
            if domain_cov.status == "poor"
        )
        
        # Estimate missing content
        report.estimated_missing_rules = self._estimate_missing_rules(
            discovered_count=len(discovered_rules),
            domains_covered=report.domains_with_rules,
            total_domains=report.total_domains_required,
        )
        
        # Generate recommendations
        report.recommendations = self._generate_recommendations(
            state_code=state_code,
            report=report,
            weak_domains=[c.domain for c in report.domain_coverage.values() if c.status == "poor"],
        )
        
        return report
    
    def _estimate_missing_rules(
        self, discovered_count: int, domains_covered: int, total_domains: int
    ) -> int:
        """Estimate how many rules are likely missing."""
        if domains_covered == 0:
            return total_domains * 20  # Conservative estimate
        
        avg_per_domain = discovered_count / domains_covered
        remaining_domains = max(0, total_domains - domains_covered)
        return int(remaining_domains * avg_per_domain)
    
    def _generate_recommendations(
        self,
        state_code: str,
        report: CorpusGapReport,
        weak_domains: List[str],
    ) -> List[str]:
        """Generate actionable recommendations for filling gaps."""
        recommendations = []
        
        if not weak_domains:
            recommendations.append(f"{state_code}: Coverage appears complete for known domains.")
            return recommendations
        
        for domain in weak_domains[:3]:  # Top 3 weak domains
            agency = next(
                (a for a in self.catalog.get(state_code, []) if a.domain == domain),
                None,
            )
            if agency:
                if agency.api_endpoint:
                    recommendations.append(
                        f"{state_code}: Use API endpoint for {domain}: {agency.api_endpoint}"
                    )
                elif agency.rule_index_url:
                    recommendations.append(
                        f"{state_code}: Fetch rule index from {domain}: {agency.rule_index_url}"
                    )
                else:
                    recommendations.append(f"{state_code}: Investigate rule publication at {domain}")
        
        if report.estimated_missing_rules > 0:
            recommendations.append(
                f"{state_code}: Estimated {report.estimated_missing_rules} rules still missing. "
                f"Run with increased max_candidates ({report.total_domains_required * 8}) "
                f"to enable deeper discovery."
            )
        
        return recommendations
    
    async def detect_pdf_availability(
        self,
        state_code: str,
        known_domains: Optional[List[str]] = None,
    ) -> Dict[str, List[str]]:
        """Detect PDF documents available for a state across domains.
        
        Returns:
            Dict mapping domain to list of PDF URLs found
        """
        pdfs_by_domain = defaultdict(list)
        
        agencies = self.catalog.get(state_code, [])
        domains_to_check = known_domains or [a.domain for a in agencies]
        
        for domain in domains_to_check:
            # Check /pdf, /documents, /rules, /regulations paths
            pdf_paths = [
                f"https://{domain}/pdf/",
                f"https://{domain}/documents/",
                f"https://{domain}/rules/",
                f"https://{domain}/regulations/",
            ]
            
            for path in pdf_paths:
                try:
                    # TODO: Actually probe for PDFs (requires HTTP capabilities)
                    pass
                except Exception as exc:
                    logger.debug(f"Error checking PDF path {path}: {exc}")
        
        return dict(pdfs_by_domain)
    
    def format_gap_report(self, report: CorpusGapReport) -> str:
        """Format gap report as human-readable text."""
        lines = [
            f"\n{'=' * 70}",
            f"CORPUS GAP ANALYSIS: {report.state_code}",
            f"{'=' * 70}",
            f"Domains Required: {report.total_domains_required}",
            f"Domains Discovered: {report.domains_discovered}",
            f"Domains With Rules: {report.domains_with_rules}",
            f"Domains With Gaps: {report.domains_with_gaps}",
            f"",
            f"Coverage Summary:",
            f"  Strong Points ({len(report.strong_points)}):",
        ]
        
        for domain in report.strong_points:
            lines.append(f"    ✓ {domain}")
        
        lines.extend([
            f"",
            f"  Weak Points ({len(report.weak_points)}):",
        ])
        
        for domain in report.weak_points:
            lines.append(f"    ✗ {domain}")
        
        lines.extend([
            f"",
            f"Estimated Missing Rules: {report.estimated_missing_rules}",
            f"",
            f"Recommendations:",
        ])
        
        for i, rec in enumerate(report.recommendations, 1):
            lines.append(f"  {i}. {rec}")
        
        lines.append(f"{'=' * 70}\n")
        
        return "\n".join(lines)


async def analyze_multi_state_gaps(
    results: Dict[str, Any],
    state_codes: List[str],
) -> Dict[str, CorpusGapReport]:
    """Analyze gaps across multiple states.
    
    Args:
        results: Dict mapping state code to StateDiscoveryResult
        state_codes: List of state codes to analyze
    
    Returns:
        Dict mapping state code to CorpusGapReport
    """
    analyzer = CorpusGapAnalyzer()
    gap_reports = {}
    
    for state_code in state_codes:
        discovery_result = results.get(state_code)
        if discovery_result:
            discovered_rules = getattr(discovery_result, "rules", [])
            discovered_domains = getattr(discovery_result, "domains_visited", set())
            
            report = await analyzer.analyze_state_gaps(
                state_code=state_code,
                discovered_rules=discovered_rules,
                discovered_domains=discovered_domains,
            )
            gap_reports[state_code] = report
    
    return gap_reports
