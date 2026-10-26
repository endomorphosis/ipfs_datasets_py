#!/usr/bin/env python3
"""Polite raw-PDF collector for the no-text / OCR queues (replaces OCR; the Normalizer ingests the PDFs).

Sources (read-only):
  ro      staging/eu/_state/council_ro/notext_urls.jsonl          doc_id romol:<doc_key|sha1(url)[:20]>     (= ocr_ro.row_for)
  gb      staging/eu/_state/council_gb/notext_urls.jsonl          doc_id ukbyelaw:<doc_key|sha1(url)[:20]>  (= ocr_gb.row_for)
  afme    out/afme/_ocr_queue.jsonl                               doc_id/place_id as queued; fetch plan = ocr_afme.candidates (+lane mirror)
  afme_lane out/afme/<CC>/*.jsonl rows content_complete=false with a .pdf URL, not already in the afme queue
  sasia   staging/sasia_ru/_ocr/ocr_queue.jsonl + ru_gosweb_notext.jsonl (dedup by doc_id, = ocr_sasia.load)
          Tatarstan CC rows have no place until OCR names the issuer -> place_id null, place_key "_unassigned"
  ph      staging/ph/_state/ocr_queue.jsonl                       place_id = queue "place_key" field (= ocr_ph.row_for)
  ukie    staging/ukie/_state/needs_ocr/notext_urls.jsonl (GB/IE, council_gb format, lane doc_ids kept; key (place_key, doc_id))
  asia_latam staging/asia_latam/_scanned_pdfs_manifest.jsonl (BR SAPL; key (place_key, doc_id)); states staging/states/_scanned_pdfs_manifest.jsonl (archive URL first)
  sweep   staging/pdf/_state/sweep_20261017.jsonl  global no-text sweep (ocr/sweep_*.py), lane 'sweep'
          + staging/eu/_state/pl/ocr_queue_pl.jsonl and staging/eu/_state/gr/failed.jsonl (EU lane, read-only, re-read every 30 min)
  pk_sd   PK-SD content_complete=false rows (sindhlaws scanned PDFs), from the newest local iso_PK-SD_html.parquet
          PDF = DownloadDocument.aspx?PubID=<pub_id>&Lang=EN (= collect_pk_prov.sd_rec)
place_key = pipeline/schema.place_key(place_id).

Output : staging/pdf/<CC>/<place_key>/<safe(doc_id)>.pdf     (':' '/' -> '_'; long names -> prefix + sha1)
Manifest: per pipeline/PDF_STAGING.md v1.0: staging/pdf/_manifest/batch_<NNNN>.jsonl (.jsonl.tmp while open -> rename -> empty batch_<NNNN>.ready LAST).
          source_url = URL actually fetched (archive URL when archive-sourced); pdf_file when the canonical name is unusable.
          Only image-only PDFs are staged (text-layer PDFs skipped: has_text_layer). Tatarstan rows (no place_id yet) skipped. Sealed batches
          are never touched again. A batch is done when the Normalizer writes batch_<NNNN>.pushed (it deletes the PDFs).
State  : staging/pdf/_state/done.txt (key lane|place_id|doc_id; downloaded rows at seal, terminal skips immediately)
Logs   : staging/pdf/_logs/skipped.jsonl, fetched.jsonl (fetch url/via), events.log
Limits : robots.txt per host (cached; unreachable -> skip), 1 req/s/host, backoff on 429/5xx, <=100 MB, PDF only,
         no Cloudflare/sign-in bypass, rows with source_policy robots_unreachable/robots_disallowed skipped (robots re-checked live
         and logged), staging/pdf <= 10 GB and free disk >= 35 GB (seal + pause until the Normalizer deletes pushed batches).
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, glob, hashlib, json, os, re, shutil, sys, threading, time, urllib.robotparser
from collections import defaultdict, Counter, deque
from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr"))
from schema import place_key as _place_key  # noqa: E402

WL = Path(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law"))
ROOT = WL / "staging/pdf"; MAN, STATE, LOGS = ROOT / "_manifest", ROOT / "_state", ROOT / "_logs"
UA = "world-municipal-law-research/1.0 (PDF collection; open-data reuse; ~1 req/s per host)"
UA_TOKEN = "world-municipal-law-research"
MAX_BYTES = 100 * 1024 * 1024
CF_POL = "metadata_only_cloudflare_challenge"
ROBOTS_POL = {"robots_unreachable", "robots_disallowed"}
SRC = {
    "ro": WL / "staging/eu/_state/council_ro/notext_urls.jsonl",
    "gb": WL / "staging/eu/_state/council_gb/notext_urls.jsonl",
    "afme": WL / "out/afme/_ocr_queue.jsonl",
    "sasia": [WL / "staging/sasia_ru/_ocr/ocr_queue.jsonl", WL / "staging/sasia_ru/_ocr/ru_gosweb_notext.jsonl"],
    "ph": WL / "staging/ph/_state/ocr_queue.jsonl",
    "pk_sd": [WL / "out_national/world_law/data/PK/iso_PK-SD_html.parquet"] +
             sorted(glob.glob(str(WL / "state/dryrun_*/out_national/world_law/data/PK/iso_PK-SD_html.parquet")), reverse=True),
}

def utcnow(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def sha1(s): return hashlib.sha1(s.encode()).hexdigest()
def pols(p): return set(p if isinstance(p, list) else [p]) if p else set()
def place_key(pid): return _place_key(pid) if pid else "_unassigned"
def safe(doc_id):
    """PDF_STAGING.md §2 sanitize_doc_id: every ':', '/', '\\' -> '_', nothing else."""
    return re.sub(r"[:/\\]", "_", doc_id)
def alt_name(doc_id):
    """Fallback file name (recorded in pdf_file) when the canonical name is unusable: starts with '_'/'.', which the
    uploader ignores, is too long for the filesystem, or collides with another doc_id of the same place."""
    s = safe(doc_id).lstrip("._") or "doc"
    if len(s.encode()) > 200: s = s.encode()[:150].decode("utf-8", "ignore")
    return f"d{s}~{sha1(doc_id)[:12]}"
def jl(path):
    with open(path, encoding="utf-8") as f:
        for ln in f:
            if not ln.endswith("\n"): continue
            try: yield json.loads(ln)
            except ValueError: pass

def jl_snapshot(path, tries=5):
    """Read a queue that its producer rewrites atomically (tmp + rename): one open() = one complete version. Retries
    if the name is briefly missing mid-rename. Rows absent from a shorter version are never un-queued or un-done:
    the queue/done sets only grow, so a partial (still-being-rebuilt) file just yields fewer new rows."""
    for i in range(tries):
        try:
            with open(path, encoding="utf-8") as f: data = f.read()
            break
        except FileNotFoundError:
            if i == tries - 1: raise
            time.sleep(1)
    out = []
    for ln in data.splitlines(keepends=True):
        if not ln.endswith("\n"): continue
        try: out.append(json.loads(ln))
        except ValueError: pass
    return out

class Skip(Exception):
    def __init__(self, reason, detail=""): super().__init__(detail); self.reason, self.detail = reason, detail
class Retry(Exception): pass   # transient: not marked done, retried next run

# ---------------------------------------------------------------- sources
def item(lane, doc_id, place_id, cc, url, policy, plan, **kw):
    return dict(lane=lane, doc_id=doc_id, place_id=place_id, place_key=place_key(place_id), country_code=cc,
                source_url=url, source_policy=policy, plan=plan, **kw)

def load_council(lane):
    pre, cc = {"ro": ("romol", "RO"), "gb": ("ukbyelaw", "GB")}[lane]; seen = set()
    for e in jl(SRC[lane]):
        u = e.get("source_url")
        if not u or u in seen or not e.get("place_id"): continue      # = ocr_ro.new_entries
        seen.add(u); key = e.get("doc_key") or ("doc:" + sha1(u)[:20])
        yield item(lane, f"{pre}:{key[4:] if key.startswith('doc:') else key}", e["place_id"], cc, u, e.get("source_policy"),
                   [("live", u)], ocr_done_key=sha1(u)[:20])

AFME_SLIM_STATS = Counter()
def _afme_lane_pdf_keys():
    """(place_id, doc_id) that load_afme_lane would yield (content_complete=false + .pdf URL) -> slim rows defer to it."""
    ks = set()
    for f in sorted(glob.glob(str(WL / "out/afme/*/[!_]*.jsonl"))):
        if "/_" in f: continue
        for r in jl(f):
            if r.get("content_complete") is not False: continue
            urls = [r.get("source_url"), r.get("original_url"), (r.get("extra_metadata") or {}).get("pdf_url")]
            if any(u and re.search(r"\.pdf($|[?#])", u, re.I) for u in urls): ks.add((r.get("place_id"), r.get("doc_id")))
    return ks

def _afme_slim(rows, full_keys):
    """2026-10-18: slim pointer rows (cc, place_key, doc_id, pdf_url, file; no place_id). place_id from place_key (as
    load_states), cc -> country_code, pdf_url -> source_url; PDF-like because the lane put it in pdf_url (the %PDF- header
    + content-type checks still apply). Lane-file row (file=) supplies source_policy/platform/archive when present.
    Keyed on (place_key, doc_id); deduped vs full queue rows, afme_lane, done.txt (afme|/afme_lane|) and fetched.jsonl."""
    AFME_SLIM_STATS.clear()
    if not rows: return
    lane_keys = _afme_lane_pdf_keys()
    done = set((STATE / "done.txt").read_text().split("\n")) if (STATE / "done.txt").exists() else set()
    led, urls = pair_exclusions(); seen = set(); mirrors = {}
    for e in rows:
        pk, did, u = e.get("place_key"), e.get("doc_id"), e.get("pdf_url")
        if not pk or not did or not u or (pk, did) in seen: continue
        seen.add((pk, did)); AFME_SLIM_STATS["slim_unique"] += 1
        pid = pid_of_pk(pk)
        if not pid: AFME_SLIM_STATS["bad_place_key"] += 1; continue
        k = (pid, did)
        if k in full_keys: AFME_SLIM_STATS["dup_queue_full_row"] += 1; continue
        if k in lane_keys: AFME_SLIM_STATS["dup_afme_lane"] += 1; continue
        if f"afme|{pid}|{did}" in done or f"afme_lane|{pid}|{did}" in done or (pk, did) in led:
            AFME_SLIM_STATS["dup_done_ledger"] += 1; continue
        if u in urls: AFME_SLIM_STATS["dup_fetched"] += 1; continue
        m = {}
        f = e.get("file")
        if f and str(f).startswith(str(WL / "out/afme/")) and Path(f).exists():
            if f not in mirrors:
                mirrors[f] = {}
                for r in jl(f):
                    r.pop("text", None); r.pop("html", None); mirrors[f].setdefault((r.get("place_id"), r.get("doc_id")), r)
            m = mirrors[f].get(k) or {}
        full = dict(place_id=pid, doc_id=did, country_code=e.get("cc") or m.get("country_code"), source_url=u,
                    source_policy=m.get("source_policy"), source_platform=m.get("source_platform"),
                    original_url=m.get("original_url"), archive_url=m.get("archive_url"))
        if not full["country_code"]: AFME_SLIM_STATS["no_cc"] += 1; continue
        AFME_SLIM_STATS["queued"] += 1; afme_lane_keys.add(k)
        import ocr_afme as A
        yield item("afme", did, pid, full["country_code"], u, full["source_policy"], A.candidates(full, m or full),
                   archive=(m.get("extra_metadata") or {}).get("archive"), ocr_done_key=A.did_of(full), slim=True)

def load_afme():
    import ocr_afme as A
    allrows = jl_snapshot(SRC["afme"])
    rows = [e for e in allrows if e.get("place_id") and e.get("doc_id") and e.get("country_code") and e.get("source_url")]
    slim = [e for e in allrows if not e.get("place_id") and e.get("place_key") and e.get("pdf_url")]
    keys = {(e["place_id"], e["doc_id"]) for e in rows}
    mirror = A.load_mirror(keys); seen = set()
    for e in rows:
        k = (e["place_id"], e["doc_id"])
        if k in seen: continue
        pl = e.get("pdf_url_like")
        if pl is None:                                  # older queue format: URL heuristic
            pl = any(u and re.search(r"\.pdf($|[?#])", u, re.I) for u in (e.get("source_url"), e.get("pdf_url"), e.get("archive_url")))
        if not pl: continue                             # HTML/listing page: not queued, not marked done (a rebuild may add a PDF)
        seen.add(k); m = mirror.get(k) or e        # lane files wiped after the reboot -> the queue row carries archive_url/extra_metadata.archive
        yield item("afme", e["doc_id"], e["place_id"], e["country_code"], e["source_url"], e.get("source_policy"),
                   A.candidates(e, m), archive=(m.get("extra_metadata") or {}).get("archive"), ocr_done_key=A.did_of(e))
    afme_lane_keys.update(keys)
    yield from _afme_slim(slim, keys)

afme_lane_keys = set()
def load_afme_lane():
    import ocr_afme as A
    seen = set(afme_lane_keys)
    for f in sorted(glob.glob(str(WL / "out/afme/*/[!_]*.jsonl"))):
        if "/_" in f: continue
        for r in jl(f):
            if r.get("content_complete") is not False: continue
            k = (r.get("place_id"), r.get("doc_id"))
            if k in seen or not all(k): continue
            urls = [r.get("source_url"), r.get("original_url"), (r.get("extra_metadata") or {}).get("pdf_url")]
            if not any(u and re.search(r"\.pdf($|[?#])", u, re.I) for u in urls): continue
            seen.add(k)
            yield item("afme_lane", r["doc_id"], r["place_id"], r["country_code"], r["source_url"], r.get("source_policy"),
                       A.candidates(r, r), archive=(r.get("extra_metadata") or {}).get("archive"))

def load_sasia():
    seen = set()
    for p in SRC["sasia"]:
        for e in jl(p):
            if e["doc_id"] in seen: continue
            seen.add(e["doc_id"]); ar = e.get("archive_ref"); src = e.get("source")
            if src == "pravo_tatarstan_cc" or (ar and src == "egazette_in"):
                plan = [("cc", "https://data.commoncrawl.org/" + ar["warc_filename"])]
                pol = "archived_commoncrawl"
            else:
                plan = [("live", e["source_url"])]; pol = e.get("source_policy") or ("robots_allowed_rfc9309" if src == "ru_gosweb" else None)
            # TT issuer is only known after OCR -> stage under the republic (Normalizer 2026-10-14), flagged issuer_unresolved
            pid = "iso:RU-TA" if src == "pravo_tatarstan_cc" else e.get("place_id")
            yield item("sasia", e["doc_id"], pid, e.get("country_code") or e.get("country"), e["source_url"], pol, plan,
                       archive=ar, ocr_done_key=sha1(e["doc_id"])[:20], sub=src,
                       issuer_unresolved=(src == "pravo_tatarstan_cc"))

PH_GDRIVE_BLOCKED = WL / "staging/ph/_state/ocr_queue_gdrive_blocked.jsonl"
def load_ph():
    seen = {e["doc_id"] for e in jl(PH_GDRIVE_BLOCKED) if e.get("doc_id")} if PH_GDRIVE_BLOCKED.exists() else set()
    for e in jl(SRC["ph"]):
        if not e.get("doc_id") or e["doc_id"] in seen: continue
        seen.add(e["doc_id"])
        yield item("ph", e["doc_id"], e["place_key"], "PH", e["source_url"], e.get("source_policy"),
                   [("gdrive" if e.get("source_kind") == "gdrive" else "live", e["source_url"])], ocr_done_key=sha1(e["doc_id"])[:20])

def load_pk_sd():
    import pandas as pd
    p = next((x for x in SRC["pk_sd"] if Path(x).exists()), None)
    if not p: return
    d = pd.read_parquet(p, columns=["doc_id", "place_id", "source_url", "source_policy", "content_complete", "extra_metadata"])
    for r in d[d.content_complete == False].itertuples():  # noqa: E712
        em = r.extra_metadata; em = json.loads(em) if isinstance(em, str) else (em or {})
        pub = em.get("pub_id") or r.doc_id.split("sindhlaws-", 1)[-1]
        pol = r.source_policy if isinstance(r.source_policy, str) else None
        yield item("pk_sd", r.doc_id, r.place_id, "PK", r.source_url, pol,
                   [("live", f"https://www.sindhlaws.gov.pk/DownloadDocument.aspx?PubID={pub}&Lang=EN")], src_file=str(p))

NP_Q = WL / "staging/sasia_ru/_ocr/np_palika_notext.jsonl"
def load_sasia_np():
    """Nepal palika no-text/garbled PDFs. doc_id = np_palika.py: 'npgov:' + host + ':' + sha1(node)[:16], node = doc_page_url
    minus the site base. One doc can have up to 3 PDFs -> done key carries the PDF url hash; extra PDFs get pdf_file names.
    reason=bad_text_layer (garbled) is staged even though pdftotext finds characters."""
    if not NP_Q.exists(): return
    seen = set()
    for e in jl(NP_Q):
        pg, u = e.get("doc_page_url"), e.get("source_url")
        if not pg or not u or not e.get("place_id"): continue
        sp = urlparse(pg); base = f"{sp.scheme}://{sp.netloc}"; node = pg[len(base):]
        did = "npgov:" + sp.hostname + ":" + sha1(node)[:16]
        if (did, u) in seen: continue
        seen.add((did, u))
        yield item("sasia_np", did, e["place_id"], e.get("country") or "NP", u, e.get("source_policy"), [("live", u)],
                   key_extra=sha1(u)[:12], allow_text_layer=(e.get("reason") in ("bad_text_layer", "timeout")),
                   min_gap=10.0, derive_policy=True)

def load_my_kedah():
    """Kedah PBT (out/eap/MY, eap_my_kedah.py): rows content_complete=false, or scanned (pdftotext had no usable text, the lane
    OCR'd inline: 'ocr' set). doc_id/place_id as in the law rows. Scanned+OCR'd ones are queued in the already-OCR'd tier."""
    seen = set()
    for f in sorted(glob.glob(str(WL / "out/eap/MY/[!_]*.jsonl")), reverse=True):
        for r in jl(f):
            if r.get("country_code") != "MY" or r.get("source_platform") != "my_pbt_kedah": continue
            k = (r.get("place_id"), r.get("doc_id"))
            if k in seen or not all(k): continue
            inc = r.get("content_complete") is False
            if not (inc or r.get("ocr")) or not re.search(r"\.pdf($|[?#])", r.get("source_url") or "", re.I): continue
            seen.add(k)
            yield item("my_kedah", r["doc_id"], r["place_id"], "MY", r["source_url"], r.get("source_policy"),
                       [("live", r["source_url"])], ocr_text=bool(r.get("text")) and not inc)

def load_eap_odm():
    """Open Development Mekong scanned regulations (out/eap/{KH,LA,MM}/iso_*.eap-odm*.jsonl, .full batches, read-only):
    rows content_complete=false; PDF = pdf_url; doc_id/place_id/source_policy as in the law rows."""
    seen = set()
    for f in sorted(glob.glob(str(WL / "out/eap/[KLM][HAM]/iso_*.eap-odm*.jsonl")), reverse=True):
        if f.split("/")[-2] not in ("KH", "LA", "MM"): continue
        for r in jl(f):
            k = (r.get("place_id"), r.get("doc_id"))
            if r.get("content_complete") is not False or k in seen or not all(k) or not r.get("pdf_url"): continue
            seen.add(k)
            yield item("eap_odm", r["doc_id"], r["place_id"], r["country_code"], r["pdf_url"], r.get("source_policy"), [("live", r["pdf_url"])])

EAP_MAN = WL / "out/eap/_scanned_pdfs_manifest.jsonl"
def load_eap():
    """EAP scanned-PDF manifest (supersedes eap_odm + my_kedah). place_id = inverse of place_key (wd_Q1 -> wd:Q1,
    iso_KH-12 -> iso:KH-12), checked against schema.place_key. Rows with local_path (DBKL) are copied in after
    verifying %PDF- and sha256; the rest are fetched from source_url. ocr_done rows go in the last tier."""
    if not EAP_MAN.exists(): return
    seen = set()
    for r in jl(EAP_MAN):
        did, pk = r.get("doc_id"), r.get("place_key")
        if not did or not pk or did in seen: continue
        seen.add(did)
        pid = pk.replace("_", ":", 1) if pk.startswith(("wd_", "iso_")) else None
        if not pid or place_key(pid) != pk: continue
        plan = ([("local", r["local_path"])] if r.get("local_path") else []) + [("live", r["source_url"])]
        it = item("eap", did, pid, r["country_code"], r["source_url"], r.get("source_policy"), plan,
                  ocr_text=bool(r.get("ocr_done")), local_sha256=r.get("sha256"))
        it["place_key"] = pk
        yield it

SWEEP_Q = STATE / "sweep_20261017.jsonl"
SWEEP_FILES = [SWEEP_Q, STATE / "sweep_pl_20261017.jsonl"]   # + PL EU-lane failed acts (ocr/sweep_pl.py)
ARCH_HOSTS = ("web.archive.org", "archive.org", "arquivo.pt", "archive.ph", "data.commoncrawl.org")
def load_sweep():
    """Global sweep 2026-10-17 (ocr/sweep_local.py + sweep_hub.py + sweep_build.py): PDF-like docs whose law row has empty /
    near-empty text and that are not in state/pdf_ledger.jsonl, fetched.jsonl or done.txt. Append-only file; fields doc_id,
    place_id, place_key, country_code, source_url, lane='sweep' (+ fetch_url, archive_url, source_policy). Plan: fetch_url, then
    source_url, then the Wayback raw (id_) capture if the row has one; archive hosts get a 10 s gap."""
    seen = set()
    for e in (r for f in SWEEP_FILES if f.exists() for r in jl(f)):
        did, pid = e.get("doc_id"), e.get("place_id")
        if not did or not pid or did in seen or place_key(pid) != e.get("place_key"): continue
        if str(e.get("found_in") or "").startswith("staging/eu/_state/pl/"): continue   # PL: ocr_queue_pl.jsonl is authoritative
        seen.add(did); plan = []
        for u in (e.get("fetch_url"), e.get("source_url")):
            if u and u.startswith("http") and ("live", u) not in plan: plan.append(("live", u))
        au = e.get("archive_url")
        if au and "web.archive.org/web/" in au:
            au = re.sub(r"/web/(\d+)[a-z_]*/", r"/web/\1id_/", au, count=1)
            if ("live", au) not in plan: plan.append(("live", au))
        yield item("sweep", did, pid, e["country_code"], e["source_url"], e.get("source_policy"), plan,
                   derive_policy=True, min_gap=(10.0 if (urlparse(plan[0][1]).hostname or "").endswith(ARCH_HOSTS) else None),
                   max_attempts=e.get("max_attempts"))   # PL timeouts: 1 = exactly one retry, then gave_up

PL_ISSUE_TL_OK = {"scanned_act_pages", "scanned_issue", "garbled_text_layer", "text_layer_but_act_not_located_in_issue"}
PL_Q = WL / "staging/eu/_state/pl/ocr_queue_pl.jsonl"     # EU lane PL list (act_id, pdf_url, place_id, reason_class), read-only
GR_Q = WL / "staging/eu/_state/gr/failed.jsonl"           # EU lane Diavgeia scans (id=ADA, pdf_url, place_id, reason), growing, read-only
def load_sweep_eu():
    """Sweep lane, EU-lane inputs re-read at every 30-min re-read: Poland ocr_queue_pl.jsonl (doc_id = act_id = ELI;
    timeout_or_connection rows get max_attempts 1 = one retry, then gave_up) and Greece gr/failed.jsonl rows with
    reason no_text_layer (doc_id = 'gr_diavgeia:' + ADA, as gr_diavgeia.build). Rows without place_id are skipped; doc_ids
    already in state/pdf_ledger.jsonl, fetched.jsonl or done.txt (any lane) or at the attempt cap are not queued."""
    import sweep_common as SC
    led, fet, dn, capped = SC.load_exclusions(); excl = led | fet | dn | capped
    seen = set()
    if PL_Q.exists():
        for e in jl(PL_Q):
            did, pid, u = e.get("act_id"), e.get("place_id"), e.get("pdf_url")
            if e.get("needs", "ocr") != "ocr": continue          # 2026-10-17 16:xx PT: unavailable / refetch are not ours
            if not did or not pid or not u or did in seen or did in excl: continue
            seen.add(did); rc = e.get("reason_class"); extra = {}; ik = None
            m = re.search(r"/GetActPdf\.ashx\?year=(\d+)&book=(\d+)&position=(\d+)", u)
            if m:                                                 # whole journal issue: bytes do not depend on position
                ik = f"{urlparse(u).hostname}|{m.group(1)}|{m.group(2)}"
                extra = {"issue_shared": True, "pdf_scope": e.get("pdf_scope") or "journal_issue", "act_position": int(m.group(3)),
                         "journal_year": int(m.group(1)), "journal_issue_nr": e.get("journal_issue_nr") or int(m.group(2)),
                         "pl_reason": rc, "pdf_url_old": e.get("pdf_url_old")}
            yield item("sweep", did, pid, "PL", u, None, [("live", u)], derive_policy=True,
                       max_attempts=(1 if rc == "timeout_or_connection" else None),
                       allow_text_layer=(rc in PL_ISSUE_TL_OK), issue_key=ik, extra_row=extra)
    if GR_Q.exists():
        for e in jl(GR_Q):
            if e.get("reason") != "no_text_layer" or not e.get("id") or not e.get("place_id") or not e.get("pdf_url"): continue
            did = "gr_diavgeia:" + e["id"]
            if did in seen or did in excl: continue
            seen.add(did)
            yield item("sweep", did, e["place_id"], "GR", e["pdf_url"], None, [("live", e["pdf_url"])], derive_policy=True)

AL_Q = WL / "staging/asia_latam/_scanned_pdfs_manifest.jsonl"   # Asia & LatAm bot (BR SAPL), append-only, read-only here
STATES_Q = WL / "staging/states/_scanned_pdfs_manifest.jsonl"    # States & Provinces bot (India Code, ID BPK, CA-NS ...), read-only
def pid_of_pk(pk):
    """Inverse of schema.place_key for the manifest's place_key: wd_Q1 -> wd:Q1, iso_CA-NS -> iso:CA-NS, 123 -> gnis:123."""
    if not pk: return None
    pid = pk.replace("_", ":", 1) if pk.startswith(("wd_", "iso_")) else (f"gnis:{pk}" if pk.isdigit() else None)
    return pid if pid and place_key(pid) == pk else None
_pair_ex = [None, 0.0]
def pair_exclusions():
    """(place_key, doc_id) pairs already in state/pdf_ledger.jsonl + URLs already fetched by any lane (fetched.jsonl has no
    place). Cached 10 min. doc_id alone is NOT unique (SAPL 'sapl-38' repeats across towns; SCHEMA.md: unique per place)."""
    if _pair_ex[0] is None or time.time() - _pair_ex[1] > 600:
        led, urls = set(), set()
        for r in jl(WL / "state/pdf_ledger.jsonl"): led.add((r.get("place_key"), r.get("doc_id")))
        for r in jl(LOGS / "fetched.jsonl"):
            if r.get("url"): urls.add(r["url"])
        _pair_ex[0], _pair_ex[1] = (led, urls), time.time()
    return _pair_ex[0]

def _scanned_manifest(path, lane, archive_first=False):
    """eap/asia_latam scanned-PDF manifest rows (doc_id, place_key, country_code, source_url, local_path, ocr_done,
    source_policy, law_file [+ archive_url / wayback_url / extra_metadata.archive]). Keyed on (place_key, doc_id)."""
    if not path.exists(): return                         # not created yet by its bot: fine, checked again at the next re-read
    led, urls = pair_exclusions(); seen = set()
    for r in jl(path):                                   # jl(): a partial last line (writer mid-append) is ignored
        did, pk, u = r.get("doc_id"), r.get("place_key"), r.get("source_url")
        if not did or not pk or not (u or r.get("local_path")) or (pk, did) in seen: continue
        seen.add((pk, did))
        pid = pid_of_pk(pk)
        if not pid or (pk, did) in led: continue
        em = r.get("extra_metadata") or {}
        if isinstance(em, str):
            try: em = json.loads(em)
            except ValueError: em = {}
        ar = em.get("archive") if isinstance(em, dict) else None
        au = r.get("archive_url") or r.get("wayback_url") or (ar.get("archive_url") or ar.get("url") if isinstance(ar, dict) else ar if isinstance(ar, str) else None)
        if au and "web.archive.org/web/" in au: au = re.sub(r"/web/(\d+)[a-z_]*/", r"/web/\1id_/", au, count=1)
        if (u and u in urls) or (au and au in urls): continue        # same PDF already staged by another lane
        plan = ([("local", r["local_path"])] if r.get("local_path") else [])
        if au and archive_first: plan.append(("archive", au))
        if u: plan.append(("live", u))
        if au and not archive_first: plan.append(("archive", au))
        it = item(lane, did, pid, r.get("country_code"), u or au, r.get("source_policy"), plan,
                  ocr_text=bool(r.get("ocr_done")), local_sha256=r.get("sha256"), archive_url=au,
                  extra_row=({"law_file": r["law_file"]} if r.get("law_file") else {}))
        it["place_key"] = pk
        yield it
def load_asia_latam(): yield from _scanned_manifest(AL_Q, "asia_latam")
def load_states(): yield from _scanned_manifest(STATES_Q, "states", archive_first=True)

UKIE_Q = WL / "staging/ukie/_state/needs_ocr/notext_urls.jsonl"  # UK & Ireland scraper, append-only, read-only here
UKIE_STATS = Counter()
def load_ukie():
    """Lane 'ukie': same line format as council_gb/notext_urls.jsonl (place_id, source_url, doc_key, ...) + the lane's own
    doc_id (ukpspo:/ukbyelaw:...), kept exactly (fallback = load_council's ukbyelaw:<key>). Keyed on (place_key, doc_id).
    Deduped against council_gb rows (URL / gb done key), done.txt (any lane, same place_id+doc_id) and fetched.jsonl (URL).
    Rows with archive_url (live site gone) try the archive copy first (archive rules), then live."""
    UKIE_STATS.clear()
    if not UKIE_Q.exists(): return
    gb_urls = {e.get("source_url") for e in jl(SRC["gb"])} if Path(SRC["gb"]).exists() else set()
    done_pairs, gb_keys = set(), set()
    for k in (STATE / "done.txt").read_text().split("\n") if (STATE / "done.txt").exists() else []:
        p3 = k.split("|", 3)
        if len(p3) >= 3:
            done_pairs.add((p3[1], p3[2]))
            if p3[0] == "gb": gb_keys.add((p3[1], p3[2]))
    led, urls = pair_exclusions(); seen = set()
    for e in jl(UKIE_Q):                                  # jl(): partial last line ignored
        u, pid = e.get("source_url"), e.get("place_id")
        if not u or not pid: continue
        key = e.get("doc_key") or ("doc:" + sha1(u)[:20])
        did = e.get("doc_id") or f"ukbyelaw:{key[4:] if key.startswith('doc:') else key}"
        pk = e.get("place_key") or place_key(pid)
        if (pk, did) in seen: continue
        seen.add((pk, did)); UKIE_STATS["unique"] += 1
        kid = f"ukbyelaw:{key[4:] if key.startswith('doc:') else key}"
        au = e.get("archive_url")
        if u in gb_urls or (e.get("original_url") or "") in gb_urls or (pid, kid) in gb_keys: UKIE_STATS["dup_gb"] += 1; continue
        if (pid, did) in done_pairs or (pk, did) in led: UKIE_STATS["dup_done_ledger"] += 1; continue
        if u in urls or (au and au in urls) or (e.get("original_url") or "") in urls: UKIE_STATS["dup_fetched"] += 1; continue
        if place_key(pid) != pk: UKIE_STATS["bad_place_key"] += 1; continue
        plan = ([("archive", au)] if au else []) + [("live", u)]
        UKIE_STATS["queued"] += 1
        yield item("ukie", did, pid, e.get("country_code") or "GB", u, e.get("source_policy"), plan,
                   archive_url=au, ocr_done_key=sha1(u)[:20])

def _chain_sweep():
    """One 'sweep' lane = sweep files + EU inputs; the first occurrence of a doc_id wins (EU inputs first: current URLs)."""
    seen = set()
    for it in list(load_sweep_eu()) + list(load_sweep()):
        if it["doc_id"] in seen: continue
        seen.add(it["doc_id"]); yield it

LOADERS = {"ro": lambda: load_council("ro"), "gb": lambda: load_council("gb"), "afme": load_afme,
           "afme_lane": load_afme_lane, "sasia": load_sasia, "ph": load_ph, "pk_sd": load_pk_sd,
           "sasia_np": load_sasia_np, "eap": load_eap, "sweep": lambda: _chain_sweep(),
           "asia_latam": load_asia_latam, "states": load_states, "ukie": load_ukie}
OLD_LOADERS = {"my_kedah": load_my_kedah, "eap_odm": load_eap_odm}   # superseded by 'eap' (kept for --lanes)

OCR = WL / "staging/ocr"
OCR_DONE = {"ro": "done.txt", "gb": "gb_done.txt", "afme": "afme_done.txt", "sasia": "sasia_done.txt", "ph": "ph_done.txt"}
OCR_SKIP = {"ro": "skipped.jsonl", "gb": "gb_skipped.jsonl.gz", "afme": "afme_skipped.jsonl", "sasia": "sasia_skipped.jsonl", "ph": "ph_skipped.jsonl"}
def ocr_texted():
    """Which items already have OCR text: staged in staging/ocr (any lane), or marked done by that lane's OCR script and never
    logged as skipped there (near_empty/low_conf/error/held docs count as NOT OCR'd). Returns (staged ids, staged pairs, lane done keys)."""
    import gzip
    ids, pairs = set(), set()
    for f in glob.glob(str(OCR / "*/[!.]*.jsonl")):
        for r in jl(f):
            if r.get("text"): ids.add(r["doc_id"]); pairs.add((r.get("place_id"), r["doc_id"]))
    lane_ok = {}
    for lane, fn in OCR_DONE.items():
        p = OCR / "_state" / fn
        done = set(p.read_text().split()) if p.exists() else set()
        sk = OCR / "_logs" / OCR_SKIP[lane]
        if sk.exists():
            op = gzip.open if sk.suffix == ".gz" else open
            with op(sk, "rt", encoding="utf-8") as f:
                for ln in f:
                    try: r = json.loads(ln)
                    except ValueError: continue
                    if lane in ("ro", "gb") and r.get("source_url"): done.discard(sha1(r["source_url"])[:20])
                    elif lane == "afme" and r.get("doc_id"): done.discard(sha1(f"{r.get('place_id')}|{r['doc_id']}")[:20])
                    elif r.get("doc_id"): done.discard(sha1(r["doc_id"])[:20])
        lane_ok[lane] = done
    return ids, pairs, lane_ok

# ---------------------------------------------------------------- HTTP
class HostGate:
    def __init__(self, gap=1.0): self.gap, self.next, self.lk, self.extra = gap, defaultdict(float), threading.Lock(), {}
    def __setitem__(self, host, gap): self.extra[host] = max(self.extra.get(host, 0), gap)
    def wait(self, host):
        with self.lk:
            t = max(time.time(), self.next[host]); self.next[host] = t + max(self.gap, self.extra.get(host, 0))
        time.sleep(max(0, t - time.time()))
    def penalize(self, host, secs):
        with self.lk: self.next[host] = max(self.next[host], time.time() + secs)
GATE = HostGate()
tl_lk = threading.Lock()
_tls = threading.local()
CA_PLUS = WL / "staging/eu/_state/pl_certs/ca_bundle_plus.pem"
def sess():
    if not hasattr(_tls, "s"):
        _tls.s = requests.Session(); _tls.s.headers["User-Agent"] = UA
        if CA_PLUS.exists(): _tls.s.verify = str(CA_PLUS)   # certifi + Certum intermediates (PL e-Dziennik hosts MP/LS/LD), read-only
    return _tls.s

def is_cf(r, head=b""):
    return (r.headers.get("cf-mitigated") == "challenge" or
            (r.status_code in (403, 503) and "cloudflare" in r.headers.get("server", "").lower()) or
            b"Just a moment" in head or b"challenge-platform" in head)

class Robots:
    def __init__(self, d): self.d = d; d.mkdir(parents=True, exist_ok=True); self.mem = {}; self.lk = defaultdict(threading.Lock)
    def _load(self, base, fresh=False):
        f = self.d / (re.sub(r"[^A-Za-z0-9.-]", "_", base) + ".json")
        if not fresh and base in self.mem: return self.mem[base]
        c = None
        if not fresh and f.exists():
            c = json.loads(f.read_text())
            if time.time() - c["t"] > 86400: c = None
        if c is None:
            st, txt = None, ""
            for a in range(3):
                GATE.wait(urlparse(base).hostname)
                try:
                    r = sess().get(base + "/robots.txt", timeout=(10, 30)); st = r.status_code
                    if st in (429,) or st >= 500: time.sleep(5 * 2 ** a); continue
                    txt = r.text if st == 200 else ""; break
                except requests.RequestException as x: st = f"err:{type(x).__name__}"; time.sleep(3 * 2 ** a)
            state = "ok" if st == 200 else ("allow_4xx" if isinstance(st, int) and 400 <= st < 500 else "unreachable")
            c = {"t": time.time(), "status": st, "state": state, "text": txt[:500000]}
            f.write_text(json.dumps(c))
        rp = urllib.robotparser.RobotFileParser(); rp.parse(c["text"].splitlines())
        self.mem[base] = (c, rp); return self.mem[base]
    def policy(self, url):
        p = urlparse(url); c = self.mem.get(f"{p.scheme}://{p.netloc}", ({},))[0]
        return {"ok": "robots_allowed_rfc9309", "allow_4xx": "robots_404_allow_rfc9309"}.get(c.get("state"))
    def check(self, url, fresh=False):
        """-> 'allowed' | 'disallowed' | 'unreachable'"""
        p = urlparse(url); base = f"{p.scheme}://{p.netloc}"
        with self.lk[base]:
            c, rp = self._load(base, fresh)
        if c["state"] == "ok":
            cd = rp.crawl_delay(UA_TOKEN) or rp.crawl_delay("*")
            if cd: GATE[p.hostname] = min(float(cd), 60.0)          # honour Crawl-delay (cap 60 s)
        if c["state"] == "unreachable": return "unreachable"
        if c["state"] == "allow_4xx": return "allowed"
        return "allowed" if (rp.can_fetch(UA_TOKEN, url) and rp.can_fetch(UA, url)) else "disallowed"
ROBOTS = None

def stream(url, dest, rng=None, expect_len=None):
    """GET url -> dest.part, enforcing 100 MB, PDF magic, no HTML/sign-in/CF. Returns (bytes, sha256, final_url)."""
    host = urlparse(url).hostname or ""; err = None
    for a in range(4):
        GATE.wait(host)
        try:
            r = sess().get(url, timeout=(15, 120), stream=True, allow_redirects=True, headers={"Range": rng} if rng else {})
        except (requests.ConnectionError, requests.Timeout) as x:
            err = f"{type(x).__name__}"; time.sleep(3 * 2 ** a); continue
        with r:
            fh = urlparse(r.url).hostname or ""
            if fh.endswith("accounts.google.com") or "ServiceLogin" in r.url: raise Skip("gdrive_signin", r.url[:200])
            it = r.iter_content(256 * 1024); first = next(it, b"") if r.status_code < 400 or r.status_code in (403, 503) else b""
            if is_cf(r, first[:4096]): raise Skip("blocked_cf", f"cloudflare {r.status_code}")
            if r.status_code == 429 or r.status_code >= 500:
                ra = r.headers.get("Retry-After", ""); w = int(ra) if ra.isdigit() else 10 * 2 ** a
                GATE.penalize(host, min(w, 600)); err = f"http {r.status_code}"; time.sleep(min(w, 120)); continue
            if r.status_code >= 400: raise Skip("http_error", f"http {r.status_code}")
            cl = r.headers.get("Content-Length")
            if cl and cl.isdigit() and int(cl) > MAX_BYTES and not rng: raise Skip("too_large", f"content-length {cl}")
            ct = r.headers.get("Content-Type", "").lower()
            if rng:          # commoncrawl WARC record (gzip member): bounded by warc_length
                buf = bytearray(first)
                for ch in it:
                    buf += ch
                    if len(buf) > MAX_BYTES + 65536: raise Skip("too_large", "warc record > 100 MB")
                return bytes(buf), None, r.url
            if not first.lstrip()[:5] == b"%PDF-":
                h = first[:4096].lower()
                if "drive.google.com" in fh or "docs.google.com" in fh: raise Skip("gdrive_signin", f"non-pdf drive response ct={ct}")
                raise Skip("html" if ("html" in ct or b"<html" in h or b"<!doctype" in h) else "not_pdf", f"ct={ct}")
            hs = hashlib.sha256(); n = 0; part = dest.with_name(dest.name + ".tmp")
            part.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(part, "wb") as f:
                    for ch in [first] + []: f.write(ch); hs.update(ch); n += len(ch)
                    for ch in it:
                        n += len(ch)
                        if n > MAX_BYTES: raise Skip("too_large", "stream > 100 MB")
                        f.write(ch); hs.update(ch)
                    f.flush(); os.fsync(f.fileno())
            except BaseException:
                part.unlink(missing_ok=True); raise
            return n, hs.hexdigest(), r.url
    raise Retry(f"fetch failed after retries: {err}")

def text_chars(path, pages=5):
    import subprocess
    try: out = subprocess.run(["pdftotext", "-l", str(pages), "-q", str(path), "-"], capture_output=True, timeout=120).stdout
    except Exception: return 0  # noqa
    return len(re.sub(rb"\s", b"", out))

def warc_pdf(raw):
    import gzip
    rec = gzip.decompress(raw); _, _, rest = rec.partition(b"\r\n\r\n"); hh, _, body = rest.partition(b"\r\n\r\n")
    if b"chunked" in hh.lower() and not body.lstrip()[:5] == b"%PDF-":
        out, b = bytearray(), body
        while b:
            l, _, b = b.partition(b"\r\n")
            try: n = int(l.split(b";")[0].strip() or b"0", 16)
            except ValueError: return body                 # not really chunked

            if n == 0: break
            out += b[:n]; b = b[n + 2:]
        body = bytes(out)
    return body.rstrip(b"\r\n") if not body.endswith(b"%%EOF") else body

def fetch(it, dest):
    """Try the item's plan in order. Returns dict(bytes, sha256, via, url)."""
    last = None
    for kind, url in it["plan"]:
        try:
            if kind == "local":
                lp = Path(url)
                if not lp.is_file(): last = Skip("local_missing", url); continue
                b = lp.read_bytes()
                if b[:5] != b"%PDF-": last = Skip("local_not_pdf", url); continue
                h = hashlib.sha256(b).hexdigest()
                if it.get("local_sha256") and h != it["local_sha256"]: last = Skip("local_sha256_mismatch", h); continue
                if len(b) > MAX_BYTES: raise Skip("too_large", f"local {len(b)}")
                dest.parent.mkdir(parents=True, exist_ok=True); part = dest.with_name(dest.name + ".tmp")
                with open(part, "wb") as f: f.write(b); f.flush(); os.fsync(f.fileno())
                return {"bytes": len(b), "sha256": h, "via": "local_copy", "url": it["source_url"]}
            if kind == "cc":
                ar = it.get("archive") or {}
                if not ar.get("warc_offset"): last = Skip("no_archive_ref", url); continue
                off, ln = int(ar["warc_offset"]), int(ar["warc_length"])
                if ln > MAX_BYTES + 65536: raise Skip("too_large", f"warc_length {ln}")
                raw, _, fu = stream(url, dest, rng=f"bytes={off}-{off + ln - 1}")
                b = warc_pdf(raw)
                if b.lstrip()[:5] != b"%PDF-":
                    raise Skip("html" if b"<html" in b[:4096].lower() else "not_pdf", "commoncrawl record")
                if len(b) > MAX_BYTES: raise Skip("too_large", "warc body > 100 MB")
                dest.parent.mkdir(parents=True, exist_ok=True); part = dest.with_name(dest.name + ".tmp")
                with open(part, "wb") as f: f.write(b); f.flush(); os.fsync(f.fileno())
                return {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(), "via": "commoncrawl", "url": url}
            if kind == "archive":                         # Wayback/archive copy: not robots-checked (archive rules), 1 req/s/host
                n, h, fu = stream(url, dest)
                return {"bytes": n, "sha256": h, "via": "archive", "url": fu}
            if kind == "wayback_lookup":
                raise Skip("blocked_cf", "cloudflare-blocked row (no bypass)")
            if kind in ("live", "gdrive"):
                rb = ROBOTS.check(url)
                if rb != "allowed": raise Skip("robots_" + rb, url[:200])
            n, h, fu = stream(url, dest)
            return {"bytes": n, "sha256": h, "via": kind, "url": fu}
        except Skip as s:
            last = s
            if s.reason in ("too_large", "gdrive_signin", "blocked_cf") or s.reason.startswith("robots_"): raise
    raise last or Skip("no_plan")

# ---------------------------------------------------------------- disk
def dir_bytes(p):
    t = 0; seen = set()
    for dp, _, fs in os.walk(p):
        for f in fs:
            try: st = os.lstat(os.path.join(dp, f))
            except FileNotFoundError: continue
            if (st.st_dev, st.st_ino) in seen: continue          # hard links (shared journal-issue PDFs) count once
            seen.add((st.st_dev, st.st_ino)); t += st.st_size
    return t
def free_bytes(): return shutil.disk_usage(str(WL)).free

# ---------------------------------------------------------------- main
def main():
    global ROBOTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--lanes", default=",".join(LOADERS)); ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--per-lane", type=int, default=0, help="test: take at most N items per lane")
    ap.add_argument("--max-batches", type=int, default=0, help="stop after sealing N batches this run")
    ap.add_argument("--batch-gb", type=float, default=2.0); ap.add_argument("--cap-gb", type=float, default=10.0)
    ap.add_argument("--min-free-gb", type=float, default=35.0); ap.add_argument("--poll", type=int, default=300)
    ap.add_argument("--count-only", action="store_true", help="print source/priority counts and exit")
    ap.add_argument("--max-attempts", type=int, default=5, help="temporary-error attempts before a row is done-skipped")
    ap.add_argument("--reread", type=int, default=1800, help="re-read the input queues every N s for new rows (0 = off)")
    a = ap.parse_args()
    for d in (MAN, STATE, LOGS): d.mkdir(parents=True, exist_ok=True)
    ROBOTS = Robots(STATE / "robots")
    evf = open(LOGS / "events.log", "a")
    def ev(m): evf.write(f"{utcnow()} {m}\n"); evf.flush()
    lk = threading.Lock(); donef = STATE / "done.txt"
    attf = STATE / "attempts.json"; attempts = json.loads(attf.read_text()) if attf.exists() else {}
    def save_attempts():
        t = attf.with_name(attf.name + ".tmp"); t.write_text(json.dumps(attempts)); os.replace(t, attf)
    done = set(donef.read_text().split("\n")) if donef.exists() else set()
    def mark(keys):
        with open(donef, "a") as f:
            for k in keys: f.write(k + "\n"); done.add(k)
    def key(it): return f"{it['lane']}|{it['place_id'] or ''}|{it['doc_id']}" + (f"|{it['key_extra']}" if it.get("key_extra") else "")

    # recover a batch left open by a crash (rows were fsynced): seal it as-is
    for t in sorted(MAN.glob("batch_*.jsonl.tmp")):
        rows = [r for r in jl(t) if (ROOT / (r.get("pdf_file") or f"{r['country_code']}/{r['place_key']}/{safe(r['doc_id'])}.pdf")).exists()]
        fin = t.with_name(t.name[:-4])
        with open(t.with_name(t.name + ".rec"), "w") as f:
            for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush(); os.fsync(f.fileno())
        os.rename(t.with_name(t.name + ".rec"), fin); t.unlink(); fin.with_suffix(".ready").write_text("")
        mark(f"{r['lane']}|{r['place_id'] or ''}|{r['doc_id']}" for r in rows); ev(f"recovered {fin.name} rows={len(rows)}")

    queued = set()
    def is_done(it):
        k = key(it)
        if k in done: return True
        if it["lane"] == "ph": return it["doc_id"] in ph_done_ids()
        if it["lane"] == "eap": return it["doc_id"] in eap_done_ids()          # PH queue regenerates: match by doc_id
        return False
    _phd = [None, -1]; _eapd = [None, -1]
    def eap_done_ids():
        if _eapd[1] != len(done):
            _eapd[0] = {k.split("|", 3)[2] for k in done if k.startswith(("eap|", "eap_odm|", "my_kedah|"))}; _eapd[1] = len(done)
        return _eapd[0]
    def ph_done_ids():
        if _phd[1] != len(done): _phd[0] = {k.split("|", 2)[2] for k in done if k.startswith("ph|")}; _phd[1] = len(done)
        return _phd[0]
    def load_all(first):
        texted_ids, texted_pairs, lane_ok = ocr_texted()
        counts, items = Counter(), []
        for lane in a.lanes.split(","):
            try: lane_items = list({**LOADERS, **OLD_LOADERS}[lane]())
            except FileNotFoundError as x:
                lane_items = []; counts[(lane, "missing")] = 1; ev(f"source {lane}: input missing ({x.filename}); skipped this read")
            for it in lane_items:
                counts[(lane, "rows")] += 1
                if is_done(it): counts[(lane, "done")] += 1; continue
                if key(it) in queued: counts[(lane, "inproc")] += 1; continue      # queued/handled earlier in this process
                it["ocrd"] = ((it["place_id"], it["doc_id"]) in texted_pairs or (it["place_id"] is None and it["doc_id"] in texted_ids)
                              or it.get("ocr_done_key") in lane_ok.get(lane, ()) or bool(it.get("ocr_text")))
                counts[(lane, "ocrd")] += it["ocrd"]; counts[(lane, "new")] += 1
                items.append(it)
        if a.per_lane and first:
            by = defaultdict(list)
            for it in items: by[it["lane"]].append(it)
            items = [it for v in by.values() for it in sorted(v, key=lambda i: i["ocrd"])[:a.per_lane]]
        for lane in a.lanes.split(","):
            msg = f"source {lane}: rows={counts[(lane,'rows')]} already_done={counts[(lane,'done')]} seen_this_run={counts[(lane,'inproc')]} newly_queued={counts[(lane,'new')]} already_ocr_text={counts[(lane,'ocrd')]}"
            print(msg, flush=True); ev(("load " if first else "reread ") + msg)
            if lane == "afme" and AFME_SLIM_STATS: ev(f"{'load' if first else 'reread'} afme slim {dict(AFME_SLIM_STATS)}")
            if lane == "ukie" and UKIE_STATS: ev(f"{'load' if first else 'reread'} ukie dedupe {dict(UKIE_STATS)}")
        def host_of(it): return urlparse(it["plan"][0][1] if it["plan"] else it["source_url"]).hostname or ""
        for tier in (False, True):   # no OCR text first; interleave hosts within a tier
            by = defaultdict(deque)
            for it in items:
                if it["ocrd"] == tier: by[(it["lane"], host_of(it))].append(it)
            qs = deque(by.values())
            while qs:
                q = qs.popleft(); x = q.popleft(); tiers[tier].append(x); queued.add(key(x))
                if q: qs.append(q)
        ev(f"{'load' if first else 'reread'} total newly_queued={len(items)} pending_in_queue={len(tiers[False]) + len(tiers[True])}")
        return len(items)
    tiers = {False: deque(), True: deque()}
    if a.count_only:
        load_all(True); return
    total = [load_all(True)]; last_read = [time.time()]
    ev(f"start items={total[0]} lanes={a.lanes} per_lane={a.per_lane}")
    import signal
    stop = threading.Event()
    def on_term(sig, frm): stop.set(); ev(f"signal {sig}: draining in-flight docs, sealing open batch, exiting")
    signal.signal(signal.SIGTERM, on_term); signal.signal(signal.SIGINT, on_term)

    nums = [int(m.group(1)) for p in MAN.glob("batch_*") if (m := re.match(r"batch_(\d{4})", p.name))]
    bn = [max(nums, default=0) + 1]; cur = {"rows": [], "keys": [], "bytes": 0, "f": None}; sealed = [0]; stats = Counter(); skipped_b = Counter()
    skipf = open(LOGS / "skipped.jsonl", "a", encoding="utf-8"); fetf = open(LOGS / "fetched.jsonl", "a", encoding="utf-8")
    reserved = [0]
    def open_batch():
        cur["f"] = open(MAN / f"batch_{bn[0]:04d}.jsonl.tmp", "a", encoding="utf-8")
    def seal():
        if not cur["rows"]: return
        cur["f"].flush(); os.fsync(cur["f"].fileno()); cur["f"].close()
        t = MAN / f"batch_{bn[0]:04d}.jsonl.tmp"; fin = MAN / f"batch_{bn[0]:04d}.jsonl"
        os.rename(t, fin)
        rd = MAN / f"batch_{bn[0]:04d}.ready"; rdt = rd.with_name(rd.name + ".tmp")
        ev(f"batch {fin.name} lanes={dict(Counter(r['lane'] for r in cur['rows']))}")
        rdt.write_text(""); os.rename(rdt, rd)        # empty marker, written LAST (PDF_STAGING.md §3)
        mark(cur["keys"])
        ev(f"sealed {fin.name} rows={len(cur['rows'])} bytes={cur['bytes']}"); sealed[0] += 1
        bn[0] += 1; cur.update(rows=[], keys=[], bytes=0, f=None)
    def skip(it, reason, detail="", terminal=True):
        stats["skip_" + reason] += 1; skipped_b[(it["lane"], reason)] += 1
        skipf.write(json.dumps({"ts": utcnow(), "lane": it["lane"], "doc_id": it["doc_id"], "place_id": it["place_id"],
                                "country_code": it["country_code"], "source_url": it["source_url"], "source_policy": it["source_policy"],
                                "reason": reason, "detail": str(detail)[:300], "terminal": terminal}, ensure_ascii=False) + "\n"); skipf.flush()
        if terminal: mark([key(it)])
    def space_ok():
        return dir_bytes(ROOT) + reserved[0] + MAX_BYTES <= a.cap_gb * 1e9 and free_bytes() - reserved[0] - MAX_BYTES >= a.min_free_gb * 1e9
    def wait_space():
        while not space_ok():
            with lk: seal()
            ev(f"PAUSE staging/pdf={dir_bytes(ROOT)/1e9:.2f}GB free={free_bytes()/1e9:.1f}GB; waiting for .pushed batches to be deleted")
            if stop.wait(a.poll): return False
        return True

    def job(it):
        pol = pols(it["source_policy"])
        if CF_POL in pol: return ("skip", "blocked_cf", "source_policy metadata_only_cloudflare_challenge")
        if not it["place_id"]: return ("skip", "no_place_id", "place known only after OCR (Tatarstan issuer); manifest needs place_id")
        if pol & ROBOTS_POL:
            live = ROBOTS.check(next((u for k, u in it["plan"] if k in ("live", "gdrive")), it["source_url"]), fresh=True)
            return ("skip", "policy_" + "_".join(sorted(pol & ROBOTS_POL)), f"live robots recheck: {live}")
        d = ROOT / (it["country_code"] or "XX") / it["place_key"]; nm = safe(it["doc_id"])
        with name_lk:
            if nm[:1] in "._" or len(nm.encode()) > 240 or (d / (nm + ".pdf")) in claimed or (d / (nm + ".pdf")).exists():
                nm = alt_name(it["doc_id"])
            dest = d / (nm + ".pdf"); claimed.add(dest)
        if it.get("min_gap"): GATE[urlparse(it["plan"][0][1]).hostname] = it["min_gap"]
        if it.get("issue_key"): return issue_job(it, dest)
        try: r = fetch(it, dest)
        except Skip as s: return ("skip", s.reason, s.detail)
        except Retry as x: return ("retry", "transient", str(x))
        except Exception as x: return ("retry", "error", repr(x)[:300])  # noqa
        tmp = dest.with_name(dest.name + ".tmp")
        ch = 0 if it.get("allow_text_layer") else text_chars(tmp)
        if ch >= 200:
            tmp.unlink(missing_ok=True)
            if it["lane"] == "pk_sd":
                with tl_lk, open(STATE / "text_layer_pk_sd.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"doc_id": it["doc_id"], "source_url": it["source_url"], "pdf_url": r["url"], "chars": ch}, ensure_ascii=False) + "\n")
            return ("skip", "has_text_layer", f"PDF has a usable text layer ({ch} chars, PDF_STAGING.md §1)")
        return ("ok", dest, r)

    ISS = STATE / "issue_cache"; ISS.mkdir(exist_ok=True)
    iss_lk = defaultdict(threading.Lock); iss_meta = {}      # issue_key -> (cache path, fetch result) | ("skip", reason, detail)
    def issue_job(it, dest):
        """Journal-issue PDF shared by many acts: download once per issue into _state/issue_cache (ignored by the uploader:
        no manifest line points there), then hard-link it as each act's own staged file. Skips are shared too."""
        ik = it["issue_key"]
        with iss_lk[ik]:
            m = iss_meta.get(ik)
            if m and m[0] == "skip": return m
            cp = ISS / (sha1(ik)[:20] + ".pdf")
            if not (m and cp.exists()):
                try: r = fetch(it, cp)                            # fetch writes <cp>.tmp
                except Skip as s:
                    iss_meta[ik] = ("skip", s.reason, s.detail); return iss_meta[ik]
                except Retry as x: return ("retry", "transient", str(x))
                except Exception as x: return ("retry", "error", repr(x)[:300])  # noqa
                os.replace(cp.with_name(cp.name + ".tmp"), cp)
                if not it.get("allow_text_layer"):
                    ch = text_chars(cp)
                    if ch >= 200:
                        cp.unlink(missing_ok=True)
                        iss_meta[ik] = ("skip", "has_text_layer", f"issue PDF has a usable text layer ({ch} chars, PDF_STAGING.md §1)")
                        return iss_meta[ik]
                iss_meta[ik] = (cp, r)
                with lk: stats["issue_downloads"] += 1
            else:
                with lk: stats["issue_reused"] += 1
            cp, r = iss_meta[ik]
            dest.parent.mkdir(parents=True, exist_ok=True); t = dest.with_name(dest.name + ".tmp")
            t.unlink(missing_ok=True); os.link(cp, t)
        return ("ok", dest, dict(r, via=r["via"] + "+issue_shared"))

    name_lk = threading.Lock(); claimed = set(); t0 = time.time(); lastp = [time.time()]
    ex = ThreadPoolExecutor(a.workers); futs = {}; qi = 0
    def submit():
        nonlocal qi
        while not stop.is_set() and (tiers[False] or tiers[True]) and len(futs) < a.workers * 2:
            if not wait_space(): return
            it = (tiers[False] or tiers[True]).popleft(); qi += 1
            futs[ex.submit(job, it)] = it
    try:
        submit()
        while futs:
            dn, _ = wait(list(futs), return_when=FIRST_COMPLETED)
            for fu in dn:
                it = futs.pop(fu); st, x, y = fu.result()
                with lk:
                    if st == "skip": skip(it, x, y)
                    elif st == "retry":
                        k = key(it); attempts[k] = attempts.get(k, 0) + 1; save_attempts()
                        if attempts[k] >= (it.get("max_attempts") or a.max_attempts): skip(it, "gave_up_" + x, f"{attempts[k]} attempts; last: {y}")
                        else: skip(it, x, y, terminal=False); queued.discard(k)          # retried at the next re-read
                    else:
                        dest, r = x, y
                        os.rename(dest.with_name(dest.name + ".tmp"), dest)
                        if cur["f"] is None: open_batch()
                        row = {"doc_id": it["doc_id"], "place_id": it["place_id"], "place_key": it["place_key"],
                               "country_code": it["country_code"], "source_url": r["url"], "sha256": r["sha256"],
                               "bytes": r["bytes"], "fetched_at": utcnow(), "source_policy": it["source_policy"], "lane": it["lane"]}
                        if dest.stem != safe(it["doc_id"]): row["pdf_file"] = str(dest.relative_to(ROOT))
                        if it.get("issuer_unresolved"): row["issuer_unresolved"] = True
                        if it.get("extra_row"): row.update(it["extra_row"])
                        if r.get("via") == "archive":
                            row["archive_url"] = r["url"]; row["archive_source"] = "wayback" if "web.archive.org" in r["url"] else "archive"
                            if not row["source_policy"]: row["source_policy"] = "live_unreachable_archive_fallback"
                        if row["source_policy"] is None and it.get("derive_policy"): row["source_policy"] = ROBOTS.policy(r["url"])
                        cur["f"].write(json.dumps(row, ensure_ascii=False) + "\n"); cur["f"].flush(); os.fsync(cur["f"].fileno())
                        cur["rows"].append(row); cur["keys"].append(key(it)); cur["bytes"] += r["bytes"]; stats["ok"] += 1; stats["bytes"] += r["bytes"]
                        fetf.write(json.dumps({"ts": row["fetched_at"], "lane": it["lane"], "doc_id": it["doc_id"], "via": r["via"], "url": r["url"]}, ensure_ascii=False) + "\n"); fetf.flush()
                        if cur["bytes"] >= a.batch_gb * 1e9: seal()
            if time.time() - lastp[0] >= 600:
                lastp[0] = time.time(); h = (time.time() - t0) / 3600
                ev(f"progress ok={stats['ok']} MB={stats['bytes']/1e6:.1f} MB/h={stats['bytes']/1e6/h:.1f} PDFs/h={stats['ok']/h:.1f} "
                   f"skips={sum(v for k, v in stats.items() if k.startswith('skip_'))} queue_pos={qi}/{total[0]} batch_open_MB={cur['bytes']/1e6:.1f}")
            if a.max_batches and sealed[0] >= a.max_batches: break
            if a.reread and not a.per_lane and time.time() - last_read[0] >= a.reread:
                last_read[0] = time.time(); total[0] += load_all(False)
            submit()
            while not futs and not stop.is_set() and a.reread and not a.per_lane and not a.max_batches:
                with lk: seal()                     # queue drained: seal what we have and keep polling the inputs
                for f in ISS.glob("*.pdf"): f.unlink(missing_ok=True)      # shared issue cache: staged copies are hard links
                for k in [k for k, v in iss_meta.items() if v[0] != "skip"]: iss_meta.pop(k, None)
                if stop.wait(a.reread): break
                last_read[0] = time.time(); total[0] += load_all(False); submit()
    finally:
        for fu in list(futs): fu.cancel()
        ex.shutdown(wait=True, cancel_futures=True)
        with lk: seal()
        summ = {"ts": utcnow(), **stats, "skips_by_lane": {f"{l}:{r}": n for (l, r), n in skipped_b.items()}}
        (LOGS / f"summary_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json").write_text(json.dumps(summ, indent=1))
        print(json.dumps(summ), flush=True)

if __name__ == "__main__":
    main()
