#!/usr/bin/env python3
"""Turn collect_ch_municipal.py raw docs.jsonl into the MUNICIPAL_HANDOFF layout.
Usage: python build_ch_municipal.py RAWDIR OUTDIR   (needs pyarrow; schema.py from legal_scrapers on PYTHONPATH)"""
import json, sys, os, hashlib, datetime, shutil, collections
import pyarrow as pa, pyarrow.parquet as pq
sys.path.insert(0, os.environ.get("LEGAL_SCRAPERS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
from schema import MUNICIPAL_LAWS_SCHEMA, RAW_ARTICLES_SCHEMA, validate_municipal_table, municipal_law_id
import re

HEAD = re.compile(r"(?m)^[ \t\x0c\xad]{0,3}(Art\.|Art(?= )|§)[ \t]*(\d+)(bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies|undecies|duodecies|terdecies|quaterdecies|[a-z])?((?:[ \t]*(?:[–-]|bis(?= )|und(?= \d))[ \t]*(?:Art\.[ \t]?)?\d+[a-z]?)?)((?:[–-]\d+)*\d*)\.?\*?(?=\s|$|(?<=bis|ter)[A-ZÄÖÜ])([^\n]*)")
SUFS = ("bis", "ter", "quater", "quinquies", "sexies", "septies", "octies", "nonies", "novies", "decies", "undecies", "duodecies", "terdecies", "quaterdecies")
def _sufrank(suf):
    if not suf: return 0
    return SUFS.index(suf) + 1 if suf in SUFS else ord(suf) - 96

def split_articles(text):
    """Line-initial 'Art. N' / '§ N' headings (only the marker the document uses for its own articles).
    Footnote digits glued to a number ('Art. 52 Titel' = Art. 5, footnote 2) are resolved by taking the digit prefix that
    continues the sequence. A candidate that skips numbers is a reference ('Art. 44 ROAB richtet sich...') whenever a
    lower, still-expected number follows. Sentences wrapped to a line start ('Art. 6 übertragen werden.') and reference lines
    (Abs./Ziff./lit./und/sowie/,) are skipped. Numbers increase monotonically (suffixes bis/ter/a/b only after their base).
    Text before the first heading -> 'Ingress'."""
    allm = list(HEAD.finditer(text))
    nart = sum(1 for m in allm if m.group(1) in ("Art.", "Art")); npar = len(allm) - nart
    marker = "Art." if nart >= npar else "§"
    allm = [m for m in allm if (m.group(1) in ("Art.", "Art")) == (marker == "Art.")]
    def prefixes(m):
        d = m.group(2)
        return [int(d[:k]) for k in range(1, len(d) + 1)] if not (m.group(3) or m.group(4)) else [int(d)]
    def opts(m, prev=None):
        """Possible article numbers of a candidate: the full number when it plausibly continues the sequence, otherwise
        its digit prefixes (footnote digits glued on: 'Art. 52' = Art. 5 + footnote 2)."""
        full = int(m.group(2))
        if m.group(3) or m.group(4) or (prev is not None and prev < full <= prev + 15): return [full]
        return prefixes(m)
    def rng_end(m, num, nxt_vals=()):
        e = re.findall(r"\d+", m.group(4) or "")
        if not e: return num
        e = e[-1]; c = [int(e[:k]) for k in range(1, len(e) + 1) if num <= int(e[:k]) <= num + 60]
        if "und" in m.group(4): return num + 1 if num + 1 in c else num        # 'Art. 4 und 511' = Art. 4 and 5 + fn 11
        if not c: return num
        if nxt_vals:
            for cc in sorted(c):
                if cc + 1 in nxt_vals: return cc        # 'Art. 1 - 42' followed by Art. 5 -> range 1-4 (+ footnote 2)
        return min(c)
    CHG = re.compile(r"^\s*\d{2}\.\d{2}\.\d{4}|^\s*(Abs\.|Ziff\.|lit\.|Bst\.|und |bis |sowie |oder |,|ff\.|f\.)")
    plaus = [not CHG.match(m.group(6)) for m in allm]          # change-table rows / references don't count in look-ahead
    ahead = lambda ci: [x for x, ok in zip(allm[ci + 1:ci + 13], plaus[ci + 1:ci + 13]) if ok]
    pe = re.search(r"(?im)\b(verfügt|erlässt|beschliesst|beschließt|verordnet|beschlossen|erlassen)\s*:\s*$", text[:4000])
    pre_end = pe.end() if pe and re.search(r"(?i)gestützt auf|in Anwendung", text[:pe.start()]) else 0
    heads, prev, prev_suf, block = [], 0, None, 1
    for ci, m in enumerate(allm):
        if CHG.match(m.group(6)) and re.match(r"^\s*\d{2}\.\d{2}\.\d{4}", m.group(6)): continue   # change-table row
        rest = m.group(6)
        if re.search(r"\.{5,}|…{3,}", rest): continue                  # table-of-contents line
        if m.start() < pre_end: continue               # preamble ('gestützt auf ... Art. 20 GebR ..., verfügt:')
        refish = re.match(r"\s*(Abs\.|Ziff\.|lit\.|Bst\.|und |bis |sowie |oder |,|ff\.|f\.)", rest) or \
                 (re.match(r"^\s*[a-zäöü]", rest) and not re.match(r"^\s*(\(|[a-z]\.\s)", rest))           # reference / wrapped sentence
        if refish and not (int(m.group(2)) == prev + 1 and not m.group(3) and not any(prev + 1 in opts(x, prev) for x in ahead(ci))):
            continue                                   # ...unless it is the expected next article and nothing later claims that number
        if m.group(4) and rest.strip() and not re.search(r"[A-Za-zÄÖÜäöü(…]", rest): continue   # 'Art. 127 und 130 – 131.' (reference)
        if m.group(4) and "und" in m.group(4) and rng_end(m, int(m.group(2))) != int(m.group(2)) + 1: continue
        suf = m.group(3); num = None
        if suf:
            v = int(m.group(2))
            if v == prev and _sufrank(suf) > _sufrank(prev_suf): num = v
            elif v == prev + 1 or (prev < v <= prev + 15 and not any(prev < o < v for x in ahead(ci) for o in opts(x, prev))): num = v
        else:
            o = opts(m, prev); pre = prefixes(m); nxt = ahead(ci)[:3]
            if prev + 1 in o and not (m.group(4) and re.match(r"^\s*[.;,)]", rest)): num = prev + 1
            elif prev + 1 in pre and (o == pre or any(prev + 2 in opts(x, prev + 1) for x in nxt)): num = prev + 1   # 'Art. 11' = Art. 1 + fn 1
            else:
                for v in o:
                    chain = prev == 0 and not refish and sum(1 for k in (1, 2) if any(v + k in opts(x, v + k - 1) for x in ahead(ci)[:4])) == 2
                    if prev + 1 < v <= prev + 15 and not re.match(r"^\s*[.;,)]", rest) and (chain or not any(prev < x_o < v for x in ahead(ci) for x_o in opts(x, prev))):
                        num = v; break                 # (v, v+1, v+2 follow: a real sequence even if lower numbers appear later)
        if num is None and not suf and 1 in prefixes(m) and prev >= 3 and not refish \
                and re.match(r"^\s*(\d\s+)?[A-ZÄÖÜ][a-zäöüß]", rest) and m.start() == text.rfind("\n", 0, m.start() + 1) + 1 \
                and [v for x in ahead(ci)[:2] for v in prefixes(x)][:1] == [2] and any(3 in prefixes(x) for x in ahead(ci)[1:4]):
            block += 1; num = 1; prev, prev_suf = 0, None        # numbering restarts at Art. 1: a second enactment text in the file
        if num is None: continue
        label = f"{num}{suf or ''}" if block == 1 else f"{block}.{num}{suf or ''}"
        if label in {h[1] for h in heads}: continue
        heads.append((m.start(), label, f"{'Art.' if m.group(1) == 'Art' else m.group(1)} {label}{m.group(4)} {rest.strip()}".strip()))
        prev, prev_suf = (rng_end(m, num, {v for x in ahead(ci)[:3] for v in prefixes(x)}) if m.group(4) else num), suf
    out = []
    if not heads:
        return [("1", "whole text", text.strip())], 1.0
    if heads[0][0] > 0 and text[:heads[0][0]].strip():
        out.append(("0", "Ingress", text[:heads[0][0]].strip()))
    # annexes after the last article (tables that cite articles line-initially) become their own records
    anx = [m.start() for m in re.finditer(r"(?m)^[ \t]*(Anhang|Anhänge|Beilage)\b[^\n]{0,80}$", text) if m.start() > heads[-1][0]]
    for i, (pos, label, title) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else (anx[0] if anx else len(text))
        out.append((label, title[:300], text[pos:end].strip()))
    for k, a0 in enumerate(anx, 1):
        a1 = anx[k] if k < len(anx) else len(text)
        out.append((f"anhang-{k}", text[a0:a0 + 200].split("\n")[0].strip()[:300], text[a0:a1].strip()))
    cov = sum(len(b) for _, _, b in out) / max(1, len(text.strip()))
    return out, cov

def article_checks(arts, text):
    """Sequence checks on split output.
    gaps: base numbers missing between consecutive articles (ranges 'Art. 3 bis 13' / 'Art. 36–46' count as covering).
    hidden: line-initial headings of the doc's marker inside a record whose number is the record's own or the next one
    and which is not itself a record (= a missed heading, i.e. a record holding several articles).
    source_gap: a gap number that occurs nowhere in the text as a line-start heading (absent from the source)."""
    labs = {n for n, _, _ in arts}; prev_end, gaps, hidden = None, [], []
    mk = r"Art\.?" if sum(t.startswith("Art.") for _, t, _ in arts) >= sum(t.startswith("§") for _, t, _ in arts) else "§"
    cur_blk = None
    for n, ti, body in arts:
        m = re.match(r"^(?:(\d+)\.)?(\d+)", n)
        if not m or n == "0": continue
        if m.group(1) != cur_blk: cur_blk, prev_end = m.group(1), None
        num = int(m.group(2))
        r = re.match(r"^(?:Art\.|§) \d+[a-z]*\s*(?:[–-]|\sbis\s|\sund\s)\s*(?:Art\.\s?)?(\d+)", ti)
        end = num
        if r:
            e = r.group(1)
            end = max(int(e[:k]) for k in range(1, len(e) + 1) if int(e[:k]) <= num + 60) if int(e[:1]) else num
        if prev_end is not None and num > prev_end + 1: gaps += [(cur_blk, g) for g in range(prev_end + 1, num)]
        prev_end = max(end, prev_end or 0)
        for h in list(re.finditer(r"(?m)^(?:" + mk + r") ?(\d+)(bis|ter|quater|quinquies|sexies|septies|octies|nonies|[a-z])?(?=\s)([^\n]*)", body))[1:]:
            if re.match(r"\s*(Abs\.|Ziff\.|lit\.|Bst\.|und |bis |sowie |oder |,|ff\.|f\.|[a-zäöü])", h.group(3)): continue
            lab = h.group(1) + (h.group(2) or "")
            if lab not in labs and num <= int(h.group(1)) <= num + 1: hidden.append(f"{n}>{lab}")
    span = collections.defaultdict(str)          # text of each numbering block (block 2+ = a second enactment in the file)
    for n, _, body in arts:
        mm = re.match(r"^(?:(\d+)\.)?\d", n)
        span[mm.group(1) if mm else None] += body + "\n"
    span[None] = text if len(span) <= 1 else span[None]
    src = [(b, g) for b, g in gaps if not re.search(r"(?m)^\W{0,2}(?:" + mk + r")\s?" + str(g) + r"(?!\d)", span[b])]
    lab = lambda b, g: f"{b}.{g}" if b else g
    return [lab(b, g) for b, g in gaps], hidden, [lab(b, g) for b, g in src]

LIC = "Official enactments, not protected by copyright under Art. 5 para. 1 lit. a Swiss Copyright Act (URG); attribution to source retained"
def sha(p): h = hashlib.sha256(); h.update(open(p, "rb").read()); return h.hexdigest()

STATS = {}
def _ver(d):
    """A folded (repealed, same-title) version keeps its full text, not just the link."""
    return dict(native_id=d["native_id"], title=d["title"], source_url=d["source_url"], law_status="repealed",
                retrieved_at=d["retrieved_at"], sha256_text=hashlib.sha256(d["text"].encode()).hexdigest(), text=d["text"])

def main(raw, out):
    docs = [json.loads(l) for l in open(f"{raw}/raw/docs.jsonl")]
    zf = f"{raw}/raw/docs_zh_layout.jsonl" if os.path.exists(f"{raw}/raw/docs_zh_layout.jsonl") else f"{raw}/raw/docs_zh.jsonl"
    if os.path.exists(zf): docs += [json.loads(l) for l in open(zf)]
    STATS["zh_discovered_act_pages"] = 792; STATS["zh_fetched"] = sum(1 for d in docs if d["municipality_code"] == "261")
    DROP = {("351", "153.210"), ("2701", "BaB 172.900"), ("2701", "BaB 172.400"), ("2701", "BaB 171.300")}
    docs = [d for d in docs if (d["municipality_code"], d["native_id"]) not in DROP]
    for d in docs:
        d["status"] = "repealed" if (re.search(r"Aufgehoben", d["text"][:800]) or re.search(r"\((Aufgehoben|Ausser Kraft|aufgehoben)\)", d["title"])) else "in_force"
    # agreements are not enactments (Verifier rule applied to Basel BG): exclude Zürich Verträge/Vereinbarungen too
    # (any title containing vertrag / vereinbarung / statuten: Subventions-, Stiftungs-, Anschluss-, Tagblattvertrag, foundation Statuten)
    excl = [d for d in docs if d["municipality_code"] == "261" and re.search(r"(?i)vertrag|vereinbarung|statuten", d["title"])]
    STATS["zh_excluded_agreements_statutes"] = sorted(d["native_id"] for d in excl)
    # same rule for the LexFind municipalities (Riehen, Bettingen, Bürgergemeinde Basel): boundary treaties, Verträge, Vereinbarungen.
    # Bern 153.11 is a Gemeinderatsbeschluss on general terms of contract (an enactment), so Bern is not filtered by title.
    lx = [d for d in docs if d["municipality_code"] in ("2701", "2702", "2703") and re.search(r"(?i)vertrag|vereinbarung|statuten", d["title"])]
    STATS["lexfind_excluded_agreements"] = sorted(f'{d["municipality_code"]}:{d["native_id"]}' for d in lx)
    excl += lx
    docs = [d for d in docs if d not in excl]
    # same-title duplicates: keep current version, fold repealed same-title versions into extras
    cur_titles = {(d["municipality_code"], d["title"].strip().lower()) for d in docs if d["status"] == "in_force"}
    kept = []
    for d in docs:
        if d["status"] == "repealed" and (d["municipality_code"], d["title"].strip().lower()) in cur_titles:
            for c in docs:
                if c["status"] == "in_force" and c["municipality_code"] == d["municipality_code"] and c["title"].strip().lower() == d["title"].strip().lower():
                    c["extras"].setdefault("repealed_versions", []).append(_ver(d)); break
            continue
        kept.append(d)
    # remaining repealed versions sharing a title among themselves: keep newest native id only
    seen_rep = {}
    for d in sorted(kept, key=lambda x: x["native_id"]):
        if d["status"] == "repealed":
            k = (d["municipality_code"], d["title"].strip().lower())
            if k in seen_rep: seen_rep[k]["extras"].setdefault("repealed_versions", []).append(_ver(d)); d["_drop"] = 1
            else: seen_rep[k] = d
    docs = [d for d in kept if not d.get("_drop")]
    laws, byid, byhash = [], {}, {}
    for d in docs:
        if len((d["text"] or "").strip()) < 80: continue
        lid = municipal_law_id("ch", d["municipality_code"], d["native_id"])
        h = hashlib.sha256(d["text"].encode()).hexdigest()
        key = (d["municipality_code"], h)
        if key in byhash:   # same text within municipality -> keep one, record alt url
            byhash[key]["extras"].setdefault("alt_urls", []).append(d["source_url"]); continue
        if lid in byid and byid[lid]["retrieved_at"] >= d["retrieved_at"]: continue
        d["id"] = lid; d["sha"] = h; byid[lid] = d; byhash[key] = d
    arts = []
    for d in byid.values():
        a, cov = split_articles(d["text"]); d["n_art"] = len(a)
        assert cov >= 0.95, (d["native_id"], cov)
        d["extras"]["article_text_coverage"] = round(cov, 4)
        gaps, hidden, src_gaps = article_checks(a, d["text"])
        # every numbering gap must be absent from the source text itself, and no record may hide a further article heading
        if os.environ.get("CH_CHECK_ONLY"):
            if set(gaps) - set(src_gaps) or hidden: print("CHECK", d["municipality_code"], d["native_id"], sorted(set(gaps) - set(src_gaps))[:8], hidden[:4])
        else:
            assert set(gaps) <= set(src_gaps), (d["native_id"], sorted(set(gaps) - set(src_gaps)))
            assert not hidden, (d["native_id"], hidden)
        if gaps: d["extras"]["numbering_gaps_in_source"] = gaps; STATS["laws_with_source_numbering_gaps"] = STATS.get("laws_with_source_numbering_gaps", 0) + 1
        if len(a) == 1: STATS["whole_text_records"] = STATS.get("whole_text_records", 0) + 1
        for i, (n, title, body) in enumerate(a, 1):
            arts.append(dict(law_id=d["id"], id=f"{d['id']}-art-{n.lower()}", title=title, text=body, source_url=d["source_url"],
                             document_number=d["native_id"], article_number=n, record_type="article", metadata_json="{}"))
    rows = [dict(id=d["id"], title=d["title"], text=d["text"], source_url=d["source_url"], source_type="official_pdf",
                 jurisdiction=f"CH/{d['admin1']}/{d['municipality']}", country="Switzerland", language=d["language"], eli=None,
                 date=d.get("date"), date_issued=d.get("date"), retrieved_at=d["retrieved_at"], license=LIC, law_status=d["status"],
                 identifier=d["native_id"], official_identifier=d["native_id"], article_count=d["n_art"], json_path=None,
                 metadata_json=json.dumps({"extras": {**d["extras"], "sha256_text": d["sha"]}}, ensure_ascii=False),
                 jurisdiction_level="municipal", admin_level=8, country_iso="CH", admin1=d["admin1"], municipality=d["municipality"],
                 municipality_code=d["municipality_code"], source_body=d["source_body"]) for d in byid.values()]
    t = pa.Table.from_pylist(rows, schema=MUNICIPAL_LAWS_SCHEMA)
    errs = validate_municipal_table(t); assert not errs, errs
    at = pa.Table.from_pylist(arts, schema=RAW_ARTICLES_SCHEMA)
    assert len(set(zip(at["law_id"].to_pylist(), at["id"].to_pylist()))) == at.num_rows
    os.makedirs(f"{out}/data", exist_ok=True); os.makedirs(f"{out}/scrapers", exist_ok=True)
    pq.write_table(t, f"{out}/data/laws-00001.parquet", compression="zstd")
    pq.write_table(at, f"{out}/data/articles-00001.parquet", compression="zstd")
    here = os.path.dirname(os.path.abspath(__file__))
    shutil.copy(f"{here}/collect_ch_municipal.py", f"{out}/scrapers/collect_ch_municipal.py")
    shutil.copy(f"{here}/build_ch_municipal.py", f"{out}/scrapers/build_ch_municipal.py")
    shutil.copy(f"{here}/collect_ch_zurich.py", f"{out}/scrapers/collect_ch_zurich.py")
    shutil.copy(f"{here}/zh_pointers.py", f"{out}/scrapers/zh_pointers.py")
    for extra in ("fetch_zh_pdfs.py", "pdf_columns.py", "reextract_zh.py"): shutil.copy(f"{here}/{extra}", f"{out}/scrapers/{extra}")
    munis = collections.Counter(r["municipality"] for r in rows)
    files = {p: sha(f"{out}/{p}") for p in ["data/laws-00001.parquet", "data/articles-00001.parquet", "scrapers/collect_ch_municipal.py", "scrapers/build_ch_municipal.py", "scrapers/collect_ch_zurich.py", "scrapers/zh_pointers.py", "scrapers/fetch_zh_pdfs.py", "scrapers/pdf_columns.py", "scrapers/reextract_zh.py"]}
    man = dict(slug="switzerland", country_iso="CH", collector="scrapers/collect_ch_municipal.py",
               built_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               laws_rows=t.num_rows, articles_rows=at.num_rows, municipalities=dict(munis), sha256=files,
               law_status_counts=dict(collections.Counter(r["law_status"] for r in rows)), build_stats=STATS,
               sources=["https://www.lexfind.ch (category 9 Gemeindeerlass)", "https://stadtrecht.bern.ch (sitemap lex-* PDF exports)", "https://www.stadt-zuerich.ch Amtliche Sammlung (act pages -> current PDF)"])
    json.dump(man, open(f"{out}/MANIFEST.json", "w"), indent=1, ensure_ascii=False)
    print(json.dumps({k: man[k] for k in ("laws_rows", "articles_rows", "municipalities")}))

if __name__ == "__main__": main(sys.argv[1], sys.argv[2])
