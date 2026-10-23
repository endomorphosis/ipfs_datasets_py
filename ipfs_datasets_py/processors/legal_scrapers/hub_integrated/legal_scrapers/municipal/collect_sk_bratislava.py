#!/usr/bin/env python3
"""Bratislava (hlavné mesto, obec code 582000) VZN: URL list from bratislava.sk sitemaps (/vzn/<n>-<yyyy>), metadata from each page's
__NEXT_DATA__ (regNumber, title, effectiveFrom, category, cancellation, amendments, mainDocument), main PDF fetched and extracted.
Usage: collect_sk_bratislava.py OUT.jsonl"""
import json, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_common import Polite, doc_text, clean, sha, write_jsonl
P = Polite(1.0)
urls = set()
for i in (0, 1):
    sm, _ = P.get(f"https://bratislava.sk/sitemap-{i}.xml")
    urls |= set(re.findall(r"https://bratislava\.sk/vzn/[^<\s]+", sm.decode()))
urls = sorted(urls); print("discovered", len(urls), flush=True)
out, errs = [], {}
for k, u in enumerate(urls):
    try:
        h, hm = P.get(u)
        m = re.search(rb'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
        reg = json.loads(m.group(1))["props"]["pageProps"].get("regulation") if m else None
        if not reg: errs[u] = "no regulation json"; continue
        md = reg.get("mainDocument") or {}
        rec = dict(municipality="Bratislava", municipality_code="582000", native_id="vzn-" + reg["slug"], source_url=md.get("url") or u,
                   page_url=u, title=f"VZN {reg['regNumber']} {reg.get('fullTitle') or reg.get('titleText') or ''}".strip(),
                   retrieved_at=hm["retrieved_at"], text="", extras=dict(
                       reg_number=reg["regNumber"], effective_from=reg.get("effectiveFrom"), category=(reg.get("regulationCategory") or {}).get("title"),
                       is_full_text=reg.get("isFullTextRegulation"),
                       cancelled_by=[c.get("regNumber") for c in ([reg["cancellation"]] if isinstance(reg.get("cancellation"), dict) else (reg.get("cancellation") or []))],
                       cancelling=[c.get("regNumber") for c in reg.get("cancelling") or []],
                       amends=[c.get("regNumber") for c in reg.get("amending") or []], amended_by=[c.get("regNumber") for c in reg.get("amendments") or []],
                       attachments=[a.get("url") for a in reg.get("attachments") or []], status_source="bratislava.sk regulation record"))
        if md.get("url"):
            data, dm = P.get(md["url"], timeout=120)
            t, how = doc_text(data, dm); rec["text"] = clean(t); rec["extras"]["extraction"] = how
        out.append(rec)
    except Exception as e:
        errs[u] = str(e)[:200]
    if k % 25 == 0: print(k, len(out), len(errs), flush=True)
write_jsonl(sys.argv[1], out)
json.dump(dict(discovered=len(urls), records=len(out), errors=errs), open(sys.argv[1] + ".stats.json", "w"), ensure_ascii=False, indent=1)
print("done", len(out), len(errs))
