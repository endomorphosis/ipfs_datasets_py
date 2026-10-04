"""ZKP setup artifact helpers.

This module provides small, dependency-light helpers for working with setup
artifacts (e.g., Groth16 proving/verifying keys) produced by the Rust backend.

It intentionally does *not* run setup itself; use the Rust CLI via
`logic.zkp.backends.groth16_ffi.Groth16Backend.setup()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ipfs_datasets_py import ipfs_backend_router


@dataclass(frozen=True)
class Groth16SetupArtifacts:
    proving_key_cid: str
    verifying_key_cid: str


def store_groth16_setup_artifacts_in_ipfs(
    manifest: dict[str, Any],
    *,
    pin: bool = True,
    backend: Optional[str] = None,
    backend_instance: Optional[ipfs_backend_router.IPFSBackend] = None,
) -> dict[str, Any]:
    """Store Groth16 setup artifacts referenced by a manifest into IPFS.

    Expects a manifest dict produced by the Rust `groth16 setup` command.

    Returns a *new* manifest dict including:
      - `proving_key_cid`
      - `verifying_key_cid`

    This function is safe to unit-test by injecting a fake `backend_instance`.
    """

    if not isinstance(manifest, dict):
        raise TypeError("manifest must be a dict")

    pk_path = manifest.get("proving_key_path")
    vk_path = manifest.get("verifying_key_path")

    if not isinstance(pk_path, str) or not pk_path:
        raise ValueError("manifest must contain non-empty proving_key_path")
    if not isinstance(vk_path, str) or not vk_path:
        raise ValueError("manifest must contain non-empty verifying_key_path")

    pk_fs_path = Path(pk_path)
    vk_fs_path = Path(vk_path)
    if not pk_fs_path.exists():
        raise FileNotFoundError(f"proving_key_path does not exist: {pk_fs_path}")
    if not vk_fs_path.exists():
        raise FileNotFoundError(f"verifying_key_path does not exist: {vk_fs_path}")

    proving_key_cid = ipfs_backend_router.add_path(
        str(pk_fs_path),
        recursive=False,
        pin=pin,
        backend=backend,
        backend_instance=backend_instance,
    )
    verifying_key_cid = ipfs_backend_router.add_path(
        str(vk_fs_path),
        recursive=False,
        pin=pin,
        backend=backend,
        backend_instance=backend_instance,
    )

    out = dict(manifest)
    out["proving_key_cid"] = proving_key_cid
    out["verifying_key_cid"] = verifying_key_cid
    return out
