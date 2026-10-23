#!/usr/bin/env python3
"""Build the Greek municipal regulatory-acts corpus (Diavgeia) into OUT (MUNICIPAL_HANDOFF layout).
Usage: build_gr_municipal.py BUILD OUT     (BUILD holds munis.json, discovery.jsonl, candidates.jsonl, fetch_log.jsonl, pdf/)"""
import unicodedata, json, sys, os, re, hashlib, datetime, shutil, collections, subprocess, tempfile
import pyarrow as pa, pyarrow.parquet as pq
sys.path.insert(0, os.environ.get("LEGAL_SCRAPERS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema import MUNICIPAL_LAWS_SCHEMA, RAW_ARTICLES_SCHEMA, validate_municipal_table, municipal_law_id
import gr_fixes as G, gr_fonts as GF

HELPERS = ("schema.py",)
COLLECTORS = ("gr_common.py", "gr_fixes.py", "gr_fonts.py", "collect_gr_diavgeia.py", "build_gr_municipal.py")
LIC = ("Greek municipal regulatory acts are official texts excluded from copyright protection (Law 2121/1993, art. 2(5)); "
       "published as open public data on Diavgeia (Law 4727/2020, art. 76 ff.; formerly Law 3861/2010) and reusable under Law 4305/2014 (open data).")
STATS = collections.Counter(); DROPPED = []; WHOLE_WITH_HEADINGS = []; HIDDEN_RUNS = []; FOLDED = []
TEXT_DROPS = []; RECOVERED = []; COMMITTEE = []; NONREG = []; NEAR_FOLDED = []; NEAR_SIBLINGS = []
# verify round 1: rows the Verifier confirmed as not regulatory (by ADA, transliterated) and the wrong file
NON_REGULATORY = {"7zpewj2-cy4": "replaces a committee member", "wns3w6m-oy2": "grant of the use of a space", "cebgw6m-nik": "grant of the use of a space",
                  "66diw0o-703": "sets the site of one market"}
WRONG_FILE = {"6993wjy-0l1": "subject is the 2019 advertising-fee regulation; the PDF is finance-committee decision 748/2018 on common-space fees (0 mentions of διαφήμιση)"}
# reverify: committee decisions that are regulatory acts the committee adopts under its own powers (not recommendations to the council)
COMMITTEE_OWN = {"ΩΔ6ΔΩΕΩ-Π9Ν": "committee standing orders adopted by the committee", "9ΣΡ7ΩΕΡ-ΣΗ8": "committee standing orders adopted by the committee",
                 "659ΑΩΛΚ-Ξ3Τ": "committee standing orders adopted by the committee", "Β430Ω1Ρ-ΨΟΛ": "committee standing orders adopted by the committee",
                 "ΨΘΞΜΩΞΥ-96Χ": "cemetery-fee regulation adopted by the committee (ορθή επανάληψη: 'Εγκρίνει' replaces 'Εισηγείται στο ΔΣ'; art. 72 par. 1 ιθ N. 3852/2010)",
                 "69ΖΒΩΞΥ-5Δ8": "cemetery-fee regulation adopted by the committee (art. 72 par. 1 ιθ N. 3852/2010)"}
COMMITTEE_BORDERLINE = {"9Ω1ΡΩΡ5-ΙΒ8": "Επιτροπή Ποιότητας Ζωής regulation of the Christmas market: borderline (committee act; kept and flagged)",
                        "7ΨΧΞΩΡ5-08Ω": "Επιτροπή Ποιότητας Ζωής regulation of the Christmas market: borderline (committee act; kept and flagged)"}
MAX_BROKEN_SHARE = 0.10
MAX_RESIDUE, MAX_RESIDUE_RATE = 50, 30.0   # broken-font residue tokens left after a decode (count, per 10k Greek words)

def pdftext(path):
    """pdftotext output, cached next to the PDF ('<BUILD>/txt/<ADA>.txt', keyed on the PDF's sha256) so rebuilds do not re-extract."""
    data = open(path, "rb").read(); h = hashlib.sha256(data).hexdigest()[:16]
    cd = os.path.join(os.path.dirname(os.path.dirname(path)), "txt"); cf = os.path.join(cd, os.path.basename(path)[:-4] + f".{h}.txt")
    if os.path.exists(cf): return open(cf, encoding="utf-8").read()
    try: out = subprocess.run(["pdftotext", "-enc", "UTF-8", path, "-"], capture_output=True, timeout=180).stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired: return ""
    try: os.makedirs(cd, exist_ok=True); open(cf, "w", encoding="utf-8").write(out)
    except OSError: pass
    return out

def fetch_failures(B, flog, cands, rows):
    """the failed downloads with the retry's findings (retry45.json: Diavgeia status / revocation note / replacement ADA)"""
    rt = {}
    if os.path.exists(f"{B}/retry45.json"):
        rt = {x["ada"]: x for x in json.load(open(f"{B}/retry45.json"))["results"]}
    norm = lambda a: a.replace("0", "Ο")   # revocation notes sometimes type digit 0 for Greek Ο ('ΨΟ1ΘΩΞ2-506' = ΨΟ1ΘΩΞ2-5Ο6)
    cand = {norm(a): a for a in cands}; inrows = {norm(json.loads(r["metadata_json"])["extras"]["ada"]) for r in rows}
    alts = set()
    for r in rows:
        for a in json.loads(r["metadata_json"])["extras"].get("alt_adas", []): alts.add(norm(a))
    out = []
    for a, r in flog.items():
        if r.get("ok"): continue
        x = rt.get(a, {}); rep = sorted(set(x.get("replacement") or []))
        out.append(dict(ada=a, year=x.get("year"), error=(r.get("error") or "")[:160], diavgeia_status=x.get("status"),
                        revocation_note=(x.get("revocation_note") or "").split(" | ")[0] or None,
                        replacement=[cand.get(norm(p), p) for p in rep],
                        replacement_in_corpus=[norm(p) in inrows or norm(p) in alts for p in rep],
                        retry=("revoked: no document" if x.get("status") == "REVOKED" else
                               ("redirects to http://static.old.diavgeia.gov.gr/doc/... (host unreachable; its robots.txt cannot be read)" if x.get("redirect") else None))))
    return out

def ms2date(ms): return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone(datetime.timedelta(hours=3))).date().isoformat() if ms else None

def main(B, out):
    munis = {m["kal"]: m for m in json.load(open(f"{B}/munis.json"))}
    cands = {json.loads(l)["ada"]: json.loads(l) for l in open(f"{B}/candidates.jsonl")}
    flog = {}
    for l in open(f"{B}/fetch_log.jsonl"):
        r = json.loads(l); flog[r["ada"]] = r
    STATS["candidates"] = len(cands); STATS["fetch_attempted"] = len(flog)
    STATS["fetch_failed"] = sum(1 for r in flog.values() if not r.get("ok"))
    # pass 0: text layers; the lexicon for the broken-font repair comes from the texts without any broken-font signal
    raws, cleaned = {}, {}
    for ada, r in flog.items():
        if not r.get("ok"): continue
        fn = f"{B}/pdf/{ada}.pdf"
        if not open(fn, "rb").read(5).startswith(b"%PDF"): continue
        raws[ada] = pdftext(fn); cleaned[ada] = G.clean_text(raws[ada], ada)
    lex = GF.build_lexicon(t for a_, t in cleaned.items() if G.text_quality(raws[a_])[0] and GF.clean_signal(t))
    D = GF.Decoder(lex); STATS["lexicon_words"] = len(lex)
    docs = []
    for ada, r in flog.items():
        if not r.get("ok"): continue
        x = cands[ada]; nat = G.ada_ascii(ada)
        if ada not in raws: STATS["excluded_not_pdf"] += 1; TEXT_DROPS.append(dict(ada=ada, reason="not a PDF")); continue
        raw = raws[ada]
        ok, why = G.text_quality(raw)
        if not ok and why not in ("bad_text_layer_broken_font_map", "bad_text_layer_no_greek_words"):
            STATS["excluded_" + why] += 1; TEXT_DROPS.append(dict(ada=ada, reason=why)); continue
        # broken-font lines: decoded with the font tables (gr_fonts.py) or removed; the act is kept when <= 10% of its text is removed
        text, st = GF.repair_text(D, cleaned[ada])
        text, n_ = GF.fix_arkro(text); STATS["arkro_to_arthro"] += n_
        share = st.get("chars_removed", 0) / max(1, len(cleaned[ada]))
        if share > MAX_BROKEN_SHARE or not G.text_quality(text)[0]:
            k = "excluded_broken_font_unrecoverable" if st.get("hard_signal") or not ok else "excluded_unreadable_lines"
            STATS[k] += 1; TEXT_DROPS.append(dict(ada=ada, reason=k[9:], removed_share=round(share, 3), first_check=why)); continue
        rn, rr, rby = GF.residue(text)
        if st.get("lines_decoded") and (rn >= MAX_RESIDUE or (rr > MAX_RESIDUE_RATE and rn >= 10)):
            STATS["excluded_broken_font_residue"] += 1
            TEXT_DROPS.append(dict(ada=ada, reason="broken_font_residue", residue=rn, residue_per_10k=rr, residue_by_kind=rby)); continue
        stamps = G.stamp_adas(raw)
        ex = {"ada": ada, "decision_type": x.get("decisionTypeId"), "protocol_number": x.get("protocolNumber"),
              "diavgeia_status": x.get("status"), "version_id": x.get("versionId"), "subject_class": x.get("_class"),
              "decision_page": f"https://diavgeia.gov.gr/decision/view/{ada}", "diavgeia_organization_uid": x.get("organizationId"),
              "unit_ids": x.get("unitIds"), "signer_ids": x.get("signerIds"), "thematic_categories": x.get("thematicCategoryIds"),
              "issue_date": ms2date(x.get("issueDate")), "publish_timestamp_utc": datetime.datetime.fromtimestamp(x["publishTimestamp"] / 1000, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if x.get("publishTimestamp") else None}
        if st.get("lines_decoded") or st.get("lines_removed"):
            ex["broken_font_repair"] = {k: v for k, v in st.items() if k != "hard_signal"}
            STATS["acts_with_broken_font_lines_decoded"] += bool(st.get("lines_decoded")); STATS["acts_with_broken_font_lines_removed"] += bool(st.get("lines_removed"))
            STATS["broken_font_lines_decoded"] += st.get("lines_decoded", 0); STATS["broken_font_lines_removed"] += st.get("lines_removed", 0)
            for k_ in ("lone_e_to_eta", "final_op_to_ou", "kappa_to_theta", "words_overridden_main_table"): STATS["broken_font_" + k_] += st.get(k_, 0)
            STATS["broken_font_chars_removed"] += st.get("chars_removed", 0)
        if not ok: RECOVERED.append(dict(ada=ada, first_check=why, removed_share=round(share, 4), lines_decoded=st.get("lines_decoded", 0), lines_removed=st.get("lines_removed", 0))); STATS["recovered_broken_font_acts"] += 1
        efv = x.get("extraFieldValues") or {}
        for k in ("fek", "kanonistikipraxitype", "relatedDecisions", "documentType", "thematikiEnotita"):
            if efv.get(k): ex[k] = efv[k]
        if x.get("attachments"): ex["diavgeia_attachments_not_fetched"] = len(x["attachments"]); STATS["acts_with_attachments_not_fetched"] += 1
        if nat in WRONG_FILE:
            STATS["excluded_wrong_file_verifier"] += 1; DROPPED.append(dict(ada=ada, stamps=sorted(stamps), reason=WRONG_FILE[nat])); continue
        # own-file verification: every Diavgeia PDF is stamped 'ΑΔΑ: <ada>' on each page
        if stamps and not any(G.same_ada(s, ada) for s in stamps):
            STATS["excluded_wrong_file_other_ada_stamp"] += 1
            DROPPED.append(dict(ada=ada, stamps=sorted(stamps), reason="document stamped with another ADA")); continue
        if stamps: ex["own_file_check"] = "ada_stamp"
        else:
            sw = [w for w in re.findall(r"\w{5,}", G.fold(x["subject"]))][:15]
            ft = G.fold(text); hit = sum(1 for w in sw if w in ft) / max(1, len(sw))
            if hit < 0.6:
                STATS["excluded_own_file_unverified"] += 1
                DROPPED.append(dict(ada=ada, stamps=[], reason=f"no ADA stamp and subject words not in text ({hit:.2f})")); continue
            ex["own_file_check"] = f"no_ada_stamp; subject words in text {hit:.2f}"; STATS["own_file_by_subject_words"] += 1
        if len(re.sub(r"\s", "", text)) < 80: STATS["excluded_too_short"] += 1; TEXT_DROPS.append(dict(ada=ada, reason="too short")); continue
        title = G.fix_mixed_scripts(G.fix_latin_lookalikes(re.sub(r"\s+", " ", unicodedata.normalize("NFKC", G.map_c1(x["subject"])).replace("\u2206", "Δ")).strip().strip("«»\"").strip()))
        title = G.fix_combining(G.fix_spacing_accent(title)).strip()
        title = title[0].upper() + title[1:]
        # issuing organ: only council acts are adopted regulations (committee decisions recommend them to the council)
        org, rec = G.issuing_organ(text)
        ex["issuing_organ"] = org or "unknown"
        if nat in NON_REGULATORY:
            STATS["excluded_not_regulatory_verifier"] += 1; NONREG.append(dict(ada=ada, reason=NON_REGULATORY[nat])); continue
        if ada in COMMITTEE_OWN:
            ex["committee_own_competence"] = COMMITTEE_OWN[ada]; STATS["kept_committee_own_competence"] += 1
        elif ada in COMMITTEE_BORDERLINE:
            ex["committee_own_competence"] = COMMITTEE_BORDERLINE[ada]; ex["flag_borderline_committee_act"] = True; STATS["kept_committee_borderline_flagged"] += 1
        elif org and org != "council":
            STATS["excluded_committee_decision"] += 1; COMMITTEE.append(dict(ada=ada, organ=org, recommends_to_council=rec, title=title[:160])); continue
        m = munis[x["_kal"]]
        docs.append(dict(ada=ada, native=nat, kal=x["_kal"], muni=m, title=title, text=text, ex=ex,
                         source_url=r["url"], retrieved_at=r["retrieved_at"], issue=ex["issue_date"]))
    STATS["docs_with_text"] = len(docs)
    # identical text under different ADAs (re-posts / ορθή επανάληψη / the same act posted twice): keep the latest posting
    # (corrections supersede), record the others in extras.alt_urls / alt_adas. Gate: no identical texts remain.
    tkey = lambda d: re.sub(r"\s+", " ", d["text"]).strip().lower()
    byt = collections.defaultdict(list)
    for d in docs: byt[tkey(d)].append(d)
    final = []
    for g in byt.values():
        g.sort(key=lambda d: (d["ex"].get("publish_timestamp_utc") or "", d["ada"]), reverse=True)
        k = g[0]
        for o in g[1:]:
            k["ex"].setdefault("alt_urls", []).append(o["source_url"]); k["ex"].setdefault("alt_adas", []).append(o["ada"])
            STATS["folded_identical_text_other_ada"] += 1; FOLDED.append(dict(kept=k["ada"], folded=o["ada"], same_municipality=o["kal"] == k["kal"]))
        final.append(k)
    dupe = [k for k, v in collections.Counter(tkey(d) for d in final).items() if v > 1]
    assert not dupe, ("identical text across acts", len(dupe))
    # near-duplicates (5-word shingle Jaccard within a municipality): the same act posted twice with only the stamp, the
    # signature, a vote formula or a correction differing. Folded (latest posting kept) when J >= 0.9 and the postings are the
    # same act (same protocol number and year, or 'ορθή επανάληψη'), or J >= 0.97; other pairs >= 0.9 are distinct sibling acts.
    def sh(t):
        w = re.findall(r"\w+", G.fold(t)); return {" ".join(w[i:i + 5]) for i in range(max(1, len(w) - 4))}
    for d in final: d["_sh"] = sh(d["text"])
    def same_act(a_, b_):
        pa_, pb_ = (a_["ex"].get("protocol_number") or "").strip(), (b_["ex"].get("protocol_number") or "").strip()
        return (pa_ and pa_ == pb_ and (a_["issue"] or "")[:4] == (b_["issue"] or "")[:4]) or any(
            re.search(r"ορθη\s+επαναληψη", G.fold(z["title"] + " " + z["text"][:1500])) for z in (a_, b_))
    gone = set(); bym = collections.defaultdict(list)
    for d in final: bym[d["kal"]].append(d)
    for k_, g in bym.items():
        g.sort(key=lambda d: (d["ex"].get("publish_timestamp_utc") or "", d["ada"]), reverse=True)
        for i, a_ in enumerate(g):
            if a_["ada"] in gone: continue
            for b_ in g[i + 1:]:
                if b_["ada"] in gone: continue
                la, lb = len(a_["_sh"]), len(b_["_sh"])
                if min(la, lb) / max(la, lb, 1) < 0.9: continue
                j = len(a_["_sh"] & b_["_sh"]) / len(a_["_sh"] | b_["_sh"])
                if j < 0.9: continue
                if j >= 0.97 or same_act(a_, b_):
                    a_["ex"].setdefault("alt_urls", []).append(b_["source_url"]); a_["ex"].setdefault("alt_adas", []).append(b_["ada"])
                    gone.add(b_["ada"]); STATS["folded_near_duplicate"] += 1
                    NEAR_FOLDED.append(dict(kept=a_["ada"], folded=b_["ada"], jaccard=round(j, 3), same_protocol_year=bool(same_act(a_, b_))))
                else:
                    NEAR_SIBLINGS.append(dict(a=a_["ada"], b=b_["ada"], j=j, jaccard=round(j, 3), protocol=[a_["ex"].get("protocol_number"), b_["ex"].get("protocol_number")]))
    # the same act (same protocol number, year and title) posted twice where one posting is a subset of the other (the
    # decision without / with its annex) or one has a broken-font text layer: folded when >= 80% of the smaller posting's
    # shingles are in the other. Kept: the posting that needed no broken-font repair, then the longer one, then the latest.
    def tkey_(d): return re.sub(r"\W+", " ", G.fold(d["title"])).strip()
    for k_, g in bym.items():
        grp = collections.defaultdict(list)
        for d in g:
            pn = (d["ex"].get("protocol_number") or "").strip()
            if d["ada"] not in gone and pn: grp[(pn, (d["issue"] or "")[:4], tkey_(d))].append(d)
        for key_, ds in grp.items():
            if len(ds) < 2: continue
            ds.sort(key=lambda d: ("broken_font_repair" not in d["ex"], len(d["text"]), d["ex"].get("publish_timestamp_utc") or "", d["ada"]), reverse=True)
            a_ = ds[0]
            for b_ in ds[1:]:
                c_ = len(a_["_sh"] & b_["_sh"]) / max(1, min(len(a_["_sh"]), len(b_["_sh"])))
                if c_ < 0.8: continue
                a_["ex"].setdefault("alt_urls", []).append(b_["source_url"]); a_["ex"].setdefault("alt_adas", []).append(b_["ada"])
                gone.add(b_["ada"]); STATS["folded_same_act_subset_or_broken_twin"] += 1
                j = len(a_["_sh"] & b_["_sh"]) / len(a_["_sh"] | b_["_sh"])
                NEAR_FOLDED.append(dict(kept=a_["ada"], folded=b_["ada"], jaccard=round(j, 3), containment=round(c_, 3), same_protocol_year=True,
                                        rule="same protocol, year and title; smaller posting contained >= 0.8",
                                        folded_had_broken_font="broken_font_repair" in b_["ex"], kept_longer=len(a_["text"]) >= len(b_["text"])))
    NEAR_SIBLINGS[:] = [x_ for x_ in NEAR_SIBLINGS if x_["a"] not in gone and x_["b"] not in gone]
    final = [d for d in final if d["ada"] not in gone]
    assert all(x_["j"] < 0.97 for x_ in NEAR_SIBLINGS)
    for x_ in NEAR_SIBLINGS: x_.pop("j")
    for d in final: d.pop("_sh", None)
    rows, arts, byid = [], [], set()
    for d in final:
        lid = municipal_law_id("gr", d["kal"], "ada-" + d["native"])
        assert lid not in byid, lid; byid.add(lid)
        ex = d["ex"]; t = d["text"]
        a, cov, chk = G.split_articles(t)
        if len(a) == 1:
            run = max(0 if chk.get("toc_blocks_skipped") else G.heading_run(t), G.loose_heading_run(t, skip_dense=True))   # TOC-only acts: the TOC lines are not headings   # loose_heading_run: independent of the splitter's regex
            if run >= 3 and G.amending_with_quoted_articles(d["title"], t):
                ex["whole_text_reason"] = "amending act: the 'Άρθρο N' headings are the amended regulation's articles quoted with their new wording"
                STATS["whole_text_amending_quoted_articles"] += 1
            elif run >= 3:
                WHOLE_WITH_HEADINGS.append((lid, run))
            elif chk.get("toc_blocks_skipped"):
                ex["whole_text_reason"] = "the 'Άρθρο N' lines are only a table of contents (titles without text); the body has no Άρθρο headings"
                STATS["whole_text_toc_only"] += 1
            elif chk.get("candidates"):
                ex["whole_text_reason"] = "fewer than 2 sequential line-start 'Άρθρο N' headings (single-clause decision or cross-references)"
                STATS["whole_text_with_isolated_heading"] += 1
            STATS["whole_text_records"] += 1
        else:
            assert not chk["hidden"], (lid, chk["hidden"])
            if chk["gaps"]: ex["numbering_gaps"] = chk["gaps"]; STATS["laws_with_numbering_gaps"] += 1
            if chk["blocks"] > 1:   # the regulation's text occurs more than once (minutes + attachment / repeated pages); labels bK.N
                ex["article_blocks"] = chk["blocks"]; STATS["laws_with_repeated_article_blocks"] += 1
            ex["article_marker"] = "Άρθρο"
            if chk.get("toc_entries_skipped"): ex["toc_heading_lines_skipped"] = chk["toc_entries_skipped"]; STATS["laws_with_unpunctuated_toc_skipped"] += 1
            # gate: no run of >= 3 increasing 'Άρθρο N' lines inside one record (independent loose matcher)
            for n_, _, body_ in a:
                inner = body_.split("\n", 1)[1] if (n_ != "0" and "\n" in body_) else (body_ if n_ == "0" else "")
                r_ = G.loose_heading_run(inner, skip_dense=True)   # an unpunctuated TOC (one heading per line, skipped as split points) is not hidden headings
                if r_ >= 3:
                    if G.amending_with_quoted_articles(d["title"], t):
                        ex.setdefault("records_with_quoted_amended_articles", []).append(n_); STATS["records_with_quoted_amended_articles"] += 1
                    else: HIDDEN_RUNS.append((lid, n_, r_))
        assert cov >= 0.95, (lid, cov)
        labels = [x[0] for x in a]; assert len(labels) == len(set(labels)), (lid, "dup labels")
        iss = d["issue"]
        tdate, tkind = G.text_effective(t, iss)
        if tdate and iss and (tdate < (datetime.date.fromisoformat(iss) - datetime.timedelta(days=400)).isoformat()):
            ex["text_effective_date_rejected"] = tdate; tdate = None          # quoted older act's date, not this act's
        if tdate: date, ex["date_kind"] = tdate, "effective_text_own_clause"
        else:
            date = iss; ex["date_kind"] = "decision_issue_date" + ("; effective on publication per text" if tkind == "on_publication" else "")
        ex["sha256_text"] = hashlib.sha256(t.encode()).hexdigest()
        ex["article_text_coverage"] = round(cov, 4)
        status = "repealed" if (ex.get("diavgeia_status") or "").upper() in ("REVOKED",) else ("not_yet_in_force" if date and date > datetime.date.today().isoformat() else "unknown")
        m = d["muni"]
        if len(a) == 1: a = [("0", "Πλήρες κείμενο", a[0][2])]
        for n, title, body in a:
            arts.append(dict(law_id=lid, id=f"{lid}-art-{n}", title=title, text=body, source_url=d["source_url"], document_number=d["ada"],
                             article_number=n, record_type="preamble" if n == "0" and len(a) > 1 else ("whole_text" if len(a) == 1 else "article"), metadata_json="{}"))
        rows.append(dict(id=lid, title=d["title"], text=t, source_url=d["source_url"], source_type="official_pdf",
                         jurisdiction=f"GR/{m['name']}", country="Greece", language="el", eli=None, date=date, date_issued=iss,
                         retrieved_at=d["retrieved_at"], license=LIC, law_status=status, identifier="ada-" + d["native"], official_identifier=d["ada"],
                         article_count=len(a), json_path=None, metadata_json=json.dumps({"extras": {**ex, "municipality_wikidata": m["qid"], "diavgeia_label": m["label"]}}, ensure_ascii=False),
                         jurisdiction_level="municipal", admin_level=8, country_iso="GR", admin1=m["admin1"], municipality=m["name"],
                         municipality_code=d["kal"], source_body=f"{m['name']} (Δημοτικό Συμβούλιο / όργανα του Δήμου)"))
    if WHOLE_WITH_HEADINGS: json.dump(WHOLE_WITH_HEADINGS, open(f"{B}/whole_with_headings.json", "w"), ensure_ascii=False)
    if HIDDEN_RUNS: json.dump(HIDDEN_RUNS, open(f"{B}/hidden_runs.json", "w"), ensure_ascii=False)
    assert not HIDDEN_RUNS, ("records containing >= 3 sequential headings", len(HIDDEN_RUNS), HIDDEN_RUNS[:5])
    assert not WHOLE_WITH_HEADINGS, ("whole-text records with >= 3 sequential headings", len(WHOLE_WITH_HEADINGS), WHOLE_WITH_HEADINGS[:5])
    for r in rows:   # encoding gates
        assert not re.search(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f\ufffd]", r["text"] + r["title"]), r["id"]
        assert unicodedata.normalize("NFKC", r["text"]) == r["text"] and unicodedata.normalize("NFKC", r["title"]) == r["title"], r["id"]
        assert "(cid:" not in r["text"], r["id"]
        assert not G.lookalike_tokens(r["text"]) and not G.lookalike_tokens(r["title"]), (r["id"], "Latin look-alike letters in Greek words", G.lookalike_tokens(r["text"])[:5])
        assert len(re.findall(r"[α-ωά-ώΑ-ΩΆ-Ώ]", r["text"])) > len(re.findall(r"[A-Za-z]", r["text"])), (r["id"], "not mainly Greek")
        assert not G.unreadable_greek_runs(r["text"]), (r["id"], "unreadable Greek character run")   # gate: broken-font text
        txt = r["text"] + "\n" + r["title"]; ada_ = json.loads(r["metadata_json"])["extras"]["ada"]
        assert "\u2206" not in txt and "\u03a2" not in txt, (r["id"], "U+2206 / U+03A2")
        assert not re.search(r"[\ue000-\uf8ff\x80-\x9f\u0301]", txt), (r["id"], "private-use / C1 / loose combining accent")
        assert not G.mixed_tokens(txt), (r["id"], "mixed-script tokens", G.mixed_tokens(txt)[:5])
        assert not re.search(r"[\u0400-\u04ff]", r["text"]) or not any(set(G._script(c) for c in w) >= {"c", "g"} for w in G.TOKEN.findall(r["text"])), (r["id"], "Cyrillic inside Greek")
        assert not re.search(r"signed by|Digitally|Reason:|INFORMATICS|DEVELOPMEN", r["text"]), (r["id"], "signature box residue")
        assert not G.own_stamp_lines(r["text"], ada_), (r["id"], "own ADA stamp")
        assert not G.loose_combining(txt), (r["id"], "combining mark without a Greek base letter", G.loose_combining(txt)[:5])
        assert not re.search(r"[\u031f\u0308\u0313]", txt), (r["id"], "U+031F / U+0308 / U+0313")
        assert not re.search(r"Άρκρ|άρκρ", txt), (r["id"], "broken-font 'Άρκρο'")
        assert GF.residue(r["text"])[0] < MAX_RESIDUE, (r["id"], "broken-font residue", GF.residue(r["text"]))
        assert re.fullmatch(r"gr-mun-\d{4}-ada-[a-z0-9-]+", r["id"]), r["id"]
    t = pa.Table.from_pylist(rows, schema=MUNICIPAL_LAWS_SCHEMA); errs = validate_municipal_table(t); assert not errs, errs
    at = pa.Table.from_pylist(arts, schema=RAW_ARTICLES_SCHEMA); assert at.schema.equals(RAW_ARTICLES_SCHEMA); assert len(set(at["id"].to_pylist())) == at.num_rows
    os.makedirs(f"{out}/data", exist_ok=True); os.makedirs(f"{out}/scrapers", exist_ok=True)
    pq.write_table(t, f"{out}/data/laws-00001.parquet", compression="zstd"); pq.write_table(at, f"{out}/data/articles-00001.parquet", compression="zstd")
    here = os.path.dirname(os.path.abspath(__file__))
    for f in COLLECTORS: shutil.copy(f"{here}/{f}", f"{out}/scrapers/{f}")
    for f in HELPERS: shutil.copy(os.path.join(here, "..", f), f"{out}/scrapers/{f}")
    disc = {}
    for l in open(f"{B}/discovery.jsonl"):
        k = json.loads(l)["_kal"]; disc.setdefault(k, collections.Counter())["discovered_subject_hits"] += 1
    for x in cands.values(): disc[x["_kal"]]["regulation_candidates"] += 1
    for ada, r in flog.items(): disc[cands[ada]["_kal"]]["fetched_ok" if r.get("ok") else "fetch_failed"] += 1
    for r in rows: disc[r["municipality_code"]]["laws_rows"] += 1
    disc = {f"{k} {munis[k]['name']}": dict(v) for k, v in disc.items()}
    json.dump(disc, open(f"{B}/discovery_stats.json", "w"), ensure_ascii=False, indent=1)
    files = {p: hashlib.sha256(open(f"{out}/{p}", "rb").read()).hexdigest() for p in ["data/laws-00001.parquet", "data/articles-00001.parquet"] + [f"scrapers/{f}" for f in sorted(os.listdir(f"{out}/scrapers"))]}
    ext = lambda r: json.loads(r["metadata_json"])["extras"]
    man = dict(slug="greece", country_iso="GR", collectors=["scrapers/collect_gr_diavgeia.py"],
               built_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), laws_rows=t.num_rows, articles_rows=at.num_rows,
               municipalities=dict(collections.Counter(r["municipality"] for r in rows)), municipalities_total_gr=332,
               law_status_counts=dict(collections.Counter(r["law_status"] for r in rows)),
               date_kind_counts=dict(collections.Counter(ext(r).get("date_kind") for r in rows)),
               decision_type_counts=dict(collections.Counter(ext(r).get("decision_type") for r in rows)),
               build_stats=dict(STATS), build_dropped_wrong_file=DROPPED, build_folded_identical_text=FOLDED, build_folded_near_duplicate=NEAR_FOLDED, near_duplicate_siblings_kept=NEAR_SIBLINGS, build_dropped_text_layer=TEXT_DROPS, build_recovered_broken_font=RECOVERED, build_dropped_committee_decisions=COMMITTEE, kept_committee_acts_own_competence=[dict(ada=k, reason=v, flagged_borderline=k in COMMITTEE_BORDERLINE) for k, v in {**COMMITTEE_OWN, **COMMITTEE_BORDERLINE}.items()], build_dropped_not_regulatory=NONREG, fetch_failures=fetch_failures(B, flog, cands, rows), discovery=disc, sha256=files,
               id_rule="gr-mun-<Kallikratis code>-ada-<ADA transliterated 1:1 Greek capital->Latin letter (ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ -> abgdezhuiklmnjoprstyfxcw)>; original ADA in official_identifier",
               helper_modules={"schema.py": "legal_scrapers/schema.py (MUNICIPAL_LAWS_SCHEMA, RAW_ARTICLES_SCHEMA, validate_municipal_table, municipal_law_id); imported by build_gr_municipal.py",
                               "gr_common.py": "scrapers/gr_common.py (polite session: robots.txt, 1 req/s, disk cache); imported by collect_gr_diavgeia.py",
                               "gr_fonts.py": "scrapers/gr_fonts.py (broken Greek font tables A-E, lexicon decoder, broken-line detection); imported by build_gr_municipal.py",
                               "gr_fixes.py": "scrapers/gr_fixes.py (subject classifier, ADA transliteration, text clean-up/quality checks, Άρθρο splitter, dates); imported by collect_gr_diavgeia.py and build_gr_municipal.py",
                               "third_party": ["requests", "pyarrow", "poppler-utils (pdftotext)"]},
               sources=["Diavgeia open-data API (https://diavgeia.gov.gr/opendata): search/advanced.json for discovery, decisions/{ADA}/document for the signed PDF",
                        "Kallikratis municipality codes: YPEN WFS layer WFD_geodata_50K:kallikratikoi_dimoi (kalcode)", "Wikidata (population ranking, QIDs)"])
    json.dump(man, open(f"{out}/MANIFEST.json", "w"), indent=1, ensure_ascii=False)
    print(json.dumps({k: man[k] for k in ("laws_rows", "articles_rows", "municipalities", "law_status_counts", "date_kind_counts", "build_stats")}, ensure_ascii=False))

if __name__ == "__main__": main(sys.argv[1], sys.argv[2])
