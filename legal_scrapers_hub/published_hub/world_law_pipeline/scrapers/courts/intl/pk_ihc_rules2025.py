"""PK: Islamabad High Court rules (official, live mis.ihc.gov.pk 'IHC Rules' list = ihc.asmx/GetLatestNews pFeature=10, the page's own
unauthenticated feed). Chapter-level rows with OCR text from the Gazette of Pakistan PDFs:
 - S.R.O. 169(I)/2025 (7 Feb 2025, in force 4 Feb 2025): Civil Courts Rules IHC (Vol I & II), Instructions to Criminal Courts (Vol III),
   IHC Superintendence and Control (Subordinate Judiciary) Rules (Vol IV), IHC Practice and Procedure Rules 2025 (Vol V)
 - Establishment of Special Court (Overseas Pakistanis Property) Rules, 2026 (one rule-level split)
Gazette scan text layer is OCR -> noisy -> needs_review. Chapter numbers are OCR-normalised; out-of-order headings are renumbered sequentially.
Scanned PDFs without text layer (ADR Rules 2018, Judicial Service Tribunals Rules, ADR Mediation Accreditation Rules 2023) are skipped (no OCR on box).
Usage: pk_ihc_rules2025.py [--dry]  (expects PDFs in rules/raw/pk_ihc/, downloaded politely by the run)"""
import json, re, sys, hashlib, subprocess, datetime, os
ROOT = "/workspace/world_courts"; RAW = f"{ROOT}/rules/raw/pk_ihc"; OUT = f"{ROOT}/data/pk/pk_rules.jsonl"
COURT = "osm:way/780222423"; B = "https://mis.ihc.gov.pk/attachments/news/"
POL = "robots_absent_allowed|mis.ihc.gov.pk robots.txt 404 (no restrictions); official Islamabad High Court website, no terms of use stated"
LIC = "Rules made by the Islamabad High Court under Art. 202 of the Constitution (Gazette of Pakistan); no open licence stated"
now = datetime.datetime.now(datetime.timezone.utc).isoformat(); MAXT = 150000
def txt(fn): return subprocess.run(["pdftotext", "-layout", f"{RAW}/{fn}", "-"], capture_output=True, text=True).stdout
def sha(fn): return hashlib.sha256(open(f"{RAW}/{fn}", "rb").read()).hexdigest()
OCRD = str.maketrans({"I": "1", "l": "1", "O": "0", "o": "0", "T": "7", "S": "8", "Z": "2"})
HEAD = re.compile(r"^\s{8,}CHA[PT]?T?PTER\s*[-._]*\s*([0-9IlOoTSZ]{1,3})\s*$")
def clean(s): return re.sub(r"\n{3,}", "\n\n", s).strip()
rows = []
F1 = "IHC_Rules_Notification_2025__639039898493657836.pdf"; s1 = sha(F1); L = txt(F1).splitlines()
def find(pat, start=0):
    for i in range(start, len(L)):
        if re.match(pat, L[i]): return i
    raise SystemExit("marker not found " + pat)
v3 = find(r"^\s+VOLUME\.III\s*$"); v4 = find(r"^\s+VOLUME-IV\s*$", find(r"^\s+VOLUME\.IV\s*$")); v5 = find(r"^\s+VOLUME-V\s*$", find(r"^\s+VOLUME\.V\s*$"))
b12 = 265  # body of Vol I & II starts after its table of contents (first 'CHAPTER I' at body)
b12 = next(i for i in range(200, v3) if HEAD.match(L[i]))
b3 = next(i for i in range(v3 + 100, v4) if HEAD.match(L[i]))
VOLS = [("vol1-2", "Civil Courts Rules, Islamabad High Court, Islamabad (Volume I & II)", b12, find(r"^\s+VOLUME\.III\s*$")),
        ("vol3", "Instructions to Criminal Courts, Islamabad High Court (Volume III)", b3, find(r"^\s+VOLUME\.IV\s*$")),
        ("vol4", "Islamabad High Court Superintendence and Control (Subordinate Judiciary) Rules (Volume IV)", v4, find(r"^\s+VOLUME\.V\s*$")),
        ("vol5", "Islamabad High Court Practice and Procedure Rules, 2025 (Volume V)", v5, len(L))]
for key, rs, a, b in VOLS:
    seg = L[a:b]; heads = []; prev = 0
    for j, ln in enumerate(seg):
        m = HEAD.match(ln)
        if not m: continue
        try: n = int(m.group(1).translate(OCRD))
        except ValueError: continue
        if n <= prev or n > prev + 3: n = prev + 1
        heads.append((j, n, ln.strip())); prev = n
    if heads and heads[0][0] > 5:
        pre = clean("\n".join(seg[:heads[0][0]]))
        if len(pre) > 200: heads.insert(0, (0, 0, "(text before first OCR-detected chapter heading)"))
    for k, (j, n, raw) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(seg)
        body = clean("\n".join(seg[j + (0 if n == 0 else 1):end]))
        title = next((x.strip(" ()") for x in body.splitlines() if len(x.strip()) > 3), "")[:200]
        rid = f"pk-ihc-rules-2025-{key}:" + (f"ch{n}" if n else "pre")
        rows.append({"rule_id": rid, "rule_set_id": f"pk-ihc-rules-2025-{key}", "court_id": COURT, "jurisdiction": "PK-IS", "rule_set": rs,
            "rule_number": f"{key.replace('vol', 'Volume ').replace('1-2', 'I & II')}, Chapter {n}" if n else f"{key} preliminary text",
            "title": title, "part": None, "text": body[:MAXT], "effective_date": "2025-02-04", "pdf_path": f"rules/raw/pk_ihc/{F1}", "pdf_sha256": s1,
            "source_sha256": s1, "source_url": B + F1, "index_url": "https://mis.ihc.gov.pk/frmDetails.aspx?Type=10", "source_kind": "official",
            "site_policy": POL, "license": LIC, "retrieved_at": now, "language": "en", "needs_review": True,
            "version_note": f"S.R.O. 169(I)/2025, Gazette of Pakistan Extraordinary 18 Feb 2025; OCR text; heading OCR '{raw}'"})
F2 = "Special_Court_Overseas_Pakistanis_Property_Rules_2026___639100435865819753.pdf"; s2 = sha(F2); T = txt(F2)
TL = T.splitlines(); hs = []; prev = 0
for j, ln in enumerate(TL):
    m = re.match(r"^\s{6,12}(\d{1,2})\s*[:.]\s*[·]?\s*([A-Z][^\n]{2,90}?)\s*\.?\s*[-—–]", ln)
    if m and prev < int(m.group(1)) <= prev + 3: hs.append((j, int(m.group(1)), m.group(2))); prev = int(m.group(1))
for k, (j, n, t) in enumerate(hs):
    end = hs[k + 1][0] if k + 1 < len(hs) else len(TL)
    rows.append({"rule_id": f"pk-ihc-sc-opp-rules-2026:r{n}", "rule_set_id": "pk-ihc-sc-opp-rules-2026", "court_id": COURT, "jurisdiction": "PK-IS",
        "rule_set": "Establishment of Special Court (Overseas Pakistanis Property) Rules, 2026", "rule_number": str(n), "title": t.strip(" .-·"),
        "part": None, "text": clean("\n".join(TL[j:end]))[:MAXT], "effective_date": "2026-03-11", "pdf_path": f"rules/raw/pk_ihc/{F2}", "pdf_sha256": s2, "source_sha256": s2,
        "source_url": B + F2, "index_url": "https://mis.ihc.gov.pk/frmDetails.aspx?Type=10", "source_kind": "official", "site_policy": POL, "license": LIC,
        "retrieved_at": now, "language": "en", "needs_review": True, "version_note": "S.R.O. 524(I)/2025 [sic], Gazette of Pakistan Extraordinary 18 Mar 2026; OCR text; rule numbers missed by OCR are merged into the preceding rule"})
have = {json.loads(l)["rule_id"] for l in open(OUT) if l.strip()}
new = [r for r in rows if r["rule_id"] not in have]
from collections import Counter
print(Counter(r["rule_set_id"] for r in rows), "new", len(new))
for r in rows[:3] + rows[-3:]: print(r["rule_id"], "|", r["title"][:70], len(r["text"]))
if "--dry" not in sys.argv:
    with open(OUT, "a") as f:
        for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("wrote", len(new))
