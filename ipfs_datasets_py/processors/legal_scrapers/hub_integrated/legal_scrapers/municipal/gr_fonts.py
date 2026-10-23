"""Broken Greek font maps (no OCR). Diavgeia PDFs typed in non-embedded Greek TrueType fonts often carry a glyph->Unicode
table that is shifted against the real letters ('ηεο πξάμεο' for 'της πράξης'). Five such shifts occur in this corpus (tables A-E);
each is a fixed table shown->real with a few collisions (two real letters drawn as one shown letter, e.g. 'η' = ι or τ).
Per line, every table is tried; each word is read as the lexicon word (from the corpus's clean texts) that the table allows,
highest frequency first; the line is kept only if >= 90% of its words are lexicon words, otherwise it is removed."""
import re, collections, math, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import gr_fixes as G
def T(s):
    d = {}
    for p in s.split():
        k, v = p.split(":"); d[k] = v
    return d
FONTS = {
 "A": T("α:α β:β γ:γ δ:δζ ε:εη ζ:σθ η:ιτ θ:κφ ι:λ κ:μ λ:ν μ:ξ ν:ο ξ:ρ ο:ς π:πυ ρ:χ σ:ω ς:ψς τ:ϊ υ:ϋ φ:ό χ:ύ ψ:ώ ω:ω "
        "ά:ά έ:έ ή:ή ί:ί ό:ό ύ:ύ ώ:ώ ϊ:ϊ ϋ:ϋ "
        "Α:Α Β:Β Γ:ΔΓ Δ:ΕΔ Ε:ΖΕ Ζ:Η Η:ΙΗ Θ:ΘΗ Ι:Ι Κ:Κ Λ:Λ Μ:Μ Ν:ΝΟ Ξ:Ξ Ο:Ο Π:Π Ρ:Ρ \u03a2:ΣΥ Σ:ΤΣ Τ:Υ Υ:ΧΦ Φ:ΦΨ Χ:ΩΧ Ψ:Ψ Ω:Ω "
        "Ά:Ά Έ:Έ Ή:Ή Ί:Ί Ό:Ό Ύ:Ύ Ώ:Ώ"),
 "B": T("Α:ΓΑ Β:Δ Γ:Ε Δ:Ζ Ε:Η Ζ:Θ Η:Ι Θ:Κ Ι:Λ Κ:Μ Λ:Ν Μ:Ξ Ν:Ο Ξ:Π Ο:Ρ Π:Σ Ρ:Τ \u03a2:Υ Σ:Φ Τ:Χ Υ:Ψ Φ:Ω Ώ:ΑΆ Ϊ:έ Ϋ:ή Ω:άα ά:ί Ψ:Ω "
        "α:α β:β γ:γ δ:δ ε:ε ζ:ζ η:η θ:θ ι:ι κ:κ λ:λ μ:μ ν:ν ξ:ξ ο:ο π:π ρ:ρ σ:σ ς:ς τ:τ υ:υ φ:φ χ:χ ψ:ψ ω:ω έ:έ ή:ή ί:ί ό:ό ύ:ύ ώ:ώ"),
 "C": T("α:α β:β γ:γ δ:δ ε:η ζ:σθ η:ιτ θ:κφ ι:λ κ:ν λ:ξ μ:ομ ν:ρ ξ:ς ο:υ π:χπ ρ:ψ σ:φ ς:ω τ:ϊ υ:ό φ:ύ χ:ώ ψ:ώ "
        "ά:ά έ:έ ή:ή ί:ί ό:ό ύ:ύ ώ:ώ "
        "Α:Α Β:Β Γ:ΕΓ Δ:ΔΖ Ε:Η Ζ:ΘΣ Η:ΚΙ Θ:Κ Ι:Λ Κ:Ν Λ:Ξ Μ:ΟΜ Ν:Ρ Ξ:Σ Ο:Ο Π:Π Ρ:Ψ \u03a2:Χ Σ:Φ Τ:Τ Υ:Υ Φ:Φ Χ:Ω Ω:Ω Ά:Ά Έ:Έ Ό:Ό"),
 "E": T("α:α β:β γ:γ δ:δ ε:ε ζ:ζ η:η θ:θ ι:ι κ:κ λ:λ μ:μ ν:ν ξ:ξ ο:ο π:π ρ:ρ σ:ς ς:σ τ:τ υ:υ φ:φ χ:χ ψ:ψ ω:ω "
        "ϋ:έ ύ:ίύ ϊ:ά ό:ήό ά:ά έ:έ ή:ή ί:ί ώ:ώ Ϋ:Έ "
        "Α:Α Β:Β Γ:Γ Δ:Δ Ε:Ε Ζ:Ζ Η:Η Θ:Θ Ι:Ι Κ:Κ Λ:Λ Μ:Μ Ν:Ν Ξ:Ξ Ο:Ο Π:Π Ρ:Ρ \u03a2:Σ Σ:Σ Τ:Τ Υ:Υ Φ:Φ Χ:Χ Ψ:Ψ Ω:Ω"),
 "D": T("α:α β:β γ:γ δ:δ ε:ε ζ:έζ η:ηζ θ:η ι:ιή κ:θκ λ:λ μ:μ ν:ν ξ:ξ ο:ο π:π ρ:ρ σ:ς ς:σ τ:τ υ:υ φ:φύ χ:χ ψ:ψ ω:ω ϊ:ώ "
        "ά:ά έ:έ ή:ή ί:ί ό:ό ύ:ύ ώ:ώ "
        "Α:Α Β:Β Γ:Γ Δ:Δ Ε:Ε Ζ:ΈΖ Η:ΗΖ Θ:ΗΘ Ι:Ι Κ:Κ Λ:Λ Μ:Μ Ν:Ν Ξ:Ξ Ο:Ο Π:Π Ρ:Ρ \u03a2:Σ Σ:ΤΣ Τ:ΥΤ Υ:ΦΥ Φ:ΧΦ Χ:ΨΧ Ψ:ΩΨ Ω:Ω"),  # capitals: shifted in most font-D files, unshifted in some
}
# Some font-A files draw the capitals with a second shift ('Ππμβοπλίοπ' for Συμβουλίου, 'Θοινόιειας' Κοινότητας, 'Ξρόεδρος' Πρόεδρος,
# 'Πιεν' Στην): their capital readings are added to table A as further options (learnt from the residue of the first decode)
_A2 = {"Θ": "Κ", "Ι": "Λ", "Κ": "Μ", "Λ": "Ν", "Ξ": "Π", "Ο": "Ρ", "Π": "Σ", "Ρ": "Τ", "Υ": "Τ", "Φ": "Χ", "Χ": "Υ"}
for _c, _v in list(FONTS["A"].items()):
    if _c.isupper():
        _add = "".join(_A2[x] for x in _v[:1] if x in _A2 and _A2[x] not in _v)
        if _add: FONTS["A"][_c] = _v + _add
WT = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]+")
class Decoder:
    def __init__(self, lex, fonts=FONTS):
        self.lex = lex; self.flex = collections.Counter(); self.fonts = fonts
        for w, n in lex.items(): self.flex[G.fold(w)] += n
        self.pre = {w[:i] for w in lex for i in range(1, len(w) + 1)}
        self.fpre = {w[:i] for w in self.flex for i in range(1, len(w) + 1)}
        self.cache = {}
    def freq(self, w):
        return self.flex.get(G.fold(w), 0) if (len(w) > 1 and w.isupper()) else self.lex.get(w.lower(), 0)
    def inlex(self, w):
        return (G.fold(w) in self.flex) if (len(w) > 1 and w.isupper()) else (w.lower() in self.lex)
    def word(self, w, fn):
        k = (w, fn)
        if k in self.cache: return self.cache[k]
        F = self.fonts[fn]; up = len(w) > 1 and w.isupper()
        opts = [F.get(c) or c for c in w]
        lex, pre = (self.flex, self.fpre) if up else (self.lex, self.pre)
        key = (lambda s: G.fold(s)) if up else (lambda s: s.lower())
        best = None; stack = [("", 0, 0)]
        while stack:
            s, i, pen = stack.pop()
            if i == len(w):
                f = lex.get(key(s), 0)
                if f:
                    sc = math.log(f) - 2.0 * pen
                    if best is None or sc > best[1]: best = (s, sc)
                continue
            for j, ch in enumerate(opts[i]):
                s2 = s + ch
                if key(s2) in pre: stack.append((s2, i + 1, pen + (j > 0)))
        r = best[0] if best else None; self.cache[k] = r; return r
    def line(self, l):
        """(decoded_line, rate, font): words already in the lexicon are kept; every other word is read with the line's main font
        table, else with another table, as the most frequent lexicon word the table allows; words with no reading stay as they are.
        rate = share of words (>= 2 letters) that are lexicon words afterwards; font = the table used most (None if none)."""
        toks = list(WT.finditer(l))
        if not toks: return l, 1.0, None
        reads = {}; known = {}
        for m in toks:
            w = m.group(0)
            f0 = self.freq(w)
            r = {fn: self.word(w, fn) for fn in self.fonts}
            if f0: known[w] = (f0, r); continue
            reads[w] = r
        votes = collections.Counter(fn for w, r in reads.items() for fn, x in r.items() if x)
        order = [fn for fn, _ in votes.most_common()]
        # a lexicon word that is itself broken-font output ('άρκρο' 2x, 'κα' 2,037x next to 'άρθρο' 53,732x, 'θα' 54,781x)
        # is replaced only by the reading of the line's main table, when that reading is far more frequent
        main = order[0] if order else None
        if main is None and known:
            v = collections.Counter(fn for kw, (f0, r) in known.items() for fn, x in r.items() if x and x.lower() != kw.lower() and self.freq(x) > 20 * f0 + 50)
            main = v.most_common(1)[0][0] if v else None
        if main:
            for w, (f0, r) in known.items():
                x = r.get(main)
                if x and x.lower() != w.lower() and self.freq(x) > 20 * f0 + 50: reads[w] = {fn: (x if fn == main else None) for fn in self.fonts}
            if not order: order = [main]
        out = []; last = 0; n = hit = 0; used = collections.Counter()
        for m in toks:
            w = m.group(0); r = w; name = False
            if w in reads:
                for fn in order:
                    if reads[w][fn]: r = reads[w][fn]; used[fn] += 1; break
                else:
                    # no lexicon reading: a capitalised word (a proper name: street, person) is read with the line's main
                    # table, first reading of each letter; it does not count against the line
                    if order and w[0].isupper() and not w.isupper() and not self.inlex(w):
                        r = "".join((self.fonts[order[0]].get(c) or c)[0] for c in w); name = True
                    elif order and re.search("ς[\u0370-\u03ff]", w) and not self.inlex(w):
                        # a final sigma inside a word cannot be real text: read the word letter by letter with the main table
                        r2 = "".join((self.fonts[order[0]].get(c) or c)[0] for c in w)
                        if not re.search("ς[\u0370-\u03ff]", r2): r = r2
            if len(w) >= 2 and not name: n += 1; hit += self.inlex(r)
            out += [l[last:m.start()], r]; last = m.end()
        out.append(l[last:])
        return "".join(out), (hit / n if n else 1.0), (used.most_common(1)[0][0] if used else None)
    def override(self, l, fn):
        """lexicon words in l that are broken-font output of table fn ('Άρκρο' 2x -> 'Άρθρο' 53,732x): replaced by the fn reading
        when that reading is > 20x + 50 more frequent; returns (line, number of words replaced)"""
        n = 0; out = []; last = 0
        for m in WT.finditer(l):
            w = m.group(0)
            if len(w) == 1 and l[m.end():m.end() + 1] in (")", "΄", "'"): continue   # enumerator 'ε)' / numeral 'ε΄'
            f0 = self.freq(w); x = self.word(w, fn) if f0 else None
            if x and x.lower() != w.lower() and self.freq(x) > 20 * f0 + 50:
                out += [l[last:m.start()], x]; last = m.end(); n += 1
        out.append(l[last:])
        return "".join(out), n
    def rate(self, l):
        ws = [w for w in WT.findall(l) if len(w) >= 2]
        return sum(1 for w in ws if self.inlex(w)) / len(ws) if ws else 1.0
def repair(D, t, flags):
    """flagged lines: decoded when the decoded line is >= 90% lexicon words; kept as they are when nothing was decoded and they are
    already >= 90% lexicon words; else removed"""
    ls = t.split("\n"); out = []; st = collections.Counter()
    for l, why in zip(ls, flags):
        if not why: out.append(l); continue
        r0 = D.rate(l)
        dl, r1, font = D.line(l)
        if (r0 >= 0.9 and (not font or dl == l)) and "\u03a2" not in l and not re.search(r"[\u0400-\u04ff]", l):
            out.append(l); st["lines_kept_as_is"] += 1; continue
        if font and r1 >= 0.9 and "\u03a2" not in dl and not re.search(r"[\u0400-\u04ff]", dl):
            out.append(dl); st["lines_decoded"] += 1; st["chars_decoded"] += len(l); st["font_" + font] += 1
        else:
            st["lines_removed"] += 1; st["chars_removed"] += len(l)
            if not out or out[-1] != "": out.append("")
    return "\n".join(out), st

# ---------------------------------------------------------------- broken-line detection
GTOK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]{3,}")
def build_lexicon(texts, min_count=2):
    """lowercase (accented) word counts from texts that have no broken-font signal; words seen >= min_count times"""
    c = collections.Counter()
    for t in texts:
        for m in WT.finditer(t):
            w = m.group(0)
            if len(w) == 1 and t[m.end():m.end() + 1] in (")", "΄", "'"): continue   # enumerators 'ε)', numerals 'ε΄' are not words
            c[w.lower()] += 1
    return collections.Counter({w: n for w, n in c.items() if n >= min_count})
# font D ('ςτθν', 'τθσ', 'τουσ'): its function words; and a lowercase word ending in 'σ' (real Greek ends in 'ς')
GFW_D = re.compile(r"(?<![\u0370-\u03ff])(τθν|τθσ|ςτο|ςτθν|ςτον|ςτα|ςτισ|ςε|τουσ|τισ|ωσ|θ|κα|είναι|διμου|δθμοτικό)(?![\u0370-\u03ff])")
FINAL_SIGMA = re.compile(r"[α-ωά-ώ]{2,}σ(?![\u0370-\u03ff\u1f00-\u1fff])")
def clean_signal(t):
    """True when a text has no broken-font signal at all (used to pick the lexicon's texts)"""
    return ("\u03a2" not in t and not G.unreadable_greek_runs(t) and not re.search(r"[\u0400-\u04ff]", t)
            and len(FINAL_SIGMA.findall(t)) <= 2)
def line_flag(l, flex):
    if "\u03a2" in l: return "u03a2"
    for w in G.TOKEN.findall(l):
        s = {G._script(c) for c in w} - {"o"}
        if "c" in s and "g" in s: return "cyrillic_in_greek"
    f = G.fold(l); g = len(G.GFW.findall(f)); fw = len(G.FW.findall(f))
    if g >= 2 and g > fw: return "broken_function_words"
    gd = len([x for x in GFW_D.findall(l.lower()) if x not in ("είναι",)])
    if gd >= 2 and len(FINAL_SIGMA.findall(l)) >= 1 and gd > fw: return "broken_function_words"
    if FINAL_SIGMA.search(l): return "final_sigma"
    toks = [G.fold(w) for w in GTOK.findall(l)]
    if len(toks) >= 3:
        oov = sum(1 for w in toks if w not in flex)
        if oov / len(toks) >= 0.6 and fw <= 1: return "oov"
    return None
def broken_lines(t, flex):
    ls = t.split("\n"); fl = [line_flag(l, flex) for l in ls]
    for i, l in enumerate(ls):     # short lines next to a broken line whose words are all unknown belong to the run
        if fl[i] or not GTOK.search(l): continue
        near = any(fl[j] for j in range(max(0, i - 2), min(len(ls), i + 3)) if j != i)
        toks = [G.fold(w) for w in GTOK.findall(l)]
        if near and toks and all(w not in flex for w in toks): fl[i] = "short_oov_near_run"
    return fl
def repair_text(D, t):
    """(text, stats): broken-font lines decoded with the font tables or removed. In a text with a hard broken-font signal
    (U+03A2, broken function words, Cyrillic inside Greek) every line that is not all lexicon words is tried."""
    fl = broken_lines(t, D.flex)
    hard = any(x in ("u03a2", "broken_function_words", "cyrillic_in_greek") for x in fl)
    if not hard: return t, collections.Counter()   # no broken font: unknown words (names, glued words) are left as they are
    if hard:
        ls = t.split("\n")
        fl = [x or ("doc_has_broken_font" if WT.search(l) and D.rate(l) < 1.0 else None) for l, x in zip(ls, fl)]
    if not any(fl): return t, collections.Counter()
    t2, st = repair(D, t, fl)
    st["hard_signal"] = int(hard)
    fonts = collections.Counter({k[5:]: v for k, v in st.items() if k.startswith("font_")})
    if fonts:   # lines that read as lexicon words only can still hold rare broken-font words ('Άρκρο', a lone 'ε' for 'η'): read them
        # with each table that decoded >= 10 % of the text's decoded lines, most used first
        tot = sum(fonts.values()); ls = t2.split("\n")
        for main in [fn for fn, v in fonts.most_common() if v >= 0.1 * tot]:
            for i, l in enumerate(ls):
                l2, n = D.override(l, main)
                if n: ls[i] = l2; st["words_overridden_main_table"] += n
        t2 = "\n".join(ls)
        # an output word unknown to the lexicon whose κ read as θ is a frequent word ('Άρκρο' for Άρθρο) is the θ word
        def _kth(m):
            w = m.group(0); w2 = w.replace("κ", "θ")
            if D.freq(w) <= 2 and D.freq(w2) >= 1000: st["kappa_to_theta"] += 1; return w2
            return w
        t2 = re.sub(r"[" + _GL + r"]*κ[" + _GL + r"]*", _kth, t2)
        if fonts.get("A", 0) >= 0.1 * tot:
            # table A reads a shown 'ε' as ε or η and a shown 'π' as π or υ; a lone 'ε' that is no enumerator ('ε)', 'ε.', 'ε΄') is the
            # article 'η', and a word ending in '-οπ' (no Greek word does) is a genitive in '-ου' (surnames the lexicon does not know)
            t2, n1 = _LONE_E.subn("η", t2)
            t2, n2 = _OP_END.subn(lambda m: m.group(1) + "ου", t2)
            st["lone_e_to_eta"] += n1; st["final_op_to_ou"] += n2
    return t2, st


_GL = "\u0370-\u03ff\u1f00-\u1fff"
_LONE_E = re.compile(r"(?<![\w.(])ε(?![\w).΄'’:])")
_OP_END = re.compile(r"(?<![" + _GL + r"])([" + _GL + r"]+)οπ(?![" + _GL + r"])")


# residue of a broken-font decode: words ending in '-οπ', a lone 'ε' between two Greek words (the article η; letter-spaced text such as
# 'Σ ε λ ί δ α' does not count), 'θ.θ.' (for κ.κ.) and a final sigma inside a word
_G = "[" + _GL + "]"
RESIDUE = {"op_end": re.compile(r"(?<!" + _G + ")" + _G + r"+οπ(?!" + _G + ")"),
           "lone_e": re.compile(r"(?<=" + _G + "{2} )ε(?= " + _G + "{2})"),
           "thth": re.compile(r"θ\.\s?θ\."),
           "mid_s": re.compile(r"ς[α-ωά-ώϊϋΐΰ]")}


_REAL_SHORT = set("η ο οι το τα τη να σε με ως θα ή δε αν ας εκ εν μη τι κ π ν ι α β γ δ ε".split())
_GTOK = re.compile(_G + "+")


def _letter_spaced(t, i):
    """True when the text around position i is letter-spaced ('τοπ οθέ τησ ης', 'κα ι λ ή ξης'): >= 30 % of its Greek tokens are
    1-2-letter fragments that are no Greek words. Residue tokens there are spacing fragments, not broken-font output."""
    w = _GTOK.findall(t[max(0, i - 60):i + 60])
    return len(w) >= 5 and sum(1 for x in w if len(x) <= 2 and x.lower() not in _REAL_SHORT) >= 0.3 * len(w)


def residue(t):
    """(count, per-10k Greek words, by kind) of broken-font residue tokens (tokens inside letter-spaced text are not counted)."""
    by = {k: sum(1 for m in r.finditer(t) if not _letter_spaced(t, m.start())) for k, r in RESIDUE.items()}
    n = sum(by.values()); w = len(re.findall(_G + "{2,}", t))
    return n, round(n / max(1, w) * 1e4, 1), by


# 'Άρκρο' / 'άρκρα' (broken-font Άρθρο / άρθρα) is no Greek word; it is also left in texts with too few broken lines to be decoded
ARKRO = re.compile(r"(?<![" + _GL + r"])([ΆάΑα])ρκρ")


def fix_arkro(t):
    return ARKRO.subn(r"\1ρθρ", t)
