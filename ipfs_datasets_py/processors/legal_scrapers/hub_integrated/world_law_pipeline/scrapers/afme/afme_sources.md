# afme lane — source survey (recreated 2026-10-18 after the second reboot wiped out/afme and the scripts)
Waves 1–8 sections were lost with the reboot. Their output is safe: every staged afme file listed in staging/afme/_logs/staged_*.json
is in state/confirmed_batches/afme.jsonl (4,531 files) except 2 PR files (142 rows). Wave 8 chains did not survive the reboot; see README_resume.md.

## Wave 9 (2026-10-18)
### AU council local laws (afme owns all AU councils; Asia & LatAm will not crawl AU again)
- Places: 540 AU municipalities in global_municipalities_candidate.csv; 478 with an official site and not covered.
  Skipped (covered, on the Hub via asia_latam batches au_qld_ll-p0 / archive2026…): 48 QLD councils.
  The 7 QLD councils from Asia & LatAm's Wayback pass (wd:Q1069375 Q1053796 Q1069401 Q807974 Q1065012 Q1070208 Q1065065) are live-crawled only;
  852 Hub doc_ids/URLs for them are excluded (out/afme/AU_hub_exclude.tsv). They get no archived copies. Q807896 is treated as uncovered.
- Live crawler out/afme_au_live.py: RFC 9309 robots (404 = allow; 403/5xx/timeout/HTML robots = skip host), crawl-delay max(robots, 3 s) per host,
  homepage + sitemap + local-law/policy pages (≤25 pages per council), ≤40 docs per council. Takes local laws, subordinate local laws, SA by-laws, and NSW local approvals/orders policies.
  Excludes LEP/SEPP/planning schemes, forms, drafts, consultation material, and manuals. Maps to council place rows only (never iso:AU-*).
  doc_type: ordinance (local law/by-law), regulation (subordinate/policy). Scans go to the OCR queue as metadata-only rows.
- 20-council test: 14 files, 95 rows, 0 bad (91 full text, 4 scans). About 25% of councils are unreachable or robots-blocked (403/TLS/timeouts); these are candidates for CC fallback.
- State gazettes (out/afme_aus_gaz.py, ≥3 s/host, council local laws only, mapped by council name in the notice head → council site host → body; LEP/SEPP/planning-scheme dropped; non-council bodies unmapped → dropped):
  - VIC www.gazette.vic.gov.au (robots Allow /; disclaimer = standard Crown copyright notice): General gazettes GG{Y}G{NNN}.pdf, s74 LGA 2020 / s119 LGA 1989
    notices of making/amending/revoking local laws (proposed-law notices skipped), doc_type gazette_act, one row per notice. Test 2022 (45 issues): 11 rows 0 bad, re-test after a mapping/segmentation fix queued.
  - WA legislation.wa.gov.au (robots 404 = allow; content CC BY 4.0): gazette PDFs by year (gazettes{Y}.html), local laws under LGA 1995 published in full;
    one row per local law. Since 1 Jul 2023 most subsidiary legislation moved off the gazette, but council local laws are still gazetted. Test 2021–22 (120 issues): 27 rows / 9 councils, 0 bad.
  - Full runs 2000–2026 queued after chain A (afme_w9_gaz_chain.sh).
  Other gazettes: SA governmentgazette.sa.gov.au and legislation.nsw.gov.au
  are behind a Cloudflare challenge (skip); TAS gazette disallows /*.pdf and /editions (skip); QLD publications.qld.gov.au disallows /storage/ (gazette PDFs; skip).
### Lusophone Africa
- MZ: council sites cmmaputo.gov.mz (posturas + BR III série, robots allow), cmnampula.gov.mz (Código de Posturas 2021), municipiobeira, cmnacala (nothing found).
  The Boletim da República (inm.gov.mz) is a paid shop: not crawled.
- CV: boe.incv.cv "Parte G – Autarquias locais" (49 listing pages × 100 acts, entity = município, act PDFs with a text layer). robots.txt 404 = allow; terms §6 forbid copying
  without INCV authorisation, and Benjamin approved crawling anyway (2026-10-18). out/afme_cv_boe.py: ≥5 s, plain GET, stops on CAPTCHA. Only normative acts are kept (posturas, códigos, regulamentos, tabelas de taxas,
  regimentos, planos detalhados/urbanísticos); personnel acts are excluded. Rows tagged source_policy=site_terms_no_copy_user_approved + source_policy_raw (§6 text + URL).
  Test (8 listing pages): 18 rows / 12 municípios, 0 bad. Full run running (chain D).
  Council sites: cmrb.cv (Código de Posturas). Most others are dead, TLS-broken or robots-403, so they go to the CC/Wayback fallback (out/afme_lus_arch.py, 1 archive worker).
- AO: only provincial-government sites (gov.ao provinces); there are no municipal sites, and the Diário da República is paid. Nothing municipal to take.
- GW, ST: no public municipal sources found.

## Wave 10 (2026-10-20)
- AU archived fallback for 103 unreachable/robots-blocked councils: CC index (prefix queries; wildcard 504s) then Wayback CDX (mimetype pdf), tagged cc_/wayback_archive_fallback.
- NZ council websites (bylaws pages), 69 councils not covered by eap: live, RFC 9309, ≥3 s per host.
- Checked and found low-yield: the Laws.Africa LIIs for ZW/NA/LS/SZ/GH/SL/NG/SC (national AKN only). PacLII (paclii.org) gave no response (connect timeout) and has no by-law collections for VU/FJ.
