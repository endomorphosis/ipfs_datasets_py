#!/usr/bin/env python3
"""Slovak VZN helpers: exclusions, dates, status, article splitting (§ / Článok / Čl. with arabic or roman numbers)."""
import re, collections, unicodedata

MONTHS = {m: i + 1 for i, m in enumerate("januára februára marca apríla mája júna júla augusta septembra októbra novembra decembra".split())}
MONTHS.update({m: i + 1 for i, m in enumerate("január február marec apríl máj jún júl august september október november december".split())})   # nominative (signature blocks)
MONTHS = dict(sorted(MONTHS.items(), key=lambda kv: -len(kv[0])))           # longest alternative first in DATE
DATE = r"(\d{1,2})\s*\.\s*(\d{1,2}|" + "|".join(MONTHS) + r")\s*\.?\s*((?:19|20)\d{2})"
def iso(d, m, y):
    m = MONTHS.get(m.lower(), None) if not m.isdigit() else int(m)
    try:
        d, y = int(d), int(y)
        if not (1 <= m <= 12 and 1 <= d <= 31 and 1990 <= y <= 2030): return None
        return f"{y:04d}-{m:02d}-{d:02d}"
    except (TypeError, ValueError): return None

# ---------- exclusions ----------
NON_NORMATIVE = re.compile(r"(?i)\b(návrh|navrh|dôvodová správa|pripomienk|oznámenie o|zápisnica|informácia o|stanovisko|"
                           r"vyhodnotenie|dôvodov)\b")
CONTRACT = re.compile(r"(?i)\b(zmluv[auy]?|dohod[auy]|memorand|zásady hospodárenia|štatút\b|rokovací poriadok|organizačný poriadok)")
def exclusion(d):
    t = d["title"]
    if re.match(r"(?i)\s*návrh|\s*navrh", t) or re.search(r"(?i)\bnávrh (všeobecne|vzn)", t): return "proposal"
    if CONTRACT.search(t) and not re.search(r"(?i)nariadeni|vzn", t): return "contract_or_internal_rules"
    if re.search(r"(?i)dôvodová správa|pripomienk|zápisnica|oznámenie\b|vyhodnotenie pripomienok", t): return "non_normative"
    return None

# ---------- dates ----------
EFFX = r"(?i)(?:nadob(?:úda|udne|udlo|údajú|udol|udnú)\s+účinnos[tť]\w*|účinnos[tť]\s+nadob(?:úda|udne|udlo|údajú|udol|udnú))\s+(?:dňom|dňa|od|dňom\s+jeho\s+vyhlásenia,?\s*t\.\s*j\.)?\s*:?\s*" + DATE
# 'nadobúda účinnosť 15-tym dňom od vyvesenia na úradnej tabuli mesta, t. j. dňom 25.12.2025'
EFFTJ = r"(?i)nadob(?:úda|udne|udlo|údajú|udol)\s+účinnos[tť]\w*[^.;]{0,160}?t\.\s*j\.\s*(?:dňom|dňa|od)?\s*" + DATE
REL = r"(?i)nadob(?:úda|udne)\s+účinnos[tť]\w*\s+(\d{1,2})\s*\.?\s*(?:-?t?ym|-?ym)?\s*dňom\s+od\s+(?:jeho\s+)?vyvesenia"
def text_posting(text):
    """Signature block: 'Schválené Mestským zastupiteľstvom ... dňa: 09.12.2025', 'Vyvesené dňa: 13.02.2026', and a relative
    clause 'nadobúda účinnosť 15. dňom od vyvesenia' -> (approved, posted, computed effective = posted + N days)."""
    tail = text[-4000:]
    a = re.search(r"(?i)Schválen[éé]\s+(?:Mestsk\w+\s+zastupiteľstv\w+|MZ|uznesením)[^\n]{0,80}?(?:dňa|dna)\s*:?\s*" + DATE, tail)
    v = re.search(r"(?i)Vyvesen[éeý]\s+(?:na\s+úradnej\s+tabuli\s+)?(?:dňa|dna)?\s*:?\s*" + DATE, tail)
    if not a:     # signing place/date 'V Trnave dňa 8. septembra 1998' as the approval-date fallback
        a = re.search(r"(?m)^[ \t]*V\s+[A-ZŽŠČ]\w+(?:\s+[a-zžšč]\w+)?\s*,?\s*(?:dňa|dna)?\s*:?\s*" + DATE, tail)
    r = re.search(REL, text)
    ap = iso(*a.groups()) if a else None; po = iso(*v.groups()) if v else None; eff = None
    if po and r:
        import datetime as _dt
        eff = (_dt.date.fromisoformat(po) + _dt.timedelta(days=int(r.group(1)))).isoformat()
    return ap, po, eff

def text_effective(text):
    """Header 'účinné od <date>' or the act's own Účinnosť / Záverečné ustanovenia clause ('nadobúda účinnosť 1. januára 2026');
    latest wins (consolidated texts list the dates of each amendment)."""
    own = [iso(*m.groups()) for m in re.finditer(r"(?i)(?:účinn[éáý]\w*\s+od|účinnosťou\s+od|účinnos[tť]\s*:)\s*:?\s*" + DATE, text[:1500])]
    sec = list(re.finditer(r"(?im)^[ \t]*(?:§\s*\d+[a-z]?|" + CL + r"\s*[\dIVXL]+)\s*\n?\s*(?:Účinnos[tť]|Záverečné\s+(?:a\s+prechodné\s+)?ustanoveni[ae]|Zrušovacie\s+a\s+záverečné)", text))
    if sec:
        s = text[sec[-1].start(): sec[-1].start() + 3000]
        own += [iso(*m.groups()) for m in re.finditer(EFFX, s)]
        own += [iso(*m.groups()) for m in re.finditer(EFFTJ, s)]
    own = [v for v in own if v]
    if own: return max(own), "text_own_clause"
    allx = [iso(*m.groups()) for m in re.finditer(EFFX, text)] + [iso(*m.groups()) for m in re.finditer(EFFTJ, text)]
    allx = [v for v in allx if v]
    if allx: return max(allx), "text"
    # publisher-OCR digits in the clause ('dňom l.l.l998', '1.1O.1993') or a day without its dot ('dňom 15 apríla 1994')
    ox = []
    for m in re.finditer(r"(?i)nadob\w*\s+účinnos[tť]\w*\s+(?:dňom|dňa|od)?\s*:?\s*([0-9lIO]{1,2})\s*\.?\s*([0-9lIO]{1,2}|" + "|".join(MONTHS) + r")\s*\.?\s*([0-9lIO]{4})", text):
        tr = lambda x: x.translate(str.maketrans("lIO", "110"))
        v = iso(tr(m.group(1)), m.group(2) if m.group(2).lower() in MONTHS else tr(m.group(2)), tr(m.group(3)))
        if v and re.fullmatch(r"(19|20)\d\d", tr(m.group(3))): ox.append(v)
    if ox: return max(ox), "text_ocr_digits"
    return None, None

def norm_date(s):
    if not s: return None
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(s).strip()[:10].rstrip("T"))
    if not m or not (1990 <= int(m.group(1)) <= 2030): return None       # register typos such as '0206-01-01'
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

# ---------- articles ----------
ROMAN = {v: i + 1 for i, v in enumerate("I II III IV V VI VII VIII IX X XI XII XIII XIV XV XVI XVII XVIII XIX XX XXI XXII XXIII XXIV XXV XXVI XXVII XXVIII XXIX XXX".split())}
# article markers incl. publisher-OCR forms: 'ČI.'/'CI.'/'či.'/'Č1.' (I / i / 1 for l, also 'Čl .'), 'ČL', Czech 'Článek', unaccented 'Clanok'
CL = r"(?:[ČC][lI1][ \t]?\.|[čc][li1][ \t]?\.|[ČC]L[ \t]?\.|[ČCčc]l[aá]n[oe]k|[ČC]L[AÁ]N[OE]K|Čl|čl|ČL|Cl)"
PARTPFX = r"(?:(?:ČASŤ|Časť|ČAST|CAST|Cast|Čast)[ \t]+[IVX]{1,5}\.?[ \t]+)?"     # 'Časť II. Čl. 2 Základné ustanovenia' on one line
CAND = re.compile(r"(?m)^[ \t]*" + PARTPFX + r"(§|" + CL + r")[ \t]*(\d{1,3}|[IVXL]{1,6})([a-z])?(?:[ \t]*[-–][ \t]*(\d{1,3})(?![\d.]))?[ \t]*[.:]?[ \t]*(?=\n|[A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ(\[]|[-–] *(?:vypusten|zrušen|vypúšťa)|$)([^\n]{0,200})")
# a roman numeral alone on a line, the title on the next line ('I.' / 'Predmet dane')
ROMLINE = re.compile(r"(?m)^[ \t]*([IVX]{1,5})\.[ \t]*\n(?:[ \t]*\n)?[ \t]*((?:\d{1,2}[.)][ \t]+)?[A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ][^\n]{1,150})$")   # title, or directly point '1. …' 
CASTLINE = re.compile(r"(?m)^[ \t]*(?:ČASŤ|Časť|ČAST|CAST|Cast|Čast)[ \t]+([IVX]{1,5}|\d{1,2})\.?[ \t]*(?=\n|[A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ]|$)([^\n]{0,150})")
REFW = r"^(ods\.|odsek|písm\.|zákona|zák\.|a\s|až|,|bod|VZN|tohto|nariadenia|sa\s|znie|Zb\.|Z\.\s?z\.)"

def heading_run(text):
    """Longest increasing run (steps 1..5) of heading candidates of one family, and the lines - used by the build gates."""
    fams = collections.defaultdict(list)
    for c in all_candidates(text):
        if not c[3]: fams[c[1]].append((c[2], c[5][:40]))
    best, lines = 0, []
    for vs in fams.values():
        dp = []
        for j, (v, _) in enumerate(vs): dp.append(1 + max([dp[k] for k in range(j) if vs[k][0] < v <= vs[k][0] + 5] or [0]))
        if dp and max(dp) > best: best, lines = max(dp), [x[1] for x in vs]
    return best, lines

def all_candidates(text):
    """Every line-start heading candidate: (pos, family, n, suffix, rest, raw, end). Families: '§', 'cl' (Čl./Článok + arabic),
    'cl-roman' (Čl. + roman), 'rom' (roman numeral alone on a line + title line). Used by the splitter and by the build gates."""
    cands = []
    for m in CAND.finditer(text):
        mk = "§" if m.group(1) == "§" else "cl"
        n = _num(m.group(2))
        if n is None: continue
        fam = mk + ("-roman" if not m.group(2).isdigit() else "")
        rest = m.group(5).strip()
        end = int(m.group(4)) if m.group(4) and m.group(2).isdigit() and n < int(m.group(4)) <= n + 5 else n
        if m.group(4) and end == n: continue
        if re.search(r"\.{4,}|…{2,}|\s\d{1,3}\s*$", rest): continue                     # TOC line
        if re.match(REFW, rest): continue   # reference, not a heading
        cands.append((m.start(), fam, n, m.group(3), rest, m.group(0).strip(), end))
    for m in CASTLINE.finditer(text):      # 'Časť I. Úvodné ustanovenie' / 'ČASŤ II.' as the only heading level
        n = _num(m.group(1)) if not m.group(1).isdigit() else int(m.group(1))
        if n is None or re.search(r"\.{4,}|…{2,}|\s\d{1,3}\s*$", m.group(2)) or CAND.match(text, m.start()): continue
        cands.append((m.start(), "cast", n, None, m.group(2).strip(), m.group(0).strip()[:40], n))
    for m in ROMLINE.finditer(text):
        n = ROMAN.get(m.group(1))
        if n is None or re.search(r"\.{4,}|…{2,}|\s\d{1,3}\s*$", m.group(2)): continue
        cands.append((m.start(), "rom", n, None, "", m.group(1) + ".", n))
    cands.sort(key=lambda c: c[0])
    return cands
def _num(s): return int(s) if s.isdigit() else ROMAN.get(s)

CONF = str.maketrans({"l": "1", "I": "1", "O": "0", "S": "5", "B": "8"})
def normalize_ocr_headings(text, ocr, bb=False):
    """Publisher-OCR misreads in heading lines only (we never OCR): 'Článok l' -> 'Článok 1', '$ 5' -> '§ 5'; in OCR text layers
    also '8 5' / 'S 5' / 's 5' alone on a line -> '§ 5'. Returns (text, n_changes)."""
    n = 0
    def f1(m):
        nonlocal n; tok = m.group(2)
        if tok.isdigit() or re.fullmatch(r"[IVXL]+", tok) and tok != "I": return m.group(0)
        n += 1; return m.group(1) + tok.translate(CONF) + m.group(3)
    t = re.sub(r"(?m)^([ \t]*(?:" + CL + r"|§)[ \t]*)(\d?[lOS]\d?|\dB\d?|B\d)([ \t]*[.:]?[ \t]*$)", f1, text)
    t, k = re.subn(r"(?m)^([ \t]*)\$[ \t]?(?=\d{1,3}[a-z]?\b)", r"\1§ ", t); n += k
    # dash-leader article headings ('Čl.1 -------- Úvodné ustanovenia ----', Trnava) -> 'Čl. 1 Úvodné ustanovenia'
    t, k = re.subn(r"(?m)^([ \t]*[Čč]l\.)[ \t]*(\d{1,3})[ \t]*-{3,}[ \t]*([^\n]*?)[ \t]*-*[ \t]*$", lambda m: f"{m.group(1)} {m.group(2)}" + (f" {m.group(3)}" if m.group(3) else ""), t); n += k
    if ocr or bb:  # sequence-aware: publisher-OCR layers of every source, and every Banská Bystrica text (its born-digital PDFs
                   # also print § as '8'/'5': '82', '810', '8 12', '51', '8 1 Úvodné ustanovenia'). A line that is only
                   # '§N'/'$N'/'sN'/'SN'/'8 N'/'8N' becomes '§ N' only when N is the next expected § number (BB: or a skip of
                   # up to 3 followed by a heading title). Born-digital texts of other cities use '81','82' for list items 8.1, 8.2.
        lines = t.split("\n"); exp = 1
        for i, ln in enumerate(lines):
            m = re.fullmatch(r"[ \t]*(§|\$|8|S|s|5)[ \t]?([1-9]\d?)[ \t]*\.?[ \t]*", ln)
            if m and m.group(1) == "5" and not bb: m = None
            if not m:
                if not bb: continue
                # '8 1 Úvodné ustanovenia': heading number and title on one line
                m2 = re.fullmatch(r"[ \t]*(\$|8|S|s)[ \t]?([1-9]\d?)[ \t]+([A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ][a-záäčďéíĺľňóôŕšťúýž]+(?: [^\n]*)?)", ln)
                if m2 and exp <= int(m2.group(2)) <= exp + 3 and not re.search(r"\d+[,.]\d|€|eur\b|Sk\b|%", m2.group(3)):
                    v = int(m2.group(2)); lines[i] = f"§ {v} {m2.group(3)}"; exp = v + 1; n += 1
                continue
            v = int(m.group(2))
            if m.group(1) == "§": exp = v + 1; continue
            nxt1 = next((x.strip() for x in lines[i + 1:i + 4] if x.strip()), "")
            if v == 1 and exp > 1 and bb and re.match(r"[A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽU][a-záäčďéíĺľňóôŕšťúýž]", nxt1):
                exp = 1        # '81' + title after a stray earlier '§ 2' line (cover sheet / TOC): the run starts here
            # the next expected number, or a skip of up to 3 (a heading lost/unrecognised in the source layer, e.g. '§ 1' missing,
            # '810' after '§ 7'); only for lines that are nothing but marker+number
            nxt = next((x.strip() for x in lines[i + 1:i + 4] if x.strip()), "")
            if m.group(1) == "5" and v != exp: continue      # '51' for '§ 1' (Banská Bystrica): only as the exact next number
            if v != exp and not bb: continue                 # other sources: only the exact next number
            if v != exp and not re.match(r"[A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ(]", nxt): continue     # a skip needs a heading title on the next line
            if exp <= v <= exp + 3: lines[i] = "§ " + str(v); exp = v + 1; n += 1
        t = "\n".join(lines)
    return t, n

def split_articles(text):
    out, cov, chk = _split_repair(text)
    if len(out) > 1:
        out, chk["parts"], chk["nested"], chk["toc_records"] = refine_records(out, chk["marker"])
    return out, cov, chk

def is_toc_records(recs):
    """Records that are a table of contents: almost no text after each heading line and no sentences."""
    rs = [r for r in recs if r[0] != "0"][:-1]
    if len(rs) < 2: return False
    after = sorted(len(b.split("\n", 1)[1].strip()) if "\n" in b else 0 for _, _, b in rs)
    sent = sum(1 for _, _, b in rs if re.search(r"[a-záäčďéíĺľňóôŕšťúýž][.;](\s|$)", b.split("\n", 1)[1] if "\n" in b else ""))
    return after[len(after) // 2] < 40 and sent < 0.3 * len(rs)

def refine_records(out, top_marker):
    """A record (incl. Úvod) that still holds >= 3 sequential headings is split again: a restart of the main numbering
    (parts / sections that restart Čl. 1, an attached second act) becomes part k with labels 'pK.N'; another heading family inside
    an article (an annex with its own Článok 1..N inside § 15) gets labels '<parent>.N'. Tables of contents are left in place."""
    res, nested, tocs = [], 0, 0
    parts = collections.Counter({"": 1}); nblk = collections.Counter()
    work = [(l, t, b, top_marker, "") for l, t, b in out]
    while work:
        lab, title, body, fam, base = work.pop(0)
        inner = body if lab == "0" else (body.split("\n", 1)[1] if "\n" in body else "")
        if heading_run(inner)[0] < 3 or lab.count(".") >= 4:
            res.append((lab, title, body)); continue
        sub, _, k = _split(inner)
        if len(sub) < 3 or is_toc_records(sub):
            if len(sub) >= 3: tocs += 1
            res.append((lab, title, body)); continue
        lead = body[:len(body) - len(inner)] + (sub[0][2] if sub[0][0] == "0" else "")
        kids = [r for r in sub if r[0] != "0"]
        if lead.strip():
            if len(lead) < len(body) and heading_run(lead if lab == "0" else (lead.split("\n", 1)[1] if "\n" in lead else ""))[0] >= 3:
                work.insert(0, (lab, title, lead.strip(), fam, base)); lead_again = True     # the lead holds another block: refine it too
            else: res.append((lab, title, lead.strip())); lead_again = False
        else: lead_again = False
        pos = 1 if lead_again else 0                  # children go after the lead (which is refined first)
        if k["marker"] == fam and lab != "0":        # the same numbering restarts: a new part at the same level
            parts[base] += 1; p = parts[base]
            work[pos:pos] = [(f"{base}p{p}.{l}", t, b, fam, base) for l, t, b in kids]
        else:                                         # another heading family inside this record
            nested += 1; nblk[lab] += 1; nb = f"{lab}." if nblk[lab] == 1 else f"{lab}.b{nblk[lab]}."; parts[nb] = 1
            work[pos:pos] = [(f"{nb}{l}", t, b, k["marker"], nb) for l, t, b in kids]
    part = parts[""]
    return res, part, nested, tocs

def _split_repair(text):
    """Split with one repair pass: a missing § number whose heading is glued to a page number ('-2§5') or follows a sentence on
    the same line ('súhlasí. § 20 Vo veciach ...', '§ 10 - vypustený') gets its own line, then the text is split again."""
    out, cov, chk = _split(text)
    if not chk["gaps"]: return out, cov, chk
    t2 = text
    for n in chk["gaps"]:
        rx = r"(?:(?<=[.;:])|(?<=^-\d)|(?<=^-\d\d)|(?<=^- \d -)|(?<=^-\d-))[ \t]*(?=(?:§|" + CL + r")[ \t]*%d(?![\d\w])(?![ \t]*(?:ods|písm|zák|a[ \t]|až|,|\)|\.\s*\d)))" % n
        t2 = re.sub(rx, "\n", t2, count=1, flags=re.M)
        # publisher-OCR digit confusions in a line-initial heading ('Článok S' for 'Článok 5')
        conf = "".join({"5": "[5S]", "0": "[0O]", "1": "[1lI]", "8": "[8B]", "6": "[6b]"}.get(ch, ch) for ch in str(n))
        if conf != str(n):
            t2 = re.sub(r"(?m)^([ \t]*(?:§|" + CL + r")[ \t]*)" + conf + r"(?=[ \t]*$)", lambda m: m.group(1) + str(n), t2, count=1)
    if t2 == text: return out, cov, chk
    o2, c2, k2 = _split(t2)
    if len(k2["gaps"]) < len(chk["gaps"]) and not k2["hidden"]: k2["repaired"] = len(chk["gaps"]) - len(k2["gaps"]); k2["text"] = t2; return o2, c2, k2
    return out, cov, chk

def _split(text):
    """Line-initial headings only. The dominant marker family (§ / Čl.-arabic / Čl.-roman) is the one with the longest run
    1,2,3,... ; TOC lines (dot leaders / page numbers) are skipped; numbering must increase by +1 (suffix letters 'a','b' allowed
    after their base); a restart at 1 opens a new block only after a clear end ('Príloha', second act). Returns
    (records, coverage, checks)."""
    cands = all_candidates(text)
    best, bestfam = [], None
    for fam in ("§", "cl", "cl-roman", "rom", "cast"):
        seq, prev, prev_suf = [], 0, None
        fc = [c for c in cands if c[1] == fam]
        for j, c in enumerate(fc):
            pos, _, n, suf, rest, raw, end = c
            if suf and n == prev and suf != prev_suf: seq.append(c); prev_suf = suf; continue
            if suf: continue
            if n == prev + 1: seq.append(c); prev, prev_suf = end, None; continue
            if prev == 0 and n in (2, 3) and not any(d[2] == 1 and not d[3] for d in fc) and any(d[2] == n + 1 and not d[3] for d in fc[j + 1:j + 3]):
                seq.append(c); prev, prev_suf = end, None; continue
            # a jump of 2-3 (repealed/omitted section) is accepted only when the following candidate continues from it
            nx = [d for d in fc[j + 1:j + 4] if not d[3]]
            if prev >= 1 and prev + 1 < n <= prev + 3 and (any(d[2] == n + 1 for d in nx[:2])
                    or (len(nx) >= 2 and n < nx[0][2] <= n + 3 and nx[1][2] == nx[0][2] + 1)
                    or (not nx and n <= prev + 2 and re.match(r"(?i)\W*(?:záverečn|zaverecn|účinnos|ucinnos|zrušovac)", rest))):   # last heading after an omitted one
                seq.append(c); prev, prev_suf = end, None
        if fam in ("rom", "cast") and len(best) >= 3: continue   # bare roman / Časť headings lead only when no §/Čl. run exists
        if len(seq) > len(best): best, bestfam = seq, fam
    lenient = False
    if len(best) < 2:
        # fallback: longest strictly increasing chain (steps 1..5, no suffixes) of one family, >= 3 headings - acts whose numbering is
        # broken in the source/OCR layer (missing or unreadable headings). Gaps are recorded as usual.
        for fam in ("§", "cl", "cl-roman", "rom", "cast"):
            fc = [c for c in cands if c[1] == fam and not c[3]]
            dp = []
            for j, c in enumerate(fc):
                bestj = [c]
                for k in range(j):
                    if dp[k][-1][6] < c[2] <= dp[k][-1][6] + 5 and len(dp[k]) + 1 > len(bestj): bestj = dp[k] + [c]
                dp.append(bestj)
            ch = max(dp, key=len) if dp else []
            if len(ch) >= 3 and len(ch) > len(best): best, bestfam, lenient = ch, fam, True
    if len(best) < 2:
        return [("1", "whole text", text.strip())], 1.0, dict(marker=None, gaps=[], hidden=[])
    out = []
    if text[:best[0][0]].strip(): out.append(("0", "Úvod", text[:best[0][0]].strip()))
    for i, c in enumerate(best):
        end = best[i + 1][0] if i + 1 < len(best) else len(text)
        body = text[c[0]:end].strip()
        lab = f"{c[2]}{c[3] or ''}" + (f"-{c[6]}" if c[6] != c[2] else "")
        head = c[5] if c[4] else (c[5] + " " + body.split("\n", 2)[1].strip() if body.count("\n") >= 1 else c[5])
        out.append((lab, head[:300], body))
    # gaps (missing numbers between consecutive headings) and hidden headings: a missing number that does occur as a
    # same-family line-initial candidate inside the preceding record (i.e. the splitter skipped it)
    hidden, gaps = [], []
    if best and best[0][2] > 1: gaps += list(range(1, best[0][2]))
    for i, c in enumerate(best):
        end = best[i + 1][0] if i + 1 < len(best) else len(text)
        if i + 1 < len(best) and best[i + 1][2] > c[6] + 1:
            miss = list(range(c[6] + 1, best[i + 1][2])); gaps += miss
            for d in cands:
                if d[1] == bestfam and c[0] < d[0] < end and d[2] in miss and not d[3]: hidden.append(f"{c[2]}->{d[2]}")
    cov = sum(len(b) for _, _, b in out) / max(1, len(text.strip()))
    return out, cov, dict(marker=bestfam, gaps=gaps, hidden=hidden, lenient=lenient)

def doc_type(title):
    t = title.lower()
    for k, rx in (("územný plán", r"územn\w* plán|územnoplánovac|záväzn\w* časť"), ("dane a poplatky", r"dani|daň|poplat"),
                  ("názvy ulíc", r"názv\w* ul|názv\w* verejn|pomenovan"), ("parkovanie", r"parkovan"), ("školstvo", r"škol|dieťa|dieťaťa|materské|príspevk"),
                  ("sociálne služby", r"sociáln"), ("trhový poriadok", r"trhov|predaj výrobkov"), ("verejný poriadok", r"poriad|čistot|psov|alkohol|hluk|nočn|hazard|herní"),
                  ("odpady", r"odpad"), ("dotácie", r"dotáci")):
        if re.search(rx, t): kind = k; break
    else: kind = "iné"
    amend = bool(re.search(r"(?i)ktorým sa (mení|dopĺňa|menia)|zmena vzn|dodatok", title))
    repeal = bool(re.search(r"(?i)ktorým sa zrušuje|o zrušení všeobecne", title))
    return kind, ("amending" if amend else "repealing" if repeal else "original")


GENERIC_TITLE = re.compile(r"(?i)^\s*(znenie\s+)?(vzn|všeobecne záväzné nariadenie)(\s+mesta|\s+obce)?\s*(č\.)?\s*[\d/ .-]*\s*$")
def subject_from_text(text, reg=None):
    """'... č. 3/2012\n z 23. marca 2012\n o dani za užívanie verejného priestranstva' -> 'o dani za užívanie verejného priestranstva'."""
    head = text[:3000]
    # whole heading block: from the act's name line to the enacting clause ('Miestne zastupiteľstvo ... podľa ...')
    hb = re.search(r"(?is)((?:všeobecne\s+záväzné\s+nariadenie|VZN)\b.{10,900}?)\n\s*(?:(?:Mestské|Miestne|Obecné)\s+zastupiteľstvo|Mesto\s+\S+\s+(?:na\s+základe|podľa|v\s+zmysle)|Hlavné\s+mesto\s+Slovenskej\s+republiky\s+Bratislava\s+(?:podľa|na))", head)
    if hb:
        t = re.sub(r"\s+", " ", hb.group(1)).strip()
        if 25 <= len(t) <= 900 and not re.search(r"(?i)úplné znenie vzn nájdete", t): return t[:300]
    m = re.search(r"(?im)^\s*((?:o|ktorým|ktorou|ktorými|ktoré)\s[^\n]{8,}(?:\n(?![ \t]*(?:§|Čl|Mestské|Miestne|Obecné|Zastupiteľstvo|Hlavné))[^\n]{3,}){0,2})", head)
    if not m: return None
    sub = re.sub(r"\s+", " ", m.group(1)).strip()
    sub = re.split(r"(?<=[a-zľščťžýáíéúäôň\)])\s+(?=(?:Mestské|Miestne|Obecné) zastupiteľstvo)", sub)[0]
    return sub[:300]


def source_ocr_layer(text):
    """Text layer produced by the publisher's own OCR of a scan (we never OCR): '§' read as s/8/$/S, diacritics dropped."""
    return (len(re.findall(r"(?:^|\s)[s8\$S]\s?\d{1,2}\s+ods\.", text)) >= 2 or len(re.findall(r"\b(Clánok|Úcinnost|vseobecne|zastupiterstvo|císlo)\b", text)) >= 2
            # degraded layer without diacritics: digits inside words ('z6ny', 'zav8znej') or typical glyph swaps ('uznesenfm', 'zastupitefstvo')
            or len(re.findall(r"\b[a-zA-Z]+[0-9][a-z]+\b", text)) >= 3 and len(re.findall(r"(?i)zastupitefstv|uznesenfm|zriadenf|neskoffi|z6ny|zav8zn", text)) >= 1)
