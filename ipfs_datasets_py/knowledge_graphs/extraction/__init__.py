"""
Knowledge graph extraction package.

This package contains refactored extraction functionality from
knowledge_graph_extraction.py (2,969 lines), split into focused modules.

CURRENT STATUS: Active development (Phase 3 Task 3.2)
- types.py: Shared types and imports ✅
- entities.py: Entity class (planned)
- relationships.py: Relationship class (planned)
- graph.py: KnowledgeGraph class (planned)
- extractor.py: Extraction logic (planned)
- validator.py: Validation and SPARQL (planned)
- wikipedia.py: Wikipedia integration (planned)

Package Structure:
```
extraction/
├── __init__.py        # Public API exports
├── types.py           # Shared types and imports ✅
├── entities.py        # Entity class (~380 lines)
├── relationships.py   # Relationship class (~420 lines)
├── graph.py           # KnowledgeGraph container (~510 lines)
├── extractor.py       # Main extraction logic (~620 lines)
├── validator.py       # Validation & SPARQL (~390 lines)
└── wikipedia.py       # Wikipedia integration (~310 lines)
```

Backward Compatibility:
The original knowledge_graph_extraction.py file will remain in place
with imports from this package, ensuring zero breaking changes.

Usage (after migration):
```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    Entity,
    Relationship,
    KnowledgeGraph,
    KnowledgeGraphExtractor
)
```

Legacy usage (still supported):
```python
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
    Entity,
    Relationship,
    KnowledgeGraph,
    KnowledgeGraphExtractor
)
```
"""

# Import shared types for package-wide use
from .types import (
    EntityID,
    RelationshipID,
    EntityType,
    RelationshipType,
    DEFAULT_CONFIDENCE,
    MIN_CONFIDENCE,
    MAX_CONFIDENCE,
    HAVE_TRACER,
    HAVE_ACCELERATE,
    WikipediaKnowledgeGraphTracer,
    AccelerateManager,
    is_accelerate_available,
    get_accelerate_status,
)

# Future imports (will be uncommented as modules are created):
# from .entities import Entity
# from .relationships import Relationship
# from .graph import KnowledgeGraph
# from .extractor import KnowledgeGraphExtractor, KnowledgeGraphExtractorWithValidation
# from .validator import validate_with_sparql
# from .wikipedia import extract_from_wikipedia


__all__ = [
    # Types (available now)
    'EntityID',
    'RelationshipID',
    'EntityType',
    'RelationshipType',
    'DEFAULT_CONFIDENCE',
    'MIN_CONFIDENCE',
    'MAX_CONFIDENCE',
    'HAVE_TRACER',
    'HAVE_ACCELERATE',
    'WikipediaKnowledgeGraphTracer',
    'AccelerateManager',
    'is_accelerate_available',
    'get_accelerate_status',
    
    # Classes (will be added as modules are created)
    # 'Entity',
    # 'Relationship',
    # 'KnowledgeGraph',
    # 'KnowledgeGraphExtractor',
    # 'KnowledgeGraphExtractorWithValidation',
]


__version__ = '0.1.0'
__phase__ = 'Phase 3 Task 3.2 - Package Structure'
__status__ = 'In Development'
