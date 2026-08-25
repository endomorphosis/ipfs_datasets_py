# US Code Sparse GraphRAG Gold Set Rationale (USCIR-003)

## Purpose

This report freezes the legal retrieval and graph evaluation suite for
`publicus-ir-graphrag/v2` before BM25, vector, hybrid, or graph tuning.
The sealed fixtures are:

| Artifact | Path |
|---|---|
| Positive gold set | `tests/fixtures/legal_ir/uscode_sparse_gold.json` |
| Negative controls | `tests/fixtures/legal_ir/uscode_sparse_negative_controls.json` |
| Integrity tests | `tests/unit/logic/legal_ir/test_uscode_goldset.py` |

Labels are grounded in official U.S. Code citations and the program's sealed
release authority. Generated model relevance labels are not authoritative.

## Release authority and currentness

The gold suite is bound to:

- **Release point:** `us/pl/118/45`
- **Edition:** `olrc-us-pl-118-45`
- **Provider:** House Office of the Law Revision Counsel (`olrc_house`)
- **Pinned baseline corpus revision:** `75cfc5982dc3a6808614cd4eb9b4238f8f9308b8`

Publication and acquisition timestamps are **not** claims of wall-clock legal
currentness. Time-sensitive queries must expose the release point/edition, and
individualized “what is the law for my case today” questions may require
abstention. Retrieval output remains a research aid, not a substitute for the
official source.

## Title coverage

The suite covers representative provisions from Titles
**5, 11, 17, 18, 26, 28, 31, 35, 42, and 47**:

| Title | Representative provisions | Why included |
|---|---|---|
| 5 | § 552 FOIA; § 552(a) procedures; § 552a Privacy Act | Information-law exact, subsection, and cross-statute paths |
| 11 | § 362 automatic stay | High-traffic bankruptcy doctrine with synonym demand |
| 17 | § 107 fair use | Copyright doctrine with strong semantic/synonym forms |
| 18 | § 1030 CFAA | Criminal computer-access provision |
| 26 | § 61 gross income; § 501 tax-exempt orgs | Tax code synonym and semantic retrieval |
| 28 | § 1331 federal question; § 1367 supplemental; § 1441 removal | Jurisdiction graph and cross-title civil procedure |
| 31 | § 3729 False Claims Act | Civil enforcement synonym path |
| 35 | § 101 eligibility; § 103 obviousness; § 112 specification | Patentability graph and historical-version ambiguity |
| 42 | § 1983 civil rights; § 12101 ADA findings | Civil-rights synonym and disability provisions |
| 47 | § 230 platform immunity | Communications Act exact/synonym and currentness controls |

These match the evaluation set enumerated in
`docs/architecture/USCODE_SPARSE_GRAPHRAG_PLAN.md` §8.

## Query and label taxonomy

### Query kinds

| Kind | Intent |
|---|---|
| `exact_citation` | Bluebook/compact citation lookup |
| `synonym` | Popular name or paraphrase without a formal citation |
| `semantic` | Natural-language doctrinal description |
| `subsection` | Chunk/subsection-scoped retrieval |
| `cross_title` | Multi-title support set |
| `graph_path` | Explicit multi-hop statutory path |
| `historical_version` | Version/edition ambiguity |
| `time_sensitive` | Release exposure / abstention boundary |

### Label kinds

| Label kind | Meaning |
|---|---|
| `exact_section` | Canonical section is the primary hit |
| `relevant_subsection` | Subsection/chunk is the primary or supporting unit |
| `supporting_citation_path` | Related authority that should appear in support or graph expansion |
| `authoritative_source_evidence` | Reserved for source-receipt checks against official packages |
| `known_ambiguity` | Multiple plausible readings or vintages; must not force a single exact hit |
| `abstention` | Research-aid boundary; do not present sealed text as case-specific current advice |
| `time_sensitive` | Retrieval allowed only with explicit release/edition exposure |

### Grades

`exact`, `relevant`, `ambiguous`, `abstain_candidate`, and `not_relevant`.

## Train / dev / test partitions

| Partition | Role | Leakage rule |
|---|---|---|
| `train` | Qualitative inspection and non-reporting iteration | Must not be used as the sealed final metric split |
| `dev` | Fusion weights, probe counts, and other tunable selection | May guide tuning; not final reported numbers |
| `test` | Sealed evaluation | Report once after freeze; no post-hoc label edits for score chasing |

Partition assignments are explicit in `partition_index` and on each query.
Every required title appears in at least one positive gold query. Negative
controls also span train/dev/test so fail-closed behaviors are exercised on
every split.

## Identity contract

Each gold document carries:

- **`legal_id`** — stable citation-oriented identity
  (`usc:us:{title}:{section}[;qualifiers]`), independent of content version.
- **`entry_cid`** — sealed retrieval primary-key token for the gold document stub.
- **`source_cid`** — sealed source-evidence token for provenance joins.

Judgments reference both `legal_id` and `entry_cid` so later BM25/vector/graph
evaluators can join either by durable legal identity or by content-addressed
entry key. Qualifier-bearing identities (for example
`usc:us:5:552;subsection=a`) exercise subsection/chunk parentage without
collapsing to bare `(title, section)`.

## Graph paths

Three sealed graph paths freeze multi-hop expectations before graph tuning:

1. **Civil-rights jurisdiction path (dev):** § 1983 → § 1331 → § 1441.
2. **Patentability trio (test):** § 101 with related § 103 and § 112.
3. **FOIA / Privacy Act path (test):** § 552 related to § 552a.

Edges are doctrinal support relations, not lexical co-occurrence. They exist
to evaluate structural and semantic graph walks without inventing citation
edges that the official source does not support.

## Negative controls

Negative controls seal behaviors that pure positive qrels cannot express:

| Control kind | Expectation |
|---|---|
| Fabricated citation | No exact hit |
| Wrong-title confusion | Patent rows are not exact FOIA hits |
| Out-of-corpus jurisdiction | State statutes are not U.S. Code exact hits |
| Lexical decoy | Homonym “Section 230” does not force 47 U.S.C. § 230 |
| Recovery-row contamination | Quarantine/recovery rows never enter default exact hits |
| Currentness overclaim | Release exposure required; no wall-clock currentness claim |
| False friend | Unrelated doctrines are not jointly exact |
| Noise query | Stopword queries produce no confident exact hits |
| Individualized advice | Outcome prediction is not gold exact authority |
| Fabricated subsection | Imaginary subsections are not exact subsection hits |

## Grounding and review policy

- Labels are human-authored against official citation identity, not model
  outputs.
- No generated relevance label is treated as authoritative without review
  evidence (task precondition).
- The suite freezes expectations **before** hybrid/graph weight tuning so
  later evaluation cannot silently retarget labels to improve scores.
- Changes require a schema-version bump (`uscode-sparse-gold-v1` /
  `uscode-sparse-negative-controls-v1`) and an explicit rationale update.

## Validation

```bash
python -m pytest tests/unit/logic/legal_ir/test_uscode_goldset.py -q
```

The unit suite asserts title coverage, train/dev/test partitions, unique
stable `legal_id`/`entry_cid` values, judgment join integrity, graph-path
consistency, and negative-control structure.
