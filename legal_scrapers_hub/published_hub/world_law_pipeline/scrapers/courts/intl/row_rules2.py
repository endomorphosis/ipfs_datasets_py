"""Chunk-2 procedural rules: PH (Rules of Court, lawphil/E-Library), AR (CPCCN, CPPN; infoleg), CO (CGP, CPP; Senate basedoc via Wayback), CL (CPC, CPP, COT; BCN LeyChile XML).
One row per article/section, original language. -> data/<cc>/<cc>_rules.jsonl + crosswalk.  usage: row_rules2.py PH AR CO CL"""
import sys, hashlib, html, glob
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
RAW = f"{ROOT}/rules/raw"
def sha(*ps):
    h = hashlib.sha256()
    for p in ps: h.update(open(p, "rb").read())
    return h.hexdigest()
def ws(s): return re.sub(r"\s+", " ", s or "").strip()
def htext(p, enc="utf-8"):
    t = open(p, "rb").read().decode(enc, "ignore"); t = re.sub(r"(?s)<(script|style).*?</\1>", "", t); t = re.sub(r"(?i)</(p|div|tr|li|h\d)>|<br\s*/?>", "\n", t)
    return html.unescape(re.sub(r"<[^>]+>", "", t)).replace("\xa0", " ").replace("\r", "")
def row(sid, cc, name, num, text, url, sh, pol, lic, lang, eff=None, title=None):
    return dict(rule_id=f"{sid}:{re.sub(r'[^A-Za-z0-9]+', '-', num).strip('-').lower()}", rule_set_id=sid, court_id=None, jurisdiction=cc, rule_set=name, rule_number=num, title=title, text=text[:12000], effective_date=eff, pdf_path=None, pdf_sha256=None, source_sha256=sh, source_url=url, site_policy=pol, retrieved_at=NOW(), license=lic, language=lang)
def dedupe(rows):
    seen = {}; out = []
    for r in rows:
        k = r["rule_id"]
        if k in seen:
            if len(r["text"]) <= len(seen[k]["text"]): continue
            out[out.index(seen[k])] = r; seen[k] = r; continue
        seen[k] = r; out.append(r)
    return out
# ---------------- PH ----------------
def ph_sections(t):
    out = []; rule = None
    toks = list(re.finditer(r"(?im)^[ \t]*RULE\s+(\d+[A-Z]?)\s*$|^[ \t]*Section\s+(\d+)\.", t))
    for i, m in enumerate(toks):
        if m.group(1): rule = m.group(1); continue
        e = toks[i + 1].start() if i + 1 < len(toks) else len(t); body = ws(t[m.end():e])
        mm = re.match(r"(.{2,160}?)\.\s*[-–]?\s*(.*)", body, re.S)
        title, rest = (mm.group(1).strip(), mm.group(2).strip()) if mm else (None, body)
        if rule and len(rest) > 10: out.append((rule, m.group(2), title, rest))
    return out
def ph():
    SETS = [("ph-roc-civil-2019", "2019 Amendments to the 1997 Rules of Civil Procedure (A.M. No. 19-10-20-SC; amended Rules of Court, Rules 1-71)", "am_19-10-20-sc_2019.html", "https://www.lawphil.net/courts/rules/am_19-10-20-sc_2019.html", "2020-05-01", ["ph-supreme-court", "ph-court-of-appeals", "ph-regional-trial-court", "ph-metropolitan-trial-court"]),
            ("ph-roc-civil-1997", "1997 Rules of Civil Procedure (Rules 1-71, Rules of Court; superseded in part by the 2019 amendments)", "rc_1-71_civil.html", "https://www.lawphil.net/courts/rules/rc_1-71_civil.html", "1997-07-01", ["ph-supreme-court", "ph-court-of-appeals", "ph-regional-trial-court", "ph-metropolitan-trial-court"]),
            ("ph-roc-criminal-2000", "2000 Revised Rules of Criminal Procedure (Rules 110-127, Rules of Court)", "rc_110-127_crim.html", "https://www.lawphil.net/courts/rules/rc_110-127_crim.html", "2000-12-01", ["ph-supreme-court", "ph-court-of-appeals", "ph-regional-trial-court", "ph-sandiganbayan"])]
    rows = []; xw = []
    for sid, name, fn, url, eff, courts in SETS:
        p = f"{RAW}/ph/{fn}"; lst = ph_sections(htext(p)); sh = sha(p)
        for rule, sec, title, rest in lst:
            rows.append(row(sid, "PH", name, f"Rule {rule} Sec. {sec}", rest, url, sh, "secondary:lawphil.net (Arellano Law Foundation); official text at sc.judiciary.gov.ph unreachable from the box", "Philippine court rules are public-domain government works (RA 8293 s.176); lawphil.net compilation, reuse with attribution", "en", eff, title))
        print(sid, len(lst), flush=True)
        for c in courts: xw.append(dict(rule_set_id=sid, rule_set=name, court_id=c, jurisdiction="PH", basis="Rules of Court applicable in this court", source_url=url, linked_rows="new"))
    return rows, xw
# ---------------- AR ----------------
ARTRE = re.compile(r"(?im)^[ \t]*(?:ART[IÍ]CULO|ART\.?)[ \t]+(\d{1,4})[ \t]*(?:[º°o]|bis|ter|quater|quinquies|sexies)?[ \t]*(?:[-–.]|$)")
def ar_split(t):
    ms = list(ARTRE.finditer(t)); out = {}; order = []
    for i, m in enumerate(ms):
        e = ms[i + 1].start() if i + 1 < len(ms) else len(t); k = m.group(1)
        sfx = re.match(r"[ \t]*\d+[ \t]*(bis|ter|quater|quinquies|sexies)", m.group(0), re.I); k = k + ("-" + sfx.group(1).lower() if sfx else "")
        body = ws(t[m.end():e])
        if len(body) < 8: continue
        if k not in out: out[k] = body; order.append(k)
    return [(k, out[k]) for k in order]
def ar():
    SETS = [("ar-cpccn", "Código Procesal Civil y Comercial de la Nación (Ley 17.454, texto ordenado)", "cpccn.htm", "https://servicios.infoleg.gob.ar/infolegInternet/anexos/15000-19999/16547/texact.htm", "1981-01-01", ["ar-csjn", "ar-camara-nacional-civil", "ar-camara-nacional-comercial"]),
            ("ar-cppn", "Código Procesal Penal de la Nación (Ley 23.984; abrogado por Ley 27.063 salvo disposiciones de entrada en vigencia gradual)", "n383.htm", "https://servicios.infoleg.gob.ar/infolegInternet/anexos/0-4999/383/texact.htm", "1992-09-05", ["ar-csjn", "ar-camara-federal-casacion-penal"])]
    rows = []; xw = []
    for sid, name, fn, url, eff, courts in SETS:
        p = f"{RAW}/ar/{fn}"; lst = ar_split(htext(p, "latin-1")); sh = sha(p)
        for k, body in lst:
            rows.append(row(sid, "AR", name, f"Art. {k}", body, url, sh, "robots_unknown:fetched_ok (infoleg.gob.ar; Ministerio de Justicia)", "Argentine legislation is public (Ley 11.723 art. 5 excludes laws from copyright); InfoLEG official database", "es", eff))
        print(sid, len(lst), flush=True)
        for c in courts: xw.append(dict(rule_set_id=sid, rule_set=name, court_id=c, jurisdiction="AR", basis="national procedural code applying to this court", source_url=url, linked_rows="new"))
    return rows, xw
# ---------------- CO ----------------
COART = re.compile(r"(?m)^[ \t]*ART[ÍI]CULO[ \t]+(\d{1,4})(?:[ \t]*([A-Z]))?[ \t]*\.[ \t]*(?:\n|[^\n]*)")
CUT = re.compile(r"\n[ \t]*(?:Jurisprudencia|Concordancias|Notas de Vigencia|Legislaci[óo]n Anterior|Doctrina|Notas del Editor|Vigencia|Texto original|Subsecci[óo]n)\b")
def co_split(t):
    ms = list(re.finditer(r"(?m)^[ \t]*ART[ÍI]CULO[ \t]+(\d{1,4})(?:[ \t]*([A-Z]))?[ \t]*\.", t)); out = {}; order = []
    for i, m in enumerate(ms):
        e = ms[i + 1].start() if i + 1 < len(ms) else len(t); body = t[m.end():e]; c = CUT.search(body)
        if c: body = body[:c.start()]
        body = ws(body); k = m.group(1) + (m.group(2) or "")
        if len(body) < 8 or k in out: continue
        out[k] = body; order.append(k)
    return [(k, out[k]) for k in order]
def co():
    SETS = [("co-cgp", "Código General del Proceso (Ley 1564 de 2012)", "ley_1564_2012", "http://www.secretariasenado.gov.co/senado/basedoc/ley_1564_2012.html", "2012-07-12", ["co-corte-suprema-de-justicia", "co-consejo-de-estado", "co-tribunal-superior"]),
            ("co-cpp", "Código de Procedimiento Penal (Ley 906 de 2004)", "ley_0906_2004", "http://www.secretariasenado.gov.co/senado/basedoc/ley_0906_2004.html", "2004-08-31", ["co-corte-suprema-de-justicia", "co-tribunal-superior"])]
    rows = []; xw = []
    for sid, name, base, url, eff, courts in SETS:
        fs = sorted(glob.glob(f"{RAW}/co/{base}_pr*.html")); t = "\n".join(htext(f) for f in fs); sh = sha(*fs); lst = co_split(t)
        for k, body in lst:
            rows.append(row(sid, "CO", name, f"Art. {k}", body, url, sh, "archive_wayback(live_secretariasenado_unreachable); Senate official basedoc", "Colombian legislation is public domain (Ley 23 de 1982 art. 41); Secretaría del Senado basedoc", "es", eff))
        print(sid, len(fs), "files", len(lst), flush=True)
        for c in courts: xw.append(dict(rule_set_id=sid, rule_set=name, court_id=c, jurisdiction="CO", basis="national procedural code applying to this court", source_url=url, linked_rows="new"))
    return rows, xw
# ---------------- CL ----------------
def cl():
    import xml.etree.ElementTree as ET
    ns = {"n": "http://www.leychile.cl/esquemas"}
    SETS = [("cl-cpc", "Código de Procedimiento Civil (Ley 1.552)", "cpc.xml", "https://www.bcn.cl/leychile/navegar?idNorma=22740", "1903-03-01", ["cl-corte-suprema", "cl-corte-de-apelaciones", "cl-juzgado-civil"]),
            ("cl-cpp", "Código Procesal Penal (Ley 19.696)", "cpp.xml", "https://www.bcn.cl/leychile/navegar?idNorma=176595", "2000-10-12", ["cl-corte-suprema", "cl-corte-de-apelaciones", "cl-juzgado-de-garantia", "cl-tribunal-de-juicio-oral-en-lo-penal"]),
            ("cl-cot", "Código Orgánico de Tribunales (Ley 7.421)", "cot.xml", "https://www.bcn.cl/leychile/navegar?idNorma=25563", "1943-07-09", ["cl-corte-suprema", "cl-corte-de-apelaciones"])]
    rows = []; xw = []
    for sid, name, fn, url, eff, courts in SETS:
        p = f"{RAW}/cl/{fn}"
        if not os.path.exists(p): print("missing", p); continue
        sh = sha(p); r = ET.parse(p).getroot(); lst = []; seen = set()
        for e in r.iter("{http://www.leychile.cl/esquemas}EstructuraFuncional"):
            if e.get("tipoParte") != "Artículo": continue
            tx = e.findtext("n:Texto", namespaces=ns) or ""; tx = ws(tx)
            m = re.match(r"(?:Art[íi]culo|Art\.?)\s+(\d+[º°]?(?:\s*(?:bis|ter|quáter|quater|quinquies|sexies|septies|octies|nonies|decies|[A-Z]))?)[\s.\-–]*(.*)", tx, re.I)
            if not m: continue
            k = re.sub(r"[º°]", "", m.group(1)).strip(); body = m.group(2)
            if e.get("transitorio") == "transitorio": k += " transitorio"
            if len(body) < 8 or k in seen: continue
            seen.add(k); lst.append((k, body, e.get("derogado")))
        for k, body, der in lst:
            rr = row(sid, "CL", name, f"Art. {k}", body, url, sh, "robots_unknown:fetched_ok (leychile.cl XML export; Biblioteca del Congreso Nacional)", "BCN LeyChile: legislation is public; reuse permitted with source citation (CC BY 3.0 CL)", "es", eff)
            if der and der != "no derogado": rr["record_note"] = "derogado"
            rows.append(rr)
        print(sid, len(lst), flush=True)
        for c in courts: xw.append(dict(rule_set_id=sid, rule_set=name, court_id=c, jurisdiction="CL", basis="national procedural code applying to this court", source_url=url, linked_rows="new"))
    return rows, xw
B = dict(PH=ph, AR=ar, CO=co, CL=cl)
# ---------------- NG ----------------
def ng():
    p = f"{RAW}/ng/acja_nms.txt"; t = open(p, errors="ignore").read().replace("\x0c", "\n"); i0 = t.find("ENACTED by the National Assembly"); t = t[i0:]; sh = sha(p)
    pos = 0; hits = []
    for n in range(1, 496):
        m = re.compile(rf"(?m)^[ \t]*{n}\.[ \t]+(?:\(1\)|[A-Z“\"])").search(t, pos)
        if not m: continue
        hits.append((n, m)); pos = m.end()
    rows = []
    for j, (n, m) in enumerate(hits):
        e = hits[j + 1][1].start() if j + 1 < len(hits) else len(t); body = ws(t[m.end():e])
        if len(body) > 12: rows.append(row("ng-acja-2015", "NG", "Administration of Criminal Justice Act, 2015", f"s. {n}", body, "https://justice.gov.ng/wp-content/uploads/2020/09/Administration-of-Justice-Criminal-Act-2015.pdf", sh,
            "official scan at justice.gov.ng is image-only (no OCR available on box); text layer from secondary copy nms.ng/files/Administration of Criminal Justice Act 2015.pdf", "Nigerian federal legislation; official publication (Federal Ministry of Justice); text-layer copy from nms.ng", "en", "2015-05-13"))
    print("ng-acja-2015 sections", len(rows), flush=True)
    xw = [dict(rule_set_id="ng-acja-2015", rule_set="Administration of Criminal Justice Act, 2015", court_id=c, jurisdiction="NG", basis="applies to federal courts and the FCT courts", source_url="https://justice.gov.ng/wp-content/uploads/2020/09/Administration-of-Justice-Criminal-Act-2015.pdf", linked_rows="new") for c in ("ng-supreme-court", "ng-court-of-appeal", "ng-federal-high-court", "ng-fct-high-court")]
    return rows, xw
def ke():
    SETS = [("ke-cpa-cap21", "Civil Procedure Act (Cap. 21)", "cap21.html", "http://kenyalaw.org/lex//actview.xql?actid=CAP.%2021", "1924-01-31", ["ke-high-court", "ke-magistrates-court", "ke-court-of-appeal"], False),
            ("ke-cpc-cap75", "Criminal Procedure Code (Cap. 75)", "cap75.html", "http://kenyalaw.org/lex/actview.xql?actid=CAP.%2075", "1930-01-01", ["ke-high-court", "ke-magistrates-court", "ke-court-of-appeal"], True)]
    rows = []; xw = []
    for sid, name, fn, url, eff, courts, partial in SETS:
        p = f"{RAW}/ke/{fn}"; t = html.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"(?s)<(script|style).*?</\1>", "", open(p, "rb").read().decode("utf-8", "ignore")))).replace("\xa0", " "); t = re.sub(r"\n\s*\n+", "\n", t); sh = sha(p)
        ms = list(re.finditer(r"(?m)^(\d{1,3}[A-Z]{0,2})\.\n", t)); lst = []; seen = set()
        for i, m in enumerate(ms):
            e = ms[i + 1].start() if i + 1 < len(ms) else len(t); body = t[m.end():e]
            tt, _, rest = body.partition("\n"); k = m.group(1)
            if k in seen or len(rest) < 12: continue
            seen.add(k); lst.append((k, ws(tt), ws(rest)))
        for k, tt, rest in lst:
            rr = row(sid, "KE", name, f"s. {k}", rest, url, sh, "archive_wayback(live_new_kenyalaw_waf_challenge); Kenya Law (National Council for Law Reporting) legacy Laws of Kenya database", "Kenya Law legacy database; Laws of Kenya revised edition, reuse with attribution to National Council for Law Reporting", "en", eff, tt)
            if partial: rr["record_note"] = "Wayback capture truncated at 1 MiB: later sections of the Code missing"
            rows.append(rr)
        print(sid, len(lst), flush=True)
        for c in courts: xw.append(dict(rule_set_id=sid, rule_set=name, court_id=c, jurisdiction="KE", basis="procedural statute applying to this court", source_url=url, linked_rows="new"))
    return rows, xw
B["KE"] = ke
B["NG"] = ng

if __name__ == "__main__":
    for cc in sys.argv[1:]:
        rows, xw = B[cc.upper()](); rows = dedupe(rows); d = f"{ROOT}/data/{cc.lower()}"; os.makedirs(d, exist_ok=True)
        wjl(f"{d}/{cc.lower()}_rules.jsonl", rows); wjl(f"{d}/{cc.lower()}_rules_crosswalk.jsonl", xw); print(cc, "rules", len(rows), "xw", len(xw), flush=True)

