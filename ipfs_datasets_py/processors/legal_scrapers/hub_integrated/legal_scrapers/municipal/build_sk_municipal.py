#!/usr/bin/env python3
"""Build the Slovak municipal VZN corpus from the collectors' JSONL (RAW/raw/*.jsonl) into OUT (MUNICIPAL_HANDOFF layout).
Usage: build_sk_municipal.py RAW OUT"""
import unicodedata, json, sys, os, re, hashlib, datetime, shutil, collections, glob
import pyarrow as pa, pyarrow.parquet as pq
sys.path.insert(0, os.environ.get("LEGAL_SCRAPERS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema import MUNICIPAL_LAWS_SCHEMA, RAW_ARTICLES_SCHEMA, validate_municipal_table, municipal_law_id
import sk_fixes as S

HELPERS = ("schema.py", "common_crawl_helper.py")
COLLECTORS = ("sk_common.py", "sk_fixes.py", "sk_ligature_fix.py", "collect_sk_bratislava.py", "collect_sk_kosice.py", "collect_sk_zoznamvzn.py", "collect_sk_wp.py",
              "collect_sk_trencin.py", "collect_sk_petrzalka.py", "collect_sk_cc_karlovaves.py", "sk_reextract.py", "build_sk_municipal.py")
LIC = "Slovak municipal generally binding regulations (VZN) are official documents excluded from copyright protection (Act 185/2015 Coll., § 5 (a)); texts as published by the municipality."
TODAY = datetime.date.today().isoformat()
# kraj (ISO 3166-2:SK) per obec code
KRAJ = {"582000": "SK-BL", "529460": "SK-BL", "529397": "SK-BL", "529320": "SK-BL", "506745": "SK-TA", "505820": "SK-TC", "500011": "SK-NI",
        "517402": "SK-ZI", "510998": "SK-ZI", "512036": "SK-ZI", "508438": "SK-BC", "524336": "SK-PV", "523381": "SK-PV", "599981": "SK-KI"}
BODY = {"582000": "Hlavné mesto SR Bratislava – mestské zastupiteľstvo", "599981": "Mesto Košice – mestské zastupiteľstvo"}
STATS = collections.Counter()
DROPPED = []
# publisher links another act's file (verified on the live page): dropped and listed in MANIFEST build_dropped_wrong_file
WRONG_FILE = {("523381", "vzn-07-2024"): "the only file on poprad.sk/vzn/260 is '05_1998_Dodatky_07-08_2014.pdf' (Dodatok č. 7/2014 + 8/2014 to VZN 05/1998)"}
GARBLED = re.compile(r"[a-zA-Záäčéíóôúýž](?:[‚ƒ†‡ˆ‰‹•][a-zA-Záäčéíóôúýž]|[‚ƒ†‡ˆ‰‹](?=[\s.,]))")
WHOLE_WITH_HEADINGS = []; HIDDEN_RUNS = []
# reviewed false positives (heading-like lines that are not headings); filled after the broad scan, see README
WHOLE_TEXT_REVIEWED = {}
# born-digital text layers that still print '§' as '8'/'5' in headings ('817' + title = § 17), found by the broad scan
OCR_SECTION_SIGN = {"sk-mun-523381-vzn-04-2021"}
# accepted by the Verifier (reverify3 'accepted_exemption'): amending act whose own 'čl.i.'/'Čl. II' wrap quoted Čl. 8, 9, 15 ...
KEEP_WHOLE = {"sk-mun-508438-vzn-5-2020"}
RECORD_REVIEWED = {"sk-mun-508438-vzn-4-2024": "roman-numbered parking-zone tables in the annex (I., III., IV., VI.: zone rows), not headings"}

def status_of(d):
    ex = d["extras"]; reg = ex.get("register_status")
    regs = " ".join(reg) if isinstance(reg, list) else str(reg or "")
    eff = d.get("date")
    vu = S.norm_date(ex.get("valid_until"))
    if ex.get("cancelled_by") or ex.get("register_repealed") or re.search(r"(?i)zru[sš]|cancel|archiv-zrusenych", regs) or (vu and vu < TODAY):
        return "repealed"
    if eff and eff > TODAY: return "not_yet_in_force"
    stated_valid = (d["municipality_code"] == "582000" and not ex.get("cancelled_by")) or re.search(r"(?i)valid|platn|účinn|ucinn|schválen", regs) \
                   or (d["municipality_code"] == "599981" and not ex.get("register_repealed"))
    stated_valid = stated_valid or (d["municipality_code"] == "529460" and not ex.get("register_repealed"))
    if stated_valid and eff: return "in_force"
    return "unknown"

def main(raw, out):
    docs = []
    for fn in sorted(glob.glob(f"{raw}/raw/*.jsonl")):
        docs += [json.loads(l) for l in open(fn)]
    STATS["raw_records"] = len(docs)
    keep = []
    for d in docs:
        d["title"] = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", d["title"])).strip()
        d["title"] = re.sub(r"\s+null$", "", re.sub(r"^(VZN\s+(?:č\.\s*)?\d+/\d{4})\s+(?:VZN\s+(?:č\.\s*)?)?\d+/\d{4}\b", r"\1", d["title"]))
        # ţ/Ţ (t-cedilla, not a Slovak letter) is how some PDF fonts map ž/Ž
        d["title"] = d["title"].replace("ţ", "ž").replace("Ţ", "Ž"); d["text"] = d["text"].replace("ţ", "ž").replace("Ţ", "Ž")
        d["text"] = unicodedata.normalize("NFKC", d["text"]).replace("\x0c", "\n").replace("\r\n", "\n").replace("\r", "\n")          # pdftotext page breaks, CR from old HTML
        d["text"] = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", d["text"])).strip()
        d["text"] = re.sub(r"(?m)^,[ \t]*(?=§[ \t]*\d)", "", d["text"])          # ', § 20' (stray comma before a heading)
        if d["native_id"].startswith("page-"):     # CMS page id only: take the act number from the title (same rule as collect_sk_zoznamvzn.py now uses)
            mn = re.search(r"(?:VZN|nariadenie(?:\s+mesta\s+\w+)?)\s+(?:č\.\s*)?(\d+[a-z]?/\d{4})", d["title"])
            if mn: d["extras"]["reg_number"] = mn.group(1); d["native_id"] = "vzn-" + mn.group(1).replace("/", "-")
        rn = d["extras"].get("reg_number")
        m8 = re.fullmatch(r"(\d+)/((?:19|20)\d{3})", rn or "")
        my = re.search(r"č\.\s*0*%s\s*/\s*((?:19|20)\d\d)(?!\d)" % m8.group(1), d["text"][:1500]) if m8 else None
        if my and my.group(1)[:3] == m8.group(2)[:3]:      # register typo '10/20145' -> the act's own number in its text, '10/2015'
            d["extras"]["register_number_typo"] = rn; rn = d["extras"]["reg_number"] = f"{m8.group(1)}/{my.group(1)}"
            d["native_id"] = f"vzn-{m8.group(1)}-{my.group(1)}"; STATS["register_number_typo_fixed"] += 1
        if d["municipality_code"] == "510998" and rn:      # ruzomberok.sk register numbers differ from the act's own number in its file
            m9 = re.search(r"(?i)nariadenie\s+(?:mesta\s+\w+\s+)?č\.\s*0*(\d+)\s*/\s*((?:19|20)\d\d)", d["text"][:600])
            if m9 and f"{m9.group(1)}/{m9.group(2)}" != re.sub(r"^0+", "", rn) and m9.group(2) == rn.split("/")[-1]:
                d["extras"]["register_number"] = rn; rn = d["extras"]["reg_number"] = f"{m9.group(1)}/{m9.group(2)}"
                d["native_id"] = f"vzn-{m9.group(1)}-{m9.group(2)}"; STATS["rk_number_from_text"] += 1
        if rn and re.fullmatch(r"\d+[a-z]?/(\d{4})/\1", rn): d["extras"]["reg_number"] = rn.rsplit("/", 1)[0]
        d["native_id"] = re.sub(r"^(vzn-\d+[a-z]?-(\d{4}))-\2$", r"\1", d["native_id"])
        # Petržalka-style register notes inside the link text ('Toto VZN je Z R U Š E N É a platí VZN č. 15/2015.', 'ÚPLNÉ ZNENIE VZN NÁJDETE TU.')
        note = re.search(r"(?i)\s*(?:Toto\s+)?VZN\s+(?:už\s+)?(?:je|bolo)?\s*(?:už\s+)?(?:Z\s?R\s?U\s?Š\s?E\s?N\s?É|zrušené|NIE JE PLATNÉ)[^\n]*$", d["title"])
        if note:
            d["extras"]["register_note"] = d["extras"].get("register_note") or note.group(0).strip(); d["extras"]["register_repealed"] = True
            d["title"] = d["title"][:note.start()].strip()
        m6 = re.match(r"Platí\s+VZN\s+č\.\s*\d+/\d{4}\s*\.?\s*", d["title"])
        if m6: d["extras"]["register_note"] = ((d["extras"].get("register_note") or "") + " " + m6.group(0)).strip(); d["title"] = d["title"][m6.end():]
        m7 = re.search(r"\s*Toto\s+VZN\s+(?:je|bolo)\s+N\s?O\s?V\s?E\s?L\s?I\s?Z\s?O\s?V\s?A\s?N\s?É[^\n]*$", d["title"])
        if m7: d["extras"]["register_note"] = m7.group(0).strip(); d["title"] = d["title"][:m7.start()].strip()     # amended, not repealed
        d["title"] = re.sub(r"(dopĺňa|mení|ruší)(VZN)", r"\1 \2", d["title"])
        d["title"] = re.sub(r"(?i)\s*(ÚPLNÉ ZNENIE VZN NÁJDETE TU\.?|Doplnené VZN[^.]*\.)\s*", " ", d["title"]).strip()
        m2 = re.search(r"\s*[–-]\s*zrušen[eé]\.?\s*$", d["title"])
        if m2: d["title"] = d["title"][:m2.start()].strip(); d["extras"]["register_repealed"] = True
        m4 = re.search(r"[.,]?\s*\b(?:Zrušen[éé]|Novelizovan[éé]|Ruší|Mení)\s+(?:VZN|všeobecne)[^\n]*$", d["title"]) if d["municipality_code"] == "506745" else None
        if m4:    # trnava.sk register notes appended to the title ('Zrušené VZN 356, novelizované VZN 301')
            d["extras"]["register_note"] = d["title"][m4.start():].strip(" .,"); d["title"] = d["title"][:m4.start()].strip()
            if re.match(r"(?i)zrušen", d["extras"]["register_note"]): d["extras"]["register_repealed"] = True
        m3 = re.search(r"\s*\(\s*(?:zrušené|zrušený)\s*\)", d["title"])
        m5 = re.search(r"\s*\(\s*(zrušená\s+[IVX]+\.\s*časť)\s*\)", d["title"])
        if m5: d["extras"]["register_note"] = m5.group(1); d["title"] = (d["title"][:m5.start()] + d["title"][m5.end():]).strip()
        if m3: d["title"] = re.sub(r"\s*\(\s*(?:zrušené|zrušený)\s*\)", "", d["title"]).strip(); d["extras"]["register_repealed"] = True
        d["title"] = re.sub(r"č\.\s*(\d+)\s*/\s*(\d{4})", r"č. \1/\2", d["title"])
        d["title"] = re.sub(r"^Všetky\s+(?=všeobecne)", "", d["title"])
        d["title"] = d["title"][0].upper() + d["title"][1:] if d["title"] else d["title"]
        if S.GENERIC_TITLE.match(d["title"]) or len(d["title"]) < 20 or re.match(r"(?i)znenie vzn \d|toto vzn (?:je|bolo)\b", d["title"]):
            sub = S.subject_from_text(d["text"])
            num = d["extras"].get("reg_number") or (re.search(r"\d+/\d{4}", d["title"]) or [None])[0]
            if sub:
                d["extras"]["original_link_title"] = d["title"]
                d["title"] = sub if re.match(r"(?i)všeobecne|vzn", sub) else (f"VZN č. {num} {sub}" if num else f"VZN {sub}")
        if (d["municipality_code"], d["native_id"]) in WRONG_FILE:
            STATS["excluded_wrong_file_text_of_other_act"] += 1
            DROPPED.append(dict(id=f"sk-mun-{d['municipality_code']}-{d['native_id']}", source_url=d["source_url"], text_is_act=None,
                                reason=WRONG_FILE[(d["municipality_code"], d["native_id"])])); continue
        why = S.exclusion(d)
        if why: STATS["excluded_" + why] += 1; continue
        if len(re.sub(r"\s", "", d["text"])) < 200: STATS["excluded_no_text_layer"] += 1; continue   # scanned PDF (no OCR) or empty file
        if re.search(r"[\x00-\x08\x0b\x0e-\x1f\ufffd]", d["text"] + d["title"]): d["text"] = re.sub(r"[\x00-\x08\x0b\x0e-\x1f\ufffd]", " ", d["text"])
        ex = d["extras"]
        pt = ex.pop("page_text", None)
        if pt:            # nitra.sk act page: 'Schválené/Účinné podľa stavu od 11.07.2020'
            m = re.search(r"Účinné podľa stavu od\s*(\d{2})\.(\d{2})\.(\d{4})", pt)
            if m and not ex.get("effective_from"): ex["effective_from"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        meta_eff = S.norm_date(ex.get("effective_from"))
        if ex.get("effective_from") and not meta_eff:        # register typo outside 1990..2030 ('0206-01-01'): kept only as rejected
            ex["register_date_rejected"] = ex.pop("effective_from")
        tdate, tkind = S.text_effective(d["text"])
        ry = re.search(r"/((?:19|20)\d\d)\b", ex.get("reg_number") or d["title"])
        if meta_eff and ry and meta_eff[:4] < ry.group(1) and tdate and tdate[:4] >= ry.group(1):
            ex["register_date_rejected"] = meta_eff; meta_eff = None        # register date predates the act itself (data-entry slip)
        # consolidated text (úplné znenie): its own date is the latest amendment's effective date (label 'účinné od …' or the text)
        cons = None
        if ex.get("is_consolidated"):
            ml = re.search(r"účinné od\s*" + S.DATE, ex.get("text_version") or "")
            cons = S.iso(*ml.groups()) if ml else (tdate if tkind == "text_own_clause" else None)
        if meta_eff and cons and cons > meta_eff:
            ex["original_effective_from"] = meta_eff; d["date"], ex["date_kind"] = cons, "effective_consolidated_version"
        elif meta_eff: d["date"], ex["date_kind"] = meta_eff, "effective_register"
        elif tdate: d["date"], ex["date_kind"] = tdate, "effective_" + tkind
        else:
            ap, po, ceff = S.text_posting(d["text"])
            if ap and not ex.get("approved"): ex["approved"] = ap; ex["approved_source"] = "text"
            if po and not ex.get("promulgated"): ex["promulgated"] = po; ex["promulgated_source"] = "text (Vyvesené dňa)"
            iss = S.norm_date(ex.get("promulgated")) or S.norm_date(ex.get("approved"))
            if ceff: d["date"], ex["date_kind"] = ceff, "effective_computed_posting_plus_days"
            elif iss: d["date"], ex["date_kind"] = iss, "promulgated" if S.norm_date(ex.get("promulgated")) else "approved"
            else:
                y = re.search(r"/((?:19|20)\d\d)\b", ex.get("reg_number") or d["title"])
                d["date"], ex["date_kind"] = (y.group(1), "year") if y else (None, None)
        if tdate and meta_eff and tdate != meta_eff: ex["text_effective_date"] = tdate
        d["date_issued"] = S.norm_date(ex.get("promulgated")) or S.norm_date(ex.get("approved"))
        if re.match(r"\d+/\d{4}\s", d["title"]):
            d["extras"]["original_link_title"] = d["title"]; d["title"] = "VZN č. " + d["title"]
        elif re.match(r"(?i)^(o|ktorým|ktorou)\s", d["title"]) and ex.get("reg_number"):
            d["extras"]["original_link_title"] = d["title"]; d["title"] = f"VZN č. {ex['reg_number']} {d['title']}"
        if S.source_ocr_layer(d["text"]): ex["text_layer"] = "publisher_ocr"; STATS["publisher_ocr_text_layer"] += 1
        if len(GARBLED.findall(d["text"])) >= 3:          # per-document subset-font encoding (no consistent map; no OCR) -> flagged
            ex["text_garbled_glyphs"] = len(GARBLED.findall(d["text"])); STATS["publisher_font_garbled_text_layer"] += 1
            if ex.get("text_layer") != "publisher_ocr": ex["text_layer"] = "publisher_font_garbled"
        ex["doc_type"], ex["act_kind"] = S.doc_type(d["title"])
        d["status"] = status_of(d)
        keep.append(d)
    # duplicates within a municipality: same native id -> fold only when same date AND (identical title OR word-Jaccard >= 0.8)
    wset = lambda x: set(re.findall(r"\w+", x["text"].lower()))
    byk = collections.defaultdict(list)
    for d in keep: byk[(d["municipality_code"], d["native_id"])].append(d)
    final = []
    for k, g in byk.items():
        g.sort(key=lambda x: -len(x["text"])); reps = []
        for d in g:
            hit = next((r for r in reps if (r.get("date") == d.get("date")) and (r["title"] == d["title"] or len(wset(r) & wset(d)) / max(1, len(wset(r) | wset(d))) >= 0.8)), None)
            if hit:
                hit["extras"].setdefault("alt_versions", []).append(dict(source_url=d["source_url"], title=d["title"], text=d["text"])); STATS["folded_same_version"] += 1
            else: reps.append(d)
        if len(reps) > 1:
            for i, d in enumerate(reps[1:], 1): d["native_id"] = f"{d['native_id']}-{hashlib.sha256(d['text'].encode()).hexdigest()[:8]}"
        final += reps
    # identical text under different acts = the publisher linked another act's file. Keep only the act whose own number is in the
    # text header; drop the others (counted, listed in MANIFEST build_dropped_wrong_file). Gate: no identical texts remain.
    def own_number_in_header(d):
        rn = d["extras"].get("reg_number") or ""
        m = re.fullmatch(r"0*(\d+)[a-z]?(?:/(\d{4}))?", rn)
        if not m: return False
        rx = r"(?i)č\.?\s*0*" + m.group(1) + (r"\s*/\s*" + m.group(2) if m.group(2) else r"(?![\d/])")
        return bool(re.search(rx, d["text"][:1200]))
    tkey = lambda d: re.sub(r"\s+", " ", d["text"]).strip().lower()
    byt = collections.defaultdict(list)
    for d in final: byt[tkey(d)].append(d)
    drop = set()
    for g in byt.values():
        if len({(x["municipality_code"], x["native_id"]) for x in g}) < 2: continue
        own = [x for x in g if own_number_in_header(x)]
        keepx = own[0] if len(own) == 1 else None
        for x in g:
            if x is not keepx:
                drop.add(id(x)); STATS["excluded_wrong_file_text_of_other_act"] += 1
                DROPPED.append(dict(id=f"sk-mun-{x['municipality_code']}-{x['native_id']}", source_url=x["source_url"],
                                    text_is_act=keepx["native_id"] if keepx else None, reason="file carries another act's text"))
    final = [d for d in final if id(d) not in drop]
    dupe = [k for k, v in collections.Counter(tkey(d) for d in final).items() if v > 1]
    assert not dupe, ("identical text across acts", len(dupe))
    rows, arts, byid = [], [], {}
    for d in final:
        lid = municipal_law_id("sk", d["municipality_code"], d["native_id"])
        assert lid not in byid, lid
        h = hashlib.sha256(d["text"].encode()).hexdigest()
        d["text"], nfix = S.normalize_ocr_headings(d["text"], d["extras"].get("text_layer") == "publisher_ocr" or lid in OCR_SECTION_SIGN, bb=d["municipality_code"] == "508438" or lid in OCR_SECTION_SIGN)
        if nfix: d["extras"]["ocr_heading_fixes"] = nfix; STATS["laws_with_ocr_heading_fixes"] += 1
        h = hashlib.sha256(d["text"].encode()).hexdigest()
        if lid in KEEP_WHOLE:     # reviewed amending act: its line-start headings are the quoted wording of the amended VZN
            a, cov, chk = [("1", "whole text", d["text"].strip())], 1.0, dict(marker=None, gaps=[], hidden=[])
        else: a, cov, chk = S.split_articles(d["text"])
        if chk.get("text"):        # repair pass edited heading lines: law.text gets the same edit so concat(articles) == law.text
            d["text"] = chk.pop("text"); h = hashlib.sha256(d["text"].encode()).hexdigest(); STATS["laws_split_repair_pass"] += 1
        if len(a) == 1:   # gate: a whole-text record must not contain >= 3 heading lines of one family in increasing order
            run, hl = S.heading_run(d["text"])
            quoted = re.search(r"(?i)sa mení (?:nasledovne|takto)|znie:|sa dopĺňa|sa vkladá|nové znenie|sa nahrádza|vypúšťa", d["text"])
            if run >= 3 and quoted and d["extras"].get("act_kind") == "amending":
                d["extras"]["whole_text_reason"] = "amending act: line-start headings are the quoted new wording of the amended VZN"
                STATS["whole_text_amending_quoted_headings"] += 1
            elif run >= 3 and lid in WHOLE_TEXT_REVIEWED:
                d["extras"]["whole_text_reason"] = WHOLE_TEXT_REVIEWED[lid]; STATS["whole_text_reviewed_false_positive"] += 1
            elif run >= 3: WHOLE_WITH_HEADINGS.append((lid, hl[:6]))
            elif len(hl) >= 3:
                d["extras"]["whole_text_reason"] = "heading-like lines are not one numbered sequence (cross-references / mixed markers)"
                STATS["whole_text_unsequenced_heading_lines"] += 1
        else:             # gate: no record (incl. Úvod) holds >= 3 sequential heading lines of one family
            for n_, _, body_ in a:
                inner = body_ if n_ == "0" else (body_.split("\n", 1)[1] if "\n" in body_ else "")
                r_, hl_ = S.heading_run(inner)
                if r_ >= 3 and S.is_toc_records(S._split(inner)[0]): continue      # a table of contents inside the record
                if r_ >= 3 and not (d["extras"].get("act_kind") == "amending"):
                    if lid in RECORD_REVIEWED: d["extras"]["record_heading_lines_reviewed"] = RECORD_REVIEWED[lid]
                    else: HIDDEN_RUNS.append((lid, n_, hl_[:6]))
        assert cov >= 0.95, (lid, cov)
        assert not chk["hidden"], (lid, chk["hidden"])                       # no record holds a skipped heading
        labels = [x[0] for x in a]; assert len(labels) == len(set(labels)), (lid, "dup labels")
        ex = d["extras"]; ex.update(article_marker=chk["marker"], article_text_coverage=round(cov, 4), sha256_text=h)
        if len(a) > 1:   # restarts of the numbering -> parts pK.N; another heading family inside a record -> <parent>.N
            if chk.get("parts", 1) > 1: ex["article_parts"] = chk["parts"]; STATS["laws_split_into_parts_pK.N"] += 1
            if chk.get("nested"): ex["nested_heading_blocks"] = chk["nested"]; STATS["laws_with_nested_records_parent.N"] += 1
            if chk.get("toc_records"): ex["toc_left_in_record"] = chk["toc_records"]; STATS["laws_with_toc_in_a_record"] += 1
        if chk.get("lenient"): ex["split_mode"] = "lenient_increasing_chain"; STATS["laws_split_lenient_chain"] += 1
        if chk["gaps"]:
            ex["numbering_gaps"] = chk["gaps"]; STATS["laws_with_numbering_gaps"] += 1
            present = [n for n in chk["gaps"] if any(c[1] == chk["marker"] and c[2] == n for c in S.all_candidates(d["text"]))]
            ex["numbering_gaps_absent_in_text"] = [n for n in chk["gaps"] if n not in present]
            if present: ex["numbering_gaps_out_of_order"] = present; STATS["gaps_heading_present_out_of_order"] += len(present)
            else: STATS["laws_gaps_all_absent_in_text"] += 1
        if len(a) == 1: STATS["whole_text_records"] += 1
        byid[lid] = d
        for n, title, body in a:
            arts.append(dict(law_id=lid, id=f"{lid}-art-{n}", title=title, text=body, source_url=d["source_url"], document_number=d["native_id"],
                             article_number=n, record_type="section", metadata_json="{}"))
        rows.append(dict(id=lid, title=d["title"], text=d["text"], source_url=d["source_url"],
                         source_type="official_pdf" if d["extras"].get("extraction") == "pdftotext" else "official_document",
                         jurisdiction=f"SK/{d['municipality']}", country="Slovakia", language="sk", eli=None, date=d.get("date"), date_issued=d.get("date_issued"),
                         retrieved_at=d["retrieved_at"], license=LIC, law_status=d["status"], identifier=d["native_id"], official_identifier=ex.get("reg_number"),
                         article_count=len(a), json_path=None, metadata_json=json.dumps({"extras": {**ex, "page_url": d.get("page_url")}}, ensure_ascii=False),
                         jurisdiction_level="municipal", admin_level=8, country_iso="SK", admin1=KRAJ[d["municipality_code"]], municipality=d["municipality"],
                         municipality_code=d["municipality_code"], source_body=BODY.get(d["municipality_code"], f"{d['municipality']} – obecné/mestské zastupiteľstvo")))
    if True:
        json.dump(WHOLE_WITH_HEADINGS, open("/tmp/sk_whole_with_headings.json", "w"), ensure_ascii=False, indent=0)
    json.dump(HIDDEN_RUNS, open("/tmp/sk_hidden_runs.json", "w"), ensure_ascii=False, indent=0)
    assert not HIDDEN_RUNS, ("records holding >= 3 sequential heading lines", len(HIDDEN_RUNS), HIDDEN_RUNS[:5])
    assert not WHOLE_WITH_HEADINGS, ("whole-text records with >= 3 heading lines", len(WHOLE_WITH_HEADINGS), WHOLE_WITH_HEADINGS[:5])
    for r in rows:
        for k in ("date", "date_issued"):     # sanity gate: dates are 1990..2030 (YYYY or YYYY-MM-DD)
            assert r[k] is None or (re.fullmatch(r"\d{4}(-\d\d-\d\d)?", r[k]) and "1990" <= r[k][:4] <= "2030"), (r["id"], k, r[k])
        assert "ţ" not in r["text"] + r["title"] and "Ţ" not in r["text"] + r["title"], r["id"]
        assert not re.search(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f\ufffd]", r["text"] + r["title"]), r["id"]
        assert unicodedata.normalize("NFKC", r["text"]) == r["text"] and unicodedata.normalize("NFKC", r["title"]) == r["title"], r["id"]
        assert not re.fullmatch(r"(?i)(vzn|všeobecne záväzné nariadenie|nariadenie|dokument|pdf|stiahnuť)[\s\d./č-]*", r["title"]), r["id"]
    t = pa.Table.from_pylist(rows, schema=MUNICIPAL_LAWS_SCHEMA); errs = validate_municipal_table(t); assert not errs, errs
    at = pa.Table.from_pylist(arts, schema=RAW_ARTICLES_SCHEMA); assert len(set(at["id"].to_pylist())) == at.num_rows
    os.makedirs(f"{out}/data", exist_ok=True); os.makedirs(f"{out}/scrapers", exist_ok=True)
    pq.write_table(t, f"{out}/data/laws-00001.parquet", compression="zstd"); pq.write_table(at, f"{out}/data/articles-00001.parquet", compression="zstd")
    here = os.path.dirname(os.path.abspath(__file__))
    for f in COLLECTORS: shutil.copy(f"{here}/{f}", f"{out}/scrapers/{f}")
    for f in HELPERS: shutil.copy(os.path.join(here, "..", f), f"{out}/scrapers/{f}")
    disc = {}
    for fn in sorted(glob.glob(f"{raw}/raw/*.jsonl.stats.json")):
        s = json.load(open(fn)); disc[os.path.basename(fn).split(".")[0]] = dict(discovered=s.get("discovered"), fetched=s.get("records"), errors=len(s.get("errors", {})), skipped=s.get("skipped") or s.get("skipped_proposals"))
    files = {p: hashlib.sha256(open(f"{out}/{p}", "rb").read()).hexdigest() for p in ["data/laws-00001.parquet", "data/articles-00001.parquet"] + [f"scrapers/{f}" for f in sorted(os.listdir(f"{out}/scrapers"))]}
    man = dict(slug="slovakia", country_iso="SK", collectors=[f"scrapers/{c}" for c in COLLECTORS if c.startswith("collect")],
               built_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), laws_rows=t.num_rows, articles_rows=at.num_rows,
               municipalities=dict(collections.Counter(r["municipality"] for r in rows)), municipalities_total_sk=2890,
               law_status_counts=dict(collections.Counter(r["law_status"] for r in rows)),
               date_kind_counts=dict(collections.Counter(json.loads(r["metadata_json"])["extras"].get("date_kind") for r in rows)),
               doc_types=dict(collections.Counter(json.loads(r["metadata_json"])["extras"]["doc_type"] for r in rows)),
               build_stats=dict(STATS), build_dropped_wrong_file=DROPPED, discovery=disc, sha256=files,
               helper_modules={"schema.py": "legal_scrapers/schema.py (MUNICIPAL_LAWS_SCHEMA, RAW_ARTICLES_SCHEMA, validate_municipal_table, municipal_law_id); imported by build_sk_municipal.py",
                               "common_crawl_helper.py": "legal_scrapers/common_crawl_helper.py (Common Crawl CDX lookup + ranged WARC reads); imported by collect_sk_cc_karlovaves.py",
                               "sk_common.py": "scrapers/sk_common.py (polite session with robots.txt, cache, pdftotext/docx/html extraction, LibreOffice for RTF/.doc); imported by every collect_sk_*.py and sk_reextract.py",
                               "sk_fixes.py": "scrapers/sk_fixes.py (exclusions, dates, status, article splitter); imported by build_sk_municipal.py",
                               "sk_ligature_fix.py": "scrapers/sk_ligature_fix.py (restores fi/fl ligatures pdftotext dropped, using pdfminer.six on the same PDF; run once on Košice vzn-51 raw text)",
                               "third_party": ["requests", "pyarrow", "poppler-utils (pdftotext)", "pdfminer.six (sk_ligature_fix.py only)", "LibreOffice (soffice --headless, RTF/.doc to text)"]},
               sources=["official municipal websites and their public CMS APIs (bratislava.sk Next.js data, WordPress wp-json, register pages)", "Common Crawl (CDX + ranged WARC reads): Bratislava-Karlova Ves text (live site times out); coverage check for Prešov, Martin, Ružinov, zverejnenie.esluzbykosice.sk"])
    json.dump(man, open(f"{out}/MANIFEST.json", "w"), indent=1, ensure_ascii=False)
    print(json.dumps({k: man[k] for k in ("laws_rows", "articles_rows", "municipalities", "law_status_counts", "date_kind_counts", "build_stats")}, ensure_ascii=False))

if __name__ == "__main__": main(sys.argv[1], sys.argv[2])
