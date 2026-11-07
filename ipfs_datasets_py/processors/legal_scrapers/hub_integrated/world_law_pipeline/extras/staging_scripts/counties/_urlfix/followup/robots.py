import re,urllib.request,urllib.error
from urllib.parse import urlsplit, unquote
UA='Mozilla/5.0 (world_law county lane)'
rp_cache = {}
def rfc_rules(txt):
    """RFC 9309: rules of the '*' group(s) (we send no named product token)."""
    rules, grp, in_star, last_ua = [], [], False, False
    for line in txt.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line: continue
        k, v = [x.strip() for x in line.split(":", 1)]; k = k.lower()
        if k == "user-agent":
            if not last_ua: in_star = False
            in_star = in_star or v == "*"; last_ua = True
        elif k in ("allow", "disallow"):
            last_ua = False
            if in_star and v: rules.append((k == "allow", v))
        else: last_ua = False
    return rules
def rfc_allowed(rules, u):
    sp = urlsplit(u); path = (sp.path or "/") + ("?" + sp.query if sp.query else "")
    best = (-1, True)
    for allow, pat in rules:
        rx = "^" + re.escape(pat).replace(r"\*", ".*")
        if rx.endswith(r"\$"): rx = rx[:-2] + "$"
        if re.match(rx, path) or re.match(rx, unquote(path)):
            L = len(pat)
            if L > best[0] or (L == best[0] and allow): best = (L, allow)
    return best[1]
def robots(u):
    h = urlsplit(u); base = f"{h.scheme}://{h.netloc}"
    if base not in rp_cache:
        try:
            r = urllib.request.urlopen(urllib.request.Request(base + "/robots.txt", headers={"User-Agent": UA}), timeout=30)
            rp_cache[base] = ("ok", rfc_rules(r.read().decode("utf-8", "replace")))
        except urllib.error.HTTPError as e:
            rp_cache[base] = ("404", None) if e.code in (404, 410) else ("unreach", None)
        except Exception: rp_cache[base] = ("unreach", None)
    st, rp = rp_cache[base]
    if st == "404": return "robots_404_allow_rfc9309"
    if st == "unreach": return "robots_unreachable"
    return "robots_allowed_rfc9309" if rfc_allowed(rp, u) else "robots_disallowed"
