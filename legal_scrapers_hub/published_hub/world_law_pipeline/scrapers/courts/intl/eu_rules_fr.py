"""French procedural codes from the DILA 'LEGI' open-data dump (echanges.dila.gouv.fr/OPENDATA/LEGI, Licence Ouverte / Open Licence 2.0 Etalab). Legifrance itself returns 403 to the box, so the official
open-data dump is used (Freemium_legi_global_20250713 snapshot: articles in force at 2025-07-13; later amendments NOT applied). Streams the tar once, keeps articles with ETAT=VIGUEUR of the target codes.
-> data/fr/fr_rules.jsonl"""
import sys, tarfile, re, hashlib, collections
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
from lxml import etree
TGT = {"LEGITEXT000006070716": ("fr-cpc", "Code de procédure civile"), "LEGITEXT000006071154": ("fr-cpp", "Code de procédure pénale"), "LEGITEXT000006070933": ("fr-cja", "Code de justice administrative"),
       "LEGITEXT000006071164": ("fr-coj", "Code de l'organisation judiciaire"), "LEGITEXT000025024948": ("fr-cpcexec", "Code des procédures civiles d'exécution")}
TAR = f"{ROOT}/data/ref/legi/Freemium_legi_global.tar.gz"
def ws(s): return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()
def main():
    rows = []; keys = [k.encode() for k in TGT]; n = 0; sha = "dump:Freemium_legi_global_20250713-140000"
    with tarfile.open(TAR, "r|gz") as tf:
        for m in tf:
            n += 1
            if not m.isfile() or "/LEGI/ARTI/" not in m.name or not m.name.endswith(".xml"): continue
            b = tf.extractfile(m).read()
            if not any(k in b for k in keys): continue
            try: r = etree.fromstring(b)
            except Exception: continue
            cid = r.find(".//CONTEXTE/TEXTE").get("cid") if r.find(".//CONTEXTE/TEXTE") is not None else None
            if cid not in TGT or ws(r.findtext(".//META_ARTICLE/ETAT")) != "VIGUEUR": continue
            sid, nm = TGT[cid]; num = ws(r.findtext(".//META_ARTICLE/NUM")); aid = ws(r.findtext(".//META_COMMUN/ID"))
            c = r.find(".//BLOC_TEXTUEL/CONTENU"); text = ws(" ".join(c.itertext())) if c is not None else ""
            if not num or len(text) < 5: continue
            rows.append(dict(rule_id=f"{sid}:{num}:{aid}", rule_set_id=sid, court_id=None, jurisdiction="FR", rule_set=nm, rule_number=f"Article {num}", title=None, text=text, effective_date=ws(r.findtext(".//META_ARTICLE/DATE_DEBUT")) or None, pdf_path=None, pdf_sha256=None,
                             source_sha256=sha, source_url=f"https://www.legifrance.gouv.fr/codes/article_lc/{aid}", site_policy="open_data_dump", retrieved_at=NOW(), license="Licence Ouverte 2.0 (Etalab), source DILA/Légifrance LEGI open data", language="fr"))
            if len(rows) % 1000 == 0: print(len(rows), n, flush=True)
    os.makedirs(f"{ROOT}/data/fr", exist_ok=True); wjl(f"{ROOT}/data/fr/fr_rules.jsonl", rows)
    print("FR rules", len(rows), collections.Counter(r["rule_set_id"] for r in rows))
if __name__ == "__main__": main()
