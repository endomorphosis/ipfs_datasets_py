# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
# world_law shared archive fetcher (`/workspace/world_law/pipeline/archive/`)

Fetches official law pages that are blocked or unreachable from the box out of **web archives**:

1. **Common Crawl**: CDX index at `index.commoncrawl.org/<crawl>-index`, then a byte-range GET of the
   single WARC record from `data.commoncrawl.org/<filename>` (`Range: bytes=offset-(offset+length-1)`).
2. **Wayback Machine**: CDX API `web.archive.org/cdx/search/cdx`, then the raw capture
   `web.archive.org/web/<timestamp>id_/<original url>` (no toolbar or rewriting).

Never used: archive.today / archive.ph / archive.is (hard-blocked in `core.FORBIDDEN_HOSTS`), anything behind a captcha,
proxies or VPNs. **Read-only**: nothing is uploaded anywhere.

## Layout
| path | what |
|---|---|
| `core.py` | `ArchiveFetcher`, `Capture`, `ArchivedDoc`, `ArchiveDeferred`, `CaptureList`, retries, disk cache, WARC parser |
| `deferral.py` | 429/5xx deferral: box-wide per-host cool-down (Retry-After / 60->900 s), per-lane >=5 s spacing (2026-10-18) |
| `ratelimit.py` | box-wide limiter: flock + state file per host family under `_ratelimit/` (see below) |
| `_ratelimit/` | lock, state and audit files (0777/0666), shared by every process on the box |
| `staging.py` | `provenance_fields(doc)`, `StagedWriter`: SCHEMA.md-contract writer (.tmp → fsync → validate → rename) + provenance sidecar |
| `cli.py` / `__main__.py` | command line |
| `vendor/legal_scrapers/` | **unmodified** copies of the ipfs_datasets_py tooling (`common_crawl_index_loader.py`, `common_crawl_scraper.py`, `legal_web_archive_search.py`, `parallel_web_archiver.py`, `url_archive_cache.py`, `shared_fetch_cache.py`, `LEGAL_WEB_ARCHIVE_INTEGRATION.md`), with sha256 hashes in `vendor/PROVENANCE.txt` |
| `_cache/` | local cache (see below) |

How the vendored code is used: `URLArchiveCache` is imported as is from `vendor/` (with `persist_to_ipfs=False`)
and records the newest good capture per URL under `_cache/url_archive_cache/`. The source order
(CC WARC pointer first, then Wayback) follows `parallel_web_archiver`/`common_crawl_scraper`. Their
async/HF-pointer-dataset code paths need the full package, aiohttp and the HF WARC-pointer index, so
`core.py` reimplements them synchronously against the public CC and Wayback APIs. The repo itself is never modified.

## Python API
```python
import sys; sys.path.insert(0, "/workspace/world_law/pipeline")
from archive import ArchiveFetcher, StagedWriter, provenance_fields

fx = ArchiveFetcher(cc_crawls=8)          # newest 8 CC crawls (0 = all ~110 crawls; slow)

# 1) list captures, newest first, CC + Wayback
caps = fx.list_captures("pravo.gov.ru/proxy/ips/?docbody=&nd=102010268")              # exact URL
caps = fx.list_captures("bdlaws.minlaw.gov.bd/act-*")                                   # prefix (trailing *)
caps = fx.list_captures("kenyalaw.org", "domain", newest_per_url=True)                  # domain incl. subdomains
caps = fx.wb_captures("vbpl.vn/", "prefix", collapse="timestamp:4",                     # Wayback only, 1 row/URL/year
                      filters=["mimetype:text/html", "original:.*vbpq-toanvan.*"])
caps = fx.cc_captures("dof.gob.mx/nota_detalle.php", "prefix", filters=["status:200"])  # CC only (pywb filter syntax ok too)

# 2) newest good capture of one URL (CC first, then Wayback; 2xx, not an error/captcha page)
doc = fx.fetch_newest("http://pravo.gov.ru/proxy/ips/?docbody=&nd=102010268")
doc.body, doc.text(), doc.content_type, doc.provenance()

# 3) or pick from captures you already listed (avoids a per-URL CDX query in bulk jobs)
doc = fx.fetch_best(caps, max_tries=4, validator=lambda d: b"<table" in d.body)

# 4) stage it (one place per StagedWriter; batch suffix should contain 'archive')
w = StagedWriter("/workspace/world_law/staging/<lane>", "RU", "iso:RU", batch_prefix="archive", chunk=500)
rec = {"place_id": "iso:RU", "country_code": "RU", "doc_id": "ru_pravo_ips:102010268", ...,
       "text": "...", **provenance_fields(doc)}
w.add(rec)      # validates; returns an error string if the record is invalid
w.flush()       # writes <CC>/<place_key>.archive<UTC>p0001.jsonl atomically; never touches it again
```
`fetch_best(..., policy="cc_first")` (default) tries CC captures newest-first, then Wayback newest-first. If the newest
Wayback capture is more than 365 days newer than the newest CC capture, that Wayback capture is tried first.
`policy="newest"` orders strictly by timestamp. A capture that is truncated or partial is returned only when no complete one
is found among `max_tries`.

## Errors, deferrals and what a caller must do (2026-10-18)

| exception | meaning | caller |
|---|---|---|
| `ArchiveError` | permanent-ish failure (404 replay, bad WARC, forbidden host...) | treat as a miss / log |
| `ArchiveTransient(ArchiveError)` | try again later: timeouts/network errors after the retry budget, Wayback breaker open, slot busy | requeue |
| `ArchiveDeferred(ArchiveTransient)` | **429 or 5xx** (or the host is still cooling down from one): nothing retried in-process | requeue for `e.not_before` |

`ArchiveDeferred` attributes: `not_before` (epoch s; `retry_in` = seconds left), `families` (e.g. `["cc_index",
"wayback"]`), `sources` (`commoncrawl`/`wayback`), `host` / `hosts`, `status`, `retry_after`, `url`, `lane`, and for listings
`partial` (captures collected before the deferral - **incomplete**). Code that only catches `ArchiveTransient` or
`ArchiveError` keeps working (subclass).

**HTTP layer (`_get`).** On 429/5xx: one attempt, then a box-wide cool-down for that host
(`_ratelimit/host_cooldown.json`): `Retry-After` (delta-seconds or HTTP-date) if sent, else 60 s doubling per consecutive
deferral on that host, cap 900 s; a success resets it. While a host cools down, requests to it raise `ArchiveDeferred`
without being sent. Deferrals are **not** Wayback-breaker failures. Each lane keeps >= 5 s between its own Wayback request
starts (`WORLD_LAW_LANE_MIN_INTERVAL`, families in `WORLD_LAW_LANE_SPACED_FAMILIES`, default `wayback`), cross-process via
`_ratelimit/lane.<lane>.<family>.{lock,json}`. `ArchiveFetcher(defer_on_throttle=False)` / `WORLD_LAW_ARCHIVE_DEFER=0`
restores the old in-process retries (and breaker counting) for 429/5xx.

**Timeouts / network errors** still count toward the Wayback breaker and set the family's soft backoff (that is the
protection), but the same URL is retried at most `timeout_retries` times (default **1**, `WORLD_LAW_ARCHIVE_TIMEOUT_RETRIES`,
ctor `timeout_retries=`); the retry waits out the soft backoff in `slot()`. Then `ArchiveTransient`. `max_retries`
(default 6) still bounds the legacy paths (403 from `data.commoncrawl.org`, `defer_on_throttle=False`).

**`fetch_best` / `fetch_newest`.**
* found a usable doc -> returned, even if a source was deferred; `fx.last_deferral` (merged `ArchiveDeferred` or None),
  `fx.last_cc_deferred`, `fx.last_wb_deferred` say what was deferred.
* nothing usable **and** at least one CC or Wayback capture / CDX lookup was deferred -> **raises one merged
  `ArchiveDeferred`** (earliest `not_before`, union of `families`/`hosts`).
* genuine miss (nothing deferred) -> `None`, as before. Breaker-open Wayback skips are still only reported in
  `last_wb_deferred` (no raise).
* After the first deferral of a source its remaining captures are skipped without a request and don't use up `max_tries`.
* Opt-out (old `None`): `raise_deferred=False` per call, `ArchiveFetcher(raise_deferred=False)` or
  `WORLD_LAW_ARCHIVE_RAISE_DEFERRED=0`.

**Listings.** `cc_captures` stops at the first deferred crawl and `list_captures` records a deferred CC or Wayback CDX
lookup. Both return a `CaptureList` (a real `list`) with `.deferred` / `.truncated` = True and `.deferral` set
(`on_deferred="flag"`, default), or raise `ArchiveDeferred` with `.partial` (`on_deferred="raise"`, or
`ArchiveFetcher(listing_deferred="raise")` / `WORLD_LAW_ARCHIVE_LISTING_DEFERRED=raise`; `cc_captures(on_error="raise")`
always raises). Flag mode is the default because many discovery loops call `cc_captures` without a try. **Check
`.truncated` (or `fx.last_deferral` after `caps += ...`) before treating a listing as complete.** `wb_captures` raises
`ArchiveDeferred` (no partial list) as before.

```python
from archive import ArchiveFetcher, ArchiveDeferred, ArchiveTransient
try:
    doc = fx.fetch_newest(url)                  # or fx.fetch_best(caps)
except ArchiveDeferred as e:                    # throttled: come back later
    queue.requeue(item, not_before=e.not_before, why=f"{e.families} {e.hosts}")
except ArchiveTransient:                        # timeouts / breaker open
    queue.requeue(item, not_before=time.time() + 600)
else:
    if doc is None: mark_miss(item)             # genuine miss
caps = fx.cc_captures(prefix, "prefix")
if caps.truncated:                              # discovery incomplete: don't mark the prefix done
    queue.requeue(prefix, not_before=caps.deferral.not_before)
```

## CLI
```bash
cd /workspace/world_law/pipeline
PY=/workspace/world_law/pipeline/venv/bin/python
$PY -m archive captures "bdlaws.minlaw.gov.bd/act-*" --limit 20             # newest first: ts source crawl status mime url
$PY -m archive --cc-crawls 3 captures kenyalaw.org --match domain --newest-per-url --json
$PY -m archive --no-cc captures "vbpl.vn/tw/" --match prefix --wb-collapse timestamp:4
$PY -m archive fetch "http://pravo.gov.ru/proxy/ips/?docbody=&nd=102010268" --out /tmp/doc.html   # provenance JSON on stderr
$PY -m archive fetch URL --meta                                               # provenance only
$PY -m archive cache-stats
$PY -m archive evict --max-gb 8 [--include-cdx]          # default cap is 8 GB
```

## Provenance fields (every archived document)
SCHEMA.md v1.0.0 has **no archive fields and no extra-metadata column**. `provenance_fields(doc)` therefore adds
these as **extra top-level keys** on the staged record (`validate_record` ignores unknown keys) and copies the same
object to `extra_metadata.archive`. `source_policy`/`robots_basis`, when present, also go into the provenance sidecar:

| key | value |
|---|---|
| `archive_source` | `commoncrawl` or `wayback` |
| `archive_crawl_id` | CC crawl id (`CC-MAIN-2026-39`) or `wayback` |
| `archive_timestamp` | capture time, ISO 8601 UTC |
| `archive_url` | `https://data.commoncrawl.org/<warc>#offset=…&length=…` or `https://web.archive.org/web/<ts>id_/<url>` |
| `original_url` | the URL as captured (also use it as `source_url`) |
| `content_complete` | `false` if the WARC record has `WARC-Truncated`, the CC index says `truncated`, the block or body is shorter than declared, the stream broke, or the body exceeded `max_body_bytes` (25 MB) |
| `possibly_stale` | `true` if the capture is more than 2 years (730 days) older than 2026-10-10 (`core.TODAY`) |
| `source_policy` | only when set by the caller: `archived_robots_disallowed` for hosts whose robots.txt disallows live crawling (archived copies allowed by decision of 2026-10-10; never any live request to those hosts). Pass it as `provenance_fields(doc, "archived_robots_disallowed", robots_basis)`. The national lane derives it per original host from `scrapers/national/archive/robots_policy.py` |
| `robots_basis` | with `source_policy`: why the host counts as disallowed (e.g. `robots.txt unreachable (TLS) => disallow-all`) |

`run_loop.py` keeps only the 22 parquet columns, so these keys are **not** in the published parquet. To keep them,
`StagedWriter` also writes an uploader-ignored sidecar `staging/<lane>/_archive_provenance/<CC>/<same file name>`
(one `{doc_id, place_id, …provenance}` line per doc), and the staged files themselves keep the keys after they are moved to
`processed/`. If SCHEMA.md gains an `extra`/metadata column later, map `extra_metadata` into it.

## Box-wide rate limiter (`ratelimit.py`): read this before connecting another bot
Every request this module makes to an archive host goes through **one box-wide limiter**, shared by every process of
every bot on this machine that imports the module. The Python API (`ArchiveFetcher` and everything built on it), the CLI
(`python -m archive ...`) and the national lane's `requests`/`urllib` hook (`scrapers/national/rlhook/sitecustomize.py`)
all go through it. The limits are fixed in code: no environment variable or per-bot override changes them.

| family | hosts | in flight (box-wide) | min spacing (end of previous → start of next) | timeout (connect, read) |
|---|---|---|---|---|
| `wayback` | `web.archive.org` (CDX API and `id_` replays) | 1 | 2.0 s | 10 s + 20 s |
| `cc_index` | `index.commoncrawl.org` | 1 | 1.0 s | 10 s + 30 s |
| `cc_data` | `data.commoncrawl.org` (WARC byte ranges) | 1 | 0.2 s | 10 s + 30 s |

**Files** (dir `0777`, files `0666`), one set per family under `/workspace/world_law/pipeline/archive/_ratelimit/`:
```
<family>.lock        fcntl.flock(LOCK_EX), held for the whole request; this is what makes "1 in flight"
<family>.state.json  last_start, last_end, backoff_until, fails (= hard_fails + soft_fails), hard, last_fail_status,
                     last_fail_kind (hard|soft), last_probe, lane, pid, updated
<family>.queue.json  waiting tickets {id: {lane, pid, since, hb}} and served {lane: time last served}
<family>.qlock       short flock that serialises writes to <family>.queue.json (reads are lock-free; files are replaced atomically)
<family>.log         audit, one line per request: start  end  pid  outcome  status  lane  url  (epoch seconds; rotated to .log.1 at 5 MB)
```

### Backoff is per family, capped at 3 min, and timeouts are soft (v3, 2026-10-11 15:00 PT)
`req.fail(status)` sets `backoff_until` **only in that family's state file**. Every process using that family waits; the
other families are unaffected. There are two ladders, each with ±15 % jitter:

| kind | what counts | pause |
|---|---|---|
| **hard** | int 429, int 5xx, 403 from `data.commoncrawl.org`, or any `Retry-After` | 10 s × 2^(n-1): 10, 20, 40, 80, 160, then **cap 180 s** (also caps `Retry-After`) |
| **soft** | timeouts and network errors: `fail("timeout")`, `fail("neterr")`, `fail(None)` | 5 s × 1.5^(n-1): 5, 7.5, 11, 17, 25, 38, then **cap 60 s** |

* **Probes during a soft backoff.** When the slot holder finds more than 15 s of a soft-only backoff left, it doesn't just
  sleep it out under the lock. About every 30 s (jittered) it makes one tiny health request (Wayback: CDX `url=archive.org&limit=1`;
  CC index: `collinfo.json`). These probes take the slot, observe spacing and are logged as `PROBE` lines. If a probe succeeds,
  `fails`/`backoff_until` are cleared at once and the queue moves on. Hard backoffs (the server asked us to slow down) are never cut short.
* A success clears `fails`, `hard_fails`, `soft_fails` **and** `backoff_until`, so processes still running older module code
  also see the pause end.
* While backing off, the holder re-reads the state every ≤5 s, so a clear made by anyone takes effect at once.
* On load, any `backoff_until` more than 180 s ahead (for example 900 s written by an older module copy) is clamped to 180 s.

**Why (incident 2026-10-11 14:18–14:57 PT).** Wayback `id_` replays started timing out (20 s read) while CDX stayed healthy.
In the old design every timeout counted as a hard failure on a ×2 ladder capped at 900 s. Only one request ran per backoff
window, and when it also timed out the pause doubled again: 8 timeouts in 25 min took the family to a 15-min pause
(`fails=8`, `last_fail_status=null` because the hook passed `None`), with every lane (national, eu, asia_latam, web) queued
behind it. The holder slept the pause inside the lock, so nothing could recover early. Nothing was dead: all 10 waiters
had fresh heartbeats. With v3 the same burst is bounded at 60 s pauses, and a good probe ends it. `ArchiveFetcher` (since 2026-10-18) does not
call `req.fail()` for 429/5xx at all - it defers (see "Errors, deferrals"), so the **hard** ladder now only applies to raw
`slot()` users, the rlhook, 403s from `data.commoncrawl.org` and `defer_on_throttle=False`. Timeouts are retried at most
`timeout_retries` (default 1) times, other legacy failures up to `max_retries` (6; 3 for the CC index,
`WORLD_LAW_CC_INDEX_RETRIES`), then `ArchiveTransient` (a subclass of `ArchiveError`). Transient errors are never
negatively cached, so a later run retries.

**Common Crawl can't stall Wayback work.** Backoff was always stored per family, yet Common Crawl 502/504s still held up
Wayback jobs. The cause was the workers, not the shared state. Each worker is single-threaded and asks the CC index
first. While `cc_index` was backing off (up to 900 s) or its single slot was queued, the worker sat in the CC wait and
never reached its Wayback step. A run log showed "waited 300s for the box-wide cc_index slot". 90 s read timeouts made it worse.
The fix:
* Common Crawl is treated as optional. `ArchiveFetcher(cc_max_wait=30)` (env `WORLD_LAW_CC_MAX_WAIT`) and the national
  hook call `slot("cc_index"|"cc_data", max_wait=30)`. If the CC slot can't start within 30 s, because of CC backoff or the
  queue, `ratelimit.SlotBusy` is raised immediately. The fetcher then skips CC for that URL (the `cc_breaker` skips the
  remaining crawls) and goes on to Wayback. The hook raises a `ConnectionError`/`URLError` instead, so collectors fall back.
* Timeouts are shorter: Wayback 10 + 20 s, CC 10 + 30 s. The hook caps any larger timeout a caller passes. A timeout counts as a **soft** failure for
  that family's backoff (see above; the hook now passes `"timeout"`/`"neterr"` instead of `None`). A body stream additionally has a wall-clock cap (Wayback 90 s, CC 120 s), after which the doc is
  marked `content_complete=false`.
* `slot()` is re-entrant per thread, so a hooked process using `ArchiveFetcher` can't deadlock on itself.

### Lanes and fair sharing
Each request belongs to a **lane**. Set it, in order of precedence:
1. `slot(fam, lane="...")`, `ArchiveFetcher(lane="...")` or `python -m archive --lane ...`;
2. env **`ARCHIVE_LANE`**, e.g. `ARCHIVE_LANE=asia-latam python collect.py`;
3. env `BOT_NAME` or `AGENT_NAME`;
4. otherwise `user:<login>`, or `pid:<pid>` if there is no login name.

All bots run as user `box`, so **untagged processes from every bot share one lane, `user:box`**. Set `ARCHIVE_LANE` so your
bot gets its own share. Lane names in use: `national` (national-law runners and the rlhook collectors) and the test lanes `t-*`.

Fairness semantics:
* A waiting process registers a ticket `{lane, pid, since, hb}` in `<family>.queue.json`.
* When the slot frees up, it goes to the **waiting lane that was served least recently** (a lane never served before goes first). Within a lane, tickets are FIFO.
* So with N lanes waiting, each lane gets about 1/N of the requests, whatever its number of workers. A lane with 3 workers gets the same share as a lane with 1. The workers only queue behind each other.
* The limits stay the same: one request in flight and the 2 s Wayback spacing, measured from the end of the previous request.
* An idle lane loses nothing and doesn't bank credit beyond "first in line".

Crash safety:
* The kernel releases the request lock if its holder dies. The next request is then spaced from the dead request's *start*.
* Tickets are pruned at once when their pid no longer exists, and after 15 s without a heartbeat. Waiters heartbeat every 3 s. Every waiter prunes when it sees a stale ticket, so a dead or hung waiter never blocks any lane for more than about 15 s.
* A dead holder releases the flock immediately (kernel). A *live* holder can't be preempted: if it's sleeping out a backoff, it now wakes every ≤5 s and probes, so it no longer sits on the lock for up to 15 min.
* State older than 6 h is ignored, `backoff_until` more than 180 s in the future is clamped, and corrupt files are reset.
* **New lane joining (e.g. `eu`) while stale or dead tickets exist:** stale and dead tickets are dropped before the winner is chosen, and a lane never served (or served least recently) wins the next free slot. Offline test (2026-10-11 PT): two `national` workers running, a dead-pid `web` ticket and a 60 s-stale `asia` ticket injected, then `eu` joined. `eu` got the 2nd slot after joining (about 1 s), then alternated `nEnEnEnE`. The dead and stale tickets were gone, and the queue ended empty.
* Waiters log a warning after 300 s.
* A process still running an **older copy** of this module (loaded before 2026-10-10 19:15 PT) takes the lock without a ticket. One-in-flight and spacing still hold, but it isn't part of the rotation until it is restarted.

### Rules for other bots and lanes
* **Do not bypass the limiter.** Do not call `web.archive.org`, `archive.org` or `*.commoncrawl.org` with your own `requests`/`aiohttp`/`wget`/`curl` client, and do not run a second Wayback client (e.g. the repo's `archive_fallbacks.py`, `parallel_web_archiver.py`, `waybackpy`) alongside it. Route every such request through this module or the rlhook.
* Set `ARCHIVE_LANE` to your bot or lane name. Do not use another bot's lane, and do not create several lanes for one bot to get a bigger share.
* Do not delete, chmod or edit anything in `_ratelimit/`, and do not change `ratelimit.FAMILIES`/`TIMEOUTS`.
* The whole box gets about 1 Wayback request every 2+ s, split across the waiting lanes. More workers don't make you faster; 1–3 per lane is plenty.
* User-Agent: `WorldLaw-ArchiveFetcher/1.0 (...)` with a contact or project string (`WORLD_LAW_ARCHIVE_UA` may change the text).
* archive.today/ph/is are hard-blocked (`core.FORBIDDEN_HOSTS`). No captcha pages, proxies or VPNs.

### Using it from another lane
* Interpreter: `/workspace/world_law/pipeline/venv/bin/python`. It already has `requests`, `beautifulsoup4` and `lxml`.
* In your own venv, only `requests` is required, plus Python ≥ 3.9 on Linux (fcntl). `bs4` and `lxml` are needed only for HTML text extraction, and the `pdftotext` binary only for PDFs.
```python
import os, sys; sys.path.insert(0, "/workspace/world_law/pipeline")
os.environ.setdefault("ARCHIVE_LANE", "asia-latam")          # or pass lane= below
from archive import ArchiveFetcher, ArchiveTransient, ratelimit

fx = ArchiveFetcher(lane="asia-latam")        # all HTTP inside goes through the box-wide limiter
caps = fx.wb_captures("example.gov/laws/", "prefix", collapse="timestamp:4")
doc  = fx.fetch_newest("https://example.gov/laws/act-1")   # CC first (skipped if CC is backing off), then Wayback
fx = ArchiveFetcher(lane="asia-latam", use_cc=False)       # Wayback only

# Must you make a raw archive request yourself? Do it inside the same slot with the shared timeouts:
import requests
with ratelimit.slot("wayback", lane="asia-latam") as req:  # blocks until your lane's turn
    r = requests.get("https://web.archive.org/cdx/search/cdx?url=example.gov&limit=5",
                     headers={"User-Agent": "WorldLaw-<lane>/1.0 (+contact)"}, timeout=req.timeout)
    if r.status_code == 429 or r.status_code >= 500:
        req.fail(r.status_code)               # pauses the wayback family for every process and counts toward
                                              # the breaker (prefer ArchiveFetcher, which defers instead)
    else:
        req.ok(r.status_code)
# Optional source? Fail fast instead of waiting:
try:
    with ratelimit.slot("cc_index", lane="asia-latam", max_wait=30) as req: ...
except ratelimit.SlotBusy:
    pass                                      # CC busy or backing off: go to Wayback
print(ratelimit.status())                     # per family: backoff_remaining, waiting lanes, last request
```
For scripts that use plain `requests`/`urllib`, the national lane uses an import hook instead:
`PYTHONPATH=/workspace/world_law/pipeline/scrapers/national/rlhook`. It patches both libraries so archive hosts go through
the limiter, as lane `national`. Copy that file and change `LANE` for your own lane rather than reusing `national`.
`$PY -m archive cache-stats` prints the limiter state, and `tail .../_ratelimit/wayback.log` shows recent requests with their lanes.

### Verification (2026-10-10 PT)
* **Offline, with a temporary state dir:** lane A with 1 worker, lane B with 3 workers and lane C with 1 worker made 30 requests. The order was
  `B C A B C A B C A B C A B C A B C A B B B …`. B got 1/3 of the slots while all three lanes were waiting, and the rest once the others had finished. The minimum gap was 2.000 s with 0 overlaps.
* **Holder killed mid-request:** the next waiter got the slot about 1 s later. A ghost ticket from a dead pid and a corrupt state file were cleaned up.
* **Live, 19:14:50–19:24 PT:** lanes `t-asia` (3 workers), `t-latam` and `t-eu`, alongside the running `national` lane, a `user:box` lane and old-code processes. There were 128 Wayback requests with 0 overlaps and a minimum gap of 2.000 s. The ticketed lanes rotated strictly: `N L E A U N L E A U …`, with no lane served twice in a row in 58 handoffs.
* **Injected `cc_index` 503 at 19:18:09 PT** (60 s pause): Wayback kept serving a request every ~2 s through the whole CC pause, and its backoff stayed at 0.
  A CC-first `fetch_newest()` skipped CC immediately (`cc_index_skipped_busy: 1`) and returned the Wayback copy.

## Cache (`_cache/`, override with `WORLD_LAW_ARCHIVE_CACHE`)
* `cdx/`: CDX pages and listings (JSON, keyed by sha256 of the query). TTL is 14 days for Wayback and the newest CC crawl.
  Older CC crawls are immutable and kept for 10 years. This makes listings **resumable**: a restarted job re-reads finished pages from disk.
* `body/xx/<sha>.bin.gz + .json`: fetched captures (gzip body + provenance). Permanent failures (404 replay, bad
  WARC) are negatively cached as `NEG|…` entries.
* `url_archive_cache/`: the vendored `URLArchiveCache` (newest good capture per URL → archive_url + provenance).
* Size-aware LRU eviction: bodies are evicted oldest-access-first when the cache exceeds `WORLD_LAW_ARCHIVE_CACHE_MAX_BYTES`
  (default **8 GB** since 2026-10-11, was 30 GB; checked every 500 writes), or on demand with `python -m archive evict --max-gb N`.
  Eviction is LRU by mtime (reads touch the body's mtime) and removes only `body/*.bin.gz` + their `.json` meta;
  `cdx/` listings (needed for resumable discovery), `NEG|…` negative entries and `url_archive_cache/` are kept unless
  `--include-cdx`. Processes started before the change keep the old 30 GB cap in memory until restarted, so run
  `$PY -m archive evict --max-gb 8` periodically (or after big jobs) to enforce the cap.

## Resumable bulk jobs (example: national lane)
`/workspace/world_law/pipeline/scrapers/national/archive/run_archive.py TARGET` with targets in `specs.py`
(URL queries, include regex → stable key, place resolver, HF de-dup key). State lives in
`staging/national/_archive_work/<TARGET>/` (`candidates.jsonl.gz` — or a legacy plain `candidates.jsonl`, the newer one wins —, `done.tsv`, `stats.json`) and logs in
`staging/national/_logs/archive/`. Re-running the same command resumes the job. Use `--rediscover` to refresh listings and
`--max-fetch N` for small yield probes. Other lanes can copy this pattern and put their state under their own `staging/<lane>/_…` directory.

## National-lane scripts built on this fetcher (`pipeline/scrapers/national/archive/`)
* `specs.py`: one entry per blocked source (queries, include regex → stable key, place resolver, HF de-dup key, selectors, `follow_pdf`)
* `places.py`: ISO 3166-2 tables (AT Länder, KE counties, VN provinces, ID provinces, IN states, RU subjects)
* `run_archive.py TARGET`: resumable harvest (see above). Landing pages whose full-text PDF is not archived are staged with
  `content_complete=false` (`incomplete_reason=landing_page_only:pdf_not_archived`)
* `queue_archive.sh`: phase A (`--max-fetch 25` yield probes), then phase B (full runs), 4 targets at a time, `nice`d
* `report.py [--md]`: per-target captures / candidates / on-HF / staged / %complete / %stale / yield / expected total
* `run_repo_archive.sh` + `emit_repo_archive.py`: run the patched repo collectors (https Wayback) under
  `_archive_work/<CC>_repo/` and stage them with the batch prefix `archiverepo`
* `peek.py TARGET [N]`: dump archived bodies for debugging

## Disk hygiene (2026-10-11)
* Cache cap is **8 GB** (`DEFAULT_CACHE_MAX_BYTES`, env `WORLD_LAW_ARCHIVE_CACHE_MAX_BYTES`); `python -m archive evict` with no
  `--max-gb` evicts down to that default. LRU = oldest body mtime first (reads touch mtime); `cdx/`, `NEG|…` entries and
  `url_archive_cache/` stay unless `--include-cdx`, so discovery stays resumable.
* `run_archive.py` writes new candidate lists as **`candidates.jsonl.gz`** (zcat-readable) and compresses `sort` temp
  files (`--compress-program=gzip`, disable with `ARCHIVE_SORT_COMPRESS=`). It reads either `.jsonl.gz` or plain `.jsonl`.
* Staged finals (`staging/<lane>/<CC>/*.jsonl`) stay **uncompressed**: SCHEMA.md §2 says the uploader only reads `*.jsonl` /
  `*.parquet`. The same goes for `_archive_provenance/` sidecars (named after the staged file).
* `scrapers/national/gzip_idle_work.py [--dry-run] [--min-mb 10]` gzips large idle intermediates in
  `staging/national/_work/` and `_archive_work/` after close. It does one file at a time under nice/ionice, and skips:
  open files, recently modified files, active/queued CCs and targets, emitter input (`instruments/*.json`), resume state
  (`index.jsonl`, `done.tsv`, `_emitted_ids.txt`), `_hf_ids/`, and git working trees. Log: `staging/national/_logs/gzip_idle_work.log`.

## Wayback circuit breaker (ratelimit v4, 2026-10-13)

Why: from ~08:00 PT on 2026-10-13 web.archive.org failed at TLS from the box (likely an IP block) while Common
Crawl kept working; every lane kept retrying Wayback with soft backoffs and 30 s probes.

- State: `_ratelimit/wayback.breaker.json` (0666), read-modify-write under `wayback.qlock`, atomic rename.
  Fields: `state` (closed|open), `consec_fails`, `last_fail`, `opened_at`, `reason`, `opens`, `last_probe`,
  `last_probe_result`, `probes`, `probe_claim`, `closed_at`, `closed_by`, `spacing`, `healthy_since`.
- Opens after `BREAKER_THRESHOLD` = 3 consecutive Wayback failures box-wide (any lane/process): TLS/SSL errors,
  connection resets and other network errors, timeouts, and 429/5xx **reported via `Request.fail()`** (raw `slot()`
  users, rlhook, `defer_on_throttle=False`). Since 2026-10-18 `ArchiveFetcher` 429/5xx are deferrals (host cool-down)
  and do **not** count; timeouts still do. Any Wayback answer (`Request.ok()`, incl. 404) resets the count.
- While open: `slot("wayback")` raises `WaybackDown` (subclass of `SlotBusy`, so existing `except SlotBusy`
  code keeps working) immediately, also for waiters already queued. `wayback_available()` is False.
  `ArchiveFetcher`: `wb_captures()` raises `ArchiveTransient`; `fetch_best()` drops Wayback captures (Common
  Crawl only) and sets `fx.last_wb_deferred` (number of Wayback captures skipped); `fetch_newest()` likewise.
  Callers must DEFER, not fail, items when `doc is None and fx.last_wb_deferred` (breaker-open case; 429/5xx
  deferrals raise `ArchiveDeferred` instead, see above) (national `run_archive.py`:
  not written to done.tsv, so every later run retries; audit in `<work>/<TARGET>/deferred_wayback.tsv`;
  discovery of a new target exits 75 instead of producing a Wayback-less candidate list).
- Probing: at most once per `BREAKER_PROBE_EVERY` = 30 min box-wide. When due, `wayback_available()` returns
  True; the first `slot("wayback")` caller claims the probe in the breaker file (claim expires after 120 s or
  when the claimer dies), takes `wayback.lock`, sends the CDX health probe (audit tag `BREAKER_PROBE`);
  everyone else gets `WaybackDown`.
- Probe success closes the breaker at half rate: Wayback spacing 4 s (`BREAKER_SLOW_SPACING`), stepping back
  1 s per hour (`BREAKER_HEAL_SECS`) without a Wayback failure, down to 2 s. Any failure restarts the clock.
- Helpers: `breaker_status()`, `wayback_available()`, `breaker_reset()` (manual close, keeps 4 s spacing);
  `status()` / `python -m archive status` include `wayback_breaker`.
- Processes still running the v3 module do not see the breaker (they keep their own soft backoff/probes and do
  not count toward it) -> restart them from checkpoint to load v4. National rlhook: SSL errors tagged `ssl`;
  breaker-open Wayback calls surface as ConnectionError/URLError "wayback skipped: wayback breaker open".
- Tests: `venv/bin/python archive/tests/test_breaker.py` and `archive/tests/test_core_breaker.py` (temp dir,
  no network). Backups of v3: `/tmp/{core,ratelimit,run_archive,sitecustomize}.py.v3`, `/tmp/README.md.v3`.
- National rollout helpers: `scrapers/national/archive/wayback_wait.py` (blocks until closed, triggers the due
  probe) and `resume_after_wayback.sh` (waits for close + no running queue_restart.sh, then reruns the full
  phase of all national targets from checkpoint). done.tsv also accepts `<key>\trequeue` lines to re-open items
  (used for 1 RU_ips item failed by the v3 runner during the outage). Note: stats.json `done_total` counts
  this run's in-memory deferrals; on-disk done.tsv does not contain them.

## Completeness signals (2026-10-18, national review)

- **Listings.** `cc_captures` / `list_captures` return a `CaptureList` with `.truncated`, `.truncated_reason` (first cause), `.errors` (all causes) and `.deferral` (merged `ArchiveDeferred` or None). Every early stop sets `.truncated`. Reasons: `timeout`, `throttled`/`deferred`, `crawl_list_unavailable`, `crawl_failed` (with `cc_breaker` in errors when 2 consecutive crawls failed), `breaker_open`, `wb_query_deferred`, `wb_query_failed`, `wb_failed`. Transient causes (timeouts, breaker, 429/5xx) also set `.deferral`, with `not_before` = now + backoff (min 60 s; for the breaker, the next probe). Permanent causes are flagged only. `on_deferred="raise"` raises whenever `.deferral` is set. `on_error="raise"` raises the first failure (transient → `ArchiveDeferred` with `.partial`).
- **fetch_best / fetch_newest return None ONLY when every source answered with nothing usable.** A timeout, open Wayback breaker or throttle with nothing usable raises `ArchiveDeferred` (`.reason` in `timeout|breaker_open|busy|throttled|cooldown|transient`, `.reasons` = all of them). `raise_deferred=False` restores None.
- **Doc found while another source failed:** `doc.incomplete` is True, `doc.deferral` holds the failed sources, and `doc.fetch_info` holds the details. This is separate from `doc.content_complete`, which is about the body itself. These are not dataclass fields and are never cached.
- **Per-call context:** `doc.fetch_info`, `exc.fetch_info`, or `doc, info = fx.fetch_best_ex(...)` / `fx.fetch_newest_ex(...)` (`info.deferrals`, `.errors`, `.cc_deferred`, `.wb_deferred`, `.exception`, `.incomplete`). `fx.last_deferral` / `last_wb_deferred` / `last_cc_deferred` remain for compatibility. They are **unreliable with nested calls** (validators/builders that fetch on the same fetcher) and threads.

## Round 3 (2026-10-18): breaker budget, permanent vs retryable gaps, typed errors, strict *_ex

- **Timeouts skip the source for the rest of the call.** In fetch_best / fetch_newest, once a source times out (its single retry already spent), its remaining captures are skipped. No request is sent and no max_tries is used; the timed-out capture itself counts as one try. Busy, breaker-open and throttle failures skip the same way and don't count as a try. Skips are recorded in `info.skip_sources` ({source: reason}) and `info.skipped` ({source: n}), and they count in cc_/wb_deferred. fetch_newest carries the skip from its first (CC) pass into its second (CC + Wayback) pass.
- **Breaker budget.** One public call (fetch_best[_ex], fetch_newest[_ex], cc_captures, list_captures, including their nested internal calls) adds at most ONE box-wide breaker failure per family. Later failures still pause the family but aren't counted (stat `<family>_breaker_fail_suppressed`). A single item can no longer open the Wayback breaker (threshold 3). Raw `_get` outside these calls is unchanged.
- **CC listings.** After a crawl timeout the other crawls are still queried. Timeouts count once per call toward the in-call CC breaker (`cc_breaker`, 2 consecutive failed crawls). When the CC breaker stops early, the crawls it didn't query are a retryable gap: deferral reason `cc_breaker`, retry in 1 h.
- **Permanent vs retryable truncation.** `.truncated` is still True for any gap. `.retryable_truncation` means `.deferral` is set, so re-list after `.deferral.not_before`. `.complete_except_permanent` means there is no retryable gap: either the list is complete or its only gaps are permanent, so treat it as final.
  - Permanent: `ArchiveError.permanent`, i.e. a 4xx status (400/403/404/410...) or a plain ArchiveError with no status. Examples: a crawl returning 404/410, or a crawl index that's permanently missing. Their `.errors` entries say "permanent:".
  - Retryable: any ArchiveTransient (timeout or network error, busy, breaker open, non-JSON or garbled response), a 5xx/408/425/429 ArchiveError, and 429/5xx deferrals.
  - A crawl list that's unavailable because of a network error is retryable (reason crawl_list_unavailable, with a deferral). A collinfo 404 is permanent.
- **Typed exceptions.** These all subclass ArchiveTransient, so old except clauses still work, and the messages are unchanged:
  - `ArchiveTimeout` (kind "timeout"): a timeout or network error after the retry budget.
  - `ArchiveBreakerOpen` ("breaker_open").
  - `ArchiveBusy` ("busy"): no slot was free or the family is backing off.
  - `ArchiveTransient(kind="bad_response")`: non-JSON CDX or collinfo.

  Every ArchiveError has `.kind`, `.status` and `.permanent`, and `ArchiveDeferred.kind` is "deferred" or its reason. `_as_deferral` uses `.kind` and never parses messages. A plain `ArchiveTransient("...timeout...")` raised by your own code is now reason "transient", so raise `ArchiveTimeout` instead.
- **Strict `*_ex`.** `fetch_best_ex` / `fetch_newest_ex` raise TypeError on unknown kwargs. `raise_deferred` defaults to False there and ignores the fetcher default, so they always return `(doc, info)` with `info.exception` set. With `raise_deferred=True` they raise `info.exception` when doc is None (and `e.fetch_info` is the same info).

## Round 5 (2026-10-18): conservative permanence, Common Crawl 403s

- **`ArchiveError.permanent` defaults to False.** It's True only for an explicit 400/404/410 status (for example a crawl page returning 404/410, or collinfo 404) or where the raiser passes `permanent=True`. Anything else is a retryable gap with `.deferral` set: a plain ArchiveError with no status, a parse error, an unknown error, or a code bug inside `cc_crawls` / `_cc_query`, which is caught and wrapped instead of crashing the listing. The deferral reason for such a gap is `unknown_error` with a 1 h retry; 5xx and timeouts keep their family backoff. So `complete_except_permanent` is True only when every gap is a real 400/404/410.
- **No retry cap in the module.** A truly broken item stays a retryable gap and comes back every hour. Lanes should cap this with their requeue counter, for example treating it as done-with-gaps after N `unknown_error` deferrals. Capture-level failures in fetch_best (WARC parse errors, a capture without a WARC pointer) are unchanged: they're recorded in `info.errors` and negatively cached, not deferred.
- **Any 403 from *.commoncrawl.org (index or data) is treated as throttling.** It becomes an ArchiveDeferred with per-host cool-down (`defer_on_throttle`), or a hard backoff with retry when `defer_on_throttle` is off, and is never permanent. Common Crawl's status page says CloudFront 4xx errors are "mostly … explicit rate limit rules", and its FAQ says to slow down on 503 and that an IP may be blocked temporarily (wait 24 h).
- **Wayback 403 is unchanged** (permanent for that URL, `permanent=True`; replay is negatively cached). On archive.org a 403 usually means the URL is excluded or blocked by the site owner, while rate limiting is 429. That's covered by the existing deferral handling, plus the breaker for refused or reset connections. A Wayback CDX 403 is likewise a permanent `wb_failed`.
