"""Reusable legal corpus framework interfaces.

The framework defines jurisdiction-neutral contracts for acquiring,
normalizing, addressing, indexing, publishing, and validating legal corpora.
Concrete jurisdictions keep their source-specific logic behind these
interfaces. The first implementation is the Netherlands BWBR pipeline.
"""

from .interfaces import (
    BM25IndexBuilder,
    CIDGenerator,
    DiscoveryProvider,
    DiscoveryRecord,
    FetchProvider,
    FetchedDocument,
    HierarchyExtractor,
    HierarchyNode,
    HuggingFacePublisher,
    IndexBuildResult,
    IntegrityValidator,
    JsonLdGraphBuilder,
    JurisdictionSpec,
    LawStatus,
    LegalCorpusJurisdiction,
    PackageBuildResult,
    PackageBuilder,
    ParsedArticleRecord,
    ParsedLawRecord,
    Parser,
    PublicationResult,
    STATUS_FIELD_NAMES,
    StatusClassifier,
    StatusMetadata,
    VectorIndexBuilder,
)
from .registry import available_jurisdictions, get_jurisdiction, register_jurisdiction

__all__ = [
    "BM25IndexBuilder",
    "CIDGenerator",
    "DiscoveryProvider",
    "DiscoveryRecord",
    "FetchProvider",
    "FetchedDocument",
    "HierarchyExtractor",
    "HierarchyNode",
    "HuggingFacePublisher",
    "IndexBuildResult",
    "IntegrityValidator",
    "JsonLdGraphBuilder",
    "JurisdictionSpec",
    "LawStatus",
    "LegalCorpusJurisdiction",
    "PackageBuildResult",
    "PackageBuilder",
    "ParsedArticleRecord",
    "ParsedLawRecord",
    "Parser",
    "PublicationResult",
    "STATUS_FIELD_NAMES",
    "StatusClassifier",
    "StatusMetadata",
    "VectorIndexBuilder",
    "available_jurisdictions",
    "get_jurisdiction",
    "register_jurisdiction",
]
