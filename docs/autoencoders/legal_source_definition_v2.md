# V2 source definitions as corpus candidates

`logic/autoformal/legal_source_definition_bridge_v2.py` accepts explicit,
unreviewed unary definition declarations against the complete official V2
markup view. `corpus_definition_adapter_v2.py` transports a regenerated report
into source-bound corpus records and a definition-only candidate graph.

This path uses the existing V2 source sampler and source-record owners. It
shares bounded Boolean lowering with the legacy definition compiler. The
legacy request/profile and its document validation remain available; a V2
document is never relabeled as a legacy paragraph population.

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
remain false. Actual legal/formal reviews require a compatible versioned V2
review subject; the old definition-plus-norm domain and blank review packets are
not compatible submissions. A real definition-use binding, complete supported
norm, scoped lookup evidence, native build and downstream admission remain
separate work.
