# Exact-51 residual replay playbook (v1)

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Branch: `feature/legal-corpora-reindex`  
Task: `LCR-106`  
Goal: `LCR-G148`  
Track: `exact51-residual-replay`  
Status: acquisition playbook for remaining jurisdictions; **not a publication authorization**

This document is the operator playbook behind supervisor goals `LCR-G148`–`LCR-G153`
and tasks `LCR-086`–`LCR-106`. It extracts the six closed-state steps that already
sealed current-bundle pairs and applies them to the 17 remaining jurisdictions
that still lack an authorizing current-bundle pair. Residual work reuses the
closed-bundle seed, grouped-archive residual, and host retained-replay contracts
defined here. Publication remains unauthorized.

Assembler-selected current-bundle pairs stay untouched. This campaign performs
no Hub mutation, writes no production input map, and never Docker-copies
`~/.ipfs_datasets`.

## Six closed-state steps

Every sealed current-bundle pair used the same six closed-state steps. Remaining
states must reuse this pipeline. Do not invent a second acquisition, replay, or
publication path.

1. **Source-derived frontier.** Membership comes from retained official
   catalog/root bytes, not static lists, repaired catalogs, sample caps, or
   filename coverage. Every reachable hierarchy and leaf member is enumerated
   or given a typed disposition.
2. **Fresh evidence generation.** Seed a new root with hardlinks from already
   authorizing parser inputs. Never overwrite a prior ledger, promote a failed
   canary, or resume a fenced staging root as current.
3. **Direct-only reuse when possible.** Seed
   `--allowed-source-transport direct`. Historical Wayback bodies are
   diagnostics unless an explicit current-equivalence proof exists for that
   exact URL and byte identity.
4. **One residual wave with grouped archive rules.** Submit only the
   source-ordered difference as same-domain plural fetches. One Common Crawl
   inventory per domain per logical wave. Grouped/coalesced WARC reuse. Plural
   Wayback prefix inventory. Residual-only retries **without** archive
   reinventory. No per-page archive loop. No archive.is.
5. **Host retained replay without Docker copies.** Run
   `--retained-replay-only` on the host against the existing local evidence
   root. The process-wide network guard authorizes zero-network. Do **not**
   Docker-copy `~/.ipfs_datasets` (about 80 GiB of state-law ledgers plus the
   page cache). Seeds hardlink objects; they never duplicate bytes.
6. **Normalize and seal under the no-publish gate.** Produce canonical JSON-LD,
   parquet, normalized receipt, and run seal with
   `public_law_no_state_copyright`. Start/end producer identities must match.
   No Hub mutation, no `--publish-to-hf`, and no assembler input-map write.

Rights: enacted public-law text is not subject to state copyright. Editorial
annotations, database arrangement, and site chrome stay excluded.

A jurisdiction is closed only when all six steps succeed for the same source
observation. A typed residual report that names the exact next URL or proof set
is an allowed stopping point for a child task; a static list, sample cap,
per-page archive loop, Docker evidence copy, or Hub publish is not.

## Seventeen remaining jurisdictions

The exact remaining open set is the 17 jurisdictions that still lack an
authorizing current-bundle pair after the guarded assembler union that selected
34 digest-bound pairs. That remaining set is:

`AR GA KY LA MI MN MO MS MT NH NY RI TN VT WA WI WV`

Named in full:

1. Arkansas (`AR`)
2. Georgia (`GA`)
3. Kentucky (`KY`)
4. Louisiana (`LA`)
5. Michigan (`MI`)
6. Minnesota (`MN`)
7. Missouri (`MO`)
8. Mississippi (`MS`)
9. Montana (`MT`)
10. New Hampshire (`NH`)
11. New York (`NY`)
12. Rhode Island (`RI`)
13. Tennessee (`TN`)
14. Vermont (`VT`)
15. Washington (`WA`)
16. Wisconsin (`WI`)
17. West Virginia (`WV`)

Closed current-bundle pairs stay out of this campaign. They include
`AK AL AZ CA CO CT DE FL HI IA ID IL IN KS MA MD ME NC ND NE NJ NM NV OH OK OR PA SC SD TX UT VA WY DC`.
Pennsylvania host retained replay is already sealed and is the canary for waves
A–D. Do not reuse fenced PA v2–v6 roots. Do not copy PA evidence into a
container.

## Shared substrate remaining states must reuse

| Mechanism | Module / command | Closed-state lesson |
|---|---|---|
| Direct-only seed | `scripts/ops/legal_data/seed_state_laws_retained_evidence.py` | PA v7 seeded 75 direct inputs, 150 hardlinks, projection `425927…fd07`, zero copies |
| Host retained replay | `retained_replay_isolated_worker.py` host runner + `retained_replay_network_guard.py` | Same `HOME`, `~/.ipfs_datasets/state_laws`, and `legal_page_cache`; PA v7 sealed 14,620 rows, 75/75 retained replay |
| Network deny | `retained_replay_network_guard.py` | Process-wide audit hook, liveness proof, trusted absolute `pdftotext` |
| Grouped archive fallback | `web_archiving` Common Crawl prefix/WARC batching + Wayback CDX/prefix inventory | One inventory per domain/wave; coalesced WARC ranges; residual-only retry |
| Normalization | `refresh_state_laws_corpus.py --strict-acquisition-evidence` | Identity projection must exclude mutable deny-lease state |
| Publication | none in this campaign | Indexing (`gte-small`, BM25, BM25 graph, centroids, sparse meta) stays disabled until exact-51 assembler succeeds |

Shared substrate tasks (`LCR-086`, `LCR-087`, `LCR-088`) own the seed, host
worker, and archive-batching modules. Residual-wave tasks must not rewrite those
files. Adapters may be edited only for the assigned jurisdiction.

## Residual waves and first actions

| Wave | Goal | Bundle | Jurisdictions | Why this grouping | First action |
|---|---|---|---|---|---|
| Shared substrate | LCR-G149 | `exact51-residual-substrate` | all remaining | Unblocks every residual | Direct-only seed must skip unverifiable disallowed transports (MT v4 Wayback mismatch); host-local replay using existing caches; grouped archive contract |
| Wave A | LCR-G150 | `exact51-residual-wave-a` | MT, KY | Bounded, GO or exact residual | Seed MT direct-only 40,132; acquire 5 missing catalogs + 6,652 leaves. KY: 11,641 unique leaf residual |
| Wave B | LCR-G151 | `exact51-residual-wave-b` | MN, MO, WA | Large leaf residuals, retained catalogs exist | Seed verified direct projection; one global leaf wave |
| Wave C | LCR-G152 | `exact51-residual-wave-c` | LA, RI, NH, VT, WV | Catalog-then-leaf or fresh current root | LA 21,531 residual; RI 29 nested catalogs first; NH/VT/WV start fresh current roots |
| Wave D | LCR-G153 | `exact51-residual-wave-d` | AR, GA, MI, MS, NY, TN, WI | Proof, delegated Lexis, or no authorizing ledger | Exact URL/proof residuals only; do not hunt unbounded |

Each remaining jurisdiction either seals a current-bundle pair after host
zero-network replay or records the exact remaining URL or proof residual. No
static list, sample cap, per-page archive loop, Docker evidence copy, or Hub
publish is admitted.

### Per-jurisdiction residual contract

| Code | Task | Exact residual or floor | Seed / reuse rule | Must not |
|---|---|---|---|---|
| MT | LCR-089 | Direct-only projection `6b8d0baca081…` (40,132 inputs); five missing catalogs + 6,652 active leaves | Seed verified direct projection; derive descendants of the five catalogs | Drift Title 0 constitution identity; resume fenced `staging-mt-v11`; treat 2016 Wayback bodies as current without an equivalence proof |
| KY | LCR-090 | 11,641 unique leaves, ordered URL SHA `c96072a16cc6…` | Preserve duplicate exact-request groups; never double-count | Replay mixed historical request identities as current |
| MN | LCR-091 | 16,798 current-edition detail residuals, ordered SHA `105c435137f5…` | Seed verified direct projection; reject historical archive editions | Stamp 2018–2024 Wayback bodies current |
| MO | LCR-092 | 26,587 unique ordered `OneSection` URLs, SHA `49187bc62944…` | Seed only strict v13 | Seed older v4 wholesale; infer the § 70.655 fallback locator |
| WA | LCR-093 | 50,500 source-ordered section URLs, digest `e41a7baf281a…` | Submit exactly the 50,500-URL difference | Guess later URLs; merge residuals across states |
| LA | LCR-094 | 21,531 unique leaves after 24,832 retained | Use the ASP.NET retained parser | Invent later `Law.aspx` targets |
| RI | LCR-095 | 29 nested catalogs first (URL SHA `aeb95ffc2041…`), then the leaf union | Fetch nested catalogs before the leaf union | Per-slice archive inventory; resume zero-row `staging-ri-v1`–v3 as current |
| NH | LCR-096 | Fresh current root at `https://gc.nh.gov/rsa/html/NHTOC.htm` | Do not resume v4 2025 Wayback roots as exact-current | Derive `legal_as_of` from wall-clock on 2025 bytes |
| VT | LCR-097 | Fresh root plus 46 titles (floor 47 requests) | Start from absent staging roots | Import the receiptless May generic cache as authorizing evidence |
| WV | LCR-098 | Fresh root plus 139 chapters (floor 140 requests) | Start from absent staging roots | Import catalog descriptions, singleton artifacts, or source-recovery experiments |
| AR | LCR-099 | Exact proof/URN residual: Act 283 inputs plus four `19-42-201`/`23-4-909` URNs; fail-closed without Act 283 proof bytes | Replay the atomic proof bundle; one same-domain URN wave | Unbounded locator hunt; encode diagnostic notes as decisions |
| GA | LCR-100 | Catalog then 29,165 current body URLs | Retain root/title-patch bytes first | Import legislative-summary PDFs or the two-row artifact |
| MI | LCR-101 | 227 chapter XML documents plus the retained v20 root | Do not repeat CDX for already selected captures; media-aware inventory required | Import repaired diagnostic or capped 160-row corpus |
| MS | LCR-102 | Delegated Lexis catalog then 30,291 current bodies | Retain Legislature delegation, publisher redirect, container root, and 51 TOC bytes | Invent even titles; target the dead 2024 path |
| NY | LCR-103 | Exact 30-URL `www.nysenate.gov` wave plus reviewed proof resolvers | Seed the 96-input v20-plus-AGM union | Convert unresolved decisions into current law |
| TN | LCR-104 | Delegated Lexis frontier of 36,118 parser inputs | Fresh isolated acquisition; PATCH archive substitution forbidden | Use the synthetic v4 receipt or secondary caches |
| WI | LCR-105 | Viewer frontier from one root; lower bound 14,832 URLs; later continuations source-dependent | Close each source-derived continuation wave | Admit the receiptless historical cache |

Supporting audits remain diagnostic until the assigned residual task reseals
them: `minnesota_retained_frontier_audit_v1.md`,
`washington_retained_frontier_audit_v1.md`,
`wisconsin_retained_viewer_audit_v1.md`,
`new_york_residual_inputs_v1.md`,
`mississippi_current_source_resolution_v1.md`,
`tennessee_current_source_resolution_v1.md`,
`new_hampshire_current_source_resolution_v1.md`, and
`arkansas_current_variant_resolution_v1.md`.

## Grouped archive rules

Residual acquisition uses one grouped archive path. These rules are mandatory
for every remaining jurisdiction:

- Replay the exact retained request identity before any network.
- Submit hierarchy and leaf URLs as same-host plural GET/POST batches. Never
  open one HTTP client per URL.
- At most one Common Crawl inventory term per domain per logical wave. Repeating
  a same-domain inventory inside one acquisition attempt fails closed.
- WARC recovery uses grouped byte-range coalescing. Identical WARC files are
  opened once.
- Wayback uses prefix inventory, not per-page CDX. Media-aware inventory is
  required when the frontier is XML/PDF (Michigan lesson).
- Retry waves contain only unresolved exact URLs and **must not** repeat grouped
  archive inventory.
- `archive.is` and legacy per-page archive loops are forbidden.
- Direct-only residual retries proceed without archive reinventory after the
  grouped inventory for that wave has already run.
- `pdftotext` is only the import-time trusted absolute converter
  (`/usr/bin/pdftotext`). Basename `pdftotext` lookups are denied.

Shared tests that remaining adapters must continue to satisfy:

- `tests/unit/web_archiving/test_common_crawl_warc_batching.py`
- `tests/unit/web_archiving/test_wayback_prefix_inventory_batching.py`
- `tests/unit/web_archiving/test_strict_ledger_grouped_archive_policy.py`

`LCR-088` owns those tests. Residual tasks consume the contract; they do not
rewrite it.

## Host retained replay without Docker copies

Remaining-state replay runs on the host against existing local caches. Docker
is not an evidence-transport.

- Evidence and caches live on the host at `~/.ipfs_datasets/state_laws`
  (~80 GiB) and `~/.ipfs_datasets/legal_page_cache`.
- New generations are **hardlinked** from existing objects
  (`copied_file_count=0`). Byte copies are allowed only across filesystems and
  must still be recorded; they are not a Docker bind-mount substitute.
- Host workers inherit `HOME`, `LEGAL_SCRAPER_*` cache dirs, and the same Python
  environment. `build_host_retained_replay_command()` must never contain
  `docker` or `--network`.
- Workers may run in Git worktrees, but they must read and write the shared
  host `~/.ipfs_datasets` trees. They must not bind-mount, `docker cp`, or
  otherwise create a second copy of those files.
- Residual acquisition may use the existing page/fetch caches. Retained-replay-only
  still fails closed on a ledger miss before cache or network.
- Output roots stay under `~/.ipfs_datasets/state_laws/legal-corpora-reindex-*`.
- PA v7 remains the host-replay canary and is not reused as a fenced root.

Host replay command shape after a residual wave closes:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states XX \
  --scrape \
  --retained-replay-only \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-publish \
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-xx-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-xx-vN \
  --parallel-workers 1 \
  --json
```

Require zero network requests, exact first/replay frontier equality, matching
producer identity at run start and seal, and a publication-authorizing
normalized receipt before treating the pair as assembler-eligible. The pair is
still not a publication authorization.

`LCR-087` owns the host worker and network guard. Residual tasks call that
helper; they do not reintroduce Docker evidence copies.

## No-publish gate

This playbook does not authorize indexing, upload, Hub mutation, or public
release.

- No `--publish-to-hf`.
- No incremental Hub publish (`--no-incremental-state-publish` remains set).
- No assembler input-map write until all 51 digest-bound pairs exist.
- No `gte-small`, BM25, BM25-vocabulary graph, centroid, or sparse-meta index
  build for remaining states.
- One-state `partial_success` is expected for a single-jurisdiction refresh and
  is not exact-51 success.
- Publication tasks `LCR-040+` remain blocked on exact-51 live acceptance
  (`LCR-084` / `LCR-G146`). This campaign does not weaken that gate.
- Hugging Face targets `justicedao/ipfs_state_laws` and
  `justicedao/ipfs_federal_register` stay untouched.

A sealed current-bundle pair for one remaining jurisdiction is assembler-eligible
evidence only. It does not flip `exact_51_ready` and does not authorize
publication.

## Normalization and seal rules

- Produce `STATE-XX.jsonld`, parquet, raw and normalized receipts, frontier
  closure projection, and a run seal.
- Producer identity at run start equals identity at seal.
- Host `pdftotext` is the trusted absolute `/usr/bin/pdftotext`.
- Statutory-text rights basis is `public_law_no_state_copyright`.
- Canonical JSON-LD and parquet must have exact ordered serialized parity.
- First and retained-replay frontier digests must match.
- Unresolved, failed-final, sample, fixture, or partial-checkpoint states cannot
  promote success.

## Board DAG for LCR-086 through LCR-106

This playbook documents the existing board DAG. It does not add, remove, or
reorder dependencies. Cross-lane dependencies remain authoritative.

```text
LCR-106  (playbook; no deps; campaign owner of this report)
LCR-086  (direct-only seed; no deps)
LCR-087  (host retained replay; no deps)
LCR-088  (grouped archive contract; no deps)

LCR-089 .. LCR-105  each depend on LCR-086, LCR-087, LCR-088
  Wave A  LCR-G150  LCR-089 MT, LCR-090 KY
  Wave B  LCR-G151  LCR-091 MN, LCR-092 MO, LCR-093 WA
  Wave C  LCR-G152  LCR-094 LA, LCR-095 RI, LCR-096 NH, LCR-097 VT, LCR-098 WV
  Wave D  LCR-G153  LCR-099 AR, LCR-100 GA, LCR-101 MI, LCR-102 MS,
                    LCR-103 NY, LCR-104 TN, LCR-105 WI
```

| Task | Goal | Bundle | Depends on | Owns |
|---|---|---|---|---|
| LCR-086 | LCR-G149 | exact51-residual-substrate | (none) | direct-only retained seed |
| LCR-087 | LCR-G149 | exact51-residual-substrate | (none) | host retained-replay worker and network guard |
| LCR-088 | LCR-G149 | exact51-residual-substrate | (none) | grouped Common Crawl/WARC/Wayback residual tests |
| LCR-089 | LCR-G150 | exact51-residual-wave-a | LCR-086, LCR-087, LCR-088 | Montana residual report and tests |
| LCR-090 | LCR-G150 | exact51-residual-wave-a | LCR-086, LCR-087, LCR-088 | Kentucky residual report and tests |
| LCR-091 | LCR-G151 | exact51-residual-wave-b | LCR-086, LCR-087, LCR-088 | Minnesota residual report and tests |
| LCR-092 | LCR-G151 | exact51-residual-wave-b | LCR-086, LCR-087, LCR-088 | Missouri residual report and tests |
| LCR-093 | LCR-G151 | exact51-residual-wave-b | LCR-086, LCR-087, LCR-088 | Washington residual report and tests |
| LCR-094 | LCR-G152 | exact51-residual-wave-c | LCR-086, LCR-087, LCR-088 | Louisiana residual report and tests |
| LCR-095 | LCR-G152 | exact51-residual-wave-c | LCR-086, LCR-087, LCR-088 | Rhode Island residual report and tests |
| LCR-096 | LCR-G152 | exact51-residual-wave-c | LCR-086, LCR-087, LCR-088 | New Hampshire residual report and tests |
| LCR-097 | LCR-G152 | exact51-residual-wave-c | LCR-086, LCR-087, LCR-088 | Vermont residual report and tests |
| LCR-098 | LCR-G152 | exact51-residual-wave-c | LCR-086, LCR-087, LCR-088 | West Virginia residual report and tests |
| LCR-099 | LCR-G153 | exact51-residual-wave-d | LCR-086, LCR-087, LCR-088 | Arkansas residual report and tests |
| LCR-100 | LCR-G153 | exact51-residual-wave-d | LCR-086, LCR-087, LCR-088 | Georgia residual report and tests |
| LCR-101 | LCR-G153 | exact51-residual-wave-d | LCR-086, LCR-087, LCR-088 | Michigan residual report and tests |
| LCR-102 | LCR-G153 | exact51-residual-wave-d | LCR-086, LCR-087, LCR-088 | Mississippi residual report and tests |
| LCR-103 | LCR-G153 | exact51-residual-wave-d | LCR-086, LCR-087, LCR-088 | New York residual report and tests |
| LCR-104 | LCR-G153 | exact51-residual-wave-d | LCR-086, LCR-087, LCR-088 | Tennessee residual report and tests |
| LCR-105 | LCR-G153 | exact51-residual-wave-d | LCR-086, LCR-087, LCR-088 | Wisconsin residual report and tests |
| LCR-106 | LCR-G148 | exact51-residual-replay | (none) | this playbook only |

Residual tasks do **not** depend on `LCR-106`. The playbook is campaign
documentation that those tasks reuse; encoding it as a hard DAG predecessor
would serialize four lanes behind a documentation task. Shared substrate tasks
have no dependencies, so lanes 0/1/2/3 can start immediately (`LCR-086`,
`LCR-087`, `LCR-106`, `LCR-088`). Residual tasks wait only on seed, host
replay, and grouped archive (`LCR-086`–`LCR-088`). Each residual task owns only
its report and focused tests.

Lane assignment for generated tasks remains
`sha256_full_task_id_first_8_hex_modulo_4`. Conflict policy for every task in
this range: owns only the listed outputs; performs no Hub mutation and does not
edit protected control-plane files.

## Direct-only seed command

When a verified retained ledger exists, seed a fresh absent destination before
the residual wave:

```bash
python scripts/ops/legal_data/seed_state_laws_retained_evidence.py \
  --source-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-xx-vN/XX \
  --destination-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-xx-vNplus/XX \
  --jurisdiction XX \
  --parser-name XxScraper \
  --allowed-source-transport direct
```

Require `network_io_performed=false`, `copied_file_count=0` on the same
filesystem, and a selected-projection SHA that matches the verified direct
count. A mixed ledger with failing Wayback receipts must still seed the exact
direct projection and must never copy unverifiable disallowed transports into
the destination root (`LCR-086`).

## Forbidden actions

- Static lists, sample caps, fixture transports, or repaired catalogs as
  current membership.
- Per-page Wayback, per-page archive.is, or grouped-archive reinventory on
  residual retry.
- Docker copies, bind-mount clones, or second copies of `~/.ipfs_datasets`.
- Overwriting a prior ledger or promoting a failed canary.
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index builds.
- Converting missing proofs, unresolved decisions, or historical archive bodies
  into current law.
- Editing protected control-plane files, including
  `docs/architecture/legal_corpora_reindex.todo.md`,
  `docs/architecture/legal_corpora_reindex.objectives.md`,
  `scripts/validate_legal_corpora_reindex_board.py`, and the scheduler/lane
  matrix.

## Campaign stop condition

`LCR-G148` is complete only when every remaining jurisdiction has either:

1. a sealed current-bundle pair matching these six closed-state steps, or
2. a typed residual report naming the exact next URL or proof set.

The unexplained-gap set among
`AR GA KY LA MI MN MO MS MT NH NY RI TN VT WA WI WV` must be empty. The
no-publish gate stays closed until `LCR-084` / `LCR-G146` accept all 51
digest-bound pairs.
