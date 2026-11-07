"""Depth-pass-4 rules: GT (Código Procesal Civil y Mercantil, Decreto Ley 107; municipal-government copy of the official text), BJ (Code de procédure civile, commerciale, sociale, administrative et des comptes, loi 2008-07; sgg.gouv.bj)
usage: row_rules6.py CC.. -> data/<cc>/<cc>_rules.jsonl + crosswalk"""
import sys
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_rules5 import *
def gt():
    p = f"{RAW}/gt/cpc.txt"; t = txt(p); sh = sha(f"{RAW}/gt/cpc.pdf"); t = t[t.find("ARTICULO 1. Jurisdicción"):]
    lst = seq_split(t, re.compile(r"(?m)^ARTICULO (\d{1,3})\.[ \t]*"), lambda m: m.group(1))
    url = "https://zaragoza.gob.gt/wp-content/uploads/2023/09/CODIGO-PROCESAL-CIVIL-Y-MERCANTIL-DECRETO-LEY-107.pdf"; name = "Código Procesal Civil y Mercantil (Decreto Ley 107, 1963)"
    rows = [row("gt-cpcm", "GT", name, f"Art. {k}", b, url, sh, "allowed_by_robots (zaragoza.gob.gt; municipal government copy of Decreto Ley 107; the Organismo Judicial library catalogue was not fetchable as a file)", "Guatemalan legislation (Ley de Derecho de Autor y Derechos Conexos art. 4 excludes laws and official texts)", "es", "1964-07-01") for k, b in lst]
    print("gt-cpcm", len(rows)); return rows, xwalk("GT", "gt-cpcm", name, ["gt-supreme-court", "gt-court-of-appeal", "gt-high-court", "gt-lower-court"], url, "national procedural code applying to this court")
def bj():
    p = f"{RAW}/bj/cpc.txt"; t = txt(p); sh = sha(f"{RAW}/bj/cpc.pdf")
    def key(m): return "1" if m.group(1) == "1er" else m.group(1)
    lst = seq_split(t, re.compile(r"(?m)^Article (\d{1,4}|1er)[ \t]*:[ \t]*"), key)
    url = "https://sgg.gouv.bj/doc/loi-2008-07/"; name = "Code de procédure civile, commerciale, sociale, administrative et des comptes (loi n° 2008-07 du 28 février 2011)"
    rows = [row("bj-cpc", "BJ", name, f"Art. {k}", b, url, sh, "allowed_by_robots (sgg.gouv.bj; Secrétariat général du Gouvernement, robots.txt has no disallow rule); pdftotext of a scanned-and-OCR'd PDF, OCR errors possible", "Beninese legislation published by the Secrétariat général du Gouvernement (official texts of laws; no licence stated)", "fr", "2011-02-28") for k, b in lst]
    print("bj-cpc", len(rows)); return rows, xwalk("BJ", "bj-cpc", name, ["bj-supreme-court", "bj-court-of-appeal", "bj-high-court", "bj-lower-court"], url, "national procedural code applying to this court")
B.update(GT=gt, BJ=bj)
if __name__ == "__main__":
    for cc in sys.argv[1:]:
        rows, xw = B[cc.upper()](); rows = dedupe(rows); d = f"{ROOT}/data/{cc.lower()}"; os.makedirs(d, exist_ok=True)
        wjl(f"{d}/{cc.lower()}_rules.jsonl", rows); wjl(f"{d}/{cc.lower()}_rules_crosswalk.jsonl", xw); print(cc, "rules", len(rows), flush=True)
