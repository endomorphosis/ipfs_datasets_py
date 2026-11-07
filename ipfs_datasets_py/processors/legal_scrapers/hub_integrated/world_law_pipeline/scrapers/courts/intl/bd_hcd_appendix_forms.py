#!/usr/bin/env python3
"""Bangladesh Supreme Court (High Court Division) Rules, 1973 Appendices I-IV —
prescribed court forms (Civil / Criminal / Contempt / Writ).

Source: official supremecourt.gov.bd PDFs under resources/rules/HighCourt/APPENDIX-{I,II,III,IV}.pdf
(cached at rules/raw/bd/sc/). Scanned OCR text layer is noisy (Bangla glyphs), so individual
form rows are needs_review; titles prefer English labels recovered near the Form No. header.

Writes:
  - one bundle form row per appendix PDF (category = HCD Rules appendix form bundle)
  - one row per Form No. recovered in each appendix (pdf_start_page set; shared pdf_sha256)

Append-only; dedupe by form_id and by pdf_sha256 for bundles.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_COURTS = _ipfs_Path(_ipfs_os.environ.get("WORLD_COURTS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_courts")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, re, os, hashlib, shutil, subprocess, datetime

W = str(_COURTS)
RAW = f"{W}/rules/raw/bd/sc"
FD = f"{W}/forms/bd"
OUT = f"{W}/data/bd/bd_forms.jsonl"
BASE = "https://www.supremecourt.gov.bd/resources/rules/HighCourt/"
IDX = "https://www.supremecourt.gov.bd/web/?page=rules.php&menu=11"
POL = "robots_absent_allowed|supremecourt.gov.bd: Supreme Court of Bangladesh official website; public court rules/forms, no licence stated"
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()

APPS = {
    "I":   ("Civil forms", "civil"),
    "II":  ("Criminal forms", "criminal"),
    "III": ("Contempt of court forms", "contempt"),
    "IV":  ("Writ petition forms", "writ"),
}

# Known English titles (OCR-assisted; needs_review remains True for safety)
TITLE_HINTS = {
    ("I", "1"): "Form No. 1 (Civil) [Omitted]",
    ("I", "1A"): "In Re Register (Writ/Civil/Criminal/Miscellaneous)",
    ("I", "2"): "Notice — Subordinate Court's Record",
    ("I", "3"): "Form No. 3 (Civil) [Omitted]",
    ("I", "4"): "Notice to Respondent/Opposite party about the day fixed for appearance and hearing",
    ("I", "4A"): "Form No. 4A (Civil)",
    ("I", "5"): "Copy of Urgent Order",
    ("I", "6"): "Notice for Grant of Certificate for appeal to Appellate Division",
    ("I", "10"): "Form No. 10 (Civil/Criminal/Writ)",
    ("I", "15"): "Detailed statement of costs incurred in the preparation of Paper-book",
    ("I", "15A"): "Form No. 15A (Civil) [Omitted]",
    ("I", "16"): "Appellant's List",
    ("I", "17"): "Respondent's List",
    ("I", "18"): "Estimated cost of Paper-book as per Appellant's List",
    ("I", "19"): "Estimated cost of Paper-book as per Respondent's List",
    ("I", "24"): "Form No. 24 (Civil) — estimate of costs for copy",
    ("I", "24A"): "Application for Photostat Copy",
    ("I", "25"): "Register of application for copy, stamps, folios and information application",
    ("I", "26"): "Title Page (Part I)",
    ("I", "27"): "Title Page (Part II)",
    ("I", "27A"): "Title Page (preservation periods)",
    ("I", "27B"): "Title Page (Part II — destroy after 3 years)",
    ("I", "28"): "Application for inspection",
    ("I", "29"): "Application for Information",
    ("I", "31"): "Form No. 31 (Civil)",
}

os.makedirs(FD, exist_ok=True)
have_id = set()
have_sha = set()
if os.path.exists(OUT):
    for line in open(OUT):
        if not line.strip():
            continue
        r = json.loads(line)
        have_id.add(r["form_id"])
        if r.get("pdf_sha256"):
            have_sha.add(r["pdf_sha256"])

rows = []

def add(row):
    if row["form_id"] in have_id or row["form_id"] in {x["form_id"] for x in rows}:
        return
    rows.append(row)
    have_id.add(row["form_id"])

HDR = re.compile(
    r"Form\s+No\.?\s*([0-9]+[A-Z]?)\s*(?:\(([^)]{0,40})\))?[,\s]*Appendix\s*[I1l|IV]{0,3}",
    re.I,
)
SKIP = re.compile(r"substituted|inserted by|was inserted|contd\.?\)|Appendix I was", re.I)

for letter, (label, kind) in APPS.items():
    src_path = f"{RAW}/HighCourt_APPENDIX-{letter}.pdf"
    if not os.path.exists(src_path) or os.path.getsize(src_path) < 1000:
        print("skip missing/empty", letter); continue
    blob = open(src_path, "rb").read()
    sha = hashlib.sha256(blob).hexdigest()
    dst = f"{FD}/{sha}.pdf"
    if not os.path.exists(dst):
        shutil.copy2(src_path, dst)
    src_url = BASE + f"APPENDIX-{letter}.pdf"

    # bundle row
    bid = f"bd-hcd-app{letter.lower()}-bundle"
    if bid not in have_id and sha not in have_sha:
        add({
            "form_id": bid, "court_id": "bd-high-court-division", "jurisdiction": "BD",
            "form_number": f"HCD Rules 1973 Appendix {letter}",
            "title": f"Supreme Court (High Court Division) Rules, 1973 — Appendix {letter} ({label})",
            "category": f"Supreme Court HCD Rules appendix (form bundle — {kind})",
            "language": "en", "revision_date": None, "file_format": "pdf",
            "pdf_path": f"forms/bd/{sha}.pdf", "pdf_sha256": sha, "file_bytes": len(blob),
            "source_url": src_url, "index_url": IDX, "source_kind": "official",
            "site_policy": POL, "license": "Supreme Court of Bangladesh official publication; no licence stated",
            "retrieved_at": NOW, "needs_review": False,
            "record_note": "one PDF containing the set of prescribed forms in this appendix",
        })
        have_sha.add(sha)

    # individual forms
    text = subprocess.run(["pdftotext", "-layout", src_path, "-"], capture_output=True, text=True).stdout
    pages = text.split("\f")
    seen_nos = set()
    for pi, page in enumerate(pages):
        lines = [l for l in page.split("\n") if l.strip()]
        for i, line in enumerate(lines[:30]):
            if SKIP.search(line):
                continue
            m = HDR.search(line) or re.search(r"Form\s+No\.?\s*([0-9]+[A-Z]?)\s*(?:\(([^)]{0,40})\))?", line, re.I)
            if not m:
                continue
            no = m.group(1)
            # normalize kind from paren
            paren = (m.group(2) or kind).strip()
            paren_l = paren.lower()
            if "omit" in page[max(0, page.find(line)): page.find(line) + 200].lower() and "Omitted by Notification" in page:
                omitted = True
            else:
                omitted = "Omitted by Notification" in "\n".join(lines[i:i+5])
            key = no.upper()
            if key in seen_nos:
                continue
            # skip footnote/substitution echoes later on page
            if "was substituted" in line.lower() or "was inserted" in line.lower():
                continue
            seen_nos.add(key)
            fid = f"bd-hcd-app{letter.lower()}-form-{no.lower()}"
            title = TITLE_HINTS.get((letter, no))
            if not title:
                # pull a short English-ish candidate after header
                cands = []
                for x in lines[i + 1:i + 12]:
                    xs = x.strip()
                    if re.search(r"SUPREME\s+COURT|HIGH\s+COURT", xs, re.I):
                        continue
                    if len(xs) < 4 or re.search(r"[\u0980-\u09FF]", xs):
                        continue
                    if sum(c.isascii() for c in xs) / max(1, len(xs)) < 0.75:
                        continue
                    if sum(c.isalpha() for c in xs) < 5:
                        continue
                    if re.match(r"^[\[!\(]|District\s*\|", xs):
                        continue
                    cands.append(re.sub(r"\s+", " ", xs))
                title = cands[0][:160] if cands else f"Form No. {no} ({paren})"
            if omitted and "[Omitted]" not in title:
                title = title + " [Omitted]"
            rule = None
            chunk = "\n".join(lines[i:i + 4])
            rm = re.search(r"\((Rules?\s*[^)]*?HCD\s*Rules)\)", chunk, re.I) or re.search(r"\((Rule[^)]{3,60})\)", chunk, re.I)
            if rm:
                rule = re.sub(r"\s+", " ", rm.group(1)).strip()
            add({
                "form_id": fid, "court_id": "bd-high-court-division", "jurisdiction": "BD",
                "form_number": f"Appendix {letter} Form No. {no}" + (f" ({paren})" if paren else ""),
                "title": title, "category": f"Supreme Court HCD Rules 1973 Appendix {letter}: {label}",
                "language": "en", "revision_date": None, "file_format": "pdf",
                "pdf_path": f"forms/bd/{sha}.pdf", "pdf_sha256": sha, "file_bytes": len(blob),
                "pdf_start_page": pi + 1, "rule_set_id": "bd-hcd-rules-1973",
                "applies_to": ["Supreme Court of Bangladesh, High Court Division"],
                "source_url": src_url, "index_url": IDX, "source_kind": "official",
                "issuer": "Supreme Court of Bangladesh",
                "site_policy": POL, "license": "Supreme Court of Bangladesh official publication; no licence stated",
                "retrieved_at": NOW, "needs_review": True,
                "extraction": f"pdftotext -layout of scanned HCD Appendix {letter}; OCR noisy; title heuristic"
                              + (f"; rule ref: {rule}" if rule else ""),
                "record_note": ("form omitted by later notification" if omitted else None),
            })
            break  # one primary form header per page

with open(OUT, "a") as fh:
    for r in rows:
        # drop None-valued optional keys for cleanliness
        r = {k: v for k, v in r.items() if v is not None}
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print("BD HCD appendix forms new", len(rows),
      {k: sum(1 for r in rows if r["form_id"].startswith(f"bd-hcd-app{k.lower()}")) for k in APPS})
