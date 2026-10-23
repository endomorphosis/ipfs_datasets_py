"""Archive targets for the national lane (blocked/unreachable official sources).

Each spec: cc, platform, language, queries [(url, matchType, wayback_filters)], include (regex on URL,
group 1 = stable key), exclude, place(url, key, text, title) -> (place_id, place_name, iso_3166_2, admin_level)
or None (skip), doc_type, consolidated, hf_key (regex applied to HF source_urls for dedupe), selectors.
"""
import re
from places import (AT_ABFRAGE, AT_DOCPREFIX, VN, ke_county, id_province_from_slug, in_state, norm, ru_place as _ru,
                    kz_place)

NAT = lambda cc: (lambda url, key, text, title: (f"iso:{cc}", None, None, "country"))  # noqa: E731


def _adm1(code, name):
    return (f"iso:{code}", name, code, "adm1")


PE_NORM = {"L": "Ley", "LEY": "Ley", "DS": "Decreto Supremo", "DL": "Decreto Legislativo", "DLEG": "Decreto Legislativo",
           "DU": "Decreto de Urgencia", "RM": "Resolución Ministerial", "RS": "Resolución Suprema",
           "RJ": "Resolución Jefatural", "RD": "Resolución Directoral", "RA": "Resolución Administrativa",
           "RL": "Resolución Legislativa", "OM": "Ordenanza Municipal", "OR": "Ordenanza Regional"}


def pe_spij_title(key):
    """'graficos/peru/2010/abril/20/ds-003-2010-mimdes.pdf' -> 'Decreto Supremo N° 003-2010-MIMDES (gráfico/anexo SPIJ)'."""
    from urllib.parse import unquote
    stem = unquote(key.rsplit("/", 1)[-1].rsplit(".", 1)[0]).upper()
    m = re.match(r"([A-Z]+)[-_ ]+(.+)$", stem)
    if m and m.group(1) in PE_NORM:
        return f"{PE_NORM[m.group(1)]} N° {m.group(2).replace('_', ' ')} (archivo gráfico SPIJ)"
    return f"{stem.replace('_', ' ')} (archivo gráfico SPIJ)"


def kz_spec_place(url, key, text, title):
    r = kz_place(title, text)
    if r == "national":
        return ("iso:KZ", "Қазақстан", None, "country")
    if isinstance(r, tuple):
        return _adm1(r[0], r[1])
    return None  # district / town acts -> municipal lanes


def at_place(url, key, text, title):
    m = re.search(r"Abfrage=(Lr\w+)", url)
    ab = m.group(1) if m else AT_DOCPREFIX.get(key[:3])
    if ab in AT_ABFRAGE:
        return _adm1(*AT_ABFRAGE[ab])
    if key.startswith("NOR") or "Bundesnormen" in url:
        return ("iso:AT", "Österreich", None, "country")
    return None


def vn_place(url, key, text, title):
    m = re.search(r"vbpl\.vn(?::\d+)?/([^/]+)/", url, re.I)
    unit = (m.group(1) if m else "").lower()
    if unit in ("tw", "trunguong", "botuphap"):
        return ("iso:VN", "Việt Nam", None, "country")
    if unit in VN:
        return _adm1(*VN[unit])
    return ("iso:VN", "Việt Nam", None, "country")  # vbpl.vn hosts only central bodies + provinces


def ru_ips_place(url, key, text, title):
    r = _ru(title or "", text)
    if r == "national":
        return ("iso:RU", "Россия", None, "country")
    if isinstance(r, tuple):
        return _adm1(r[0], r[1])
    return None


def ke_place(url, key, text, title):
    m = re.search(r"/akn/ke-([a-z0-9]+)/", url, re.I)
    if not m:
        return None
    r = ke_county(m.group(1), text[:3000])
    return _adm1(*r) if r else None


def bpk_regional_place(url, key, text, title):
    slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
    r = id_province_from_slug(slug)
    return _adm1(*r) if r else None


def bpk_national_place(url, key, text, title):
    slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
    if re.match(r"(perda|perbup|perwali|pergub|kepgub|kepbup|kepwal|perdes|qanun)", slug):
        return None  # regional -> handled by ID_bpk_regional (province) or skipped (kab/kota need wd:)
    return ("iso:ID", "Indonesia", None, "country")


def in_place(url, key, text, title):
    for pat in (r"State\s*Acts?\s*[»>:/|-]+\s*([A-Z][A-Za-z &]+?)(?:\s*[»>|\n]|$)",
                r"\bState\s*:\s*([A-Z][A-Za-z &]+?)\s*(?:\n|$)",
                r"Ministry\s*:?\s*\n?\s*([A-Z][A-Za-z &]+?)\s*(?:\n|$)"):
        for m in re.finditer(pat, text[:6000]):
            r = in_state(m.group(1))
            if r:
                return _adm1(*r)
    if re.search(r"Ministry\s*:?\s*\n\s*Ministry of ", text[:20000]):
        return ("iso:IN", "India", None, "country")  # central act (beyond HF's 849 if not de-duplicated)
    return None


SPECS = {
    "MX_leyesbiblio": dict(cc="MX", platform="mx_diputados_leyesbiblio", language="es", doc_type="statute", consolidated=True,
        queries=[("diputados.gob.mx/LeyesBiblio/", "prefix", ["mimetype:application/pdf"])],
        include=r"(?i)diputados\.gob\.mx(?::\d+)?/LeyesBiblio/((?:pdf|regley|abro/[\w-]+|pdf_mov|regla|ley_ref)/[^/?#]+\.pdf)$",
        hf_key=r"(?i)/LeyesBiblio/(.+\.pdf)$", place=NAT("MX")),
    "MX_dof": dict(cc="MX", platform="mx_dof", language="es", doc_type="gazette_act", consolidated=False,
        queries=[("dof.gob.mx/nota_detalle.php", "prefix", ["mimetype:text/html"])],
        include=r"(?i)dof\.gob\.mx(?::\d+)?/nota_detalle\.php\?codigo=(\d{5,8})", place=NAT("MX"),
        selectors=["#DivDetalleNota", "div.Contenido", "td.txt_azul"], min_chars=300),
    "EG_parliament": dict(cc="EG", platform="eg_parliament", language="ar", doc_type="statute", consolidated=False,
        queries=[("parliament.gov.eg", "domain", ["mimetype:application/pdf"]),
                 ("parliament.gov.eg/EPA/ar/itemX.jsp", "prefix", None)],
        include=r"(?i)parliament\.gov\.eg(?::\d+)?/(.+\.pdf|EPA/ar/itemX\.jsp\?.*)$", place=NAT("EG"), min_chars=500),
    "EG_cc": dict(cc="EG", platform="eg_court_of_cassation", language="ar", doc_type="decision", consolidated=False,
        queries=[("cc.gov.eg", "domain", None)],
        include=r"(?i)cc\.gov\.eg(?::\d+)?/((?:judgment_single|civil_judgment|criminal_judgment|Books)[^#]*)$",
        place=NAT("EG"), min_chars=500),
    "RU_ips": dict(cc="RU", platform="ru_pravo_ips", language="ru", doc_type="statute", consolidated=True,
        queries=[("pravo.gov.ru/proxy/ips/", "prefix", ["mimetype:text/html", "original:.*(docbody|doc_itself).*"])],
        include=r"(?i)pravo\.gov\.ru(?::\d+)?/proxy/ips/\?(?:docbody|doc_itself)=.*?\bnd=(\d{6,12})",
        hf_key=r"\bnd=(\d+)", place=ru_ips_place, min_chars=300),
    "RU_publication": dict(cc="RU", platform="ru_publication_pravo", language="ru", doc_type="gazette_act", consolidated=False,
        queries=[("publication.pravo.gov.ru/Document/View/", "prefix", None),
                 ("publication.pravo.gov.ru/document/", "prefix", None)],
        include=r"(?i)publication\.pravo\.gov\.ru(?::\d+)?/(?:Document/View|document)/(\d{16})", place=NAT("RU"),
        follow_pdf=r"(?i)/(?:File/GetFile|file/pdf)[^\"' ]*", min_chars=200),
    "BD": dict(cc="BD", platform="bd_bdlaws", language="en", doc_type="statute", consolidated=True,
        queries=[("bdlaws.minlaw.gov.bd/act-", "prefix", ["mimetype:text/html", "original:.*/act-(details-)?[0-9]+\\.html.*"])],
        include=r"(?i)bdlaws\.minlaw\.gov\.bd(?::\d+)?/act-(?:details-)?(\d+)\.html", hf_key=r"act-details-(\d+)",
        place=NAT("BD"), selectors=["div.lineremoves", "div.act-chapter-group", "section.bg-act-section", "div.boxed-layout"], min_chars=300),
    "AT": dict(cc="AT", platform="at_ris", language="de", doc_type="statute", consolidated=True,
        queries=[("ris.bka.gv.at/Dokument.wxe", "prefix", ["mimetype:text/html", "original:.*Abfrage=(Lr|Bundesnormen).*"]),
                 ("ris.bka.gv.at/GeltendeFassung.wxe", "prefix", ["mimetype:text/html"])],
        include=r"(?i)ris\.bka\.gv\.at(?::\d+)?/(?:Dokument\.wxe\?Abfrage=(?:Lr\w+|Bundesnormen)&.*?Dokumentnummer=([A-Z]{3}\d{5,12})|GeltendeFassung\.wxe\?Abfrage=(Lr\w+&Gesetzesnummer=\d+))",
        hf_key=r"(NOR\d+)", place=at_place, selectors=["div.documentContent", "#content"], min_chars=80),
    "IR": dict(cc="IR", platform="ir_majlis_rc", language="fa", doc_type="statute", consolidated=False,
        queries=[("rc.majlis.ir/fa/law/show/", "prefix", None), ("rc.majlis.ir/fa/law/print_version/", "prefix", None),
                 ("qavanin.ir/Law/TreeText/", "prefix", None)],
        include=r"(?i)(?:rc\.majlis\.ir(?::\d+)?/fa/law/(?:show|print_version)/(\d+)|qavanin\.ir(?::\d+)?/Law/TreeText/\D*?(\d+))",
        hf_key=r"(?:law/show/|TreeText/\D*?)(\d+)", place=NAT("IR"), min_chars=300),
    "TH": dict(cc="TH", platform="th_ratchakitcha_krisdika", language="th", doc_type="gazette_act", consolidated=False,
        queries=[("ratchakitcha.soc.go.th/DATA/PDF/", "prefix", ["mimetype:application/pdf"]),
                 ("krisdika.go.th", "domain", ["mimetype:application/pdf"])],
        include=r"(?i)((?:ratchakitcha\.soc\.go\.th(?::\d+)?/DATA/PDF/|krisdika\.go\.th(?::\d+)?/(?:data/law|librarian|data/outsitedata)).+\.pdf)$",
        hf_key=r"(?i)(ratchakitcha\.soc\.go\.th/.+\.pdf)$", place=NAT("TH"), min_chars=200),
    "ID_national": dict(cc="ID", platform="id_peraturan_jdih", language="id", doc_type="regulation", consolidated=False,
        queries=[("peraturan.go.id/id/", "prefix", None), ("peraturan.go.id/common/dokumen/", "prefix", None),
                 ("jdih.setneg.go.id/viewpdfperaturan/", "prefix", None), ("jdih.setneg.go.id/Produk/", "prefix", None),
                 ("peraturan.bpk.go.id/Details/", "prefix", ["mimetype:text/html"])],
        include=r"(?i)(?:peraturan\.go\.id(?::\d+)?/(?:id/([\w-]+)|common/dokumen/(.+\.pdf))$|jdih\.setneg\.go\.id(?::\d+)?/(?:viewpdfperaturan/(.+\.pdf)|Produk/(.+))$|peraturan\.bpk\.go\.id(?::\d+)?/Details/(\d+)/[\w-]+$)",
        exclude=r"(?i)/Details/\d+/(perda|perbup|perwali|pergub|kepgub|kepbup|kepwal|perdes|qanun|perkab|perkot)[\w-]*$",
        hf_key=r"Details/(\d+)", place=bpk_national_place, follow_pdf=r"(?i)/(?:Download|Read)/\d+/[^\"' ]+\.pdf", min_chars=300),
    "ID_bpk_regional": dict(cc="ID", platform="id_bpk_regional", language="id", doc_type="regulation", consolidated=False,
        queries=[("peraturan.bpk.go.id/Details/", "prefix", ["mimetype:text/html", "original:.*/(perda|pergub|kepgub)-.*"])],
        include=r"(?i)peraturan\.bpk\.go\.id(?::\d+)?/Details/(\d+)/(?:perda|pergub|kepgub)-prov[\w-]+$",
        hf_key=r"Details/(\d+)", place=bpk_regional_place, follow_pdf=r"(?i)/(?:Download|Read)/\d+/[^\"' ]+\.pdf", min_chars=300),
    "PH": dict(cc="PH", platform="ph_official_gazette", language="en", doc_type="statute", consolidated=False,
        queries=[("officialgazette.gov.ph/", "prefix", ["mimetype:text/html",
                  "original:.*/(19|20)\\d\\d/\\d\\d/\\d\\d/(republic-act|executive-order|proclamation|administrative-order|memorandum-circular|presidential-decree|batas-pambansa|commonwealth-act|act-no|general-order|letter-of-instruction|presidential-proclamation).*"])],
        include=r"(?i)officialgazette\.gov\.ph(?::\d+)?/(?:19|20)\d\d/\d\d/\d\d/((?:republic-act|executive-order|proclamation|administrative-order|memorandum-circular|presidential-decree|batas-pambansa|commonwealth-act|act-no|general-order|letter-of-instruction|presidential-proclamation)[\w-]*)/?$",
        hf_key=r"(republic-act-no-\d+)", place=NAT("PH"), title_selectors=["h1.entry-title", "h2.entry-title", ".entry-title"], selectors=["div.entry-content", "article", "#content"], min_chars=300),
    "IN_state": dict(cc="IN", platform="in_indiacode_state", language="en", doc_type="statute", consolidated=True,
        queries=[("indiacode.nic.in/handle/123456789/", "prefix", ["mimetype:text/html"])],
        include=r"(?i)indiacode\.nic\.in(?::\d+)?/handle/123456789/(\d+)(?:\?view_type=search|/?$|\?locale=en$)",
        hf_key=r"handle/123456789/(\d+)", place=in_place, always_follow_pdf=True, follow_pdf=r"(?i)/bitstream/123456789/\d+/[^\"' ]+\.pdf",
        selectors=["#content", "div.container"], min_chars=300),
    "KE_county": dict(cc="KE", platform="ke_kenyalaw_county", language="en", doc_type="statute", consolidated=True,
        queries=[("new.kenyalaw.org/akn/ke-", "prefix", None), ("kenyalaw.org/akn/ke-", "prefix", None)],
        include=r"(?i)kenyalaw\.org(?::\d+)?/akn/(ke-[a-z0-9]+/act/[^@?#]+@?[\d-]*)(?:/source\.pdf)?/?$",
        place=ke_place, follow_pdf=r"(?i)(/source(\.pdf)?|\.pdf)$", selectors=["la-akoma-ntoso", "div.akn-akomaNtoso", "div.document-content", "#document-content"], min_chars=200),
    "VN_vbpl": dict(cc="VN", platform="vn_vbpl", language="vi", doc_type="regulation", consolidated=False,
        queries=[("vbpl.vn/", "prefix", ["mimetype:text/html", "original:.*vbpq-toanvan.aspx.*ItemID=.*"])],
        include=r"(?i)vbpl\.vn(?::\d+)?/([a-z]+/Pages/vbpq-toanvan\.aspx\?.*?ItemID=\d+)",
        hf_key=r"(?i)ItemID=(\d+)", place=vn_place, title_from_text=2, selectors=["div.toanvancontent", "#toanvancontent", "div.fulltext"],
        min_chars=200),
    "PE": dict(cc="PE", platform="pe_elperuano_normas", language="es", doc_type="regulation", consolidated=False,
        queries=[("busquedas.elperuano.pe/normaslegales/", "prefix", ["mimetype:text/html"]),
                 ("busquedas.elperuano.pe/dispositivo/NL/", "prefix", None)],
        include=r"(?i)busquedas\.elperuano\.pe(?::\d+)?/(?:normaslegales/(?!-?avis)[\w-]*?-(\d{5,8})-\d+/?|dispositivo/NL/(\d{5,8})-\d+)$",
        hf_key=r"(?:normaslegales/[\w-]*?-|/NL/)(\d{5,8})-", place=NAT("PE"),
        selectors=["div.story", "#story", "article"], min_chars=250),
    "KW": dict(cc="KW", platform="kw_kuwaitalyawm", language="ar", doc_type="gazette_act", consolidated=False,
        disabled="archives hold only issue landing pages/ads (~470 chars); issue PDFs (/system/files/) have 0 Wayback captures",
        queries=[("kuwaitalyawm.media.gov.kw", "domain", None)],
        include=r"(?i)kuwaitalyawm\.media\.gov\.kw(?::\d+)?/((?:online/)?(?:AdsDetails|Details|flip|Article|%D8%A7%D9%84%D8%A7%D8%B9%D8%AF%D8%A7%D8%AF)[^#]*|.+\.pdf)$",
        place=NAT("KW"), min_chars=400),
    "CN_npc": dict(cc="CN", platform="cn_npc", language="zh", doc_type="statute", consolidated=True,
        queries=[("npc.gov.cn/npc/c2/", "prefix", ["mimetype:text/html"]), ("npc.gov.cn/c2/", "prefix", ["mimetype:text/html"]),
                 ("npc.gov.cn/zgrdw/npc/xinwen/", "prefix", ["mimetype:text/html", "original:.*/(lfgz|fztd)/.*"]),
                 ("flk.npc.gov.cn/detail", "prefix", None)],
        include=r"(?i)((?:www\.)?npc\.gov\.cn(?::\d+)?/(?:npc/)?c2/(?:c\d+/)+\d{6}/t\d{8}_\d+\.html|npc\.gov\.cn/zgrdw/npc/xinwen/(?:lfgz|fztd)/.+\.htm|flk\.npc\.gov\.cn/detail2?\.html\?\w+)$",
        hf_key=r"(npc\.gov\.cn/.+\.html?)$", place=NAT("CN"), selectors=["#Zoom", "div.Zoom", "div.article", "div.wenzhang"],
        title_must=r"法|条例|决定|规定", min_chars=300),
    # ---- archive-only targets whose live robots.txt disallows crawling (decision 2026-10-10: archived copies OK,
    # docs carry source_policy='archived_robots_disallowed' via robots_policy.py; no live requests ever)
    "CN_flk": dict(cc="CN", platform="cn_flk_npc", language="zh", doc_type="statute", consolidated=True,
        custom="flk", hf_title_dedupe=True, keep_caps=2,
        queries=[("wb.flk.npc.gov.cn", "domain", None)],
        include=r"(?i)wb\.flk\.npc\.gov\.cn(?::\d+)?/(flfg|xffl|xzfg|sfjs|dfxfg)/(?:(WORD|PDF)/(\w{16,40})\.(docx|pdf)|html/\w/(\w{40})/0/text/\d+\.json)",
        key_fn=lambda m: (f"{m.group(1)}/{m.group(2).upper()}/{m.group(3)}.{m.group(4).lower()}" if m.group(2)
                          else f"{m.group(1)}/reader/{m.group(5)}"),
        place=NAT("CN"), title_must=r"法|条例|决定|规定|办法|解释|细则|规则|决议|批复", min_chars=200),
    "KZ_adilet": dict(cc="KZ", platform="kz_adilet", language="ru", doc_type="regulation", consolidated=True,
        queries=[("adilet.zan.kz/rus/docs/", "prefix", ["mimetype:text/html", r"original:.*/rus/docs/[A-Za-z0-9_]+/?$"])],
        include=r"(?i)adilet\.zan\.kz(?::\d+)?/rus/docs/([A-Z][A-Z0-9_]{9,12})/?$",
        hf_key=r"/docs/([A-Za-z0-9_]+)", keep_caps=6, reject_body=r"(?i)включите JavaScript|enable JavaScript",
        selectors=["div.container_gamma.text", "div.container_gamma", "article"],
        head_rx=r"(?m)^\s*(?:Решение|Постановление|Распоряжение|Приказ|Совместный приказ|Указ|Закон|Кодекс|Конституционный закон|Нормативное постановление)[^\n]{5,250}$",
        doc_type_fn=lambda key, title: "statute" if key[:1].upper() in "ZK" else "regulation",
        place=kz_spec_place, min_chars=200),
    "PE_spij": dict(cc="PE", platform="pe_spij_minjus", language="es", doc_type="regulation", consolidated=False,
        # SPIJ's Folio/CLP pages archive as login/error pages and the new SPIJ is an SPA (8 archived API JSONs);
        # the archived norm PDFs under /Graficos/Peru/<year>/<month>/<day>/ are usable. EXP-* (exposición de
        # motivos) and ANEXO files are not the norm itself -> excluded.
        queries=[("spij.minjus.gob.pe/Graficos/", "prefix", ["mimetype:application/pdf"])],
        include=r"(?i)spij\.minjus\.gob\.pe(?::\d+)?/(Graficos/Peru/\d{4}/\w+/\d{1,2}/[^/?#]+\.pdf)$",
        exclude=r"(?i)/(EXP-|[^/]*ANEXO)", keep_caps=3,
        doc_type_fn=lambda key, title: "statute" if re.search(r"/(l|dl|dleg|ley)[-_ ]?\d", key) else "regulation",
        title_rx=r"(?m)^[ \t]*(?:LEY|DECRETO (?:SUPREMO|LEGISLATIVO|DE URGENCIA|REGIONAL)|RESOLUCI[ÓO]N (?:MINISTERIAL|SUPREMA|JEFATURAL|DIRECTORAL|ADMINISTRATIVA|LEGISLATIVA|DE [A-ZÁÉÍÓÚ ]+)|ORDENANZA)[ \t]+N[°ºo.]*[ \t]*[\w\-/ ]{1,40}$",
        title_from_key=pe_spij_title,
        place=NAT("PE"), min_chars=300),
    # Macau Boletim Oficial (Imprensa Oficial). Live robots.txt unreachable (TLS EOF on https, connect timeout on http,
    # 2026-10-16) => disallow-all; archive-only. Added by national bot; not launched (Wayback breaker open).
    "MO_bo": dict(cc="MO", platform="mo_bo_io", language="pt", doc_type="gazette_act", consolidated=False,
        queries=[("bo.io.gov.mo/bo/i/", "prefix", ["mimetype:text/html"])],
        include=r"(?i)bo\.io\.gov\.mo(?::\d+)?/bo/(i/\d{4}/\d{2}/[\w.-]+\.asp)",
        exclude=r"(?i)/(?:index|bo)\.asp|_cn\.asp",
        place=NAT("MO"), min_chars=300),
}
