"""France pilot — harvest + build.

Three platform families (survey 2026-10-14, see france_pilot report):
1. datagouv_static — communes that upload per-act PDFs as resources of
   data.gouv.fr datasets; files live on static.data.gouv.fr (robots:
   /resources/ paths allowed). Jouarre (77238, per-délibération PDFs,
   one dataset per year) and Faugères (07088, per-session PDFs).
2. besancon_webservice — Grand Besançon's municipal affichage service:
   datasets.grandbesancon.fr/besanconfr.php?method=getConseilsMunicipaux
   &year=YYYY&output=json returns sessions -> délibérations with a
   per-délibération PDF URL on the same host (no robots.txt = no rules).
   Besançon (25056).
3. arcgis_hub — Chelles (77108) publishes its délibérations as an
   ArcGIS Hub dataset (FeatureServer on services8.arcgis.com).

The dominant French platform family, Opendatasoft, is NOT harvested:
its standard robots.txt disallows /api/ for User-agent: * (only
Googlebot is allowed) — documented as a dead end, not worked around.

Row splitting: preamble + one row per "Article N" when the act has
articles; otherwise one body row per document (délibérations are single
decisions). Faugères session compilations split per délibération.
PDFs with <100 chars of native text are scanned images -> deferred
(no `fra` tesseract traineddata in the workspace tessroot).

Checkpointed per commune into run_manifest.json; parquets in data/.
"""
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import fitz  # PyMuPDF
import requests

REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.normalize import make_row, finalize_rows, drop_empty_rows  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402
from world_municipal.jurisdiction import get_scheme  # noqa: E402

OUT = Path(__file__).resolve().parent.parent
DATA = OUT / "data"
SCRATCH = OUT / "scratch"
RETRIEVED = "2026-10-14"
FR = get_scheme("FR")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 world-municipal-law-pilot/0.1"
HEADERS = {"User-Agent": UA, "Accept-Language": "fr,en;q=0.5"}
SAMPLE_DOCS = 16  # pilot sample: documents per commune (JP precedent)

REGISTRY = {}
for _l in (DATA / "jurisdictions.jsonl").read_text(encoding="utf-8").splitlines():
    _j = json.loads(_l)
    REGISTRY[_j["jurisdiction_id"]] = _j

COMMUNES = {
    "25056": {"family": "besancon_webservice", "years": [2025, 2024]},
    "07088": {"family": "datagouv_static",
              "datasets": ["deliberations-du-conseil-municipal-de-faugeres-07"]},
    "02722": {"family": "datagouv_static",
              "datasets": ["deliberations-2025-du-conseil-municipal-de-la-ville-de-soissons",
                           "deliberations-2024-du-conseil-municipal-de-la-ville-de-soissons"]},
    "62108": {"family": "datagouv_static",
              "datasets": ["repertoire-des-conseils-municipaux-2020"]},
    "77238": {"family": "datagouv_static",
              "datasets": ["2020-deliberations-du-conseil-municipal-de-jouarre",
                           "2019-deliberations-du-conseil-municipal-de-jouarre",
                           "2018-deliberations-du-conseil-municipal-de-jouarre"]},
}

FR_MONTHS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
             "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
             "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12}
DATE_FR_RE = re.compile(r"(\d{1,2})(?:er)?\s+(janvier|février|fevrier|mars|avril|mai|juin|juillet|"
                        r"août|aout|septembre|octobre|novembre|décembre|decembre)\s+(\d{4})")
DATE_NUM_RE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")
ART_RE = re.compile(r"(?m)^(Article\s+(?:1er|\d+)[^\n]{0,80})$")
MIN_TEXT = 100


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


class Fetcher:
    def __init__(self):
        self.s = requests.Session()
        self._robots = {}
        self._delay = {}

    def _robots_for(self, url):
        parts = urlparse(url)
        key = (parts.scheme, parts.netloc)
        if key not in self._robots:
            # Fetch robots.txt with the session (browser UA + retries) and
            # parse the body ourselves: RobotFileParser.read() marks the
            # whole host disallowed on any transient 4xx, which the flaky
            # egress proxy can produce spuriously (seen on
            # static.data.gouv.fr, whose real rules allow /resources/).
            rp = RobotFileParser()
            rp.set_url(f"{parts.scheme}://{parts.netloc}/robots.txt")
            body = None
            for i in range(4):
                try:
                    r = self.s.get(rp.url, headers=HEADERS, timeout=60)
                    if r.status_code == 200:
                        body = r.text
                        break
                    if r.status_code == 404:
                        body = ""  # no robots file: no rules
                        break
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(3 * (i + 1))
            if body is None:
                self._robots[key] = None  # unreadable after retries: no rules
                self._delay[key] = 0
            else:
                rp.parse(body.splitlines())
                self._robots[key] = rp
                self._delay[key] = rp.crawl_delay(UA) or 0
        return self._robots[key]

    def allows(self, url):
        rp = self._robots_for(url)
        return True if rp is None else rp.can_fetch(UA, url)

    def get(self, url, cache_path=None, timeout=90, attempts=4):
        if cache_path and cache_path.exists() and cache_path.stat().st_size > 0:
            return cache_path.read_bytes()
        if not self.allows(url):
            raise PermissionError(f"robots.txt disallows {url}")
        parts = urlparse(url)
        delay = self._delay.get((parts.scheme, parts.netloc), 0)
        last = None
        for i in range(attempts):
            try:
                r = self.s.get(url, headers=HEADERS, timeout=timeout)
                if r.status_code == 200 and r.content:
                    if cache_path:
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        cache_path.write_bytes(r.content)
                    if delay:
                        time.sleep(min(delay, 60))
                    return r.content
                last = f"HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                last = f"{type(e).__name__}: {str(e)[:120]}"
            time.sleep(3 * (i + 1))
        raise RuntimeError(f"GET failed {url}: {last}")

    def get_json(self, url, cache_path=None):
        return json.loads(self.get(url, cache_path=cache_path).decode("utf-8"))


# ---------------------------------------------------------------- sampling
def even_sample(items, n):
    """Deterministic evenly-spaced sample of n from an ordered list."""
    if len(items) <= n:
        return list(items)
    idx = sorted({round(i * (len(items) - 1) / (n - 1)) for i in range(n)})
    return [items[i] for i in idx]


# ---------------------------------------------------------------- pdf utils
def pdf_text(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = [p.get_text() for p in doc]
    return "\n".join(pages), len(doc)


def text_to_html(text):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        paras = [l.strip() for l in text.splitlines() if l.strip()]
    import html as h
    return "".join(f"<p>{h.escape(p)}</p>" for p in paras)


def split_units(text):
    """-> [(unit_key, label, body_text)] preamble + articles, or one body unit."""
    m = list(ART_RE.finditer(text))
    if len(m) >= 2:
        units = [("preamble", "Préambule", text[: m[0].start()].strip())]
        for i, mm in enumerate(m):
            end = m[i + 1].start() if i + 1 < len(m) else len(text)
            label = mm.group(1).strip()
            units.append((f"article-{i+1}", label, text[mm.start():end].strip()))
        return [(k, l, b) for k, l, b in units if b]
    return [("document", "Document", text.strip())]


def parse_fr_date(text, default=""):
    m = re.search(DATE_FR_RE.pattern, text or "", re.IGNORECASE)
    if m:
        mo = FR_MONTHS.get(m.group(2).lower())
        if mo:
            return f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(1)):02d}"
    m = DATE_NUM_RE.search(text or "")
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return default


OBJET_RE = re.compile(r"(?m)^Objet\s*:\s*(.+)$")
DEL_NUMBER_RE = re.compile(r"N[°º]\s*(\d{4}\s*-\s*\d{1,2}\s*-\s*\d{2,3})")


def split_session_compilation(text):
    """Faugères-style session PDF -> (preamble, [(number, title, segment)]).

    Returns None when the PDF is not a multi-délibération compilation.
    Each délibération starts at an "Objet : ..." line; its number is the
    "N°AAAA-MM-NNN" at the end of that line when present.
    """
    marks = list(OBJET_RE.finditer(text))
    if len(marks) < 2:
        return None
    preamble = text[: marks[0].start()].strip()
    segs = []
    for i, mm in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        seg = text[mm.start():end].strip()
        objet = mm.group(1).strip()
        nm = DEL_NUMBER_RE.search(objet)
        number = re.sub(r"\s+", "", nm.group(1)) if nm else ""
        title = DEL_NUMBER_RE.sub("", objet).rstrip(" -–").strip() or objet
        segs.append((number, title, seg))
    return preamble, segs


# ---------------------------------------------------------------- adapters
def enum_datagouv(fx, code, cfg):
    docs = []
    for slug in cfg["datasets"]:
        api = f"https://www.data.gouv.fr/api/1/datasets/{slug}/"
        data = fx.get_json(api, cache_path=SCRATCH / code / f"dg_{slug}.json")
        for res in data.get("resources", []):
            if (res.get("format") or "").lower() != "pdf":
                continue
            docs.append({
                "title": (res.get("title") or "").rsplit(".", 1)[0].strip(),
                "url": res["url"],
                "date_modified": (res.get("last_modified") or "")[:10],
                "dataset": slug,
            })
    docs.sort(key=lambda d: (d["title"], d["url"]))
    return docs


def doc_id_datagouv(doc):
    base = doc["url"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
    m = re.match(r"(dcm[._-]\d{4}[._-]\d+)", base.lower())  # Soissons dcm.2025.124
    if m:
        return re.sub(r"[._]+", ".", m.group(1))
    m = re.match(r"(\d{4}-\d{2,3})\b", base)
    if m:
        return m.group(1)
    m = re.search(r"(\d{8})", base)
    if m:
        return f"cm-{m.group(1)}"
    return re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[:60]


def is_annexe(doc):
    base = doc["url"].rsplit("/", 1)[-1].lower()
    return "annexe" in base


def enum_besancon(fx, code, cfg):
    docs = []
    for year in cfg["years"]:
        api = ("https://datasets.grandbesancon.fr/besanconfr.php"
               f"?method=getConseilsMunicipaux&year={year}&output=json")
        sessions = fx.get_json(api, cache_path=SCRATCH / code / f"besancon_{year}.json")
        for sess in sessions:
            for d in sess.get("deliberations", []):
                if d.get("urlPdf"):
                    docs.append({"title": (d.get("titre") or "").strip(),
                                 "url": d["urlPdf"],
                                 "date": (d.get("date") or sess.get("date") or "")[:10],
                                 "session": sess.get("titre", "")})
    docs.sort(key=lambda d: (d["date"], d["title"]))
    return docs


def enum_arcgis(fx, code, cfg):
    meta = fx.get_json(cfg["layer"] + "?f=json", cache_path=SCRATCH / code / "arcgis_meta.json")
    fields = [f["name"] for f in meta.get("fields", [])]
    q = (cfg["layer"] + "/query?where=1%3D1&outFields=*&orderByFields=OBJECTID"
         "&resultRecordCount=2000&f=json")
    data = fx.get_json(q, cache_path=SCRATCH / code / "arcgis_query.json")
    feats = data.get("features", [])
    docs = []
    for f in feats:
        a = f.get("attributes", {})
        docs.append({"title": str(a.get("titre") or a.get("objet") or a.get("title") or ""),
                     "attrs": a, "fields": fields})
    return docs, meta


# ---------------------------------------------------------------- build one
def build_commune(fx, code, cfg, manifest):
    info = REGISTRY[code]
    name = info["jurisdiction_name"]
    entry = {"name": name, "family": cfg["family"], "region": info["region_name"],
             "departement": info["departement_name"]}
    manifest["communes"][code] = entry

    if cfg["family"] == "datagouv_static":
        corpus = enum_datagouv(fx, code, cfg)
        get_id, get_date = doc_id_datagouv, None
    elif cfg["family"] == "besancon_webservice":
        corpus = enum_besancon(fx, code, cfg)
        get_id = lambda d: d["url"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()  # noqa: E731
        get_date = lambda d: d.get("date", "")  # noqa: E731
    elif cfg["family"] == "arcgis_hub":
        corpus, meta = enum_arcgis(fx, code, cfg)
        entry["arcgis_fields"] = meta.get("fields") and [f["name"] for f in meta["fields"]]
        entry["arcgis_has_attachments"] = meta.get("hasAttachments")
        entry["corpus_docs"] = len(corpus)
        entry["status"] = "adapter_probe_only"
        manifest_save(manifest)
        return entry  # resolved after inspecting the layer shape
    else:
        raise ValueError(cfg["family"])

    entry["corpus_docs"] = len(corpus)
    main_docs = [d for d in corpus if not is_annexe(d)]
    annexes = [d for d in corpus if is_annexe(d)]
    entry["corpus_annexes"] = len(annexes)
    pool = main_docs if len(main_docs) >= SAMPLE_DOCS else main_docs + annexes
    sample = even_sample(pool, SAMPLE_DOCS)
    entry["sampled_docs"] = len(sample)
    rows, doc_meta = [], []
    name_norm = norm(name)

    def emit(did, title, text, url, date_eff, rec):
        units = split_units(text)
        for ukey, label, body in units:
            rows.append(make_row(
                jurisdiction_id=code, jurisdiction_name=name, country="FR",
                doc_id=f"{did}-{ukey}", regeling_id=did, regeling_work_id=did,
                title=title, structural_path=title, node_label=label,
                body_html=text_to_html(body), source_url=url,
                date_effective=date_eff, date_modified=rec.get("date_modified", ""),
                retrieved=RETRIEVED,
            ))
        return len(units)

    for doc in sample:
        did = get_id(doc)
        rec = {"doc_id": did, "title": doc["title"], "url": doc["url"],
               "date_modified": doc.get("date_modified", "")}
        try:
            pdf = fx.get(doc["url"], cache_path=SCRATCH / code / "pdf" / f"{did}.pdf")
            text, npages = pdf_text(pdf)
        except Exception as e:  # noqa: BLE001
            rec["status"] = f"fetch_failed: {type(e).__name__}: {str(e)[:100]}"
            doc_meta.append(rec)
            continue
        rec["pages"] = npages
        if len(text.strip()) < MIN_TEXT:
            rec["status"] = "ocr_deferred_scanned_pdf"
            doc_meta.append(rec)
            continue
        in_text = name_norm in norm(text)
        rec["attribution"] = "name_in_text" if in_text else "official_listing"
        date_eff = (get_date(doc) if get_date else "") or parse_fr_date(text[:3000])
        comp = split_session_compilation(text)
        if comp:
            preamble, segs = comp
            n = 0
            if preamble:
                n += emit(f"{did}-seance", f"{doc['title']} — séance (ouverture)",
                          preamble, doc["url"], date_eff, rec)
            for i, (number, title, seg) in enumerate(segs):
                sub = number or f"{did}-objet-{i+1}"
                n += emit(sub, title, seg, doc["url"], date_eff, rec)
            rec["rows"] = n
            rec["sub_docs"] = len(segs)
        else:
            rec["rows"] = emit(did, doc["title"], text, doc["url"], date_eff, rec)
        rec["status"] = "ok"
        rec["date_effective"] = date_eff
        doc_meta.append(rec)
        time.sleep(0.5)
    entry["docs"] = doc_meta
    rows = drop_empty_rows(finalize_rows(rows))
    table = rows_to_table(rows)
    errs = validate_table(table, jurisdiction_id=code, jurisdiction_name=name, country="FR")
    entry["rows"] = table.num_rows
    entry["valid"] = not errs
    entry["errors"] = errs
    if table.num_rows == 0:
        ok = sum(1 for d in doc_meta if d.get("status") == "ok")
        defr = sum(1 for d in doc_meta if d.get("status") == "ocr_deferred_scanned_pdf")
        entry["status"] = f"no_publishable_docs (ok={ok}, ocr_deferred={defr})"
    if not errs and table.num_rows:
        write_html_parquet(DATA / FR.file_name(code), table)
        write_validation_report(DATA / f"{code}_validation.json",
                                validation_report(table, jurisdiction_id=code,
                                                    jurisdiction_name=name, country="FR"))
        # re-read gate
        t2 = read_html_parquet(DATA / FR.file_name(code))
        entry["reread_valid"] = not validate_table(
            t2, jurisdiction_id=code, jurisdiction_name=name, country="FR")
    manifest_save(manifest)
    return entry


def manifest_save(manifest):
    (OUT / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    only = sys.argv[1:] or None
    fx = Fetcher()
    manifest = {"retrieved": RETRIEVED, "communes": {}}
    if (OUT / "run_manifest.json").exists():
        manifest = json.loads((OUT / "run_manifest.json").read_text(encoding="utf-8"))
    for code, cfg in COMMUNES.items():
        if only and code not in only:
            continue
        print("===", code, REGISTRY[code]["jurisdiction_name"], cfg["family"], flush=True)
        try:
            e = build_commune(fx, code, cfg, manifest)
            print("   corpus:", e.get("corpus_docs"), "sampled:", e.get("sampled_docs"),
                  "rows:", e.get("rows"), "valid:", e.get("valid"), flush=True)
        except Exception as e:  # noqa: BLE001
            manifest["communes"][code] = {"family": cfg["family"],
                                          "status": f"failed: {type(e).__name__}: {str(e)[:200]}"}
            manifest_save(manifest)
            print("   FAILED:", type(e).__name__, str(e)[:200], flush=True)


if __name__ == "__main__":
    main()
