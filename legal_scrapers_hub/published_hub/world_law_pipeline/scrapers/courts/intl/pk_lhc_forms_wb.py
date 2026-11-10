"""PK: Lahore High Court 'Judicial Forms' page (lhc.gov.pk/judicial_forms) files via Wayback Machine id_ captures (2012-2013),
because lhc.gov.pk / data.lhc.gov.pk are unreachable from the box. Captures listed by the Wayback CDX (state/run_20261101_18/cc_probe.jsonl).
Forms are scanned images (GIF) or PDFs; old captures -> needs_review. Usage: pk_lhc_forms_wb.py [--dry]"""
import json, hashlib, os, sys, time, datetime, subprocess, tempfile, requests
UA = "WorldCourtsResearchBot/1.0 (+https://huggingface.co/datasets/endomorphosis/world_courts; polite research crawl)"
ROOT = "/workspace/world_courts"; OUT = f"{ROOT}/data/pk/pk_forms.jsonl"; FD = f"{ROOT}/forms/pk"; COURT = "osm:node/2953146416"
B = "http://lhc.gov.pk/judicial_forms/"
F = [("20130918193225", "copy_form_private.pdf", "Application for Certified Copy (private party)", "en", "copies"),
     ("20130626061149", "copy_form_sc.pdf", "Application for Certified Copy (for Supreme Court proceedings)", "en", "copies"),
     ("20121004143551", "copy_form_urdu.gif", "Application for Certified Copy (Urdu)", "ur", "copies"),
     ("20121004143442", "decree_form_urdu_1.gif", "Decree Form 1 (Urdu)", "ur", "civil"),
     ("20121004143414", "decree_form_urdu_2.gif", "Decree Form 2 (Urdu)", "ur", "civil"),
     ("20121004143543", "gardianship_urdu_1.gif", "Guardianship Certificate, page 1 (Urdu)", "ur", "family"),
     ("20121004143248", "gardianship_urdu_2.gif", "Guardianship Certificate, page 2 (Urdu)", "ur", "family"),
     ("20121004143648", "janishi_certificate_urdu.gif", "Succession (Janishini) Certificate (Urdu)", "ur", "probate"),
     ("20121004143503", "power_of_attorney.gif", "Power of Attorney (Wakalatnama) (English)", "en", "general"),
     ("20121004143527", "power_of_attorney_civil_urdu.gif", "Power of Attorney (Wakalatnama), Civil (Urdu)", "ur", "civil"),
     ("20121004143423", "power_of_attorney_criminal_urdu.gif", "Power of Attorney (Wakalatnama), Criminal (Urdu)", "ur", "criminal"),
     ("20121004143601", "receipt_pro_note.gif", "Receipt / Pro-Note (Urdu)", "ur", "general"),
     ("20121004143332", "urgent_proforma.gif", "Urgent Proforma (application for urgent hearing)", "en", "general")]
SIG = {b"%PDF": "pdf", b"GIF8": "gif"}
def fetch(u):
    try:
        r = requests.get(u, headers={"User-Agent": UA}, timeout=120); code, c = r.status_code, r.content
    except requests.exceptions.SSLError:
        with tempfile.NamedTemporaryFile() as f:
            p = subprocess.run(["curl", "-s", "-m", "120", "-A", UA, "-o", f.name, "-w", "%{http_code}", u], capture_output=True, text=True)
            code, c = int(p.stdout or 0), open(f.name, "rb").read()
    time.sleep(4); return code, c
def main():
    dry = "--dry" in sys.argv; now = datetime.datetime.now(datetime.timezone.utc).isoformat(); os.makedirs(FD, exist_ok=True)
    old = [json.loads(l) for l in open(OUT) if l.strip()] if os.path.exists(OUT) else []
    shas = {r.get("pdf_sha256") for r in old}; srcs = {r.get("source_url") for r in old}; n = 0; fail = []
    for ts, fn, title, lang, cat in F:
        src = B + fn
        if src in srcs: continue
        code, c = fetch(f"https://web.archive.org/web/{ts}id_/{src}")
        ext = next((e for k, e in SIG.items() if c.startswith(k)), None)
        if code != 200 or not ext: fail.append(fn); continue
        sha = hashlib.sha256(c).hexdigest()
        if sha in shas: continue
        row = {"form_id": f"pk-{sha[:16]}", "court_id": COURT, "jurisdiction": "PK-PB", "form_number": None, "title": title, "category": cat,
               "language": lang, "file_format": ext, "pdf_path": f"forms/pk/{sha}.{ext}", "pdf_sha256": sha, "file_bytes": len(c), "source_url": src,
               "index_url": "http://lhc.gov.pk/judicial_forms", "source_kind": "official", "needs_review": True,
               "license": "Lahore High Court published judicial forms; Pakistan government work, no licence stated",
               "site_policy": f"archived_copy(wayback:{ts[:8]});origin_unreachable", "retrieved_at": now,
               "version_note": f"Wayback capture {ts[:8]}; current LHC version may differ"}
        if not dry:
            open(f"{FD}/{sha}.{ext}", "wb").write(c)
            with open(OUT, "a") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
        shas.add(sha); srcs.add(src); n += 1
    print("added", n, "fail", fail)
main()
