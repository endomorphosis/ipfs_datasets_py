"""Streaming adapter for DILA open-data case-law dumps (CASS, CAPP, JADE, CONSTIT, INCA).

Promoted from ``justicedao/world_law_scrapers`` ``caselaw/fr_dila/adapter.py`` at
``e8169767dcb69aff9e09e27f13e7450a031d95dc``. This module does not replace
``collect_legi`` and does not change the France statute query route.

Streams .tar.gz over HTTPS (verify on), parses XML members on the fly; never writes archives.
Usage: python collect_fr_dila.py --fond CASS --archive <name> --out DIR [--limit N]
       python collect_fr_dila.py --full --out DIR --state state.json   (resumable, guarded)
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import argparse, datetime as dt, json, os, re, shutil, sys, tarfile, time
import requests
from lxml import etree

BASE = "https://echanges.dila.gouv.fr/OPENDATA/"
UA = "JusticeDAO-caselaw-collector/0.1 (open-data research; ipfs_datasets_py)"
FONDS = {"CASS": "fr_cass", "CAPP": "fr_capp", "JADE": "fr_jade", "CONSTIT": "fr_constit", "INCA": "fr_inca"}
PAUSE = 2.0
S = requests.Session(); S.headers["User-Agent"] = UA

def guard(min_mem_gb=4.2, min_disk_gb=10.5, path=None):
    if path is None:
        path = str(_CORPORA)
    mem = int(re.search(r"MemAvailable:\s+(\d+)", open("/proc/meminfo").read()).group(1)) / 1024**2
    disk = shutil.disk_usage(path).free / 1024**3
    return mem >= min_mem_gb and disk >= min_disk_gb, mem, disk

def list_archives(fond):
    time.sleep(PAUSE)
    r = S.get(f"{BASE}{fond}/", timeout=60, verify=True); r.raise_for_status()
    return sorted(set(re.findall(r'href="([^"]+\.tar\.gz)"', r.text)))

def _t(root, *paths):
    for p in paths:
        v = root.findtext(p)
        if v: return v.strip()
    return None

def parse(xml_bytes, fond, url, archive):
    root = etree.fromstring(xml_bytes)
    meta = ".//META_JURI"
    text_el = root.find(".//CONTENU")
    text = " ".join(text_el.itertext()).strip() if text_el is not None else None
    return {
        "ecli": _t(root, ".//ECLI"),
        "jurisdiction": "FR",
        "court": _t(root, f"{meta}/JURIDICTION"),
        "chamber": _t(root, ".//FORMATION"),
        "date": _t(root, f"{meta}/DATE_DEC"),
        "number": _t(root, f"{meta}/NUMERO", ".//NUMEROS_AFFAIRES/NUMERO_AFFAIRE"),
        "title": _t(root, f"{meta}/TITRE"),
        "text": text,
        "source_url": url, "archive_name": archive, "is_archive": False,
        "licence": "Licence Ouverte 2.0",
        "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "court_id": None, "dila_id": _t(root, ".//META_COMMUN/ID"), "config": FONDS[fond],
    }

class ResumableRaw:
    """File-like over an HTTP body; on IncompleteRead/reset reopens with Range from the current
    byte offset (server sends Accept-Ranges: bytes), up to `retries` times with backoff."""
    def __init__(self, url, retries=5):
        self.url, self.retries, self.pos, self.r = url, retries, 0, None
        self._open()
    def _open(self):
        h = {"Range": f"bytes={self.pos}-"} if self.pos else {}
        time.sleep(PAUSE)
        self.r = S.get(self.url, stream=True, timeout=120, verify=True, headers=h)
        self.r.raise_for_status()
        if self.pos and self.r.status_code != 206:
            self.r.close(); raise IOError(f"server ignored Range at {self.pos}")
        self.r.raw.decode_content = False
    def read(self, n=-1):
        for attempt in range(self.retries + 1):
            try:
                b = self.r.raw.read(n); self.pos += len(b); return b
            except Exception as e:
                if attempt >= self.retries: raise
                wait = min(300, 10 * 2 ** attempt)
                print(f"stream error at byte {self.pos}: {type(e).__name__}: {str(e)[:160]}; retry {attempt+1}/{self.retries} in {wait}s (Range)", flush=True)
                try: self.r.close()
                except Exception: pass
                time.sleep(wait)
                try: self._open()
                except Exception as e2: print(f"reopen failed: {e2}", flush=True)
    def close(self):
        try: self.r.close()
        except Exception: pass

def stream(fond, archive):
    url = f"{BASE}{fond}/{archive}"
    raw = ResumableRaw(url)
    try:
        with tarfile.open(fileobj=raw, mode="r|gz") as tf:
            for m in tf:
                if m.isfile() and m.name.endswith(".xml"):
                    try: yield parse(tf.extractfile(m).read(), fond, url, archive)
                    except etree.XMLSyntaxError: continue
    finally: raw.close()

def write_parquet(rows, path):
    import pyarrow as pa, pyarrow.parquet as pq
    pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")

def existing_ids(base):
    import glob, pyarrow.parquet as pq
    ids = set()
    for f in glob.glob(f"{base}.*parquet"):
        ids.update(x for x in pq.read_table(f, columns=["dila_id"]).column(0).to_pylist() if x)
    return ids

def save_state(st, path):
    tmp = path + ".tmp"; json.dump(st, open(tmp, "w")); os.replace(tmp, path)

def full(out, state_path, check_every=180, batch=2000):
    st = json.load(open(state_path)) if os.path.exists(state_path) else {"done": []}
    st.setdefault("failed", {}); run = dt.datetime.now().strftime("r%Y%m%d%H%M")
    print(f"run {run} start; done={len(st['done'])} failed={len(st['failed'])}", flush=True)
    last = 0
    for fond, cfg in FONDS.items():
        os.makedirs(f"{out}/{cfg}", exist_ok=True)
        for a in list_archives(fond):
            key = f"{fond}/{a}"
            if key in st["done"]: continue
            rows, part, total, skipped = [], 0, 0, 0
            base = f"{out}/{cfg}/{a.replace('.tar.gz','')}"
            seen = existing_ids(base)  # partial output from an interrupted run: skip by dila_id
            if seen: print(f"{key}: {len(seen)} ids already staged; new parts tagged .{run}.", flush=True)
            pfx = f"{base}.{run}.part"  # run id in name: never overwrites earlier parts
            try:
                for rec in stream(fond, a):
                    if rec["dila_id"] and rec["dila_id"] in seen: skipped += 1; continue
                    rows.append(rec)
                    if len(rows) >= batch:
                        write_parquet(rows, f"{pfx}{part:05d}.parquet"); total += len(rows); part += 1; rows = []
                    if time.time() - last > check_every:
                        ok, mem, disk = guard(); last = time.time()
                        print(f"guard mem={mem:.1f}G disk={disk:.1f}G", flush=True)
                        if not ok:
                            if rows: write_parquet(rows, f"{pfx}{part:05d}.parquet")
                            print("GUARD STOP", flush=True); sys.exit(3)
                if rows: write_parquet(rows, f"{pfx}{part:05d}.parquet"); total += len(rows)
            except Exception as e:
                if rows: write_parquet(rows, f"{pfx}{part:05d}.parquet"); total += len(rows)
                st["failed"][key] = {"error": f"{type(e).__name__}: {str(e)[:300]}", "run": run, "rows_written": total}
                save_state(st, state_path)
                print(f"FAILED {key} rows={total}: {type(e).__name__}: {str(e)[:200]}; continuing", flush=True)
                continue
            st["done"].append(key); st["failed"].pop(key, None); save_state(st, state_path)
            print(f"done {key} rows={total} skipped_existing={skipped} parts={part + (1 if rows else 0)}", flush=True)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fond"); ap.add_argument("--archive"); ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=20); ap.add_argument("--full", action="store_true")
    ap.add_argument("--state")
    a = ap.parse_args()
    ok, mem, disk = guard()
    if not ok: sys.exit(f"ABORT: MemAvailable={mem:.2f}G disk={disk:.1f}G below thresholds")
    if a.full: full(a.out, a.state)
    else:
        rows = list(stream(a.fond, a.archive))
        write_parquet(rows, f"{a.out}/sample.parquet")
        with open(f"{a.out}/preview.jsonl", "w") as f:
            for r in rows[:a.limit]: f.write(json.dumps({**r, "text": (r["text"] or "")[:500]}, ensure_ascii=False) + "\n")
        print(f"records={len(rows)}")
