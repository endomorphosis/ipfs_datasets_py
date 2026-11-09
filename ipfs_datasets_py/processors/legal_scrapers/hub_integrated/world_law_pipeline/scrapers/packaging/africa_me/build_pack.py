#!/usr/bin/env python3
"""Per-country pack builder (Africa + Middle East lane) on top of common_crawl_helper.

usage: build_pack.py CC [CC ...]   (run from /tmp with ipfs_datasets_fresh_venv python)
Output: $IPFS_DATASETS_LEGAL_COLLECTORS_ROOT/ready_africa_me_cc_packs_20261010/<cc>/{data/laws.parquet,data/articles.parquet,
        provenance/cc_pointers.parquet, MANIFEST.json, README.md}
Schema pinned to the raw layer (world_package.LAW_COLS / ART_COLS): laws 19 cols, articles 9 cols,
all strings except article_count=int64.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
_COLLECTORS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors")))
import sys as _sys
_sys.path.insert(0, _ipfs_os.path.dirname(_ipfs_os.path.abspath(__file__)))
_LS_HELPERS = Path(__file__).resolve().parents[4] / "legal_scrapers"
if _LS_HELPERS.is_dir():
    _sys.path.insert(0, str(_LS_HELPERS))
import sys as _sys
_
# common_crawl_helper lives with hub_integrated legal_scrapers
import sys, os, re, json, hashlib, time, logging, shutil, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, str(_COLLECTORS)); import common_crawl_helper as cc
from domains import C
import pyarrow as pa, pyarrow.parquet as pq

OUT = Path((str(_COLLECTORS) + "/ready_africa_me_cc_packs_20261010"))
WORK = Path((str(_COLLECTORS) + "/africa_me_cc/work"))
MAX_FETCH = int(os.environ.get("AMC_MAX_FETCH", "400"))
N_COLL = int(os.environ.get("AMC_COLLECTIONS", "8"))
LAW_COLS = ["id","title","text","source_url","source_type","jurisdiction","country","language","eli","date","date_issued",
            "retrieved_at","license","law_status","identifier","official_identifier","article_count","json_path","metadata_json"]
ART_COLS = ["law_id","id","title","text","source_url","document_number","article_number","record_type","metadata_json"]
log = logging.getLogger("pack")

BAD_URL = re.compile(r"robots\.txt|/(wp-content|wp-json|feed|tag|category|author|gallery|photo|video|login|search|cart|sitemap)\b|\.(jpe?g|png|gif|css|js|xml|zip|mp[34])($|\?)", re.I)
NEWSY = re.compile(r"/(news|blog|actualit|press|event|contact|about|galerie|media|agenda|communique)", re.I)
LEGAL_URL = re.compile(r"(?<![a-z])(laws?|acts?|loi|lois|decrets?|d%c3%a9crets?|arretes?|ordonnances?|ley|leyes|lei|leis|decreto|proclamations?|gazettes?|journal|jo|legislation|legislations|codes?|constitution|regulations?|bulletin|boletim|diario|statutes?|bill|tax-?law|%d9%82%d8%a7%d9%86%d9%88%d9%86|قانون|مرسوم)(?![a-z])", re.I)
LEGAL_TXT = re.compile(r"\b(act|law|decree|proclamation|regulations?|ordinance|bill|constitution|gazette|statutory instrument|legal notice|loi|décret|decret|arrêté|arrete|ordonnance|code|journal officiel|constitution|règlement|reglement|lei|decreto|portaria|resolu[cç][aã]o|boletim|diploma|c[oó]digo|ley|art[ií]culo)\b|قانون|مرسوم|قرار|دستور|لائحة|الجريدة الرسمية|المادة|مادة|نظام|أمر", re.I)
STRONG = re.compile(r"(?i)\b(act|law|decree|proclamation|regulations?|ordinance|constitution|gazette|statutory instrument|legal notice|order|loi|loi organique|d[ée]cret|arr[êe]t[ée]|ordonnance|code|journal officiel|r[èe]glement|lei|decreto|portaria|resolu[cç][aã]o|boletim oficial|ley|c[oó]digo)\b[^\n]{0,80}?(n[°o]|no\.?|number|num[ée]ro|\d{1,4}\s*[/-]\s*\d{2,4}|of\s+\d{4}|du\s+\d|de\s+\d{4}|20\d\d|19\d\d)|قانون[^\n]{0,40}(رقم|\d)|مرسوم[^\n]{0,40}(رقم|\d)|(القرار|قرار)[^\n]{0,20}رقم|دستور|لائحة تنفيذية|بعد الاطلاع|Having (?:reviewed|considered|examined)|\bVu (?:la|le|les)\b|الجريدة الرسمية|(?m:^\s*(?:ال)?مادة\s*[\(\[]?\s*(?:\d|الأولى))|\b(?:Article|Section)\s+\d")
ART_LATIN = re.compile(r"(?im)^[ \t]*(?:Article|Art[ií]culo|Artigo|Art\.?|Section|Sec\.)[ \t]*(?:n[°o]\.?|N[°o]\.?)?[ \t]*(\d+[A-Za-z]?(?:[-–.]\d+)?|premier|1er|unique|[IVX]{1,6})\b")
ART_AR = re.compile(r"(?m)^[ \t]*(?:ال)?مادة[ \t]*[\(\[]?[ \t]*([0-9٠-٩]+|[\u0621-\u064A]{2,12}(?: [\u0621-\u064A]{2,12})?)[ \t]*[\)\]]?(?:[ \t]*[:：\-–.]|[ \t]*$|[ \t]+(?!(?:من|في|بند|فقرة|و|أو|الفقرة|البند)\b))")
ART_NUM = re.compile(r"(?m)^[ \t]*(\d{1,3})[ \t]*[.\-–][ \t]+(?=[A-ZÀ-Ý\u0600-\u06FF])")
AR_LETTERS = re.compile(r"[\u0600-\u06FF]")


def now_iso(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def sha(s: bytes | str): return hashlib.sha256(s if isinstance(s, bytes) else s.encode()).hexdigest()


def norm_url(u):
    p = urlparse(u); h = p.netloc.lower().removeprefix("www.")
    return h + p.path.rstrip("/") + (("?" + p.query) if p.query else "")


def detect_lang(text, default):
    s = text[:6000]
    letters = [c for c in s if c.isalpha()]
    if not letters: return default
    if sum(1 for c in letters if "\u0600" <= c <= "\u06ff") / len(letters) > 0.4: return "ar"
    w = re.findall(r"\b[a-zà-ÿ]+\b", s.lower())
    sc = {"fr": sum(1 for x in w if x in {"le","la","les","des","et","du","au","aux","est","une","pour","dans","que","par"}),
          "en": sum(1 for x in w if x in {"the","of","and","to","in","shall","for","be","is","that","by"}),
          "pt": sum(1 for x in w if x in {"de","da","do","dos","das","que","para","os","uma","pelo","pela","em"}),
          "es": sum(1 for x in w if x in {"el","los","las","del","que","para","por","una","con","se"})}
    best = max(sc, key=sc.get)
    return best if sc[best] >= 8 else default


def garbage(text):
    lines = [l for l in text.split("\n") if l.strip()]
    if len(lines) < 5: return False
    short = sum(1 for l in lines if len(l.strip()) <= 2)
    return short / len(lines) > 0.5


def to_digits(s):
    return s.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))


def split_articles(text):
    cands = []
    for rx in (ART_LATIN, ART_AR):
        cands = [(m.start(), m.group(1).strip()) for m in rx.finditer(text)]
        if len(cands) >= 2: break
    if len(cands) < 2:  # numbered sections 1. 2. 3. ... require a clean running chain
        chain, exp = [], 1
        for m in ART_NUM.finditer(text):
            n = int(m.group(1))
            if n == exp: chain.append((m.start(), str(n))); exp += 1
        cands = chain if len(chain) >= 5 else []
    cands = cands[:5000]
    arts = []
    for i, (pos, num) in enumerate(cands):
        end = cands[i + 1][0] if i + 1 < len(cands) else len(text)
        body = text[pos:end].strip()
        if len(body) >= 15: arts.append((num, body[:30000]))
    return arts


def title_of(text, url):
    for l in text.split("\n")[:80]:
        l = l.strip()
        if 12 <= len(l) <= 220 and STRONG.search(l) and sum(c.isalpha() for c in l) > 8:
            return l
    for l in text.split("\n")[:60]:
        l = l.strip()
        if 12 <= len(l) <= 220 and LEGAL_TXT.search(l) and sum(c.isalpha() for c in l) > 8 and not re.fullmatch(r"[\W\d_]+", l):
            return l
    for l in text.split("\n")[:40]:
        l = l.strip()
        if 15 <= len(l) <= 220 and sum(c.isalpha() for c in l) > 10: return l
    return os.path.basename(urlparse(url).path) or url


def find_year(url, text, ts):
    for src in (url, text[:1500]):
        ys = [int(y) for y in re.findall(r"(?<!\d)(19[5-9]\d|20[0-2]\d)(?!\d)", src)]
        if ys: return str(ys[0])
    return None


def score(p):
    s = 0; u = p["url"]
    if "pdf" in (p.get("mime") or ""): s += 3
    if LEGAL_URL.search(u): s += 2
    if NEWSY.search(u): s -= 3
    if p["length"] > 8_000_000: s -= 5
    return s


def gather_pointers(code):
    name, lang, doms = C[code]
    cols = cc.spread_collections(N_COLL)
    seen, allp = set(), []
    for d in doms:
        try:
            ps = cc.find_pointers(d, cols, status="200", mime_regex="pdf|html", max_records=1500, max_blocks_per_collection=4)
        except Exception as e:
            log.warning("%s %s pointers failed %s", code, d, e); continue
        for p in ps:
            if BAD_URL.search(p["url"]) or re.match(r"https?://(mail|webmail|smtp|ftp|cpanel)\.", p["url"]): continue
            k = norm_url(p["url"]); dg = p.get("digest")
            if k in seen or (dg and dg in seen): continue
            seen.add(k); dg and seen.add(dg)
            p["domain"] = d; allp.append(p)
        log.info("%s %s -> %d (cum %d)", code, d, len(ps), len(allp))
    allp.sort(key=score, reverse=True)
    return allp


def process(code):
    name, lang, doms = C[code]
    WORK.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ptrs = gather_pointers(code)
    sel = [p for p in ptrs if p["length"] <= 8_000_000][:MAX_FETCH]
    log.info("%s: %d pointers, fetching %d", code, len(ptrs), len(sel))
    laws, arts, stats = [], [], {"pointers": len(ptrs), "fetched": 0, "fetch_errors": 0, "gated_out": 0, "dupe": 0}
    seen_txt = set(); retrieved = now_iso()
    for i in range(0, len(sel), 40):
        if not cc.resource_guard(wait=True): log.error("%s resource guard stop", code); break
        for r in cc.fetch_records(sel[i:i + 40]):
            if r.get("error") or r.get("http_status") != 200 or not r.get("body"):
                stats["fetch_errors"] += 1; continue
            stats["fetched"] += 1
            txt = re.sub(r"[ \t]{2,}", " ", cc.clean_text(cc.extract_text(r["body"], r.get("mime"))))
            if len(txt) < 600 or garbage(txt): stats["gated_out"] += 1; continue
            head = txt[:2500]
            arts_l = split_articles(txt)
            is_html = "html" in (r.get("mime") or "") and "pdf" not in (r.get("mime") or "")
            strong = bool(STRONG.search(head[:800 if is_html else 2500]))
            if not (len(arts_l) >= 3 or strong):
                stats["gated_out"] += 1; continue
            if is_html and NEWSY.search(r["url"]) and len(arts_l) < 5:
                stats["gated_out"] += 1; continue
            h = sha(txt)
            if h in seen_txt: stats["dupe"] += 1; continue
            seen_txt.add(h)
            lid = f"{code.lower()}-cc-{sha(norm_url(r['url']))[:14]}"
            host = urlparse(r["url"]).netloc
            year = find_year(r["url"], txt, r["timestamp"])
            language = detect_lang(txt, lang)
            lic = (f"Official publication of the government of {name} ({host}); text retrieved from the Common Crawl archive "
                   f"({r['collection']}). The authentic official text prevails. Not legal advice.")
            meta = {"collector": "africa_me_cc/build_pack.py", "schema": "collection_record.v1", "source_host": host,
                    "content_sha256": h, "fetch_method": "common_crawl_ranged_warc",
                    "cc": {"collection": r["collection"], "timestamp": r["timestamp"], "warc_filename": r["filename"],
                           "warc_offset": r["offset"], "warc_length": r["length"], "digest": r.get("digest"), "mime": r.get("mime")},
                    "rights": {"not_legal_advice": True, "official_reuse_url": r["url"], "license": lic},
                    "text_extraction": {"source": "common_crawl", "backend": "pdftotext" if "pdf" in (r.get("mime") or "") else "bs4"}}
            ident = os.path.basename(urlparse(r["url"]).path) or lid
            laws.append({"id": lid, "title": title_of(txt, r["url"]), "text": txt, "source_url": r["url"],
                         "source_type": f"{code.lower()}_official_common_crawl", "jurisdiction": code, "country": name,
                         "language": language, "eli": None, "date": f"{year}-01-01" if year else None,
                         "date_issued": f"{year}-01-01" if year else None, "retrieved_at": retrieved, "license": lic,
                         "law_status": "current", "identifier": ident, "official_identifier": ident,
                         "article_count": len(arts_l), "json_path": f"instruments/{lid}.json",
                         "metadata_json": json.dumps(meta, ensure_ascii=False)})
            for j, (num, body) in enumerate(arts_l):
                arts.append({"law_id": lid, "id": f"{lid}-art-{j+1}", "title": body.split("\n")[0][:200], "text": body,
                             "source_url": r["url"], "document_number": ident, "article_number": num,
                             "record_type": "article", "metadata_json": json.dumps({"text_extraction": meta["text_extraction"]})})
        log.info("%s progress %d/%d laws=%d arts=%d %s", code, min(i + 40, len(sel)), len(sel), len(laws), len(arts), stats)
    write_pack(code, name, lang, doms, laws, arts, ptrs, sel, stats, time.time() - t0)
    return len(laws), len(arts)


def write_pack(code, name, lang, doms, laws, arts, ptrs, sel, stats, secs):
    d = OUT / code.lower()
    tmp = WORK / f"{code.lower()}_building"
    shutil.rmtree(tmp, ignore_errors=True); (tmp / "data").mkdir(parents=True); (tmp / "provenance").mkdir()
    lt = pa.Table.from_pylist(laws, schema=pa.schema([(c, pa.int64() if c == "article_count" else pa.large_string()) for c in LAW_COLS])) if laws else None
    at = pa.Table.from_pylist(arts, schema=pa.schema([(c, pa.large_string()) for c in ART_COLS])) if arts else None
    if lt is None:
        (tmp / "NO_ROWS.txt").write_text(json.dumps({"country": code, "stats": stats, "domains": doms}, indent=1))
    else:
        pq.write_table(lt, tmp / "data" / "laws.parquet", compression="zstd")
        pq.write_table(at if at is not None else pa.Table.from_pylist([], schema=pa.schema([(c, pa.large_string()) for c in ART_COLS])),
                       tmp / "data" / "articles.parquet", compression="zstd")
    cc.save_pointers(sel, str(tmp / "provenance" / "cc_pointers.parquet"))
    man = {"pack": f"{code.lower()}-cc-increment-20261010", "country_code": code, "country": name, "language_default": lang,
           "generated_at": now_iso(), "kind": "increment (new rows, not a full replacement of endomorphosis/ipfs_*_laws)",
           "schema": {"laws": LAW_COLS, "articles": ART_COLS, "article_count_dtype": "int64", "text_dtype": "large_string",
                      "reference": "world_package.LAW_COLS/ART_COLS (raw layer, 19/9 columns)"},
           "rows": {"laws": len(laws), "articles": len(arts)}, "stats": stats, "candidate_domains": doms,
           "method": "common_crawl_helper: S3 cluster.idx -> CDXJ -> ranged WARC; no live requests to source sites",
           "elapsed_s": round(secs, 1), "upload_owner": "Chief of Staff (not uploaded)",
           "files": {}}
    for f in sorted(tmp.rglob("*")):
        if f.is_file(): man["files"][str(f.relative_to(tmp))] = {"bytes": f.stat().st_size, "sha256": sha(f.read_bytes())}
    (tmp / "MANIFEST.json").write_text(json.dumps(man, indent=1, ensure_ascii=False))
    (tmp / "README.md").write_text(f"# {name} ({code}) — Common Crawl increment pack\n\nLaws: {len(laws)}  Articles: {len(arts)}\n\n"
        f"Official/government domains harvested from Common Crawl via ranged WARC reads (no live requests). "
        f"Schema = raw `ipfs_*_laws` layer (laws 19 cols, articles 9 cols, article_count int64). Merge/dedupe against the existing "
        f"`endomorphosis/ipfs_*_laws` rows by `source_url`/`content_sha256` before upload. Not legal advice; official gazette prevails.\n\n"
        f"Stats: `{json.dumps(stats)}`\n")
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(d, ignore_errors=True); shutil.move(str(tmp), str(d))
    log.info("PACK %s laws=%d arts=%d -> %s", code, len(laws), len(arts), d)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("ipfs_datasets_py").setLevel(logging.ERROR)
    for code in sys.argv[1:]:
        try:
            print("DONE", code, process(code), flush=True)
        except Exception as e:
            import traceback; traceback.print_exc(); print("FAIL", code, e, flush=True)
