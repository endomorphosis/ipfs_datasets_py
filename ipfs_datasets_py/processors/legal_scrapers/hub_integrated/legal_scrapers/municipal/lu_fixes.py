"""Text helpers for the Luxembourg communal regulations (no OCR): text layer, cleaning, signature / page-furniture stripping,
encoding and mixed-script gates, language (fr / de / lb), document classification, dates, article splitter.
Imported by build_lu_municipal.py."""
import re, subprocess, unicodedata, collections, datetime

# ---------------------------------------------------------------- text layer
def pdf_text(path, timeout=180):
    """pdftotext -enc UTF-8 (reading order, no layout); '' when the PDF has no text layer. No OCR."""
    try:
        r = subprocess.run(["pdftotext", "-enc", "UTF-8", "-q", path, "-"], capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", "replace")
    except (subprocess.TimeoutExpired, OSError):
        return ""

def pdf_pages(path):
    try:
        r = subprocess.run(["pdfinfo", path], capture_output=True, timeout=60, text=True)
        m = re.search(r"^Pages:\s+(\d+)", r.stdout, re.M); return int(m.group(1)) if m else None
    except (subprocess.TimeoutExpired, OSError):
        return None

def text_quality(t, pages=None):
    """(ok, reason): enough letters for the page count, no cid glyphs, little replacement noise"""
    letters = len(re.findall(r"[A-Za-zÀ-ÿ]", t))
    if "(cid:" in t: return False, "bad_text_layer_cid"
    if letters < 300: return False, "no_text_layer_scanned"          # image-only PDF: no OCR
    if pages and letters < 120 * pages * 0.5 and letters < 4000: return False, "no_text_layer_mostly_scanned"
    if t.count("\ufffd") > 0.01 * letters: return False, "bad_text_layer_replacement_chars"
    if "\ufffd" in clean_text(t): return False, "bad_text_layer_replacement_chars"   # an unmapped glyph inside a word (a letter is lost)
    words = re.findall(r"[A-Za-zÀ-ÿ]{2,}", t)
    if words and sum(1 for w in words if not re.search(r"[aeiouyàâäéèêëîïôöûüùAEIOUYÉÈ]", w)) > 0.35 * len(words):
        return False, "bad_text_layer_broken_font"
    if garble_rate(t) > 50: return False, "garbled_ocr_text_layer"    # the publisher's own OCR layer ('d6lib6rations', 'S6ance'); we do no OCR
    return True, None

_GARBLE = re.compile(r"(?i)\b(?:[a-zà-ÿ]+\d[a-zà-ÿ\d]*[a-zà-ÿ]|[a-zà-ÿ]*[a-zà-ÿ]\d[a-zà-ÿ]+)\b")
_GARBLE_OK = re.compile(r"(?i)[a-z]{1,3}\d+[a-z]?|\d+[a-z]{1,3}|[a-z]+\d+[a-z]{1,2}")   # codes like 'B12a', 'CO2e', 'N1a'
def garble_rate(t):
    """letter-digit-letter tokens per 10,000 words: OCR misreadings of accented letters ('arr6t6e' = 'arrêtée'). Clean texts score <= 20,
    garbled OCR layers > 100."""
    n = len(re.findall(r"\b\w+\b", t))
    if not n: return 0.0
    return 1e4 * sum(1 for m in _GARBLE.finditer(t) if not _GARBLE_OK.fullmatch(m.group(0))) / n

# ---------------------------------------------------------------- characters
C1 = {0x80: "€", 0x82: "‚", 0x84: "„", 0x85: "…", 0x8a: "Š", 0x8c: "Œ", 0x8e: "Ž", 0x91: "‘", 0x92: "’", 0x93: "“", 0x94: "”", 0x95: "•",
      0x96: "–", 0x97: "—", 0x99: "™", 0x9a: "š", 0x9c: "œ", 0x9e: "ž", 0x9f: "Ÿ"}
def map_c1(t):
    return re.sub(r"[\x80-\x9f]", lambda m: C1.get(ord(m.group(0)), ""), t)

PUA = {0xF020: " ", 0xF02D: "-", 0xF0B7: "•", 0xF0A7: "•", 0xF0FC: "•", 0xF0D8: "•", 0xF06C: "•", 0xF0A8: "•", 0xF076: "•", 0xF0E0: "→", 0xF0F0: "•",
       0xF0AE: "→", 0xF0D2: "•", 0xF06E: "•", 0xF071: "•", 0xF0B2: "•", 0xF0F7: "•", 0xF0FB: "•", 0xF0FE: "•", 0xF0A2: "•", 0xF09F: "•"}
def map_pua(t):
    def f(m):
        o = ord(m.group(0))
        if o in PUA: return PUA[o]
        if 0xF021 <= o <= 0xF07E: return chr(o - 0xF000)       # Symbol-font ASCII range
        return ""
    return re.sub(r"[\ue000-\uf8ff]", f, t)

# Cyrillic / Greek letters that look like Latin ones, inside Latin words ('Règlеment' with a Cyrillic е)
LOOK = dict(zip("АВЕКМНОРСТХаеорсухіјѕԁԛԝΑΒΕΖΗΙΚΜΝΟΡΤΥΧοαι", "ABEKMHOPCTXaeopcyxijsdqwABEZHIKMNOPTYXoai"))
TOKEN = re.compile(r"[^\W\d_]+", re.U)
def _script(c):
    o = ord(c)
    if 0x0400 <= o <= 0x04FF: return "c"
    if 0x0370 <= o <= 0x03FF or 0x1F00 <= o <= 0x1FFF: return "g"
    if c.isalpha(): return "l"
    return "o"
def fix_lookalikes(t):
    def f(m):
        w = m.group(0); s = {_script(c) for c in w}
        if "l" in s and (s & {"c", "g"}): return "".join(LOOK.get(c, c) if _script(c) in ("c", "g") else c for c in w)
        return w
    return TOKEN.sub(f, t)
def mixed_tokens(t):
    return [w for w in TOKEN.findall(t) if len({_script(c) for c in w} - {"o"}) > 1 and not re.fullmatch(r"[µμ][a-zA-Z]{1,2}", w)]

def loose_combining(t):
    """combining marks left without a letter base (every valid letter + mark is precomposed after NFC)"""
    return [t[max(0, i - 10):i + 5] for i, c in enumerate(t) if unicodedata.category(c) == "Mn" and (i == 0 or not t[i - 1].isalpha())]

SPACING_ACC = {"\u00b4": "\u0301", "`": "\u0300", "\u00a8": "\u0308", "^": "\u0302"}
def fix_spacing_accents(t):
    """'re´glement' / 're´ glement' (spacing acute before or after the letter) -> 'règlement' forms: attach to the following vowel"""
    V = "aeiouAEIOU"
    t = re.sub(r"([" + V + r"])\s?([\u00b4`\u00a8^])(?=[a-zà-ÿ])", lambda m: unicodedata.normalize("NFC", m.group(1) + SPACING_ACC[m.group(2)]), t)   # 're´glement' -> 'réglement'
    t = re.sub(r"(?<=[a-zà-ÿ])([\u00b4\u00a8])\s?([" + V + r"])", lambda m: unicodedata.normalize("NFC", m.group(2) + SPACING_ACC[m.group(1)]), t)  # 'r´eglement'
    return t

# ---------------------------------------------------------------- signatures, page furniture
SIG = re.compile(r"(?im)^.*(signé\s+électroniquement|digitally\s+signed|signature\s+numérique|signature\s+électronique|elektronisch\s+signiert|"
                 r"signed\s+by\s*:|LuxTrust|Reason\s*:|Location\s*:\s*Luxembourg|Date\s*:\s*\d{4}[.\-/]\d\d[.\-/]\d\d\s+\d\d:\d\d|"
                 r"Adobe\s+Acrobat|Validit[éy]\s+unknown|Signature\s+(valid|non\s+vérifiée)).*$")
PAGE_NO = re.compile(r"(?im)^\s*(page|seite|säit|p\.)?\s*\d{1,3}\s*(/|sur|de|von|vun|of)\s*\d{1,3}\s*$|^\s*-\s*\d{1,3}\s*-\s*$|^\s*(page|seite|säit)\s+\d{1,3}\s*$")
def strip_furniture(t):
    """removes signature-box lines, page numbers, and short header/footer lines repeated on >= half of the pages (>= 3 pages)"""
    pages = t.split("\f"); n = len([p for p in pages if p.strip()])
    rep = set()
    if n >= 3:
        c = collections.Counter()
        for p in pages:
            ls = [l.strip() for l in p.split("\n") if l.strip()]
            for l in set(ls[:4] + ls[-4:]):
                if len(l) <= 90 and not ARTICLE_LINE.match(l): c[re.sub(r"\d+", "#", l)] += 1
        rep = {k for k, v in c.items() if v >= max(3, n / 2)}
    out = []
    for p in pages:
        for l in p.split("\n"):
            s = l.strip()
            if s and (re.sub(r"\d+", "#", s) in rep or PAGE_NO.match(s) or SIG.match(s)): continue
            out.append(l)
        out.append("")
    return "\n".join(out)

COVER = re.compile(r"(?i)minist[eè]re\s+de\s+l['’]?\s?int[ée]rieur|innenministerium")
COVER_ACT = re.compile(r"(?i)approbation|approuv|retourn[ée]\s+à|pris\s+connaissance|genehmig")
def split_cover_letter(raw):
    """a Ministry of the Interior transmission / approval letter scanned as page 1 (or as the last page) is not part of the regulation:
    (text without it, letter date or None, removed: bool). Only when the other pages carry the text (>= 300 letters)."""
    pg = raw.split("\f"); out_date = None; removed = False
    def letter(p): return COVER.search(p[:1500]) and COVER_ACT.search(p) and len(re.findall(r"[A-Za-zÀ-ÿ]", p)) < 3500
    def ldate(p):
        m = re.search(r"(?i)Luxembourg,?\s+le\s+(?P<d>" + D_TXT + ")", p)
        return _date(m.group("d")) if m else None
    rest = lambda ps: len(re.findall(r"[A-Za-zÀ-ÿ]", "".join(ps))) >= 300
    if len(pg) > 1 and letter(pg[0]) and rest(pg[1:]): out_date = ldate(pg[0]); pg = pg[1:]; removed = True
    tail = [k for k, p in enumerate(pg) if p.strip()]
    if len(tail) > 1 and letter(pg[tail[-1]]) and rest(pg[:tail[-1]]): out_date = out_date or ldate(pg[tail[-1]]); pg = pg[:tail[-1]]; removed = True
    return "\f".join(pg), out_date, removed
TITLE_LINE = re.compile(r"^\s*(R[EÈÉ]GLEMENT|Règlement|Reglement|Verordnung|Polizeiverordnung|Allgemeines\s+Polizeireglement)\b[^.;,]{0,60}$")   # a title line, not a sentence
LETTER = re.compile(r"(?i)\b(chères\s+(con)?citoyennes|chers\s+(con)?citoyens|liebe\s+mitbürger|nous\s+nous\s+permettons\s+de\s+rappeler|nous\s+avons\s+l['’]honneur\s+de\s+vous\s+faire\s+parvenir)")
def strip_citizen_letter(t):
    """(text, letter_date, removed): a letter to the citizens printed in front of the full regulation ('Chères citoyennes, chers citoyens,
    nous avons l'honneur de vous faire parvenir ci-joint le règlement …  Bascharage, le 19 mars 2014' + the German version) is cut when the
    rest carries the regulation (>= 10 article headings). The cut ends at the last signature / place-and-date line of the letter(s) before
    the first article heading. letter_date = the vote date the letter reports ('voté en date du 25 avril 2012')."""
    m0 = LETTER.search(t[:2000])
    if not m0: return t, None, False
    ls = t.split("\n"); hc = heading_candidates(ls)
    if len(hc) < 10: return t, None, False
    start = t.count("\n", 0, m0.start())    # the salutation line; the title block above it stays
    end = next((i for i in range(start + 1, len(ls)) if re.match(r"(?i)^\s*(sommaire|inhaltsverzeichnis|table\s+des\s+mati[eè]res|le\s+conseil\s+communal\b|der\s+gemeinderat\b|titre\s+[\divx]|chapitre\s+[\divx]|kapitel\s+[\divx])", ls[i])
                or ARTICLE_LINE.match(ls[i]) or (TITLE_LINE.match(ls[i]) and i > start + 3)), None)
    if end is None or end - start > 120: return t, None, False
    letter = "\n".join(ls[start:end]); rest = "\n".join(ls[:start] + ls[end:]).strip()
    if len(re.findall(r"[A-Za-zÀ-ÿ]", rest)) < 3000: return t, None, False
    m = re.search(r"(?i)vot[ée]\s+(en\s+date\s+)?du\s+(?P<d>" + D_TXT + "|" + D_NUM + ")", letter)
    return rest, (_date(m.group("d")) if m else None), True
MEMORIAL = re.compile(r"(?i)mentions\s+ci-après\s+sont\s+faites\s+en\s+vertu|r[ée]glements\s+communaux\s*\n[^\n]{0,40}\(les\s+mentions|m[ée]morial\s+(a|b)\s*[-–—]?\s*n[°o]")
def strip_memorial_pages(raw):
    """(text, n): trailing pages copied from the Mémorial ('Règlements communaux (Les mentions ci-après sont faites en vertu de l'article 4
    …)') list other communes' acts and state acts; they are removed when the earlier pages carry the text"""
    pg = raw.split("\f"); n = 0
    while len(pg) > 1:
        k = max(i for i, p in enumerate(pg) if p.strip()) if any(p.strip() for p in pg) else 0
        if k == 0 or not MEMORIAL.search(pg[k]) or len(re.findall(r"[A-Za-zÀ-ÿ]", "".join(pg[:k]))) < 300: break
        pg = pg[:k]; n += 1
    return "\f".join(pg), n
def strip_stamp_noise(t):
    """publisher-OCR noise from stamps / logos in the first 60 lines ('~k', 'I~f', ',;~', 'UJ', 'LL'): lines without any 3-letter word that
    carry stray symbols or are 1-2 letters. Only applied when >= 4 such lines are present (a stamp)."""
    ls = t.split("\n"); head = ls[:60]
    junk = lambda l: l.strip() and not re.search(r"[A-Za-zÀ-ÿ]{3}", l) and not re.fullmatch(r"\s*([\d./-]+|N°|No|\d+°|[a-z]\)|[IVX]+\.?|[-•–]+)\s*", l) \
        and (re.search(r"[~<>|\\^`;:,!?'\"()=·•_*]", l) or re.fullmatch(r"\s*[A-Za-z]{1,2}\s*\.{0,3}\s*", l))
    if sum(1 for l in head if junk(l)) < 4: return t
    return "\n".join([l for l in head if not junk(l)] + ls[60:])
# closing formula of a deliberation / regulation, after which only signatures, stamps and certification follow
CLOSE = re.compile(r"(?im)^[^\n]{0,80}\b(suivent\s+les\s+signatures|folgen\s+die\s+unterschriften|pour\s+(extrait|expédition|copie)\s+conforme|"
                   r"für\s+gleichlautend\w*|date\s+que\s+dessus|^\s*fait\s+(à\s+[\w\-]+,?\s+)?le\s+\d{1,2}|^\s*palais\s+de\s+luxembourg,?\s+le|^\s*ch[âa]teau\s+de\s+berg,?\s+le|^\s*(colmar-)?berg,?\s+le\s+\d|^\s*donné\s+à\s+|datum\s+wie\s+oben|\((s|sé|sig)\.?\)\s*(le|la|der|die)?\s*(bourgmestre|secrétaire|ministre|bürgermeister))")
CLOSE_TAIL = re.compile(r"(?im)^\s*(pour\s+le\s+coll[eè]ge\s+(échevinal|des\s+bourgmestre)|(le|la)\s+(bourgmestre|secrétaire)(\s+communal\w*)?(\s+f\.\s?f\.)?\s*,?\s*$|"
                        r"(der|die)\s+(bürgermeister|sekretär)\w*\s*,?\s*$|de\s+buergermeeschter\s*,?\s*$)")
ADDR = [r"\bB\.?\s?P\.?\s*\d", r"\bL-\d{4}\b", r"(T[ée]l\.?|\bT\.|Fax)\s*[:.]?\s*\(?\+?\d", r"www\.", r"@\w", r"\+\s?352"]
def strip_letterhead(t):
    """letterhead / footer lines (address, phone, web, e-mail: >= 2 of these on one line) in the first 25 and the last 12 lines"""
    ls = t.split("\n"); n = len(ls)
    is_addr = lambda l: len(l) < 220 and sum(bool(re.search(x, l, re.I)) for x in ADDR) >= 2
    ls = [l for k, l in enumerate(ls) if not ((k < 25 or k >= n - 12) and is_addr(l))]
    # a trailing address block ('Hôtel de Ville … L-6460 Echternach' / 'Adresse postale:' / 'www.echternach.lu'): short lines from the end
    one = lambda l: len(l) < 120 and (any(re.search(x, l, re.I) for x in ADDR) or re.search(r"(?i)adresse\s+postale|hôtel\s+de\s+ville|administration\s+communale|^\s*$", l))
    while ls and one(ls[-1]) and len(ls) > 5: ls.pop()
    return "\n".join(ls)
def strip_signature_tail(t):
    """(text, removed): cuts the closing formula and what follows it ('Suivent les signatures. / Pour extrait conforme / Bettembourg, le … /
    names / stamp'), when it sits in the last 3,000 characters and the cut part holds no article heading and is < 2,500 characters"""
    lo = max(0, len(t) - 3000)
    for rx in (CLOSE, CLOSE_TAIL):
        for m in rx.finditer(t, lo):   # the earliest closing formula whose tail holds no article heading / annex
            if rx is CLOSE_TAIL and m.start() < len(t) - 1500: continue
            tail = t[m.start():]
            if len(tail) < 2500 and not heading_candidates(tail.split("\n")[1:]) and not re.search(r"(?im)^\s*(annexe|anlage)\s+\w", tail):
                return t[:m.start()].rstrip(), True
    return t, False
def fix_replacement_chars(t):
    """U+FFFD left by an unmapped glyph: French elision 'd�application' / 'jusqu�au' -> ’ (the only letter-free reading); a standalone
    U+FFFD (signature scribble, bullet glyph) is removed. U+FFFD inside a word stays, and text_quality then excludes the document."""
    t = re.sub(r"(?i)\b(d|l|qu|jusqu|lorsqu|puisqu|quoiqu|n|s|j|c|m|t)\ufffd(?=[aeiouyhàâéèêîôûAEIOUYHÀÂÉÈÊÎÔÛ])", lambda m: m.group(1) + "’", t)
    return re.sub(r"(?<![\w\ufffd])\ufffd+(?![\w\ufffd])", "", t)
E_AS_6 = re.compile(r"(?<![\w\d])([a-zà-ÿ]{1,20})6([a-zà-ÿ]{1,20})(?![\w\d])")
def fix_e_as_6(t):
    """publisher-OCR 'é read as 6' inside a French word ('reserv6s', 'se6ances' -> 'reservés', 'séances'); only lower-case letters on both
    sides, no other digit in the token ('A6', '6e', '16h' are untouched)"""
    return E_AS_6.sub(lambda m: (m.group(1)[:-1] + "é" if m.group(1).endswith("e") else m.group(1) + "é") + m.group(2), t)
def fix_dotless_i(t):
    """'maı̂tre' (dotless ı + combining circumflex/diaeresis) -> 'maître'"""
    return unicodedata.normalize("NFC", re.sub(r"ı(?=[\u0300-\u036f])", "i", t))
def fix_backtick_apostrophe(t):
    """'l`article', 'd`une' -> ’ between letters"""
    return re.sub(r"(?<=[A-Za-zÀ-ÿ])[`´](?=[A-Za-zÀ-ÿ])", "’", t)
def clean_text(raw):
    t = map_pua(map_c1(raw))
    t = re.sub(r"(?m)^\s*R[eè]gl[eè]m[eè]nts\s+tax[eè]s\s*$", "", t)   # decorative running header (Dudelange register extracts), not text
    t = strip_furniture(t)                      # needs the \f page breaks
    t = t.replace("\f", "\n")
    t = fix_spacing_accents(t)
    t = unicodedata.normalize("NFKC", t)
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b\u200c\u200d\u2060\ufeff\u00ad]", "", t)   # controls, zero-width, soft hyphen
    t = re.sub(r"(?<=\S)\u0301|\u0301", "", t)   # stray combining acute after NFKC of a spacing accent that had no vowel
    t = unicodedata.normalize("NFC", "".join(c for i, c in enumerate(t) if not (unicodedata.category(c) == "Mn" and (i == 0 or not t[i - 1].isalpha()))))
    t = fix_lookalikes(t)
    t = fix_e_as_6(t)
    t = fix_replacement_chars(t)
    t = fix_dotless_i(t); t = fix_backtick_apostrophe(t)
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    t = re.sub(r" *\n *", "\n", t); t = strip_stamp_noise(t); t = strip_letterhead(t); t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

# ---------------------------------------------------------------- language
STOP = {"fr": "le la les des du de et est pour par dans sur une un aux qui que sont être cette ces au en conseil communal article".split(),
        "de": "der die das und ist für von mit den dem des ein eine im auf zu sind werden wird nicht auch gemeinde artikel".split(),
        "lb": "an der de vun fir mat dat ass gëtt ginn d' dës gemeng hir och net ze eng een säin sinn kann dass".split()}
def language(t):
    w = collections.Counter(x.lower() for x in re.findall(r"[A-Za-zÀ-ÿëé']+", t[:30000]))
    sc = {k: sum(w[x] for x in v) for k, v in STOP.items()}
    lb_only = sum(w[x] for x in ("vun", "fir", "mat", "gëtt", "ginn", "dës", "gemeng", "sinn", "ass", "eng", "hir"))
    if lb_only > 0.25 * max(1, sc["de"]) and lb_only >= 15: return "lb"
    return max(("fr", "de"), key=lambda k: sc[k])

# ---------------------------------------------------------------- classification
REG_T = re.compile(r"(?i)\br[eèé]glement|\breglement|verordnung|\bstatuts?\b|polizeiverordnung|r[eèé]glementation|taxenreglement|gebührenordnung|"
                   r"ordre\s+int[eé]rieur|geschäftsordnung|bautenreglement|bautereglement|r\.?o\.?i\.?\b")
NOT_REG = [("state_act", re.compile(r"(?i)r[eèé]glement\s+grand[- ]ducal|großherzogliche\s+verordnung|grossherzogliche\s+verordnung|\bloi\s+du\s+\d|\bloi\s+modifi[ée]e\s+du|règlement\s+\(ue\)|règlement\s+\(ce\)|règlement\s+ministériel")),
           ("draft", re.compile(r"(?i)\b(avant[- ]?projet|projet\s+de\s+r[eè]glement|entwurf|draft|version\s+provisoire|proposition\s+de\s+r[eè]glement)\b")),
           ("brochure_or_guide", re.compile(r"(?i)\b(schoulbuet|schoulorganisatioun|schulorganisation|organisation\s+scolaire|brochure|broschüre|dépliant|faltblatt|flyer|guide\s+pratique|leitfaden|newsletter|magazine?|bulletin\s+communal|gemengebuet|info\s?gemeng)\b")),
           ("form", re.compile(r"(?i)\b(formulaire|formular|demande\s+d['e]|antrag\s+auf|fiche\s+d['e]\s*inscription|bulletin\s+d['e]\s*inscription|déclaration\s+de)\b")),
           ("minutes", re.compile(r"(?i)\b(rapport\s+de\s+la\s+séance|compte[- ]rendu|sitzungsbericht|gemengerotssitzung|séance\s+publique\s+du\s+conseil\s+communal\s+du)\b")),
           ("letter_to_citizens", re.compile(r"(?i)\b(chères\s+concitoyennes|chers\s+concitoyens|liebe\s+mitbürger|nous\s+nous\s+permettons\s+de\s+rappeler)")),
           ("correspondence", re.compile(r"(?i)\b(Är\s+Froe|Ärem\s+Br[eé]if|en\s+réponse\s+à\s+votre|votre\s+(lettre|courrier|question)\s+du|Ihr\s+Schreiben\s+vom|Ihre\s+Anfrage\s+vom)")),
           ("blank_deliberation_template", re.compile(r"(?i)séance\s+(publique\s+)?du\s*:?\s*\.{5,}|sitzung\s+vom\s*:?\s*\.{5,}|r[eèé]glement[-\s]\w*\s*(communal\s+)?du\s*\.{5,}")),
           ("event_rules", re.compile(r"(?i)r[eèé]glement\s+(de\s+(la\s+)?course|du\s+concours|du\s+jeu|de\s+participation|du\s+tournoi)|\bchallenge\b|\blaf\b|teilnahmebedingungen")),
           ("public_notice", re.compile(r"(?i)\b(il\s+est\s+porté\s+à\s+la\s+connaissance\s+du\s+public|avis\s+au\s+public|a\s+été\s+vot[ée]+e?\s+par\s+le\s+conseil\s+communal|"
                                         r"est\s+à\s+la\s+disposition\s+du\s+public|bekanntmachung|öffentliche\s+bekanntmachung|avis\s+aux\s+(résidents|riverains|habitants|citoyens|usagers)|tient\s+à\s+informer|information\s+der\s+kommission|information\s+de\s+la\s+commission|mitteilung\s+an\s+die\s+(bürger|einwohner))")),
           ("opinion_or_report", re.compile(r"(?i)\b(avis\s+de\s+la\s+commission|avis\s+du\s+conseil\s+d['’]état|rapport\s+justificatif|rapport\s+sur\s+le\s+projet|étude\s+d['’]évaluation|notice\s+environnementale|stratégische\s+umweltprüfung|évaluation\s+des\s+incidences)\b"))]
ENACT = re.compile(r"(?i)\bvu\s+(la|le|les|l['’]|l'article)|considérant|\barrête\b|\bdécide\b|conseil\s+communal|arrêt\s+du\s+conseil|der\s+gemeinderat|beschlie[sß]t|gemengerot|"
                   r"coll[eè]ge\s+(des\s+bourgmestre\s+et\s+)?échevin|schöffenrat|^\s*art(icle|ikel|\.)?\s*(1|1er|premier|I)\b|^\s*§\s*1\b|^\s*chapitre\s+(1|i|premier)\b", re.M)
REGISTER = re.compile(r"(?i)extrait\s+du\s+registre|registre\s+aux\s+d[ée]lib[ée]rations|beratungsregister|auszug\s+aus\s+dem\s+register")
REG_SUBJ = re.compile(r"(?i)r[eèé]glement[-\s]?taxes?|\btaxes?\s+(communales?|à\s+percevoir|du\s+service|d['’]|de\s+|sur\s+)|\b(re)?fixation\s+d['’]une\s+taxe|adaptation\s+de\s+la\s+taxe|"
                      r"r[ée]glementation\s+(temporaire\s+)?de\s+la\s+circulation|modification\s+temporaire|circulation\s+routi[eè]re|chapitre\s+[\divx]+\s*[:–-]")
def _not_cited(rx, s):
    """a match of rx in s that is not inside a 'Vu …' / 'Revu …' / 'Considérant …' citation line"""
    for m in rx.finditer(s):
        ls = s.rfind("\n", 0, m.start()) + 1
        if not re.match(r"(?i)\s*(re)?vu\b|\s*considérant|\s*gesehen", s[ls:m.start()]): return m
    return None
def classify(title, head, link=""):
    """('regulation', None) or ('excluded', reason). title = document title; head = first ~3000 characters of the cleaned text;
    link = the link text on the commune's page ('Règlement contre le bruit (brochure)')"""
    s = title + "\n" + head[:3000]
    register = REGISTER.search(head[:1500])
    # an extract of the deliberation register (council or collège) that adopts or amends a regulation, a tax chapter of the
    # règlement-taxes or a (temporary) traffic regulation names it in its 'Objet' / operative part, after the attendance list
    subj = REG_T.search(title) or REG_T.search(link or "") or REG_T.search(head[:600]) or \
        (register and (REG_T.search(head[:2500]) or REG_SUBJ.search(head[:2500])))
    if not subj: return "excluded", "not_a_regulation"
    if re.search(r"(?i)^\W*(relevé|liste|annexe|anlage|tableau)\b", title) or re.search(r"(?i)[-–]\s*(annexe|anlage)\s*\d*\s*$", title):
        if not re.search(r"(?im)^\s*art(icle|ikel|\.)\s*\d", head): return "excluded", "annex_only"
    n_art = len(heading_candidates(head.split("\n")))
    # a publication notice ('AVIS AU PUBLIC – il est porté à la connaissance du public …') is excluded unless the document also carries
    # the regulation's text (Pétange publishes the notice followed by the text)
    for k in ("brochure_or_guide", "public_notice", "draft"):
        if dict(NOT_REG)[k].search(link or "") and not (k == "public_notice" and n_art >= 3): return "excluded", k
    if dict(NOT_REG)["brochure_or_guide"].search(head[:300]): return "excluded", "brochure_or_guide"
    if not ENACT.search(head) and len(heading_candidates(head.split("\n"))) < 3: return "excluded", "no_enacting_text"     # a leaflet / notice about a regulation, not its text
    # an annex published on its own ('Relevé des colonnes … – Liste annexée au règlement concernant l'affichage public')
    if re.search(r"(?i)^\W*(relevé|liste|annexe|anlage|tableau)\b[^\n]{0,250}\n?[^\n]{0,150}\b(annex|anlage\s+zu)", head[:400]): return "excluded", "annex_only"
    for k, rx in NOT_REG:
        if k == "state_act":
            # a communal regulation cites grand-ducal regulations and laws in its preamble; only a title that is one is a state act
            # the title is the state act itself ('Règlement grand-ducal du …', 'Loi du …'), not a communal regulation citing one
            if rx.match(re.sub(r"^\W+", "", title)) or (rx.search(head[:300]) and not re.search(r"(?i)communal|commune|gemeinde|gemeng|conseil\s+communal|gemeinderat", head[:600])): return "excluded", k
        elif k in ("minutes",):
            if rx.search(title) or (rx.search(head[:400]) and not register): return "excluded", k
            # an agenda ('ordre du jour') without a deliberation-register header and without article text is a meeting document; a
            # register extract for one agenda point ('Point no 03 de l'ordre du jour – approbation du règlement …') is the adopted act
            if re.search(r"(?i)ordre\s+du\s+jour|tagesordnung", head[:400]) and n_art < 3 and \
                    not re.search(r"(?i)registre|délibération|beratungsregister|extrait|auszug", head[:1500]): return "excluded", k
        elif k == "event_rules":
            if rx.search(title) or rx.search(head[:300]): return "excluded", k
        elif k in ("letter_to_citizens", "blank_deliberation_template"):
            if rx.search(head[:1500]): return "excluded", k     # an unfilled deliberation form is not an adopted act
        elif k == "correspondence":
            if rx.search(head[:1500]) and n_art < 3: return "excluded", k
        elif k == "public_notice":
            if (rx.search(title) or rx.search(head[:1500])) and n_art < 3: return "excluded", k
        elif k == "opinion_or_report":
            # 'Vu l'avis de la commission des finances' (a citation) and the procedure block of an adopted act ('Avis de la commission des
            # bâtisses 19 septembre 2016 / Vote du conseil communal 28 octobre 2016') are not an opinion
            if (rx.search(title) or _not_cited(rx, head[:250])) and not re.search(r"(?i)vote\s+du\s+conseil\s+communal|^\s*le\s+conseil\s+communal\s*,", head[:1500], re.M): return "excluded", k
        elif rx.search(title) or rx.search(head[:250]): return "excluded", k
    return "regulation", None

# ---------------------------------------------------------------- dates
MON = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
       "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12, "januar": 1, "jänner": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4,
       "juni": 6, "juli": 7, "august": 8, "oktober": 10, "dezember": 12, "januar": 1, "mäerz": 3, "abrëll": 4, "juni": 6, "september": 9, "november": 11}
D_TXT = r"(\d{1,2})(?:er|\.|\s?ier)?\s*(" + "|".join(sorted(MON, key=len, reverse=True)) + r")\s+(\d{4})"
D_NUM = r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})"
def _iso(d, m, y):
    try: return datetime.date(int(y), int(m), int(d)).isoformat()
    except ValueError: return None
def _date(s):
    m = re.match(D_TXT, s, re.I)
    if m: return _iso(m.group(1), MON[m.group(2).lower()], m.group(3))
    m = re.match(D_NUM, s)
    return _iso(*m.groups()) if m else None
ADOPT = re.compile(r"(?i)((arrêté|voté|adopté|approuvé)e?\s+par\s+le\s+conseil\s+communal\s+(le|en\s+date\s+du|dans\s+sa\s+séance\s+du|en\s+sa\s+séance\s+du)|en\s+(sa\s+)?séance\s+(publique\s+)?du|délibération\s+du\s+conseil\s+communal\s+du|par\s+délibération\s+du|conseil\s+communal\s+du|"
                   r"r[eèé]glement\s+communal\s+(modifi[eé]\s+)?du|r[eèé]glement\s+(modifi[eé]\s+)?du|gemeinderatssitzung\s+vom|beschluss\s+des\s+gemeinderates?\s+vom|"
                   r"gemeinderat(es)?\s+vom|verordnung\s+vom|sitzung\s+vom|gemengerot\s+vum|beschloss\s+vum)\s*:?\s*(?P<d>" + D_TXT + "|" + D_NUM + ")")
# a title names the act's own date: 'Règlement sur les égouts publics du 22 mai 1978', 'Verordnung … vom 3. März 2019'
SESSION = re.compile(r"(?i)(registre\s+aux\s+d[ée]lib[ée]rations|extrait\s+du\s+registre|beratungsregister|sitzungsregister)[\s\S]{0,400}?(séance|sitzung)(\s+publique|\s+à\s+huis\s+clos|\s+öffentliche)?(\s+d['’]urgence)?(\s+du\s+conseil\s+communal)?\s+(du|vom)\s*:?\s*(?P<d>" + D_TXT + "|" + D_NUM + ")")
# the meeting date in the header of a register extract: 'Date de la réunion: 24 juin 2026' (Bettembourg collège), 'réunion du vendredi, 3 mai 2024'
MEETING = re.compile(r"(?im)(date\s+de\s+la\s+r[ée]union|r[ée]union\s+du(\s+(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche))?\s*,?|^\s*s[ée]ance\s+(publique\s+)?du)\s*:?\s*(?P<d>" + D_TXT + "|" + D_NUM + ")")
# the act's own adoption, stated in its text: 'le conseil communal, en sa séance du 30 janvier 2026, a adopté le présent règlement',
# 'Délibération du Conseil Communal de la Ville d'Esch-sur-Alzette du 8 juillet 2022', 'Vote du conseil communal 12/11/2024'
CLAUSE = re.compile(r"(?i)(délibération\s+du\s+conseil\s+communal[^\n]{0,80}?\bdu|par\s+sa\s+d[ée]lib[ée]rat\s?ion\s+du|édicté\s+par\s+le\s+conseil\s+communal\s+(le|en\s+date\s+du|dans\s+sa\s+séance\s+du)|vote\s+du\s+conseil\s+communal(\s*[-–][^\n]{0,40})?|vote\s+du\s+conseil\s+communal\s+du|"
                    r"(le\s+conseil\s+communal,?\s+)?(en|dans)\s+sa\s+séance\s+(publique\s+)?du|(arrêté|voté|adopté|approuvé)e?\s+par\s+le\s+conseil\s+communal\s+(le|en\s+date\s+du|dans\s+sa\s+séance\s+du|en\s+sa\s+séance\s+du)|"
                    r"gemeinderatssitzung\s+vom|beschluss\s+des\s+gemeinderates?\s+vom|gemengerot\s+vum|beschloss\s+vum)\s*:?\s*(?P<d>" + D_TXT + "|" + D_NUM + ")")
# the date of the version of a consolidated text: 'Version consolidée du 19 décembre 2025', 'Texte coordonné : conseil communal du 11 juillet 2025'
CONSOL = re.compile(r"(?i)(version\s+consolid[ée]e|texte\s+coordonn[ée])\s*(du|:)?\s*(conseil\s+communal\s+du\s*)?(?P<d>" + D_TXT + "|" + D_NUM + ")")
# the council's deliberation date in the approval appended to a tax regulation: 'Date délibération : 24/10/2025', 'Date de délibération du Conseil communal :
# 19 juin 2026', 'La délibération du 30 janvier 2026 prise par le conseil communal de la commune de Mondercange'
DELIB = re.compile(r"(?i)(date\s+(de\s+(la\s+)?)?d[ée]lib[ée]ration(\s+du\s+conseil\s+communal)?\s*:|la\s+d[ée]lib[ée]ration\s+du(?=\s*(" + D_TXT + "|" + D_NUM + r")\s+prise\s+par\s+le\s+conseil\s+communal))\s*(?P<d>" + D_TXT + "|" + D_NUM + ")")
def in_citation(t, pos):
    """pos lies in a 'Vu …' / 'Revu …' / 'Considérant …' clause (which may run over several lines, up to the previous ';' or blank line)"""
    st = max(t.rfind(";", 0, pos), t.rfind("\n\n", 0, pos), t.rfind(".\n", 0, pos), t.rfind(":\n", 0, pos))
    seg = t[st + 1:pos] if st >= 0 else t[max(0, pos - 400):pos]
    return bool(re.match(r"(?i)\W*((re)?vu\b|considérant|gesehen|nach\s+einsicht)", seg))
CITED = re.compile(r"(?i)(loi|r[eè]glement|arrêté|directive|convention|circulaire|code|constitution|délibération|décision|avis|version|modifi\w*|abrog\w*|abolition)\W+(\w+\W+){0,6}$")
TITLE_DATE = re.compile(r"(?i)(\b(du|vom|vum)\s+|\(\s*)(?P<d>" + D_TXT + "|" + D_NUM + ")")
APPROVAL = re.compile(r"(?i)(approuvé\w*|genehmigt)[^.]{0,120}?(ministre|minister|grand[- ]duc|großherzog)[^.]{0,80}?\b(le|am|du|vom)\s+(?P<d>" + D_TXT + "|" + D_NUM + ")")
def issuing_organ(t):
    """'college_echevinal' for an extract of the register of the collège des bourgmestre et échevins (temporary traffic regulations are
    within its own competence), 'conseil_communal' for the council register or text, else None"""
    h = t[:2500]
    co = re.search(r"(?i)(registre|beratungsregister)[\s\S]{0,200}?(coll[eè]ge\s+(des\s+bourgmestre\s+et\s+)?[ée]chevin|schöffenrat)", h)
    cc = re.search(r"(?i)(délibération|vote|séance\s+publique)\s+du\s+conseil\s+communal|registre\s+aux\s+délibérations\s+du\s+conseil\s+communal|^\s*le\s+conseil\s+communal\s*,", h, re.M)
    if co and cc and cc.start() < co.start(): return "conseil_communal"   # 'Délibération du Conseil Communal … du 8 juillet 2022' (Esch)
    if co: return "college_echevinal"
    if re.search(r"(?i)conseil\s+communal|gemeinderat|gemengerot", h): return "conseil_communal"
    return None
def act_dates(title, t, today=None):
    """(adoption_date, approval_date, basis). Date sanity: 1800 <= year, not after today, approval >= adoption."""
    today = today or datetime.date.today().isoformat()
    ok = lambda d: d and "1800-01-01" <= d <= today
    ad = None; basis = None
    m = ADOPT.search(title)
    if m and ok(_date(m.group("d"))): ad, basis = _date(m.group("d")), "title"
    if not ad:   # an extract of the deliberation register: the session date is the date of the vote (before a bare title date, which
        m = SESSION.search(t[:2500])   # can be the day a temporary measure applies: 'Modification temporaire du 17 octobre 2026')
        if m and ok(_date(m.group("d"))): ad, basis = _date(m.group("d")), "deliberation_session_date"
    if not ad:
        m = TITLE_DATE.search(title)
        if m and ok(_date(m.group("d"))): ad, basis = _date(m.group("d")), "title"
    if not ad:   # the meeting date in a register-extract header
        m = next((m for m in MEETING.finditer(t[:2500]) if not in_citation(t, m.start())), None)
        if m and ok(_date(m.group("d"))): ad, basis = _date(m.group("d")), "meeting_date"
    if not ad:   # the act's own adoption clause; a clause about another act ('du règlement-taxe général adopté par le conseil communal en
        # date du 21 décembre 2001') or inside a 'Vu …' citation is skipped; 'Vote du conseil communal' takes the latest (revisions follow)
        def own_clause(m):   # the clause is followed by its verb ('…, a adopté le présent règlement') before any other date
            after = t[m.end():m.end() + 100]; nd = re.search(D_TXT + "|" + D_NUM, after, re.I)
            v = re.search(r"(?i)\b(a|ont)\s+(adopté|arrêté|voté|approuvé)|présent", after)
            return bool(v) and (not nd or v.start() < nd.start())
        cands = []
        for m in CLAUSE.finditer(t[:6000]):
            d = _date(m.group("d")); before = t[max(0, m.start() - 90):m.start()]
            if not ok(d) or in_citation(t, m.start()): continue
            if re.search(r"(?i)r[eè]glement", before) and not re.search(r"(?i)présent", before) and not own_clause(m): continue
            cands.append((m, d))
        own = [c for c in cands if own_clause(c[0])]
        votes = [c for c in cands if re.match(r"(?i)vote", c[0].group(0))]
        if own: ad, basis = own[0][1], "text_adoption_clause"
    if not ad:   # 'Date délibération : 24/10/2025' / 'La délibération du … prise par le conseil communal' (approval appended to the text)
        m = next((m for m in DELIB.finditer(t) if not in_citation(t, m.start()) and ok(_date(m.group("d")))), None)
        if m: ad, basis = _date(m.group("d")), "deliberation_date"
    if not ad:   # a consolidated text: the date of its version
        m = next((m for m in CONSOL.finditer(t[:2500]) if ok(_date(m.group("d")))), None)
        if m: ad, basis = _date(m.group("d")), "consolidated_version_date"
    if not ad:   # a coordinated text headed 'Texte du 16 juin 1967 tel qu'il a été modifié': the date of the original text
        m = re.search(r"(?im)^\s*texte\s+du\s+(?P<d>" + D_TXT + "|" + D_NUM + r")\s+tel\s+qu", t[:1500])
        if m and ok(_date(m.group("d"))): ad, basis = _date(m.group("d")), "original_text_date"
    if not ad:
        pick = votes[-1] if votes else (cands[0] if cands else None)
        if pick: ad, basis = pick[1], "text_adoption_clause"
    if not ad:   # older clause forms ('séance publique du', 'adopté par le conseil communal le'); cited regulations ('règlement … du') excluded
        for m in ADOPT.finditer(t[:6000]):
            d = _date(m.group("d"))
            if not ok(d) or in_citation(t, m.start()): continue
            if re.match(r"(?i)r[eèé]glement", m.group(0)): continue        # a cited regulation ('Le règlement du 26 avril 2013 … est abrogé')
            if re.search(r"(?i)(abrog|remplac|modifi)\w*\s+(par\s+)?(la\s+)?(décision|délibération)?(\s+du(\s+conseil\s+communal\s+du)?)?\s*$", t[max(0, m.start() - 40):m.start()]): continue
            ad, basis = d, "text_adoption_clause"; break
    if not ad and not COVER.search(t[:1500]):   # dated document header 'Luxembourg, le 25 mai 1970' (the date the text was issued, not necessarily the vote)
        m = re.search(r"(?i)^[^\n]{0,40}\b[A-ZÀ-Ý][\w\-]+,\s+(le|den)\s+(?P<d>" + D_TXT + "|" + D_NUM + ")", t[:600], re.M)
        if m and ok(_date(m.group("d"))): ad, basis = _date(m.group("d")), "document_header_date"
    if not ad:   # a likely date in the opening text: the first date in the first 1,500 characters that is not cited ('Vu la loi du …',
        # 'règlement grand-ducal du …', 'modifié le …')
        for m in re.finditer(r"(?i)(?<!\d)(?P<d>" + D_TXT + "|" + D_NUM + ")", t[:1500]):
            d = _date(m.group("d"))
            if not ok(d) or in_citation(t, m.start()) or CITED.search(t[max(0, m.start() - 80):m.start()]): continue
            if re.search(r"(?i)(entrée\s+en\s+vigueur|en\s+vigueur\s+(le|au)|publié\w*\s+(du|le)|publication\s+(du|le)|à\s+partir\s+du|avec\s+effet\s+au)\s*:?\s*$", t[max(0, m.start() - 40):m.start()]): continue
            ad, basis = d, "opening_text_date"; break
    ap = None
    for m in APPROVAL.finditer(t):
        d = _date(m.group("d"))
        if ok(d) and (not ad or d >= ad): ap = d
    return ad, ap, basis

# ---------------------------------------------------------------- articles
# 'Art. 1er', 'Article 1', 'Art.1.', 'ARTICLE 2 -', 'Artikel 3', 'Art 4:', '§ 5' (case-insensitive; OCR-tolerant: 'Art. l er' / 'Art. I er' = 1er)
ARTICLE_LINE = re.compile(r"(?i)^\s*(?:[-–]\s*\d{1,3}\s*[-–]?\s*)?(?:[∗*•✱]\s*)?(?P<m>art(?:icle|ikel|\.|\b)|§)\s*(?P<n>\d{1,3}(?:/\d{1,3}){1,3}\b|\d{1,3}(?:\s?(?:er|ier|bis|ter|quater|[a-h]))?\b|1\s?er|[lI]\s?er\b|premier|first|[IVXL]{1,6}\b)\s*(?P<rest>.*)$")
REF = re.compile(r"(?i)^(de\s+la|du|des|de\s+l|der|des\s+gesetzes|vum|vun|et\s+\d|à\s+\d|bis\s+\d|und\s+\d|,|paragraphe|alinéa|absatz|al\.|du\s+règlement|de\s+la\s+loi|du\s+présent|précité|ci-dessus|ci-après)")
def _num(n):
    n = n.lower().replace(" ", "")
    if "/" in n: return int(n.split("/")[0]), n          # chapter / article ('Art. 7/1', 'ARTICLE 5/4/1'): number = chapter, label = path
    if n in ("1er", "ler", "ier", "premier", "first", "1ier"): return 1, "1"
    m = re.match(r"(\d+)(er|ier|bis|ter|quater|[a-h])?$", n)
    if m: return int(m.group(1)), m.group(1) + ({"er": "", "ier": ""}.get(m.group(2) or "", m.group(2) or ""))
    r = {"i": 1, "v": 5, "x": 10, "l": 50}; s = 0
    for i, c in enumerate(n):
        v = r.get(c, 0); s += -v if i + 1 < len(n) and r.get(n[i + 1], 0) > v else v
    return s, n.upper()
def heading_candidates(lines):
    out = []
    for i, l in enumerate(lines):
        m = ARTICLE_LINE.match(l)
        if not m: continue
        rest = m.group("rest").strip()
        if REF.match(rest): continue
        if len(rest) > 160 and not re.match(r"^[.:\-–—)]", rest): continue      # a sentence that starts with 'Article 3 du …'
        v, lab = _num(m.group("n"))
        if not v: continue
        sub = re.match(r"^\.(\d{1,2})\.?(?!\d)", rest)          # sub-article 'Art. 75.1.' (own heading, own label)
        if sub and lab.isdigit(): lab = f"{lab}.{sub.group(1)}"
        out.append((i, v, lab, m.group("m")))
    return out
def _is_toc(lines, i):
    """a table-of-contents entry: dot leaders, or a heading title followed by a page number ('Art. 3 Objet 4', 'Article 3 – Objet .... 4')"""
    l = lines[i]; m = ARTICLE_LINE.match(l); rest = m.group("rest") if m else l
    if re.search(r"\.{4,}|…{2,}|_{6,}", l) or re.search(r"\.{4,}\s*\d+\s*$", "\n".join(lines[i:i + 2])): return True
    return bool(re.search(r"[A-Za-zÀ-ÿ]{3,}[^\d]*\s\d{1,3}\s*$", rest)) and not re.search(r"(?i)\b(loi|règlement|article|art\.|du|de|vom|des|n°|no)\s*\d{1,3}\s*$", rest)
def dense_toc(lines, cands):
    """a column of bare heading lines is a table of contents: >= 3 bare candidates ('Article 7 :', 'ART. 14') within 8 lines, with only
    empty or short title-like lines between them (a body puts article text between its headings)"""
    bare = lambda i: not re.sub(r"[\s:.\-–]", "", ARTICLE_LINE.match(lines[i]).group("rest"))
    b = [c[0] for c in cands if bare(c[0])]; dense = set()
    for k in range(len(b) - 2):
        win = b[k:k + 3]
        if win[-1] - win[0] <= 8 and all(len(lines[j].strip()) <= 60 and not re.search(r"[.;:,]\s*$", lines[j].strip())
                                         for j in range(win[0], win[-1] + 1) if j not in win):
            dense.update(win)
    return dense
def chain(cands, lines):
    """the article sequence: candidates whose numbers rise 1, 2, 3 … (gaps <= 5 allowed); a number that restarts at 1 after >= 3
    articles starts a new block (a second copy / annex). Table-of-contents lines (dot leaders, page numbers) are skipped."""
    dense = dense_toc(lines, cands)
    cs = [c for c in cands if not _is_toc(lines, c[0]) and c[0] not in dense]
    blocks, cur, last = [], [], 0
    # the first block may start above 2 only when the text has no Art. 1 / 2 heading at all (a coordinated text whose first title
    # was repealed starts at 'Article 7'); otherwise a stray earlier number would swallow the real sequence
    late = not any(c[1] in (1, 2) for c in cs)
    def rising(j, v):   # the next two candidates continue from v (v, v+1 … v+2 each): a real jump or restart, not a stray reference
        nx = [c[1] for c in cs[j + 1:j + 3]]
        return len(nx) == 2 and v <= nx[0] <= v + 2 and nx[0] <= nx[1] <= nx[0] + 2
    for j, c in enumerate(cs):
        i, v, lab, mk = c
        hier = cur and "/" in lab and "/" in cur[-1][2] and _key(v, lab) > _key(cur[-1][1], cur[-1][2])   # 'Art. 1/1' -> 'Art. 1/2/1'
        if cur and len(cur) >= 3 and not hier and (v == 1 or (v < last and rising(j, v))): blocks.append(cur); cur, last = [], 0
        if (not cur and (v in (1, 2) or (late and not blocks) or (blocks and rising(j, v)))) or (cur and last < v <= last + 5) \
                or (cur and v == last and lab != cur[-1][2]) or (cur and v > last + 5 and rising(j, v)):
            cur.append(c); last = v
            # a range heading 'Art. 21 – Art 31 (abrogés …)' / 'Articles 21 à 31' continues the sequence from its upper bound
            rg = re.match(r"(?i)^\s*(?:[-–—]|à|bis)\s*(?:art(?:icle)?s?\.?\s*)?(\d{1,3})\b", ARTICLE_LINE.match(lines[i]).group("rest"))
            if rg and v < int(rg.group(1)) <= v + 60: last = int(rg.group(1))
    if cur: blocks.append(cur)
    blocks = [b for b in blocks if len(b) >= 2]
    # a block whose headings sit on (almost) adjacent lines is a table of contents when a later block repeats its numbers
    def toc_block(k):
        b = blocks[k]; d = sorted(y[0] - x[0] for x, y in zip(b, b[1:]))
        later = {c[2] for bb in blocks[k + 1:] for c in bb}
        if len({c[2] for c in b} & later) < 0.5 * len(b): return False
        # a TOC: headings on (almost) adjacent lines, or bodies that are only a heading title ('Art. 3 / Aménagement du domaine public')
        bodies = sorted(len(" ".join(l.strip() for l in lines[x[0] + 1:y[0]])) for x, y in zip(b, b[1:]))
        if (d and d[len(d) // 2] <= 3) or (bodies and bodies[len(bodies) // 2] < 80): return True
        # or a TOC with section titles and page numbers between the entries ('Art. 2 / Champ d'application / 6 / TITRE II / 7')
        ne = [l.strip() for l in lines[b[0][0]:b[-1][0] + 1] if l.strip()]
        pages = sum(1 for l in ne if re.fullmatch(r"\d{1,3}", l))
        return bool(bodies) and bodies[len(bodies) // 2] < 400 and pages >= 0.2 * len(ne)
    blocks = [b for k, b in enumerate(blocks) if not toc_block(k)]
    return blocks, len(cs) < len(cands)
CH_LINE = re.compile(r"^\s*(?:CHAPITRE|Chapitre|KAPITEL|Kapitel)\s+(?P<n>[IVX]{1,5}|\d{1,2})(?:\s*-\s*(?P<s>\d{1,2}))?(?=[\s.:–-]|$)(?!.*\.{4,})(?!.*\s\d{1,3}\s*$).{0,160}$")
def toc_chapter_run(lines, hits):
    """indices of chapter headings that belong to a table of contents: a run of >= 2 rising chapter headings with < 400 characters
    between consecutive ones (only contents entries under each), whose chapter numbers are repeated by later headings (the body).
    hits = [(line index, sortable key)] in text order; the last heading of a run ends where the numbering restarts."""
    toc, k = set(), 0
    while k < len(hits):
        run = [hits[k]]
        while k + len(run) < len(hits):
            nxt = hits[k + len(run)]
            if nxt[1] > run[-1][1] and len("\n".join(lines[run[-1][0] + 1:nxt[0]]).strip()) < 400: run.append(nxt)
            else: break
        later = {h[1] for h in hits[k + len(run):]}
        if len(run) >= 2 and len({h[1] for h in run} & later) >= max(2, 0.5 * len(run)): toc.update(h[0] for h in run)
        k += len(run)
    return toc
def chapter_split(lines):
    """a text without article headings that is organised in chapters ('Chapitre I. Ordre public' … 'Chapitre X'; a coordinated tax text
    'Chapitre I-1 : Règlement-taxe sur les chiens' … 'Chapitre VII-5'): one record per chapter, the text before the first chapter is the
    preamble. TOC lines (dot leaders, trailing page numbers) are not headings; the chapters must rise in order (I, II … or I-1, I-2, II-1 …),
    >= 3 of them, with bodies of their own (median >= 200 characters). None when the text does not qualify."""
    seq = []
    hits = [(i, m, (_num(m.group("n"))[0], int(m.group("s") or 0))) for i, l in enumerate(lines) for m in [CH_LINE.match(l)] if m]
    toc = toc_chapter_run(lines, [(i, k) for i, m, k in hits])     # contents entries are not chapters: the body headings are
    for i, m, k in hits:
        if i in toc: continue
        if not seq:
            if k in ((1, 0), (1, 1)): seq.append((i, m, k))
            continue
        lk = seq[-1][2]
        if (k[0] == lk[0] and k[1] == lk[1] + 1 and k[1] > 0) or (k[0] == lk[0] + 1 and k[1] == (1 if lk[1] else 0)): seq.append((i, m, k))
    if len(seq) < 3: return None
    # a part heading above the first chapter of its part ('Partie II : Culture et loisir' before 'Chapitre II-1') starts that chapter's
    # record, not the end of the previous one (same roman number as the chapter; TOC lines with dot leaders / page numbers excluded)
    seq = [(i, m, k, i) for i, m, k in seq]
    for j, (i, m, k, _) in enumerate(seq):
        if k[1] > 1 or (j and seq[j - 1][2][0] == k[0]): continue
        lo = seq[j - 1][0] + 1 if j else 0
        for q in range(i - 1, lo - 1, -1):
            pm = re.match(r"^\s*(?:PARTIE|Partie|TEIL|Teil)\s+([IVX]{1,5}|\d{1,2})\s*(?:[:.\-–].{0,120})?$", lines[q])
            if pm and _num(pm.group(1))[0] == k[0] and not re.search(r"\.{4,}|\s\d{1,3}\s*$", lines[q]):
                seq[j] = (q, m, k, i); break
    ends = [x[0] for x in seq[1:]] + [len(lines)]
    bodies = [("\n".join(lines[i:e])).strip() for (i, m, k, h), e in zip(seq, ends)]
    if sorted(len(b) for b in bodies)[len(bodies) // 2] < 200: return None
    recs = []; pre = "\n".join(lines[:seq[0][0]]).strip()
    if pre: recs.append(("0", "", pre))
    for (i, m, k, h), b in zip(seq, bodies):
        recs.append(("chapitre-" + m.group("n") + (f"-{m.group('s')}" if m.group("s") else ""), lines[h].strip()[:200], b))
    return recs
def split_articles(t):
    """[(label, title_line, body)], coverage, info. Label '0' = preamble; repeated blocks get 'bK.N'."""
    lines = t.split("\n"); cands = heading_candidates(lines)
    blocks, toc = chain(cands, lines)
    if not blocks:
        ch = chapter_split(lines)
        if ch: return ch, 1.0, dict(candidates=len(cands), blocks=0, toc_lines_skipped=toc, chapters=len(ch) - 1)
        return [("0", "", t)], 1.0, dict(candidates=len(cands), blocks=0, toc_lines_skipped=toc)
    starts = []
    for k, b in enumerate(blocks):
        for (i, v, lab, mk) in b: starts.append((i, lab if k == 0 else f"b{k + 1}.{lab}", mk))
    # annexes after the last article ('ANNEXE 2: DISPOSITIONS PARTICULIÈRES', 'Anlage 1') are records of their own
    an = [(i, f"annexe-{m.group(2)}", "annexe") for i, l in enumerate(lines) if i > max(x[0] for x in starts)
          for m in [re.match(r"^\s*(ANNEXE|Annexe|ANLAGE|Anlage)\s+([IVX]{1,5}|\d{1,2})\b(\s*[:.\-–]|\s+[A-ZÀ-Ý]|\s*$)(?!.*\.{4,})(?!.*\s\d{1,3}\s*$)", l)] if m]
    # a chapter that follows the last article without article headings of its own (traffic regulations: 'CHAPITRE II' = street tables)
    an += [(i, f"chapitre-{m.group(2)}", "chapitre") for i, l in enumerate(lines) if i > max(x[0] for x in starts)
           for m in [re.match(r"^\s*(CHAPITRE|KAPITEL)\s+([IVX]{1,5}|\d{1,2})\b\s*([:.\-–].*)?$", l)] if m]
    an.sort()
    starts += [a for a in an if not any(a[1] == b[1] for b in an[:an.index(a)])]
    starts.sort()
    recs = []
    pre = "\n".join(lines[:starts[0][0]]).strip()
    # a long preamble that holds chapters of its own ('Chapitre 1 Bâtisses' … 'Chapitre 10 Energie' of a coordinated tax regulation,
    # each with a tariff table and no article headings) is split on those chapter headings (TOC lines with dot leaders / page numbers excluded)
    if len(pre) > 8000:
        ch = [(i, m.group(1)) for i, l in enumerate(lines[:starts[0][0]]) for m in [re.match(r"^\s*(?:CHAPITRE|Chapitre|KAPITEL|Kapitel)\s+(\d{1,2}|[IVX]{1,5})\b(?!.*\.{4,})(?!.*\s\d{1,3}\s*$).{0,120}$", l)] if m]
        toc_ch = toc_chapter_run(lines, [(i, _num(n)[0]) for i, n in ch])
        seq = []
        for i, n in [x for x in ch if x[0] not in toc_ch]:
            v = _num(n)[0]
            if (not seq and v == 1) or (seq and v == seq[-1][2] + 1): seq.append((i, n, v))
        # only chapters with bodies of their own: a TOC lists 'Art. 3 Aménagement …' lines under each chapter and has short entries
        ends = [x[0] for x in seq[1:]] + [starts[0][0]]
        lens = sorted(len("\n".join(lines[i:e]).strip()) for (i, n, v), e in zip(seq, ends))
        arts = sum(1 for l in lines[seq[0][0]:starts[0][0]] if ARTICLE_LINE.match(l)) if seq else 0
        if len(seq) >= 3 and arts == 0 and lens[len(lens) // 2] >= 300:
            starts = [(i, f"chapitre-{n}", "chapitre") for i, n, v in seq] + starts
            pre = "\n".join(lines[:seq[0][0]]).strip()
    if pre: recs.append(("0", "", pre))
    seen = collections.Counter()
    for j, (i, lab, mk) in enumerate(starts):
        e = starts[j + 1][0] if j + 1 < len(starts) else len(lines)
        body = "\n".join(lines[i:e]).strip(); seen[lab] += 1
        if seen[lab] > 1: lab = f"{lab}#{seen[lab]}"
        recs.append((lab, lines[i].strip()[:200], body))
    cov = sum(len(r[2]) for r in recs) / max(1, len(t.strip()))
    nums = [v for (i, v, lab, mk) in blocks[0]]; gaps = [(a, b) for a, b in zip(nums, nums[1:]) if b - a > 1]
    mk = collections.Counter(re.sub(r"\.", "", m.lower()) for (_, _, _, m) in blocks[0]).most_common(1)[0][0]
    return recs, cov, dict(candidates=len(cands), blocks=len(blocks), gaps=gaps, toc_lines_skipped=toc, marker=mk)
def _key(v, lab):
    return tuple(int(x) for x in lab.split("/")) if "/" in lab and all(x.isdigit() for x in lab.split("/")) else (v,)
def loose_heading_run(body):
    """longest run of >= 3 rising 'Art./Article/Artikel N' line starts inside one record (independent of the splitter's chain rules;
    references and TOC lines excluded; a run whose headings sit on (almost) adjacent lines, median spacing <= 3, is a table of contents).
    Hierarchical numbers ('Art. 5/4/1') rise as paths."""
    lines = body.split("\n"); best = 0; run = []; last = None
    cands = heading_candidates(lines); dense = dense_toc(lines, cands)
    def score(r):
        if len(r) < 3: return len(r)
        d = sorted(y - x for x, y in zip(r, r[1:]))
        bodies = sorted(len(" ".join(l.strip() for l in lines[x + 1:y])) for x, y in zip(r, r[1:]))
        if d[len(d) // 2] <= 3 or bodies[len(bodies) // 2] < 80: return 0   # a TOC: adjacent headings or title-only bodies
        ne = [l.strip() for l in lines[r[0]:r[-1] + 1] if l.strip()]   # or section titles and page numbers between the entries
        return 0 if bodies[len(bodies) // 2] < 400 and sum(1 for l in ne if re.fullmatch(r"\d{1,3}", l)) >= 0.2 * len(ne) else len(r)
    for i, v, lab, mk in cands:
        if _is_toc(lines, i) or i in dense: continue
        k = _key(v, lab)
        if last is not None and last < k and k[0] <= last[0] + 3: run.append(i)
        else: best = max(best, score(run)); run = [i]
        last = k
    return max(best, score(run))
