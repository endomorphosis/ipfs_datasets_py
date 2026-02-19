"""
Wikipedia and Wikidata extraction helpers.

This module provides WikipediaExtractionMixin, a mixin class that adds
Wikipedia page extraction and Wikidata validation capabilities to
KnowledgeGraphExtractor.  Extracted from extractor.py to reduce its size.
"""
import logging
import requests
from typing import Dict, List, Any, Optional

from .entities import Entity
from .relationships import Relationship
from .graph import KnowledgeGraph
from ..exceptions import EntityExtractionError, ValidationError
from ._entity_helpers import _string_similarity

logger = logging.getLogger(__name__)


class WikipediaExtractionMixin:
    """Mixin providing Wikipedia/Wikidata extraction and validation methods."""

    def extract_from_wikipedia(self, 
                            page_title: str, 
                            extraction_temperature: float = 0.7,
                           structure_temperature: float = 0.5
                           ) -> KnowledgeGraph:
        """Extract a knowledge graph from a Wikipedia page with tunable parameters.

        This method fetches content from a Wikipedia page via the Wikipedia API and processes it into
        a structured knowledge graph. The extraction process is highly configurable through temperature
        parameters that control both the level of detail and structural complexity of the resulting graph.

        Args:
            page_title (str): The exact title of the Wikipedia page to extract from. Must match
                the Wikipedia page title format (case-sensitive, with proper spacing).
            extraction_temperature (float, optional): Controls the granularity and depth of entity
                and relationship extraction. Defaults to 0.7.
                - Low values (0.1-0.3): Extract only primary concepts, major entities, and the 
                    strongest, most obvious relationships. Results in a minimal, core knowledge graph.
                - Medium values (0.4-0.7): Balanced extraction including secondary concepts, 
                    moderate entity detail, and well-supported relationships. Provides good coverage
                    without excessive noise.
                - High values (0.8-1.0): Comprehensive extraction including detailed concepts,
                    entity properties, attributes, nuanced relationships, and contextual information.
                    May include more speculative or weak relationships.
            structure_temperature (float, optional): Controls the hierarchical complexity and
                relationship diversity of the knowledge graph structure. Defaults to 0.5.
                - Low values (0.1-0.3): Creates flatter graph structures with fewer relationship
                    types, focusing on direct connections and simple hierarchies.
                - Medium values (0.4-0.7): Generates balanced hierarchical structures with
                    moderate relationship type diversity and multi-level organization.
                - High values (0.8-1.0): Produces rich, multi-layered concept hierarchies with
                    diverse relationship types, complex interconnections, and deep structural nesting.

        Returns:
            KnowledgeGraph: A comprehensive knowledge graph object containing:
                - Extracted entities with their properties and confidence scores
                - Relationships between entities with type classification and confidence
                - A special Wikipedia page entity representing the source
                - "sourced_from" relationships linking all entities to their Wikipedia origin
                - Metadata including entity and relationship type classifications
                - Graph name formatted as "wikipedia_{page_title}"

        Raises:
            ValueError: If the specified Wikipedia page title is not found or does not exist.
                The error message will indicate the specific page title that was not found.
            RuntimeError: If any error occurs during the Wikipedia API request, content processing,
                or knowledge graph construction. The original exception details are preserved
                in the error message for debugging purposes.

        Note:
            - The method requires an active internet connection to access the Wikipedia API
            - Wikipedia page titles are case-sensitive and must match exactly
            - The extraction process may take significant time for large Wikipedia pages
            - If tracing is enabled, detailed extraction metadata is recorded for analysis
            - The resulting knowledge graph includes bidirectional relationship tracking
            - All extracted entities maintain provenance through "sourced_from" relationships

        Example:
            >>> extractor = KnowledgeGraphExtractor()
            >>> kg = extractor.extract_from_wikipedia(
            ...     page_title="Artificial Intelligence",
            ...     extraction_temperature=0.6,
            ...     structure_temperature=0.4
            ... )
            >>> print(f"Extracted {len(kg.entities)} entities and {len(kg.relationships)} relationships")
        """
        # Create trace if tracer is enabled
        trace_id = None
        if self.use_tracer and self.tracer:
            trace_id = self.tracer.trace_extraction(
                page_title=page_title,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

        # Fetch Wikipedia content
        try:
            # Make API request to get Wikipedia page content
            url = "https://en.wikipedia.org/w/api.php"
            params = {
                "action": "query",
                "format": "json",
                "titles": page_title,
                "prop": "extracts",
                "exintro": 0,  # Include the full page, not just intro
                "explaintext": 1  # Get plain text
            }

            response = requests.get(url, params=params)
            data = response.json()

            # Extract the page content
            pages = data["query"]["pages"]
            page_id = list(pages.keys())[0]

            # Check if page exists
            if page_id == "-1":
                error_msg = f"Wikipedia page '{page_title}' not found."
                # Update trace with error if tracer is enabled
                if self.use_tracer and self.tracer and trace_id:
                    self.tracer.update_extraction_trace(
                        trace_id=trace_id,
                        status="failed",
                        error=error_msg
                    )
                raise ValueError(error_msg)

            page_content = pages[page_id]["extract"]

            # Create knowledge graph from the content with temperature parameters
            kg = self.extract_enhanced_knowledge_graph(
                page_content,
                use_chunking=True,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

            # Add metadata about the source
            kg.name = f"wikipedia_{page_title}"

            # Add the Wikipedia page as a source entity
            page_entity = Entity(
                entity_type="wikipedia_page",
                name=page_title,
                properties={"url": f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}"},
                confidence=1.0
            )

            kg.entities[page_entity.entity_id] = page_entity
            kg.entity_types["wikipedia_page"].add(page_entity.entity_id)
            kg.entity_names[page_title].add(page_entity.entity_id)

            # Create "source_from" relationships
            for entity in list(kg.entities.values()):
                if entity.entity_id != page_entity.entity_id:
                    rel = Relationship(
                        relationship_type="sourced_from",
                        source=entity,
                        target=page_entity,
                        confidence=1.0
                    )

                    kg.relationships[rel.relationship_id] = rel
                    kg.relationship_types["sourced_from"].add(rel.relationship_id)
                    kg.entity_relationships[entity.entity_id].add(rel.relationship_id)
                    kg.entity_relationships[page_entity.entity_id].add(rel.relationship_id)

            # Update trace with results if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                self.tracer.update_extraction_trace(
                    trace_id=trace_id,
                    status="completed",
                    knowledge_graph=kg,
                    entity_count=len(kg.entities),
                    relationship_count=len(kg.relationships),
                    entity_types=dict(kg.entity_types),
                    relationship_types=dict(kg.relationship_types)
                )

            return kg

        except (requests.RequestException, requests.HTTPError, requests.Timeout) as e:
            error_msg = f"Network error extracting knowledge graph from Wikipedia '{page_title}': {e}"
            logger.error(error_msg)
            # Update trace with error if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                self.tracer.update_extraction_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=error_msg
                )
            # Re-raise as EntityExtractionError
            raise EntityExtractionError(error_msg, details={'wikipedia_title': page_title, 'trace_id': trace_id}) from e
        
        except (ValueError, KeyError, TypeError, IndexError) as e:
            error_msg = f"Unexpected error extracting knowledge graph from Wikipedia '{page_title}': {e}"
            logger.error(error_msg)
            # Update trace with error if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                self.tracer.update_extraction_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=error_msg
                )
            # Re-raise as EntityExtractionError
            raise EntityExtractionError(error_msg, details={'wikipedia_title': page_title, 'trace_id': trace_id}) from e

    def validate_against_wikidata(self, kg: KnowledgeGraph, entity_name: str) -> Dict[str, Any]:
        """
        Validate a knowledge graph against Wikidata's structured data.

        Args:
            kg (KnowledgeGraph): Knowledge graph to validate
            entity_name (str): Name of the main entity to validate against

        Returns:
            Dict: Validation results including:
                - coverage: Percentage of Wikidata statements covered
                - missing_relationships: Relationships in Wikidata not in the KG
                - additional_relationships: Relationships in the KG not in Wikidata
                - entity_mapping: Mapping between KG entities and Wikidata entities
        """
        # Create trace if tracer is enabled
        trace_id = None
        if self.use_tracer and self.tracer:
            trace_id = self.tracer.trace_validation(
                kg_name=kg.name,
                entity_name=entity_name
            )

        try:
            # Map the entity to Wikidata
            wikidata_id = self._get_wikidata_id(entity_name)

            if not wikidata_id:
                error_result = {
                    "error": f"Could not find Wikidata entity for '{entity_name}'",
                    "coverage": 0.0,
                    "missing_relationships": [],
                    "additional_relationships": [],
                    "entity_mapping": {}
                }

                # Update trace with error if tracer is enabled
                if self.use_tracer and self.tracer and trace_id:
                    self.tracer.update_validation_trace(
                        trace_id=trace_id,
                        status="failed",
                        error=error_result["error"],
                        validation_results=error_result
                    )

                return error_result

            # Get structured data from Wikidata
            wikidata_statements = self._get_wikidata_statements(wikidata_id)

            # Find corresponding entity in the knowledge graph
            kg_entities = kg.get_entities_by_name(entity_name)

            if not kg_entities:
                error_result = {
                    "error": f"Entity '{entity_name}' not found in the knowledge graph",
                    "coverage": 0.0,
                    "missing_relationships": wikidata_statements,
                    "additional_relationships": [],
                    "entity_mapping": {}
                }

                # Update trace with error if tracer is enabled
                if self.use_tracer and self.tracer and trace_id:
                    self.tracer.update_validation_trace(
                        trace_id=trace_id,
                        status="failed",
                        error=error_result["error"],
                        validation_results=error_result
                    )

                return error_result

            kg_entity = kg_entities[0]

            # Find relationships in the KG involving this entity
            kg_relationships = kg.get_relationships_by_entity(kg_entity)

            # Convert to simplified format for comparison
            kg_statements = []
            entity_mapping = {kg_entity.entity_id: wikidata_id}

            for rel in kg_relationships:
                if rel.source_id == kg_entity.entity_id:
                    # This is an outgoing relationship
                    kg_statements.append({
                        "property": rel.relationship_type,
                        "value": rel.target_entity.name,
                        "value_entity": rel.target_entity.entity_id
                    })
                elif rel.target_id == kg_entity.entity_id:
                    # This is an incoming relationship
                    kg_statements.append({
                        "property": f"inverse_{rel.relationship_type}",
                        "value": rel.source_entity.name,
                        "value_entity": rel.source_entity.entity_id
                    })

            # Compare statements
            covered_statements = []
            missing_statements = []

            for wk_stmt in wikidata_statements:
                # Try to find a matching statement in the KG
                found = False
                best_match = None
                best_score = 0.0

                for kg_stmt in kg_statements:
                    # Compare property names (inexact)
                    prop_match = _string_similarity(
                        wk_stmt["property"].lower(),
                        kg_stmt["property"].lower()
                    )

                    # Compare values (inexact)
                    value_match = _string_similarity(
                        wk_stmt["value"].lower(),
                        kg_stmt["value"].lower()
                    )

                    # Calculate overall match score
                    score = (prop_match + value_match) / 2.0

                    if score > 0.7 and score > best_score:  # Threshold for considering a match
                        found = True
                        best_match = kg_stmt
                        best_score = score

                if found:
                    covered_statements.append({
                        "wikidata": wk_stmt,
                        "kg": best_match,
                        "match_score": best_score
                    })

                    # Add to entity mapping
                    if "value_id" in wk_stmt and "value_entity" in best_match:
                        entity_mapping[best_match["value_entity"]] = wk_stmt["value_id"]
                else:
                    missing_statements.append(wk_stmt)

            # Find additional statements in the KG
            additional_statements = []

            for kg_stmt in kg_statements:
                if not any(covered["kg"] == kg_stmt for covered in covered_statements):
                    additional_statements.append(kg_stmt)

            # Calculate coverage
            if len(wikidata_statements) > 0:
                coverage = len(covered_statements) / len(wikidata_statements)
            else:
                coverage = 1.0  # No statements to cover

            result = {
                "coverage": coverage,
                "covered_relationships": covered_statements,
                "missing_relationships": missing_statements,
                "additional_relationships": additional_statements,
                "entity_mapping": entity_mapping
            }

            # Update trace with results if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                self.tracer.update_validation_trace(
                    trace_id=trace_id,
                    status="completed",
                    wikidata_id=wikidata_id,
                    wikidata_statements_count=len(wikidata_statements),
                    kg_statements_count=len(kg_statements),
                    coverage=coverage,
                    covered_count=len(covered_statements),
                    missing_count=len(missing_statements),
                    additional_count=len(additional_statements),
                    validation_results=result
                )

            return result

        except (requests.RequestException, requests.HTTPError, requests.Timeout) as e:
            error_result = {
                "error": f"Network error validating against Wikidata: {e}",
                "coverage": 0.0,
                "missing_relationships": [],
                "additional_relationships": [],
                "entity_mapping": {}
            }
            logger.error(f"Wikidata validation network error: {e}")

            # Update trace with error if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                self.tracer.update_validation_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=str(e),
                    validation_results=error_result
                )

            return error_result
        
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as e:
            error_result = {
                "error": f"Unexpected error validating against Wikidata: {e}",
                "coverage": 0.0,
                "missing_relationships": [],
                "additional_relationships": [],
                "entity_mapping": {}
            }
            logger.error(f"Wikidata validation error: {e}")

            # Update trace with error if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                self.tracer.update_validation_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=str(e),
                    validation_results=error_result
                )

            # Wrap in ValidationError
            raise ValidationError(
                f"Failed to validate knowledge graph against Wikidata: {e}",
                details={'trace_id': trace_id, 'entity_name': kg.entities.get(list(kg.entities.keys())[0]).name if kg.entities else 'unknown'}
            ) from e

    def _get_wikidata_id(self, entity_name: str) -> Optional[str]:
        """
        Get the Wikidata ID for an entity name.

        Args:
            entity_name (str): Name of the entity

        Returns:
            str: Wikidata ID (Qxxxxx) or None if not found
        """
        try:
            # Make API request to search for the entity
            url = "https://www.wikidata.org/w/api.php"
            params = {
                "action": "wbsearchentities",
                "format": "json",
                "search": entity_name,
                "language": "en"
            }

            response = requests.get(url, params=params)
            data = response.json()

            # Get the first result if available
            if "search" in data and len(data["search"]) > 0:
                return data["search"][0]["id"]
            else:
                return None

        except (requests.RequestException, ValueError) as e:
            logger.debug(f"Could not retrieve Wikidata ID for '{entity_name}': {e}")
            return None
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            logger.warning(f"Unexpected error getting Wikidata ID for '{entity_name}': {e}")
            return None

    def _get_wikidata_statements(self, entity_id: str) -> List[Dict[str, Any]]:
        """
        Get structured statements for a Wikidata entity.

        Args:
            entity_id (str): Wikidata entity ID (Qxxxxx)

        Returns:
            List[Dict]: List of simplified statements
        """
        try:
            # Query the Wikidata SPARQL endpoint
            sparql_endpoint = "https://query.wikidata.org/sparql"

            # SPARQL query to get all direct relations
            query = f"""
            SELECT ?property ?propertyLabel ?value ?valueLabel ?valueId
            WHERE {{
              wd:{entity_id} ?p ?value .
              ?property wikibase:directClaim ?p .
              OPTIONAL {{ ?value wdt:P31 ?type . }}
              OPTIONAL {{
                FILTER(isIRI(?value))
                BIND(STRAFTER(STR(?value), 'http://www.wikidata.org/entity/') AS ?valueId)
              }}
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
            }}
            """

            headers = {
                'User-Agent': 'KnowledgeGraphValidator/1.0 (https://example.org/; info@example.org)',
                'Accept': 'application/json'
            }

            response = requests.get(
                sparql_endpoint,
                params={"query": query, "format": "json"},
                headers=headers
            )

            data = response.json()

            # Process and simplify the results
            statements = []

            for result in data.get("results", {}).get("bindings", []):
                # Skip some administrative properties
                property_id = result.get("property", {}).get("value", "")
                if property_id.endswith("/P31") or property_id.endswith("/P279"):  # Instance of, subclass of
                    continue

                statement = {
                    "property": result.get("propertyLabel", {}).get("value", "Unknown property"),
                    "value": result.get("valueLabel", {}).get("value", "Unknown value")
                }

                # Include Wikidata IDs if available
                if "valueId" in result and result["valueId"].get("value"):
                    statement["value_id"] = result["valueId"]["value"]

                statements.append(statement)

            return statements

        except (requests.RequestException, requests.HTTPError, requests.Timeout) as e:
            logger.error(f"Network error querying Wikidata for entity '{entity_id}': {e}")
            return []
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as e:
            logger.error(f"Unexpected error querying Wikidata for entity '{entity_id}': {e}")
            raise ValidationError(
                f"Failed to query Wikidata statements for entity '{entity_id}': {e}",
                details={'entity_id': entity_id}
            ) from e



    def extract_and_validate_wikipedia_graph(self, page_title: str, extraction_temperature: float = 0.7,
                                        structure_temperature: float = 0.5) -> Dict[str, Any]:
        """
        Extract knowledge graph from a Wikipedia page and validate against Wikidata SPARQL.

        This function extracts a knowledge graph from a Wikipedia page, then queries the
        Wikidata SPARQL endpoint to validate that the extraction contains at least the
        structured data already present in Wikidata.

        Args:
            page_title (str): Title of the Wikipedia page
            extraction_temperature (float): Controls level of detail (0.0-1.0)
            structure_temperature (float): Controls structural complexity (0.0-1.0)

        Returns:
            Dict: Result containing:
                - knowledge_graph: The extracted knowledge graph
                - validation: Validation results against Wikidata
                - coverage: Percentage of Wikidata statements covered (0.0-1.0)
                - metrics: Additional metrics about extraction quality
                - trace_id: ID of the trace if tracing is enabled
        """
        # Create trace if tracer is enabled
        trace_id = None
        if self.use_tracer and self.tracer:
            trace_id = self.tracer.trace_extraction_and_validation(
                page_title=page_title,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

        try:
            # Extract knowledge graph from Wikipedia
            kg = self.extract_from_wikipedia(
                page_title=page_title,
                extraction_temperature=extraction_temperature,
                structure_temperature=structure_temperature
            )

            # Validate against Wikidata
            validation_results = self.validate_against_wikidata(kg, page_title)

            # Calculate additional metrics
            metrics = {
                "entity_count": len(kg.entities),
                "relationship_count": len(kg.relationships),
                "entity_types": {entity_type: len(entities) for entity_type, entities in kg.entity_types.items()},
                "relationship_types": {rel_type: len(rels) for rel_type, rels in kg.relationship_types.items()},
                "avg_confidence": sum(e.confidence for e in kg.entities.values()) / len(kg.entities) if kg.entities else 0,
                "extraction_temperature": extraction_temperature,
                "structure_temperature": structure_temperature
            }

            # Create comprehensive result
            result = {
                "knowledge_graph": kg,
                "validation": validation_results,
                "coverage": validation_results.get("coverage", 0.0),
                "metrics": metrics
            }

            # Add trace ID if tracing is enabled
            if self.use_tracer and self.tracer and trace_id:
                result["trace_id"] = trace_id

                # Update combined trace with results
                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="completed",
                    knowledge_graph=kg,
                    validation_results=validation_results,
                    metrics=metrics,
                    entity_count=len(kg.entities),
                    relationship_count=len(kg.relationships),
                    coverage=validation_results.get("coverage", 0.0)
                )

            return result

        except EntityExtractionError:
            # Re-raise our custom exceptions
            raise
        except ValidationError:
            # Re-raise validation errors
            raise
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as e:
            logger.error(f"Extract and validate failed for '{page_title}': {e}")
            # Update trace with error if tracer is enabled
            if self.use_tracer and self.tracer and trace_id:
                self.tracer.update_extraction_and_validation_trace(
                    trace_id=trace_id,
                    status="failed",
                    error=str(e)
                )
            # Wrap in EntityExtractionError
            raise EntityExtractionError(
                f"Failed to extract and validate knowledge graph from Wikipedia page '{page_title}': {e}",
                details={'page_title': page_title, 'extraction_temperature': extraction_temperature,
                        'structure_temperature': structure_temperature}
            ) from e


__all__ = ["WikipediaExtractionMixin"]
