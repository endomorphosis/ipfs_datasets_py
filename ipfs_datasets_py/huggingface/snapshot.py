"""Generic names for the immutable Hugging Face snapshot/cache contract.

The implementation originated in the bounded SkillCenter ingest.  These are
intentional aliases, rather than subclasses or copies: old and new callers can
exchange manifests and cache entries without changing class equality,
snapshot identifiers, alias paths, or the ``skillcenter-snapshot/v1`` wire
schema.  The legacy wire spelling is retained as a compatibility contract; it
does not constrain snapshots to the SkillCenter repository.
"""

from ..logic.intent_ir.source_adapters.snapshot import (
    SkillCenterSnapshot as HuggingFaceSnapshot,
)
from ..logic.intent_ir.source_adapters.snapshot import (
    SkillCenterSnapshotCache as HuggingFaceSnapshotCache,
)
from ..logic.intent_ir.source_adapters.snapshot import (
    SkillCenterSnapshotCacheMiss as HuggingFaceSnapshotCacheMiss,
)
from ..logic.intent_ir.source_adapters.snapshot import (
    SkillCenterSnapshotError as HuggingFaceSnapshotError,
)
from ..logic.intent_ir.source_adapters.snapshot import (
    SkillCenterSnapshotFetcher as HuggingFaceSnapshotFetcher,
)
from ..logic.intent_ir.source_adapters.snapshot import (
    SkillCenterSnapshotFetchError as HuggingFaceSnapshotFetchError,
)
from ..logic.intent_ir.source_adapters.snapshot import (
    SkillCenterSnapshotIntegrityError as HuggingFaceSnapshotIntegrityError,
)
from ..logic.intent_ir.source_adapters.snapshot import (
    SkillCenterSnapshotValidationError as HuggingFaceSnapshotValidationError,
)
from ..logic.intent_ir.source_adapters.snapshot import (
    SkillCenterStaleCacheAliasError as HuggingFaceStaleCacheAliasError,
)

__all__ = [
    "HuggingFaceSnapshot",
    "HuggingFaceSnapshotCache",
    "HuggingFaceSnapshotCacheMiss",
    "HuggingFaceSnapshotError",
    "HuggingFaceSnapshotFetchError",
    "HuggingFaceSnapshotFetcher",
    "HuggingFaceSnapshotIntegrityError",
    "HuggingFaceSnapshotValidationError",
    "HuggingFaceStaleCacheAliasError",
]
