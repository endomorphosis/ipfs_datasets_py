"""Test minimal OntologyComparator for import verification."""

STANDARD_DIMENSIONS = (
    "completeness",
    "consistency",
    "clarity",
    "granularity",
    "relationship_coherence",
    "domain_alignment",
)


class OntologyComparator:
    """Test class."""
    
    def __init__(self, dimensions=None):
        self.DIMENSIONS = dimensions or STANDARD_DIMENSIONS
