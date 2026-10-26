#!/usr/bin/env python3
"""Germany municipal-law pilot harvester.

Per-Gemeinde official Ortsrecht/Satzungen PDF collections on the
Gemeinden's own websites. Document lists were enumerated via Wayback
CDX over the official domains (raw/cdx_<domain>.json). Downloads try
the LIVE official URL first and fall back to the Wayback snapshot of
that same official URL (archive-only pattern for hosts that hang from
this egress); the route used is recorded per document.

Extraction: PyMuPDF -> pdfplumber -> pdftotext -> OCR (pdftoppm +
persistent tessroot tesseract, deu) for scanned docs. Rows split on
§ headings into the world_municipal 19-column schema; fail-closed
validation; one parquet + validation sidecar per Gemeinde (AGS).

Usage: harvest_de_pilot.py AGS [AGS ...]
Artifacts: data/{ags}_html.parquet, data/{ags}_validation.json,
out/pilot_summary.json (merged), raw/pdf/<ags>/ PDF cache (resume-safe).
"""
import html as html_mod
import json
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py"))
from ipfs_datasets_py.processors.legal_scrapers.world_municipal import (  # noqa: E402
    jurisdiction,
    normalize,
    parquet_io,
    schema as wm_schema,
)
import pyarrow as pa  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
RAW = HERE / "raw"
DATA = HERE / "data"
OUT = HERE / "out"
RETRIEVED = date.today().isoformat()
PACING_S = 2.0
EXTRA_COLS = [("sammlung", pa.string()), ("source_route", pa.string())]
TESSERACT = str(Path.home() / "workspace/tools/bin/tesseract")

S = requests.Session()
S.headers["User-Agent"] = (
    "ipfs_datasets_py world-municipal pilot (open legal data research)"
)

# Pilot Gemeinden: AGS -> (registry name, cdx file, path filter, sammlung label)
GEMEINDEN = {
    "01051044": ("Heide, Stadt", "cdx_heide_de.json",
                 "/fileadmin/heide_de/inhalte/Rathaus_und_Buergerservice/Ortsrecht/",
                 "Ortsrecht (aktuelle Sammlung)"),
    "01051011": ("Brunsbüttel, Stadt", "cdx_brunsbuettel_de.json",
                 "/rathaus/satzungen/", "Satzungen (Nummernsammlung, Altbestand)"),
    "05554004": ("Ahaus, Stadt", "cdx_ahaus_de.json",
                 "/fileadmin/ahaus/Rathaus/Ortsrecht/", "Ortsrecht"),
    "05554012": ("Borken, Stadt", "cdx_borken_de.json",
                 "/Ortsrecht/", "Ortsrecht"),
}


def doc_list(ags):
    _, cdx_file, path_filter, _ = GEMEINDEN[ags]
    rows = json.loads((RAW / cdx_file).read_text(encoding="utf-8"))
    seen, docs = set(), []
    for r in rows:
        p = unquote(urlparse(r["url"]).path)
        if path_filter not in p:
            continue
        if not p.lower().endswith(".pdf"):
            continue
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        docs.append({"url": r["url"], "ts": r["ts"], "path": p})
    docs.sort(key=lambda d: d["path"])
    return docs


def title_from_path(path: str) -> str:
    base = unquote(path.rsplit("/", 1)[-1])
    base = re.sub(r"\.pdf$", "", base, flags=re.I)
    base = base.replace("_", " ").replace("-", " ")
    base = re.sub(r"\s+", " ", base).strip()
    return base


def fetch_live(url: str, tries: int = 1) -> bytes:
    last = None
    for i in range(tries):
        try:
            r = S.get(url, timeout=30)
            r.raise_for_status()
            if len(r.content) > 200 and r.content[:4] == b"%PDF":
                return r.content
            raise ValueError(f"not a PDF ({r.headers.get('Content-Type')}, {len(r.content)}B)")
        except Exception as e:
            last = e
            time.sleep(6 * (i + 1))
    raise last


def fetch_wayback(url: str, ts: str, tries: int = 4) -> bytes:
    wb = f"https://web.archive.org/web/{ts}id_/{url}"
    last = None
    for i in range(tries):
        try:
            r = S.get(wb, timeout=90)
            r.raise_for_status()
            if len(r.content) > 200 and r.content[:4] == b"%PDF":
                return r.content
            raise ValueError(f"not a PDF ({len(r.content)}B)")
        except Exception as e:
            last = e
            time.sleep(15 * (i + 1))
    raise last


def extract_text(pdf_path: Path):
    """PDF chain: PyMuPDF -> pdfplumber -> pdftotext -> OCR (tessroot, deu)."""
    import fitz

    pages = 0
    try:
        doc = fitz.open(pdf_path)
        pages = doc.page_count
        text = "\n".join(p.get_text() for p in doc)
        doc.close()
        if len(text.strip()) >= 300:
            return text, "pymupdf", pages
    except Exception:
        pass
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            pages = pages or len(pdf.pages)
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        if len(text.strip()) >= 300:
            return text, "pdfplumber", pages
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True, timeout=120)
        text = out.stdout.decode("utf-8", errors="replace")
        if len(text.strip()) >= 300:
            return text, "pdftotext", pages
    except Exception:
        pass
    # OCR fallback: render pages at 300 dpi, tesseract deu
    try:
        with_prefix = pdf_path.with_suffix("")
        subprocess.run(
            ["pdftoppm", "-png", "-r", "200", str(pdf_path), str(with_prefix) + "_pg"],
            capture_output=True, timeout=600, check=True)
        texts = []
        for img in sorted(pdf_path.parent.glob(pdf_path.stem + "_pg*.png")):
            o = subprocess.run([TESSERACT, str(img), "stdout", "-l", "deu", "--psm", "6"],
                               capture_output=True, timeout=300)
            texts.append(o.stdout.decode("utf-8", errors="replace"))
            img.unlink(missing_ok=True)
        text = "\n".join(texts)
        if text.strip():
            return text, "ocr-tesseract-deu", pages
    except Exception:
        pass
    return "", "none", pages


SEC_RE = re.compile(r"(?m)^[ \t]*(§[ \t]*\d+[a-z]?)\b[ \t]*(.*)$")


def split_articles(text: str):
    matches = list(SEC_RE.finditer(text))
    if not matches:
        return [("", text.strip())]
    segs = []
    pre = text[: matches[0].start()].strip()
    if len(pre) >= 40:
        segs.append(("Präambel", pre))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        seg = text[m.start():end].strip()
        if seg:
            segs.append((m.group(1).replace(" ", ""), seg))
    return segs


EFF_RE = re.compile(
    r"in Kraft[^\n]{0,60}?(\d{1,2})\.(\d{1,2})\.(\d{4})|"
    r"(\d{1,2})\.(\d{1,2})\.(\d{4})[^\n]{0,40}?in Kraft"
)


def date_effective(text: str) -> str:
    m = EFF_RE.search(text)
    if not m:
        return ""
    g = [x for x in m.groups() if x]
    if len(g) == 3:
        d, mo, y = g
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return ""


def text_to_html(text: str) -> str:
    esc = html_mod.escape(text)
    return "<p>" + esc.replace("\n", "<br/>\n") + "</p>"


def harvest(ags: str) -> dict:
    t0 = time.time()
    ags = jurisdiction.get_scheme("DE").normalize(ags)
    reg_name, _, _, sammlung = GEMEINDEN[ags]
    docs = doc_list(ags)
    pdf_dir = RAW / "pdf" / ags
    pdf_dir.mkdir(parents=True, exist_ok=True)
    name_probe = reg_name.split(",")[0].strip()
    rows, stats = [], {
        "ags": ags, "name": reg_name, "docs_listed": len(docs),
        "downloaded": 0, "extracted": 0, "scanned_or_empty": 0,
        "download_failed": 0, "name_hits": 0, "pages": 0,
        "methods": {}, "routes": {},
    }
    # Brunsbüttel's live collection path is retired (404) — Wayback first.
    wayback_first = ags == "01051011"
    live_fail_streak = 0
    for doc in docs:
        fname = unquote(doc["path"].rsplit("/", 1)[-1])
        dest = pdf_dir / fname
        route = "cache"
        try:
            if not dest.exists() or dest.stat().st_size == 0:
                if wayback_first:
                    try:
                        data = fetch_wayback(doc["url"], doc["ts"])
                        route = "wayback"
                    except Exception:
                        data = fetch_live(doc["url"])
                        route = "live"
                else:
                    try:
                        data = fetch_live(doc["url"])
                        route = "live"
                        live_fail_streak = 0
                    except Exception:
                        live_fail_streak += 1
                        if live_fail_streak >= 5:
                            wayback_first = True
                        data = fetch_wayback(doc["url"], doc["ts"])
                        route = "wayback"
                dest.write_bytes(data)
                time.sleep(PACING_S)
            stats["downloaded"] += 1
            stats["routes"][route] = stats["routes"].get(route, 0) + 1
        except Exception as e:
            stats["download_failed"] += 1
            print(f"  DL FAIL {ags} {fname}: {type(e).__name__} {str(e)[:90]}", flush=True)
            continue
        text, method, pages = extract_text(dest)
        stats["pages"] += pages
        stats["methods"][method] = stats["methods"].get(method, 0) + 1
        if len(text.strip()) < 100:
            stats["scanned_or_empty"] += 1
            continue
        stats["extracted"] += 1
        if name_probe and name_probe.lower() in text.lower():
            stats["name_hits"] += 1
        title = title_from_path(doc["path"])
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
        eff = date_effective(text)
        segs = split_articles(text)
        for si, (label, seg) in enumerate(segs):
            doc_id = f"{ags}-{slug}"
            if len(segs) > 1:
                doc_id = f"{doc_id}-{si}"
            rows.append(normalize.make_row(
                jurisdiction_id=ags,
                jurisdiction_name=reg_name,
                country="DE",
                doc_id=doc_id,
                regeling_id=slug,
                regeling_work_id=slug,
                title=title,
                structural_path=title,
                node_label=label,
                body_html=text_to_html(seg),
                text=seg,
                source_url=doc["url"],
                date_effective=eff,
                retrieved=RETRIEVED,
                sammlung=sammlung,
                source_route=route,
            ))
    rows = normalize.finalize_rows(normalize.drop_empty_rows(rows))
    table = wm_schema.rows_to_table(rows, extra_columns=EXTRA_COLS)
    report = wm_schema.validation_report(
        table, jurisdiction_id=ags, jurisdiction_name=reg_name, country="DE")
    DATA.mkdir(parents=True, exist_ok=True)
    parquet_io.write_html_parquet(DATA / f"{ags}_html.parquet", table)
    parquet_io.write_validation_report(DATA / f"{ags}_validation.json", report)
    stats["rows"] = table.num_rows
    stats["valid"] = report["valid"]
    stats["errors"] = report["errors"]
    stats["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(stats, ensure_ascii=False), flush=True)
    return stats


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary_path = OUT / "pilot_summary.json"
    all_stats = []
    if summary_path.exists():
        all_stats = json.loads(summary_path.read_text(encoding="utf-8"))
    done = {s["ags"] for s in all_stats}
    for ags in sys.argv[1:]:
        if ags in done:
            print(f"skip {ags} (already in summary)", flush=True)
            continue
        st = harvest(ags)
        all_stats.append(st)
        summary_path.write_text(json.dumps(all_stats, indent=1, ensure_ascii=False),
                                encoding="utf-8")


if __name__ == "__main__":
    main()
