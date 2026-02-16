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


class TestExpandedVocabularies:
    """Test new vocabulary types added in Path C."""
    
    def test_all_vocabulary_types_defined(self):
        """Test that all 14 vocabulary types are defined."""
        # GIVEN the VocabularyType enum
        # WHEN checking count
        vocab_types = [v for v in VocabularyType if v != VocabularyType.CUSTOM]
        
        # THEN should have at least 13 vocabularies (excluding CUSTOM)
        assert len(vocab_types) >= 13
    
    def test_rdf_vocabulary(self):
        """Test RDF vocabulary context expansion."""
        # GIVEN an expander with RDF vocabulary
        expander = ContextExpander()
        context = JSONLDContext(vocab=VocabularyType.RDF.value)
        
        # WHEN expanding a term
        term = expander._expand_term("type", context)
        
        # THEN it should use RDF namespace
        assert term == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    
    def test_rdfs_vocabulary(self):
        """Test RDFS vocabulary context expansion."""
        # GIVEN an expander with RDFS vocabulary
        expander = ContextExpander()
        context = JSONLDContext(vocab=VocabularyType.RDFS.value)
        
        # WHEN expanding a term
        term = expander._expand_term("label", context)
        
        # THEN it should use RDFS namespace
        assert term == "http://www.w3.org/2000/01/rdf-schema#label"
    
    def test_owl_vocabulary(self):
        """Test OWL vocabulary context expansion."""
        # GIVEN an expander with OWL vocabulary
        expander = ContextExpander()
        context = JSONLDContext(vocab=VocabularyType.OWL.value)
        
        # WHEN expanding a term
        term = expander._expand_term("Class", context)
        
        # THEN it should use OWL namespace
        assert term == "http://www.w3.org/2002/07/owl#Class"
    
    def test_prov_vocabulary(self):
        """Test PROV (provenance) vocabulary."""
        # GIVEN an expander with PROV vocabulary
        expander = ContextExpander()
        context = JSONLDContext(vocab=VocabularyType.PROV.value)
        
        # WHEN expanding a term
        term = expander._expand_term("wasGeneratedBy", context)
        
        # THEN it should use PROV namespace
        assert term == "http://www.w3.org/ns/prov#wasGeneratedBy"
    
    def test_org_vocabulary(self):
        """Test ORG vocabulary for organizations."""
        # GIVEN an expander with ORG vocabulary
        expander = ContextExpander()
        context = JSONLDContext(vocab=VocabularyType.ORG.value)
        
        # WHEN expanding a term
        term = expander._expand_term("Organization", context)
        
        # THEN it should use ORG namespace
        assert term == "http://www.w3.org/ns/org#Organization"
    
    def test_vcard_vocabulary(self):
        """Test VCARD vocabulary for contact information."""
        # GIVEN an expander with VCARD vocabulary
        expander = ContextExpander()
        context = JSONLDContext(vocab=VocabularyType.VCARD.value)
        
        # WHEN expanding a term
        term = expander._expand_term("email", context)
        
        # THEN it should use VCARD namespace
        assert term == "http://www.w3.org/2006/vcard/ns#email"
    
    def test_dcat_vocabulary(self):
        """Test DCAT vocabulary for datasets."""
        # GIVEN an expander with DCAT vocabulary
        expander = ContextExpander()
        context = JSONLDContext(vocab=VocabularyType.DCAT.value)
        
        # WHEN expanding a term
        term = expander._expand_term("Dataset", context)
        
        # THEN it should use DCAT namespace
        assert term == "http://www.w3.org/ns/dcat#Dataset"
    
    def test_time_vocabulary(self):
        """Test TIME vocabulary for temporal information."""
        # GIVEN an expander with TIME vocabulary
        expander = ContextExpander()
        context = JSONLDContext(vocab=VocabularyType.TIME.value)
        
        # WHEN expanding a term
        term = expander._expand_term("Instant", context)
        
        # THEN it should use TIME namespace
        assert term == "http://www.w3.org/2006/time#Instant"
    
    def test_geo_vocabulary(self):
        """Test GEO vocabulary for geographic information."""
        # GIVEN an expander with GEO vocabulary
        expander = ContextExpander()
        context = JSONLDContext(vocab=VocabularyType.GEO.value)
        
        # WHEN expanding a term
        term = expander._expand_term("lat", context)
        
        # THEN it should use GEO namespace
        assert term == "http://www.w3.org/2003/01/geo/wgs84_pos#lat"
    
    def test_mixed_vocabulary_context(self):
        """Test using multiple vocabularies with prefixes."""
        # GIVEN a context with multiple vocabulary prefixes
        context = JSONLDContext(
            vocab=VocabularyType.SCHEMA_ORG.value,
            prefixes={
                "rdf": VocabularyType.RDF.value,
                "rdfs": VocabularyType.RDFS.value,
                "owl": VocabularyType.OWL.value,
                "prov": VocabularyType.PROV.value,
                "geo": VocabularyType.GEO.value
            }
        )
        expander = ContextExpander()
        
        # WHEN expanding prefixed terms
        rdf_type = expander._expand_term("rdf:type", context)
        rdfs_label = expander._expand_term("rdfs:label", context)
        geo_lat = expander._expand_term("geo:lat", context)
        
        # THEN all should be properly expanded
        assert rdf_type == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        assert rdfs_label == "http://www.w3.org/2000/01/rdf-schema#label"
        assert geo_lat == "http://www.w3.org/2003/01/geo/wgs84_pos#lat"
    
    def test_jsonld_with_prov_vocabulary(self):
        """Test converting JSON-LD with provenance vocabulary."""
        # GIVEN a translator and JSON-LD with PROV vocabulary
        translator = JSONLDTranslator()
        jsonld = {
            "@context": {
                "@vocab": VocabularyType.PROV.value
            },
            "@type": "Entity",
            "wasGeneratedBy": {
                "@type": "Activity",
                "startedAtTime": "2024-01-01T00:00:00Z"
            }
        }
        
        # WHEN converting to IPLD
        graph = translator.jsonld_to_ipld(jsonld)
        
        # THEN should have entities and relationships
        assert len(graph.entities) == 2
        assert len(graph.relationships) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
