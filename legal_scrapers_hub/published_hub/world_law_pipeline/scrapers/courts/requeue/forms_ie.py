"""IE court forms (courts.ie /forms/ pages -> /docs/ files; robots disallow /docs/ ignored per owner 2026-11-01; Crawl-delay 10; deed-poll register excluded)."""
import sys
sys.path.insert(0,"/workspace/world_courts/scrapers/courts/intl")
import eu_forms_generic as g
g.CFG["IE"]=dict(host="www.courts.ie",seeds=[l.strip() for l in open("/workspace/world_courts/scrapers/courts/requeue/ie_form_pages.txt") if l.strip()],
  page_re=r"^\b$",doc_re=r"^(?!.*deed-poll)(?!.*deed_poll).*/docs/.*\.(pdf|docx?|rtf|odt)(\?|$)",lang="en",
  lic="Courts Service of Ireland (courts.ie) court forms; official forms, no licence stated")
g.main("IE",maxpages=int(sys.argv[1]),maxdocs=int(sys.argv[2]),depth=0)
