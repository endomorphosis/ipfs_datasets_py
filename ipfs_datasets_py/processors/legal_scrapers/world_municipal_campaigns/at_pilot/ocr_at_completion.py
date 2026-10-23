#!/usr/bin/env python3
"""Austria/Carinthia OCR completion pass (2026-10-14).

Recovers the 19 scanned/image PDFs the pilot deferred (tesseract was
missing then). Reuses harvest_at_pilot.py wholesale: cached listing
HTML parse, the pilot's digital extract_text chain (a doc is deferred
iff its digital text is <100 chars — the pilot's own rule), its
split_articles / date_effective / iso_date helpers and
normalize.make_row row building, and the world_municipal fail-closed
gates. New here is only the OCR step itself: pdftoppm 300 dpi ->
tesseract deu, for the deferred docs only.

Phases: identify | ocr | build | all
Artifacts: ocr_work/at_deferred.json, ocr_work/text/*.txt,
ocr_work/ocr_stats.json, ocr_work/backup/<gkz>/ (pre-supersede copies),
ocr_work/ocr_summary.json. Merged parquets land in out/ (supersede).
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harvest_at_pilot as H  # noqa: E402
from ipfs_datasets_py.processors.legal_scrapers.world_municipal import (  # noqa: E402
    normalize,
    parquet_io,
    schema as wm_schema,
)

WORK = HERE / "ocr_work"
TEXTS = WORK / "text"

# Restart-proof tesseract: the workspace-persistent tessroot binary +
# this run's own tessdata dir (deu copied in 2026-10-14 after two VM
# restarts wiped the apt install mid-run). Falls back to PATH tesseract
# only if the tessroot binary is absent.
_TESSROOT = Path.home() / "workspace/tools/tessroot/usr"
_TESSBIN = _TESSROOT / "bin/tesseract"
if _TESSBIN.exists():
    TESS_CMD = [str(_TESSBIN), "--tessdata-dir", str(WORK / "tessdata")]
    TESS_ENV = dict(**{k: v for k, v in __import__("os").environ.items()},
                    LD_LIBRARY_PATH=str(_TESSROOT / "lib/x86_64-linux-gnu"))
else:
    TESS_CMD = ["tesseract"]
    TESS_ENV = None
GKZS = ["20911", "20503", "21001", "20701", "20802"]  # 20302 Dellach: 0 deferred
REGISTRY = {r["gkz"]: r["name"] for r in json.loads(
    (H.RAW / "statistik_at_carinthia.json").read_text(encoding="utf-8"))}


def name_probe(reg_name: str) -> str:
    return reg_name.split(" im ")[0].split(" am ")[0].split(" in ")[0].strip()


def probe_hit(text: str, probe: str) -> bool:
    """Pilot's attribution check (substring, case-insensitive), plus a
    dehyphenated variant for OCR line-break hyphenation."""
    if not probe:
        return False
    p = probe.lower()
    t = text.lower()
    if p in t:
        return True
    t2 = re.sub(r"-\s*\n\s*", "", t)
    t2 = re.sub(r"\s+", " ", t2)
    return p in t2


def page_count(pdf: Path) -> int:
    try:
        import fitz
        d = fitz.open(pdf)
        n = d.page_count
        d.close()
        return n
    except Exception:
        return 0


def identify():
    WORK.mkdir(parents=True, exist_ok=True)
    deferred = []
    for gkz in GKZS:
        html_text = (H.RAW / f"listing_{gkz}.html").read_text(encoding="utf-8")
        docs = H.parse_listing(gkz, html_text)
        pdf_dir = H.RAW / "pdf" / gkz
        n_def = 0
        for doc in docs:
            dest = pdf_dir / doc["file_name"]
            if not dest.exists():
                print(f"MISSING PDF {gkz} {doc['file_name']}", flush=True)
                continue
            text, method, _pages = H.extract_text(dest)
            if len(text.strip()) < 100:
                n_def += 1
                deferred.append({
                    "gkz": gkz, "name": REGISTRY[gkz],
                    "file_name": doc["file_name"], "hub_id": doc["hub_id"],
                    "title": doc["title"], "sachgebiet": doc["sachgebiet"],
                    "published_raw": doc["published_raw"],
                    "is_annex": doc["is_annex"], "url": doc["url"],
                    "pages": page_count(dest),
                    "pdf_bytes": dest.stat().st_size,
                    "digital_chars": len(text.strip()),
                    "digital_method": method,
                })
                print(f"deferred {gkz} {doc['file_name']} "
                      f"({deferred[-1]['pages']} pp, {dest.stat().st_size} B)",
                      flush=True)
        print(f"{gkz} {REGISTRY[gkz]}: {n_def} deferred of {len(docs)} listed",
              flush=True)
    (WORK / "at_deferred.json").write_text(
        json.dumps(deferred, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"TOTAL deferred: {len(deferred)}")
    return deferred


def ocr_doc(entry) -> dict:
    pdf = H.RAW / "pdf" / entry["gkz"] / entry["file_name"]
    tmp = WORK / "pages" / f"{entry['gkz']}_{entry['hub_id'] or 'x'}"
    tmp.mkdir(parents=True, exist_ok=True)
    prefix = tmp / "p"
    subprocess.run(["pdftoppm", "-r", "300", "-png", str(pdf), str(prefix)],
                   check=True, timeout=3600)
    pngs = sorted(tmp.glob("p*.png"))
    pages_text = []
    for png in pngs:
        o = subprocess.run(TESS_CMD + [str(png), "stdout", "-l", "deu"],
                           capture_output=True, timeout=600, env=TESS_ENV)
        pages_text.append(o.stdout.decode("utf-8", errors="replace"))
        png.unlink(missing_ok=True)
    text = "\n".join(pages_text)
    TEXTS.mkdir(parents=True, exist_ok=True)
    key = f"{entry['gkz']}_{entry['hub_id'] or entry['file_name']}"
    (TEXTS / f"{key}.txt").write_text(text, encoding="utf-8")
    tmp.rmdir()
    chars = len(text.strip())
    nons = re.sub(r"\s+", "", text)
    alpha = sum(c.isalpha() for c in nons)
    st = dict(entry)
    st.update({
        "ocr_chars": chars,
        "ocr_pages_rendered": len(pngs),
        "alpha_ratio": round(alpha / max(1, len(nons)), 3),
        "chars_per_page": round(chars / max(1, len(pngs)), 1),
        "name_hit": probe_hit(text, name_probe(entry["name"])),
        "text_file": f"text/{key}.txt",
    })
    return st


def ocr_all():
    deferred = json.loads((WORK / "at_deferred.json").read_text(encoding="utf-8"))
    stats_path = WORK / "ocr_stats.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else []
    done = {(s["gkz"], s["file_name"]) for s in stats}
    for e in deferred:
        if (e["gkz"], e["file_name"]) in done:
            print(f"skip OCR (done) {e['gkz']} {e['file_name']}", flush=True)
            continue
        t0 = time.time()
        st = ocr_doc(e)
        st["ocr_seconds"] = round(time.time() - t0, 1)
        # Quality gate: enough text, mostly letters, attribution probe hit.
        reasons = []
        if st["ocr_chars"] < 300:
            reasons.append(f"only {st['ocr_chars']} OCR chars (near-empty)")
        if st["alpha_ratio"] < 0.55:
            reasons.append(f"alpha ratio {st['alpha_ratio']} < 0.55 (garbled?)")
        if not st["name_hit"]:
            reasons.append("Gemeinde name not found in OCR text (attribution)")
        st["quality_pass"] = not reasons
        st["quality_reasons"] = reasons
        stats.append(st)
        stats_path.write_text(json.dumps(stats, indent=1, ensure_ascii=False),
                              encoding="utf-8")
        print(f"OCR {e['gkz']} {e['file_name']}: {st['ocr_chars']} chars, "
              f"{st['ocr_pages_rendered']} pp, alpha {st['alpha_ratio']}, "
              f"name_hit={st['name_hit']}, pass={st['quality_pass']} "
              f"{reasons if reasons else ''} ({st['ocr_seconds']}s)", flush=True)
    return stats


def build():
    stats = json.loads((WORK / "ocr_stats.json").read_text(encoding="utf-8"))
    passing = {}
    for s in stats:
        if s["quality_pass"]:
            passing.setdefault(s["gkz"], []).append(s)
    summary = []
    for gkz in GKZS:
        reg_name = REGISTRY[gkz]
        out_path = H.OUT / f"{gkz}_html.parquet"
        old_table = parquet_io.read_html_parquet(out_path)
        rows_before = old_table.num_rows
        docs = passing.get(gkz, [])
        if not docs:
            summary.append({"gkz": gkz, "name": reg_name, "rows_before": rows_before,
                            "rows_after": rows_before, "rows_added": 0,
                            "docs_recovered": 0})
            print(f"{gkz}: no passing docs, parquet untouched ({rows_before} rows)",
                  flush=True)
            continue
        new_rows = []
        for s in docs:
            text = (WORK / s["text_file"]).read_text(encoding="utf-8")
            eff = H.date_effective(text)
            pub_iso = H.iso_date(s["published_raw"])
            segs = H.split_articles(text)
            for si, (label, seg) in enumerate(segs):
                doc_id = f"{gkz}-{s['hub_id'] or s['file_name']}"
                if len(segs) > 1:
                    doc_id = f"{doc_id}-{si}"
                new_rows.append(normalize.make_row(
                    jurisdiction_id=gkz,
                    jurisdiction_name=reg_name,
                    country="AT",
                    doc_id=doc_id,
                    regeling_id=re.sub(r"\.pdf$", "", s["file_name"], flags=re.I),
                    regeling_work_id=re.sub(r"\.pdf$", "", s["file_name"], flags=re.I),
                    title=s["title"],
                    structural_path=s["title"],
                    node_label=label,
                    body_html=H.text_to_html(seg),
                    text=seg,
                    source_url=s["url"],
                    date_effective=eff,
                    date_modified=pub_iso,
                    retrieved=H.RETRIEVED,
                    sachgebiet=s["sachgebiet"],
                ))
        combined = old_table.to_pylist() + new_rows
        combined = normalize.finalize_rows(normalize.drop_empty_rows(combined))
        table = wm_schema.rows_to_table(combined, extra_columns=H.EXTRA_COLS)
        report = wm_schema.validation_report(
            table, jurisdiction_id=gkz, jurisdiction_name=reg_name, country="AT")
        if not report["valid"]:
            raise RuntimeError(f"{gkz} merged table INVALID: {report['errors']}")
        bdir = WORK / "backup" / gkz
        bdir.mkdir(parents=True, exist_ok=True)
        for f in (out_path, H.OUT / f"{gkz}_validation.json"):
            if f.exists():
                (bdir / f.name).write_bytes(f.read_bytes())
        parquet_io.write_html_parquet(out_path, table)
        parquet_io.write_validation_report(H.OUT / f"{gkz}_validation.json", report)
        # re-read gate
        back = parquet_io.read_html_parquet(out_path)
        errs = wm_schema.validate_table(back, jurisdiction_id=gkz,
                                        jurisdiction_name=reg_name, country="AT")
        assert not errs, f"{gkz} re-read validation failed: {errs}"
        rec = {"gkz": gkz, "name": reg_name, "rows_before": rows_before,
               "rows_after": table.num_rows,
               "rows_added": table.num_rows - rows_before,
               "docs_recovered": len(docs),
               "recovered_files": [s["file_name"] for s in docs]}
        summary.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    (WORK / "ocr_summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    return summary


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    if phase in ("identify", "all"):
        identify()
    if phase in ("ocr", "all"):
        ocr_all()
    if phase in ("build", "all"):
        build()


if __name__ == "__main__":
    main()
