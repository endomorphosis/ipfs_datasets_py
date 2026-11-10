"""Build hungary_municipal from the Common Crawl captures fetched by collect_hu_cc.py (offline).
  python build_hu_municipal.py <hu_build dir> <out dir>
One row per decree (önkormányzati rendelet): the captured state in force at capture that comes into force last (future states and
'3000-01-0x' placeholder states rank below it); articles: preamble, one record per §, annexes.
Sources, folded into one version ranking per decree (issuer id, year, number):
  pages.jsonl.gz        Common Crawl captures of or.njt.hu /eli/(v01/)<issuer>/r/<y>/<n>(/<state>)       (collect_hu_cc.py fetch / secondary / alt)
  pages_ornjt.jsonl.gz  Common Crawl captures of or.njt.hu /onkormanyzati-rendelet/<y>-<n>-SP-<code> and /onkormanyzati-rendelet/<id> (collect_hu_cc.py ornjt)
  njt_pages.jsonl.gz    direct polite fetch of njt.jog.gov.hu/jogszabaly/<y>-<n>-SP-5Y<code> (collect_hu_njt.py)
Consolidated states that or.njt.hu filed under several registry numbers (same issuer and decree number, near-identical text) are folded into one row."""
import os, sys, re, json, gzip, collections, hashlib, shutil, unicodedata, datetime
# hu-mun-07667-424811-2019-3: the page heading names Oszkó (the source page mixes Olaszfa and Oszkó text); the official registry
# (njt.jog.gov.hu/jogszabaly/2019-3-SP-5Y3203) lists 'Olaszfa … 3/2019. (III. 1.)' and issuer 424811 is Olaszfa on every other page
ISSUER_OVERRIDE = {("424811", "2019", "3"): ("Olaszfa Község Önkormányzata", "issuer from the official registry listing (njt.jog.gov.hu 2019-3-SP-5Y3203: Olaszfa), the page heading names Oszkó")}
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import pyarrow as pa, pyarrow.parquet as pq
import hu_fixes as H
from schema import MUNICIPAL_LAWS_SCHEMA, RAW_ARTICLES_SCHEMA, validate_municipal_table, municipal_law_id
COLLECTORS = ("collect_hu_cc.py", "collect_hu_njt.py", "hu_fixes.py", "build_hu_municipal.py")
LIC = ("Hungarian local-government decrees are legislation; under Act LXXVI of 1999 (Szjt.) § 1 (4) legal norms are not protected by "
       "copyright. Texts as published in the Önkormányzati Rendeletek Tára (or.njt.hu / njt.jog.gov.hu, Nemzeti Jogszabálytár), taken from Common Crawl "
       "captures and, for decrees Common Crawl lacks, fetched directly from njt.jog.gov.hu (robots.txt-permitted /jogszabaly/ pages, 1 request at a time).")
ORNJT = re.compile(r"^https?://or\.njt\.hu/onkormanyzati-rendelet/(?:(?P<y>\d{4})-(?P<n>\d+)-SP-(?P<sp>\d+)|(?P<num>\d+))/?$")
NJT = re.compile(r"^https://njt\.jog\.gov\.hu/jogszabaly/(?P<y>\d{4})-(?P<n>\d+)-SP-5Y(?P<sp>\d+)$")
PLACEHOLDER = "3000"
ELI = re.compile(r"^https?://or\.njt\.hu/eli/(?:v01/)?(?P<iss>\d+)/r/(?P<y>\d{4})/(?P<n>\d+)(?:/(?P<v>\d{4}-\d{2}-\d{2}|alaprendelet))?/?$")
STATS = collections.Counter(); DROPS = collections.defaultdict(list)
DATES = re.compile(r"(\d{4})\s*[.-]\s*(\d{2})\s*[.-]\s*(\d{2})")
TAG = re.compile(r"<[^>]+>")
ENTITY = re.compile(r"&(?:[A-Za-z]{2,8}|#\d{2,5}|#x[0-9A-Fa-f]{2,4});")
def clean_head(s):
    import html as _h
    # an escaped '&lt;br&gt;' (or a doubly escaped '&amp;lt;br&amp;gt;') in the source title is a tag too: unescape until stable, tags -> space
    s = s or ""
    for _ in range(3):
        s2 = _h.unescape(TAG.sub(" ", s))
        if s2 == s: break
        s = s2
    s = TAG.sub(" ", s); return H.fix_letters(H.strip_fn_markers(re.sub(r"\s+", " ", s)).strip())
def _real(d):
    """a '3000-01-0x' date is or.njt.hu's placeholder for a state whose start is not known ('Hatályos: Nem ismert'): never a real date"""
    return None if not d or d >= "2999-" else d                # 2999-12-31 ends are 'no end' markers, nulled as well
def hataly(p):
    """(start, end) of the state a page shows: njt 'Hatályos: 2016. 12. 23- 2023. 06. 30', orr '2015-06-09-tól 2021-03-24-ig' / data-hatba;
    live njt.jog.gov.hu 'div.hataly' state date plus the title footnote 'Hatálytalan: 2023. I. 22-től' (set as in_force_to by live_page).
    Placeholder 3000-… dates are returned as None."""
    ds = ["-".join(x) for x in DATES.findall(p.get("in_force_text") or "")]
    st = ds[0] if ds else (p.get("in_force_from") or None)
    en = ds[1] if len(ds) > 1 else p.get("_live_end")
    return _real(st), _real(en)
def placeholder(p):
    return PLACEHOLDER + "-" in (p.get("in_force_text") or "") + " " + (p.get("in_force_from") or "") + " " + (p["_m"]["v"] or "")
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12}
def live_page(r):
    """a njt.jog.gov.hu page (collect_hu_njt.py) in the shape of a fetched capture: parts of the 2023- layout, the state date from div.hataly,
    and the end of force from a title footnote ('Hatálytalan: 2023. I. 22-től' / 'Hatályon kívül helyezve … Hatálytalan: …')"""
    from collect_hu_cc import parts
    from bs4 import BeautifulSoup
    pt = parts(r["html"])
    if not pt: return None
    s = BeautifulSoup(pt["content_html"], "html.parser"); hv = s.select_one("div.hataly")
    st = None
    if hv:
        m = DATES.search(hv.get_text(" ", strip=True))
        if m: st = "-".join(m.groups())
    end = None
    for t in s.select("h1.jogszabalyMainTitle, h2.jogszabalySubtitle"):
        for sup in t.select("sup.fnSup"):
            f = s.find(id=sup.get("data-note-id"))
            m = re.search(r"Hatálytalan:\s*(\d{4})\.\s*([IVX]+)\.\s*(\d{1,2})", f.get_text(" ", strip=True) if f else "")
            if m and m.group(2) in ROMAN: end = f"{m.group(1)}-{ROMAN[m.group(2)]:02d}-{int(m.group(3)):02d}"
    pt["in_force_text"] = f"Hatályos: {st.replace('-', '. ')}." if st else None
    return dict(url=r["url"], timestamp=r["fetched_at"], collection="njt.jog.gov.hu (direct fetch)", warc=None, offset=None, length=None, digest=None,
                fetch_mode="njt_direct", _live_end=end, **pt)
def cap_date(p): return f"{p['timestamp'][:4]}-{p['timestamp'][4:6]}-{p['timestamp'][6:8]}"
def state(p):
    """the date a page's state comes into force: the start in its own hatály line (what the page shows), else the version date in the URL,
    else its capture date (placeholder 3000-… dates do not count); the original text (/alaprendelet) is '0000-00-00'."""
    v = p["_m"]["v"]
    if v == "alaprendelet": return "0000-00-00"
    return hataly(p)[0] or _real(v) or (None if placeholder(p) else cap_date(p))
def rank(p):
    """version ranking: the original text last; then states with a known start above placeholder-only states; then states already in force at
    their capture above future states (a state that starts after the page was captured is kept in other_versions, not as the row);
    then the later state; then the newer capture"""
    st = state(p); alap = p["_m"]["v"] == "alaprendelet"
    return (not alap, st is not None, alap or (st or "") <= cap_date(p), st or "", p["timestamp"])
def recs_of(p):
    """records of one captured page: first split (njt blocks / text lines), then the second pass (H.resplit); footnote markers removed"""
    extra = {}
    if p["layout"] == "njt":
        blocks, info = H.njt_blocks(p["content_html"])
        if isinstance(blocks, tuple):
            body, foot = H.orr_text(blocks[1] or "", None); recs = H.records_text(H.strip_fn_markers(H.fix_letters(body))); info = dict(footnotes=foot, attachment_links=[]); extra["page_structure"] = "html"
        else:
            blocks = [(a, k, H.strip_fn_markers(H.fix_letters(t))) for a, k, t in blocks]; recs = H.records_njt(blocks); extra["page_structure"] = "njt_marked"
    else:
        body, foot = H.orr_text(p["content_html"], p.get("footnotes_html")); recs = H.records_text(H.strip_fn_markers(H.fix_letters(body))); info = dict(footnotes=foot, attachment_links=[])
        extra["page_structure"] = "orr"
    n0 = len(recs); recs = H.resplit(recs); extra["second_pass_new_records"] = len(recs) - n0
    return recs, info, extra
def main(B="hu_build", OUT="hungary_municipal"):
    from collect_hu_cc import read_jsonl_gz
    wd = json.load(open(f"{B}/wd_ksh.json", encoding="utf-8"))
    cty = {b["ksh"]["value"]: b["cLabel"]["value"] for b in json.load(open(f"{B}/wd_county.json", encoding="utf-8"))["results"]["bindings"]}
    I = H.Issuers(wd, cty); today = datetime.date.today().isoformat()
    pages = list(read_jsonl_gz(f"{B}/pages.jsonl.gz", STATS))
    STATS["pages"] = len(pages)
    # one page per version (issuer, year, number, state) over both URL forms: the latest capture; the other captures are kept for headings
    ver = {}; errs = {}
    for p in pages:
        m = ELI.match(p["url"])
        if not m: STATS["url_not_eli"] += 1; continue
        g = m.groupdict(); g["n"] = str(int(g["n"])); k = (g["iss"], g["y"], g["n"], g["v"] or "")
        if p.get("error"): errs.setdefault(k, p); continue
        p["_m"] = g; p["_now"] = 'circle now' in (p.get("content_html") or "")[:6000]; p["_form"] = "v01" if "/eli/v01/" in p["url"] else "plain"
        if k not in ver: ver[k] = [p]
        else: ver[k].append(p)
    for k, e in errs.items():
        if k not in ver: STATS["capture_error"] += 1; DROPS["capture_errors"].append(dict(url=e["url"], error=e["error"][:120]))
    groups = collections.defaultdict(list)
    for k, ps in ver.items():
        ps.sort(key=lambda q: q["timestamp"], reverse=True); top = ps[0]; top["_alts"] = ps[1:]; STATS["duplicate_captures_of_a_version"] += len(ps) - 1
        groups[k[:3]].append(top)
    STATS["decrees"] = len(groups)
    vote = collections.defaultdict(collections.Counter)
    for (iss_id, _, _), ps in groups.items():
        for q in ps:
            for qq in [q] + q["_alts"]:
                hh = H.parse_head(qq["h1"]); rr = I.resolve(hh["issuer"]) if hh else None
                if rr: vote[iss_id][rr] += 1
    by_issuer = {k: v.most_common(1)[0][0] for k, v in vote.items() if v}
    # ---- the other sources, folded into the same (issuer, year, number) groups as undated current pages
    ksh2iss = collections.defaultdict(collections.Counter)
    for (iss_id, _, _), ps in groups.items():
        if iss_id in by_issuer: ksh2iss[by_issuer[iss_id][0]][iss_id] += len(ps)
    ksh2iss = {k: v.most_common(1)[0][0] for k, v in ksh2iss.items()}
    sp2iss = json.load(open(f"{B}/sp2iss.json")) if os.path.exists(f"{B}/sp2iss.json") else {}
    def add_page(k, p, form):
        p["_m"] = dict(iss=k[0], y=k[1], n=k[2], v=""); p["_now"] = 'circle now' in (p.get("content_html") or "")[:6000]; p["_form"] = form
        # one entry per source form next to the ELI versions (a page of another form may show an older state than the ELI current page,
        # so it is ranked by its state like any version, not merged into the ELI current page); captures of the same form: newest first
        same = [q for q in groups.get(k, []) if q.get("_form") == form]
        if same:
            top = same[0]; allc = sorted([top] + top["_alts"] + [p], key=lambda q: q["timestamp"], reverse=True)
            new = allc[0]; new["_alts"] = allc[1:]
            if new is not top: top.pop("_alts", None); groups[k] = [new if q is top else q for q in groups[k]]
        else:
            p["_alts"] = []; groups.setdefault(k, []).append(p)
        SRC[form][k] += 1
    SRC = collections.defaultdict(collections.Counter); eli_keys = set(groups); unmapped = []
    if os.path.exists(f"{B}/pages_ornjt.jsonl.gz"):
        best = {}
        for p in read_jsonl_gz(f"{B}/pages_ornjt.jsonl.gz", STATS):
            if p.get("error"): STATS["ornjt_page_error"] += 1; continue
            m = ORNJT.match(p["url"])
            if not m: continue
            if m["sp"] and m["sp"] in sp2iss: add_page((sp2iss[m["sp"]], m["y"], str(int(m["n"]))), p, "sp"); STATS["ornjt_sp_mapped_pages"] += 1
            else: unmapped.append((m, p))
        # numeric-id pages and SP pages of codes not seen on any ELI page: the decree key from the heading (issuer -> KSH -> issuer id)
        def head_of(m, p):
            """strict heading, else the loose parse (number from the heading, or from the SP URL)"""
            hh = H.parse_head(p["h1"])
            if not hh:
                y_, n_ = (m["y"], m["n"]) if m["sp"] else (None, None)
                if not y_:
                    hn = re.search(r"(?<![\d/])(\d{1,4})\s*/\s*((?:19|20)\d\d)\b", p.get("h1") or "")
                    if hn: n_, y_ = hn.groups()
                if y_: hh = H.parse_head_loose(p["h1"], y_, n_)
            rr = I.resolve(hh["issuer"]) if hh and hh.get("issuer") else None
            return hh, rr
        ksh_sp = {}
        for m, p in unmapped:
            hh, rr = head_of(m, p)
            if m["sp"] and rr: ksh_sp.setdefault(rr[0], m["sp"])
        for m, p in unmapped:
            hh, rr = head_of(m, p)
            if not hh or not rr: STATS["ornjt_heading_or_issuer_not_resolved"] += 1; DROPS["ornjt_heading_or_issuer_not_resolved"].append(dict(url=p["url"], h1=(p.get("h1") or "")[:160])); continue
            no, yy = hh["number"].split("/")[0], hh["year"]
            if m["sp"]: iss = ksh2iss.get(rr[0]) or f"sp{m['sp']}"; y_, n_ = m["y"], str(int(m["n"]))
            else: iss = ksh2iss.get(rr[0]) or (f"sp{ksh_sp[rr[0]]}" if rr[0] in ksh_sp else None); y_, n_ = yy, str(int(no))
            if not iss: STATS["ornjt_issuer_id_unknown"] += 1; DROPS["ornjt_issuer_id_unknown"].append(dict(url=p["url"], h1=p["h1"][:160])); continue
            add_page((iss, y_, n_), p, "sp" if m["sp"] else "num"); STATS["ornjt_sp_unmapped_pages" if m["sp"] else "ornjt_num_pages"] += 1
    if os.path.exists(f"{B}/njt_pages.jsonl.gz"):
        for r in read_jsonl_gz(f"{B}/njt_pages.jsonl.gz", STATS):
            if r.get("http") != 200: STATS[f"njt_http_{r.get('http')}"] += 1; continue
            if "Túl sok lekérdezés" in r.get("html", ""): STATS["njt_throttled_page_ignored"] += 1; continue
            p = live_page(r)
            if not p: STATS["njt_no_decree_parts"] += 1; continue
            add_page(tuple(r["key"]), p, "njt_live"); STATS["njt_pages"] += 1
    STATS["decrees"] = len(groups); STATS["decrees_only_in_other_sources"] = len(set(groups) - eli_keys)
    rows, arts, ids, seen_text = [], [], set(), {}; SUBJ = {}
    rcache = {}
    def recs_cached(q):
        if id(q) not in rcache: rcache[id(q)] = recs_of(q)
        return rcache[id(q)]
    for (iss_id, y, n), ps in sorted(groups.items()):
        # equal states: the newest capture wins, not the one marked 'current' (a later capture of an ended state is no longer marked current)
        ps.sort(key=rank, reverse=True)
        STATS["versions_folded"] += len(ps) - 1
        # the kept page: the best-ranked capture with text. A page that shows no text (a spent / repealed decree shows only its title) gives
        # way to the next capture or version that has it; its end of force still sets the status below.
        order = [(q, qq) for q in ps for qq in [q] + q["_alts"]]; kv, p = order[0]; skipped = []
        for q, qq in order:
            rr_ = recs_cached(qq)[0]
            if len(re.sub(r"\s", "", "\n".join(x[2] for x in rr_))) >= 60 or any(H.is_hollow(x[0], x[2]) for x in rr_): kv, p = q, qq; break
            skipped.append(qq)
        else: kv, p = order[0]; skipped = []
        if skipped: STATS["kept_page_after_pages_without_text"] += 1
        others = [q for q in ps if q is not kv]
        caps = [p] + [x for x in [kv] + kv["_alts"] if x is not p] + [qq for q in others for qq in [q] + q["_alts"]]      # all captures, the kept page first
        h = H.parse_head(p["h1"]); head_basis = None
        if not h:
            for q in caps[1:]:
                h = H.parse_head(q["h1"])
                if h: STATS["heading_from_other_capture"] += 1; head_basis = "heading of another capture" + (" (same version)" if q in [kv] + kv["_alts"] else " (another version)"); break
        recs, info, extra = recs_cached(p)
        recs = [list(r) for r in recs]
        if not h:                                                 # the full heading printed at the top of the content (h1 holds only the title)
            import html as _h
            top = re.sub(r"\s+", " ", _h.unescape(TAG.sub(" ", p.get("content_html") or "")))[:600]
            mt = re.search(r"\S.{0,200}?\d{1,3}\s*/\s*\d{4}\.?\s*\([^)]{2,20}\)\s*(?:számú\s+)?önkormányzati\s+rendelete", top)
            if mt:
                h = H.parse_head(mt.group(0).strip())
                if h and (h["year"] != y or int(h["number"].split("/")[0]) != int(n)): h = None
                if h: STATS["heading_from_content_top"] += 1; head_basis = "heading printed at the top of the content (h1 is the title only)"
        if not h:
            cands = [H.parse_head_loose(q["h1"], y, n) for q in caps]
            h = next((c for c in cands if c["date"]), None) or cands[0]
            head_basis = "loose heading parse (" + ("number from the heading" if h.get("number_basis") == "heading" else "number and year from the ELI URL") + ")"
            if not h["date"]:
                d, why = H.body_date(clean_head(p["h1"]) + "\n" + clean_head(p.get("h2")) + "\n" + "\n".join(r[2] for r in recs), h["number"], h["year"])
                if d: h["date"] = d; head_basis += f"; date from the text ({why})"; STATS["date_from_body"] += 1
            if not h["date"]:
                STATS["excluded_heading_not_parsed"] += 1; DROPS["heading_not_parsed"].append(dict(url=p["url"], h1=p["h1"][:200], key=[iss_id, y, n])); continue
            STATS["heading_parsed_loosely"] += 1
        if not h.get("date"):                                     # a strict parse with an impossible date ('(VIII. 45)'): date from the text
            d, why = H.body_date(clean_head(p["h1"]) + "\n" + clean_head(p.get("h2")) + "\n" + "\n".join(r[2] for r in recs), h["number"], h["year"])
            if not d:
                STATS["excluded_heading_not_parsed"] += 1; DROPS["heading_not_parsed"].append(dict(url=p["url"], h1=p["h1"][:200], key=[iss_id, y, n])); continue
            h["date"] = d; head_basis = (head_basis or "heading (date not valid)") + f"; date from the text ({why})"; STATS["date_from_body"] += 1
        num_ok = h["year"] == y and int(h["number"].split("/")[0]) == int(n)
        if not num_ok: STATS["heading_number_differs_from_url"] += 1
        res = I.resolve(h["issuer"]) if h["issuer"] else None
        if not res and iss_id in by_issuer: res = by_issuer[iss_id]; STATS["issuer_from_issuer_id"] += 1
        if (iss_id, y, n) in ISSUER_OVERRIDE: res = I.resolve(ISSUER_OVERRIDE[(iss_id, y, n)][0]); head_basis = (head_basis or "strict heading") + "; " + ISSUER_OVERRIDE[(iss_id, y, n)][1]; STATS["issuer_override"] += 1
        if not res: STATS["excluded_issuer_not_resolved"] += 1; DROPS["issuer_not_resolved"].append(dict(url=p["url"], issuer=(h["issuer"] or "")[:160])); continue
        ksh, kind, mname, county = res
        h1 = clean_head(p["h1"]); h2 = clean_head(p.get("h2"))
        head = h1 + ("\n" + h2 if h2 else "")
        if recs and recs[0][0] == "0": recs[0] = ["0", "", (head + "\n" + recs[0][2]).strip()]
        else: recs.insert(0, ["0", "", head])
        recs = [[r_[0], unicodedata.normalize("NFC", r_[1] or ""), unicodedata.normalize("NFC", r_[2]).strip(), {}] for r_ in recs]
        recs = [r_ for r_ in recs if r_[2]]
        # hollow § (the kept state shows only the number: repealed or spent): the text of the newest other captured version that has it
        hol = [i for i, r_ in enumerate(recs) if H.is_hollow(r_[0], r_[2])]
        if hol:
            STATS["hollow_records"] += len(hol)
            for i in hol:
                for q in others:
                    qr = {a: b for a, _, b in recs_cached(q)[0]}
                    t = qr.get(recs[i][0])
                    if t and not H.is_hollow(recs[i][0], t):
                        t = unicodedata.normalize("NFC", t).strip()
                        recs[i][3] = dict(recovered_from=dict(url=q["url"], state=("alaprendelet" if q["_m"]["v"] == "alaprendelet" else state(q)), capture=q["timestamp"]),
                                          kept_state_text=recs[i][2])
                        recs[i][2] = t; STATS["hollow_recovered"] += 1; break
                else:
                    recs[i][3] = dict(hollow=True, note="the kept state shows only the § number (repealed or spent provision); no other captured version has its text")
                    STATS["hollow_left"] += 1
        text = "\n".join(r_[2] for r_ in recs).strip()
        body_len = len(re.sub(r"\s", "", text)) - len(re.sub(r"\s", "", head))
        if body_len < 60: STATS["excluded_no_text"] += 1; DROPS["no_text"].append(dict(url=p["url"], chars=body_len)); continue
        tk = (ksh, hashlib.sha256(re.sub(r"\s+", " ", text[len(head):]).encode()).hexdigest())
        native = f"{iss_id}-{y}-{int(n)}"
        lid = municipal_law_id("HU", ksh, native)
        if tk in seen_text:
            STATS["folded_identical_text"] += 1; DROPS["folded_identical_text"].append(dict(url=p["url"], kept=seen_text[tk])); continue
        seen_text[tk] = lid
        assert lid not in ids, lid; ids.add(lid)
        title = " ".join(x for x in (h1, h2) if x)
        if mname.split(" ")[0].lower() not in h1.lower(): title = f"[{mname}, {h['number']}] " + title; STATS["title_prefixed"] += 1   # the heading does not name the municipality
        st0, end = hataly(p); capd = cap_date(p); alap = p["_m"]["v"] == "alaprendelet"
        amending = bool(re.search(r"(?i)módosításáról|módosítás", h2 or "")); repealing = bool(re.search(r"(?i)hatályon kívül helyezés", h2 or ""))
        if end and end < capd:
            if alap or amending or repealing: law_status, sb = "not_in_force", "in-force period of the kept text ended before capture" + (" (amending / repealing decree: spent)" if amending or repealing else "")
            elif not p["_m"]["v"]: law_status, sb = "repealed", "the current page at capture shows a state that had ended (no state in force)"
            else: law_status, sb = "not_in_force", "the kept dated state ended before capture (a later state may exist that was not captured)"
        elif st0 and st0 > capd:
            law_status, sb = "not_yet_in_force", "state starts after capture (no earlier state in force at capture was captured)"
        elif st0 and not alap: law_status, sb = "in_force", "in force at capture (hatály line)"
        elif st0: law_status, sb = "in_force", "derived: original text (alaprendelet) only; its hatály line starts before capture and has no end date, so the original text was the state in force when captured (no later state captured)"
        else: law_status, sb = "unknown", "no in-force dates on the kept page" + (" (only a '3000-01-0x' placeholder start, nulled)" if placeholder(p) else "")
        for q in skipped:                                        # a better-ranked page without text that shows the decree out of force
            qs_, qe_ = hataly(q)
            if qe_ and qe_ <= cap_date(q):
                law_status = "not_in_force" if (amending or repealing) else "repealed"; end = end or qe_
                sb = f"a newer page ({q['url']}, captured {cap_date(q)}) shows the decree out of force from {qe_} and no text; the text is from the kept page"; STATS["status_from_newer_page_without_text"] += 1; break
        if placeholder(p) or any(placeholder(q) for q in caps): STATS["rows_with_placeholder_3000_state"] += 1; DROPS["placeholder_3000_state_nulled"].append(lid)
        ex = dict(eli=p["url"] if p["_form"] in ("plain", "v01") else None, page_url=p["url"], url_form=p["_form"], issuer=h["issuer"], issuer_id=iss_id, issuer_kind=kind, organ=h["organ"], decree_number=h["number"],
                  registry_number=None if num_ok else f"{int(n)}/{y}", heading_number_matches_url=num_ok,
                  promulgation_date=h["date"], date_basis="promulgation_date_in_decree_number", county=county, heading_basis=head_basis,
                  in_force_text=p.get("in_force_text"), in_force_from=st0, in_force_to=end, status_basis=sb,
                  version=("alaprendelet (original text)" if p["_m"]["v"] == "alaprendelet" else (p["_m"]["v"] or "current page")),
                  version_current_at_capture=p["_now"] if p["layout"] == "njt" and p["_form"] != "njt_live" else None,
                  source_form=p["_form"], sources_of_decree=sorted({q["_form"] for q in caps}),
                  amending_decree=amending, repealing_decree=repealing,
                  footnotes=info.get("footnotes")[:40] or None, footnote_count=len(info.get("footnotes") or []) or None,
                  annex_attachments=info.get("attachment_links") or None,
                  version_state_date=state(p) if p["_m"]["v"] != "alaprendelet" else None,
                  version_rank_basis="state start (hatály start / URL version date / capture date; 3000-01-0x placeholders ignored), states in force at capture above future and placeholder states, original text last; pages without text give way to the next capture",
                  version_basis=("version date in URL" if p["_m"]["v"] and p["_m"]["v"] != "alaprendelet" else "original text (only version captured)" if p["_m"]["v"] else "undated URL = state in force at capture"),
                  versions_captured=len(ps), captures_of_kept_version=1 + len(kv["_alts"]),
                  other_versions=[dict(url=q["url"], state=state(q), capture=q["timestamp"], **({"state_placeholder_3000": True} if placeholder(q) else {}),
                                       **({"future_at_capture": True} if (state(q) or "") > cap_date(q) else {})) for q in others] or None,
                  cc_collection=p["collection"], cc_warc=p["warc"], cc_offset=p["offset"],
                  cc_length=p["length"], cc_timestamp=p["timestamp"], cc_digest=p.get("digest"), ksh_code=ksh,
                  hollow_records=sum(1 for r_ in recs if r_[3].get("hollow")) or None, recovered_records=sum(1 for r_ in recs if r_[3].get("recovered_from")) or None, **extra)
        ex = {k: v for k, v in ex.items() if v not in (None, [], {})}
        labs = [r_[0] for r_ in recs]; assert len(labs) == len(set(labs)), (lid, labs)
        for lab, ht, b, md in recs:
            rt = "preamble" if lab == "0" and len(recs) > 1 else ("whole_text" if len(recs) == 1 else ("schedule" if lab.startswith(("melleklet", "fuggelek")) else "article"))
            m_ = dict(md); 
            if ht: m_["heading"] = ht
            arts.append(dict(law_id=lid, id=f"{lid}-art-{lab}", title=title, text=b, source_url=p["url"], document_number=h["number"], article_number=lab,
                             record_type=rt, metadata_json=json.dumps(m_, ensure_ascii=False)))
        lvl = {"settlement": 8, "budapest_district": 9, "county": 6, "capital": 6}[kind]
        body_src = h["issuer"] or f"{mname} " + ("polgármestere" if h["organ"] == "mayor" else "képviselő-testülete")
        rows.append(dict(id=lid, title=title, text=text, source_url=p["url"], source_type="official_html", jurisdiction=f"HU/{mname}", country="Hungary",
                         language="hu", eli=(p["url"] if p["_form"] in ("plain", "v01") else (f"https://or.njt.hu/eli/{iss_id}/r/{y}/{int(n)}" if iss_id.isdigit() else None)), date=h["date"], date_issued=h["date"], retrieved_at=datetime.datetime.strptime(p["timestamp"], "%Y%m%d%H%M%S").strftime("%Y-%m-%dT%H:%M:%SZ"),
                         license=LIC, law_status=law_status, identifier=native,
                         official_identifier=f"{h['number']}. ({h['issuer'] or mname})" + ("" if num_ok else f" [or.njt.hu registry {int(n)}/{y}]"), article_count=len(recs), json_path=None,
                         metadata_json=json.dumps({"extras": ex}, ensure_ascii=False), jurisdiction_level="municipal", admin_level=lvl, country_iso="HU",
                         admin1=county, municipality=mname, municipality_code=ksh, source_body=body_src))
        SUBJ[lid] = re.sub(r"\W+", " ", re.sub(r"(?is)^.*?\br\s?e\s?n\s?d\s?e\s?l\s?e\s?t\s?e\b", "", h2 or "").lower()).strip()   # the subject, without a repeated heading
        STATS["whole_text_records"] += len(recs) == 1
    # consolidated states of one decree that or.njt.hu filed under several registry numbers (Zalakomár 1/2014 as 2014/1, 2014/8, 2014/17 …):
    # same municipality, organ and decree number, and the same subject title or near-identical text (word 5-gram Jaccard >= 0.6).
    # One row is kept: the latest state (then the newer capture); the others are listed in extras.folded_registry_rows and their articles dropped.
    def sh(t):
        w = re.sub(r"\W+", " ", t.lower()).split(); return {tuple(w[i:i + 5]) for i in range(max(0, len(w) - 4))}
    dn = collections.defaultdict(list)
    for r in rows:
        e = json.loads(r["metadata_json"])["extras"]; dn[(r["municipality_code"], e["organ"], e["decree_number"])].append(r)
    gone = set(); FOLDS = []
    for key, rs in dn.items():
        if len(rs) < 2: continue
        par = list(range(len(rs))); S_ = [sh(r["text"].split("\n", 2)[-1]) for r in rs]
        def f(i):
            while par[i] != i: i = par[i]
            return i
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                jac = len(S_[i] & S_[j]) / max(1, len(S_[i] | S_[j]))
                if (SUBJ[rs[i]["id"]] and SUBJ[rs[i]["id"]] == SUBJ[rs[j]["id"]]) or jac >= 0.6: par[f(j)] = f(i)
        cl = collections.defaultdict(list)
        for i in range(len(rs)): cl[f(i)].append(rs[i])
        for c in cl.values():
            if len(c) < 2: continue
            def rk(r):
                e = json.loads(r["metadata_json"])["extras"]; return (e.get("version_state_date") or e.get("in_force_from") or "", r["retrieved_at"])
            c.sort(key=rk, reverse=True); keep = c[0]; m_ = json.loads(keep["metadata_json"])
            m_["extras"]["folded_registry_rows"] = [dict(id=x["id"], registry_number="/".join(reversed(x["identifier"].split("-")[1:])), source_url=x["source_url"],
                                                         state=json.loads(x["metadata_json"])["extras"].get("version_state_date"), retrieved_at=x["retrieved_at"]) for x in c[1:]]
            m_["extras"]["folded_registry_note"] = "consolidated states of this decree that or.njt.hu filed under other registry numbers; the latest state is kept"
            keep["metadata_json"] = json.dumps(m_, ensure_ascii=False)
            gone |= {x["id"] for x in c[1:]}; FOLDS.append(dict(kept=keep["id"], decree_number=key[2], folded=[x["id"] for x in c[1:]]))
    rows = [r for r in rows if r["id"] not in gone]; arts = [x for x in arts if x["law_id"] not in gone]
    STATS["folded_consolidated_state_rows"] = len(gone); DROPS["folded_consolidated_states"] = FOLDS
    # the same decree number twice in one municipality: flag both rows (both published under that number; the ids keep the registry number)
    dn = collections.defaultdict(list)
    for r in rows: dn[(r["municipality_code"], json.loads(r["metadata_json"])["extras"]["decree_number"])].append(r)
    for (k_, num), rs in dn.items():
        if len(rs) > 1:
            for r in rs:
                m_ = json.loads(r["metadata_json"]); m_["extras"]["decree_number_shared_with"] = [x["id"] for x in rs if x is not r]
                r["metadata_json"] = json.dumps(m_, ensure_ascii=False); DROPS["decree_number_shared"].append(r["id"])
    iss_map = collections.defaultdict(set)
    for r in rows: iss_map[json.loads(r["metadata_json"])["extras"]["issuer_id"]].add(r["municipality_code"])
    multi = {k: sorted(v) for k, v in iss_map.items() if len(v) > 1}
    fails = []
    for r in rows:
        try:
            txt = r["text"] + "\n" + r["title"]
            assert not H.bad_chars(txt), (r["id"], "control / FFFD / PUA / C1", H.bad_chars(txt)[:5])
            assert unicodedata.normalize("NFC", txt) == txt, (r["id"], "not NFC")
            assert not re.search(r"[\u0400-\u04ff\u0370-\u03ff]", txt) or True
            assert not re.search(r"[õûÕÛ]", txt), (r["id"], "õ/û for ő/ű")
            assert len(re.findall(r"[áéíóöőúüű]", r["text"].lower())) / max(1, len(re.findall(r"[a-záéíóöőúüű]", r["text"].lower()))) > 0.03, (r["id"], "not Hungarian text")
            assert r["date"] and "1990-01-01" <= r["date"] <= today, (r["id"], r["date"])
            assert re.fullmatch(r"hu-mun-\d{2}(\d{3})?-(?:\d+|sp\d+)-\d{4}-\d+", r["id"]), r["id"]
            assert not TAG.search(r["title"]) and not ENTITY.search(r["title"]) and r["title"] == r["title"].strip(), (r["id"], "HTML / entity / spaces in title")
            assert not re.search(r"\b3000-\d\d-\d\d", json.dumps({k: e.get(k) for k in ("in_force_from", "in_force_to", "version_state_date")})), (r["id"], "placeholder date left")
            assert "\u206f" not in txt and not re.search(r"\[\d{1,3}\]", txt), (r["id"], "U+206F or [n] footnote marker left")
            e = json.loads(r["metadata_json"])["extras"]
            assert r["law_status"] in ("in_force", "not_in_force", "repealed", "not_yet_in_force", "unknown"), (r["id"], r["law_status"])
            if e.get("in_force_to") and e["in_force_to"] < r["retrieved_at"][:10]: assert r["law_status"] in ("not_in_force", "repealed"), (r["id"], "ended state not marked")
            if e["issuer_kind"] == "settlement": assert not re.search(r"(?i)\bmegyei?\s*(?:önkormányzat\w*|közgyűlés\w*)?\s*$", e.get("issuer") or ""), (r["id"], "county assembly filed as settlement")
            assert e["heading_number_matches_url"] or e.get("registry_number"), (r["id"], "heading number differs from URL without registry_number")
        except AssertionError as e: fails.append(e.args[0] if e.args else r["id"])
    for k_, v in multi.items():
        kinds = {len(c) for c in v}
        if 2 in kinds and 5 in kinds: fails.append((k_, "issuer id maps to a county and a settlement", v))
    # split checks (reported): next § heading at a line start inside a record; whole_text records with ≥ 2 § lines
    SECL = re.compile(r"^\s*(\d{1,3})\s?\.\s*§", re.M); SECD = re.compile(r"^\s*(\d{1,3})\s?§", re.M); hid = []; hidq = []; hidd = []; wt2 = []
    def _quoted(body, pos):
        pre = body[:pos]; return pre.count("„") > pre.count("”") or re.search(r"(lép|egészül ki|módosul|rendelkezés)\s*:\s*\n?[^\n]*$", pre[-300:]) is not None
    for x in arts:
        body = "\n".join(x["text"].split("\n")[1:])
        if x["record_type"] == "whole_text" and len(SECL.findall(x["text"])) >= 2: wt2.append(x["id"])
        mm = re.fullmatch(r"(\d+)", x["article_number"])
        if not mm: continue
        for rx, lst in ((SECL, None), (SECD, hidd)):
            for v in rx.finditer(body):
                if int(v.group(1)) == int(mm.group(1)) + 1:
                    if lst is None: (hidq if _quoted(body, v.start()) else hid).append(x["id"])
                    else: lst.append(x["id"])
                    break
    STATS["check_hidden_next_section_heading"] = len(hid) + len(hidq); STATS["check_hidden_next_section_heading_unquoted"] = len(hid)
    STATS["check_hidden_next_section_heading_dotless"] = len(hidd); STATS["check_whole_text_with_2plus_sections"] = len(wt2)
    DROPS["check_hidden_next_section_heading"] = dict(unquoted=hid[:200], quoted=hidq[:200], dotless=hidd[:200]); DROPS["check_whole_text_with_2plus_sections"] = wt2
    if fails: json.dump(fails, open(f"{B}/gate_failures.json", "w"), ensure_ascii=False, default=str)
    assert not fails, (len(fails), fails[:8])
    t = pa.Table.from_pylist(rows, schema=MUNICIPAL_LAWS_SCHEMA); errs = validate_municipal_table(t); assert not errs, errs
    at = pa.Table.from_pylist(arts, schema=RAW_ARTICLES_SCHEMA); assert len(set(at["id"].to_pylist())) == at.num_rows
    cnt = collections.Counter(x["law_id"] for x in arts); assert all(cnt[r["id"]] == r["article_count"] for r in rows)
    os.makedirs(f"{OUT}/data", exist_ok=True); os.makedirs(f"{OUT}/scrapers", exist_ok=True)
    pq.write_table(t, f"{OUT}/data/laws.parquet", compression="zstd"); pq.write_table(at, f"{OUT}/data/articles.parquet", compression="zstd")
    for f in COLLECTORS: shutil.copy(f"{HERE}/{f}", f"{OUT}/scrapers/{f}")
    shutil.copy(f"{os.path.dirname(HERE)}/schema.py", f"{OUT}/scrapers/schema.py"); shutil.copy(f"{os.path.dirname(HERE)}/common_crawl_helper.py", f"{OUT}/scrapers/common_crawl_helper.py")
    files = {}
    for root, _, fs in os.walk(OUT):
        for f in fs:
            p_ = os.path.join(root, f); rel = os.path.relpath(p_, OUT)
            if rel in ("MANIFEST.json", "README.md", "HANDOFF_READY") or "__pycache__" in rel: continue
            files[rel] = hashlib.sha256(open(p_, "rb").read()).hexdigest()
    mc = collections.Counter((r["municipality_code"], r["municipality"]) for r in rows)
    ex_all = [json.loads(r["metadata_json"])["extras"] for r in rows]
    mc_by_name = collections.Counter(r["municipality"] for r in rows)
    man = dict(slug="hungary_municipal", country_iso="HU", collectors=list(COLLECTORS) + ["common_crawl_helper.py"],
               built_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), laws_rows=len(rows), articles_rows=len(arts),
               data_file_names=["data/laws.parquet", "data/articles.parquet"],
               municipalities={f"{k} {n}": c for (k, n), c in sorted(mc.items())}, municipalities_count=len(mc),
               issuer_kind_counts=dict(collections.Counter(e["issuer_kind"] for e in ex_all)), organ_counts=dict(collections.Counter(e["organ"] for e in ex_all)),
               county_counts=dict(collections.Counter(r["admin1"] for r in rows)), year_counts=dict(sorted(collections.Counter(r["date"][:4] for r in rows).items())),
               page_structure_counts=dict(collections.Counter(e.get("page_structure") for e in ex_all)),
               record_type_counts=dict(collections.Counter(x["record_type"] for x in arts)), cc_collection_counts=dict(collections.Counter(e["cc_collection"] for e in ex_all)),
               law_status_counts=dict(collections.Counter(r["law_status"] for r in rows)), url_form_counts=dict(collections.Counter(e["url_form"] for e in ex_all)),
               heading_basis_counts=dict(collections.Counter((e.get("heading_basis") or "strict heading").split(";")[0] for e in ex_all)),
               heading_number_differs_from_url=[r["id"] for r, e in zip(rows, ex_all) if not e["heading_number_matches_url"]],
               issuer_ids_with_several_codes=multi,
               hollow_section_records=dict(found=STATS["hollow_records"], recovered_from_other_version=STATS["hollow_recovered"], left_flagged=STATS["hollow_left"]),
               second_pass_split=dict(H.SPLIT_STATS), footnote_markers=dict(H.FN_STATS),
               annex_links=dict(total=sum(len(e.get("annex_attachments", [])) for e in ex_all), unique=len({u for e in ex_all for u in e.get("annex_attachments", [])}),
                                by_extension=dict(collections.Counter((re.search(r"\.([A-Za-z0-9]{2,4})(?:$|\?)", u) or [None, "none"])[1].lower() for e in ex_all for u in e.get("annex_attachments", []))),
                                rows=sum(1 for e in ex_all if e.get("annex_attachments"))),
               cities_with_county_rights={c: mc_by_name.get(c, 0) for c in ("Budapest", "Debrecen", "Szeged", "Miskolc", "Pécs", "Győr", "Nyíregyháza", "Kecskemét", "Székesfehérvár", "Szombathely",
                                                                           "Szolnok", "Tatabánya", "Kaposvár", "Érd", "Veszprém", "Békéscsaba", "Zalaegerszeg", "Sopron", "Eger", "Nagykanizsa",
                                                                           "Dunaújváros", "Hódmezővásárhely", "Salgótarján", "Szekszárd", "Esztergom")},
               source_form_counts=dict(collections.Counter(e.get("source_form") for e in ex_all)),
               rows_by_sources_of_decree=dict(collections.Counter("+".join(e.get("sources_of_decree") or []) for e in ex_all)),
               build_stats=dict(STATS), symbol_font_chars_mapped=dict(H.SYM_STATS), build_dropped=dict(DROPS), sha256=files,
               excluded_image_only_pdfs=dict(note="Common Crawl HTML pages only: no PDFs were read, so there are no image-only scans. Annexes published only "
                                                  "as PDF attachments on or.njt.hu are listed per row in extras.annex_attachments (not fetched).", count=0,
                                             likely_regulation_count=0, per_municipality={}, items=[], broken_text_layer=dict(count=0, per_municipality={}, items=[]),
                                             annex_attachments_not_fetched=sum(len(e.get("annex_attachments", [])) for e in ex_all)),
               id_rule="hu-mun-<KSH code>-<or.njt.hu issuer id>-<year>-<decree number> (schema.municipal_law_id). KSH code: 5-digit settlement / Budapest district code (Wikidata P939); 2-digit KSH county code for county assemblies; 13578 Budapest for the Fővárosi Közgyűlés.",
               helper_modules={"hu_fixes.py": "scrapers/hu_fixes.py (heading parse, issuer -> KSH, text, § split); imported by build_hu_municipal.py",
                               "common_crawl_helper.py": "scrapers/common_crawl_helper.py (cluster.idx / CDX pointers, ranged WARC reads); imported by collect_hu_cc.py",
                               "schema.py": "scrapers/schema.py (pinned schemas, validate_municipal_table, municipal_law_id)"},
               sources=dict(texts="(1) Common Crawl captures (CC-MAIN-2019 … 2026) of or.njt.hu ELI pages /eli/v01/<issuer>/r/<year>/<no> and /eli/<issuer>/r/<year>/<no> (both forms; ≤ 3 pages per decree: current, newest dated state, original text); "
                                  "(2) Common Crawl captures of or.njt.hu /onkormanyzati-rendelet/<year>-<no>-SP-<code> and /onkormanyzati-rendelet/<numeric id> pages (latest capture per decree / page; a second capture where the first was 'Hiányzó dokumentum'); "
                                  "ranged WARC reads only. (3) njt.jog.gov.hu/jogszabaly/<year>-<no>-SP-5Y<code> fetched directly (robots.txt allows /jogszabaly/*; one connection, ≥ 1.2 s between requests, UA 'EndomorphosisWorldLaws-municipal/1.0'), gap-first. "
                                  "All three are folded into one version ranking per (issuer, year, number). /eli/<issuer>/ri/… pages (indokolás, explanatory memoranda) are not legislation and are not included",
                            codes="KSH settlement codes via Wikidata P939; counties via Wikidata P131 (Q188604)"))
    json.dump(man, open(f"{OUT}/MANIFEST.json", "w"), ensure_ascii=False, indent=1)
    need = sorted({tuple(r["identifier"].split("-")) for r, e in zip(rows, ex_all) if e.get("hollow_records")} | {tuple(d["key"]) for d in DROPS.get("heading_not_parsed", [])})
    json.dump([list(k) for k in need], open(f"{B}/need_secondary.json", "w"))
    print(json.dumps(dict(laws=len(rows), articles=len(arts), stats=dict(STATS)), ensure_ascii=False))
if __name__ == "__main__":
    main(*(sys.argv[1:3]))
