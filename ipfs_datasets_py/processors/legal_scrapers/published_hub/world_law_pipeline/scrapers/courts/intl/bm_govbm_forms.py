"""Bermuda court forms from the official Government of Bermuda portal (www.gov.bm): Judiciary, Supreme Court,
Court of Appeal and Magistrates' Court pages. Downloads each form once (sha256-named under forms/bm/), appends
rows to data/bm/bm_forms.jsonl (dedupe by source_url and sha256). gov.bm serves no robots.txt (returns the HTML app).
Polite: 2s between requests. Guidance notes, circulars, schedules, reports and non-court bodies (CICB, liquor licensing) skipped."""
import json, re, os, html, hashlib, datetime, time, urllib.request, urllib.parse
ROOT = "/workspace/world_courts"; OUT = f"{ROOT}/data/bm/bm_forms.jsonl"; FD = f"{ROOT}/forms/bm"
UA = {"User-Agent": "Mozilla/5.0 world-courts-research (public court data)"}
BASE = "https://www.gov.bm"
PAGES = {"department/judiciary": "bm-supreme-court", "supreme-court": "bm-supreme-court", "court-appeal": "bm-court-of-appeal",
         "magistrates-court": "bm-magistrates-court"}
KEEP = re.compile(r"^(FORM \d|Application to Allow Children|Consent Order|Summons$|Affidavit$|Declaration of Parentage|Case Management Form|"
                  r"Notice of Appeal|Notice of Motion for Leave|Notice of Application|Request a Record of your Traffic)", re.I)
now = datetime.datetime.now(datetime.UTC).isoformat()
def get(u):
    time.sleep(2); return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=90).read()
os.makedirs(FD, exist_ok=True)
rows_old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []
seen_url = {r["source_url"] for r in rows_old}; seen_sha = {r["pdf_sha256"] for r in rows_old}
cand = {}
for path, court in PAGES.items():
    t = get(f"{BASE}/{path}").decode("utf-8", "replace")
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', t, flags=re.S):
        h = html.unescape(m.group(1)); title = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).split())
        if not ("/files/" in h or h.startswith("/media/")) or h.endswith("?download") or "guidance" in title.lower(): continue
        title = re.sub(r"\.pdf$", "", title, flags=re.I).strip()
        if not KEEP.search(title): continue
        if title == "Consent Order":
            sl = re.search(r"consent_order-_(.+?)\.pdf", h)
            if sl: title = f"Consent Order - {sl.group(1).replace('_', ' ').strip().capitalize()}"
        u = urllib.parse.urljoin(BASE + "/", h)
        cand.setdefault(u, (title, court, f"{BASE}/{path}"))
rows = []
for u, (title, court, idx) in cand.items():
    if u in seen_url: continue
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120); b = r.read(); ct = r.headers.get("Content-Type", ""); time.sleep(2)
    except Exception as ex: print("fail", u, ex); continue
    ext = "pdf" if b[:4] == b"%PDF" else "doc" if b[:4] == b"\xd0\xcf\x11\xe0" else "docx" if b[:2] == b"PK" else None
    if not ext: print("skip non-doc", u, ct); continue
    sha = hashlib.sha256(b).hexdigest()
    if sha in seen_sha: print("dup sha", u); continue
    seen_sha.add(sha); p = f"forms/bm/{sha}.{ext}"; open(f"{ROOT}/{p}", "wb").write(b)
    num = re.match(r"FORM (\d+)", title, re.I)
    m2 = re.search(r"_form_(\d+)\.doc", u)
    cat = ("criminal" if "criminal" in u or "conviction" in title.lower() or "sentence" in title.lower() or re.match(r"FORM \d", title, re.I)
           else "family" if court == "bm-supreme-court" and not title.startswith("Case Management") else "traffic" if "traffic" in u else "civil")
    if "civil" in u: cat = "civil"
    rows.append({"form_id": f"bm-{sha[:16]}", "court_id": court, "jurisdiction": "BM",
        "form_number": f"Form {num.group(1)}" if num else (f"Form {m2.group(1)}" if m2 else None), "title": title, "category": cat,
        "language": "en", "file_format": ext, "pdf_path": p, "pdf_sha256": sha, "file_bytes": len(b), "source_url": u, "index_url": idx,
        "source_kind": "official", "site_policy": "no_robots_txt|gov.bm: Government of Bermuda website terms (no open licence stated)",
        "license": "Government of Bermuda official court form; no licence stated", "retrieved_at": now})
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("candidates", len(cand), "added", len(rows))
for r in rows: print(r["court_id"], r["form_number"], r["title"], r["file_format"], r["category"])
