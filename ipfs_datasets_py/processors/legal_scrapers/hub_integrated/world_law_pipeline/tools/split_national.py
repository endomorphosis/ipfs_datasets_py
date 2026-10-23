#!/usr/bin/env python3
"""One-off, non-destructive split of iso_* (national / adm1 / supranational) places out of
endomorphosis/world_municipal_law into endomorphosis/world_national_law (2026-10-11).

  split_national.py plan            # what would move (no lock, no writes)
  split_national.py upload          # LOCK -> create repo if missing -> hard-link iso_* into out_national/ ->
                                    #   migration manifests + places.parquet + card -> commit(s) -> verify -> UNLOCK
  split_national.py verify          # re-verify the national repo against out_national/ (sha256 + rows), no lock
  split_national.py delete          # LOCK -> verify again -> ONE commit deleting iso_* from world_municipal_law +
                                    #   regenerated municipal places.parquet/card/manifest -> unlink iso_* from out/ -> UNLOCK

Coordinates with run_loop.py through state/run_loop.lock (blocking wait, held only for the Hub edit).
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import argparse
import fcntl
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import schema as S  # noqa: E402
from card import build_card, PHASE1_COUNTRIES  # noqa: E402

BASE = Path(os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law"))
OUT, NAT, STATE = BASE / "out", BASE / "out_national", BASE / "state"
MUNI_REPO, NAT_REPO = S.REPO_ID, S.NATIONAL_REPO_ID
LOG = STATE / "split_national.jsonl"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def note(**kw):
    with LOG.open("a") as f:
        f.write(json.dumps({"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **kw}) + "\n")


@contextmanager
def run_lock(max_wait_s=3600):
    f = open(STATE / "run_loop.lock", "w")
    t0 = time.time()
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.time() - t0 > max_wait_s:
                f.close()
                raise SystemExit("run_loop lock still held after max wait; aborting")
            time.sleep(10)
    log(f"lock acquired after {time.time() - t0:.0f}s")
    t1 = time.time()
    try:
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()
        log(f"lock released (held {time.time() - t1:.0f}s)")
        note(event="lock", held_s=round(time.time() - t1, 1), waited_s=round(t1 - t0, 1))


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def iso_files(tree: Path):
    root = tree / S.ROOT
    data = sorted(p for p in (root / "data").glob("*/iso_*_html.parquet"))
    meta = sorted(p for p in (root / "metadata").glob("*/iso_*.json"))
    return root, data, meta


def rows_of(p: Path) -> int:
    import pyarrow.parquet as pq
    return pq.ParquetFile(str(p)).metadata.num_rows


def build_places_and_card(tree: Path, kind: str, hub_files=()):
    import pyarrow as pa
    import pyarrow.parquet as pq
    root = tree / S.ROOT
    recs, cs = [], defaultdict(Counter)
    for mp in sorted((root / "metadata").glob("*/*.json")):
        m = json.loads(mp.read_text())
        if (kind == "national") != S.is_national_key(m["place_key"]):
            continue
        files = m.get("html_files") or [S.html_path(m["country_code"], m["place_key"])]
        recs.append({c: m.get(c) for c in S.PLACES_COLUMNS if c not in ("html_path", "metadata_path", "n_shards", "source_repo", "source_paths", "has_local_data")}
                    | {"html_path": files[0] if len(files) == 1 else S.shard_glob(m["country_code"], m["place_key"]),
                       "metadata_path": S.metadata_path(m["country_code"], m["place_key"]), "n_shards": len(files),
                       "source_repo": S.NATIONAL_REPO_ID if kind == "national" else S.REPO_ID,
                       "source_paths": None, "has_local_data": True})
        cs[m["country_code"]].update(m.get("doc_stats") or {"docs": m.get("total_docs") or 0})
        cs[m["country_code"]]["places"] += 1
    if kind == "municipal":  # keep the US pointer rows (cached; see us_pointers.py)
        import us_pointers
        have = {r["place_id"] for r in recs}
        recs += [r for r in us_pointers.pointer_rows(BASE / "state") if r["place_id"] not in have]
    pl = root / "places.parquet"
    tmp = pl.with_name("places.parquet.tmp")
    pq.write_table(pa.Table.from_pylist(recs, schema=S.places_schema()), str(tmp), compression="zstd")
    tmp.replace(pl)
    countries = set(cs)
    if kind == "municipal":
        countries |= set(PHASE1_COUNTRIES)
    readme = tree / "README.md"
    tmp = readme.with_name("README.md.tmp")
    tmp.write_text(build_card(countries, {k: dict(v) for k, v in cs.items()}, kind=kind))
    tmp.replace(readme)
    return pl, readme, len(recs), cs


def commit(api, repo, ops, msg):
    sys.path.insert(0, str(HERE))
    from run_loop import create_commit_with_retry, MAX_OPS_PER_COMMIT
    ids = []
    chunks = [ops[i:i + MAX_OPS_PER_COMMIT] for i in range(0, len(ops), MAX_OPS_PER_COMMIT)]
    for i, ch in enumerate(chunks):
        c = create_commit_with_retry(api, repo_id=repo, repo_type="dataset", operations=ch,
                                     commit_message=f"{msg} (part {i + 1}/{len(chunks)})")
        log(f"committed {len(ch)} ops to {repo}: {c.commit_url}")
        ids.append(c.oid)
    return ids


def verify(api, expect_tree: Path):
    """Every iso_* data/metadata file in expect_tree must be on the national Hub repo with the same sha256 and,
    for parquet, the same row count (read from the Hub file's parquet footer)."""
    from huggingface_hub import HfFileSystem
    import pyarrow.parquet as pq
    root, data, meta = iso_files(expect_tree)
    hub = {}
    for e in api.list_repo_tree(NAT_REPO, repo_type="dataset", recursive=True, expand=True):
        if getattr(e, "size", None) is not None:
            lfs = getattr(e, "lfs", None)
            hub[e.path] = (lfs.sha256 if lfs else None, e.size)
    fs = HfFileSystem()
    bad, rows_local, rows_hub, checked = [], 0, 0, 0
    for p in data + meta:
        rel = str(p.relative_to(expect_tree))
        if rel not in hub:
            bad.append((rel, "missing"))
            continue
        hsha, size = hub[rel]
        lsha = sha256(p)
        if hsha is None:  # small non-LFS file: hash the downloaded bytes
            with fs.open(f"datasets/{NAT_REPO}/{rel}", "rb") as f:
                hsha = hashlib.sha256(f.read()).hexdigest()
        if hsha != lsha or size != p.stat().st_size:
            bad.append((rel, "sha256/size mismatch"))
        if p.suffix == ".parquet":
            rl = rows_of(p)
            with fs.open(f"datasets/{NAT_REPO}/{rel}", "rb") as f:
                rh = pq.ParquetFile(f).metadata.num_rows
            rows_local += rl
            rows_hub += rh
            if rl != rh:
                bad.append((rel, f"rows {rl} != {rh}"))
        checked += 1
    extra = sorted(h for h in hub if "/iso_" not in h and h.startswith(f"{S.ROOT}/data/"))
    res = {"checked_files": checked, "data_files": len(data), "metadata_files": len(meta), "rows_local": rows_local,
           "rows_hub": rows_hub, "mismatches": bad[:20], "n_mismatches": len(bad), "non_iso_data_on_hub": extra[:10],
           "hub_files": len(hub)}
    log(f"verify: {json.dumps(res)}")
    return res


def cmd_plan(_a):
    root, data, meta = iso_files(OUT)
    rows = sum(rows_of(p) for p in data)
    print(json.dumps({"data_files": len(data), "metadata_files": len(meta), "rows": rows,
                      "bytes": sum(p.stat().st_size for p in data),
                      "places": len({p.name.split('_html')[0].split('.s')[0] for p in data})}, indent=1))


def cmd_upload(a):
    from huggingface_hub import CommitOperationAdd, HfApi
    from huggingface_hub.utils import RepositoryNotFoundError
    api = HfApi()
    with run_lock():
        try:
            info = api.repo_info(NAT_REPO, repo_type="dataset")
            files = api.list_repo_files(NAT_REPO, repo_type="dataset")
            if info.private or getattr(info, "gated", False):
                if [f for f in files if f not in (".gitattributes",)]:
                    raise SystemExit(f"{NAT_REPO} exists, private/gated, with content: stop")
            log(f"{NAT_REPO} exists (private={info.private}), {len(files)} files")
        except RepositoryNotFoundError:
            url = api.create_repo(NAT_REPO, repo_type="dataset", private=False, exist_ok=False)
            log(f"created {url}")
            note(event="create_repo", repo=NAT_REPO, url=str(url))
        # hard-link iso_* files into out_national (never written through: run_loop writes tmp+replace)
        root, data, meta = iso_files(OUT)
        n_link = 0
        for p in data + meta:
            dst = NAT / p.relative_to(OUT)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                os.link(p, dst)
                n_link += 1
        log(f"linked {n_link} files into {NAT}")
        # manifests: (1) migration manifest with sha256/rows/source of every moved file, (2) the historical
        # municipal manifest lines for iso_* paths
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        muni_sha = api.repo_info(MUNI_REPO, repo_type="dataset").sha
        hist, last = [], {}
        for mf in sorted((OUT / S.ROOT / "manifests").glob("*.jsonl")):
            for line in mf.open():
                r = json.loads(line)
                if "/iso_" in r.get("path_in_repo", ""):
                    hist.append({**r, "from_manifest": f"{S.ROOT}/manifests/{mf.name}", "repo": MUNI_REPO})
                    last[r["path_in_repo"]] = r
        man_dir = NAT / S.ROOT / "manifests"
        man_dir.mkdir(parents=True, exist_ok=True)
        mig = man_dir / f"migration_{ts}_from_world_municipal_law_manifest.jsonl"
        hst = man_dir / "history_from_world_municipal_law.jsonl"
        _, ndata, nmeta = iso_files(NAT)
        with mig.open("w") as f:
            for p in ndata + nmeta:
                rel = str(p.relative_to(NAT))
                m = json.loads((NAT / S.ROOT / "metadata" / p.parent.name / (
                    p.name.split("_html")[0].split(".s")[0] + ".json")).read_text()) if p.suffix == ".parquet" else {}
                f.write(json.dumps({"path_in_repo": rel, "sha256": sha256(p), "bytes": p.stat().st_size,
                                    "rows": rows_of(p) if p.suffix == ".parquet" else None,
                                    "place_id": m.get("place_id"), "place_key": m.get("place_key"),
                                    "country_code": p.parent.name,
                                    "source_files": (last.get(rel) or {}).get("source_files"),
                                    "migrated_from": f"{MUNI_REPO}@{muni_sha}", "migrated_at": ts,
                                    "schema_version": S.SCHEMA_VERSION}, ensure_ascii=False) + "\n")
        with hst.open("w") as f:
            for r in hist:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        pl, readme, n_places, _ = build_places_and_card(NAT, "national")
        ops = [CommitOperationAdd(path_in_repo=str(p.relative_to(NAT)), path_or_fileobj=str(p)) for p in ndata + nmeta]
        ops += [CommitOperationAdd(path_in_repo=str(x.relative_to(NAT)), path_or_fileobj=str(x)) for x in (pl, mig, hst)]
        ops += [CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(readme))]
        ids = commit(api, NAT_REPO, ops, f"split from {MUNI_REPO}@{muni_sha[:12]}: {n_places} iso_* places "
                                         f"(national / adm1 / supranational)")
        note(event="upload", repo=NAT_REPO, commits=ids, places=n_places, data_files=len(ndata),
             metadata_files=len(nmeta), municipal_sha=muni_sha)
        res = verify(api, NAT)
        note(event="verify", **res)
        if res["n_mismatches"]:
            raise SystemExit("verification FAILED; not proceeding")


def cmd_verify(_a):
    from huggingface_hub import HfApi
    res = verify(HfApi(), NAT)
    note(event="verify", **res)


def cmd_delete(a):
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi
    api = HfApi()
    with run_lock():
        res = verify(api, NAT)
        note(event="verify_before_delete", **res)
        if res["n_mismatches"] or res["checked_files"] == 0:
            raise SystemExit("national repo does not verify; refusing to delete from municipal")
        hub = api.list_repo_files(MUNI_REPO, repo_type="dataset")
        dels = sorted(f for f in hub if f.startswith(f"{S.ROOT}/data/") and "/iso_" in f
                      or f.startswith(f"{S.ROOT}/metadata/") and "/iso_" in f)
        # every file to delete must exist in the verified national repo with the same content
        nat_hub = set(api.list_repo_files(NAT_REPO, repo_type="dataset"))
        missing = [d for d in dels if d not in nat_hub]
        if missing:
            raise SystemExit(f"{len(missing)} municipal iso_* files are not in {NAT_REPO}: {missing[:5]}")
        # regenerate municipal places.parquet + card (iso_* excluded) and a deletion manifest
        pl, readme, n_places, _ = build_places_and_card(OUT, "municipal")
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        man = OUT / S.ROOT / "manifests" / f"split_{ts}_manifest.jsonl"
        nat_sha = api.repo_info(NAT_REPO, repo_type="dataset").sha
        with man.open("w") as f:
            for d in dels:
                f.write(json.dumps({"path_in_repo": d, "deleted": True,
                                    "reason": f"moved to {NAT_REPO}@{nat_sha} (national/adm1/supranational split)",
                                    "built_at": ts, "repo": MUNI_REPO}) + "\n")
            f.write(json.dumps({"path_in_repo": f"{S.ROOT}/places.parquet", "sha256": sha256(pl),
                                "bytes": pl.stat().st_size, "rows": n_places, "built_at": ts, "repo": MUNI_REPO}) + "\n")
        ops = [CommitOperationDelete(path_in_repo=d) for d in dels]
        ops += [CommitOperationAdd(path_in_repo=f"{S.ROOT}/places.parquet", path_or_fileobj=str(pl)),
                CommitOperationAdd(path_in_repo=str(man.relative_to(OUT)), path_or_fileobj=str(man)),
                CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(readme))]
        if len(ops) > 500:
            raise SystemExit("too many ops for one commit; split needed")
        ids = commit(api, MUNI_REPO, ops, f"split: delete {len(dels)} iso_* files (moved to {NAT_REPO}@{nat_sha[:12]}); "
                                          f"regenerate places.parquet + card")
        note(event="delete", repo=MUNI_REPO, commits=ids, deleted=len(dels), municipal_places=n_places,
             national_sha=nat_sha)
        # local: drop iso_* from out/ (out_national keeps its own links)
        _, data, meta = iso_files(OUT)
        for p in data + meta:
            if (NAT / p.relative_to(OUT)).exists():
                p.unlink()
        log(f"removed {len(data) + len(meta)} iso_* files from {OUT}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "upload", "verify", "delete"])
    a = ap.parse_args()
    {"plan": cmd_plan, "upload": cmd_upload, "verify": cmd_verify, "delete": cmd_delete}[a.cmd](a)


if __name__ == "__main__":
    main()
