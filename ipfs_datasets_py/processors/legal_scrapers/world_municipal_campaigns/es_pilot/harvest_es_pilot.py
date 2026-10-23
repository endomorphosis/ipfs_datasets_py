"""Spain BOP pilot harvester (bounded, local-only, no upload).

Generalizes the NL/PT generalized 19-column parquet (one file per municipio,
jurisdiction_id = INE 5-digit code) to Spain's gazette pattern: municipal
ordenanzas/reglamentos take effect only when published in an official
bulletin. Three different vendor/portal stacks, one adapter each:

  BOCM  (Comunidad de Madrid, Drupal)      -> Madrid 28079, Alcalá 28005
  BOPB  (Diputació de Barcelona, Symfony)  -> Barcelona 08019, Terrassa 08279
  BORM  (Región de Murcia, AngularJS+REST) -> Murcia 30030, Cartagena 30016

Reuse-first: cid_v1_raw_sha256 + strip_tags + compression come from the US
hub parquet_writer (same as NL/PT pilots); PDF fallback chain is the
project's existing one (pdfplumber -> PyMuPDF -> pdftotext -> tesseract).
robots posture honoured per host (BOCM/BOPB advertise Crawl-delay: 10;
BOPB detail PDFs under /anunci/veure-pdf/ are robots-disallowed and never
fetched; BORM serves no robots.txt). Pilot traffic is deliberately small.
"""

from __future__ import annotations

import html as html_mod
import importlib.util
import json
import random
import re
import subprocess
import tempfile
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests  # noqa: F401  (kept for potential future in-process calls)

# ---------------------------------------------------------------- reuse repo code
PW_PATH = (
    Path.home()
    / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"
    / "municipal_law_database_scrapers/hub/parquet_writer.py"
)
_spec = importlib.util.spec_from_file_location("us_parquet_writer", PW_PATH)
pw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pw)

# ---------------------------------------------------------------- constants
UA = ("Mozilla/5.0 (X11; Linux x86_64) ipfs-datasets-es-pilot/0.1 "
      "(bounded pilot; research corpus of official gazettes)")
OUT_ROOT = Path(__file__).resolve().parent
RETRIEVED = datetime.now(timezone.utc).strftime("%Y-%m-%d")
WINDOW = ("2024-10-06", "2026-10-06")  # inclusive, ISO

ES_COLUMNS = [
    "cid", "jurisdiction_id", "jurisdiction_name", "country",
    "doc_id", "regeling_id", "regeling_work_id", "doc_order",
    "title", "structural_path", "node_label",
    "html_title", "html", "text",
    "source_url", "xml_url", "date_effective", "date_modified", "retrieved",
]

MAX_ACTS_PER_MUNICIPIO = 3
ACT_RE = re.compile(
    r"^(Artículo|Article)\s+(único|únic|[0-9]+[ºª]?|[IVXLCDM]+|"
    r"primero|primer|segundo|segon|tercero|tercer|cuarto|quart|quinto|"
    r"cinquè|sexto|sisè|séptimo|setè|octavo|vuitè|noveno|novè|décimo|dècim)\b",
    re.I,
)
CHAP_RE = re.compile(r"^(TÍTULO|TÍTOL|LIBRO|LLIBRE|CAPÍTULO|CAPÍTOL)\s+\S+", re.I)
ORDEN_RE = re.compile(r"ordenanza|ordenança|reglamento|reglament", re.I)


# ---------------------------------------------------------------- polite HTTP
class _Resp:
    """Minimal response shim over curl (host egress is proxy-mediated;
    curl subprocesses proved reliable where in-process clients stall)."""

    def __init__(self, content: bytes):
        self.content = content
        self.headers = {}

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")


class Polite:
    """curl-backed fetcher; delay honours each host's robots Crawl-delay."""

    def __init__(self, delay: float, jar: str | None = None):
        self.delay = delay
        self.jar = jar

    def _run(self, args: list[str], timeout: int) -> _Resp:
        last = None
        for attempt in range(3):
            try:
                p = subprocess.run(
                    ["curl", "-s", "--max-time", str(timeout), "-A", UA, *args],
                    capture_output=True, timeout=timeout + 30)
                if p.returncode != 0:
                    raise RuntimeError(f"curl rc={p.returncode} {args[-1]}")
                time.sleep(self.delay + random.uniform(0, 0.15))
                return _Resp(p.stdout)
            except Exception as e:  # noqa: BLE001
                last = e
                if attempt < 2:
                    time.sleep((2 ** attempt) + random.uniform(0, 1))
                    continue
                raise
        raise RuntimeError(f"fetch failed: {args[-1]}") from last

    def _jar_args(self) -> list[str]:
        return ["-b", self.jar, "-c", self.jar] if self.jar else []

    def get(self, url: str, **kw) -> _Resp:
        return self._run([*self._jar_args(), url],
                         int(kw.get("timeout", 60)))

    def post(self, url: str, data: dict | None = None, **kw) -> _Resp:
        args = [*self._jar_args()]
        for k, v in (data or {}).items():
            args += ["--data-urlencode", f"{k}={v}"]
        return self._run([*args, url], int(kw.get("timeout", 240)))


# ---------------------------------------------------------------- PDF chain
def pdf_to_text(data: bytes) -> str:
    """Existing project PDF chain: pdfplumber -> PyMuPDF -> pdftotext -> OCR."""
    text = ""
    try:  # digital-text layer
        import pdfplumber
        import io
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception:  # noqa: BLE001
        text = ""
    if len(text.strip()) < 200:
        try:
            import fitz
            doc = fitz.open(stream=data, filetype="pdf")
            text = "\n".join(pg.get_text() for pg in doc)
        except Exception:  # noqa: BLE001
            pass
    if len(text.strip()) < 200:
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
                f.write(data)
                f.flush()
                text = subprocess.run(
                    ["pdftotext", "-layout", f.name, "-"],
                    capture_output=True, timeout=120,
                ).stdout.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
    if len(text.strip()) < 200:  # scanned: OCR with the Spanish pack
        try:
            import fitz
            doc = fitz.open(stream=data, filetype="pdf")
            pages = []
            with tempfile.TemporaryDirectory() as td:
                for i, pg in enumerate(doc):
                    png = Path(td) / f"p{i}.png"
                    pg.get_pixmap(dpi=200).save(str(png))
                    out = subprocess.run(
                        ["tesseract", str(png), "stdout", "-l", "spa"],
                        capture_output=True, timeout=180,
                    )
                    pages.append(out.stdout.decode("utf-8", "replace"))
            text = "\n".join(pages)
        except Exception:  # noqa: BLE001
            pass
    return text


# ---------------------------------------------------------------- text -> rows
def split_segments(text: str, preamble_label: str) -> list[dict]:
    """Group plain-text lines into preamble/article segments with chapters."""
    lines = [ln.strip() for ln in (text or "").replace("\r", "").split("\n")]
    segments: list[dict] = []
    chapter = ""
    label, path = preamble_label, ""
    cur: list[str] = []

    def flush():
        body = "\n".join(cur).strip()
        if body:
            segments.append({"label": label, "path": path or label, "text": body})

    i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln:
            cur.append("")
            i += 1
            continue
        if CHAP_RE.match(ln) and len(ln) <= 120:
            chapter = ln
            cur.append(ln)
            i += 1
            continue
        if ACT_RE.match(ln):
            flush()
            label = ln
            # plain-text heading often packs "Artículo 1. Objeto." on one line;
            # if it is a bare number, a short next line is the article title
            bare = re.fullmatch(r"(Artículo|Article)\s+\S+\.?º?ª?", ln, re.I)
            if bare and i + 1 < len(lines):
                nxt = lines[i + 1]
                if nxt and len(nxt) <= 110 and not nxt.endswith(".") \
                        and not ACT_RE.match(nxt) and not CHAP_RE.match(nxt):
                    label = f"{ln} — {nxt}"
                    i += 1
            path = " > ".join(p for p in (chapter, label) if p)
            cur = []
            i += 1
            continue
        cur.append(ln)
        i += 1
    flush()
    # drop a leading segment that is only gazette boilerplate (very short)
    if segments and segments[0]["label"] == preamble_label \
            and len(segments[0]["text"]) < 40 and len(segments) > 1:
        segments.pop(0)
    return segments


def paras_html(text: str) -> str:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return "".join(
        "<p>" + html_mod.escape(" ".join(p.split("\n"))).strip() + "</p>"
        for p in paras
    ) or "<p>" + html_mod.escape(text.strip()) + "</p>"


def slugify(label: str, fallback: str) -> str:
    s = re.sub(r"[^0-9a-zà-ÿ]+", "-", label.lower()).strip("-")
    return s or fallback


def make_rows(act: dict, juris_id: str, juris_name: str,
              order_start: int) -> list[dict]:
    preamble = "Preàmbul" if act.get("lang") == "ca" else "Preámbulo"
    segs = split_segments(act["text"], preamble)
    used: dict[str, int] = {}
    rows = []

    def uniq(base: str) -> str:
        n = used.get(base, 0) + 1
        used[base] = n
        return base if n == 1 else f"{base}-{n}"

    for seg in segs:
        doc_id = f"{act['regeling_id']}/{uniq(slugify(seg['label'], 'preambulo'))}"
        html_doc = f'<div class="chunk-content">{paras_html(seg["text"])}</div>'
        rows.append({
            "cid": pw.cid_v1_raw_sha256(f"{juris_id}_{doc_id}.json"),
            "jurisdiction_id": juris_id,
            "jurisdiction_name": juris_name,
            "country": "ES",
            "doc_id": doc_id,
            "regeling_id": act["regeling_id"],
            "regeling_work_id": act["work_id"],
            "doc_order": order_start + len(rows),
            "title": act["title"],
            "structural_path": seg["path"],
            "node_label": seg["label"],
            "html_title": f'<div class="chunk-title">'
                          f'{html_mod.escape(seg["label"])}</div>',
            "html": html_doc,
            "text": pw.strip_tags(html_doc),
            "source_url": act["source_url"],
            "xml_url": act.get("xml_url", ""),
            "date_effective": act["date"],
            "date_modified": act["date"],
            "retrieved": RETRIEVED,
        })
    return rows


def write_parquet(path: Path, rows: list[dict]) -> int:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {}
    for col in ES_COLUMNS:
        if col == "doc_order":
            arrays[col] = pa.array([int(r[col]) for r in rows], type=pa.uint32())
        else:
            arrays[col] = pa.array([str(r.get(col, "")) for r in rows])
    table = pa.table(arrays)
    pq.write_table(table, str(path), compression=pw._compression())
    return table.num_rows


# ---------------------------------------------------------------- BOCM
BOCM = "https://www.bocm.es"


def bocm_candidates(http: Polite, org_id: str, want: int, log) -> list[dict]:
    """Page the organismo filter (recent-first), title/regex + window filter."""
    out = []
    for page in range(45):
        url = f"{BOCM}/advanced-search/p/field_orden_organo_y_organismo_3/{org_id}/seccion/8387"
        if page:
            url += f"/page/{page}"
        r = http.get(url)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "lxml")
        rows = []
        for art in soup.select("article.node-orden"):
            about = (art.get("about") or "").strip("/")
            desc = art.select_one(
                ".field-name-field-short-description .field-item")
            if about and desc:
                rows.append((about.upper(),
                             desc.get_text(" ", strip=True).lstrip("–- ").strip()))
        if not rows:
            log(f"bocm page {page}: no rows, stop")
            break
        log(f"bocm page {page}: {len(rows)} results, {len(out)} candidates so far")
        dates = [c[5:13] for c, _ in rows]  # YYYYMMDD out of CVE
        for cve, title in rows:
            d = f"{cve[5:9]}-{cve[9:11]}-{cve[11:13]}"
            if WINDOW[0] <= d <= WINDOW[1] and ORDEN_RE.search(title):
                out.append({"cve": cve, "title": title, "date": d})
                if len(out) >= want:
                    return out
        if max(dates) < WINDOW[0].replace("-", ""):
            log(f"bocm page {page}: all pre-window, stop")
            break
    return out


def bocm_detail(http: Polite, cand: dict) -> dict | None:
    url = f"{BOCM}/{cand['cve'].lower()}"
    r = http.get(url)
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>',
                  r.text, re.S)
    if not m:
        return None
    d = json.loads(m.group(1))
    text = (d.get("text") or "").strip()
    if not text:
        return None
    pdf_url = ""
    for enc in d.get("encoding") or []:
        if enc.get("encodingFormat") == "application/pdf":
            pdf_url = enc.get("contentUrl", "")
    date = (d.get("datePublished") or "").replace("/", "-")
    if pdf_url and len([s for s in split_segments(text, "Preámbulo")
                        if ACT_RE.match(s["label"])]) < 2:
        # JSON-LD text is often just the approval announcement; the signed
        # PDF carries the full ordinance text.
        try:
            rp = http.get(pdf_url, timeout=120)
            if rp.content[:4] == b"%PDF":
                ptext = pdf_to_text(rp.content).strip()
                if len(ptext) > len(text):
                    text = ptext
        except Exception:  # noqa: BLE001
            pass
    return {
        "regeling_id": d.get("legislationIdentifier") or cand["cve"],
        "work_id": cand["cve"],
        "title": (d.get("name") or cand["title"]).strip(),
        "text": text,
        "source_url": url,
        "xml_url": pdf_url,
        "date": date or cand["date"],
        "lang": "es",
    }


# ---------------------------------------------------------------- BORM
BORM = "https://www.borm.es"
AYTO_IDS_FILE = OUT_ROOT / "borm_ayuntamientos.json"


def borm_candidates(http: Polite, ayto_id: int, want: int, log) -> list[dict]:
    """Per-ayuntamiento reverse-chronological anuncio list (REST, paged)."""
    out = []
    for page in range(1, 31):
        r = http.get(f"{BORM}/services/anuncio/ayuntamiento/{ayto_id}?pagina={page}")
        root = ET.fromstring(r.content)
        items = []
        for li in root.iter("listItems"):
            f = {c.tag: (c.text or "") for c in li}
            if f.get("id"):
                items.append(f)
        if not items:
            log(f"borm page {page}: empty, stop")
            break
        log(f"borm page {page}: {len(items)} items, {len(out)} candidates so far")
        oldest = None
        for f in items:
            ts = int(f.get("fechaPublicacion") or 0) // 1000
            d = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
            oldest = d
            s = f.get("sumario", "")
            if WINDOW[0] <= d <= WINDOW[1] and ORDEN_RE.search(s) \
                    and re.search(r"definitiva", s, re.I):
                out.append({"id": f["id"], "title": s.strip(), "date": d,
                            "pages": int(f.get("paginas") or 0),
                            "numero": f.get("numero", ""),
                            "boletin": f.get("numeroBoletin", "")})
                if len(out) >= want:
                    return out
        if oldest and oldest < WINDOW[0]:
            log(f"borm page {page}: reached {oldest} (pre-window), stop")
            break
    return out


def borm_detail(http: Polite, cand: dict, name: str) -> dict | None:
    r = http.get(f"{BORM}/services/anuncio/{cand['id']}/txt")
    text = r.content.decode("utf-8", "replace").strip()
    if len(text) < 200:  # announcement-only or empty: try the PDF chain once
        rp = http.get(f"{BORM}/services/anuncio/{cand['id']}/pdf")
        if rp.content[:4] == b"%PDF":
            text = pdf_to_text(rp.content).strip()
    lines = [ln.strip() for ln in text.split("\n")]
    # drop the 3-line gazette header (section / municipio / anuncio number)
    if len(lines) > 4 and lines[1].lower() == name.lower():
        text = "\n".join(lines[3:]).strip()
    return {
        "regeling_id": cand["id"],
        "work_id": f"BORM núm. {cand['boletin']} anuncio {cand['numero']}",
        "title": cand["title"],
        "text": text,
        "source_url": f"{BORM}/services/anuncio/{cand['id']}/txt",
        "xml_url": f"{BORM}/services/anuncio/{cand['id']}/pdf",
        "date": cand["date"],
        "lang": "es",
    }


# ---------------------------------------------------------------- BOPB
BOPB = "https://bop.diba.cat"
TIPUS_DEFINITIVA = ["46", "44", "48"]  # reguladores / fiscals / reglaments, def.


def bopb_search(http: Polite, org_id: str, tipus: str) -> str:
    r = http.get(f"{BOPB}/cercador-butlletins")
    m = re.search(r'name="cerca_avancada\[_token\]"[^>]*value="([^"]+)"', r.text) \
        or re.search(r'value="([^"]+)"[^>]*name="cerca_avancada\[_token\]"', r.text)
    data = {
        "cerca_avancada[paraulaClau]": "",
        "cerca_avancada[dataInici]": WINDOW[0],
        "cerca_avancada[dataFinal]": WINDOW[1],
        "cerca_avancada[tipologiaAnunciant][tipologiaAnunciant4]": org_id,
        "cerca_avancada[tipusAnunci][tipusAnunci2]": tipus,
        "cerca_avancada[_token]": m.group(1),
    }
    return http.post(f"{BOPB}/cercador-butlletins", data=data).text


def bopb_detail(http: Polite, url: str) -> dict | None:
    r = http.get(url)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "lxml")
    # full text lives in the anuncio body container; fall back to <main>
    node = soup.select_one(".anunci") or soup.find("main") or soup.body
    text = node.get_text("\n", strip=False) if node else ""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    cve = ""
    m = re.search(r"(CVE[- ]?[A-Za-z0-9-]+|codi de verificaci)", r.text, re.I)
    if m:
        cve = m.group(1)
    return {"html": r.text, "text": text, "cve": cve,
            "pdf_disallowed": "/anunci/veure-pdf/" in r.text}


# ---------------------------------------------------------------- run model
MUNICIPIOS = [
    # adapter, name (INE denomination), INE code, source params, ayuntamiento string
    ("bocm", "Madrid", "28079", {"org": "12817"}, "Ayuntamiento de Madrid"),
    ("bocm", "Alcalá de Henares", "28005", {"org": "12818"},
     "Ayuntamiento de Alcalá de Henares"),
    ("bopb", "Barcelona", "08019", {"org": "org-240"}, "Ajuntament de Barcelona"),
    ("bopb", "Terrassa", "08279", {"org": "org-665"}, "Ajuntament de Terrassa"),
    ("borm", "Murcia", "30030", {"ayto": 172}, "Ayuntamiento de Murcia"),
    ("borm", "Cartagena", "30016", {"ayto": 189}, "Ayuntamiento de Cartagena"),
]


def attribution_ok(act: dict, ayto: str, name: str) -> bool:
    head = act["text"][:3000].upper()
    return ayto.upper() in head or name.upper() in act["title"].upper() \
        or act["title"].upper().startswith(name.upper())


def article_count(act: dict) -> int:
    return sum(1 for ln in act["text"].split("\n") if ACT_RE.match(ln.strip()))


def main(only: set[str]):
    summary = {"window": list(WINDOW), "municipios": {}, "failures": []}

    def log(msg):
        print(msg, flush=True)

    http10 = Polite(10.2)   # bocm.es robots Crawl-delay: 10
    http10j = Polite(10.2, jar="/tmp/diba_jar_harvest.txt")  # bopb session
    http_fast = Polite(0.6)

    def checkpoint():
        (OUT_ROOT / "pilot_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False))

    only_names = {s.strip() for s in
                    __import__("os").environ.get("ES_ONLY", "").split(",")
                    if s.strip()}
    for adapter, name, code, params, ayto in MUNICIPIOS:
        if adapter not in only:
            continue
        if only_names and name not in only_names:
            continue
        log(f"== {name} ({code}) via {adapter} ==")
        entry = {"ine_code": code, "adapter": adapter,
                 "candidates": 0, "fetched": 0, "announcement_only": 0,
                 "rows_written": 0}
        acts: list[dict] = []
        try:
            if adapter == "bocm":
                cands = bocm_candidates(http10, params["org"],
                                        MAX_ACTS_PER_MUNICIPIO * 2, log)
                entry["candidates"] = len(cands)
                for c in cands:
                    if len(acts) >= MAX_ACTS_PER_MUNICIPIO:
                        break
                    try:
                        act = bocm_detail(http10, c)
                    except Exception as e:  # noqa: BLE001
                        summary["failures"].append(f"{c['cve']}: {e}")
                        continue
                    if act and attribution_ok(act, ayto, name) \
                            and article_count(act) >= 2:
                        acts.append(act)
                        log(f"  + {c['cve']}: kept ({article_count(act)} articles)")
                    elif act:
                        entry["announcement_only"] += 1
                        log(f"  - {c['cve']}: rejected (articles="
                            f"{article_count(act)}, attrib="
                            f"{attribution_ok(act, ayto, name)})")
            elif adapter == "borm":
                cands = borm_candidates(http_fast, params["ayto"],
                                        MAX_ACTS_PER_MUNICIPIO * 2, log)
                entry["candidates"] = len(cands)
                for c in cands:
                    if len(acts) >= MAX_ACTS_PER_MUNICIPIO:
                        break
                    try:
                        act = borm_detail(http_fast, c, name)
                    except Exception as e:  # noqa: BLE001
                        summary["failures"].append(f"borm {c['id']}: {e}")
                        continue
                    if act and attribution_ok(act, ayto, name) \
                            and article_count(act) >= 2:
                        acts.append(act)
                        log(f"  + borm {c['id']}: kept ({article_count(act)} articles)")
                    elif act:
                        entry["announcement_only"] += 1
                        log(f"  - borm {c['id']}: rejected (articles="
                            f"{article_count(act)}, attrib="
                            f"{attribution_ok(act, ayto, name)})")
            elif adapter == "bopb":
                Path("/tmp/diba_jar_harvest.txt").unlink(missing_ok=True)
                found: list[dict] = []
                for tipus in TIPUS_DEFINITIVA:
                    if found:
                        break
                    html_doc = bopb_search(http10j, params["org"], tipus)
                    (OUT_ROOT / f"bopb_results_{code}_{tipus}.html").write_text(html_doc)
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html_doc, "lxml")
                    for a in soup.find_all("a", href=re.compile(r"/anunci/")):
                        href = a["href"]
                        if "veure-pdf" in href or "descarrega-pdf" in href:
                            continue  # robots-disallowed endpoints
                        found.append({"url": urllib.parse.urljoin(BOPB, href),
                                      "title": a.get_text(" ", strip=True)})
                entry["candidates"] = len(found)
                for c in found[:MAX_ACTS_PER_MUNICIPIO * 2]:
                    if len(acts) >= MAX_ACTS_PER_MUNICIPIO:
                        break
                    try:
                        det = bopb_detail(http10j, c["url"])
                    except Exception as e:  # noqa: BLE001
                        summary["failures"].append(f"bopb {c['url']}: {e}")
                        continue
                    act = {"regeling_id": det["cve"] or c["url"].rstrip("/").split("/")[-1],
                           "work_id": c["url"], "title": c["title"],
                           "text": det["text"], "source_url": c["url"],
                           "xml_url": "", "date": WINDOW[1], "lang": "ca",
                           "pdf_only": det["pdf_disallowed"]}
                    if attribution_ok(act, ayto, name) \
                            and article_count(act) >= 2:
                        acts.append(act)
                        log(f"  + {c['url']}: kept ({article_count(act)} articles)")
                    elif act:
                        entry["announcement_only"] += 1
                        log(f"  - {c['url']}: rejected (articles="
                            f"{article_count(act)}, attrib="
                            f"{attribution_ok(act, ayto, name)})")
            else:
                raise ValueError(adapter)
        except Exception as e:  # noqa: BLE001
            summary["failures"].append(f"{name}: {type(e).__name__} {e}")

        rows: list[dict] = []
        for act in acts:
            rows.extend(make_rows(act, code, name, len(rows)))
        entry["fetched"] = len(acts)
        if rows:
            out = OUT_ROOT / "spain_law" / "data" / f"{code}_html.parquet"
            entry["rows_written"] = write_parquet(out, rows)
            entry["parquet"] = str(out)
            log(f"  wrote {entry['rows_written']} rows -> {out}")
        summary["municipios"][name] = entry
        checkpoint()

    (OUT_ROOT / "pilot_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import sys
    only = set(sys.argv[1].split(",")) if len(sys.argv) > 1 else {"bocm", "bopb", "borm"}
    main(only)
