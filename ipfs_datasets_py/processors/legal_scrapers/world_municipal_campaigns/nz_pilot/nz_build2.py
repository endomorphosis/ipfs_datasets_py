"""New Zealand pilot — RECOVERY build step.

Builds section-level rows from the PDFs that nz_fetch.py downloaded to
disk (pdfs/<code>/), never from the network. Reuses the first worker's
sound machinery from nz_pilot_build.py (extract_text chain fitz ->
pdfplumber -> pdftotext -> tesseract, split_units, prettify_title,
world_municipal gates) and writes run_manifest.json entries in exactly
the shape nz_publish.py consumes ({valid, rows, docs, name, ...}) plus
fetch-provenance fields (per-doc source: live | wayback | disk).
"""
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

OUT = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "nz_pilot"
sys.path.insert(0, str(OUT))
sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"))

import html as html_mod  # noqa: E402
from nz_pilot_build import extract_text, split_units, prettify_title  # noqa: E402
from world_municipal.normalize import make_row, finalize_rows, drop_empty_rows  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402
from world_municipal.jurisdiction import get_scheme  # noqa: E402

NZ = get_scheme("NZ")
RETRIEVED = "2026-10-13"  # all pilot fetches landed 2026-10-13 PDT


def build_council(code, files):
    name = None
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
        units = split_units(text)
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
            first = unit.split("\n")[0].strip()
            label = first[:120] if i else (first[:120] or title)
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
            "parquet": pq.name, "valid": True}


def main():
    fetch = json.loads((OUT / "fetch_manifest.json").read_text())
    manifest_path = OUT / "run_manifest.json"
    manifest = {"retrieved": RETRIEVED, "councils": {}}
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        manifest["prior_attempt"] = old  # keep the first worker's record visible
    for code, entry in sorted(fetch["councils"].items()):
        ok_files = [f for f in entry.get("files", []) if f.get("status") == "ok"]
        if not ok_files:
            manifest["councils"][code] = {
                "error": entry.get("error") or "no PDFs fetched",
                "fetch_detail": {f["url"]: f.get("errors") for f in entry.get("files", [])}}
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
