"""BT: Judiciary of Bhutan 'judicial forms' page (judiciary.gov.bt/posts/first-category/jud-forms; robots Allow: /). Form number = file stem (G1, H11 ...)."""
import json, sys, re, datetime, hashlib, os, time, shutil, requests, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
from bs4 import BeautifulSoup as B
IDX = "https://www.judiciary.gov.bt/posts/first-category/jud-forms"; H = {"User-Agent": UA}
OUT = f"{ROOT}/data/bt/bt_forms.jsonl"; FD = f"{ROOT}/forms/bt"; os.makedirs(FD, exist_ok=True)
old = rjl(OUT); osha = {r["pdf_sha256"] for r in old}; osrc = {r["source_url"] for r in old}
now = datetime.datetime.now(datetime.UTC).isoformat(); n = nb = 0; fail = []; seen = set()
s = B(requests.get(IDX, headers=H, timeout=60).text, "html.parser")
for a in s.find_all("a", href=True):
    h = a["href"]
    if not re.search(r"\.(pdf|docx?)$", h, re.I): continue
    src = urllib.parse.urljoin(IDX, h)
    if src in seen or src in osrc: continue
    seen.add(src)
    if shutil.disk_usage("/workspace").free < 20 * 2**30: print("disk < 20 GB, pausing"); break
    time.sleep(2)
    try: r = requests.get(src, headers=H, timeout=120)
    except requests.RequestException as e: fail.append((src, str(e)[:50])); continue
    if r.status_code != 200 or len(r.content) < 500: fail.append((src, r.status_code)); continue
    ext = src.rsplit(".", 1)[-1].lower(); sha = hashlib.sha256(r.content).hexdigest()
    if sha in osha: continue
    open(f"{FD}/{sha}.{ext}", "wb").write(r.content)
    row = {"form_id": f"bt-{sha[:16]}", "court_id": None, "jurisdiction": "BT", "form_number": os.path.splitext(os.path.basename(src))[0],
           "title": re.sub(r"\s+", " ", a.get_text(" ", strip=True)), "category": "judiciary-judicial-forms", "language": "dz",
           "revision_date": None, "file_format": ext, "pdf_path": f"forms/bt/{sha}.{ext}", "pdf_sha256": sha, "file_bytes": len(r.content),
           "source_url": src, "index_url": IDX, "license": "Judiciary of Bhutan published forms; no licence stated",
           "site_policy": "robots_allowed", "retrieved_at": now, "record_note": "language assumed Dzongkha (titles are English on the index page); needs review"}
    with open(OUT, "a") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
    osha.add(sha); n += 1; nb += len(r.content)
print("added", n, "bytes", nb, "fail", fail)
