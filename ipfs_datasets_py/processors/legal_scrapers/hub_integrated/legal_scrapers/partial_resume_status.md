# Partial resume status — legal corpus scrapers

Generated: 2026-09-04 11:06:00 PT

Operator: endomorphosis Hugging Face datasets (`ipfs_*_laws`).
Not legal advice. Official gazettes prevail.

## Before → after (round 4)

| Country | Laws before → after | Articles before → after | Δ laws | Δ arts | Upload |
| --- | --- | --- | --- | --- | --- |
| Italy | 6278 → **8110** | 1104 → **1265** | +1832 | +161 | https://huggingface.co/datasets/endomorphosis/ipfs_italy_laws |
| Romania | 13128 → **15128** | 915 → **1925** | +2000 | +1010 | https://huggingface.co/datasets/endomorphosis/ipfs_romania_laws |
| Slovenia | 6161 → **8161** | 346 → **475** | +2000 | +129 | https://huggingface.co/datasets/endomorphosis/ipfs_slovenia_laws |
| Bulgaria | 297 → **320** | 3576 → **3877** | +23 | +301 | https://huggingface.co/datasets/endomorphosis/ipfs_bulgaria_laws |
| Cyprus | 127 → **198** | 1690 → **2690** | +71 | +1000 | https://huggingface.co/datasets/endomorphosis/ipfs_cyprus_laws |

## Summary deltas

- **Italy**: resumed Normattiva catalog (200k 2004–1861 shard); +1832 acts (168 fails). Uploaded.
- **Romania**: SOAP years from 2010; +2000 (0 fails). Uploaded.
- **Slovenia**: moved `catalog.jsonl` → `catalog_aside_r3.jsonl`; rediscovered YEAR_START=2022 MAX_CATALOG=8000; +2000 from new catalog (8026 entries). Uploaded.
- **Bulgaria**: Wayback CDX timestamps + windows; live TLS still SSLEOF; captcha interstitial + CDX HTTP 503 thinning. Stopped mid-flight at ok=23/200 (fail≈353). Net +23 laws / +301 arts. Uploaded checkpoint.
- **Cyprus**: patched collector (skip known fails; CDX-ts Wayback-first; sort newer first). +71 GPO PDFs. Honest article extract via IntegratedPDFProcessor/pdfplumber: `{'none': 111, 'arithmos_notice': 48, 'orthro_article': 28, 'meros_section': 11}` → **2690 articles** across 87/198 laws. Stopped past MAX_SECONDS on hung live PDF. cylaw.org not used. Uploaded.

## Common Crawl usage (indexes / CDX only — no bulk WARC)

Probes via `archive_fallbacks.search_common_crawl` (index.commoncrawl.org) with small limits. No WARC dumps.

| Query | limit | hits | secs | notes |
| --- | --- | --- | --- | --- |
| `dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat=` | 50 | **0** | 82.3 | err=None |
| `dv.parliament.bg/DVWeb/` | 40 | **0** | 27.0 | err=None |
| `www.mof.gov.cy/mof/gpo/gazette.nsf` | 40 | **0** | 24.3 | err=None |
| `mof.gov.cy/mof/gpo/gazette.nsf/*/$file/` | 30 | **0** | 24.2 | err=None |

- BG/CY: **+0 laws from CC** this round (index empty for these hosts/paths).
- HF curated CC indexes (`CommonCrawlIndexLoader`) US-focused; not used.
- Log: `~/.ipfs_datasets/legal_collectors/logs/cc_probe_round4.json`
- Disk: no WARC downloads; root ~113G free throughout.

## Blockers remaining

| Country | Blocker |
| --- | --- |
| Italy | Volume — ~200k catalogued 2004–1861; continue MAX_NEW slices |
| Romania | Years ≤2009 largely untouched; HTML portal TCP-closes; SOAP OK |
| Slovenia | New 2022 catalog 8k partially fetched (~2k of 8k); older years ≤2021 not rediscovered yet (MAX_CATALOG stop) |
| Bulgaria | Live TLS SSLEOF; Wayback captcha on many timestamps; CDX 503s thinning pool; CC CDX empty this probe |
| Cyprus | Whole-issue PDFs; 111/198 lack honest Άρθρο/Αριθμός/ΜΕΡΟΣ structure; live hangs on some Greek-filename indexes; GPO cert incomplete; CC thin; cylaw.org forbidden |

## PDF / parser notes

- Cyprus: pdfplumber via IntegratedPDFProcessor path; `scrapers/cy_extract_articles.py` honest heading split only.
- Round-4 CY collector tweaks: `known_fail_keys`, Wayback-first when CDX ts present, sort CDX by timestamp desc.

## Disk hygiene

- Root free ~113G (6–7% used). Corpora ~818M; logs ~872K.
- No CC WARC / large HF shard downloads.
- No logs >20MB; no residual `.warc` temps found after uploads.

## Next resume commands

```bash
source /workspace/hf-venv/bin/activate
cd ~/.ipfs_datasets/legal_collectors/scrapers

YEAR_START=2004 YEAR_END=1861 MAX_NEW=2000 MAX_SECONDS=14400 python -u collect_it.py
YEAR_START=2009 YEAR_END=1990 MAX_NEW=2000 MAX_SECONDS=14400 python -u collect_ro.py
# Slovenia — continue remaining from current 8026 catalog (no aside needed):
MAX_NEW=2000 MAX_SECONDS=14400 python -u collect_si.py
# or aside again + YEAR_START=2021 for older TOC rediscover
MAX_NEW=200 MAX_SECONDS=7200 ID_RADIUS=8 CDX_LIMIT=2500 SKIP_KNOWN_FAIL=1 python -u collect_bg.py
MAX_NEW=100 MAX_SECONDS=3600 MAX_CATALOG=800 python -u collect_cy.py
python -u cy_extract_articles.py

cd ~/.ipfs_datasets/legal_collectors
python restore_and_package.py package-upload <cc> 'checkpoint'
```

## Artifacts

- `~/.ipfs_datasets/legal_collectors/scrapers/` — collectors (+ `cy_extract_articles.py`, BG captcha-aware Wayback)
- `/workspace/ipfs_datasets_py_snip/` — IntegratedPDFProcessor + CC helpers
- `~/.ipfs_datasets/legal_corpora/{it,ro,si,bg,cy}/`
- Logs: it5, ro6, si4, bg5, cy5b, cy_article_extract_r4, cc_probe_round4
- SI aside catalog: `~/.ipfs_datasets/legal_corpora/si/raw/catalog_aside_r3.jsonl`


---

# Restore + packaging + deepen — 2026-09-04 12:33 PT

Operator notes. Not legal advice. Official gazettes prevail. Skipped USA; did **not** touch SN/RW/UG.

## Priority 1 — Iceland RESTORE

| Field | Before | After |
| --- | --- | --- |
| HF tip | ~60 laws / 0 arts (chrome/nav junk regression) | **917 / 0** |
| Local instruments | 60 (thin) | **917** restored from HF tip; thin set → `instruments_thin60_bak` |
| Staging | 60 | **917** rebuilt |
| URL | https://huggingface.co/datasets/endomorphosis/ipfs_iceland_laws | tip sha `f6fef90d2ef5` |

Notes: Tip already republished at 917 by prior restore (`36be55c1` / PUBLISH_STATUS). This pass re-synced local+staging from tip and re-uploaded to guard against thin package-upload. `collect_is.py` MAX_NEW default patched **80→0** to avoid thin regressions. Catalog ~918 Althingi acts — near-complete index snapshot.

## Priority 2 — Italy PACKAGING (honest)

| Field | Before (stale card / shells) | After (honest) |
| --- | --- | --- |
| HF tip / README | 47938 laws / 42 arts (shell catalog) | **6314 / 1265** |
| Local JSON | 8110 (incl. 1796 text&lt;80 shells) | unchanged; package drops shells |
| README vs parquet | mismatched historically | **match** |
| URL | https://huggingface.co/datasets/endomorphosis/ipfs_italy_laws | tip sha `6337e5421eba` |

Notes: No blind MAX_NEW. Rebuilt package from `~/.ipfs_datasets/legal_corpora/it/` with text≥80 filter. Normattiva catalog ~200k remains for future year-paged slices.

## Priority 3 — Verifier deepen AM → PY → ET → BG → CY

| CC | HF before | HF after | Δ laws | Δ arts | URL |
| --- | ---: | ---: | ---: | ---: | --- |
| AM | 10→130 then **130/11161** | **342 / 16679** | +212 vs 130 | +5518 | https://huggingface.co/datasets/endomorphosis/ipfs_armenia_laws |
| PY | **28 / 0** | **427 / 4434** | +399 | +4434 | https://huggingface.co/datasets/endomorphosis/ipfs_paraguay_laws |
| ET | **39 / 3** | **57 / 19** | +18 | +16 | https://huggingface.co/datasets/endomorphosis/ipfs_ethiopia_laws |
| BG | **320 / 3877** | **1669 / 15604** (local deepen pass packaged 488/5295; tip advanced further) | +1349 tip | +11727 tip | https://huggingface.co/datasets/endomorphosis/ipfs_bulgaria_laws |
| CY | **198 / 2690** | **302 / 4398** | +104 | +1708 | https://huggingface.co/datasets/endomorphosis/ipfs_cyprus_laws |

### Deepen method notes
- **AM**: ARLIS live HTML + CDX prefix `arlis.am/*/acts/` (CDX_LIMIT=600, MAX_NEW=200).
- **PY**: BACN sitemap + HTML `.entry-content` (MAX_NEW=200); article Art. splits.
- **ET**: MoJ/FSC PDFs; many jet_download Wayback IncompleteRead fails; readable-text filter dropped 1 binary dump; article splits still thin (Amharic PDF).
- **BG**: Wayback of `dv.parliament.bg` showMaterialDV (live TLS SSLEOF); captcha skips; MAX_NEW=150 → local 488 then tip shows larger set.
- **CY**: GPO mof.gov.cy PDFs via Wayback only; **cylaw.org not used**; `cy_extract_articles.py` → 4398 arts (`arithmos_notice`/`orthro_article`/`meros_section`).

## Disk / CC hygiene
- Root free ~112G (stop rule &lt;20G free unused).
- CC CDX small limits only; no bulk WARC.
- No WAF bypass; no cylaw.org.
