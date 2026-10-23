"""URL discovery via Wayback CDX through the shared archive module (lane=states), paged with small pages so each
request finishes inside the limiter's 20 s read timeout. Writes one line per capture: '<timestamp> <original_url>'.
usage: cdx_list.py OUT PREFIX_BASE SUFFIX [SUFFIX ...]     (parts cached in data/cdx_parts/; re-runs skip finished parts)
Throttle (ArchiveDeferred/transient): the part is requeued for >= not_before (data/cdx_parts/_deferred.tsv, persisted)
and the next part is tried; when only deferred parts remain it sleeps until the earliest. Exit 75 = parts still deferred."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, time
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
os.environ.setdefault("ARCHIVE_LANE", "states")
from archive import ArchiveFetcher
from common import check_guards as _cg  # noqa: E402
from deferq import DeferQueue, ArchiveTransient, not_before_for, listing_state  # noqa: E402

PARTS = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/states/data/cdx_parts")


def main():
    out, base, sufs = sys.argv[1], sys.argv[2], sys.argv[3:] or [""]
    os.makedirs(PARTS, exist_ok=True)
    fx = ArchiveFetcher(lane="states", cc_crawls=0)
    # ArchiveDeferred / transient: requeue the part for >= not_before and move on; persisted in _deferred.tsv
    dq = DeferQueue(f"{PARTS}/_deferred.tsv", guard=_cg)
    errs = {}

    def fname(s):
        return f"{PARTS}/{(base + s).replace('/', '_').replace(':', '_')}.txt"

    def todo():
        for s in sufs:
            if os.path.exists(fname(s)):
                dq.clear(base + s) if (base + s) in dq else None
                continue
            if dq.held(base + s, s):
                continue
            yield s
        yield from dq.drain(guard=_cg, log=lambda m: print(time.strftime("%FT%T"), m, flush=True))

    for s in todo():
        fn = fname(s)
        if os.path.exists(fn):
            continue
        try:
            caps = fx.wb_captures(base + s, "prefix", collapse="urlkey", page_size=500)
        except ArchiveTransient as e:          # incl. ArchiveDeferred (429/5xx cool-down) and breaker open
            nb = not_before_for(e, ["wayback"])
            dq.defer(base + s, nb, f"{type(e).__name__}:{e}", s)
            print(time.strftime("%FT%T"), "deferred", base + s, "until", time.strftime("%T", time.localtime(nb)), repr(e)[:160], flush=True)
            continue
        except Exception as e:
            errs[s] = errs.get(s, 0) + 1
            print(time.strftime("%FT%T"), "fail", base + s, errs[s], repr(e)[:200], flush=True)
            if errs[s] < 6:
                dq.defer(base + s, time.time() + 300, f"{type(e).__name__}:{e}", s)
            continue
        st, nb = listing_state(caps)            # never mark a part complete on a retryable truncated listing
        if st == "retry":
            dq.defer(base + s, nb, f"truncated:{getattr(caps, 'truncated_reason', '')}", s)
            print(time.strftime("%FT%T"), "truncated -> requeued", base + s, flush=True)
            continue
        _cg()  # disk floor: pause (common.check_guards) before every write
        with open(fn + ".tmp", "w") as f:
            for c in caps:
                f.write(f"{c.timestamp} {c.original_url}\n")
        os.rename(fn + ".tmp", fn)
        if (base + s) in dq:
            dq.clear(base + s)
        print(time.strftime("%FT%T"), "ok", base + s, len(caps), flush=True)
    missing = [s for s in sufs if not os.path.exists(fname(s))]
    if missing:
        print(time.strftime("%FT%T"), "INCOMPLETE", len(missing), "part(s) still missing/deferred:", " ".join(missing[:20]), flush=True)
        if any((base + s) in dq for s in missing):   # still deferred (throttle): don't publish a partial list; rerun resumes
            print(time.strftime("%FT%T"), "not writing", out, "- deferred parts left in", dq.path, flush=True)
            sys.exit(75)
    lines = set()
    for fn in os.listdir(PARTS):
        if fn.startswith(base.replace("/", "_").replace(":", "_")) and fn.endswith(".txt"):
            lines.update(l for l in open(f"{PARTS}/{fn}") if l.strip())
    _cg()  # disk floor: pause (common.check_guards) before every write
    with open(out + ".tmp", "w") as f:
        f.writelines(sorted(lines))
    os.rename(out + ".tmp", out)
    print("done", len(lines), "->", out, flush=True)


if __name__ == "__main__":
    main()
