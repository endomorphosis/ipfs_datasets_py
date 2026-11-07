"""Top-court rosters, chunk 4. Names/titles from official court/judiciary pages (via search excerpts); needs_review=true.
Usage: row_judges4.py CC.. -> data/<cc>/<cc>_judges.jsonl"""
import sys
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_judges3 import *
def pol(p, rows):
    for r in rows: r["site_policy"] = p
    return rows
LIC = "official public information; no licence stated"
def ug():
    n = ["Flavian Zeija", "Esther Kisaakye", "Lillian Tibatemwa Ekirikubinza", "Percy Night Tuhaise", "Mike Chibita", "Elizabeth Musoke", "Stephen Musota", "Christopher Madrama Izama", "Catherine K. Bamugemereire", "Monica Kalyegira Mugenyi", "Muzamiru Mutangula Kibeedi"]
    return mk3("UG", "supreme-court", [(x, "Chief Justice of Uganda" if i == 0 else "Justice of the Supreme Court", "chief" if i == 0 else "associate") for i, x in enumerate(n)],
               "https://judiciary.go.ug/data/incourt/3/The+Honourable+Justices+of+the+Supreme+Court+of+Uganda.html", "https://www.judiciary.go.ug/files/downloads/file_1782288656.pdf", "names/titles from the Uganda Judiciary Supreme Court page and Judicial Officers' List (June 2026)", LIC)
def tz():
    n = ["Augustino Gherabait Mwarija", "Shaban Lila", "Rehema Mkuye", "Gerald Ndika", "Jacobs Mwambegele", "Ferdinand Wambali", "Winfrida Korosso", "Barke Sehel", "Lugano Mwandambo", "Mary Levira", "Ignus Kitusi", "Rehema Kerefu", "Zepherine Galeba", "Patricia Fikirini", "Penterine Kente", "Lilian Mashaka", "Paul Kihwelo", "Lucia Kairo", "Issa Maige", "Abraham Mwampashi", "Omar Makungu", "Sam Rumanyika", "Zainabu Muruke", "Leila Mgonya", "Masoud Benhaji", "Amour Khamis", "Gerson Mdemu", "Agnes Mgeyekwa", "Abdul-Hakim Issa", "Lameck Mlacha", "Paul Ngwembe", "Mustafa Ismail", "Eliezer Feleshi", "Latifa Mansoor", "Deo Nangela", "Ubena Agatho"]
    r = [("George Mcheche Masaju", "Chief Justice of Tanzania", "chief")] + [(x, "Justice of Appeal", "associate") for x in n]
    return mk3("TZ", "supreme-court", r, "https://www.judiciary.go.tz/", "https://www.judiciary.go.tz/justiceofappeal", "Court of Appeal of Tanzania (apex court, mapped to the national supreme-court level); names from the Judiciary of Tanzania Comprehensive Performance Report 2025 annex (Justices of Appeal); the 9 justices sworn in 2026 are not yet included", LIC)
def iq():
    n = [("منذر إبراهيم حسين", "رئيس المحكمة الاتحادية العليا", "chief"), ("سمير عباس محمد", "نائب رئيس المحكمة الاتحادية العليا", "associate"), ("غالب عامر شنين", "عضو المحكمة الاتحادية العليا", "associate"), ("حيدر جابر عبد", "عضو المحكمة الاتحادية العليا", "associate"), ("حيدر علي نوري", "عضو المحكمة الاتحادية العليا", "associate"), ("خلف أحمد رجب", "عضو المحكمة الاتحادية العليا", "associate"), ("أيوب عباس صالح", "عضو المحكمة الاتحادية العليا", "associate"), ("صدقي سليم خان نعمان", "عضو المحكمة الاتحادية العليا", "associate")]
    return mk3("IQ", "supreme-court", n, "https://www.iraqfsc.iq/ethadai.php", "http://www.uaccc.org/member-states/the-republic-of-iraq/current-composition/", "Federal Supreme Court of Iraq (constitutional court; body mapped to the national supreme-court level); names from the court's decision of 27-10-2025 (Iraqi Gazette 4848) and the member list; Diyar Mohammed Ali appears in the 2025 decision but not in the current list", LIC)
def lk():
    n = ["Yasantha Kodagoda", "Dilip Nawaz", "Shiran Gooneratne", "Janak de Silva", "Achala Wengappuli", "Mahinda Samayawardhena", "Arjuna Obeyesekere", "Sobhitha Rajakaruna", "Menaka Wijesundara", "Sampath B. Abeykoon", "Sampath Wijeratne", "Gihan Kulatunga"]
    r = [("Padman Surasena", "Chief Justice of Sri Lanka", "chief")] + [(x, "Puisne Justice of the Supreme Court", "associate") for x in n]
    return mk3("LK", "supreme-court", r, "https://supremecourt.lk/", "https://supremecourt.lk/wp-content/uploads/2026/05/Amended-Bench-List-04th-May-to-08th-May-2026.pdf", "composition as of June 2026 per Wikipedia (secondary), cross-checked against names on official Supreme Court bench lists (Mar/May 2026); 4 seats vacant", "secondary roster; names are public facts")
def np_():
    n = ["Sapana Pradhan Malla", "Kumar Regmi", "Hari Prasad Phuyal", "Nahakul Subedi", "Vinod Sharma", "Saranga Subedi", "Abdul Ajiz Musalman", "Mahesh Sharma Poudel", "Tek Prasad Dhungana", "Sunil Kumar Pokharel", "Balkrishna Dhakal", "Nripadhwoj Niraula", "Nityananda Pandeya", "Meghraj Pokharel", "Shreekanta Poudel"]
    r = [("Manoj Kumar Sharma", "Chief Justice of Nepal", "chief")] + [(x, "Justice of the Supreme Court", "associate") for x in n]
    return mk3("NP", "supreme-court", r, "https://supremecourt.gov.np/web/justices", "https://supremecourt.gov.np/web/justices", "names per the Supreme Court of Nepal 'Justices' page (via search excerpt); Latin transliteration", LIC)

def cm():
    import re, html, urllib.request
    b = urllib.request.urlopen(urllib.request.Request("https://coursupreme.cm/membres/", headers={"User-Agent": "Mozilla/5.0"}), timeout=40).read().decode("utf8", "ignore")
    b = re.sub(r"(?s)<(script|style|nav|footer|header)[^>]*>.*?</\1>", "", b)
    L = [x.strip() for x in html.unescape(re.sub(r"<[^>]+>", "\n", b)).split("\n") if x.strip()]
    i = [k for k, x in enumerate(L) if x.startswith("Membres de la Cour Supreme")][-1]
    out = []; seen = set(); k = i + 1
    while k < len(L) - 2:
        if L[k + 1].startswith("Magistrat") and not L[k].startswith("Magistrat"):
            name, t = L[k], L[k + 2]
            if t.startswith("Magistrat") or name in seen: k += 1; continue
            seen.add(name)
            pt = "chief" if t.startswith("Premier Président") else "prosecutor" if re.search(r"Procureur|Avocat Général", t) else "chamber_president" if t.startswith("Président") else "associate"
            out.append((name.title() if name.isupper() else name, t, pt)); k += 3
        else: k += 1
    return pol("no_robots_txt_404|official_page_scrape", mk3("CM", "supreme-court", out, "https://coursupreme.cm/membres/", "https://coursupreme.cm/membres/", "scraped from the official 'Membres de la Cour Suprême du Cameroun' page; names as published (surname/given order varies); includes parquet (Procureur/Avocats Généraux) with position_type=prosecutor", "official public information; no licence stated"))
def ci():
    return pol("robots_allows_generic_ua|official_page", mk3("CI", "supreme-court", [("Yua Koffi", "Président de la Cour de cassation", "chief")], "https://courdecassation.ci/institution/", "https://courdecassation.ci/institution/", "Cour de cassation de Côte d'Ivoire (apex ordinary court since the 2020 organic law; Conseil d'État is the administrative apex; the 'Cour suprême' was abolished); only the president is named on the official page (decree 2023-797)", "official public information; no licence stated"))
BUILD.update({"CM": cm, "CI": ci})
BUILD.update({"UG": ug, "TZ": tz, "IQ": iq, "LK": lk, "NP": np_})
if __name__ == "__main__":
    for cc in sys.argv[1:]:
        rows = BUILD[cc](); os.makedirs(f"{ROOT}/data/{cc.lower()}", exist_ok=True); wjl(f"{ROOT}/data/{cc.lower()}/{cc.lower()}_judges.jsonl", rows); print(cc, len(rows))
