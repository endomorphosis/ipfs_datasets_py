# World scrape status

- updated: 2026-09-04 11:51 PT
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

Under `/workspace/legal_scrapers/scrapers/`:
`world_lib.py, collect_{am,al,ba,mk,me,md,ge,rs,ec,bo,py,pa,dz,tn,et,tz,is,xk,uz,rw,by,mn,np,jm,ug,sn}.py`
Packager: `/workspace/legal_scrapers/world_package.py`

## Method notes

- Official national gazette / legislation portals only.
- Live official URL first; Wayback of the same official URL on failure.
- No WAF bypass, no commercial consolidators, no bulk WARC.
- PDF text via pdftotext; raw PDF bytes rejected after extractor fix.

- disk_free: 112G (used 7.6G / 126G)
