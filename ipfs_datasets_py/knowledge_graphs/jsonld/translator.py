"""
JSON-LD to IPLD Translator

This module provides bidirectional translation between JSON-LD and IPLD formats.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from .context import ContextCompactor, ContextExpander
from .types import IPLDGraph, JSONLDContext, TranslationOptions

logger = logging.getLogger(__name__)


class JSONLDTranslator:
    """
    Translates between JSON-LD (semantic web format) and IPLD (content-addressed format).
    
    Features:
    - Bidirectional conversion
    - Context preservation
    - Blank node handling
    - ID mapping between @id and CID
    """
    
    def __init__(self, options: Optional[TranslationOptions] = None):
        """
        Initialize the translator.
        
        Args:
            options: Translation options
        """
        self.options = options or TranslationOptions()
        self.expander = ContextExpander()
        self.compactor = ContextCompactor()
        
        # Mapping between JSON-LD @id and IPLD entity IDs
        self.id_mappings: Dict[str, str] = {}
        self.reverse_id_mappings: Dict[str, str] = {}
    
    def jsonld_to_ipld(self, jsonld: Dict[str, Any]) -> IPLDGraph:
        """
        Convert JSON-LD document to IPLD graph.
        
        Args:
            jsonld: JSON-LD document
            
        Returns:
            IPLDGraph structure
        """
        # Extract and parse context
        context = None
        if "@context" in jsonld:
            context = JSONLDContext.from_dict(jsonld["@context"])
        else:
            context = JSONLDContext()
        
        # Expand the JSON-LD if requested
        if self.options.expand_context:
            expanded = self.expander.expand(jsonld, context)
        else:
            expanded = jsonld
        
        # Create IPLD graph
        graph = IPLDGraph()
        
        # Store context in metadata
        if context:
            graph.metadata["context"] = context.to_dict()
        
        # Reset ID mappings for this conversion
        self.id_mappings.clear()
        self.reverse_id_mappings.clear()
        
        # Convert based on structure
        if "@graph" in expanded:
            # Graph container - convert all items
            for item in expanded["@graph"]:
                self._convert_node_to_ipld(item, graph, context)
        else:
            # Single node or object
            self._convert_node_to_ipld(expanded, graph, context)
        
        return graph
    
    def _convert_node_to_ipld(
        self,
        node: Dict[str, Any],
        graph: IPLDGraph,
        context: Optional[JSONLDContext]
    ) -> str:
        """
        Convert a JSON-LD node to IPLD entity.
        
        Args:
            node: JSON-LD node
            graph: Target IPLD graph
            context: JSON-LD context
            
        Returns:
            Entity ID
        """
        # Generate or extract entity ID
        entity_id = self._get_or_create_entity_id(node)
        
        # Extract type
        node_type = node.get("@type", "Thing")
        if isinstance(node_type, list):
            node_type = node_type[0] if node_type else "Thing"
        
        # Create entity
        entity: Dict[str, Any] = {
            "id": entity_id,
            "type": node_type,
            "properties": {}
        }
        
        # Store original @id if present
        if "@id" in node:
            entity["properties"]["_jsonld_id"] = node["@id"]
        
        # Process properties
        for key, value in node.items():
            # Skip JSON-LD keywords
            if key in ("@id", "@type", "@context", "@graph"):
                continue
            
            # Check if this is a relationship or property
            if isinstance(value, dict) and ("@id" in value or "@type" in value):
                # This is a relationship to another entity
                target_id = self._convert_node_to_ipld(value, graph, context)
                
                # Create relationship
                relationship = {
                    "type": key,
                    "source": entity_id,
                    "target": target_id,
                    "properties": {}
                }
                graph.relationships.append(relationship)
            
            elif isinstance(value, list):
                # Array of values - could be relationships or literals
                for item in value:
                    if isinstance(item, dict) and ("@id" in item or "@type" in item):
                        # Relationship
                        target_id = self._convert_node_to_ipld(item, graph, context)
                        relationship = {
                            "type": key,
                            "source": entity_id,
                            "target": target_id,
                            "properties": {}
                        }
                        graph.relationships.append(relationship)
                    else:
                        # Literal value - add to properties as array
                        if key not in entity["properties"]:
                            entity["properties"][key] = []
                        entity["properties"][key].append(item)
            
            elif isinstance(value, str) and value.startswith("_:"):
                # Blank node reference - create relationship
                target_id = self._get_or_create_entity_id({"@id": value})
                relationship = {
                    "type": key,
                    "source": entity_id,
                    "target": target_id,
                    "properties": {}
                }
                graph.relationships.append(relationship)
            
            else:
                # Literal property
                entity["properties"][key] = value
        
        # Add entity to graph if not already present
        if not any(e["id"] == entity_id for e in graph.entities):
            graph.entities.append(entity)
        
        return entity_id
    
    def _get_or_create_entity_id(self, node: Dict[str, Any]) -> str:
        """
        Get or create an entity ID for a JSON-LD node.
        
        Args:
            node: JSON-LD node
            
        Returns:
            Entity ID
        """
        # Check if node has @id
        if "@id" in node:
            jsonld_id = node["@id"]
            
            # Check if we already have a mapping
            if jsonld_id in self.id_mappings:
                return self.id_mappings[jsonld_id]
            
            # Create new entity ID
            if jsonld_id.startswith("_:"):
                # Blank node
                if self.options.preserve_blank_nodes:
                    entity_id = jsonld_id
                else:
                    entity_id = f"_:{uuid.uuid4().hex[:8]}"
            else:
                # Named node - use hash of URI
                entity_id = f"entity_{uuid.uuid5(uuid.NAMESPACE_URL, jsonld_id).hex[:16]}"
            
            # Store mapping
            self.id_mappings[jsonld_id] = entity_id
            self.reverse_id_mappings[entity_id] = jsonld_id
            
            return entity_id
        
        # No @id - generate one if requested
        if self.options.generate_ids:
            entity_id = f"_:{uuid.uuid4().hex[:8]}"
            return entity_id
        
        # Use a generated ID based on content hash
        return f"entity_{uuid.uuid4().hex[:16]}"
    
    def ipld_to_jsonld(
        self,
        graph: IPLDGraph,
        context: Optional[JSONLDContext] = None
    ) -> Dict[str, Any]:
        """
        Convert IPLD graph to JSON-LD document.
        
        Args:
            graph: IPLD graph
            context: JSON-LD context to use (if None, extract from metadata)
            
        Returns:
            JSON-LD document
        """
        # Get context from metadata if not provided
        if context is None and "context" in graph.metadata:
            context = JSONLDContext.from_dict(graph.metadata["context"])
        
        if context is None:
            context = JSONLDContext()
        
        # Reset reverse mappings
        self.id_mappings.clear()
        self.reverse_id_mappings.clear()
        
        # Build entity map
        entity_map = {entity["id"]: entity for entity in graph.entities}
        
        # Build relationship map (grouped by source)
        relationship_map: Dict[str, List[Dict[str, Any]]] = {}
        for rel in graph.relationships:
            source_id = rel["source"]
            if source_id not in relationship_map:
                relationship_map[source_id] = []
            relationship_map[source_id].append(rel)
        
        # Convert entities to JSON-LD
        jsonld_nodes = []
        for entity in graph.entities:
            node = self._convert_entity_to_jsonld(
                entity,
                relationship_map.get(entity["id"], []),
                entity_map,
                context
            )
            jsonld_nodes.append(node)
        
        # Create result structure
        if len(jsonld_nodes) == 1:
            result = jsonld_nodes[0]
        else:
            result = {
                "@graph": jsonld_nodes
            }
        
        # Add context
        context_dict = context.to_dict()
        if context_dict:
            result["@context"] = context_dict
        
        # Compact if requested
        if self.options.compact_output:
            result = self.compactor.compact(result, context)
        
        return result
    
    def _convert_entity_to_jsonld(
        self,
        entity: Dict[str, Any],
        relationships: List[Dict[str, Any]],
        entity_map: Dict[str, Dict[str, Any]],
        context: JSONLDContext
    ) -> Dict[str, Any]:
        """
        Convert an IPLD entity to JSON-LD node.
        
        Args:
            entity: IPLD entity
            relationships: Outgoing relationships from this entity
            entity_map: Map of entity IDs to entities
            context: JSON-LD context
            
        Returns:
            JSON-LD node
        """
        node: Dict[str, Any] = {}
        
        # Add @type
        node["@type"] = entity["type"]
        
        # Add @id if entity has one stored
        if "_jsonld_id" in entity.get("properties", {}):
            node["@id"] = entity["properties"]["_jsonld_id"]
        else:
            # Generate @id from entity ID
            node["@id"] = f"_:{entity['id']}"
        
        # Add properties
        for key, value in entity.get("properties", {}).items():
            if key == "_jsonld_id":
                continue
            node[key] = value
        
        # Add relationships
        rel_groups: Dict[str, List[str]] = {}
        for rel in relationships:
            rel_type = rel["type"]
            target_id = rel["target"]
            
            # Get target @id
            if target_id in entity_map:
                target_entity = entity_map[target_id]
                if "_jsonld_id" in target_entity.get("properties", {}):
                    target_ref = target_entity["properties"]["_jsonld_id"]
                else:
                    target_ref = f"_:{target_id}"
            else:
                target_ref = f"_:{target_id}"
            
            # Group by relationship type
            if rel_type not in rel_groups:
                rel_groups[rel_type] = []
            rel_groups[rel_type].append(target_ref)
        
        # Add grouped relationships to node
        for rel_type, targets in rel_groups.items():
            if len(targets) == 1:
                node[rel_type] = targets[0]
            else:
                node[rel_type] = targets
        
        return node
