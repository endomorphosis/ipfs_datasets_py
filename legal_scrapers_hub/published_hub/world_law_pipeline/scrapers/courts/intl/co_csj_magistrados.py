"""CO: magistrates of the Corte Suprema de Justicia from cortesuprema.gov.co 'La Corte - Magistrados Integrantes' profile pages linked from the
home page (robots: only /wp-admin/ disallowed). Names (page <title>) and official title only; 3 s delay between requests."""
import json, re, html, datetime, hashlib, os, time, requests
ROOT = "/workspace/world_courts"; UA = "Mozilla/5.0 (world_courts research; public court data)"
OUT = f"{ROOT}/data/co/co_judges.jsonl"; CID = "co-corte-suprema-de-justicia"; HOME = "https://cortesuprema.gov.co/"
now = datetime.datetime.now(datetime.UTC).isoformat()
t = requests.get(HOME, headers={"User-Agent": UA}, timeout=60).text; time.sleep(3)
links = sorted(set(re.findall(r'href="(https://cortesuprema.gov.co/la-corte-magistrados-integrantes-[^"]+)"', t)))
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
import unicodedata
def asc(s): return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []; have = {slug(asc(x["name"])) for x in old}; n = 0
def tc(s): return " ".join(w if w in ("de", "del", "la") else w.capitalize() for w in s.lower().split())
with open(OUT, "a") as f:
    for u in links:
        r = requests.get(u, headers={"User-Agent": UA}, timeout=60); time.sleep(3)
        if r.status_code != 200: print("fail", u, r.status_code); continue
        ti = html.unescape(re.search(r"<title>(.*?)</title>", r.text, re.S).group(1))
        m = re.search(r"Integrantes\s*-\s*(Magistrad[ao]|Presidente|Presidenta|Vicepresidente|Vicepresidenta)\s+(.+?)\s+-\s+Corte Suprema", ti)
        if not m: print("noparse", ti); continue
        role, name = m.group(1), tc(m.group(2).strip())
        if slug(asc(name)) in have: continue
        title = {"Presidente": "Presidente, Corte Suprema de Justicia", "Presidenta": "Presidenta, Corte Suprema de Justicia",
                 "Vicepresidente": "Vicepresidente, Corte Suprema de Justicia", "Vicepresidenta": "Vicepresidenta, Corte Suprema de Justicia"}.get(role, f"{role}, Corte Suprema de Justicia")
        f.write(json.dumps({"judge_id": f"co-csj-{slug(asc(name))}", "court_id": CID, "name": name, "title": title,
            "position_type": "chief" if role.startswith("Presiden") else "associate", "term_start": None, "term_end": None, "status": "sitting",
            "roster_url": HOME, "source_url": u, "site_policy": "robots_allowed", "retrieved_at": now, "needs_review": False,
            "extraction": "CSJ 'Magistrados Integrantes' profile page title (name/title only)", "license": "Rama Judicial de Colombia website (facts)",
            "source_sha256": hashlib.sha256(r.content).hexdigest()}, ensure_ascii=False) + "\n"); n += 1; have.add(slug(asc(name)))
print("links", len(links), "added", n)
