#!/usr/bin/env python3
"""Rewrite _state/pl/ocr_queue_pl.jsonl (tmp + rename) for the 406 rows (ELI text.pdf missing for pre-2012 acts):
pdf_url -> GetActPdf.ashx issue URL (pdf_url_old keeps the ELI URL), pdf_scope=journal_issue, and the outcome of
tools/pl_issue_refetch.py: refetched by the EU lane (needs=none, dropped from OCR), real scan / garbled text layer
(needs=ocr), pending (needs=refetch_eu, do not OCR yet). The original is kept once as ocr_queue_pl.jsonl.pre_406fix."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, shutil, sqlite3, sys
from collections import Counter
from pathlib import Path
ST = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_state/pl"))
Q = ST / "ocr_queue_pl.jsonl"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pl_dzienniki as P  # noqa


def main():
    items = {json.loads(l)["eli"]: json.loads(l) for l in (ST / "issue_refetch_queue.jsonl").open(encoding="utf-8")}
    why = {}
    db = ST / "issue_refetch_done.sqlite"
    if db.exists():
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        why = dict(con.execute("select id, why from done"))
    bak = Q.with_suffix(".jsonl.pre_406fix")
    if not bak.exists():
        shutil.copy2(Q, bak)
    rows, c = [], Counter()
    for l in bak.open(encoding="utf-8"):
        r = json.loads(l)
        it = items.get(r["act_id"])
        if it:
            host = P.HOSTS[it["voivodeship"]][1]
            r["pdf_url_old"] = r.get("pdf_url_old") or r["pdf_url"]
            r["pdf_url"] = r["source_url"] = (f"https://{host}/GetActPdf.ashx?year={it['year']}&book={it['volume']}"
                                              f"&position={it['pos']}")
            r["pdf_scope"] = "journal_issue"          # whole Dziennik issue; the act is at 'Poz. <pos>'
            r["journal_issue_nr"], r["position"] = it["volume"], it["pos"]
            r["eli_text_pdf_status"] = 406
            w = why.get(r["act_id"])
            if w == "ok":
                r["needs"], r["reason_class"] = "none", "refetched_text_layer"; c["dropped_refetched"] += 1
                continue                                # done by the EU lane: drop from the OCR queue
            if w in ("scanned_issue", "scanned_act_pages", "garbled_text_layer"):
                r["needs"], r["reason_class"] = "ocr", w
            elif w in ("split_failed",):
                r["needs"], r["reason_class"] = "ocr", "text_layer_but_act_not_located_in_issue"
            elif w == "issue_pdf_404":
                r["needs"], r["reason_class"] = "unavailable", "no_pdf_available_eli_406_and_issue_404"
            else:
                r["needs"], r["reason_class"] = "refetch_eu", "pending_eu_refetch_text_layer_expected"
            c[r["reason_class"]] += 1
        else:
            c["unchanged_" + r.get("needs", "?")] += 1
        rows.append(r)
    tmp = Q.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, Q)
    s = {"rows": len(rows), **c}
    (ST / "ocr_queue_pl.406fix.summary.json").write_text(json.dumps(s, indent=1))
    print(json.dumps(s))


if __name__ == "__main__":
    main()
