"""Depth-pass-6 national court-form crawler configs (reuses eu_forms_generic.main): DE TT GY JM BB (BS files return 500; FJ challenge page). python row_forms_pass6.py <CC> [maxpages] [maxdocs]"""
import sys
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
import eu_forms_generic as g
DOC = r"\.(pdf|docx?|xlsx?|rtf|odt)(\?|$)"
F = "https://justiz.de/service/formular/"
g.CFG.update({
 "DE": dict(host="justiz.de", seeds=[F + s + "/index.php" for s in ["f_allgemeines", "f_europa", "f_familie", "f_insolvenzen", "f_kosten_verguetungen", "f_mahn_vollstreckung", "f_zivilprozess"]], page_re=r"/service/formular/f_", doc_re=DOC, lang="de", lic="Justizportal des Bundes und der Länder (justiz.de) bundeseinheitliche Formulare; amtliche Formulare (§ 5 UrhG)"),
 "JM": dict(host="supremecourt.gov.jm", seeds=["https://supremecourt.gov.jm/supreme-court-forms"], page_re=r"forms", doc_re=DOC, lang="en", lic="Supreme Court of Jamaica published forms; official court forms, no licence stated"),
 "TT": dict(host="www.ttlawcourts.org", seeds=["https://www.ttlawcourts.org/uncategorised/supreme-court-forms-civil"], page_re=r"forms", doc_re=DOC, lang="en", lic="Judiciary of Trinidad and Tobago published forms; official court forms, no licence stated"),
 "FJ": dict(host="judiciary.gov.fj", seeds=["https://judiciary.gov.fj/forms/", "https://judiciary.gov.fj/courts/magistrates-court/family/", "https://judiciary.gov.fj/courts/magistrates-court/civil/"], page_re=r"/forms/|/courts/", doc_re=DOC, lang="en", lic="Judiciary of Fiji published forms; official court forms, no licence stated"),
 "BS": dict(host="courts.bs", seeds=["http://courts.bs/"], page_re=r"form", doc_re=r"/wp-content/uploads/.*(form|Form|Affidavit|Summons|Probate|Requisition|Application)[^/]*" + DOC, lang="en", lic="The Judiciary of The Bahamas (courts.bs) published forms; official court forms, no licence stated"),
 "GY": dict(host="supremecourt.gy", seeds=["https://supremecourt.gy/rules-of-court", "https://supremecourt.gy/forms", "https://supremecourt.gy/filing"], page_re=r"forms|rules-of-court|filing", doc_re=DOC, lang="en", lic="Supreme Court of Judicature of Guyana published forms; official court forms, no licence stated"),
 "BB": dict(host="www.barbadoslawcourts.gov.bb", seeds=["https://www.barbadoslawcourts.gov.bb/useful-links/for-public/application-forms/"], page_re=r"^$-never", doc_re=r"/applications-forms/.*" + DOC, lang="en", lic="Barbados Judicial System (Supreme Court Registry) published application forms; official forms, no licence stated"),
})
SLOW = {"GY": 10.0, "BB": 10.0}  # robots.txt Crawl-delay values honoured
if __name__ == "__main__":
    if sys.argv[1] in SLOW:
        _pg = g.polite_get; d = SLOW[sys.argv[1]]
        g.polite_get = lambda u, delay=2.0, **k: _pg(u, delay=max(delay, d), **k)
    if sys.argv[1] == "BB":  # page uses <base href="/">: resolve relative asset links against the site root
        import urllib.parse as _up; _uj = _up.urljoin
        g.urllib.parse.urljoin = lambda b, h, *a: _uj("https://www.barbadoslawcourts.gov.bb/", h) if h.startswith("assets/") else _uj(b, h, *a)
    g.main(sys.argv[1], maxpages=int(sys.argv[2]) if len(sys.argv) > 2 else 40, maxdocs=int(sys.argv[3]) if len(sys.argv) > 3 else 200)
