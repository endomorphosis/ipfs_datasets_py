"""France tranche 1 — OCR the 2 scanned Besançon docs and republish.

Route is robots-allowed and the tessroot now carries fra, so the
deferred lane opens for these two docs only. Pipeline: pdftoppm
300 dpi -> tesseract fra (persistent wrapper) -> the same row
emission as fr_full_build.doc_rows. The two checkpoint records are
replaced in a dedicated checkpoint file that the merge step reads
LAST (it overrides by doc_id), then the merged parquet is rebuilt,
re-validated, superseded in place, and remote-verified.
"""
import json
import subprocess
import sys
from pathlib import Path

HF = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
sys.path.insert(0, str(HF / "fr_pilot" / "scripts"))
sys.path.insert(0, str(HF / "fr_tranche1" / "scripts"))
import fr_build as B  # noqa: E402
import fr_full_build as F  # noqa: E402

OUT = HF / "fr_tranche1"
TESS = Path.home() / "workspace" / "tools" / "bin" / "tesseract"
IDS = {"0000c8b5", "0000cae3"}
CODE = "25056"
name = B.REGISTRY[CODE]["jurisdiction_name"]
name_norm = B.norm(name)


def ocr_pdf(pdf_path, workdir):
    workdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pdftoppm", "-r", "300", "-png", str(pdf_path),
                    str(workdir / "pg")], check=True)
    texts = []
    for img in sorted(workdir.glob("pg-*.png")):
        r = subprocess.run([str(TESS), str(img), "stdout", "-l", "fra",
                            "--psm", "1"], capture_output=True, text=True)
        texts.append(r.stdout)
    return "\n".join(texts)


def rows_for(doc, text):
    did = doc["url"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
    date_eff = doc.get("date", "") or B.parse_fr_date(text[:3000])
    rows = []

    def emit(sub_id, title, seg_text):
        for ukey, label, body in B.split_units(seg_text):
            rows.append(B.make_row(
                jurisdiction_id=CODE, jurisdiction_name=name, country="FR",
                doc_id=f"{sub_id}-{ukey}", regeling_id=sub_id, regeling_work_id=sub_id,
                title=title, structural_path=title, node_label=label,
                body_html=B.text_to_html(body), source_url=doc["url"],
                date_effective=date_eff, date_modified="", retrieved="2026-10-14"))
    comp = B.split_session_compilation(text)
    if comp:
        preamble, segs = comp
        if preamble:
            emit(f"{did}-seance", f"{doc['title']} — séance (ouverture)", preamble)
        for i, (number, title, seg) in enumerate(segs):
            emit(number or f"{did}-objet-{i+1}", title, seg)
    else:
        emit(did, doc["title"], text)
    return rows, date_eff


def main():
    corpus = json.loads((OUT / "besancon_corpus.json").read_text(encoding="utf-8"))["docs"]
    by_id = {d["url"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower(): d for d in corpus}
    out_recs = []
    for did in sorted(IDS):
        doc = by_id[did]
        pdf_path = OUT / "scratch" / "25056" / "pdf" / f"{did}.pdf"
        text = ocr_pdf(pdf_path, OUT / "scratch" / "ocr" / did)
        rec = {"doc_id": did, "title": doc["title"], "url": doc["url"],
               "ocr_chars": len(text.strip())}
        if len(text.strip()) < B.MIN_TEXT:
            rec["status"] = "ocr_failed_still_deferred"
            rec["rows"] = []
        else:
            rows, date_eff = rows_for(doc, text)
            rec["rows"] = [dict(r) for r in rows]
            rec["n_rows"] = len(rows)
            rec["date_effective"] = date_eff
            rec["attribution"] = "name_in_text" if name_norm in B.norm(text) else "official_listing"
            rec["status"] = "ok_ocr"
        out_recs.append(rec)
        print(did, rec["status"], "chars:", rec["ocr_chars"], "rows:", rec.get("n_rows", 0), flush=True)
    with (OUT / "checkpoint_25056_ocr.jsonl").open("w", encoding="utf-8") as fh:
        for rec in out_recs:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("OCR FINISH DONE", flush=True)


if __name__ == "__main__":
    main()
