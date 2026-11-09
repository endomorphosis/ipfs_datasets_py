#!/usr/bin/env python3
"""Build the JO municipal supplement (add-only vs endomorphosis/ipfs_jordan_municipal_laws) from the collected state.
Inputs : $JO_STATE/gazette/{issues,text}, $JO_STATE/lists/{listing.json,text}, terms.json, robots_status.json, hub/{mun,nat}.
Outputs: $JO_OUT/data/laws-00001.parquet, data/articles-00001.parquet, $JO_STATE/image_only_pdfs.json, $JO_STATE/build_report.json.
Gates (Verifier ZA lessons): non-laws excluded (classifier), text-layer quality gate (no OCR), truncated / cover-only text dropped,
near-duplicates by 8-word shingle containment (in-pack and vs the Hub), compilations flagged, language by script, full terms text."""
import os, re, sys, json, gzip, glob, hashlib, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/workspace/legal_scrapers")
import pyarrow as pa, pyarrow.parquet as pq
import jo_common as C
import collect_jo_gazette as G
from schema import MUNICIPAL_LAWS_SCHEMA, RAW_ARTICLES_SCHEMA, validate_municipal_table, municipal_law_id

ST = C.STATE
OUT = os.environ.get("JO_OUT", "/workspace/legal-corpora/municipal/jordan_municipal")
PAGE_OK, DOC_PAGES_OK, DOC_SCORE_OK = 0.70, 0.90, 0.75
AR_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

MUNI = [  # (regex, code, Arabic name, English name, admin1)
    (r"أمانة\s*عمان|امانة\s*عمان|مدينة\s+عمان|حدود\s+عمان", "q8959166", "أمانة عمان الكبرى", "Greater Amman Municipality", "JO-AM"),
    (r"بلدية\s+إربد|بلدية\s+اربد", "irbid", "بلدية إربد الكبرى", "Greater Irbid Municipality", "JO-IR"),
    (r"بلدية\s+الزرقاء", "zarqa", "بلدية الزرقاء", "Zarqa Municipality", "JO-AZ"),
    (r"بلدية\s+الرصيفة", "russeifa", "بلدية الرصيفة", "Russeifa Municipality", "JO-AZ"),
    (r"بلدية\s+السلط", "salt", "بلدية السلط الكبرى", "Greater Salt Municipality", "JO-BA"),
    (r"بلدية\s+مادبا", "madaba", "بلدية مادبا الكبرى", "Greater Madaba Municipality", "JO-MD"),
    (r"بلدية\s+الكرك", "karak", "بلدية الكرك الكبرى", "Greater Karak Municipality", "JO-KA"),
    (r"بلدية\s+معان", "maan", "بلدية معان الكبرى", "Greater Ma'an Municipality", "JO-MN"),
    (r"بلدية\s+المفرق", "mafraq", "بلدية المفرق الكبرى", "Greater Mafraq Municipality", "JO-MA"),
    (r"بلدية\s+جرش", "jerash", "بلدية جرش الكبرى", "Greater Jerash Municipality", "JO-JA"),
    (r"بلدية\s+عجلون", "ajloun", "بلدية عجلون الكبرى", "Greater Ajloun Municipality", "JO-AJ"),
    (r"بلدية\s+الطفيلة", "tafila", "بلدية الطفيلة الكبرى", "Greater Tafila Municipality", "JO-AT"),
    (r"بلدية\s+سحاب", "sahab", "بلدية سحاب", "Sahab Municipality", "JO-AM"),
    (r"بلدية\s+الرمثا", "ramtha", "بلدية الرمثا الجديدة", "Ramtha Municipality", "JO-IR"),
]
FURNITURE_RX = re.compile(r"^\s*(?:\d{1,5}|صفحة\s*\d+|الجريدة\s+الرسمية.*|عدد\s*\d+.*الجريدة.*|رقم\s+العدد.*)\s*$")
ART_RX = re.compile(r"(?m)^[ \t]*(?:ال)?مادة\s*[\(\[]?\s*(\d{1,3})\s*[\)\]]?")
KEY_RX = re.compile(r"(نظام|تعليمات)\s*(?:رقم|رقـم)\s*\(?\s*([0-9]{1,4})\s*\)?\s*(?:لسنة|لعام)\s*([0-9]{4})")
COMP_RX = re.compile(r"وتعديلاته|وتعديلاتها|مجموعة\s+(?:الأنظمة|التعليمات)|نسخة\s+معدلة|مع\s+التعديلات")


def tnorm(t):
    t = C.norm_ar(t or "").translate(AR_DIG)
    return t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")


def shingles(t, n=8):
    w = re.findall(r"[\u0621-\u064a0-9]+", tnorm(t))
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def containment(a, b):
    return len(a & b) / len(a) if a else 0.0


def law_key(s):
    m = KEY_RX.search(C.norm_ar(s or "").translate(AR_DIG))
    return (m.group(1), int(m.group(2)), int(m.group(3))) if m else None


def municipality(title, text_head):
    for rx, code, ar, en, a1 in MUNI:
        if re.search(rx, title):
            return "municipal", code, ar, en, a1
    m = re.search(r"بلدية\s+([\u0621-\u064a]+(?:\s+[\u0621-\u064a]+)?)", title)
    if m and not re.search(r"البلديات|بلدية\s+(?:و|في)", m.group(0)):
        code = "other-" + hashlib.sha1(m.group(0).encode()).hexdigest()[:8]
        return "municipal", code, m.group(0), "", ""
    return "national", "national", "", "", ""   # general rules for all municipalities / local councils (MoLA)


def clean_text(pages):
    lines = []
    for p in pages:
        for l in p["text"].replace("\r", "").split("\n"):
            l = re.sub(r"[ \t\u00a0]+", " ", l).strip()
            if not l or FURNITURE_RX.match(l.translate(AR_DIG)):
                continue
            lines.append(l)
    return "\n".join(lines).strip()


def split_articles(text):
    """Exact cover of text[start:] by articles (char spans); preamble kept as record_type=preamble."""
    ms = list(ART_RX.finditer(text))
    if not ms:
        return []
    out = []
    if ms[0].start() > 0 and text[:ms[0].start()].strip():
        out.append(("0", "preamble", 0, ms[0].start()))
    for i, m in enumerate(ms):
        out.append((m.group(1), "article", m.start(), ms[i + 1].start() if i + 1 < len(ms) else len(text)))
    return out


def terms_text(host):
    T = json.load(open(os.path.join(ST, "terms.json")))[host]
    return "\n\n".join(f"[{x['url']} retrieved {x['retrieved_at']}]\n{x['text']}" for x in T if x.get("status") == 200)


def main():
    os.makedirs(os.path.join(OUT, "data"), exist_ok=True)
    robots = json.load(open(os.path.join(ST, "robots_status.json")))
    lic_pm = ("Official Gazette of the Hashemite Kingdom of Jordan (الجريدة الرسمية), published by the Prime Ministry "
              "(www.pm.gov.jo; documents served by doc.pm.gov.jo). Official legislative texts; Jordanian Copyright Law "
              "No. 22 of 1992, art. 7, excludes laws, regulations and official documents from protection. Publisher's "
              "site terms, quoted in full:\n\n" + terms_text("pm.gov.jo"))
    hub_mun = pq.read_table(os.path.join(ST, "hub/mun/data/laws-00001.parquet"), columns=["id", "title", "text", "official_identifier"]).to_pylist()
    hub_nat = pq.read_table(os.path.join(ST, "hub/nat/data/laws.parquet"), columns=["id", "title", "text"]).to_pylist()
    hub_keys = {}
    for h in hub_mun:
        k = law_key(h["title"])
        if not k and h.get("official_identifier") and "/" in str(h["official_identifier"]):
            n, y = str(h["official_identifier"]).split("/")[:2]
            kind = "تعليمات" if "تعليمات" in h["title"] else "نظام"
            if n.isdigit() and y.isdigit():
                k = (kind, int(n), int(y))
        if k:
            hub_keys.setdefault(k, h["id"])
    for h in hub_nat:
        k = law_key((h["text"] or "")[:400])
        if k and k[0] == "نظام":
            hub_keys.setdefault(k, h["id"])
    hub_sh = [(h["id"], shingles(h["text"])) for h in hub_mun]
    nat_sh = None  # built lazily (1,229 national texts)

    scope = {}
    for f in glob.glob(os.path.join(ST, "gazette/issues/*.json")):
        d = json.load(open(f))
        for it in d.get("items", []):
            k, why = G.classify(it)
            scope[it["did"]] = (k, why, it)
    rep = collections.Counter(); image_only, dropped, rows, arts = [], [], [], []
    for fn in sorted(glob.glob(os.path.join(ST, "gazette/text/*.json.gz"))):
        r = json.loads(gzip.open(fn).read())
        did = r["did"]; k, why, it = scope.get(did, ("out", "not in current index", r["item"]))
        base = {"did": did, "issue": it["issue"], "title": it["title"], "viewer_url": it["viewer_url"],
                "download_url": r.get("download_url", "")}
        if k != "in":
            rep["out_of_scope_after_reclassify"] += 1; dropped.append({**base, "reason": why}); continue
        if r.get("status") != 200:
            rep["http_" + str(r.get("status"))] += 1; dropped.append({**base, "reason": f"HTTP {r.get('status')}"}); continue
        if r.get("image_only") or r.get("kind") != "pdf":
            reason = {"zip": "DocuWare TIFF scan (zip of .DWTiff pages)", "tiff": "TIFF scan"}.get(r.get("kind"), "PDF without a text layer")
            image_only.append({**base, "kind": r.get("kind"), "reason": reason, "members": r.get("members", [])[:5]})
            rep["image_only"] += 1; continue
        P = [p for p in r["pages"] if p["words"] >= 10]
        okp = sum(1 for p in P if p["in_vocab"] >= PAGE_OK)
        tw = sum(p["words"] for p in P)
        score = sum(p["words"] * p["in_vocab"] for p in P) / tw if tw else 0.0
        q = {"pages": r["npages"], "word_pages": len(P), "pages_ok": okp, "in_vocab_weighted": round(score, 3)}
        if not P or okp / len(P) < DOC_PAGES_OK or score < DOC_SCORE_OK:
            image_only.append({**base, "kind": "pdf", "reason": "garbled_text_layer (CID font text layer does not decode to Arabic; needs OCR)",
                               "quality": q, "fonts": r.get("fonts", [])[:5]})
            rep["garbled_text_layer"] += 1; continue
        text = clean_text(r["pages"])
        A = split_articles(text)
        nums = [int(a[0]) for a in A if a[1] == "article"]
        if len(re.findall(r"[\u0621-\u064a]+", text)) < 60 or not nums:
            dropped.append({**base, "reason": "cover-only / no article text", "quality": q}); rep["cover_only"] += 1; continue
        if nums[0] != 1:
            dropped.append({**base, "reason": f"truncated: first article is {nums[0]}", "quality": q}); rep["truncated"] += 1; continue
        key = law_key(it["title"]) or law_key(text[:600])
        sh = shingles(text)
        if key and key in hub_keys:
            dropped.append({**base, "reason": f"already on the Hub as {hub_keys[key]} (same type/number/year)"}); rep["hub_dup_key"] += 1; continue
        hd = max(((hid, containment(sh, hs)) for hid, hs in hub_sh), key=lambda x: x[1], default=(None, 0))
        if hd[1] >= 0.90:  # same repo (add-only): near-copies of existing Hub rows are not re-added
            dropped.append({**base, "reason": f"contained in Hub row {hd[0]} ({hd[1]:.3f})"}); rep["hub_dup_text"] += 1; continue
        if nat_sh is None:
            nat_sh = [(h["id"], shingles(h["text"])) for h in hub_nat]
        nd = max(((hid, containment(sh, hs)) for hid, hs in nat_sh), key=lambda x: x[1], default=(None, 0))
        if nd[1] >= 0.90:
            rep["also_in_national_hub"] += 1  # kept (different repo); flagged in extras
        lvl, code, mun_ar, mun_en, a1 = municipality(it["title"], text[:500])
        lid = municipal_law_id("jo", code, f"og{it['issue']}-d{did}")
        dm = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})", text[:1500].translate(AR_DIG))
        date_issued = f"{dm.group(3)}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}" if dm else ""
        title = re.sub(r"\s+", " ", it["title"]).strip().rstrip(".")
        extras = {"gazette_issue": it["issue"], "gazette_issue_url": G.DETAIL.format(it["issue"]), "docuware_did": did,
                  "viewer_url": it["viewer_url"], "download_url": r["download_url"], "sha256": r["sha256"], "bytes": r["bytes"],
                  "last_modified": r.get("last_modified", ""), "pdfinfo": r.get("pdfinfo", {}), "text_quality": q,
                  "text_extraction": "pdftotext (poppler) text layer; no OCR", "compilation": bool(COMP_RX.search(title)),
                  "law_key": list(key) if key else None, "hub_max_containment": round(hd[1], 3), "nat_max_containment": round(nd[1], 3),
                  "also_in_national_hub": nd[0] if nd[1] >= 0.90 else None,
                  "municipality_name_en": mun_en, "terms_urls": [x["url"] for x in json.load(open(os.path.join(ST, "terms.json")))["pm.gov.jo"]],
                  "robots": {h: robots[h]["note"] for h in ("https://www.pm.gov.jo", "https://doc.pm.gov.jo")},
                  "scope_reason": why}
        rows.append({"id": lid, "title": title, "text": text, "source_url": G.DETAIL.format(it["issue"]),
                     "source_type": "jo_official_gazette", "jurisdiction": f"JO/{code}" if lvl == "municipal" else "JO",
                     "country": "JO", "language": C.lang_of(text), "eli": None, "date": str(key[2]) if key else "",
                     "date_issued": date_issued, "retrieved_at": r["retrieved_at"], "license": lic_pm, "law_status": "published",
                     "identifier": f"OG {it['issue']} / DW {did}", "official_identifier": f"{key[1]}/{key[2]}" if key else "",
                     "article_count": len(nums), "json_path": f"gazette/text/{did}.json.gz", "metadata_json": None,
                     "jurisdiction_level": lvl, "admin_level": 8 if lvl == "municipal" else 2, "country_iso": "JO",
                     "admin1": a1 or None, "municipality": mun_ar or None, "municipality_code": code,
                     "source_body": "أمانة عمان الكبرى" if code == "q8959166" else ("وزارة الإدارة المحلية / مجلس الوزراء" if lvl == "national" else mun_ar),
                     "_extras": extras, "_sh": sh, "_A": A})
        rep["candidate"] += 1
    # in-pack near-duplicates: containment >= 0.98 -> drop the shorter; 0.80-0.98 -> version group
    rows.sort(key=lambda x: -len(x["text"]))
    keep = []
    for x in rows:
        best = max(((y, containment(x["_sh"], y["_sh"])) for y in keep), key=lambda z: z[1], default=(None, 0))
        if best[1] >= 0.98:
            best[0]["_extras"].setdefault("alt_urls", []).append(x["_extras"]["viewer_url"])
            dropped.append({"did": x["_extras"]["docuware_did"], "title": x["title"], "reason": f"contained in {best[0]['id']} ({best[1]:.3f})"})
            rep["pack_dup"] += 1; continue
        if best[1] >= 0.80:
            g = best[0]["_extras"].setdefault("version_group", best[0]["id"]); x["_extras"]["version_group"] = g
        keep.append(x)
    keep.sort(key=lambda x: x["id"])
    for x in keep:
        x["metadata_json"] = json.dumps({"extras": x["_extras"]}, ensure_ascii=False)
        for n, kind, s, e in x["_A"]:
            aid = f"{x['id']}-art-{n}" if kind == "article" else f"{x['id']}-preamble"
            arts.append({"law_id": x["id"], "id": aid, "title": "" if kind == "preamble" else f"المادة {n}",
                         "text": x["text"][s:e], "source_url": x["source_url"], "document_number": x["official_identifier"],
                         "article_number": n, "record_type": kind,
                         "metadata_json": json.dumps({"char_start": s, "char_end": e}, ensure_ascii=False)})
    seen = set(); arts2 = []
    for a in arts:  # unique (law_id, id): repeated article numbers (e.g. amending text quoting articles) get a suffix
        i, j = a["id"], 2
        while (a["law_id"], a["id"]) in seen:
            a["id"] = f"{i}-{j}"; j += 1
        seen.add((a["law_id"], a["id"])); arts2.append(a)
    cols = MUNICIPAL_LAWS_SCHEMA.names
    lt = pa.Table.from_pylist([{c: x[c] for c in cols} for x in keep], schema=MUNICIPAL_LAWS_SCHEMA)
    prob = validate_municipal_table(lt)
    if keep:
        assert not prob, prob
        assert len({x["id"] for x in keep}) == len(keep)
    for f in glob.glob(os.path.join(OUT, "data", "*.parquet")):
        os.remove(f)  # own output only
    if keep:
        pq.write_table(lt, os.path.join(OUT, "data", "laws-00001.parquet"), compression="zstd")
        pq.write_table(pa.Table.from_pylist(arts2, schema=RAW_ARTICLES_SCHEMA), os.path.join(OUT, "data", "articles-00001.parquet"), compression="zstd")
    json.dump({"generated_utc": C.now_utc(), "policy": "no OCR; listed here instead of being OCRed",
               "gate": {"page_in_vocab_min": PAGE_OK, "doc_pages_ok_min": DOC_PAGES_OK, "doc_weighted_in_vocab_min": DOC_SCORE_OK},
               "count": len(image_only), "items": image_only}, open(os.path.join(ST, "image_only_pdfs.json"), "w"), ensure_ascii=False, indent=1)
    sc = collections.Counter(v[0] for v in scope.values())
    out = {"built_utc": C.now_utc(), "issues_indexed": len(glob.glob(os.path.join(ST, "gazette/issues/*.json"))),
           "gazette_items": len(scope), "scope": dict(sc), "results": dict(rep), "laws_rows": len(keep), "articles_rows": len(arts2),
           "municipalities": sorted({x["municipality_code"] for x in keep}), "validate": prob,
           "by_level": dict(collections.Counter(x["jurisdiction_level"] for x in keep)),
           "languages": dict(collections.Counter(x["language"] for x in keep)),
           "compilations": sum(1 for x in keep if x["_extras"]["compilation"]), "dropped": dropped}
    json.dump(out, open(os.path.join(ST, "build_report.json"), "w"), ensure_ascii=False, indent=1)
    G.log(f"build: laws={len(keep)} articles={len(arts2)} {dict(rep)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
