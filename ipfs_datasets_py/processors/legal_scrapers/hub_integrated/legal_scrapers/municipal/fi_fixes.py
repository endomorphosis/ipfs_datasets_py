#!/usr/bin/env python3
"""Verifier-driven fixes for the FI municipal build: text repair, non-normative filtering, titles, language,
effective dates + version resolution (law_status), and § number restoration from the table of contents."""
import collections, re, unicodedata
TODAY = "2026-10-16"
MUNI_GEN = {"091": "helsing", "049": "espoo", "837": "tampere", "092": "vantaa", "564": "oulu", "853": "turku", "179": "jyväskylä",
            "297": "kuopio", "398": "lahde", "609": "pori", "286": "kouvola", "167": "joensuu", "405": "lappeenran", "109": "hämeenlinna",
            "905": "vaasa", "743": "seinäjoe", "698": "rovanie", "491": "mikkeli", "285": "kotka", "734": "salo"}

SHIFT_MAP = {"l": "ä", "|": "ö", "\x86": "§", "b": "Ä", "g": "Ö", "¼": "€"}
def shift_fix(text):
    """Fonts with a +29 code offset ('.RXYRODQ\\x03NDXSXQNL' -> 'Kouvolan kaupunki')."""
    ctl = lambda l: sum(1 for c in l if ord(c) < 0x20 and c not in "\t")
    dec1 = lambda l: "".join(c if c == " " else SHIFT_MAP.get(c, chr(ord(c) + 29) if ord(c) < 0x62 else c) for c in l)
    if text.count("\x03") < 20:   # only isolated stamp lines (e.g. '\x14\x13\x11...' = '10.12.2025'): decode those lines only
        return "\n".join(dec1(l).strip() if ctl(l) >= 2 else l for l in text.split("\n"))
    out = []
    for line in text.split("\n"):
        if line.strip():
            dec = "".join(c if c == " " else SHIFT_MAP.get(c, chr(ord(c) + 29) if ord(c) < 0x62 else c) for c in line)
            sc = lambda s: len(re.findall(r"(?i)(en|an|in|aa|ää|ta|tä|ja|is|uu|ks)", s))
            line = dec if (ctl(line) >= 2 or sc(dec) > sc(line) * 1.3) else line
        out.append(line)
    return "\n".join(out)

NON_NORMATIVE = re.compile(r"(?i)(perustelu|luonnos|lausunno|palaute|osallistumis-? ja arviointi|\boas\b|oas-|asiakkaille|kehittamistuki|kehittämistuki|"
                           r"ty(o|ö)llistamislis|kes(a|ä)ty(o|ö)|koulun-jarjestys|koulun järjestys|karpasen-koulun)")
def script_bad(t):
    s = t[:20000]; n = max(1, len(s))
    return len(re.findall(r"[а-яА-Я]", s)) / n > 0.05 or len(re.findall(r"[\u0600-\u06FF]", s)) / n > 0.02

def other_muni(d):
    """Document issued by a different municipality (e.g. 'SUONENJOEN KAUPUNKI' hosted by Kuopio)."""
    head = d["text"][:250]
    m = re.findall(r"(?i)\b([A-ZÅÄÖa-zåäö]+?)N (KAUPUNKI|KUNTA)\b", head)
    own = MUNI_GEN.get(d["municipality_code"], "")[:4]
    return bool(m) and not any(x[0].lower().startswith(own) for x in m) and own not in head.lower()

def lang_of(t, title=""):
    if re.search(r"(?i)\b(taksa|alkaen|lukien|sääntö|säännöt|maksut?|määräykset|järjestys)\b", title): return "fi"
    w = re.findall(r"\w+", t.lower()[:30000])
    fi = sum(x in ("ja", "tai", "sekä", "on", "kaupungin", "kunnan", "taksa", "maksu", "euroa", "alkaen", "jos", "että", "voidaan", "mukaan") for x in w)
    sv = sum(x in ("och", "för", "att", "som", "med", "staden", "kommunen", "avgift", "från", "eller", "enligt") for x in w)
    return "sv" if sv > 1.5 * fi else "fi"

GENERIC = re.compile(r"(?i)^(avaa tiedosto|sääntö|säännöt|toimintasääntö|hallintosääntö|rakennusjärjestys|taksa|maksut|perustelut|pdf|"
                     r"[\w\-]+\.pdf|rakennusjärjestys \(pdf\)|hallintosääntö \(pdf\))$")
def garbled(s):
    letters = sum(c.isalpha() for c in s); return len(s) > 5 and letters / len(s) < 0.6
def derive_title(d):
    lines = [l.strip() for l in d["text"].split("\n") if l.strip()]
    lines = [l for l in lines[:25] if not re.fullmatch(r"[\d\s()/.\-]+", l) and not re.match(r"(?i)^(sivu|page)\b", l)]
    kw = re.compile(r"(?i)sääntö|säännöt|taksa|määräy|järjestys|maksu|ohjesääntö|toimintasääntö|stadga|taxa")
    for i, l in enumerate(lines):
        if kw.search(l) and len(l) < 160:
            t = l
            if i + 1 < len(lines) and (t.endswith("-") or (lines[i + 1].isupper() and t.isupper() and len(t) < 60)) and len(lines[i + 1]) < 80:
                t = (t[:-1] if t.endswith("-") else t + " ") + lines[i + 1]
            if i > 0 and lines[i - 1].endswith("-") and len(lines[i - 1]) < 80:
                t = lines[i - 1][:-1] + t
            elif i > 0 and len(lines[i - 1]) < 60 and ((lines[i - 1].isupper() and t.isupper()) or len(t.split()) <= 2) and not kw.search(lines[i - 1]) \
                    and re.search(r"(?i)(kaupun|kunta|kunnan|seudun|lautakun|stad)", lines[i - 1]):
                t = lines[i - 1] + " " + t
            if i + 1 < len(lines) and lines[i + 1] not in t and re.match(r"^\d{1,2}\.\d{1,2}\.\d{4}\s*(alkaen|lukien)?$", lines[i + 1], re.I):
                t = t + " " + lines[i + 1]
            k = i + 1
            while re.search(r"(?i)\s(ja|sekä|och)$", t) and k < len(lines) and len(lines[k]) < 90: t += " " + lines[k]; k += 1
            t = re.sub(r"\s+\d{1,3}\s?§.*$", "", " ".join(t.split()))
            return t[:1].upper() + t[1:].lower() if t.isupper() else t
    stem = re.sub(r"[_\-]+", " ", d["native_id"]).strip()
    return stem[:1].upper() + stem[1:]
def heading_block(d):
    """Cover-page heading split over lines ('Kuopion Tilapalveluiden / toimintasääntö / 1.1.2026 alkaen'):
    lines before the doc-type line are joined to it (hyphen-aware)."""
    lines = [l.strip() for l in d["text"].split("\n") if l.strip()][:14]
    for i, l in enumerate(lines):
        if re.fullmatch(r"(?i)(toiminta-?\s?)?sääntö|toimintasääntö|johtosääntö|taksa", l):
            pre = []
            for j in range(i - 1, max(-1, i - 4), -1):
                if re.fullmatch(r"-?[A-ZÄÖÅa-zäöå][\wäöåÄÖÅ \-]{1,58}", lines[j]) and not re.match(r"(?i)sisällys|sääntö nro|liitenro", lines[j]):
                    pre.insert(0, lines[j])
                else: break
            if not pre: return None
            t = ""
            for part in pre + [l]:
                t = (t[:-1] + part) if t.endswith("-") and not t.endswith(" -") else (t + " " + part).strip()
            return re.sub(r"\s+", " ", t)
    return None

def fix_title(d):
    t = re.sub(r"\s*\((pdf|PDF|pfd)[^)]*\)\s*(\([\d.,]+ ?[KM]B\))?", "", d["title"]).strip()
    t = re.sub(r"(?i)\s+sisällysluettelo$", "", t); t = re.sub(r"(rakennusjärjestykse|järjestykse)n$", r"\1".replace("kse", "s") if False else lambda m: m.group(1)[:-3] + "s", t)
    t = re.sub(r"\s+pdf(-tiedostona)?$", "", t, flags=re.I); t = re.sub(r"\s*\(\s*pdf[^)]*\)", "", t, flags=re.I); t = re.sub(r"\s+\d{1,3}\s?§.*$", "", t).strip()
    t = re.sub(r"\.pdf$", "", t, flags=re.I).strip()
    if re.match(r"(?i)^(toiminta)?sääntö\b|^toimintasääntö\b", t):       # title is just the doc type (+date)
        hb = heading_block(d)
        if hb: d["extras"]["original_link_title"] = d["title"]; t = hb + (" " + m.group(0) if (m := re.search(r"\d{1,2}\.\d{1,2}\.\d{4}\s*(alkaen|lukien)?", t)) else "")
    if GENERIC.match(t) or garbled(t) or len(t) < 6 or len(t.split()) <= 1 or re.search(r"(?i)\s(ja|sekä|och)$", t):
        t2 = derive_title(d)
        d["extras"]["original_link_title"] = d["title"]; t = t2
    if len(t.split()) <= 2 and d["municipality"].lower()[:4] not in t.lower():
        t = f"{t} – {d['municipality']}" + (f" {d['date']}" if d.get("date") else "")
    d["title"] = t

# ---------- dates & versions ----------
def _iso(dd, mm, yy):
    try:
        dd, mm, yy = int(dd), int(mm), int(yy)
        if 1 <= dd <= 31 and 1 <= mm <= 12 and 1980 <= yy <= 2035: return f"{yy:04d}-{mm:02d}-{dd:02d}"
    except Exception: pass
    return None
EFF = [r"(?i)(?:alkaen|lukien)\s+(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})",
       r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\s*(?:alkaen|lukien|från|ALKAEN|LUKIEN)",
       r"(?i)(?:voimaan|voimaantulo|voimassa|voimaantulopäivä|tulee voimaan)\D{0,25}(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})",
       r"(?<![\d.])(\d{1,2})\s(\d{1,2})\s(20\d{2})\s(?:alkaen|lukien)"]
STRONG = r"(?i)(?:voimaan|voimaantulo|voimassa|voimaantulopäivä|träder i kraft|ikraftträdande)\D{0,25}(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})(?!\s*(?:asti|saakka|mennessä|till))"
def effective_date(d):
    """Order: explicit effective phrase in title/id ('alkaen/lukien/voimaan <date>') > 'alkaen/lukien <date>' in the
    header (first 1500 chars) > the date in the act's own '§ Voimaantulo' section >
    voimaantulo/voimaan/voimassa date anywhere in the text (latest one, i.e. the current wording after amendments) > ddmmyyyy in id >
    other 'alkaen' dates in the text head > 'voimaan heti' + adoption date > adoption date > year in title/id."""
    tid = " ".join([d["title"], d["native_id"].replace("_", " ").replace("-", " ")])
    ym = re.search(r"(?<!\d)(19[89]\d|20[0-3]\d)(?!\d)", tid); tyear = ym.group(1) if ym else None
    for rx in EFF:
        m = re.search(rx, tid)
        if m and _iso(*m.groups()[:3]): return _iso(*m.groups()[:3]), "effective"
    txt = d["text"]
    # the act's own header ('JÄTEHUOLTOMÄÄRÄYKSET 1.6.2023 alkaen') and its own '§ Voimaantulo' section (not a TOC line) beat
    # dates elsewhere in the body; the latest of them wins (amended consolidations: 'Muutettu taksa tulee voimaan 1.1.2024')
    own = []
    for rx in (EFF[0], EFF[1], EFF[3]):
        own += [_iso(*m.groups()[:3]) for m in re.finditer(rx, txt[:1500])]
    vs = list(re.finditer(r"(?im)^[ \t]*\d+[ \t]*§[ \t]*(?:Voimaantulo|Ikraftträdande)\b(?![^\n]*\.{4,})[^\n]*$", txt))
    if vs:
        sec = re.split(r"(?m)^[ \t]*\d+[ \t]*§", txt[vs[-1].end(): vs[-1].end() + 1500])[0]
        own += [_iso(*m.groups()) for m in re.finditer(r"(?i)(?:voimaan|träder i kraft)\D{0,40}(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})", sec)]
    own = [v for v in own if v and v <= "2028-12-31"]
    if own: return max(own), "effective"
    strong = [v for v in (_iso(*m.groups()) for m in re.finditer(STRONG, txt)
                          if not re.search(r"(?i)(sellaisena\s+kuin|kuin\s+(se|ne)\s+(on|ovat))\s*$", txt[max(0, m.start() - 40):m.start()]))
              if v and v <= "2028-12-31"]                # skips statute citations ('lakia ... sellaisena kuin se on voimassa 1.1.2013')
    if strong: return max(strong), "effective"          # text's (latest) voimaan date beats a date in the file name
    m = re.search(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)", d["native_id"])
    if m and _iso(*m.groups()): return _iso(*m.groups()), "effective"
    for rx in (EFF[0], EFF[1], EFF[3]):
        m = re.search(rx, txt[:2500])
        if m and _iso(*m.groups()[:3]): return _iso(*m.groups()[:3]), "effective"
    m = re.search(r"(?i)(?:hyväksytty|hyväksyi|kv|kaupunginvaltuusto|valtuusto|lautakunta|kaupunginhallitus)\D{0,30}(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})", txt)
    if m and _iso(*m.groups()):
        v = _iso(*m.groups())
        if re.search(r"(?i)voimaan\s+heti|voimaan\s+välittömästi", txt): return v, "effective"
        if not (tyear and v[:4] < tyear): return v, "adopted"
    if tyear: return tyear, "year"
    return None, None

DATES_RX = re.compile(r"(?<!\d)(\d{1,2}[._-]\d{1,2}[._-](19|20)?\d{2}|\d{2}\d{2}(19|20)\d{2}|\d{6}|(19|20)\d{2})(?!\d)")
CORE = ("hallintosääntö", "rakennusjärjestys", "järjestyssääntö", "jätehuoltomääräykset", "ympäristönsuojelumääräykset", "taloussääntö")
def version_key(d):
    dt = d["extras"].get("doc_type")
    s = (d["title"] + " " + d["native_id"]).lower()
    if dt in CORE and not re.search(r"\bliite|\bosa\b|-osa-|\bluvut|\bohje\b|kaavam", s):
        return (d["municipality_code"], dt)
    base = unicodedata.normalize("NFKD", d["native_id"].lower())
    base = DATES_RX.sub(" ", base)                      # drop dates/years only; other numbers ('luvut-1-2' vs 'luvut-3-4') stay
    base = re.sub(r"alkaen|lukien|poytakirjaan|hyvaksytty|lopullinen|uusin|saavutettava|[^a-z0-9]+", "", base)
    return (d["municipality_code"], base)

def resolve_versions(docs):
    for d in docs:
        dt, kind = effective_date(d); d["date"] = dt; d["extras"]["date_kind"] = kind
    # union of two keys: file-stem/doc-type key and normalized title key (titles like 'Sivistystoimialan toimintasääntö
    # 27.3.2026 lukien' vs '... – Kuopio' with differing file stems)
    def tkey(d):
        t = re.sub(r"\d{1,2}\.\d{1,2}\.\d{2,4}|\b(19|20)\d\d\b|\b(alkaen|lukien|från)\b|\s–\s.*$|\(.*?\)", " ", d["title"].lower())
        t = re.sub(r"[^0-9a-zäöå]+", " ", t).strip()
        return (d["municipality_code"], "T:" + t) if len(t.split()) >= 2 else None
    parent = {}
    def find(x):
        while parent.setdefault(x, x) != x: x = parent[x]
        return x
    for d in docs:
        a = find(version_key(d)); b = tkey(d)
        if b: parent[find(b)] = a
    groups = collections.defaultdict(list)          # language versions (fi/sv) are separate acts, never versions of each other
    for d in docs: groups[(find(version_key(d)), d.get("language"))].append(d)
    keep, folded = [], 0
    for k, g in groups.items():
        # identical-version copies (same date, incl. both undated): keep longest, fold others WITH text
        ntit0 = lambda x: re.sub(r"[^0-9a-zåäö]+", "", x["title"].lower())
        # fold only copies with the same date AND (an identical title OR the same text: word-set Jaccard >= 0.8, which absorbs
        # PDF-vs-HTML extraction noise); 'luvut 1-2' vs 'luvut 3-4' (Jaccard 0.11) stay apart
        wset = lambda x: set(re.findall(r"[0-9a-zäöå]+", x["text"].lower()))
        jac = lambda a, b: len(wset(a) & wset(b)) / max(1, len(wset(a) | wset(b)))
        bydate = collections.defaultdict(list); cl = []
        for d in sorted(g, key=lambda x: -len(x["text"])):
            dk = (d["date"] or "")[:10]
            hit = next((c for c in cl if c[0] == dk and (ntit0(c[1]) == ntit0(d) or jac(c[1], d) >= 0.8)), None)
            if hit: bydate[id(hit[1])].append(d)
            else: cl.append((dk, d)); bydate[id(d)].append(d)
        reps = []
        for dk, dd in bydate.items():
            dd.sort(key=lambda x: -len(x["text"])); main = dd[0]
            for o in dd[1:]:
                main["extras"].setdefault("alt_versions", []).append({"source_url": o["source_url"], "title": o["title"], "text": o["text"]}); folded += 1
            reps.append(main)
        dated = sorted([d for d in reps if d["date"]], key=lambda x: x["date"])
        past = [d for d in dated if d["date"][:10] <= TODAY]
        current = past[-1] if past else None
        if current is not None:
            ntit = ntit0
            for d in [r for r in reps if not r["date"] and ntit(r) == ntit(current)]:
                current["extras"].setdefault("alt_versions", []).append({"source_url": d["source_url"], "title": d["title"], "text": d["text"]}); folded += 1
                reps.remove(d)
        for d in reps:
            if d["date"] and d["date"][:10] > TODAY: d["status"] = "not_yet_in_force"
            elif current is not None and d is not current and len(reps) > 1 and d["date"]: d["status"] = "repealed"; d["extras"]["superseded_by"] = current["source_url"]
            elif d is current and (len(reps) > 1 or d["extras"]["date_kind"] == "effective"): d["status"] = "in_force"
            else: d["status"] = "unknown"
            keep.append(d)
    return keep, folded

# ---------- § restoration from TOC (Helsinki hallintosääntö: § numbers are auto-numbering, absent from the text layer) ----------
def restore_toc_numbers(text):
    lines = text.split("\n")
    toc_idx = [i for i, l in enumerate(lines) if re.search(r"\.{5,}\s*\d*\s*$", l)]
    if len(toc_idx) < 20: return text, 0
    body_heads = len(re.findall(r"(?m)^[ \t]{0,3}\d{1,3} ?[a-z]? ?§", "\n".join(lines[toc_idx[-1] + 1:])))
    if body_heads > len(toc_idx) * 0.3: return text, 0
    entries, block, n, last = [], 0, 0, None
    for i in toc_idx:
        l = lines[i]
        if re.match(r"^\s*[IVX]+ osa\b", l): last = i; continue
        if last is None or i - last > 1: block += 1; n = 0
        last = i
        m = re.match(r"^\s*(\d{1,3})\s?([a-z])?\s?§\s*(.*?)\s*\.{3,}", l)
        title = re.sub(r"\s*\.{3,}.*$", "", l).strip()
        if m:
            num = f"{m.group(1)}{m.group(2) or ''}"; title = m.group(3).strip()
            if not m.group(2): n = int(m.group(1))
        else:
            n += 1; num = str(n)
        entries.append((block, num, title))
    pos, done, cur = toc_idx[-1] + 1, 0, None
    for blk, num, title in entries:
        if len(title) < 3: continue
        for j in range(pos, len(lines)):
            s = lines[j].strip()
            s2 = re.sub(r"^\d{1,3}\s?[a-z]?\s?§\s*", "", s)
            if s2 == title:
                # chapter marker (TOC block) so the splitter can tell a chapter restart from a stray '1 §'
                lines[j] = (f"{blk} luku\n" if blk != cur else "") + f"{num} § {title}"; cur = blk
                pos = j + 1; done += 1; break
    return "\n".join(lines), done
