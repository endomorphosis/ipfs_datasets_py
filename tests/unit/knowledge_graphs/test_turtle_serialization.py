"""
Tests for Turtle RDF Serialization

This module provides tests for RDF Turtle serialization functionality.
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.jsonld import (
    TurtleSerializer,
    TurtleParser,
    jsonld_to_turtle,
    turtle_to_jsonld,
)


class TestTurtleSerializer:
    """Test Turtle RDF serialization."""
    
    def test_simple_triple_serialization(self):
        """Test serializing simple triples."""
        # GIVEN a serializer and simple triples
        serializer = TurtleSerializer()
        triples = [
            ("http://example.org/alice", "http://xmlns.com/foaf/0.1/name", "Alice"),
            ("http://example.org/alice", "http://xmlns.com/foaf/0.1/age", 30),
        ]
        
        # WHEN serializing
        turtle = serializer.serialize(triples)
        
        # THEN should contain prefix declarations and triples
        assert "@prefix" in turtle
        assert "foaf:" in turtle
        assert "Alice" in turtle
        assert "30" in turtle
    
    def test_blank_node_serialization(self):
        """Test serializing blank nodes."""
        # GIVEN triples with blank nodes
        serializer = TurtleSerializer()
        triples = [
            ("_:alice", "http://xmlns.com/foaf/0.1/name", "Alice"),
            ("_:alice", "http://xmlns.com/foaf/0.1/knows", "_:bob"),
        ]
        
        # WHEN serializing
        turtle = serializer.serialize(triples)
        
        # THEN blank nodes should be preserved
        assert "_:alice" in turtle
        assert "_:bob" in turtle
    
    def test_custom_prefixes(self):
        """Test using custom prefixes."""
        # GIVEN custom prefixes
        serializer = TurtleSerializer()
        custom_prefixes = {
            "ex": "http://example.org/"
        }
        triples = [
            ("http://example.org/alice", "http://example.org/knows", "http://example.org/bob"),
        ]
        
        # WHEN serializing with custom prefixes
        turtle = serializer.serialize(triples, prefixes=custom_prefixes)
        
        # THEN should use custom prefix
        assert "@prefix ex:" in turtle
        assert "ex:alice" in turtle or "ex:knows" in turtle or "ex:bob" in turtle
    
    def test_base_uri(self):
        """Test base URI declaration."""
        # GIVEN a base URI
        serializer = TurtleSerializer()
        triples = [
            ("http://example.org/alice", "http://xmlns.com/foaf/0.1/name", "Alice"),
        ]
        
        # WHEN serializing with base URI
        turtle = serializer.serialize(triples, base_uri="http://example.org/")
        
        # THEN should include base declaration
        assert "@base" in turtle
    
    def test_boolean_literal(self):
        """Test serializing boolean literals."""
        # GIVEN triples with boolean
        serializer = TurtleSerializer()
        triples = [
            ("http://example.org/alice", "http://example.org/verified", True),
            ("http://example.org/bob", "http://example.org/verified", False),
        ]
        
        # WHEN serializing
        turtle = serializer.serialize(triples)
        
        # THEN should have true/false
        assert "true" in turtle
        assert "false" in turtle
    
    def test_numeric_literals(self):
        """Test serializing numeric literals."""
        # GIVEN triples with numbers
        serializer = TurtleSerializer()
        triples = [
            ("http://example.org/alice", "http://example.org/age", 30),
            ("http://example.org/alice", "http://example.org/height", 1.75),
        ]
        
        # WHEN serializing
        turtle = serializer.serialize(triples)
        
        # THEN should have numbers
        assert "30" in turtle
        assert "1.75" in turtle
    
    def test_grouped_predicates(self):
        """Test grouping predicates for same subject."""
        # GIVEN multiple predicates for one subject
        serializer = TurtleSerializer()
        triples = [
            ("http://example.org/alice", "http://xmlns.com/foaf/0.1/name", "Alice"),
            ("http://example.org/alice", "http://xmlns.com/foaf/0.1/age", 30),
            ("http://example.org/alice", "http://xmlns.com/foaf/0.1/email", "alice@example.com"),
        ]
        
        # WHEN serializing
        turtle = serializer.serialize(triples)
        
        # THEN predicates should be grouped with semicolons
        assert ";" in turtle
        lines = turtle.split("\n")
        alice_lines = [l for l in lines if "alice" in l.lower()]
        # Should have one subject declaration and multiple predicates
        assert len([l for l in alice_lines if l.strip().endswith(".")]) == 1


class TestTurtleParser:
    """Test Turtle RDF parsing."""
    
    def test_parse_simple_triple(self):
        """Test parsing simple triple."""
        # GIVEN simple Turtle text
        parser = TurtleParser()
        turtle = """
        @prefix foaf: <http://xmlns.com/foaf/0.1/> .
        
        <http://example.org/alice> foaf:name "Alice" .
        """
        
        # WHEN parsing
        triples, prefixes = parser.parse(turtle)
        
        # THEN should extract triple and prefix
        assert len(triples) >= 1
        assert "foaf" in prefixes
        assert prefixes["foaf"] == "http://xmlns.com/foaf/0.1/"
    
    def test_parse_prefix_declarations(self):
        """Test parsing multiple prefix declarations."""
        # GIVEN Turtle with multiple prefixes
        parser = TurtleParser()
        turtle = """
        @prefix foaf: <http://xmlns.com/foaf/0.1/> .
        @prefix schema: <https://schema.org/> .
        @prefix ex: <http://example.org/> .
        """
        
        # WHEN parsing
        _, prefixes = parser.parse(turtle)
        
        # THEN all prefixes should be extracted
        assert len(prefixes) >= 3
        assert "foaf" in prefixes
        assert "schema" in prefixes
        assert "ex" in prefixes
    
    def test_parse_base_uri(self):
        """Test parsing base URI declaration."""
        # GIVEN Turtle with base URI
        parser = TurtleParser()
        turtle = """
        @base <http://example.org/> .
        @prefix foaf: <http://xmlns.com/foaf/0.1/> .
        
        <alice> foaf:name "Alice" .
        """
        
        # WHEN parsing
        triples, prefixes = parser.parse(turtle)
        
        # THEN base URI should be set
        assert parser.base_uri == "http://example.org/"
    
    def test_parse_blank_nodes(self):
        """Test parsing blank nodes."""
        # GIVEN Turtle with blank nodes
        parser = TurtleParser()
        turtle = """
        @prefix foaf: <http://xmlns.com/foaf/0.1/> .
        
        _:alice foaf:name "Alice" .
        _:alice foaf:knows _:bob .
        """
        
        # WHEN parsing
        triples, _ = parser.parse(turtle)
        
        # THEN should extract blank node triples
        assert len(triples) >= 2
        subjects = [t[0] for t in triples]
        assert any(s.startswith("_:") for s in subjects)
    
    def test_parse_multiple_objects(self):
        """Test parsing multiple objects with comma."""
        # GIVEN Turtle with multiple objects
        parser = TurtleParser()
        turtle = """
        @prefix foaf: <http://xmlns.com/foaf/0.1/> .
        
        <http://example.org/alice> foaf:knows <http://example.org/bob>, <http://example.org/charlie> .
        """
        
        # WHEN parsing
        triples, _ = parser.parse(turtle)
        
        # THEN should extract multiple triples
        knows_triples = [t for t in triples if "knows" in t[1]]
        assert len(knows_triples) >= 2
    
    def test_parse_predicate_object_lists(self):
        """Test parsing predicate-object lists with semicolon."""
        # GIVEN Turtle with semicolon lists
        parser = TurtleParser()
        turtle = """
        @prefix foaf: <http://xmlns.com/foaf/0.1/> .
        
        <http://example.org/alice>
            foaf:name "Alice" ;
            foaf:age 30 .
        """
        
        # WHEN parsing
        triples, _ = parser.parse(turtle)
        
        # THEN should extract multiple triples for same subject
        assert len(triples) >= 2
        subjects = [t[0] for t in triples]
        assert len(set(subjects)) == 1  # Same subject for all
    
    def test_parse_numeric_literals(self):
        """Test parsing numeric literals."""
        # GIVEN Turtle with numbers
        parser = TurtleParser()
        turtle = """
        @prefix ex: <http://example.org/> .
        
        <http://example.org/alice> ex:age 30 .
        <http://example.org/alice> ex:height 1.75 .
        """
        
        # WHEN parsing
        triples, _ = parser.parse(turtle)
        
        # THEN should parse numbers correctly
        objects = [t[2] for t in triples]
        assert 30 in objects or "30" in objects
        assert 1.75 in objects or "1.75" in objects
    
    def test_parse_boolean_literals(self):
        """Test parsing boolean literals."""
        # GIVEN Turtle with booleans
        parser = TurtleParser()
        turtle = """
        @prefix ex: <http://example.org/> .
        
        <http://example.org/alice> ex:verified true .
        <http://example.org/bob> ex:verified false .
        """
        
        # WHEN parsing
        triples, _ = parser.parse(turtle)
        
        # THEN should parse booleans
        objects = [t[2] for t in triples]
        assert True in objects
        assert False in objects


class TestTurtleRoundtrip:
    """Test roundtrip conversion between Turtle and triples."""
    
    def test_roundtrip_simple_triples(self):
        """Test roundtrip with simple triples."""
        # GIVEN original triples
        serializer = TurtleSerializer()
        parser = TurtleParser()
        
        original_triples = [
            ("http://example.org/alice", "http://xmlns.com/foaf/0.1/name", "Alice"),
            ("http://example.org/alice", "http://xmlns.com/foaf/0.1/age", 30),
        ]
        
        # WHEN doing roundtrip
        turtle = serializer.serialize(original_triples)
        recovered_triples, _ = parser.parse(turtle)
        
        # THEN essential data should be preserved
        assert len(recovered_triples) >= 2
        
        # Check that subject and predicates are preserved
        subjects = [t[0] for t in recovered_triples]
        predicates = [t[1] for t in recovered_triples]
        assert any("alice" in s for s in subjects)
        assert any("name" in p for p in predicates)
    
    def test_roundtrip_with_blank_nodes(self):
        """Test roundtrip preserves blank nodes."""
        # GIVEN triples with blank nodes
        serializer = TurtleSerializer()
        parser = TurtleParser()
        
        original_triples = [
            ("_:alice", "http://xmlns.com/foaf/0.1/name", "Alice"),
            ("_:alice", "http://xmlns.com/foaf/0.1/knows", "_:bob"),
        ]
        
        # WHEN doing roundtrip
        turtle = serializer.serialize(original_triples)
        recovered_triples, _ = parser.parse(turtle)
        
        # THEN blank nodes should be preserved
        assert len(recovered_triples) >= 2
        subjects = [t[0] for t in recovered_triples]
        assert any(s.startswith("_:") for s in subjects)


class TestJSONLDTurtleConversion:
    """Test conversion between JSON-LD and Turtle."""
    
    def test_jsonld_to_turtle_simple(self):
        """Test converting simple JSON-LD to Turtle."""
        # GIVEN simple JSON-LD
        jsonld = {
            "@context": "https://schema.org/",
            "@type": "Person",
            "name": "Alice",
            "age": 30
        }
        
        # WHEN converting to Turtle
        turtle = jsonld_to_turtle(jsonld)
        
        # THEN should produce valid Turtle
        assert "@prefix" in turtle
        assert "Person" in turtle or "schema:Person" in turtle
        assert "Alice" in turtle
        assert "30" in turtle
    
    def test_jsonld_to_turtle_with_relationships(self):
        """Test converting JSON-LD with relationships to Turtle."""
        # GIVEN JSON-LD with relationship
        jsonld = {
            "@context": "https://schema.org/",
            "@type": "Person",
            "name": "Alice",
            "knows": {
                "@type": "Person",
                "name": "Bob"
            }
        }
        
        # WHEN converting to Turtle
        turtle = jsonld_to_turtle(jsonld)
        
        # THEN should include both entities and relationship
        assert "Alice" in turtle
        assert "Bob" in turtle
        assert "knows" in turtle or "schema:knows" in turtle
    
    def test_turtle_to_jsonld_simple(self):
        """Test converting simple Turtle to JSON-LD."""
        # GIVEN simple Turtle
        turtle = """
        @prefix schema: <https://schema.org/> .
        
        <http://example.org/alice>
            a schema:Person ;
            schema:name "Alice" ;
            schema:age 30 .
        """
        
        # WHEN converting to JSON-LD
        jsonld = turtle_to_jsonld(turtle)
        
        # THEN should produce valid JSON-LD
        assert "@type" in jsonld or "@graph" in jsonld
        # Check that data is present somewhere in the structure
        assert "Alice" in str(jsonld)
    
    def test_jsonld_turtle_roundtrip(self):
        """Test roundtrip JSON-LD → Turtle → JSON-LD."""
        # GIVEN original JSON-LD
        original = {
            "@context": "https://schema.org/",
            "@type": "Person",
            "name": "Alice",
            "age": 30
        }
        
        # WHEN doing roundtrip
        turtle = jsonld_to_turtle(original)
        recovered = turtle_to_jsonld(turtle)
        
        # THEN essential data should be preserved
        # The structure may differ but data should be present
        recovered_str = str(recovered)
        assert "Alice" in recovered_str
        assert "Person" in recovered_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
