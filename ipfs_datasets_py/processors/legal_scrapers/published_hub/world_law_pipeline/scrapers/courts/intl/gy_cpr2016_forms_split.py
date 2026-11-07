"""GY: per-form rows for Schedule 3 (Forms) of the Civil Procedure Rules 2016, split logically from the already-stored official combined PDF
(forms/gy/c4548d00...pdf, from supremecourt.gy). No new download: each row points at the same local PDF with its page range."""
import json, os, re, subprocess, datetime
ROOT = "/workspace/world_courts"; OUT = f"{ROOT}/data/gy/gy_forms.jsonl"
SHA = "c4548d0038d49c900752d0c747e85eab1a4a8ace6798aa2bc3559d9407d5134b"; PDF = f"{ROOT}/forms/gy/{SHA}.pdf"
SRC = "https://supremecourt.gy/sites/default/files/Civil%20Procedure%20Forms%202016.pdf"; IDX = "https://supremecourt.gy/rules-of-court"
now = datetime.datetime.now(datetime.UTC).isoformat()
pages = subprocess.run(["pdftotext", "-layout", PDF, "-"], capture_output=True, text=True).stdout.split("\f")
toc = []
for pg in pages[:4]:
    for m in re.finditer(r"^Form (\d+[A-Z]?):\s+(.+?)\s*\.{3,}\s*(\d+)\s*$", pg, re.M): toc.append((m.group(1), m.group(2).strip(" ."), int(m.group(3))))
# locate the PDF page index where each form's heading appears
idx = {}
for pi, pg in enumerate(pages):
    for m in re.finditer(r"^[ \t]*Form (\d+[A-Z]?):[ \t]+\S", pg, re.M):
        if "...." in pg[m.start():m.start() + 200].split("\n")[0]: continue
        idx.setdefault(m.group(1), pi + 1)
rows = []
for j, (fn, title, _) in enumerate(toc):
    ps = idx.get(fn); pe = None
    if ps:
        nxt = [idx[t[0]] for t in toc[j + 1:] if t[0] in idx]
        pe = (nxt[0] - 1 if nxt and nxt[0] > ps else ps) if nxt else len([p for p in pages if p.strip()])
    rows.append({"form_id": f"gy-cpr2016-form-{fn.lower()}", "court_id": None, "jurisdiction": "GY", "form_number": f"Form {fn}", "title": title,
        "category": "civil-procedure-rules-2016-schedule-3", "language": "en", "file_format": "pdf", "pdf_path": f"forms/gy/{SHA}.pdf", "pdf_sha256": SHA,
        "page_start": ps, "page_end": pe, "file_bytes": None, "source_url": SRC, "index_url": IDX, "rules_ref": "Civil Procedure Rules 2016, Schedule 3",
        "license": "Supreme Court of Judicature of Guyana published forms; official court forms, no licence stated",
        "site_policy": "robots_allowed (crawl-delay 10 respected)", "retrieved_at": now, "record_note": "logical split of the combined Schedule 3 PDF (same file, page range)"})
old = {json.loads(l)["form_id"] for l in open(OUT)}
new = [r for r in rows if r["form_id"] not in old]
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("toc", len(toc), "located", sum(1 for r in rows if r["page_start"]), "added", len(new))
