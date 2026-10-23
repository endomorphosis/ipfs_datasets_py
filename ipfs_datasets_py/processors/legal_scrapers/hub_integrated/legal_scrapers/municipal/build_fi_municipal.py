#!/usr/bin/env python3
"""collect_fi_municipal.py raw docs_fi.jsonl -> MUNICIPAL_HANDOFF layout (finland_municipal).
Usage: python build_fi_municipal.py RAWDIR OUTDIR"""
import unicodedata, json, sys, os, re, hashlib, datetime, shutil, collections
import pyarrow as pa, pyarrow.parquet as pq
sys.path.insert(0, os.environ.get("LEGAL_SCRAPERS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
from schema import MUNICIPAL_LAWS_SCHEMA, RAW_ARTICLES_SCHEMA, validate_municipal_table, municipal_law_id

LIC = "Municipal regulations/decisions: not protected by copyright under Section 9 of the Finnish Copyright Act (404/1961); attribution to source retained"
HEAD = re.compile(r"(?m)^[ \t]{0,3}(\d{1,3})[ \t]*([a-z])?[ \t]*§(?![ \t]*(?:mom|:n|:ssä|:ää|:stä|:ä|:n mukaan))([^\n]*)")
def _toc_filter(cands, text):
    """Drop table-of-contents headings: runs of >=4 consecutive candidates whose segments are < 120 chars."""
    seg = [(cands[i + 1][0] if i + 1 < len(cands) else len(text)) - c[0] for i, c in enumerate(cands)]
    drop, i = set(), 0
    while i < len(cands):
        j = i
        while j < len(cands) and seg[j] < 120: j += 1
        if j - i >= 4 and cands[i][0] < 0.15 * len(text):                     # TOC sits at the front
            drop.update(range(i, j))
            # last TOC entry is followed by a chapter heading, so its segment is longer; it is still TOC when the body restarts below it
            if j + 1 < len(cands) and cands[j + 1][1] <= cands[i][1] < cands[j][1]: drop.add(j)
        i = j + 1 if j == i else j
    for k in range(1, len(cands) - 1):          # a short entry sandwiched between two TOC runs (chapter heading after it) is TOC too
        if k not in drop and k - 1 in drop and k + 1 in drop and seg[k] < 200: drop.add(k)
    return [c for k, c in enumerate(cands) if k not in drop]

def split_articles(text):
    """Line-initial 'N §' headings; TOC lines (dot leaders, or runs of tiny segments) ignored. Numbering is monotonic
    within a chapter; a restart at 1 (Finnish rule books often renumber § per luku) opens a new block and labels become
    '<block>-<n>'. Ingress before first heading; one whole-text record when fewer than 2 headings."""
    cands = []
    for m in HEAD.finditer(text):
        ahead = "\n".join(text[m.start(): m.start() + 600].split("\n")[:2])
        if re.search(r"\.{4,}|…{2,}|(\. ){4,}", ahead): continue          # TOC entry (possibly wrapped onto 2 lines)
        rest = m.group(3).strip()
        if re.match(r"^[,.;:]", rest): continue
        if re.match(r"^\d", rest) and not re.match(r"^\d+[a-z]?(\.\d+)*\.?\s+[A-ZÄÖÅ]", rest): continue   # '16 § 1. Tonttijaosta' is a heading
        line = text[m.start():].split("\n", 1)[0]
        cands.append((m.start(), int(m.group(1)), m.group(2), rest, bool(re.search(r"\S\s+\d{1,3}\s*$", line))))
    # TOC without dot leaders: >=3 consecutive headings each ending in a page number (a wrapped entry sandwiched
    # between two such headings counts too)
    fl = [c[4] for c in cands]
    for k in range(1, len(cands) - 1):
        if not fl[k] and fl[k - 1] and fl[k + 1] and cands[k][0] < 0.25 * len(text): cands[k] = cands[k][:4] + (True,)
    drop, i = set(), 0
    while i < len(cands):
        j = i
        while j < len(cands) and cands[j][4] and (cands[j + 1][0] if j + 1 < len(cands) else len(text)) - cands[j][0] < 200: j += 1
        if j - i >= 3: drop.update(range(i, j))
        i = max(j, i + 1)
    cands = [c[:4] for k, c in enumerate(cands) if k not in drop]
    cands = _toc_filter(cands, text)
    lukus = [m.start() for m in re.finditer(r"(?m)^[ \t]{0,3}(?:\d{1,2}|[IVXL]{1,6})\.?[ \t]*(?:luku|LUKU|kap\.|KAPITLET|kapitlet)\b", text)]
    if len(lukus) < 3: lukus = []
    heads, prev, prev_suf, block = [], 0, None, 1
    for k, (pos, num, suf, rest) in enumerate(cands):
        if num == 1 and not suf and heads:
            if lukus and any(heads[-1][0] < lp < pos for lp in lukus): block += 1   # a 'N luku' heading opened a new chapter
            elif prev >= 2 and any(c[1] == prev + 1 for c in cands[k + 1:k + 6]): continue   # stray '1 §': old sequence goes on
            elif prev == 1 and pos - heads[-1][0] < 200: heads.pop()      # a lone earlier '1 §' with no body was a false start
            else: block += 1
            prev, prev_suf = 0, None
        if heads and not (prev < num <= prev + 15 or (num == prev and suf and suf != prev_suf)): continue
        heads.append([pos, block, f"{num}{suf or ''}", f"{num}{suf or ''} § {rest}".strip()]); prev, prev_suf = num, suf
    if len(heads) < 2:
        return [("1", "whole text", text.strip())], 1.0
    blocks = sorted({h[1] for h in heads}); ren = {b: i + 1 for i, b in enumerate(blocks)}
    for h in heads: h[1] = ren[h[1]]
    multi = len(blocks) > 1
    out = []
    if text[:heads[0][0]].strip(): out.append(("0", "Johdanto", text[:heads[0][0]].strip()))
    for i, (pos, blk, n, title) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        out.append((f"{blk}-{n}" if multi else n, title[:300], text[pos:end].strip()))
    return out, sum(len(b) for _, _, b in out) / max(1, len(text.strip()))

def numbering_gaps(labels):
    """Missing § numbers inside a chapter block (kept in extras: mostly repealed/'kumottu' sections or table layouts)."""
    out, prev = [], None
    for lab in labels:
        m = re.match(r"^(?:(\d+)-)?(\d+)[a-z]?$", lab)
        if not m or lab == "0": continue
        key = (m.group(1), int(m.group(2)))
        if prev and prev[0] == key[0] and key[1] - prev[1] > 1:
            out += [f"{key[0] + '-' if key[0] else ''}{n}" for n in range(prev[1] + 1, key[1])]
        prev = key
    return out

def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()

STATS = {}
HELPERS = ("schema.py", "common_crawl_helper.py")
def main(raw, out):
    docs = []
    for fn in ("docs_fi.jsonl", "docs_fi_html.jsonl"):
        if os.path.exists(f"{raw}/raw/{fn}"): docs += [json.loads(l) for l in open(f"{raw}/raw/{fn}")]
    NOISE = re.compile(r"(?i)(tiedote|stipend|palkinto|kunniamerk|\bEN\b|_EN|EN_|\bRU\b|RU_|_ru\b|venaja|englanti|avustuss(a|ä)(a|ä)nt|avustusten|apuraha)")
    def bad_lang(t):
        sm = t[:20000]; cyr = len(re.findall(r"[а-яА-Я]", sm)) / max(1, len(sm))
        w = re.findall(r"[a-z]+", sm.lower()); en = sum(x in ("the", "and", "of", "for", "is") for x in w) / max(1, len(w))
        return cyr > 0.05 or en > 0.03
    import fi_fixes as F
    dropped = collections.Counter()
    keep = []
    for d in docs:
        d["text"] = F.shift_fix(d["text"]); d["title"] = F.shift_fix(d["title"]) if "\x03" in d["title"] else d["title"]
        d["text"], d["title"] = unicodedata.normalize("NFKC", d["text"]), unicodedata.normalize("NFKC", d["title"])   # ﬁ/ﬂ ligatures etc.
        # lost 'ti' ligature (U+FFFD between letters, e.g. 'markkinoin\ufffdjohtajalle') and leftover control characters
        LIGRX = r"\ufffd(?=[a-zäöå-]|\s*\n)|(?<=[a-zäöå])\ufffd"
        nlig = len(re.findall(LIGRX, d["text"]))
        if nlig: d["text"] = re.sub(LIGRX, "ti", d["text"]); d["extras"]["ligature_ti_restored"] = nlig
        d["text"] = re.sub(r"[\x00-\x08\x0b\x0e-\x1f]", " ", d["text"]).replace("\ufffd", "")
        if NOISE.search(d["native_id"] + " " + d["title"]): dropped["noise_title"] += 1; continue
        if F.NON_NORMATIVE.search(d["native_id"] + " " + d["title"] + " " + d["text"][:200]): dropped["non_normative"] += 1; continue
        if bad_lang(d["text"]) or F.script_bad(d["text"]): dropped["non_fi_sv_language"] += 1; continue
        if F.other_muni(d): dropped["other_municipality"] += 1; continue
        d["text"], nrest = F.restore_toc_numbers(d["text"])
        if nrest: d["extras"]["section_numbers_restored_from_toc"] = nrest
        d["language"] = F.lang_of(d["text"], d["title"])
        keep.append(d)
    docs = keep
    # exact-text duplicates first (keep one), then version resolution
    seen = {}; uniq = []
    for d in docs:
        h = hashlib.sha256(d["text"].encode()).hexdigest(); k = (d["municipality_code"], h)
        if k in seen: seen[k]["extras"].setdefault("alt_urls", []).append(d["source_url"]); dropped["exact_dup"] += 1; continue
        seen[k] = d; uniq.append(d)
    for d in uniq: F.fix_title(d)
    # near-duplicates: same municipality and title, >=95% similar text (e.g. Jyväskylä tsv-jatetaksa / tsv-jatetaksa_2025)
    import difflib
    nd = []
    for d in uniq:
        twin = next((e for e in nd if e["municipality_code"] == d["municipality_code"] and e["title"].lower() == d["title"].lower()
                     and difflib.SequenceMatcher(None, e["text"][:6000], d["text"][:6000]).ratio() >= 0.95), None)
        if twin:
            twin["extras"].setdefault("alt_versions", []).append(dict(native_id=d["native_id"], source_url=d["source_url"], title=d["title"],
                                                                     text=d["text"], sha256_text=hashlib.sha256(d["text"].encode()).hexdigest()))
            dropped["near_duplicate"] += 1; continue
        nd.append(d)
    uniq = nd
    docs, nfold = F.resolve_versions(uniq); dropped["folded_same_version"] = nfold
    for d in docs: F.fix_title(d)
    for d in docs:   # titles the derivation cannot recover from the document head
        if re.search(r"(?i)määräyskokoelma", d["title"]) and d["extras"].get("doc_type"):
            y = (d.get("date") or "")[:4]; d["title"] = f"{d['municipality']}n kaupungin {d['extras']['doc_type']}" + (f" {y}" if y else "")
        if re.search(r"maa-ainestaksa", d["native_id"]) and not re.search(r"(?i)maa-aines", d["title"]):
            d["title"] = "Maa-ainesten ottamissuunnitelman tarkastamisesta ja ottamistoiminnan valvonnasta suoritettavat maksut"
        if re.search(r"maa-ainestaksa.*poytakirjaan", d["native_id"]):
            y = re.search(r"(20\d\d)", d["native_id"]).group(1); d["title"] = re.sub(r"\s*\(maa-ainestaksa.*\)$", "", d["title"]) + f" (maa-ainestaksa {y}, pöytäkirjan liite)"
    print("dropped", dict(dropped)); STATS["dropped"] = dict(dropped)
    byid, byhash = {}, {}
    for d in docs:
        if len(d["text"].strip()) < 80: continue
        h = hashlib.sha256(d["text"].encode()).hexdigest(); k = (d["municipality_code"], h)
        if k in byhash: byhash[k]["extras"].setdefault("alt_urls", []).append(d["source_url"]); continue
        lid = municipal_law_id("fi", d["municipality_code"], d["native_id"])
        if lid in byid:   # same filename stem, different text: disambiguate by short hash (stable for identical text)
            lid = municipal_law_id("fi", d["municipality_code"], f"{d['native_id']}-{h[:8]}")
        d["id"], d["sha"] = lid, h; byid[lid] = d; byhash[k] = d
    arts = []
    for d in byid.values():
        a, cov = split_articles(d["text"]); assert cov >= 0.95, (d["id"], cov)
        d["n_art"] = len(a); d["extras"]["article_text_coverage"] = round(cov, 4)
        gaps = numbering_gaps([x[0] for x in a])
        if gaps: d["extras"]["numbering_gaps"] = gaps; STATS["laws_with_numbering_gaps"] = STATS.get("laws_with_numbering_gaps", 0) + 1
        for n, title, body in a:
            arts.append(dict(law_id=d["id"], id=f"{d['id']}-art-{n}", title=title, text=body, source_url=d["source_url"],
                             document_number=d["native_id"], article_number=n, record_type="section", metadata_json="{}"))
    rows = [dict(id=d["id"], title=d["title"], text=d["text"], source_url=d["source_url"], source_type=("official_html" if d["extras"].get("via") == "sitemap/html-page" else "official_pdf"),
                 jurisdiction=f"FI/{d['municipality']}", country="Finland", language=d["language"], eli=None, date=d.get("date"), date_issued=(d.get("date") if d["extras"].get("date_kind") == "adopted" else None),
                 retrieved_at=d["retrieved_at"], license=LIC, law_status=d["status"], identifier=d["native_id"], official_identifier=None,
                 article_count=d["n_art"], json_path=None,
                 metadata_json=json.dumps({"extras": {**d["extras"], "sha256_text": d["sha"]}}, ensure_ascii=False),
                 jurisdiction_level="municipal", admin_level=8, country_iso="FI", admin1=None, municipality=d["municipality"],
                 municipality_code=d["municipality_code"], source_body=d["source_body"]) for d in byid.values()]
    t = pa.Table.from_pylist(rows, schema=MUNICIPAL_LAWS_SCHEMA); errs = validate_municipal_table(t); assert not errs, errs
    at = pa.Table.from_pylist(arts, schema=RAW_ARTICLES_SCHEMA)
    assert len(set(at["id"].to_pylist())) == at.num_rows
    os.makedirs(f"{out}/data", exist_ok=True); os.makedirs(f"{out}/scrapers", exist_ok=True)
    pq.write_table(t, f"{out}/data/laws-00001.parquet", compression="zstd"); pq.write_table(at, f"{out}/data/articles-00001.parquet", compression="zstd")
    here = os.path.dirname(os.path.abspath(__file__))
    for f in ("collect_fi_municipal.py", "build_fi_municipal.py", "fi_pointers.py", "fi_fixes.py"): shutil.copy(f"{here}/{f}", f"{out}/scrapers/{f}")
    # helper modules imported from legal_scrapers/ (copied so scrapers/ runs standalone: LEGAL_SCRAPERS_DIR=scrapers)
    for f in HELPERS: shutil.copy(os.path.join(here, "..", f), f"{out}/scrapers/{f}")
    munis = collections.Counter(r["municipality"] for r in rows)
    types = collections.Counter(json.loads(r["metadata_json"])["extras"]["doc_type"] for r in rows)
    files = {p: sha(f"{out}/{p}") for p in ["data/laws-00001.parquet", "data/articles-00001.parquet"] + [f"scrapers/{f}" for f in os.listdir(f"{out}/scrapers")]}
    if os.path.exists(f"{out}/README.md"): files["README.md"] = sha(f"{out}/README.md")
    man = dict(slug="finland", country_iso="FI", collector="scrapers/collect_fi_municipal.py",
               built_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), laws_rows=t.num_rows, articles_rows=at.num_rows,
               municipalities=dict(munis), municipalities_total_fi=308, law_status_counts=dict(collections.Counter(r["law_status"] for r in rows)), build_filters=STATS.get("dropped"), doc_types=dict(types), sha256=files,
               helper_modules={"schema.py": "legal_scrapers/schema.py (MUNICIPAL_LAWS_SCHEMA, RAW_ARTICLES_SCHEMA, validate_municipal_table, municipal_law_id); imported by build_fi_municipal.py",
                               "common_crawl_helper.py": "legal_scrapers/common_crawl_helper.py (CDX pointer lookup); imported by fi_pointers.py",
                               "fi_fixes.py": "scrapers/fi_fixes.py (titles, dates, versions, glyph fixes); imported by build_fi_municipal.py",
                               "third_party": ["requests", "pyarrow", "poppler-utils (pdftotext)"]},
               sources=["official municipal websites (sitemaps -> rule pages -> linked PDFs)", "Common Crawl CDX index (pointer discovery only; documents fetched live)"])
    json.dump(man, open(f"{out}/MANIFEST.json", "w"), indent=1, ensure_ascii=False)
    print(json.dumps({k: man[k] for k in ("laws_rows", "articles_rows", "municipalities", "doc_types")}, ensure_ascii=False))
if __name__ == "__main__": main(sys.argv[1], sys.argv[2])
