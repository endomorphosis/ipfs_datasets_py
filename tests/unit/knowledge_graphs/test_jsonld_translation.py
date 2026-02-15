"""
Tests for JSON-LD Translation (Phase 4)

This module provides comprehensive tests for JSON-LD ↔ IPLD translation.
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.jsonld import (
    JSONLDTranslator,
    ContextExpander,
    ContextCompactor,
    JSONLDContext,
    IPLDGraph,
    TranslationOptions,
    VocabularyType,
)


class TestJSONLDContext:
    """Test JSON-LD context parsing and generation."""
    
    def test_simple_context_from_string(self):
        """Test creating context from simple string."""
        # GIVEN a simple context string
        context_str = "https://schema.org/"
        
        # WHEN creating context from string
        context = JSONLDContext.from_dict(context_str)
        
        # THEN vocab should be set
        assert context.vocab == "https://schema.org/"
        assert context.base_uri is None
        assert len(context.prefixes) == 0
    
    def test_complex_context_from_dict(self):
        """Test creating context from complex dictionary."""
        # GIVEN a complex context dictionary
        context_dict = {
            "@vocab": "https://schema.org/",
            "@base": "http://example.org/",
            "foaf": "http://xmlns.com/foaf/0.1/",
            "dc": "http://purl.org/dc/terms/"
        }
        
        # WHEN creating context from dict
        context = JSONLDContext.from_dict(context_dict)
        
        # THEN all fields should be parsed
        assert context.vocab == "https://schema.org/"
        assert context.base_uri == "http://example.org/"
        assert context.prefixes["foaf"] == "http://xmlns.com/foaf/0.1/"
        assert context.prefixes["dc"] == "http://purl.org/dc/terms/"
    
    def test_context_array(self):
        """Test merging multiple contexts from array."""
        # GIVEN an array of contexts
        context_array = [
            "https://schema.org/",
            {"foaf": "http://xmlns.com/foaf/0.1/"}
        ]
        
        # WHEN creating context from array
        context = JSONLDContext.from_dict(context_array)
        
        # THEN contexts should be merged
        assert context.vocab == "https://schema.org/"
        assert context.prefixes["foaf"] == "http://xmlns.com/foaf/0.1/"
    
    def test_context_to_dict(self):
        """Test converting context back to dictionary."""
        # GIVEN a context with various fields
        context = JSONLDContext(
            vocab="https://schema.org/",
            base_uri="http://example.org/",
            prefixes={"foaf": "http://xmlns.com/foaf/0.1/"}
        )
        
        # WHEN converting to dict
        result = context.to_dict()
        
        # THEN all fields should be present
        assert result["@vocab"] == "https://schema.org/"
        assert result["@base"] == "http://example.org/"
        assert result["foaf"] == "http://xmlns.com/foaf/0.1/"


class TestContextExpander:
    """Test JSON-LD context expansion."""
    
    def test_expand_simple_vocabulary(self):
        """Test expanding terms with vocabulary."""
        # GIVEN an expander and simple data
        expander = ContextExpander()
        context = JSONLDContext(vocab="https://schema.org/")
        data = {
            "@context": "https://schema.org/",
            "@type": "Person",
            "name": "Alice"
        }
        
        # WHEN expanding
        result = expander.expand(data, context)
        
        # THEN terms should be expanded
        assert result["@type"] == "https://schema.org/Person"
        assert "name" in result or "https://schema.org/name" in result
    
    def test_expand_with_prefixes(self):
        """Test expanding terms with prefixes."""
        # GIVEN an expander with prefix context
        expander = ContextExpander()
        context = JSONLDContext(
            prefixes={"foaf": "http://xmlns.com/foaf/0.1/"}
        )
        
        # WHEN expanding prefixed term
        term = expander._expand_term("foaf:name", context)
        
        # THEN it should be expanded
        assert term == "http://xmlns.com/foaf/0.1/name"
    
    def test_expand_preserves_uris(self):
        """Test that existing URIs are preserved."""
        # GIVEN an expander and URI
        expander = ContextExpander()
        context = JSONLDContext(vocab="https://schema.org/")
        
        # WHEN expanding a URI
        uri = "http://example.org/thing"
        result = expander._expand_term(uri, context)
        
        # THEN it should be unchanged
        assert result == uri


class TestContextCompactor:
    """Test JSON-LD context compaction."""
    
    def test_compact_with_vocabulary(self):
        """Test compacting URIs with vocabulary."""
        # GIVEN a compactor and expanded data
        compactor = ContextCompactor()
        context = JSONLDContext(vocab="https://schema.org/")
        
        # WHEN compacting a URI
        uri = "https://schema.org/Person"
        result = compactor._compact_term(uri, context)
        
        # THEN it should be compacted
        assert result == "Person"
    
    def test_compact_with_prefix(self):
        """Test compacting URIs with prefix."""
        # GIVEN a compactor with prefix context
        compactor = ContextCompactor()
        context = JSONLDContext(
            prefixes={"foaf": "http://xmlns.com/foaf/0.1/"}
        )
        
        # WHEN compacting a URI
        uri = "http://xmlns.com/foaf/0.1/knows"
        result = compactor._compact_term(uri, context)
        
        # THEN it should use prefix
        assert result == "foaf:knows"


class TestJSONLDTranslator:
    """Test JSON-LD to IPLD translation."""
    
    def test_simple_person_to_ipld(self):
        """Test converting simple Person to IPLD."""
        # GIVEN a translator and simple JSON-LD
        translator = JSONLDTranslator()
        jsonld = {
            "@context": "https://schema.org/",
            "@type": "Person",
            "name": "Alice Smith",
            "age": 30
        }
        
        # WHEN converting to IPLD
        graph = translator.jsonld_to_ipld(jsonld)
        
        # THEN graph should have one entity
        assert len(graph.entities) == 1
        entity = graph.entities[0]
        assert entity["type"] == "Person" or entity["type"] == "https://schema.org/Person"
        # Properties may be expanded or not depending on options
        props = entity["properties"]
        assert "name" in props or "https://schema.org/name" in props
        name_value = props.get("name") or props.get("https://schema.org/name")
        assert name_value == "Alice Smith"
        assert "age" in props or "https://schema.org/age" in props
        age_value = props.get("age") or props.get("https://schema.org/age")
        assert age_value == 30
    
    def test_person_with_relationship(self):
        """Test converting Person with knows relationship."""
        # GIVEN a translator and JSON-LD with relationship
        translator = JSONLDTranslator()
        jsonld = {
            "@context": "https://schema.org/",
            "@type": "Person",
            "name": "Alice",
            "knows": {
                "@type": "Person",
                "name": "Bob"
            }
        }
        
        # WHEN converting to IPLD
        graph = translator.jsonld_to_ipld(jsonld)
        
        # THEN graph should have two entities and one relationship
        assert len(graph.entities) == 2
        assert len(graph.relationships) == 1
        
        # Check relationship
        rel = graph.relationships[0]
        assert rel["type"] == "knows" or rel["type"] == "https://schema.org/knows"
        assert "source" in rel
        assert "target" in rel
    
    def test_multiple_relationships(self):
        """Test converting entity with multiple relationships."""
        # GIVEN JSON-LD with array of relationships
        translator = JSONLDTranslator()
        jsonld = {
            "@context": "https://schema.org/",
            "@type": "Person",
            "name": "Alice",
            "knows": [
                {"@type": "Person", "name": "Bob"},
                {"@type": "Person", "name": "Charlie"}
            ]
        }
        
        # WHEN converting to IPLD
        graph = translator.jsonld_to_ipld(jsonld)
        
        # THEN should have 3 entities and 2 relationships
        assert len(graph.entities) == 3
        assert len(graph.relationships) == 2
    
    def test_jsonld_graph_container(self):
        """Test converting @graph container."""
        # GIVEN JSON-LD with @graph
        translator = JSONLDTranslator()
        jsonld = {
            "@context": "https://schema.org/",
            "@graph": [
                {"@type": "Person", "name": "Alice"},
                {"@type": "Person", "name": "Bob"}
            ]
        }
        
        # WHEN converting to IPLD
        graph = translator.jsonld_to_ipld(jsonld)
        
        # THEN should have 2 entities
        assert len(graph.entities) == 2
    
    def test_blank_nodes(self):
        """Test handling blank nodes."""
        # GIVEN JSON-LD with blank nodes
        translator = JSONLDTranslator(
            TranslationOptions(preserve_blank_nodes=True)
        )
        jsonld = {
            "@context": "https://schema.org/",
            "@id": "_:alice",
            "@type": "Person",
            "name": "Alice"
        }
        
        # WHEN converting to IPLD
        graph = translator.jsonld_to_ipld(jsonld)
        
        # THEN blank node ID should be preserved
        assert len(graph.entities) == 1
        entity = graph.entities[0]
        assert entity["id"].startswith("_:")
    
    def test_ipld_to_jsonld_simple(self):
        """Test converting simple IPLD back to JSON-LD."""
        # GIVEN an IPLD graph
        graph = IPLDGraph(
            entities=[
                {
                    "id": "entity_1",
                    "type": "Person",
                    "properties": {
                        "name": "Alice",
                        "age": 30
                    }
                }
            ],
            metadata={"context": {"@vocab": "https://schema.org/"}}
        )
        translator = JSONLDTranslator()
        
        # WHEN converting to JSON-LD
        result = translator.ipld_to_jsonld(graph)
        
        # THEN should have correct structure
        assert "@type" in result
        assert result["@type"] == "Person"
        assert result["name"] == "Alice"
        assert result["age"] == 30
    
    def test_ipld_to_jsonld_with_relationships(self):
        """Test converting IPLD with relationships to JSON-LD."""
        # GIVEN an IPLD graph with relationships
        graph = IPLDGraph(
            entities=[
                {
                    "id": "entity_1",
                    "type": "Person",
                    "properties": {"name": "Alice"}
                },
                {
                    "id": "entity_2",
                    "type": "Person",
                    "properties": {"name": "Bob"}
                }
            ],
            relationships=[
                {
                    "type": "knows",
                    "source": "entity_1",
                    "target": "entity_2",
                    "properties": {}
                }
            ],
            metadata={"context": {"@vocab": "https://schema.org/"}}
        )
        translator = JSONLDTranslator()
        
        # WHEN converting to JSON-LD
        result = translator.ipld_to_jsonld(graph)
        
        # THEN should have @graph with relationships
        assert "@graph" in result
        nodes = result["@graph"]
        assert len(nodes) == 2
        
        # Find Alice and check she knows Bob
        alice = next(n for n in nodes if n["name"] == "Alice")
        assert "knows" in alice
    
    def test_roundtrip_conversion(self):
        """Test roundtrip JSON-LD → IPLD → JSON-LD preserves data."""
        # GIVEN original JSON-LD
        translator = JSONLDTranslator()
        original = {
            "@context": "https://schema.org/",
            "@type": "Person",
            "name": "Alice",
            "age": 30
        }
        
        # WHEN doing roundtrip conversion
        graph = translator.jsonld_to_ipld(original)
        recovered = translator.ipld_to_jsonld(graph)
        
        # THEN essential data should be preserved
        assert recovered["@type"] == original["@type"] or \
               recovered["@type"] == "https://schema.org/Person"
        # Properties may be expanded - check both forms
        name_value = recovered.get("name") or recovered.get("https://schema.org/name")
        age_value = recovered.get("age") or recovered.get("https://schema.org/age")
        assert name_value == original["name"]
        assert age_value == original["age"]
    
    def test_roundtrip_with_relationships(self):
        """Test roundtrip preserves relationships."""
        # GIVEN JSON-LD with relationships
        translator = JSONLDTranslator()
        original = {
            "@context": "https://schema.org/",
            "@type": "Person",
            "name": "Alice",
            "knows": {
                "@type": "Person",
                "name": "Bob"
            }
        }
        
        # WHEN doing roundtrip
        graph = translator.jsonld_to_ipld(original)
        recovered = translator.ipld_to_jsonld(graph)
        
        # THEN relationships should be preserved
        # Handle both single node and @graph output
        if "@graph" in recovered:
            nodes = recovered["@graph"]
            # Check both compacted and expanded forms
            alice = next(
                (n for n in nodes 
                 if n.get("name") == "Alice" or 
                    n.get("https://schema.org/name") == "Alice"),
                None
            )
            assert alice is not None
            assert "knows" in alice or "https://schema.org/knows" in alice
        else:
            assert "knows" in recovered or "https://schema.org/knows" in recovered


class TestIPLDGraph:
    """Test IPLD graph data structure."""
    
    def test_graph_to_dict(self):
        """Test converting graph to dictionary."""
        # GIVEN an IPLD graph
        graph = IPLDGraph(
            entities=[{"id": "1", "type": "Person"}],
            relationships=[{"type": "knows", "source": "1", "target": "2"}],
            metadata={"version": "1.0"}
        )
        
        # WHEN converting to dict
        result = graph.to_dict()
        
        # THEN all fields should be present
        assert "entities" in result
        assert "relationships" in result
        assert "metadata" in result
        assert result["metadata"]["version"] == "1.0"
    
    def test_graph_from_dict(self):
        """Test creating graph from dictionary."""
        # GIVEN a dictionary representation
        data = {
            "entities": [{"id": "1", "type": "Person"}],
            "relationships": [{"type": "knows", "source": "1", "target": "2"}],
            "metadata": {"version": "1.0"}
        }
        
        # WHEN creating graph from dict
        graph = IPLDGraph.from_dict(data)
        
        # THEN all fields should be populated
        assert len(graph.entities) == 1
        assert len(graph.relationships) == 1
        assert graph.metadata["version"] == "1.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
