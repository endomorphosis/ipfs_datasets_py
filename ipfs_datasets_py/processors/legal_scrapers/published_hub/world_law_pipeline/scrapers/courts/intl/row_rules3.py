"""Chunk-3 procedural rules (one row per article/rule, original language): EC (COGEP, funcionjudicial.gob.ec), MY (Rules of Court 2012, AGC portal), TR (HMK, CMK, IYUK, Danistay Kanunu; mevzuat.gov.tr).
usage: row_rules3.py CC.. -> data/<cc>/<cc>_rules.jsonl + crosswalk"""
import sys
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_rules2 import *
def txt(p): return open(p, errors="ignore").read().replace("\x0c", "\n")
def seq_split(t, rx, key):
    ms = list(rx.finditer(t)); out = []; seen = set()
    for i, m in enumerate(ms):
        e = ms[i + 1].start() if i + 1 < len(ms) else len(t); k = key(m)
        if k in seen: continue
        body = ws(t[m.end():e])
        if len(body) < 10: continue
        seen.add(k); out.append((k, body))
    return out
def xwalk(cc, sid, name, courts, url, basis): return [dict(rule_set_id=sid, rule_set=name, court_id=c, jurisdiction=cc, basis=basis, source_url=url, linked_rows="new") for c in courts]
def ec():
    p = f"{RAW}/ec/cogep.txt"; t = txt(p); i0 = t.find("Art. 1.-"); t = t[i0:]; sh = sha(p)
    lst = seq_split(t, re.compile(r"(?m)^[ \t]*Art\.[ \t]*(\d{1,3})\.-[ \t]*"), lambda m: m.group(1))
    url = "https://www.funcionjudicial.gob.ec/resources/pdf/codigoorganicogeneralderocesosCOGEP.pdf"; name = "Código Orgánico General de Procesos (COGEP)"
    rows = [row("ec-cogep", "EC", name, f"Art. {k}", b, url, sh, "robots_unknown:fetched_ok (funcionjudicial.gob.ec; Función Judicial)", "Ecuadorian legislation published by the Función Judicial (Ley de Propiedad Intelectual art. 8 excludes laws); compilation by Ediciones Legales", "es", "2015-05-22") for k, b in lst]
    print("ec-cogep", len(rows)); return rows, xwalk("EC", "ec-cogep", name, ["ec-corte-nacional-de-justicia", "ec-corte-provincial", "ec-unidad-judicial"], url, "national procedural code applying to this court")
def my():
    p = f"{RAW}/my/roc2012.txt"; t = txt(p); sh = sha(p)
    rx = re.compile(r"\(O\.[ \t]*(\d{1,3}[A-Z]?),[ \t]*r\.[ \t]*(\d{1,3}[A-Z]?)\)")
    ms = list(rx.finditer(t)); rows = []; seen = set()
    url = "https://lom.agc.gov.my/ilims/upload/portal/akta/outputp/pua_20120702_RULES%20OF%20COURT%202012%20(FINAL)%20-%201%20July%202012.pdf"; name = "Rules of Court 2012 (P.U.(A) 205/2012)"
    for i, m in enumerate(ms):
        e = ms[i + 1].start() if i + 1 < len(ms) else len(t); k = f"O. {m.group(1)} r. {m.group(2)}"
        if k in seen: continue
        body = ws(t[m.end():e])
        if len(body) < 10: continue
        # heading of the NEXT marker precedes it on the same line: trim trailing heading text
        body = re.sub(r"\s+[A-Z][^.()]{3,90}$", "", body) if len(body) > 120 else body
        seen.add(k); rows.append(row("my-roc-2012", "MY", name, k, body, url, sh, "robots_unknown:fetched_ok (lom.agc.gov.my; Attorney General's Chambers)", "Malaysian federal legislation (Copyright Act 1987 s.3: texts of laws are not copyright works); AGC portal", "en", "2012-08-01"))
    print("my-roc-2012", len(rows)); return rows, xwalk("MY", "my-roc-2012", name, ["my-federal-court", "my-court-of-appeal", "my-high-court", "my-sessions-court", "my-magistrates-court"], url, "rules of court applying to this court")
TRRX = re.compile(r"(?m)^[ \t]*((?:Ek|Geçici|GEÇİCİ|EK)[ \t]+)?(?:MADDE|Madde)[ \t]+(\d{1,3})[ \t]*[–\-—]")
def tr():
    SETS = [("tr-hmk", "Hukuk Muhakemeleri Kanunu (6100)", "hmk", "1.5.6100", "2011-10-01", ["tr-yargitay", "tr-bolge-adliye-mahkemesi", "tr-asliye-hukuk-mahkemesi"]),
            ("tr-cmk", "Ceza Muhakemesi Kanunu (5271)", "cmk", "1.5.5271", "2005-06-01", ["tr-yargitay", "tr-bolge-adliye-mahkemesi", "tr-asliye-ceza-mahkemesi"]),
            ("tr-iyuk", "İdari Yargılama Usulü Kanunu (2577)", "idari", "1.5.2577", "1982-01-20", ["tr-danistay", "tr-bolge-idare-mahkemesi", "tr-idare-mahkemesi"]),
            ("tr-danistay", "Danıştay Kanunu (2575)", "danistay", "1.5.2575", "1982-01-20", ["tr-danistay"])]
    rows = []; xw = []
    for sid, name, fn, mv, eff, courts in SETS:
        p = f"{RAW}/tr/{fn}.txt"; t = txt(p); sh = sha(f"{RAW}/tr/{fn}.pdf"); url = f"https://www.mevzuat.gov.tr/MevzuatMetin/{mv}.pdf"
        i0 = list(re.finditer(r"(?m)^[ \t]*(?:MADDE|Madde)[ \t]+1[ \t]*[–\-—]", t)); t = t[i0[0].start():] if i0 else t
        for m_, b in seq_split(t, TRRX, lambda m: (m.group(1) or "").strip().lower() + " " + m.group(2)):
            rows.append(row(sid, "TR", name, f"{m_.strip().replace('ek ', 'Ek ').replace('geçici ', 'Geçici ')} Madde".replace("  ", " ") if False else (f"Madde {m_}" if not m_.startswith(" ") else f"Madde {m_.strip()}") if m_.split()[0].isdigit() else f"{m_.split()[0].capitalize()} Madde {m_.split()[1]}", b, url, sh, "robots_unknown:fetched_ok (mevzuat.gov.tr; Presidency Legislation Information System)", "Turkish legislation published by the Presidency (Law 5846 art. 31: laws are not protected works)", "tr", eff))
        print(sid, sum(1 for r in rows if r["rule_set_id"] == sid)); xw += xwalk("TR", sid, name, courts, url, "procedural statute applying to this court")
    return rows, xw
B = dict(EC=ec, MY=my, TR=tr)
if __name__ == "__main__":
    for cc in sys.argv[1:]:
        rows, xw = B[cc.upper()](); rows = dedupe(rows); d = f"{ROOT}/data/{cc.lower()}"; os.makedirs(d, exist_ok=True)
        wjl(f"{d}/{cc.lower()}_rules.jsonl", rows); wjl(f"{d}/{cc.lower()}_rules_crosswalk.jsonl", xw); print(cc, "rules", len(rows), flush=True)
