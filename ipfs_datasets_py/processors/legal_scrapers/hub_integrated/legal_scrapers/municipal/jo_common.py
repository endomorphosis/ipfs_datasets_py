"""Polite HTTP + resource guard for the Jordan (JO) municipal collectors (adapted from za_common.py).

- robots.txt ('User-agent: *' group, '*'/'$' wildcards, longest match wins) checked on every URL and on the final URL after
  redirects; Crawl-delay honoured (per-host delay = max(JO_MIN_DELAY, crawl-delay)); robots.txt unreadable (network/TLS
  error, 5xx) -> host not crawled (fail closed). 404 robots -> no rules (allow all). Status recorded per host.
- TLS always verified (certifi, or a host-only CA bundle at <JO_CA_DIR>/<host>.pem). Never verify=False. A host that
  resets TLS / has a bad certificate is skipped (no archive copies are read for it).
- Backoff: HTTP 429/5xx and network errors are retried (3 tries, 30 s / 90 s / 270 s; Retry-After honoured).
- HTML bodies cached gzip under <JO_STATE>/cache; document bodies (PDF) are returned, not cached.
- Every request is appended to <JO_STATE>/logs/requests.jsonl.
- resource_ok(): MemAvailable >= 4.5 GiB and free bytes on / >= 32212254720 (30 GiB, exact bytes).
No secrets, no cookies kept across runs, no logins.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, re, time, json, gzip, hashlib, threading, urllib.parse, datetime
import requests, certifi

STATE = os.environ.get("JO_STATE", str(_CORPORA) + "/municipal/jo_build_state")
CA_DIR = os.environ.get("JO_CA_DIR", os.path.join(STATE, "ca"))
MIN_DELAY = float(os.environ.get("JO_MIN_DELAY", "2"))
UA = "EndomorphosisWorldLaws-municipal/1.0 (research; legal translation corpus; polite crawler; robots.txt honoured)"
MIN_MEM_BYTES = int(4.5 * 1024 ** 3)
MIN_DISK_BYTES = 32212254720


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mem_bytes():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable:"):
            return int(l.split()[1]) * 1024
    return 0


def disk_bytes(path="/"):
    s = os.statvfs(path)
    return s.f_bavail * s.f_frsize


def resource_ok():
    return mem_bytes() >= MIN_MEM_BYTES and disk_bytes("/") >= MIN_DISK_BYTES


def resource_str():
    return f"mem={mem_bytes()/1024**3:.2f}GiB disk_free={disk_bytes('/')}B"


class ResourcePause(Exception):
    pass


def parse_robots(txt):
    rules, delay, agents, in_rules = [], None, [], False
    for raw in txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            if in_rules:
                agents, in_rules = [], False
            agents.append(v.lower())
        elif k in ("allow", "disallow", "crawl-delay"):
            in_rules = True
            if "*" not in agents:
                continue
            if k == "crawl-delay":
                try:
                    delay = float(v)
                except ValueError:
                    pass
            elif v:
                rules.append((k == "allow", v))
    return rules, delay


def robots_allows(rules, path):
    best = None
    for allow, p in rules:
        anchored = p.endswith("$")
        core = p[:-1] if anchored else p
        rx = "^" + re.escape(core).replace(r"\*", ".*") + ("$" if anchored else "")
        if re.match(rx, path):
            key = (len(p), allow)
            if best is None or key > best[0]:
                best = (key, allow)
    return True if best is None else best[1]


def _gz_w(fn, b):
    with open(fn + ".tmp", "wb") as f:
        f.write(gzip.compress(b, 6))
    os.replace(fn + ".tmp", fn)


class Polite:
    def __init__(self, state=STATE, min_delay=MIN_DELAY):
        self.state = state
        self.cache = os.path.join(state, "cache")
        os.makedirs(self.cache, exist_ok=True)
        os.makedirs(os.path.join(state, "logs"), exist_ok=True)
        self.reqlog = os.path.join(state, "logs", "requests.jsonl")
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.s.headers["Accept-Language"] = "ar,en;q=0.5"
        self.min_delay = min_delay
        self.robots, self.robots_raw, self.robots_note, self.last = {}, {}, {}, {}
        self.lock = threading.Lock()

    def ca_for(self, host):
        p = os.path.join(CA_DIR, host + ".pem")
        return p if os.path.exists(p) else certifi.where()

    def _log(self, **kw):
        kw["t"] = now_utc()
        with open(self.reqlog, "a") as f:
            f.write(json.dumps(kw, ensure_ascii=False) + "\n")

    def _wait(self, host, delay):
        while True:
            with self.lock:
                t = time.time()
                nxt = self.last.get(host, 0) + delay
                if t >= nxt:
                    self.last[host] = t
                    return
            time.sleep(nxt - t)

    def host_delay(self, base):
        r = self.robots.get(base)
        d = r[1] if r and r[1] else 0
        return max(self.min_delay, d)

    def _robots(self, base):
        if base in self.robots:
            return self.robots[base]
        host = urllib.parse.urlsplit(base).netloc
        fn = os.path.join(self.cache, "robots_" + re.sub(r"[^a-z0-9.]+", "_", base.lower()) + ".json")
        if os.path.exists(fn):
            d = json.load(open(fn))
            if time.time() - d["ts"] < 86400:
                self.robots[base] = None if d["blocked"] else (d["rules"], d["delay"])
                self.robots_raw[base] = d.get("raw", ""); self.robots_note[base] = d.get("note", "")
                return self.robots[base]
        self._wait(host, self.min_delay)
        res, raw, note = None, "", ""
        try:
            r = self.s.get(base + "/robots.txt", timeout=40, verify=self.ca_for(host), allow_redirects=True)
            self._log(url=base + "/robots.txt", status=r.status_code, kind="robots")
            if r.status_code == 200 and "<html" not in r.text[:500].lower():
                raw = r.text; res = parse_robots(raw); note = "robots 200"
            elif r.status_code in (404, 410) or r.status_code == 200:
                res = ([], None); note = f"robots {r.status_code} (no robots.txt; no rules)"
            else:
                note = f"robots status {r.status_code} (fail closed)"
        except requests.RequestException as e:
            note = f"robots error {type(e).__name__}: {str(e)[:200]} (fail closed)"
            self._log(url=base + "/robots.txt", status=-1, kind="robots", error=note)
        self.robots[base] = res; self.robots_raw[base] = raw; self.robots_note[base] = note
        json.dump(dict(ts=time.time(), checked_at=now_utc(), blocked=res is None, rules=res[0] if res else None,
                       delay=res[1] if res else None, raw=raw[:20000], note=note), open(fn, "w"), ensure_ascii=False)
        return res

    def robots_status(self, base):
        self._robots(base)
        return {"base": base, "note": self.robots_note.get(base, ""), "raw": self.robots_raw.get(base, "")[:4000],
                "crawlable": self.robots.get(base) is not None}

    def allowed(self, url):
        u = urllib.parse.urlsplit(url)
        base = f"{u.scheme}://{u.netloc}"
        rr = self._robots(base)
        if rr is None:
            return False
        path = (u.path or "/") + (("?" + u.query) if u.query else "")
        return robots_allows(rr[0], path) and robots_allows(rr[0], urllib.parse.unquote(path))

    def post(self, url, data, *, timeout=120, tries=3):
        """ASP.NET pagination POST-back (same robots / delay / backoff rules; never cached)."""
        if not self.allowed(url):
            return None
        u = urllib.parse.urlsplit(url); base = f"{u.scheme}://{u.netloc}"; backoff = 30
        for attempt in range(tries):
            if not resource_ok():
                raise ResourcePause(resource_str())
            self._wait(u.netloc, self.host_delay(base))
            try:
                r = self.s.post(url, data=data, timeout=timeout, allow_redirects=True, verify=self.ca_for(u.netloc))
            except requests.RequestException as e:
                self._log(url=url, method="POST", status=-1, error=f"{type(e).__name__}: {str(e)[:200]}")
                if attempt + 1 < tries:
                    time.sleep(backoff); backoff *= 3; continue
                return dict(status=-1, url=url, body=b"", ctype="error", retrieved_at=now_utc())
            self._log(url=url, method="POST", status=r.status_code, length=len(r.content))
            if (r.status_code == 429 or r.status_code >= 500) and attempt + 1 < tries:
                time.sleep(backoff); backoff *= 3; continue
            return dict(status=r.status_code, url=r.url, body=r.content, ctype=r.headers.get("content-type", ""),
                        retrieved_at=now_utc())

    def get(self, url, *, doc=False, timeout=120, max_bytes=120_000_000, use_cache=True, tries=3):
        """-> dict(status, url, ctype, body, cached, retrieved_at) ; None when robots disallows / host blocked."""
        key = hashlib.sha1(url.encode()).hexdigest()
        fn = os.path.join(self.cache, key[:2], key)
        if use_cache and os.path.exists(fn + ".json"):
            meta = json.load(open(fn + ".json"))
            if os.path.exists(fn + ".gz") or meta.get("status") != 200:
                body = gzip.decompress(open(fn + ".gz", "rb").read()) if os.path.exists(fn + ".gz") else b""
                return dict(meta, body=body, cached=True)
        if not self.allowed(url):
            return None
        u = urllib.parse.urlsplit(url)
        base = f"{u.scheme}://{u.netloc}"
        backoff = 30
        for attempt in range(tries):
            if not resource_ok():
                raise ResourcePause(resource_str())
            self._wait(u.netloc, self.host_delay(base))
            try:
                r = self.s.get(url, timeout=timeout, stream=True, allow_redirects=True, verify=self.ca_for(u.netloc))
                if r.url != url and not self.allowed(r.url):
                    r.close(); self._log(url=url, final=r.url, status=r.status_code, kind="redirect-disallowed")
                    return None
                chunks, n = [], 0
                for ch in r.iter_content(65536):
                    chunks.append(ch); n += len(ch)
                    if n > max_bytes:
                        break
                body = b"".join(chunks)
                meta = dict(status=r.status_code, url=r.url, ctype=r.headers.get("content-type", ""),
                            cdisp=r.headers.get("content-disposition", ""), last_modified=r.headers.get("last-modified", ""),
                            truncated=n > max_bytes, retrieved_at=now_utc(), length=len(body))
            except requests.exceptions.SSLError as e:
                self._log(url=url, status=-1, error=f"SSLError: {str(e)[:200]}")
                return dict(status=-1, url=url, ctype="error:SSLError", body=b"", cached=False, error=str(e)[:300],
                            retrieved_at=now_utc())
            except requests.RequestException as e:
                self._log(url=url, status=-1, error=f"{type(e).__name__}: {str(e)[:200]}", attempt=attempt)
                if attempt + 1 < tries:
                    time.sleep(backoff); backoff *= 3; continue
                return dict(status=-1, url=url, ctype="error:" + type(e).__name__, body=b"", cached=False,
                            error=str(e)[:300], retrieved_at=now_utc())
            self._log(url=url, final=meta["url"], status=meta["status"], ctype=meta["ctype"], length=meta["length"],
                      attempt=attempt)
            if (meta["status"] == 429 or meta["status"] >= 500) and attempt + 1 < tries:
                ra = r.headers.get("retry-after", "")
                time.sleep(max(backoff, int(ra) if ra.isdigit() else 0)); backoff *= 3; continue
            break
        is_html = bool(re.search(r"html|xml|json|text/plain", meta["ctype"], re.I)) and not body[:5] == b"%PDF-"
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        if meta["status"] == 200 and is_html and not doc:
            _gz_w(fn + ".gz", body); json.dump(meta, open(fn + ".json", "w"))
        elif meta["status"] in (404, 410):
            json.dump(meta, open(fn + ".json", "w"))
        return dict(meta, body=body, cached=False)


# ---------------------------------------------------------------- Arabic text helpers
AR_RX = re.compile(r"[\u0600-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeff]")
LAT_RX = re.compile(r"[A-Za-z]")


def lang_of(t):
    a = len(AR_RX.findall(t or "")); l = len(LAT_RX.findall(t or ""))
    if a + l == 0:
        return "und"
    if a >= 0.8 * (a + l):
        return "ar"
    if l >= 0.8 * (a + l):
        return "en"
    return "ar,en"


def norm_ar(t):
    t = (t or "").replace("\u0640", "")            # tatweel
    t = re.sub(r"[\u064b-\u0652\u0670]", "", t)    # harakat
    t = re.sub(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", t)
    return re.sub(r"[ \t]+", " ", t)
