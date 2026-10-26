"""ZA OCR recovery build — recover the 8 `scanned_image_pdf_ocr_pending`
works left by the PDF tranche, and ONLY those works.

Why not `za_pdf_tranche_build.py build` directly: phase_build asserts the
live baseline is the 15,439-row AKN layer, but the live dataset is now the
16,129-row PDF-tranche merge. This script therefore reuses the builder's
own per-work machinery (get_streams / find_segment / score_segment /
split_units / make_row / gates, imported from za_pdf_tranche_build) and
merges the new rows onto the CURRENT live parquets, with the same
preservation check (existing rows identical, new rows appended) and the
same fail-closed gates. run_manifest.json is updated cumulatively
(rows_before stays the 15,439 AKN baseline, so publish_final.py's totals
still hold: recovered + excluded == 105).

Modes:
  scan  — build candidate rows in memory, run the tranche QA
          contamination scan, print per-work outcomes; writes nothing.
  write — merge, gate, write out/<MDB>_html.parquet + validation,
          update run_manifest.json (and progress.jsonl build records).
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, ".")
import za_pdf_tranche_build as B
from world_municipal.normalize import finalize_rows  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402

OUT = B.OUT
OUTD = B.OUTD
CODES = ["CPT", "ETH", "WC023"]
TARGET_WORKS = [
    "/akn/za-cpt/act/by-law/2011/sub-council-further-amendment",
    "/akn/za-eth/act/by-law/1996/water-supply",
    "/akn/za-eth/act/mn/1998/50",
    "/akn/za-eth/act/mn/1998/51",
    "/akn/za-eth/act/mn/1998/52",
    "/akn/za-eth/act/mn/1999/7",
    "/akn/za-eth/act/mn/2012/20",
    "/akn/za-wc023/act/by-law/2007/rules-of-order-regulating-the-conduct-of-meetings",
]


def ocr_complete(w):
    """Guard: only run the builder pipeline for works whose per-page OCR
    checkpoints are complete; otherwise get_streams would block on a
    synchronous in-build OCR of the remainder. Returns (done, total)."""
    import fitz
    import hashlib
    p = B.pdf_path(w)
    doc = fitz.open(p)
    n = doc.page_count
    doc.close()
    sha = hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]
    pdir = B.TEXTS / "_ocr_pages" / sha
    done = sum(1 for i in range(n) if (pdir / f"p{i:04d}.txt").exists())
    return done, n


def build_work_rows(w, code, jname, code_norm, dl):
    """The phase_build per-work pipeline, verbatim semantics.
    Returns (info_dict, rows list)."""
    key = w["expression"]
    done, n = ocr_complete(w)
    if done < n:
        return {"work": w["work"], "title": w["title"], "status": "excluded",
                "reason": f"ocr_incomplete_at_recovery_build: {done}/{n} pages checkpointed"}, []
    rec_dl = dl.get(key, {})
    if rec_dl.get("status") != "downloaded" or not B.pdf_path(w).exists():
        return {"work": w["work"], "title": w["title"], "status": "excluded",
                "reason": f"pdf_download_failed: {rec_dl.get('error', 'not downloaded')}"}, []
    w["pdf_url"] = rec_dl.get("pdf_url") or B.pdf_url_for(w)
    try:
        streams, method = B.get_streams(w)
    except Exception as exc:  # noqa: BLE001
        return {"work": w["work"], "title": w["title"], "status": "excluded",
                "reason": f"pdf_extract_failed: {str(exc)[:160]}"}, []
    total_chars = sum(len(x.strip()) for x in streams.get("linear", []))
    if total_chars < 300:
        return {"work": w["work"], "title": w["title"], "status": "excluded",
                "method": method,
                "reason": f"no_usable_text: {total_chars} chars after full extraction chain incl. OCR"}, []
    order = (["right", "linear", "left"] if w["lang"] == "afr"
             else ["left", "linear", "right"])
    seg = tier = sname = None
    seg_start = seg_end = None
    best_score = -99
    for nm in order:
        if nm not in streams:
            continue
        s, t, st, en = B.find_segment(streams[nm], w)
        if s:
            sc = B.score_segment(B.clean_segment(s), w)
            if t == "muni+terms-loose":
                sc -= 1.0
            if sc > best_score:
                seg, tier, sname, seg_start, seg_end = s, t, nm, st, en
                best_score = sc
    if not seg:
        return {"work": w["work"], "title": w["title"], "status": "excluded",
                "method": method,
                "reason": "instrument_not_located_in_source_pdf"}, []
    seg = B.clean_segment(seg)
    if len(seg) < 200:
        return {"work": w["work"], "title": w["title"], "status": "excluded",
                "method": method,
                "reason": f"segment_too_short: {len(seg)} chars"}, []
    units = B.split_units(seg)
    parts = w["work"].split("/")
    year = parts[5] if len(parts) > 5 else ""
    slug = "-".join(parts[6:]) if len(parts) > 6 else ""
    wrows = []
    for uid, label, body in units:
        if len(body.strip()) < 20:
            continue
        wrows.append(B.make_row(
            jurisdiction_id=code_norm, jurisdiction_name=jname,
            country="ZA",
            doc_id=f"{year}-{slug}-{uid}".replace("_", "-"),
            regeling_id=w["work"], regeling_work_id=w["work"],
            title=w["title"],
            structural_path=f"{jname} > {w['title']} > {label}",
            node_label=label, body_html=B._body_html(body),
            source_url=w["expression"], xml_url=w["pdf_url"],
            date_effective=w["date"], retrieved=B.RETRIEVED,
        ))
    if not wrows:
        return {"work": w["work"], "title": w["title"], "status": "excluded",
                "method": method, "reason": "segment_yielded_no_rows"}, []
    info = {"work": w["work"], "title": w["title"],
            "status": "recovered", "rows": len(wrows),
            "units": "section" if len(units) > 1 or units[0][0] != "document" else "document",
            "method": method, "stream": sname, "tier": tier,
            "seg_pages": [seg_start[0] if seg_start else None,
                          seg_end[0] if seg_end else None],
            "seg_chars": len(seg), "pdf_url": w["pdf_url"],
            "pdf_bytes": rec_dl.get("bytes")}
    return info, wrows


def contamination_scan(new_rows_by_work, own_code):
    """Tranche QA: scan each new row's opening 400 chars for OTHER
    municipalities' names (word-boundary, >=5 chars, 257-registry)."""
    names = {}
    for e in B.REG:
        nm = B._short_name(e["name"])
        if len(nm) >= 5:
            names[nm.lower()] = e["jurisdiction_id"]
    own_names = {B._short_name(e["name"]).lower()
                 for e in B.REG if e["jurisdiction_id"] == own_code}
    flags = {}
    for work, rows in new_rows_by_work.items():
        hits = []
        for r in rows:
            head = (r.get("text") or "")[:400].lower()
            for nm, jid in names.items():
                if nm in own_names:
                    continue
                if re.search(r"\b" + re.escape(nm) + r"\b", head):
                    hits.append((r["doc_id"], nm, jid))
        if hits:
            flags[work] = hits
    return flags


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
    assert mode in ("scan", "write")
    codes = CODES
    if len(sys.argv) > 2 and sys.argv[2]:
        codes = [c.strip() for c in sys.argv[2].split(",") if c.strip()]
        assert set(codes) <= set(CODES), codes
    import pyarrow.parquet as pq
    from huggingface_hub import HfApi, hf_hub_download

    want = [t for t in TARGET_WORKS
            if any(t.startswith(f"/akn/za-{c.lower()}/") or
                   (c == "EC443" and t.startswith("/akn/za-ec443/"))
                   for c in codes)]
    # municipality of each target work, from the v2 manifest via load_excluded
    works = [w for w in B.load_excluded() if w["work"] in TARGET_WORKS
             and w["mdb"] in codes]
    assert len(works) == len(want), (len(works), len(want))
    # mn/1998/50 first so its streams populate the shared-hash cache
    works.sort(key=lambda w: TARGET_WORKS.index(w["work"]))

    dl = {}
    prog_path = OUT / "progress.jsonl"
    for line in open(prog_path):
        try:
            rec = json.loads(line)
            if rec.get("phase") == "download":
                dl[rec["key"]] = rec
        except Exception:  # noqa: BLE001
            pass

    prev = json.load(open(OUT / "run_manifest.json"))
    assert prev.get("baseline_total") == 15439

    # fresh live parquets = merge base (must equal published manifest state)
    live_dir = OUT / "live_recovery"
    live_dir.mkdir(exist_ok=True)
    HfApi()  # noqa: F841 - parity with builder (unauthenticated public read)
    REPO_ID = "endomorphosis/ipfs_south_africa_municipal_laws"
    old_rows = {}
    for code in codes:
        p = hf_hub_download(REPO_ID, f"data/{code}_html.parquet",
                            repo_type="dataset", local_dir=str(live_dir))
        old_rows[code] = pq.read_table(p).to_pylist()
        exp = prev["municipalities"][code]["rows_after"]
        assert len(old_rows[code]) == exp, (code, len(old_rows[code]), exp)
        print(f"{code}: live rows {len(old_rows[code])} == manifest rows_after {exp} OK",
              flush=True)

    results = {}   # code -> (outcomes list, {work: rows})
    for code in codes:
        jname = B.PLACES[[k for k, v in B.PLACES.items() if v[0] == code][0]][1]
        code_norm = B.ZA.normalize(code)
        outcomes, rows_by_work = [], {}
        for w in [x for x in works if x["mdb"] == code]:
            info, wrows = build_work_rows(w, code, jname, code_norm, dl)
            outcomes.append(info)
            if wrows:
                rows_by_work[w["work"]] = wrows
            print(f"[{code}] {info['status']} {w['work']} "
                  f"rows={info.get('rows', 0)} method={info.get('method')} "
                  f"reason={info.get('reason', '')[:100]}", flush=True)
        flags = contamination_scan(rows_by_work, code)
        for wk, hits in flags.items():
            print(f"  CONTAMINATION FLAGS {wk}: {hits[:6]}", flush=True)
        results[code] = (outcomes, rows_by_work, flags)

    if mode == "scan":
        print("SCAN ONLY — nothing written")
        return

    prog = open(prog_path, "a")
    for code in codes:
        outcomes, rows_by_work, flags = results[code]
        # Guard (added 2026-10-14, mn/1998 stage): works already recorded
        # as recovered in the manifest are already in the live merge base;
        # re-appending their rows would duplicate them (finalize_rows
        # suffixes duplicate doc_ids instead of dropping them). Skip such
        # works entirely in write mode — rows and manifest entry stay
        # exactly as published. Scan mode is unchanged.
        already = {e["work"] for e in prev["municipalities"][code]["recovered"]}
        skipped = [o["work"] for o in outcomes if o["work"] in already]
        if skipped:
            print(f"{code}: skipping already-published works in write: "
                  f"{skipped}", flush=True)
            outcomes = [o for o in outcomes if o["work"] not in already]
            rows_by_work = {wk: rs for wk, rs in rows_by_work.items()
                            if wk not in already}
            flags = {wk: hs for wk, hs in flags.items() if wk not in already}
        if flags:
            raise SystemExit(f"{code}: contamination flags present — refusing to write")
        jname = B.PLACES[[k for k, v in B.PLACES.items() if v[0] == code][0]][1]
        code_norm = B.ZA.normalize(code)
        new_rows = [r for rows in rows_by_work.values() for r in rows]
        if not new_rows:
            print(f"{code}: no new rows — manifest exclusions updated only", flush=True)
        combined = finalize_rows(old_rows[code] + new_rows)
        assert len(combined) == len(old_rows[code]) + len(new_rows)
        for a, b in zip(old_rows[code], combined):
            for kkey in a:
                assert str(a[kkey]) == str(b[kkey]), (code, kkey, a.get("doc_id"))
        table = rows_to_table(combined)
        errors = validate_table(table, jurisdiction_id=code_norm,
                                jurisdiction_name=jname, country="ZA")
        if errors:
            raise SystemExit(f"{code}: VALIDATION FAILED {errors}")
        outp = OUTD / f"{code}_html.parquet"
        write_html_parquet(outp, table)
        reread = read_html_parquet(outp)
        report = validation_report(reread, jurisdiction_id=code_norm,
                                   jurisdiction_name=jname, country="ZA")
        write_validation_report(OUTD / f"{code}_validation.json", report)
        assert report["valid"], report
        # cumulative manifest update
        mv = prev["municipalities"][code]
        tgt = {o["work"] for o in outcomes}
        rec_list = [e for e in mv["recovered"] if e["work"] not in tgt]
        ex_list = [e for e in mv["excluded"] if e["work"] not in tgt]
        for o in outcomes:
            (rec_list if o["status"] == "recovered" else ex_list).append(o)
            if o["status"] == "recovered":
                prog.write(json.dumps({"phase": "build", "key": o["work"], **o}) + "\n")
        prog.flush()
        mv["recovered"] = rec_list
        mv["excluded"] = ex_list
        mv["works_recovered"] = len(rec_list)
        mv["works_excluded"] = len(ex_list)
        mv["rows_after"] = table.num_rows
        mv["new_rows"] = table.num_rows - mv["rows_before"]
        mv["valid"] = True
        print(f"{code}: before(live)={len(old_rows[code])} after={table.num_rows} "
              f"recovered_total={len(rec_list)} excluded_total={len(ex_list)} OK",
              flush=True)
    prev.setdefault("ocr_recovery", {})["2026-10-13"] = {
        "works_targeted": TARGET_WORKS,
        "note": "OCR recovery pass (tesseract 300dpi eng, workspace tessroot); "
                "merged onto the 16,129-row live state; see "
                "south_africa_ocr_recovery_2026-10-13.md"}
    json.dump(prev, open(OUT / "run_manifest.json", "w"),
              indent=2, ensure_ascii=False)
    tot_rec = sum(v["works_recovered"] for v in prev["municipalities"].values())
    tot_ex = sum(v["works_excluded"] for v in prev["municipalities"].values())
    tot_after = sum(v["rows_after"] for v in prev["municipalities"].values())
    print(f"RECOVERY BUILD DONE recovered={tot_rec} excluded={tot_ex} "
          f"rows 15439 -> {tot_after}")


if __name__ == "__main__":
    main()
