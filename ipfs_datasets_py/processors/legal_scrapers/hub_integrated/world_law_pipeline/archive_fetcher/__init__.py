"""world_law shared archive fetcher (Common Crawl + Wayback). See README.md."""
from .core import (ArchiveFetcher, ArchivedDoc, Capture, ArchiveError, ArchiveTransient, ArchiveDeferred, ArchiveTimeout, ArchiveBreakerOpen, ArchiveBusy, CaptureList, FetchInfo, merge_deferrals, canonical_url, good_doc,  # noqa: F401
                   is_stale, DEFAULT_CACHE, UA)
from .staging import provenance_fields, StagedWriter  # noqa: F401
from . import ratelimit  # noqa: F401
from . import deferral  # noqa: F401
