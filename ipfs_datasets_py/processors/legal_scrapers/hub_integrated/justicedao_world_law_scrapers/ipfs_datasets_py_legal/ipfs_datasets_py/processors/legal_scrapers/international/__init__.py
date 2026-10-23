"""Harvested official-gazette collectors and unified legal scrape API."""

from .api import (
    LegalSource,
    get_jurisdiction_wrapper,
    harvest_legal_collectors,
    list_legal_sources,
    load_published_snapshot,
    resolve_legal_source,
    scrape_legal_data,
)
from .catalog import (
    SnapshotCorpus,
    get_snapshot_corpus,
    infer_snapshot_corpus_for_dataset_id,
    list_snapshot_corpora,
    snapshot_catalog_summary,
)
from .harvest import harvest_legal_scrapers_repo, rewrite_sandbox_source
from .helpers.paths import collectors_root, corpora_root
from .scrape_state import (
    load_published_scrape_state,
    load_skip_keys,
    sync_published_scrape_state,
)

__all__ = [
    "LegalSource",
    "SnapshotCorpus",
    "collectors_root",
    "corpora_root",
    "get_jurisdiction_wrapper",
    "get_snapshot_corpus",
    "harvest_legal_collectors",
    "harvest_legal_scrapers_repo",
    "infer_snapshot_corpus_for_dataset_id",
    "list_legal_sources",
    "list_snapshot_corpora",
    "load_published_snapshot",
    "resolve_legal_source",
    "rewrite_sandbox_source",
    "scrape_legal_data",
    "snapshot_catalog_summary",
    "sync_published_scrape_state",
    "load_published_scrape_state",
    "load_skip_keys",
]
