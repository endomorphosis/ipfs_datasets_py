#!/usr/bin/env python3
"""Cities on the shared 'zoznam-vzn' CMS (Trnava, Poprad, ...): register /zoznam-vzn filtered by status (valid = 'Platné znenie',
canceled = 'Zrušené, neplatné'; proposals 'Návrh' are skipped), paged; each row links the act page and its main file (download.dat).
Usage: collect_sk_zoznamvzn.py BASE_URL MUNICIPALITY CODE OUT.jsonl"""
import json, re, sys, os, html as H
from urllib.parse import urljoin
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_common import Polite, doc_text, clean, write_jsonl
base, muni, code, outp = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3], sys.argv[4]
P = Polite(1.0)
strip = lambda s: re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s))).strip()
rows, seen = [], set()
for status in ("valid", "canceled", "announced"):
    page = 1
    while True:
        u = f"{base}/zoznam-vzn?SearchModel.OrdinanceStatus={status}" + (f"&page={page}" if page > 1 else "")
        t = P.get(u)[0].decode("utf-8", "replace")
        trs = re.findall(r"(?s)<tr>\s*<td>(.*?)</tr>", t); new = 0
        if not trs:   # card layout (poprad.sk): <div class="contact-box"> title link, <span class="position">state</span>, download.dat
            trs = [re.sub(r'<span class="position">\s*(.*?)\s*</span>', r"<td>\1</td>", b, flags=re.S)
                   for b in re.findall(r'(?s)<div class="contact-box">(.*?)</div>\s*</div>', t)]
        for tr in trs:
            m = re.search(r'href="(/vzn/(\d+)/[^"]*)"[^>]*>(.*?)</a>', tr, re.S)
            if not m or m.group(2) in seen: continue
            seen.add(m.group(2)); new += 1
            sub = re.search(r"(?s)</a>\s*<br\s*/?>\s*<p>(.*?)</p>", tr)
            f = re.search(r'href="([^"]*download\.dat\?id=[^"]+)"', tr)
            st = strip(re.findall(r"(?s)<td>(.*?)</td>", tr + "</td>")[-1]) if "<td>" in tr else ""
            rows.append(dict(page=urljoin(base + "/", m.group(1)), pid=m.group(2), title=strip(m.group(3)) + (" " + strip(sub.group(1)) if sub else ""),
                             file=urljoin(base + "/zoznam-vzn", H.unescape(f.group(1))) if f else None, status=status, status_label=strip(tr)[-40:]))
        if not trs or not new or f"page={page + 1}" not in t: break
        page += 1
print("discovered", len(rows), flush=True)
out, errs = [], {}
for k, r in enumerate(rows):
    try:
        h, hm = P.get(r["page"]); t = h.decode("utf-8", "replace")
        body = strip(re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", " ", t))
        num = re.search(r"VZN č\.\s*(\d+[a-z]?(?:/\d{4})?)", r["title"]) or re.search(r"(?:VZN|nariadenie(?:\s+mesta\s+\w+)?)\s+(?:č\.\s*)?(\d+[a-z]?/\d{4})", r["title"])
        dates = {k2: re.search(rx, body) for k2, rx in (("promulgated", r"(?:Vyvesené|Zverejnené|Dátum vyvesenia)[^0-9]{0,20}(\d{1,2}\.\s?\d{1,2}\.\s?\d{4})"),
                                                         ("effective_from", r"(?:Účinnosť|Účinné od|Platné od|Nadobúda účinnosť)[^0-9]{0,20}(\d{1,2}\.\s?\d{1,2}\.\s?\d{4})"))}
        atts = sorted(set(urljoin(r["page"], H.unescape(x)) for x in re.findall(r'href="([^"]*download\.dat\?id=[^"]+)"', t)) - {r["file"]})
        rec = dict(municipality=muni, municipality_code=code, native_id=f"vzn-{num.group(1).replace('/', '-')}" if num else f"page-{r['pid']}",
                   source_url=r["file"] or r["page"], page_url=r["page"], title=r["title"], retrieved_at=hm["retrieved_at"], text="",
                   extras=dict(reg_number=num.group(1) if num else None, register_status=r["status"], cms_id=r["pid"],
                               **{k2: ("-".join(reversed(re.sub(r"\s", "", v.group(1)).split(".")))) if v else None for k2, v in dates.items()},
                               attachments=atts[:30], status_source=f"{base}/zoznam-vzn register status (Platné znenie / Zrušené, neplatné)"))
        if r["file"]:
            data, dm = P.get(r["file"], timeout=180)
            tt, how = doc_text(data, dm); rec["text"] = clean(tt); rec["extras"]["extraction"] = how
        out.append(rec)
    except Exception as e:
        errs[r["page"]] = str(e)[:200]
    if k % 25 == 0: print(k, len(out), len(errs), flush=True)
write_jsonl(outp, out)
json.dump(dict(discovered=len(rows), records=len(out), errors=errs), open(outp + ".stats.json", "w"), ensure_ascii=False, indent=1)
print("done", len(out), len(errs))
