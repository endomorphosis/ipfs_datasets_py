#!/usr/bin/env python3
"""Page-boundary filtering for provincial Act PDFs (ported from ZA metro batch-6 bounds_za_metro.py).
A Provincial Gazette / legislature PDF can carry the cover, a promulgation notice, parallel Afrikaans / isiXhosa / isiZulu
texts and unrelated gazette items. trim() keeps only the English text of the Act itself:
  * per-page language score (English vs Afrikaans vs Nguni function words); non-English pages are never kept;
  * start = first English page carrying the Act masthead ('... ACT, <year>' / 'ACT No. n of <year>') or an enacting clause
    ('BE IT ENACTED ...'); leading cover / contents / notice pages are dropped (counted, never quoted);
  * stop at the first of: a non-English page after the Act started (parallel-language text), a heading of another gazette item
    (notice to creditors, deceased estate, liquor licence, other provincial / general notice), a change of PROVINCIAL NOTICE /
    P.N. number, or eof.
Returns (text, info); info records offsets, page counts and reasons only (never dropped text)."""
import re
FF = "\f"
EN = set("the of and to in is or be by for shall any this that with act section may such which person under an are as".split())
AF = set("die van en word vir met wat hierdie artikel moet deur kan nie enige persoon ingevolge wet sal ook".split())
NG = set("ukuthi kanye noma umthetho lo uma ngokwe isigaba kufanele ukuba kwe yi nga oku uku le ka isahluko".split())
def lang(page):
    w = re.findall(r"[a-z]+", page.lower()); e = sum(x in EN for x in w); a = sum(x in AF for x in w)
    n = sum(x in NG for x in w) + sum(1 for x in w if len(x) > 6 and x.startswith(("uku", "oku", "nge", "kwa", "ngo", "eku")))
    tot = e + a + n
    if tot < 12: return "neutral", round(e / tot, 2) if tot else None
    r = e / tot
    return ("en" if r >= 0.6 else "other"), round(r, 2)
CONTENTS = re.compile(r"(?im)^\s*(?:contents|inhoud|arrangement of sections)\b")
MAST = re.compile(r"(?m)^\s*(?:[A-Z][A-Z\-’',()& ]{3,120}\s+ACT,?\s+(?:19|20)\d\d\s*$|(?:THE\s+)?CONSTITUTION\s+OF\s+THE\s+(?:PROVINCE\s+OF\s+)?(?:WESTERN\s+CAPE|KWAZULU-NATAL),?\s+(?:19|20)\d\d\s*$|\(?ACT\s+NO\.?\s*\d{1,3}\s+OF\s+(?:19|20)\d\d\)?\s*$)")
ENACT = re.compile(r"(?i)be\s+it\s+(?:therefore\s+)?enacted")
FOREIGN = re.compile(r"(?i)notice\s+to\s+creditors|deceased\s+estate|estate\s+late|boedel\s+wyle|liquor\s+licen[cs]e|drankliseni|"
                     r"^\s*(?:general|local authority|public|official)\s+notices?\b(?!\s+is\b)|^\s*(?:provinsiale|algemene)\s+kennisgewings?\b")
NOTENO = re.compile(r"(?i)^\s*(?:provincial\s+notice|p\.\s?n\.|notice\s+no\.?)\s*(\d{1,6})(?:\s*(?:/|of)\s*((?:19|20)\d\d))?")
def _caps(l):
    a = [c for c in l if c.isalpha()]; return bool(a) and sum(c.isupper() for c in a) / len(a) > 0.7
def trim(text, title=""):
    pages = text.split(FF); offs, o = [], 0
    for p in pages: offs.append(o); o += len(p) + 1
    langs = [lang(p) for p in pages]
    info = {"pages_in": len(pages), "lang_pages": {k: sum(1 for x, _ in langs if x == k) for k in ("en", "other", "neutral")},
            "leading_pages_dropped": 0, "start": 0, "end": len(text), "end_reason": "eof", "chars_in": len(text)}
    sp = None
    for i, p in enumerate(pages):
        if langs[i][0] == "other": continue
        if CONTENTS.search(p) and len(re.findall(r"\.{6,}", p)) >= 2: continue
        if MAST.search(p) or ENACT.search(p): sp = i; break
    if sp is None:
        sp = next((i for i, (l, _) in enumerate(langs) if l == "en"), None)
        if sp is None:
            info.update(start=0, end=0, end_reason="no_english_page", chars_out=0, chars_dropped=len(text)); return "", info
    lines = pages[sp].splitlines(True); m = MAST.search(pages[sp]); li = 0
    if m:
        ln_i = pages[sp][:m.start()].count("\n")
        li = ln_i
        while li > 0 and _caps(lines[li - 1].strip()) and lines[li - 1].strip() and len(lines[li - 1].strip()) < 120 and \
                not re.search(r"(?i)gazette|koerant|notice|kennisgewing|extraordinary|buitengewone", lines[li - 1]): li -= 1
    start = offs[sp] + sum(len(x) for x in lines[:li])
    info["leading_pages_dropped"] = sp; info["start_page"] = sp
    end, reason, noteno, ep = len(text), "eof", None, sp
    for i in range(sp, len(pages)):
        if i > sp and langs[i][0] == "other":
            end, reason = offs[i], "parallel_language_page"; break
        pos = offs[i] if i > sp else start; stop = False
        for ln in text[pos:offs[i] + len(pages[i])].splitlines(True):
            s = ln.rstrip("\n")
            if pos > start and FOREIGN.search(s) and _caps(s.strip()[:80]) and len(s.strip()) < 160:
                end, reason, stop = pos, "other_gazette_item_heading", True; break
            mm = NOTENO.match(s)
            if mm:
                if noteno is None: noteno = mm.group(1)
                elif mm.group(1) != noteno: end, reason, stop = pos, "notice_number_change", True; break
            pos += len(ln)
        ep = i
        if stop: break
    out = text[start:end].rstrip()
    info.update(start=start, end=end, end_reason=reason, end_page=ep, chars_out=len(out), chars_dropped=len(text) - len(out))
    return out, info
