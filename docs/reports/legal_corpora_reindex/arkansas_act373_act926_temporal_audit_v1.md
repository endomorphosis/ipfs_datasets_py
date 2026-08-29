# Arkansas Act 373 / Act 926 temporal-source audit v1

Date: 2026-08-29
Board: `legal-corpora-reindex-v1`
Task: `LCR-099`
Base commit: `d6e225f628c2a5c5bcbae53a029f9d1905caffb3`
Status: **one exact enacted-body row closed; four genuine rows remain**
Publication: **not authorized**

This bounded continuation closes `23-4-909` from the exact official Act 373
body without selecting or guessing either delegated Lexis URN. It does not
close the Act 926 contingent pair. The retained rulemaking records concern
odometer-disclosure rules and do not establish either occurrence or
nonoccurrence of Act 926 section 12's separately defined systems-implementation
certification.

| Field | Value |
|---|---|
| temporal_status | partial_source_closure |
| temporal_current_bundle_sealed | false |
| temporal_authorizing_for_materialization | false |
| temporal_publication_authorized | false |
| temporal_rows_closed | 1 |
| temporal_closed_citations | 23-4-909 |
| temporal_unresolved_citations | 19-42-201, 27-14-802, 27-14-803, 5-64-308 |
| temporal_parser_change | exact Act 373 vector-aware enacted-body bridge for 23-4-909 only |
| temporal_full_state_live_to_retained_run | not launched; four source boundaries remain |
| act373_disposition | selected_current_source_body |
| act373_delegated_urn_selected | false |
| act373_source_input_count | 5 |
| act373_source_sha256 | fa0ad2a4dd3cef14da56065a2cd128caa29cacb4db3eb7544b4a67eecf4341c4 |
| act373_source_byte_size | 538638 |
| act373_page_count | 63 |
| act373_printed_pages | 6, 7, 62, 63 |
| act373_effective_date | 2025-03-20 |
| act373_current_text_sha256 | bd886059029338c2d76bc0e8027169740f96bedf6e7f9c9813d67d8746f93d85 |
| act373_geometry_sha256 | 522ba00fc5bccb10f2d193df7555aab5bf16ac4fa61a8f46520c82b659072c81 |
| act373_pagination_sha256 | bd5a8e30fcb45879a99b0b564eccf219d1ba6980b25befb8e910e1c6f38748e2 |
| act373_amendment_instruction_sha256 | d41ecd3f1398129b71323b46ba7a5e2ff9470798836220845d319014d74e530a |
| act373_markup_geometry_sha256 | 61848e6f48ed21875bc06a3a5b8f7773043092ccbd073368f07416f6e7365eed |
| act373_effective_date_geometry_sha256 | 90ad7aa341aeddfd23935b7048bf08abf4fad50f48f220ac3ac4a15a1ab7a3cf |
| act373_mark_projection_sha256 | 1137ecd61ed8691e461a2488765bb8906c3c73637a8747f3407a2533f3fe9699 |
| act373_inserted_words | 41 |
| act373_deleted_words | 9 |
| act373_authorizing_evidence_root | `/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260829-ar-act373-proof-Zyxt13` |
| act373_authorizing_parser_name | ArkansasCurrentVariantResolution |
| act373_authorizing_parser_inputs | 70 |
| act373_authorizing_direct_get_inputs | 70 |
| act373_authorizing_unique_objects | 70 |
| act373_authorizing_unique_urls | 70 |
| act373_authorizing_total_bytes | 29424058 |
| act373_authorizing_union_migration_receipt_sha256 | c43eed116eec85febb0b80ad0b3a66e13718f8ece00e9bcf89a93c44efb0589f |
| act373_authorizing_union_projection_sha256 | f5de87ae9fdc179f1650501c5126f6800ce925132a0709ac9ba258b46829c859 |
| act373_authorizing_retained_replay_inputs | 70 |
| act373_authorizing_retained_replay_network_requests | 0 |
| temporal_research_evidence_root | `/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260829-ar-temporal-proof-yNIRXa` |
| temporal_research_parser_name | ArkansasTemporalSourceAuditV1DiagnosticOnly |
| temporal_research_parser_inputs | 76 |
| temporal_research_direct_get_inputs | 71 |
| temporal_research_direct_post_inputs | 5 |
| temporal_research_unique_objects | 57 |
| temporal_research_unique_urls | 72 |
| temporal_research_total_bytes | 14614946 |
| temporal_research_union_migration_receipt_sha256 | 5cf4986a783543738d5aec6c4ef4ace3d180c851010d93f073afba3c6fe6c278 |
| temporal_research_union_projection_sha256 | ce3c9cc843e6499ec08ec7d349adf1a97c0f2af4fe8fad187db90d7911c4c612 |
| temporal_research_projection_sha256 | f53d83cddb9eadd3c64cfb26787972419591f9a5835d33c36186cc2a79081a10 |
| temporal_research_retained_replay_inputs | 76 |
| temporal_research_retained_replay_network_requests | 0 |
| temporal_preflight_selected | 127 |
| temporal_preflight_selected_current_source_body | 1 |
| temporal_preflight_no_current | 1 |
| temporal_preflight_unresolved | 4 |
| temporal_original_conflict_selected | 33 |
| temporal_original_conflict_unresolved | 4 |
| temporal_decision_sha256 | 3d75e491f3052a8decb129d8f4af27675cdbb24edaad27d6d96d674f9eb81e94 |
| temporal_act926_certification_locator | unidentified |
| temporal_act926_occurrence_encoded | false |
| temporal_act926_nonoccurrence_encoded | false |

## Act 373 exact enacted-body closure

The public act says that stricken language is deleted and underlined language
is added to present law. Section 11 then says that Arkansas Code § 23-4-909 is
amended to read as follows. The ordinary PDF text layer is not sufficient: it
places deleted and added words in the same text stream. The state-scoped bridge
therefore accepts only the exact 538,638-byte act and independently pins:

- all 63 physical pages and printed pages 6, 7, 62, and 63;
- the section 11 amendment instruction and the section 12 boundary;
- every word coordinate in the target section and every intersecting filled
  strike/underline rectangle;
- the section 31 emergency-clause path, the approval line, and the resulting
  `2025-03-20` effective date; and
- the complete 530-byte enacted result.

The resulting body is:

```text
23-4-909. Apportionment of rates and charges.
(a) Upon receipt of a sufficient number of valid petitions under § 23-4-905, the Arkansas Public Service Commission may inquire into the reasonableness of the apportionment of rates and charges by a co-op.
(b) When determining how rates and charges established under § 23-4-903 are to be allocated among different rate classes, a co-op shall endeavor to apportion the rates and charges in a manner consistent with, as closely as practicable, the last approved cost-of-service study.
```

The retained official inputs that authorize this one body are:

| Input | Body SHA-256 | Parser-input receipt SHA-256 | Transport receipt SHA-256 |
|---|---|---|---|
| Act 373 | fa0ad2a4dd3cef14da56065a2cd128caa29cacb4db3eb7544b4a67eecf4341c4 | 7bf39ff6d23152ed8c512ed2e2cd975cc2dccf1657667e83aaa034cb9810a555 | dfb189276b75ac5d96fcb2d528063e0335015b10c9253d02e65d8ccef497596f |
| Current Arkleg session contract | bcf72c798505d420a0a355dfcfa7dafab47de73cda8ce94298c9b67279cafae4 | 31602e094c6be0a96821106eec4c39d3973a4836fc2eb163aae5e6786e112e93 | e25234c7ee4c1cfe5025bf14f4f35c0b3536e096be43d0374fb7e83dac4169a0 |
| Title 23, 2025R change table | 5178070bc931f9766f31c96ec9c54b48445e1ebb114a7cc5c85d9d0d4f9b0ec4 | 8fa132250d0b6f85b8efb05b2a7ca2c1b7662f33b34ee0f8b46f76ab59c3c773 | d1effd19672196512de034eb1ea4ef0bc11e009ca9c2fae293fa9c546bcc09aa |
| Title 23, 2026F change table | ee56f5a91b00961947efd0004cae792deb71cddb4db48f1f49b4e310a09932b6 | 91c3e4889e0bedcfe5ac8697cafdc375196d4e598344e8015ddf8a5e4b142281 | 609aa91bbacab4dfb69db7a2ddf9b95fe694987fa6b2db8b2f0548406cb55581 |
| Title 23, 2026S1 change table | 69aba984cfa4fc083f7aaf2e382bc96c7cc4c20ac6891a5f330e583b46293a85 | db4928fb731cd6898a2f384eb6a1fb410b67880e97caf03f704ef808dc9eba12 | 66570f6d602f122cd595a74b11fee4addeb79f699972cf2778880992d0aa2d85 |

The 2025R table has exactly one `23-4-909` row: Act 373 / SB307,
emergency clause yes, and no repeal, new-section, or renumbering flag. The
same table records Act 745's later correction to other sections of the act,
not to `23-4-909`. The current Arkleg contract exposes only 2026F and 2026S1
after 2025R. The 2026F title-23 table has one unrelated row,
`23-86-119(a)(1)` / Act 147 / SB7. The 2026S1 table returns the exact terminal
`No amended code for this section.` This completes the current-as-of
2026-08-29 temporal chain.

The resolver emits `selected_current_source_body`. It intentionally emits no
`selected_node_id` or `selected_link_href`; neither same-heading Lexis URN is
treated as identified. Compatibility counts include this disposition in the
selected total, while `temporal_preflight_selected_current_source_body=1`
records its distinct authority class.

## Act 926 remains unresolved

Act 926 section 12 controls the two remaining motor-vehicle variants. Upon
implementation of the systems under § 27-14-906(f), the Office of Motor
Vehicle must certify that fact in writing to the DFA Secretary; the Secretary
must file the certification with the BLR Director and the Arkansas Code
Revision Commission. Sections 9 and 10 become effective on the certification
date and do not become effective unless the systems are implemented.

The newly retained official chain is narrower than that trigger:

| Official input | Body SHA-256 | Parser-input receipt SHA-256 | Exact limit |
|---|---|---|---|
| Act 926 | 613ef75651a4e3c5adbb66da1859ad105e6eac1336604a443251a61aa2561353 | a1270aa2b2da3e4d26959f48b3d19c37a8c44c48b2f3274673d5729c0a01e55e | Defines the separate section 12 certification trigger. |
| October 1, 2025 DFA memo | d0403419eaf05e826a3c8d189f3706a4ab7775105f1671efa21be1c4078488ea | 98c6b5b4247d887d97ca02a2babbbd61eefe49b08be38b4af78dc1c561e01260 | Says the odometer-rule amendment was circulating internally and had not been sent to the Governor's Office. |
| March 26, 2026 rule packet | e3cad66134c1c3863bc86c93516574b1e30ecf7f428ed3ad2f57618f16ce1bc2 | 46bf9eb50f05d86cc2b13bf095c224912a1165b0ebc57003b651e2c815fa7454 | Stamped `Proposed Rulemaking`; rule pages are marked `DRAFT`. |
| June 15, 2026 summary | 70364fc12634f1a5ab0d03e0c653e3a9e27c46a365e67e25bb70d0c00f17dff7 | fcb8d22fa7e02a253a65bf3346ee0af89416a49a01c043270573e0f59f0dec9c | Says the proposed effective date is pending legislative review and approval. |
| August 1, 2026 DFA report | 34953866ba559c7e76a09c9ee186c03a3cd15f22af1b7220288841f20637cc73 | 87abc4b60c3899b134f5de9db702b66070c83ef09fff5cf04e0d54140f58bac0 | Omits Act 926 from seven acts still awaiting rules; it makes no systems-implementation or certification statement. |

The exact BLR directory listings that source-derive those attachment URLs are
retained under receipts
`e1df0caa2e7b333e607d2f733f57903e1e3c259360eda4b484cc3639f808e742`,
`444b491c6c879191168f4abb4520d6f17c112ea6ff6d8ff19cf962fbdcb30f4d`,
and `0d043c3736679946d078688bf0a833794404f4367f8cd5197d2b3b499499c7e6`.

Rule promulgation is not the statutory section 12 occurrence. The October and
March records are dated nonimplementation evidence for a rulemaking track,
not a source-authorized finding that the systems certification had not
occurred at every later time. The June status and August omission likewise do
not prove the certification. Neither occurrence nor nonoccurrence is encoded,
so `27-14-802` and `27-14-803` remain unresolved.

## Reproduction and stopping point

The authorizing root is an append-only retained union of the prior 67-input
Arkansas proof and the three exact later-session inputs. Its migration used 70
hardlinks, zero copies, and zero network requests. A 70-request replay under
`retained_replay_only=True` reproduces the preflight algebra:

```text
126 selected + 1 exact Act 373 source body = 127 selected
5 unresolved - 1 exact Act 373 source body = 4 unresolved
127 selected + 1 no-current + 4 unresolved = 132 duplicate groups
```

The focused deterministic check is:

```bash
ARKANSAS_ACT373_TEST_EVIDENCE_ROOT=/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260829-ar-act373-proof-Zyxt13 \
pytest -q tests/unit/legal_scrapers/test_arkansas_act373_enacted_body.py
```

Expected result: 12 tests pass, including adversarial byte, pagination,
instruction-coordinate, strike/underline-coordinate, effective-date,
later-session, and resulting-text drift rejection. No corpus-scale body run,
assembler input-map write, Hub mutation, or remote publication was attempted.
Another Act 926 retry is justified only by a newly filed official section 12
certification or an explicit source-policy-authorized nonoccurrence record.
