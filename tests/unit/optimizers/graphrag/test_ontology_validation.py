"""Unit tests for ontology validation utilities.

Tests the validate_ontology, find_orphaned_entities, detect_circular_relationships,
and other validation functions.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_validation import (
    validate_ontology,
    ValidationResult,
    find_orphaned_entities,
    find_dangling_references,
    detect_circular_relationships,
    find_duplicate_ids,
    check_entity_consistency,
    check_relationship_consistency,
    format_validation_result,
)


class TestValidateOntology:
    """Test the validate_ontology function."""

    def test_empty_ontology_valid(self):
        """Test that empty ontology is valid."""
        ontology = {"entities": [], "relationships": []}
        result = validate_ontology(ontology)
        
        assert result.is_valid
        assert len(result.errors) == 0

    def test_missing_entities_key(self):
        """Test error when 'entities' key is missing."""
        ontology = {"relationships": []}
        result = validate_ontology(ontology)
        
        assert not result.is_valid
        assert any("entities" in err.lower() for err in result.errors)

    def test_missing_relationships_key(self):
        """Test error when 'relationships' key is missing."""
        ontology = {"entities": []}
        result = validate_ontology(ontology)
        
        assert not result.is_valid
        assert any("relationships" in err.lower() for err in result.errors)

    def test_valid_simple_ontology(self):
        """Test validation of a simple valid ontology."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "text": "Alice"},
                {"id": "e2", "type": "Person", "text": "Bob"},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"}
            ],
        }
        result = validate_ontology(ontology)
        
        assert result.is_valid
        assert len(result.errors) == 0

    def test_duplicate_entity_ids(self):
        """Test detection of duplicate entity IDs."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice"},
                {"id": "e1", "text": "Alice duplicate"},
            ],
            "relationships": [],
        }
        result = validate_ontology(ontology)
        
        assert not result.is_valid
        assert any("duplicate entity id" in err.lower() for err in result.errors)

    def test_duplicate_relationship_ids(self):
        """Test detection of duplicate relationship IDs."""
        ontology = {
            "entities": [{"id": "e1"}],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e1"},
                {"id": "r1", "source_id": "e1", "target_id": "e1"},
            ],
        }
        result = validate_ontology(ontology)
        
        assert not result.is_valid
        assert any("duplicate relationship id" in err.lower() for err in result.errors)

    def test_dangling_reference(self):
        """Test detection of dangling references."""
        ontology = {
            "entities": [{"id": "e1", "text": "Alice"}],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e99", "type": "knows"}
            ],
        }
        result = validate_ontology(ontology)
        
        assert not result.is_valid
        assert any("missing" in err.lower() for err in result.errors)

    def test_orphaned_entities_warning(self):
        """Test warning for orphaned entities (non-strict mode)."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice"},
                {"id": "e2", "text": "Bob"},  # Orphaned
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e1", "type": "self"}
            ],
        }
        result = validate_ontology(ontology, strict=False)
        
        assert result.is_valid  # Valid in non-strict mode
        assert len(result.warnings) > 0
        assert any("orphaned" in warn.lower() for warn in result.warnings)

    def test_orphaned_entities_error_strict(self):
        """Test error for orphaned entities in strict mode."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice"},
                {"id": "e2", "text": "Bob"},  # Orphaned
            ],
            "relationships": [],
        }
        result = validate_ontology(ontology, strict=True)
        
        assert not result.is_valid
        assert any("orphaned" in err.lower() for err in result.errors)

    def test_circular_relationships_warning(self):
        """Test warning for circular relationships."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice"},
                {"id": "e2", "text": "Bob"},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"},
                {"id": "r2", "source_id": "e2", "target_id": "e1", "type": "knows"},
            ],
        }
        result = validate_ontology(ontology, strict=False)
        
        assert result.is_valid  # Valid in non-strict mode
        assert len(result.warnings) > 0
        assert any("circular" in warn.lower() for warn in result.warnings)


class TestFindOrphanedEntities:
    """Test the find_orphaned_entities function."""

    def test_no_orphans(self):
        """Test when all entities are referenced."""
        entities = [{"id": "e1"}, {"id": "e2"}]
        rels = [{"source_id": "e1", "target_id": "e2"}]
        
        orphaned = find_orphaned_entities(entities, rels)
        
        assert len(orphaned) == 0

    def test_one_orphan(self):
        """Test detection of one orphaned entity."""
        entities = [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}]
        rels = [{"source_id": "e1", "target_id": "e2"}]
        
        orphaned = find_orphaned_entities(entities, rels)
        
        assert orphaned == ["e3"]

    def test_all_orphans(self):
        """Test when all entities are orphaned."""
        entities = [{"id": "e1"}, {"id": "e2"}]
        rels = []
        
        orphaned = find_orphaned_entities(entities, rels)
        
        assert set(orphaned) == {"e1", "e2"}

    def test_self_reference_not_orphan(self):
        """Test that self-referencing entity is not orphaned."""
        entities = [{"id": "e1"}]
        rels = [{"source_id": "e1", "target_id": "e1"}]
        
        orphaned = find_orphaned_entities(entities, rels)
        
        assert len(orphaned) == 0


class TestFindDanglingReferences:
    """Test the find_dangling_references function."""

    def test_no_dangling(self):
        """Test when all references are valid."""
        rels = [{"id": "r1", "source_id": "e1", "target_id": "e2"}]
        valid_ids = {"e1", "e2"}
        
        dangling = find_dangling_references(rels, valid_ids)
        
        assert len(dangling) == 0

    def test_dangling_source(self):
        """Test detection of dangling source reference."""
        rels = [{"id": "r1", "source_id": "e99", "target_id": "e2"}]
        valid_ids = {"e2"}
        
        dangling = find_dangling_references(rels, valid_ids)
        
        assert len(dangling) == 1
        assert dangling[0] == ("r1", "source", "e99")

    def test_dangling_target(self):
        """Test detection of dangling target reference."""
        rels = [{"id": "r1", "source_id": "e1", "target_id": "e99"}]
        valid_ids = {"e1"}
        
        dangling = find_dangling_references(rels, valid_ids)
        
        assert len(dangling) == 1
        assert dangling[0] == ("r1", "target", "e99")

    def test_both_dangling(self):
        """Test detection when both source and target are invalid."""
        rels = [{"id": "r1", "source_id": "e98", "target_id": "e99"}]
        valid_ids = set()
        
        dangling = find_dangling_references(rels, valid_ids)
        
        assert len(dangling) == 2


class TestDetectCircularRelationships:
    """Test the detect_circular_relationships function."""

    def test_no_cycles(self):
        """Test when there are no circular relationships."""
        rels = [
            {"source_id": "e1", "target_id": "e2"},
            {"source_id": "e2", "target_id": "e3"},
        ]
        
        cycles = detect_circular_relationships(rels)
        
        assert len(cycles) == 0

    def test_simple_cycle(self):
        """Test detection of a simple 2-node cycle."""
        rels = [
            {"source_id": "e1", "target_id": "e2"},
            {"source_id": "e2", "target_id": "e1"},
        ]
        
        cycles = detect_circular_relationships(rels)
        
        assert len(cycles) > 0

    def test_self_loop_cycle(self):
        """Test detection of self-loop as a cycle."""
        rels = [{"source_id": "e1", "target_id": "e1"}]
        
        cycles = detect_circular_relationships(rels)
        
        assert len(cycles) > 0

    def test_three_node_cycle(self):
        """Test detection of a 3-node cycle."""
        rels = [
            {"source_id": "e1", "target_id": "e2"},
            {"source_id": "e2", "target_id": "e3"},
            {"source_id": "e3", "target_id": "e1"},
        ]
        
        cycles = detect_circular_relationships(rels)
        
        assert len(cycles) > 0


class TestFindDuplicateIds:
    """Test the find_duplicate_ids function."""

    def test_no_duplicates(self):
        """Test when there are no duplicates."""
        ids = ["a", "b", "c"]
        
        duplicates = find_duplicate_ids(ids)
        
        assert len(duplicates) == 0

    def test_one_duplicate(self):
        """Test detection of one duplicate ID."""
        ids = ["a", "b", "a", "c"]
        
        duplicates = find_duplicate_ids(ids)
        
        assert duplicates == ["a"]

    def test_multiple_duplicates(self):
        """Test detection of multiple duplicate IDs."""
        ids = ["a", "b", "a", "c", "b"]
        
        duplicates = find_duplicate_ids(ids)
        
        assert set(duplicates) == {"a", "b"}

    def test_empty_list(self):
        """Test with empty list."""
        ids = []
        
        duplicates = find_duplicate_ids(ids)
        
        assert len(duplicates) == 0


class TestCheckEntityConsistency:
    """Test the check_entity_consistency function."""

    def test_valid_entities(self):
        """Test with valid entities."""
        entities = [
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.9}
        ]
        
        issues = check_entity_consistency(entities)
        
        assert len(issues) == 0

    def test_missing_id(self):
        """Test detection of missing ID."""
        entities = [{"type": "Person", "text": "Alice"}]
        
        issues = check_entity_consistency(entities)
        
        assert any("missing" in issue.lower() and "id" in issue.lower() for issue in issues)

    def test_missing_type(self):
        """Test detection of missing type."""
        entities = [{"id": "e1", "text": "Alice"}]
        
        issues = check_entity_consistency(entities)
        
        assert any("type" in issue.lower() for issue in issues)

    def test_missing_text(self):
        """Test detection of missing text."""
        entities = [{"id": "e1", "type": "Person"}]
        
        issues = check_entity_consistency(entities)
        
        assert any("text" in issue.lower() for issue in issues)

    def test_empty_text(self):
        """Test detection of empty text."""
        entities = [{"id": "e1", "type": "Person", "text": "   "}]
        
        issues = check_entity_consistency(entities)
        
        assert any("empty text" in issue.lower() for issue in issues)

    def test_invalid_confidence(self):
        """Test detection of out-of-range confidence."""
        entities = [
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 1.5}
        ]
        
        issues = check_entity_consistency(entities)
        
        assert any("confidence" in issue.lower() for issue in issues)

    def test_non_numeric_confidence(self):
        """Test detection of non-numeric confidence."""
        entities = [
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": "high"}
        ]
        
        issues = check_entity_consistency(entities)
        
        assert any("non-numeric" in issue.lower() for issue in issues)


class TestCheckRelationshipConsistency:
    """Test the check_relationship_consistency function."""

    def test_valid_relationships(self):
        """Test with valid relationships."""
        rels = [
            {
                "id": "r1",
                "source_id": "e1",
                "target_id": "e2",
                "type": "knows",
                "confidence": 0.8,
            }
        ]
        
        issues = check_relationship_consistency(rels)
        
        assert len(issues) == 0

    def test_missing_id(self):
        """Test detection of missing ID."""
        rels = [{"source_id": "e1", "target_id": "e2", "type": "knows"}]
        
        issues = check_relationship_consistency(rels)
        
        assert any("missing" in issue.lower() and "id" in issue.lower() for issue in issues)

    def test_missing_source_id(self):
        """Test detection of missing source_id."""
        rels = [{"id": "r1", "target_id": "e2", "type": "knows"}]
        
        issues = check_relationship_consistency(rels)
        
        assert any("source_id" in issue.lower() for issue in issues)

    def test_missing_target_id(self):
        """Test detection of missing target_id."""
        rels = [{"id": "r1", "source_id": "e1", "type": "knows"}]
        
        issues = check_relationship_consistency(rels)
        
        assert any("target_id" in issue.lower() for issue in issues)

    def test_missing_type(self):
        """Test detection of missing type."""
        rels = [{"id": "r1", "source_id": "e1", "target_id": "e2"}]
        
        issues = check_relationship_consistency(rels)
        
        assert any("type" in issue.lower() for issue in issues)

    def test_self_loop(self):
        """Test detection of self-loop."""
        rels = [
            {"id": "r1", "source_id": "e1", "target_id": "e1", "type": "self"}
        ]
        
        issues = check_relationship_consistency(rels)
        
        assert any("self-loop" in issue.lower() for issue in issues)

    def test_invalid_confidence(self):
        """Test detection of out-of-range confidence."""
        rels = [
            {
                "id": "r1",
                "source_id": "e1",
                "target_id": "e2",
                "type": "knows",
                "confidence": -0.5,
            }
        ]
        
        issues = check_relationship_consistency(rels)
        
        assert any("confidence" in issue.lower() for issue in issues)


class TestValidationResult:
    """Test the ValidationResult dataclass."""

    def test_is_valid_true(self):
        """Test is_valid property when no errors."""
        result = ValidationResult(warnings=["Warning"])
        
        assert result.is_valid is True

    def test_is_valid_false(self):
        """Test is_valid property when errors exist."""
        result = ValidationResult(errors=["Error"])
        
        assert result.is_valid is False

    def test_total_issues(self):
        """Test total_issues property."""
        result = ValidationResult(
            errors=["E1", "E2"],
            warnings=["W1", "W2", "W3"],
        )
        
        assert result.total_issues == 5

    def test_repr(self):
        """Test __repr__ method."""
        result = ValidationResult(errors=["Error"], warnings=["Warning"])
        repr_str = repr(result)
        
        assert "ValidationResult" in repr_str
        assert "Invalid" in repr_str
        assert "errors=1" in repr_str


class TestFormatValidationResult:
    """Test the format_validation_result function."""

    def test_format_valid(self):
        """Test formatting a valid result."""
        result = ValidationResult()
        formatted = format_validation_result(result)
        
        assert "Valid" in formatted

    def test_format_invalid(self):
        """Test formatting an invalid result."""
        result = ValidationResult(errors=["Error 1"])
        formatted = format_validation_result(result)
        
        assert "Invalid" in formatted

    def test_format_verbose(self):
        """Test verbose formatting."""
        result = ValidationResult(
            errors=["Error 1", "Error 2"],
            warnings=["Warning 1"],
        )
        formatted = format_validation_result(result, verbose=True)
        
        assert "Error 1" in formatted
        assert "Error 2" in formatted
        assert "Warning 1" in formatted

    def test_format_summary(self):
        """Test summary formatting (non-verbose)."""
        result = ValidationResult(
            errors=["Error 1", "Error 2", "Error 3"],
        )
        formatted = format_validation_result(result, verbose=False)
        
        assert "Error 1" in formatted  # First error shown
        # Not all errors shown in summary mode
        assert formatted.count("Error") < 3


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_validate_with_non_list_entities(self):
        """Test validation when entities is not a list."""
        ontology = {"entities": "not a list", "relationships": []}
        result = validate_ontology(ontology)
        
        assert not result.is_valid
        assert any("must be a list" in err for err in result.errors)

    def test_validate_with_non_list_relationships(self):
        """Test validation when relationships is not a list."""
        ontology = {"entities": [], "relationships": "not a list"}
        result = validate_ontology(ontology)
        
        assert not result.is_valid

    def test_validate_with_non_dict_entity(self):
        """Test validation when entity is not a dict."""
        ontology = {"entities": ["not a dict"], "relationships": []}
        result = validate_ontology(ontology)
        
        # Should produce warnings about consistency
        assert len(result.warnings) > 0

    def test_circular_detection_max_depth(self):
        """Test that circular detection respects max_depth."""
        # Create a very long chain
        rels = [{"source_id": f"e{i}", "target_id": f"e{i+1}"} for i in range(200)]
        
        cycles = detect_circular_relationships(rels, max_depth=10)
        
        # Should not crash or take too long
        assert isinstance(cycles, list)
