"""Snapshot tests for ontology generator outputs.

These tests capture the structure and format of ontology generator outputs
and alert when they change unexpectedly. Uses JSON-based golden files.
"""

import json
import pytest
from pathlib import Path
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
)


SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"


def get_snapshot_path(snapshot_name: str) -> Path:
    """Get path to snapshot file."""
    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    return SNAPSHOTS_DIR / f"{snapshot_name}.json"


def load_snapshot(snapshot_name: str) -> dict:
    """Load a snapshot from disk."""
    path = get_snapshot_path(snapshot_name)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def save_snapshot(snapshot_name: str, data: dict) -> None:
    """Save a snapshot to disk."""
    path = get_snapshot_path(snapshot_name)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class TestEntityExtractionResultSnapshots:
    """Test Entity Extraction Result snapshots."""

    def test_basic_extraction_output_snapshot(self):
        """Snapshot of basic extraction result structure."""
        entities = [
            Entity(id="e1", text="Alice", type="Person", confidence=0.95),
            Entity(id="e2", text="Bob", type="Person", confidence=0.90),
            Entity(id="e3", text="ACME Corp", type="Organization", confidence=0.87),
        ]
        relationships = [
            Relationship(id="r1", source_id="e1", target_id="e3", type="works_for", confidence=0.92),
            Relationship(id="r2", source_id="e2", target_id="e3", type="works_for", confidence=0.88),
            Relationship(id="r3", source_id="e1", target_id="e2", type="knows", confidence=0.75),
        ]
        result = EntityExtractionResult( entities=entities, relationships=relationships, confidence=0.91, 
        )

        # Convert to JSON-serializable format
        snapshot_data = {
            "entity_count": len(result.entities),
            "relationship_count": len(result.relationships),
            "overall_confidence": result.confidence,
            "entity_types": sorted(set(e.type for e in result.entities)),
            "relationship_types": sorted(set(r.type for r in result.relationships)),
            "avg_entity_confidence": sum(e.confidence for e in result.entities) / len(result.entities),
            "avg_relationship_confidence": sum(r.confidence for r in result.relationships) / len(result.relationships),
        }

        # Compare with snapshot
        snapshot = load_snapshot("basic_extraction")
        if snapshot is None:
            # First run - save snapshot
            save_snapshot("basic_extraction", snapshot_data)
            snapshot = snapshot_data

        assert snapshot_data == snapshot, "Extraction structure snapshot mismatch"

    def test_large_extraction_snapshot(self):
        """Snapshot of larger extraction result."""
        # Create 50 entities and 100 relationships
        entities = [Entity(id=f"e{i}", text=f"Entity_{i}", type="Entity", confidence=0.85 + i*0.001) for i in range(50)]
        relationships = [
            Relationship(
                id=f"r{j}", 
                source_id=f"e{j % 50}", 
                target_id=f"e{(j+1) % 50}", 
                type="related_to", 
                confidence=0.80 + (j % 20) * 0.01
            ) 
            for j in range(100)
        ]
        result = EntityExtractionResult(
            entities=entities,
            relationships=relationships,
            confidence=0.85,
            metadata={"source": "test", "batch_size": 50},
        )

        snapshot_data = {
            "entity_count": len(result.entities),
            "relationship_count": len(result.relationships),
            "metadata_keys": sorted(result.metadata.keys()),
            "min_entity_conf": min(e.confidence for e in result.entities),
            "max_entity_conf": max(e.confidence for e in result.entities),
            "min_rel_conf": min(r.confidence for r in result.relationships),
            "max_rel_conf": max(r.confidence for r in result.relationships),
        }

        snapshot = load_snapshot("large_extraction")
        if snapshot is None:
            save_snapshot("large_extraction", snapshot_data)
            snapshot = snapshot_data

        assert snapshot_data == snapshot, "Large extraction snapshot mismatch"

    def test_extraction_with_metadata_snapshot(self):
        """Snapshot of extraction with rich metadata."""
        entities = [Entity(id="e1", text="Test", type="Test", confidence=0.9)]
        relationships = []
        
        metadata = {
            "source_file": "test.txt",
            "processing_time_ms": 123.45,
            "model_version": "2.1.0",
            "extraction_method": "llm",
            "language": "en",
            "warnings": ["Entity confidence below threshold for e5"],
            "extraction_stats": {
                "tokens_processed": 1500,
                "entities_initial": 10,
                "entities_final": 8,
                "merge_count": 2,
            },
        }
        
        result = EntityExtractionResult(
            entities=entities,
            relationships=relationships,
            confidence=0.92,
            metadata=metadata,
        )

        snapshot_data = {
            "entity_count": len(result.entities),
            "relationship_count": len(result.relationships),
            "metadata_sections": sorted(metadata.keys()),
            "has_warnings": len(metadata.get("warnings", [])) > 0,
            "tokens_processed": metadata.get("extraction_stats", {}).get("tokens_processed"),
        }

        snapshot = load_snapshot("extraction_with_metadata")
        if snapshot is None:
            save_snapshot("extraction_with_metadata", snapshot_data)
            snapshot = snapshot_data

        assert snapshot_data == snapshot, "Metadata extraction snapshot mismatch"

    def test_filter_by_type_snapshot(self):
        """Snapshot of filtered entity extraction result."""
        entities = [
            Entity(id="e1", text="Alice", type="Person", confidence=0.95),
            Entity(id="e2", text="Bob", type="Person", confidence=0.90),
            Entity(id="e3", text="ACME Corp", type="Organization", confidence=0.87),
            Entity(id="e4", text="NYC", type="Location", confidence=0.92),
        ]
        relationships = [
            Relationship(id="r1", source_id="e1", target_id="e3", type="works_for", confidence=0.92),
            Relationship(id="r2", source_id="e1", target_id="e4", type="located_in", confidence=0.88),
            Relationship(id="r3", source_id="e3", target_id="e4", type="located_in", confidence=0.85),
        ]
        result = EntityExtractionResult(entities=entities, relationships=relationships, confidence=0.91)

        # Filter by Person type
        filtered = result.filter_by_type("Person")
        
        snapshot_data = {
            "original_entity_count": len(result.entities),
            "filtered_entity_count": len(filtered.entities),
            "filtered_entity_types": sorted(set(e.type for e in filtered.entities)),
            "original_rel_count": len(result.relationships),
            "filtered_rel_count": len(filtered.relationships),
            "confidence_preserved": result.confidence == filtered.confidence,
        }

        snapshot = load_snapshot("filter_by_type")
        if snapshot is None:
            save_snapshot("filter_by_type", snapshot_data)
            snapshot = snapshot_data

        assert snapshot_data == snapshot, "Filter by type snapshot mismatch"


class TestEntityRelationshipSnapshots:
    """Test Entity and Relationship class snapshots."""

    def test_entity_to_text_snapshot(self):
        """Snapshot of Entity.to_text() format."""
        entities = [
            Entity(id="e1", text="Alice", type="Person", confidence=0.95),
            Entity(id="e2", text="Acme Inc.", type="Organization", confidence=0.87),
        ]
        
        snapshot_data = {
            "entity_text_formats": [e.to_text() for e in entities],
            "format_pattern_entity_matches": all("(" in e.to_text() for e in entities),
            "format_includes_confidence": all("conf=" in e.to_text() for e in entities),
        }

        snapshot = load_snapshot("entity_to_text")
        if snapshot is None:
            save_snapshot("entity_to_text", snapshot_data)
            snapshot = snapshot_data

        assert snapshot_data == snapshot, "Entity text format snapshot mismatch"

    def test_entity_equality_snapshot(self):
        """Snapshot of Entity equality semantics."""
        e1 = Entity(id="e1", text="Alice", type="Person", confidence=0.95)
        e2 = Entity(id="e1", text="Alice", type="Person", confidence=0.95)
        e3 = Entity(id="e1", text="Alice", type="Person", confidence=0.90)  # Different confidence
        
        snapshot_data = {
            "e1_equals_e2": e1 == e2,
            "e1_not_equals_e3": e1 != e3,
            "e1_hash_equals_e2_hash": hash(e1) == hash(e2),
            "e1_hash_equals_e3_hash": hash(e1) == hash(e3),  # Hash only uses ID
        }

        snapshot = load_snapshot("entity_equality")
        if snapshot is None:
            save_snapshot("entity_equality", snapshot_data)
            snapshot = snapshot_data

        assert snapshot_data == snapshot, "Entity equality snapshot mismatch"


class TestRelationshipSnapshots:
    """Test Relationship-specific snapshots."""

    def test_relationship_to_dict_snapshot(self):
        """Snapshot of Relationship.to_dict() structure."""
        rel = Relationship(
            id="r1",
            source_id="e1",
            target_id="e2",
            type="knows",
            properties={"strength": 0.8, "context": "colleagues"},
            confidence=0.92,
            direction="subject_to_object",
        )
        
        rel_dict = rel.to_dict()
        snapshot_data = {
            "dict_keys": sorted(rel_dict.keys()),
            "has_all_fields": all(
                k in rel_dict for k in ["id", "source_id", "target_id", "type", "confidence", "direction"]
            ),
            "properties_preserved": rel_dict.get("properties") == {"strength": 0.8, "context": "colleagues"},
        }

        snapshot = load_snapshot("relationship_to_dict")
        if snapshot is None:
            save_snapshot("relationship_to_dict", snapshot_data)
            snapshot = snapshot_data

        assert snapshot_data == snapshot, "Relationship dict snapshot mismatch"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
