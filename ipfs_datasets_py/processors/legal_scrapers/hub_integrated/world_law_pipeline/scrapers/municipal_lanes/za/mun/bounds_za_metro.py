#!/usr/bin/env python3
"""Page-boundary filtering for gazette-borne by-law PDFs (batch 6 fix).
A Provincial Gazette PDF carries many unrelated items (creditors / deceased-estate notices, liquor licences,
other municipalities' notices). trim() keeps only the by-law itself:
  * keeps a publisher cover page (title / APPROVED BY COUNCIL / PROMULGATED) if it is page 0;
  * drops leading non-by-law pages (gazette masthead, CONTENTS, other notices) up to the by-law heading;
  * stops at the first of: signature/authority block (after the by-law has started), a parallel-language
    re-publication header (STAD KAAPSTAD / ISIXEKO SASEKAPA ...), a heading of another gazette item
    (notice to creditors, deceased estate, liquor licence, other municipality, provincial/public notice),
    or a change of PROVINCIAL NOTICE / NOTICE / P.N. / LA number; everything after is dropped.
Returns (text, info) where info records offsets and reasons only (never the dropped text)."""
import re
FF = "\f"
CONTENTS = re.compile(r"(?im)^\s*(?:contents|inhoud)\b|\.{8,}")
COVER = re.compile(r"(?i)\bpromulgated\b|approved by council|amended by council")
FOREIGN = re.compile(r"(?i)notice\s+to\s+creditors|deceased\s+estate|estate\s+late|boedel\s+wyle|liquor\s+licen[cs]e|drankliseni|"
                     r"\bcreditors\b|\bkrediteure\b|^\s*(?:provincial|local authority|public|official|general)\s+notices?\b(?!\s+is\b)|"
                     r"^\s*(?:provinsiale|publieke|amptelike)\s+kennisgewings?\b|"
                     r"^\s*(?!city of )(?!.*\b(?:cape town|johannesburg)\b)[A-Z][A-Z'’\- ]{2,40}\s+(?:LOCAL\s+|DISTRICT\s+)?MUNICIPALITY\b")
TRANSL = re.compile(r"^\s*(?:STAD\s+KAAPSTAD|ISIXEKO\s+SASEKAPA|STAD\s+(?:VAN\s+)?JOHANNESBURG|ISIXEKO\s+SASE\s*GOLI)\b|"
                    r"^\s*(?:KENNISGEWING|ISAZISO)\s*$|^\s*ALGEMENE\s+VERDUIDELIKENDE\s+NOTA\b|^\s*UMTHETHO\s+KAMASIPALA\b")
SIGN = re.compile(r"^\s*(?:(?:ACTING|WAARNEMENDE)\s+)?(?:CITY\s+MANAGER|MUNICIPAL\s+MANAGER|EXECUTIVE\s+MAYOR|SPEAKER|CITY\s+SECRETARY|TOWN\s+CLERK)\s*[,.]?\s*$")
NOTENO = re.compile(r"(?i)^\s*(?:(?:provincial|local\s+authority)\s+notice|p\.\s?n\.|l\.\s?a\.|notice\s+no\.?)\s*(\d{1,6})(?:\s*(?:/|of)\s*((?:19|20)\d\d))?")
SECLINE = re.compile(r"^ {0,20}\d{1,3}[A-Z]?\.?\s{1,14}(?=[A-Z(\"“'‘])")
HEAD = re.compile(r"(?i)by-?\s?laws?|general explanatory note|be it enacted|hereby enacts|council of the city of (?:cape town|johannesburg)")
STOPW = {"city", "of", "cape", "town", "johannesburg", "the", "by", "law", "laws", "bylaw", "and", "to", "for", "amendment", "further", "first"}
STRONG = re.compile(r"(?i)general explanatory note|be it (?:therefore )?enacted|hereby enacts|council of the city of (?:cape town|johannesburg)[^\n]{0,60}(?:enacts|has enacted)")
def _caps(l):
    a = [c for c in l if c.isalpha()]; return bool(a) and sum(c.isupper() for c in a) / len(a) > 0.7
def _words(s): return {w for w in re.findall(r"[a-z]+", s.lower()) if w not in STOPW and len(w) > 2}
def trim(text, title=""):
    pages = text.split(FF); tw = _words(title); ty = (re.findall(r"(?:19|20)\d\d", title) or [""])[-1]
    offs, o = [], 0
    for p in pages: offs.append(o); o += len(p) + 1
    info = {"pages_in": len(pages), "cover_kept": False, "leading_pages_dropped": 0, "start": 0, "end": len(text), "end_reason": "eof", "chars_in": len(text)}
    cover = bool(pages) and len(pages[0]) < 1500 and COVER.search(pages[0]) and not CONTENTS.search(pages[0])
    first = 1 if cover else 0
    # start page: first non-contents page carrying the by-law body proper: an enacting clause / explanatory note, or a
    # title-matching by-law heading together with a section-1 line on that page or the next (notice-only pages are skipped)
    def _hd(s): return bool(s) and HEAD.search(s) and tw and len(tw & _words(s)) >= max(1, (len(tw) + 1) // 2) and (not ty or ty in s or True)
    sp = None
    for i in range(first, len(pages)):
        pg = pages[i]
        if CONTENTS.search(pg) and len(re.findall(r"\.{8,}", pg)) >= 2: continue
        strong = STRONG.search(pg); heads = [ln for ln in pg.splitlines() if _caps(ln.strip()) and _hd(ln.strip()) and not TRANSL.search(ln)]
        sec1 = re.search(r"(?m)^ {0,20}1\.?\s{1,14}[A-Z(\"“]", pg + "\n" + (pages[i + 1] if i + 1 < len(pages) else ""))
        if (strong and heads) or (strong and not tw) or (heads and sec1 and not re.search(r"(?i)notice is hereby given", pg[:pg.find(heads[0]) + 400] if heads else "")):
            sp = i; break
    if sp is None:
        sp = next((i for i in range(first, len(pages)) if STRONG.search(pages[i])), first)
    lines = pages[sp].splitlines(True); li = 0
    anchor = next((j for j, ln in enumerate(lines) if STRONG.search(ln)), len(lines))
    hj = [j for j, ln in enumerate(lines[:anchor + 1]) if _caps(ln.strip()) and _hd(ln.strip()) and not TRANSL.search(ln)]
    if hj:
        li = hj[-1]
        while li > 0 and _caps(lines[li - 1].strip()) and _hd(lines[li - 1].strip()): li -= 1
        for k in range(li - 1, max(-1, li - 5), -1):
            if re.match(r"(?i)^\s*(?:the\s+)?city of (?:cape town|johannesburg)\b", lines[k]): li = k; break
    start = offs[sp] + sum(len(x) for x in lines[:li])
    info["leading_pages_dropped"] = sp - first; info["start_page"] = sp
    # end scan
    pos = start; nsec = 0; noteno = None; seen = 0; end = len(text); reason = "eof"
    for ln in text[start:].splitlines(True):
        s = ln.rstrip("\n"); seen += 1
        if seen > 1:
            if TRANSL.search(s): end, reason = pos, "parallel_language_republication"; break
            if FOREIGN.search(s) and _caps(s.strip()[:80]) and len(s.strip()) < 160: end, reason = pos, "other_gazette_item_heading"; break
        m = NOTENO.match(s)
        if m:
            if noteno is None: noteno = m.group(1)
            elif m.group(1) != noteno: end, reason = pos, "notice_number_change"; break
        if SECLINE.match(s): nsec += 1
        pos += len(ln)
        if nsec and SIGN.match(s): end, reason = pos, "signature_block"; break
    body = text[start:end].rstrip(); sched = None
    if reason == "parallel_language_republication":
        # a schedule printed after the parallel-language texts still belongs to the by-law (e.g. lists of repealed by-laws)
        ms = re.search(r"(?m)^\s*(?:SCHEDULE|BYLAE|ISHEDYULI)\b[^\n]*$", text[end:])
        if ms and ms.group(0).strip().upper().startswith("SCHEDULE") is False:
            ms = re.search(r"(?m)^\s*SCHEDULE\b[^\n]*$", text[end:])
        if ms and not any(FOREIGN.search(l) and _caps(l.strip()[:80]) and len(l.strip()) < 160 for l in text[end:end + ms.start()].splitlines()):
            s0 = end + ms.start(); p2 = s0; e2 = len(text); r2 = "end_of_schedule_eof"
            for ln in text[s0:].splitlines(True):
                t = ln.rstrip("\n")
                if p2 > s0 and FOREIGN.search(t) and _caps(t.strip()[:80]) and len(t.strip()) < 160: e2, r2 = p2, "end_of_schedule_other_gazette_item"; break
                m = NOTENO.match(t)
                if m and noteno and m.group(1) != noteno: e2, r2 = p2, "end_of_schedule_notice_number_change"; break
                p2 += len(ln)
            body = body + "\n\n" + text[s0:e2].rstrip(); sched = {"start": s0, "end": e2, "end_reason": r2}
    info["schedule_after_translations"] = sched
    out = (pages[0] + FF if cover else "") + body
    info.update(cover_kept=bool(cover), start=start, end=end, end_reason=reason, chars_out=len(out), chars_dropped=len(text) - len(out))
    return out, info
