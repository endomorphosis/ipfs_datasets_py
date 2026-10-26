#!/usr/bin/env python3
"""Bratislava-Petržalka (obec code 529460): archive www.petrzalka.sk/vseobecne-zavazne-nariadenia/page/N/; each <figure class="vzn">
block gives number, 'Účinnosť od', 'Schválené', a ZRUŠENÉ note (with the replacing VZN) and the PDF ('Znenie VZN ...').
Usage: collect_sk_petrzalka.py OUT.jsonl"""
import json, re, sys, os, html as H
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_common import Polite, doc_text, clean, write_jsonl
P = Polite(1.0); B = "https://www.petrzalka.sk/vseobecne-zavazne-nariadenia/"
strip = lambda s: re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()
dmy = lambda s: "-".join(reversed(s.split("."))) if s and re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", s) else None
blocks, page = [], 1
while True:
    t = P.get(B + (f"page/{page}/" if page > 1 else ""))[0].decode("utf-8", "replace")
    fb = re.findall(r'(?s)<figure class="vzn">(.*?)</figure>', t)
    blocks += fb
    if not fb or f"/page/{page + 1}/" not in t: break
    page += 1
print("discovered", len(blocks), "pages", page, flush=True)
out, errs, seen = [], {}, set()
for k, b in enumerate(blocks):
    try:
        num = strip((re.search(r"<li><strong>([^<]*)</strong></li>", b) or [None, ""])[1])
        eff = re.search(r"Účinnosť od:</strong>\s*([\d.]+)", b); appr = re.search(r"Schválené:</strong>\s*([\d.]+)", b)
        h3 = strip((re.search(r"(?s)<h3>(.*?)</h3>", b) or [None, ""])[1])
        rep = re.search(r"(?i)Z\s?R\s?U\s?Š\s?E\s?N\s?É", h3)
        pdfs = re.findall(r'<a class="pdf" href="([^"]+)">([^<]*)</a>', b)
        if not pdfs: errs[num or str(k)] = "no pdf"; continue
        pick = next((p for p in pdfs if re.search(r"(?i)znenie vzn|vzn", p[1])), pdfs[0])
        desc = re.sub(r"(?i)^Toto VZN je\s+Z\s?R\s?U\s?Š\s?E\s?N\s?É[^.]*\.(\s*\d+/\d{4}\.)?", "", h3).strip()
        title = desc if re.search(r"(?i)nariaden|vzn", desc) and len(desc) > 25 else strip(pick[1])
        title = re.sub(r"\s*\(\d+[,.]?\d*\s*[KM]B\)\s*$", "", title)
        nid = "vzn-" + re.sub(r"\D+", "-", num).strip("-") if re.search(r"\d+/\d{4}", num) else f"block-{k}"
        if nid in seen: nid += f"-{k}"
        seen.add(nid)
        rec = dict(municipality="Bratislava-Petržalka", municipality_code="529460", native_id=nid, source_url=pick[0], page_url=B, title=title,
                   retrieved_at=None, text="", extras=dict(reg_number=num or None, effective_from=dmy(eff.group(1)) if eff else None, approved=dmy(appr.group(1)) if appr else None,
                                                         register_repealed=bool(rep), register_note=h3[:400] if rep else None, files=[p[0] for p in pdfs],
                                                         status_source="petrzalka.sk VZN archive (repealed acts marked ZRUŠENÉ)"))
        data, dm = P.get(pick[0], timeout=180); tt, how = doc_text(data, dm)
        rec["text"] = clean(tt); rec["extras"]["extraction"] = how; rec["retrieved_at"] = dm["retrieved_at"]
        out.append(rec)
    except Exception as e: errs[str(k)] = str(e)[:200]
    if k % 25 == 0: print(k, len(out), len(errs), flush=True)
write_jsonl(sys.argv[1], out)
json.dump(dict(discovered=len(blocks), records=len(out), errors=errs), open(sys.argv[1] + ".stats.json", "w"), ensure_ascii=False, indent=1)
print("done", len(out), len(errs))
