#!/usr/bin/env python3
"""Trenčín (obec code 505820): register trencin.sk/samosprava/transparentny-trencin/vseobecne-zavazne-nariadenia/ (current acts;
states Navrhované / Platné / Účinné; proposals skipped), detail page ?id=N (Číslo, Názov, Stav, PDF dokumenty).
Usage: collect_sk_trencin.py OUT.jsonl"""
import json, re, sys, os, html as H
from urllib.parse import urljoin
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_common import Polite, doc_text, clean, write_jsonl
P = Polite(1.0); B = "https://trencin.sk/samosprava/transparentny-trencin/vseobecne-zavazne-nariadenia/"
strip = lambda s: re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()
t = P.get(B)[0].decode("utf-8", "replace")
rows = []
for m in re.finditer(r'(?s)<div class="row table-row">(.*?)</div>\s*</div>', t):
    c = m.group(1); a = re.findall(r'href="(\./detail-nariadenia/\?id=(\d+))"[^>]*>(.*?)</a>', c, re.S)
    st = re.search(r'col-md-2 right">(.*?)$', c, re.S)
    if a: rows.append(dict(url=urljoin(B, a[0][0]), id=a[0][1], num=strip(a[0][2]), name=strip(a[1][2]) if len(a) > 1 else "", state=strip(st.group(1)) if st else ""))
print("discovered", len(rows), flush=True)
out, errs, skipped = [], {}, 0
for k, r in enumerate(rows):
    if re.match(r"(?i)navrh", r["state"]): skipped += 1; continue
    try:
        h, hm = P.get(r["url"]); d = h.decode("utf-8", "replace")
        pdfs = re.findall(r'href="(https://trencin\.sk/wp-content/uploads/[^"]+\.(?:pdf|docx?))"[^>]*>([^<]*)', d, re.I)
        if not pdfs: errs[r["url"]] = "no pdf"; continue
        pick = next((p for p in pdfs if re.search(r"(?i)ucinn|uplne|úplné", p[0] + p[1])), pdfs[0])
        num = re.search(r"(\d+\s*/\s*\d{4})", r["num"])
        rec = dict(municipality="Trenčín", municipality_code="505820", native_id="vzn-" + re.sub(r"\D+", "-", num.group(1)) if num else f"id-{r['id']}",
                   source_url=pick[0], page_url=r["url"], title=f"{r['num'].replace('č.', 'č. ')} {r['name']}".strip(), retrieved_at=hm["retrieved_at"], text="",
                   extras=dict(reg_number=re.sub(r"\s", "", num.group(1)) if num else None, register_status=r["state"], files=[p[0] for p in pdfs],
                               status_source="trencin.sk VZN register (Platné / Účinné)"))
        data, dm = P.get(pick[0], timeout=180); tt, how = doc_text(data, dm); rec["text"] = clean(tt); rec["extras"]["extraction"] = how
        out.append(rec)
    except Exception as e: errs[r["url"]] = str(e)[:200]
write_jsonl(sys.argv[1], out)
json.dump(dict(discovered=len(rows), records=len(out), skipped_proposals=skipped, errors=errs), open(sys.argv[1] + ".stats.json", "w"), ensure_ascii=False, indent=1)
print("done", len(out), len(errs), skipped)
