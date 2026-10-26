#!/usr/bin/env python3
"""Polite, bounded crawler for French municipal acts (recueil des actes administratifs, arretes,
deliberations, reglements). Derived from de_ortsrecht_crawler.py (same architecture and limits).

Targets: FR rows with source_url in global_municipalities_candidate.csv (+ code_hosts/FR.jsonl links,
INSEE code from pipeline/codes/place_codes.parquet via _state/insee_map.json).

(Original DE notes follow.)

Seeds: ipfs_datasets_py .../municipal/seeds/code_hosts/DE.jsonl (known bylaw links
from code_links.py homepage scan), joined to place_id via the global candidate CSV.

Per place:
  1. Template detection (vendor/CMS) -> host-specific hints (skip gazette/RIS/juris).
  2. Bounded best-first crawl from the known Satzung/Ortsrecht links (or the homepage
     when none are known) to find the section and its legal documents.
  3. Download HTML / PDF documents, extract text (pdftotext), write JSONL.

Politeness: robots.txt (strict; 401/403/5xx/unreachable => disallow), Crawl-delay,
>= 2 s between requests per host, 1 request in flight per host, descriptive UA,
<= 200 requests per place, depth <= 3. Shared fetch cache (sqlite + content-addressed
raw store) so Amt / Verbandsgemeinde sites shared by many members are fetched once.

Output (only): /workspace/world_law/staging/web/DE/
  places/<place_key>/documents.jsonl   one record per document
  _raw/<sha[:2]>/<sha>.<ext>           raw bytes (content addressed)
  _state/done_place_ids.txt            resumability
  _state/place_results.jsonl           one summary row per finished place
  _state/fetch_cache.sqlite            URL fetch cache
  _progress.json                       per-country progress
  _logs/                               logs
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import argparse
import gc
import csv
import datetime as dt
import gzip
import hashlib
import heapq
import importlib.util
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse

from collections import Counter, OrderedDict, defaultdict, deque
from pathlib import Path

import requests
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rfc9309 import Robots  # noqa: E402  (vendored from scrapers/asia_latam/common/rfc9309.py)
ROBOTS_DIR: "Path | None" = None
from bs4 import BeautifulSoup

import warnings
warnings.filterwarnings("ignore")
try:
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except Exception:
    pass

REPO = Path("/workspace/ipfs_datasets_py")
if Path("/workspace/ipfs_datasets_py_latest/ipfs_datasets_py/processors/legal_scrapers/municipal/code_links.py").is_file():
    REPO = Path("/workspace/ipfs_datasets_py_latest")
MUNI = REPO / "ipfs_datasets_py/processors/legal_scrapers/municipal"
SEED_FILE = MUNI / "seeds/code_hosts/FR.jsonl"
CANDIDATES = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
OUT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/web/FR"))
SCHEMA = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/SCHEMA.md"))
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
import schema as world_schema  # noqa: E402  (place_key, validate_file, validate_record)
SOURCE_PLATFORM = "fr_municipal_web"

# Reuse code_links.py without importing the heavy package __init__.
_spec = importlib.util.spec_from_file_location("_code_links", MUNI / "code_links.py")
code_links = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(code_links)  # type: ignore[union-attr]
_fold = code_links._fold
vendor_for_host = code_links.vendor_for_host
host_of = code_links.host_of

CRAWLER_VERSION = "fr_actes_crawler/0.2"
UA_TOKEN = "WorldLawMunicipalBot"
USER_AGENT = (
    f"{UA_TOKEN}/0.2 (+https://github.com/endomorphosis/ipfs_datasets_py; "
    "research crawler collecting public municipal acts (actes administratifs, arretes, deliberations); "
    "respects robots.txt and Crawl-delay; 1 request per host every >=2s)"
)

MIN_DELAY = 2.0
MAX_CRAWL_DELAY = 30.0       # hosts asking for more are skipped (too slow to be bounded)
MAX_REQUESTS_PER_PLACE = 200
MAX_DEPTH = 3
MAX_DOCS_PER_PLACE = 150
MAX_PDF_BYTES = 25_000_000
MAX_HTML_BYTES = 2_000_000
TIMEOUT = (5, 20)            # connect fail-fast; read timeout per socket op
PLACE_TIME_BUDGET = 30 * 60  # seconds
MAX_TEXT_CHARS = 1_000_000
TMP_DIR = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/web/FR/_tmp"))
ROBOTS_LRU = 2000
MAX_FRONTIER = 2500
REQUEST_DEADLINE = 90  # seconds for a whole response body (slow-drip guard)
HOST_DEAD_AFTER = 3     # consecutive connect/timeout/ssl failures => host skipped for this process
UNPRODUCTIVE_STREAK = 80  # stop a place after N fetches in a row with no new doc/section (once >=1 doc found)
STORE_RAW = False       # never keep raw bytes: PDFs are streamed to _tmp, text extracted, temp deleted

# ---------------------------------------------------------------- keywords
SECTION_RE = re.compile(
    r"recueil|actes? administratifs?|actes-administratifs|actes reglementaires|actes-reglementaires|"
    r"publication des actes|publication-des-actes|arretes|arrete|deliberations?|reglements?|"
    r"actes? de la commune|actes-de-la|registre des actes|affichage legal|affichage-legal|"
    r"documents officiels|documents-officiels|actes officiels|publications? legales?|raa\b"
)
DOC_RE = re.compile(
    r"arrete|deliberation|reglement|recueil|actes? administratif|\braa\b|decision|"
    r"proces[- ]verbal|compte[- ]rendu|police|statuts?|tarif|redevance|taxe"
)
NAV_RE = re.compile(
    r"mairie|municipal|municipalite|conseil|vie-locale|vie locale|ma-commune|la-commune|votre-commune|"
    r"administration|publications?|documents?|demarches|informations|commune|ville|services"
)
EXCLUDE_RE = re.compile(
    r"offres? d.emploi|recrutement|emploi|marches? publics?|appels? d.offres|agenda|evenement|"
    r"manifestation|fete|formulaire|cerfa|mentions? legales|donnees personnelles|rgpd|cookies?|"
    r"accessibilite|contact|/contact|facebook|instagram|twitter|youtube|linkedin|whatsapp|"
    r"connexion|login|se connecter|newsletter|presse|tourisme|hebergement|restaurant|camping|"
    r"plan du site|plan-du-site|galerie|photos?|videos?|meteo|webcam|plan de la ville|"
    r"elections?|menus?|cantine|annuaire|petites annonces|associations?|panier|"
    r"/search|recherche|\?q=|lang=en|/en/|"
    r"actualites?|/news|/blog|/tag/|/tags/|/category/|/categorie/|/author/|/auteur/|wp-json|/feed|"
    r"imprimer|print=|partager|share=|replytocom|calendrier|ical|/event"
)
GAZETTE_RE = re.compile(r"bulletin municipal|bulletin-municipal|magazine|journal municipal|lettre d.information|gazette|\bbm ?\d|flash info|echo de")
NONDOC_EXT = re.compile(r"\.(jpe?g|png|gif|svg|webp|mp4|mp3|zip|rar|7z|exe|css|js|ico|woff2?|ttf|xml|rss|ics|vcf|tif?f|dwg|kml|gpx)(\?|$)", re.I)
DOC_EXT = re.compile(r"\.pdf(\?|$|#)", re.I)
DOWNLOAD_HINT = re.compile(r"telecharg|/wp-content/uploads/|/medias?/|/fichiers?/|/documents?/|/upload|download|/output/download\.php|fileadmin|/media/|/files?/|getfile|/dokumente?/|/datei|blob=publicationfile|/uploads/", re.I)

# Hosts/vendors handled specially (template detection).
SKIP_HOST_RE = re.compile(
    r"(^|\.)(facebook\.com|instagram\.com|twitter\.com|x\.com|youtube\.com|(www|maps|docs|drive|play)\.google\.[a-z.]+|"
    r"legifrance\.gouv\.fr|linkedin\.com|wikipedia\.org|apple\.com|openstreetmap\.org|panneaupocket\.com|"
    r"intramuros\.org|illiwap\.com|tripadvisor\.[a-z.]+|booking\.com|calameo\.com|issuu\.com|yumpu\.com)$"
)
TEMPLATES = [
    # (name, host regex, html regex, hints)  -- French municipal CMS / vendors
    ("intramuros", re.compile(r"intramuros\.org$"), None, {"skip": True}),
    ("panneaupocket", re.compile(r"panneaupocket\.com$"), None, {"skip": True}),
    ("legifrance", re.compile(r"legifrance\.gouv\.fr$"), None, {"skip": True}),
    ("lapagelocale", re.compile(r"lapagelocale\.fr$"), None, {}),
    ("campagnol", re.compile(r"campagnol\.fr$"), re.compile(r"campagnol", re.I), {}),
    ("e_monsite", re.compile(r"e-monsite\.com$"), re.compile(r"e-monsite\.com|emonsite", re.I), {}),
    ("google_sites", re.compile(r"^sites\.google\.com$"), None, {}),
    ("pagesperso_orange", re.compile(r"pagesperso-orange\.fr$"), None, {}),
    ("stratis", None, re.compile(r"stratis|/typo3conf/ext/stratis", re.I), {}),
    ("inovagora", None, re.compile(r"inovagora", re.I), {}),
    ("kosmos", None, re.compile(r"kosmos|kportal|/kportal/", re.I), {}),
    ("ametys", None, re.compile(r"ametys", re.I), {}),
    ("jalios", None, re.compile(r"jalios|/jcms/", re.I), {}),
    ("neopse_localeo", None, re.compile(r"neopse|localeo|e-magnus", re.I), {}),
    ("alkante_cmonsite", None, re.compile(r"cmonsite|alkante", re.I), {}),
    ("wix", None, re.compile(r"wixstatic|_wixCssImports|wix\.com", re.I), {}),
    ("jimdo", None, re.compile(r"jimdo", re.I), {}),
    ("site_w", None, re.compile(r"site-w\.com|sitew", re.I), {}),
    ("wordpress", None, re.compile(r"/wp-content/|/wp-includes/", re.I), {}),
    ("joomla", None, re.compile(r"/media/jui/|Joomla|/media/system/js/", re.I), {}),
    ("drupal", None, re.compile(r"Drupal|/sites/default/files/", re.I), {}),
    ("typo3", None, re.compile(r"typo3(conf|temp)|/fileadmin/", re.I), {}),
    ("spip", None, re.compile(r"spip\.php|/IMG/pdf/|squelettes", re.I), {}),
]

# -------------------------------------------------------------- utilities
_print_lock = threading.Lock()
LOG_FH = None


def log(msg: str) -> None:
    line = f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    with _print_lock:
        print(line, flush=True)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def place_key(place_id: str) -> str:
    return world_schema.place_key(place_id, None, "FR")


def stable_doc_id(url: str) -> str:
    """Stable per-document id: hash of the canonical document URL (never change this)."""
    return "web-" + hashlib.sha256(canon(url).encode("utf-8")).hexdigest()[:24]


CONSOLIDATED_RE = re.compile(r"version consolidee|texte consolide|consolidee au|version en vigueur", re.I)


def clean_title(t: str) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    t = re.sub(r"\(\s*\d+\s*Downloads?\s*\)", "", t, flags=re.I)
    t = re.sub(r"\(?\b(PDF|pdf)(-Datei|-Dokument)?\b[^)]*?\d+([.,]\d+)?\s*[KkMm]i?B\)?", "", t)
    t = re.sub(r"\(\s*\d+([.,]\d+)?\s*[KkMm]i?B\s*\)", "", t)
    t = re.sub(r"\(\s*(PDF|pdf)(-Datei|-Dokument)?\s*\)", "", t)
    t = re.sub(r"(?<=[a-zäöüß])PDF$", "", t)
    t = re.sub(r"\.pdf$", "", t, flags=re.I)
    return re.sub(r"\s+", " ", urllib.parse.unquote(t)).strip(" -|·")


def schema_doc_type(doc_type_guess: str) -> str:
    if doc_type_guess == "recueil_actes":
        return "gazette_act"
    if doc_type_guess in ("deliberation", "proces_verbal"):
        return "decision"
    if doc_type_guess == "arrete":
        return "regulation"
    return "ordinance"


GENERIC_ANCHOR_RE = re.compile(r"^(consulter|telecharger|telechargement|voir|lire|ouvrir|ici|cliquez ici|pdf|document|"
                               r"lien|en savoir plus|lire la suite|afficher|download|fichier|\W*)$")


def _fr_title(d: dict) -> str:
    t = clean_title(d.get("title") or "")
    fn = clean_title(d["doc_url"].split("?")[0].rsplit("/", 1)[-1])
    if not t or GENERIC_ANCHOR_RE.search(_fold(t).strip()):
        t = re.sub(r"[-_]+", " ", fn).strip() or t
    return t or d["doc_url"]


def to_schema_record(d: dict, order: int) -> dict:
    """Map an internal document record to SCHEMA.md §2 staged record (cid omitted)."""
    head = _fold((d.get("title") or "") + " " + (d.get("text") or "")[:3000])
    rec = {
        "place_id": d["place_id"],
        "country_code": "FR",
        "doc_id": stable_doc_id(d["requested_url"]),
        "doc_order": order,
        "source_platform": SOURCE_PLATFORM,
        "source_url": d["doc_url"],
        "doc_type": schema_doc_type(d["doc_type_guess"]),
        "language": "fr",
        "title_native": _fr_title(d),
        "in_force": None,
        "consolidated": bool(CONSOLIDATED_RE.search(head)),
        "content_format": "pdf_text" if d["content_type"] == "pdf" else "html",
        "text": d.get("text") or "",
        "retrieved_at": d.get("fetched_at") or now_iso(),
        # place-level fields
        "place_name": d.get("municipality_name"),
        "qid": d.get("qid"),
        "admin_level": "municipality",
        "insee_code": d.get("insee_code"),
        "platform": SOURCE_PLATFORM,
        # extra provenance (ignored by normalizer)
        "municipality_source_url": d.get("source_url"),
        "homepage": d.get("homepage"),
        "section_url": d.get("section_url"),
        "requested_url": d.get("requested_url"),
        "doc_type_guess": d.get("doc_type_guess"),
        "http_content_type": d.get("http_content_type"),
        "sha256": d.get("sha256"),
        "size_bytes": d.get("size_bytes"),
        "raw_path": d.get("raw_path"),
        "text_extraction": d.get("text_extraction"),
        "template": d.get("template"),
        "crawler": d.get("crawler"),
    }
    return rec


def canon(url: str) -> str:
    try:
        p = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return ""
    if p.scheme not in ("http", "https") or not p.netloc:
        return ""
    # FR: the box has no outbound port 80, so every http URL is upgraded to https (doc ids use the https form)
    if p.scheme == "http":
        p = p._replace(scheme="https")
    netloc = p.netloc.lower()
    if netloc.endswith(":443") and p.scheme == "https":
        netloc = netloc[:-4]
    if netloc.endswith(":80") and p.scheme == "http":
        netloc = netloc[:-3]
    # keep the query string byte-for-byte; only drop known tracking/session params
    parts = [x for x in p.query.split("&") if x] if p.query else []
    kept = [x for x in parts if not x.split("=", 1)[0].lower().startswith(("utm_", "fbclid", "phpsessid", "jsessionid", "sid="))
            and x.split("=", 1)[0].lower() not in ("sid", "phpsessid", "jsessionid")]
    query = p.query if len(kept) == len(parts) else "&".join(kept)
    path = p.path or "/"
    path = re.sub(r";jsessionid=[^/?#]*", "", path, flags=re.I)
    return urllib.parse.urlunsplit((p.scheme, netloc, path, query, ""))


def netloc(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc.lower()


def reg_domain(host: str) -> str:
    host = host.split(":")[0].lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


# ------------------------------------------------------------- fetch cache
class FetchCache:
    def __init__(self, path: Path):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=60)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS fetch (url TEXT PRIMARY KEY, status INT, final_url TEXT, "
            "content_type TEXT, sha256 TEXT, path TEXT, size INT, fetched_at TEXT, error TEXT)"
        )
        self.db.commit()

    def get(self, url: str):
        with self.lock:
            row = self.db.execute(
                "SELECT status, final_url, content_type, sha256, path, size, fetched_at, error FROM fetch WHERE url=?",
                (url,),
            ).fetchone()
        if not row:
            return None
        keys = ("status", "final_url", "content_type", "sha256", "path", "size", "fetched_at", "error")
        return dict(zip(keys, row))

    def put(self, url: str, rec: dict) -> None:
        with self.lock:
            self.db.execute(
                "INSERT OR REPLACE INTO fetch VALUES (?,?,?,?,?,?,?,?,?)",
                (url, rec.get("status"), rec.get("final_url"), rec.get("content_type"), rec.get("sha256"),
                 rec.get("path"), rec.get("size"), rec.get("fetched_at"), rec.get("error")),
            )
            self.db.commit()


# ------------------------------------------------------- polite HTTP layer
class Politeness:
    """Per-host robots.txt, crawl-delay and serialisation (1 in flight per host)."""

    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.lock = threading.Lock()
        self.host_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self.next_ok: dict[str, float] = defaultdict(float)
        self.robots: "OrderedDict[str, tuple[str, object]]" = OrderedDict()  # LRU host -> (state, parser)
        self.robots_lock: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self.host_failures: Counter = Counter()
        self.dead_hosts: set[str] = set()

    def note_result(self, host: str, err: str) -> None:
        with self.lock:
            if err in ("timeout", "conn_error", "ssl_error"):
                self.host_failures[host] += 1
                if self.host_failures[host] >= HOST_DEAD_AFTER:
                    self.dead_hosts.add(host)
            else:
                self.host_failures.pop(host, None)

    def _host_lock(self, host: str) -> threading.Lock:
        with self.lock:
            return self.host_locks[host]

    def delay_for(self, host: str) -> float:
        st = self.robots.get(host)
        d = MIN_DELAY
        if st and st[0] == "ok":
            try:
                cd = st[1].crawl_delay(UA_TOKEN)
                if cd:
                    d = max(d, float(cd))
            except Exception:
                pass
        return d

    def wait_turn(self, host: str) -> None:
        """Caller must hold host lock."""
        delay = self.delay_for(host)
        while True:
            t = time.time()
            nxt = self.next_ok[host]
            if t >= nxt:
                break
            time.sleep(min(nxt - t, 5))
        self.next_ok[host] = time.time() + delay

    def robots_state(self, scheme: str, host: str, session) -> tuple[str, object]:
        """Policy (RFC 9309): 2xx -> parse with rfc9309.Robots; 4xx -> allow all;
        5xx / unreachable / timeout -> disallow all for this host. Raw robots.txt saved
        under _state/robots/ for audits."""
        with self.lock:
            rl = self.robots_lock[host]
        with rl:
            with self.lock:
                hit = self.robots.get(host)
                if hit is not None:
                    self.robots.move_to_end(host)
            if hit is not None:
                return hit
            url = f"{scheme}://{host}/robots.txt"
            hl = self._host_lock(host)
            state: tuple[str, object]
            text, code = "", 0
            with hl:
                self.wait_turn(host)
                try:
                    r = session.get(url, timeout=TIMEOUT, allow_redirects=True, stream=True)
                    body = r.raw.read(512_000, decode_content=True)
                    r.close()
                    code = r.status_code
                    if code >= 500:
                        state = ("disallow_all", f"robots {code}")
                    elif code >= 400:
                        state = ("allow_all", f"robots {code}")
                    else:
                        text = body.decode("utf-8", errors="replace")
                        state = ("ok", Robots(text))
                except Exception as e:
                    state = ("unreachable", f"robots {type(e).__name__}: {str(e)[:120]}")
            with self.lock:
                self.robots[host] = state
                while len(self.robots) > ROBOTS_LRU:
                    # evict parsed robots only; per-host locks/next_ok timestamps are tiny and are kept so
                    # the 1-in-flight + delay guarantees can never be broken by eviction
                    self.robots.popitem(last=False)
            if ROBOTS_DIR is not None:
                try:
                    ROBOTS_DIR.mkdir(parents=True, exist_ok=True)
                    fn = ROBOTS_DIR / (re.sub(r"[^A-Za-z0-9_.-]", "_", f"{scheme}_{host}") + ".json")
                    fn.write_text(json.dumps({"url": url, "status": code, "state": state[0],
                                              "note": state[1] if isinstance(state[1], str) else "",
                                              "fetched_at": now_iso(), "text": text}, ensure_ascii=False))
                except Exception:
                    pass
            return state

    def allowed(self, url: str, session) -> tuple[bool, str]:
        p = urllib.parse.urlsplit(url)
        host = p.netloc.lower()
        if host in self.dead_hosts:
            return False, "host_dead"
        st = self.robots_state(p.scheme, host, session)
        if st[0] == "allow_all":
            return True, ""
        if st[0] == "disallow_all":
            return False, "robots_disallowed"
        if st[0] == "unreachable":
            return False, "unreachable:" + str(st[1])
        rp = st[1]
        try:
            ok = rp.can_fetch(UA_TOKEN, url)
        except Exception:
            ok = False
        if ok:
            cd = self.delay_for(host)
            if cd > MAX_CRAWL_DELAY:
                return False, "crawl_delay_too_long"
        return ok, ("" if ok else "robots_disallowed")


class Fetcher:
    def __init__(self, cache: FetchCache, raw_dir: Path):
        self.cache = cache
        self.raw_dir = raw_dir
        self._local = threading.local()
        self.pol = Politeness(self.session)
        self.stats = Counter()
        self.stats_lock = threading.Lock()

    def session(self):
        s = getattr(self._local, "s", None)
        if s is None:
            s = requests.Session()
            s.headers.update({
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5",
                "Accept-Language": "fr-FR,fr;q=0.9",
            })
            s.max_redirects = 8
            self._local.s = s
        return s

    def _bump(self, k: str) -> None:
        with self.stats_lock:
            self.stats[k] += 1

    def get(self, url: str) -> dict:
        """Returns dict(status, final_url, content_type, sha256, path, size, error, cached, body)."""
        cached = self.cache.get(url)
        if cached is not None:
            cached["cached"] = True
            body = b""
            if cached.get("path") and Path(cached["path"]).is_file():
                body = Path(cached["path"]).read_bytes()
            elif cached.get("sha256"):
                cached = None  # raw lost; refetch
            if cached is not None:
                cached["body"] = body
                self._bump("cache_hit")
                return cached
        sess = self.session()
        ok, why = self.pol.allowed(url, sess)
        if not ok:
            rec = {"status": 0, "final_url": url, "content_type": "", "sha256": "", "path": "", "size": 0,
                   "fetched_at": now_iso(), "error": why, "body": b"", "cached": False, "not_fetched": True}
            return rec  # robots decisions are not cached in sqlite (host-level state is in memory)
        host = netloc(url)
        hl = self.pol._host_lock(host)
        rec = {"status": 0, "final_url": url, "content_type": "", "sha256": "", "path": "", "size": 0,
               "fetched_at": now_iso(), "error": "", "body": b"", "cached": False}
        tmp_pdf: Path | None = None
        hasher = hashlib.sha256()
        # Redirects are followed manually so robots.txt is checked for EVERY hop (same host or not)
        # BEFORE it is requested; each hop takes that host's lock (1 in flight per host, >=2 s spacing).
        cur = url
        hops = 0
        try:
            while True:
                if hops > 0:
                    okh, whyh = self.pol.allowed(cur, sess)
                    if not okh:
                        rec["error"] = whyh
                        rec["final_url"] = cur
                        break
                h_cur = netloc(cur)
                redirect_to = None
                with self.pol._host_lock(h_cur):
                    self.pol.wait_turn(h_cur)
                    self._bump("requests")
                    r = None
                    try:
                        r = sess.get(cur, timeout=TIMEOUT, allow_redirects=False, stream=True)
                        rec["status"] = r.status_code
                        rec["final_url"] = cur
                        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                            redirect_to = canon(urllib.parse.urljoin(cur, r.headers["location"]))
                            if not redirect_to:
                                rec["error"] = "bad_redirect"
                        else:
                            ctype = (r.headers.get("content-type") or "").lower()
                            rec["content_type"] = ctype
                            clen = int(r.headers.get("content-length") or 0)
                            limit = MAX_PDF_BYTES if ("pdf" in ctype or DOC_EXT.search(cur)) else MAX_HTML_BYTES
                            if clen and clen > limit:
                                rec["error"] = f"too_large:{clen}"
                            elif r.status_code == 200:
                                # Stream: PDFs go straight to a temp file on disk; HTML is buffered (<= MAX_HTML_BYTES).
                                chunks, total, t0, fh = [], 0, time.time(), None
                                for chunk in r.iter_content(65536):
                                    if not chunk:
                                        continue
                                    if total == 0 and chunk[:5] == b"%PDF-":
                                        limit = MAX_PDF_BYTES
                                        tmp_pdf = TMP_DIR / f"dl_{os.getpid()}_{threading.get_ident()}_{int(t0 * 1000)}.pdf"
                                        fh = tmp_pdf.open("wb")
                                    hasher.update(chunk)
                                    total += len(chunk)
                                    if fh is not None:
                                        fh.write(chunk)
                                    else:
                                        chunks.append(chunk)
                                    if total > limit:
                                        rec["error"] = "too_large"
                                        break
                                    if time.time() - t0 > REQUEST_DEADLINE:
                                        rec["error"] = "timeout"
                                        break
                                if fh is not None:
                                    fh.close()
                                rec["size"] = total
                                if not rec["error"]:
                                    rec["body"] = b"".join(chunks)
                                chunks = None
                            else:
                                rec["error"] = f"http_{r.status_code}"
                        if r.status_code == 429 or r.status_code == 503:
                            ra = r.headers.get("retry-after")
                            try:
                                back = min(float(ra), 300.0) if ra else 60.0
                            except ValueError:
                                back = 60.0
                            self.pol.next_ok[h_cur] = time.time() + back
                    except requests.exceptions.Timeout:
                        rec["error"] = "timeout"
                    except requests.exceptions.SSLError:
                        rec["error"] = "ssl_error"
                    except requests.exceptions.ConnectionError:
                        rec["error"] = "conn_error"
                    except Exception as e:
                        rec["error"] = f"{type(e).__name__}"
                    finally:
                        if r is not None:
                            r.close()
                        self.pol.note_result(h_cur, rec["error"])
                if redirect_to and not rec["error"]:
                    hops += 1
                    if hops > 5:
                        rec["error"] = "too_many_redirects"
                        break
                    cur = redirect_to
                    continue
                break
            have_pdf = tmp_pdf is not None and not rec["error"]
            body = rec["body"]
            if have_pdf:
                sha = hasher.hexdigest()
                if "pdf" not in rec["content_type"]:
                    rec["content_type"] = "application/pdf; " + rec["content_type"]
                # Disk policy (v0.2, like DE): PDF streamed to _tmp, text extracted, temp deleted in finally;
                # nothing is written to _raw. The cache row keeps sha but no path => later hits refetch.
                txt, err = pdf_text(str(tmp_pdf))
                rec["body"] = txt.encode("utf-8")
                rec["kind"] = "pdftxt"
                rec["extract_err"] = err
                txt = None
                rec.update(sha256=sha, path="")
            elif body and not STORE_RAW:
                rec.update(sha256=hasher.hexdigest(), path="", size=len(body))
            elif body:
                sha = hasher.hexdigest()
                path = self.raw_dir / sha[:2] / (sha + ".html.gz")
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_name(path.name + f".tmp{threading.get_ident()}")
                    with gzip.open(tmp, "wb") as gfh:
                        gfh.write(body)
                    tmp.replace(path)
                rec.update(sha256=sha, path=str(path), size=len(body))
        finally:
            if tmp_pdf is not None:
                tmp_pdf.unlink(missing_ok=True)
        if rec["error"] not in ("timeout", "conn_error") and not rec.get("not_fetched"):
            store = {k: v for k, v in rec.items() if k not in ("body", "cached", "kind", "extract_err")}
            self.cache.put(url, store)
        return rec


def body_bytes(rec: dict) -> bytes:
    b = rec.get("body") or b""
    p = rec.get("path") or ""
    if p.endswith(".gz") and b[:2] == b"\x1f\x8b":
        b = gzip.decompress(b)
    return b


def decode_html(b: bytes, ctype: str) -> str:
    m = re.search(r"charset=([\w-]+)", ctype or "")
    enc = m.group(1) if m else None
    if not enc:
        m2 = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", b[:4096], re.I)
        enc = m2.group(1).decode("ascii", "ignore") if m2 else "utf-8"
    try:
        return b.decode(enc, errors="replace")
    except LookupError:
        return b.decode("utf-8", errors="replace")


PDF_SEM = threading.BoundedSemaphore(int(os.environ.get("PDF_CONCURRENCY", "4")))  # bounds child RSS
PDF_CHILD_AS = 400 * 1024 * 1024  # address-space cap per pdftotext child


def _limit_child():
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (PDF_CHILD_AS, PDF_CHILD_AS))


def pdf_text(path: str) -> tuple[str, str]:
    """pdftotext to a temp file on disk, read at most MAX_TEXT_CHARS*4 bytes back."""
    out_txt = Path(path + ".txt")
    try:
        with PDF_SEM:
            out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", path, str(out_txt)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120,
                                 preexec_fn=_limit_child)
        if not out_txt.exists():
            return "", f"pdftotext rc={out.returncode}"
        with out_txt.open("rb") as fh:
            raw = fh.read(MAX_TEXT_CHARS * 4)
        txt = raw.decode("utf-8", errors="replace")[:MAX_TEXT_CHARS]
        raw = None
        # linear-time cleanup (a regex like [ \t]+\n is quadratic on long space runs and holds the GIL)
        out_lines, blank = [], 0
        for ln in txt.split("\n"):
            ln = ln.rstrip()
            if ln:
                blank = 0
                out_lines.append(ln)
            else:
                blank += 1
                if blank <= 1:
                    out_lines.append("")
        txt = "\n".join(out_lines).strip()
        return txt, ("" if out.returncode == 0 else f"pdftotext rc={out.returncode}")
    except subprocess.TimeoutExpired:
        return "", "pdftotext timeout"
    except Exception as e:
        return "", f"pdftotext {type(e).__name__}"
    finally:
        out_txt.unlink(missing_ok=True)


def html_main_text(soup: BeautifulSoup) -> str:
    for t in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "aside", "svg", "iframe"]):
        t.decompose()
    main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find(id=re.compile("content|inhalt|main", re.I)) or soup.body or soup
    txt = main.get_text("\n", strip=True)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


# --------------------------------------------------------------- seeding
def load_targets() -> list[dict]:
    """FR communes with a source_url in the candidate CSV; code_hosts/FR.jsonl links joined by qid;
    INSEE code from _state/insee_map.json (built from pipeline/codes/place_codes.parquet)."""
    seeds = {}
    if SEED_FILE.exists():
        with SEED_FILE.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    s = json.loads(line)
                    seeds[s["qid"]] = s
    insee = {}
    im = OUT / "_state" / "insee_map.json"
    if im.exists():
        insee = json.loads(im.read_text())
    targets, seen = [], set()
    with CANDIDATES.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["country_code"] != "FR" or not r.get("source_url") or not r.get("place_id"):
                continue
            if r["place_id"] in seen:
                continue
            seen.add(r["place_id"])
            s = seeds.get(r["qid"], {})
            src = r["source_url"].split(",")[0].strip()
            targets.append({
                "place_id": r["place_id"],
                "qid": r["qid"],
                "name": r.get("place_name") or s.get("name"),
                "country_code": "FR",
                "homepage": s.get("final_url") or src,
                "source_url": src,
                "population": r.get("population") or "",
                "insee_code": insee.get(r["place_id"]),
                "code_links": s.get("code_links") or [],
            })
    return targets


def score_seed(link: dict) -> int:
    t = _fold(link.get("url", "") + " " + link.get("text", ""))
    if SKIP_HOST_RE.search(host_of(link.get("url", ""))):
        return -1
    s = 0
    if re.search(r"recueil|actes? administratif|actes-administratif|publication des actes|publication-des-actes|actes reglementaires|actes-reglementaires", t):
        s += 50
    if re.search(r"arretes|deliberations|reglements|arrete|deliberation", t):
        s += 40
    if DOC_EXT.search(link.get("url", "")):
        s += 5
    if GAZETTE_RE.search(t):
        s -= 30
    if re.search(r"conseil municipal|conseil-municipal|affichage", t):
        s += 5
    if EXCLUDE_RE.search(t) and not re.search(r"arrete|deliberation|recueil", t):
        s -= 40
    if re.search(r"budget primitif|compte administratif|plan de zonage", t):
        s -= 25
    return s


def detect_template(host: str, html: str) -> tuple[str, dict]:
    for name, hre, bre, hints in TEMPLATES:
        if hre is not None and hre.search(host):
            return name, hints
    for name, hre, bre, hints in TEMPLATES:
        if hre is None and bre is not None and html and bre.search(html[:300_000]):
            return name, hints
    return "generic", {}


def guess_doc_type(t: str) -> str:
    t = _fold(t)
    if re.search(r"recueil|actes? administratif|\braa\b", t):
        return "recueil_actes"
    if "arrete" in t:
        return "arrete"
    if "deliberation" in t:
        return "deliberation"
    if "reglement" in t:
        return "reglement"
    if re.search(r"proces[- ]verbal|compte[- ]rendu", t):
        return "proces_verbal"
    if re.search(r"tarif|redevance|taxe", t):
        return "tarifs"
    return "other"


# ---------------------------------------------------------------- crawling
class DocSink:
    """Writes each validated schema record straight to <pk>.inprogress.jsonl.tmp in the staging dir,
    so a place's document texts are never all held in memory at once."""

    def __init__(self, out: Path, pk: str):
        self.out, self.pk = out, pk
        self.tmp = out / f"{pk}.inprogress.jsonl.tmp"
        self.fh = None
        self.rows = self.pdf = self.html = self.found = 0
        self.dropped: Counter = Counter()
        self.ids: set[str] = set()
        self.scanned: list[dict] = []

    def add(self, d: dict) -> None:
        self.found += 1
        if d["content_type"] == "pdf" and not (d.get("text") or "").strip():
            self.scanned.append({k: d.get(k) for k in ("place_id", "doc_url", "requested_url", "title", "sha256",
                                                       "size_bytes", "section_url", "fetched_at")})
            self.dropped["empty_content"] += 1
            return
        r = to_schema_record(d, self.rows)
        if r["doc_id"] in self.ids:
            self.dropped["dup_doc_id"] += 1
            return
        errs = world_schema.validate_record(r)
        if errs:
            for e in errs:
                self.dropped[e.split(":")[0].split(" ")[0]] += 1
            return
        if self.fh is None:
            self.fh = self.tmp.open("w", encoding="utf-8")
        self.fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.ids.add(r["doc_id"])
        self.rows += 1
        if r["content_format"] == "pdf_text":
            self.pdf += 1
        else:
            self.html += 1

    def close(self) -> None:
        if self.fh is not None:
            self.fh.flush()
            os.fsync(self.fh.fileno())
            self.fh.close()
            self.fh = None

    def abort(self) -> None:
        if self.fh is not None:
            self.fh.close()
            self.fh = None
        self.tmp.unlink(missing_ok=True)


class PlaceCrawler:
    def __init__(self, target: dict, fetcher: Fetcher, sink: DocSink, stop: threading.Event | None = None):
        self.t = target
        self.f = fetcher
        self.sink = sink
        self.stop = stop or threading.Event()
        self.interrupted = False
        self.requests = 0
        self.visited: set[str] = set()
        self.doc_shas: set[str] = set()
        self.doc_urls: set[str] = set()
        self.events = Counter()
        self.templates = Counter()
        self.section_pages: list[str] = []
        self.allowed_hosts: set[str] = set()
        self.started = time.time()
        self.first_errors: list[str] = []

    # -- helpers
    def budget_left(self) -> bool:
        if self.stop.is_set():
            self.interrupted = True
            return False
        return self.requests < MAX_REQUESTS_PER_PLACE and self.sink.found < MAX_DOCS_PER_PLACE and \
            time.time() - self.started < PLACE_TIME_BUDGET

    def fetch(self, url: str) -> dict:
        rec = self.f.get(url)
        if not rec.get("cached") and not rec.get("not_fetched"):
            self.requests += 1
        if rec.get("error"):
            e = rec["error"].split(":")[0]
            self.events["err_" + e] += 1
            if len(self.first_errors) < 5:
                self.first_errors.append(f"{rec['error']} {url}")
        return rec

    def host_ok(self, url: str) -> bool:
        h = host_of(url)
        return h in self.allowed_hosts or reg_domain(h) in {reg_domain(x) for x in self.allowed_hosts}

    def add_doc(self, url: str, rec: dict, title: str, ctype: str, text: str, via: str, extract_err: str = "", template: str = "") -> None:
        if not rec.get("sha256") or rec["sha256"] in self.doc_shas:
            return
        self.doc_shas.add(rec["sha256"])
        self.doc_urls.add(url)
        self.sink.add({
            "place_id": self.t["place_id"],
            "qid": self.t["qid"],
            "country_code": "FR",
            "municipality_name": self.t["name"],
            "insee_code": self.t.get("insee_code"),
            "source_url": self.t["source_url"],
            "homepage": self.t["homepage"],
            "section_url": via,
            "doc_url": rec.get("final_url") or url,
            "requested_url": url,
            "title": (title or "").strip()[:500],
            "doc_type_guess": guess_doc_type(title + " " + url),
            "content_type": ctype,  # "pdf" | "html"
            "http_content_type": rec.get("content_type", ""),
            "fetched_at": rec.get("fetched_at") or now_iso(),
            "sha256": rec["sha256"],
            "size_bytes": rec.get("size", 0),
            "raw_path": rec.get("path", ""),
            "text": text,
            "text_chars": len(text),
            "text_extraction": "pdftotext" if ctype == "pdf" else "bs4",
            "extraction_error": extract_err,
            "language": "fr",
            "template": template,
            "crawler": CRAWLER_VERSION,
        })
        text = None

    # -- main
    def run(self) -> dict:
        seeds = []
        for l in self.t["code_links"]:
            u = canon(l.get("url", ""))
            if not u:
                continue
            sc = score_seed(l)
            if sc < 0:
                continue
            seeds.append((sc, u, l.get("text", "")))
        seeds.sort(key=lambda x: -x[0])
        strong = [s for s in seeds if s[0] >= 30]
        mode = "seed_links" if strong else "homepage"
        hp = canon(self.t["homepage"] or self.t["source_url"].split(",")[0])
        for _, u, _ in seeds:
            self.allowed_hosts.add(host_of(u))
        if hp:
            self.allowed_hosts.add(host_of(hp))
        self.allowed_hosts = {h for h in self.allowed_hosts if h and not SKIP_HOST_RE.search(h)}

        # frontier: (priority, counter, url, depth, anchor, from_section)
        frontier: list = []
        cnt = 0

        def push(prio: float, url: str, depth: int, anchor: str, from_section: str):
            nonlocal cnt
            if url in self.visited or depth > MAX_DEPTH:
                return
            cnt += 1
            heapq.heappush(frontier, (prio, cnt, url, depth, anchor, from_section))
            if len(frontier) > MAX_FRONTIER:  # keep only the most promising half
                frontier[:] = heapq.nsmallest(MAX_FRONTIER // 2, frontier)
                heapq.heapify(frontier)

        for sc, u, txt in (strong or seeds)[:12]:
            push(-sc, u, 0, txt, "")
        if mode == "homepage" and hp:
            push(-1, hp, 0, "homepage", "")
        # weak seeds (bekanntmachung etc.) only after strong ones
        if strong:
            for sc, u, txt in seeds:
                if sc < 30 and sc >= 0:
                    push(50 - sc, u, 1, txt, "")

        robots_blocked_seeds = 0
        fetched_ok_pages = 0
        streak = 0
        while frontier and self.budget_left():
            if self.sink.found and streak >= UNPRODUCTIVE_STREAK:
                self.events["stop_unproductive"] += 1
                break
            prio, _, url, depth, anchor, from_section = heapq.heappop(frontier)
            if url in self.visited:
                continue
            self.visited.add(url)
            is_pdf_link = bool(DOC_EXT.search(url))
            rec = self.fetch(url)
            streak += 1
            if rec.get("error"):
                if depth == 0 and rec["error"] == "robots_disallowed":
                    robots_blocked_seeds += 1
                continue
            body = body_bytes(rec)
            if not body:
                continue
            ctype = rec.get("content_type", "")
            if rec.get("kind") == "pdftxt" or (rec.get("path") or "").endswith(".pdftxt.gz") or body[:5] == b"%PDF-":
                if self._doc_link_ok(anchor, url, from_section):
                    if body[:5] == b"%PDF-":  # legacy raw pdf
                        txt, err = pdf_text(rec["path"])
                    else:
                        txt, err = body.decode("utf-8", errors="replace"), rec.get("extract_err", "")
                    n0 = self.sink.found
                    self.add_doc(url, rec, anchor or url.rsplit("/", 1)[-1], "pdf", txt, from_section, err)
                    if self.sink.found > n0:
                        streak = 0
                continue
            if "html" not in ctype and not body.lstrip()[:200].lower().startswith((b"<!doctype", b"<html", b"<?xml")) and b"<html" not in body[:3000].lower():
                continue
            fetched_ok_pages += 1
            html = decode_html(body, ctype)
            final = canon(rec.get("final_url") or url) or url
            self.visited.add(final)
            tpl, hints = detect_template(host_of(final), html)
            self.templates[tpl] += 1
            if hints.get("skip"):
                continue
            try:
                soup = BeautifulSoup(html, "lxml")
            except Exception:
                continue
            title = (soup.title.get_text(" ", strip=True) if soup.title else "")
            h1 = soup.find("h1")
            h1t = h1.get_text(" ", strip=True) if h1 else ""
            page_fold = _fold(final + " " + title + " " + h1t + " " + anchor)
            is_section = bool(SECTION_RE.search(page_fold)) and not hints.get("gazette_only")
            if is_section and final not in self.section_pages:
                self.section_pages.append(final)
                streak = 0
            links = self._links(soup, final)
            # HTML legal document page?
            if depth > 0 or mode == "seed_links":
                self._maybe_html_doc(url, rec, soup, h1t or title, from_section, links, tpl)
            # enqueue
            name_f = _fold(self.t["name"] or "")
            name_re = re.compile(r"(^|[^a-z])" + re.escape(name_f) + r"([^a-z]|$)") if len(name_f) >= 3 else None
            page_path = urllib.parse.urlsplit(final).path.rstrip("/") + "/"
            children = [(hf_, tx_) for hf_, tx_ in links
                        if host_of(hf_) == host_of(final) and urllib.parse.urlsplit(hf_).path.startswith(page_path)
                        and urllib.parse.urlsplit(hf_).path.rstrip("/") + "/" != page_path]
            member_mode = bool(is_section and name_re and len(children) >= 4 and
                               any(name_re.search(_fold(tx_ + " " + urllib.parse.unquote(hf_).rstrip("/").rsplit("/", 1)[-1])) for hf_, tx_ in children))
            child_set = {hf_ for hf_, _ in children}
            for href, text in links:
                if href in self.visited or href in self.doc_urls:
                    continue
                lf = _fold(urllib.parse.unquote(href) + " " + text)
                tf = _fold(text)
                # the part of the URL that is new relative to the current page (for exclusion tests)
                hp_ = urllib.parse.urlsplit(href)
                tail = hp_.path[len(page_path):] if hp_.path.startswith(page_path) else hp_.path
                tail_f = _fold(urllib.parse.unquote(tail + ("?" + hp_.query if hp_.query else "")) + " " + text)
                h = host_of(href)
                if not h or SKIP_HOST_RE.search(h):
                    continue
                if NONDOC_EXT.search(href):
                    continue
                pdf = bool(DOC_EXT.search(href))
                if pdf:
                    if self._doc_link_ok(text, href, final if is_section else ""):
                        push(-80 if is_section else -60, href, depth + 1, text, final if is_section else from_section)
                    continue
                if member_mode and href in child_set:
                    seg = _fold(text + " " + urllib.parse.unquote(href).rstrip("/").rsplit("/", 1)[-1])
                    if name_re.search(seg):
                        push(-95, href, depth + 1, text, final)
                        continue
                    if not (DOC_RE.search(tf) or re.search(r"\b(communaute|intercommunal|syndicat|epci|agglomeration|metropole|cc)\b", seg)):
                        continue  # another member municipality's law
                if not self.host_ok(href):
                    # off-site Amt / VG Ortsrecht pages linked from a section page or seed
                    if (is_section or depth == 0) and SECTION_RE.search(lf) and not EXCLUDE_RE.search(tf) \
                            and len(self.allowed_hosts) < 6:
                        self.allowed_hosts.add(h)
                    else:
                        continue
                excluded = bool(EXCLUDE_RE.search(tail_f))
                if excluded and not SECTION_RE.search(tf):
                    continue
                if GAZETTE_RE.search(tail_f) and not SECTION_RE.search(tf):
                    continue
                if re.search(r"budget primitif|compte administratif|plan de zonage", lf):
                    continue
                if SECTION_RE.search(lf):
                    push(-70 + depth * 5, href, depth + 1, text, final if is_section else from_section)
                elif is_section and DOC_RE.search(tf):
                    push(-65 + depth * 5, href, depth + 1, text, final)
                elif is_section and DOWNLOAD_HINT.search(href) and depth < MAX_DEPTH:
                    push(-60, href, depth + 1, text, final)  # file download without .pdf suffix
                elif is_section and self._is_pagination(href, text, final):
                    push(-55, href, depth, text, final)  # pagination: same depth
                elif mode == "homepage" and depth <= 1 and NAV_RE.search(lf) and self.host_ok(href):
                    push(-20 + depth * 10, href, depth + 1, text, "")
                elif is_section and depth < 2 and "ModID=" in href and self.host_ok(href):
                    push(-40, href, depth + 1, text, final)  # IKISS detail/listing
            soup.decompose()  # break bs4 reference cycles promptly
            soup = links = children = child_set = html = body = rec = None
        status = self._status(mode, robots_blocked_seeds, fetched_ok_pages)
        return {
            "place_id": self.t["place_id"], "qid": self.t["qid"], "name": self.t["name"],
            "mode": mode, "status": status, "docs": self.sink.found,
            "pdf_docs": self.sink.pdf, "html_docs": self.sink.html,
            "requests": self.requests, "pages_ok": fetched_ok_pages, "visited": len(self.visited),
            "section_pages": self.section_pages[:10], "templates": dict(self.templates),
            "events": dict(self.events), "first_errors": self.first_errors,
            "elapsed_s": round(time.time() - self.started, 1), "finished_at": now_iso(),
            "budget_exhausted": not self.budget_left(),
        }

    def _status(self, mode: str, robots_blocked: int, pages_ok: int) -> str:
        if self.sink.found:
            return "ok"
        ev = self.events
        if pages_ok == 0:
            if ev.get("err_robots_disallowed"):
                return "robots_disallowed"
            if ev.get("err_unreachable"):
                return "unreachable"
            if ev.get("err_timeout"):
                return "timeout"
            if ev.get("err_crawl_delay_too_long"):
                return "crawl_delay_too_long"
            if any(k.startswith("err_http_") for k in ev):
                return "http_error"
            if any(k.startswith("err_") for k in ev):
                return "fetch_error"
            return "no_pages"
        if not self.section_pages:
            if ev.get("err_robots_disallowed"):
                return "robots_disallowed_partial"
            return "no_section_found"
        if ev.get("err_robots_disallowed"):
            return "docs_robots_disallowed"
        return "section_no_docs"

    def _is_pagination(self, href: str, text: str, page: str) -> bool:
        t = _fold(text).strip()
        if re.fullmatch(r"\d{1,3}|weiter|nachste|nachste seite|vor|>|>>|»|›|next|mehr", t):
            return True
        return bool(re.search(r"[?&](page|seite|pg|start|offset|p)=\d+|/page/\d+|/seite-?\d+", href, re.I)) and \
            href.split("?")[0].rstrip("/") == page.split("?")[0].rstrip("/")

    def _doc_link_ok(self, text: str, url: str, from_section: str) -> bool:
        lf = _fold(text + " " + urllib.parse.unquote(url))
        if re.search(r"formulaire|cerfa|flyer|plaquette|depliant|menu|cantine|mentions legales|offre d.emploi|"
                     r"bulletin|magazine|ordre du jour|convocation|plan de zonage|affiche|programme|"
                     r"budget primitif|compte administratif|inscription|fiche|guide", lf):
            return False
        if GAZETTE_RE.search(lf) and not re.search(r"arrete|deliberation|recueil", lf):
            return False
        if DOC_RE.search(lf):
            return True
        return bool(from_section)

    def _links(self, soup: BeautifulSoup, base: str) -> list[tuple[str, str]]:
        out, seen = [], set()
        b = soup.find("base", href=True)
        basehref = urllib.parse.urljoin(base, b["href"]) if b else base
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.lower().startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
                continue
            u = canon(urllib.parse.urljoin(basehref, href))
            if not u or u in seen:
                continue
            seen.add(u)
            text = a.get_text(" ", strip=True) or a.get("title", "") or a.get("aria-label", "")
            out.append((u, re.sub(r"\s+", " ", text)[:300]))
        return out

    def _maybe_html_doc(self, url, rec, soup, heading, via, links, tpl) -> None:
        hf = _fold(heading)
        if not re.search(r"arrete|deliberation|reglement|recueil", hf):
            return
        if re.search(r"budget primitif|plan de zonage", hf):
            return
        # many links to PDFs => listing page, not a document
        text = html_main_text(soup)
        paras = len(re.findall(r"(?im)^\s*(article|art\.)\s*\d+|vu le|considerant", _fold(text)))
        if len(text) < 1500 or paras < 3:
            return
        self.add_doc(url, rec, heading, "html", text, via, "", tpl)


# ------------------------------------------------------------- orchestration
class Runner:
    def __init__(self, args):
        self.args = args
        self.out = Path(args.out)
        for d in ("_raw", "_state", "_logs"):
            (self.out / d).mkdir(parents=True, exist_ok=True)
        global ROBOTS_DIR, TMP_DIR
        ROBOTS_DIR = self.out / "_state" / "robots"
        TMP_DIR = self.out / "_tmp"
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        for stale in list(TMP_DIR.glob("dl_*")) + list(self.out.glob("*.inprogress.jsonl.tmp")):
            stale.unlink(missing_ok=True)  # leftovers of a killed process (never-finished files)
        self.cache = FetchCache(self.out / "_state/fetch_cache.sqlite")
        self.fetcher = Fetcher(self.cache, self.out / "_raw")
        self.done_path = self.out / "_state/done_place_ids.txt"
        self.results_path = self.out / "_state/place_results.jsonl"
        self.progress_path = self.out / "_progress.json"
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.drain = threading.Event()
        self.done = set()
        if self.done_path.exists():
            self.done = {l.strip() for l in self.done_path.read_text().splitlines() if l.strip()}
        self.agg = self._load_agg()
        self.started = time.time()
        self.session_done = 0
        self.active_hosts: Counter = Counter()

    def _load_agg(self) -> dict:
        agg = {"processed": 0, "with_docs": 0, "docs": 0, "pdf": 0, "html": 0, "status": Counter(),
               "templates": Counter(), "requests": 0}
        if self.results_path.exists():
            seen = set()
            for line in self.results_path.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r["place_id"] in seen:
                    continue
                seen.add(r["place_id"])
                self._agg_add(agg, r)
        return agg

    @staticmethod
    def _agg_add(agg: dict, r: dict) -> None:
        agg["processed"] += 1
        agg["with_docs"] += 1 if r["docs"] else 0
        agg["docs"] += r["docs"]
        agg["pdf"] += r["pdf_docs"]
        agg["html"] += r["html_docs"]
        agg["requests"] += r.get("requests", 0)
        agg["status"][r["status"]] += 1
        for k in r.get("templates", {}):
            agg["templates"][k] += 1

    def write_progress(self, total: int, final: bool = False) -> None:
        a = self.agg
        el = time.time() - self.started
        rate = self.session_done / el if el > 0 else 0
        remaining = max(total - a["processed"], 0)
        prog = {
            "country_code": "FR",
            "crawler": CRAWLER_VERSION,
            "updated_at": now_iso(),
            "targets_total": total,
            "processed": a["processed"],
            "remaining": remaining,
            "with_docs": a["with_docs"],
            "hit_rate": round(a["with_docs"] / a["processed"], 4) if a["processed"] else 0,
            "documents_total": a["docs"],
            "documents_pdf": a["pdf"],
            "documents_html": a["html"],
            "http_requests_total": a["requests"],
            "status_counts": dict(a["status"]),
            "template_counts": dict(a["templates"].most_common(20)),
            "session_places_per_hour": round(rate * 3600, 1),
            "eta_hours": round(remaining / rate / 3600, 2) if rate else None,
            "schema_md_present": SCHEMA.exists(),
            "schema_version": world_schema.SCHEMA_VERSION,
            "output_files": "<place_key>.full.<UTCts>.jsonl (SCHEMA.md v1 staged records)",
            "pid": os.getpid(),
            "finished": final,
        }
        tmp = self.progress_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(prog, indent=2, ensure_ascii=False))
        tmp.replace(self.progress_path)

    def finish_place(self, t: dict, sink: DocSink, res: dict) -> None:
        pk = place_key(t["place_id"])
        res["docs_found"] = sink.found
        res["docs"] = sink.rows
        res["pdf_docs"] = sink.pdf
        res["html_docs"] = sink.html
        res["dropped_rows"] = dict(sink.dropped)
        if not sink.rows and res.get("status") == "ok":
            res["status"] = "docs_without_text"  # e.g. scanned PDFs (no OCR available)
        if sink.scanned:
            with self.lock, (self.out / "_state" / "scanned_pdfs_need_ocr.jsonl").open("a", encoding="utf-8") as fh:
                for d in sink.scanned:
                    fh.write(json.dumps(d, ensure_ascii=False) + "\n")
        res["pdf_no_text"] = len(sink.scanned)
        res["file"] = ""
        if sink.rows:
            sink.close()
            batch = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            final = self.out / f"{pk}.full.{batch}.jsonl"
            # validate_file dispatches on the suffix, so validate a hard link with a .jsonl name
            chk = self.out / "_state" / "validate" / (final.name)
            chk.parent.mkdir(parents=True, exist_ok=True)
            chk.unlink(missing_ok=True)
            os.link(sink.tmp, chk)
            v = world_schema.validate_file(chk, expect_place_key=pk)
            chk.unlink(missing_ok=True)
            if v["ok"]:
                os.rename(sink.tmp, final)
                res["file"] = final.name
            else:
                res["status"] = "validation_failed"
                res["validation_errors"] = [str(e) for e in v["errors"][:5]]
                bad = self.out / "_state" / "invalid" / final.name
                bad.parent.mkdir(parents=True, exist_ok=True)
                os.rename(sink.tmp, bad)
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

    def primary_host(self, t: dict) -> str:
        best = sorted(((score_seed(l), l["url"]) for l in t["code_links"]), key=lambda x: -x[0])
        if best and best[0][0] >= 0:
            return host_of(best[0][1])
        return host_of(t["homepage"])

    def run(self) -> None:
        targets = load_targets()
        if self.args.only:
            ids = set(self.args.only.split(","))
            targets = [t for t in targets if t["place_id"] in ids or t["qid"] in ids]
        if self.args.sample:
            import random
            rnd = random.Random(self.args.seed)
            targets = rnd.sample(targets, min(self.args.sample, len(targets)))
        total = len(targets)
        pending = [t for t in targets if t["place_id"] not in self.done]
        if self.args.limit:
            pending = pending[: self.args.limit]
        # group by primary host; schedule so no two workers share a primary host
        by_host: dict[str, deque] = defaultdict(deque)
        for t in pending:
            by_host[self.primary_host(t)].append(t)
        host_order = deque(sorted(by_host, key=lambda h: -len(by_host[h])))  # big shared hosts start early
        log(f"targets={total} done={len(self.done)} pending={len(pending)} hosts={len(by_host)} workers={self.args.workers} repo={REPO}")
        self.write_progress(total)
        sched_lock = threading.Lock()

        def next_target():
            with sched_lock:
                for _ in range(len(host_order)):
                    h = host_order[0]
                    host_order.rotate(-1)
                    if not by_host[h]:
                        continue
                    if self.active_hosts[h] > 0:
                        continue
                    self.active_hosts[h] += 1
                    return h, by_host[h].popleft()
                return None, None

        def remaining():
            with sched_lock:
                return sum(len(q) for q in by_host.values())

        def worker(i: int):
            while not self.stop.is_set() and not self.drain.is_set():
                h, t = next_target()
                if t is None:
                    if remaining() == 0:
                        return
                    time.sleep(2)
                    continue
                sink = DocSink(self.out, place_key(t["place_id"]))
                pc = None
                try:
                    pc = PlaceCrawler(t, self.fetcher, sink, self.stop)
                    try:
                        res = pc.run()
                    except Exception as e:
                        res = {"place_id": t["place_id"], "qid": t["qid"], "name": t["name"], "mode": "",
                               "status": "ok" if sink.found else "crawler_exception", "docs": sink.found,
                               "pdf_docs": sink.pdf, "html_docs": sink.html,
                               "requests": pc.requests, "error": f"{type(e).__name__}: {e}",
                               "trace": traceback.format_exc()[-1500:], "finished_at": now_iso()}
                    if pc.interrupted or self.stop.is_set():
                        sink.abort()  # interrupted mid-place: don't mark done; redone after restart
                        return
                    self.finish_place(t, sink, res)
                    log(f"[{self.agg['processed']}/{total}] {t['place_id']} {t['name']} status={res['status']} "
                        f"docs={res['docs']} (pdf={res['pdf_docs']} html={res['html_docs']}) req={res.get('requests')} "
                        f"t={res.get('elapsed_s')}s")
                    if self.session_done % 5 == 0:
                        self.write_progress(total)
                    if self.args.max_places and self.session_done >= self.args.max_places and not self.drain.is_set():
                        log(f"max-places {self.args.max_places} reached: draining for process recycle")
                        self.drain.set()
                except Exception:
                    sink.abort()
                    log(f"worker error {t['place_id']}: {traceback.format_exc()[-800:]}")
                finally:
                    pc = sink = None
                    with sched_lock:
                        self.active_hosts[h] -= 1
                    gc.collect()

        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(self.args.workers)]
        for th in threads:
            th.start()
        try:
            while any(th.is_alive() for th in threads):
                time.sleep(5)
                if self.stop.is_set():
                    break
        except KeyboardInterrupt:
            self.stop.set()
        for th in threads:
            th.join(timeout=60 if self.stop.is_set() else None)
        finished = not self.stop.is_set() and not self.drain.is_set() and self.agg["processed"] >= total
        self.write_progress(total, final=finished)
        log(f"finished session: processed={self.session_done} stats={dict(self.fetcher.stats)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--max-places", type=int, default=0, help="exit after N places this session (process recycling)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample", type=int, default=0, help="random sample of N targets (testing)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--only", default="", help="comma-separated place_ids/qids")
    args = ap.parse_args()
    r = Runner(args)

    def _sig(signum, frame):
        log(f"signal {signum}: stopping after in-flight places")
        r.stop.set()
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    r.run()


if __name__ == "__main__":
    main()
