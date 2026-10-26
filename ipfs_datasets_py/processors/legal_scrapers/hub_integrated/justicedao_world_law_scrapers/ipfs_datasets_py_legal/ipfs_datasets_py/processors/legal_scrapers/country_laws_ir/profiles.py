"""Per-language legal heading lexicons for country-law structure extraction.

Oregon (ORS) is English title/chapter/section. Other gazettes use their own
words (Artikel, Titre, Artículo, 条, مادة). This table is how we *score*
whether a split used the right language — not a claim that every country
has a dedicated parser.

Languages with no lexicon (ar, zh, ja, ko, …) must not be force-split on
Latin TITLE/ARTICLE markers; collectors may already have article rows.
"""

from __future__ import annotations

from collections import Counter
import re
from typing import Any

# keyword -> list of (kind, language); some words are shared (article).
HEADING_LEXICON: dict[str, list[tuple[str, str]]] = {}

def _add(lang: str, kind: str, *words: str) -> None:
    for word in words:
        HEADING_LEXICON.setdefault(word.casefold(), []).append((kind, lang))


_add("en", "title", "title")
_add("en", "chapter", "chapter")
_add("en", "part", "part")
_add("en", "article", "article")
_add("en", "section", "section", "sec.", "rule", "regulation", "schedule", "annex", "appendix")
_add("fr", "section", "annexe")
_add("es", "section", "anexo")
_add("de", "section", "anlage")
_add("nl", "section", "bijlage")
_add("it", "section", "allegato")
_add("pl", "section", "załącznik")
_add("sv", "section", "bilaga")
_add("fi", "section", "liite")
_add("cs", "section", "příloha")
_add("pt", "section", "anexo")

_add("fr", "title", "titre")
_add("fr", "chapter", "chapitre")
_add("fr", "part", "partie")
_add("fr", "article", "article")
_add("fr", "section", "section", "paragraphe")

_add("de", "title", "titel")
_add("de", "chapter", "kapitel")
_add("de", "part", "teil")
_add("de", "article", "artikel")
_add("de", "section", "abschnitt", "paragraf")

_add("nl", "title", "titel")
_add("nl", "chapter", "hoofdstuk")
_add("nl", "part", "deel")
_add("nl", "article", "artikel")
_add("nl", "section", "paragraaf", "afdeling")

_add("es", "title", "título", "titulo")
_add("es", "chapter", "capítulo", "capitulo")
_add("es", "part", "parte")
_add("es", "article", "artículo", "articulo")
_add("es", "section", "sección", "seccion")
_add("es", "article", "disposición", "disposicion")

_add("pt", "title", "título", "titulo")
_add("pt", "chapter", "capítulo", "capitulo")
_add("pt", "part", "parte")
_add("pt", "article", "artigo")
_add("pt", "section", "secção", "secao")

_add("it", "title", "titolo")
_add("it", "chapter", "capitolo")
_add("it", "part", "parte")
_add("it", "article", "articolo")
_add("it", "section", "sezione")

_add("el", "article", "άρθρο", "αρθρο")
_add("el", "chapter", "κεφάλαιο")
_add("hu", "article", "szakasz", "cikk")
_add("cs", "article", "článek")
_add("cs", "chapter", "kapitola")
_add("cs", "section", "odstavec", "odst.")
_add("sk", "article", "článok")
_add("sl", "article", "člen")
_add("nb", "article", "artikkel")
_add("sv", "article", "paragraf")
_add("fi", "article", "pykälä")
_add("fi", "chapter", "luku")
_add("is", "article", "grein")
_add("lv", "article", "pants")
_add("lv", "chapter", "nodaļa")
_add("et", "article", "paragrahv")
_add("et", "chapter", "peatükk")
_add("pl", "article", "artykuł", "artykul")
_add("ro", "article", "articolul", "articol")
_add("mt", "article", "artikolu")
_add("zh", "article", "条", "條")
_add("ar", "article", "مادة", "المادة", "الماده", "املادة", "املاده")
_add("ar", "chapter", "الباب")
_add("ar", "part", "الكتاب")
_add("ar", "section", "الفصل", "ملحق", "الفرع")
_add("fa", "article", "ماده")
_add("fa", "section", "تبصره", "بند")
_add("ja", "article", "条")
_add("ko", "article", "조")
_add("he", "article", "סעיף")
_add("he", "chapter", "פרק")
_add("he", "part", "חלק")
_add("he", "section", "סימן", "תוספת", "תקנה")
_add("th", "article", "มาตรา")
_add("th", "chapter", "หมวด")
_add("th", "section", "ข้อ", "วรรค")
_add("hi", "article", "धारा")
_add("bn", "article", "ধারা")
_add("ru", "article", "статья")
_add("ru", "chapter", "глава")
_add("ru", "title", "раздел")
_add("uk", "article", "стаття")
_add("bg", "article", "член", "чл")
_add("mk", "article", "член")
_add("sr", "article", "члан")
_add("hr", "article", "članak")
_add("hr", "chapter", "poglavlje")
_add("bs", "article", "članak")
_add("sq", "article", "neni")
_add("tr", "article", "madde")
_add("az", "article", "maddə")
_add("uz", "article", "модда")
_add("mn", "article", "зүйл")
_add("lo", "article", "ມາດຕາ")
_add("id", "article", "pasal")
_add("id", "chapter", "bab")
_add("ms", "article", "seksyen")
_add("ms", "part", "bahagian")
_add("lt", "article", "straipsnis")
_add("ta", "article", "பிரிவு")
_add("el", "part", "μέρος")
_add("el", "section", "παράγραφος")
_add("uk", "title", "розділ")
_add("zh", "chapter", "章")
_add("ja", "chapter", "章")
_add("ko", "chapter", "장")
_add("vi", "article", "điều")
_add("vi", "chapter", "chương")
_add("ka", "article", "მუხლი")
_add("hy", "article", "հոդված")
_add("am", "article", "አንቀጽ")
_add("km", "article", "មាត្រា")
_add("my", "article", "ပုဒ်မ")
_add("ne", "article", "दफा")
_add("si", "article", "වගන්තිය")
_add("kk", "article", "бап")
_add("uz", "article", "modda")
_add("be", "article", "артыкул")
_add("ky", "article", "берене")
_add("ur", "article", "دفعہ")
_add("so", "article", "qodob", "qodobka")
_add("ga", "article", "airteagal")
_add("cy", "article", "erthygl")
_add("fil", "article", "artikulo")
_add("fil", "section", "seksyon")
_add("fil", "chapter", "kabanata")
_add("id", "part", "bagian")
_add("vi", "part", "mục")
_add("sw", "part", "sehemu")
_add("ht", "article", "atik")
_add("eu", "article", "artikulua")
_add("da", "section", "stk")
_add("nb", "section", "ledd")
_add("de", "section", "absatz")
_add("es", "section", "apartado")
_add("it", "section", "comma")
_add("tr", "section", "fıkra")
_add("hr", "section", "stavak")
_add("bg", "section", "ал")
_add("te", "article", "ప్రకరణము", "ప్రకరణ")
_add("kn", "article", "ಪ್ರಕರಣ")
_add("gu", "article", "કલમ")
_add("pa", "article", "ਧਾਰਾ")
_add("ml", "article", "വകുപ്പ്")
_add("th", "title", "ลักษณะ")
_add("zh", "part", "编")
_add("ja", "part", "編")
_add("ko", "part", "편")
_add("tg", "article", "модда")
_add("sw", "article", "kifungu")
_add("ca", "article", "article")
_add("ca", "chapter", "capítol", "capitol")
_add("ca", "title", "títol", "titol")
_add("ca", "section", "secció", "seccio")
_add("pl", "chapter", "rozdział")
_add("pl", "title", "dział")
_add("ro", "chapter", "capitolul")
_add("ro", "title", "titlul")
_add("it", "chapter", "capo")
_add("cs", "chapter", "hlava")
_add("sk", "chapter", "hlava")
_add("es", "part", "libro")
_add("sv", "chapter", "kap")
_add("km", "chapter", "ជំពូក")
_add("lo", "part", "ພາກ")
_add("my", "chapter", "အခန်း")
_add("ka", "chapter", "თავი")
_add("hy", "chapter", "գլուխ")
_add("am", "chapter", "ምዕራፍ")
_add("sq", "chapter", "kreu")
_add("hu", "chapter", "fejezet")
_add("tr", "chapter", "bölüm")
_add("az", "chapter", "fəsil")
_add("lt", "chapter", "skyrius")
_add("is", "chapter", "kafli")
_add("ga", "chapter", "caibidil")
_add("cy", "chapter", "pennod")
_add("mt", "chapter", "kapitolu")
_add("ht", "chapter", "chapit")
_add("sw", "chapter", "sura")
_add("nb", "chapter", "kapittel")
_add("ha", "chapter", "sashe")
_add("mg", "chapter", "andiany")
_add("mi", "part", "wāhanga", "wahanga")
_add("sm", "part", "vaega")
_add("to", "article", "kupu")
_add("fj", "chapter", "wase")
_add("tpi", "part", "hap")
_add("fo", "chapter", "kapittul")
_add("bi", "article", "atikol")
_add("rw", "article", "ingingo")
_add("zu", "chapter", "isigaba")
_add("xh", "chapter", "icandelo")
_add("st", "part", "karolo")
_add("tn", "chapter", "kgaolo")
_add("sn", "part", "chikamu")
_add("ny", "article", "ndime")
_add("ku", "part", "beş")
_add("ky", "chapter", "бөлүм")
_add("tg", "chapter", "боби")
_add("yo", "article", "abala")
_add("yo", "chapter", "ori")
_add("ig", "article", "nkeji")
_add("lg", "part", "ekitundu")
_add("om", "chapter", "kutaa")
_add("ln", "part", "eténi", "eteni")
_add("ti", "article", "ዓንቀጽ")
_add("bm", "article", "sariya")
_add("wo", "article", "tere")
_add("ak", "article", "ahyɛde", "ahyede")
_add("ee", "part", "akpa")
_add("ff", "part", "faanda")
_add("br", "article", "pennad")
_add("kri", "section", "sekshon")
_add("bo", "article", "དོན་ཚན")
_add("ug", "article", "ماددا")
_add("kw", "article", "erthygel")
_add("tw", "article", "hyɛdeɛ", "hyedee")
_add("tet", "article", "artigu")
_add("haw", "article", "paukū", "pauku")
_add("ty", "article", "irava")
_add("ch", "part", "påtte", "patte")
_add("es", "section", "numeral")
_add("it", "section", "capoverso")
_add("de", "section", "nummer")
_add("so", "part", "qaybta")
_add("vi", "part", "phần")
_add("sk", "chapter", "oddiel")
_add("el", "title", "τίτλος")
_add("bg", "title", "дял")
_add("uz", "chapter", "bob")
_add("kk", "chapter", "тарау")
_add("hi", "chapter", "अध्याय")
_add("bn", "chapter", "অধ্যায়")
_add("ur", "chapter", "باب")
_add("fa", "chapter", "فصل")
_add("ne", "chapter", "परिच्छेद")
_add("zh", "section", "节")
_add("ja", "section", "節")
_add("ko", "section", "절")
_add("th", "section", "ตอน")
_add("sr", "part", "одељак")
_add("be", "title", "раздзел")

# Shared abbreviation; language left unknown.
_add("und", "article", "art.", "član")
_add("und", "section", "§")

# Scripts we do not Latin-split:
NO_LATIN_SPLIT_LANGS = frozenset(
    {
        "ar", "zh", "zh-cn", "zh-tw", "ja", "ko", "fa", "he", "th", "hi", "bn",
        "am", "ru", "uk", "be", "ka", "hy", "km", "lo", "my", "si",
    }
)

_TOKEN_RE = re.compile(r"[^\W\d_]+|art\.|sec\.|чл\.|§", re.UNICODE)


def classify_heading_token(token: str) -> list[tuple[str, str]]:
    return list(HEADING_LEXICON.get(token.casefold()) or ())


def score_heading_languages(text: str) -> Counter[str]:
    """Count distinctive lexicon hits. Shared words like 'article' do not vote."""
    counts: Counter[str] = Counter()
    if not text:
        return counts
    for token in _TOKEN_RE.findall(text):
        hits = classify_heading_token(token)
        langs = {lang for _kind, lang in hits if lang != "und"}
        if len(langs) == 1:
            counts[next(iter(langs))] += 1
    return counts


def majority_language(counts: Counter[str], *, exclude: tuple[str, ...] = ("und",)) -> str | None:
    filtered = Counter({k: v for k, v in counts.items() if k not in exclude})
    if not filtered:
        return None
    lang, _n = filtered.most_common(1)[0]
    return lang


def iso_lang(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    if not text:
        return ""
    return text.split("-")[0]


def latin_split_allowed(language: str) -> bool:
    return iso_lang(language) not in NO_LATIN_SPLIT_LANGS
