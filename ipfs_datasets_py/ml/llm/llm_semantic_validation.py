"""
Semantic Validation Module for LLM Outputs in GraphRAG

This module provides schema-based validation and semantic augmentation for LLM outputs
in GraphRAG operations. It ensures that outputs conform to expected formats and
enriches them with domain-specific semantic information.

Main components:
- SchemaValidator: Validates LLM outputs against predefined schemas
- SemanticAugmenter: Enriches validated outputs with additional semantic information
- SchemaRegistry: Maintains a registry of schemas for different domains and tasks
- ValidationResult: Represents the result of a validation operation
- SPARQLValidator: Validates knowledge graphs against SPARQL endpoints like Wikidata
"""

import re
import time
import json
import logging
import jsonschema
import requests
from datetime import datetime
from typing import Dict, List, Any, Optional, Union, Tuple, Set, Callable, TypeVar, Generic

from ipfs_datasets_py.ml.llm.llm_interface import LLMInterface, MockLLMInterface, LLMInterfaceFactory
from ipfs_datasets_py.ml.llm.llm_graphrag import GraphRAGLLMProcessor, DomainSpecificProcessor
from ipfs_datasets_py.ml.llm.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer
from ipfs_datasets_py.knowledge_graphs.sparql_query_templates import *

# Type for generic schema validation
T = TypeVar('T')


class ValidationResult(Generic[T]):
    """
    Result of a validation operation.

    This class represents the result of validating an LLM output against a schema,
    including validation status, errors, and the validated/transformed data.
    """

    def __init__(
        self,
        is_valid: bool,
        data: Optional[T] = None,
        errors: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None
    ):
        """
        Initialize validation result.

        Args:
            is_valid: Whether the validation was successful
            data: The validated and potentially transformed data
            errors: List of validation errors
            warnings: List of validation warnings
        """
        self.is_valid = is_valid
        self.data = data
        self.errors = errors or []
        self.warnings = warnings or []
        self.timestamp = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "is_valid": self.is_valid,
            "data": self.data,
            "errors": self.errors,
            "warnings": self.warnings,
            "timestamp": self.timestamp.isoformat()
        }

    def __bool__(self) -> bool:
        """Boolean representation (True if valid)."""
        return self.is_valid


class SchemaRegistry:
    """
    Registry for maintaining schemas for different domains and tasks.

    This class provides a central registry for schemas used in validating
    LLM outputs, organized by domain, task, and version.
    """

    def __init__(self):
        """Initialize schema registry."""
        self._schemas: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._default_schemas: Dict[str, Dict[str, Any]] = {}

    def register_schema(
        self,
        domain: str,
        task: str,
        schema: Dict[str, Any],
        version: str = "1.0.0"
    ) -> None:
        """
        Register a schema for a domain and task.

        Args:
            domain: Domain for the schema (e.g., "academic", "medical")
            task: Task for the schema (e.g., "cross_document_reasoning")
            schema: JSON schema definition
            version: Schema version
        """
        if domain not in self._schemas:
            self._schemas[domain] = {}

        if task not in self._schemas[domain]:
            self._schemas[domain][task] = {}

        self._schemas[domain][task][version] = schema

    def register_default_schema(
        self,
        task: str,
        schema: Dict[str, Any],
        version: str = "1.0.0"
    ) -> None:
        """
        Register a default schema for a task.

        Args:
            task: Task for the schema
            schema: JSON schema definition
            version: Schema version
        """
        if task not in self._default_schemas:
            self._default_schemas[task] = {}

        self._default_schemas[task][version] = schema

    def get_schema(
        self,
        domain: str,
        task: str,
        version: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get a schema for a domain and task.

        Args:
            domain: Domain for the schema
            task: Task for the schema
            version: Schema version (latest if None)

        Returns:
            The schema or None if not found
        """
        # Check if domain exists
        if domain not in self._schemas:
            return self._get_default_schema(task, version)

        # Check if task exists
        if task not in self._schemas[domain]:
            return self._get_default_schema(task, version)

        # Get versions
        versions = self._schemas[domain][task]

        # If version is specified, get that version
        if version and version in versions:
            return versions[version]

        # Otherwise, get latest version
        if versions:
            latest_version = max(versions.keys())
            return versions[latest_version]

        # Fall back to default schema
        return self._get_default_schema(task, version)

    def _get_default_schema(
        self,
        task: str,
        version: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get a default schema for a task.

        Args:
            task: Task for the schema
            version: Schema version (latest if None)

        Returns:
            The schema or None if not found
        """
        # Check if task exists
        if task not in self._default_schemas:
            return None

        # Get versions
        versions = self._default_schemas[task]

        # If version is specified, get that version
        if version and version in versions:
            return versions[version]

        # Otherwise, get latest version
        if versions:
            latest_version = max(versions.keys())
            return versions[latest_version]

        return None


class SchemaValidator:
    """
    Validator for LLM outputs against predefined schemas.

    This class validates LLM outputs against JSON schemas, with support for
    different validation strategies and domain-specific schema selection.
    """

    def __init__(
        self,
        registry: Optional[SchemaRegistry] = None,
        llm_interface: Optional[LLMInterface] = None
    ):
        """
        Initialize schema validator.

        Args:
            registry: Schema registry (creates default if None)
            llm_interface: LLM interface for validation assistance (creates mock if None)
        """
        self.registry = registry or SchemaRegistry()
        # Prefer the factory so router-backed LLMs work end-to-end.
        self.llm = llm_interface or LLMInterfaceFactory.create()

        # Initialize with default schemas
        self._initialize_default_schemas()

    def _initialize_default_schemas(self) -> None:
        """Initialize default schemas for common tasks."""
        # Default schema for cross-document reasoning
        cross_doc_schema = {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
                "references": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["answer", "reasoning", "confidence"]
        }
        self.registry.register_default_schema("cross_document_reasoning", cross_doc_schema)

        # Default schema for evidence chain analysis
        evidence_chain_schema = {
            "type": "object",
            "properties": {
                "relationship_type": {
                    "type": "string",
                    "enum": ["complementary", "contradictory", "identical", "unrelated"]
                },
                "explanation": {"type": "string"},
                "inference": {"type": "string"},
                "confidence": {"type": "number"}
            },
            "required": ["relationship_type", "explanation", "inference", "confidence"]
        }
        self.registry.register_default_schema("evidence_chain_analysis", evidence_chain_schema)

    def validate(
        self,
        data: Any,
        domain: str,
        task: str,
        version: Optional[str] = None,
        strict: bool = False
    ) -> ValidationResult:
        """
        Validate data against a schema.

        Args:
            data: Data to validate
            domain: Domain for the schema
            task: Task for the schema
            version: Schema version (latest if None)
            strict: Whether to perform strict validation

        Returns:
            Validation result
        """
        # Get schema
        schema = self.registry.get_schema(domain, task, version)

        if not schema:
            return ValidationResult(
                is_valid=False,
                errors=[f"No schema found for domain '{domain}', task '{task}'"]
            )

        try:
            # Perform validation
            if strict:
                jsonschema.validate(instance=data, schema=schema)
            else:
                # In non-strict mode, we validate but collect all errors
                errors = list(jsonschema.Draft7Validator(schema).iter_errors(data))
                if errors:
                    return ValidationResult(
                        is_valid=False,
                        data=data,
                        errors=[str(e) for e in errors]
                    )

            # Validation succeeded
            return ValidationResult(is_valid=True, data=data)

        except jsonschema.exceptions.ValidationError as e:
            # Validation failed
            return ValidationResult(
                is_valid=False,
                data=data,
                errors=[str(e)]
            )
        except Exception as e:
            # Other error
            return ValidationResult(
                is_valid=False,
                errors=[f"Validation error: {str(e)}"]
            )

    def repair_and_validate(
        self,
        data: Any,
        domain: str,
        task: str,
        max_attempts: int = 3
    ) -> ValidationResult:
        """
        Attempt to repair invalid data and validate it.

        Args:
            data: Data to validate and potentially repair
            domain: Domain for the schema
            task: Task for the schema
            max_attempts: Maximum number of repair attempts

        Returns:
            Validation result with potentially repaired data
        """
        # First, try validating as-is
        result = self.validate(data, domain, task)

        if result.is_valid:
            return result

        # Get the schema for error reporting
        schema = self.registry.get_schema(domain, task)

        if not schema:
            return ValidationResult(
                is_valid=False,
                errors=[f"No schema found for domain '{domain}', task '{task}'"]
            )

        # Attempt to repair
        repaired_data = data
        for attempt in range(max_attempts):
            # Format the schema and errors for the LLM
            schema_str = json.dumps(schema, indent=2)
            errors_str = "\n".join(result.errors)

            # Create prompt for the LLM
            prompt = f"""
            Please fix the following JSON data to conform to the schema:

            SCHEMA:
            {schema_str}

            VALIDATION ERRORS:
            {errors_str}

            CURRENT DATA:
            {json.dumps(repaired_data, indent=2)}

            FIXED DATA (valid JSON that conforms to the schema):
            """

            try:
                # Ask the LLM to fix the data
                response = self.llm.generate(prompt)

                # Extract JSON from the response
                json_pattern = r"```json\s*([\s\S]*?)\s*```|```([\s\S]*?)```|\{[\s\S]*\}"
                match = re.search(json_pattern, response["text"])

                if match:
                    json_str = match.group(1) or match.group(2) or match.group(0)
                    repaired_data = json.loads(json_str)

                    # Validate the repaired data
                    result = self.validate(repaired_data, domain, task)

                    if result.is_valid:
                        return result

                else:
                    # Couldn't extract JSON
                    result.warnings.append(f"Repair attempt {attempt+1}: couldn't extract JSON from LLM response")

            except Exception as e:
                # Error during repair
                result.warnings.append(f"Repair attempt {attempt+1} failed: {str(e)}")

        # If we get here, all repair attempts failed
        return ValidationResult(
            is_valid=False,
            data=repaired_data,
            errors=result.errors,
            warnings=[*result.warnings, "All repair attempts failed"]
        )


class SemanticAugmenter:
    """
    Augments validated data with additional semantic information.

    This class enriches validated LLM outputs with domain-specific semantic
    information, such as entity linking, relation enhancement, and contextual
    information.
    """

    def __init__(
        self,
        llm_interface: Optional[LLMInterface] = None,
        domain_processor: Optional[DomainSpecificProcessor] = None
    ):
        """
        Initialize semantic augmenter.

        Args:
            llm_interface: LLM interface for semantic augmentation
            domain_processor: Domain-specific processor for context
        """
        self.llm = llm_interface or LLMInterfaceFactory.create()
        self.domain_processor = domain_processor

    def augment(
        self,
        data: Dict[str, Any],
        domain: str,
        task: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Augment data with semantic information.

        Args:
            data: Validated data to augment
            domain: Domain for augmentation
            task: Task for augmentation
            context: Additional context information

        Returns:
            Augmented data
        """
        # Copy data to avoid modifying the original
        augmented = data.copy()

        # Add domain information
        augmented["domain"] = domain
        augmented["task"] = task

        # Add timestamps
        augmented["augmented_at"] = datetime.now().isoformat()

        # Apply task-specific augmentation
        if task == "cross_document_reasoning":
            augmented = self._augment_cross_document_reasoning(augmented, domain, context)
        elif task == "evidence_chain_analysis":
            augmented = self._augment_evidence_chain(augmented, domain, context)

        return augmented

    def _augment_cross_document_reasoning(
        self,
        data: Dict[str, Any],
        domain: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Augment cross-document reasoning results.

        Args:
            data: Validated data to augment
            domain: Domain for augmentation
            context: Additional context information

        Returns:
            Augmented data
        """
        # Extract key information from the reasoning
        if "reasoning" in data:
            # Add key concepts extracted from reasoning
            data["key_concepts"] = self._extract_key_concepts(data["reasoning"])

            # Add uncertainty assessment
            data["uncertainty_assessment"] = self._assess_uncertainty(data["reasoning"], data.get("confidence", 0.0))

        # Add domain-specific augmentations
        if domain == "academic":
            data["scholarly_context"] = self._generate_scholarly_context(data, context)
        elif domain == "medical":
            data["clinical_relevance"] = self._generate_clinical_relevance(data, context)
        elif domain == "legal":
            data["legal_implications"] = self._generate_legal_implications(data, context)

        return data

    def _augment_evidence_chain(
        self,
        data: Dict[str, Any],
        domain: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Augment evidence chain analysis results.

        Args:
            data: Validated data to augment
            domain: Domain for augmentation
            context: Additional context information

        Returns:
            Augmented data
        """
        # Add confidence interpretation
        if "confidence" in data:
            confidence = data["confidence"]

            if confidence >= 0.8:
                data["confidence_interpretation"] = "high"
            elif confidence >= 0.5:
                data["confidence_interpretation"] = "moderate"
            else:
                data["confidence_interpretation"] = "low"

        # Add relationship strength based on relationship type
        if "relationship_type" in data:
            relationship_type = data["relationship_type"]

            if relationship_type == "complementary":
                data["relationship_strength"] = "strong"
            elif relationship_type == "contradictory":
                data["relationship_strength"] = "strong"
            elif relationship_type == "identical":
                data["relationship_strength"] = "very strong"
            else:  # unrelated
                data["relationship_strength"] = "none"

        return data

    def _extract_key_concepts(self, text: str) -> List[str]:
        """
        Extract key concepts from text.

        Args:
            text: Text to extract concepts from

        Returns:
            List of key concepts
        """
        # In a real implementation, this would use NLP or an LLM
        # For now, we'll use a simple approach based on capitalized phrases
        concept_pattern = r'\b[A-Z][a-z]*(?:\s+[A-Z][a-z]*)*\b'
        concepts = re.findall(concept_pattern, text)

        # Filter out common words
        common_words = {"The", "A", "An", "This", "That", "These", "Those", "I", "We", "They"}
        concepts = [c for c in concepts if c not in common_words and len(c) > 3]

        # Remove duplicates and limit to top 5
        return list(set(concepts))[:5]

    def _assess_uncertainty(self, text: str, confidence: float) -> Dict[str, Any]:
        """
        Assess uncertainty in reasoning.

        Args:
            text: Reasoning text
            confidence: Confidence score

        Returns:
            Uncertainty assessment
        """
        # Look for uncertainty markers in the text
        uncertainty_markers = [
            "may", "might", "could", "possibly", "perhaps", "probably",
            "likely", "unlikely", "uncertain", "unclear", "not clear",
            "suggests", "indicates", "seems", "appears"
        ]

        # Count occurrences of uncertainty markers
        marker_count = sum(1 for marker in uncertainty_markers if f" {marker} " in f" {text} ")

        # Calculate uncertainty score
        text_length = len(text.split())
        marker_density = marker_count / max(text_length, 1) * 100

        # Combine with confidence score
        combined_score = (1 - confidence) * 0.7 + (min(marker_density, 10) / 10) * 0.3

        # Interpret the score
        if combined_score < 0.3:
            interpretation = "low uncertainty"
        elif combined_score < 0.6:
            interpretation = "moderate uncertainty"
        else:
            interpretation = "high uncertainty"

        return {
            "score": combined_score,
            "interpretation": interpretation,
            "markers_found": marker_count,
            "confidence_impact": 1 - confidence
        }

    def _generate_scholarly_context(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate scholarly context for academic domain.

        Args:
            data: Result data
            context: Additional context information

        Returns:
            Scholarly context string
        """
        # In a real implementation, this would generate more comprehensive context
        key_concepts = data.get("key_concepts", [])

        if not key_concepts:
            return "No key scholarly concepts identified."

        # Create a scholarly context based on key concepts
        return f"This analysis relates to scholarly research in {', '.join(key_concepts[:3])}. The findings may contribute to the academic discourse on these topics."

    def _generate_clinical_relevance(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate clinical relevance for medical domain.

        Args:
            data: Result data
            context: Additional context information

        Returns:
            Clinical relevance string
        """
        return "The clinical relevance of these findings should be assessed by medical professionals. This analysis is for informational purposes only and does not constitute medical advice."

    def _generate_legal_implications(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate legal implications for legal domain.

        Args:
            data: Result data
            context: Additional context information

        Returns:
            Legal implications string
        """
        return "The legal implications discussed here are based on document analysis and should not be considered legal advice. Consult with legal professionals for definitive guidance."


class SemanticValidator:
    """
    Combines schema validation and semantic augmentation.

    This class provides a unified interface for validating LLM outputs against
    schemas and augmenting them with semantic information.
    """

    def __init__(
        self,
        validator: Optional[SchemaValidator] = None,
        augmenter: Optional[SemanticAugmenter] = None
    ):
        """
        Initialize semantic validator.

        Args:
            validator: Schema validator (creates default if None)
            augmenter: Semantic augmenter (creates default if None)
        """
        self.validator = validator or SchemaValidator()
        self.augmenter = augmenter or SemanticAugmenter()

    def process(
        self,
        data: Any,
        domain: str,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        auto_repair: bool = True
    ) -> Tuple[bool, Dict[str, Any], List[str]]:
        """
        Process data through validation and augmentation.

        Args:
            data: Data to process
            domain: Domain for processing
            task: Task for processing
            context: Additional context information
            auto_repair: Whether to attempt repair of invalid data

        Returns:
            Tuple of (success, processed_data, errors)
        """
        # Validate the data
        if auto_repair:
            result = self.validator.repair_and_validate(data, domain, task)
        else:
            result = self.validator.validate(data, domain, task)

        # If validation failed, return the errors
        if not result.is_valid:
            return False, data, result.errors

        # Augment the validated data
        augmented = self.augmenter.augment(result.data, domain, task, context)

        return True, augmented, []


class SPARQLValidator:
    """
    Validates knowledge graphs against SPARQL endpoints.

    This class provides advanced validation of knowledge graphs against SPARQL
    endpoints like Wikidata, enabling verification of extracted knowledge against
    established knowledge bases and detection of inconsistencies or missing information.
    """

    def __init__(
        self,
        endpoint_url: str = "https://query.wikidata.org/sparql",
        tracer: Optional[WikipediaKnowledgeGraphTracer] = None,
        llm_interface: Optional[LLMInterface] = None,
        cache_results: bool = True,
        cache_ttl: int = 3600
    ):
        """
        Initialize SPARQL validator.

        Args:
            endpoint_url: URL of the SPARQL endpoint to query
            tracer: Optional tracer for detailed tracing
            llm_interface: Optional LLM interface for explanation generation
            cache_results: Whether to cache validation results
            cache_ttl: Time-to-live for cached results in seconds
        """
        self.endpoint_url = endpoint_url
        self.tracer = tracer
        self.llm = llm_interface or LLMInterfaceFactory.create()
        self.cache_results = cache_results
        self.cache_ttl = cache_ttl
        self.cache = {}
        self.headers = {
            'User-Agent': 'IPFSDatasets-SPARQLValidator/1.0',
            'Accept': 'application/json'
        }

    def validate_entity(
        self,
        entity_name: str,
        entity_type: Optional[str] = None,
        entity_properties: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """
        Validate a single entity against the SPARQL endpoint.

        Args:
            entity_name: Name of the entity to validate
            entity_type: Optional type of the entity
            entity_properties: Optional properties of the entity

        Returns:
            ValidationResult: Result of validation
        """
        # Check if results are cached
        cache_key = f"entity_{entity_name}_{entity_type}"
        if self.cache_results and cache_key in self.cache:
            cache_entry = self.cache[cache_key]
            if time.time() - cache_entry["timestamp"] < self.cache_ttl:
                return cache_entry["result"]

        try:
            # Look up entity in Wikidata
            wikidata_entity = self._get_wikidata_entity(entity_name, entity_type)

            if not wikidata_entity:
                result = ValidationResult(
                    is_valid=False,
                    errors=[f"Entity '{entity_name}' not found in Wikidata"],
                    warnings=["Consider checking alternative spellings or labels"]
                )
                if self.cache_results:
                    self.cache[cache_key] = {
                        "result": result,
                        "timestamp": time.time()
                    }
                return result

            # Entity found, validate properties if provided
            mismatches = []
            validated_properties = {}

            if entity_properties:
                wikidata_props = self._get_entity_properties(wikidata_entity["id"])

                for prop_name, prop_value in entity_properties.items():
                    # Try to find matching property in Wikidata
                    matched, closest_match = self._match_property(prop_name, prop_value, wikidata_props)

                    if not matched:
                        mismatches.append({
                            "property": prop_name,
                            "expected": prop_value,
                            "closest_match": closest_match
                        })
                    else:
                        validated_properties[prop_name] = {
                            "wikidata_match": closest_match["property"],
                            "confidence": closest_match["confidence"]
                        }

            # Construct validation result
            result = ValidationResult(
                is_valid=len(mismatches) == 0,
                data={
                    "entity": entity_name,
                    "wikidata_entity": wikidata_entity,
                    "validated_properties": validated_properties,
                    "property_mismatches": mismatches
                },
                errors=[f"Mismatch in property '{m['property']}'" for m in mismatches],
                warnings=[]
            )

            # Cache the result if enabled
            if self.cache_results:
                self.cache[cache_key] = {
                    "result": result,
                    "timestamp": time.time()
                }

            return result

        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"SPARQL validation error: {str(e)}"]
            )

    def validate_relationship(
        self,
        source_entity: str,
        relationship_type: str,
        target_entity: str,
        bidirectional: bool = False
    ) -> ValidationResult:
        """
        Validate a relationship between entities against the SPARQL endpoint.

        Args:
            source_entity: Source entity name
            relationship_type: Type of relationship
            target_entity: Target entity name
            bidirectional: Whether the relationship is bidirectional

        Returns:
            ValidationResult: Result of validation
        """
        # Check if results are cached
        cache_key = f"rel_{source_entity}_{relationship_type}_{target_entity}_{bidirectional}"
        if self.cache_results and cache_key in self.cache:
            cache_entry = self.cache[cache_key]
            if time.time() - cache_entry["timestamp"] < self.cache_ttl:
                return cache_entry["result"]

        try:
            # Get Wikidata IDs for source and target entities
            source_wikidata = self._get_wikidata_entity(source_entity)
            target_wikidata = self._get_wikidata_entity(target_entity)

            if not source_wikidata or not target_wikidata:
                missing_entities = []
                if not source_wikidata:
                    missing_entities.append(source_entity)
                if not target_wikidata:
                    missing_entities.append(target_entity)

                result = ValidationResult(
                    is_valid=False,
                    errors=[f"Entities not found in Wikidata: {', '.join(missing_entities)}"],
                    warnings=["Relationship cannot be validated without entity lookup"]
                )
                if self.cache_results:
                    self.cache[cache_key] = {
                        "result": result,
                        "timestamp": time.time()
                    }
                return result

            # Check if relationship exists in Wikidata
            relationship_info = self._check_relationship(
                source_wikidata["id"],
                target_wikidata["id"],
                relationship_type,
                bidirectional
            )

            if not relationship_info["exists"]:
                result = ValidationResult(
                    is_valid=False,
                    data={
                        "source": source_entity,
                        "target": target_entity,
                        "relationship": relationship_type,
                        "wikidata_relationship": relationship_info["closest_match"]
                    },
                    errors=[f"Relationship '{relationship_type}' not found in Wikidata"],
                    warnings=[
                        f"Consider checking similar relationships: {relationship_info['closest_match']['property']}"
                        if relationship_info.get("closest_match") else
                        "No similar relationships found"
                    ]
                )
            else:
                result = ValidationResult(
                    is_valid=True,
                    data={
                        "source": source_entity,
                        "target": target_entity,
                        "relationship": relationship_type,
                        "wikidata_relationship": relationship_info["relationship"],
                        "confidence": relationship_info["confidence"]
                    }
                )

            # Cache the result if enabled
            if self.cache_results:
                self.cache[cache_key] = {
                    "result": result,
                    "timestamp": time.time()
                }

            return result

        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"SPARQL relationship validation error: {str(e)}"]
            )

    def validate_knowledge_graph(
        self,
        kg: Any,  # Should be KnowledgeGraph from knowledge_graph_extraction module
        main_entity_name: Optional[str] = None,
        validation_depth: int = 1,
        min_confidence: float = 0.7
    ) -> ValidationResult:
        """
        Validate an entire knowledge graph against the SPARQL endpoint.

        Args:
            kg: Knowledge graph to validate
            main_entity_name: Optional name of the main entity to validate against
            validation_depth: Depth of validation (1 = entity properties, 2 = relationships, 3 = full graph)
            min_confidence: Minimum confidence threshold for validation

        Returns:
            ValidationResult: Result of validation
        """
        # Start trace if tracer is available
        trace_id = None
        if self.tracer:
            trace_id = self.tracer.trace_validation(
                kg_name=getattr(kg, "name", "unknown_kg"),
                entity_name=main_entity_name or "all_entities"
            )

        try:
            # If the knowledge graph doesn't have the expected interface, return an error
            if not hasattr(kg, "entities") or not hasattr(kg, "relationships"):
                return ValidationResult(
                    is_valid=False,
                    errors=["Invalid knowledge graph object: missing entities or relationships attributes"]
                )

            entities = list(kg.entities.values()) if hasattr(kg.entities, "values") else kg.entities
            relationships = list(kg.relationships.values()) if hasattr(kg.relationships, "values") else kg.relationships

            # If main entity is specified, focus validation on that entity
            if main_entity_name:
                main_entities = [e for e in entities if e.name == main_entity_name]
                if not main_entities:
                    return ValidationResult(
                        is_valid=False,
                        errors=[f"Main entity '{main_entity_name}' not found in knowledge graph"]
                    )
                main_entity = main_entities[0]

                # Get Wikidata entity for main entity
                wikidata_entity = self._get_wikidata_entity(main_entity.name, main_entity.entity_type)

                if not wikidata_entity:
                    result = ValidationResult(
                        is_valid=False,
                        errors=[f"Main entity '{main_entity_name}' not found in Wikidata"],
                        warnings=["Consider checking alternative spellings or labels"]
                    )

                    if self.tracer and trace_id:
                        self.tracer.update_validation_trace(
                            trace_id=trace_id,
                            status="failed",
                            error=result.errors[0],
                            validation_results=result.to_dict()
                        )

                    return result

                # Get Wikidata properties for main entity
                wikidata_props = self._get_entity_properties(wikidata_entity["id"])

                # Validate properties
                property_validations = {}
                property_coverage = 0.0

                if hasattr(main_entity, "properties") and main_entity.properties:
                    valid_props = 0
                    for prop_name, prop_value in main_entity.properties.items():
                        matched, closest_match = self._match_property(prop_name, prop_value, wikidata_props)
                        property_validations[prop_name] = {
                            "valid": matched,
                            "wikidata_match": closest_match["property"] if closest_match else None,
                            "confidence": closest_match["confidence"] if closest_match else 0.0
                        }
                        if matched:
                            valid_props += 1

                    property_coverage = valid_props / len(main_entity.properties) if main_entity.properties else 0.0

                # If validation depth > 1, validate relationships
                relationship_validations = {}
                relationship_coverage = 0.0

                if validation_depth > 1:
                    # Get relationships involving the main entity
                    entity_relationships = []
                    for rel in relationships:
                        if (hasattr(rel, "source_entity") and hasattr(rel.source_entity, "entity_id") and
                            rel.source_entity.entity_id == main_entity.entity_id) or \
                           (hasattr(rel, "target_entity") and hasattr(rel.target_entity, "entity_id") and
                            rel.target_entity.entity_id == main_entity.entity_id):
                            entity_relationships.append(rel)

                    valid_rels = 0
                    for rel in entity_relationships:
                        # Determine source and target for validation
                        if hasattr(rel, "source_entity") and hasattr(rel.source_entity, "entity_id") and rel.source_entity.entity_id == main_entity.entity_id:
                            source = main_entity.name
                            target = rel.target_entity.name if hasattr(rel, "target_entity") and hasattr(rel.target_entity, "name") else "unknown"
                        else:
                            source = rel.source_entity.name if hasattr(rel, "source_entity") and hasattr(rel.source_entity, "name") else "unknown"
                            target = main_entity.name

                        # Validate relationship
                        rel_result = self.validate_relationship(
                            source,
                            rel.relationship_type if hasattr(rel, "relationship_type") else "related_to",
                            target,
                            rel.bidirectional if hasattr(rel, "bidirectional") else False
                        )

                        relationship_validations[rel.relationship_id if hasattr(rel, "relationship_id") else f"rel_{valid_rels}"] = {
                            "valid": rel_result.is_valid,
                            "source": source,
                            "target": target,
                            "relationship_type": rel.relationship_type if hasattr(rel, "relationship_type") else "related_to",
                            "wikidata_match": rel_result.data.get("wikidata_relationship", {}).get("property") if rel_result.is_valid else None,
                            "confidence": rel_result.data.get("confidence", 0.0) if rel_result.is_valid else 0.0
                        }

                        if rel_result.is_valid:
                            valid_rels += 1

                    relationship_coverage = valid_rels / len(entity_relationships) if entity_relationships else 0.0

                # Calculate overall coverage
                overall_coverage = (property_coverage + relationship_coverage) / 2 if validation_depth > 1 else property_coverage

                # Create validation result
                result = ValidationResult(
                    is_valid=overall_coverage >= min_confidence,
                    data={
                        "entity_name": main_entity.name,
                        "wikidata_entity": wikidata_entity,
                        "property_validations": property_validations,
                        "property_coverage": property_coverage,
                        "relationship_validations": relationship_validations,
                        "relationship_coverage": relationship_coverage,
                        "overall_coverage": overall_coverage
                    },
                    errors=[] if overall_coverage >= min_confidence else [f"Overall validation coverage ({overall_coverage:.2f}) below threshold ({min_confidence})"],
                    warnings=[f"Some properties could not be validated against Wikidata"] if property_coverage < 1.0 else []
                )

            else:
                # Validate all entities and relationships
                entity_validations = {}
                relationship_validations = {}

                valid_entities = 0
                for entity in entities:
                    if not hasattr(entity, "name") or not entity.name:
                        continue

                    # Skip entities with confidence below threshold
                    if hasattr(entity, "confidence") and entity.confidence < min_confidence:
                        continue

                    entity_result = self.validate_entity(
                        entity.name,
                        entity.entity_type if hasattr(entity, "entity_type") else None,
                        entity.properties if hasattr(entity, "properties") else None
                    )

                    entity_validations[entity.entity_id if hasattr(entity, "entity_id") else entity.name] = {
                        "valid": entity_result.is_valid,
                        "name": entity.name,
                        "type": entity.entity_type if hasattr(entity, "entity_type") else "entity",
                        "wikidata_entity": entity_result.data.get("wikidata_entity") if entity_result.is_valid else None
                    }

                    if entity_result.is_valid:
                        valid_entities += 1

                entity_coverage = valid_entities / len(entities) if entities else 0.0

                # Validate relationships if validation depth > 1
                valid_relationships = 0
                if validation_depth > 1 and relationships:
                    for rel in relationships:
                        # Skip relationships with confidence below threshold
                        if hasattr(rel, "confidence") and rel.confidence < min_confidence:
                            continue

                        # Get source and target entities
                        source = rel.source_entity.name if hasattr(rel, "source_entity") and hasattr(rel.source_entity, "name") else None
                        target = rel.target_entity.name if hasattr(rel, "target_entity") and hasattr(rel.target_entity, "name") else None

                        if not source or not target:
                            continue

                        rel_result = self.validate_relationship(
                            source,
                            rel.relationship_type if hasattr(rel, "relationship_type") else "related_to",
                            target,
                            rel.bidirectional if hasattr(rel, "bidirectional") else False
                        )

                        relationship_validations[rel.relationship_id if hasattr(rel, "relationship_id") else f"{source}_{target}"] = {
                            "valid": rel_result.is_valid,
                            "source": source,
                            "target": target,
                            "relationship_type": rel.relationship_type if hasattr(rel, "relationship_type") else "related_to",
                            "wikidata_match": rel_result.data.get("wikidata_relationship", {}).get("property") if rel_result.is_valid else None
                        }

                        if rel_result.is_valid:
                            valid_relationships += 1

                    relationship_coverage = valid_relationships / len(relationships) if relationships else 0.0
                else:
                    relationship_coverage = 0.0

                # Calculate overall coverage
                overall_coverage = (entity_coverage + relationship_coverage) / 2 if validation_depth > 1 else entity_coverage

                # Create validation result
                result = ValidationResult(
                    is_valid=overall_coverage >= min_confidence,
                    data={
                        "entity_validations": entity_validations,
                        "entity_coverage": entity_coverage,
                        "relationship_validations": relationship_validations,
                        "relationship_coverage": relationship_coverage,
                        "overall_coverage": overall_coverage
                    },
                    errors=[] if overall_coverage >= min_confidence else [f"Overall validation coverage ({overall_coverage:.2f}) below threshold ({min_confidence})"],
                    warnings=[f"Some entities could not be validated against Wikidata"] if entity_coverage < 1.0 else []
                )

            # Update trace if tracer is available
            if self.tracer and trace_id:
                self.tracer.update_validation_trace(
                    trace_id=trace_id,
                    status="completed" if result.is_valid else "partial",
                    validation_results=result.to_dict(),
                    coverage=result.data.get("overall_coverage", 0.0)
                )

            return result

        except Exception as e:
            error_result = ValidationResult(
                is_valid=False,
                errors=[f"Knowledge graph validation error: {str(e)}"]
            )

            # Update trace with error if tracer is available
            if self.tracer and trace_id:
                self.tracer.update_validation_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=str(e),
                    validation_results=error_result.to_dict()
                )

            return error_result

    def generate_validation_explanation(
        self,
        validation_result: ValidationResult,
        explanation_type: str = "summary"  # "summary", "detailed", or "fix"
    ) -> str:
        """
        Generate a human-readable explanation of a validation result.

        Args:
            validation_result: Validation result to explain
            explanation_type: Type of explanation to generate

        Returns:
            str: Human-readable explanation
        """
        if not validation_result.is_valid and explanation_type == "fix":
            # Generate suggestions for fixing validation issues
            if "entity_name" in validation_result.data:
                # Single entity validation
                entity_name = validation_result.data["entity_name"]
                property_validations = validation_result.data.get("property_validations", {})
                invalid_properties = {k: v for k, v in property_validations.items() if not v.get("valid")}

                prompt = f"""
                I need to fix validation issues for the entity "{entity_name}" against Wikidata.
                The following properties failed validation:

                {json.dumps(invalid_properties, indent=2)}

                Please suggest specific fixes for each property, including:
                1. Whether the property should be renamed to match Wikidata's terminology
                2. Whether the property value should be adjusted
                3. Whether the property should be removed because it's incorrect

                Format your response as a JSON object with property names as keys and fix suggestions as values.
                """

                response = self.llm.generate(prompt)
                return f"### Validation Fix Suggestions for {entity_name}\n\n{response['text']}"

            else:
                # Multi-entity validation
                entity_validations = validation_result.data.get("entity_validations", {})
                invalid_entities = {k: v for k, v in entity_validations.items() if not v.get("valid")}

                prompt = f"""
                I need to fix validation issues for multiple entities against Wikidata.
                The following entities failed validation:

                {json.dumps(invalid_entities, indent=2)}

                Please suggest specific fixes for each entity, including:
                1. Whether the entity name should be adjusted to match Wikidata's terminology
                2. Whether the entity type should be changed
                3. Alternative Wikidata entities that might be a better match

                Format your response as a JSON object with entity names as keys and fix suggestions as values.
                """

                response = self.llm.generate(prompt)
                return f"### Knowledge Graph Validation Fix Suggestions\n\n{response['text']}"

        elif explanation_type == "detailed":
            # Generate detailed explanation
            if "entity_name" in validation_result.data:
                # Single entity validation
                entity_name = validation_result.data["entity_name"]
                wikidata_entity = validation_result.data.get("wikidata_entity", {})
                property_validations = validation_result.data.get("property_validations", {})
                property_coverage = validation_result.data.get("property_coverage", 0.0)
                relationship_validations = validation_result.data.get("relationship_validations", {})
                relationship_coverage = validation_result.data.get("relationship_coverage", 0.0)
                overall_coverage = validation_result.data.get("overall_coverage", 0.0)

                explanation = f"## Detailed Validation Report for '{entity_name}'\n\n"
                explanation += f"- Wikidata match: {wikidata_entity.get('label', 'Unknown')}\n"
                explanation += f"- Wikidata ID: {wikidata_entity.get('id', 'Unknown')}\n"
                explanation += f"- Property coverage: {property_coverage:.2f}\n"
                explanation += f"- Relationship coverage: {relationship_coverage:.2f}\n"
                explanation += f"- Overall coverage: {overall_coverage:.2f}\n\n"

                explanation += "### Property Validations\n\n"
                for prop_name, validation in property_validations.items():
                    status = "✅" if validation.get("valid") else "❌"
                    explanation += f"- {status} {prop_name}: "
                    if validation.get("valid"):
                        explanation += f"Matches Wikidata property '{validation.get('wikidata_match')}' with confidence {validation.get('confidence', 0.0):.2f}\n"
                    else:
                        explanation += f"No match found in Wikidata.\n"

                if relationship_validations:
                    explanation += "\n### Relationship Validations\n\n"
                    for rel_id, validation in relationship_validations.items():
                        status = "✅" if validation.get("valid") else "❌"
                        explanation += f"- {status} {validation.get('source')} {validation.get('relationship_type')} {validation.get('target')}: "
                        if validation.get("valid"):
                            explanation += f"Matches Wikidata relationship '{validation.get('wikidata_match')}'\n"
                        else:
                            explanation += f"No match found in Wikidata.\n"

                return explanation

            else:
                # Multi-entity validation
                entity_validations = validation_result.data.get("entity_validations", {})
                entity_coverage = validation_result.data.get("entity_coverage", 0.0)
                relationship_validations = validation_result.data.get("relationship_validations", {})
                relationship_coverage = validation_result.data.get("relationship_coverage", 0.0)
                overall_coverage = validation_result.data.get("overall_coverage", 0.0)

                explanation = f"## Detailed Knowledge Graph Validation Report\n\n"
                explanation += f"- Entity coverage: {entity_coverage:.2f}\n"
                explanation += f"- Relationship coverage: {relationship_coverage:.2f}\n"
                explanation += f"- Overall coverage: {overall_coverage:.2f}\n\n"

                explanation += "### Entity Validations\n\n"
                for entity_id, validation in entity_validations.items():
                    status = "✅" if validation.get("valid") else "❌"
                    explanation += f"- {status} {validation.get('name')} ({validation.get('type')}): "
                    if validation.get("valid"):
                        wikidata_entity = validation.get("wikidata_entity", {})
                        explanation += f"Matches Wikidata entity '{wikidata_entity.get('label')}' ({wikidata_entity.get('id')})\n"
                    else:
                        explanation += f"No match found in Wikidata.\n"

                if relationship_validations:
                    explanation += "\n### Relationship Validations\n\n"
                    for rel_id, validation in relationship_validations.items():
                        status = "✅" if validation.get("valid") else "❌"
                        explanation += f"- {status} {validation.get('source')} {validation.get('relationship_type')} {validation.get('target')}: "
                        if validation.get("valid"):
                            explanation += f"Matches Wikidata relationship '{validation.get('wikidata_match')}'\n"
                        else:
                            explanation += f"No match found in Wikidata.\n"

                return explanation

        else:  # summary explanation
            # Generate summary explanation
            if "entity_name" in validation_result.data:
                # Single entity validation
                entity_name = validation_result.data["entity_name"]
                wikidata_entity = validation_result.data.get("wikidata_entity", {})
                property_coverage = validation_result.data.get("property_coverage", 0.0)
                relationship_coverage = validation_result.data.get("relationship_coverage", 0.0)
                overall_coverage = validation_result.data.get("overall_coverage", 0.0)

                if validation_result.is_valid:
                    return f"Entity '{entity_name}' successfully validated against Wikidata entity '{wikidata_entity.get('label')}' ({wikidata_entity.get('id')}). Overall coverage: {overall_coverage:.2f}."
                else:
                    return f"Entity '{entity_name}' validation failed. Match found in Wikidata as '{wikidata_entity.get('label', 'Unknown')}', but coverage ({overall_coverage:.2f}) is below threshold."

            else:
                # Multi-entity validation
                entity_coverage = validation_result.data.get("entity_coverage", 0.0)
                relationship_coverage = validation_result.data.get("relationship_coverage", 0.0)
                overall_coverage = validation_result.data.get("overall_coverage", 0.0)

                if validation_result.is_valid:
                    return f"Knowledge graph successfully validated against Wikidata. Overall coverage: {overall_coverage:.2f}."
                else:
                    return f"Knowledge graph validation failed. Coverage ({overall_coverage:.2f}) is below threshold."

    def _get_wikidata_entity(
        self,
        entity_name: str,
        entity_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get Wikidata entity by name and optional type.

        Args:
            entity_name: Name of the entity
            entity_type: Optional type of the entity for better matching

        Returns:
            Dict or None: Wikidata entity data
        """
        # Create cache key
        cache_key = f"wikidata_entity_{entity_name}_{entity_type}"

        # Check cache
        if self.cache_results and cache_key in self.cache:
            cache_entry = self.cache[cache_key]
            if time.time() - cache_entry["timestamp"] < self.cache_ttl:
                return cache_entry["result"]

        try:
            # Query Wikidata API
            url = "https://www.wikidata.org/w/api.php"
            params = {
                "action": "wbsearchentities",
                "format": "json",
                "search": entity_name,
                "language": "en"
            }

            response = requests.get(url, params=params, headers=self.headers)
            data = response.json()

            # Process results
            if "search" in data and data["search"]:
                # If entity type is provided, try to find a matching entity
                if entity_type:
                    # Convert entity type to potential Wikidata instance types
                    type_map = {
                        "person": ["human", "person"],
                        "organization": ["organization", "company", "corporation"],
                        "location": ["location", "place", "geographic"],
                        "event": ["event"],
                        "work": ["creative work", "book", "film", "music"],
                        "product": ["product", "software"],
                        "concept": ["concept", "idea", "abstract"],
                        "field": ["field", "discipline", "area"],
                        "model": ["model", "algorithm"],
                        "technology": ["technology"]
                    }

                    # Try to match entity type
                    for entity in data["search"]:
                        # If description contains type keyword, prioritize this match
                        if "description" in entity:
                            entity_desc = entity["description"].lower()
                            type_keywords = type_map.get(entity_type.lower(), [entity_type.lower()])

                            for keyword in type_keywords:
                                if keyword in entity_desc:
                                    result = {
                                        "id": entity["id"],
                                        "label": entity["label"],
                                        "description": entity.get("description", ""),
                                        "url": f"https://www.wikidata.org/wiki/{entity['id']}"
                                    }

                                    # Cache result
                                    if self.cache_results:
                                        self.cache[cache_key] = {
                                            "result": result,
                                            "timestamp": time.time()
                                        }

                                    return result

                # If no type match or no type provided, return first result
                entity = data["search"][0]
                result = {
                    "id": entity["id"],
                    "label": entity["label"],
                    "description": entity.get("description", ""),
                    "url": f"https://www.wikidata.org/wiki/{entity['id']}"
                }

                # Cache result
                if self.cache_results:
                    self.cache[cache_key] = {
                        "result": result,
                        "timestamp": time.time()
                    }

                return result

            # No results
            if self.cache_results:
                self.cache[cache_key] = {
                    "result": None,
                    "timestamp": time.time()
                }

            return None

        except Exception as e:
            logging.error(f"Error getting Wikidata entity: {e}")
            return None

    def _get_entity_properties(self, entity_id: str) -> List[Dict[str, Any]]:
        """
        Get properties of a Wikidata entity.

        Args:
            entity_id: Wikidata entity ID (Qxxxxx)

        Returns:
            List[Dict]: List of entity properties
        """
        # Create cache key
        cache_key = f"wikidata_props_{entity_id}"

        # Check cache
        if self.cache_results and cache_key in self.cache:
            cache_entry = self.cache[cache_key]
            if time.time() - cache_entry["timestamp"] < self.cache_ttl:
                return cache_entry["result"]

        try:
            # Query Wikidata SPARQL endpoint
            query = f"""
            SELECT ?property ?propertyLabel ?value ?valueLabel
            WHERE {{
              wd:{entity_id} ?p ?value .
              ?property wikibase:directClaim ?p .
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
            }}
            """

            response = requests.get(
                self.endpoint_url,
                params={"query": query, "format": "json"},
                headers=self.headers
            )

            data = response.json()

            # Process results
            properties = []
            for binding in data.get("results", {}).get("bindings", []):
                prop = {
                    "property": binding.get("propertyLabel", {}).get("value", ""),
                    "property_id": binding.get("property", {}).get("value", "").split("/")[-1],
                    "value": binding.get("valueLabel", {}).get("value", ""),
                    "value_uri": binding.get("value", {}).get("value", "")
                }
                properties.append(prop)

            # Cache result
            if self.cache_results:
                self.cache[cache_key] = {
                    "result": properties,
                    "timestamp": time.time()
                }

            return properties

        except Exception as e:
            logging.error(f"Error getting entity properties: {e}")
            return []

    def _match_property(
        self,
        prop_name: str,
        prop_value: Any,
        wikidata_props: List[Dict[str, Any]]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Match a property against Wikidata properties.

        Args:
            prop_name: Property name to match
            prop_value: Property value to match
            wikidata_props: List of Wikidata properties

        Returns:
            Tuple[bool, Dict]: (matched, closest_match)
        """
        best_match = None
        best_score = 0.0

        # Convert property value to string for comparison
        prop_value_str = str(prop_value)

        for wiki_prop in wikidata_props:
            # Calculate name similarity
            name_similarity = self._string_similarity(prop_name.lower(), wiki_prop["property"].lower())

            # Calculate value similarity
            value_similarity = self._string_similarity(prop_value_str.lower(), wiki_prop["value"].lower())

            # Calculate combined score
            score = (name_similarity * 0.6) + (value_similarity * 0.4)

            if score > best_score and score >= 0.7:  # Threshold for considering a match
                best_score = score
                best_match = {
                    "property": wiki_prop["property"],
                    "property_id": wiki_prop["property_id"],
                    "value": wiki_prop["value"],
                    "confidence": score
                }

        # If no good match, return closest property by name
        if best_match is None:
            best_name_match = None
            best_name_score = 0.0

            for wiki_prop in wikidata_props:
                name_similarity = self._string_similarity(prop_name.lower(), wiki_prop["property"].lower())

                if name_similarity > best_name_score:
                    best_name_score = name_similarity
                    best_name_match = {
                        "property": wiki_prop["property"],
                        "property_id": wiki_prop["property_id"],
                        "value": wiki_prop["value"],
                        "confidence": name_similarity * 0.5  # Lower confidence for name-only match
                    }

            return False, best_name_match

        return True, best_match

    def _check_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        bidirectional: bool = False
    ) -> Dict[str, Any]:
        """
        Check if a relationship exists between entities in Wikidata.

        Args:
            source_id: Wikidata ID of source entity
            target_id: Wikidata ID of target entity
            relationship_type: Type of relationship to check
            bidirectional: Whether to check in both directions

        Returns:
            Dict: Information about the relationship
        """
        # Create cache key
        cache_key = f"wikidata_rel_{source_id}_{target_id}_{relationship_type}_{bidirectional}"

        # Check cache
        if self.cache_results and cache_key in self.cache:
            cache_entry = self.cache[cache_key]
            if time.time() - cache_entry["timestamp"] < self.cache_ttl:
                return cache_entry["result"]

        try:
            # Query Wikidata SPARQL endpoint for direct relationships
            forward_query = f"""
            SELECT ?property ?propertyLabel
            WHERE {{
              wd:{source_id} ?p wd:{target_id} .
              ?property wikibase:directClaim ?p .
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
            }}
            """

            response = requests.get(
                self.endpoint_url,
                params={"query": forward_query, "format": "json"},
                headers=self.headers
            )

            data = response.json()
            forward_results = data.get("results", {}).get("bindings", [])

            # Check reverse direction if bidirectional
            reverse_results = []
            if bidirectional:
                reverse_query = f"""
                SELECT ?property ?propertyLabel
                WHERE {{
                  wd:{target_id} ?p wd:{source_id} .
                  ?property wikibase:directClaim ?p .
                  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
                }}
                """

                response = requests.get(
                    self.endpoint_url,
                    params={"query": reverse_query, "format": "json"},
                    headers=self.headers
                )

                data = response.json()
                reverse_results = data.get("results", {}).get("bindings", [])

            # Combine results
            all_relationships = []
            for binding in forward_results:
                all_relationships.append({
                    "property": binding.get("propertyLabel", {}).get("value", ""),
                    "property_id": binding.get("property", {}).get("value", "").split("/")[-1],
                    "direction": "forward"
                })

            for binding in reverse_results:
                all_relationships.append({
                    "property": binding.get("propertyLabel", {}).get("value", ""),
                    "property_id": binding.get("property", {}).get("value", "").split("/")[-1],
                    "direction": "reverse"
                })

            # Check if any relationship matches the provided type
            best_match = None
            best_score = 0.0

            for rel in all_relationships:
                similarity = self._string_similarity(relationship_type.lower(), rel["property"].lower())

                if similarity > best_score:
                    best_score = similarity
                    best_match = rel

            # Determine if relationship exists
            if best_match and best_score >= 0.7:  # Threshold for considering a match
                result = {
                    "exists": True,
                    "relationship": best_match,
                    "confidence": best_score
                }
            else:
                result = {
                    "exists": False,
                    "closest_match": best_match,
                    "confidence": best_score if best_match else 0.0
                }

            # Cache result
            if self.cache_results:
                self.cache[cache_key] = {
                    "result": result,
                    "timestamp": time.time()
                }

            return result

        except Exception as e:
            logging.error(f"Error checking relationship: {e}")
            return {
                "exists": False,
                "error": str(e)
            }

    def _string_similarity(self, str1: str, str2: str) -> float:
        """
        Calculate string similarity using Jaccard similarity of words.

        Args:
            str1: First string
            str2: Second string

        Returns:
            float: Similarity score (0-1)
        """
        # Edge cases
        if not str1 and not str2:
            return 1.0
        if not str1 or not str2:
            return 0.0

        # Create sets of words
        words1 = set(str1.lower().split())
        words2 = set(str2.lower().split())

        # Calculate Jaccard similarity
        intersection = words1.intersection(words2)
        union = words1.union(words2)

        return len(intersection) / len(union)

    def find_entity_paths(
        self,
        source_entity: str,
        target_entity: str,
        max_path_length: int = 2
    ) -> ValidationResult:
        """
        Find paths between two entities in Wikidata.

        Args:
            source_entity: Source entity name
            target_entity: Target entity name
            max_path_length: Maximum path length (1 or 2)

        Returns:
            ValidationResult: Result of the path finding
        """
        # Check if results are cached
        cache_key = f"paths_{source_entity}_{target_entity}_{max_path_length}"
        if self.cache_results and cache_key in self.cache:
            cache_entry = self.cache[cache_key]
            if time.time() - cache_entry["timestamp"] < self.cache_ttl:
                return cache_entry["result"]

        try:
            # Get Wikidata IDs for source and target entities
            source_wikidata = self._get_wikidata_entity(source_entity)
            target_wikidata = self._get_wikidata_entity(target_entity)

            if not source_wikidata or not target_wikidata:
                missing_entities = []
                if not source_wikidata:
                    missing_entities.append(source_entity)
                if not target_wikidata:
                    missing_entities.append(target_entity)

                result = ValidationResult(
                    is_valid=False,
                    errors=[f"Entities not found in Wikidata: {', '.join(missing_entities)}"],
                    warnings=["Path finding cannot proceed without entity lookup"]
                )

                if self.cache_results:
                    self.cache[cache_key] = {
                        "result": result,
                        "timestamp": time.time()
                    }
                return result

            # Build and execute query to find paths
            query = build_path_relationship_query(source_wikidata["id"], target_wikidata["id"])

            response = requests.get(
                self.endpoint_url,
                params={"query": query, "format": "json"},
                headers=self.headers
            )

            data = response.json()
            bindings = data.get("results", {}).get("bindings", [])

            # Process query results
            direct_paths = []
            two_hop_paths = []

            for binding in bindings:
                if "p2" not in binding:
                    # Direct path
                    direct_paths.append({
                        "property": binding.get("p1Label", {}).get("value", "unknown relation"),
                        "property_id": binding.get("p1", {}).get("value", "").split("/")[-1] if "p1" in binding else None,
                        "direction": "forward"
                    })
                else:
                    # Two-hop path
                    two_hop_paths.append({
                        "intermediate": binding.get("intermediateLabel", {}).get("value", "unknown entity"),
                        "intermediate_id": binding.get("intermediate", {}).get("value", "").split("/")[-1] if "intermediate" in binding else None,
                        "first_property": binding.get("p1Label", {}).get("value", "unknown relation"),
                        "first_property_id": binding.get("p1", {}).get("value", "").split("/")[-1] if "p1" in binding else None,
                        "second_property": binding.get("p2Label", {}).get("value", "unknown relation"),
                        "second_property_id": binding.get("p2", {}).get("value", "").split("/")[-1] if "p2" in binding else None
                    })

            # Create validation result
            result = ValidationResult(
                is_valid=len(direct_paths) > 0 or len(two_hop_paths) > 0,
                data={
                    "source": source_entity,
                    "source_id": source_wikidata["id"],
                    "target": target_entity,
                    "target_id": target_wikidata["id"],
                    "direct_paths": direct_paths,
                    "two_hop_paths": two_hop_paths
                },
                errors=[] if len(direct_paths) > 0 or len(two_hop_paths) > 0 else [f"No paths found between '{source_entity}' and '{target_entity}'"],
                warnings=[] if direct_paths else ["No direct paths found, but indirect paths exist"] if two_hop_paths else []
            )

            # Cache the result if enabled
            if self.cache_results:
                self.cache[cache_key] = {
                    "result": result,
                    "timestamp": time.time()
                }

            return result

        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"Error finding paths between entities: {str(e)}"]
            )

    def find_similar_entities(
        self,
        entity_name: str,
        entity_type: Optional[str] = None,
        min_similarity: float = 0.5
    ) -> ValidationResult:
        """
        Find similar entities to a given entity in Wikidata.

        Args:
            entity_name: Name of the entity to find similar entities for
            entity_type: Optional type of entities to search for
            min_similarity: Minimum similarity score (0.0-1.0)

        Returns:
            ValidationResult: Result with similar entities
        """
        # Check if results are cached
        cache_key = f"similar_{entity_name}_{entity_type}_{min_similarity}"
        if self.cache_results and cache_key in self.cache:
            cache_entry = self.cache[cache_key]
            if time.time() - cache_entry["timestamp"] < self.cache_ttl:
                return cache_entry["result"]

        try:
            # Get Wikidata entity
            wikidata_entity = self._get_wikidata_entity(entity_name, entity_type)

            if not wikidata_entity:
                result = ValidationResult(
                    is_valid=False,
                    errors=[f"Entity '{entity_name}' not found in Wikidata"],
                    warnings=["Cannot find similar entities without entity lookup"]
                )

                if self.cache_results:
                    self.cache[cache_key] = {
                        "result": result,
                        "timestamp": time.time()
                    }
                return result

            # Get entity type ID if needed but not provided
            type_id = None
            if entity_type:
                # Try to map entity type to Wikidata type ID
                type_map = {
                    "person": "Q5",           # human
                    "organization": "Q43229",  # organization
                    "company": "Q783794",      # company
                    "location": "Q82794",      # geographic location
                    "place": "Q82794",         # geographic location
                    "country": "Q6256",        # country
                    "city": "Q515",            # city
                    "event": "Q1190554",       # event
                    "technology": "Q11016",    # technology
                    "software": "Q7397",       # software
                    "book": "Q571",            # book
                    "film": "Q11424",          # film
                    "concept": "Q151885",      # concept
                    "scientific_concept": "Q2023214"  # scientific concept
                }
                type_id = type_map.get(entity_type.lower())

                # If type not found in map, search for it
                if not type_id:
                    try:
                        # Simple search for the type
                        type_search_query = build_entity_query(entity_type)
                        response = requests.get(
                            self.endpoint_url,
                            params={"query": type_search_query, "format": "json"},
                            headers=self.headers
                        )
                        data = response.json()
                        bindings = data.get("results", {}).get("bindings", [])

                        if bindings:
                            first_match = bindings[0]
                            type_id = first_match.get("item", {}).get("value", "").split("/")[-1]
                    except Exception:
                        # If search fails, continue without type filter
                        pass

            # Build and execute query to find similar entities
            query = build_similar_entities_query(wikidata_entity["id"], type_id)

            response = requests.get(
                self.endpoint_url,
                params={"query": query, "format": "json"},
                headers=self.headers
            )

            data = response.json()
            bindings = data.get("results", {}).get("bindings", [])

            # Process query results
            similar_entities = []

            for binding in bindings:
                similarity_score = float(binding.get("score", {}).get("value", "0"))

                # Only include entities with similarity above threshold
                if similarity_score >= min_similarity:
                    similar_entities.append({
                        "entity": binding.get("itemLabel", {}).get("value", "unknown entity"),
                        "entity_id": binding.get("item", {}).get("value", "").split("/")[-1],
                        "similarity": similarity_score
                    })

            # Create validation result
            result = ValidationResult(
                is_valid=len(similar_entities) > 0,
                data={
                    "entity": entity_name,
                    "entity_id": wikidata_entity["id"],
                    "similar_entities": similar_entities
                },
                errors=[] if similar_entities else [f"No similar entities found for '{entity_name}' with similarity >= {min_similarity}"],
                warnings=[] if len(similar_entities) >= 3 else ["Only a few similar entities found"]
            )

            # Cache the result if enabled
            if self.cache_results:
                self.cache[cache_key] = {
                    "result": result,
                    "timestamp": time.time()
                }

            return result

        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"Error finding similar entities: {str(e)}"]
            )

    def validate_common_properties(
        self,
        entity_name: str,
        entity_type: str,
        entity_properties: Dict[str, Any]
    ) -> ValidationResult:
        """
        Validate that an entity has the common properties expected for its type.

        Args:
            entity_name: Name of the entity
            entity_type: Type of the entity
            entity_properties: Properties of the entity

        Returns:
            ValidationResult: Result of the validation
        """
        # Check if results are cached
        cache_key = f"common_props_{entity_name}_{entity_type}"
        if self.cache_results and cache_key in self.cache:
            cache_entry = self.cache[cache_key]
            if time.time() - cache_entry["timestamp"] < self.cache_ttl:
                return cache_entry["result"]

        try:
            # Get Wikidata entity
            wikidata_entity = self._get_wikidata_entity(entity_name, entity_type)

            if not wikidata_entity:
                result = ValidationResult(
                    is_valid=False,
                    errors=[f"Entity '{entity_name}' not found in Wikidata"],
                    warnings=["Cannot validate common properties without entity lookup"]
                )

                if self.cache_results:
                    self.cache[cache_key] = {
                        "result": result,
                        "timestamp": time.time()
                    }
                return result

            # Get entity type ID
            type_map = {
                "person": "Q5",           # human
                "organization": "Q43229",  # organization
                "company": "Q783794",      # company
                "location": "Q82794",      # geographic location
                "place": "Q82794",         # geographic location
                "country": "Q6256",        # country
                "city": "Q515",            # city
                "event": "Q1190554",       # event
                "technology": "Q11016",    # technology
                "software": "Q7397",       # software
                "book": "Q571",            # book
                "film": "Q11424",          # film
                "concept": "Q151885",      # concept
                "scientific_concept": "Q2023214"  # scientific concept
            }

            type_id = type_map.get(entity_type.lower())

            if not type_id:
                # If type not in map, try to get types of the entity itself
                entity_type_query = build_entity_type_query(wikidata_entity["id"])

                response = requests.get(
                    self.endpoint_url,
                    params={"query": entity_type_query, "format": "json"},
                    headers=self.headers
                )

                data = response.json()
                type_bindings = data.get("results", {}).get("bindings", [])

                if type_bindings:
                    type_id = type_bindings[0].get("type", {}).get("value", "").split("/")[-1]
                else:
                    result = ValidationResult(
                        is_valid=False,
                        errors=[f"Cannot determine Wikidata type for entity type '{entity_type}'"],
                        warnings=["Cannot validate common properties without a valid entity type"]
                    )

                    if self.cache_results:
                        self.cache[cache_key] = {
                            "result": result,
                            "timestamp": time.time()
                        }
                    return result

            # Get property statistics for this entity type
            property_stats_query = build_property_stats_query(type_id)

            response = requests.get(
                self.endpoint_url,
                params={"query": property_stats_query, "format": "json"},
                headers=self.headers
            )

            data = response.json()
            stats_bindings = data.get("results", {}).get("bindings", [])

            # Get common properties and their usage percentages
            common_properties = []
            for binding in stats_bindings:
                property_name = binding.get("propertyLabel", {}).get("value", "")
                usage_percentage = float(binding.get("percentage", {}).get("value", "0"))

                if usage_percentage >= 30:  # Consider properties used by at least 30% of entities
                    common_properties.append({
                        "property": property_name,
                        "percentage": usage_percentage
                    })

            # Check which common properties the entity has
            missing_properties = []
            found_properties = []

            for common_prop in common_properties:
                property_name = common_prop["property"]
                usage_percentage = common_prop["percentage"]

                # Try to find a matching property in the entity properties
                property_found = False
                for entity_prop_name, entity_prop_value in entity_properties.items():
                    if self._string_similarity(property_name.lower(), entity_prop_name.lower()) >= 0.7:
                        property_found = True
                        found_properties.append({
                            "property": property_name,
                            "entity_property": entity_prop_name,
                            "percentage": usage_percentage
                        })
                        break

                if not property_found:
                    missing_properties.append({
                        "property": property_name,
                        "percentage": usage_percentage
                    })

            # Calculate coverage
            coverage = len(found_properties) / len(common_properties) if common_properties else 1.0

            # Create validation result
            result = ValidationResult(
                is_valid=coverage >= 0.7,  # Consider valid if at least 70% of common properties are present
                data={
                    "entity": entity_name,
                    "entity_id": wikidata_entity["id"],
                    "entity_type": entity_type,
                    "type_id": type_id,
                    "common_properties": common_properties,
                    "found_properties": found_properties,
                    "missing_properties": missing_properties,
                    "coverage": coverage
                },
                errors=[] if coverage >= 0.7 else [f"Missing {len(missing_properties)} common properties for entity type '{entity_type}'"],
                warnings=[f"Entity is missing some common properties: {', '.join(p['property'] for p in missing_properties[:3])}{'...' if len(missing_properties) > 3 else ''}"] if missing_properties else []
            )

            # Cache the result if enabled
            if self.cache_results:
                self.cache[cache_key] = {
                    "result": result,
                    "timestamp": time.time()
                }

            return result

        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"Error validating common properties: {str(e)}"]
            )

    def execute_custom_sparql_query(
        self,
        query: str
    ) -> Dict[str, Any]:
        """
        Execute a custom SPARQL query against the endpoint.

        Args:
            query: Custom SPARQL query to execute

        Returns:
            Dict: Query results
        """
        # Check if results are cached
        cache_key = f"custom_query_{hash(query)}"
        if self.cache_results and cache_key in self.cache:
            cache_entry = self.cache[cache_key]
            if time.time() - cache_entry["timestamp"] < self.cache_ttl:
                return cache_entry["result"]

        try:
            # Execute query
            response = requests.get(
                self.endpoint_url,
                params={"query": query, "format": "json"},
                headers=self.headers
            )

            # Parse response
            result = response.json()

            # Cache the result if enabled
            if self.cache_results:
                self.cache[cache_key] = {
                    "result": result,
                    "timestamp": time.time()
                }

            return result

        except Exception as e:
            logging.error(f"Error executing custom SPARQL query: {e}")
            return {"error": str(e)}
