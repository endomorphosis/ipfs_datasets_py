#!/usr/bin/env python3
"""Build OCR (tesseract ell+eng) rows for the broken-font Diavgeia PDFs and merge them into greece_municipal (same row rules as build_gr_municipal.py).
Usage: build_ocr_rows.py  -> writes gr_ocr_state/new_laws.parquet, new_articles.parquet, build_report.json (no pack change)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))

# Prefer in-package Greek municipal helpers (hub_integrated/legal_scrapers/municipal).
_MUNI_HELPERS = Path(__file__).resolve().parents[4] / "legal_scrapers" / "municipal"
if _MUNI_HELPERS.is_dir():
    import sys as _sys
    _sys.path.insert(0, str(_MUNI_HELPERS))
_COLLECTORS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors")))
import json, os, re, sys, hashlib, datetime, unicodedata, collections
import pyarrow as pa, pyarrow.parquet as pq, pandas as pd
ROOT = (str(_CORPORA) + "/municipal"); PK = f"{ROOT}/greece_municipal"; ST = f"{ROOT}/gr_ocr_state"
from schema import MUNICIPAL_LAWS_SCHEMA, RAW_ARTICLES_SCHEMA, validate_municipal_table, municipal_law_id
import gr_fixes as G
LIC = pd.read_parquet(f"{PK}/data/laws.parquet", columns=["license"]).license.iloc[0]
old = pd.read_parquet(f"{PK}/data/laws.parquet")
muni = {}
for _, r in old.iterrows():
    if r.municipality_code not in muni:
        e = json.loads(r.metadata_json)["extras"]
        muni[r.municipality_code] = dict(name=r.municipality, admin1=r.admin1, qid=e["municipality_wikidata"], label=e["diavgeia_label"])
items = json.load(open(f"{ROOT}/ocr_candidates.json"))["packs"]["greece_municipal"]["broken_text_layer"]["items"]
flog = {}
for l in open(f"{ST}/fetch_log.jsonl"):
    r = json.loads(l)
    if r.get("ok") and not r.get("skipped"): flog[r["ada"]] = r
olog = {json.loads(l)["ada"]: json.loads(l) for l in open(f"{ST}/ocr_log.jsonl")}
ms2date = lambda ms: datetime.datetime.fromtimestamp(ms/1000, datetime.timezone(datetime.timedelta(hours=3))).date().isoformat() if ms else None
rows, arts, drops, fails = [], [], [], []
def drop(ada, why, **k): drops.append(dict(ada=ada, reason=why, **k))
for it in items:
    ada = it["ada"]; kal = it["municipality_code"]
    if ada not in olog or not olog[ada].get("ok"): fails.append(dict(ada=ada, error=(olog.get(ada) or {}).get("error", "not OCRed"))); continue
    x = json.load(open(f"{ST}/meta/{ada}.json")); raw = open(f"{ST}/ocr/{ada}.txt", encoding="utf-8").read()
    nat = G.ada_ascii(ada)
    t = unicodedata.normalize("NFKC", raw)
    t = G.clean_text(t, ada); t = G.fix_latin_lookalikes(t); t = G.fix_combining(G.fix_spacing_accent(t))
    t = re.sub(r"[ \t]+", " ", t); t = re.sub(r"\n{3,}", "\n\n", t).strip()
    gw = len(re.findall(r"[α-ωά-ώΑ-ΩΆ-Ώ]{3,}", t)); lw = len(re.findall(r"[A-Za-z]{3,}", t))
    if len(re.sub(r"\s", "", t)) < 80 or gw < 30 or gw < 3 * lw: drop(ada, "ocr_text_too_short_or_not_greek", greek_words=gw, latin_words=lw); continue
    stamps = G.stamp_adas(raw)
    ex = {"ada": ada, "decision_type": x.get("decisionTypeId"), "protocol_number": x.get("protocolNumber"), "diavgeia_status": x.get("status"),
          "version_id": x.get("versionId"), "decision_page": f"https://diavgeia.gov.gr/decision/view/{ada}", "diavgeia_organization_uid": x.get("organizationId"),
          "unit_ids": x.get("unitIds"), "signer_ids": x.get("signerIds"), "thematic_categories": x.get("thematicCategoryIds"),
          "issue_date": ms2date(x.get("issueDate")),
          "publish_timestamp_utc": datetime.datetime.fromtimestamp(x["publishTimestamp"]/1000, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if x.get("publishTimestamp") else None,
          "ocr": True, "ocr_engine": "tesseract 5.5.0", "ocr_lang": "ell+eng", "ocr_dpi": 300, "ocr_psm": 3, "ocr_pages": olog[ada]["pages"],
          "text_source": "ocr of the signed PDF (text layer had an undecodable broken font map); OCR errors possible",
          "broken_font_reason": it["reason"]}
    efv = x.get("extraFieldValues") or {}
    for k in ("fek", "kanonistikipraxitype", "relatedDecisions", "documentType", "thematikiEnotita"):
        if efv.get(k): ex[k] = efv[k]
    if x.get("attachments"): ex["diavgeia_attachments_not_fetched"] = len(x["attachments"])
    # own-file check: OCR garbles the ADA stamp, so accept an exact/near stamp, else subject words + protocol number in the text
    sw = re.findall(r"\w{5,}", G.fold(x["subject"]))[:15]; ft = G.fold(t)
    hit = sum(1 for w in sw if w in ft) / max(1, len(sw))
    norm = lambda s: re.sub(r"[^0-9A-Za-zΑ-Ωα-ω]", "", s).upper()
    stamp_ok = any(G.same_ada(s, ada) for s in stamps) if stamps else False
    ada_near = any(norm(ada)[:5] == norm(s)[:5] for s in stamps) if stamps else False
    if stamps and not stamp_ok and not ada_near and hit < 0.6: drop(ada, "document stamped with another ADA", stamps=sorted(stamps)); continue
    if stamp_ok: ex["own_file_check"] = "ada_stamp"
    elif hit >= 0.6: ex["own_file_check"] = f"ocr: ADA stamp garbled; subject words in text {hit:.2f}"
    else: drop(ada, "own_file_unverified", subject_word_hit=round(hit, 2)); continue
    title = G.fix_mixed_scripts(G.fix_latin_lookalikes(re.sub(r"\s+", " ", unicodedata.normalize("NFKC", G.map_c1(x["subject"])).replace("\u2206", "Δ")).strip().strip("«»\"").strip()))
    title = G.fix_combining(G.fix_spacing_accent(title)).strip(); title = title[0].upper() + title[1:]
    org, rec = G.issuing_organ(t); ex["issuing_organ"] = org or "unknown"
    if org and org != "council": drop(ada, "committee_decision", organ=org, recommends_to_council=rec, title=title[:160]); continue
    # encoding / script gates on the OCR text (same as the build's)
    bad = []
    if re.search(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f\ufffd]", t + title): bad.append("control chars")
    if G.mixed_tokens(t + "\n" + title): bad.append(f"mixed-script tokens {G.mixed_tokens(t)[:5]}")
    if G.lookalike_tokens(t) or G.lookalike_tokens(title): bad.append("latin lookalikes")
    if G.loose_combining(t + title): bad.append("loose combining")
    if G.unreadable_greek_runs(t): bad.append("unreadable greek runs")
    if bad: drop(ada, "ocr_text_gate_failed", gates=bad); continue
    a, cov, chk = G.split_articles(t)
    if len(a) == 1:
        run = max(0 if chk.get("toc_blocks_skipped") else G.heading_run(t), G.loose_heading_run(t, skip_dense=True))
        if run >= 3 and not G.amending_with_quoted_articles(title, t): drop(ada, "whole_text_with_>=3_sequential_headings (OCR split failure)", run=run); continue
        if run >= 3: ex["whole_text_reason"] = "amending act: quoted articles"
    else:
        ex["article_marker"] = "Άρθρο"
        hid = [n for n, _, b in a if G.loose_heading_run(b.split("\n", 1)[1] if (n != "0" and "\n" in b) else (b if n == "0" else ""), skip_dense=True) >= 3 and not G.amending_with_quoted_articles(title, t)]
        if hid: drop(ada, "hidden_headings_inside_records", records=hid[:5]); continue
    if cov < 0.95: drop(ada, "article_coverage_below_0.95", coverage=round(cov, 3)); continue
    labels = [z[0] for z in a]
    if len(labels) != len(set(labels)): drop(ada, "duplicate_article_labels"); continue
    iss = ex["issue_date"]; tdate, tkind = G.text_effective(t, iss)
    if tdate and iss and tdate < (datetime.date.fromisoformat(iss) - datetime.timedelta(days=400)).isoformat(): ex["text_effective_date_rejected"] = tdate; tdate = None
    if tdate: date, ex["date_kind"] = tdate, "effective_text_own_clause"
    else: date = iss; ex["date_kind"] = "decision_issue_date" + ("; effective on publication per text" if tkind == "on_publication" else "")
    ex["sha256_text"] = hashlib.sha256(t.encode()).hexdigest(); ex["article_text_coverage"] = round(cov, 4)
    lid = municipal_law_id("gr", kal, "ada-" + nat)
    status = "repealed" if (ex["diavgeia_status"] or "").upper() == "REVOKED" else ("not_yet_in_force" if date and date > datetime.date.today().isoformat() else "unknown")
    m = muni[kal]
    if len(a) == 1: a = [("0", "Πλήρες κείμενο", a[0][2])]
    surl = flog[ada]["url"]
    for n, ti, body in a:
        arts.append(dict(law_id=lid, id=f"{lid}-art-{n}", title=ti, text=body, source_url=surl, document_number=ada, article_number=n,
                         record_type="preamble" if n == "0" and len(a) > 1 else ("whole_text" if len(a) == 1 else "article"), metadata_json="{}"))
    rows.append(dict(id=lid, title=title, text=t, source_url=surl, source_type="official_pdf", jurisdiction=f"GR/{m['name']}", country="Greece", language="el", eli=None,
                     date=date, date_issued=iss, retrieved_at=flog[ada]["retrieved_at"], license=LIC, law_status=status, identifier="ada-" + nat, official_identifier=ada,
                     article_count=len(a), json_path=None,
                     metadata_json=json.dumps({"extras": {**ex, "municipality_wikidata": m["qid"], "diavgeia_label": m["label"]}}, ensure_ascii=False),
                     jurisdiction_level="municipal", admin_level=8, country_iso="GR", admin1=m["admin1"], municipality=m["name"], municipality_code=kal,
                     source_body=f"{m['name']} (Δημοτικό Συμβούλιο / όργανα του Δήμου)"))
# near-duplicate guard vs existing pack rows (same municipality)
def sh(t):
    w = re.findall(r"\w+", G.fold(t)); return {" ".join(w[i:i+5]) for i in range(max(1, len(w)-4))}
oldsh = {}
for _, r in old.iterrows(): oldsh.setdefault(r.municipality_code, []).append((r.id, sh(r.text)))
keep, keepids = [], set()
for r in rows:
    s = sh(r["text"]); dup = None
    for oid, os_ in oldsh.get(r["municipality_code"], []):
        j = len(s & os_) / max(1, len(s | os_))
        if j >= 0.9: dup = (oid, round(j, 3)); break
    if r["id"] in set(old.id): dup = (r["id"], 1.0)
    if dup: drop(r["official_identifier"], "near_duplicate_of_existing_pack_row", existing=dup[0], jaccard=dup[1])
    else: keep.append(r); keepids.add(r["id"])
arts = [a for a in arts if a["law_id"] in keepids]
t = pa.Table.from_pylist(keep, schema=MUNICIPAL_LAWS_SCHEMA) if keep else None
at = pa.Table.from_pylist(arts, schema=RAW_ARTICLES_SCHEMA) if keep else None
errs = validate_municipal_table(t) if keep else []
if keep:
    pq.write_table(t, f"{ST}/new_laws.parquet", compression="zstd"); pq.write_table(at, f"{ST}/new_articles.parquet", compression="zstd")
rep = dict(items=len(items), ocr_ok=sum(1 for v in olog.values() if v.get("ok")), ocr_failed=fails, rows_new=len(keep), articles_new=len(arts), drops=drops,
           drop_reasons=dict(collections.Counter(d["reason"] for d in drops)), validate_new_only=errs,
           per_municipality=dict(collections.Counter(r["municipality"] for r in keep)))
json.dump(rep, open(f"{ST}/build_report.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in rep.items() if k != "drops"}, ensure_ascii=False, indent=1))
