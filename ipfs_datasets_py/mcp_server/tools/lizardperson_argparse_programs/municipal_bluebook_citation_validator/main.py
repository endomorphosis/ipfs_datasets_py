#!/usr/bin/env python3
"""
Bluebook Citation Validator - Main Implementation
Based on the Second SAD architecture
"""
import argparse
import functools
import logging
import random
import sys
from pathlib import Path
from queue import Queue
import re
from threading import RLock
from typing import Any, Dict, Generator, List, Optional, Tuple, TypeVar, Union


from types_ import DatabaseConnection


logger = logging.getLogger(__name__)


from _setup_databases_and_files import make_setup_database_and_files
from stratified_sampler import make_stratified_sampler
from citation_validator import make_citation_validator
from results_analyzer import make_results_analyzer
import math


def main() -> int:
    """
    Main function implementing the 4-step process from Second SAD:
    1. Setup - connect to databases and load files
    2. Smart Sampling - select 385 places to check  
    3. Validation Loop - run all 5 checkers on each citation
    4. Analysis and Reporting - count errors and generate reports
    """
    try:
        # Step 1: Setup
        print("Step 1: Setting up databases and loading files...")
        setup = make_setup_database_and_files()
        reference_db, error_db = setup.get_databases() # -> DatabaseConnection, DatabaseConnection
        citations, html =  setup.get_files() # -> List[Path], List[Path]

        print(f"Found {len(citations)} citation files and {len(html)} document files")

        # Step 2: Smart Sampling
        stratified_sampler = make_stratified_sampler()
        gnis_counts_by_state, gnis_for_sampled_places = stratified_sampler.get_stratified_sample(citations, reference_db)

        # Step 3: Validation Loop
        citation_validator = make_citation_validator()
        citation_validator.validate_citations_against_html_and_references(
                            citations, html, gnis_for_sampled_places, 
                            reference_db, error_db
                        )

        # Step 4: Analysis
        results_analyzer = make_results_analyzer()
        error_summary, accuracy_stats, extrapolated_results = results_analyzer.analyze()


        # Step 5: Generate reports
        report_path: Path = generate_validation_report(
            output_dir, error_summary, accuracy_stats, extrapolated_results
        )
        
        print(f"Validation complete! Report saved to: {report_path}")
        print(f"Sample accuracy: {accuracy_stats['accuracy_percent']:.2f}%")
        print(f"Estimated full dataset accuracy: {extrapolated_results['estimated_accuracy']:.2f}%")
        
        return 0
        
    except Exception as e:
        logger.exception(f"{type(e).__name__} occurred during validation: {e}")
        print(f"Error during validation: {e}", file=sys.stderr)
        return 1
    finally:
        # Cleanup connections
        cleanup_database_connections(error_db)














def run_section_checker(citation: Dict, documents: List[Dict]) -> Dict:  # -> ValidationResult
    """Check: Does section 14-75 actually exist in this document?"""
    try:
        cited_section = citation.get('section')
        document_url = citation.get('document_url')
        
        if not cited_section or not document_url:
            return {
                'valid': False,
                'error_type': 'section_error',
                'message': 'Missing section or document_url information in citation'
            }
        
        # Find the matching document
        matching_doc = None
        for doc in documents:
            if doc.get('url') == document_url or doc.get('source_url') == document_url:
                matching_doc = doc
                break
        
        if not matching_doc:
            return {
                'valid': False,
                'error_type': 'section_error',
                'message': f'Document not found for URL: {document_url}'
            }
        
        # Get the HTML content
        html_content = matching_doc.get('html_content', '')
        if not html_content:
            return {
                'valid': False,
                'error_type': 'section_error',
                'message': 'No HTML content found in document'
            }
        
        # Search for the section in the HTML content
        # Look for various patterns: "section 14-75", "§ 14-75", "14-75", etc.
        section_patterns = [
            f"section {cited_section}",
            f"Section {cited_section}",
            f"SECTION {cited_section}",
            f"§ {cited_section}",
            f"§{cited_section}",
            cited_section
        ]
        
        found_section = False
        for pattern in section_patterns:
            if pattern.lower() in html_content.lower():
                found_section = True
                break
        
        if not found_section:
            return {
                'valid': False,
                'error_type': 'section_error',
                'message': f'Section {cited_section} not found in document'
            }
        
        return {
            'valid': True,
            'error_type': None,
            'message': 'Section check passed'
        }
        
    except Exception as e:
        logger.error(f"Error in section check: {e}")
        return {
            'valid': False,
            'error_type': 'section_error',
            'message': f'Section check failed with error: {str(e)}'
        }

def run_date_checker(citation: Dict, documents: List[Dict]) -> Dict:  # -> ValidationResult
    """Check: Is the year reasonable (1776-2025)?"""
    try:
        cited_date = citation.get('date') or citation.get('year')
        
        if not cited_date:
            return {
                'valid': False,
                'error_type': 'date_error',
                'message': 'Missing date or year information in citation'
            }
        
        # Extract year from various date formats
        year = None
        if isinstance(cited_date, int):
            year = cited_date
        elif isinstance(cited_date, str):
            # Try to extract 4-digit year from string
            year_match = re.search(r'\b(1[7-9]\d{2}|20[0-2][0-9])\b', cited_date)
            if year_match:
                year = int(year_match.group(1))
        
        if year is None:
            return {
                'valid': False,
                'error_type': 'date_error',
                'message': f'Could not extract valid year from date: {cited_date}'
            }
        
        # Check if year is in reasonable range (1776-2025)
        if year < 1776 or year > 2025:
            return {
                'valid': False,
                'error_type': 'date_error',
                'message': f'Year {year} is outside reasonable range (1776-2025)'
            }
        
        return {
            'valid': True,
            'error_type': None,
            'message': 'Date check passed'
        }
        
    except Exception as e:
        logger.error(f"Error in date check: {e}")
        return {
            'valid': False,
            'error_type': 'date_error',
            'message': f'Date check failed with error: {str(e)}'
        }

def run_format_checker(citation: Dict) -> Dict:  # -> ValidationResult
    """Check: Does this follow correct Bluebook formatting?"""
    try:
        # Get citation components
        title = citation.get('title', '')
        section = citation.get('section', '')
        date = citation.get('date', '')
        url = citation.get('url', '')
        
        if not any([title, section, date, url]):
            return {
                'valid': False,
                'error_type': 'format_error',
                'message': 'Missing required citation components'
            }
        
        errors = []
        
        # Check title formatting (should not be empty and properly capitalized)
        if not title or title.strip() == '':
            errors.append('Title is missing or empty')
        elif title != title.strip():
            errors.append('Title has leading/trailing whitespace')
        
        # Check section formatting (should match pattern like "14-75" or "§ 14-75")
        if section:
            section_pattern = r'^(§\s*)?[\d]+[-\.][\d]+(\([a-z]\))?$'
            if not re.match(section_pattern, section.strip()):
                errors.append(f'Section "{section}" does not match expected format')
        
        # Check URL formatting (should be valid URL)
        if url:
            url_pattern = r'^https?://[^\s<>"{}|\\^`\[\]]+$'
            if not re.match(url_pattern, url.strip()):
                errors.append(f'URL "{url}" is not properly formatted')
        
        # Check date formatting (should be valid year or date)
        if date:
            date_str = str(date).strip()
            # Check for various date formats
            date_patterns = [
                r'^\d{4}$',  # Year only: 2023
                r'^\d{1,2}/\d{1,2}/\d{4}$',  # MM/DD/YYYY
                r'^\d{4}-\d{2}-\d{2}$',  # YYYY-MM-DD
                r'^[A-Za-z]+ \d{1,2}, \d{4}$'  # Month DD, YYYY
            ]
            if not any(re.match(pattern, date_str) for pattern in date_patterns):
                errors.append(f'Date "{date}" is not in a recognized format')
        
        if errors:
            return {
                'valid': False,
                'error_type': 'format_error',
                'message': '; '.join(errors)
            }
        
        return {
            'valid': True,
            'error_type': None,
            'message': 'Format check passed'
        }
        
    except Exception as e:
        logger.error(f"Error in format check: {e}")
        return {
            'valid': False,
            'error_type': 'format_error',
            'message': f'Format check failed with error: {str(e)}'
        }


# Step 3: Error Storage Function
def save_validation_errors(citation: Dict, validation_results: List[Dict], error_db) -> int:
    """Save any validation errors found to the error database."""
    error_count = 0
    
    for result in validation_results:
        gnis = result.get('gnis')
        citation_data = result.get('citation', {})
        citation_cid = citation_data.get('cid') or citation_data.get('id')
        
        # Check each validation type for errors
        geography_check = result.get('geography', {})
        type_check = result.get('type', {})
        section_check = result.get('section', {})
        date_check = result.get('date', {})
        format_check = result.get('format', {})
        
        # Determine if there are any errors
        geography_error = not geography_check.get('valid', True)
        type_error = not type_check.get('valid', True)
        section_error = not section_check.get('valid', True)
        date_error = not date_check.get('valid', True)
        format_error = not format_check.get('valid', True)
        
        # Only save if there are errors
        if any([geography_error, type_error, section_error, date_error, format_error]):
            # Collect error messages
            error_messages = []
            if geography_error:
                error_messages.append(f"Geography: {geography_check.get('message', 'Unknown error')}")
            if type_error:
                error_messages.append(f"Type: {type_check.get('message', 'Unknown error')}")
            if section_error:
                error_messages.append(f"Section: {section_check.get('message', 'Unknown error')}")
            if date_error:
                error_messages.append(f"Date: {date_check.get('message', 'Unknown error')}")
            if format_error:
                error_messages.append(f"Format: {format_check.get('message', 'Unknown error')}")
            
            error_message = "; ".join(error_messages)
            
            # Determine severity based on error types
            critical_errors = geography_error or type_error
            severity = "critical" if critical_errors else "minor"
            
            try:
                # Insert error record into database
                error_db.sql("""
                    INSERT INTO errors (
                        gnis, citation_cid, geography_error, section_error, 
                        date_error, format_error, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, [
                    gnis, citation_cid, geography_error, section_error,
                    date_error, format_error, error_message
                ])
                error_count += 1
                
            except Exception as e:
                logger.error(f"Failed to save error to database: {e}")
    
    return error_count








def calculate_accuracy_statistics(total_citations: int, total_errors: int, predicted_positives: int, predicted_negatives: int) -> Dict[str, float]:
    """
    Calculate accuracy percentages for the sample.
    
    Args:
        total_citations (int): Total number of citations checked.
        total_errors (int): Total number of errors found.
        predicted_positives (int): Total number of citations that were predicted as valid.
        predicted_negatives (int): Total number of citations that were predicted as invalid.

    Returns:
        A confusion matrix statistics dictionary with all metrics.
    """

    if total_citations == 0:
        return {
            'total_citations': 0,
            'total_errors': 0,
            'accuracy_percent': 0.0,
            'error_rate_percent': 0.0,
            'valid_citations': 0
        }
    
    # Basic counts
    valid_citations = total_citations - total_errors
    total_population = total_citations
    
    # Confusion matrix values
    true_positives = valid_citations  # Correctly identified as valid
    true_negatives = total_errors     # Correctly identified as having errors
    false_positives = max(0, predicted_positives - true_positives)  # Predicted valid but actually invalid
    false_negatives = max(0, predicted_negatives - true_negatives)  # Predicted invalid but actually valid
    
    # Core metrics
    accuracy = (true_positives + true_negatives) / total_population if total_population > 0 else 0.0
    error_rate = 1 - accuracy
    
    # Positive prediction metrics
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0.0
    sensitivity = recall  # Same as recall
    true_positive_rate = recall  # Same as recall
    
    # Negative prediction metrics
    specificity = true_negatives / (true_negatives + false_positives) if (true_negatives + false_positives) > 0 else 0.0
    true_negative_rate = specificity  # Same as specificity
    negative_predictive_value = true_negatives / (true_negatives + false_negatives) if (true_negatives + false_negatives) > 0 else 0.0
    
    # Error rates
    false_positive_rate = false_positives / (false_positives + true_negatives) if (false_positives + true_negatives) > 0 else 0.0
    false_negative_rate = false_negatives / (false_negatives + true_positives) if (false_negatives + true_positives) > 0 else 0.0
    false_discovery_rate = false_positives / (false_positives + true_positives) if (false_positives + true_positives) > 0 else 0.0
    false_omission_rate = false_negatives / (false_negatives + true_negatives) if (false_negatives + true_negatives) > 0 else 0.0
    
    # Additional metrics
    prevalence = (true_positives + false_negatives) / total_population if total_population > 0 else 0.0
    f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    # Likelihood ratios
    positive_likelihood_ratio = sensitivity / false_positive_rate if false_positive_rate > 0 else float('inf')
    negative_likelihood_ratio = false_negative_rate / specificity if specificity > 0 else float('inf')
    
    # Diagnostic odds ratio
    diagnostic_odds_ratio = positive_likelihood_ratio / negative_likelihood_ratio if negative_likelihood_ratio > 0 else float('inf')

    return {
        # Raw counts
        'total_citations': float(total_citations),
        'total_errors': float(total_errors),
        'valid_citations': float(valid_citations),
        
        # Confusion matrix values
        'true_positives': float(true_positives),
        'true_negatives': float(true_negatives),
        'false_positives': float(false_positives),
        'false_negatives': float(false_negatives),
        
        # Core performance metrics
        'accuracy': accuracy,
        'accuracy_percent': accuracy * 100,
        'error_rate': error_rate,
        'error_rate_percent': error_rate * 100,
        
        # Positive prediction metrics
        'precision': precision,
        'recall': recall,
        'sensitivity': sensitivity,
        'true_positive_rate': true_positive_rate,
        'f1_score': f1_score,
        
        # Negative prediction metrics
        'specificity': specificity,
        'true_negative_rate': true_negative_rate,
        'negative_predictive_value': negative_predictive_value,
        
        # Error rates
        'false_positive_rate': false_positive_rate,
        'false_negative_rate': false_negative_rate,
        'false_discovery_rate': false_discovery_rate,
        'false_omission_rate': false_omission_rate,
        
        # Additional metrics
        'prevalence': prevalence,
        'positive_likelihood_ratio': positive_likelihood_ratio,
        'negative_likelihood_ratio': negative_likelihood_ratio,
        'diagnostic_odds_ratio': diagnostic_odds_ratio
    }


def generate_validation_report(
    output_dir: Path,
    error_summary: Dict[str, int], 
    accuracy_stats: Dict[str, float],
    extrapolated_results: Dict[str, float]
) -> Path:
    """Generate final reports showing what kinds of errors are most common."""
    pass


# Cleanup Function
def cleanup_database_connections(*connections) -> None:
    """Close all database connections properly."""
    for conn in connections:
        if conn is not None:
            try:
                conn.close()
                logger.info(f"Closed database connection: {conn}")
            except Exception as e:
                logger.error(f"Error closing database connection: {e}")


# utils.py


if __name__ == "__main__":
    try:
        exit_code: int = main()
    except KeyboardInterrupt:
        print("Validation interrupted by user")
        exit_code = 0
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        print(f"Unexpected error: {e}")
        exit_code = 1
    finally:
        sys.exit(exit_code)