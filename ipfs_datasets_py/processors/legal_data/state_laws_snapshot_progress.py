"""Progress snapshot and stall classification for the 51-jurisdiction GraphRAG build."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

DEFAULT_DEST = (
    Path.home()
    / ".ipfs_datasets"
    / "state_laws"
    / "snapshot-graphrag-v2026.08.31-all51-cuda"
)
DEFAULT_STATUS_PATH = DEFAULT_DEST / "watcher_status.json"
DEFAULT_LCR_TODO = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "architecture"
    / "legal_corpora_reindex.todo.md"
)
BUILDER_MARKER = "build_state_laws_snapshot_sparse_graphrag.py"
SCHEMA: Final = "ipfs_datasets_py.state_laws.snapshot_graphrag.progress.v1"
LCR_BOARD_SCHEMA: Final = "ipfs_datasets_py.lcr.board_snapshot.v1"
_LIVE_OFFICIAL_TASK_IDS: Final[frozenset[str]] = frozenset({"LCR-084"})
_LIVE_OFFICIAL_MARKERS: Final[tuple[str, ...]] = (
    "require-live-official",
    "residential proxy",
    "fresh exhaustive official evidence for exactly 51",
    "reobserves all official state",
)
_PUBLICATION_MARKERS: Final[tuple[str, ...]] = (
    "current-bundle",
    "authorizing_for_publication",
    "justicedao/ipfs_state_laws",
    "justicedao/ipfs_federal_register",
)
_SNAPSHOT_MARKERS: Final[tuple[str, ...]] = (
    "snapshot_research",
    "snapshot-graphrag",
    "tmp_laws",
)
STALL_SECONDS_QUIET_SORT = 20 * 60
STALL_SECONDS_DEAD = 60


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return dict(payload) if isinstance(payload, Mapping) else None


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _iter_python_cmds() -> list[dict[str, Any]]:
    proc = Path("/proc")
    if not proc.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for item in proc.iterdir():
        if not item.name.isdigit():
            continue
        try:
            raw = (item / "cmdline").read_bytes()
        except OSError:
            continue
        argv = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
        if not argv:
            continue
        line = " ".join(argv)
        if BUILDER_MARKER not in line:
            continue
        rss = 0
        try:
            status = (item / "status").read_text(encoding="utf-8")
        except OSError:
            status = ""
        for row in status.splitlines():
            if row.startswith("VmRSS:"):
                try:
                    rss = int(row.split()[1]) * 1024
                except (IndexError, ValueError):
                    rss = 0
                break
        found.append(
            {
                "argv": argv,
                "cmdline": line,
                "pid": int(item.name),
                "rss_bytes": rss,
            }
        )
    return found


def _tail(path: Path, *, max_bytes: int = 8192) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
            data = handle.read()
    except OSError:
        return ""
    return data.decode("utf-8", "replace")


def _stage_from_log(text: str) -> str:
    stage = "unknown"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("snapshot stage="):
            stage = stripped.split("=", 1)[1].split()[0]
        elif stripped.startswith("Traceback") or "out of memory" in stripped.lower():
            stage = "failed"
    return stage


def _classify_lcr_text(task_id: str, body: str) -> str:
    ident = task_id.strip().upper()
    blob = f"{ident}\n{body}".lower()
    if ident in _LIVE_OFFICIAL_TASK_IDS or any(m in blob for m in _LIVE_OFFICIAL_MARKERS):
        return "host_blocked"
    if any(m in blob for m in _PUBLICATION_MARKERS) and not any(
        m in blob for m in _SNAPSHOT_MARKERS
    ):
        return "publication_gated"
    return "rd_feasible"


def summarize_lcr_board(todo_path: Path | None = None) -> dict[str, Any]:
    """Count remaining LCR tasks and mark host-impossible demands."""

    path = Path(todo_path or DEFAULT_LCR_TODO)
    counts = {"completed": 0, "todo": 0, "other": 0}
    remaining: list[dict[str, str]] = []
    blocked: list[str] = []
    gated: list[str] = []
    feasible: list[str] = []
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        chunks = text.replace("\r\n", "\n").split("\n## ")
        for raw in chunks:
            chunk = raw[3:] if raw.startswith("## ") else raw
            if not chunk.startswith("LCR-"):
                continue
            header = chunk.split("\n", 1)[0].strip()
            task_id = header.split()[0]
            status = "other"
            for line in chunk.splitlines():
                if line.startswith("- Status:"):
                    status = line.split(":", 1)[1].strip().lower()
                    break
            if status == "completed":
                counts["completed"] += 1
                continue
            if status == "todo":
                counts["todo"] += 1
            else:
                counts["other"] += 1
            kind = _classify_lcr_text(task_id, chunk)
            remaining.append({"classification": kind, "status": status, "task_id": task_id})
            if kind == "host_blocked":
                blocked.append(task_id)
            elif kind == "publication_gated":
                gated.append(task_id)
            else:
                feasible.append(task_id)
    return {
        "blocked": blocked,
        "counts": counts,
        "feasible": feasible,
        "gated": gated,
        "path": str(path),
        "remaining": remaining,
        "schema": LCR_BOARD_SCHEMA,
    }


def snapshot_graphrag_progress(
    dest: Path | None = None,
    *,
    processes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Observe the all-51 snapshot GraphRAG dest without mutating it."""

    root = Path(dest or DEFAULT_DEST)
    embedding_manifest = _load_json(root / "checkpoints" / "embeddings" / "manifest.json") or {}
    receipt = root / "snapshot_build_receipt.json"
    hf_manifest = root / "hf-release" / "manifest.json"
    logs = [
        root / "build.resume2.log",
        root / "build.resume.log",
        root / "build.log",
    ]
    log_path = next((path for path in logs if path.is_file()), logs[0])
    log_text = _tail(log_path)
    postings_ckpt = (
        root
        / "bm25-work"
        / "postings"
        / "postings-sort"
        / "sort_checkpoint.json"
    )
    postings = _load_json(postings_ckpt) or {}
    builders = list(processes) if processes is not None else _iter_python_cmds()
    dest_alive = bool(builders)
    stage = _stage_from_log(log_text)
    if receipt.is_file() and hf_manifest.is_file():
        stage = "complete"
    elif dest_alive and stage in {"unknown", "failed"}:
        stage = "running"
    signature_payload = {
        "embedding_rows": embedding_manifest.get("row_count"),
        "hf": hf_manifest.is_file(),
        "log_mtime": _mtime(log_path),
        "postings_consumed": postings.get("records_consumed"),
        "postings_mtime": _mtime(postings_ckpt.parent) if postings_ckpt.parent.exists() else None,
        "process_count": len(builders),
        "receipt": receipt.is_file(),
        "stage": stage,
    }
    signature = hashlib.sha256(
        json.dumps(signature_payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    lcr = summarize_lcr_board()
    return {
        "authorizing_for_publication": False,
        "builders": builders,
        "dest": str(root),
        "embedding_batch_count": embedding_manifest.get("batch_count") or 0,
        "embedding_row_count": embedding_manifest.get("row_count") or 0,
        "hf_manifest": hf_manifest.is_file(),
        "lcr_board": lcr,
        "log_mtime": _mtime(log_path),
        "log_path": str(log_path),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "postings_records_consumed": int(postings.get("records_consumed") or 0),
        "process_alive": dest_alive,
        "receipt": receipt.is_file(),
        "schema": SCHEMA,
        "signature": signature,
        "stage": stage,
    }


def classify_progress(
    current: Mapping[str, Any],
    *,
    previous: Mapping[str, Any] | None = None,
    now: float | None = None,
    stall_seconds: float = STALL_SECONDS_QUIET_SORT,
) -> dict[str, Any]:
    """Classify GraphRAG health. Quiet BM25 sorts are progress if counters move."""

    clock = time.time() if now is None else now
    if current.get("receipt") and current.get("hf_manifest"):
        return {
            "health": "complete",
            "reason": "snapshot_build_receipt_present",
            "retry": False,
        }
    if current.get("stage") == "failed":
        return {
            "health": "blocked",
            "reason": "builder_log_failed",
            "retry": bool(current.get("embedding_row_count")),
        }
    if not current.get("process_alive"):
        return {
            "health": "blocked",
            "reason": "builder_process_dead",
            "retry": bool(int(current.get("embedding_row_count") or 0) > 0)
            and not current.get("receipt"),
        }
    if previous is None:
        return {"health": "progressing", "reason": "first_sample", "retry": False}
    prev_sig = str(previous.get("signature") or "")
    cur_sig = str(current.get("signature") or "")
    if prev_sig and prev_sig != cur_sig:
        return {"health": "progressing", "reason": "signature_changed", "retry": False}
    prev_at = previous.get("observed_epoch")
    if not isinstance(prev_at, (int, float)):
        return {"health": "progressing", "reason": "missing_prior_epoch", "retry": False}
    quiet = clock - float(prev_at)
    if quiet >= stall_seconds:
        return {
            "health": "stalled",
            "reason": f"no_progress_for_{int(quiet)}s",
            "retry": False,
        }
    return {"health": "progressing", "reason": "within_stall_window", "retry": False}


def load_status(path: Path) -> dict[str, Any] | None:
    payload = _load_json(path)
    return payload


def write_status(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    body["observed_epoch"] = time.time()
    tmp = path.with_name(f".{path.name}.partial")
    tmp.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
