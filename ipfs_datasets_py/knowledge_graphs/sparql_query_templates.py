"""
.. deprecated::

    This module has been relocated to
    ``ipfs_datasets_py.knowledge_graphs.query.sparql_templates``.
    Update your imports accordingly.
"""
import warnings
warnings.warn(
    "ipfs_datasets_py.knowledge_graphs.sparql_query_templates is deprecated. "
    "Use ipfs_datasets_py.knowledge_graphs.query.sparql_templates instead.",
    DeprecationWarning,
    stacklevel=2,
)
from ipfs_datasets_py.knowledge_graphs.query.sparql_templates import *  # noqa: F401, F403
from ipfs_datasets_py.knowledge_graphs.query.sparql_templates import (  # noqa: F401
    build_entity_query,
    build_entity_properties_query,
    build_direct_relationship_query,
    build_inverse_relationship_query,
    build_entity_type_query,
    build_path_relationship_query,
    build_similar_entities_query,
    build_property_stats_query,
    build_property_validation_query,
)
