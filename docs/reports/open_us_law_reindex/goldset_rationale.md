# Open US Law Sparse GraphRAG Gold Set Rationale (OUL-036)

## Purpose

This report freezes the jurisdiction-diverse legal retrieval and graph
evaluation suite for `open-us-law-sparse-graphrag/v1` before BM25, vector,
hybrid, or graph tuning. The sealed fixtures are:

| Artifact | Path |
|---|---|
| Positive gold recipe | `tests/fixtures/legal_ir/open_us_law_sparse_gold.json` |
| Negative-control recipe | `tests/fixtures/legal_ir/open_us_law_sparse_negative_controls.json` |
| Integrity tests / expander | `tests/unit/processors/legal_data/test_open_us_law_goldset.py` |

The on-disk fixtures are compact sealed recipes. They do not re-emit a full
envelope per case. Deterministic expansion lives in
`tests/unit/processors/legal_data/test_open_us_law_goldset.py`
(`materialize_gold_payload`, `materialize_negative_controls`) and binds
`legal_id` values through `open_us_law_schema.build_legal_id` plus the
OUL-002 official source catalog.

Labels are grounded in official state/DC citations and that catalog.
Generated model relevance labels are not authoritative.

**This gold set is not legal advice.** Retrieval output is a research aid and
is not a substitute for the official source of any jurisdiction.

## Release authority and currentness

The gold suite is bound to:

- **Release point:** `us/state-statutes/exact-51/2024-official`
- **Edition:** `2024-official`
- **Provider:** official state legislatures in the exact-51 set
- **Pinned gold-set identity:** SHA-1 of `open-us-law-sparse-gold-v1|OUL-036`
- **Source catalog:** `data/legal/state_laws/official_source_catalog.json`
- **Dataset target:** `justicedao/open-us-law-sparse-graphrag`
- **Source bucket:** `justicedao/open-us-law-bucket`
- **Embedding pin:** `thenlper/gte-small` @ `17e1f347d17fe144873b1201da91788898c639cd`

Publication and acquisition timestamps are **not** claims of wall-clock legal
currentness. Time-sensitive queries must expose the release point/edition, and
individualized “what is the law for my case today” questions require
abstention. Historical and repealed rows use explicit edition and status
qualifiers rather than implying that the sealed 2024 official pin is the
vintage of interest.

## Jurisdiction and cohort coverage

The suite covers every exact-51 jurisdiction (50 postal state codes + DC) and
every acquisition cohort A–M:

| Cohort | Task | Jurisdictions | Representative exact citation |
|---|---|---|---|
| Cohort A | OUL-009 | AL, AK, AZ, AR | Ala. Code § 36-12-40 |
| Cohort B | OUL-010 | CA, CO, CT, DE | Cal. Gov't Code § 7922.530 |
| Cohort C | OUL-011 | FL, GA, HI, ID | Fla. Stat. § 119.07 |
| Cohort D | OUL-012 | IL, IN, IA, KS | 5 ILCS 140/3 |
| Cohort E | OUL-013 | KY, LA, ME, MD | KRS § 61.872 |
| Cohort F | OUL-014 | MA, MI, MN, MS | M.G.L. c. 66, § 10 |
| Cohort G | OUL-015 | MO, MT, NE, NV | RSMo § 610.023 |
| Cohort H | OUL-016 | NH, NJ, NM, NY | N.Y. Pub. Off. Law § 87 |
| Cohort I | OUL-017 | NC, ND, OH, OK | R.C. 149.43 |
| Cohort J | OUL-018 | OR, PA, RI, SC | ORS 192.314 |
| Cohort K | OUL-019 | SD, TN, TX, UT | Tex. Gov't Code § 552.021 |
| Cohort L | OUL-020 | VT, VA, WA, WV | RCW 42.56.070 |
| Cohort M | OUL-021 | WI, WY, DC | D.C. Code § 2-532 |

Every jurisdiction appears as a gold document with official `code_family`,
`official_source_id`, `official_url`, `source_cid`, and `rights_record_id`
from the sealed source catalog. Every jurisdiction is a judgment target at
least once. One exact-citation query is sealed per cohort and partitioned
across train/dev/test so no lane is evaluation-only or train-only.

## Query and label taxonomy

### Query kinds

| Kind | Intent |
|---|---|
| `exact_citation` | Compact/Bluebook-style citation lookup |
| `terminology_variant` | Popular name or paraphrase (FOIL, OPRA, Sunshine Law, GRAMA, UIPA, RTKL, CCPA, Right-to-Know) |
| `semantic` | Natural-language doctrinal description |
| `subsection` | Chunk/subsection-scoped retrieval |
| `cross_state_ambiguity` | Same topic, unnamed or conflicting jurisdiction |
| `repealed_or_reserved` | Reserved placeholder or recodified/repealed text |
| `graph_citation` | Explicit multi-hop statutory path |
| `source_provenance` | Official host / source-id join, not a secondary aggregator |
| `historical_version` | Edition/vintage ambiguity |
| `time_sensitive` | Release exposure / abstention boundary |
| `no_legal_advice` | Individualized outcome prediction must abstain |

### Label kinds

| Label kind | Meaning |
|---|---|
| `exact_section` | Canonical section is the primary hit |
| `relevant_subsection` | Subsection/chunk is the primary or supporting unit |
| `supporting_citation_path` | Related authority that should appear in support or graph expansion |
| `authoritative_source_evidence` | Official source-id / source CID join |
| `known_ambiguity` | Multiple plausible jurisdictions or vintages; must not force a single exact hit |
| `abstention` | Research-aid boundary; do not present sealed text as case-specific current advice |
| `time_sensitive` | Retrieval allowed only with explicit release/edition exposure |
| `repealed_or_reserved` | Status must be exposed; reserved/repealed rows are not current authority |

### Grades

`exact`, `relevant`, `ambiguous`, `abstain_candidate`, and `not_relevant`.

## Train / dev / test partitions

| Partition | Role | Leakage rule |
|---|---|---|
| `train` | Qualitative inspection and non-reporting iteration | Must not be used as the sealed final metric split |
| `dev` | Fusion weights, probe counts, and other tunable selection | May guide tuning; not final reported numbers |
| `test` | Sealed evaluation | Report once after freeze; no post-hoc label edits for score chasing |

Partition assignments are explicit in `partition_index` and on each query.
Negative controls also span train/dev/test so fail-closed behaviors are
exercised on every split.

## Identity contract

Each gold document carries:

- **`legal_id`** — stable citation-oriented identity
  (`oul:{kind}:{JJ}:{code_family}:{path}[;qualifiers]`), independent of
  content version. Current status is omitted; `repealed`, `reserved`, and
  `historical` statuses are explicit qualifiers.
- **`entry_cid`** — sealed retrieval primary-key token (`bafkreie…`).
- **`source_cid`** — sealed official-source evidence token (`bafkreis…`).
- **`official_source_id` / `official_url` / `rights_record_id`** — catalog
  provenance from OUL-002 / LCR-002, never a secondary commercial mirror.

Judgments reference both `legal_id` and `entry_cid` so later
BM25/vector/graph evaluators can join either by durable legal identity or by
content-addressed entry key. Qualifier-bearing identities (for example
`…;subsection=a` and `…;status=reserved`) exercise subsection parentage and
currency without collapsing to a bare section token.

Puerto Rico, federal U.S. Code, constitutions, recovery, and quarantine
identities are excluded from default exact-51 gold documents.

## Graph citations

Four sealed graph paths freeze multi-hop expectations before graph tuning:

1. **Oregon public-records path (dev):** ORS 192.311 definitions → ORS 192.314
   inspection right → ORS 192.329 agency response.
2. **New York FOIL path (test):** Pub. Off. Law § 84 declaration → § 87 access
   → § 89 procedures.
3. **New Jersey OPRA path (train):** N.J.S.A. 47:1A-1 findings → 47:1A-5 access.
4. **California CPRA recodification path (test):** former Gov. Code § 6253
   (repealed) → current Gov. Code § 7922.530.

Edges are doctrinal support or recodification relations, not lexical
co-occurrence. They exist to evaluate structural and semantic graph walks
without inventing citation edges the official source does not support.

## Terminology variants

Popular-name queries are sealed without requiring a formal citation:

| Variant | Jurisdiction | Canonical target |
|---|---|---|
| FOIL | NY | N.Y. Pub. Off. Law § 87 |
| OPRA | NJ | N.J.S.A. 47:1A-5 |
| Sunshine Law | MO | RSMo § 610.023 |
| GRAMA | UT | Utah Code § 63G-2-201 |
| Right-to-Know | NH | RSA 91-A:4 |
| RTKL | PA | 65 P.S. § 67.701 |
| UIPA | HI | HRS § 92F-11 |
| CCPA | CA | Cal. Civ. Code § 1798.100 |

## Cross-state ambiguity

Two complementary cases are sealed:

- **Unscoped “state FOIA”** — FOIA-named analogs in AR, CT, DE, IL, MI, SC,
  VA, WV, and DC are jointly `ambiguous`. Systems must not force a single
  exact hit.
- **Named “California FOIA”** — the California Public Records Act is the
  exact hit; other states’ FOIA-named statutes must not be exact.

A negative control further forbids treating New York FOIL as an exact hit
for a Texas FOIL query.

## Repealed or reserved status

- **Reserved:** ORS 192.315 is sealed as `status=reserved` and must not be
  treated as the current Oregon inspection right (that remains ORS 192.314).
- **Repealed/recodified:** former Cal. Gov't Code § 6253 (`2022-official`,
  `status=repealed`) is not current CPRA inspection authority.
- **Historical edition:** Ga. Code Ann. § 50-18-70 at `2012-official` is an
  edition-scoped vintage and must not silently collapse onto `2024-official`.

## Source provenance

Provenance queries require a join to the official catalog source, not a
secondary aggregator:

- Oregon: `or-legislature-ors`
- Texas: `tx-capitol-statutes`

Every gold document carries `source_authority_class=official`. The unofficial
Justia control rejects treating a commercial mirror as official provenance
even when the underlying citation is real.

## Explicit no-legal-advice controls

The gold set and the negative-control fixture both freeze the advice
boundary:

- Gold query `q-test-no-legal-advice-outcome` asks whether the user should
  sue and will win; the expectation is `abstention`.
- Negative control `neg-private-advice` allows research-aid retrieval of
  ORS 192.314 but forbids presenting a win/lose prediction as gold exact
  authority.
- Fixture-level `not_legal_advice: true` and the currentness disclaimer
  apply to every split.

## Negative controls

Negative controls seal behaviors that pure positive qrels cannot express:

| Control kind | Expectation |
|---|---|
| Fabricated citation | No exact hit |
| Cross-state confusion | NY FOIL is not an exact Texas hit |
| Out-of-corpus jurisdiction | Federal FOIA and Puerto Rico are not exact-51 hits |
| Lexical decoy | Homonym section numbers and federal § 230 do not force state exact hits |
| Recovery-row contamination | Quarantine/recovery rows never enter default exact hits |
| Currentness overclaim | Release exposure required; no wall-clock currentness claim |
| False friend | CPRA inspection and CCPA privacy are not jointly exact |
| Noise query | Stopword queries produce no confident exact hits |
| Individualized advice | Outcome prediction is not gold exact authority |
| Fabricated subsection | Imaginary subsections are not exact subsection hits |
| Unofficial source | Secondary aggregators are not official provenance |
| Reserved-as-current | Reserved rows are not current inspection authority |

## Grounding and review policy

- Labels are human-authored against official citation identity and the
  OUL-002 source catalog, not model outputs.
- No generated relevance label is treated as authoritative without review
  evidence (task precondition).
- The suite freezes expectations **before** hybrid/graph weight tuning so
  later evaluation cannot silently retarget labels to improve scores.
- Fixtures store citation stubs, headings, and provenance — not full
  statutory text envelopes — so they stay compact and secret-free.
- Changes require a schema-version bump (`open-us-law-sparse-gold-v1` /
  `open-us-law-sparse-negative-controls-v1`) and an explicit rationale update.

## Validation

```bash
python -m pytest tests/unit/processors/legal_data/test_open_us_law_goldset.py -q
```

The unit suite expands the compact recipes, then asserts cohort and
exact-51 coverage, train/dev/test partitions, unique stable
`legal_id`/`entry_cid` values, judgment join integrity, graph-path
consistency, official-source provenance, repealed or reserved status, and
no-legal-advice negative-control structure.
