#!/usr/bin/env python3
"""Crawler for non-US places whose official site was found by missing_urls_discover.py
(staging/web/_discovery/missing_urls_20261020.jsonl, status=found). Reuses fr_actes_crawler.py v0.2 (the generic
crawler re-parameterised exactly like it_bylaw_crawler.py / ca_bylaw_crawler.py): strict RFC 9309 robots via rfc9309.py
(2xx parse, 4xx allow, 5xx/unreachable disallow), Crawl-delay honoured (>=2 s, 1 in flight per host), per-place page/doc caps,
PDFs -> pdftotext. Multilingual keywords (fr/en/es/pt/ar). Every non-homepage URL is checked with
old_url_check.UrlChecker before it is fetched; covered URLs are skipped.
State/logs: staging/web/_missing/. Output: staging/web/<CC>/<place_key>.full.<UTC>.jsonl (one file per place_id).
Places ending robots_disallowed / unreachable are appended to _missing/_state/archive_queue.jsonl for
`--archive` mode (shared ArchiveFetcher, lane web, CC first then Wayback; source_policy=archived_robots_disallowed)."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import datetime as dt, importlib.util, json, os, re, sys, threading, time, urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("fr_base", HERE / "fr_actes_crawler.py")
base = importlib.util.module_from_spec(_spec); sys.modules["fr_base"] = base; _spec.loader.exec_module(base)
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/tools"))
from old_url_check import covered, UrlChecker  # noqa: E402,F401

WEB = Path(os.environ.get("MU_WEB", "/workspace/world_law/staging/web"))   # MU_* overrides are for tests only
OUT = WEB / "_missing"
DISC = Path(os.environ.get("MU_DISC", "/workspace/world_law/staging/web/_discovery/missing_urls_20261020.jsonl"))
AQ = OUT / "_state" / "archive_queue.jsonl"
_fold = base._fold
base.OUT = OUT
base.SOURCE_PLATFORM = "intl_municipal_web"
base.CRAWLER_VERSION = "missing_urls_crawler/0.1"
base.TMP_DIR = OUT / "_tmp"
base.MAX_DEPTH = 3
base.MAX_REQUESTS_PER_PLACE = int(os.environ.get("MU_MAX_REQ", "150"))
base.MAX_DOCS_PER_PLACE = 100
base.PLACE_TIME_BUDGET = 25 * 60
base.USER_AGENT = (f"{base.UA_TOKEN}/0.2 (+https://github.com/endomorphosis/ipfs_datasets_py; research crawler collecting "
                   "public municipal law (bylaws, arretes, deliberations, ordenanzas, decrets, gazettes); respects robots.txt "
                   "and Crawl-delay; 1 request per host every >=2s)")
base.SECTION_RE = re.compile(
    r"by-?laws?|ordinances?|regulations?|legislation|gazette|notices|acts|statutory|council resolutions?|minutes|"
    r"arretes?|deliberations?|actes? administratifs?|reglements?|decrets?|journal officiel|textes? (officiels|juridiques)|"
    r"ordenanzas?|decretos?|resoluciones?|normativa|digesto|boletin oficial|reglamentos?|"
    r"leis?|posturas|editais|boletim oficial|qararat|qawanin|marasim|documents|publications|downloads|resources")
base.DOC_RE = re.compile(
    r"by-?law|ordinance|regulation|act\b|statutory instrument|gazette|notice|resolution|"
    r"arrete|deliberation|reglement|decret|decision|"
    r"ordenanza|decreto|resolucion|reglamento|digesto|"
    r"\blei\b|postura|edital|portaria")
base.NAV_RE = re.compile(r"council|government|administration|mairie|commune|municipal|intendencia|gobierno|"
                         r"documents|publications|services|about|governance|legal|transparen")
base.EXCLUDE_RE = re.compile(
    r"tender|bid|procurement|vacanc|job|career|recruit|event|news|press|gallery|photo|video|tourism|contact|login|"
    r"facebook|instagram|twitter|youtube|linkedin|whatsapp|cookie|privacy|/tag/|/category/|/author/|wp-json|/feed|"
    r"print=|share=|replytocom|ical|licitacion|llamado|concurso|noticias|agenda|eventos|appel d.offres|recrutement|"
    r"actualites|evenement")
base.GAZETTE_RE = re.compile(r"newsletter|magazine|bulletin municipal")
base.SKIP_HOST_RE = re.compile(
    r"(^|\.)(facebook\.com|instagram\.com|twitter\.com|x\.com|youtube\.com|(www|maps|docs|drive|play)\.google\.[a-z.]+|"
    r"linkedin\.com|wikipedia\.org|apple\.com|openstreetmap\.org|whatsapp\.com|telegram\.me|issuu\.com|scribd\.com)$")
base.TEMPLATES = [t for t in base.TEMPLATES if t[0] in ("wordpress", "joomla", "drupal", "typo3", "spip", "wix")]

_LANG = {"BF": "fr", "MR": "fr", "CF": "fr", "CG": "fr", "GA": "fr", "KM": "fr", "TD": "fr", "UY": "es", "TL": "pt",
         "ST": "pt", "GW": "pt", "YE": "ar", "KW": "ar", "EH": "ar", "SR": "nl", "AW": "nl", "CW": "nl", "SX": "nl", "TJ": "tg"}
TARGETS: dict[str, dict] = {}
_tl = threading.local()


def _checker():
    c = getattr(_tl, "c", None)
    if c is None:
        c = _tl.c = UrlChecker()
    return c


def detect_lang(t: dict, text: str) -> str:
    f = _fold(text[:5000])
    sc = {"fr": len(re.findall(r"\b(le|la|les|des|du|et|commune|arrete)\b", f)),
          "en": len(re.findall(r"\b(the|and|of|council|shall|by-law)\b", f)),
          "es": len(re.findall(r"\b(el|los|las|del|y|que|ordenanza)\b", f)),
          "pt": len(re.findall(r"\b(o|os|das|dos|e|que|municipio)\b", f))}
    if re.search(r"[\u0600-\u06ff]{20}", text[:5000]):
        return "ar"
    best = max(sc, key=sc.get)
    return best if sc[best] >= 5 else _LANG.get(t["country_code"], "en")


def guess_doc_type(s: str) -> str:
    s = _fold(s)
    if re.search(r"gazette|journal officiel|boletin oficial|boletim oficial", s): return "gazette_act"
    if re.search(r"by-?law|ordinance|ordenanza|arrete|postura", s): return "ordinance"
    if re.search(r"deliberation|resolution|resolucion|decision|decret|decreto|portaria", s): return "decision"
    if re.search(r"\bact\b|\blei\b|\bloi\b|statut", s): return "statute"
    return "regulation"


def to_schema_record(d: dict, order: int) -> dict:
    t = TARGETS.get(d["place_id"], {})
    txt = d.get("text") or ""
    return {"place_id": d["place_id"], "country_code": t.get("country_code"),
            "doc_id": base.stable_doc_id(d["requested_url"]), "doc_order": order,
            "source_platform": base.SOURCE_PLATFORM, "source_url": d["doc_url"],
            "doc_type": guess_doc_type((d.get("title") or "") + " " + d["doc_url"] + " " + txt[:1500]),
            "language": detect_lang(t, (d.get("title") or "") + "\n" + txt),
            "title_native": base._fr_title(d), "in_force": None, "consolidated": False,
            "content_format": "pdf_text" if d["content_type"] == "pdf" else "html",
            "text": txt, "retrieved_at": d.get("fetched_at") or base.now_iso(),
            "place_name": t.get("name"), "qid": t.get("qid"), "admin_level": t.get("admin_level") or "municipality",
            "platform": base.SOURCE_PLATFORM, "source_policy": "robots_allowed_rfc9309", "source_official": True,
            "homepage": t.get("homepage"), "discovery_source": t.get("disc_source"),
            "discovery_confidence": t.get("disc_conf"), "section_url": d.get("section_url"),
            "requested_url": d.get("requested_url"), "http_content_type": d.get("http_content_type"),
            "sha256": d.get("sha256"), "size_bytes": d.get("size_bytes"),
            "text_extraction": d.get("text_extraction"), "crawler": base.CRAWLER_VERSION}


def place_key(pid: str) -> str:
    return base.world_schema.place_key(pid, None, TARGETS.get(pid, {}).get("country_code"))


def load_targets() -> list[dict]:
    out, seen = [], set()
    if not DISC.exists():
        return out
    covered_hosts = {h for h in (os.environ.get("MU_SKIP_HOSTS") or "").split(",") if h}
    for line in DISC.open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("status") != "found" or r["place_id"] in seen or r["country_code"] in ("GB", "IE"):
            continue
        if r.get("confidence") not in ("high", "medium"):
            continue
        h = urllib.parse.urlsplit(r["url"]).netloc.lower()
        if h in covered_hosts:
            continue
        seen.add(r["place_id"])
        t = {"place_id": r["place_id"], "qid": r["qid"], "name": r["name"], "country_code": r["country_code"],
             "homepage": r["url"], "source_url": r["url"], "population": r.get("population") or "",
             "insee_code": None, "code_links": [], "admin_level": r.get("admin_level"),
             "disc_source": r.get("source"), "disc_conf": r.get("confidence")}
        TARGETS[t["place_id"]] = t
        out.append(t)
    return out


_orig_fetch = base.PlaceCrawler.fetch


def _fetch(self, url: str) -> dict:
    if base.canon(url) != base.canon(self.t["homepage"]):
        try:
            cov = _checker().covered(url)
        except Exception:
            cov = None
        if cov:
            self.events["dedup_covered"] += 1
            return {"status": 0, "final_url": url, "content_type": "", "sha256": "", "path": "", "size": 0,
                    "fetched_at": base.now_iso(), "error": "dedup_covered", "body": b"", "cached": False, "not_fetched": True}
    return _orig_fetch(self, url)


_orig_add = base.PlaceCrawler.add_doc


def _add_doc(self, url, rec, title, ctype, text, via, extract_err="", template=""):
    return _orig_add(self, url, rec, title, ctype, text, via, extract_err, template)


class _Sink(base.DocSink):
    def __init__(self, out: Path, pk: str):
        super().__init__(out, pk)
        self.tmp = OUT / "_tmp" / f"{pk}.inprogress.jsonl.tmp"   # moved into staging/web/<CC>/ on finish


def _finish_place(self, t: dict, sink, res: dict) -> None:
    """base.Runner.finish_place, with the final file in staging/web/<CC>/ and all _state under _missing/_state."""
    cc = t["country_code"]
    ccdir = WEB / cc
    pk = place_key(t["place_id"])
    res.update(docs_found=sink.found, docs=sink.rows, pdf_docs=sink.pdf, html_docs=sink.html,
               dropped_rows=dict(sink.dropped), country_code=cc, homepage=t["homepage"])
    if not sink.rows and res.get("status") == "ok":
        res["status"] = "docs_without_text"
    if sink.scanned:
        with self.lock, (self.out / "_state" / "scanned_pdfs_need_ocr.jsonl").open("a", encoding="utf-8") as fh:
            for d in sink.scanned:
                fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    res["pdf_no_text"] = len(sink.scanned)
    res["file"] = ""
    if sink.rows:
        sink.close()
        ccdir.mkdir(parents=True, exist_ok=True)
        batch = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        final = ccdir / f"{pk}.full.{batch}.jsonl"
        tmp = ccdir / f"{final.name}.tmp"
        os.rename(sink.tmp, tmp)          # same filesystem; already fsynced
        sink.tmp = tmp
        chk = self.out / "_state" / "validate" / final.name
        chk.parent.mkdir(parents=True, exist_ok=True)
        chk.unlink(missing_ok=True)
        os.link(tmp, chk)
        v = base.world_schema.validate_file(chk, expect_place_key=pk)
        chk.unlink(missing_ok=True)
        if v["ok"]:
            os.rename(tmp, final)
            res["file"] = str(final)
        else:
            res["status"] = "validation_failed"
            res["validation_errors"] = [str(e) for e in v["errors"][:5]]
            bad = self.out / "_state" / "invalid" / final.name
            bad.parent.mkdir(parents=True, exist_ok=True)
            os.rename(tmp, bad)
    else:
        sink.abort()
    sdir = self.out / "_state" / "places"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / f"{pk}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    with self.lock:
        with self.results_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(res, ensure_ascii=False) + "\n")
        with self.done_path.open("a") as fh:
            fh.write(t["place_id"] + "\n")
        self.done.add(t["place_id"])
        self._agg_add(self.agg, res)
        self.session_done += 1
    st = res.get("status", "")
    errs = " ".join(res.get("first_errors") or [])
    if not res.get("docs") and re.search(r"robots|unreachable|host_dead|timeout|connect", st + " " + errs):
        with self.lock, AQ.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"place_id": t["place_id"], "country_code": cc, "name": t["name"], "qid": t["qid"],
                                 "homepage": t["homepage"], "status": st, "admin_level": t.get("admin_level"),
                                 "queued_at": base.now_iso()}, ensure_ascii=False) + "\n")


_orig_wp = base.Runner.write_progress


def _write_progress(self, total, final=False):
    _orig_wp(self, total, final)
    p = json.loads(self.progress_path.read_text())
    p["country_code"] = "multi"
    p["discovery_lines"] = sum(1 for _ in DISC.open()) if DISC.exists() else 0
    disc_done = False
    try:
        disc_done = any("DISCOVERY_DONE" in f.read_text(errors="ignore") for f in (OUT / "_logs").glob("discover_*.log"))
    except Exception:
        pass
    p["discovery_finished"] = disc_done
    p["finished"] = bool(final and disc_done)
    tmp = self.progress_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(p, indent=2, ensure_ascii=False)); tmp.replace(self.progress_path)


# ------------------------------------------------------------------ archive fallback
LAW_URL_RE = re.compile(r"(?i)(by-?law|ordinance|regulation|gazette|arr[eê]t[eé]|d[eé]lib[eé]ration|r[eè]glement|d[eé]cret|"
                        r"ordenanza|decreto|resoluci[oó]n|reglamento|digesto|boletin|journal[-_]?officiel|legislation|\.pdf$)")
BAD_URL_RE = re.compile(r"(?i)(tender|vacanc|job|news|event|gallery|wp-json|/feed|\.(jpe?g|png|gif|css|js|ico|svg)$)")


def archive_main():
    os.environ.setdefault("ARCHIVE_LANE", "web")
    sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
    from archive import ArchiveFetcher, ArchiveTransient, StagedWriter, provenance_fields
    from bs4 import BeautifulSoup
    import tempfile, subprocess
    done_p = OUT / "_state" / "archive_done.txt"
    done = set(done_p.read_text().split()) if done_p.exists() else set()
    if not AQ.exists():
        print("no archive queue"); return
    q, seen = [], set()
    for l in AQ.open():
        r = json.loads(l)
        if r["place_id"] not in done and r["place_id"] not in seen:
            seen.add(r["place_id"]); q.append(r)
    print(f"archive queue {len(q)}", flush=True)
    fx = ArchiveFetcher(lane="web", cc_crawls=4, cc_max_wait=30, raise_deferred=True)
    chk = UrlChecker()
    for r in q:
        host = urllib.parse.urlsplit(r["homepage"]).netloc.lower().removeprefix("www.")
        n_ok, deferred = 0, False
        try:
            caps = fx.list_captures(host, "domain", newest_per_url=True)
        except ArchiveTransient as e:
            print(f"defer {r['place_id']} {host}: {e}", flush=True); continue
        if getattr(caps, "truncated", False):
            deferred = True
        cands = [c for c in caps if LAW_URL_RE.search(c.original_url) and not BAD_URL_RE.search(c.original_url)]
        w = StagedWriter(WEB, r["country_code"], r["place_id"], batch_prefix="archive", chunk=200)
        ids = set()
        for c in cands[:60]:
            if n_ok >= 40:
                break
            if chk.covered(c.original_url):
                continue
            try:
                doc = fx.fetch_best([c], max_tries=1)
            except ArchiveTransient:
                deferred = True; break
            if doc is None or not doc.body:
                continue
            ct = (doc.content_type or "").lower()
            if "pdf" in ct or doc.body[:5] == b"%PDF-":
                with tempfile.NamedTemporaryFile(suffix=".pdf", dir=OUT / "_tmp", delete=True) as tf:
                    tf.write(doc.body); tf.flush()
                    try:
                        text = subprocess.run(["pdftotext", "-layout", tf.name, "-"], capture_output=True, timeout=120).stdout.decode("utf-8", "replace")
                    except Exception:
                        text = ""
                fmt = "pdf_text"; title = urllib.parse.unquote(c.original_url.rsplit("/", 1)[-1])
            elif "html" in ct:
                soup = BeautifulSoup(doc.text(), "html.parser")
                title = (soup.title.get_text(" ", strip=True) if soup.title else "") or c.original_url
                text = base.html_main_text(soup); fmt = "html"
            else:
                continue
            text = (text or "").strip()
            if len(text) < 300:
                continue
            did = base.stable_doc_id(c.original_url)
            if did in ids:
                continue
            ids.add(did)
            t = {"country_code": r["country_code"]}
            rec = {"place_id": r["place_id"], "country_code": r["country_code"], "doc_id": did,
                   "source_platform": base.SOURCE_PLATFORM, "source_url": c.original_url,
                   "doc_type": guess_doc_type(title + " " + c.original_url + " " + text[:1500]),
                   "language": detect_lang(t, title + "\n" + text), "title_native": title[:500],
                   "consolidated": False, "content_format": fmt, "text": text[:base.MAX_TEXT_CHARS],
                   "retrieved_at": base.now_iso(), "place_name": r["name"], "qid": r["qid"],
                   "admin_level": r.get("admin_level") or "municipality", "source_official": True,
                   "crawler": base.CRAWLER_VERSION + "+archive",
                   **provenance_fields(doc, source_policy="archived_robots_disallowed", robots_basis=r["status"])}
            if not w.add(rec):
                n_ok += 1
        w.flush()
        print(f"{r['place_id']} {host} caps={len(caps)} cands={len(cands)} docs={n_ok} deferred={deferred}", flush=True)
        if not deferred:
            with done_p.open("a") as fh:
                fh.write(r["place_id"] + "\n")
    print("ARCHIVE_PASS_DONE", flush=True)


base.guess_doc_type = guess_doc_type
base.to_schema_record = to_schema_record
base.load_targets = load_targets
base.place_key = place_key
base.DocSink = _Sink
base.PlaceCrawler.fetch = _fetch
base.PlaceCrawler.add_doc = _add_doc
base.Runner.finish_place = _finish_place
base.Runner.write_progress = _write_progress

if __name__ == "__main__":
    if "--archive" in sys.argv:
        archive_main(); sys.exit(0)
    if "--out" not in sys.argv:
        sys.argv += ["--out", str(OUT)]
    base.main()
