# Legal corpus gap todo

Captured 2026-11-08 from `corpus_work_todo()` on branch `legal-dataset-schema-20261107`. Research-only. Authority flags stay false. This file is the list to queue from. `sample_corpus_gaps` still draws raw empty cells, including county patents, and is not the work queue.

Regenerate the live items with `corpus_work_todo()` in `ipfs_datasets_py/ducklake/legal_text_search.py`. A county row is not a second job. County search uses the municipal corpus. Each index job's `publish_repo` is on the `justicedao` org (`justicedao/<source-leaf>_ir`, with no second suffix).

## Queue

259 items: 64 index builds, 16 source checks, 179 municipal-ordinance scrapes.

### Build a vector index and a knowledge graph

Every index build publishes to the `justicedao` org. The destination on each line is the sibling the publisher must use. Source packs on `endomorphosis` stay the text and are not overwritten. National `ipfs_*_laws` statute packs are built with `COUNTRY_LAWS_IR_ROOT=/storage/hf_cache/country-laws-ir HF_HOME=/storage/hf_cache python -m ipfs_datasets_py.processors.legal_scrapers.country_laws_ir build --source-repo <source> --upload`. The local release stays under `/storage/hf_cache/country-laws-ir`. The upload target is only `justicedao/ipfs_<slug>_laws_ir`. The other rows are not that statute layout, so they do not go through that builder. A stub vector pack is not uploaded. `justicedao/ipfs_state_laws` and `justicedao/ipfs_federal_register` are not index destinations.


These selected corpora have text and no vector family. The US Code, US caselaw GraphRAG, the US patent IR, and the US Federal Register already declare both, so they are not listed.

US:

- [x] `justicedao/ipfs_us_cfr` — national regulations → `justicedao/ipfs_us_cfr_ir` (`a67a3eed0282c4620c67fbff66c8280692146f22`, 3650 documents)
- [x] `justicedao/ipfs_us_courts` — court directory → `justicedao/ipfs_us_courts_ir` (`3afaf71f5e29b1ffdeef74980f37807b83c9c50b`, 13761 documents)
- [x] `justicedao/ipfs_us_executive_orders` — national executive orders → `justicedao/ipfs_us_executive_orders_ir` (`e29d3c1fd056c527ed81bca57f03f6ed82c7b366`, 4149 documents)
- [ ] `justicedao/american_municipal_law_norm` — municipal ordinances → `justicedao/american_municipal_law_norm_ir`. Source loaded 13405571 laws then SIGKILL (`exit=-9`) inside in-memory normalize. Not uploaded.
- [x] `justicedao/ipfs_us_municipal_laws` — municipal ordinances → `justicedao/ipfs_us_municipal_laws_ir` (`3d81ae5cda6b4d715cc5977f80e59f81d51ec7f9`, 386 documents)

Caselaw text packs:

- [x] `justicedao/ipfs_australia_caselaw` → `justicedao/ipfs_australia_caselaw_ir` (`7450b1d888ef12a89b9cff106360ed98fe4bc696`, 3605507 documents)
- [x] `justicedao/ipfs_austria_caselaw` → `justicedao/ipfs_austria_caselaw_ir` (`3395380608685cdfc3fcd7176ceb9e6d5869bec5`, 42781 documents)
- [x] `endomorphosis/ipfs_brazil_caselaw` → `justicedao/ipfs_brazil_caselaw_ir` (`279f176b592c3cbd4318a2c1d097e036d8d5ef33`, 16237 documents)
- [x] `justicedao/ipfs_canada_caselaw` → `justicedao/ipfs_canada_caselaw_ir` (`bc05ff49b661b8321c67fe9a1299478bf4e62189`, 1768937 documents)
- [x] `endomorphosis/ipfs_canada_federal_caselaw` → `justicedao/ipfs_canada_federal_caselaw_ir` (`0eb77e1b71a4e5a21b75b0038c2082a49680478a`, 9563 documents)
- [x] `endomorphosis/ipfs_eu_caselaw` → `justicedao/ipfs_eu_caselaw_ir` (`5f329fd7403cc68fbe1dafafc7da3bcd5d397376`, 42557 documents)
- [x] `justicedao/ipfs_france_caselaw` → `justicedao/ipfs_france_caselaw_ir` (`777dcb1b33a280ff668a7fdb9ee349f80e70f08d`, 3641206 documents). Graph was streamed (7161550 nodes, 10923618 edges) after the in-memory writer was SIGKILL'd.
- [x] `justicedao/ipfs_germany_caselaw` → `justicedao/ipfs_germany_caselaw_ir` (`8f55994f2a9e8dfdf31d492036c886a44a3176e0`, 1246542 documents). Replaces thin `de1734b91c497ce47973429fd40e3a11a6b9160e` (193 documents keyed by court_id).
- [ ] `justicedao/ipfs_india_caselaw` → `justicedao/ipfs_india_caselaw_ir` — normalized 8762922 documents (`law+structured`, 1217850 staged laws, 119794 duplicate sections dropped) then SIGKILL (`exit=-9`) before `india_caselaw_corpus.parquet` was written. Not uploaded.
- [x] `endomorphosis/ipfs_malawi_caselaw` → `justicedao/ipfs_malawi_caselaw_ir` (`22de3c175b7988cde95919967b1daf483ae3c0d0`, 108 documents)
- [x] `justicedao/ipfs_netherlands_caselaw` → `justicedao/ipfs_netherlands_caselaw_ir` (`9ea77844f21e2f9eaaee11a909ab0304385a09fd`, 2881 documents)
- [ ] `justicedao/ipfs_poland_caselaw` → `justicedao/ipfs_poland_caselaw_ir` — vectors and BM25 are cached for 3386822 documents. Graph was SIGKILL'd (`exit=-9`) and is not uploaded.
- [x] `endomorphosis/ipfs_south_africa_caselaw` → `justicedao/ipfs_south_africa_caselaw_ir` (`2dadec77f19ba35782bd852c177b249367710197`, 421 documents)
- [x] `justicedao/ipfs_switzerland_caselaw` → `justicedao/ipfs_switzerland_caselaw_ir` (`d87fa9cc6654233d60c484b4d4442453a60af09e`, 68382 documents)
- [ ] `endomorphosis/world_caselaw` → `justicedao/world_caselaw_ir`. Staged 24949136 rows (64GB) then SIGKILL (`exit=-9`) during `pd.read_parquet`. Not uploaded.
- [x] `justicedao/ipfs_juricaf_caselaw` → `justicedao/ipfs_juricaf_caselaw_ir` (`2f6b32d31eaea5c2b597612f1cfdb9abbc0cb9bc`, 33796 documents)

Court directories:

- [x] `endomorphosis/ipfs_australia_courts` → `justicedao/ipfs_australia_courts_ir` (`17019a4b8927a0c4128652fb97b93d4d75d7d0be`, 4121 documents)
- [x] `endomorphosis/ipfs_brazil_courts` → `justicedao/ipfs_brazil_courts_ir` (`706ebe5e69cf1202de5b44df4b20d10b0a6077b3`, 118 documents)
- [x] `endomorphosis/ipfs_canada_courts` → `justicedao/ipfs_canada_courts_ir` (`c99385fbb9a41cc88281ceb0dcf1b9bd8234cdc0`, 8297 documents)
- [x] `endomorphosis/ipfs_france_courts` → `justicedao/ipfs_france_courts_ir` (`d44b36c45e9b6116a76666849d05949082020630`, 1773 documents)
- [x] `endomorphosis/ipfs_germany_courts` → `justicedao/ipfs_germany_courts_ir` (`65a8c8ea20702bb1655e663161d8f1ec986ce103`, 1358 documents)
- [x] `endomorphosis/ipfs_ireland_courts` → `justicedao/ipfs_ireland_courts_ir` (`d8b2fa916d0dab51357035520c22c15127a28cab`, 8553 documents)
- [x] `endomorphosis/ipfs_netherlands_courts` → `justicedao/ipfs_netherlands_courts_ir` (`a7dbfe13a15ede04c87063a75bc8eb6cc831c486`, 259 documents)
- [x] `endomorphosis/ipfs_newzealand_courts` → `justicedao/ipfs_newzealand_courts_ir` (`e0c735d4c0a86a192f8d1f269a481d16ecbdb90d`, 364 documents)
- [x] `endomorphosis/ipfs_uk_courts` → `justicedao/ipfs_uk_courts_ir` (`3272f4e82d67bdeb5fcc0579ccd6b01cdf3360b2`, 39042 documents)
- [x] `endomorphosis/ipfs_court_data` → `justicedao/ipfs_court_data_ir` (`38cbf89f84f7bb84a307958c09a437977f0ffd1e`, 116080 documents)
- [x] `endomorphosis/ipfs_world_court_judges` → `justicedao/ipfs_world_court_judges_ir` (`fac9209bccf1c76b8feeedc37744d34cc62a44df`, 5 documents)
- [x] `endomorphosis/ipfs_world_courts_directory` → `justicedao/ipfs_world_courts_directory_ir` (`f38c35facfce6c48a7582e0da3de41c0abe075a2`, 5137 documents)
- [x] `justicedao/ipfs_world_courts` → `justicedao/ipfs_world_courts_ir` (`b4c20d0bbeb7596c61315ce476d8569ffe73ae8c`, 630 documents)

Dedup the four world court repos before embedding all of them.

Regulations:

- [x] `justicedao/ipfs_australia_regulations` → `justicedao/ipfs_australia_regulations_ir` (`26dd005dbd9d4115bdb51e2ce4c9e8d3700b0f31`, 139 documents)
- [x] `justicedao/ipfs_austria_regulations` → `justicedao/ipfs_austria_regulations_ir` (`0ca992c322ad07686116f9f7f48a40452ab4bd5b`, 174 documents)
- [x] `justicedao/ipfs_brazil_regulations` → `justicedao/ipfs_brazil_regulations_ir` (`471a51fcea2d8b2169fc156cc4c592ce8d207ac9`, 2 documents)
- [x] `justicedao/ipfs_canada_regulations` → `justicedao/ipfs_canada_regulations_ir` (`8170442abf5d7c5387bb6bbb4b2f9d1fef3a379d`, 1877 documents)
- [x] `justicedao/ipfs_czechia_regulations` → `justicedao/ipfs_czechia_regulations_ir` (`e15dbc186706bfcff4619f6466f7424a414d5524`, 945 documents)
- [x] `justicedao/ipfs_eu_admin_regulations` → `justicedao/ipfs_eu_admin_regulations_ir` (`619c56d0e8ffcb529e9d5b7b0680cd450c71db7c`, 27 documents)
- [x] `justicedao/ipfs_france_regulations` → `justicedao/ipfs_france_regulations_ir` (`ea3350c0717999d0f4149c6527c13b7dcfd7f1d4`, 352 documents)
- [x] `justicedao/ipfs_germany_regulations` → `justicedao/ipfs_germany_regulations_ir` (`ddefe61c442353b81c0f73d9032b45c18fd0dd2b`, 2505 documents)
- [x] `justicedao/ipfs_japan_regulations` → `justicedao/ipfs_japan_regulations_ir` (`155eabe2ba1d3f8e976ae0244e78eaf79f1050b0`, 78 documents)
- [x] `justicedao/ipfs_poland_regulations` → `justicedao/ipfs_poland_regulations_ir` (`c80cb375e883c1c2d6f9ee949ad93332b77094fb`, 2524 documents)
- [x] `justicedao/ipfs_spain_regulations` → `justicedao/ipfs_spain_regulations_ir` (`b956c8d581b9d856e01ec5d5d76912ce05a46968`, 744 documents)
- [x] `justicedao/ipfs_unitedkingdom_regulations` → `justicedao/ipfs_unitedkingdom_regulations_ir` (`0c37375f1d6aff1e3fb8e55f2ca5af1f918aa14d`, 887 documents)

Other text packs:

- [x] `endomorphosis/ipfs_spain_laws_subnational` — state statutes → `justicedao/ipfs_spain_laws_subnational_ir` (`b82d03d9e6b13428ec8021c50d5f630b5e940fe3`, 332473 documents)
- [x] `justicedao/ipfs_spain_catalonia_municipal_laws` — municipal ordinances → `justicedao/ipfs_spain_catalonia_municipal_laws_ir` (`fa19fe089ebaeb68b650bb66c1b3d3e2f03283c8`, 87618 documents)
- [ ] `endomorphosis/world_court_forms` → `justicedao/world_court_forms_ir` — skipped. The repo is a PDF path index and has no form text.
- [x] `endomorphosis/ipfs_world_court_rules` → `justicedao/ipfs_world_court_rules_ir` (`f13a4745d6fed9d8916a322e431e7b04a38d1621`, 76494 documents)

- [x] `endomorphosis/ipfs_bonairesinteustatiusandsaba_laws` → `justicedao/ipfs_bonairesinteustatiusandsaba_laws_ir` (`c50bc39c8dc5a860bdfcabfca7ecc7cfe1d78c69`, 22218 vectors)
- [x] `endomorphosis/ipfs_christmasisland_laws` → `justicedao/ipfs_christmasisland_laws_ir` (`7e38e6f366d7d35553d29866b82fc020e4e7154d`, 141 vectors)
- [x] `endomorphosis/ipfs_cocoskeelingislands_laws` → `justicedao/ipfs_cocoskeelingislands_laws_ir` (`09d431841e27f986e2c13165ca10e98f17c11f90`, 153 vectors)
- [x] `endomorphosis/ipfs_frenchguiana_laws` → `justicedao/ipfs_frenchguiana_laws_ir` (`46b0e191fdace229a06cf446176d5862f81fe9e5`, 3211 vectors)
- [x] `endomorphosis/ipfs_guadeloupe_laws` → `justicedao/ipfs_guadeloupe_laws_ir` (`63d3134968930eed721d8c5b103a34d4bd73359d`, 2510 vectors)

- [x] `endomorphosis/ipfs_martinique_laws` → `justicedao/ipfs_martinique_laws_ir` (`e62799215c5899f2fb24f9ccfd96bd9297fe036a`, 2510 vectors)
- [x] `endomorphosis/ipfs_mayotte_laws` → `justicedao/ipfs_mayotte_laws_ir` (`a1d680ae64d4cebe2f559a14cf13b5cd19a6733c`, 10467 vectors)
- [x] `endomorphosis/ipfs_northernmarianaislands_laws` → `justicedao/ipfs_northernmarianaislands_laws_ir` (`0e73ae7246d2e52caf087f7b35ccac2cfe9fbcc9`, 759 vectors)
- [x] `endomorphosis/ipfs_reunion_laws` → `justicedao/ipfs_reunion_laws_ir` (`5720d46b10d3e1458bd596543b74947e1052b90b`, 2701 vectors)
- [x] `endomorphosis/ipfs_saintbarthelemy_laws` → `justicedao/ipfs_saintbarthelemy_laws_ir` (`82ef5d9c29e4d9c3face9325335999aaa5d8c285`, 1170 vectors)
- [x] `endomorphosis/ipfs_saintmartin_laws` → `justicedao/ipfs_saintmartin_laws_ir` (`507a8bdd3d82459f7d2960e6057aa3aa0988bea6`, 1478 vectors)
- [x] `endomorphosis/ipfs_saintpierreandmiquelon_laws` → `justicedao/ipfs_saintpierreandmiquelon_laws_ir` (`16bfec8a5b881f3622d8db57d4584f67d2dfc20a`, 4978 vectors)
- [x] `endomorphosis/ipfs_svalbardandjanmayen_laws` → `justicedao/ipfs_svalbardandjanmayen_laws_ir` (`8773b5a28dfb44ac104036e8edae18d75fa92717`, 7957 vectors)
- [x] `endomorphosis/ipfs_virginislandsus_laws` → `justicedao/ipfs_virginislandsus_laws_ir` (`5c65c9a5d58f04e12693cac39baf03667db62a81`, 169 vectors)

### Find a source, then scrape

A sibling instrument is already published. Do not scrape until the public source is named.

- [ ] Czechia caselaw — regulations exist
- [ ] India court directory — caselaw exists
- [ ] India regulations — caselaw exists
- [ ] Ireland caselaw — court directory exists
- [ ] Japan caselaw — regulations exist
- [ ] Malawi court directory — caselaw exists
- [ ] Malawi regulations — caselaw exists
- [ ] Netherlands regulations — caselaw and a court directory exist
- [ ] New Zealand caselaw — court directory exists
- [ ] Poland court directory — caselaw and regulations exist
- [ ] South Africa court directory — caselaw exists
- [ ] South Africa regulations — caselaw exists
- [ ] Spain caselaw — regulations and subnational statutes exist
- [ ] Switzerland court directory — caselaw exists
- [ ] Switzerland regulations — caselaw exists
- [ ] UK caselaw — regulations and a court directory exist

### Municipal ordinances

179 jurisdictions have a searchable national statute layout and no municipal ordinance corpus. Confirm a municipal code exists, then scrape it. One corpus covers the county row. Dependencies and small territories are in this list on purpose. Skip a name when there is no municipal code.

afghanistan, aland, albania, algeria, angola, anguilla, antigua_barbuda, argentina, armenia, aruba, azerbaijan, bahamas, bahrain, bangladesh, barbados, belarus, belize, benin, bermuda, bhutan, bolivia, bosnia, botswana, british_virgin_islands, brunei, bulgaria, burkinafaso, burundi, caboverde, cambodia, cameroon, car, cayman, chad, chile, china, colombia, comoros, congobrazzaville, cookislands, costarica, cotedivoire, croatia, cuba, curacao, cyprus, djibouti, dominica, dominicanrepublic, drc, ecuador, egypt, elsalvador, equatorialguinea, eritrea, eswatini, falkland_islands, faroe, fiji, french_polynesia, fsm, gabon, gambia, georgia, ghana, gibraltar, greenland, grenada, guam, guatemala, guernsey, guinea, guineabissau, guyana, haiti, honduras, hongkong, hungary, iceland, india, iran, iraq, isle_of_man, israel, jamaica, jersey, kazakhstan, kiribati, kosovo, kuwait, kyrgyzstan, laos, lebanon, lesotho, liberia, libya, liechtenstein, lithuania, madagascar, malawi, malaysia, maldives, mali, marshallislands, mauritania, moldova, monaco, mongolia, montenegro, montserrat, morocco, myanmar, nauru, nepal, new_caledonia, nicaragua, niger, nigeria, niue, norfolk_island, northkorea, northmacedonia, norway, oman, pakistan, palau, panama, papuanewguinea, paraguay, philippines, pitcairn, poland, puerto_rico, qatar, romania, russia, rwanda, saint_helena, saint_kitts_nevis, saint_lucia, saint_vincent_grenadines, samoa, sanmarino, saotome, senegal, serbia, seychelles, sierraleone, singapore, sint_maarten, solomonislands, somalia, southsudan, srilanka, sudan, suriname, syria, tajikistan, thailand, timorleste, togo, tonga, trinidad, turkey, turkmenistan, turks_caicos, tuvalu, uae, uk, ukraine, uruguay, uzbekistan, vanuatu, vatican, venezuela, vietnam, wallis_futuna, yemen, zambia

Countries that already have a municipal IR, including France, Germany, and Spain, are not in this list. The EU and the world key are not municipal lawmakers.

## Double-check before queueing

### Verify the layout, then decide

Leave both unselected until the files are read.

- [ ] `justicedao/ipfs_court_rules` — US state rules of procedure
- [ ] `justicedao/ipfs_state_admin_rules` — US state regulations

### Pin-gated, do not select to close a gap

- [ ] `endomorphosis/world_municipal_law`
- [ ] `endomorphosis/world_national_law`
- [ ] `justicedao/world_national_law`
- [ ] `justicedao/world_national_law_norm`

### Overlap with a corpus that already has vectors and a graph

- [ ] `justicedao/ipfs_caselaw_access_project` — US caselaw text beside `justicedao/caselaw-access-project-graphrag`
- [ ] `justicedao/Caselaw_Access_Project_embeddings` — vectors exist, graph family does not, GraphRAG already covers US caselaw
- [ ] `endomorphosis/publicus` — beside `justicedao/ipfs_uscode`
- [ ] `justicedao/ipfs_ukraine_laws_supplement` — beside the Ukraine statute IR

### Text packs that may be empty, duplicated, or already inside a parent

Do not embed these until the row count and the parent corpus are checked.

- [ ] `endomorphosis/ipfs_antarctica_laws`
- [ ] `endomorphosis/ipfs_bouvetisland_laws`
- [ ] `endomorphosis/ipfs_britishindianoceanterritory_laws`
- [ ] `endomorphosis/ipfs_frenchsouthernterritories_laws`
- [ ] `endomorphosis/ipfs_heardislandandmcdonaldislands_laws`
- [ ] `endomorphosis/ipfs_southgeorgiaandthesouthsandwichislands_laws`
- [ ] `endomorphosis/ipfs_unitedstatesminoroutlyingislands_laws`
- [ ] `endomorphosis/ipfs_runion_laws` — spelling pair of `ipfs_reunion_laws`
- [ ] `endomorphosis/ipfs_saintbarthlemy_laws` — spelling pair of `ipfs_saintbarthelemy_laws`
- [ ] `endomorphosis/ipfs_puertorico_laws` — pair of the `puerto_rico` statute layout
- [ ] `endomorphosis/ipfs_saintmartinfrenchpart_laws` — pair of `ipfs_saintmartin_laws`
- [ ] `justicedao/ipfs_france_local_laws`
- [ ] `justicedao/ipfs_italy_regional_laws`
- [ ] `justicedao/ipfs_indonesia_east_java_laws`
- [ ] `justicedao/ipfs_us_local_laws`
- [ ] `endomorphosis/world_law_scanned_text`
- [x] `endomorphosis/ipfs_tokelau_laws` — published on request to `justicedao/ipfs_tokelau_laws_ir` (`52fdb6d2cc05d31e678627fc0d37e0580154eefe`, 3 documents). `HOLD_RIGHTS_UNRESOLVED.md` still says all rights reserved.
- [x] `endomorphosis/ipfs_americansamoa_laws` — license field says attribution is required and territorial reuse terms must be verified. Queued on request. The canonical `data/laws.parquet` is one line per statute and was emptied by the banner filter; wave parquets plus the banner fix are in the rebuild to `justicedao/ipfs_americansamoa_laws_ir`. (`fdc4b0f73a241d1dc1c8643bda3c9c613db3c4c7`, 7397 documents)
- [x] `endomorphosis/ipfs_macao_laws` — published on request to `justicedao/ipfs_macao_laws_ir` (`6042c867859b1792fce2e91dc422eb6e6551278e`, 6811 documents). The license field still names the gazette and does not grant redistribution.
- [ ] `endomorphosis/ipfs_westernsahara_laws` — provenance scripts only. There is no `laws.parquet` to index.

### Subnational keys, not new countries

These already have a statute layout. Do not open a municipal scraper for each one.

argentina_provincial, australia_state, belgium_regional, brazil_state, canada_state, egypt_governorate, greece_regional, india_state, kazakhstan_district, kazakhstan_provincial, latvia_district, nepal_provincial, netherlands_provincial, pakistan_provincial, slovakia_regional, south_africa_provincial, united_kingdom_county, united_states_county, united_states_state, uzbekistan_district, uzbekistan_provincial

## Do not queue

Each of these is 284 empty cells, one per jurisdiction key. They are not missing scrapers.

- County, state, and municipal patents. Patent law in this corpus is national. The US patent IR is already a searchable layout. There is no county patent list to collect.
- County, state, and municipal registers. The register corpus is the US Federal Register.
- County and municipal executive orders. US executive orders are the national index job above. State executive orders are not queued.
- State, county, and municipal court forms. The form corpus is `endomorphosis/world_court_forms`.
- National and state ordinances. Ordinances are municipal, and the county row uses that same corpus.
- County and municipal caselaw, court directories, rules of procedure, regulations, and statutes. Those instruments are national or state. Local laws are the ordinance scrape above.
- A second county job whenever the municipal cell is the same corpus or the same gap.

Also not queued, on purpose:

- National caselaw, regulations, or court directories for countries that have statutes but no sibling pack. The 16 source checks above are the ones with a sibling already in hand. The rest wait until a source is named.
- State or provincial statute books other than the US state-law corpus, the Spain subnational pack, and the partition keys listed above.
- Patent offices and official gazettes outside the US packs already in the schema.
