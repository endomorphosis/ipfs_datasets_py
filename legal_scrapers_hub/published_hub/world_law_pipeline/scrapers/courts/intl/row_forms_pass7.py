"""Depth-pass-7 national court-form crawler configs (reuses eu_forms_generic.main): FI SK PH MW BW NA. python row_forms_pass7.py <CC> [maxpages] [maxdocs]"""
import sys
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
import eu_forms_generic as g
DOC = r"\.(pdf|docx?|xlsx?|rtf|odt)(\?|$)"
g.CFG.update({
 "FI": dict(host="www.tuomioistuimet.fi", seeds=["https://www.tuomioistuimet.fi/asiointi/asiointipalvelut/asiointilomakkeet/", "https://www.tuomioistuimet.fi/tuomioistuimet/kanta-hameen-karajaoikeus/asiointi/asiat-ja-lomakkeet/"], page_re=r"lomakkeet|asiointilomakkeet", doc_re=r"/app/uploads/.*" + DOC, lang="fi", lic="Tuomioistuimet.fi (Finnish courts) published forms; official forms, Copyright Act § 9 excludes official documents"),
 "SK": dict(host="www.justice.gov.sk", seeds=["https://www.justice.gov.sk/sluzby/vzory-a-formulare/vzory-pre-fo-a-po/", "https://www.justice.gov.sk/sluzby/vzory-a-formulare/vzory-a-poucenia-pre-sudy/"], page_re=r"vzory-a-formulare|vzory-a-poucenia", doc_re=DOC, lang="sk", lic="Ministerstvo spravodlivosti SR published court form templates; official documents, no licence stated"),
 "PH": dict(host="sc.judiciary.gov.ph", seeds=["https://sc.judiciary.gov.ph/small-claims/", "https://sc.judiciary.gov.ph/downloads/"], page_re=r"small-claims|downloads", doc_re=r"/wp-content/uploads/.*" + DOC, lang="en", lic="Supreme Court of the Philippines published judicial forms; official forms, no licence stated"),
 "MW": dict(host="www.judiciary.mw", seeds=["https://www.judiciary.mw/judiciary/e-services/e-forms"], page_re=r"e-forms", doc_re=r"/sites/default/files/.*" + DOC, lang="en", lic="Malawi Judiciary published court forms; official forms, no licence stated"),
 "BW": dict(host="www.justice.gov.bw", seeds=["https://www.justice.gov.bw/high-court-forms"], page_re=r"-forms", doc_re=r"/sites/default/files/.*" + DOC, lang="en", lic="Botswana Administration of Justice published High Court forms; official forms, no licence stated"),
 "NA": dict(host="ejustice.moj.na", seeds=["https://ejustice.moj.na/High%20Court/FormsandPrecedents/Pages/HighCourtRules.aspx"], page_re=r"FormsandPrecedents", doc_re=DOC, lang="en", lic="Namibia eJustice (Ministry of Justice / High Court) forms and precedents; official forms, no licence stated"),
})
SLOW = {"BW": 10.0}  # robots.txt Crawl-delay
if __name__ == "__main__":
    if sys.argv[1] in SLOW:
        _pg = g.polite_get; d = SLOW[sys.argv[1]]
        g.polite_get = lambda u, delay=2.0, **k: _pg(u, delay=max(delay, d), **k)
    g.main(sys.argv[1], maxpages=int(sys.argv[2]) if len(sys.argv) > 2 else 20, maxdocs=int(sys.argv[3]) if len(sys.argv) > 3 else 150)
