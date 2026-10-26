"""France tranche 1 — Besançon 25056 FULL corpus build.

Reuses the pilot builder's functions (imported from fr_pilot) for
identical row semantics and doc-id scheme; differences vs the pilot:
- fresh session enumeration (no cached session JSONs),
- ALL corpus docs processed (no even_sample),
- per-doc checkpoint: extracted rows for each completed doc are
  appended to rows_checkpoint.jsonl so an interrupted run resumes
  without re-fetching,
- PDFs cached under fr_tranche1/scratch/25056/pdf (pilot cache is
  consulted read-only as a fallback mirror to save re-downloads).

Gates: same world_municipal fail-closed validation as the pilot;
scanned docs (<100 chars native text) stay ocr_deferred.
"""
import json
import sys
import time
from pathlib import Path

HF = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
sys.path.insert(0, str(HF / "fr_pilot" / "scripts"))
import fr_build as B  # noqa: E402

OUT = HF / "fr_tranche1"
DATA = OUT / "data"
DATA.mkdir(parents=True, exist_ok=True)
SCRATCH = OUT / "scratch" / "25056"
SCRATCH.mkdir(parents=True, exist_ok=True)
PILOT_PDF_CACHE = HF / "fr_pilot" / "scratch" / "25056" / "pdf"
CODE = "25056"
CKPT = OUT / "checkpoint_25056.jsonl"
RETRIEVED = "2026-10-14"

fx = B.Fetcher()
info = B.REGISTRY[CODE]
name = info["jurisdiction_name"]
name_norm = B.norm(name)


def fresh_enum(years=(2024, 2025, 2026)):
    docs = []
    per_year = {}
    for year in years:
        api = ("https://datasets.grandbesancon.fr/besanconfr.php"
               f"?method=getConseilsMunicipaux&year={year}&output=json")
        try:
            sessions = fx.get_json(api)  # no cache_path: always fresh
        except Exception as e:  # noqa: BLE001
            per_year[year] = f"failed: {type(e).__name__}: {str(e)[:100]}"
            continue
        (SCRATCH / f"besancon_{year}_fresh.json").write_text(
            json.dumps(sessions, ensure_ascii=False), encoding="utf-8")
        n = 0
        for sess in sessions:
            for d in sess.get("deliberations", []):
                if d.get("urlPdf"):
                    docs.append({"title": (d.get("titre") or "").strip(),
                                 "url": d["urlPdf"],
                                 "date": (d.get("date") or sess.get("date") or "")[:10],
                                 "session": sess.get("titre", "")})
                    n += 1
        per_year[year] = n
    docs.sort(key=lambda d: (d["date"], d["title"]))
    # dedupe on URL (same act can appear under two sessions?)
    seen, uniq = set(), []
    for d in docs:
        if d["url"] not in seen:
            seen.add(d["url"])
            uniq.append(d)
    return uniq, per_year


def load_checkpoint():
    done = {}
    if CKPT.exists():
        for line in CKPT.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["doc_id"]] = rec
    return done


def doc_rows(doc):
    """Process one doc; returns (rec, [row dicts as lists via make_row])."""
    did = doc["url"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
    rec = {"doc_id": did, "title": doc["title"], "url": doc["url"], "rows": []}
    cache = SCRATCH / "pdf" / f"{did}.pdf"
    pilot_cache = PILOT_PDF_CACHE / f"{did}.pdf"
    try:
        if cache.exists() and cache.stat().st_size > 0:
            pdf = cache.read_bytes()
        elif pilot_cache.exists() and pilot_cache.stat().st_size > 0:
            pdf = pilot_cache.read_bytes()
        else:
            pdf = fx.get(doc["url"], cache_path=cache)
        text, npages = B.pdf_text(pdf)
    except Exception as e:  # noqa: BLE001
        rec["status"] = f"fetch_failed: {type(e).__name__}: {str(e)[:100]}"
        return rec
    rec["pages"] = npages
    if len(text.strip()) < B.MIN_TEXT:
        rec["status"] = "ocr_deferred_scanned_pdf"
        return rec
    rec["attribution"] = "name_in_text" if name_norm in B.norm(text) else "official_listing"
    date_eff = doc.get("date", "") or B.parse_fr_date(text[:3000])
    rec["date_effective"] = date_eff
    rows = []

    def emit(sub_id, title, seg_text):
        for ukey, label, body in B.split_units(seg_text):
            rows.append(B.make_row(
                jurisdiction_id=CODE, jurisdiction_name=name, country="FR",
                doc_id=f"{sub_id}-{ukey}", regeling_id=sub_id, regeling_work_id=sub_id,
                title=title, structural_path=title, node_label=label,
                body_html=B.text_to_html(body), source_url=doc["url"],
                date_effective=date_eff, date_modified="", retrieved=RETRIEVED))

    comp = B.split_session_compilation(text)
    if comp:
        preamble, segs = comp
        if preamble:
            emit(f"{did}-seance", f"{doc['title']} — séance (ouverture)", preamble)
        for i, (number, title, seg) in enumerate(segs):
            emit(number or f"{did}-objet-{i+1}", title, seg)
        rec["sub_docs"] = len(segs)
    else:
        emit(did, doc["title"], text)
    rec["rows"] = [r for r in rows]
    rec["n_rows"] = len(rows)
    rec["status"] = "ok"
    return rec


def main():
    corpus, per_year = fresh_enum()
    print("fresh enumeration per year:", per_year, "total unique docs:", len(corpus), flush=True)
    (OUT / "besancon_corpus.json").write_text(
        json.dumps({"per_year": per_year, "total": len(corpus), "docs": corpus},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    done = load_checkpoint()
    print("checkpointed docs:", len(done), flush=True)
    n_new = 0
    with CKPT.open("a", encoding="utf-8") as fh:
        for i, doc in enumerate(corpus):
            did = doc["url"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
            if did in done:
                continue
            rec = doc_rows(doc)
            # store rows as plain dicts for JSON checkpointing
            rec["rows"] = [dict(r) for r in rec["rows"]]
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            done[did] = rec
            n_new += 1
            if n_new % 25 == 0:
                ok = sum(1 for r in done.values() if r.get("status") == "ok")
                print(f"progress: {len(done)}/{len(corpus)} docs, ok={ok}", flush=True)
            time.sleep(0.3)
    print("all docs processed:", len(done), flush=True)

    # Build the table from checkpoints
    all_rows, doc_meta = [], []
    for doc in corpus:
        did = doc["url"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
        rec = done.get(did)
        if rec is None:
            doc_meta.append({"doc_id": did, "status": "missing_checkpoint"})
            continue
        doc_meta.append({k: v for k, v in rec.items() if k != "rows"})
        all_rows.extend(rec.get("rows", []))
    all_rows = B.drop_empty_rows(B.finalize_rows(all_rows))
    table = B.rows_to_table(all_rows)
    errs = B.validate_table(table, jurisdiction_id=CODE, jurisdiction_name=name, country="FR")
    print("rows:", table.num_rows, "valid:", not errs, "errors:", errs[:5], flush=True)
    result = {"corpus_docs": len(corpus), "per_year": per_year,
              "docs_ok": sum(1 for d in doc_meta if d.get("status") == "ok"),
              "docs_ocr_deferred": sum(1 for d in doc_meta if d.get("status") == "ocr_deferred_scanned_pdf"),
              "docs_fetch_failed": sum(1 for d in doc_meta if str(d.get("status", "")).startswith("fetch_failed")),
              "rows": table.num_rows, "valid": not errs, "errors": errs}
    (OUT / "besancon_build_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "besancon_doc_meta.json").write_text(
        json.dumps(doc_meta, ensure_ascii=False, indent=1), encoding="utf-8")
    if not errs and table.num_rows:
        B.write_html_parquet(DATA / B.FR.file_name(CODE), table)
        B.write_validation_report(DATA / f"{CODE}_validation.json",
                                  B.validation_report(table, jurisdiction_id=CODE,
                                                      jurisdiction_name=name, country="FR"))
        t2 = B.read_html_parquet(DATA / B.FR.file_name(CODE))
        print("reread valid:", not B.validate_table(
            t2, jurisdiction_id=CODE, jurisdiction_name=name, country="FR"), flush=True)
    print("BUILD DONE", flush=True)


if __name__ == "__main__":
    main()
