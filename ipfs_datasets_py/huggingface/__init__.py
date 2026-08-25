"""Read-only, immutable Hugging Face source contracts.

The package deliberately performs no network access at import time.  Dataset
and bucket clients are supplied by callers, while downloaded bytes are
promoted only through the content-verified snapshot cache.
"""

from .bucket import (
    HUGGINGFACE_BUCKET_INVENTORY_SCHEMA_VERSION,
    HUGGINGFACE_BUCKET_LISTING_SCHEMA_VERSION,
    HuggingFaceBucketError,
    HuggingFaceBucketHttpClient,
    HuggingFaceBucketInventory,
    HuggingFaceBucketListing,
    HuggingFaceBucketListingObject,
    HuggingFaceBucketObject,
    HuggingFaceBucketStore,
)
from .corpus import (
    CORPUS_ROOT_SCHEMA,
    CorpusBuildError,
    DEFAULT_MAX_FILE_BYTES,
    PATENT_SOURCE_GROUP_COUNT,
    ingest_local_snapshot,
    load_release_inventory,
    plan_corpus,
    reject_path_attack,
    seal_corpus,
    seal_inventory_path,
)
from .repository import (
    HUGGINGFACE_REPOSITORY_REVISION_SCHEMA_VERSION,
    HuggingFaceRepository,
    HuggingFaceRepositoryError,
    HuggingFaceRepositoryFetcher,
    HuggingFaceRepositoryRevision,
)
from .snapshot import (
    HuggingFaceSnapshot,
    HuggingFaceSnapshotCache,
    HuggingFaceSnapshotCacheMiss,
    HuggingFaceSnapshotError,
    HuggingFaceSnapshotFetcher,
    HuggingFaceSnapshotFetchError,
    HuggingFaceSnapshotIntegrityError,
    HuggingFaceSnapshotValidationError,
    HuggingFaceStaleCacheAliasError,
)

__all__ = [
    "CORPUS_ROOT_SCHEMA",
    "CorpusBuildError",
    "DEFAULT_MAX_FILE_BYTES",
    "HUGGINGFACE_BUCKET_INVENTORY_SCHEMA_VERSION",
    "HUGGINGFACE_BUCKET_LISTING_SCHEMA_VERSION",
    "HUGGINGFACE_REPOSITORY_REVISION_SCHEMA_VERSION",
    "PATENT_SOURCE_GROUP_COUNT",
    "HuggingFaceBucketError",
    "HuggingFaceBucketHttpClient",
    "HuggingFaceBucketInventory",
    "HuggingFaceBucketListing",
    "HuggingFaceBucketListingObject",
    "HuggingFaceBucketObject",
    "HuggingFaceBucketStore",
    "HuggingFaceRepository",
    "HuggingFaceRepositoryError",
    "HuggingFaceRepositoryFetcher",
    "HuggingFaceRepositoryRevision",
    "HuggingFaceSnapshot",
    "HuggingFaceSnapshotCache",
    "HuggingFaceSnapshotCacheMiss",
    "HuggingFaceSnapshotError",
    "HuggingFaceSnapshotFetchError",
    "HuggingFaceSnapshotFetcher",
    "HuggingFaceSnapshotIntegrityError",
    "HuggingFaceSnapshotValidationError",
    "HuggingFaceStaleCacheAliasError",
    "ingest_local_snapshot",
    "load_release_inventory",
    "plan_corpus",
    "reject_path_attack",
    "seal_corpus",
    "seal_inventory_path",
]
