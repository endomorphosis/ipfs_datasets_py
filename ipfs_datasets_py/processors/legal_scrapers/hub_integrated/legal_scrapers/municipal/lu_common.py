"""Polite HTTP for the Luxembourg municipal collector: robots.txt (own matcher: '*' and '$' wildcards, longest match wins,
Allow beats Disallow on ties, group 'User-agent: *'), at most 1 request per second per host, disk cache keyed on the URL.
Defaults are relative to the working directory: LU_BUILD (default 'lu_build'), LU_CACHE (default '<LU_BUILD>/cache')."""
import os, re, time, hashlib, json, threading, urllib.parse
import requests

BUILD = os.environ.get("LU_BUILD", "lu_build")
CACHE = os.environ.get("LU_CACHE", os.path.join(BUILD, "cache"))
UA = "Mozilla/5.0 (compatible; legal-corpora-research/0.1; municipal regulations; 1 req/s)"

def robots_rules(txt):
    """rules for 'User-agent: *' as [(allow, pattern)]"""
    groups, cur, ua_block, rules = [], [], False, {}
    agents = []; out = []
    for raw in txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line: continue
        k, v = [x.strip() for x in line.split(":", 1)]; k = k.lower()
        if k == "user-agent":
            if ua_block: agents = []; ua_block = False
            agents.append(v.lower())
        elif k in ("allow", "disallow"):
            ua_block = True
            if "*" in agents and v: out.append((k == "allow", v))
    return out

def robots_allowed(rules, path):
    best = None
    for allow, p in rules:
        pp = p[:-1] + "$" if p.endswith("$") else p
        rx = re.compile("^" + re.escape(pp.rstrip("$")).replace(r"\*", ".*") + ("$" if pp.endswith("$") else ""))
        if rx.match(path):
            key = (len(p), allow)
            if best is None or key > best[0]: best = (key, allow)
    return True if best is None else best[1]

class Polite:
    def __init__(self, cache=CACHE, delay=1.0):
        self.s = requests.Session(); self.s.headers["User-Agent"] = UA
        self.cache = cache; os.makedirs(cache, exist_ok=True); self.delay = delay
        self.last = {}; self.robots = {}; self.lock = threading.Lock()
    def _robots(self, base):
        if base not in self.robots:
            try:
                r = self.s.get(base + "/robots.txt", timeout=30)
                self.robots[base] = robots_rules(r.text) if r.status_code == 200 and "<html" not in r.text[:500].lower() else []
            except requests.RequestException:
                self.robots[base] = None     # robots.txt unreadable: do not crawl the host
        return self.robots[base]
    def allowed(self, url):
        u = urllib.parse.urlsplit(url); base = f"{u.scheme}://{u.netloc}"
        rules = self._robots(base)
        if rules is None: return False
        path = (u.path or "/") + (("?" + u.query) if u.query else "")
        return robots_allowed(rules, urllib.parse.unquote(path)) and robots_allowed(rules, path)
    def _wait(self, host):
        while True:
            with self.lock:
                t = time.time(); nxt = self.last.get(host, 0) + self.delay
                if t >= nxt: self.last[host] = t; return
            time.sleep(nxt - t)
    def get(self, url, binary=False, timeout=60, max_bytes=60_000_000, html_only=False, store_body=True):
        """(status, final_url, content-type, body) from cache or network; None when robots.txt disallows the URL.
        html_only (crawling): a response that is not HTML / XML is not downloaded; its body is returned empty (own cache key)"""
        if html_only:   # a page already cached by a plain request is reused when it is HTML / XML
            k0 = os.path.join(self.cache, hashlib.sha1(url.encode()).hexdigest())
            if os.path.exists(k0 + ".json"):
                meta = json.load(open(k0 + ".json"))
                if re.search(r"html|xml", meta.get("ctype") or "", re.I) or meta["status"] != 200:
                    body = open(k0, "rb").read() if os.path.exists(k0) else b""
                    return meta["status"], meta["url"], meta["ctype"], (body if binary else body.decode("utf-8", "replace"))
        key = hashlib.sha1((url + ("#html-only" if html_only else "")).encode()).hexdigest(); fn = os.path.join(self.cache, key)
        if os.path.exists(fn + ".json"):
            meta = json.load(open(fn + ".json")); body = open(fn, "rb").read() if os.path.exists(fn) else b""
            return meta["status"], meta["url"], meta["ctype"], (body if binary else body.decode("utf-8", "replace"))
        if not self.allowed(url): return None
        host = urllib.parse.urlsplit(url).netloc; self._wait(host)
        try:
            r = self.s.get(url, timeout=timeout, stream=True, allow_redirects=True)
            if not self.allowed(r.url): r.close(); return None
            body = b""
            if html_only and not re.search(r"html|xml", r.headers.get("content-type", ""), re.I):
                st, fu, ct = r.status_code, r.url, r.headers.get("content-type", ""); r.close()
                json.dump(dict(status=st, url=fu, ctype=ct, body_skipped=True), open(fn + ".json", "w"))
                return st, fu, ct, (b"" if binary else "")
            for ch in r.iter_content(65536):
                body += ch
                if len(body) > max_bytes: break
            st, fu, ct = r.status_code, r.url, r.headers.get("content-type", "")
        except requests.RequestException as e:
            st, fu, ct, body = -1, url, "error:" + type(e).__name__, b""
        if st != -1:
            # store_body=False (document fetch: the caller keeps the file itself) caches only the metadata, keeping the cache lean
            if store_body or st != 200: open(fn, "wb").write(body); json.dump(dict(status=st, url=fu, ctype=ct), open(fn + ".json", "w"))
        return st, fu, ct, (body if binary else body.decode("utf-8", "replace"))
