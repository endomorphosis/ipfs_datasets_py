#!/usr/bin/env python3
"""Austria/Carinthia amtstafel.at pilot harvester.

One hub (amtstafel.at, Elektronisches Amtsblatt Kärnten), one listing
page per Gemeinde namespaced by GKZ. Downloads each ordinance PDF,
extracts text (PyMuPDF -> pdfplumber -> pdftotext; no OCR available on
this VM), splits into article-level (§) rows in the world_municipal
19-column schema, validates fail-closed, writes one parquet per GKZ.

Usage: harvest_at_pilot.py GKZ [GKZ ...]
Artifacts: out/{gkz}_html.parquet, out/{gkz}_validation.json,
out/pilot_summary.json (merged), raw/ PDFs cached per GKZ.
"""
import html as html_mod
import json
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py"))
from ipfs_datasets_py.processors.legal_scrapers.world_municipal import (  # noqa: E402
    jurisdiction,
    normalize,
    parquet_io,
    schema as wm_schema,
)
import pyarrow as pa  # noqa: E402

BASE = "https://amtstafel.at"
HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
OUT = HERE / "out"
RETRIEVED = date.today().isoformat()
PACING_S = 2.0
EXTRA_COLS = [("sachgebiet", pa.string())]

S = requests.Session()
S.headers["User-Agent"] = (
    "ipfs_datasets_py world-municipal pilot (open legal data research)"
)


def fetch(url: str, binary: bool = False):
    r = S.get(url, timeout=90)
    r.raise_for_status()
    return r.content if binary else r.text


def parse_listing(gkz: str, html_text: str):
    """Return list of doc dicts in page order (main entries + annexes)."""
    soup = BeautifulSoup(html_text, "html.parser")
    docs, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "handler=DownloadFile" not in href:
            continue
        m = re.search(r"fileName=([^&]+)", href)
        if not m:
            continue
        from urllib.parse import unquote

        fname = unquote(m.group(1))
        tr = a.find_parent("tr")
        cells = []
        if tr is not None:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        # hub id = last all-digit cell
        hub_id = ""
        for c in reversed(cells):
            if c.isdigit():
                hub_id = c
                break
        key = (fname, hub_id)
        if key in seen:
            continue
        seen.add(key)
        is_annex = bool(cells) and cells[0].lower().startswith("anhang")
        if is_annex:
            title = fname.rsplit(".", 1)[0]
            sach, pub = "", ""
        else:
            title = cells[1] if len(cells) > 1 and cells[1] else fname.rsplit(".", 1)[0]
            sach = cells[2] if len(cells) > 2 else ""
            pub = cells[3] if len(cells) > 3 else ""
        docs.append(
            {
                "file_name": fname,
                "hub_id": hub_id,
                "title": title,
                "sachgebiet": sach,
                "published_raw": pub,
                "is_annex": is_annex,
                "url": BASE + href if href.startswith("/") else href,
            }
        )
    return docs


def iso_date(raw: str) -> str:
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", raw or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def extract_text(pdf_bytes: Path) -> tuple[str, str, int]:
    """PDF chain: PyMuPDF -> pdfplumber -> pdftotext. Returns (text, method, pages)."""
    import fitz

    try:
        doc = fitz.open(pdf_bytes)
        pages = doc.page_count
        text = "\n".join(p.get_text() for p in doc)
        doc.close()
        if len(text.strip()) >= 300:
            return text, "pymupdf", pages
    except Exception:
        pages = 0
    try:
        import pdfplumber

        with pdfplumber.open(pdf_bytes) as pdf:
            pages = pages or len(pdf.pages)
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        if len(text.strip()) >= 300:
            return text, "pdfplumber", pages
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(pdf_bytes), "-"],
            capture_output=True, timeout=120,
        )
        text = out.stdout.decode("utf-8", errors="replace")
        if text.strip():
            return text, "pdftotext", pages
    except Exception:
        pass
    return "", "none", pages


SEC_RE = re.compile(r"(?m)^[ \t]*(§[ \t]*\d+[a-z]?)\b[ \t]*(.*)$")


def split_articles(text: str):
    """Split ordinance text into (node_label, segment_text) at § headings."""
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


def harvest_gemeinde(gkz: str, reg_name: str) -> dict:
    t0 = time.time()
    gkz = jurisdiction.get_scheme("AT").normalize(gkz)
    page_url = f"{BASE}/Gemeindeverordnungen_Ktn/{gkz}"
    html_text = fetch(page_url)
    (RAW / f"listing_{gkz}.html").write_text(html_text, encoding="utf-8")
    docs = parse_listing(gkz, html_text)
    pdf_dir = RAW / "pdf" / gkz
    pdf_dir.mkdir(parents=True, exist_ok=True)
    rows, stats = [], {
        "gkz": gkz, "name": reg_name, "docs_listed": len(docs),
        "downloaded": 0, "extracted": 0, "scanned_or_empty": 0,
        "download_failed": 0, "name_hits": 0, "pages": 0, "methods": {},
    }
    name_probe = reg_name.split(" im ")[0].split(" am ")[0].split(" in ")[0].strip()
    for doc in docs:
        dest = pdf_dir / doc["file_name"]
        try:
            if not dest.exists() or dest.stat().st_size == 0:
                data = fetch(doc["url"], binary=True)
                dest.write_bytes(data)
                time.sleep(PACING_S)
            stats["downloaded"] += 1
        except Exception as e:
            stats["download_failed"] += 1
            print(f"  DL FAIL {gkz} {doc['file_name']}: {e}", flush=True)
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
        eff = date_effective(text)
        pub_iso = iso_date(doc["published_raw"])
        segs = split_articles(text)
        for si, (label, seg) in enumerate(segs):
            doc_id = f"{gkz}-{doc['hub_id'] or doc['file_name']}"
            if len(segs) > 1:
                doc_id = f"{doc_id}-{si}"
            rows.append(normalize.make_row(
                jurisdiction_id=gkz,
                jurisdiction_name=reg_name,
                country="AT",
                doc_id=doc_id,
                regeling_id=re.sub(r"\.pdf$", "", doc["file_name"], flags=re.I),
                regeling_work_id=re.sub(r"\.pdf$", "", doc["file_name"], flags=re.I),
                title=doc["title"],
                structural_path=doc["title"],
                node_label=label,
                body_html=text_to_html(seg),
                text=seg,
                source_url=doc["url"],
                date_effective=eff,
                date_modified=pub_iso,
                retrieved=RETRIEVED,
                sachgebiet=doc["sachgebiet"],
            ))
    rows = normalize.finalize_rows(normalize.drop_empty_rows(rows))
    table = wm_schema.rows_to_table(rows, extra_columns=EXTRA_COLS)
    report = wm_schema.validation_report(
        table, jurisdiction_id=gkz, jurisdiction_name=reg_name, country="AT")
    out_path = OUT / f"{gkz}_html.parquet"
    parquet_io.write_html_parquet(out_path, table)
    parquet_io.write_validation_report(OUT / f"{gkz}_validation.json", report)
    stats["rows"] = table.num_rows
    stats["valid"] = report["valid"]
    stats["errors"] = report["errors"]
    stats["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(stats, ensure_ascii=False), flush=True)
    return stats


def main():
    registry = {r["gkz"]: r["name"] for r in json.loads(
        (RAW / "statistik_at_carinthia.json").read_text(encoding="utf-8"))}
    all_stats = []
    summary_path = OUT / "pilot_summary.json"
    if summary_path.exists():
        all_stats = json.loads(summary_path.read_text(encoding="utf-8"))
    done = {s["gkz"] for s in all_stats}
    for gkz in sys.argv[1:]:
        if gkz in done:
            print(f"skip {gkz} (already in summary)", flush=True)
            continue
        st = harvest_gemeinde(gkz, registry[gkz])
        all_stats.append(st)
        summary_path.write_text(json.dumps(all_stats, indent=1, ensure_ascii=False),
                                encoding="utf-8")


if __name__ == "__main__":
    main()
