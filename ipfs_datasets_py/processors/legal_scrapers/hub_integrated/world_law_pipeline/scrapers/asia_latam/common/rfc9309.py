"""Minimal RFC 9309 robots.txt matcher (urllib.robotparser ignores '*' and '$' wildcards, so it is NOT used).

- groups selected by case-insensitive product-token match of the user-agent line (most specific wins), else '*'
- longest matching rule wins; on equal length, Allow wins
- '*' matches any sequence, '$' anchors the end
- /robots.txt is always allowed
"""
import functools, re
from urllib.parse import urlparse, unquote


def _parse(text):
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


@functools.lru_cache(maxsize=4096)
def _pat(p):
    # consecutive '*' are equivalent to one; collapsing them avoids catastrophic regex backtracking
    # (e.g. lexml.gov.br uses 'Allow: /*******************.js'). Rule precedence still uses len(original pattern).
    q = re.sub(r"\*+", "*", p)
    rx = "".join(".*" if c == "*" else ("$" if (c == "$" and i == len(q) - 1) else re.escape(c)) for i, c in enumerate(q))
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


if __name__ == "__main__":
    r = Robots("User-agent: Buck/2.2\nDisallow: /\n\nUser-agent: *\nDisallow: /*\nAllow: /info$\nAllow: /info.0$\nAllow: /$\n")
    for u in ["https://x/board/1/", "https://x/preview-document/a", "https://x/info.0", "https://x/", "https://x/info.0x"]:
        print(u, r.can_fetch("JusticeDAO-WorldLaw/1.0", u))
    j = Robots("User-agent: *\nDisallow: /*/act/content/content21*.htm\nDisallow: /*/act/hist/\n")
    for u in ["https://lg/kitami_city/reiki/act/110000007.html", "https://lg/k/reiki/act/hist/1.html", "https://lg/k/act/content/content21x.htm"]:
        print(u, j.can_fetch("JusticeDAO-WorldLaw/1.0", u))
    print(Robots("User-agent: *\nDisallow: /\n").can_fetch("x", "https://a/b"), Robots("User-agent: *\nDisallow:\n").can_fetch("x", "https://a/b"))
