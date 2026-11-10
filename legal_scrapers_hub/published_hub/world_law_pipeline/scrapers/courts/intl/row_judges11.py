"""Top-court rosters, depth pass 7 (UA TG SL LA HK RS PY NI KG BG SV DK FI NO SK). Public names and titles only; needs_review=true on all rows; pol tags mark weak (news) sources.
Usage: row_judges11.py CC.. -> data/<cc>/<cc>_judges.jsonl (merged by judge_id)"""
import sys, json, os
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_judges7 import *
NEWS = "secondary:news|search_excerpt"; OFF = "robots_unknown:official_site_via_search_excerpt"
B = {
 "UA": lambda: A("UA", "supreme-court", [("Станіслав Кравченко", "Голова Верховного Суду (з 26 травня 2023)", "chief")], "https://supreme.court.gov.ua/", "https://supreme.court.gov.ua/supreme/pres-centr/news/1986474", "Supreme Court of Ukraine press releases naming the President", pol=OFF),
 "TG": lambda: A("TG", "supreme-court", [("Abdoulaye Yaya", "Président de la Cour suprême", "chief")], "https://www.republiquetogolaise.tg/justice/1510-12388-justice-la-cour-supreme-a-effectue-sa-rentree", "https://atop.tg/reprise-des-activites-juridictionnelles-a-la-cour-supreme-du-togo/", "Government portal and national press agency (ATOP) report of the 2026 judicial year opening", pol="secondary:government_portal_and_news"),
 "SL": lambda: A("SL", "supreme-court", [("Komba Kamanda", "Chief Justice (sworn in 20 December 2024)", "chief")], "https://www.sierraleonemonitor.com/president-bio-presides-over-swearing-in-of-new-chief-justice/", "https://sierraleonews.com/2026/10/06/uk-envoy-chief-justice-discuss-sierra-leone-judiciary-reforms/", "Chief Justice per news reports", pol=NEWS),
 "LA": lambda: A("LA", "supreme-court", [("Phaivy Siboualipha", "President of the People's Supreme Court (appointed 23 March 2026)", "chief")], "https://kpl.gov.la/En/detail.aspx?id=97518", "https://cacj-ajp.org/announcements/appointment-of-the-honourable-phaivy-siboualipha-as-president-of-the-people-s-supreme-court-of-the-lao-pdr/", "KPL (Lao state news agency) and CACJ announcement", pol=NEWS),
 "HK": lambda: A("HK", "supreme-court", [("Andrew Cheung Kui-nung", "Chief Justice of the Court of Final Appeal (since 11 January 2021)", "chief")], "https://www.hkcfa.hk/", "https://www.hkcfa.hk/en/about/who/judges/chief_justice/index.html", "Court of Final Appeal Chief Justice page", pol=OFF),
 "RS": lambda: A("RS", "supreme-court", [("Мирољуб Томић", "Председник Врховног суда (од 1. јула 2026)", "chief")], "https://vrh.sud.rs/", "https://vrh.sud.rs/en/court-president", "Supreme Court of Serbia president page", pol=OFF),
 "PY": lambda: A("PY", "supreme-court", [("Alberto Joaquín Martínez Simón", "Presidente de la Corte Suprema de Justicia (período febrero 2026 - febrero 2027)", "chief")], "https://www.pj.gov.py/", "https://www.pj.gov.py/notas/29409-corte-suprema-de-justicia-eligio-a-sus-nuevas-autoridades-para-el-periodo-febrero-2026-febrero-2027", "Poder Judicial del Paraguay news release", pol=OFF),
 "NI": lambda: A("NI", "supreme-court", [("Ana Julia Guido Ochoa", "Presidenta de la Corte Suprema de Justicia (juramentada 1 sep 2026)", "chief"), ("José Manuel Fuertes Toledo", "Vicepresidente de la Corte Suprema de Justicia", "associate")], "https://noticias.asamblea.gob.ni/juramentamos-a-los-companes-ana-julia-guido-y-jose-manuel-fuertes-como-presidenta-y-vicepresidente-de-la-corte-suprema-de-justicia/", "https://www.prensa-latina.cu/2026/09/01/nicaragua-parlamento-ratifica-nuevas-autoridades-de-corte-suprema/", "National Assembly news portal and Prensa Latina", pol="secondary:legislature_release_and_news"),
 "KG": lambda: A("KG", "supreme-court", [("Медербек Сатыев", "Председатель Верховного суда (назначен в октябре 2024)", "chief")], "https://ru.kabar.kg/news/satyev-nezavisimoe-rassmotrenie-ekologicheskix-del-prioritet-sudov/", "https://kginform.com/ru/news/20241024/55289.html", "Kabar (state news agency) and KGinform", pol=NEWS),
 "BG": lambda: A("BG", "ordinary-supreme", [("Галина Захарова", "Председател (изпълняващ функциите) на Върховния касационен съд", "chief")], "https://www.vks.bg/", "https://www.vks.bg/sastav-i-struktura.html", "VKS composition page; holds the post in an acting capacity per press reports", pol=OFF),
 "SV": lambda: A("SV", "supreme-court", [("Jenny Alvarado Tení", "Presidenta de la Corte Suprema de Justicia y del Órgano Judicial (desde 13 oct 2026)", "chief")], "https://www.csj.gob.sv/", "https://www.soy502.com/articulo/jenny-alvaro-teni-fue-juramentada-como-presidenta-csj-102154", "News report of the 13 Oct 2026 swearing-in (very recent; verify on csj.gob.sv)", pol=NEWS),
 "DK": lambda: A("DK", "ordinary-supreme", [("Jens Peter Christensen", "Præsident for Højesteret (fratræder 30. november 2026; Oliver Talevski fra 1. december 2026)", "chief"), ("Oliver Talevski", "Højesteretsdommer, valgt præsident fra 1. december 2026", "associate")], "https://www.domstol.dk/hoejesteret/", "https://domstoldk.euwest01.umbraco.io/aktuelt/2026/9/hoejesteret-faar-ny-praesident/", "Danmarks Domstole press release on the presidency change", pol=OFF),
 "FI": lambda: A("FI", "ordinary-supreme", [("Tatu Leppänen", "Korkeimman oikeuden presidentti (1.9.2019 alkaen)", "chief")], "https://www.korkeinoikeus.fi/", "https://www.korkeinoikeus.fi/tietoa-meista/henkilosto/presidentti-ja-jasenet/", "Supreme Court of Finland president and members page", pol=OFF),
 "NO": lambda: A("NO", "supreme-court", [("Toril Marie Øie", "Justitiarius, Høyesterett (siden 2016)", "chief")], "https://www.domstol.no/no/hoyesterett/", "https://www.domstol.no/no/hoyesterett/dommere/oie/", "Høyesterett judge page (domstol.no)", pol=OFF),
 "SK": lambda: A("SK", "ordinary-supreme", [("František Mozner", "Predseda Najvyššieho súdu SR (od 21. mája 2025)", "chief")], "https://www.nsud.sk/", "https://www.nsud.sk/predseda-najvyssieho-sudu/", "Najvyšší súd SR president page", pol=OFF),
}
if __name__ == "__main__":
    for cc in sys.argv[1:]:
        rows = B[cc](); p = f"/workspace/world_courts/data/{cc.lower()}/{cc.lower()}_judges.jsonl"
        old = [json.loads(l) for l in open(p)] if os.path.exists(p) else []
        seen = {r["judge_id"]: r for r in old}
        for r in rows: seen[r["judge_id"]] = r
        with open(p, "w") as f:
            for r in seen.values(): f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(cc, len(rows))
