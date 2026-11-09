#!/usr/bin/env python3
"""ZA batch 5 (A): Free State Provincial Gazette FETCH step (runs inside a fleet runner slot; parse/stage are offline).

Source: Free State Provincial Government, https://www.fsonline.fs.gov.za/?page_id=6939 ("Provincial Gazette"), which
links the gazette PDFs on the province's own /wp-content/uploads. robots.txt is 404 (= allow); every request and every
redirect hop goes through robots_guard.GuardedSession (re-checked per hop, fail closed), TLS verify=True (certifi /
system CAs via rg.ca_verify_for), 1 request in flight, >= 5 s between sends. Only the listing page and the gazette PDFs
it links are requested.

Outputs: $FS_RAW/<file>.pdf (raw downloads on disk, not shipped), $FS_STAGE/fetch.jsonl (one line per gazette),
$FS_STAGE/listing.json, $FS_STAGE/FETCH_DONE.json. Resumable (already-fetched files with a matching sha are skipped).
Exit codes: 0 done | 3 hard stop (MemAvailable < 3 GiB, disk < 12,500 MiB, RSS > 1 GiB) | 4 memory pause
(MemAvailable < 4 GiB held 60 s; wrapper releases the slot and re-queues in 30 min)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import hashlib, html, json, os, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlsplit
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("LEGAL_CORPORA_ROOT", "/dev/shm/muni_africa/fs/root")
import robots_guard as rg  # noqa: E402

LISTING = "https://www.fsonline.fs.gov.za/?page_id=6939"
HOST = "www.fsonline.fs.gov.za"
STAGE = Path(os.environ.get("FS_STAGE", "/dev/shm/muni_africa/fs"))
RAW = Path(os.environ.get("FS_RAW", (str(_LEGAL_WS) + "/muni/fs_raw")))
MAX_PDF = 80 * 2**20
MIN_INTERVAL = float(os.environ.get("FS_MIN_INTERVAL", "5.0"))


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def mem_gib():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable:"):
            return int(l.split()[1]) / 2**20
    return 99.0


def disk_mib():
    st = os.statvfs("/")
    return st.f_bavail * st.f_frsize / 2**20


def rss():
    for l in open("/proc/self/status"):
        if l.startswith("VmRSS:"):
            return int(l.split()[1]) * 1024
    return 0


def gate():
    if mem_gib() < 3.0 or disk_mib() < 12500 or rss() > 2**30:
        log(f"HARD STOP mem={mem_gib():.2f}GiB disk={disk_mib():.0f}MiB rss={rss() / 2**20:.0f}MiB"); sys.exit(3)
    t0 = time.time()
    while mem_gib() < 4.0:
        if mem_gib() < 3.0:
            log("HARD STOP mem < 3 GiB"); sys.exit(3)
        if time.time() - t0 >= 60:
            log(f"MEMORY PAUSE: MemAvailable < 4 GiB for 60 s ({mem_gib():.2f} GiB); checkpointed, releasing slot"); sys.exit(4)
        time.sleep(5)


def parse_listing(body: str):
    out, seen = [], set()
    for href, txt in re.findall(r'<a[^>]+href="([^"]+?\.pdf)"[^>]*>(.*?)</a>', body, re.S | re.I):
        title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", txt))).strip()
        url = urljoin(LISTING, html.unescape(href))
        if urlsplit(url).hostname != HOST or not re.search(r"(?i)gazette\s*no", title) or url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "title": title})
    return out


def main():
    STAGE.mkdir(parents=True, exist_ok=True); RAW.mkdir(parents=True, exist_ok=True)
    rg.set_country("za")
    S = rg.GuardedSession(); S.headers["User-Agent"] = rg.ROBOTS_UA; S.min_interval = MIN_INTERVAL; S.max_redirects = 5
    lj = STAGE / "listing.json"
    if lj.exists():
        items = json.loads(lj.read_text())["items"]
    else:
        gate()
        r = S.get(LISTING, timeout=(20, 60), verify=rg.ca_verify_for(LISTING))
        r.raise_for_status()
        if rg._CHALLENGE.search(r.text[:6000]):
            log("WAF/challenge page: stop"); sys.exit(2)
        items = parse_listing(r.text)
        lj.write_text(json.dumps({"listing_url": LISTING, "fetched_at": rg._utc_iso(), "listing_sha256": hashlib.sha256(r.content).hexdigest(),
                                  "items": items}, indent=1))
    log(f"listing: {len(items)} gazette PDF links")
    fj = STAGE / "fetch.jsonl"
    done = {}
    if fj.exists():
        for l in open(fj):
            d = json.loads(l); done[d["url"]] = d
    for k, it in enumerate(items, 1):
        url = it["url"]
        d = done.get(url)
        if d and d["status"] == "fetched" and (RAW / d["file"]).exists():
            continue
        if d and d["status"] in ("robots_blocked", "http_error", "not_pdf", "too_large") and d.get("attempts", 1) >= 2:
            continue
        gate()
        fn = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(urlsplit(url).path).name)
        rec = {"url": url, "title": it["title"], "file": fn, "fetched_at": rg._utc_iso(), "attempts": (d or {}).get("attempts", 0) + 1}
        try:
            r = S.get(url, timeout=(20, 180), stream=True, verify=rg.ca_verify_for(url))
            rec["http_status"] = r.status_code; rec["final_url"] = r.url
            if r.status_code != 200:
                rec["status"] = "http_error"; r.close()
            else:
                h, n, tmp = hashlib.sha256(), 0, RAW / (fn + ".part")
                with open(tmp, "wb") as fh:
                    for ch in r.iter_content(1 << 16):
                        n += len(ch)
                        if n > MAX_PDF:
                            break
                        h.update(ch); fh.write(ch)
                r.close()
                if n > MAX_PDF:
                    tmp.unlink(); rec["status"] = "too_large"
                elif open(tmp, "rb").read(5) != b"%PDF-":
                    tmp.unlink(); rec["status"] = "not_pdf"
                else:
                    os.replace(tmp, RAW / fn)
                    rec.update(status="fetched", bytes=n, sha256=h.hexdigest(), content_type=r.headers.get("Content-Type", ""))
        except rg.RobotsBlocked as e:
            rg.log_robots_blocked(e, caller="collect_za_fs_gazette"); rec.update(status="robots_blocked", error=str(e)[:200])
        except Exception as e:      # TLS failures land here: skipped, never retried unverified
            rec.update(status="fetch_error", error=f"{type(e).__name__}: {e}"[:300])
        with open(fj, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
        done[url] = rec
        log(f"[{k}/{len(items)}] {rec['status']} {rec.get('bytes', '')} {it['title'][:70]}")
        if rec["status"] in ("http_error", "fetch_error") and rec.get("http_status") in (429, 503):
            log("server pushback (429/503): back off 120 s"); time.sleep(120)
    st = {}
    for d in done.values():
        st[d["status"]] = st.get(d["status"], 0) + 1
    (STAGE / "FETCH_DONE.json").write_text(json.dumps({"finished_at": rg._utc_iso(), "listing_items": len(items), "status_counts": st,
                                                       "bytes": sum(d.get("bytes", 0) for d in done.values())}, indent=1))
    log(f"FETCH DONE {st}")
    sys.exit(0 if st.get("fetched", 0) else 2)


if __name__ == "__main__":
    main()
