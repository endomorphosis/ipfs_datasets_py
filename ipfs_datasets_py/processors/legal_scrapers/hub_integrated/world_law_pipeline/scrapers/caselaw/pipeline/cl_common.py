"""Shared Phase A pipeline pieces: gates, polite fetcher (robots-gated), shard writer, text extraction."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import datetime, glob, hashlib, json, os, re, shutil, sys, time, logging
if _ipfs_os.environ.get("IPFS_DATASETS_PY"):  # optional checkout override; normally the installed package is used
    sys.path.insert(0, _ipfs_os.environ["IPFS_DATASETS_PY"])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.WARNING)
import requests
import pyarrow.parquet as pq
try:   # r7: the robots gate lives in ipfs_datasets_py (needs anyio). Guarded so plain python3 can import this module (fixtures, validation); only fetching needs the venv.
    from ipfs_datasets_py.processors.legal_scrapers.robots_gate import get_default_gate, RobotsDenied
    from ipfs_datasets_py.processors.legal_scrapers.http_user_agents import DEFAULT_USER_AGENT
    ROBOTS_GATE_AVAILABLE = True
except ImportError:
    ROBOTS_GATE_AVAILABLE = False
    DEFAULT_USER_AGENT = "caselaw-pipeline (robots gate unavailable)"
    class RobotsDenied(Exception): pass
    def get_default_gate():
        raise RuntimeError(("robots gate unavailable (anyio / ipfs_datasets_py not importable): fetching needs " + str(_LEGAL_WS) + "/ipfs_datasets_fresh_venv/bin/python"))
import caselaw_schema as cs
from court_matcher import CourtMatcher
import r6_rules

OUT = (str(_LEGAL_WS) + "/case_law/out")
DISK_FLOOR = 16 * 2**30
MEM_FLOOR = int(4.5 * 2**30)


class StopJob(Exception):
    pass


def disk_free() -> int:
    return shutil.disk_usage((str(_LEGAL_WS))).free


def mem_avail() -> int:
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable:"):
            return int(ln.split()[1]) * 1024
    return 0


def now_la() -> str:
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def preflight(tag: str = "", max_wait_s: int = 3600) -> dict:
    """Disk < 16G -> StopJob. MemAvailable < 4.5Gi -> PAUSE: wait and recheck every 30 s (up to max_wait_s), then continue; StopJob only if it never recovers."""
    d = disk_free()
    if d < DISK_FLOOR:
        raise StopJob(f"STOP {tag}: free disk {d/2**30:.2f}G < 16G floor")
    waited = 0
    while mem_avail() < MEM_FLOOR:
        if waited == 0:
            print(now_la(), f"PAUSE {tag}: MemAvailable {mem_avail()/2**30:.2f}Gi < 4.5Gi, waiting", flush=True)
        if waited >= max_wait_s:
            raise StopJob(f"STOP {tag}: MemAvailable {mem_avail()/2**30:.2f}Gi < 4.5Gi for {waited}s")
        time.sleep(30); waited += 30
        if disk_free() < DISK_FLOOR:
            raise StopJob(f"STOP {tag}: free disk < 16G while waiting")
    if waited: print(now_la(), f"RESUME {tag} after {waited}s", flush=True)
    d, m = disk_free(), mem_avail()
    return {"disk_free_gib": round(d / 2**30, 2), "mem_avail_gib": round(m / 2**30, 2)}


class Fetcher:
    def __init__(self, min_delay: float = 1.0):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = DEFAULT_USER_AGENT
        self.gate = get_default_gate()
        self.gate.min_delay_seconds = max(getattr(self.gate, "min_delay_seconds", 1.0), min_delay)
        self.n = 0
        self.blocked = 0
        self.errors = 0

    def get(self, url, params=None, headers=None, timeout=(10, 90), tries=3, stream_max=None):
        """Robots-gated GET with TLS verification (always on). Returns Response or None on 404/410.
        Stops (StopJob) on repeated 403/429 (never bypassed)."""
        last = None
        for i in range(tries):
            self.gate.enforce(url)  # raises RobotsDenied / waits crawl-delay
            self.n += 1
            try:
                r = self.s.get(url, params=params, headers=headers, timeout=timeout, allow_redirects=True)
            except requests.RequestException as e:
                last = repr(e); self.errors += 1
                time.sleep(min(60, 5 * 2 ** i)); continue
            if r.status_code in (404, 410):
                return None
            if r.status_code in (403, 429):
                self.blocked += 1
                if self.blocked >= 3:
                    raise StopJob(f"STOP: {r.status_code} x3 from {url[:80]} (not bypassing)")
                time.sleep(min(300, int(r.headers.get("Retry-After", "30") or 30))); last = f"HTTP {r.status_code}"; continue
            if r.status_code >= 500:
                last = f"HTTP {r.status_code}"; self.errors += 1
                time.sleep(min(60, 5 * 2 ** i)); continue
            r.raise_for_status()
            self.blocked = 0
            return r
        raise requests.RequestException(f"giving up {url[:100]}: {last}")


def html_to_text(raw: bytes | str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw, "html.parser")
    for t in soup(["script", "style", "head"]):
        t.decompose()
    txt = soup.get_text("\n")
    txt = re.sub(r"[ \t\r\f\v\u00a0]+", " ", txt)
    txt = re.sub(r"\n\s*\n+", "\n\n", txt)
    return txt.strip()


class SourceOut:
    """Shard writer for one source: out/<source>/<record_type>/part-NNNN.parquet + manifest.jsonl."""

    def __init__(self, source: str, phase="phaseA", max_rows=2000, max_text_bytes=40_000_000, dry=False):
        self.source, self.phase = source, phase
        self.dir = f"{OUT}/{source}"
        self.dry = dry; self.rejected_log = []   # r8: dry=True never touches the disk (add_pair rejections are kept in self.rejected_log); flush() is not used in dry mode
        if not dry: os.makedirs(self.dir, exist_ok=True)
        self.max_rows, self.max_text_bytes = max_rows, max_text_bytes
        self.buf = {k: [] for k in cs.RECORD_TYPES}
        self.text_bytes = 0
        self.rows = {k: 0 for k in cs.RECORD_TYPES}
        self.bytes = {k: 0 for k in cs.RECORD_TYPES}
        self.shards = {k: 0 for k in cs.RECORD_TYPES}
        self.manifest = f"{self.dir}/manifest.jsonl"
        self.seen = set()
        for p in sorted(glob.glob(f"{self.dir}/decision/part-*.parquet")):
            self.seen.update(pq.read_table(p, columns=["source_record_id"]).column(0).to_pylist())
        self.next_idx = {k: len(glob.glob(f"{self.dir}/{k}/part-*.parquet")) for k in cs.RECORD_TYPES}
        self.ids_seen = set()
        for k in cs.RECORD_TYPES:
            for p in glob.glob(f"{self.dir}/{k}/part-*.parquet"):
                self.ids_seen.update(pq.read_table(p, columns=["id"]).column(0).to_pylist())

    def add_pair(self, dec: dict, op: dict) -> bool:
        """Validate a decision+opinion pair row-wise BEFORE buffering; a bad pair is rejected (logged to rejected_rows.jsonl), never poisons a whole shard flush."""
        import copy
        try:
            r6_rules.apply_r8(dec, op)   # r8 = r7 + date rules (zero-date flag, ARGVP publication year, AR heading date, anchored BGE date); r7 (TG nav strip, CH dates, body_type, not_decision) on top of r6: clean labels, body_type, e-mail redaction (+rehash, +personal_contact flag)
            for kind, r in (("decision", dec), ("opinion", op)):
                probs = cs.validate_caselaw_table(cs.cast_rows([copy.deepcopy(r)], kind), kind)
                if probs: raise ValueError(f"{kind}: " + "; ".join(probs[:4]))
            pend = lambda r: ((r6_rules._meta(r).get("terms") or {}).get("pending_legal_review"))
            if dec.get("restricted_ai_training") != op.get("restricted_ai_training") or dec.get("licence_class") != op.get("licence_class") or pend(dec) != pend(op):
                raise ValueError("decision/opinion restricted_ai_training/licence_class/terms.pending_legal_review differ")
        except Exception as e:
            self.rejected = getattr(self, "rejected", 0) + 1
            rec = {"time_la": now_la(), "source_record_id": dec.get("source_record_id"), "reason": str(e)[:300]}
            if self.dry: self.rejected_log.append(rec)
            else:
                with open(f"{self.dir}/rejected_rows.jsonl", "a") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            return False
        self.add("decision", dec); self.add("opinion", op)
        return True

    def add(self, kind: str, row: dict):
        self.buf[kind].append(row)
        if kind == "opinion" and row.get("text"):
            self.text_bytes += len(row["text"].encode("utf-8"))

    def full(self) -> bool:
        return len(self.buf["decision"]) >= self.max_rows or self.text_bytes >= self.max_text_bytes

    def flush(self) -> list[dict]:
        done = []
        if not any(self.buf.values()):
            return done
        gate = preflight(f"{self.source} shard")
        for kind in cs.RECORD_TYPES:
            rows = self.buf[kind]
            if not rows:
                continue
            for r in rows:  # fix1 duplicate rule
                if r["id"] in self.ids_seen:
                    r.setdefault("metadata_json", {})
                    r["metadata_json"]["id_original"] = r["id"]; r["metadata_json"]["id_rule"] = cs.ID_RULE
                    r["id"] = cs.dedupe_id(r["id"], self.phase)
                self.ids_seen.add(r["id"])
            t = cs.cast_rows(rows, kind)
            os.makedirs(f"{self.dir}/{kind}", exist_ok=True)
            idx = self.next_idx[kind]; self.next_idx[kind] += 1
            final = f"{self.dir}/{kind}/part-{idx:04d}.parquet"
            tmp = f"{self.dir}/{kind}/.part-{idx:04d}.parquet.writing"
            size = cs.write_shard(t, tmp, kind)
            os.replace(tmp, final)
            self.rows[kind] += t.num_rows; self.bytes[kind] += size; self.shards[kind] += 1
            rec = {"time_la": now_la(), "path": final, "record_type": kind, "rows": t.num_rows, "bytes": size, **gate}
            with open(self.manifest, "a") as f:
                f.write(json.dumps(rec) + "\n")
            done.append(rec)
            self.buf[kind] = []
        self.text_bytes = 0
        return done


def common_row(kind, *, source_name, source_type, rec_id, country_iso, level, juris_raw, url, phase, source_file, licence, admin1=None, fetch_mode="api", licence_class=None):
    return dict(licence_class=licence_class or "unknown", id=cs.make_id(kind, source_name, rec_id), record_type=kind, country_iso=country_iso, jurisdiction_level=level,
                jurisdiction_raw=juris_raw, admin1=admin1, source_name=source_name, source_type=source_type, source_record_id=rec_id,
                source_url=url, fetch_mode=fetch_mode, retrieval_date=datetime.date.today().isoformat(), licence=licence,
                phase=phase, source_file=source_file)


def write_state(source: str, state: dict):
    """Checkpoint/state file (resume info; shard-based resume in SourceOut remains authoritative)."""
    d = (str(_LEGAL_WS) + "/case_law/pipeline/state"); os.makedirs(d, exist_ok=True)
    state = dict(state, updated_la=now_la(), schema_doc_version=cs.SCHEMA_DOC_VERSION)
    json.dump(state, open(f"{d}/{source}.json.tmp", "w"), indent=1); os.replace(f"{d}/{source}.json.tmp", f"{d}/{source}.json")


def unmatched_from_shards(source: str) -> list[dict]:
    """Gap list derived from ALL decision shards on disk (not only this run): the single source of truth for unmatched_courts.json."""
    agg: dict[tuple, dict] = {}
    for p in sorted(glob.glob(f"{OUT}/{source}/decision/part-*.parquet")):
        t = pq.read_table(p, columns=["country_iso", "admin1", "court_name_raw", "court_match_status", "court_key_provisional"])
        for iso, a1, nm, st, pk in zip(*(t.column(n).to_pylist() for n in t.column_names)):
            if st == "matched": continue
            e = agg.setdefault((iso, a1, nm or "", st), {"country_iso": iso, "admin1": a1, "court_name_raw": nm, "status": st, "provisional_keys": set(), "rows": 0})
            e["rows"] += 1; e["provisional_keys"].add(pk)
    out = []
    for e in sorted(agg.values(), key=lambda x: -x["rows"]):
        e["provisional_keys"] = sorted(e["provisional_keys"]); out.append(e)
    return out


def dump_unmatched(source: str, matcher: CourtMatcher):
    path = f"{OUT}/{source}/unmatched_courts.json"
    items = unmatched_from_shards(source)
    json.dump({"courts_dataset_revision": cs.COURTS_DATASET_REVISION, "schema_doc_version": cs.SCHEMA_DOC_VERSION,
               "match_stats_this_run": matcher.stats if matcher else None, "unmatched": items}, open(path, "w"), indent=1, ensure_ascii=False)
    return path


def court_match_from_shards(source: str) -> dict:
    """r5: court-match counts over ALL decision shards on disk (includes resumed rows), not just this run."""
    cnt = {"matched": 0, "ambiguous": 0, "unmatched": 0}
    for p in sorted(glob.glob(f"{OUT}/{source}/decision/part-*.parquet")):
        for st in pq.read_table(p, columns=["court_match_status"]).column(0).to_pylist():
            cnt[st] = cnt.get(st, 0) + 1
    return cnt


def totals_from_shards(source: str) -> dict:
    rows, shards, nbytes = {}, {}, {}
    for k in cs.RECORD_TYPES:
        ps = sorted(glob.glob(f"{OUT}/{source}/{k}/part-*.parquet"))
        shards[k] = len(ps); nbytes[k] = sum(os.path.getsize(p) for p in ps); rows[k] = sum(pq.ParquetFile(p).metadata.num_rows for p in ps)
    rej = f"{OUT}/{source}/rejected_rows.jsonl"
    return {"decisions_total_incl_resume": rows["decision"], "rows_total": rows, "shards_total": shards, "bytes_total": nbytes,
            "court_match": court_match_from_shards(source), "n_rejected_rows": sum(1 for _ in open(rej)) if os.path.exists(rej) else 0}


def write_summary(source: str, **extra) -> dict:
    """summary.json: totals/court_match are derived from the shards on disk (resume-safe); this-run counters go in under *_this_run keys."""
    s = {"source": source, "schema_doc_version": cs.SCHEMA_DOC_VERSION, **totals_from_shards(source), **extra}
    json.dump(s, open(f"{OUT}/{source}/summary.json", "w"), indent=1)
    return s
