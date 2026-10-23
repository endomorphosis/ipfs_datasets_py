#!/usr/bin/env python3
"""Italy municipal pilot harvester (regolamenti comunali + statuto).

Per comune: robots check -> listing discovery (seed paths + homepage
keyword-link following, depth 2) -> download regolamenti/statuto PDFs
-> extract (PyMuPDF -> pdfplumber -> pdftotext -> tesseract-ita OCR
via the persistent tessroot wrapper) -> split on Art. headings ->
world_municipal 19-column rows -> fail-closed validation -> parquet +
validation sidecar per comune. Everything cached on disk (listings,
PDFs) so reruns resume; summary merged incrementally.

Usage: harvest_it.py CODE [CODE ...]
Artifacts: out/{code}_html.parquet, out/{code}_validation.json,
out/pilot_summary.json, raw/listings/<code>/, raw/pdf/<code>/.
"""
import html as html_mod
import json
import os
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from net import fetch, make_session  # noqa: E402

sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py"))
from ipfs_datasets_py.processors.legal_scrapers.world_municipal import (  # noqa: E402
    jurisdiction,
    normalize,
    parquet_io,
    schema as wm_schema,
)
import pyarrow as pa  # noqa: E402

RAW = HERE.parent / "raw"
OUT = HERE.parent / "out"
RETRIEVED = date.today().isoformat()
PACING_S = 2.0
MAX_DOCS = 40
EXTRA_COLS = [("platform", pa.string())]
TESSERACT = str(Path.home() / "workspace/tools/bin/tesseract")
KW = re.compile(r"regolament|statut|verordnung|satzung", re.I)
DOC_KW = re.compile(r"regolament|statut", re.I)

# Codes and names are ISTAT-registry-exact (verified against
# jurisdictions.jsonl 2026-10-14 — an earlier draft carried wrong
# codes for Colorno/Riva/Arco/Rovereto, caught by the registry
# cross-check below before anything mislabeled could validate).
COMUNI = {
    "034014": dict(name="Fidenza", region="Emilia-Romagna", platform="wordpress",
                   base="https://www.comune.fidenza.pr.it",
                   seeds=["/statuto-e-regolamenti/"]),
    "034010": dict(name="Colorno", region="Emilia-Romagna", platform="plone_myportal",
                   base="https://www.comune.colorno.pr.it",
                   seeds=["/statuto-e-regolamenti", "/regolamenti"]),
    "022153": dict(name="Riva del Garda", region="Trentino-Alto Adige/Südtirol",
                   platform="openpa_opencity",
                   base="https://www.comune.rivadelgarda.tn.it",
                   seeds=["/content/search?SearchText=regolamenti"]),
    "022006": dict(name="Arco", region="Trentino-Alto Adige/Südtirol",
                   platform="openpa_opencity",
                   base="https://www.comune.arco.tn.it",
                   seeds=["/content/search?SearchText=regolamenti"]),
    "021051": dict(name="Merano", region="Trentino-Alto Adige/Südtirol",
                   platform="civis",
                   base="https://www.comune.merano.bz.it", seeds=[]),
    "021013": dict(name="Brunico", region="Trentino-Alto Adige/Südtirol",
                   platform="civis",
                   base="https://www.comune.brunico.bz.it", seeds=[]),
    "022161": dict(name="Rovereto", region="Trentino-Alto Adige/Südtirol",
                   platform="opencity_like",
                   base="https://www.comune.rovereto.tn.it",
                   seeds=["/Amministrazione/Documenti-e-dati"]),
    "022205": dict(name="Trento", region="Trentino-Alto Adige/Südtirol",
                   platform="custom",
                   base="https://www.comune.trento.it", seeds=[]),
    "021008": dict(name="Bolzano", region="Trentino-Alto Adige/Südtirol",
                   platform="custom",
                   base="https://www.comune.bolzano.bz.it", seeds=[]),
    "021004": dict(name="Appiano sulla strada del vino",
                   region="Trentino-Alto Adige/Südtirol", platform="civis",
                   base="https://www.comune.appiano.bz.it", seeds=[]),
    "021040": dict(name="Laives", region="Trentino-Alto Adige/Südtirol",
                   platform="civis",
                   base="https://www.comune.laives.bz.it", seeds=[]),
    "021041": dict(name="Lana", region="Trentino-Alto Adige/Südtirol",
                   platform="civis",
                   base="https://www.comune.lana.bz.it", seeds=[]),
    "022139": dict(name="Pergine Valsugana", region="Trentino-Alto Adige/Südtirol",
                   platform="openpa_opencity",
                   base="https://www.comune.pergine.tn.it",
                   seeds=["/content/search?SearchText=regolamenti"]),
    "022001": dict(name="Ala", region="Trentino-Alto Adige/Südtirol",
                   platform="openpa_opencity",
                   base="https://www.comune.ala.tn.it",
                   seeds=["/content/search?SearchText=regolamenti"]),
    "022104": dict(name="Levico Terme", region="Trentino-Alto Adige/Südtirol",
                   platform="openpa_opencity",
                   base="https://www.comune.levico-terme.tn.it",
                   seeds=["/content/search?SearchText=regolamenti"]),
}

S = make_session()

_REGISTRY = None


def registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = {
            r["code"]: r
            for r in map(json.loads, (OUT / "jurisdictions.jsonl")
                         .read_text(encoding="utf-8").splitlines())
        }
    return _REGISTRY


def robots_check(base):
    """Return (excerpt, disallow_prefixes). Best-effort: unreachable robots
    is recorded, harvest proceeds only for paths not known-disallowed."""
    try:
        status, _, body = fetch(S, base + "/robots.txt", timeout=(15, 30),
                                tries=3, max_bytes=200_000)
        if status != 200:
            return f"robots.txt HTTP {status}", []
        txt = body.decode("utf-8", errors="replace")
        dis = [ln.split(":", 1)[1].strip() for ln in txt.splitlines()
               if ln.strip().lower().startswith("disallow:")
               and len(ln.strip()) > 10]
        return txt[:600], [d for d in dis if d and d != "/"]
    except Exception as e:
        return f"robots unreachable: {type(e).__name__}", []


def is_disallowed(url, dis_prefixes):
    path = urlparse(url).path
    return any(path.startswith(d) for d in dis_prefixes)


def get_page(url, cache_dir, tag):
    """Fetch an HTML page with on-disk cache. Returns (status, final_url, soup)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", tag)[:80]
    cpath = cache_dir / f"{safe}.html"
    if cpath.exists() and cpath.stat().st_size > 0:
        body = cpath.read_bytes()
        status, final = 200, url
    else:
        status, final, body = fetch(S, url, timeout=(20, 90), tries=4,
                                    deadline=600)
        if status == 200:
            cpath.write_bytes(body)
        time.sleep(PACING_S)
    if status != 200:
        return status, final, None
    return status, final, BeautifulSoup(body.decode("utf-8", errors="replace"),
                                        "html.parser")


def discover_docs(code, cfg, dis_prefixes):
    """Return ordered unique [{url, title}] of regolamenti/statuto PDFs."""
    base = cfg["base"]
    cache = RAW / "listings" / code
    listing_urls = [urljoin(base, s) for s in cfg["seeds"]]
    docs, seen_docs = [], set()
    visited = set()

    def scan_page(url, tag, depth):
        if url in visited or len(visited) > 14:
            return
        visited.add(url)
        if is_disallowed(url, dis_prefixes):
            print(f"  robots-disallowed, skip: {url}", flush=True)
            return
        try:
            status, final, soup = get_page(url, cache, tag)
        except Exception as e:
            print(f"  listing FAIL {url}: {type(e).__name__} {e}"[:160], flush=True)
            return
        if soup is None:
            print(f"  listing HTTP {status}: {url}", flush=True)
            return
        follow = []
        for a in soup.find_all("a", href=True):
            href = urljoin(final, a["href"])
            txt = a.get_text(" ", strip=True)
            low = href.lower().split("?")[0]
            is_pdf = low.endswith(".pdf") or "/download" in low and "pdf" in low
            if is_pdf and (DOC_KW.search(href) or DOC_KW.search(txt)
                           or DOC_KW.search(url)):
                if href not in seen_docs and not is_disallowed(href, dis_prefixes):
                    seen_docs.add(href)
                    docs.append({"url": href,
                                 "title": txt or unquote(Path(urlparse(href).path).name),
                                 "listing": final})
            elif (depth < 2 and KW.search(txt) and href.startswith(base)
                    and not low.endswith((".pdf", ".zip", ".doc", ".docx",
                                          ".xls", ".xlsx", ".jpg", ".png"))):
                follow.append((href, txt))
        for href, txt in follow[:8]:
            scan_page(href, f"sub_{txt[:30]}", depth + 1)

    # homepage first (follow its keyword links), then seeds
    scan_page(base, "home", 0)
    for i, u in enumerate(listing_urls):
        scan_page(u, f"seed{i}", 1)
    return docs[:MAX_DOCS], len(visited)


_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f�]")


def garble_ratio(text):
    """Share of control/replacement chars — catches PDFs whose embedded
    font encoding makes digital extraction return glyph garbage
    (observed: Levico Terme OpenPA download, 73% control chars,
    accepted by a naive length check before this gate existed)."""
    if not text:
        return 1.0
    return len(_CTRL_RE.findall(text)) / len(text)


def _usable(text):
    """A digital extraction counts only if it is real text: long enough,
    ~no control chars, not made of (cid:N) glyph tokens (PDFs without
    ToUnicode maps — pdfplumber emits those verbatim), and letters are
    a plausible share of the whole (Italian legal prose ~55-70%)."""
    if len(text.strip()) < 300 or garble_ratio(text) > 0.02:
        return False
    if text.count("(cid:") > len(text) / 2000:
        return False
    letters = sum(1 for ch in text if ch.isalpha())
    return letters / len(text) >= 0.45


def extract_text(pdf_path):
    """PDF chain: PyMuPDF -> pdfplumber -> pdftotext -> OCR(ita).
    Every digital method must pass the garble gate, else fall through
    (OCR renders pixels and is immune to font-encoding garbage).
    Returns (text, method, pages)."""
    import fitz

    pages = 0
    try:
        doc = fitz.open(pdf_path)
        pages = doc.page_count
        text = "\n".join(p.get_text() for p in doc)
        doc.close()
        if _usable(text):
            return text, "pymupdf", pages
    except Exception:
        pass
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            pages = pages or len(pdf.pages)
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        if _usable(text):
            return text, "pdfplumber", pages
    except Exception:
        pass
    try:
        out = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"],
                             capture_output=True, timeout=180)
        text = out.stdout.decode("utf-8", errors="replace")
        if _usable(text):
            return text, "pdftotext", pages
    except Exception:
        pass
    # OCR fallback via the persistent tessroot wrapper (ita)
    try:
        if pages and pages <= 80:
            with __import__("tempfile").TemporaryDirectory() as td:
                subprocess.run(["pdftoppm", "-r", "300", "-png",
                                str(pdf_path), str(Path(td) / "pg")],
                               capture_output=True, timeout=600)
                texts = []
                for img in sorted(Path(td).glob("pg*.png")):
                    o = subprocess.run([TESSERACT, str(img), "stdout",
                                        "-l", "ita"],
                                       capture_output=True, timeout=300)
                    texts.append(o.stdout.decode("utf-8", errors="replace"))
                text = "\n".join(texts)
                if text.strip():
                    return text, "ocr_tesseract_ita", pages
    except Exception:
        pass
    return "", "none", pages


ART_RE = re.compile(
    r"(?m)^[ \t]*(Art\.\s*\d+[a-z]?(?:\s*[-–]\s*[^\n]{0,80})?|Articolo\s+\d+[a-z]?)\s*$"
    r"|^[ \t]*(Art\.\s*\d+[a-z]?)\s+[A-ZÀÈÉÌÒÙ]")


def split_articles(text):
    """Split regolamento text at 'Art. N' / 'Articolo N' headings."""
    matches = list(ART_RE.finditer(text))
    if len(matches) < 2:
        return [("", text.strip())]
    segs = []
    pre = text[: matches[0].start()].strip()
    if len(pre) >= 40:
        segs.append(("Premessa", pre))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        seg = text[m.start():end].strip()
        if seg:
            label = (m.group(1) or m.group(2) or "Art.").strip()
            segs.append((re.sub(r"\s+", " ", label)[:60], seg))
    return segs or [("", text.strip())]


EFF_RE = re.compile(
    r"in vigore[^\n]{0,50}?(\d{1,2})[./](\d{1,2})[./](\d{4})|"
    r"(\d{1,2})[./](\d{1,2})[./](\d{4})[^\n]{0,30}?in vigore", re.I)


def date_effective(text):
    m = EFF_RE.search(text)
    if not m:
        return ""
    g = [x for x in m.groups() if x]
    if len(g) == 3:
        d, mo, y = g
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return ""


def text_to_html(text):
    esc = html_mod.escape(text)
    return "<p>" + esc.replace("\n", "<br/>\n") + "</p>"


def harvest_comune(code):
    cfg = COMUNI[code]
    code = jurisdiction.get_scheme("IT").normalize(code)
    # Fail-closed registry cross-check: the config's name must be the
    # ISTAT registry's name for this exact code (a wrong code/name
    # pairing must never reach a parquet).
    reg = registry().get(code)
    if reg is None:
        raise RuntimeError(f"code {code} not in ISTAT registry")
    if reg["name"] != cfg["name"]:
        raise RuntimeError(
            f"registry name mismatch for {code}: registry={reg['name']!r} "
            f"config={cfg['name']!r}")
    t0 = time.time()
    stats = {"code": code, "name": cfg["name"], "region": cfg["region"],
             "platform": cfg["platform"], "docs_listed": 0, "downloaded": 0,
             "extracted": 0, "scanned_or_empty": 0, "download_failed": 0,
             "name_hits": 0, "pages": 0, "methods": {}}
    # Liveness pre-check tuned to the observed regime (2026-10-14 late:
    # egress not dead but ~30 s+ latency — curl fetched istat.it with a
    # 200 at the 30 s mark while 15 s connect timeouts all failed).
    try:
        fetch(S, cfg["base"], timeout=(20, 60), tries=2, deadline=150,
              max_bytes=100_000)
    except Exception as e:
        stats["errors"] = [f"host unreachable this pass: {type(e).__name__}"]
        stats["rows"] = 0
        stats["valid"] = False
        stats["seconds"] = round(time.time() - t0, 1)
        print(f"{code} {cfg['name']}: SKIPPED (host unreachable)", flush=True)
        return stats
    robots_excerpt, dis = robots_check(cfg["base"])
    stats["robots"] = robots_excerpt[:200]
    stats["robots_disallows"] = dis
    docs, n_pages = discover_docs(code, cfg, dis)
    stats["docs_listed"] = len(docs)
    stats["listing_pages"] = n_pages
    print(f"{code} {cfg['name']}: {len(docs)} docs from {n_pages} listing pages",
          flush=True)
    pdf_dir = RAW / "pdf" / code
    pdf_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    name_probe = cfg["name"].split("/")[0].strip().lower()
    for di, doc in enumerate(docs):
        fname = unquote(Path(urlparse(doc["url"]).path).name) or f"doc{di}.pdf"
        fname = re.sub(r"[^A-Za-z0-9._-]+", "_", fname)[:120]
        dest = pdf_dir / fname
        try:
            if not dest.exists() or dest.stat().st_size == 0:
                status, _, body = fetch(S, doc["url"], binary=True,
                                        timeout=(20, 120), tries=4,
                                        max_bytes=30_000_000, deadline=1200)
                if status != 200 or not body.startswith(b"%PDF"):
                    raise RuntimeError(f"HTTP {status} / not a PDF")
                dest.write_bytes(body)
                time.sleep(PACING_S)
            stats["downloaded"] += 1
        except Exception as e:
            stats["download_failed"] += 1
            print(f"  DL FAIL {doc['url'][:90]}: {e}"[:170], flush=True)
            continue
        text, method, pages = extract_text(dest)
        stats["pages"] += pages
        stats["methods"][method] = stats["methods"].get(method, 0) + 1
        if len(text.strip()) < 100:
            stats["scanned_or_empty"] += 1
            continue
        stats["extracted"] += 1
        if name_probe and name_probe in text.lower():
            stats["name_hits"] += 1
        title = doc["title"] or fname
        slug = normalize.slugify(Path(fname).stem) or f"doc{di}"
        segs = split_articles(text)
        for si, (label, seg) in enumerate(segs):
            doc_id = f"{code}-{slug}"
            if len(segs) > 1:
                doc_id = f"{doc_id}-{si}"
            rows.append(normalize.make_row(
                jurisdiction_id=code,
                jurisdiction_name=cfg["name"],
                country="IT",
                doc_id=doc_id,
                regeling_id=slug,
                regeling_work_id=slug,
                title=title,
                structural_path=title,
                node_label=label,
                body_html=text_to_html(seg),
                text=seg,
                source_url=doc["url"],
                date_effective=date_effective(text),
                date_modified="",
                retrieved=RETRIEVED,
                platform=cfg["platform"],
            ))
    rows = normalize.finalize_rows(normalize.drop_empty_rows(rows))
    table = wm_schema.rows_to_table(rows, extra_columns=EXTRA_COLS)
    report = wm_schema.validation_report(
        table, jurisdiction_id=code, jurisdiction_name=cfg["name"], country="IT")
    if table.num_rows > 0:
        parquet_io.write_html_parquet(OUT / f"{code}_html.parquet", table)
    parquet_io.write_validation_report(OUT / f"{code}_validation.json", report)
    stats["rows"] = table.num_rows
    stats["valid"] = report["valid"]
    stats["errors"] = report["errors"]
    stats["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(stats, ensure_ascii=False), flush=True)
    return stats


def main():
    summary_path = Path(os.environ.get(
        "IT_SUMMARY", str(OUT / "pilot_summary.json")))
    all_stats = []
    if summary_path.exists():
        all_stats = json.loads(summary_path.read_text(encoding="utf-8"))
    by_code = {s["code"]: s for s in all_stats}

    def is_done(code):
        s = by_code.get(code)
        return bool(s and s.get("valid") and s.get("rows", 0) > 0)

    queue = [c for c in sys.argv[1:] if not is_done(c)]
    for c in sys.argv[1:]:
        if is_done(c):
            print(f"skip {c} (already valid in summary)", flush=True)
    # two passes: egress windows open and close over time; a comune that
    # fails pass 1 gets a second chance after the others have run.
    for pass_no in (1, 2):
        remaining = []
        for code in queue:
            st = harvest_comune(code)
            by_code[code] = st
            all_stats = list(by_code.values())
            summary_path.write_text(json.dumps(all_stats, indent=1,
                                               ensure_ascii=False),
                                    encoding="utf-8")
            if not (st.get("valid") and st.get("rows", 0) > 0):
                remaining.append(code)
        queue = remaining
        if not queue:
            break
        print(f"pass {pass_no} done; retrying {queue}", flush=True)


if __name__ == "__main__":
    main()
