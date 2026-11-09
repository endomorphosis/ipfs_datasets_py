"""Bermuda judges (names + official titles only) from the official Bermuda Judiciary Annual Report 2025 (gov.bm),
pages 12-15 (Court of Appeal, Supreme Court, Magistracy). Registrars/staff and temporary Assistant Justices skipped.
Sir Christopher Clarke skipped: report records his retirement as President (Nov 2025); Ian Kawaley is named President.
Every name is verified to occur in the PDF text before writing. Rows needs_review (roster as of the 2025 report)."""
import json, re, os, hashlib, datetime, subprocess, urllib.request, time
ROOT = "/workspace/world_courts"; OUT = f"{ROOT}/data/bm/bm_judges.jsonl"
SRC = "https://www.gov.bm/files/media-library/20260619/1f3864aa-16336-judiciaryannual-report_v04_online.pdf"
IDX = "https://www.gov.bm/supreme-court"
RAW = f"{ROOT}/state/run_20261101_06/bm/ar2025.pdf"
UA = {"User-Agent": "Mozilla/5.0 world-courts-research (public court data)"}
if not os.path.exists(RAW):
    os.makedirs(os.path.dirname(RAW), exist_ok=True); time.sleep(2)
    open(RAW, "wb").write(urllib.request.urlopen(urllib.request.Request(SRC, headers=UA), timeout=180).read())
sha = hashlib.sha256(open(RAW, "rb").read()).hexdigest()
T = re.sub(r"\s+", " ", subprocess.run(["pdftotext", "-layout", RAW, "-"], capture_output=True, text=True).stdout).upper()
J = [("bm-court-of-appeal", "Ian Kawaley", "President of the Court of Appeal", "president", "MR. IAN KAWALEY"),
     ("bm-court-of-appeal", "Geoffrey Bell", "Justice of Appeal", "appellate", "MR. GEOFFREY BELL"),
     ("bm-court-of-appeal", "Sir Anthony Smellie", "Justice of Appeal", "appellate", "SIR ANTHONY SMELLIE"),
     ("bm-court-of-appeal", "Dame Elizabeth Gloster", "Justice of Appeal", "appellate", "DAME ELIZABETH GLOSTER"),
     ("bm-court-of-appeal", "Narinder K. Hargun", "Justice of Appeal", "appellate", "MR. NARINDER K. HARGUN"),
     ("bm-court-of-appeal", "Sir Gary Hickinbottom", "Justice of Appeal", "appellate", "SIR GARY HICKINBOTTOM"),
     ("bm-supreme-court", "Larry Mussenden", "Chief Justice", "chief", "MR. LARRY MUSSENDEN"),
     ("bm-supreme-court", "Nicole Stoneham", "Puisne Judge", "judge", "MS. NICOLE STONEHAM"),
     ("bm-supreme-court", "Shade Subair Williams", "Puisne Judge", "judge", "MRS. SHADE SUBAIR WILLIAMS"),
     ("bm-supreme-court", "Andrew Martin", "Puisne Judge", "judge", "MR. ANDREW MARTIN"),
     ("bm-supreme-court", "Alexandra Wheatley", "Acting Puisne Judge", "acting", "MS. ALEXANDRA WHEATLEY"),
     ("bm-supreme-court", "Juan Wolffe", "Puisne Judge", "judge", "MR. JUAN WOLFFE"),
     ("bm-supreme-court", "Alan Richards", "Puisne Judge", "judge", "MR. ALAN RICHARDS"),
     ("bm-magistrates-court", "Maxanne Anderson", "Senior Magistrate", "magistrate", "MAXANNE ANDERSON, JP"),
     ("bm-magistrates-court", "Tyrone Chin", "Magistrate", "magistrate", "TYRONE CHIN, JP"),
     ("bm-magistrates-court", "Craig Attridge", "Magistrate", "magistrate", "CRAIG ATTRIDGE, JP"),
     ("bm-magistrates-court", "Maria Sofianos", "Magistrate", "magistrate", "MARIA SOFIANOS, JP"),
     ("bm-magistrates-court", "Aura Cassidy", "Magistrate", "magistrate", "AURA CASSIDY, JP")]
old = {json.loads(l)["judge_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
now = datetime.datetime.now(datetime.UTC).isoformat(); rows = []
for court, name, title, pt, needle in J:
    assert needle in T, needle
    jid = f"{court}-{re.sub(r'[^a-z0-9]+', '-', re.sub(r'^(sir|dame) ', '', name.lower())).strip('-')}"
    if jid in old: continue
    rows.append({"judge_id": jid, "court_id": court, "name": name, "title": title, "position_type": pt, "term_start": None, "term_end": None,
        "status": "sitting", "jurisdiction": "BM", "roster_url": IDX, "source_url": SRC, "source_kind": "official",
        "site_policy": "no_robots_txt|gov.bm: Government of Bermuda website terms (no open licence stated)", "retrieved_at": now,
        "needs_review": True, "extraction": "Bermuda Judiciary Annual Report 2025, judicial officer photo pages (pp. 12-15)",
        "license": "Government of Bermuda official publication (facts)", "source_sha256": sha})
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(rows))
