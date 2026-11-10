#!/usr/bin/env python3
"""Sri Lanka Civil Procedure Code (Cap. 105/101) First Schedule prescribed forms, from the
official LawNet PDF (lawnet.gov.lk/wp-content/uploads/2016/11/CIVIL-PROCEDURE-CODE.pdf) via the
Wayback Machine (live lawnet.gov.lk unreachable). Text layer is ABBYY OCR of a printed revision,
so every row is needs_review. One row per 'No. N' form; append-only, dedup by form_id."""
import json, re, os, hashlib, subprocess, datetime, urllib.request, shutil, base64
W = "/workspace/world_courts"; RAW = f"{W}/rules/raw/lk/lk_cpc.pdf"
ORIG = "https://www.lawnet.gov.lk/wp-content/uploads/2016/11/CIVIL-PROCEDURE-CODE.pdf"; TS = "20240502160500"
WB = f"https://web.archive.org/web/{TS}id_/{ORIG}"; DIGEST = "2DEXJEIAKIYG43V7PO3BY2W23NYE5UYX"
UA = "WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
b = open(RAW, "rb").read() if os.path.exists(RAW) else b""
if base64.b32encode(hashlib.sha1(b).digest()).decode() != DIGEST:
    b = urllib.request.urlopen(urllib.request.Request(WB, headers={"User-Agent": UA}), timeout=120).read()
sha = hashlib.sha256(b).hexdigest(); os.makedirs(f"{W}/forms/lk", exist_ok=True)
dst = f"{W}/forms/lk/{sha}.pdf"
if not os.path.exists(dst): open(dst, "wb").write(b)
txt = subprocess.run(["pdftotext", "-layout", dst, "-"], capture_output=True, text=True).stdout
pages = txt.split("\f")
# locate First Schedule .. Second Schedule
start = next(i for i, p in enumerate(pages) if re.search(r"^\s{30,}FIRST SCHEDULE\s*$", p, re.M))
end = next(i for i, p in enumerate(pages) if i > start and re.search(r"^\s{30,}SECOND SCHEDULE", p, re.M))
lines = []
for pi in range(start, end + 1):
    pl = pages[pi].split("\n")
    if pi == start: pl = pl[next(k for k, l in enumerate(pl) if "FIRST SCHEDULE" in l):]
    if pi == end: pl = pl[:next(k for k, l in enumerate(pl) if "SECOND SCHEDULE" in l)]
    lines += [(pi + 1, l) for l in pl]
hdr = re.compile(r"^\s{8,}N[o0][\.,]\s?(\d{1,3}\s?[A-Za-z]?)\.?\s*$")
forms, cur = [], None
for pg, l in lines:
    m = hdr.match(l)
    if m:
        cur = {"no": m.group(1).replace(" ", "").upper(), "page": pg, "lines": []}; forms.append(cur); continue
    if cur is not None and not re.match(r"^\s*(Cap\. 10[15]\]|CIVIL PROCEDURE CODE|V\s?/\s?\d+)\s*", l.strip() and l or "x"):
        cur["lines"].append(l)
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
out = f"{W}/data/lk/lk_forms.jsonl"; have = set()
if os.path.exists(out):
    have = {json.loads(l)["form_id"] for l in open(out) if l.strip()}
rows, seen = [], set()
for f in forms:
    body = "\n".join(x.rstrip() for x in f["lines"]).strip()
    sec = re.search(r"\[\s*(Sections?[^\]]{1,60})\]", body)
    tl = re.search(r"^\s*(?:\[[^\]]*\]\s*)?((?:FORM|NOTICE|SUMMONS|DECREE|WARRANT|PLAINT|AFFIDAVIT|ORDER|PRECEPT|APPLICATION|PROCLAMATION|CERTIFICATE|BOND|RETURN|PETITION)\b[^\n]{3,160})", body, re.M)
    title = re.sub(r"\s{2,}", " ", tl.group(1)).strip() if tl else None
    if title: title = re.sub(r"\s*\[[^\]]*\]?\s*$", "", title).strip()
    if title: title = re.sub(r"\bO F\b", "OF", re.sub(r"\bT H E\b|\bTH E\b", "THE", title)).title()
    fid = f"lk-cpc-schedule1-form-{f['no'].lower()}"
    if fid in seen: fid += f"-p{f['page']}"
    seen.add(fid)
    if fid in have: continue
    rows.append({"form_id": fid, "court_id": None, "jurisdiction": "LK", "form_number": f"No. {f['no']}",
        "title": title or f"Civil Procedure Code First Schedule Form No. {f['no']}",
        "category": "Civil Procedure Code (Cap. 105), First Schedule (Forms)", "language": "en",
        "revision_date": None, "file_format": "pdf", "pdf_path": f"forms/lk/{sha}.pdf", "pdf_sha256": sha,
        "file_bytes": len(b), "pdf_start_page": f["page"], "rule_reference": sec.group(1).strip() if sec else None,
        "rule_set_id": "lk-cpc", "text": body[:20000], "source_url": f"https://web.archive.org/web/{TS}/{ORIG}",
        "original_url": ORIG, "index_url": "https://www.lawnet.gov.lk/civil-procedure-code-4/", "source_kind": "official_archived",
        "site_policy": "robots_unknown:lawnet.gov.lk unreachable live 2026-11-04 (robots ignored per user authorization), archived copy used (Wayback id_)|official Ministry of Justice LawNet publication of Sri Lanka written law; no licence stated",
        "retrieved_at": now, "license": "Sri Lanka written law (public legislation); no licence stated",
        "extraction": "pdftotext -layout of ABBYY OCR text layer; split on 'No. N' headings", "needs_review": True,
        "record_note": "prescribed form printed in the CPC First Schedule (statutory form text, not a fillable court file); pdf_start_page = 1-based PDF page"})
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "a") as fh:
    for r in rows: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print("forms parsed", len(forms), "added", len(rows), "pages", start + 1, end + 1)
for r in rows[:5] + rows[-3:]: print(r["form_number"], r["pdf_start_page"], r["rule_reference"], "|", r["title"])
