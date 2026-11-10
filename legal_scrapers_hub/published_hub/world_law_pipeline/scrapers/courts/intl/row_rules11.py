"""Gap pass rules: IT codice di procedura civile (R.D. 1443/1940) and codice di procedura penale (D.P.R. 447/1988) from the official Normattiva Open Data API
(api.normattiva.it bff-opendata, async AKN export, CC BY 4.0 since 1 Jan 2026). NOTE: the API export returned only the ORIGINALE (as-enacted) version even when
vigente was requested, so rule_set names say "testo originale" and rows are not the current consolidated text. usage: row_rules11.py IT"""
import sys, re, html
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_rules9 import *
POL = "open_api_documented (Normattiva Open Data API, api.normattiva.it; async export of official AKN)"
LIC = "Normattiva Open Data (Istituto Poligrafico e Zecca dello Stato), CC BY 4.0; legislative texts not protected (L. 633/1941 art. 5)"
def akn(p):
    s = open(p, encoding="utf-8").read(); items = []
    for m in re.finditer(r'<doc name="[^"]*-art\. ?([^"]+)">(.*?)</doc>', s, re.S):
        t = ws2(html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<meta>.*?</meta>", "", m.group(2), flags=re.S))))
        t = re.sub(r"^.*?\bArt\.\s*[\w-]+\s*\.?\s*", "", t, count=1); tm = re.match(r"\(([^)]{3,200})\)\s*", t)
        title = tm.group(1) if tm else None; body = t[tm.end():] if tm else t
        items.append((f"Art. {m.group(1).strip()}", title, body.lstrip(". ")))
    for m in ([] if items else re.finditer(r'<article eId="art_([^"]+)">(.*?)</article>', s, re.S)):
        if m.group(1).startswith("0"): continue
        x = m.group(2); hm = re.search(r"<heading>(.*?)</heading>", x, re.S); title = ws2(html.unescape(re.sub(r"<[^>]+>", " ", hm.group(1)))).strip("() ") if hm else None
        x = re.sub(r"<num>.*?</num>|<heading>.*?</heading>", " ", x, count=2, flags=re.S); body = ws2(html.unescape(re.sub(r"<[^>]+>", " ", x)))
        items.append((f"Art. {m.group(1)}", title or None, body))
    return items
C = ["it-ordinary-supreme", "it-cassazione"]
def it():
    a = f"{RAW}/it/cpc_1940_originale_akn.xml"; b = f"{RAW}/it/cpp_1988_originale_akn.xml"
    r1, x1 = build("it", "it-cpc", "Codice di procedura civile (R.D. 28 ottobre 1940, n. 1443) - testo originale", akn(a), "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:regio.decreto:1940-10-28;1443", S(a), POL, LIC, "it", C, "rule set applies to Italian civil courts", "1942-04-21")
    r2, x2 = build("it", "it-cpp", "Codice di procedura penale (D.P.R. 22 settembre 1988, n. 447) - testo originale", akn(b), "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:decreto.del.presidente.della.repubblica:1988-09-22;447", S(b), POL, LIC, "it", C, "rule set applies to Italian criminal courts", "1989-10-24")
    return r1 + r2, x1 + x2
def ir():
    p = f"{RAW}/ir/cpc_tehran91.html"; s = open(p, encoding="utf-8", errors="ignore").read()
    t = ws2(html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style).*?</\1>", "", s, flags=re.S))))
    ms = list(re.finditer(r"ماده\s*([۰-۹0-9]+)\s*[-–ـ:]", t)); items = []; seen = set(); tr = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    for i, m in enumerate(ms):
        n = m.group(1).translate(tr); e = ms[i + 1].start() if i + 1 < len(ms) else len(t)
        if n in seen: continue
        seen.add(n); body = t[m.end():e].strip()
        if n == "529": body = body.split("کلیه حقوق")[0].strip()
        items.append((f"ماده {n}", None, body))
    return build("ir", "ir-cpc-1379", "قانون آیین دادرسی دادگاه‌های عمومی و انقلاب (در امور مدنی) مصوب ۱۳۷۹ (Code of Civil Procedure 2000, with amendments as published)", items,
                 "https://web.archive.org/web/20220128062351/http://laws.tehran.ir/Law/MainLawView/91", S(p), "archive_wayback (laws.tehran.ir, Tehran City Council legal portal; official rc.majlis.ir and qavanin.ir live sites behind a JS challenge, not bypassed)",
                 "Iranian legislation (Majlis); official texts not protected (Law on Protection of Authors' Rights 1348 art. 2 scope); portal copyright notice by Tehran City Council", "fa", ["ir-ordinary-supreme"], "rule set applies to Iranian general and revolutionary courts (civil matters)", "2000-05-11")
B.update(IT=it, IR=ir)
if __name__ == "__main__":
    for k in sys.argv[1:]:
        rows, xw = B[k]()
        for sid in dict.fromkeys(r["rule_set_id"] for r in rows):
            merge(k.lower(), k, [r for r in rows if r["rule_set_id"] == sid], [x for x in xw if x["rule_set_id"] == sid])
