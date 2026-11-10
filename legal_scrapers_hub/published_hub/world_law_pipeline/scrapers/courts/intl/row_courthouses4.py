"""Chunk 5 (phase 7 completion): courthouses + bodies for every remaining country in global_municipalities.
Generic four-tier spec with multilingual tier keywords. Usage: row_courthouses4.py CC.. (or ALL)"""
import sys
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
import row_courthouses3 as m
from row_courthouses3 import *
SUP = r"|Suprema|Supremo|Oberste|Højesteret|Högsta|Vrhovn|Najvyšš|Hæstirétt|Hæstiréttur|Lartë|უზენაეს|Գերագույն|Cassa|Kassa|Hooggerechtshof|Yuqori|Oliy|Дээд|Върховн|Najvyš|Aukščiausias|Augstākā|Riigikohus|Korkein|Høyesterett|Vrhovno|Cour suprême|Cour de cassation|Mahakama Kuu ya Rufaa"
APP = r"|Apellyasiya|Apelac|Apelaci|Apelaç|Apelación|Berufung|Beroep|Žalb|Rayuan|Hovrätt|Landsret|Lagmannsrett|სააპელაციო|Վերաքննիչ|Apelit|Cour d.appel|Appeals|Court of Appeal|Appellate|Cassation Chamber"
HIGH = r"|Cámara|Camara|Audiencia|Tribunal Departamental|Obergericht|Kantonsgericht|Landgericht|Landsretten|Tribunal de Grande Instance|Tribunal Régional|Gjykata e Lartë|Higher|Superior|Tribunal Superior|Corte Superior|Corte de Apelaciones|Cour d.assises|Tribunal de Première Instance de|Region|Supreme Court of .* State|Mahakama Kuu|Tribunal Judicial|Tribunal de Justicia"
LOW = r"|tinghus|tingrett|jordskifte|héraðsdóm|eqqartuus|məhkəm|Məhkəm|шүүх|محاكم|مجمع|maxkamad|mahkamit|Judic|Penal|Judec|Curtea|Judecat|sudi\b|Gjyq|Gjykat|Gericht|sud\b|sodišče|Teismas|სასამართლო|դատարան|tuomioistuin|domstol|dómstóll|kohus|tiesa|Rechtbank|Pengadilan|Tòa|ศาล|Tribunal|Juzgado|Jugado|Juzgad|Corte|Cour\b|Kooti|Mahkama|Mahkeme|Hof\b|Law Court|Magistrate|Sheriff|Justice of the Peace|Tribunale|Giudice|Judge|Juez|Judici|Tribuna|Paz|Alcald.a de justicia|Palacio de Justicia|Palace of Justice|Palais de Justice|Justicia|Justiça|Justice"
def G4(cc, local=""):
    g = G(cc, local); out = []
    for (bid, name, lvl, par, rx) in g:
        if bid == "supreme-court": rx += SUP
        elif bid == "court-of-appeal": rx += APP
        elif bid == "high-court": rx += HIGH
        else: rx += LOW
        out.append((bid, name, lvl, par, rx))
    return out
CC = open("/tmp/allcc.txt").read().split()
for _cc in CC:
    if _cc in m.B and _cc not in ("KH", "BO", "PY", "UY", "CR", "PA", "GT", "DO", "ZM", "ZW", "UZ"): continue
    m.B[_cc] = S(_cc, G4(_cc, m.SPEC_G.get(_cc, "")))
c2.NOT_COURT = re.compile(c2.NOT_COURT.pattern + r"|shipping|marine|navigation|\bltd\b|\bco\.|\bhome\b|\bfamily\b|\bschool\b|\bhotel\b|\bbank\b|\bchurch\b|\bmosque\b|restaurant|\bshop\b|\bhospital\b|\bpharmacy\b|homestead|\bfarm\b|prokuror|tu[zž]ila[sš]t|тужилаштво|правобранилаштво|ministarstvo|министарство|këshilli|\bmib\b|pallati i avokat|upravlenie yusticii|katta eshik|(?<!court )(?<!law )house\\b|domicile|r[eé]sidence|maison|\\bferme\\b|[eé]glise|clinique|abbaye|بيت|ເຮືອນ|village|brigad|зуслан|parquet|auditorat|الإدعاء|الكاتب العدل|\\bguest\\b", re.I)
import row_courthouses2
row_courthouses2.NOT_COURT = c2.NOT_COURT

import json as _j, os as _o
PF = {"ZW": 0.25}
def postfilter(cc, thr=None):
    thr = PF.get(cc, 9) if thr is None else thr
    f = f"/workspace/world_courts/data/{cc.lower()}/{cc.lower()}_courthouses.jsonl"
    rs = [_j.loads(l) for l in open(f)]
    ch = [r for r in rs if r["record_type"] == "courthouse"]
    unc = [r for r in ch if not r.get("parent_court_id") and not r.get("wikidata") and r["name"] != "Courthouse"]
    dropped = 0
    if ch and len(unc) / len(ch) > thr:
        ids = {r["court_id"] for r in unc}; rs = [r for r in rs if r["court_id"] not in ids]; dropped = len(ids)
        with open(f, "w") as o:
            for r in rs: o.write(_j.dumps(r, ensure_ascii=False) + "\n")
    return dropped, len(unc), len(ch)
if __name__ == "__main__":
    ccs = CC if sys.argv[1:] == ["ALL"] else sys.argv[1:]
    for cc in ccs:
        m.B[cc]()
        d = postfilter(cc)
        if d[0]: print("postfilter", cc, "dropped unclassified/unnamed-court rows:", d[0], "of", d[2], flush=True)
        open(f"/workspace/world_courts/data/row/postfilter_{cc}.json", "w").write(_j.dumps({"dropped": d[0], "unclassified": d[1], "courthouses_before": d[2]}))
