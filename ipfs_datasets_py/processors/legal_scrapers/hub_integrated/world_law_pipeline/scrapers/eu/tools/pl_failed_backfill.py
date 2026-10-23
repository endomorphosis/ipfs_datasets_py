#!/usr/bin/env python3
"""Backfill _state/pl/failed_<XX>.jsonl rows with pdf/source URL, act id, host, place_id (if resolvable) and a reason
class, from the local ELI catalog/queue metadata only (no PDF downloads, no network). Each failed file is rewritten
atomically (original kept as failed_<XX>.jsonl.pre_backfill once); an OCR hand-off list with one row per act that is
still not done is written to _state/pl/ocr_queue_pl.jsonl (+ ocr_queue_pl.summary.json)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, re, sqlite3, sys, shutil
from collections import Counter, defaultdict
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import pl_dzienniki as P  # noqa
ST = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_state/pl"))

def rclass(e):
    e = e or ""
    if "no text" in e: return "no_text_layer"
    if "403" in e or "parked" in e: return "http_403_host_block"
    if re.search(r"HTTP 5\d\d", e): return "http_5xx"
    if "HTTPSConnectionPool" in e or "imed out" in e: return "timeout_or_connection"
    return "other"

def wjson(path, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def main():
    pm = P.PlaceMap()
    con = sqlite3.connect(f"file:{ST/'pl_done.sqlite'}?mode=ro", uri=True)
    done_db = {r[0] for r in con.execute("select eli from done")}
    tot = Counter(); ocr = {}
    for ff in sorted(ST.glob("failed_??.jsonl")):
        woj = ff.stem[-2:]; host = P.HOSTS[woj][1]
        rows = [json.loads(l) for l in ff.open(encoding="utf-8") if l.strip()]
        need = {r["eli"] for r in rows}
        meta = {}
        for src in (ST / f"catalog_{woj}.jsonl", ST / f"queue_{woj}.jsonl"):
            if src.exists():
                for l in src.open(encoding="utf-8"):
                    if '"eli"' in l:
                        m = json.loads(l)
                        if m.get("eli") in need:
                            meta.setdefault(m["eli"], {}).update({k: v for k, v in m.items() if v not in (None, "")})
        done_txt = set((ST / f"done_{woj}.txt").read_text().split()) if (ST / f"done_{woj}.txt").exists() else set()
        out = []
        for r in rows:
            e = r["eli"]; m = meta.get(e, {})
            pub, yr, pos = e.split("/")
            org = m.get("_org"); lvl = m.get("_lvl")
            if not org:
                mo = re.search(r"\b((?:Rad[ayz]|W[óo]jt|Burmistrz|Prezydent|Zarząd|Starost|Sejmik)\w*\s.+?)\s+z dnia", m.get("title", ""))
                org = mo.group(1) if mo else None
            pid = None; pm_match = None
            if org and lvl in ("gmina", "powiat"):
                x = pm.resolve_ext(woj, org, lvl, m.get("title", ""), "")
                pid, pm_match = x.get("place_id"), x.get("match")
            elif lvl in ("voivodeship", "voivode"):
                pid, pm_match = f"iso:{P.HOSTS[woj][2]}", "voivodeship_iso"
            base = f"https://{host}/api/eli/acts/{pub}/{yr}/{pos}"
            r.update(act_id=e, host=host, voivodeship=woj, publisher=pub, year=int(yr), pos=int(pos),
                     pdf_url=base + "/text.pdf", source_url=base + "/text.pdf", html_url=base + "/text.html",
                     title=m.get("title"), act_type=m.get("type"), promulgation=(m.get("promulgation") or "")[:10] or None,
                     display_address=m.get("displayAddress"), issuing_body_name=org, level=lvl,
                     place_id=pid, place_match=pm_match, reason=r.get("error"), reason_class=rclass(r.get("error")),
                     now_done=e in done_db or e in done_txt, meta_found=bool(m))
            out.append(r)
            tot["rows"] += 1; tot["with_url"] += 1; tot["with_meta"] += bool(m); tot["with_place_id"] += bool(pid)
            if not r["now_done"]:
                o = ocr.get(e)
                if o is None:
                    o = ocr[e] = {k: r[k] for k in ("act_id", "pdf_url", "source_url", "html_url", "host", "voivodeship",
                                  "title", "act_type", "promulgation", "issuing_body_name", "level", "place_id", "place_match")}
                    o.update(attempts=0, reasons=Counter(), first_at=r["at"], last_at=r["at"])
                o["attempts"] += 1; o["reasons"][r["reason_class"]] += 1
                o["first_at"] = min(o["first_at"], r["at"]); o["last_at"] = max(o["last_at"], r["at"])
        bak = ff.with_suffix(".jsonl.pre_backfill")
        if not bak.exists(): shutil.copy2(ff, bak)
        wjson(ff, out)
    rows = []
    for o in ocr.values():
        o["reason_class"] = "no_text_layer" if o["reasons"].get("no_text_layer") else o["reasons"].most_common(1)[0][0]
        o["reasons"] = dict(o["reasons"]); o["needs"] = "ocr" if o["reason_class"] == "no_text_layer" else "refetch"
        rows.append(o)
    rows.sort(key=lambda o: o["act_id"])
    wjson(ST / "ocr_queue_pl.jsonl", rows)
    s = {"failed_rows": tot["rows"], "rows_with_pdf_url": tot["with_url"], "rows_with_catalog_meta": tot["with_meta"],
         "rows_with_place_id": tot["with_place_id"], "unique_acts_not_done": len(rows),
         "by_reason": dict(Counter(o["reason_class"] for o in rows)),
         "by_voivodeship": dict(Counter(o["voivodeship"] for o in rows)),
         "with_place_id": sum(1 for o in rows if o["place_id"]),
         "by_host": dict(Counter(o["host"] for o in rows))}
    (ST / "ocr_queue_pl.summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1))
    print(json.dumps(s, ensure_ascii=False))

if __name__ == "__main__":
    main()
