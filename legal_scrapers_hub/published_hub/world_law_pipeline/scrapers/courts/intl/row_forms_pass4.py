"""Depth-pass-4 national court-form crawler configs (reuses eu_forms_generic.main). python row_forms_pass4.py <CC> [maxpages] [maxdocs]"""
import sys
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
import eu_forms_generic as g
DOC = r"\.(pdf|docx?|xlsx?|rtf|odt)(\?|$)"
g.CFG.update({
 "ES": dict(host="www.mjusticia.gob.es", seeds=["https://www.mjusticia.gob.es/es/ciudadania/tramites/relacion-descarga-modelos"], page_re=r"modelo|formulario|solicitud|tramite|impreso", doc_re=DOC, lang="es", lic="Ministerio de Justicia de España (mjusticia.gob.es) modelos normalizados; reutilización de información del sector público (Ley 37/2007)"),
 "PL": dict(host="www.gov.pl", seeds=["https://www.gov.pl/web/sprawiedliwosc/formularze-pism-procesowych-w-postepowaniu-cywilnym", "https://www.gov.pl/web/sprawiedliwosc/wzory-pism-i-oswiadczen"], page_re=r"sprawiedliwosc/(formularz|wzor|wzory)", doc_re=r"/attachment/|\.(pdf|docx?|xlsx?|rtf|odt)(\?|$)", lang="pl", lic="Ministerstwo Sprawiedliwości (gov.pl) formularze i wzory pism; official acts and forms are excluded from copyright (Ustawa o prawie autorskim art. 4)"),
 "TR": dict(host="www.adalet.gov.tr", seeds=["https://www.adalet.gov.tr/"], page_re=r"form|dilek|yardim|yardım|basvuru|başvuru", doc_re=DOC, lang="tr", lic="T.C. Adalet Bakanlığı (adalet.gov.tr) published forms; official documents (Fikir ve Sanat Eserleri Kanunu m.31 excludes official texts)"),

 "AT": dict(host="www.justiz.gv.at", seeds=["https://www.justiz.gv.at/service/formulare.2c94848542ec498101437ed8c5af4fe4.de.html"], page_re=r"formular|antrag|vordruck", doc_re=DOC, lang="de", lic="Bundesministerium für Justiz Österreich (justiz.gv.at) Formulare; amtliche Werke are free of copyright (UrhG §7)"),
 "CL": dict(host="www.pjud.cl", seeds=["https://www.pjud.cl/formularios"], page_re=r"formulario|escritos|modelo|tramit", doc_re=DOC, lang="es", lic="Poder Judicial de Chile (pjud.cl) formularios; public institutional information, no licence stated"),
 "UA": dict(host="court.gov.ua", seeds=["https://court.gov.ua/"], page_re=r"zrazk|blank|forma|obrazc|formi|document", doc_re=DOC, lang="uk", lic="Judiciary of Ukraine (court.gov.ua) published forms; official documents are not subject to copyright (Law on Copyright art. 10)"),
})
if __name__ == "__main__": g.main(sys.argv[1], maxpages=int(sys.argv[2]) if len(sys.argv) > 2 else 40, maxdocs=int(sys.argv[3]) if len(sys.argv) > 3 else 200)
