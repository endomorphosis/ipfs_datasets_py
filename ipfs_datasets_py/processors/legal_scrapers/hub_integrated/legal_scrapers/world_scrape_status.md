# World scrape status

- updated: 2026-09-04 13:08 PT
- disk: see `df -h /` (stop under ~20G free)
- USA: skipped entirely
- IT/RO/SI/BG/CY: left alone (other agent)

## Uploaded this run (batch 1)

| Country | CC | Laws | Articles | Source | URL | Notes |
| --- | --- | ---: | ---: | --- | --- | --- |
| armenia | am | 10 | 3023 | ARLIS arlis.am | https://huggingface.co/datasets/endomorphosis/ipfs_armenia_laws | ok |
| paraguay | py | 28 | 0 | BACN bacn.gov.py | https://huggingface.co/datasets/endomorphosis/ipfs_paraguay_laws | ok |
| algeria | dz | 50 | 2829 | JORADP joradp.dz | https://huggingface.co/datasets/endomorphosis/ipfs_algeria_laws | ok |
| ecuador | ec | 80 | 24889 | gob.ec API + RO PDFs | https://huggingface.co/datasets/endomorphosis/ipfs_ecuador_laws | ok |
| bolivia | bo | 30 | 1395 | Gaceta Oficial Bolivia | https://huggingface.co/datasets/endomorphosis/ipfs_bolivia_laws | ok (filtered extractable PDFs) |
| northmacedonia | mk | 40 | 1483 | slvesnik.com.mk Issues PDFs | https://huggingface.co/datasets/endomorphosis/ipfs_northmacedonia_laws | ok |
| ethiopia | et | 39 | 3 | justice.gov.et / hopr.gov.et / FSC | https://huggingface.co/datasets/endomorphosis/ipfs_ethiopia_laws | ok (few article splits) |
| panama | pa | 36 | 2128 | gacetaoficial.gob.pa pdfTemp | https://huggingface.co/datasets/endomorphosis/ipfs_panama_laws | ok |

## Uploaded this run (batch 2)

| Country | CC | Laws | Articles | Source | URL | Notes |
| --- | --- | ---: | ---: | --- | --- | --- |
| iceland | is | 60 | 0 | Althingi Lagasafn HTML | https://huggingface.co/datasets/endomorphosis/ipfs_iceland_laws | ok (article split weak) |
| uzbekistan | uz | 45 | 1661 | lex.uz | https://huggingface.co/datasets/endomorphosis/ipfs_uzbekistan_laws | ok |
| rwanda | rw | 40 | 151 | MINIJUST Official Gazette PDFs | https://huggingface.co/datasets/endomorphosis/ipfs_rwanda_laws | ok |
| belarus | by | 40 | 7335 | pravo.by | https://huggingface.co/datasets/endomorphosis/ipfs_belarus_laws | ok |
| mongolia | mn | 40 | 834 | legalinfo.mn | https://huggingface.co/datasets/endomorphosis/ipfs_mongolia_laws | ok |
| uganda | ug | 40 | 37 | parliament.go.ug PDFs | https://huggingface.co/datasets/endomorphosis/ipfs_uganda_laws | ok |
| kosovo | xk | 13 | 237 | GZK gzk.rks-gov.net ASP.NET PDFs | https://huggingface.co/datasets/endomorphosis/ipfs_kosovo_laws | ok (slow postback; small set) |
| jamaica | jm | 40 | 23 | moj.gov.jm PDFs | https://huggingface.co/datasets/endomorphosis/ipfs_jamaica_laws | mixed (CPR + JP lists/forms) |
| senegal | sn | 43 | 1202 | JO via archives.sn / jo.gouv.sn CDX | https://huggingface.co/datasets/endomorphosis/ipfs_senegal_laws | ok (archives.sn hosts JO) |
| nepal | np | 32 | 1385 | lawcommission.gov.np uploads | https://huggingface.co/datasets/endomorphosis/ipfs_nepal_laws | ok (incl. Constitution) |

**Batch 2 new datasets:** 10
**Batch 2 law rows:** 393
**Batch 2 article rows:** 12865
**Combined new this overall run:** 18 datasets

## Priority batch 1 blockers / partials

- **serbia**: PIS SPA shell live; Wayback of ELI /reg mostly short shells. 1 pravilnik recovered.
- **albania**: QBZ Angular SPA live; Wayback ELI ligj snapshots are shells. No WAF bypass.
- **bosnia**: Docs portal login-walled; CDX PDFs were forms/annexes not gazette laws.
- **montenegro**: sluzbenilist.me detail pages archive to login wall (Prijavite se).
- **georgia**: matsne.gov.ge Access Denied WAF live; Wayback also challenge/Access Denied.
- **moldova**: legis.md Cloudflare challenge live; not bypassed.
- **tunisia**: iort/legislation.tn TLS fail; Wayback OCR/session junk; only 2 weak rows kept.
- **tanzania**: parliament.go.tz timeouts; collector hung before catalog.
- **usa**: SKIPPED per request.

## Batch 2 notes / skips

- **kyrgyzstan**: cbd.minjust.gov.kg SPA shell (~2KB); not collected.
- **azerbaijan**: e-qanun.az Next.js SPA; framework pages lack body text without client API.
- **namibia lac.org.na**: NGO annotated statutes — skipped (not official gazette).
- **jo.gouv.sn live**: TLS/timeouts; Senegal used archives.sn official JO mirrors + CDX.

## Collectors added

Under `~/.ipfs_datasets/legal_collectors/scrapers/`:
`world_lib.py, collect_{am,al,ba,mk,me,md,ge,rs,ec,bo,py,pa,dz,tn,et,tz,is,xk,uz,rw,by,mn,np,jm,ug,sn}.py`
Packager: `~/.ipfs_datasets/legal_collectors/world_package.py`

## Method notes

- Official national gazette / legislation portals only.
- Live official URL first; Wayback of the same official URL on failure.
- No WAF bypass, no commercial consolidators, no bulk WARC.
- PDF text via pdftotext; raw PDF bytes rejected after extractor fix.

- disk_free: 112G (used 7.6G / 126G)


## Deepen XK/JM + creates — 2026-09-04 13:08 PT

Skipped USA. Did not touch SN/RW/UG (Scraper). Africa Batch A not scraped this run.

### Deepen high-thin (verified HF tip)

| Country | CC | Before L / A | After L / A (HF) | Source | URL |
| --- | --- | ---: | ---: | --- | --- |
| kosovo | xk | 13 / 237 | **90 / 1780** | GZK gzk.rks-gov.net ActDetail PDFs | https://huggingface.co/datasets/endomorphosis/ipfs_kosovo_laws |
| jamaica | jm | 40 / 23 (careers/adverts contaminated) | **103 / 723** | MOJ `/sites/default/files/laws/` + laws.moj.gov.jm legislation | https://huggingface.co/datasets/endomorphosis/ipfs_jamaica_laws |

**Net deepen (XK+JM):** laws 53 → 193 (+140); articles 260 → 2503 (+2243).

### Creates this run (verified HF tip)

| Country | CC | L / A | Source | URL |
| --- | --- | ---: | --- | --- |
| honduras | hn | **40 / 529** | TSC tsc.gob.hn/web/leyes La Gaceta PDFs | https://huggingface.co/datasets/endomorphosis/ipfs_honduras_laws |
| georgia | ge | **19 / 2188** | matsne.gov.ge PDF | https://huggingface.co/datasets/endomorphosis/ipfs_georgia_laws |
| moldova | md | **60 / 0** | legis.md State Register (Wayback HTML; thin article splits) | https://huggingface.co/datasets/endomorphosis/ipfs_moldova_laws |

### Collector notes

- **XK:** Preferential SearchIn + dense ActID bands near known text PDFs; inheritance notices skipped; pdfplumber then pdftotext; many GZK PDFs remain image-only (`pdf_short_or_scan`). Ligji/Kodi including Penal Code 06/L-074 landed.
- **JM:** Quarantined careers/adverts/JP lists; CDX/http Wayback of official MOJ law paths only; `archive_fallbacks` WAYBACK_* switched to `http://web.archive.org` after https SSLEOF.
- **HN/GE/MD:** Official gazette/portal PDFs; AL/RS create attempts this run yielded 0 (Wayback bodies unusable / fail-all) — left for later.
- Disk ~111G free; no WAF bypass; no cylaw; no bulk WARC; CDX small limits.

### Parallel note

Other agent concurrently published AZ/ME/TN/GT/FJ/CU/KH/DO (and Africa CM/AO scrapes). Those were not re-touched here beyond gap refresh.

## PDF parse deepen (ipfs_datasets_py) — 2026-09-04 1:25 PM PT

Goal: IntegratedPDFProcessor-style extraction (pdfplumber → pymupdf → pdftotext → tesseract OCR) + honest article/section splits; re-upload thin PDF-backed tips.

| Country | CC | Before L / A (HF tip) | After L / A | OCR used? | URL |
| --- | --- | ---: | ---: | --- | --- |
| El Salvador | sv | 35 / 0 | **26 / 642** | yes (19/26 decretos) | https://huggingface.co/datasets/endomorphosis/ipfs_elsalvador_laws |
| Tunisia | tn | 40 / 0 | **41 / 21** | yes (2 image PDFs) | https://huggingface.co/datasets/endomorphosis/ipfs_tunisia_laws |
| Ethiopia | et | 58 / 19 | **58 / 19** | no | https://huggingface.co/datasets/endomorphosis/ipfs_ethiopia_laws |
| Jamaica | jm | 40 / 23 (later tip ~103/723) | **122 / 1047** | no | https://huggingface.co/datasets/endomorphosis/ipfs_jamaica_laws |
| Fiji | fj | 38 / 25 | **38 / 444** | yes (1 Hindi const. try) | https://huggingface.co/datasets/endomorphosis/ipfs_fiji_laws |
| Sri Lanka | lk | deferred (image Acts) | **8 / 33** (new) | yes (6 Acts) | https://huggingface.co/datasets/endomorphosis/ipfs_srilanka_laws |
| Laos | la | deferred / 2 local | **2 / 0** local only — not packaged | partial | — |

### Method / tooling

- `scrapers/pdf_extract_lib.py` — mirrors `ipfs_datasets_py` `IntegratedPDFProcessor` (pdfplumber first, OCR fallback via pymupdf render + tesseract).
- `scrapers/deepen_sv_pdf.py` — replaced 1847 Diario garbage scans (quarantined) with Asamblea Constitución + decretos (Wayback `http://web.archive.org/...id_/`); honest `Art. N` splits.
- `scrapers/reprocess_pdf_articles.py` — in-place re-split for tn/et/fj/jm/la; PNG junk quarantined (TN); JM sample-letter/HR junk quarantined.
- Honest splits only (≥2 heading matches); no invented boundaries.
- README matches parquet on all uploads (verified staging).

### Blockers

- **SV modern Diario Oficial:** Wayback CDX only has 1847–1854 scans for `diariooficial.gob.sv/diarios/` — no modern gazette PDFs in CDX; used Asamblea instead. Jurisprudencia DocumentosBoveda = court cases (skipped).
- **TN:** Most JO PDFs lack line-start `الفصل` structure after bidi noise; only 1 instrument yielded honest fasl splits (21 arts).
- **ET:** Bilingual Negarit layout; line-start Article/አንቀጽ still sparse — tip held at 58/19 (no regression).
- **LA:** One instrument is HTML mislabeled; other is annex/product list without article headings; OCR not helpful for honest splits — not uploaded.
- **LK:** Many 1980 Acts are image-heavy; OCR yields text but few honest Section heads; Constitution (parliament.lk) carries the article count.
- Disk free ~111G throughout; no WAF bypass; no cylaw; did not touch SN/RW/UG; did not regress IS 917 / IT 6314/1265 / AM/PY/BG/CY.

### New helpers

- `scrapers/pdf_extract_lib.py`, `scrapers/deepen_sv_pdf.py`, `scrapers/reprocess_pdf_articles.py`, `scrapers/collect_lk.py`

## CREATE rs/ba/al/tz — 2026-09-04 13:36 PT (local package only; no HF upload)

| Country | CC | L / A | Source | Staging | Gaps/blockers |
| --- | --- | ---: | --- | --- | --- |
| tanzania | tz | **60 / 1329** | OAG MIS acts-ajax + `/portal/acts/{id}/download` live PDFs | `~/.ipfs_datasets/legal_collectors/staging_tz` | parliament.go.tz still times out; used OAG instead |
| serbia | rs | **66 / 1037** | PIS viewdoc Wayback PDFs + parlament.gov.rs `/upload/.../zakoni/` live PDFs | `~/.ipfs_datasets/legal_collectors/staging_rs` | Live PIS SPA; many CDX viewdoc PDFs image-only (`pdf_extract_failed`); Assembly PDFs filled catalog |
| albania | al | **60 / 3120** | QPZ `botime/fletore_zyrtare` official FZ PDFs via Wayback | `~/.ipfs_datasets/legal_collectors/staging_al` | Live QBZ Angular SPA / ELI shells; used predecessor official QPZ static PDFs |
| bosnia | ba | **50 / 2764** | sluzbenilist.ba `/page/PdfDownload` live + CDX | `~/.ipfs_datasets/legal_collectors/staging_ba` | Docs portal login-walled; oversized issues (>28MB) skipped; prior forms/index junk cleared |

META entries present in `world_package.py`. Collectors updated under `scrapers/collect_{rs,ba,al,tz}.py`. Did not touch mz/zw/bw. No WAF bypass. No HF upload.


## Completeness deepen IT/AZ — 2026-09-04 13:55 PT (local staging only; NO Hub upload)

User dismissed HF upload approvals — packages left under staging_*.

| Country | Before (HF tip) | After (local staging) | Path | Notes |
| --- | ---: | ---: | --- | --- |
| italy | 6314 / 1265 | **8626 / 4390** (still growing) | `~/.ipfs_datasets/legal_collectors/staging_it` | Catalog extended 2006–2026 → 204768; Normattiva bodies newest-first; text≥80 |
| azerbaijan | 36 / 100 | **383 / 682** | `~/.ipfs_datasets/legal_collectors/staging_az` | e-qanun downloadDetailPdf Wayback+ID probe; SPA skipped |

Italy collector still running (MAX_NEW=5000). TN/ET/SV/DO owned by Scraper. No Hub push this wave.


### IT/AZ checkpoint refresh — 2026-09-04 14:04 PT

| Country | HF tip before | Local staging now | Path |
| --- | ---: | ---: | --- |
| italy | 6314/1265 | **9318/5130** (collector still running toward +5000) | `~/.ipfs_datasets/legal_collectors/staging_it` |
| azerbaijan | 36/100 | **385/682** | `~/.ipfs_datasets/legal_collectors/staging_az` |

No Hub upload (approvals dismissed). Catalog IT=204768. Disk ~108G free.


### IT/AZ local packages — 2026-09-04 14:20 PT (NO Hub upload)

| Country | Before (HF) | After (staging) | Path | URL (unchanged tip) |
| --- | ---: | ---: | --- | --- |
| italy | 6314/1265 | **10827/7099** (collector still running ~2586/5000 this slice) | `~/.ipfs_datasets/legal_collectors/staging_it` | https://huggingface.co/datasets/endomorphosis/ipfs_italy_laws |
| azerbaijan | 36/100 | **385/682** | `~/.ipfs_datasets/legal_collectors/staging_az` | https://huggingface.co/datasets/endomorphosis/ipfs_azerbaijan_laws |

Notes: IT catalog extended 2006–2026 → 204768 entries; bodies newest-first Normattiva dettaglio-atto; text≥80 (short abrogated excluded). AZ e-qanun downloadDetailPdf Wayback. TN/ET/SV/DO not scraped (Scraper-owned). Disk ~107G free.


## IT/AZ deepen report — 2026-09-04 14:46 PT (local only; Hub upload deferred)

| Country | Before | After (staging) | Path |
| --- | ---: | ---: | --- |
| italy | 6314/1265 | **12798/8274** | `~/.ipfs_datasets/legal_collectors/staging_it` |
| azerbaijan | 36/100 | **452/813** | `~/.ipfs_datasets/legal_collectors/staging_az` |

HF tips unchanged (no upload). Italy collector may still be running. Disk ≫20G free.


## IT/AZ deepen FINAL report — 2026-09-04 14:48 PT (local staging; Hub upload deferred)

| Country | Before (HF tip) | After (local staging) | Path | Tip URL (unchanged) |
| --- | ---: | ---: | --- | --- |
| italy | 6314/1265 | **12979/8432** | `~/.ipfs_datasets/legal_collectors/staging_it` | https://huggingface.co/datasets/endomorphosis/ipfs_italy_laws |
| azerbaijan | 36/100 | **505/854** | `~/.ipfs_datasets/legal_collectors/staging_az` | https://huggingface.co/datasets/endomorphosis/ipfs_azerbaijan_laws |

Method: IT Normattiva OpenData dettaglio-atto; catalog extended 2006–2026 → 204768; text≥80. AZ e-qanun downloadDetailPdf Wayback. No Hub push (user dismissed approvals). TN/ET/SV/DO not touched (Scraper-owned). Disk ≫20G free.


## IT/AZ honest package — 2026-09-04 14:50 PT (NO Hub upload)

| Country | Before (HF) | After staging (text≥80) | Path |
| --- | ---: | ---: | --- |
| italy | 6314/1265 | **10886/8458** | `~/.ipfs_datasets/legal_collectors/staging_it` |
| azerbaijan | 36/100 | **505/854** | `~/.ipfs_datasets/legal_collectors/staging_az` |

Italy slice-1 done (+4770 bodies); slice-2 running. Catalog 204768. README=parquet. Tip URLs unchanged until parent uploads.


## Executor report IT/AZ — 2026-09-04 14:59 PT

**No Hub upload** (approvals dismissed). Packages ready for parent.

| Country | Before (HF tip) | After (local staging, text≥80) | Path | Tip URL |
| --- | ---: | ---: | --- | --- |
| italy | 6314/1265 | **11133/8833** (collector still running) | `~/.ipfs_datasets/legal_collectors/staging_it` | https://huggingface.co/datasets/endomorphosis/ipfs_italy_laws |
| azerbaijan | 36/100 | **605/1027** | `~/.ipfs_datasets/legal_collectors/staging_az` | https://huggingface.co/datasets/endomorphosis/ipfs_azerbaijan_laws |

- IT catalog extended 2006–2026 → **204768** entries; slice-1 +4770 bodies done; slice-2 running (short abrogated saved but excluded from package).
- AZ: e-qanun.az `downloadDetailPdf` via Wayback + ID probe; SPA skipped.
- Did **not** scrape TN/ET/SV/DO (Scraper-owned). No USA. Iceland untouched.
- Disk ~107G free.
