"""Process / host memory watchdog for large IR builds (DO OOM lesson).

Env overrides:
  IR_MEM_WARN_GIB   MemAvailable threshold to shed collectors (default 3.5)
  IR_MEM_ABORT_GIB  MemAvailable abort floor (default 2.5)
  IR_RSS_ABORT_GIB  process RSS hard abort (default 12.0)
  IR_MEM_LOG_EVERY  rows between mem logs when callers pass every_n (default 5000)
"""
from __future__ import annotations

import gc
import os
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

DEFAULT_WARN_GIB = 3.5
DEFAULT_ABORT_AVAIL_GIB = 2.5
DEFAULT_ABORT_RSS_GIB = 12.0
DEFAULT_LOG_EVERY = 5000

# Prefer shedding zero-article / lean collectors first; protect AT+DK until last.
DEFAULT_SHED_ORDER: list[tuple[str, tuple[str, ...]]] = [
    ("mm", ("collect_mm", "run_collector_cc.sh collect_mm")),
    ("th", ("collect_th", "run_collector_cc.sh collect_th")),
    ("is-reg", ("collect_is", "is-reg", "run_collector_cc.sh collect_is")),
    ("lt", ("collect_lt", "run_collector_cc.sh collect_lt")),
    ("kw", ("collect_kw", "run_collector_cc.sh collect_kw")),
    ("mt", ("collect_mt", "run_collector_cc.sh collect_mt")),
    ("dk", ("collect_dk", "run_collector_cc.sh collect_dk")),
    ("at", ("collect_at", "run_collector_cc.sh collect_at", "at_deepen")),
]


class MemAbort(RuntimeError):
    """Raised when MemAvailable or RSS crosses hard abort thresholds."""


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def warn_gib() -> float:
    return _env_float("IR_MEM_WARN_GIB", DEFAULT_WARN_GIB)


def abort_avail_gib() -> float:
    return _env_float("IR_MEM_ABORT_GIB", DEFAULT_ABORT_AVAIL_GIB)


def abort_rss_gib() -> float:
    return _env_float("IR_RSS_ABORT_GIB", DEFAULT_ABORT_RSS_GIB)


def log_every() -> int:
    try:
        return max(1, int(os.environ.get("IR_MEM_LOG_EVERY", DEFAULT_LOG_EVERY)))
    except ValueError:
        return DEFAULT_LOG_EVERY


def mem_available_gib() -> float:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 / 1024
    except Exception:
        pass
    return -1.0


def rss_gib(pid: int | None = None) -> float:
    path = Path(f"/proc/{pid or 'self'}/status")
    try:
        for line in path.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024 / 1024
    except Exception:
        pass
    return -1.0


def snapshot(stage: str = "") -> dict[str, Any]:
    return {
        "stage": stage,
        "mem_avail_gib": round(mem_available_gib(), 3),
        "rss_gib": round(rss_gib(), 3),
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def log_mem(stage: str, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    snap = snapshot(stage)
    msg = (
        f"mem stage={stage} MemAvailable={snap['mem_avail_gib']:.2f}G "
        f"RSS={snap['rss_gib']:.2f}G"
    )
    if log is not None:
        log(msg)
    else:
        print(f"[{snap['ts']}] {msg}", flush=True)
    return snap


def discover_pids(*patterns: str) -> list[int]:
    found: list[int] = []
    try:
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                cmd = (proc / "cmdline").read_bytes().replace(b"\x00", b" ").decode(
                    "utf-8", "ignore"
                )
            except Exception:
                continue
            if any(p in cmd for p in patterns):
                found.append(int(proc.name))
    except Exception:
        pass
    return found


def shed_collectors(
    stage: str,
    *,
    warn: float | None = None,
    protect: frozenset[str] | None = None,
    log: Callable[[str], None] | None = None,
    notes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """SIGTERM lean collectors when MemAvailable < warn. Protect AT/DK by default until last."""
    warn = warn_gib() if warn is None else warn
    protect = protect if protect is not None else frozenset({"at", "dk"})
    g = mem_available_gib()
    out: list[dict[str, Any]] = []
    if g < 0 or g >= warn:
        return out
    # First pass: non-protected; second pass: protected if still under warn.
    for pass_protected in (False, True):
        for name, pats in DEFAULT_SHED_ORDER:
            if (name in protect) != pass_protected:
                continue
            pids = discover_pids(*pats)
            for pid in pids:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    continue
                except PermissionError:
                    continue
                try:
                    os.kill(pid, signal.SIGTERM)
                    note = {
                        "stage": stage,
                        "name": name,
                        "pid": pid,
                        "mem_before": round(g, 2),
                        "protected_pass": pass_protected,
                    }
                    out.append(note)
                    if notes is not None:
                        notes.append(note)
                    msg = f"SIGTERM collector {name} pid={pid} mem={g:.2f}G stage={stage}"
                    if log:
                        log(msg)
                    else:
                        print(msg, flush=True)
                except ProcessLookupError:
                    pass
                except Exception as exc:
                    msg = f"SIGTERM failed {name} pid={pid}: {exc}"
                    if log:
                        log(msg)
                    else:
                        print(msg, flush=True)
            g = mem_available_gib()
            if g >= warn:
                return out
    return out


def checkpoint(
    stage: str,
    *,
    row: int | None = None,
    every_n: int | None = None,
    shed: bool = True,
    abort: bool = True,
    log: Callable[[str], None] | None = None,
    notes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Periodic mem log + optional shed + hard abort.

    Call every N rows with ``row`` set; always logs when row is None.
    """
    every = every_n if every_n is not None else log_every()
    if row is not None and row != 0 and row % every != 0:
        # Still enforce hard abort cheaply on every call.
        rss = rss_gib()
        avail = mem_available_gib()
        if abort and rss >= abort_rss_gib():
            raise MemAbort(f"RSS_ABORT stage={stage} rss={rss:.2f}G > {abort_rss_gib()}G")
        if abort and 0 <= avail < abort_avail_gib():
            if shed:
                shed_collectors(stage, log=log, notes=notes)
                avail = mem_available_gib()
            if 0 <= avail < abort_avail_gib():
                raise MemAbort(
                    f"MEM_ABORT stage={stage} MemAvailable={avail:.2f}G < {abort_avail_gib()}G"
                )
        return snapshot(stage)

    snap = log_mem(stage if row is None else f"{stage}@{row}", log=log)
    if shed and 0 <= snap["mem_avail_gib"] < warn_gib():
        shed_collectors(stage, log=log, notes=notes)
        snap = log_mem(f"{stage}_after_shed", log=log)
        gc.collect()
    if abort:
        if snap["rss_gib"] >= abort_rss_gib():
            raise MemAbort(
                f"RSS_ABORT stage={stage} rss={snap['rss_gib']:.2f}G > {abort_rss_gib()}G"
            )
        if 0 <= snap["mem_avail_gib"] < abort_avail_gib():
            raise MemAbort(
                f"MEM_ABORT stage={stage} MemAvailable={snap['mem_avail_gib']:.2f}G "
                f"< {abort_avail_gib()}G"
            )
    return snap
