# Typed theorem lineage for retained V2 corpus packets

The [theorem-lineage owner](../../legal_corpus_definition_use_preservation_theorem_lineage_v2.py)
declares fifteen engineering claim candidates from a fully replayed
[retained corpus packet](legal_corpus_definition_use_preservation_packet_v2.md).
Each candidate binds an exact Lean declaration header, explicit hypotheses,
source ranges, original interpretation and declared import/artifact closure.
It uses the existing `IRClaim`, `Assumption` and `ProofObligation` types.

The statements have kind `lean_declaration_header`: they retain the literal
`theorem` command, name and all binders. They are opaque source identities.
They are not elaborated kernel types, executable backend requests, legal
`FormalizationArtifact` objects or new `ProofReceipt` objects. Their domain is
`engineering_corpus_preservation`; result and proof authority remain unchanged.

## Prepare and validate a complete lineage

`prepare_definition_use_preservation_theorem_lineage_v2` takes the original
immutable 49-file packet, typed original corpus preparation, assessment and all
eight original packet-reader arguments. An independently trusted SHA256 of the
exact packet-observation bytes is also required. It calls the existing public
packet reader to replay current source/review/preparation compatibility.

The frozen `RetainedCorpusTheoremLineage` contains `lineage_json` and a tuple of
fifteen genuine typed claims. `.to_dict()` exposes the sealed common context,
ordered `entries`, serialized `claims`, original review state and explicit
future native handoff requirements. `lineage_sha256` addresses its exact bytes
and consistent typed storage; computing a hash does not validate provenance.

`validate_definition_use_preservation_theorem_lineage_v2` additionally takes the
lineage object and independently expected complete lineage SHA256. It checks
bounded storage and commitments, regenerates the whole lineage through current
owners, then compares all bytes and typed claim storage. A caller-constructed
dataclass or a resealed mutation cannot replace that regeneration.

The operation binds the original argument tree before replay and checks it
afterward and at return, together with the full original corpus preparation,
packet identity and all producer files. Type-sensitive canonical comparisons
distinguish `False` from `0` and integer values from floating point values.
Preflight checks genuine registered claim classes before reading slots, so a
counterfeit class with a matching name cannot execute a property getter.
The complete record is bounded to 8 MiB; unsupported or incomplete input refuses.

## Theorem-specific hypotheses

The existing manifest groups three declarations as `conditional_theorems`.
The lineage preserves that partition while retaining each declaration's actual
binders:

| Declaration | Explicit proposition hypotheses | Universal parameters |
| --- | --- | --- |
| `consumer_predicate_iff_donor_body` | `hDonor`, `hAlias` | Entity/Agent carriers, interpretation, time and entity |
| `joint_of_components` | `hDonor`, `hConsumer`, `hAlias` | Entity/Agent carriers, interpretation and time |
| `joint_matches_original` | None | Entity/Agent carriers, interpretation and time |
| Four roles' `native_value_exact` | None | None |
| Four roles' `native_ast_closed` | None | None |
| Four roles' `denotation_matches_native` | None | Entity/Agent carriers, interpretation and time |

Each family therefore retains five explicit proposition-premise occurrences
across two theorems. The fifteen empty historical axiom inventories do not
establish those premises. Universal parameters are not assumed or proved facts.
Each claim has one obligation whose ordered assumption IDs match that theorem's
premise objects, including exact binder text, byte range and qualified target.

The three existing conditional names and twelve preservation names remain
unchanged. The underlying native family is recorded separately as `native_family`;
the opaque header's representation family is `lean4`. Identical source labels
or theorem suffixes do not merge different roles, families or packet contexts.

## Exact declaration and artifact bindings

The owner recognizes the closed recipes already emitted by the current qualified
corpus and preservation owners. It requires one uniquely anchored complete block
containing the exact header, ` := by` separator, proof body and `#print axioms`
command inside its original namespace. It does not parse arbitrary Lean or emit
a replacement proof. Unsupported templates, changed statements or extra anchors
refuse.

Every range records raw UTF8, start/end byte offsets, byte count and SHA256.
Offsets count bytes, including Unicode operators, rather than Python characters.
The ranges refer to generated Lean modules; they are not statute source maps.

Each entry retains:

- Fully qualified theorem/module/namespace identity, role and exact original formula target.
- Original fragment, AST, formula, emitter-body and preservation bindings.
- Ordered declared transitive imports, with source, executed-source and retained `.olean` path/length/hash for every module in the closure.
- The actual shared `LegalCorpusV2.Interpretation`, original Prelude, preservation semantics and compiled-artifact references.
- Common full packet/preparation/assessment/argument commitments, toolchain and binary identities, producer pins and unchanged review/dependency state.
- Typed claim and obligation digests, explicit premise IDs and the separate historical axiom inventory.

The closure is a conservative **declared import closure**. It is not an inventory
of elaborated Lean term dependencies. Referencing a retained `.olean` neither
rechecks it in a kernel nor authorizes executable reuse.

Actual Prelude and namespaced semantics file hashes remain distinct from the
standalone body/template hashes carried by native fragments. Original explanatory
`theorem_assumptions` text is retained verbatim, including preparation-era status
wording; it is context, not a new execution result.

## Receipt issuance remains a separate boundary

The output keeps all fresh compilation, execution, proof, cache, source/review,
model and training authority false, with zero training and evaluation masks.
The earlier native receipt remains historical evidence. This operation writes
no index and leaves the previously qualified observational database untouched.

A later native adapter must first qualify elaboration of each exact
namespace-bound header into the intended kernel proposition. It must then bind
the claim, declaration, obligation and assumptions to a genuine bounded
`BackendRequest`, successful `BackendAttempt`, affirmative `ProofResult`, exact
output, compiler/environment and imported dependencies before calling the
existing `ProofReceipt.issue` API. Merely constructing matching typed objects
does not authenticate execution.

Legal proof-cache eligibility additionally requires a real legal-domain
formalization artifact and exact receipt-to-artifact obligation binding.
Declaration-name matching alone is insufficient. Reviewed statutory source
correspondence, compiler artifact reuse, general preservation, token savings
and model convergence retain their separate acceptance gates.

The separate [native elaboration profile](legal_corpus_definition_use_preservation_elaboration_v2.md)
now qualifies exact original/header-alias kernel-type checks for this supported
engineering profile. It preserves these opaque claims unchanged and issues no
typed theorem receipt.

## Qualification on October 16, 2026

The [qualification receipt](../../../../../../../artifacts/legal-ir-corpus-theorem-lineage-20261015-01/qualification-receipt.json)
records **61 passing tests**, with no failures, errors or skips: 45 new lineage
cases and 16 existing claim/proof-protocol regressions. Historical packets in
unit fixtures and proof receipts in the protocol regressions are synthetic.

Separate owned replay consumed both actual retained authored FOL/TDFOL packets
and produced 30 typed claims and obligations, with ten explicit premise
occurrences across four theorems. Three resealed or mismatched candidates
refused. The [independent readback](../../../../../../../artifacts/legal-ir-corpus-theorem-lineage-20261015-01/independent-theorem-lineage-readback.json)
reconstructed all 30 namespace-bound blocks, 150 source ranges, declared import
closures and typed digests across 131 exports. All 123 prior exports, 98 original
packet files, nine existing qualified owners and the closed observational
database remain unchanged.

The initial independent check refused two stale expected diagnostic strings;
only those expectations were corrected, and the initial reader and refusal
remain retained. Production and actual replay outputs did not change. No new
Lean invocations, compiler probes, backend requests, proof receipts or cache
writes occurred. Both selected resource reservations were durably released.
