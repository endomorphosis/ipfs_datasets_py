"""Generic bounded national court-form crawler: python eu_forms_generic.py <CC>. Per-country seeds/host/page-link regex below; follows same-host links (depth<=DEPTH, <=MAXPAGES pages) whose url or text matches PAGE_RE,
downloads pdf/doc(x)/xls(x)/rtf links -> forms/<cc>/<sha256>.<ext>; metadata -> data/<cc>/<cc>_forms.jsonl. robots.txt honoured via polite_get; crawl delay 2 s; resumable (re-run skips known sha)."""
import sys, hashlib, urllib.parse, collections
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import polite_get
from bs4 import BeautifulSoup
CFG = {
 "AT": dict(host="www.justiz.gv.at", seeds=["https://www.justiz.gv.at/service/formulare.2c94848a.html", "https://www.justiz.gv.at/service/verfahrenshilfe.960.de.html", "https://www.justiz.gv.at/service/familienrecht.962.de.html",
            "https://www.justiz.gv.at/service/gebuehren-und-einbringungsrecht.385.de.html", "https://www.justiz.gv.at/service/opferhilfe-und-prozessbegleitung.961.de.html"],
            page_re=r"formular|antrag|verfahrenshilfe|familienrecht|gebuehren|opferhilfe|vordruck", doc_re=r"/file/[^?]*\.(pdf|docx?|xlsx?|rtf)", lang="de", lic="Austrian Federal Ministry of Justice (justiz.gv.at) published court forms; public information, reuse per site terms"),
 "SE": dict(host="www.domstol.se", seeds=["https://www.domstol.se/amnen/", "https://www.domstol.se/blanketter/", "https://www.domstol.se/amnen/familj/", "https://www.domstol.se/amnen/tvist/"],
            page_re=r"blankett|formul|ansok|ansökan|mal-|\-och-blanketter", doc_re=r"\.(pdf|docx?|xlsx?|rtf)(\?|$)", lang="sv", lic="Sveriges Domstolar (domstol.se) published forms; public judiciary documents, reuse per site terms"),
 "CZ": dict(host="www.justice.cz", seeds=["https://www.justice.cz/web/msp/formulare", "https://www.justice.cz/web/msp/"], page_re=r"formul|tiskopis", doc_re=r"\.(pdf|docx?|xlsx?|rtf|odt)(\?|$)", lang="cs", lic="Czech Ministry of Justice (justice.cz) published forms; public information"),
 "BE": dict(host="justice.belgium.be", seeds=["https://justice.belgium.be/nl/themas_en_dossiers/formulieren", "https://justice.belgium.be/fr/themes_et_dossiers/formulaires"], page_re=r"formul", doc_re=r"\.(pdf|docx?|xlsx?|rtf)(\?|$)", lang="nl", lic="Belgian FPS Justice (justice.belgium.be) published forms; public information"),
 "FI": dict(host="www.tuomioistuimet.fi", seeds=["https://www.tuomioistuimet.fi/asiointi/asiointipalvelut/asiointilomakkeet/", "https://www.tuomioistuimet.fi/asiointi/"], page_re=r"lomake|hakemus|asiakirjapohja", doc_re=r"\.(pdf|docx?|xlsx?|rtf|odt)(\?|$)", lang="fi", lic="Finnish courts (oikeus.fi / Oikeusministeriö) published forms; public information"),
 "SI": dict(host="www.sodisce.si", seeds=["https://www.sodisce.si/sodisca/obrazci/", "https://www.sodisce.si/"], page_re=r"obrazc|vlog|formular", doc_re=r"\.(pdf|docx?|xlsx?|rtf|odt)(\?|$)|/mma/[^?]*obrazec", lang="sl", lic="Sodstvo Republike Slovenije (sodisce.si) published forms; public information"),
 "HR": dict(host="sudovi.hr", seeds=["https://sudovi.hr/hr/ossb/pristup-informacijama/obrasci", "https://sudovi.hr/hr/"], page_re=r"obrasc|obrazac|zahtjev|tuzb", doc_re=r"\.(pdf|docx?|xlsx?|rtf|odt)(\?|$)", lang="hr", lic="Sudovi Republike Hrvatske (sudovi.hr) published forms; public information"),
 "SK": dict(host="obcan.justice.gov.sk", seeds=["https://obcan.justice.gov.sk/", "https://obcan.justice.gov.sk/pre-obcana/formulare"], page_re=r"formul|tlačiv|tlaciv", doc_re=r"\.(pdf|docx?|xlsx?|rtf|odt)(\?|$)", lang="sk", lic="Ministerstvo spravodlivosti SR (justice.gov.sk) published forms; public information"),
 "EE": dict(host="www.kohus.ee", seeds=["https://www.kohus.ee/", "https://www.kohus.ee/et/vormid"], page_re=r"vorm|avaldus|blankett|taotlus", doc_re=r"\.(pdf|docx?|xlsx?|rtf|odt|asice)(\?|$)", lang="et", lic="Eesti kohtud (kohus.ee) published forms; public information"),
 "LV": dict(host="www.tiesas.lv", seeds=["https://www.tiesas.lv/lv/tiesvediba", "https://www.tiesas.lv/"], page_re=r"/lv/[a-z0-9-]*(tiesvedib|veidlap|iesniegum|paraug|pieteikum|palidzib|valsts-nodev|mediacij)", doc_re=r"\.(pdf|docx?|xlsx?|rtf|odt|edoc)(\?|$)", lang="lv", lic="Latvijas tiesas (tiesas.lv) published forms; public information"),
 "CY": dict(host="www.supremecourt.gov.cy", seeds=["https://www.supremecourt.gov.cy/"], page_re=r"form|entypa|έντυπ", doc_re=r"\.(pdf|docx?|xlsx?|rtf|odt)(\?|$)", lang="el", lic="Supreme Court of Cyprus published forms; public information"),
}
def main(cc, maxpages=50, maxdocs=300, depth=2):
    c = CFG[cc]; low = cc.lower(); os.makedirs(f"{ROOT}/forms/{low}", exist_ok=True); os.makedirs(f"{ROOT}/data/{low}", exist_ok=True)
    out = []; seen = set(); q = [(u, 0, u) for u in c["seeds"]]; docs = {}; pg = 0
    while q and pg < maxpages:
        u, d, cat = q.pop(0); u = re.sub(r";jsessionid=[^?#]*", "", u)
        if u in seen: continue
        seen.add(u); b, eu, pol = polite_get(u, delay=2.0)
        if not b: continue
        pg += 1; s = BeautifulSoup(b.decode("utf-8", "replace"), "html.parser")
        for a in s.find_all("a", href=True):
            h = re.sub(r";jsessionid=[^?#]*", "", urllib.parse.urljoin(u, a["href"]).split("#")[0]); t = a.get_text(" ", strip=True)
            if urllib.parse.urlparse(h).netloc != c["host"]: continue
            if re.search(c["doc_re"], h, re.I): docs.setdefault(h, (t, u, cat, pol))
            elif d < depth and h not in seen and re.search(c["page_re"], h + " " + t, re.I) and not re.search(r"\.(jpg|png|zip)$", h, re.I): q.append((h, d + 1, cat))
        print("page", pg, u[-70:], len(docs), flush=True)
    for i, (h, (t, src, cat, pol)) in enumerate(docs.items()):
        if i >= maxdocs: break
        b, eu, p2 = polite_get(h, delay=2.0, binary=True, maxbytes=40_000_000)
        if not b or len(b) < 500: continue
        m = re.search(r"\.(pdf|docx?|xlsx?|rtf|odt)(\?|$)", h, re.I); ext = m.group(1).lower() if m else ("pdf" if b[:4] == b"%PDF" else "docx" if b[:2] == b"PK" else "doc" if b[:4] == b"\xd0\xcf\x11\xe0" else "bin"); sha = hashlib.sha256(b).hexdigest(); path = f"forms/{low}/{sha}.{ext}"
        if not os.path.exists(f"{ROOT}/{path}"): open(f"{ROOT}/{path}", "wb").write(b)
        if any(o["pdf_sha256"] == sha for o in out): continue
        title = re.sub(r"\s*\((pdf|docx?|xlsx?)[^)]*\)\s*$", "", t, flags=re.I).strip() or urllib.parse.unquote(h.rsplit("/", 1)[-1].split("?")[0])
        out.append(dict(form_id=f"{low}-{sha[:16]}", court_id=None, jurisdiction=cc, form_number=None, title=title, category=cat.rsplit("/", 1)[-1][:80], language=c["lang"], file_format=ext, pdf_path=path, pdf_sha256=sha, file_bytes=len(b),
                        source_url=eu, index_url=src, license=c["lic"], site_policy=p2, retrieved_at=NOW()))
        if len(out) % 20 == 0: wjl(f"{ROOT}/data/{low}/{low}_forms.jsonl", out)
    wjl(f"{ROOT}/data/{low}/{low}_forms.jsonl", out); print(cc, "forms", len(out), collections.Counter(o["file_format"] for o in out))
if __name__ == "__main__": main(sys.argv[1])
