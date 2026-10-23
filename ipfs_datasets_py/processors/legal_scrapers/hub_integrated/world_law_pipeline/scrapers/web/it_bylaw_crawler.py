#!/usr/bin/env python3
"""Italian comuni crawler (regolamenti comunali, statuto, delibere, ordinanze). Same architecture, politeness
and limits as fr_actes_crawler.py v0.2 (imported and re-parameterised, like ca_bylaw_crawler.py): strict
RFC 9309 robots (2xx parse, 4xx allow, 5xx/unreachable block), Crawl-delay honoured (>=2 s/host, 1 in
flight/host), PDFs streamed to _tmp -> pdftotext -> temp deleted (no _raw), bounded per-place budgets,
resumable via _state, scanned PDFs listed in _state/scanned_pdfs_need_ocr.jsonl.

Targets: IT rows with source_url in global_municipalities_candidate.csv; seeds from code_hosts/IT.jsonl
(joined by qid); ISTAT code (it_istat) from pipeline/codes/place_codes.parquet -> _state/code_map.json.
Vendor templates are detected on each page (Halley, Maggioli/JCityGov, PA Digitale/URBI, Municipium,
Designers Italia "Comuni" theme, Gruppo Soluzioni, ISWEB, Dedagroup, Studio K, Comune.Net, ...); on the
homepage the template adds its known 'Amministrazione trasparente' / regolamenti entry points, then the
generic bounded crawl runs. Lasting regolamenti/statuto are preferred over albo notices; gare/bandi/avvisi/
concorsi are skipped. Output: /workspace/world_law/staging/web/IT/
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import csv
import importlib.util
import json
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("fr_base", HERE / "fr_actes_crawler.py")
base = importlib.util.module_from_spec(_spec)
sys.modules["fr_base"] = base
_spec.loader.exec_module(base)  # type: ignore[union-attr]

CC = "IT"
OUT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/web/IT"))
CODES = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/codes/place_codes.parquet"))
CODE_SYSTEM = "it_istat"
VENV_PY = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/venv/bin/python"))
_fold = base._fold

for _r in (Path("/workspace/ipfs_datasets_py_latest"), Path("/workspace/ipfs_datasets_py")):
    if (_r / "ipfs_datasets_py/processors/legal_scrapers/municipal/seeds/code_hosts/IT.jsonl").exists():
        base.REPO = _r
        base.MUNI = _r / "ipfs_datasets_py/processors/legal_scrapers/municipal"
        break
base.OUT = OUT
base.SOURCE_PLATFORM = "it_municipal_web"
base.CRAWLER_VERSION = "it_bylaw_crawler/0.1"
base.SEED_FILE = base.MUNI / "seeds/code_hosts/IT.jsonl"
base.TMP_DIR = OUT / "_tmp"
base.MAX_DEPTH = 4  # Amministrazione trasparente > sezione > sottosezione > atto > allegato
base.USER_AGENT = (
    f"{base.UA_TOKEN}/0.2 (+https://github.com/endomorphosis/ipfs_datasets_py; research crawler collecting "
    "public municipal law (regolamenti comunali, statuto, delibere, ordinanze); respects robots.txt and "
    "Crawl-delay; 1 request per host every >=2s)")

base.SECTION_RE = re.compile(
    r"regolament|statuto comunale|statuto del comune|\bstatuto\b|atti generali|atti-generali|"
    r"atti normativi|atti-normativi|riferimenti normativi|"
    r"amministrazione trasparente|amministrazione-trasparente|"
    r"delibere|deliberazioni|ordinanze|albo pretorio|albo-pretorio|albo on ?line|albopretorio|"
    r"atti amministrativi|documenti e dati|documenti-e-dati|normativa comunale")
base.DOC_RE = re.compile(
    r"regolamento|regolamenti|statuto|delibera|deliberazione|ordinanza|\bd\.?c\.?c\.?\b|\bd\.?g\.?c\.?\b|"
    r"consiglio comunale|giunta comunale|\bn\.? ?\d{1,4}[/ ]\d{2,4}|tari\b|imu\b|tributi|canone|"
    r"polizia (urbana|locale|mortuaria)|edilizi|urbanistic|commercio|cimiter|tariff|norme tecniche|piano")
base.NAV_RE = re.compile(
    r"amministrazione|comune|il comune|documenti|trasparen|albo|atti|servizi|uffici|consiglio|giunta|"
    r"sindaco|normativ|municipio|governo")
base.EXCLUDE_RE = re.compile(
    r"bandi|bando|gare|gara d|appalti|avvis[oi]|concors[oi]|selezion[ei]|graduatori|eventi|evento|notizie|"
    r"news|comunicati|turismo|cultura|manifestazion|meteo|webcam|galleria|foto|video|facebook|instagram|"
    r"twitter|youtube|linkedin|login|accedi|spid|newsletter|privacy|cookie|accessibilita|mappa del sito|"
    r"contatti|pagopa|pago pa|elezioni|modulistica|moduli|/tag/|/category/|/author/|wp-json|/feed|print=|"
    r"share=|replytocom|ical|determin[ae]|incarichi|personale|bilanci|pagamenti dell|sovvenzioni|contributi")
base.GAZETTE_RE = re.compile(r"notiziario|giornalino|periodico comunale|informacomune|magazine|newsletter")
base.DOWNLOAD_HINT = re.compile(
    r"download|scarica|allegat|getfile|/file/|/files?/|/documenti?/|/uploads?/|/wp-content/uploads/|"
    r"/sites/default/files/|/media/|/docs?/|/zf/index\.php/.*(allegat|download)|/hh/|/c\d{6}/|"
    r"/at/|openfile|/attachment|/documents/|/-/papca/|papca/display|allegat|jcitygov.*(download|allegat)|/openweb/.*(download|file)||/resource/|blob|/portale/.*\.pdf|/downloads?/", re.I)
base.SKIP_HOST_RE = re.compile(
    r"(^|\.)(facebook\.com|instagram\.com|twitter\.com|x\.com|youtube\.com|(www|maps|docs|drive|play)\.google\.[a-z.]+|"
    r"normattiva\.it|gazzettaufficiale\.it|linkedin\.com|wikipedia\.org|apple\.com|openstreetmap\.org|"
    r"tripadvisor\.[a-z.]+|booking\.com|calameo\.com|issuu\.com|yumpu\.com|pagopa\.gov\.it|spid\.gov\.it|"
    r"agid\.gov\.it|anticorruzione\.it|istat\.it|interno\.gov\.it|whatsapp\.com|telegram\.me)$")
base.TEMPLATES = [
    ("halley", re.compile(r"halleyweb\.com$|halley\.it$"), re.compile(r"halley|/zf/index\.php/trasparenza|hspromo|/c\d{6}/(zf|hh|po)/", re.I), {}),
    ("maggioli", re.compile(r"maggioli(cloud)?\.it$|trasparenza-valutazione-merito\.it$|jcitygov"), re.compile(r"maggioli|jcitygov|/c/portal/|sicr@web|sicraweb", re.I), {}),
    ("pa_digitale", re.compile(r"urbi\.it$|padigitale\.it$"), re.compile(r"pa ?digitale|urbismart|/urbi/|urbi\.it", re.I), {}),
    ("asmel", re.compile(r"asmenet\.it$|asmecomm\.it$"), re.compile(r"asmenet|asmel", re.I), {}),
    ("saturnweb", re.compile(r"servizipubblicaamministrazione\.it$"), re.compile(r"saturnweb", re.I), {}),
    ("municipium", re.compile(r"municipiumapp\.it$|municipium\.it$"), re.compile(r"municipium", re.I), {}),
    ("gruppo_soluzioni", re.compile(r"soluzionipa\.it$|gruppo-?soluzioni"), re.compile(r"gruppo ?soluzioni|soluzionipa|grupposoluzioni", re.I), {}),
    ("isweb", re.compile(r"isweb\.it$|internetsoluzioni\.it$"), re.compile(r"isweb|internet soluzioni|pantarei|/pagina\d+_", re.I), {}),
    ("dedagroup", re.compile(r"dedagroup\.it$"), re.compile(r"dedagroup|civilia", re.I), {}),
    ("studio_k", None, re.compile(r"studio ?k s\.?r\.?l|studiok", re.I), {}),
    ("comune_net", re.compile(r"comune\.net$"), re.compile(r"comune\.net|comunenet", re.I), {}),
    ("apkappa", re.compile(r"apkappa\.it$"), re.compile(r"apkappa|hypersic", re.I), {}),
    ("kibernetes", re.compile(r"kibernetes\.it$"), re.compile(r"kibernetes", re.I), {}),
    ("designers_italia", None, re.compile(r"bootstrap-italia|design-comuni|designers italia|comuni-italia|design-italia|italia\.it/assets", re.I), {}),
    ("wordpress", None, re.compile(r"/wp-content/|/wp-includes/", re.I), {}),
    ("joomla", None, re.compile(r"/media/jui/|Joomla|/media/system/js/", re.I), {}),
    ("drupal", None, re.compile(r"Drupal|/sites/default/files/", re.I), {}),
    ("typo3", None, re.compile(r"typo3(conf|temp)|/fileadmin/", re.I), {}),
]
base.GENERIC_ANCHOR_RE = re.compile(
    r"^(scarica|download|apri|visualizza|leggi|dettaglio|dettagli|allegato|file|documento|pdf|qui|clicca qui|"
    r"vai|link|\W*)$")

# vendor entry points tried from the homepage (anchor text matches SECTION_RE so they are enqueued as sections)
_TPL_PATHS = {
    "halley": ["/c{istat}/zf/index.php/trasparenza/index/index", "/c{istat}/po/mostra_news.php?area=H"],
    "designers_italia": ["/amministrazione-trasparente", "/documenti-e-dati", "/documenti-e-dati/atti-normativi",
                         "/amministrazione-trasparente/disposizioni-generali/atti-generali"],
    "municipium": ["/amministrazione-trasparente", "/documenti-e-dati", "/documenti_pubblici"],
    "maggioli": ["/web/trasparenza/dettaglio-trasparenza", "/amministrazione-trasparente", "/statuto-e-regolamenti", "/regolamenti"],
    "pa_digitale": ["/amministrazione-trasparente", "/regolamenti"],
    "gruppo_soluzioni": ["/amministrazione-trasparente", "/regolamenti"],
    "isweb": ["/amministrazione-trasparente", "/regolamenti"],
}
_GENERIC_PATHS = ["/amministrazione-trasparente", "/regolamenti"]
_SYN_ANCHOR = "regolamenti atti generali amministrazione trasparente"

_IT = re.compile(r"\b(il|la|le|di|del|della|che|comune|articolo|regolamento|consiglio|sono|per)\b")
_CODE_MAP: dict[str, dict] = {}


def detect_lang(text: str) -> str:
    t = _fold((text or "")[:6000])
    if re.search(r"\b(der|die|und|gemeinde)\b", t) and len(re.findall(r"\b(der|die|und|das|gemeinde)\b", t)) > len(_IT.findall(t)):
        return "de"  # South Tyrol bilingual comuni
    return "it"


def guess_doc_type(t: str) -> str:
    t = _fold(t)
    if re.search(r"\bstatuto\b", t):
        return "statuto"
    if re.search(r"regolament", t):
        return "regolamento"
    if re.search(r"ordinanz", t):
        return "ordinanza"
    if re.search(r"delibera|deliberazione|\bd\.?c\.?c\b|\bd\.?g\.?c\b", t):
        return "delibera"
    if re.search(r"decreto", t):
        return "decreto"
    return "other"


def schema_doc_type(g: str) -> str:
    return {"statuto": "statute", "regolamento": "regulation", "ordinanza": "ordinance",
            "delibera": "decision", "decreto": "decision"}.get(g, "regulation")


def to_schema_record(d: dict, order: int) -> dict:
    d["doc_type_guess"] = guess_doc_type((d.get("title") or "") + " " + d.get("doc_url", "") + " " + (d.get("text") or "")[:1500])
    head = _fold((d.get("title") or "") + " " + (d.get("text") or "")[:3000])
    meta = _CODE_MAP.get(d["place_id"]) or {}
    code = d.get("insee_code") or meta.get("code")
    return {
        "place_id": d["place_id"], "country_code": CC,
        "doc_id": base.stable_doc_id(d["requested_url"]), "doc_order": order,
        "source_platform": base.SOURCE_PLATFORM, "source_url": d["doc_url"],
        "doc_type": schema_doc_type(d["doc_type_guess"]),
        "language": detect_lang((d.get("title") or "") + "\n" + (d.get("text") or "")),
        "title_native": base._fr_title(d), "in_force": None,
        "consolidated": bool(re.search(r"testo coordinato|testo vigente|coordinato con le modifiche|testo consolidato|testo integrato", head)),
        "content_format": "pdf_text" if d["content_type"] == "pdf" else "html",
        "text": d.get("text") or "", "retrieved_at": d.get("fetched_at") or base.now_iso(),
        "place_name": d.get("municipality_name"), "qid": d.get("qid"), "admin_level": "municipality",
        "place_code": code, "place_code_system": CODE_SYSTEM if code else None,
        "platform": base.SOURCE_PLATFORM,
        "municipality_source_url": d.get("source_url"), "homepage": d.get("homepage"),
        "section_url": d.get("section_url"), "requested_url": d.get("requested_url"),
        "doc_type_guess": d.get("doc_type_guess"), "http_content_type": d.get("http_content_type"),
        "sha256": d.get("sha256"), "size_bytes": d.get("size_bytes"),
        "text_extraction": d.get("text_extraction"), "template": d.get("template"), "crawler": base.CRAWLER_VERSION,
    }


def place_key(place_id: str) -> str:
    return base.world_schema.place_key(place_id, None, CC)


def load_code_map() -> dict:
    global _CODE_MAP
    cm = OUT / "_state" / "code_map.json"
    if (not cm.exists() or cm.stat().st_size < 10 or cm.stat().st_mtime < CODES.stat().st_mtime) and CODES.exists():
        try:
            import pyarrow  # noqa: F401
            build_code_map()
        except ImportError:
            import subprocess
            subprocess.run([str(VENV_PY), str(Path(__file__).resolve()), "--build-code-map"], check=True)
    _CODE_MAP = json.loads(cm.read_text()) if cm.exists() else {}
    return _CODE_MAP


def build_code_map() -> None:
    """place_id -> {code, code_system: it_istat}; official match, preferred rank, lowest code."""
    import pandas as pd
    pc = pd.read_parquet(CODES)
    pc = pc[(pc.country_code == CC) & (pc.code_system == CODE_SYSTEM) & (pc.is_current != False)].copy()  # noqa: E712
    pc = pc[pc.code.astype(str).str.fullmatch(r"\d{6}")]
    pc["_k"] = list(zip(pc.official_check.ne("match"), pc.wd_rank.ne("PreferredRank"), pc.code.astype(str)))
    pc = pc.sort_values("_k")
    m: dict[str, dict] = {}
    for pid, code in zip(pc.place_id, pc.code.astype(str)):
        m.setdefault(pid, {"code": code, "code_system": CODE_SYSTEM})
    (OUT / "_state").mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_state" / "code_map.json.tmp"
    tmp.write_text(json.dumps(m, ensure_ascii=False, sort_keys=True))
    tmp.replace(OUT / "_state" / "code_map.json")
    print(f"code_map: {len(m)} IT places (it_istat)")


def load_targets() -> list[dict]:
    codes = load_code_map()
    seeds = {}
    if base.SEED_FILE.exists():
        with base.SEED_FILE.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    s = json.loads(line)
                    seeds[s["qid"]] = s
    out, seen = [], set()
    with base.CANDIDATES.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["country_code"] != CC or not r.get("source_url") or not r.get("place_id") or r["place_id"] in seen:
                continue
            seen.add(r["place_id"])
            s = seeds.get(r["qid"], {})
            src = r["source_url"].split(",")[0].strip()
            code = (codes.get(r["place_id"]) or {}).get("code")
            out.append({"place_id": r["place_id"], "qid": r["qid"], "name": r.get("place_name") or s.get("name"),
                        "country_code": CC, "homepage": s.get("final_url") or src, "source_url": src,
                        "population": r.get("population") or "", "insee_code": code,
                        "place_code_system": CODE_SYSTEM if code else None,
                        "code_links": s.get("code_links") or []})
    return out


def score_seed(link: dict) -> int:
    t = _fold(link.get("url", "") + " " + link.get("text", ""))
    if base.SKIP_HOST_RE.search(base.host_of(link.get("url", ""))):
        return -1
    s = 0
    if re.search(r"regolament|statuto", t):
        s += 55
    if re.search(r"atti generali|atti-generali|atti normativi|disposizioni generali", t):
        s += 50
    if re.search(r"amministrazione trasparente|amministrazione-trasparente|trasparenza", t):
        s += 35
    if re.search(r"delibere|deliberazioni|ordinanze", t):
        s += 30
    if re.search(r"albo|albopretorio", t):
        s += 12  # daily notices: weaker than lasting regolamenti
    if base.EXCLUDE_RE.search(t) and not re.search(r"regolament|statuto|atti generali", t):
        s -= 40
    return s


def _doc_link_ok(self, text: str, url: str, from_section: str) -> bool:
    lf = _fold(text + " " + urllib.parse.unquote(url))
    if re.search(r"regolament|statuto", lf) and not re.search(r"modul[oi] |domanda di|richiesta di|avviso pubblico", lf):
        return True
    if re.search(r"\bbando\b|bandi|\bgara\b|gare |appalt|avvis[oi]|concors|graduatori|selezione|esito|"
                 r"modulo|moduli|modulistica|domanda|istanza|manifestazione d.interesse|curriculum|\bcv\b|"
                 r"determin[ae]|liquidazione|impegno di spesa|affidamento|cig\b|convocazione|ordine del giorno|"
                 r"pubblicazioni di matrimonio|matrimon|cambio di residenza|elenco|menu|mensa|calendario|"
                 r"orari|volantino|locandina|brochure|depliant|informativa privacy|notiziario|bilancio|rendiconto", lf):
        return False
    if base.GAZETTE_RE.search(lf):
        return False
    if re.search(r"delibera|deliberazione|ordinanza|norme tecniche", lf):
        return True
    if base.DOC_RE.search(lf) and from_section:
        return True
    return bool(from_section) and bool(re.search(r"regolament|statuto|atti generali|atti normativi|disposizioni generali", _fold(from_section)))


def _maybe_html_doc(self, url, rec, soup, heading, via, links, tpl) -> None:
    hf = _fold(heading)
    if not re.search(r"regolament|statuto", hf):
        return
    text = base.html_main_text(soup)
    paras = len(re.findall(r"(?im)^\s*(articolo|art\.)\s*\d+|titolo [ivx]+|capo [ivx]+", _fold(text)))
    if len(text) < 1500 or paras < 3:
        return
    self.add_doc(url, rec, heading, "html", text, via, "", tpl)


_orig_links = base.PlaceCrawler._links


def detect_template(host: str, html: str) -> tuple[str, dict]:
    """Host match first, then HTML fingerprint, for every template (vendor entries carry both)."""
    for name, hre, bre, hints in base.TEMPLATES:
        if hre is not None and hre.search(host):
            return name, hints
    head = (html or "")[:300_000]
    for name, hre, bre, hints in base.TEMPLATES:
        if bre is not None and head and bre.search(head):
            return name, hints
    return "generic", {}


def _links(self, soup, page):
    out = _orig_links(self, soup, page)
    # JCityGov / Liferay menus: anchor text lives in data-resource, real target in data-mainurl
    extra = {}
    for a in soup.find_all("a", attrs={"data-resource": True}):
        res = re.sub(r"\s+", " ", a.get("data-resource", ""))[:300]
        for attr in (("data-mainurl",) if a.get("data-mainurl") else ("href",)):
            v = (a.get(attr) or "").strip()
            if v and not v.lower().startswith(("javascript:", "#", "mailto:")):
                u = base.canon(urllib.parse.urljoin(page, v))
                if u:
                    extra[u] = res
    if extra:
        menu = {base.canon(urllib.parse.urljoin(page, a.get("href", ""))) for a in soup.find_all("a", attrs={"data-mainurl": True})}
        out = [(u, (t + " " + extra[u]).strip() if u in extra else t) for u, t in out if u in extra or u not in menu]
        have = {u for u, _ in out}
        out += [(u, t) for u, t in extra.items() if u not in have]
    if getattr(self, "_it_syn_done", False):
        return out
    self._it_syn_done = True  # first HTML page fetched (homepage or best seed): add vendor entry points
    try:
        html = str(soup)[:300_000]
    except Exception:
        html = ""
    tpl, _ = base.detect_template(base.host_of(page), html)
    self._it_template = tpl
    root = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(page))
    istat = self.t.get("insee_code") or ""
    have = {u for u, _ in out}
    for p in _TPL_PATHS.get(tpl, []) + _GENERIC_PATHS:
        if "{istat}" in p:
            if not istat:
                continue
            p = p.format(istat=istat)
        u = base.canon(root + p)
        if u and u not in have:
            have.add(u)
            out.append((u, _SYN_ANCHOR))
    return out


def _session(self):
    s = getattr(self._local, "s", None)
    if s is None:
        s = base.requests.Session()
        s.headers.update({"User-Agent": base.USER_AGENT,
                          "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5",
                          "Accept-Language": "it-IT,it;q=0.9,en;q=0.5"})
        s.max_redirects = 8
        self._local.s = s
    return s


_orig_add_doc = base.PlaceCrawler.add_doc


def _add_doc(self, url, rec, title, ctype, text, via, extract_err="", template=""):
    return _orig_add_doc(self, url, rec, title, ctype, text, via, extract_err, template or getattr(self, "_it_template", ""))


class _PrioHeap:
    """Frontier shim: lasting law (regolamenti/statuto/atti generali) first, daily albo notices last."""
    import heapq as _h
    _BOOST = re.compile(r"regolament|statuto|atti generali|atti-generali|atti normativi|atti-normativi|disposizioni generali")
    _ALBO = re.compile(r"albo|albopretorio|dettaglio-albo|pubblicazioni")

    def heappush(self, heap, item):
        prio, cnt, url, depth, anchor, from_section = item
        f = _fold(urllib.parse.unquote(url) + " " + (anchor or ""))
        if self._BOOST.search(f):
            prio -= 25
        elif self._ALBO.search(f):
            prio += 35
        self._h.heappush(heap, (prio, cnt, url, depth, anchor, from_section))

    def __getattr__(self, k):
        return getattr(self._h, k)


base.heapq = _PrioHeap()

_orig_wp = base.Runner.write_progress


def _write_progress(self, total, final=False):
    _orig_wp(self, total, final)
    p = json.loads(self.progress_path.read_text())
    p["country_code"] = CC
    tmp = self.progress_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(p, indent=2, ensure_ascii=False))
    tmp.replace(self.progress_path)


base.detect_template = detect_template
base.schema_doc_type = schema_doc_type
base.guess_doc_type = guess_doc_type
base.to_schema_record = to_schema_record
base.load_targets = load_targets
base.score_seed = score_seed
base.place_key = place_key
base.PlaceCrawler._doc_link_ok = _doc_link_ok
base.PlaceCrawler._maybe_html_doc = _maybe_html_doc
base.PlaceCrawler._links = _links
base.PlaceCrawler.add_doc = _add_doc
base.Fetcher.session = _session
base.Runner.write_progress = _write_progress

if __name__ == "__main__":
    if "--build-code-map" in sys.argv:
        build_code_map()
        sys.exit(0)
    if "--out" not in sys.argv:
        sys.argv += ["--out", str(OUT)]
    base.main()
