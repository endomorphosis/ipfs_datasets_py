"""Rest-of-world national court-form crawler configs (reuses eu_forms_generic.main). python row_forms_generic.py <CC>"""
import sys
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
import eu_forms_generic as g
DOC = r"\.(pdf|docx?|xlsx?|rtf|odt)(\?|$)"
g.CFG.update({
 "NZ": dict(host="www.justice.govt.nz", seeds=["https://www.justice.govt.nz/courts/civil/forms-and-fees/", "https://www.justice.govt.nz/courts/going-to-court/without-a-lawyer/representing-yourself-civil-high-court/documents-prescribed-forms-and-useful-templates/",
            "https://www.justice.govt.nz/courts/civil/forms-and-fees/dc-rules-dc-act-2016/", "https://www.justice.govt.nz/courts/family/", "https://www.justice.govt.nz/courts/criminal/", "https://www.justice.govt.nz/tribunals/"],
            page_re=r"form|template|prescribed|appl(y|ication)|apply|documents", doc_re=DOC, lang="en", lic="NZ Ministry of Justice (justice.govt.nz) published court forms; CC-BY 4.0 / NZ Government open access licensing framework"),

 "JP": dict(host="www.courts.go.jp", seeds=["https://www.courts.go.jp/saiban/syosiki/index.html", "https://www.courts.go.jp/saiban/syurui/index.html", "https://www.courts.go.jp/saiban/tetuzuki/index.html"],
            page_re=r"syosiki|syurui|tetuzuki|youshiki|moushitate|syoshiki", doc_re=r"\.(pdf|docx?|xlsx?|rtf|ichitaro|jtd)(\?|$)", lang="ja", lic="Supreme Court of Japan (courts.go.jp) published court forms/templates (書式); reuse per site terms"),
})
if __name__ == "__main__": g.main(sys.argv[1], maxpages=int(sys.argv[2]) if len(sys.argv) > 2 else 60, maxdocs=int(sys.argv[3]) if len(sys.argv) > 3 else 300)
