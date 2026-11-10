"""Ontario Court Forms (ontariocourtforms.on.ca, Ministry of the Attorney General): PDFs -> forms/ca/<sha>.pdf ; rows -> data/ca/ca_forms_on.jsonl (resumable)."""
import sys, os, json, hashlib, re
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import cached, RAW
OUT = f"{ROOT}/data/ca/ca_forms_on.jsonl"; DIR = f"{ROOT}/forms/ca"; os.makedirs(DIR, exist_ok=True)
BASE = "https://ontariocourtforms.on.ca"
home = open(f"{RAW}/intl_on_forms_home.html", "rb").read().decode()
cats = sorted({p.rstrip("/") for p in re.findall(r'href="(/en/[^"#]+)"', home) if re.search(r"forms|rules|documents|waiver|exhibits", p) and "accessibility" not in p and "wi-fi" not in p})
COURT = {"rules-of-civil-procedure-forms": "ca-on-superior-court", "family-law-rules-forms": "ca-on-superior-court", "rules-of-the-small-claims-court-forms": "ca-on-superior-court",
         "forms-under-the-criminal-rules-of-the-ontario-court-of-justice": "ca-on-provincial-court", "forms-under-the-criminal-proceedings-rules-of-the-superior-court-of-justice": "ca-on-superior-court",
         "criminal-appeal-rules-forms": "ca-on-court-of-appeal", "provincial-offences-act-forms": "ca-on-provincial-court", "rules-of-the-ontario-court-provincial-division-in-provincial-offences-proceedings-forms": "ca-on-provincial-court"}
done = {r["form_id"] for r in rjl(OUT)}; n = 0
print(len(cats), "category pages", flush=True)
for c in cats:
    slg = c.split("/")[-1]
    try: b, _, pol = cached(BASE + c + "/", f"intl_on_forms_{slg}.html")
    except Exception as e: print("ERR", c, e); continue
    if not b: continue
    h = b.decode("utf-8", "replace")
    for m in re.finditer(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>', h):
        href = m.group(1); url = href if href.startswith("http") else BASE + href
        ctx = re.sub(r"<[^>]+>", "\n", h[max(0, m.start() - 700):m.start()]); lines = [x.strip() for x in ctx.split("\n") if x.strip()]
        title = lines[-1] if lines else os.path.basename(href)
        fn = re.search(r"\b(?:Form|Formule)\s+([0-9A-Z][\w.\-]*)", title); fid = f"ca-on-form-{hashlib.sha1(url.encode()).hexdigest()[:12]}"
        if fid in done: continue
        base = dict(form_id=fid, court_id=COURT.get(slg), jurisdiction="CA-ON", form_number=fn.group(1) if fn else None, title=title[:300], category=slg, language="fr" if re.search(r"-fr\b|-f\.pdf|_f\.pdf|-fra|fr-fil|-fil-fr", href) else "en",
                    revision_date=None, file_format="pdf", source_url=url, index_url=BASE + c + "/", license="Queen's/King's Printer for Ontario (court forms; verify terms)")
        try: data = get(url, delay=2.0, binary=True, timeout=90)
        except Exception as e:
            print("ERR", url, str(e)[:60], flush=True); continue
        if data[:4] != b"%PDF": print("notpdf", url); continue
        h2 = hashlib.sha256(data).hexdigest(); open(f"{DIR}/{h2}.pdf", "wb").write(data)
        base.update(pdf_path=f"forms/ca/{h2}.pdf", pdf_sha256=h2, file_bytes=len(data), site_policy=pol, retrieved_at=NOW())
        open(OUT, "a").write(json.dumps(base) + "\n"); done.add(fid); n += 1
        if n % 25 == 0: print("downloaded", n, flush=True)
print("done", n)
