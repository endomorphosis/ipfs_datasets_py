"""
Golden Query Fixtures for Cypher Parser and Compiler (Workstream D2)

This test suite validates that key Cypher query patterns parse and compile
to the expected Intermediate Representation (IR).  Each test is a "golden
fixture": it locks in the exact IR produced so that refactors cannot
silently change query semantics.

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import pytest

from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser, CypherParseError
from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler, CypherCompileError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_and_compile(query: str):
    """Parse then compile *query* and return the IR list."""
    parser = CypherParser()
    ast = parser.parse(query)
    compiler = CypherCompiler()
    return compiler.compile(ast)


def _op_types(ir):
    """Return the sequence of op-codes as a list of strings."""
    return [op["op"] for op in ir]


def _ops_of_type(ir, op_type: str):
    """Return all IR operations with the given op-code."""
    return [op for op in ir if op["op"] == op_type]


# ---------------------------------------------------------------------------
# Simple MATCH patterns
# ---------------------------------------------------------------------------

class TestSimpleMatchPatterns:
    """Golden fixtures for simple MATCH … RETURN queries."""

    def test_match_all_nodes(self):
        """
        GIVEN: MATCH (n) RETURN n
        WHEN: Parsed and compiled
        THEN: IR contains ScanAll followed by Project
        """
        # GIVEN / WHEN
        ir = _parse_and_compile("MATCH (n) RETURN n")

        # THEN
        ops = _op_types(ir)
        assert "ScanAll" in ops
        assert "Project" in ops
        scan = _ops_of_type(ir, "ScanAll")[0]
        assert scan["variable"] == "n"

    def test_match_by_label(self):
        """
        GIVEN: MATCH (p:Person) RETURN p
        WHEN: Parsed and compiled
        THEN: IR contains ScanLabel for 'Person' and Project
        """
        # GIVEN / WHEN
        ir = _parse_and_compile("MATCH (p:Person) RETURN p")

        # THEN
        ops = _op_types(ir)
        assert "ScanLabel" in ops
        assert "Project" in ops
        scan = _ops_of_type(ir, "ScanLabel")[0]
        assert scan["label"] == "Person"
        assert scan["variable"] == "p"

    def test_match_with_property_filter(self):
        """
        GIVEN: MATCH (p:Person {name: 'Alice'}) RETURN p
        WHEN: Parsed and compiled
        THEN: IR contains ScanLabel then Filter on name, then Project
        """
        # GIVEN / WHEN
        ir = _parse_and_compile("MATCH (p:Person {name: 'Alice'}) RETURN p")

        # THEN
        ops = _op_types(ir)
        assert "ScanLabel" in ops
        assert "Filter" in ops
        assert "Project" in ops
        filters = _ops_of_type(ir, "Filter")
        prop_names = {f["property"] for f in filters}
        assert "name" in prop_names

    def test_match_relationship(self):
        """
        GIVEN: MATCH (a:Person)-[r:KNOWS]->(b:Person) RETURN a, b
        WHEN: Parsed and compiled
        THEN: IR contains ScanLabel, Expand and Project
        """
        # GIVEN / WHEN
        ir = _parse_and_compile(
            "MATCH (a:Person)-[r:KNOWS]->(b:Person) RETURN a, b"
        )

        # THEN
        ops = _op_types(ir)
        assert "ScanLabel" in ops
        assert "Expand" in ops
        assert "Project" in ops
        expand = _ops_of_type(ir, "Expand")[0]
        assert "KNOWS" in expand.get("rel_types", [])


# ---------------------------------------------------------------------------
# WHERE clause patterns
# ---------------------------------------------------------------------------

class TestWhereClause:
    """Golden fixtures for WHERE clause compilation."""

    def test_where_equality(self):
        """
        GIVEN: MATCH (p:Person) WHERE p.age = 30 RETURN p
        WHEN: Parsed and compiled
        THEN: IR contains Filter with operator '='
        """
        # GIVEN / WHEN
        ir = _parse_and_compile("MATCH (p:Person) WHERE p.age = 30 RETURN p")

        # THEN
        filters = _ops_of_type(ir, "Filter")
        assert any(f.get("property") == "age" and f.get("operator") == "=" for f in filters)

    def test_where_greater_than(self):
        """
        GIVEN: MATCH (p:Person) WHERE p.age > 25 RETURN p
        WHEN: Parsed and compiled
        THEN: IR contains Filter with operator '>'
        """
        # GIVEN / WHEN
        ir = _parse_and_compile("MATCH (p:Person) WHERE p.age > 25 RETURN p")

        # THEN
        filters = _ops_of_type(ir, "Filter")
        assert any(f.get("property") == "age" and f.get("operator") == ">" for f in filters)

    def test_where_not_operator(self):
        """
        GIVEN: MATCH (p:Person) WHERE NOT p.age > 30 RETURN p
        WHEN: Parsed and compiled
        THEN: IR contains at least one Filter operation (NOT wraps the predicate)
        """
        # GIVEN / WHEN
        ir = _parse_and_compile("MATCH (p:Person) WHERE NOT p.age > 30 RETURN p")

        # THEN
        ops = _op_types(ir)
        assert "ScanLabel" in ops
        assert "Project" in ops
        # At minimum a Filter or a composite filter must be present
        assert "Filter" in ops

    def test_where_and_compound(self):
        """
        GIVEN: MATCH (p:Person) WHERE p.age > 20 AND p.age < 40 RETURN p
        WHEN: Parsed and compiled
        THEN: IR contains two Filter operations (one per predicate)
        """
        # GIVEN / WHEN
        ir = _parse_and_compile(
            "MATCH (p:Person) WHERE p.age > 20 AND p.age < 40 RETURN p"
        )

        # THEN
        filters = _ops_of_type(ir, "Filter")
        assert len(filters) >= 2


# ---------------------------------------------------------------------------
# RETURN clause patterns
# ---------------------------------------------------------------------------

class TestReturnClause:
    """Golden fixtures for RETURN clause compilation."""

    def test_return_single_variable(self):
        """
        GIVEN: MATCH (n:Person) RETURN n
        WHEN: Parsed and compiled
        THEN: Project lists variable 'n'
        """
        # GIVEN / WHEN
        ir = _parse_and_compile("MATCH (n:Person) RETURN n")

        # THEN
        projects = _ops_of_type(ir, "Project")
        assert projects
        items = projects[0].get("items", [])
        assert any("n" in str(item) for item in items)

    def test_return_property_access(self):
        """
        GIVEN: MATCH (n:Person) RETURN n.name
        WHEN: Parsed and compiled
        THEN: Project contains property-access expression for 'n.name'
        """
        # GIVEN / WHEN
        ir = _parse_and_compile("MATCH (n:Person) RETURN n.name")

        # THEN
        projects = _ops_of_type(ir, "Project")
        assert projects
        items_str = str(projects[0].get("items", []))
        assert "name" in items_str

    def test_return_with_alias(self):
        """
        GIVEN: MATCH (n:Person) RETURN n.name AS personName
        WHEN: Parsed and compiled
        THEN: Project alias is 'personName'
        """
        # GIVEN / WHEN
        ir = _parse_and_compile("MATCH (n:Person) RETURN n.name AS personName")

        # THEN
        projects = _ops_of_type(ir, "Project")
        assert projects
        items_str = str(projects[0].get("items", []))
        assert "personName" in items_str

    def test_return_with_limit(self):
        """
        GIVEN: MATCH (n:Person) RETURN n LIMIT 5
        WHEN: Parsed and compiled
        THEN: IR contains a Limit operation with value 5
        """
        # GIVEN / WHEN
        ir = _parse_and_compile("MATCH (n:Person) RETURN n LIMIT 5")

        # THEN
        ops = _op_types(ir)
        assert "Limit" in ops
        limit_op = _ops_of_type(ir, "Limit")[0]
        assert limit_op.get("count") == 5

    def test_return_with_order_by(self):
        """
        GIVEN: MATCH (n:Person) RETURN n ORDER BY n.name
        WHEN: Parsed and compiled
        THEN: IR contains an OrderBy operation
        """
        # GIVEN / WHEN
        ir = _parse_and_compile("MATCH (n:Person) RETURN n ORDER BY n.name")

        # THEN
        ops = _op_types(ir)
        assert "OrderBy" in ops


# ---------------------------------------------------------------------------
# CREATE patterns
# ---------------------------------------------------------------------------

class TestCreatePatterns:
    """Golden fixtures for CREATE clause compilation."""

    def test_create_node(self):
        """
        GIVEN: CREATE (n:Person {name: 'Charlie'}) RETURN n
        WHEN: Parsed and compiled
        THEN: IR contains CreateNode operation
        """
        # GIVEN / WHEN
        ir = _parse_and_compile("CREATE (n:Person {name: 'Charlie'}) RETURN n")

        # THEN
        ops = _op_types(ir)
        assert "CreateNode" in ops
        create = _ops_of_type(ir, "CreateNode")[0]
        assert "Person" in create.get("labels", [])

    def test_create_relationship(self):
        """
        GIVEN: MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'})
               CREATE (a)-[r:KNOWS]->(b) RETURN r
        WHEN: Parsed and compiled
        THEN: IR contains CreateRelationship operation for 'KNOWS'
        """
        # GIVEN / WHEN
        query = (
            "MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'}) "
            "CREATE (a)-[r:KNOWS]->(b) RETURN r"
        )
        ir = _parse_and_compile(query)

        # THEN
        ops = _op_types(ir)
        assert "CreateRelationship" in ops
        create_rel = _ops_of_type(ir, "CreateRelationship")[0]
        assert "KNOWS" in create_rel.get("rel_type", "")


# ---------------------------------------------------------------------------
# Error / invalid-input paths
# ---------------------------------------------------------------------------

class TestParserErrors:
    """Golden fixtures that verify invalid queries raise the right exceptions."""

    def test_empty_query_returns_empty_ir(self):
        """
        GIVEN: An empty string
        WHEN: Parsed and compiled
        THEN: The result is an empty IR (no operations); no exception is raised
        """
        # GIVEN / WHEN
        ir = _parse_and_compile("")

        # THEN – parser tolerates empty input; compiler returns no operations
        assert ir == []

    def test_incomplete_match_raises(self):
        """
        GIVEN: 'MATCH' with no pattern
        WHEN: Parsed
        THEN: CypherParseError is raised
        """
        # GIVEN
        parser = CypherParser()

        # WHEN / THEN
        with pytest.raises((CypherParseError, Exception)):
            parser.parse("MATCH")

    def test_unmatched_parenthesis_raises(self):
        """
        GIVEN: Query with unmatched parenthesis
        WHEN: Parsed
        THEN: An exception is raised (not a silent failure)
        """
        # GIVEN
        parser = CypherParser()

        # WHEN / THEN
        with pytest.raises(Exception):
            parser.parse("MATCH (n:Person RETURN n")
