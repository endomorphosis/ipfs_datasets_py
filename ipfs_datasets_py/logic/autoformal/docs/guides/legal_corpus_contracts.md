# Legal corpus source and qualification contracts

The additive corpus contracts preserve exact source identity, extracted-view
occurrences, declared context, orthogonal qualification and candidate graph
endpoints. They are a foundation for the span-to-graph-to-Lean pipeline. Existing
span/entity caches, checkpoint formats and model selection remain unchanged.

The implementation is pure data validation. It does not run an encoder, compiler,
solver or Lake, fetch evidence, authenticate a reviewer or establish legal meaning.
Records use the existing canonical CIDv1 DAG-JSON owner. Their CID excludes only
the `record_cid` field; `cid_scope` is part of the hashed payload.

## Source versions and occurrences

`logic.autoformal.corpus_source` supplies:

- `build_source_version` and `validate_source_version`, binding exact raw bytes
  and an extracted text view to caller-supplied expected SHA256 digests, profiles,
  provision, release and edition.
- `build_source_occurrence` and `validate_source_occurrence`, binding character
  and UTF8 half-open intervals to the same nonempty physical occurrence.
- `build_context_declaration` and `validate_context_declaration`, retaining
  `none_required`, `declared_context` or `required_unavailable` without guessing.

All selectors address the extracted view. They are never labelled as raw HTML or
PDF byte offsets. Without raw bytes, source validation checks the raw CID/SHA pair
and independently expected digest, rather than claiming the raw artifact is
available. Historical IDs remain `declared_alias`, `unresolved` or `unsupported`;
aliases do not establish equivalence. Context references remain declarations and
are not resolved by these functions.

```python
import hashlib
from ipfs_datasets_py.logic.autoformal.corpus_source import (
    build_source_occurrence,
    build_source_version,
)

# Authored engineering example, not statutory gold.
raw = b"<p>The registrar shall file notice.</p>"
text = "The registrar shall file notice."
source = build_source_version(
    source_id="fixture:registrar", release_id="fixture-release:1",
    edition="1", provision_id="fixture:section:1",
    raw_bytes=raw, expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
    extracted_text=text,
    expected_extracted_sha256=hashlib.sha256(text.encode()).hexdigest(),
    extraction_profile="fixture-visible-text/v1",
    normalization_profile="identity/v1", media_type="text/html",
)
occurrence = build_source_occurrence(
    source, expected_raw_sha256=source["raw_artifact"]["sha256"],
    extracted_text=text,
    expected_extracted_sha256=source["extracted_view"]["sha256"],
    start_char=0, end_char=len(text), start_utf8=0, end_utf8=len(text.encode()),
)
```

Real consumers obtain expected digests from their pinned intake manifest. The
example computes both sides locally to demonstrate API shape; it supplies no
independent source authenticity.

## Qualification declarations

`corpus_qualification.prepare_qualification` binds eight dimensions to exactly
one artifact CID and profile: processing, source integrity, interpretation,
representation, dependencies, native translation, Lean compilation and proof.
Affirmative statuses require evidence CID references. Requested proof and
`not_requested` are distinct, and a declared discharged Lean proof requires
declared passed compilation.

`derive_eligibility` returns candidate-graph, reviewed-graph and checked-Lean
views with `declared_eligible` and explicit blockers. These are **declared evidence
only**, not admission. Evidence/reviewer authentication, source semantics, proof
authority, admission and formalization flags remain false. A consumer must apply
its own evidence-resolution and authority policy before treating a record as
reviewed or checked. `validate_eligibility` recomputes the view from the exact
qualification, rejecting even a resealed invented eligibility result.

`adapt_legacy_qualification` preserves sealed/gap/admitted/formalized observations
descriptively. It may translate processing readiness, but grants no review,
source, dependency, compilation or proof credit from those flags.

## Candidate graph envelopes

`corpus_graph.build_node`, `build_edge`, `build_graph_snapshot` and corresponding
validators provide a closed local candidate graph. Nodes reference separately
stored content and preserve scope and alternative-interpretation identities.
Assertions require source-occurrence and interpretation reference slots; those
references are not automatically fetched or authenticated.

Every edge endpoint must exist in the same snapshot. External imports are
unsupported in this first profile and produce an explicit error. Role edges
have explicit ordinals and compatible destination kinds; repeated arguments
survive at distinct positions, while conflicting positions refuse. Definition
and denotation edges enforce their declared endpoint kinds. Edges cannot connect
mutually exclusive readings in the same alternative group.

Canonical storage order is independent of input order. Semantic argument order
is retained by edge ordinals and the separately referenced typed payload; hash
sort order is not statutory order. The snapshot remains `view="candidate"`, with
admission, formalization and source-semantic flags false. Scoped definition
resolution, complete AST validation, external imports and authenticated release
qualification are later pipeline contributions.

The additive [paired-span adapter](legal_corpus_span_adapter.md) now retains
source-bound or explicitly unresolved cache observations as opaque candidate
interpretations. The [graph exchange](legal_corpus_graph_exchange.md) transports
complete graph envelopes through hash-bound Parquet and supplies a local
validator CLI. Both retain candidate-only status; typed semantic projection,
source review and a unified Lean release remain separate work.

The [legacy source-join ledger](legal_corpus_legacy_source_join.md) now retains
every exact stored-Parquet occurrence candidate without selecting a historical
producer occurrence. The [proposed-graph bridge](legal_corpus_proposed_graph_adapter.md)
reuses the existing graph and official HTML selector owners, independently
regenerates source geometry and retains original graph identities/ordered ASTs
through candidate export. The two coordinate profiles remain distinct; no
view-to-view equivalence or semantic definition encoding is inferred.

The separately supported [definition/norm adapter](legal_corpus_definition_norm_adapter.md)
now regenerates explicit section-local unary definitions and universally guarded
norms through their existing owner. It preserves all supporting paragraphs,
composition-bound symbols and native ASTs, and emits candidate `DEFINES` and
`USES_DEFINITION` links. This profile encodes the caller's declaration; source
review, authenticity, context closure and Lean compilation remain unverified.

The [graph-bound Lean preparer](legal_corpus_lake.md) now delegates a complete
independently pinned candidate population to the existing definition/norm Lake
owner. It maps source occurrences, typed graph assertions and definition-use
edges to every generated joint module, preserving the native project bytes.
Its exact local readback remains preparation evidence: shared-definition
deduplication, reviewed statutory meaning and an actual corpus build remain open.

The additive [shared-definition profile](legal_corpus_shared_lake.md) now emits
one module for each exactly matching scoped/source-bound definition and imports
it from its original norms, preserving every candidate's provenance. Its
bounded build boundary covers the exact shared package and conditional
definition-use theorems. Legal source qualification remains separate from
kernel compilation and those explicit-premise obligations.

## Import and validation behavior

Importing these public modules no longer constructs `autoformal.SESSION`.
The existing session is created under a lock on first attribute access or
dispatch, with its original compiler/decompiler/parser tree checks intact.
`reset_session()` still explicitly constructs a fresh session. Unknown dispatch
does not create one.

`corpus_contracts.load_record_bytes` accepts expected-digest-bound JSON and rejects
duplicate keys, nonfinite values, invalid UTF8 and oversized input. Individual
records have a one-MiB bound plus depth/node limits. Candidate graphs also check
aggregate input bounds before per-record validation. Larger corpus snapshots
need explicit partitioning rather than a raised implicit bound.

Focused tests cover seals and tampering, raw/extracted digest binding, Unicode
geometry, repeated occurrences, context gaps, legacy promotion, resealed false
eligibility, dangling/typed endpoints, argument order, exclusive readings and
actual public imports/session lifecycle. The broader legacy alias-loader tests
have separate parent-comparison evidence; this contribution does not change their
parser semantics or report their existing failures as passing.
