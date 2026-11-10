#!/usr/bin/env python3
"""Generic Wayback (CDX + id_ snapshot) caselaw scraper for sites that block live bots.
Rows tagged archive-used. 1 connection to archive.org; resumable (state/<src>_done.txt); CDX cached."""
import argparse, json, os, re, sys, time, html as H, datetime, shutil, subprocess
sys.path.insert(0, os.path.dirname(__file__))
from peachjam import wait_for_space, get, log, next_part, save_part, CourtMap, AMEA, BASE
SAFLII = {"ZACC":"Constitutional Court of South Africa","ZASCA":"Supreme Court of Appeal of South Africa","ZALAC":"Labour Appeal Court","ZALC":"Labour Court",
 "ZALCJHB":"Labour Court","ZALCCT":"Labour Court","ZALCD":"Labour Court","ZALCC":"Land Claims Court","ZACAC":"Competition Appeal Court","ZAEC":"Electoral Court",
 "ZAECGHC":"za-hc-ec","ZAECMHC":"za-hc-ec","ZAECPEHC":"za-hc-ec","ZAECBHC":"za-hc-ec","ZAECHC":"za-hc-ec","ZAFSHC":"za-hc-fs","ZAGPPHC":"za-hc-gp","ZAGPJHC":"za-hc-gp",
 "ZAKZPHC":"za-hc-kzn","ZAKZDHC":"za-hc-kzn","ZALMPPHC":"za-hc-lp","ZALMPTHC":"za-hc-lp","ZAMPMBHC":"za-hc-mp","ZAMPMHC":"za-hc-mp","ZANCHC":"za-hc-nc","ZANWHC":"za-hc-nw","ZAWCHC":"za-hc-wc"}
def to_text(r):
    if r.content[:4] == b"%PDF":
        return subprocess.run(["pdftotext","-layout","-","-"],input=r.content,capture_output=True).stdout.decode("utf8","replace").strip() or None, None
    r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else (r.apparent_encoding or "utf-8")
    h = r.text; title = H.unescape(re.sub(r"\s+"," ",(re.findall(r"(?is)<title>(.*?)</title>",h) or [""])[0])).strip()
    h = re.sub(r"(?is)<(script|style|head|nav|footer)[^>]*>.*?</\1>|<!--.*?-->","",h)
    h = re.sub(r"(?i)</(p|div|h\d|li|tr)>|<br\s*/?>","\n",h)
    t = H.unescape(re.sub(r"<[^>]+>","",h)); t = "\n".join(l.strip() for l in t.splitlines() if l.strip())
    return (t if len(t) > 300 else None), title
def main():
    ap = argparse.ArgumentParser()
    for a in ["prefix","cc","src","include","court","court_id","policy","license","lang"]: ap.add_argument("--"+a.replace("_","-"), default=None)
    ap.add_argument("--delay", type=float, default=4); ap.add_argument("--shard-rows", type=int, default=200)
    a = ap.parse_args(); D = f"{BASE}/data/{a.cc}"; os.makedirs(D, exist_ok=True)
    pol = (a.policy or "robots-allowed") + ";archive-used"
    cache = f"{AMEA}/state/cdx_{a.src}.tsv"
    if not os.path.exists(cache):
        base = f"https://web.archive.org/cdx/search/cdx?url={a.prefix}&matchType=prefix&filter=statuscode:200&collapse=urlkey&fl=original,timestamp"
        r = None
        for _w in range(24):
            r = get(base.split("&filter")[0] + "&showNumPages=true", a.delay)
            if r is not None and r.text.strip().isdigit(): break
            log("cdx unavailable, waiting 10 min"); time.sleep(600)
        if r is None or not r.text.strip().isdigit(): raise SystemExit("CDX unavailable")
        pages = int(r.text.strip()) if r and r.text.strip().isdigit() else 1
        lines = []
        for pg in range(pages):
            r = None
            for _w in range(24):
                r = get(f"{base}&page={pg}", a.delay)
                if r is not None: break
                log("cdx unavailable, waiting 10 min"); time.sleep(600)
            if r is None: log("cdx page failed", pg); continue
            lines += [l for l in r.text.splitlines() if re.search(a.include, l.split(" ")[0])]
            log("cdx page", pg+1, "/", pages, len(lines))
        open(cache+".tmp","w").write("\n".join(lines)); os.replace(cache+".tmp", cache)
    sf = f"{AMEA}/state/{a.src}_done.txt"; done = set(open(sf).read().split()) if os.path.exists(sf) else set()
    part = next_part(a.src, D); cmap = CourtMap(a.cc); buf = []; n = 0; seen = set()
    def flush():
        nonlocal part, buf
        if not buf: return
        p = f"{D}/{a.src}_part{part:04d}.jsonl"
        with open(p+".tmp","w") as f:
            for r in buf: f.write(json.dumps(r, ensure_ascii=False)+"\n")
        os.rename(p+".tmp", p); open(sf,"a").write("\n".join(r["x_key"] for r in buf)+"\n")
        log("wrote", p, len(buf)); part += 1; save_part(a.src, part); buf = []; cmap.dump_missing()
    for l in open(cache):
        try: orig, ts = l.split()
        except ValueError: continue
        key = re.sub(r"^https?://(www\.)?", "", orig).replace(":80/", "/").rstrip("?").replace("?Dil=","").split("#")[0]
        if key in done or key in seen: continue
        seen.add(key)
        wait_for_space()
        fetch = f"https://web.archive.org/web/{ts}id_/{orig}"
        r = get(fetch, a.delay)
        if not r: continue
        txt, title = to_text(r)
        if not txt: continue
        court, cid, cit, date = a.court, (a.court_id or None), None, None
        m = re.search(r"/za/cases/([A-Z]+)/(\d{4})/(\d+)", orig)
        if m:
            v = SAFLII.get(m.group(1), m.group(1)); cit = f"[{m.group(2)}] {m.group(1)} {m.group(3)}"
            if v.startswith("za-"): cid = v; court = next((x["name"] for x in cmap.rows if x["court_id"] == v), v)
            else: court = v; cid = cmap.lookup(v, a.cc, "https://www.saflii.org/za/cases/" + m.group(1) + "/")
            dm = re.search(r"\((\d{1,2} \w+ \d{4})\)", title or "")
            if dm:
                try: date = datetime.datetime.strptime(dm.group(1), "%d %B %Y").date().isoformat()
                except Exception: pass
        if not cid and court: cid = cmap.lookup(court, a.cc, None)
        cn = None
        m2 = re.search(r"/BB/(\d{4})/(\d+)", orig)
        if m2: cn = f"{m2.group(1)}/{m2.group(2)}"
        parties = None
        if title and " v " in title: parties = [p.strip() for p in re.split(r"\s\(|\s\[", title)[0].split(" v ", 1)]
        buf.append({"id": f"{a.src}:{key}", "court": court, "court_id": cid, "jurisdiction_cc": a.cc, "place_id": None, "decision_date": date,
            "case_number": cn, "parties": parties, "judges": None, "citation": cit, "text": txt, "source_url": fetch, "license": a.license or "unknown",
            "site_policy": pol, "language": a.lang, "title": title, "source": a.src,
            "retrieved_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "x_original_url": orig, "x_key": key})
        n += 1
        if n % 25 == 0: log("progress", n, key)
        if len(buf) >= a.shard_rows: flush()
    flush(); log("finished", n)
if __name__ == "__main__": main()
