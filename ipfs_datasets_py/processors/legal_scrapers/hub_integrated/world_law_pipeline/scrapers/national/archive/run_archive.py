#!/usr/bin/env python3
"""Archive harvest for one national-lane target (see specs.py). Resumable.

  run_archive.py TARGET [--max-fetch N] [--cc-crawls 8] [--discover-only] [--chunk 200]

Phases: (1) discovery: CC CDX + Wayback CDX listings of the spec queries (pages cached in the shared
archive cache, so a restart re-reads them from disk); (2) per candidate URL (newest first), fetch the
newest good capture (CC WARC first, Wayback id_ second), extract text, emit SCHEMA-valid docs via
archive.StagedWriter into staging/national/<CC>/<place_key>.archive<UTC>pNNNN.jsonl.
State: staging/national/_archive_work/<TARGET>/ (done.tsv, candidates.jsonl[.gz], stats.json).
Since 2026-10-11 new candidate lists are written gzip-compressed (candidates.jsonl.gz, zcat-readable);
an existing plain candidates.jsonl is still read. .gz wins when both exist.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import argparse, gzip, hashlib, json, logging, os, re, signal, subprocess, sys, tempfile, time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from archive import ArchiveFetcher, StagedWriter, provenance_fields, canonical_url, good_doc  # noqa: E402
from archive.core import ArchiveError, ArchiveDeferred, ArchiveTransient, Capture  # noqa: E402
from archive import deferral  # noqa: E402  (per-host cool-down state, 2026-10-18)
from archive import ratelimit  # noqa: E402
from specs import SPECS  # noqa: E402
from robots_policy import policy_for  # noqa: E402

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national"))
WORK = STAGE / "_archive_work"
HF_IDS = WORK / "_hf_ids"
# sort(1) temp files are compressed too (disk pressure); override with ARCHIVE_SORT_COMPRESS="" to disable.
SORT_COMPRESS = [f"--compress-program={c}"] if (c := os.environ.get("ARCHIVE_SORT_COMPRESS", "gzip")) else []


def cands_path(d: Path):
    """Existing candidate list for a target dir, else None. If both candidates.jsonl.gz and a plain
    candidates.jsonl exist (e.g. a pre-2026-10-11 runner rediscovered), the newer one by mtime wins."""
    found = [p for p in (d / "candidates.jsonl.gz", d / "candidates.jsonl") if p.exists()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def open_text(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open(encoding="utf-8")


class _TextSink:
    """str -> utf-8 bytes writer over a GzipFile (lets us fsync the underlying raw file after close)."""
    def __init__(self, gz):
        self.gz = gz

    def write(self, s: str):
        self.gz.write(s.encode("utf-8"))


log = logging.getLogger("run_archive")
STOP = False
# 2026-10-18 throttle deferral: the shared fetcher raises ArchiveDeferred on 429/5xx (or while the host cools down)
# instead of retrying. Items hit by a deferral are requeued in deferred_wayback.tsv (never marked done/failed);
# after DEFER_STREAK consecutive throttle-deferred items the run ends cleanly with rc 75 and the waiter
# (wayback_resume_loop.py) waits out the cool-down. A full (non --deferred-only) run cut short this way leaves
# <TARGET>/resume_full.flag so the waiter reruns the full pass (resumes from done.tsv).
# 2026-10-18 ~12:10 PT shared-fetcher API v2 (archive/README.md "Errors, deferrals"):
#  * fetch_best / fetch_newest RAISE ArchiveDeferred (earliest not_before, .families/.hosts) when nothing usable was
#    found and a CC/Wayback source was throttled -> requeued with e.not_before. (v2-era last_wb_deferred / last_deferral
#    checks are superseded by the per-call FetchInfo below.)
#  * cc_captures / list_captures return a CaptureList; .truncated -> listing incomplete: discovery is NOT completed,
#    finished queries are checkpointed in <TARGET>/discovery_partial/ and the next run resumes from there.
#  * The deferral-counter check (_ndef) stays as a safety net (partial doc + deferral, builders that swallow
#    exceptions, WORLD_LAW_ARCHIVE_RAISE_DEFERRED=0).
# 2026-10-18 ~12:25 PT API v3 ("Completeness signals"): the fetch phase relies on PER-CALL signals only
# (fx.fetch_best_ex -> (doc, FetchInfo); no fx.last_* instance attributes, which nested calls overwrite):
#  * doc None + info.exception (throttle / cool-down / timeout / busy / breaker_open) -> requeue for
#    exception.not_before; reason column "throttle:fetch" (throttle/cool-down only) or "deferred:fetch:<reasons>".
#  * doc None + no exception -> genuine all-sources miss (no_good_capture).
#  * doc.incomplete (another source failed transiently): staged if the body is complete (content_complete, as
#    before); a partial body (content_complete False) is requeued for a fuller copy (prior partial-doc policy).
#  * discovery (round 4): CaptureList.retryable_truncation -> rc 75, re-list after .deferral.not_before;
#    .complete_except_permanent (only permanent gaps) -> final, gaps logged + kept in progress.json "permanent_gaps".
#    Wayback listing errors: non-permanent (.permanent False) -> rc 75; permanent -> logged gap. TSV reasons come from
#    ArchiveDeferred.reasons / typed .kind, never from message text.
DEFER_STREAK = int(os.environ.get("ARCHIVE_DEFER_STREAK", "10"))
# Round 5 (2026-10-18 ~12:45 PT): the fetcher turns unknown / no-status / parse errors into retryable gaps (reason
# unknown_error, ~1 h) and does NOT cap them. We cap them here:
#  * discovery: per query, retries caused ONLY by unknown_error gaps are counted in progress.json
#    (unknown_error_attempts); the UNKNOWN_CAP-th such failure finalises the query as done-with-gaps
#    (progress.json unknown_error_gaps + stats discovery_unknown_error_gaps).
#  * items: requeues whose reasons are ONLY unknown_error carry an attempt count in the reason column
#    ("deferred:fetch:unknown_error#2"); the UNKNOWN_CAP-th marks the item failed_unknown_error in done.tsv
#    (retry manually later with a "<key>\trequeue" line in done.tsv). Any other requeue resets the count.
UNKNOWN_CAP = int(os.environ.get("ARCHIVE_UNKNOWN_ERROR_CAP", "3"))
# 2026-10-18 ~12:55 PT: every pass (--deferred-only and full/resume passes) skips deferred items whose column-4
# not_before (from their LAST deferred_wayback.tsv line) is still in the future: not fetched, line left as is, no
# streak. If nothing was due the run logs the earliest not_before and exits rc 75 (items still deferred); the
# waiter (wayback_resume_loop.py) does not launch a target with nothing due and sleeps until the earliest one.
_UNK_RX = re.compile(r"(?:^|:)unknown_error#(\d+)$")
WB_HOST = "web.archive.org"
ARCHIVE_HOSTS = (WB_HOST, "index.commoncrawl.org", "data.commoncrawl.org")


def _stop(*_):
    global STOP
    STOP = True


def utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def first_group(m):
    return next((g for g in m.groups() if g), None) if m else None


def hf_keys(spec):
    keys, urls = set(), set()
    p = HF_IDS / f"{spec['cc']}.jsonl"
    if not p.exists():
        return keys, urls
    rx = re.compile(spec["hf_key"]) if spec.get("hf_key") else None
    for line in p.open():
        r = json.loads(line)
        u = r.get("source_url") or ""
        if u:
            urls.add(canonical_url(u))
            if rx:
                k = first_group(rx.search(u))
                if k:
                    keys.add(k.lower())
    return keys, urls


# ---------------------------------------------------------------- extraction
def html_extract(html: str, selectors, title_selectors=None):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    title = ""
    for sel in list(title_selectors or []) + ["h1"]:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            title = el.get_text(" ", strip=True)
            break
    t = soup.find("title")
    page_title = t.get_text(" ", strip=True) if t else ""
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "iframe", "svg", "select", "button"]):
        tag.decompose()
    text = ""
    for sel in selectors or []:
        try:
            nodes = soup.select(sel)
        except Exception:
            nodes = []
        t = "\n".join(n.get_text("\n", strip=True) for n in nodes)
        if len(t) > 150:
            text = t
            break
    if not text:
        text = (soup.body or soup).get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t\u00a0]+", " ", text))
    links = [a.get("href") for a in soup.find_all("a", href=True)]
    return (title or page_title)[:500], page_title[:500], text, links


def pdf_text(body: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(body); f.flush()
        try:
            out = subprocess.run(["pdftotext", "-q", "-enc", "UTF-8", f.name, "-"], capture_output=True, timeout=180)
            return out.stdout.decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            return ""


DATE_RX = [re.compile(r"\b((?:19|20)\d\d)-(\d\d)-(\d\d)\b"), re.compile(r"\b(\d{1,2})[./](\d{1,2})[./]((?:19|20)\d\d)\b")]


def guess_date(text: str):
    for i, rx in enumerate(DATE_RX):
        m = rx.search(text[:3000])
        if m:
            try:
                if i == 0:
                    y, mo, d = m.groups()
                else:
                    d, mo, y = m.groups()
                datetime(int(y), int(mo), int(d))
                return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------- main
class Runner:
    def __init__(self, target, args):
        self.t = target
        self.spec = SPECS[target]
        self.args = args
        self.dir = WORK / target
        self.dir.mkdir(parents=True, exist_ok=True)
        self.fx = ArchiveFetcher(cc_crawls=args.cc_crawls, lane=os.environ.get("ARCHIVE_LANE") or "national")
        self.writers = {}
        self.unk_attempts = {}   # key -> consecutive unknown_error-only requeues (from deferred_wayback.tsv)
        self.pending = []  # canonical urls awaiting flush -> done
        self.done = {}
        self.stats = Counter()
        self.seen_titles = set()
        self.hf_titles = set()
        if self.spec.get("hf_title_dedupe"):
            p = HF_IDS / f"{self.spec['cc']}.jsonl"
            if p.exists():
                for line in p.open():
                    t = json.loads(line).get("title") or ""
                    if t:
                        self.hf_titles.add(re.sub(r"\s+", "", t))
        self.inc = re.compile(self.spec["include"])
        self.exc = re.compile(self.spec["exclude"]) if self.spec.get("exclude") else None
        rb = self.spec.get("reject_body")   # e.g. SPA shells: try older captures instead
        self.validator = (lambda d, _rx=re.compile(rb.encode()): not _rx.search(d.body[:200000])) if rb else None
        dp = self.dir / "done.tsv"
        if dp.exists():
            for line in dp.open():
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2:
                    if parts[1] == "requeue":          # later line re-opens an item (e.g. failed during an outage)
                        self.done.pop(parts[0], None)
                    else:
                        self.done[parts[0]] = parts[1]

    # ---- discovery (streamed through disk: captures -> TSV -> external sort -> grouped candidates;
    # nothing proportional to the listing size is held in memory, so it runs under a ~600 MB AS cap)
    def _iter_wb(self, url, match, filters, max_rows):
        """Generator twin of ArchiveFetcher.wb_captures (same params, same cache keys -> cached pages reused)."""
        from urllib.parse import quote
        from archive.core import WB_CDX
        params = [("url", url), ("matchType", match), ("output", "json"),
                  ("fl", "timestamp,original,mimetype,statuscode,digest,length"), ("filter", "statuscode:200")]
        for flt in filters or []:
            params.append(("filter", flt))
        params.append(("collapse", "timestamp:4"))
        resume, part, n = None, 0, 0
        while True:
            p = list(params) + [("limit", "10000"), ("showResumeKey", "true")]
            if resume:
                p.append(("resumeKey", resume))
            q = "&".join(f"{k}={quote(v, safe=':/*,!')}" for k, v in p)
            key = f"WB|{q}"
            data = self.fx.cache.cdx_get(key, self.fx.cdx_ttl)
            if data is None:
                r = self.fx._get("wayback", f"{WB_CDX}?{q}", ok_status=(200,))
                if r.status_code != 200:
                    raise ArchiveError(f"wayback cdx {r.status_code}", status=r.status_code,
                                       permanent=True if r.status_code == 403 else None)
                try:
                    data = r.json() if r.text.strip() else []
                except ValueError:
                    raise ArchiveTransient("wayback cdx non-json", kind="bad_response")
                self.fx.cache.cdx_put(key, data)
            rows = data[1:] if data and data[0] and data[0][0] == "timestamp" else data
            resume = None
            if len(rows) >= 2 and rows[-2] == [] and len(rows[-1]) == 1:
                resume = rows[-1][0]; rows = rows[:-2]
            for row in rows:
                if len(row) < 6:
                    continue
                ts, orig, mime, st, dg, ln = row[:6]
                n += 1
                yield Capture("wayback", "wayback", ts, orig, int(st) if str(st).isdigit() else None,
                              mime, dg, int(ln) if str(ln).isdigit() else None)
            del data, rows
            part += 1
            if not resume or n >= max_rows or STOP:
                break
            log.info("wayback cdx %s: %d rows so far (part %d, streamed)", url, n, part)

    # ---- throttle deferral helpers (2026-10-18)
    def _ndef(self):
        """Fetcher deferral counter (429/5xx deferrals + calls refused during a host cool-down + timeouts given up +
        breaker skips): safety net for builders that swallow fetch exceptions (flk reader pages)."""
        return sum(v for k, v in self.fx.stats.items()
                   if k.endswith(("_deferred", "_deferred_cooldown", "_timeout_gaveup", "_skipped_breaker")))

    @staticmethod
    def _reason_tag(stage, e):
        """deferred_wayback.tsv reason column (no tabs): 'throttle:<stage>' for 429/5xx / cool-down only (unchanged
        from before), else 'deferred:<stage>:<reason,...>' (timeout / breaker_open / busy / transient)."""
        if isinstance(e, ArchiveDeferred):
            rs = sorted(set(e.reasons or [e.reason]))
        elif e is not None:
            rs = [getattr(e, "kind", None) or "transient"]      # typed .kind (timeout / breaker_open / busy / ...)
        else:
            rs = []
        if not rs or set(rs) <= {"throttled", "cooldown"}:
            return f"throttle:{stage}"
        return f"deferred:{stage}:" + ",".join(re.sub(r"[\s:]", "_", r) for r in rs)[:120]

    @staticmethod
    def _only_unknown(e):
        return isinstance(e, ArchiveDeferred) and set(e.reasons or [e.reason]) == {"unknown_error"}

    def _requeue(self, key, n, stage, e, not_before=None):
        """Requeue one item (never done/failed); bumps the throttle streak. Returns True if the run must stop.
        unknown_error-only requeues are counted and capped at UNKNOWN_CAP (then: failed_unknown_error in done.tsv)."""
        nb = not_before or getattr(e, "not_before", None) or (time.time() + 600 if e is not None else None)
        tag = self._reason_tag(stage, e)
        if self._only_unknown(e):
            att = self.unk_attempts.get(key, 0) + 1
            if att >= UNKNOWN_CAP:
                log.warning("%s: %d unknown_error requeues (cap %d) -> failed_unknown_error: %s", key, att,
                            UNKNOWN_CAP, str(e)[:300])
                self.stats["failed_unknown_error"] += 1
                self.mark(key, "failed_unknown_error")     # done.tsv; compact_deferred drops its deferred line
                self.unk_attempts.pop(key, None)
                return False
            self.unk_attempts[key] = att
            tag = f"{tag}#{att}"
        else:
            self.unk_attempts.pop(key, None)
        self.stats["deferred_throttle" if tag.startswith("throttle:") else "deferred_" + tag.split(":")[2].split(",")[0]] += 1
        self.defer_item(key, n, tag, not_before=nb)
        self.defer_streak += 1
        if self.defer_streak >= DEFER_STREAK:
            self._throttle_stop()
            return True
        return False

    @staticmethod
    def _not_before():
        nb = 0.0
        for h, v in (deferral.host_status() or {}).items():
            if h in ARCHIVE_HOSTS and isinstance(v, dict):
                nb = max(nb, float(v.get("not_before", 0) or 0))
        return nb

    def defer_item(self, key, n, reason, not_before=None):
        """Requeue: deferred_wayback.tsv line (key, count, utc, not_before epoch, reason); never done/failed.
        not_before: the ArchiveDeferred's own (earliest) not_before when known, else the hosts' cool-down."""
        nb = float(not_before or 0) or self._not_before()
        with (self.dir / "deferred_wayback.tsv").open("a") as f:
            f.write(f"{key}\t{n}\t{utc()}\t{nb:.0f}\t{reason}\n")
        self.done[key] = "deferred_wayback"   # skip for the rest of this run only (not written to done.tsv)

    def _set_full_flag(self, why):
        if not self.args.deferred_only and not self.args.max_fetch:
            (self.dir / "resume_full.flag").write_text(f"{utc()} {why}\n")

    def _discovery_deferred(self, why, not_before=None, stat="discovery_deferred_throttle"):
        """Listing incomplete (throttled / truncated / transient): never build candidates from it. Queries already
        finished stay checkpointed in discovery_partial/ (nothing is deleted); rc 75 so the waiter reruns later."""
        nb = float(not_before or 0) or self._not_before()
        log.warning("discovery deferred: %s; %d/%d queries checkpointed; rerun after %s (rc 75)", why,
                    len(getattr(self, "_disc_prog", {}).get("done", [])), len(self.spec["queries"]),
                    time.strftime("%F %T %Z", time.localtime(nb)) if nb else "?")
        self.stats[stat] += 1
        if getattr(self, "_disc_prog", None) is not None:
            self._disc_prog.update(deferred=why[:500], not_before=round(nb), complete=False)
            self._save_disc_prog()
        self._set_full_flag("discovery deferred: " + why[:200])
        self.save_stats()
        raise SystemExit(75)

    def _unknown_gap_final(self, i, src, errors, why):
        """Count an unknown_error-only discovery failure for query i. True -> cap reached: finalise as done-with-gaps
        (recorded in progress.json unknown_error_gaps); False -> caller defers (rc 75)."""
        prog = self._disc_prog
        att = prog.setdefault("unknown_error_attempts", {})
        k = f"{i}:{src}"
        att[k] = int(att.get(k, 0)) + 1
        self._save_disc_prog()
        if att[k] < UNKNOWN_CAP:
            return False
        log.warning("discovery query %d %s: %d unknown_error attempts (cap %d) -> done-with-gaps: %s", i, src, att[k],
                    UNKNOWN_CAP, why[:300])
        prog.setdefault("unknown_error_gaps", {})[k] = [str(x)[:300] for x in list(errors or [why])[:20]]
        prog["unknown_error_gap_count"] = len(prog["unknown_error_gaps"])
        self.stats["discovery_unknown_error_gaps"] += 1
        self._save_disc_prog()
        return True

    # ---- discovery checkpoint (discovery_partial/: q<NNNN>.tsv per finished query + progress.json)
    def _disc_sig(self):
        sp, a = self.spec, self.args
        return hashlib.sha1(json.dumps([repr(sp["queries"]), sp["include"], sp.get("exclude"), bool(a.no_cc),
                                        bool(a.no_wayback), a.cc_crawls, a.max_wb_rows], default=str).encode()).hexdigest()[:16]

    def _save_disc_prog(self):
        self._disc_prog["updated"] = utc()
        tmp = self._disc_dir / "progress.json.tmp"
        tmp.write_text(json.dumps(self._disc_prog, indent=1))
        os.replace(tmp, self._disc_dir / "progress.json")

    def _load_disc_prog(self):
        d = self._disc_dir = self.dir / "discovery_partial"
        sig = self._disc_sig()
        prog = None
        if (d / "progress.json").exists():
            try:
                prog = json.loads((d / "progress.json").read_text())
            except ValueError:
                prog = None
            if not prog or prog.get("sig") != sig:
                aside = self.dir / f"discovery_partial.stale_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
                os.replace(d, aside)                     # spec/args changed: set aside (never deleted)
                log.warning("discovery checkpoint does not match spec/args; moved to %s", aside.name)
                prog = None
        d.mkdir(exist_ok=True)
        if prog is None:
            prog = {"sig": sig, "n_queries": len(self.spec["queries"]), "done": [], "rows": {}, "started": utc()}
        prog["done"] = [i for i in prog.get("done", []) if (d / f"q{i:04d}.tsv").exists()]
        self._disc_prog = prog
        return prog

    def discover(self):
        prog = self._load_disc_prog()
        pdir = self._disc_dir
        done_q = set(prog["done"])
        if done_q:
            log.info("discovery resumes: %d/%d queries already checkpointed in %s", len(done_q),
                     len(self.spec["queries"]), pdir.name)
        n_rows = 0

        def emit(c, fo):
            nonlocal n_rows
            if c.status not in (200, None):
                return
            m = self.inc.search(c.original_url)
            if not m or (self.exc and self.exc.search(c.original_url)):
                return
            key = self.spec["key_fn"](m) if self.spec.get("key_fn") else first_group(m)
            if not key:
                return
            k = re.sub(r"[\t\n\r]", " ", key.lower())
            fo.write(f"{k}\t{c.timestamp}\t{int(c.source == 'commoncrawl')}\t"
                     f"{json.dumps(c.to_dict(), ensure_ascii=False)}\n")
            n_rows += 1
        if len(done_q) < len(self.spec["queries"]):
            if not self.args.no_wayback and not ratelimit.wayback_available():
                # a listing without Wayback would silently drop Wayback-only candidates: defer discovery
                log.warning("wayback breaker open (box-wide): discovery deferred, rerun later (or --no-wayback)")
                self._discovery_deferred("wayback breaker open", stat="discovery_deferred_wayback")
            if not self.args.no_wayback and deferral.host_cooldown(WB_HOST) > 0:
                self._discovery_deferred(f"{WB_HOST} cooling down {deferral.host_cooldown(WB_HOST):.0f}s")
        for i, (url, match, flt) in enumerate(self.spec["queries"]):
            if STOP:
                break
            if i in done_q:
                continue
            t0 = time.time(); n_cc = n_wb = 0; r0 = n_rows
            with (pdir / f"q{i:04d}.tsv").open("w") as fo:     # (re)written from scratch; done only when complete
                if not self.args.no_cc:
                    caps = self.fx.cc_captures(url, match)
                    for c in caps:
                        n_cc += 1; emit(c, fo)
                    if caps.truncated:
                        tr = caps.truncated_reason or "deferred"
                        errs = "; ".join(list(caps.errors or ())[:3])
                        dr = set(caps.deferral.reasons or [caps.deferral.reason]) if caps.retryable_truncation else set()
                        if dr == {"unknown_error"} and self._unknown_gap_final(i, "cc", caps.errors, errs or str(caps.deferral)):
                            pass                                   # capped: done-with-gaps, query treated as final
                        elif caps.retryable_truncation:
                            # a gap that may fill later (throttle / timeout / busy / breaker / cc_breaker): re-list
                            # after .deferral.not_before; finished queries stay checkpointed
                            self._discovery_deferred(f"cc listing {url} truncated ({tr}) after {n_cc} captures: "
                                                     f"{errs or caps.deferral}", caps.deferral.not_before,
                                                     stat="discovery_truncated_cc")
                        else:
                            # complete_except_permanent: only permanent gaps (400/404/410 crawl) -> final
                            log.warning("cc listing %s: permanent gaps only (%s), treated as complete: %s", url, tr, errs)
                            self.stats["discovery_cc_permanent_gaps"] += 1
                            prog.setdefault("permanent_gaps", {})[str(i)] = list(caps.errors or [tr])[:20]
                if not self.args.no_wayback:
                    try:
                        for c in self._iter_wb(url, match, flt, self.args.max_wb_rows):
                            n_wb += 1; emit(c, fo)
                    except ArchiveDeferred as e:
                        # a partial listing would silently drop candidates; finished queries stay checkpointed
                        self._discovery_deferred(f"wayback listing {url}: {e}", e.not_before)
                    except ArchiveTransient as e:
                        # timeouts after the retry budget / breaker opened mid-listing: also incomplete, not a result
                        self._discovery_deferred(f"wayback listing {url} transient: {e}", time.time() + 600,
                                                 stat="discovery_deferred_transient")
                    except ArchiveError as e:
                        unk = getattr(e, "kind", "error") == "error" and not e.permanent   # no status / unknown
                        if unk and self._unknown_gap_final(i, "wb", [f"wayback: {e}"], str(e)):
                            pass                                   # capped: done-with-gaps
                        elif not e.permanent:
                            self._discovery_deferred(f"wayback listing {url} ({e.kind}): {e}",
                                                     time.time() + (3600 if unk else 600),
                                                     stat="discovery_deferred_transient")
                        else:
                            log.warning("wayback listing failed permanently %s (%s): %s", url, e.kind, e)
                            prog.setdefault("permanent_gaps", {}).setdefault(str(i), []).append(f"wayback: {e}"[:300])
                        self.stats["wb_listing_failed"] += 1
            if STOP:   # _iter_wb stops early on SIGTERM: this query is incomplete, not checkpointed
                break
            prog["done"].append(i); prog["rows"][str(i)] = n_rows - r0
            prog.pop("deferred", None); prog.pop("not_before", None)
            self._save_disc_prog()
            log.info("discover %s %s: cc=%d wb=%d (%.0fs)", url, match, n_cc, n_wb, time.time() - t0)
            self.stats["captures_cc"] += n_cc
            self.stats["captures_wb"] += n_wb
        if STOP:
            log.warning("stopped during discovery; %d/%d queries checkpointed, rerun resumes", len(prog["done"]),
                        len(self.spec["queries"]))
            self._set_full_flag("stopped during discovery")
            return iter(())
        qfiles = [str(pdir / f"q{i:04d}.tsv") for i in range(len(self.spec["queries"]))] or ["/dev/null"]
        n_rows = sum(int(v) for v in prog["rows"].values())
        hfk, hfu = hf_keys(self.spec)
        keep = self.spec.get("keep_caps", 3)
        env = dict(os.environ, LC_ALL="C")
        srt = subprocess.Popen(["sort", "-S", "64M", *SORT_COMPRESS, "-T", str(self.dir), "-t", "\t", "-k1,1", "-k2,2r", "-k3,3r", *qfiles],
                               stdout=subprocess.PIPE, env=env, text=True)
        grp = self.dir / "cand_grouped.tmp"
        n_out = n_hf = 0

        def flush(k, caps, fg):
            nonlocal n_out, n_hf
            if not caps:
                return
            cc = [c for c in caps if c["source"] == "commoncrawl"][:keep]
            wb = [c for c in caps if c["source"] == "wayback"][:keep]
            in_hf = k in hfk or any(canonical_url(c["original_url"]) in hfu for c in caps[:5])
            r = {"key": k, "newest": caps[0]["timestamp"], "in_hf": in_hf, "caps": cc + wb}
            fg.write(f"{r['newest']}\t{json.dumps(r, ensure_ascii=False)}\n")
            n_out += 1; n_hf += in_hf

        with grp.open("w") as fg:
            cur, caps, n_src = None, [], Counter()
            for line in srt.stdout:
                k, ts, iscc, cj = line.rstrip("\n").split("\t", 3)
                if k != cur:
                    flush(cur, caps, fg)
                    cur, caps, n_src = k, [], Counter()
                src = "commoncrawl" if iscc == "1" else "wayback"
                if n_src[src] < keep or len(caps) < 5:
                    caps.append(json.loads(cj)); n_src[src] += 1
            flush(cur, caps, fg)
        if srt.wait() != 0:
            raise RuntimeError("sort failed")
        tmp = self.dir / "candidates.jsonl.gz.tmp"
        with open(tmp, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6) as gz:
            f = _TextSink(gz)
            s2 = subprocess.Popen(["sort", "-S", "64M", *SORT_COMPRESS, "-T", str(self.dir), "-s", "-t", "\t", "-k1,1r", str(grp)],
                                  stdout=subprocess.PIPE, env=env, text=True)
            for line in s2.stdout:
                f.write(line.split("\t", 1)[1])
            if s2.wait() != 0:
                raise RuntimeError("sort failed")
            gz.close(); raw.flush(); os.fsync(raw.fileno())
        os.replace(tmp, self.dir / "candidates.jsonl.gz")
        (self.dir / "candidates.jsonl").unlink(missing_ok=True)  # superseded plain list
        grp.unlink(missing_ok=True)
        # discovery complete: retire the checkpoint (moved aside, not deleted; scratch, safe to clean up later)
        prog.update(complete=True, candidates=n_out)
        self._save_disc_prog()
        os.replace(pdir, self.dir / f"discovery_done_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
        self.stats["candidates"] = n_out
        self.stats["candidates_in_hf"] = n_hf
        log.info("candidates=%d (in HF already: %d; %d filtered capture rows, streamed via disk)", n_out, n_hf, n_rows)
        return (r for r in self._iter_cands(self.dir / "candidates.jsonl.gz") if r is not None)

    # ---- writing
    def writer(self, place_id):
        w = self.writers.get(place_id)
        if w is None:
            w = self.writers[place_id] = StagedWriter(STAGE, self.spec["cc"], place_id, batch_prefix="archive",
                                                      chunk=self.args.chunk)
        return w

    def mark(self, key, outcome, flushed=True):
        if flushed:
            with (self.dir / "done.tsv").open("a") as f:
                f.write(f"{key}\t{outcome}\t{utc()}\n")
        self.done[key] = outcome

    def flush_all(self):
        for w in self.writers.values():
            if w.buf:
                p = w.flush()
                log.info("staged %s", p)
        for k in self.pending:
            self.mark(k, "staged")
        self.pending = []

    # ---- per candidate
    def build(self, r, doc):
        sp = self.spec
        if sp.get("custom") == "flk":
            return self.build_flk(r, doc)
        ct = (doc.content_type or "").lower()
        is_pdf = "pdf" in ct or doc.body[:5] == b"%PDF-"
        links = []
        if is_pdf:
            text = pdf_text(doc.body)
            title = next((l.strip() for l in text.splitlines() if len(l.strip()) > 8), "")[:300]
            page_title = ""
            fmt = "pdf_text"
        else:
            title, page_title, text, links = html_extract(doc.text(), sp.get("selectors"), sp.get("title_selectors"))
            fmt = "html"
            if sp.get("head_rx"):   # issuer / act-type line that sits outside the text container
                full = html_extract(doc.text(), [], None)[2]
                m = re.search(sp["head_rx"], full)
                if m and m.group(0).strip() not in text[:500]:
                    text = m.group(0).strip() + "\n\n" + text
        # follow an archived PDF when the page itself is thin
        if not is_pdf and sp.get("follow_pdf") and (len(text) < 3000 or sp.get("always_follow_pdf")):
            from urllib.parse import urljoin
            rx = re.compile(sp["follow_pdf"])
            got_pdf = False
            seen = []
            for href in links:
                if href and rx.search(href):
                    purl = urljoin(doc.original_url, href)
                    if purl in seen:
                        continue
                    seen.append(purl)
                    if len(seen) > 2:
                        break
                    try:
                        pdoc, pinfo = self.fx.fetch_newest_ex(purl, max_tries=3)
                    except ArchiveError:
                        pdoc, pinfo = None, None
                    if pdoc is None and pinfo is not None and pinfo.exception is not None:
                        raise pinfo.exception      # transient: requeue the whole item (run() -> build stage)
                    if pdoc is not None and getattr(pdoc, "incomplete", False) and not pdoc.content_complete:
                        raise pdoc.deferral or ArchiveTransient("pdf: partial copy while a source failed")
                    if pdoc is not None and (pdoc.body[:5] == b"%PDF-"):
                        ptxt = pdf_text(pdoc.body)
                        if len(ptxt.strip()) > 200:
                            text = (title + "\n\n" + ptxt) if title else ptxt
                            fmt = "pdf_text"
                            got_pdf = True
                            self.stats["followed_pdf"] += 1
                            doc.content_complete = doc.content_complete and pdoc.content_complete
                            break
            if seen and not got_pdf:
                # landing page only (metadata/abstract); full text PDF not in the archives
                self.stats["pdf_not_archived"] += 1
                doc.content_complete = False
                doc.incomplete_reason = "landing_page_only:pdf_not_archived"
        text = text.strip()
        if sp.get("title_rx"):   # norm heading inside the text beats generic page/PDF headers
            m = re.search(sp["title_rx"], text[:6000])
            if m:
                title = re.sub(r"\s+", " ", m.group(0)).strip()[:300]
            elif sp.get("title_from_key"):
                title = sp["title_from_key"](r["key"])
        if sp.get("title_from_text"):
            ls = [l.strip() for l in text.splitlines() if len(l.strip()) > 1][: sp["title_from_text"]]
            if ls:
                title = " ".join(ls)[:500]
        if len(text) < sp.get("min_chars", 300):
            return None, "too_short"
        if sp.get("title_must") and not re.search(sp["title_must"], (title or "") + (page_title or "")):
            return None, "title_filter"
        place = sp["place"](doc.original_url, r["key"], text, title)
        if not place:
            return None, "no_place"
        place_id, place_name, iso2, level = place
        rec = {
            "place_id": place_id, "country_code": sp["cc"], "doc_id": f"{sp['platform']}:{r['key']}",
            "source_platform": sp["platform"], "source_url": doc.original_url,
            "doc_type": sp["doc_type_fn"](r["key"], title) if sp.get("doc_type_fn") else sp["doc_type"],
            "language": sp["language"], "title_native": (title or page_title or r["key"])[:1000],
            "consolidated": sp["consolidated"], "content_format": fmt, "text": text,
            "retrieved_at": doc.fetched_at, "admin_level": level, "platform": sp["platform"],
        }
        if place_name:
            rec["place_name"] = place_name
        if iso2:
            rec["iso_3166_2"] = iso2
        d = guess_date(text)
        if d:
            rec["published_date"] = d
        if "/abro/" in doc.original_url:
            rec["in_force"] = False
        rec.update(provenance_fields(doc, *policy_for(doc.original_url)))
        return rec, "ok"

    def build_flk(self, r, doc):
        import flk
        sp = self.spec
        out, why, fmt, incomplete = flk.build(self, r, doc)
        if out is None:
            return None, why
        if len(out["text"]) < sp.get("min_chars", 300):
            return None, "too_short"
        if sp.get("title_must") and not re.search(sp["title_must"], out["title"]):
            return None, "title_filter"
        if out["place"] in (None, "municipal"):
            return None, "municipal_level" if out["place"] == "municipal" else "no_place"
        tkey = re.sub(r"\s+", "", out["title"])
        if tkey in self.hf_titles:
            return None, "in_hf_title"
        if tkey in self.seen_titles:
            return None, "dup_title"
        self.seen_titles.add(tkey)
        place_id, place_name, iso2, level = out["place"]
        if incomplete:
            doc.content_complete = False
            doc.incomplete_reason = incomplete
        rec = {
            "place_id": place_id, "country_code": sp["cc"], "doc_id": f"{sp['platform']}:{r['key']}",
            "source_platform": sp["platform"], "source_url": doc.original_url, "doc_type": out["doc_type"],
            "language": sp["language"], "title_native": out["title"][:1000] or r["key"],
            "consolidated": sp["consolidated"], "content_format": fmt, "text": out["text"],
            "retrieved_at": doc.fetched_at, "admin_level": level, "platform": sp["platform"],
        }
        if place_name:
            rec["place_name"] = place_name
        if iso2:
            rec["iso_3166_2"] = iso2
        d = guess_date(out["text"])
        if d:
            rec["published_date"] = d
        rec.update(provenance_fields(doc, *policy_for(doc.original_url)))
        if incomplete:
            rec["extra_metadata"]["archive"]["incomplete_reason"] = incomplete
        return rec, "ok"

    def run(self):
        cpath = cands_path(self.dir)
        if self.args.rediscover or cpath is None:
            cands = self.discover()
        else:
            # stream from disk (memory): one counting pass, then iterate lazily
            n0 = n = n_hf = 0
            for r in self._iter_cands(cpath, count_only=True):
                n0 += 1
                if r is not None:
                    n += 1; n_hf += bool(r["in_hf"])
            if self.exc:
                self.stats["excluded_after_discovery"] = n0 - n
            self.stats["candidates"] = n
            self.stats["candidates_in_hf"] = n_hf
            cands = (r for r in self._iter_cands(cpath) if r is not None)
        self.save_stats()
        if self.args.discover_only:
            return
        n = 0
        last_flush = time.time()
        self.deferred_prev = self.load_deferred()
        if self.args.deferred_only:
            log.info("deferred-only: %d keys in deferred_wayback.tsv", len(self.deferred_prev))
        self.cand_seen = set()        # eligible candidate keys reached in this pass (for pruning stale deferred keys)
        self.full_pass = False
        self.defer_streak = 0         # consecutive items deferred by throttling (429/5xx / host cool-down)
        self.throttle_stopped = False
        self.next_due = None          # earliest future not_before among skipped deferred items
        for r in cands:
            if STOP or (self.args.max_fetch and n >= self.args.max_fetch):
                break
            if self.args.deferred_only and r["key"] not in self.deferred_prev:
                continue
            if r["in_hf"] and not self.args.include_hf:
                continue
            self.cand_seen.add(r["key"])
            if r["key"] in self.done:
                continue
            nbk = self.def_nb.get(r["key"], 0.0) if r["key"] in self.deferred_prev else 0.0
            if nbk > time.time():
                # requeued with a not_before still in the future: leave it (line untouched, no streak)
                self.stats["skipped_not_due"] += 1
                self.next_due = min(self.next_due or nbk, nbk)
                continue
            if self.args.deferred_only and ratelimit.breaker_status().get("state") == "open":
                # breaker reopened: don't burn the rest of the list into deferrals; leave them for the waiter
                log.warning("wayback breaker open: stopping deferred retry pass (items stay deferred)")
                self.stats["stopped_breaker_open"] += 1
                break
            n += 1
            caps = [Capture(**c) for c in r["caps"]]
            try:
                doc, info = self.fx.fetch_best_ex(caps, max_tries=max(4, len(caps)), validator=self.validator)
            except ArchiveTransient as e:       # not expected (fetch_best_ex never raises deferrals): requeue
                log.info("fetch transient %s: %s", r["key"], e)
                if self._requeue(r["key"], 1, "fetch", e):
                    break
                continue
            except ArchiveError as e:
                log.info("fetch error %s: %s", r["key"], e)
                doc, info = None, None
            d1 = self._ndef()
            exc = getattr(info, "exception", None)
            if doc is None and exc is not None:
                # nothing usable and a source failed transiently (throttle / cool-down / timeout / breaker): requeue
                log.info("fetch deferred %s: %s", r["key"], exc)
                if self._requeue(r["key"], max(1, len(getattr(info, "deferrals", ()) or ())), "fetch", exc):
                    break
                continue
            if doc is None:
                # genuine miss: every source answered, nothing usable
                self.stats["no_good_capture"] += 1
                self.mark(r["key"], "no_good_capture")
                continue
            if getattr(doc, "incomplete", False):
                self.stats["found_while_source_failed"] += 1
                if not doc.content_complete:
                    # partial body + another source failed: a complete copy may come later -> requeue (prior policy)
                    dfr = getattr(doc, "deferral", None) or getattr(info, "deferral", None)
                    log.info("partial doc while a source failed %s: %s", r["key"], dfr)
                    if self._requeue(r["key"], max(1, len(getattr(info, "deferrals", ()) or ())), "fetch", dfr):
                        break
                    continue
            transient = None
            try:
                rec, why = self.build(r, doc)
            except ArchiveTransient as e:   # incl. ArchiveDeferred / breaker-open listing inside a builder
                rec, why, transient = None, "deferred", e
            except Exception as e:  # keep going
                log.exception("build failed %s", r["key"])
                rec, why = None, f"build_error:{type(e).__name__}"
            d2 = self._ndef()
            if d2 > d1 or transient is not None:
                # a follow-up fetch (PDF / reader pages) was deferred: requeue instead of staging a partial record
                log.info("deferred during build %s: %s", r["key"], transient or f"{d2 - d1} deferrals")
                if self._requeue(r["key"], max(1, d2 - d1), "build", transient):
                    break
                continue
            self.defer_streak = 0
            if rec is None:
                self.stats[why] += 1
                self.mark(r["key"], why)
                continue
            err = self.writer(rec["place_id"]).add(rec)
            if err:
                self.stats["invalid"] += 1
                self.mark(r["key"], "invalid:" + err[:80])
                continue
            self.stats["staged"] += 1
            self.stats["complete" if rec["content_complete"] else "incomplete"] += 1
            self.stats["stale" if rec["possibly_stale"] else "fresh"] += 1
            self.stats["src_" + rec["archive_source"]] += 1
            self.pending.append(r["key"])
            # writers auto-flush at chunk size; mark pending done when nothing is buffered
            if not any(w.buf for w in self.writers.values()):
                for k in self.pending:
                    self.mark(k, "staged")
                self.pending = []
            if time.time() - last_flush > self.args.flush_secs:
                self.flush_all(); last_flush = time.time()
            if n % 25 == 0:
                self.save_stats()
                log.info("progress fetched=%d staged=%d %s", n, self.stats["staged"], dict(self.fx.stats))
        else:
            self.full_pass = not STOP
        if self.stats["skipped_not_due"]:
            log.info("%d deferred items not yet due (earliest %s); %d attempted this run", self.stats["skipped_not_due"],
                     time.strftime("%F %T %Z", time.localtime(self.next_due)), n)
            self.stats["next_due"] = round(self.next_due)
        if self.full_pass and not self.args.deferred_only and not self.args.max_fetch:
            (self.dir / "resume_full.flag").unlink(missing_ok=True)
        self.flush_all()
        self.save_stats(final=not STOP)
        return self.compact_deferred()

    def _throttle_stop(self):
        nb = self._not_before()
        log.warning("%d consecutive items deferred by throttling (host cool-down until %s): ending run, rc 75",
                    self.defer_streak, time.strftime("%F %T %Z", time.localtime(nb)) if nb else "?")
        self.stats["stopped_throttle"] += 1
        self.throttle_stopped = True
        self._set_full_flag("stopped on throttle streak")

    # ---- deferred_wayback.tsv: retry list. A key leaves it only when done.tsv has a real outcome
    # (staged / no_good_capture / ...), or when a complete pass shows it is no longer an eligible candidate.
    def load_deferred(self):
        """Keys in deferred_wayback.tsv; also loads unknown_error attempt counts from the LAST line per key."""
        p, keys = self.dir / "deferred_wayback.tsv", set()
        self.unk_attempts = {}
        self.def_nb = {}      # key -> not_before (epoch) of its last line; 0 / missing = due now
        if p.exists():
            with p.open() as f:
                for line in f:
                    parts = line.rstrip("\n").split("\t")
                    k = parts[0]
                    if k:
                        keys.add(k)
                        m = _UNK_RX.search(parts[4]) if len(parts) >= 5 else None
                        if m:
                            self.unk_attempts[k] = int(m.group(1))
                        else:
                            self.unk_attempts.pop(k, None)
                        try:
                            self.def_nb[k] = float(parts[3]) if len(parts) >= 4 and parts[3] else 0.0
                        except ValueError:
                            self.def_nb[k] = 0.0
        return keys

    def compact_deferred(self):
        p = self.dir / "deferred_wayback.tsv"
        if not p.exists():
            return 0
        last = {}
        for line in p.open():
            k = line.split("\t", 1)[0].rstrip("\n")
            if k:
                last[k] = line if line.endswith("\n") else line + "\n"
        keep, resolved, stale = [], 0, 0
        for k, line in last.items():
            v = self.done.get(k)
            if v is not None and v != "deferred_wayback":
                resolved += 1
            elif self.full_pass and k not in self.cand_seen:
                stale += 1
            else:
                keep.append(line)
        tmp = p.with_suffix(".tsv.tmp")
        tmp.write_text("".join(keep))
        os.replace(tmp, p)
        log.info("deferred_wayback.tsv: %d still deferred, %d resolved (done/miss), %d no longer candidates",
                 len(keep), resolved, stale)
        self.stats["deferred_remaining"] = len(keep)
        self.save_stats(final=not STOP)
        return len(keep)

    def _iter_cands(self, path, count_only=False):
        """Yield candidate dicts one line at a time; None for lines excluded by spec['exclude']
        (exclusions may be added after discovery, e.g. BPK kab/kota -> municipal lanes)."""
        with open_text(path) as f:
            for line in f:
                r = json.loads(line)
                if self.exc and any(self.exc.search(c["original_url"]) for c in r["caps"][:1]):
                    yield None
                    continue
                if count_only:
                    r["caps"] = None
                yield r

    def save_stats(self, final=False):
        st = dict(self.stats)
        st["done_total"] = len(self.done)
        st["staged_total"] = sum(1 for v in self.done.values() if v == "staged")
        st["fetcher"] = dict(self.fx.stats)
        st["updated"] = utc()
        st["final"] = final
        tmp = self.dir / "stats.json.tmp"
        tmp.write_text(json.dumps(st, indent=1))
        os.replace(tmp, self.dir / "stats.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", choices=sorted(SPECS))
    ap.add_argument("--max-fetch", type=int, default=0)
    ap.add_argument("--cc-crawls", type=int, default=8)
    ap.add_argument("--max-wb-rows", type=int, default=600000)
    ap.add_argument("--chunk", type=int, default=200)
    ap.add_argument("--flush-secs", type=int, default=900)
    ap.add_argument("--discover-only", action="store_true")
    ap.add_argument("--rediscover", action="store_true")
    ap.add_argument("--include-hf", action="store_true")
    ap.add_argument("--no-cc", action="store_true")
    ap.add_argument("--no-wayback", action="store_true")
    ap.add_argument("--deferred-only", action="store_true",
                    help="only retry keys listed in deferred_wayback.tsv; stop when the Wayback breaker is open")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    if SPECS[a.target].get("disabled"):
        log.warning("%s disabled: %s", a.target, SPECS[a.target]["disabled"])
        return
    _single_instance(a.target)
    runner = Runner(a.target, a)
    left = runner.run()
    if left or getattr(runner, "throttle_stopped", False):
        log.warning("%s: %d items still deferred (wayback/throttle) -> exit 75", a.target, left or 0)
        sys.exit(75)                                   # EX_TEMPFAIL: not done


def _other_runner(target):
    me = os.getpid()
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) == me:
            continue
        try:
            argv = open(f"/proc/{d}/cmdline", "rb").read().split(b"\0")
        except OSError:
            continue
        if any(x.endswith(b"run_archive.py") for x in argv) and target.encode() in argv and b"python" in argv[0]:
            return int(d)
    return None


def _single_instance(target):
    """One runner per target (shared done.tsv / candidates.jsonl): wait for any other instance, then hold
    an flock on the target's work dir for the rest of the run."""
    import fcntl
    while True:
        pid = _other_runner(target)
        if not pid:
            break
        log.info("another %s runner (pid %d) is active; waiting", target, pid)
        time.sleep(60)
    d = WORK / target
    d.mkdir(parents=True, exist_ok=True)
    global _LOCKF
    _LOCKF = open(d / ".runner.lock", "w")
    fcntl.flock(_LOCKF, fcntl.LOCK_EX)


if __name__ == "__main__":
    main()
