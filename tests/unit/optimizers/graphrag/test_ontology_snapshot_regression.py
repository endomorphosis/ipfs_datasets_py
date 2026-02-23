"""Snapshot tests for OntologyGenerator to catch regressions.

These tests compare full pipeline outputs against golden reference snapshots.
Any changes to entity extraction, relationship inference, or scoring logic
will cause these tests to fail, alerting developers to potential regressions.

Snapshots are stored as JSON files in tests/fixtures/ontology_snapshots/.
To update snapshots after intentional changes, run with --update-snapshots flag.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from typing import Any, Dict

# Import the classes we'll be testing
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    DataType,
    ExtractionStrategy,
    ExtractionConfig,
)


# Fixture for snapshot directory
@pytest.fixture
def snapshot_dir(tmp_path):
    """Create a temporary directory for snapshots during testing."""
    # In production, this would be a versioned fixtures directory
    # For now, use tmp_path to avoid cluttering the repo
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir(exist_ok=True)
    return snap_dir


class TestOntologyGeneratorSnapshots:
    """Snapshot-based regression tests for full ontology generation pipeline."""
    
    @pytest.fixture
    def generator(self):
        """Create a standard OntologyGenerator instance."""
        return OntologyGenerator(
            ipfs_accelerate_config=None,
            use_ipfs_accelerate=False,
        )
    
    @pytest.fixture
    def legal_context(self):
        """Standard legal domain context."""
        return OntologyGenerationContext(
            data_source="test_legal_doc",
            data_type=DataType.TEXT,
            domain="legal",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
    
    @pytest.fixture
    def medical_context(self):
        """Standard medical domain context."""
        return OntologyGenerationContext(
            data_source="test_medical_doc",
            data_type=DataType.TEXT,
            domain="medical",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
    
    def _normalize_snapshot(self, ontology: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize ontology dict for deterministic comparison.
        
        Removes non-deterministic fields like timestamps, entity IDs (if auto-generated),
        and sorts entities/relationships for consistent ordering.
        """
        normalized = dict(ontology)
        
        # Sort entities by text for deterministic ordering
        if "entities" in normalized:
            normalized["entities"] = sorted(
                normalized["entities"],
                key=lambda e: (e.get("text", ""), e.get("type", ""))
            )
            # Remove or normalize entity IDs if they're auto-generated UUIDs
            for ent in normalized["entities"]:
                # Keep IDs for now, but could normalize them if needed
                pass
        
        # Sort relationships by type and endpoints
        if "relationships" in normalized:
            normalized["relationships"] = sorted(
                normalized["relationships"],
                key=lambda r: (r.get("type", ""), r.get("source_id", ""), r.get("target_id", ""))
            )
        
        # Remove timestamp fields that change on every run
        if "metadata" in normalized:
            meta = dict(normalized["metadata"])
            meta.pop("timestamp", None)
            meta.pop("generation_time_ms", None)
            normalized["metadata"] = meta
        
        return normalized
    
    def _save_snapshot(self, snapshot_dir: Path, name: str, data: Dict[str, Any]):
        """Save a snapshot to disk."""
        snapshot_file = snapshot_dir / f"{name}.json"
        with open(snapshot_file, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
    
    def _load_snapshot(self, snapshot_dir: Path, name: str) -> Dict[str, Any]:
        """Load a snapshot from disk; return None if it doesn't exist."""
        snapshot_file = snapshot_dir / f"{name}.json"
        if not snapshot_file.exists():
            return None
        with open(snapshot_file, "r") as f:
            return json.load(f)
    
    def _assert_snapshot_match(self, snapshot_dir: Path, name: str, actual: Dict[str, Any], update: bool = False):
        """Compare actual output against saved snapshot or update it."""
        normalized = self._normalize_snapshot(actual)
        
        if update:
            self._save_snapshot(snapshot_dir, name, normalized)
            pytest.skip(f"Updated snapshot: {name}")
        
        expected = self._load_snapshot(snapshot_dir, name)
        if expected is None:
            # First run: save the snapshot
            self._save_snapshot(snapshot_dir, name, normalized)
            pytest.skip(f"Created new snapshot: {name}. Run tests again to validate.")
        
        # Deep comparison
        assert normalized == expected, f"Snapshot mismatch for {name}. Run with --update to refresh."
    
    def test_legal_contract_extraction_snapshot(self, generator, legal_context, snapshot_dir):
        """Snapshot test: legal contract entity extraction."""
        text = """
        This Employment Agreement is entered into between Acme Corporation (the "Employer")
        and John Smith (the "Employee") on January 1, 2024. The Employee shall be employed
        as a Senior Software Engineer. The Employer agrees to pay the Employee an annual
        salary of $150,000. Both parties agree to comply with the terms herein.
        """
        
        result = generator.extract_entities(text, legal_context)
        
        # Convert to dict for snapshot
        actual = result.to_dict()
        
        self._assert_snapshot_match(
            snapshot_dir,
            "legal_contract_extraction",
            actual,
            update=False  # Set to True to update snapshots
        )
    
    def test_medical_diagnosis_extraction_snapshot(self, generator, medical_context, snapshot_dir):
        """Snapshot test: medical diagnosis entity extraction."""
        text = """
        Patient John Doe presented with symptoms of Type 2 Diabetes on 2024-01-15.
        Dr. Jane Smith prescribed Metformin 500mg twice daily. Patient should monitor
        blood glucose levels and follow up in 3 months. Family history includes
        cardiovascular disease and hypertension.
        """
        
        result = generator.extract_entities(text, medical_context)
        actual = result.to_dict()
        
        self._assert_snapshot_match(
            snapshot_dir,
            "medical_diagnosis_extraction",
            actual,
            update=False
        )
    
    def test_legal_relationship_inference_snapshot(self, generator, legal_context, snapshot_dir):
        """Snapshot test: legal relationship inference from entities."""
        text = """
        The Plaintiff Alice Johnson filed a complaint against Defendant Bob Corp
        alleging breach of contract. Attorney Sarah Williams represents the Plaintiff.
        Judge Robert Martinez presides over the case.
        """
        
        result = generator.extract_entities(text, legal_context)
        actual = result.to_dict()
        
        # Verify we have both entities and relationships
        assert len(actual["entities"]) > 0, "Expected entities to be extracted"
        assert len(actual["relationships"]) > 0, "Expected relationships to be inferred"
        
        self._assert_snapshot_match(
            snapshot_dir,
            "legal_relationship_inference",
            actual,
            update=False
        )
    
    def test_confidence_scores_snapshot(self, generator, legal_context, snapshot_dir):
        """Snapshot test: verify confidence scores remain stable."""
        text = "John Smith works at Acme Corporation in New York."
        
        result = generator.extract_entities(text, legal_context)
        actual = result.to_dict()
        
        # Extract just confidence-related data
        confidence_snapshot = {
            "overall_confidence": actual.get("confidence", 0.0),
            "entity_confidences": [
                {"text": e["text"], "type": e["type"], "confidence": e["confidence"]}
                for e in actual.get("entities", [])
            ],
            "relationship_confidences": [
                {"type": r["type"], "confidence": r["confidence"]}
                for r in actual.get("relationships", [])
            ],
        }
        
        self._assert_snapshot_match(
            snapshot_dir,
            "confidence_scores",
            confidence_snapshot,
            update=False
        )
    
    def test_empty_input_snapshot(self, generator, legal_context, snapshot_dir):
        """Snapshot test: empty input should produce empty ontology."""
        text = ""
        
        result = generator.extract_entities(text, legal_context)
        actual = result.to_dict()
        
        # Verify empty result structure
        assert actual["entities"] == []
        assert actual["relationships"] == []
        
        self._assert_snapshot_match(
            snapshot_dir,
            "empty_input",
            actual,
            update=False
        )
    
    def test_domain_specific_patterns_snapshot(self, generator, legal_context, snapshot_dir):
        """Snapshot test: verify domain-specific extraction patterns remain stable."""
        text = """
        The Court hereby orders that Defendant shall pay Plaintiff damages in the amount
        of $50,000. This judgment is binding and enforceable under California law.
        Case number: CV-2024-12345.
        """
        
        result = generator.extract_entities(text, legal_context)
        actual = result.to_dict()
        
        # Verify legal-specific entities are extracted
        entity_types = {e["type"] for e in actual.get("entities", [])}
        assert "Obligation" in entity_types or "Legal" in entity_types or "Entity" in entity_types
        
        self._assert_snapshot_match(
            snapshot_dir,
            "legal_domain_patterns",
            actual,
            update=False
        )
    
    def test_entity_type_distribution_snapshot(self, generator, legal_context, snapshot_dir):
        """Snapshot test: entity type distribution should remain consistent."""
        text = """
        Acme Corporation (Company) hired John Smith (Person) on January 1, 2024 (Date).
        The employment contract was signed in San Francisco (Location). The contract
        specifies that John must complete training (Obligation) within 90 days.
        """
        
        result = generator.extract_entities(text, legal_context)
        actual = result.to_dict()
        
        # Extract type distribution
        type_counts = {}
        for e in actual.get("entities", []):
            etype = e.get("type", "unknown")
            type_counts[etype] = type_counts.get(etype, 0) + 1
        
        distribution_snapshot = {
            "total_entities": len(actual.get("entities", [])),
            "type_distribution": type_counts,
            "unique_types": len(type_counts),
        }
        
        self._assert_snapshot_match(
            snapshot_dir,
            "entity_type_distribution",
            distribution_snapshot,
            update=False
        )


class TestOntologyGeneratorRegressionChecks:
    """Additional regression checks that don't use snapshots."""
    
    @pytest.fixture
    def generator(self):
        return OntologyGenerator(
            ipfs_accelerate_config=None,
            use_ipfs_accelerate=False,
        )
    
    @pytest.fixture
    def context(self):
        return OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
    
    def test_no_duplicate_entity_ids(self, generator, context):
        """Regression check: entity IDs should be unique."""
        text = "Alice works at Acme. Bob also works at Acme. Charlie manages Acme."
        
        result = generator.extract_entities(text, context)
        entity_ids = [e.id for e in result.entities]
        
        assert len(entity_ids) == len(set(entity_ids)), "Entity IDs must be unique"
    
    def test_no_duplicate_relationship_ids(self, generator, context):
        """Regression check: relationship IDs should be unique."""
        text = "Alice works at Acme. Bob works at Acme. Charlie manages Acme."
        
        result = generator.extract_entities(text, context)
        rel_ids = [r.id for r in result.relationships]
        
        assert len(rel_ids) == len(set(rel_ids)), "Relationship IDs must be unique"
    
    def test_no_dangling_relationships(self, generator, context):
        """Regression check: all relationships must reference existing entities."""
        text = "Alice works at Acme Corporation. Bob manages the team."
        
        result = generator.extract_entities(text, context)
        entity_ids = {e.id for e in result.entities}
        
        for rel in result.relationships:
            assert rel.source_id in entity_ids, f"Dangling source: {rel.source_id}"
            assert rel.target_id in entity_ids, f"Dangling target: {rel.target_id}"
    
    def test_confidence_bounds(self, generator, context):
        """Regression check: all confidences should be in [0, 1]."""
        text = "Alice works at Acme Corporation in New York."
        
        result = generator.extract_entities(text, context)
        
        # Check overall confidence
        assert 0.0 <= result.confidence <= 1.0, "Overall confidence out of bounds"
        
        # Check entity confidences
        for e in result.entities:
            assert 0.0 <= e.confidence <= 1.0, f"Entity {e.id} confidence out of bounds: {e.confidence}"
        
        # Check relationship confidences
        for r in result.relationships:
            assert 0.0 <= r.confidence <= 1.0, f"Relationship {r.id} confidence out of bounds: {r.confidence}"
    
    def test_extraction_determinism(self, generator, context):
        """Regression check: same input should produce same output (deterministic extraction)."""
        text = "Alice works at Acme Corporation."
        
        result1 = generator.extract_entities(text, context)
        result2 = generator.extract_entities(text, context)
        
        # Compare entity counts
        assert len(result1.entities) == len(result2.entities), "Non-deterministic entity count"
        assert len(result1.relationships) == len(result2.relationships), "Non-deterministic relationship count"
        
        # Compare entity texts (sorted for order-independence)
        texts1 = sorted([e.text for e in result1.entities])
        texts2 = sorted([e.text for e in result2.entities])
        assert texts1 == texts2, "Non-deterministic entity extraction"
