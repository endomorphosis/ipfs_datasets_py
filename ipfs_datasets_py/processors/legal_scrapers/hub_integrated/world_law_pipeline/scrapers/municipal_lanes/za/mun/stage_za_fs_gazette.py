#!/usr/bin/env python3
"""ZA batch 5 (A), OFFLINE step 2: split each Free State Provincial Gazette into notices, classify them, keep by-law
notices only, attribute each to its municipality, split into sections and write data/laws-00003.parquet +
data/articles-00003.parquet (schema mirrored exactly from the live shards), plus manifests:
  batch5_fs_notices.jsonl      every notice found (gazette, number, type, title, class, kept/excluded, municipality)
  batch5_fs_exclusions.jsonl   every excluded candidate with its exclusion type and reason
  batch5_fs_municipalities.json  municipality -> QID mapping used (+ coverage)
  batch5_stage_result.json     (written/merged by verify_za_batch5.py) names the expected Hub parent
Usage: python3 stage_za_fs_gazette.py LIVE_DIR PACK_DIR"""
import hashlib, json, os, re, sys, unicodedata
from collections import Counter, defaultdict
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
STAGE = Path(os.environ.get("FS_STAGE", "/dev/shm/muni_africa/fs"))
SEEDS = Path(os.environ.get("FS_SEEDS", str(HERE / "seeds")))
HUB_PARENT = os.environ.get("ZA_HUB_PARENT", "7aafa0a56f8f08147f4e8be7505d331482c6d648")
PARSER_VERSION = "za-fs-gazette-2026.10.04-b5"
LISTING = "https://www.fsonline.fs.gov.za/?page_id=6939"
LICENSE = ("Official municipal by-law text published in the Free State Provincial Gazette by the Free State Provincial Government; official "
           "texts of a legislative, administrative or legal nature are excluded from copyright under s12(8)(a) of the Copyright Act 98 of 1978; "
           "site footer claims general copyright over site content.")
TERMS = ("fsonline.fs.gov.za (Free State Provincial Government): no terms-of-use or disclaimer page found; footer 'Copyright (c) Free State Online, "
         "all rights reserved' only; robots.txt 404 (no rules) (checked 2026-10-04). Text taken from the Provincial Gazette PDF.")
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                                      "november", "december"], 1)}
MONTH_FIX = {"juy": "july", "febraury": "february", "feburary": "february", "septmber": "september", "januay": "january", "agust": "august",
             "decmber": "december", "novemeber": "november", "ocober": "october"}
MONTH_NAMES = {i: m.capitalize() for m, i in MONTHS.items()}

# ------------------------------------------------------------------ helpers
def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def norm_text(t):
    return re.sub(r"[ \t]+\n", "\n", (t or "").replace("\f", "\n")).strip()


SEC_LINE = re.compile(r"(?m)^[ \t]*(\d{1,3}[A-Z]?)\.[ \t]+([A-Z][^\n]{1,160})$")


def split_sections(text):          # batch-1 splitter (verbatim)
    ms = list(SEC_LINE.finditer(text or ""))
    if len(ms) < 2:
        return []
    ones = [i for i, m in enumerate(ms) if m.group(1) == "1"]
    if len(ones) >= 2:
        ms = ms[ones[1]:]
    out, seen = [], set()
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        chunk = text[m.start():end].strip()
        num = m.group(1)
        if len(chunk) < 15 or num in seen:
            continue
        seen.add(num)
        out.append({"num": num, "title": f"{num}. {m.group(2).strip()}"[:200], "text": chunk})
    return out if len(out) >= 2 else []


def split_chain(text):
    """Fallback when the batch-1 '2nd 1.' rule jumps into a schedule: longest run of section lines numbered 1,2,3,...
    in order (gaps of <= 2 allowed), first occurrence of each number after the previous one."""
    ms = list(SEC_LINE.finditer(text or ""))
    best = []
    for i, m in enumerate(ms):
        if m.group(1) != "1":
            continue
        chain, want = [m], 2
        for n in ms[i + 1:]:
            v = re.match(r"\d+", n.group(1)).group(0)
            if int(v) in range(want, want + 3) and n.group(1).isdigit():
                chain.append(n); want = int(v) + 1
        if len(chain) > len(best):
            best = chain
    if len(best) < 3:
        return []
    out = []
    for k, m in enumerate(best):
        end = best[k + 1].start() if k + 1 < len(best) else len(text)
        out.append({"num": m.group(1), "title": f"{m.group(1)}. {m.group(2).strip()}"[:200], "text": text[m.start():end].strip()})
    return out


def stubs(secs):
    return sum(1 for x in secs if len(x["text"]) < 80)


def resplit(text):
    a, b = split_sections(text), split_chain(text)
    if b and (len(b) >= 1.5 * max(1, len(a)) or (a and stubs(a) >= 0.5 * len(a) and stubs(b) < stubs(a))):
        return b, "numbered_chain (batch-1 ids/fields)"
    if a:
        return a, "batch1_split_sections"
    return [], "whole_text (no headings found)"


# ------------------------------------------------------------------ gazette parsing
HDR = re.compile(r"(?m)^[ \t]*[\[(]?[ \t]*(PROVINCIAL|GENERAL|MUNICIPAL|LOCAL[ \t]+AUTHORITY|PROCLAMATION|OFFICIAL|BOARD)?[ \t]*"
                 r"NOTICES?[ \t]*(?:NO|NR|NUMBER)?[ \t]*[.:]?[ \t]*(\d{1,4})\b[ \t]*(?:(?:OF|VAN)[ \t]*(\d{4}|NOTICE))?")
HDR_PROC = re.compile(r"(?m)^[ \t]*[\[(]?[ \t]*(PROCLAMATION)[ \t]*(?:NO|NR)?[ \t]*[.:]?[ \t]*(\d{1,4})\b[ \t]*(?:(?:OF|VAN)[ \t]*(\d{4}))?")


def gazette_meta(title, cover):
    no = date = None
    m = re.search(r"(?i)\bNO\.?\s*(\d{1,3})\b[^\n]{0,40}?\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", cover or "")
    t = re.search(r"(?i)No\.?\s*(\d{1,3})\s*[-–]?\s*(\d{1,2})\s*([A-Za-z]+)\s*(\d{4})", title)
    for src in (m, t):
        if not src:
            continue
        mon = MONTH_FIX.get(src.group(3).lower(), src.group(3).lower())
        if mon in MONTHS:
            no, date = int(src.group(1)), (int(src.group(4)), MONTHS[mon], int(src.group(2)))
            break
    return no, date


def toc_titles(front):
    """Contents page: '28    Ngwathe Local Municipality: ... By-Law......  3' (left/English column)."""
    out, cur, num = {}, [], None
    for line in front.splitlines():
        left = re.split(r"\s{6,}", line.strip(), maxsplit=1)
        mm = re.match(r"^(\d{1,4})\s{2,}(\S.*)$", line.strip())
        if mm:
            if num is not None and cur:
                out.setdefault(num, " ".join(cur))
            num, cur = int(mm.group(1)), [re.split(r"\s{6,}", mm.group(2))[0]]
        elif num is not None and left and left[0] and not re.match(r"^(\d+|GENERAL NOTICES|NOTICES|PROVINCIAL NOTICES|Continue|Continued)", left[0]):
            cur.append(left[0])
        if num is not None and re.search(r"[.…]{3,}\s*\d+\s*$", line.split("      ")[0] if "      " in line else line):
            out.setdefault(num, " ".join(cur)); num, cur = None, []
    if num is not None and cur:
        out.setdefault(num, " ".join(cur))
    return {k: re.sub(r"[.…]{2,}.*$", "", re.sub(r"\s+", " ", v)).strip(" .:") for k, v in out.items()}


def segment(g):
    """Concatenate pages (layout text; OCR text for OCR pages) and cut at notice headers."""
    parts, offs, pos = [], [], 0
    for p in g["pages"]:
        t = (p.get("text") or "") + "\n\f\n"
        parts.append(t); offs.append((pos, p["page"], p["source"])); pos += len(t)
    doc = "".join(parts)
    hs = []
    for rx in (HDR, HDR_PROC):
        for m in rx.finditer(doc):
            line = doc[m.start():doc.find("\n", m.start())]
            if not re.search(r"\[|\(|\bOF\b|\bVAN\b", line[:60]):   # bare 'NOTICE 5' inside text is not a header
                continue
            if rx is HDR and not re.search(r"NOTICE", line[:40]):
                continue
            hs.append((m.start(), (m.group(1) or "").replace("\t", " ").strip(), int(m.group(2)), m.group(3)))
    hs.sort()
    ded = []
    for h in hs:                     # drop duplicates (same number re-stated within 400 chars, e.g. bilingual column)
        if ded and h[2] == ded[-1][2] and h[0] - ded[-1][0] < 400:
            continue
        ded.append(h)
    def page_of(o):
        k = 0
        for i, (st, _, _) in enumerate(offs):
            if st <= o:
                k = i
        return k
    segs = []
    for i, (st, typ, num, yr) in enumerate(ded):
        en = ded[i + 1][0] if i + 1 < len(ded) else len(doc)
        p0, p1 = page_of(st), page_of(max(st, en - 1))
        segs.append({"start": st, "end": en, "type": typ, "num": num, "year": yr, "text": doc[st:en],
                     "pages": list(range(offs[p0][1], offs[p1][1] + 1)), "sources": sorted({offs[k][2] for k in range(p0, p1 + 1)})})
    front = doc[:ded[0][0]] if ded else doc
    return doc, segs, front


# ------------------------------------------------------------------ classification
BYLAW = re.compile(r"(?i)\bby[\s\-–]*laws?\b|\bbylaws?\b|\bverordening")
PROPOSED = re.compile(r"(?i)\bproposed\b|\bdraft\b|public (comment|participation)|calling for (public )?comment|invite[sd]? .{0,40}comment|"
                      r"comments? (on|in respect of) the (proposed|draft)|voorgestelde|konsep")
LANDUSE = re.compile(r"(?i)\brezon|\bre-zon|hersoner|subdivi|onderverdel|consolidat|konsolid|township|dorpstig|\berf\b|\berven\b|\berwe\b|"
                     r"removal of restrict|restrictive (title )?condition|title deed|land use (development )?application|"
                     r"application (for|in terms of)|aansoek|change (in|of) land use|departure|special consent|"
                     r"farm\s+[A-Z][\w ]{0,30}\s+\d+|portion\s+\d+|amendment scheme|town planning scheme|land development application|"
                     r"closure of (a )?(public )?(street|road|park)|\bspluma\b.{0,80}(application|notice)|notices? in terms of the .{0,60}land use planning")
LIQUOR = re.compile(r"(?i)liquor|drank")
RATES = re.compile(r"(?i)levying (of )?(property )?rates|rates? resolution|resolution levying|property rates? (for|tariffs?)|rates (and|&) tariffs|"
                   r"\btariffs?\b|\btarief|determination of (property )?rates|charges for|fees? (for|payable)")
PROVINCIAL = re.compile(r"(?i)\bact\b,? \d{4}|\bact no\.?|appropriation|regulations?\b|proclamation|premier|\bMEC\b|member of the executive council|"
                        r"provincial (treasury|government|legislature)|ordinance|conversion of certain rights|leasehold|determination|"
                        r"appointment|establishment of|ward|electoral|by-election|tribunal members|gambling|gaming|road traffic")
ENACT = re.compile(r"(?i)promulgat|hereby (publishes|promulgates|gives notice)|has (adopted|approved|enacted|passed|made)|in terms of section 1[23]|"
                   r"section 13 of the (local government: )?municipal systems act|adopted by (the )?(municipal )?council|council (resolved|resolution)|"
                   r"comes? into (operation|effect)|repeal|is hereby (repealed|amended)")


def classify(head, toc, body):
    t = f"{toc or ''}\n{head}"
    if LIQUOR.search(t) and not BYLAW.search(t):
        return "excluded", "liquor_licence_application", "liquor (registration/licence) application notice"
    if BYLAW.search(t):
        if LANDUSE.search(toc or head[:400]) and not re.search(r"(?i)(promulgation|adoption) of|by-?law (is|has been) (adopted|promulgated)", t):
            return "excluded", "land_use_application", "land-use / town-planning application made under a land-use by-law (not a by-law)"
        if PROPOSED.search(t):
            return "excluded", "proposed_bylaw_for_comment", "proposed / draft by-law or by-law amendment published for public comment (not enacted)"
        if re.search(r"(?i)\btariff|\btarief|fees|charges", t):
            return "kept", "tariff_bylaw", "tariff by-law"
        if re.search(r"(?i)credit control|debt collection", t):
            return "kept", "credit_control_bylaw", "credit control / debt collection by-law"
        if re.search(r"(?i)\brepeal", t):
            return "kept", "bylaw_repeal", "by-law repeal notice"
        if re.search(r"(?i)\bamend", t):
            return "kept", "bylaw_amendment", "by-law amendment"
        return "kept", "bylaw", "municipal by-law"
    if LANDUSE.search(t):
        k = ("rezoning" if re.search(r"(?i)rezon|re-zon|hersoner", t) else "township_establishment" if re.search(r"(?i)township|dorpstig", t)
             else "removal_of_restrictions" if re.search(r"(?i)restrict|title deed|titelakte", t) else "land_use_application")
        return "excluded", k, "land-use / town-planning notice"
    if RATES.search(t):
        return "excluded", "rates_or_tariff_resolution_not_bylaw", "property-rates resolution / tariff schedule not enacted as a by-law"
    if PROVINCIAL.search(t):
        return "excluded", "provincial_or_other_statutory_notice", "provincial act / regulation / proclamation / statutory notice (not a municipal by-law)"
    return "excluded", "other_non_bylaw_notice", "other notice (not a municipal by-law)"


# ------------------------------------------------------------------ municipality attribution
def load_munis():
    j = json.loads((SEEDS / "za_fs_municipalities.json").read_text())
    ms = j["municipalities"]
    pats = []
    for m in ms:
        core = m["aliases"][0]
        rx = re.compile(r"(?i)\b" + re.escape(core).replace(r"\-", r"[\s\-]*").replace(r"\ ", r"[\s\-]*") + r"\b")
        pats.append((m, rx, [re.compile(r"(?i)\b" + re.escape(a) + r"\b") for a in m["aliases"][1:]]))
    return ms, pats


def attribute(head, toc, body, pats):
    for src, txt in (("toc_title", toc or ""), ("notice_heading", head[:900])):
        hits = sorted({(rx.search(txt).start(), m["municipality_id"]): m for m, rx, _ in pats if rx.search(txt)}.items())
        if hits:
            ids = {m["municipality_id"] for _, m in hits}
            lm = [m for _, m in hits if m["admin_level"] != "district_municipality"]
            pick = (lm or [m for _, m in hits])[0]
            return pick, src, ("" if len(ids) == 1 else f"several municipality names in {src}: {sorted(ids)}; first local/metro used")
    cnt = Counter()
    for m, rx, _ in pats:
        n = len(rx.findall(body))
        if n:
            cnt[m["municipality_id"]] = n
    if cnt:
        (top, n), *rest = cnt.most_common()
        if not rest or n >= 3 * rest[0][1]:
            return next(m for m, _, _ in pats if m["municipality_id"] == top), "body_mentions", f"body mentions {dict(cnt)}"
    return None, "unattributed", f"no municipality name in title/heading; body mentions {dict(cnt)}"


TITLE_SKIP = re.compile(r"(?i)^(notice|kennisgewing|municipal manager|city manager|ref|date|\d+\.|[\[(])")


def notice_title(seg, toc, muni):
    lines = [l.strip() for l in seg["text"].splitlines()[1:40] if l.strip()]
    cand = []
    for l in lines:
        l = re.split(r"\s{6,}", l)[0].strip()
        if BYLAW.search(l) and not TITLE_SKIP.match(l) and len(l) <= 200:
            cand.append(l)
            if re.search(r"(?i)by-?\s?laws?,?\s*(\d{4})?\s*$", l):
                break
    base = cand[0] if cand else (toc or (lines[0] if lines else "By-law notice"))
    if toc and BYLAW.search(toc) and (not cand or len(toc) < 160):
        base = re.sub(r"^[^:]{3,80}(Municipality|Munisipaliteit)\s*:\s*", "", toc).strip() or base
    base = re.sub(r"\s+", " ", base).strip(" .:-")
    if base.isupper():
        base = " ".join(w.capitalize() if len(w) > 3 or i == 0 else w.lower() for i, w in enumerate(base.lower().split()))
        base = re.sub(r"(?i)\bby-law\b", "By-law", re.sub(r"(?i)\bbylaw", "By-law", base))
    return base[:250]


# ------------------------------------------------------------------ main
def main():
    live, pack = Path(sys.argv[1]), Path(sys.argv[2])
    LT, AT = pq.read_table(live / "data/laws-00002.parquet"), pq.read_table(live / "data/articles-00002.parquet")
    live_ids = set()
    for s in ("00001", "00002"):
        live_ids |= set(pq.read_table(live / f"data/laws-{s}.parquet", columns=["id"]).column("id").to_pylist())
    ms, pats = load_munis()
    fetch = {}
    for l in open(STAGE / "fetch.jsonl"):
        d = json.loads(l); fetch[d["url"]] = d
    gazettes = []
    for f in sorted((STAGE / "pages").glob("*.json")):
        g = json.loads(f.read_text())
        no, date = gazette_meta(g["title"], g["pages"][0]["text"] if g["pages"] else "")
        g["no"], g["date"] = no, date
        gazettes.append(g)
    gazettes.sort(key=lambda g: (g["date"] or (0, 0, 0), g["no"] or 0))
    laws, arts, notices, excl = [], [], [], []
    for g in gazettes:
        doc, segs, front = segment(g)
        toc = toc_titles(front)
        y, mo, d = g["date"] or (None, None, None)
        gdate = f"{d} {MONTH_NAMES[mo]} {y}" if g["date"] else ""
        if not segs:
            notices.append({"gazette": g["no"], "gazette_date": gdate, "source_url": g["url"], "notice": None, "class": "no_numbered_notices",
                            "title": g["title"]})
        for s in segs:
            typ = (s["type"] or "").title().replace("Local Authority", "Local Authority") or "Notice"
            yr = s["year"] if (s["year"] or "").isdigit() else (str(y) if y else "")
            nno = f"{typ} Notice {s['num']} of {yr}".replace("Notice Notice", "Notice").replace("Proclamation Notice", "Proclamation")
            head = s["text"][:1500]
            tt = toc.get(s["num"])
            dec, cls, why = classify(head, tt, s["text"])
            muni, msrc, mnote = attribute(head, tt, s["text"], pats)
            rec = {"gazette": g["no"], "gazette_date": gdate, "source_url": g["url"], "notice": nno, "notice_type": typ, "pages": s["pages"],
                   "toc_title": tt, "heading": re.sub(r"\s+", " ", head[:300]), "decision": dec, "class": cls, "reason": why,
                   "municipality_id": muni["municipality_id"] if muni else None, "municipality_source": msrc}
            notices.append(rec)
            if dec != "kept":
                excl.append({k: rec[k] for k in ("gazette", "gazette_date", "notice", "toc_title", "class", "reason", "municipality_id", "source_url", "pages")}
                            | {"heading": rec["heading"][:200]})
                continue
            text = norm_text(re.sub(r"^.*PROVINCIAL GAZETTE / PROVINSIALE KOERANT.*$\n?|^[ \t]*_{10,}[ \t]*$\n?|^[ \t]*-{20,}[ -]*$\n?", "", s["text"], flags=re.M))
            title = notice_title(s, tt, muni)
            mslug = slug(muni["aliases"][0]) if muni else "fs"
            lid = f"za-muni-fs-{mslug}-{slug(title)[:90]}-{slug(nno)}"[:200]
            assert lid not in live_ids and lid not in {r['id'] for r in laws}, lid
            secs, how = resplit(text)
            pg = [p for p in g["pages"] if p["page"] in s["pages"]]
            ocrp = [p for p in pg if p["source"] == "ocr"]
            ws = sum(p.get("words") or 0 for p in ocrp)
            backend = "pdftotext" if not ocrp else ("ocr_tesseract_eng" if len(ocrp) == len(pg) else "pdftotext+ocr_tesseract_eng")
            mcols = {"municipality_id": muni["municipality_id"] if muni else "", "municipality_name": muni["name"] if muni else "",
                     "wikidata_qid": muni["wikidata_qid"] if muni else "", "province": "Free State"}
            sk = re.sub(r"\s+", " ", re.sub(r"\b(19|20)\d\d\b|\bby-?laws?\b|\bmunicipality\b|\blocal\b|\bthe\b|\bof\b|\band\b", " ", title.lower())).strip()
            meta = {"schema_version": "collection_record.v1", "record_type": "law", "law_identifier": lid, "source": "fsonline",
                    "work_key": f"{g['url']}#{slug(nno)}", "listing_url": LISTING, "list_title": g["title"], "gazette": "Free State Provincial Gazette",
                    "gazette_number": str(g["no"] or ""), "gazette_date": gdate, "notice_number": nno, "notice_type": typ,
                    "notice_class": cls, "toc_title": tt, "municipality": muni["name"] if muni else None,
                    "municipality_attribution": msrc, "municipality_note": mnote or None, "source_pdf_url": g["url"],
                    "source_pdf_sha256": g["sha256"], "pdf_pages": s["pages"], "province_code": "ZA-FS",
                    "text_backend": backend, "text_source": backend, "subject_key": sk, "year": y,
                    "admin_level": muni["admin_level"] if muni else None, "publisher": "Free State Provincial Government (Provincial Gazette)",
                    "source_terms_note": TERMS, "batch": 5, "parser_version": PARSER_VERSION}
            if not muni:
                meta["qid_note"] = "municipality not confidently identified; wikidata_qid left empty"
            if ocrp:
                meta["ocr"] = {"engine": "tesseract", "lang": "eng", "dpi": 250, "pages_ocr": [p["page"] for p in ocrp],
                               "mean_conf": round(sum((p.get("conf") or 0) * (p.get("words") or 0) for p in ocrp) / ws, 1) if ws else None}
                meta["note"] = "Some pages OCR'd (tesseract, eng); OCR text may contain recognition errors."
            fd = fetch.get(g["url"], {})
            laws.append({"id": lid, "title": title, "text": text, "source_url": g["url"], "source_type": "za_provincial_gazette_fs",
                         "jurisdiction": "ZA", "country": "South Africa", "language": "en", "eli": f"{g['url']}#{slug(nno)}",
                         "date": gdate, "date_issued": gdate, "retrieved_at": fd.get("fetched_at", ""), "license": LICENSE,
                         "law_status": "as_gazetted", "identifier": nno, "official_identifier": nno, "article_count": 0, "json_path": "",
                         "metadata_json": meta, "notice_number": nno, "gazette_number": str(g["no"] or ""), "gazette_date": gdate,
                         "commencement_date": "", "effective_date": "", "source_terms_note": TERMS, **mcols})
            if secs:
                na = []
                for x in secs:
                    aid = f"{lid}-s-{slug(str(x['num']))}"[:200]
                    na.append({"law_id": lid, "id": aid, "title": x["title"], "text": x["text"], "source_url": g["url"],
                               "document_number": f"section {x['num']}", "article_number": f"section {x['num']}", "record_type": "article",
                               "metadata_json": json.dumps({"law_identifier": lid, "kind": "section"}), **mcols})
            else:
                na = [{"law_id": lid, "id": f"{lid}-a001", "title": title, "text": text, "source_url": g["url"], "document_number": nno,
                       "article_number": None, "record_type": "whole_text",
                       "metadata_json": json.dumps({"law_identifier": lid, "kind": "whole_text", "whole_text": True}), **mcols}]
            laws[-1]["article_count"] = len(na)
            laws[-1]["metadata_json"]["section_split"] = how
            arts += na
            rec["law_id"] = lid; rec["articles"] = len(na); rec["title"] = title
    for r in laws:
        r["metadata_json"] = json.dumps(r["metadata_json"], ensure_ascii=False)
    ids = [r["id"] for r in laws]; aids = [a["id"] for a in arts]
    assert len(set(ids)) == len(ids) and len(set(aids)) == len(aids) and not (set(ids) & live_ids)
    (pack / "data").mkdir(parents=True, exist_ok=True); (pack / "manifests").mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(laws, schema=LT.schema), pack / "data/laws-00003.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(arts, schema=AT.schema), pack / "data/articles-00003.parquet", compression="zstd")
    with open(pack / "manifests/batch5_fs_notices.jsonl", "w") as fh:
        for x in notices:
            fh.write(json.dumps(x, ensure_ascii=False) + "\n")
    with open(pack / "manifests/batch5_fs_exclusions.jsonl", "w") as fh:
        for x in excl:
            fh.write(json.dumps(x, ensure_ascii=False) + "\n")
    used = Counter(r["municipality_id"] or "(unattributed)" for r in laws)
    (pack / "manifests/batch5_fs_municipalities.json").write_text(json.dumps({
        "province": "Free State", "qid_source": "Wikidata (label exact match + P31 local/metropolitan/district municipality + P131 check, 2026-10-04)",
        "municipalities": [{**{k: m[k] for k in ("municipality_id", "demarcation_code", "name", "admin_level", "district", "wikidata_qid", "qid_check")},
                            "laws": used.get(m["municipality_id"], 0)} for m in ms],
        "unattributed_laws": used.get("(unattributed)", 0),
        "qid_coverage": f"{sum(1 for r in laws if r['wikidata_qid'])}/{len(laws)}"}, indent=1, ensure_ascii=False))
    summ = {"gazettes": len(gazettes), "pages": sum(len(g["pages"]) for g in gazettes),
            "pages_ocr": sum(p["source"] == "ocr" for g in gazettes for p in g["pages"]),
            "pages_blank": sum(p["source"] == "blank" for g in gazettes for p in g["pages"]),
            "notices_found": sum(1 for n in notices if n.get("notice")), "kept": len(laws), "articles": len(arts),
            "kept_by_class": dict(Counter(n["class"] for n in notices if n.get("decision") == "kept")),
            "kept_by_municipality": dict(used), "excluded_by_class": dict(Counter(x["class"] for x in excl)),
            "laws_with_ocr_pages": sum(1 for r in laws if "ocr" in r["metadata_json"])}
    (STAGE / "stage_summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
