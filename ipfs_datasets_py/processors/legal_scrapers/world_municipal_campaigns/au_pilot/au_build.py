"""Australia pilot — harvest + build (checkpointed per council).

Fetches the pilot councils' local-law / by-law PDFs with hard-capped
curl, extracts text via the program chain (pdfplumber -> PyMuPDF ->
pdftotext -> tesseract eng OCR), splits to clause-level rows, builds
world_municipal 19-column parquets, and validates fail-closed on write
and on re-read. State lands in au_pilot/run_manifest.json after every
council; parquets in au_pilot/data/. Sample sizes: 1-4 laws per council.
"""
import html as html_mod
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.normalize import make_row, finalize_rows, drop_empty_rows  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402
from world_municipal.jurisdiction import get_scheme  # noqa: E402

OUT = Path(__file__).resolve().parent.parent
SCRATCH = OUT / "scratch" / "pdfs"
SCRATCH.mkdir(parents=True, exist_ok=True)
DATA = OUT / "data"
RETRIEVED = "2026-10-13"
AU = get_scheme("AU")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 world-municipal-law-pilot/0.1"

BNE = "https://www.brisbane.qld.gov.au/content/dam/brisbanecitycouncil/corpwebsite/laws-and-permits-/documents/"
COUNCILS = {
    "31000": {"state": "Queensland", "platform": "Adobe AEM", "docs": [
        ("Advertising Devices Local Law 2021", BNE + "advertising-devices-local-law-2021.pdf"),
        ("Animals Local Law 2017", BNE + "animals-local-law-2017.pdf"),
        ("Events Local Law 2022", BNE + "events-local-law-2022.pdf"),
        ("Health, Safety and Amenity Local Law 2021", BNE + "health-safety-and-amenity-local-law-2021.pdf"),
    ]},
    "24700": {"state": "Victoria", "platform": "Granicus OpenCities", "docs": [
        ("General Local Law 2018 (consolidated, as amended 2025)",
         "https://www.merri-bek.vic.gov.au/globalassets/website-merri-bek/areas/my-council/local-laws-legislation/merri-bek-local-laws/moreland-city-council-general-local-law-2018-consolidated-version-amended-2025.pdf"),
    ]},
    "40070": {"state": "South Australia", "platform": "custom / CloudFront docs", "docs": [
        ("By-law No. 1 — Permits and Penalties", "https://d31atr86jnqrq2.cloudfront.net/docs/by-law-1-permits-and-penalties.pdf"),
        ("By-law No. 2 — Moveable Signs", "https://d31atr86jnqrq2.cloudfront.net/docs/by-law-2-moveable-signs.PDF"),
        ("By-law No. 4 — Roads", "https://d31atr86jnqrq2.cloudfront.net/docs/by-law-4-roads.PDF"),
        ("By-law No. 7 — Dogs", "https://d31atr86jnqrq2.cloudfront.net/docs/by-law-7-dogs.PDF"),
    ]},
    "54170": {"state": "Western Australia", "platform": "custom CMS", "docs": [
        ("Parking Local Law 2023", "https://joondalup.wa.gov.au/awcontent/Web/Documents/Local%20Laws/Parking-Local-Law-2023-(consolidated).pdf"),
        ("Local Government and Public Property Local Law 2014",
         "http://www.joondalup.wa.gov.au/Files/Local%20Government%20and%20Public%20Property%20Local%20Law%202014%20-%20Amended%20November%202015%20with%20Information%20Notes.pdf"),
    ]},
}


def fetch(url, dest, max_time=120):
    t0 = time.monotonic()
    p = subprocess.run(["curl", "-sS", "-L", "--max-time", str(max_time), "-A", UA,
                        "-o", str(dest), "-w", "%{http_code}", url],
                       capture_output=True, timeout=max_time + 30)
    code = p.stdout.decode().strip()
    size = dest.stat().st_size if dest.exists() else 0
    head = dest.read_bytes()[:5] if size else b""
    return {"status": int(code) if code.isdigit() else 0, "bytes": size,
            "is_pdf": head == b"%PDF-", "seconds": round(time.monotonic() - t0, 1)}


def extract_text(pdf_path):
    """pdfplumber -> PyMuPDF -> pdftotext -> tesseract eng. (text, method)"""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        if len(text.strip()) >= 200:
            return text, "pdfplumber"
    except Exception:  # noqa: BLE001
        pass
    try:
        import fitz
        doc = fitz.open(pdf_path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        if len(text.strip()) >= 200:
            return text, "fitz"
    except Exception:  # noqa: BLE001
        pass
    try:
        out = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"],
                             capture_output=True, timeout=300)
        text = out.stdout.decode("utf-8", "replace")
        if len(text.strip()) >= 200:
            return text, "pdftotext"
    except Exception:  # noqa: BLE001
        pass
    try:
        import fitz
        doc = fitz.open(pdf_path)
        pages = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=200)
            img = SCRATCH / f"{pdf_path.stem}_p{i}.png"
            pix.save(img)
            o = subprocess.run(["tesseract", str(img), "stdout", "-l", "eng"],
                               capture_output=True, timeout=300)
            pages.append(o.stdout.decode("utf-8", "replace"))
            img.unlink(missing_ok=True)
        doc.close()
        return "\n".join(pages), "tesseract"
    except Exception:  # noqa: BLE001
        return "", "failed"


PAGE_MARK = re.compile(r"^\s*Page\s+\d+\b")


def strip_furniture(text):
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    counts = Counter(l.strip() for l in lines if l.strip())
    furniture = set()
    for i, l in enumerate(lines):
        if PAGE_MARK.match(l):
            furniture.add(i)
            for j in range(max(0, i - 2), min(len(lines), i + 3)):
                s = lines[j].strip()
                if s and counts[s] >= 3 and len(s) <= 110:
                    furniture.add(j)
    return [l for i, l in enumerate(lines) if i not in furniture]


SEC_START = re.compile(
    r"^\s*(?:PART\s+\d+\b|Part\s+\d+\b|SCHEDULE\s*\d*\b|Schedule\s+\d+\b"
    r"|\d{1,3}\.\d{1,3}\s+[A-Z(]"
    r"|\d{1,3}\.\s+[A-Z(]"
    r"|\d{1,3}\.\s*$"
    r"|\d{1,3}\s+[A-Z][a-zA-Z ]{2,60}$)")


def split_units(text):
    lines = strip_furniture(text)
    units, cur = [], []
    for ln in lines:
        if SEC_START.match(ln) and cur and sum(len(x) for x in cur) > 40:
            units.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        units.append(cur)
    out = []
    for u in units:
        body = "\n".join(u).strip()
        if len(body) < 40:
            if out:
                out[-1] = out[-1] + "\n" + body
            continue
        out.append(body)
    return out


def build_council(code, registry):
    name = registry[code]
    jid = AU.normalize(code)
    cfg = COUNCILS[code]
    t_start = time.monotonic()
    rows, docs = [], []
    for title, url in cfg["docs"]:
        stem = f"au_{code}_" + re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        dest = SCRATCH / f"{stem}.pdf"
        f = fetch(url, dest)
        rec = {"title": title, "source_url": url, "fetch": f}
        if not f["is_pdf"]:
            rec["error"] = f"fetch status {f['status']}, not a PDF"
            docs.append(rec)
            print(f"[{code}] FAIL {title}: {rec['error']}", flush=True)
            continue
        text, method = extract_text(dest)
        units = split_units(text)
        if len(units) < 2:
            units = [text.strip()] if len(text.strip()) >= 200 else []
        slug = stem
        made = 0
        for i, unit in enumerate(units):
            first = [l for l in unit.split("\n") if l.strip()]
            label_first = first[0].strip() if first else ""
            if re.fullmatch(r"\d{1,3}\.", label_first) and len(first) > 1:
                label = f"{label_first} {first[1].strip()}"[:120]
            else:
                label = label_first[:120] or title
            body_html = "".join(
                f"<p>{html_mod.escape(p.strip())}</p>"
                for p in re.split(r"\n\s*\n|\n", unit) if p.strip())
            year = ""
            m = re.search(r"(19|20)\d\d", title)
            if m:
                year = m.group(0)
            rows.append(make_row(
                jurisdiction_id=jid, jurisdiction_name=name, country="AU",
                doc_id=f"{slug}#{i + 1}", title=title,
                structural_path=title, node_label=label,
                body_html=body_html, source_url=url,
                date_effective=year, retrieved=RETRIEVED))
            made += 1
        rec.update({"method": method, "chars": len(text), "units": made,
                    "fetch_seconds": f["seconds"]})
        docs.append(rec)
        print(f"[{code}] {title}: {method}, {len(text)} chars, {made} rows, "
              f"fetch {f['seconds']}s", flush=True)
        time.sleep(2)
    rows = finalize_rows(drop_empty_rows(rows))
    if not rows:
        return {"code": jid, "name": name, "docs": docs, "rows": 0,
                "error": "no rows built"}
    table = rows_to_table(rows)
    errors = validate_table(table, jurisdiction_id=jid, jurisdiction_name=name, country="AU")
    if errors:
        return {"code": jid, "name": name, "docs": docs, "rows": len(rows),
                "error": f"VALIDATION FAILED: {errors}"}
    pq = DATA / f"{jid}_html.parquet"
    write_html_parquet(pq, table)
    back = read_html_parquet(pq)
    errors2 = validate_table(back, jurisdiction_id=jid, jurisdiction_name=name, country="AU")
    if errors2:
        return {"code": jid, "name": name, "docs": docs, "rows": len(rows),
                "error": f"RE-READ VALIDATION FAILED: {errors2}"}
    rep = validation_report(back, jurisdiction_id=jid, jurisdiction_name=name, country="AU")
    write_validation_report(DATA / f"{jid}_validation.json", rep)
    return {"code": jid, "name": name, "state": cfg["state"], "platform": cfg["platform"],
            "docs": docs, "rows": len(rows),
            "wall_seconds": round(time.monotonic() - t_start, 1),
            "parquet": pq.name, "valid": True}


def main():
    registry = {}
    for ln in (DATA / "jurisdictions.jsonl").read_text().splitlines():
        r = json.loads(ln)
        if r["kind"] == "lga":
            registry[r["code"]] = r["name"]
    codes = sys.argv[1:] or list(COUNCILS)
    mpath = OUT / "run_manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {"retrieved": RETRIEVED, "councils": {}}
    for code in codes:
        try:
            manifest["councils"][code] = build_council(code, registry)
        except Exception as exc:  # noqa: BLE001
            manifest["councils"][code] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"[{code}] BUILD FAILED: {exc}", flush=True)
        mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps({k: (v.get("rows"), v.get("error")) for k, v in manifest["councils"].items()}, indent=1))


if __name__ == "__main__":
    main()
