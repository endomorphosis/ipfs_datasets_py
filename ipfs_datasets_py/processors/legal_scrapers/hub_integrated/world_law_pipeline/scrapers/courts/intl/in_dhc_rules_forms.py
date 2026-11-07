"""India - Delhi High Court (delhihighcourt.nic.in, official):
 - Court Rules page (/web/court-rules, paginated): 'High Court Rules and Orders' Volumes I-V (chapter PDFs) and the Delhi High Court
   (Original Side) Rules, 2018 chapters -> one rule row per chapter (granularity 'chapter'), text via pdftotext (null if scanned).
   Skipped: the consolidated Original Side Rules PDF (chapters are ingested), Appendices A-G (statutes / judges' service rules /
   advocates' etiquette) and the lawyers' chambers allotment rules.
 - Forms & Proformas page (/web/online-forms-downloadable-forms, paginated): litigant/advocate forms -> forms/in/<sha256>.pdf.
   Skipped staff/HR items (medical facilities, government accommodation, Delhi Judicial Service attestation) and notices/procedures.
robots.txt returns 404 (robots_absent_allowed). Polite 1.5-2 s delays. Dedupe by ids; re-runs add 0."""
import json, re, os, html, hashlib, datetime, subprocess, time, requests
ROOT = "/workspace/world_courts"; D = f"{ROOT}/data/in"; RAW = f"{ROOT}/rules/raw/in/dhc"; FD = f"{ROOT}/forms/in"
os.makedirs(RAW, exist_ok=True); os.makedirs(FD, exist_ok=True)
BASE = "https://delhihighcourt.nic.in"; UA = {"User-Agent": "Mozilla/5.0 (WorldCourtsResearchBot/1.0; public court data; polite)"}
POL = "robots_absent_allowed|delhihighcourt.nic.in: Delhi High Court official website (NIC); no licence stated"
now = datetime.datetime.now(datetime.UTC).isoformat(); S = requests.Session()
def get(u):
    for i in range(3):
        try:
            r = S.get(u, headers=UA, timeout=120); time.sleep(1.5); r.raise_for_status(); return r
        except Exception as e:
            last = e; time.sleep(5)
    raise last
def listing(path):
    out = []
    for pg in range(0, 40):
        h = get(f"{BASE}/web/{path}?page={pg}").text; rows = []
        for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", h, re.S):
            cells = [html.unescape(re.sub(r"<[^>]+>|\s+", " ", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)]
            link = re.search(r'href="([^"]+\.pdf)"', m.group(1))
            if len(cells) > 1 and link: rows.append((cells[1], link.group(1) if link.group(1).startswith("http") else BASE + link.group(1)))
        new = [r for r in rows if r not in out]
        if not new: break
        out += new
    return out
def rules():
    P = f"{D}/in_rules.jsonl"; old = {json.loads(l)["rule_id"] for l in open(P)}; rows = []; idx = f"{BASE}/web/court-rules"
    for title, url in listing("court-rules"):
        t = re.sub(r"\s+", " ", title).strip()
        m = re.match(r"Volume\s+([ivx]+)\s+chapter\s+(\d+(?:\([a-z]\))?)\s*:\s*(.+)", t, re.I)
        if m:
            vol, ch, ttl = m.group(1).upper(), m.group(2), m.group(3).strip()
            sid, sname, num = "in-dhc-rules-orders", "High Court Rules and Orders (Delhi High Court), Volumes I-V", f"Vol. {vol}, Chapter {ch}"
        else:
            m = re.match(r"Chapter\s+(\d+(?:\([a-z]\))?)\s*:\s*(.+)", t, re.I)
            if not m: continue
            ch, ttl = m.group(1), m.group(2).strip()
            sid, sname, num = "in-dhc-original-side-2018", "Delhi High Court (Original Side) Rules, 2018", f"Chapter {ch}"
        rid = f"{sid}:{num.lower().replace('vol. ', 'v').replace(', chapter ', '-ch').replace('chapter ', 'ch').replace(' ', '')}"
        if rid in old or any(r["rule_id"] == rid for r in rows): continue
        p = f"{RAW}/{url.rsplit('/', 1)[1]}"
        if not os.path.exists(p): open(p, "wb").write(get(url).content)
        sha = hashlib.sha256(open(p, "rb").read()).hexdigest()
        txt = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout.replace("\f", "\n").strip()
        txt = re.sub(r"\n{3,}", "\n\n", txt) if len(re.sub(r"\s", "", txt)) > 200 else None
        rows.append({"rule_id": rid, "rule_set_id": sid, "court_id": "in-hc-delhi", "jurisdiction": "IN", "subdivision": "IN-DL", "rule_set": sname,
            "rule_number": num, "title": ttl[:1].upper() + ttl[1:], "text": txt, "effective_date": None, "pdf_path": None, "pdf_sha256": sha,
            "source_sha256": sha, "source_url": url, "index_url": idx, "source_kind": "official", "site_policy": POL, "retrieved_at": now,
            "granularity": "chapter", "license": "Delhi High Court official publication; no licence stated", "language": "en",
            "needs_review": txt is None, "extraction": "pdftotext -layout (whole chapter)" if txt else "image-only PDF; no text layer"})
    with open(P, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows), sum(1 for r in rows if r["text"] is None)
SKIPF = re.compile(r"Medical Facilities|Government Accommodation|Attestation Form|^Notice regarding|^Procedure for Online Gate Pass", re.I)
def forms():
    P = f"{D}/in_forms.jsonl"; olds = {json.loads(l)["pdf_sha256"] for l in open(P)}; oldu = {json.loads(l)["source_url"] for l in open(P)}
    rows = []; idx = f"{BASE}/web/online-forms-downloadable-forms"
    for title, url in listing("online-forms-downloadable-forms"):
        if SKIPF.search(title) or url in oldu: continue
        b = get(url).content
        if not b.startswith(b"%PDF"): continue
        sha = hashlib.sha256(b).hexdigest()
        if sha in olds: continue
        olds.add(sha); p = f"{FD}/{sha}.pdf"
        if not os.path.exists(p): open(p, "wb").write(b)
        rows.append({"form_id": f"in-{sha[:16]}", "court_id": "in-hc-delhi", "jurisdiction": "IN", "subdivision": "IN-DL", "form_number": None,
            "title": re.sub(r"\s+", " ", title).strip().rstrip("."), "category": "Delhi High Court forms & proformas", "language": "en", "revision_date": None,
            "file_format": "pdf", "pdf_path": f"forms/in/{sha}.pdf", "pdf_sha256": sha, "file_bytes": len(b), "source_url": url, "index_url": idx,
            "source_kind": "official", "site_policy": POL, "license": "Delhi High Court official form; no licence stated", "retrieved_at": now})
    with open(P, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)
if __name__ == "__main__":
    print("forms added", forms()); print("rules added/no_text", rules())
