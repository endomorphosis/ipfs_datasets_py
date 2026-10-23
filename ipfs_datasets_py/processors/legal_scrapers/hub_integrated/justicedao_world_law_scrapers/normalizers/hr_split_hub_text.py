#!/usr/bin/env python3
"""Croatia (HR): build articles.parquet by splitting hub laws.text locally (no network).

Priority: (1) 108 existing Hub article rows verbatim (byte-identical values, no dedupe);
(2) NN-crawled articles (hr_extract_articles.py) for laws that have them;
(3) local split of laws.text for every other law with text.
Uses split_units/ID conventions from hr_extract_articles.py. Streams laws in batches.
Stops if MemAvailable <= 3.5 GiB. Writes gap list of laws with no articles. No network, no IR.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import importlib.util, json, re, sys, time
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq

spec = importlib.util.spec_from_file_location("hrx", "/workspace/scripts/hr_extract_articles.py")
hrx = importlib.util.module_from_spec(spec); spec.loader.exec_module(hrx)

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "{_CORPORA}/hr/extract/articles_merged.parquet")
GAP = Path("/workspace/country-law-triage/croatia_gap_list.json")
STATS = _CORPORA / "hr" / "extract" / "split_stats.json"
MEM_STOP_KB = int(3.5 * 1024 * 1024)
COLS = hrx.COLS
schema = pa.schema([(c, pa.string()) for c in COLS])
NN_HDR = re.compile(r"^NN \d+/\d{4} \(")
MIN_BODY = 200


def body_lines(text: str) -> list[str]:
    L = [re.sub(r"\s+", " ", x).strip() for x in (text or "").replace("\r", "").replace("\u00ad", "").replace("\xa0", " ").split("\n")]
    L = [x for x in L if x]
    s = 0
    for i, x in enumerate(L[:40]):
        if NN_HDR.match(x):
            s = i + 1; break
    e = len(L)
    for i in range(s, len(L)):
        if L[i].startswith("Dio NN:") or L[i].startswith("Opći uvjeti korištenja"):
            e = i
            if e > s and L[e - 1] == "Više":
                e -= 1
                if e > s and re.search(r", NN \d+/\d{4}-\d+$", L[e - 1]):
                    e -= 1
            break
    return L[s:e]


def main():
    hub = pq.read_table(hrx.HUB_ARTS)
    hub_laws = set(hub.column("law_id").to_pylist())
    w = pq.ParquetWriter(OUT.with_suffix(".tmp"), schema, compression="zstd")
    w.write_table(hub.select(COLS).cast(schema))
    st = {"hub_existing": hub.num_rows, "crawled": 0, "split": 0, "laws_hub": len(hub_laws),
          "laws_crawled": 0, "laws_split": 0, "split_units": {}}
    # crawled NN rows (skip the 108 seeded hub rows)
    crawled_laws = set(); batch = []
    for line in hrx.ARTS_JSONL.open(encoding="utf-8"):
        r = json.loads(line)
        if '"hr_extract_articles"' not in (r.get("metadata_json") or ""):
            continue
        if r["law_id"] in hub_laws:
            continue
        crawled_laws.add(r["law_id"]); batch.append({c: r.get(c) for c in COLS})
    w.write_table(pa.Table.from_pylist(batch, schema=schema))
    st["crawled"] = len(batch); st["laws_crawled"] = len(crawled_laws); batch = []
    gaps = []
    pf = pq.ParquetFile(hrx.HUB_LAWS)
    n = 0
    for rb in pf.iter_batches(batch_size=500, columns=["id", "title", "text", "source_url"]):
        if hrx.mem_available_kb() <= MEM_STOP_KB:
            w.close(); OUT.with_suffix(".tmp").unlink()
            print("MEM GUARD tripped; abort"); sys.exit(3)
        out = []
        for r in rb.to_pylist():
            n += 1
            lid = r["id"]
            if lid in hub_laws or lid in crawled_laws:
                continue
            L = body_lines(r["text"])
            blen = sum(len(x) for x in L)
            if not (r["text"] or "").strip():
                gaps.append({"law_id": lid, "reason": "empty_text", "body_chars": 0, "title": r["title"], "source_url": r["source_url"]}); continue
            if blen < MIN_BODY:
                gaps.append({"law_id": lid, "reason": "short_text", "body_chars": blen, "title": r["title"], "source_url": r["source_url"]}); continue
            units, kind = hrx.split_units(L)
            if not units:
                gaps.append({"law_id": lid, "reason": "no_article_structure", "body_chars": blen, "title": r["title"], "source_url": r["source_url"]}); continue
            st["laws_split"] += 1; st["split_units"][kind] = st["split_units"].get(kind, 0) + 1
            for i, u in enumerate(units):
                num = u["num"]
                label = f"Članak {num}." if kind == "clanak" else f"{num}."
                out.append({
                    "law_id": lid,
                    "id": f"{lid}-{'cl' if kind == 'clanak' else 't'}-{hrx.slug(num)}-{i}"[:200],
                    "title": label, "text": "\n".join(u["lines"]),
                    "source_url": r["source_url"], "document_number": lid[3:],
                    "article_number": num, "record_type": "article",
                    "metadata_json": json.dumps({"collector": "hr_split_hub_text",
                        "source": "hub laws.text (narodne-novine.nn.hr ELI HTML snapshot)",
                        "unit": kind, "heading": u["heading"], "context": u["ctx"], "ordinal": i}, ensure_ascii=False),
                })
        if out:
            w.write_table(pa.Table.from_pylist(out, schema=schema)); st["split"] += len(out)
    w.close(); OUT.with_suffix(".tmp").replace(OUT)
    st["laws_total"] = n; st["total_articles"] = st["hub_existing"] + st["crawled"] + st["split"]
    st["laws_with_articles"] = st["laws_hub"] + st["laws_crawled"] + st["laws_split"]
    from collections import Counter
    st["gap_count"] = len(gaps); st["gap_reasons"] = dict(Counter(g["reason"] for g in gaps))
    GAP.write_text(json.dumps({"country": "HR", "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "count": len(gaps), "reasons": st["gap_reasons"], "min_body_chars": MIN_BODY,
        "note": "Laws with no articles after hub-existing + NN-crawl + local split of hub laws.text. Not crawled.",
        "laws": gaps}, ensure_ascii=False, indent=1))
    st["mem_avail_kB"] = hrx.mem_available_kb()
    STATS.write_text(json.dumps(st, indent=2)); print(json.dumps(st, indent=2))


main()
