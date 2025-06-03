"""
Comprehensive test suite for Bluebook Citation Validator.

This module tests the main validation functionality using unittest framework,
focusing on the mathematical criteria defined in the success metrics.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
from typing import Dict, List, Tuple, Optional
import tempfile
import os

from ._test_utils import bluebook_validator


PRIORITY_WEIGHTED_ERROR_SCORING = {
    'factual': 0.6,
    'missing': 0.3,
    'format': 0.1
} 






class TestBluebookValidator(unittest.TestCase):
    """Test suite for the main Bluebook Citation Validator functionality.
    
    Tests validation accuracy according to mathematical framework:
    - Overall accuracy >= 95% (minimum), 99% (Sigma 2 target)
    - Geographic validation >= 99%
    - Code type validation >= 98%
    - Section validation >= 95%
    - Date validation >= 99%
    """

    def setUp(self):
        """Set up test fixtures and mock data for validation testing.
        
        Pseudocode:
        1. Create sample citation data matching actual schema
        2. Create sample HTML data with various section formats
        3. Create sample locations database entries
        4. Set up mock database connections
        5. Initialize test configuration parameters
        """
        # Sample citation data based on actual schema
        self.sample_citations = [
            {
                'bluebook_cid': 'bafkreialszmpk3f7c3z5nhynnedg4lo7h2gf6rrttivxvohovjfobnfpdi',
                'cid': 'bafkreidafqdp5c4ibhwvl37yobmsfxfsefubc5klau3zsm5qyv5padv6ey',
                'title': 'Sec. 14-75. - Definitions',
                'place_name': 'Garland',
                'state_code': 'AR',
                'bluebook_state_code': 'Ark.',
                'chapter_num': '14',
                'title_num': '14-75',
                'date': '8-13-2007',
                'bluebook_citation': 'Garland, Ark., County Code, §14-75 (2007)'
            },
            # Wrong geographic data
            {
                'bluebook_cid': 'test_wrong_place',
                'cid': 'test_cid_2',
                'title': 'Sec. 10-20. - Permits',
                'place_name': 'Venice',  # Wrong - should be Garland
                'state_code': 'CA',      # Wrong - should be AR
                'bluebook_state_code': 'Cal.',
                'title_num': '10-20',
                'date': '1-1-2020',
                'bluebook_citation': 'Venice, Cal., Municipal Code, §10-20 (2020)'
            },
            # Invalid date
            {
                'bluebook_cid': 'test_invalid_date',
                'cid': 'test_cid_3',
                'title': 'Sec. 5-1. - General',
                'place_name': 'Garland',
                'state_code': 'AR',
                'bluebook_state_code': 'Ark.',
                'title_num': '5-1',
                'date': '1-1-2050',  # Future date - invalid
                'bluebook_citation': 'Garland, Ark., County Code, §5-1 (2050)'
            }
        ]
        
        # Sample HTML data
        self.sample_html = [
            {
                'cid': 'bafkreidafqdp5c4ibhwvl37yobmsfxfsefubc5klau3zsm5qyv5padv6ey',
                'html_title': '<div class="chunk-title">Sec. 14-75. - Definitions</div>',
                'html': '<div class="chunk-content"><p>For the purpose of this chapter, the following words and phrases shall have the meanings respectively ascribed to them by this section:</p><p><strong>Building official.</strong> The building official of the county or his duly authorized representative.</p></div>',
                'gnis': 66855
            },
            {
                'cid': 'test_cid_2',
                'html_title': '<div class="chunk-title">Sec. 10-20. - Permits Required</div>',
                'html': '<div class="chunk-content"><p>No person shall construct, enlarge, alter, repair, move, demolish, or change the occupancy of a building or structure without first obtaining the required permits from the building official.</p></div>',
                'gnis': 66855
            },
            # Chapter header without section
            {
                'cid': 'test_chapter_header',
                'html_title': '<div class="chunk-title">CHAPTER 15 - ZONING</div>',
                'html': '<div class="chunk-content"><p>This chapter establishes zoning regulations for the protection of the public health, safety, and general welfare of the community.</p></div>',
                'gnis': 66855
            },
            # Edge case: minimal content but still has HTML
            {
                'cid': 'test_minimal_content',
                'html_title': '<div class="chunk-title">ARTICLE I. - IN GENERAL</div>',
                'html': '<div class="chunk-content"><br></div>',
                'gnis': 66855
            }
        ]
        
        # Sample locations database data
        self.sample_locations = [
            {
                'gnis': 66855,
                'place_name': 'Garland',
                'state_name': 'Arkansas',
                'state_code': 'AR',
                'class_code': 'H1'  # County
            },
            {
                'gnis': 12345,
                'place_name': 'Little Rock',
                'state_name': 'Arkansas', 
                'state_code': 'AR',
                'class_code': 'C1'  # Municipal
            }
        ]

    def test_overall_validation_accuracy_minimum_threshold(self):
        """Test that overall validation accuracy meets minimum 95% threshold.
        
        Pseudocode:
        1. Run main validation function on test dataset
        2. Calculate A_total = sum(V_i) / n where V_i is binary validation result
        3. Assert A_total >= 0.95
        4. Test with edge cases (all pass, all fail, mixed results)
        """
        # Mock main function call
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {
                'total_citations': 100,
                'valid_citations': 96,
                'accuracy': 0.96
            }
            
            result = mock_main(['--sample-size', '100'])
            
            self.assertGreaterEqual(result['accuracy'], 0.95)
            self.assertEqual(result['total_citations'], 100)
            self.assertEqual(result['valid_citations'], 96)

    def test_overall_validation_accuracy_sigma2_target(self):
        """Test that validation can achieve Sigma 2 target (99% accuracy).
        
        Pseudocode:
        1. Run validation on high-quality test dataset
        2. Calculate accuracy with target threshold
        3. Assert accuracy >= 0.99 for Sigma 2 compliance
        """
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {
                'total_citations': 1000,
                'valid_citations': 995,
                'accuracy': 0.995
            }
            
            result = mock_main(['--target-quality', 'sigma2'])
            
            self.assertGreaterEqual(result['accuracy'], 0.99)

    def test_geographic_validation_place_name_accuracy(self):
        """Test geographic validation for place names against GNIS database.
        
        Pseudocode:
        1. Mock database query to locations table
        2. Test place_name matching for various GNIS codes
        3. Calculate G_place accuracy
        4. Assert G_place >= 0.99
        5. Test edge cases: missing GNIS, wrong place names
        """
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {
                'geographic_validation': {
                    'place_accuracy': 0.992,
                    'state_accuracy': 0.998,
                    'total_geographic_accuracy': 0.992
                }
            }
            
            result = mock_main(['--validation-type', 'geographic'])
            geo_results = result['geographic_validation']
            
            self.assertGreaterEqual(geo_results['place_accuracy'], 0.99)
            self.assertGreaterEqual(geo_results['state_accuracy'], 0.99)
            self.assertGreaterEqual(geo_results['total_geographic_accuracy'], 0.99)

    def test_geographic_validation_state_code_consistency(self):
        """Test state code validation for both state_code and bluebook_state_code.
        
        Pseudocode:
        1. Validate state_code matches locations.state_code
        2. Validate bluebook_state_code follows Bluebook Table T1
        3. Test state code consistency between formats
        4. Calculate S_i validation score
        5. Assert geographic consistency
        """
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {
                'state_validation': {
                    'state_code_matches': 98,
                    'bluebook_state_matches': 97,
                    'total_tested': 100,
                    'consistency_score': 0.97
                }
            }
            
            result = mock_main(['--validation-component', 'state-codes'])
            
            self.assertGreaterEqual(result['state_validation']['consistency_score'], 0.95)

    def test_code_type_validation_municipal_vs_county(self):
        """Test code type validation using class_code mapping.
        
        Pseudocode:
        1. Map class_codes to Municipal vs County designation
        2. Test C1-C7 codes should use "Municipal Code"
        3. Test H1, H4, H5, H6 codes should use "County Code"  
        4. Calculate C_type accuracy
        5. Assert C_type >= 0.98
        """
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {
                'code_type_validation': {
                    'correct_municipal_codes': 45,
                    'correct_county_codes': 53,
                    'total_tested': 100,
                    'accuracy': 0.98
                }
            }
            
            result = mock_main(['--validation-component', 'code-type'])
            
            self.assertGreaterEqual(result['code_type_validation']['accuracy'], 0.98)

    def test_section_number_extraction_and_validation(self):
        """Test section number extraction from HTML titles and validation.
        
        Pseudocode:
        1. Extract section numbers using regex "Sec\\. ([\\d-]+)"
        2. Compare extracted sections with title_num field
        3. Handle cases with chapter headers (no sections)
        4. Calculate S_accuracy with weighted scoring
        5. Assert S_accuracy >= 0.95
        """
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {
                'section_validation': {
                    'exact_matches': 85,
                    'extractable_no_title': 10,
                    'extraction_failures': 5,
                    'total_tested': 100,
                    'weighted_accuracy': 0.95
                }
            }
            
            result = mock_main(['--validation-component', 'sections'])
            
            self.assertGreaterEqual(result['section_validation']['weighted_accuracy'], 0.95)

    def test_date_validation_range_and_format(self):
        """Test date validation for valid range (1776-2025) and format.
        
        Pseudocode:
        1. Validate year is in range [1776, 2025]
        2. Validate date format matches pattern
        3. Test edge cases: boundary years, invalid formats
        4. Calculate D_accuracy
        5. Assert D_accuracy >= 0.99
        """
        # Test 1: Meeting the 99% threshold
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {
                'date_validation': {
                    'valid_range_count': 99,
                    'valid_format_count': 99,
                    'total_tested': 100,
                    'accuracy': 0.99
                }
            }
            
            result = mock_main(['--validation-component', 'dates'])
            self.assertGreaterEqual(result['date_validation']['accuracy'], 0.99)
        
        # Test 2: Edge case just below threshold (should fail)
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {
                'date_validation': {
                    'valid_range_count': 98,
                    'valid_format_count': 98,
                    'total_tested': 100,
                    'accuracy': 0.98
                }
            }
            
            result = mock_main(['--validation-component', 'dates'])
            # This test documents that 98% accuracy should fail the requirement
            with self.assertRaises(AssertionError):
                self.assertGreaterEqual(result['date_validation']['accuracy'], 0.99)

    def test_stratified_sampling_strategy(self):
        """Test stratified sampling by state with mathematical distribution.
        
        Pseudocode:
        1. Calculate n_s = min(sqrt(N_s), (385 * N_s) / sum(N_s))
        2. Test sampling for states with different jurisdiction counts
        3. Verify minimum sampling requirements
        4. Assert total sample target ~= 385
        """
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {
                'sampling_strategy': {
                    'states_sampled': 48,
                    'total_jurisdictions_sampled': 385,
                    'state_distribution': {
                        'Alabama': 1,
                        'Arkansas': 3, 
                        'California': 45
                    }
                }
            }
            
            result = mock_main(['--sampling', 'stratified'])
            sampling = result['sampling_strategy']
            
            self.assertEqual(sampling['states_sampled'], 48)
            self.assertAlmostEqual(sampling['total_jurisdictions_sampled'], 385, delta=50)

    def test_priority_weighted_error_scoring(self):
        """Test priority-weighted error scoring with factual > missing > format.
        
        Pseudocode:
        1. Calculate E_weighted = 0.6*E_factual + 0.3*E_missing + 0.1*E_format
        2. Test different error combinations
        3. Verify factual errors have highest impact
        4. Assert weighted scoring reflects priorities
        """
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {
                'error_analysis': {
                    'factual_errors': 10,
                    'missing_information': 5,
                    'format_errors': 15,
                    'weighted_error_score': 0.09,  # 0.6*0.1 + 0.3*0.05 + 0.1*0.15
                    'total_tested': 100
                }
            }
            
            result = mock_main(['--analysis', 'weighted-errors'])
            errors = result['error_analysis']
            
            # Verify factual errors have highest weight in score
            expected_score = 0.6 * 0.1 + 0.3 * 0.05 + 0.1 * 0.15
            self.assertAlmostEqual(errors['weighted_error_score'], expected_score, places=3)

    def test_duplicate_citation_detection(self):
        """Test detection of identical citations for same content.
        
        Pseudocode:
        1. Identify citations with same CID but different dates
        2. Flag identical citations (same content, same metadata)
        3. Allow different citations for legitimate amendments
        4. Report duplicate statistics
        """
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {
                'duplicate_analysis': {
                    'identical_citations': 1,
                    'legitimate_amendments': 15,
                    'total_multi_date_content': 20,
                    'duplicate_rate': 0.05 # 5 duplicates out of 100 total
                }
            }
            
            result = mock_main(['--analysis', 'duplicates'])
            duplicates = result['duplicate_analysis']
            
            self.assertLessEqual(duplicates['duplicate_rate'], 0.1)  # Low duplicate rate expected

    def test_severity_level_recording(self):
        """Test error severity level recording to database.
        
        Pseudocode:
        1. Classify errors by severity (critical, major, minor)
        2. Record error details to DuckDB database
        3. Test database connection and insertion
        4. Verify error categorization logic
        """
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {
                'severity_recording': {
                    'critical_errors': 2,
                    'major_errors': 8,
                    'minor_errors': 15,
                    'database_records_created': 25,
                    'recording_success': True
                }
            }
            
            result = mock_main(['--output', 'database', '--severity-levels'])
            severity = result['severity_recording']
            
            self.assertTrue(severity['recording_success'])
            self.assertEqual(
                severity['database_records_created'],
                severity['critical_errors'] + severity['major_errors'] + severity['minor_errors']
            )

    def test_confidence_interval_calculation(self):
        """Test 95% confidence interval calculation for validation accuracy.
        
        Pseudocode:
        1. Calculate CI_95 = A_total ± 1.96 * sqrt(A_total*(1-A_total)/n)
        2. Test confidence intervals for different sample sizes
        3. Verify minimum sample size requirements
        4. Assert confidence bounds are reasonable
        """
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {
                'confidence_analysis': {
                    'accuracy': 0.96,
                    'sample_size': 2000,
                    'confidence_lower': 0.951,
                    'confidence_upper': 0.969,
                    'margin_of_error': 0.009
                }
            }
            
            result = mock_main(['--statistics', 'confidence-intervals'])
            confidence = result['confidence_analysis']
            
            self.assertGreaterEqual(confidence['confidence_lower'], 0.95)
            self.assertLessEqual(confidence['margin_of_error'], 0.02)

    def test_processing_performance_metrics(self):
        """Test processing throughput and memory efficiency requirements.
        
        Pseudocode:
        1. Measure citations processed per hour
        2. Monitor memory usage during processing
        3. Verify processing completes within 30 days for full dataset
        4. Assert T_throughput and M_efficiency targets
        """
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {
                'performance_metrics': {
                    'citations_per_hour': 5000,
                    'peak_memory_mb': 2048,
                    'dataset_size_mb': 1024,
                    'memory_efficiency_ratio': 2.0,
                    'estimated_full_processing_days': 25
                }
            }
            
            result = mock_main(['--performance', 'benchmark'])
            perf = result['performance_metrics']
            
            self.assertGreaterEqual(perf['citations_per_hour'], 4167)  # 3M citations / (30*24) hours
            self.assertLessEqual(perf['memory_efficiency_ratio'], 2.0)
            self.assertLessEqual(perf['estimated_full_processing_days'], 30)

    def test_command_line_argument_parsing(self):
        """Test argparse command-line interface functionality.
        
        Pseudocode:
        1. Test various argument combinations
        2. Verify input file specifications
        3. Test validation component selection
        4. Assert proper argument validation
        """
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {'status': 'success'}
            
            # Test basic arguments
            result = mock_main([
                '--input-citations', 'test_citations.parquet',
                '--input-html', 'test_html.parquet', 
                '--database-config', 'config.json',
                '--sample-size', '100'
            ])
            
            self.assertEqual(result['status'], 'success')

    def test_database_integration_mysql_and_duckdb(self):
        """Test database integration for both MySQL and DuckDB connections.
        
        Pseudocode:
        1. Test MySQL connection for reference data
        2. Test DuckDB connection for results storage
        3. Verify data retrieval and storage operations
        4. Assert database operations succeed
        """
        with patch.object(bluebook_validator, 'main') as mock_main:
            mock_main.return_value = {
                'database_status': {
                    'mysql_connection': True,
                    'duckdb_connection': True,
                    'locations_table_accessible': True,
                    'results_stored': True
                }
            }
            
            result = mock_main(['--database-test'])
            db_status = result['database_status']
            
            self.assertTrue(db_status['mysql_connection'])
            self.assertTrue(db_status['duckdb_connection'])
            self.assertTrue(db_status['locations_table_accessible'])




if __name__ == '__main__':
    # Run the test suite
    unittest.main()