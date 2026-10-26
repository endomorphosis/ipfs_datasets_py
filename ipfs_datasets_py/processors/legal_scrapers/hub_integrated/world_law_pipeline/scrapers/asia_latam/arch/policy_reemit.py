"""Re-emit already-staged archive docs whose archived page carries robots meta noarchive/noindex,
tagged source_policy=noarchive_meta|noindex_meta (held from upload). Finished files are never touched.

Per affected place (SCHEMA.md §1.4 merge semantics: rows merge per place by doc_id, newest file wins;
'.full' = complete current set):
  * place whose ONLY docs anywhere (staging + processed, asia_latam) are our flagged archive docs
      -> <pk>.full.archive-policy<UTC>.jsonl containing all of them, tagged.
  * otherwise -> <pk>.archive-policy<UTC>.jsonl with just the flagged docs (same doc_id, tagged); being
      newer, it wins on doc_id conflict and leaves the place's other docs untouched.
Manifest: staging/asia_latam/_policy_reemit_manifest.jsonl (one line per re-emitted file).
Input: _archive_work/_meta/hits.json from meta_scan.py, or --greiki (all staged g-reiki archive docs)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys as _sys; _sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/asia_latam/common")); from jsonl_io import open_text, glob_jsonl, locate  # noqa: E402,E702
import argparse, glob, json, os, re, sys
from collections import defaultdict
from datetime import datetime, timezone
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from schema import validate_file
from robots_meta import policy_for

ST = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam")
PR = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/processed/asia_latam")
MAN = ST + "/_policy_reemit_manifest.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--greiki", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--all", action="store_true", help="with --dry: ignore the manifest (test that every source file is still readable)")
    a = ap.parse_args()
    hits = json.load(open(ST + "/_archive_work/_meta/hits.json"))
    flagged = defaultdict(dict)  # (cc, pk) -> doc_id -> (file, flags)
    for h in hits:
        if h["flags"] and h["flags"] != ["MISSING"]:
            cc, pk = h["file"].split("/")[-2], os.path.basename(h["file"]).split(".")[0]
            flagged[(cc, pk)][h["doc_id"]] = (h["file"], h["flags"])
    done = set()
    if os.path.exists(MAN):
        for l in open(MAN):
            m = json.loads(l)
            done |= {(m["cc"], m["place_key"], d) for d in m["doc_ids"]}
    batch = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for (cc, pk), docs in sorted(flagged.items()):
        if all((cc, pk, d) in done for d in docs) and not (a.all and a.dry):
            continue
        files = [f for f in glob.glob(f"{ST}/{cc}/{pk}.*") + glob.glob(f"{PR}/{cc}/{pk}.*")
                 if f.endswith((".jsonl", ".jsonl.gz", ".parquet"))]
        all_ids, recs = set(), {}
        only_ours = True
        for f in files:
            if f.endswith(".parquet") or ".archive" not in os.path.basename(f):
                only_ours = False
                continue
            for l in open_text(f):
                r = json.loads(l)
                all_ids.add(r["doc_id"])
                if r["doc_id"] in docs:
                    recs[r["doc_id"]] = r  # later files overwrite (glob order ~ name order not guaranteed)
        full = only_ours and all_ids == set(docs)
        out = []
        for d, (src, flags) in sorted(docs.items()):
            r = dict(recs[d])
            r["source_policy"] = policy_for(flags)
            em = dict(r.get("extra_metadata") or {})
            em["robots_meta"] = flags
            em["policy_reemit_of"] = os.path.basename(src)
            r["extra_metadata"] = em
            out.append(r)
        name = f"{pk}.full.archive-policy{batch}.jsonl" if full else f"{pk}.archive-policy{batch}.jsonl"
        final = f"{ST}/{cc}/{name}"
        print(cc, pk, "full" if full else "partial", len(out), flush=True)
        if a.dry:
            continue
        tmp = final + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for r in out:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush(); os.fsync(fh.fileno())
        chk = f"{ST}/{cc}/.{name}.check.jsonl"  # validate_file needs a .jsonl suffix; dot-files are ignored
        os.link(tmp, chk)
        try:
            v = validate_file(chk, expect_place_key=pk)
        finally:
            os.unlink(chk)
        if not v.get("ok") or v.get("bad_rows"):
            os.unlink(tmp)
            print("  INVALID", v.get("errors")[:3], v.get("file_errors"))
            continue
        os.rename(tmp, final)
        with open(MAN, "a", encoding="utf-8") as m:
            m.write(json.dumps({"cc": cc, "place_key": pk, "file": name, "mode": "full" if full else "newer_batch_same_doc_id",
                                "doc_ids": sorted(docs), "source_policy": sorted({r["source_policy"] for r in out}),
                                "replaces_rows_in": sorted({os.path.basename(s) for s, _ in docs.values()}),
                                "created": batch, "reason": "robots meta noarchive/noindex on archived page "
                                "(coordinator decision 2026-10-10)"}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
