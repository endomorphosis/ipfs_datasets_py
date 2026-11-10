"""Top-court rosters, depth pass 1 (BD DE TR ID CN RU ET EG CD VN IR TH). Names/titles from official court/judiciary pages (via search excerpts) or, where tagged, news/secondary sources; needs_review=true.
Usage: row_judges5.py CC.. -> data/<cc>/<cc>_judges.jsonl"""
import sys, re
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_judges4 import *
LIC = "official public information; no licence stated"
def P(rows, pol): 
    for r in rows: r["site_policy"] = pol
    return rows
def A(cc, court, people, url, roster, ext, lic=LIC, pol="robots_unknown:official_site_unreachable_or_spa|search_excerpt"): return P(mk3(cc, court, people, url, roster, ext, lic), pol)
def bd():
    n = ["Md. Rezaul Haque", "S. M. Emdadul Hoque", "Farah Mahbub", "Md. Habibul Gani"]
    return A("BD", "supreme-court", [("Zubayer Rahman Chowdhury", "Chief Justice of Bangladesh", "chief")] + [(x, "Judge, Appellate Division", "associate") for x in n], "https://www.supremecourt.gov.bd/web/?div_id=1&lang=&menu=11&page=judges.php", "https://www.supremecourt.gov.bd/web/?div_id=1&lang=&menu=11&page=judges.php", "Appellate Division of the Supreme Court of Bangladesh (judges' list page; Habibul Gani sworn in 30 Aug 2026)")
def de():
    s1 = ["Stephan Harbarth", "Yvonne Ott", "Henning Radtke", "Ines Härtel", "Heinrich Amadeus Wolff", "Martin Eifert", "Miriam Meßling", "Günter Spinner"]
    s2 = ["Ann-Katrin Kaufhold", "Christine Langenfeld", "Astrid Wallrabenstein", "Rhona Fetzer", "Thomas Offenloch", "Peter Frank", "Holger Wöckel", "Sigrid Emmenegger"]
    r = [(s1[0], "Präsident des Bundesverfassungsgerichts; Vorsitzender des Ersten Senats", "chief")] + [(x, "Richter/in des Ersten Senats", "associate") for x in s1[1:]] + [(s2[0], "Vizepräsidentin; Vorsitzende des Zweiten Senats", "associate")] + [(x, "Richter/in des Zweiten Senats", "associate") for x in s2[1:]]
    return A("DE", "constitutional-supreme", r, "https://www.bundesverfassungsgericht.de/DE/DasBundesverfassungsgericht/RichterinnenRichter/richterinnenRichter_node.html", "https://www.bundesverfassungsgericht.de/DE/GrundgesetzRechtsgrundlagen/Geschaeftsverteilung/gv2026/geschaeftsverteilung_2026_node.html", "Federal Constitutional Court, composition for Geschäftsjahr 2026 (members cross-checked against the 2026 chamber assignments)", pol="robots_unknown:search_excerpt")
def tr():
    m = ["Engin Yıldırım", "Rıdvan Güleç", "Recai Akyel", "Yusuf Şevki Hakyemez", "Yıldız Seferinoğlu", "Selahaddin Menteş", "Kenan Yaşar", "Muhterem İnce", "Yılmaz Akçil", "Ömer Çınar", "Metin Kıratlı", "Şaban Kazdal"]
    r = [("Kadir Özkaya", "Başkan (President) of the Constitutional Court", "chief"), ("Basri Bağcı", "Başkanvekili", "associate"), ("İrfan Fidan", "Başkanvekili", "associate")] + [(x, "Üye", "associate") for x in m]
    return A("TR", "anayasa-mahkemesi", r, "https://www.anayasa.gov.tr/tr/baskanvekilleri-ve-uyeler/uyeler/", "https://www.anayasa.gov.tr/tr/baskanvekilleri-ve-uyeler/uyeler/", "Turkish Constitutional Court (15 members); names from the court's members page, titles/dates cross-checked with Turkish Wikipedia (secondary) — Chair term ends 22 Dec 2026")
def nm(s):
    s = s.split(",")[0]; s = re.sub(r"^(?:(?:Prof|Dr|Drs|Dra|H|Hj|Brigjen TNI \(Purn\))\.?\s*)+", "", s.strip(), flags=re.I); s = re.sub(r"\s+", " ", s).strip(" .")
    return s.title() if s.isupper() else s
def idn():
    lead = [("Sunarto", "Ketua Mahkamah Agung", "chief"), ("Suharto", "Wakil Ketua MA Bidang Yudisial", "associate"), ("Dwiarso Budi Santiarto", "Wakil Ketua MA Bidang Non-Yudisial", "associate"),
            ("Prim Haryadi", "Ketua Kamar Pidana", "chamber_president"), ("I Gusti Agung Sumanatha", "Ketua Kamar Perdata", "chamber_president"), ("Yasardin", "Ketua Kamar Agama", "chamber_president"), ("Hidayat Manao", "Ketua Kamar Militer", "chamber_president"),
            ("Yulius", "Ketua Kamar Tata Usaha Negara", "chamber_president"), ("Syamsul Ma'arif", "Ketua Kamar Pembinaan (Hakim Agung Kamar Perdata)", "chamber_president"), ("Yanto", "Ketua Kamar Pengawasan (Hakim Agung Kamar Pidana)", "chamber_president")]
    K = {"Pidana": ["Surya Jaya", "Salman Luthan", "Soesilo", "Jupriyadi", "Yohanes Priyana", "Achmad Setyo Pudjoharsoyo", "Ainal Mardhiah", "Noor Edi Yono", "Sigid Triyono", "Sutarjo", "Suradi"],
         "Perdata": ["Nurul Elmiyah", "Hamdi", "Panji Widagdo", "Ibrahim", "Muhammad Yunus Wahab", "Pri Pambudi Teguh", "Rahmi Mulyati", "Nani Indrawati", "Lukas Prakoso", "Agus Subroto", "Ennid Hasanuddin", "Heru Pramono"],
         "Agama": ["Busra", "Imron Rosyadi", "Lailatul Arofah", "Muhayah"], "Tata Usaha Negara": ["Irfan Fachrudin", "Yosran", "Yodi Martono Wahyunadi", "Cerah Bangun", "Lulik Tri Cahayaningrum", "Hari Sugiharto", "Budi Nugroho", "Diana Melamita Ginting"],
         "Militer": ["Sugeng Sutrisno", "Tama Ulinta Tarigan", "Agustinus Purnomo Hadi"]}
    new = [("Syamsul Arief", "Pidana"), ("Sugiyanto", "Pidana"), ("Sudharmawatiningsih", "Pidana"), ("Dhifla Wiyani", "Pidana"), ("Sobandi", "Perdata"), ("Nurnaningsih", "Perdata"), ("Musthofa", "Agama"), ("Mamat Ruhimat", "Agama"), ("Maftuh Effendi", "Tata Usaha Negara (khusus pajak)"), ("L.Y. Hari Sih Advianto", "Tata Usaha Negara (khusus pajak)"), ("Yeheskiel Minggus Tiranda", "Tata Usaha Negara (khusus pajak)")]
    r = list(lead); seen = {x[0] for x in lead}
    for k, v in K.items():
        for x in v:
            if x not in seen: seen.add(x); r.append((x, f"Hakim Agung Kamar {k}", "associate"))
    for x, k in new:
        if x not in seen: seen.add(x); r.append((x, f"Hakim Agung Kamar {k} (dilantik 2 Sep 2026)", "associate"))
    return A("ID", "mahkamah-agung", r, "https://kepaniteraan.mahkamahagung.go.id/id/registry-news/3061-kini-ma-miliki-57-hakim-agung-dan-12-hakim-ad-hoc", "https://kepaniteraan.mahkamahagung.go.id/registry-news/2859-hakim-agung-yanto-dilantik-tuaka-was-inilah-formasi-lengkap-pimpinan-ma-di-awal-2026", "Mahkamah Agung: leadership and chamber rosters as published Jan 2026 (48 justices) plus the 11 sworn in 2 Sep 2026; the court reports 57 justices, so ~2 departures since January are not reflected; ad hoc judges not included")
def cn():
    r = [("张军", "最高人民法院院长、首席大法官 (President, Chief Justice)", "chief"), ("邓修明", "副院长、一级大法官 (executive Vice President)", "associate"), ("陶凯元", "副院长、二级大法官", "associate"), ("杨临萍", "副院长、第六巡回法庭庭长、二级大法官", "associate"), ("茅仲华", "副院长、第一巡回法庭庭长、二级大法官", "associate"),
         ("李勇", "副院长、第二巡回法庭庭长、二级大法官", "associate"), ("王中明", "副院长、第四巡回法庭庭长", "associate"), ("党广锁", "副院长 (appointed 28 Aug 2026)", "associate"), ("高晓力", "副院长、二级大法官", "associate"), ("王淑梅", "审判委员会专职委员、第三巡回法庭庭长、二级大法官", "associate"),
         ("葛迪", "二级大法官 (Grand Justice, announced 26 Feb 2026)", "associate"), ("王红卫", "二级大法官 (announced 26 Feb 2026)", "associate"), ("秦海", "二级大法官 (announced 26 Feb 2026)", "associate"), ("陈志君", "二级大法官 (announced 26 Feb 2026)", "associate")]
    return A("CN", "supreme-peoples-court", r, "https://www.court.gov.cn/jigou/fayuanlingdao.html", "https://www.court.gov.cn/jigou/fayuanlingdao.html", "Supreme People's Court leadership page (院长, 副院长, 专职委员) plus the Feb 2026 Grand Justice announcement; rank-and-file judges (审判员) not listed; the 2026-08-28 NPCSC appointment (党广锁) is reflected; 沈亮 removed same day", pol="robots_unknown:official_page_search_excerpt")
def ru():
    r = [("Игорь Викторович Краснов", "Председатель Верховного Суда Российской Федерации", "chief"), ("Владимир Александрович Давыдов", "Первый заместитель Председателя", "associate"), ("Игорь Владимирович Крупнов", "Заместитель Председателя (административные дела)", "associate"),
         ("Николай Викторович Тимошин", "Заместитель Председателя (уголовные дела)", "associate"), ("Владимир Владимирович Хомчик", "Заместитель Председателя (дела военнослужащих)", "associate"), ("Олег Николаевич Нефедов", "Заместитель Председателя — председатель Судебной коллегии по гражданским делам", "associate")]
    return A("RU", "supreme-court", r, "https://www.vsrf.ru/about/structure", "https://www.vsrf.ru/about/info/court/structure", "Supreme Court of the Russian Federation, leadership only (the court has ~170 judges; the full roster page was not retrievable)")
def et():
    return A("ET", "federal-supreme-court", [("Tewodros Meheret Kebede", "President of the Federal Supreme Court", "chief"), ("Abeba Embiale", "Vice President of the Federal Supreme Court", "associate")], "https://www.fsc.gov.et/About-Us/President/Current-President", "https://www.fsc.gov.et/About-Us/Vice-President/Current-Vice-President", "Federal Supreme Court of Ethiopia: President and Vice President only (the 16 justices appointed 2024 are not named on the site)")
def eg():
    mem = ["عادل عمر شريف", "رجب عبد الحكيم سليم", "محمود محمد غنيم", "محمد عماد النجار", "عبد العزيز محمد سالمان", "طارق عبد الجواد شبل", "طارق عبد العليم أبو العطا", "خالد أحمد رأفت", "علاء الدين أحمد السيد", "فاطمة محمد الرزاز", "صلاح محمد الرويني", "محمد أيمن عباس"]
    dep = ["شيرين حافظ موسى فرهود", "عوض عبد الحميد عبد الله علي خليفة", "مراد فكري هابيل قرياقص", "تامر عبد الحميد حمد فرجاني"]
    r = [("بولس فهمي إسكندر", "رئيس المحكمة الدستورية العليا", "chief")] + [(x, "نائب رئيس المحكمة (قرار جمهوري 29 سبتمبر 2026)", "associate") for x in dep] + [(x, "عضو المحكمة", "associate") for x in mem]
    return A("EG", "supreme-constitutional-court", r, "https://www.shorouknews.com/news/view.aspx?cdate=29092026&id=6a0608d4-6aee-4490-bb41-2926bcb88b74", "https://www.masralyoum.net/9416576", "Supreme Constitutional Court of Egypt (apex constitutional court mapped to the national supreme-court level); names from Egyptian news reports of the 29 Sep 2026 presidential decree — secondary source, no official roster page located", pol="secondary:news_report|search_excerpt")
def cd():
    cc = ["Norbert Nkulu Kilombo Mitumba", "François Bokona Wiipa Bondjali", "Alphonsine Kalume Asengo Cheusi", "Christian Jalar Yuma Bahati", "Sylvain Lumu Mbaya", "Dieudonné Mandza Andia", "Marthe Odio Nonde", "Kahindo Nguru Aristide"]
    r = [("Élie-Léon Ndomba Kabeya", "Premier président de la Cour de cassation", "chief"), ("Brigitte Nsensele wa Nsensele", "Présidente du Conseil d'État", "associate")] + [(x, "Juge à la Cour constitutionnelle", "associate") for x in cc]
    return A("CD", "supreme-court", r, "https://cour-constitutionnelle.cd/", "https://conseildetat.cd/judges", "DRC apex courts: Cour de cassation (president per press report of the 28 Jul 2026 reshuffle), Conseil d'État (president), Cour constitutionnelle ('notamment' — partial member list)", pol="robots_unknown:official_and_news|search_excerpt")
def vn():
    r = [("Nguyễn Văn Quảng", "Chánh án Tòa án nhân dân tối cao (2026–2031)", "chief")] + [(x, "Phó Chánh án Tòa án nhân dân tối cao", "associate") for x in ["Nguyễn Hải Trâm", "Dương Văn Thăng", "Nguyễn Văn Tiến", "Phạm Quốc Hưng", "Lê Tiến", "Nguyễn Biên Thùy"]]
    return A("VN", "toa-an-nhan-dan-toi-cao", r, "https://xaydungchinhsach.chinhphu.vn/tieu-su-dong-chi-nguyen-van-quang-chanh-an-toa-an-nhan-dan-toi-cao-nhiem-ky-2026-2031-11926040716361848.htm", "https://vi.wikipedia.org/wiki/T%C3%B2a_%C3%A1n_nh%C3%A2n_d%C3%A2n_t%E1%BB%91i_cao_(Vi%E1%BB%87t_Nam)", "Supreme People's Court: Chief Justice per Government site / National Assembly resolution 11/2026/QH16; deputy chief justices per Vietnamese Wikipedia (secondary)", pol="secondary:wikipedia+official|search_excerpt")
def ir():
    return A("IR", "supreme-court", [("محمدجعفر منتظری", "رئیس دیوان عالی کشور", "chief")], "https://www.mizanonline.ir/fa/news/4923530/", "https://www.mizanonline.ir/fa/news/4923530/", "Supreme Court of Iran: president as presiding the 21 Mehr 1405 general-board session (Mizan, judiciary news agency); the Tasnim item reports a change of president is expected — verify", pol="secondary:judiciary_news_agency|search_excerpt")
def th():
    return A("TH", "supreme-court", [("วีระพงศ์ สุดาวงศ์", "ประธานศาลฎีกา (คนที่ 52, from 1 Oct 2569/2026)", "chief"), ("ชยโยศ อรณูศรี", "รองประธานศาลฎีกา", "associate"), ("ชวลิต อิสระเดจ", "รองประธานศาลฎีกา", "associate")], "https://www.supremecourt.or.th/index.php/en/executive-of-the-supreme-court-of-thailand", "https://www.supremecourt.or.th/index.php/en/executive-of-the-supreme-court-of-thailand", "Supreme Court of Thailand executives; President per Thai press report of the Royal appointment effective 1 Oct 2026, Vice Presidents per the court's executive page (may pre-date the change)")
BUILD.update({"BD": bd, "DE": de, "TR": tr, "ID": idn, "CN": cn, "RU": ru, "ET": et, "EG": eg, "CD": cd, "VN": vn, "IR": ir, "TH": th})
if __name__ == "__main__":
    for cc in sys.argv[1:]:
        rows = BUILD[cc](); os.makedirs(f"{ROOT}/data/{cc.lower()}", exist_ok=True); wjl(f"{ROOT}/data/{cc.lower()}/{cc.lower()}_judges.jsonl", rows); print(cc, len(rows))
