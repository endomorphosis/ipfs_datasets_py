#!/usr/bin/env python3
"""Stage batch 6 (ZA metro by-laws: CPT + JHB official PDFs) as a diff-limited APPEND to
endomorphosis/ipfs_south_africa_municipal_laws: new shards data/laws-00004.parquet + data/articles-00004.parquet
(schema/codec/row-group layout copied from the live laws-00003/articles-00003); every live file untouched.
QA: masthead titles; maker from enacting clause; repeals only on express clauses; sections split at line start
(case-sensitive, monotone); gaps/dups recorded; no Jan-1 padding; webmail redaction; post-fetch dedupe vs live.
Usage: stage_za_metro.py --parent <sha>   Env ZA_WORK"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import hashlib, json, os, re, sys
from collections import Counter
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plan_za_metro import core, fold, live_keys, year  # noqa
from bounds_za_metro import trim  # page-boundary filtering (batch-6 fix)
W = Path(os.environ.get("ZA_WORK", (str(_LEGAL_WS) + "/world_laws/za_metro"))); N = 6
PACK = W / f"hf_b{N}/ipfs_south_africa_municipal_laws"; TIP = W / "tip"
MUNI = {"cpt": ("za-cpt", "City of Cape Town Metropolitan Municipality", "Q1185115", "Western Cape", "ZA-WC", "City of Cape Town", "www.capetown.gov.za"),
        "jhb": ("za-jhb", "City of Johannesburg Metropolitan Municipality", "Q2346838", "Gauteng", "ZA-GP", "City of Johannesburg", "joburg.org.za")}
LIC = ("Official municipal by-law text published by the {pub} on its official website; official texts of a legislative, administrative "
       "or legal nature are excluded from copyright under s12(8)(a) of the Copyright Act 98 of 1978 (described, not quoted).")
TERMS = "{host}: site terms-of-use page not separately reviewed in batch 6; robots.txt permits the fetched paths (checked {d})."
MON = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
WEBMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@(?:gmail|googlemail|yahoo|ymail|hotmail|outlook|live|msn|aol|icloud|me|mail|gmx|protonmail|proton|zoho|yandex|webmail|telkomsa|vodamail|mweb|iafrica|absamail|lantic)\.[A-Za-z.]{2,10}\b", re.I)
BYL = re.compile(r"\bBY-?\s?LAWS?\b|\bBYLAWS?\b", re.I)
SKIP = re.compile(r"^(to provide|these by|this by|in terms|notice is|be it|whereas|the municipal manager|under|published|provincial gazette|"
                  r"provinsiale|buitengewone|extraordinary|page|no\.|table of contents|contents|arrangement|index|preamble|schedule|"
                  r"to repeal|to amend|for the|and to|and for|in this|by-law no|repeal|chapter|part)\b", re.I)
CITYL = re.compile(r"(?i)^\s*(?:the\s+)?city\s+of\s+(?:cape\s+town|johannesburg)(?:\s+metropolitan\s+municipality)?\s*[:\-–]?\s*$")
STOPUP = re.compile(r"(?i)city of|province|provinsie|gazette|koerant|notice|kennisgewing|approved|promulgated|municipality|^\W*\d+\W*$|\.{4}")
def _caps(l):
    a = [c for c in l if c.isalpha()]; return bool(a) and sum(c.isupper() for c in a) / len(a) > 0.7
def _cands(lines):
    for i, l in enumerate(lines):
        if not BYL.search(l) or ".." in l or len(l) > 140 or not _caps(l) or re.match(r"(?i)^\s*(to provide|these|this|in terms|the previous|repeal|to repeal|to amend)", l):
            continue
        near_city = i < 15 or any(re.match(r"(?i)^\s*city of (?:cape town|johannesburg)\b", x) for x in lines[max(0, i - 6):i + 1])
        if not near_city: continue
        parts = [l]; j = i - 1
        while j >= 0 and i - j <= 4 and _caps(lines[j]) and not STOPUP.search(lines[j]) and 8 <= len(lines[j]) < 70 and not BYL.search(lines[j]):
            parts.insert(0, lines[j]); j -= 1
        k = i + 1
        while k < len(lines) and k - i <= 4 and not re.search(r"(?:19|20)\d\d\s*\)?\s*$", parts[-1]):
            nx = lines[k]
            if parts[-1].endswith("-") and nx and _caps(nx): parts[-1] = parts[-1] + nx.strip(); k += 1; continue
            if re.fullmatch(r"\s*(?:19|20)\d\d\s*", nx) or (_caps(nx) and not STOPUP.search(nx) and len(nx) < 70 and not re.match(r"(?i)^\s*(to |approved|amended|promulgated|chapter|part|index|contents|table)", nx)):
                parts.append(nx); k += 1; continue
            break
        t = re.sub(r"\s+", " ", " ".join(parts)).strip(" .:-–")
        t = re.sub(r"(?i)^no\.?\s*\d+/\d{4}\s*", "", t)
        t = re.sub(r"(?i)^(?:local authority notice|provincial notice|notice)\s+\d+\s+(?:of\s+\d{4}\s*)?", "", t)
        t = re.sub(r"(?i)^(?:the\s+)?city of (?:cape town|johannesburg)(?: metropolitan municipality)?\s*[:\-–]?\s*", "", t)
        t = re.sub(r"\s+,", ",", t)
        if len(t) < 8 or re.fullmatch(r"(?i)by-?\s?laws?(?:,? \d{4})?", t): continue
        t = t.title()
        t = re.sub(r"\bBy-?\s?Laws?\b|\bBylaws?\b", lambda m: "By-laws" if m.group(0).lower().endswith("s") else "By-law", t)
        t = re.sub(r"(?<!^)\b(And|Of|The|To|For|On|In|That|Relating|With|By)\b(?! ?-?law)", lambda m: m.group(0).lower(), t)
        yield i, t[:300]
def masthead(text, city=None, hint=""):
    lines = [re.sub(r"\s{3,}.*$", "", l.strip()) for l in text.splitlines() if l.strip()][:3000]
    cs = list(_cands(lines))
    if not cs: return None
    hk = set(core(hint).split()) - {"cape", "town", "johannesburg", "city"}
    if not hk: return cs[0][1]
    best = max(cs, key=lambda c: (len(hk & set(core(c[1]).split())) / max(1, len(set(core(c[1]).split()) | hk)), -c[0]))
    return best[1]
def _d(m): return f"{int(m.group(1))} {m.group(2).capitalize()} {m.group(3)}"
DRX = r"(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+((?:19|20)\d\d)"
def gdate(text, title_year=None):
    """Promulgation date from the publisher's cover ('PROMULGATED <date>'), else the gazette issue date line, else first
    date in the heading. Never padded; dates earlier than the by-law's own title year are rejected."""
    f = fold(text[:8000])
    for rx in (r"\bpromulgated\s*(?:on\s*)?:?\s*" + DRX, r"(?m)^\s*(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday),?\s+" + DRX, r"\b" + DRX):
        for m in re.finditer(rx, f):
            d = _d(m)
            if title_year and int(m.group(3)) < title_year: continue
            return d
    return ""
ENACT = re.compile(r"(?:be\s+it\s+(?:therefore\s+)?enacted\s+by\s+the\s+(?:municipal\s+)?council[^.\n]{0,80}|"
                   r"(?:the\s+)?(?:municipal\s+)?council\s+of\s+the\s+city\s+of\s+(?:cape\s+town|johannesburg)[^.\n]{0,40}?\s+(?:hereby\s+)?(?:enacts|has\s+enacted|resolved|adopted)|"
                   r"the\s+city\s+of\s+(?:cape\s+town|johannesburg)\s+(?:hereby\s+)?enacts|"
                   r"municipal\s+manager[^.]{0,200}?publishes[^.]{0,200}?approved\s+by\s+(?:its|the)\s+council|"
                   r"(?:the\s+)?city\s+of\s+(?:cape\s+town|johannesburg)[^.\n]{0,60}hereby\s+publishes[^.]{0,160}?(?:by-?\s?laws?)[^.]{0,100}?(?:adopted|approved)\s+by\s+(?:the|its)\s+council)", re.I | re.S)
def maker(text, city):
    m = ENACT.search(text[:20000])
    if m: return {"maker": f"Municipal Council of the {MUNI[city][1]}", "status": "confirmed_enacting_clause", "evidence": re.sub(r"\s+", " ", m.group(0))[:300]}
    return {"maker": None, "status": "unconfirmed_no_enacting_clause", "evidence": None}
def repeals(text):
    return [re.sub(r"\s+", " ", m.group(0)).strip()[-220:] for m in re.finditer(r"[^\n]{0,160}\b(?:is|are)\s+(?:hereby\s+)?repealed\b[^\n]{0,60}", text)][:25]
SEC = re.compile(r"^ {0,20}(\d{1,3})([A-Z]?)\.?(?:\s{1,14}|(?=\())(?=[A-Z(\"“'‘])")
def split(text):
    """Line-start, case-sensitive, monotone section numbering. Numbering that restarts at 1 opens a new run (TOC,
    parallel-language text, quoted schedules); the first run carrying >= 60% of the largest run's text is kept."""
    runs, secs, cur, last = [], [], None, 0
    lines = text.splitlines()
    nums_at = [(i, int(m.group(1))) for i, ln in enumerate(lines) for m in [SEC.match(ln)] if m and not re.match(r"^\s*\d{1,3}\.?\s+(?:of|and|to)\b", ln)]
    def _cont(i, last):  # a '1' that is a quoted/inner sub-item when the outer numbering resumes at last+1 afterwards
        nxt = next((n for j, n in nums_at if j > i and n != 1 and n <= last + 2 and n > 1), None)
        later = [n for j, n in nums_at if j > i][:12]
        return nxt == last + 1 and last + 1 in later
    for li_, ln in enumerate(lines):
        m = SEC.match(ln)
        if m and not re.match(r"^\s*\d{1,3}\.?\s+(?:of|and|to)\b", ln):
            n = int(m.group(1)); suf = m.group(2)
            if n == 1 and not suf and last >= 2 and _cont(li_, last):
                if cur is not None and ln.strip(): cur["text"].append(ln.rstrip())
                continue
            if n == 1 and not suf and last >= 2:
                runs.append(secs); secs, cur, last = [], None, 0
            if (last == 0 and n <= 2) or (last and last < n <= last + 4) or (suf and n == last):
                cur = {"num": f"{n}{suf}", "n": n, "text": [ln.strip()]}; secs.append(cur); last = n; continue
        if cur is not None and ln.strip(): cur["text"].append(ln.rstrip())
    runs.append(secs)
    size = [sum(len(" ".join(x["text"])) for x in r) for r in runs]
    secs = next((r for r, z in zip(runs, size) if z >= 0.6 * max(size)), []) if max(size) else []
    nums = [s["n"] for s in secs]
    return secs, {"gaps": [f"{a}->{b}" for a, b in zip(nums, nums[1:]) if b > a + 1],
                  "duplicates": [k for k, v in Counter(s["num"] for s in secs).items() if v > 1]}
def slug(s): return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")[:120]
def redact(s, ctr):
    out, n = WEBMAIL.subn("[redacted-webmail]", s or ""); ctr["webmail_redacted"] += n; return out
def main():
    parent = sys.argv[sys.argv.index("--parent") + 1]
    live_l = pq.read_table(TIP / "data/laws-00003.parquet"); live_a = pq.read_table(TIP / "data/articles-00003.parquet")
    live_ids = set(); live_aids = set()
    for f in sorted((TIP / "data").glob("laws-*.parquet")): live_ids |= set(pq.read_table(f, columns=["id"]).column("id").to_pylist())
    for f in sorted((TIP / "data").glob("articles-*.parquet")): live_aids |= set(pq.read_table(f, columns=["id"]).column("id").to_pylist())
    keys, _ = live_keys()
    cat = {i["ident"]: i for i in json.load(open(W / "catalog.json"))}
    res = {}
    for l in open(W / "results.jsonl"):
        d = json.loads(l); res[d["ident"]] = d
    new_l, new_a, drops, qa, seen = [], [], [], Counter(), {}
    rdate = None
    for ident in json.load(open(W / "todo.json")):
        it = cat[ident]; r = res.get(ident); city = it["src"]; M = MUNI[city]
        if not r or r.get("status") != 200:
            drops.append({"ident": ident, "url": it["url"], "reason": f"fetch_status_{r.get('status') if r else 'not_fetched'}"}); continue
        ocrm = None
        if r.get("needs_ocr"):
            oj = W / "cache/ocr" / f"{ident}.json"
            if not oj.exists():
                drops.append({"ident": ident, "url": it["url"], "reason": "no_usable_text_layer_needs_ocr"}); continue
            ocrm = json.load(open(oj)); qa["ocr_" + ocrm["status"]] += 1
        text = (W / "cache/ocr" / f"{ident}.txt").read_text() if ocrm else (W / "cache/text" / f"{ident}.txt").read_text()
        head = fold(text[:2500])
        if re.search(r"\bdraft\b|for public comment|invitation to comment|comments? (?:are|is) invited", head):
            drops.append({"ident": ident, "url": it["url"], "reason": "draft_or_for_comment_not_promulgated"}); continue
        title = masthead(text, city, it["title"] + " " + it["filename"])
        if not title:
            drops.append({"ident": ident, "url": it["url"], "reason": "masthead_title_not_found", "listing_title": it["title"]}); continue
        text, pb = trim(text, title); qa["pb_" + pb["end_reason"]] += 1; qa["pb_leading_pages_dropped"] += pb["leading_pages_dropped"]
        y = year(title) or year(gdate(text)) or year(it["title"]) or year(it["filename"])
        k = core(title); amend = bool(re.search(r"(?i)amend", title))
        hit = [(city, k, yy) for yy in ((y,) if amend else (y, y - 1, y + 1) if y else ()) if (city, k, yy) in keys]
        if not year(title) and not amend:  # undated masthead: any live year of the same by-law counts as a duplicate
            hit = hit or [kk for kk in keys if kk[0] == city and kk[1] == k]
        if hit:
            drops.append({"ident": ident, "url": it["url"], "reason": "dup_live_masthead_name_year", "title": title, "year": y, "live_title": keys[hit[0]]}); continue
        if (city, k, y) in seen:
            drops.append({"ident": ident, "url": it["url"], "reason": "dup_masthead_in_batch", "title": title, "kept": seen[(city, k, y)]}); continue
        secs, sp = split(text)
        if not secs:
            drops.append({"ident": ident, "url": it["url"], "reason": "no_sections_found", "title": title}); continue
        seen[(city, k, y)] = ident
        tslug = slug(title if y and str(y) in title else f"{title} {y or ''}")
        law_id = f"za-muni-{city}-{tslug}"
        if law_id in live_ids or any(d["id"] == law_id for d in new_l): law_id += "-b6"
        assert law_id not in live_ids
        dt = gdate(text, year(title)); mk = maker(text, city); rep = repeals(text)
        notice = re.search(r"(?i)\b((?:local authority|provincial|general|municipal)\s+notice\s+(?:no\.?\s*)?\d+\s+of\s+\d{4})", text[:6000])
        notice = re.sub(r"\s+", " ", notice.group(1)).title().replace(" Of ", " of ") if notice else ""
        gz = re.search(r"(?i)(?:provincial gazette|gazette)[^\n]{0,60}?\bno\.?\s*(\d{3,5})", text[:6000]); gz = gz.group(1) if gz else ""
        te = ({"backend": ocrm["engine"], "ocr": True, "ocr_mean_conf": ocrm["mean_conf"], "ocr_status": ocrm["status"]} if ocrm else {"backend": "pdftotext -layout", "ocr": False})
        terms = TERMS.format(host=M[6], d="2026-10-13")
        meta = {"schema_version": "collection_record.v1", "record_type": "law", "law_identifier": law_id, "work_key": it["url"],
                "listing_url": it["listing_url"], "list_title": it["title"], "filename": it["filename"], "province_code": M[4], "pages": r.get("pages"),
                "pdf_bytes": r.get("bytes"), "source_pdf_sha256": r.get("sha256"), "text_backend": te["backend"], "text_extraction": te,
                "no_text_layer": bool(ocrm), "subject_key": k, "year": y, "admin_level": "metropolitan_municipality", "publisher": M[5],
                "title_source": "masthead", "maker_check": mk, "express_repeals": rep, "is_amendment": bool(re.search(r"(?i)amend", title)),
                "page_boundary": pb, "section_split": {"method": "line-start-case-sensitive-monotone", **sp, "count": len(secs)}, "batch": N, "source_terms_note": terms}
        new_l.append({"id": law_id, "title": title, "text": redact(text, qa), "source_url": it["url"], "source_type": "za_metro_official_bylaws",
                      "jurisdiction": "ZA", "country": "South Africa", "language": "en", "eli": it["url"], "date": dt, "date_issued": dt,
                      "retrieved_at": r.get("retrieved_at"), "license": LIC.format(pub=M[5]), "law_status": "in_force_per_publisher",
                      "identifier": notice or title, "official_identifier": notice, "article_count": len(secs), "json_path": "",
                      "metadata_json": json.dumps(meta, ensure_ascii=False), "municipality_id": M[0], "municipality_name": M[1], "wikidata_qid": M[2],
                      "province": M[3], "notice_number": notice, "gazette_number": gz, "gazette_date": dt if gz else "",
                      "commencement_date": "", "effective_date": "", "source_terms_note": terms})
        used = Counter()
        for s in secs:
            used[s["num"]] += 1
            sid = f"{law_id}-s-{s['num'].lower()}" + (f"-dup{used[s['num']]}" if used[s["num"]] > 1 else "")
            body = redact(re.sub(r"[ \t]+", " ", "\n".join(s["text"])).strip(), qa)
            new_a.append({"law_id": law_id, "id": sid, "title": re.sub(r"\s+", " ", s["text"][0])[:100], "text": body, "source_url": it["url"],
                          "document_number": f"section {s['num']}", "article_number": f"section {s['num']}", "record_type": "article",
                          "metadata_json": json.dumps({"law_identifier": law_id, "kind": "section"}), "municipality_id": M[0],
                          "municipality_name": M[1], "wikidata_qid": M[2], "province": M[3]})
        qa["laws_with_gaps"] += bool(sp["gaps"]); qa["laws_with_dups"] += bool(sp["duplicates"]); qa[f"maker_{mk['status']}"] += 1
        qa["date_none"] += not dt; qa["date_jan1"] += dt.startswith("1 January"); qa["express_repeal_laws"] += bool(rep); qa[f"city_{city}"] += 1
    assert not (set(a["id"] for a in new_a) & live_aids) and len(set(a["id"] for a in new_a)) == len(new_a)
    (PACK / "data").mkdir(parents=True, exist_ok=True); (PACK / "manifests").mkdir(parents=True, exist_ok=True)
    out = {}
    for name, live, rows in (("laws", live_l, new_l), ("articles", live_a, new_a)):
        tbl = pa.Table.from_pylist(rows, schema=live.schema)
        p = PACK / "data" / f"{name}-00004.parquet"
        pq.write_table(tbl, p, compression="zstd", row_group_size=max(1, tbl.num_rows), version=pq.ParquetFile(TIP / f"data/{name}-00003.parquet").metadata.format_version)
        back = pq.read_table(p); assert back.equals(tbl) and back.schema.equals(live.schema)
        md = pq.ParquetFile(p).metadata
        out[f"data/{name}-00004.parquet"] = {"rows": back.num_rows, "codec": md.row_group(0).column(0).compression, "row_groups": md.num_row_groups,
                                             "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
    with open(PACK / f"manifests/batch{N}_drops.jsonl", "w") as fh:
        for d in drops: fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    (PACK / f"manifests/batch{N}_listing_exclusions.jsonl").write_bytes((W / "listing_exclusions.jsonl").read_bytes())
    tl = sum(pq.ParquetFile(f).metadata.num_rows for f in (TIP / "data").glob("laws-*.parquet")) + len(new_l)
    ta = sum(pq.ParquetFile(f).metadata.num_rows for f in (TIP / "data").glob("articles-*.parquet")) + len(new_a)
    sr = {"batch": N, "repo": "endomorphosis/ipfs_south_africa_municipal_laws", "expected_hub_parent": parent,
          "parts": {"A": "append: City of Cape Town (www.capetown.gov.za) + City of Johannesburg (joburg.org.za) official by-law PDFs not already in the live repo -> data/laws-00004.parquet, data/articles-00004.parquet"},
          "changed_files": [], "new_files": sorted(out), "files": out, "laws_added": len(new_l), "articles_added": len(new_a),
          "added_by_city": dict(Counter(r["municipality_id"] for r in new_l)), "total_laws": tl, "total_articles": ta,
          "drops": dict(Counter(d["reason"] for d in drops)), "listing_exclusions": dict(Counter(json.loads(l)["reason"] for l in open(W / "listing_exclusions.jsonl"))),
          "qa_counts": dict(qa), "mode": "diff-limited append: new shards only; every live file (incl. CPT_html/JHB_html AKN rows from the user's writer) untouched; ZSTD single row group like live",
          "licence": "Copyright Act 98 of 1978 (South Africa) s12(8)(a) - described, not quoted"}
    (PACK / f"manifests/batch{N}_stage_result.json").write_text(json.dumps(sr, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: sr[k] for k in ("laws_added", "articles_added", "added_by_city", "drops", "qa_counts")}))
if __name__ == "__main__": main()
