"""Shared type aliases for the ``ipfs_datasets_py.optimizers.graphrag`` package.

Import from here instead of redefining ``Dict[str, Any]`` etc. throughout the
codebase.  Using explicit aliases makes function signatures self-documenting.

Usage
-----
.. code-block:: python

    from ipfs_datasets_py.optimizers.graphrag.typing import OntologyDict, EntityDict

    def process(o: OntologyDict) -> EntityDict: ...
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# A raw ontology dict ({"entities": [...], "relationships": [...]})
OntologyDict = Dict[str, Any]

# A single entity dict ({"id": "...", "text": "...", "type": "...", "confidence": 0.9})
EntityDict = Dict[str, Any]

# A single relationship dict ({"id": "...", "source_id": "...", "target_id": "...", ...})
RelationshipDict = Dict[str, Any]

# Arbitrary metadata dict
MetadataDict = Dict[str, Any]

# A list of entity dicts
EntityList = List[EntityDict]

# A list of relationship dicts
RelationshipList = List[RelationshipDict]

# Fix suggestion as returned by LogicValidator.suggest_fixes
FixSuggestion = Dict[str, Any]

# Extraction action name (e.g. 'merge_duplicates', 'split_entity')
ActionName = str

__all__ = [
    "OntologyDict",
    "EntityDict",
    "RelationshipDict",
    "MetadataDict",
    "EntityList",
    "RelationshipList",
    "FixSuggestion",
    "ActionName",
]
