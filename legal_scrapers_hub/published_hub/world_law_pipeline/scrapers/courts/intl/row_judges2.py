"""Top-court rosters, chunk 2 (KR TW PH AR CO CL NG KE). Official pages where reachable (cached), otherwise official-site excerpts located via web search (tagged site_policy/extraction, needs_review=true).
Usage: row_judges2.py CC.. -> data/<cc>/<cc>_judges.jsonl"""
import sys
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_judges import *
def tw():
    u = "https://cons.judicial.gov.tw/docdata.aspx?fid=2147"; out = []
    names = [("謝銘洋", "Ming-Yan SHIEH", "Acting President of the Judicial Yuan and Chief Justice of the Constitutional Court", "chief", "2019-10-01"), ("呂太郎", "Tai-Lang LU", "Justice of the Constitutional Court", "associate", "2019-10-01"), ("蔡彩貞", "Tsai-Chen TSAI", "Justice of the Constitutional Court", "associate", "2023-10-01"),
             ("楊惠欽", "Hui-Chin YANG", "Justice of the Constitutional Court", "associate", "2019-10-01"), ("蔡宗珍", "Tzung-Jen TSAI", "Justice of the Constitutional Court", "associate", "2019-10-01"), ("尤伯祥", "Po-Hsiang YU", "Justice of the Constitutional Court", "associate", "2023-10-01"),
             ("陳忠五", "Chung-Wu CHEN", "Justice of the Constitutional Court", "associate", "2023-10-01"), ("朱富美", "Fu-Meei JU", "Justice of the Constitutional Court", "associate", "2023-10-01")]
    for zh, en, t, pt, ts in names:
        r = J("TW", "constitutional-court", zh, t, pt, u, "https://cons.judicial.gov.tw/", "robots_unknown:official_site_unreachable_from_box|search_excerpt", "name list from official Constitutional Court site (Current Members / Annual Report) as returned by web search; host unreachable from the box; 8 of 15 seats filled (nominations rejected by Legislative Yuan)",
              "Judicial Yuan, Taiwan public website; Government Website Open Data License", term_start=ts)
        r["name_en"] = en; out.append(r)
    return out
def mk(cc, court, names, ptitle, url, roster, pol, ext, lic, chief=None, tmap=None):
    out = []
    for n in names:
        chief_ = chief and n.startswith(chief)
        t = (tmap or {}).get(n) or (ptitle[0] if chief_ else ptitle[1])
        out.append(J(cc, court, n, t, "chief" if chief_ else "associate", url, roster, pol, ext, lic, term_start=None))
    return out
SP = "robots_unknown:official_site_unreachable_from_box|search_excerpt"
def ph():
    names = ["Alexander G. Gesmundo", "Marvic M.V.F. Leonen", "Alfredo Benjamin S. Caguioa", "Ramon Paul L. Hernando", "Amy C. Lazaro-Javier", "Henri Jean Paul B. Inting", "Rodil V. Zalameda", "Samuel H. Gaerlan", "Ricardo R. Rosario", "Jhosep Y. Lopez", "Japar B. Dimaampao", "Jose Midas P. Marquez", "Antonio T. Kho, Jr.", "Maria Filomena D. Singh", "Raul B. Villanueva"]
    return mk("PH", "supreme-court", names, ("Chief Justice", "Associate Justice"), "https://sc.judiciary.gov.ph/incumbent-justices/", "https://sc.judiciary.gov.ph/incumbent-justices/", SP, "name list from the official Incumbent Justices page as returned by web search (host unreachable from the box); cross-checked with SC press releases of Jan 2026", "Supreme Court of the Philippines public website; Philippine government works are public domain (RA 8293 s.176)", chief="Alexander", tmap={"Marvic M.V.F. Leonen": "Senior Associate Justice"})
def kr():
    names = ["조희대", "천대엽", "오경미", "오석준", "서경환", "권영준", "엄상필", "신숙희", "노경필", "박영재", "이숙연", "마용주", "김성수"]
    r = mk("KR", "supreme-court", names, ("Chief Justice (대법원장)", "Justice (대법관)"), "https://scourt.go.kr/supreme/news/ChfJusticeListAction.work?gubun=705&top=Y", "https://www.scourt.go.kr/judiciary/organization/supreme/index.html", SP, "Hangul name list from the official scourt.go.kr Justices page as returned by web search (host unreachable from the box); roster may be incomplete (court has the Chief Justice + 13 Justices)", "Supreme Court of Korea website; KOGL Type 1 / public-sector works (Copyright Act art. 7 excludes some official documents)", chief="조희대")
    for x in r: x["name_local"] = x["name"]
    return r
def co():
    names = ["Paola Andrea Meneses Mosquera", "Natalia Ángel Cabo", "Jorge Enrique Ibáñez Najar", "Juan Carlos Cortés González", "Vladimir Fernández Andrade", "Héctor Alfonso Carvajal Londoño", "Carlos Camargo Assis", "Lina Marcela Escobar Martínez", "Miguel Polo Rosero"]
    return mk("CO", "corte-constitucional", names, ("Presidenta (Magistrada)", "Magistrado/a"), "https://www.corteconstitucional.gov.co/ingles/justices", "https://www.ramajudicial.gov.co/portal/sobre-la-rama/magistrados-de-las-altas-cortes/corte-constitucional", SP, "name list from official Corte Constitucional / Rama Judicial pages as returned by web search; 2026 presidency per corteconstitucional.gov.co news 36305", "Rama Judicial / Corte Constitucional public website; Colombian official works (Ley 23/1982 art. 41)", chief="Paola", tmap={"Natalia Ángel Cabo": "Vicepresidenta (Magistrada)"})
def cl():
    names = ["Gloria Ana Chevesich Ruiz", "Ricardo Blanco", "Andrea Muñoz", "Manuel Valderrama", "Arturo Prado", "Mauricio Silva", "María Angélica Repetto", "Leopoldo Llanos", "Adelita Ravanales", "Mario Carroza", "Jean Pierre Matus", "María Cristina Gajardo", "María Soledad Melo", "Jessica González", "Mireya López", "Omar Astudillo", "Gonzalo Ruz", "Jorge Zepeda"]
    return mk("CL", "corte-suprema", names, ("Presidenta (Ministra)", "Ministro/a"), "https://www.pjud.cl/tribunales/corte-suprema", "https://www.pjud.cl/tribunales/corte-suprema", "robots_unknown:official_site_behind_captcha|search_excerpt", "name list from pjud.cl / Poder Judicial press as returned by web search (pjud.cl serves a human-verification captcha to the box, not bypassed); roster may be incomplete (court has 21 ministros)", "Poder Judicial de Chile public website; Chilean official works", chief="Gloria")
def ng():
    names = ["Kudirat Motonmori Olatokunbo Kekere-Ekun", "John Inyang Okoro", "Uwani Musa Abba Aji", "Mohammed Lawal Garba", "Helen Moronkeji Ogunwumiju", "Ibrahim Njodi Mohammed Saulawa", "Adamu Jauro", "Tijjani Abubakar", "Emmanuel Akomaye Agim", "Haruna Simon Tsammani", "Moore Aseimo Abraham Adumein", "Jummai Hannatu Sankey", "Chidiebere Nwaoma Uwa", "Chioma Egondu Nwosu-Iheme", "Obande Festus Ogbuinya", "Stephen Jonah Adah", "Habeeb Adewale Olumuyiwa Abiru", "Jamilu Yammama Tukur", "Abubakar Umar", "Mohammed Idris", "Joseph Olubunmi Kayode Oyewole"]
    return mk("NG", "supreme-court", names, ("Chief Justice of Nigeria", "Justice of the Supreme Court"), "https://bob.gov.ng/justices-of-the-supreme-court/", "https://www.supremecourt.gov.ng/", "robots_unknown:official_site_js_only|search_excerpt", "name list from Body of Benchers / court reports as returned by web search (supremecourt.gov.ng is a JavaScript-only app with no static roster); sworn-in list as of Feb 2026 (21 justices)", "Nigerian public-office roster; compiled from Body of Benchers (bob.gov.ng) public page", chief="Kudirat")
def ar():
    u = "https://www.csjn.gov.ar/institucional/jueces"; out = []
    for n, t, pt, ts in (("Horacio Daniel Rosatti", "Presidente de la Corte Suprema", "chief", "2016-06-01"), ("Carlos Fernando Rosenkrantz", "Vicepresidente", "associate", "2016-08-01"), ("Ricardo Luis Lorenzetti", "Ministro de la Corte Suprema", "associate", "2004-12-01")):
        out.append(J("AR", "csjn", n, t, pt, u, u, "robots_unknown:fetched_ok", "official CSJN Jueces page (HTML, parsed names and 'ministro desde' dates)", "Corte Suprema de Justicia de la Nación public website; Ley 11.723 art. 5", term_start=ts))
    return out
def ke():
    u = "https://judiciary.go.ke/supreme-court-judges/"; out = []
    for n, t, pt in (("Martha Koome", "Chief Justice and President of the Supreme Court", "chief"), ("Philomena Mbete Mwilu", "Deputy Chief Justice and Vice-President of the Supreme Court", "associate"), ("Mohamed Abdulahi Warsame", "Justice of the Supreme Court", "associate"), ("Isaac Lenaola", "Justice of the Supreme Court", "associate"),
                     ("Njoki Ndungu", "Justice of the Supreme Court", "associate"), ("William Ouko", "Justice of the Supreme Court", "associate")):
        out.append(J("KE", "supreme-court", n, t, pt, u, u, "robots_unknown:fetched_ok", "official Judiciary of Kenya Supreme Court Judges page (HTML headings)", "Judiciary of Kenya public website; reuse with attribution"))
    return out
BUILD.update({"TW": tw, "PH": ph, "KR": kr, "CO": co, "CL": cl, "NG": ng, "AR": ar, "KE": ke})
if __name__ == "__main__":
    for cc in sys.argv[1:]:
        rows = BUILD[cc](); os.makedirs(f"{ROOT}/data/{cc.lower()}", exist_ok=True); wjl(f"{ROOT}/data/{cc.lower()}/{cc.lower()}_judges.jsonl", rows); print(cc, len(rows))
