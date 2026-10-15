# Public V2 definition-use handoffs

The public reasoning package exposes its existing 553 ordered names through lazy
owner imports. Importing source-map and symbol helpers for a definition-use
handoff therefore does not initialize the verifier, learned guidance, model
training, or optional SymbolicAI configuration. A caller that explicitly requests
one of those optional owners still needs that owner's dependencies and setup.

The owner table preserves the effective bindings of the former eager facade,
including the final schema-evolution binding of
`LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION`. The four public functions whose names also
name child modules retain their function-facing behavior when the corresponding
owner loads. Loading an owner must also preserve explicit caller overrides made
before or after that load, apart from the inherited convention that the exact
colliding owner-module object resolves to its public function. This is a public attribute compatibility rule, not a
promise that importing every optional owner works without its dependencies.

The facade and handoff tests were selectively adopted from the existing fix at
`f3b51b007bf60be9420788099dec26c5555930a4`, whose parent is
`72c4bb353f03682f34a694f3f476fa59c186f8b0`. The local change additionally preserves
overrides installed before a colliding child owner first loads. The adoption
receipt records original Git blobs separately from this local correction. Other
source from that checkout, its models, datasets and run artifacts were not
copied. The earlier failed 300-case qualification and the later external
316-case qualification retain their own source and observation cutoffs; neither
is a substitute for testing this checkout.

## Fresh-process transport

The supported exchange carries the complete original definition-use component,
the exact review assessment and its independently pinned raw inputs, and the
prepared ten-file project. The graph, review and project exchange tests exercise
the actual public owners in a fresh Python process, including restrictions on optional
imports, subprocesses and configuration writes. Their authored JSON, JSONL and
Parquet fixtures are synthetic test inputs; they are not the statutory span or
entity caches.

A successful exchange establishes that the public owners can reconstruct the
same candidate and review dependencies from transported files. It does not
authorize a source interpretation or promote a review. The caller must keep an
externally trusted pin for each original assessment/receipt; a freshly resealed
derivative is not an independent source of authority. Review registry, policy,
exact dependency population and original source/context inputs remain part of
validation. See the [V2 preparation contract](legal_corpus_definition_use_lake_v2.md)
and [native build contract](legal_corpus_definition_use_build_v2.md).

## Actual authored native qualification

The owned integration retains separate fictional FOL and TDFOL candidates. The
TDFOL fixture contains four declared TDFOL fragments for quantified unary Boolean
definitions and an explicit assumed alias. It introduces no new modal norm
semantics. Each candidate has six generated modules and three conditional
theorems: predicate/donor-body equivalence under the exact assumptions, joint
assembly under all component premises, and modular/original joint equivalence.

The actual TDFOL baseline was compiled at
`d00ace8bd0ac96c30cf4a4e12b1d442876390539` before this import adoption. A second
bounded build of the same unchanged fixture qualifies the adopted source and
compares all six output files with that baseline. These are two observations of
the same three TDFOL theorems. Each invocation uses independently pinned Lake and
Lean binaries, bounded version probes, the existing validation lease and the
existing offline, no-cache build adapter. Saved readback is checked after the
lease is released. Installed-library closure and incremental/cache reuse remain
separate work.

Successful Lean checking establishes these conditional technical statements for
the authored inputs. The original preparation remains pending with unavailable
review registry/policy and no reviews. Its preparation-era wording is retained;
later receipts describe the subsequent build. Actual statutory source/meaning
decisions, legal/formal reviews, governing-use acceptance, training/gold status,
graph admission and Lean corpus admission require their own evidence. This
qualification creates none of those decisions or admissions.

## Next corpus step

Apply the supported source/context and definition-use contracts to a small
connected statutory pilot with independently reviewed meaning and applicability.
Retain span and entity provenance from the existing caches, both original ASTs,
the explicit alias assumption, and complete graph endpoints. The initial profile
uses a representative first matching role for lookup and binds the whole
predicate consistently; it does not establish per-occurrence governing lookup.
Same-document multi-definition carriers, broader term/norm semantics, complete
toolchain closure and incremental rebuild validity need separately specified
extensions.
