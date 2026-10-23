#!/usr/bin/env python3
"""2026-10-17: re-place already-staged PL docs that were mapped through rows of codes/proposed/PL_gmina_fill.csv that
the review (PL_gmina_fill_reviewed.csv) REJECTED (Żory -> wd:Q33732308, Rumia with Reda's TERC 2215011, rural gmina
Zielona Góra 0809102 on the city). Staged files are never modified: corrected rows go to NEW batches
  PL/<place_key>.pldzremap_<UTC>p<NNNN>.jsonl   (same doc_id, newer UTC batch -> supersedes the old row)
Rows are re-resolved with pl_dzienniki.PlaceMap.resolve_ext (reviewed fill + REJECT_FIX).
Usage: python3 tools/restage_fill_rejects.py [--dry-run]
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, json, re, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
import pl_dzienniki as P  # noqa: E402
import schema  # noqa: E402

PL = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/PL"))
OLD = re.compile(r"PL_gmina_fill(?!_reviewed)")


STAGING = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging"))
OUTD = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/world_law/data"))


def can_full(pk: str, rows: dict) -> bool:
    """`.full` only when this batch really is the complete set: nothing published for the place, no other bot staged
    it, and every staged EU file of the place holds only docs that are in this batch (else a .full would drop them)."""
    if list(OUTD.glob(f"*/{pk}_html.parquet")) + list(OUTD.glob(f"*/*/{pk}_html.parquet")) + list(OUTD.glob(f"*/{pk}.s*_html.parquet")):
        return False
    for f in STAGING.glob(f"*/*/{pk}.*"):
        if f.name.startswith((".", "_")) or not f.name.endswith((".jsonl", ".parquet")):
            continue
        if f.parent != PL or f.suffix != ".jsonl":
            return False
        with f.open(encoding="utf-8") as fh:
            if any(json.loads(ln)["doc_id"] not in rows for ln in fh if ln.strip()):
                return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    pm = P.PlaceMap()
    out, moves, src_files = defaultdict(dict), Counter(), Counter()
    for f in sorted(PL.glob("*.jsonl")):
        if f.name.startswith((".", "_")):
            continue
        with f.open(encoding="utf-8") as fh:
            for ln in fh:
                if "PL_gmina_fill" not in ln:
                    continue
                r = json.loads(ln)
                if not OLD.search(str(r.get("place_match"))):
                    continue
                res = pm.resolve_ext(r.get("voivodeship"), r.get("issuing_body_name"), r.get("level") or "gmina",
                                     r.get("title_native") or "", r.get("text") or "")
                if not res.get("place_id"):
                    moves[(r["place_id"], None, "unresolved")] += 1
                    continue
                old_pid = r["place_id"]
                r.update(place_id=res["place_id"], qid=res["qid"], place_name=res["place_name"],
                         admin_level=res.get("admin_level") or "municipality", platform_place_id=res.get("teryt"),
                         issuing_body_code=res.get("teryt"), issuing_body_qid=res["qid"],
                         place_match="remap:" + str(res["match"]),
                         restaged_from=f.name, restaged_reason="PL_gmina_fill_reviewed: rejected mapping",
                         remapped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
                for k in ("mapped_via", "former_name", "former_code", "dissolved_date", "valid_to"):
                    if res.get(k):
                        r[k] = res[k]
                if res.get("mapped_via") == "successor" and res.get("former_code"):
                    r["issuing_body_code"] = res["former_code"]
                r.pop("successor_note", None)
                out[r["place_id"]][r["doc_id"]] = r      # a doc staged twice: keep the last (files sorted by name)
                moves[(old_pid, r["place_id"], f"{res['match']}|ibc={r['issuing_body_code']}")] += 1
                src_files[f.name] += 1
    for k, v in sorted(moves.items(), key=lambda x: -x[1]):
        print(v, *k)
    print("source files:", dict(src_files))
    if a.dry_run:
        for pid, rows in sorted(out.items()):
            print(pid, len(rows), "full" if can_full(schema.place_key(pid), rows) else "normal batch")
        return
    part = 0
    for pid, rows in sorted(out.items()):
        rs = list(rows.values())
        bad = [x["doc_id"] for x in rs if schema.validate_record(x)]
        if bad:
            raise SystemExit(f"invalid rows for {pid}: {bad[:3]}")
        part += 1
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        pk = schema.place_key(pid)
        full = ".full" if can_full(pk, rows) else ""
        path = PL / f"{pk}{full}.pldzremap_{ts}p{part:04d}.jsonl"
        P.atomic_write(path, rs, pk)        # .tmp -> fsync -> schema.validate_file -> os.rename
        print("wrote", path.name, len(rs))


if __name__ == "__main__":
    main()
