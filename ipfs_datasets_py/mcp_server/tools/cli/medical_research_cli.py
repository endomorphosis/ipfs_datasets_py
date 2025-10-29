#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CLI commands for medical research scrapers and biomolecule discovery.

This module provides command-line interface access to medical research tools,
ensuring the same code paths are used regardless of access method (CLI, MCP, or Python API).
"""

import argparse
import json
import sys
from typing import Optional, List


def scrape_pubmed_cli():
    """CLI command for PubMed medical research scraping."""
    parser = argparse.ArgumentParser(
        description="Scrape medical research from PubMed",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --query "COVID-19 treatment" --max-results 100
  %(prog)s --query "diabetes therapy" --email user@example.com --research-type clinical_trial
        """
    )
    parser.add_argument('--query', required=True, help='Search query for medical research')
    parser.add_argument('--max-results', type=int, default=100, help='Maximum number of results (default: 100)')
    parser.add_argument('--email', help='Email for NCBI E-utilities (recommended)')
    parser.add_argument('--research-type', choices=['clinical_trial', 'meta_analysis', 'review', 'research_article'],
                       help='Type of research to filter by')
    parser.add_argument('--output', '-o', help='Output file path (JSON format)')
    parser.add_argument('--format', choices=['json', 'table'], default='json', help='Output format')
    
    args = parser.parse_args()
    
    # Import the MCP tool function
    try:
        from ..medical_research_mcp_tools import scrape_pubmed_medical_research
    except ImportError:
        print("Error: Medical research tools not available", file=sys.stderr)
        sys.exit(1)
    
    # Call the tool function (same code path as MCP)
    result = scrape_pubmed_medical_research(
        query=args.query,
        max_results=args.max_results,
        email=args.email,
        research_type=args.research_type
    )
    
    # Output results
    if args.format == 'json':
        output = json.dumps(result, indent=2)
    else:
        # Table format
        if result.get('success') and result.get('articles'):
            output = format_articles_table(result['articles'])
        else:
            output = json.dumps(result, indent=2)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
        print(f"Results written to {args.output}")
    else:
        print(output)
    
    return 0 if result.get('success') else 1


def scrape_clinical_trials_cli():
    """CLI command for clinical trials scraping."""
    parser = argparse.ArgumentParser(
        description="Scrape clinical trial data from ClinicalTrials.gov",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --condition diabetes --intervention metformin
  %(prog)s --condition "heart disease" --phase "Phase 3" --max-results 50
        """
    )
    parser.add_argument('--query', help='General search query')
    parser.add_argument('--condition', help='Medical condition to search for')
    parser.add_argument('--intervention', help='Intervention/treatment to filter by')
    parser.add_argument('--phase', choices=['Phase 1', 'Phase 2', 'Phase 3', 'Phase 4'],
                       help='Trial phase')
    parser.add_argument('--max-results', type=int, default=50, help='Maximum number of results (default: 50)')
    parser.add_argument('--output', '-o', help='Output file path (JSON format)')
    parser.add_argument('--format', choices=['json', 'table'], default='json', help='Output format')
    
    args = parser.parse_args()
    
    if not args.query and not args.condition:
        parser.error("Either --query or --condition is required")
    
    # Import the MCP tool function
    try:
        from ..medical_research_mcp_tools import scrape_clinical_trials
    except ImportError:
        print("Error: Medical research tools not available", file=sys.stderr)
        sys.exit(1)
    
    # Call the tool function (same code path as MCP)
    result = scrape_clinical_trials(
        query=args.query or args.condition,
        condition=args.condition,
        intervention=args.intervention,
        max_results=args.max_results
    )
    
    # Output results
    if args.format == 'json':
        output = json.dumps(result, indent=2)
    else:
        if result.get('success') and result.get('trials'):
            output = format_trials_table(result['trials'])
        else:
            output = json.dumps(result, indent=2)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
        print(f"Results written to {args.output}")
    else:
        print(output)
    
    return 0 if result.get('success') else 1


def discover_protein_binders_cli():
    """CLI command for discovering protein binders."""
    parser = argparse.ArgumentParser(
        description="Discover protein binders using RAG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --target "SARS-CoV-2 spike protein" --min-confidence 0.7
  %(prog)s --target "PD-L1" --interaction binding --max-results 20
        """
    )
    parser.add_argument('--target', required=True, help='Target protein name')
    parser.add_argument('--interaction', choices=['binding', 'inhibition', 'activation'],
                       help='Type of interaction')
    parser.add_argument('--min-confidence', type=float, default=0.5,
                       help='Minimum confidence score (0-1, default: 0.5)')
    parser.add_argument('--max-results', type=int, default=50, help='Maximum number of results (default: 50)')
    parser.add_argument('--output', '-o', help='Output file path (JSON format)')
    parser.add_argument('--format', choices=['json', 'table'], default='json', help='Output format')
    
    args = parser.parse_args()
    
    # Import the MCP tool function
    try:
        from ..medical_research_mcp_tools import discover_protein_binders
    except ImportError:
        print("Error: Biomolecule discovery tools not available", file=sys.stderr)
        sys.exit(1)
    
    # Call the tool function (same code path as MCP)
    result = discover_protein_binders(
        target_protein=args.target,
        interaction_type=args.interaction,
        min_confidence=args.min_confidence,
        max_results=args.max_results
    )
    
    # Output results
    if args.format == 'json':
        output = json.dumps(result, indent=2)
    else:
        if result.get('success') and result.get('candidates'):
            output = format_candidates_table(result['candidates'])
        else:
            output = json.dumps(result, indent=2)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
        print(f"Results written to {args.output}")
    else:
        print(output)
    
    return 0 if result.get('success') else 1


def discover_enzyme_inhibitors_cli():
    """CLI command for discovering enzyme inhibitors."""
    parser = argparse.ArgumentParser(
        description="Discover enzyme inhibitors using RAG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --target ACE2 --enzyme-class protease
  %(prog)s --target TMPRSS2 --min-confidence 0.6 --max-results 30
        """
    )
    parser.add_argument('--target', required=True, help='Target enzyme name')
    parser.add_argument('--enzyme-class', help='Enzyme classification (e.g., kinase, protease)')
    parser.add_argument('--min-confidence', type=float, default=0.5,
                       help='Minimum confidence score (0-1, default: 0.5)')
    parser.add_argument('--max-results', type=int, default=50, help='Maximum number of results (default: 50)')
    parser.add_argument('--output', '-o', help='Output file path (JSON format)')
    parser.add_argument('--format', choices=['json', 'table'], default='json', help='Output format')
    
    args = parser.parse_args()
    
    # Import the MCP tool function
    try:
        from ..medical_research_mcp_tools import discover_enzyme_inhibitors
    except ImportError:
        print("Error: Biomolecule discovery tools not available", file=sys.stderr)
        sys.exit(1)
    
    # Call the tool function (same code path as MCP)
    result = discover_enzyme_inhibitors(
        target_enzyme=args.target,
        enzyme_class=args.enzyme_class,
        min_confidence=args.min_confidence,
        max_results=args.max_results
    )
    
    # Output results
    if args.format == 'json':
        output = json.dumps(result, indent=2)
    else:
        if result.get('success') and result.get('candidates'):
            output = format_candidates_table(result['candidates'])
        else:
            output = json.dumps(result, indent=2)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
        print(f"Results written to {args.output}")
    else:
        print(output)
    
    return 0 if result.get('success') else 1


def discover_biomolecules_rag_cli():
    """CLI command for high-level biomolecule discovery."""
    parser = argparse.ArgumentParser(
        description="Discover biomolecules using RAG (unified interface)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --target "PD-L1" --type binders --max-results 20
  %(prog)s --target "TMPRSS2" --type inhibitors --min-confidence 0.7
  %(prog)s --target "mTOR signaling" --type pathway --max-results 100
        """
    )
    parser.add_argument('--target', required=True, help='Target protein, enzyme, or pathway name')
    parser.add_argument('--type', required=True, choices=['binders', 'inhibitors', 'pathway'],
                       help='Type of discovery to perform')
    parser.add_argument('--min-confidence', type=float, default=0.5,
                       help='Minimum confidence score (0-1, default: 0.5)')
    parser.add_argument('--max-results', type=int, default=50, help='Maximum number of results (default: 50)')
    parser.add_argument('--output', '-o', help='Output file path (JSON format)')
    parser.add_argument('--format', choices=['json', 'table'], default='json', help='Output format')
    
    args = parser.parse_args()
    
    # Import the MCP tool function
    try:
        from ..medical_research_mcp_tools import discover_biomolecules_rag
    except ImportError:
        print("Error: Biomolecule discovery tools not available", file=sys.stderr)
        sys.exit(1)
    
    # Call the tool function (same code path as MCP)
    result = discover_biomolecules_rag(
        target=args.target,
        discovery_type=args.type,
        max_results=args.max_results,
        min_confidence=args.min_confidence
    )
    
    # Output results
    if args.format == 'json':
        output = json.dumps(result, indent=2)
    else:
        if result.get('success') and result.get('candidates'):
            output = format_candidates_table(result['candidates'])
        else:
            output = json.dumps(result, indent=2)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
        print(f"Results written to {args.output}")
    else:
        print(output)
    
    return 0 if result.get('success') else 1


# Table formatting functions

def format_articles_table(articles: List[dict]) -> str:
    """Format PubMed articles as a table."""
    if not articles:
        return "No articles found."
    
    lines = []
    lines.append("=" * 120)
    lines.append(f"{'PMID':<12} {'Title':<60} {'Journal':<30} {'Date':<15}")
    lines.append("=" * 120)
    
    for article in articles:
        pmid = article.get('pmid', 'N/A')[:11]
        title = article.get('title', 'N/A')[:59]
        journal = article.get('journal', 'N/A')[:29]
        date = article.get('publication_date', 'N/A')[:14]
        lines.append(f"{pmid:<12} {title:<60} {journal:<30} {date:<15}")
    
    lines.append("=" * 120)
    lines.append(f"Total: {len(articles)} articles")
    
    return "\n".join(lines)


def format_trials_table(trials: List[dict]) -> str:
    """Format clinical trials as a table."""
    if not trials:
        return "No trials found."
    
    lines = []
    lines.append("=" * 120)
    lines.append(f"{'NCT ID':<15} {'Title':<50} {'Phase':<12} {'Status':<20} {'Enrollment':<12}")
    lines.append("=" * 120)
    
    for trial in trials:
        nct_id = trial.get('nct_id', 'N/A')[:14]
        title = trial.get('title', 'N/A')[:49]
        phase = trial.get('phase', 'N/A')[:11]
        status = trial.get('status', 'N/A')[:19]
        enrollment = str(trial.get('enrollment', 'N/A'))[:11]
        lines.append(f"{nct_id:<15} {title:<50} {phase:<12} {status:<20} {enrollment:<12}")
    
    lines.append("=" * 120)
    lines.append(f"Total: {len(trials)} trials")
    
    return "\n".join(lines)


def format_candidates_table(candidates: List[dict]) -> str:
    """Format biomolecule candidates as a table."""
    if not candidates:
        return "No candidates found."
    
    lines = []
    lines.append("=" * 120)
    lines.append(f"{'Name':<30} {'Type':<15} {'Confidence':<12} {'Function':<50}")
    lines.append("=" * 120)
    
    for candidate in candidates:
        name = candidate.get('name', 'N/A')[:29]
        biomol_type = candidate.get('biomolecule_type', 'N/A')[:14]
        confidence = f"{candidate.get('confidence_score', 0):.2f}"[:11]
        function = (candidate.get('function') or 'N/A')[:49]
        lines.append(f"{name:<30} {biomol_type:<15} {confidence:<12} {function:<50}")
    
    lines.append("=" * 120)
    lines.append(f"Total: {len(candidates)} candidates")
    
    return "\n".join(lines)


# Entry point for subcommands
if __name__ == '__main__':
    # This module is meant to be called via the main CLI dispatcher
    print("This module should be called via the main CLI tool")
    sys.exit(1)
