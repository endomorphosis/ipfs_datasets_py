"""
Knowledge graph extraction package.

This package will contain refactored extraction functionality from
knowledge_graph_extraction.py (2,969 lines).

CURRENT STATUS: Planning phase
- Structure defined but not yet populated
- Original file remains in place to avoid breaking changes
- Migration will happen gradually as test coverage improves

Future structure:
- entities.py: Entity and relationship definitions
- extractors.py: Extraction algorithms
- analyzers.py: Semantic analysis
- builders.py: Graph construction

For now, use the original module:
    from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
        KnowledgeGraphExtractor
    )
"""

import warnings

_MIGRATION_MESSAGE = """
The extraction/ package is currently in planning phase.

Please continue using:
    from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import ...

Migration will occur gradually over the next few months.
See docs/MIGRATION_GUIDE.md for details.
"""

def _show_migration_notice():
    """Show migration notice."""
    warnings.warn(_MIGRATION_MESSAGE, FutureWarning, stacklevel=3)


__all__ = []
