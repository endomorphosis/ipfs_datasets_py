"""Extract legal hierarchy from country-law text (Oregon-style, multilingual).

Oregon Revised Statutes are stored as title / chapter / section / subsection
trees. National gazettes are not that uniform: some use Article/Artikel,
some §, some only a single instrument body.

This module:

* strips leftover HTML chrome so GraphRAG sees legal text, not tags;
* detects multilingual heading markers (title/chapter/part/article/section);
* splits an instrument into those units when at least two headings exist;
* otherwise keeps the whole instrument (never invents a hierarchy).

Subsection markers such as ``(a)`` / ``(1)`` are recorded on the parent
unit; they are not forced into their own retrieval rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import html as html_lib
import json
import os
from pathlib import Path
import re
import unicodedata
from typing import Any

_WS_RE = re.compile(r"\s+", re.UNICODE)
_HAS_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")

# 1:1 map so match offsets stay aligned with the stored body. re.I does not
# treat É as E; gazettes use Décision, Ordonnance, Điều, Člen, etc.
_LATIN_FOLD = str.maketrans({
    **dict.fromkeys("áàâäãåăąāấầẩẫậắằẳẵặảạ", "a"),
    **dict.fromkeys("ÁÀÂÄÃÅĂĄĀẢẠ", "A"),
    **dict.fromkeys("éèêëěęēếềểễệẻẹə", "e"),
    **dict.fromkeys("ÉÈÊËĚĘĒẺẸƏ", "E"),
    **dict.fromkeys("íìîïĩįīıịỉ", "i"),
    **dict.fromkeys("ÍÌÎÏĨĮĪİỈỊ", "I"),
    **dict.fromkeys("óòôöõőøōốồổỗộớờởỡợỏọ", "o"),
    **dict.fromkeys("ÓÒÔÖÕŐØŌỎỌ", "O"),
    **dict.fromkeys("úùûüűũūůứừửữựủụ", "u"),
    **dict.fromkeys("ÚÙÛÜŰŨŪŮỦỤ", "U"),
    **dict.fromkeys("ýÿỳỹỷỵ", "y"),
    **dict.fromkeys("ÝŸỶỴ", "Y"),
    **dict.fromkeys("çćčĉċ", "c"),
    **dict.fromkeys("ÇĆČĈĊ", "C"),
    **dict.fromkeys("ďđ", "d"),
    **dict.fromkeys("ĎĐ", "D"),
    **dict.fromkeys("ğĝģġ", "g"),
    **dict.fromkeys("ĞĜĢĠ", "G"),
    **dict.fromkeys("ñńņň", "n"),
    **dict.fromkeys("ÑŃŅŇ", "N"),
    **dict.fromkeys("ŕŗř", "r"),
    **dict.fromkeys("ŔŖŘ", "R"),
    **dict.fromkeys("śŝşšș", "s"),
    **dict.fromkeys("ŚŜŞŠȘ", "S"),
    **dict.fromkeys("ţťț", "t"),
    **dict.fromkeys("ŢŤȚ", "T"),
    **dict.fromkeys("źżž", "z"),
    **dict.fromkeys("ŹŻŽ", "Z"),
    **dict.fromkeys("ĺļľł", "l"),
    **dict.fromkeys("ĹĻĽŁ", "L"),
    "æ": "a", "Æ": "A", "œ": "o", "Œ": "O", "ß": "s",
    "ɛ": "e", "Ɛ": "E", "ɔ": "o", "Ɔ": "O", "ŋ": "n", "Ŋ": "N",
    **dict.fromkeys("ơớờởỡợ", "o"),
    **dict.fromkeys("ƠỚỜỞỠỢ", "O"),
    **dict.fromkeys("ưứừửữự", "u"),
    **dict.fromkeys("ƯỨỪỬỮỰ", "U"),
    **dict(zip("άέήίόύώϊϋΐΰ", "αεηιουωιυιυ")),
    **dict(zip("ΆΈΉΊΌΎΏ", "ΑΕΗΙΟΥΩ")),
    "ς": "σ",
    "ё": "е", "Ё": "Е", "ї": "и", "Ї": "И", "є": "е", "Є": "Е", "ґ": "г", "Ґ": "Г",
})


def _latin_fold(text: str) -> str:
    return text.translate(_LATIN_FOLD)

# Headings at line start *or* after . ; : so compacted "Art. 1. … Art. 2." still splits.
# Separator allows "Art. 1", "Art.1", "Član 12.", "ARTICULO 10.-", "Madde 1 –",
# "Article (1)", French "Art. L. 111-1", Roman "ARTICLE I".
_HEADING_NUM = (
    r"(?:[0-9٠-٩۰-۹]+(?:er|ère|bis|ter|quater|o)?"
    r"|(?-i:[IVXLCDM]{1,8})(?:er|ère)?(?![A-Za-z])"
    r"|premier(?:e)?|première|primero|primeira"
    r"|unique|unico|unica|único|única)"
)
_ARTICLE_N = (
    r"(?:"
    r"(?:[LRD]\.?\s*)?"
    r"(?:"
    r"[0-9٠-٩۰-۹]+(?:\.[0-9]+)?"
    r"(?:er|ère|bis|ter|quater|aad|[A-Za-z]|o)?"
    r"(?:/[0-9A-Za-z]+)?"
    r"(?:\s+(?:bis|ter|quater))?"
    r"|(?-i:[IVXLCDM]{1,8})(?:er|ère)?(?![A-Za-z])"
    r"|[Α-Ω]{1,6}(?![Α-Ωα-ω])"
    r")"
    r"(?:[-–](?:[0-9]+|aad|bis|ter|quater|[A-Za-z](?![A-Za-z])))?"
    r"(?:\([0-9A-Za-z]+\))?"
    r"|premier(?:e)?"
    r"|première"
    r"|unique|unico|unica|único|única"
    r"|primero|primera|primeiro|primeira"
    r"|primo(?![A-Za-z])|secondo(?![A-Za-z])|terzo(?![A-Za-z])|quarto(?![A-Za-z])|quinto(?![A-Za-z])|prima(?![A-Za-z])"
    r"|eerste|första|første"
    r"|annexe"
    r"|primera|segunda|tercera|cuarta|quinta"
    r"|sexta|séptima|octava|novena|décima"
    r")"
)
_HEADING_START = r"(?:^|(?<=[.;:])|(?<=\d[ \t]))[ \t\[\(\u00ab\u00bb\"“”‘’«»‹›\u2039\u203a]*"
_HEADING_RE = re.compile(
    _latin_fold(
    r"(?im)" + _HEADING_START + r"(?:"
    r"(?P<title>TITLE|TITRE|TITEL|T[IÍ]TULO|TITOLO|TITLUL|T[IÍ]TUL|LUKU|PEAT[UÜ]KK|"
    r"РАЗДЕЛ|РОЗДІЛ|DZIA[ŁL]|ΤΙΤΛΟΣ|ДЯЛ)\s+"
    r"(?P<title_n>" + _HEADING_NUM + r"(?:\.[0-9]+|-(?:[0-9]+|[A-Za-z](?![A-Za-z])))?)"
    r"|(?P<chapter>CHAPTER|CHAPITRE|KAPITEL|CAP[IÍ]TULO|CAPITOLO|HOOFDSTUK|"
    r"ROZDZIA[ŁL]|CAPITOLUL|NODA[ĻL]A|GLAVA|ГЛАВА|POGLAVLJE|KAPITOLA|"
    r"ΚΕΦΑΛΑΙ[ΟO]|CH[UƯ][OƠ]NG|BAB|KABANATA|CAPO|HLAVA|KREU|FEJEZET|"
    r"B[ÖO]L[ÜU]M|FESIL|CAIBIDIL|PENNOD|KAPITOLU|CHAPIT|ODDIEL|"
    r"SURA(?:\s+YA)?|KAPITTEL|KAPITTUL|ANDIANY|SASHE(?:\s+NA)?|WASE|"
    r"ISIGABA|ICANDELO|KGAOLO|BOBI|KUTAA|ORI|CAP\.)\s+"
    r"(?P<chapter_n>" + _HEADING_NUM + r"(?:\.[0-9]+|-(?:[0-9]+|[A-Za-z](?![A-Za-z])))?)"
    r"|(?P<part>PART|PARTIE|TEIL|PARTE|DEEL|LIVRE|BOOK|BUCH|TOMO|KNIHA|"
    r"KODEKS|CODE|ZAKONIK|BAHAGIAN|BAGIAN|SEHEMU|MỤC|MUC|LIBRO|PH[AẦ]N|"
    r"QAYBTA|WAHANGA|VAEGA|HAP|KAROLO|CHIKAMU|BES|EKITUNDU|ETENI|"
    r"AKPA|FAANDA|PATTE|ΜΕΡΟΣ)\s+"
    r"(?P<part_n>" + _HEADING_NUM + r"(?:\.[0-9]+|-(?:[0-9]+|[A-Za-z](?![A-Za-z])))?)"
    r"|(?P<article>(?:l['’])?(?:(?:EK|GEÇICI|GECICI|GEÇİCİ)\s+)?"
    r"(?:ART(?:ICLE|IKEL|ÍCULO|ICULO|IGO|ICOLO|IKKEL|YKU[ŁL]|ICOLUL|ICOL|IKOLU|IKULA)?\.?"
    r"|ART\.|NENI|PASAL|MADDE|MADDƏ|ĐIỀU|ĐIÊU|DIEU|CLANAK|ČLANAK|ČLÁNEK|ČLÁNOK|ČLEN|ČLAN|CLAN"
    r"|ЧЛАНАК|ЧЛАН|ЧЛЕН|ЧЛ\.|СТАТЬЯ|СТАТТЯ|SZAKASZ|CIKK|ΆΡΘΡΟ|ΑΡΘΡΟ"
    r"|PYKÄLÄ|GREIN|PANTS|SEKSYEN|CIKK|KIFUNGU|MODDA|ATIK|KUPU|ATIKOL|"
    r"INGINGO(?:\s+YA)?|NDIME|ABALA|NKEJI|SARIYA|TERE|AHYEDE|PENNAD|ERTHYGEL|HYEDEE|"
    r"ARTIGU|PAUKU|IRAVA"
    r"|მუხლი|ՀՈԴՎԱԾ|Հոդված))(?![A-Za-z])"
    r"(?:\s*(?:n\.?[o°º”'“*´`]|nr|no)\.?\s*)?\s*[.\s:–—-]*\(?\s*"
    r"(?P<article_n>" + _ARTICLE_N + r")\)?"
    r"|(?P<section>SUB(?:-)?SECTION|SECTION|SECCI[OÓ]N|SEZIONE|ABSCHNITT|PARAGRAHV|PARAGRAPHE|PARAGRAAF|PARAGRAPH|"
    r"RECITAL|CONSIDERANDO|"
    r"ALIN[EÉ]A|ALINEATUL|INCISO|P[AÁ]RRAFO|PUNKT(?![A-Za-z])|SATZ(?![A-Za-z])|LID|"
    r"ΠΑΡΑΓΡΑΦΟΣ|ABSATZ|APARTADO|COMMA(?![A-Za-z])|FIKRA|STAVAK|STK\.?|АЛ\.|SEKSHON|"
    r"NUMERAL|CAPOVERSO|NUMMER|"
    r"AYAT|KHOẢN|KHOAN|"
    r"RULE(?![A-Za-z])|REGULATION(?![A-Za-z])|SCHEDULE(?![A-Za-z])|FORM(?![A-Za-z])|"
    r"ORDINANCE|ORDONNANCE|ORDONAN[TŢȚ][AĂÁ]?|ORDIN(?![A-Za-z])|BY-?LAW|DIRECTIVE(?![A-Za-z])|"
    r"D[EÉ]CISION(?![A-Za-z])|DECISION(?![A-Za-z])|DECIZIE|"
    r"BESLUIT(?![A-Za-z])|REGELING(?![A-Za-z])|BESCHIKKING(?![A-Za-z])|"
    r"ODLUKA|PRAVILNIK|HOT[ĂA]R[ÂAÎI]RE|"
    r"RESOLUCI[OÓ]N(?![A-Za-z])|RESOLU[CÇ][AÃ]O(?![A-Za-z])|PORTARIA(?![A-Za-z])|ACUERDO(?![A-Za-z])|"
    r"MEDIDA\s+PROVIS[OÓ]RIA|"
    r"PROCLAMATION(?![A-Za-z])|PROKLAMATION|CIRCULAR(?![A-Za-z])|INSTRUCTION(?![A-Za-z])|"
    r"GUIDELINE(?![A-Za-z])|MEMORANDUM(?![A-Za-z])|"
    r"AVISO(?![A-Za-z])|AVIS(?![A-Za-z])|BEKANNTMACHUNG|MEDDELANDE|"
    r"NORMA(?![A-Za-z])|"
    r"PRESIDENTIAL\s+DECREE|DECRETO-LEI|DECRETO(?![A-Za-z])|DECREE(?![A-Za-z])|"
    r"D[EÉ]CRET-LOI|D[EÉ]CRET(?![A-Za-z])|ARR[EÊ]T[EÉ]|"
    r"DELIBERA[CÇ][AÃ]O|D[EÉ]LIB[EÉ]RATION|COMUNICADO|"
    r"R[EÈ]GLEMENT(?![A-Za-z])|CIRCULAIRE(?![A-Za-z])|VERORDNUNG(?![A-Za-z])|ERLASS(?![A-Za-z])|"
    r"PUNTO(?![A-Za-z])|SUB(?:-)?PARAGRAPH|"
    r"ANNEX(?:E)?(?![A-Za-z])|ANEXO|ANLAGE|BIJLAGE|APPENDIX|ALLEGATO|"
    r"ZA[ŁL][AĄ]CZNIK|BILAGA|LIITE|P[ŘR][IÍ]LOHA|"
    r"UST\.|ODST\.|ODS\.|BEK\.|"
    r"SEC(?:\.|(?=\s+[0-9])))(?![A-Za-z])(?:\s*(?:n\.?[o°º”'“*´`]|nr|no)\.?\s*)?[.\s:]*\(?\s*"
    r"(?P<section_n>(?:[0-9][0-9A-Za-z.\-]*(?:\([0-9A-Za-z]+\))?|"
    r"(?-i:[IVXLCDM]{1,8})(?![A-Za-z])|[A-Za-z](?![A-Za-z])))\)?"
    r"|(?P<section_sym>§+)\s*(?P<section_sym_n>[0-9]+(?:[A-Za-z](?![A-Za-z]))?(?:\s+[A-Za-z](?![A-Za-z]))?(?:\s*\([0-9A-Za-z]+\))?)"
    r"|(?P<section_pre_n>[0-9]+(?:\s*[a-z])?)\s*\.?\s*(?P<section_pre>§)"
    r"|(?P<grein_n>[0-9]+[a-z]?)\s*\.\s*(?P<grein>gr|pants)\.?"
    r"|(?P<straipsnis_n>[0-9]+[a-z]?)\s*[.]?\s*(?P<straipsnis>straipsnis)"
    r"|(?P<artikulua_n>[0-9]+[a-z]?)\s*[.]?\s*(?P<artikulua>artikulua)"
    r"|(?P<ledd_n>[0-9]+)\s*[.]?\s*(?P<ledd>ledd)"
    r"|(?P<kap_n>[0-9]+)\s*(?P<kap>kap)\.?"
    r"|(?P<luku_n>[0-9]+)\s*(?P<luku>luku)"
    r"|(?P<fejezet_n>[IVXLCDM0-9]+)\s*\.\s*(?P<fejezet>fejezet)"
    r"|(?P<peatukk_n>[0-9]+)\s*[.]?\s*(?P<peatukk>peat[uü]kk)"
    r"|(?P<skyrius_n>[IVXLCDM0-9]+)\s*(?P<skyrius>skyrius)"
    r"|(?P<nodala_n>[IVXLCDM0-9]+)\s*(?P<nodala>noda[ļl]a)"
    r"|(?P<kafli_n>[IVXLCDM0-9]+)\s*[.]?\s*(?P<kafli>kafli)"
    r"|(?P<bob_n>[0-9]+)\s*-\s*(?P<bob>bob)"
    r"|(?P<tarau_n>[0-9]+)\s*-\s*(?P<tarau>тарау)"
    r"|(?P<bolum_n>[0-9]+)\s*-\s*(?P<bolum>бөлүм)"
    r"|(?P<modda_n>[0-9]+)\s*-\s*(?P<modda>модда|modda)"
    r"|(?P<mn_n>[0-9]+)\s*(?P<mn>(?:дүгээр|дугаар)\s*зүйл)"
    r"|(?P<kk_n>[0-9]+)\s*-?\s*(?P<kk>бап)"
    r"|(?P<mom_n>[0-9]+)\s*(?P<mom>momentti)"
    r"|(?P<order>(?:EXECUTIVE\s+)?ORDER)\s+(?P<order_n>[0-9]+)"
    r"|(?P<kidogo>KIFUNGU\s+KIDOG[OU])\s*\(?\s*(?P<kidogo_n>[0-9]+)"
    r"|(?P<disp>DISPOSICI[OÓ]N)(?:\s+(?:adicional(?:es)?|transitoria(?:s)?|derogatoria(?:s)?|final(?:es)?))?\s+"
    r"(?P<disp_n>" + _ARTICLE_N + r")"
    r"|(?P<esresol>primero|segundo|tercero|cuarto|quinto|sexto|septimo|octavo|noveno|decimo|"
    r"erstens|zweitens|drittens|viertens|funftens|"
    r"premierement|deuxiemement|troisiemement|quatriemement|cinquiemement)\s*:"
    r")"
    )
)
# Commonwealth "1. Short title" — used only when keyword headings are scarce.
_CW_NUM_RE = re.compile(
    r"(?m)^[ \t]*(?P<cw_n>[0-9]+[A-Za-z]?)\.?\s+(?:\([0-9A-Za-z]+\)\s+)?(?=[A-Z][a-z]+)"
)
_MONTH_START_RE = re.compile(
    r"(?i)^(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"janvier|f[eé]vrier|marzo|abril|enero|junio|julio)\b"
)
_CW_NUM_LANGS = frozenset({"", "en", "hi", "bn", "ne", "ur", "ms", "fil", "sw", "si"})
_LEXICON_HEADING_RE: re.Pattern[str] | None = None
_LEXICON_KIND: dict[str, str] = {}

_SUBSECTION_RE = re.compile(r"\(([0-9A-Za-z]{1,6})\)")

_KIND_RANK = {
    "title": 1,
    "chapter": 2,
    "part": 3,
    "article": 4,
    "section": 5,
    "subsection": 6,
}

MIN_SPLIT_HEADINGS = 2
MIN_UNIT_CHARS = 40

# Markers on the *stored* body (no rewritten newline copy).
_ZH_ART_RE = re.compile(
    r"第\s*[一二三四五六七八九十百千万零〇两0-9]+\s*[条條](?:之[一二三四五六七八九十百0-9]+)?"
)
_AR_ORD = (
    r"(?:الحادية|الثانية|الثالثة|الرابعة|الخامسة|السادسة|السابعة|الثامنة|التاسعة)[\s\u0640]*والعشرون|"
    r"(?:الحادية|الثانية|الثالثة|الرابعة|الخامسة|السادسة|السابعة|الثامنة|التاسعة)[\s\u0640]*عشرة|"
    r"العشرون|"
    r"الأولى|الأولي|األولى|الاولى|الثانية|الثالثة|الرابعة|الخامسة|"
    r"السادسة|السابعة|الثامنة|التاسعة|العاشرة"
)
_AR_ORD_M = (
    r"الأول|الاول|الثاني|الثالث|الرابع|الخامس|"
    r"السادس|السابع|الثامن|التاسع|العاشر"
)
_AR_ART_RE = re.compile(
    r"\(?(?:الماد[ةه]|املاد[ةه]|مادة)\s*[-–]?\s*[()]*\s*(?:[0-9٠-٩۰-۹]+|" + _AR_ORD + r")"
    r"(?:\s*[-–])?(?:\s*[()]*)?(?:\s*مكرر(?:اً|ا)?)?"
)
_CITE_TAIL_RE = re.compile(
    _latin_fold(
        r"(?i)\s+(?:"
        r"of\s+(?:this\s+|the\s+)?(?:act|law|agreement|code|constitution|article|section|"
        r"principal\s+act|ordinance|regulation|decree|chapter|part|title|ruling|order)"
        r"|thereof\b"
        r"|hereof\b"
        r"|hereunder\b"
        r"|de\s+la\s+(?:loi|ley|presente|présente)"
        r"|du\s+(?:code|présent|present)"
        r"|des\s+gesetzes"
        r"|van\s+(?:deze\s+)?(?:wet|artikel)"
        r"|i\s+lov\b"
        r"|cua\s+luat(?:\s+nay)?"
        r")\b"
    )
)
_NUMERO_FOLD_RE = re.compile(
    r"(?i)(?:№|n\.\s*o\b|n\.?[°º]|nÂ[oº°]|\bno\.?\s+(?=\d))\.?\s*"
)
_CJK_RANGE_RE = re.compile(
    r"第\s*[一二三四五六七八九十百千万零〇两0-9]+\s*[条條]\s*(?:至|到|から)\s*"
    r"第\s*[一二三四五六七八九十百千万零〇两0-9]+\s*[条條](?:まで)?"
)
_FA_ORD = (
    r"یازدهم|دوازدهم|سیزدهم|چهاردهم|پانزدهم|شانزدهم|هفدهم|هجدهم|نوزدهم|بیستم|"
    r"اولی?|نخست|دوم|سوم|چهارم|چارم|جارم|پنجم|ششم|هفتم|هشتم|نهم|دهم"
)
_FA_ART_RE = re.compile(r"(?:ماده|مادة)\s*(?:[0-9۰-۹]+|" + _FA_ORD + r")")
_DA_ART_RE = re.compile(r"(?:Artikel|§)\s*[0-9]+", re.IGNORECASE)
_CHROME_LINE_RE = re.compile(
    r"(?i)^(?:"
    r"početna stranica\b.*|"
    r"upute za korištenje\b.*|"
    r"elektronička pošta\b.*|"
    r"vsebina uradnega lista\b.*|"
    r"the incident id is\b.*|"
    r"ωράριο λειτουργίας\b.*|"
    r"τηλέφωνο επικοινωνίας\b.*|"
    r"skip to (?:main )?content\b.*|"
    r"javascript is (?:required|disabled)\b.*|"
    r"privacy policy\s*$|"
    r"traduction française pour information\s*$|"
    r"pdf\s*$|"
    r"https?://\S+\s*$|"
    r"légimonaco\b.*|"
    r"statutory instruments\s*$|"
    r"official gazette\s*$|"
    r"government gazette\s*$|"
    r"(?:the )?london gazette\s*$|"
    r"journal officiel(?: de la république(?: [^\n]{0,40})?)?\.?\s*$|"
    r"bulletin officiel\s*$|"
    r"gazette du canada\s*$|"
    r"(?:the )?[\w .'-]{0,50}gazette\s*$|"
    r"الوقائع المصرية\s*$|"
    r"الوقائع العراقية\b.*|"
    r"العدد\s*$|"
    r"العدد\s+\S.{0,80}الوقائع\b.*|"
    r".*شعبة الجريدة الرسمية\s*$|"
    r"(?:the )?(?:republic of sudan gazette|gazette published by authority|official gazette of the republic of sudan)\b.*|"
    r"الصفحة(?:\s*[0-9٠-٩]+)?\s*$|"
    r"(?:الجريدة|اجلريدة|جريدة)(?:\s+الر\s*سمية)?(?:\s+العدد(?:\s*\(\s*\)?\s*[0-9٠-٩]+)?)?\s*$|"
    r"république du s[ée]n[ée]gal\s*$|"
    r"jamhuuriyadda\b.*|"
    r"warta kerajaan\s*$|"
    r"lembaran negara\s*$|"
    r"berita negara\s*$|"
    r"công báo\s*$|"
    r"la gaceta\s*$|"
    r"no\.?\s*\d+\s+government gazette\b.*|"
    r"supplement to (?:the |official ).{0,60}gazette\b.*|"
    r"[a-z0-9 ,.'()-]*supplement to official gazette[a-z0-9 ,.'()-]*$|"
    r"printed by\b.*|"
    r"https?://\S+(?:\s+\d+(?:\.\d+)*)?\s*$|"
    r"©+\s*.*congress\b.*|"
    r"(?:s|sm)\s+congress\b.*|"
    r"palikir,\s*pohnpei\b.*|"
    r"www\.\S+(?:\s+\d+)?\s*$|"
    r"at\s+www\.\S+\s*$|"
    r".*research bulletin.*|"
    r"acts supplement\s*$|"
    r"supplement\s+(?:nr\.\s*|no\.?\s*)\d+(?:\s+\d{1,2}(?:st|nd|rd|th)\s+[a-z]+,?\s+\d{4}\.?)?\s*$|"
    r"no\.\s+of\s+\d{4}\.?\s*$|"
    r"act no\.\s+of\s+\d{4}\.?\s*$|"
    r"bill for the\s*$|"
    r"(?:the )?republic of [a-z]+(?:\s+[a-z]+)?\s*$|"
    r"federal republic of [a-z]+(?:\s+[a-z]+)?\s*$|"
    r"democratic people's republic of korea\s*$|"
    r".{0,10}republic of palau\s*$|"
    r"saint vincent and the grenadines\s*$|"
    r"\[?\s*član\s+\.\.\.\s*\]?\s*$|"
    r".*аудиони тинглаш.*|"
    r"reprint\s*$|"
    r"reprint authorised by\b.*|"
    r"parliament building\s*$|"
    r"oau drive, tower hill\s*$|"
    r"office of the clerk of parliament\s*$|"
    r"(?:(?:first|second|third|fourth|fifth)\s+parliament(?:\s+of\s+the\s+(?:first|second|third|fourth|fifth)\s+republic)?\s*){1,2}$|"
    r"(?:(?:first|second|third|fourth|fifth)\s+meeting of parliament\s*){1,2}$|"
    r"تفاصيل\s+(?:النظام|اللائحة)\s*$|"
    r"مجموعة الأنظمة السعودية\s*$|"
    r"المجلد\s+\S+\s*$|"
    r"أنظمة\s+\S.{0,60}$|"
    r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+folder\s*$|"
    r"this law includes:\s*$|"
    r"-\s*اختر\s*-\s*$|"
    r"تاريخ الإصدار\s*$|"
    r"تاريخ النشر\s*$|"
    r"الحالة\s*$|"
    r"ساري\s*$|"
    r"العربية\s*$|"
    r"الإسم\s*$|"
    r"البريد الإلكتروني\s*$|"
    r"رقم الجوال\s*$|"
    r"نوع البلاغ\s*$|"
    r"\d{4}/\d{2}/\d{2}\s+ه\s+الموافق\s*:?\s*\d{2}/\d{2}/\d{4}\s+م\s*$|"
    r"\d{3,4}\s+ه\s*$|"
    r"خطأ لغوي\s*$|"
    r"خطأ في مادة\s*$|"
    r"يتضمن (?:النظام|التنظيم) ما يلي\s*:?\s*$|"
    r"عدد مرات التصفح\s*\d*\s*$|"
    r"نبذة عن النظام\s*$|"
    r"اسم النظام/اللائحة\b.*|"
    r"تاريخ (?:إصدار|نشر) النظام/اللائحة\s*$|"
    r"حالة النظام/اللائحة\b.*|"
    r"أدوات إصدار النظام\s*$|"
    r"نص النظام\s*$|"
    r"مادة معدلة\s*$|"
    r"مادة ملغية\s*$|"
    r"اصل الوثيقة\s*$|"
    r"طباعة\s*$|"
    r"إبلاغ\s*$|"
    r"الإصدارات\s*$|"
    r"اللغات\s*$|"
    r"الإنجليزية\s*\(English\)\s*$|"
    r"(?:\d{4}\s+)?revised edition(?:\s+as at\b.*|\s+page\s+\d+)?\s*$|"
    r"page\s+\d+\s+\d{4}\s+revised edition\s*$|"
    r"\[note: this version\b.*|"
    r"\[this is the version of this document\b.*|"
    r"el peruano\s*$|"
    r"(?:act\s+\d+\s+of\s+\d{4}\s+)?page\s*\d+(?:\s+(?:of\s+\d+|act\s+\d+\s+of\s+\d{4}|[a-z]))?\s*$|"
    r"[a-z]\s+page\s*\d+\s*$|"
    r"(?:section\s+)?pages?\s*$|"
    r"seite\s+\d+(?:\s+(?:von|of|bis)\s+\d+)?\s*$|"
    r"bundesrecht konsolidiert\b.*|"
    r".*ris\.bka\.gv\.at.*$|"
    r"\{\\rtf\d+\b.*|"
    r"p[aá]gina\s+\d+\s*$|"
    r"pagina\s+\d+\s*$|"
    r"strona\s+\d+\s*$|"
    r"p\.\s*\d+(?:\s+(?:of|di|von|sur|de)\s+\d+)?\s*$|"
    r"pag\.\s*\d+(?:\s+(?:di|of|de)\s+\d+)?\s*$|"
    r"blz\.\s*\d+\s*$|"
    r"folio\s+\d+\s*$|"
    r"foglio\s+\d+\s*$|"
    r"лист\s+\d+\s*$|"
    r"стр\.\s*\d+\s*$|"
    r"ص\s*\.?\s*\d+\s*$|"
    r"עמוד\s+\d+\s*$|"
    r"trang\s+\d+\s*$|"
    r"halaman\s+\d+\s*$|"
    r"sayfa\s+\d+\s*$|"
    r"oldal\s+\d+\s*$|"
    r"stran(?:ica)?\s+\d+\s*$|"
    r"www\.\S+\s*$|"
    r"downloaded from\b.*|"
    r"printed on\s+\d.*|"
    r"generated by\b.*|"
    r"e-?mail:\s*\S+@\S+\s*$|"
    r"tel(?:ephone)?:\s*[+\d].*$|"
    r"for more information visit\b.*|"
    r"[-–—]\s*\d{1,4}\s*[-–—]\s*$|"
    r"table of contents\s*$|"
    r"table des mati[eè]res\s*$|"
    r"inhaltsverzeichnis\s*$|"
    r"(?:índice|indice)\s*$|"
    r"sommaire\s*$|"
    r".*\barrangement of (?:sections|provisions|regulations|rules)\.?(?:\s+cap\.\s*[\d.]+.*)?\s*$|"
    r"contents\s*$|"
    r"section\s*$|"
    r"[\s.\-;,*/_×|+~•·{}()\\=»«®∞]+$|"
    r"(?=.*[+|])[+\-|]{3,}\s*$|"
    r"\[original service \d{4}\].*|"
    r"statute law of the [a-z ]+$|"
    r"[A-Z][A-Z .'\-]{0,40}\[ch\.\s*\d+.*|"
    r"التاريخ:\s*$|"
    r"republic of the marshall islands\s*$|"
    r"jepilpilin ke ejukaan\s*$|"
    r"zastupni[cč]ki dom hrvatskoga sabora\s*$|"
    r"dr[zž]avni zavod za normizaciju i mjeriteljstvo\s*$|"
    r"олдинги таҳрирга қаранг\.?\s*$|"
    r"explanatory note\s*$|"
    r"\.\s*\(\s*\d+\s*\)\s*$|"
    r"(?:يناير|فبراير|مارس|أبريل|ابريل|مايو|يونيو|يوليو|أغسطس|اغسطس|سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر)\s+\d{4}\s*$|"
    r"laws of (?:the )?[a-z]+(?:\s+(?:&|[a-z]+)){0,4}\s*$|"
    r"(?-i:LAWS OF (?:THE )?[A-Z]+(?:\s+[A-Z]+){0,6}\s+s\s*\d+\s*$)|"
    r"(?:í|i)ndice legislativo\s*$|"
    r"قائمة (?:المحتويات|احملتويات)\s*$|"
    r"spis tre[sś]ci\s*$|"
    r"содержание\s*$|"
    r"πίνακας περιεχομένων\s*$|"
    r"목차\s*$|"
    r"目次\s*$|"
    r"สารบัญ\s*$|"
    r"[aα]ριθμός\s+\d+[^\n]{0,24}\s*$|"
    r"[aα]ρ\.\s*\d+(?:/\d+)?[^\n]{0,12}\s*$|"
    r"številka\s+\d+[^\n]{0,24}\s*$|"
    r"(?:nr|no|n[uú]m(?:ero|éro|ber)?|broj|č[ií]slo|szám|sayı|номер)\.?\s*\d{2,}(?:/\d+)?[.\s]*$|"
    r"№\s*\d+\s*$|"
    r"copyright\s*©?\s*\d{4}.*$|"
    r"©\s*\d{4}.*$|"
    r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s*$|"
    r"\d{4}-\d{2}-\d{2}\s*$|"
    r"\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december|"
    r"janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[eé]cembre|"
    r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+\d{4}\s*$|"
    r"end of (?:the )?document\s*$|"
    r"fin du document\s*$|"
    r"ende des dokuments?\s*$|"
    r"fin del documento\s*$|"
    r"fim do documento\s*$|"
    r"[-*=._]{3,}\s*$|"
    r"published\s*$|"
    r"publi[eé]\s*$|"
    r"publicado\s*$|"
    r"veröffentlicht\s*$|"
    r"\[?seal\]?\s*$|"
    r"\(seal\)\s*$|"
    r"l\.s\.?\s*$|"
    r"god save the (?:king|queen)\s*$|"
    r"vive la r[eé]publique\s*$|"
    r"by (?:order|command)\s*$|"
    r"signed\s*$|"
    r"diario oficial(?: de la federación)?\s*$|"
    r"gazzetta ufficiale(?: della repubblica(?: italiana)?)?\s*$|"
    r"boletín oficial(?: del estado)?\s*$|"
    r"diário da república\s*$|"
    r"bundesgesetzblatt\s*$|"
    r"moniteur belge\s*$|"
    r"belgisch staatsblad\s*$|"
    r"staatsblad\s*$|"
    r"lovtidende\s*$|"
    r"svensk författningssamling\s*$|"
    r"uradni list\s*$|"
    r"dziennik ustaw\s*$|"
    r"monitorul oficial\s*$|"
    r"εφημερίδα της κυβερνήσεως\s*$|"
    r"resmi gazete\s*$|"
    r"iris oifigiúil\s*$|"
    r"latvijas vēstnesis\s*$|"
    r"valstybės žinios\s*$|"
    r"官報\s*$|"
    r"国务院公报\s*$|"
    r"관보\s*$|"
    r"ราชกิจจานุเบกษา\s*$|"
    r"(?:เล่ม|เลม)\s*[๐-๙0-9].*ราชกิจจานุเบกษา.*|"
    r"اطلاق نسخة جديدة من الميزان\s*$|"
    r"\[\d+/\d{4}(?:\s+wef\s+[\d/]+)?\]\s*$|"
    r"\[\d{1,2}(?:st|nd|rd|th)\s+[a-z]+\s+\d{4}\]\s+.+\s+\d{1,4}\s*$|"
    r"\[\d{1,2}(?:st|nd|rd|th)\s+[a-z]+,?\s+\d{4}\]\s*$|"
    r"(?:18|19|20)\d{2}\s*$|"
    r"gazette\.?\s*$|"
    r"cap\.\s*\d+(?:\.\d+)*\s*$|"
    r".+\scap\.?\s*[\d.]+\s+section\s+\d+\s*$|"
    r"diario oficial\s*$|"
    r"diário oficial(?: da união)?\s*$|"
    r"gaceta oficial(?: de la república)?\s*$|"
    r"registro oficial\s*$|"
    r"sbírka zákonů\s*$|"
    r"zbierka z[^\n]{0,40}\s*$|"
    r"magyar közlöny\s*$|"
    r"narodne novine\s*$|"
    r"službeni glasnik\s*$|"
    r"службени гласник\s*$|"
    r"държавен вестник\s*$|"
    r"monitorul oficial(?: al româniei)?\s*$|"
    r"norsk lovtidend\s*$|"
    r"suomen säädöskokoelma\s*$|"
    r"finlands författningssamling\s*$|"
    r"riigi teataja\s*$|"
    r"российская газета\s*$|"
    r"(?:the )?kenya gazette\s*$|"
    r"federal negar[ie]t gazett?e\s*$|"
    r"gazette officielle\s*$|"
    r"amtsblatt(?: der europäischen union)?\s*$|"
    r"official journal of the european union\s*$|"
    r"journal officiel de l'union européenne\s*$|"
    r"gazzetta ufficiale dell'unione europea\s*$|"
    r"الجريدة الرسمية\b.*|"
    r"ваш броузер застарів\b.*|"
    r"your browser is (?:out of date|outdated|obsolete)\b.*|"
    r"all rights reserved\b.*|"
    r"subscribe to\s+(?:our\s+)?(?:newsletter|mailing(?:\s+list)?|updates|feed)\b.*|"
    r"(?:we use|this (?:site|website) uses)\s+cookies\b.*|"
    r".{0,80}використовуємо cookies\b.*|"
    r".{0,80}використання cookies\b.*|"
    r"продовжуючи відвідування сайту\b.*|"
    r"al meezan\b.*|"
    r"الميزان\b.*|"
    r".{0,40}وزارة العدل(?: و الشؤون القانونية)?\s*$|"
    r"التشريعات\b.*|"
    r"page not found\b.*|"
    r"(?:error\s+)?404(?:\s+not found)?\b.*|"
    r"access denied\s*$|"
    r"forbidden\s*$|"
    r"public notification\s*$|"
    r"[^\n]{0,40}@mjla\b.*|"
    r".{0,40}gaceta oficial(?: digital)?\b.*|"
    r"paragraph\s*$|"
    r"[^\n]{0,60}slov-lex\s*$|"
    r"(?:crown\s+)?copyright\s*(?:©\s*)?\d{4}\.?\s*$|"
    r"copying\s*/\s*unauthori[sz]ed distribution strictly prohibited\.?\s*$|"
    r"(?:revision|consolidation) date\s*:.*|"
    r"showing the law as at\s+\d.*|"
    r"this is a revised edition of the law\b.*|"
    r"printed under authority by\s*$|"
    r"(?:the )?regional law revision centre\b.*|"
    r"continued on next page\b.*|"
    r"back to (?:page one|the top|top)\s*$|"
    r"page\s*:\s*\d+\s+date\s*:.*|"
    r"bwpageid\s*::.*|"
    r"bwservice\s*::.*|"
    r".*ron_book\b.*|"
    r"\d+\s+service\s+\d+\s*$|"
    r"(?:pdf|word|audio)\s+download\s*$|"
    r"login with (?:facebook|google|apple|twitter|email)\b.*|"
    r"(?:view|print|e-?mail)\s*$|"
    r"last updated(?:\s+on)?\s+\d.*|"
    r"speakers office\s*$|"
    r"fsm congress\s*$|"
    r".*almeezan\b.*|"
    r"add new section\s*$|"
    r"section name\s*$|"
    r".*hijripage\b.*|"
    r"search in articles\s*$|"
    r"privacy statement\s*$|"
    r"terms of use\s*$|"
    r"rate this website\s*$|"
    r"feedback via reach\s*$|"
    r"singapore statutes online\b.*|"
    r".*reprint is authorised by\b.*|"
    r"công báo\s*/\s*số\b.*|"
    r"thời gian ký\s*:.*|"
    r"lex\.?uz\b.*|"
    r"\[?(?:окоз|тсз|спит)\s*:.*|"
    r"\d+(?:\.\d{2}){3,}.*[\u0400-\u04FF].*|"
    r"issue\s*:\s*\d+\s*,\s*amendment\s*:\s*\d+\b.*|"
    r"presidential comm\.?\s*no\b.*|"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4}(?:\s+[a-z])?\s*$|"
    r"(?-i:\d{1,4}\s+[Cc][Aa][Pp]\.\s*\d+\.\d+\b(?!.*\b(?!etc\b)[a-z]{3,}\b).*$)|"
    r"(?-i:(?!.*\b(?!etc\b)[a-z]{3,}\b).{0,90}\b[Cc][Aa][Pp]\.\s*\d+\.\d+(?:\.\d+)*\s+\d{1,4}\s*$)|"
    r"(?-i:\d{1,4}\s+[Cc][Aa][Pp]\.\s*\d+\s+(?!.*\b[a-z]{3,}\b).+$)|"
    r"(?-i:(?!.*\b[a-z]{3,}\b).{0,90}\b[Cc][Aa][Pp]\.\s*\d+\s+\d{1,4}\s*$)|"
    r"(?-i:\d{1,4}\s+[Cc]hap\.\s*\d+(?::\d+)?\b(?!.*\b[a-z]{3,}\b).*$)|"
    r"(?-i:\d{1,4}\s+(?:[A-Z][A-Za-z]+(?:\s+|$)){3,12}(?:19|20)\d{2}\s*$)|"
    r"(?-i:(?:[A-Z][A-Za-z]+(?:\s+|$)){3,12}(?:19|20)\d{2}\s+\d{1,4}\s*$)|"
    r"constituci[oó]n pol[ií]tica del per[uú]\s+\d+\s*$|"
    r"\d{1,4}\s+edici[oó]n del congreso\b.*|"
    r"nr\.\s*\d+\s*\].*\[.*|"
    r"st\.?\s*christopher and nevis\s*$|"
    r"official gazette\s+nr\.\s*\d[\d\s/.-]*(?:\s+of\s+[\d/.-]+)?\s*$|"
    r"www\.\S+(?:\s+(?!(?:for|under|and|the|is|of)\b)[A-Za-z][\w.-]{1,24}){1,2}\s*$|"
    r".*laws\.africa\b.*|"
    r".*share widely and freely.*|"
    r".*no copyright on the legislative content.*|"
    r"(?-i:^(?:Malawi|Zambia|Kenya|Uganda|Ghana|Namibia|Botswana|Lesotho|Eswatini|Rwanda|Tanzania|Nigeria|Zimbabwe|Mauritius|Seychelles|Liberia|Gambia)\s+.{0,80}\(Chapter\s+\d+\)\s*$)|"
    r"(?-i:^Act\s+\d+\s+(?:[A-Z][a-z]+\s+){1,6}(?:19|20)\d{2}\s*$)|"
    r"issue\s*:?\s*\d+(?:\.\d+)?\s+page\s+\d+\s+of\s+\d+\b.*|"
    r"issue\s*:\s*\d+(?:\.\d+)?\s+\d+\s+\d{1,2}\s+[a-z]+\s+\d{4}\s*$|"
    r".*edition officielle mise [aà] jour.*|"
    r"code general des impots\s+\d{4}\s*$|"
    r"\d{1,2}\.\d{1,2}\.\d{4}\s*-\s*\d{1,2}\.\d{1,2}\.\d{4}\s*$|"
    r"(?!.*δημοσιευ)(?!.*\bστην\b)(?=.*εφημερ.{0,12}κυβερν)(?=.*(?:τευξ|τεύχ|\(\s*τευ)).{0,140}$|"
    r"(?:\d{1,4}\s+)?επ[ιί]σημη\s+εφημερ[ιί]δ[αά]\b.*|"
    r"sistema integrado de gest[aã]o de finan[cç]as p[uú]blicas\s*\(sigfip\)\s*\d+\s*/\s*\d+\s*$|"
    r"editado por\s*:.*\beditado em\s*:.*|"
    r"issue\s+\d{1,4}\s*$|"
    r"\d{1,4}\s*\|\s*page\s*$|"
    r"page\s*\|\s*\d{1,4}\s*$|"
    r"\{\{[^}\n]*\}\}\s*$|"
    r"lap tetej[eé]re\s*$|"
    r"megnyitottak\s*$|"
    r"jogszab[aá]lykeres[oő]\s*$|"
    r".*slu[zž]beni glasnik\b.{0,50}stranica\s+\d+\s*$|"
    r".*\(unknown\)/ron\b.*|"
    r"\[the next page is\s+[\d,]+\s*\]\s*$|"
    r"service\s+\d+\s+[\d,]+\s*$|"
    r"\[act\s+\d+\s+of\s+\d{4}\s+wef\s+[\d/]+\]\s*$|"
    r"(?:i{1,3}|iv|vi{0,3}|ix|xi{0,3})\s+s[eé]rie\s*-\s*n[uú]mero\s+\d+(?:\s+(?:[a-zç]+-feira|s[aá]bado|domingo),?\s*\d{1,2}\s+de\s*[a-zç]+\s+de\s+\d{4})?\s*$|"
    r"(?:i{1,3}|iv|vi{0,3}|ix|xi{0,3})\s*-?\s*s[eé]rie\b.*\d.*|"
    r"(?:i{1,3}|iv|vi{0,3}|ix|xi{0,3})s[eé]rie\b.*\d.*|"
    r"\d+\s+(?:[a-zç]+-feira|s[aá]bado|domingo),?\s+\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4}(?:\s+p[aá]gina\s+\d+)?\s*$|"
    r"s[eé]rie\s+[ivx]+\s*,\s*nr\.\s*\d+\b.{0,80}p[aá]gina\s+\d+\s*$|"
    r"(?:[a-zç]+-feira|s[aá]bado|domingo),?\s+\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4}\s+s[eé]rie\s+[ivx]+\s*,\s*nr\.\s*\d+\s*$|"
    r"\d+\s*[\(\)]+\s*مذكرة تفسيرية\b.*|"
    r"-\s*\d+\s*-\s*\).*$|"
    r".*constituteproject\.org.*|"
    r"pdf generated\s*:.*|"
    r"[a-z][a-z]+(?:\s+[a-z][a-z]+){0,3}\s+(?:19|20)\d{2}\s+page\s+\d+\s*$|"
    r"الصفحة\s*\.?\s*[0-9٠-٩]+\s*$|"
    r"\[state/territory\]\s*$|"
    r"direction g[eé]n[eé]rale adjointe des imp[oô]ts\s*$|"
    r"et des domaines\s*$|"
    r"rio:\s*\d+\s*$|"
    r"#+\s*journal officiel\b.*|"
    r"journal officiel\s*-\s*banque des?\s*donn[eé]es juridiques\b.*|"
    r"(?!.*\b(?:publie|publi[eé]|shall|entre)\b)journal officiel (?:de la r[eé]publique|du faso)\b.{0,50}$|"
    r"\[(?:\.{3}|…)\]\s*$|"
    r"bsd:\s*\d+\s*$|"
    r"\d{1,2}\.?\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s*$|"
    r"(?-i:(?:[A-Z][A-Za-z]+\s+){1,12}(?:Act|Law|Code),?\s+(?:19|20)\d{2}(?:\s+(?:19|20)\d{2})?\s+nr\.\s*\d+\s+[A-Z]\s+\d+\s*$)|"
    r"(?-i:^[A-Z]\s+\d{1,4}\s+(?:19|20)\d{2}\s+nr\.\s*\d+\s+(?:[A-Z][A-Za-z]+\s+){1,12}(?:Act|Law|Code),?\s+(?:19|20)\d{2}\s*$)|"
    r"printed on the orders? of government\s*\.?\s*$|"
    r".*(?<![A-Za-z])(?:printed|thinted)\b.{0,80}government printing\b.*|"
    r"to be purchased at the govt\.?\s*publications bureau\b.*|"
    r"b\.?\s*l\.?\s*r\.?\s*o\.?\s*\d+\s*/\s*\d{4}\s*$|"
    r"pages authorised\s*$|"
    r"(?:current\s+)?authorised pages\s*$|"
    r"\(inclusive\)\s*by\s+lro\.?\s*$|"
    r"(?-i:(?:[A-Z][a-z]+(?:\s+|$)){1,8}(?:Malawi|Zambia|Kenya|Uganda|Ghana|Namibia|Botswana|Lesotho|Eswatini|Rwanda|Tanzania|Nigeria|Zimbabwe|Mauritius|Seychelles|Liberia|Gambia)\s*$)|"
    r"code\s+\S+(?:\s+\S+){0,6}\s+\d{1,3}/\d{2,3}\s*$|"
    r"index\s*$|"
    r"ministry/program(?:me)?/sub(?:head|program(?:me)?)\s+page\s*$|"
    r"page\s+\d{1,3}\s*/\s*\d{1,3}\s*$|"
    r"\[?\s*printed by authority of the\s*$|"
    r"printed in [a-z][a-z .'-]{0,40}by the government printer\s*$|"
    r"[\w.+-]+@[\w.-]+\.[a-z]{2,}\s+www\.\S+\s*$|"
    r"secr[eé]tariat g[eé]n[eé]ral du gouvernement\s+www\.\S+\s*$|"
    r"site:\s*(?:https?://|www\.)\S+\s*$|"
    r"justice sector support program\s*\(jssp\).*|"
    r"serial number:\s*\d+\b.*|"
    r"copyright government of [a-z]+(?:\s+[a-z]+){0,3}\s*$|"
    r"this page was intentionally left blank\.?\s*$|"
    r"this is page \d+ of \d+\s+pages? of the above table\.?\s*$|"
    r"new provisions(?: in the schedule)? are printed in italics\.?\s*$|"
    r"go to top page(?: next chapter)?\s*$|"
    r"(?:\d{4}\s+)?parliamentary series\s+(?:nr\.|no\.?)\s*\d+\s*$|"
    r"try reloading the page or downloading the pdf\.?\s*$|"
    r"reload page\s*$|"
    r"uploaded by:\s*https?://\S+\s*$|"
    r"t[eé]l[eé]charg[eé] sur www\.\S+\s*$|"
    r"ibirimo/summary/sommaire\b.*|"
    r"website:\s*(?:https?://|www\.)\S+\s*$|"
    r"www\.\S+\s+[\w.+-]+@[\w.-]+\s*$|"
    r"gazette order page\.?\s*$|"
    r"(?:lexis finder|esilec profesional)\s*-\s*www\.\S+\s*$|"
    r"official gazette\s+(?:nr\.|no\.?)\s*(?:special(?:\s+bis)?|\d+\s*bis)\s+of\b.*|"
    r"s[eé]rie\s+[ivxlcdm]+\s*,\s*nr\.\s*\S+(?:\s+[A-Za-z0-9]+)?\s*$|"
    r"unofficial translat(?:ed|ion)\b.*|"
    r"\(?\d[\d\s().-]{6,}\)?\s*\|\s*(?:https?://|www\.)\S+\s*$|"
    r"volume:\s*\d+\s+issue no:\s*\d+\s+government gazette\s*$|"
    r"tonga government gazette supplement\s*$|"
    r"ministry of legal affairs\s+www\.\S+\s*$|"
    r"\d+\s+www\.\S+\s*$|"
    r"www\.\S+\s+\d+\s*/\s*\d+\s*$|"
    r"www\.\S+\s+(?:(?!for\b|is\b|shall\b|the\b)[a-z][a-z .'-]{0,50})$|"
    r".*/type/page>{2,}.*|"
    r"subject\.\s*reference\.\s*page\.?\s*$|"
    r"name reference page no\.?\s*$|"
    r"sl\s*#\s*law\s*#\s*legislation commencement gazette\s*$|"
    r"gn\s*=\s*gazette notice\b.*|"
    r"de blank page\b.*|"
    r"printed and published by the ministry of justice\b.*|"
    r"rarotonga,\s*cook islands:\s*printed under the authority\b.*|"
    r"e-?mail\s*:\s*\S+@\S+.*(?:site web|www\.)\S+.*|"
    r"διεύθυνση στο διαδίκτυο\s*\(url\)\s*:\s*https?://\S+.*|"
    r"spletna stran:\s*www\.\S+\s*$|"
    r"copyright\s*$|"
    r"copyright and designs act\s+\d{4}\s*$|"
    r"copyright act\s+\d{4}\s*$|"
    r"powered by tcpdf\b.*|"
    r"pour l'acquisition de votre abonnement\b.*|"
    r"a\s*bonnement au journal officiel\b.*|"
    r"[eé]dit[eé] par la direction de l'[eé]dition du journal officiel\b.*|"
    r"\[the inclusion of this page is authori[sz]ed by\b.*|"
    r"ins\s*=\s*inserted\b.*|"
    r"[a-z]{2,8}\s*=\s*gazette\b.*|"
    r"site web\s*:\s*www\.\S+\s*$|"
    r"web\s*sites?\s*:?\s*-?\s*www\.\S+\s*$|"
    r".*www\.documents\.gov\.lk\s*$|"
    r"τηλ\.?:?\s*[\d\s,]+φαξ:?\s*[\d\s]+\s*-\s*www\.\S+\s*$|"
    r"das dokument ist einsehbar unter:\s*www\.\S+\s*$|"
    r"sujet articles page\s*$|"
    r"language is printed on uneven numbered pages\.?\s*$|"
    r".*www\.nbs\.sk\.?\s*$|"
    r"\d{2}-\d{4,6}\s+\d{1,3}/\d{1,3}\s*$|"
    r"\d{1,3}/\d{1,3}\s+\d{2}-\d{4,6}\s*$|"
    r"[as]/(?:res|prst)/\d+\s*\(\d{4}\)\s*$|"
    r"ab\s+\d{4},\s*nr\.\s*\d+\s*$|"
    r"grondslag\s*:\s*[.\-–\s]*$|"
    r"رقم الهاتف\s*:.*|"
    r"\+[\u0600-\u06FF]{1,2}\s*$|"
    r"(?-i:(?!.*\b(?:est|sont|doit|shall)\b)(?!.*\b[a-z]{4,}\b).*\bImprimerie\s+[A-Z].*$)|"
    r"(?-i:(?!.*\b(?:shall|is|are|means|under|must)\b).{8,120}\(Chapter\s+\d+(?::\d+)?\)\s+[A-Z][a-z]+\s*$)|"
    r"(?-i:(?!.*\b(?:ACT|LAW|CODE|DECREE|ORDINANCE|CHAPTER|ARTICLE|SECTION|TITLE|PART|SCHEDULE|GENERAL|PROVISIONS|SHORT|INTERPRETATION|PRELIMINARY|AMENDMENT|REPEAL|COMMENCEMENT|DEFINITIONS|REGULATIONS|RULES|ORDER|APPENDIX)\b)(?:[A-ZÁÉÍÓÚÜÑ]{2,}(?:\s+|$)){4,10}\d{1,3}\s*$)|"
    r"(?-i:(?!.*\b(?:ACT|LAW|CODE|DECREE|ORDINANCE|CHAPTER|ARTICLE|SECTION|TITLE|PART|SCHEDULE|GENERAL|PROVISIONS|SHORT|INTERPRETATION|PRELIMINARY|AMENDMENT|REPEAL|COMMENCEMENT|DEFINITIONS|REGULATIONS|RULES|ORDER|APPENDIX)\b)\d{3,4}\s+(?:[A-ZÁÉÍÓÚÜÑ]{3,}(?:\s+|$)){1,3}\s*$)|"
    r"\[\d{1,4}\]?\s*$|"
    r"หน.?า\s+[0-9๐-๙]+\s*$|"
    r"(?:home|blog|contact us|cookie|accueil|startseite|"
    r"página inicial|página principal|επικοινωνία|αρχική)\s*$"
    r")"
)
_CHROME_INLINE_RE = re.compile(
    r"(?i)skip to (?:main )?content|all rights reserved|click here|"
    r"légimonaco"
)
_JA_ART_RE = re.compile(r"第\s*[0-9一二三四五六七八九十百]+\s*[条條]")
_CIRCLED_ART_RE = re.compile(r"[①-⑳⑴-⒇❶-❿⓫-⓴]")
_CJK_ENUM_RE = re.compile(r"(?m)^[ \t]*[一二三四五六七八九十百]+、")
_CJK_PAREN_RE = re.compile(r"(?m)^[ \t]*[（(][一二三四五六七八九十百]+[）)]")
_CJK_DIGIT_ENUM_RE = re.compile(r"(?m)^[ \t]*[0-9０-９]+、")
_KO_GA_RE = re.compile(r"(?m)^[ \t]*[가나다라마바사아자차카타파하]\.")
_JA_KATA_ENUM_RE = re.compile(r"(?m)^[ \t]*[アイウエオカキクケコ]、")
_HANGUL_GA = "가나다라마바사아자차카타파하"
_KATA_ENUM = "アイウエオカキクケコ"
_AR_ABJAD_INDEX = {
    "أ": "1", "ا": "1", "ب": "2", "ج": "3", "د": "4", "ه": "5",
    "و": "6", "ز": "7", "ح": "8", "ط": "9", "ي": "10",
}
_HE_ALEF = "אבגדהוזחטי"
_TH_KO = "กขคงจฉชซฌญ"
_AR_ABJAD_RE = re.compile(r"(?m)^[ \t]*[(\[]?[أابجدهوزحطي][)\]]?\s*[-.)]")
_HE_ALEF_RE = re.compile(r"(?m)^[ \t]*[אבגדהוזחטי]\.")
_HE_PEREK_RE = re.compile(r"(?m)^[ \t]*פרק\s+[א-ת]{1,3}['׳]?")
_HE_SIMAN_RE = re.compile(r"(?m)^[ \t]*סימן\s+[א-ת]{1,3}['׳]?")
_HE_HELEK_RE = re.compile(r"(?m)^[ \t]*חלק\s+[א-ת]{1,3}['׳]?")
_HE_TOS_RE = re.compile(
    r"(?m)^[ \t]*תוספת\s+(?:ראשונה|שנייה|שניה|שלישית|רביעית|חמישית|שישית|[א-ת]['׳]?|[0-9]+)"
)
_HE_TAKANA_RE = re.compile(r"(?m)^[ \t]*תקנה\s+[0-9]+")
_AR_ANNEX_RE = re.compile(r"(?m)^[ \t]*ملحق(?:\s*رقم)?\s*[0-9٠-٩()]+")
_AR_BAB_RE = re.compile(
    r"(?m)^[ \t]*الباب\s+(?:[0-9٠-٩]+|" + _AR_ORD_M + r"|" + _AR_ORD + r")"
)
_AR_FASL_RE = re.compile(
    r"(?m)^[ \t]*الفصل\s+(?:[0-9٠-٩]+|" + _AR_ORD_M + r"|" + _AR_ORD + r")"
)
_AR_KITAB_RE = re.compile(
    r"(?m)^[ \t]*الكتاب\s+(?:[0-9٠-٩]+|" + _AR_ORD_M + r"|" + _AR_ORD + r")"
)
_AR_FARA_RE = re.compile(
    r"(?m)^[ \t]*الفرع\s+(?:[0-9٠-٩]+|" + _AR_ORD_M + r"|" + _AR_ORD + r")"
)
_FA_BAND_RE = re.compile(r"بند\s*[0-9۰-۹]+")
_CJK_ZHANG_RE = re.compile(r"第\s*[一二三四五六七八九十百千万零〇两0-9]+\s*章")
_KO_JANG_RE = re.compile(r"제\s*[0-9]+\s*장")
_TA_ART_RE = re.compile(r"பிரிவு\s*[0-9௦-௯]+")
_TE_ART_RE = re.compile(r"ప్రకరణ(?:ము)?\s*[0-9౦-౯]+")
_KN_ART_RE = re.compile(r"ಪ್ರಕರಣ\s*[0-9೦-೯]+")
_GU_ART_RE = re.compile(r"કલમ\s*[0-9૦-૯]+")
_PA_ART_RE = re.compile(r"ਧਾਰਾ\s*[0-9੦-੯]+")
_ML_ART_RE = re.compile(r"വകുപ്പ്\s*[0-9൦-൯]+")
_CJK_BIAN_RE = re.compile(r"第\s*[一二三四五六七八九十百千万零〇两0-9]+\s*[编編]")
_KO_PYEON_RE = re.compile(r"제\s*[0-9]+\s*편")
_TH_LAK_RE = re.compile(r"(?m)^[ \t]*ลักษณะ\s*[0-9๐-๙]+")
_KM_CHAP_RE = re.compile(r"ជំពូក\s*[0-9០-៩]+")
_LO_PART_RE = re.compile(r"ພາກ\s*[0-9໐-໙]+")
_MY_CHAP_RE = re.compile(r"အခန်း\s*[0-9၀-၉]+")
_KA_CHAP_RE = re.compile(r"თავი\s+[IVXLCDM0-9]+")
_HY_CHAP_RE = re.compile(r"Գլուխ\s+[IVXLCDM0-9]+", re.IGNORECASE)
_AM_CHAP_RE = re.compile(r"ምዕራፍ\s*[0-9፩-፻]+")
_HI_CHAP_RE = re.compile(r"अध्याय\s*[0-9०-९]+")
_BN_CHAP_RE = re.compile(r"অধ্যায়\s*[0-9০-৯]+")
_UR_CHAP_RE = re.compile(r"باب\s*[0-9۰-۹]+")
_FA_FASL_RE = re.compile(r"فصل\s*[0-9۰-۹]+")
_NE_CHAP_RE = re.compile(r"परिच्छेद\s*[0-9०-९]+")
_CJK_JIE_RE = re.compile(r"第\s*[一二三四五六七八九十百千万零〇两0-9]+\s*[节節]")
_KO_JEOL_RE = re.compile(r"제\s*[0-9]+\s*절")
_TH_TON_RE = re.compile(r"(?m)^[ \t]*ตอน\s*[0-9๐-๙]+")
_SR_PART_RE = re.compile(r"(?:Одељак|ОДЕЉАК)\s+[IVXLCDM0-9]+", re.IGNORECASE)
_RU_TITLE_RE = re.compile(
    r"(?:Раздел|РАЗДЕЛ|Розділ|РОЗДІЛ|Раздзел|РАЗДЗЕЛ)\s+[IVXLCDM0-9]+",
    re.IGNORECASE,
)
_RU_CHAP_RE = re.compile(r"(?:Глава|ГЛАВА)\s+[IVXLCDM0-9]+", re.IGNORECASE)
_TH_KO_RE = re.compile(r"(?m)^[ \t]*[กขคงจฉชซฌญ]\.")
_HI_DIGIT_ENUM_RE = re.compile(r"(?m)^[ \t]*[०-९]+\s*[.।]")
_BN_DIGIT_ENUM_RE = re.compile(r"(?m)^[ \t]*[০-৯]+\s*[.।]")
_CYR_AB = "абвгдежзийк"
_EL_AB = "αβγδεζηθικ"
_KA_AB = "აბგდევზთიკლ"
_HY_AB = "աբգդեզէըթժ"
_CYR_AB_RE = re.compile(r"(?im)^[ \t]*[абвгдежзийк]\s*[).]")
_EL_AB_RE = re.compile(r"(?im)^[ \t]*[αβγδεζηθικ]\s*[).]")
_KA_AB_RE = re.compile(r"(?m)^[ \t]*[აბგდევზთიკლ]\s*[).]")
_HY_AB_RE = re.compile(r"(?m)^[ \t]*[աբգդեզէըթժ]\s*[).]")
_MARK_AFTER = r"(?:\s+|(?=[^\x00-\x7f]))"
_LATIN_LETTER_RE = re.compile(
    r"(?m)^[ \t]*(?:\(\s*(?P<paren>[a-z])\s*\)|(?P<bare>[a-z])\)|"
    r"(?P<roman>viii|iii|vii|ii|iv|ix|vi|i|v|x)\.)"
    + _MARK_AFTER
)
_BULLET_RE = re.compile(r"(?m)^[ \t]*[•·●‣⁃*#]\s+")
_DASH_NUM_RE = re.compile(r"(?m)^[ \t]*-\s*(?P<bn>[0-9]{1,3})\s+(?=[^\W\d_])")
_LATIN_NUM_LIST_RE = re.compile(
    r"(?m)^[ \t]*(?:"
    r"\(\s*(?P<nparen>[0-9]{1,3})\s*\)|"
    r"(?P<nclose>[0-9]{1,3})\)|"
    r"(?P<nord>[0-9]{1,3})[º°o]|"
    r"(?P<ndot>[0-9]{1,3})\.-|"
    r"(?P<ncolon>[0-9]{1,3}):|"
    r"(?P<ndash>[0-9]{1,3})-|"
    r"(?P<dbl>([a-z])\2)\)"
    r")"
    + _MARK_AFTER
)
_ROMAN_LOWER = {
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "x": "10",
    "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9",
}
_JA_KOU_RE = re.compile(r"第[0-9一二三四五六七八九十百]+項")
_ZH_KUAN_RE = re.compile(r"第[一二三四五六七八九十百千万零〇两0-9]+款")
_KO_ART_RE = re.compile(r"제\s*[0-9]+\s*조")
_KO_HANG_RE = re.compile(r"제\s*[0-9]+\s*항")
_KO_HO_RE = re.compile(r"제\s*[0-9]+\s*호")
_TH_PARA_RE = re.compile(r"วรรค\s*[0-9๐-๙]+")
_TH_KHO_RE = re.compile(r"(?m)^[ \t]*ข้อ\s*[0-9๐-๙]+")
_TH_HUAT_RE = re.compile(r"(?m)^[ \t]*หมวด\s*[0-9๐-๙]+")
_FA_TAB_RE = re.compile(r"تبصره\s*[0-9۰-۹]+")
_HE_PARA_RE = re.compile(r"פסקה\s*[0-9]+")
_AR_PARA_RE = re.compile(r"الفقرة\s*[0-9٠-٩]+")
_AR_QARAR_RE = re.compile(r"قرار(?:\s*رقم)?\s*[0-9٠-٩]+")
_AR_DECREE_RE = re.compile(r"(?:مرسوم|أمر)(?:\s*رقم)?\s*[0-9٠-٩]+")
_RU_INST_RE = re.compile(r"(?:Указ|Постановление|Приказ)\s+[0-9]+", re.IGNORECASE)
_KO_RANGE_RE = re.compile(
    r"제\s*[0-9]+\s*조\s*부터\s*제\s*[0-9]+\s*조(?:까지)?"
)
_HE_ART_RE = re.compile(
    r"(?:סעיף\s*(?:[0-9]+|(?!קטן)[א-ת]{1,3}['׳]?)|\.\s*[0-9]+(?=[\u0590-\u05FF]))"
)
_HE_KATAN_RE = re.compile(r"סעיף\s+קטן\s*\(?\s*[א-ת]'?\)?")
_TH_ART_RE = re.compile(r"มาตรา\s*[0-9๐-๙]+")
_HI_ART_RE = re.compile(r"(?:धारा|ধারা)\s*[0-9০-৯]+")
_RU_ART_RE = re.compile(r"(?:Статья|СТАТЬЯ|Стаття|СТАТТЯ)\s+[0-9]+(?:-[0-9]+)?", re.IGNORECASE)
_KA_ART_RE = re.compile(r"მუხლი\s*[0-9]+")
_HY_ART_RE = re.compile(r"Հոդված\s*[0-9]+", re.IGNORECASE)
_AM_ART_RE = re.compile(r"አንቀጽ\s*[0-9፩-፻]+")
_BN_ART_RE = re.compile(r"ধারা\s*[0-9০-৯]+")
_LO_ART_RE = re.compile(r"ມາດຕາ\s*[0-9໐-໙]+")
_KM_ART_RE = re.compile(r"មាត្រា\s*[0-9០-៩]+")
_MY_ART_RE = re.compile(r"ပုဒ်မ\s*[0-9၀-၉]+")
_UZ_ART_RE = re.compile(r"[0-9]+\s*-\s*(?:модда|modda)", re.IGNORECASE)
_MN_ART_RE = re.compile(r"[0-9]+\s*(?:дүгээр|дугаар)\s*зүйл", re.IGNORECASE)
_KK_ART_RE = re.compile(r"[0-9]+\s*-?\s*бап", re.IGNORECASE)
_NE_ART_RE = re.compile(r"दफा\s*[0-9०-९]+")
_TI_ART_RE = re.compile(r"ዓንቀጽ\s*[0-9፩-፻]+")
_BO_ART_RE = re.compile(r"དོན་ཚན་\s*[0-9༠-༩]+")
_UG_ART_RE = re.compile(r"ماددا\s*[0-9۰-۹]+")
_AR_POINT_RE = re.compile(r"(?m)^[ \t]*(?:أولا|ثانيا|ثالثا|رابعا|خامسا)\s*[:/]")
_AR_POINT_NUM = (("أولا", "1"), ("ثانيا", "2"), ("ثالثا", "3"), ("رابعا", "4"), ("خامسا", "5"))
_SI_ART_RE = re.compile(r"වගන්තිය\s*[0-9෦-෯]+")
_UR_ART_RE = re.compile(r"دفعہ\s*[0-9۰-۹]+")
_KY_ART_RE = re.compile(r"[0-9]+\s*-?\s*берене", re.IGNORECASE)
_BE_ART_RE = re.compile(r"Артыкул\s*[0-9]+", re.IGNORECASE)

# "A R T Í C U L O 86" / "C A P I T U L O I" → ARTÍCULO 86 / CAPITULO I
_SPACED_KEYWORD_RE = re.compile(
    r"(?iu)\b((?:[A-ZÁÉÍÓÚÜÑÀÈÌÒÙÂÊÎÔÛÄËÏÖÜÃÕÇ]\s+){3,}"
    r"[A-ZÁÉÍÓÚÜÑÀÈÌÒÙÂÊÎÔÛÄËÏÖÜÃÕÇ])\b"
    r"(?=\s*[.:\-–—]?\s*[0-9IVXLCDM])"
)


def _squeeze_spaced_keyword(match: re.Match[str]) -> str:
    return re.sub(r"\s+", "", match.group(1))


_ZW_RE = re.compile(
    r"[\ufeff\u200b\u200c\u200d\u00ad\u2060\u200e\u200f\u202a-\u202e\u2066-\u2069]"
)
# Tashkeel, niqqud, Latin combining. Keep Thai/Lao/Khmer/Myanmar/Indic Mn.
_STRIP_MARKS_RE = re.compile(
    "["
    "\u0300-\u036f"
    "\u0483-\u0489"
    "\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7"
    "\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed"
    "\u08d3-\u08e1\u08e3-\u08ff"
    "]"
)
_SCRIPT_CITE_TAIL_RE = re.compile(
    r"(?i)^\s*(?:"
    r"من\s*(?:الدستور|القانون|الأمر|المرسوم|القرار)|"
    r"của\s+luật|"
    r"של\s+(?:חוק|פקודה)"
    r")"
)

# UTF-8 read as Latin-1: Â§ (U+00C2 U+00A7) is §, Ã© is é. Âmbito stays.
_LATIN1_UTF8_RE = re.compile(r"[\u00c2\u00c3][\u0080-\u00bf]")


def _repair_latin1_utf8(text: str) -> str:
    if "\u00c2" not in text and "\u00c3" not in text:
        return text

    def repl(match: re.Match[str]) -> str:
        try:
            return match.group(0).encode("latin-1").decode("utf-8")
        except UnicodeDecodeError:
            return match.group(0)

    return _LATIN1_UTF8_RE.sub(repl, text)


# Script-tagged gazettes that still publish English Article/Section translations.
_LATIN_FALLBACK_LANGS = frozenset(
    {"ka", "km", "hy", "am", "lo", "my", "si", "th", "he", "ne", "fa"}
)


class _HTMLText(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag in {"br", "p", "tr", "div", "li", "h1", "h2", "h3"} and self.skip == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in {"p", "div", "li", "tr"} and self.skip == 0:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip == 0:
            self.parts.append(data)


def has_html_tags(text: str) -> bool:
    return bool(text and _HAS_TAG_RE.search(text))


def strip_html(raw: str) -> str:
    """Turn leftover HTML into visible legal text. No-op if there are no tags."""
    if not raw or not _HAS_TAG_RE.search(raw):
        return raw
    parser = _HTMLText()
    try:
        parser.feed(raw)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        text = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
        text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html_lib.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_ROMAN_PAGE_RE = re.compile(
    r"(?i)(?:i{1,3}|iv|vi{0,3}|ix|xi{0,3}|xiv|xv)$"
)


def _is_roman_page_line(line: str, nxt: str) -> bool:
    """A lone i/ii/iii between blocks is a page stamp, not a list item."""
    if _ROMAN_PAGE_RE.fullmatch(line.strip()) is None:
        return False
    nxt = nxt.strip()
    if not nxt:
        return True
    return not (nxt[:1].islower() or nxt.startswith("("))


def _is_page_num_line(line: str) -> bool:
    token = line.strip()
    if 1 <= len(token) <= 4 and all(unicodedata.category(ch) == "Nd" for ch in token):
        return True
    # "1/3" between paragraphs is page 1 of 3, not a section.
    parts = token.split("/")
    if len(parts) == 2 and all(part.isascii() and part.isdigit() for part in parts):
        left, right = int(parts[0]), int(parts[1])
        return 1 <= left <= right <= 30
    return False


def _is_facing_page_line(line: str) -> bool:
    """'736 737' between blocks is a two-page spread, not a citation."""
    parts = line.split()
    if len(parts) != 2 or not all(part.isascii() and part.isdigit() for part in parts):
        return False
    left, right = int(parts[0]), int(parts[1])
    return 100 <= left and right == left + 1 and right <= 9999


_PAGE_OF_RE = re.compile(r"(?i)(\d{1,2})\s+of\s+(\d{1,2})")


def _is_page_of_line(line: str) -> bool:
    """'3 of 5' between blocks is a page count, not a citation."""
    match = _PAGE_OF_RE.fullmatch(line.strip())
    if match is None:
        return False
    left, right = int(match.group(1)), int(match.group(2))
    return 1 <= left <= right <= 30


def learned_patterns_path() -> Path:
    override = os.environ.get("COUNTRY_LAWS_LEARNED_PATTERNS")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "data" / "learned_line_patterns.json"


_LEARNED: tuple[float, re.Pattern[str] | None] | None = None


def learned_line_pattern() -> re.Pattern[str] | None:
    """Whole-line rules added by the normalize loop. Compiled once per file change."""
    global _LEARNED
    path = learned_patterns_path()
    if not path.is_file():
        return None
    mtime = path.stat().st_mtime
    if _LEARNED is not None and _LEARNED[0] == mtime:
        return _LEARNED[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _LEARNED = (mtime, None)
        return None
    parts: list[str] = []
    for item in payload.get("patterns") or []:
        if not isinstance(item, str):
            continue
        try:
            re.compile(item, re.IGNORECASE)
        except re.error:
            continue
        parts.append(item)
    compiled = re.compile("|".join(f"(?:{part})" for part in parts), re.IGNORECASE) if parts else None
    _LEARNED = (mtime, compiled)
    return compiled


def strip_chrome_lines(text: str) -> str:
    """Drop gazette-site chrome lines. Never invents replacement legal text."""
    if not text:
        return ""
    raw_lines = text.splitlines()
    multi = sum(1 for ln in raw_lines if ln.strip()) > 1
    learned = learned_line_pattern()
    kept = []
    for idx, ln in enumerate(raw_lines):
        stripped = ln.strip()
        if not stripped:
            continue
        if _CHROME_LINE_RE.match(stripped) or _CHROME_INLINE_RE.search(ln):
            continue
        if learned is not None and learned.match(stripped):
            continue
        # A lone "2" or "10" is an article number. The same token inside a
        # longer page is a page stamp.
        if multi and (
            _is_page_num_line(stripped)
            or _is_facing_page_line(stripped)
            or _is_page_of_line(stripped)
        ):
            continue
        nxt = ""
        for later in raw_lines[idx + 1 :]:
            if later.strip():
                nxt = later
                break
        if multi and _is_roman_page_line(stripped, nxt):
            continue
        kept.append(ln)
    return "\n".join(kept).strip()


_HYPHEN_BREAK_RE = re.compile(r"(?<=[^\W\d_])-[ \t]*\n+[ \t]*([^\W\d_])")


def _join_hyphen_breaks(text: str) -> str:
    """Join a hyphenated word split across lines. Leave a following capital header."""

    def repl(match: re.Match[str]) -> str:
        nxt = match.group(1)
        if nxt.isupper():
            return match.group(0)
        return nxt

    return _HYPHEN_BREAK_RE.sub(repl, text)


def normalize_legal_text(value: Any) -> str:
    """NFKC + HTML strip. Keeps newlines so heading detection still works."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).replace("\x00", "")
    if text.startswith("ÿþ") or text.startswith("þÿ"):
        text = text[2:]
    text = re.sub(r"[\x00-\x08\x0b\x0e-\x1f\x7f]", " ", text)
    text = text.replace("\ufffd", " ")
    text = re.sub(r"[\ue000-\uf8ff]", "", text)
    text = _repair_latin1_utf8(text)
    text = re.sub(r"\(cid:\d+\)", " ", text)
    text = _ZW_RE.sub("", text).replace("ـ", "")
    text = _STRIP_MARKS_RE.sub("", text)
    text = re.sub(r"[\u2010-\u2015\u2212\ufe58\ufe63\uff0d]", "-", text)
    text = re.sub(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]", " ", text)
    text = text.replace("\u2028", "\n").replace("\u2029", "\n").replace("\f", "\n")
    text = _join_hyphen_breaks(text)
    text = _NUMERO_FOLD_RE.sub("nr. ", text)
    text = re.sub(r"المادة\s*-\s*اختر\s*-\s*", "", text)
    text = re.sub(r"(?m)^[ \t]*©+\s*", "", text)
    text = re.sub(r"\b((?:19|20)\d{2}) \1\b", r"\1", text)
    text = re.sub(r"(?<=[A-Za-z])!+(?=\d)", " ", text)
    text = re.sub(r":!+", ":", text)
    text = re.sub(r"(?m)!+\s*$", "", text)
    text = _SPACED_KEYWORD_RE.sub(_squeeze_spaced_keyword, text)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = strip_html(text)
    text = html_lib.unescape(text).replace("\xa0", " ")
    text = re.sub(r"_{3,}", " ", text)
    text = re.sub(r"\.{4,}", " ", text)
    text = re.sub(r"(?m)^[ \t]*#{1,6}[ \t]+", "", text)
    text = strip_chrome_lines(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"~\$\S{0,16}", " ", text)
    text = re.sub(r"\*\*([^*]{1,80})\*\*", r"\1", text)
    text = re.sub(r"__([^_]{1,80})__", r"\1", text)
    text = re.sub(r"'{3}([^']{1,80})'{3}", r"\1", text)
    text = re.sub(r"^={2,6}\s*(.+?)\s*={2,6}\s*$", r"\1", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = _join_hyphen_breaks(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@dataclass
class StructureUnit:
    kind: str
    number: str
    heading: str
    body: str
    title_number: str = ""
    chapter_number: str = ""
    part_number: str = ""
    article_number: str = ""
    section_number: str = ""
    subsections: tuple[str, ...] = ()
    hierarchy_path: str = ""
    char_start: int = 0
    char_end: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "number": self.number,
            "heading": self.heading,
            "body": self.body,
            "title_number": self.title_number,
            "chapter_number": self.chapter_number,
            "part_number": self.part_number,
            "article_number": self.article_number,
            "section_number": self.section_number,
            "subsections": list(self.subsections),
            "hierarchy_path": self.hierarchy_path,
            "char_start": self.char_start,
            "char_end": self.char_end,
        }


def _cursor_path(cursor: dict[str, str]) -> str:
    parts = []
    for key, label in (
        ("title", "Title"),
        ("chapter", "Chapter"),
        ("part", "Part"),
        ("article", "Article"),
        ("section", "Section"),
    ):
        value = cursor.get(key) or ""
        if value:
            parts.append(f"{label} {value}")
    return " > ".join(parts)


def _subsection_tokens(text: str) -> tuple[str, ...]:
    seen: list[str] = []
    for match in _SUBSECTION_RE.finditer(text):
        token = match.group(1)
        if token not in seen:
            seen.append(token)
        if len(seen) >= 40:
            break
    return tuple(seen)


def check_exclusive_cover(text: str, units: list[StructureUnit]) -> bool:
    """True iff units are contiguous, non-overlapping, and cover *text* exactly."""
    if not units:
        return not text
    ordered = sorted(units, key=lambda u: u.char_start)
    if ordered[0].char_start != 0 or ordered[-1].char_end != len(text):
        return False
    prev = 0
    for unit in ordered:
        if unit.char_start != prev or unit.char_end < unit.char_start:
            return False
        if text[unit.char_start : unit.char_end] != unit.body:
            return False
        prev = unit.char_end
    return True


def _script_regex(language: str):
    from .profiles import iso_lang

    lang = iso_lang(language)
    if lang in {"zh", "zh-cn", "zh-tw"}:
        return _ZH_ART_RE
    if lang == "ar":
        return _AR_ART_RE
    if lang == "fa":
        return _FA_ART_RE
    if lang == "ja":
        return _JA_ART_RE
    if lang == "ko":
        return _KO_ART_RE
    if lang == "he":
        return _HE_ART_RE
    if lang == "th":
        return _TH_ART_RE
    if lang == "hi":
        return _HI_ART_RE
    if lang == "bn":
        return _BN_ART_RE
    if lang in {"ru", "uk", "be"}:
        return _RU_ART_RE
    if lang == "ka":
        return _KA_ART_RE
    if lang == "hy":
        return _HY_ART_RE
    if lang == "am":
        return _AM_ART_RE
    if lang == "ti":
        return _TI_ART_RE
    if lang == "bo":
        return _BO_ART_RE
    if lang == "ug":
        return _UG_ART_RE
    if lang == "lo":
        return _LO_ART_RE
    if lang == "km":
        return _KM_ART_RE
    if lang == "my":
        return _MY_ART_RE
    if lang == "uz":
        return _UZ_ART_RE
    if lang == "mn":
        return _MN_ART_RE
    if lang == "kk":
        return _KK_ART_RE
    if lang == "ne":
        return _NE_ART_RE
    if lang == "si":
        return _SI_ART_RE
    if lang == "ta":
        return _TA_ART_RE
    if lang == "te":
        return _TE_ART_RE
    if lang == "kn":
        return _KN_ART_RE
    if lang == "gu":
        return _GU_ART_RE
    if lang == "pa":
        return _PA_ART_RE
    if lang == "ml":
        return _ML_ART_RE
    if lang == "ur":
        return _UR_ART_RE
    if lang == "ky":
        return _KY_ART_RE
    if lang == "be":
        return _BE_ART_RE
    return None


def _detected_script_regexes(text: str, language: str) -> list:
    found: list = []
    primary = _script_regex(language)
    if primary is not None:
        found.append(primary)
    if re.search(r"[①-⑳⑴-⒇❶-❿⓫-⓴]", text):
        found.append(_CIRCLED_ART_RE)
    if re.search(r"[\u4e00-\u9fff]", text):
        found.extend((_ZH_ART_RE, _JA_ART_RE, _ZH_KUAN_RE, _JA_KOU_RE, _CJK_ZHANG_RE, _CJK_BIAN_RE, _CJK_JIE_RE, _CJK_ENUM_RE, _CJK_PAREN_RE, _CJK_DIGIT_ENUM_RE))
    if re.search(r"[\uac00-\ud7af]", text):
        found.extend((_KO_ART_RE, _KO_HANG_RE, _KO_HO_RE, _KO_GA_RE, _KO_JANG_RE, _KO_PYEON_RE, _KO_JEOL_RE))
    if re.search(r"[\u30a0-\u30ff]", text):
        found.append(_JA_KATA_ENUM_RE)
    if re.search(r"[\u0600-\u06ff]", text):
        found.extend((
            _AR_ART_RE, _FA_ART_RE, _FA_TAB_RE, _FA_BAND_RE, _FA_FASL_RE, _AR_PARA_RE, _AR_QARAR_RE, _AR_DECREE_RE,
            _AR_ABJAD_RE, _AR_ANNEX_RE, _AR_BAB_RE, _AR_FASL_RE, _AR_KITAB_RE, _AR_FARA_RE, _UR_CHAP_RE, _UG_ART_RE, _AR_POINT_RE,
        ))
    if re.search(r"[\u0590-\u05ff]", text):
        found.extend((
            _HE_ART_RE, _HE_PARA_RE, _HE_ALEF_RE, _HE_PEREK_RE, _HE_SIMAN_RE,
            _HE_HELEK_RE, _HE_TOS_RE, _HE_TAKANA_RE, _HE_KATAN_RE,
        ))
    if re.search(r"[\u0e00-\u0e7f]", text):
        found.extend((_TH_ART_RE, _TH_PARA_RE, _TH_KO_RE, _TH_KHO_RE, _TH_HUAT_RE, _TH_LAK_RE, _TH_TON_RE))
    if re.search(r"[\u0900-\u097f]", text):
        found.extend((_HI_ART_RE, _HI_DIGIT_ENUM_RE, _HI_CHAP_RE, _NE_CHAP_RE))
    if re.search(r"[\u0980-\u09ff]", text):
        found.extend((_BN_ART_RE, _BN_DIGIT_ENUM_RE, _BN_CHAP_RE))
    if re.search(r"[\u0b80-\u0bff]", text):
        found.append(_TA_ART_RE)
    if re.search(r"[\u0c00-\u0c7f]", text):
        found.append(_TE_ART_RE)
    if re.search(r"[\u0c80-\u0cff]", text):
        found.append(_KN_ART_RE)
    if re.search(r"[\u0a80-\u0aff]", text):
        found.append(_GU_ART_RE)
    if re.search(r"[\u0a00-\u0a7f]", text):
        found.append(_PA_ART_RE)
    if re.search(r"[\u0d00-\u0d7f]", text):
        found.append(_ML_ART_RE)
    if re.search(r"[\u0e80-\u0eff]", text):
        found.extend((_LO_ART_RE, _LO_PART_RE))
    if re.search(r"[\u1780-\u17ff]", text):
        found.extend((_KM_ART_RE, _KM_CHAP_RE))
    if re.search(r"[\u1000-\u109f]", text):
        found.extend((_MY_ART_RE, _MY_CHAP_RE))
    if re.search(r"[\u1200-\u137f]", text):
        found.extend((_AM_ART_RE, _AM_CHAP_RE, _TI_ART_RE))
    if re.search(r"[\u0f00-\u0fff]", text):
        found.append(_BO_ART_RE)
    if re.search(r"[\u10a0-\u10ff]", text):
        found.extend((_KA_ART_RE, _KA_AB_RE, _KA_CHAP_RE))
    if re.search(r"[\u0530-\u058f]", text):
        found.extend((_HY_ART_RE, _HY_AB_RE, _HY_CHAP_RE))
    if re.search(r"[\u0400-\u04ff]", text):
        found.extend((_CYR_AB_RE, _RU_TITLE_RE, _RU_CHAP_RE, _SR_PART_RE))
    if re.search(r"[\u0370-\u03ff]", text):
        found.append(_EL_AB_RE)
    if "модда" in text.casefold() or re.search(r"\bmodda\b", text, re.IGNORECASE):
        found.append(_UZ_ART_RE)
    if re.search(r"зүйл", text, re.IGNORECASE):
        found.append(_MN_ART_RE)
    if re.search(r"бап", text, re.IGNORECASE):
        found.append(_KK_ART_RE)
    if "दफा" in text:
        found.append(_NE_ART_RE)
    if "परिच्छेद" in text:
        found.append(_NE_CHAP_RE)
    if "වගන්තිය" in text:
        found.append(_SI_ART_RE)
    if "دفعہ" in text:
        found.append(_UR_ART_RE)
    if re.search(r"берене", text, re.IGNORECASE):
        found.append(_KY_ART_RE)
    if re.search(r"артыкул", text, re.IGNORECASE):
        found.append(_BE_ART_RE)
    if re.search(r"статья|стаття", text, re.IGNORECASE):
        found.append(_RU_ART_RE)
    if re.search(r"указ|постановление|приказ", text, re.IGNORECASE):
        found.append(_RU_INST_RE)
    # Preserve order, drop duplicate pattern objects.
    out: list = []
    seen: set[int] = set()
    for regex in found:
        key = id(regex)
        if key not in seen:
            seen.add(key)
            out.append(regex)
    return out


def _lexicon_heading_re() -> re.Pattern[str]:
    """Heading matcher generated from HEADING_LEXICON so new languages are data."""
    global _LEXICON_HEADING_RE, _LEXICON_KIND
    if _LEXICON_HEADING_RE is not None:
        return _LEXICON_HEADING_RE
    from .profiles import HEADING_LEXICON

    words: list[str] = []
    kinds: dict[str, str] = {}
    for token, hits in HEADING_LEXICON.items():
        token = (token or "").strip()
        if len(token) < 2:
            continue
        kinds_found = [kind for kind, _lang in hits if kind in {"article", "section", "title", "chapter", "part"}]
        if not kinds_found:
            continue
        folded = _latin_fold(token)
        words.append(folded)
        kinds[folded.casefold()] = kinds_found[0]
    words.sort(key=len, reverse=True)
    escaped = [re.escape(w) for w in words]
    _LEXICON_HEADING_RE = re.compile(
        _latin_fold(
        r"(?im)" + _HEADING_START + r"(?:l['’])?(?P<lex>"
        + "|".join(escaped)
        + r")(?![A-Za-z])(?:\s*(?:n\.?[o°º”'“*´`]|nr|no)\.?\s*)?\s*[.\s:–—-]*\(?\s*(?P<lex_n>"
        + _ARTICLE_N
        + r")\)?"
        )
    )
    _LEXICON_KIND = kinds
    return _LEXICON_HEADING_RE


def _plausible_cw_number(raw: str) -> bool:
    """Drop year-like '1902. Amendment' titles from keyword-less numbering."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return False
    value = int(digits)
    if value <= 0 or value > 2000:
        return False
    if 1800 <= value <= 2099:
        return False
    return True


def _fold_digits_in_number(raw: str) -> str:
    """Map Nd digits (١, १, ๑, …) to ASCII so retrieval numbers stay decimal."""
    if not raw:
        return raw
    out: list[str] = []
    changed = False
    for ch in raw:
        if unicodedata.category(ch) == "Nd":
            digit = unicodedata.digit(ch)
            if digit is not None:
                mapped = str(digit)
                out.append(mapped)
                if mapped != ch:
                    changed = True
                continue
        out.append(ch)
    return "".join(out) if changed else raw


def _unicode_digit_runs(text: str) -> list[str]:
    """ASCII-fold Nd runs (Thai ๑, Myanmar ၁, Arabic-Indic, …)."""
    runs: list[str] = []
    cur: list[str] = []
    for char in text:
        if unicodedata.category(char) == "Nd":
            cur.append(str(unicodedata.digit(char)))
        elif cur:
            runs.append("".join(cur))
            cur = []
    if cur:
        runs.append("".join(cur))
    return runs


_AR_ORDINAL_NUM = (
    ("الحادية عشرة", "11"),
    ("الثانية عشرة", "12"),
    ("الثالثة عشرة", "13"),
    ("الرابعة عشرة", "14"),
    ("الخامسة عشرة", "15"),
    ("السادسة عشرة", "16"),
    ("السابعة عشرة", "17"),
    ("الثامنة عشرة", "18"),
    ("التاسعة عشرة", "19"),
    ("الحادية والعشرون", "21"),
    ("الثانية والعشرون", "22"),
    ("الثالثة والعشرون", "23"),
    ("الرابعة والعشرون", "24"),
    ("الخامسة والعشرون", "25"),
    ("السادسة والعشرون", "26"),
    ("السابعة والعشرون", "27"),
    ("الثامنة والعشرون", "28"),
    ("التاسعة والعشرون", "29"),
    ("العشرون", "20"),
    ("الأولى", "1"),
    ("الأولي", "1"),
    ("األولى", "1"),
    ("الاولى", "1"),
    ("الثانية", "2"),
    ("الثالثة", "3"),
    ("الرابعة", "4"),
    ("الخامسة", "5"),
    ("السادسة", "6"),
    ("السابعة", "7"),
    ("الثامنة", "8"),
    ("التاسعة", "9"),
    ("العاشرة", "10"),
    ("الأول", "1"),
    ("الاول", "1"),
    ("الثاني", "2"),
    ("الثالث", "3"),
    ("الرابع", "4"),
    ("الخامس", "5"),
    ("السادس", "6"),
    ("السابع", "7"),
    ("الثامن", "8"),
    ("التاسع", "9"),
    ("العاشر", "10"),
)
_HE_VALUES = {
    "א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8, "ט": 9,
    "י": 10, "כ": 20, "ך": 20, "ל": 30, "מ": 40, "ם": 40, "נ": 50, "ן": 50,
    "ס": 60, "ע": 70, "פ": 80, "ף": 80, "צ": 90, "ץ": 90, "ק": 100,
    "ר": 200, "ש": 300, "ת": 400,
}
_HE_ORDINAL_NUM = (
    ("ראשונה", "1"),
    ("שנייה", "2"),
    ("שניה", "2"),
    ("שלישית", "3"),
    ("רביעית", "4"),
    ("חמישית", "5"),
    ("שישית", "6"),
)
_ETH_VALUES = {
    "፩": 1, "፪": 2, "፫": 3, "፬": 4, "፭": 5, "፮": 6, "፯": 7, "፰": 8, "፱": 9,
    "፲": 10, "፳": 20, "፴": 30, "፵": 40, "፶": 50, "፷": 60, "፸": 70, "፹": 80, "፺": 90,
    "፻": 100, "፼": 10000,
}
_FA_ORDINAL_NUM = (
    ("دوازدهم", "12"),
    ("سیزدهم", "13"),
    ("چهاردهم", "14"),
    ("پانزدهم", "15"),
    ("شانزدهم", "16"),
    ("هفدهم", "17"),
    ("هجدهم", "18"),
    ("نوزدهم", "19"),
    ("یازدهم", "11"),
    ("بیستم", "20"),
    ("چهارم", "4"),
    ("چارم", "4"),
    ("جارم", "4"),
    ("پنجم", "5"),
    ("ششم", "6"),
    ("هفتم", "7"),
    ("هشتم", "8"),
    ("نهم", "9"),
    ("دهم", "10"),
    ("سوم", "3"),
    ("دوم", "2"),
    ("اولی", "1"),
    ("اول", "1"),
    ("نخست", "1"),
)
_CJK_DIGIT = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def _cjk_numeral_value(text: str) -> str | None:
    body = re.sub(r"[第条條項款章编編节節之조항호편절、]", "", text)
    if not body or not all(ch in _CJK_DIGIT or ch == "十" or ch == "百" for ch in body):
        return None
    if body == "十":
        return "10"
    if body.startswith("十"):
        return str(10 + _CJK_DIGIT.get(body[1], 0))
    if "百" in body:
        left, right = body.split("百", 1)
        if not left:
            hundreds = 100
        elif left in _CJK_DIGIT:
            hundreds = _CJK_DIGIT[left] * 100
        else:
            return None
        if not right:
            return str(hundreds)
        rest = _cjk_numeral_value(right)
        if rest is None:
            return None
        return str(hundreds + int(rest))
    if "十" in body:
        left, right = body.split("十", 1)
        tens = _CJK_DIGIT.get(left, 0) * 10
        ones = _CJK_DIGIT.get(right, 0) if right else 0
        return str(tens + ones)
    if body in _CJK_DIGIT:
        return str(_CJK_DIGIT[body])
    return None


def _circled_to_int(char: str) -> str | None:
    if not char:
        return None
    code = ord(char[0])
    if 0x2460 <= code <= 0x2473:
        return str(code - 0x2460 + 1)
    if 0x2474 <= code <= 0x2487:
        return str(code - 0x2474 + 1)
    if 0x2488 <= code <= 0x249B:
        return str(code - 0x2488 + 1)
    if 0x2776 <= code <= 0x277F:
        return str(code - 0x2776 + 1)
    if 0x24EB <= code <= 0x24F4:
        return str(code - 0x24EB + 11)
    return None


def _ethiopic_numeral_value(text: str) -> str | None:
    chars = [ch for ch in text if ch in _ETH_VALUES]
    if not chars:
        return None
    body = "".join(chars)
    if "፼" in body:
        left, right = body.split("፼", 1)
        mul = _ethiopic_numeral_value(left) if left else "1"
        rest = _ethiopic_numeral_value(right) if right else "0"
        if mul is None or rest is None:
            return None
        return str(int(mul) * 10000 + int(rest))
    if "፻" in body:
        left, right = body.split("፻", 1)
        mul = sum(_ETH_VALUES[ch] for ch in left) if left else 1
        rest = sum(_ETH_VALUES[ch] for ch in right)
        return str(mul * 100 + rest)
    return str(sum(_ETH_VALUES[ch] for ch in chars))


def _hebrew_letter_num(raw: str) -> str | None:
    """Map פרק א' / תוספת שניה / סעיף יא to decimal. Long Hebrew words stay unmapped."""
    cleaned = re.sub(r"['׳״\"`]", "", raw)
    for word, num in _HE_ORDINAL_NUM:
        if word in cleaned:
            return num
    katan = re.search(r"סעיף\s+קטן\s*\(?\s*([א-ת])", cleaned)
    if katan:
        ch = katan.group(1)
        return str(_HE_VALUES[ch]) if ch in _HE_VALUES else ch
    match = re.search(r"(?:פרק|סימן|חלק|תוספת|סעיף)\s*(?!קטן)([א-ת]{1,3})", cleaned)
    if not match:
        return None
    total = sum(_HE_VALUES.get(ch, 0) for ch in match.group(1))
    return str(total) if total else None


def _script_hit_kind(regex: re.Pattern[str]) -> str:
    if regex is _RU_TITLE_RE or regex is _TH_LAK_RE:
        return "title"
    if regex in (
        _HE_PEREK_RE, _AR_BAB_RE, _TH_HUAT_RE, _CJK_ZHANG_RE, _KO_JANG_RE,
        _RU_CHAP_RE, _KM_CHAP_RE, _MY_CHAP_RE, _KA_CHAP_RE, _HY_CHAP_RE, _AM_CHAP_RE,
        _HI_CHAP_RE, _BN_CHAP_RE, _UR_CHAP_RE, _FA_FASL_RE, _NE_CHAP_RE,
    ):
        return "chapter"
    if regex in (_HE_HELEK_RE, _AR_KITAB_RE, _CJK_BIAN_RE, _KO_PYEON_RE, _LO_PART_RE, _SR_PART_RE):
        return "part"
    if regex in (
        _HE_SIMAN_RE,
        _HE_TOS_RE,
        _HE_TAKANA_RE,
        _HE_PARA_RE,
        _HE_KATAN_RE,
        _AR_ANNEX_RE,
        _AR_PARA_RE,
        _AR_FASL_RE,
        _AR_FARA_RE,
        _JA_KOU_RE,
        _ZH_KUAN_RE,
        _KO_HANG_RE,
        _KO_HO_RE,
        _TH_PARA_RE,
        _TH_KHO_RE,
        _TH_TON_RE,
        _FA_TAB_RE,
        _FA_BAND_RE,
        _AR_POINT_RE,
        _CJK_JIE_RE,
        _KO_JEOL_RE,
    ):
        return "section"
    return "article"


def _script_article_number(raw: str) -> str:
    stripped = raw.strip()
    for word, num in _AR_POINT_NUM:
        if stripped.startswith(word):
            return num
    compact = raw.strip().strip("()[] \t\u3001\uff08\uff09.、-–—")
    circled = _circled_to_int(compact)
    if circled:
        return circled
    if compact and len(compact) <= 3:
        first = compact[0]
        if first in _HANGUL_GA:
            return str(_HANGUL_GA.index(first) + 1)
        if first in _KATA_ENUM:
            return str(_KATA_ENUM.index(first) + 1)
        if first in _AR_ABJAD_INDEX:
            return _AR_ABJAD_INDEX[first]
        if first in _HE_ALEF:
            return str(_HE_ALEF.index(first) + 1)
        if first in _TH_KO:
            return str(_TH_KO.index(first) + 1)
        low = first.casefold()
        if low in _CYR_AB:
            return str(_CYR_AB.index(low) + 1)
        if low in _EL_AB:
            return str(_EL_AB.index(low) + 1)
        if first in _KA_AB:
            return str(_KA_AB.index(first) + 1)
        if first in _HY_AB:
            return str(_HY_AB.index(first) + 1)
        cjk_early = _cjk_numeral_value(compact)
        if cjk_early:
            return cjk_early
    he = _hebrew_letter_num(raw)
    if he:
        return he
    digits = _unicode_digit_runs(raw)
    if digits:
        if len(digits) >= 2 and re.search(r"[0-9٠-٩۰-۹]+-[0-9٠-٩۰-۹]+", raw):
            return "-".join(digits[:2])
        return digits[0]
    eth = _ethiopic_numeral_value(raw)
    if eth:
        return eth
    compact = re.sub(r"[\s\u0640]+", "", raw)
    for word, num in _AR_ORDINAL_NUM + _FA_ORDINAL_NUM:
        needle = re.sub(r"[\s\u0640]+", "", word)
        if needle and needle in compact:
            return num
    cjk = _cjk_numeral_value(compact)
    if cjk:
        return cjk
    tail = re.search(r"([0-9٠-٩۰-۹]+|[IVXLCDM]{1,8})$", compact)
    if tail:
        return tail.group(1)
    return compact


def _in_range_boilerplate(text: str, start: int) -> bool:
    for regex in (_KO_RANGE_RE, _CJK_RANGE_RE):
        for match in regex.finditer(text):
            if match.start() <= start < match.end():
                return True
    return False


def _kind_number_from_heading_match(match: re.Match) -> tuple[str, str]:
    for name in ("title", "chapter", "part", "article", "section"):
        if match.group(name):
            return name, (match.group(f"{name}_n") or "").strip()
    if match.group("section_sym"):
        return "section", (match.group("section_sym_n") or "").strip()
    if match.group("section_pre"):
        return "section", (match.group("section_pre_n") or "").strip()
    if match.group("grein"):
        return "article", (match.group("grein_n") or "").strip()
    if match.group("straipsnis"):
        return "article", (match.group("straipsnis_n") or "").strip()
    if match.group("artikulua"):
        return "article", (match.group("artikulua_n") or "").strip()
    if match.group("ledd"):
        return "section", (match.group("ledd_n") or "").strip()
    if match.group("kap"):
        return "chapter", (match.group("kap_n") or "").strip()
    if match.group("luku"):
        return "chapter", (match.group("luku_n") or "").strip()
    if match.group("fejezet"):
        return "chapter", (match.group("fejezet_n") or "").strip()
    if match.group("peatukk"):
        return "chapter", (match.group("peatukk_n") or "").strip()
    if match.group("skyrius"):
        return "chapter", (match.group("skyrius_n") or "").strip()
    if match.group("nodala"):
        return "chapter", (match.group("nodala_n") or "").strip()
    if match.group("kafli"):
        return "chapter", (match.group("kafli_n") or "").strip()
    if match.group("bob"):
        return "chapter", (match.group("bob_n") or "").strip()
    if match.group("tarau"):
        return "chapter", (match.group("tarau_n") or "").strip()
    if match.group("bolum"):
        return "chapter", (match.group("bolum_n") or "").strip()
    if match.group("modda"):
        return "article", (match.group("modda_n") or "").strip()
    if match.group("mn"):
        return "article", (match.group("mn_n") or "").strip()
    if match.group("kk"):
        return "article", (match.group("kk_n") or "").strip()
    if match.group("disp"):
        return "article", (match.group("disp_n") or "").strip()
    if match.group("mom"):
        return "section", (match.group("mom_n") or "").strip()
    if match.group("order"):
        return "section", (match.group("order_n") or "").strip()
    if match.group("kidogo"):
        return "section", (match.group("kidogo_n") or "").strip()
    if match.group("esresol"):
        word = _latin_fold(match.group("esresol") or "").casefold()
        return "section", {
            "primero": "1", "segundo": "2", "tercero": "3", "cuarto": "4",
            "quinto": "5", "sexto": "6", "septimo": "7", "octavo": "8",
            "noveno": "9", "decimo": "10",
            "erstens": "1", "zweitens": "2", "drittens": "3", "viertens": "4", "funftens": "5",
            "premierement": "1", "deuxiemement": "2", "troisiemement": "3",
            "quatriemement": "4", "cinquiemement": "5",
        }.get(word, word)
    return "", ""


@dataclass
class _Hit:
    start: int
    kind: str
    number: str
    heading: str


_PAREN_XREF_RE = re.compile(
    r"(?i)^\s*(?:\([a-z0-9]{1,4}\))?\s+"
    r"(?:is|are|or|and|of|have|has|was|were|by|to|for|from|in|that|shall)\b"
)


def _paren_letter_xref(raw: str, number: str, rest: str) -> bool:
    """Skip 'paragraph (i) or …' / 'subsection (l)(b) is …' cross-references."""
    if len(number) != 1 or not number.isalpha() or "(" not in raw:
        return False
    return _PAREN_XREF_RE.match(rest) is not None


def _collect_hits(text: str, *, language: str, latin: bool) -> list[_Hit]:
    hits: list[_Hit] = []
    folded = _latin_fold(text) if latin else text
    if latin:
        for match in _HEADING_RE.finditer(folded):
            kind, number = _kind_number_from_heading_match(match)
            if not kind:
                continue
            if _CITE_TAIL_RE.match(folded[match.end() : match.end() + 48]):
                continue
            if _paren_letter_xref(match.group(0), number, folded[match.end() : match.end() + 48]):
                continue
            for gname in (
                "title_n", "chapter_n", "part_n", "article_n", "section_n",
                "section_sym_n", "section_pre_n", "grein_n", "straipsnis_n",
                "artikulua_n", "ledd_n", "kap_n", "luku_n",
                "fejezet_n", "peatukk_n", "skyrius_n", "nodala_n",
                "kafli_n", "bob_n", "tarau_n", "bolum_n",
                "modda_n", "mn_n", "kk_n", "mom_n", "order_n", "kidogo_n", "disp_n",
            ):
                try:
                    start, end = match.span(gname)
                except IndexError:
                    continue
                if start >= 0:
                    number = text[start:end]
                    break
            number = _fold_digits_in_number(number.strip().rstrip(".-:–—"))
            line_end = text.find("\n", match.start())
            if line_end < 0:
                line_end = len(text)
            heading = re.sub(r"\s+", " ", text[match.start() : line_end]).strip()[:240]
            hits.append(_Hit(match.start(), kind, number, heading))
        for match in _lexicon_heading_re().finditer(folded):
            if _CITE_TAIL_RE.match(folded[match.end() : match.end() + 48]):
                continue
            token = (match.group("lex") or "").casefold()
            kind = _LEXICON_KIND.get(token, "article")
            start, end = match.span("lex_n")
            number = _fold_digits_in_number(
                (text[start:end] if start >= 0 else match.group("lex_n") or "").strip().rstrip(".-:–—")
            )
            if not number:
                continue
            line_end = text.find("\n", match.start())
            if line_end < 0:
                line_end = len(text)
            heading = re.sub(r"\s+", " ", text[match.start() : line_end]).strip()[:240]
            hits.append(_Hit(match.start(), kind, number, heading))
    for match in _LATIN_LETTER_RE.finditer(text):
        letter = match.group("paren") or match.group("bare")
        if letter:
            number = str(ord(letter) - 96)
        else:
            number = _ROMAN_LOWER.get(match.group("roman") or "", "")
        if not number:
            continue
        line_end = text.find("\n", match.start())
        if line_end < 0:
            line_end = len(text)
        heading = re.sub(r"\s+", " ", text[match.start() : line_end]).strip()[:240]
        hits.append(_Hit(match.start(), "section", number, heading))
    for match in _LATIN_NUM_LIST_RE.finditer(text):
        number = (
            match.group("nparen")
            or match.group("nclose")
            or match.group("nord")
            or match.group("ndot")
            or match.group("ncolon")
            or match.group("ndash")
            or ""
        )
        dbl = match.group("dbl")
        if dbl:
            number = str(ord(dbl[0]) - 96)
        if not number:
            continue
        line_end = text.find("\n", match.start())
        if line_end < 0:
            line_end = len(text)
        heading = re.sub(r"\s+", " ", text[match.start() : line_end]).strip()[:240]
        hits.append(_Hit(match.start(), "section", number, heading))
    for i, match in enumerate(_BULLET_RE.finditer(text), start=1):
        line_end = text.find("\n", match.start())
        if line_end < 0:
            line_end = len(text)
        heading = re.sub(r"\s+", " ", text[match.start() : line_end]).strip()[:240]
        hits.append(_Hit(match.start(), "section", str(i), heading))
    for match in _DASH_NUM_RE.finditer(text):
        number = (match.group("bn") or "").strip()
        if not number:
            continue
        line_end = text.find("\n", match.start())
        if line_end < 0:
            line_end = len(text)
        heading = re.sub(r"\s+", " ", text[match.start() : line_end]).strip()[:240]
        hits.append(_Hit(match.start(), "section", number, heading))
    for regex in _detected_script_regexes(text, language):
        for match in regex.finditer(text):
            if _in_range_boilerplate(text, match.start()):
                continue
            if _SCRIPT_CITE_TAIL_RE.match(text[match.end() : match.end() + 48]):
                continue
            raw = match.group(0)
            number = _fold_digits_in_number(_script_article_number(raw))
            heading = re.sub(r"\s+", " ", raw).strip()[:240]
            hits.append(_Hit(match.start(), _script_hit_kind(regex), number, heading))
    if latin:
        from .profiles import iso_lang

        lang = iso_lang(language)
        keyword_hits = [h for h in hits if h.kind in {"article", "section"}]
        if len(keyword_hits) < MIN_SPLIT_HEADINGS and lang in _CW_NUM_LANGS:
            for match in _CW_NUM_RE.finditer(text):
                number = (match.group("cw_n") or "").strip()
                if not _plausible_cw_number(number):
                    continue
                if _MONTH_START_RE.match(text[match.end() : match.end() + 16]):
                    continue
                hits.append(
                    _Hit(
                        match.start(),
                        "section",
                        number,
                        match.group(0).strip()[:240],
                    )
                )
    hits.sort(key=lambda h: (h.start, -len(h.heading)))
    merged: list[_Hit] = []
    seen_starts: set[int] = set()
    for hit in hits:
        if hit.start in seen_starts:
            continue
        seen_starts.add(hit.start)
        merged.append(hit)
    return merged


def _units_from_hits(text: str, hits: list[_Hit]) -> list[StructureUnit]:
    if not hits:
        return [
            StructureUnit(kind="preamble", number="", heading="", body=text, char_start=0, char_end=len(text))
        ]
    cursor = {"title": "", "chapter": "", "part": "", "article": "", "section": ""}
    units: list[StructureUnit] = []
    if hits[0].start > 0:
        units.append(
            StructureUnit(
                kind="preamble",
                number="",
                heading="",
                body=text[0 : hits[0].start],
                char_start=0,
                char_end=hits[0].start,
            )
        )
    for i, hit in enumerate(hits):
        start = hit.start
        end = hits[i + 1].start if i + 1 < len(hits) else len(text)
        body = text[start:end]
        cursor[hit.kind] = hit.number
        for lower, rank in _KIND_RANK.items():
            if rank > _KIND_RANK.get(hit.kind, 99):
                cursor[lower] = ""
        units.append(
            StructureUnit(
                kind=hit.kind,
                number=hit.number,
                heading=hit.heading[:240],
                body=body,
                title_number=cursor["title"],
                chapter_number=cursor["chapter"],
                part_number=cursor["part"],
                article_number=cursor["article"],
                section_number=cursor["section"],
                subsections=_subsection_tokens(body),
                hierarchy_path=_cursor_path(cursor),
                char_start=start,
                char_end=end,
            )
        )
    return units


def segment_exclusive(text: str, *, language: str = "") -> list[StructureUnit]:
    """Internal exclusive-span segmentation of *text* (includes preamble)."""
    from .profiles import iso_lang, latin_split_allowed

    if not text:
        return []
    latin = not language or latin_split_allowed(language)
    hits = _collect_hits(text, language=language, latin=latin)
    retrieval_like = [h for h in hits if h.kind in {"article", "section"}]
    if (
        not latin
        and len(retrieval_like) < MIN_SPLIT_HEADINGS
        and iso_lang(language) in _LATIN_FALLBACK_LANGS
    ):
        hits = _collect_hits(text, language=language, latin=True)
    return _units_from_hits(text, hits)


def split_script_units(text: str, language: str) -> list[StructureUnit]:
    """Retrieval projection of script-specific exclusive spans."""
    internal = segment_exclusive(text, language=language)
    retrieval = [u for u in internal if u.kind == "article" and len(u.body.strip()) >= 16]
    return retrieval if len(retrieval) >= MIN_SPLIT_HEADINGS else []


def split_structured_units(text: str, *, language: str = "") -> list[StructureUnit]:
    """Retrieval units. Empty list means keep the whole instrument.

    Prefers article/section. When those are scarce, numbered chapter then title
    headings (Cameroon CHAPITRE, Bolivia TÍTULO, Cape Verde CAPÍTULO).
    """
    if not text or len(text) < 16:
        return []
    from .profiles import latin_split_allowed

    internal = segment_exclusive(text, language=language)

    def _take(kinds: set[str]) -> list[StructureUnit]:
        out: list[StructureUnit] = []
        for u in internal:
            if u.kind not in kinds:
                continue
            min_len = 16 if u.number else MIN_UNIT_CHARS
            if language and not latin_split_allowed(language):
                min_len = 16
            if len(u.body.strip()) >= min_len:
                out.append(u)
        return out

    for kinds in (
        {"article", "section"},
        {"chapter"},
        {"part"},
        {"title"},
    ):
        retrieval = _take(kinds)
        if len(retrieval) >= MIN_SPLIT_HEADINGS:
            return retrieval
    return []
