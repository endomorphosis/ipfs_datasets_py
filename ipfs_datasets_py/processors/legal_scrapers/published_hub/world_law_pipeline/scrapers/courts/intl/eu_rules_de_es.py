"""Procedural codes: DE (gesetze-im-internet.de XML, official, §5 UrhG amtliche Werke) and ES (BOE consolidated-legislation open API, reuse Ley 37/2007/CC-BY 4.0 'BOE').
-> data/de/de_rules.jsonl, data/es/es_rules.jsonl  (crosswalk built in eu_crosswalk.py)"""
import sys, io, zipfile, hashlib, re, os, time
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import cached
from lxml import etree
def ws(s): return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()
def row(sid, name, jur, num, title, text, src, sha, pol, lic, lang, eff=None):
    return dict(rule_id=f"{sid}:{num}", rule_set_id=sid, court_id=None, jurisdiction=jur, rule_set=name, rule_number=num, title=title, text=text, effective_date=eff, pdf_path=None, pdf_sha256=None, source_sha256=sha,
                source_url=src, site_policy=pol, retrieved_at=NOW(), license=lic, language=lang)
DE = [("zpo", "Zivilprozessordnung"), ("stpo", "Strafprozessordnung"), ("gvg", "Gerichtsverfassungsgesetz"), ("vwgo", "Verwaltungsgerichtsordnung"), ("arbgg", "Arbeitsgerichtsgesetz"),
      ("sgg", "Sozialgerichtsgesetz"), ("fgo", "Finanzgerichtsordnung"), ("famfg", "Gesetz über das Verfahren in Familiensachen und in den Angelegenheiten der freiwilligen Gerichtsbarkeit"),
      ("bverfgg", "Bundesverfassungsgerichtsgesetz"), ("jgg", "Jugendgerichtsgesetz"), ("owig", "Gesetz über Ordnungswidrigkeiten"), ("rpflg", "Rechtspflegergesetz"), ("inso", "Insolvenzordnung")]
def de():
    out = []
    for slug_, nm in DE:
        b, u, pol = cached(f"https://www.gesetze-im-internet.de/{slug_}/xml.zip", f"intl_de_{slug_}.zip", delay=2.0, binary=True)
        if not b: print("DE miss", slug_); continue
        sha = hashlib.sha256(b).hexdigest(); z = zipfile.ZipFile(io.BytesIO(b)); xml = z.read([n for n in z.namelist() if n.endswith(".xml")][0])
        root = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, load_dtd=False)); sid = f"de-{slug_}"; n = 0
        title_full = ws(root.findtext(".//langue")) or nm; abbr = ws(root.findtext(".//jurabk")) or slug_.upper()
        for norm_ in root.iter("norm"):
            enbez = ws(norm_.findtext("metadaten/enbez"))
            if not re.match(r"^(§|Art)", enbez): continue
            c = norm_.find("textdaten/text/Content")
            if c is None: continue
            text = ws(" ".join(ws("".join(p.itertext())) for p in c.iter("P")))
            if len(text) < 5: continue
            out.append(row(sid, f"{title_full} ({abbr})", "DE", enbez, ws(norm_.findtext("metadaten/titel")) or None, text, f"https://www.gesetze-im-internet.de/{slug_}/{enbez.replace('§ ', 'BJNR').replace(' ', '_')}.html" if False else f"https://www.gesetze-im-internet.de/{slug_}/", sha, pol, "public domain (amtliches Werk, § 5 UrhG)", "de")); n += 1
        print("DE", slug_, n, flush=True)
    wjl(f"{ROOT}/data/de/de_rules.jsonl", out); return out
ES = [("BOE-A-2000-323", "es-lec", "Ley 1/2000, de Enjuiciamiento Civil"), ("BOE-A-1882-6036", "es-lecrim", "Ley de Enjuiciamiento Criminal (RD 14 sep 1882)"), ("BOE-A-1998-16718", "es-lrjca", "Ley 29/1998, reguladora de la Jurisdicción Contencioso-administrativa"),
      ("BOE-A-2011-15936", "es-lrjs", "Ley 36/2011, reguladora de la jurisdicción social"), ("BOE-A-1985-12666", "es-lopj", "Ley Orgánica 6/1985, del Poder Judicial"), ("BOE-A-1979-23709", "es-lotc", "Ley Orgánica 2/1979, del Tribunal Constitucional")]
def es():
    import urllib.request
    out = []
    for bid, sid, nm in ES:
        p = f"{RAW_}/intl_es_{bid}.xml"
        if not os.path.exists(p):
            time.sleep(2.0); r = urllib.request.urlopen(urllib.request.Request(f"https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/{bid}", headers={"Accept": "application/xml", "User-Agent": UA}), timeout=120)
            open(p, "wb").write(r.read())
        raw = open(p, "rb").read(); sha = hashlib.sha256(raw).hexdigest(); root = etree.fromstring(raw); n = 0
        for bl in root.iter("bloque"):
            if bl.get("tipo") != "precepto": continue
            vs = bl.findall("version")
            if not vs: continue
            v = vs[-1]; ps = [p for p in v.iter("p")]
            if not ps: continue
            head = ws("".join(ps[0].itertext())); m = re.match(r"^(Artículo|Art\.|Disposición\s+\w+(?:\s+\w+)?|Artículo\s+\w+)\s*([\w.ºª-]*)\.?\s*(.*)$", head)
            mm = re.match(r"^(Artículo\s+[\w.ºª-]+(?:\s+(?:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies))?)\.?\s*(.*)$", head)
            num = ws(mm.group(1)) if mm else head[:60]; title = (mm.group(2) if mm else None) or None
            text = ws(" ".join(ws("".join(q.itertext())) for q in ps[1:]))
            if len(text) < 5: continue
            out.append(row(sid, nm, "ES", num, title, text, f"https://www.boe.es/buscar/act.php?id={bid}", sha, "robots_allowed", "BOE reuse (Ley 37/2007; CC-BY 4.0 equivalent, attribution: Agencia Estatal Boletín Oficial del Estado)", "es", eff=(v.get("fecha_vigencia") or None))); n += 1
        print("ES", sid, n, flush=True)
    wjl(f"{ROOT}/data/es/es_rules.jsonl", out); return out
RAW_ = "/workspace/world_courts/rules/raw"
if __name__ == "__main__":
    os.makedirs(f"{ROOT}/data/de", exist_ok=True); os.makedirs(f"{ROOT}/data/es", exist_ok=True)
    for a in (sys.argv[1:] or ["de", "es"]): {"de": de, "es": es}[a]()
