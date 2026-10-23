#!/usr/bin/env python3
"""Spain esPublico Gestiona sedes (*.sedelectronica.es) — "Ordenanzas y reglamentos" board.

Robots-first: every host's /robots.txt is fetched (RFC 9309 matcher, wildcard-aware) and the board URL and
preview-document URLs are checked BEFORE any content request. Conservative policy (asia_latam lane):
  robots.txt unreachable (timeout/network/5xx) -> skip, status=robots_unreachable
  board or document path disallowed            -> skip, status=robots_disallow
Only if allowed: list the board (repo parser municipal/code_docs.parse_sede_documents + Wicket "Mostrar más"),
download each preview-document, extract text (pdftotext), stage SCHEMA.md v1 jsonl to staging/asia_latam/ES/.
State per seed in staging/asia_latam/_state/es/, robots copies in _robots/, logs in _logs/.
NOTE: as of 2026-10-10 every sampled host serves `User-agent: * / Disallow: /* / Allow: /info$ /info.0$ /$`,
so the content path has never been exercised against live data.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, hashlib, json, logging, os, re, subprocess, sys, tempfile, threading, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, "/workspace/ipfs_datasets_py")
import schema as S  # noqa: E402
from common.rfc9309 import Robots  # noqa: E402

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam"))
OUT, STATE, ROBOTS_DIR, QUAR = STAGE / "ES", STAGE / "_state" / "es", STAGE / "_robots", STAGE / "_quarantine" / "ES"
UA = "JusticeDAO-WorldLaw/1.0 (+https://github.com/endomorphosis/ipfs_datasets_py; municipal law research crawler; polite)"
BOARD_ID = "97521486-f59b-11de-b600-00237da12c6a"
log = logging.getLogger("es_sede")
_lock = threading.Lock()
_next = [0.0]


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gate(interval):
    """Global gate: all *.sedelectronica.es hosts are one esPublico backend, so rate-limit them together."""
    with _lock:
        d = _next[0] - time.time()
        if d > 0:
            time.sleep(d)
        _next[0] = time.time() + interval


def load_state(sid):
    p = STATE / f"{sid}.json"
    return json.loads(p.read_text()) if p.exists() else {"seed_id": sid, "status": "new", "done": {}}


def save_state(sid, st):
    STATE.mkdir(parents=True, exist_ok=True)
    p = STATE / f"{sid}.json"
    t = p.with_suffix(".json.tmp")
    t.write_text(json.dumps(st, ensure_ascii=False))
    os.replace(t, p)


def get_robots(sess, host, interval):
    gate(interval)
    try:
        r = sess.get(f"https://{host}/robots.txt", timeout=25)
    except requests.RequestException as e:
        return None, f"robots_unreachable: {type(e).__name__}"
    if r.status_code >= 500:
        return None, f"robots_unreachable: HTTP {r.status_code}"
    ROBOTS_DIR.mkdir(parents=True, exist_ok=True)
    (ROBOTS_DIR / f"{host}.txt").write_text(r.text if r.status_code == 200 else f"# HTTP {r.status_code}\n")
    if r.status_code >= 400:
        return Robots(allow_all=True), None
    return Robots(r.text), None


def jdate(s):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def doc_type(title):
    t = (title or "").lower()
    return "ordinance" if "ordenanza" in t else "regulation"


def pdf_text(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush()
        r = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, timeout=120)
        return r.stdout.decode("utf-8", "replace").strip()


def write_batch(seed, st, rows):
    pk = S.place_key(seed["place_id"], None, "ES")
    good, bad = [], []
    for r in rows:
        (bad if S.validate_record(r) else good).append(r)
    if bad:
        QUAR.mkdir(parents=True, exist_ok=True)
        with open(QUAR / f"{pk}.{seed['seed_id']}.jsonl", "a") as q:
            for r in bad:
                q.write(json.dumps({"reasons": S.validate_record(r), "record": r}, ensure_ascii=False) + "\n")
    if good:
        OUT.mkdir(parents=True, exist_ok=True)
        st["batch"] = st.get("batch", 0) + 1
        final = OUT / f"{pk}.{seed['seed_id']}-sede-p{st['batch']:04d}-{datetime.now(timezone.utc):%Y%m%dT%H%MZ}.jsonl"
        tmp = final.with_name("." + final.name + ".tmp.jsonl")
        with tmp.open("w", encoding="utf-8") as fh:
            for r in good:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush(); os.fsync(fh.fileno())
        v = S.validate_file(tmp, expect_place_key=pk)
        if not v["ok"]:
            raise RuntimeError(f"validate_file: {v['errors'][:3]}")
        os.rename(tmp, final)
    for r in rows:
        st["done"][r["doc_id"]] = 1
    st["n_docs"] = st.get("n_docs", 0) + len(good)
    save_state(seed["seed_id"], st)



_CD = {}


def _code_docs():
    """Load the repo's municipal/code_docs.py WITHOUT executing the heavy ipfs_datasets_py package __init__
    (which needs optional deps such as anyio): stub parent packages, then import the two stdlib-only modules."""
    if not _CD:
        import importlib, types
        base = "/workspace/ipfs_datasets_py/ipfs_datasets_py"
        for name, path in (("ipfs_datasets_py", base), ("ipfs_datasets_py.processors", base + "/processors"),
                           ("ipfs_datasets_py.processors.legal_scrapers", base + "/processors/legal_scrapers"),
                           ("ipfs_datasets_py.processors.legal_scrapers.municipal", base + "/processors/legal_scrapers/municipal")):
            if name not in sys.modules or not hasattr(sys.modules[name], "__path__"):
                m = types.ModuleType(name); m.__path__ = [path]; sys.modules[name] = m
        cd = importlib.import_module("ipfs_datasets_py.processors.legal_scrapers.municipal.code_docs")
        _CD["f"] = (cd.parse_sede_documents, cd.sede_more_path)
    return _CD["f"]

def crawl(seed, a):
    sid, host = seed["seed_id"], seed["host"]
    st = load_state(sid)
    if st.get("status") in ("done", "robots_disallow", "robots_unreachable", "unmatched") and not a.recheck:
        return st
    sess = requests.Session(); sess.headers["User-Agent"] = UA
    board = f"https://{host}/board/{BOARD_ID}/"
    rb, err = get_robots(sess, host, a.interval)
    st["robots_checked_at"] = now_utc()
    if err:
        st.update(status="robots_unreachable", reason=err)
    elif not rb.can_fetch(UA, board):
        st.update(status="robots_disallow", reason=f"board path disallowed: {board}")
    elif not rb.can_fetch(UA, f"https://{host}/preview-document/x"):
        st.update(status="robots_disallow", reason="preview-document path disallowed")
    elif not seed.get("place_id"):
        st.update(status="unmatched", reason="no place_id")
    elif a.robots_only:
        st.update(status="robots_allowed_pending")
    else:
        parse_sede_documents, sede_more_path = _code_docs()
        try:
            gate(a.interval)
            r = sess.get(board, timeout=40)
            html = r.text
            docs = parse_sede_documents(html, board)
            pages = 0
            while (mp := sede_more_path(html)) and pages < 200:
                u = urljoin(board, mp)
                if not rb.can_fetch(UA, u):
                    break
                gate(a.interval)
                html = sess.get(u, timeout=40, headers={"Wicket-Ajax": "true"}).text
                docs += parse_sede_documents(html, board); pages += 1
            st["n_listed"] = len(docs)
            rows = []
            for d in docs:
                did = d["url"].rstrip("/").rsplit("/", 1)[-1]
                if did in st["done"] or not rb.can_fetch(UA, d["url"]):
                    continue
                gate(a.interval)
                rr = sess.get(d["url"], timeout=60)
                ct = rr.headers.get("content-type", "")
                if "pdf" in ct:
                    text, cf = pdf_text(rr.content), "pdf_text"
                else:
                    from bs4 import BeautifulSoup
                    text, cf = BeautifulSoup(rr.text, "lxml").get_text("\n", strip=True), "html"
                rows.append({"place_id": seed["place_id"], "country_code": "ES", "doc_id": did, "source_platform": "es_sedelectronica",
                             "source_url": d["url"], "doc_type": doc_type(d.get("title")), "language": "es",
                             "html_title": d.get("title") or d.get("label"), "title_native": d.get("title") or d.get("label"),
                             "number": d.get("expediente") or None, "published_date": jdate(d.get("published")), "in_force": None,
                             "consolidated": False, "content_format": cf, "text": text, "retrieved_at": now_utc(),
                             "place_name": seed["name"], "qid": seed["qid"], "admin_level": seed.get("admin_level") or "municipality",
                             "platform": "es_sedelectronica", "platform_place_id": host, "ine_code": seed.get("ine"),
                             "board_label": d.get("label"), "procedure": d.get("procedure"),
                             "content_sha256": hashlib.sha256(rr.content).hexdigest()})
                if len(rows) >= 100:
                    write_batch(seed, st, rows); rows = []
            write_batch(seed, st, rows)
            st["status"] = "done"
        except Exception as e:  # noqa: BLE001
            st.update(status="error", reason=f"{type(e).__name__}: {e}"[:300])
    save_state(sid, st)
    log.info("%s %s %s status=%s %s", sid, host, seed["name"], st["status"], st.get("reason", ""))
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between requests to the shared esPublico backend")
    ap.add_argument("--robots-only", action="store_true")
    ap.add_argument("--recheck", action="store_true", help="re-check seeds previously skipped for robots")
    a = ap.parse_args()
    seeds = json.load(open(HERE / "seeds_places.json"))
    if a.ids:
        ids = set(a.ids.split(",")); seeds = [s for s in seeds if s["seed_id"] in ids]
    if a.limit:
        seeds = seeds[: a.limit]
    log.info("seeds=%d interval=%.1fs robots_only=%s", len(seeds), a.interval, a.robots_only)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(lambda s: crawl(s, a), seeds))
    log.info("finished")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
