"""Sweden pilot — build step (disk-only, from fetch_manifest.json).

PDFs: text via fitz -> pdfplumber -> pdftotext (tesseract is NOT
installed on this VM, so the OCR rung of the NZ chain is absent;
Swedish KFS PDFs are born-digital). Text is split into paragraph
units on Swedish legal structure: lines starting "N §" or "N kap."
HTML doc-pages (Uppsala): main-content text extracted from the saved
page; split the same way.
Every kommun's table must pass world_municipal validate_table on
write AND on re-read, else the kommun is dropped (fail closed).
"""
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

OUT = Path(__file__).resolve().parent
SCRATCH = OUT / "scratch"
sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"))
from world_municipal.normalize import make_row, finalize_rows, drop_empty_rows  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402
from world_municipal.jurisdiction import get_scheme  # noqa: E402

SE = get_scheme("SE")
RETRIEVED = "2026-10-14"
REG = {json.loads(ln)["jurisdiction_id"]: json.loads(ln)["jurisdiction_name"]
       for ln in (OUT / "jurisdictions.jsonl").read_text(encoding="utf-8").splitlines()}


def extract_pdf_text(pdf_path, stem):
    tmp = SCRATCH / f"{stem}.pdf"
    tmp.write_bytes(Path(pdf_path).read_bytes())
    try:
        import fitz
        doc = fitz.open(tmp)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        if len(text.strip()) >= 200:
            return text, "fitz"
    except Exception:  # noqa: BLE001
        pass
    try:
        import pdfplumber
        with pdfplumber.open(tmp) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        if len(text.strip()) >= 200:
            return text, "pdfplumber"
    except Exception:  # noqa: BLE001
        pass
    try:
        out = subprocess.run(["pdftotext", "-layout", str(tmp), "-"],
                             capture_output=True, timeout=300)
        text = out.stdout.decode("utf-8", "replace")
        if len(text.strip()) >= 200:
            return text, "pdftotext"
    except Exception:  # noqa: BLE001
        pass
    return "", "failed"


def extract_page_text(html_path):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(Path(html_path).read_text(encoding="utf-8", errors="replace"),
                         "html.parser")
    main = soup.find("main") or soup.find("article") or soup.body
    if main is None:
        return ""
    for tag in main.find_all(["nav", "header", "footer", "script", "style", "form"]):
        tag.decompose()
    return main.get_text("\n")


PAGE_MARK = re.compile(r"^\s*(Sidan|Page|Sid)\s+\d+\s*(av|of)?\s*\d*\s*$", re.I)
PAGE_XOFY = re.compile(r"^\s*(?:Sida\s+)?\d{1,3}\s*\(\d{1,4}\)\s*$")  # "5 (10)" / "Sida 2 (5)"
BARE_NUM = re.compile(r"^\s*\d{1,3}\s*$")


def strip_furniture(text):
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    counts = Counter(l.strip() for l in lines if l.strip())
    out = []
    for ln in lines:
        s = ln.strip()
        if PAGE_MARK.match(ln) or PAGE_XOFY.match(ln) or BARE_NUM.match(ln):
            continue
        if s and counts[s] >= 4 and len(s) <= 90 and not re.match(r"^\d+\s*§", s):
            continue  # running header/footer repeated across pages
        out.append(ln)
    return out


SEC_BARE = re.compile(r"^\s*(?:\d{1,3}\s*§|§\s*\d{1,3})\s*$")
SEC_HEADED = re.compile(r"^\s*(?:§\s*\d{1,3}\s+[A-ZÅÄÖ]|\d{1,3}\s*§\s+[A-ZÅÄÖ])")
NUM_HEAD = re.compile(r"^\s*\d{1,2}\.\s+[A-ZÅÄÖ]")
KAP_HEAD = re.compile(r"^\s*\d{1,3}\s*kap\.")


def is_sec_start(ln):
    """Section-start line, both Swedish conventions ('1 §' föreskrift
    style, '§ 3' reglemente style). ToC lines (dot leaders) and long
    wrapped body lines are excluded to avoid false splits."""
    if "..." in ln:
        return False
    if SEC_BARE.match(ln):
        return True
    if KAP_HEAD.match(ln):
        return True
    if len(ln) > 120:
        return False
    return bool(SEC_HEADED.match(ln) or NUM_HEAD.match(ln))


def split_units(text):
    lines = strip_furniture(text)
    units, cur = [], []
    for ln in lines:
        if is_sec_start(ln) and cur and sum(len(x) for x in cur) > 60:
            units.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        units.append(cur)
    out = []
    for u in units:
        body = "\n".join(u).strip()
        if len(body) < 60:
            if out:
                out[-1] = out[-1] + "\n" + body
            continue
        out.append(body)
    return out


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", unquote(s).lower()).strip("-")
    return s or "doc"


def build_kommun(code, files):
    name = REG[code]
    jid = SE.normalize(code)
    rows, docs = [], []
    for f in files:
        path = OUT / f["path"]
        title = f["title"]
        if f["kind"] == "pdf":
            text, method = extract_pdf_text(path, f"se_{code}_{path.stem}")
        else:
            text, method = extract_page_text(path), "html_page"
            if len(text.strip()) < 2000:
                # landing/metadata page only — no full föreskrift text
                docs.append({"title": title, "source_url": f["url"], "method": method,
                             "chars": len(text), "units": 0,
                             "skipped": "html landing page, no full text"})
                print(f"[{code}] SKIP {title[:50]}: landing page only", flush=True)
                continue
        if len(text.strip()) < 200:
            docs.append({"title": title, "source_url": f["url"], "method": method,
                         "chars": len(text), "units": 0, "skipped": "text too short"})
            print(f"[{code}] SKIP {title[:50]}: {method}, {len(text)} chars", flush=True)
            continue
        units = split_units(text)
        if len(units) < 2:
            units = [text.strip()] if len(text.strip()) >= 400 else []
        year = ""
        m = re.search(r"träder i kraft[^\d]{0,40}((?:19|20)\d\d)", text, re.I)
        if m:
            year = m.group(1)
        else:
            m = re.search(r"(19|20)\d\d", title + " " + unquote(f["url"]))
            if m:
                year = m.group(0)
        slug = slugify(Path(f["path"]).stem)
        made = 0
        for i, unit in enumerate(units):
            first = [l for l in unit.split("\n") if l.strip()]
            label_first = first[0].strip() if first else ""
            if (re.fullmatch(r"\d{1,3}\s*§", label_first)
                    or re.fullmatch(r"§\s*\d{1,3}", label_first)) and len(first) > 1:
                label = f"{label_first} {first[1].strip()}"[:120]
            else:
                label = (label_first[:120] or title)
            import html as html_mod
            body_html = "".join(
                f"<p>{html_mod.escape(p.strip())}</p>"
                for p in re.split(r"\n\s*\n|\n", unit) if p.strip())
            rows.append(make_row(
                jurisdiction_id=jid, jurisdiction_name=name, country="SE",
                doc_id=f"{slug}#{i + 1}", title=title,
                structural_path=title, node_label=label,
                body_html=body_html, source_url=f["url"],
                date_effective=year, retrieved=RETRIEVED))
            made += 1
        docs.append({"title": title, "source_url": f["url"], "method": method,
                     "chars": len(text), "units": made})
        print(f"[{code}] {title[:60]}: {method}, {len(text)} chars, {made} rows", flush=True)
    if not rows:
        return {"code": jid, "name": name, "docs": docs, "rows": 0,
                "valid": False, "error": "no rows built"}
    rows = drop_empty_rows(finalize_rows(rows))
    table = rows_to_table(rows)
    errors = validate_table(table, jurisdiction_id=jid, jurisdiction_name=name, country="SE")
    if errors:
        return {"code": jid, "name": name, "docs": docs, "rows": 0,
                "valid": False, "error": f"validation: {errors}"}
    pq = OUT / f"{jid}_html.parquet"
    write_html_parquet(pq, table)
    back = read_html_parquet(pq)
    errors2 = validate_table(back, jurisdiction_id=jid, jurisdiction_name=name, country="SE")
    if errors2:
        return {"code": jid, "name": name, "docs": docs, "rows": 0,
                "valid": False, "error": f"re-read validation: {errors2}"}
    rep = validation_report(back, jurisdiction_id=jid, jurisdiction_name=name, country="SE")
    write_validation_report(OUT / f"{jid}_validation.json", rep)
    return {"code": jid, "name": name, "docs": docs, "rows": len(rows),
            "parquet": pq.name, "valid": True, "builder": "se_build.py"}


def main():
    fetch = json.loads((OUT / "fetch_manifest.json").read_text())
    mp = OUT / "run_manifest.json"
    manifest = json.loads(mp.read_text()) if mp.exists() else {"retrieved": RETRIEVED, "kommuner": {}}
    manifest["retrieved"] = RETRIEVED
    for code, entry in sorted(fetch["kommuner"].items()):
        ok_files = [f for f in entry.get("files", []) if f.get("status") == "ok"]
        # Uppsala: prefer the canonical PDF over its landing page per title
        pdf_titles = {f["title"] for f in ok_files if f["kind"] == "pdf"}
        ok_files = [f for f in ok_files
                    if f["kind"] == "pdf" or f["title"] not in pdf_titles]
        if not ok_files:
            print(f"[{code}] SKIP — no fetched docs", flush=True)
            continue
        t0 = time.monotonic()
        try:
            res = build_kommun(code, ok_files)
        except Exception as exc:  # noqa: BLE001
            res = {"code": code, "name": REG[code], "valid": False,
                   "error": f"{type(exc).__name__}: {exc}", "rows": 0, "docs": []}
        res["wall_seconds"] = round(time.monotonic() - t0, 1)
        manifest["kommuner"][code] = res
        mp.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
        print(f"[{code}] -> valid={res['valid']} rows={res['rows']}", flush=True)
    print(json.dumps({k: (v.get("rows"), v.get("error")) for k, v in manifest["kommuner"].items()}, indent=1))


if __name__ == "__main__":
    main()
