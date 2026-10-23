"""(Vendored from scrapers/asia_latam/common/rfc9309.py; EU-lane change: strip a UTF-8 BOM, which several
Polish e-Dziennik hosts send and which otherwise hides the first User-agent line. Plus RobotsCache below.)

Minimal RFC 9309 robots.txt matcher (urllib.robotparser ignores '*' and '$' wildcards, so it is NOT used).

- groups selected by case-insensitive product-token match of the user-agent line (most specific wins), else '*'
- longest matching rule wins; on equal length, Allow wins
- '*' matches any sequence, '$' anchors the end
- /robots.txt is always allowed
"""
import re
from urllib.parse import urlparse, unquote


def _parse(text):
    text = text.lstrip("\ufeff")
    groups, cur, last_was_ua = [], None, False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            if not last_was_ua or cur is None:
                cur = {"agents": [], "rules": []}
                groups.append(cur)
            cur["agents"].append(v.lower())
            last_was_ua = True
        elif k == "crawl-delay":
            last_was_ua = False
            if cur is not None:
                try:
                    cur["delay"] = float(v)
                except ValueError:
                    pass
        elif k in ("allow", "disallow"):
            last_was_ua = False
            if cur is None:
                continue
            if k == "disallow" and v == "":
                continue
            cur["rules"].append((k == "allow", v))
        else:
            last_was_ua = False if k not in ("sitemap",) else last_was_ua
    return groups


def _pat(p):
    rx = "".join(".*" if c == "*" else ("$" if (c == "$" and i == len(p) - 1) else re.escape(c)) for i, c in enumerate(p))
    return re.compile(rx)


class Robots:
    def __init__(self, text="", allow_all=False, disallow_all=False):
        self.allow_all, self.disallow_all = allow_all, disallow_all
        self.groups = _parse(text) if text else []

    def _rules(self, ua):
        token = re.split(r"[/\s]", ua.strip(), maxsplit=1)[0].lower()
        best = ""
        for g in self.groups:
            for a in g["agents"]:
                if a != "*" and (token == a or token.startswith(a)) and len(a) > len(best):
                    best = a
        key = best or "*"
        return [r for g in self.groups if key in g["agents"] for r in g["rules"]]

    def crawl_delay(self, ua):
        """Non-standard Crawl-delay for the selected group (honoured for politeness), or None."""
        token = re.split(r"[/\s]", ua.strip(), maxsplit=1)[0].lower()
        best = ""
        for g in self.groups:
            for a in g["agents"]:
                if a != "*" and (token == a or token.startswith(a)) and len(a) > len(best):
                    best = a
        key = best or "*"
        ds = [g["delay"] for g in self.groups if key in g["agents"] and "delay" in g]
        return max(ds) if ds else None

    def can_fetch(self, ua, url):
        if self.allow_all:
            return True
        if self.disallow_all:
            return False
        p = urlparse(url)
        path = unquote(p.path or "/") + (("?" + p.query) if p.query else "")
        if path == "/robots.txt":
            return True
        best_len, allowed = -1, True
        for allow, pat in self._rules(ua):
            if _pat(pat).match(path):
                L = len(pat)
                if L > best_len or (L == best_len and allow):
                    best_len, allowed = L, allow
        return allowed


class RobotsCache:
    """Per-host robots.txt per RFC 9309 sec. 2.3.1: 2xx -> parse; 4xx -> allow all; 5xx/unreachable -> disallow all
    (re-tried after `ttl_fail`). Successful fetches are cached for `ttl` seconds."""

    def __init__(self, session_factory, ua, ttl=86400, ttl_fail=3600, log=None):
        import threading
        self.sf, self.ua, self.ttl, self.ttl_fail, self.log = session_factory, ua, ttl, ttl_fail, log
        self.cache, self.lock = {}, threading.Lock()

    def get(self, url):
        import time
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        with self.lock:
            hit = self.cache.get(base)
        if hit and time.time() < hit[1]:
            return hit[0]
        status, rb, ttl = None, None, self.ttl
        try:
            r = self.sf(base).get(base + "/robots.txt", timeout=(15, 60), allow_redirects=True)
            status = r.status_code
            if 200 <= status < 300:
                ctype = r.headers.get("content-type", "")
                txt = r.text
                if "html" in ctype.lower() and "<html" in txt[:500].lower():
                    rb = Robots(allow_all=True)  # SPA fallback page, not a robots file
                else:
                    rb = Robots(txt)
            elif 400 <= status < 500:
                rb = Robots(allow_all=True)
            else:
                rb, ttl = Robots(disallow_all=True), self.ttl_fail
        except Exception as e:  # noqa: BLE001
            status, rb, ttl = f"error {type(e).__name__}", Robots(disallow_all=True), self.ttl_fail
        if self.log:
            self.log.info("robots %s/robots.txt -> %s", base, status)
        with self.lock:
            self.cache[base] = (rb, time.time() + ttl, status)
        return rb

    def can_fetch(self, url):
        return self.get(url).can_fetch(self.ua, url)


if __name__ == "__main__":
    r = Robots("User-agent: Buck/2.2\nDisallow: /\n\nUser-agent: *\nDisallow: /*\nAllow: /info$\nAllow: /info.0$\nAllow: /$\n")
    for u in ["https://x/board/1/", "https://x/preview-document/a", "https://x/info.0", "https://x/", "https://x/info.0x"]:
        print(u, r.can_fetch("JusticeDAO-WorldLaw/1.0", u))
    j = Robots("User-agent: *\nDisallow: /*/act/content/content21*.htm\nDisallow: /*/act/hist/\n")
    for u in ["https://lg/kitami_city/reiki/act/110000007.html", "https://lg/k/reiki/act/hist/1.html", "https://lg/k/act/content/content21x.htm"]:
        print(u, j.can_fetch("JusticeDAO-WorldLaw/1.0", u))
    print(Robots("User-agent: *\nDisallow: /\n").can_fetch("x", "https://a/b"), Robots("User-agent: *\nDisallow:\n").can_fetch("x", "https://a/b"))
