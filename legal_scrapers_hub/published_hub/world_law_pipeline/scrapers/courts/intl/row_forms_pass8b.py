"""Gap pass 8b: multi-host form crawl (one eu_forms_generic config per official host, results merged by sha into data/<cc>/<cc>_forms.jsonl).
IT tribunale-milano.giustizia.it; TR adliye sites on *.adalet.gov.tr; BE rechtbanken-tribunaux.be + justice.belgium.be. robots.txt checked (no ai-train opt-out). python row_forms_pass8b.py CC"""
import sys, json, os
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
import eu_forms_generic as g
from courts_common import ROOT, wjl
DOC = r"\.(pdf|docx?|xlsx?|rtf|odt)(\?|$)"
IT_L = "Ministero della Giustizia / uffici giudiziari (giustizia.it) modulistica; atti ufficiali (L. 633/1941 art. 5)"
TR_L = "T.C. Adalet Bakanlığı adliye web sites (adalet.gov.tr) form/dilekçe örnekleri; official documents (FSEK m.31)"
BE_L = "Belgian courts (rechtbanken-tribunaux.be) / FPS Justice published forms; public information"
H = {
 "IT": [dict(host="tribunale-milano.giustizia.it", seeds=[f"https://tribunale-milano.giustizia.it/it/moduli_1.page?item={i}" for i in range(1, 8)] + ["https://tribunale-milano.giustizia.it/it/moduli_prof.page"], page_re=r"moduli", doc_re=r"/cmsresources/.*" + DOC, lang="it", lic=IT_L)],
 "TR": [dict(host=h, seeds=[f"https://{h}/{p}"], page_re=r"dilek|form", doc_re=DOC, lang="tr", lic=TR_L) for h, p in [("ankara.adalet.gov.tr", "form-ve-dilekceler"), ("bakirkoy.adalet.gov.tr", "ornek-formlar-ve-dilekceler"), ("odemis.adalet.gov.tr", "dilekce-ve-form-ornekleri"), ("adlisicil.adalet.gov.tr", "Home/SayfaDetay/dilekce-ornekleri")]],
 "BE": [dict(host="www.rechtbanken-tribunaux.be", seeds=["https://www.rechtbanken-tribunaux.be/fr/tribunal-de-premiere-instance-francophone-de-bruxelles/documents", "https://www.rechtbanken-tribunaux.be/nl/nederlandstalige-rechtbank-van-eerste-aanleg-brussel/documenten"], page_re=r"documents|documenten", doc_re=r"/sites/default/files/.*" + DOC, lang="fr", lic=BE_L),
        dict(host="justice.belgium.be", seeds=["https://justice.belgium.be/fr/themes_et_dossiers/documents/telecharger_des_documents/formulaires_pour_le_depot_de_documents_au", "https://justice.belgium.be/fr/themes_et_dossiers/documents/telecharger_des_documents"], page_re=r"telecharger|formulaire", doc_re=r"/sites/default/files/.*" + DOC, lang="fr", lic=BE_L)],
}
if __name__ == "__main__":
    cc = sys.argv[1]; low = cc.lower(); p = f"{ROOT}/data/{low}/{low}_forms.jsonl"
    acc = {json.loads(l)["pdf_sha256"]: json.loads(l) for l in open(p)} if os.path.exists(p) else {}
    for c in H[cc]:
        g.CFG[cc] = c
        try: g.main(cc, maxpages=20, maxdocs=120, depth=1)
        except Exception as e: print("ERR", c["host"], e)
        if os.path.exists(p):
            for l in open(p): r = json.loads(l); acc.setdefault(r["pdf_sha256"], r)
        wjl(p, list(acc.values()))
    print(cc, "total forms", len(acc))
