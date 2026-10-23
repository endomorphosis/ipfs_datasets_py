#!/usr/bin/env python3
"""Greek-specific rules: subject classifier (real regulations vs. decisions that merely mention one),
accent folding, ADA transliteration, article splitter, date extraction."""
import re, unicodedata, collections

def fold(s):
    s = unicodedata.normalize("NFKC", s or "")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.lower().replace("ς", "σ")).strip()

# One Latin letter per Greek capital, so the ASCII id is reversible (ADA alphabet = Greek capitals + digits).
TR = dict(zip("ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ", "abgdezhuiklmnjoprstyfxcw"))
def ada_ascii(ada):
    out = "".join(TR.get(ch, ch.lower()) for ch in unicodedata.normalize("NFC", ada.upper()))
    assert re.fullmatch(r"[a-z0-9-]+", out), (ada, out)
    return out

TERM = r"(κανονισμ|κανονιστικ|οργανισμ\w* εσωτερικησ υπηρεσιασ|ο\.?ε\.?υ\b)"
ADOPT = r"(εγκρισ|ψηφισ|καταρτισ|θεσπισ|τροποποιησ|τροποποιητικ|αναθεωρησ|συμπληρωσ|κωδικοποιησ|επικαιροποιησ|λη[ψψ]η αποφασησ|εκδοσ|εγκρινει|ψηφιζει|εγκρινεται|εγκεκριμεν|εναρμονισ|εφαρμογη τησ αποφασησ.{0,10}κανονιστ|εσωτερικοσ κανονισμοσ|κανονισμοσ (λειτουργιασ|καθαριοτητασ|κοιμητηρι|υδρευσ|αποχετευσ|αρδευσ|λαικ|στασιμευσ|κοινοχρηστ|χρησησ|διαχειρισησ|προσκομισησ|οικονομικησ|εσωτερικησ|τομων|ηλεκτρ|δημοτικ|πρασινου|αδεσποτ|υπαιθρι|παραχωρησ|ομβριων|αστικ))"
EXCL = [
    ("draft_or_consultation", r"(σχεδιο|διαβουλευσ|εισηγησ|εισηγειται|να εισηγηθει|γνωμοδοτ|διατυπωση αποψεων|αποψεισ|προτασ|καταθεση|συζητηση|ενημερωση|αναβολ|anabolh|επανασυζητ)"),
    ("not_adopted_or_opinion", r"(\bμη εγκρισ|συμφωνη γνωμη|παραπομπη στο δημοτικο|παραβιασ|βεβαιωθηκε|\bακυρωση τησ εγγραφησ|παραβασ\w* κανονισμ)"),
    ("community_council", r"(δημοτικησ κοινοτητασ|συμβουλιου κοινοτητασ|συνεδριαση .{0,30}κοινοτητασ|επιτροπη διαβουλευσησ)"),
    ("works_pricing_protocol", r"(πρωτοκολλ\w* κανονισμου τιμων|π\.?κ\.?τ\.?μ\.?ν\.?ε|ανακεφαλαιωτικ|κανονισμου τιμων μοναδ)"),
    ("enforcement_or_individual", r"(βεβαιωσησ παραβασ|\bδιαγραφ|παραχωρησησ? του δικαιωματοσ|\bταφου|\bπροστιμ|\bεπιβολη|κατ εξαιρεση|παρατασησ? ωραριου|\bαδεια|\bχορηγηση)"),
    ("applies_regulation", r"(συμφωνα με (τον|το|την|τουσ)\b.{0,60}κανονισμ|βασει (του|τησ|των)\b.{0,60}κανονισμ|κατ εφαρμογη|του αρθρου \d+\w* (του|τησ) .{0,40}κανονισμ|προβλεπεται απο)"),
    ("eu_regulation", r"(κανονισμ\w* \((εε|εκ|ευρατομ)\)|\(εε\) αριθ|\(εκ\) αριθ|2016/679|1407/2013|651/2014|1303/2013|2021/1060|γκπδ|gdpr|de minimis|ευρωπαικ)"),
    ("contract_memo_procurement", r"(μνημονι|συμβασ|αναθεσ|προμηθει|διαγωνισμ|μισθωσ|δημοπρασ|προκηρυξ|προσκλησ|τευχ|μελετησ?\b|εργου|υπηρεσιασ με τιτλο|πληρωμ|δαπαν|αποζημιωσ|προϋπολογισμ|προυπολογισμ|απολογισμ|ισολογισμ)"),
    ("staff_or_organ", r"(προσληψ|μετακινησ|μεταταξ|αποσπασ|ορισμ\w* .{0,40}(επιτροπ|μελ|εκπροσωπ|υπαλληλ)|συγκροτησ|ανακαθορισμ\w* μελ|αντιμισθ|εξουσιοδοτ|μεταβιβασ\w* αρμοδιοτητ|ορισμοσ|ορκωμοσ|υπερωρι|εφημερι|καθορισμοσ ωραριου εργασιασ)"),
]

def classify_subject(subject, dtype=None):
    s = fold(subject)
    if not re.search(TERM, s): return False, "no_regulation_term"
    for name, rx in EXCL:
        if re.search(rx, s): return False, "excluded_" + name
    # street-level 'κανονιστικές' decisions (signs, one parking space, a bus stop, a telecom cabin, a citizen's request): regulatory in form but
    # individual in scope; kept only when the subject names a Κανονισμός (e.g. 'Κανονισμός ελεγχόμενης στάθμευσης')
    if "κανονισμ" not in s and re.search(r"(κυκλοφοριακ|πινακιδ|θεσ\w* σταθμευσ|σταθμευσησ? (για|οχηματ)|καμπιν|σηματοδοτ|αιτημα|εισοδου ?- ?εξοδου|λεωφορειακ|στασησ? (και|&)|απαγορευση στασ|μονοδρομ|ποδηλατοδρομ|ραμπ|εμποδι|κολωνακ|διαγραμμισ|οδοστρωμ|αμεα|α\.μ\.ε\.α|ατομο με αναπηρ)", s):
        return False, "excluded_street_level_traffic_or_individual"
    if re.search(r"\bαιτημα\b", s): return False, "excluded_street_level_traffic_or_individual"
    if dtype not in (None, "Α.2", "2.4.7.1"): return False, "excluded_decision_type_" + dtype
    if dtype == "2.4.7.1":   # 'other individual administrative acts': only explicit adoption of a regulation
        if re.match(r"(λη[ψ]η αποφασησ (για|σχετικα με) (την|τον|το) )?(εγκρισ\w*|ψηφισ\w*|καταρτισ\w*|τροποποιησ\w*)\s+(του\s+|τησ\s+)?(νεου\s+|νεασ\s+)?(εσωτερικου\s+)?(κανονισμου|κανονιστικησ αποφασησ|οργανισμου εσωτερικησ)", s):
            return True, "keep_2.4.7.1_explicit_adoption"
        return False, "excluded_2.4.7.1_not_explicit_adoption"
    if re.search(ADOPT, s) or s.startswith(("κανονισμ", "κανονιστικ")): return True, "keep_" + (dtype or "?")
    return False, "no_adoption_verb"

# ---------------------------------------------------------------- text clean-up / checks
LOOK = str.maketrans("ABEZHIKMNOPTYXo", "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧο")
MIXED = re.compile(r"(?<![\w])(?=[\w]*[α-ωά-ώΑ-ΩΆ-Ώϊϋΐΰ])(?=[\w]*[A-Za-z])[A-Za-zα-ωά-ώΑ-ΩΆ-Ώϊϋΐΰ]{2,}(?![\w])")
def lookalike_tokens(t):
    """Greek words containing Latin look-alike letters ('Kλάδος' with Latin K) - every Latin letter of the word has a Greek twin."""
    return [w for w in MIXED.findall(t) if all(ch in "ABEZHIKMNOPTYXo" for ch in w if "A" <= ch <= "z")]
def fix_latin_lookalikes(t):
    return MIXED.sub(lambda m: m.group(0).translate(LOOK) if m.group(0) in set(lookalike_tokens(m.group(0))) else m.group(0), t)

# ---- character repairs (verify round 1)
# C1 controls: Windows-1252 bytes that leaked through ('\x97' = em dash); applied before NFKC
C1 = {0x80: "€", 0x82: "‚", 0x84: "„", 0x85: "…", 0x86: "†", 0x87: "‡", 0x89: "‰", 0x8b: "‹", 0x91: "‘", 0x92: "’", 0x93: "“", 0x94: "”",
      0x95: "•", 0x96: "–", 0x97: "—", 0x9b: "›"}
def map_c1(t):
    return re.sub(r"[\x80-\x9f]", lambda m: C1.get(ord(m.group(0)), ""), t)
def map_pua(t):
    """Symbol/Wingdings private-use code points (U+F0xx): ASCII punctuation/digits keep their character (U+F02D '-', U+F020 ' '),
    the bullets / check marks / arrows (U+F0B7, F0A7, F0FC, F0D8, F06C ...) become '•'; any other private-use character is dropped."""
    def f(m):
        c = ord(m.group(0))
        if 0xF020 <= c <= 0xF03F: return chr(c - 0xF000)
        if c == 0xF0A0: return " "
        if 0xF000 <= c <= 0xF0FF: return "•"
        return ""
    return re.sub(r"[\ue000-\uf8ff]", f, t)
# look-alike letters inside a word of another script: mapped to the word's majority script
L2G = dict(zip("ABEHIKMNOPTXYZaeiknoptuvxyw", "ΑΒΕΗΙΚΜΝΟΡΤΧΥΖαειкνορτυνχυω".replace("к", "κ")))
C2G = dict(zip("АВЕНІКМОРТХПГЛФДаеорхпуі", "ΑΒΕΗΙΚΜΟΡΤΧΠΓΛΦΔαεορχπυι"))
G2L = dict(zip("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧοαικνρυχ", "ABEZHIKMNOPTYXoaikvpux"))
L2C = dict(zip("ABCEHKMOPTXYacekopxy", "АВСЕНКМОРТХУасекорху"))
TOKEN = re.compile(r"[^\W\d_]+")
def _script(ch):
    if "\u0370" <= ch <= "\u03ff" or "\u1f00" <= ch <= "\u1fff": return "g"
    if "\u0400" <= ch <= "\u04ff": return "c"
    if ch.isascii() or "\u00c0" <= ch <= "\u024f": return "l"
    return "o"
ROMAN = set("IVXLΙΧ")
UNITS = re.compile(r"^μ[gmlLs]$")                     # micro sign units (NFKC maps µ -> Greek μ): μg, μm, μl
L2G_LOW = {"s": "σ", "z": "ζ", "l": "ι", "ï": "ϊ", "ü": "ϋ"}
def _to(w, maj):
    up = sum(1 for c in w if c.isupper()) > len(w) / 2
    if maj == "g":
        out = []
        for i, c in enumerate(w):
            if _script(c) == "g": out.append(c); continue
            r = L2G.get(c) or C2G.get(c)
            if r is None and c in L2G_LOW: r = L2G_LOW[c]
            if r is None and c == "S": r = "Σ" if up else None
            if r is None and c == "l" and up: r = "Ι"
            if r is None: return None
            if r == "σ" and (i == len(w) - 1): r = "ς"
            if up and c in ("l",): r = "Ι"
            out.append(r)
        return "".join(out)
    tab = G2L if maj == "l" else L2C
    out = "".join(tab.get(c, c) if _script(c) != maj else c for c in w)
    return out if len({_script(c) for c in out} - {"o"}) == 1 else None
def _fix_token(w):
    sc = collections.Counter(_script(c) for c in w); sc.pop("o", None)
    if len(sc) < 2 or UNITS.match(w): return w
    if set(w) <= ROMAN: return w.replace("Ι", "I").replace("Χ", "X")            # roman numeral typed with Greek Ι/Χ
    if re.match(r"^l(?=[Α-ΩΆ-Ώ])", w) and all(_script(c) == "g" for c in w[1:]): return "• " + w[1:]   # Wingdings bullet 'l'
    m = re.fullmatch(r"([ivx]+)([\u0370-\u03ff]+)|([\u0370-\u03ff]+)([ivx]+)", w)
    if m: return " ".join(x for x in m.groups() if x)                              # 'iiγ' = roman numeral + list letter
    # broken accent glyph: a single Latin capital L/R/S standing for the tonos inside a lowercase Greek word ('ΚαλλικραL', 'χωRρων')
    lat = [c for c in w if _script(c) == "l"]
    if len(lat) == 1 and lat[0] in "LRS" and sc["g"] >= 1 and not any(c.isupper() for c in w if _script(c) == "g" and c != w[0]):
        return w.replace(lat[0], "")
    maj = max(("g", "l", "c"), key=lambda k: (sc[k], k == "g"))
    order = [maj] + [k for k in ("g", "l", "c") if k != maj and sc[k]] + [k for k in ("l", "g", "c") if k != maj and not sc[k]]
    # all-capital Greek look-alikes around Latin letters without a Greek twin ('ΤΑΧΙS', 'ΗD', 'Κm') read as Latin
    if all(c in G2L for c in w if _script(c) == "g") and any(_script(c) == "l" and c not in L2G and c not in L2G_LOW for c in w):
        order = ["l"] + [k for k in order if k != "l"]
    for k in order:
        r = _to(w, k)
        if r: return r
    # glued words of two scripts ('ήHARDWARE', 'deliveryκλπ'): split at the script boundary
    return re.sub(r"(?<=[\u0370-\u03ff\u1f00-\u1fff])(?=[A-Za-z\u00c0-\u024f])|(?<=[A-Za-z\u00c0-\u024f])(?=[\u0370-\u03ff\u1f00-\u1fff])|(?<=[\u0400-\u04ff])(?=[^\u0400-\u04ff])|(?<=[^\u0400-\u04ff])(?=[\u0400-\u04ff])", " ", w)
def fix_mixed_scripts(t):
    t = t.replace("HYPERLINK", " ").replace("myKEΠlive", "myKEPlive")
    t = re.sub(r"(?<![^\W\d_])[οo][Cc](?![^\W\d_])", "°C", t)            # '37 οC' (omicron as degree sign)
    t = re.sub(r"(?<![^\W\d_])[іІ]+(?![^\W\d_])", lambda m: m.group(0).replace("і", "i").replace("І", "I"), t)   # Cyrillic і as roman numeral 'ii'
    return TOKEN.sub(lambda m: _fix_token(m.group(0)), t)
def mixed_tokens(t):
    return [w for w in TOKEN.findall(t) if len({_script(c) for c in w} - {"o"}) > 1 and not UNITS.match(w)]
# Diavgeia's digital-signature box (Latin text drawn over page 1): 'signed by Ministry of Digital Governance', 'INFORMATICS DEVELOPMENT AGENCY',
# 'Hellenic Republic', 'Date: 2026.07.30 12:00:06 EEST', 'Reason:', 'Location: Athens', and the signer's name in Latin capitals
SIGW = set("signed by Digitally Digital Governance Ministry of Hellenic Republic Date Reason Location Athens INFORMATICS INFORMATIC S AGENCY "
           "DEVELOPMENT DEVELOPMEN DEVELOPME T NT EEST EET".split())
def _sig_line(l):
    l = re.sub(r"\d{4}\.\d\d\.\d\d|\d\d:\d\d:\d\d|[+-]\d\d'?\d\d'?|[:.,]", " ", l).strip()
    if not l or re.search(r"[\u0370-\u03ff\d]", l): return None
    ws = l.split()
    if all(w in SIGW or re.fullmatch(r"[A-Z]{2,15}", w) for w in ws):
        return "key" if any(w in ("signed", "Digitally", "Reason") for w in ws) else "ok"
    return None
STRONG = {"INFORMATICS", "DEVELOPMEN", "DEVELOPMENT", "DEVELOPME", "AGENCY", "EEST", "EET", "Hellenic", "Republic", "Ministry", "Governance", "Digitally", "signed", "Reason"}
def strip_signature(t):
    """Remove the signature box: each contiguous block of box-only lines that contains a box word (signed / Digitally / Reason /
    INFORMATICS / DEVELOPMENT / AGENCY / EEST / Hellenic Republic ...), box words glued to Greek text on the first page
    ('ΑΝΑΡΤΗΤΕΑReason:', 'ΟΡΘΗ DEVELOPMEN'), and the municipality signer's caption ('Ψηφιακά υπογεγραμμένο από NAME
    Ημερομηνία: 2023.09.14'). Returns (text, n)."""
    ls = t.split("\n"); keep = [True] * len(ls); n = 0; i = 0
    while i < len(ls):
        if _sig_line(ls[i]) is None: i += 1; continue
        j = i; key = False
        while j < len(ls) and (_sig_line(ls[j]) is not None or (not ls[j].strip() and j + 1 < len(ls) and _sig_line(ls[j + 1]) is not None)):
            key = key or _sig_line(ls[j]) == "key" or bool(set(re.findall(r"[A-Za-z]+", ls[j])) & STRONG); j += 1
        if key and j - i <= 25:
            for k in range(i, j): keep[k] = False
            n += 1
        i = max(j, i + 1)
    out = []
    for k, l in enumerate(ls):
        if keep[k]: out.append(l)
        elif not out or out[-1] != "": out.append("")
    t = "\n".join(out)
    head, tail = t[:6000], t[6000:]
    head, k1 = re.subn(r"(Digitally signed by|signed by|Digitally|Reason:|INFORMATICS(?: AGENCY)?|DEVELOPMENT?(?: AGENCY)?|DEVELOPME|Hellenic Republic(?: Date:)?)", " ", head)
    head, k2 = re.subn(r"Ψηφιακά\s+(?:υπογεγραμμένο|υπογράφηκε)\s+από\s*(?:\n?[ \t]*[A-Z][A-Z.\-]+[ \t]*){1,4}(?:\n?[ \t]*Ημερομηνία:\s*\d{4}\.\d\d\.\d\d(?:\s+\d\d:\d\d(?::\d\d)?)?(?:\s*[+-]\d\d'?\d\d'?)?)?", "", head)
    head = re.sub(r"(?m)^[ \t]+$", "", head)
    t = head + tail
    t, k = re.subn(r"(?m)(?<=\S)signed by$", "", t)          # 'ΑΔΑ: 66signed by' (box text glued to a line end)
    return t, n + k + k1 + k2
ADA_RX = r"[0-9Α-ΩA-Z]{4,}[0-9Α-ΩA-Z]*-[0-9Α-ΩA-Z]{1,3}"
def _ada_rx(ada):
    alt = {"Α": "ΑA", "Β": "ΒB", "Ε": "ΕE", "Ζ": "ΖZ", "Η": "ΗH", "Ι": "ΙI", "Κ": "ΚK", "Μ": "ΜM", "Ν": "ΝN", "Ο": "ΟO", "Ρ": "ΡP", "Τ": "ΤT", "Υ": "ΥY", "Χ": "ΧX"}
    return r"\s*".join(("[" + alt[c] + "]") if c in alt else re.escape(c) for c in ada)
def _ada_lb(ada):
    """the ADA must not continue a longer code: no capital before it; no digit either when the ADA itself starts with a digit
    (an ADA that starts with a letter can be glued to a number: '22/1990ΒΕΑΛΩΨ8-6ΝΤ')"""
    return r"(?<![0-9Α-ΩA-Z])" if ada[:1].isdigit() else r"(?<![Α-ΩA-Z])"
def strip_own_stamps(t, ada):
    """Remove the act's own per-page stamp 'ΑΔΑ: <ada>' wherever pdftotext put it: on its own line, split over two lines
    ('ΑΔΑ:' / '<ada>'), glued to text ('τάφωνΑΔΑ: Β4ΛΜΩΗ9-Α9Μ'), or as a bare '<ada>' line; then the orphan 'ΑΔΑ:' labels of
    those stamps (an 'ΑΔΑ:' not followed by any ADA)."""
    rx = _ada_rx(ada)
    t, n = re.subn(r"(?:(?:ΑΔΑ|Α\.Δ\.Α\.?)[ \t]*:?[ \t]*\n?[ \t]*)?" + _ada_lb(ada) + rx + r"(?![0-9Α-ΩA-Z])", " ", t)
    if n:
        t = re.sub(r"(?:ΑΔΑ|Α\.Δ\.Α\.?)[ \t]*:(?![ \t]*\n?[ \t]*\(?" + ADA_RX + ")", " ", t)
        t = re.sub(r"(?m)^[ \t]+|[ \t]+$", "", t); t = re.sub(r"[ \t]{2,}", " ", t)
    return t
def own_stamp_lines(t, ada):
    return [m.group(0) for m in re.finditer(_ada_lb(ada) + _ada_rx(ada) + r"(?![0-9Α-ΩA-Z])", t)]
def fix_spacing_accent(t):
    """NFKC turns a spacing tonos/acute (U+0384, U+00B4) into ' ' + U+0301. Before a capital vowel it is that vowel's accent (' ́Αρθρο' ->
    'Άρθρο'); after a letter it is an apostrophe / numeral sign ('υπ ́αριθμ' -> 'υπ’αριθμ', 'τ. Β ́' -> 'τ. Β’'); a lone one is dropped."""
    t = re.sub(r"(?: \u0301)([ΑΕΗΙΟΥΩ])", lambda m: unicodedata.normalize("NFC", m.group(1) + "\u0301"), t)
    t = re.sub(r" \u0301(?=[ΆΈΉΊΌΎΏ])", "", t)
    t = re.sub(r"(?<=[^\W\d_.]) \u0301", "’", t)
    t = re.sub(r"(?<=[.\d]) \u0301", "’", t)
    t = re.sub(r" \u0301", "", t)
    # what is left cannot compose: after a line break or a closing bracket / slash it is a numeral sign ('ΦΕΚ 143/τ. Α )́' -> 'Α)’'),
    # after an already accented vowel it is a doubled accent ('αποτελεί́') - dropped; NFC first so composable pairs stay letters
    t = unicodedata.normalize("NFC", t)
    t = re.sub(r"\n\u0301", "\n", t)
    return t.replace("\u0301", "")

def fix_combining(t):
    """combining marks that some PDFs use as letters or punctuation (after NFKC): U+031F (combining plus sign below) is the glyph of 'π'
    in some fonts ('Τρο\u031fο\u031fοίηση' = 'Τροποποίηση'); a loose U+0308 (NFKC of '¨' after a space / at line start) is a quote mark;
    a loose U+0313 after a space is an apostrophe ('υπ \u0313 αρ.' -> 'υπ’ αρ.'); any other combining mark without a letter base is dropped"""
    t = t.replace("\u031f", "π")
    t = re.sub(r"(?<=\S) \u0308(?=\s|[.,;:)»]|$)", "\"", t)          # closing: 'Θεσσαλονίκης ̈ και' -> 'Θεσσαλονίκης" και'
    t = re.sub(r"(?:(?<=\s)|^)\u0308", "\"", t, flags=re.M)          # opening: 'διάταξης ̈Διόρθωση' -> 'διάταξης "Διόρθωση'
    t = re.sub(r" ?\u0308", "\"", t)
    t = re.sub(r"(?<=\w) \u0313", "\u2019", t)
    out = []
    for i, c in enumerate(t):
        if unicodedata.category(c) == "Mn":
            p = out[-1] if out else ""
            if not p or not unicodedata.category(p).startswith("L"): continue    # no letter base: drop
        out.append(c)
    return unicodedata.normalize("NFC", "".join(out))
def loose_combining(t):
    """gate helper: combining marks not attached to a letter, or attached to a Greek letter (every valid Greek letter+mark is
    precomposed after NFC, so a remaining one is a broken glyph)"""
    bad = []
    for i, c in enumerate(t):
        if unicodedata.category(c) == "Mn":
            p = t[i - 1] if i else ""
            if not p or not unicodedata.category(p).startswith("L") or "\u0370" <= p <= "\u03ff" or "\u1f00" <= p <= "\u1fff": bad.append(t[max(0, i - 10):i + 5])
    return bad

def clean_text(t, ada):
    """C1 (cp1252) and private-use characters mapped, NFKC, page breaks -> \n, control chars removed, '∆' (U+2206) -> 'Δ', Diavgeia
    digital-signature box and the act's own 'ΑΔΑ: <ada>' stamps removed, spacing accents and mixed-script look-alikes repaired."""
    t = map_pua(map_c1(t))
    t = unicodedata.normalize("NFKC", t).replace("\x0c", "\n").replace("\r\n", "\n").replace("\r", "\n").replace("\u2206", "Δ")
    t = re.sub(r"[\x00-\x08\x0b\x0e-\x1f\x7f\ufffd]", " ", t)
    t = fix_combining(t)
    t, _ = strip_signature(t)
    t = strip_own_stamps(t, ada)
    # a capital's tonos printed as a separate spacing accent before it (' ́Αρθρο', NFKC of U+0384) -> the accented capital ('Άρθρο')
    t = fix_spacing_accent(t)
    t = fix_latin_lookalikes(t); t = fix_mixed_scripts(t)
    lines = t.split("\n"); out = []
    sig = re.compile(r"^\s*(Digitally signed by|Ministry of|Ministry|Digital|Governance|of Digital Governance|Date: \d{4}\.\d\d\.\d\d|\d\d:\d\d:\d\d [A-Z]{3,4}|Reason:|Location: \w+|Υπογραφή Ψηφιακά|Ψηφιακά υπογεγραμμένο)\b.*$")
    for l in lines:
        if sig.match(l): continue
        out.append(l.rstrip())
    t = "\n".join(out)
    # letter-spaced text layers (Lamia): a heading-only line 'Άρθρ ο 2 ο', 'Ά ρ θ ρ ο 1 4ο', 'Άρθρ ο 3 0 ο' -> 'Άρθρο 2ο', 'Άρθρο 14ο', 'Άρθρο 30ο'
    t = re.sub(r"(?m)^([ \t]*)([ΆΑ])[ \t]?ρ[ \t]?θ[ \t]?ρ[ \t]?ο[ \t]*(\d)[ \t]?(\d)?[ \t]?(ον|ο)[ \t]*$",
               lambda m: f"{m.group(1)}{m.group(2)}ρθρο {m.group(3)}{m.group(4) or ''}{m.group(5)}" if " " in m.group(0).strip() and m.group(0).strip() != f"{m.group(2)}ρθρο {m.group(3)}{m.group(4) or ''}{m.group(5)}" else m.group(0), t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t

def stamp_adas(raw):
    raw = unicodedata.normalize("NFKC", raw)
    return set(re.sub(r"\s", "", m) for m in re.findall(r"ΑΔΑ\s*:\s*([0-9Α-ΩA-Z]{4,}[0-9Α-ΩA-Z]*-[0-9Α-ΩA-Z]{1,3})(?![0-9Α-ΩA-Z])", raw))

LAT2GR = str.maketrans("ABEZHIKMNOPTYX", "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ")
def same_ada(a, b):
    return a.translate(LAT2GR) == b.translate(LAT2GR)

def text_quality(t):
    """(ok, reason): scans (no text layer) and broken font encodings are rejected (no OCR)."""
    ns = len(re.sub(r"\s", "", t))
    if ns < 200: return False, "no_text_layer"
    gr = len(re.findall(r"[\u0370-\u03ff\u1f00-\u1fff]", t)); la = len(re.findall(r"[A-Za-z\u00c0-\u024f]", t))
    if gr + la == 0 or gr / (gr + la) < 0.6: return False, "bad_text_layer_not_greek"
    if t.count("(cid:") > 5: return False, "bad_text_layer_cid"
    if unreadable_greek_runs(t): return False, "bad_text_layer_broken_font_map"
    # broken ToUnicode maps give Greek letters in impossible sequences; require common Greek words
    f = fold(t)
    if len(re.findall(r"\b(και|του|τησ|των|το|τα|για|με|στο|στην|απο)\b", f)) < max(5, ns // 400): return False, "bad_text_layer_no_greek_words"
    return True, "ok"

FW = re.compile(r"\b(και|του|τησ|των|το|τα|την|τη|για|με|στο|στην|στον|απο|που|σε|ωσ|δεν)\b")
# the common broken Greek font map (glyph ids shifted: 'της'->'ηεο', 'του'->'ηνπ', 'και'->'θαη', 'των'->'ησλ', 'την'->'ηελ',
# 'για'->'γηα', 'στο'->'ζην', 'που'->'πνπ', 'με'->'κε', 'από'->'απφ'): these strings are not Greek words
GFW = re.compile(r"\b(ηεσ|ηεο|ηνπ|θαη|ησλ|ηελ|γηα|ζην|ζηελ|ζηνλ|πνπ|κε|απφ|απν|ζε|δελ)\b")
def unreadable_greek_runs(t, win=2000):
    """Windows of text from a font whose glyph->Unicode map is broken ('ηεο πξάμεο' for 'της πράξης'; several letters collapse,
    so it cannot be repaired without OCR): >= 3 broken-map function words and more of them than real Greek function words.
    Returns the number of such windows."""
    bad = 0
    for i in range(0, max(1, len(t)), win):
        w = fold(t[i:i + win]); g = len(GFW.findall(w))
        if g >= 3 and g > len(FW.findall(w)): bad += 1
    return bad

# ---------------------------------------------------------------- article splitter
ORD = {w: i for i, w in enumerate("πρωτο δευτερο τριτο τεταρτο πεμπτο εκτο εβδομο ογδοο ενατο δεκατο ενδεκατο δωδεκατο".split(), 1)}
HEAD = re.compile(r"(?m)^[ \t\f\v]*(?:'|\uf0b7|•|▪)?[ \t]*(?:(?:Ά|Α|Ά|A)(?:ρθρο|ΡΘΡΟ|ρθρον|ΡΘΡΟΝ| Ρ Θ Ρ Ο)|(?:ά|α)ρθρον?)[ \t]*(\d{1,3}|[Α-Ωα-ωάέήίόύώΆΈΉΊΌΎΏ]+)[ \t]*(?:ον|ο|Ο|ΟΝ|º|°|ο\.|\.)?(?![\d/])[ \t]*([:.,\-–—]?)[ \t]*(.*)$")
REFX = re.compile(r"^((?:του|της|των|τον|και|έως|εως|ως|όπως|σε|στο|στον|στη|στην|στις|ΚΔΚ)\b|παρ\.|παράγρ|περ\.|εδ\.|ν\.|Ν\.|π\.δ|Π\.Δ|,|Κ\.Δ\.Κ|N\.|ν\.\s*\d|απ\.|αποφ|ΚΥΑ\b|Κ\.Υ\.Α)", re.I)   # whole words only ('ΣΤΟΧΟΙ', 'ΤΩΝ' vs 'ΤΟΝΩΣΗ')

def _num(tok):
    if tok.isdigit(): return int(tok)
    return ORD.get(fold(tok))

def heading_candidates(t):
    out = []
    for m in HEAD.finditer(t):
        n = _num(m.group(1)); rest = m.group(3).strip()
        if n is None or n == 0 or REFX.match(rest): continue
        if m.group(0).lstrip(" \t\f\v'•▪\uf0b7")[:1] in "άα":     # lowercase 'άρθρο N' at line start: a heading only with a title (same or next line)
            nl = next((x for x in t[m.end():m.end() + 300].split("\n") if x.strip() and not re.fullmatch(r"\s*-?\s*\d{1,3}\s*-?\s*", x)), "").strip()   # skip page numbers
            if rest and not re.match(r"[«\"]?[Α-ΩΆΈΉΊΌΎΏ∆]", rest): continue      # '∆' (U+2206) is printed for Δ in some fonts
            if not rest and not (re.match(r"[«\"]?[Α-ΩΆΈΉΊΌΎΏ∆]", nl) and not re.match(r"^\(|^\)", nl)): continue
        if m.group(2) == "," and not re.match(r"[Α-ΩΆΈΉΊΌΎΏA-Z«\"]", rest): continue   # 'Άρθρο 5, Title' (Thessaloniki ΟΕΥ) yes; 'άρθρο 5, παρ. 2' no
        if re.search(r"\.{4,}|…{2,}|_{4,}|(\.\s){4,}", rest): continue        # table-of-contents line (dot leaders, page number)
        nxt = next((x for x in t[m.end():m.end() + 400].split("\n") if x.strip()), "")
        if re.search(r"\.{4,}|…{2,}|_{4,}", nxt) and len(nxt) < 200: continue   # TOC entry whose title (or dot leaders) wraps onto the next line
        out.append((m.start(), m.end(), n, rest))
    return out

def _chain(c):
    """Best increasing chain (step 1..5) over candidate list c: chains starting at 1 and densest (fewest gaps) first."""
    if not c: return []
    dp = [1] * len(c); prv = [-1] * len(c)
    for j in range(len(c)):
        for k in range(j):
            if c[k][2] < c[j][2] <= c[k][2] + 5 and dp[k] + 1 > dp[j]: dp[j], prv[j] = dp[k] + 1, k
    def score(j):
        ch = []; x = j
        while x != -1: ch.append(x); x = prv[x]
        ch.reverse(); first = c[ch[0]][2]
        gaps = sum(c[ch[i]][2] - c[ch[i - 1]][2] - 1 for i in range(1, len(ch))) + (first - 1)
        return (len(ch) - gaps, len(ch), -first), ch
    return max((score(j) for j in range(len(c))), key=lambda s: s[0])[1]

def _is_toc_chain(t, ch):
    """A chain of headings that is a table of contents: almost nothing after each heading line, and no sentences."""
    after, sent = [], 0
    for i, x in enumerate(ch[:-1]):
        sec = t[x[1]:ch[i + 1][0]]; after.append(len(sec.strip()))
        if re.search(r"[.;](\s|$)", (x[3] or "") + " " + sec): sent += 1
    after.sort()
    return after[len(after) // 2] < 40 and sent < 0.3 * len(after)

def split_articles(t):
    """Line-start 'Άρθρο N' headings. Text before the first heading is art-0 (Προοίμιο: decision header, minutes, legal basis).
    Many decisions carry the regulation more than once (the text inside the minutes + the attached regulation, or repeated pages):
    the numbering restarts at 1. Each restart opens a new block; block 1 labels are 'N', block k >= 2 labels 'bK.N'
    (e.g. 'b2.1'). Within a block: best increasing chain (step 1..5; gaps recorded). Unpunctuated tables of contents are skipped.
    Returns (articles[(label,title,body)], coverage, check)."""
    c = heading_candidates(t)
    # an unpunctuated table of contents ('Άρθρο 1 Ορισμοί / Άρθρο 2 ...' one per line, the body following later with the same numbers):
    # a candidate whose section is < 150 chars and whose number occurs again later is a TOC entry, not a split point
    toc = set()
    for i, x in enumerate(c):
        nxt = c[i + 1][0] if i + 1 < len(c) else len(t)
        sec = t[x[1]:nxt]; body = sec.split("\n", 1)[1] if (not x[3] and "\n" in sec.strip("\n")) else sec
        if len(sec.strip()) < 150 and len(body.strip()) < 80 and any(y[2] == x[2] and y[0] > x[0] for y in c[i + 1:]): toc.add(i)   # TOC: title only, no text
    ntoc = len(toc)
    c = [x for i, x in enumerate(c) if i not in toc]
    chk = {"marker": "Άρθρο", "gaps": [], "hidden": [], "restarts": 0, "toc_entries_skipped": ntoc, "blocks": 0}
    # blocks: cut before every candidate numbered 1 that follows a higher number
    blocks, cur = [], []
    low = lambda x: t[x[0]:x[1]].lstrip(" \t\f\v'•▪\uf0b7")[:1] in "άα"
    for x in c:
        if cur and not low(x) and ((x[2] == 1 and max(y[2] for y in cur) >= 2) or (x[2] <= 3 and max(y[2] for y in cur) >= x[2] + 3)): blocks.append(cur); cur = []   # numbering restarts (at 1, or 2/3 when Άρθρο 1 is unnumbered)
        cur.append(x)
    if cur: blocks.append(cur)
    chains = []
    for b in blocks:
        ch = [b[i] for i in _chain(b)]
        if len(ch) >= 3 and _is_toc_chain(t, ch): chk["toc_blocks_skipped"] = chk.get("toc_blocks_skipped", 0) + 1; continue   # a table of contents (titles only)
        if len(ch) >= 2 and ch[0][2] <= 3: chains.append((b, ch))
    if not chains:
        return [("0", None, t)], 1.0, dict(chk, marker=None, candidates=len(c))
    chk["blocks"] = len(chains); chk["restarts"] = len(chains) - 1
    allch = []
    for k, (b, ch) in enumerate(chains, 1):
        nums = [x[2] for x in ch]
        g = [n for i in range(1, len(nums)) for n in range(nums[i - 1] + 1, nums[i])] + list(range(1, nums[0]))
        chk["gaps"] += g if k == 1 else [f"b{k}.{n}" for n in g]
        chosen = set(id(x) for x in ch)
        for x in b:     # hidden: an unchosen candidate whose number fills a gap between its chosen neighbours
            if id(x) in chosen: continue
            prev = max([y for y in ch if y[0] < x[0]], default=None, key=lambda y: y[0]); nxt = min([y for y in ch if y[0] > x[0]], default=None, key=lambda y: y[0])
            if prev and prev[2] < x[2] and (nxt is None or x[2] < nxt[2]) and x[2] in g: chk["hidden"].append(x[2] if k == 1 else f"b{k}.{x[2]}")
        allch += [(x, (str(x[2]) if k == 1 else f"b{k}.{x[2]}")) for x in ch]
    arts = []
    pre = t[:allch[0][0][0]].strip()
    if pre: arts.append(("0", "Προοίμιο", pre))
    for i, ((s_, e, n, rest), lab) in enumerate(allch):
        end = allch[i + 1][0][0] if i + 1 < len(allch) else len(t)
        body = t[s_:end].strip()
        head = t[s_:e].strip()
        title = head
        if not rest:
            after = t[e:end].lstrip("\n").split("\n", 1)[0].strip()
            if 0 < len(after) < 120 and not after.endswith((".", ",", ";", ":")) and not re.match(r"^\d+\.", after): title = f"{head} – {after}"
        arts.append((lab, re.sub(r"\s+", " ", title), body))
    cov = sum(len(b) for _, _, b in arts) / max(1, len(t.strip()))
    return arts, min(cov, 1.0), chk

AMEND = re.compile(r"(τροποποι|συμπληρω|αντικατασταση|αντικαθιστα|προστιθετ|προσθηκη|καταργ|κωδικοποι)")
QUOTE = re.compile(r"(ωσ εξησ|ωσ ακολουθωσ|αντικαθισταται|τροποποιειται|προστιθεται|διαμορφωνεται|συμπληρωνεται|νεο κειμενο|τροπολογια)")
def amending_with_quoted_articles(subject, t):
    """Amending decision whose 'Άρθρο N' lines are the amended regulation's articles quoted with their new wording."""
    return bool(AMEND.search(fold(subject)) and QUOTE.search(fold(t)))

def heading_run(t):
    """Longest increasing run (steps 1..5) of line-start 'Άρθρο N' headings - used by the whole-text gate."""
    vs = [x[2] for x in heading_candidates(t)]
    dp = []
    for j, v in enumerate(vs): dp.append(1 + max([dp[k] for k in range(j) if vs[k] < v <= vs[k] + 5] or [0]))
    return max(dp or [0])

LOOSE = re.compile(r"(?mi)^[ \t\W]{0,4}[ΆάΑαA][ \t]?[Ρρ][ \t]?[Θθ][ \t]?[Ρρ][ \t]?[Οο][Νν]?[ \t]*(\d{1,3})(?![\d/])[^\n]{0,80}")
def loose_heading_run(t, skip_dense=False):
    """Independent check for the whole-text gate (does not reuse HEAD): any line starting with Άρθρο/ΑΡΘΡΟ/άρθρο (also letter-spaced)
    + number, minus references ('άρθρο 67 παρ. 6 του Ν.') and table-of-contents lines; longest increasing run (steps 1..5)."""
    vs = []
    ms = list(LOOSE.finditer(t))
    for i, m in enumerate(ms):
        if skip_dense and ((i + 1 < len(ms) and ms[i + 1].start() - m.end() < 300) or (i > 0 and m.start() - ms[i - 1].end() < 300 and i + 1 == len(ms))): continue
        line = t[m.start():t.find("\n", m.end()) if t.find("\n", m.end()) != -1 else len(t)]; rest = re.sub(r"^\D*\d{1,3}\s*(?:ον|ο|°|º)?\s*[:.,\-–—]?\s*", "", line, count=1, flags=re.I)
        if REFX.match(rest) or re.match(r"(?i)(παρ\.|παράγρ|ν\.|εδ\.|περ\.|απ\.|αποφ|κυα|π\.?δ|β\.?δ|\(|§|ν\s*\d|Ν\s*:)", rest): continue
        if re.search(r"\.{4,}|…{2,}|_{4,}|\s\d{1,3}\s*$|,\s*$", line): continue     # TOC / page number / 'Άρθρο 7,' table cell
        nxt = next((x for x in t[m.end():m.end() + 300].split("\n") if x.strip()), "")
        if re.search(r"\.{4,}|…{2,}|_{4,}", nxt) or re.fullmatch(r"\s*\d{1,3}\s*", nxt): continue    # TOC: dot leaders / page number on the next line
        vs.append(int(m.group(1)))
    dp = []
    for j, v in enumerate(vs): dp.append(1 + max([dp[k] for k in range(j) if vs[k] < v <= vs[k] + 5] or [0]))
    return max(dp or [0])

# ---------------------------------------------------------------- dates
MONTHS = {"ιανουαριου": 1, "φεβρουαριου": 2, "μαρτιου": 3, "απριλιου": 4, "μαιου": 5, "ιουνιου": 6, "ιουλιου": 7, "αυγουστου": 8,
          "σεπτεμβριου": 9, "οκτωβριου": 10, "νοεμβριου": 11, "δεκεμβριου": 12}
D_NUM = r"(\d{1,2})[./-](\d{1,2})[./-]((?:19|20)?\d\d)"
D_TXT = r"(\d{1,2})(?:η|ης)?\s+(" + "|".join(MONTHS) + r")\s+((?:19|20)\d\d)"

def _iso(d, m, y):
    y = int(y); y = y + 2000 if y < 100 else y
    try: return datetime.date(y, int(m), int(d)).isoformat()
    except ValueError: return None

EFF = re.compile(r"(?P<w>ισχυ(?:ει|ουν|σει|σουν|σ)?|εναρξη ισχυοσ|τιθεται σε (?:ισχυ|εφαρμογη)|εφαρμοζεται|εφαρμογη)\s(?P<gap>.{0,60}?)(απο|την)\s+(την\s+)?(?P<d>" + D_NUM + "|" + D_TXT + ")")
EFF_NOT = re.compile(r"(μεχρι|εωσ|εντοσ|ληξη|ληγει|παραταση|διαρκεια|παρατειν|ισχυοντ|ισχυσαν)")
def text_effective(t, issue=None):
    """Own effective-date clause ('ισχύει από 1-1-2024', 'έναρξη ισχύος … 01.03.2025', 'τίθεται σε ισχύ από 1η Ιανουαρίου 2024').
    End dates ('ισχύ μέχρι …') are skipped; the last clause in text order wins. Returns (date, kind) or (None, 'on_publication'/None)."""
    f = fold(t)
    ds = []
    for m in EFF.finditer(f):
        if EFF_NOT.search(m.group("gap")) or EFF_NOT.search(f[max(0, m.start() - 12):m.start()]): continue   # 'ισχύ μέχρι 31.12.2026' is an end date
        if re.search(r"[.;]\s", m.group("gap")): continue                   # the clause ended before the date ('έχει ισχύ νόμου. … από 24-9/20-10-1958')
        if re.match(r"[/\-.]\d", f[m.end():m.end() + 2]): continue          # part of a compound date of a quoted act ('24-9/20-10-1958')
        win = f[max(0, m.start() - 120):m.end()]
        own = re.search(r"\bπαρ(ων|ουσα|ον|οντοσ|ουσασ)\b|\bο\s+κανονισμοσ\b|\bη\s+(παρουσα\s+)?αποφαση\b|\bο\s+οργανισμοσ\b", win)
        if m.group("w").startswith("εφαρμ") and not own: continue           # 'από 1.1.2028 εφαρμόζει το «Πληρώνω όσο πετάω»' is one provision
        s = m.group("d"); a = re.match(D_NUM, s)
        iso = _iso(*a.groups()) if a else (lambda b: _iso(b.group(1), MONTHS[b.group(2)], b.group(3)))(re.match(D_TXT, s))
        if iso and issue and iso > (datetime.date.fromisoformat(issue) + datetime.timedelta(days=365)).isoformat() and not own: continue   # sanity: > 1 year after issue only for the act's own clause
        if iso and not (issue and iso < (datetime.date.fromisoformat(issue) - datetime.timedelta(days=400)).isoformat()):   # older dates: quoted acts
            ds.append((0 if m.group("w").startswith("εφαρμ") else 1, iso))
    if ds:   # the last ισχύ/έναρξη ισχύος clause in text order (final provisions); 'εφαρμόζεται από' only when there is none
        strong = [d for k, d in ds if k == 1]
        return (strong or [d for _, d in ds])[-1], "text_own_clause"
    if re.search(r"(ισχυ\w*|τιθεται σε ισχυ|εναρξη ισχυοσ).{0,60}(δημοσιευσ|αναρτησ)", f): return None, "on_publication"
    return None, None

import datetime

# ---------------------------------------------------------------- issuing organ (verify round 1)
# Only the municipal council (Δημοτικό Συμβούλιο) adopts regulatory acts (Κώδικας Δήμων και Κοινοτήτων art. 79); the committees
# (Οικονομική Επιτροπή, Επιτροπή Ποιότητας Ζωής, Δημοτική Επιτροπή, Εκτελεστική Επιτροπή) and community councils draft them and
# recommend them to the council ('εισηγείται στο Δημοτικό Συμβούλιο'). Their decisions are not the adopted act.
ORGANS = {"council": r"δημοτικ\w*\s+συμβουλι\w*|δημ\.\s*συμβουλι\w*",
          "finance_committee": r"οικονομικ\w*\s+επιτροπ\w*",
          "quality_of_life_committee": r"επιτροπ\w*\s+ποιοτητ\w*\s+(τησ\s+)?ζωησ",
          "municipal_committee": r"δημοτικ\w*\s+επιτροπ\w*",
          "executive_committee": r"εκτελεστικ\w*\s+επιτροπ\w*",
          "community_council": r"συμβουλι\w*\s+(τησ\s+)?(\w{1,2}['΄’]?\s+)?(δημοτικησ\s+|τοπικησ\s+)?κοινοτητ\w*"}   # 'το συμβούλιο της Α' Δημοτικής Κοινότητας'
_ANY = "|".join(f"(?P<{k}>{v})" for k, v in ORGANS.items())
# in an explicit 'ΑΠΟΣΠΑΣΜΑ / πρακτικό … συνεδρίασης της <organ>' header a bare 'Δημοτική / Τοπική Κοινότητα' is the community council
# ('Απόσπασμα από το πρακτικό της 3ης συνεδρίασης της Δημοτικής Κοινότητας Λαμιέων'); elsewhere it is only a place name
_ANY_H = _ANY.replace("(?P<community_council>", "(?P<community_council>(δημοτικ|τοπικ)\\w*\\s+κοινοτητ\\w*|")
_SESS = re.compile(r"(συνηλθ\w*|συνεδριασ\w*|συνεδριαζ\w*|πρακτικ\w*)[^.;]{0,160}?\b(του|τησ|το|η)\s+(" + _ANY + ")")
REC = re.compile(r"(εισηγ\w*|παραπεμπ\w*|προτειν\w*|διαβιβαζ\w*|υποβαλλ?\w*)[^.]{0,200}?(δημοτικο\s+συμβουλιο|δ\.\s?σ\b)")
# meeting-header forms, each naming the organ that met: 'συνήλθε … η Επιτροπή Ποιότητας Ζωής', 'Το Δημοτικό Συμβούλιο Ηρακλείου
# συνεδρίασε', 'ΠΡΑΚΤΙΚΟ 24ο/2014 τακτικής συνεδρίασης Δημοτικού Συμβουλίου', 'Απόσπασμα από το πρακτικό … της Οικονομικής Επιτροπής'
_HDR = [_SESS,
        re.compile(r"\b(το|η)\s+(" + _ANY.replace("?P<", "?P<b_") + r")[^.;:]{0,50}?\b(συνεδριασ\w*|συνηλθ\w*|συνεδριαζ\w*)"),
        re.compile(r"(πρακτικ\w*|αποσπασμα)[^.;:]{0,80}?(συνεδριασ\w*|συνεδριαση)\s+(του\s+|τησ\s+)?(\d{1,2}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{2,4}\s+)?(" + _ANY_H.replace("?P<", "?P<c_") + ")"),   # '… συνεδρίασης της 01-10-2013 Επιτροπής Ποιότητας Ζωής' 
        re.compile(r"αποσπασμα[^.;:]{0,60}?πρακτικ\w*[^.;:]{0,60}?\b(του|τησ)\s+(" + _ANY_H.replace("?P<", "?P<d_") + ")"),
        # 'Απόσπασμα της με αριθ. 6/29-09-2014 συνεδρίασης Δημοτικής Κοινότητας Αγ. Βασιλείου' (abbreviation dots inside the header)
        re.compile(r"αποσπασμα[^;:\n]{0,80}?συνεδριασ\w*\s+(του\s+|τησ\s+)?(" + _ANY_H.replace("?P<", "?P<e_") + ")"),
        # 'Η Δημοτική Κοινότητα Αγ. Βασιλείου συνεδρίασε σήμερα …'
        re.compile(r"\bη\s+(?P<f_community_council>(δημοτικ|τοπικ)\w*\s+κοινοτητ\w*)[^;:\n]{0,60}?\b(συνεδριασ\w*|συνηλθ\w*)")]
# the council's own session record without a header naming it: the councillors' attendance list ('ΠΑΡΟΝΤΕΣ ΚΑΙ ΑΠΟΝΤΕΣ ΔΗΜΟΤΙΚΟΙ
# ΣΥΜΒΟΥΛΟΙ') or the council-session clause ('σύμφωνα με τις διατάξεις του αρ. 74 Ν.4555/2018' / 'άρθρο 67 Ν.3852/2010')
_COUNCIL_SESSION = re.compile(r"παροντεσ\s+(και\s+αποντεσ\s+)?δημοτικοι\s+συμβουλοι|(αρθρ\w*|αρ\.?)\s*74\b[^;\n]{0,30}?4555\s*/\s*2018|(αρθρ\w*|αρ\.?)\s*67\b[^;\n]{0,30}?3852\s*/\s*2010")
_SUBJ = re.compile(r"θεμα\s*:|περιληψη\s*:|\bαποφαση\s+\d+\s*/\s*\d{4}")
def _hdr_organ(h):
    """the earliest meeting header in h: (organ, position) — the header that comes first is the organ that decided; a committee named
    later is a quoted recommendation ('… την αριθμ. 397/2026 απόφαση της Δημοτικής Επιτροπής')"""
    best = None
    for rx in _HDR:
        for m in rx.finditer(h):
            gd = {(k[2:] if k[:2] in ("b_", "c_", "d_", "e_", "f_") else k): v for k, v in m.groupdict().items() if v}
            org = next((k for k in ORGANS if k in gd), None)
            if not org: continue
            if _SUBJ.search(m.group(0)): continue   # the organ is named in the subject line, not in the header
            pos = m.start()
            if best is None or pos < best[1]: best = (org, pos)
            break
    return best
# letterhead department lines name an office, not an organ that met: 'ΔΙΕΥΘΥΝΣΗ ΔΙΟΙΚΗΤΙΚΩΝ ΥΠΗΡΕΣΙΩΝ / ΤΜΗΜΑ ΔΗΜΟΤΙΚΟΥ ΣΥΜΒΟΥΛΙΟΥ',
# 'Γραφείο Δημοτικού Συμβουλίου', 'Γραμματεία Οικονομικής Επιτροπής'; they are blanked (same length) before the organ is read
_LETTERHEAD = re.compile(r"\b(αυτοτελεσ\s+)?(τμημα|γραφειο|γραμματεια|υπηρεσια|τμ\.)\s+(υποστηριξησ\s+)?(πολιτικων\s+οργανων\s+)?(του\s+|τησ\s+)?(" + _ANY.replace("?P<", "?P<l_") + ")")
def _blank_letterhead(h):
    return _LETTERHEAD.sub(lambda m: " " * len(m.group(0)), h)
def issuing_organ(t):
    """(organ, recommends_to_council): the organ of the earliest meeting header ('Απόσπασμα από το πρακτικό … του Δημοτικού Συμβουλίου',
    'Το Δημοτικό Συμβούλιο … συνεδρίασε', 'συνήλθε … η Επιτροπή Ποιότητας Ζωής'); else 'council' when the text carries the councillors'
    attendance list or the council-session clause (art. 74 Ν.4555/2018, art. 67 Ν.3852/2010); else the first organ named in the letterhead."""
    f = re.sub(r"[ \t]+", " ", fold(t)); h = _blank_letterhead(f[:4000])
    b = _hdr_organ(h)
    if b: org = b[0]
    elif _COUNCIL_SESSION.search(h): org = "council"
    else:
        h2 = re.sub(r"(θεμα|περιληψη)\s*:[^\n.;]{0,300}", lambda m: " " * len(m.group(0)), h[:1500])   # not the organ named in the subject line
        m = re.search(_ANY, h2); org = next(k for k in ORGANS if m.group(k)) if m else None
    i = max(f.rfind("αποφασιζει"), f.rfind("αποφασισε"), f.rfind("αποφασιζουν")); op = f[i:i + 1500] if i >= 0 else ""
    rec = bool(REC.search(op)) or bool(re.search(r"\bσχεδιο\w*\s+(του\s+)?κανονισμ", op[:400]))
    return org, rec
