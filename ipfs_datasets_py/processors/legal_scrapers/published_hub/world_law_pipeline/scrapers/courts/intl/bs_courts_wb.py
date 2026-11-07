"""BS: Judiciary of The Bahamas (courts.bs) via Wayback Machine id_ snapshots (live courts.bs returns HTTP 500 from the box).
1) judges: 'Judicial Officers' page (Chief Justice, Supreme Court Justices, Supreme Court Registrars, Stipendiary & Circuit Magistrates):
   name + official position only (emails, phones, room numbers and appointment dates on the page are NOT stored).
2) rules: Supreme Court Civil Procedure Rules 2022 (reprint, Extraordinary Gazette 9 Jan 2024) split into Part-level rows, if archived."""
import json, re, sys, os, hashlib, datetime, time, subprocess, requests, unicodedata
from bs4 import BeautifulSoup as B
ROOT = "/workspace/world_courts"; H = {"User-Agent": "Mozilla/5.0 (world_courts research; public court data)"}
now = datetime.datetime.now(datetime.UTC).isoformat(); dry = "--dry" in sys.argv
POL = "robots_unknown:live courts.bs HTTP 500, archived copy used (Wayback id_)|courts.bs: (c) Judiciary The Bahamas, no licence stated"
def slug(s): return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()).strip("-")
def rjl(p): return [json.loads(l) for l in open(p)] if os.path.exists(p) else []
def wb(url, ts="2026"):
    for k in range(4):
        try:
            r = requests.get(f"https://web.archive.org/web/{ts}id_/{url}", headers=H, timeout=180); time.sleep(5)
            if r.status_code == 200: return r, re.search(r"/web/(\d{14})id_/", r.url).group(1)
            if r.status_code == 404: return None, None
        except requests.RequestException as e: print("wb err", str(e)[:60])
        time.sleep(20 * (k + 1))
    return None, None
# ---- judges
JO = "https://courts.bs/judicial-officers/"; OUTJ = f"{ROOT}/data/bs/bs_judges.jsonl"
r, ts = wb(JO); assert r is not None, "judicial-officers not archived"
sha = hashlib.sha256(r.content).hexdigest(); s = B(r.text, "html.parser")
for x in s(["script", "style"]): x.decompose()
T = s.get_text("\n", strip=True).split("\n")
st = T.index("Officers of The Judiciary"); sec = None; rows = []; have = {slug(o["name"]) for o in rjl(OUTJ)}
SECS = {"Chief Justice": "bs-supreme-court", "Supreme Court Justices": "bs-supreme-court", "Supreme Court Registrars": "bs-supreme-court",
        "Stipendiary and Circuit Magistrates": "bs-lower-court"}
for i in range(st, len(T)):
    if T[i] in SECS and (i + 1 < len(T) and T[i+1] != "Position"): sec = T[i]; continue
    if T[i] == "Position" and sec and i >= 1:
        name = T[i-1].strip(); pos = T[i+1].strip()
        if name in ("Assistant", "Acting", "Deputy Coroner", "Acting Coroner") or len(name) < 4: continue
        k = slug(re.sub(r"\s+(Kt|KC)\.?$", "", name).strip())
        if k in have: continue
        have.add(k); pl = pos.lower()
        pt = "chief" if pl.startswith(("chief justice", "acting chief magistrate", "chief magistrate")) else "registrar" if "registrar" in pl else \
             "magistrate" if "magistrate" in pl else "associate"
        rows.append({"judge_id": f"bs-{k}", "court_id": SECS[sec], "name": re.sub(r"\s+(Kt|KC)\.?$", "", name).strip(), "name_as_listed": name,
            "title": pos, "position_type": pt, "roster_section": sec, "term_start": None, "term_end": None,
            "status": "acting" if "acting" in pl else "sitting", "jurisdiction": "BS", "roster_url": JO, "source_url": f"https://web.archive.org/web/{ts}/{JO}",
            "source_kind": "archive", "archive_timestamp": ts, "site_policy": POL, "retrieved_at": now, "needs_review": True,
            "extraction": "courts.bs Judicial Officers page via Wayback snapshot (name + official position only)",
            "record_note": f"from archived snapshot {ts[:8]}; live site unreachable, roster may have changed",
            "license": "official public information; no licence stated", "source_sha256": sha})
if not dry and rows:
    with open(OUTJ, "a") as f:
        for x in rows: f.write(json.dumps(x, ensure_ascii=False) + "\n")
print("judges added", len(rows), [(x["name"], x["title"]) for x in rows][:60])
# ---- CPR 2022 (reprint) rules (rule-level) + First Schedule forms
import shutil
CPR = "https://courts.bs/wp-content/uploads/2024/02/Extraordinary-Gazette-January-9-2024-A-Supreme-Court-Civil-Procedure-Rules-Reprint.-Final.pdf"
if shutil.disk_usage("/workspace").free < 20 * 2**30: raise SystemExit("disk < 20 GB, pausing")
r, ts2 = wb(CPR)
if r is None or not r.content.startswith(b"%PDF"): raise SystemExit("CPR PDF not archived")
csha = hashlib.sha256(r.content).hexdigest(); os.makedirs(f"{ROOT}/forms/bs", exist_ok=True)
PDFP = f"{ROOT}/forms/bs/{csha}.pdf"
if not os.path.exists(PDFP): open(PDFP, "wb").write(r.content)
RAW = subprocess.run(["pdftotext", "-layout", PDFP, "-"], capture_output=True, text=True).stdout
pages = RAW.split("\f"); L = []; PG = []
for pi, ptxt in enumerate(pages):
    for l in ptxt.split("\n"): L.append(l); PG.append(pi + 1)
CPOL = POL.replace("courts.bs: (c)", "Bahamas subsidiary legislation (S.I.), published in Extraordinary Gazette 9 Jan 2024; courts.bs (c)")
SRCU = f"https://web.archive.org/web/{ts2}/{CPR}"
body0 = next(i for i, l in enumerate(L) if i > 900 and re.match(r"\s*PART 1 - OVERRIDING OBJECTIVE", l))
sched = next(i for i, l in enumerate(L) if i > body0 and re.match(r"^\s*FIRST SCHEDULE\s*$", l))
toc = {}
for l in L[20:body0]:
    m = re.match(r"^\s*(\d{1,2})\.{1,2}(\d{1,2}[A-Z]?)\s+(\S.*?)[\s.]*\d*\s*$", l)
    if m: toc.setdefault(f"{m.group(1)}.{m.group(2)}", re.sub(r"\.{2,}.*$", "", m.group(3)).strip(" ."))
parts = {}
for i in range(body0, sched):
    m = re.match(r"^\s*PART (\d+[A-Z]?)\s*[-–]\s*(.*)$", L[i])
    if m: parts[i] = m.group(1)
noise = re.compile(r"^\s*Page - \d+\s*$|^\s*Supreme Court Civil Procedure Rules, 2022\s*$")
heads = []; seen = set()
for i in range(body0, sched):
    m = re.match(r"^\s{0,9}(\d{1,2}\.\d{1,2}[A-Z]?)\s+([A-Z(“\"‘'].*)$", L[i])
    if m and m.group(1) in toc and m.group(1) not in seen: seen.add(m.group(1)); heads.append((m.group(1), i))
OUTR = f"{ROOT}/data/bs/bs_rules.jsonl"; oldr = {o["rule_id"] for o in rjl(OUTR)}; rrows = []
for k, (num, i) in enumerate(heads):
    e = heads[k+1][1] if k + 1 < len(heads) else sched
    seg = [x for x in L[i:e] if not noise.match(x) and not re.match(r"^\s*PART \d+", x)]
    txt = re.sub(r"\s+", " ", " ".join(x.strip() for x in seg)).strip()
    rid = f"bs-cpr-2022:r{num}"
    if rid in oldr: continue
    rrows.append({"rule_id": rid, "rule_set_id": "bs-cpr-2022", "court_id": "bs-supreme-court", "jurisdiction": "BS",
        "rule_set": "Supreme Court Civil Procedure Rules, 2022 (reprint, Extraordinary Gazette 9 January 2024)", "rule_number": num,
        "part": num.split(".")[0], "title": toc[num], "text": txt, "effective_date": None, "pdf_path": os.path.relpath(PDFP, ROOT), "pdf_sha256": csha,
        "source_sha256": csha, "pdf_page": PG[i], "source_url": SRCU, "original_url": CPR, "index_url": "https://courts.bs/new-civil-procedure-rules-2022/",
        "source_kind": "archive", "site_policy": CPOL, "retrieved_at": now, "license": "Bahamas subsidiary legislation; no licence stated", "language": "en",
        "record_note": "text extracted from PDF layout; may include footnote markers/notes (S.I. amendment references)"})
# First Schedule forms
OUTF = f"{ROOT}/data/bs/bs_forms.jsonl"; oldf = {o["form_id"] for o in rjl(OUTF)}; frows = []
end2 = next(i for i, l in enumerate(L) if i > sched and re.match(r"^\s*SECOND SCHEDULE\s*$", l))
for i in range(sched, end2):
    m = re.match(r"^\s*FORM\s+([A-Z]{0,3}\d+[A-Z]?)\s*[:.–-]\s*(.+?)\s*$", L[i])
    if not m: continue
    no = m.group(1); t = re.sub(r"(Form)\d+$", r"\1", m.group(2)).strip(); fid = f"bs-cpr-2022-form-{no.lower()}"
    if fid in oldf: continue
    oldf.add(fid)
    rr = next((re.sub(r"\s+", " ", L[j].strip()) for j in range(max(sched, i - 4), i) if re.match(r"^\s*\(Rules?\s", L[j])), None)
    frows.append({"form_id": fid, "court_id": "bs-supreme-court", "jurisdiction": "BS", "form_number": no, "title": t,
        "category": "Supreme Court Civil Procedure Rules 2022, First Schedule (Forms)", "language": "en", "revision_date": "2024-01-09", "file_format": "pdf",
        "pdf_path": os.path.relpath(PDFP, ROOT), "pdf_sha256": csha, "file_bytes": len(r.content), "pdf_start_page": PG[i], "rule_reference": rr,
        "source_url": SRCU, "original_url": CPR, "index_url": "https://courts.bs/new-civil-procedure-rules-2022/", "source_kind": "archive",
        "site_policy": CPOL, "retrieved_at": now, "license": "Bahamas subsidiary legislation; no licence stated",
        "record_note": "prescribed form inside the consolidated CPR 2022 reprint PDF; pdf_start_page = PDF page index"})
if not dry:
    for p_, rows_ in ((OUTR, rrows), (OUTF, frows)):
        with open(p_, "a") as f:
            for x in rows_: f.write(json.dumps(x, ensure_ascii=False) + "\n")
print("toc rules", len(toc), "rules added", len(rrows), "forms added", len(frows))
