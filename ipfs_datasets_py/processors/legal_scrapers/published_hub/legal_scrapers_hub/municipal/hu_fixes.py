"""Hungarian local decrees (or.njt.hu pages from Common Crawl): heading parse, issuer -> KSH code, text, § split, quality checks."""
import re, unicodedata, json, collections
ROM = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12}
# '<issuer> Képviselő-testületének 12/2023. (XI. 28.) önkormányzati rendelete' / '… Közgyűlésének …'
HEAD = re.compile(r"^(?P<iss>.+?)\s+(?i:(?P<org>képviselő\s*-?\s*testület(?:ének|e)|közgyűlés(?:ének|e)|testület(?:ének|e)|polgármester(?:ének|e)))\s+"
                  r"(?P<no>\d{1,4})\s*/\s*(?P<y>(?:19|20)\d\d)\.?\s*\(\s*(?P<m>[IVX]{1,4})\s*\.\s*(?P<d>\d{1,2})\s*\.{0,2}\s*\)\s*(?:számú\s+)?"
                  r"(?:önkormányzati\s+)?rendelete\b", re.S | re.I)
COUNTY = {"Baranya": "02", "Bács-Kiskun": "03", "Békés": "04", "Borsod-Abaúj-Zemplén": "05", "Csongrád-Csanád": "06", "Csongrád": "06", "Fejér": "07",
          "Győr-Moson-Sopron": "08", "Hajdú-Bihar": "09", "Heves": "10", "Komárom-Esztergom": "11", "Nógrád": "12", "Pest": "13", "Somogy": "14",
          "Szabolcs-Szatmár-Bereg": "15", "Jász-Nagykun-Szolnok": "16", "Tolna": "17", "Vas": "18", "Veszprém": "19", "Zala": "20"}
def parse_head(h1):
    h1 = re.sub(r"\s+", " ", h1).strip()
    m = HEAD.match(h1)
    if not m: return None
    import datetime
    try: d = datetime.date(int(m.group("y")), ROM[m.group("m").upper()], int(m.group("d"))).isoformat()
    except (KeyError, ValueError): d = None
    return dict(issuer=m.group("iss").strip(" ,"), organ="mayor" if m.group("org").lower().startswith("polg") else "council", number=f"{int(m.group('no'))}/{m.group('y')}", year=m.group("y"), date=d)
LOOSE_ISS = re.compile(r"^(?P<iss>.{3,120}?)\s+(?:Önkormányzat(?:a|ának)?\s+)?(?:Képviselő-?\s*testület(?:e|ének)?|Közgyűlés(?:e|ének)?|[Pp]olgármester(?:e|ének)?)\b", re.I)
def parse_head_loose(h1, url_year, url_no):
    """a heading the strict pattern misses ('… 16/2004. (2005. I. 30.) önkormányzati rendelete', '6/2013 (08.29.)', or only the subject):
    number and year from the ELI URL; issuer from the heading when it names one; promulgation date only when the heading gives one"""
    import datetime
    h1 = re.sub(r"\s+", " ", h1 or "").strip()
    m = LOOSE_ISS.match(h1); iss = m.group("iss").strip(" ,") if m else None
    if iss and not re.search(r"[A-ZÁÉÍÓÖŐÚÜŰ]", iss[:1]): iss = None
    # the heading's own decree number ('8/2005.(X.01.)', '5/1997.(III.24.)', '16/2004. (2005. I. 30.)') beats the URL (or.njt.hu's registry number)
    hn = re.search(r"(?<![\d/])(?P<no>\d{1,4})\s*/\s*(?P<y>(?:19|20)\d\d)\b(?!\s*/)", h1)
    num_basis = "url"
    if hn and (1990 <= int(hn.group("y")) <= 2030):
        url_no, url_year, num_basis = hn.group("no"), hn.group("y"), "heading"
    d = None
    for pat in (r"\((?P<y>\d{4})\.\s*(?P<m>[IVX]{1,4})\.\s*(?P<d>\d{1,2})\.?\s*\)", r"\((?P<m>[IVX]{1,4})\.\s*(?P<d>\d{1,2})\.{0,2}\s*\)",
                r"\((?P<mm>\d{1,2})\.\s*(?P<d>\d{1,2})\.?\s*\)"):
        q = re.search(pat, h1)
        if not q: continue
        g = q.groupdict(); yy = int(g.get("y") or url_year)
        mo = ROM.get((g.get("m") or "").upper()) if g.get("m") else int(g["mm"])
        try: d = datetime.date(yy, mo, int(g["d"])).isoformat()
        except (TypeError, ValueError): d = None
        if d and not (int(url_year) <= yy <= int(url_year) + 1): d = None
        if d: break
    organ = "mayor" if re.search(r"(?i)polgármester", h1) and not re.search(r"(?i)képviselő|közgyűlés", h1) else "council"
    return dict(issuer=iss, organ=organ, number=f"{int(url_no)}/{url_year}", year=str(url_year), date=d, loose=True, number_basis=num_basis)
def body_date(text, number, year):
    """promulgation date for a heading without one: '<number>. (<month>. <day>.)' in the opening text, else the first '(<month>. <day>.)'
    of the opening 400 characters, else a numeric 'YYYY.MM.DD.' date of the decree year printed under the title (opening 600 characters)."""
    import datetime
    t = re.sub(r"\s+", " ", text[:3000]); no = number.split("/")[0]
    pats = [rf"\b{no}\s*/\s*{year}\.?\s*\(\s*(?P<m>[IVX]{{1,4}})\s*\.\s*(?P<d>\d{{1,2}})\s*\.?\s*\)", r"\(\s*(?P<m>[IVX]{1,4})\s*\.\s*(?P<d>\d{1,2})\s*\.?\s*\)"]
    for k, pat in enumerate(pats):
        q = re.search(pat, t if k == 0 else t[:400])
        if q and q.group("m").upper() in ROM:
            try: return datetime.date(int(year), ROM[q.group("m").upper()], int(q.group("d"))).isoformat(), ("number+date in text" if k == 0 else "first (month. day.) in the opening text")
            except ValueError: pass
    for q in re.finditer(rf"\b{year}\s*\.\s*(\d{{2}})\s*\.\s*(\d{{2}})\s*\.", t[:600]):
        try: return datetime.date(int(year), int(q.group(1)), int(q.group(2))).isoformat(), "numeric date printed under the title"
        except ValueError: pass
    return None, None
SUFFIX = re.compile(r"\s+(?:(?:Megyei\s+Jogú\s+|Megyei\s+jogú\s+)?Város(?:i)?|Nagyközség(?:i)?|Község(?:i)?|Községek?|Városi|Közös)?\s*"
                    r"(?:Önkormányzat(?:a|ának|ai)?|önkormányzat(?:a|ának)?)\s*$")
class Issuers:
    """issuer name -> (KSH code, kind, settlement / county name, county). Settlements: Wikidata P939 (KSH 5-digit code, unique names);
    Budapest districts by roman numeral; county assemblies -> KSH county code; the Fővárosi Közgyűlés / Budapest Főváros Önkormányzata -> Budapest."""
    def __init__(self, wd_ksh, wd_county):
        self.by = {}; self.dist = {}
        for x in wd_ksh:
            m = re.match(r"Budapest ([IVXL]+)\. kerülete$", x["name"])
            if m: self.dist[m.group(1)] = x["ksh"]
            else: self.by.setdefault(self.key(x["name"]), (x["ksh"], x["name"]))
        self.county = {k: v.replace(" megye", " vármegye") for k, v in wd_county.items()}
    @staticmethod
    def key(s): return unicodedata.normalize("NFC", s).lower().replace("–", "-").strip()
    def resolve(self, iss):
        s = re.sub(r"\s+", " ", iss).strip()
        m = re.search(r"Budapest\s+Főváros\s+([IVXL]+)\.?\s*[Kk]erület", s) or re.search(r"Budapest\s+([IVXL]+)\.\s*[Kk]erület", s)
        if m and m.group(1) in self.dist: return self.dist[m.group(1)], "budapest_district", f"Budapest {m.group(1)}. kerület", "Budapest"
        # issuer type first: the capital, then county assemblies ('<county> Megye(i) [Önkormányzat|Közgyűlés]', the organ word may already be
        # cut off by the heading pattern), and only then settlements. 'Megyei Jogú Város' cities are settlements.
        if re.search(r"(?i)^(Fővárosi\s+(Közgyűlés|Önkormányzat)\w*|Budapest\s+Főváros(?:i)?(?:\s+(?:Önkormányzat\w*|Közgyűlés\w*))?\s*$)", s):
            return "13578", "capital", "Budapest", "Budapest"
        m = re.match(r"^(?P<c>[A-ZÁÉÍÓÖŐÚÜŰ][\wáéíóöőúüű\-]+)\s+(?:[Vv]ár)?[Mm]egye(?:i)?(?:\s+(?:Önkormányzat\w*|Közgyűlés\w*))*\s*$", s)
        if m and m.group("c") in COUNTY: return COUNTY[m.group("c")], "county", f"{m.group('c')} vármegye", f"{m.group('c')} vármegye"
        n = SUFFIX.sub("", s).strip(" ,")
        for cand in (n, re.sub(r"\s+(Község|Nagyközség|Város)$", "", n), n.split(" ")[0] if " " in n and not "-" in n else None):
            if cand and self.key(cand) in self.by:
                k, name = self.by[self.key(cand)]; return k, "settlement", name, self.county.get(k)
        return None
# ---------------------------------------------------------------- text
def _clean_line(x):
    x = unicodedata.normalize("NFC", x).replace("\u00a0", " ").replace("\u2005", " ").replace("\u2002", " ").replace("\u2003", " ").replace("\u2009", " ")
    x = re.sub(r"[\u200b-\u200d\ufeff\u00ad]", "", x)
    return re.sub(r"[ \t]+", " ", x).strip()
def _table_text(t):
    rows = []
    for tr in t.find_all("tr"):
        cells = [_clean_line(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells]
        if any(cells): rows.append(" | ".join(cells))
    return "\n".join(rows)
def njt_blocks(content_html):
    """[(jh_id, kind, text)] in order from the 2023- layout. Footnote markers (sup.fnSup / a footnote link) and the footnote list are
    dropped; tables become ' | ' rows. kind: preamble / section / annex / appendix / heading / quoted / body."""
    from bs4 import BeautifulSoup
    s = BeautifulSoup(content_html, "html.parser"); j = s.select_one(".jogszabaly") or s
    if not j.find("span", class_="jhId"):
        hd = j.select_one("div.x2h-htmlDiv")                       # an unstructured page ('alaprendelet' HTML): plain text, split by '§' lines
        return ("html", str(hd) if hd else None), []
    links = [a.get("href") for a in j.select("a.resource_link") if a.get("href")]
    for x in j.select("sup.fnSup, .fnSup, span.fnSup"): x.decompose()
    foot = []
    out = []; cur = None; prev_top = None; seen_top = set()
    for x in j.find_all(recursive=False):
        cl = " ".join(x.get("class") or [])
        if x.name == "span" and "jhId" in cl: cur = x.get("id") or cur; continue
        if x.get("id") == "scrollTitle" or "jogszabalyMainTitle" in cl or "jogszabalySubtitle" in cl or cl.strip() == "hataly": continue
        if "footnote" in cl: foot.append(_clean_line(x.get_text(" ", strip=True))); continue
        if x.name == "table" or "tablazat" in cl:
            tb = x if x.name == "table" else (x.find("table") or x); t = _table_text(tb) if tb.name == "table" else _clean_line(x.get_text(" ", strip=True))
        else:
            for br in x.find_all("br"): br.replace_with("\n")
            t = "\n".join(_clean_line(l) for l in x.get_text("").split("\n")); t = re.sub(r"\n{2,}", "\n", t).strip()
        if not t: continue
        top = (cur or "").split("@")[0]
        # a § starts at the first non-empty block of a new SZ<n> id (the szakasz div itself is empty; its text is in SZ<n>@BE<k>)
        if "idezet" in cl: kind = "quoted"
        elif top == "PR" or "preambulum" in cl: kind = "preamble"
        elif re.match(r"SZ", top) and top not in seen_top: kind = "section"
        elif re.match(r"ME", top) and top not in seen_top: kind = "annex"
        elif re.match(r"FU", top) and top not in seen_top: kind = "appendix"
        elif re.match(r"(TA|AC|FE|RE)", top) and ("tagolo" in cl or "alcim" in cl or "fejezet" in cl or "resz" in cl or "Cim" in cl): kind = "heading"
        else: kind = "body"
        out.append((cur, kind, t))
        if kind != "quoted": prev_top = top; seen_top.add(top)
    return out, dict(footnotes=foot, attachment_links=links)
def orr_text(content_html, footnotes_html=None):
    from bs4 import BeautifulSoup
    s = BeautifulSoup(content_html, "html.parser")
    for x in s.select("sup, .fnSup"): 
        if re.fullmatch(r"\s*\d{1,3}\s*", x.get_text()): x.decompose()
    for t in s.find_all("table"): t.replace_with(s.new_string("\n" + _table_text(t) + "\n"))
    for br in s.find_all("br"): br.replace_with("\n")
    for p in s.find_all(["p", "div", "h1", "h2", "h3", "h4", "li"]): p.insert_after(s.new_string("\n"))
    t = "\n".join(_clean_line(l) for l in s.get_text("").split("\n"))
    foot = []
    if footnotes_html:
        f = BeautifulSoup(footnotes_html, "html.parser"); foot = [_clean_line(x.get_text(" ", strip=True)) for x in f.find_all(["p", "div", "li"]) if x.get_text(strip=True)]
    return re.sub(r"\n{2,}", "\n", t).strip(), foot
SEC = re.compile(r"^(?P<n>\d{1,3}(?:/[A-Za-z])?)\s?\.\s*§")
ANNEX = re.compile(r"^(?P<n>\d{1,3}(?:[./][a-zA-Z0-9]{1,2})?)\.?\s*(?:számú\s+)?(?P<k>melléklet|függelék)\b", re.I)
def _lab(s): return re.sub(r"[^0-9a-z/]+", "", s.lower()).replace("/", "-").strip("-")
def records_njt(blocks):
    """[(label, heading, text)]: '0' preamble (and anything before the first §); one record per § (label '3', '3-a'); annexes 'melleklet-2',
    appendices 'fuggelek-1'. Headings (chapter / subtitle) start the record of the § that follows them; quoted (amending) text stays in its §."""
    recs = []; pend = []
    def new(lab, head):
        recs.append([lab, head, []])
    for jid, kind, t in blocks:
        if kind == "preamble" and not recs: new("0", "", ); recs[-1][2].append(t); continue
        if kind == "heading": pend.append(t); continue
        if kind in ("section", "annex", "appendix"):
            first = t.split("\n")[0]
            if kind == "section":
                m = SEC.match(first); lab = _lab(m.group("n")) if m else _lab((jid or "").split("@")[0][2:]) or f"s{len(recs)}"
            else:
                m = ANNEX.match(first); lab = ("melleklet-" if kind == "annex" else "fuggelek-") + (_lab(m.group("n")) if m else str(len(recs)))
            new(lab, (pend[-1] if pend else "") if kind == "section" else first[:200])
            if kind == "section" and not recs[-1][1]: recs[-1][1] = first[:200]
            recs[-1][2].extend(pend + [t]); pend = []; continue
        if not recs: new("0", "")
        recs[-1][2].extend(pend + [t]); pend = []
    if pend:
        if not recs: new("0", "")
        recs[-1][2].extend(pend)
    # an annex given only as a PDF attachment ('1. melléklet' and nothing else): its label goes to the end of the record before it
    k = len(recs) - 1
    while k > 0:
        if recs[k][0].startswith(("melleklet", "fuggelek")) and len("\n".join(recs[k][2])) <= 60:
            recs[k - 1][2].extend(recs[k][2]); recs[k - 1].append(None); del recs[k]
        k -= 1
    # a 'section' block that is quoted amending text: or.njt.hu sometimes marks the replacement § of the amended decree as its own § (SZ id).
    # It follows a record ending with an amending formula ('… a következő rendelkezés lép:') and breaks the § sequence: it goes back into that record.
    k = 1; mx = 0
    while k < len(recs):
        n_ = _num(recs[k][0]); pv = "\n".join(recs[k - 1][2]).rstrip().split("\n")[-1] if recs[k - 1][2] else ""
        pn = _num(recs[k - 1][0])
        if pn is not None: mx = max(mx, pn)
        if n_ is not None and mx and n_ != mx + 1 and AMEND_INTRO.search(pv):
            recs[k - 1][2].extend(recs[k][2]); del recs[k]; SPLIT_STATS["njt_quoted_section_merged"] += 1; continue
        k += 1
    out, seen = [], collections.Counter()
    for lab, head, parts, *_ in recs:
        seen[lab] += 1; lab2 = lab if seen[lab] == 1 else f"{lab}#{seen[lab]}"
        out.append((lab2, head, "\n".join(parts).strip()))
    return [r for r in out if r[2]]
def records_text(t):
    """older layout: split the text at '3. §' lines and 'N. melléklet' lines; 1-2 short heading lines just before a § go with it."""
    lines = t.split("\n"); starts = []; last = 0
    for i, l in enumerate(lines):
        m = SEC.match(l)
        if m:
            v = int(re.match(r"\d+", m.group("n")).group(0))
            starts.append((i, _lab(m.group("n")), "section")); continue
        m = ANNEX.match(l)
        if m and starts and len(l) < 200: starts.append((i, ("melleklet-" if m.group("k").lower().startswith("m") else "fuggelek-") + _lab(m.group("n")), "annex"))
    if not [s for s in starts if s[2] == "section"]: return [("0", "", t)]
    adj = []
    for i, lab, k in starts:
        j = i
        if k == "section":
            for q in (i - 1, i - 2):
                if q > (adj[-1][0] if adj else 0) and 0 < len(lines[q]) < 120 and not re.search(r"[.:;,]$", lines[q]) and not SEC.match(lines[q]) \
                        and not re.match(r"^\(?\d", lines[q]) and not re.match(r"^[a-z]", lines[q]): j = q
                else: break
        adj.append((j, lab, i))
    recs = []
    if adj[0][0] > 0: recs.append(("0", "", "\n".join(lines[:adj[0][0]]).strip()))
    seen = collections.Counter()
    for k, (j, lab, i) in enumerate(adj):
        e = adj[k + 1][0] if k + 1 < len(adj) else len(lines)
        seen[lab] += 1; lab2 = lab if seen[lab] == 1 else f"{lab}#{seen[lab]}"
        recs.append((lab2, lines[i][:200], "\n".join(lines[j:e]).strip()))
    return [r for r in recs if r[2]]
def bad_chars(t): return re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd\ue000-\uf8ff\x80-\x9f]", t)
# Hungarian ő/ű read as õ/û (Latin-1 fonts) — the NJT texts sometimes carry them; map to the Hungarian letters
TILDE = str.maketrans({"õ": "ő", "Õ": "Ő", "û": "ű", "Û": "Ű", "ô": "ő", "Ô": "Ő"})
# font leftovers in tables and lists: Wingdings / Symbol bullets and boxes (U+F0xx private use), and C1 bytes that are cp1252 punctuation
SYM = {"\x7f": "☐", "\x9f": "•", "\uf0b7": "•", "\uf0a7": "▪", "\uf0d8": "➢", "\uf0fc": "✓", "\uf06c": "•", "\uf06e": "▪", "\uf076": "❖", "\uf07f": "☐",
       "\uf0a8": "☐", "\uf06f": "☐", "\uf0e0": "→", "\uf0e8": "→", "\uf02d": "-", "\uf0be": "—"}
def _c1(ch):
    try: return bytes([ord(ch)]).decode("cp1252")
    except UnicodeDecodeError: return ""
SYM_STATS = collections.Counter()
FN_MARK = re.compile(r"[ \t]?\[\d{1,3}\]")
FN_STATS = collections.Counter()
def strip_fn_markers(t):
    """leftover footnote reference markers '[12]' (the footnote list itself is kept in extras.footnotes)"""
    n = len(FN_MARK.findall(t))
    if n: FN_STATS["footnote_markers_removed"] += n; t = FN_MARK.sub("", t)
    return t
def fix_letters(t):
    t = t.translate(TILDE)
    if "\u206f" in t: SYM_STATS["U+206F->☐"] += t.count("\u206f"); t = t.replace("\u206f", "☐")   # 'NOMINAL DIGIT SHAPES' used as form boxes
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", t):                       # stray C0 control bytes in the source page (e.g. U+0010 after a colon)
        SYM_STATS["C0 control removed"] += len(re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", t)); t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)
    if "\ufffd" in t:                                                        # a form box glyph already lost in the source (a run of U+FFFD on its own)
        def _box(m): SYM_STATS["U+FFFD run->☐"] += 1; return "☐"
        t = re.sub(r"(?<!\S)\ufffd+(?!\S)", _box, t)
    if re.search(r"[\x7f-\x9f\ue000-\uf8ff]", t):
        def r(m):
            ch = m.group(0); v = SYM.get(ch)
            if v is None: v = _c1(ch) if ch <= "\x9f" else "•"          # an unknown Symbol-font glyph: a bullet
            SYM_STATS[f"U+{ord(ch):04X}->{v or 'removed'}"] += 1; return v
        t = re.sub(r"[\x7f-\x9f\ue000-\uf8ff]", r, t)
    return t

# ---------------------------------------------------------------- second pass: headings the first split missed
SEC_ANY = re.compile(r"^(?P<n>\d{1,3})\s?\.\s*§(?:\s*[.,])?(?=\s|\(|$|[A-ZÁÉÍÓÖŐÚÜŰ])")
# headings without the dot ('24 §', '4§.', '4§'): only when a new sentence follows ('(1) A …', 'A …', end of line), so that a wrapped
# reference ('… a rendelet' / '24 § (1) bekezdése') is not taken; and '13.' on one line with '§' on the next
SEC_NODOT = re.compile(r"^(?P<n>\d{1,3})\s?§\.?(?=\s*(?:\(\s?\d{1,2}\s?\)\s*)?(?:[A-ZÁÉÍÓÖŐÚÜŰ„\"]|$))")
SEC_NUM_LINE = re.compile(r"^(?P<n>\d{1,3})\s?\.?$")
def _sec_head(lines, i):
    l = lines[i]; m = SEC_ANY.match(l)
    if m: return m, "dot"
    m = SEC_NODOT.match(l)
    if m: return m, "nodot"
    m = SEC_NUM_LINE.match(l)
    if m and i + 1 < len(lines) and re.match(r"^§\.?(?:\s|\(|$)", lines[i + 1]): return m, "split_line"
    return None, None
OWN_SEC = re.compile(r"^\s*(?:\(1\)\s*)?(?:Ez a rendelet|E rendelet|A Rendelet|A rendelet|Hatályát veszti|Hatályba|Záró)")
SEC_GLUED = re.compile(r"(?<=[a-záéíóöőúüű)][.;:!?])\s?(?P<n>\d{1,3})\s?\.\s*§\.?\s*(?=\(\d|[A-ZÁÉÍÓÖŐÚÜŰ])")
ANNEX_HEAD = re.compile(r"^(?P<n>\d{1,3})\s*\.\s*(?:számú\s+|sz\.\s*)?(?P<k>melléklet|függelék)(?:\s+(?:a|az)\b.{0,220})?\s*:?\s*$", re.I)
SPLIT_STATS = collections.Counter()
AMEND_INTRO = re.compile(r"(?:\blép|\bki|kiegészül|módosul|helyébe|szöveg(?:rész)?|rendelkezés)\s*:\s*$", re.I)
def _num(lab):
    m = re.fullmatch(r"(\d+)", lab or ""); return int(m.group(1)) if m else None
def resplit(recs):
    """Split records at § headings and content annexes that the first pass left inside another record: line-start '1.§', '97 . §',
    '5. §.' and '3. §' after footnote-marker removal; a '6. §' glued after a sentence end ('nyújt.6. §.(1)') starts a new line. Guards: a §
    heading must carry the next § number (sequence), annexes need ≥ 80 characters of content and a label not used yet, and nothing inside
    quoted amending text (a line opening with „ or " up to the closing ”, or the line after an amending formula '… lép:', '… egészül ki:') is split."""
    out = []; labs = {r[0] for r in recs}; last = 0
    for lab, head, text in recs:
        n0 = _num(lab)
        if n0 is not None: last = max(last, n0)
        lines = text.split("\n"); cuts = []; inq = False; prev = ""; i = 0
        while i < len(lines):
            l = lines[i]
            quoted = inq or bool(AMEND_INTRO.search(prev)) or l.startswith(("„", '"'))
            if l.startswith(("„", '"')) and "”" not in l[1:]: inq = True
            elif inq and "”" in l: inq = False
            if i > 0 and quoted and not AMEND_INTRO.search(prev):        # a quote that never closed: the decree's own closing § ends it
                m = SEC_ANY.match(l)
                if m and int(m.group("n")) == last + 1 and OWN_SEC.match(l[m.end():]): quoted = inq = False; SPLIT_STATS["quote_state_reset"] += 1
            if i > 0 and not quoted:
                m, form = _sec_head(lines, i)
                if m and int(m.group("n")) == last + 1 and str(last + 1) not in labs:
                    last += 1; cuts.append((i, str(last), l[:200], "section")); labs.add(str(last))
                    if form != "dot": SPLIT_STATS["section_heading_" + form] += 1
                else:
                    m = None
                g = SEC_GLUED.search(l, 1)
                if g and int(g.group("n")) == last + 1 and str(last + 1) not in labs and l[:g.start()].strip():
                    lines[i:i + 1] = [l[:g.start()].rstrip(), l[g.start():].lstrip()]; SPLIT_STATS["glued_section_heading_split"] += 1
                    prev = lines[i]; i += 1; continue                 # the next round starts at the glued heading
                if m: prev = l; i += 1; continue
                m = ANNEX_HEAD.match(l)
                if m and last > 0 and len(l) <= 260:
                    al = ("melleklet-" if m.group("k").lower().startswith("m") else "fuggelek-") + m.group("n")
                    if al not in labs and al not in {c[1] for c in cuts}: cuts.append((i, al, l[:200], "annex"))
            prev = l; i += 1
        # annexes: keep only those with content up to the next cut
        keep = []
        for k, c in enumerate(cuts):
            if c[3] == "annex":
                end = cuts[k + 1][0] if k + 1 < len(cuts) else len(lines)
                if len(re.sub(r"\s", "", "\n".join(lines[c[0] + 1:end]))) < 80: continue
                labs.add(c[1])
            keep.append(c)
        if not keep: out.append((lab, head, "\n".join(lines))); continue
        out.append((lab, head, "\n".join(lines[:keep[0][0]]).strip()))
        for k, c in enumerate(keep):
            end = keep[k + 1][0] if k + 1 < len(keep) else len(lines)
            out.append((c[1], c[2], "\n".join(lines[c[0]:end]).strip())); SPLIT_STATS["split_" + c[3]] += 1
    return [r for r in out if r[2]]
HOLLOW = re.compile(r"(?s)^(?:[^\n]{0,200}\n){0,3}\d{1,3}(?:/[A-Za-z])?\s?\.\s*§\.?\s*$")
def is_hollow(lab, text):
    """a § record that is only its number (and maybe a sub-title): the provision was repealed or spent and or.njt.hu shows the number only"""
    return bool(re.fullmatch(r"\d+(?:-[a-z])?", lab or "")) and bool(HOLLOW.match(text.strip()))
