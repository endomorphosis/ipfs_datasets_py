"""ZA municipal supplement: Open By-laws (openbylaws.org.za) gap fetch.

Only expressions listed in the site's robots-referenced sitemap (/sitemaps/legislation.xml) that are NOT already in
endomorphosis/ipfs_south_africa_municipal_laws (diff file from the Hub check: works not on the Hub + other-language /
other-date expressions of works on the Hub). Robots: Crawl-delay 5 honoured (6 s used), /api/, /search/,
/akn/*/provision/* never requested. Content-Signal ai-train=no / ai-input=no is recorded in every row's licence field;
this corpus is for translation, not model training. When an expression page carries no AKN body, the expression's
own /source.pdf (robots-allowed) is fetched once and its text kept if it has a text layer.
Writes <STATE>/openbylaws/expressions.jsonl (html kept in the HTML cache; pdf text inline). Resumable.
"""
import os, sys, json, re, hashlib, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import za_common as zc
from bs4 import BeautifulSoup
import warnings; warnings.filterwarnings("ignore")

STATE = os.environ.get("ZA_STATE", "za_build_state")
OUT = os.path.join(STATE, "openbylaws"); os.makedirs(OUT, exist_ok=True)
diff = json.load(open(os.path.join(STATE, "listings", "openbylaws_sitemap_diff.json")))
miss = set(diff["miss_works"])
targets = [l for l in diff["locs"] if l.split("openbylaws.org.za")[1].rsplit("/", 1)[0] in miss] + diff["newer"]
fn = os.path.join(OUT, "expressions.jsonl")
done = {json.loads(l)["url"] for l in open(fn)} if os.path.exists(fn) else set()
P = zc.Polite(min_delay=6)
for u in targets:
    if u in done: continue
    r = P.get(u)
    rec = dict(url=u, status=None if r is None else r["status"], final_url=None if r is None else r["url"], retrieved_at=zc.now_utc())
    if r and r["status"] == 200 and "openbylaws.org.za" in r["url"]:
        s = BeautifulSoup(r["body"], "html.parser")
        la = s.find("la-akoma-ntoso")
        rec["has_akn"] = bool(la and la.find(class_="akn-akomaNtoso"))
        rec["html_sha1_key"] = hashlib.sha1(u.encode()).hexdigest()
        if not rec["has_akn"]:
            src = u + "/source.pdf"
            d = P.get(src, doc=True, max_bytes=40_000_000)
            if d and d["status"] == 200 and d["body"][:5] == b"%PDF-":
                t = subprocess.run(["pdftotext", "-enc", "UTF-8", "-", "-"], input=d["body"], capture_output=True, timeout=300).stdout.decode("utf-8", "replace")
                rec.update(source_pdf=src, source_pdf_sha256=hashlib.sha256(d["body"]).hexdigest(), source_pdf_bytes=len(d["body"]),
                           source_pdf_pages=t.count("\f"), source_pdf_text=t)
            else:
                rec.update(source_pdf=src, source_pdf_status=None if d is None else d["status"])
    with open(fn, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(zc.now_utc(), rec["status"], rec.get("has_akn"), u, flush=True)
print("DONE", flush=True)
