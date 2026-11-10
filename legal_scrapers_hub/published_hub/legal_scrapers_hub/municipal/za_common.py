"""Polite HTTP + resource guard for the South Africa municipal supplement collectors.

- robots.txt (User-agent '*' group, '*'/'$' wildcards, longest match wins, Allow wins ties) checked on every URL and on
  the final URL after redirects; Crawl-delay honoured (per-host delay = max(ZA_MIN_DELAY, crawl-delay)); robots.txt
  unreadable (network/TLS error, 5xx) -> the host is not crawled (fail closed). 404 robots -> allow all.
- TLS is always verified: certifi, or a per-host CA bundle at <ZA_CA_DIR>/<host>.pem (certifi roots + the host's missing
  public intermediate). Never verify=False.
- HTML/XML bodies are cached gzip-compressed under <ZA_STATE>/cache (resumable); document bodies (PDF/DOC) are returned to
  the caller and are not cached (the caller stores extracted text; only image-only PDFs are kept for a later OCR pass).
- Every network request is appended to <ZA_STATE>/logs/requests.jsonl.
- resource_ok(): MemAvailable >= 4.5 GiB and free disk on / >= 30 GiB; wait_resources() pauses until both hold.
Paths come from env: ZA_STATE (state dir), ZA_CA_DIR (per-host PEMs). No secrets, no cookies, no logins.
"""
import os, re, time, json, gzip, hashlib, threading, urllib.parse, datetime
import requests, certifi

STATE = os.environ.get("ZA_STATE", "za_build_state")
CA_DIR = os.environ.get("ZA_CA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "ca"))
MIN_DELAY = float(os.environ.get("ZA_MIN_DELAY", "3"))
UA = "EndomorphosisWorldLaws-municipal/1.0 (research; legal translation corpus; polite crawler; robots.txt honoured)"
MIN_MEM_GIB = float(os.environ.get("ZA_MIN_MEM_GIB", "4.5"))
MIN_DISK_GIB = float(os.environ.get("ZA_MIN_DISK_GIB", "30"))


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mem_gib():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable:"):
            return int(l.split()[1]) / 1048576
    return 0.0


def disk_gib(path="/"):
    s = os.statvfs(path)
    return s.f_bavail * s.f_frsize / 1024 ** 3


def resource_ok():
    return mem_gib() >= MIN_MEM_GIB and disk_gib("/") >= MIN_DISK_GIB


def wait_resources(log=print, stop_file=None):
    """Block while memory/disk are under the floors (checks every 60 s). Returns False if stop_file appears."""
    warned = False
    while not resource_ok():
        if stop_file and os.path.exists(stop_file):
            return False
        if not warned:
            log(f"{now_utc()} PAUSE resources: mem={mem_gib():.2f}GiB disk={disk_gib():.1f}GiB")
            warned = True
        time.sleep(60)
    if warned:
        log(f"{now_utc()} RESUME resources: mem={mem_gib():.2f}GiB disk={disk_gib():.1f}GiB")
    return True


def parse_robots(txt):
    """-> (rules [(allow, pattern)], crawl_delay or None) for the 'User-agent: *' group(s)."""
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
        self.min_delay = min_delay
        self.robots = {}     # base -> (rules, delay) or None (blocked / unreadable)
        self.robots_raw = {}
        self.last = {}
        self.lock = threading.Lock()

    def ca_for(self, host):
        p = os.path.join(CA_DIR, host + ".pem")
        return p if os.path.exists(p) else certifi.where()

    def _log(self, **kw):
        kw["t"] = now_utc()
        with open(self.reqlog, "a") as f:
            f.write(json.dumps(kw) + "\n")

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
        fn = os.path.join(self.state, "cache", "robots_" + re.sub(r"[^a-z0-9.]+", "_", base.lower()) + ".json")
        if os.path.exists(fn):
            d = json.load(open(fn))
            if time.time() - d["ts"] < 86400:
                self.robots[base] = None if d["blocked"] else (d["rules"], d["delay"])
                self.robots_raw[base] = d.get("raw", "")
                return self.robots[base]
        self._wait(host, self.min_delay)
        res, raw, note = None, "", ""
        try:
            r = self.s.get(base + "/robots.txt", timeout=40, verify=self.ca_for(host), allow_redirects=True)
            self._log(url=base + "/robots.txt", status=r.status_code, kind="robots")
            if r.status_code == 200 and "<html" not in r.text[:500].lower():
                raw = r.text
                rules, delay = parse_robots(raw)
                res = (rules, delay)
            elif r.status_code in (404, 410) or (r.status_code == 200):
                res = ([], None)  # no robots.txt (or an HTML page): allow all
                note = f"robots {r.status_code}"
            else:
                note = f"robots status {r.status_code}"
        except requests.RequestException as e:
            note = f"robots error {type(e).__name__}: {str(e)[:200]}"
            self._log(url=base + "/robots.txt", status=-1, kind="robots", error=note)
        self.robots[base] = res
        self.robots_raw[base] = raw or note
        json.dump(dict(ts=time.time(), blocked=res is None, rules=res[0] if res else None,
                       delay=res[1] if res else None, raw=raw[:20000], note=note), open(fn, "w"))
        return res

    def allowed(self, url):
        u = urllib.parse.urlsplit(url)
        base = f"{u.scheme}://{u.netloc}"
        rr = self._robots(base)
        if rr is None:
            return False
        path = (u.path or "/") + (("?" + u.query) if u.query else "")
        return robots_allows(rr[0], path) and robots_allows(rr[0], urllib.parse.unquote(path))

    def get(self, url, *, doc=False, timeout=90, max_bytes=80_000_000, use_cache=True):
        """-> dict(status, url, ctype, body: bytes, cached) ; None when robots disallows or the host is blocked.
        doc=True: body not cached (documents); HTML/XML responses are cached."""
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
        self._wait(u.netloc, self.host_delay(base))
        try:
            r = self.s.get(url, timeout=timeout, stream=True, allow_redirects=True, verify=self.ca_for(u.netloc))
            if r.url != url and not self.allowed(r.url):
                r.close()
                self._log(url=url, final=r.url, status=r.status_code, kind="redirect-disallowed")
                return None
            chunks, n = [], 0
            for ch in r.iter_content(65536):
                chunks.append(ch)
                n += len(ch)
                if n > max_bytes:
                    break
            body = b"".join(chunks)
            meta = dict(status=r.status_code, url=r.url, ctype=r.headers.get("content-type", ""),
                        truncated=n > max_bytes, retrieved_at=now_utc(), length=len(body))
        except requests.RequestException as e:
            self._log(url=url, status=-1, error=f"{type(e).__name__}: {str(e)[:200]}")
            return dict(status=-1, url=url, ctype="error:" + type(e).__name__, body=b"", cached=False,
                        error=str(e)[:300], retrieved_at=now_utc())
        self._log(url=url, final=meta["url"], status=meta["status"], ctype=meta["ctype"], length=meta["length"])
        is_html = bool(re.search(r"html|xml|json|text/plain", meta["ctype"], re.I)) and not body[:5] == b"%PDF-"
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        if meta["status"] == 200 and is_html and not doc:
            _gz_w(fn + ".gz", body)
            json.dump(meta, open(fn + ".json", "w"))
        elif meta["status"] in (404, 410):
            json.dump(meta, open(fn + ".json", "w"))
        return dict(meta, body=body, cached=False)
