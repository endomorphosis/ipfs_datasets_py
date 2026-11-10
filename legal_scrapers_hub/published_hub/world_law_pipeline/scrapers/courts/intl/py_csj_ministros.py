"""PY: Ministros de la Corte Suprema de Justicia from pj.gov.py/ministros/ (robots.txt only lists a sitemap => allowed).
Names (Dr./Dra. stripped) + official title only. Existing rows matched on name slug are not duplicated."""
import json, re, html, datetime, hashlib, os, unicodedata, requests
ROOT = "/workspace/world_courts"; UA = "Mozilla/5.0 (world_courts research; public court data)"
SRC = "https://www.pj.gov.py/ministros/"; OUT = f"{ROOT}/data/py/py_judges.jsonl"; now = datetime.datetime.now(datetime.UTC).isoformat()
r = requests.get(SRC, headers={"User-Agent": UA}, timeout=60); r.raise_for_status(); sha = hashlib.sha256(r.content).hexdigest()
t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", r.text, flags=re.S)
x = [y for y in (re.sub(r"\s+", " ", html.unescape(z)).strip() for z in re.sub(r"<[^>]+>", "\n", t).split("\n")) if y]
i0 = x.index("Ministros de la CSJ"); names = []
for y in x[i0:i0 + 20]:
    m = re.match(r"^Dra?\.\s+(.+)$", y)
    if m: names.append(m.group(1).strip())
def slug(s): return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()).strip("-")
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []; have = {slug(o["name"]) for o in old}; n = 0
with open(OUT, "a") as f:
    for nm in names:
        if slug(nm) in have: continue
        f.write(json.dumps({"judge_id": f"py-supreme-court-{slug(nm)}", "court_id": "py-supreme-court", "name": nm, "title": "Ministro de la Corte Suprema de Justicia",
            "position_type": "associate", "term_start": None, "term_end": None, "status": "sitting", "roster_url": SRC, "source_url": SRC,
            "site_policy": "robots_allowed", "retrieved_at": now, "needs_review": False, "extraction": "pj.gov.py 'Ministros de la CSJ' page (names/official title only)",
            "license": "official public information; no licence stated", "source_sha256": sha}, ensure_ascii=False) + "\n"); n += 1; have.add(slug(nm))
print("parsed", len(names), "added", n)
