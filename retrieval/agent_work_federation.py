"""Re-export EAAEF-062 federation."""

from ipfs_datasets_py.retrieval.agent_work_federation import (  # type: ignore[import-not-found]
    ENGINES,
    FederationError,
    federate,
)

__all__ = ("ENGINES", "FederationError", "federate")
