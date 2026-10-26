"""Australia tranche-2 driver — checkpointed per council.

Scope lives in config.json: {code: {state, platform, docs:[[title,url],...]}}.
For each council not already published (state.json + fresh HF listing):
fetch PDFs (hard-capped curl, pilot machinery) -> extract
(pdfplumber -> PyMuPDF -> pdftotext -> tesseract) -> clause split ->
world_municipal 19-col parquet + validation sidecar -> publish
per-council to endomorphosis/ipfs_australia_municipal_laws ->
remote-verify by re-download. State in state.json after every council.
"""
import html as html_mod
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

HERE = Path(__file__).resolve().parent
PILOT = HERE.parent / "au_pilot"
DATA = HERE / "data"; DATA.mkdir(parents=True, exist_ok=True)
PDFS = HERE / "scratch" / "pdfs"; PDFS.mkdir(parents=True, exist_ok=True)
STATE = HERE / "state.json"
REPO = "endomorphosis/ipfs_australia_municipal_laws"
RETRIEVED = "2026-10-14"

REPO_PY = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO_PY / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.normalize import make_row, finalize_rows, drop_empty_rows  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402
from world_municipal.jurisdiction import get_scheme  # noqa: E402
AU = get_scheme("AU")

spec = importlib.util.spec_from_file_location("au_build", PILOT / "scripts" / "au_build.py")
au_build = importlib.util.module_from_spec(spec); spec.loader.exec_module(au_build)
fetch, extract_text, split_units = au_build.fetch, au_build.extract_text, au_build.split_units
# OCR temp images land in this driver's own scratch, not the pilot's
au_build.SCRATCH = PDFS

# Watchdog fix 2026-10-14: percent-encode literal spaces in doc URLs before
# curl (raw spaces make curl fail with status 0 — Wodonga 27170's
# "Local Laws 2024_Final.pdf" URL; verified encoded form returns 200/PDF.
# Same defect class as the NZ tranche-2 curl_url() fix.)
from urllib.parse import quote as _urlquote  # noqa: E402

_raw_fetch = fetch


def fetch(url, dest, max_time=120):  # noqa: F811
    return _raw_fetch(_urlquote(url, safe=":/?&=%-._~+"), dest, max_time=max_time)


def registry():
    reg = {}
    for ln in (PILOT / "data" / "jurisdictions.jsonl").read_text().splitlines():
        r = json.loads(ln)
        if r["kind"] == "lga":
            reg[r["code"]] = r["name"]
    return reg


def hf_api():
    sys.path.insert(0, "/opt/hatch/workflow-skills/custom-connector-setup/bin")
    from dynamic_credentials import dynamic_credential_entry
    entry = dynamic_credential_entry("custom.huggingface")
    token = str(entry["surrogate"]).strip() if entry and entry.get("surrogate") else None
    if not token:
        raise RuntimeError("no HF surrogate credential")
    from huggingface_hub import HfApi
    return HfApi(token=token), token


def build_council(code, cfg, reg):
    name = reg[code]
    jid = AU.normalize(code)
    rows, docs = [], []
    for title, url in cfg["docs"]:
        stem = f"au_{code}_" + re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        dest = PDFS / f"{stem}.pdf"
        if dest.exists() and dest.read_bytes()[:5] == b"%PDF-":
            f = {"status": 200, "bytes": dest.stat().st_size, "is_pdf": True, "seconds": 0, "cached": True}
        else:
            f = fetch(url, dest)
        rec = {"title": title, "source_url": url, "fetch": f}
        if not f["is_pdf"]:
            rec["error"] = f"fetch status {f['status']}, not a PDF"
            docs.append(rec); print(f"[{code}] FAIL {title}: {rec['error']}", flush=True); continue
        text, method = extract_text(dest)
        units = split_units(text)
        if len(units) < 2:
            units = [text.strip()] if len(text.strip()) >= 200 else []
        made = 0
        for i, unit in enumerate(units):
            first = [l for l in unit.split("\n") if l.strip()]
            label_first = first[0].strip() if first else ""
            if re.fullmatch(r"\d{1,3}\.", label_first) and len(first) > 1:
                label = f"{label_first} {first[1].strip()}"[:120]
            else:
                label = label_first[:120] or title
            body_html = "".join(f"<p>{html_mod.escape(p.strip())}</p>"
                                for p in re.split(r"\n\s*\n|\n", unit) if p.strip())
            year = ""
            m = re.search(r"(19|20)\d\d", title)
            if m: year = m.group(0)
            rows.append(make_row(jurisdiction_id=jid, jurisdiction_name=name, country="AU",
                                 doc_id=f"{stem}#{i + 1}", title=title, structural_path=title,
                                 node_label=label, body_html=body_html, source_url=url,
                                 date_effective=year, retrieved=RETRIEVED))
            made += 1
        rec.update({"method": method, "chars": len(text), "units": made})
        docs.append(rec)
        print(f"[{code}] {title}: {method}, {len(text)} chars, {made} rows", flush=True)
        time.sleep(1)
    rows = finalize_rows(drop_empty_rows(rows))
    if not rows:
        return {"code": jid, "name": name, "docs": docs, "rows": 0, "error": "no rows built"}
    table = rows_to_table(rows)
    errors = validate_table(table, jurisdiction_id=jid, jurisdiction_name=name, country="AU")
    if errors:
        return {"code": jid, "name": name, "docs": docs, "rows": len(rows), "error": f"VALIDATION FAILED: {errors}"}
    pq = DATA / f"{jid}_html.parquet"
    write_html_parquet(pq, table)
    back = read_html_parquet(pq)
    errors2 = validate_table(back, jurisdiction_id=jid, jurisdiction_name=name, country="AU")
    if errors2:
        return {"code": jid, "name": name, "docs": docs, "rows": len(rows), "error": f"RE-READ VALIDATION FAILED: {errors2}"}
    rep = validation_report(back, jurisdiction_id=jid, jurisdiction_name=name, country="AU")
    write_validation_report(DATA / f"{jid}_validation.json", rep)
    return {"code": jid, "name": name, "state": cfg["state"], "platform": cfg["platform"],
            "docs": docs, "rows": len(rows), "valid": True}


def publish_and_verify(api, token, code, reg):
    from huggingface_hub import hf_hub_download
    for local, remote in [(DATA / f"{code}_html.parquet", f"data/{code}_html.parquet"),
                          (DATA / f"{code}_validation.json", f"data/{code}_validation.json")]:
        api.upload_file(path_or_fileobj=str(local), path_in_repo=remote, repo_id=REPO,
                        repo_type="dataset", commit_message=f"AU tranche2 {code}: {remote}")
    p = hf_hub_download(REPO, f"data/{code}_html.parquet", repo_type="dataset", token=token, force_download=True)
    t = read_html_parquet(p)
    errs = validate_table(t, jurisdiction_id=code, jurisdiction_name=reg[code], country="AU")
    return {"remote_rows": t.num_rows, "errors": errs}


def main():
    config = json.loads((HERE / "config.json").read_text())
    reg = registry()
    state = json.loads(STATE.read_text()) if STATE.exists() else {"retrieved": RETRIEVED, "councils": {}}
    api, token = hf_api()
    info = api.dataset_info(REPO, files_metadata=True)
    remote = {s.rfilename for s in info.siblings or []}
    print(f"HF listing: {len(remote)} files", flush=True)
    only = sys.argv[1:]
    for code, cfg in config.items():
        if only and code not in only:
            continue
        st = state["councils"].get(code, {})
        if st.get("status") == "published_verified":
            print(f"[{code}] already published_verified, skip", flush=True); continue
        if f"data/{code}_html.parquet" in remote and code == "40070":
            pass  # Adelaide supersede handled outside driver
        try:
            res = build_council(code, cfg, reg)
            state["councils"][code] = {**res, "status": "built" if res.get("valid") else "failed"}
            STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
            if not res.get("valid"):
                print(f"[{code}] BUILD FAILED: {res.get('error')}", flush=True); continue
            ver = publish_and_verify(api, token, code, reg)
            ok = ver["remote_rows"] == res["rows"] and not ver["errors"]
            state["councils"][code].update({"status": "published_verified" if ok else "verify_failed", "verify": ver})
            print(f"[{code}] PUBLISHED rows={res['rows']} verify={ver}", flush=True)
        except Exception as exc:  # noqa: BLE001
            state["councils"][code] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            print(f"[{code}] ERROR {exc}", flush=True)
        STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    print("DRIVER DONE", json.dumps({k: (v.get("status"), v.get("rows")) for k, v in state["councils"].items()}), flush=True)


if __name__ == "__main__":
    main()
