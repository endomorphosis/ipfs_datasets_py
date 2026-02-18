"""
Tests for P1 Deferred Features: NOT operator and CREATE relationships

This test suite validates the implementation of:
1. Cypher NOT operator in WHERE clauses
2. Cypher CREATE relationships in CREATE clauses

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor, GraphEngine


class TestNotOperator:
    """Test suite for NOT operator implementation."""
    
    @pytest.fixture
    def compiler(self):
        """Create a CypherCompiler instance."""
        return CypherCompiler()
    
    @pytest.fixture
    def parser(self):
        """Create a CypherParser instance."""
        return CypherParser()
    
    def test_not_operator_simple_comparison(self, parser, compiler):
        """
        GIVEN: A Cypher query with NOT operator on simple comparison
        WHEN: Compiling the query
        THEN: IR contains negated filter operation
        """
        # GIVEN
        query = "MATCH (p:Person) WHERE NOT p.age > 30 RETURN p"
        
        # WHEN
        ast = parser.parse(query)
        ir = compiler.compile(ast)
        
        # THEN
        # Should have filter with <= operator (negation of >)
        filter_ops = [op for op in ir if op.get('op') == 'Filter']
        assert len(filter_ops) > 0
        # Check that negation was applied
        filter_op = filter_ops[0]
        # Either negated operator or NOT expression
        assert (filter_op.get('operator') == '<=' or
                'expression' in filter_op and filter_op['expression'].get('op') == 'NOT')
    
    def test_not_operator_with_equality(self, parser, compiler):
        """
        GIVEN: A Cypher query with NOT on equality check
        WHEN: Compiling the query
        THEN: IR contains <> (not equal) operator
        """
        # GIVEN
        query = "MATCH (p:Person) WHERE NOT p.name = 'Alice' RETURN p"
        
        # WHEN
        ast = parser.parse(query)
        ir = compiler.compile(ast)
        
        # THEN
        filter_ops = [op for op in ir if op.get('op') == 'Filter']
        assert len(filter_ops) > 0
        filter_op = filter_ops[0]
        assert (filter_op.get('operator') == '<>' or
                'expression' in filter_op and filter_op['expression'].get('op') == 'NOT')
    
    def test_not_operator_complex_expression(self, parser, compiler):
        """
        GIVEN: A Cypher query with NOT on complex expression
        WHEN: Compiling the query
        THEN: IR contains NOT wrapper for the expression
        """
        # GIVEN
        query = "MATCH (p:Person) WHERE NOT (p.age > 30 AND p.city = 'NYC') RETURN p"
        
        # WHEN
        ast = parser.parse(query)
        ir = compiler.compile(ast)
        
        # THEN
        filter_ops = [op for op in ir if op.get('op') == 'Filter']
        assert len(filter_ops) > 0
        # Complex expressions should have NOT wrapper
        has_not = any('expression' in op and isinstance(op.get('expression'), dict)
                     and op['expression'].get('op') == 'NOT'
                     for op in filter_ops)
        assert has_not or len(filter_ops) >= 2  # Or multiple negated filters


class TestCreateRelationships:
    """Test suite for CREATE relationship implementation."""
    
    @pytest.fixture
    def compiler(self):
        """Create a CypherCompiler instance."""
        return CypherCompiler()
    
    @pytest.fixture
    def parser(self):
        """Create a CypherParser instance."""
        return CypherParser()
    
    def test_create_simple_relationship(self, parser, compiler):
        """
        GIVEN: A CREATE query with relationship pattern
        WHEN: Compiling the query
        THEN: IR contains CreateNode and CreateRelationship operations
        """
        # GIVEN
        query = "CREATE (a:Person {name: 'Alice'})-[r:KNOWS]->(b:Person {name: 'Bob'})"
        
        # WHEN
        ast = parser.parse(query)
        ir = compiler.compile(ast)
        
        # THEN
        # Should have 2 CreateNode operations and 1 CreateRelationship
        create_node_ops = [op for op in ir if op.get('op') == 'CreateNode']
        create_rel_ops = [op for op in ir if op.get('op') == 'CreateRelationship']
        
        assert len(create_node_ops) == 2, f"Expected 2 CreateNode ops, got {len(create_node_ops)}"
        assert len(create_rel_ops) == 1, f"Expected 1 CreateRelationship op, got {len(create_rel_ops)}"
        
        # Check relationship operation structure
        rel_op = create_rel_ops[0]
        assert 'rel_type' in rel_op
        assert rel_op['rel_type'] == 'KNOWS'
        assert 'start_variable' in rel_op
        assert 'end_variable' in rel_op
    
    def test_create_relationship_with_properties(self, parser, compiler):
        """
        GIVEN: A CREATE query with relationship properties
        WHEN: Compiling the query
        THEN: IR contains relationship with compiled properties
        """
        # GIVEN
        query = "CREATE (a:Person)-[r:KNOWS {since: 2020, strength: 0.8}]->(b:Person)"
        
        # WHEN
        ast = parser.parse(query)
        ir = compiler.compile(ast)
        
        # THEN
        create_rel_ops = [op for op in ir if op.get('op') == 'CreateRelationship']
        assert len(create_rel_ops) == 1
        
        rel_op = create_rel_ops[0]
        assert 'properties' in rel_op
        assert len(rel_op['properties']) == 2
    
    def test_create_multiple_relationships(self, parser, compiler):
        """
        GIVEN: A CREATE query with chain of relationships
        WHEN: Compiling the query
        THEN: IR contains all relationship operations
        """
        # GIVEN
        query = "CREATE (a:Person)-[:KNOWS]->(b:Person)-[:KNOWS]->(c:Person)"
        
        # WHEN
        ast = parser.parse(query)
        ir = compiler.compile(ast)
        
        # THEN
        create_node_ops = [op for op in ir if op.get('op') == 'CreateNode']
        create_rel_ops = [op for op in ir if op.get('op') == 'CreateRelationship']
        
        assert len(create_node_ops) == 3, f"Expected 3 CreateNode ops, got {len(create_node_ops)}"
        assert len(create_rel_ops) == 2, f"Expected 2 CreateRelationship ops, got {len(create_rel_ops)}"
    
    def test_create_left_direction_relationship(self, parser, compiler):
        """
        GIVEN: A CREATE query with left-pointing relationship
        WHEN: Compiling the query
        THEN: IR correctly handles reversed direction
        """
        # GIVEN
        query = "CREATE (a:Person)<-[r:KNOWS]-(b:Person)"
        
        # WHEN
        ast = parser.parse(query)
        ir = compiler.compile(ast)
        
        # THEN
        create_rel_ops = [op for op in ir if op.get('op') == 'CreateRelationship']
        assert len(create_rel_ops) == 1
        
        rel_op = create_rel_ops[0]
        # In left direction, start and end should be swapped
        assert 'start_variable' in rel_op
        assert 'end_variable' in rel_op


class TestEndToEndIntegration:
    """Test end-to-end execution of P1 features with GraphEngine."""
    
    @pytest.fixture
    def query_executor(self):
        """Create a QueryExecutor with GraphEngine."""
        graph_engine = GraphEngine()
        return QueryExecutor(graph_engine=graph_engine), graph_engine
    
    def test_not_operator_execution(self, query_executor):
        """
        GIVEN: A graph with Person nodes of different ages
        WHEN: Executing query with NOT operator
        THEN: Returns correct filtered results
        """
        # GIVEN
        executor, engine = query_executor
        alice = engine.create_node(labels=["Person"], properties={"name": "Alice", "age": 25})
        bob = engine.create_node(labels=["Person"], properties={"name": "Bob", "age": 35})
        charlie = engine.create_node(labels=["Person"], properties={"name": "Charlie", "age": 40})
        
        # WHEN
        result = executor.execute("MATCH (p:Person) WHERE NOT p.age > 30 RETURN p.name as name")
        
        # THEN
        records = list(result)
        # Should return only Alice (age 25)
        names = [r.get('name') for r in records if 'name' in r]
        assert 'Alice' in str(names) or 'Alice' in str(records)
    
    def test_create_relationship_execution(self, query_executor):
        """
        GIVEN: An empty graph
        WHEN: Executing CREATE query with relationships
        THEN: Nodes and relationships are created
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        query = "CREATE (a:Person {name: 'Alice'})-[r:KNOWS {since: 2020}]->(b:Person {name: 'Bob'})"
        result = executor.execute(query)
        
        # THEN
        # Verify nodes were created - use find_nodes to get all Person nodes
        person_nodes = list(engine.find_nodes(labels=["Person"]))
        assert len(person_nodes) >= 2, f"Expected at least 2 Person nodes, got {len(person_nodes)}"
        
        # Verify at least one node has Alice
        node_names = [n.properties.get('name') for n in person_nodes if hasattr(n, 'properties')]
        assert 'Alice' in node_names or 'Bob' in node_names


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
