#!/usr/bin/env python3
"""Stage ZA provincial pack1 (batch 1) for the NEW repo endomorphosis/ipfs_south_africa_provincial_laws:
data/laws.parquet + data/articles.parquet (columns of the national ZA pack endomorphosis/ipfs_southafrica_laws @fdf0f845,
laws + province, gazette_no, gazette_date, act_no), ZSTD, one row group each.
QA: page-boundary filtering (bounds_za_prov.trim), English only; title from the Act masthead; maker from the enacting clause
(Act dropped if the clause is national or no provincial legislature is confirmed); repeals only on express clauses; sections
split at line start (case-sensitive, monotone) with gaps / duplicates recorded; no padded / Jan-1 dates; webmail redaction;
post-fetch dedupe vs the national repo by title, Act number and year. Env ZA_WORK."""
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
from plan_za_prov import core, fold, year, NAT  # noqa
from bounds_za_prov import trim, lang  # noqa
W = Path(os.environ.get("ZA_WORK", (str(_LEGAL_WS) + "/world_laws/za_prov")))
PACK = W / "hf_b1/ipfs_south_africa_provincial_laws"
PROV = {"wc": ("Western Cape", "ZA-WC", "Provincial Parliament of the Western Cape", "www.wcpp.gov.za",
               r"provincial\s+(?:parliament|legislature)\s+of\s+(?:the\s+)?(?:province\s+of\s+(?:the\s+)?)?western\s+cape"),
        "kzn": ("KwaZulu-Natal", "ZA-KZN", "Provincial Legislature of KwaZulu-Natal", "kznlegislature.gov.za",
                r"provincial\s+legislature\s+of\s+(?:the\s+)?(?:province\s+of\s+)?kwa\s*zulu[\s-]*natal")}
LIC = ("Official provincial legislation published by the {leg} on its official website ({host}). Official texts of a legislative, "
       "administrative or legal nature are excluded from copyright under s.12(8)(a) of the South African Copyright Act 98 of 1978 "
       "(described, not quoted). The authentic signed Act / Provincial Gazette prevails. Not legal advice.")
WEBMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@(?:gmail|googlemail|yahoo|ymail|hotmail|outlook|live|msn|aol|icloud|me|mail|gmx|protonmail|proton|zoho|yandex|webmail|telkomsa|vodamail|mweb|iafrica|absamail|lantic)\.[A-Za-z.]{2,10}\b", re.I)
MON = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
DRX = r"(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december),?\s+((?:19|20)\d\d)"
def iso(m):
    d = f"{int(m.group(3)):04d}-{MON[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return "" if d.endswith("-01-01") else d
def masthead(body):
    lines = [l.strip() for l in body.splitlines() if l.strip()][:120]
    for i, l in enumerate(lines):
        l2 = re.sub(r"\s{3,}.*$", "", l)
        m = re.fullmatch(r"([A-Z][A-Z\-’',()& ]{3,120}?\s+ACT),?\s+((?:19|20)\d\d)", l2)
        if m and not re.search(r"\bBILL\b", l2):
            parts = [m.group(1)]; j = i - 1
            while j >= 0 and i - j <= 3 and re.fullmatch(r"[A-Z][A-Z\-’',()& ]{3,80}", lines[j]) and \
                    not re.search(r"GAZETTE|KOERANT|NOTICE|EXTRAORDINARY|PROVINCE OF|PROVINSIE|NO\.|ACT\b", lines[j]): parts.insert(0, lines[j]); j -= 1
            t = re.sub(r"\s+", " ", " ".join(parts)).title()
            t = re.sub(r"(?<!^)\b(And|Of|The|To|For|On|In)\b", lambda x: x.group(0).lower(), t).replace("Kwazulu-Natal", "KwaZulu-Natal").replace("Kzn", "KZN")
            return f"{t}, {m.group(2)}"
        m = re.fullmatch(r"(?:THE\s+)?(CONSTITUTION\s+OF\s+THE\s+(?:PROVINCE\s+OF\s+)?(?:WESTERN\s+CAPE|KWAZULU-NATAL)),?\s+((?:19|20)\d\d)", l2)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).title().replace(" Of The ", " of the ").replace("Kwazulu", "KwaZulu").replace("Province Of", "Province of") + f", {m.group(2)}"
    return None
def bill_masthead(body):
    head = "\n".join(body.splitlines()[:60])
    return bool(re.search(r"(?m)^\s*[A-Z][A-Z\-’',()& ]{3,120}\s+BILL\b", head)) and not re.search(r"(?m)^\s*[A-Z][A-Z\-’',()& ]{3,120}\s+ACT,?\s+(?:19|20)\d\d\s*$", head)
def act_no(body, raw, lab):
    for s in (body[:6000], raw[:8000], lab):
        m = re.search(r"(?i)\bact\s+(?:no\.?\s*)?(\d{1,3})\s+of\s+((?:19|20)\d\d)", s) or re.search(r"(?i)\bno\.?\s*(\d{1,3})\s+of\s+((?:19|20)\d\d)", s)
        if m: return int(m.group(1)), int(m.group(2))
        m = re.search(r"(?i)\bact\s*\[?no\.?\s*(\d{1,3})\s*-\s*((?:19|20)\d\d)", s)
        if m: return int(m.group(1)), int(m.group(2))
    return None
def gazette(raw):
    h = fold(raw[:6000]); no = None
    m = re.search(r"provincial\s+gazette[^\n]{0,60}?\bno\.?\s*(\d{3,5})\b", h) or re.search(r"(?m)^\s*(\d{4,5})\s*$", h[:1500])
    if m: no = m.group(1)
    dm = re.search(r"\b" + DRX, h[:3000])
    return no, (iso(dm) if dm else "")
def assent(body):
    f = fold(body[:6000])
    m = re.search(r"(?:assented\s+to|signed\s+by\s+the\s+premier)[^\d]{0,40}" + DRX, f) or re.search(r"\(\s*" + DRX + r"\s*\)", f)
    return iso(m) if m else ""
def maker(body, prov):
    f = re.sub(r"\s+", " ", fold(body[:30000]))
    m = re.search(r"be\s+it\s+(?:therefore\s+)?enacted\s+by\s+the\s+([^.:]{0,160})", f)
    if not m: return None, "no_enacting_clause", None
    ev = m.group(0)[:300]
    if re.search(PROV[prov][4], m.group(1)): return PROV[prov][2], "confirmed_enacting_clause", ev
    if re.search(r"parliament\s+of\s+the\s+republic", m.group(1)): return None, "national_enacting_clause", ev
    return None, "enacting_clause_other", ev
def repeals(text):
    return [re.sub(r"\s+", " ", m.group(0)).strip()[-220:] for m in re.finditer(r"[^\n]{0,160}\b(?:is|are)\s+(?:hereby\s+)?repealed\b[^\n]{0,60}", text)][:25]
SEC = re.compile(r"^ {0,20}(\d{1,3})([A-Z]?)\.?(?:\s{1,14}|(?=\())(?=[A-Z(\"“'‘])")
def split(text):
    """Line-start, case-sensitive, monotone section numbering (ported from stage_za_metro.split). Numbering that restarts at 1
    opens a new run (arrangement of sections, schedules); the first run carrying >= 60% of the largest run's text is kept."""
    runs, secs, cur, last = [], [], None, 0
    lines = text.splitlines()
    nums_at = [(i, int(m.group(1))) for i, ln in enumerate(lines) for m in [SEC.match(ln)] if m and not re.match(r"^\s*\d{1,3}\.?\s+(?:of|and|to)\b", ln)]
    def _cont(i, last):
        nxt = next((n for j, n in nums_at if j > i and n != 1 and n <= last + 2 and n > 1), None)
        later = [n for j, n in nums_at if j > i][:12]
        return nxt == last + 1 and last + 1 in later
    for li_, ln in enumerate(lines):
        m = SEC.match(ln)
        if m and not re.match(r"^\s*\d{1,3}\.?\s+(?:of|and|to)\b", ln) and not re.search(r"\.{5,}\s*\d*\s*$", ln):
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
    secs = next((r for r, z in zip(runs, size) if z >= 0.6 * max(size)), []) if size and max(size) else []
    nums = [s["n"] for s in secs]
    return secs, {"gaps": [f"{a}->{b}" for a, b in zip(nums, nums[1:]) if b > a + 1],
                  "duplicates": [k for k, v in Counter(s["num"] for s in secs).items() if v > 1]}
def redact(s, ctr):
    out, n = WEBMAIL.subn("[redacted-webmail]", s or ""); ctr["webmail_redacted"] += n; return out
def jacc(a, b):
    a, b = set(a.split()), set(b.split()); return len(a & b) / max(1, len(a | b))
def main():
    cat = {i["ident"]: i for i in json.load(open(W / "catalog.json"))}
    res = {}
    for l in open(W / "results.jsonl"):
        d = json.loads(l); res[d["ident"]] = d
    qids = json.load(open(W / "qids.json")) if (W / "qids.json").exists() else {}
    nat = pq.read_table(NAT, columns=["id", "title"]).to_pylist()
    natk = {(core(r["title"]), year(r["title"])): r["id"] for r in nat}
    natn = {}
    for r in nat:
        m = re.search(r"(?i)\bact\s+(\d{1,3})\s+of\s+((?:19|20)\d\d)", r["title"])
        if m: natn.setdefault((int(m.group(1)), int(m.group(2))), []).append((core(r["title"]), r["id"]))
    laws, arts, drops, ocr_rows, ctr, seen = [], [], [], [], Counter(), {}
    for ident, r in res.items():
        it = cat[ident]; prov = it["src"]; P = PROV[prov]
        if r.get("status") != 200:
            drops.append({"ident": ident, "reason": f"fetch_{r.get('status')}", "url": it["url"]}); continue
        raw = (W / "cache/text" / f"{ident}.txt").read_text(); src = "pdf_text_layer"; ocrm = None
        if r.get("needs_ocr"):
            oj = W / "cache/ocr" / f"{ident}.json"
            if not oj.exists(): drops.append({"ident": ident, "reason": "needs_ocr_not_done"}); continue
            ocrm = json.load(open(oj)); raw = (W / "cache/ocr" / f"{ident}.txt").read_text(); src = "ocr_tesseract"
            ocr_rows.append(ocrm)
        body, binfo = trim(raw, it.get("title", ""))
        if not body or lang(body)[0] == "other":
            drops.append({"ident": ident, "reason": "not_english_text", "bounds": binfo}); continue
        if bill_masthead(body):
            drops.append({"ident": ident, "reason": "masthead_is_bill_not_act"}); continue
        title = masthead(body)
        mk, mks, ev = maker(body, prov)
        if mks == "national_enacting_clause":
            drops.append({"ident": ident, "reason": "national_act", "title": title}); continue
        if not title:
            drops.append({"ident": ident, "reason": "no_act_masthead"}); continue
        if mks != "confirmed_enacting_clause" and not re.search(r"(?i)western cape|kwazulu|kzn", title):
            drops.append({"ident": ident, "reason": "province_unconfirmed", "title": title, "maker_status": mks}); continue
        an = act_no(body, raw, it.get("title", "")); ty = year(title)
        if an and ty and an[1] != ty: an = None
        k = core(title)
        dupn = (k, ty) in natk or any(jacc(k, c) >= 0.5 for c, _ in natn.get(an, [])) if an else (k, ty) in natk
        if dupn:
            drops.append({"ident": ident, "reason": "dup_national_repo", "title": title}); continue
        key = (prov, k, ty)
        if key in seen:
            drops.append({"ident": ident, "reason": "dup_in_pack", "title": title, "kept": seen[key]}); continue
        gno, gdate = gazette(raw); ad = assent(body)
        lid = f"za-{prov}-act-{an[1]}-{an[0]}" if an else f"za-{prov}-act-{ty}-{re.sub(r'[^a-z0-9]+', '-', k)[:60]}"
        seen[key] = lid
        secs, qa = split(body)
        if (W / "cache/pdf" / f"{ident}.pdf").exists():
            sha = hashlib.sha256((W / "cache/pdf" / f"{ident}.pdf").read_bytes()).hexdigest()
        else: sha = r.get("sha256")
        ident_s = f"Act {an[0]} of {an[1]}" if an else ""
        meta = {"schema_version": "collection_record.v1", "record_type": "law", "document_type": "provincial_act", "batch": 1,
                "province": P[0], "province_iso": P[1], "province_wikidata": (qids.get(prov) or {}).get("qid"),
                "province_wikidata_check": (qids.get(prov) or {}).get("status"), "maker": mk, "maker_status": mks, "maker_evidence": ev,
                "repeals_express": repeals(body), "listing_title": it.get("title"), "listing_url": it.get("listing_url"),
                "download_page_url": it["url"] if it["url"] != r.get("pdf_url") else None, "pdf_url": r.get("pdf_url"),
                "content_sha256": sha, "text_extraction": {"source": src, "ocr": ocrm}, "bounds": binfo, "section_qa": qa,
                "date_basis": "assent_or_signature" if ad else ("provincial_gazette_date" if gdate else None)}
        text = redact(body, ctr)
        laws.append({"id": lid, "title": title, "text": text, "source_url": r.get("pdf_url"), "source_type": f"{prov}_legislature_pdf",
                     "jurisdiction": P[1], "country": "ZA", "language": "en", "eli": None, "date": ad or gdate or None, "date_issued": ad or None,
                     "retrieved_at": r.get("retrieved_at"), "license": LIC.format(leg=P[2], host=P[3]), "law_status": "enacted",
                     "identifier": ident_s or None, "official_identifier": (f"{P[0]} {ident_s}" if ident_s else None), "article_count": len(secs),
                     "json_path": None, "metadata_json": json.dumps(meta, ensure_ascii=False), "province": P[0], "gazette_no": gno,
                     "gazette_date": gdate or None, "act_no": ident_s or None})
        for s in secs:
            t = "\n".join(s["text"])
            arts.append({"law_id": lid, "id": f"{lid}-section-{s['num']}", "title": redact(re.sub(r"\s+", " ", s["text"][0])[:200], ctr),
                         "text": redact(t, ctr), "source_url": r.get("pdf_url"), "document_number": f"section {s['num']}",
                         "article_number": f"section {s['num']}", "record_type": "article",
                         "metadata_json": json.dumps({"law_identifier": lid, "province": P[0], "metadata": {"text_extraction": {"source": src}}})})
    nl = pq.read_schema(NAT); na = pq.read_schema(W / "national/articles.parquet")
    ls = pa.schema(list(nl) + [pa.field(c, pa.string()) for c in ("province", "gazette_no", "gazette_date", "act_no")])
    (PACK / "data").mkdir(parents=True, exist_ok=True); (PACK / "manifests").mkdir(parents=True, exist_ok=True)
    lt = pa.Table.from_pylist(laws, schema=ls); at = pa.Table.from_pylist(arts, schema=na)
    for t, f in ((lt, "laws"), (at, "articles")):
        pq.write_table(t, PACK / f"data/{f}.parquet", compression="zstd", row_group_size=max(1, t.num_rows))
    with open(PACK / "manifests/batch1_drops.jsonl", "w") as fh:
        for d in drops: fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    with open(PACK / "manifests/batch1_ocr.jsonl", "w") as fh:
        for d in ocr_rows: fh.write(json.dumps(d) + "\n")
    with open(PACK / "manifests/batch1_listing_exclusions.jsonl", "w") as fh: fh.write(open(W / "listing_exclusions.jsonl").read())
    json.dump(qids, open(PACK / "manifests/batch1_wikidata.json", "w"), indent=1)
    summ = {"laws": lt.num_rows, "articles": at.num_rows, "by_province": dict(Counter(r["province"] for r in laws)),
            "drops": dict(Counter(d["reason"] for d in drops)), "webmail_redacted": ctr["webmail_redacted"], "ocr_docs": len(ocr_rows),
            "ocr_degraded": sum(1 for o in ocr_rows if o.get("status") == "DEGRADED"),
            "section_gaps": sum(len(json.loads(r["metadata_json"])["section_qa"]["gaps"]) for r in laws),
            "section_dups": sum(len(json.loads(r["metadata_json"])["section_qa"]["duplicates"]) for r in laws),
            "zero_section_laws": [r["id"] for r in laws if not r["article_count"]]}
    json.dump(summ, open(PACK / "manifests/batch1_stage_summary.json", "w"), indent=1)
    print(json.dumps(summ))
if __name__ == "__main__": main()
