"""France tranche 2 — finisher: retry fetch-failures once, OCR the
scanned docs (fra), per class. Usage: fr_t2_ocr.py {delib|acte}

Writes override checkpoints the merge reads AFTER the shard files:
checkpoint_<class>_retry.jsonl (fetch_failed docs that now extract
natively) and checkpoint_<class>_ocr.jsonl (scanned docs recovered
via pdftoppm 300dpi -> tesseract fra, persistent wrapper). Docs that
still fail keep their original checkpoint record (merge precedence)
and are reported by the merge as deferred/failed.

Row emission mirrors fr_t2_build exactly (compilation split for
delib, single-act for actes, document_type set on every row).
OCR is CPU-bound: docs are processed by a 2-process pool.
"""
import json
import os
import subprocess
import sys
from multiprocessing import Pool
from pathlib import Path

HF = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
sys.path.insert(0, str(HF / "fr_pilot" / "scripts"))
import fr_build as B  # noqa: E402

OUT = HF / "fr_tranche2"
CODE = "25056"
RETRIEVED = "2026-10-14"
TESS = Path.home() / "workspace" / "tools" / "bin" / "tesseract"
CLS = sys.argv[1]
assert CLS in ("delib", "acte")
name = B.REGISTRY[CODE]["jurisdiction_name"]
name_norm = B.norm(name)
PDFDIR = OUT / "scratch" / CLS / "pdf"


def emit(rows, sub_id, title, seg_text, url, date_eff, dtype):
    for ukey, label, body in B.split_units(seg_text):
        r = B.make_row(
            jurisdiction_id=CODE, jurisdiction_name=name, country="FR",
            doc_id=f"{sub_id}-{ukey}", regeling_id=sub_id, regeling_work_id=sub_id,
            title=title, structural_path=title, node_label=label,
            body_html=B.text_to_html(body), source_url=url,
            date_effective=date_eff, date_modified="", retrieved=RETRIEVED)
        r["document_type"] = dtype
        rows.append(r)


def rows_from_text(doc, text, ocr=False):
    if CLS == "delib":
        did, dtype = doc["doc_id"], "délibération"
        date_eff = doc.get("date", "") or B.parse_fr_date(text[:3000])
        rows = []
        comp = B.split_session_compilation(text)
        if comp:
            preamble, segs = comp
            if preamble:
                emit(rows, f"{did}-seance", f"{doc['title']} — séance (ouverture)",
                     preamble, doc["url"], date_eff, dtype)
            for i, (number, title, seg) in enumerate(segs):
                emit(rows, number or f"{did}-objet-{i+1}", title, seg,
                     doc["url"], date_eff, dtype)
        else:
            emit(rows, did, doc["title"], text, doc["url"], date_eff, dtype)
        return rows, date_eff
    did = doc["acte_id"].lower()
    dtype = "arrêté" if doc["type"] == "Arrêté" else "décision"
    date_eff = doc.get("date_acte", "") or B.parse_fr_date(text[:3000])
    rows = []
    emit(rows, did, doc["title"], text, doc["url"], date_eff, dtype)
    return rows, date_eff


def base_rec(doc):
    if CLS == "delib":
        return {"doc_id": doc["doc_id"], "title": doc["title"], "url": doc["url"],
                "date": doc.get("date", ""), "class": "delib", "rows": []}
    return {"doc_id": doc["acte_id"].lower(), "title": doc["title"], "url": doc["url"],
            "date": doc.get("date_acte", ""), "class": "acte",
            "acte_type": doc["type"], "domaine": doc.get("domaine", ""), "rows": []}


OCR_ENV = dict(os.environ, OMP_THREAD_LIMIT="1")
# 200 dpi for the bulk délibérations queue (the DE tranche-1
# high-volume lane's setting): ~2.25x fewer pixels than the 300 dpi
# used for the actes + the first ~211 délib docs, on a box whose
# load from five campaigns' OCR lanes is the binding constraint.
# Docs that fail the text bar at 200 dpi stay ocr_failed_* and can
# be retried at 300 dpi as a cheap final tier.
OCR_DPI = int(os.environ.get("FR_T2_OCR_DPI", "200"))


def ocr_pdf(pdf_path, workdir):
    workdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pdftoppm", "-r", str(OCR_DPI), "-png", str(pdf_path),
                    str(workdir / "pg")], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    texts = []
    for img in sorted(workdir.glob("pg-*.png")):
        # --psm 6 (uniform block) instead of tranche-1's --psm 1: the
        # OSD pass in psm 1 is several times slower and these are
        # flat single-column legal acts; OMP_THREAD_LIMIT=1 stops
        # tesseract thread-thrash on the shared 2-core box (the DE
        # tranche-1 high-volume lane uses the same psm 6 pattern).
        r = subprocess.run([str(TESS), str(img), "stdout", "-l", "fra",
                            "--psm", "6"], capture_output=True, text=True,
                           env=OCR_ENV)
        texts.append(r.stdout)
        img.unlink()
    return "\n".join(texts)


def ocr_one(arg):
    doc, did = arg
    rec = base_rec(doc)
    pdf_path = PDFDIR / f"{did}.pdf"
    try:
        text = ocr_pdf(pdf_path, OUT / "scratch" / CLS / "ocr" / did.replace("/", "_"))
    except Exception as e:  # noqa: BLE001
        rec["status"] = f"ocr_failed: {type(e).__name__}: {str(e)[:100]}"
        return rec
    rec["ocr_chars"] = len(text.strip())
    if len(text.strip()) < B.MIN_TEXT:
        rec["status"] = "ocr_failed_still_deferred"
        return rec
    rows, date_eff = rows_from_text(doc, text, ocr=True)
    rec["rows"] = [dict(r) for r in rows]
    rec["n_rows"] = len(rows)
    rec["date_effective"] = date_eff
    rec["attribution"] = "name_in_text" if name_norm in B.norm(text) else "official_listing"
    rec["status"] = "ok_ocr"
    return rec


def latest_records():
    """Latest record per doc_id, WITHOUT row payloads (the délib shard
    checkpoints hold ~25k rows of text; keeping them in the finisher's
    memory alongside two workers contributed to the first run's death
    — BrokenPipe from a vanished parent)."""
    recs = {}
    for p in sorted(OUT.glob(f"checkpoint_{CLS}_shard*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                r.pop("rows", None)
                recs[r["doc_id"]] = r
    return recs


def already_done(fname):
    p = OUT / fname
    done = set()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["doc_id"])
    return done


def main():
    if CLS == "delib":
        corpus = json.loads((OUT / "delib_pre2024_corpus.json").read_text(encoding="utf-8"))["docs"]
        by_id = {d["doc_id"]: d for d in corpus}
    else:
        corpus = json.loads((OUT / "actes_corpus.json").read_text(encoding="utf-8"))["docs"]
        by_id = {d["acte_id"].lower(): d for d in corpus}
    recs = latest_records()
    deferred = [r["doc_id"] for r in recs.values() if r.get("status") == "ocr_deferred_scanned_pdf"]
    failed = [r["doc_id"] for r in recs.values() if str(r.get("status", "")).startswith("fetch_failed")]
    print(f"{CLS}: deferred={len(deferred)} fetch_failed={len(failed)}", flush=True)

    # --- retry fetch-failures natively (sequential, network-bound) ---
    retry_done = already_done(f"checkpoint_{CLS}_retry.jsonl")
    failed = [d for d in failed if d not in retry_done]
    if failed:
        fx = B.Fetcher()
        n_ok = 0
        with (OUT / f"checkpoint_{CLS}_retry.jsonl").open("a", encoding="utf-8") as fh:
            for did in failed:
                doc = by_id[did]
                rec = base_rec(doc)
                cache = PDFDIR / f"{did}.pdf"
                if cache.exists() and cache.stat().st_size == 0:
                    cache.unlink()
                try:
                    pdf = fx.get(doc["url"], cache_path=cache)
                    text, npages = B.pdf_text(pdf)
                except Exception as e:  # noqa: BLE001
                    rec["status"] = f"fetch_failed: {type(e).__name__}: {str(e)[:100]}"
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fh.flush()
                    continue
                rec["pages"] = npages
                if len(text.strip()) < B.MIN_TEXT:
                    rec["status"] = "ocr_deferred_scanned_pdf"  # flows into OCR pass below
                    deferred.append(did)
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fh.flush()
                    continue
                rows, date_eff = rows_from_text(doc, text)
                rec["rows"] = [dict(r) for r in rows]
                rec["n_rows"] = len(rows)
                rec["date_effective"] = date_eff
                rec["attribution"] = "name_in_text" if name_norm in B.norm(text) else "official_listing"
                rec["status"] = "ok"
                n_ok += 1
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
        print(f"{CLS}: retry done, recovered:", n_ok, "/", len(failed), flush=True)

    # --- OCR the deferred (parallel pool, incremental writes) ---
    # Sliced pools (120 docs per Pool lifetime, chunksize=1, queue
    # sorted by page count ascending): a pool/parent failure loses at
    # most one slice of in-flight work, and completed records are
    # already flushed to the checkpoint (resume via already_done).
    ocr_done = already_done(f"checkpoint_{CLS}_ocr.jsonl")
    todo = [d for d in sorted(set(deferred)) if d not in ocr_done]
    pages_of = {r["doc_id"]: (r.get("pages") or 0) for r in recs.values()}
    todo.sort(key=lambda d: (pages_of.get(d, 0), d))
    if os.environ.get("FR_T2_OCR_RETRY_FAILED"):
        # Final tier (run by the stage-2 closer at 300 dpi): docs
        # whose OCR already failed the text bar get one more attempt.
        latest_ocr = {}
        p = OUT / f"checkpoint_{CLS}_ocr.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    latest_ocr[r["doc_id"]] = r.get("status", "")
        todo = sorted((d for d, s in latest_ocr.items()
                       if str(s).startswith("ocr_failed")),
                      key=lambda d: (pages_of.get(d, 0), d))
        print(f"{CLS}: retry-failed tier: {len(todo)} docs re-queued", flush=True)
    total_todo = len(todo)
    n_ok_total = 0
    done_total = 0
    SLICE = 120
    for s0 in range(0, total_todo, SLICE):
        batch = todo[s0:s0 + SLICE]
        args = [(by_id[did], did) for did in batch]
        try:
            with (OUT / f"checkpoint_{CLS}_ocr.jsonl").open("a", encoding="utf-8") as fh:
                with Pool(2) as pool:
                    for rec in pool.imap_unordered(ocr_one, args, chunksize=1):
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        fh.flush()
                        done_total += 1
                        if rec.get("status") == "ok_ocr":
                            n_ok_total += 1
                        if done_total % 50 == 0:
                            print(f"{CLS}: ocr {done_total}/{total_todo} ok={n_ok_total}",
                                  flush=True)
        except Exception as e:  # noqa: BLE001 — slice failure: log, continue with next slice
            print(f"{CLS}: OCR slice at {s0} failed: {type(e).__name__}: {str(e)[:160]}",
                  flush=True)
    print(f"{CLS}: ocr done, recovered:", n_ok_total, "/", total_todo, flush=True)
    print(f"{CLS} FINISHER DONE", flush=True)


if __name__ == "__main__":
    main()
