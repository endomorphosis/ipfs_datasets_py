# States & Provinces lane (`states`)

Adm1 law (state / province / territory / Land / canton / region) -> `endomorphosis/world_national_law` via run_loop.
* Code: `pipeline/scrapers/states/` (this dir). Venv: `/workspace/world_law/pipeline/venv`.
* Staging: `staging/states/<CC>/iso_<ISO3166-2>.<source>-<UTC>.jsonl` (SCHEMA.md v1.2.0, `place_id iso:CA-ON`,
  `admin_level adm1`, atomic dot-file -> `validate_file` -> rename; never rewritten). Rejected files: `staging/states/_rejected/`.
* Logs/reports: `staging/states/_logs/`. Archive lane name: `ARCHIVE_LANE=states` (shared pipeline/archive limiter + breaker).
* Scanned (image-only) PDFs: NOT OCR'd. Queued in `staging/states/_scanned_pdfs_manifest.jsonl` (same format as
  asia_latam/eap manifests read by `ocr/pdf_collect.py`), for World Law OCR to pick up.
* UA: `WorldLawStatesBot/0.1 (+https://github.com/endomorphosis/ipfs_datasets_py; ...)`; RFC 9309 robots; >= max(2 s, Crawl-delay)
  per host; challenge pages (Cloudflare/CloudFront) stop the source, never bypassed. Guards: RSS <= 900 MB, free disk >= 35 GB.

## Sources prepared (test batch, not yet run)
| key | jurisdiction | host | robots | licence | discovery |
|---|---|---|---|---|---|
| ca_on_elaws | iso:CA-ON | www.ontario.ca/laws/statute/ | allowed, Crawl-delay 1 | ON legal materials exempt | Wayback CDX url list (`data/on_statute_cdx_20261018.txt`, 962 ids) |
| ca_mb_ccsm | iso:CA-MB | web2.gov.mb.ca/laws/statutes/ccsm/ | robots -> 404 page => allow (RFC 9309) | OpenMB licence | index_ccsm.php (516 ids) |
| au_qld_leg | iso:AU-QLD | www.legislation.qld.gov.au/view/xml/ | /view/xml allowed; /view/pdf disallowed | CC BY 4.0 | sitemap.xml + feed?id=crawler (72 ids) |

Run: `venv/bin/python run_test.py` (dry run: robots only) / `--live --limit 30 --on-cdx-file data/on_statute_cdx_20261018.txt`.

## Robots/terms notes (2026-10-17 PT)
Disallow-all for our UA (archive-only candidates): bclaws.gov.bc.ca (Google/Bing only), kings-printer.alberta.ca.
Cloudflare/CloudFront challenge (not bypassed; archive-only): legislation.nsw.gov.au, legislation.sa.gov.au,
legisquebec.gouv.qc.ca, laws.yukon.ca. CanLII: non-official aggregator, skipped per brief (terms not reviewed).
Allowed: legislation.vic.gov.au (Crawl-delay 2, file downloads disallowed), legislation.tas.gov.au, legislation.nt.gov.au,
legislation.act.gov.au (Crawl-delay 10, /View/ and /html/ disallowed), nslegislature.ca (Crawl-delay 10, statutes are PDFs),
laws.gnb.ca (showVersion/showPdf disallowed), assembly.nl.ca, princeedwardisland.ca, justice.gov.nt.ca (EN files).

## Review workflow
`run_test.py --live --review` stages into `staging/states/_review/<CC>/` (uploader-ignored); after eyeballing, `common.promote(path)`
re-validates and renames into `staging/states/<CC>/` (same FS, atomic).

## Test batch 2026-10-17 PT (promoted 22:29 PT)
* `CA/iso_CA-ON.ca_on_elaws-20261018T052605Z.jsonl` 30 rows (18 consolidated, 3 repealed final consolidations in_force=false, 9 private Pr acts as enacted)
* `CA/iso_CA-MB.ca_mb_ccsm-20261018T052706Z.jsonl` 30 rows (EN column only; 19 bilingual pages had FR columns dropped)
* `AU/iso_AU-QLD.au_qld_leg-20261018T052843Z.jsonl` 30 rows (28 acts, 2 SL)
Known gaps: ON CDX ids include junk/404 slugs and pages without WordSection (repealed stubs); QLD sitemap/feed ids for
repealed/expired titles 404 on /inforce/current/ (need point-in-time URL from the feed instead).

## Phase 3: full CA + AU (started 2026-10-17 PT)
Runner: `run_full.py --source <key> [--test 20]` (adapters in `adapters.py`). A `--test` run writes one chunk to
`staging/states/_review/<CC>/` and stops; after eyeballing, `promote_review.py <key>` moves it into `staging/states/<CC>/`,
and then the full run (no flags) stages 150-row chunks to `_review` and promotes each one after validation and QC.
Done state: `staging/states/_state/<key>.done.tsv` (dedupe by doc_id; seeded from already-staged files).

| key | place | source | discovery | notes |
|---|---|---|---|---|
| ca_on_elaws | CA-ON | ontario.ca/laws (live) | Wayback CDX URL list (listing page is a Radware JS shell) | repealed/source-law pages skipped; regs need `data/on_regulation_cdx_full.txt` (split CDX, `cdx_split.sh`) |
| ca_mb_ccsm | CA-MB | web2.gov.mb.ca/laws | index_ccsm.php + regs/index.php | French column removed |
| au_qld_leg | AU-QLD | legislation.qld.gov.au /view/xml | projectdata in-force PIT browse | CC BY 4.0 |
| au_tas_leg | AU-TAS | legislation.tas.gov.au /view/xml | projectdata in-force PIT browse | CC BY 4.0 + attribution text |
| au_nt_leg | AU-NT | legislation.nt.gov.au | Acts + SL By-Title?status=inforce | PDF text layer (pdftotext); scanned PDFs go to the OCR manifest |
| ca_nb_laws | CA-NB | laws.gnb.ca /en/document/ | chapters?selection=all (statutes + regs) | robots disallows showVersion/pdf/search; King's Printer non-commercial licence plus a conditional commercial licence |
| ca_nt_justice | CA-NT | justice.gov.nt.ca consolidation PDFs | /en/legislation/ file browser | only the English column of the bilingual PDFs is kept (left-half crop); non-commercial licence |
| ca_nl_assembly | CA-NL | assembly.nl.ca | titleindex + regs index | **TERMS HOLD**: HOA copyright statement permits excerpt/cite only; test batch kept in `_review` |

Blocked or held (no collection):
* AU-VIC: text is only in content.legislation.vic.gov.au (robots `Disallow: /`), and the terms say "personal use only". Blocked.
* CA-NS: nslegislature.ca says "provided for your convenience and personal use only". Terms block (PDF pipeline not run).
* CA-SK: King's Printer requires a written request for copyright release ("does not authorize unlimited ... reproduction"). Terms block.
* CA-PE: HTML pages answer with a Radware bot page (no bypass). The PDFs under /sites/default/files/legislation/ are not challenged; discovery would have to come from a CDX URL list (pending).
* AU-ACT: robots disallows /results (the browse endpoint), /View/ and /html/. Allowed: /a/<id>/, /sl/<id>/ and /DownloadFile/. Discovery comes from a Wayback CDX URL list (split by year, pending); Crawl-delay 10.

### Status 2026-10-17 23:55 PT
Totals staged (counting staging plus processed/): AU-QLD 999, AU-TAS 1970, AU-NT 689, CA-MB 1605, CA-NB 1296, CA-NT 803, CA-ON 1381 (regs run in progress).
Ontario regs: IDs come from 4 cached CDX pages (2,679 IDs, up to R.R.O. 900598). `cdx_list.py` is fetching the remaining sub-prefixes (9006–903, 91–99).
ACT: `act_after_cdx.sh` waits for `cdx_list.py` (a/ and sl/ by year), then runs a 20-row test into _review (held for review).

### Decisions 2026-10-17 23:52 PT (coordinator)
* **Blocked by terms, no collection (live or archived):** CA-NS, CA-SK, CA-PE, CA-NL. The NL 20-row test stays in `_review/CA/` (do not promote).
* AU-VIC: robots-disallowed, so archive copies only (shared module, `archived_robots_disallowed`, with copy date). Added to the archive queue.
* The AT/ID/IN/DE files in staging/states/ belong to the lane's second worker (National handover plus German Länder). It shares ARCHIVE_LANE=states. Do not touch its files.
* Archive queue (Common Crawl first, to spare Wayback): BC, AB, NSW, SA, QC (LégisQuébec), YT, VIC.

### Unattended jobs (2026-10-18 00:45 PT). Run `./status.sh` for counts and health
* `run_full.py --source ca_on_elaws`: Ontario regulations pass (2,689 IDs).
* `cdx_list.py` chain: ACT a/ and sl/ by year, then the remaining Ontario regulation sub-prefixes, written to `data/on_regulation_cdx_extra.txt`.
* `on_regs_rerun.sh`: after both of the above, copies the extra list to `on_regulation_cdx_full.txt` and reruns ca_on_elaws (dedupes via done.tsv).
* `act_after_cdx.sh`: ACT 20-row test into _review, **held for manual spot-check** before `promote_review.py au_act_leg` and the full run.
* `archive_discovery.sh`: Wayback URL lists for NSW, QC, BC, YT, AB, SA and VIC.
* `archive_tests.sh`: 20-row archive test per source into _review, **held** for review.
Common Crawl has no usable captures for these hosts. CCBot obeys their robots.txt or gets 403 challenges (checked: NSW is all 403; BC/NSW/SA/YT return 0 captures with status 200), so every archive source depends on Wayback.
Archive adapters (`*_archive` in adapters.py) use a generic HTML/PDF text extractor; tune the per-source XPaths after the first test rows.

## Phase 4: Swiss cantons + Italian regions (started 2026-10-18 00:45 PT)

### CH: all 26 cantons via LexFind (`ch_lexfind_<abbr>`, place `iso:CH-XX`)
- LexFind (lexfind.ch) is run for the Swiss State Chancellors' Conference (SSK) by Sitrox, with legal work by ZRI. It is one shared platform for every canton. robots.txt is empty (allow all). The site has no terms of use beyond a disclaimer, and Swiss legislative texts are not protected by copyright (Art. 5 para. 1 lit. a URG).
- Listing: `GET /api/frontend/v1/<lang>/entities` (ids), then `/entities/<id>/systematics?active_only=true&tols_for_systematics[]=<sys ids>`. This returns the active texts of law with title, systematic number and category.
- Text: `GET /tol/<tol_id>/<lang>` returns the newest version as a PDF copy of the cantonal SGS text. We use the pdftotext text layer; nothing is OCR'd, and scanned PDFs go to the OCR manifest.
- Language is set per record. Bilingual and trilingual cantons are fetched once per language (BE de/fr, FR fr/de, VS fr/de, GR de/it/rm). A language check skips texts that come back in another language. doc_id = `ch_<abbr>:<tol_id>:<lang>`.
- Category 9 (Gemeindeerlass) is excluded because it belongs to the municipal lane. Categories map to doc_type statute/regulation/decision; the LexFind category name goes to extra_metadata.
- Runner: `ch_full.sh` runs one canton after another in a single process, so the 2 s/host spacing holds. Resumable via `_state/ch_lexfind_<c>.done.tsv`; progress in `_logs/ch_full.out`.

### IT regions
| Region | Key | Source | Licence | Status |
|---|---|---|---|---|
| IT-45 Emilia-Romagna | it_er_demetra | Demetra weekly bulk zips (NIR XML of testi vigenti, legislatures I-XII; `data/it_er/dl.sh`) | CC BY 4.0 | done: 926 in force (1,159 repealed skipped) |
| IT-52 Toscana | it_tos_raccolta | Raccolta Normativa: URNs from the CC BY 3.0 bulk AKN zips (leg. I-X), current text from `articolo?urndoc=...&pr=idx,0;artic,1;articparziale,0` | CC BY 3.0 / "liberamente utilizzabili citando la fonte" | full run (3,952 URNs; repealed skipped) |
| IT-25 Lombardia | it_lom_crl | List from the CC0 Socrata dataset dati.lombardia.it `abjw-hhay` (stato_legge=vigente; laws and regs), text as NIR XML from normelombardia `xmain_xml.aspx` | CC0 (list) / CRL | full run (2,454 vigente; metadata-only entries skipped) |
| IT-78 Calabria | it_cal_crc | Consiglio regionale open data: `bdf/api/CTG?Legislatura=1..13` XML lists (dati.gov.it, CC BY 4.0); text `bdf/api/BDF?numero=&anno=&tipo=TXT` (testo vigente, plain text) | CC BY 4.0 | full run (1,190 listed; robots Request-rate 1/30 s honoured) |
| IT-62 Lazio | it_laz_crl | Consiglio regionale: per-year lists `?vw=leggiregionali&sv=vigente`, detail `?vw=leggiregionalidettaglio&id=&sv=vigente` (testo coordinato; older laws in a plain table) | site CC BY-NC-SA 2.0 IT + art. 5 L. 633/1941 | full run (2,531 listed; laws whose note says "Legge abrogata" skipped) |
| IT-36 Friuli VG | it_fvg_lexview | Lexview `fontinormative/xml/xmlLex.aspx?anno=&legge=` (testo vigente, div.NIR). Index is a postback tree, so (year x 1..90) is enumerated and a year stops after 6 misses (skip_beyond_end, no request) | art. 5 (avviso legale: unofficial reproduction) | full run |
| IT-57 Marche | it_mar_crm | Consiglio regionale `cronologico.php?arc=vig&anno=` + `dettaglio.php?arc=vig&idl=` (testo vigente, laws and regs; 'Abr.' entries skipped) | site "Note legali": personal/non-commercial download "salvo diversa indicazione"; text public domain under art. 5 (license_note) | full run (2,321 listed) |
| IT-88 Sardegna | it_sar_bdg | Banca dati giuridica JSON `regional-laws/front-office/search` (2,607 laws) + born-digital PDF `/<id>/files/pdf` (coordinated text from AKN) | art. 5 | full run |
| IT-TN Trento | it_tn_codprov | Codice provinciale: the public search's own endpoint `SearchControl/CodiceProvinciale_response.aspx` (read-only POST, 3,171 acts) + `DetailControl/CodiceProvinciale_response.aspx` info/ultimotesto (HTML). Robots-disallowed `/doc/clex_*.pdf` never fetched; state acts and recepted regional acts skipped; "a termine scaduto"/abrogato skipped | art. 5 | full run |
| IT-75 Puglia | it_pug_bussola | Bussola Normativa: 'Ricerca semplice' per year x {leggi, regolamenti} (ASP.NET postback + result pages), text `LeggeNavscroll.aspx?id=` (follows the VIGENTE version; 'Abrogato: Si' skipped) | art. 5 | full run (2,722 listed; text = enclosing cell of lblTesto, whose HTML is malformed) |

Notes and blocks:
- Normattiva: the national Open Data API (api.normattiva.it, CC BY 4.0) has national acts only. Regional acts sit in "Normattiva Regioni" (`/mfr/`), a federated search whose `/mfr/ricerca/` is disallowed in robots.txt, so we do not use it. dati.normattiva.it answers our UA (even on robots.txt) with an IPZS protection block (409).
- Veneto (consiglioveneto.it): Akamai "Access Denied" (403), even on robots.txt. Blocked, no bypass.
- Piemonte (arianna.cr.piemonte.it): Arianna data is CC BY-NC-SA 3.0 IT. robots.txt disallows /dwd/, /allegati/, /htmlregolamenti/ and /leggistatutarie/. The server times out intermittently, so the adapter is pending.
- Toscana post-2020: `tos_post2020.py` lists `urn:nir:regione.toscana:<tipo>:<year>-` captures from Common Crawl + Wayback (shared archive module, URL lists only; text is fetched live) into `data/it_tos/urns_post2020.tsv`; `ToscanaRN.discover` merges it; `tos_after.sh` resumes the Toscana run (first chunk held) when discovery and the current run finish.
- Piemonte: still unreachable (arianna.cr.piemonte.it and api.smartdatanet.it time out from this network, 2026-10-18 01:40 PT). Licence decision recorded: CC BY-NC-SA OK with license_note (art. 5), avoid /dwd/.
- Veneto: no alternative official dataset found (dati.gov.it has no Veneto law dataset; bur.regione.veneto.it gives 403 on the service root). Stays blocked.
- Bolzano: lexbrowser.provinz.bz.it robots `Disallow: /`; the TAA BUR (bollettino.regione.taa.it) also disallows /it/ and /de/ for all agents (plus DisallowAITraining). Archive-only candidate.
- Trentino-Alto Adige (regione.taa.it): act pages are allowed but the listing is loaded from /api/ (disallowed); no static list or sitemap entries. Pending.
- Sicilia: w3.ars.sicilia.it allows search pages (only /app/, /icaro/ etc. disallowed); historical texts only (coordinated texts are ARS-internal). Pending adapter. GURS unreachable.
- Basilicata: atticonsiglio.consiglio.basilicata.it (AD_Elenco_Leggi, testi coordinati) unreachable from here; consiglio.basilicata.it reachable. Pending.
- Valle d'Aosta: consiglio.vda.it (leggi e regolamenti since 1950, it/fr) unreachable from here. Pending retry.
- Liguria: Crawl-delay 600 on www.regione.liguria.it, lrv.regione.liguria.it 403. Pending.
- Abruzzo, Campania (consiglio), Molise (consiglio), Umbria: hosts time out from this network. Retry later.

### Fixes (2026-10-18)
- `run_full.py`: rows that fail schema validation are now logged to qc_rejects and NOT marked done. Before, they were silently dropped and marked. No earlier CA/AU run had validation errors.
- `run_full.py`: sleeps 1.1 s after each promote. Batch tags have 1 s resolution, and a fast local source (ER) collided on a file name.

### Disk floor / HF stall (2026-10-18 01:55 PT)
- `common.check_guards()` no longer raises on low disk: below STATES_MIN_FREE_GB (35) it logs to stderr and `_logs/DISK_FLOOR_HIT.log`, then sleeps (STATES_DISK_PAUSE_S, 300 s) and re-checks until free >= floor. Nothing is deleted. The RSS guard still raises. Every write path calls it: stage_place, promote, queue_scanned_pdf, arch_common, arch_states, de_hb, and now cdx_list.py, tos_post2020.py, de_by_cc.py (guard added before each `open(..., "w")`). Processes started before 01:54 PT keep the old behaviour (stop by exception, resumable). New runs and each new ch_full canton get the pause.
- Staged files are NOT compressed: run_loop.py only picks up `.jsonl`/`.parquet` (`f.suffix in (".jsonl", ".parquet")`) and rejects other names as bad_filename, so `.jsonl.gz` would be ignored. Our own logs/_work/cdx lists total under 10 MB (mostly already zipped), so compressing them gives nothing; only the /tmp/stprobe recon scratch was gzipped (65 MB -> 7.4 MB).
- status.sh shows a DISK FLOOR HIT banner and the rows already published and verified-pruned (state/pruned_manifest.jsonl).

### Archive throttle deferrals (2026-10-18, archive module v5)
All archive-using runners requeue instead of retrying: `ArchiveDeferred`/`ArchiveTransient` (and `deferq.ItemDeferred`
for breaker-open/timeout misses) put the item into a persisted deferred queue next to its checkpoint and the runner moves
on; when only deferred items remain it sleeps until the earliest `not_before`. `None` from fetch_best/fetch_newest is a
genuine miss. Truncated listings (`.truncated`) never complete a unit/part. Queues: `_state/<key>.deferred.tsv` (run_full
archive sources), `_work/<target>/deferred.tsv` (arch_states), `data/cdx_parts/_deferred.tsv` (cdx_list; exit 75 and no
output file while parts are deferred), `data/it_tos/_deferred.tsv` + `post2020_units.done` (tos_post2020),
`_work/de_juris_probe/{deferred,done}.tsv`, `data/cc_probe/_deferred.tsv`. Helper: `deferq.py`. Env: STATES_MAX_DEFERS (60
per item per run; then left queued for the next run), STATES_DEFER_DEFAULT_S (60).

## Federal expansion (2026-10-18 PT)
* **AR** (in-force selection from the SAIJ open CSV "Base SAIJ de Normativa Provincial", CC BY 4.0; SAIJ web texts NOT used, blocked by Res. 1427/2011): `ar_b_normas` (normas.gba.gob.ar), `ar_c_boletin` (CABA Boletín Oficial normativa; updated-text PDF when it has a text layer, else original HTML), `ar_s_normativa` (Santa Fe SIN, original PDFs). Mendoza / Córdoba: robots unreachable => not crawled. `ar_r_digesto` (Río Negro Digesto API; consolidated DEFINITIVO PDF, else promulgated text), `ar_u_digesto` (Chubut Digesto public API, VIGENTE provincial laws, textoCompleto), `ar_h_digesto` (Chaco Digesto Kendo grid JSON, in-force Leyes, digest numbering). San Juan (AR-J) `ar_j_digesto`: the digesto lists 2,107 in-force laws; texts sit on minio.legsanjuan.gob.ar whose robots.txt answers 403 (MinIO AccessDenied, no challenge). Coordinator decision 2026-10-18: RFC 9309 (4xx => allow) for that host only (`RFC9309_4XX_ALLOW_HOSTS` in common.py) while content pages serve normally to our UA; any content 403/challenge stops the run. Basis recorded in license_note and `robots_basis`.
* **ZA**: official legislature/government sites only (coordinator decision). LawLibrary is **blocked by terms** (no scraping/bulk download, CC BY-NC). `za_wc_wcpp` (WCPP Acts), `za_ec_ecpl` (EC Legislature document API, category provincial_acts; only the newest 1000 docs are listable; national gazette copies filtered). KZN: bills/notices only; Gauteng: a single Act post; Northern Cape: acts page lists titles without files; Limpopo/FS/NW: unreachable; Mpumalanga: **blocked** (coordinator 2026-10-18): the SPA reads a Supabase `documents` table with a key embedded in the page code; we do not use keys lifted from page code to query backend databases.
* **Blocked by terms, no collection:** AE-DU (Dubai DLP: personal/research use only), AE-AZ (Abu Dhabi ADJD terms: no extraction/reproduction), AE-SH (Sharjah gazette terms: reproduction prohibited, linking needs approval). Coordinator decision 2026-10-18.
* **Skipped (licence):** MY-13 Sarawak LawNet ("Copyright 2011 Sarawak Government. All Rights Reserved"; no statutory-text exception in Malaysian law). Coordinator decision 2026-10-18.
* **Skipped:** BE regions/communities (EU lane covers regional acts); NG-LA Lagos (LRC lists metadata only; texts are paid via LawPavilion).
* **AR-F La Rioja** `ar_f_legislatura`: SAIJ in-force laws (1,865) found on the legislature's WordPress "leyes" type (1,542); all sampled PDFs are image-only scans => queued to _scanned_pdfs_manifest.jsonl (no OCR), no rows staged.
* **AR-V Tierra del Fuego (live): not collected.** legistdf.gob.ar robots.txt allows `*` (Crawl-delay 10) but its comments ask dataset/AI crawlers (CCBot, GPTBot, ClaudeBot, Google-Extended, xAI-PDF-Recovery, ...) to stay out of /lp/ (the law-PDF archive) after an overload outage; we respect that intent. Held for a coordinator decision.
* **PK-BA Balochistan: skipped** (coordinator 2026-10-18; "All rights reserved by Law & Parliamentary Affairs Department Balochistan", same as MY-13 Sarawak). KP/Sindh are the national lane's (`national/pk/collect_pk_prov.py`); Punjab: sasia_ru lane notes (archive).
* **BA** (coordinator 2026-10-18): official texts are excluded from copyright by Art. 8(1)(b) of the BiH Law on Copyright and Related Rights (Sl. glasnik BiH 63/2010), cited in every license_note. All rows consolidated=False, in_force=None, `text_version` as_adopted (Brčko: also `precisceni_tekst` for the Assembly's consolidated-text PDFs, still consolidated=False). `ba_fbih_vlada` (FBiH government registers 2022-2026 link per-law HTML texts; older registers list titles only), `ba_srp_nsrs` (RS National Assembly adopted laws, .zip/.doc converted with LibreOffice headless), `ba_brc_skupstina` (Brčko Assembly law PDFs, one row per PDF; file names spell diacritics as c--/s--/z--/c+/c-).
* **IQ-KR** `iq_kr_parliament`: Kurdistan Parliament law PDFs, Kurdish section (1992-) and Arabic section (2002-); language per record (ckb/ar), in_force=None, consolidated=False. Many PDFs use legacy non-Unicode Arabic-script fonts (text layer is mojibake) => queued with scans in _scanned_pdfs_manifest.jsonl. Iraqi Copyright Law No. 3/1971 has no explicit official-text exclusion (noted in license_note).
* **AR-V Tierra del Fuego**: live site not touched (coordinator 2026-10-18); archive copies (Wayback/CC via the shared module) allowed at low priority, only if captures exist - pending.
* **DE-BE**: Wayback has ~2,800 2019 captures of the old gesetze.berlin.de jportal with full text (e.g. ArbSchGebO, 23k chars); snapshot is 2019-era (stale). Adapter deferred until de_sh_wb finishes (box-wide Wayback slot).
* **MX: not collected by this lane** (coordinator 2026-10-18). Overlap: the asia_latam lane (`asia_latam/arch/mx_arch.py`) collects OJN (ordenjuridico.gob.mx) state + municipal law for all 32 states from web archives; the Hub's 28 MX adm1 places (national lane, OJN archive samples, 1-343 docs each; GRO/MOR/SON/TLA missing) belong to that work. State-congress sources found (GRO 137 PDFs, TLA 113, NL ~177; SON/MOR robots unreachable) are left to asia_latam.
* **DE-SH** `de_sh_wb.py` (arch_states target): Wayback copies of the old juris portal, Gesamtausgabe pages only; listing flags (truncated/retry) are read per listing before merging.

**2026-10-19 review-hold fix.** Holds that are by design or in progress now go in `staging/states/_state/review_holds.tsv`, which status.sh prints. Nothing in `_review` is promoted automatically, and the routine checks never ran a promote, so these files sat there untouched. AU-NSW: the r1 test rows were only the JS frame of `/view/html/inforce/current/<id>` (about 220 chars, no provisions). The adapter now takes the archived `/view/whole/html/inforce/<date>/<id>` page, falling back to `/view/xml/...`, and the r1 file is in `_review/AU/_superseded/`. DE-SH: the old per-prefix `timestamp:4` listing returned 2 rows. A `urlkey` listing returns 16 Gesamtausgabe laws, and those 16 are all the archive holds. SH coverage is therefore 16 laws (an archive limit), and they're being run in full.
