"""AU forms: Federal Circuit and Family Court of Australia (family law forms; live site TLS-blocked from box -> Wayback) and Supreme Court of Victoria. forms/au/<sha>.pdf ; rows -> data/au/au_forms.jsonl"""
import sys, os, json, hashlib, re, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
OUT = f"{ROOT}/data/au/au_forms.jsonl"; DIR = f"{ROOT}/forms/au"; os.makedirs(DIR, exist_ok=True)
done = {r["form_id"] for r in rjl(OUT)}; n = 0
def save(fid, court, jur, title, cat, url, fetch_url, index_url, policy, lic):
    global n
    if fid in done: return
    b = None
    for fu in dict.fromkeys([fetch_url, "https://web.archive.org/web/2026id_/" + url] if "archive.org" in fetch_url else [fetch_url]):
        try: b = get(fu, delay=2.0, binary=True, timeout=120); break
        except Exception as e: err = e
    if b is None: print("ERR", url, str(err)[:60], flush=True); return
    if b[:4] != b"%PDF": print("notpdf", url, flush=True); return
    h = hashlib.sha256(b).hexdigest(); open(f"{DIR}/{h}.pdf", "wb").write(b)
    row = dict(form_id=fid, court_id=court, jurisdiction=jur, form_number=None, title=title, category=cat, language="en", revision_date=None, file_format="pdf", pdf_path=f"forms/au/{h}.pdf", pdf_sha256=h, file_bytes=len(b),
               source_url=url, index_url=index_url, site_policy=policy, license=lic, retrieved_at=NOW())
    open(OUT, "a").write(json.dumps(row) + "\n"); done.add(fid); n += 1
    if n % 20 == 0: print("downloaded", n, flush=True)
# Supreme Court of Victoria
u = "https://www.supremecourt.vic.gov.au/forms-fees-and-services/forms-templates-and-guidelines"
h = get(u, delay=1.0)
for m in re.finditer(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', h, re.S | re.I):
    url = urllib.parse.urljoin(u, m.group(1)); t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(2))).strip() or os.path.basename(url)
    save("au-vic-sc-" + hashlib.sha1(url.encode()).hexdigest()[:12], "au-vic-supreme-court", "AU-VIC", t, "supreme_court_vic", url, url, u, "robots_allowed", "CC-BY-4.0 (Victorian Gov; verify)")
# FCFCOA via Wayback
IDX = "https://web.archive.org/web/20260927040344/https://www.fcfcoa.gov.au/fl/forms"
idx = get(IDX, delay=1.0, timeout=120)
slugs = sorted(set(re.findall(r'href="/web/\d+/https://www\.fcfcoa\.gov\.au/fl/forms/([^"]+)"', idx)))
print(len(slugs), "fcfcoa form pages", flush=True)
for s in slugs:
    pu = f"https://www.fcfcoa.gov.au/fl/forms/{s}"
    if f"au-fcfcoa-{s}" in done: continue
    try: p = get("https://web.archive.org/web/2026/" + pu, delay=2.0, timeout=120)
    except Exception as e: print("pageERR", s, str(e)[:60], flush=True); continue
    pdfs = [x for x in re.findall(r'href="(https://web\.archive\.org/web/\d+/(https://www\.fcfcoa\.gov\.au/sites/default/files/[^"]+\.pdf))"', p)]
    tm = re.search(r"<title>(.*?)</title>", p, re.S); title = re.sub(r"\s*\|.*$", "", re.sub(r"\s+", " ", tm.group(1))).strip() if tm else s
    for wb, orig in pdfs[:1]:
        raw = re.sub(r"/web/(\d+)/", r"/web/\1id_/", wb, count=1)
        save(f"au-fcfcoa-{s}", "au-fcfcoa", "AU", title, "family_law", orig, raw, pu, "archive_wayback(live_tls_blocked_from_box)", "CC-BY-4.0 (FCFCOA; verify)")
print("done", n)
