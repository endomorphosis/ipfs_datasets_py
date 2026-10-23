#!/usr/bin/env python3
"""gzip our processed files in place: /workspace/world_law/processed/asia_latam/<CC>/*.jsonl -> *.jsonl.gz.

Safe because run_loop.py never re-reads processed/ (it only moves files there; the ledger keys on staging path + sha256,
merges use out/ parquet). Lane readers use common/jsonl_io.py and read .jsonl.gz transparently.
Per file: count lines -> write <name>.gz.tmp (gzip -6) -> fsync -> verify by decompressing (sha256 AND line count equal)
-> copy atime/mtime -> os.replace to <name>.gz -> fsync dir -> unlink original. Files whose ctime is < --min-age-hours old
are skipped (a run_loop move may be in flight). Crash-safe: a leftover .gz.tmp is removed on the next run. Resumable.
Log: staging/asia_latam/_logs/gzip_processed.log; per-file ledger: _logs/gzip_processed.tsv."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, gzip, hashlib, os, sys, time
from pathlib import Path

ROOT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/processed/asia_latam"))
LOG = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam/_logs"))


def sha_lines(fh):
    h = hashlib.sha256(); n = 0
    for b in iter(lambda: fh.read(1 << 20), b""):
        h.update(b); n += b.count(b"\n")
    return h.hexdigest(), n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--min-age-hours", type=float, default=1.0)
    ap.add_argument("--min-free-gb", type=float, default=3.0)
    ap.add_argument("--cc", nargs="*", default=None)
    ap.add_argument("--loop-minutes", type=float, default=0, help="repeat every N minutes (supervisor job); 0 = one pass")
    a = ap.parse_args()
    while True:
        one_pass(a)
        if not a.loop_minutes:
            return
        time.sleep(a.loop_minutes * 60)


def one_pass(a):
    cutoff = time.time() - a.min_age_hours * 3600
    led = open(LOG / "gzip_processed.tsv", "a")
    n = raw = gzs = 0; bad = 0; vanished = 0; t0 = time.time()
    ccs = a.cc or sorted(p.name for p in ROOT.iterdir() if p.is_dir())
    for cc in ccs:
        d = ROOT / cc
        try:
            entries = sorted(d.iterdir())
        except FileNotFoundError:
            continue
        for p in entries:
          try:
              f = p.name
              if f.endswith(".gz.tmp"):
                  if a.apply:
                      p.unlink(missing_ok=True)
                  continue
              if f.endswith(".gz") or ".jsonl" not in f or not p.is_file():
                  continue
              st = p.stat()
              if st.st_ctime > cutoff:
                  continue
              if not a.apply:
                  n += 1; raw += st.st_size; continue
              fs = os.statvfs(ROOT)
              if fs.f_bavail * fs.f_frsize < a.min_free_gb * 1e9:
                  print("free space below --min-free-gb; stopping", flush=True); break
              gz, tmp = p.with_name(f + ".gz"), p.with_name(f + ".gz.tmp")
              with open(p, "rb") as fh:
                  h0, n0 = sha_lines(fh)
              with open(p, "rb") as src, open(tmp, "wb") as raw_out:
                  with gzip.GzipFile(filename=f, mode="wb", compresslevel=6, fileobj=raw_out, mtime=int(st.st_mtime)) as dst:
                      for b in iter(lambda: src.read(1 << 20), b""):
                          dst.write(b)
                  raw_out.flush(); os.fsync(raw_out.fileno())
              with gzip.open(tmp, "rb") as fh:
                  h1, n1 = sha_lines(fh)
              if (h0, n0) != (h1, n1):
                  tmp.unlink(); bad += 1
                  print(f"VERIFY FAILED kept original: {p} lines {n0}/{n1}", flush=True); continue
              if not p.exists():   # pruned while we compressed: don't resurrect it as .gz
                  tmp.unlink(missing_ok=True); vanished += 1; continue
              os.utime(tmp, (st.st_atime, st.st_mtime))
              os.replace(tmp, gz)
              dfd = os.open(d, os.O_RDONLY); os.fsync(dfd); os.close(dfd)
              p.unlink(missing_ok=True)
              n += 1; raw += st.st_size; gzsz = gz.stat().st_size; gzs += gzsz
              led.write(f"{cc}/{f}\t{n0}\t{st.st_size}\t{gzsz}\t{h0}\n")
              if n % 500 == 0:
                  led.flush()
                  print(f"{time.strftime('%H:%M:%S')} {cc} files={n} raw={raw/1e9:.2f}GB gz={gzs/1e9:.2f}GB saved={(raw-gzs)/1e9:.2f}GB", flush=True)
          except FileNotFoundError:   # Normalizer pruned it mid-scan (only Hub-committed, >=2h old files)
            vanished += 1
            for t in (p.with_name(p.name + ".gz.tmp"),):
                t.unlink(missing_ok=True)
            continue
    led.close()
    print(f"{'APPLIED' if a.apply else 'DRY RUN'} files={n} raw={raw/1e9:.2f}GB gz={gzs/1e9:.2f}GB saved={(raw-gzs)/1e9:.2f}GB "
          f"verify_failed={bad} vanished={vanished} secs={time.time()-t0:.0f}", flush=True)


if __name__ == "__main__":
    main()
