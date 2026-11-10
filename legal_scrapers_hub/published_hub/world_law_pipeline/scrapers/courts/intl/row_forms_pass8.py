"""Gap pass 8 national court-form crawler configs (reuses eu_forms_generic.main): FR IT CN CH DZ MA (+ existing BE, pass4 TR). robots.txt checked; no ai-train opt-out found on these hosts (2026-10-30).
python row_forms_pass8.py <CC> [maxpages] [maxdocs]"""
import sys
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
import eu_forms_generic as g, row_forms_pass4  # noqa: F401 (registers TR)
DOC = r"\.(pdf|docx?|xlsx?|rtf|odt)(\?|$)"
g.CFG.update({
 "FR": dict(host="www.justice.fr", seeds=["https://www.justice.fr/formulaires", "https://www.justice.fr/"], page_re=r"formulaire|cerfa|demarche|fiche", doc_re=DOC, lang="fr", lic="Ministère de la Justice (justice.fr) formulaires; informations publiques (CRPA L321-1)"),
 "IT": dict(host="www.giustizia.it", seeds=["https://www.giustizia.it/giustizia/page/it/modulistica", "https://www.giustizia.it/giustizia/it/mg_3_1.page", "https://www.giustizia.it/"], page_re=r"modul|mg_3|istanz|domand", doc_re=DOC, lang="it", lic="Ministero della Giustizia (giustizia.it) modulistica; atti ufficiali (L. 633/1941 art. 5)"),
 "CN": dict(host="www.court.gov.cn", seeds=["https://www.court.gov.cn/"], page_re=r"文书|样式|格式|诉讼指南|susong|wenshu", doc_re=DOC, lang="zh", lic="Supreme People's Court (court.gov.cn) litigation document templates; official documents (Copyright Law art. 5)"),
 "CH": dict(host="www.gerichte-zh.ch", seeds=["https://www.gerichte-zh.ch/formulare.html", "https://www.gerichte-zh.ch/"], page_re=r"formular|merkbl|eingabe", doc_re=DOC, lang="de", lic="Gerichte des Kantons Zürich published forms; amtliche Erlasse/Formulare (URG Art. 5)"),
 "DZ": dict(host="www.mjustice.dz", seeds=["https://www.mjustice.dz/", "https://www.mjustice.dz/ar/"], page_re=r"form|imprim|نماذج|استمار|مطبوع", doc_re=DOC, lang="ar", lic="Ministère de la Justice (mjustice.dz) formulaires; official documents"),
 "MA": dict(host="www.mahakim.ma", seeds=["https://www.mahakim.ma/"], page_re=r"form|نماذج|مطبوع|استمار", doc_re=DOC, lang="ar", lic="Ministère de la Justice du Maroc (mahakim.ma) court forms; official documents"),
})
if __name__ == "__main__":
    g.main(sys.argv[1], maxpages=int(sys.argv[2]) if len(sys.argv) > 2 else 25, maxdocs=int(sys.argv[3]) if len(sys.argv) > 3 else 150)
