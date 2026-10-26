# World law coverage — 2026-10-10 (PT)

Sources: tracker `2026-10-09T10:10 AM PT (AU municipal NSW re-check)`, national triage sheet, HF API listings (anonymous, 2026-10-10 ~4:50 PM PT), prep queue 2026-10-06.

national DONE = endomorphosis hub + justicedao IR both on HF; IN_PROGRESS = hub without IR; NOT_COLLECTED = no hub found under known slugs; US SKIPPED. laws/articles come from the national triage sheet (as of counts_as_of, at counts_tip) and may predate the current hub tip. State/municipal statuses from the tracker (Oct 9), municipal refreshed where an HF municipal hub now exists.

## Summary

- **rows**: 199
- **national (195 UN members+observers)**: {"DONE": 193, "SKIPPED": 1, "NOT_COLLECTED": 1}
- **national (all rows)**: {"DONE": 197, "SKIPPED": 1, "NOT_COLLECTED": 1}
- **state (all rows)**: {"NEEDS_PERMISSION": 69, "N/A": 9, "BLOCKED_SOURCE": 55, "DONE": 5, "READY": 9, "BLOCKED_TERMS": 8, "NOT_SURVEYED": 39, "NO_NATIONAL_CHANNEL": 4, "SKIPPED": 1}
- **municipal (all rows)**: {"NO_NATIONAL_CHANNEL": 49, "NEEDS_PERMISSION": 30, "BLOCKED_SOURCE": 77, "IN_PROGRESS": 22, "QUEUED": 2, "BLOCKED_TERMS": 3, "READY": 3, "DONE": 5, "N/A": 7, "SKIPPED": 1}
- **national hubs on HF (endomorphosis/ipfs_*_laws, excl. municipal)**: 215
- **municipal hubs on HF**: 25
- **justicedao IR repos (*_laws_ir / *-ir)**: 231
- **rows with any blocker**: 165
- **blocker counts (rows)**: {"NEEDS_PERMISSION": 85, "NO_NATIONAL_CHANNEL": 50, "BLOCKED_SOURCE": 100, "BLOCKED_TERMS": 11}
- **hubs not mapped to a tracker row (territories/duplicates/EU)**: ["ipfs_anguilla_laws", "ipfs_aruba_laws", "ipfs_bermuda_laws", "ipfs_british_virgin_islands_laws", "ipfs_cayman_laws", "ipfs_curacao_laws", "ipfs_eu_laws", "ipfs_hongkong_laws", "ipfs_montserrat_laws", "ipfs_puerto_rico_laws", "ipfs_sint_maarten_laws", "ipfs_turks_caicos_laws"]

## Remaining READY / QUEUED collection work

Total known: **1,299,011 items**, serial **434.5–1,116.9 h (~18.1–46.5 days)**. Unknown size: au_sa, be_codex_vlaanderen.

Serial single-collector estimate (one collector at a time, as under current memory policy). Lower bound = request delay only; upper = delay + ~1.5 s fetch/parse (NL range is measured). Excludes packing/IR encode time and any countries still NEEDS_PERMISSION/BLOCKED.

| item | status | ids | s/id | hours | note |
|---|---|---:|---|---|---|
| nl_municipal (NL-M CVDR scan) | IN_PROGRESS (tranche 1 published; main scan running) | see update below | 0.5–2.7 | n/a | tranche 1 = CVDR 600000..767599, 61,655 laws / 925,208 units at justicedao/ipfs_netherlands_municipal_laws; GAP ids 640600..664399 (24,000) unscanned on the current disk, to be appended as tranche 2; scan continues below id 600000 |
| cz_sbirkapp T2 | READY (paused, STOP_CZ) | 67000 | 2.0–4.0 | 37.2–74.4 | cursor 2243/3704 municipalities; >=2.0 s/request + OCR |
| id_bpk (JDIH BPK regional) | READY (paused) | 268443 | 2.0–3.5 | 149.1–261.0 | >=2.0 s between requests |
| ee_municipal_t2 | READY | 11045 | 1.5–3.0 | 4.6–9.2 | Net-new only; exclude T1 tip 9ef422a2a38a akt-ids. Exclude list FROZEN & WIRED: ref/ee_t1_akt_ids_20261006.txt (939 ids) |
| is_bdeild | QUEUED | 1682 | 1.0–2.5 | 0.5–1.2 | At GO: polite read-only probe to confirm 1588+94 membership; if 403 persists — no bypass, report and HOLD. CoS 2026-10-0 |
| be_fl_vindplaats | QUEUED | 1718 | 1.0–2.5 | 0.5–1.2 | Confirmed 2021-07→2024-05 Centrale Vindplaats stale only; never the 3.78M harvester. CoS 2026-10-06 ~2:05 PM PT. |
| au_sa | QUEUED | ? | 10.0–11.5 | ? | Delay floor 10s confirmed OK. CoS 2026-10-06 ~2:05 PM PT. |
| be_codex_vlaanderen | QUEUED | ? | 1.0–2.5 | ? | Count first at GO, then collect. CoS 2026-10-06 ~2:05 PM PT. |
| it_toscana | QUEUED | 4361 | 1.5–3.0 | 1.8–3.6 | Discover pagination at GO under robots; stop and report if blocked. CoS 2026-10-06 ~2:05 PM PT. |
| it_statuti | QUEUED | 8284 | 1.5–3.0 | 3.5–6.9 | Statutes only; OCR attachments only when text empty (CZ-style child OCR). CoS 2026-10-06 ~2:05 PM PT. |
| fr_scdl_deliberations | READY | 28 | 1.0–2.5 | 0.0–0.0 | ONLY collect frozen 28-id allow-list (ref/fr_scdl_28_allowlist_20261006.json: 21 lov2 + 6 fr-lo + 1 odc-odbl; skip 18 no |
| id_jateng_jdih | QUEUED | 2101 | 2.0–3.5 | 1.2–2.0 | Perda + Pergub only (no Kepgub). CoS 2026-10-06 ~2:05 PM PT. |
| br_alesp | QUEUED | 254063 | 2.0–3.5 | 141.1–247.0 | Alone-required confirmed (never with NL-M); at GO ALL tipos from open ZIP (not Lei-only) — dump not crawl. CoS 2026-10-0 |
| pt_azores | QUEUED | 754 | 1.0–2.5 | 0.2–0.5 | Clear — CoS confirmed. CoS 2026-10-06 ~2:05 PM PT. |
| za_western_cape | QUEUED | 133 | 10.0–11.5 | 0.4–0.4 | Acts only, delay 10s — clear. CoS 2026-10-06 ~2:05 PM PT. |

## Per-country

| cc | country | national | hub tip | laws / articles | IR | state | municipal | blockers |
|---|---|---|---|---|---|---|---|---|
| AF | Afghanistan | DONE | 8efb49310c98 |  | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| AL | Albania | DONE | 11be1a792eee | 2,830 / 53,169 | yes | NEEDS_PERMISSION | NEEDS_PERMISSION | NEEDS_PERMISSION |
| DZ | Algeria | DONE | e01c7f983e00 | 100 / 492 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| AD | Andorra | DONE | f5d83515a911 |  | yes | N/A | IN_PROGRESS |  |
| AO | Angola | DONE | 2487027e44f3 | 2,856 / 31,073 | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| AG | Antigua and Barbuda | DONE | cc1ea1a66d97 |  | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| AR | Argentina | DONE | 765485dcb802 | 8,643 / 92,507 | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| AM | Armenia | DONE | 0840d70d9a6e | 342 / 16,679 | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| AU | Australia | DONE | 58732457a228 | 29,084 / 309,135 | yes | DONE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| AT | Austria | DONE (LIVE) | 096bd65e89d3 | 21,959 / 201,971 | yes | NEEDS_PERMISSION | IN_PROGRESS | NEEDS_PERMISSION |
| AZ | Azerbaijan | DONE | 0881fc57ea43 | 4,447 / 6,185 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| BS | Bahamas | DONE | 4fbb225cc993 |  | yes | BLOCKED_SOURCE | NO_NATIONAL_CHANNEL | BLOCKED_SOURCE, NO_NATIONAL_CHANNEL |
| BH | Bahrain | DONE | 12ea22a55e21 | 173 / 5,484 | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| BD | Bangladesh | DONE | 16782096c126 | 1,676 / 1,046 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| BB | Barbados | DONE | bf22aebf7550 |  | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| BY | Belarus | DONE | b5fe172bd073 | 40 / 7,335 | yes | NEEDS_PERMISSION | NEEDS_PERMISSION | NEEDS_PERMISSION |
| BE | Belgium | DONE | edb77b124b59 | 9,116 / 783,990 | yes | READY | QUEUED |  |
| BZ | Belize | DONE | f01dde128a4a |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| BJ | Benin | DONE | 4205c221a681 |  | yes | BLOCKED_TERMS | BLOCKED_SOURCE | BLOCKED_SOURCE, BLOCKED_TERMS |
| BT | Bhutan | DONE | 796412e31957 |  | yes | BLOCKED_SOURCE | NO_NATIONAL_CHANNEL | BLOCKED_SOURCE, NO_NATIONAL_CHANNEL |
| BO | Bolivia | DONE | 73d9f37a858d | 2,752 / 21,944 | yes | NEEDS_PERMISSION | NEEDS_PERMISSION | NEEDS_PERMISSION |
| BA | Bosnia and Herzegovina | DONE | 07c77d96ea2d | 157 / 9,637 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| BW | Botswana | DONE | 4f8f104e784a | 99 / 9,227 | yes | BLOCKED_TERMS | BLOCKED_SOURCE | BLOCKED_SOURCE, BLOCKED_TERMS |
| BR | Brazil | DONE | 4da9b8178484 | 16,875 / 99,687 | yes | READY | IN_PROGRESS |  |
| BN | Brunei | DONE | fa649d0d49be | 238 / 21,383 | yes | BLOCKED_SOURCE | NO_NATIONAL_CHANNEL | BLOCKED_SOURCE, NO_NATIONAL_CHANNEL |
| BG | Bulgaria | DONE | ed5761093e16 | 1,761 / 29,643 | yes | BLOCKED_SOURCE | BLOCKED_TERMS | BLOCKED_SOURCE, BLOCKED_TERMS |
| BF | Burkina Faso | DONE | 397e6ed9482e |  | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| BI | Burundi | DONE | b5768508c9ba |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| CV | Cabo Verde | DONE | 20408347f403 |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| KH | Cambodia | DONE | 551c9f263211 | 101 / 1,330 | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| CM | Cameroon | DONE | 18e26bb8203a | 188 / 3,280 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| CA | Canada | DONE | 56377e97d5bd | 11,676 / 267,570 | yes | DONE | BLOCKED_TERMS | BLOCKED_TERMS |
| CF | Central African Republic | DONE | 7fd4f3ed940b |  | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| TD | Chad | DONE | cfef0584fb76 | 99 / 19,425 | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| CL | Chile | DONE | 4fbfd2b68c15 | 786 / 25,625 | yes | NOT_SURVEYED | NEEDS_PERMISSION | NEEDS_PERMISSION |
| CN | China | DONE | 416a1b3eac0d | 295 / 21,454 | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| CO | Colombia | DONE | bfafc6e2e8d6 | 2,708 / 81,694 | yes | NOT_SURVEYED | READY |  |
| KM | Comoros | DONE | bf29adc28297 |  | yes | BLOCKED_SOURCE | NO_NATIONAL_CHANNEL | BLOCKED_SOURCE, NO_NATIONAL_CHANNEL |
| CG | Congo | DONE | 79328ea45cb0 |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| CD | DR Congo | DONE | a72ae6be8813 |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| CR | Costa Rica | DONE | 35a79265f533 | 4,373 / 55,393 | yes | NOT_SURVEYED | NEEDS_PERMISSION | NEEDS_PERMISSION |
| CI | Côte d'Ivoire | DONE | 67ef43d5e4b3 |  | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| HR | Croatia | DONE | 42326b74f129 | 30,315 / 282,996 | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| CU | Cuba | DONE | cd431e5d0272 | 279 / 21,087 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| CY | Cyprus | DONE | c46312ea7022 | 779 / 24,036 | yes | NOT_SURVEYED | NEEDS_PERMISSION | NEEDS_PERMISSION |
| CZ | Czechia | DONE | f1dc1010ae15 | 41,340 / 15,091 | yes | NOT_SURVEYED | DONE |  |
| DK | Denmark | DONE | 6db5f2622c57 | 33,334 / 580,533 | yes | NOT_SURVEYED | NO_NATIONAL_CHANNEL | NO_NATIONAL_CHANNEL |
| DJ | Djibouti | DONE | bc8e769bb669 | 165 / 3,205 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| DM | Dominica | DONE | d071c156bb3c | 156 / 4,690 | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| DO | Dominican Republic | DONE | cefdb06b1bc2 | 2,936 / 267,857 | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| EC | Ecuador | DONE | 0c6f1d5e86a2 | 320 / 54,064 | yes | NOT_SURVEYED | NEEDS_PERMISSION | NEEDS_PERMISSION |
| EG | Egypt | DONE | 0ddf04279b31 | 407 / 1,214 | yes | BLOCKED_SOURCE | NEEDS_PERMISSION | BLOCKED_SOURCE, NEEDS_PERMISSION |
| SV | El Salvador | DONE | d4c95b8ac61d | 245 / 12,937 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| GQ | Equatorial Guinea | DONE | 6d86d0c7e604 |  | yes | BLOCKED_TERMS | BLOCKED_SOURCE | BLOCKED_SOURCE, BLOCKED_TERMS |
| ER | Eritrea | DONE (BLOCKED_SOURCE) | 614ff41f143f |  | yes | BLOCKED_SOURCE | NO_NATIONAL_CHANNEL | BLOCKED_SOURCE, NO_NATIONAL_CHANNEL |
| EE | Estonia | DONE | 902b122cd27e | 3,484 / 62,308 | yes | NOT_SURVEYED | DONE |  |
| SZ | Eswatini | DONE | 7076fc82ba00 |  | yes | BLOCKED_TERMS | NO_NATIONAL_CHANNEL | BLOCKED_TERMS, NO_NATIONAL_CHANNEL |
| ET | Ethiopia | DONE | 2bf76f8a31fe | 2,542 / 14,119 | yes | NEEDS_PERMISSION | IN_PROGRESS | NEEDS_PERMISSION |
| FJ | Fiji | DONE | 8c93026f2002 | 434 / 254 | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| FI | Finland | DONE | e2853063c76a | 106,244 / 248,848 | yes | NOT_SURVEYED | NO_NATIONAL_CHANNEL | NO_NATIONAL_CHANNEL |
| FR | France | DONE | 2302d85c4edc | 114,041 / 677,149 | yes | NOT_SURVEYED | READY |  |
| GA | Gabon | DONE | 55ca40a7d28b |  | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| GM | Gambia | DONE | 1bf963a9d18f |  | yes | BLOCKED_SOURCE | NO_NATIONAL_CHANNEL | BLOCKED_SOURCE, NO_NATIONAL_CHANNEL |
| GE | Georgia | DONE | 33c0dca57766 | 158 / 4,075 | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| DE | Germany | DONE | 4911b83beea2 | 6,127 / 129,983 | yes | DONE | NO_NATIONAL_CHANNEL | NO_NATIONAL_CHANNEL |
| GH | Ghana | DONE | c19c1fb59bc2 | 101 / 8,572 | yes | NOT_SURVEYED | BLOCKED_SOURCE | BLOCKED_SOURCE |
| GR | Greece | DONE | a3df2d112411 | 6,988 / 4,656 | yes | NOT_SURVEYED | BLOCKED_SOURCE | BLOCKED_SOURCE |
| GD | Grenada | DONE | 50132c510a29 |  | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| GT | Guatemala | DONE | d03bf173cd7c | 235 / 2,057 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| GN | Guinea | DONE | c330b9fc21b5 |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| GW | Guinea-Bissau | DONE | a8f9cc04584f |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| GY | Guyana | DONE | b0752848c53b |  | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| HT | Haiti | DONE | c938fe61f3cd |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| HN | Honduras | DONE | be98536b6872 | 200 / 7,730 | yes | BLOCKED_SOURCE | NEEDS_PERMISSION | BLOCKED_SOURCE, NEEDS_PERMISSION |
| HU | Hungary | DONE | 88ecd571972f | 380 / 10,520 | yes | NOT_SURVEYED | BLOCKED_SOURCE | BLOCKED_SOURCE |
| IS | Iceland | DONE (LIVE) | b4b6f9eefa6e | 917 / 23,768 | yes | N/A | QUEUED |  |
| IN | India | DONE | 051f15283bfc | 849 / 35,400 | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| ID | Indonesia | DONE | 796ca261e322 | 1,924 / 105,645 | yes | READY | IN_PROGRESS |  |
| IR | Iran | DONE | fe1c82dfab44 | 3,324 / 11,361 | yes | NOT_SURVEYED | BLOCKED_SOURCE | BLOCKED_SOURCE |
| IQ | Iraq | DONE | 1be4f2009a68 | 76 / 335 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| IE | Ireland | DONE | 888c3cea15ef | 3,953 / 7,716 | yes | NOT_SURVEYED | NO_NATIONAL_CHANNEL | NO_NATIONAL_CHANNEL |
| IL | Israel | DONE | 86221a671797 | 995 / 7,915 | yes | BLOCKED_TERMS | NEEDS_PERMISSION | BLOCKED_TERMS, NEEDS_PERMISSION |
| IT | Italy | DONE (UNLOCK_PENDING) | 681b49661ec2 | 203,128 / 31,443 | yes | READY | READY |  |
| JM | Jamaica | DONE | 55281e1c39d2 | 302 / 9,328 | yes | BLOCKED_SOURCE | NEEDS_PERMISSION | BLOCKED_SOURCE, NEEDS_PERMISSION |
| JP | Japan | DONE | 8679bf08620e | 2,103 / 178,632 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| JO | Jordan | DONE | bd8dd9fb9fe1 | 1,229 / 28,645 | yes | NOT_SURVEYED | IN_PROGRESS |  |
| KZ | Kazakhstan | DONE | b99006fea61b | 390 / 23,665 | yes | NEEDS_PERMISSION | NEEDS_PERMISSION | NEEDS_PERMISSION |
| KE | Kenya | DONE | 27b81c642fec | 261 / 9,802 | yes | NOT_SURVEYED | IN_PROGRESS |  |
| KI | Kiribati | DONE | 32b6f34aefd1 |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| KP | North Korea | DONE (BLOCKED_SOURCE) | 24a3cad871b2 |  | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| KR | South Korea | DONE | a174ce3d2e51 | 5,659 / 174,324 | yes | READY | IN_PROGRESS |  |
| KW | Kuwait | DONE (HOLD_THIN) | bd40bf9d68b5 | 93 / 0 | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| KG | Kyrgyzstan | DONE | 3adfd953b02b |  | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| LA | Laos | DONE | e1a4c77adecd | 2,550 / 19,985 | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| LV | Latvia | DONE | 047b73ac47dd | 85,628 / 885,028 | yes | NOT_SURVEYED | IN_PROGRESS |  |
| LB | Lebanon | DONE | ea3f4b4af18f | 40 / 54 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| LS | Lesotho | DONE | f92fc7f5c27f |  | yes | BLOCKED_TERMS | BLOCKED_SOURCE | BLOCKED_SOURCE, BLOCKED_TERMS |
| LR | Liberia | DONE | aa4f84dc94fa |  | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| LY | Libya | DONE | d46fc6a85eaa | 69 / 692 | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| LI | Liechtenstein | DONE | 9a0cf396c086 |  | yes | N/A | N/A |  |
| LT | Lithuania | DONE | e05ad958959f | 7,492 / 37,693 | yes | NOT_SURVEYED | BLOCKED_SOURCE | BLOCKED_SOURCE |
| LU | Luxembourg | DONE | ffc59f665caa | 1,354 / 38,335 | yes | N/A | NEEDS_PERMISSION | NEEDS_PERMISSION |
| MG | Madagascar | DONE | f94916739687 |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| MW | Malawi | DONE | e6767e7ec365 | 3,565 / 4,163 | yes | BLOCKED_TERMS | NO_NATIONAL_CHANNEL | BLOCKED_TERMS, NO_NATIONAL_CHANNEL |
| MY | Malaysia | DONE | 9f15e2d97c44 | 1,501 / 8,957 | yes | NO_NATIONAL_CHANNEL | NO_NATIONAL_CHANNEL | NO_NATIONAL_CHANNEL |
| MV | Maldives | DONE | 7c8f75f3868a | 2,535 / 1,678 | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| ML | Mali | DONE | dea9e0d1bd07 |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| MT | Malta | DONE | 404a1774ff3b | 19,675 / 128,394 | yes | N/A | DONE |  |
| MH | Marshall Islands | DONE | 74821456297a | 884 / 3,119 | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| MR | Mauritania | DONE | d97f455627dc |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| MU | Mauritius | DONE | 94566e522d28 |  | yes | NOT_SURVEYED | IN_PROGRESS |  |
| MX | Mexico | DONE | 1e47d5b641b0 | 317 / 44,168 | yes | NEEDS_PERMISSION | NEEDS_PERMISSION | NEEDS_PERMISSION |
| FM | Micronesia | DONE | aece546f4dbc |  | yes | BLOCKED_TERMS | NO_NATIONAL_CHANNEL | BLOCKED_TERMS, NO_NATIONAL_CHANNEL |
| MD | Moldova | DONE | 8c6bc269d103 | 402 / 9,207 | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| MC | Monaco | DONE | 1d930b8966ee | 862 / 438 | yes | N/A | N/A |  |
| MN | Mongolia | DONE | c2564ea95a50 | 773 / 22,129 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| ME | Montenegro | DONE | 0923d27ec500 | 700 / 1,879 | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| MA | Morocco | DONE | 8fed9ac782c4 | 482 / 2,233 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| MZ | Mozambique | DONE | 6f080529e748 | 155 / 5,267 | yes | NOT_SURVEYED | IN_PROGRESS |  |
| MM | Myanmar | DONE (HOLD_THIN) | 13e18ca290ce | 73 / 0 | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| NA | Namibia | DONE | 256c49d9a67d | 160 / 5,791 | yes | NOT_SURVEYED | IN_PROGRESS |  |
| NR | Nauru | DONE | 41eb38ee2113 | 466 / 10,936 | yes | BLOCKED_SOURCE | N/A | BLOCKED_SOURCE |
| NP | Nepal | DONE | 22395665af98 | 52 / 1,229 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| NL | Netherlands | DONE | 58982353b51d | 18,626 / 18,626 | yes | NOT_SURVEYED | IN_PROGRESS |  |
| NZ | New Zealand | DONE | 50544050b5a8 | 1,668 / 87,828 | yes | NOT_SURVEYED | BLOCKED_SOURCE | BLOCKED_SOURCE |
| NI | Nicaragua | DONE | 59efc0b35ac8 | 278 / 14,597 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| NE | Niger | DONE | e27a3d51e154 |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| NG | Nigeria | DONE | acc86f29d874 | 222 / 7,216 | yes | NEEDS_PERMISSION | NEEDS_PERMISSION | NEEDS_PERMISSION |
| MK | North Macedonia | DONE | dc4436515779 | 123 / 1,483 | yes | BLOCKED_SOURCE | NO_NATIONAL_CHANNEL | BLOCKED_SOURCE, NO_NATIONAL_CHANNEL |
| NO | Norway | DONE | e7127ddcf815 | 5,872 / 97,340 | yes | NOT_SURVEYED | BLOCKED_TERMS | BLOCKED_TERMS |
| OM | Oman | DONE | 5541edef3d9f | 1,679 / 1,743 | yes | BLOCKED_SOURCE | NEEDS_PERMISSION | BLOCKED_SOURCE, NEEDS_PERMISSION |
| PK | Pakistan | DONE | f64d60c2a991 | 958 / 4,189 | yes | NEEDS_PERMISSION | NEEDS_PERMISSION | NEEDS_PERMISSION |
| PW | Palau | DONE | cfe244d07d2b | 107 / 471 | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| PA | Panama | DONE | 2c7977edd65c | 425 / 15,133 | yes | BLOCKED_SOURCE | NO_NATIONAL_CHANNEL | BLOCKED_SOURCE, NO_NATIONAL_CHANNEL |
| PG | Papua New Guinea | DONE | a7527b285391 | 113 / 405 | yes | BLOCKED_SOURCE | NO_NATIONAL_CHANNEL | BLOCKED_SOURCE, NO_NATIONAL_CHANNEL |
| PY | Paraguay | DONE | 2e8736d28819 | 427 / 5,356 | yes | BLOCKED_SOURCE | NO_NATIONAL_CHANNEL | BLOCKED_SOURCE, NO_NATIONAL_CHANNEL |
| PE | Peru | DONE | b9d7781812a5 | 1,735 / 13,221 | yes | NOT_SURVEYED | IN_PROGRESS |  |
| PH | Philippines | DONE | 2f7ee80e0ff2 | 10,870 / 33,589 | yes | NOT_SURVEYED | NO_NATIONAL_CHANNEL | NO_NATIONAL_CHANNEL |
| PL | Poland | DONE | fdbce4d4fb14 | 39,298 / 533,538 | yes | NOT_SURVEYED | NEEDS_PERMISSION | NEEDS_PERMISSION |
| PT | Portugal | DONE | ddf64fdbbf0c | 6,541 / 52,977 | yes | READY | IN_PROGRESS |  |
| QA | Qatar | DONE | 238102e09d63 | 2,796 / 23,619 | yes | BLOCKED_SOURCE | NEEDS_PERMISSION | BLOCKED_SOURCE, NEEDS_PERMISSION |
| RO | Romania | DONE | 5828122eb9a5 | 81,872 / 23,984 | yes | NOT_SURVEYED | NO_NATIONAL_CHANNEL | NO_NATIONAL_CHANNEL |
| RU | Russia | DONE | c81227eb09f7 | 12,390 / 65,184 | yes | READY | BLOCKED_SOURCE | BLOCKED_SOURCE |
| RW | Rwanda | DONE | 234f956fd27d | 1,926 / 48,685 | yes | NEEDS_PERMISSION | NEEDS_PERMISSION | NEEDS_PERMISSION |
| KN | Saint Kitts and Nevis | DONE | 7debf0584c36 |  | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| LC | Saint Lucia | DONE | fa487689caec |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| VC | Saint Vincent and the Grenadines | DONE | 0e65f6ff9569 |  | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| WS | Samoa | DONE | 1db7f49bfb36 |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| SM | San Marino | DONE (HOLD_REPAIR) | f18d1dcc063b |  | yes | N/A | N/A |  |
| ST | Sao Tome and Principe | DONE | d7dc8feb75b0 |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| SA | Saudi Arabia | DONE | 94bd316e19d5 | 623 / 10,467 | yes | NOT_SURVEYED | IN_PROGRESS |  |
| SN | Senegal | DONE | dd57e78c5ba3 | 85 / 9,556 | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| RS | Serbia | DONE | c27db0988d43 | 3,412 / 41,579 | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| SC | Seychelles | DONE | 18e49bfef602 |  | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| SL | Sierra Leone | DONE | 4e62de61f623 |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| SG | Singapore | DONE | ee26bc9d91a5 | 701 / 5,029 | yes | N/A | N/A |  |
| SK | Slovakia | DONE | b28c2e913f97 | 16,799 / 147,423 | yes | NOT_SURVEYED | NO_NATIONAL_CHANNEL | NO_NATIONAL_CHANNEL |
| SI | Slovenia | DONE | 8ba5be36c89f | 236,538 / 1,515,677 | yes | NOT_SURVEYED | IN_PROGRESS |  |
| SB | Solomon Islands | DONE | c921827129d0 |  | yes | BLOCKED_SOURCE | NEEDS_PERMISSION | BLOCKED_SOURCE, NEEDS_PERMISSION |
| SO | Somalia | DONE | ac6aefed0dbe |  | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| ZA | South Africa | DONE | fdf0f845d185 | 822 / 4,516 | yes | READY | IN_PROGRESS |  |
| SS | South Sudan | DONE | 9e2fc87393bf | 80 / 535 | yes | NO_NATIONAL_CHANNEL | NO_NATIONAL_CHANNEL | NO_NATIONAL_CHANNEL |
| ES | Spain | DONE | ed0ac217106e | 8,766 / 324,828 | yes | DONE | NEEDS_PERMISSION | NEEDS_PERMISSION |
| LK | Sri Lanka | DONE (LIVE) | 9d51b86ad1d8 | 5,801 / 2,915 | yes | NEEDS_PERMISSION | NO_NATIONAL_CHANNEL | NEEDS_PERMISSION, NO_NATIONAL_CHANNEL |
| SD | Sudan | DONE | 6a063943f9df |  | yes | NO_NATIONAL_CHANNEL | NO_NATIONAL_CHANNEL | NO_NATIONAL_CHANNEL |
| SR | Suriname | DONE | ca87c3f430c5 |  | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| SE | Sweden | DONE | 0a1e752cb178 | 9,982 / 16,690 | yes | NOT_SURVEYED | NO_NATIONAL_CHANNEL | NO_NATIONAL_CHANNEL |
| CH | Switzerland | DONE | 7f9da5c86658 | 5,086 / 15,260 | yes | DONE | NEEDS_PERMISSION | NEEDS_PERMISSION |
| SY | Syria | DONE | 8d2537ff5585 |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| TJ | Tajikistan | DONE | a65dcc660a43 | 497 / 4,937 | yes | BLOCKED_SOURCE | NO_NATIONAL_CHANNEL | BLOCKED_SOURCE, NO_NATIONAL_CHANNEL |
| TZ | Tanzania | DONE | 1ad5c4b57b39 | 101 / 6,340 | yes | NEEDS_PERMISSION | IN_PROGRESS | NEEDS_PERMISSION |
| TH | Thailand | DONE (HOLD_THIN) | cde9df4f9b72 | 281 / 0 | yes | NOT_SURVEYED | BLOCKED_SOURCE | BLOCKED_SOURCE |
| TL | Timor-Leste | DONE | d9398c2b3567 |  | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| TG | Togo | DONE | 5d6406438adc |  | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| TO | Tonga | DONE | 7a3c6262c6de |  | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| TT | Trinidad and Tobago | DONE | 9bd47e8883c1 | 237 / 10,072 | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| TN | Tunisia | DONE | 1a7ce2f5664b | 3,467 / 76,586 | yes | NOT_SURVEYED | IN_PROGRESS |  |
| TR | Türkiye | DONE | eba740f7b32b | 917 / 37,879 | yes | BLOCKED_SOURCE | NO_NATIONAL_CHANNEL | BLOCKED_SOURCE, NO_NATIONAL_CHANNEL |
| TM | Turkmenistan | DONE | ce38a3085e08 |  | yes | NEEDS_PERMISSION | NEEDS_PERMISSION | NEEDS_PERMISSION |
| TV | Tuvalu | DONE | d7f84a3a4ff7 | 289 / 8,141 | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| UG | Uganda | DONE | 6ac04f94f100 | 126 / 7,166 | yes | NOT_SURVEYED | IN_PROGRESS |  |
| UA | Ukraine | DONE | 14a17aeb15e0 | 7,586 / 45,548 | yes | NOT_SURVEYED | NO_NATIONAL_CHANNEL | NO_NATIONAL_CHANNEL |
| AE | United Arab Emirates | DONE | 400423ae7692 | 237 / 12,566 | yes | NEEDS_PERMISSION | NEEDS_PERMISSION | NEEDS_PERMISSION |
| GB | United Kingdom | DONE | ef0cc003db30 | 156,830 / 1,669,352 | yes | READY | DONE |  |
| US | United States | SKIPPED (SKIP_US) |  |  | no | SKIPPED | SKIPPED |  |
| UY | Uruguay | DONE | 5d30cc830c7a | 4,537 / 31,871 | yes | NEEDS_PERMISSION | NEEDS_PERMISSION | NEEDS_PERMISSION |
| UZ | Uzbekistan | DONE | f2969f250b6b | 111 / 1,788 | yes | NEEDS_PERMISSION | NEEDS_PERMISSION | NEEDS_PERMISSION |
| VU | Vanuatu | DONE | 755173efca8c | 89 / 1,062 | yes | BLOCKED_SOURCE | NO_NATIONAL_CHANNEL | BLOCKED_SOURCE, NO_NATIONAL_CHANNEL |
| VE | Venezuela | DONE | fa24f9ef360a |  | yes | NO_NATIONAL_CHANNEL | BLOCKED_SOURCE | BLOCKED_SOURCE, NO_NATIONAL_CHANNEL |
| VN | Viet Nam | DONE | 5088d10cf67c | 700 / 29,215 | yes | NEEDS_PERMISSION | NEEDS_PERMISSION | NEEDS_PERMISSION |
| YE | Yemen | DONE | 2a18a87063c1 |  | yes | NEEDS_PERMISSION | BLOCKED_SOURCE | BLOCKED_SOURCE, NEEDS_PERMISSION |
| ZM | Zambia | DONE | c1a9085ff47f | 2,501 / 8,074 | yes | BLOCKED_SOURCE | BLOCKED_SOURCE | BLOCKED_SOURCE |
| ZW | Zimbabwe | DONE | 30b9434df496 | 411 / 15,508 | yes | BLOCKED_SOURCE | DONE | BLOCKED_SOURCE |
| VA | Holy See | NOT_COLLECTED |  |  | no | N/A | N/A |  |
| PS | Palestine | DONE | 3dfb5eba2ced | 3,178 / 12,820 | yes | NOT_SURVEYED | IN_PROGRESS |  |
| TW | Taiwan | DONE | 4b2305d5d9ae | 14,966 / 307,040 | yes | NOT_SURVEYED | BLOCKED_SOURCE | BLOCKED_SOURCE |
| XK | Kosovo | DONE | 605c2d3fe517 | 90 / 1,780 | yes | NEEDS_PERMISSION | NEEDS_PERMISSION | NEEDS_PERMISSION |
| CK | Cook Islands | DONE | 197f309a560b |  | yes | BLOCKED_SOURCE | NEEDS_PERMISSION | BLOCKED_SOURCE, NEEDS_PERMISSION |
| NU | Niue | DONE | 097999244810 |  | yes | NEEDS_PERMISSION | N/A | NEEDS_PERMISSION |

Hubs on HF not mapped to a tracker row: ipfs_anguilla_laws, ipfs_aruba_laws, ipfs_bermuda_laws, ipfs_british_virgin_islands_laws, ipfs_cayman_laws, ipfs_curacao_laws, ipfs_eu_laws, ipfs_hongkong_laws, ipfs_montserrat_laws, ipfs_puerto_rico_laws, ipfs_sint_maarten_laws, ipfs_turks_caicos_laws


## Update 2026-10-15 (PT) - NL-M tranche 1

- Published `justicedao/ipfs_netherlands_municipal_laws` (dataset): CVDR ids 600000..767599, current law only, **61,655 laws / 925,208 units** (809,984 articles, 78,215 sections, 37,009 annexes), 375 jurisdictions (gemeente 57,975, provincie 2,500, waterschap 1,180). License CC0-1.0 (KOOP); the repository host serves no robots.txt (HTTP 404).
- Scan status in range (143,600 of 167,600 ids scanned): ok 61,661 (6 expired before build), expired 60,330, absent 15,626, in_force_out_of_scope 3,831, stop_lvbb_xml_unsupported 1,881, future_only 109, in_force_no_text_in_xml 89, no_xml 56, fetch_fail_xml 8, manifest_parse_fail 7, fetch_fail_manifest 2.
- **GAP:** ids 640600..664399 (24,000) were scanned on an earlier boot whose disk is not currently reachable; not in tranche 1; to be appended as tranche 2 after the disk union.
- A UTF-8 BOM manifest parsing bug (about 25.7k ids in 600600..640398) was fixed in `collectors/nl_municipal_collect.py` and those ids were rescanned (finished 2026-10-15); `retrieved_at` of 6,754 rows rebuilt from cached raw XML is the cached file mtime.
- Scan continues below id 600000 (tranche 2 candidates).
