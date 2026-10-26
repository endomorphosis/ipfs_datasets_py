#!/usr/bin/env python3
"""Košice (obec code 599981) VZN: register www.kosice.sk/vzn (all terms; repealed acts marked 'ZRUŠENÉ'), detail page /vzn/<n>
(Vyhlásené (platné), Účinné, documents). Main text = the latest 'Úplné znenie' (consolidated) PDF when present, else the
original 'Text VZN'. Earlier consolidations and amendment PDFs are listed (url + label) in extras.
Usage: collect_sk_kosice.py OUT.jsonl"""
import json, re, sys, os, html as H
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_common import Polite, doc_text, clean, write_jsonl
P = Polite(1.0)
strip = lambda s: re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s))).strip()
reg, _ = P.get("https://www.kosice.sk/vzn"); reg = reg.decode("utf-8", "replace")
rows = []
for tr in re.findall(r"(?s)<tr>(.*?)</tr>", reg):
    m = re.search(r'href="(https://www\.kosice\.sk/vzn/(\d+))"[^>]*>(.*?)</a>(.*?)$', tr, re.S)
    if not m: continue
    d = re.search(r"(\d{2}\.\d{2}\.\d{4})", tr)
    rows.append(dict(url=m.group(1), num=m.group(2), title=strip(m.group(3)), tail=strip(m.group(4)), listed=d.group(1) if d else None,
                     repealed="ZRUŠEN" in strip(tr).upper()))
print("discovered", len(rows), flush=True)
out, errs = [], {}
dmy = lambda s: "-".join(reversed(re.sub(r"\s", "", s).split("."))) if s else None
for k, r in enumerate(rows):
    try:
        h, hm = P.get(r["url"]); t = h.decode("utf-8", "replace")
        txt = strip(re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", " ", t))
        vy = re.search(r"Vyhlásené \(platné\):\s*(\d{1,2}\.\s?\d{1,2}\.\s?\d{4})", txt); uc = re.search(r"Účinné:\s*(\d{1,2}\.\s?\d{1,2}\.\s?\d{4})", txt)
        # the 'canceled_by' box (up to the next 'info' block) links the REPLACING act's documents: never take files from it
        cb = [(m.start(), (t.find('class="info', m.start()) if t.find('class="info', m.start()) > 0 else m.start() + 1500))
              for m in re.finditer(r'class="canceled_by', t)]
        cb_nums = sorted(set(re.findall(r"/vzn/(\d+)\b", "".join(t[a:b] for a, b in cb)) + re.findall(r'class="number">\s*(\d+)', "".join(t[a:b] for a, b in cb))))
        incb = lambda pos: any(a <= pos < b for a, b in cb)
        docs = []
        for m in re.finditer(r'(?s)<a [^>]*href="(https://static\.kosice\.sk/vzn/(doc|changes)/[^"]+)"[^>]*>(.*?)</a>', t):
            if incb(m.start()): continue
            lab = strip(m.group(3))
            if lab == "PDF" or any(x["url"] == m.group(1) for x in docs): continue
            after = strip(re.sub(r"(?s)<style.*?</style>", " ", t[m.end(): m.end() + 400])).split(" PDF ")[0][:200]
            docs.append(dict(url=m.group(1), kind=m.group(2), label=(lab + " " + after).strip()))
        main = [x for x in docs if x["kind"] == "doc"]
        cons = [x for x in main if re.search(r"(?i)úplné znenie", x["label"])]
        pick = cons[-1] if cons else (main[0] if main else None)
        rec = dict(municipality="Košice", municipality_code="599981", native_id=f"vzn-{r['num']}", source_url=pick["url"] if pick else r["url"],
                   page_url=r["url"], title=f"VZN č. {r['num']} {re.sub(r'(?i)\s*ZRUŠENÉ\s*$', '', r['title'])}".strip(), retrieved_at=hm["retrieved_at"], text="",
                   extras=dict(reg_number=r["num"], promulgated=dmy(vy.group(1)) if vy else None, effective_from=dmy(uc.group(1)) if uc else None,
                               register_date=dmy(r["listed"]), register_repealed=r["repealed"], cancelled_by=[n for n in cb_nums if n != r["num"]], text_version=pick["label"] if pick else None,
                               is_consolidated=bool(cons), versions=[dict(url=x["url"], label=x["label"]) for x in main if x is not pick],
                               amendments=[dict(url=x["url"], label=x["label"]) for x in docs if x["kind"] == "changes"],
                               status_source="kosice.sk VZN register (repealed acts marked ZRUŠENÉ)"))
        if pick:
            data, dm = P.get(pick["url"], timeout=180)
            tt, how = doc_text(data, dm); rec["text"] = clean(tt); rec["extras"]["extraction"] = how
        out.append(rec)
    except Exception as e:
        errs[r["url"]] = str(e)[:200]
    if k % 25 == 0: print(k, len(out), len(errs), flush=True)
write_jsonl(sys.argv[1], out)
json.dump(dict(discovered=len(rows), records=len(out), errors=errs), open(sys.argv[1] + ".stats.json", "w"), ensure_ascii=False, indent=1)
print("done", len(out), len(errs))
