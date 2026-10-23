"""New Zealand pilot — FINISH build step.

Like nz_build2.py (disk-only build from pdfs/<code>/ per
fetch_manifest.json), but with a fixed section splitter. The original
split_units() in nz_pilot_build.py required a clause number and heading
text on the SAME line ("^\\d+\\.\\s+[A-Z(]"). Tauranga's PDFs put the
clause number alone on its own line ("5."), the ALL-CAPS heading on the
next line, and sub-clause numbers ("5.1") on their own lines too — so
no line matched and each document collapsed to a single unit
(4 docs -> 5 rows). split_units2() below additionally recognises a
bare "N." line as a section start and strips the councils' repeating
page furniture (running title, "Page N ..." and "Objective Number:"
lines) before splitting. Prototype on the four Tauranga PDFs:
20/19/11/14 units (was 1/2/1/4); on Hamilton's PDFs it reproduces the
shipped granularity (6/17/61; Alcohol Control 27 vs shipped 18 because
the contents-page entries also split — Hamilton's parquet is kept
as-is regardless; this builder is never run on 016).

Manifest handling: merges into run_manifest.json — the shipped 016
entry (and any other untouched council entries) are preserved verbatim;
built councils get fresh entries in the nz_publish.py shape.
"""
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

OUT = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "nz_pilot"
sys.path.insert(0, str(OUT))
sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"))

import html as html_mod  # noqa: E402
from nz_pilot_build import extract_text, prettify_title  # noqa: E402
from world_municipal.normalize import make_row, finalize_rows, drop_empty_rows  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402
from world_municipal.jurisdiction import get_scheme  # noqa: E402

NZ = get_scheme("NZ")
RETRIEVED = "2026-10-13"

PAGE_MARK = re.compile(r"^\s*Page\s+\d+\b")
OBJ_MARK = re.compile(r"^\s*Objective Number\s*:")


def strip_furniture(text):
    """Drop per-page furniture lines: 'Page N ...', 'Objective Number: ...',
    and running-title lines repeated >=3x adjacent to a Page marker."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    counts = Counter(l.strip() for l in lines if l.strip())
    furniture = set()
    page_idx = []
    for i, l in enumerate(lines):
        if PAGE_MARK.match(l) or OBJ_MARK.match(l):
            furniture.add(i)
        if PAGE_MARK.match(l):
            page_idx.append(i)
    for i in page_idx:
        for j in range(max(0, i - 2), min(len(lines), i + 3)):
            s = lines[j].strip()
            if s and counts[s] >= 3 and len(s) <= 110:
                furniture.add(j)
    return [l for i, l in enumerate(lines) if i not in furniture]


SEC_START = re.compile(
    r"^\s*(?:PART\s+\d+\b|Part\s+\d+\b|SCHEDULE\s*\d*\b"
    r"|\d{1,3}\.\s*$|\d{1,3}\.\s+[A-Z(])")


def split_units2(text):
    """Split extracted text into clause-level units (superset of the
    original split_units: also splits on a bare 'N.' heading line, the
    Tauranga format, and strips page furniture first)."""
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


def build_council(code, files):
    reg = {json.loads(ln)["jurisdiction_id"]: json.loads(ln)["jurisdiction_name"]
           for ln in (OUT / "jurisdictions.jsonl").read_text().splitlines()}
    name = reg[code]
    jid = NZ.normalize(code)
    t_start = time.monotonic()
    rows, docs = [], []
    for f in files:
        pdf_url, link_text = f["url"], f.get("link_text", "")
        title = prettify_title(pdf_url, link_text)
        pdf_bytes = (OUT / f["path"]).read_bytes()
        stem = f"nz_{code}_" + re.sub(r"[^a-z0-9]+", "-", Path(f["path"]).stem.lower()).strip("-")
        text, method = extract_text(pdf_bytes, stem)
        units = split_units2(text)
        if len(units) < 2:
            units = [text.strip()] if len(text.strip()) >= 200 else []
        year = ""
        m = re.search(r"(19|20)\d\d", title + " " + unquote(pdf_url))
        if m:
            year = m.group(0)
        slug = re.sub(r"[^a-z0-9]+", "-", unquote(pdf_url).split("/")[-1].lower())
        slug = re.sub(r"\.pdf$", "", slug).strip("-")
        made = 0
        for i, unit in enumerate(units):
            first = [l for l in unit.split("\n") if l.strip()]
            label_first = first[0].strip() if first else ""
            # Tauranga format: number alone, heading on the next line —
            # combine both into the node label.
            if re.fullmatch(r"\d{1,3}\.", label_first) and len(first) > 1:
                label = f"{label_first} {first[1].strip()}"[:120]
            else:
                label = label_first[:120] if i else (label_first[:120] or title)
            body_html = "".join(
                f"<p>{html_mod.escape(p.strip())}</p>"
                for p in re.split(r"\n\s*\n|\n", unit) if p.strip())
            rows.append(make_row(
                jurisdiction_id=jid, jurisdiction_name=name, country="NZ",
                doc_id=f"{slug}#{i + 1}", title=title,
                structural_path=title, node_label=label,
                body_html=body_html, source_url=pdf_url,
                date_effective=year, retrieved=RETRIEVED))
            made += 1
        docs.append({"title": title, "source_url": pdf_url, "method": method,
                     "chars": len(text), "units": made,
                     "fetch_source": f.get("source"), "fetch_seconds": f.get("seconds")})
        print(f"[{code}]  {title}: {method}, {len(text)} chars, {made} rows "
              f"(fetch={f.get('source')})", flush=True)
    rows = drop_empty_rows(finalize_rows(rows))
    table = rows_to_table(rows)
    errors = validate_table(table, jurisdiction_id=jid, jurisdiction_name=name, country="NZ")
    if errors:
        raise SystemExit(f"[{code}] VALIDATION FAILED: {errors}")
    pq = OUT / f"{jid}_html.parquet"
    write_html_parquet(pq, table)
    back = read_html_parquet(pq)
    errors2 = validate_table(back, jurisdiction_id=jid, jurisdiction_name=name, country="NZ")
    if errors2:
        raise SystemExit(f"[{code}] RE-READ VALIDATION FAILED: {errors2}")
    rep = validation_report(back, jurisdiction_id=jid, jurisdiction_name=name, country="NZ")
    write_validation_report(OUT / f"{jid}_validation.json", rep)
    return {"code": jid, "name": name, "docs": docs, "rows": len(rows),
            "wall_seconds": round(time.monotonic() - t_start, 1),
            "parquet": pq.name, "valid": True, "builder": "nz_build3.py"}


def main():
    codes = sys.argv[1:]
    fetch = json.loads((OUT / "fetch_manifest.json").read_text())
    if not codes:
        codes = [c for c, e in sorted(fetch["councils"].items())
                 if c != "016" and any(f.get("status") == "ok" for f in e.get("files", []))]
    manifest_path = OUT / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() \
        else {"retrieved": RETRIEVED, "councils": {}}
    manifest["retrieved"] = RETRIEVED
    for code in codes:
        entry = fetch["councils"].get(code, {})
        ok_files = [f for f in entry.get("files", []) if f.get("status") == "ok"]
        if not ok_files:
            print(f"[{code}] SKIP — no fetched PDFs", flush=True)
            continue
        try:
            res = build_council(code, ok_files)
            res["fetch_wall_seconds"] = entry.get("wall_seconds")
            res["fetch_requests"] = sum(f.get("attempts", 0) for f in entry.get("files", []))
            manifest["councils"][code] = res
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001
            manifest["councils"][code] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"[{code}] BUILD FAILED: {exc}", flush=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps({k: (v.get("rows"), v.get("error")) for k, v in manifest["councils"].items()}, indent=1))


if __name__ == "__main__":
    main()
