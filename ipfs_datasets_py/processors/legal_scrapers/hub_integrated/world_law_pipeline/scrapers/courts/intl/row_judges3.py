"""Top-court rosters, chunk 3. Official-site excerpts located via web search (host pages are SPA/unreachable from the box); needs_review=true.
Usage: row_judges3.py CC.. -> data/<cc>/<cc>_judges.jsonl"""
import sys
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_judges2 import *
SP = "robots_unknown:official_site_unreachable_or_spa|search_excerpt"
def mk3(cc, court, people, url, roster, ext, lic):
    return [J(cc, court, n, t, pt, url, roster, SP, ext, lic) for n, t, pt in people]
def sg():
    p = [("Sundaresh Menon", "Chief Justice", "chief"), ("Ang Cheng Hock", "Justice of the Court of Appeal", "associate"), ("Hri Kumar Nair", "Justice of the Court of Appeal", "associate"), ("Sushil Nair", "Justice of the Court of Appeal", "associate"), ("Hoo Sheau Peng", "Justice of the Court of Appeal", "associate"),
         ("Woo Bih Li", "Judge of the Appellate Division (President)", "associate"), ("Kannan Ramesh", "Judge of the Appellate Division", "associate"), ("Debbie Ong Siew Ling", "Judge of the Appellate Division", "associate"), ("See Kee Oon", "Judge of the Appellate Division", "associate"), ("Goh Yihan", "Judge of the Appellate Division (from 2026-10-01)", "associate")]
    return mk3("SG", "supreme-court", p, "https://www.sgdi.gov.sg/organs-of-state/supcourt", "https://www.judiciary.gov.sg/who-we-are/role-structure-supreme-court/structure", "names/titles from the Singapore Government Directory (SGDI) and judiciary.gov.sg structure page as returned by web search; High Court judges omitted", "Singapore Judiciary public website; Singapore Open Data Licence")
def my():
    n = ["Wan Ahmad Farid bin Wan Salleh", "Rhodzariah binti Bujang", "Nordin bin Hassan", "Vazeer Alam bin Mydin Meera", "Ahmad Terrirudin bin Mohd Salleh", "Lee Swee Seng", "Che Mohd. Ruzima bin Ghazali", "Mohd Nazlan bin Mohd Ghazali", "Collin Lawrence Sequerah", "Azimah binti Omar", "Ravinthran a/l N. Paramaguru", "Azmi bin Ariffin"]
    return mk3("MY", "federal-court", [(x, "Chief Justice of Malaysia" if i == 0 else "Judge of the Federal Court", "chief" if i == 0 else "associate") for i, x in enumerate(n)], "https://www.kehakiman.gov.my/en/about-us/court/federal-court/federal-court-judges", "https://www.kehakiman.gov.my/en/about-us/court/federal-court/federal-court-judges", "name list from the official Federal Court Judges pages as returned by web search; honorifics (Tun/Tan Sri/Dato') omitted; President of the Court of Appeal / Chief Judges not included", "Malaysian judiciary public website")
def il():
    n = ["Yitzhak Amit", "Noam Sohlberg", "Daphne Barak-Erez", "David Mintz", "Yael Willner", "Ofer Grosskopf", "Alex Stein", "Gila Canfy-Steinitz", "Khaled Kabub", "Ruth Ronnen", "Yechiel Kasher"]
    r = mk3("IL", "supreme-court", [(x, "President of the Supreme Court" if i == 0 else "Deputy President" if i == 1 else "Justice", "chief" if i == 0 else "associate") for i, x in enumerate(n)], "https://supreme.court.gov.il/sites/en/Pages/Justices.aspx", "https://supreme.court.gov.il/sites/en/Pages/Justices.aspx", "name list from the official Supreme Court of Israel Justices page as returned by web search", "Israeli Judicial Authority public website")
    return r
def pk():
    n = ["Yahya Afridi", "Munib Akhtar", "Jamal Khan Mandokhail", "Muhammad Ali Mazhar", "Ayesha A. Malik", "Shahid Waheed", "Musarrat Hilali", "Irfan Saadat Khan", "Naeem Akhtar Afghan", "Malik Shehzad Ahmed Khan", "Aqeel Ahmed Abbasi", "Shahid Bilal Hassan", "Muhammad Hashim Khan Kakar", "Muhammad Shafi Siddiqui", "Ishtiaq Ibrahim", "Shakeel Ahmad", "Salahuddin Panhwar"]
    return mk3("PK", "supreme-court", [(x, "Chief Justice of Pakistan" if i == 0 else "Judge of the Supreme Court", "chief" if i == 0 else "associate") for i, x in enumerate(n)], "https://www.supremecourt.gov.pk/honorable-judges-2/", "https://www.supremecourt.gov.pk/honorable-judges-2/", "name list from the official Honorable Judges page as returned by web search", "Supreme Court of Pakistan public website")
def gh():
    n = ["Paul Baffoe-Bonnie", "Gabriel Pwamang", "Avril Lovelace-Johnson", "Issifu Omoro Tanko Amadu", "Henrietta Nyarko Mensa-Bonsu", "Emmanuel Yonny Kulendi", "Samuel Kwame Adibu-Asiedu", "George Kingsley Koomson", "Ernest Yao Gaewu", "Henry A. Kwofie", "Yaw Darko Asare", "Richard Adjei-Frimpong", "Senyo Dzamefe", "Dennis Dominic Adjei", "Gbiel Simon Suurbaareh", "Janapare Adzua Bartels-Kodwo", "Hafisata Amaleboba", "Kweku Tawiah Ackaah-Boafo", "Sophia Rosetta Bernasko Essah", "Edward Amoako Asante", "Tony Forson"]
    return mk3("GH", "supreme-court", [(x, "Chief Justice of Ghana" if i == 0 else "Justice of the Supreme Court", "chief" if i == 0 else "associate") for i, x in enumerate(n)], "https://judicial.gov.gh/index.php/supreme-court-judges", "https://judicial.gov.gh/index.php/supreme-court-judges", "name list from the official judiciary Supreme Court Judges page and GNA report (swearing-in of three new justices on 2026-09-10) as returned by web search", "Judicial Service of Ghana public website")
BUILD.update({"SG": sg, "MY": my, "IL": il, "PK": pk, "GH": gh})
if __name__ == "__main__":
    for cc in sys.argv[1:]:
        rows = BUILD[cc](); os.makedirs(f"{ROOT}/data/{cc.lower()}", exist_ok=True); wjl(f"{ROOT}/data/{cc.lower()}/{cc.lower()}_judges.jsonl", rows); print(cc, len(rows))
