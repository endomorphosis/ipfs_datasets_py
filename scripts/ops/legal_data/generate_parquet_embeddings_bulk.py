#!/usr/bin/env python3
"""Generate semantic embeddings for parquet rows in bulk.

This script is designed for large parquet ingestion runs where the same model
runtime should remain hot in one process. It uses embeddings_router with
local HF defaults and writes companion *_embeddings.parquet files.
"""

from __future__ import annotations

import argparse
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
    parts: list[str] = []
    used = set()

    for key in PREFERRED_FIELDS:
        if key in row and pd.notna(row[key]):
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
        if pd.isna(raw_value):
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
        discover_peers_via_dht_sync,
        discover_peers_via_mdns_sync,
        discover_peers_via_rendezvous_sync,
    )

    mode = str(discovery_mode).strip().lower()
    out: list[Any] = []

    if mode in {"none", ""}:
        return out
    if mode in {"mdns", "all"}:
        out.extend(discover_peers_via_mdns_sync(timeout_s=timeout_s, limit=limit, exclude_self=True))
    if mode in {"dht", "all"}:
        out.extend(discover_peers_via_dht_sync(timeout_s=timeout_s, limit=limit, exclude_self=True, namespace=""))
    if mode in {"rendezvous", "all"}:
        out.extend(discover_peers_via_rendezvous_sync(timeout_s=timeout_s, limit=limit, exclude_self=True, namespace=""))

    # Deduplicate by (peer_id, multiaddr)
    deduped: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for remote in out:
        peer = str(getattr(remote, "peer_id", "") or "").strip()
        addr = str(getattr(remote, "multiaddr", "") or "").strip()
        key = (peer, addr)
        if not peer or not addr or key in seen:
            continue
        seen.add(key)
        deduped.append(remote)
    return deduped


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


def _wait_local_task_sync(*, queue: Any, task_id: str, timeout_s: float) -> dict[str, Any] | None:
    deadline = time.time() + max(1.0, float(timeout_s))
    while time.time() < deadline:
        task = queue.get(str(task_id))
        if isinstance(task, dict) and str(task.get("status") or "") in {"completed", "failed"}:
            return task
        time.sleep(0.05)
    return None


def _embed_file_via_taskqueue(
    *,
    parquet_path: Path,
    output_path: Path,
    source_rows: int,
    row_ids: list[int],
    texts: list[str],
    model: str,
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
) -> tuple[int, int]:
    _ensure_ipfs_accelerate_path()
    from ipfs_accelerate_py.p2p_tasks.client import submit_task_sync  # type: ignore
    from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue  # type: ignore

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

    if backend_choice == "remote" and not remotes:
        raise RuntimeError("No remote TaskQueue peers resolved for --taskqueue-backend remote")

    use_remote = bool(remotes) and backend_choice in {"remote", "auto"}
    queue = None
    if not use_remote:
        queue = TaskQueue()

    pending: list[dict[str, Any]] = []
    log_every = max(1, int(queue_submit_log_every))

    for idx, (row_index, text) in enumerate(zip(row_ids, texts), start=1):
        payload: dict[str, Any] = {"text": str(text)}
        if str(queue_session_id).strip():
            payload["session_id"] = str(queue_session_id).strip()
        if str(queue_sticky_worker_id).strip():
            payload["sticky_worker_id"] = str(queue_sticky_worker_id).strip()

        if use_remote:
            remote = remotes[(idx - 1) % len(remotes)]
            task_id = submit_task_sync(
                remote=remote,
                task_type=str(task_type),
                model_name=str(model),
                payload=payload,
            )
            pending.append({"row_index": int(row_index), "task_id": str(task_id), "remote": remote, "backend": "remote"})
        else:
            task_id = queue.submit(
                task_type=str(task_type),
                model_name=str(model),
                payload=payload,
            )
            pending.append({"row_index": int(row_index), "task_id": str(task_id), "backend": "local"})

        if idx % log_every == 0:
            print(f"[queue] submitted={idx}/{len(texts)} backend={'remote' if use_remote else 'local'}")

    vectors_by_row: dict[int, list[float]] = {}
    failed = 0

    for i, ref in enumerate(pending, start=1):
        task = None
        if ref.get("backend") == "remote":
            task = _wait_remote_task_sync(
                remote=ref.get("remote"),
                task_id=str(ref.get("task_id") or ""),
                timeout_s=float(task_timeout_s),
            )
        else:
            task = _wait_local_task_sync(
                queue=queue,
                task_id=str(ref.get("task_id") or ""),
                timeout_s=float(task_timeout_s),
            )

        row_index = int(ref.get("row_index") or -1)
        if not isinstance(task, dict):
            failed += 1
        else:
            status = str(task.get("status") or "")
            if status != "completed":
                failed += 1
            else:
                emb = _extract_embedding_from_task(task)
                if emb:
                    vectors_by_row[row_index] = emb
                else:
                    failed += 1

        if i % log_every == 0:
            print(f"[queue] completed={i}/{len(pending)} failures={failed}")

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
        print(f"[queue] warning: failed_or_empty={failed} successful={len(out_rows)}")

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
        choices=["none", "mdns", "dht", "rendezvous", "all"],
        default="all",
        help="Peer discovery mode for remote taskqueue submission",
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
