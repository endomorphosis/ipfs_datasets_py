#!/usr/bin/env python3
"""Discover Toscana acts from 2020 onwards (missing from the bulk datasets) via archive capture LISTS only
(shared pipeline/archive module, lane=states): Common Crawl index + Wayback CDX prefix queries on
raccoltanormativa.../articolo?urndoc=urn:nir:regione.toscana:<tipo>:<year>-.  Texts are then fetched LIVE (robots allow).
Output: data/it_tos/urns_post2020.tsv (tipo, date, number). Resumable: re-running merges."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, re, sys, time
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
os.environ.setdefault("ARCHIVE_LANE", "states")
from archive.core import ArchiveFetcher  # noqa: E402
from common import check_guards as _cg  # noqa: E402
from deferq import DeferQueue, ArchiveTransient, not_before_for, listing_state  # noqa: E402

OUT = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/states/data/it_tos/urns_post2020.tsv")
RX = re.compile(r"urn:nir:regione\.toscana:(legge|regolamento\.giunta|regolamento\.consiglio):(\d{4}-\d{2}-\d{2});(\d+(?:/R)?)", re.I)
found = set()
if os.path.exists(OUT):
    found = {tuple(l.rstrip("\n").split("\t")) for l in open(OUT) if l.strip()}
fx = ArchiveFetcher(lane="states", cc_crawls=24, use_cc=True, use_wayback=True, cc_max_wait=900)
H = "raccoltanormativa.consiglio.regione.toscana.it/articolo?urndoc=urn:nir:regione.toscana:"


def add(urls):
    n = 0
    for u in urls:
        from urllib.parse import unquote
        for m in RX.finditer(unquote(u)):
            k = (m.group(1).lower(), m.group(2), m.group(3).upper().replace("/R", "/R"))
            if int(k[1][:4]) >= 2020 and k not in found:
                found.add(k); n += 1
    _cg()  # disk floor: pause (common.check_guards) before every write
    with open(OUT + ".tmp", "w") as f:
        for k in sorted(found):
            f.write("\t".join(k) + "\n")
    os.replace(OUT + ".tmp", OUT)
    return n


# Work units: one CC index query per (crawl, tipo, year) and one Wayback CDX prefix query per (tipo, year).
# ArchiveDeferred / transient -> unit requeued for >= not_before (data/it_tos/_deferred.tsv, persisted) and the next
# unit runs; when only deferred units remain, sleep until the earliest. Finished units: data/it_tos/post2020_units.done.
DONE_U = os.path.join(os.path.dirname(OUT), "post2020_units.done")
done_u = set(l.strip() for l in open(DONE_U)) if os.path.exists(DONE_U) else set()
dq = DeferQueue(os.path.join(os.path.dirname(OUT), "_deferred.tsv"), guard=_cg)
errs = {}


def finish(uid, why="ok"):
    _cg()
    with open(DONE_U, "a") as f:
        f.write(uid + ("" if why == "ok" else "\t" + why) + "\n")
    done_u.add(uid)
    if uid in dq:
        dq.clear(uid)


while True:
    try:
        crawls = fx.cc_crawls()[:24]
        break
    except ArchiveTransient as e:
        nb = not_before_for(e, ["cc_index"]); print("cc crawl list deferred until", time.strftime("%T", time.localtime(nb)), flush=True)
        time.sleep(max(5, nb - time.time()))
units = []
for tipo in ("legge", "regolamento.giunta", "regolamento.consiglio"):
    for y in range(2020, 2027):
        units += [("cc", cr, tipo, y) for cr in crawls] + [("wb", "wayback", tipo, y)]


def todo():
    for u in units:
        uid = "|".join(map(str, u))
        if uid in done_u or dq.held(uid, u):
            continue
        yield u
    yield from dq.drain(guard=_cg, log=lambda m: print(time.strftime("%T"), m, flush=True))


for u in todo():
    fam, cr, tipo, y = u
    uid = "|".join(map(str, u))
    if uid in done_u:
        continue
    pre = f"{H}{tipo}:{y}-"
    try:
        if fam == "cc":
            caps = fx.cc_captures(pre, match="prefix", crawls=[cr], on_error="raise", on_deferred="raise")
        else:
            caps = fx.wb_captures(pre, match="prefix", collapse="urlkey")
    except ArchiveTransient as e:          # incl. ArchiveDeferred
        nb = not_before_for(e, ["cc_index"] if fam == "cc" else ["wayback"])
        dq.defer(uid, nb, f"{type(e).__name__}:{e}", u)
        print(time.strftime("%T"), "deferred", uid, "until", time.strftime("%T", time.localtime(nb)), str(e)[:100], flush=True)
        continue
    except Exception as e:
        errs[uid] = errs.get(uid, 0) + 1
        print(time.strftime("%T"), "err", uid, errs[uid], str(e)[:120], flush=True)
        if errs[uid] >= 3:
            finish(uid, "failed:" + type(e).__name__)
        else:
            dq.defer(uid, time.time() + 300, f"{type(e).__name__}:{e}", u)
        continue
    st, nb = listing_state(caps)             # a retryable .truncated gap never completes a unit
    n_new = add(c.original_url for c in caps)
    if st == "retry":
        dq.defer(uid, nb, f"truncated:{getattr(caps, 'truncated_reason', '')}", u)
        print(time.strftime("%T"), "truncated -> requeued", uid, getattr(caps, "truncated_reason", ""), flush=True); continue
    print(time.strftime("%T"), fam, cr, tipo, y, len(caps), "new", n_new, "" if st == "ok" else f"(final, permanent gaps: {list(caps.errors)[:2]})", flush=True)
    finish(uid, "ok" if st == "ok" else "final_permanent_gaps")
left = [u for u in units if "|".join(map(str, u)) not in done_u]
print("DONE total post-2020 URNs:", len(found), "units left (deferred):", len(left), flush=True)
sys.exit(75 if left else 0)
