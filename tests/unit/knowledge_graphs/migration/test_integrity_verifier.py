"""
Tests for integrity verifier
"""

try:
    import pytest
    HAVE_PYTEST = True
except ImportError:
    HAVE_PYTEST = False

from ipfs_datasets_py.knowledge_graphs.migration.formats import (
    NodeData, RelationshipData, GraphData
)
from ipfs_datasets_py.knowledge_graphs.migration.integrity_verifier import (
    IntegrityVerifier, VerificationReport
)


class TestVerificationReport:
    """Test VerificationReport class."""
    
    def test_report_creation(self):
        """Test creating a verification report."""
        report = VerificationReport(
            passed=True,
            checks_performed=5,
            checks_passed=5,
            checks_failed=0
        )
        assert report.passed is True
        assert report.checks_performed == 5
        assert report.checks_passed == 5
    
    def test_report_to_dict(self):
        """Test converting report to dictionary."""
        report = VerificationReport(
            passed=False,
            checks_performed=3,
            checks_passed=2,
            checks_failed=1,
            errors=[{"check": "test", "message": "error"}],
            warnings=["warning1"]
        )
        
        data = report.to_dict()
        assert data['passed'] is False
        assert data['checks_performed'] == 3
        assert len(data['errors']) == 1
        assert len(data['warnings']) == 1


class TestIntegrityVerifier:
    """Test IntegrityVerifier class."""
    
    def test_verifier_initialization(self):
        """Test verifier initialization."""
        verifier = IntegrityVerifier()
        assert verifier.strict_mode is False
        
        strict_verifier = IntegrityVerifier(strict_mode=True)
        assert strict_verifier.strict_mode is True
    
    def test_verify_identical_graphs(self):
        """Test verification of identical graphs."""
        nodes = [
            NodeData(id="1", labels=["Person"], properties={"name": "Alice"}),
            NodeData(id="2", labels=["Person"], properties={"name": "Bob"})
        ]
        rels = [
            RelationshipData(id="1", type="KNOWS", start_node="1", end_node="2")
        ]
        
        source = GraphData(nodes=nodes.copy(), relationships=rels.copy())
        target = GraphData(nodes=nodes.copy(), relationships=rels.copy())
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        assert report.passed is True
        assert report.checks_performed > 0
        assert report.checks_failed == 0
    
    def test_verify_node_count_mismatch(self):
        """Test verification fails on node count mismatch."""
        source_nodes = [
            NodeData(id="1", labels=["Person"]),
            NodeData(id="2", labels=["Person"])
        ]
        target_nodes = [
            NodeData(id="1", labels=["Person"])
        ]
        
        source = GraphData(nodes=source_nodes)
        target = GraphData(nodes=target_nodes)
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        assert report.passed is False
        assert report.checks_failed > 0
        assert any('node_count' in str(err) for err in report.errors)
    
    def test_verify_relationship_count_mismatch(self):
        """Test verification fails on relationship count mismatch."""
        nodes = [NodeData(id="1"), NodeData(id="2")]
        source_rels = [
            RelationshipData(id="1", type="KNOWS", start_node="1", end_node="2"),
            RelationshipData(id="2", type="KNOWS", start_node="2", end_node="1")
        ]
        target_rels = [
            RelationshipData(id="1", type="KNOWS", start_node="1", end_node="2")
        ]
        
        source = GraphData(nodes=nodes.copy(), relationships=source_rels)
        target = GraphData(nodes=nodes.copy(), relationships=target_rels)
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        assert report.passed is False
        assert report.checks_failed > 0
    
    def test_verify_empty_graphs(self):
        """Test verification of empty graphs."""
        source = GraphData(nodes=[], relationships=[])
        target = GraphData(nodes=[], relationships=[])
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        assert report.passed is True
        assert report.checks_performed > 0
    
    def test_verify_strict_mode(self):
        """Test strict mode enforcement."""
        # Slight difference in properties
        source_nodes = [
            NodeData(id="1", labels=["Person"], properties={"name": "Alice", "age": 30})
        ]
        target_nodes = [
            NodeData(id="1", labels=["Person"], properties={"name": "Alice"})
        ]
        
        source = GraphData(nodes=source_nodes)
        target = GraphData(nodes=target_nodes)
        
        # Non-strict mode might tolerate small differences
        verifier = IntegrityVerifier(strict_mode=False)
        report1 = verifier.verify(source, target)
        
        # Strict mode should be more stringent
        strict_verifier = IntegrityVerifier(strict_mode=True)
        report2 = strict_verifier.verify(source, target)
        
        # At least one should show differences
        assert report1.passed is True or report2.passed is False
    
    def test_verify_large_graphs(self):
        """Test verification of large graphs."""
        nodes = [NodeData(id=str(i), labels=["Node"]) for i in range(100)]
        rels = [
            RelationshipData(id=str(i), type="LINK", start_node=str(i), end_node=str((i+1) % 100))
            for i in range(100)
        ]
        
        source = GraphData(nodes=nodes.copy(), relationships=rels.copy())
        target = GraphData(nodes=nodes.copy(), relationships=rels.copy())
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        assert report.passed is True
        assert report.checks_performed > 0
    
    def test_verify_with_statistics(self):
        """Test that report includes statistics."""
        nodes = [NodeData(id="1", labels=["Test"])]
        source = GraphData(nodes=nodes)
        target = GraphData(nodes=nodes)
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        # Report should have statistics
        assert isinstance(report.statistics, dict)


class TestIntegrityEdgeCases:
    """Test edge cases for integrity verification."""
    
    def test_verify_graphs_with_different_node_order(self):
        """Test verification handles different node ordering."""
        nodes1 = [
            NodeData(id="1", labels=["A"]),
            NodeData(id="2", labels=["B"])
        ]
        nodes2 = [
            NodeData(id="2", labels=["B"]),
            NodeData(id="1", labels=["A"])
        ]
        
        source = GraphData(nodes=nodes1)
        target = GraphData(nodes=nodes2)
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        # Should pass regardless of order
        assert report.passed is True
    
    def test_verify_with_different_labels(self):
        """Test verification detects label differences."""
        source_nodes = [
            NodeData(id="1", labels=["Person"]),
            NodeData(id="2", labels=["Organization"])
        ]
        target_nodes = [
            NodeData(id="1", labels=["Person"]),
            NodeData(id="2", labels=["Company"])  # Different label
        ]
        
        source = GraphData(nodes=source_nodes)
        target = GraphData(nodes=target_nodes)
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        # Should detect label differences
        assert report.checks_performed > 0
        # Should have warnings about missing/extra labels
        assert len(report.warnings) > 0
    
    def test_verify_with_different_relationship_types(self):
        """Test verification detects relationship type differences."""
        nodes = [NodeData(id="1"), NodeData(id="2")]
        source_rels = [
            RelationshipData(id="1", type="KNOWS", start_node="1", end_node="2")
        ]
        target_rels = [
            RelationshipData(id="1", type="FRIEND_OF", start_node="1", end_node="2")
        ]
        
        source = GraphData(nodes=nodes.copy(), relationships=source_rels)
        target = GraphData(nodes=nodes.copy(), relationships=target_rels)
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        # Should detect relationship type differences
        assert len(report.warnings) > 0
    
    def test_verify_with_unicode_properties(self):
        """Test verification with Unicode properties."""
        nodes = [
            NodeData(id="1", labels=["Person"], properties={"name": "李明", "city": "北京"})
        ]
        
        source = GraphData(nodes=nodes.copy())
        target = GraphData(nodes=nodes.copy())
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        assert report.passed is True
    
    def test_verify_with_null_properties(self):
        """Test verification with null property values."""
        nodes = [
            NodeData(id="1", properties={"value": None, "data": "test"})
        ]
        
        source = GraphData(nodes=nodes.copy())
        target = GraphData(nodes=nodes.copy())
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        assert report.passed is True
    
    def test_verify_with_complex_property_types(self):
        """Test verification with complex property types."""
        nodes = [
            NodeData(
                id="1",
                properties={
                    "tags": ["a", "b", "c"],
                    "scores": [1, 2, 3],
                    "nested": {"key": "value"}
                }
            )
        ]
        
        source = GraphData(nodes=nodes.copy())
        target = GraphData(nodes=nodes.copy())
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        assert report.passed is True
    
    def test_verify_statistics_included(self):
        """Test that statistics are included in report."""
        nodes = [
            NodeData(id="1", labels=["Person", "Employee"]),
            NodeData(id="2", labels=["Person"])
        ]
        rels = [
            RelationshipData(id="1", type="KNOWS", start_node="1", end_node="2"),
            RelationshipData(id="2", type="WORKS_WITH", start_node="1", end_node="2")
        ]
        
        source = GraphData(nodes=nodes, relationships=rels)
        target = GraphData(nodes=nodes, relationships=rels)
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        # Check that statistics are in the report
        assert 'source' in report.statistics
        assert 'target' in report.statistics
        assert 'node_count' in report.statistics['source']
        assert 'relationship_count' in report.statistics['source']
        assert 'label_counts' in report.statistics['source']
        assert 'relationship_type_counts' in report.statistics['source']
    
    def test_verify_with_missing_labels_in_target(self):
        """Test verification with missing labels in target."""
        source_nodes = [
            NodeData(id="1", labels=["Person", "Employee"]),
            NodeData(id="2", labels=["Person", "Manager"])
        ]
        target_nodes = [
            NodeData(id="1", labels=["Person"]),
            NodeData(id="2", labels=["Person"])
        ]
        
        source = GraphData(nodes=source_nodes)
        target = GraphData(nodes=target_nodes)
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        # Should detect missing labels
        assert len(report.warnings) > 0
        assert any("Missing labels" in w for w in report.warnings)
    
    def test_verify_with_extra_labels_in_target(self):
        """Test verification with extra labels in target."""
        source_nodes = [
            NodeData(id="1", labels=["Person"]),
            NodeData(id="2", labels=["Person"])
        ]
        target_nodes = [
            NodeData(id="1", labels=["Person", "Employee"]),
            NodeData(id="2", labels=["Person", "Manager"])
        ]
        
        source = GraphData(nodes=source_nodes)
        target = GraphData(nodes=target_nodes)
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        # Should detect extra labels
        assert len(report.warnings) > 0
        assert any("Extra labels" in w for w in report.warnings)
    
    def test_verify_with_missing_relationship_types(self):
        """Test verification with missing relationship types in target."""
        nodes = [NodeData(id="1"), NodeData(id="2")]
        source_rels = [
            RelationshipData(id="1", type="KNOWS", start_node="1", end_node="2"),
            RelationshipData(id="2", type="WORKS_WITH", start_node="1", end_node="2")
        ]
        target_rels = [
            RelationshipData(id="1", type="KNOWS", start_node="1", end_node="2")
        ]
        
        source = GraphData(nodes=nodes, relationships=source_rels)
        target = GraphData(nodes=nodes, relationships=target_rels)
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        # Should detect missing relationship types
        assert report.passed is False  # Count mismatch
        assert report.checks_failed > 0
    
    def test_verify_with_extra_relationship_types(self):
        """Test verification with extra relationship types in target."""
        nodes = [NodeData(id="1"), NodeData(id="2")]
        source_rels = [
            RelationshipData(id="1", type="KNOWS", start_node="1", end_node="2")
        ]
        target_rels = [
            RelationshipData(id="1", type="KNOWS", start_node="1", end_node="2"),
            RelationshipData(id="2", type="WORKS_WITH", start_node="1", end_node="2")
        ]
        
        source = GraphData(nodes=nodes, relationships=source_rels)
        target = GraphData(nodes=nodes, relationships=target_rels)
        
        verifier = IntegrityVerifier()
        report = verifier.verify(source, target)
        
        # Should fail due to count mismatch
        assert report.passed is False
        assert report.checks_failed > 0


class TestIntegrityVerifierSample:
    """Tests for IntegrityVerifier.verify_sample() — covers lines 182-214."""

    def _make_graph(self, count: int = 3) -> "GraphData":
        """Helper: build a GraphData with `count` nodes."""
        nodes = [
            NodeData(id=f"n{i}", labels=["Item"], properties={"val": i})
            for i in range(count)
        ]
        return GraphData(nodes=nodes)

    def test_verify_sample_identical_graphs(self):
        """
        GIVEN: Two identical graphs
        WHEN: verify_sample() is called
        THEN: Report passes with all checks passed
        """
        graph = self._make_graph(3)
        verifier = IntegrityVerifier()
        report = verifier.verify_sample(graph, graph, sample_size=10)

        assert report.passed is True
        assert report.checks_performed == 3
        assert report.checks_passed == 3
        assert report.checks_failed == 0

    def test_verify_sample_missing_node_in_target(self):
        """
        GIVEN: Source has a node absent from target
        WHEN: verify_sample() is called
        THEN: Report fails with an error entry for the missing node
        """
        source = GraphData(nodes=[
            NodeData(id="n0", labels=["X"], properties={"a": 1}),
            NodeData(id="n1", labels=["X"], properties={"b": 2}),
        ])
        target = GraphData(nodes=[
            NodeData(id="n1", labels=["X"], properties={"b": 2}),
        ])

        verifier = IntegrityVerifier()
        report = verifier.verify_sample(source, target, sample_size=10)

        assert report.passed is False
        assert report.checks_failed >= 1
        assert any(e["check"] == "node_exists" for e in report.errors)

    def test_verify_sample_property_mismatch_recorded_as_warning(self):
        """
        GIVEN: Source node has different properties than target node
        WHEN: verify_sample() is called
        THEN: Mismatch recorded; checks_failed incremented
        """
        source = GraphData(nodes=[
            NodeData(id="n0", labels=["X"], properties={"val": 1}),
        ])
        target = GraphData(nodes=[
            NodeData(id="n0", labels=["X"], properties={"val": 999}),
        ])

        verifier = IntegrityVerifier()
        report = verifier.verify_sample(source, target, sample_size=10)

        assert report.checks_performed == 1
        assert report.checks_failed == 1
        assert len(report.warnings) >= 1

    def test_verify_sample_respects_sample_size(self):
        """
        GIVEN: Source has 10 nodes; target matches all
        WHEN: verify_sample() is called with sample_size=5
        THEN: Only 5 checks are performed
        """
        source = self._make_graph(10)
        target = self._make_graph(10)

        verifier = IntegrityVerifier()
        report = verifier.verify_sample(source, target, sample_size=5)

        assert report.checks_performed == 5

    def test_verify_sample_empty_source(self):
        """
        GIVEN: Source is an empty graph
        WHEN: verify_sample() is called
        THEN: Report passes with zero checks performed
        """
        source = GraphData(nodes=[])
        target = GraphData(nodes=[])

        verifier = IntegrityVerifier()
        report = verifier.verify_sample(source, target, sample_size=10)

        assert report.passed is True
        assert report.checks_performed == 0


if __name__ == "__main__" and HAVE_PYTEST:
    pytest.main([__file__, "-v"])
