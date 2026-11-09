#!/usr/bin/env python3
"""Build ipfs_south_africa_municipal_laws batch parquet from /dev/shm/muni_africa/za/records.jsonl (offline, no fetch).

Selection (CoS rulings 2026-10-04): promulgated by-laws and tariff by-laws only; no drafts / out-for-comment /
fine schedules / forms / policies / language duplicates. Ekurhuleni 'Municipal Code' (index PDF) supplies effective
dates + in-force list. Buffalo City multi-notice gazettes are split per notice. Repeat versions of the same by-law are
deduped (latest kept, superseded versions recorded in the manifest). Ids injective; asserts: unique law ids, unique
work keys (source_url#notice), 0 orphan articles. Schema = KE pack + province / gazette / notice / commencement cols.
"""
import hashlib, json, os, re, sys, unicodedata
from collections import defaultdict
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq

STAGE = Path(os.environ.get("MUNI_STAGE", "/dev/shm/muni_africa/za"))
BATCH = int(os.environ.get("ZA_BATCH", "1"))
REPO = STAGE / "hf" / "ipfs_south_africa_municipal_laws"
PRIOR_IDS_DIR = Path(os.environ.get("ZA_PRIOR_IDS_DIR", str(Path(__file__).resolve().parent / "seeds")))  # batchN_law_ids.txt of live batches
HUB_PARENT = os.environ.get("ZA_HUB_PARENT", "e08ede82745cae32e107fbd6b958dd09c63b8a6c")
OUT, MAN = REPO / "data", REPO / "manifests"

METROS = {
    "eth": {"name": "eThekwini Metropolitan Municipality", "short": "eThekwini Municipality", "qid": "Q311544",
            "province": "KwaZulu-Natal", "province_code": "ZA-KZN",
            "terms": "durban.gov.za: footer claims all rights reserved; the linked Terms & Conditions page carries no substantive "
                     "reuse or automated-access terms (checked 2026-10-04)."},
    "ekh": {"name": "City of Ekurhuleni Metropolitan Municipality", "short": "City of Ekurhuleni", "qid": "Q326891",
            "province": "Gauteng", "province_code": "ZA-GP",
            "terms": "ekurhuleni.gov.za Terms and Conditions: generic statement that site content is owned by the City and protected "
                     "by copyright/IP law; no explicit reuse prohibition or automated-access clause (checked 2026-10-04)."},
    "bcm": {"name": "Buffalo City Metropolitan Municipality", "short": "Buffalo City Metropolitan Municipality", "qid": "Q1002006",
            "province": "Eastern Cape", "province_code": "ZA-EC",
            "terms": "buffalocity.gov.za Terms of Use: boilerplate template reserving all rights in site contents; no personal-use-only, "
                     "reuse-ban or automated-access clause (checked 2026-10-04)."},
    "tsh": {"name": "City of Tshwane Metropolitan Municipality", "short": "City of Tshwane", "qid": "Q1094207",
            "province": "Gauteng", "province_code": "ZA-GP",
            "terms": "tshwane.gov.za: no terms-of-use, disclaimer or copyright page found; site footer links only the PAIA manual "
                     "(checked 2026-10-04). By-laws published as scanned Provincial Gazette extracts; text obtained by OCR."},
}


def licence(metro):
    return (f"Official municipal by-law text published by {METROS[metro]['short']}; official texts of a legislative, "
            "administrative or legal nature are excluded from copyright under s12(8)(a) of the Copyright Act 98 of 1978; "
            "site terms claim general copyright over site content.")


MONTHS = "JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER"
MON_RX = rf"\d{{1,2}}\s*(?:{MONTHS})\s+\d{{4}}"


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ------------------------------------------------------------- KE-style section split (same as stage/collect KE)
SEC_LINE = re.compile(r"(?m)^[ \t]*(\d{1,3}[A-Z]?)\.[ \t]+([A-Z][^\n]{1,160})$")


def split_sections(text):
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


def split_sections_chain(text, min_gap=60):
    """OCR documents (Tshwane gazette scans): pick the longest chain of 'N. HEADING' lines whose numbers increase
    by 1-3 with at least `min_gap` characters of body between consecutive headings. This skips the table of
    contents (adjacent lines) and stray numbered list items, and keeps the by-law's own section sequence."""
    ms = list(SEC_LINE.finditer(text or ""))
    if len(ms) < 2:
        return []
    nums = [int(re.match(r"\d+", m.group(1)).group()) for m in ms]
    best, prev = [1] * len(ms), [-1] * len(ms)
    for i in range(len(ms)):
        for j in range(max(0, i - 400), i):
            d = nums[i] - nums[j]
            if (1 <= d <= 3 or (d == 0 and ms[i].group(1)[-1:].isalpha())) and ms[i].start() - ms[j].end() >= min_gap \
                    and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    end = max(range(len(ms)), key=lambda k: (best[k], -k))
    chain = []
    while end != -1:
        chain.append(end); end = prev[end]
    chain.reverse()
    if len(chain) < 2 or nums[chain[0]] > 3:
        return []
    out = []
    for k, i in enumerate(chain):
        m = ms[i]
        stop = ms[chain[k + 1]].start() if k + 1 < len(chain) else len(text)
        out.append({"num": m.group(1), "title": f"{m.group(1)}. {m.group(2).strip()}"[:200], "text": text[m.start():stop].strip()})
    return out


OCR_HEAD = re.compile(r"(?m)^[ \t]*(?:(\d{1,3}[A-Z]?)[.,][ \t]+)?([A-Z][A-Z0-9 ,'\u2019()/&:;-]{3,110}?)[ \t]*$")
RUNNING_HEAD = re.compile(r"BY-LAW,? \d{4} \(AMENDED|^(?:THE )?(?:CITY OF )?(?:TSHWANE )?(?:LAND USE )?(?:MANAGEMENT )?BY-LAW,? \d{4}|^(?:CITY OF|TSHWAN\w*)$")
OCR_HEAD_SKIP = re.compile(r"GAZETTE|KOERANT|GPWONLINE|^(?:CHAPTER|HOOFSTUK|PART)\b|^[IVXL]+$")


def split_sections_ocr(text, min_body=150):
    """OCR'd gazette scans lose the margin numbering (tesseract puts the 'N.' column in its own block), so split
    on ALL-CAPS heading lines instead. Headings whose body is shorter than `min_body` non-space characters (table of
    contents lines, stacked chapter titles) do not start a block. Blocks get ordinal ids; 'N.' is kept when present."""
    text = text or ""
    cand = [m for m in OCR_HEAD.finditer(text)
            if sum(ch.isalpha() for ch in m.group(2)) >= 6 and not OCR_HEAD_SKIP.search(m.group(2).strip())]
    # running page headers (the same caps line on many pages, e.g. "CITY OF TSHWANE ... BY-LAW, 2016 (AMENDED 2024)")
    freq = {}
    for m in cand:
        freq[m.group(2).strip()] = freq.get(m.group(2).strip(), 0) + 1
    hs = [m for m in cand if freq[m.group(2).strip()] < 4 and not RUNNING_HEAD.search(m.group(2))]
    keep = []
    for i, m in enumerate(hs):
        stop = hs[i + 1].start() if i + 1 < len(hs) else len(text)
        if len(re.sub(r"\s", "", text[m.end():stop])) >= min_body:
            keep.append(m)
    out = []
    for k, m in enumerate(keep):
        stop = keep[k + 1].start() if k + 1 < len(keep) else len(text)
        head = m.group(2).strip()
        out.append({"num": m.group(1) or "", "ordinal": k + 1, "kind": "heading_block",
                    "title": (f"{m.group(1)}. {head}" if m.group(1) else head)[:200], "text": text[m.start():stop].strip()})
    return out if len(out) >= 2 else []


def split_sections_tsh(text, is_ocr):
    if not is_ocr:
        return split_sections(text) or split_sections_chain(text)
    chain, blocks = split_sections_chain(text), split_sections_ocr(text)
    if len(chain) >= 3 and len(chain) >= 0.6 * len(blocks):
        return chain
    return blocks or chain


# ------------------------------------------------------------- helpers
def norm_text(t):
    return re.sub(r"[ \t]+\n", "\n", (t or "").replace("\f", "\n")).strip()


def first_page(t):
    return (t or "").split("\f", 1)[0]


def gazette_meta(t):
    head = (t or "")[:6000]
    g = {}
    m = re.search(r"Vol\.?\s*\d+\s+(" + MON_RX + r")\s+No\.?\s*(\d{3,5})", head, re.I | re.S)
    if m:
        g["gazette_date"], g["gazette_number"] = re.sub(r"\s+", " ", m.group(1)).title(), m.group(2)
    m2 = re.search(r"No\.\s*(\d{3,5})\s+PROVINCIAL GAZETTE(?: EXTRAORDINARY)?,\s*(" + MON_RX + ")", head, re.I) or \
        re.search(r"PROVINCIAL GAZETTE(?: EXTRAORDINARY)?,\s*(" + MON_RX + r")\s+No\.\s*(\d{3,5})", head, re.I)
    if m2 and "gazette_number" not in g:
        a, b = m2.group(1), m2.group(2)
        num, dt = (a, b) if a.isdigit() else (b, a)
        g["gazette_number"], g["gazette_date"] = num, re.sub(r"\s+", " ", dt).title()
    if "gazette_number" not in g:
        m3 = re.search(r"(?:Provincial\s+Gazette|Gazette)(?:\s+Extraordinary)?\s*(?:No\.?|Number|no)\s*(\d{2,5})", head, re.I)
        if m3:
            g["gazette_number"] = m3.group(1)
    return g


def commencement(t, extra=""):
    for rx in (r"Date of Commencement\s*:?\s*([0-9]{1,2}[\s\-/]*[A-Za-z]+[\s\-/]*\d{4}|\d{1,2}/\d{1,2}/\d{4})",
               r"commencement[- ]date[- ](\d{1,2}[- ][a-z]+[- ]\d{4})",
               r"promulgated[- ]on[- ](\d{1,2}[- ][a-z]+[- ]\d{4})",
               r"Commencement Date\s*:?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})"):
        for src in (extra, (t or "")[:8000]):
            m = re.search(rx, src or "", re.I)
            if m:
                return re.sub(r"[\s\-]+", " ", m.group(1)).strip().title()
    return ""


def years_in(s):
    return [int(y) for y in re.findall(r"(?<!\d)(19[5-9]\d|20[0-3]\d)(?!\d)", s or "")]


def is_draft(t, title):
    head = (t or "")[:2500]
    if re.search(r"\bdraft\b", title or "", re.I):
        return True
    return bool(re.search(r"(?m)^\s*(?:PROPOSED\s+)?DRAFT\b", head)) or bool(
        re.search(r"for (?:public )?comment|invites? (?:the public|comments)|public participation process", head, re.I)) and \
        not re.search(r"promulgat|hereby publishes|Date of Commencement", head, re.I)


# ------------------------------------------------------------- Buffalo City per-notice split
NOTICE_HEAD = re.compile(r"(?m)^[ \t]*((?:LOCAL AUTHORITY|PROVINCIAL|MUNICIPAL|GENERAL) NOTICE)\s+(\d{1,5})(?:\s+OF\s+(\d{4}))?[ \t]*$", re.I)
CONTENTS_LINE = re.compile(r"(?m)^[ \t]*(\d{1,5})[ \t]+(.+?)[ \t]{2,}(\d{1,4})[ \t]+(\d{3,5})[ \t]*$")


def split_notices(text):
    """Return list of (notice_kind, notice_no, notice_year, segment_text, contents_title)."""
    contents = {m.group(1): re.sub(r"\s+", " ", m.group(2)).strip() for m in CONTENTS_LINE.finditer(text[:20000])}
    heads = list(NOTICE_HEAD.finditer(text))
    segs = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        segs.append((m.group(1).upper(), m.group(2), m.group(3) or "", text[m.start():end], contents.get(m.group(2), "")))
    return segs, contents


def heading_title(seg, metro):
    """First heading-like line naming a by-law/tariff within the first lines of a segment."""
    lines = [l.strip() for l in seg.splitlines()[:80] if l.strip()]
    for l in lines:
        if re.search(r"BY-?\s?LAWS?|BYLAWS?|TARIFF", l, re.I) and len(l) < 160 and not re.search(
                r"PROVINCIAL GAZETTE|^\d+\s+No\.|hereby|in terms of|whereas|council of|^\(?\d+\)", l, re.I):
            return re.sub(r"\s+", " ", l)
    return ""


# ------------------------------------------------------------- Ekurhuleni Municipal Code index
DATE_RX = re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4})")
RES_RX = re.compile(r"\b([A-Z]{1,4}\s*[-–]\s*[A-Z&]{1,6}\s*\(?[\d\s&\-–]+(?:-\s*\d{2,4})?\)?|PS\s*\d+/\d{4})")


def parse_municipal_code(text):
    """Very tolerant table reader: rows are anchored on an effective date (dd/mm/yyyy); name fragments are the
    left-most column text on that line and the lines since the previous anchor."""
    entries, buf = [], []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        cols = [c for c in re.split(r"\s{2,}", line.strip()) if c]
        d = DATE_RX.search(line)
        if d and cols:
            name_parts = buf + [c for c in cols if not DATE_RX.search(c) and not RES_RX.fullmatch(c.strip())][:1]
            res = RES_RX.search(line)
            entries.append({"name": re.sub(r"\s+", " ", " ".join(name_parts)).strip()[:200],
                            "effective": d.group(1), "resolution": res.group(1).strip() if res else ""})
            buf = []
        else:
            if cols and len(cols[0]) < 60 and not re.search(r"BY-LAW\s+COUNCIL|RESOLUTION|EFFECTIVE|RESPONSIBLE|DEPARTMENT|MUNICIPAL CODE|Page \d", cols[0], re.I):
                buf = (buf + [cols[0]])[-3:]
    return entries


STOP = {"by", "law", "laws", "bylaw", "bylaws", "the", "of", "and", "for", "city", "ekurhuleni", "metropolitan",
        "municipality", "municipal", "amended", "amendment", "s"}


def toks(s):
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", (s or "").lower()) if w not in STOP and len(w) > 2}


def match_code(title, entries):
    tt = toks(title)
    best, score = None, 0.0
    for e in entries:
        et = toks(e["name"])
        if not et or not tt:
            continue
        j = len(tt & et) / len(tt | et)
        if j > score:
            best, score = e, j
    return (best, score) if score >= 0.5 else (None, score)


# ------------------------------------------------------------- titles / subject keys
def eth_title(slug_title, text):
    s = slug_title.lower()
    s = re.sub(r"-?(commencement-date|promulgated-on|adopted-by-council-on).*$", "", s)
    s = re.sub(r"-?(english|mn-\d+-of-\d{4}|notice-\d+-of-\d{4})", "", s)
    s = re.sub(r"^local-government-municipal-systems-act-32-2000-ethekwini-municipality-", "", s)
    words = [w for w in s.split("-") if w]
    t = " ".join(words).title()
    t = re.sub(r"\bBy Laws?\b|\bBylaws?\b", "By-law", t)
    yr = re.search(r"\b(19|20)\d\d\b", t)
    if "By-law" not in t:
        t = (re.sub(r"\s*\b(19|20)\d\d\b", "", t) + " By-law" + (f", {yr.group(0)}" if yr else "")).strip()
    else:
        t = re.sub(r"By-law\s+((19|20)\d\d)", r"By-law, \1", t)
    return t


def subject_key(title):
    s = (title or "").lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"local government:? municipal systems act.*?:", " ", s)
    s = re.sub(r"\b(19|20)\d\d\b|\b\d+\b", " ", s)
    s = re.sub(r"buffalo city|ethekwini|ekurhuleni|durban|bcmm?|metropolitan|municipality|municipal|national|"
               r"the|of|and|for|in|rationali[sz]ed|as amended|updated|old|new|bylaws?|by-?\s?laws?|english|gazette|prov|no", " ", s)
    s = re.sub(r"debt (collection|management)", " ", s)
    s = s.replace("recreational", "recreation").replace("establishments", "establishment").replace("tariffs", "tariff")
    ws = [w.rstrip("s") for w in re.findall(r"[a-z]+", s) if len(w) > 1]
    amend = any(w.startswith("amend") for w in ws)
    ws = [w for w in ws if not w.startswith("amend") and w not in {"first", "second", "third", "rd", "nd", "st", "th", "further"}]
    key = " ".join(ws)
    if amend:  # amendment by-laws are distinct instruments: keep their ordinal / year in the key
        key += " | amendment " + " ".join(re.findall(r"(first|second|third|3rd|2nd|further|\b(?:19|20)\d\d\b)", title.lower()))
    return key.strip()


# ------------------------------------------------------------- Tshwane (scanned gazette extracts; titles carry Pg/Lan/date)
MON3 = {m[:3]: i + 1 for i, m in enumerate(MONTHS.split("|"))}


def _date_str(d, mon, y):
    mi = MON3.get(mon[:3].upper()) if not mon.isdigit() else int(mon)
    if not mi or not (1 <= int(d) <= 31):
        return ""
    return f"{int(d)} {MONTHS.split('|')[mi - 1].title()} {y}"


def tsh_title_meta(lt, url):
    """Parse gazette number (Pg/Pge/Gaz/Gazette/Prov Gaz No), notice number (Lan N) and date from the list title
    (or the upload filename for direct /wp-content links)."""
    s = re.sub(r"[_]+", " ", lt)
    fn = re.sub(r"[_]+", " ", url.rsplit("/", 1)[-1]) if "/wp-content/" in url else ""
    out = {}
    # a direct upload's filename describes the file actually served (its link text can be stale): filename first
    for src in ((fn, s) if fn else (s,)):
        if "gazette_number" not in out:
            m = re.search(r"(?<![A-Za-z])(?:Pge?|Gaz(?:ette)?|Provincial Gazette|Prov\.? Gaz\.?)\s*(?:No\.?\s*)?(\d{1,4})(?!\d)", src, re.I)
            if m:
                out["gazette_number"] = m.group(1)
        if "lan" not in out:
            m = re.search(r"(?<![A-Za-z])Lan\.?\s*(\d{1,5})(?!\d)", src, re.I)
            if m:
                out["lan"] = m.group(1)
        if "gazette_date" not in out:
            m = (re.search(r"(\d{1,2})\s*(" + "|".join(k.title() for k in MON3) + r")[a-z]*\.?\s*(\d{4})", src) or
                 re.search(r"(\d{1,2})\s*(" + "|".join(MON3) + r")[A-Z]*\s*(\d{4})", src))
            if m:
                out["gazette_date"] = _date_str(m.group(1), m.group(2), m.group(3))
            else:
                m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", src) or re.search(r"\b(\d{4})(\d{2})(\d{2})\b", src)
                if m:
                    a, b, c = m.groups()
                    out["gazette_date"] = _date_str(c, b, a) if len(a) == 4 else _date_str(a, b, c)
        if src is fn and fn and out:
            break          # filename carried gazette metadata: ignore the (possibly stale) link text entirely
    return out


def tsh_clean_title(lt):
    t = re.sub(r"[_]+", " ", lt).strip()
    t = re.split(r"\s+(?:-\s+)?(?:Pge?\b|Lan\b|Gazette\b|Provincial Gazette\b|Prov Gaz\b)", t, maxsplit=1)[0]
    t = re.sub(r"\s+-\s*(?:\d{1,2}\s+\w+\s+)?\d{4}.*$", "", t).strip(" -,")
    t = re.sub(r"\bBy[- ]\s?Laws\b|\bBylaws\b|\bBy Laws\b", "By-laws", t, flags=re.I)
    t = re.sub(r"\bBy[- ]\s?Law\b|\bBylaw\b", "By-law", t, flags=re.I)
    return re.sub(r"\s+", " ", t)


# (regex over list title + upload filename, alias key, canonical title). First match wins; order matters.
TSH_ALIASES = [
    (r"LUMByLaw2016Amend", "lum-2024-amendment", "Tshwane Land Use Management Amendment By-law, 2024"),
    (r"land use management", "land-use-management-2016", "Tshwane Land Use Management By-law, 2016"),
    (r"air quality", "air-quality", "Air Quality By-law"),
    (r"outdoor advertising", "outdoor-advertising", "Outdoor Advertising By-law"),
    (r"handheld parking", "handheld-parking-meter", "Handheld Parking Meter By-law"),
    (r"derelict", "derelict-buildings", "By-laws on Derelict Buildings"),
    (r"public participation", "public-participation", "Public Participation By-law"),
    (r"petition", "petitions", "By-laws on Petitions"),
    (r"\bbees\b", "keeping-bees", "Keeping of Bees By-law"),
    (r"cemeter|cremat", "cemeteries-crematoria", "Cemeteries and Crematoria By-law"),
    (r"child care", "child-care-services", "Health By-law for Child Care Services"),
    (r"keeping (?:of )?animals|animals,? birds", "keeping-animals-birds-poultry", "Health By-laws Relating to the Keeping of Animals, Birds and Poultry"),
    (r"initiation school", "initiation-schools", "Health By-laws for the Operation and Management of Initiation Schools"),
    (r"youth development", "youth-development", "Youth Development By-law"),
    (r"fire brigade|\bfbs\b", "fire-brigade-services", "Fire Brigade Services By-law"),
    (r"credit control", "credit-control", "Credit Control By-law"),
    (r"electricity", "electricity-supply", "Standard Electricity Supply By-laws"),
    (r"fifa", "fifa-2010", "FIFA 2010 World Cup By-law"),
    (r"green building|\b79\b.*\b328\b", "green-building", "Green Building Development By-law"),
    (r"elderly", "homes-for-the-elderly", "Health By-laws for Homes for the Elderly"),
    (r"imsd|internal municipal service district", "imsd", "Internal Municipal Service District By-law"),
    (r"librar", "library-services", "Library Services By-laws"),
    (r"flats", "flats", "Management and Control of Flats By-laws"),
    (r"hostel", "hostels", "Management and Control of Hostels By-laws"),
    (r"property rates", "property-rates", "Property Rates By-law"),
    (r"public amenit", "public-amenities", "Public Amenities By-laws"),
    (r"rules and orders", "rules-and-orders", "Rules and Orders By-laws"),
    (r"sanitation", "sanitation", "Sanitation By-laws"),
    (r"substance abuse", "substance-abuse", "Substance Abuse By-laws"),
    (r"tshwane market", "tshwane-market", "Tshwane Market By-laws"),
    (r"ward committee", "ward-committee", "Ward Committee By-law"),
    (r"waste man|waste mang", "waste-management", "Waste Management By-law"),
    (r"water supply", "water-supply", "Water Supply By-laws"),
    (r"road reserve", "work-in-road-reserve", "Work in the Public Road Reserve By-laws"),
]
LUM24_PART = re.compile(r"LUMByLaw2016Amend\w*?(FrontPage|Part(\d))", re.I)


def tsh_alias(lt, url):
    s = lt + " " + (url.rsplit("/", 1)[-1] if "/wp-content/" in url else "")
    for rx, key, canon in TSH_ALIASES:
        if re.search(rx, s, re.I):
            return key, canon
    return None, None


def tsh_candidates(trecs, drops):
    """Tshwane: one candidate per document, except the 2024 LUM amendment (FrontPage + Part1-3, Gazette 106 of
    27 March 2024) which is merged into one law. OCR provenance kept per candidate."""
    cands, lum = [], []
    for url, r in trecs:
        lt = r["list_title"]
        if r.get("duplicate_of"):
            drops["tsh"].append({"url": url, "title": lt, "reason": "byte_identical_repeat", "duplicate_of": r["duplicate_of"]})
            continue
        if r.get("text_backend") in ("ocr_skipped_unreadable_pdf", "ocr_skipped_too_many_pages"):
            drops["tsh"].append({"url": url, "title": lt, "reason": r["text_backend"], "pages": r.get("pages")})
            continue
        if LUM24_PART.search(lt):
            lum.append((url, r))
            continue
        key, canon = tsh_alias(lt, url)
        tm = tsh_title_meta(lt, url)
        gm = gazette_meta(r.get("text") or "")
        if not tm.get("lan"):                     # notice number from the OCR text when the title lacks 'Lan N'
            nh = NOTICE_HEAD.search((r.get("text") or "")[:8000])
            if nh and re.match(r"local authority", nh.group(1), re.I):
                tm["lan"] = nh.group(2)
                if nh.group(3) and not tm.get("gazette_date"):
                    tm["notice_year_text"] = nh.group(3)
        c = {"metro": "tsh", "source_url": url, "final_url": r.get("final_url"), "doc_url": url, "listing_url": r["listing_url"], "list_title": lt,
             "list_date": r.get("list_date"), "retrieved_at": r["retrieved_at"], "pages": r.get("pages"),
             "text_backend": r.get("text_backend"), "no_text_layer": bool(r.get("no_text_layer")), "bytes": r.get("bytes"),
             "title": tsh_clean_title(lt), "canonical_title": canon, "alias_key": key, "text": norm_text(r.get("text")),
             "notice_kind": "Local Authority Notice" if tm.get("lan") else "", "notice_number": tm.get("lan", ""),
             "notice_year": ((years_in(tm.get("gazette_date", "")) or [tm.get("notice_year_text", "")])[0]) if tm.get("lan") else "",
             "contents_title": "", "gazette_number": tm.get("gazette_number") or gm.get("gazette_number", ""),
             "gazette_date": tm.get("gazette_date") or gm.get("gazette_date", ""), "title_meta": bool(tm),
             "ocr": _ocr_info([r])}
        cands.append(c)
    if lum:
        order = lambda ur: (0 if "frontpage" in ur[1]["list_title"].lower() else 1,
                            int((LUM24_PART.search(ur[1]["list_title"]).group(2) or 0)))
        lum.sort(key=order)
        u0, r0 = lum[0]
        tm = tsh_title_meta(r0["list_title"], u0)
        cands.append({"metro": "tsh", "source_url": u0, "final_url": r0.get("final_url"), "doc_url": u0, "listing_url": r0["listing_url"],
                      "list_title": " + ".join(r["list_title"] for _, r in lum), "list_date": "", "retrieved_at": max(r["retrieved_at"] for _, r in lum),
                      "pages": sum((r.get("pages") or 0) for _, r in lum), "text_backend": r0.get("text_backend"),
                      "no_text_layer": True, "bytes": sum((r.get("bytes") or 0) for _, r in lum),
                      "title": TSH_ALIASES[0][2], "canonical_title": TSH_ALIASES[0][2], "alias_key": "lum-2024-amendment",
                      "text": "\n\n".join(norm_text(r.get("text")) for _, r in lum),
                      "notice_kind": "", "notice_number": "", "notice_year": "", "contents_title": "",
                      "gazette_number": tm.get("gazette_number", "106"), "gazette_date": tm.get("gazette_date", "27 March 2024"),
                      "title_meta": True, "merged_parts": [{"url": u, "list_title": r["list_title"], "pages": r.get("pages")} for u, r in lum],
                      "ocr": _ocr_info([r for _, r in lum])})
    return cands


def _ocr_info(rs):
    if not any(r.get("text_backend") == "ocr_tesseract_eng" for r in rs):
        return None
    w = sum((r.get("pages") or 0) for r in rs)
    mean = sum((r.get("ocr_mean_conf") or 0) * (r.get("pages") or 0) for r in rs) / w if w else None
    pcs = [c for r in rs for c in (r.get("ocr_page_conf") or []) if c is not None]
    return {"engine": "tesseract", "lang": "eng", "dpi": rs[0].get("ocr_dpi"), "mean_conf": round(mean, 1) if mean is not None else None,
            "min_page_conf": min(pcs) if pcs else None, "pages": w}


# ------------------------------------------------------------- main
def main():
    recs = {}
    for line in open(STAGE / "records.jsonl"):
        r = json.loads(line)
        recs[r["url"]] = r
    listed = defaultdict(int)
    if (STAGE / "listings.jsonl").exists():
        latest = {}
        for line in open(STAGE / "listings.jsonl"):
            L = json.loads(line)
            if L.get("batch", 1) == BATCH:
                latest[L["metro"]] = L
        for m, L in latest.items():
            listed[m] = len(L["items"])
    drops = defaultdict(list)       # metro -> [{url,title,reason}]
    code_entries = []
    cands = []                      # candidate law dicts before dedupe
    trecs = []                      # Tshwane records (handled by tsh_candidates)
    batch_metros = set()
    # Records of earlier (Hub-live) batches are re-run through the same pipeline only so that repeat versions /
    # same-subject items in this batch are detected against them; only rows of THIS batch are emitted.
    for url, r in recs.items():
        m = r["metro"]
        rb = r.get("batch", 1)
        if rb > BATCH:
            continue
        if rb == BATCH:
            batch_metros.add(m)
        dropsink = drops if rb == BATCH else defaultdict(list)
        if r.get("status") == "predropped":
            dropsink[m].append({"url": url, "title": r["list_title"], "reason": r["drop_reason"]})
            continue
        if r.get("status") != 200:
            dropsink[m].append({"url": url, "title": r["list_title"], "reason": f"fetch_{r.get('status')}"})
            continue
        if m == "tsh":
            trecs.append((url, r))
            continue
        _ncand = len(cands)
        _one_record(url, r, m, rb, cands, dropsink, code_entries)
        for c in cands[_ncand:]:
            c["batch"] = rb
    for c in tsh_candidates([t for t in trecs if t[1].get("batch", 1) == BATCH], drops):
        c["batch"] = BATCH
        cands.append(c)
    code_entries = code_entries[0] if code_entries and isinstance(code_entries[0], list) else code_entries
    _classify_dedupe_emit(cands, drops, listed, code_entries, batch_metros)


def _one_record(url, r, m, rb, cands, drops, code_holder):
        text = r.get("text") or ""
        if m == "ekh" and re.search(r"municipal code", r["list_title"], re.I):
            code_holder[:] = [parse_municipal_code(text)]
            drops[m].append({"url": url, "title": r["list_title"], "reason": "index_municipal_code (used for effective dates)"})
            return
        lt = r["list_title"]
        base = {"metro": m, "source_url": r.get("final_url") or url, "listing_url": r["listing_url"], "list_title": lt,
                "list_date": r.get("list_date"), "retrieved_at": r["retrieved_at"], "pages": r.get("pages"),
                "text_backend": r.get("text_backend"), "no_text_layer": bool(r.get("no_text_layer")), "bytes": r.get("bytes")}
        if m == "bcm" and re.search(r"policy|_polic", lt, re.I):
            drops[m].append({"url": url, "title": lt, "reason": "policy"})
            return
        segs, contents = split_notices(text) if m == "bcm" else ([], {})
        bylaw_segs = []
        for kind, no, yr, seg, ctitle in segs:
            t_head = heading_title(seg, m)
            label = ctitle or t_head
            if not re.search(r"by-?\s?laws?|bylaws?|tariff", label + " " + t_head, re.I):
                continue
            if re.search(r"municipalit", ctitle, re.I) and not re.search(r"buffalo", ctitle, re.I):
                continue
            bylaw_segs.append((kind, no, yr, seg, ctitle, t_head))
        gm = gazette_meta(text)
        if bylaw_segs:
            for kind, no, yr, seg, ctitle, t_head in bylaw_segs:
                title = t_head.title() if t_head else ctitle.split(":")[-1].strip()
                if ctitle and t_head and len(t_head) < 25:  # bare 'NOISE BY-LAW' -> use contents wording
                    title = ctitle.split(":")[-1].strip() or t_head.title()
                title = re.sub(r"\bBy-Laws?\b|\bBylaws?\b", lambda x: "By-laws" if x.group(0).lower().endswith("s") else "By-law", title)
                cands.append({**base, "title": title, "text": norm_text(seg), "notice_kind": kind.title(), "notice_number": no,
                              "notice_year": yr, "contents_title": ctitle, **gm})
            return
        if m == "bcm" and segs and not bylaw_segs and not re.search(r"by-?\s?law|bylaw|tariff", lt, re.I):
            drops[m].append({"url": url, "title": lt, "reason": "other_notice_no_bylaw"})
            return
        if m == "eth":
            title = eth_title(lt, text)
        elif m == "ekh":
            title = lt
        else:
            title = heading_title(text, m).title() or re.sub(r"[_\-]+", " ", re.sub(r"\.pdf$", "", lt, flags=re.I)).strip()
            title = re.sub(r"\bBy-Laws?\b|\bBylaws?\b|\bBy Laws?\b", "By-law", title)
        nh = NOTICE_HEAD.search(text[:8000])
        cands.append({**base, "title": title, "text": norm_text(text), "notice_kind": nh.group(1).title() if nh else "",
                      "notice_number": nh.group(2) if nh else "", "notice_year": (nh.group(3) or "") if nh else "", "contents_title": "",
                      **gm})


def _classify_dedupe_emit(cands, drops, listed, code_entries, batch_metros):
    # classify + enrich
    kept = []
    live_drops = drops
    for c in cands:
        m = c["metro"]
        drops = live_drops if c["batch"] == BATCH else defaultdict(list)
        if m == "tsh":   # listing page is the 'Promulgated By-Laws' page: only title-level draft check (OCR head unreliable)
            if re.search(r"\bdraft\b", c["title"] + " " + c["list_title"], re.I):
                drops[m].append({"url": c["source_url"], "title": c["title"], "reason": "draft"}); continue
        elif is_draft(c["text"], c["title"] + " " + c["list_title"]):
            drops[m].append({"url": c["source_url"], "title": c["title"], "reason": "draft_or_for_comment"}); continue
        if re.search(r"fine schedule", c["title"] + " " + c["list_title"], re.I) and not re.search(r"tariff", c["title"], re.I):
            drops[m].append({"url": c["source_url"], "title": c["title"], "reason": "fine_schedule"}); continue
        if m == "bcm" and re.search(r"^notice", c["list_title"], re.I) and len(split_sections(c["text"])) < 2:
            drops[m].append({"url": c["source_url"], "title": c["title"], "reason": "notice_not_bylaw"}); continue
        c["commencement_date"] = commencement(c["text"], c["list_title"])
        if m == "ekh" and code_entries:
            e, sc = match_code(c["title"], code_entries)
            c["code_match"] = {"name": e["name"], "effective": e["effective"], "resolution": e["resolution"], "score": round(sc, 2)} if e else None
            if e:
                c["effective_date"] = e["effective"]
        c.setdefault("effective_date", c["commencement_date"])
        ys = years_in(c["title"]) or years_in(c.get("gazette_date", "")) or years_in(c["commencement_date"]) \
            or years_in(c.get("notice_year", "")) or years_in(c["list_title"]) or years_in(c["text"][:3000])
        c["year"] = max(ys) if ys and years_in(c["title"]) == [] else (ys[0] if ys else None)
        c["subject_key"] = subject_key(c["title"])
        if m == "tsh":
            # year only from the title/filename/gazette date or an explicit commencement date (never free OCR text)
            fn = c["doc_url"].rsplit("/", 1)[-1] if "/wp-content/" in c.get("doc_url", "") else ""
            ys = years_in(c.get("gazette_date", "")) or years_in(fn) or years_in(c["list_title"]) or years_in(c["commencement_date"])
            c["year"] = ys[0] if ys else None
            c["subject_key"] = c.get("alias_key") or subject_key(c["title"])
        kept.append(c)
    drops = live_drops
    # Tshwane: items sharing a (gazette, notice) pair are the same instrument
    pair_key = {}
    for c in kept:
        if c["metro"] == "tsh" and c.get("gazette_number") and c.get("notice_number") and c.get("alias_key"):
            pair_key.setdefault((c["gazette_number"], c["notice_number"]), c["subject_key"])
    for c in kept:
        if c["metro"] == "tsh" and (c.get("gazette_number"), c.get("notice_number")) in pair_key:
            c["subject_key"] = pair_key[(c["gazette_number"], c["notice_number"])]
    # dedupe repeat versions (same metro + subject key): keep latest year, then longest text
    groups = defaultdict(list)
    for c in kept:
        groups[(c["metro"], c["subject_key"])].append(c)
    final, superseded, prior_conflicts = [], [], []
    for (m, k), cs in groups.items():
        if m == "tsh":   # latest promulgated version: (year, has gazette+notice metadata, text length)
            cs.sort(key=lambda c: ((c["year"] or 0), bool(c.get("gazette_number")), len(c["text"])), reverse=True)
        else:
            cs.sort(key=lambda c: ((c["year"] or 0), len(c["text"])), reverse=True)
        prior = [c for c in cs if c["batch"] < BATCH]
        if prior and cs[0]["batch"] == BATCH:
            # a same-subject row is already live from an earlier batch: do not emit a second version; flag for review
            for c in cs:
                if c["batch"] == BATCH:
                    prior_conflicts.append({"metro": m, "subject_key": k, "title": c["title"], "url": c["source_url"], "year": c["year"],
                                            "live_title": prior[0]["title"], "live_url": prior[0]["source_url"], "live_year": prior[0]["year"],
                                            "note": "newer-or-equal version than the live row; not emitted (needs review)"})
            final.append(prior[0])
            continue
        final.append(cs[0])
        for s in cs[1:]:
            if s["batch"] < BATCH and cs[0]["batch"] < BATCH:
                continue
            superseded.append({"metro": m, "subject_key": k, "kept_title": cs[0].get("canonical_title") or cs[0]["title"],
                               "kept_url": cs[0]["source_url"], "kept_batch": cs[0]["batch"],
                               "superseded_title": s["list_title"] if m == "tsh" else s["title"], "superseded_url": s["source_url"],
                               "superseded_year": s["year"], "superseded_notice": s.get("notice_number", ""),
                               "superseded_gazette": s.get("gazette_number", ""), "superseded_gazette_date": s.get("gazette_date", "")})
    for c in final:
        if c["metro"] == "tsh":
            t = c.get("canonical_title") or c["title"]
            if c["year"] and not re.search(r"(19|20)\d\d", t):
                t = f"{t}, {c['year']}"
            c["title"] = t
    # ids
    for c in final:
        c["work_key"] = c["source_url"] + "#" + (c.get("notice_number") or "")
        base_id = f"za-muni-{c['metro']}-{slug(re.sub(r',?\s*(19|20)\d\d\s*$', '', c['title']))[:80]}" + (f"-{c['year']}" if c["year"] else "")
        c["id"] = base_id
    cnt = defaultdict(int)
    for c in final:
        cnt[c["id"]] += 1
    for c in final:
        if cnt[c["id"]] > 1 or c["id"].endswith("-"):
            c["id"] += "-x" + hashlib.sha1(c["work_key"].encode()).hexdigest()[:10]
    laws, arts = [], []
    final = [c for c in final if c["batch"] == BATCH]     # earlier batches are live already: emit only this batch
    for c in sorted(final, key=lambda c: c["id"]):
        m = c["metro"]
        M = METROS[m]
        secs = split_sections_tsh(c["text"], bool(c.get("ocr"))) if m == "tsh" else split_sections(c["text"])
        mcols = {"municipality_id": f"za-{m}", "municipality_name": M["name"], "wikidata_qid": M["qid"], "province": M["province"]}
        notice = f"{c['notice_kind']} {c['notice_number']}" + (f" of {c['notice_year']}" if c.get("notice_year") else "") if c.get("notice_number") else ""
        meta = {"schema_version": "collection_record.v1", "record_type": "law", "law_identifier": c["id"], "work_key": c["work_key"],
                "listing_url": c["listing_url"], "list_title": c["list_title"], "list_date": c["list_date"],
                "contents_title": c.get("contents_title", ""), "province_code": M["province_code"], "pages": c["pages"],
                "pdf_bytes": c["bytes"], "text_backend": c["text_backend"], "no_text_layer": c["no_text_layer"],
                "municipal_code_match": c.get("code_match"), "subject_key": c["subject_key"], "year": c["year"],
                "admin_level": "metropolitan_municipality", "publisher": M["short"], "source_terms_note": M["terms"],
                "batch": BATCH, "text_source": "ocr_tesseract_eng" if c.get("ocr") else (c["text_backend"] or "")}
        if c.get("ocr"):
            meta["ocr"] = c["ocr"]
            meta["note"] = ("Text obtained by OCR (tesseract, eng) from a scanned Provincial Gazette extract; may contain "
                            "recognition errors. Mean word confidence per document in ocr.mean_conf.")
        if m == "tsh":
            meta.update({"final_url": c.get("final_url"), "alias_key": c.get("alias_key"), "title_source_list_title": c["list_title"],
                         "gazette_meta_from_list_title": c.get("title_meta")})
            if c.get("merged_parts"):
                meta["merged_parts"] = c["merged_parts"]
        date = c.get("effective_date") or c.get("commencement_date") or c.get("gazette_date") or (str(c["year"]) if c["year"] else "")
        laws.append({"id": c["id"], "title": c["title"], "text": c["text"], "source_url": c["source_url"],
                     "source_type": "za_metro_official_bylaws", "jurisdiction": "ZA", "country": "South Africa", "language": "en",
                     "eli": c["work_key"], "date": date, "date_issued": c.get("gazette_date") or "", "retrieved_at": c["retrieved_at"],
                     "license": licence(m), "law_status": "in_force_per_publisher", "identifier": notice or c["title"],
                     "official_identifier": notice or c["work_key"], "article_count": len(secs), "json_path": "",
                     "metadata_json": json.dumps(meta, ensure_ascii=False), **mcols,
                     "notice_number": notice, "gazette_number": c.get("gazette_number", ""), "gazette_date": c.get("gazette_date", ""),
                     "commencement_date": c.get("commencement_date", ""), "effective_date": c.get("effective_date", ""),
                     "source_terms_note": M["terms"]})
        for s in secs:
            num = str(s["num"])
            if s.get("kind") == "heading_block":
                k = s["ordinal"]
                arts.append({"law_id": c["id"], "id": f"{c['id']}-b-{k:03d}"[:200], "title": s["title"], "text": s["text"],
                             "source_url": c["source_url"], "document_number": f"block {k}",
                             "article_number": f"section {num}" if num else f"block {k}", "record_type": "article",
                             "metadata_json": json.dumps({"law_identifier": c["id"], "kind": "heading_block", "ocr_split": True,
                                                          "note": "split on OCR heading lines; section numbering not recoverable"}),
                             **mcols})
                continue
            arts.append({"law_id": c["id"], "id": f"{c['id']}-s-{slug(num)}"[:200], "title": s["title"], "text": s["text"],
                         "source_url": c["source_url"], "document_number": f"section {num}", "article_number": f"section {num}",
                         "record_type": "article", "metadata_json": json.dumps({"law_identifier": c["id"], "kind": "section"}),
                         **mcols})
    ids = [l["id"] for l in laws]
    dups = {i for i in ids if ids.count(i) > 1}
    assert not dups, f"duplicate law ids: {sorted(dups)[:10]}"
    wk = [l["eli"] for l in laws]
    assert len(set(wk)) == len(wk), "duplicate work keys (source_url#notice)"
    seen, arts2 = set(), []
    for a in arts:
        if a["id"] in seen:
            continue
        seen.add(a["id"]); arts2.append(a)
    prior_ids = set()
    for f in sorted(PRIOR_IDS_DIR.glob("batch*_law_ids.txt")):
        if int(re.search(r"batch(\d+)_", f.name).group(1)) < BATCH:
            prior_ids |= {l.strip() for l in open(f) if l.strip()}
    if BATCH > 1:
        assert prior_ids, f"no prior batch id lists found in {PRIOR_IDS_DIR}"
    clash = set(ids) & prior_ids
    assert not clash, f"ids already live in an earlier batch: {sorted(clash)[:10]}"
    law_ids = set(ids)
    orphans = [a for a in arts2 if a["law_id"] not in law_ids]
    assert not orphans, f"orphan articles: {len(orphans)}"
    if not laws:
        raise SystemExit(f"batch {BATCH}: 0 laws selected; nothing written (drops: {dict((k, len(v)) for k, v in drops.items())})")
    OUT.mkdir(parents=True, exist_ok=True); MAN.mkdir(parents=True, exist_ok=True)
    lt = pa.Table.from_pylist(laws, schema=pa.schema([(k, pa.int32() if k == "article_count" else pa.string()) for k in laws[0]]))
    at = pa.Table.from_pylist(arts2, schema=pa.schema([(k, pa.string()) for k in arts2[0]]))
    lf, af = OUT / f"laws-{BATCH:05d}.parquet", OUT / f"articles-{BATCH:05d}.parquet"
    # never clobber the hand-built batch-1 replacement files (patch_za_batch1_bcm.py) that sit in the same pack
    assert BATCH > 1 or not (MAN / "batch1_corrections.jsonl").exists(), \
        "refusing to overwrite the patched replacement laws/articles-00001 (manifests/batch1_corrections.jsonl present)"
    assert lf.name not in ("laws-00001.parquet", "articles-00001.parquet") or BATCH == 1
    pq.write_table(lt, lf, compression="zstd")
    pq.write_table(at, af, compression="zstd")
    per = {}
    for m in sorted(batch_metros):
        per[m] = {"municipality": METROS[m]["name"], "qid": METROS[m]["qid"], "listed": listed.get(m, 0),
                  "kept_laws": sum(1 for l in laws if l["municipality_id"] == f"za-{m}"),
                  "articles": sum(1 for a in arts2 if a["municipality_id"] == f"za-{m}"),
                  "dropped": dict(sorted(defaultdict(int, {}).items())),
                  "superseded_versions": sum(1 for s in superseded if s["metro"] == m),
                  "laws_zero_articles": sum(1 for l in laws if l["municipality_id"] == f"za-{m}" and l["article_count"] == 0)}
        dd = defaultdict(int)
        for d in drops[m]:
            dd[d["reason"]] += 1
        per[m]["dropped"] = dict(dd)
    res = {"batch": BATCH, "repo": "endomorphosis/ipfs_south_africa_municipal_laws", "laws_rows": lt.num_rows,
           "articles_rows": at.num_rows, "articles_dropped_dup_id": len(arts) - len(arts2), "municipalities": len({l["municipality_id"] for l in laws}),
           "laws_with_text": sum(1 for l in laws if len(l["text"]) >= 200), "laws_zero_articles": sum(1 for l in laws if l["article_count"] == 0),
           "asserts": {"unique_law_ids": True, "unique_work_keys": True, "orphan_articles": 0,
                       "disjoint_from_prior_batches": True, "prior_ids_checked": len(prior_ids)},
           "expected_hub_parent": HUB_PARENT if BATCH > 1 else None,
           "ocr_laws": sum(1 for l in laws if '"text_source": "ocr_tesseract_eng"' in l["metadata_json"]),
           "ocr_docs": [{"id": l["id"], **json.loads(l["metadata_json"]).get("ocr", {})} for l in laws
                        if '"text_source": "ocr_tesseract_eng"' in l["metadata_json"]],
           "prior_batch_subject_conflicts": prior_conflicts,
           "per_metro": per, "municipal_code_entries_parsed": len(code_entries),
           "superseded_versions": superseded, "dropped_items": {m: drops[m] for m in drops}}
    for p in (lf, af):
        res[p.name] = {"path": str(p), "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    (MAN / f"batch{BATCH}_stage_result.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    short = {k: v for k, v in res.items() if k not in ("superseded_versions", "dropped_items")}
    print(json.dumps(short, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
