"""Re-export EAAEF-061 corpora contracts."""

from ipfs_datasets_py.retrieval.agent_work_corpora import (  # type: ignore[import-not-found]
    CORPORA,
    CorpusError,
    CorpusRecord,
    separate,
)

__all__ = ("CORPORA", "CorpusError", "CorpusRecord", "separate")
