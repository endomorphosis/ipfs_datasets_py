#!/usr/bin/env python3
"""PROPOSAL (not scheduled): gzip the archived source files in processed/ in place.

processed/<bot>/<CC>/*.jsonl is write-only for run_loop.py: files are renamed there after a successful upload and
never read again (the ledger keys on staging path + sha256, and merges use out/ parquet). The JSONL holds raw HTML
and compresses ~6.7x with gzip -6 (measured on a 300-file random sample: 119 MB -> 17.7 MB).

Safety:
  * default is --dry-run (report only); pass --apply to compress
  * never touches staging/, out/ or anything outside processed/
  * does not take or probe run_loop's lock: only files whose ctime (set by run_loop's rename) is older than
    --min-age-hours are touched, so a running run_loop never sees a file change under it
  * per file: write <name>.gz.tmp -> fsync -> verify by decompressing and comparing sha256 -> rename to
    <name>.gz -> unlink the original. A crash leaves at most a .gz.tmp, which the next run removes.
  * mtime/atime of the original are copied to the .gz
Readers: run_loop.py never reads processed/, but some bot tools glob processed/**/*.jsonl and would silently skip
.jsonl.gz: scrapers/asia_latam/jp/reemit_d1law.py (JP), scrapers/asia_latam/arch/pe_pdf.py (PE),
scrapers/asia_latam/arch/policy_reemit.py (asia_latam), scrapers/web/robots_audit.py (web/DE; reads *.jsonl.gz since 2026-10-11, so web/ is enabled). asia_latam/ stays
excluded by default (--bots eu national web id_jdih states ukie; the last three added 2026-10-17, no
processed/ readers in their code) until its owners read *.jsonl.gz too. Compression only; pruning of
web/ stays disabled (state/prune_config.json).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import argparse
import gzip
import hashlib
import os
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law")) / "processed"


def sha(path, opener=open):
    h = hashlib.sha256()
    with opener(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="really compress (default: dry run)")
    ap.add_argument("--min-age-hours", type=float, default=2.0)
    ap.add_argument("--min-free-gb", type=float, default=2.0, help="stop if free space drops below this")
    ap.add_argument("--bots", nargs="+", default=["eu", "national", "web", "id_jdih", "states", "ukie"],
                    help="bot dirs under processed/ to compress (default: eu national web id_jdih states ukie; see Readers above)")
    ap.add_argument("--limit", type=int, default=0, help="max files this run (0 = all)")
    a = ap.parse_args()
    cutoff = time.time() - a.min_age_hours * 3600
    n = raw = done = saved = 0
    for dp, dn, fn in (w for b in a.bots for w in os.walk(ROOT / b)):
        for f in fn:
            p = Path(dp) / f
            if f.endswith(".gz.tmp"):
                if a.apply:
                    p.unlink(missing_ok=True)
                continue
            if not f.endswith(".jsonl"):
                continue
            st = p.stat()
            if st.st_ctime > cutoff:
                continue
            n += 1
            raw += st.st_size
            if not a.apply:
                continue
            if a.limit and done >= a.limit:
                continue
            free = os.statvfs(ROOT)
            if free.f_bavail * free.f_frsize < a.min_free_gb * 1e9:
                print("free space below --min-free-gb; stopping", file=sys.stderr)
                break
            gz, tmp = p.with_name(f + ".gz"), p.with_name(f + ".gz.tmp")
            with open(p, "rb") as src, gzip.open(tmp, "wb", compresslevel=6) as dst:
                for b in iter(lambda: src.read(1 << 20), b""):
                    dst.write(b)
            with open(tmp, "rb") as fh:
                os.fsync(fh.fileno())
            if sha(tmp, gzip.open) != sha(p):
                tmp.unlink()
                print("verify failed, kept original:", p, file=sys.stderr)
                continue
            os.utime(tmp, (st.st_atime, st.st_mtime))
            os.replace(tmp, gz)
            saved += st.st_size - gz.stat().st_size
            p.unlink()
            done += 1
    print(f"{'APPLIED' if a.apply else 'DRY RUN'}: eligible files {n}, {raw/1e9:.2f} GB raw; "
          f"compressed {done}, saved {saved/1e9:.2f} GB; est. saving at 6.7x: {raw*(1-1/6.7)/1e9:.1f} GB")


if __name__ == "__main__":
    main()
