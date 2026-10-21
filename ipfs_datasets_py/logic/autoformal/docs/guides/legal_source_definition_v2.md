# Source definitions as corpus candidates

`logic/autoformal/legal_source_definition_bridge_v2.py` accepts explicit,
unreviewed unary definition declarations against the complete official V2
markup view. `corpus_definition_adapter_v2.py` transports a regenerated report
into source-bound corpus records and a definition-only candidate graph.
These same owners also expose a separate literal-parent profile for plaintext
cache fields, described below. Both routes reuse the existing Boolean lowering.

This path uses the existing V2 source sampler and source-record owners. Its
bounded Boolean lowering preserves the legacy definition compiler's unary
Boolean semantics. The active repository retains the legacy compiler's source
unchanged, including its original producer pins. A V2 document is never
relabeled as a legacy paragraph population.

## Independent inputs

First retain a complete `legal_source_sampling.prepare_source_sampling` report,
its original HTML, acquisition descriptor and independently expected hashes.
The sampler report must remain separately available, including every source
block and context record. Pass its **full canonical** hash from
`source_sampling_report_sha256`, including the internal payload digest.

```python
from ipfs_datasets_py.logic.autoformal import legal_source_definition_bridge_v2 as bridge
from ipfs_datasets_py.logic.autoformal import corpus_definition_adapter_v2 as corpus

trusted = dict(
    sampling_report=complete_sampling_report,
    expected_sampling_report_sha256=independent_full_sampling_hash,
    raw_html=original_html,
    descriptor=original_descriptor,
    expected_descriptor_sha256=independent_descriptor_hash,
    expected_raw_sha256=independent_html_hash,
    expected_raw_bytes=independent_html_length,
)
report = bridge.prepare_definition_v2(explicit_request, **trusted)
bridge.validate_definition_v2(report, explicit_request, **trusted)

# Retain the exact original request/report JSON bytes and their transport hashes.
candidate = corpus.adapt_definition_only_bytes_v2(
    original_report_json,
    expected_report_sha256=independent_report_file_hash,
    request_raw=original_request_json,
    expected_request_sha256=independent_request_file_hash,
    **trusted,
)
corpus.validate_definition_only_candidate_v2(
    candidate, original_report_json,
    expected_report_sha256=independent_report_file_hash,
    request_raw=original_request_json,
    expected_request_sha256=independent_request_file_hash,
    **trusted,
)
```

Expected commitments originate outside the incoming records. Raw JSON file
hashes, full canonical report hashes, internal payload hashes and record CIDs
have separate meanings. The corpus adapter hash-checks its bounded original
request/report bytes before importing the native owner. The bridge replays the
complete source sampler against original HTML and descriptor inputs. No network,
model, reviewer, registry or clock is selected implicitly.

## Explicit declaration

The request has exactly `schema=bridge.REQUEST_SCHEMA`,
`profile=bridge.PROFILE`, `family` (`fol` or `tdfol`) and `declaration`.
The declaration has these fields:

| Field | Meaning |
| --- | --- |
| `declaration_id` | Caller-supplied interpretation identity |
| `interpretation_status` | Exactly `unreviewed_caller_declaration` |
| `source_version_ref`, `normalized_view_id` | Exact sampler source/version and V2 view identities |
| `contributor_unit_refs` | Nonempty unique original candidate-paragraph unit refs in source order |
| `scope_unit_ref`, `scope_span` | Exact original source unit and literal introducing the declared scope |
| `head`, `definition_cue` | Exact head and `means` spans within the first contributor |
| `body` | Caller-declared `atom`, `not`, `all` or `any` expression |
| `applicability` | Separate explicit scope/jurisdiction/instrument/date/source declarations |

Full unit/version refs contain `record_cid`, `schema` and the full canonical
record `sha256`. Source spans contain exactly `char_start`, `char_end` and
`text`, addressing the normalized Unicode view. Body atoms must follow the cue
and remain within the selected contributors. An atom crossing a line separator
retains that exact interval and every intersected contributor; the bridge does
not concatenate fragments. Source contributor order and Boolean operand order
remain distinct.

Applicability contains exactly `scope_kind` (`title` or `section`), `scope_id`,
`jurisdiction_id`, `instrument_id`, `legal_as_of_civil_date` (canonical ISO date
or explicit unknown `null`), `source_edition` and `source_release_id`. Edition
and release must match the original sampler source version. The exact scope
literal is case-insensitively `In this title` or `In this section`, with an
optional colon, matching the declared kind. It must precede the head. This
checks an explicit declaration; it does not establish governing applicability,
attachment, title hierarchy or the truth of a source-role decision.

The native formula is `forall x, head(x) iff body(x)` over one Entity carrier.
Symbols bind the actual source version/view, profile, declaration, scope evidence
and applicability. Inclusion, exclusion, aliases, equality, extra sorts, arbitrary
arity and implicit external definitions are outside this profile. The bridge
does not infer Boolean connectives from legal text or assert complete definition
coverage. Unsupported declarations refuse rather than silently weakening them.

## Occurrences, contexts and graph

Whole contributor and scope-block refs preserve exact membership in the sampler
population. New head, cue, scope-literal and body-atom subspan occurrences derive
through the existing `corpus_source` owner against the same source version and
view. They do not change the original sampler population. Every unique physical
origin has a context declaration with all six requirements still open. Ordered
role bindings retain intersecting block indices, context refs and symbols.
Shared geometry may have multiple roles; equal text at different offsets retains
different physical occurrences.

The corpus companion retains request custody, external report custody, source
version/occurrences/contexts, ordered roles, declared scope/applicability, symbols,
definition AST, head term sense, input binding, issues and graph. The graph uses
the existing node/edge vocabulary and emits `DEFINES` with closed node-record-CID
endpoints. It supplies no norm record, ground entity or `USES_DEFINITION` edge.
The full AST stays in the companion; graph edges do not replace it.

`export_definition_only_candidate_v2(candidate, output_directory, **inputs)`
validates the same original inputs, including `report_raw`, before delegating to
the existing graph exchange. That export contains graph envelopes. Retain the
complete companion and independently pinned original inputs separately: a CID
does not retrieve their payloads automatically.

## Bounds and remaining qualification

Each request/report and the complete sealed corpus companion obeys the one-MiB
record bound. Complete source transport has separate finite budgets (32 MiB
sampling report, 48 MiB aggregate bridge inputs). The bridge allows at most 256
physical origins, 512 role bindings and 256 contributors; Boolean depth/node/
operand and literal bounds also apply. Optional limits only lower defaults.
Overflow refuses the entire result without truncating source, contexts or ASTs.
The full §101 sampling report is about 2.79 MB, so it remains external evidence.

Native parsing/AST roundtrip and generated Lean source qualify the caller's
bounded encoding. Authority, source meaning/applicability, context closure,
independent review, training gold, semantic admission and Lean execution flags
remain false. Compatible context/evidence/subject APIs are available in the
[V2 definition review adapter](corpus_definition_review_v2.md). Actual legal/formal
reviews must use that signing domain; the old definition-plus-norm domain and
blank review packets are not compatible submissions. A real definition-use
binding, complete supported norm, scoped lookup evidence, native build and downstream admission remain
separate work.

## Plaintext parent definitions

`prepare_parent_definition_v1` accepts the complete literal field already
retained by the [parent occurrence adapter](corpus_parent_occurrence_adapter.md)
and the plaintext source binding in `legal_semantic_graph`. This route does not
invoke the HTML extractor. Source custody includes the original file and its
physical row, original report bytes, occurrence and companion CIDs, and an
independently expected manifest. The complete parent population is replayed
before a declaration is encoded.

```python
# Use the exact inputs already accepted by bind_parent_source_occurrence.
parent_inputs = dict(
    parent_bundle=original_parent_bundle,
    expected_manifest_cid=independent_parent_manifest_cid,
    source_occurrence_cid=whole_field_occurrence_cid,
    companion_record_cid=original_companion_cid,
    report_bytes=original_parent_report_bytes,
    expected_report_pins=independent_parent_report_pins,
    replay_inputs=original_parent_replay_inputs,
)
report = bridge.prepare_parent_definition_v1(parent_request, **parent_inputs)
bridge.validate_parent_definition_v1(report, parent_request, **parent_inputs)

candidate = corpus.adapt_parent_definition_only_bytes_v1(
    original_report_json,
    expected_report_sha256=independent_report_file_hash,
    request_raw=original_request_json,
    expected_request_sha256=independent_request_file_hash,
    **parent_inputs,
)
```

The request has exactly `schema=bridge.PARENT_REQUEST_SCHEMA`,
`profile=bridge.PARENT_PROFILE`, `family` (`fol` or `tdfol`) and `declaration`.
The declaration contains these exact fields:

| Field | Meaning |
| --- | --- |
| `declaration_id`, `interpretation_status` | Explicit identity and exactly `unreviewed_caller_declaration` |
| `source_binding_sha256` | Commitment to the complete independently replayed parent source binding |
| `scope` | Exact `legal_semantic_graph.bind_parent_scope` declaration for that binding |
| `scope_kind`, `scope_span` | `title` or `section` and its exact preceding `In this title/section` literal, optionally followed by a colon |
| `contributor_spans` | Ordered, nonoverlapping caller-declared character ranges; these are not verified statutory units |
| `head`, `definition_cue` | Exact source spans in the first contributor, with the literal cue `means` |
| `body` | Explicit ordered `atom`, `not`, `all` or `any` expression using exact spans |

Each span contains `char_start`, `char_end` and `text` against the original
literal field. UTF-8 coordinates derive through `corpus_source`; Unicode text
and line separators remain intact. Body atoms must follow the cue and lie in
the union of declared contributors. Adjacent contributors may cover a multiline
atom; an uncovered gap refuses. Sentence splitting supplies no statutory
structure. The root occurrence must cover the entire field and match both its
SHA-256 and CID; a fragment or same-length replacement cannot stand in for it.

The encoding is the same explicit universal biconditional as the official V2
route. Physical row identity participates in the symbol namespace, so equal
text from different parent rows does not merge definitions. Repeated literals
within one declaration retain their distinct source occurrences and roles.
No model supplies the declarations or Boolean structure in this profile.

The parent report, candidate and nested records have separate schema domains.
They retain the complete parent binding, whole-field and derived occurrences,
unavailable-context declarations, ordered roles, declaration, AST and producer
pins. Unknown edition remains unknown. There are no fabricated normalized HTML
view IDs or statutory unit refs. Contributor completeness, lexical coverage,
source-region roles and governing scope remain unverified.

The candidate graph has custody and `DEFINES` edges. Its scope record names an
unreviewed declaration; the graph omits `APPLIES_WITHIN` and `USES_DEFINITION`.
All existing authority flags stay false. The official V2 review adapter does
not accept this parent schema. Qualified review, context closure, actual norm
use, Lean execution and admission still require their own supported evidence.

`validate_parent_definition_only_candidate_v1` regenerates the entire candidate
from the original inputs. `export_parent_definition_only_candidate_v1` takes
the same validation inputs, including `report_raw`, before exporting through the
existing graph exchange. Retain the complete companion and original inputs
alongside that export. Hashes and graph envelopes do not replace their payloads.

`parent_limits` lowers the existing parent evidence budgets. `limits` lowers
`bridge.PARENT_DEFAULT_LIMITS`: the compact request/report and complete corpus
companion retain the one-MiB bound, with up to 256 origins, 512 role bindings
and 256 contributors. Every declared span, including a contributor, is bounded
by `max_literal_bytes` (4096 bytes by default). Boolean bounds and the shared
JSON depth/item bounds also apply; fitting one bound does not waive another.
Excess size or depth refuses without truncation.

The regression fixtures are authored plaintext interpretations. Their finite
Boolean oracle tests the encoding; graph export/reload and physical replay test
custody. They are not measurements of statutory extraction accuracy, trained
8D/384D/768D/4096D performance, qualified legal review or a native Lean build.
