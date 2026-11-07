"""Sri Lanka procedure codes from LawNet (lawnet.gov.lk, Ministry of Justice portal) via Wayback Machine captures.
lawnet.gov.lk is unreachable live (2026-11); captures are fetched from web.archive.org (id_ raw mode), 4 s pacing.
- Civil Procedure Code (Cap. 101/105, consolidated to Act No. 4 of 2005), capture 2024-05-23
- Code of Criminal Procedure Act No. 15 of 1979 (consolidated as shown on LawNet), capture 2023-05-11
Section-level rows -> data/lk/lk_rules.jsonl (dedup by rule_id). needs_review: later amendments not consolidated."""
import re, html, json, hashlib, os, time, urllib.request, datetime
W = "/workspace/world_courts"; RAW = f"{W}/rules/raw/lk"; OUT = f"{W}/data/lk/lk_rules.jsonl"
UA = "WorldCourtsResearchBot/1.0 (Benjamin Barber world law project; polite crawler)"
SRC = [
  dict(rsid="lk-cpc", ts="20240523122453", url="https://www.lawnet.gov.lk/civil-procedure-code-4/", raw="lk_cpc4.html",
       rule_set="Civil Procedure Code (Cap. 101; Ordinance No. 2 of 1889, as amended to Act No. 4 of 2005)", court_id=None,
       eff="1890-08-01", note="LawNet consolidation as amended to Act No. 4 of 2005; LawNet page truncated after s.539; later amendments (e.g. Acts of 2017-2023) not consolidated"),
  dict(rsid="lk-cpc", ts="20200924101413", url="https://www.lawnet.gov.lk/civil-procedure-code-2/", raw="lk_cpc2.html", after=539,
       rule_set="Civil Procedure Code (Cap. 101; Ordinance No. 2 of 1889, as amended to Act No. 4 of 2005)", court_id=None,
       eff="1890-08-01", note="sections after s.539 taken from LawNet page civil-procedure-code-2 (2020 capture) because the 2024 page is truncated at s.539; LawNet pages end at s.583, later sections not available"),
  dict(rsid="lk-ccp", ts="20230511042126", url="https://www.lawnet.gov.lk/code-of-criminal-procedure/", raw="lk_ccp_page.html",
       rule_set="Code of Criminal Procedure Act, No. 15 of 1979", court_id=None,
       eff="1979-07-02", note="LawNet consolidation (Acts 15/1979, 36/1979, 68/1979, 52/1980 and later as shown); later amendments may be missing"),
]
POLICY = ("robots_unknown:lawnet.gov.lk unreachable live 2026-11-02 (robots.txt not retrievable; robots ignored per user authorization)|"
          "official Ministry of Justice LawNet portal, no restrictive terms found|fetched from Wayback Machine capture, 4 s/request")
def fetch(s):
    p = f"{RAW}/{s['raw']}"
    if not os.path.exists(p) or os.path.getsize(p) < 50000:
        u = f"https://web.archive.org/web/{s['ts']}id_/{s['url']}"
        for i in range(3):
            try:
                b = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA, "Accept-Encoding": "identity"}), timeout=120).read()
                open(p, "wb").write(b); break
            except Exception as e: print("retry", e); time.sleep(10)
        time.sleep(4)
    return open(p, "rb").read()
def text_of(b):
    h = b.decode("utf-8", "replace")
    t = html.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"<(script|style).*?</\1>", "", h, flags=re.S)))
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n", t))
def parse(t):
    st = t.find("Short title"); t = t[st - 400:]
    end = t.find("\nLeave a Reply"); t = t[:end] if end > 0 else t
    ms = list(re.finditer(r"\n ?(\d{1,3}[A-Z]{0,2})\s*\n\s*\.\s", t))
    rows, last, chap, seen = [], 0, None, set()
    def num(x): return int(re.match(r"\d+", x).group())
    keep = []
    for m in ms:
        n = num(m.group(1))
        if n < last or n > last + 40: continue  # monotonic guard against stray numbers
        keep.append(m); last = n
    for i, m in enumerate(keep):
        pre = t[(keep[i-1].end() if i else 0):m.start()]
        # chapter heading seen in previous section's tail
        ch = re.findall(r"\n ?(CHAPTER [IVXLC]+[A-Z]?)\s*\n([^\n]{3,120})", "\n" + pre)
        body_end = keep[i+1].start() if i + 1 < len(keep) else len(t)
        body = t[m.end():body_end]
        lines = body.rstrip().split("\n")
        # trailing line before next section is that section's marginal note
        title_next = lines[-1].strip() if len(lines) > 1 and len(lines[-1]) < 160 else None
        if i + 1 < len(keep) and title_next: body = "\n".join(lines[:-1])
        rows.append(dict(sec=m.group(1), body=body.strip(), chap=None, title=None))
        if ch: rows[-1]["chap_pre"] = " ".join(ch[-1])
        if i + 1 < len(keep): rows[-1]["title_next"] = title_next
    # attach titles (marginal notes) and chapters
    first_title = t[:keep[0].start()].strip().split("\n")[-1].strip() if keep else None
    cur = None
    for i, r in enumerate(rows):
        r["title"] = first_title if i == 0 else rows[i-1].get("title_next")
        if r.get("chap_pre"): cur = r["chap_pre"]
        # a chapter heading inside the body applies from next section
        r["chap"] = cur
        ch = re.findall(r"\n ?(CHAPTER [IVXLC]+[A-Z]?)\s*\n([^\n]{3,120})", "\n" + r["body"])
        if ch:
            r["body"] = r["body"][:r["body"].find(ch[0][0])].strip(); cur = " ".join(ch[-1])
    return rows
def main():
    have = set()
    if os.path.exists(OUT):
        for l in open(OUT): have.add(json.loads(l)["rule_id"])
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(); add = 0
    with open(OUT, "a") as f:
        for s in SRC:
            b = fetch(s); sha = hashlib.sha256(b).hexdigest(); rows = parse(text_of(b)); n = 0
            for r in rows:
                rid = f"{s['rsid']}:s{r['sec']}"
                if rid in have or len(r["body"]) < 5: continue
                if s.get("after") and int(re.match(r"\d+", r["sec"]).group()) <= s["after"]: continue
                if r["title"] and re.match(r"^\[.*\]$", r["title"].strip()): r["body"] = r["title"].strip() + " " + r["body"]; r["title"] = None
                have.add(rid); n += 1
                f.write(json.dumps(dict(rule_id=rid, rule_set_id=s["rsid"], court_id=s["court_id"], jurisdiction="LK", rule_set=s["rule_set"],
                    rule_number=f"Section {r['sec']}", title=(r["title"] or "").strip(" .") or None, part=r["chap"], text=("" + r["body"])[:60000],
                    effective_date=s["eff"], pdf_path=None, pdf_sha256=None, source_sha256=sha, source_url=s["url"],
                    index_url=f"https://web.archive.org/web/{s['ts']}/{s['url']}", site_policy=POLICY, retrieved_at=now,
                    license="Sri Lanka written law (public legislation), official LawNet text; no licence stated", language="en",
                    source_kind="official_archived", version_note=s["note"], needs_review=True), ensure_ascii=False) + "\n")
            print(s["rsid"], "parsed", len(rows), "added", n); add += n
    print("total added", add)
if __name__ == "__main__":
    import sys
    if "--dry" in sys.argv:
        for s in SRC:
            rows = parse(text_of(fetch(s))); print(s["rsid"], len(rows), [ (r["sec"], (r["title"] or "")[:40], r["chap"]) for r in rows[:6]], rows[-1]["sec"])
            for r in rows[100:103]: print("  ", r["sec"], r["title"], "|", r["body"][:200].replace("\n"," "))
    else: main()
