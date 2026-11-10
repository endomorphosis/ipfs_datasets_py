import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
# DE juris-portal Länder (BW/NI/HE/TH ...): probe whether old server-rendered jportal pages exist in Wayback/CC (test-first before any discovery). Log: staging/states/_logs/de_probe3_*.log
# 2026-10-18: ArchiveDeferred/transient -> probe unit requeued for >= not_before (persisted in
# staging/states/_work/de_juris_probe/deferred.tsv), next unit runs; sleeps only when every remaining unit is deferred.
# Finished units: staging/states/_work/de_juris_probe/done.tsv (re-runs skip them).
import os, sys, re, time, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
os.environ.setdefault("ARCHIVE_LANE", "states")
from archive import ArchiveFetcher  # noqa: E402
from common import STAGING, check_guards  # noqa: E402
from deferq import DeferQueue, ArchiveTransient, ItemDeferred, not_before_for, listing_state  # noqa: E402

W = STAGING / "_work" / "de_juris_probe"
W.mkdir(parents=True, exist_ok=True)
DONE = W / "done.tsv"
done = {l.split("\t")[0] for l in open(DONE)} if DONE.exists() else set()
dq = DeferQueue(W / "deferred.tsv", guard=check_guards)
fx = ArchiveFetcher(cc_crawls=3, lane="states")
errs = collections.Counter()


def txtlen(b):
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", b.decode("utf-8", "replace"))))
    return len(t), t


def finish(uid, res):
    check_guards()
    with open(DONE, "a") as f:
        f.write(f"{uid}\t{res}\n")
    done.add(uid)
    if uid in dq:
        dq.clear(uid)


def _show_biggest(caps, n=2):
    html = [c for c in caps if (c.mime or "").startswith("text/html") or not (c.original_url.lower().endswith((".pdf", ".js", ".css", ".png", ".gif", ".jpg")))]
    best = []
    for c in sorted(html, key=lambda c: -int(c.length or 0))[:n]:
        n_, t = txtlen(fx.fetch_capture(c).body)
        js = "kein JavaScript" in t
        para = len(re.findall(r"§\s*\d+", t))
        print("  ", c.timestamp, c.original_url[:150], "textlen", n_, "§-refs", para, "JS-shell" if js else "", "|", t[:300], flush=True)
        best.append((n_, para, js))
    return best


def run_unit(kind, target):
    if kind == "wbold":            # old server-rendered jportal (pre-2019) pages: Wayback prefix listing, biggest pages
        raw = fx.wb_captures(target, "prefix", collapse="urlkey", limit=3000)
        st, nb = listing_state(raw)
        if st == "retry":
            raise ItemDeferred(f"wb listing truncated ({getattr(raw, 'truncated_reason', '')})", nb)
        caps = [c for c in raw if c.status == 200]
        print(target, "wb captures", len(caps), "years", sorted(collections.Counter(c.timestamp[:4] for c in caps).items())[:20], flush=True)
        best = _show_biggest(caps, 3)
        return f"wb_caps={len(caps)};best=" + ",".join(f"{a}/{b}{'/js' if c else ''}" for a, b, c in best)
    if kind == "ccbig":
        raw = fx.cc_captures(target, "prefix", on_error="raise", on_deferred="raise")
        st, nb = listing_state(raw)
        if st == "retry":
            raise ItemDeferred(f"cc listing truncated ({raw.truncated_reason})", nb)
        caps = [c for c in raw if c.status == 200]
        print(target, "cc captures", len(caps), flush=True)
        best = _show_biggest(caps, 3)
        return f"cc_caps={len(caps)};best=" + ",".join(f"{a}/{b}{'/js' if c else ''}" for a, b, c in best)
    if kind == "cc":
        raw = fx.cc_captures(target, "prefix", crawls=["CC-MAIN-2026-34"], on_error="raise", on_deferred="raise")
        st, nb = listing_state(raw)                # check flags on the CaptureList itself, before filtering
        caps = [c for c in raw if c.status == 200]
        if st == "retry":                          # retryable gap: not a finished probe
            raise ItemDeferred(f"cc listing truncated ({raw.truncated_reason})", nb)
        print(target, len(caps), collections.Counter(int(c.length or 0) // 5000 * 5 for c in caps).most_common(5), flush=True)
        for c in sorted(caps, key=lambda c: -int(c.length or 0))[:2]:
            n, t = txtlen(fx.fetch_capture(c).body); print("  ", c.original_url[:140], n, t[:300], flush=True)
        return f"cc_caps={len(caps)}"
    raw = fx.wb_captures(target, "prefix", limit=60)
    st, nb = listing_state(raw)
    if st == "retry":
        raise ItemDeferred(f"wb listing truncated ({getattr(raw, 'truncated_reason', '')})", nb)
    caps = [c for c in raw if c.status == 200]
    print(target, len(caps), [(c.timestamp[:8], c.length) for c in caps][:12], flush=True)
    for c in sorted(caps, key=lambda c: -int(c.length or 0))[:1]:
        n, t = txtlen(fx.fetch_capture(c).body); print("  ", c.timestamp, n, t[:500], flush=True)
    return f"wb_caps={len(caps)}"


UNITS = [("cc", h) for h in ["voris.wolterskluwer-online.de/", "www.voris.niedersachsen.de/"]] + \
        [("wb", q) for q in ["www.landesrecht-bw.de/jportal/?quelle=jlink&query=LBO+BW", "www.nds-voris.de/jportal/?quelle=jlink&query=BauO+ND",
                             "www.rv.hessenrecht.hessen.de/jportal/?quelle=jlink&query=BauO+HE",
                             "landesrecht.thueringen.de/jportal/?quelle=jlink&query=BauO+TH"]] + \
        [("wbold", h + "/jportal/portal/page/") for h in [
            "www.landesrecht-bw.de", "www.rv.hessenrecht.hessen.de", "www.landesrecht-mv.de", "landesrecht.rlp.de",
            "recht.saarland.de", "www.landesrecht.sachsen-anhalt.de", "www.gesetze-rechtsprechung.sh.juris.de",
            "landesrecht.thueringen.de", "www.nds-voris.de", "gesetze.berlin.de", "www.landesrecht-hamburg.de"]] + \
        [("ccbig", h) for h in ["gesetze.berlin.de/bsbe/", "www.landesrecht-hamburg.de/bsha/",
                                "www.landesrecht.sachsen-anhalt.de/bsst/"]]


def todo():
    for u in UNITS:
        uid = f"{u[0]}|{u[1]}"
        if uid in done or dq.held(uid, u):
            continue
        yield u
    yield from dq.drain(guard=check_guards, log=lambda m: print(time.strftime("%T"), m, flush=True))


for kind, target in todo():
    uid = f"{kind}|{target}"
    if uid in done:
        continue
    try:
        finish(uid, run_unit(kind, target))
    except ArchiveTransient as e:              # incl. ArchiveDeferred: requeue, move on
        nb = not_before_for(e, ["cc_index", "cc_data"] if kind == "cc" else ["wayback"])
        dq.defer(uid, nb, f"{type(e).__name__}:{e}", (kind, target))
        print(time.strftime("%T"), "deferred", uid, "until", time.strftime("%T", time.localtime(nb)), str(e)[:120], flush=True)
    except Exception as e:
        errs[uid] += 1
        print(target, "ERR", e, flush=True)
        if errs[uid] >= 3:
            finish(uid, f"error:{type(e).__name__}")
        else:
            dq.defer(uid, time.time() + 300, f"{type(e).__name__}:{e}", (kind, target))
left = [u for u in UNITS if f"{u[0]}|{u[1]}" not in done]
print("PROBE END units left (deferred):", len(left), flush=True)
