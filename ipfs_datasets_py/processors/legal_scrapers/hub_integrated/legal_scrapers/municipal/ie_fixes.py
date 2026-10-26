"""Ireland bye-laws: text layer, cleaning, classification, dates, issuing organ, article splitter. Self-contained; the generic text-layer and
encoding helpers (pdftotext without OCR, C1 / private-use mapping, look-alike letters, garbled-OCR rate) are the same as in the other
municipal builds."""
import re, subprocess, unicodedata, collections, zipfile, html, os, shutil, tempfile

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
LOOK.update({"ί": "í", "ό": "ó", "ά": "á", "έ": "é", "ύ": "ú", "Ί": "Í", "Ό": "Ó", "Ά": "Á", "Έ": "É"})   # Irish fadas set in a Greek font ('Chorcaί')
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


# ---------------------------------------------------------------- HTML pages that hold the bye-law text itself
def html_main_text(h):
    """the main content of a council page as text (block elements on their own lines): <main> / <article> / role=main, else <body>;
    navigation, header, footer, scripts, forms and cookie banners removed"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(h, "html.parser")
    for x in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "aside", "svg", "button", "iframe"]): x.decompose()
    for x in soup.select("[class*=cookie],[id*=cookie],[class*=breadcrumb],[class*=share],[class*=related],[class*=feedback]"): x.decompose()
    main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article") or soup.body or soup
    # link lists inside the main area (Cork City's 'news room' listing under every notice): blocks with >= 5 links whose link text is
    # > 70 % of their text. Innermost first, so a block that holds the bye-law text and one such list keeps the text.
    for b in reversed(main.find_all(["ul", "ol", "div", "section", "table", "nav"])):
        if getattr(b, "decomposed", False): continue
        links = b.find_all("a")
        if len(links) < 5: continue
        tx = len(b.get_text(" ", strip=True)); lt = sum(len(x.get_text(" ", strip=True)) for x in links)
        if tx and lt / tx > 0.7: b.decompose()
    for br in main.find_all("br"): br.replace_with("\n")
    for b in main.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "section", "ol", "ul", "dd", "dt"]):
        b.insert_before("\n"); b.insert_after("\n")
    t = main.get_text("")
    t = "\n".join(l for l in t.split("\n") if not re.search(r"(?i)(our\s+website\s+uses\s+cookies|^\s*(manage|accept\s+all|reject\s+all)\s+cookies\s*$|cookie\s+policy\s+page)", l)
                  and not re.fullmatch(r"(?i)\s*(public\s+notices|useful\s+links|related\s+(pages|links|content)|share(\s+this(\s+page)?)?|back\s+to\s+top)\s*", l))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t\u00a0]+", " ", t)).strip()
STRONG = re.compile(r"(?i)may\s+be\s+cited\s+as|hereby\s+makes?|in\s+exercise\s+of\s+the\s+powers|common\s+seal")

# ---------------------------------------------------------------- documents
def docx_text(path):
    """paragraph text of a .docx (word/document.xml; tables as lines), '' when unreadable"""
    try:
        with zipfile.ZipFile(path) as z: x = z.read("word/document.xml").decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError, OSError): return ""
    x = re.sub(r"<w:tab/>", "\t", x); x = re.sub(r"<w:br[^>]*/>", "\n", x)
    paras = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", x, re.S):
        paras.append(html.unescape("".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", p))))
    return "\n".join(paras)
def doc_text(path, timeout=180):
    """legacy .doc via LibreOffice headless conversion to text (no OCR); '' when it fails"""
    d = tempfile.mkdtemp(prefix="iedoc_")
    try:
        subprocess.run(["soffice", "--headless", f"-env:UserInstallation=file://{d}/profile", "--convert-to", "txt:Text (encoded):UTF8",
                        "--outdir", d, path], capture_output=True, timeout=timeout)
        out = os.path.join(d, os.path.splitext(os.path.basename(path))[0] + ".txt")
        return open(out, encoding="utf-8", errors="replace").read() if os.path.exists(out) else ""
    except (subprocess.TimeoutExpired, OSError): return ""
    finally: shutil.rmtree(d, ignore_errors=True)
def doc_any(path):
    ext = path.rsplit(".", 1)[-1].lower()
    if path.endswith(".html.txt"): return open(path, encoding="utf-8").read(), None      # main text of an HTML page (build_ie_municipal)
    if ext == "pdf": return pdf_text(path), pdf_pages(path)
    if ext == "docx": return docx_text(path), None
    if ext == "doc": return doc_text(path), None
    return "", None

def text_quality(t, pages=None):
    letters = len(re.findall(r"[A-Za-zÀ-ÿ]", t))
    if "(cid:" in t: return False, "bad_text_layer_cid"
    if letters < 300: return False, "no_text_layer_scanned"            # image-only PDF: no OCR
    if pages and letters < 120 * pages * 0.5 and letters < 4000: return False, "no_text_layer_mostly_scanned"
    if t.count("\ufffd") > 0.01 * letters: return False, "bad_text_layer_replacement_chars"
    words = re.findall(r"[A-Za-zÀ-ÿ]{2,}", t)
    if words and sum(1 for w in words if not re.search(r"[aeiouyáéíóúAEIOUYÁÉÍÓÚ]", w)) > 0.35 * len(words): return False, "bad_text_layer_broken_font"
    if garble_rate(t) > 50: return False, "garbled_ocr_text_layer"
    return True, None

# ---------------------------------------------------------------- cleaning
PAGE_NO = re.compile(r"(?i)^\s*((page|pg\.?|leathanach)\s*)?\d{1,3}\s*((/|of|de)\s*\d{1,3})?\s*$|^\s*-\s*\d{1,3}\s*-\s*$")
SIG = re.compile(r"(?im)^.*(digitally\s+signed|signed\s+by\s*:|Reason\s*:|Adobe\s+Acrobat|Signature\s+(valid|not\s+verified)|DocuSign\s+Envelope).*$")
def strip_furniture(t):
    """page numbers, signature-box lines, and short header / footer lines repeated on >= half of the pages (>= 3 pages)"""
    pages = t.split("\f"); n = len([p for p in pages if p.strip()]); rep = set()
    if n >= 3:
        c = collections.Counter()
        for p in pages:
            ls = [l.strip() for l in p.split("\n") if l.strip()]
            for l in set(ls[:3] + ls[-3:]):
                if len(l) <= 100 and not HEAD.match(l): c[re.sub(r"\d+", "#", l)] += 1
        rep = {k for k, v in c.items() if v >= max(3, n / 2)}
    out = []
    for p in pages:
        for l in p.split("\n"):
            s = l.strip()
            if s and (re.sub(r"\d+", "#", s) in rep or PAGE_NO.match(s) or SIG.match(s)): continue
            out.append(l)
        out.append("")
    return "\n".join(out)
def fix_replacement_chars(t):
    t = re.sub(r"(?<=[A-Za-z])\ufffd(?=(s|t|ll|re|ve|d|m)\b)", "’", t)          # Council�s -> Council’s
    return re.sub(r"(?<![\w\ufffd])\ufffd+(?![\w\ufffd])", "", t)
def clean_text(raw):
    t = map_pua(map_c1(raw)); t = strip_furniture(t); t = t.replace("\f", "\n")
    t = unicodedata.normalize("NFKC", t)
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b\u200c\u200d\u2060\ufeff\u00ad]", "", t)
    t = unicodedata.normalize("NFC", "".join(c for i, c in enumerate(t) if not (unicodedata.category(c) == "Mn" and (i == 0 or not t[i - 1].isalpha()))))
    t = fix_lookalikes(t); t = fix_replacement_chars(t)
    t = re.sub(r"[ \t\u00a0]+", " ", t); t = re.sub(r" *\n *", "\n", t); t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

# ---------------------------------------------------------------- sealing / signature block
SEAL = re.compile(r"(?im)^[^\n]{0,60}\b(given\s+under\s+the\s+(common\s+)?seal|(made\s+(and\s+adopted\s+)?|adopted\s+)under\s+the\s+(common\s+)?seal|sealed\s+and\s+(made|adopted)|present\s+when\s+the\s+(common\s+)?seal|the\s+(common\s+)?seal\s+of\s+[^\n]{0,80}(was|is)\s+(hereunto\s+)?affixed|"
                  r"sealed\s+with\s+the\s+(common\s+)?seal|in\s+witness\s+whereof|faoi\s+shéala|séala\s+coiteann)")
SEAL_END = re.compile(r"(?m)^\s*((FIRST|SECOND|THIRD|FOURTH|FIFTH|\d+(ST|ND|RD|TH)?)\s+)?(SCHEDULE|APPENDIX|ANNEX|PART\s+[\dIVX]+|EXPLANATORY\s+NOTE|First\s+Schedule|Schedule\s+\d+|Schedule\b|Appendix\b)")
CLOSE = re.compile(r"(?im)^[^\n]{0,40}\b(cathaoirleach|chief\s+executive|county\s+manager|city\s+manager|meetings?\s+administrator|"
                   r"mayor\s+of|lord\s+mayor|cathaoirleach|authori[sz]ed\s+officer|signed\s*:|(s\.)\s)[^\n]{0,60}$")
def strip_seal(t):
    """(text, seal_text): the sealing and signature block ('GIVEN under the Common Seal of … this 12th day of March 2019', 'Present when the
    Common Seal was affixed:', Cathaoirleach / Chief Executive / Meetings Administrator) is removed, up to the next Schedule / Appendix / Part
    heading or the end; the date inside it is kept by the caller. A block in the first third of the text is not a closing block."""
    m = None
    for x in SEAL.finditer(t):
        if x.start() >= len(t) * 0.33 or len(t) - x.start() < 2500: m = x; break
    if not m: return t, None
    e = SEAL_END.search(t, m.end()); end = e.start() if e else len(t)
    seal = t[m.start():end].strip()
    if len(seal) > 3000: seal = seal[:3000]; end = m.start() + len(seal)   # never swallow a large body
    return (t[:m.start()].rstrip() + ("\n\n" + t[end:].lstrip() if end < len(t) else "")).strip(), seal

# ---------------------------------------------------------------- language
STOP = {"en": "the of and to in a is be for by or any shall on as with council this that which are such person not".split(),
        "ga": "agus an na ar le do go is seo ag ina ón aon nó dá chomhairle contae fodhlíthe faoi mar sin den".split()}
def language(t):
    w = collections.Counter(x.lower() for x in re.findall(r"[A-Za-zÀ-ÿáéíóúÁÉÍÓÚ']+", t[:30000]))
    sc = {k: sum(w[x] for x in v) for k, v in STOP.items()}
    return max(sc, key=sc.get)

# ---------------------------------------------------------------- classification
BYELAW = re.compile(r"(?i)bye[\s\-]*laws?|byelaws?|by[\s\-]laws?|fodhl[ií]")
DRAFT = re.compile(r"(?i)\bdraft\b|\bproposed\b|\bdréacht|public\s+consultation|\bconsultation\b|submissions?\s+(may|are|should|can)\s+be\s+made|"
                   r"invit\w+\s+(submissions|observations)|observations\s+(and|or)\s+submissions|notice\s+of\s+(intention|intent)|intends?\s+to\s+make")
ENACT = re.compile(r"(?i)(hereby\s+make[s]?|in\s+exercise\s+of\s+the\s+powers?\s+conferred|in\s+exercise\s+of\s+(its|the)\s+powers|"
                   r"have\s+made\s+the\s+following|makes?\s+the\s+following\s+bye|made\s+(by|at)\s+[^.\n]{0,120}(council|meeting|members)|"
                   r"adopted\s+(by|at)\s+[^.\n]{0,120}(council|meeting|members)|common\s+seal|under\s+section\s+199|sections?\s+199|"
                   r"may\s+be\s+cited\s+as|shall\s+come\s+into\s+(operation|force|effect)|feidhmiú\s+(dó\s+|di\s+|dí\s+)?na\s+gcumhacht|"
                   r"déan(ann|tar)\s+[^.]{0,200}?leis\s+seo|féad(?:far|tar)\s+[^.]{0,160}?a\s+lua|leis\s+seo,?\s+trí\s+na\s+cumhacht|i\s+láthair\s+nuair\s+a\s+greamaíodh\s+séala|tugtar\s+de\s+chumhacht|fógraítear\s+leis\s+seo|déanann\s+[^.]{0,300}?na\s+fo-?dhlíthe\s+seo|fo-?dhlíthe\s+[^.]{0,80}?(?:déanta|a\s+rinneadh)|arna\s+ndéanamh\s+ag\s+c(?:h)?omhairle|(?m:^\s*SÉALA\s*$)|teacht\s+i\s+(bhfeidhm|ngníomh)|séala\s+(coiteann|comhchoiteann))")
NOTICE = re.compile(r"(?i)^\W*(public\s+)?notice\b|notice\s+is\s+hereby\s+given|fógra\s+poiblí|take\s+notice")
FORM = re.compile(r"(?i)application\s+form|\bform\s+[A-Z]?\d|please\s+(complete|tick|print)|applicant['’]s?\s+(name|signature)|for\s+office\s+use\s+only|block\s+capitals")
GUIDE = re.compile(r"(?i)frequently\s+asked|\bFAQs?\b|guidance\s+notes?|guide\s+to\b|information\s+leaflet|leaflet|brochure|newsletter|annual\s+report|"
                   r"minutes\s+of\s+(the\s+)?(meeting|proceedings)|agenda\b|chief\s+executive['’]?s\s+report|report\s+on\s+(the\s+)?(submissions|consultation)")
MINUTES = re.compile(r"(?i)minutes\s+of\s+(the\s+)?(\w+\s+){0,3}meeting|proceedings\s+of\s+(the\s+)?(\w+\s+){0,3}meeting|^\s*present\s*:", re.M)
MAP = re.compile(r"(?i)\bmap\b|drawing\s+no|\bdwg\b|legend\b|scale\s+1\s*:\s*\d")
STATE = re.compile(r"(?i)^\W*(S\.?I\.?\s+No\.?\s*\d+\s+of\s+\d{4}|statutory\s+instruments?)\b|\bact\s+\d{4}\s*$")
TEMPLATE_YEAR = re.compile(r"(?<![\w/])(?:19|20)(?:XX|xx|__+|\.\.|\[\s*\d?\s*\])(?![\w])|\b(?:19|20)\d?X\b|\[\s*year\s*\]|\byyyy\b", re.I)
# only in a date context (the making / commencement / sealing line); 'Cemetery Bye-Laws 202X' on a fixed-payment form in an appendix is not
TEMPLATE_DATE = re.compile(r"(?i)(day\s+of|dated|come\s+into\s+(?:operation|force|effect)|commenc\w*|made\s+on|adopted\s+on)[^.\n]{0,60}?(?:" + TEMPLATE_YEAR.pattern + ")")
PLACEHOLDER = re.compile(r"(?i)(come\s+into\s+(operation|force|effect)|commence\w*|this)\s+(on\s+)?(the\s+)?(XX+|_{2,}|\.{3,}|\[\s*date\s*\])")
def classify(title, t, link="", today="9999"):
    """(kind, reason): 'byelaw' or an exclusion reason. A bye-law text is enacted ('in exercise of the powers conferred …', 'hereby makes the
    following Bye-Laws', a sealing clause, 'may be cited as') and is not a draft / consultation / notice of intention, form, guide or minutes."""
    head = t[:4000]; hl = (title + "\n" + link + "\n" + head)
    words = len(re.findall(r"\w+", t))
    if FORM.search(head) and not ENACT.search(t[:8000]): return "excluded", "form"
    if MINUTES.search(head[:1500]) and not re.search(r"(?i)hereby\s+make|may\s+be\s+cited\s+as", t): return "excluded", "minutes"
    # a privacy / data-protection statement about bye-laws ('PRIVACY STATEMENT for administration and enforcement of the … Bye-Laws 2020')
    if re.search(r"(?i)\b(privacy\s+(statement|notice|policy)|data\s+protection\s+(statement|notice))\b", title + " " + head[:600]) \
            and not re.search(r"(?i)hereby\s+make|may\s+be\s+cited\s+as", t): return "excluded", "privacy_statement"
    if GUIDE.search(title + " " + link) or (GUIDE.search(head[:800]) and not ENACT.search(t[:8000])): return "excluded", "guide_or_report"
    dr = DRAFT.search(title + " " + link) or DRAFT.search(head[:1500])
    # an adopted text whose front matter mentions its 'Consultation Process' (Longford Parks 2024) or whose link says 'Adopted … Signed'
    # (Roscommon speed limits 2020) is made, not a draft: only a 'draft' / 'proposed' in its own title or link keeps it out then
    adopted = re.search(r"(?i)\badopted\b|\bsigned\b|\bglactha\b", title + " " + link + " " + head[:1500])
    if dr and adopted and not re.search(r"(?i)\b(draft|proposed|dréacht)\b", title + " " + link): dr = None
    if dr: return "excluded", "draft_or_consultation"
    # a text for the current year whose commencement / sealing dates are still placeholders ('come into operation on the XX of XXXX 2026',
    # 'this XX day of XXX 2026') is not yet made: published for consultation or awaiting confirmation
    yrs = re.findall(r"\b(20\d\d)\b", title + " " + head[:600])
    if PLACEHOLDER.search(t) and re.search(r"(?i)\bXX+\b", t) and yrs and max(yrs) >= today[:4]: return "excluded", "draft_unmade_placeholder_dates"
    # a template year ('come into effect on the ___ day of ___ 20XX', 'Dated this … 20XX', '19__'): never a made text, whatever the year
    if TEMPLATE_DATE.search(t): return "excluded", "draft_unmade_placeholder_dates"
    if NOTICE.search(head[:600]) and not re.search(r"(?i)may\s+be\s+cited\s+as|hereby\s+make", t): return "excluded", "public_notice"
    # a short notice / advert of adoption ('THE MUNICIPAL DISTRICT OF DUNDALK / PUBLIC NOTICE / … Bye-Laws 2023 / The Members … in exercise of
    # the powers …' in ~200 words): it announces the bye-laws, it is not their text
    if words < 500 and (re.search(r"(?im)^\W*(public\s+)?notice\b|fógra\s+poiblí", head[:600])
                        or re.search(r"(?i)public[\s\-_]*notice|\badvert|notice[\s\-_]*(for|of)[\s\-_]*adopt", link + " " + title)): return "excluded", "public_notice"
    if not BYELAW.search(hl) and not BYELAW.search(t[:20000]): return "excluded", "not_a_byelaw"
    if not ENACT.search(t): return "excluded", "no_enacting_text"
    if words < 120: return "excluded", ("map_or_schedule_only" if MAP.search(t) else "too_short")
    if MAP.search(title + " " + link) and words < 600 and not re.search(r"(?i)may\s+be\s+cited|hereby\s+make", t): return "excluded", "map_or_schedule_only"
    return "byelaw", None

# ---------------------------------------------------------------- dates
MON = {m: i + 1 for i, m in enumerate("january february march april may june july august september october november december".split())}
MON.update({m[:3]: i for m, i in list(MON.items())}); MON["sept"] = 9
GA_MON = {"eanáir": 1, "feabhra": 2, "márta": 3, "aibreán": 4, "bealtaine": 5, "meitheamh": 6, "iúil": 7, "lúnasa": 8, "meán fómhair": 9,
          "deireadh fómhair": 10, "samhain": 11, "nollaig": 12}
_M = r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\.?"
D_TXT = r"(\d{1,2})\s?(?:st|nd|rd|th)?\.?(?:\s+day)?(?:\s+of)?\s+" + _M + r",?\s+(\d{4})|" + _M + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})"
D_NUM = r"(\d{1,2})[./](\d{1,2})[./](\d{4})"
DATE = re.compile(r"(?i)(?<![\w/])(?:" + D_TXT + "|" + D_NUM + r")(?![\w/])")
def _iso(d, m, y):
    try:
        import datetime; return datetime.date(int(y), int(m), int(d)).isoformat()
    except (ValueError, TypeError): return None
def _norm_mon(x):
    x = x.lower().rstrip(".")
    return MON.get(x) or MON.get(x[:3])
def parse_date(s):
    """first date in s as ISO ('12th day of March, 2019', 'March 12, 2019', '12/03/2019' = day/month/year)"""
    m = DATE.search(s)
    if not m: return None
    g = m.groups()
    if g[0]: return _iso(g[0], _norm_mon(g[1]), g[2])
    if g[3]: return _iso(g[4], _norm_mon(g[3]), g[5])
    return _iso(g[6], g[7], g[8])
_D = r"(?:(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday),?\s+(?:the\s+)?)?(?P<d>(?:" + D_TXT + "|" + D_NUM + r"))"   # 'on Monday 1st March 2010' 
MEET = re.compile(r"(?i)(made|adopted|passed|approved|confirmed)\s+(?:by\s+[^.;]{0,160}?\s+)?(?:at\s+(?:its|the|a)\s+[^.;]{0,80}?meeting(?:\s+of\s+[^.;]{0,100}?)?\s+(?:held\s+)?on\s+(?:the\s+)?|on\s+(?:the\s+)?)" + _D)
MEET2 = re.compile(r"(?i)(?:at\s+(?:its|the|a)\s+[^.;\n]{0,80}?meeting\s+(?:held\s+)?on\s+(?:the\s+)?)" + _D + r"[^.]{0,200}?(?:makes?|made|adopted|resolved|passed)")
RESOL = re.compile(r"(?i)(?:by\s+)?resolution\s+(?:of\s+[^.;]{0,120}?\s+)?(?:dated|passed\s+on|of)\s+(?:the\s+)?" + _D)
SEAL_DATE = re.compile(r"(?i)(this|on\s+the|dated\s+(this|the)?)\s*" + _D)
# 'Approved by Longford County Council: 10 September 2025' / 'Adopted by the Members of X Municipal District, 3rd May 2021'
APPROVED = re.compile(r"(?i)\b(approved|adopted|made)\s+by\s+(?:the\s+)?[^.;\n]{0,80}?(council|members|district)\s*[:,–-]\s*(?:on\s+)?(?:the\s+)?" + _D)
# a sealing clause left in the body ('MADE AND ADOPTED UNDER THE COMMON SEAL OF WEXFORD COUNTY COUNCIL THIS 10th DAY OF July 2023')
SEAL_IN_TEXT = re.compile(r"(?i)\b(made\s+and\s+adopted|adopted|made|given|sealed)\s+under\s+the\s+(common\s+)?seal\b[^.]{0,160}?(?:this|on\s+the|dated(?:\s+this|\s+the)?)\s*" + _D)
# the making phrase in the text itself: 'Made and Adopted by Roscommon County Council on this 26th day of September, 2011', 'resolved to make
# these Bye-Laws at its meeting on 14 April, 2014', 'Subject to the adoption of the … Bye-Laws by Members … at a plenary meeting on the 14th March
# 2022', 'Adopted 27th July, 2009'
MAKING = re.compile(r"(?i)\b(?:made\s+and\s+adopted|adopted|resolved\s+to\s+make|adoption\s+of|made\s+pursuant\s+to)\b(?:[^.;]{0,160}?\b(?:held\s+)?on\s+(?:this\s+|the\s+)*|\s+)" + _D)
# a document-control table: 'Date of Adoption' / '10 April 2024', 'Implementation Date' / '1 June 2024' (Longford parks 2024)
ADOPT_FIELD = re.compile(r"(?i)\bdate\s+of\s+adoption\s*[:\-–]?\s*" + _D)
IMPL_FIELD = re.compile(r"(?i)\b(?:implementation|commencement)\s+date\s*[:\-–]?\s*" + _D)
# 'Dated this the 4th day of August 2015.' as a line of its own (Carlow liquor 2015)
DATED = re.compile(r"(?im)^\s*dated\s+(?:this\s+)?(?:the\s+)?" + _D)
COMMENCE = re.compile(r"(?i)(come\s+into\s+(operation|force|effect)|enter\s+into\s+force|commence|effective\s+from|take\s+effect)\s+(on|from|with\s+effect\s+from)?\s*(the\s+)?" + _D)
def act_dates(title, t, seal, today):
    """(adoption_date, basis, commencement_date). Adoption: 'made / adopted by the elected members … at its meeting held on <date>'; else a
    resolution date; else the date in the sealing clause ('this 12th day of March 2019' = the date the bye-laws were sealed after they were
    made). The commencement date ('shall come into operation on …') is kept separately and never used as the adoption date."""
    ok = lambda d: d and "1850-01-01" <= d <= today
    com = None
    m = COMMENCE.search(t) or IMPL_FIELD.search(t)
    if m and ok(parse_date(m.group("d"))): com = parse_date(m.group("d"))
    for rx, basis in ((MEET, "meeting_adoption_date"), (MEET2, "meeting_adoption_date"), (APPROVED, "meeting_adoption_date"), (RESOL, "resolution_date"),
                      (MAKING, "making_phrase_date"), (ADOPT_FIELD, "meeting_adoption_date")):
        for m in rx.finditer(t + "\n" + (seal or "")):
            ctx = t[max(0, m.start() - 60):m.start()] if m.start() < len(t) else ""
            if re.search(r"(?i)((revok|repeal|replac)\w*|\bamend(s|ing|ment)\b)[^.]{0,40}$", ctx): continue          # a date of another, revoked act
            # '… Bye-Laws 1999 made by the Council on the 8th day of November, 1999 are hereby revoked': the date of the revoked act
            if m.end() <= len(t) and (re.match(r"(?is)[^.;]{0,200}?\b(revoked|repealed|rescinded|cease\s+to\s+have\s+effect)\b", t[m.end():m.end() + 220])
                                      or re.search(r"(?i)\b(revocation|repeal)s?\b[^\n]{0,10}\n(?:.*\n){0,3}[^\n]*$", t[max(0, m.start() - 250):m.start()])): continue
            d = parse_date(m.group("d"))
            ty = re.search(r"\b(19[5-9]\d|20[0-4]\d)\b(?!.*\b(19[5-9]\d|20[0-4]\d)\b)", title or "")
            if ok(d) and ty and int(d[:4]) < int(ty.group(1)) - 1: continue                        # older than the bye-laws' own year
            if ok(d): return d, basis, com
    if seal:
        m = SEAL_DATE.search(seal)
        if m and ok(parse_date(m.group("d"))): return parse_date(m.group("d")), "common_seal_date", com
    for m in SEAL_IN_TEXT.finditer(t):
        if ok(parse_date(m.group("d"))): return parse_date(m.group("d")), "common_seal_date", com
    for m in DATED.finditer(t):
        if ok(parse_date(m.group("d"))): return parse_date(m.group("d")), "dated_clause", com
    return None, None, com

# 'with amendments made by resolution of the members … at the Council Meeting on the 3rd of February 2020, which amendments take effect from
# the 1st of June 2020' (Meath Foreshore Bye-Laws 2010 (As Amended)): the making of the amendment, kept apart from the original adoption
AMENDED = re.compile(r"(?i)\bamendments?\s+(?:were\s+)?(?:made|adopted|approved)\s+by\s+resolution\b[^.;]{0,160}?\bon\s+(?:the\s+)?" + _D)
AMEND_EFFECT = re.compile(r"(?i)\bamendments?\s+(?:shall\s+)?(?:take|took)\s+effect\s+(?:from|on)\s+(?:the\s+)?" + _D)
def amended_dates(t, today):
    ok = lambda d: d and "1850-01-01" <= d <= today
    m = AMENDED.search(t); e = AMEND_EFFECT.search(t)
    a = parse_date(m.group("d")) if m else None; c = parse_date(e.group("d")) if e else None
    return (a if ok(a) else None), (c if ok(c) else None)
# 'Adopted November 2021' in the council's link text: month precision only
LINK_MONTH = re.compile(r"(?i)\b(?:adopted|approved|made)\s+(?:in\s+)?(" + "|".join(k for k in MON if len(k) > 3) + r")\s+((?:19|20)\d\d)\b")
def link_month(link_text, today):
    m = LINK_MONTH.search(link_text or "")
    if not m: return None
    v = f"{m.group(2)}-{MON[m.group(1).lower()]:02d}"
    return v if "1850-01" <= v <= today[:7] else None

def issuing_organ(t):
    """'council' (the elected members of the county / city council; bye-laws are a reserved function, s. 199 Local Government Act 2001), or
    'municipal_district' when the members of a municipal district made them ('the Municipal District of X … hereby make')"""
    h = t[:6000]
    W = r"[A-ZÁÉÍÓÚ][\w'’\-]+"
    J = r"(?:[ \-]|\s*/\s*|\s+and\s+)"
    stop = r"(?i)\s+(?:casual|trading|bye[\s\-]*laws?|byelaws?|parking|appointed|car|control|in|hereby|has|have|within|is|are|hereinafter|for|at|on)\b"
    clean = lambda x: re.sub(r"\s+", " ", re.sub(r"(?i)\b((county|city)\s+council|council|members?|the|of)\b", " ", re.split(stop, x)[0])).strip(" -/")
    md = None
    m1 = re.search(r"(?i)municipal\s+district\s+of\s+(?P<md>" + W + "(?:" + J + W + "){0,3})", h)
    m2 = re.search(r"(?P<md>(?:" + W + r"(?:[ \-]|\s*/\s*)){1,3})(?i:municipal\s+district)\b", h)
    for m in (m1, m2):
        # 'West Clare Municipal District of Clare County Council': the words after 'of' are the council, not the district
        if m and clean(m.group("md")) and not re.match(r"(?i)\s*" + W + r"\s+(county|city)\s+council", m.group("md")):
            md = clean(m.group("md")); break
    # 'The Members of the Borough District of Drogheda in exercise of the powers …' (Louth's borough district)
    bd = re.search(r"(?i)members\s+of\s+the\s+borough\s+district\s+of\s+(" + W + ")", h)
    if not md and bd: return "municipal_district", "Borough District of " + (bd.group(1).title() if bd.group(1).isupper() else bd.group(1))
    m = m1 or m2
    if m and md:
        md = re.sub(r"\s*/\s*", "/", md)
        made_by_md = re.search(r"(?i)(members\s+of\s+(the\s+)?[^.]{0,80}municipal\s+district|municipal\s+district\s+(of\s+[^.]{0,60})?[^.]{0,120}?(hereby\s+make|in\s+exercise|have\s+made|adopted|made))", h)
        # the bye-laws' own title names the district ('Casual Trading Bye-Laws 2026 Municipal District of Tullow')
        made_by_md = made_by_md or re.search(r"(?i)bye[\s\-–]*laws?,?\s+(?:\(?\w+\)?\s+)?(?:19|20)\d\d\s+(?:for\s+the\s+)?municipal\s+district\s+of\s+", h[:1500])
        if md and made_by_md: return "municipal_district", (md.title() if md.isupper() else md)
    return "council", None

# ---------------------------------------------------------------- article splitter
HEAD = re.compile(r"(?i)^\s*(?P<m>bye[\s\-]*laws?|byelaws?|by[\s\-]laws?|article|section|regulation|clause|rule|fodhlí|alt)\s+(?:no\.?\s*)?(?P<n>\d{1,3}[a-z]?)\b(?![./]\d)\s*(?P<rest>[.:\-–—)]?.*)$")
NUMHEAD = re.compile(r"^\s*(?P<n>\d{1,3})\s*[.)]\s+(?P<rest>[A-Z“\"‘'(][^\n]{0,200})$|^\s*(?P<n2>\d{1,3})\s*\.\s*$")
REFWORD = re.compile(r"(?i)^\s*(of|to|and|or|in|under|the|shall|as|is|has|by|above|below|thereof|hereof|\(\d|\d{4}|act|acts)\b")
def _toc_line(l): return bool(re.search(r"\.{4,}|…{2,}|\s\d{1,3}\s*$", l)) and len(l) < 160
def candidates(lines):
    marked, numbered = [], []
    for i, l in enumerate(lines):
        if _toc_line(l): continue
        m = HEAD.match(l)
        if m and not REFWORD.match(m.group("rest").lstrip(".:-–—) ")) and len(l) <= 160:
            marked.append((i, int(re.match(r"\d+", m.group("n")).group(0)), m.group("n").lower(), m.group("m").lower()))
            continue
        m = NUMHEAD.match(l)
        if m and len(l) <= 220:
            n = m.group("n") or m.group("n2"); numbered.append((i, int(n), n, "num"))
    return marked, numbered
def chain(cs):
    """rising article numbers (gaps <= 3); a restart at 1 after >= 3 articles starts a new block (a schedule's own numbering)"""
    blocks, cur, last = [], [], 0
    for c in cs:
        i, v, lab, mk = c
        if cur and len(cur) >= 3 and v == 1: blocks.append(cur); cur, last = [], 0
        if (not cur and v in (1, 2)) or (cur and last < v <= last + 3): cur.append(c); last = v
    if cur: blocks.append(cur)
    return [b for b in blocks if len(b) >= 3]
DECHEAD = re.compile(r"^\s*(?P<a>\d{1,2})\.(?P<b>\d{1,2})\.?(?:\s+(?P<rest>[A-Z“\"‘'(][^\n]{0,200})|\s*)$")
def decimal_candidates(lines):
    """'1.1. Title' / '1.1.' section headings of a text numbered in parts and sections (Kildare / Meath waste bye-laws 2018)"""
    out = []
    for i, l in enumerate(lines):
        if _toc_line(l) or any(re.search(r"\.{4,}|…{2,}", x) for x in lines[i + 1:i + 4]): continue    # TOC: '1.1.' / '' / 'Title ......'
        m = DECHEAD.match(l)
        if m and len(l) <= 220: a, b = int(m.group("a")), int(m.group("b")); out.append((i, a * 100 + b, f"{a}.{b}", "decimal"))
    return out
def chain_decimal(cs):
    """rising section numbers: the next section of the same part (gap <= 3) or the first sections of the next part; a return to 1.1 after
    >= 3 sections starts a new block"""
    blocks, cur, last = [], [], None
    for c in cs:
        a, b = divmod(c[1], 100)
        if cur and len(cur) >= 3 and (a, b) == (1, 1): blocks.append(cur); cur, last = [], None
        ok = (last is None and a in (1, 2) and b in (0, 1, 2)) or (last and ((a == last[0] and last[1] < b <= last[1] + 3) or (a == last[0] + 1 and b in (0, 1, 2))))
        if ok: cur.append(c); last = (a, b)
    if cur: blocks.append(cur)
    return [b for b in blocks if len(b) >= 3]
TOC_HDR = re.compile(r"(?i)^\s*(table\s+of\s+contents|contents|arrangement\s+of\s+(the\s+)?(bye[\s\-]*laws?|sections|articles|clauses)|index|clár(\s+an\s+ábhair)?)\s*:?\s*$")
def _toc_like(b, lines):
    """headings with title-only bodies ('1.' / 'Definitions' / '2.' …), or a run that starts right after a 'Contents' / 'Arrangement of
    Bye-Laws' line"""
    bodies = sorted(len(" ".join(l.strip() for l in lines[x[0] + 1:y[0]])) for x, y in zip(b, b[1:]))
    if bodies and bodies[len(bodies) // 2] < 60: return True
    return any(TOC_HDR.match(lines[j]) for j in range(max(0, b[0][0] - 6), b[0][0]))
ENDNUM = re.compile(r"^\s*(?P<h>[A-Z][^.\n]{1,60}?):?\s+(?P<n>\d{1,3})\.\s*$")      # margin heading + number: 'Short Title: 1.'
AFTER_TOC = re.compile(r"(?i)hereby\s+make|may\s+be\s+cited|short\s+title|long\s+title|in\s+exercise\s+of\s+the\s+powers|déanann")
def chain_relaxed(cs):
    """chain() for a body that follows a contents list: the first number may be up to 5 (numbers lost in margin notes)"""
    blocks, cur, last = [], [], 0
    for c in cs:
        i, v, lab, mk = c
        if cur and len(cur) >= 3 and v == 1: blocks.append(cur); cur, last = [], 0
        if (not cur and 1 <= v <= 5) or (cur and last < v <= last + 3): cur.append(c); last = v
    if cur: blocks.append(cur)
    return [b for b in blocks if len(b) >= 3]
def contents_run(b, lines):
    """a numbered run that is a contents list: >= 5 entries with title-only bodies (or a 'Contents' line above), and the making clause /
    citation / long title only after it (Carlow horses, Bandon car parks, Douglas / Wexford / Kilkenny parking: the body follows, with
    numbers the chain cannot see)"""
    if len(b) < 5 or not _toc_like(b, lines): return False
    before = "\n".join(lines[:b[0][0]]); after = "\n".join(lines[b[-1][0] + 1:])
    if not AFTER_TOC.search(after) or len(after) <= 3 * len("\n".join(lines[b[0][0]:b[-1][0] + 1])): return False
    if not re.search(r"(?i)hereby\s+make|déanann", before): return True
    # a cover page with its own making clause (Carlow horses 2021): the entry titles must come back as body headings
    heads = {re.sub(r"\W+", " ", l).strip().casefold() for l in lines[b[-1][0] + 1:]}
    tit = [re.sub(r"\W+", " ", re.sub(r"^\s*\d{1,3}\s*[.)]?", "", lines[c[0]])).strip().casefold() for c in b]
    tit = [x for x in tit if len(x.split()) >= 1 and len(x) >= 4]
    return len(tit) >= 5 and sum(x in heads for x in tit) >= 0.5 * len(tit)
def body_after_contents(lines, start, kind):
    marked, numbered = candidates(lines)
    cs = [c for c in (marked if kind == "marked" else numbered) if c[0] >= start]
    for i in range(start, len(lines)):
        m = re.match(r"^\s*(\d{1,2})\.\s*(?:\(1\)|[A-Z“(])", lines[i])           # '5.Cork County Council …', '4. (1) In these'
        if m and not _toc_line(lines[i]) and (len(lines[i]) <= 220 or "(1)" in lines[i][:12]) and not any(c[0] == i for c in cs): cs.append((i, int(m.group(1)), m.group(1), "num")); continue
        m = ENDNUM.match(lines[i])
        if m and not any(c[0] == i for c in cs): cs.append((i, int(m.group("n")), m.group("n"), "endnum"))
    # a bare '1.' that only wraps the end of a sentence ('… the maps in Schedule' / '1.') is no heading
    prev = lambda i: next((lines[j].rstrip() for j in range(i - 1, -1, -1) if lines[j].strip()), "")
    cs = [c for c in cs if not (re.fullmatch(r"\s*\d{1,3}\.?\s*", lines[c[0]]) and re.search(r"(?i)\b(schedules?|part|appendix|annex|sections?|articles?|bye-?laws?|no|paragraph)$", prev(c[0])))]
    cs.sort()
    return chain_relaxed(cs)
def toc_block(b, lines, later):
    """a block whose headings sit on (almost) adjacent lines or have title-only bodies, repeated by a later block, is a table of contents"""
    if not later: return False
    d = sorted(y[0] - x[0] for x, y in zip(b, b[1:]))
    bodies = sorted(len(" ".join(l.strip() for l in lines[x[0] + 1:y[0]])) for x, y in zip(b, b[1:]))
    rep = len({c[2] for c in b} & {c[2] for c in later}) >= 0.5 * len(b)
    return rep and ((d and d[len(d) // 2] <= 2) or _toc_like(b, lines))
SCHED = re.compile(r"^\s*((FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH)\s+SCHEDULE|SCHEDULE\s*([\dIVX]{1,4}|[A-Z])?\b|APPENDIX\s*([\dIVX]{1,4}|[A-Z])?\b|ANNEX\s*([\dIVX]{1,4}|[A-Z])?\b|"
                   r"(?:AGUISÍN|Aguisín|SCEIDEAL|Sceideal)\s*([\dIVX]{1,4}|[A-Z])?\b|(First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth)\s+Schedule\b|Schedule\s+([\dIVX]{1,4}|[A-Z])\b|Appendix\s+([\dIVX]{1,4}|[A-Z])\b|EXPLANATORY\s+NOTE|Explanatory\s+Note)(?!.*\.{4,})(?!.*(?<![Pp]art)(?<!PART)\s\d{1,3}\s*$)[^\n]{0,120}$")
PARTHEAD = re.compile(r"^\s*(?:(?:PART|Part|CUID|Cuid)\s+(?P<n>[IVX]{1,6}|\d{1,2})|(?:PART|Part)(?P<n2>[IVX]{1,6}))\b\s*[.:\-–]?\s*(?P<rest>.{0,120})$")
def _pnum(n):
    n = n or ""
    if n.isdigit(): return int(n)
    v = {"I": 1, "V": 5, "X": 10}; t = 0
    for a, b in zip(n, n[1:] + " "): t += -v[a] if b != " " and v[a] < v[b] else v[a]
    return t
def part_heads(lines):
    """Body PART headings in rising order: [(line, number, label)]. Contents runs (another PART line within 3 lines; dot leaders / trailing
    page numbers) are left out; a PART line inside running text ('… under Part 2 of the Act') is not a heading (rest must not start lower-case)."""
    c = [(i, _pnum(m.group("n") or m.group("n2"))) for i, l in enumerate(lines) for m in [PARTHEAD.match(l)]
         if m and not re.match(r"[a-z(]", m.group("rest") or "") and not re.search(r"\.{4,}|\d\s*$", m.group("rest") or "")]
    # the same part named twice in a row ('PARTIV' / 'Definitions for Part IV' in the margin) is one heading; different parts within 3 lines
    # of each other are a contents list
    c = [(i, n) for k, (i, n) in enumerate(c) if not (k and c[k - 1][1] == n and i - c[k - 1][0] <= 3)]
    c = [(i, n) for k, (i, n) in enumerate(c) if not any(abs(i - j) <= 3 and m != n for j, m in c[:k] + c[k + 1:])]
    # an 'Arrangement of Bye-Laws' run: >= 2 PART lines with < 1,200 characters between neighbours, at least half of whose numbers
    # come again later (Kilkenny parking 2012: Part I–VII listed with their bye-law titles, then the body's PART II …)
    runs, cur = [], []
    for i, n in c:
        if cur and len("\n".join(lines[cur[-1][0]:i])) >= 1200: runs.append(cur); cur = []
        cur.append((i, n))
    if cur: runs.append(cur)
    drop = set()
    for r in runs:
        later = {n for i, n in c if i > r[-1][0]}
        if len(r) >= 2 and sum(n in later for _, n in r) * 2 >= len(r): drop |= {i for i, _ in r}
    c = [(i, n) for i, n in c if i not in drop]
    out = []
    for i, n in c:
        if (not out and n <= 2) or (out and out[-1][1] < n <= out[-1][1] + 2): out.append((i, n))     # one part may be lost to the scan
    return [(i, n, f"part-{n}") for i, n in out] if len(out) >= 2 else []
def exact_cuts(t, recs):
    """re-cut each record from the law text: every record is then an exact substring of it (merges above joined with '\n'), in order"""
    sq = lambda x: re.sub(r"\s+", "", x)
    pos, st = 0, []
    for r in recs:
        head = r[2].split("\n")[0][:80]; want = sq(r[2])[:300]; k = pos - 1
        while True:                                       # the line itself, not an earlier copy of its first line (contents list)
            k = t.find(head, k + 1)
            if k < 0: return recs                         # cannot happen for records cut from t; keep them as they are
            if sq(t[k:k + 3 * len(r[2][:300]) + 400])[:len(want)] == want: break
        st.append(k); pos = k + len(head)
    out = []
    for j, r in enumerate(recs):
        e = st[j + 1] if j + 1 < len(st) else len(t)
        out.append((r[0], r[1], t[st[j]:e].strip()))
    return out
def split_articles(t):
    """[(label, heading, body)], info. '0' = preamble (title, recitals, making clause). Headings: 'Bye-Law 3', 'Article 3', 'Section 3', or a
    numbered paragraph '3. Interpretation' / '3. These Bye-Laws …' (only when no marked headings form a sequence). Schedules / appendices /
    explanatory notes after the last article are records of their own ('schedule-1', 'appendix-a', 'explanatory-note')."""
    lines = t.split("\n"); marked, numbered = candidates(lines)
    bl = chain(marked); kind = "marked"
    if not bl or sum(len(b) for b in bl) < 3: bl = chain(numbered); kind = "numbered"
    if not bl or sum(len(b) for b in bl) < 3: bl = chain_decimal(decimal_candidates(lines)); kind = "decimal"     # '1.1. Title' sections
    toc_info = None; tail_list = None
    # a numbered run in the last 40 % under a schedule / appendix heading or a signature line, with > 5k characters of text before it, is a
    # schedule (Kilkenny horses 2020's street list, DCC litter's inspection form notes), not the bye-laws: the bye-laws are split by their
    # decimal sections or PART headings and the run stays inside its schedule record
    if bl and kind == "numbered" and bl[0][0][0] > 0.6 * len(lines) and len("\n".join(lines[:bl[0][0][0]])) > 5000:
        s0 = bl[0][0][0]
        if any(SCHED.match(lines[j]) or re.match(r"(?i)^\s*(signed|sínithe)\s*:", lines[j]) for j in range(max(0, s0 - 30), s0)):
            tail_list = s0
            dec = chain_decimal([c for c in decimal_candidates(lines) if c[0] < s0])
            bl = dec if dec and sum(len(b) for b in dec) >= 5 else []; kind = "decimal" if bl else "numbered"
            if not bl:     # 'CITATION 1. These Bye-Laws …', '4(a) The entire area …': margin words and lettered first paragraphs
                cs = []
                for i in range(s0):
                    m = re.match(r"^\s*(?:[A-Z][A-Z ]{2,40}\s+)?(\d{1,2})(?:\.\s+[A-Z“(]|\(a\)\s)", lines[i])
                    if m and not _toc_line(lines[i]) and not any(lines[i][m.end(1):].lstrip(". ")[:40].count(x) > 1 for x in "0123456789"):
                        cs.append((i, int(m.group(1)), m.group(1), "num"))
                bl = chain_relaxed(cs)
    if bl and kind in ("marked", "numbered") and contents_run(bl[0], lines):
        # the contents list stays in the preamble; the bye-laws are the numbered run after it (plain labels)
        st = bl[0][-1][0] + 1; body = body_after_contents(lines, st, kind)
        # bye-laws whose numbers were margin notes ('Short Title' / … / 'Commencement:' before '4. (1) In these Bye-Laws', Douglas
        # parking 2020): the contents titles of the missing first numbers, found as heading lines before the first numbered bye-law
        if body and body[0][0][1] > 1:
            k0 = body[0][0][1]; b0 = body[0][0][0]
            nm = lambda x: re.sub(r"\W+", " ", x).strip().casefold()
            tit = {c[1]: nm(re.sub(r"^\s*\d{1,3}\s*[.)]?", "", lines[c[0]])) for c in bl[0]}
            mk_ = max((i for i in range(st, b0) if re.search(r"(?i)hereby\s+makes?\b", lines[i])), default=None)
            if mk_ is not None:
                nxt_ = lambda i: next((l for l in lines[i + 1:b0 + 1] if l.strip()), "").strip()
                # margin headings: a short title line followed by a sentence ('Short Title' / 'These Bye-Laws may be cited as …')
                hs = [i for i in range(mk_ + 1, b0) if re.fullmatch(r"\s*[A-Z][A-Za-z ]{2,38}:?\s*", lines[i]) and nxt_(i)[:1].isupper() and len(nxt_(i)) > 40]
                if hs and nm(lines[hs[-1]]) == tit.get(k0): hs = hs[:-1]          # 'Interpretation' / '4. (1) In these Bye-Laws'
                good = sum(nm(lines[i]) == tit.get(n) or nm(lines[i]) in (tit.get(n) or "") or (tit.get(n) or "~") in nm(lines[i])
                           for n, i in enumerate(hs, 1))
                if len(hs) == k0 - 1 and good * 2 >= len(hs): body[0] = [(i, n, str(n), "title") for n, i in enumerate(hs, 1)] + body[0]
        toc_info = dict(contents_lines=[bl[0][0][0], bl[0][-1][0]], entries=len(bl[0]))
        bl = body + [b for b in bl[1:] if b[0][0] > (body[-1][-1][0] if body else st)] if body else [b for b in bl[1:]]
    bl = [b for k, b in enumerate(bl) if not toc_block(b, lines, [c for bb in bl[k + 1:] for c in bb])]
    ph = part_heads(lines)
    if not bl and ph:                                    # parts only ('PART I … PART V', no numbered bye-laws the splitter can chain)
        bl = [[(i, n, lab, "part") for i, n, lab in ph]]; kind = "part"
    starts = []
    for k, b in enumerate(bl):
        for (i, v, lab, mk) in b: starts.append((i, lab if k == 0 else f"b{k + 1}.{lab}"))
    if starts and kind != "part":
        # a hidden PART heading: one with > 300 characters of its own before the next article (Kilkenny parking b2.5 runs on through
        # Parts II–IV; Waterford casual trading art. 7 holds Part III) starts a record of its own
        st = sorted(x[0] for x in starts)
        for i, n, lab in ph:
            nxt = next((x for x in st if x > i), len(lines))
            if i > st[0] and len("\n".join(lines[i:nxt])) > 300 and i not in st: starts.append((i, lab))
        # a numbered schedule heading between the items of a schedule list ('6.6 Sixth Schedule (80 km/h) – New Ross District' after item 14
        # of the fifth schedule, Wexford speed limits 2018) closes the item before it
        for i, l in enumerate(lines):
            m = re.match(r"^\s*(\d{1,2}\.\d{1,2})\s+(?:(?:First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth|Eleventh|Twelfth)\s+)?Schedule\b", l)
            if m and i > st[0] and i not in st and not re.search(r"\.{4,}|\s\d{1,3}\s*$", l): starts.append((i, "schedule-" + m.group(1)))
    if not starts:
        # no articles and no parts: the main text and its schedules (DCC taxi stands 2015, whose bye-law numbers were margin notes)
        sch = [(i, l) for i, l in enumerate(lines) if SCHED.match(l) and len("\n".join(lines[:i])) > 1500]
        if not sch: return [("0", "", t)], dict(kind=None, blocks=0)
        starts = [(0, "body")]; kind = "schedules"; bl = [[(0, 0, "body", "text")]]
    last = max(s[0] for s in starts if not s[1].startswith("part-")) if kind != "part" else max(s[0] for s in starts)
    seen_s = collections.Counter()
    for i, l in enumerate(lines):
        if i > last and SCHED.match(l):
            m = SCHED.match(l); tag = re.sub(r"[^a-z0-9]+", "-", m.group(1).lower()).strip("-")
            seen_s[tag] += 1
            if seen_s[tag] == 1: starts.append((i, tag))      # a repeated 'Schedule 1' line is a page header or a reference, not a new record
    starts.sort()
    # a record over 50k characters that holds schedule headings of its own (Meath speed limits 2018: the last item of the third schedule ran
    # on through the Fourth to Seventh Schedules) is cut at each schedule's first heading line ('Fifth Schedule (60km/h) – Part 1')
    have = {lab for _, lab in starts}; sizes = [0] * len(lines)
    for i, l in enumerate(lines): sizes[i] = len(l) + 1
    for j, (i0, lab0) in enumerate(list(starts)):
        e0 = starts[j + 1][0] if j + 1 < len(starts) else len(lines)
        # (and an item of a later numbered list, 'b3.1 Navan', that runs on into the next schedules)
        big = sum(sizes[i0:e0]) > 50000
        small = re.match(r"b\d+\.\d+$", lab0) or re.match(r"(schedule|appendix|annex|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)", lab0)
        for i in range(i0 + 1, e0):
            m = SCHED.match(re.sub(r"^\s*[IVX]{1,5}\.\s+", "", lines[i]))        # 'VII. Sixth Schedule (80km/h)'
            if not m or re.search(r"(?i)explanatory", m.group(1)): continue
            ordinal = re.match(r"(?i)(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+schedule", m.group(1))
            pq_ = next((lines[q] for q in range(i - 1, max(i0, i - 3), -1) if lines[q].strip()), "")
            roman = re.match(r"^\s*[IVX]{1,5}\.\s", lines[i]) or re.fullmatch(r"\s*[IVX]{1,5}\.?\s*", pq_)
            # in a small record only an ordinal schedule heading counts ('VIII. Seventh Schedule' inside a drawing-list item), in any other
            # record only a numbered one ('IV.' / 'Third Schedule (40km/h)' after the last bye-law)
            if not big and not ((small and ordinal) or (ordinal and roman)): continue
            pm = re.search(r"(?i)\bpart\s+(\d{1,2}|[IVX]{1,4})\b", lines[i])
            tag = re.sub(r"[^a-z0-9]+", "-", m.group(1).lower()).strip("-") + (f"-part-{pm.group(1).lower()}" if pm else "")
            if tag in have:
                # the schedule's own text after its drawing list ('VII. Sixth Schedule (80km/h)' / '1. …' / … / 'VII. Sixth Schedule' /
                # 'Roads in respect of which …'): a continuation, folded into that schedule's record below
                if lab0 != tag and (small or roman):
                    q = next((q for q in range(i - 1, max(i0, i - 3), -1) if lines[q].strip()), None)   # 'IV.' / '' / 'Third Schedule'
                    starts.append((q if q is not None and re.fullmatch(r"\s*[IVX]{1,5}\.?\s*", lines[q]) else i, f"__cont{i}"))
                continue
            have.add(tag); h = i
            q = next((q for q in range(i - 1, max(i0, i - 3), -1) if lines[q].strip()), None)        # 'VI.' / '' / 'Fifth Schedule …'
            if q is not None and re.fullmatch(r"\s*[IVX]{1,5}\.?\s*", lines[q]): h = q
            starts.append((h, tag))
        # no schedule heading the pattern knows, but the seal and then 'Schedule, Disabled Bays' tables (Wexford parking 2023 bye-law 61)
        if sum(sizes[i0:e0]) > 50000 and not any(i0 < x < e0 for x, _ in starts):
            seal = next((i for i in range(i0, e0) if re.search(r"(?i)common\s+seal|seal\s+of\s+[^.]{0,60}was\s+affixed", lines[i])), None)
            sc = next((i for i in range(seal + 1, e0) if re.match(r"(?i)^\s*schedules?\b[\s,:\-–]", lines[i] + " ") and len(lines[i]) <= 80), None) if seal is not None else None
            if sc is not None and "schedule" not in have: have.add("schedule"); starts.append((sc, "schedule"))
    starts.sort()
    recs = []; pre = "\n".join(lines[:starts[0][0]]).strip()
    if pre: recs.append(("0", "", pre))
    seen = collections.Counter()
    for j, (i, lab) in enumerate(starts):
        e = starts[j + 1][0] if j + 1 < len(starts) else len(lines)
        seen[lab] += 1
        if seen[lab] > 1: lab = f"{lab}#{seen[lab]}"
        recs.append((lab, lines[i].strip()[:200], "\n".join(lines[i:e]).strip()))
    # bare stubs ('1.', '17.', 'Miscellaneous:') left by a two-column layout go onto the front of the next record (the last onto the one before)
    stub = lambda b: len(b) <= 60 and all(re.fullmatch(r"[\d.():;\-–]+|[A-Z][A-Za-z ]{0,30}:?", x.strip()) for x in b.split("\n") if x.strip()) \
        and sum(bool(re.search("[A-Za-z]", x)) for x in b.split("\n")) <= 1
    j = 0; isstub = [r[0] != "0" and re.fullmatch(r"(b\d+\.)?\d+", r[0]) is not None and stub(r[2]) for r in recs]
    while j < len(recs):
        if isstub[j] and len(recs) > 2:
            if j + 1 < len(recs): recs[j + 1] = (recs[j + 1][0], recs[j + 1][1], recs[j][2] + "\n" + recs[j + 1][2]); del recs[j]; del isstub[j]; continue
            recs[j - 1] = (recs[j - 1][0], recs[j - 1][1], recs[j - 1][2] + "\n" + recs[j][2]); del recs[j]; del isstub[j]; continue
        j += 1
    # drawing / map lists of a schedule ('1. Ashbourne & Greenoge (CWA02Rev.A)' as items of a later numbered list): single-line items of
    # < 120 characters go into the schedule record before them (or, before any schedule, into the schedule record after them), and the
    # continuation of a schedule's text after its list goes into that schedule's record
    schedlike = lambda lab: re.match(r"(schedule|appendix|annex|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)", lab) is not None
    short_item = lambda r: re.match(r"b\d+\.\d+$", r[0]) and len(r[2]) < 120 and r[2].strip().count("\n") <= 1
    j = 1
    while j < len(recs):
        if recs[j][0].startswith("__cont") or (short_item(recs[j]) and schedlike(recs[j - 1][0])):
            recs[j - 1] = (recs[j - 1][0], recs[j - 1][1], recs[j - 1][2] + "\n" + recs[j][2]); del recs[j]; continue
        j += 1
    # a schedule heading record (< 120 characters) straight before the first item of a list ('SECOND SCHEDULE – 30km/h' / 'PART A' /
    # '2. The following roads at …') takes that item in: the heading names the list, it is no record of its own
    j = 0
    while j < len(recs) - 1:
        if schedlike(recs[j][0]) and len(recs[j][2]) < 120 and re.match(r"b\d+\.\d+$", recs[j + 1][0]):
            recs[j] = (recs[j][0], recs[j][1], recs[j][2] + "\n" + recs[j + 1][2]); del recs[j + 1]
        j += 1
    j = len(recs) - 2
    while j >= 1:
        if short_item(recs[j]) and schedlike(recs[j + 1][0]) and not schedlike(recs[j - 1][0]):
            recs[j + 1] = (recs[j + 1][0], recs[j][1], recs[j][2] + "\n" + recs[j + 1][2]); del recs[j]
            recs[j] = (recs[j][0], recs[j][2].split("\n")[0][:200], recs[j][2])
        j -= 1
    # a PART record that is only its heading ('PART III' straight before 'SCHEDULE A') goes onto the front of the next record
    for j in range(len(recs) - 2, -1, -1):
        if recs[j][0].startswith("part-") and len(recs[j][2]) < 60:
            recs[j + 1] = (recs[j + 1][0], recs[j + 1][1], recs[j][2] + "\n" + recs[j + 1][2]); del recs[j]
    recs = exact_cuts(t, recs)
    if kind in ("part", "schedules"):
        return recs, dict(kind=kind, blocks=1, gaps=[], marker=kind)
    nums = [v for (i, v, lab, mk) in bl[0]]
    if toc_info: kind = kind + "_after_contents"
    gaps = [(a, b) for a, b in zip(nums, nums[1:]) if b - a > 1 and not (kind == "decimal" and b // 100 == a // 100 + 1 and b % 100 <= 2)]
    if kind == "decimal": gaps = [(f"{a // 100}.{a % 100}", f"{b // 100}.{b % 100}") for a, b in gaps]
    return recs, dict(kind=kind, blocks=len(bl), gaps=gaps, marker=collections.Counter(c[3] for c in bl[0]).most_common(1)[0][0])
def loose_heading_run(body, kind):
    """longest run of >= 3 rising headings of the splitter's kind inside one record (TOC lines and adjacent-line runs excluded)"""
    lines = body.split("\n"); marked, numbered = candidates(lines)
    cs = marked if kind in (None, "marked") else numbered
    best = 0
    for b in (chain_decimal(decimal_candidates(lines)) if kind == "decimal" else chain(cs)):
        d = sorted(y[0] - x[0] for x, y in zip(b, b[1:]))
        if (d and d[len(d) // 2] <= 2) or _toc_like(b, lines): continue
        best = max(best, len(b))
    return best
