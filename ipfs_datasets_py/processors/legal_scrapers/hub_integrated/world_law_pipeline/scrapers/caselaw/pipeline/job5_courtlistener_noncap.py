"""Job 5: CourtListener (Free Law Project) public bulk CSVs -> caselaw-raw/v0-r8, NON-CAP material only.
Streams each bz2 CSV over HTTP from the free.law S3 bucket (robots-gated, TLS-verified, single connection, honest UA), decompresses on the fly, never lands raw data.
Stages (all resumable, checkpoints in state/<SRC>.json, sqlite index in state/<SRC>.sqlite):
  courts -> A clusters (index, CAP drop) -> A2 citations -> B dockets (docket shards, CAP-bit drop) -> C opinions (decision+opinion pair per opinion, 500 rows/shard) -> E citation edges -> finalize.
CAP/Harvard exclusion: cluster.source containing 'U'; cluster filepath_json_harvard/filepath_pdf_harvard non-empty; docket.source & 16; opinion.xml_harvard non-empty.
Env: SRC (default courtlistener_noncap), STAGE_LIMITS="A=100000,B=...,C=...,E=..." (smoke only), MAX_MBPS (default 25)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys, os, re, io, csv, bz2, json, time, queue, threading, sqlite3, html as htmllib, datetime, copy
from cl_common import *
import r6_rules

SRC = os.environ.get("SRC", "courtlistener_noncap")
SNAP = "2026-09-30"
BASE = "https://com-courtlistener-storage.s3.amazonaws.com/bulk-data/"
def URL(name): return f"{BASE}{name}-{SNAP}.csv.bz2"
SRC_FILE = lambda name: f"courtlistener_bulk/{name}-{SNAP}.csv.bz2"
MAX_BPS = float(os.environ.get("MAX_MBPS", "25")) * 1e6
LIMITS = {k: int(v) for k, v in (x.split("=") for x in os.environ.get("STAGE_LIMITS", "").split(",") if x)}
STATE_DIR = (str(_LEGAL_WS) + "/case_law/pipeline/state")
DB = f"{STATE_DIR}/{SRC}.sqlite"; CKPT = f"{STATE_DIR}/{SRC}.json"
RESERVE = 1 * 2**30                    # opinion stage stops at floor+1GiB so that edges/finalisation still fit above the 16G floor
EDGE_SHARD_ROWS = 200_000
csv.field_size_limit(2**31 - 1)

LICENCE = ("No formal licence: Free Law Project states 'Our bulk data files are free of known copyright restrictions' (https://www.courtlistener.com/help/api/bulk-data/); "
           "no warranty on third-party copyright in individual documents; CourtListener terms and policies apply (https://wiki.free.law/c/terms/courtlistener/courtlistenercom-terms-of-service-and-policies)")
TERMS = {"basis": "Free Law Project CourtListener bulk-data page (https://www.courtlistener.com/help/api/bulk-data/): 'Our bulk data files are free of known copyright restrictions.' No formal licence grant and no AI/TDM reservation found on that page; "
                  "bulk files are provided as-is with no copyright warranty for third-party content. CourtListener Terms of Service & policies (FLP wiki, read 2026-10-29) restrict unlawful use, FCRA-regulated (consumer-report) use and "
                  "criminal-record screening style uses and disclaim warranties; the www.courtlistener.com terms page itself returned HTTP 403 to the fetcher so the FLP wiki copy was used. "
                  "Bucket host robots.txt returns 404 (no restrictions). Licence class kept 'unknown' and rows restricted from AI training pending legal review. "
                  "CAP/Harvard (Caselaw Access Project) material is excluded: cluster source containing 'U', filepath_*_harvard set, docket source bit 16, opinion xml_harvard set.",
         "evidence_url": ["https://www.courtlistener.com/help/api/bulk-data/", "https://wiki.free.law/c/terms/courtlistener/courtlistenercom-terms-of-service-and-policies",
                          "https://lil.law.harvard.edu/blog/2024/03/26/transitions-for-the-caselaw-access-project/", "https://com-courtlistener-storage.s3.amazonaws.com/robots.txt"],
         "checked": "2026-10-29", "pending_legal_review": True, "attribution": "Free Law Project / CourtListener", "snapshot": SNAP,
         "excluded": "CAP/Harvard material; blocked clusters (blocked=t); non-court bodies (attorney-general opinions, committees, test courts)"}

OPTYPE = {"010combined": "lead", "015unanimous": "majority", "020lead": "lead", "025plurality": "plurality", "030concurrence": "concurrence", "035concurrenceinpart": "concurrence",
          "040dissent": "dissent", "050addendum": "other", "060remittitur": "other", "070rehearing": "other", "080onthemerits": "other", "090onmotiontostrike": "other"}
STATES = {"alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
          "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
          "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
          "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
          "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC", "puerto rico": "PR", "guam": "GU", "virgin islands": "VI", "american samoa": "AS", "northern mariana": "MP"}
STATE_RE = re.compile(r"\b(" + "|".join(sorted((re.escape(s) for s in STATES), key=len, reverse=True)) + r")\b", re.I)
NON_COURT = {"SAG", "C", "T"}          # attorney-general opinions, committees, test courts: body_type rules would mislabel them as courts


# ---------------------------------------------------------------- streaming
class StreamFetcher(Fetcher):
    def open_stream(self, url, tries=4):
        last = None
        for i in range(tries):
            self.gate.enforce(url); self.n += 1
            try:
                r = self.s.get(url, stream=True, timeout=(15, 120), allow_redirects=True)
            except requests.RequestException as e:
                last = repr(e); self.errors += 1; time.sleep(min(120, 10 * 2 ** i)); continue
            if r.status_code in (403, 429):
                self.blocked += 1; r.close()
                if self.blocked >= 3: raise StopJob(f"STOP: HTTP {r.status_code} x3 from {url} (not bypassing)")
                time.sleep(min(300, 30 * self.blocked)); last = f"HTTP {r.status_code}"; continue
            if r.status_code >= 500: last = f"HTTP {r.status_code}"; r.close(); time.sleep(min(120, 10 * 2 ** i)); continue
            r.raise_for_status(); self.blocked = 0
            return r
        raise requests.RequestException(f"giving up {url}: {last}")


class QReader(io.RawIOBase):
    def __init__(self, q): self.q = q; self.buf = b""; self.done = False
    def readable(self): return True
    def readinto(self, b):
        while not self.buf and not self.done:
            it = self.q.get()
            if it is None: self.done = True
            elif isinstance(it, BaseException): raise it
            else: self.buf = it
        n = min(len(b), len(self.buf)); b[:n] = self.buf[:n]; self.buf = self.buf[n:]; return n


def producer(fetcher, url, q, stop, stats):
    r = None
    try:
        r = fetcher.open_stream(url)
        d = bz2.BZ2Decompressor(); t0 = time.time(); got = 0
        for chunk in r.iter_content(1 << 20):
            if stop.is_set(): return
            got += len(chunk); stats["bytes"] = got; data = chunk
            while data:
                if d.eof: d = bz2.BZ2Decompressor()          # multi-stream file: next stream
                out = d.decompress(data); data = d.unused_data if d.eof else b""
                while out and not stop.is_set():
                    try: q.put(out, timeout=1); break
                    except queue.Full: pass
            lag = got / MAX_BPS - (time.time() - t0)
            if lag > 0: time.sleep(lag)
        q.put(None)
    except BaseException as e:
        q.put(e)
    finally:
        if r is not None: r.close()


def rows_once(fetcher, name, skip, stats):
    q = queue.Queue(maxsize=6); stop = threading.Event()
    th = threading.Thread(target=producer, args=(fetcher, URL(name), q, stop, stats), daemon=True); th.start()
    try:
        f = io.TextIOWrapper(io.BufferedReader(QReader(q), 1 << 20), encoding="utf-8", errors="replace", newline="")
        rd = csv.reader(f, delimiter=",", quotechar='"', escapechar="\\", doublequote=False)
        hdr = next(rd); yield hdr
        for i, row in enumerate(rd):
            if i < skip: continue
            yield row
    finally:
        stop.set()
        try:
            while True: q.get_nowait()
        except queue.Empty: pass


def rows(fetcher, name, skip=0, limit=None):
    """-> (header, generator of (row_index, row)). Reconnects after transport errors by re-streaming and skipping rows already yielded."""
    stats = {"bytes": 0}
    first = {}
    def gen():
        pos = skip; tries = 0
        while True:
            try:
                it = rows_once(fetcher, name, pos, stats); hdr = next(it); first.setdefault("hdr", hdr)
                for row in it:
                    yield pos, row; pos += 1; tries = 0
                    if limit is not None and pos >= limit: return
                return
            except (requests.RequestException, OSError, EOFError, ValueError) as e:
                tries += 1
                if tries > 6: raise
                print(now_la(), f"stream {name} error {e!r}; retry {tries} from row {pos}", flush=True); time.sleep(min(300, 30 * 2 ** tries))
    g = gen()
    # peek header: run generator machinery lazily -> simplest is to read header separately
    return g, stats


def header_of(fetcher, name):
    stats = {"bytes": 0}; it = rows_once(fetcher, name, 0, stats)
    try: return next(it)
    finally: it.close()


# ---------------------------------------------------------------- state
def ckpt_load():
    return json.load(open(CKPT)) if os.path.exists(CKPT) else {"stages": {}, "counters": {}, "consumed": {}, "court_used": {}}
def ckpt_save(st):
    st["updated_la"] = now_la(); st["pid"] = os.getpid()
    json.dump(st, open(CKPT + ".tmp", "w"), indent=1); os.replace(CKPT + ".tmp", CKPT)

class Counters:
    def __init__(self, d): self.d = d
    def add(self, table, bucket, reason=None, n=1):
        t = self.d.setdefault(table, {"read": 0, "kept": 0, "excluded_cap": 0, "excluded_other": 0, "reasons": {}})
        t[bucket] += n
        if reason: t["reasons"][f"{bucket}:{reason}"] = t["reasons"].get(f"{bucket}:{reason}", 0) + n


def db_open():
    os.makedirs(STATE_DIR, exist_ok=True)
    db = sqlite3.connect(DB); db.execute("PRAGMA journal_mode=WAL"); db.execute("PRAGMA synchronous=NORMAL"); db.execute("PRAGMA cache_size=-262144")
    db.executescript("""CREATE TABLE IF NOT EXISTS kept(cid INTEGER PRIMARY KEY, docket_id INTEGER, date_filed TEXT, csource TEXT, judges TEXT, prec TEXT, ccount INTEGER) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS excl(cid INTEGER PRIMARY KEY, flag INTEGER) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS cit(cid INTEGER, typ INTEGER, c TEXT);
    CREATE TABLE IF NOT EXISTS dock(docket_id INTEGER PRIMARY KEY, court_id TEXT, docket_number TEXT, dsource INTEGER) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS capdock(docket_id INTEGER PRIMARY KEY) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS opflag(opid INTEGER PRIMARY KEY, flag INTEGER) WITHOUT ROWID;""")
    return db


# ---------------------------------------------------------------- output
class Out(SourceOut):
    """SourceOut for a streamed multi-table job: resume is row-skip based, so no `seen` set; edge ids are not tracked (unique by construction)."""
    def __init__(self):
        self.source, self.phase = SRC, "phaseA"; self.dir = f"{OUT}/{SRC}"; self.dry = False; os.makedirs(self.dir, exist_ok=True)
        self.max_rows, self.max_text_bytes = 500, 64_000_000
        self.buf = {k: [] for k in cs.RECORD_TYPES}; self.text_bytes = 0
        self.rows = {k: 0 for k in cs.RECORD_TYPES}; self.bytes = {k: 0 for k in cs.RECORD_TYPES}; self.shards = {k: 0 for k in cs.RECORD_TYPES}
        self.manifest = f"{self.dir}/manifest.jsonl"; self.seen = set(); self.ids_seen = set()
        for k in ("decision", "opinion", "docket"):
            for p in glob.glob(f"{self.dir}/{k}/part-*.parquet"):
                for b in pq.ParquetFile(p).iter_batches(columns=["id"], batch_size=65536): self.ids_seen.update(b.column(0).to_pylist())
        self.next_idx = {k: len(glob.glob(f"{self.dir}/{k}/part-*.parquet")) for k in cs.RECORD_TYPES}
    def check_row(self, kind, row):
        try:
            probs = cs.validate_caselaw_table(cs.cast_rows([copy.deepcopy(row)], kind), kind)
            if probs: raise ValueError(f"{kind}: " + "; ".join(probs[:4]))
            return True
        except Exception as e:
            self.rejected = getattr(self, "rejected", 0) + 1
            with open(f"{self.dir}/rejected_rows.jsonl", "a") as f: f.write(json.dumps({"time_la": now_la(), "source_record_id": row.get("source_record_id"), "reason": str(e)[:300]}) + "\n")
            return False
    def flush_kind(self, kind, gate=None):
        rows_ = self.buf[kind]
        if not rows_: return None
        gate = gate or preflight(f"{SRC} {kind} shard")
        if kind != "citation_edge":
            for r in rows_:
                if r["id"] in self.ids_seen:
                    r.setdefault("metadata_json", {}); r["metadata_json"]["id_original"] = r["id"]; r["metadata_json"]["id_rule"] = cs.ID_RULE; r["id"] = cs.dedupe_id(r["id"], self.phase)
                self.ids_seen.add(r["id"])
        t = cs.cast_rows(rows_, kind); os.makedirs(f"{self.dir}/{kind}", exist_ok=True)
        idx = self.next_idx[kind]; self.next_idx[kind] += 1
        final = f"{self.dir}/{kind}/part-{idx:05d}.parquet"; tmp = f"{self.dir}/{kind}/.part-{idx:05d}.parquet.writing"
        size = cs.write_shard(t, tmp, kind); os.replace(tmp, final)
        self.rows[kind] += t.num_rows; self.bytes[kind] += size; self.shards[kind] += 1
        rec = {"time_la": now_la(), "path": final, "record_type": kind, "rows": t.num_rows, "bytes": size, **gate}
        with open(self.manifest, "a") as f: f.write(json.dumps(rec) + "\n")
        self.buf[kind] = []
        if kind == "opinion": self.text_bytes = 0
        return rec


# ---------------------------------------------------------------- helpers
def strip_html(h):
    h = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</(?:p|div|li|tr|h[1-6]|blockquote|pre|center|table)>", "\n", h)
    h = re.sub(r"<[^>]+>", "", h); h = htmllib.unescape(h)
    h = re.sub(r"[ \t\r\f\v\u00a0]+", " ", h); h = re.sub(r" ?\n ?", "\n", h); h = re.sub(r"\n{3,}", "\n\n", h)
    return h.strip()

def state_of(name):
    m = STATE_RE.findall(name or "")
    if not m: return None
    best = max(m, key=len); return "US-" + STATES[best.lower()]

class Courts:
    def __init__(self, matcher, courts): self.m, self.courts, self.cache = matcher, courts, {}
    def get(self, court_id):
        if court_id in self.cache: return self.cache[court_id]
        c = self.courts.get(court_id)
        if not c: self.cache[court_id] = None; return None
        jur, name, url = c["jurisdiction"], c["full_name"] or c["short_name"], c["url"]
        st = state_of(name); federal = jur.startswith("F") or jur in ("MA", "MB", "I", "")
        level = "national" if federal or not st and jur not in ("S", "SA", "ST", "SS") else "state"
        prim = None if federal else st; alt = st if federal else None
        tries = [prim] + ([alt] if alt and alt != prim else [])
        best = None
        for a1 in tries:
            cm = self.m.match("US", name, admin1=a1, source_name=SRC, discriminator=court_id)
            if best is None: best = (a1, cm)
            if cm["court_match_status"] == "matched": best = (a1, cm); break
        if best[1]["court_match_status"] != "matched" and url:
            cm = self.m.match("US", name, admin1=prim, website=url, source_name=SRC, discriminator=court_id)
            if cm["court_match_status"] == "matched": best = (prim, cm)
        res = {"admin1": best[0], "cm": best[1], "name": cs.clean_label(name), "level": level, "jur": jur, "court_id": court_id}
        self.cache[court_id] = res; return res

LANG_NOTE = "assumed 'en' from US jurisdiction (CourtListener carries no language field)"
def base_row(kind, rec_id, court, url, srcfile, found_on, licence_class="unknown"):
    r = common_row(kind, source_name=SRC, source_type="courtlistener_bulk_csv", rec_id=rec_id, country_iso="US", level=court["level"], juris_raw=court["court_id"], admin1=court["admin1"],
                   url=url, phase="phaseA", source_file=srcfile, licence=LICENCE, fetch_mode="bulk", licence_class=licence_class)
    r["found_on"] = found_on
    return r

def court_fields(row, court):
    cm = court["cm"]
    row.update(court_entity_key=cm["court_entity_key"], court_key_provisional=cm["court_key_provisional"], court_match_status=cm["court_match_status"], court_name_raw=court["name"])
    return cm["meta"]

def date_ok(v): return v if v and cs.RE_DATE.match(v) and len(v) == 10 else None
def to_int(v):
    try: return int(v)
    except (TypeError, ValueError): return None
def progress(tag, n, t0, stats, extra=""):
    gate = preflight(tag)
    print(now_la(), f"{tag} rows={n} {n/max(1,time.time()-t0):.0f}/s dl={stats['bytes']/1e9:.2f}GB disk={gate['disk_free_gib']}G mem={gate['mem_avail_gib']}Gi {extra}", flush=True)


# ---------------------------------------------------------------- stages
def stage_courts(f):
    gen, st = rows(f, "courts"); hdr = header_of(f, "courts"); H = {h: i for i, h in enumerate(hdr)}; out = {}
    for pos, r in gen:
        if len(r) != len(hdr): continue
        out[r[H["id"]]] = {"jurisdiction": r[H["jurisdiction"]], "full_name": r[H["full_name"]], "short_name": r[H["short_name"]], "url": r[H["url"]]}
    print(now_la(), "courts", len(out), flush=True); return out

def stage_clusters(f, db, S, C, ck):
    if S.get("A") == "done": return
    hdr = header_of(f, "opinion-clusters"); H = {h: i for i, h in enumerate(hdr)}
    need = ["id", "date_filed", "source", "filepath_json_harvard", "filepath_pdf_harvard", "docket_id", "blocked", "judges", "precedential_status", "citation_count"]
    assert all(n in H for n in need), "cluster header changed"
    skip = ck["consumed"].get("A", 0); t0 = time.time(); kept, excl = [], []
    gen, stats = rows(f, "opinion-clusters", skip, LIMITS.get("A")); n = skip
    for pos, r in gen:
        n = pos + 1
        if len(r) != len(hdr): C.add("opinion_clusters", "read"); C.add("opinion_clusters", "excluded_other", "malformed_row"); continue
        cid = to_int(r[H["id"]]); C.add("opinion_clusters", "read")
        if cid is None: C.add("opinion_clusters", "excluded_other", "bad_id"); continue
        src = r[H["source"]]
        if "U" in src: excl.append((cid, 1)); C.add("opinion_clusters", "excluded_cap", "source_contains_U"); 
        elif r[H["filepath_json_harvard"]] or r[H["filepath_pdf_harvard"]]: excl.append((cid, 1)); C.add("opinion_clusters", "excluded_cap", "harvard_filepath")
        elif r[H["blocked"]] == "t": excl.append((cid, 2)); C.add("opinion_clusters", "excluded_other", "blocked")
        elif not date_ok(r[H["date_filed"]]) or to_int(r[H["docket_id"]]) is None: excl.append((cid, 2)); C.add("opinion_clusters", "excluded_other", "bad_date_or_docket")
        else:
            kept.append((cid, to_int(r[H["docket_id"]]), r[H["date_filed"]], src, r[H["judges"]][:300] or None, r[H["precedential_status"]] or None, to_int(r[H["citation_count"]])))
            C.add("opinion_clusters", "kept")
        if len(kept) + len(excl) >= 50000:
            db.executemany("INSERT OR REPLACE INTO kept VALUES (?,?,?,?,?,?,?)", kept); db.executemany("INSERT OR REPLACE INTO excl VALUES (?,?)", excl); kept, excl = [], []
        if n % 200000 == 0:
            db.executemany("INSERT OR REPLACE INTO kept VALUES (?,?,?,?,?,?,?)", kept); db.executemany("INSERT OR REPLACE INTO excl VALUES (?,?)", excl); kept, excl = [], []; db.commit()
            ck["consumed"]["A"] = n; ck["counters"] = C.d; ckpt_save(ck); progress("A clusters", n, t0, stats, f"kept={C.d['opinion_clusters']['kept']}")
    db.executemany("INSERT OR REPLACE INTO kept VALUES (?,?,?,?,?,?,?)", kept); db.executemany("INSERT OR REPLACE INTO excl VALUES (?,?)", excl); db.commit()
    ck["consumed"]["A"] = n; S["A"] = "done" if LIMITS.get("A") is None else "done_limited"; ck["counters"] = C.d; ckpt_save(ck); print(now_la(), "A done", n, flush=True)

def stage_citations(f, db, S, C, ck):
    if S.get("A2") == "done": return
    hdr = header_of(f, "citations"); H = {h: i for i, h in enumerate(hdr)}
    keptset = set(x[0] for x in db.execute("SELECT cid FROM kept")); t0 = time.time(); batch = []
    db.execute("DELETE FROM cit")
    gen, stats = rows(f, "citations", 0, LIMITS.get("A2")); n = 0
    for pos, r in gen:
        n = pos + 1; C.add("citations", "read")
        cid = to_int(r[H["cluster_id"]]) if len(r) == len(hdr) else None
        if cid is None: C.add("citations", "excluded_other", "malformed_row"); continue
        if cid in keptset:
            c = f"{r[H['volume']]} {r[H['reporter']]} {r[H['page']]}".strip()
            if cs.RE_CASE_NAME_VALUE.search(c) or len(c) > 80: C.add("citations", "excluded_other", "case_name_like"); continue
            batch.append((cid, to_int(r[H["type"]]), c)); C.add("citations", "kept")
        else:
            row = db.execute("SELECT flag FROM excl WHERE cid=?", (cid,)).fetchone()
            if row and row[0] == 1: C.add("citations", "excluded_cap", "cluster_is_cap")
            else: C.add("citations", "excluded_other", "cluster_not_kept" if row else "cluster_missing_from_snapshot")
        if len(batch) >= 50000: db.executemany("INSERT INTO cit VALUES (?,?,?)", batch); batch = []
        if n % 1000000 == 0: progress("A2 citations", n, t0, stats)
    db.executemany("INSERT INTO cit VALUES (?,?,?)", batch); db.execute("CREATE INDEX IF NOT EXISTS cit_cid ON cit(cid)"); db.commit()
    S["A2"] = "done" if LIMITS.get("A2") is None else "done_limited"; ck["counters"] = C.d; ckpt_save(ck); print(now_la(), "A2 done", n, flush=True)

def stage_dockets(f, db, S, C, ck, out, courts):
    if S.get("B") == "done": return
    hdr = header_of(f, "dockets"); H = {h: i for i, h in enumerate(hdr)}
    need = ["id", "source", "date_filed", "date_terminated", "docket_number", "court_id", "blocked"]; assert all(n in H for n in need), "docket header changed"
    needed = set(x[0] for x in db.execute("SELECT DISTINCT docket_id FROM kept")); skip = ck["consumed"].get("B", 0); t0 = time.time(); batch = []; capb = []
    gen, stats = rows(f, "dockets", skip, LIMITS.get("B")); n = skip
    def save(n):
        db.executemany("INSERT OR REPLACE INTO dock VALUES (?,?,?,?)", batch); db.executemany("INSERT OR REPLACE INTO capdock VALUES (?)", capb); batch.clear(); capb.clear(); db.commit()
        ck["consumed"]["B"] = n; ck["counters"] = C.d; ck["court_used"] = {k: (v["cm"]["court_match_status"] if v else None) for k, v in courts.cache.items()}; ckpt_save(ck)
    for pos, r in gen:
        n = pos + 1; C.add("dockets", "read")
        if len(r) != len(hdr): C.add("dockets", "excluded_other", "malformed_row"); continue
        did = to_int(r[H["id"]]); dsrc = to_int(r[H["source"]]) or 0
        if did not in needed:
            if dsrc & 16: C.add("dockets", "excluded_cap", "harvard_bit_not_referenced")
            else: C.add("dockets", "excluded_other", "not_referenced_by_kept_cluster")
        elif dsrc & 16:
            capb.append((did,)); C.add("dockets", "excluded_cap", "harvard_bit_referenced")
        elif r[H["blocked"]] == "t": C.add("dockets", "excluded_other", "blocked"); batch.append((did, None, None, dsrc))
        else:
            cid_ = r[H["court_id"]]; court = courts.get(cid_); dn = cs.clean_label(r[H["docket_number"]])
            if dn and cs.RE_CASE_NAME_VALUE.search(dn): dn = None
            batch.append((did, cid_ if court else None, dn, dsrc))
            if court is None: C.add("dockets", "excluded_other", "unknown_court")
            elif court["jur"] in NON_COURT: C.add("dockets", "excluded_other", "non_court_body")
            elif not dn: C.add("dockets", "excluded_other", "no_usable_docket_number")
            else:
                row = base_row("docket", f"docket-{did}", court, f"https://www.courtlistener.com/api/rest/v4/dockets/{did}/", SRC_FILE("dockets"), URL("dockets"))
                meta = court_fields(row, court)
                row.update(docket_number=dn, filing_date=date_ok(r[H["date_filed"]]), termination_date=date_ok(r[H["date_terminated"]]), restricted_ai_training=True, parties_redaction_status="unknown",
                           metadata_json={"terms": TERMS, "cl_docket_id": did, "cl_court_id": cid_, "docket_source_bitmask": dsrc, "courts_dataset_revision": cs.COURTS_DATASET_REVISION, **meta})
                if out.check_row("docket", row): out.buf["docket"].append(row); C.add("dockets", "kept")
                else: C.add("dockets", "excluded_other", "validation_reject")
                if len(out.buf["docket"]) >= 500:
                    rec = out.flush_kind("docket"); save(n); print(now_la(), "shard", rec["path"][-30:], flush=True)
        if n % 1000000 == 0:
            if out.buf["docket"]: out.flush_kind("docket")
            save(n); progress("B dockets", n, t0, stats, f"kept={C.d['dockets']['kept']}")
    if out.buf["docket"]: out.flush_kind("docket")
    save(n)
    # clusters on a Harvard-bit docket are CAP-adjacent: move them from kept to excluded_cap
    ncap = db.execute("SELECT COUNT(*) FROM kept WHERE docket_id IN (SELECT docket_id FROM capdock)").fetchone()[0]
    db.execute("INSERT OR REPLACE INTO excl SELECT cid, 1 FROM kept WHERE docket_id IN (SELECT docket_id FROM capdock)")
    db.execute("DELETE FROM kept WHERE docket_id IN (SELECT docket_id FROM capdock)"); db.commit()
    C.add("opinion_clusters", "excluded_cap", "docket_harvard_bit", ncap); C.add("opinion_clusters", "kept", None, -ncap)
    S["B"] = "done" if LIMITS.get("B") is None else "done_limited"; ck["counters"] = C.d; ckpt_save(ck); print(now_la(), "B done", n, "clusters moved to cap:", ncap, flush=True)

def stage_opinions(f, db, S, C, ck, out, courts):
    if S.get("C") in ("done", "done_limited"): return
    hdr = header_of(f, "opinions"); H = {h: i for i, h in enumerate(hdr)}
    need = ["id", "author_str", "per_curiam", "type", "sha1", "page_count", "plain_text", "html", "html_lawbox", "html_columbia", "html_anon_2020", "xml_harvard", "html_with_citations", "extracted_by_ocr", "cluster_id"]
    assert all(n in H for n in need), "opinion header changed"
    Q = "SELECT k.docket_id,k.date_filed,k.csource,k.judges,k.prec,k.ccount,d.court_id,d.docket_number,d.dsource,(SELECT group_concat(typ||'|'||c, char(10)) FROM cit WHERE cid=k.cid) FROM kept k LEFT JOIN dock d ON d.docket_id=k.docket_id WHERE k.cid=?"
    skip = ck["consumed"].get("C", 0); t0 = time.time(); pending = []; last_flush_rows = out.rows["decision"]
    gen, stats = rows(f, "opinions", skip, LIMITS.get("C")); n = skip; stopped = None
    def save(n):
        db.executemany("INSERT OR REPLACE INTO opflag VALUES (?,?)", pending); pending.clear(); db.commit()
        ck["consumed"]["C"] = n; ck["counters"] = C.d; ck["court_used"] = {k: (v["cm"]["court_match_status"] if v else None) for k, v in courts.cache.items()}; ckpt_save(ck)
    def do_flush(n):
        if disk_free() < DISK_FLOOR + RESERVE: raise StopJob(f"RESERVE: free disk {disk_free()/2**30:.2f}G < floor+1G reserve; stopping opinion stage cleanly")
        out.flush_kind("decision"); rec = out.flush_kind("opinion"); save(n); print(now_la(), "shard", rec["path"][-30:], rec["rows"], "rows", flush=True)
    try:
        for pos, r in gen:
            n = pos + 1; C.add("opinions", "read")
            if len(r) != len(hdr): C.add("opinions", "excluded_other", "malformed_row"); continue
            oid = to_int(r[H["id"]]); cid = to_int(r[H["cluster_id"]])
            if oid is None: C.add("opinions", "excluded_other", "bad_id"); continue
            if r[H["xml_harvard"]]: pending.append((oid, 1)); C.add("opinions", "excluded_cap", "xml_harvard"); continue
            k = db.execute(Q, (cid,)).fetchone() if cid is not None else None
            if not k:
                e = db.execute("SELECT flag FROM excl WHERE cid=?", (cid,)).fetchone() if cid is not None else None
                if e and e[0] == 1: pending.append((oid, 1)); C.add("opinions", "excluded_cap", "cluster_is_cap")
                else: pending.append((oid, 2)); C.add("opinions", "excluded_other", "cluster_excluded_other" if e else "cluster_missing_from_snapshot")
                continue
            docket_id, date_filed, csrc, judges, prec, ccount, court_id, dnum, dsrc, cits = k
            court = courts.get(court_id) if court_id else None
            if court is None: pending.append((oid, 2)); C.add("opinions", "excluded_other", "no_docket_or_court_record"); continue
            if court["jur"] in NON_COURT: pending.append((oid, 2)); C.add("opinions", "excluded_other", "non_court_body"); continue
            txt = None
            if r[H["plain_text"]].strip(): txt, fmt, fld = r[H["plain_text"]].strip(), "plain", "plain_text"
            else:
                for fld in ("html_with_citations", "html_columbia", "html_lawbox", "html_anon_2020", "html"):
                    if r[H[fld]].strip(): txt, fmt = strip_html(r[H[fld]]), "html"; break
            if not txt: pending.append((oid, 2)); C.add("opinions", "excluded_other", "no_text"); continue
            other, neutral = [], None
            for line in (cits or "").split("\n"):
                if "|" not in line: continue
                typ, c = line.split("|", 1)
                if typ == "8" and not neutral: neutral = c
                elif c not in other: other.append(c)
            rid = f"opinion-{oid}"; url = f"https://www.courtlistener.com/api/rest/v4/opinions/{oid}/"
            dec = base_row("decision", rid, court, url, SRC_FILE("opinions"), URL("opinions")); meta = court_fields(dec, court)
            lang = "en"; ocr = r[H["extracted_by_ocr"]] == "t"; sha = cs.text_sha256(txt)
            dec.update(docket_number=dnum, decision_date=date_filed, neutral_citation=neutral, other_citations=other[:20] or None, decision_type="other", language=lang, opinion_count=1,
                       restricted_ai_training=True, ocr=ocr, text_sha256=sha, parties_redaction_status="unknown",
                       metadata_json={"terms": TERMS, "cl_cluster_id": cid, "cl_opinion_id": oid, "cl_docket_id": docket_id, "cl_court_id": court_id, "cluster_source_codes": csrc, "precedential_status": prec,
                                      "citation_count": ccount, "judges_text": judges, "snapshot": SNAP, "language_basis": LANG_NOTE, "courts_dataset_revision": cs.COURTS_DATASET_REVISION, **meta})
            op = base_row("opinion", rid, court, url, SRC_FILE("opinions"), URL("opinions"))
            otype = "per_curiam" if r[H["per_curiam"]] == "t" else OPTYPE.get(r[H["type"]], "other")
            op.update(decision_id=dec["id"], opinion_type=otype, author_raw=cs.clean_label(r[H["author_str"]]), text=txt, text_format=fmt, page_count=to_int(r[H["page_count"]]), language=lang, ocr=ocr,
                      text_backend=f"courtlistener_{fld}", text_sha256=sha, restricted_ai_training=True, parties_redaction_status="unknown",
                      metadata_json={"terms": TERMS, "sha1_source": r[H["sha1"]] or None, "text_field": fld})
            if not out.add_pair(dec, op): pending.append((oid, 2)); C.add("opinions", "excluded_other", "validation_reject"); continue
            pending.append((oid, 3)); C.add("opinions", "kept")
            if out.full():
                do_flush(n)
            if n % 100000 == 0: save(n) if not out.buf["decision"] else None; progress("C opinions", n, t0, stats, f"kept={C.d['opinions']['kept']}")
        if out.buf["decision"]: do_flush(n)
        save(n); S["C"] = "done" if LIMITS.get("C") is None else "done_limited"
    except StopJob as e:
        if str(e).startswith("RESERVE"):
            stopped = str(e); S["C"] = "stopped_disk_reserve"; print(now_la(), stopped, flush=True)
            out.buf = {k: [] for k in cs.RECORD_TYPES}; out.text_bytes = 0   # unflushed rows are re-read on resume (consumed counter only advances at flush)
            saved = json.load(open(CKPT))["counters"]; C.d.clear(); C.d.update(saved)   # counters on disk correspond to the last flush
        else: raise
    ckpt_save(ck); print(now_la(), "C status", S.get("C"), "rows consumed", ck["consumed"].get("C"), flush=True)

def supersede_edges(out):
    d = f"{out.dir}/citation_edge"
    if os.path.isdir(d):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S"); os.makedirs(f"{out.dir}/_superseded", exist_ok=True)
        os.rename(d, f"{out.dir}/_superseded/citation_edge_{stamp}")
        keep = [l for l in open(out.manifest) if '"record_type": "citation_edge"' not in l]; os.replace(out.manifest, f"{out.dir}/_superseded/manifest_before_edges_{stamp}.jsonl")
        open(out.manifest, "w").writelines(keep); out.next_idx["citation_edge"] = 0
        print(now_la(), "superseded earlier citation_edge shards ->", f"_superseded/citation_edge_{stamp}", flush=True)

def stage_edges(f, db, S, C, ck, out):
    basis = ck["consumed"].get("C")
    if S.get("E") == "done" and ck.get("edges_based_on") == basis: return
    if not str(S.get("A")).startswith("done") or not str(S.get("B")).startswith("done"): return
    if os.path.isdir(f"{out.dir}/citation_edge"): supersede_edges(out)
    C.d.pop("citation_edges", None); S.pop("E", None)
    hdr = header_of(f, "citation-map"); H = {h: i for i, h in enumerate(hdr)}
    mx = db.execute("SELECT MAX(opid) FROM opflag").fetchone()[0] or 0; flag = bytearray(mx + 2)
    for opid, fl in db.execute("SELECT opid, flag FROM opflag"): flag[opid] = fl
    t0 = time.time(); gen, stats = rows(f, "citation-map", 0, LIMITS.get("E")); n = 0
    mk = lambda oid: cs.make_id("decision", SRC, f"opinion-{oid}")
    ckpt_basis = basis
    for pos, r in gen:
        n = pos + 1; C.add("citation_edges", "read")
        if len(r) != len(hdr): C.add("citation_edges", "excluded_other", "malformed_row"); continue
        a, b = to_int(r[H["citing_opinion_id"]]), to_int(r[H["cited_opinion_id"]])
        if a is None or b is None: C.add("citation_edges", "excluded_other", "bad_id"); continue
        fa = flag[a] if a <= mx else 0; fb = flag[b] if b <= mx else 0
        if fa == 3 and fb == 3:
            row = common_row("citation_edge", source_name=SRC, source_type="courtlistener_bulk_csv", rec_id=f"{a}>{b}", country_iso="US", level="national", juris_raw="US", url=None, phase="phaseA",
                             source_file=SRC_FILE("citation-map"), licence=LICENCE, fetch_mode="bulk", licence_class="unknown")
            row.update(found_on=URL("citation-map"), citing_id=mk(a), cited_id=mk(b), depth=to_int(r[H["depth"]]), treatment="cites", metadata_json={"terms": TERMS, "snapshot": SNAP})
            out.buf["citation_edge"].append(row); C.add("citation_edges", "kept")
            if len(out.buf["citation_edge"]) >= EDGE_SHARD_ROWS:
                out.flush_kind("citation_edge"); ckpt_save(ck)
        elif fa == 1 or fb == 1: C.add("citation_edges", "excluded_cap", "endpoint_is_cap_opinion")
        else: C.add("citation_edges", "excluded_other", "endpoint_not_ingested")
        if n % 5000000 == 0: progress("E edges", n, t0, stats, f"kept={C.d['citation_edges']['kept']}")
    if out.buf["citation_edge"]: out.flush_kind("citation_edge")
    S["E"] = "done" if LIMITS.get("E") is None else "done_limited"; ck["edges_based_on"] = ckpt_basis; ck["counters"] = C.d; ckpt_save(ck); print(now_la(), "E done", n, flush=True)


def main():
    print(now_la(), "start", SRC, "pid", os.getpid(), "limits", LIMITS, preflight("start"), flush=True)
    ck = ckpt_load(); S = ck["stages"]; C = Counters(ck["counters"]); db = db_open()
    f = StreamFetcher(1.0); out = Out(); fails = []; reason = None
    matcher = CourtMatcher()
    try:
        courts = Courts(matcher, stage_courts(f))
        stage_clusters(f, db, S, C, ck)
        stage_citations(f, db, S, C, ck)
        stage_dockets(f, db, S, C, ck, out, courts)
        stage_opinions(f, db, S, C, ck, out, courts)
        stage_edges(f, db, S, C, ck, out)
    except StopJob as e:
        reason = str(e); fails.append(reason); print(now_la(), reason, flush=True); C.d.clear(); C.d.update(json.load(open(CKPT))["counters"]) if os.path.exists(CKPT) else None
    except Exception as e:
        reason = f"error: {e!r}"; fails.append(reason); print(now_la(), reason, flush=True); import traceback; traceback.print_exc()
    # finalise (derived from the shards on disk)
    try: out.buf = {k: [] for k in cs.RECORD_TYPES}
    except Exception: pass
    up = dump_unmatched(SRC, matcher)
    cu = ck.get("court_used", {}); cu_stats = {s: sum(1 for v in cu.values() if v == s) for s in ("matched", "ambiguous", "unmatched")}
    cu_stats["not_in_courts_table"] = sum(1 for v in cu.values() if v is None)
    summary = write_summary(SRC, n_fails=len(fails), fails=fails[:20], snapshot=SNAP, stages=S, consumed=ck["consumed"], tables=C.d, courts_used=len(cu), courts_distinct_match_status=cu_stats,
                            licence_recorded=LICENCE, terms_recorded=TERMS, restricted_ai_training="true on all rows (licence_class unknown, terms.pending_legal_review true)",
                            design_note="one decision row per opinion (decision/opinion 1:1) with cl_cluster_id in metadata_json; rows are CourtListener non-CAP only",
                            end_gate=preflight("end") if reason is None or "STOP" not in reason else {"disk_free_gib": round(disk_free()/2**30, 2), "mem_avail_gib": round(mem_avail()/2**30, 2)}, finished_la=now_la(), stopped_reason=reason, unmatched_file=up)
    ck["final_la"] = now_la(); ckpt_save(ck)
    print(json.dumps({k: summary[k] for k in ("rows_total", "shards_total", "court_match", "stages", "tables", "courts_distinct_match_status", "end_gate", "stopped_reason")}, indent=1), flush=True)
    return 3 if reason else 0

if __name__ == "__main__":
    sys.exit(main())
