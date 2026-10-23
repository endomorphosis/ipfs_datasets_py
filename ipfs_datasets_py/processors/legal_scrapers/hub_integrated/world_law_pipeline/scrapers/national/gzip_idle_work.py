#!/usr/bin/env python3
"""Gzip-after-close sweeper for national-lane work dirs (disk pressure, 2026-10-11).

Compresses large, idle intermediates in place (<file> -> <file>.gz, zcat/gzip -dc readable, mtime kept) under
  staging/national/_work/<CC>/...            (collector raw dumps, catalogs, csv/xml/txt)
  staging/national/_archive_work/<TARGET>/   (candidates.jsonl -> candidates.jsonl.gz; run_archive.py reads both)
Never touches staged finals (staging/national/<CC>/*.jsonl: the uploader only reads .jsonl/.parquet, SCHEMA.md §2),
_archive_provenance/, _logs/, or anything outside these two roots.

Skipped:
  * files open by any process (/proc/*/fd), files modified within --min-idle-min, files < --min-mb
  * already-compressed / binary-archive suffixes (.gz .zip .bz2 .xz .zst .7z .pack .parquet .pdf ...), *.tmp, locks
  * emitter input  _work/<CC>/**/instruments/*.json  (emit_staged.py globs *.json), _emitted_ids.txt, done.tsv,
    stats.json, index.jsonl, failures.jsonl, _archive_work/_hf_ids/, and whole git working trees
  * active CCs/targets: cwd of a running process inside _work/<CC>, CCs named in a running queue_full.py
    (CC:collect_xx.py), run_archive.py TARGET args, TARGETS of queue_restart.sh, plus --skip
Note: some collectors resume from plain _work/<CC>/raw/catalog.jsonl; after gzipping, a re-run of that collector
re-fetches its catalog (or `gzip -d` it first). Active/queued CCs are skipped for exactly this reason.

Usage: gzip_idle_work.py [--dry-run] [--min-mb 10] [--min-idle-min 30] [--level 9] [--skip CC,TARGET,...]
One file at a time, nice 19 + ionice idle, streaming gzip (constant memory).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, os, re, subprocess, sys, time
from datetime import datetime
from pathlib import Path

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national"))
ROOTS = [STAGE / "_work", STAGE / "_archive_work"]
LOG = STAGE / "_logs" / "gzip_idle_work.log"
SKIP_SUFFIX = {".gz", ".tgz", ".zip", ".bz2", ".xz", ".zst", ".7z", ".rar", ".pack", ".idx", ".parquet", ".pdf",
               ".jpg", ".jpeg", ".png", ".gif", ".webp", ".docx", ".xlsx", ".odt", ".tmp", ".lock", ".done"}
SKIP_NAMES = {"_emitted_ids.txt", "done.tsv", "stats.json", ".runner.lock", "_job.lock", "index.jsonl",
              "failures.jsonl", "SUMMARY.md"}  # collector/runner resume + append-mode state
SKIP_DIRS = {".git", "_hf_ids"}  # _hf_ids/*.jsonl is read as plain text by run_archive.py / emit_repo_archive.py


def log(msg, dry):
    line = f"{datetime.now():%F %T} {'DRY ' if dry else ''}{msg}"
    print(line, flush=True)
    if not dry:
        with LOG.open("a") as f:
            f.write(line + "\n")


def open_files():
    s = set()
    for fd in Path("/proc").glob("[0-9]*/fd/*"):
        try:
            s.add(os.readlink(fd))
        except OSError:
            pass
    return s


def active_units():
    act = set()
    qr = Path(__file__).resolve().parent / "archive" / "queue_restart.sh"
    for pd in Path("/proc").glob("[0-9]*"):
        try:
            argv = (pd / "cmdline").read_bytes().split(b"\0")
            argv = [a.decode("utf-8", "replace") for a in argv if a]
            cwd = os.readlink(pd / "cwd")
        except OSError:
            continue
        m = re.match(re.escape(str(STAGE / "_work")) + r"/([^/]+)", cwd)
        if m:
            act.add(m[1])
        if any(a.endswith("queue_full.py") for a in argv):
            act.update(a.split(":")[0] for a in argv if re.match(r"^[A-Z]{2}:", a))
        if any(a.endswith("run_archive.py") for a in argv):
            i = next(i for i, a in enumerate(argv) if a.endswith("run_archive.py"))
            if i + 1 < len(argv):
                act.add(argv[i + 1])
        if any(a.endswith("queue_restart.sh") for a in argv):
            try:
                env = dict(l.split("=", 1) for l in (pd / "environ").read_bytes().decode("utf-8", "replace").split("\0") if "=" in l)
            except OSError:
                env = {}
            t = env.get("TARGETS")
            if not t and qr.exists():
                m2 = re.search(r'TARGETS=\$\{TARGETS:-"([^"]*)"\}', qr.read_text())
                t = m2[1] if m2 else ""
            act.update((t or "").split())
    return act


def candidates(min_bytes, min_idle_s, skip):
    now = time.time()
    for root in ROOTS:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            rel = Path(dirpath).relative_to(root).parts
            if ".git" in dirnames or (rel and (rel[0] in skip or rel[-1] in SKIP_DIRS)):
                # git working trees (e.g. CA laws-lois-xml) are left intact so `git pull` keeps working
                dirnames[:] = []
                continue
            for fn in filenames:
                p = Path(dirpath) / fn
                if fn in SKIP_NAMES or p.suffix.lower() in SKIP_SUFFIX or fn.startswith("."):
                    continue
                if p.parent.name == "instruments" and p.suffix == ".json":
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                if st.st_size < min_bytes or now - st.st_mtime < min_idle_s or not p.is_file() or p.is_symlink():
                    continue
                yield p, st


def gzip_one(p, st, level, dry):
    if dry:
        log(f"would gzip {p} ({st.st_size} B)", dry)
        return 0
    gz, tmp = p.with_name(p.name + ".gz"), p.with_name("." + p.name + ".gz.tmp")
    if gz.exists():
        log(f"SKIP {p}: {gz.name} already exists", dry)
        return 0
    try:
        with tmp.open("wb") as out:
            r = subprocess.run(["ionice", "-c3", "nice", "-n", "19", "gzip", f"-{level}", "-c", "--", str(p)], stdout=out)
        if r.returncode != 0 or subprocess.run(["gzip", "-t", str(tmp)]).returncode != 0:
            raise RuntimeError("gzip failed")
        st2 = p.stat()
        if (st2.st_mtime, st2.st_size) != (st.st_mtime, st.st_size) or str(p) in open_files():
            raise RuntimeError("file changed or opened during compression")
        os.utime(tmp, (st.st_atime, st.st_mtime))
        os.replace(tmp, gz)
        p.unlink()
    except Exception as e:
        tmp.unlink(missing_ok=True)
        log(f"SKIP {p}: {e}", dry)
        return 0
    saved = st.st_size - gz.stat().st_size
    log(f"GZIP {p} {st.st_size} -> {gz.stat().st_size} saved={saved}", dry)
    return saved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-mb", type=float, default=10)
    ap.add_argument("--min-idle-min", type=float, default=30)
    ap.add_argument("--level", type=int, default=9)
    ap.add_argument("--skip", default="", help="comma-separated extra CCs / archive targets to leave alone")
    a = ap.parse_args()
    try:
        os.nice(19)
    except OSError:
        pass
    skip = active_units() | {s for s in a.skip.split(",") if s}
    log(f"start; skipping active/queued units: {' '.join(sorted(skip))}", a.dry_run)
    busy = open_files()
    total = n = 0
    for p, st in list(candidates(int(a.min_mb * 1024 * 1024), a.min_idle_min * 60, skip)):
        if str(p) in busy:
            log(f"SKIP {p}: open by a process", a.dry_run)
            continue
        s = gzip_one(p, st, a.level, a.dry_run)
        total += s; n += bool(s)
    log(f"done; gzipped {n} files, saved {total} B ({total / 1024**2:.1f} MiB)", a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
