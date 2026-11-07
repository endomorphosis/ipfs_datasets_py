"""Pass 8 (caselaw-gap lane): real court bodies replacing generic placeholders (<cc>-supreme-court/-court-of-appeal/-high-court/-lower-court)
for HK MN KZ KG TJ TM UZ + Pacific (FJ PG WS TO VU SB KI TV NR PW FM MH CK NU) and new files for MO TK AS + territories GU MP NC PF WF NF PN;
SL Special Court (historical international); IN CESTAT (body only). Structures from constitutions/judiciary acts as published on official judiciary sites;
Wikidata QIDs looked up via wbsearchentities (CC0) and kept only when the hit is described as a court/tribunal. Child rows of placeholders are re-parented via REMAP."""
import json, os, sys, time, datetime, urllib.request, urllib.parse, re
ROOT = "/workspace/world_courts"; NOW = datetime.datetime.now(datetime.UTC).isoformat()
UA = "Mozilla/5.0 (compatible; world_courts-research/0.1)"
# (suffix, name, name_local, level, parent_suffix|None, court_system, website)
S = {
"HK": ("https://www.judiciary.hk/en/court_services_facilities/index.html", [
 ("cfa","Court of Final Appeal","終審法院","supreme",None,"national","https://www.hkcfa.hk/"),
 ("hc","High Court","高等法院","appellate","cfa","national","https://www.judiciary.hk/"),
 ("hc-ca","Court of Appeal of the High Court","上訴法庭","appellate","hc","national",None),
 ("hc-cfi","Court of First Instance of the High Court","原訟法庭","trial_general","hc","national",None),
 ("dc","District Court","區域法院","trial_general","hc-ca","national",None),
 ("fc","Family Court","家事法庭","family","dc","national",None),
 ("lt","Lands Tribunal","土地審裁處","other","hc-ca","national",None),
 ("mag","Magistrates' Courts","裁判法院","trial_limited","hc-cfi","national",None),
 ("cor","Coroner's Court","死因裁判法庭","other","hc-cfi","national",None),
 ("lbt","Labour Tribunal","勞資審裁處","other","hc-cfi","national",None),
 ("sct","Small Claims Tribunal","小額錢債審裁處","trial_limited","hc-cfi","national",None),
 ("oat","Obscene Articles Tribunal","淫褻物品審裁處","other","hc-cfi","national",None),
 ("ct","Competition Tribunal","競爭事務審裁處","other","hc-ca","national",None)],
 {"supreme":"cfa","court-of-appeal":"hc-ca","high-court":"hc-cfi","lower-court":"mag"}),
"MN": ("https://www.supremecourt.mn/", [
 ("sc","Supreme Court of Mongolia","Монгол Улсын Дээд шүүх","supreme",None,"national","https://www.supremecourt.mn/"),
 ("cc","Constitutional Court of Mongolia (Tsets)","Үндсэн хуулийн цэц","supreme",None,"constitutional","https://www.conscourt.gov.mn/"),
 ("app-crim","Appellate Criminal Courts (capital city and aimags)",None,"appellate","sc","national",None),
 ("app-civ","Appellate Civil Courts (capital city and aimags)",None,"appellate","sc","national",None),
 ("app-adm","Appellate Administrative Court",None,"appellate","sc","administrative",None),
 ("fi-crim","First-instance criminal courts (district/soum)",None,"trial_general","app-crim","national",None),
 ("fi-civ","First-instance civil courts (district/soum)",None,"trial_general","app-civ","national",None),
 ("fi-adm","First-instance administrative courts",None,"administrative","app-adm","administrative",None)],
 {"supreme":"sc","court-of-appeal":"app-civ","high-court":"app-civ","lower-court":"fi-civ"}),
"KZ": ("https://www.sud.gov.kz/", [
 ("sc","Supreme Court of the Republic of Kazakhstan","Верховный Суд Республики Казахстан","supreme",None,"national","https://www.sud.gov.kz/"),
 ("cc","Constitutional Court of the Republic of Kazakhstan","Конституционный Суд Республики Казахстан","supreme",None,"constitutional","https://www.ksrk.gov.kz/"),
 ("reg","Regional and equivalent courts (oblast courts; Astana, Almaty, Shymkent city courts)","Областные и приравненные к ним суды","appellate","sc","national",None),
 ("dist","District (city) and equivalent courts","Районные (городские) и приравненные к ним суды","trial_general","reg","national",None),
 ("econ","Specialized interdistrict economic courts","Специализированные межрайонные экономические суды","trial_general","reg","national",None),
 ("adm","Specialized interdistrict administrative courts","Специализированные межрайонные административные суды","administrative","reg","administrative",None),
 ("juv","Specialized interdistrict juvenile courts","Специализированные межрайонные суды по делам несовершеннолетних","juvenile","reg","national",None),
 ("crim","Specialized interdistrict criminal courts","Специализированные межрайонные суды по уголовным делам","trial_general","reg","national",None),
 ("mil","Military courts","Военные суды","other","sc","military",None),
 ("aifc","Astana International Financial Centre Court","Суд МФЦА","other",None,"special","https://court.aifc.kz/")],
 {"supreme":"sc","court-of-appeal":"reg","high-court":"reg","lower-court":"dist"}),
"KG": ("https://sot.kg/", [
 ("sc","Supreme Court of the Kyrgyz Republic","Верховный суд Кыргызской Республики","supreme",None,"national","https://sot.kg/"),
 ("cc","Constitutional Court of the Kyrgyz Republic","Конституционный суд Кыргызской Республики","supreme",None,"constitutional","https://constsot.kg/"),
 ("reg","Regional courts and Bishkek City Court","Областные суды и Бишкекский городской суд","appellate","sc","national",None),
 ("dist","District (city) courts","Районные (городские) суды","trial_general","reg","national",None),
 ("adm","Interdistrict (administrative) courts","Межрайонные суды","administrative","reg","administrative",None),
 ("mil","Military courts","Военные суды","other","sc","military",None)],
 {"supreme":"sc","court-of-appeal":"reg","high-court":"reg","lower-court":"dist"}),
"TJ": ("https://sud.tj/", [
 ("sc","Supreme Court of the Republic of Tajikistan","Суди Олии Ҷумҳурии Тоҷикистон","supreme",None,"national","https://sud.tj/"),
 ("cc","Constitutional Court of the Republic of Tajikistan","Суди конститутсионии Ҷумҳурии Тоҷикистон","supreme",None,"constitutional","https://www.constcourt.tj/"),
 ("sec","Supreme Economic Court of the Republic of Tajikistan","Суди олии иқтисодии Ҷумҳурии Тоҷикистон","supreme",None,"economic","https://oiisud.tj/"),
 ("reg","Regional courts (GBAO, Sughd, Khatlon) and Dushanbe City Court",None,"appellate","sc","national",None),
 ("dist","City and district courts",None,"trial_general","reg","national",None),
 ("econ","Regional economic courts",None,"trial_general","sec","economic",None),
 ("mil","Military courts",None,"other","sc","military",None)],
 {"supreme":"sc","court-of-appeal":"reg","high-court":"reg","lower-court":"dist"}),
"TM": ("https://www.turkmenistan.gov.tm/", [
 ("sc","Supreme Court of Turkmenistan","Türkmenistanyň Ýokary kazyýeti","supreme",None,"national",None),
 ("arb","Arbitration Court of Turkmenistan","Türkmenistanyň Arbitraž kazyýeti","trial_general","sc","economic",None),
 ("vel","Velayat courts and Ashgabat City Court","Welaýat kazyýetleri","appellate","sc","national",None),
 ("etr","Etrap and city courts","Etrap we şäher kazyýetleri","trial_general","vel","national",None),
 ("mil","Military courts",None,"other","sc","military",None)],
 {"supreme":"sc","court-of-appeal":"vel","high-court":"vel","lower-court":"etr"}),
"UZ": ("https://sud.uz/", [
 ("sc","Supreme Court of the Republic of Uzbekistan","Oʻzbekiston Respublikasi Oliy sudi","supreme",None,"national","https://sud.uz/"),
 ("cc","Constitutional Court of the Republic of Uzbekistan","Oʻzbekiston Respublikasi Konstitutsiyaviy sudi","supreme",None,"constitutional","https://www.ksuz.uz/"),
 ("reg","Regional courts (Karakalpakstan, regions, Tashkent city)","Viloyat sudlari","appellate","sc","national",None),
 ("civ","Interdistrict/district (city) civil courts","Fuqarolik ishlari boʻyicha tumanlararo sudlar","trial_general","reg","national",None),
 ("crim","District (city) criminal courts","Jinoyat ishlari boʻyicha tuman sudlari","trial_general","reg","national",None),
 ("econ","Interdistrict economic courts","Tumanlararo iqtisodiy sudlar","trial_general","reg","economic",None),
 ("adm","District (city) administrative courts","Tuman maʼmuriy sudlari","administrative","reg","administrative",None),
 ("mil","Military Court of the Republic of Uzbekistan","Harbiy sud","other","sc","military",None)],
 {"supreme":"sc","court-of-appeal":"reg","high-court":"reg","lower-court":"civ"}),
"FJ": ("https://www.judiciary.gov.fj/", [
 ("sc","Supreme Court of Fiji",None,"supreme",None,"national","https://www.judiciary.gov.fj/"),("ca","Court of Appeal of Fiji",None,"appellate","sc","national",None),
 ("hc","High Court of Fiji",None,"trial_general","ca","national",None),("mag","Magistrates' Courts of Fiji",None,"trial_limited","hc","national",None),
 ("erc","Employment Relations Court",None,"other","ca","national",None),("ert","Employment Relations Tribunal",None,"other","erc","national",None),
 ("sct","Small Claims Tribunal",None,"trial_limited","mag","national",None)],{"supreme":"sc","court-of-appeal":"ca","high-court":"hc","lower-court":"mag"}),
"PG": ("https://www.pngjudiciary.gov.pg/", [
 ("sc","Supreme Court of Papua New Guinea",None,"supreme",None,"national","https://www.pngjudiciary.gov.pg/"),("nc","National Court of Justice",None,"trial_general","sc","national",None),
 ("dc","District Courts",None,"trial_limited","nc","national","https://www.magisterialservices.gov.pg/"),("vc","Village Courts",None,"other","dc","customary",None),
 ("llc","Local Land Courts",None,"other","dc","customary",None)],{"supreme":"sc","court-of-appeal":"sc","high-court":"nc","lower-court":"dc"}),
"WS": ("https://www.samoajudiciary.gov.ws/", [
 ("ca","Court of Appeal of Samoa",None,"supreme",None,"national","https://www.samoajudiciary.gov.ws/"),("sc","Supreme Court of Samoa",None,"trial_general","ca","national",None),
 ("dc","District Court of Samoa",None,"trial_limited","sc","national",None),("ltc","Land and Titles Court",None,"other",None,"customary",None),
 ("fc","Family Court of Samoa",None,"family","sc","national",None)],{"supreme":"ca","court-of-appeal":"ca","high-court":"sc","lower-court":"dc"}),
"TO": ("https://www.justice.gov.to/", [
 ("ca","Court of Appeal of Tonga",None,"supreme",None,"national",None),("sc","Supreme Court of Tonga",None,"trial_general","ca","national",None),
 ("lc","Land Court of Tonga",None,"other","ca","national",None),("mag","Magistrates' Court of Tonga",None,"trial_limited","sc","national",None)],{"supreme":"ca","court-of-appeal":"ca","high-court":"sc","lower-court":"mag"}),
"VU": ("https://courts.gov.vu/", [
 ("ca","Court of Appeal of Vanuatu",None,"supreme",None,"national","https://courts.gov.vu/"),("sc","Supreme Court of Vanuatu",None,"trial_general","ca","national",None),
 ("mag","Magistrates' Courts of Vanuatu",None,"trial_limited","sc","national",None),("ic","Island Courts",None,"other","sc","customary",None)],{"supreme":"ca","court-of-appeal":"ca","high-court":"sc","lower-court":"mag"}),
"SB": ("https://www.courts.gov.sb/", [
 ("ca","Court of Appeal of Solomon Islands",None,"supreme",None,"national",None),("hc","High Court of Solomon Islands",None,"trial_general","ca","national",None),
 ("mag","Magistrates' Courts",None,"trial_limited","hc","national",None),("lc","Local Courts",None,"other","mag","customary",None),
 ("clac","Customary Land Appeal Courts",None,"other","hc","customary",None)],{"supreme":"ca","court-of-appeal":"ca","high-court":"hc","lower-court":"mag"}),
"KI": ("https://www.paclii.org/ki/", [
 ("ca","Court of Appeal of Kiribati",None,"supreme",None,"national",None),("hc","High Court of Kiribati",None,"trial_general","ca","national",None),
 ("mag","Magistrates' Courts of Kiribati",None,"trial_limited","hc","national",None)],{"supreme":"ca","court-of-appeal":"ca","high-court":"hc","lower-court":"mag"}),
"TV": ("https://www.paclii.org/tv/", [
 ("ca","Court of Appeal of Tuvalu",None,"supreme",None,"national",None),("hc","High Court of Tuvalu",None,"trial_general","ca","national",None),
 ("smc","Senior Magistrate's Court",None,"trial_limited","hc","national",None),("ic","Island Courts",None,"other","smc","customary",None),("lnd","Lands Courts",None,"other","hc","customary",None)],
 {"supreme":"ca","court-of-appeal":"ca","high-court":"hc","lower-court":"smc"}),
"NR": ("https://www.paclii.org/nr/", [
 ("ca","Nauru Court of Appeal",None,"supreme",None,"national",None),("sc","Supreme Court of Nauru",None,"trial_general","ca","national",None),
 ("dc","District Court of Nauru",None,"trial_limited","sc","national",None),("fc","Family Court of Nauru",None,"family","sc","national",None)],{"supreme":"ca","court-of-appeal":"ca","high-court":"sc","lower-court":"dc"}),
"PW": ("https://www.palausupremecourt.net/", [
 ("sc-app","Supreme Court of Palau, Appellate Division",None,"supreme",None,"national","https://www.palausupremecourt.net/"),("sc-tri","Supreme Court of Palau, Trial Division",None,"trial_general","sc-app","national",None),
 ("lc","Land Court of Palau",None,"other","sc-app","national",None),("ccp","Court of Common Pleas",None,"trial_limited","sc-tri","national",None)],{"supreme":"sc-app","court-of-appeal":"sc-app","high-court":"sc-tri","lower-court":"ccp"}),
"FM": ("https://www.fsmsupremecourt.org/", [
 ("sc-app","FSM Supreme Court, Appellate Division",None,"supreme",None,"national","https://www.fsmsupremecourt.org/"),("sc-tri","FSM Supreme Court, Trial Division",None,"trial_general","sc-app","national",None),
 ("chuuk","Chuuk State Supreme Court",None,"trial_general","sc-app","state",None),("kosrae","Kosrae State Court",None,"trial_general","sc-app","state",None),
 ("pohnpei","Pohnpei Supreme Court",None,"trial_general","sc-app","state",None),("yap","Yap State Court",None,"trial_general","sc-app","state",None)],
 {"supreme":"sc-app","court-of-appeal":"sc-app","high-court":"sc-tri","lower-court":"sc-tri"}),
"MH": ("https://rmicourts.org/", [
 ("sc","Supreme Court of the Marshall Islands",None,"supreme",None,"national","https://rmicourts.org/"),("hc","High Court of the Marshall Islands",None,"trial_general","sc","national",None),
 ("trc","Traditional Rights Court",None,"other","hc","customary",None),("dc","District Court of the Marshall Islands",None,"trial_limited","hc","national",None),
 ("cc","Community Courts",None,"trial_limited","dc","national",None)],{"supreme":"sc","court-of-appeal":"sc","high-court":"hc","lower-court":"dc"}),
"CK": ("https://www.justice.gov.ck/", [
 ("ca","Court of Appeal of the Cook Islands",None,"supreme",None,"national",None),("hc","High Court of the Cook Islands",None,"trial_general","ca","national",None),
 ("lc","Land Division of the High Court (Land Court)",None,"other","hc","national",None),("jp","Justices of the Peace",None,"trial_limited","hc","national",None)],{"supreme":"ca","court-of-appeal":"ca","high-court":"hc","lower-court":"jp"}),
"NU": ("https://www.paclii.org/nu/", [
 ("ca","Court of Appeal of Niue",None,"supreme",None,"national",None),("hc","High Court of Niue",None,"trial_general","ca","national",None),
 ("lc","Land Court of Niue",None,"other","hc","national",None)],{"supreme":"ca","court-of-appeal":"ca","high-court":"hc","lower-court":"hc"}),
# new files
"MO": ("https://www.court.gov.mo/", [
 ("tui","Court of Final Appeal","終審法院","supreme",None,"national","https://www.court.gov.mo/"),("tsi","Court of Second Instance","中級法院","appellate","tui","national",None),
 ("tjb","Primary Court (Court of First Instance)","初級法院","trial_general","tsi","national",None),("ta","Administrative Court","行政法院","administrative","tsi","administrative",None)],{}),
"TK": ("https://www.tokelau.org.nz/", [
 ("hcnz","High Court of New Zealand (Tokelau jurisdiction)",None,"appellate",None,"national",None),
 ("cc-atafu","Commissioner's Court, Atafu",None,"trial_limited","hcnz","village",None),("cc-fakaofo","Commissioner's Court, Fakaofo",None,"trial_limited","hcnz","village",None),
 ("cc-nukunonu","Commissioner's Court, Nukunonu",None,"trial_limited","hcnz","village",None)],{}),
"AS": ("https://www.ascourt.org/", [
 ("hc-app","High Court of American Samoa, Appellate Division",None,"supreme",None,"territorial","https://www.ascourt.org/"),
 ("hc-tri","High Court of American Samoa, Trial Division",None,"trial_general","hc-app","territorial",None),
 ("hc-lt","High Court of American Samoa, Land and Titles Division",None,"other","hc-app","territorial",None),
 ("dc","District Court of American Samoa",None,"trial_limited","hc-tri","territorial",None),("vc","Village Courts of American Samoa",None,"trial_limited","dc","customary",None)],{}),
"GU": ("https://www.guamcourts.org/", [
 ("sc","Supreme Court of Guam",None,"supreme",None,"territorial","https://www.guamcourts.org/"),("spc","Superior Court of Guam",None,"trial_general","sc","territorial",None),
 ("dcg","District Court of Guam",None,"federal_district",None,"federal","https://www.gud.uscourts.gov/")],{}),
"MP": ("https://www.cnmilaw.org/", [
 ("sc","Commonwealth Supreme Court (CNMI)",None,"supreme",None,"territorial",None),("spc","Commonwealth Superior Court (CNMI)",None,"trial_general","sc","territorial",None),
 ("dnmi","District Court for the Northern Mariana Islands",None,"federal_district",None,"federal","https://www.nmid.uscourts.gov/")],{}),
"NC": ("https://www.cours-appel.justice.fr/noumea", [
 ("ca","Cour d'appel de Nouméa",None,"appellate",None,"national","https://www.cours-appel.justice.fr/noumea"),("tpi","Tribunal de première instance de Nouméa",None,"trial_general","ca","national",None),
 ("ta","Tribunal administratif de Nouvelle-Calédonie",None,"administrative",None,"administrative",None)],{}),
"PF": ("https://www.cours-appel.justice.fr/papeete", [
 ("ca","Cour d'appel de Papeete",None,"appellate",None,"national","https://www.cours-appel.justice.fr/papeete"),("tpi","Tribunal de première instance de Papeete",None,"trial_general","ca","national",None),
 ("ta","Tribunal administratif de la Polynésie française",None,"administrative",None,"administrative",None)],{}),
"WF": ("https://www.cours-appel.justice.fr/noumea", [
 ("tpi","Tribunal de première instance de Mata-Utu",None,"trial_general",None,"national",None),("ta","Tribunal administratif de Wallis-et-Futuna",None,"administrative",None,"administrative",None)],{}),
"NF": ("https://www.fedcourt.gov.au/", [
 ("sc","Supreme Court of Norfolk Island",None,"trial_general",None,"territorial",None),("cps","Court of Petty Sessions (Norfolk Island)",None,"trial_limited","sc","territorial",None)],{}),
"PN": ("https://www.government.pn/", [
 ("ca","Court of Appeal of the Pitcairn Islands",None,"supreme",None,"territorial",None),("sc","Supreme Court of the Pitcairn Islands",None,"trial_general","ca","territorial",None),
 ("mag","Magistrate's Court of the Pitcairn Islands",None,"trial_limited","sc","territorial",None)],{}),
}
EXTRA = {  # (cc, suffix, name, level, parent, system, website, note)
 "SL": [("scsl","Special Court for Sierra Leone","other",None,"international","https://www.rscsl.org/","historical: 2002–2013, succeeded by the Residual Special Court for Sierra Leone"),
        ("rscsl","Residual Special Court for Sierra Leone","other",None,"international","https://www.rscsl.org/","successor of the Special Court for Sierra Leone (2013–)")],
 "IN": [("cestat","Customs, Excise and Service Tax Appellate Tribunal (CESTAT), Principal Bench New Delhi","tax",None,"tribunal","https://cestat.gov.in/","formerly Customs, Excise and Gold (Control) Appellate Tribunal (CEGAT)")]}
_last = [0]
CN = {"HK":"hong kong","MN":"mongolia","KZ":"kazakhstan","KG":"kyrgyz","TJ":"tajikistan","TM":"turkmenistan","UZ":"uzbekistan","FJ":"fiji","PG":"papua new guinea","WS":"samoa","TO":"tonga","VU":"vanuatu","SB":"solomon","KI":"kiribati","TV":"tuvalu","NR":"nauru","PW":"palau","FM":"micronesia","MH":"marshall","CK":"cook islands","NU":"niue","MO":"maca","TK":"tokelau","AS":"american samoa","GU":"guam","MP":"northern mariana","NC":"cal\u00e9donie|caledonia|noum","PF":"polyn|papeete|tahiti","WF":"wallis","NF":"norfolk","PN":"pitcairn","SL":"sierra leone","IN":"india"}
def wd(name, cc=""):
    w = 1.0 - (time.time() - _last[0])
    if w > 0: time.sleep(w)
    _last[0] = time.time()
    try:
        u = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({"action": "wbsearchentities", "search": name, "language": "en", "format": "json", "limit": 3})
        j = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=30))
        for h in j.get("search", []):
            d = (h.get("description") or "").lower()
            if re.search(r"court|tribunal|judiciary", d) and re.search(CN.get(cc, "^$"), (d + " " + h.get("label", "")).lower()) and re.sub(r"\W", "", h.get("label", "").lower()) == re.sub(r"\W", "", name.lower()): return h["id"]
    except Exception: return None
def body(cc, sfx, name, local, level, parent, system, web, src, note=None):
    lc = cc.lower(); q = wd(name, cc)
    return {"court_id": f"{lc}-{sfx}", "record_type": "court_body", "name": name, "name_local": local, "level": level, "court_system": system, "country_code": cc, "subdivision": cc,
        "jurisdiction": None, "parent_court_id": f"{lc}-{parent}" if parent else None, "address": {"street": None, "city": None, "postcode": None, "region": None, "country": cc},
        "geo": {"lat": None, "lon": None}, "phone": None, "website": web, "wikidata": q, "place_ids": [], "source_url": web or src, "source_kind": "official_structure" + ("+wikidata" if q else ""),
        "site_policy": "reference:official_judiciary_structure", "retrieved_at": NOW, "license": "CC0-1.0 (compiled structure; Wikidata CC0)", "record_note": note,
        "sources": [{"source_url": src, "site_policy": "reference", "source_kind": "official_structure"}] + ([{"source_url": f"https://www.wikidata.org/wiki/{q}", "site_policy": "open_license:CC0", "source_kind": "wikidata"}] if q else []), "needs_review": True}
def apply(cc):
    lc = cc.lower(); src, spec, remap = S[cc]; p = f"{ROOT}/data/{lc}/{lc}_courthouses.jsonl"
    old = [json.loads(l) for l in open(p)] if os.path.exists(p) else []
    ph = {f"{lc}-{k}": f"{lc}-{v}" for k, v in remap.items()}
    ph.update({f"{lc}-supreme-court": f"{lc}-{remap.get('supreme', spec[0][0])}"} if remap else {})
    ph = {(f"{lc}-supreme-court" if k.endswith("-supreme") else k): v for k, v in ph.items()}
    newb = [body(cc, *x, src) for x in spec]; nids = {b["court_id"] for b in newb}
    keep = []
    for r in old:
        if r.get("record_type") == "court_body" and (r["court_id"] in ph or r["court_id"] in nids): continue
        if r.get("parent_court_id") in ph: r["parent_court_id"] = ph[r["parent_court_id"]]
        keep.append(r)
    for b in newb:
        b["replaces_placeholder_ids"] = sorted(k for k, v in ph.items() if v == b["court_id"]) or None
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        for r in newb + keep: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return [b["court_id"] for b in newb], ph
def extra(cc):
    lc = cc.lower(); p = f"{ROOT}/data/{lc}/{lc}_courthouses.jsonl"; R = [json.loads(l) for l in open(p)]
    ids = {r["court_id"] for r in R}; add = []
    for sfx, n, lvl, par, sysm, web, note in EXTRA[cc]:
        if f"{lc}-{sfx}" in ids: continue
        add.append(body(cc, sfx, n, None, lvl, par, sysm, web, web, note))
    with open(p, "w") as f:
        for r in R + add: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return [b["court_id"] for b in add]
if __name__ == "__main__":
    out = {}
    for cc in sys.argv[1:]:
        if cc in EXTRA and cc not in S: out[cc] = {"added": extra(cc)}
        else: ids, ph = apply(cc); out[cc] = {"bodies": ids, "placeholder_map": ph}
        print(cc, json.dumps(out[cc], ensure_ascii=False), flush=True)
    json.dump(out, open(f"/tmp/pass8_{'_'.join(sys.argv[1:])[:40]}.json", "w"), ensure_ascii=False, indent=1)
