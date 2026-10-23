#!/usr/bin/env python3
"""Column-aware text extraction for law PDFs with marginal notes (Randtitel), e.g. Stadt Zürich AS.
pdftotext -layout keeps columns; per page we find the main text column indent and move margin notes
(left margin on even pages, right margin on odd pages) onto their own line *before* the body line,
so 'Art. N' headings become line-initial. Also repairs fonts with a +29 code offset (glyph-shift garbage,
e.g. 'QXW]EDU\\x03JHPDFKW' -> 'nutzbar gemacht'). No OCR."""
import collections, re, subprocess, tempfile

SHIFT_LIG = {"ġ": "fl", "Ġ": "fi", "Ã": "ä"}
CTL = re.compile(r"[\x01-\x08\x0b-\x1f]")

def _dec(seg):
    return "".join(SHIFT_LIG.get(c) or (chr(ord(c) + 29) if ord(c) < 0x62 else c) for c in seg)

def _shift_fix(line):
    """Fonts with a +29 code offset ('QXW]EDU\x03JHPDFKW' -> 'nutzbar gemacht'). Decoded per column segment (runs separated
    by 2+ spaces), so normal-font columns on the same line stay untouched; ligature glyphs ġ/Ġ = fl/fi, Ã = ä."""
    shifted = lambda p: CTL.search(p) or (re.search("[ġĠ]", p) and sum(c.islower() for c in p) <= 1)
    if not shifted(line) and not re.search("[ġĠ]", line): return line
    score = lambda s: len(re.findall(r"(en|er|ch|ei|ie|un|de|te|ge|st)", s.lower()))
    out = []
    for p in re.split(r"( {2,})", line):
        if shifted(p):
            d = _dec(p)
            p = d if score(d) >= score(p) else p
        out.append(p)
    return "".join(out)

def _tok_fix(line):
    """Tokens still holding control chars after the segment fix: decode per token; tokens that still are not text
    (plan labels drawn with symbol fonts) are dropped."""
    if not CTL.search(line): return line
    out = []
    for tok in line.split(" "):
        if CTL.search(tok):
            dec = _dec(tok)
            if sum(ch.isalpha() for ch in dec) >= 0.6 * len(dec) and not CTL.search(dec): out.append(dec)
            continue
        out.append(tok)
    return " ".join(out).rstrip()

def layout_text(pdf_path):
    out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", pdf_path, "-"], capture_output=True, timeout=300).stdout.decode("utf-8", "ignore")
    pages = out.split("\f"); res = []
    for pg in pages:
        lines = [_shift_fix(l.rstrip()) for l in pg.splitlines()]
        ind = collections.Counter(len(l) - len(l.lstrip()) for l in lines if len(l.strip()) >= 25)
        main = ind.most_common(1)[0][0] if ind else 0
        for l in lines:
            if not l.strip(): res.append(""); continue
            left, body = l[:main], l[main:]
            margin = []
            # a heading in the main column with a margin note glued on by a single space ('Veröffentlichung Art. 14 ...')
            hm = re.compile(r"(?:Art\.|§)\s?\d").search(l, max(0, main - 4), main + 4) if main else None
            if hm and l[:hm.start()].strip() and (len(l) - len(l.lstrip())) < hm.start():
                res.append(l[:hm.start()].strip()); l = l[hm.start():]; left, body = "", l
            if left.strip() and (len(l) - len(l.lstrip())) < main:
                # left margin note only if separated from body by >=2 spaces at the column boundary
                m = re.match(r"^(.*?\S)\s{2,}(\S.*)$", l)
                if m and len(m.group(1)) <= main + 2:
                    margin.append(m.group(1).strip()); body = m.group(2)
                else:
                    body = l.strip()
            m = re.match(r"^(.*?\S)\s{6,}(\S[^\n]{0,40})$", body)
            if m and len(m.group(1)) >= 30:
                margin.append(m.group(2).strip()); body = m.group(1)
            for mg in margin: res.append(mg)
            res.append(body.strip())
        res.append("")
    # second pass: a margin note left glued to a heading by one space ('Veröffentlichung Art. 14 Dieses ...',
    # 'b. personal- Art. 5 1 ...'); references inside sentences ('gemäss Art. 6', 'sowie Art. 44') are left alone
    FUNC = r"(?:^|\s)(?:gemäss|gemäß|gem\.|nach|laut|vgl\.|i\.\s?S\.\s?v\.|sowie|Sinne von|auf|Abs\.\s?\d+|lit\.\s?\w|Ziff\.\s?\d+|\d|,)"
    res2 = []
    for l in res:
        m = re.match(r"^(\S.{0,38}?\S)\s+((?:Art\.|§)\s?\d+(?:bis|ter|quater|quinquies|[a-z])?\d*(?:\s+\d(?:\s|$)|\s+[A-ZÄÖÜ]).*)$", l)
        if m and (re.match(r"^[A-ZÄÖÜ]", m.group(1)) and not re.search(FUNC + r"$", m.group(1)) and len(m.group(1).split()) <= 4
                  and not m.group(1).endswith((".", ":", ";")) or re.match(r"^([a-z]|\d{1,2})\.\s", m.group(1))):
            res2 += [m.group(1), m.group(2)]
        else: res2.append(l)
    t = "\n".join(_tok_fix(l.lstrip("\xad")) for l in res2)
    t = re.sub(r"[ \t]+", " ", t); t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()
