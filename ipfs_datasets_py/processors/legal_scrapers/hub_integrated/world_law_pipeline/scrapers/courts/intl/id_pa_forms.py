"""ID: Pengadilan Agama (religious court, under MA/Badilag) public forms pages. Files are hosted as public Google Drive shares linked from the official court site."""
import json, sys, re, datetime, hashlib, os, time, requests
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
from bs4 import BeautifulSoup as B
now = datetime.datetime.now(datetime.UTC).isoformat(); OUT = f"{ROOT}/data/id/id_forms.jsonl"; FD = f"{ROOT}/forms/id"; os.makedirs(FD, exist_ok=True)
SITES = [("pa-gedongtataan", "Pengadilan Agama Gedong Tataan", "https://www.pa-gedongtataan.go.id/pagepdf-7-formulir-berperkara", 3, "robots_allowed"),
         ("pa-tenggarong", "Pengadilan Agama Tenggarong", "https://www.pa-tenggarong.go.id/layanan-hukum/formulir-gugatan-1", 10, "robots_allowed(crawl-delay 10)")]
old = {json.loads(l)["pdf_sha256"] for l in open(OUT)} if os.path.exists(OUT) else set(); H = {"User-Agent": "world-courts-research/0.3"}; n = 0; fail = []
for key, court, idx, delay, pol in SITES:
    s = B(requests.get(idx, headers=H, timeout=40).text, "html.parser"); time.sleep(delay)
    for a in s.find_all("a", href=re.compile(r"drive\.google\.com/file/d/")):
        fid = re.search(r"/file/d/([\w-]+)", a["href"]).group(1)
        title = (a.get("aria-label") or "").replace("Unduh ", "").strip()
        if not title:
            tr = a.find_parent("tr"); tds = tr.find_all("td") if tr else []
            title = tds[1].get_text(" ", strip=True) if len(tds) > 1 else ""
        if not title or re.match(r"(?i)panduan", title): continue
        r = requests.get(f"https://drive.google.com/uc?export=download&id={fid}", headers=H, timeout=90); time.sleep(3)
        c = r.content; ext = "pdf" if c[:4] == b"%PDF" else ("docx" if c[:2] == b"PK" else ("doc" if c[:4] == b"\xd0\xcf\x11\xe0" else None))
        if r.status_code != 200 or not ext: fail.append((title, r.status_code)); continue
        sha = hashlib.sha256(c).hexdigest()
        if sha in old: continue
        open(f"{FD}/{sha}.{ext}", "wb").write(c); old.add(sha); n += 1
        row = {"form_id": f"id-{sha[:16]}", "court_id": None, "jurisdiction": "ID", "form_number": None, "title": title.title() if title.isupper() else title,
          "category": f"pengadilan-agama-formulir:{key}", "language": "id", "file_format": ext, "pdf_path": f"forms/id/{sha}.{ext}", "pdf_sha256": sha, "file_bytes": len(c),
          "source_url": a["href"], "index_url": idx, "license": f"{court} public court forms (Badilag/Mahkamah Agung RI); no licence stated",
          "site_policy": f"{pol};file_host:drive.google.com(public share linked from official site)", "retrieved_at": now}
        open(OUT, "a").write(json.dumps(row, ensure_ascii=False) + "\n")
print("added", n, "fail", fail)
