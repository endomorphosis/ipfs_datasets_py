"""2026-11-02 topup3 normalize (after postfilter): IKISS/Advantic download.php links 404 for direct GETs, so rewrite to the
underlying media file: ?file=<urlencoded /media/custom/..PDF?ts> -> that path; ?fid=A.B.C.PDF -> /media/custom/A_B_C.PDF.
Drop obvious HTML pages picked up by the 'download' link pattern (path ending '/', index.php, .php pages without PDF hint).
Re-dedupe against everything staged, also comparing with query strings stripped (staged media URLs carry ?<timestamp>)."""
import json, re, sys, hashlib, urllib.parse
from urllib.parse import urlsplit
sys.argv, _a = ["x"], sys.argv[1:]
from de_by_topup3_build import staged
SU, SI = staged(); SUS = {u.split("?")[0] for u in SU} | {urllib.parse.unquote(u.split("?")[0]) for u in SU}
for q in _a:
    p = f"entries/de_by_wd_{q}.json"; E = json.load(open(p)); out, seen, st = [], set(), dict(rewritten=0, html=0, dup=0)
    for it in E["items"]:
        u = it["url"]; s = urlsplit(u)
        if s.path.endswith("/output/download.php"):
            qs = urllib.parse.parse_qs(s.query)
            if "file" in qs: u = f"{s.scheme}://{s.netloc}{qs['file'][0]}"; st["rewritten"] += 1
            elif "fid" in qs and re.fullmatch(r"\d+\.\d+\.\d+\.PDF", qs["fid"][0], re.I):
                a, b, c, ext = qs["fid"][0].split("."); u = f"{s.scheme}://{s.netloc}/media/custom/{a}_{b}_{c}.{ext}"; st["rewritten"] += 1
        pth = urlsplit(u).path.lower()
        if (pth.endswith("/") or pth.endswith(".php") or pth.endswith(".html")) and not re.search(r"pdf|loadDocument|Dox\.aspx", u, re.I): st["html"] += 1; continue
        if pth.endswith((".php", "/")) and "download.php" in pth: st["html"] += 1; continue
        b = u.split("?")[0]; did = "de_by_kreisrecht:" + hashlib.sha1(u.encode()).hexdigest()[:16]
        if u in SU or did in SI or (("?" in u or b.lower().endswith(".pdf")) and (b in SUS or urllib.parse.unquote(b) in SUS)) or b + "|" + u in seen or u in seen:
            st["dup"] += 1; continue
        seen.add(u); out.append(dict(it, url=u))
    E["items"] = out; json.dump(E, open(p, "w"), ensure_ascii=False); print(q, E["place_name"], "kept", len(out), st, flush=True)
