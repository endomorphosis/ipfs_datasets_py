# Upstream legal_scrapers review — 2026-10-10

Source: `endomorphosis/legal_scrapers (HF dataset)` @ `ec9da93c30e6cdf0577060d770778ad4433c3a8c` (2026-10-10 3:28 PM PT): "Add 21 missing collectors, refresh shared helpers, add country_laws_ir normalizer snapshot + pinned schema".

Reviewed against this repo's policy (official sources only; robots/terms respected; no Wayback, CDX or Common Crawl; no captcha/WAF bypass). Static review only.

**Result: 0 OK, 21 WAYBACK_EXCLUDE, 0 NEEDS_REVIEW — no upstream code is vendored here.**

world_lib.fetch_official defaults to wayback=True and imports archive_fallbacks (Wayback + Common Crawl); common/world_lib have no robots.txt handling. Live-only use would need wayback=False, removal of cdx_urls discovery, and an added robots check.

| cc | country | lines | class | hub laws / articles | IR | vs hub collector | adds volume? |
|---|---|---:|---|---|---|---|---|
| AF | Afghanistan | 224 | WAYBACK_EXCLUDE | 62 / 4905 | yes | identical to hub scrapers/ copy | no: hub was built by the same or a fuller version of this collector |
| BN | Brunei | 108 | WAYBACK_EXCLUDE | 238 / 21383 | yes | hub copy larger (156 vs 108 lines), same hosts | no: hub was built by the same or a fuller version of this collector |
| BW | Botswana | 440 | WAYBACK_EXCLUDE | 159 / 10656 | yes | hub copy larger (768 vs 440); new adds competitionauthority.co.bw + ppadb.co.bw | small: two agency hosts not in hub (PPADB, Competition Authority) — likely tens of instruments |
| CM | Cameroon | 554 | WAYBACK_EXCLUDE | 575 / 6056 | yes | hub copy larger (649 vs 554), same hosts | no: hub was built by the same or a fuller version of this collector |
| CU | Cuba | 103 | WAYBACK_EXCLUDE | 279 / 33808 | yes | hub copy larger (376 vs 103) and also covers minjus.gob.cu | no: hub was built by the same or a fuller version of this collector |
| FJ | Fiji | 110 | WAYBACK_EXCLUDE | 434 / 254 | yes | hub copy larger (190 vs 110), same hosts | no: hub was built by the same or a fuller version of this collector |
| GT | Guatemala | 99 | WAYBACK_EXCLUDE | 2412 / 27029 | yes | hub copy larger (143 vs 99), same hosts | no: hub was built by the same or a fuller version of this collector |
| HN | Honduras | 101 | WAYBACK_EXCLUDE | 209 / 10550 | yes | near-identical (6 diff lines) | no: hub was built by the same or a fuller version of this collector |
| IQ | Iraq | 144 | WAYBACK_EXCLUDE | 363 / 4464 | yes | near-identical (7) | no: hub was built by the same or a fuller version of this collector |
| KH | Cambodia | 99 | WAYBACK_EXCLUDE | 117 / 8301 | yes | identical | no: hub was built by the same or a fuller version of this collector |
| LB | Lebanon | 114 | WAYBACK_EXCLUDE | 370 / 1139 | yes | hub copy larger (290 vs 114), same hosts | no: hub was built by the same or a fuller version of this collector |
| MG | Madagascar | 6 | WAYBACK_EXCLUDE | 280 / 13206 | yes | new file is a 6-line stub; hub copy is 916 lines over 9 official hosts | no: hub was built by the same or a fuller version of this collector |
| MZ | Mozambique | 667 | WAYBACK_EXCLUDE | 294 / 8338 | yes | identical | no: hub was built by the same or a fuller version of this collector |
| NA | Namibia | 658 | WAYBACK_EXCLUDE | 530 / 5791 | yes | new larger (658 vs 560) adding bon.com.na, but hub already has 89 BoN rows | none meaningful: BoN already in hub (89/530 laws) |
| NI | Nicaragua | 103 | WAYBACK_EXCLUDE | 353 / 34727 | yes | hub copy larger (232 vs 103) | no: hub was built by the same or a fuller version of this collector |
| PG | Papua New Guinea | 104 | WAYBACK_EXCLUDE | 113 / 405 | yes | hub copy larger (158 vs 104), also pnglaw.gov.pg | no: hub was built by the same or a fuller version of this collector |
| SS | South Sudan | 249 | WAYBACK_EXCLUDE | 99 / 601 | yes | identical | no: hub was built by the same or a fuller version of this collector |
| SV | El Salvador | 313 | WAYBACK_EXCLUDE | 325 / 12937 | yes | identical | no: hub was built by the same or a fuller version of this collector |
| TT | Trinidad and Tobago | 103 | WAYBACK_EXCLUDE | 488 / 12588 | yes | hub copy larger (370 vs 103) | no: hub was built by the same or a fuller version of this collector |
| VE | Venezuela | 100 | WAYBACK_EXCLUDE | 205 / 6392 | yes | hub copy larger (528 vs 100) | no: hub was built by the same or a fuller version of this collector |
| ZW | Zimbabwe | 418 | WAYBACK_EXCLUDE | 490 / 26696 | yes | hub copy larger (648 vs 418), more hosts | no: hub was built by the same or a fuller version of this collector |
