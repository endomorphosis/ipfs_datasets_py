"""United States Code Sparse GraphRAG corpus adapter (USCIR-029).

Thin knowledge_graphs registration surface over the package facade in
``ipfs_datasets_py.processors.legal_data.uscode_sparse_graphrag``.

Importing this module is optional-dependency safe. Heavy query/build
operations go through the lazy facade / ``UscodeQueryClient``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Mapping, Optional, Sequence

from ipfs_datasets_py.processors.legal_data.uscode_sparse_graphrag import (
    CORPUS_ID,
    DEFAULT_BASELINE_REVISION,
    DEFAULT_CONFIG_V2,
    DEFAULT_DATASET_REPO_ID,
    PRIMARY_KEY_V2,
    RELEASE_PROFILE,
    TASK_ID,
    AdapterRootSet,
    UscodeSparseGraphragAPI,
    UscodeSparseGraphragError,
    open_api,
    reconcile_adapter_roots,
    reconcile_registry_path_cid,
    warn_legacy_default_config,
)

ADAPTER_SCHEMA: Final = "uscode-corpus-adapter/v1"
DEFAULT_REPO_ID: Final = DEFAULT_DATASET_REPO_ID


class UscodeAdapterError(UscodeSparseGraphragError):
    """Raised for adapter-level configuration or reconciliation failures."""

    code = "uscode_adapter_error"


@dataclass
class UscodeCorpusAdapter:
    """Public adapter for the US Code sparse GraphRAG release family.

    Parameters
    ----------
    release_root:
        Optional offline release directory (manifest + data/).
    dataset_repo_id:
        Hub repository id (default ``justicedao/ipfs_uscode``).
    revision:
        Immutable revision pin.
    compatibility_config_name:
        Explicit config selector; defaults to v2 (legacy requires opt-in).
    """

    release_root: Path | str | None = None
    dataset_repo_id: str = DEFAULT_REPO_ID
    revision: str = DEFAULT_BASELINE_REVISION
    compatibility_config_name: str = DEFAULT_CONFIG_V2

    def __post_init__(self) -> None:
        if self.release_root is not None:
            root = Path(self.release_root).expanduser().resolve()
            if not root.is_dir():
                raise UscodeAdapterError(
                    f"release_root is not a directory: {root}"
                )
            self.release_root = root
        self._api = open_api(
            dataset_repo_id=self.dataset_repo_id,
            revision=self.revision,
            compatibility_config_name=self.compatibility_config_name,
        )

    @property
    def api(self) -> UscodeSparseGraphragAPI:
        return self._api

    @property
    def corpus_id(self) -> str:
        return CORPUS_ID

    def identity(self) -> dict[str, Any]:
        payload = self._api.package_identity()
        payload.update(
            {
                "adapter_schema": ADAPTER_SCHEMA,
                "release_root": (
                    str(self.release_root) if self.release_root else None
                ),
                "task_id": TASK_ID,
            }
        )
        return payload

    def registry_resolution(self) -> dict[str, Any]:
        receipt = reconcile_registry_path_cid()
        return receipt.to_dict() if hasattr(receipt, "to_dict") else dict(receipt)

    def release_gate_capability(self) -> dict[str, Any]:
        return self._api.release_gate_capability()

    def reconcile_roots(
        self, roots: AdapterRootSet | Mapping[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        # Normalize to a mapping so module-reload isinstance mismatches
        # (pytest reimport of the facade) cannot fail closed incorrectly.
        if hasattr(roots, "to_dict") and not isinstance(roots, Mapping):
            roots = roots.to_dict()  # type: ignore[assignment]
        return reconcile_adapter_roots(roots, **kwargs)

    def open_query_client(self, resolver: Any = None, **kwargs: Any) -> Any:
        """Open the legal hybrid/graph query client (lazy heavy import)."""

        if resolver is None and self.release_root is not None:
            from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
                ImmutableHubResolver,
                LocalRootTransport,
            )

            resolver = ImmutableHubResolver(
                repo_id=self.dataset_repo_id,
                revision=self.revision,
                transport=LocalRootTransport(self.release_root),
                local_root=self.release_root,
                supported_schemas={
                    "hf-graphrag-release/v1",
                    "publicus-ir-graphrag/v2",
                },
            )
        return self._api.open_query_client(resolver, **kwargs)

    def use_legacy_compatibility(self) -> "UscodeCorpusAdapter":
        warn_legacy_default_config()
        return UscodeCorpusAdapter(
            release_root=self.release_root,
            dataset_repo_id=self.dataset_repo_id,
            revision=self.revision,
            compatibility_config_name="legacy-uscode-parquet/v1",
        )

    def validate(self) -> dict[str, Any]:
        """Lightweight adapter validation (no network, no parquet required)."""

        registry = self.registry_resolution()
        identity = self.identity()
        capability = self.release_gate_capability()
        return {
            "adapter_schema": ADAPTER_SCHEMA,
            "capability": capability,
            "identity": identity,
            "primary_key": PRIMARY_KEY_V2,
            "profile": RELEASE_PROFILE,
            "registry": registry,
            "registry_reconciled": bool(registry.get("reconciled")),
            "schema": "uscode-corpus-validation-receipt/v1",
            "task_id": TASK_ID,
        }


def register_uscode_adapter() -> dict[str, Any]:
    """Return a registration descriptor for knowledge_graphs consumers.

    Does not mutate global registries at import time. Callers may feed this
    into release-gate builders when promoting US Code to a required corpus.
    """

    api = open_api()
    return {
        "adapter_module": __name__,
        "adapter_class": "UscodeCorpusAdapter",
        "capability": api.release_gate_capability(),
        "corpus_id": CORPUS_ID,
        "dataset_repo_id": DEFAULT_REPO_ID,
        "primary_key": PRIMARY_KEY_V2,
        "profile": RELEASE_PROFILE,
        "schema": "uscode-adapter-registration/v1",
        "task_id": TASK_ID,
    }


__all__ = [
    "ADAPTER_SCHEMA",
    "CORPUS_ID",
    "DEFAULT_REPO_ID",
    "UscodeAdapterError",
    "UscodeCorpusAdapter",
    "register_uscode_adapter",
]
