# LegalIR V2 definition alias integration

The additive definition-use candidate adapter is now integrated from
`6b5ee085a9ffc4cb2492552ca31b335badfd1fc1`, preserving its three file bodies
and author through import `7e34bb15d`. It connects two existing definition
candidates with a separately declared alias assumption. The
[US Code improvement plan](legal_ir_uscode_corpus_improvement_plan_20261015.md)
continues to require actual source/meaning reviews and supported complete uses
before statutory graph or training admission.

## Supported component

The [adapter contract](corpus_definition_use_v2.md) accepts two distinct physical
documents, one unary definition candidate at each endpoint, matching native
families and exactly equal declared applicability. It retains both original
ASTs and adds `forall x, B(x) iff A(x)` as an explicit unreviewed assumption.
The joint AST is the donor definition conjoined with the consumer definition
and that assumption. Generated conditional Lean text does not prove the alias.

All matching consumer body roles and physical occurrences remain explicit.
Lookup covers the first matching role in existing binding order as a
representative of the predicate. `per_occurrence_lookup_verified` stays false;
role multiplicity does not establish governing lookup at every occurrence.
The complete supplied registry, route, source/scope bindings and declared
lookup dependencies remain part of the candidate.

The graph retains both original graphs and adds the alias interpretation and
candidate `USES_DEFINITION` edge between definition-assertion graph-node CIDs.
It supplies no norm or ground actor. The separate
[combined-use review domain](corpus_definition_use_review_v2.md) now binds this
new interpretation; original definition reviews cannot approve the alias,
joint AST or new edge. This adapter accepts no review credentials.

## Qualification

The [execution receipt](evidence/legal-ir-definition-use-v2-integration-20261015/qualification-v01/receipt.json)
and [independent recount](evidence/legal-ir-definition-use-v2-integration-20261015/independent_recount.json)
record **302 unique cases across ten complete modules**, zero failures/errors/
skips, with all **506 listed input bindings**, HEAD and index unchanged during
execution. The original author's 255 cases are a subset of this run.

The three-path contribution adds no changes to existing runtime files. The
focused suites cover its 44 cases, resolver, V2 preparation/compiler/adapter,
dependency and graph owners, graph exchange and import controls. The prior
966-case qualification remains attributable to its original generation; it
was not repeated or added to this count. All 501 inputs listed by that earlier
run retain the same file bodies in this checkout.

Three new integration cases exercise the following boundaries:

- FOL and TDFOL: fully validate a component, write actual Parquet through the
  existing public graph writer, and read it in a fresh interpreter. Exact graph
  endpoints/evidence, both originals and all twelve input byte bodies survive.
  This cold reader loads graph envelopes, not the complete native component.
- Add a real competing row to the searched donor table and rebuild its registry.
  Observe its actual partition hash and table pin. Dependency invalidation
  makes the lookup and combined graph stale with a propagation witness while
  preserving reuse of the two original graphs. Fresh ambiguous lookup refuses
  a new component. This new case does not claim a filled-empty-partition test.

A normal merge also preserves main's concurrent IPFS staging cleanup at
`9b870a811`. Its four paths are outside the tested inventory and all 506 listed
inputs remain exact. The [preservation receipt](evidence/legal-ir-definition-use-v2-integration-20261015/main_reconciliation.json)
records that separate scope; these suites do not qualify provider operations.

The public transport sequence is explicit:

```python
checked = use.validate_definition_use_candidate_v2(component, request_raw, **inputs)
manifest = exchange.write_graph_bundle(checked["graph"], output_directory)
```

Retain the complete component, both endpoint input/context populations, registry,
lookup, query and original byte commitments separately. The graph-only reader
cannot replay those inputs or retrieve their payloads from a CID automatically.
All semantic-binding, review, training, proof and admission flags remain false.
No native Lean process or model fit was run by this integration.

## Retained inputs and next source component

The author's existing fictional example remains under its original manifest,
producer paths and receipts. The integration inventory binds those exact assets
without relabeling them as a current-checkout replay. Qualification reuses the
existing authored fixture definitions; it does not supply a new statutory use.

The retained real §101 assets contain one document and one opaque-body candidate.
They cannot provide a positive case for this two-document profile. Rewriting
source identities/applicability, splitting its opaque list into inferred classes,
or inventing a norm would add premises. Select an actual source/use component
and review its meaning before choosing needed scope or norm extensions.

The subsequent [combined-use review integration](legal_definition_use_review_v2_integration_20261015.md)
now qualifies the exact alias/joint AST/edge subject, both original candidates
and complete declared tables, contexts and dependencies. Its native A/B jobs
pass 541 distinct cases across sixteen modules, overlapping this earlier
qualification. Actual source/applicability and legal/formal meaning decisions
remain necessary, as does checked correspondence from standalone intake and
exposure evidence to the authenticated subject before evaluation or teacher supervision.
Add same-document scope, normative arguments or per-occurrence lookup through
existing owners only where the selected reviewed component requires them.

Keep separate IR families, schema/version/task checkpoints and parallel
8D/384D/768D lanes, reusing compatible retained assets. Genuine legal/formal
reviews, supported bindings, pinned native builds and admission remain the gates
before this component can become semantic supervision or a proven planner fact.
