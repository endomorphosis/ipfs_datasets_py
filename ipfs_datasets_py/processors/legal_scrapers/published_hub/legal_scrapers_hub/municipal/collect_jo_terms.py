#!/usr/bin/env python3
"""Fetch the publishers' terms / copyright / disclaimer pages and robots.txt status for every JO host used
-> $JO_STATE/terms.json (full page text, never truncated) and $JO_STATE/robots_status.json."""
import os, re, sys, json, html as H
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jo_common as C
from bs4 import BeautifulSoup

HOSTS = ["https://www.pm.gov.jo", "https://doc.pm.gov.jo", "https://media.ammancity.gov.jo", "https://www.ammancity.gov.jo",
         "https://www.mola.gov.jo"]
PAGES = {
    "pm.gov.jo": ["https://www.pm.gov.jo/AR/Pages/شروط_الاستخدام", "https://www.pm.gov.jo/AR/Pages/حقوق_النشر",
                  "https://www.pm.gov.jo/AR/Pages/إخلاء_المسؤولية"],
    "media.ammancity.gov.jo": [],
    "www.mola.gov.jo": [],
}


def page_lines(b):
    s = BeautifulSoup(b, "html.parser")
    for x in s(["script", "style", "noscript"]):
        x.decompose()
    return [l.strip() for l in s.get_text("\n").split("\n") if l.strip()]


def strip_boilerplate(pages):
    """Full page text minus the site chrome: lines that occur on every terms page of the same host are dropped."""
    sets = [set(ls) for ls in pages]
    common = set.intersection(*sets) if len(sets) >= 2 else set()
    return ["\n".join(l for l in ls if l not in common) for ls in pages]


def find_links(P, home, words):
    r = P.get(home)
    if not r or r["status"] != 200:
        return []
    out = []
    for m in re.finditer(r'href="([^"]+)"', r["body"].decode("utf-8", "replace")):
        u = H.unescape(m.group(1))
        if any(w in u for w in words):
            if u.startswith("/"):
                u = home.rstrip("/").split("/AR")[0].split("/Ar")[0] + u
            if u.startswith("http") and u not in out:
                out.append(u)
    return out


def main():
    P = C.Polite()
    rob = {b: P.robots_status(b) for b in HOSTS}
    json.dump(rob, open(os.path.join(C.STATE, "robots_status.json"), "w"), ensure_ascii=False, indent=1)
    words = ["شروط", "حقوق_النشر", "إخلاء", "اخلاء", "سياسة_الخصوصية"]
    PAGES["media.ammancity.gov.jo"] = find_links(P, "https://media.ammancity.gov.jo/AR/List/التشريعات", words)[:6]
    PAGES["www.mola.gov.jo"] = find_links(P, "https://www.mola.gov.jo/Ar/List/الانظمة", words)[:6]
    out = {}
    for host, urls in PAGES.items():
        out[host] = []
        for u in urls:
            r = P.get(u)
            if not r:
                out[host].append({"url": u, "status": "robots-disallowed"}); continue
            out[host].append({"url": u, "final_url": r.get("url"), "status": r["status"], "retrieved_at": r.get("retrieved_at"),
                              "_lines": page_lines(r["body"]) if r["status"] == 200 else []})
        texts = strip_boilerplate([x.get("_lines", []) for x in out[host]])
        for x, t in zip(out[host], texts):
            x.pop("_lines", None); x["text"] = "\n".join(l for l in t.split("\n") if not re.fullmatch(r"[\d\s\"]+", l)); print(host, x["url"], x["status"], len(t))
    json.dump(out, open(os.path.join(C.STATE, "terms.json"), "w"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except C.ResourcePause as e:
        print("PAUSE", e); sys.exit(4)
