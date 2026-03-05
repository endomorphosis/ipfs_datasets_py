#!/usr/bin/env python3
"""Generate semantic embeddings for parquet rows in bulk.

This script is designed for large parquet ingestion runs where the same model
runtime should remain hot in one process. It uses embeddings_router with
local HF defaults and writes companion *_embeddings.parquet files.
"""

from __future__ import annotations

import argparse
from collections import deque
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import anyio
import pandas as pd

from ipfs_datasets_py import embeddings_router


DEFAULT_MODEL = "thenlper/gte-small"
DEFAULT_PROVIDER = "local_adapter"
DEFAULT_BATCH_SIZE = 64
DEFAULT_FLUSH_SIZE = 512

PREFERRED_FIELDS = [
    "text",
    "content",
    "body",
    "section_text",
    "law_text",
    "statute_text",
    "description",
    "title",
    "summary",
    "heading",
    "clause",
    "paragraph",
]

SKIP_EXACT = {
    "cid",
    "id",
    "uuid",
    "hash",
    "checksum",
    "source",
    "source_url",
    "url",
    "link",
    "metadata",
    "json",
    "raw_json",
    "created_at",
    "updated_at",
    "filename",
    "file_path",
}

SKIP_MARKERS = ("cid", "hash", "uuid", "url", "source", "metadata", "json", "_id")


def _ensure_ipfs_accelerate_path() -> None:
    """Best-effort sys.path fixup for importing ipfs_accelerate_py.p2p_tasks."""
    import importlib

    try:
        import ipfs_accelerate_py.p2p_tasks  # type: ignore  # noqa: F401
        return
    except Exception:
        pass

    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / "ipfs_accelerate_py" / "p2p_tasks"
        if candidate.exists() and candidate.is_dir():
            parent_text = str(parent)
            if parent_text not in sys.path:
                sys.path.insert(0, parent_text)
            importlib.invalidate_caches()
            try:
                import ipfs_accelerate_py.p2p_tasks  # type: ignore  # noqa: F401
                return
            except Exception:
                # If an empty namespace package was already cached from another
                # path, clear it and retry once.
                sys.modules.pop("ipfs_accelerate_py", None)
                importlib.invalidate_caches()
                try:
                    import ipfs_accelerate_py.p2p_tasks  # type: ignore  # noqa: F401
                    return
                except Exception:
                    continue


def _resolve_input_dir(input_dir: str) -> Path:
    """Resolve local paths and fish:// URI-style paths to a local directory."""
    value = str(input_dir).strip()
    if value.startswith("fish://"):
        # Expected pattern: fish://user@host/absolute/path
        slash = value.find("/", len("fish://"))
        if slash != -1:
            value = value[slash:]
    return Path(value).expanduser().resolve()


def _iter_parquet_files(base: Path, pattern: str, recursive: bool) -> Iterable[Path]:
    globber = base.rglob if recursive else base.glob
    for path in sorted(globber(pattern)):
        if path.name.endswith("_embeddings.parquet"):
            continue
        if path.is_file():
            yield path


def _build_semantic_text(row: pd.Series, min_text_chars: int, min_words: int) -> str:
    def _is_missing_value(value: Any) -> bool:
        """Return True for scalar/array-like NA values without ambiguous truth errors."""
        try:
            missing = pd.isna(value)
        except Exception:
            return False
        if isinstance(missing, bool):
            return missing
        try:
            return bool(missing.all())
        except Exception:
            return False

    parts: list[str] = []
    used = set()

    for key in PREFERRED_FIELDS:
        if key in row and not _is_missing_value(row[key]):
            value = str(row[key]).strip()
            if value and len(value) >= min_text_chars:
                parts.append(value)
                used.add(key)

    for key, raw_value in row.items():
        key_l = str(key).strip().lower()
        if key in used or key_l in SKIP_EXACT:
            continue
        if any(marker in key_l for marker in SKIP_MARKERS):
            continue
        if _is_missing_value(raw_value):
            continue

        value = str(raw_value).strip()
        if not value or len(value) < min_text_chars:
            continue
        if value.startswith("{") or value.startswith("["):
            continue
        if value.startswith("http://") or value.startswith("https://"):
            continue

        parts.append(value)

    if not parts:
        return ""

    text = "\n\n".join(parts)
    return text if len(text.split()) >= min_words else ""


def _extract_embedding_from_task(task: dict[str, Any]) -> list[float]:
    result = task.get("result")
    if isinstance(result, dict):
        emb = result.get("embedding")
        if isinstance(emb, list):
            return [float(x) for x in emb]
        nested = result.get("result")
        if isinstance(nested, dict):
            emb2 = nested.get("embedding")
            if isinstance(emb2, list):
                return [float(x) for x in emb2]
    return []


def _extract_embedding_runtime_info(task: dict[str, Any]) -> dict[str, str]:
    """Best-effort extraction of embedding execution path metadata."""
    result = task.get("result")
    if not isinstance(result, dict):
        return {}

    # Prefer explicit worker metadata fields.
    backend = result.get("embedding_backend")
    model = result.get("embedding_model")
    device = result.get("embedding_device")
    accel_err = result.get("embedding_accelerate_error")

    # Some handlers may nest the actual result payload.
    nested = result.get("result")
    if isinstance(nested, dict):
        backend = backend or nested.get("embedding_backend")
        model = model or nested.get("embedding_model")
        device = device or nested.get("embedding_device")
        accel_err = accel_err or nested.get("embedding_accelerate_error")

    out: dict[str, str] = {}
    if backend is not None:
        out["backend"] = str(backend)
    if model is not None:
        out["model"] = str(model)
    if device is not None:
        out["device"] = str(device)
    if accel_err is not None:
        out["accelerate_error"] = str(accel_err)
    return out


def _collect_texts(
    df: pd.DataFrame,
    *,
    min_text_chars: int,
    min_words: int,
    max_rows: int,
) -> tuple[list[int], list[str]]:
    row_ids: list[int] = []
    texts: list[str] = []
    for row_index, row in df.iterrows():
        if max_rows > 0 and len(texts) >= max_rows:
            break
        text = _build_semantic_text(row, min_text_chars=min_text_chars, min_words=min_words)
        if not text:
            continue
        row_ids.append(int(row_index))
        texts.append(text)
    return row_ids, texts


def _embed_file(
    parquet_path: Path,
    *,
    output_path: Path,
    model: str,
    provider: str,
    device: str,
    batch_size: int,
    flush_size: int,
    min_text_chars: int,
    min_words: int,
    mode: str,
    task_type: str,
    taskqueue_backend: str,
    taskqueue_targets: list[str],
    taskqueue_discovery: str,
    taskqueue_discovery_timeout_s: float,
    taskqueue_discovery_limit: int,
    task_timeout_s: float,
    queue_session_id: str,
    queue_sticky_worker_id: str,
    queue_submit_log_every: int,
    queue_submit_retries: int,
    queue_submit_retry_base_ms: int,
    queue_wait_retries: int,
    queue_wait_retry_base_ms: int,
    queue_wait_slice_timeout_s: float,
    queue_wait_probe_interval_cycles: int,
    queue_wait_probe_near_deadline_s: float,
    queue_wait_probe_get_retries: int,
    queue_retry_dial_timeout_scale: float,
    queue_retry_dial_timeout_max_s: float,
    queue_retry_delay_max_ms: int,
    queue_max_concurrent_dials: int,
    queue_max_concurrent_wait_dials: int,
    queue_dial_slot_timeout_s: float,
    queue_wait_dial_slot_timeout_s: float,
    queue_cache_max_keys: int,
    queue_cache_stale_s: float,
    queue_remote_cooldown_base_ms: int,
    queue_remote_cooldown_max_ms: int,
    queue_remote_penalty_decay_every: int,
    queue_remote_penalty_decay_divisor: int,
    queue_remote_penalty_skip_threshold: int,
    queue_retry_lightweight_discovery: bool,
    queue_explicit_addr_cooldown_base_ms: int,
    queue_explicit_addr_cooldown_max_ms: int,
    queue_inflight_limit: int,
    queue_submit_drop_backoff_base_ms: int,
    queue_submit_drop_backoff_max_ms: int,
    queue_remote_probe_timeout_s: float,
    queue_remote_min_healthy: int,
    queue_remote_max_active: int,
    queue_bootstrap_max_attempts: int,
    queue_bootstrap_seed_max_connects: int,
    queue_verbose: bool,
    queue_submit_fail_hard: bool,
    max_rows: int,
) -> tuple[int, int]:
    df = pd.read_parquet(parquet_path)

    pending_row_ids, pending_texts = _collect_texts(
        df,
        min_text_chars=min_text_chars,
        min_words=min_words,
        max_rows=int(max_rows),
    )

    if not pending_texts:
        return len(df), 0

    queue_mode = str(mode).strip().lower() if mode else "inline"
    if queue_mode == "taskqueue":
        return _embed_file_via_taskqueue(
            parquet_path=parquet_path,
            output_path=output_path,
            source_rows=len(df),
            row_ids=pending_row_ids,
            texts=pending_texts,
            model=model,
            device=device,
            task_type=task_type,
            taskqueue_backend=taskqueue_backend,
            taskqueue_targets=taskqueue_targets,
            taskqueue_discovery=taskqueue_discovery,
            taskqueue_discovery_timeout_s=float(taskqueue_discovery_timeout_s),
            taskqueue_discovery_limit=int(taskqueue_discovery_limit),
            task_timeout_s=float(task_timeout_s),
            queue_session_id=queue_session_id,
            queue_sticky_worker_id=queue_sticky_worker_id,
            queue_submit_log_every=int(queue_submit_log_every),
            queue_submit_retries=int(queue_submit_retries),
            queue_submit_retry_base_ms=int(queue_submit_retry_base_ms),
            queue_wait_retries=int(queue_wait_retries),
            queue_wait_retry_base_ms=int(queue_wait_retry_base_ms),
            queue_wait_slice_timeout_s=float(queue_wait_slice_timeout_s),
            queue_wait_probe_interval_cycles=int(queue_wait_probe_interval_cycles),
            queue_wait_probe_near_deadline_s=float(queue_wait_probe_near_deadline_s),
            queue_wait_probe_get_retries=int(queue_wait_probe_get_retries),
            queue_retry_dial_timeout_scale=float(queue_retry_dial_timeout_scale),
            queue_retry_dial_timeout_max_s=float(queue_retry_dial_timeout_max_s),
            queue_retry_delay_max_ms=int(queue_retry_delay_max_ms),
            queue_max_concurrent_dials=int(queue_max_concurrent_dials),
            queue_max_concurrent_wait_dials=int(queue_max_concurrent_wait_dials),
            queue_dial_slot_timeout_s=float(queue_dial_slot_timeout_s),
            queue_wait_dial_slot_timeout_s=float(queue_wait_dial_slot_timeout_s),
            queue_cache_max_keys=int(queue_cache_max_keys),
            queue_cache_stale_s=float(queue_cache_stale_s),
            queue_remote_cooldown_base_ms=int(queue_remote_cooldown_base_ms),
            queue_remote_cooldown_max_ms=int(queue_remote_cooldown_max_ms),
            queue_remote_penalty_decay_every=int(queue_remote_penalty_decay_every),
            queue_remote_penalty_decay_divisor=int(queue_remote_penalty_decay_divisor),
            queue_remote_penalty_skip_threshold=int(queue_remote_penalty_skip_threshold),
            queue_retry_lightweight_discovery=bool(queue_retry_lightweight_discovery),
            queue_explicit_addr_cooldown_base_ms=int(queue_explicit_addr_cooldown_base_ms),
            queue_explicit_addr_cooldown_max_ms=int(queue_explicit_addr_cooldown_max_ms),
            queue_inflight_limit=int(queue_inflight_limit),
            queue_submit_drop_backoff_base_ms=int(queue_submit_drop_backoff_base_ms),
            queue_submit_drop_backoff_max_ms=int(queue_submit_drop_backoff_max_ms),
            queue_remote_probe_timeout_s=float(queue_remote_probe_timeout_s),
            queue_remote_min_healthy=int(queue_remote_min_healthy),
            queue_remote_max_active=int(queue_remote_max_active),
            queue_bootstrap_max_attempts=int(queue_bootstrap_max_attempts),
            queue_bootstrap_seed_max_connects=int(queue_bootstrap_seed_max_connects),
            queue_verbose=bool(queue_verbose),
            queue_submit_fail_hard=bool(queue_submit_fail_hard),
        )

    return _embed_file_inline(
        parquet_path=parquet_path,
        output_path=output_path,
        source_rows=len(df),
        row_ids=pending_row_ids,
        texts=pending_texts,
        model=model,
        provider=provider,
        device=device,
        batch_size=batch_size,
        flush_size=flush_size,
    )


def _embed_file_inline(
    *,
    parquet_path: Path,
    output_path: Path,
    source_rows: int,
    row_ids: list[int],
    texts: list[str],
    model: str,
    provider: str,
    device: str,
    batch_size: int,
    flush_size: int,
) -> tuple[int, int]:
    all_vectors: list[list[float]] = []
    all_row_ids: list[int] = []
    pending_texts: list[str] = []
    pending_row_ids: list[int] = []

    def flush_inline() -> None:
        if not pending_texts:
            return
        vectors = embeddings_router.embed_texts_batched(
            pending_texts,
            batch_size=batch_size,
            model_name=model,
            provider=provider,
            device=device,
        )
        all_vectors.extend(vectors)
        all_row_ids.extend(pending_row_ids)
        pending_texts.clear()
        pending_row_ids.clear()

    for row_index, text in zip(row_ids, texts):
        pending_texts.append(text)
        pending_row_ids.append(int(row_index))
        if len(pending_texts) >= flush_size:
            flush_inline()

    flush_inline()

    if not all_vectors:
        return source_rows, 0

    out_df = pd.DataFrame(
        {
            "source_file": [parquet_path.name] * len(all_row_ids),
            "source_row_index": all_row_ids,
            "embedding": all_vectors,
        }
    )
    out_df.to_parquet(output_path, index=False)
    return source_rows, len(out_df)


def _discover_taskqueue_targets(
    *,
    discovery_mode: str,
    timeout_s: float,
    limit: int,
) -> list[Any]:
    _ensure_ipfs_accelerate_path()
    from ipfs_accelerate_py.p2p_tasks.client import (  # type: ignore
        RemoteQueue,
        discover_peers_via_dht_sync,
        discover_peers_via_mdns_sync,
        discover_peers_via_rendezvous_sync,
    )

    def _configured_bootstrap_multiaddrs() -> list[str]:
        raw = os.environ.get("IPFS_ACCELERATE_PY_TASK_P2P_BOOTSTRAP_PEERS")
        if raw is None:
            raw = os.environ.get("IPFS_DATASETS_PY_TASK_P2P_BOOTSTRAP_PEERS", "")
        parts = [segment.strip() for segment in str(raw).split(",") if str(segment).strip()]
        return parts

    def _bootstrap_targets_from_env() -> list[Any]:
        targets: list[Any] = []
        for addr in _configured_bootstrap_multiaddrs():
            marker = "/p2p/"
            if marker not in addr:
                continue
            peer_id = addr.rsplit(marker, 1)[-1].strip()
            if not peer_id:
                continue
            targets.append(RemoteQueue(peer_id=peer_id, multiaddr=addr))
        return targets

    mode = str(discovery_mode).strip().lower()
    out: list[Any] = []

    if mode in {"none", ""}:
        return out
    # "auto" prioritizes the common mesh channels: mdns + dht + configured
    # bootstrap peers.
    if mode in {"mdns", "auto", "all"}:
        out.extend(discover_peers_via_mdns_sync(timeout_s=timeout_s, limit=limit, exclude_self=True))
    if mode in {"dht", "auto", "all"}:
        out.extend(discover_peers_via_dht_sync(timeout_s=timeout_s, limit=limit, exclude_self=True, namespace=""))
    if mode in {"rendezvous", "all"}:
        out.extend(discover_peers_via_rendezvous_sync(timeout_s=timeout_s, limit=limit, exclude_self=True, namespace=""))
    if mode in {"bootstrap", "auto", "all"}:
        out.extend(_bootstrap_targets_from_env())

    # Deduplicate by peer_id and keep the first dialable address observed for
    # that peer to avoid retry storms against duplicate stale addresses.
    deduped: list[Any] = []
    seen_peers: set[str] = set()
    for remote in out:
        peer = str(getattr(remote, "peer_id", "") or "").strip()
        addr = str(getattr(remote, "multiaddr", "") or "").strip()
        if not peer or not addr or peer in seen_peers:
            continue
        seen_peers.add(peer)
        deduped.append(remote)
    return deduped


def _probe_taskqueue_remotes(
    *,
    remotes: list[Any],
    timeout_s: float,
    verbose: bool,
    status_retries: int = 0,
) -> tuple[list[Any], list[tuple[int, Any, bool]]]:
    """Probe remotes and return healthy-first ordering with probe metadata."""
    _ensure_ipfs_accelerate_path()
    from ipfs_accelerate_py.p2p_tasks.client import request_status_sync  # type: ignore

    if not remotes:
        return [], []

    results: list[tuple[int, Any, bool]] = []
    primary_retry_env = "IPFS_ACCELERATE_PY_TASK_P2P_STATUS_RETRIES"
    compat_retry_env = "IPFS_DATASETS_PY_TASK_P2P_STATUS_RETRIES"
    prev_primary = os.environ.get(primary_retry_env)
    prev_compat = os.environ.get(compat_retry_env)
    try:
        os.environ[primary_retry_env] = str(max(0, int(status_retries)))
        os.environ[compat_retry_env] = str(max(0, int(status_retries)))
        for idx, remote in enumerate(remotes):
            ok = False
            try:
                status = request_status_sync(remote=remote, timeout_s=max(0.1, float(timeout_s)), detail=False)
                ok = bool(isinstance(status, dict) and status.get("ok"))
            except Exception:
                ok = False
            results.append((int(idx), remote, bool(ok)))
    finally:
        if prev_primary is None:
            os.environ.pop(primary_retry_env, None)
        else:
            os.environ[primary_retry_env] = prev_primary
        if prev_compat is None:
            os.environ.pop(compat_retry_env, None)
        else:
            os.environ[compat_retry_env] = prev_compat

    healthy = [entry[1] for entry in results if bool(entry[2])]
    unhealthy = [entry[1] for entry in results if not bool(entry[2])]
    ordered = healthy + unhealthy

    if bool(verbose):
        print(
            "[queue:probe] "
            f"healthy={len(healthy)}/{len(remotes)} timeout_s={max(0.1, float(timeout_s)):.2f}"
        )

    return ordered, results


def _parse_target_specs(target_specs: list[str]) -> list[Any]:
    _ensure_ipfs_accelerate_path()
    from ipfs_accelerate_py.p2p_tasks.client import RemoteQueue  # type: ignore

    out: list[Any] = []
    for raw in target_specs:
        text = str(raw or "").strip()
        if not text:
            continue
        if "::" not in text:
            raise ValueError(f"Invalid --taskqueue-target value: {text}. Expected 'peer_id::multiaddr'.")
        peer_id, multiaddr = text.split("::", 1)
        peer_id = str(peer_id).strip()
        multiaddr = str(multiaddr).strip()
        if not peer_id or not multiaddr:
            raise ValueError(f"Invalid --taskqueue-target value: {text}. Expected 'peer_id::multiaddr'.")
        out.append(RemoteQueue(peer_id=peer_id, multiaddr=multiaddr))
    return out


async def _wait_remote_task_async(*, remote: Any, task_id: str, timeout_s: float) -> dict[str, Any] | None:
    _ensure_ipfs_accelerate_path()
    from ipfs_accelerate_py.p2p_tasks.client import wait_task  # type: ignore

    return await wait_task(remote=remote, task_id=str(task_id), timeout_s=float(timeout_s))


def _wait_remote_task_sync(*, remote: Any, task_id: str, timeout_s: float) -> dict[str, Any] | None:
    async def _run_wait() -> dict[str, Any] | None:
        return await _wait_remote_task_async(
            remote=remote,
            task_id=str(task_id),
            timeout_s=float(timeout_s),
        )

    return anyio.run(_run_wait, backend="trio")


def _submit_remote_with_retries(
    *,
    remotes: list[Any],
    preferred_remote_index: int,
    task_type: str,
    model: str,
    payload: dict[str, Any],
    submit_retries: int,
    submit_retry_base_ms: int,
    retry_delay_max_ms: int = 5000,
    remote_cooldown_base_ms: int = 25,
    remote_cooldown_max_ms: int = 1000,
    remote_penalties: list[int] | None = None,
    remote_failure_streaks: list[int] | None = None,
    remote_unavailable_until: list[float] | None = None,
    remote_penalty_skip_threshold: int = -1,
    verbose: bool = False,
) -> tuple[str, Any, int]:
    _ensure_ipfs_accelerate_path()
    from ipfs_accelerate_py.p2p_tasks.client import submit_task_sync  # type: ignore

    if not remotes:
        raise RuntimeError("No remote peers available for submit")

    retries = max(0, int(submit_retries))
    base_ms = max(10, int(submit_retry_base_ms))
    delay_cap_ms = max(base_ms, int(retry_delay_max_ms))
    cooldown_base_ms = max(10, int(remote_cooldown_base_ms))
    cooldown_max_ms = max(cooldown_base_ms, int(remote_cooldown_max_ms))
    n_remotes = len(remotes)
    # In multi-remote mode, cover one full sweep plus explicit retry budget so
    # intermittent failures on several peers still get additional recovery tries.
    total_attempts = retries + 1
    if n_remotes > 1:
        total_attempts = max(total_attempts, n_remotes + retries)
    last_exc: Exception | None = None
    last_remote_desc = ""

    def _candidate_indices(*, allow_penalty_skip: bool) -> list[int]:
        now = time.monotonic()
        ordered_indices = [((int(preferred_remote_index) + i) % n_remotes) for i in range(n_remotes)]
        if isinstance(remote_penalties, list) and len(remote_penalties) == n_remotes:
            # Re-evaluate penalties each attempt so a remote that just failed is
            # deprioritized immediately for the next retry.
            ordered_indices = sorted(
                ordered_indices,
                key=lambda i: (int(remote_penalties[i]), (i - int(preferred_remote_index)) % n_remotes),
            )

            threshold = int(remote_penalty_skip_threshold)
            if allow_penalty_skip and threshold >= 0:
                healthy = [i for i in ordered_indices if int(remote_penalties[i]) <= threshold]
                # If all remotes are currently penalized, keep fallback behavior
                # by trying all remotes instead of failing selection.
                if healthy:
                    ordered_indices = healthy

        # Prefer remotes that are not in a short local cooldown window. If all
        # remotes are cooling down, keep fallback behavior by allowing all.
        if isinstance(remote_unavailable_until, list) and len(remote_unavailable_until) == n_remotes:
            available = [i for i in ordered_indices if float(remote_unavailable_until[i]) <= now]
            if available:
                ordered_indices = available
        return ordered_indices

    tried_remote_indices: set[int] = set()

    for attempt in range(total_attempts):
        # Apply strict skip-threshold only on first attempt; broaden retries to
        # all remotes to maximize recovery under partial remote degradation.
        ordered_indices = _candidate_indices(allow_penalty_skip=(attempt == 0))
        selectable = [i for i in ordered_indices if i not in tried_remote_indices]
        if not selectable:
            tried_remote_indices.clear()
            selectable = ordered_indices
        remote_idx = int(selectable[0])
        tried_remote_indices.add(remote_idx)
        remote = remotes[remote_idx]
        if verbose:
            penalty = int(remote_penalties[remote_idx]) if isinstance(remote_penalties, list) and len(remote_penalties) == n_remotes else -1
            streak = int(remote_failure_streaks[remote_idx]) if isinstance(remote_failure_streaks, list) and len(remote_failure_streaks) == n_remotes else -1
            unavailable_for_s = 0.0
            if isinstance(remote_unavailable_until, list) and len(remote_unavailable_until) == n_remotes:
                unavailable_for_s = max(0.0, float(remote_unavailable_until[remote_idx]) - time.monotonic())
            print(
                "[queue:submit] "
                f"attempt={attempt + 1}/{total_attempts} "
                f"remote_index={remote_idx} "
                f"penalty={penalty} streak={streak} "
                f"cooldown_remaining_s={unavailable_for_s:.3f}"
            )
        try:
            task_id = submit_task_sync(
                remote=remote,
                task_type=str(task_type),
                model_name=str(model),
                payload=payload,
            )
            if isinstance(remote_penalties, list) and len(remote_penalties) == n_remotes:
                remote_penalties[remote_idx] = max(0, int(remote_penalties[remote_idx]) - 1)
            if isinstance(remote_failure_streaks, list) and len(remote_failure_streaks) == n_remotes:
                remote_failure_streaks[remote_idx] = 0
            if isinstance(remote_unavailable_until, list) and len(remote_unavailable_until) == n_remotes:
                remote_unavailable_until[remote_idx] = 0.0
            if verbose:
                print(
                    "[queue:submit] "
                    f"ok task_id={str(task_id)} remote_index={remote_idx}"
                )
            return str(task_id), remote, int(remote_idx)
        except Exception as exc:
            if verbose:
                print(
                    "[queue:submit] "
                    f"error remote_index={remote_idx} "
                    f"error={type(exc).__name__}: {exc}"
                )
            last_exc = exc
            last_remote_desc = (
                f"peer_id={getattr(remote, 'peer_id', '')} "
                f"multiaddr={getattr(remote, 'multiaddr', '')} "
                f"remote_index={remote_idx}"
            )
            if isinstance(remote_penalties, list) and len(remote_penalties) == n_remotes:
                penalty_bump = 1
                if isinstance(remote_failure_streaks, list) and len(remote_failure_streaks) == n_remotes:
                    current_streak = int(remote_failure_streaks[remote_idx])
                    penalty_bump = min(4, 1 + (current_streak // 2))
                remote_penalties[remote_idx] = min(1_000_000, int(remote_penalties[remote_idx]) + penalty_bump)
            if isinstance(remote_failure_streaks, list) and len(remote_failure_streaks) == n_remotes:
                remote_failure_streaks[remote_idx] = min(1_000_000, int(remote_failure_streaks[remote_idx]) + 1)
                streak = int(remote_failure_streaks[remote_idx])
                cooldown_ms = min(cooldown_max_ms, cooldown_base_ms * (2 ** min(streak, 8)))
                if isinstance(remote_unavailable_until, list) and len(remote_unavailable_until) == n_remotes:
                    remote_unavailable_until[remote_idx] = time.monotonic() + (float(cooldown_ms) / 1000.0)
            if attempt >= (total_attempts - 1):
                break
            # While there are still untried remotes in the current sweep,
            # fail over immediately instead of sleeping between attempts.
            if n_remotes > 1 and len(tried_remote_indices) < n_remotes:
                continue
            # Backoff growth is capped by configured retry depth so expanded
            # remote sweeps do not introduce runaway sleep times.
            backoff_stage = max(0, min(int(attempt), int(retries)))
            stage_delay_ms = min(delay_cap_ms, base_ms * (2**backoff_stage))
            jitter_cap_ms = max(1.0, min(float(base_ms), float(stage_delay_ms)))
            delay_s = (stage_delay_ms / 1000.0) + (random.uniform(0.0, jitter_cap_ms) / 1000.0)
            time.sleep(delay_s)

    detail = f"remote submit failed after {total_attempts} attempts"
    if last_remote_desc:
        detail = f"{detail} ({last_remote_desc})"
    if last_exc is not None:
        raise RuntimeError(f"{detail}: {last_exc}") from last_exc
    raise RuntimeError(detail)


def _wait_remote_with_retries(
    *,
    remote: Any,
    task_id: str,
    timeout_s: float,
    wait_retries: int,
    wait_retry_base_ms: int,
    retry_delay_max_ms: int = 5000,
) -> dict[str, Any] | None:
    retries = max(0, int(wait_retries))
    base_ms = max(10, int(wait_retry_base_ms))
    delay_cap_ms = max(base_ms, int(retry_delay_max_ms))
    total_attempts = retries + 1

    # Split long waits into attempt windows so transient transport failures can
    # reconnect and resume waiting without giving up the task entirely.
    per_attempt_timeout_s = max(5.0, float(timeout_s) / float(total_attempts))

    for attempt in range(total_attempts):
        try:
            task = _wait_remote_task_sync(
                remote=remote,
                task_id=str(task_id),
                timeout_s=float(per_attempt_timeout_s),
            )
            # `wait_task` returning None usually means "not ready yet" (long-poll
            # timeout), not a transport fault. Return early so callers can
            # requeue/drain other in-flight work without extra retry delays.
            if task is None:
                return None
            if isinstance(task, dict):
                return task
        except Exception:
            pass
        if attempt >= retries:
            break
        stage_delay_ms = min(delay_cap_ms, base_ms * (2**max(0, int(attempt))))
        jitter_cap_ms = max(1.0, min(float(base_ms), float(stage_delay_ms)))
        delay_s = (stage_delay_ms / 1000.0) + (random.uniform(0.0, jitter_cap_ms) / 1000.0)
        time.sleep(delay_s)
    return None


def _get_remote_task_with_retries(
    *,
    remote: Any,
    task_id: str,
    get_retries: int,
    get_retry_base_ms: int,
    retry_delay_max_ms: int = 5000,
) -> dict[str, Any] | None:
    _ensure_ipfs_accelerate_path()
    from ipfs_accelerate_py.p2p_tasks.client import get_task  # type: ignore

    def _get_remote_task_sync(*, remote: Any, task_id: str) -> dict[str, Any] | None:
        async def _run_get() -> dict[str, Any] | None:
            return await get_task(remote=remote, task_id=str(task_id))

        return anyio.run(_run_get, backend="trio")

    retries = max(0, int(get_retries))
    base_ms = max(10, int(get_retry_base_ms))
    delay_cap_ms = max(base_ms, int(retry_delay_max_ms))
    total_attempts = retries + 1

    for attempt in range(total_attempts):
        try:
            task = _get_remote_task_sync(remote=remote, task_id=str(task_id))
            if isinstance(task, dict):
                return task
        except Exception:
            pass
        if attempt >= retries:
            break
        stage_delay_ms = min(delay_cap_ms, base_ms * (2**max(0, int(attempt))))
        jitter_cap_ms = max(1.0, min(float(base_ms), float(stage_delay_ms)))
        delay_s = (stage_delay_ms / 1000.0) + (random.uniform(0.0, jitter_cap_ms) / 1000.0)
        time.sleep(delay_s)
    return None


def _wait_local_task_sync(*, queue: Any, task_id: str, timeout_s: float) -> dict[str, Any] | None:
    deadline = time.time() + max(1.0, float(timeout_s))
    while time.time() < deadline:
        task = queue.get(str(task_id))
        if isinstance(task, dict) and str(task.get("status") or "") in {"completed", "failed"}:
            return task
        time.sleep(0.05)
    return None


def _reset_p2p_retry_metrics_best_effort() -> None:
    """Reset p2p retry counters if the client metrics API is available."""
    try:
        _ensure_ipfs_accelerate_path()
        from ipfs_accelerate_py.p2p_tasks.client import reset_p2p_retry_metrics  # type: ignore

        reset_p2p_retry_metrics()
    except Exception:
        # Metrics API may be unavailable in older checkouts; keep execution
        # behavior unchanged when observability is not present.
        return


def _get_p2p_retry_metrics_best_effort() -> dict[str, int]:
    """Return p2p retry counters if available, otherwise an empty mapping."""
    try:
        _ensure_ipfs_accelerate_path()
        from ipfs_accelerate_py.p2p_tasks.client import get_p2p_retry_metrics  # type: ignore

        data = get_p2p_retry_metrics()
        if isinstance(data, dict):
            return {str(k): int(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def _effective_p2p_knobs(args: argparse.Namespace) -> dict[str, Any]:
    """Return normalized p2p tuning values used by taskqueue mode."""
    return {
        "submit_retries": max(0, int(args.queue_submit_retries)),
        "submit_retry_base_ms": max(10, int(args.queue_submit_retry_base_ms)),
        "wait_retries": max(0, int(args.queue_wait_retries)),
        "wait_retry_base_ms": max(10, int(args.queue_wait_retry_base_ms)),
        "wait_slice_timeout_s": max(1.0, float(args.queue_wait_slice_timeout_s)),
        "wait_probe_interval_cycles": max(0, int(args.queue_wait_probe_interval_cycles)),
        "wait_probe_near_deadline_s": max(1.0, float(args.queue_wait_probe_near_deadline_s)),
        "wait_probe_get_retries": max(0, int(args.queue_wait_probe_get_retries)),
        "retry_dial_timeout_scale": max(1.0, float(args.queue_retry_dial_timeout_scale)),
        "retry_dial_timeout_max_s": max(1.0, float(args.queue_retry_dial_timeout_max_s)),
        "retry_delay_max_ms": max(10, int(args.queue_retry_delay_max_ms)),
        "max_concurrent_dials": max(1, int(args.queue_max_concurrent_dials)),
        "max_concurrent_wait_dials": max(1, int(args.queue_max_concurrent_wait_dials)),
        "dial_slot_timeout_s": max(0.1, float(args.queue_dial_slot_timeout_s)),
        "wait_dial_slot_timeout_s": max(0.1, float(args.queue_wait_dial_slot_timeout_s)),
        "cache_max_keys": max(64, int(args.queue_cache_max_keys)),
        "cache_stale_s": max(30.0, float(args.queue_cache_stale_s)),
        "remote_cooldown_base_ms": max(10, int(args.queue_remote_cooldown_base_ms)),
        "remote_cooldown_max_ms": max(
            int(args.queue_remote_cooldown_base_ms),
            int(args.queue_remote_cooldown_max_ms),
        ),
        "remote_penalty_decay_divisor": max(2, int(args.queue_remote_penalty_decay_divisor)),
        "remote_penalty_decay_every": int(args.queue_remote_penalty_decay_every),
        "remote_penalty_skip_threshold": int(args.queue_remote_penalty_skip_threshold),
        "retry_lightweight_discovery": bool(args.queue_retry_lightweight_discovery),
        "explicit_addr_cooldown_base_ms": max(10, int(args.queue_explicit_addr_cooldown_base_ms)),
        "explicit_addr_cooldown_max_ms": max(
            int(args.queue_explicit_addr_cooldown_base_ms),
            int(args.queue_explicit_addr_cooldown_max_ms),
        ),
        "inflight_limit": max(1, int(args.queue_inflight_limit)),
        "submit_drop_backoff_base_ms": max(0, int(args.queue_submit_drop_backoff_base_ms)),
        "submit_drop_backoff_max_ms": max(
            int(args.queue_submit_drop_backoff_base_ms),
            int(args.queue_submit_drop_backoff_max_ms),
        ),
        "remote_probe_timeout_s": max(0.1, float(args.queue_remote_probe_timeout_s)),
        "remote_min_healthy": max(0, int(args.queue_remote_min_healthy)),
        "remote_max_active": max(0, int(args.queue_remote_max_active)),
        "bootstrap_max_attempts": max(1, int(args.queue_bootstrap_max_attempts)),
        "bootstrap_seed_max_connects": max(1, int(args.queue_bootstrap_seed_max_connects)),
    }


def _format_kv_pairs(data: dict[str, Any]) -> str:
    return " ".join(f"{k}={data[k]}" for k in sorted(data.keys()))


def _group_retry_metrics(metrics: dict[str, int]) -> dict[str, int]:
    grouped = {"submit": 0, "wait": 0, "status": 0, "rpc": 0, "other": 0}
    for key, value in metrics.items():
        prefix = str(key).split(".", 1)[0].strip().lower()
        if prefix in {"submit", "wait", "status"}:
            grouped[prefix] += int(value)
        elif prefix in {
            "claim",
            "claim_many",
            "heartbeat",
            "list",
            "complete",
            "release",
            "get",
            "cancel",
            "call_tool",
            "cache_get",
            "cache_has",
            "cache_set",
            "cache_delete",
            "submit_with_info",
        }:
            grouped["rpc"] += int(value)
        else:
            grouped["other"] += int(value)
    return grouped


def _build_embedding_task_payload(
    *,
    text: str,
    queue_session_id: str,
    queue_sticky_worker_id: str,
    device: str,
) -> dict[str, Any]:
    """Build a queue payload for embedding tasks.

    In taskqueue mode, this explicitly forwards device preference so remote
    workers can honor `--device` via accelerator endpoint routing or worker
    device selection logic.
    """

    payload: dict[str, Any] = {"text": str(text)}
    if str(queue_session_id).strip():
        payload["session_id"] = str(queue_session_id).strip()
    if str(queue_sticky_worker_id).strip():
        payload["sticky_worker_id"] = str(queue_sticky_worker_id).strip()

    device_text = str(device or "").strip()
    if device_text:
        payload["device"] = device_text
        payload["endpoint_type"] = device_text

    return payload


def _embed_file_via_taskqueue(
    *,
    parquet_path: Path,
    output_path: Path,
    source_rows: int,
    row_ids: list[int],
    texts: list[str],
    model: str,
    device: str,
    task_type: str,
    taskqueue_backend: str,
    taskqueue_targets: list[str],
    taskqueue_discovery: str,
    taskqueue_discovery_timeout_s: float,
    taskqueue_discovery_limit: int,
    task_timeout_s: float,
    queue_session_id: str,
    queue_sticky_worker_id: str,
    queue_submit_log_every: int,
    queue_submit_retries: int,
    queue_submit_retry_base_ms: int,
    queue_wait_retries: int,
    queue_wait_retry_base_ms: int,
    queue_wait_slice_timeout_s: float,
    queue_wait_probe_interval_cycles: int,
    queue_wait_probe_near_deadline_s: float,
    queue_wait_probe_get_retries: int,
    queue_retry_dial_timeout_scale: float,
    queue_retry_dial_timeout_max_s: float,
    queue_retry_delay_max_ms: int,
    queue_max_concurrent_dials: int,
    queue_max_concurrent_wait_dials: int,
    queue_dial_slot_timeout_s: float,
    queue_wait_dial_slot_timeout_s: float,
    queue_cache_max_keys: int,
    queue_cache_stale_s: float,
    queue_remote_cooldown_base_ms: int,
    queue_remote_cooldown_max_ms: int,
    queue_remote_penalty_decay_every: int,
    queue_remote_penalty_decay_divisor: int,
    queue_remote_penalty_skip_threshold: int,
    queue_retry_lightweight_discovery: bool,
    queue_explicit_addr_cooldown_base_ms: int,
    queue_explicit_addr_cooldown_max_ms: int,
    queue_inflight_limit: int,
    queue_submit_drop_backoff_base_ms: int,
    queue_submit_drop_backoff_max_ms: int,
    queue_remote_probe_timeout_s: float,
    queue_remote_min_healthy: int,
    queue_remote_max_active: int,
    queue_bootstrap_max_attempts: int,
    queue_bootstrap_seed_max_connects: int,
    queue_verbose: bool,
    queue_submit_fail_hard: bool,
) -> tuple[int, int]:
    _ensure_ipfs_accelerate_path()
    from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue  # type: ignore

    # Keep p2p client submit behavior aligned with script retry controls.
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_SUBMIT_RETRIES"] = str(max(0, int(queue_submit_retries)))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_SUBMIT_RETRY_BASE_MS"] = str(max(10, int(queue_submit_retry_base_ms)))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_STATUS_RETRIES"] = str(max(0, int(queue_wait_retries)))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_STATUS_RETRY_BASE_MS"] = str(max(10, int(queue_wait_retry_base_ms)))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_WAIT_RETRIES"] = str(max(0, int(queue_wait_retries)))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_WAIT_RETRY_BASE_MS"] = str(max(10, int(queue_wait_retry_base_ms)))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_RPC_RETRIES"] = str(max(int(queue_submit_retries), int(queue_wait_retries), 0))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_RPC_RETRY_BASE_MS"] = str(
        max(10, int(queue_submit_retry_base_ms), int(queue_wait_retry_base_ms))
    )
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_RETRY_DIAL_TIMEOUT_SCALE"] = str(max(1.0, float(queue_retry_dial_timeout_scale)))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_RETRY_DIAL_TIMEOUT_MAX_S"] = str(max(1.0, float(queue_retry_dial_timeout_max_s)))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_RETRY_DELAY_MAX_MS"] = str(max(10, int(queue_retry_delay_max_ms)))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_MAX_CONCURRENT_DIALS"] = str(max(1, int(queue_max_concurrent_dials)))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_MAX_CONCURRENT_WAIT_DIALS"] = str(max(1, int(queue_max_concurrent_wait_dials)))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_DIAL_SLOT_TIMEOUT_S"] = str(max(0.1, float(queue_dial_slot_timeout_s)))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_WAIT_DIAL_SLOT_TIMEOUT_S"] = str(
        max(0.1, float(queue_wait_dial_slot_timeout_s))
    )
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_CACHE_MAX_KEYS"] = str(max(64, int(queue_cache_max_keys)))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_CACHE_STALE_S"] = str(max(30.0, float(queue_cache_stale_s)))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_COOLDOWN_BASE_MS"] = str(max(10, int(queue_remote_cooldown_base_ms)))
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_COOLDOWN_MAX_MS"] = str(
        max(int(queue_remote_cooldown_base_ms), int(queue_remote_cooldown_max_ms))
    )
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_RETRY_LIGHTWEIGHT_DISCOVERY"] = (
        "1" if bool(queue_retry_lightweight_discovery) else "0"
    )
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_EXPLICIT_ADDR_COOLDOWN_BASE_MS"] = str(
        max(10, int(queue_explicit_addr_cooldown_base_ms))
    )
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_EXPLICIT_ADDR_COOLDOWN_MAX_MS"] = str(
        max(int(queue_explicit_addr_cooldown_base_ms), int(queue_explicit_addr_cooldown_max_ms))
    )
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_BOOTSTRAP_MAX_ATTEMPTS"] = str(
        max(1, int(queue_bootstrap_max_attempts))
    )
    os.environ["IPFS_ACCELERATE_PY_TASK_P2P_BOOTSTRAP_SEED_MAX_CONNECTS"] = str(
        max(1, int(queue_bootstrap_seed_max_connects))
    )

    backend_choice = str(taskqueue_backend).strip().lower()
    explicit_targets = _parse_target_specs(taskqueue_targets)
    discovered_targets: list[Any] = []
    if backend_choice in {"remote", "auto"}:
        try:
            discovered_targets = _discover_taskqueue_targets(
                discovery_mode=taskqueue_discovery,
                timeout_s=float(taskqueue_discovery_timeout_s),
                limit=int(taskqueue_discovery_limit),
            )
        except Exception:
            discovered_targets = []

    remotes: list[Any] = []
    remotes.extend(explicit_targets)
    remotes.extend(discovered_targets)

    healthy_count = 0
    if remotes:
        remotes, probe_results = _probe_taskqueue_remotes(
            remotes=remotes,
            timeout_s=float(queue_remote_probe_timeout_s),
            verbose=bool(queue_verbose),
            status_retries=0,
        )
        healthy_remotes = [remote for _, remote, ok in probe_results if bool(ok)]
        healthy_count = sum(1 for _, _, ok in probe_results if bool(ok))
        required_healthy = max(0, int(queue_remote_min_healthy))
        if required_healthy > 0 and healthy_count < required_healthy:
            raise RuntimeError(
                "Insufficient healthy remote TaskQueue peers: "
                f"healthy={healthy_count} required={required_healthy}"
            )

        # In auto backend, avoid retry storms against clearly unhealthy peers
        # discovered on the LAN: use only probe-healthy remotes when possible,
        # and cleanly fall back to local queue when none are healthy.
        if backend_choice == "auto":
            if healthy_remotes:
                remotes = list(healthy_remotes)
                if bool(queue_verbose):
                    print(
                        "[queue:probe] "
                        f"auto backend using healthy remotes only: {len(remotes)}"
                    )
            else:
                remotes = []
                if bool(queue_verbose):
                    print("[queue:probe] auto backend found no healthy remotes; falling back to local queue")

        max_active = max(0, int(queue_remote_max_active))
        if max_active > 0 and len(remotes) > max_active:
            remotes = remotes[:max_active]
            if bool(queue_verbose):
                print(f"[queue:probe] limiting active remotes to {len(remotes)}")

    if backend_choice == "remote" and not remotes:
        raise RuntimeError("No remote TaskQueue peers resolved for --taskqueue-backend remote")

    use_remote = bool(remotes) and backend_choice in {"remote", "auto"}
    queue = None
    if not use_remote:
        queue = TaskQueue()

    pending: deque[dict[str, Any]] = deque()
    text_by_row_index: dict[int, str] = {int(r): str(t) for r, t in zip(row_ids, texts)}
    log_every = max(1, int(queue_submit_log_every))
    inflight_limit = max(1, int(queue_inflight_limit))
    # Avoid overfilling a single remote with very large in-flight windows.
    # This keeps burst pressure proportional to healthy peer count.
    if use_remote and remotes:
        per_remote_cap = 64
        adaptive_cap = max(16, len(remotes) * per_remote_cap)
        inflight_limit = min(inflight_limit, adaptive_cap)

    if bool(queue_verbose):
        print(
            "[queue:config] "
            f"use_remote={use_remote} remotes={len(remotes)} inflight_limit={inflight_limit} "
            f"submit_retries={max(0, int(queue_submit_retries))} wait_retries={max(0, int(queue_wait_retries))} "
            f"wait_slice_timeout_s={max(1.0, float(queue_wait_slice_timeout_s)):.1f} "
            f"wait_probe_interval_cycles={max(0, int(queue_wait_probe_interval_cycles))} "
            f"wait_probe_near_deadline_s={max(1.0, float(queue_wait_probe_near_deadline_s)):.1f} "
            f"wait_probe_get_retries={max(0, int(queue_wait_probe_get_retries))}"
        )
        for idx, remote in enumerate(remotes):
            print(
                "[queue:remote] "
                f"index={idx} peer_id={getattr(remote, 'peer_id', '')} "
                f"multiaddr={getattr(remote, 'multiaddr', '')}"
            )
    remote_start_offset = 0
    next_preferred_remote_index = 0
    remote_penalties: list[int] = []
    remote_failure_streaks: list[int] = []
    remote_unavailable_until: list[float] = []
    if use_remote and remotes:
        # Desynchronize first-choice remote across multiprocess runs to reduce
        # connection bursts against the same endpoint.
        remote_start_offset = (abs(hash(parquet_path.name)) + os.getpid()) % len(remotes)
        next_preferred_remote_index = int(remote_start_offset)
        remote_penalties = [0 for _ in remotes]
        remote_failure_streaks = [0 for _ in remotes]
        remote_unavailable_until = [0.0 for _ in remotes]
        # Healthy remotes are ordered first after probing; assign a startup
        # penalty to unhealthy remotes so high-throughput submit loops do not
        # keep revisiting endpoints that already failed a status probe.
        for i in range(max(0, healthy_count), len(remote_penalties)):
            remote_penalties[i] = 64

    vectors_by_row: dict[int, list[float]] = {}
    failed = 0
    completed = 0
    submit_failed = 0
    wait_requeued = 0
    submit_failure_streak = 0
    submit_count = 0
    decay_every_raw = int(queue_remote_penalty_decay_every)
    if decay_every_raw < 0:
        penalty_decay_every = 0
    elif decay_every_raw == 0:
        penalty_decay_every = max(32, len(remotes) * 8) if remotes else 64
    else:
        penalty_decay_every = max(1, decay_every_raw)
    penalty_decay_divisor = max(2, int(queue_remote_penalty_decay_divisor))

    def _decay_remote_penalties() -> None:
        if not remote_penalties:
            return
        # Let remotes recover over time so brief instability does not cause
        # long-lived starvation in sustained runs.
        for i in range(len(remote_penalties)):
            p = int(remote_penalties[i])
            if p > 1:
                remote_penalties[i] = max(0, p // penalty_decay_divisor)
            elif p == 1:
                remote_penalties[i] = 0

    def _int_field(ref: dict[str, Any], key: str, default: int) -> int:
        value = ref.get(key)
        if value is None:
            return int(default)
        try:
            return int(value)
        except Exception:
            return int(default)

    def _mark_remote_failure(remote_index: int) -> None:
        if not (0 <= int(remote_index) < len(remote_penalties)):
            return
        idx = int(remote_index)
        remote_penalties[idx] = min(1_000_000, int(remote_penalties[idx]) + 1)
        if 0 <= idx < len(remote_failure_streaks):
            remote_failure_streaks[idx] = min(1_000_000, int(remote_failure_streaks[idx]) + 1)
            streak = int(remote_failure_streaks[idx])
            cooldown_ms = min(
                max(10, int(queue_remote_cooldown_max_ms)),
                max(10, int(queue_remote_cooldown_base_ms)) * (2 ** min(streak, 8)),
            )
            if 0 <= idx < len(remote_unavailable_until):
                remote_unavailable_until[idx] = time.monotonic() + (float(cooldown_ms) / 1000.0)

    def _mark_remote_success(remote_index: int) -> None:
        nonlocal next_preferred_remote_index
        if not (0 <= int(remote_index) < len(remote_penalties)):
            return
        idx = int(remote_index)
        # Rotate preferred target after success to distribute load across
        # healthy peers instead of sticking indefinitely to one endpoint.
        next_preferred_remote_index = (idx + 1) % max(1, len(remotes))
        remote_penalties[idx] = max(0, int(remote_penalties[idx]) - 1)
        if 0 <= idx < len(remote_failure_streaks):
            remote_failure_streaks[idx] = 0
        if 0 <= idx < len(remote_unavailable_until):
            remote_unavailable_until[idx] = 0.0

    def _consume_one(ref: dict[str, Any]) -> None:
        nonlocal failed, completed, next_preferred_remote_index, wait_requeued
        t0 = time.monotonic()
        task = None
        remote_index = _int_field(ref, "remote_index", -1)
        is_remote_backend = ref.get("backend") == "remote"
        row_index = _int_field(ref, "row_index", -1)
        submitted_at_monotonic = float(ref.get("submitted_at_monotonic") or 0.0)
        if submitted_at_monotonic <= 0.0:
            submitted_at_monotonic = float(t0)
        wait_cycle = _int_field(ref, "wait_cycle", 0)
        task_age_s = max(0.0, float(t0) - float(submitted_at_monotonic))
        wait_remaining_s = max(0.0, float(task_timeout_s) - float(task_age_s))
        wait_slice_timeout_s = max(1.0, float(queue_wait_slice_timeout_s))
        per_call_wait_timeout_s = max(1.0, min(wait_slice_timeout_s, wait_remaining_s or wait_slice_timeout_s))
        if bool(queue_verbose):
            print(
                "[queue:wait] "
                f"start row_index={row_index} "
                f"task_id={str(ref.get('task_id') or '')} "
                f"remote_index={remote_index} backend={str(ref.get('backend') or '')} "
                f"wait_cycle={wait_cycle} task_age_s={task_age_s:.2f} wait_remaining_s={wait_remaining_s:.2f} "
                f"wait_timeout_s={per_call_wait_timeout_s:.2f}"
            )
        if ref.get("backend") == "remote":
            task = _wait_remote_with_retries(
                remote=ref.get("remote"),
                task_id=str(ref.get("task_id") or ""),
                timeout_s=float(per_call_wait_timeout_s),
                wait_retries=int(queue_wait_retries),
                wait_retry_base_ms=int(queue_wait_retry_base_ms),
                retry_delay_max_ms=int(queue_retry_delay_max_ms),
            )
        else:
            task = _wait_local_task_sync(
                queue=queue,
                task_id=str(ref.get("task_id") or ""),
                timeout_s=float(task_timeout_s),
            )

        # Under heavy load, probing get_task after every wait timeout can
        # amplify control-RPC traffic. Probe sparingly: periodically while the
        # task is still young, and always near timeout budget exhaustion.
        should_probe_get = False
        if not isinstance(task, dict) and is_remote_backend:
            near_deadline_s = max(1.0, float(queue_wait_probe_near_deadline_s))
            probe_interval = max(0, int(queue_wait_probe_interval_cycles))
            if wait_remaining_s <= near_deadline_s:
                should_probe_get = True
            elif probe_interval > 0 and wait_cycle > 0 and (wait_cycle % probe_interval == 0):
                should_probe_get = True

        if should_probe_get:
            task = _get_remote_task_with_retries(
                remote=ref.get("remote"),
                task_id=str(ref.get("task_id") or ""),
                get_retries=max(0, int(queue_wait_probe_get_retries)),
                get_retry_base_ms=max(10, int(queue_wait_retry_base_ms)),
                retry_delay_max_ms=int(queue_retry_delay_max_ms),
            )
            if bool(queue_verbose) and not isinstance(task, dict):
                print(
                    "[queue:wait] "
                    f"probe_empty row_index={row_index} remote_index={remote_index} "
                    f"wait_cycle={wait_cycle} wait_remaining_s={wait_remaining_s:.2f}"
                )

        if not isinstance(task, dict):
            # Avoid head-of-line blocking and false negatives under high queue
            # pressure: if the task still has overall timeout budget remaining,
            # requeue and let other in-flight tasks make progress.
            if is_remote_backend and wait_remaining_s > 0.0:
                deferred_ref = dict(ref)
                deferred_ref["submitted_at_monotonic"] = float(submitted_at_monotonic)
                deferred_ref["wait_cycle"] = int(wait_cycle) + 1
                pending.append(deferred_ref)
                wait_requeued += 1
                if bool(queue_verbose):
                    print(
                        "[queue:wait] "
                        f"requeued_no_task row_index={row_index} remote_index={remote_index} "
                        f"wait_cycle={deferred_ref['wait_cycle']} wait_remaining_s={wait_remaining_s:.2f}"
                    )
                return
            failed += 1
            _mark_remote_failure(remote_index)
            if bool(queue_verbose):
                print(
                    "[queue:wait] "
                    f"failed_no_task row_index={row_index} remote_index={remote_index} "
                    f"elapsed_s={(time.monotonic() - t0):.3f}"
                )
        else:
            status = str(task.get("status") or "")
            deferred_wait = False
            if status != "completed":
                # Remote long-poll wait can return a still-running snapshot near
                # timeout boundaries; do a short follow-up get_task probe before
                # counting this as a hard failure.
                if is_remote_backend and status in {"running", "queued", "claimed", "assigned"}:
                    grace_s = min(max(1.0, float(task_timeout_s) * 0.10), 5.0)
                    grace_deadline = time.monotonic() + grace_s
                    while time.monotonic() < grace_deadline:
                        task_probe = _get_remote_task_with_retries(
                            remote=ref.get("remote"),
                            task_id=str(ref.get("task_id") or ""),
                            get_retries=max(1, int(queue_wait_retries)),
                            get_retry_base_ms=max(10, int(queue_wait_retry_base_ms)),
                            retry_delay_max_ms=int(queue_retry_delay_max_ms),
                        )
                        if isinstance(task_probe, dict):
                            task = task_probe
                            status = str(task.get("status") or "")
                            if status == "completed":
                                emb = _extract_embedding_from_task(task)
                                if emb:
                                    vectors_by_row[row_index] = emb
                                    _mark_remote_success(remote_index)
                                    if bool(queue_verbose):
                                        print(
                                            "[queue:wait] "
                                            f"completed_after_probe row_index={row_index} remote_index={remote_index} "
                                            f"embedding_dim={len(emb)} elapsed_s={(time.monotonic() - t0):.3f}"
                                        )
                                    completed += 1
                                    if completed % log_every == 0:
                                        print(f"[queue] completed={completed}/{len(texts)} failures={failed}")
                                    return
                            if status in {"failed", "cancelled", "error"}:
                                break
                        time.sleep(0.2)
                    if bool(queue_verbose):
                        print(
                            "[queue:wait] "
                            f"grace_exhausted row_index={row_index} remote_index={remote_index} "
                            f"status={status} grace_s={grace_s:.2f}"
                        )
                    if status in {"running", "queued", "claimed", "assigned"}:
                        defer_count = _int_field(ref, "wait_defer_count", 0)
                        max_defer = max(0, int(queue_wait_retries))
                        if defer_count < max_defer:
                            deferred_wait = True
                            deferred_ref = dict(ref)
                            deferred_ref["wait_defer_count"] = defer_count + 1
                            pending.append(deferred_ref)
                            if bool(queue_verbose):
                                print(
                                    "[queue:wait] "
                                    f"deferred row_index={row_index} remote_index={remote_index} "
                                    f"status={status} defer={defer_count + 1}/{max_defer}"
                                )
                if deferred_wait:
                    return

                # If a task remains non-terminal after deferred waits, issue a
                # bounded resubmit for this row to recover from stuck task IDs.
                if is_remote_backend and use_remote and remotes:
                    resubmit_count = _int_field(ref, "resubmit_count", 0)
                    max_resubmits = max(0, min(2, int(queue_wait_retries)))
                    if resubmit_count < max_resubmits and row_index in text_by_row_index:
                        payload = _build_embedding_task_payload(
                            text=text_by_row_index[row_index],
                            queue_session_id=queue_session_id,
                            queue_sticky_worker_id=queue_sticky_worker_id,
                            device=device,
                        )
                        try:
                            preferred_remote_index = int(next_preferred_remote_index) % len(remotes)
                            new_task_id, new_remote, new_remote_index = _submit_remote_with_retries(
                                remotes=remotes,
                                preferred_remote_index=int(preferred_remote_index),
                                task_type=str(task_type),
                                model=str(model),
                                payload=payload,
                                submit_retries=int(queue_submit_retries),
                                submit_retry_base_ms=int(queue_submit_retry_base_ms),
                                retry_delay_max_ms=int(queue_retry_delay_max_ms),
                                remote_cooldown_base_ms=int(queue_remote_cooldown_base_ms),
                                remote_cooldown_max_ms=int(queue_remote_cooldown_max_ms),
                                remote_penalties=remote_penalties,
                                remote_failure_streaks=remote_failure_streaks,
                                remote_unavailable_until=remote_unavailable_until,
                                remote_penalty_skip_threshold=int(queue_remote_penalty_skip_threshold),
                                verbose=bool(queue_verbose),
                            )
                            next_preferred_remote_index = (int(new_remote_index) + 1) % max(1, len(remotes))
                            pending.append(
                                {
                                    "row_index": int(row_index),
                                    "task_id": str(new_task_id),
                                    "remote": new_remote,
                                    "remote_index": int(new_remote_index),
                                    "backend": "remote",
                                    "resubmit_count": resubmit_count + 1,
                                    "wait_defer_count": 0,
                                }
                            )
                            if bool(queue_verbose):
                                print(
                                    "[queue:wait] "
                                    f"resubmitted row_index={row_index} old_remote_index={remote_index} "
                                    f"new_remote_index={int(new_remote_index)} resubmit={resubmit_count + 1}/{max_resubmits}"
                                )
                            return
                        except Exception as resubmit_exc:
                            if bool(queue_verbose):
                                print(
                                    "[queue:wait] "
                                    f"resubmit_failed row_index={row_index} remote_index={remote_index} "
                                    f"error={type(resubmit_exc).__name__}: {resubmit_exc}"
                                )
                failed += 1
                _mark_remote_failure(remote_index)
                if bool(queue_verbose):
                    print(
                        "[queue:wait] "
                        f"failed_status row_index={row_index} remote_index={remote_index} "
                        f"status={status} elapsed_s={(time.monotonic() - t0):.3f}"
                    )
            else:
                emb = _extract_embedding_from_task(task)
                if emb:
                    vectors_by_row[row_index] = emb
                    _mark_remote_success(remote_index)
                    if bool(queue_verbose):
                        runtime = _extract_embedding_runtime_info(task)
                        runtime_suffix = ""
                        if runtime:
                            runtime_suffix = (
                                f" backend={runtime.get('backend', '')}"
                                f" device={runtime.get('device', '')}"
                                f" model={runtime.get('model', '')}"
                            )
                            if runtime.get("accelerate_error"):
                                runtime_suffix += f" accelerate_error={runtime.get('accelerate_error', '')}"
                        print(
                            "[queue:wait] "
                            f"completed row_index={row_index} remote_index={remote_index} "
                            f"embedding_dim={len(emb)} elapsed_s={(time.monotonic() - t0):.3f}"
                            f"{runtime_suffix}"
                        )
                else:
                    failed += 1
                    _mark_remote_failure(remote_index)
                    if bool(queue_verbose):
                        print(
                            "[queue:wait] "
                            f"failed_empty_embedding row_index={row_index} remote_index={remote_index} "
                            f"elapsed_s={(time.monotonic() - t0):.3f}"
                        )

        completed += 1
        if completed % log_every == 0:
            print(f"[queue] completed={completed}/{len(texts)} failures={failed}")

    for idx, (row_index, text) in enumerate(zip(row_ids, texts), start=1):
        if use_remote and remote_penalties:
            submit_count += 1
            if penalty_decay_every > 0 and submit_count % penalty_decay_every == 0:
                _decay_remote_penalties()

        payload = _build_embedding_task_payload(
            text=str(text),
            queue_session_id=queue_session_id,
            queue_sticky_worker_id=queue_sticky_worker_id,
            device=device,
        )

        if use_remote:
            try:
                preferred_remote_index = int(next_preferred_remote_index) % len(remotes)
                task_id, remote, remote_index = _submit_remote_with_retries(
                    remotes=remotes,
                    preferred_remote_index=int(preferred_remote_index),
                    task_type=str(task_type),
                    model=str(model),
                    payload=payload,
                    submit_retries=int(queue_submit_retries),
                    submit_retry_base_ms=int(queue_submit_retry_base_ms),
                    retry_delay_max_ms=int(queue_retry_delay_max_ms),
                    remote_cooldown_base_ms=int(queue_remote_cooldown_base_ms),
                    remote_cooldown_max_ms=int(queue_remote_cooldown_max_ms),
                    remote_penalties=remote_penalties,
                    remote_failure_streaks=remote_failure_streaks,
                    remote_unavailable_until=remote_unavailable_until,
                    remote_penalty_skip_threshold=int(queue_remote_penalty_skip_threshold),
                    verbose=bool(queue_verbose),
                )
                pending.append(
                    {
                        "row_index": int(row_index),
                        "task_id": str(task_id),
                        "remote": remote,
                        "remote_index": int(remote_index),
                        "backend": "remote",
                        "submitted_at_monotonic": float(time.monotonic()),
                        "wait_cycle": 0,
                    }
                )
                # Advance submit preference immediately so bursty submit loops
                # spread requests across healthy remotes before wait handling.
                next_preferred_remote_index = (int(remote_index) + 1) % max(1, len(remotes))
                submit_failure_streak = 0
            except Exception as exc:
                submit_failure_streak += 1
                submit_failed += 1
                failed += 1
                completed += 1
                if bool(queue_verbose):
                    print(
                        "[queue:submit] "
                        f"dropped row_index={int(row_index)} error={type(exc).__name__}: {exc}"
                    )
                backoff_base_ms = max(0, int(queue_submit_drop_backoff_base_ms))
                backoff_cap_ms = max(backoff_base_ms, int(queue_submit_drop_backoff_max_ms))
                if backoff_base_ms > 0:
                    exp = min(10, max(0, submit_failure_streak - 1))
                    delay_ms = min(backoff_cap_ms, backoff_base_ms * (2**exp))
                    delay_ms += random.uniform(0.0, float(backoff_base_ms))
                    if bool(queue_verbose):
                        print(
                            "[queue:submit] "
                            f"global_backoff_s={delay_ms / 1000.0:.3f} "
                            f"submit_failure_streak={submit_failure_streak}"
                        )
                    time.sleep(delay_ms / 1000.0)
                if bool(queue_submit_fail_hard):
                    raise
                if completed % log_every == 0:
                    print(f"[queue] completed={completed}/{len(texts)} failures={failed}")
                continue
        else:
            task_id = queue.submit(
                task_type=str(task_type),
                model_name=str(model),
                payload=payload,
            )
            pending.append({"row_index": int(row_index), "task_id": str(task_id), "backend": "local"})

        if idx % log_every == 0:
            print(f"[queue] submitted={idx}/{len(texts)} backend={'remote' if use_remote else 'local'}")

        # Keep in-flight queue bounded so large batch runs do not accumulate
        # excessive outstanding tasks before consuming results.
        while len(pending) >= inflight_limit:
            _consume_one(pending.popleft())

    while pending:
        _consume_one(pending.popleft())

    out_rows = sorted(vectors_by_row.items(), key=lambda x: x[0])
    if not out_rows:
        if queue is not None:
            try:
                queue.close()
            except Exception:
                pass
        return source_rows, 0

    out_df = pd.DataFrame(
        {
            "source_file": [parquet_path.name] * len(out_rows),
            "source_row_index": [int(r[0]) for r in out_rows],
            "embedding": [r[1] for r in out_rows],
        }
    )
    out_df.to_parquet(output_path, index=False)

    if failed:
        print(
            "[queue] warning: "
            f"failed_or_empty={failed} submit_failed={submit_failed} successful={len(out_rows)}"
        )
    if wait_requeued:
        print(f"[queue] wait_requeued={wait_requeued}")

    if use_remote and remote_penalties:
        nonzero = sum(1 for p in remote_penalties if int(p) > 0)
        max_penalty = max(int(p) for p in remote_penalties)
        avg_penalty = sum(int(p) for p in remote_penalties) / float(len(remote_penalties))
        print(
            "p2p_remote_penalties "
            f"remotes={len(remote_penalties)} nonzero={nonzero} "
            f"max={max_penalty} avg={avg_penalty:.2f} "
            f"decay_every={penalty_decay_every} decay_divisor={penalty_decay_divisor}"
        )

    if queue is not None:
        try:
            queue.close()
        except Exception:
            pass

    return source_rows, len(out_df)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate bulk embeddings for parquet files")
    parser.add_argument("--input-dir", required=True, help="Input directory containing parquet files")
    parser.add_argument("--glob", default="*.parquet", help="Glob for parquet files")
    parser.add_argument("--recursive", action="store_true", help="Search recursively")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Embedding model")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, help="Embeddings provider")
    parser.add_argument("--device", default="cuda", help="Embedding device, e.g. cuda/cpu")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Router batch size")
    parser.add_argument("--flush-size", type=int, default=DEFAULT_FLUSH_SIZE, help="Rows to accumulate before each router call")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing *_embeddings.parquet")
    parser.add_argument("--min-text-chars", type=int, default=24, help="Minimum chars for semantic snippets")
    parser.add_argument("--min-words", type=int, default=3, help="Minimum words for final semantic text")
    parser.add_argument(
        "--mode",
        choices=["taskqueue", "inline"],
        default="taskqueue",
        help="Execution mode: submit embedding jobs to taskqueue or run inline",
    )
    parser.add_argument(
        "--task-type",
        default="embedding",
        help="TaskQueue task_type for embedding jobs",
    )
    parser.add_argument(
        "--taskqueue-backend",
        choices=["auto", "local", "remote"],
        default="auto",
        help="TaskQueue submit backend. 'auto' prefers discovered/explicit remotes, then local queue.",
    )
    parser.add_argument(
        "--taskqueue-target",
        action="append",
        default=[],
        help="Explicit remote target in format 'peer_id::multiaddr' (repeatable)",
    )
    parser.add_argument(
        "--taskqueue-discovery",
        choices=["none", "mdns", "dht", "rendezvous", "bootstrap", "auto", "all"],
        default="all",
        help=(
            "Peer discovery mode for remote taskqueue submission "
            "(auto=mdns+dht+bootstrap env peers, all=auto+rendezvous)"
        ),
    )
    parser.add_argument(
        "--taskqueue-discovery-timeout-s",
        type=float,
        default=5.0,
        help="Discovery timeout in seconds",
    )
    parser.add_argument(
        "--taskqueue-discovery-limit",
        type=int,
        default=16,
        help="Maximum discovered peers",
    )
    parser.add_argument(
        "--task-timeout-s",
        type=float,
        default=1800.0,
        help="Per-task wait timeout in seconds",
    )
    parser.add_argument(
        "--queue-session-id",
        default="",
        help="Optional session_id tag for task affinity",
    )
    parser.add_argument(
        "--queue-sticky-worker-id",
        default="",
        help="Optional sticky_worker_id to pin tasks to a worker",
    )
    parser.add_argument(
        "--queue-submit-log-every",
        type=int,
        default=500,
        help="Progress log frequency for queue submission/completion",
    )
    parser.add_argument(
        "--queue-submit-retries",
        type=int,
        default=3,
        help="Additional remote submit retries per task for transient connection failures",
    )
    parser.add_argument(
        "--queue-submit-retry-base-ms",
        type=int,
        default=50,
        help="Base backoff (ms) for remote submit retries",
    )
    parser.add_argument(
        "--queue-wait-retries",
        type=int,
        default=2,
        help="Additional retries for remote wait_task polling when connection attempts fail",
    )
    parser.add_argument(
        "--queue-wait-retry-base-ms",
        type=int,
        default=100,
        help="Base backoff (ms) for remote wait_task retries",
    )
    parser.add_argument(
        "--queue-wait-slice-timeout-s",
        type=float,
        default=30.0,
        help=(
            "Bounded timeout (seconds) used per remote wait call before requeuing "
            "in-flight tasks; reduces head-of-line blocking under high throughput"
        ),
    )
    parser.add_argument(
        "--queue-wait-probe-interval-cycles",
        type=int,
        default=4,
        help=(
            "Run get_task probe every N wait requeue cycles (0 disables periodic probes; "
            "near-deadline probes still apply)"
        ),
    )
    parser.add_argument(
        "--queue-wait-probe-near-deadline-s",
        type=float,
        default=5.0,
        help="Force get_task probing when remaining task timeout budget is below this threshold",
    )
    parser.add_argument(
        "--queue-wait-probe-get-retries",
        type=int,
        default=0,
        help="Retry attempts for each wait-loop get_task probe (0 keeps probe to a single control RPC)",
    )
    parser.add_argument(
        "--queue-retry-dial-timeout-scale",
        type=float,
        default=1.25,
        help="Scale factor applied to dial timeout on each retry attempt",
    )
    parser.add_argument(
        "--queue-retry-dial-timeout-max-s",
        type=float,
        default=30.0,
        help="Maximum dial timeout (seconds) allowed for retry attempts",
    )
    parser.add_argument(
        "--queue-retry-delay-max-ms",
        type=int,
        default=5000,
        help="Maximum retry backoff delay (ms) before jitter for transport retries",
    )
    parser.add_argument(
        "--queue-max-concurrent-dials",
        type=int,
        default=32,
        help="Process-level limit for concurrent submit/status/short-RPC dial attempts",
    )
    parser.add_argument(
        "--queue-max-concurrent-wait-dials",
        type=int,
        default=128,
        help="Process-level limit for concurrent long-poll wait dial attempts",
    )
    parser.add_argument(
        "--queue-dial-slot-timeout-s",
        type=float,
        default=10.0,
        help="Seconds to wait for a dial slot before failing that attempt",
    )
    parser.add_argument(
        "--queue-wait-dial-slot-timeout-s",
        type=float,
        default=30.0,
        help="Seconds to wait for a long-poll wait dial slot before failing that attempt",
    )
    parser.add_argument(
        "--queue-cache-max-keys",
        type=int,
        default=1024,
        help="Maximum discovered multiaddr cache entries retained in-process",
    )
    parser.add_argument(
        "--queue-cache-stale-s",
        type=float,
        default=1800.0,
        help="Seconds after which idle discovered multiaddr cache entries are pruned",
    )
    parser.add_argument(
        "--queue-remote-cooldown-base-ms",
        type=int,
        default=25,
        help="Base cooldown (ms) applied per remote peer after retryable transport failures",
    )
    parser.add_argument(
        "--queue-remote-cooldown-max-ms",
        type=int,
        default=1000,
        help="Maximum cooldown (ms) applied per remote peer after repeated failures",
    )
    parser.add_argument(
        "--queue-remote-penalty-decay-every",
        type=int,
        default=0,
        help=(
            "Remote submit-count interval for penalty decay; 0 uses adaptive default, "
            "negative disables decay"
        ),
    )
    parser.add_argument(
        "--queue-remote-penalty-decay-divisor",
        type=int,
        default=2,
        help="Penalty decay divisor (>=2). Larger values decay penalties more aggressively.",
    )
    parser.add_argument(
        "--queue-remote-penalty-skip-threshold",
        type=int,
        default=-1,
        help=(
            "Skip remotes with penalty above this value during submit selection; "
            "negative disables skipping"
        ),
    )
    parser.add_argument(
        "--queue-retry-lightweight-discovery",
        dest="queue_retry_lightweight_discovery",
        action="store_true",
        help="Use lightweight dialing on retries (cache + announce) and skip broad discovery fanout",
    )
    parser.add_argument(
        "--queue-no-retry-lightweight-discovery",
        dest="queue_retry_lightweight_discovery",
        action="store_false",
        help="Allow broad discovery fanout during retry attempts",
    )
    parser.set_defaults(queue_retry_lightweight_discovery=True)
    parser.add_argument(
        "--queue-explicit-addr-cooldown-base-ms",
        type=int,
        default=250,
        help="Base cooldown (ms) for stale explicit/cache/announce multiaddrs after transport failures",
    )
    parser.add_argument(
        "--queue-explicit-addr-cooldown-max-ms",
        type=int,
        default=5000,
        help="Maximum cooldown (ms) for stale explicit/cache/announce multiaddrs",
    )
    parser.add_argument(
        "--queue-inflight-limit",
        type=int,
        default=256,
        help="Maximum number of outstanding taskqueue jobs before draining results",
    )
    parser.add_argument(
        "--queue-submit-drop-backoff-base-ms",
        type=int,
        default=100,
        help="Global backoff base (ms) applied after each dropped submit while fail-soft mode continues",
    )
    parser.add_argument(
        "--queue-submit-drop-backoff-max-ms",
        type=int,
        default=5000,
        help="Maximum global backoff (ms) applied after consecutive dropped submits",
    )
    parser.add_argument(
        "--queue-remote-probe-timeout-s",
        type=float,
        default=1.5,
        help="Per-remote status probe timeout (seconds) used to prioritize healthy remotes",
    )
    parser.add_argument(
        "--queue-remote-min-healthy",
        type=int,
        default=0,
        help="Require at least this many healthy remotes before starting (0 disables requirement)",
    )
    parser.add_argument(
        "--queue-remote-max-active",
        type=int,
        default=8,
        help="Maximum active remotes after probing (0 keeps all)",
    )
    parser.add_argument(
        "--queue-bootstrap-max-attempts",
        type=int,
        default=4,
        help="Maximum direct bootstrap dial attempts per discovery pass",
    )
    parser.add_argument(
        "--queue-bootstrap-seed-max-connects",
        type=int,
        default=8,
        help="Maximum bootstrap connects when seeding DHT routing tables",
    )
    parser.add_argument(
        "--queue-submit-fail-hard",
        action="store_true",
        help="Abort immediately when a remote submit exhausts retries (default: fail soft and continue)",
    )
    parser.add_argument(
        "--queue-verbose",
        action="store_true",
        help="Print detailed per-task queue submit/wait diagnostics",
    )
    parser.add_argument(
        "--queue-report-p2p-retry-metrics",
        action="store_true",
        help="Print p2p retry counters at the end of the run when using remote taskqueue",
    )
    parser.add_argument(
        "--queue-reset-p2p-retry-metrics",
        action="store_true",
        help="Reset p2p retry counters at run start when using remote taskqueue",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="Optional cap on embeddable rows per parquet file (0 means all)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    input_dir = _resolve_input_dir(args.input_dir)
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {input_dir}")

    files = list(_iter_parquet_files(input_dir, args.glob, args.recursive))
    print(f"input_dir={input_dir}")
    print(
        f"files={len(files)} model={args.model} provider={args.provider} device={args.device} "
        f"mode={args.mode} taskqueue_backend={args.taskqueue_backend}"
    )

    backend_choice = str(args.taskqueue_backend).strip().lower()
    using_remote_queue = str(args.mode).strip().lower() == "taskqueue" and backend_choice in {"remote", "auto"}
    if using_remote_queue:
        print(f"p2p_effective_knobs {_format_kv_pairs(_effective_p2p_knobs(args))}")
    if using_remote_queue and bool(args.queue_reset_p2p_retry_metrics):
        _reset_p2p_retry_metrics_best_effort()

    total_rows = 0
    total_embedded = 0

    for parquet_path in files:
        output_path = parquet_path.with_name(f"{parquet_path.stem}_embeddings.parquet")
        if output_path.exists() and not args.overwrite:
            print(f"[skip] {output_path} exists (use --overwrite)")
            continue

        source_rows, embedded_rows = _embed_file(
            parquet_path,
            output_path=output_path,
            model=args.model,
            provider=args.provider,
            device=args.device,
            batch_size=int(args.batch_size),
            flush_size=int(args.flush_size),
            min_text_chars=int(args.min_text_chars),
            min_words=int(args.min_words),
            mode=str(args.mode),
            task_type=str(args.task_type),
            taskqueue_backend=str(args.taskqueue_backend),
            taskqueue_targets=list(args.taskqueue_target or []),
            taskqueue_discovery=str(args.taskqueue_discovery),
            taskqueue_discovery_timeout_s=float(args.taskqueue_discovery_timeout_s),
            taskqueue_discovery_limit=int(args.taskqueue_discovery_limit),
            task_timeout_s=float(args.task_timeout_s),
            queue_session_id=str(args.queue_session_id),
            queue_sticky_worker_id=str(args.queue_sticky_worker_id),
            queue_submit_log_every=int(args.queue_submit_log_every),
            queue_submit_retries=int(args.queue_submit_retries),
            queue_submit_retry_base_ms=int(args.queue_submit_retry_base_ms),
            queue_wait_retries=int(args.queue_wait_retries),
            queue_wait_retry_base_ms=int(args.queue_wait_retry_base_ms),
            queue_wait_slice_timeout_s=float(args.queue_wait_slice_timeout_s),
            queue_wait_probe_interval_cycles=int(args.queue_wait_probe_interval_cycles),
            queue_wait_probe_near_deadline_s=float(args.queue_wait_probe_near_deadline_s),
            queue_wait_probe_get_retries=int(args.queue_wait_probe_get_retries),
            queue_retry_dial_timeout_scale=float(args.queue_retry_dial_timeout_scale),
            queue_retry_dial_timeout_max_s=float(args.queue_retry_dial_timeout_max_s),
            queue_retry_delay_max_ms=int(args.queue_retry_delay_max_ms),
            queue_max_concurrent_dials=int(args.queue_max_concurrent_dials),
            queue_max_concurrent_wait_dials=int(args.queue_max_concurrent_wait_dials),
            queue_dial_slot_timeout_s=float(args.queue_dial_slot_timeout_s),
            queue_wait_dial_slot_timeout_s=float(args.queue_wait_dial_slot_timeout_s),
            queue_cache_max_keys=int(args.queue_cache_max_keys),
            queue_cache_stale_s=float(args.queue_cache_stale_s),
            queue_remote_cooldown_base_ms=int(args.queue_remote_cooldown_base_ms),
            queue_remote_cooldown_max_ms=int(args.queue_remote_cooldown_max_ms),
            queue_remote_penalty_decay_every=int(args.queue_remote_penalty_decay_every),
            queue_remote_penalty_decay_divisor=int(args.queue_remote_penalty_decay_divisor),
            queue_remote_penalty_skip_threshold=int(args.queue_remote_penalty_skip_threshold),
            queue_retry_lightweight_discovery=bool(args.queue_retry_lightweight_discovery),
            queue_explicit_addr_cooldown_base_ms=int(args.queue_explicit_addr_cooldown_base_ms),
            queue_explicit_addr_cooldown_max_ms=int(args.queue_explicit_addr_cooldown_max_ms),
            queue_inflight_limit=int(args.queue_inflight_limit),
            queue_submit_drop_backoff_base_ms=int(args.queue_submit_drop_backoff_base_ms),
            queue_submit_drop_backoff_max_ms=int(args.queue_submit_drop_backoff_max_ms),
            queue_remote_probe_timeout_s=float(args.queue_remote_probe_timeout_s),
            queue_remote_min_healthy=int(args.queue_remote_min_healthy),
            queue_remote_max_active=int(args.queue_remote_max_active),
            queue_bootstrap_max_attempts=int(args.queue_bootstrap_max_attempts),
            queue_bootstrap_seed_max_connects=int(args.queue_bootstrap_seed_max_connects),
            queue_verbose=bool(args.queue_verbose),
            queue_submit_fail_hard=bool(args.queue_submit_fail_hard),
            max_rows=int(args.max_rows),
        )
        total_rows += source_rows
        total_embedded += embedded_rows
        output_label = str(output_path) if output_path.exists() else "<none>"
        print(
            f"[done] {parquet_path.name}: source_rows={source_rows} embedded_rows={embedded_rows} "
            f"output={output_label}"
        )

    print(f"completed total_source_rows={total_rows} total_embedded_rows={total_embedded}")
    if using_remote_queue and bool(args.queue_report_p2p_retry_metrics):
        metrics = _get_p2p_retry_metrics_best_effort()
        if metrics:
            ordered = " ".join(f"{k}={metrics[k]}" for k in sorted(metrics.keys()))
            print(f"p2p_retry_metrics {ordered}")
            print(f"p2p_retry_metric_groups {_format_kv_pairs(_group_retry_metrics(metrics))}")
        else:
            print("p2p_retry_metrics <empty>")
            print("p2p_retry_metric_groups other=0 rpc=0 status=0 submit=0 wait=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
