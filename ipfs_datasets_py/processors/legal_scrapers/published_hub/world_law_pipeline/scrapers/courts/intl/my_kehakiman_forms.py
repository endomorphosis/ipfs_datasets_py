"""MY: Office of the Chief Registrar, Federal Court of Malaysia - 'Court Related Forms' page (kehakiman.gov.my, robots allow /sites/default/files)."""
import json, sys, re, datetime, hashlib, os, time, shutil, requests, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
from bs4 import BeautifulSoup as B
IDX = "https://www.kehakiman.gov.my/en/public-access/court-related-forms"; H = {"User-Agent": UA}
OUT = f"{ROOT}/data/my/my_forms.jsonl"; FD = f"{ROOT}/forms/my"; os.makedirs(FD, exist_ok=True)
old = rjl(OUT); osha = {r["pdf_sha256"] for r in old}; osrc = {r["source_url"] for r in old}
now = datetime.datetime.now(datetime.UTC).isoformat(); n = nb = 0; fail = []
s = B(requests.get(IDX, headers=H, timeout=60).text, "html.parser")
for tr in s.find_all("tr"):
    a = tr.find("a", href=True)
    if not a: continue
    if shutil.disk_usage("/workspace").free < 20 * 2**30: print("disk < 20 GB, pausing"); break
    title = re.sub(r"\s+", " ", tr.find("td").get_text(" ", strip=True))
    src = urllib.parse.urljoin(IDX, a["href"])
    if src in osrc: continue
    time.sleep(2)
    r = requests.get(src, headers=H, timeout=120)
    if r.status_code != 200 or len(r.content) < 500: fail.append((src, r.status_code)); continue
    ext = src.rsplit(".", 1)[-1].lower(); sha = hashlib.sha256(r.content).hexdigest()
    if sha in osha: continue
    open(f"{FD}/{sha}.{ext}", "wb").write(r.content)
    m = re.search(r"/files/(\d{4})-(\d{2})/", src)
    row = {"form_id": f"my-{sha[:16]}", "court_id": "my-federal-court" if title.startswith("Mahkamah Persekutuan") else None, "jurisdiction": "MY",
           "form_number": None, "title": title, "category": "kehakiman-court-related-forms", "language": "ms",
           "revision_date": None, "upload_month": f"{m.group(1)}-{m.group(2)}" if m else None, "file_format": ext,
           "pdf_path": f"forms/my/{sha}.{ext}", "pdf_sha256": sha, "file_bytes": len(r.content), "source_url": src, "index_url": IDX,
           "license": "Office of the Chief Registrar, Federal Court of Malaysia published forms; no licence stated",
           "site_policy": "robots_allowed", "retrieved_at": now}
    with open(OUT, "a") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
    osha.add(sha); n += 1; nb += len(r.content)
print("added", n, "bytes", nb, "fail", fail)
