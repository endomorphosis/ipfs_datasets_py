#!/usr/bin/env python3
"""Stage Samburu County Assembly Acts (KE batch 2) into the ipfs_kenya_municipal_laws schema.

Offline: reads $MUNI_STAGE/{records.jsonl,selection.json,ocr_results.jsonl,qid_samburu.json,text/<key>.txt}
written by collect_ke_samburu_muni.py and resolve_ke_samburu_qid.py, and writes to $MUNI_PACK
(data/laws-<shard>.parquet, data/articles-<shard>.parquet, manifests/batch<N>_*.json[l]).

Schema, id scheme and county attribution match stage_ke_counties_muni.py (batch 1):
  law id = "ke-muni-" + slug(FRBR work without /akn/) (+ -x<sha1[:10]> only if lossy),
  article id = <law id>-s-<num>, document_number/article_number = "section <num>".
Kenya Law publishes no Samburu works, so the FRBR work is constructed in the same AKN pattern
(/akn/ke-025/act/<year>/<number>) from the Act's own citation ("No. N of YEAR"); metadata says so.

Section splitting (gazette layout, phone scans): body starts at the enacting clause; running
headers (No. N / year / page / short title / Gazette) and marginal notes (the section headings,
matched against the ARRANGEMENT OF SECTIONS) are removed; sections are taken as a sequential
"N." chain checked against the arrangement (gaps / orphans); the last section is cut at the
first SCHEDULE heading. A law is shipped only if its split is reliable (chain complete and equal
to the arrangement) and its text quality passes; otherwise it goes to drops with the reason.
"""
import difflib, hashlib, json, os, re, sys, unicodedata
from datetime import datetime
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq

STAGE = Path(os.environ["MUNI_STAGE"])
PACK = Path(os.environ["MUNI_PACK"])
SHARD = os.environ.get("KE_SHARD", "00002")
BATCH = os.environ.get("KE_BATCH", "batch2")
HUB_PARENT = os.environ.get("KE_HUB_PARENT", "")
COUNTY_CODE, COUNTY_NAME = "ke-025", "Samburu County"
WORDLIST = Path(os.environ.get("KE_WORDLIST", STAGE / "eng_wordlist.txt"))
SOURCE_TYPE = "samburu_county_assembly_acts"
PUBLISHER = "County Assembly of Samburu"
LICENSE = ("Samburu County Act published by the County Assembly of Samburu (samburuassembly.go.ke). The site "
           "carries only a generic all-rights-reserved copyright footer and no terms of use; enacted written "
           "laws are outside the Copyright Act (Cap. 130) definition of a literary work (s.2), so the texts are "
           "treated as not subject to copyright. Source footer noted in manifests/" + BATCH + "_stage_result.json.")
MIN_LEX = float(os.environ.get("KE_MIN_LEX", "0.80"))      # body lexical share floor
MIN_CONF = float(os.environ.get("KE_MIN_CONF", "80"))      # OCR mean word confidence floor

def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

_CLEAN = re.compile(r"[a-z0-9]+(?:[-/][a-z0-9]+)*")
def law_id(w):
    p = w.replace("/akn/", "")
    s = slug(p)
    if not _CLEAN.fullmatch(p):
        s += "-x" + hashlib.sha1(w.encode("utf-8")).hexdigest()[:10]
    return "ke-muni-" + s

WORDS = set()
if WORDLIST.exists():
    WORDS = {w.strip().lower() for w in WORDLIST.open(encoding="utf-8", errors="ignore") if w.strip()}
def lexical_share(text):
    toks = [t.lower() for t in re.findall(r"[A-Za-z]{3,}", text)]   # same definition as the collector
    if len(toks) < 20 or not WORDS:
        return None
    return round(sum(1 for t in toks if t in WORDS) / len(toks), 3)

def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"[^a-z]+", "", s)

ENACT = re.compile(r"ENACTED\s*b[yv]\s*.{0,14}?(?:County\s*A\w{0,3}s+e?mbly\s*(?:of\s*)?S\w{0,2}mbur\w*|Samburu\s*County\s*A\w*sembly)",
                   re.I | re.S)
ARR = re.compile(r"ARRANGEMENT\s+OF\s+SECTIONS", re.I)
TOC_ENTRY = re.compile(r"^\s*([0-9Il|]{0,2}\d[0-9Il|]{0,2}|[Il|]\d|\d)\s*(?:[-–—~=]+\s*|\.\s+|\s+)(?=[A-Za-z(“\"'])(.+?)\s*$")
SEC = re.compile(r"^\s*(\d{1,3})\s*[.,]\s*(?=[A-Z(“\"'‘a-z])")
SCHED = re.compile(r"^[\W_]{0,4}(?:(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|First|Second|Third|Fourth|Fifth|Sixth)\s*)?"
                   r"(?:SC?HEDULES?|Schedules?)\b(?P<rest>.{0,60})$")
def is_schedule_heading(line):
    m = SCHED.match(line.strip())
    if not m:
        return False
    rest = re.sub(r"\b(?:sections?|s|rule|r|paragraph|para)\b", " ", m.group("rest"))
    return not re.search(r"[a-z]{3,}", rest)
PART = re.compile(r"^\s*PART\s*[IVXL1l]{1,6}\b")
CIT = re.compile(r"No\.?\s*(\d{1,2})\s*of\s*((?:19|20)\d\d)", re.I)
MONTHS = "January February March April May June July August September October November December".split()
DATE_RE = re.compile(r"(\d{1,2}|[Il1]st|[Il1]\d?(?:st|nd|rd|th))\s*(?:st|nd|rd|th)?\s*,?\s*(" + "|".join(MONTHS) + r")\s*,?\s*((?:19|20)\d\d)", re.I)

def parse_date(s):
    s = re.sub(r"(?<=\d)O|O(?=\d)", "0", s)
    s = re.sub(r"(?<=\d{3})[\]|lI]", "1", s)
    s = re.sub(r"\bSuly\b", "July", s)
    m = DATE_RE.search(s)
    if not m:
        return ""
    d = re.sub(r"(st|nd|rd|th)$", "", m.group(1), flags=re.I).replace("I", "1").replace("l", "1")
    try:
        return datetime(int(m.group(3)), MONTHS.index(m.group(2).capitalize()) + 1, int(d)).strftime("%Y-%m-%d")
    except ValueError:
        return ""

def short_title(title):
    t = re.sub(r"^the\s+", "", title, flags=re.I)
    return re.sub(r"\s*\(?Amendment\)?\s*", " Amendment ", re.sub(r",?\s*Act,?\s*\d{4}\s*$", "", t, flags=re.I)).strip()

def is_header(line, st_norm):
    s = line.strip()
    if not s:
        return True
    if re.search(r"\bAct\b", s):          # running headers carry the short title without "Act"; citations keep it
        return False
    if re.fullmatch(r"(?:No\.?\s*\d{1,2}|(?:19|20)\d\d|\d{1,3}|[^\w]{1,4})", s):
        return True
    if re.search(r"Gazette\s+Supplement|Kenya\s+Gazette|GOVERNMENT\s+PRINTER", s, re.I):
        return True
    rest = re.sub(r"No\.?\s*\d{1,2}|(?:19|20)\d\d|\b\d{1,3}\b", " ", s)
    rn = norm(rest)
    if 8 <= len(rn) <= len(st_norm) + 12 and len(s.split()) <= 12:
        r = difflib.SequenceMatcher(None, rn, st_norm).ratio()
        if r >= 0.72:
            return True
    return False

_MAP = str.maketrans({"S": "5", "s": "5", "§": "5", "$": "5", "I": "1", "i": "1", "l": "1", "|": "1", "O": "0", "o": "0"})
def parse_toc(lines):
    toc = {}
    for ln in lines:
        m = TOC_ENTRY.match(ln)
        if not m:
            continue
        tok = m.group(1)
        if len(tok) > 3:
            continue
        n, h = int(tok.translate(_MAP)), m.group(2).strip()
        if not 0 < n <= 400:
            continue
        h = re.sub(r"[\s.,;:©]+$", "", h)
        h = re.sub(r"\s+[A-Z]\.?$|\s*\d+$", "", h).strip()
        if n not in toc and len(norm(h)) >= 3:
            toc[n] = h
    return toc

def similar(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if len(a) >= 6 and a in b and len(a) >= 0.5 * len(b):
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()

def sec_start(line):
    """Section-number candidate at the start of a line -> (num, kind, rest) or None.
    kind: dot ("12. ..."), mapped (OCR letter-for-digit, e.g. "Si." "2i." "I1."), nodot ("54 (1) ..."), bare ("6" / "5.")."""
    s = re.sub(r"^[_\-—–~=|:;'`·•]{1,6}\s*", "", line.strip())
    m = re.match(r"^([0-9SsIil|O§$]{1,3})(\s*[.,]\s*|\s+|$)(.*)$", s)
    if not m:
        return None
    tok, sep, rest = m.group(1), m.group(2), m.group(3).strip()
    if rest and not re.match(r"[A-Z(“\"'‘\[{/]", rest):   # "{" and "/" are OCR readings of "("
        return None
    dot = "." in sep or "," in sep
    if tok.isdigit():
        kind = "dot" if dot and rest else "bare" if not rest else "nodot"
    else:
        if not dot or not rest or not any(c.isdigit() for c in tok) and len(tok) > 1 and tok[0] not in "S§$":
            return None
        kind = "mapped"
    try:
        n = int(tok.translate(_MAP))
    except ValueError:
        return None
    if n == 0:
        return None
    return n, kind, rest

def split_law(text, title):
    st_norm = norm(short_title(title))
    full = text.replace("\f", "\n")
    info = {}
    am = ARR.search(full)
    em = ENACT.search(full)
    info["enacting_clause"] = re.sub(r"\s+", " ", em.group(0)) if em else None
    if not em:
        return None, {**info, "split_error": "no_enacting_clause"}
    toc_lines = full[am.end():em.start()].split("\n") if am and am.start() < em.start() else []
    toc = parse_toc(toc_lines)
    info["toc_entries"] = len(toc)
    body = full[em.end():].split("\n")[1:]
    hdr = [is_header(ln, st_norm) for ln in body]

    def near_heading(i, n, lo=5, hi=5):
        h = toc.get(n)
        if not h:
            return False
        return any(similar(body[j].strip(), h) >= 0.8 for j in range(max(0, i - lo), min(len(body), i + hi + 1))
                   if j != i and body[j].strip() and len(body[j].split()) <= 12)

    # reading-order repair (text layers of phone-captured spreads): the first line of section N+1 placed just before
    # section N ("25. The Fund shall consist of" / "24. Any applicant ...") -> move that line to the end of section N
    # (before the next PART heading / N+1's marginal note / next section line). Logged per law.
    repairs = []
    for _ in range(8):
        cands = [(i, sec_start(ln)) for i, ln in enumerate(body)]
        cands = [(i, c[0]) for i, c in cands if c and c[1] == "dot" and not hdr[i]]
        seen, fixed = set(), False
        for x, (i, a) in enumerate(cands):
            nxt = [(j, b) for j, b in cands[x + 1:x + 3] if j - i <= 4 and b == a - 1]
            if nxt and (a - 2) in seen and (a - 1) not in seen:
                j = nxt[0][0]
                h = toc.get(a, "")
                stop = next((k for k in range(j + 1, min(len(body), j + 60))
                             if PART.match(body[k].strip()) or (h and similar(body[k].strip(), h) >= 0.8 and len(body[k].split()) <= 12)
                             or (sec_start(body[k]) and sec_start(body[k])[0] == a + 1)), None)
                if stop is None:
                    break
                line, hl = body.pop(i), hdr.pop(i)
                stop -= 1
                k2 = stop
                while k2 + 1 < len(body) and (PART.match(body[k2].strip()) is None) and False:
                    k2 += 1
                body.insert(stop, line); hdr.insert(stop, hl)
                repairs.append({"moved_section_start": a, "before_section": a - 1})
                fixed = True
                break
            seen.add(a)
        if not fixed:
            break
    info["reading_order_repairs"] = repairs

    toc_max = max(toc) if toc else None
    chain, gaps, kinds, expected = [], [], {}, 1
    for i, ln in enumerate(body):
        c = sec_start(ln)
        if not c:
            continue
        n, kind, rest = c
        ok = False
        if kind == "dot" and not hdr[i]:
            ok = n == expected or (chain and expected < n <= expected + 2 and (toc_max is None or n <= toc_max))
        elif kind == "mapped" and not hdr[i]:
            ok = n == expected
        elif kind == "nodot":
            ok = n == expected and (rest.startswith("(") or near_heading(i, n))
        elif kind == "bare":
            ok = n == expected and near_heading(i, n)
        if ok and kind != "dot":
            # prefer a regular "N. text" line for the same number just below (bare "7." line, then "7. (1) ...")
            for j in range(i + 1, min(len(body), i + 9)):
                c2 = sec_start(body[j])
                if c2 and c2[0] == n and c2[1] == "dot" and not hdr[j]:
                    ok = False; break
        if ok:
            if n != expected:
                gaps.extend(range(expected, n))
            chain.append((i, n)); kinds[n] = kind; expected = n + 1
            hdr[i] = False
        if toc_max and expected > toc_max:
            break
    # gap repair for a single missing number between found neighbours (flagged as numbers_inferred):
    #  (a) a marginal note matching an arrangement heading, followed within 3 lines by the section's first line;
    #  (b) the standard interpretation opening ("In this Act, unless the context otherwise requires").
    allheads = list(toc.values())
    inferred = []
    for g in list(gaps):
        prev = [i for i, n in chain if n == g - 1]
        nxt = [i for i, n in chain if n == g + 1]
        if not (prev and nxt):
            continue
        hit, how = None, None
        for j in range(prev[0] + 1, nxt[0]):
            if re.match(r"^\s*In\s+this\s+Act\s*,?\s*unless\s+the\s+context", body[j]) and (g <= 3):
                hit, how = j, "interpretation_opening"; break
        if hit is None:
            consistent0 = bool(toc) and toc_max == (chain[-1][1] if chain else None)
            gh = [toc[g]] if consistent0 and g in toc else [] if consistent0 else [toc[g + d] for d in range(-2, 10) if (g + d) in toc]
            for j in range(prev[0] + 1, nxt[0]):
                sj = body[j].strip()
                if not gh or not sj or hdr[j] or len(sj.split()) > 12 or sec_start(sj):
                    continue
                if max(similar(sj, h) for h in gh) >= 0.85:
                    for k2 in range(j + 1, min(nxt[0], j + 4)):
                        sk = body[k2].strip()
                        if (sk and not hdr[k2] and max((similar(sk, h) for h in allheads), default=0) < 0.8 and len(sk.split()) >= 4
                                and not re.match(r"^(?:No\.?|Cap\.?|L\.?N\.?)\s*\d", sk)):
                            hit, how = k2, "marginal_note"; break
                    if hit is not None:
                        break
        if hit is not None:
            chain.append((hit, g)); kinds[g] = "inferred_" + how; inferred.append(g); gaps.remove(g)
    chain.sort()
    info["chain_gaps"] = gaps
    info["numbers_inferred"] = inferred
    info["start_kinds"] = {k: sum(1 for v in kinds.values() if v == k) for k in sorted(set(kinds.values()))}
    if not chain:
        return None, {**info, "split_error": "no_sections"}
    if [n for _, n in chain] != sorted(n for _, n in chain):
        info["order_violation"] = True
    end = len(body)
    for j in range(chain[-1][0] + 1, len(body)):
        if is_schedule_heading(body[j]):
            end = j; break
    info["schedule_cut_line"] = end if end < len(body) else None
    drop = {j for j in range(len(body)) if hdr[j]}
    nchain = [n for _, n in chain]
    consistent = bool(toc) and toc_max == (nchain[-1] if nchain else None)
    info["arrangement_numbering_consistent"] = consistent if toc else None
    heads, head_src = {}, {}

    def window(k):
        i = chain[k][0]
        lo = chain[k - 1][0] + 1 if k else 0
        hi = chain[k + 1][0] if k + 1 < len(chain) else end
        before = list(range(i - 1, max(lo, i - 6) - 1, -1))          # nearest first
        after = [j for j in range(i + 1, min(hi, i + 4)) if j < hi - 2 or hi - i > 6]
        return [j for j in before + after if body[j].strip() and len(body[j].split()) <= 12 and not sec_start(body[j])], lo, hi

    def verified(k, h):
        js, lo, hi = window(k)
        for j in js:
            if similar(body[j].strip(), h) >= 0.8:
                return j
        return None

    for k, (i, n) in enumerate(chain):
        _, lo, hi = window(k)
        offsets = (0,) if consistent else (0, 1, -1)
        bh, bj = None, None
        for d in offsets:
            h = toc.get(n + d)
            if h:
                j = verified(k, h)
                if j is not None:
                    bh, bj = h, j
                    break
        if bh:
            heads[n], head_src[n] = bh, ("arrangement_verified_by_marginal_note" if bj is not None else "arrangement")
            drop.add(bj)
            if bj + 1 < hi and bj + 1 != i:
                s2 = body[bj + 1].strip()
                if s2 and len(s2.split()) <= 6 and not s2.startswith("(") and similar(body[bj].strip() + " " + s2, bh) > max(0.85, similar(body[bj].strip(), bh)):
                    drop.add(bj + 1)
            if bj - 1 >= lo and bj - 1 != i:
                s0 = body[bj - 1].strip()
                if s0 and len(s0.split()) <= 6 and not s0.startswith("(") and not re.search(r"[.;:]$", s0) and similar(s0 + " " + body[bj].strip(), bh) > max(0.85, similar(body[bj].strip(), bh)):
                    drop.add(bj - 1)
        elif consistent and n in toc:
            heads[n], head_src[n] = toc[n], "arrangement"
    if toc and not consistent and chain:
        last_h = toc.get(toc_max, "")
        info["arrangement_last_heading_verified_in_last_body_sections"] = any(
            verified(k, last_h) is not None for k in range(max(0, len(chain) - 3), len(chain)))
    info["heading_sources"] = {v: sum(1 for x in head_src.values() if x == v) for v in set(head_src.values())}
    for j, ln in enumerate(body[:end]):
        sj = ln.strip()
        letters = re.sub(r"[^A-Za-z]", "", sj)
        if PART.match(sj) or (len(letters) >= 3 and letters.isupper() and len(sj.split()) <= 10):
            drop.add(j)
    info["header_lines_removed"] = sum(1 for j in range(end) if hdr[j])
    info["marginal_or_heading_lines_removed"] = len(drop) - info["header_lines_removed"]
    secs, trailing_removed = [], []
    for k, (i, n) in enumerate(chain):
        hi = chain[k + 1][0] if k + 1 < len(chain) else end
        lines_ = [body[j] for j in range(i, hi) if j not in drop or j == i]
        # trailing marginal notes / stray fragments: short lines (<= 6 words, not list items) after the last line
        # that ends a sentence or clause are removed (earliest such line, so the whole trailing block goes)
        nz = [x for x in range(len(lines_)) if lines_[x].strip()]

        def frag(t):
            letters = re.sub(r"[^A-Za-z]", "", t)
            return (len(t.split()) <= 6 and not t.startswith(("(", '"', "\u201c", "'", "\u2018"))
                    and (t[0].isupper() or t[0].isdigit() or len(letters) <= 3))

        def ends(t):
            return bool(re.search(r"[.;:\u201d\"]\s*$", t))
        bs = len(nz)
        while bs - 1 >= 1 and frag(lines_[nz[bs - 1]].strip()):
            bs -= 1
        while bs < len(nz) and not ends(lines_[nz[bs - 1]].strip()):
            bs += 1
        if bs < len(nz):
            trailing_removed.append((n, [lines_[y].strip() for y in nz[bs:]]))
            lines_ = lines_[:nz[bs - 1] + 1]
        chunk = "\n".join(lines_).strip()
        chunk = re.sub(r"\n{3,}", "\n\n", chunk)
        if kinds.get(n) != "dot":   # normalise the start so the text opens "N. "
            first, _, restc = chunk.partition("\n")
            c = sec_start(first)
            first = f"{n}. " + (c[2] if c else re.sub(r"^[\W_]{0,4}[0-9SsIil|O§$]{1,3}\s*[.,]\s*", "", first.strip()))
            if first.strip() == f"{n}." and restc.strip():          # bare number line: join the next line
                nxt_, _, restc = restc.lstrip("\n").partition("\n")
                first = f"{n}. " + nxt_.strip()
            chunk = (first.rstrip() + ("\n" + restc if restc else "")).strip()
        h = heads.get(n) or re.sub(r"^\S+\s*", "", chunk.split("\n", 1)[0]).strip()[:120]
        if n not in heads:
            head_src[n] = "first_line"
        secs.append({"num": str(n), "title": f"{n}. {h}"[:200], "text": chunk})
    info["trailing_fragment_lines_removed"] = sum(len(c) for _, c in trailing_removed)
    info["trailing_fragments"] = [{"section": n_, "lines": c} for n_, c in trailing_removed]
    tot_lines = garb_lines = 0
    for s_ in secs:
        s_["lexical_share"] = lexical_share(s_["text"])
        g = []
        for ln in s_["text"].split("\n"):
            toks = [t.lower() for t in re.findall(r"[A-Za-z]{3,}", ln)]
            if len(toks) >= 3 and WORDS:
                tot_lines += 1
                if sum(1 for t in toks if t in WORDS) / len(toks) < 0.5:
                    g.append(ln.strip())
        s_["garbled_lines"] = g
        garb_lines += len(g)
    info["line_count_scored"] = tot_lines
    info["garbled_lines"] = garb_lines
    info["garbled_line_share"] = round(garb_lines / tot_lines, 4) if tot_lines else None
    # a section is flagged degraded when >= 2 of its lines are garbled (< 50 % dictionary words) or its lexical share < 0.75
    info["degraded_sections"] = [{"section": s_["num"], "lexical_share": s_["lexical_share"], "garbled_lines": len(s_["garbled_lines"])}
                                 for s_ in secs if len(s_["garbled_lines"]) >= 2 or (s_["lexical_share"] is not None and s_["lexical_share"] < 0.75)]
    for s_ in secs:
        s_.pop("garbled_lines", None)
    nums = [int(s["num"]) for s in secs]
    info["contiguous_1_to_n"] = nums == list(range(1, len(nums) + 1))
    info["last_section"] = nums[-1] if nums else None
    info["toc_max"] = toc_max
    info["toc_missing_in_body"] = sorted(set(toc) - set(nums)) if consistent else []
    info["toc_entries_missing_ocr"] = sorted(set(range(1, (toc_max or 0) + 1)) - set(toc))
    info["empty_sections"] = [s["num"] for s in secs if len(re.sub(r"^\s*\d+\s*[.,]", "", s["text"]).strip()) < 15]
    return secs, info

def main():
    recs = [json.loads(l) for l in open(STAGE / "records.jsonl")]
    recs = {r["key"]: r for r in recs if r.get("http_status") == 200 and r.get("key")}
    sel = json.load(open(STAGE / "selection.json"))
    ocr = {}
    for l in open(STAGE / "ocr_results.jsonl"):
        o = json.loads(l); ocr[o["key"]] = o
    qid = json.load(open(STAGE / "qid_samburu.json"))
    assert qid.get("accepted") and qid["qid"], "QID not accepted"
    QID = qid["qid"]
    mcols = {"municipality_id": COUNTY_CODE, "municipality_name": COUNTY_NAME, "wikidata_qid": QID}
    laws, arts, drops, per_law = [], [], [], []
    for k in sel["keep"]:
        key = hashlib.sha1(k["url"].encode()).hexdigest()[:12]
        r = recs.get(key) or next((x for x in recs.values() if x["url"] == k["url"]), None)
        if r is None:
            drops.append({"url": k["url"], "list_title": k["title"], "reason": "not_fetched"}); continue
        text = (STAGE / "text" / f"{r['key']}.txt").read_text(encoding="utf-8")
        head = text[:6000]
        title = re.sub(r"^the\s+", "", k["title"].strip(), flags=re.I)
        title = re.sub(r"\s*,?\s*((?:19|20)\d\d)\s*$", r", \1", title)
        if re.search(r"\bAmendment\b", title) and re.search(r"\(\s*Amendment\s*\)", text[:8000]):
            title = re.sub(r"\s*\bAmendment\b\s*", " (Amendment) ", title).replace("  ", " ")   # the Act's own short title
        cm = CIT.search(head)
        o = ocr.get(r["key"], {})
        secs, info = split_law(text, k["title"])
        maker_ok = bool(info.get("enacting_clause"))
        if not cm:
            drops.append({"url": k["url"], "list_title": k["title"], "key": r["key"], "reason": "no_citation"}); continue
        num, year = int(cm.group(1)), int(cm.group(2))
        ty = re.search(r"((?:19|20)\d\d)\s*$", title)
        work = f"/akn/{COUNTY_CODE}/act/{year}/{num}"
        lid = law_id(work)
        am = re.search(r"Date\w?\s*of\s*Assent\s*[:;.]?\s*(.{0,40})", head, re.I)
        cmn = re.search(r"Date\w?\s*of\s*Commencement\s*[:;.]?\s*(.{0,60})", head, re.I)
        gz = re.search(r"NAIROBI\s*,?\s*(.{0,30})", head)
        assent = parse_date(am.group(1)) if am else ""
        gazette = parse_date(gz.group(1)) if gz else ""
        body_txt = "\n".join(s["text"] for s in (secs or []))
        lex_body = lexical_share(body_txt) if body_txt else None
        kept = {int(p) for p, c in (o.get("garbled_page_choice") or {}).items() if c == "text_layer_kept"}
        ocr_pages = [p for p in (o.get("ocr_pages") or []) if p not in kept]
        backend = "pdf_text_layer" if not ocr_pages else ("tesseract_ocr" if len(ocr_pages) == r["pages"] else "pdf_text_layer+tesseract_ocr")
        q = {"key": r["key"], "id": lid, "title": title, "doc_kind": r["doc_kind"], "pages": r["pages"],
             "text_backend": backend, "ocr_pages": len(ocr_pages), "ocr_mean_conf": o.get("ocr_mean_conf"),
             "ocr_hi_conf_share": o.get("ocr_hi_conf_share"), "ocr_lexical_share": o.get("ocr_lexical_share"),
             "text_layer_lexical_share_doc": lexical_share(text), "body_lexical_share": lex_body,
             "sections": len(secs or []), **{x: info.get(x) for x in ("toc_entries", "toc_max", "last_section", "chain_gaps",
             "numbers_inferred", "start_kinds", "reading_order_repairs", "trailing_fragment_lines_removed", "trailing_fragments", "line_count_scored", "garbled_lines", "garbled_line_share", "degraded_sections", "arrangement_numbering_consistent",
             "arrangement_last_heading_verified_in_last_body_sections", "heading_sources", "toc_missing_in_body", "toc_entries_missing_ocr", "empty_sections", "schedule_cut_line",
             "header_lines_removed", "marginal_or_heading_lines_removed", "split_error")}}
        reasons = []
        if not maker_ok:
            reasons.append("maker_unconfirmed:no_enacting_clause_of_County_Assembly_of_Samburu")
        if ty and int(ty.group(1)) != year:
            reasons.append(f"title_year_{ty.group(1)}_ne_citation_year_{year}")
        if not secs:
            reasons.append("split_failed:" + str(info.get("split_error")))
        else:
            if info["chain_gaps"] or not info["contiguous_1_to_n"]:
                reasons.append(f"split_unreliable:chain_gaps={info['chain_gaps']}")
            if info["toc_max"] and info["last_section"] != info["toc_max"] and not info.get("arrangement_last_heading_verified_in_last_body_sections"):
                reasons.append(f"split_unreliable:last_section={info['last_section']}!=arrangement_max={info['toc_max']}")
            if info["toc_missing_in_body"]:
                reasons.append(f"split_unreliable:arrangement_numbers_missing_in_body={info['toc_missing_in_body']}")
            if info["empty_sections"]:
                reasons.append(f"empty_sections={info['empty_sections']}")
        if lex_body is not None and lex_body < MIN_LEX:
            reasons.append(f"text_degraded:body_lexical_share={lex_body}<{MIN_LEX}")
        if o.get("ocr_mean_conf") is not None and o["ocr_mean_conf"] < MIN_CONF:
            reasons.append(f"ocr_low_confidence:mean_conf={o['ocr_mean_conf']}<{MIN_CONF}")
        q["flags"] = reasons
        q["shipped"] = not reasons
        per_law.append(q)
        if reasons:
            drops.append({"url": k["url"], "list_title": k["title"], "key": r["key"], "id": lid, "frbr_work": work,
                          "reason": "; ".join(reasons),
                          "quality": {"doc_kind": r["doc_kind"], "pages": r["pages"], "garbled_layer_pages": o.get("garbled_layer_pages") or [],
                                      "ocr_page_metrics": o.get("page_metrics") or [], "sections_found": len(secs or []),
                                      "arrangement_max": info.get("toc_max")}}); continue
        meta = {"schema_version": "collection_record.v1", "record_type": "law", "law_identifier": lid,
                "frbr_work": work, "citation": f"Act No. {num} of {year}", "display_type": "pdf",
                "pdf_url": r["url"], "pdf_bytes": r["bytes"], "commenced": parse_date(cmn.group(1)) if cmn else "",
                "text_backend": backend, "no_text_layer": r["doc_kind"] == "scan_no_text_layer", "error": None,
                "admin_level": "county", "publisher": PUBLISHER,
                "frbr_work_constructed": True,
                "frbr_note": "Kenya Law has no Samburu County works; work URI constructed in the Kenya Law AKN pattern from the Act's citation",
                "date_of_assent": assent, "gazette_date": gazette, "pdf_sha256": r["sha256"],
                "pdf_producer": r.get("producer"), "doc_kind": r["doc_kind"], "listing_title": k["title"],
                "listing_url": sel["listing_url"], "enacting_clause": info["enacting_clause"],
                "ocr_quality": {**{x: q[x] for x in ("ocr_pages", "ocr_mean_conf", "ocr_hi_conf_share", "ocr_lexical_share", "body_lexical_share")},
                                "garbled_line_share": info.get("garbled_line_share"), "degraded_sections": info.get("degraded_sections") or []},
                "split": {x: info.get(x) for x in ("numbers_inferred", "reading_order_repairs", "arrangement_numbering_consistent", "toc_max", "last_section")},
                "toc_entries": info["toc_entries"], "parser": "ke_samburu_gazette_v1"}
        d = assent or gazette
        laws.append({"id": lid, "title": title, "text": text, "source_url": r["url"], "source_type": SOURCE_TYPE,
                     "jurisdiction": "KE", "country": "Kenya", "language": "en", "eli": work, "date": d, "date_issued": d,
                     "retrieved_at": r["retrieved_at"], "license": LICENSE, "law_status": "current",
                     "identifier": f"Act No. {num} of {year}", "official_identifier": work,
                     "article_count": len(secs), "json_path": "", "metadata_json": json.dumps(meta, ensure_ascii=False), **mcols})
        for s in secs:
            n = s["num"]
            arts.append({"law_id": lid, "id": f"{lid}-s-{slug(n)}"[:200], "title": s["title"], "text": s["text"],
                         "source_url": r["url"], "document_number": f"section {n}", "article_number": f"section {n}",
                         "record_type": "article", "metadata_json": json.dumps({"law_identifier": lid, "kind": "section"}), **mcols})
    # express repeal check: a clause in any staged Act that repeals another staged Act by name
    repeals = []
    for l in laws:
        for m in re.finditer(r"([A-Z][^.;\n]{5,160}?Act,?\s*(?:19|20)\d\d)[^.;]{0,40}?\b(?:is|are)\s+(?:hereby\s+)?repealed", l["text"].replace("\n", " ")):
            named = norm(m.group(1))
            for t in laws:
                if t is not l and norm(t["title"]) and norm(t["title"]) in named:
                    repeals.append({"repealing": l["id"], "repealed": t["id"], "clause": m.group(0)[:300]})
    for rp in repeals:
        for t in laws:
            if t["id"] == rp["repealed"]:
                t["law_status"] = "repealed"
    # partial express repeals (a section of another staged Act) and amendments are recorded; law_status stays "current"
    partial, amends = [], []
    for l in laws:
        flat = re.sub(r"\s+", " ", l["text"])
        for m in re.finditer(r"rep[a-z]?als?\s+(sections?\s+[0-9A-Za-z, ()]+?)\s+of\s+the\s+([A-Z][^.;]{5,160}?Act,?\s*(?:19|20)\d\d)", flat, re.I):
            named = norm(m.group(2))
            for t in laws:
                if t is not l and norm(t["title"]) and norm(t["title"]) in named:
                    partial.append({"repealing": l["id"], "target": t["id"], "provision": m.group(1).strip(), "clause": m.group(0)[:300]})
        if re.search(r"\(\s*Amendment\s*\)", l["title"]):
            m = re.search(r"Act\s*No\.?\s*([0-9Il]{1,2})\s*of\s*((?:19|20)\d\d)", flat)
            if m:
                tgt = f"/akn/{COUNTY_CODE}/act/{m.group(2)}/{int(m.group(1).replace('I', '1').replace('l', '1'))}"
                amends.append({"amending": l["id"], "target_work": tgt, "target": next((t["id"] for t in laws if t["eli"] == tgt), None)})
    for rp in partial:
        for t in laws:
            if t["id"] == rp["target"]:
                md = json.loads(t["metadata_json"]); md.setdefault("express_partial_repeals", []).append({k: rp[k] for k in ("repealing", "provision")})
                t["metadata_json"] = json.dumps(md, ensure_ascii=False)
    for am in amends:
        for t in laws:
            if t["id"] == am["target"]:
                md = json.loads(t["metadata_json"]); md.setdefault("amended_by", []).append(am["amending"])
                t["metadata_json"] = json.dumps(md, ensure_ascii=False)
    ids = [l["id"] for l in laws]
    assert len(ids) == len(set(ids)), "duplicate law ids"
    assert len({l["eli"] for l in laws}) == len(laws), "duplicate FRBR works"
    aids = [a["id"] for a in arts]
    assert len(aids) == len(set(aids)), "duplicate article ids"
    assert all(a["law_id"] in set(ids) for a in arts), "orphan articles"
    LAW_COLS = ["id", "title", "text", "source_url", "source_type", "jurisdiction", "country", "language", "eli", "date",
                "date_issued", "retrieved_at", "license", "law_status", "identifier", "official_identifier", "article_count",
                "json_path", "metadata_json", "municipality_id", "municipality_name", "wikidata_qid"]
    ART_COLS = ["law_id", "id", "title", "text", "source_url", "document_number", "article_number", "record_type",
                "metadata_json", "municipality_id", "municipality_name", "wikidata_qid"]
    (PACK / "data").mkdir(parents=True, exist_ok=True)
    (PACK / "manifests").mkdir(parents=True, exist_ok=True)
    lt = pa.Table.from_pylist(laws, schema=pa.schema([(c, pa.int32() if c == "article_count" else pa.string()) for c in LAW_COLS]))
    at = pa.Table.from_pylist(arts, schema=pa.schema([(c, pa.string()) for c in ART_COLS]))
    lp, ap = PACK / "data" / f"laws-{SHARD}.parquet", PACK / "data" / f"articles-{SHARD}.parquet"
    pq.write_table(lt, lp, compression="zstd")
    pq.write_table(at, ap, compression="zstd")
    with open(PACK / "manifests" / f"{BATCH}_drops.jsonl", "w") as f:
        for d in drops:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    with open(PACK / "manifests" / f"{BATCH}_listing_exclusions.jsonl", "w") as f:
        for e in sel["excluded"]:
            f.write(json.dumps({x: e.get(x) for x in ("listing_ordinal", "title", "url", "reason")}, ensure_ascii=False) + "\n")
    res = {"batch": BATCH, "shard": SHARD, "hub_parent": HUB_PARENT, "county": {"municipality_id": COUNTY_CODE,
           "municipality_name": COUNTY_NAME, "wikidata_qid": QID, "qid_route": qid.get("route")},
           "source": {"listing_url": sel["listing_url"], "listing_sha256": sel["listing_sha256"],
                      "document_links": sel["document_links"], "kept": len(sel["keep"]), "excluded": len(sel["excluded"]),
                      "licence_observation": "site footer is a generic all-rights-reserved copyright notice; no terms-of-use page found"},
           "laws_rows": lt.num_rows, "articles_rows": at.num_rows, "drops": len(drops), "municipalities": 1,
           "laws_zero_articles": sum(1 for l in laws if l["article_count"] == 0),
           "express_repeals": repeals, "express_partial_repeals": partial, "amendments": amends, "law_status_counts": {s: sum(1 for l in laws if l["law_status"] == s) for s in {l["law_status"] for l in laws}},
           "quality": {"min_body_lexical_share": MIN_LEX, "min_ocr_mean_conf": MIN_CONF, "per_law": per_law},
           "frbr_work_note": "constructed /akn/ke-025/act/<year>/<no> from each Act's citation; Kenya Law has no Samburu works"}
    for p in (lp, ap):
        res[f"data/{p.name}"] = {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    (PACK / "manifests" / f"{BATCH}_stage_result.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps({x: res[x] for x in ("laws_rows", "articles_rows", "drops", "express_repeals", "express_partial_repeals", "amendments")}, indent=1))
    for q in per_law:
        print(q["key"], q["sections"], q["toc_max"], q["toc_entries"], q["chain_gaps"], q["numbers_inferred"], q["start_kinds"],
              q["empty_sections"], q["body_lexical_share"], q["flags"], q["title"][:45])

if __name__ == "__main__":
    main()
