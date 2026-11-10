"""Build the South Africa municipal SUPPLEMENT pack (never replaces endomorphosis/ipfs_south_africa_municipal_laws).

Inputs (all under ZA_STATE): openbylaws/expressions.jsonl (+ HTML cache), munisites/<code>.docs.jsonl,
seeds/za_sites.json, terms/terms.json (per-host stated terms), hub/ (read-only snapshot of the Hub repo, token=False).
Output: <OUT>/data/laws.parquet (MUNICIPAL_LAWS_SCHEMA), data/articles.parquet (RAW_ARTICLES_SCHEMA), report.json
(counts, overlaps, exclusions). MANIFEST / README / HANDOFF_READY are written by finalize_za_supplement.py.
Rules: ids za-mun-<mdb code>-<native id>; rows whose text is already on the Hub (same AKN work+expression, same text
sha256, or same municipality + normalised title + year) are excluded and listed; image-only PDFs are listed, not OCR'd.
usage: build_za_municipal_supplement.py ZA_STATE OUT_DIR
"""
import os, sys, re, json, glob, gzip, hashlib, unicodedata, collections, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import pyarrow as pa, pyarrow.parquet as pq
from bs4 import BeautifulSoup
import warnings; warnings.filterwarnings("ignore")
from schema import MUNICIPAL_LAWS_SCHEMA, RAW_ARTICLES_SCHEMA, municipal_law_id, validate_municipal_table, validate_table
import za_split

STATE, OUT = sys.argv[1], sys.argv[2]
os.makedirs(os.path.join(OUT, "data"), exist_ok=True)
SITES = {s["code"]: s for s in json.load(open(os.path.join(STATE, "seeds", "za_sites.json")))}
TERMS = json.load(open(os.path.join(STATE, "terms", "terms.json"))) if os.path.exists(os.path.join(STATE, "terms", "terms.json")) else {}
# CoS 2026-10-18 14:27 PT: curated exact-quote terms where the automatic 3-sentence summary was wrong or cut off
_OV = os.path.join(STATE, "terms", "terms_overrides.json")
for _h, _o in (json.load(open(_OV)) if os.path.exists(_OV) else {}).items():
    if _o.get("apply_to_rows") and _h in TERMS:
        TERMS[_h] = dict(TERMS[_h], summary=f"{_o['url']}: " + " ".join(_o["quoted"]))
S12 = "official texts of a legislative, administrative or legal nature are excluded from copyright under s12(8)(a) of the South African Copyright Act 98 of 1978"
OBL_TERMS = ("Open By-laws (openbylaws.org.za, Laws.Africa / AfricanLII): by-law text itself is not protected ({s12}); "
             "the site's Terms of Use apply to its presentation and robots.txt carries Content-Signal ai-train=no, ai-input=no, "
             "search=yes (an express reservation of rights). Collected for translation / legal research only; not for AI training or AI input. "
             "Laws.Africa states CC BY-NC-SA for its consolidated legislation.").format(s12=S12)
BYLAW = re.compile(r"by[\s_\-\.]*laws?|bylaw|byelaw|verordening|umthetho|by-wet", re.I)
HARD_EXCL = re.compile(r"draft|proposed|for comment|comments|participation|invitation|fines?[\s_\-]*list|list[\s_\-]*of[\s_\-]*fines|"
                       r"schedule[\s_\-]*of[\s_\-]*fines|flyer|presentation|summary|notice[\s_\-]*of[\s_\-]*intent|explanatory|\bfaqs?\b|"
                       r"application[\s_\-]*form|checklist|\bpolicy\b(?!.*by[\s_\-]*law)", re.I)
NONLAW = re.compile(r"terms of reference|portfolio committee|minutes|\bagenda\b|frequently asked|imibuzo|\bquery\b|\bfaqs?\b|"
                    r"voorgestelde|\bdraft\b|proposed|for public comment|list[\s_\-]+of[\s_\-]+(municipal[\s_\-]+)?by[\s_\-]*laws|unpacked", re.I)  # link text / file name
NONLAW_TEXT = re.compile(r"\bdraft\b[^\n]{0,70}(by[\s\-]*laws?|bylaws?|verordening)|(by[\s\-]*laws?|bylaws?)[^\n]{0,40}\b(final\s+)?draft\b|"
                         r"frequently asked|imibuzo|voorgestelde|proposed amendment|notice of (the )?proposed|"
                         r"invites? (the )?(public|comments|inputs)|call for (public )?comments|for public comment", re.I)
NONLAW_START = re.compile(r"terms of reference|minutes of the|\bagenda\b", re.I)   # only at the very start of the text
SABINET = re.compile(r"Reproduced by Sabinet Online in terms of Government Printer.s Copyright Authority No\. ?10507 dated 02 February 1998")
NOW_BUILD = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

report = collections.defaultdict(list)
CTRL = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f\ufffe\uffff\u200b\u200c\u200d\u2060\ufeff]")


def clean(t):
    t = unicodedata.normalize("NFC", t.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n"))
    t = CTRL.sub("", t).replace("\u00ad", "")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{4,}", "\n\n\n", t)
    return t.strip() + "\n"


def lang_of(t):
    w = re.findall(r"[a-zA-Z']+", t[:20000].lower())
    if not w: return "en"
    af = sum(x in ("die", "van", "en", "is", "nie", "word", "munisipaliteit", "verordening", "raad", "wat", "op", "vir", "met") for x in w)
    en = sum(x in ("the", "of", "and", "is", "not", "be", "municipality", "by-law", "council", "which", "on", "for", "with") for x in w)
    return "af" if af > 1.3 * en else "en"


def norm_title(t, muni=""):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    for w in re.findall(r"[a-z]+", (muni or "").lower()):
        if len(w) > 3: t = re.sub(r"\b" + w + r"\b", " ", t)
    t = re.sub(r"\.(pdf|docx?)\b", " ", t)
    t = re.sub(r"\b(by[\s\-_]*laws?|bylaws?|the|of|and|for|in|on|to|relating|municipality|municipal|local|metropolitan|city|"
               r"council|promulgated|final|gazette|gazetted|no|nr|version|amm|approved|copy|revised|pdf)\b", " ", t)
    t = re.sub(r"\b(19|20)\d\d\b", " ", t)
    t = re.sub(r"[^a-z]+", " ", t)
    return " ".join(sorted(set(x for x in t.split() if len(x) > 2)))


def year_of(*xs):
    for x in xs:
        m = re.findall(r"(?<!\d)(19[5-9]\d|20[0-2]\d)(?!\d)", x or "")
        if m: return m[-1] if len(m) == 1 else m[0]
    return None


# ------------------------------------------------------------------ Hub snapshot (read-only)
hub_ids, hub_text_sha, hub_titles, hub_exprs = set(), set(), collections.defaultdict(list), set()
for f in glob.glob(os.path.join(STATE, "hub", "mun", "data", "*_html.parquet")):
    t = pq.read_table(f, columns=["jurisdiction_id", "doc_id", "cid", "title", "source_url", "regeling_work_id"]).to_pylist()
    for r in t:
        hub_ids.add(r["doc_id"]); hub_ids.add(r["cid"]); hub_exprs.add(r["source_url"])
        hub_titles[r["jurisdiction_id"]].append((norm_title(r["title"]), year_of(r["regeling_work_id"]), r["title"], r["source_url"]))
L1_MAP = {"za-bcm": "BUF", "za-cpt": "CPT", "za-ekh": "EKU", "za-eth": "ETH", "za-jhb": "JHB", "za-tsh": "TSH", "za-man": "MAN"}
for f in glob.glob(os.path.join(STATE, "hub", "mun", "data", "laws-*.parquet")):
    for r in pq.read_table(f, columns=["id", "title", "text", "source_url", "municipality_id", "date"]).to_pylist():
        hub_ids.add(r["id"]); hub_text_sha.add(hashlib.sha256(clean(r["text"] or "").encode()).hexdigest())
        code = L1_MAP.get(r["municipality_id"]) or (r["municipality_id"] or "").replace("za-", "").upper()
        hub_titles[code].append((norm_title(r["title"]), year_of(r["title"], r["date"]), r["title"], r["source_url"]))
        hub_exprs.add(r["source_url"])
for f in glob.glob(os.path.join(STATE, "hub", "mun", "data", "articles-*.parquet")):
    for r in pq.read_table(f, columns=["id"]).to_pylist(): hub_ids.add(r["id"])
for f in glob.glob(os.path.join(STATE, "hub", "prov", "data", "*.parquet")):
    for r in pq.read_table(f, columns=["id"]).to_pylist(): hub_ids.add(r["id"])


def hub_overlap(code, title, year, text_sha, url):
    if url in hub_exprs: return "same source URL on the Hub"
    if text_sha in hub_text_sha: return "same text sha256 on the Hub"
    nt = set(norm_title(title, SITES.get(code, {}).get("name", "")).split())
    if not nt: return None
    for ht, hy, htitle, hurl in hub_titles.get(code, []):
        hs = set(ht.split())
        if not hs: continue
        j = len(nt & hs) / len(nt | hs)
        if j >= 0.75 and (not year or not hy or year == hy):
            return f"title match on the Hub: '{htitle}' ({hurl})"
    return None


laws, arts = [], []


def add_law(code, native, title, text, url, source_type, lic, lang, date, extras, official_identifier=None, retrieved_at=None,
            record_kind="html"):
    site = SITES[code]
    lid = municipal_law_id("ZA", code, native)
    text = clean(text)
    sp = za_split.split(text)
    a_rows = []
    for k, (s, e, lab, rt) in enumerate(sp, 1):
        a_rows.append(dict(law_id=lid, id=f"{lid}-art-{k}", title=(f"Section {lab}" if rt == "article" else lab.replace("-", " ").title()),
                           text=text[s:e], source_url=url, document_number=official_identifier, article_number=lab, record_type=rt,
                           metadata_json=json.dumps({"extras": {"char_start": s, "char_end": e}})))
    extras = dict(extras); extras.update(municipality_qid=site.get("qid"), mdb_category=site.get("category"), ocr=False,
                                         source_terms=lic, split="za_split.v1", n_parts=len(sp))
    laws.append(dict(id=lid, title=title, text=text, source_url=url, source_type=source_type, jurisdiction="ZA", country="South Africa",
                     language=lang, eli=None, date=date, date_issued=date, retrieved_at=retrieved_at, license=lic,
                     law_status="published_by_issuer", identifier=title, official_identifier=official_identifier,
                     article_count=len(a_rows), json_path=None, metadata_json=json.dumps({"extras": extras}, ensure_ascii=False),
                     jurisdiction_level="municipal", admin_level=8, country_iso="ZA", admin1=site.get("province"),
                     municipality=site.get("name"), municipality_code=code, source_body=site.get("name")))
    arts.extend(a_rows)


# ------------------------------------------------------------------ Open By-laws gap
fn = os.path.join(STATE, "openbylaws", "expressions.jsonl")
PLACE = lambda p: p.replace("za-", "").upper()
if os.path.exists(fn):
    for l in open(fn):
        e = json.loads(l); u = e["url"]
        if e.get("status") != 200:
            report["excluded"].append(dict(url=u, reason=f"status {e.get('status')} / final {e.get('final_url')}")); continue
        if u in hub_exprs:
            report["overlap_with_hub"].append(dict(url=u, reason="expression already on the Hub")); continue
        m = re.match(r"https://openbylaws\.org\.za/akn/(za-[a-z0-9]+)/act/([^@]+)/(eng|afr|zul|xho)@(\d{4}-\d\d-\d\d)", u)
        place, wpath, lng, edate = m.group(1), m.group(2), m.group(3), m.group(4)
        code = PLACE(place)
        if code == "ETH" and code not in SITES: code = "ETH"
        k = hashlib.sha1(u.encode()).hexdigest()
        h = gzip.decompress(open(os.path.join(STATE, "cache", k[:2], k + ".gz"), "rb").read())
        s = BeautifulSoup(h, "html.parser")
        la = s.find("la-akoma-ntoso")
        title = CTRL.sub("", (s.find("h1").get_text(" ", strip=True) if s.find("h1") else "") or wpath).strip()
        pub = re.search(r"Published in ([^<\n]{5,120}?\d{4})", s.get_text(" ", strip=True))
        extras = dict(akn_expression=u.split("openbylaws.org.za")[1], akn_work=u.split("openbylaws.org.za")[1].rsplit("/", 1)[0],
                      expression_date=edate, publication=pub.group(1) if pub else None, platform="openbylaws.org.za")
        native = f"akn-{wpath}-{lng}-{edate}"
        lang = {"eng": "en", "afr": "af", "zul": "zu", "xho": "xh"}[lng]
        if e.get("has_akn"):
            body = la.find(class_="akn-akomaNtoso")
            for x in body.find_all(["script", "style"]): x.decompose()
            text = body.get_text("\n", strip=False)
            text = re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text))
            if len(text.strip()) < 80:
                report["excluded"].append(dict(url=u, reason="empty AKN body")); continue
            other = sorted(x for x in hub_exprs if x.startswith(u.rsplit("/", 1)[0] + "/"))
            if other: extras["hub_has_other_expression"] = other   # another language / point-in-time version of this work is on the Hub
            add_law(code, native, title, text, u, "za_openbylaws_akn_html", OBL_TERMS, lang, edate, extras,
                    official_identifier=extras["publication"], retrieved_at=e["retrieved_at"])
        else:
            t = e.get("source_pdf_text") or ""
            pages = e.get("source_pdf_pages") or 0
            if len(re.sub(r"\s+", "", t)) < 200:
                report["excluded"].append(dict(url=u, reason="no AKN body; source PDF without text layer or missing", source_pdf=e.get("source_pdf"),
                                               pages=pages, status=e.get("source_pdf_status")))
                if e.get("source_pdf_text") is not None:
                    report["excluded_image_only_pdfs"].append(dict(url=e.get("source_pdf"), municipality_code=code, title=title, pages=pages,
                                                                  source="openbylaws.org.za", reason="no text layer"))
                continue
            if pages > 12:
                report["excluded"].append(dict(url=u, reason=f"no AKN body; source PDF is a {pages}-page gazette issue (instrument not segmented)",
                                               source_pdf=e.get("source_pdf")))
                continue
            extras.update(source_pdf=e.get("source_pdf"), source_pdf_sha256=e.get("source_pdf_sha256"), pages=pages)
            add_law(code, native, title, t, e["source_pdf"], "za_openbylaws_source_pdf", OBL_TERMS, lang, edate, extras,
                    official_identifier=extras["publication"], retrieved_at=e["retrieved_at"])

# ------------------------------------------------------------------ municipal websites
seen_sha = {}
for f in sorted(glob.glob(os.path.join(STATE, "munisites", "*.docs.jsonl"))):
    code = os.path.basename(f).split(".")[0]
    site = SITES[code]
    host_terms = {}
    for l in open(f):
        try: d = json.loads(l)
        except Exception: continue
        u = d["url"]; fu = d.get("final_url") or u
        fname = urllib.parse.unquote(urllib.parse.urlsplit(fu).path.rsplit("/", 1)[-1])
        label = (d.get("anchor") or "") + " " + fname
        host = urllib.parse.urlsplit(fu).netloc
        base = dict(url=u, municipality_code=code, anchor=d.get("anchor"), page_url=d.get("page_url"))
        if d.get("status") != 200:
            report["excluded"].append(dict(base, reason=f"http {d.get('status')}")); continue
        if d.get("skip"):
            report["excluded"].append(dict(base, reason=d["skip"])); continue
        if re.search(r"draft|proposed|for comment|public participation", d.get("page_title") or "", re.I):
            report["excluded"].append(dict(base, reason="listed on a draft / proposed by-laws page")); continue
        if HARD_EXCL.search(label):
            report["excluded"].append(dict(base, reason="not a promulgated by-law (draft / fines list / form / policy / summary)")); continue
        if d.get("image_only"):
            report["excluded_image_only_pdfs"].append(dict(url=u, municipality_code=code, municipality=site["name"], title=d.get("anchor") or fname,
                                                          pages=d.get("pages"), bytes=d.get("n_bytes"), sha256=d.get("sha256_bytes"),
                                                          kept_at=os.path.relpath(d.get("image_only_path", ""), STATE) if d.get("image_only_path") else None))
            continue
        if d.get("truncated"):
            report["excluded"].append(dict(base, reason="document over 40 MB (truncated)")); continue
        text = clean(d.get("text") or "")
        if len(text) < 400:
            report["excluded"].append(dict(base, reason=f"too little text ({len(text)} chars)")); continue
        head = text[:6000]
        if not BYLAW.search(head) and not BYLAW.search(label):
            report["excluded"].append(dict(base, reason="text does not identify itself as a by-law")); continue
        if not BYLAW.search(head):
            report["excluded"].append(dict(base, reason="by-law named in link only; document text is not a by-law")); continue
        if not BYLAW.search(label) and not BYLAW.search(head[:1500]):
            report["excluded"].append(dict(base, reason="by-law not named in the link or the opening of the document")); continue
        if NONLAW.search(label) or NONLAW_TEXT.search(head[:1500]) or NONLAW_START.search(head[:300]):
            report["excluded"].append(dict(base, reason="not a by-law (minutes / agenda / terms of reference / FAQ / proposed amendment / notice)")); continue
        if re.search(r"\b(draft|proposed)\s+(by[\s\-]*law|bylaw)|for public comment|invites? (the )?(public|comments)", head[:2500], re.I):
            report["excluded"].append(dict(base, reason="draft / proposed by-law (from text)")); continue
        anchor = re.sub(r"\s+", " ", d.get("anchor") or "").strip()
        if not anchor or re.fullmatch(r"(?i)(download|view|open|click here|read more|pdf|here|file|document)[\s\w\(\)\.]*", anchor) or len(anchor) < 6:
            anchor = re.sub(r"[_\-]+", " ", re.sub(r"\.(pdf|docx?)$", "", fname, flags=re.I)).strip()
        title = CTRL.sub("", re.sub(r"\s*\(\s*\d+(\.\d+)?\s*[kKmM]i?[bB]\s*\)\s*$", "", anchor)).strip()[:300]
        yr = year_of(title, fname)
        sha = hashlib.sha256(text.encode()).hexdigest()
        ov = hub_overlap(code, title, yr, sha, u)
        if ov:
            report["overlap_with_hub"].append(dict(base, title=title, reason=ov)); continue
        key = (code, sha)
        if key in seen_sha:
            row = seen_sha[key]; m = json.loads(row["metadata_json"])
            if u != row["source_url"] and u not in m["extras"]["alt_urls"]: m["extras"]["alt_urls"].append(u)
            lt_ = m["extras"].setdefault("link_texts", [m["extras"].get("link_text")])
            def _jac(a, b):
                a, b = set(norm_title(a).split()), set(norm_title(b).split())
                return len(a & b) / len(a | b) if a and b else 1.0
            if d.get("anchor") and d.get("anchor") not in lt_:
                lt_.append(d.get("anchor"))
            bl = [re.sub(r"[\s\.]*\.(pdf|docx?)$", "", x.strip(), flags=re.I) for x in lt_ if x and " " in x.strip() and BYLAW.search(x)
                  and not re.search(r"gazette[\s_\-]+dated", x, re.I)]
            if bl and not m["extras"].get("multi_instrument_document") and (len(bl) == 1 or min(_jac(bl[0], x) for x in bl[1:]) >= 0.25):
                if not (BYLAW.search(row["title"]) and not re.search(r"\.pdf|gazette[\s_\-]+dated", row["title"], re.I)):
                    row["title"] = row["identifier"] = CTRL.sub("", re.sub(r"\s+", " ", bl[0])).strip()[:300]
            if len(bl) > 1 and min(_jac(bl[0], x) for x in bl[1:]) < 0.25:
                lt_ = bl
                base_t = re.sub(r"\s*\((page|pg)\.?\s*\d+\)\s*$", "", lt_[0] or "", flags=re.I)
                row["title"] = row["identifier"] = (f"{site['name']}: document with several by-laws ({'; '.join(re.sub(r'\s+', ' ', x or '')[:60] for x in lt_[:6])}"
                                                    + ("; ..." if len(lt_) > 6 else "") + ")")[:300]
                m["extras"]["multi_instrument_document"] = True
            row["metadata_json"] = json.dumps(m, ensure_ascii=False)
            report["same_text_merged"].append(dict(url=u, kept=row["id"])); continue
        sab = bool(SABINET.search(head))
        head = SABINET.sub(" ", head)
        gz = re.search(r"Provincial\s+Gazette(?:\s+Extraordinary)?\s*(?:No\.?\s*)?(\d{3,5})", head, re.I)
        MONTHS = r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+(?:19|20)\d\d)"
        gdate = None
        if gz:   # the gazette's own date sits next to its masthead / number
            gdate = re.search(MONTHS, head[max(0, gz.start() - 300): gz.end() + 300])
        if not gdate:
            gdate = re.search(r"(?:date of (?:publication|promulgation|commencement)|published|promulgated)[^\n]{0,40}?" + MONTHS, head, re.I)
            if gdate: gdate = re.search(MONTHS, gdate.group(0))
        notice = re.search(r"(?:Local Authority |Municipal |Provincial |General )?Notice\s+(?:No\.?\s*)?(\d{1,4}\s*(?:/|of)\s*(?:19|20)\d\d)", head, re.I)
        oid = "; ".join(x for x in [f"Provincial Gazette {gz.group(1)}" if gz else None, f"Notice {notice.group(1)}" if notice else None] if x) or None
        date = re.sub(r"\s+", " ", gdate.group(1)) if gdate else yr
        if date and not re.match(r"^\d{1,2} [A-Z][a-z]+ \d{4}$|^\d{4}$", date): date = yr
        native = re.sub(r"\.(pdf|docx?)$", "", urllib.parse.unquote(urllib.parse.urlsplit(fu).path).strip("/"), flags=re.I)
        q = urllib.parse.urlsplit(fu).query
        if q: native += "-" + hashlib.sha1(q.encode()).hexdigest()[:8]
        if len(native) > 120: native = native[-110:] + "-" + hashlib.sha1(native.encode()).hexdigest()[:8]
        terms = TERMS.get(host) or TERMS.get(host[4:] if host.startswith("www.") else "www." + host) or {}
        lic = (f"Official municipal by-law text published by {site['name']} on {host}; {S12}. "
               f"Site terms: {terms.get('summary') or 'no terms-of-use / copyright page found on the site (checked ' + NOW_BUILD[:10] + ')'}")
        extras = dict(page_url=d.get("page_url"), link_text=d.get("anchor"), file_name=fname, sha256_bytes=d.get("sha256_bytes"), pages=d.get("pages"),
                      extraction=d.get("method"), host=host, alt_urls=[], gazette=gz.group(1) if gz else None,
                      terms_url=terms.get("url"), sabinet_reproduction=sab,
                      gazette_issue=bool(re.search(r"Provincial\s+Gazette", head[:1500], re.I)) and (d.get("pages") or 0) > 20)
        add_law(code, native, title, text, fu, "za_municipal_website_document", lic, lang_of(text), date, extras,
                official_identifier=oid, retrieved_at=d.get("retrieved_at"))
        seen_sha[key] = laws[-1]

# ------------------------------------------------------------------ id dedupe (same id -> newest retrieved_at), write
by_id = {}
for r in laws:
    o = by_id.get(r["id"])
    if o is None or (r["retrieved_at"] or "") > (o["retrieved_at"] or ""):
        if o is not None: report["dup_id_dropped"].append(o["source_url"])
        by_id[r["id"]] = r
    else:
        report["dup_id_dropped"].append(r["source_url"])
keep = set(id(r) for r in by_id.values())
laws = [r for r in laws if id(r) in keep]
lid = set(r["id"] for r in laws)
arts = [a for a in arts if a["law_id"] in lid and any(True for _ in [0])]
# articles of dropped duplicate laws: keep only those of the surviving row (same id -> rebuild from surviving text)
surv = {r["id"]: r for r in laws}
arts2, seen_a = [], set()
for a in arts:
    if (a["law_id"], a["id"]) in seen_a: continue
    seen_a.add((a["law_id"], a["id"])); arts2.append(a)
arts = arts2
HEAD_BL = re.compile(r"^[ \t]*((?:[A-Z][A-Z'&\-]*[ ,]+){0,10}(?:BY-?LAWS?|VERORDENING)(?:[ ,]+(?:19|20)\d\d)?)[ \t,]*$", re.M)
for r in laws:   # flag compilations (one PDF holding several separate by-laws)
    ex = json.loads(r["metadata_json"]); e = ex["extras"]
    heads = []
    for h in HEAD_BL.findall(r["text"]):
        h = re.sub(r"[\s,]+$", "", re.sub(r"\s+", " ", h)).strip()
        if len(h.split()) < 2 or h.startswith("BY") or "VERORDENING" in h: continue
        if re.match(r"(OF|THE|THIS|THESE|APPLICATION|ARRANGEMENT|SCOPE|PURPOSE|OBJECTS?|REPEAL|REPEALED|EXEMPTION|APPROVAL|OFFICIAL|INTERPRETATION|NAME|"
                    r"DEFINITIONS|OFFENCES|TOEPASSING|ISSUED|PROPOSED|AMENDED|AMENDMENT|SHORT|TITLE|COMMENCEMENT|CONFLICT|COPY|ENFORCEMENT|COMPLIANCE)\b", h) \
           or re.search(r"\b(OF|UNDER|IN TERMS OF|FROM PROVISIONS OF|WITH) (THE |THIS |THESE )?BY-?LAWS?\b", h) or re.match(r"(MANAGEMENT|CONTROL|SCHEME) BY", h):
            continue
        nh = set(norm_title(re.sub(r"(19|20)\d\d", "", h), r.get("municipality") or "").split()) - {"by", "law", "laws", "bylaw", "bylaws"}
        if not nh or any(len(nh & k) / len(nh | k) >= 0.5 for k in [set(norm_title(re.sub(r"(19|20)\d\d", "", x), r.get("municipality") or "").split()) - {"by", "law", "laws", "bylaw", "bylaws"} for x in heads]):
            continue
        heads.append(h)
    if len(heads) >= 3 and (e.get("gazette_issue") or (e.get("pages") or 0) > 40):
        e["multi_instrument_document"] = True; e["contained_bylaw_headings"] = heads[:60]
        e.setdefault("link_text_title", r["title"])
        r["title"] = r["identifier"] = (f"Compilation of {len(heads)} by-laws ({'; '.join(h.title() for h in heads[:4])}"
                                        + ("; ..." if len(heads) > 4 else "") + ")")[:300]
        report.setdefault("multi_instrument_documents", []).append(dict(id=r["id"], n=len(heads), url=r["source_url"]))
    r["metadata_json"] = json.dumps(ex, ensure_ascii=False)
laws.sort(key=lambda r: r["id"]); order = {r["id"]: i for i, r in enumerate(laws)}
arts.sort(key=lambda a: (order[a["law_id"]], int(a["id"].rsplit("-", 1)[1])))
lt = pa.Table.from_pylist(laws, schema=MUNICIPAL_LAWS_SCHEMA)
at = pa.Table.from_pylist(arts, schema=RAW_ARTICLES_SCHEMA)
pq.write_table(lt, os.path.join(OUT, "data", "laws.parquet"), compression="zstd")
pq.write_table(at, os.path.join(OUT, "data", "articles.parquet"), compression="zstd")
coll = sorted(lid & hub_ids)
rep = dict(built_utc=NOW_BUILD, laws=len(laws), articles=len(arts), municipalities=dict(collections.Counter(r["municipality_code"] for r in laws)),
           by_source_type=dict(collections.Counter(r["source_type"] for r in laws)), by_language=dict(collections.Counter(r["language"] for r in laws)),
           validate=validate_municipal_table(lt), validate_articles=validate_table(at, "articles"), hub_id_collisions=coll,
           **{k: v for k, v in report.items()})
json.dump(rep, open(os.path.join(OUT, "report.json"), "w"), indent=1, ensure_ascii=False)
print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in rep.items() if k != "municipalities"}, indent=1))
print("municipalities", len(rep["municipalities"]))
