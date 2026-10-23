"""France tranche 2 — sharded harvest of Besançon pre-2024
délibérations (1989–2023) and actes (arrêtés/décisions, 2022–2026).

Usage: fr_t2_build.py {delib|acte} SHARD_INDEX SHARD_COUNT

Row semantics identical to the pilot/tranche-1 builders (imported
from fr_pilot): preamble + per-Article rows where present, else one
body row; session compilations split per délibération (delib class
only — each acte PDF is a single act). Every row carries the extra
`document_type` column (schema-sanctioned extension): "délibération"
for the council corpus, the actes service's own type normalized
("arrêté" / "décision") for actes.

Per-doc checkpoints (checkpoint_<class>_shard<N>.jsonl) make every
shard resumable; PDFs cached under scratch/<class>/pdf/. Scanned
docs (<100 chars native text) are checkpointed as
ocr_deferred_scanned_pdf for the OCR finisher.
"""
import json
import sys
import time
from pathlib import Path

HF = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
sys.path.insert(0, str(HF / "fr_pilot" / "scripts"))
import fr_build as B  # noqa: E402

OUT = HF / "fr_tranche2"
CODE = "25056"
RETRIEVED = "2026-10-14"
CLS = sys.argv[1]
SHARD = int(sys.argv[2])
NSHARDS = int(sys.argv[3])
assert CLS in ("delib", "acte")

fx = B.Fetcher()
info = B.REGISTRY[CODE]
name = info["jurisdiction_name"]
name_norm = B.norm(name)
PDFDIR = OUT / "scratch" / CLS / "pdf"
PDFDIR.mkdir(parents=True, exist_ok=True)
MY_CKPT = OUT / f"checkpoint_{CLS}_shard{SHARD}.jsonl"


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


def fetch_pdf(url, did):
    cache = PDFDIR / f"{did}.pdf"
    if cache.exists() and cache.stat().st_size > 0:
        return cache.read_bytes()
    return fx.get(url, cache_path=cache)


def delib_rows(doc):
    did = doc["doc_id"]
    rec = {"doc_id": did, "title": doc["title"], "url": doc["url"],
           "date": doc.get("date", ""), "class": "delib", "rows": []}
    try:
        text, npages = B.pdf_text(fetch_pdf(doc["url"], did))
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
    comp = B.split_session_compilation(text)
    if comp:
        preamble, segs = comp
        if preamble:
            emit(rows, f"{did}-seance", f"{doc['title']} — séance (ouverture)",
                 preamble, doc["url"], date_eff, "délibération")
        for i, (number, title, seg) in enumerate(segs):
            emit(rows, number or f"{did}-objet-{i+1}", title, seg,
                 doc["url"], date_eff, "délibération")
        rec["sub_docs"] = len(segs)
    else:
        emit(rows, did, doc["title"], text, doc["url"], date_eff, "délibération")
    rec["rows"] = rows
    rec["n_rows"] = len(rows)
    rec["status"] = "ok"
    return rec


def acte_rows(doc):
    did = doc["acte_id"].lower()
    dtype = "arrêté" if doc["type"] == "Arrêté" else "décision"
    rec = {"doc_id": did, "title": doc["title"], "url": doc["url"],
           "date": doc.get("date_acte", ""), "class": "acte",
           "acte_type": doc["type"], "domaine": doc.get("domaine", ""), "rows": []}
    try:
        text, npages = B.pdf_text(fetch_pdf(doc["url"], did.replace("/", "_")))
    except Exception as e:  # noqa: BLE001
        rec["status"] = f"fetch_failed: {type(e).__name__}: {str(e)[:100]}"
        return rec
    rec["pages"] = npages
    if len(text.strip()) < B.MIN_TEXT:
        rec["status"] = "ocr_deferred_scanned_pdf"
        return rec
    rec["attribution"] = "name_in_text" if name_norm in B.norm(text) else "official_listing"
    date_eff = doc.get("date_acte", "") or B.parse_fr_date(text[:3000])
    rec["date_effective"] = date_eff
    rows = []
    emit(rows, did, doc["title"], text, doc["url"], date_eff, dtype)
    rec["rows"] = rows
    rec["n_rows"] = len(rows)
    rec["status"] = "ok"
    return rec


def load_done():
    done = set()
    for p in OUT.glob(f"checkpoint_{CLS}*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["doc_id"])
    return done


def main():
    if CLS == "delib":
        corpus = json.loads((OUT / "delib_pre2024_corpus.json").read_text(encoding="utf-8"))["docs"]
        key = lambda d: d["doc_id"]  # noqa: E731
        process = delib_rows
    else:
        corpus = json.loads((OUT / "actes_corpus.json").read_text(encoding="utf-8"))["docs"]
        key = lambda d: d["acte_id"].lower()  # noqa: E731
        process = acte_rows
    done = load_done()
    mine = [d for i, d in enumerate(corpus) if i % NSHARDS == SHARD]
    todo = [d for d in mine if key(d) not in done]
    print(f"{CLS} shard {SHARD}/{NSHARDS}: mine={len(mine)} todo={len(todo)}", flush=True)
    n = 0
    with MY_CKPT.open("a", encoding="utf-8") as fh:
        for doc in todo:
            rec = process(doc)
            rec["rows"] = [dict(r) for r in rec["rows"]]
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if n % 50 == 0:
                print(f"{CLS} shard {SHARD}: +{n}/{len(todo)}", flush=True)
            time.sleep(0.15)
    print(f"{CLS} shard {SHARD} DONE (+{n})", flush=True)


if __name__ == "__main__":
    main()
