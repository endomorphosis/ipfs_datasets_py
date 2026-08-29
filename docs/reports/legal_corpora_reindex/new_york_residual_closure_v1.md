# New York residual closure v1

Date: 2026-08-29
Board: `legal-corpora-reindex-v1`
Task: `LCR-103`
Track: `exact51-residual-wave-d`
Status: **39 source-proved decisions closed; retained replay complete; not sealed; not publication-authorized**

This report supersedes the earlier 209-row projection. It records a fresh
retained evidence generation, fixed fail-closed resolvers, and a complete
filesystem-only replay of all 94 New York consolidated laws. No full corpus
job, remote publication, or Hub mutation was performed.

## Exact identity

| Field | Value |
|---|---|
| jurisdiction | NY |
| official domain | www.nysenate.gov |
| official_pdf_domain | legislation.nysenate.gov |
| official_assembly_domain | assembly.ny.gov |
| official entry | `https://www.nysenate.gov/legislation/laws` |
| official_consolidated_url | `https://www.nysenate.gov/legislation/laws/CONSOLIDATED` |
| corrected_evidence_root | `/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260828-ny-corrected-evidence-cgGxfD` |
| corrected_inventory | `NY/inventories/903f27eb0b34c54e3a167ff811e2eb327fa50eb28d14796077c5aec43c09d5f6.json` |
| corrected_blocker | `NY/blockers/65a124fdb40824bcccd8310e65c3214bf030c10e53d626f95ddf6fd7663bec9c.json` |
| corrected_seed | 99 selected inputs: 95 catalog/PDF plus four substantive Senate pages |
| corrected_audited_identity | 37441 = 36477 operative + 752 terminal + 212 unresolved |
| corrected_audited_closed_laws | 70 |
| corrected_audited_event_rows | 183 |
| corrected_audited_senate_version_rows | 29 |
| corrected_unresolved_projection_sha256 | `482b7e60020ad20e2ce6bdd49ef1f9870f9d94269d00f1345c4d1c912b1604b1` |
| retained_evidence_root | `/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260828-ny-closure-evidence-v2-85Omy9` |
| retained_selected_input_count | 110 |
| retained_unique_content_object_count | 110 |
| retained_selected_projection_sha256 | `0a153391b342a56f2c8baa1760eefbc78686a7ae713263f466ee56ee9dc8452c` |
| retained_proof_manifest_count | 15 |
| retained_proof_manifest_sha256 | `0c90f800f56d197fe53f7d177a7ba4b2bd26b70a860e57da97423d0ad48b643b` |
| retained_replay_identity | 37441 = 36498 operative + 770 terminal + 173 unresolved |
| retained_replay_closed_laws | 73 |
| retained_replay_open_laws | 21 |
| retained_unresolved_projection_sha256 | `da20ba612eb0f67887cdfb6b2369c5ed3dfc79e95208cfac5dbdd0803ae23a7c` |
| senate_28_attempt_root | `/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260829-ny-senate-28-v2-HfGAC3` |
| senate_28_attempt_classification | 28 HTTP 200 responses: 4 substantive and retained; 24 soft-not-found and rejected |
| senate_28_classification_projection_sha256 | `fe8f770592dcb88f0699ab278a0bfaa36662f5f329dc91c168ea1f56dae6a794` |
| senate_28_retained_projection_sha256 | `c9bc5989b9346ed840785d2f51bff104ad86acb60bd4cb1058faf3184517bb0b` |
| env_7_locator_root | `/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260829-ny-env-seven-locators-v2-I8ss1B` |
| env_7_locator_count | 7 direct official HTTP 200 inputs |
| env_7_locator_projection_sha256 | `fdf73292f378ca1fb5ac421322800aaef2c6cc8595e9a749ee366aefdaab9b91` |
| agm28_lifecycle_report_url | `https://agriculture.ny.gov/system/files/documents/2023/02/urbanruralconsumeraccessreport.pdf` |
| agm28_lifecycle_report_sha256 | `6abaab50ad7bf3bec0c5c98949de8d543bdb4fb8b869f13a824776d39ed8580d` |
| agm28_direct_status | HTTP 200; exact digest matched |
| signed_bill_proof_count | 2 |
| signed_bill_wave_name | `signed-assembly-bill-records-1-2` |
| signed_bill_url_projection_sha256 | `ef7e526c284aa62b725b457639b71707627482ac9b35ea76ff8bf74ad48a8a31` |
| projected_identity_after_bounded_direct_wave | 37441 = 36477 operative + 755 terminal + 209 unresolved |
| projected_closed_laws | 73 |
| remaining_event_rows | 146 |
| remaining_senate_version_rows | 27 |
| remaining_unresolved_rows | 173 |
| remaining_senate_wave_url_count | 28 |
| remaining_senate_wave_name | `source-derived-supplemental-sections-1-28` |
| remaining_senate_wave_sha256 | `b03131cd20eb808d159427e548a732a078fc7b3f94291a2c5fff8a4cd206dde0` |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| host_retained_replay_network_requests | 0 required |

The corrected audited starting identity was:

```text
37,441 = 36,477 operative + 752 terminal + 212 unresolved
212 = 183 official event-condition decisions + 29 Senate/version decisions
```

The retained replay closes 39 exact decisions:

```text
operative: ENV +4, MHY +15, COR +1, RSS +1
terminal:  AGM +1, CPL +1, EDN +1, MAC/PBA +15

37,441 = 36,498 operative + 770 terminal + 173 unresolved
173 = 146 official event-condition decisions + 27 Senate/version decisions
73 of 94 laws closed; 21 laws remain open
```

There were no unmatched residual rows against the corrected inventory.

## Retained official proofs and typed dispositions

All network inputs below were retained with their exact raw body, raw SHA-256,
receipt, sanitized request, transport, URL, media type, byte count, and
retrieval timestamp. Each resolver also pins a stable semantic projection and
fails closed if any required legal conjunct or source identity drifts.

### Direct and signed-session-law closures

- AGM §28 is terminal because the named official Agriculture and Markets
  report was delivered. Raw SHA-256:
  `6abaab50ad7bf3bec0c5c98949de8d543bdb4fb8b869f13a824776d39ed8580d`.
- CPL §150.30 is repealed effective 2020-01-01. The official Assembly A02009C
  record at
  `https://assembly.ny.gov/leg/?Actions=Y&Summary=Y&Text=Y&bn=A02009&term=2019`
  pins signed Chapter 59, the Part JJJ repeal, and the same-Part effective
  clause. Semantic SHA-256:
  `83609b2646f17478c3b6cbfbfa21400eeb4ba10cacb778afa2659cccc0358be7`.
- Education Law §666 is repealed effective 2025-05-09. The official Assembly
  A03006C record at
  `https://assembly.ny.gov/leg/?Actions=Y&Summary=Y&Text=Y&bn=A03006&term=2025`
  pins signed Chapter 56, the Part D repeal, and its immediate effective
  clause. Semantic SHA-256:
  `3a212979e4428f98acfad78f033949c7abb2b09f8ffe0ac7c24c46dec6d94a02`.

### ENV §§9-2301 through 9-2304

The original seven-locator candidate bundle was acquired as seven direct
HTTP 200 responses in its own clean retained generation. The exact raw rows
are:

| Official URL | Bytes | Raw SHA-256 | Receipt SHA-256 |
|---|---:|---|---|
| `https://www.nysenate.gov/legislation/bills/2025/A7454` | 94,159 | `5db0eaa57c32b52e1f45518c2387520944c7df9db7a40c263f98b4e834b098c5` | `969675c96b365c0ca074c807c6c6486352ca16ddf214e34bc339c12002c48a34` |
| `https://www.nysenate.gov/legislation/bills/2025/S5227` | 129,713 | `df1565adbf964ed39136b919515ae1388c58d0e71de47da42d88cf70eeeb26be` | `4f4602c9615e9c719187d6cc2c9e8a18df20086dcdcbe2b1a5c4240e16f5ef06` |
| `https://www.nysenate.gov/legislation/bills/2025/S8047` | 101,904 | `d68d960c0ce0e1c93369b91542bec185fa88de7e526e54bd0daf5d5bbcde7ec8` | `e5edc82dc5a845a42a2b53bd0964a7304fcaca9e6c2066210c1add04f93a3e8a` |
| `https://elections.ny.gov/2025-statewide-ballot-proposal` | 61,148 | `7ecfd5c5c9c29129ffa0933606f55c554d7509fb464f27180995fac23c27ab39` | `71c477cd61dd7cfe208375bcca0d8e84eeb9fc978885dc455034553a27908cdb` |
| `https://results.elections.ny.gov/contest/5860` | 209,281 | `ab6e65f3db7b5d217c889d5c2f4c5a1a03c4312efc6a7f639469ea6f247aff7d` | `853b9ebe078255eae769190a9752fef9039b43eb19240edb34af317bc5455772` |
| `https://results.elections.ny.gov/document/482` | 124,260 | `ef3f088a92963ec547d37c9315912e2344380582593115b1f79954254a6bc036` | `b092a77b0a3d8f054fbf4fb7f755d43d31f5c491a021aa7ef478c718e239f674` |
| `https://www.nysenate.gov/legislation/laws/CNS/A14S1` | 47,334 | `75391bddabf3b48d7f0c3a3bc46af0515111d97106dd75e96f46c1f5db7cc35c` | `1ed03cd08980a49a7bc47e9a2b528cf5dd80aca258de4b6ca7c9cc29ec39a0b3` |

The seven-locator projection is the canonical URL-sorted JSON projection of
URL, raw and receipt digests, byte count, media type, and retrieval timestamp.

Those research locators establish the proposal and vote record, but the
admitted resolver uses a stronger four-record official chain: the Assembly
concurrent-resolution record, the signed implementation record, and the
current Article XIV and Article XIX constitutional sections.

| Official URL | Raw SHA-256 | Receipt SHA-256 |
|---|---|---|
| `https://assembly.ny.gov/leg/?Actions=Y&Summary=Y&Text=Y&bn=A07454&term=2025` | `263bb9d369ada41b5b212be86560c6ba74a3547d3cecdfe6998c3953269eb0e4` | `77f6385d043909a6b8ad11d15642a4118ecfebd14339940107b02d9908088d45` |
| `https://assembly.ny.gov/leg/?Actions=Y&Summary=Y&Text=Y&bn=A03628&term=2025` | `4f297f5c565668d3252298cf994fa834d8872360f63509bcfe57b279ea8a5a55` | `f39e8085cac10466fb299901302d29b9425edd4f0bff87b912b4c39c914966d7` |
| `https://www.nysenate.gov/legislation/laws/CNS/A14S1` | `74c3592b99cd2d53d1117c24b8d73e883a90009df86ce8bb8911cf1b62e14756` | `d1a53464fe0a43ec2eddcdd1b3c72f1eb789a28af19821834d825e7b732d66c8` |
| `https://www.nysenate.gov/legislation/laws/CNS/A19S1` | `6142b13124be7d5f554cc00b2d00b6bf51bc37c4e1ebfa5faa7ddf4c5cd4e9d7` | `54412ac5d46595e402203204cfc840ee5ff517ed55cd95b38573fcb46981391d` |

The stable four-source projection SHA-256 is
`d8a0b122f30db8d19162c9c6fb195d7ef8725f227d2ded7a15c8dc0af748e57d`.
It proves the four sections operative effective 2026-01-01.

### MHY Article 82 and MAC/PBA title 10

- The official 2025-08-20 State Register at
  `https://dos.ny.gov/system/files/documents/2025/08/082025.pdf` has raw
  SHA-256
  `e9fc4f3ed8d434edc0311b018101db5152f46821a60139aeceeb0aaf84b8c0dd`
  and semantic SHA-256
  `56a4639fec369eaa7b9c0bcafebc049497fe462150169c6bdcec46bcdbf7360d`.
  It proves MHY §§82.01-.15 operative effective 2025-11-18.
- The official New York City financial statement at
  `https://www.nyc.gov/assets/investorrelations/downloads/pdf/go-bonds-statements/2011/nycgo-2011f.pdf`
  has raw SHA-256
  `dd8066805f497b94bc2497b42a25be882d70360ee7f56f36912748d10f4480d7`
  and semantic SHA-256
  `56803160ce2f27076cc5eff975fc9daa13429153fa0d709812d3862b7badd044`.
  It proves the MAC liability discharge and types PBA §§3030-3041 terminal,
  expired 2009-09-30.

### COR §851 parser reconciliation

The official Correction Law PDF contains one uniquely dated current version
(`Effective until September 1, 2027`), a dated future replacement, and an
older event-conditioned alternate. The parser now lets that unique dated
current version control for the legal-as-of snapshot and retains the other
two bodies as lifecycle alternates. No external-event assumption is made.

### RSS §1204-a two-record event chain

| Official URL | Bytes | Raw SHA-256 | Receipt SHA-256 |
|---|---:|---|---|
| `https://legislation.nysenate.gov/pdf/bills/2011/S5837` | 7,148 | `48d0029397e4b7c6e7392ad15a5f18e8b01a5cf3ede3460727b1a9d35d4c5135` | `7f1b7038fd2fea42fa520c02f8fbd55de07a59d6acdc3b76e19e46515acc494d` |
| `https://www.osc.ny.gov/state-agencies/payroll-bulletins/state-agencies/1275-new-deduction-code-616-paf-retirement-tax-paf-btx-and-new-deduction` | 103,312 | `bdcc51aa2ce75775110eedaa80e56c0ea8f03b2ebf4812ce1fc39c4fdccb97ff` | `df0084850d8a47e65c16ed6a5c616460d427a8db90a55471cedb128dccd39f66` |

The enacted bill supplies the exact event formula. OSC Bulletin 1275 records
the favorable IRS ruling dated 2013-07-09 and the 414(h) payroll treatment
effective 2013-10-01. The individual semantic SHA-256 values are
`cc908cd562c6fb3d5e818812d1618e3c81cf1963590eeb54fff1853f05c4cef9`
and
`0c62cb0118bf665a5935f9214d4d4210c6fed5765aeda3fb60a7b6c1c522c8ca`;
the combined projection is
`c13fd0df9f5a8e0e898c562e02d6881d893f36bb9e0836dd10b7b951f48e3448`.
RSS §1204-a is operative effective 2013-10-01.

## Exhausted exact Senate/version wave

The production acquisition path derives and pins this ordered 28-URL wave:

```text
https://www.nysenate.gov/legislation/laws/EPT/3-6.5
https://www.nysenate.gov/legislation/laws/GBS/495-d
https://www.nysenate.gov/legislation/laws/GMU/902
https://www.nysenate.gov/legislation/laws/PBA/2799-aaaa
https://www.nysenate.gov/legislation/laws/EDN/669-c
https://www.nysenate.gov/legislation/laws/EDN/2023-b
https://www.nysenate.gov/legislation/laws/ELD/221
https://www.nysenate.gov/legislation/laws/ELN/3-408
https://www.nysenate.gov/legislation/laws/ELN/7-108
https://www.nysenate.gov/legislation/laws/ELN/8-310
https://www.nysenate.gov/legislation/laws/ELN/9-104
https://www.nysenate.gov/legislation/laws/ELN/9-128
https://www.nysenate.gov/legislation/laws/ELN/11-304
https://www.nysenate.gov/legislation/laws/ELN/17-140
https://www.nysenate.gov/legislation/laws/ELN/17-158
https://www.nysenate.gov/legislation/laws/EXC/236
https://www.nysenate.gov/legislation/laws/GMU/371-a
https://www.nysenate.gov/legislation/laws/ISC/3114
https://www.nysenate.gov/legislation/laws/MHY/7.48
https://www.nysenate.gov/legislation/laws/PAR/27.09
https://www.nysenate.gov/legislation/laws/SOS/364-j-1
https://www.nysenate.gov/legislation/laws/SOS/369-ii
https://www.nysenate.gov/legislation/laws/TAX/602
https://www.nysenate.gov/legislation/laws/TAX/622
https://www.nysenate.gov/legislation/laws/TAX/636
https://www.nysenate.gov/legislation/laws/TAX/1262-l
https://www.nysenate.gov/legislation/laws/VAT/235
https://www.nysenate.gov/legislation/laws/VAT/1180-i
```

Its ordered URL SHA-256 is
`b03131cd20eb808d159427e548a732a078fc7b3f94291a2c5fff8a4cd206dde0`.
The pin is computed as
`sha256("\n".join(urls).encode("utf-8"))`. Canonical proof manifests use
`json.dumps(..., ensure_ascii=False, separators=(",", ":"), sort_keys=True)`;
the two identities are deliberately distinct. The bounded wave names remain
`consolidated-catalog`, `full-law-pdfs-…`, `agm-28-lifecycle-selector`, and
`source-derived-supplemental-sections-1-28`.
Four substantive pages were already present in the corrected seed. The other
24 exact direct requests returned HTTP 200 soft-not-found shells, and permitted
grouped Common Crawl/Wayback recovery did not yield admissible historical
section bodies. The fresh direct classification projection SHA-256 is
`fe8f770592dcb88f0699ab278a0bfaa36662f5f329dc91c168ea1f56dae6a794`.
Only the four substantive pages were retained in the wave evidence root; their
exact retained projection SHA-256 is
`c9bc5989b9346ed840785d2f51bff104ad86acb60bd4cb1058faf3184517bb0b`.
Soft not-found shells remain excluded. Current-page absence is not proof, and
no per-page archive loop was used.

The 27 remaining decisions are:

```text
EDN 669-c; EDN 2023-b*2; ELD 221; ELN 3-408; ELN 7-108; ELN 8-310;
ELN 9-104; ELN 9-128; ELN 11-304; ELN 17-140; ELN 17-158; EXC 236;
GBS 495-d; GMU 371-a*2; ISC 3114; MHY 7.48; PBA 2799-aaaa;
SOS 364-j-1; SOS 369-ii; TAX 602; TAX 622; TAX 636; TAX 1262-l*2;
VAT 235*2; VAT 235*3; VAT 1180-i*5; VAT 1180-i*6
```

They require an exact official OpenLeg historical version, signed session
law, or other source that exposes the missing body/lifecycle note.

## Remaining event families

Exactly 146 event-conditioned rows remain in 17 families:

| Family | Rows | Official evidence status / blocker |
|---|---:|---|
| DFS 2025 Part Y rules | 16 | 2026 official DFS/DOS material is preproposal or agenda material; no final adoption/effective record found |
| DFS superintendent notification | 1 | Named issuance/receipt record and date not located |
| matching New Jersey enactment | 7 | Exact identical-effect NJ enactment not established; similarly themed enactments are not proof |
| DEC move to Albany | 1 | Current Albany headquarters is known, but the exact statutory move event/date record is missing |
| State BOE compact notification | 2 | Exact commissioner notification and date not located |
| DCJS/DOS §837-aa rules | 1 | Exact adoption plus State Register publication not located |
| GMU agency termination | 107 | Current OSC IDA roster is insufficient; the statute requires DOS nonfiling certificates and DED dissolved/ceased records for named agencies |
| DOT roadway completion | 1 | Exact project completion record and date not located |
| Insurance §5516-e schedule | 1 | Exact schedule submission/non-submission record and date not located |
| MHY reimbursement approval | 1 | Approval/certification under 2026 ch.60 §8 not located |
| PEN 2022 ch.205 condition | 1 | Official DCJS RFIs show investigation/testing, not the required technological-viability or servicing-entity event |
| Franchise Board appointments | 1 | Official records show a June 2017 transition, but not the exact majority-appointment/notice date needed for a typed date |
| IRS ruling for RPT §304 | 1 | Exact ruling and applicability/date not located |
| IRS ruling for RPT §926-a | 1 | Distinct exact ruling and applicability/date not located |
| LIRR election/Comptroller receipt | 2 | Exact election plus Comptroller receipt/date not located |
| DOH contract plus 16 years | 1 | Executed contract and execution date not located |
| DED notice to LBDC | 1 | Exact notice/receipt under 2019 ch.683 §6(2)(b) not located |

The rows with current official status evidence remain unresolved because the
required event has not yet been proved: DFS Part Y (draft/preproposal only),
PEN Chapter 205 (testing/RFI only), and the identified DCJS/DOS rulemaking
families. The other rows are genuine official-source or custodian-record
blockers after direct official research. General rosters, present-day agency
status, similarly themed laws, or absence from a current webpage are not
substitutes for the named statutory event.

## Verification and publication gate

The complete 94-law replay used only the retained ledger. It issued zero
network requests and reproduced the 15-input proof manifest and exact
37,441-row algebra above. Focused resolver/acquisition validation also covers
raw and semantic drift, mixed PDF/HTML proof media, source-derived residual
membership, and the COR dated-current parser rule.

- `test_new_york_residual_closure.py`: 41 passed.
- Retained 94-PDF New York baseline replay: 1 passed.
- `py_compile` and `git diff --check`: passed.

Before any later materialization, rerun host `--retained-replay-only` with
`--no-incremental-state-publish`; require 94/94 laws closed,
`37,441 = operative + terminal`, and first/replay frontier equality.

```bash
python -B scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states NY \
  --output-root /absent/fresh/new-york-replay-output \
  --scrape \
  --acquisition-evidence-root /home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260828-ny-closure-evidence-v2-85Omy9 \
  --retained-replay-only \
  --no-incremental-state-publish
```

Publication remains forbidden while 173 decisions are unresolved. This
worktree did not launch a corpus-scale job or mutate any remote service.
The generation was seeded from the exact 99-input corrected seed; copying an
evidence tree with Docker (`docker-copying`) is forbidden. An unresolved row
must never be silently emitted as current law.
