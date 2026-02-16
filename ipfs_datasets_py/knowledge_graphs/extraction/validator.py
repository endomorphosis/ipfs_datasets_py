"""
Knowledge Graph Extractor with Validation Module

This module provides the KnowledgeGraphExtractorWithValidation class for 
extracting and validating structured knowledge graphs from unstructured text.
It extends the base extractor with automated validation against external 
knowledge bases like Wikidata through SPARQL queries.

Key Features:
- Automated validation during extraction
- Entity property validation against Wikidata
- Relationship validation against Wikidata
- Suggestions for correcting invalid entities and relationships
- Confidence scoring based on validation results
- Detailed validation reports
- Integrated with WikipediaKnowledgeGraphTracer for tracing
"""

from typing import Dict, List, Any, Optional

# Import extraction package components
from .extractor import KnowledgeGraphExtractor
from .graph import KnowledgeGraph

# Import the Wikipedia knowledge graph tracer for enhanced tracing capabilities
from ipfs_datasets_py.ml.llm.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer




class KnowledgeGraphExtractorWithValidation:
    """
    Enhanced knowledge graph extractor with integrated validation.

    This class extends the knowledge graph extraction functionality with automated
    validation against external knowledge bases like Wikidata through SPARQL queries.
    It provides a unified interface for extracting and validating knowledge graphs,
    with options for automatic correction suggestions and continuous improvement.

    Key Features:
    - Automated validation during extraction
    - Entity property validation against Wikidata
    - Relationship validation against Wikidata
    - Suggestions for correcting invalid entities and relationships
    - Confidence scoring based on validation results
    - Detailed validation reports
    - Integrated with WikipediaKnowledgeGraphTracer for tracing
    """

    def __init__(
        self,
        use_spacy: bool = False,
        use_transformers: bool = False,
        relation_patterns: Optional[List[Dict[str, Any]]] = None,
        min_confidence: float = 0.5,
        use_tracer: bool = True,
        sparql_endpoint_url: str = "https://query.wikidata.org/sparql",
        validate_during_extraction: bool = True,
        auto_correct_suggestions: bool = False,
        cache_validation_results: bool = True
    ):
        """
        Initialize the knowledge graph extractor with validation.

        Args:
            use_spacy: Whether to use spaCy for extraction
            use_transformers: Whether to use Transformers for extraction
            relation_patterns: Custom relation extraction patterns
            min_confidence: Minimum confidence threshold for extraction
            use_tracer: Whether to use the WikipediaKnowledgeGraphTracer
            sparql_endpoint_url: URL of the SPARQL endpoint for validation
            validate_during_extraction: Whether to validate during extraction
            auto_correct_suggestions: Whether to generate correction suggestions
            cache_validation_results: Whether to cache validation results
        """
        # Initialize the base extractor
        self.extractor = KnowledgeGraphExtractor(
            use_spacy=use_spacy,
            use_transformers=use_transformers,
            relation_patterns=relation_patterns,
            min_confidence=min_confidence,
            use_tracer=use_tracer
        )

        # Initialize tracer if enabled
        self.tracer = WikipediaKnowledgeGraphTracer() if use_tracer else None

        # Initialize validator
        try:
            from ipfs_datasets_py.ml.llm.llm_semantic_validation import SPARQLValidator
            self.validator = SPARQLValidator(
                endpoint_url=sparql_endpoint_url,
                tracer=self.tracer,
                cache_results=cache_validation_results
            )
            self.validator_available = True
        except ImportError:
            print("Warning: SPARQLValidator not available. Validation will be disabled.")
            self.validator = None
            self.validator_available = False

        # Configuration options
        self.validate_during_extraction = validate_during_extraction and self.validator_available
        self.auto_correct_suggestions = auto_correct_suggestions
        self.min_confidence = min_confidence

    def extract_knowledge_graph(
        self,
        text: str,
        extraction_temperature: float = 0.7,
        structure_temperature: float = 0.5,
        validation_depth: int = 1
    ) -> Dict[str, Any]:
        """
        Extract and validate a knowledge graph from text.

        Args:
            text: Text to extract knowledge graph from
            extraction_temperature: Controls level of detail (0.0-1.0)
            structure_temperature: Controls structural complexity (0.0-1.0)
            validation_depth: Depth of validation (1=entities, 2=relationships)

        Returns:
            Dict containing:
                - knowledge_graph: The extracted knowledge graph
                - validation_results: Validation results if enabled
                - validation_metrics: Validation metrics if enabled
                - corrections: Correction suggestions if enabled
        """
        # Create trace if tracer is enabled
        trace_id = None
        if self.tracer:
            trace_id = self.tracer.trace_extraction_and_validation(
                page_title="Custom Text",
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

        try:
            # Extract knowledge graph
            kg = self.extractor.extract_enhanced_knowledge_graph(
                text=text,
                use_chunking=True,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

            result = {
                "knowledge_graph": kg,
                "entity_count": len(kg.entities),
                "relationship_count": len(kg.relationships)
            }

            # Perform validation if enabled
            if self.validate_during_extraction and self.validator:
                validation_result = self.validator.validate_knowledge_graph(
                    kg=kg,
                    validation_depth=validation_depth,
                    min_confidence=self.min_confidence
                )

                result["validation_results"] = validation_result.to_dict()
                result["validation_metrics"] = {
                    "entity_coverage": validation_result.data.get("entity_coverage", 0.0),
                    "relationship_coverage": validation_result.data.get("relationship_coverage", 0.0),
                    "overall_coverage": validation_result.data.get("overall_coverage", 0.0)
                }

                # Generate correction suggestions if enabled
                if self.auto_correct_suggestions:
                    corrections = {}

                    # Entity corrections
                    if "entity_validations" in validation_result.data:
                        entity_corrections = {}
                        for entity_id, validation in validation_result.data["entity_validations"].items():
                            if not validation.get("valid", False):
                                explanation = self.validator.generate_validation_explanation(
                                    validation_result,
                                    explanation_type="fix"
                                )
                                entity_corrections[entity_id] = {
                                    "entity_name": validation.get("name", ""),
                                    "suggestions": explanation
                                }

                        if entity_corrections:
                            corrections["entities"] = entity_corrections

                    # Relationship corrections
                    if "relationship_validations" in validation_result.data:
                        rel_corrections = {}
                        for rel_id, validation in validation_result.data["relationship_validations"].items():
                            if not validation.get("valid", False):
                                rel_corrections[rel_id] = {
                                    "source": validation.get("source", ""),
                                    "relationship_type": validation.get("relationship_type", ""),
                                    "target": validation.get("target", ""),
                                    "suggestions": f"Consider using '{validation.get('wikidata_match', '')}' instead"
                                }

                        if rel_corrections:
                            corrections["relationships"] = rel_corrections

                    if corrections:
                        result["corrections"] = corrections

            # Update trace if enabled
            if self.tracer and trace_id:
                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="completed",
                    knowledge_graph=kg,
                    validation_results=result.get("validation_results", {}),
                    entity_count=len(kg.entities),
                    relationship_count=len(kg.relationships),
                    coverage=result.get("validation_metrics", {}).get("overall_coverage", 0.0)
                )

            return result

        except Exception as e:
            error_result = {
                "error": f"Error extracting and validating knowledge graph: {e}",
                "knowledge_graph": None
            }

            # Update trace with error if tracer is enabled
            if self.tracer and trace_id:
                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=str(e)
                )

            return error_result

    def extract_from_wikipedia(
        self,
        page_title: str,
        extraction_temperature: float = 0.7,
        structure_temperature: float = 0.5,
        validation_depth: int = 2,
        focus_validation_on_main_entity: bool = True
    ) -> Dict[str, Any]:
        """
        Extract and validate a knowledge graph from a Wikipedia page.

        Args:
            page_title: Title of the Wikipedia page
            extraction_temperature: Controls level of detail (0.0-1.0)
            structure_temperature: Controls structural complexity (0.0-1.0)
            validation_depth: Depth of validation (1=entities, 2=relationships)
            focus_validation_on_main_entity: Whether to focus validation on main entity

        Returns:
            Dict containing:
                - knowledge_graph: The extracted knowledge graph
                - validation_results: Validation results
                - validation_metrics: Validation metrics
                - corrections: Correction suggestions if enabled
        """
        # Create trace if tracer is enabled
        trace_id = None
        if self.tracer:
            trace_id = self.tracer.trace_extraction_and_validation(
                page_title=page_title,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

        try:
            # Extract knowledge graph from Wikipedia
            kg = self.extractor.extract_from_wikipedia(
                page_title=page_title,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

            result = {
                "knowledge_graph": kg,
                "entity_count": len(kg.entities),
                "relationship_count": len(kg.relationships)
            }

            # Perform validation if enabled
            if self.validate_during_extraction and self.validator:
                if focus_validation_on_main_entity:
                    # Validate with focus on main entity
                    validation_result = self.validator.validate_knowledge_graph(
                        kg=kg,
                        main_entity_name=page_title,
                        validation_depth=validation_depth,
                        min_confidence=self.min_confidence
                    )
                else:
                    # Validate entire knowledge graph
                    validation_result = self.validator.validate_knowledge_graph(
                        kg=kg,
                        validation_depth=validation_depth,
                        min_confidence=self.min_confidence
                    )

                result["validation_results"] = validation_result.to_dict()

                # Extract validation metrics
                if "entity_name" in validation_result.data:
                    # Single entity focus validation
                    result["validation_metrics"] = {
                        "property_coverage": validation_result.data.get("property_coverage", 0.0),
                        "relationship_coverage": validation_result.data.get("relationship_coverage", 0.0),
                        "overall_coverage": validation_result.data.get("overall_coverage", 0.0)
                    }
                else:
                    # Full knowledge graph validation
                    result["validation_metrics"] = {
                        "entity_coverage": validation_result.data.get("entity_coverage", 0.0),
                        "relationship_coverage": validation_result.data.get("relationship_coverage", 0.0),
                        "overall_coverage": validation_result.data.get("overall_coverage", 0.0)
                    }

                # Generate correction suggestions if enabled
                if self.auto_correct_suggestions:
                    explanation = self.validator.generate_validation_explanation(
                        validation_result,
                        explanation_type="fix"
                    )
                    result["corrections"] = explanation

                # Perform path finding between key entities
                if len(kg.entities) >= 2:
                    # Find main entity
                    main_entities = [e for e in kg.entities.values() if e.name.lower() == page_title.lower()]

                    if main_entities and validation_depth > 1:
                        main_entity = main_entities[0]

                        # Find path to at least one other important entity
                        other_entities = []
                        for entity in kg.entities.values():
                            if entity.entity_id != main_entity.entity_id and hasattr(entity, "confidence") and entity.confidence > 0.8:
                                other_entities.append(entity)

                        if other_entities:
                            # Take the entity with highest confidence
                            other_entity = max(other_entities, key=lambda e: getattr(e, "confidence", 0))

                            # Find paths between entities
                            path_result = self.validator.find_entity_paths(
                                source_entity=main_entity.name,
                                target_entity=other_entity.name,
                                max_path_length=2
                            )

                            if path_result.is_valid:
                                result["path_analysis"] = path_result.to_dict()

            # Update trace if enabled
            if self.tracer and trace_id:
                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="completed",
                    knowledge_graph=kg,
                    validation_results=result.get("validation_results", {}),
                    entity_count=len(kg.entities),
                    relationship_count=len(kg.relationships),
                    coverage=result.get("validation_metrics", {}).get("overall_coverage", 0.0)
                )

            return result

        except Exception as e:
            error_result = {
                "error": f"Error extracting and validating Wikipedia knowledge graph: {e}",
                "knowledge_graph": None
            }

            # Update trace with error if tracer is enabled
            if self.tracer and trace_id:
                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=str(e)
                )

            return error_result

    def extract_from_documents(
        self,
        documents: List[Dict[str, str]],
        text_key: str = "text",
        extraction_temperature: float = 0.7,
        structure_temperature: float = 0.5,
        validation_depth: int = 1
    ) -> Dict[str, Any]:
        """
        Extract and validate a knowledge graph from multiple documents.

        Args:
            documents: List of document dictionaries
            text_key: Key for the text field in the documents
            extraction_temperature: Controls level of detail (0.0-1.0)
            structure_temperature: Controls structural complexity (0.0-1.0)
            validation_depth: Depth of validation (1=entities, 2=relationships)

        Returns:
            Dict containing:
                - knowledge_graph: The extracted knowledge graph
                - validation_results: Validation results if enabled
                - validation_metrics: Validation metrics if enabled
                - corrections: Correction suggestions if enabled
        """
        # Create trace if tracer is enabled
        trace_id = None
        if self.tracer:
            trace_id = self.tracer.trace_extraction_and_validation(
                page_title="Multiple Documents",
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

        try:
            # Extract knowledge graph from documents
            kg = self.extractor.extract_from_documents(
                documents=documents,
                text_key=text_key,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

            # Enrich with inferred types
            kg = self.extractor.enrich_with_types(kg)

            result = {
                "knowledge_graph": kg,
                "entity_count": len(kg.entities),
                "relationship_count": len(kg.relationships)
            }

            # Perform validation if enabled
            if self.validate_during_extraction and self.validator:
                validation_result = self.validator.validate_knowledge_graph(
                    kg=kg,
                    validation_depth=validation_depth,
                    min_confidence=self.min_confidence
                )

                result["validation_results"] = validation_result.to_dict()
                result["validation_metrics"] = {
                    "entity_coverage": validation_result.data.get("entity_coverage", 0.0),
                    "relationship_coverage": validation_result.data.get("relationship_coverage", 0.0),
                    "overall_coverage": validation_result.data.get("overall_coverage", 0.0)
                }

                # Generate correction suggestions if enabled
                if self.auto_correct_suggestions:
                    explanation = self.validator.generate_validation_explanation(
                        validation_result,
                        explanation_type="fix"
                    )
                    result["corrections"] = explanation

                # Additional validation: find entity paths
                if validation_depth > 1:
                    # Select top entities by confidence
                    top_entities = sorted(
                        [e for e in kg.entities.values() if hasattr(e, "confidence") and e.confidence > 0.8],
                        key=lambda e: getattr(e, "confidence", 0),
                        reverse=True
                    )[:5]  # Top 5 entities

                    # Find paths between pairs of top entities
                    path_results = []
                    for i in range(len(top_entities)):
                        for j in range(i + 1, len(top_entities)):
                            entity1 = top_entities[i]
                            entity2 = top_entities[j]

                            path_result = self.validator.find_entity_paths(
                                source_entity=entity1.name,
                                target_entity=entity2.name,
                                max_path_length=2
                            )

                            if path_result.is_valid:
                                path_results.append({
                                    "source": entity1.name,
                                    "target": entity2.name,
                                    "paths": path_result.data
                                })

                    if path_results:
                        result["path_analysis"] = path_results

            # Update trace if enabled
            if self.tracer and trace_id:
                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="completed",
                    knowledge_graph=kg,
                    validation_results=result.get("validation_results", {}),
                    entity_count=len(kg.entities),
                    relationship_count=len(kg.relationships),
                    coverage=result.get("validation_metrics", {}).get("overall_coverage", 0.0)
                )

            return result

        except Exception as e:
            error_result = {
                "error": f"Error extracting and validating multi-document knowledge graph: {e}",
                "knowledge_graph": None
            }

            # Update trace with error if tracer is enabled
            if self.tracer and trace_id:
                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=str(e)
                )

            return error_result

    def apply_validation_corrections(
        self,
        kg: KnowledgeGraph,
        corrections: Dict[str, Any]
    ) -> KnowledgeGraph:
        """
        Apply correction suggestions to a knowledge graph.

        Args:
            kg: Knowledge graph to correct
            corrections: Correction suggestions from validation

        Returns:
            KnowledgeGraph: Corrected knowledge graph
        """
        # Create a copy of the knowledge graph to avoid modifying the original
        corrected_kg = KnowledgeGraph(name=kg.name)

        # Create maps for tracking corrections
        entity_corrections = {}
        relationship_type_corrections = {}

        # Parse entity corrections
        if "entities" in corrections:
            for entity_id, entity_correction in corrections["entities"].items():
                # TODO entity_name is not referenced anywhere. See if we need it.
                entity_name = entity_correction.get("entity_name", "")
                suggestions = entity_correction.get("suggestions", "")

                # Process suggestions to extract corrections
                # # TODO This is simplified - in a real implementation, more sophisticated . SO WE'RE GUNNA MAKE IT MORE SOPHISTICATED DAMNIT!
                # parsing of the suggestion text would be needed
                if isinstance(suggestions, dict):
                    # Structured suggestions
                    entity_corrections[entity_id] = suggestions
                elif isinstance(suggestions, str) and ":" in suggestions:
                    # Simple text parsing
                    correction_map = {}
                    for line in suggestions.split("\n"):
                        if ":" in line:
                            key, value = line.split(":", 1)
                            correction_map[key.strip()] = value.strip()
                    entity_corrections[entity_id] = correction_map

        # Parse relationship corrections
        if "relationships" in corrections:
            for rel_id, rel_correction in corrections["relationships"].items():
                rel_type = rel_correction.get("relationship_type", "")
                suggestions = rel_correction.get("suggestions", "")

                # Extract suggested relationship type
                if "instead" in suggestions and "'" in suggestions:
                    import re
                    match = re.search(r"'([^']+)'", suggestions)
                    if match:
                        relationship_type_corrections[rel_type] = match.group(1)

        # Apply entity corrections
        for original_entity_id, entity in kg.entities.items():
            # Create a copy of the entity
            entity_properties = entity.properties.copy() if hasattr(entity, "properties") else {}

            # Apply property corrections if available
            if original_entity_id in entity_corrections:
                for prop, correction in entity_corrections[original_entity_id].items():
                    if prop in entity_properties:
                        entity_properties[prop] = correction

            # Add the corrected entity
            # TODO corrected_entity is not reference anywhere. See if we need it.
            corrected_entity = corrected_kg.add_entity(
                entity_type=entity.entity_type if hasattr(entity, "entity_type") else "entity",
                name=entity.name if hasattr(entity, "name") else "Unknown",
                properties=entity_properties,
                entity_id=original_entity_id,
                confidence=entity.confidence if hasattr(entity, "confidence") else 1.0,
                source_text=entity.source_text if hasattr(entity, "source_text") else None
            )

        # Apply relationship corrections
        for rel_id, rel in kg.relationships.items():
            # Get source and target entities
            source_entity = corrected_kg.get_entity_by_id(rel.source_id)
            target_entity = corrected_kg.get_entity_by_id(rel.target_id)

            if source_entity and target_entity:
                # Correct relationship type if needed
                rel_type = rel.relationship_type if hasattr(rel, "relationship_type") else "related_to"
                if rel_type in relationship_type_corrections:
                    rel_type = relationship_type_corrections[rel_type]

                # Create the corrected relationship
                corrected_kg.add_relationship(
                    relationship_type=rel_type,
                    source=source_entity,
                    target=target_entity,
                    properties=rel.properties.copy() if hasattr(rel, "properties") else {},
                    relationship_id=rel_id,
                    confidence=rel.confidence if hasattr(rel, "confidence") else 1.0,
                    source_text=rel.source_text if hasattr(rel, "source_text") else None,
                    bidirectional=rel.bidirectional if hasattr(rel, "bidirectional") else False
                )

        return corrected_kg
