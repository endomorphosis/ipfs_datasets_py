"""Build denmark_municipal from the NSTAR texts fetched by collect_dk_nstar.py (offline).
  python build_dk_municipal.py <dk_build dir> <out dir>
One row per published affaldsregulativ (husholdning / erhverv) per kommune; articles: preamble (title + indholdsfortegnelse),
one record per § (its §N.N sub-sections included), one record per bilag listed in the indholdsfortegnelse."""
import os, sys, re, json, gzip, collections, hashlib, shutil, unicodedata, datetime
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import pyarrow as pa, pyarrow.parquet as pq
from schema import MUNICIPAL_LAWS_SCHEMA, RAW_ARTICLES_SCHEMA, validate_municipal_table, municipal_law_id
from collect_dk_nstar import norm_kommune, BASE
from collect_dk_kommune_pdfs import CURRENCY, EXTRA, DATES, CHECKED
COLLECTORS = ("collect_dk_nstar.py", "collect_dk_kommune_pdfs.py", "build_dk_municipal.py")
LIC = ("Danish municipal affaldsregulativer are administrative regulations (administrative forskrifter) issued under miljøbeskyttelsesloven; "
       "under ophavsretsloven (LBK 2023/1093) § 9, stk. 1 laws, administrative regulations and similar public documents are not subject to copyright. "
       "Separate works reproduced in them (e.g. maps, photos in bilag) may keep their protection (§ 9, stk. 2). Texts as published in NSTAR (Energistyrelsen).")
TYPE_TITLE = {"husholdning": "Regulativ for husholdningsaffald", "erhverv": "Regulativ for erhvervsaffald"}
OFFICIAL = {"København": "Københavns Kommune", "Bornholm": "Bornholms Regionskommune"}
STATS = collections.Counter(); DROPS = collections.defaultdict(list); HEADING_ONLY = []
CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\ufffd\ue000-\uf8ff]")
FOOTER = re.compile(r"^\s*Side\s+\d+(\s*(af|/)\s*\d+)?\s*$")
TOC_SEC = re.compile(r"^§\s?(\d+[a-z]?)\.?\s+(.+?)(?:\s*\.{2,}\s*|\s+)(\d+)$")  # page number after spaces or a dot leader
TOC_BIL = re.compile(r"^(Bilag\s*(\d+))\b.*?\s+(\d+)$", re.I)
HEAD = re.compile(r"^§\s?(\d+[a-z]?)(?:\.\s*(?=\D)|\s+)(\S.{0,150})$")   # '§17 Ordning', '§ 17. Ordning', '§17.Ordning' (not '§17.1')
SUBSEC = re.compile(r"^§\s?(\d+[a-z]?)\.(\d+)")         # §N.M sub-section line
SECLINE = re.compile(r"^§\s?\d+[a-z]?\.?\s+\D")         # another '§N text' line (heading or cross-reference list item)

def follow(L, j, k, depth=0):
    """What follows the '§k ...' line L[j]: 'strong' = its own §k.M sub-section (after at most one heading-continuation line),
    'weak' = prose, None = a sub-section of another § or a §-list line (a cross-reference, not a heading). A §-line that directly
    follows is accepted only if it is the next § (successor of k) and is itself a valid heading (empty stub sections such as
    '§27 Ordning for [...]' followed by '§28 Øvrige ordninger')."""
    nb = [i for i in range(j + 1, min(len(L), j + 12)) if L[i].strip()][:2]
    if not nb: return "weak"
    x = L[nb[0]]
    m = SUBSEC.match(x)
    if m: return "strong" if m.group(1) == k else None
    if SECLINE.match(x):
        h = HEAD.match(x)
        if h and h.group(1) == k: return "weak"                     # a sub-heading of the same § ('§28 Øvrige ordninger' / '§ 28 ordning for ...')
        if h and h.group(1) in successors(k) and depth < 3 and follow(L, nb[0], h.group(1), depth + 1): return "weak"
        return None
    if re.match(r"^bilag\s*\d", x, re.I): return "weak"
    if len(nb) > 1:
        m = SUBSEC.match(L[nb[1]])
        if m and m.group(1) == k and len(x) < 90: return "strong"   # heading wrapped over two lines
    return "weak"

def successors(lab):
    n, x = re.fullmatch(r"(\d+)([a-z]?)", lab).groups(); n = int(n)
    return [str(n + 1), f"{n + 1}a", f"{n}a"] if not x else [f"{n}{chr(ord(x) + 1)}", str(n + 1), f"{n + 1}a"]

SYM = {"\uf0b7": "•", "\uf0a7": "▪", "\uf0d8": "➢", "\uf0fc": "✓", "\uf0e0": "→", "\uf02d": "–", "\uf06f": "o", "\uf076": "❖", "\uf0be": "–"}  # Symbol/Wingdings bullets
SYM_STATS = collections.Counter()

WM = re.compile(r"Created with EO\.Pdf(?: for \.NET trial version\. http://www\.essentialobjects\.com\.)?|\.NET trial version\. http://www\.essentialobjects\.com\.")

PAGEOF = re.compile(r"^(?:\d{2}-\d{2}-\d{4}\s.*?)?\d{1,3}\s+af\s+\d{1,3}$")  # 'N af M' / 'DD-MM-YYYY ... N af M' page footers

def clean(t):
    n = len(WM.findall(t))
    if n:  # EO.Pdf trial watermark (generator artefact, one per page); on p. 1 it interleaves with 'Gældende fra d.'
        STATS["eo_pdf_trial_watermarks_removed"] += n; t = WM.sub("", t)
        t2 = re.sub(r"(?m)^\s*fra\s*\n(\s*)Gældende  ford\.\s*$", r"\1Gældende fra d.", t)
        STATS["eo_pdf_watermark_title_lines_repaired"] += t2 != t; t = t2
    for k, v in SYM.items():
        n = t.count(k)
        if n: SYM_STATS[f"U+{ord(k):04X}->{v}"] += n; t = t.replace(k, v)
    def _bul(m): SYM_STATS[f"U+{ord(m.group(2)):04X}->• (line-initial list marker)"] += 1; return m.group(1) + "•"
    t = re.sub(r"(?m)^(\s*)([\uf020-\uf0ff])(?=\s)", _bul, t)
    t = unicodedata.normalize("NFC", t.replace("\f", "\n").replace("\u00a0", " "))
    out, prev_blank = [], True
    for l in t.split("\n"):
        if FOOTER.match(l): STATS["footer_lines_removed"] += 1; continue
        l = l.strip()
        if PAGEOF.match(l): STATS["page_of_footer_lines_removed"] += 1; continue
        if not l:
            if not prev_blank: out.append("")
            prev_blank = True; continue
        out.append(l); prev_blank = False
    return "\n".join(out).strip()

def key(s): return re.sub(r"[^a-zæøå0-9]", "", s.lower())[:14]

def split(text):
    L = text.split("\n")
    toc = {}; bil = {}; last_toc = -1
    for i, l in enumerate(L[:400]):
        m = TOC_SEC.match(l)
        if m and int(m.group(3)) < 2000: toc.setdefault(m.group(1), m.group(2)); last_toc = i; continue
        m = TOC_BIL.match(l)
        if m and toc: bil.setdefault(int(m.group(2)), l); last_toc = i
    heads, exp, j, strength = [], ["1"], last_toc + 1, None
    while j < len(L):
        m = HEAD.match(L[j])
        if m and not TOC_SEC.match(L[j]):
            k = m.group(1); t = toc.get(k)
            f = follow(L, j, k)
            # title must agree with the contents list, unless the line is followed by its own §k.1 ('§17.Ordningen for ...' vs 'Ordning for ...')
            title_ok = t is None or key(m.group(2)).startswith(key(t)[:8]) or key(t).startswith(key(m.group(2))[:8])
            if title_ok or f == "strong":
                if k in exp and f:
                    heads.append((j, k, L[j])); exp = successors(k); strength = f
                elif title_ok and f == "strong" and heads and heads[-1][1] == k and strength == "weak":
                    # the accepted §k heading was followed only by prose (e.g. a '§ 18 Ordning for ...' reference inside §17);
                    # a later §k line followed by its own §k.1 is the real heading
                    heads[-1] = (j, k, L[j]); strength = f; STATS["weak_heading_replaced_by_later_strong"] += 1
        j += 1
    if not heads: return [("1", None, text)], dict(toc_sections=len(toc), found=0)
    bheads = []
    if bil:
        j = heads[-1][0] + 1
        for n in sorted(bil):
            for jj in range(j, len(L)):
                if re.match(rf"^Bilag\s*{n}\b", L[jj], re.I) and len(L[jj]) <= 200:
                    bheads.append((jj, f"bilag-{n}", L[jj])); j = jj + 1; break
    starts = [(0, "0", None)] + heads + bheads
    if starts[1][0] == 0: starts = starts[1:]
    recs = []
    for a, b in zip(starts, starts[1:] + [(len(L), None, None)]):
        recs.append((a[1], a[2], "\n".join(L[a[0]:b[0]])))
    return recs, dict(toc_sections=len(toc), toc_bilag=len(bil), found=len(heads), bilag_found=len(bheads))

def ddmmyy(s):
    m = re.fullmatch(r"(\d{2})-(\d{2})-(\d{2}|\d{4})", (s or "").strip())
    if not m: return None
    y = m.group(3); y = int(y) + 2000 if len(y) == 2 else int(y)
    return f"{y:04d}-{m.group(2)}-{m.group(1)}"

def main(B="dk_build", OUT="denmark_municipal"):
    kk = json.load(open(f"{B}/kommunekoder.json")); codes = kk["codes"]
    region, cur = {}, None
    for v in kk["statbank_folk1a_omraade"]:
        if re.fullmatch(r"08[1-5]", v["id"]): cur = v["text"]
        elif re.fullmatch(r"\d{3}", v["id"]) and int(v["id"]) >= 101: region[v["id"]] = cur
    recs_in, errs_in = {}, {}
    with gzip.open(f"{B}/nstar_texts.jsonl.gz", "rt") as f:
        try:
            for l in f:
                r = json.loads(l)
                if r.get("error"): errs_in[(r["type"], r["document_id"])] = dict(kommune=r["kommune"], type=r["type"], document_id=r["document_id"], error=r["error"]); continue
                recs_in[(r["type"], r["document_id"])] = r
        except EOFError: STATS["truncated_shard_tail"] += 1
    for k_, e_ in errs_in.items():
        if k_ in recs_in: STATS["download_retried_ok"] += 1
        else: DROPS["download_error"].append(e_)
    today = datetime.date.today().isoformat(); rows, arts, excluded = [], [], []
    # kommune-site replacement / extra texts (collect_dk_kommune_pdfs.py); see CURRENCY for the pre-2021 NSTAR rows
    kom_in = {}
    if os.path.exists(f"{B}/kommune_texts.jsonl.gz"):
        for l in gzip.open(f"{B}/kommune_texts.jsonl.gz", "rt"):
            r = json.loads(l); k_ = tuple(r["key"]) if isinstance(r["key"], list) else r["key"]
            if r.get("error"): DROPS["kommune_pdf_error"].append(dict(key=r["key"], source_url=r["source_url"], error=r["error"])); continue
            kom_in[k_] = r
    jobs = []
    for (typ, did), r in recs_in.items():
        cur = CURRENCY.get(did)
        if cur and cur["outcome"] == "replaced" and did in kom_in:
            k = kom_in[did]; d_ad, d_eff = DATES[did]
            jobs.append((typ, dict(r, **{x: k[x] for x in ("text", "pages", "pdf_bytes", "pdf_sha256", "filename", "producer", "retrieved_at")}),
                         dict(kind="kommune", source_url=cur["url"], adopted=d_ad, date=d_ad or d_eff, eff=d_eff, native=f"{typ}-{d_eff}", stale_nstar=r, cur=cur)))
            STATS["nstar_rows_replaced_by_kommune_pdf"] += 1
        else:
            if cur and cur["outcome"] == "replaced": cur = dict(cur, outcome="superseded", superseded_by=cur["url"], note=cur["note"] + " (kommune PDF could not be fetched at build time)")
            jobs.append((typ, r, dict(kind="nstar", cur=cur)))
    for (typ, kname), e in EXTRA.items():
        if (typ, kname) not in kom_in: continue
        k = kom_in[(typ, kname)]; d_ad, d_eff = DATES[(typ, kname)]
        jobs.append((typ, dict(k, kommune=kname, type=typ, document_id=None, approved=None, paradigm_id=None, status_note=None),
                     dict(kind="extra", source_url=e["url"], original_url=e.get("original_url"), adopted=d_ad, date=d_ad or d_eff, eff=d_eff, native=f"{typ}-{d_eff}", extra=e)))
        DROPS["download_error"] = [x for x in DROPS["download_error"] if not (x["type"] == typ and x["kommune"] == kname)]
        DROPS["download_error_resolved"].append(dict(kommune=kname, type=typ, nstar_document_id=e["nstar_document_id"], resolution="kommune PDF (archive replay) ingested instead; see the row's extras.note"))
    if not DROPS["download_error"]: del DROPS["download_error"]
    for typ, r, src in sorted(jobs, key=lambda x: (x[1]["kommune"], x[0])):
        did = r["document_id"]
        code = codes.get(norm_kommune(r["kommune"])); assert code, r["kommune"]
        chars_pp = len(re.sub(r"\s", "", r["text"])) / max(1, r["pages"])
        if chars_pp < 200:
            excluded.append(dict(kommune=r["kommune"], kommunekode=code, type=typ, document_id=did, filename=r["filename"], pages=r["pages"], chars_per_page=round(chars_pp, 1))); continue
        text = clean(r["text"]); recs, sinfo = split(text)
        native = did if src["kind"] == "nstar" else src["native"]
        lid = municipal_law_id("dk", code, native); mname = OFFICIAL.get(r["kommune"], f"{r['kommune']} Kommune")
        title = f"{TYPE_TITLE[typ]} – {mname}"
        if src["kind"] == "nstar":
            eff = re.search(r"Gældende fra(?: d\.)?\s*(\d{2})[-.](\d{2})[-.](\d{4})", text[:2000])
            eff = f"{eff.group(3)}-{eff.group(2)}-{eff.group(1)}" if eff else None
            date = ddmmyy(r["approved"]); src_url = BASE
            ex = dict(nstar_document_id=did, paradigm_id=r.get("paradigm_id"), regulation_type=typ, nstar_approved=r["approved"], effective_from=eff,
                      pdf_filename=r["filename"], pdf_sha256=r["pdf_sha256"], pdf_bytes=r["pdf_bytes"], pages=r["pages"], pdf_producer=r.get("producer"),
                      nstar_status_note=r.get("status_note"), split=sinfo, region=region.get(code),
                      text_extraction="pdftotext -layout (poppler); lines left/right-stripped, 'Side N' page footers and EO.Pdf trial watermarks removed, blank-line runs collapsed, Symbol-font PUA bullets mapped (U+F0B7 -> •), NFC",
                      download="POST " + BASE + " (ASP.NET postback of the row's 'PDF' button; DocumentId = nstar_document_id)")
            status = "in_force" if not eff or eff <= today else "adopted_not_yet_in_force"
            cur = src["cur"]
            if cur:
                ex["currency_check"] = dict(outcome=cur["outcome"], checked=CHECKED, note=cur["note"], url=cur.get("superseded_by") or cur.get("evidence_url"))
                if cur["outcome"] == "superseded": status = "superseded"; ex["superseded_by"] = cur["superseded_by"]
                elif cur["outcome"] == "unverified_current": status = "unverified_current"
                STATS[f"pre2021_{cur['outcome']}"] += 1
            ident, offid = did, f"NSTAR regulativ {did} ({mname}, {typ})"
        else:
            eff, date, src_url = src["eff"], src["date"], src["source_url"]
            ex = dict(regulation_type=typ, effective_from=eff, adopted=src.get("adopted"),
                      source="kommune website PDF" + (" (Wayback Machine replay of the kommune's URL)" if "web.archive.org" in src_url else ""),
                      original_url=src.get("original_url"), pdf_filename=r["filename"], pdf_sha256=r["pdf_sha256"], pdf_bytes=r["pdf_bytes"], pages=r["pages"],
                      pdf_producer=r.get("producer"), split=sinfo, region=region.get(code),
                      text_extraction="pdftotext -layout (poppler) of a born-digital PDF; lines left/right-stripped, 'Side N' page footers removed, blank-line runs collapsed, Symbol-font PUA bullets mapped, NFC",
                      download="GET source_url (robots.txt checked, 1.5 s spacing)")
            if src["kind"] == "kommune":
                st = src["stale_nstar"]
                ex.update(replaces_nstar=dict(nstar_document_id=did, nstar_approved=st["approved"], nstar_law_id=municipal_law_id("dk", code, did),
                                               nstar_status_note=st.get("status_note"), stale=True),
                          currency_check=dict(outcome="replaced", checked=CHECKED, note=src["cur"]["note"], url=src_url))
                status = "in_force" if eff <= today else "adopted_not_yet_in_force"
                ident, offid = native, f"{TYPE_TITLE[typ]}, {mname}, i kraft {eff} (kommune website; replaces stale NSTAR regulativ {did})"
                STATS["pre2021_replaced"] += 1
                if "1292" == did: ex["note"] = "PDF metadata title reads 'Forslag til ...'; the text is the adopted regulativ (vedtaget 05-09-2023) linked by the kommune."
                if "2206" == did: ex["note"] = "PDF metadata title reads 'Udkast til ...'; the text is the adopted regulativ (gældende fra 01-01-2023) linked by the kommune. The text gives no adoption date, so date = ikrafttrædelse."
            else:
                e = src["extra"]; ex.update(nstar_document_id_unavailable=e["nstar_document_id"], note=e["note"], may_not_be_latest=True)
                status = "unverified_current"
                ident, offid = native, f"{TYPE_TITLE[typ]}, {mname} (kommune website '2025' PDF; NSTAR regulativ {e['nstar_document_id']} could not be downloaded)"
                STATS["extra_kommune_rows"] += 1
        if lid == "dk-mun-240-2916": ex["has_amendment"] = dict(record="bilag-2", note="Bilag 2 is a Tillæg (amendment) to the regulativ, in force 01-07-2024, with its own §1ff.")
        ex = {k: v for k, v in ex.items() if v not in (None, [], {})}
        assert "\n".join(x[2] for x in recs) == text, lid
        labs = [x[0] for x in recs]; assert len(labs) == len(set(labs)), (lid, labs)
        for lab, ht, b in recs:
            rt = "whole_text" if len(recs) == 1 else "preamble" if lab == "0" else "schedule" if lab.startswith("bilag") else "article"
            md = {"heading": ht} if ht else {}
            if ht and b.strip() == ht.strip():
                md["heading_only"] = True; STATS["heading_only_records"] += 1
                md["note"] = (f"bilag listed in the regulativ; its content is not part of the {'NSTAR' if src['kind'] == 'nstar' else 'published'} text" if lab.startswith("bilag") else "section has a heading and no text in the published regulativ")
                HEADING_ONLY.append(dict(id=f"{lid}-art-{lab}", municipality=mname, type=typ, heading=ht, kind="bilag not in text" if lab.startswith("bilag") else "empty section"))
            if lid == "dk-mun-240-2916" and lab == "bilag-2":
                md["amendment"] = True; md["note"] = "Tillæg (amendment) to the regulativ, in force 01-07-2024, with its own §1ff.; kept as a schedule record"
            arts.append(dict(law_id=lid, id=f"{lid}-art-{lab}", title=title, text=b, source_url=src_url, document_number=ident, article_number=lab,
                             record_type=rt, metadata_json=json.dumps(md, ensure_ascii=False)))
        STATS["whole_text_records"] += len(recs) == 1
        STATS["toc_mismatch"] += bool(sinfo.get("toc_sections")) and sinfo["toc_sections"] != sinfo["found"]
        if bool(sinfo.get("toc_sections")) and sinfo["toc_sections"] != sinfo["found"]: DROPS["toc_mismatch_info"].append(dict(id=lid, **sinfo))
        rows.append(dict(id=lid, title=title, text=text, source_url=src_url, source_type="official_pdf", jurisdiction=f"DK/{mname}", country="Denmark", language="da",
                         eli=None, date=date, date_issued=date, retrieved_at=r["retrieved_at"], license=LIC,
                         law_status=status, identifier=ident,
                         official_identifier=offid, article_count=len(recs), json_path=None,
                         metadata_json=json.dumps({"extras": ex}, ensure_ascii=False), jurisdiction_level="municipal", admin_level=7, country_iso="DK",
                         admin1=region.get(code), municipality=mname, municipality_code=code, source_body=f"Kommunalbestyrelsen, {mname}"))
    fails = []
    for r in rows:
        try:
            txt = r["text"] + "\n" + r["title"]
            assert not CTRL.search(txt), (r["id"], "control / FFFD / PUA / C1", CTRL.findall(txt)[:5])
            assert unicodedata.normalize("NFC", txt) == txt, (r["id"], "not NFC")
            assert re.search(r"[æøå]", r["text"]) and re.search(r"\baffald", r["text"].lower()), (r["id"], "not Danish waste regulation text")
            assert r["date"] and "2010-01-01" <= r["date"] <= today, (r["id"], r["date"])
            assert re.fullmatch(r"dk-mun-\d{3}-(\d+|(husholdning|erhverv)-\d{4}-\d{2}-\d{2})", r["id"]), r["id"]
            assert len(r["text"]) > 2000, (r["id"], "too short")
            assert "essentialobjects" not in r["text"] and "EO.Pdf" not in r["text"], (r["id"], "EO.Pdf watermark left")
        except AssertionError as e: fails.append(e.args[0] if e.args else r["id"])
    for a in arts:
        if not a["text"].strip(): fails.append((a["id"], "empty article"))
    if fails: json.dump(fails, open(f"{B}/gate_failures.json", "w"), ensure_ascii=False, default=str)
    assert not fails, (len(fails), fails[:8])
    t = pa.Table.from_pylist(rows, schema=MUNICIPAL_LAWS_SCHEMA); errs = validate_municipal_table(t); assert not errs, errs
    at = pa.Table.from_pylist(arts, schema=RAW_ARTICLES_SCHEMA); assert len(set(at["id"].to_pylist())) == at.num_rows
    assert len(set(t["id"].to_pylist())) == t.num_rows
    cnt = collections.Counter(x["law_id"] for x in arts); assert all(cnt[r["id"]] == r["article_count"] for r in rows)
    os.makedirs(f"{OUT}/data", exist_ok=True); os.makedirs(f"{OUT}/scrapers", exist_ok=True)
    pq.write_table(t, f"{OUT}/data/laws.parquet", compression="zstd"); pq.write_table(at, f"{OUT}/data/articles.parquet", compression="zstd")
    for f in COLLECTORS: shutil.copy(f"{HERE}/{f}", f"{OUT}/scrapers/{f}")
    shutil.copy(f"{os.path.dirname(HERE)}/schema.py", f"{OUT}/scrapers/schema.py")
    files = {}
    for root, _, fs in os.walk(OUT):
        for f in fs:
            p_ = os.path.join(root, f); rel = os.path.relpath(p_, OUT)
            if rel in ("MANIFEST.json", "README.md", "HANDOFF_READY") or "__pycache__" in rel: continue
            files[rel] = hashlib.sha256(open(p_, "rb").read()).hexdigest()
    mc = collections.Counter((r["municipality_code"], r["municipality"]) for r in rows)
    ex_all = [json.loads(r["metadata_json"])["extras"] for r in rows]
    per_m = collections.Counter(f"{e['kommunekode']} {e['kommune']}" for e in excluded)
    man = dict(slug="denmark_municipal", country_iso="DK", collectors=list(COLLECTORS), license_note=LIC,
               built_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), laws_rows=len(rows), articles_rows=len(arts),
               data_file_names=["data/laws.parquet", "data/articles.parquet"],
               municipalities={f"{k} {n}": c for (k, n), c in sorted(mc.items())}, municipalities_count=len(mc),
               regulation_type_counts=dict(collections.Counter(e["regulation_type"] for e in ex_all)),
               region_counts=dict(collections.Counter(r["admin1"] for r in rows)), year_counts=dict(sorted(collections.Counter(r["date"][:4] for r in rows).items())),
               law_status_counts=dict(collections.Counter(r["law_status"] for r in rows)),
               record_type_counts=dict(collections.Counter(x["record_type"] for x in arts)), pdf_producer_counts=dict(collections.Counter(e.get("pdf_producer") for e in ex_all)),
               build_stats=dict(STATS), symbol_font_chars_mapped=dict(SYM_STATS), build_dropped={k: v for k, v in DROPS.items()}, sha256=files,
               excluded_image_only_pdfs=dict(note="Every NSTAR regulativ PDF was text-checked (non-whitespace characters per page < 200 = image-only). Image-only PDFs are listed here and not "
                                                  "included; no OCR was done.", count=len(excluded), likely_regulation_count=len(excluded), per_municipality=dict(per_m), items=excluded,
                                             broken_text_layer=dict(count=0, per_municipality={}, items=[])),
               heading_only_records=dict(count=len(HEADING_ONLY), note="Records whose text is only their heading: paradigm sections the kommune left empty, or bilag listed in the "
                                         "contents whose content is not in the published text. Flagged heading_only in the article metadata_json.", items=HEADING_ONLY),
               amendments=[dict(id="dk-mun-240-2916-art-bilag-2", note="Egedal husholdning bilag 2 is a Tillæg (amendment, in force 01-07-2024) with its own §1ff.; "
                                "kept as a schedule record, flagged amendment=true (article metadata) and extras.has_amendment (law row).")],
               currency_check=dict(checked=CHECKED, note="NSTAR shows the last regulativ each kommune reported, which is not always the one in force. The 26 rows approved "
                                   "before 2021 were checked by hand on the kommune websites (scrapers/collect_dk_kommune_pdfs.py, CURRENCY). Outcome per row is in the law's "
                                   "extras.currency_check; law_status is 'superseded' / 'unverified_current' where applicable. Rows approved 2021 or later were not individually checked.",
                                   outcomes=dict(collections.Counter(v["outcome"] for v in CURRENCY.values())),
                                   rows={f"dk-mun-{codes.get(norm_kommune(recs_in[(t_, d_)]['kommune']))}-{d_}": dict(outcome=v["outcome"], url=v.get("url") or v.get("superseded_by") or v.get("evidence_url"))
                                         for d_, v in CURRENCY.items() for t_ in ("husholdning", "erhverv") if (t_, d_) in recs_in}),
               id_rule=("dk-mun-<3-digit kommunekode>-<NSTAR regulativ database id> (schema.municipal_law_id); rows built from a kommune-website PDF (replacing a stale NSTAR row, or "
                        "for a regulativ NSTAR cannot serve) use dk-mun-<kode>-<husholdning|erhverv>-<ikrafttrædelse YYYY-MM-DD>, with the stale NSTAR id in extras.replaces_nstar. "
                        "Kommunekode from Danmarks Statistik (StatBank FOLK1A OMRÅDE)."),
               scope=dict(included=("Affaldsregulativer (husholdning + erhverv), one per type per kommune, all 98 kommuner (Christiansø is not a kommune and has none): the NSTAR "
                                    "text, or the kommune's own newer PDF where the NSTAR row was found superseded (see currency_check)."),
                          excluded={"lokalplaner": "Excluded: zoning plans under planloven (binding land-use plans for areas, not general regulations of conduct); distributed via Plandata.dk as plan documents.",
                                    "retsinformation": "Not a source for municipal regulations: Retsinformation / Lovtidende carry state law only (no kommunale regulativer or forskrifter).",
                                    "other_regulativer": "Spildevand (betalingsvedtægter / spildevandsplaner), jordflytning (regulativ / anvisningsregulativ for jordflytning), politivedtægter / ordensreglementer and vandløbsregulativer have no national bulk/API source; they live only on individual kommune (or forsyning) websites (vandløbsregulativer partly in Miljøportalen) and are not included. A per-kommune site crawler is needed for them.",
                                    "also_not_included": "Kommunale affaldsplaner and takst-/gebyrblade (plans and price lists, not regulations); råstofplaner are regional (5 regioner), not municipal."}),
               helper_modules={"collect_dk_nstar.py": "scrapers/collect_dk_nstar.py (NSTAR status page + PDF postbacks, kommunekoder); norm_kommune / BASE imported by build_dk_municipal.py",
                               "collect_dk_kommune_pdfs.py": "scrapers/collect_dk_kommune_pdfs.py (currency check table CURRENCY / DATES / EXTRA + kommune-website PDF fetcher -> dk_build/kommune_texts.jsonl.gz); imported by build_dk_municipal.py",
                               "schema.py": "scrapers/schema.py (pinned schemas, validate_municipal_table, municipal_law_id)"},
               sources=dict(texts="NSTAR, Energistyrelsen: https://nstar.ens.dk/PublicMunicipalityStatusPage.aspx (husholdning + erhverv lists; PDF per row). No robots.txt (404).",
                            kommune_websites="Born-digital regulativ PDFs from the kommuner's own websites (source_url per row) for rows where NSTAR is stale, and Læsø erhverv via a Wayback Machine replay of laesoe.dk. robots.txt respected, 1.5 s spacing.",
                            legal_basis="BEK nr. 938 af 2022 (affaldsaktørbekendtgørelsen) § 3, stk. 4: a regulativ is valid only once published in NSTAR.",
                            codes="Danmarks Statistik StatBank API https://api.statbank.dk/v1/tableinfo/FOLK1A (OMRÅDE values; open data)"))
    json.dump(man, open(f"{OUT}/MANIFEST.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(dict(laws=len(rows), articles=len(arts), excluded=len(excluded), stats=dict(STATS), drops={k: len(v) for k, v in DROPS.items()}), ensure_ascii=False))
if __name__ == "__main__":
    main(*(sys.argv[1:3]))
