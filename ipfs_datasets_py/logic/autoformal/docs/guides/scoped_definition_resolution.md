# Declared definition lookup and dependency evidence

`logic.autoformal.scoped_definition_resolution` wraps the existing
`logic.integration.reasoning.legal_ir_symbols` resolver. It records complete
caller-supplied symbol tables and exact query routes, then delegates local scope
shadowing, explicit cross-document lookup and alias handling to that owner.
It generates candidate lookup records and dependency manifests. Public import
initializes no resolver, optional numerical runtime, compiler or session.

## Inputs and scope

`build_definition_lookup_registry(partition_inputs, expected_population)` binds
an exact ordered partition inventory. Each partition input has:

- `partition_id`, `release_id`, integer `edition` and `document_id`;
- separately declared `source_version_cid`, `scope_cid` and `applicability_cid`;
- `table_raw`, the complete original UTF8 JSON bytes of an existing-owner
  `LegalIRSymbolTable.to_dict()` record, or `None` for unavailable content.

The independently retained population supplies ordered `{partition_id,
table_sha256}` pins. Every available table is hash-checked before parsing or
owner loading, round-trips exactly through the owner and retains its original
wire bytes. A known empty table has real bytes/hash and declared local scopes.
Unavailable tables have null byte/hash/CID fields and may have an unknown
`source_version_cid=None`. They cannot be treated as evidence of absence.

The profile refuses duplicate partition identities, conflicting or duplicate
global definition/alias identities, undeclared local scopes, missing/cyclic
parent chains, inconsistent document identities and noncanonical owner records.
Inputs are bounded to 32 partitions, 128 scopes and 256 items per table category,
with a complete aggregate one-MiB JSON envelope. Unsupported populations refuse
as a whole; no candidates are truncated to fit.

Metadata CIDs are declared references. This wrapper does not fetch their content,
authenticate official sources, establish governing applicability, verify physical
source selectors or review legal meaning. A caller that has source/interpretation
records retains and validates them through their respective owners separately.

## Queries and outcomes

`resolve_definition_lookup(registry, query_raw, expected_query_sha256)` checks
the independently pinned exact query bytes. Its closed fields are `reference`
(the existing owner's complete `LegalIRSymbolReference.to_dict()`), ordered
`partition_ids`, `source_occurrence_cid` and `interpretation_cid`. The first
partition is local; the rest are explicit external candidate tables. All
requested partitions must share the declared release, edition and applicability
reference. Query document/scope and explicit external target must belong to that
declared route.

The exact Unicode literal remains in the query. The existing matching policy
extracts lower-case ASCII alphanumeric words; its versioned policy label is
recorded explicitly. A normalized spelling match does not establish semantic
identity. Role kinds are those supported by the symbol owner; arity, legal
sorts, time and statutory priority are not inferred by this profile.

The recorded owner result is recomputed, preserving candidate symbol/alias IDs,
scope path and diagnostics. Outcomes are `resolved`, `unresolved`, `ambiguous`
or `unavailable`. Only an all-available uniquely resolved result has a
`selected_symbol_id`. A resolved owner result that contradicts an explicit
requested kind, target document or target scope refuses; the wrapper does not
choose an alternative. Ambiguous candidates remain unselected. Any requested
unavailable table prevents selection, even when an available table contains a
tentative match.

`validate_definition_lookup_registry` and `validate_definition_lookup` replay
complete bytes and policy/owner pins. Retain independent registry/lookup CIDs and
query hashes when transporting records. A seal or a self-supplied hash alone
does not authenticate the original population.

## Incremental dependencies

`build_definition_lookup_dependencies(registry, lookups, expected_lookup_cids)`
replays the complete independently pinned lookup population and delegates to
the existing `legal_graph_dependencies` manifest owner. Lookup artifacts depend
on every complete table in their explicit query route, including empty tables.
Stable partition IDs bind the complete original table and declared namespace;
policy/implementation pins are carried alongside them. Unavailable table pins
are null, so the existing reverse invalidation owner prevents reuse.

The dependency coverage is conservative complete supplied tables, rather than
an exact trace of which rows/scopes the resolver visited. A new competing
definition changes a depended-on partition even when the old selected definition
bytes remain unchanged. Filling a verified empty or unavailable partition also
reopens its lookups and reverse-reachable graph/module/proof artifacts. Changing
an unsearched partition preserves an unrelated lookup's content identity.

Each query's ordered route is independently pinned. Adding an outside partition
does not silently add it to an earlier route: the source/applicability/review
owner must supply a changed query when its governing candidate inventory changes.
The registry is validated in full, while each lookup identity binds its requested
route and partition contents. This is completeness of the declared inventory,
with `exhaustive_search_verified=false` and governing/context closure still open.

These records create no semantic `USES_DEFINITION` edge automatically and supply
no reviewed training target, native Lean declaration or proof. Source meaning,
authenticity, context closure, review, admission, formalization, model execution,
Lean compilation and proof authority remain false. Attach separately governed
review evidence through an explicit compatible subject profile; existing canonical
graph-review profiles cannot be substituted for a native quantified-definition AST.


## Literal-parent candidate profile

The additive parent APIs use distinct registry, partition and lookup schemas:

```python
build_parent_definition_lookup_registry_v1(partition_inputs, expected_population)
validate_parent_definition_lookup_registry_v1(registry, expected_registry_cid=None)
resolve_parent_definition_lookup_v1(registry, query_raw, expected_query_sha256)
validate_parent_definition_lookup_v1(lookup, registry, query_raw=None,
                                    expected_query_sha256=None)
build_parent_definition_lookup_dependencies_v1(registry, lookups,
                                              expected_lookup_cids)
```

Each parent partition has exactly `partition_id`, `release_id`, `edition`,
`document_id`, `source_version_cid`, `scope_cid`, `preparation_cid`,
`parent_manifest_cid`, `root_source_occurrence_cid`, `companion_record_cid`,
`source_binding_sha256` and `table_raw`. The ordered population remains
`{partition_id, table_sha256}`. `edition` must be the literal
`not_declared_in_source_artifact`. There is no `applicability_cid` field and no
conversion into an official year or HTML source profile. All source references
remain required for an unavailable table; this profile represents known parent
references whose symbol table is unavailable, not an unknown parent identity.

Copy these references from the separately prepared literal-parent evidence:
`source_version` supplies document/release/edition/version identity; `scope_id`
supplies the scope reference; the preparation's `record_cid` supplies
`preparation_cid`; and `parent_input_binding` supplies manifest, root occurrence,
companion and source-binding references. These are declared commitments at this
layer. The lookup wrapper neither replays parent source bytes nor authenticates
the preparation. A consumer must independently replay the parent review owner
and match every reference before binding the lookup to actual source evidence.

Parent queries keep the same exact four fields described above. They delegate
to the same existing symbol resolver and retain its exact result. Explicit
candidate routes may cross different Parquet release references. Equal unknown
edition markers do not establish equal governing editions, applicable scopes,
current law, or permission to use a definition. `resolved` means one lexical
candidate under the supplied route. `applicability_verified`,
`governing_edition_verified`, `parent_source_replay_verified` and all existing
review/admission flags remain false. The official-profile APIs reject parent
records, and the parent APIs reject official records.

The original 32-partition, 128-scope, 256-table-item and aggregate table-byte
bounds still apply. Known empty, unavailable and ambiguous populations remain
separate. An unavailable partition in the requested route prevents selection.
Parent dependency artifact and pin names use the `parent-` prefix. The complete
sealed partition, including every provenance reference, is its dependency
identity: changing metadata invalidates its dependent lookups even when table
bytes are unchanged. Unsearched partitions do not alter an unrelated lookup.
No semantic graph edge, combined-use review, training target or native Lean
proof is generated by this lookup profile.
