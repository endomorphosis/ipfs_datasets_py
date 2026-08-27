# Tennessee current-source resolution v1

Observation date: 2026-08-26 UTC

## Outcome

Tennessee's authoritative current statutory source and its exact metadata
frontier are resolved.  The Tennessee General Assembly's Web Publications page
delegates its `Tennessee Code` link to LexisNexis, whose redirect reaches the
free-public-access `Tennessee Code Unannotated` container.  A bounded,
metadata-only observation closed exactly 71 statutory title roots and 36,046
unique document leaves.  It opened no document body.

Tennessee is **not** ready to materialize, index, or publish.  None of the live
authority, catalog, or body bytes from this observation were retained in the
strict acquisition ledger.  The exact strict-reusable current-source parser
input count is therefore zero.  The existing synthetic 71-row v4 receipt is
preserved as a diagnostic but is explicitly nonauthorizing.

## Authority and public-law scope

The current delegation chain is:

```text
https://wapp.capitol.tn.gov/apps/WebPublications/
https://www.lexisnexis.com/hottopics/tncode
https://advance.lexis.com/container?config=014CJAA5ZGVhZjA3NS02MmMzLTRlZWQtOGJjNC00YzQ1MmZlNzc2YWYKAFBvZENhdGFsb2e9zYpNUjTRaIWVfyrur9ud
```

The former adapter entry
`https://www.tn.gov/tga/statutes.html` returned HTTP 404 on the observation
date.  Invented per-title descendants under that path are not current source
locators.

The admissible corpus scope is enacted Tennessee statutory text, statutory
citations and captions, and source-attached legislative history needed to
interpret the provision.  Publisher annotations, case notes, search results,
navigation, commercial access state, and visual presentation are outside the
corpus because they are editorial or secondary material.  There is no state
copyright in public laws; these exclusions do not imply otherwise.

The separately handled Tennessee Constitution, administrative rules, court
rules, bills, and session-law materials are not members of this Code-body
frontier.  The root's `Volume 13 Tables` node is publisher/table material rather
than one of the 71 statutory titles and is excluded from title membership.

## Exact delegated source identity

| Field | Exact value |
|---|---|
| container origin | `https://advance.lexis.com` |
| allowed container | the exact `config` URL above |
| TOC pod/root | `6gf5kkk` |
| TOC endpoint | `/r/tocprovider/6gf5kkk/toc/6gf5kkk` |
| document path family | `/shared/document/statutes-legislation/urn:contentItem:…` |
| statutory title roots | Titles 1 through 71, in source order |
| excluded root | `Volume 13 Tables` |

The source advertises the supported `open-to` levels for each title root.  One
PATCH using the maximum advertised level returned each expandable title's
complete hierarchy.  This is a 69-request catalog expansion, not a node-by-node
request loop.  Titles 19 and 51 are direct document roots labelled
`[Reserved]`; the other 69 titles are expandable roots.

Material corrections to the adapter's prior title labels are:

| Title | Current source label |
|---:|---|
| 14 | `COVID-19` |
| 15 | `Holidays and Days of Special Observance` |
| 19 | `[Reserved]` |
| 33 | `Mental Health and Substance Abuse and Intellectual and Developmental Disabilities` |
| 48 | `Securities, Corporations And Associations` |
| 51 | `[Reserved]` |
| 52 | `Department of Disability and Aging` |
| 64 | `Regional Authorities` |

## Exact metadata-only frontier

The bounded expansion completed once, without retry, and opened no body
document.  The 69 raw TOC responses totalled 40,064,454 bytes in memory.
Those bytes were not written into the acquisition ledger, so the observation
is diagnostic rather than authorizing.

| Measure | Exact result |
|---|---:|
| source roots including nonstatutory tables | 72 |
| statutory title roots | 71 |
| expandable title roots | 69 |
| direct reserved-document title roots | 2 |
| complete deepest TOC responses | 69 |
| descendant nodes below expandable roots | 40,193 |
| descendant containers | 4,149 |
| descendant document leaves | 36,044 |
| all document leaves including direct roots | 36,046 |
| all statutory nodes including title roots | 40,264 |
| unique node paths | 36,046 / 36,046 document leaves |
| unique content-item paths | 36,046 / 36,046 document leaves |
| non-document terminal leaves | 0 |
| conflicting or repeated semantic nodes | 0 |

The structural algebra closes exactly:

```text
40,193 descendants = 4,149 containers + 36,044 document leaves
40,264 all statutory nodes = 69 expandable roots + 4,149 containers
                             + 36,046 document leaves
36,046 document leaves = 36,044 descendant documents + 2 direct reserved roots
```

Source-level counts across the two direct roots plus every descendant are:

```text
L1 2 + L2 1,119 + L3 9,618 + L4 25,299 + L5 4,157 = 40,195
```

The root nodes for the 69 expandable titles sit outside that source-level
subtotal; adding them produces the 40,264 all-node total.

## Diagnostic membership hashes

The hashes below bind canonical semantic serializations from this one completed
observation.  They do not replace raw transport receipts and are not reusable
parser inputs.

| Serialization | Canonical bytes | SHA-256 |
|---|---:|---|
| 71-title root membership | 20,850 | `88135a531583ec0784f72ab7ec436e282f61da93df58e0c86b98f65983620566` |
| all-node frontier membership | 12,847,086 | `ea80e34aff88bc2d289494ff1ab67c2d53193d1b5f086000510b7cafa31d8826` |
| document-leaf membership | 8,571,315 | `8bfc62cda73e7529b30f5848d7cb9128c341d6c0f8910c6ed08dc0beb58d7286` |
| ordered document content-item paths | 3,063,911 | `af6b3962a8eedc12d5f76d98608deee37c8398b30236829b504986c42234599b` |
| 69-response metadata manifest | 23,062 | `29570e7e953a0b80ba32a9245c94b05cbb0076e1c4283eb59e88853b90ccd40a` |

The Title 1 raw response was 56,636 bytes at SHA-256
`128aff6a55787f9a57f31e30035fa7a9bb0dbc77ba90d26db26af20a98117004`.
It too is merely a diagnostic hash because the response was not retained.

## Catalog labels, temporal state, and duplicates

The catalog-label partition is exact at the metadata layer:

```text
36,046 leaves = 1,359 explicitly terminal-labelled leaves
              + 34,687 body-unclassified/current candidates

1,359 explicit terminal labels = 720 repealed + 561 reserved
                               + 53 transferred + 16 expired
                               + 9 obsolete
```

This is not final body algebra.  The audit opened no documents, so operative
text, empty terminal bodies, effective dates, and concurrent source variants
have not been reconciled.  The current exact operative/terminal corpus totals
are therefore not provable yet.

There are 35,359 citation-labelled leaves and 35,159 unique citation labels.
Exactly 182 citation identities repeat; some have more than two content-item
paths.  All 36,046 content-item paths are distinct.  No implementation may
deduplicate these paths by citation before exact body and temporal
reconciliation.

## Existing-byte reuse audit

No local artifact authorizes reuse against this delegated current frontier.

### Synthetic v4 catalog receipt — preserved, nonauthorizing

The following two directories contain byte-identical copies of the old
71-title artifact:

```text
~/.ipfs_datasets/state_laws/legal-corpora-reindex-20260824/catalog-first/TN
~/.ipfs_datasets/state_laws/legal-corpora-reindex-20260824/full-acquisition-evidence-v4/TN/frontiers/official-catalog-observations/first/b80543521a7918f0d3f8fe482bddacdc5d31909e2b5fe70da636b4887c03696e/TN
```

The first directory's exact hashes are:

| File | SHA-256 |
|---|---|
| `request.bin` | `84c606668ca8b44fa39e5617d4c715ada2174c8db5b7a50a8c2b5ad532b25d10` |
| `response.bin` | `89e20a95d9fd8cbacea5a980d8be8a2a5e5fc6506e688d49a48a6a54c068cf90` |
| `body.bin` | `79d2d9e385f0c0a4363e3e33182c3596ff651041920404648cfd659fbbafede6` |
| `rows.jsonl` | `888c043d959c7e195c7aa08d3f0e4537beae13bfd68bc78c811caf88b874b0e0` |
| `frontier.json` | `54c279973c38a40fa366d7c9a1cebe1d9f418685ca21a6b688c51c92a43b938b` |
| `checkpoint.json` | `4e1c50def884d040d595f015a59e4d7b2ac16645f28fcba4671da4ee332267a5` |

`response.bin` begins with a synthetic HTTP status followed by generated JSON,
because the dead `tn.gov` fetch returned no page.  Its rows invent per-title
`tn.gov` locators and label them `repaired_official_leginfo`.  The checkpoint
nevertheless says `fixture=false`, `transport_kind=live_https`, and records an
unsupported `legal_as_of=2026-07-01`; its frontier digest is
`6850ed433c01d8085997eb4e67d3073d973b693cde57e89b34ad22e14e04374a`.
The referenced `receipt.json` is absent.  These contradictions make the entire
artifact nonauthorizing.  It remains on disk unchanged as regression evidence.

The partial strict checkpoint at
`staging-shard-c-tail-v1/partial_checkpoints/STATE-TN-partial.json` contains zero
statutes.  The v4 evidence tree has no Tennessee fetch objects or body ledger.

### Secondary and legacy material

- The shared legal-page cache contains zero exact Tennessee entries.
- The current top-level pair contains only 18 Justia Title 1 rows.  JSON-LD is
  `34e5bba2db771ac6a7110fdf66854bdb35a264fa36a5a9b88f12386c64c8b99b`;
  Parquet is
  `7f46228cdf560a1563ffeba6fc60cfa5876601217e0762e98d73515414fcf423`.
- The May parallel run has 1,719 Tennessee cache metadata entries: 1,116
  `law.justia.com` Playwright entries and 603 `r.jina.ai` direct-reader entries.
  They have no `transport_evidence` and do not bind the delegated content-item
  frontier.  Its 278-row Justia JSON-LD is
  `adeb7cb1650aa7b9572d6bfb7d836adb7156f9e8b8b9368b9310a56497b3763a`;
  its 362-row mixed Parquet is
  `159b8ef4227f1fa9fb7830e89333a2e7dd5e4469efa531738169d79dc1571dea`.
- The cached 84-row Hugging Face blob is 48,218,573 bytes at
  `b772cc0673a3269acd2077cfd83151969c5fceb65c735e1dda41ea7a1158d517`.
  Its capitol, Web Publications, Secretary of State, and blank rows are
  navigation/search provenance rather than statute bodies.
- A stale completion-registry claim of 278 statutes describes the May
  secondary output, not a strict current-source pair.

These bytes may remain diagnostic or parser-test oracles.  None may suppress a
request in the exact delegated frontier.

## Exact residual and required grouped archival recovery

Strict-reusable current-source parser inputs: **0**.

Exact source-derived body residual: **36,046** distinct content-item paths.
Although 1,359 leaves have terminal-looking catalog labels, all 36,046 should
remain body targets until the source contract has retained and proved how a
catalog terminal can close without a body.  This avoids silently discarding
reserved, transferred, expired, obsolete, or repeated variants.

The authority/catalog prelude is counted separately from bodies.  A future
authorizing run must retain at least:

- one exact General Assembly response proving the Lexis delegation;
- the publisher-entry redirect receipt;
- the exact container root response; and
- all 69 deepest TOC responses.

That is 72 required authority/catalog inputs under this minimal chain, followed
by 36,046 body inputs: **36,118 exact residual parser inputs in total**.  If an
implementation retains an additional
corroborating state page or intermediate redirect, that input must be counted
explicitly rather than hidden in the body algebra.

Every same-domain hierarchy or body wave must submit its ordered URL set to
`_fetch_page_contents_with_archival_fallback_retrying_residuals`.  Concurrency
or memory chunks may be bounded, but the shared archive inventory scope may not
devolve into a per-page loop.  Required invariants are:

```text
common_crawl_inventory_queries <= 1 per source domain/wave
group_warc_ranges_by_warc_filename = true
coalesce_compatible_warc_ranges = true
wayback_prefix_inventory = true
retry_residual_urls_only = true
per_page_archive_inventory_loop = false
```

This permits many requested pages on `advance.lexis.com`, including pages in
the same WARC object, to share one inventory and grouped/coalesced WARC range
retrieval.  Successful direct or archive inputs must be retained first; later
retries receive only aligned residual URLs.  An interrupted run must reuse the
same evidence root so immutable retained inputs replay and only genuine ledger
misses touch the network.

Closure is a separate ordered ledger-only replay across every authority,
catalog, and body parser input.  It must bypass live/archive acquisition and
prove `network_requested_pages=0`; calling a per-page archive fallback during
closure is forbidden.

## Code boundary

The Tennessee adapter binds the current General Assembly delegation,
publisher entry, exact container, TOC endpoint, corrected title labels, and a
Tennessee-specific strict Lexis parser.  It deliberately does not treat every
Lexis host URL as official: only the exact delegated container, its exact
request-body-bound TOC responses, and source-derived statute content-item paths
enter the strict frontier.

The offline implementation now provides:

- exact rendered-root validation for the 71 source-ordered statutory roots,
  the two direct reserved-document roots, the 69 expandable roots and the
  excluded `Volume 13 Tables` root;
- one deterministic `open-to` PATCH identity per expandable title, bound to
  the maximum source-advertised level, canonical request bytes, method,
  headers, request-body length and request-body SHA-256;
- strict nested-subtree validation for ancestry, title boundaries, expandable
  closure, document-path uniqueness and untyped non-document leaves;
- a same-domain plural GET seam which delegates Common Crawl inventory,
  grouped/coalesced WARC reuse, plural Wayback prefix discovery and
  residual-only retries to the shared implementation;
- exact document-body classification that removes publisher annotations but
  retains source-attached legislative history, binds every row or typed
  terminal to its content-item, parser receipt, transport receipt and request
  identity, and never truncates statutory text; and
- a five-wave, ordered, ledger-only reconstruction and closure route:
  `1 state + 1 publisher + 1 root + 69 TOCs + all bodies`, with zero network
  requests and no per-page archive loop.

The TOC PATCH wave is ledger-only during reconstruction and closure.  A GET
archive cannot prove a PATCH request body, so the adapter explicitly forbids
archive substitution for those 69 identities.  Future authority and body GET
acquisition must use the plural shared path; bounded legacy probes retain their
bounded behavior.

Strict full-corpus mode remains fail-closed unless an attached ledger is in
retained-replay-only mode and contains the complete exact request set.  The
parser also refuses to collapse repeated citations: after all bodies are
available, any still-operative repeated citation remains a typed temporal
residual until source-bound effective-date or contingency evidence selects or
preserves its correct current variant.  The diagnostic catalog currently
contains 182 such repeated citation identities.  This is intentionally more
conservative than admitting multiple content paths as interchangeable current
law.

No acquisition was launched for this implementation update.  Strict-reusable
current-source parser inputs therefore remain **0**, and the known residual
remains **36,118** exact inputs.  The preserved synthetic and secondary
artifacts remain nonauthorizing and unchanged.

Current source-software identity:

```text
ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee.TennesseeScraper@sha256:42e4c260c2be4599bd2acccf4763d6d907c2f214cc764770f3c3c0e8bc4b5528
```

## Safe next commands

With current code, this fresh isolated strict command is expected to stop at
the Tennessee delegated-frontier blocker.  It must not materialize, index, or
publish:

```bash
python scripts/ops/legal_data/refresh_state_laws_corpus.py \
  --states TN \
  --scrape \
  --strict-full-text \
  --max-statutes 0 \
  --parallel-workers 1 \
  --per-state-timeout-seconds 14400 \
  --output-root /tmp/state-laws-tn-strict-v1 \
  --acquisition-evidence-root /tmp/state-laws-tn-evidence-v1 \
  --strict-acquisition-evidence \
  --no-merge-existing-local \
  --no-skip-completed-states \
  --no-persist-completed-states-registry \
  --no-startup-stale-sync \
  --no-incremental-state-materialize \
  --no-incremental-state-publish \
  --json
```

After the exact delegated route exists, that is also the fresh acquisition
shape.  A safe residual restart repeats the exact command with the same output
and evidence roots; the ledger must replay successes and submit only missing
request identities.  A newly chosen evidence root is a fresh run, not a
residual retry.  Materialization, gte-small vectors, BM25, BM25-vocabulary
knowledge graph, centroid/meta indexes, and publication remain prohibited
until a subsequent dedicated closure run proves exact leaf algebra and
zero-network replay.
