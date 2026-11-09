#!/usr/bin/env python3
"""Offline unit test of the hard pre-request pacing and the hard stops in collect_ke_samburu_muni.py (no network: the wire is
faked; fake clock). Checks: robots.txt is fetched first and ONCE per run, and the full gap (robots Crawl-Delay 20 s > 5 s)
is waited after it; every redirect hop is paced; a new run waits for the last send of an earlier run (requests.jsonl
sent_at); www.samburuassembly.go.ke and samburuassembly.go.ke share one clock; an early send raises PacingError and never reaches the wire; an
absent robots.txt (404) is allowed with the 5 s floor; cf-mitigated header, HTTP 403 / 429 / 503 and challenge-platform
markup and an Imunify360 bot-check page are hard stops. Run: python3 test_ke_samburu_pacer.py"""
import io, json, os, shutil, sys, tempfile, time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="ke_samburu_pacer_"))
os.environ.update(MUNI_STAGE=str(TMP / "b_t"), LEGAL_CORPORA_ROOT=str(TMP / "b_t" / "root"),
                  KE_PACING_LOGS=str(TMP / "b*" / "requests.jsonl"), KE_PACE_S="5")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import requests                                    # noqa: E402
import requests.adapters                           # noqa: E402
from requests.structures import CaseInsensitiveDict  # noqa: E402

CLOCK = {"t": time.time()}
time.time = lambda: CLOCK["t"]
time.monotonic = lambda: CLOCK["t"]
def fake_sleep(s):
    if s > 0:
        CLOCK["t"] += s
time.sleep = fake_sleep

import collect_ke_samburu_muni as C                 # noqa: E402
import robots_guard as rg                         # noqa: E402

WIRE = []
MODE = {"robots": "User-agent: *\nCrawl-Delay: 20\n", "robots_status": 200}

def fake_transport(adapter, prep, stream=False, timeout=None, verify=True, cert=None, proxies=None):
    WIRE.append((CLOCK["t"], prep.url))
    assert verify not in (False, None), "TLS verification must stay on"
    r = requests.Response()
    r.url, r.request, r.encoding, r.connection = prep.url, prep, "utf-8", adapter
    h = {"content-type": "text/html"}
    if prep.url.endswith("/robots.txt"):
        r.status_code, body, h = MODE["robots_status"], MODE["robots"].encode(), {"content-type": "text/plain"}
    elif prep.url.endswith("/r"):
        r.status_code, body, h = 301, b"", {"location": "https://www.samburuassembly.go.ke/b"}
    elif prep.url.endswith("/cf"):
        r.status_code, body, h = 200, b"<html>ok</html>", {"content-type": "text/html", "cf-mitigated": "challenge"}
    elif prep.url.endswith("/s403"):
        r.status_code, body = 403, b"<html>forbidden</html>"
    elif prep.url.endswith("/s429"):
        r.status_code, body = 429, b"<html>slow down</html>"
    elif prep.url.endswith("/s503"):
        r.status_code, body = 503, b"<html>unavailable</html>"
    elif prep.url.endswith("/chal"):
        r.status_code, body = 200, b'<html><script src="/cdn-cgi/challenge-platform/h/b/orchestrate/jsch/v1"></script></html>'
    elif prep.url.endswith("/imu"):
        r.status_code, body = 200, b"<html><head><title>Bot verification</title></head><body><form action=\"/imunify-bot-check\"></form></body></html>"
    elif prep.url.endswith("/jam"):
        r.status_code, body = 200, b"<!DOCTYPE html><html><head><title>Just a moment...</title></head></html>"
    else:
        r.status_code, body = 200, b"<html><body>ok</body></html>"
    r.headers, r.raw = CaseInsensitiveDict(h), io.BytesIO(body)
    CLOCK["t"] += 0.3
    return r
requests.adapters.HTTPAdapter.send = fake_transport

def new_run():
    rg.reset_cache(); rg._cache.clear(); C.start_pacing()

def gaps(w):
    return [round(b[0] - a[0], 3) for a, b in zip(w, w[1:])]

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS" if cond else "FAIL"), name, info)

B = "https://www.samburuassembly.go.ke"
new_run(); WIRE.clear()
C.get(B + "/a")
check("T1 robots.txt fetched before the first request", [u for _, u in WIRE] == [B + "/robots.txt", B + "/a"], [u for _, u in WIRE])
check("T1 full gap (Crawl-Delay 20 s) after the robots fetch", gaps(WIRE)[0] >= 20.0, gaps(WIRE))
w0 = len(WIRE); C.get(B + "/r")
seg = WIRE[w0 - 1:]
check("T2 request + redirect hop each >= 20 s apart", [u for _, u in seg[1:]] == [B + "/r", B + "/b"] and min(gaps(seg)) >= 20.0, gaps(seg))
check("T3 robots.txt fetched once per run", sum(1 for _, u in WIRE if u.endswith("/robots.txt")) == 1)
last_prev = WIRE[-1][0]
new_run(); w0 = len(WIRE); C.get(B + "/c")
check("T4 next run: robots fetch >= 20 s after the previous run's last send (persisted Crawl-Delay)", WIRE[w0][0] - last_prev >= 20.0, round(WIRE[w0][0] - last_prev, 3))
check("T4 next run: page >= 20 s after this run's robots fetch", WIRE[w0 + 1][0] - WIRE[w0][0] >= 20.0)
w0 = len(WIRE); C.get("https://samburuassembly.go.ke/d")
seg = WIRE[w0 - 1:]
check("T5 samburuassembly.go.ke shares the clock with www.samburuassembly.go.ke (robots + page >= 20 s apart)",
      [u for _, u in seg[1:]] == ["https://samburuassembly.go.ke/robots.txt", "https://samburuassembly.go.ke/d"] and min(gaps(seg)) >= 20.0, gaps(seg))
time.sleep = lambda s: None
w0 = len(WIRE)
try:
    C.get(B + "/f"); raised = False
except C.PacingError as e:
    raised = True; print("     ", e)
check("T6 early send raises PacingError", raised)
check("T6 nothing reached the wire", len(WIRE) == w0)
time.sleep = fake_sleep
# absent robots.txt (404): allowed, 5 s floor
shutil.rmtree(TMP / "b_t"); (TMP / "b_t").mkdir()
MODE.update(robots="<html>not found</html>", robots_status=404)
new_run(); C.PACER.persisted_cd = 0.0; w0 = len(WIRE); C.get(B + "/g")
check("T7 absent robots.txt (404): page fetched, gap >= 5 s after the robots fetch", WIRE[-1][1] == B + "/g" and WIRE[-1][0] - WIRE[w0][0] >= 5.0,
      round(WIRE[-1][0] - WIRE[w0][0], 3))
d = rg.check(B + "/g")
check("T7 robots_guard decision for 404 = missing/allowed", d.allowed and d.robots_status == "missing", (d.reason, d.robots_status))
for path, name in (("/cf", "cf-mitigated header"), ("/s403", "HTTP 403"), ("/s429", "HTTP 429"), ("/s503", "HTTP 503"),
                   ("/chal", "challenge-platform script"), ("/jam", "'Just a moment' title"),
                   ("/imu", "Imunify360 bot-check page")):
    try:
        C.get(B + path); stopped = False
    except C.HardStop as e:
        stopped = "CLOUDFLARE" in str(e)
    check(f"T8 hard stop on {name}", stopped)
rows = [json.loads(l) for l in open(TMP / "b_t" / "requests.jsonl")]
check("T9 robots fetches are logged in requests.jsonl (kind robots_txt)", any(r.get("kind") == "robots_txt" for r in rows))
try:
    C.get("https://docs.google.com/viewer?url=x"); off = False
except AssertionError:
    off = True
check("T10 off-host URL (Google Docs preview) refused before any send", off)
check("T11 RSS self-check reads this process tree", C.rss_tree_mib() > 1)
shutil.rmtree(TMP)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
