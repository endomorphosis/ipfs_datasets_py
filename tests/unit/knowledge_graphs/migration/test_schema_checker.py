"""
Tests for schema compatibility checker
"""

try:
    import pytest
    HAVE_PYTEST = True
except ImportError:
    HAVE_PYTEST = False

from ipfs_datasets_py.knowledge_graphs.migration.formats import SchemaData
from ipfs_datasets_py.knowledge_graphs.migration.schema_checker import (
    SchemaChecker, CompatibilityReport
)


class TestCompatibilityReport:
    """Test CompatibilityReport class."""
    
    def test_report_creation(self):
        """Test creating a compatibility report."""
        report = CompatibilityReport(
            compatible=True,
            compatibility_score=95.0
        )
        assert report.compatible is True
        assert report.compatibility_score == 95.0
    
    def test_report_to_dict(self):
        """Test converting report to dictionary."""
        report = CompatibilityReport(
            compatible=False,
            compatibility_score=60.0,
            issues=[{"type": "index", "message": "unsupported"}],
            warnings=["warning1"],
            recommendations=["recommendation1"]
        )
        
        data = report.to_dict()
        assert data['compatible'] is False
        assert data['compatibility_score'] == 60.0
        assert len(data['issues']) == 1
        assert len(data['warnings']) == 1
        assert len(data['recommendations']) == 1


class TestSchemaChecker:
    """Test SchemaChecker class."""
    
    def test_checker_initialization(self):
        """Test schema checker initialization."""
        checker = SchemaChecker()
        assert checker.custom_rules == {}
        
        custom_checker = SchemaChecker(custom_rules={"rule1": "value"})
        assert len(custom_checker.custom_rules) == 1
    
    def test_check_empty_schema(self):
        """Test checking an empty schema."""
        schema = SchemaData(
            indexes=[],
            constraints=[],
            node_labels=[],
            relationship_types=[]
        )
        
        checker = SchemaChecker()
        report = checker.check_schema(schema)
        
        # Empty schema should be compatible
        assert report.compatible is True
        assert report.compatibility_score >= 0
    
    def test_check_basic_schema(self):
        """Test checking a basic schema."""
        schema = SchemaData(
            indexes=[
                {"label": "Person", "property": "name", "type": "BTREE"}
            ],
            constraints=[
                {"label": "Person", "property": "id", "type": "UNIQUENESS"}
            ],
            node_labels=["Person", "Organization"],
            relationship_types=["KNOWS", "WORKS_AT"]
        )
        
        checker = SchemaChecker()
        report = checker.check_schema(schema)
        
        assert report.compatibility_score >= 0
        assert report.compatibility_score <= 100
    
    def test_check_schema_with_supported_index_types(self):
        """Test schema with supported index types."""
        schema = SchemaData(
            indexes=[
                {"label": "Person", "property": "name", "type": "BTREE"},
                {"label": "Document", "property": "text", "type": "FULLTEXT"},
                {"label": "Embedding", "property": "vector", "type": "VECTOR"}
            ]
        )
        
        checker = SchemaChecker()
        report = checker.check_schema(schema)
        
        # Should be compatible with supported types
        assert report.compatibility_score > 0
    
    def test_check_schema_with_supported_constraint_types(self):
        """Test schema with supported constraint types."""
        schema = SchemaData(
            constraints=[
                {"label": "Person", "property": "id", "type": "UNIQUENESS"},
                {"label": "Person", "property": "email", "type": "UNIQUE"},
                {"label": "Person", "property": "name", "type": "NODE_PROPERTY_EXISTENCE"}
            ]
        )
        
        checker = SchemaChecker()
        report = checker.check_schema(schema)
        
        # Should be compatible with supported types
        assert report.compatibility_score > 0
    
    def test_check_schema_with_multiple_labels(self):
        """Test schema with multiple node labels."""
        schema = SchemaData(
            node_labels=["Person", "Employee", "Manager", "Organization", "Department"]
        )
        
        checker = SchemaChecker()
        report = checker.check_schema(schema)
        
        assert report.compatible is True
        assert len(schema.node_labels) == 5
    
    def test_check_schema_with_multiple_relationship_types(self):
        """Test schema with multiple relationship types."""
        schema = SchemaData(
            relationship_types=["KNOWS", "WORKS_AT", "MANAGES", "REPORTS_TO", "FRIEND_OF"]
        )
        
        checker = SchemaChecker()
        report = checker.check_schema(schema)
        
        assert report.compatible is True
        assert len(schema.relationship_types) == 5
    
    def test_check_schema_with_custom_rules(self):
        """Test schema checker with custom rules."""
        custom_rules = {
            "max_indexes": 10,
            "max_constraints": 5
        }
        
        schema = SchemaData(
            indexes=[{"label": f"Label{i}", "property": "prop"} for i in range(3)],
            constraints=[{"label": "Person", "property": "id", "type": "UNIQUE"}]
        )
        
        checker = SchemaChecker(custom_rules=custom_rules)
        report = checker.check_schema(schema)
        
        # Should process with custom rules
        assert report.compatibility_score >= 0


class TestSchemaEdgeCases:
    """Test edge cases for schema checking."""
    
    def test_schema_with_no_indexes(self):
        """Test schema with no indexes."""
        schema = SchemaData(
            indexes=[],
            constraints=[{"label": "Person", "property": "id", "type": "UNIQUE"}],
            node_labels=["Person"]
        )
        
        checker = SchemaChecker()
        report = checker.check_schema(schema)
        
        assert report.compatible is True
    
    def test_schema_with_no_constraints(self):
        """Test schema with no constraints."""
        schema = SchemaData(
            indexes=[{"label": "Person", "property": "name", "type": "BTREE"}],
            constraints=[],
            node_labels=["Person"]
        )
        
        checker = SchemaChecker()
        report = checker.check_schema(schema)
        
        assert report.compatible is True
    
    def test_schema_with_unicode_labels(self):
        """Test schema with Unicode node labels."""
        schema = SchemaData(
            node_labels=["人物", "组织", "Persönlich"],
            relationship_types=["认识", "工作于"]
        )
        
        checker = SchemaChecker()
        report = checker.check_schema(schema)
        
        assert report.compatible is True
    
    def test_schema_with_special_characters(self):
        """Test schema with special characters in names."""
        schema = SchemaData(
            node_labels=["Node-Type", "Node_Type", "Node:Type"],
            relationship_types=["REL-TYPE", "REL_TYPE"]
        )
        
        checker = SchemaChecker()
        report = checker.check_schema(schema)
        
        # Should handle special characters
        assert report.compatibility_score >= 0
    
    def test_schema_with_complex_indexes(self):
        """Test schema with complex index configurations."""
        schema = SchemaData(
            indexes=[
                {
                    "label": "Person",
                    "property": "name",
                    "type": "BTREE",
                    "options": {"unique": False}
                },
                {
                    "label": "Document",
                    "property": "content",
                    "type": "FULLTEXT",
                    "options": {"analyzer": "standard"}
                }
            ]
        )
        
        checker = SchemaChecker()
        report = checker.check_schema(schema)
        
        assert report.compatibility_score >= 0
    
    def test_schema_with_complex_constraints(self):
        """Test schema with complex constraint configurations."""
        schema = SchemaData(
            constraints=[
                {
                    "label": "Person",
                    "property": "id",
                    "type": "UNIQUENESS",
                    "options": {"enforced": True}
                },
                {
                    "label": "Person",
                    "properties": ["firstName", "lastName"],
                    "type": "NODE_KEY"
                }
            ]
        )
        
        checker = SchemaChecker()
        report = checker.check_schema(schema)
        
        assert report.compatibility_score >= 0
    
    def test_schema_with_long_names(self):
        """Test schema with very long label/type names."""
        long_name = "A" * 100
        schema = SchemaData(
            node_labels=[long_name],
            relationship_types=[long_name + "_REL"]
        )
        
        checker = SchemaChecker()
        report = checker.check_schema(schema)
        
        # Should handle long names
        assert report.compatibility_score >= 0
    
    def test_schema_with_duplicate_labels(self):
        """Test schema with duplicate labels."""
        schema = SchemaData(
            node_labels=["Person", "Person", "Organization"],
            relationship_types=["KNOWS", "KNOWS"]
        )
        
        checker = SchemaChecker()
        report = checker.check_schema(schema)
        
        # Should handle duplicates (might warn or pass)
        assert report.compatibility_score >= 0
    
    def test_schema_data_serialization(self):
        """Test SchemaData to_dict and from_dict."""
        original_schema = SchemaData(
            indexes=[{"label": "Person", "property": "name"}],
            constraints=[{"label": "Person", "property": "id", "type": "UNIQUE"}],
            node_labels=["Person", "Organization"],
            relationship_types=["KNOWS", "WORKS_AT"]
        )
        
        # Convert to dict and back
        schema_dict = original_schema.to_dict()
        loaded_schema = SchemaData.from_dict(schema_dict)
        
        assert len(loaded_schema.indexes) == len(original_schema.indexes)
        assert len(loaded_schema.constraints) == len(original_schema.constraints)
        assert set(loaded_schema.node_labels) == set(original_schema.node_labels)
        assert set(loaded_schema.relationship_types) == set(original_schema.relationship_types)


if __name__ == "__main__" and HAVE_PYTEST:
    pytest.main([__file__, "-v"])
