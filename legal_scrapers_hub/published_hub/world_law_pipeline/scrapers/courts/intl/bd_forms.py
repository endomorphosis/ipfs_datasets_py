"""BD: civil (dewani), criminal (foujdari) and legal-aid forms from the Dhaka District Judiciary portal (judiciary.gov.bd; robots: no rules). Internal administrative/ACR forms skipped."""
import json, sys, re, datetime, hashlib, os, time, requests
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
from bs4 import BeautifulSoup as B
now = datetime.datetime.now(datetime.UTC).isoformat(); OUT = f"{ROOT}/data/bd/bd_forms.jsonl"; FD = f"{ROOT}/forms/bd"; os.makedirs(FD, exist_ok=True)
old = {json.loads(l)["pdf_sha256"] for l in open(OUT)} if os.path.exists(OUT) else set(); rows = []; H = {"User-Agent": "world-courts-research/0.3"}
for cat, label in [("form-dewani", "civil"), ("form-foujdari", "criminal"), ("form-legal-aid", "legal-aid")]:
    idx = f"https://dhaka.judiciary.gov.bd/en/{cat}"; s = B(requests.get(idx, headers=H, timeout=40).text, "html.parser"); time.sleep(3)
    for tr in s.select("tr"):
        a = tr.find("a", href=re.compile(r"\.(pdf|docx?)$", re.I)); tds = tr.find_all("td")
        if not a or len(tds) < 2: continue
        title = tds[1].get_text(" ", strip=True); u = a["href"].replace(" ", "%20")
        r = requests.get(u, headers=H, timeout=90); time.sleep(3)
        if r.status_code != 200 or len(r.content) < 500: continue
        sha = hashlib.sha256(r.content).hexdigest(); ext = u.rsplit(".", 1)[-1].lower()
        if sha in old or sha in {x["pdf_sha256"] for x in rows}: continue
        open(f"{FD}/{sha}.{ext}", "wb").write(r.content)
        rows.append({"form_id": f"bd-{sha[:16]}", "court_id": None, "jurisdiction": "BD", "form_number": None, "title": title, "category": f"district-court-{label}",
          "language": "bn" if re.search(r"[\u0980-\u09FF]", title) else "en", "file_format": ext, "pdf_path": f"forms/bd/{sha}.{ext}", "pdf_sha256": sha,
          "file_bytes": len(r.content), "source_url": u, "index_url": idx, "license": "Bangladesh District Judiciary published court forms; no licence stated",
          "site_policy": "robots_allowed(no rules; content-signal preamble only)", "retrieved_at": now})
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(rows))
