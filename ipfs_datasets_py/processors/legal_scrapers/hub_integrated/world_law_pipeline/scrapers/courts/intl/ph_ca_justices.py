"""PH: incumbent justices of the Court of Appeals from ca.judiciary.gov.ph/about/incumbent-justices (official; robots.txt redirects to an
error page => treated as absent). Names and official title (Presiding/Executive/Associate Justice) only; division chair roles and dates not stored."""
import json, re, html, datetime, hashlib, os, requests
ROOT = "/workspace/world_courts"; UA = "Mozilla/5.0 (world_courts research; public court data)"
URL = "https://ca.judiciary.gov.ph/about/incumbent-justices"; OUT = f"{ROOT}/data/ph/ph_judges.jsonl"; CID = "ph-court-of-appeals"
now = datetime.datetime.now(datetime.UTC).isoformat()
r = requests.get(URL, headers={"User-Agent": UA}, timeout=60); r.raise_for_status(); sha = hashlib.sha256(r.content).hexdigest()
t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", r.text, flags=re.S)
x = [y for y in (re.sub(r"\s+", " ", html.unescape(z)).strip() for z in re.sub(r"<[^>]+>", "\n", t).split("\n")) if y]
recs = [(x[i + 1], x[i + 2]) for i in range(len(x) - 2) if x[i] == "HON." and x[i + 2] in ("Presiding Justice", "Associate Justice", "Executive Justice")]
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []; have = {slug(o["name"]) for o in old}; n = 0
with open(OUT, "a") as f:
    for name, role in recs:
        if slug(name) in have: continue
        f.write(json.dumps({"judge_id": f"ph-ca-{slug(name)}", "court_id": CID, "name": name, "title": f"{role}, Court of Appeals",
            "position_type": "chief" if role == "Presiding Justice" else "associate", "term_start": None, "term_end": None, "status": "sitting",
            "roster_url": URL, "source_url": URL, "site_policy": "robots_absent(error_page)", "retrieved_at": now, "needs_review": False,
            "extraction": "Court of Appeals 'Incumbent Justices' page (names/titles only)", "license": "Court of Appeals of the Philippines website (facts)",
            "source_sha256": sha}, ensure_ascii=False) + "\n"); n += 1; have.add(slug(name))
print("parsed", len(recs), "added", n)
