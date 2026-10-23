"""Read staged/processed JSONL transparently whether plain (.jsonl) or gzip-compressed (.jsonl.gz).

processed/<bot>/<CC>/ files may be gzipped in place (pipeline/tools/compress_processed.py), and run_loop.py may rename
a moved file to <name>.jsonl.<ts> on collision. Use these helpers in every lane script that reads staged/processed docs.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import glob as _glob
import gzip
import os

PROCESSED = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/processed/asia_latam")
STAGING = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam")


def open_text(path, encoding="utf-8"):
    """Text-mode reader for .jsonl or .jsonl.gz (by suffix, falling back to the gzip magic bytes)."""
    path = str(path)
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding=encoding)
    with open(path, "rb") as fh:
        magic = fh.read(2)
    if magic == b"\x1f\x8b":
        return gzip.open(path, "rt", encoding=encoding)
    return open(path, encoding=encoding)


def is_jsonl(path):
    return str(path).endswith((".jsonl", ".jsonl.gz"))


def glob_jsonl(pattern):
    """glob for a '*.jsonl' style pattern that also returns the '.jsonl.gz' twins; if both a plain and a gz version
    of one file exist (mid-compression), only the plain one is returned. Sorted by name without .gz."""
    pattern = str(pattern)
    pats = [pattern] + ([pattern + ".gz"] if pattern.endswith(".jsonl") else [])
    found = {}
    for p in pats:
        for f in _glob.glob(p):
            base = f[:-3] if f.endswith(".gz") else f
            if base not in found or not f.endswith(".gz"):
                found[base] = f
    return [found[k] for k in sorted(found)]


def iter_jsonl_lines(path):
    with open_text(path) as fh:
        for line in fh:
            if line.strip():
                yield line


def locate(path):
    """Find a staged file that may since have been moved to processed/ and/or gzipped. Returns a path or None."""
    path = str(path)
    cands = [path, path + ".gz"]
    if path.startswith(STAGING + "/"):
        p2 = PROCESSED + path[len(STAGING):]
        cands += [p2, p2 + ".gz"]
    for c in cands:
        if os.path.exists(c):
            return c
    return None
