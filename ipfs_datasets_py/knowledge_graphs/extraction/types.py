"""
Shared types and imports for knowledge graph extraction.

This module provides common types, constants, and imports used across
the extraction package.
"""

import re
import uuid
import json
import requests
from dataclasses import dataclass, field
from typing import Dict, List, Any, Set, Optional, Tuple, Union
from collections import defaultdict

# Import the Wikipedia knowledge graph tracer for enhanced tracing capabilities
try:
    from ipfs_datasets_py.ml.llm.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer
    HAVE_TRACER = True
except ImportError:
    WikipediaKnowledgeGraphTracer = None
    HAVE_TRACER = False

# Try to import accelerate integration for distributed inference
try:
    from ipfs_datasets_py.ml.accelerate_integration import (
        AccelerateManager,
        is_accelerate_available,
        get_accelerate_status
    )
    HAVE_ACCELERATE = True
except ImportError:
    HAVE_ACCELERATE = False
    AccelerateManager = None
    is_accelerate_available = lambda: False
    get_accelerate_status = lambda: {"available": False}


# Type aliases for clarity
EntityID = str
RelationshipID = str
EntityType = str
RelationshipType = str


# Constants
DEFAULT_CONFIDENCE = 1.0
MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0


__all__ = [
    # Core types
    'EntityID',
    'RelationshipID',
    'EntityType',
    'RelationshipType',
    
    # Constants
    'DEFAULT_CONFIDENCE',
    'MIN_CONFIDENCE',
    'MAX_CONFIDENCE',
    
    # Feature flags
    'HAVE_TRACER',
    'HAVE_ACCELERATE',
    
    # Optional imports
    'WikipediaKnowledgeGraphTracer',
    'AccelerateManager',
    'is_accelerate_available',
    'get_accelerate_status',
    
    # Standard library
    're',
    'uuid',
    'json',
    'requests',
    'dataclass',
    'field',
    'Dict',
    'List',
    'Any',
    'Set',
    'Optional',
    'Tuple',
    'Union',
    'defaultdict',
]
