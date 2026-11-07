# STATUS b2 — Asia/Americas/Europe executor (Batch 2 from CoS)
Output root: ~/.ipfs_datasets/legal_collectors/ready_asia_americas_europe_b2/ (batch1 dir untouched). Hub re-read 2026-10-16 ~16:45 PT into /workspace/asia_americas_europe/hub_b2/ (revisions in MANIFESTs).
Strict verifier: /workspace/asia_americas_europe/verify_b2.py (every Hub law row identical in ALL columns except ids in ALLOW file; every Hub article row present; schema == Hub schema).

1. CN — DONE: b2/cn = batch1 parquets byte-identical (315/22,043; Hub still 295/21,454 rev 416a1b3e); README row 'Laws / instruments' -> 315. VA: already LIVE (ipfs_vatican_laws, 400/1,222), not in the audit-failed file; nothing to land, only the item-4 quality items.
2. SV — DONE: rebuilt on Hub rev d4c95b8a (325/12,937): 382 laws / 13,779 articles (+57 laws, +842 articles). All 325 Hub rows identical (incl. the 76 + 4). Note: 78 Hub SV rows have article_count != article rows (came with the 22:22Z merge); left exactly as the Hub has them.
3. article_count — DONE: iq 9 ids (Hub has moved: 363 laws), sn 37, vu 28 (Hub VU now 399 laws after Waves 8/9 on 10-13; 27 of the 28 came from those waves). ALLOW_article_count_ids.json + article_count_changes.json (old->new) in each pack. New value = actual article rows for the law id (many SN/VU become 0: the Hub claims articles that have no rows).
4. Quality — DONE: IQ title fixed; VA 2 stamp-only laws re-fetched (CC) + OCR -> b2/va 400/1,229; MZ mz-decreto-no-1-2010 listed for CoS approval (PDF not in CC). Milestone note: handoffs/20261016_asia_b2_items1-4_READY.txt
5. Big systems — PENDING (blocked on CC availability).
5. Big systems — RUNNING since 16:54 PT: one worker, queue MX IN VN CN PK TR (TH skipped: no real law text in CC, see batch1), cc_country_harvest.py OFFSET=200 max 500 per country, deduped against current Hub (hub_b2). Log: /workspace/asia_americas_europe/queue_b2.log. Then pack via build_b2.py -> conform_b2.py -> verify_b2.py -> manifest_b2.py.
   Note: index.commoncrawl.org/collinfo.json is flaky; b2q/shim.py supplies the collection list from data.commoncrawl.org instead (same S3 ranged-read flow).
   16:? round1 done: MX +142 laws/+9,291 arts (602/65,945), IN +97/+6,021 (1077/44,361), PK +4/+48 (970/41,986); VN/CN/TR 0 new from cached pointers -> round2 with older collections running (VN CN TR).
   17:30 PT: round2/3 found 0 CN because the zh law gate used \b (never matches inside Chinese text); fixed in lawgate.py (ZH_STRONG/ZH_POLICY/ZH_RULE + >=2 第N条). Round4 CN running.

17:35 PT CoS decisions: VA OCR not approved -> b2/va removed (Hub unchanged); MZ decreto left as Hub; uploads only after Verifier PASS (HF token present, user endomorphosis; no PASS yet).
MX/IN/PK packed+conformed+verified OK+manifested: mx 602/65,945 (+142/+9,291), in 1,077/44,361 (+97/+6,021), pk 970/41,986 (+4/+48).

17:55 PT: Verifier audit -> SN PASS, IQ PASS(+CoS OK): UPLOADED sn 9c3f7a97, iq e3c7d6d2. Fixed CN (314/22,318), SV (340/13,456), VU (string cast + README) -> handoffs/20261016_asia_b2_items1-4_fixes_READY.txt for re-audit; upload CN/SV/VU only after re-PASS. VA dropped from b2. VN round5 (congbao HTML allowed) running.
18:10 PT: item 5 closed: MX/IN/PK ready for audit; VN/TR 0 gains; CN +2 not added. handoffs/20261016_asia_b2_bigsystems_READY.txt

Re-audit: CN/SV/VU/PK PASS -> UPLOADED cn f18d968e, sv d43dfdae, vu 88abba62, pk 0d320c58. MX/IN fixed -> mx 560/61,263, in 1,072/43,997; handoffs/20261016_asia_b2_MX_IN_fixes_READY.txt (awaiting re-audit; not uploaded).
Round 2: IN UPLOADED 829e3770. MX round 3 fixes -> 560/61,255; handoffs/20261016_asia_b2_MX_round3_READY.txt (awaiting re-audit).
MX round 4 (4 titles) -> handoffs/20261016_asia_b2_MX_round4_READY.txt; awaiting re-audit; not uploaded.

## FINAL Batch 2 summary (2026-10-16 ~18:05 PT)
All uploads are additive, pinned to parent_commit, re-verified with verify_b2 right before each commit, and passed by the Verifier.
| Pack | Hub before | Live now | Commit |
|---|---|---|---|
| SN ipfs_senegal_laws | 422/15,304 | 422/15,304 (37 article_count fixes) | 9c3f7a97d955 |
| IQ ipfs_iraq_laws | 363/4,464 | 363/4,464 (9 article_count + gazette title) | e3c7d6d278c4 |
| CN ipfs_china_laws | 295/21,454 | 314/22,318 | f18d968eb082 |
| SV ipfs_elsalvador_laws | 325/12,937 | 340/13,456 | d43dfdaedb1e |
| VU ipfs_vanuatu_laws | 399/1,107 | 399/1,107 (28 article_count fixes, string cast) | 88abba620d3d |
| PK ipfs_pakistan_laws | 966/41,938 | 970/41,986 | 0d320c58ff4b |
| IN ipfs_india_laws | 980/38,340 | 1,072/43,997 | 829e377049c8 |
| MX ipfs_mexico_laws | 460/56,654 | 560/61,255 | 4372183d055e |
Not changed, per CoS: VA (no OCR; Hub stays as is), MZ mz-decreto-no-1-2010 (left as on the Hub).
No gains: VN, TR (gate rejects / no CC coverage), TH skipped. Blockers: pakistancode.gov.pk, mevzuat.gov.tr, resmigazete.gov.tr, laws.boe.gov.sa have no CC pointers; VN congbao HTML still rejected by the generic gate; 2 extra CN candidates not added; IN has 4 'Act is under updation' titles + 8 repeated-name titles left (soft).
