# Provisional fixtures and retrieved context

The [context-to-projection handoff](context_projection_handoff.md) now connects
explicit fixture/cited bindings and retrieved structured slot manifests to
native Legal/UI target preparation and Lake checks. The candidate retrieval
layer described below continues to grant no source-truth authority.

A missing trigger, definition, referent or application policy should not force
us to stop developing its projection. Give the unresolved source an explicitly
assumed companion, test that companion, and continue collecting evidence for
the original. Keep these three objects separate:

1. **Original source:** exact bytes and unresolved slots; unchanged negative control.
2. **Provisional companion:** separately identified source and declared modeling
   premises. Its successful checks are conditional on those premises.
3. **Retrieved context:** exact supporting excerpts, candidate relationships,
   corpus/index revision and retrieval evidence. Ranking does not select meaning.

This implements the next step after the
[context diagnosis](projection_context_resolution.md). It does not automatically
promote an interpretation into a legal fact or training label. The Constitution
remains unformalized.

## Entry points

| Module | Public entry point | What it does |
| --- | --- | --- |
| `logic.formalization.context_resolution` | `ContextSpan.from_source` | Checks native SourceRef/SourceSpan against exact UTF-8 container bytes, hash and offsets |
| Same | `BoundedContextIndex` | Builds a reusable small BM25 shard plus explicit directed context links |
| Same | `prepare_context_bundle`, `validate_context_bundle` | Retrieves candidates for shared semantic slots, records provisional values and replays against original index bytes |
| `logic.formalization.context_retrieval_adapters` | `PinnedSparseContextRetriever` | Joins existing sparse GraphRAG/BM25 search results to registered exact spans |
| `logic.formalization.context_link_obligations` | `prepare_context_link_obligation`, `validate_context_link_obligation` | Produces a native `ProofSearchPlan`, explicit assumptions and an inert hammer handoff after index replay |
| `optimizers.logic_theorem_optimizer.provisional_context_panel` | `prepare_companion` | Constructs the two explicit Legal/UI companions and their v7 projection declarations |

No database schema, checkpoint, production parser, decoder or training gate is
changed. These APIs produce detached JSON evidence suitable for the existing
artifact/control-plane owners. They do not write to DuckDB, publish to the Hub,
enqueue supervisor tasks, download weights or increase model context windows.

## Gather context once per source

Create native `SourceRef` and `SourceSpan` records for the selected span and the
bounded support inventory. Pass their original, unnormalized document text to
`ContextSpan.from_source`; it verifies the entire source hash before extracting
the requested bytes. Reuse existing identities instead of inventing new corpus
span IDs. The standalone smoke contains a complete runnable example.

```python
index = BoundedContextIndex(
    verified_spans,
    revision="the-exported-index-revision",
    edges=[{"source_span_id": "selected", "target_span_id": "definition",
            "relation": "definition"}],
)
slots = [{
    "slot_id": "deadline-origin",
    "question": "deadline begins upon receipt of notice",
    "sort": "temporal_anchor",
    "projection_ids": ["legal-ir/modal-family/deontic/v3",
                       "legal-ir/modal-family/temporal/v3"],
}]
bundle = prepare_context_bundle(
    index, source_span_id="selected", slots=slots,
    fixtures=[{"slot_id": "deadline-origin",
               "value": {"trigger": "synthetic_notice_received"},
               "rationale": "Temporary authored premise for projection development."}],
)
validate_context_bundle(bundle, index=index)
```

The Legal families share one slot and its context. A fixture value changes the
slot status to `provisional`; `source_resolved` stays false. Removing the fixture
restores the unresolved interpretation without changing source bytes. The values
are inert JSON, not Lean text or executable tactics.

Retrieval uses adjacent indexed excerpts from the same document revision,
explicit parent/citation/definition/policy/support links (at most two hops), and
the existing lexical BM25 implementation. Neighboring excerpts need not be
contiguous and are never automatically governing context. Explicit links are
caller-declared retrieval relationships, not proven implications.

Local scoring and every graph hop enforce partition isolation. The caller must
assign connected source/context groups to consistent train/holdout partitions;
this module cannot detect a wrongly labeled split. Duplicate document versions
and dangling graph links are rejected. Repeated questions share one lexical
query; candidate texts are deduplicated across slots by artifact digest.

Defaults are eight candidates per slot, 32 KiB of unique context text, two graph
hops, 128 graph visits and a five-second local preparation budget. The shard is
bounded to 4,096 spans and 16 MB of serialized span records. Exceeded budgets
produce explicit incomplete diagnostics; they are not absence-of-evidence
proofs. Replay rejects incomplete bundles. The local shard is copied for a
request; this is bounded preparation, not an Arrow zero-copy training path.
The time budget is cooperative between bounded operations, not a process-level
interrupt of a running BM25 call.

## Use the existing sparse GraphRAG release

Inject a configured `OpenUsLawQueryClient.bm25_search` or compatible public
`RemoteSearchClient.bm25_search`. Register an explicit `entry_cid` to existing
span-ID map, repository ID and immutable 40-hex revision:

```python
retriever = PinnedSparseContextRetriever(
    searcher=client.bm25_search,
    spans=verified_spans,
    entry_bindings=[{"entry_cid": entry_cid, "span_id": "definition"}],
    repo_id=repository_id, revision=immutable_revision,
)
observation = retriever.search(slots[0]["question"], partition="train",
                               top_k=8, max_bytes=65536)
bundle = prepare_context_bundle(index, source_span_id="selected", slots=slots,
    sparse_observations=[observation.to_dict()])
```

The adapter checks corpus revision, verified fetch trace, exact hydrated source
bytes, excerpt offsets and finite scores. It creates no spans from arbitrary
search text. Unmapped entries remain diagnostic exclusions. Original text is
never normalized before hashing. Returned evidence is bounded separately from
the search client's I/O/time budget; configure that client before injection.
The adapter cannot interrupt an arbitrary Python callback or retroactively cap
its download/memory use.

Filtering returned candidates by partition does **not** prove the remote index
was holdout-isolated: document frequencies and rankings may already mix splits.
The report explicitly records that no holdout-safety claim is established.
Use a separately built partition-specific index for training evaluation. Local
replay verifies the registered bytes and joins; a self-hashed remote observation
does not become proof of an interpretation or the search transport's honesty.

## Exercise the previously blocked projections

`prepare_companion("legal_ir")` retains the original `within 10 days` negative
and creates an explicitly authored discrete-day, inclusive-boundary
interpretation with a synthetic trigger binding. Its origin remains a parameter;
no actual event occurrence is asserted. The temporal view is declared to be the
body inside the obligation. A companion manifest does not repair native AST
containment in the generic ModalIR producer.

`prepare_companion("ui_ux_ir")` retains the original high-risk single-confirm
negative and declares a request-correlated, finite-prefix confirmation policy.
The synthetic maximum age is ten ticks; cancellation and consumption are
explicit assumptions. No real confirmation/invocation/completion trace is
invented. These fixtures exercise supported profiles, not every application
policy or legal calendar convention.

The runner retains all 27 emitted projections and the complete 40-family
inventory per modality. Required native syntax checks, actual modality Lake
builds and applicable SANY checks run through the existing v5 path. Missing
applicability reviews and capability floors remain blockers for strict training;
the runner fabricates none. It performs no numerical training and makes no
heldout reconstruction claim.

```bash
PYTHONPATH="$PWD" python scripts/ops/autoencoder/smoke_context_retrieval.py \
  --output workspace/test-logs/context-retrieval-new

PYTHONPATH="$PWD" python scripts/ops/autoencoder/smoke_provisional_context_fixtures.py \
  --output workspace/test-logs/provisional-fixtures-new \
  --lake /path/to/installed/lean-toolchain/bin/lake \
  --java-executable /path/to/installed/java17/bin/java \
  --tla2tools-jar /path/to/installed/tla2tools.jar
```

Use the canonical tree or an exact reviewed export with explicit `PYTHONPATH`.
Both scripts require fresh output directories. No HACC or hallucinate_app tree
is modified. Successful fixture builds are not admissions of their original
sources; only actual Lake execution supplies Lean build evidence.

## Resolution and training handoff

Review each proposed context relationship against exact source scope, revision,
definitions and competing readings. Formalize the selected relationship and
retain the assumptions used by the prover. Hammer/tactician can search for
existing lemmas, generate conditional obligations and propose section links;
unproved retrieved prose must never enter their premise corpus as a theorem.
Proof of `premises → consequence` establishes no source support for the premises.

The link-plan API accepts a replayed bundle, slot ID, retrieved candidate span
ID, proposed JSON binding and typed relationship. It retains both source
records, retrieval path, dependent projections and undischarged assumption IDs.
Its native `ProofSearchPlan` describes source review, typed lowering, conditional
hammer work and native validation. Hammer execution stays
`awaiting_reviewed_typed_goal_and_premises`; the adapter registers no theorem or
goal and does not run a prover. The standalone retrieval smoke exports two
such plans. They are not supervisor-importable tasks until the reviewed routing
integration is implemented.

After source/context review and supported typed lowering, regenerate every
dependent projection and run the unchanged syntax, Lake, floor and loss gates.
Cache keys must include source/context, fixture or reviewed interpretation,
index/policy revision and producer hashes. Replacing a provisional value must
invalidate its dependent targets. The current release prepares evidence and
companions; production automatic semantic extraction, reviewed binding
promotion, supervisor ingestion and distributed cache invalidation are separate
integration work, not silently enabled here.

## Validation evidence

An exact export of package revision `bc8ee2a7459ba9bf2a277d765e87891b54791fb4`
plus the completed context files passed **64 tests in 12.916 seconds**. This includes an
actual offline sparse GraphRAG query through `OpenUsLawQueryClient` and
`LocalRootTransport`, byte/revision/partition checks, source-drift rejection,
rehashed-tampering rejection, provisional assumptions and link-plan replay.

The fresh companion smoke passed **27 of 27 emitted projections**, with two
actual successful builds (`LegalIR`, `UIUXIR`) and one UI SANY check, in
**15.432 seconds**. It used installed Lean 4.30.0, Java 17.0.20 and tla2tools
1.8.0, with tool hashes checked before and after execution. The original three
semantic blockers remained unchanged and both strict training decisions stayed
false pending separate reviews/floors.

The authored five-span local retrieval smoke exercised two selections and two
inert linking plans, with one BM25 query per selection and no proof/model run.
This small fixture run is a functional check, not a corpus throughput or bridge
evaluation benchmark. No speedup or low-resident-memory claim is made.

The first validation used `d5238def2`; a concurrent publication advanced main
and included earlier context drafts. Validation was repeated on the new main
revision with the completed files, preserving the other published changes.

See [results](../implementation/reports/evidence/provisional-context-main-20261001/results.json)
and the accompanying manifest/archive for raw observations, generated Lean,
initial failed test attempt, source snapshots and final test receipts.
