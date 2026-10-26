#!/usr/bin/env python3
"""Phase 2 site discovery, stage 2: for town/parish/community councils with no site from Wikidata, guess the
conventional council domains (<name>parishcouncil.gov.uk, <name>-pc.gov.uk, <name>towncouncil.gov.uk, ...),
resolve them in DNS (no HTTP for non-resolving names), then fetch only the home page of resolving candidates through
the robots-respecting PoliteSession and accept it only if the page title/h1 names the place and a council of that
tier. Names shared by several phase-2 places are skipped (cannot tell which parish a domain belongs to).
Resumable (items 'dns:<place_id>'); updates places.site / mode='council_site_dns'; never deletes."""
import collections, json, re, socket, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.util import STATE_DIR, PoliteSession, State, StopRun, get_logger, guard, utcnow  # noqa: E402
from councils import h1_title  # noqa: E402
from places import fold  # noqa: E402

log = get_logger("ukie_dns")
PAT = ["{s}parishcouncil.gov.uk", "{s}-pc.gov.uk", "{s}pc.gov.uk", "{s}towncouncil.gov.uk", "{s}-tc.gov.uk",
       "{s}parishcouncil.org.uk", "{s}parishcouncil.co.uk", "{s}-parish-council.org.uk", "{s}pc.org.uk",
       "{s}communitycouncil.gov.uk", "{s}-cc.gov.uk", "{s}towncouncil.co.uk"]
WELSH = ["{s}communitycouncil.org.uk", "cyngorcymuned{s}.cymru"]
COUNCIL = re.compile(r"(parish|town|community|village|city)\s+council|parish meeting|cyngor", re.I)


def resolves(host):
    try:
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        return True
    except (socket.gaierror, UnicodeError, OSError):
        return False


def main():
    st = State()
    ps = PoliteSession(log, min_interval=2.0, retries=1)
    rows = st.c.execute("SELECT place_id, name, tier, site FROM places WHERE phase=2").fetchall()
    cnt = collections.Counter(fold(n) for _, n, _, _ in rows)
    n = collections.Counter()
    for pid, name, tier, site in rows:
        if site:
            continue
        key = f"dns:{pid}"
        if st.item(key):
            continue
        guard()
        f = fold(name)
        if cnt[f] > 1 or not f:
            st.mark_item(key, "dns", "skip_ambiguous_name", pid); n["ambiguous"] += 1
            continue
        slugs = list(dict.fromkeys([f.replace(" ", ""), f.replace(" ", "-")]))
        cands = [p.format(s=s) for s in slugs for p in PAT + (WELSH if tier == "community" else [])]
        hit = None
        for h in cands:
            time.sleep(0.05)
            if not resolves(h):
                continue
            try:
                r = ps.get(f"https://{h}/")
            except Exception:  # noqa: BLE001
                try:
                    r = ps.get(f"http://{h}/")
                except Exception:  # noqa: BLE001
                    continue
            if "html" not in r.headers.get("content-type", ""):
                continue
            t = r.text[:200000]
            m = re.search(r"<title[^>]*>(.*?)</title>", t, re.I | re.S)
            label = " ".join(((m.group(1) if m else "") + " " + h1_title(t, r.url)).split())
            if f in fold(label) and COUNCIL.search(label):
                hit = (r.url, label[:120])
                break
        if hit:
            st.c.execute("UPDATE places SET site=?, mode='council_site_dns' WHERE place_id=?", (hit[0], pid))
            st.c.commit()
            st.mark_item(key, "dns", "found", pid, {"url": hit[0], "label": hit[1]}); n["found"] += 1
        else:
            st.mark_item(key, "dns", "none", pid); n["none"] += 1
        if sum(n.values()) % 200 == 0:
            log.info("dns discovery: %s", dict(n))
    print(json.dumps(n))
    print("DISCOVER_DNS_DONE")


if __name__ == "__main__":
    try:
        main()
    except StopRun as e:
        log.error("STOP: %s", e)
