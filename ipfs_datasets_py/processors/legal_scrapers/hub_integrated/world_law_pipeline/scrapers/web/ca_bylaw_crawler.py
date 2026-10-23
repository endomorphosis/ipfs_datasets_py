#!/usr/bin/env python3
"""Canadian municipal by-law crawler (English + French). Same architecture, politeness and limits as
fr_actes_crawler.py v0.2 (which it imports and re-parameterises): strict RFC 9309 robots (2xx parse,
4xx allow, 5xx/unreachable block), Crawl-delay honoured (>=2 s/host, 1 in flight/host), PDFs streamed to
_tmp -> pdftotext -> temp deleted (no _raw), bounded per-place budgets, resumable via _state.

Targets: CA rows with source_url in global_municipalities_candidate.csv. Codes: pipeline/codes/
place_codes.parquet (prefer ca_sgc_csd; else ca_sgc_cd for regional governments / census divisions,
ca_sgc_dpl for designated places), precomputed to _state/code_map.json by --build-code-map
(needs the pipeline venv for pyarrow). Output: /workspace/world_law/staging/web/CA/
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
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("fr_base", HERE / "fr_actes_crawler.py")
base = importlib.util.module_from_spec(_spec)
sys.modules["fr_base"] = base
_spec.loader.exec_module(base)  # type: ignore[union-attr]

CC = "CA"
OUT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/web/CA"))
CODES = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/codes/place_codes.parquet"))
_fold = base._fold

base.OUT = OUT
base.SOURCE_PLATFORM = "ca_municipal_web"
base.CRAWLER_VERSION = "ca_bylaw_crawler/0.2"
CODE_SYSTEM = "ca_sgc_csd"  # preferred; CD/DPL used when a place has no CSD
# Preference order when building the map (never assign a CD/DPL code under ca_sgc_csd).
CODE_SYSTEMS = ("ca_sgc_csd", "ca_sgc_cd", "ca_sgc_dpl")
VENV_PY = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/venv/bin/python"))
base.SEED_FILE = base.MUNI / "seeds/code_hosts/CA.jsonl"
base.TMP_DIR = OUT / "_tmp"

base.SECTION_RE = re.compile(
    r"by-?laws?|bylaw|by law|municipal code|consolidated by-?laws|bylaw library|by-law library|"
    r"bylaw registry|by-law registry|bylaws? search|policies and by-?laws|policies-and-bylaws|"
    r"reglements? municipaux|reglements-municipaux|reglementation|reglements? d.urbanisme|"
    r"recueil des reglements|codification administrative|reglements? et politiques"
)
base.DOC_RE = re.compile(
    r"by-?law|bylaw|\bno\.? ?\d{1,4}[-/]\d{2,4}|consolidat|regulation|reglement|codification|"
    r"policy|zoning|fees?|tariff|tarif|traffic|parking|noise|nuisance|animal|dog|fire|building|"
    r"business licen|licen[cs]ing|taxation|tax rate|procedure"
)
base.NAV_RE = re.compile(
    r"city hall|town hall|village hall|municipal hall|government|council|municipal|your city|"
    r"your town|residents|services|documents|publications|administration|governance|"
    r"hotel de ville|ville|municipalite|mairie|conseil|citoyens|services"
)
base.EXCLUDE_RE = re.compile(
    r"jobs?|careers?|employment|tenders?|bids?|procurement|rfp|rfq|events?|calendar|news|blog|"
    r"tourism|visitors?|recreation programs|program guide|swim|skating|facebook|instagram|twitter|"
    r"youtube|linkedin|login|sign in|newsletter|subscribe|photos?|gallery|videos?|webcam|weather|"
    r"elections?|contact|accessibility|privacy|careers|donate|shop|/search|\?q=|"
    r"emplois?|offres d.emploi|appels? d.offres|evenements?|nouvelles|actualites|loisirs|"
    r"/tag/|/category/|/author/|wp-json|/feed|print=|share=|replytocom|ical"
)
base.GAZETTE_RE = re.compile(r"newsletter|bulletin|magazine|annual report|community guide|journal municipal|infolettre")
base.DOWNLOAD_HINT = re.compile(
    r"/documentcenter/view/|/weblink/(docview|electronicfile)|electronicfile\.aspx|docview\.aspx|"
    r"civicweb\.net/document|/document/\d+|filestream|getdocument|/download|/uploads/|"
    r"/wp-content/uploads/|/sites/default/files/|/files?/|/media/|/assets/|/docs?/|/documents?/|"
    r"telecharg|fileadmin", re.I)
base.TEMPLATES = [
    ("ecode360", re.compile(r"ecode360\.com$"), None, {}),
    ("civicweb", re.compile(r"civicweb\.net$"), None, {}),
    ("escribe", re.compile(r"escribemeetings\.com$"), None, {}),
    ("laserfiche", None, re.compile(r"/WebLink/|Laserfiche", re.I), {}),
    ("civicplus", None, re.compile(r"civicplus|/DocumentCenter/|CivicPlus", re.I), {}),
    ("esolutions_icreate", None, re.compile(r"esolutionsgroup|iCreate|/en/.*\.aspx", re.I), {}),
    ("granicus_govstack", None, re.compile(r"granicus|govstack|govdelivery", re.I), {}),
    ("civiclive", None, re.compile(r"civiclive|schoolmessenger", re.I), {}),
    ("sitecore", None, re.compile(r"sitecore|/-/media/", re.I), {}),
    ("episerver", None, re.compile(r"episerver|/globalassets/|/contentassets/", re.I), {}),
    ("squarespace", None, re.compile(r"squarespace", re.I), {}),
    ("wix", None, re.compile(r"wixstatic|_wixCssImports|wix\.com", re.I), {}),
    ("wordpress", None, re.compile(r"/wp-content/|/wp-includes/", re.I), {}),
    ("joomla", None, re.compile(r"/media/jui/|Joomla|/media/system/js/", re.I), {}),
    ("drupal", None, re.compile(r"Drupal|/sites/default/files/", re.I), {}),
]
base.GENERIC_ANCHOR_RE = re.compile(
    r"^(view|download|open|read more|click here|here|pdf|document|link|more|details|file|"
    r"consulter|telecharger|voir|ici|lire la suite|\W*)$")

_EN = re.compile(r"\b(the|and|of|shall|council|bylaw|by-law|section|whereas|enacts)\b")
_FR = re.compile(r"\b(le|la|les|et|des|du|conseil|reglement|article|attendu|decrete)\b")

# place_id -> {"code": str, "code_system": str}; filled by load_code_map / build_code_map
_CODE_MAP: dict[str, dict] = {}


def detect_lang(text: str) -> str:
    t = _fold((text or "")[:6000])
    en, fr = len(_EN.findall(t)), len(_FR.findall(t))
    return "fr" if fr > en * 1.2 else "en"


def schema_doc_type(g: str) -> str:
    return {"resolution": "decision", "policy": "regulation", "zoning": "ordinance"}.get(g, "ordinance")


def guess_doc_type(t: str) -> str:
    t = _fold(t)
    if re.search(r"consolidat|codification", t):
        return "consolidated_bylaw"
    if re.search(r"zoning|zonage", t):
        return "zoning"
    if re.search(r"by-?law|bylaw|reglement|\bb\d{3,4}\b|\bno\.? ?\d{1,4}[-/]\d{2,4}", t):
        return "bylaw"
    if re.search(r"resolution", t):
        return "resolution"
    if re.search(r"policy|politique", t):
        return "policy"
    return "other"


def _meta_for(place_id: str, code: str | None = None) -> tuple[str | None, str | None]:
    """Return (place_code, place_code_system) for a place."""
    meta = _CODE_MAP.get(place_id)
    if isinstance(meta, dict):
        c = code or meta.get("code")
        return (c, meta.get("code_system") if c else None)
    if isinstance(meta, str):  # legacy string-only map
        c = code or meta
        return (c, CODE_SYSTEM if c else None)
    return (code, CODE_SYSTEM if code else None)


def to_schema_record(d: dict, order: int) -> dict:
    d["doc_type_guess"] = guess_doc_type((d.get("title") or "") + " " + d.get("doc_url", "") + " " + (d.get("text") or "")[:1500])
    head = _fold((d.get("title") or "") + " " + (d.get("text") or "")[:3000])
    place_code, place_code_system = _meta_for(d["place_id"], d.get("insee_code"))
    if d.get("place_code_system"):
        place_code_system = d["place_code_system"]
    return {
        "place_id": d["place_id"], "country_code": CC,
        "doc_id": base.stable_doc_id(d["requested_url"]), "doc_order": order,
        "source_platform": base.SOURCE_PLATFORM, "source_url": d["doc_url"],
        "doc_type": schema_doc_type(d["doc_type_guess"]),
        "language": detect_lang((d.get("title") or "") + "\n" + (d.get("text") or "")),
        "title_native": base._fr_title(d), "in_force": None,
        "consolidated": bool(re.search(r"consolidat|codification administrative|office consolidation", head)),
        "content_format": "pdf_text" if d["content_type"] == "pdf" else "html",
        "text": d.get("text") or "", "retrieved_at": d.get("fetched_at") or base.now_iso(),
        "place_name": d.get("municipality_name"), "qid": d.get("qid"), "admin_level": d.get("admin_level") or "municipality",
        "place_code": place_code, "place_code_system": place_code_system if place_code else None,
        "platform": base.SOURCE_PLATFORM,
        "municipality_source_url": d.get("source_url"), "homepage": d.get("homepage"),
        "section_url": d.get("section_url"), "requested_url": d.get("requested_url"),
        "doc_type_guess": d.get("doc_type_guess"), "http_content_type": d.get("http_content_type"),
        "sha256": d.get("sha256"), "size_bytes": d.get("size_bytes"),
        "text_extraction": d.get("text_extraction"), "template": d.get("template"), "crawler": base.CRAWLER_VERSION,
    }


def place_key(place_id: str) -> str:
    return base.world_schema.place_key(place_id, None, CC)


def _normalize_map_entry(v) -> dict | None:
    if isinstance(v, dict) and v.get("code"):
        return {"code": str(v["code"]), "code_system": v.get("code_system") or CODE_SYSTEM}
    if isinstance(v, str) and v:
        return {"code": v, "code_system": CODE_SYSTEM}
    return None


def load_code_map() -> dict:
    """place_id -> {code, code_system}. Prefers ca_sgc_csd; else ca_sgc_cd / ca_sgc_dpl.
    Rebuilt (via the pipeline venv, which has pyarrow) when missing, empty, legacy string-valued,
    or older than place_codes.parquet."""
    global _CODE_MAP
    cm = OUT / "_state" / "code_map.json"
    stale = (not cm.exists()) or cm.stat().st_size < 10 or (CODES.exists() and cm.stat().st_mtime < CODES.stat().st_mtime)
    if not stale and cm.exists():
        raw = json.loads(cm.read_text())
        # rebuild if still the old place_id -> bare-string shape
        sample = next(iter(raw.values()), None) if raw else None
        if raw and not isinstance(sample, dict):
            stale = True
    if stale and CODES.exists():
        try:
            import pyarrow  # noqa: F401
            build_code_map()
        except ImportError:
            import subprocess
            subprocess.run([str(VENV_PY), str(Path(__file__).resolve()), "--build-code-map"], check=True)
    if cm.exists():
        raw = json.loads(cm.read_text())
        _CODE_MAP = {k: e for k, v in raw.items() if (e := _normalize_map_entry(v))}
    else:
        _CODE_MAP = {}
    return _CODE_MAP


def load_targets() -> list[dict]:
    codes = load_code_map()
    out, seen = [], set()
    with base.CANDIDATES.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["country_code"] != CC or not r.get("source_url") or not r.get("place_id") or r["place_id"] in seen:
                continue
            seen.add(r["place_id"])
            src = r["source_url"].split(",")[0].strip()
            meta = codes.get(r["place_id"]) or {}
            code = meta.get("code") if isinstance(meta, dict) else meta
            system = meta.get("code_system") if isinstance(meta, dict) and code else (CODE_SYSTEM if code else None)
            out.append({"place_id": r["place_id"], "qid": r["qid"], "name": r.get("place_name"), "country_code": CC,
                        "homepage": src, "source_url": src, "population": r.get("population") or "",
                        "insee_code": code, "place_code_system": system, "code_links": []})
    return out


def _doc_link_ok(self, text: str, url: str, from_section: str) -> bool:
    lf = _fold(text + " " + base.urllib.parse.unquote(url))
    if re.search(r"application form|\bform\b|formulaire|brochure|flyer|newsletter|agenda|minutes|"
                 r"proces-verbal|ordre du jour|\bmap\b|guide|budget|tender|rfp|poster|schedule of events|"
                 r"menu|registration|inscription|annual report|financial statement|avis public|public notice|"
                 r"appel d.offres|derogation mineure|offre d.emploi", lf):
        return False
    if base.GAZETTE_RE.search(lf) and not re.search(r"by-?law|bylaw|reglement", lf):
        return False
    if re.search(r"by-?law|bylaw|reglement|codification|consolidat", lf):
        return True
    if base.DOC_RE.search(lf) and from_section:
        return True
    return bool(from_section)


def _maybe_html_doc(self, url, rec, soup, heading, via, links, tpl) -> None:
    hf = _fold(heading)
    if not re.search(r"by-?law|bylaw|reglement|chapter|municipal code", hf):
        return
    text = base.html_main_text(soup)
    paras = len(re.findall(r"(?im)^\s*(section|article|art\.|part)\s*\d+|whereas|be it enacted|attendu que|"
                           r"enacts as follows|decrete ce qui suit", _fold(text)))
    if len(text) < 1500 or paras < 3:
        return
    self.add_doc(url, rec, heading, "html", text, via, "", tpl)


def _session(self):
    s = getattr(self._local, "s", None)
    if s is None:
        s = base.requests.Session()
        s.headers.update({"User-Agent": base.USER_AGENT.replace("actes administratifs, arretes, deliberations", "by-laws"),
                          "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5",
                          "Accept-Language": "en-CA,en;q=0.9,fr-CA;q=0.8,fr;q=0.7"})
        s.max_redirects = 8
        self._local.s = s
    return s


_orig_wp = base.Runner.write_progress


def _write_progress(self, total, final=False):
    _orig_wp(self, total, final)
    p = json.loads(self.progress_path.read_text())
    p["country_code"] = CC
    tmp = self.progress_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(p, indent=2, ensure_ascii=False))
    tmp.replace(self.progress_path)


base.schema_doc_type = schema_doc_type
base.guess_doc_type = guess_doc_type
base.to_schema_record = to_schema_record
base.load_targets = load_targets
base.place_key = place_key
base.PlaceCrawler._doc_link_ok = _doc_link_ok
base.PlaceCrawler._maybe_html_doc = _maybe_html_doc
base.Fetcher.session = _session
base.Runner.write_progress = _write_progress


def build_code_map() -> None:
    """Build place_id -> {code, code_system} preferring CSD, then CD, then DPL.

    Never stores a census-division (4-digit) or province code under ca_sgc_csd.
    """
    global _CODE_MAP
    import pandas as pd  # pipeline venv (pyarrow)
    pc = pd.read_parquet(CODES)
    pc = pc[(pc.country_code == CC) & (pc.code_system.isin(CODE_SYSTEMS)) & (pc.is_current != False)].copy()  # noqa: E712
    # CSDUIDs are 7 digits; keep CD (4) / DPL (6) under their own systems only.
    is_csd = pc.code_system == "ca_sgc_csd"
    pc = pc[(~is_csd) | (pc.code.astype(str).str.len() == 7)].copy()
    sys_rank = {s: i for i, s in enumerate(CODE_SYSTEMS)}
    pc["_sys"] = pc.code_system.map(sys_rank)
    # deterministic pick within a system: official match, Wikidata preferred rank, then lowest code
    pc["_k"] = list(zip(
        pc._sys,
        pc.official_check.ne("match"),
        pc.wd_rank.ne("PreferredRank"),
        pc.code.astype(str),
    ))
    pc = pc.sort_values("_k")
    m: dict[str, dict] = {}
    for pid, code, system in zip(pc.place_id, pc.code.astype(str), pc.code_system):
        if pid in m:
            continue  # higher-preference system already chosen
        m[pid] = {"code": code, "code_system": system}
    (OUT / "_state").mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_state" / "code_map.json.tmp"
    tmp.write_text(json.dumps(m, ensure_ascii=False, sort_keys=True))
    tmp.replace(OUT / "_state" / "code_map.json")
    _CODE_MAP = m
    by = {}
    for e in m.values():
        by[e["code_system"]] = by.get(e["code_system"], 0) + 1
    print(f"code_map: {len(m)} CA places " + ", ".join(f"{k}={v}" for k, v in sorted(by.items())))


if __name__ == "__main__":
    if "--build-code-map" in sys.argv:
        build_code_map()
        sys.exit(0)
    if "--out" not in sys.argv:
        sys.argv += ["--out", str(OUT)]
    base.main()
