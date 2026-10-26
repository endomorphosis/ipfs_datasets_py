#!/usr/bin/env python3
"""Per-country tar shards for endomorphosis/world_law_scanned_pdfs (default upload mode since 2026-10-18).
Pure local code (no Hub access); tools/upload_pdfs.py drives it.

Hub layout:   shards/<CC>/<YYYY>/<MM>/<CC>_<seq:06d>.tar   (ONE country per shard, uncompressed POSIX/PAX tar)
              seq is monotonically increasing per country across batches (state/pdf_shards_state.json); YYYY/MM is
              the month the shard name was reserved. A failed push reuses the reserved names (no gaps/collisions).
Members:      <place_key>/<sha256>.pdf, ordered by (place_key, sha256); each sha256 at most once per shard.
Size:         ~768 MB target per shard (SHARD_TARGET_BYTES); a shard only exceeds it when one PDF alone does
              (never > 1 GB unless a single PDF is). A country with few PDFs in a batch gets one small shard.
Every member is stored uncompressed, so one PDF = bytes [offset, offset+size) of the shard: fetch it with an HTTP
Range request (world_law_loader.fetch_pdf).
pdf_ref:      "<repo>:<shard>.tar#member=<member>&offset=<o>&size=<n>&sha256=<h>"
Loose refs "<repo>:pdfs/....pdf" of PDFs published before sharding are unchanged and stay valid.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, quote

SHARD_ROOT = "shards"
SHARD_TARGET_BYTES = 768 * 1024 ** 2
SHARD_MAX_BYTES = 1024 ** 3
SEQ_WIDTH = 6
STATE_NAME = "pdf_shards_state.json"


def shard_path(cc: str, seq: int, ym: str) -> str:
    """ym = 'YYYY/MM'."""
    cc = str(cc).upper()
    return f"{SHARD_ROOT}/{cc}/{ym}/{cc}_{seq:0{SEQ_WIDTH}d}.tar"


def member_name(place_key: str, sha256: str) -> str:
    return f"{place_key}/{sha256}.pdf"


def group_country_shards(items: List[Dict[str, Any]], target: int = SHARD_TARGET_BYTES
                         ) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """items: {'cc', 'place_key', 'sha256', 'bytes', ...}. Returns [(cc, [items...])] - one country per shard,
    members sorted by (place_key, sha256), consecutive shards filled up to ~target bytes."""
    by: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        by.setdefault(str(it["cc"]).upper(), []).append(it)
    out: List[Tuple[str, List[Dict[str, Any]]]] = []
    for cc in sorted(by):
        cur: List[Dict[str, Any]] = []
        b = 0
        for it in sorted(by[cc], key=lambda i: (i["place_key"], i["sha256"])):
            if cur and b + int(it["bytes"]) > target:
                out.append((cc, cur))
                cur, b = [], 0
            cur.append(it)
            b += int(it["bytes"])
        if cur:
            out.append((cc, cur))
    return out


# -- per-country sequence + per-batch reservations (one atomic JSON file) ------------------------------
def load_state(state_dir: Path) -> Dict[str, Any]:
    p = Path(state_dir) / STATE_NAME
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        d = {}
    d.setdefault("seq", {})
    d.setdefault("batches", {})
    return d


def save_state(state_dir: Path, d: Dict[str, Any]) -> None:
    p = Path(state_dir) / STATE_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True))
    with open(tmp, "rb+") as f:
        os.fsync(f.fileno())
    tmp.replace(p)


def reserve(state_dir: Path, batch: str, items: List[Dict[str, Any]], ym: str,
            target: int = SHARD_TARGET_BYTES) -> List[Dict[str, Any]]:
    """Shard plan for a batch, reusing earlier reservations of the same batch (retries keep their names).
    items not in any reserved shard get NEW shards with the next per-country seq numbers. Seq counter and
    reservation are written in ONE atomic file write, so a crash can neither leave a gap nor reuse a number.
    Returns [{'shard_path','cc','members':[{'member','sha256','place_key'}], ...recorded build info}]."""
    st = load_state(state_dir)
    plans: List[Dict[str, Any]] = st["batches"].get(batch, [])
    reserved = {(p["cc"], m["sha256"]) for p in plans for m in p["members"]}
    new = [it for it in items if (str(it["cc"]).upper(), it["sha256"]) not in reserved]
    if new:
        for cc, grp in group_country_shards(new, target):
            n = int(st["seq"].get(cc, 0)) + 1
            st["seq"][cc] = n
            plans.append({"shard_path": shard_path(cc, n, ym), "cc": cc, "seq": n,
                          "members": [{"member": member_name(i["place_key"], i["sha256"]), "sha256": i["sha256"],
                                       "place_key": i["place_key"]} for i in grp]})
        st["batches"][batch] = plans
        save_state(state_dir, st)
    return plans


def record_build(state_dir: Path, batch: str, shard: str, info: Dict[str, Any]) -> None:
    st = load_state(state_dir)
    for p in st["batches"].get(batch, []):
        if p["shard_path"] == shard:
            p["built"] = info
    save_state(state_dir, st)


# -- tar writing / reading ---------------------------------------------------------------------------
def write_shard(dest: Path, members: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """members: {'member','sha256','local'} in final order. Deterministic bytes (mtime 0, uid/gid 0, no names).
    Returns {'sha256','bytes','index':[{'member','offset','size','sha256'}]}; every member is re-hashed from
    the written tar."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    members = list(members)
    with tarfile.open(tmp, "w", format=tarfile.PAX_FORMAT) as tf:
        for m in members:
            p = Path(m["local"])
            ti = tarfile.TarInfo(m["member"])
            ti.size = p.stat().st_size
            ti.mode, ti.mtime, ti.uid, ti.gid, ti.uname, ti.gname = 0o644, 0, 0, 0, "", ""
            with open(p, "rb") as f:
                tf.addfile(ti, f)
    with tarfile.open(tmp, "r") as tf:
        offs = {ti.name: (ti.offset_data, ti.size) for ti in tf.getmembers()}
    index = []
    h_all = hashlib.sha256()
    with open(tmp, "rb") as f:
        for m in members:
            o, n = offs[m["member"]]
            f.seek(o)
            h = hashlib.sha256(f.read(n)).hexdigest()
            if h != m["sha256"]:
                raise ValueError(f"shard verify failed for {m['member']}: {h}")
            index.append({"member": m["member"], "offset": o, "size": n, "sha256": h})
        f.seek(0)
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h_all.update(chunk)
    tmp.replace(dest)
    return {"sha256": h_all.hexdigest(), "bytes": dest.stat().st_size, "index": index}


def shard_ref(repo: str, shard: str, member: str, offset: int, size: int, sha256: str) -> str:
    return f"{repo}:{shard}#member={quote(member, safe='/_-.')}&offset={int(offset)}&size={int(size)}&sha256={sha256}"


def parse_ref(ref: str) -> Dict[str, Any]:
    """'repo:path' or 'repo:shard.tar#member=..&offset=..&size=..&sha256=..' -> dict(repo, path[, member, offset,
    size, sha256])."""
    repo, sep, rest = str(ref).partition(":")
    if not sep or not rest:
        raise ValueError(f"not a pdf_ref: {ref!r}")
    path, _, frag = rest.partition("#")
    out: Dict[str, Any] = {"repo": repo, "path": path}
    if frag:
        q = dict(parse_qsl(frag))
        out.update(member=q.get("member"), offset=int(q["offset"]), size=int(q["size"]), sha256=q.get("sha256"))
    return out


def read_member(fileobj: io.BufferedIOBase, offset: int, size: int, sha256: Optional[str] = None) -> bytes:
    """Local equivalent of the HTTP Range read 'bytes=offset-(offset+size-1)'."""
    fileobj.seek(offset)
    data = fileobj.read(size)
    if sha256 and hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("sha256 mismatch")
    return data
