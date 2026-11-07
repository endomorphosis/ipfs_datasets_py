"""BB: Magistrate's Courts (Criminal Procedure) Rules, 2001 (Cap. 116A, L.R.O. 2007) rule-level rows from the official PDF on
barbadoslawcourts.gov.bb (robots allows; crawl-delay 10 respected). Titles from the Arrangement of Rules; marginal notes stripped heuristically."""
import json, os, re, hashlib, datetime, subprocess
ROOT = "/workspace/world_courts"
SRC = "https://www.barbadoslawcourts.gov.bb/assets/content/pdfs/subsidiary_legislation_of_barbados/Magistrate'sCourts(CriminalProcedure)Rules,2001Cap116A'A.pdf"
IDX = "https://www.barbadoslawcourts.gov.bb/useful-links/for-legal-professionals/rules-of-court/"
RAW = f"{ROOT}/rules/raw/bb/bb_mccpr2001.pdf"; OUT = f"{ROOT}/data/bb/bb_rules.jsonl"
now = datetime.datetime.now(datetime.UTC).isoformat(); sha = hashlib.sha256(open(RAW, "rb").read()).hexdigest()
L0 = subprocess.run(["pdftotext", "-layout", RAW, "-"], capture_output=True, text=True).stdout.replace("\f", "\n").splitlines()
JUNK = re.compile(r"THE LAWS OF BARBADOS|Printed by the Government Printer|by the authority of the Government|L\.R\.O\. 2007|^\s*Procedure\) Rules, 2001\s*$|^\s*rs?\.\s?\d|Cap\. 116A\.?\s*$|CAP\. 116A")
start = [i for i, l in enumerate(L0) if re.match(r"^\s*1\.\s+These Rules may be cited", l)][0]
toc = {}
for l in L0[:start]:
    m = re.match(r"^\s*(\d{1,3})\.\s+(.+?)\.?\s*$", l)
    if m: toc.setdefault(int(m.group(1)), m.group(2).strip())
end = [i for i, l in enumerate(L0) if i > start and re.fullmatch(r"\s*FIRST SCHEDULE\s*", l)][0]
L = []
for l in L0[start:end]:
    if JUNK.search(l): continue
    st = len(l) - len(l.lstrip())
    if st >= 64 and len(l.strip()) <= 24: continue                       # right-margin note line
    l = re.sub(r"^(\S[^ ]*(?: [^ ]+){0,2})\s{2,}(?=\S)", lambda m: " " * len(m.group(0)), l) if st == 0 and re.match(r"^\S.{0,16}?\s{2,}\S", l) else l  # left margin
    l = re.sub(r"\s{2,}\S.{0,22}$", "", l) if len(l) > 70 and re.search(r"\s{2,}\S.{0,22}$", l) and l.rfind("  ") >= 60 else l  # right margin
    L.append(l)
cand, prev = [], 0
for i, l in enumerate(L):
    m = re.match(r"^\s*(\d{1,3})\.\s+(?:\(\d+\)\s*)?\S", l)
    if m and int(m.group(1)) == prev + 1: prev += 1; cand.append((i, prev))
rows = []
for j, (i, n) in enumerate(cand):
    e = cand[j + 1][0] if j + 1 < len(cand) else len(L)
    blk = []
    for x in L[i:e]:
        if re.match(r"^\s*_{3,}\s*$", x) or "ARRANGEMENT OF FORMS" in x: break
        if x.strip(): blk.append(x.strip())
    while len(blk) > 1 and toc.get(n + 1) is None and False: pass
    # drop trailing cross-heading lines (centred headings such as 'Committal Proceedings')
    while len(blk) > 1 and re.fullmatch(r"[A-Z][A-Za-z ,'()]{2,60}", blk[-1]) and not blk[-1].endswith("."): blk.pop()
    rows.append({"rule_id": f"bb-mccpr-2001:r{n}", "rule_set_id": "bb-mccpr-2001", "court_id": None, "jurisdiction": "BB",
        "rule_set": "Magistrate's Courts (Criminal Procedure) Rules, 2001 (Cap. 116A)", "rule_number": f"Rule {n}", "title": toc.get(n),
        "text": re.sub(r"\s+", " ", " ".join(blk)).strip(), "effective_date": "2001-09-20", "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha,
        "source_url": SRC, "index_url": IDX, "site_policy": "robots_allowed (crawl-delay 10 respected)", "retrieved_at": now,
        "license": "Laws of Barbados (L.R.O. 2007), printed by the Government Printer by authority of the Government of Barbados; official public text, no licence stated",
        "language": "en", "needs_review": True, "extraction": "pdftotext layout; marginal notes stripped heuristically (some may remain inline)"})
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
new = [x for x in rows if x["rule_id"] not in old]
if os.environ.get("DRY"): print(len(rows), len(toc)); [print(r["rule_number"], "|", r["title"], "|", r["text"][:220]) for r in rows[:5] + rows[-2:]]; raise SystemExit
with open(OUT, "a") as f:
    for x in new: f.write(json.dumps(x, ensure_ascii=False) + "\n")
print("parsed", len(rows), "added", len(new))
