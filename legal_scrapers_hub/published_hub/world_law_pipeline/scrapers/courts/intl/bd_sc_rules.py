"""Bangladesh: Supreme Court rules from supremecourt.gov.bd 'Court Rules' page (official PDFs):
 - Supreme Court of Bangladesh (High Court Division) Rules, 1973 - Notification + Chapters I-XVI (incl. IA) as separate PDFs
   -> one rule row per chapter (granularity 'chapter').
 - Supreme Court of Bangladesh (Appellate Division) Rules, 1988 (apprule1.pdf, OCR'd scan; several ORDER headings are not recoverable)
   -> one document-level row, needs_review.
 - HCD Rules Appendices I-IV (forms: civil, criminal, contempt of court, writ petition) -> 4 form rows (bundle PDFs) in bd_forms.jsonl.
Skipped: the staff recruitment rules (Bangla) and the consolidated 'download all together' PDF. robots.txt -> 404 (robots_absent_allowed).
Dedupe by ids/sha256; re-runs add 0."""
import json, re, os, html, hashlib, datetime, subprocess, time, requests
ROOT = "/workspace/world_courts"; D = f"{ROOT}/data/bd"; RAW = f"{ROOT}/rules/raw/bd/sc"; FD = f"{ROOT}/forms/bd"
os.makedirs(RAW, exist_ok=True); os.makedirs(FD, exist_ok=True)
IDX = "https://www.supremecourt.gov.bd/web/?page=rules.php&menu=11&lang="; BASE = "https://www.supremecourt.gov.bd/resources/rules/"
UA = {"User-Agent": "Mozilla/5.0 (WorldCourtsResearchBot/1.0; public court data; polite)"}
POL = "robots_absent_allowed|supremecourt.gov.bd: Supreme Court of Bangladesh official website; no licence stated"
now = datetime.datetime.now(datetime.UTC).isoformat(); S = requests.Session()
def get(u):
    for i in range(3):
        try:
            r = S.get(u, headers=UA, timeout=180); time.sleep(2); r.raise_for_status(); return r
        except Exception as e:
            last = e; time.sleep(5)
    raise last
def fetch(rel):
    p = f"{RAW}/{rel.replace('/', '_')}"
    if not os.path.exists(p): open(p, "wb").write(get(BASE + rel).content)
    b = open(p, "rb").read(); return p, b, hashlib.sha256(b).hexdigest()
def text(p, minlen=200):
    t = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout.replace("\f", "\n").strip()
    return re.sub(r"\n{3,}", "\n\n", t) if len(re.sub(r"\s", "", t)) > minlen else None
page = get(IDX).text
links = [(html.unescape(re.sub(r"<[^>]+>|\s+", " ", m.group(2))).strip(), m.group(1).replace("../resources/rules/", ""))
         for m in re.finditer(r'<a[^>]+href="(\.\./resources/rules/[^"]+\.pdf)"[^>]*>(.*?)</a>', page, re.S)]
RP = f"{D}/bd_rules.jsonl"; FP = f"{D}/bd_forms.jsonl"
oldr = {json.loads(l)["rule_id"] for l in open(RP)}; olds = {json.loads(l)["pdf_sha256"] for l in open(FP)}
rules, forms = [], []
base = dict(jurisdiction="BD", effective_date=None, pdf_path=None, index_url=IDX, source_kind="official", site_policy=POL, retrieved_at=now,
            license="Supreme Court of Bangladesh official publication; no licence stated", language="en")
for label, rel in links:
    m = re.match(r"Chapter-([IVXL]+A?)\s*\((.+)\)", label)
    if rel.startswith("HighCourt/") and (m or label == "Notification"):
        num = f"Chapter {m.group(1)}" if m else "Notification"; ttl = m.group(2).strip() if m else "Notification (amendments)"
        rid = f"bd-hcd-rules-1973:{'ch' + m.group(1) if m else 'notification'}"
        if rid in oldr: continue
        p, b, sha = fetch(rel); t = text(p)
        rules.append(dict(base, rule_id=rid, rule_set_id="bd-hcd-rules-1973", court_id=None, rule_set="Supreme Court of Bangladesh (High Court Division) Rules, 1973",
            rule_number=num, title=ttl, text=t, pdf_sha256=sha, source_sha256=sha, source_url=BASE + rel, granularity="chapter",
            needs_review=t is None, extraction="pdftotext -layout (whole chapter)" if t else "image-only PDF; no text layer"))
    elif rel == "apprule1.pdf":
        rid = "bd-ad-rules-1988:document"
        if rid in oldr: continue
        p, b, sha = fetch(rel); t = text(p)
        rules.append(dict(base, rule_id=rid, rule_set_id="bd-ad-rules-1988", court_id=None, rule_set="Supreme Court of Bangladesh (Appellate Division) Rules, 1988",
            rule_number="Parts I-VII (whole rules)", title="The Supreme Court of Bangladesh (Appellate Division) Rules, 1988 (with amendments)", text=t,
            pdf_sha256=sha, source_sha256=sha, source_url=BASE + rel, granularity="document", needs_review=True,
            extraction="pdftotext of an OCR'd scan; order-level split not attempted because several ORDER headings are unreadable"))
    elif rel.startswith("HighCourt/APPENDIX-"):
        p, b, sha = fetch(rel)
        if sha in olds: continue
        olds.add(sha); fp = f"{FD}/{sha}.pdf"
        if not os.path.exists(fp): open(fp, "wb").write(b)
        forms.append({"form_id": f"bd-{sha[:16]}", "court_id": None, "jurisdiction": "BD", "form_number": rel.split("/")[-1][:-4],
            "title": f"Supreme Court (High Court Division) Rules, 1973 - {label}", "category": "Supreme Court HCD Rules appendix (form bundle)", "language": "en",
            "revision_date": None, "file_format": "pdf", "pdf_path": f"forms/bd/{sha}.pdf", "pdf_sha256": sha, "file_bytes": len(b), "source_url": BASE + rel,
            "index_url": IDX, "source_kind": "official", "site_policy": POL, "license": "Supreme Court of Bangladesh official publication; no licence stated",
            "retrieved_at": now, "note": "one PDF containing the set of prescribed forms in this appendix"})
with open(RP, "a") as f:
    for r in rules: f.write(json.dumps(r, ensure_ascii=False) + "\n")
with open(FP, "a") as f:
    for r in forms: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("rules", len(rules), "no_text", sum(1 for r in rules if not r["text"]), "forms", len(forms))
