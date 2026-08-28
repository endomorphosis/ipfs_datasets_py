# Louisiana residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-094`  
Goal: `LCR-G152`  
Track: `exact51-residual-wave-c`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-094 by recording the exact remaining Louisiana
`Law.aspx` leaf residual after the ASP.NET retained parser. Host
zero-network replay has not sealed a current-bundle pair. The six
closed-state steps remain the only admitted path. Hub mutation, a static
residual list, a per-page archive loop, and invented later `Law.aspx`
targets are not admitted.

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | LA |
| official domain | legis.la.gov |
| official entry | `https://legis.la.gov/legis/Laws_Toc.aspx?folder=75&level=Parent` |
| official_law_locator | `https://legis.la.gov/legis/Law.aspx?d=` |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| parser | ASP.NET retained parser |
| same_target_parser_for_live_and_replay | true |
| invent_later_law_aspx_targets | forbidden |
| static_residual_list | forbidden |
| toc_inputs | 55 |
| toc_root_gets | 1 |
| toc_title_postbacks | 54 |
| raw_law_anchors | 92726 |
| unique_leaves | 46363 |
| retained_leaves | 24832 |
| retained_operative | 20681 |
| retained_typed_terminals | 4151 |
| residual_count | 21531 |
| residual_kind | unique ordered Law.aspx leaves |
| residual_first_url | first source-ordered unique Law.aspx leaf absent from the retained 24,832-leaf ledger after ASP.NET TOC replay |
| residual_wave_name | `source-ordered-law-aspx-residuals` |
| leaf_acquisition_wave_count | 1 |
| per_page_archive_loop | false |
| grouped_warc_recovery | true |
| wayback_prefix_inventory | true |
| residual_only_retries | true |
| archive_is | forbidden |
| host_retained_replay_network_requests | 0 |
| rights_basis | `public_law_no_state_copyright` |
| residual_sha_method | `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))` |
| residual_ordered_sha256_prefix | source_derived_after_aspnet_toc_replay |
| diagnostic_producer | `LouisianaScraper@sha256:51663b23ac274d2194e2da205e4221e8cd54d3babf801c8e06a4ca00130a108a` |

The residual SHA-256 is not a predeclared hex prefix. It is the canonical
JSON digest of the source-ordered unique `Law.aspx` difference after
ASP.NET TOC replay minus the 24,832 retained leaves. Guessing that hex,
emitting a 21,531-URL dump, or inventing a later `Law.aspx?d=` identifier
fails closed: a static dump would be a forbidden residual list and would
exceed the compact-recipe admission bound.

## Outcome

Louisiana is **not** assembler-eligible. Hierarchy membership is known,
retained leaves are known, and the remaining leaf wave is an exact
21,531-URL `Law.aspx` residual. No host retained-replay seal, normalized
receipt, JSON-LD/Parquet pair, or current-bundle pair exists for this
observation.

The allowed stopping point for this child task is the typed residual
below. The remaining operator action is one global residual wave against
a fresh direct-only seed of the 55 TOC inputs plus 24,832 retained
leaves, then host `--retained-replay-only` of all 46,363 unique leaves
with zero network before materialization.

## ASP.NET unique-leaf algebra

Strict lifecycle derives 55 TOC inputs from the official
`Laws_Toc.aspx?folder=75&level=Parent` catalog, not from
`_ARCHIVE_LAW_URLS`, bounded live seeds, or any other static law list:

```text
55 = 1 root GET + 54 title POSTs
```

Those title views render the same `Law.aspx` anchor in two parallel
presentation blocks. Live discovery and retained replay use the same
entity-escaped postback parser (`&#39;` included) and admit each
target's first source-order occurrence only. Fail-closed pagination
rejects noncontiguous, duplicate, or conflicting page indexes.

```text
92,726 raw Law.aspx anchors
  → 46,363 unique first-occurrence leaves
```

Retained evidence covers 24,832 of those unique leaves exactly:

```text
24,832 retained leaves
  = 20,681 operative
  +  4,151 typed terminals
```

Retained-vs-residual leaf algebra is therefore:

```text
24,832 retained unique leaves
  + 21,531 Law.aspx residuals
  = 46,363 unique leaves
```

The residual is that source-ordered difference. It is not a later
`Law.aspx?d=` hunt, a Wayback CDX expansion, or a bounded sample.

## Exact remaining URL

The exact next URL is the first source-ordered unique `Law.aspx` leaf
that is absent from the retained 24,832-leaf ledger after ASP.NET TOC
replay. That locator is built only from a retained (or live) TOC href
that matches `Law.aspx?d=\d+`. It is not inferred from
`_ARCHIVE_LAW_URLS`, from `d=100114`/`d=100115` bounded live seeds, or
from a guessed later document id.

The exact remaining proof residual is the complete 21,531-URL ordered
unique-leaf difference. Recompute that array only from ASP.NET TOC
replay minus retained leaf endpoints. A later residual SHA may be
recorded only after that derivation and must use
`sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))`.

## One global residual wave

The adapter already submits the complete unique `Law.aspx` union as one
archive-aware plural wave (`_fetch_louisiana_law_frontier`). After a
direct-only seed of the 55 TOC inputs plus 24,832 retained leaves, that
wave's unresolved remainder is the exact 21,531-leaf residual. Residual
retries do not repeat grouped archive inventory. Do not invent a second
per-page, per-title, or CDX loop.

Required acquisition shape:

1. Seed verified direct TOC (55) and 24,832 leaf inputs into a fresh
   absent evidence root (`--allowed-source-transport direct`; hardlinks,
   `copied_file_count=0`).
2. Replay the retained ASP.NET TOC with the same target parser used for
   live discovery. Require 1 root GET + 54 POSTs and 46,363 unique
   first-occurrence leaves.
3. Submit the complete source-ordered unique union as one plural batch.
   Retained replay covers 24,832 leaves. The unresolved remainder is
   the 21,531-URL residual named `source-ordered-law-aspx-residuals`.
4. Use one `legis.la.gov` Common Crawl inventory with URL term
   `/legis/Law.aspx`, grouped/coalesced WARC reuse, and Wayback prefix
   inventory. Residual-only retries must not repeat grouped archive
   inventory.
5. Host-replay every parser input with `--retained-replay-only` and zero
   network. Require 46,363 unique leaves (20,681 retained operative plus
   residual operative/terminal algebra), first/replay frontier equality,
   and `public_law_no_state_copyright` before treating the pair as
   assembler-eligible evidence.

Forbidden:

- static residual URL lists, sample caps, or invented later
  `Law.aspx?d=` targets;
- per-page archive loops, per-title CDX, and `archive.is`;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- resuming a fenced staging root as current;
- stamping historical archive bodies current without an explicit
  current-equivalence proof for that exact URL and byte identity;
- sole-admitting `_ARCHIVE_LAW_URLS` or bounded live seeds as the
  residual membership.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | Louisiana binding |
|---|---|
| Source-derived frontier | ASP.NET TOC postbacks plus first-occurrence `Law.aspx` leaves |
| Fresh evidence generation | Seed 55 TOC inputs + 24,832 retained leaves; never overwrite |
| Direct-only reuse | `--allowed-source-transport direct` |
| One residual wave | unresolved remainder of `_fetch_louisiana_law_frontier`, 21,531 URLs |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |

Host replay command shape after the residual wave closes:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states LA \
  --scrape \
  --retained-replay-only \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-publish \
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-la-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-la-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

## Next residual URL

The exact next URL is the first source-ordered unique `Law.aspx` leaf
absent from the retained 24,832-leaf ledger after ASP.NET TOC replay.
Inventing a later `Law.aspx?d=` identifier that is not in that
difference fails closed.

The exact remaining proof residual is the complete 21,531-URL ordered
unique-leaf wave at SHA prefix `source_derived_after_aspnet_toc_replay`.
