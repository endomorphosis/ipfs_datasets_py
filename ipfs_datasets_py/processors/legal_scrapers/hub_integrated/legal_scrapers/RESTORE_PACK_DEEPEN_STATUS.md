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
