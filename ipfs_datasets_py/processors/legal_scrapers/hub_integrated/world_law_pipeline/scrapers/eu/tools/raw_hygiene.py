#!/usr/bin/env python3
"""Delete eu/_raw working files ONLY for docs in batches confirmed on Hugging Face
(/workspace/world_law/state/confirmed_batches/eu.jsonl). Never touches _state, checkpoints, or raw of unconfirmed docs.

Most confirmed batch files were already pruned locally, so a batch's doc_ids are reconstructed from our own
done-order + resolver and accepted ONLY if sha256("\\n".join(sorted(ids))) equals the uploader's doc_ids_sha256
(pruned_manifest.jsonl) or the ids read from the still-present file. Anything not verified is kept.
Any doc that also appears in a present, unconfirmed staged/processed file is kept.
Usage: raw_hygiene.py [--apply]   (default: dry run, prints what would be freed)
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, collections, glob, gzip, hashlib, json, os, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
W = Path(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law"))
EU = W / "staging" / "eu"
RAW = EU / "_raw"
CONF = W / "state" / "confirmed_batches" / "eu.jsonl"
PRUNED = W / "state" / "pruned_manifest.jsonl"


def h(ids):
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def file_ids(p):
    op = gzip.open if str(p).endswith(".gz") else open
    with op(p, "rt", encoding="utf-8") as f:
        return [str(json.loads(l).get("doc_id")) for l in f if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    conf = {}
    for l in open(CONF, encoding="utf-8"):
        r = json.loads(l)
        conf[r["rel"]] = r
    dh = {}
    for l in open(PRUNED, encoding="utf-8"):
        r = json.loads(l)
        if r.get("bot") == "eu":
            dh[r["ledger_rel"]] = r["doc_ids_sha256"]
    st = collections.Counter()
    confirmed_ids = {"NL": set(), "ES": set()}
    unverified = collections.Counter()
    # 1) present files: confirmed -> ids directly; unconfirmed -> protect
    protect = set()
    for root in (EU, W / "processed" / "eu"):
        for cc in ("NL", "ES"):
            for p in glob.glob(str(root / cc / "*.jsonl")) + glob.glob(str(root / cc / "*.jsonl.gz")):
                rel = f"eu/{cc}/" + os.path.basename(p).removesuffix(".gz")
                ids = file_ids(p)
                if rel in conf:
                    confirmed_ids[cc].update(ids)
                    st["conf_present_files"] += 1
                else:
                    protect.update(ids)
                    st["unconf_present_files"] += 1
    # 2) pruned confirmed NL files: reconstruct per place from cvdr done-order + resolver, verify by doc-hash
    import cvdr as C
    pm = C.PlaceMap()
    sch = C.get_schema()
    cat = {}
    done_order = [x for x in (EU / "_state" / "done_2026-10-10.txt").read_text().split()]
    need = set(done_order)
    with open(EU / "_state" / "catalog_2026-10-10.jsonl", encoding="utf-8") as f:
        for l in f:
            m = json.loads(l)
            if m["identifier"] in need:
                cat[m["identifier"]] = (m.get("creator", ""), m.get("creator_scheme", ""))
    seq = collections.defaultdict(list)       # place_key -> doc ids in done order
    seen = set()
    for d in done_order:
        if d in seen or d not in cat:
            continue
        seen.add(d)
        pid = pm.resolve(*cat[d])["place_id"]
        if pid:
            seq[sch.place_key(pid)].append(d)
    remapped = collections.defaultdict(list)   # Frisian docs staged via cvdrremap
    rd = EU / "_state" / "remap_done.txt"
    rset = set(rd.read_text().split()) if rd.exists() else set()
    for pk, ids in seq.items():
        remapped[pk] = [d for d in ids if d in rset]
    del cat
    for rel, r in conf.items():
        if r["cc"] != "NL":
            continue
        p1 = W / "processed" / rel
        if p1.exists() or Path(str(p1) + ".gz").exists() or (EU / rel[3:]).exists():
            continue   # handled in 1)
        target = dh.get(rel)
        n = r["rows"]
        if not target:
            unverified["no_doc_hash"] += n
            continue
        cands = [remapped[r["place_key"]]] if ".cvdrremap_" in rel else [seq.get(r["place_key"], [])]
        hit = None
        for L in cands:
            if len(L) == n and h(L) == target:
                hit = L
                break
            for i in range(0, max(0, len(L) - n + 1)):
                w = L[i:i + n]
                if h(w) == target:
                    hit = w
                    break
            if hit:
                break
        if hit:
            confirmed_ids["NL"].update(hit)
            st["conf_pruned_verified_files"] += 1
        else:
            unverified["hash_not_reconstructed"] += n
            st["conf_pruned_unverified_files"] += 1
    # ES (es_boe_ac): same reconstruction: done order + region_of(catalog item) -> place_key, verified by doc-hash
    import es_boe_ac as ES
    eseq = collections.defaultdict(list)
    edone = (EU / "_state" / "es_boe_ac" / "done.txt").read_text().split()
    eneed = set(edone)
    reg = {}
    with open(EU / "_state" / "es_boe_ac" / "catalog.jsonl", encoding="utf-8") as f:
        for l in f:
            it = json.loads(l)
            if it["identificador"] in eneed:
                rg = ES.region_of(it)
                if rg:
                    reg[it["identificador"]] = sch.place_key(f"iso:ES-{rg}")
    eseen = set()
    for d in edone:
        if d in reg and d not in eseen:
            eseen.add(d)
            eseq[reg[d]].append(d)
    for rel, r in conf.items():
        if r["cc"] != "ES":
            continue
        p1 = W / "processed" / rel
        if p1.exists() or Path(str(p1) + ".gz").exists() or (EU / rel[3:]).exists():
            continue
        target, n, L, hit = dh.get(rel), r["rows"], eseq.get(r["place_key"], []), None
        if target:
            for i in range(0, max(0, len(L) - n + 1)):
                if h(L[i:i + n]) == target:
                    hit = L[i:i + n]
                    break
        if hit:
            confirmed_ids["ES"].update(hit)
            st["es_conf_pruned_verified_files"] += 1
        else:
            unverified["es_not_reconstructed"] += n
            st["es_conf_pruned_unverified_files"] += 1
    # 3) candidate raw files
    freed = 0
    nfiles = 0
    kept_protect = 0
    for cc, sub, pat in (("NL", "cvdr", "{w}/{d}.xml.gz"), ("ES", "es_boe_ac", "{d}.xml.gz")):
        for d in sorted(confirmed_ids[cc]):
            if d in protect:
                kept_protect += 1
                continue
            work = d.rsplit("_", 1)[0]
            name = pat.format(w=work, d=d.split(":")[-1])
            p = RAW / sub / name
            if p.exists():
                freed += p.stat().st_size
                nfiles += 1
                if a.apply:
                    p.unlink()
                    try:
                        p.parent.rmdir() if sub == "cvdr" else None
                    except OSError:
                        pass
    print(json.dumps({"apply": a.apply, "stats": st, "confirmed_ids": {k: len(v) for k, v in confirmed_ids.items()},
                      "unverified_rows": unverified, "kept_in_unconfirmed_files": kept_protect,
                      "raw_files": nfiles, "bytes": freed, "GB": round(freed / 1e9, 3)}, default=dict))


if __name__ == "__main__":
    main()
