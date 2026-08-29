# Missouri residual closure v1

Date: 2026-08-27  
Board: `legal-corpora-reindex-v1`  
Task: `LCR-092`  
Goal: `LCR-G151`  
Track: `exact51-residual-wave-b`  
Status: **typed residual recorded**; **not** a sealed current-bundle pair; **not** a publication authorization

This report closes LCR-092 by recording the exact remaining Missouri
`OneSection` residual after strict v13. Host zero-network replay has not
sealed a current-bundle pair. The six closed-state steps remain the only
admitted path. Hub mutation, a static residual list, a per-page archive
loop, wholesale v4 seeding, and an inferred § 70.655 locator are not
admitted.

## Paced acquisition postmortem (2026-08-29)

The paced direct acquisition completed its exact transport frontier but failed
closed before normalization. The preserved generations are:

- evidence:
  `/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260828-mo-paced-evidence-14YnHy`;
- failed output:
  `/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260828-mo-paced-output-SUThd0`;
- direct-only seed source:
  `/home/barberb/.ipfs_datasets/state_laws/legal-corpora-reindex-20260828-mo-evidence-GjIIlI`;
- seed migration receipt:
  `fa72ed18136c4f3b771aa97cccdb312e219e91548bfcd43e7333e5bb0a4e9932`;
- 4,983-input seed projection:
  `d745cf3f1d27f37fcc82f00b3a3323463f4efc64070da66c976ecd286a5635b9`.

That seed used hardlinks, copied zero bodies, and performed zero network I/O.
The live runtime was
`MissouriScraper@sha256:ecd6eb8b362309b313dbc16b3035f392ba7930541dbb0323ac60ce35fdc2a801`.
The runner identity was
`refresh_state_laws_corpus@sha256:91ba1bb60d363033bf28784d3f49e9f27d9cd381f42324f2be323029e2571260`.
Both identities remained equal from start to finish.

### Exact acquisition algebra

The retained catalogs still derive 30,170 operative identities. The 4,983-input
seed contains 3,584 current `PageSelect` inputs and 926 source-reachable
`OneSection` fallbacks. Therefore the live difference is exactly 25,660
source-ordered `OneSection` URLs:

```text
30,170 operative identities
- 3,584 retained current PageSelect inputs
-   926 retained current OneSection inputs
= 25,660 live OneSection residuals
```

The compact-JSON ordered residual SHA-256 is
`8af665b9df4130d3f1554bb347140e5960ef5ea783b5263484423429249953e2`.
The final evidence ledger has exactly 30,643 unique direct receipts and 30,643
fixity-valid unique objects:

```text
30,643 = 1 Home + 468 chapters + 3,584 PageSelect + 26,590 OneSection
```

The primary residual wave left 97 transport misses. One direct-only residual
retry recovered all 97; every recovered body now has the requested statutory
identity. Their source-ordered URL SHA-256 is
`b635af38434a8776321efcb23ae0c42d23f8df5e505e3300e93a6d727aef7f0c`.
No archive body was retained.

### Complete retained-body classification

A zero-network scan of all 25,660 live residual bodies produced this exact
algebra:

```text
25,660 = 25,409 requested-body matches
       +    140 requested-page shells with blank or wrong statutory bodies
       +    111 source-bound HTTP-200 Server-busy shells
```

All 25,660 receipt/body pairs pass SHA-256 fixity. The 140 requested-page
shells comprise 94 blank bodies and 46 wrong-section bodies. Their ordered
`OneSection` URL SHA-256 is
`afd504524183754280d87dcdc5bce08af9c9f730b6da64d173cb73a2baa21dfe`;
the corresponding exact catalog `PageSelect` locator SHA-256 is
`d51b571f3037eb9c8bb40f64a469b60473a7ef2b5c19e8f20d2393df949c9fd6`.

All 111 no-identity responses are one semantic source shape: a 1,292-byte
ASP.NET form posting to `./Wait.aspx`, linking the Revisor home/logo, and
publishing the visible text `Server busy! Please use browser back button and
retry your request.` The normalized visible-text SHA-256 is
`888de13904125c5c46f87a2ab415d4b5364f6bc4e981c68f162be56966054fe8`.
Their ordered `OneSection` URL SHA-256 is
`888751230e20482b9e83914123b498ef9d522267d78ab0db88b182d9ecdf2fda`;
their corresponding exact catalog `PageSelect` locator SHA-256 is
`40aed5e853a1ac5f716a430974e5d4a3c4a7ed49a077fae7b699ee93f561f542`.
Neither preserved Missouri evidence generation retains any of those 111 exact
`PageSelect` locators.

The first hard failure is § 86.910. Its rejected `OneSection` receipt is
`7577fb7a6d184442c174f6eff3e1537b2b21fea81ce184b3df09915b26880e6e`,
and its Server-busy body is
`be26f588406e998cf30e9e190857ebedad6e9959c75f6651e76a6c9d17225991`.
The current catalog independently binds that identity to exact locator
`PageSelect.aspx?section=86.910&bid=4279&hl=`.

### Bounded retained-valid reseed and recovery

No reseed or acquisition was launched by this audit. The exact next seed
projection is nevertheless closed over 30,392 identity-aligned direct inputs:

```text
30,392 = 30,643 retained direct inputs
       -    111 Server-busy OneSection shells
       -    140 page-only/mismatched OneSection shells
```

Those 30,392 inputs have 30,392 unique content objects. In seeder order, their
selected-projection SHA-256 is
`285b26bbadedfd2d0f41ff8b9e2955f2944f7ef975e69c226625ead9bbf30f36`;
their ordered included-URL SHA-256 is
`d245cd23bd460d0c48cb166c04bb8bb2fe0c6925ee03caf0bbf3a1db58dadd91`.
These are prospective zero-network seed identities, not a migration receipt or
an authorizing closure.

The remaining acquisition is bounded to two source-derived sets:

1. reacquire the exact 111 `OneSection` URLs through the Missouri validator,
   which now rejects the semantic `Wait.aspx` Server-busy shell before
   retention; and
2. acquire the exact 140 current catalog `PageSelect` locators for the
   independently proven requested-page/body-mismatch set.

The isolated patched producer identity for that plan is
`MissouriScraper@sha256:8d0afd323923bd2029d87a74ba9297e3a5c8a3a4bdd463c1a9efce320bc10a69`.

If both sets return requested identities, the resulting parser-input algebra
is again exactly 30,643, but with the rejected inputs replaced:

```text
30,643 = 30,392 retained-valid seed
       +    111 corrected OneSection inputs
       +    140 exact PageSelect recovery inputs
```

Only then may a hard zero-network replay attempt normalization and a run seal.
No corpus-scale acquisition, retained replay, materialization, or publication
is authorized by this postmortem.

### Failed output identity

Run `768e2bdb181646fda670ae1e594d7f61` finished with status
`failed_acquisition_run_finalization`, zero statutes, and one state error. Its
run seal is `not_issued` and nonauthorizing. Preserved output hashes are:

| Artifact | SHA-256 |
|---|---|
| `partial_checkpoints/STATE-MO-partial.json` | `8fedbd63a813ce209be2f63259c0d4d2c03c5abb70cbf6181e167fba1787f787` |
| `state_laws_parquet_cid/state_laws_refresh_manifest.json` | `8ec328dc58213fd17855a7f3f2bd0afac4edc7611e769c71bb9015f4d13c18bc` |
| `state_refresh_progress.json` | `146b456dba9b112617763d91fc7626f5e65de6fc3e969c84bbcd8e02716b6073` |

## Residual identity (exact)

| Field | Value |
|---|---|
| jurisdiction | MO |
| official domain | revisor.mo.gov |
| official entry | `https://revisor.mo.gov/main/Home.aspx` |
| closure_status | residual_recorded |
| current_bundle_sealed | false |
| publication_authorized | false |
| hub_mutation | forbidden |
| seed | strict v13 only |
| v4_wholesale_seed | forbidden |
| static_residual_list | forbidden |
| inferred_section_70_655_locator | forbidden |
| v13_unique_inputs | 4056 |
| v13_home_pages | 1 |
| v13_chapter_catalogs | 468 |
| v13_pageselect_pages | 3584 |
| v13_onesection_fallbacks | 3 |
| source_chapters | 468 |
| effective_dated_variants | 31074 |
| source_identities | 30441 |
| current_operative_identities | 30170 |
| future_effective_variants_excluded | 853 |
| superseded_variants_excluded | 51 |
| future_only_identities_excluded | 271 |
| empty_chapters | 8 |
| transferred_chapters | 2 |
| residual_count | 26587 |
| residual_kind | unique ordered OneSection URLs |
| residual_first_section | 70.655 |
| residual_last_section | 701.550 |
| residual_first_url | `https://revisor.mo.gov/main/OneSection.aspx?section=70.655` |
| residual_last_url | `https://revisor.mo.gov/main/OneSection.aspx?section=701.550` |
| residual_ordered_sha256_prefix | `49187bc62944` |
| residual_sha_method | `sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))` |
| residual_wave_name | `source-ordered-one-section-residuals` |
| one_section_plural_wave_count | 1 |
| per_page_archive_loop | false |
| grouped_warc_recovery | true |
| wayback_prefix_inventory | true |
| residual_only_retries | true |
| archive_is | forbidden |
| host_retained_replay_network_requests | 0 |
| rights_basis | `public_law_no_state_copyright` |
| source_bundle_prefix | `0c4155f60cd4` |

The residual SHA-256 prefix `49187bc62944` is the already published identity
of the source-ordered unique `OneSection` URL array. The adapter records the
complete 64-hex digest as `residual_one_section_sha256` after a v13 seed
derives that exact array. This report does not emit the 26,587 URLs: a static
dump would be a forbidden residual list and would exceed the compact-recipe
admission bound.

## Outcome

Missouri is **not** assembler-eligible. Strict lifecycle membership is known,
v13 retained inputs are known, and the remaining leaf wave is an exact
26,587-URL `OneSection` residual. No host retained-replay seal, normalized
receipt, JSON-LD/Parquet pair, or current-bundle pair exists for this
observation.

The allowed stopping point for this child task is the typed residual below.
The remaining operator action is one global residual wave against a fresh
v13-seeded evidence root, then host `--retained-replay-only` with zero
network before materialization.

## v13 seed algebra

Strict lifecycle derives 468 chapters from the official Home.aspx catalog,
not from `OFFICIAL_NUMERIC_CHAPTERS` or any other static chapter list.
Those catalogs expose 31,074 effective-dated variants over 30,441 identities.
Current selection keeps 30,170 operative identities and excludes 853 future
plus 51 superseded variants, including 271 future-only identities. Eight
empty chapters and two transferred chapters are typed terminals and are not
leaf residuals.

The v13 ledger is exactly 4,056 unique parser inputs:

```text
4,056 = 1 home + 468 chapter catalogs + 3,584 PageSelect pages
      + 3 already retained OneSection fallbacks
```

Those 3,584 `PageSelect` pages are versioned catalog locators. They are
inspected through the retained ledger only. Missing or unparseable
`PageSelect` identities are **not** submitted as residual `PageSelect`
fetches. The stable `OneSection` locator derived from the selected section
number is the one exact residual source for that identity.

Retained-vs-residual leaf algebra for the 30,170 current operative
identities is:

```text
3,580 successful retained PageSelect parses
  + 3 retained OneSection fallbacks
  + 26,587 OneSection residuals
  = 30,170 current operative identities
```

Four of the 3,584 retained `PageSelect` pages do not themselves admit a
current operative body: three already have retained `OneSection` fallbacks,
and retained § 70.655 is the exceptional mismatch that opens the residual
wave.

Every current identity already present in older v4 material is covered by
v13, and none of those v4 identities overlaps the 26,587-URL residual. v4
also contains noncurrent, invalid, and ambiguous duplicate endpoints.
Do not seed v4 wholesale. Seed only strict v13 into a fresh immutable
evidence root.

## Exact § 70.655 residual locator

The first residual member is not an inferred `PageSelect` continuation, a
footer `OneSection` scrape, or a guessed bid. Retained
`PageSelect.aspx?section=70.655&bid=57378&hl=` proves the exceptional
mismatch: its selected page identity is 70.655 and its statutory body is
70.631. The adapter therefore emits the exact `OneSection` fallback built
from the selected section number:

```text
https://revisor.mo.gov/main/OneSection.aspx?section=70.655
```

That URL is `missouri_chapter.section_url("70.655")`. The last residual
member is the same construction for the final selected identity:

```text
https://revisor.mo.gov/main/OneSection.aspx?section=701.550
```

A later residual SHA may be recomputed only from the source-ordered unique
URL array after a v13 seed. It must still start with `49187bc62944` or
record a newly hashed equal count from a drifted official catalog. Guessing
the remaining hex, inferring § 70.655 from 70.631, or substituting a static
URL list fails closed.

## One global residual wave

The adapter turns the retained v13 frontier into a single
source-ordered residual wave rather than 26,586 futile `PageSelect`
attempts followed by another archive pass.

Required acquisition shape:

1. Seed verified direct v13 inputs into a fresh absent evidence root
   (`--allowed-source-transport direct`; hardlinks, `copied_file_count=0`).
2. Replay retained Home.aspx and 468 chapter catalogs from that ledger.
3. Probe retained `PageSelect` inputs without converting misses into
   requests.
4. Submit only the source-ordered unique `OneSection` difference as one
   plural batch named `source-ordered-one-section-residuals`.
5. Use one `revisor.mo.gov` Common Crawl inventory, grouped/coalesced WARC
   reuse, and Wayback prefix inventory. Residual-only retries must not
   repeat grouped archive inventory.
6. Host-replay every parser input with `--retained-replay-only` and zero
   network. Require 30,170 operative identities, first/replay frontier
   equality, and `public_law_no_state_copyright` before treating the pair as
   assembler-eligible evidence.

Forbidden:

- static residual URL lists or sample caps;
- per-page archive loops and `archive.is`;
- Hub mutation, `--publish-to-hf`, assembler input-map writes, or index
  builds;
- Docker-copying `~/.ipfs_datasets`;
- resuming a fenced staging root as current;
- stamping historical archive bodies current without an explicit
  current-equivalence proof for that exact URL and byte identity.

## Shared substrate this residual reuses

LCR-086, LCR-087, and LCR-088 own the seed, host worker, and grouped
archive contract. This task does not rewrite those modules.

| Step | Missouri binding |
|---|---|
| Source-derived frontier | Home.aspx chapter order plus chapter-catalog `PageSelect` identities |
| Fresh evidence generation | Seed only strict v13; never overwrite v13 or promote v4 |
| Direct-only reuse | `--allowed-source-transport direct` |
| One residual wave | `source-ordered-one-section-residuals`, 26,587 URLs |
| Host retained replay | `build_host_retained_replay_command()`; no `docker`, no `--network` |
| No-publish gate | `--no-incremental-state-publish`; no Hub mutation |

Host replay command shape after the residual wave closes:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states MO \
  --scrape \
  --retained-replay-only \
  --strict-acquisition-evidence \
  --strict-full-text \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-publish \
  --output-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/staging-mo-vN \
  --acquisition-evidence-root ~/.ipfs_datasets/state_laws/legal-corpora-reindex-*/full-acquisition-evidence-*-mo-vN \
  --parallel-workers 1 \
  --json
```

A sealed pair would still be assembler-eligible evidence only. It would not
flip `exact_51_ready` and would not authorize publication.

## Next residual URL

The exact next URL is the first residual member:

```text
https://revisor.mo.gov/main/OneSection.aspx?section=70.655
```

The exact remaining proof residual is the complete 26,587-URL ordered
`OneSection` wave from that locator through
`https://revisor.mo.gov/main/OneSection.aspx?section=701.550` at SHA prefix
`49187bc62944`.
