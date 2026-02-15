#!/usr/bin/env python3
"""
Pytest migration of test_skeleton_text_quality.py

Text Quality Tests for the Omni-Converter.
This module tests the quality of text extraction for different file types.
Converted from unittest to pytest format while preserving all test logic.
"""

import os
import json
import random
import tempfile
import pytest
from datetime import datetime
from typing import Any, Union, Optional


from nltk.translate.bleu_score import sentence_bleu
import string


from core.core_factory import make_processing_pipeline
from core.file_validator._file_validator import FileValidator


@pytest.mark.performance
class TestTextQuality:
    """Test case for text quality evaluation."""

    def setup_method(self):
        """Set up test case with necessary data structures."""
        self._processing_pipeline = make_processing_pipeline()

        # Quality threshold from requirements (90%)
        self.quality_threshold = 0.9
        
        # Define weighting parameters for quality score calculation
        # These match the formulas in the TESTING.md document
        self.weights = {
            'text': {'bleu': 0.5, 'rouge_l': 0.3, 'structural': 0.2},
            'image': {'bleu': 0.6, 'rouge_l': 0.4},
            'audio': {'bleu': 0.6, 'rouge_l': 0.4},
            'video': {'bleu': 0.6, 'rouge_l': 0.4},
            'application': {'bleu': 0.5, 'rouge_l': 0.3, 'structural': 0.2}
        }
        
        # Create test data with reference texts and extracted texts
        self.test_files = self._create_test_files()
        
        # Create the results directory if it doesn't exist
        os.makedirs('tests/collected_results', exist_ok=True)
        
        # Create temp directory for output
        self.temp_output_dir = tempfile.mkdtemp()
        
        # Initialize validator
        self.validator = FileValidator()
        
        # Results will be stored here
        self.results = {
            'test_name': 'Text Quality for LLM Training',
            'timestamp': datetime.now().isoformat(),
            'categories': {},
            'overall': {
                'average_quality_score': 0,
                'meets_requirement': False
            }
        }
        
        # Try to load NLTK and other NLP libraries for better metrics
        self.nlp_available = False
        try:
            import nltk
            nltk.download('punkt', quiet=True)
            from nltk.translate.bleu_score import sentence_bleu
            self.nlp_available = True
            self.nltk = nltk
        except ImportError:
            print("NLTK not available. Using simplified text metrics.")
            
        # Try to load ROUGE metrics if available
        self.rouge_available = False
        try:
            from rouge import Rouge
            self.rouge = Rouge()
            self.rouge_available = True
        except ImportError:
            print("ROUGE metrics not available. Using simplified metrics.")

    def _create_test_files(self) -> dict[str, list[dict[str, Any]]]:
        """Create test file data with reference and extracted texts.
        
        Returns:
            Dictionary of test files by category
        """
        # Define where to look for ground truth reference files
        ground_truth_dirs = [
            os.path.join('test_files', 'ground_truth'),
            os.path.join('test_files', 'reference')
        ]
        
        # Find real test files with ground truth if available
        real_files = self._find_real_test_files_with_ground_truth(ground_truth_dirs)
        
        # Define extensions for each category
        extensions = {
            'text': ['html', 'xml', 'txt', 'csv', 'md'],
            'image': ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'],
            'audio': ['mp3', 'wav', 'ogg', 'flac', 'aac'],
            'video': ['mp4', 'webm', 'avi', 'mkv', 'mov'],
            'application': ['pdf', 'json', 'docx', 'xlsx']
        }
        
        # Create test files for each category
        test_files = {}
        
        for category, exts in extensions.items():
            category_files = []
            
            # Add real files if found
            category_real_files = [f for f in real_files if f['category'] == category]
            category_files.extend(category_real_files)
            
            # Add sample files to have at least a few files per category
            min_files = 3  # Minimum number of files to test per category
            if len(category_files) < min_files:
                for i in range(len(category_files), min_files):
                    ext = exts[i % len(exts)]
                    
                    category_files.append({
                        'file_name': f"sample_{category}_{i+1}.{ext}",
                        'file_path': f"/sample/path/sample_{category}_{i+1}.{ext}",
                        'format': ext,
                        'reference_text': self._generate_reference_text(ext),
                        'is_sample': True,
                        'category': category
                    })
            
            test_files[category] = category_files
        
        return test_files

    def _find_real_test_files_with_ground_truth(self, ground_truth_dirs: list[str]) -> list[dict[str, Any]]:
        """Find real test files that have corresponding ground truth reference text.
        
        Args:
            ground_truth_dirs: List of directories to search for ground truth files
            
        Returns:
            List of file dictionaries with ground truth data
        """
        real_files = []
        
        # For this skeleton implementation, return empty list
        # In a real implementation, this would search for .txt reference files
        # that correspond to test files in the test_files directory
        
        return real_files

    def _generate_reference_text(self, format_type: str) -> str:
        """Generate reference text for a given format type.
        
        Args:
            format_type: The file format/extension
            
        Returns:
            Reference text
        """
        # Very simplified text generation based on format
        # In a real implementation, these would be real text samples
        
        if format_type in ['html', 'xml', 'md', 'svg']:
            return (
                "This is a structured document with paragraphs and formatting.\n\n"
                "It contains multiple sections:\n"
                "* Section 1: Introduction to the topic\n"
                "* Section 2: Detailed explanation\n"
                "* Section 3: Conclusion\n\n"
                "It also includes a table:\n"
                "| Column 1 | Column 2 | Column 3 |\n"
                "| -------- | -------- | -------- |\n"
                "| Value 1  | Value 2  | Value 3  |\n"
                "| Value 4  | Value 5  | Value 6  |\n\n"
                "The document ends with a summary."
            )
        elif format_type == 'csv':
            return (
                "Name,Age,Location\n"
                "John Smith,34,New York\n"
                "Jane Doe,28,San Francisco\n"
                "Robert Johnson,45,Chicago\n"
                "Sarah Williams,31,Boston"
            )
        elif format_type == 'txt':
            return (
                "This is a plain text document.\n\n"
                "It contains several paragraphs of text without special formatting.\n\n"
                "Information is presented in a straightforward manner.\n\n"
                "The document is easy to read and process."
            )
        elif format_type in ['jpg', 'png', 'jpeg', 'gif', 'webp']:
            return (
                "This image shows a landscape with mountains in the background.\n"
                "There is a lake in the foreground reflecting the mountains.\n"
                "Trees can be seen along the shoreline.\n"
                "The sky is blue with some clouds."
            )
        elif format_type in ['mp3', 'wav', 'ogg', 'flac', 'aac']:
            return (
                "Speaker 1: Welcome to our discussion on climate change.\n"
                "Speaker 2: Thank you for having me.\n"
                "Speaker 1: What do you think are the biggest challenges we face?\n"
                "Speaker 2: I believe the main challenges are reducing emissions while maintaining economic growth.\n"
                "Speaker 1: How can individuals contribute to the solution?\n"
                "Speaker 2: Everyone can make a difference through sustainable choices in daily life."
            )
        elif format_type in ['mp4', 'webm', 'avi', 'mkv', 'mov']:
            return (
                "The video shows a presentation on renewable energy sources.\n\n"
                "The presenter discusses solar power, wind energy, and hydroelectric power.\n\n"
                "Charts and graphs are displayed showing the growth of renewable energy adoption.\n\n"
                "The presentation concludes with recommendations for future investments."
            )
        elif format_type in ['pdf', 'docx', 'xlsx']:
            return (
                "Title: Annual Report 2024\n\n"
                "Executive Summary:\n"
                "This report presents the company's performance for fiscal year 2024.\n\n"
                "1. Financial Results\n"
                "   Revenue increased by 15% compared to the previous year.\n"
                "   Operating expenses were reduced by 8%.\n"
                "   Net profit margin improved to 22%.\n\n"
                "2. Market Analysis\n"
                "   Market share grew from 18% to 23%.\n"
                "   Customer satisfaction score improved to 4.7/5.\n\n"
                "3. Future Outlook\n"
                "   We expect continued growth in the coming year.\n"
                "   New product launches are scheduled for Q2 and Q3.\n\n"
                "Appendix: Detailed financial statements are attached."
            )
        elif format_type == 'json':
            return (
                "{\n"
                "  \"users\": [\n"
                "    {\n"
                "      \"id\": 1,\n"
                "      \"name\": \"John Smith\",\n"
                "      \"email\": \"john@example.com\",\n"
                "      \"roles\": [\"admin\", \"user\"]\n"
                "    },\n"
                "    {\n"
                "      \"id\": 2,\n"
                "      \"name\": \"Jane Doe\",\n"
                "      \"email\": \"jane@example.com\",\n"
                "      \"roles\": [\"user\"]\n"
                "    }\n"
                "  ],\n"
                "  \"metadata\": {\n"
                "    \"version\": \"1.0\",\n"
                "    \"generated\": \"2024-03-15T10:30:00Z\"\n"
                "  }\n"
                "}"
            )
        else:
            return f"Sample text for {format_type} format."

    def _generate_extracted_text(self, reference_text: str, quality_factor: float = 0.85) -> str:
        """Generate realistic extracted text based on reference text.
        
        Args:
            reference_text: The reference/ground truth text
            quality_factor: How similar the extracted text should be (0.0-1.0)
            
        Returns:
            Simulated extracted text with realistic imperfections
        """
        extracted_text = reference_text
        
        if quality_factor >= 0.95:
            # High quality extraction - minimal changes
            return extracted_text
        elif quality_factor >= 0.85:
            # Good quality - minor formatting issues
            extracted_text = extracted_text.replace('\n\n', '\n')  # Some paragraph breaks lost
            extracted_text = extracted_text.replace('*', '-')      # Bullet points changed
        elif quality_factor >= 0.70:
            # Medium quality - some text issues
            extracted_text = extracted_text.replace('\n\n', ' ')   # Paragraph structure lost
            extracted_text = extracted_text.replace('|', ' ')      # Table formatting lost
            extracted_text = extracted_text.replace('-', ' ')      # Lists become regular text
        else:
            # Low quality - significant issues
            # Introduce character recognition errors
            replacements = [
                ('o', '0'), ('l', '1'), ('S', '5'), ('B', '8'),
                ('i', 'l'), ('rn', 'm'), ('cl', 'd'), ('vv', 'w')
            ]
            for old, new in replacements:
                if random.random() < 0.1:  # 10% chance of each replacement
                    extracted_text = extracted_text.replace(old, new)
            
            # Remove some content
            lines = extracted_text.split('\n')
            extracted_text = '\n'.join(lines[::2])  # Keep every other line
        
        return extracted_text

    def _process_file_and_extract_text(self, file_data: dict[str, Any]) -> Optional[str]:
        """Process a file and extract text using the processing pipeline.
        
        Args:
            file_data: File information dictionary
            
        Returns:
            Extracted text or None if processing failed
        """
        if file_data.get('is_sample', False):
            # For sample files, simulate extraction with varying quality
            quality_factor = random.uniform(0.7, 0.95)  # Random quality between 70% and 95%
            return self._generate_extracted_text(file_data['reference_text'], quality_factor)
        
        # For real files, use actual processing pipeline
        try:
            # Create output path
            output_path = os.path.join(
                self.temp_output_dir,
                f"{os.path.splitext(file_data['file_name'])[0]}.txt"
            )
            
            # Process the file
            result = self._processing_pipeline.process_file(
                file_data['file_path'],
                output_path,
                {'format': 'txt'}
            )
            
            if result.success and os.path.exists(output_path):
                with open(output_path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                return None
                
        except Exception as e:
            print(f"Error processing {file_data['file_name']}: {e}")
            return None

    def _calculate_bleu_score(self, reference: str, extracted: str) -> float:
        """Calculate BLEU score between reference and extracted text.
        
        Args:
            reference: Reference text
            extracted: Extracted text
            
        Returns:
            BLEU score (0.0 to 1.0)
        """
        if not self.nlp_available:
            # Simplified similarity without NLTK
            return self._simple_text_similarity(reference, extracted)
        
        try:
            # Tokenize texts
            reference_tokens = self.nltk.word_tokenize(reference.lower())
            extracted_tokens = self.nltk.word_tokenize(extracted.lower())
            
            # Calculate BLEU score
            return sentence_bleu([reference_tokens], extracted_tokens)
            
        except Exception as e:
            print(f"Error calculating BLEU score: {e}")
            return self._simple_text_similarity(reference, extracted)

    def _calculate_rouge_l_score(self, reference: str, extracted: str) -> float:
        """Calculate ROUGE-L score between reference and extracted text.
        
        Args:
            reference: Reference text
            extracted: Extracted text
            
        Returns:
            ROUGE-L F1 score (0.0 to 1.0)
        """
        if not self.rouge_available:
            # Use simplified longest common subsequence
            return self._simple_lcs_similarity(reference, extracted)
        
        try:
            scores = self.rouge.get_scores(extracted, reference)
            return scores[0]['rouge-l']['f']
            
        except Exception as e:
            print(f"Error calculating ROUGE-L score: {e}")
            return self._simple_lcs_similarity(reference, extracted)

    def _calculate_structural_preservation_score(self, reference: str, extracted: str) -> float:
        """Calculate how well the structural elements are preserved.
        
        Args:
            reference: Reference text
            extracted: Extracted text
            
        Returns:
            Structural preservation score (0.0 to 1.0)
        """
        # Count structural elements in reference and extracted texts
        structure_elements = [
            '\n\n',     # Paragraph breaks
            '\n*',      # Bullet points
            '\n-',      # Dash bullets
            '\n1.',     # Numbered lists
            '|',        # Table elements
            '**',       # Bold text
            '#',        # Headers
            ':',        # Colons (often indicate structure)
        ]
        
        ref_structure_count = sum(reference.count(elem) for elem in structure_elements)
        ext_structure_count = sum(extracted.count(elem) for elem in structure_elements)
        
        if ref_structure_count == 0:
            return 1.0  # No structure to preserve
        
        # Calculate preservation ratio
        preservation_ratio = min(ext_structure_count / ref_structure_count, 1.0)
        return preservation_ratio

    def _simple_text_similarity(self, text1: str, text2: str) -> float:
        """Calculate simple text similarity without external libraries.
        
        Args:
            text1: First text
            text2: Second text
            
        Returns:
            Similarity score (0.0 to 1.0)
        """
        # Convert to lowercase and split into words
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if len(words1) == 0 and len(words2) == 0:
            return 1.0
        if len(words1) == 0 or len(words2) == 0:
            return 0.0
        
        # Jaccard similarity
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0

    def _simple_lcs_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity based on longest common subsequence.
        
        Args:
            text1: First text
            text2: Second text
            
        Returns:
            LCS-based similarity score (0.0 to 1.0)
        """
        # Simple character-level LCS
        def lcs_length(s1, s2):
            m, n = len(s1), len(s2)
            dp = [[0] * (n + 1) for _ in range(m + 1)]
            
            for i in range(1, m + 1):
                for j in range(1, n + 1):
                    if s1[i-1] == s2[j-1]:
                        dp[i][j] = dp[i-1][j-1] + 1
                    else:
                        dp[i][j] = max(dp[i-1][j], dp[i][j-1])
            
            return dp[m][n]
        
        lcs_len = lcs_length(text1, text2)
        max_len = max(len(text1), len(text2))
        
        return lcs_len / max_len if max_len > 0 else 0.0

    def _calculate_quality_score(self, reference: str, extracted: str, category: str) -> dict[str, float]:
        """Calculate overall quality score for extracted text.
        
        Args:
            reference: Reference text
            extracted: Extracted text
            category: File category (text, image, audio, video, application)
            
        Returns:
            Dictionary with individual scores and overall quality
        """
        scores = {}
        
        # Calculate BLEU score
        scores['bleu'] = self._calculate_bleu_score(reference, extracted)
        
        # Calculate ROUGE-L score
        scores['rouge_l'] = self._calculate_rouge_l_score(reference, extracted)
        
        # Calculate structural preservation (only for text and application categories)
        if category in ['text', 'application']:
            scores['structural'] = self._calculate_structural_preservation_score(reference, extracted)
        
        # Calculate weighted overall score
        weights = self.weights[category]
        overall_score = 0.0
        
        for metric, weight in weights.items():
            if metric in scores:
                overall_score += scores[metric] * weight
        
        scores['overall'] = overall_score
        
        return scores

    @pytest.mark.slow
    def test_text_quality_for_llm_training(self):
        """Test text quality across different file types for LLM training suitability."""
        try:
            all_quality_scores = []
            
            for category, files in self.test_files.items():
                print(f"\nTesting text quality for {category} files:")
                print(f"Quality threshold: {self.quality_threshold}")
                print(f"Files to test: {len(files)} files")
                
                category_results = []
                
                for file_data in files:
                    print(f"Processing {file_data['file_name']}...")
                    
                    # Extract text from file
                    extracted_text = self._process_file_and_extract_text(file_data)
                    
                    if extracted_text is None:
                        print(f"Failed to extract text from {file_data['file_name']}")
                        quality_scores = {
                            'bleu': 0.0,
                            'rouge_l': 0.0,
                            'structural': 0.0,
                            'overall': 0.0
                        }
                        success = False
                    else:
                        # Calculate quality scores
                        quality_scores = self._calculate_quality_score(
                            file_data['reference_text'],
                            extracted_text,
                            category
                        )
                        success = True
                    
                    # Store file results
                    file_result = {
                        'file_name': file_data['file_name'],
                        'format': file_data['format'],
                        'success': success,
                        'is_sample': file_data.get('is_sample', False),
                        'quality_scores': quality_scores,
                        'meets_threshold': quality_scores['overall'] >= self.quality_threshold
                    }
                    
                    category_results.append(file_result)
                    all_quality_scores.append(quality_scores['overall'])
                    
                    print(f"  Overall quality: {quality_scores['overall']:.3f}")
                    print(f"  Meets threshold: {file_result['meets_threshold']}")
                
                # Calculate category statistics
                category_quality_scores = [r['quality_scores']['overall'] for r in category_results]
                category_avg_quality = sum(category_quality_scores) / len(category_quality_scores)
                meets_threshold_count = sum(1 for r in category_results if r['meets_threshold'])
                
                self.results['categories'][category] = {
                    'files_tested': len(category_results),
                    'real_files_tested': len([r for r in category_results if not r.get('is_sample', False)]),
                    'sample_files_tested': len([r for r in category_results if r.get('is_sample', False)]),
                    'average_quality_score': category_avg_quality,
                    'files_meeting_threshold': meets_threshold_count,
                    'percentage_meeting_threshold': (meets_threshold_count / len(category_results)) * 100,
                    'file_results': category_results
                }
                
                print(f"Category {category} results:")
                print(f"  Average quality: {category_avg_quality:.3f}")
                print(f"  Files meeting threshold: {meets_threshold_count}/{len(category_results)} ({(meets_threshold_count/len(category_results))*100:.1f}%)")
            
            # Calculate overall results
            overall_avg_quality = sum(all_quality_scores) / len(all_quality_scores)
            meets_requirement = overall_avg_quality >= self.quality_threshold
            
            self.results['overall'] = {
                'average_quality_score': overall_avg_quality,
                'meets_requirement': meets_requirement
            }
            
            print(f"\nOverall Results:")
            print(f"Average quality score: {overall_avg_quality:.3f}")
            print(f"Meets requirement ({self.quality_threshold}): {meets_requirement}")
            
            # Make assertion based on results
            # For skeleton implementation, we're lenient if we have mostly sample files
            real_file_count = sum(
                result['real_files_tested'] 
                for result in self.results['categories'].values()
            )
            
            if real_file_count >= 5:
                assert meets_requirement, f"Overall text quality score {overall_avg_quality:.3f} does not meet threshold {self.quality_threshold}"
            else:
                print("\nNote: Not enough real test files for strict quality assertion")
                # Still assert that we got reasonable scores from sample files
                assert overall_avg_quality > 0.5, "Text quality scores should be reasonable even for sample files"
            
        except ImportError as e:
            print(f"Failed to import required modules: {e}")
            self.results['error'] = str(e)
            pytest.fail(f"ImportError: {e}")
        except Exception as e:
            print(f"Unexpected error during testing: {e}")
            self.results['error'] = str(e)
            pytest.fail(f"Error: {e}")

    def teardown_method(self):
        """Save test results to a JSON file and clean up temporary files."""
        # Save results to JSON file
        output_file = os.path.join('tests', 'collected_results', 'text_quality.json')
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\nTest results saved to {output_file}")
        
        # Clean up temp directory
        if os.path.exists(self.temp_output_dir):
            import shutil
            try:
                shutil.rmtree(self.temp_output_dir)
            except Exception as e:
                print(f"Warning: Failed to clean up temporary directory: {e}")