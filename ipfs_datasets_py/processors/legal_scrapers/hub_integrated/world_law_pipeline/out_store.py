"""On-demand local data parquet for out/ and out_national/ (rehydrate from the Hub + verified eviction).

Why this is safe: the local data parquet (out*/world_law/data/<CC>[/<b>]/<key>*_html.parquet) is only READ by
  * build_place (merge of rows_existing when a place gets a non-full batch),
  * dedupe.build_index (cross-lane primary index of a country's national parquet),
  * prune_processed check 4 (local parquet == Hub sha before a processed/ source is deleted).
places.parquet, the README card and stats are built from the metadata JSONs only, which are never evicted.

Eviction (evict()) deletes a place's data parquet only when ALL of its files are older than min_age (2h),
each file's sha256+size equals the Hub LFS sha256+size, and the local metadata JSON is byte-identical on the Hub
(git blob id) and lists exactly those files. Before any unlink a record per file is fsync'ed to
state/evicted_out.jsonl (repo, rel, sha256, bytes). That record is the expected sha for rehydrate() and the
substitute for the local file in prune_processed check 4.

Rehydrate (rehydrate()) downloads the missing files of ONE place into a temp dir with retries, verifies every
sha256/size against the current Hub LFS sha (else the newer of eviction record / newest local manifest line), and only when all
files verified moves them into out/. Any failure raises RehydrateError: the caller skips the place and its
staged files stay in staging (a place is never built from partial data).
"""
from __future__ import annotations

import hashlib, json, os, shutil, time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import schema as S

EVICT_LOG = "evicted_out.jsonl"
MIN_AGE_S = 2 * 3600


class RehydrateError(RuntimeError):
    pass


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def git_blob_id(p: Path) -> str:
    data = Path(p).read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def load_evicted(state: Path, repo: Optional[str] = None) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Latest eviction record per (repo, rel)."""
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    p = Path(state) / EVICT_LOG
    if not p.exists():
        return out
    with p.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if repo is None or r.get("repo") == repo:
                out[(r["repo"], r["rel"])] = r
    return out


def manifest_lines(out_dir: Path, rels: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """Newest manifest line per rel (path_in_repo -> {"sha256", "bytes", "built_at", "deleted"}), newest manifest first."""
    want, found = set(rels), {}
    mdir = Path(out_dir) / S.ROOT / "manifests"
    if not want or not mdir.is_dir():
        return found
    for mp in sorted(mdir.glob("drop_*_manifest.jsonl"), reverse=True):
        with mp.open() as f:
            for line in f:
                if not any(r in line for r in want - set(found)):
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                rel = r.get("path_in_repo")
                if rel in want and rel not in found:
                    found[rel] = {"sha256": None if r.get("deleted") else r.get("sha256"),
                                  "bytes": None if r.get("deleted") else r.get("bytes"),
                                  "built_at": r.get("built_at") or mp.name[len("drop_"):len("drop_") + 16]}
        if len(found) == len(want):
            break
    return found


def manifest_expected(out_dir: Path, rels: Iterable[str]) -> Dict[str, Tuple[str, int]]:
    """Newest manifest line (path_in_repo -> sha256, bytes) for rels, scanning local manifests newest first."""
    return {k: (v["sha256"], v["bytes"]) for k, v in manifest_lines(out_dir, rels).items() if v["sha256"]}


def hub_lfs_expected(repo: str, rels: Iterable[str], api=None) -> Dict[str, Tuple[str, int]]:
    """Current Hub LFS sha256/size per rel (only LFS files; missing or non-LFS paths are left out)."""
    rels = list(rels)
    if not rels:
        return {}
    if api is None:
        from huggingface_hub import HfApi
        api = HfApi()
    info = _hub_info(api, repo, rels)
    return {r: (v["sha256"], v["size"]) for r, v in info.items() if v and v.get("sha256")}


def _ts(s: Optional[str]) -> str:
    """Comparable UTC stamp from '2026-10-17T03:45:48Z' or a run id '20261017T034529Z'."""
    return (s or "").replace("-", "").replace(":", "")[:15]


def expected_shas(state: Path, out_dir: Path, repo: str, rels: Iterable[str],
                  hub: Optional[Dict[str, Tuple[str, int]]] = None, log=None) -> Dict[str, Tuple[str, int]]:
    """Expected (sha256, bytes) per rel for a verified rehydrate. Precedence:
      1. the current Hub LFS sha (`hub`, when the caller could look it up): the file we download must be exactly
         what the Hub serves now. A stale eviction record (the place was rebuilt + recommitted after it was evicted,
         or the local re-eviction record was lost) no longer wins over it.
      2. eviction record vs newest local manifest line: the newer of the two (manifest built_at vs evicted_at);
      3. whichever of them exists.
    A disagreement between the Hub/manifest and an eviction record is logged."""
    rels = list(rels)
    ev = load_evicted(state, repo)
    man = manifest_lines(out_dir, rels)
    hub = hub or {}
    exp: Dict[str, Tuple[str, int]] = {}
    for r in rels:
        e = ev.get((repo, r))
        m = man.get(r) if man.get(r, {}).get("sha256") else None
        if r in hub:
            exp[r] = hub[r]
            if e and e["sha256"] != hub[r][0] and log:
                log(f"rehydrate {repo}:{r}: eviction record {e['sha256'][:12]} is stale; using Hub sha {hub[r][0][:12]}")
        elif e and m:
            if m["sha256"] != e["sha256"] and _ts(m.get("built_at")) > _ts(e.get("evicted_at")):
                exp[r] = (m["sha256"], m["bytes"])
                if log:
                    log(f"rehydrate {repo}:{r}: eviction record {e['sha256'][:12]} older than manifest; "
                        f"using manifest sha {m['sha256'][:12]}")
            else:
                exp[r] = (e["sha256"], e["bytes"])
        elif e:
            exp[r] = (e["sha256"], e["bytes"])
        elif m:
            exp[r] = (m["sha256"], m["bytes"])
    return exp


def _default_download(repo: str, rel: str, local_dir: str) -> str:
    from huggingface_hub import hf_hub_download
    return hf_hub_download(repo, rel, repo_type="dataset", local_dir=local_dir)


def rehydrate(repo: str, out_dir: Path, state: Path, rels: List[str], download: Optional[Callable] = None,
              attempts: int = 3, backoff_s: float = 5.0, sleep=None, log=print,
              hub_lookup: Optional[Callable] = None) -> List[Path]:
    """Download rels (all files of one place missing locally) into out_dir, verified, all-or-nothing.
    hub_lookup(repo, rels) -> {rel: (sha256, size)} gives the current Hub LFS sha (precedence over eviction records);
    by default it queries the Hub when the real downloader is used; with an injected (mock) download and no
    hub_lookup only eviction records / manifests are used."""
    if hub_lookup is None and download is None:
        hub_lookup = hub_lfs_expected
    download = download or _default_download
    sleep = sleep or time.sleep
    out_dir = Path(out_dir)
    rels = sorted(set(rels))
    if not rels:
        return []
    hub = None
    if hub_lookup is not None:
        try:
            hub = hub_lookup(repo, rels)
        except Exception as e:  # noqa: BLE001  (Hub metadata unavailable: fall back to records / manifests)
            log(f"rehydrate {repo}: Hub sha lookup failed ({e!r}); using eviction records / manifests")
    exp = expected_shas(state, out_dir, repo, rels, hub=hub, log=log)
    missing = [r for r in rels if r not in exp]
    if missing:
        raise RehydrateError(f"no expected sha256 (eviction record / manifest) for {missing}")
    tmp = out_dir / ".rehydrate_tmp" / f"{os.getpid()}_{abs(hash(tuple(rels))) % 10**8}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        got: Dict[str, Path] = {}
        for rel in rels:
            want_sha, want_bytes = exp[rel]
            err = None
            for a in range(1, attempts + 1):
                try:
                    p = Path(download(repo, rel, str(tmp)))
                    size, sha = p.stat().st_size, sha256_file(p)
                    if sha != want_sha or (want_bytes is not None and size != want_bytes):
                        p.unlink(missing_ok=True)
                        raise RehydrateError(f"sha/size mismatch for {rel}: got {sha[:12]}/{size}, "
                                             f"want {want_sha[:12]}/{want_bytes}")
                    got[rel] = p
                    err = None
                    break
                except Exception as e:  # noqa: BLE001
                    err = e
                    log(f"rehydrate {repo}:{rel} attempt {a}/{attempts} failed: {e!r}")
                    if a < attempts:
                        sleep(backoff_s * a)
            if err is not None:
                raise RehydrateError(f"download of {rel} failed after {attempts} attempts: {err!r}")
        for rel, p in got.items():  # all verified: move into place (same filesystem)
            dst = out_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(p, dst)
            os.utime(dst, None)  # fresh mtime: not evicted again for min_age
        return [out_dir / r for r in rels]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def local_place_files(out_dir: Path, cc: str, key: str) -> List[Path]:
    return S.local_place_files(out_dir, cc, key)  # flat and bucketed layouts (S.place_dir)


def evicted_missing(out_dir: Path, state: Path, repo: str, cc: str, key: Optional[str] = None,
                    national: Optional[bool] = None) -> Dict[Tuple[str, str], List[str]]:
    """Places whose current metadata JSON lists data files that are missing locally and were evicted by us."""
    out_dir = Path(out_dir)
    ev = load_evicted(state, repo)
    res: Dict[Tuple[str, str], List[str]] = {}
    mdir = out_dir / S.ROOT / "metadata" / cc
    if not mdir.is_dir():
        return res
    if key:
        metas = [out_dir / S.metadata_path(cc, key)] + [out_dir / r for r in S.legacy_metadata_paths(cc, key)]
        metas = [next((m for m in metas if m.exists()), metas[0])]
    else:
        metas = sorted(list(mdir.glob("*.json")) + list(mdir.glob("??/*.json")), key=lambda p: p.name)
    for mp in metas:
        if not mp.exists():
            continue
        k = mp.name[:-5]
        if national is not None and S.is_national_key(k) != national:
            continue
        try:
            files = json.loads(mp.read_text()).get("html_files") or []
        except Exception:
            continue
        miss = [r for r in files if not (out_dir / r).exists() and (repo, r) in ev]
        if miss:
            res[(cc, k)] = miss
    return res


def _hub_info(api, repo: str, paths: List[str]) -> Dict[str, Any]:
    info: Dict[str, Any] = {p: None for p in paths}
    for i in range(0, len(paths), 200):
        for it in api.get_paths_info(repo, paths[i:i + 200], repo_type="dataset", expand=True):
            lfs = getattr(it, "lfs", None)
            info[it.path] = {"sha256": lfs.sha256, "size": lfs.size} if lfs is not None else \
                {"blob_id": getattr(it, "blob_id", None), "size": getattr(it, "size", None)}
    return info


def evict(out_dir: Path, repo: str, state: Path, api, min_age_s: float = MIN_AGE_S, apply: bool = False,
          now: Optional[float] = None, sha_cache=None, national: Optional[bool] = None, log=print) -> Dict[str, Any]:
    """Delete local data parquet of places verified identical on the Hub and older than min_age_s."""
    out_dir, state = Path(out_dir), Path(state)
    now = now or time.time()
    st: Dict[str, Any] = {"repo": repo, "out": str(out_dir), "apply": apply, "places_seen": 0, "places_evicted": 0,
                          "files_evicted": 0, "bytes_evicted": 0, "eligible_bytes": 0}
    skips: Dict[str, int] = {}
    data = out_dir / S.ROOT / "data"
    if not data.is_dir():
        return st
    places: Dict[Tuple[str, str], List[Path]] = {}
    for cc, p in S.iter_local_data(out_dir / S.ROOT):  # flat data/<CC>/ and bucketed data/<CC>/<b>/
        key = p.name[: -len("_html.parquet")]
        if ".s" in key and key.rsplit(".s", 1)[1].isdigit():
            key = key.rsplit(".s", 1)[0]
        places.setdefault((cc, key), []).append(p)

    def skip(why):
        skips[why] = skips.get(why, 0) + 1

    cand = []
    for (cc, key), files in places.items():
        st["places_seen"] += 1
        if national is not None and S.is_national_key(key) != national:
            skip("other_repo"); continue
        rels = sorted(str(f.relative_to(out_dir)) for f in files)
        if any(not S.is_place_data_file(r, cc, key) for r in rels):
            skip("bad_name"); continue
        if any(now - f.stat().st_mtime < min_age_s for f in files):
            skip("too_young"); continue
        meta = out_dir / S.metadata_path(cc, key)
        if not meta.exists():
            skip("no_local_metadata"); continue
        try:
            listed = sorted(json.loads(meta.read_text()).get("html_files") or [])
        except Exception:
            skip("bad_metadata"); continue
        if listed != rels:
            skip("metadata_files_differ"); continue
        cand.append((cc, key, files, rels, meta))
    allp = [r for c in cand for r in c[3]] + [S.metadata_path(c[0], c[1]) for c in cand]
    info = _hub_info(api, repo, allp) if allp else {}
    log_path = state / EVICT_LOG
    for cc, key, files, rels, meta in cand:
        mi = info.get(S.metadata_path(cc, key))
        if not mi or mi.get("blob_id") != git_blob_id(meta):
            skip("hub_metadata_differs"); continue
        ok, recs = True, []
        for f, rel in zip(files, rels):
            h = info.get(rel)
            size = f.stat().st_size
            if not h or "sha256" not in h or h["size"] != size:
                ok = False; skip("hub_missing_or_size"); break
            sha = sha_cache.get(f, sha256_file) if sha_cache is not None else sha256_file(f)
            if sha != h["sha256"]:
                ok = False; skip("hub_sha_differs"); break
            recs.append({"repo": repo, "out": str(out_dir), "rel": rel, "cc": cc, "place_key": key, "sha256": sha,
                         "bytes": size, "mtime": f.stat().st_mtime})
        if not ok:
            continue
        nbytes = sum(r["bytes"] for r in recs)
        st["eligible_bytes"] += nbytes
        if not apply:
            st["places_evicted"] += 1  # would evict
            continue
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with log_path.open("a") as lf:
            for r in recs:
                lf.write(json.dumps({**r, "evicted_at": at}) + "\n")
            lf.flush()
            os.fsync(lf.fileno())
        for f in files:
            f.unlink()
        st["places_evicted"] += 1
        st["files_evicted"] += len(files)
        st["bytes_evicted"] += nbytes
    st["skips"] = skips
    log("evict " + json.dumps(st))
    return st
