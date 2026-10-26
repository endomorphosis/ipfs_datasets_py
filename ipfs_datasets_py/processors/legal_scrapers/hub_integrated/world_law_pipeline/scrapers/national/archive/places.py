"""ISO 3166-2 lookup tables for archive targets with subnational (adm1) law."""
import re
import unicodedata


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("đ", "d")
    return re.sub(r"[^a-z0-9]", "", s)


# Austria: RIS Landesrecht Abfrage / Dokumentnummer prefixes
AT_ABFRAGE = {"LrBgld": ("AT-1", "Burgenland"), "LrK": ("AT-2", "Kärnten"), "LrNO": ("AT-3", "Niederösterreich"),
              "LrOO": ("AT-4", "Oberösterreich"), "LrSbg": ("AT-5", "Salzburg"), "LrStmk": ("AT-6", "Steiermark"),
              "LrT": ("AT-7", "Tirol"), "LrVbg": ("AT-8", "Vorarlberg"), "LrW": ("AT-9", "Wien")}
AT_DOCPREFIX = {"LBG": "LrBgld", "LKT": "LrK", "LNO": "LrNO", "LOO": "LrOO", "LSB": "LrSbg", "LST": "LrStmk",
                "LTI": "LrT", "LVB": "LrVbg", "LWI": "LrW"}

# Kenya: ISO 3166-2:KE 01..47 are alphabetical; Kenya Law AKN county codes use the
# constitutional First Schedule number (ke-001..ke-047) or a 3-letter code.
KE_ALPHA = ["Baringo", "Bomet", "Bungoma", "Busia", "Elgeyo-Marakwet", "Embu", "Garissa", "Homa Bay", "Isiolo",
            "Kajiado", "Kakamega", "Kericho", "Kiambu", "Kilifi", "Kirinyaga", "Kisii", "Kisumu", "Kitui", "Kwale",
            "Laikipia", "Lamu", "Machakos", "Makueni", "Mandera", "Marsabit", "Meru", "Migori", "Mombasa",
            "Murang'a", "Nairobi", "Nakuru", "Nandi", "Narok", "Nyamira", "Nyandarua", "Nyeri", "Samburu", "Siaya",
            "Taita-Taveta", "Tana River", "Tharaka-Nithi", "Trans Nzoia", "Turkana", "Uasin Gishu", "Vihiga",
            "Wajir", "West Pokot"]
KE_CONST = ["Mombasa", "Kwale", "Kilifi", "Tana River", "Lamu", "Taita-Taveta", "Garissa", "Wajir", "Mandera",
            "Marsabit", "Isiolo", "Meru", "Tharaka-Nithi", "Embu", "Kitui", "Machakos", "Makueni", "Nyandarua",
            "Nyeri", "Kirinyaga", "Murang'a", "Kiambu", "Turkana", "West Pokot", "Samburu", "Trans Nzoia",
            "Uasin Gishu", "Elgeyo-Marakwet", "Nandi", "Baringo", "Laikipia", "Nakuru", "Narok", "Kajiado",
            "Kericho", "Bomet", "Kakamega", "Vihiga", "Bungoma", "Busia", "Siaya", "Kisumu", "Homa Bay", "Migori",
            "Kisii", "Nyamira", "Nairobi"]
KE_BY_NAME = {norm(n): (f"KE-{i + 1:02d}", n) for i, n in enumerate(KE_ALPHA)}
KE_BY_NAME.update({"nairobicity": KE_BY_NAME["nairobi"], "elgeyomarakwet": KE_BY_NAME["elgeyomarakwet"],
                   "taitataveta": KE_BY_NAME["taitataveta"], "muranga": KE_BY_NAME["muranga"]})


def ke_county(code: str, text: str = ""):
    c = (code or "").lower()
    m = re.match(r"^0*(\d{1,2})$", c)
    if m and 1 <= int(m.group(1)) <= 47:
        return KE_BY_NAME[norm(KE_CONST[int(m.group(1)) - 1])]
    for k, v in KE_BY_NAME.items():
        if c and (k.startswith(c) or c == k[:3]):
            pass
    m = re.search(r"([A-Z][A-Za-z' -]{2,25}?)\s+County", text or "")
    if m and norm(m.group(1)) in KE_BY_NAME:
        return KE_BY_NAME[norm(m.group(1))]
    # 3-letter prefixes unique among county names
    cands = [v for k, v in KE_BY_NAME.items() if c and k.startswith(c)]
    return cands[0] if len(cands) == 1 else None


# Vietnam (pre-2025 63 units; ISO 3166-2:VN)
VN = {"hanoi": ("VN-HN", "Hà Nội"), "hochiminh": ("VN-SG", "TP Hồ Chí Minh"), "tphcm": ("VN-SG", "TP Hồ Chí Minh"),
      "haiphong": ("VN-HP", "Hải Phòng"), "danang": ("VN-DN", "Đà Nẵng"), "cantho": ("VN-CT", "Cần Thơ"),
      "angiang": ("VN-44", "An Giang"), "bariavungtau": ("VN-43", "Bà Rịa–Vũng Tàu"), "vungtau": ("VN-43", "Bà Rịa–Vũng Tàu"),
      "bacgiang": ("VN-54", "Bắc Giang"), "backan": ("VN-53", "Bắc Kạn"), "baclieu": ("VN-55", "Bạc Liêu"),
      "bacninh": ("VN-56", "Bắc Ninh"), "bentre": ("VN-50", "Bến Tre"), "binhdinh": ("VN-31", "Bình Định"),
      "binhduong": ("VN-57", "Bình Dương"), "binhphuoc": ("VN-58", "Bình Phước"), "binhthuan": ("VN-40", "Bình Thuận"),
      "camau": ("VN-59", "Cà Mau"), "caobang": ("VN-04", "Cao Bằng"), "daklak": ("VN-33", "Đắk Lắk"),
      "daclac": ("VN-33", "Đắk Lắk"), "daknong": ("VN-72", "Đắk Nông"), "dienbien": ("VN-71", "Điện Biên"),
      "dongnai": ("VN-39", "Đồng Nai"), "dongthap": ("VN-45", "Đồng Tháp"), "gialai": ("VN-30", "Gia Lai"),
      "hagiang": ("VN-03", "Hà Giang"), "hanam": ("VN-63", "Hà Nam"), "hatinh": ("VN-23", "Hà Tĩnh"),
      "haiduong": ("VN-61", "Hải Dương"), "haugiang": ("VN-73", "Hậu Giang"), "hoabinh": ("VN-14", "Hòa Bình"),
      "hungyen": ("VN-66", "Hưng Yên"), "khanhhoa": ("VN-34", "Khánh Hòa"), "kiengiang": ("VN-47", "Kiên Giang"),
      "kontum": ("VN-28", "Kon Tum"), "laichau": ("VN-01", "Lai Châu"), "lamdong": ("VN-35", "Lâm Đồng"),
      "langson": ("VN-09", "Lạng Sơn"), "laocai": ("VN-02", "Lào Cai"), "longan": ("VN-41", "Long An"),
      "namdinh": ("VN-67", "Nam Định"), "nghean": ("VN-22", "Nghệ An"), "ninhbinh": ("VN-18", "Ninh Bình"),
      "ninhthuan": ("VN-36", "Ninh Thuận"), "phutho": ("VN-68", "Phú Thọ"), "phuyen": ("VN-32", "Phú Yên"),
      "quangbinh": ("VN-24", "Quảng Bình"), "quangnam": ("VN-27", "Quảng Nam"), "quangngai": ("VN-29", "Quảng Ngãi"),
      "quangninh": ("VN-13", "Quảng Ninh"), "quangtri": ("VN-25", "Quảng Trị"), "soctrang": ("VN-52", "Sóc Trăng"),
      "sonla": ("VN-05", "Sơn La"), "tayninh": ("VN-37", "Tây Ninh"), "thaibinh": ("VN-20", "Thái Bình"),
      "thainguyen": ("VN-69", "Thái Nguyên"), "thanhhoa": ("VN-21", "Thanh Hóa"), "thuathienhue": ("VN-26", "Thừa Thiên–Huế"),
      "hue": ("VN-26", "Thừa Thiên–Huế"), "tiengiang": ("VN-46", "Tiền Giang"), "travinh": ("VN-51", "Trà Vinh"),
      "tuyenquang": ("VN-07", "Tuyên Quang"), "vinhlong": ("VN-49", "Vĩnh Long"), "vinhphuc": ("VN-70", "Vĩnh Phúc"),
      "yenbai": ("VN-06", "Yên Bái")}

# Indonesia provinces (ISO 3166-2:ID)
ID_PROV = {"aceh": "AC", "sumaterautara": "SU", "sumut": "SU", "sumaterabarat": "SB", "sumbar": "SB", "riau": "RI",
           "kepulauanriau": "KR", "kepri": "KR", "jambi": "JA", "sumateraselatan": "SS", "sumsel": "SS",
           "kepulauanbangkabelitung": "BB", "bangkabelitung": "BB", "babel": "BB", "bengkulu": "BE", "lampung": "LA",
           "dkijakarta": "JK", "jakarta": "JK", "jawabarat": "JB", "jabar": "JB", "banten": "BT", "jawatengah": "JT",
           "jateng": "JT", "diyogyakarta": "YO", "daerahistimewayogyakarta": "YO", "diy": "YO", "yogyakarta": "YO", "jawatimur": "JI",
           "jatim": "JI", "bali": "BA", "nusatenggarabarat": "NB", "ntb": "NB", "nusatenggaratimur": "NT", "ntt": "NT",
           "kalimantanbarat": "KB", "kalbar": "KB", "kalimantantengah": "KT", "kalteng": "KT", "kalimantanselatan": "KS",
           "kalsel": "KS", "kalimantantimur": "KI", "kaltim": "KI", "kalimantanutara": "KU", "kaltara": "KU",
           "sulawesiutara": "SA", "sulut": "SA", "sulawesitengah": "ST", "sulteng": "ST", "sulawesiselatan": "SN",
           "sulsel": "SN", "sulawesitenggara": "SG", "sultra": "SG", "gorontalo": "GO", "sulawesibarat": "SR",
           "sulbar": "SR", "maluku": "MA", "malukuutara": "MU", "papua": "PA", "papuabarat": "PB",
           "papuapegunungan": "PE", "papuaselatan": "PS", "papuatengah": "PT", "papuabaratdaya": "PD"}


def id_province_from_slug(slug: str):
    """'perda-prov-jawa-barat-no-1-tahun-2020' -> ('ID-JB', 'jawabarat'); longest match wins."""
    m = re.search(r"(?:perda|pergub|kepgub|pergub-prov|perda-prov)[-_](?:prov(?:insi)?[-_])?(.+?)[-_](?:no|nomor)[-_]", slug)
    if not m:
        return None
    key = norm(m.group(1))
    best = None
    for k, v in ID_PROV.items():
        if key == k or key.startswith(k):
            if best is None or len(k) > len(best[0]):
                best = (k, v)
    return (f"ID-{best[1]}", m.group(1).replace("-", " ").title()) if best else None


# India (ISO 3166-2:IN, 2023 codes)
IN_STATES = {"andhrapradesh": "AP", "arunachalpradesh": "AR", "assam": "AS", "bihar": "BR", "chhattisgarh": "CG",
             "goa": "GA", "gujarat": "GJ", "haryana": "HR", "himachalpradesh": "HP", "jharkhand": "JH",
             "karnataka": "KA", "kerala": "KL", "madhyapradesh": "MP", "maharashtra": "MH", "manipur": "MN",
             "meghalaya": "ML", "mizoram": "MZ", "nagaland": "NL", "odisha": "OD", "orissa": "OD", "punjab": "PB",
             "rajasthan": "RJ", "sikkim": "SK", "tamilnadu": "TN", "telangana": "TS", "tripura": "TR",
             "uttarpradesh": "UP", "uttarakhand": "UK", "uttaranchal": "UK", "westbengal": "WB", "delhi": "DL",
             "nctofdelhi": "DL", "nationalcapitalterritoryofdelhi": "DL", "jammuandkashmir": "JK", "jammukashmir": "JK",
             "ladakh": "LA", "puducherry": "PY", "pondicherry": "PY", "chandigarh": "CH",
             "andamanandnicobarislands": "AN", "lakshadweep": "LD",
             "dadraandnagarhavelianddamananddiu": "DH", "dadraandnagarhaveli": "DH", "damananddiu": "DH"}


def in_state(name: str):
    k = norm(name)
    return (f"IN-{IN_STATES[k]}", name.strip()) if k in IN_STATES else None


# Russia: ISO 3166-2:RU by genitive stem as it appears in the header of regional acts.
# Order matters (more specific first). Crimea/Sevastopol deliberately not mapped (skipped).
RU_STEMS = [("ямало-ненецк", "YAN"), ("ханты-мансийск", "KHM"), ("ненецкого", "NEN"), ("чукотск", "CHU"),
    ("еврейской автономн", "YEV"), ("московской области", "MOS"), ("города москвы", "MOW"), ("москвы", "MOW"),
    ("санкт-петербург", "SPE"), ("ленинградск", "LEN"), ("республики алтай", "AL"), ("алтайского края", "ALT"),
    ("амурск", "AMU"), ("архангельск", "ARK"), ("астраханск", "AST"), ("белгородск", "BEL"), ("брянск", "BRY"),
    ("владимирск", "VLA"), ("волгоградск", "VGG"), ("вологодск", "VLG"), ("воронежск", "VOR"), ("ивановск", "IVA"),
    ("иркутск", "IRK"), ("калининградск", "KGD"), ("калужск", "KLU"), ("кемеровск", "KEM"), ("кузбасс", "KEM"),
    ("кировск", "KIR"), ("костромск", "KOS"), ("курганск", "KGN"), ("курской", "KRS"), ("липецк", "LIP"),
    ("магаданск", "MAG"), ("мурманск", "MUR"), ("нижегородск", "NIZ"), ("новгородск", "NGR"), ("новосибирск", "NVS"),
    ("томск", "TOM"), ("омской", "OMS"), ("оренбургск", "ORE"), ("орловск", "ORL"), ("пензенск", "PNZ"),
    ("псковск", "PSK"), ("ростовск", "ROS"), ("рязанск", "RYA"), ("самарск", "SAM"), ("саратовск", "SAR"),
    ("сахалинск", "SAK"), ("свердловск", "SVE"), ("смоленск", "SMO"), ("тамбовск", "TAM"), ("тверск", "TVE"),
    ("тульск", "TUL"), ("тюменск", "TYU"), ("ульяновск", "ULY"), ("челябинск", "CHE"), ("ярославск", "YAR"),
    ("забайкальск", "ZAB"), ("камчатск", "KAM"), ("краснодарск", "KDA"), ("красноярск", "KYA"), ("пермск", "PER"),
    ("приморск", "PRI"), ("ставропольск", "STA"), ("хабаровск", "KHA"), ("адыге", "AD"), ("башкортостан", "BA"),
    ("бурят", "BU"), ("дагестан", "DA"), ("ингушети", "IN"), ("кабардино", "KB"), ("калмыки", "KL"),
    ("карачаево", "KC"), ("карели", "KR"), ("республики коми", "KO"), ("марий эл", "ME"), ("мордови", "MO"),
    ("саха (якутия)", "SA"), ("якути", "SA"), ("северная осетия", "SE"), ("татарстан", "TA"), ("тыва", "TY"),
    ("удмурт", "UD"), ("хакаси", "KK"), ("чеченск", "CE"), ("чуваш", "CU")]
RU_FED = re.compile(r"федеральн|российской\s+федерации|президент|правительств[а-я]*\s+российск|рсфср|ссср|кодекс", re.I)
RU_REGIONAL_HINT = re.compile(r"област|края|республик|автономн|города\s+москвы|санкт-петербург|крым|севастопол", re.I)


def ru_place(title: str, text: str):
    head = " ".join((title + "\n" + text[:500]).lower().split())
    hdr = head[:260]
    if RU_REGIONAL_HINT.search(hdr) and not re.search(r"^.{0,40}(федеральный закон|указ президента|постановление правительства российской)", hdr):
        if re.search(r"крым|севастопол", hdr):
            return "skip"
        for stem, code in RU_STEMS:
            if stem in hdr:
                return ("RU-" + code, stem)
        return "skip"
    if RU_FED.search(head[:600]):
        return "national"
    return "skip"


# ---------------------------------------------------------------- Kazakhstan (ISO 3166-2:KZ, 2022 numeric codes)
KZ_OBL = [  # (regex on Russian/Kazakh issuer phrase, code, English name)
    (r"абайск|абай облыс", "KZ-10", "Abai"),
    (r"акмолинск|ақмола облыс", "KZ-11", "Akmola"),
    (r"актюбинск|ақтөбе облыс", "KZ-15", "Aktobe"),
    (r"алматинск|алматы облыс", "KZ-19", "Almaty Region"),
    (r"атырауск|атырау облыс", "KZ-23", "Atyrau"),
    (r"западно-казахстанск|батыс қазақстан", "KZ-27", "West Kazakhstan"),
    (r"жамбылск|жамбыл облыс", "KZ-31", "Jambyl"),
    (r"жетысуск|жетісу облыс", "KZ-33", "Jetisu"),
    (r"карагандинск|қарағанды облыс", "KZ-35", "Karaganda"),
    (r"костанайск|қостанай облыс", "KZ-39", "Kostanay"),
    (r"кызылординск|қызылорда облыс", "KZ-43", "Kyzylorda"),
    (r"мангистауск|мангыстауск|маңғыстау облыс", "KZ-47", "Mangystau"),
    (r"павлодарск|павлодар облыс", "KZ-55", "Pavlodar"),
    (r"северо-казахстанск|солтүстік қазақстан", "KZ-59", "North Kazakhstan"),
    (r"туркестанск|южно-казахстанск|түркістан облыс|оңтүстік қазақстан", "KZ-61", "Turkistan"),
    (r"улытауск|ұлытау облыс", "KZ-62", "Ulytau"),
    (r"восточно-казахстанск|шығыс қазақстан", "KZ-63", "East Kazakhstan"),
]
KZ_CITY = [(r"город\w*\s+(астан|нур-султан)|астана қала|нұр-сұлтан қала", "KZ-71", "Astana"),
           (r"город\w*\s+алматы|алматы қала", "KZ-75", "Almaty"),
           (r"город\w*\s+шымкент|шымкент қала", "KZ-79", "Shymkent")]
KZ_ISSUER = re.compile(
    r"(?:решени\w+|постановлени\w+|распоряжени\w+|приказ\w*)\s+(?:\w+\s+){0,3}?(маслихат\w*|акимат\w*|аким\w*)"
    r"\s+([^\n]{3,160}?)(?:\s+от\s+\d|\s+№|\n|$)", re.I)


def kz_place(title: str, text: str):
    """'national' | ('KZ-xx', name) for oblast / city-of-republican-significance acts | 'municipal' | None."""
    head = (title or "") + "\n" + (text or "")[:400]
    m = KZ_ISSUER.search(head)
    if not m:
        return "national"
    phrase = m.group(2).lower()
    for rx, code, name in KZ_CITY:
        if re.search(rx, m.group(0).lower()):
            # district of a big city (e.g. 'Алмалинского района города Алматы') -> municipal
            return "municipal" if re.search(r"район", phrase) else (code, name)
    if re.search(r"район|город|сельск|поселк|аудан|қала", phrase):
        return "municipal"          # district / town / rural acts -> municipal lanes
    for rx, code, name in KZ_OBL:
        if re.search(rx, phrase):
            return (code, name)
    return None


# ---------------------------------------------------------------- China provinces (ISO 3166-2:CN)
CN_PROV = [("黑龙江", "CN-HL", "Heilongjiang"), ("内蒙古", "CN-NM", "Inner Mongolia"), ("新疆", "CN-XJ", "Xinjiang"),
           ("西藏", "CN-XZ", "Tibet"), ("广西", "CN-GX", "Guangxi"), ("宁夏", "CN-NX", "Ningxia"),
           ("北京", "CN-BJ", "Beijing"), ("天津", "CN-TJ", "Tianjin"), ("上海", "CN-SH", "Shanghai"), ("重庆", "CN-CQ", "Chongqing"),
           ("河北", "CN-HE", "Hebei"), ("山西", "CN-SX", "Shanxi"), ("辽宁", "CN-LN", "Liaoning"), ("吉林", "CN-JL", "Jilin"),
           ("江苏", "CN-JS", "Jiangsu"), ("浙江", "CN-ZJ", "Zhejiang"), ("安徽", "CN-AH", "Anhui"), ("福建", "CN-FJ", "Fujian"),
           ("江西", "CN-JX", "Jiangxi"), ("山东", "CN-SD", "Shandong"), ("河南", "CN-HA", "Henan"), ("湖北", "CN-HB", "Hubei"),
           ("湖南", "CN-HN", "Hunan"), ("广东", "CN-GD", "Guangdong"), ("海南", "CN-HI", "Hainan"), ("四川", "CN-SC", "Sichuan"),
           ("贵州", "CN-GZ", "Guizhou"), ("云南", "CN-YN", "Yunnan"), ("陕西", "CN-SN", "Shaanxi"), ("甘肃", "CN-GS", "Gansu"),
           ("青海", "CN-QH", "Qinghai")]


def cn_province_level(title: str):
    """Province-level issuer if the title starts with a province / autonomous region / municipality name
    (e.g. 广东省…, 新疆维吾尔自治区…, 北京市…). Returns (code, name) | 'municipal' | None."""
    t = (title or "").strip()
    for zh, code, name in CN_PROV:
        if t.startswith(zh):
            rest = t[len(zh):]
            if re.match(r"(省|市|(?:\w{0,6})自治区)", rest):
                return (code, name)
    if re.match(r"^\S{1,12}?(市|自治州|州|县|盟|地区|经济特区)", t):
        return "municipal"
    return None
