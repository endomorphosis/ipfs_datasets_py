"""MCGM (Brihanmumbai Municipal Corporation, wd:Q1195653) bye-laws / regulations — live fetch of PDFs.
robots.txt: portal.mcgm.gov.in/robots.txt -> 404 (RFC 9309: allow all). 3 s between requests."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, json, re, time, subprocess, hashlib, os, tempfile, argparse
from datetime import datetime, timezone
import requests
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from schema import validate_record, validate_file, place_key
B = "https://portal.mcgm.gov.in/irj/go/km/docs/documents/MCGM%20Department%20List/"
DOCS = [
 ("Solid%20Waste%20Management/Docs/Bye%20laws/02%20Greater%20Mumbai%20Cleanliness%20Byelaws%20-%202006.pdf",
  "Greater Mumbai Cleanliness and Sanitation Bye-laws, 2006", "ordinance", "2006-12-12", "BMC 2326/4074/C.R.238/06/UD-21"),
 ("ChiefEngineerSolidWasteManagement/RTI%20Manuals/BMC-SWM-Byelaws2025-version%20English.pdf",
  "Solid Waste (Management & Handling), Cleanliness and Sanitation Bye-laws for Brihanmumbai Municipal Corporation, 2025 (draft for vetting)", "ordinance", "2025-02", None),
 ("Chief%20Engineer%20%28Development%20Plan%29/Docs/SANCTIONED%20DP2034/DCPR/DCPR%202034.pdf",
  "Development Control and Promotion Regulations for Greater Mumbai 2034 (DCPR 2034)", "regulation", "2018-11-08", "TPB 4317/629/CR-118/2017/DP/UD-11"),
]
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--stage", action="store_true"); a = ap.parse_args()
    S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (world-law municipal research crawler)"
    rb = S.get("https://portal.mcgm.gov.in/robots.txt", timeout=30)
    policy = "robots_404_allow_rfc9309" if rb.status_code == 404 else "robots_allowed_rfc9309"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"); recs = []
    for rel, title, dt, date, num in DOCS:
        url = B + rel; time.sleep(3)
        r = S.get(url, timeout=180)
        if r.status_code != 200 or not r.content.startswith(b"%PDF"): print("skip", r.status_code, url); continue
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(r.content); f.flush()
            txt = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout
        if len(txt.strip()) < 500: print("no text", url); continue
        rec = {"place_id": "wd:Q1195653", "country_code": "IN", "doc_id": "mcgm:" + hashlib.sha1(rel.encode()).hexdigest()[:16],
               "source_platform": "in_mcgm_portal", "source_url": url, "doc_type": dt, "language": "en",
               "title_native": title, "number": num, "adopted_date": date, "in_force": None, "consolidated": False,
               "content_format": "pdf_text", "text": txt, "retrieved_at": now, "source_policy": policy,
               "source_official": True, "source_org": "Brihanmumbai Municipal Corporation",
               "place_name": "Brihanmumbai Municipal Corporation", "qid": "Q1195653", "iso_3166_2": "IN-MH",
               "admin_level": "municipality", "platform": "in_mcgm_portal"}
        e = validate_record(rec)
        if e: print("INVALID", e); continue
        recs.append(rec); print("ok", title[:60], len(txt))
    if a.stage and recs:
        d = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/sasia_ru/IN"); os.makedirs(d, exist_ok=True)
        final = f"{d}/{place_key('wd:Q1195653')}.mcgm{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}p0001.jsonl"
        chk = f"{d}/_check_{os.path.basename(final)}"
        with open(chk, "w", encoding="utf-8") as f:
            for r in recs: f.write(json.dumps(r, ensure_ascii=False) + "\n")
        res = validate_file(chk)
        os.unlink(chk)
        if not res["ok"]: print("FILE INVALID", res["errors"][:3]); return
        with open(final + ".tmp", "w", encoding="utf-8") as f:
            for r in recs: f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush(); os.fsync(f.fileno())
        os.rename(final + ".tmp", final); print("staged", final)
main()
