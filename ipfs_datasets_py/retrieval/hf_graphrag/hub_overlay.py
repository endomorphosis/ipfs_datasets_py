"""Overlay-upload a repaired GraphRAG tree onto an existing Hub dataset.

Research snapshots only. Never sets ``authorizing_for_publication`` or
``current_bundle``. IPv4 is forced because CloudFront IPv6 hangs with
CLOSE-WAIT sockets and zero Send-Q.

Callers that overlay onto ``justicedao/ipfs_state_laws`` must pass
:data:`STATE_LAWS_KEEP_PREFIXES` so ``STATE-*.parquet`` / source dumps
are not pruned.
"""

from __future__ import annotations

import json
import os
import socket
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from huggingface_hub import CommitOperationDelete, HfApi
from huggingface_hub.errors import HfHubHTTPError

_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _ipv4_getaddrinfo

DELETE_BATCH = max(1, int(os.environ.get("GRAPHRAG_HF_DELETE_BATCH", "4000")))
UPLOAD_WORKERS = max(1, int(os.environ.get("GRAPHRAG_HF_UPLOAD_WORKERS", "4")))

OVERLAY_NAMESPACES = ("data/", "indexes/", "scripts/", "skill/")
IGNORE_PATTERNS = [
    "**/postings_exploded/**",
    "**/.cache/**",
    "**/__pycache__/**",
    "**/.hf-graphrag-stage-*/**",
    "**/.upgrade_cidv1/**",
    "**/*.pyc",
    "**/.gitignore",
]
STATE_LAWS_KEEP_PREFIXES = (
    "STATE-",
    "OR/",
    "source",
    "recovery",
    "receipts",
    "acquisition",
    "current-live",
    "live-v",
    ".gitattributes",
    "state_laws_",
    "state_summaries/",
    "reports/",
    "configs/",
    "jurisdiction=",
)


def _log(message: str) -> None:
    print(message, flush=True)


def _token() -> str:
    env = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    if env:
        return env.strip()
    path = Path.home() / ".cache" / "huggingface" / "token"
    return path.read_text(encoding="utf-8").strip()


def _local_relatives(root: Path) -> set[str]:
    skip_dirs = {
        "postings_exploded",
        ".cache",
        "__pycache__",
        ".upgrade_cidv1",
    }
    relatives: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if any(part in skip_dirs or part.startswith(".") for part in parts[:-1]):
            continue
        if path.name.startswith(".") or path.name.endswith(".pyc"):
            continue
        relatives.add(path.relative_to(root).as_posix())
    return relatives


def _keep_remote(path: str, keep_prefixes: Sequence[str]) -> bool:
    if path in {".gitattributes"}:
        return True
    # Hive partitions and sidecar identity files are never superseded by
    # the flat GraphRAG overlay rewrite.
    name = path.rsplit("/", 1)[-1]
    if "jurisdiction=" in path or name in {"ids.parquet", "centroids.parquet"}:
        return True
    return any(path.startswith(prefix) or prefix in path for prefix in keep_prefixes)


def _overlay_extra(path: str) -> bool:
    return path.startswith(OVERLAY_NAMESPACES) or path in {
        "manifest.json",
        "dataset_configs.json",
        "release_metadata.json",
    }


def _http_status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def _delete_batch(
    api: HfApi, repo_id: str, paths: list[str], *, label: str
) -> None:
    ops = [CommitOperationDelete(path_in_repo=path) for path in paths]
    tries = 0
    while True:
        try:
            _log(f"delete {label} files={len(ops)}")
            api.create_commit(
                repo_id=repo_id,
                repo_type="dataset",
                revision="main",
                operations=ops,
                commit_message=(
                    f"prune superseded GraphRAG overlay paths "
                    f"({label}, {len(ops)} files)"
                ),
            )
            return
        except HfHubHTTPError as exc:
            status = _http_status(exc)
            if status == 429:
                wait_s = 120
                _log(f"429 on delete {label}; sleeping {wait_s}s")
                time.sleep(wait_s)
                continue
            if status in {500, 502, 503, 504} and tries < 6:
                tries += 1
                wait_s = min(60 * tries, 300)
                _log(f"{status} on delete {label} try {tries}; sleeping {wait_s}s")
                time.sleep(wait_s)
                continue
            raise


def overlay_upload_graphrag_release(
    folder: str | Path,
    repo_id: str,
    *,
    keep_prefixes: Sequence[str] = (".gitattributes",),
    prune_overlay_extras: bool = True,
    commit_message: str | None = None,
) -> dict[str, Any]:
    """Upload a local GraphRAG tree and optionally prune stale overlay files.

    Does not authorize publication. Refuses if the local manifest sets
    ``authorizing_for_publication`` or ``current_bundle``.
    """

    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    manifest_path = root / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("authorizing_for_publication") is True:
            raise SystemExit(
                "FAILED: refusing Hub upload of authorizing_for_publication=true"
            )
        if manifest.get("current_bundle") is True:
            raise SystemExit("FAILED: refusing Hub upload of current_bundle=true")
    local = _local_relatives(root)
    _log(f"local overlay files={len(local)} workers={UPLOAD_WORKERS} repo={repo_id}")
    api = HfApi(token=_token())
    api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True, private=False)
    api.upload_large_folder(
        repo_id=repo_id,
        folder_path=str(root),
        repo_type="dataset",
        revision="main",
        num_workers=UPLOAD_WORKERS,
        print_report=True,
        print_report_every=60,
        ignore_patterns=IGNORE_PATTERNS,
    )
    remote = set(api.list_repo_files(repo_id, repo_type="dataset", revision="main"))
    extras: list[str] = []
    if prune_overlay_extras:
        extras = sorted(
            path
            for path in remote
            if path not in local
            and not _keep_remote(path, keep_prefixes)
            and _overlay_extra(path)
        )
        _log(f"remote files={len(remote)} overlay extras to prune={len(extras)}")
        for offset in range(0, len(extras), DELETE_BATCH):
            chunk = extras[offset : offset + DELETE_BATCH]
            batch_no = offset // DELETE_BATCH + 1
            total = (len(extras) + DELETE_BATCH - 1) // DELETE_BATCH
            _delete_batch(api, repo_id, chunk, label=f"{batch_no}/{total}")
    info = api.dataset_info(repo_id, revision="main")
    sha = getattr(info, "sha", None) or getattr(info, "id", None)
    _log(f"DONE overlay sha={sha} remote_files={len(remote)} url=https://huggingface.co/datasets/{repo_id}/tree/main")
    return {
        "repo_id": repo_id,
        "sha": sha,
        "local_files": len(local),
        "remote_files": len(remote),
        "pruned": len(extras),
    }
