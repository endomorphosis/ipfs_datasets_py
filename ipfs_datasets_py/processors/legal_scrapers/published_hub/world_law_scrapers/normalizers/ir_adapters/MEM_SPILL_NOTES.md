# DO / large-country IR memory spill notes

**Date:** 2026-09-06 (PT)  
**Live DO tip 6ba4:** leave running — mid-embed already on `SQLITE_THRESHOLD=1` + `do_bm25_spill_6ba4`. Disk patches are for **next** builds only; PID was not touched.

## Hypothesis (verified)

Prior DO `package_finish` OOM (~13.6G RSS) came from stock `bm25_neighbors` holding full `term_docs`/`term_pay` plus a complete in-RAM neighbor list for ~220k docs, often concurrent with embeddings/corpus/BM25 maps. Embedding batches alone are manageable with `.npy` checkpoints; the killer is neighbor + package materialization.

## What changed (exact paths)

### Shared library (`country_laws_ir`) — used by BE/FR/PL via `build_country`

| Path | Change |
| --- | --- |
| `/workspace/country-laws-ir/country_laws_ir/mem.py` | **NEW** — `MemAvailable`/`RSS` logging, collector SIGTERM shed (0-arts first; AT/DK last), abort if `MemAvailable < 2.5G` or `RSS > 12G`. Env: `IR_MEM_WARN_GIB`, `IR_MEM_ABORT_GIB`, `IR_RSS_ABORT_GIB`, `IR_MEM_LOG_EVERY`. |
| `/workspace/country-laws-ir/country_laws_ir/spill.py` | **NEW** — SQLite FTS5 neighbor streaming (≥40k), resume-safe `neighbors_*.pkl` shards, BM25 TF spill to parquet, `build_graph_from_neighbor_shards` (no full neighbor list). Spill dir: `cache/<slug>_bm25_spill/`. |
| `/workspace/country-laws-ir/country_laws_ir/package.py` | **ADD** `package_release_sequential`, `package_from_spill` — write corpus → bm25 → graph → vectors one at a time; never hold all in RAM. |
| `/workspace/country-laws-ir/country_laws_ir/build.py` | Large corpora (`n ≥ 40k`) use sqlite spill + sequential package automatically. |
| `/workspace/country-laws-ir/country_laws_ir/vectors.py` | Encode loop calls `mem.checkpoint` each chunk (RSS/MemAvailable abort). |

### DO / operator scripts

| Path | Change |
| --- | --- |
| `/workspace/do_ir_resume/dominicanrepublic_build.py` | **NEXT-run only** — after embed: spill `vectors.pkl`; sqlite neighbors return **shard paths** (no assemble); BM25 via `build_bm25_tf_spill`; graph via `build_graph_from_neighbor_shards`; package via `package_from_spill`; `MemAbort` exit 2. Live PID unaffected. |
| `/workspace/do_ir_resume/spill_build_template.py` | **NEW** template for TN/BE/FR/PL — copy, set `SLUG`/`TIP`/`SRC`. |
| `/workspace/do_ir_resume/MEM_SPILL_NOTES.md` | This file. |

Existing DO spill scripts (`dominicanrepublic_package_{spill,sqlite,resume,seq}.py`) remain valid fallbacks; prefer shared `spill.py` + `package_from_spill` going forward.

## How to run (CoS)

### Live DO 6ba4 (do not restart)

```bash
# monitor only
ps -p 348086 -o pid,rss,etime,cmd
tail -f /workspace/country-laws-ir/reports/dominicanrepublic_build_6ba4c0218006.log
# abort only if RSS > 12G (watchdog in NEXT builds; live process has local WARN_GIB=3.5 shed)
```

Spill for live run: `/workspace/country-laws-ir/cache/do_bm25_spill_6ba4/`  
Embeddings: `/workspace/country-laws-ir/cache/embeddings/dominicanrepublic_6ba4c0218006.npy`

### Next DO package (after embed completes, or fresh tip)

If live process finishes embed but old in-memory package path is risky, kill only after checkpoint is complete and re-run **updated** script (or package-only via spill):

```bash
# Prefer letting updated dominicanrepublic_build.py finish post-embed stages,
# OR package-only once shards exist:
python -u /workspace/do_ir_resume/dominicanrepublic_build.py
# (resume: encode_corpus reloads .npy; neighbor/FTS resume in spill helpers)
```

### BE / FR / PL / TN

```bash
cp /workspace/do_ir_resume/spill_build_template.py /workspace/do_ir_resume/belgium_build_spill.py
# edit SLUG, TIP, SRC, OUT
IR_MEM_WARN_GIB=3.5 IR_RSS_ABORT_GIB=12.0 \
  /workspace/venv/bin/python -u /workspace/do_ir_resume/belgium_build_spill.py

# Or via shared build_country (auto sqlite when n>=40k):
cd /workspace/country-laws-ir && python -m country_laws_ir build belgium
```

Expected sizes: BE ~784k, FR ~677k, PL ~534k → **must** use sqlite spill (stock neighbors will OOM).

## Design summary

1. **Embeddings** — chunked encode, atomic `.npy` + `.json` checkpoint (existing).  
2. **Neighbors** — SQLite FTS5 title-only MATCH (skillcenter `iter_entry_neighbors` pattern); shards of 5k; resume contiguous.  
3. **BM25 TF** — tokenize → SQLite WITHOUT ROWID → posting parquet parts → concat.  
4. **Graph** — structural graph first, stream `BM25_NEIGHBOR_OF` from shards, recompute adjacency once.  
5. **Package** — sequential shard writes; reload one artifact at a time from spill.  
6. **Mem** — log every N rows; shed lean collectors under 3.5G MemAvailable; abort under 2.5G avail or RSS>12G.

## How to verify

```bash
python -c "from country_laws_ir.mem import checkpoint; from country_laws_ir.spill import SQLITE_THRESHOLD; from country_laws_ir.package import package_from_spill; print(SQLITE_THRESHOLD)"
# After a spill run:
ls /workspace/country-laws-ir/cache/<slug>_bm25_spill/neighbors_*.pkl | wc -l
ls /workspace/country-laws-ir/cache/<slug>_bm25_spill/{bm25_documents,bm25_postings}.parquet graph.pkl vectors.pkl
# RSS during neighbors should stay well under 12G (typically ≤8G with collectors lean)
```

## Remaining risks

- `layout_vectors` still builds a large DataFrame of Python float lists before spill — peak after embed can be multi-GB; spill ASAP (now done).  
- `build_graph_from_neighbor_shards` still holds full edges DataFrame at end (structural + neighbor edges) — for ~800k×8 edges watch RSS; may need edge parquet streaming next.  
- SQLite FTS neighbor quality is title-only MATCH (faster/leaner than full Okapi neighbor scan); scores differ slightly from stock `bm25_neighbors`.  
- Live DO 6ba4 process still runs **pre-patch** bytecode until exit; post-embed stages on that PID use old assemble+`package_release` unless restarted after embed checkpoint.  
- Protect AT+DK collectors; shed MM/TH/IS/LT first.
