"""
JSON-LD Context Management

This module provides context expansion and compaction for JSON-LD documents.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import urljoin

from .types import JSONLDContext, VocabularyType

logger = logging.getLogger(__name__)


class ContextExpander:
    """
    Expands JSON-LD contexts to full URIs.
    
    This class handles:
    - Term expansion using @context definitions
    - Prefix expansion
    - Vocabulary expansion
    - Type coercion
    """
    
    def __init__(self):
        """Initialize the context expander."""
        self.built_in_contexts: Dict[str, Dict[str, Any]] = {
            # Core vocabularies (original 5)
            VocabularyType.SCHEMA_ORG.value: {
                "@vocab": "https://schema.org/"
            },
            VocabularyType.FOAF.value: {
                "@vocab": "http://xmlns.com/foaf/0.1/"
            },
            VocabularyType.DUBLIN_CORE.value: {
                "@vocab": "http://purl.org/dc/terms/"
            },
            VocabularyType.SKOS.value: {
                "@vocab": "http://www.w3.org/2004/02/skos/core#"
            },
            VocabularyType.WIKIDATA.value: {
                "@vocab": "https://www.wikidata.org/wiki/"
            },
            # Additional semantic web vocabularies (7+ new)
            VocabularyType.RDF.value: {
                "@vocab": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
            },
            VocabularyType.RDFS.value: {
                "@vocab": "http://www.w3.org/2000/01/rdf-schema#"
            },
            VocabularyType.OWL.value: {
                "@vocab": "http://www.w3.org/2002/07/owl#"
            },
            VocabularyType.PROV.value: {
                "@vocab": "http://www.w3.org/ns/prov#"
            },
            VocabularyType.ORG.value: {
                "@vocab": "http://www.w3.org/ns/org#"
            },
            VocabularyType.VCARD.value: {
                "@vocab": "http://www.w3.org/2006/vcard/ns#"
            },
            VocabularyType.DCAT.value: {
                "@vocab": "http://www.w3.org/ns/dcat#"
            },
            VocabularyType.TIME.value: {
                "@vocab": "http://www.w3.org/2006/time#"
            },
            VocabularyType.GEO.value: {
                "@vocab": "http://www.w3.org/2003/01/geo/wgs84_pos#"
            }
        }
    
    def expand(self, data: Any, context: Optional[JSONLDContext] = None) -> Any:
        """
        Expand JSON-LD data using the provided context.
        
        Args:
            data: JSON-LD data to expand
            context: Context to use for expansion
            
        Returns:
            Expanded JSON-LD data
        """
        if context is None:
            # Try to extract context from data
            if isinstance(data, dict) and "@context" in data:
                context = JSONLDContext.from_dict(data["@context"])
        
        if context is None:
            context = JSONLDContext()
        
        return self._expand_value(data, context)
    
    def _expand_value(self, value: Any, context: JSONLDContext) -> Any:
        """Recursively expand a value."""
        if isinstance(value, dict):
            return self._expand_object(value, context)
        elif isinstance(value, list):
            return [self._expand_value(item, context) for item in value]
        else:
            return value
    
    def _expand_object(self, obj: Dict[str, Any], context: JSONLDContext) -> Dict[str, Any]:
        """Expand an object."""
        expanded = {}
        
        for key, value in obj.items():
            # Skip @context in output
            if key == "@context":
                continue
            
            # Expand the key
            expanded_key = self._expand_term(key, context)
            
            # Special handling for @type
            if key == "@type":
                if isinstance(value, str):
                    expanded[expanded_key] = self._expand_term(value, context)
                elif isinstance(value, list):
                    expanded[expanded_key] = [self._expand_term(v, context) for v in value]
                else:
                    expanded[expanded_key] = value
            else:
                # Recursively expand the value
                expanded[expanded_key] = self._expand_value(value, context)
        
        return expanded
    
    def _expand_term(self, term: str, context: JSONLDContext) -> str:
        """
        Expand a term to its full URI.
        
        Args:
            term: Term to expand
            context: Context to use for expansion
            
        Returns:
            Expanded URI or original term if no expansion possible
        """
        # Already a URI
        if "://" in term or term.startswith("_:"):
            return term
        
        # Special JSON-LD keywords
        if term.startswith("@"):
            return term
        
        # Check term definitions
        if term in context.terms:
            term_def = context.terms[term]
            if isinstance(term_def, str):
                return term_def
            elif isinstance(term_def, dict) and "@id" in term_def:
                return term_def["@id"]
        
        # Check prefix expansion
        if ":" in term:
            prefix, local = term.split(":", 1)
            if prefix in context.prefixes:
                return context.prefixes[prefix] + local
        
        # Use vocabulary
        if context.vocab:
            return context.vocab + term
        
        # Return as-is if no expansion possible
        return term


class ContextCompactor:
    """
    Compacts expanded JSON-LD to use context prefixes and terms.
    
    This class handles:
    - URI compaction using @context
    - Vocabulary-relative IRIs
    - Prefix usage
    """
    
    def __init__(self):
        """Initialize the context compactor."""
        pass
    
    def compact(self, data: Any, context: JSONLDContext) -> Dict[str, Any]:
        """
        Compact expanded JSON-LD data using the provided context.
        
        Args:
            data: Expanded JSON-LD data
            context: Context to use for compaction
            
        Returns:
            Compacted JSON-LD data with @context
        """
        compacted = self._compact_value(data, context)
        
        # Add context to output
        if isinstance(compacted, dict):
            context_dict = context.to_dict()
            if context_dict:
                compacted["@context"] = context_dict
        
        return compacted
    
    def _compact_value(self, value: Any, context: JSONLDContext) -> Any:
        """Recursively compact a value."""
        if isinstance(value, dict):
            return self._compact_object(value, context)
        elif isinstance(value, list):
            return [self._compact_value(item, context) for item in value]
        else:
            return value
    
    def _compact_object(self, obj: Dict[str, Any], context: JSONLDContext) -> Dict[str, Any]:
        """Compact an object."""
        compacted = {}
        
        for key, value in obj.items():
            # Compact the key
            compacted_key = self._compact_term(key, context)
            
            # Special handling for @type
            if key == "@type":
                if isinstance(value, str):
                    compacted[compacted_key] = self._compact_term(value, context)
                elif isinstance(value, list):
                    compacted[compacted_key] = [self._compact_term(v, context) for v in value]
                else:
                    compacted[compacted_key] = value
            else:
                # Recursively compact the value
                compacted[compacted_key] = self._compact_value(value, context)
        
        return compacted
    
    def _compact_term(self, uri: str, context: JSONLDContext) -> str:
        """
        Compact a URI to a term or prefixed form.
        
        Args:
            uri: URI to compact
            context: Context to use for compaction
            
        Returns:
            Compacted term or original URI
        """
        # Already a keyword or blank node
        if uri.startswith("@") or uri.startswith("_:"):
            return uri
        
        # Check if it's a term
        for term, definition in context.terms.items():
            if isinstance(definition, str) and definition == uri:
                return term
            elif isinstance(definition, dict):
                if definition.get("@id") == uri:
                    return term
        
        # Try vocabulary-relative compaction
        if context.vocab and uri.startswith(context.vocab):
            return uri[len(context.vocab):]
        
        # Try prefix compaction
        for prefix, namespace in context.prefixes.items():
            if uri.startswith(namespace):
                local_part = uri[len(namespace):]
                return f"{prefix}:{local_part}"
        
        # Return as-is if no compaction possible
        return uri
