"""
Comprehensive integration guide for GraphRAG optimization infrastructure.

This module demonstrates the integration and usage of all major GraphRAG
optimization components including error handling, validation, transformations,
language support, and configuration management.

Guide Overview:
- Basic ontology extraction workflow
- Multi-language extraction with language routing
- Error handling and recovery patterns
- Configuration validation and merging
- Data transformation pipelines
- Advanced optimization scenarios

Recommended Reading Order:
1. BasicOntologyExtraction - Start with basic entity/relationship extraction
2. MultiLanguageWorkflow - Add language support for global text processing
3. ErrorHandlingPatterns - Learn recovery and resilience strategies
4. ConfigurationManagement - Understand advanced configuration tuning
5. TransformationPipelines - Process and normalize extraction results
6. AdvancedScenarios - Combine multiple features for complex use cases
"""

from typing import Dict, Any, List, Optional, Tuple
from ipfs_datasets_py.optimizers.graphrag.error_handling import (
    GraphRAGException, GraphRAGConfigError, GraphRAGExtractionError,
    GraphRAGValidationError, ErrorContext, retry_with_backoff, safe_operation,
)
from ipfs_datasets_py.optimizers.graphrag.response_validators import (
    ResponseValidator, EntityExtractionValidator, ValidationResult,
)
from ipfs_datasets_py.optimizers.graphrag.data_transformers import (
    normalize_entity, normalize_relationship, TransformationPipeline,
)
from ipfs_datasets_py.optimizers.graphrag.config_validators import (
    FieldConstraint, ConfigValidator, ExtractionConfigValidator,
)
from ipfs_datasets_py.optimizers.graphrag.language_router import (
    LanguageRouter, LanguageConfig,
)


class BasicOntologyExtraction:
    """
    Basic workflow for extracting entities and relationships from text.
    
    This example shows:
    - Simple entity extraction
    - Validation of extracted entities
    - Error handling with recovery
    """
    
    def __init__(self):
        """Initialize basic extraction workflow."""
        self.validator = EntityExtractionValidator()
        self.logger = None
    
    def extract_and_validate(self, text: str) -> Dict[str, Any]:
        """
        Extract entities from text and validate results.
        
        Args:
            text: Input text to process
            
        Returns:
            Dictionary with entities and validation results
        """
        # Simple extraction (placeholder - would use actual extractor)
        entities = [
            {
                'id': 'e1',
                'text': 'Company A',
                'type': 'Organization',
                'confidence': 0.92
            },
            {
                'id': 'e2',
                'text': 'John Doe',
                'type': 'Person',
                'confidence': 0.87
            }
        ]
        
        # Validate extracted entities
        validation_result = self.validator.validate_batch(entities)
        
        return {
            'entities': entities,
            'validation': validation_result.to_dict() if hasattr(validation_result, 'to_dict') else {}
        }
    
    def extract_with_retry(self, text: str, max_attempts: int = 3) -> Dict[str, Any]:
        """
        Extract with automatic retry on failure.
        
        Args:
            text: Input text
            max_attempts: Maximum retry attempts
            
        Returns:
            Extraction results or empty dict on failure
        """
        def _extract():
            return self.extract_and_validate(text)

        extract_with_retry = retry_with_backoff(
            _extract,
            max_attempts=max_attempts,
            backoff_factor=2.0,
        )

        try:
            return extract_with_retry()
        except (
            GraphRAGException,
            AttributeError,
            KeyError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            if self.logger and hasattr(self.logger, "error"):
                self.logger.error(f"Extraction failed after {max_attempts} attempts: {e}")
            return {}


class MultiLanguageWorkflow:
    """
    Workflow for multi-language text processing with language detection.
    
    This example shows:
    - Automatic language detection
    - Language-specific configuration
    - Multi-language extraction
    """
    
    def __init__(self):
        """Initialize multi-language workflow."""
        self.router = LanguageRouter(confidence_threshold=0.6)
        self.extractor = None  # Would be actual extractor
    
    def process_multilingual_text(
        self,
        text: str,
        domain: str = 'legal'
    ) -> Dict[str, Any]:
        """
        Process text in any language with automatic routing.
        
        Args:
            text: Input text (any language)
            domain: Domain for vocabulary selection
            
        Returns:
            Results with language metadata
            
        Example:
            workflow = MultiLanguageWorkflow()
            result = workflow.process_multilingual_text(
                "El paciente tiene una obligación de informar",
                domain='medical'
            )
            # Returns: {detected_language: 'Spanish', entities: [...]}
        """
        # Detect language
        language_code = self.router.detect_language(text)
        config = self.router.get_language_config(language_code)
        
        # Get domain vocabulary for this language
        domain_vocab = config.domain_vocab.get(domain, [])
        
        # Extract with language awareness
        def extractor(text, cfg):
            # In real implementation, would use domain_vocab in extraction
            return [], []
        
        result = self.router.extract_with_language_awareness(
            text,
            extractor,
            apply_confidence_adjustment=True
        )
        
        return {
            'detected_language': result.detected_language,
            'language_confidence': result.language_confidence,
            'entities': result.entities,
            'relationships': result.relationships,
            'domain_vocab_size': len(domain_vocab),
            'processing_notes': result.language_processing_notes,
        }
    
    def batch_process_languages(
        self,
        texts: List[Tuple[str, str]]  # (text, language_code)
    ) -> List[Dict[str, Any]]:
        """
        Process multiple texts, each in a specific language.
        
        Args:
            texts: List of (text, language) tuples
            
        Returns:
            List of processing results
            
        Example:
            results = workflow.batch_process_languages([
                ("The person must comply", "en"),
                ("La persona debe cumplir", "es"),
                ("La personne doit se conformer", "fr"),
            ])
        """
        results = []
        for text, expected_language in texts:
            detected_language = self.router.detect_language(text)
            
            # Check if detection matches expectation
            language_match = detected_language == expected_language
            
            config = self.router.get_language_config(detected_language)
            
            results.append({
                'text': text[:50],  # First 50 chars
                'expected_language': expected_language,
                'detected_language': detected_language,
                'language_match': language_match,
                'config_name': config.language_name,
            })
        
        return results


class ErrorHandlingPatterns:
    """
    Demonstration of error handling and recovery patterns.
    
    This example shows:
    - Using context managers for operation tracking
    - Retry mechanisms with exponential backoff
    - Graceful error handling with fallbacks
    - Exception hierarchy usage
    """
    
    def __init__(self):
        """Initialize error handling patterns."""
        self.logger = None
    
    def complex_extraction_with_recovery(
        self,
        text: str,
        fallback_language: str = 'en'
    ) -> Dict[str, Any]:
        """
        Extract with comprehensive error handling.
        
        Args:
            text: Input text
            fallback_language: Language to use if detection fails
            
        Returns:
            Extraction results with error tracking
        """
        with ErrorContext("Complex extraction with recovery"):
            try:
                # Attempt primary extraction
                return self._primary_extraction(text)
            
            except GraphRAGExtractionError as e:
                # Handle extraction-specific errors
                self.logger.warning(f"Extraction failed: {e}. Attempting fallback...")
                return self._fallback_extraction(text, fallback_language)
            
            except GraphRAGConfigError as e:
                # Handle configuration errors
                self.logger.error(f"Configuration error: {e}")
                return self._minimal_extraction(text)
            
            except GraphRAGException as e:
                # Handle any other GraphRAG exceptions
                self.logger.error(f"GraphRAG error: {e}. Suggestions: {e.suggestions}")
                return {}
    
    def safe_extraction(self, text: str) -> Dict[str, Any]:
        """
        Safe extraction that never throws exceptions to caller.
        
        The @safe_operation decorator catches all exceptions and returns
        the fallback_value instead, logging the error internally.
        
        Args:
            text: Input text
            
        Returns:
            Extraction results or empty dict on error
        """
        safe_extract = safe_operation(self._primary_extraction, default={})
        return safe_extract(text) or {}

    def extraction_with_retry(self, text: str) -> Dict[str, Any]:
        """
        Extraction with automatic retry on transient failures.
        
        The @retry_with_backoff decorator automatically retries with
        exponential backoff if the function raises an exception.
        
        Args:
            text: Input text
            
        Returns:
            Extraction results
        """
        extract_with_retry = retry_with_backoff(
            self._primary_extraction,
            max_attempts=3,
            backoff_factor=2.0,
        )
        return extract_with_retry(text)
    
    def _primary_extraction(self, text: str) -> Dict[str, Any]:
        """Placeholder for primary extraction."""
        return {'entities': [], 'relationships': []}
    
    def _fallback_extraction(self, text: str, language: str) -> Dict[str, Any]:
        """Placeholder for fallback extraction."""
        return {'entities': [], 'relationships': [], 'fallback_language': language}
    
    def _minimal_extraction(self, text: str) -> Dict[str, Any]:
        """Minimal extraction without configuration."""
        return {'entities': [], 'relationships': [], 'minimal': True}


class ConfigurationManagement:
    """
    Advanced configuration validation and merging patterns.
    
    This example shows:
    - Field constraint validation
    - Configuration schema validation
    - Configuration merging with defaults
    - Issue detection and optimization hints
    """
    
    def __init__(self):
        """Initialize configuration management."""
        self.validator = ExtractionConfigValidator()
    
    def validate_extraction_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate extraction configuration with detailed reporting.
        
        Args:
            config: Configuration dictionary
            
        Returns:
            Validation results with issues and recommendations
            
        Example:
            config = {
                'confidence_threshold': 0.7,
                'max_entities': 100,
                'max_relationships': 200,
                'window_size': 512,
                'allowed_entity_types': ['PERSON', 'ORG'],
            }
            result = validator.validate_extraction_config(config)
            if result['is_valid']:
                print("Config is valid!")
            else:
                print(f"Issues found: {result['errors']}")
        """
        # Validate configuration
        validation_result = self.validator.validate(config)
        
        # Detect common issues
        issues = self.validator.detect_configuration_issues(config)
        
        return {
            'is_valid': validation_result.is_valid,
            'errors': [e.message for e in validation_result.errors],
            'warnings': [w.message for w in validation_result.warnings],
            'detected_issues': [
                {
                    'type': issue['type'],
                    'field': issue.get('field'),
                    'message': issue.get('message'),
                    'suggestion': issue.get('suggestion'),
                }
                for issue in issues
            ]
        }
    
    def merge_with_defaults(
        self,
        user_config: Dict[str, Any],
        defaults: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Merge user configuration with defaults.
        
        Args:
            user_config: User-provided configuration
            defaults: Default configuration (or None for built-in defaults)
            
        Returns:
            Merged configuration
            
        Example:
            user_config = {'max_entities': 500, 'window_size': 256}
            merged = cm.merge_with_defaults(user_config)
            # Returns: {...defaults..., 'max_entities': 500, 'window_size': 256}
        """
        default_config = defaults or {
            'confidence_threshold': 0.6,
            'max_entities': 1000,
            'max_relationships': 5000,
            'window_size': 512,
        }
        
        merged = default_config.copy()
        merged.update(user_config)
        
        # Validate merged configuration
        validation = self.validate_extraction_config(merged)
        
        return merged


class TransformationPipelines:
    """
    Data transformation and normalization workflows.
    
    This example shows:
    - Creating transformation pipelines
    - Composing multiple transformations
    - Batch transformations with error recovery
    """
    
    def __init__(self):
        """Initialize transformation pipelines."""
        self.pipeline = TransformationPipeline()
    
    def normalize_extraction_results(
        self,
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
        confidence_threshold: float = 0.5
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Normalize and filter extraction results.
        
        Args:
            entities: Raw extracted entities
            relationships: Raw extracted relationships
            confidence_threshold: Minimum confidence to keep
            
        Returns:
            Normalized (entities, relationships) tuple
            
        Example:
            raw_entities = [{...}, {...}, ...]
            raw_relationships = [{...}, {...}, ...]
            
            normalized_entities, normalized_rels = pipeline.normalize_extraction_results(
                raw_entities,
                raw_relationships,
                confidence_threshold=0.7
            )
        """
        normalized_entities = []
        for entity in entities:
            normalized = normalize_entity(entity)
            if normalized.get('confidence', 0) >= confidence_threshold:
                normalized_entities.append(normalized)
        
        normalized_relationships = []
        for rel in relationships:
            normalized = normalize_relationship(rel)
            if normalized.get('confidence', 0) >= confidence_threshold:
                normalized_relationships.append(normalized)
        
        return normalized_entities, normalized_relationships
    
    def build_transformation_chain(
        self,
        operations: List[str]
    ) -> 'TransformationPipeline':
        """
        Build a transformation pipeline from operation names.
        
        Args:
            operations: List of operation names ('normalize', 'filter', etc.)
            
        Returns:
            Configured TransformationPipeline
            
        Example:
            pipeline = tm.build_transformation_chain([
                'normalize',
                'filter_confidence',
                'deduplicate',
            ])
        """
        pipeline = TransformationPipeline()
        
        for op in operations:
            if op == 'normalize':
                pipeline.transform(normalize_entity)
            elif op == 'filter_confidence':
                pipeline.transform(lambda e: e if e.get('confidence', 0) > 0.6 else None)
            # Add more operations as needed
        
        return pipeline


class AdvancedScenarios:
    """
    Complex workflows combining multiple components.
    
    This example shows:
    - End-to-end multi-language extraction
    - Configuration-aware processing
    - Error recovery with validation
    - Result normalization and filtering
    """
    
    def __init__(self):
        """Initialize advanced scenario handler."""
        self.language_router = LanguageRouter()
        self.config_validator = ExtractionConfigValidator()
        self.entity_validator = EntityExtractionValidator()
    
    def complete_multilingual_pipeline(
        self,
        text: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Complete end-to-end pipeline with all components.
        
        Args:
            text: Input text (any language)
            config: Extraction configuration
            
        Returns:
            Final results with metadata
            
        Example:
            result = processor.complete_multilingual_pipeline(
                "La empresa tiene obligaciones legales",
                {
                    'confidence_threshold': 0.7,
                    'max_entities': 100,
                    'allowed_entity_types': ['ORGANIZATION', 'LOCATION'],
                }
            )
        """
        results = {
            'steps_completed': [],
            'errors': [],
            'warnings': [],
        }
        
        try:
            # Step 1: Validate configuration
            validation = self.config_validator.validate(config)
            results['steps_completed'].append('config_validation')
            
            if not validation.is_valid:
                results['errors'].extend([e.message for e in validation.errors])
                # Continue with defaults
            
            # Step 2: Detect language
            language_code = self.language_router.detect_language(text)
            results['detected_language'] = language_code
            results['steps_completed'].append('language_detection')
            
            # Step 3: Extract (placeholder)
            entities = []
            relationships = []
            results['steps_completed'].append('extraction')
            
            # Step 4: Validate extracted entities
            validation_result = self.entity_validator.validate_batch(entities)
            results['entity_validation'] = {
                'total_checked': len(entities),
                'valid_count': len([e for e in entities if True]),  # Simplified
            }
            results['steps_completed'].append('entity_validation')
            
            # Step 5: Normalize and filter
            confidence_threshold = config.get('confidence_threshold', 0.6)
            normalized_entities = [
                normalize_entity(e) for e in entities
                if e.get('confidence', 0) >= confidence_threshold
            ]
            results['steps_completed'].append('normalization')
            
            # Final results
            results['final_results'] = {
                'entity_count': len(normalized_entities),
                'relationship_count': len(relationships),
                'language': language_code,
            }
            
        except (
            GraphRAGException,
            AttributeError,
            KeyError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            results['errors'].append(str(e))
        
        return results


# ============================================================================
# Integration Tests & Examples
# ============================================================================

def integration_example_1():
    """Basic extraction workflow."""
    workflow = BasicOntologyExtraction()
    result = workflow.extract_and_validate("Some text here")
    print(f"Basic extraction: {len(result.get('entities', []))} entities found")


def integration_example_2():
    """Multi-language processing."""
    workflow = MultiLanguageWorkflow()
    result = workflow.process_multilingual_text(
        "El paciente tiene una obligación",
        domain='medical'
    )
    print(f"Language detected: {result['detected_language']}")


def integration_example_3():
    """Configuration validation."""
    config_mgmt = ConfigurationManagement()
    config = {
        'confidence_threshold': 0.75,
        'max_entities': 100,
        'max_relationships': 500,
    }
    validation = config_mgmt.validate_extraction_config(config)
    print(f"Config valid: {validation['is_valid']}")


def integration_example_4():
    """Complete advanced pipeline."""
    processor = AdvancedScenarios()
    result = processor.complete_multilingual_pipeline(
        "Some text",
        {'confidence_threshold': 0.7}
    )
    print(f"Pipeline steps: {result['steps_completed']}")


if __name__ == '__main__':
    """Run integration examples."""
    print("=" * 70)
    print("GraphRAG Integration Guide Examples")
    print("=" * 70)
    
    print("\n1. Basic Extraction:")
    integration_example_1()
    
    print("\n2. Multi-Language Processing:")
    integration_example_2()
    
    print("\n3. Configuration Validation:")
    integration_example_3()
    
    print("\n4. Advanced Pipeline:")
    integration_example_4()
    
    print("\n" + "=" * 70)
    print("Integration examples completed!")
    print("=" * 70)
