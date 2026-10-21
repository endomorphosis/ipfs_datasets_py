# Compact labels beside source-separated decoder examples

`ipfs_datasets_py.logic.autoformal.legal_compact_decoder_example_v1` adds a
compact-label companion to the existing
[source-separated byte example](legal_relational_decoder_target_contract_v1.md).
It keeps that complete example unchanged and projects its validated typed label
through the existing [compact content owner](legal_compact_content_v1.md).
It introduces no AST, renderer, source-join owner, provenance system, eligibility
decision, model or numerical decoding head.

This guide describes a staged contract. Installation and owned qualification
must independently establish behavior for the exact installed generation.
Authored tests, source inspection and successful historical suites do not grant
this new companion runtime qualification.

## Input and label compartments

The sole input compartment is `source_example.model_input`, exactly as supplied
by the original public source-example owner. Its closed fields remain
`source_text` and `context`. The companion does not add a second `model_input`
or copy any compact information into that original compartment.

`source_example` is the complete validated original example, including its old
byte encoding, source identity, physical source group, provenance, unresolved
alternatives, exposure declarations, embedding reference, producer pins, split
and eligibility fields. It is not a reconstructed summary of that example.
An embedding reference remains a declaration; this companion reads no embedding
payload, model weights, dataset row or external cache.

`compact_label` is the complete existing compact projection report. It contains
separate content, signature/role context and an archival identity sidecar. Its
context is **target-derived label information** in this operation. Calling that
field context does not establish permissible inference input or unexposed
information. Any later inference route must separately qualify where its
vocabulary and ordered roles came from. The archival sidecar is for reproduction
of the recorded target, never a prediction aid.

When the original example has no label, `compact_label` is null and compact
projection is not invoked. No fallback target is manufactured. Same-source
alternatives retain their original common group; the companion assigns no
training, tuning or held-out split and selects no governing interpretation.

## Public API

```python
prepare_compact_decoder_example_v1(
    source_example_report, join_report, example_request_raw, *,
    expected_source_example_sha256, expected_example_request_sha256,
    expected_join_report_sha256, join_replay_inputs, codec,
    expected_codec_sha256,
)

compact_decoder_example_sha256(report)

validate_compact_decoder_example_v1(
    report, source_example_report, join_report, example_request_raw, *,
    expected_report_sha256, expected_source_example_sha256,
    expected_example_request_sha256, expected_join_report_sha256,
    join_replay_inputs, codec, expected_codec_sha256,
)
```

The original preparation inputs are the same arguments required by
`legal_relational_decoder_example_v1`; the completed original report and its
independent hash are additional inputs. The companion calls that owner's public
`validate_relational_decoder_example_v1`, which regenerates the full original
source/typed-join/byte-codec chain. A self-consistent altered report cannot replace
the independently committed original inputs.

The report hash helper uses bounded ordinary canonical JSON and imports no
operation owner. It is an identity helper, not schema validation, authentication
or admission. The public validator checks the offered complete report hash,
runs fresh preparation from all original inputs and requires exact report
agreement. Expected commitments must originate from retained caller evidence;
rehashing an altered target does not establish its provenance or permission.

## Closed output

The report contains exactly:

| Field | Meaning |
| --- | --- |
| `schema` | `legal-compact-decoder-example/v1` |
| `profile` | `candidate-source-separated-compact-content/v1` |
| `source_example` | Complete unchanged public-validated original example |
| `source_example_sha256` | Independently expected canonical original-example hash |
| `compact_label` | Complete existing compact projection report, or null |
| `producer_pins` | Combined direct and publicly validated producer hashes |
| `authority` | All flags false |
| `training_mask` | Integer zero |
| `evaluation_gold_mask` | Integer zero |
| `limitations` | Fixed statements of the engineering and authority boundary |

For a labelled example, the projection consumes exactly the original label's
raw UTF-8 request. The companion crosschecks its raw request bytes/hash, complete
canonical request bytes/hash, typed-expression hash, original relational report
hash, original byte-codec identity and archival original commitments. Original
transport formatting and canonical request-value identity remain separate.
Both are retained by their existing owners; no identity normalization is hidden
inside this wrapper.

The compact owner remains responsible for constructor placement, modal scope,
ordered predicate arguments, lexical binder references and exact archival
reconstruction. This wrapper does not widen that owner's syntax. Current
65-character definition-owner predicates and counting/cardinality remain outside
the qualified relational profile. Short-named definition-shaped fixtures do not
establish exact intake from the statutory definition owner.

## Bounds and source custody

Public import and the report hash helper use only the standard library. Before
loading operation owners, preparation detaches bounded ordinary inputs, checks
the complete original-example, join and codec commitments, and checks the
example request's raw bytes and duplicate-free ordinary JSON.

| Complete bound | Limit |
| --- | ---: |
| Aggregate original inputs, including exact byte parameters | 128 MiB |
| Existing complete source-example or join report | 8 MiB each |
| Complete companion report | 16 MiB |
| Relational request | 524,288 bytes |
| Original example request | 16,384 bytes |
| JSON traversal | 2,000,000 items, depth 96 |
| Combined producer map | 256 paths |
| Named producer source | 4 MiB per file |

Whole values refuse on overflow; there is no truncation, implicit cap increase
or best-effort repair. Exact ordinary containers and primitives are required;
cycles, custom subclasses, nonfinite numbers, NULs, invalid Unicode, duplicate
wire keys and out-of-range integers refuse. Byte inputs remain exact bytes in
the original replay arguments. Returned reports contain ordinary JSON only and
are detached before closing fences.

The two direct existing owners are fixed to these raw source generations:

| Owner | SHA256 |
| --- | --- |
| `legal_relational_decoder_example_v1.py` | `4aed1fde35efce9cdd6579be83be6901143003e996611850f6b35f0cce3f705c` |
| `legal_compact_content_v1.py` | `de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e` |

Preparation requires the actual canonical package location, checks its own and
direct-owner bytes/physical witnesses before and after lazy import, and checks
the imported origins. Additional producer paths are read only after their
public owner has successfully validated the output that names them. These paths
must lie in the canonical package, agree on shared hashes and remain stable
through closing fences. Caller originals and detached replay inputs are
fingerprinted before and after operations, including raw byte parameters.

These named source checks are engineering custody checks. They do not prove
executed bytecode for arbitrary preloaded modules, third-party/interpreter
integrity, authenticated producer principals or a hermetic operating system.
Fresh owned qualification with checked-buffer imports supplies its separate
execution observations. Operational exceptions and interruptions propagate;
they are not relabelled rejected model predictions or abstentions.

## Remaining integration

No numerical model runs here. Compact JSON bytes, JSON lexical tokens, byte IDs,
encoder tokens, provider tokens, checkpoint output vocabulary and decode-step
budgets remain different measurements and contracts. This companion implements
no learned compact route, checkpoint migration, training eligibility or savings
claim.

Generated-output intake remains separate work in the existing batch-accounting
owner. It must retain original IDs/bytes, invalid UTF-8, incomplete framing,
missing/duplicate observations and operational failures without shrinking the
selected denominator, repairing a target or using a reference during generation.
This companion creates no new denominator owner. Reviewed meaning, permissible
context, physical/dependency splits, matched learned comparisons, source
equivalence and any convergence theorem still require their own evidence.
