"""BD: sitting judges of the High Court Division, Supreme Court of Bangladesh, from the court's official judges' list page
(supremecourt.gov.bd/web/?page=judges.php&div_id=2; robots.txt 404 => allowed). Names and official titles only; 'Late Justice' entries skipped."""
import json, re, html, datetime, hashlib, os, time, requests
ROOT = "/workspace/world_courts"; UA = "Mozilla/5.0 (world_courts research; public court data)"
URL = "https://www.supremecourt.gov.bd/web/?page=judges.php&menu=11&div_id=2&lang="
OUT = f"{ROOT}/data/bd/bd_judges.jsonl"; CID = "bd-wd-q5268735"  # High Court Division courthouse row
now = datetime.datetime.now(datetime.UTC).isoformat()
t = requests.get(URL, headers={"User-Agent": UA}, timeout=90).text; sha = hashlib.sha256(t.encode()).hexdigest()
lines = [html.unescape(l).replace("\ufeff", "").strip() for l in re.sub(r"<[^>]+>", "\n", t).split("\n")]
names = [re.sub(r"\s+", " ", m.group(1)).strip(" .") for l in lines if (m := re.match(r"^\d+\.\s*Justice\s+(.+)$", l))]
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []
have = {slug(r["name"]) for r in old}; ids = {r["judge_id"] for r in old}; n = 0
with open(OUT, "a") as f:
    for nm in names:
        jid = f"bd-high-court-division-{slug(nm)}"
        if slug(nm) in have or jid in ids: continue
        f.write(json.dumps({"judge_id": jid, "court_id": CID, "name": nm, "title": "Judge, High Court Division", "position_type": "trial",
            "term_start": None, "term_end": None, "status": "sitting", "roster_url": URL, "source_url": URL, "site_policy": "robots_absent(404):allowed",
            "retrieved_at": now, "needs_review": False, "extraction": "official judges' list page, High Court Division (names and titles only; deceased entries skipped)",
            "license": "Supreme Court of Bangladesh website (facts)", "source_sha256": sha}, ensure_ascii=False) + "\n"); n += 1; have.add(slug(nm)); ids.add(jid)
print("parsed", len(names), "added", n)
