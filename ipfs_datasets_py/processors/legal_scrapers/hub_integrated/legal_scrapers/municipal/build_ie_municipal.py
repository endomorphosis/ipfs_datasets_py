#!/usr/bin/env python3
"""Build the Ireland municipal corpus (local-authority bye-laws) from the collector output.
Usage: python build_ie_municipal.py [BUILD_DIR] [OUT_DIR]   (defaults: ie_build, ireland_municipal; relative to the working directory)
Inputs in BUILD_DIR: links.jsonl, fetch_log.jsonl, docs/<sha20>.<pdf|docx|doc> (collect_ie_municipal.py)."""
import os, sys, re, json, urllib.parse, collections, hashlib, shutil, unicodedata, datetime, difflib
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import pyarrow as pa, pyarrow.parquet as pq
import ie_fixes as F
from collect_ie_municipal import COUNCILS, SKIP
from schema import MUNICIPAL_LAWS_SCHEMA, RAW_ARTICLES_SCHEMA, validate_municipal_table, municipal_law_id

COLLECTORS = ("ie_common.py", "ie_fixes.py", "collect_ie_municipal.py", "build_ie_municipal.py")
LIC = ("Bye-laws made by Irish local authorities are public acts; texts as published by the councils on their websites. Re-use of public "
       "sector information: European Communities (Re-Use of Public Sector Information) Regulations 2005-2021 / Open Data Directive (EU) 2019/1024; "
       "check each council's site terms for attribution requirements.")
PROVINCE = {"5": "Leinster", "6": "Ulster", "7": "Munster", "31": "Munster", "8": "Munster", "9": "Ulster", "32": "Leinster", "10": "Leinster",
            "11": "Leinster", "33": "Connacht", "12": "Connacht", "13": "Munster", "14": "Leinster", "15": "Leinster", "16": "Leinster",
            "17": "Connacht", "34": "Munster", "18": "Leinster", "19": "Leinster", "20": "Connacht", "21": "Leinster", "22": "Ulster",
            "23": "Leinster", "24": "Connacht", "25": "Connacht", "26": "Leinster", "27": "Munster", "35": "Munster", "28": "Leinster",
            "29": "Leinster", "30": "Leinster"}
STATS = collections.Counter(); DROPS = collections.defaultdict(list)
MAX_BYTES = 40_000_000; NEAR_J = 0.90
def shingles(t, k=5):
    w = re.findall(r"\w+", t.lower()); return {" ".join(w[i:i + k]) for i in range(0, max(1, len(w) - k + 1))}
def jacc(a, b): return len(a & b) / max(1, len(a | b))

TITLE_RX = re.compile(r"(?i)^(?=.{8,260}$)(?=.*(bye[\s\-–]*laws?|byelaws?|by[\s\-]laws?|fodhl[ií]))")
CITE = re.compile(r"(?i)(?:may\s+be\s+cited\s+(?:for\s+all\s+purposes\s+)?as|shall\s+be\s+(?:cited|known|referred\s+to)\s+as|"
                  r"citation\s+of\s+these\s+bye[\s\-–]*laws\s+(?:is|shall\s+be)|\bthese\s+(?:bye[\s\-]*laws\s+)?are\s+(?=the\b))\s+(?:the\s+)?[“\"‘'«]?\s*(?P<t>[^”\"’»;]{6,220}?(?:bye[\s\-–]*laws?|byelaws?|by[\s\-]laws?)(?:,?\s*(?:\(No\.?\s*\d+\)\s*)?(?:1[89]|20)\d\d)?(?:\s*\(No\.?\s*\d+\))?)")
CITE_GA = re.compile(r"(?i)(?:féadfar\s+(?P<t>[^.;]{6,220}?fodhl[ií]the[^.;]{0,30}?)\s+a\s+lua|"
                     r"is\s+féidir\s+(?P<t2>[^.;]{6,220}?fo-?dhl[ií]the[^.;]{0,30}?)\s+a\s+thabhairt\s+ar\s+na\s+fo-?dhl)")
TEIDEAL = re.compile(r"(?i)\bis\s+teideal\s+do\s+na\s+fo-?dhl[ií]the")      # Irish short title: '<title> is teideal do na Fodhlíthe seo'
def teideal_title(flat):
    m = TEIDEAL.search(flat)
    if not m: return None
    pre = flat[max(0, m.start() - 220):m.start()]
    cut = max([pre.rfind(x) + len(x) for x in (". ", ": ", "; ", "Comhlua", "Gearrtheideal", "Teideal gearr", " 1 ")] + [0])
    t = pre[cut:].strip(" .:;,-–“”\"'")
    return t if 6 <= len(t) <= 200 and re.search(r"(?i)fo-?dhl", t) else None
SENTENCE = re.compile(r"(?i)\bhereby\b|in\s+exercise|powers\s+conferred|\bleis\s+seo\b|i\s+bhfeidhmi[uú]|\btiocfaidh\b|\bdéanann\b|\bshall\b|\bcome\s+into\b|\bmade\s+(?:by|under|on)\b|\ba\s+rinneadh\b")
def generic_title(s, c=None):
    """a title that names no particular bye-laws ('BYE-LAWS', 'FODHLÍTHE', 'Environment Bye Laws', 'Dublin City Council Bye-Laws'): no year
    and <= 3 words once the council's name is left out"""
    if c: s = re.sub("(?i)" + re.escape(c[1]) + "|" + re.escape(c[2]), " ", s)
    return not re.search(r"\b(1[89]|20)\d\d\b", s) and len(re.findall(r"[^\W\d_]+", s)) <= 3
def strip_council_prefix(s, c):
    """a leading council name ('COMHAIRLE CONTAE AN CHLÁIR CLARE COUNTY COUNCIL Clare County Council Beach Bye-Laws') is letterhead, unless it
    is part of the official title ('Carlow County Council (Control of Horses) Bye-Laws 2021'): drop the Irish name and a repeated English name"""
    fold = lambda x: unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower()
    for _ in range(3):
        f = fold(s); done = True
        for n in (c[2], c[1]):
            fn = fold(n)
            if f.startswith(fn) and len(s) > len(n) + 8:
                rest = s[len(n):].lstrip(" ,–-:")
                if n == c[1] and not fold(rest).startswith(fn) and not re.match(r"(?i)(comhairle)", rest): continue   # 'Carlow County Council (…)': keep
                s = rest; done = False; break
        if done: break
    return s
def clean_title(link_text, text, url, c=None):
    """the bye-laws' own title. Order: the citation clause ('These Bye-Laws may be cited as the Carlow County Council (Control of Horses)
    Bye-Laws 2021', Irish 'Féadfar … a lua'); the first line(s) naming bye-laws in the first 40 lines (a title split over lines is joined;
    a letterhead council name is dropped); the link text; the file name"""
    flat = re.sub(r"\s+", " ", text[:40000])
    for rx in (CITE, CITE_GA):
        m = rx.search(flat)
        g = m and (m.group("t") or (m.groupdict().get("t2") or ""))
        if m and not re.search(r"(?i)\b(XX+|_{2,})\b|hereby|in\s+exercise|powers\s+conferred|\bacts?\s+(1[89]|20)\d\d\b", g):
            return re.sub(r"\s+", " ", g).strip(" .:;,-–“”\"'")[:250]
    tt = teideal_title(flat)
    if tt and not SENTENCE.search(tt): return tt[:250]
    ls = [l.strip() for l in text.split("\n")[:60]]
    for i, l in enumerate(ls[:40]):
        if not TITLE_RX.match(l) or re.match(r"(?i)(in\s+exercise|notice|whereas|these\s+bye|the\s+bye|this\s+bye|\d+\.|bye[\s\-–]*laws?\s+\d|local\s+government\s+act)", l) \
                or re.search(r"(?i)in\s+exercise\s+of|powers\s+conferred|hereby\s+make|regulations,?\s+\d{4}", l) \
                or re.match(r"^[a-zà-ÿ0-9]", l) or (l.endswith(".") and not re.search(r"(1[89]|20)\d\d\.$", l)): continue    # a sentence, not a title
        s = l; j = i - 1
        while j >= 0 and ls[j] and not F.TOC_HDR.match(ls[j]) and len(s) < 220 and len(ls[j]) <= 100 and not re.search(r"[.;:]$", ls[j]) and i - j <= 3 and not re.match(r"(?i)(page|\d+$)", ls[j]):
            s = ls[j] + " " + s; j -= 1
        k = i + 1
        while k < len(ls) and ls[k] and len(s) < 220 and len(ls[k]) <= 60 and re.match(r"^(\(?\d{4}\)?\.?|\d{4}\s*(to|-|–)\s*\d{4}|\(No\.?\s*\d+\)|\(Amendment\)|[A-Z(][^.]{0,58}\.?)$", ls[k]) and not F.HEAD.match(ls[k]) and k - i <= 2:
            if re.match(r"(?i)(in\s+exercise|whereas|part|section|article|bye|the\s|this\s|these\s|made|adopted|arrangement|contents|index)", ls[k]): break
            s = s + " " + ls[k]; k += 1
        if c: s = strip_council_prefix(s, c)
        s = re.sub(r"(?i)\s+(arrangement\s+of\s+(the\s+)?(bye[\s\-–]*laws?|sections|articles)|(table\s+of\s+)?contents)\s*$", "", s)
        s = re.sub(r"\s+", " ", s).strip(" .:;-–")[:250]
        s = re.sub(r"(?i)^(as\s+)?follows\s*:\s*", "", s)                       # '… make the following bye-laws as follows: <title>'
        if SENTENCE.search(s) or generic_title(s, c): continue
        return s
    lt = re.sub(r"(?i)\(?\b(pdf|docx?|word)\b\)?|\d+([.,]\d+)?\s?(kb|mb)\b|\bdownload\b|\bsize\b|:", " ", link_text or "")
    lt = re.sub(r"\s+", " ", lt).strip(" -–|")
    filler = re.sub(r"(?i)\b(english|irish|gaeilge|version|leagan|click|here|view|document|file|link)\b", " ", lt)
    if len(lt) >= 8 and len(re.findall(r"[^\W\d_]{2,}", filler)) >= 2: return lt[:250]          # not 'English version', 'click here' 
    seg = [x for x in urllib.parse.unquote(url.split("?")[0]).split("/") if x]
    fn = re.sub(r"[_\-+]+", " ", os.path.splitext(seg[-1] if seg else "")[0]).strip()[:250]
    return fn.title() if fn.islower() else fn

def native_slug(url, sha):
    """native id = the document's path slug on the council site (its file name; for '/media/1979/download' links 'media-1979') + the first
    8 hex of its sha256 (the same file name is reused by several councils / versions)"""
    seg = [x for x in urllib.parse.unquote(url.split("?")[0].split("#")[0]).split("/") if x]
    while len(seg) > 1 and re.fullmatch(r"(?i)download|inline|view|file|preview|content|attachment", seg[-1]): seg = seg[:-1]
    stem = os.path.splitext(seg[-1] if seg else "doc")[0]
    if re.fullmatch(r"\d+", stem) and len(seg) > 1: stem = seg[-2] + "-" + stem       # '/media/1979/download' -> 'media-1979'
    s = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode().lower()).strip("-")[:60].strip("-") or "doc"
    return f"{s}-{sha[:8]}"

def norm(x): return re.sub(r"\W+", " ", unicodedata.normalize("NFKD", x.lower())).strip()

_WT = lambda t: [w for w in re.findall(r"[a-záéíóú]+", t.lower()) if len(w) > 1]
_YR = lambda t: set(re.findall(r"\b(?:19[5-9]\d|20[0-4]\d)\b", t))
_NM = lambda t: collections.Counter(re.findall(r"\b[A-ZÁÉÍÓÚ][a-záéíóú]{2,}\b", t))
def _cnt(w, t): return len(re.findall(r"(?i)\b" + re.escape(w) + r"\b", t))
def distinct_instruments(a, b):
    """True when two near-identical texts are different acts: other years (successive versions), a name that only one of them uses
    (twice or more), or a title word (the harbour / town) that is >= 3 times as frequent in its own text (Rush vs Loughshinny harbour)"""
    if _YR(a["text"]) != _YR(b["text"]): return True
    na, nb = _NM(a["text"]), _NM(b["text"])
    if any(c >= 2 and not nb[w] for w, c in na.items()) or any(c >= 2 and not na[w] for w, c in nb.items()): return True
    for x, y in ((a, b), (b, a)):
        for w in {w.lower() for w in re.findall(r"\b[A-ZÁÉÍÓÚ][\wáéíóú]{2,}\b", x["title"])}:
            cx, cy = _cnt(w, x["text"]), _cnt(w, y["text"])
            if cx >= 3 and cy * 3 <= cx: return True
    return False
def fold_same_act(acts):
    """The same bye-laws published twice in a council (page numbers, ToC spacing or OCR noise differ; titles may differ): word-sequence
    ratio >= 0.95 (numbers ignored), same language and district, and not distinct_instruments. Keep the cleaner text (fewer corpus-rare
    words, then lower garble rate),
    else the existing order; the kept act takes the other's URL and any date it lacks."""
    by = collections.defaultdict(list)
    for a in acts: by[(a["code"], a["lang"], a["md"])].append(a)
    gone = set(); vocab = collections.Counter(w for a in acts for w in set(_WT(a["text"])))
    # OCR noise ('pennit', 'ban ier') = words that are rare across the whole corpus; the copy with fewer of them is the cleaner one
    noise = lambda a: sum(1 for w in _WT(a["text"]) if vocab[w] <= 2) / max(1, len(_WT(a["text"])))
    for xs in by.values():
        for i, a in enumerate(xs):
            for b in xs[i + 1:]:
                if id(a) in gone or id(b) in gone: continue
                wa, wb = _WT(a["text"]), _WT(b["text"])
                if min(len(wa), len(wb)) / max(1, len(wa), len(wb)) < 0.8: continue
                sm = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
                if sm.quick_ratio() < 0.95 or sm.ratio() < 0.95 or distinct_instruments(a, b): continue
                k, d = (a, b) if (noise(a), F.garble_rate(a["text"])) <= (noise(b), F.garble_rate(b["text"])) else (b, a)
                k["alt_urls"] += [d["link"]["url"]] + d["alt_urls"]
                for f in ("adopt", "basis", "com", "amended", "amend_com"):
                    if not k.get(f) and d.get(f): k[f] = d[f]; k.setdefault("filled_from_fold", []).append(f)
                k.setdefault("folded_same_act", []).append(dict(url=d["link"]["url"], ratio=round(sm.ratio(), 3)))
                STATS["folded_same_act"] += 1; DROPS["folded_same_act"].append(dict(url=d["link"]["url"], kept=k["link"]["url"], ratio=round(sm.ratio(), 3)))
                gone.add(id(d))
    return [a for a in acts if id(a) not in gone]
_LW = r"(?i)(translated|translation|irish|version|gae|gaeilge|leagan|ga|as|final|copy|signed|approved|adopted|\d{6,})"
def _slug(u): return re.sub(r"[^a-z]+", " ", re.sub(_LW, " ", urllib.parse.unquote(u.rsplit("/", 1)[-1].rsplit(".", 1)[0]).lower())).strip()
def link_translations(acts):
    """Irish texts and their English originals in the same council: ordered digit tokens (dates, section and schedule numbers, distances)
    match (ratio >= 0.6, or >= 0.5 with near-identical file names), the best partner leads the next by >= 0.05, title years agree, one-to-one.
    The Irish row records translation_of, the English row translations; an undated Irish row takes the partner's dates."""
    num = lambda t: re.findall(r"\d+", t)
    en = [a for a in acts if a["lang"] == "en"]; best = []
    for g in [a for a in acts if a["lang"] == "ga"]:
        ng = num(g["text"]); sc = []
        for e in en:
            if e["code"] != g["code"]: continue
            ne = num(e["text"])
            if min(len(ng), len(ne)) / max(1, len(ng), len(ne)) < 0.5: continue
            yg, ye = set(re.findall(r"\b(?:19|20)\d\d\b", g["title"])), set(re.findall(r"\b(?:19|20)\d\d\b", e["title"]))
            if yg and ye and not yg & ye: continue
            r1 = difflib.SequenceMatcher(None, ng, ne, autojunk=False).ratio(); r2 = difflib.SequenceMatcher(None, _slug(g["link"]["url"]), _slug(e["link"]["url"])).ratio()
            sc.append((0.7 * r1 + 0.3 * r2, r1, r2, e))
        sc.sort(key=lambda x: -x[0])
        if sc and (sc[0][1] >= 0.6 or (sc[0][1] >= 0.5 and sc[0][2] >= 0.9)) and sc[0][0] - (sc[1][0] if len(sc) > 1 else 0) >= 0.05:
            best.append((sc[0][0], g, sc[0][3]))
    used = set()
    for s, g, e in sorted(best, key=lambda x: -x[0]):
        if id(e) in used: continue
        used.add(id(e)); g["translation_of"] = e["lid"]; e.setdefault("translations", []).append(g["lid"]); STATS["translation_pairs"] += 1
        if not g["adopt"] and e["adopt"]:
            g["adopt"], g["basis"], g["prec"] = e["adopt"], "translation_partner_" + (e["basis"] or "date"), e.get("prec"); g.setdefault("dates_from", []).append("adoption_date")
        for f, n in (("com", "commencement_date"), ("amended", "amended_date"), ("amend_com", "amendment_commencement_date")):
            if not g.get(f) and e.get(f): g[f] = e[f]; g.setdefault("dates_from", []).append(n)
_SLUGSTOP = {"signed", "final", "copy", "pdf", "docx", "adopted", "approved", "version", "byelaws", "bye", "laws", "law", "the", "of", "and", "for"}
def disambiguate_titles(acts):
    """Two acts of one council with the same title (Sligo 'PARKING CONTROL BYE LAWS 2021' for Rosses Point and for Mullaghmore): add the
    words that only this act's file name has and its text uses ('… (Rosses Point)')"""
    by = collections.defaultdict(list)
    for a in acts: by[(a["code"], norm(a["title"]))].append(a)
    for xs in by.values():
        if len(xs) < 2: continue
        sl = [set(re.findall(r"[a-z]{3,}", urllib.parse.unquote(a["link"]["url"].rsplit("/", 1)[-1]).lower())) - _SLUGSTOP - set(norm(a["title"]).split()) for a in xs]
        for i, a in enumerate(xs):
            own = sl[i] - set().union(*(sl[:i] + sl[i + 1:]))
            ws = [w for w in re.findall(r"[a-z]{3,}", urllib.parse.unquote(a["link"]["url"].rsplit("/", 1)[-1]).lower()) if w in own and _cnt(w, a["text"])]
            if ws:
                a["title_from"] = a["title"]; a["title"] = f"{a['title']} ({' '.join(dict.fromkeys(w.title() for w in ws))})"; STATS["titles_disambiguated"] += 1
OCR_NOT = re.compile(r"(?i)\b(map|maps|drawing|form|application|notice|advert|draft|proposed|consultation|report|guide|leaflet|poster|sign(age)?|photo)s?\b")
OCR_BL = re.compile(r"(?i)bye[\s\-_–]*laws?|byelaws?|fodhl[ií]the")
def ocr_list(drops, cn):
    """PDFs left out for want of a text layer (scans): the list an OCR pass would start from, if OCR is approved. likely_byelaw = the link
    text / file name names bye-laws, not a map / form / notice / draft, and the scan has >= 2 pages. Text layers that are broken (replacement
    characters, unmapped fonts) are listed separately: OCR would also rescue them."""
    def item(d):
        name = (d.get("link_text") or "") + " " + urllib.parse.unquote(d["url"].rsplit("/", 1)[-1])
        return dict(url=d["url"], municipality=cn[d["code"]][1], municipality_code=d["code"], pages=d.get("pages"), link_text=d.get("link_text"),
                    reason=d["reason"], likely_byelaw=bool(OCR_BL.search(name)) and not OCR_NOT.search(name) and (d.get("pages") or 0) >= 2)
    img = [item(d) for d in drops if d["reason"] == "no_text_layer_scanned"]
    bad = [item(d) for d in drops if d["reason"].startswith("bad_text_layer")]
    cnt = lambda xs: dict(sorted(collections.Counter(x["municipality"] for x in xs).items()))
    return dict(note="Image-only PDFs excluded (no OCR). Not uploaded anywhere; for an OCR pass if approved.", count=len(img),
                likely_byelaw_count=sum(x["likely_byelaw"] for x in img), per_municipality=cnt(img),
                per_municipality_likely_byelaw=cnt([x for x in img if x["likely_byelaw"]]), items=img,
                broken_text_layer=dict(count=len(bad), per_municipality=cnt(bad), items=bad))
def main(B="ie_build", OUT="ireland_municipal"):
    cn = {c[0]: c for c in COUNCILS}
    links = [json.loads(l) for l in open(f"{B}/links.jsonl")]
    fl = {}
    if os.path.exists(f"{B}/fetch_log.jsonl"):
        for l in open(f"{B}/fetch_log.jsonl"): r = json.loads(l); fl[r["url"]] = r
    today = datetime.date.today().isoformat()
    docs = {}
    for l in links:
        r = fl.get(l["url"])
        if not r: STATS["link_not_fetched"] += 1; DROPS["fetch_failures"].append(dict(url=l["url"], code=l["code"], error="not fetched")); continue
        if not r.get("ok"): STATS["fetch_failed"] += 1; DROPS["fetch_failures"].append(dict(url=l["url"], code=l["code"], error=r.get("error"))); continue
        k = (l["code"], r["sha256"])
        if k in docs: docs[k]["alt_urls"].append(l["url"]); STATS["same_file_other_url"] += 1; continue
        docs[k] = dict(link=l, fetch=r, alt_urls=[])
    # HTML pages that carry the full bye-law text (no document link): >= 2 enacting markers and > 4,000 characters of main content
    if os.path.exists(f"{B}/pages.jsonl"):
        sys.path.insert(0, HERE); from ie_common import Polite
        P = Polite(cache=f"{B}/cache")
        for line in open(f"{B}/pages.jsonl"):
            pg = json.loads(line); key = os.path.join(f"{B}/cache", hashlib.sha1((pg["url"] + "#html-only").encode()).hexdigest())
            if not os.path.exists(key + ".json") and not os.path.exists(os.path.join(f"{B}/cache", hashlib.sha1(pg["url"].encode()).hexdigest()) + ".json"):
                STATS["html_page_not_cached"] += 1; continue                      # the build is offline: only pages the crawl stored
            r = P.get(pg["url"], html_only=True)
            if not r or r[0] != 200: continue
            t = F.html_main_text(r[3])
            if len(t) < 4000 or len(F.STRONG.findall(t)) < 2: continue
            h = hashlib.sha256(t.encode()).hexdigest(); fn = f"{B}/docs/{h[:20]}.html.txt"
            if not os.path.exists(fn): os.makedirs(f"{B}/docs", exist_ok=True); open(fn, "w", encoding="utf-8").write(t)
            k = (pg["code"], h)
            if k in docs: continue
            docs[k] = dict(link=dict(code=pg["code"], council=pg["council"], url=pg["url"], link_text=pg.get("title"), page=pg["url"], page_title=pg.get("title")),
                           fetch=dict(url=pg["url"], ok=True, sha256=h, file=os.path.basename(fn), kind="html", bytes=len(t),
                                      retrieved_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")), alt_urls=[])
            STATS["html_pages_with_text"] += 1
    STATS["documents"] = len(docs)
    acts = []
    for (code, sha), d in sorted(docs.items()):
        l = d["link"]; r = d["fetch"]; path = f"{B}/docs/{r['file']}"
        if r.get("bytes", 0) > MAX_BYTES: STATS["excluded_too_large"] += 1; DROPS["text_layer"].append(dict(url=l["url"], code=code, reason="file > 40 MB")); continue
        tc = f"{B}/text/{os.path.basename(path)}.txt"; pc = tc + ".pages"
        if os.path.exists(tc):
            raw = open(tc, encoding="utf-8").read(); ps = open(pc).read().strip() if os.path.exists(pc) else ""; pages = int(ps) if ps else None
        else:
            raw, pages = F.doc_any(path); os.makedirs(f"{B}/text", exist_ok=True)
            open(tc, "w", encoding="utf-8").write(raw); open(pc, "w").write(str(pages or ""))
        ok, why = F.text_quality(raw, pages)
        if not ok: STATS["excluded_" + why] += 1; DROPS["text_layer"].append(dict(url=l["url"], code=code, reason=why, pages=pages, link_text=l.get("link_text"))); continue
        text = F.clean_text(raw)
        if "\ufffd" in text: STATS["excluded_bad_text_layer_replacement_chars"] += 1; DROPS["text_layer"].append(dict(url=l["url"], code=code, reason="bad_text_layer_replacement_chars", pages=pages, link_text=l.get("link_text"))); continue
        title = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", clean_title(l.get("link_text"), text, l["url"], cn[code]))).strip()
        title = re.sub(r"(?i)^(as\s+)?follows\s*:\s*", "", title)                     # '… cited as follows: <title>' 
        kind, why = F.classify(title, text, (l.get("link_text") or "") + " " + urllib.parse.unquote(l["url"].rsplit("/", 1)[-1]), today)
        if kind != "byelaw":
            STATS["excluded_" + why] += 1; DROPS["not_byelaw"].append(dict(url=l["url"], code=code, reason=why, title=title[:160])); continue
        text, seal = F.strip_seal(text)
        if seal: STATS["sealing_block_removed"] += 1
        adopt, basis, com = F.act_dates(title, text, seal, today)
        amended, amend_com = F.amended_dates(text, today); prec = None
        if not adopt:
            lm = F.link_month((l.get("link_text") or "") + " " + urllib.parse.unquote(l["url"].rsplit("/", 1)[-1]).replace("-", " "), today)
            if lm: adopt, basis, prec = lm, "link_text_month", "month"
        organ, md = F.issuing_organ(text)
        ty = re.findall(r"\b(1[89]\d\d|20\d\d)\b", title); ty = ty[-1] if ty else None
        acts.append(dict(code=code, sha=sha, link=l, fetch=r, alt_urls=d["alt_urls"], text=text, title=title, lang=F.language(text), adopt=adopt,
                         basis=basis, com=com, seal=seal, amended=amended, amend_com=amend_com, prec=prec, title_year=ty, organ=organ, md=md, pages=pages, kind=r.get("kind")))
    # identical text within a council: one act; near duplicates (Jaccard >= 0.9, same language): keep the newer, then the longer
    seen = {}; keep = []
    for a in acts:
        k = (a["code"], hashlib.sha256(a["text"].encode()).hexdigest())
        if k in seen: seen[k]["alt_urls"].append(a["link"]["url"]); STATS["folded_identical_text"] += 1; DROPS["folded_identical_text"].append(dict(url=a["link"]["url"], kept=seen[k]["link"]["url"])); continue
        seen[k] = a; keep.append(a)
    by = collections.defaultdict(list)
    for a in keep: a["sh"] = shingles(a["text"]); by[a["code"]].append(a)
    final = []
    for code, xs in by.items():
        xs.sort(key=lambda a: (a["adopt"] or "", a["kind"] == "pdf", len(a["text"])), reverse=True); kept = []
        for a in xs:
            # templated bye-laws of different municipal districts share > 90 % of their text: fold only copies of the same act
            same = lambda x, y: norm(x["title"]) == norm(y["title"]) and x["md"] == y["md"]
            hit = next((k for k in kept if a["lang"] == k["lang"] and same(a, k) and jacc(a["sh"], k["sh"]) >= NEAR_J), None)
            if hit:
                hit["alt_urls"].append(a["link"]["url"]); STATS["folded_near_duplicate"] += 1
                DROPS["folded_near_duplicate"].append(dict(url=a["link"]["url"], kept=hit["link"]["url"], jaccard=round(jacc(a["sh"], hit["sh"]), 3))); continue
            kept.append(a)
        final += kept
    final = fold_same_act(final)
    for a in final: a["lid"] = municipal_law_id("IE", a["code"], native_slug(a["link"]["url"], a["sha"]))
    link_translations(final)
    disambiguate_titles(final)
    rows, arts, ids, hidden = [], [], set(), []
    for a in sorted(final, key=lambda a: (int(a["code"]), a["adopt"] or "", a["sha"])):
        c = cn[a["code"]]; t = a["text"]
        native = native_slug(a["link"]["url"], a["sha"])
        lid = a["lid"]; assert lid not in ids, lid; ids.add(lid)
        recs, info = F.split_articles(t)
        for lab, _, body in recs:
            inner = body.split("\n", 1)[1] if (lab != "0" and "\n" in body) else body
            if len(recs) == 1 or lab == "0" or not re.match(r"(schedule|appendix|annex|explanatory|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|sceideal|aguis)", lab):
                if F.loose_heading_run(inner, info.get("kind")) >= 3: hidden.append((lid, lab))
        cov = sum(len(x[2]) for x in recs) / max(1, len(t.strip())); assert cov >= 0.95, (lid, cov)
        labs = [x[0] for x in recs]; assert len(labs) == len(set(labs)), (lid, "dup labels")
        ex = dict(source_page=a["link"].get("page"), link_text=a["link"].get("link_text"), alt_urls=a["alt_urls"], file_sha256=a["sha"], file_kind=a["kind"],
                  pdf_pages=a["pages"], language=a["lang"], adoption_date=a["adopt"], date_basis=a["basis"], commencement_date=a["com"],
                  date_precision=a.get("prec"), amended_date=a.get("amended"), amendment_commencement_date=a.get("amend_com"),
                  translation_of=a.get("translation_of"), translations=a.get("translations"), dates_from_translation=a.get("dates_from") or None,
                  folded_same_act=a.get("folded_same_act"), title_disambiguated_from=a.get("title_from"),
                  title_year=a["title_year"] if not a["adopt"] else None, issuing_organ=a["organ"], municipal_district=a["md"], sealing_clause=(a["seal"] or None) and a["seal"][:600],
                  article_kind=info.get("kind"), article_marker=info.get("marker"), numbering_gaps=info.get("gaps") or None,
                  article_blocks=info.get("blocks") if info.get("blocks", 0) > 1 else None, council_irish_name=c[2], lgma_code=a["code"])
        ex = {k: v for k, v in ex.items() if v not in (None, [], {})}
        for lab, htitle, body in recs:
            rt = "preamble" if lab == "0" and len(recs) > 1 else ("whole_text" if len(recs) == 1 else ("schedule" if re.match(r"(schedule|appendix|annex|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|sceideal|aguis)", lab) else ("note" if lab.startswith("explanatory") else "article")))
            arts.append(dict(law_id=lid, id=f"{lid}-art-{lab}", title=a["title"], text=body, source_url=a["link"]["url"], document_number=native,
                             article_number=lab, record_type=rt, metadata_json=json.dumps({"heading": htitle} if htitle else {}, ensure_ascii=False)))
        body_name = c[1] + ((f" — {a['md']}" if a["md"].startswith("Borough District") else f" — {a['md']} Municipal District") if a["md"] else "")
        rows.append(dict(id=lid, title=a["title"], text=t, source_url=a["link"]["url"], source_type={"pdf": "official_pdf", "html": "official_html"}.get(a["kind"], "official_document"),
                         jurisdiction=f"IE/{c[1]}", country="Ireland", language=a["lang"], eli=None, date=a["adopt"], date_issued=a["adopt"],
                         retrieved_at=a["fetch"]["retrieved_at"], license=LIC, law_status="unknown", identifier=native, official_identifier=None,
                         article_count=len(recs), json_path=None, metadata_json=json.dumps({"extras": ex}, ensure_ascii=False),
                         jurisdiction_level="municipal", admin_level=6, country_iso="IE", admin1=PROVINCE.get(a["code"]), municipality=c[1],
                         municipality_code=a["code"], source_body=body_name))
        STATS["whole_text_records"] += len(recs) == 1
    if hidden: json.dump(hidden, open(f"{B}/hidden_runs.json", "w"))
    assert not hidden, ("records with >= 3 sequential headings inside", len(hidden), hidden[:5])
    fails = []
    for r in rows:
        try:
            txt = r["text"] + "\n" + r["title"]
            assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd\ue000-\uf8ff\x80-\x9f]", txt), (r["id"], "control / FFFD / PUA / C1")
            assert "(cid:" not in txt, r["id"]
            assert F.garble_rate(r["text"]) <= 50, (r["id"], "garbled text layer")
            assert unicodedata.normalize("NFC", txt) == txt and unicodedata.normalize("NFKC", r["text"]) == r["text"], (r["id"], "not NFC/NFKC")
            assert not F.loose_combining(txt), (r["id"], "loose combining mark")
            assert not F.mixed_tokens(txt), (r["id"], "mixed-script tokens", F.mixed_tokens(txt)[:5])
            assert not F.SIG.search(r["text"]), (r["id"], "signature residue")
            tl = r["text"][-500:]
            assert not F.SEAL.search(tl), (r["id"], "sealing clause at the end", tl[-150:])
            assert r["language"] in ("en", "ga"), r["id"]
            assert not F.TEMPLATE_DATE.search(r["text"]), (r["id"], "template date ('20XX' / '___ day of ___ 20__'): an unmade text")
            assert not r["date"] or "1850-01-01" <= r["date"] <= today, (r["id"], r["date"])
            assert re.fullmatch(r"ie-mun-\d{1,2}-[a-z0-9-]+-[0-9a-f]{8}", r["id"]), r["id"]
        except AssertionError as e: fails.append(e.args[0] if e.args else r["id"])
    if fails: json.dump(fails, open(f"{B}/gate_failures.json", "w"), ensure_ascii=False, default=str)
    assert not fails, (len(fails), fails[:8])
    t = pa.Table.from_pylist(rows, schema=MUNICIPAL_LAWS_SCHEMA); errs = validate_municipal_table(t); assert not errs, errs
    at = pa.Table.from_pylist(arts, schema=RAW_ARTICLES_SCHEMA); assert len(set(at["id"].to_pylist())) == at.num_rows
    cnt = collections.Counter(x["law_id"] for x in arts); assert all(cnt[r["id"]] == r["article_count"] for r in rows)
    os.makedirs(f"{OUT}/data", exist_ok=True); os.makedirs(f"{OUT}/scrapers", exist_ok=True)
    pq.write_table(t, f"{OUT}/data/laws.parquet", compression="zstd"); pq.write_table(at, f"{OUT}/data/articles.parquet", compression="zstd")
    for f in COLLECTORS: shutil.copy(f"{HERE}/{f}", f"{OUT}/scrapers/{f}")
    shutil.copy(f"{os.path.dirname(HERE)}/schema.py", f"{OUT}/scrapers/schema.py")
    files = {}
    for root, _, fs in os.walk(OUT):
        for f in fs:
            p = os.path.join(root, f); rel = os.path.relpath(p, OUT)
            if rel in ("MANIFEST.json", "README.md", "HANDOFF_READY") or "__pycache__" in rel: continue
            files[rel] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    mc = collections.Counter(r["municipality"] for r in rows)
    crawl = json.load(open(f"{B}/crawl_stats.json")) if os.path.exists(f"{B}/crawl_stats.json") else {}
    ex_all = [json.loads(r["metadata_json"])["extras"] for r in rows]
    man = dict(slug="ireland_municipal", country_iso="IE", collectors=list(COLLECTORS),
               built_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), laws_rows=len(rows), articles_rows=len(arts),
               data_file_names=["data/laws.parquet", "data/articles.parquet"],
               municipalities={c[1]: mc.get(c[1], 0) for c in COUNCILS}, skipped_councils={cn[k][1]: v for k, v in SKIP.items()},
               crawl_stats=crawl, language_counts=dict(collections.Counter(r["language"] for r in rows)),
               law_status_counts=dict(collections.Counter(r["law_status"] for r in rows)),
               date_basis_counts=dict(collections.Counter(e.get("date_basis") or "none" for e in ex_all)),
               issuing_organ_counts=dict(collections.Counter(e.get("issuing_organ") for e in ex_all)),
               record_type_counts=dict(collections.Counter(x["record_type"] for x in arts)),
               build_stats=dict(STATS), fetch_failures=DROPS["fetch_failures"], build_dropped_text_layer=DROPS["text_layer"],
               build_dropped_not_byelaw=DROPS["not_byelaw"], build_folded_identical_text=DROPS["folded_identical_text"],
               build_folded_near_duplicate=DROPS["folded_near_duplicate"], build_folded_same_act=DROPS["folded_same_act"],
               translation_pairs=STATS["translation_pairs"], sha256=files,
               id_rule="ie-mun-<LGMA local authority code>-<document file-name slug>-<first 8 hex of the file's sha256> (schema.municipal_law_id)",
               helper_modules={"ie_common.py": "scrapers/ie_common.py (robots.txt matcher, 1 req/s per host, cache, CA bundle); imported by collect_ie_municipal.py",
                               "ie_fixes.py": "scrapers/ie_fixes.py (text layer, cleaning, classification, dates, organ, article splitter); imported by build_ie_municipal.py",
                               "schema.py": "scrapers/schema.py (pinned schemas, validate_municipal_table, municipal_law_id); imported by build_ie_municipal.py"},
               sources=dict(texts="local authority websites (documents linked from the councils' bye-law pages; robots.txt honoured, 1 req/s per host)",
                            codes="LGMA local authority codes (services.localgov.ie)"))
    man["excluded_image_only_pdfs"] = ocr_list(DROPS["text_layer"], cn)
    json.dump(man, open(f"{OUT}/MANIFEST.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(dict(laws=len(rows), articles=len(arts), stats=dict(STATS)), ensure_ascii=False))

if __name__ == "__main__":
    main(*(sys.argv[1:3]))
