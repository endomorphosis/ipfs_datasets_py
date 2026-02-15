"""
JSON-LD Translation Types

This module defines the core types and data structures for JSON-LD translation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class VocabularyType(Enum):
    """Supported vocabulary types."""
    SCHEMA_ORG = "https://schema.org/"
    FOAF = "http://xmlns.com/foaf/0.1/"
    DUBLIN_CORE = "http://purl.org/dc/terms/"
    SKOS = "http://www.w3.org/2004/02/skos/core#"
    WIKIDATA = "https://www.wikidata.org/wiki/"
    CUSTOM = "custom"


@dataclass
class JSONLDContext:
    """
    Represents a JSON-LD @context.
    
    Attributes:
        base_uri: Base URI for the context
        vocab: Default vocabulary URI
        prefixes: Namespace prefix mappings
        terms: Term definitions
    """
    base_uri: Optional[str] = None
    vocab: Optional[str] = None
    prefixes: Dict[str, str] = field(default_factory=dict)
    terms: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert context to JSON-LD @context dictionary."""
        context: Dict[str, Any] = {}
        
        if self.base_uri:
            context["@base"] = self.base_uri
        if self.vocab:
            context["@vocab"] = self.vocab
            
        # Add prefix mappings
        context.update(self.prefixes)
        
        # Add term definitions
        context.update(self.terms)
        
        return context
    
    @classmethod
    def from_dict(cls, data: Union[str, Dict, List]) -> "JSONLDContext":
        """Create context from JSON-LD @context value."""
        context = cls()
        
        if isinstance(data, str):
            # Simple string context (e.g., "https://schema.org/")
            context.vocab = data
        elif isinstance(data, dict):
            # Complex context object
            if "@base" in data:
                context.base_uri = data["@base"]
            if "@vocab" in data:
                context.vocab = data["@vocab"]
            
            # Extract prefixes and terms
            for key, value in data.items():
                if key.startswith("@"):
                    continue
                if isinstance(value, str):
                    context.prefixes[key] = value
                else:
                    context.terms[key] = value
        elif isinstance(data, list):
            # Array of contexts - merge them
            for item in data:
                sub_context = cls.from_dict(item)
                if sub_context.base_uri:
                    context.base_uri = sub_context.base_uri
                if sub_context.vocab:
                    context.vocab = sub_context.vocab
                context.prefixes.update(sub_context.prefixes)
                context.terms.update(sub_context.terms)
        
        return context


@dataclass
class IPLDGraph:
    """
    Represents an IPLD graph structure.
    
    Attributes:
        entities: List of entity dictionaries
        relationships: List of relationship dictionaries
        metadata: Graph metadata including context
    """
    entities: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "entities": self.entities,
            "relationships": self.relationships,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IPLDGraph":
        """Create from dictionary representation."""
        return cls(
            entities=data.get("entities", []),
            relationships=data.get("relationships", []),
            metadata=data.get("metadata", {})
        )


@dataclass
class TranslationOptions:
    """
    Options for JSON-LD translation.
    
    Attributes:
        expand_context: Whether to expand contexts during conversion
        compact_output: Whether to compact output JSON-LD
        preserve_blank_nodes: Whether to preserve blank node IDs
        generate_ids: Whether to auto-generate @id for entities without one
        validate_schema: Whether to validate against JSON Schema
    """
    expand_context: bool = True
    compact_output: bool = False
    preserve_blank_nodes: bool = True
    generate_ids: bool = True
    validate_schema: bool = False


@dataclass
class ValidationResult:
    """
    Result of schema validation.
    
    Attributes:
        valid: Whether validation passed
        errors: List of validation errors
        warnings: List of validation warnings
    """
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def add_error(self, error: str) -> None:
        """Add a validation error."""
        self.errors.append(error)
        self.valid = False
    
    def add_warning(self, warning: str) -> None:
        """Add a validation warning."""
        self.warnings.append(warning)
