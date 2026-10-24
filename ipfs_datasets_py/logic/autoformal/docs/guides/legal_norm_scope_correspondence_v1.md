# Source-scope to relational norm correspondence

`logic/autoformal/legal_norm_scope_correspondence_v1.py` connects the existing
whole-source scope report and authored relational formula through an unsigned
companion. It checks an explicitly supplied mapping. It does not generate an
interpretation from prose or decide that an interpretation is legally correct.

Both original reports are replayed against their original inputs. The companion
preserves their complete bodies and identity domains; the relational request's
`source_binding` remains null. Source meaning, context closure, governing
definitions, review, graph admission and training eligibility remain separate
requirements. All authority flags remain false and training/gold masks remain
integer zero, including when every proposed link is mechanically consistent.

## Inputs and complete accounting

Use `prepare_norm_scope_correspondence_v1(scope_report, relational_report,
mapping_request_raw, ...)` with these keyword arguments:

- `expected_scope_report_sha256`: the complete canonical scope report hash,
  **not** the scope report's internal `report_sha256` field.
- `expected_relational_report_sha256`: the complete canonical relational report
  hash.
- `expected_mapping_request_sha256`: SHA256 of the exact mapping request bytes.
- `scope_replay_inputs`: the unchanged arguments to
  `prepare_sampled_norm_scope_v1`, including `sampling_report`, original
  `raw_html`, `scope_request_raw`, `scope_declaration_raw`, all original pins,
  exact sealed `selected_unit_ref`, acquisition descriptor and any original
  sampling/view limits. Extra fields are refused.
- `relational_request_raw` and `expected_relational_request_sha256`: the original
  authored typed request bytes and their independent hash.

The mapping request has exactly these fields:

```json
{
  "schema": "legal-norm-scope-correspondence-request/v1",
  "interpretation_status": "authored_unreviewed_correspondence",
  "alternative_id": "caller-assigned-alternative",
  "scope_report_sha256": "<full canonical hash>",
  "relational_report_sha256": "<full canonical hash>",
  "source_rows": [],
  "typed_rows": []
}
```

The empty lists above describe the schema, not a valid request. Each population
must be nonempty and complete:

| Row | Required fields and checks |
| --- | --- |
| Source | `anchor_mapping` is an exact original `anchor_mappings` row in original order. `disposition`, `targets`, and a bounded nonempty `rationale` account for it. |
| Typed | `target` is an exact original `structural_mapping` row in original order. `disposition`, `source_paths`, and a bounded nonempty `rationale` account for it. |

Source `proposed_mapping` rows have one or more distinct exact typed targets.
`unresolved` and `unsupported` rows have none. Coverage anchors must have the
`literal_accounting` disposition and no targets. Other anchors cannot use that
disposition. An unresolved issue may be associated with proposed syntax, but its
original issue record remains unresolved in the output.

Typed `source_linked` rows list the exact inverse source paths, in source order.
Nodes without a source link use `authored_scaffolding` with an empty list.
Quantifier binders and modal extension records are included independently of
their wrapper nodes. Mapping keys are typed paths: a modal wrapper and extension
share a native path, and binder records do not have a node ID.

Declared modality occurrences can nominate only the exact O/P/F extension with
the same declared letter. Participant occurrences can nominate variables or
binders; action occurrences can nominate predicates. Other lexical facets remain
unsupported on this mapping profile. These are consistency checks between
authored declarations. They do not establish that a source word actually has
that modality or that a grammatical subject is the action's agent.

## Derived syntax and alternatives

`typed_context_inventory` derives each target's ordered connective, quantifier
and modal ancestry from the replayed typed expression. For every variable use it
also records the exact governing binder and predicate argument position and
declared role. No new AST or logic semantics is introduced. O/P/F remain the
independent parameters of the existing relational route.

Different argument orders, implication directions or modal scopes stay distinct
authored alternatives. The owner neither repairs an alternative into a presumed
correct interpretation nor selects between alternatives. Its `source_bound`
flag remains false: exact source custody and a proposed correspondence are not
an independently validated source translation.

The existing fragment still lacks equality/cardinality, extra semantic sorts,
purpose and anaphora. Opaque predicate labels do not implement those constructs.
The retained statutory examples have open context and meanings; an authored
fictional example is not their completed interpretation.

## Replay and execution limits

`norm_scope_correspondence_sha256(report)` hashes the complete canonical output.
`validate_norm_scope_correspondence_v1(report, ..., expected_report_sha256=...)`
requires all the original preparation inputs and exact complete regeneration.
Changing a result and repairing its outer hash does not bypass this check.

Preflight enforces exact input hashes, ordinary finite JSON, duplicate-free raw
requests, closed fields, nesting/population and incremental byte bounds. It
detaches caller-owned structures before replay. The two existing public modules'
pure parsers run before their operation dependencies load. Input and producer
checks bracket both replays and final serialization. The owner permits at most
4 MiB mapping JSON, 24 MiB output and 64 MiB aggregate input; underlying owners'
smaller bounds still apply. Limits refuse oversized material without truncation.

The private JSON encoder has a direct scalar path that checks the same exact
types, UTF8 validity, finite-number restrictions and byte limits as the compound
encoder. It avoids a second serialization of scalars; compound traversal and
canonical output formatting remain unchanged. Snapshot callers can retain those
validated immutable values without decoding them again.

The source and relational owners' original signatures, if held elsewhere, do
not cover this companion. A new meaning-review subject and its independently
admitted signer would be needed before promotion. This owner constructs neither.
Existing native parsing and Lean **text generation** occur during relational
replay; no Lean build, solver, model, training or publication is executed.

The [qualification report](../../../../../docs/autoencoders/legal_ir_source_relational_correspondence_20261015.md)
records the captured execution profile and results separately from this API.


## Explicit parent-occurrence correspondence v2

`prepare_norm_scope_correspondence_v2` and
`validate_norm_scope_correspondence_v2` add an explicit route for the
[parent literal-occurrence scope profile](legal_source_norm_scope_v1.md#original-parent-literal-occurrence-profile).
The sampled-HTML v1 API and its original request/report schemas keep their
existing behavior. This route reuses the same authored relational owner,
complete source/typed accounting, inverse links and typed context inventory.
It introduces no additional logic AST or interpretation selector.

The v2 preparation signature has the same argument names as v1. Its
`scope_report` must have schema `legal-parent-norm-scope-proposal/v1` and profile
`whole-selected-parent-literal-occurrence-unreviewed-lexical-scope/v1`.
`scope_replay_inputs` is the exact closed original argument mapping for
`prepare_parent_norm_scope_v1`:

- `parent_bundle`, `scope_request_raw` and `scope_declaration_raw`;
- `expected_manifest_cid`, `source_occurrence_cid` and `companion_record_cid`;
- `report_bytes`, `expected_report_pins` and `replay_inputs`;
- `expected_scope_request_sha256` and `expected_scope_declaration_sha256`;
- optional lower-only parent `limits`.

The three original report byte populations, independent raw/canonical pins,
physical replay inputs, bundle and selected identities remain required in full.
Do not pass HTML sampling inputs, a previously supplied parent binding, or only
the lexical source string. The retained parent source binding preserves
physical source and occurrence custody; the authored relational request still
has `source_binding: null`.

The mapping request retains the exact seven fields and accounting rules above,
with `schema` set to `legal-norm-scope-correspondence-request/v2`.
`interpretation_status` remains `authored_unreviewed_correspondence`.
The output schema is `legal-norm-scope-correspondence-report/v2`, with profile
`parent-literal-occurrence-authored-correspondence/v2`. Source rows retain exact
original `parent_selector` anchor mappings; their absolute source-field
character/UTF8 offsets and occurrence CIDs are not converted to HTML selectors
or replaced by spelling matches. All ordered source rows and typed targets,
including coverage anchors, unresolved records, modal extensions and binders,
still require complete accounting.

The independent scope and relational report pins are full canonical hashes.
The scope report's internal `report_sha256` field is a different payload seal.
Mapping and relational requests remain independently pinned original raw bytes.
`norm_scope_correspondence_sha256` hashes the complete v2 report using the
existing helper. `validate_norm_scope_correspondence_v2(report, ...,
expected_report_sha256=...)` requires all original preparation inputs and exact
full regeneration. A v1 request/report cannot stand in for the explicit v2
profile, even when outer hashes are recomputed.

The parent scope validator and original relational validator both run at
opening and closing. Each parent preparation replays the genuine original
parent binding twice. Preparation checks original and detached inputs, parsed
mapping, returned validations, selected trusted source pins and final output.
Closing checks run on failure, preserving a primary error and recording any
secondary custody failures. This route maintains separate parent producer-pin
state and does not load HTML sampling dependencies for parent scope replay.

The existing 4 MiB mapping-request, 24 MiB output and 64 MiB aggregate-input
bounds still apply. The relational request is bounded to 512 KiB and its report
to 8 MiB. Parent scope's 1 MiB report and smaller underlying original replay
bounds apply as well. Input and output content is ordinary finite bounded JSON;
unknown fields, nonmatching independent pins and oversized content are refused
without truncation.

This profile covers the whole selected literal occurrence, which may be a
fragment or unclassified region. It does not establish a complete paragraph,
whole law, governing body or legal translation. Edition remains undeclared,
all six original context requirements remain open, and unresolved meaning and
partial coverage are retained. `source_bound` stays false, all authority flags
stay false, and training/gold masks stay integer zero. Mechanically consistent
links do not supply meaning review, governing definition use, admission or a
training target. Existing relational parsing and Lean text generation remain
separate from any Lean build; no model, training, solver or Lean process runs.

The [saved qualification summary](../../../../../docs/autoformalization/evidence/legal-ir-parent-norm-scope-correspondence-20261024.json)
accepts the combined two-module cohort: 185 cases and 555 passing phases,
including 149 existing compatibility cases and 36 parent-profile cases. Both
guides refer to this same cohort. The exact qualification profile is
`parent-norm-scope-public-port-pure-controls/v2`, with namespace profile
`parent-norm-scope-scoped-unit-namespaces/v2`.

This is qualification of source custody, geometry, declared syntax and refusal
behavior. The two processor package initializers are pinned and explicitly
bypassed alongside the existing namespace bypasses; the required genuine
`uscode_release_schema.py` leaf was observed executing. Full package startup,
bypassed initializer execution and third-party cached bytecode are outside the
qualification. Original native, source READ and storage cleanup completed.
The two earlier failed attempts remain failed, with separate storage closeouts;
they are not added to the successful cohort or counted as laws.

No legal-fidelity or learned accuracy gain is claimed. Meaning review, governing
edition/context decisions, complete law semantics, training targets and gold
admission remain unavailable; all authority flags and masks described above
retain their false/zero values.
