#!/usr/bin/env python3
"""robots.txt guard for every shared fetch helper (CoS standing rule 2026-10-01).

Rule: before ANY download, fetch and honor the host's robots.txt (incl.
Crawl-delay), snapshot it with its UTC date, and never fetch a disallowed path
(report it instead).

What this module does
* fetches robots.txt once per (scheme, host) and caches it for the run;
* saves a dated snapshot  <ROOT>/<cc>/logs/robots/<host>_<YYYY-MM-DD UTC>.txt
  and appends a record to <ROOT>/<cc>/logs/robots/robots_snapshots.jsonl;
* evaluates rules Google-style (RFC 9309): the most specific matching
  user-agent group (our UA product names, else "*"), longest-match Allow/Disallow
  with "*" wildcards and "$" end anchors; Allow wins a length tie.
  (urllib.robotparser does NOT support * and $, so it is not used.)
* enforces Crawl-delay as the minimum spacing between requests to that host, with ONE
  shared per-host last-request clock (thread-safe) used by guard(), wait(), GuardedSession,
  the guarded_* wrappers and the robots-gated sessions in common / archive_fallbacks: each
  request waits the Crawl-delay once, measured from the last request to that host. A
  pre-flight guard(url)/wait(url) followed by the gated send of that request (same thread,
  same host+path, no other request to the host in between) does not wait a second time;
* a disallowed URL is NOT fetched: RobotsDisallowed is raised and the event is
  appended to <ROOT>/<cc>/logs/robots_blocked.jsonl;
* fails CLOSED when robots.txt answers 5xx / 429 / 401 / 403 / non-200 2xx
  (e.g. 202 WAF challenge) / an HTML challenge page, times out or errors at the
  network level (RobotsUnavailable, also logged to robots_blocked.jsonl).
  404 / 410 (and other 4xx) mean "no rules": allow. A TLS-verification failure
  is retried unverified for robots.txt only (public file; noted in the log).
* web.archive.org / Common Crawl / archive.is URLs are hosts like any other (Wayback
  fetches are subject to web.archive.org's own robots.txt), AND (CoS ruling 2026-10-01) an
  archive COPY of a URL is only fetched if the ORIGIN's robots.txt allows that URL too:
  for a Wayback replay URL  http(s)://web.archive.org/web/<ts>[id_|if_|im_|...]/<orig>
  (or archive.is|ph/<newest|ts>/<orig>) check() also evaluates <orig> against the origin's
  robots.txt; disallowed -> reason "origin_disallow", origin robots.txt unavailable ->
  reason "origin_robots_unavailable" (fail closed, same policy). Discovery that downloads
  no document (Wayback CDX /cdx/search/cdx, calendar /web/*/...) is judged by the archive
  host's robots.txt only. check_archived_copy(orig, archive_url) does the same for other
  archive copies (e.g. a Common Crawl WARC record of <orig>).
* robots_cached carve-out (CoS 2026-10-03), ARCHIVE copies only: every successful robots.txt
  read (200 rules, or 404/410/other 4xx = allow) is persisted to
  <ROOT>/logs/robots_snapshots/<host>.json (fetched_at, status, http_status, body); a failed
  read never overwrites it. When the ORIGIN's robots.txt cannot be read now, an archive copy
  is judged by that snapshot if it is at most 7 days old (logged as robots_cached; a cached
  Disallow blocks as origin_disallow); no snapshot or an older one stays fail-closed
  (origin_robots_unavailable). Direct live fetches to the origin are unchanged (fail closed).

Usage
    import robots_guard as rg
    rg.set_country("gt")            # or env ROBOTS_COUNTRY / COLLECTOR_CC
    rg.guard(url)                   # raises RobotsBlocked, else waits crawl-delay
    d = rg.check(url)               # Decision(allowed=..., rule=..., ...) no wait/raise
    s = rg.GuardedSession()         # requests.Session; every send() (incl. each
                                    # redirect hop) goes through guard()
    rg.guarded_curl_run(["curl", "-sL", url], capture_output=True)
                                    # curl never follows redirects itself (-L stripped,
                                    # --max-redirs 0); the wrapper follows Location hops
                                    # (max 10), guard()ing each hop incl. Crawl-delay
    try: ...
    except rg.RobotsBlocked as e:   # a PermissionError; put it BEFORE `except Exception`
        rg.log_robots_blocked(e, caller="collect_xx:fetch")   # robots_blocked, not a failure
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit, unquote, quote

ROOT = Path(os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", os.environ.get("LEGAL_CORPORA_ROOT", str(Path.home() / ".ipfs_datasets" / "legal_corpora"))))
# UA product names we answer to (matched case-insensitively against User-agent lines; RFC 9309 product names).
OUR_UA_PRODUCTS = ("legal-corpora-collector", "justicedao-legal-corpus")
ROBOTS_UA = (
    "legal-corpora-collector/1.0 "
    "(research archive of official national gazettes; polite; "
    "contact via local operator)"
)
MAX_ROBOTS_BYTES = 512 * 1024  # RFC 9309: parse at least 500 KiB
ROBOTS_TIMEOUT = (15, 30)


class RobotsBlocked(PermissionError):
    """Base: the guard refused to fetch (do not retry this URL in this run)."""

    def __init__(self, msg: str, decision: "Decision"):
        super().__init__(msg)
        self.decision = decision


class RobotsDisallowed(RobotsBlocked):
    pass


class RobotsUnavailable(RobotsBlocked):
    """robots.txt could not be read (5xx / timeout / ...): fail closed."""


# ---------------------------------------------------------------- parsing

@dataclass
class Group:
    agents: list = field(default_factory=list)
    rules: list = field(default_factory=list)  # (allow: bool, pattern: str)
    crawl_delay: Optional[float] = None


@dataclass
class Robots:
    groups: list
    sitemaps: list
    raw_sha256: str = ""

    def select(self, ua_products=OUR_UA_PRODUCTS) -> Optional[Group]:
        """Merge every group naming our most specific product name; else the * groups."""
        toks = [t.lower() for t in ua_products]
        best_len, merged = -1, None
        for g in self.groups:
            for a in g.agents:
                al = a.lower()
                if al == "*":
                    continue
                for t in toks:
                    # product-name match: the UA line name is a prefix of ours
                    if t == al or t.startswith(al):
                        if len(al) > best_len:
                            best_len, merged = len(al), Group([a], list(g.rules), g.crawl_delay)
                        elif len(al) == best_len and merged is not None:
                            merged.rules.extend(g.rules)
                            if merged.crawl_delay is None:
                                merged.crawl_delay = g.crawl_delay
        if merged is not None:
            return merged
        star = None
        for g in self.groups:
            if "*" in g.agents:
                if star is None:
                    star = Group(["*"], list(g.rules), g.crawl_delay)
                else:
                    star.rules.extend(g.rules)
                    if star.crawl_delay is None:
                        star.crawl_delay = g.crawl_delay
        return star


_LINE = re.compile(r"^\s*([A-Za-z-]+)\s*:\s*(.*?)\s*$")


def parse_robots(text: str) -> Robots:
    groups: list[Group] = []
    sitemaps: list[str] = []
    cur: Optional[Group] = None
    last_was_agent = False
    text = (text or "")
    for bom in ("\ufeff", "\u00ef\u00bb\u00bf"):  # BOM, also when mis-decoded as latin-1
        if text.startswith(bom):
            text = text[len(bom):]
    for raw in text.splitlines():
        line = raw.split("#", 1)[0]
        m = _LINE.match(line)
        if not m:
            continue
        key, val = m.group(1).lower(), m.group(2)
        if key in ("user-agent", "useragent", "user agent"):
            if cur is None or not last_was_agent:
                cur = Group()
                groups.append(cur)
            cur.agents.append(val.strip())
            last_was_agent = True
            continue
        if key == "sitemap":
            sitemaps.append(val)
            continue  # sitemap does not end an agent run
        last_was_agent = False
        if cur is None:
            continue  # rules before any User-agent are ignored
        if key in ("allow", "disallow"):
            if key == "disallow" and val == "":
                continue  # "Disallow:" (empty) = allow everything = no rule
            if val == "" and key == "allow":
                continue
            cur.rules.append((key == "allow", val))
        elif key in ("crawl-delay", "crawl_delay"):
            try:
                cur.crawl_delay = float(val)
            except ValueError:
                pass
    sha = hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()
    return Robots(groups, sitemaps, sha)


def _norm(s: str) -> str:
    """Normalise percent-encoding so /a%7Eb and /a~b compare equal."""
    try:
        return quote(unquote(s), safe="/?&=;:@!$'()*+,~-._%")
    except Exception:
        return s


def _glob_prefix(pat: str, s: str, anchored: bool) -> bool:
    """Wildcard match ('*' = any run) WITHOUT regex backtracking (ReDoS-safe, O(len*len)).

    Unanchored patterns match a prefix of s (implicit trailing '*'); '$' anchors the end.
    """
    if not anchored:
        pat = pat + "*"
    i = j = 0
    star, mark = -1, 0
    n, m = len(pat), len(s)
    while j < m:
        if i < n and pat[i] == "*":
            star, mark = i, j
            i += 1
        elif i < n and pat[i] == s[j]:
            i += 1
            j += 1
        elif star != -1:
            i = star + 1
            mark += 1
            j = mark
        else:
            return False
    while i < n and pat[i] == "*":
        i += 1
    return i == n


_pat_cache: dict = {}


def _prep(pattern: str):
    v = _pat_cache.get(pattern)
    if v is None:
        p = _norm(pattern)
        anchored = p.endswith("$")
        if anchored:
            p = p[:-1]
        p = re.sub(r"\*{2,}", "*", p)
        v = (p, anchored)
        if len(_pat_cache) < 50000:
            _pat_cache[pattern] = v
    return v


def match_rule(group: Optional[Group], path: str):
    """Return (allowed, matched_rule_str or None). Longest pattern wins; Allow wins ties."""
    if group is None or not group.rules:
        return True, None
    if not path:
        path = "/"
    p = _norm(path)
    best = None  # (len, allow, pattern)
    for allow, pattern in group.rules:
        pat = pattern if pattern.startswith(("/", "*")) else "/" + pattern
        gp, anchored = _prep(pat)
        if _glob_prefix(gp, p, anchored):
            ln = len(pattern)
            if best is None or ln > best[0] or (ln == best[0] and allow and not best[1]):
                best = (ln, allow, pattern)
    if best is None:
        return True, None
    return best[1], f"{'Allow' if best[1] else 'Disallow'}: {best[2]}"


def path_of(url: str) -> str:
    sp = urlsplit(url)
    path = sp.path or "/"
    if sp.query:
        path += "?" + sp.query
    return path


def evaluate(robots_text: Optional[str], url_or_path: str, ua_products=OUR_UA_PRODUCTS):
    """Pure helper (used by the audit): (allowed, rule, crawl_delay, agent_group)."""
    if robots_text is None:
        return True, None, None, None
    rb = parse_robots(robots_text)
    g = rb.select(ua_products)
    path = path_of(url_or_path) if "://" in url_or_path else url_or_path
    if path in ("/robots.txt",):
        return True, None, (g.crawl_delay if g else None), (g.agents[0] if g else None)
    ok, rule = match_rule(g, path)
    return ok, rule, (g.crawl_delay if g else None), (g.agents[0] if g else None)


# ---------------------------------------------------------------- runtime

@dataclass
class HostState:
    origin: str
    status: str            # ok | missing | unavailable
    http_status: int = 0
    robots: Optional[Robots] = None
    group: Optional[Group] = None
    crawl_delay: float = 0.0
    snapshot: str = ""
    fetched_at: str = ""
    error: str = ""


@dataclass
class Decision:
    allowed: bool
    url: str
    host: str
    reason: str            # allowed | disallowed | robots_unavailable
    rule: Optional[str] = None
    agent: Optional[str] = None
    crawl_delay: float = 0.0
    robots_status: str = ""
    robots_http_status: int = 0
    snapshot: str = ""
    robots_fetched_at: str = ""
    origin_url: str = ""   # archive copies: the original URL whose origin robots.txt was checked
    robots_source: str = ""  # "cached" when the origin decision came from a persisted snapshot


_lock = threading.RLock()
_host_locks: dict = {}
_cache: dict = {}            # origin -> HostState
_last_req: dict = {}         # host -> monotonic time of last request (THE shared per-host clock)
_tls = threading.local()     # per-thread pre-flight grant: (host, path, clock stamp)
_country: Optional[str] = None
_robots_fetcher: Optional[Callable] = None  # test hook: fn(robots_url) -> (status, text)


def set_country(cc: Optional[str]) -> None:
    global _country
    _country = (cc or "").strip().lower() or None


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def country() -> str:
    if _country:
        return _country
    for k in ("ROBOTS_COUNTRY", "COLLECTOR_CC", "COUNTRY_CC", "CC"):
        v = (os.environ.get(k) or "").strip().lower()
        if re.fullmatch(r"[a-z]{2}", v):
            return v
    m = re.search(r"(?:collect|fill|densify|expand|fix)_([a-z]{2})(?:_|\.py|$)", os.path.basename(sys.argv[0] if sys.argv else ""))
    if m and (ROOT / m.group(1)).is_dir():
        return m.group(1)
    m = re.match(r"^_([a-z]{2})_", os.path.basename(sys.argv[0] if sys.argv else ""))
    if m and (ROOT / m.group(1)).is_dir():
        return m.group(1)
    return "_shared"


def _logdir() -> Path:
    cc = country()
    return (ROOT / "logs") if cc == "_shared" else (ROOT / cc / "logs")


def _append_jsonl(path: Path, row: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _default_fetch(robots_url: str):
    """Returns (http_status, text, error). Uses a plain session (never guarded)."""
    import requests
    note = ""
    try:
        try:
            r = requests.get(robots_url, timeout=ROBOTS_TIMEOUT, allow_redirects=True,
                             headers={"User-Agent": ROBOTS_UA, "Accept": "text/plain,*/*"}, stream=True)
        except requests.exceptions.SSLError:
            # Broken/unknown CA chains are common on gov hosts (collectors use verify=False);
            # robots.txt is public, so read it unverified rather than fail closed on TLS alone.
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            r = requests.get(robots_url, timeout=ROBOTS_TIMEOUT, allow_redirects=True, verify=False,
                             headers={"User-Agent": ROBOTS_UA, "Accept": "text/plain,*/*"}, stream=True)
            note = "tls_unverified"
        raw = b""
        for chunk in r.iter_content(65536):
            raw += chunk
            if len(raw) >= MAX_ROBOTS_BYTES:
                break
        r.close()
        raw = raw[:MAX_ROBOTS_BYTES]
        try:  # RFC 9309: robots.txt is UTF-8 (strip a BOM)
            txt = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            txt = raw.decode(r.encoding or "latin-1", "replace")
        return r.status_code, txt, note
    except Exception as exc:  # timeout, DNS, TLS, reset ...
        return 0, "", f"{type(exc).__name__}: {exc}"[:300]


_CHALLENGE = re.compile(r"just a moment|cf-browser-verification|challenge-platform|captcha|awswaf|"
                        r"checking your browser|enable javascript|request rejected|access denied", re.I)


def _load_host(origin: str, host: str) -> HostState:
    with _lock:
        st = _cache.get(origin)
        if st is not None:
            return st
        hl = _host_locks.setdefault(origin, threading.Lock())
    with hl:
        with _lock:
            st = _cache.get(origin)
            if st is not None:
                return st
        robots_url = origin + "/robots.txt"
        fetch = _robots_fetcher or _default_fetch
        code, text, err = fetch(robots_url)
        now = _utc_iso()
        looks_html = bool(re.search(r"<\s*(html|!doctype)", (text or "")[:600], re.I))
        if code == 200 and not looks_html:
            rb = parse_robots(text)
            g = rb.select()
            st = HostState(origin, "ok", code, rb, g, float(g.crawl_delay or 0) if g else 0.0, fetched_at=now, error=err)
        elif code == 200 and looks_html and _CHALLENGE.search((text or "")[:4000]):
            st = HostState(origin, "unavailable", code, fetched_at=now, error="waf_challenge_page")
        elif code == 200 and looks_html:
            st = HostState(origin, "missing", code, fetched_at=now, error="html_body_treated_as_no_rules")
        elif code in (401, 403, 429) or code >= 500 or code == 0 or (200 < code < 300):
            st = HostState(origin, "unavailable", code, fetched_at=now, error=err or f"http_{code}")
        else:  # 404, 410, other 4xx/3xx-without-target: no rules -> allow
            st = HostState(origin, "missing", code, fetched_at=now, error=f"http_{code}" + (f";{err}" if err else ""))
        # dated snapshot (also for missing/unavailable, so the decision is auditable)
        day = now[:10]
        safe_host = re.sub(r"[^A-Za-z0-9.-]+", "_", host)
        snap = _logdir() / "robots" / f"{safe_host}_{day}.txt"
        try:
            snap.parent.mkdir(parents=True, exist_ok=True)
            body = text if st.status == "ok" else f"# robots.txt {robots_url} status={st.status} http={code} {st.error}\n"
            prev = snap.read_text(encoding="utf-8", errors="replace") if snap.exists() else None
            if prev != body:
                snap.write_text(body, encoding="utf-8")
            st.snapshot = str(snap.relative_to(ROOT))
        except Exception:
            pass
        _append_jsonl(_logdir() / "robots" / "robots_snapshots.jsonl", {
            "fetched_at": now, "country": country(), "host": host, "robots_url": robots_url,
            "http_status": code, "status": st.status, "error": st.error or None,
            "sha256": hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest() if st.status == "ok" else None,
            "bytes": len(text or ""), "agent_group": (st.group.agents[0] if st.group else None),
            "crawl_delay": st.crawl_delay or None, "snapshot": st.snapshot,
        })
        if st.status in ("ok", "missing"):
            _save_persisted_snapshot(origin, host, st, text, robots_url)
        with _lock:
            _cache[origin] = st
        return st


CACHED_MAX_AGE_S = 7 * 24 * 3600


def _persist_dir() -> Path:
    return ROOT / "logs" / "robots_snapshots"


def _persist_path(host: str) -> Path:
    return _persist_dir() / (re.sub(r"[^A-Za-z0-9.-]+", "_", host or "_") + ".json")


def _save_persisted_snapshot(origin: str, host: str, st: "HostState", text: str, robots_url: str) -> None:
    """Successful robots.txt read only (status ok / missing): write <host>.json atomically."""
    try:
        p = _persist_path(host)
        p.parent.mkdir(parents=True, exist_ok=True)
        row = {"host": host, "origin": origin, "robots_url": robots_url, "fetched_at": st.fetched_at,
               "status": st.status, "http_status": st.http_status,
               "body": (text or "") if st.status == "ok" else "",
               "sha256": hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest() if st.status == "ok" else None}
        tmp = p.with_name(p.name + f".tmp{os.getpid()}_{threading.get_ident()}")
        tmp.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


def load_persisted_snapshot(host: str) -> Optional[dict]:
    try:
        return json.loads(_persist_path(host).read_text(encoding="utf-8"))
    except Exception:
        return None


def _snapshot_age_s(snap: dict) -> Optional[float]:
    try:
        t = datetime.fromisoformat(str(snap.get("fetched_at")).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()
    except Exception:
        return None


def _cached_origin_decision(original_url: str, od: "Decision") -> Optional["Decision"]:
    """Origin robots.txt unreadable now: decide from a persisted snapshot <= 7 days old, else None."""
    snap = load_persisted_snapshot(od.host)
    if not snap or snap.get("status") not in ("ok", "missing"):
        return None
    age = _snapshot_age_s(snap)
    if age is None or age < -300 or age > CACHED_MAX_AGE_S:
        return None
    base = dict(url=original_url, host=od.host, robots_status="cached", robots_http_status=int(snap.get("http_status") or 0),
                snapshot=str(_persist_path(od.host).relative_to(ROOT)) if str(_persist_path(od.host)).startswith(str(ROOT)) else str(_persist_path(od.host)),
                robots_fetched_at=str(snap.get("fetched_at") or ""), robots_source="cached")
    if snap.get("status") == "missing" or urlsplit(original_url).path == "/robots.txt":
        return Decision(True, reason="allowed", rule="cached: no rules", **base)
    g = parse_robots(snap.get("body") or "").select()
    ok, rule = match_rule(g, path_of(original_url))
    return Decision(ok, reason="allowed" if ok else "disallowed", rule=f"cached {snap.get('fetched_at')}: {rule}",
                    agent=(g.agents[0] if g else None), crawl_delay=float(g.crawl_delay or 0) if g else 0.0, **base)


def _log_robots_cached(original_url: str, archive_url: str, cd: "Decision", live: "Decision") -> None:
    row = {"ts": _utc_iso(), "country": country(), "event": "robots_cached", "status": "robots_cached",
           "host": cd.host, "url": archive_url, "origin_url": original_url, "allowed": cd.allowed,
           "rule": cd.rule, "snapshot": cd.snapshot, "snapshot_fetched_at": cd.robots_fetched_at,
           "live_robots_error": live.rule}
    _append_jsonl(_logdir() / "robots_cached.jsonl", row)
    try:
        import logging
        logging.getLogger("robots_guard").warning("robots_cached %s %s via snapshot %s (live robots.txt: %s)",
                                                  "allow" if cd.allowed else "disallow", original_url, cd.robots_fetched_at, live.rule)
    except Exception:
        pass


def check(url: str) -> Decision:
    """Decide without waiting or raising (does fetch robots.txt on first use)."""
    sp = urlsplit(url)
    scheme = (sp.scheme or "http").lower()
    host = (sp.hostname or "").lower()
    if scheme not in ("http", "https") or not host:
        return Decision(False, url, host, "robots_unavailable", rule="unsupported_url")
    origin = f"{scheme}://{sp.netloc.lower()}"
    st = _load_host(origin, host)
    base = dict(url=url, host=host, crawl_delay=st.crawl_delay, robots_status=st.status,
                robots_http_status=st.http_status, snapshot=st.snapshot, robots_fetched_at=st.fetched_at)
    if sp.path == "/robots.txt":
        return Decision(True, reason="allowed", **base)
    if st.status == "unavailable":
        return Decision(False, reason="robots_unavailable", rule=st.error, **base)
    if st.status == "missing":
        d = Decision(True, reason="allowed", **base)
    else:
        ok, rule = match_rule(st.group, path_of(url))
        d = Decision(ok, reason="allowed" if ok else "disallowed", rule=rule,
                     agent=(st.group.agents[0] if st.group else None), **base)
    if d.allowed:
        orig = archived_original(url)
        if orig:
            return check_archived_copy(orig, url, _archive_decision=d)
    return d


# Archive replay URLs that serve a COPY of <orig> (not discovery listings such as /web/*/...).
_REPLAY_RES = (
    re.compile(r"^https?://(?:web|wayback)\.archive\.org/web/\d{1,14}(?:[a-z]{2}_)?/+(?P<orig>.+)$", re.I | re.S),
    re.compile(r"^https?://(?:www\.)?archive\.(?:is|ph|today|li|vn|fo|md)/(?:newest|oldest|timegate|\d{4,14})/+(?P<orig>.+)$",
               re.I | re.S),
)


def archived_original(url: str) -> Optional[str]:
    """The original URL inside an archive replay URL (Wayback /web/<ts>[mod_]/<orig>,
    archive.is|ph /newest|<ts>/<orig>), else None. Scheme-less originals get http://."""
    for rx in _REPLAY_RES:
        m = rx.match(url or "")
        if not m:
            continue
        orig = m.group("orig").strip()
        orig = re.sub(r"^(https?):/+", lambda mm: mm.group(1).lower() + "://", orig, flags=re.I)
        if not re.match(r"^https?://", orig, re.I):
            if re.match(r"^[a-z][a-z0-9+.-]*:", orig, re.I) and not re.match(r"^[^/:]+:\d+(/|$)", orig):
                return None  # non-http original (mailto:, ftp:, ...): nothing to check
            orig = "http://" + orig.lstrip("/")
        return orig
    return None


def check_archived_copy(original_url: str, archive_url: str = "", _archive_decision: Optional[Decision] = None) -> Decision:
    """May an archive copy of original_url be fetched? Checks the ORIGIN's robots.txt for
    original_url (fail closed). Returns the archive decision (or an allow) when the origin
    allows; else a refusing Decision with reason origin_disallow / origin_robots_unavailable."""
    od = check(original_url)
    if not od.allowed and od.reason == "robots_unavailable":
        cd = _cached_origin_decision(original_url, od)  # robots_cached carve-out (archive copies only)
        if cd is not None:
            _log_robots_cached(original_url, archive_url or original_url, cd, od)
            od = cd
    a = _archive_decision
    if a is None:
        sp = urlsplit(archive_url or original_url)
        a = Decision(True, archive_url or original_url, (sp.hostname or "").lower(), "allowed")
    if od.allowed:
        if not a.origin_url:
            a.origin_url = original_url
        if od.robots_source:
            a.robots_source = od.robots_source
        return a
    reason = "origin_robots_unavailable" if od.reason in ("robots_unavailable", "origin_robots_unavailable") else "origin_disallow"
    return Decision(False, a.url, a.host, reason, rule=f"origin {od.host}: {od.reason} ({od.rule})",
                    agent=od.agent, crawl_delay=a.crawl_delay, robots_status=od.robots_status,
                    robots_http_status=od.robots_http_status, snapshot=od.snapshot,
                    robots_fetched_at=od.robots_fetched_at, origin_url=original_url, robots_source=od.robots_source)


def _clock(url: str, min_interval: float, send: bool) -> float:
    """The shared per-host clock. Sleeps until max(Crawl-delay, min_interval) has passed since
    the last request to this host, then stamps the clock. Returns the seconds slept.

    send=False (pre-flight: guard()/wait()): also leaves a one-shot grant for this thread.
    send=True  (the actual send: GuardedSession, guarded_* wrappers, gated sessions in
    common/archive_fallbacks): if this thread holds a grant for the same host+path and no
    other request to that host was stamped since, the grant is used instead of waiting again
    (the wait already happened in the pre-flight); the clock is re-stamped at send time.
    Any send clears the thread's grant, so retries / redirect hops / later requests wait."""
    sp = urlsplit(url)
    host = (sp.hostname or "").lower()
    path = sp.path or "/"
    origin = f"{(sp.scheme or 'http').lower()}://{sp.netloc.lower()}"
    st = _cache.get(origin)
    gap = max(float(min_interval or 0), st.crawl_delay if st else 0.0)
    with _lock:
        hl = _host_locks.setdefault("wait:" + host, threading.Lock())
    slept = 0.0
    with hl:  # serialises same-host requests across threads
        if send:
            g = getattr(_tls, "grant", None)
            _tls.grant = None
            if g is not None and g[0] == host and g[1] == path and _last_req.get(host) == g[2]:
                _last_req[host] = time.monotonic()
                return 0.0
        if gap > 0:
            last = _last_req.get(host)
            if last is not None:
                delta = gap - (time.monotonic() - last)
                if delta > 0:
                    time.sleep(delta)
                    slept = delta
        now = time.monotonic()
        _last_req[host] = now
        if not send:
            _tls.grant = (host, path, now)
    return slept


def wait(url: str, min_interval: float = 0.0) -> None:
    """Pre-flight: sleep so requests to this host are >= max(Crawl-delay, min_interval) apart
    (shared per-host clock). The gated send of the same request will not wait again."""
    _clock(url, min_interval, send=False)


def wait_send(url: str, min_interval: float = 0.0) -> float:
    """Send gate: wait on the shared per-host clock unless this thread's pre-flight
    guard()/wait() already waited for this request. Returns the seconds slept."""
    return _clock(url, min_interval, send=True)


_blocked_urls: set = set()   # URLs refused by the guard in this process


def report_blocked(d: Decision, caller: str = "") -> None:
    with _lock:
        _blocked_urls.add(d.url)
    row = {"ts": _utc_iso(), "country": country(), "event": "guard_refused", "status": "robots_blocked",
           "host": d.host, "url": d.url,
           "reason": d.reason, "rule": d.rule, "agent_group": d.agent,
           "robots_status": d.robots_status, "robots_http_status": d.robots_http_status,
           "robots_snapshot": d.snapshot, "robots_fetched_at": d.robots_fetched_at,
           "caller": caller or None}
    if getattr(d, "origin_url", ""):
        row["origin_url"] = d.origin_url
    if getattr(d, "robots_source", ""):
        row["robots_source"] = d.robots_source
    _append_jsonl(_logdir() / "robots_blocked.jsonl", row)


def guard(url: str, *, min_interval: float = 0.0, caller: str = "") -> Decision:
    """Call immediately before every request. Raises RobotsBlocked instead of fetching."""
    d = check(url)
    if not d.allowed:
        report_blocked(d, caller)
        exc = RobotsUnavailable if d.reason in ("robots_unavailable", "origin_robots_unavailable") else RobotsDisallowed
        raise exc(f"robots guard: {d.reason} {url} ({d.rule})", d)
    wait(url, min_interval)
    return d


def guard_send(url: str, *, min_interval: float = 0.0, caller: str = "") -> Decision:
    """guard() for the code that actually sends the request (sessions, wrappers): same
    robots decision, but uses a pre-flight guard()'s wait instead of waiting twice."""
    d = check(url)
    if not d.allowed:
        report_blocked(d, caller)
        exc = RobotsUnavailable if d.reason in ("robots_unavailable", "origin_robots_unavailable") else RobotsDisallowed
        raise exc(f"robots guard: {d.reason} {url} ({d.rule})", d)
    wait_send(url, min_interval)
    return d


def log_robots_blocked(exc_or_url, caller: str = "", **extra) -> dict:
    """For a script's `except robots_guard.RobotsBlocked` branch: record the URL as
    robots_blocked (NOT a fetch failure) in <cc>/logs/robots_blocked.jsonl and return the row.

    The guard has already written an event="guard_refused" row when it raised; this adds an
    event="script_skipped" row naming the script/function that skipped the URL.
    """
    d = getattr(exc_or_url, "decision", None)
    url = d.url if d is not None else str(exc_or_url)
    host = d.host if d is not None else (urlsplit(url).hostname or "").lower()
    row = {"ts": _utc_iso(), "country": country(), "event": "script_skipped", "status": "robots_blocked",
           "host": host, "url": url,
           "reason": d.reason if d is not None else "robots_blocked",
           "rule": d.rule if d is not None else None,
           "exception": type(exc_or_url).__name__ if isinstance(exc_or_url, BaseException) else None,
           "caller": caller or None}
    row.update({k: v for k, v in extra.items() if k not in row})
    with _lock:
        _blocked_urls.add(url)
    _append_jsonl(_logdir() / "robots_blocked.jsonl", row)
    return row


def was_blocked(url: str) -> bool:
    """True if the guard refused this exact URL earlier in this process."""
    return url in _blocked_urls


def reset_cache() -> None:
    with _lock:
        _cache.clear()
        _last_req.clear()
        _blocked_urls.clear()


try:
    import requests as _requests

    class GuardedSession(_requests.Session):
        """requests.Session whose every send() (each redirect hop too) passes guard()."""

        min_interval: float = 0.0

        def send(self, request, **kwargs):
            guard_send(request.url, min_interval=self.min_interval, caller="GuardedSession")
            return super().send(request, **kwargs)
except Exception:  # pragma: no cover - requests missing
    GuardedSession = None  # type: ignore


# ---------------------------------------------------------------- drop-in wrappers for our scripts
# (CoS ruling R1 2026-10-01: our own collector scripts call these instead of requests/urllib/curl directly)

def guarded_request(method: str, url: str, **kwargs):
    """Drop-in for requests.request(): fresh GuardedSession per call (like requests.api), every hop guarded."""
    with GuardedSession() as s:
        return s.request(method=method, url=url, **kwargs)


def guarded_get(url: str, params=None, **kwargs):
    """Drop-in for requests.get()."""
    return guarded_request("GET", url, params=params, **kwargs)


def guarded_head(url: str, **kwargs):
    """Drop-in for requests.head() (allow_redirects defaults to False, as in requests)."""
    kwargs.setdefault("allow_redirects", False)
    return guarded_request("HEAD", url, **kwargs)


def guarded_post(url: str, data=None, json=None, **kwargs):
    """Drop-in for requests.post()."""
    return guarded_request("POST", url, data=data, json=json, **kwargs)


import socket as _socket  # noqa: E402
import urllib.request as _urlreq  # noqa: E402


class _GuardedRedirectHandler(_urlreq.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        guard_send(newurl, caller="guarded_urlopen(redirect)")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def guarded_urlopen(url, data=None, timeout=_socket._GLOBAL_DEFAULT_TIMEOUT, *, context=None):
    """Drop-in for urllib.request.urlopen(): guards the URL and every redirect hop."""
    target = url.full_url if isinstance(url, _urlreq.Request) else str(url)
    guard_send(target, caller="guarded_urlopen")
    handlers = [_GuardedRedirectHandler()]
    if context is not None:
        handlers.append(_urlreq.HTTPSHandler(context=context))
    return _urlreq.build_opener(*handlers).open(url, data, timeout)


# ---- curl / wget
# curl short options that take an argument (the rest of the word, or the next word).
_CURL_SHORT_ARG = set("AbcCdDeEFHKmoPQrtTuUwxXyYz")
# curl long options that take an argument (anything else is treated as a flag).
_CURL_LONG_ARG = {
    "--url", "--user-agent", "--referer", "--header", "--proxy-header", "--output", "--output-dir",
    "--data", "--data-ascii", "--data-binary", "--data-raw", "--data-urlencode", "--json", "--form",
    "--form-string", "--cookie", "--cookie-jar", "--max-time", "--connect-timeout", "--retry",
    "--retry-delay", "--retry-max-time", "--request", "--proxy", "--proxy-user", "--preproxy",
    "--noproxy", "--cacert", "--capath", "--cert", "--cert-type", "--key", "--key-type", "--pass",
    "--range", "--write-out", "--dump-header", "--max-filesize", "--limit-rate", "--resolve",
    "--connect-to", "--interface", "--user", "--config", "--time-cond", "--upload-file",
    "--max-redirs", "--speed-limit", "--speed-time", "--expect100-timeout", "--keepalive-time",
    "--ciphers", "--variable", "--trace", "--trace-ascii", "--stderr", "--proto", "--proto-redir",
    "--pinnedpubkey", "--dns-servers", "--local-port", "--oauth2-bearer", "--quote", "--etag-save",
    "--etag-compare", "--happy-eyeballs-timeout-ms", "--unix-socket", "--abstract-unix-socket",
    "--aws-sigv4", "--hsts", "--alt-svc", "--continue-at", "--create-file-mode", "--rate",
    "--parallel-max", "--mail-from", "--mail-rcpt", "--login-options", "--sasl-authzid",
}
_CURL_LOCATION = {"-L", "--location", "--location-trusted"}
MAX_CURL_HOPS = 10
_curl_runner: Optional[Callable] = None  # test hook: fn(argv, **kwargs) -> CompletedProcess


def _is_curl(args) -> bool:
    return bool(args) and os.path.basename(str(args[0])) in ("curl", "curl.exe")


def _curl_parse(args):
    """Sanitise a curl argv: drop -L/--location(-trusted) (also inside combined short flags such
    as -sfL) and any --max-redirs N, then append --max-redirs 0.
    Returns (new_args, had_location, url_positions_in_new_args, dump_header_path_or_None)."""
    out = [args[0]]
    urls = []
    had_loc = False
    dump = None
    i = 1
    n = len(args)
    while i < n:
        a = args[i]
        if a in _CURL_LOCATION:
            had_loc = True
            i += 1
            continue
        if a == "--max-redirs":
            i += 2
            continue
        if a.startswith("--"):
            if a in _CURL_LONG_ARG and i + 1 < n:
                if a == "--url":
                    urls.append(len(out) + 1)
                if a == "--dump-header":
                    dump = args[i + 1]
                out += [a, args[i + 1]]
                i += 2
                continue
            out.append(a)
            i += 1
            continue
        if a.startswith("-") and len(a) > 1:
            kept = "-"
            takes_next = False
            j = 1
            while j < len(a):
                c = a[j]
                if c == "L":
                    had_loc = True
                    j += 1
                    continue
                kept += c
                if c in _CURL_SHORT_ARG:
                    rest = a[j + 1:]
                    if rest:
                        kept += rest
                        if c == "D":
                            dump = rest
                    else:
                        takes_next = True
                        if c == "D" and i + 1 < n:
                            dump = args[i + 1]
                    break
                j += 1
            if kept != "-":
                out.append(kept)
            if takes_next and i + 1 < n:
                out.append(args[i + 1])
                i += 2
            else:
                i += 1
            continue
        if re.match(r"^https?://", a, re.I):
            urls.append(len(out))
        out.append(a)
        i += 1
    out += ["--max-redirs", "0"]
    return out, had_loc, urls, dump


def curl_precheck(argv):
    """Guard every http(s) URL a curl/wget argv would fetch BEFORE running it (raises RobotsBlocked).

    For curl it also returns a SANITISED argv: -L/--location is stripped and --max-redirs 0 is
    appended, so curl itself never follows a redirect. Run the returned argv, or use
    guarded_curl_run(), which follows redirects itself and guards every hop (Crawl-delay too).
    """
    as_str = isinstance(argv, str)
    import shlex
    args = shlex.split(argv) if as_str else [str(a) for a in argv]
    if _is_curl(args):
        new, _had_loc, urls, _dump = _curl_parse(args)
        for k in urls:
            guard(new[k], caller="curl_precheck(curl)")
        return shlex.join(new) if as_str else new
    for a in args[1:]:  # wget etc.: guard URL arguments (no redirect rewriting)
        if re.match(r"^https?://", a, re.I):
            guard(a, caller=f"curl_precheck({os.path.basename(args[0])})")
    return argv


def _last_header_block(text: str):
    """(status, headers-dict-lowercase) of the final HTTP response block in a curl -D dump."""
    blocks = [b for b in re.split(r"\r?\n\r?\n", text or "") if b.strip()]
    for b in reversed(blocks):
        lines = b.strip().splitlines()
        m = re.match(r"^HTTP/\S+\s+(\d{3})", lines[0].strip())
        if not m:
            continue
        hdrs = {}
        for ln in lines[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                hdrs[k.strip().lower()] = v.strip()
        return int(m.group(1)), hdrs
    return 0, {}


def guarded_curl_run(argv, *args, **kwargs):
    """subprocess.run() for a curl/wget argv, robots-guarded.

    curl: -L/--location is stripped and --max-redirs 0 added, so curl never follows a redirect
    on its own. If the caller asked for -L, the wrapper follows the redirect itself: it reads
    the Location header (curl -D dump), resolves relative URLs, guard()s every hop (robots rules
    AND Crawl-delay), and re-runs curl for that hop, up to MAX_CURL_HOPS (10) hops. A disallowed
    hop raises RobotsBlocked (logged to <cc>/logs/robots_blocked.jsonl) and is never requested.
    More than 10 hops gives returncode 47 (curl's "too many redirects").
    """
    import shlex
    import subprocess
    import tempfile
    from urllib.parse import urljoin
    runner = _curl_runner or subprocess.run
    shell_str = isinstance(argv, str)
    base = shlex.split(argv) if shell_str else [str(a) for a in argv]
    if not _is_curl(base):
        curl_precheck(argv)
        return runner(argv, *args, **kwargs)
    new, had_loc, urls, user_dump = _curl_parse(base)
    for k in urls:
        guard_send(new[k], caller="guarded_curl_run(curl)")
    if not had_loc or len(urls) != 1 or user_dump == "-":
        # no -L requested (curl would not have followed either), or several URLs / headers to
        # stdout (-D -): run once with redirects disabled; a 3xx is returned to the caller as is.
        cmd = shlex.join(new) if shell_str else new
        return runner(cmd, *args, **kwargs)
    pos = urls[0]
    tmp = None
    if user_dump is None:
        fd, tmp = tempfile.mkstemp(prefix="rg_curl_hdr_", suffix=".txt")
        os.close(fd)
        new = new[:-2] + ["-D", tmp] + new[-2:]
        dump = tmp
    else:
        dump = user_dump
    try:
        current = new[pos]
        for hop in range(MAX_CURL_HOPS + 1):
            cmd = list(new)
            cmd[pos] = current
            try:
                open(dump, "w").close()
            except Exception:
                pass
            res = runner(shlex.join(cmd) if shell_str else cmd, *args, **kwargs)
            try:
                hdr_text = open(dump, encoding="latin-1").read()
            except Exception:
                hdr_text = ""
            status, hdrs = _last_header_block(hdr_text)
            loc = hdrs.get("location")
            if status not in (301, 302, 303, 307, 308) or not loc:
                return res
            if hop == MAX_CURL_HOPS:
                break
            nxt = urljoin(current, loc)
            guard_send(nxt, caller=f"guarded_curl_run(redirect hop {hop + 1})")  # robots + Crawl-delay
            current = nxt
        msg = f"guarded_curl_run: more than {MAX_CURL_HOPS} redirects ({current})\n"
        err = res.stderr
        if isinstance(err, bytes):
            err = err + msg.encode()
        elif isinstance(err, str):
            err = err + msg
        return subprocess.CompletedProcess(res.args, 47, res.stdout, err)
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except Exception:
                pass


__all__ = [
    "RobotsBlocked", "RobotsDisallowed", "RobotsUnavailable", "Decision",
    "parse_robots", "match_rule", "evaluate", "check", "guard", "wait", "guard_send", "wait_send",
    "archived_original", "check_archived_copy", "load_persisted_snapshot", "CACHED_MAX_AGE_S",
    "set_country", "country", "report_blocked", "GuardedSession", "reset_cache",
    "guarded_request", "guarded_get", "guarded_head", "guarded_post", "guarded_urlopen",
    "curl_precheck", "guarded_curl_run", "log_robots_blocked", "was_blocked", "MAX_CURL_HOPS",
]
