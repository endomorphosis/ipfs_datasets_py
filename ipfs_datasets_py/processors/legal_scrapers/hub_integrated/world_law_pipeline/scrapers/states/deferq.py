"""States lane: persistent deferred queue for the shared archive module's throttle deferrals (2026-10-18).

The ArchiveFetcher no longer retries 429/5xx: it raises archive.ArchiveDeferred (subclass of ArchiveTransient) with
e.not_before and puts a box-wide cool-down on the host. Our runners therefore:
  * catch ArchiveDeferred / ArchiveTransient (fetch_best/fetch_newest raise it for timeouts, breaker, throttle; None is
    a true miss), requeue the item for >= not_before, and move on to other items;
  * doc.incomplete=True (another source failed): stage only if the text is full/valid and tag
    extra_metadata.archive_incomplete=true, otherwise requeue; listings with a retryable .truncated gap are requeued;
  * persist the queue next to the checkpoint (<checkpoint dir>/<name>.deferred.tsv) so it survives restarts;
  * when only deferred items are left, sleep until the earliest not_before (no sleep-and-retry on one URL).
Queue file: append-only TSV  key \t not_before(epoch) \t count \t reason   ("-1" not_before = cleared); last line wins.
"""
from __future__ import annotations
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
from archive.core import ArchiveTransient, ArchiveDeferred  # noqa: E402,F401
from archive import ratelimit, deferral  # noqa: E402

FAMILY_HOST = {"wayback": "web.archive.org", "cc_index": "index.commoncrawl.org", "cc_data": "data.commoncrawl.org"}
DEFAULT_WAIT = float(os.environ.get("STATES_DEFER_DEFAULT_S", "60"))   # transient w/o not_before (timeout, slot busy)
MAX_DEFERS = int(os.environ.get("STATES_MAX_DEFERS", "60"))            # per item per run; stays queued for next run


class ItemDeferred(ArchiveTransient):
    def __init__(self, msg, not_before):
        super().__init__(msg)
        self.not_before = float(not_before)


def breaker_not_before(now=None):
    now = now or time.time()
    try:
        b = ratelimit.breaker_status()
        if b.get("state") == "open":
            return now + max(30.0, float(b.get("next_probe_in") or 0))
    except Exception:
        pass
    return 0.0


def not_before_for(exc=None, families=None, now=None):
    """Earliest time worth retrying: the exception's own not_before, else the cool-downs of the hosts involved,
    the Wayback breaker's next probe, else now + DEFAULT_WAIT."""
    now = now or time.time()
    nb = float(getattr(exc, "not_before", 0) or 0)
    if nb > now:
        return nb
    fams = families or list(FAMILY_HOST)
    cands = [now + deferral.host_cooldown(FAMILY_HOST[f]) for f in fams if f in FAMILY_HOST]
    if "wayback" in fams or "breaker" in str(exc or ""):
        cands.append(breaker_not_before(now))
    best = max([c for c in cands if c > now] or [0.0])
    return best if best > now else now + DEFAULT_WAIT


def fetch_best_or_defer(fx, caps, **kw):
    """fx.fetch_best() (archive round 3, 12:25 PT): None is a TRUE miss (every source answered, nothing usable);
    timeouts / breaker open / throttle with nothing usable raise ArchiveDeferred (propagated -> caller requeues).
    A returned doc with doc.incomplete=True (another source failed) is flagged on the fetcher for the current item
    (fx._states_incomplete -> list of deferrals) so the runner can tag or requeue it."""
    doc = fx.fetch_best(caps, **kw)
    note_incomplete(fx, doc)
    return doc


def fetch_newest_or_defer(fx, url, **kw):
    doc = fx.fetch_newest(url, **kw)
    note_incomplete(fx, doc)
    return doc


def note_incomplete(fx, doc):
    if doc is not None and getattr(doc, "incomplete", False):
        lst = getattr(fx, "_states_incomplete", None)
        if lst is None:
            lst = []
            setattr(fx, "_states_incomplete", lst)
        lst.append(getattr(doc, "deferral", None))


def reset_incomplete(fx):
    setattr(fx, "_states_incomplete", [])


def incomplete_not_before(fx):
    """[] -> 0 (complete). Otherwise the earliest not_before of the failed sources (or now + DEFAULT_WAIT)."""
    lst = getattr(fx, "_states_incomplete", None) or []
    if not lst:
        return 0.0
    nbs = [float(getattr(d, "not_before", 0) or 0) for d in lst if d is not None]
    nbs = [n for n in nbs if n > time.time()]
    return min(nbs) if nbs else time.time() + DEFAULT_WAIT


def listing_state(caps):
    """('ok', 0) complete; ('final', 0) only permanent gaps (re-listing won't help); ('retry', not_before) retryable gap."""
    if not getattr(caps, "truncated", False):
        return "ok", 0.0
    d = getattr(caps, "deferral", None)
    if d is None:
        return "final", 0.0
    return "retry", max(float(getattr(d, "not_before", 0) or 0), time.time() + 60)


class DeferQueue:
    def __init__(self, path, guard=None):
        self.path = str(path)
        self.guard = guard            # common.check_guards (disk floor pause) before writes
        self.q = {}                   # key -> [not_before, count, reason]
        self.items = {}               # key -> item object (filled when seen / deferred in this run)
        self.run_count = {}
        if os.path.exists(self.path):
            for line in open(self.path, encoding="utf-8"):
                p = line.rstrip("\n").split("\t")
                if len(p) < 2 or not p[0]:
                    continue
                try:
                    nb = float(p[1])
                except ValueError:
                    continue
                if nb < 0:
                    self.q.pop(p[0], None)
                else:
                    self.q[p[0]] = [nb, int(p[2]) if len(p) > 2 and p[2].isdigit() else 1, p[3] if len(p) > 3 else ""]
            self._compact()

    def _write(self, line):
        if self.guard:
            self.guard()
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)

    def _compact(self):
        if self.guard:
            self.guard()
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for k, (nb, n, r) in sorted(self.q.items()):
                f.write(f"{k}\t{nb:.0f}\t{n}\t{r}\n")
        os.replace(tmp, self.path)

    def __len__(self):
        return len(self.q)

    def __contains__(self, key):
        return key in self.q

    def not_before(self, key):
        return self.q.get(key, [0])[0]

    def defer(self, key, not_before, reason="", item=None):
        nb = max(float(not_before), time.time() + 5)
        n = self.q.get(key, [0, 0, ""])[1] + 1
        self.q[key] = [nb, n, str(reason).replace("\t", " ").replace("\n", " ")[:160]]
        self.run_count[key] = self.run_count.get(key, 0) + 1
        if item is not None:
            self.items[key] = item
        self._write(f"{key}\t{nb:.0f}\t{n}\t{self.q[key][2]}\n")

    def clear(self, key):
        self.items.pop(key, None)
        if self.q.pop(key, None) is not None:
            self._write(f"{key}\t-1\t0\tdone\n")

    def held(self, key, item, now=None):
        """True if key is deferred into the future: remember the item and skip it in the first pass."""
        if key in self.q and self.q[key][0] > (now or time.time()):
            self.items[key] = item
            return True
        return False

    def drain(self, stop=lambda: False, guard=None, log=print, nap_max=600):
        """Yield remembered deferred items as they come due; sleep until the earliest not_before when none is due.
        Items deferred MAX_DEFERS times in this run are left queued (retried by the next run)."""
        while not stop():
            live = {k: v for k, v in self.q.items() if k in self.items and self.run_count.get(k, 0) < MAX_DEFERS}
            if not live:
                gave_up = [k for k in self.q if k in self.items and self.run_count.get(k, 0) >= MAX_DEFERS]
                if gave_up:
                    log(f"deferred queue: {len(gave_up)} item(s) hit {MAX_DEFERS} deferrals this run; left queued for the next run")
                return
            now = time.time()
            due = sorted((v[0], k) for k, v in live.items() if v[0] <= now)
            if not due:
                nb = min(v[0] for v in live.values())
                wait = max(1.0, nb - now)
                log(f"all {len(live)} remaining item(s) deferred; sleeping {wait:.0f}s until earliest not_before "
                    f"{time.strftime('%H:%M:%S', time.localtime(nb))}")
                end = time.time() + min(wait, nap_max)
                while time.time() < end and not stop():    # short slices so SIGTERM/STOP is honoured promptly
                    time.sleep(min(5.0, max(0.1, end - time.time())))
                if guard:
                    guard()
                continue
            for _, k in due:
                if stop():
                    return
                if k in self.q and self.q[k][0] <= time.time() and k in self.items:
                    nb0 = self.q[k][0]
                    yield self.items[k]
                    if k in self.q and self.q[k][0] == nb0:   # caller neither cleared nor re-deferred it
                        self.items.pop(k, None)
