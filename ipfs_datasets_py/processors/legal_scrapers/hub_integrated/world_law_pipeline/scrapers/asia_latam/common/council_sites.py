#!/usr/bin/env python3
"""Generic official-council-website crawler for local laws / by-laws (AU-QLD local laws, ZA municipal by-laws).

Per council (official site from Wikidata P856 / candidate list):
  1. RFC 9309 robots per host (es_bop.Fetcher: identifying UA, >=1 s/host + Crawl-delay, every redirect hop re-checked;
     robots unreachable/5xx => skip & log).
  2. Find the local-law / by-law pages: links on the home page whose text/URL match TOPIC_RE, plus a few common paths.
     Breadth-first within the council's own registrable domain, max depth 2, max MAX_PAGES pages.
  3. Collect PDF/DOC(X) links whose link text or file name matches DOC_RE (and not EXCLUDE_RE), download, extract text
     (pdftotext / python-docx), stage one record per document.
Resumable: _state/<bot>/<qid>.json (per-council status + done URLs). One staged batch per council pass.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import hashlib, heapq, itertools, json, logging, os, re, subprocess, sys, tempfile, time, zipfile, io
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from bs4 import BeautifulSoup
HERE = Path(__file__).resolve().parent
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0, str(HERE.parent / "es")); sys.path.insert(0, str(HERE.parent))
import schema as S  # noqa: E402
from es_bop import Fetcher, Blocked, pdf_text  # noqa: E402

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam"))
log = logging.getLogger("council_sites")


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


MX_STATE_DOMS = {"aguascalientes", "bc", "bajacalifornia", "bcs", "campeche", "chiapas", "chihuahua", "coahuila", "colima",
                 "cdmx", "durango", "guanajuato", "guerrero", "hidalgo", "jalisco", "edomex", "michoacan", "morelos", "nayarit",
                 "nl", "oaxaca", "puebla", "queretaro", "qroo", "slp", "sinaloa", "sonora", "tabasco", "tamaulipas", "tlaxcala",
                 "veracruz", "yucatan", "zacatecas"}


def regdom(host):
    h = (host or "").lower().split(":")[0]
    if h.startswith("www."):
        h = h[4:]
    parts = h.split(".")
    # e.g. brisbane.qld.gov.au -> keep the council label + public suffix (gov.au, qld.gov.au, gov.za, org.za)
    if h.endswith(".gob.mx"):              # <muni>.<state>.gob.mx is a municipal site on a state-run domain
        lab = h[: -len(".gob.mx")].split(".")
        if len(lab) >= 2 and lab[-1] in MX_STATE_DOMS:
            return ".".join(lab[-2:]) + ".gob.mx"
    for suf in ("qld.gov.au", "gov.au", "com.au", "org.au", "net.au", "gov.za", "org.za", "co.za", "net.za",
                "gob.mx", "com.mx", "org.mx", "net.mx", "edu.mx"):
        if h.endswith("." + suf):
            lab = h[: -len(suf) - 1].split(".")[-1]
            return lab + "." + suf
    return ".".join(parts[-2:])


def docx_text(b):
    try:
        z = zipfile.ZipFile(io.BytesIO(b))
        x = z.read("word/document.xml").decode("utf-8", "replace")
        x = re.sub(r"</w:p>", "\n", x)
        return re.sub(r"<[^>]+>", "", x).strip()
    except Exception:  # noqa: BLE001
        return ""


class CouncilCrawler:
    def __init__(self, bot, cc, topic_re, doc_re, exclude_re, seed_paths, doc_type="ordinance", lang="en",
                 max_pages=40, max_docs=400, platform="council_site", strong_re=None):
        self.strong_re = strong_re or topic_re
        self.bot, self.cc = bot, cc
        self.OUT, self.QUAR, self.STATE = STAGE / cc, STAGE / "_quarantine" / cc, STAGE / "_state" / bot
        self.topic_re, self.doc_re, self.exclude_re = topic_re, doc_re, exclude_re
        self.seed_paths, self.doc_type, self.lang = seed_paths, doc_type, lang
        self.max_pages, self.max_docs, self.platform = max_pages, max_docs, platform

    def st_load(self, q):
        p = self.STATE / f"{q}.json"
        return json.loads(p.read_text()) if p.exists() else {"qid": q, "done": {}}

    def st_save(self, q, st):
        self.STATE.mkdir(parents=True, exist_ok=True)
        p = self.STATE / f"{q}.json"; t = self.STATE / f".{q}.json.tmp"; t.write_text(json.dumps(st, ensure_ascii=False)); os.replace(t, p)

    def flush(self, st, place, rows):
        if not rows:
            return
        pk = S.place_key(place["place_id"], None, self.cc)
        good = [r for r in rows if not S.validate_record(r)]
        bad = [r for r in rows if S.validate_record(r)]
        st["batch"] = st.get("batch", 0) + 1
        name = f"{pk}.{self.bot}-p{st['batch']:04d}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        if bad:
            self.QUAR.mkdir(parents=True, exist_ok=True)
            with open(self.QUAR / f"{name}.jsonl", "a") as q:
                for r in bad:
                    q.write(json.dumps({"reasons": S.validate_record(r), "record": r}, ensure_ascii=False) + "\n")
        if good:
            self.OUT.mkdir(parents=True, exist_ok=True)
            fin = self.OUT / f"{name}.jsonl"; tmp = self.OUT / f".{name}.tmp.jsonl"
            with tmp.open("w") as fh:
                for r in good:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                fh.flush(); os.fsync(fh.fileno())
            v = S.validate_file(tmp, expect_place_key=pk)
            if not v["ok"]:
                raise RuntimeError(f"validate_file {fin.name}: {v['errors'][:3]}")
            os.rename(tmp, fin)
            st["n_docs"] = st.get("n_docs", 0) + len(good)

    def discover(self, f, home):
        """Return {doc_url: link_text} found on local-law pages of this council site."""
        dom = regdom(urlparse(home).hostname)
        base = f"{urlparse(home).scheme}://{urlparse(home).netloc}"
        cnt = itertools.count()
        q = [(0, next(cnt), home, 0)] + [(1, next(cnt), base + p, 1) for p in self.seed_paths]
        heapq.heapify(q)
        seen, docs, pages = set(), {}, []
        while q and len(seen) < self.max_pages:
            prio, _, u, d = heapq.heappop(q)
            u = urldefrag(u)[0]
            if u in seen:
                continue
            seen.add(u)
            try:
                r = f.get(u)
            except Exception:  # noqa: BLE001  (Blocked / network) -- fatal only for the home page
                if d == 0:
                    raise
                continue
            if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                if d == 0:
                    raise IOError(f"home page HTTP {r.status_code}")
                continue
            final = r.url
            on_topic = d > 0 and (bool(self.strong_re.search(final)) or prio == 0)
            if on_topic:
                pages.append(final)
            soup = BeautifulSoup(r.content, "lxml")
            for a in soup.find_all("a", href=True):
                href = urljoin(final, a["href"].strip())
                if not href.startswith("http"):
                    continue
                txt = " ".join(a.get_text(" ", strip=True).split())[:200]
                hd = regdom(urlparse(href).hostname)
                path = urlparse(href).path.lower()
                is_doc = re.search(r"\.(pdf|docx?)$", path) or "/download" in path or "/file" in path or "documents" in path
                if is_doc and on_topic:
                    label = txt or Path(path).name
                    if self.doc_re.search(label + " " + Path(path).name.replace("-", " ").replace("_", " ")) and not self.exclude_re.search(label):
                        docs.setdefault(href, label)
                    continue
                if hd != dom or is_doc or href in seen:
                    continue
                if self.strong_re.search(txt) or self.strong_re.search(path):
                    if d < 3:
                        heapq.heappush(q, (0, next(cnt), href, d + 1))
                elif self.topic_re.search(txt) or self.topic_re.search(path):
                    if d < 1:
                        heapq.heappush(q, (2, next(cnt), href, d + 1))
        return docs, pages

    def run_place(self, place, a):
        q = place["qid"]
        st = self.st_load(q)
        retry = getattr(a, "retry_failed", False) and st.get("status") in ("blocked", "error")
        if st.get("status") in ("done", "blocked", "no_site") and not a.redo and not retry:
            return st
        if retry:
            st.pop("reason", None); st["errors"] = 0
        home = place.get("site")
        if not home:
            st.update(status="no_site"); self.st_save(q, st); return st
        first = [h.strip() for h in re.split(r"[,\s]+", home) if h.strip().startswith("http")][0]
        homes = [re.sub(r"^http://", "https://", first), re.sub(r"^https://", "http://", first)]
        home = homes[0]
        f = Fetcher(min_interval=a.interval)
        f.s.headers["Accept-Language"] = getattr(self, "accept_lang", "en;q=0.9")
        try:
            if "docs" not in st:
                for i, home in enumerate(homes):          # https first; plain http only if TLS/robots over https fails
                    try:
                        docs, pages = self.discover(f, home)
                        break
                    except Blocked as e:
                        if i == len(homes) - 1 or "unreachable" not in str(e):
                            raise
                st.update(docs=docs, pages=pages[:50], discovered=now_utc()); self.st_save(q, st)
                log.info("%s %s: %d local-law pages, %d candidate docs", q, place["name"], len(pages), len(docs))
            rows = []
            for u, label in list(st["docs"].items())[: self.max_docs]:
                if u in st["done"]:
                    continue
                try:
                    r = f.get(u)
                except Blocked as e:
                    st["done"][u] = "robots"; continue
                except Exception as e:  # noqa: BLE001
                    st["done"][u] = f"err {type(e).__name__}"; continue
                if r.status_code != 200:
                    st["done"][u] = f"http {r.status_code}"; continue
                b, ct = r.content, r.headers.get("content-type", "")
                if b[:4] == b"%PDF":
                    text, fmt = pdf_text(b), "pdf_text"
                elif b[:2] == b"PK":
                    text, fmt = docx_text(b), "docx_text"
                else:
                    st["done"][u] = f"not_doc {ct[:30]}"; continue
                if len(text) < 200:
                    st["done"][u] = "no_text"; continue
                title = re.split(r"\s*(?:\(|\[|\s)(?:PDF|DOCX?)\b|\s+\d+(?:\.\d+)?\s*[KM]B\b|\s+Last modified", label, flags=re.I)[0].strip(" -|•")
                if len(title) < 5:
                    title = Path(urlparse(u).path).name
                rec = {"place_id": place["place_id"], "country_code": self.cc, "doc_id": f"{self.bot}-" + hashlib.sha1(u.encode()).hexdigest()[:16],
                       "source_platform": self.platform, "source_url": r.url, "original_url": u, "doc_type": self.doc_type, "language": self.lang,
                       "html_title": title, "title_native": title, "consolidated": False, "content_format": fmt, "text": text,
                       "retrieved_at": now_utc(), "place_name": place["name"], "qid": q, "admin_level": "municipality",
                       "iso_3166_2": place.get("iso_3166_2"), "platform": self.platform, "platform_place_id": urlparse(home).netloc,
                       "text_source": fmt, "content_complete": True, "source_policy": "robots_allowed_rfc9309",
                       "content_sha256": hashlib.sha256(text.encode()).hexdigest()}
                rows.append({k: v for k, v in rec.items() if v not in (None, "")}); st["done"][u] = 1
                if len(rows) >= 25:
                    self.flush(st, place, rows); rows = []; self.st_save(q, st)
            self.flush(st, place, rows)
            st.update(status="done", finished=now_utc(), requests=f.nreq)
        except Blocked as e:
            st.update(status="blocked", reason=str(e))
        except Exception as e:  # noqa: BLE001
            st["errors"] = st.get("errors", 0) + 1
            st.update(status="error" if st["errors"] < 3 else "blocked", reason=f"{type(e).__name__}: {e}"[:300])
        self.st_save(q, st)
        log.info("%s %s status=%s docs=%s %s", q, place["name"], st.get("status"), st.get("n_docs", 0), st.get("reason", ""))
        return st
