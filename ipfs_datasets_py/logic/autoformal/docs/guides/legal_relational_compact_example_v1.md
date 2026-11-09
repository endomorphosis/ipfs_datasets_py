# Source-separated compact label companion

`legal_relational_compact_example_v1.py` adds a compact label beside the complete
existing [relational decoder example](legal_relational_decoder_target_contract_v1.md).
It retains the original byte label, request identities, provenance, physical
source group, exposure and embedding declarations unchanged. Its new schema is
`legal-relational-compact-example/v1`; its profile is
`candidate-source-separated-relational-compact-companion/v1`.

The companion first calls the original example's public replay validator with
all original source/join/example inputs. That validator regenerates the complete
original example. If its original label exists, the companion passes the
retained relational request through the
[compact codec](legal_relational_compact_codec_v1.md) and its public replay
validator. The resulting original/canonical request identities, full canonical
request text, relational report hash, typed-codec hash and original byte-codec
identity must agree with the preserved byte label. It changes no AST, lowerer,
example policy, source parser, checkpoint or model.

```python
prepare_relational_compact_example_v1(
    original_example_report, *, expected_original_example_sha256,
    original_replay_inputs, compact_codec, expected_compact_codec_sha256
)
relational_compact_example_sha256(report)
validate_relational_compact_example_v1(
    report, *args, expected_report_sha256, **kwargs
)
```

`original_replay_inputs` is a closed dictionary containing the exact public
arguments of `prepare_relational_decoder_example_v1`: `join_report`,
`example_request_raw`, `expected_example_request_sha256`,
`expected_join_report_sha256`, `join_replay_inputs`, `codec` and
`expected_codec_sha256`. The nested replay dictionaries retain their original
interfaces, raw bytes and independent commitments. No new example request,
admission flag, target map or lookup is accepted. Expected hashes must come
from retained caller commitments; rehashing a modified report does not replace
complete original-input replay.

The returned compartments are:

| Field | Contract |
| --- | --- |
| `original_example` | Complete unchanged original example, including its byte label and all existing provenance. |
| `original_example_sha256` | Commitment to that complete original report. |
| `model_input` | Exactly the original `{source_text, context}` dictionary, with byte-identical canonical JSON serialization. |
| `source_input_sha256`, `source_group_sha256` | Unchanged original source/input group commitments. |
| `compact_label` | Compact encoding, its complete encoding hash, and original relational request/report hashes; null when the original label is null. |
| `input_pins` | Original report, request, join and byte-codec commitments, compact-codec commitment, and a complete typed fingerprint of the original replay arguments. |
| `producer_pins` | The bounded union of direct owners and producer maps returned by successful authoritative replay. |

The replay fingerprint distinguishes dictionaries, ordered lists, raw byte
strings and canonical JSON scalars using type tags and length framing. It is
an additional original-input commitment, not a substitute for retaining the
original artifacts or their individual hashes.

Only the `model_input` compartment belongs in a model prompt. Neither the
original label, compact label, alternative IDs, target lengths, codecs, review
metadata nor provenance is added to that compartment. Changing an unreviewed
interpretation can change both target labels while leaving the exact model
input and physical-source group unchanged. Such alternatives remain one source
group. Pending source examples retain status `source_only_pending_target` and
both labels remain null; the companion performs no compact target encoding for
them.

The complete detached input has a 128 MiB bound. Each report, including the
combined companion with both labels, is bounded by 8 MiB. Example requests
retain their 16 KiB bound; codec dictionaries are bounded by 32 KiB. Original
join/relational requests, scope requests, raw HTML and sampling reports retain
their existing component bounds. Ordinary traversal is bounded by two million
items and depth 96. Whole overflow is refused without truncation, dropping the
original byte label or manufacturing a pending label. A large original example
that fits its own bound may still exceed the combined companion bound.

Public import and report hashing use standard-library code. Bounded input and
independent-hash checks precede lazy operation-owner imports. Direct source
files are checked through stable, bounded, non-symlink reads; only producer maps
returned by successful public replay can nominate further source reads. Input
and source checks run through completion and on escaping errors or cancellation.
The first escaping exception is preserved; if the final check also fails, it
receives a generic failure note and no companion result is produced. No source
path from an unreplayed offered report is treated as a trusted read request.

Every companion keeps `split="unassigned"`, integer-zero training and
evaluation-gold masks, and false authority flags. Embedding references remain
unverified declarations. `compact_checkpoint_qualified` and
`provider_tokens_measured` remain false. The two label formats are separate
decoder contracts despite sharing the fixed 259-symbol byte vocabulary.
Compact byte length plus BOS/EOS framing does not measure provider tokens or
establish checkpoint compatibility, learned reconstruction quality, reviewed
legal meaning or Lean execution.

Generated-output dispositions remain with the existing batch owner. Pending
original labels must not be converted into successful generated outcomes.

## Current-source qualification

The October 17, 2026 owned-validation run passed **524 tests**: 451 existing
regressions, 39 companion cases, 33 compact-batch cases and one independent
source-to-companion-to-batch integration fixture. There were no failures,
errors, skips or deselections. The unchanged standalone byte-codec file's 36
earlier cases remain historical evidence; its product closure stayed pinned.
Native, storage and source custody reported successful closeout.

The saved authored integration fixture preserves eight selected conditions and
all ten raw observations. Two valid candidates enter structural comparison;
only one matches the reference structure. The rival keeps its different
permission scope. Invalid UTF-8, missing EOS, duplicate, unexpected and
unidentifiable observations and a declared timeout remain explicit. Source
input remains unchanged, pending labels remain null, and masks remain zero.
These fixture outputs are not model predictions or statutory review.

The run retained the existing cooperative one-CPU, 2,048-MiB, two-process,
128-MiB and 600-second limits. Exact inputs, hashes, complete JUnit, fixture
outputs and independent readback are in the local workspace package
`artifacts/legal-ir-compact-integration-20261017T171221Z/README.md`.
Actual model-token savings, checkpoint compatibility and learned quality remain
unmeasured. The historical retained statutory targets still require 2,452 byte
IDs and exceed 512/1,024-ID consumers; this integration changes no output cap.
