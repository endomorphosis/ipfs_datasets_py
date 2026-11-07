"""Collision-safe allocation of staging/pdf/_manifest/batch_NNNN numbers (PDF_STAGING.md contract).

Every writer of batch_NNNN.{jsonl,ready} must go through this module:
  * an flock on _manifest/.batch_alloc.lock serialises allocators that use this helper;
  * the number is max(N over every batch_NNNN* file on disk: .jsonl/.jsonl.tmp/.ready/.pushed/.retry.json/.reserved/...)+1;
  * the .jsonl.tmp is created with O_CREAT|O_EXCL, and the final .jsonl is created with os.link (never overwrites)
    and .ready with O_EXCL, so even a writer that ignores the lock can never be overwritten by us (we move on to the
    next number on any FileExistsError).
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Optional

_NUM = re.compile(r"^batch_(\d{4,})(?:\.|$)")
LOCK_NAME = ".batch_alloc.lock"


def max_on_disk(man: Path, floor: int = 0) -> int:
    hi = floor
    try:
        names = os.listdir(man)
    except FileNotFoundError:
        return hi
    for nm in names:
        m = _NUM.match(nm)
        if m:
            hi = max(hi, int(m.group(1)))
    return hi


def _taken(man: Path, n: int) -> bool:
    pre = f"batch_{n:04d}"
    return any(nm == pre or nm.startswith(pre + ".") for nm in os.listdir(man))


@contextmanager
def alloc_lock(man: Path, timeout: float = 120.0):
    man.mkdir(parents=True, exist_ok=True)
    fd = os.open(man / LOCK_NAME, os.O_CREAT | os.O_RDWR, 0o644)
    t0 = time.time()
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() - t0 > timeout:
                    raise TimeoutError(f"{man / LOCK_NAME} held > {timeout}s")
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


def open_new_batch(man: Path, floor: int = 0, retries: int = 1000):
    """Allocate a number and exclusively create batch_NNNN.jsonl.tmp. Returns (n, tmp_path, file object)."""
    with alloc_lock(man):
        n = max_on_disk(man, floor) + 1
        for _ in range(retries):
            if _taken(man, n):
                n += 1
                continue
            tmp = man / f"batch_{n:04d}.jsonl.tmp"
            try:
                fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                n += 1
                continue
            return n, tmp, os.fdopen(fd, "w", encoding="utf-8")
    raise RuntimeError("no free batch number")


def seal_batch(man: Path, n: int, tmp: Path, floor: int = 0) -> int:
    """tmp (closed, fsynced) -> batch_NNNN.jsonl (+ empty .ready LAST). Never overwrites: if the final names exist
    (someone ignored the lock), the rows move to a freshly allocated number. Returns the number actually used."""
    while True:
        fin = man / f"batch_{n:04d}.jsonl"
        try:
            if (man / f"batch_{n:04d}.ready").exists() or (man / f"batch_{n:04d}.pushed").exists():
                raise FileExistsError(str(fin))
            os.link(tmp, fin)                      # fails if fin exists -> no overwrite
        except FileExistsError:
            n2, tmp2, f2 = open_new_batch(man, floor)
            f2.close()
            os.replace(tmp, tmp2)                  # tmp2 is our own empty O_EXCL file
            n, tmp = n2, tmp2
            continue
        os.unlink(tmp)
        rfd = os.open(man / f"batch_{n:04d}.ready", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.close(rfd)
        return n


def write_batch(man: Path, rows: Iterable[dict], floor: int = 0) -> int:
    """Allocate + write + seal a complete batch atomically. Returns the batch number."""
    n, tmp, f = open_new_batch(man, floor)
    with f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return seal_batch(man, n, tmp, floor)


# ---------------------------------------------------------------- pushed-vs-manifest consistency
def manifest_row_count(p: Path) -> int:
    with open(p, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


GRACE_S = 60.0  # a manifest rewritten in the same second as its .pushed (10/18 shard migration) is not a collision


def stale_pushed(man: Path, batch: str, grace: float = GRACE_S) -> list:
    """Reasons a batch with a .pushed must be re-pushed: its .jsonl/.ready was rewritten after the .pushed (number
    collision / overwrite), or the pushed record count differs from the manifest row count. [] = consistent."""
    pushed, jl, rd = man / f"{batch}.pushed", man / f"{batch}.jsonl", man / f"{batch}.ready"
    if not (pushed.exists() and jl.exists() and rd.exists()):
        return []
    why = []
    pm = pushed.stat().st_mtime
    for p in (jl, rd):
        if p.stat().st_mtime > pm + grace:
            why.append(f"{p.name}_newer_than_pushed")
    try:
        rec = json.loads(pushed.read_text()).get("records")
    except (ValueError, OSError):
        rec = None
    n = manifest_row_count(jl)
    if rec is not None and int(rec) != n:
        why.append(f"pushed_records_{rec}!=manifest_rows_{n}")
    return why


def stale_batches(man: Path) -> dict:
    out = {}
    if not man.is_dir():
        return out
    for p in sorted(man.glob("batch_*.pushed")):
        b = p.name[: -len(".pushed")]
        w = stale_pushed(man, b)
        if w:
            out[b] = w
    return out


def supersede_pushed(man: Path, batch: str) -> Optional[Path]:
    """Move (never delete) a stale .pushed to _manifest/_superseded/ so the batch becomes ready again."""
    p = man / f"{batch}.pushed"
    if not p.exists():
        return None
    d = man / "_superseded"
    d.mkdir(exist_ok=True)
    dst = d / f"{batch}.pushed.{time.strftime('%Y%m%dT%H%M%S')}"
    os.replace(p, dst)
    return dst
