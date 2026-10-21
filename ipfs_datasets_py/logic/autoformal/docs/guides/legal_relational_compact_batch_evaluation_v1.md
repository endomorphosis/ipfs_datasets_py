# Complete-population accounting for compact relational outputs

The existing `logic/autoformal/legal_relational_batch_evaluation_v1.py` owner now has an explicit compact-ID interface. It reuses the original selected-population loop, reference replay and paired structural comparator. Its legacy v1 request-text interface and report schema remain unchanged. The qualification below covers engineering integration; no model experiment is claimed.

`prepare_relational_compact_batch_evaluation_v1(population_raw, references_raw, predictions_raw, *, expected_population_sha256, expected_references_sha256, expected_predictions_sha256)` takes three independently committed original UTF-8 JSON transports. Population and reference contracts are the existing `legal-relational-batch-population/v1` and `legal-relational-batch-references/v1`. Exact occurrence IDs associate observations; matching source hashes cannot substitute for missing identities or choose between same-source rivals.

The new prediction envelope is:

```json
{
  "schema": "legal-relational-compact-batch-predictions/v1",
  "codec": "the complete fixed compact codec object",
  "codec_sha256": "its independently retained canonical SHA256",
  "generation": "the existing generation declaration object",
  "rows": []
}
```

The strings standing for objects above are explanatory placeholders, not valid inputs. Supply the exact output of `build_relational_compact_codec_v1()` and its `relational_compact_codec_sha256()` commitment. The fixed table is validated through that existing owner. `generation` retains its existing declared-only contract; missing or invalid generation metadata withholds comparable credit. This interface does not add 4096-dimensional compatibility or authenticate model execution.

Each observation has exactly `id`, `source_sha256`, `context_sha256`, `status`, `teacher_forcing`, `target_access`, `generated_ids`, `generated_ids_sha256` and `reason`. For `status="generated"`, the two access flags must be literal false, `reason` must be null, and the IDs must be an ordinary list of signed int32 integers. Their digest covers the canonical finite JSON array, using sorted keys, separators `(',', ':')`, UTF-8 and `ensure_ascii=False`. IDs outside the fixed vocabulary remain valid evidence of a rejected frame; booleans, floats and out-of-int32 values are malformed observations and remain in the raw ledger without coercion.

Explicit `abstained`, `unsupported`, `error`, `timeout`, `cancellation` and `not_started` observations require null ID fields and a bounded nonempty reason. They are caller declarations. A contradictory observation carrying IDs is malformed, and its complete offered data is retained. Real codec, source-fence, resource or runtime exceptions are not converted to these declarations: they propagate and no partial batch result is returned.

## Output preservation and denominator

The `legal-relational-compact-batch-evaluation/v1` report uses profile `full-selected-compact-id-output-diagnostics/v1`. Every ordinary submitted observation is retained in `observation_ledger[].raw_observation`, alongside its original arrival index and canonical row digest. This includes malformed objects, nonobjects, duplicates, unexpected IDs and unidentifiable rows.

For committed integer-ID lists, the existing compact decoder runs without any reference argument. The ledger retains its status/reason, framing, original transport UTF-8 when valid, hexadecimal bytes when recoverable, raw byte count/hash, reconstructed canonical request identity, original-owner identities and complete decoder-report hash. The raw IDs remain in `raw_observation`; the byte/frame observations do not attest numerical generation. Invalid frames can have null raw-byte fields because no unambiguous byte frame was recovered. Null does not mean zero emitted bytes.

Mechanical decoding can retain evidence for duplicate or unexpected observations without awarding them comparable credit. Duplicate occurrence IDs never select a winner. The same expected occurrence still has exactly one terminal accounting outcome; all of its offered observations remain separately visible. Every selected occurrence stays in the denominator, including missing observations and unavailable references.

The compact report preserves existing terminal categories and adds:

| Outcome | Meaning |
| --- | --- |
| `incomplete` | The compact owner observed missing BOS/EOS or missing EOS; it performed no implicit repair. |
| `invalid_frame` | Offered integer IDs violate the fixed vocabulary/framing contract. |
| `invalid_utf8` | A complete byte frame contains invalid UTF-8; exact hex/hash remain. |
| `invalid_compact_output` | Compact JSON or its reversible projection was rejected. |
| `invalid_typed_output` | The compact projection did not produce a request supported by the existing relational owner. |
| `error`, `timeout`, `cancellation`, `not_started` | Explicit caller-declared nonoutput dispositions; execution authenticity remains false. |

Shape/provenance failures and duplicate/missing accounting take precedence over a mechanically decoded candidate. A valid different modal scope or argument order remains a valid candidate; the original comparator reports the structural disagreement. A valid request with no reference is `valid_without_reference`, not an omitted denominator member. Full-selected and comparable-pair diagnostics remain separate.

## Custody, bounds and validation

The core source snapshot cache is unchanged. A separate compact dependency cache fences the actual canonical compact and original byte-codec modules and the original codec's fixed source closure. Offered reports or codec metadata cannot nominate source paths. Import anchors, current physical snapshots and any original codec source-cache witnesses must agree. Legacy and compact calls can run sequentially in one process without expanding or replacing the core cache.

Population limit 64, observation limit 256, prediction transport limit 16 MiB, report limit 8 MiB and ordinary-JSON node limit 500,000 remain unchanged. Retaining raw IDs and hex can reach these aggregate bounds before the codec's individual sequence ceiling. Complete input, reconstructed request, decoder report or aggregate output overflow refuses the entire operation; no subset or shortened report is returned.

Use `relational_compact_batch_evaluation_sha256(report)` and `validate_relational_compact_batch_evaluation_v1(report, population_raw, references_raw, predictions_raw, *, expected_evaluation_sha256, expected_population_sha256, expected_references_sha256, expected_predictions_sha256)` for a complete original-input replay. A fresh digest of a changed report does not authorize changed observations, comparison results or masks.

The new authored suite covers the complete mixed terminal population, raw duplicates/unexpected/unidentifiable observations, invalid UTF-8/IDs/incomplete frames, shuffled same-source rivals, unavailable references, original pin failures, source drift and interruption, aggregate bounds, resealed report mutations, and mixed legacy/compact calls. The current-source qualification below supplies the execution evidence for these engineering checks.

All semantic, review, generation, training and proof authority flags remain false; training and evaluation-gold masks remain zero. These are syntax/transport observations over an authored profile. Retained A/B statutory hypotheses do not become independent laws or eligible supervision, and the separate unary definition profile is not silently coerced into this relational format.

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
