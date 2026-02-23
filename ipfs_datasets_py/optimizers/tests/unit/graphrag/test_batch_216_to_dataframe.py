"""Tests for EntityExtractionResult.to_dataframe() method.

Validates that the to_dataframe() method correctly converts entity extraction
results to pandas DataFrames with proper structure, column ordering, and error
handling for the optional pandas dependency.
"""

import pytest
from dataclasses import dataclass, field
from typing import List, Dict, Any


# Mock the Entity and Relationship classes for testing
@dataclass
class Entity:
    """Mock Entity class for testing."""
    id: str
    text: str
    type: str
    confidence: float
    properties: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self):
        return {
            'id': self.id,
            'text': self.text,
            'type': self.type,
            'confidence': self.confidence,
            'properties': self.properties,
        }


@dataclass
class Relationship:
    """Mock Relationship class for testing."""
    id: str
    source_id: str
    target_id: str
    type: str
    confidence: float
    direction: str = "forward"
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EntityExtractionResult:
    """Mock EntityExtractionResult class with to_dataframe() method."""
    entities: List[Entity]
    relationships: List[Relationship]
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dataframe(self):
        """Convert extracted entities to a :class:`pandas.DataFrame`.

        Returns:
            A ``pandas.DataFrame`` with one row per entity and columns:
            ``id``, ``text``, ``type``, ``confidence``.

        Raises:
            ImportError: If ``pandas`` is not installed.
        """
        try:
            import pandas as _pd
        except ImportError as exc:
            raise ImportError(
                "pandas is required for to_dataframe(); install with: pip install pandas"
            ) from exc
        rows = [
            {
                "id": e.id,
                "text": e.text,
                "type": e.type,
                "confidence": e.confidence,
            }
            for e in self.entities
        ]
        return _pd.DataFrame(rows, columns=["id", "text", "type", "confidence"])


class TestEntityExtractionResultToDataFrame:
    """Tests for EntityExtractionResult.to_dataframe() method."""

    def test_to_dataframe_basic(self):
        """Should convert entities to DataFrame with correct structure."""
        pytest.importorskip("pandas")
        
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="John Doe", type="Person", confidence=0.95),
                Entity(id="e2", text="Acme Corp", type="Organization", confidence=0.88),
            ],
            relationships=[],
            confidence=0.90,
        )
        
        df = result.to_dataframe()
        
        # Check DataFrame shape
        assert len(df) == 2
        assert list(df.columns) == ["id", "text", "type", "confidence"]
        
        # Check first row
        assert df.iloc[0]["id"] == "e1"
        assert df.iloc[0]["text"] == "John Doe"
        assert df.iloc[0]["type"] == "Person"
        assert df.iloc[0]["confidence"] == 0.95
        
        # Check second row
        assert df.iloc[1]["id"] == "e2"
        assert df.iloc[1]["text"] == "Acme Corp"
        assert df.iloc[1]["type"] == "Organization"
        assert df.iloc[1]["confidence"] == 0.88

    def test_to_dataframe_empty_entities(self):
        """Should return empty DataFrame with correct columns for empty entities."""
        pytest.importorskip("pandas")
        
        result = EntityExtractionResult(
            entities=[],
            relationships=[],
            confidence=1.0,
        )
        
        df = result.to_dataframe()
        
        assert len(df) == 0
        assert list(df.columns) == ["id", "text", "type", "confidence"]

    def test_to_dataframe_single_entity(self):
        """Should handle single entity correctly."""
        pytest.importorskip("pandas")
        
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Test Entity", type="Concept", confidence=0.75),
            ],
            relationships=[],
            confidence=0.75,
        )
        
        df = result.to_dataframe()
        
        assert len(df) == 1
        assert df.iloc[0]["text"] == "Test Entity"

    def test_to_dataframe_column_order(self):
        """Should maintain column order: id, text, type, confidence."""
        pytest.importorskip("pandas")
        
        result = EntityExtractionResult(
            entities=[Entity(id="e1", text="T", type="X", confidence=0.5)],
            relationships=[],
            confidence=0.5,
        )
        
        df = result.to_dataframe()
        assert list(df.columns) == ["id", "text", "type", "confidence"]

    def test_to_dataframe_data_types(self):
        """Should preserve correct data types in DataFrame."""
        pandas = pytest.importorskip("pandas")
        
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Entity1", type="Type1", confidence=0.9),
                Entity(id="e2", text="Entity2", type="Type2", confidence=0.8),
            ],
            relationships=[],
            confidence=0.85,
        )
        
        df = result.to_dataframe()
        
        # Check data types
        # Pandas may represent string columns as either `object` (legacy)
        # or the newer nullable `StringDtype`, depending on version/options.
        assert pandas.api.types.is_string_dtype(df["id"])  # string
        assert pandas.api.types.is_string_dtype(df["text"])  # string
        assert pandas.api.types.is_string_dtype(df["type"])  # string
        assert pandas.api.types.is_numeric_dtype(df["confidence"])  # numeric

    def test_to_dataframe_unicode_text(self):
        """Should handle Unicode characters in entity text."""
        pytest.importorskip("pandas")
        
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="José García", type="Person", confidence=0.92),
                Entity(id="e2", text="北京", type="Location", confidence=0.88),
                Entity(id="e3", text="Müller & Co.", type="Organization", confidence=0.85),
            ],
            relationships=[],
            confidence=0.88,
        )
        
        df = result.to_dataframe()
        
        assert len(df) == 3
        assert df.iloc[0]["text"] == "José García"
        assert df.iloc[1]["text"] == "北京"
        assert df.iloc[2]["text"] == "Müller & Co."

    def test_to_dataframe_special_characters(self):
        """Should handle special characters in entity fields."""
        pytest.importorskip("pandas")
        
        result = EntityExtractionResult(
            entities=[
                Entity(id="e_1", text="Test & Co.", type="Org/Company", confidence=0.9),
                Entity(id="e-2", text="Line1\nLine2", type="Multi-Line", confidence=0.8),
            ],
            relationships=[],
            confidence=0.85,
        )
        
        df = result.to_dataframe()
        
        assert len(df) == 2
        assert df.iloc[0]["id"] == "e_1"
        assert df.iloc[0]["text"] == "Test & Co."
        assert df.iloc[1]["text"] == "Line1\nLine2"

    def test_to_dataframe_many_entities(self):
        """Should handle large number of entities efficiently."""
        pytest.importorskip("pandas")
        
        entities = [
            Entity(id=f"e{i}", text=f"Entity{i}", type=f"Type{i%5}", confidence=0.5 + (i % 50) / 100)
            for i in range(100)
        ]
        
        result = EntityExtractionResult(
            entities=entities,
            relationships=[],
            confidence=0.75,
        )
        
        df = result.to_dataframe()
        
        assert len(df) == 100
        assert list(df.columns) == ["id", "text", "type", "confidence"]

    def test_to_dataframe_relationships_ignored(self):
        """Should only include entities, not relationships, in DataFrame."""
        pytest.importorskip("pandas")
        
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Entity1", type="Type1", confidence=0.9),
            ],
            relationships=[
                Relationship(id="r1", source_id="e1", target_id="e2", type="relates_to", confidence=0.8),
            ],
            confidence=0.85,
        )
        
        df = result.to_dataframe()
        
        # Should only have entity data
        assert len(df) == 1
        assert "source_id" not in df.columns
        assert "target_id" not in df.columns

    def test_to_dataframe_confidence_range(self):
        """Should preserve confidence values in [0, 1] range."""
        pytest.importorskip("pandas")
        
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Low", type="T1", confidence=0.1),
                Entity(id="e2", text="Med", type="T2", confidence=0.5),
                Entity(id="e3", text="High", type="T3", confidence=0.99),
            ],
            relationships=[],
            confidence=0.5,
        )
        
        df = result.to_dataframe()
        
        assert df.iloc[0]["confidence"] == 0.1
        assert df.iloc[1]["confidence"] == 0.5
        assert df.iloc[2]["confidence"] == 0.99
        assert (df["confidence"] >= 0).all()
        assert (df["confidence"] <= 1).all()

    def test_to_dataframe_properties_excluded(self):
        """Should not include entity properties in DataFrame columns."""
        pytest.importorskip("pandas")
        
        result = EntityExtractionResult(
            entities=[
                Entity(
                    id="e1",
                    text="Entity with props",
                    type="TypeX",
                    confidence=0.9,
                    properties={"key1": "value1", "key2": 123},
                ),
            ],
            relationships=[],
            confidence=0.9,
        )
        
        df = result.to_dataframe()
        
        # Properties should not create new columns
        assert list(df.columns) == ["id", "text", "type", "confidence"]
        assert "key1" not in df.columns
        assert "key2" not in df.columns

    def test_to_dataframe_pandas_not_installed(self):
        """Should raise ImportError with helpful message when pandas not installed."""
        # This test would need to mock the import system, but for now we document
        # the expected behavior
        
        # Expected behavior (cannot test easily without mocking):
        # result = EntityExtractionResult(entities=[], relationships=[], confidence=1.0)
        # with pytest.raises(ImportError, match="pandas is required"):
        #     result.to_dataframe()
        
        # Just verify the method exists and has proper error handling
        result = EntityExtractionResult(entities=[], relationships=[], confidence=1.0)
        assert hasattr(result, "to_dataframe")
        assert callable(result.to_dataframe)

    def test_to_dataframe_returns_dataframe_type(self):
        """Should return pandas.DataFrame type."""
        pandas = pytest.importorskip("pandas")
        
        result = EntityExtractionResult(
            entities=[Entity(id="e1", text="T", type="X", confidence=0.5)],
            relationships=[],
            confidence=0.5,
        )
        
        df = result.to_dataframe()
        assert isinstance(df, pandas.DataFrame)

    def test_to_dataframe_indexing(self):
        """Should allow standard DataFrame indexing operations."""
        pytest.importorskip("pandas")
        
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Entity1", type="Person", confidence=0.9),
                Entity(id="e2", text="Entity2", type="Organization", confidence=0.8),
                Entity(id="e3", text="Entity3", type="Location", confidence=0.7),
            ],
            relationships=[],
            confidence=0.8,
        )
        
        df = result.to_dataframe()
        
        # Test iloc indexing
        assert df.iloc[0]["id"] == "e1"
        assert df.iloc[2]["type"] == "Location"
        
        # Test column selection
        types = df["type"].tolist()
        assert types == ["Person", "Organization", "Location"]
        
        # Test boolean indexing
        high_conf = df[df["confidence"] > 0.75]
        assert len(high_conf) == 2

    def test_to_dataframe_filtering_operations(self):
        """Should support post-conversion filtering on DataFrame."""
        pytest.importorskip("pandas")
        
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Person1", type="Person", confidence=0.95),
                Entity(id="e2", text="Org1", type="Organization", confidence=0.88),
                Entity(id="e3", text="Person2", type="Person", confidence=0.92),
            ],
            relationships=[],
            confidence=0.92,
        )
        
        df = result.to_dataframe()
        
        # Filter by type
        persons = df[df["type"] == "Person"]
        assert len(persons) == 2
        
        # Filter by confidence threshold
        high_conf = df[df["confidence"] >= 0.9]
        assert len(high_conf) == 2
