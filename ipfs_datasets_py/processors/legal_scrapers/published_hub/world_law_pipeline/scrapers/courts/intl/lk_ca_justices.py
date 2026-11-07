"""LK: Justices of the Court of Appeal of Sri Lanka from courtofappeal.lk/justices_of_the_court/ (robots: Allow /). Names + title only;
'PC' (President's Counsel) post-nominal dropped from name; '(P/CA)' marks the President of the Court of Appeal."""
import json, re, html, datetime, hashlib, os, requests
ROOT = "/workspace/world_courts"; UA = "Mozilla/5.0 (world_courts research; public court data)"
URL = "https://courtofappeal.lk/justices_of_the_court/"; OUT = f"{ROOT}/data/lk/lk_judges.jsonl"; CID = "lk-court-of-appeal"
now = datetime.datetime.now(datetime.UTC).isoformat()
r = requests.get(URL, headers={"User-Agent": UA}, timeout=60); r.raise_for_status(); sha = hashlib.sha256(r.content).hexdigest()
t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", r.text, flags=re.S)
x = [y for y in (re.sub(r"\s+", " ", html.unescape(z)).strip() for z in re.sub(r"<[^>]+>", "\n", t).split("\n")) if y]
def fix(n):
    n = re.sub(r"\.(?=[A-Za-z])", ". ", n); n = re.sub(r"^(DR\.)\s*", "Dr. ", n)
    return " ".join(w if (len(w) <= 2 and w.endswith(".")) else w.capitalize() if not re.match(r"^([A-Z]\.)+$", w) else w for w in n.split())
recs = []
for y in x:
    m = re.match(r"^HON\.\s*JUSTICE\s+(.+)$", y)
    if not m: continue
    n = m.group(1); pres = "(P/CA)" in n; n = re.sub(r"\(P/CA\)|\bPC\b", "", n).strip()
    recs.append((fix(n), pres))
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []; have = {slug(o["name"]) for o in old}; n = 0
with open(OUT, "a") as f:
    for name, pres in recs:
        if slug(name) in have: continue
        f.write(json.dumps({"judge_id": f"lk-ca-{slug(name)}", "court_id": CID, "name": name,
            "title": "President, Court of Appeal" if pres else "Judge, Court of Appeal", "position_type": "chief" if pres else "associate",
            "term_start": None, "term_end": None, "status": "sitting", "roster_url": URL, "source_url": URL, "site_policy": "robots_allowed",
            "retrieved_at": now, "needs_review": False, "extraction": "Court of Appeal 'Justices of the Court' page (names/titles only)",
            "license": "Court of Appeal of Sri Lanka website (facts)", "source_sha256": sha}, ensure_ascii=False) + "\n"); n += 1; have.add(slug(name))
print("parsed", len(recs), "added", n, [r[0] for r in recs][:6])
