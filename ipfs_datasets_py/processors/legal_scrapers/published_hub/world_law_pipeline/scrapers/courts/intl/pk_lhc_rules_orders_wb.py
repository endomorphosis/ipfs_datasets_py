"""PK: Rules and Orders of the Lahore High Court, Volumes I-V (procedural instructions to civil & criminal courts of Punjab,
judicial administration, and proceedings in the High Court), chapter-level rows with full text.
lhc.gov.pk is unreachable from the box, so the official PDFs are taken from Wayback Machine id_ captures (2013-2014) found via
the Wayback CDX (state/run_20261101_18/cc_probe.jsonl). Text-layer PDFs (pdftotext); some OCR noise -> needs_review.
Chapter headings are accepted only in increasing numeric order (embedded Roman-numbered sub-chapters stay with their parent).
Usage: [LHC_PDF_DIR=dir_with_previously_downloaded_volumeN.pdf] pk_lhc_rules_orders_wb.py [--dry]"""
import json, re, sys, time, hashlib, subprocess, tempfile, datetime, os, requests
UA = "WorldCourtsResearchBot/1.0 (+https://huggingface.co/datasets/endomorphosis/world_courts; polite research crawl)"
OUT = "/workspace/world_courts/data/pk/pk_rules.jsonl"; COURT = "osm:node/2953146416"  # Lahore High Court
VOLS = [("I", "20130919093933", "http://lhc.gov.pk/downloads/rules_and_orders/volume1.pdf", "Instructions to Civil Courts"),
        ("II", "20130919110807", "http://lhc.gov.pk/downloads/rules_and_orders/volume2.pdf", "Instructions to Civil Courts: Special Jurisdiction and Accounts"),
        ("III", "20130612174512", "http://lhc.gov.pk:80/downloads/rules_and_orders/volume3.pdf", "Instructions to Criminal Courts"),
        ("IV", "20140712061137", "http://lhc.gov.pk/downloads/rules_and_orders/volume4.pdf", "Superintendence, Control and Judicial Administration"),
        ("V", "20130919110541", "http://lhc.gov.pk/downloads/rules_and_orders/volume5.pdf", "Proceedings in the High Court (Revised Edition 2005)")]
ROM = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
HEAD = re.compile(r"^\s*CHAPTER\s+([0-9]+|[IVXL]+)\s*[-–]?\s*([A-Z])?\s*$")
MAXT = 150000
def fetch(u):
    try:
        r = requests.get(u, headers={"User-Agent": UA}, timeout=600); r.raise_for_status(); c = r.content
    except requests.exceptions.SSLError:  # python TLS EOF to web.archive.org from this box; curl works
        with tempfile.NamedTemporaryFile() as f:
            subprocess.run(["curl", "-s", "-f", "-m", "600", "-A", UA, "-o", f.name, u], check=True); c = open(f.name, "rb").read()
    time.sleep(5); return c
def main():
    dry = "--dry" in sys.argv; now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    have = set()
    if os.path.exists(OUT):
        for l in open(OUT):
            if l.strip(): have.add(json.loads(l)["rule_id"])
    rows = []
    for vol, ts, src, vtitle in VOLS:
        wb = f"https://web.archive.org/web/{ts}id_/{src}"
        cache = os.path.join(os.environ.get("LHC_PDF_DIR", "/nonexistent"), os.path.basename(src))
        try: pdf = open(cache, "rb").read() if os.path.exists(cache) else fetch(wb)
        except Exception as e: print("vol", vol, "fetch failed", str(e)[:80]); continue
        if not pdf.startswith(b"%PDF"): print("vol", vol, "not a pdf"); continue
        sha = hashlib.sha256(pdf).hexdigest()
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(pdf); f.flush(); lines = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout.splitlines()
        heads, last = [], 0
        for i, l in enumerate(lines):
            m = HEAD.match(l)
            if not m: continue
            n = int(m.group(1)) if m.group(1).isdigit() else ROM.get(m.group(1), 0)
            if n > last: heads.append((i, n, (m.group(2) or ""))); last = n
        rs = f"pk-lhc-rules-orders-vol{vol.lower()}"
        for k, (i, n, suf) in enumerate(heads):
            j = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
            body = [x for x in lines[i + 1:j]]
            title = next((x.strip() for x in body if x.strip()), "")
            text = re.sub(r"[ \t]+", " ", "\n".join(x.strip() for x in body)); text = re.sub(r"\n{3,}", "\n\n", text).strip()
            trunc = len(text) > MAXT
            if len(text) < 40: continue
            rid = f"{rs}:ch{n}{suf.lower()}"
            rows.append({"rule_id": rid, "rule_set_id": rs, "court_id": COURT, "jurisdiction": "PK",
                "rule_set": f"Rules and Orders of the Lahore High Court, Lahore - Volume {vol}: {vtitle}",
                "rule_number": f"Volume {vol}, Chapter {n}{suf}", "title": title[:300], "part": None, "text": text[:MAXT],
                "effective_date": None, "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha, "source_url": src, "index_url": wb,
                "source_kind": "official", "site_policy": f"archived_copy(wayback:{ts[:8]});origin_unreachable|lhc.gov.pk robots not checked (origin unreachable); official High Court publication",
                "license": "Rules made by the Lahore High Court (Government of Punjab/Pakistan official rules; no open licence stated)",
                "retrieved_at": now, "language": "en", "needs_review": True,
                "version_note": f"Wayback capture {ts[:8]} of the LHC-published consolidated volume; later amendments by LHC notifications may not be reflected" + ("; text truncated at 150k chars" if trunc else "")})
        print("vol", vol, "chapters", len(heads))
    new = [r for r in rows if r["rule_id"] not in have]
    print("parsed", len(rows), "new", len(new))
    if not dry and new:
        with open(OUT, "a") as f:
            for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
main()
