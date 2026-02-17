# Knowledge Graphs Refactoring: Implementation Guide for Developers

**Version:** 1.0  
**Date:** February 16, 2026  
**Audience:** Developers implementing the refactoring plan  

---

## 🎯 Purpose

This guide provides practical, step-by-step instructions for developers implementing the knowledge graphs refactoring plan. It supplements the master plan with concrete examples, commands, and best practices.

---

## 🚀 Getting Started

### Prerequisites

**Required Skills:**
- Python 3.12+ proficiency
- Experience with pytest and test-driven development
- Understanding of refactoring patterns
- Familiarity with graph databases
- Git/GitHub workflow knowledge

**Required Tools:**
```bash
# Core development tools
python 3.12+
pip
git
pytest
pytest-cov
mypy
flake8

# Optional but recommended
pytest-parallel
pytest-xdist
radon (complexity analysis)
coverage (detailed coverage reports)
```

### Environment Setup

```bash
# 1. Clone and setup repository
cd /path/to/repository
git checkout main
git pull origin main

# 2. Create feature branch for your phase
git checkout -b feature/knowledge-graphs-phase-1-tests

# 3. Install dependencies
pip install -e ".[test]"

# 4. Verify test environment
pytest tests/unit/knowledge_graphs/lineage/ -v

# 5. Run baseline coverage
pytest --cov=ipfs_datasets_py.knowledge_graphs \
       --cov-report=html \
       --cov-report=term
```

### Project Structure Understanding

```
ipfs_datasets_py/knowledge_graphs/
├── __init__.py                    # Main package exports
│
├── 🎯 TARGET FILES (to refactor)
│   ├── knowledge_graph_extraction.py      (2,969 lines)
│   ├── cross_document_lineage.py          (4,066 lines)
│   ├── cross_document_lineage_enhanced.py (2,357 lines)
│   └── core/query_executor.py             (1,960 lines)
│
├── ✅ WELL-ORGANIZED PACKAGES (keep)
│   ├── lineage/                   (NEW - production ready)
│   ├── neo4j_compat/              (Modern API)
│   ├── cypher/                    (Query language)
│   ├── jsonld/                    (Semantic web)
│   ├── query/                     (Query engine)
│   ├── storage/                   (Backends)
│   ├── indexing/                  (Indexes)
│   └── transactions/              (ACID)
│
└── 📋 PLANNED PACKAGES (to create)
    └── extraction/                (Refactored extraction code)

tests/unit/knowledge_graphs/
├── lineage/                       (67 tests - ✅ done)
└── [TO CREATE]                    (100+ tests needed)
```

---

## 📋 Phase-by-Phase Implementation

## Phase 1: Test Infrastructure (Weeks 1-3)

### Task 1.1: Set Up Test Infrastructure (4 hours)

**Goal:** Create comprehensive test framework

**Step 1: Create Test Directory Structure**

```bash
# Create test directories
mkdir -p tests/unit/knowledge_graphs/
mkdir -p tests/integration/knowledge_graphs/

# Create __init__.py files
touch tests/unit/knowledge_graphs/__init__.py
touch tests/integration/knowledge_graphs/__init__.py
```

**Step 2: Create conftest.py with Shared Fixtures**

```python
# tests/unit/knowledge_graphs/conftest.py
"""Shared fixtures for knowledge graphs tests."""

import pytest
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
    Entity, Relationship, KnowledgeGraph, KnowledgeGraphExtractor
)

@pytest.fixture
def sample_text():
    """Sample text for extraction tests."""
    return """
    Apple Inc. is an American multinational technology company 
    headquartered in Cupertino, California. Steve Jobs founded 
    Apple in 1976 with Steve Wozniak.
    """

@pytest.fixture
def sample_entities():
    """Sample entities for testing."""
    return [
        Entity(
            id="e1",
            text="Apple Inc.",
            type="ORGANIZATION",
            metadata={"confidence": 0.95}
        ),
        Entity(
            id="e2",
            text="Steve Jobs",
            type="PERSON",
            metadata={"confidence": 0.98}
        ),
        Entity(
            id="e3",
            text="Cupertino",
            type="LOCATION",
            metadata={"confidence": 0.92}
        ),
    ]

@pytest.fixture
def sample_relationships(sample_entities):
    """Sample relationships for testing."""
    return [
        Relationship(
            source=sample_entities[1],  # Steve Jobs
            target=sample_entities[0],  # Apple Inc.
            type="FOUNDED",
            confidence=0.90
        ),
        Relationship(
            source=sample_entities[0],  # Apple Inc.
            target=sample_entities[2],  # Cupertino
            type="LOCATED_IN",
            confidence=0.88
        ),
    ]

@pytest.fixture
def knowledge_graph(sample_entities, sample_relationships):
    """Sample knowledge graph for testing."""
    kg = KnowledgeGraph()
    for entity in sample_entities:
        kg.add_entity(entity)
    for relationship in sample_relationships:
        kg.add_relationship(relationship)
    return kg

@pytest.fixture
def extractor():
    """Knowledge graph extractor instance."""
    return KnowledgeGraphExtractor()
```

**Step 3: Configure pytest**

```ini
# pytest.ini (in repository root)
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = 
    -v
    --strict-markers
    --tb=short
    --disable-warnings
markers =
    unit: Unit tests
    integration: Integration tests
    slow: Slow running tests
    requires_spacy: Requires spaCy model
    requires_gpu: Requires GPU
```

**Step 4: Configure Coverage**

```ini
# .coveragerc (in repository root, or update existing)
[run]
source = ipfs_datasets_py
omit = 
    */tests/*
    */test_*.py
    */__pycache__/*
    */venv/*

[report]
precision = 2
skip_covered = False
skip_empty = True
sort = Cover

[html]
directory = htmlcov
```

**Validation:**
```bash
# Run tests to verify setup
pytest tests/unit/knowledge_graphs/ -v

# Expected output:
# tests/unit/knowledge_graphs/lineage/test_types.py ............ [100%]
# ================= X passed in Y seconds =================
```

---

### Task 1.2: Unit Tests for knowledge_graph_extraction.py (12 hours)

**Goal:** Achieve 80%+ coverage for extraction module

**Step 1: Create Test File Structure**

```python
# tests/unit/knowledge_graphs/test_extraction.py
"""
Unit tests for knowledge_graph_extraction module.

Following GIVEN-WHEN-THEN format as per repository standards.
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
    Entity,
    Relationship,
    KnowledgeGraph,
    KnowledgeGraphExtractor,
    KnowledgeGraphExtractorWithValidation,
    EntityType,
)


class TestEntity:
    """Test Entity class."""
    
    def test_entity_creation_basic(self):
        """
        GIVEN basic entity attributes
        WHEN creating an Entity instance
        THEN entity is created with correct attributes
        """
        # GIVEN
        entity_id = "e1"
        text = "Apple Inc."
        entity_type = "ORGANIZATION"
        
        # WHEN
        entity = Entity(
            id=entity_id,
            text=text,
            type=entity_type,
            metadata={}
        )
        
        # THEN
        assert entity.id == entity_id
        assert entity.text == text
        assert entity.type == entity_type
        assert isinstance(entity.metadata, dict)
    
    def test_entity_with_metadata(self):
        """
        GIVEN entity with metadata
        WHEN creating Entity
        THEN metadata is stored correctly
        """
        # GIVEN
        metadata = {
            "confidence": 0.95,
            "source": "spacy",
            "span": (0, 10)
        }
        
        # WHEN
        entity = Entity(
            id="e1",
            text="Apple Inc.",
            type="ORGANIZATION",
            metadata=metadata
        )
        
        # THEN
        assert entity.metadata["confidence"] == 0.95
        assert entity.metadata["source"] == "spacy"
        assert entity.metadata["span"] == (0, 10)
    
    def test_entity_equality(self):
        """
        GIVEN two entities with same attributes
        WHEN comparing them
        THEN they should be equal
        """
        # GIVEN
        entity1 = Entity(id="e1", text="Apple", type="ORG", metadata={})
        entity2 = Entity(id="e1", text="Apple", type="ORG", metadata={})
        
        # WHEN/THEN
        assert entity1 == entity2
    
    def test_entity_hash(self):
        """
        GIVEN an entity
        WHEN getting its hash
        THEN hash is consistent
        """
        # GIVEN
        entity = Entity(id="e1", text="Apple", type="ORG", metadata={})
        
        # WHEN
        hash1 = hash(entity)
        hash2 = hash(entity)
        
        # THEN
        assert hash1 == hash2
        assert isinstance(hash1, int)


class TestRelationship:
    """Test Relationship class."""
    
    def test_relationship_creation(self, sample_entities):
        """
        GIVEN source and target entities
        WHEN creating a Relationship
        THEN relationship is created correctly
        """
        # GIVEN
        source = sample_entities[0]
        target = sample_entities[1]
        rel_type = "FOUNDED_BY"
        
        # WHEN
        relationship = Relationship(
            source=source,
            target=target,
            type=rel_type,
            confidence=0.9
        )
        
        # THEN
        assert relationship.source == source
        assert relationship.target == target
        assert relationship.type == rel_type
        assert relationship.confidence == 0.9
    
    def test_relationship_validation(self, sample_entities):
        """
        GIVEN invalid confidence value
        WHEN creating Relationship
        THEN raises ValueError
        """
        # GIVEN
        source = sample_entities[0]
        target = sample_entities[1]
        
        # WHEN/THEN
        with pytest.raises(ValueError):
            Relationship(
                source=source,
                target=target,
                type="TEST",
                confidence=1.5  # Invalid: >1.0
            )


class TestKnowledgeGraph:
    """Test KnowledgeGraph class."""
    
    def test_knowledge_graph_creation(self):
        """
        GIVEN nothing
        WHEN creating KnowledgeGraph
        THEN empty graph is created
        """
        # WHEN
        kg = KnowledgeGraph()
        
        # THEN
        assert len(kg.entities) == 0
        assert len(kg.relationships) == 0
    
    def test_add_entity(self, sample_entities):
        """
        GIVEN a KnowledgeGraph and entity
        WHEN adding entity
        THEN entity is added to graph
        """
        # GIVEN
        kg = KnowledgeGraph()
        entity = sample_entities[0]
        
        # WHEN
        kg.add_entity(entity)
        
        # THEN
        assert entity.id in kg.entities
        assert kg.entities[entity.id] == entity
    
    def test_add_duplicate_entity(self, sample_entities):
        """
        GIVEN a KnowledgeGraph with existing entity
        WHEN adding same entity again
        THEN entity is updated, not duplicated
        """
        # GIVEN
        kg = KnowledgeGraph()
        entity = sample_entities[0]
        kg.add_entity(entity)
        
        # WHEN
        kg.add_entity(entity)
        
        # THEN
        assert len(kg.entities) == 1
    
    def test_add_relationship(self, knowledge_graph, sample_relationships):
        """
        GIVEN a KnowledgeGraph
        WHEN adding relationship
        THEN relationship is added
        """
        # GIVEN
        kg = knowledge_graph
        initial_count = len(kg.relationships)
        
        # WHEN
        new_rel = sample_relationships[0]
        kg.add_relationship(new_rel)
        
        # THEN
        assert len(kg.relationships) > initial_count
    
    def test_get_entity_relationships(self, knowledge_graph, sample_entities):
        """
        GIVEN a KnowledgeGraph with relationships
        WHEN getting entity relationships
        THEN returns correct relationships
        """
        # GIVEN
        kg = knowledge_graph
        entity = sample_entities[0]
        
        # WHEN
        relationships = kg.get_entity_relationships(entity.id)
        
        # THEN
        assert len(relationships) > 0
        assert all(
            r.source.id == entity.id or r.target.id == entity.id
            for r in relationships
        )
    
    def test_query_by_type(self, knowledge_graph):
        """
        GIVEN a KnowledgeGraph
        WHEN querying by entity type
        THEN returns entities of that type
        """
        # GIVEN
        kg = knowledge_graph
        
        # WHEN
        orgs = kg.query_by_type("ORGANIZATION")
        
        # THEN
        assert len(orgs) > 0
        assert all(e.type == "ORGANIZATION" for e in orgs)
    
    def test_serialize_deserialize(self, knowledge_graph):
        """
        GIVEN a KnowledgeGraph
        WHEN serializing and deserializing
        THEN graph is preserved
        """
        # GIVEN
        kg = knowledge_graph
        
        # WHEN
        serialized = kg.to_dict()
        deserialized = KnowledgeGraph.from_dict(serialized)
        
        # THEN
        assert len(deserialized.entities) == len(kg.entities)
        assert len(deserialized.relationships) == len(kg.relationships)


class TestKnowledgeGraphExtractor:
    """Test KnowledgeGraphExtractor class."""
    
    def test_extractor_initialization(self):
        """
        GIVEN nothing
        WHEN creating KnowledgeGraphExtractor
        THEN extractor is initialized
        """
        # WHEN
        extractor = KnowledgeGraphExtractor()
        
        # THEN
        assert extractor is not None
        assert hasattr(extractor, 'extract')
    
    def test_extract_basic(self, extractor, sample_text):
        """
        GIVEN sample text
        WHEN extracting knowledge graph
        THEN entities and relationships are extracted
        """
        # GIVEN/WHEN
        kg = extractor.extract(sample_text)
        
        # THEN
        assert isinstance(kg, KnowledgeGraph)
        assert len(kg.entities) > 0
        # Note: Actual numbers depend on NLP model
    
    @pytest.mark.requires_spacy
    def test_extract_entities_with_spacy(self, extractor, sample_text):
        """
        GIVEN sample text and spaCy model
        WHEN extracting entities
        THEN entities are extracted with correct types
        """
        # GIVEN/WHEN
        kg = extractor.extract(sample_text)
        
        # THEN
        entity_types = {e.type for e in kg.entities.values()}
        # Should contain common entity types
        assert len(entity_types) > 0
    
    def test_extract_empty_text(self, extractor):
        """
        GIVEN empty text
        WHEN extracting
        THEN returns empty knowledge graph
        """
        # GIVEN
        empty_text = ""
        
        # WHEN
        kg = extractor.extract(empty_text)
        
        # THEN
        assert len(kg.entities) == 0
        assert len(kg.relationships) == 0
    
    def test_extract_with_custom_config(self):
        """
        GIVEN custom extractor configuration
        WHEN creating extractor
        THEN configuration is applied
        """
        # GIVEN
        config = {
            "min_confidence": 0.8,
            "max_entities": 100
        }
        
        # WHEN
        extractor = KnowledgeGraphExtractor(config=config)
        
        # THEN
        assert extractor.config["min_confidence"] == 0.8
        assert extractor.config["max_entities"] == 100


class TestKnowledgeGraphExtractorWithValidation:
    """Test KnowledgeGraphExtractorWithValidation class."""
    
    def test_validation_extractor_creation(self):
        """
        GIVEN nothing
        WHEN creating validation extractor
        THEN extractor with validation is created
        """
        # WHEN
        extractor = KnowledgeGraphExtractorWithValidation()
        
        # THEN
        assert extractor is not None
        assert hasattr(extractor, 'validate')
    
    def test_extract_and_validate(self, sample_text):
        """
        GIVEN sample text
        WHEN extracting with validation
        THEN validated knowledge graph is returned
        """
        # GIVEN
        extractor = KnowledgeGraphExtractorWithValidation()
        
        # WHEN
        kg = extractor.extract(sample_text)
        
        # THEN
        assert isinstance(kg, KnowledgeGraph)
        # All entities should pass validation
        for entity in kg.entities.values():
            assert entity.id is not None
            assert entity.text is not None
    
    def test_validation_filters_low_confidence(self):
        """
        GIVEN extractor with confidence threshold
        WHEN extracting entities
        THEN low confidence entities are filtered
        """
        # GIVEN
        config = {"min_confidence": 0.9}
        extractor = KnowledgeGraphExtractorWithValidation(config=config)
        
        # WHEN
        kg = extractor.extract("Some text here")
        
        # THEN
        # All entities should meet minimum confidence
        for entity in kg.entities.values():
            if "confidence" in entity.metadata:
                assert entity.metadata["confidence"] >= 0.9


# Integration tests
class TestKnowledgeGraphIntegration:
    """Integration tests for full extraction pipeline."""
    
    @pytest.mark.integration
    def test_full_pipeline(self, sample_text):
        """
        GIVEN sample text
        WHEN running full extraction pipeline
        THEN complete knowledge graph is produced
        """
        # GIVEN
        extractor = KnowledgeGraphExtractorWithValidation()
        
        # WHEN
        kg = extractor.extract(sample_text)
        
        # THEN
        # Should have entities
        assert len(kg.entities) > 0
        
        # Entities should have valid types
        for entity in kg.entities.values():
            assert entity.type is not None
            assert len(entity.text) > 0
        
        # Should be serializable
        serialized = kg.to_dict()
        assert "entities" in serialized
        assert "relationships" in serialized
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_large_document_extraction(self):
        """
        GIVEN a large document
        WHEN extracting knowledge graph
        THEN extraction completes successfully
        """
        # GIVEN
        large_text = "Sample text. " * 1000  # ~13K chars
        extractor = KnowledgeGraphExtractor()
        
        # WHEN
        kg = extractor.extract(large_text)
        
        # THEN
        assert kg is not None
        # Should handle large documents without errors
```

**Step 2: Run Tests and Check Coverage**

```bash
# Run new tests
pytest tests/unit/knowledge_graphs/test_extraction.py -v

# Check coverage for extraction module
pytest tests/unit/knowledge_graphs/test_extraction.py \
    --cov=ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction \
    --cov-report=term \
    --cov-report=html

# View HTML coverage report
open htmlcov/index.html  # macOS
# or
xdg-open htmlcov/index.html  # Linux
```

**Step 3: Iterate Until 80%+ Coverage**

```bash
# Identify uncovered lines
pytest --cov=ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction \
       --cov-report=term-missing

# Add tests for uncovered areas
# Repeat until coverage >= 80%
```

---

### Task 1.3-1.7: Additional Test Tasks

Follow similar pattern for:
- `test_lineage_legacy.py` (8 hours)
- `test_reasoning.py` (6 hours)
- `test_advanced_extractor.py` (6 hours)
- Integration tests (10 hours)
- CI/CD integration (4 hours)

---

## Phase 2: Lineage Migration (Week 4)

### Task 2.1: Add Deprecation Warnings (2 hours)

**Step 1: Add Warning to cross_document_lineage.py**

```python
# ipfs_datasets_py/knowledge_graphs/cross_document_lineage.py
# Add at the TOP of the file, before any other imports

"""
Cross-document lineage tracking (DEPRECATED).

⚠️ DEPRECATION NOTICE:
This module is deprecated and will be removed in version 2.0 (August 2026).
Please migrate to the new lineage package:

    from ipfs_datasets_py.knowledge_graphs.lineage import LineageTracker

See KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md for migration instructions.
"""

import warnings

warnings.warn(
    "cross_document_lineage is deprecated. "
    "Use 'from ipfs_datasets_py.knowledge_graphs.lineage import LineageTracker' instead. "
    "This module will be removed in version 2.0 (6 months). "
    "See KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md for migration instructions.",
    DeprecationWarning,
    stacklevel=2
)

# Rest of the file continues...
```

**Step 2: Add Warning to cross_document_lineage_enhanced.py**

```python
# Similar deprecation warning in cross_document_lineage_enhanced.py
```

**Step 3: Test Deprecation Warnings**

```python
# tests/unit/knowledge_graphs/test_deprecation_warnings.py
"""Test deprecation warnings."""

import pytest
import warnings


def test_cross_document_lineage_deprecation():
    """
    GIVEN importing from deprecated module
    WHEN importing LineageTracker
    THEN deprecation warning is raised
    """
    with pytest.warns(DeprecationWarning, match="cross_document_lineage is deprecated"):
        from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import (
            CrossDocumentLineageTracker
        )
```

---

### Best Practices Throughout Implementation

#### Test-Driven Development

```python
# 1. Write test FIRST
def test_new_feature():
    """
    GIVEN ...
    WHEN ...
    THEN ...
    """
    # GIVEN
    setup_code()
    
    # WHEN
    result = function_to_test()
    
    # THEN
    assert result == expected
    
# 2. Run test (it should FAIL)
# 3. Implement feature
# 4. Run test (it should PASS)
# 5. Refactor if needed
```

#### Code Review Checklist

Before submitting PR:
- [ ] All tests passing
- [ ] Coverage targets met (80%+ for modified modules)
- [ ] No linting errors (`flake8 ipfs_datasets_py/knowledge_graphs/`)
- [ ] Type hints added (`mypy ipfs_datasets_py/knowledge_graphs/`)
- [ ] Docstrings updated
- [ ] CHANGELOG.md updated
- [ ] Backward compatibility maintained
- [ ] Performance not regressed

#### Git Workflow

```bash
# 1. Create feature branch
git checkout -b feature/kg-phase-X-description

# 2. Make incremental commits
git add file1.py file2.py
git commit -m "Add unit tests for Entity class

- Test entity creation
- Test entity equality
- Test entity hashing
- Achieve 85% coverage on Entity class"

# 3. Push and create PR
git push origin feature/kg-phase-X-description

# 4. Create PR with detailed description
# Use template from master plan
```

---

## 🔧 Debugging and Troubleshooting

### Common Issues

**Issue: Import Errors**
```bash
# Solution: Ensure package is installed in editable mode
pip install -e .
```

**Issue: Tests Not Discovered**
```bash
# Solution: Check pytest configuration
pytest --collect-only

# Ensure test files start with test_
# Ensure test functions start with test_
```

**Issue: Coverage Not Working**
```bash
# Solution: Check .coveragerc configuration
# Ensure source path is correct
coverage run -m pytest tests/
coverage report
```

---

## 📚 Resources

### Documentation
- Master Plan: KNOWLEDGE_GRAPHS_MASTER_REFACTORING_PLAN_2026_02_16.md
- Quick Reference: KNOWLEDGE_GRAPHS_QUICK_REFERENCE_2026_02_16.md
- Migration Guide: KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md

### Tools
- pytest docs: https://docs.pytest.org/
- coverage.py: https://coverage.readthedocs.io/
- mypy: https://mypy.readthedocs.io/

### Internal
- Repository testing standards: docs/_example_test_format.md
- Repository docstring format: docs/_example_docstring_format.md

---

**Document Version:** 1.0  
**Last Updated:** February 16, 2026  
**Maintained By:** Development Team  

**For questions or support:**
- GitHub Issues: Tag with `knowledge-graphs`
- Documentation: See related documents in docs/
