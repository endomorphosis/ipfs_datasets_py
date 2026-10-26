"""Finder-fix-2 validation harness (offline, scan-equivalent).

For each of the 8 OCR-recovery target works: runs find_segment on every
stream (recording tier, boundaries, raw + cleaned segment sha256) and
build_work_rows in memory (recording status/rows + per-row sha256).
Writes nothing to the tranche state. Usage:
  seg_harness_finderfix2.py <out.json>
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
import za_pdf_tranche_build as B
import za_ocr_recovery_build as R


def h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def main():
    out_path = sys.argv[1]
    works = [w for w in B.load_excluded() if w["work"] in R.TARGET_WORKS]
    works.sort(key=lambda w: R.TARGET_WORKS.index(w["work"]))
    dl = {}
    for line in open(B.OUT / "progress.jsonl"):
        try:
            rec = json.loads(line)
            if rec.get("phase") == "download":
                dl[rec["key"]] = rec
        except Exception:  # noqa: BLE001
            pass
    result = {}
    for w in works:
        code = w["mdb"]
        jname = B.PLACES[[k for k, v in B.PLACES.items() if v[0] == code][0]][1]
        code_norm = B.ZA.normalize(code)
        entry = {"segs": {}}
        streams, method = B.get_streams(w)
        for nm, pages in streams.items():
            s, t, st, en = B.find_segment(pages, w)
            if s:
                entry["segs"][nm] = {
                    "tier": t, "start": list(st), "end": list(en),
                    "raw_chars": len(s), "raw_sha": h(s),
                    "clean_chars": len(B.clean_segment(s)),
                    "clean_sha": h(B.clean_segment(s)),
                }
            else:
                entry["segs"][nm] = {"tier": None, "reason": t}
        info, rows = R.build_work_rows(w, code, jname, code_norm, dl)
        entry["info"] = {k: info.get(k) for k in
                          ("status", "reason", "rows", "units", "method",
                           "stream", "tier", "seg_pages", "seg_chars")}
        entry["rows"] = [
            {"doc_id": r["doc_id"], "chars": len(r.get("text") or ""),
             "sha": h(json.dumps(r, sort_keys=True, default=str))}
            for r in rows]
        result[w["work"]] = entry
        print(f"{w['work']}: status={entry['info']['status']} "
              f"tier={entry['info']['tier']} rows={entry['info']['rows']} "
              f"segs={ {k: v.get('tier') for k, v in entry['segs'].items()} }",
              flush=True)
    Path(out_path).write_text(json.dumps(result, indent=1))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
