"""
RDF Serialization Module

This module provides serialization and deserialization for RDF formats,
particularly Turtle (Terse RDF Triple Language).
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class TurtleSerializer:
    """
    Serializes RDF graphs to Turtle format.
    
    Turtle is a human-friendly RDF serialization format that uses
    prefixes and abbreviated syntax for readability.
    """
    
    def __init__(self):
        """Initialize the Turtle serializer."""
        self.prefixes: Dict[str, str] = {}
        self.default_prefixes = {
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "xsd": "http://www.w3.org/2001/XMLSchema#",
            "owl": "http://www.w3.org/2002/07/owl#",
            "schema": "https://schema.org/",
            "foaf": "http://xmlns.com/foaf/0.1/",
            "dc": "http://purl.org/dc/terms/",
            "skos": "http://www.w3.org/2004/02/skos/core#",
            "prov": "http://www.w3.org/ns/prov#",
            "geo": "http://www.w3.org/2003/01/geo/wgs84_pos#",
        }
    
    def serialize(
        self,
        triples: List[Tuple[str, str, Any]],
        prefixes: Optional[Dict[str, str]] = None,
        base_uri: Optional[str] = None
    ) -> str:
        """
        Serialize triples to Turtle format.
        
        Args:
            triples: List of (subject, predicate, object) triples
            prefixes: Custom prefix mappings (merged with defaults)
            base_uri: Base URI for relative references
            
        Returns:
            Turtle-formatted string
        """
        # Merge prefixes
        self.prefixes = dict(self.default_prefixes)
        if prefixes:
            self.prefixes.update(prefixes)
        
        # Build Turtle output
        lines = []
        
        # Add base URI if provided
        if base_uri:
            lines.append(f"@base <{base_uri}> .")
            lines.append("")
        
        # Add prefix declarations
        for prefix, namespace in sorted(self.prefixes.items()):
            lines.append(f"@prefix {prefix}: <{namespace}> .")
        lines.append("")
        
        # Group triples by subject for more readable output
        subject_map: Dict[str, List[Tuple[str, Any]]] = {}
        for subject, predicate, obj in triples:
            if subject not in subject_map:
                subject_map[subject] = []
            subject_map[subject].append((predicate, obj))
        
        # Serialize each subject
        for subject, pred_objs in subject_map.items():
            subject_str = self._format_term(subject)
            lines.append(f"{subject_str}")
            
            # Group by predicate
            pred_map: Dict[str, List[Any]] = {}
            for pred, obj in pred_objs:
                if pred not in pred_map:
                    pred_map[pred] = []
                pred_map[pred].append(obj)
            
            # Write predicates and objects
            predicates = list(pred_map.items())
            for i, (pred, objects) in enumerate(predicates):
                pred_str = self._format_term(pred)
                
                # Write objects
                obj_strs = [self._format_term(obj) for obj in objects]
                obj_line = ", ".join(obj_strs)
                
                # Add semicolon or period
                if i == len(predicates) - 1:
                    lines.append(f"    {pred_str} {obj_line} .")
                else:
                    lines.append(f"    {pred_str} {obj_line} ;")
            
            lines.append("")
        
        return "\n".join(lines)
    
    def _format_term(self, term: Any) -> str:
        """
        Format a term (subject, predicate, or object) for Turtle output.
        
        Args:
            term: Term to format
            
        Returns:
            Formatted term string
        """
        if isinstance(term, str):
            # Check if it's a URI
            if term.startswith("http://") or term.startswith("https://"):
                # Try to use prefix
                for prefix, namespace in self.prefixes.items():
                    if term.startswith(namespace):
                        local_part = term[len(namespace):]
                        return f"{prefix}:{local_part}"
                # No prefix match, use full URI
                return f"<{term}>"
            
            # Check if it's a blank node
            elif term.startswith("_:"):
                return term
            
            # Check if it's already prefixed
            elif ":" in term and not term.startswith("http"):
                return term
            
            # Otherwise treat as literal string
            else:
                # Escape special characters
                escaped = term.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                return f'"{escaped}"'
        
        elif isinstance(term, bool):
            return "true" if term else "false"
        
        elif isinstance(term, int):
            return str(term)
        
        elif isinstance(term, float):
            return str(term)
        
        elif isinstance(term, dict):
            # Handle typed literals
            if "@value" in term:
                value = term["@value"]
                if "@type" in term:
                    value_str = self._format_term(value)
                    type_str = self._format_term(term["@type"])
                    return f"{value_str}^^{type_str}"
                elif "@language" in term:
                    value_str = self._format_term(value)
                    return f'{value_str}@{term["@language"]}'
                else:
                    return self._format_term(value)
            # Handle blank nodes with properties
            return "_:blank"
        
        else:
            return f'"{str(term)}"'


class TurtleParser:
    """
    Parses Turtle RDF format into triples.
    
    Supports:
    - Prefix declarations (@prefix, @base)
    - URIs, blank nodes, literals
    - Predicate-object lists with ; and ,
    - Collection abbreviations
    """
    
    def __init__(self):
        """Initialize the Turtle parser."""
        self.prefixes: Dict[str, str] = {}
        self.base_uri: Optional[str] = None
        self.blank_node_counter = 0
    
    def parse(self, turtle_text: str) -> Tuple[List[Tuple[str, str, Any]], Dict[str, str]]:
        """
        Parse Turtle text into triples.
        
        Args:
            turtle_text: Turtle-formatted text
            
        Returns:
            Tuple of (triples list, prefixes dict)
        """
        triples: List[Tuple[str, str, Any]] = []
        self.prefixes = {}
        self.base_uri = None
        
        # Split into lines and process
        lines = turtle_text.split("\n")
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                i += 1
                continue
            
            # Handle prefix declarations
            if line.startswith("@prefix"):
                self._parse_prefix(line)
                i += 1
                continue
            
            # Handle base URI
            if line.startswith("@base"):
                self._parse_base(line)
                i += 1
                continue
            
            # Handle triples
            # Accumulate lines until we find a period
            triple_text = line
            while not triple_text.rstrip().endswith("."):
                i += 1
                if i >= len(lines):
                    break
                next_line = lines[i].strip()
                if next_line and not next_line.startswith("#"):
                    triple_text += " " + next_line
            
            if triple_text.strip():
                parsed_triples = self._parse_triples(triple_text)
                triples.extend(parsed_triples)
            
            i += 1
        
        return triples, self.prefixes
    
    def _parse_prefix(self, line: str) -> None:
        """
        Parse a @prefix declaration.
        
        Args:
            line: Line containing @prefix
        """
        # Match: @prefix prefix: <namespace> .
        match = re.match(r'@prefix\s+(\w+):\s+<([^>]+)>\s*\.', line)
        if match:
            prefix = match.group(1)
            namespace = match.group(2)
            self.prefixes[prefix] = namespace
    
    def _parse_base(self, line: str) -> None:
        """
        Parse a @base declaration.
        
        Args:
            line: Line containing @base
        """
        # Match: @base <uri> .
        match = re.match(r'@base\s+<([^>]+)>\s*\.', line)
        if match:
            self.base_uri = match.group(1)
    
    def _parse_triples(self, text: str) -> List[Tuple[str, str, Any]]:
        """
        Parse triples from text.
        
        Args:
            text: Text containing triples
            
        Returns:
            List of triples
        """
        triples: List[Tuple[str, str, Any]] = []
        
        # Remove trailing period
        text = text.rstrip().rstrip(".")
        
        # Split by subject (simplified parsing)
        # This is a basic implementation - a full Turtle parser would be more complex
        
        # Try to extract subject
        parts = text.split(None, 1)
        if len(parts) < 2:
            return triples
        
        subject = self._expand_term(parts[0])
        rest = parts[1]
        
        # Split by semicolon for predicate-object lists
        po_groups = rest.split(";")
        
        for po_group in po_groups:
            po_group = po_group.strip()
            if not po_group:
                continue
            
            # Split predicate and objects
            po_parts = po_group.split(None, 1)
            if len(po_parts) < 2:
                continue
            
            predicate = self._expand_term(po_parts[0])
            objects_text = po_parts[1]
            
            # Split objects by comma
            object_strs = [o.strip() for o in objects_text.split(",")]
            
            for obj_str in object_strs:
                if obj_str:
                    obj = self._parse_object(obj_str)
                    triples.append((subject, predicate, obj))
        
        return triples
    
    def _expand_term(self, term: str) -> str:
        """
        Expand a term using prefixes.
        
        Args:
            term: Term to expand
            
        Returns:
            Expanded term
        """
        term = term.strip()
        
        # Full URI
        if term.startswith("<") and term.endswith(">"):
            return term[1:-1]
        
        # Blank node
        if term.startswith("_:"):
            return term
        
        # Prefixed name
        if ":" in term:
            parts = term.split(":", 1)
            prefix = parts[0]
            local_part = parts[1]
            
            if prefix in self.prefixes:
                return self.prefixes[prefix] + local_part
        
        return term
    
    def _parse_object(self, obj_str: str) -> Any:
        """
        Parse an object value.
        
        Args:
            obj_str: Object string
            
        Returns:
            Parsed object value
        """
        obj_str = obj_str.strip()
        
        # URI or blank node
        if obj_str.startswith("<") or obj_str.startswith("_:") or ":" in obj_str:
            return self._expand_term(obj_str)
        
        # String literal
        if obj_str.startswith('"'):
            # Extract string value
            # Handle language tags and datatypes
            if "^^" in obj_str:
                parts = obj_str.split("^^", 1)
                value_part = parts[0].strip('"')
                datatype = self._expand_term(parts[1])
                return {
                    "@value": value_part,
                    "@type": datatype
                }
            elif "@" in obj_str and obj_str.count('"') >= 2:
                # Language tag
                quote_end = obj_str.rfind('"')
                value_part = obj_str[1:quote_end]
                lang_part = obj_str[quote_end+1:].strip()
                if lang_part.startswith("@"):
                    return {
                        "@value": value_part,
                        "@language": lang_part[1:]
                    }
            else:
                return obj_str.strip('"')
        
        # Boolean
        if obj_str == "true":
            return True
        if obj_str == "false":
            return False
        
        # Try parsing as number
        try:
            if "." in obj_str or "e" in obj_str.lower():
                return float(obj_str)
            else:
                return int(obj_str)
        except ValueError:
            pass  # Not a number - fall through to return as string
        
        return obj_str


def jsonld_to_turtle(jsonld: Dict[str, Any]) -> str:
    """
    Convert JSON-LD to Turtle format.
    
    Args:
        jsonld: JSON-LD document
        
    Returns:
        Turtle-formatted string
    """
    from .translator import JSONLDTranslator
    
    # Convert JSON-LD to triples
    translator = JSONLDTranslator()
    graph = translator.jsonld_to_ipld(jsonld)
    
    triples: List[Tuple[str, str, Any]] = []
    
    # Convert entities to triples
    for entity in graph.entities:
        subject = entity.get("id", "_:blank")
        
        # Add type triple
        if "type" in entity:
            triples.append((subject, "rdf:type", entity["type"]))
        
        # Add property triples
        for key, value in entity.get("properties", {}).items():
            if key != "_jsonld_id":
                triples.append((subject, key, value))
    
    # Convert relationships to triples
    for rel in graph.relationships:
        subject = rel["source"]
        predicate = rel["type"]
        obj = rel["target"]
        triples.append((subject, predicate, obj))
    
    # Extract prefixes from context if available
    prefixes = {}
    if "context" in graph.metadata:
        context_dict = graph.metadata["context"]
        for key, value in context_dict.items():
            if not key.startswith("@") and isinstance(value, str):
                prefixes[key] = value
    
    # Serialize to Turtle
    serializer = TurtleSerializer()
    return serializer.serialize(triples, prefixes)


def turtle_to_jsonld(turtle_text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Convert Turtle format to JSON-LD.
    
    Args:
        turtle_text: Turtle-formatted text
        context: JSON-LD context to use
        
    Returns:
        JSON-LD document
    """
    from .translator import JSONLDTranslator
    from .types import IPLDGraph
    
    # Parse Turtle to triples
    parser = TurtleParser()
    triples, prefixes = parser.parse(turtle_text)
    
    # Convert triples to IPLD graph
    graph = IPLDGraph()
    
    # Track entities
    entity_map: Dict[str, Dict[str, Any]] = {}
    
    for subject, predicate, obj in triples:
        # Ensure subject entity exists
        if subject not in entity_map:
            entity_map[subject] = {
                "id": subject,
                "type": "Thing",
                "properties": {}
            }
        
        entity = entity_map[subject]
        
        # Handle rdf:type
        if predicate == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type" or predicate == "rdf:type":
            entity["type"] = obj
        # Handle properties vs relationships
        elif isinstance(obj, (str, int, float, bool)):
            entity["properties"][predicate] = obj
        else:
            # It's a relationship
            graph.relationships.append({
                "type": predicate,
                "source": subject,
                "target": obj,
                "properties": {}
            })
    
    # Add entities to graph
    graph.entities = list(entity_map.values())
    
    # Add prefixes to metadata
    if prefixes:
        graph.metadata["context"] = prefixes
    
    # Convert to JSON-LD
    translator = JSONLDTranslator()
    return translator.ipld_to_jsonld(graph, None)
