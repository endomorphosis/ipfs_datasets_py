# Context-bound content tokens in the existing relational batch evaluator

The explicit content-token API in
`logic/autoformal/legal_relational_batch_evaluation_v1.py` accounts for raw output
from the existing fixed compact-content token format. It shares the original
selected-population and paired-comparison loop with the legacy UTF-8 request
and full-request compact-byte interfaces. Those interfaces keep their existing
schemas, bounds and behavior. This profile introduces no tokenizer, model,
checkpoint migration, signature catalog, AST or second denominator owner.

Current-source owned qualification passed **594 cases** across eight complete
test files: 350 existing relational/byte regression cases, 109 compact-content
cases, 92 content-token cases and 43 new content-token batch cases. The saved
native request is `95c2af3f101aa1e7e0098eab8dfdaad7b343ef9dd2d7e43c9aae18439e23641a`;
the qualification receipt is
`5af5395318d756cc834fe5120e8d1d2780e979e0fedd82247645eb52396f0172`.
The native owner reported successful source, execution-resource and storage
closeout. This is authored engineering evidence; no numerical model ran.

The saved mixed fixture retains all 16 selected conditions and 19 observations.
One comparable candidate matches lexical alpha structure while retaining fresh
generated identities. Exact expression identity remains unequal. The standalone
fixture likewise separates structural agreement from archival identity. Context
permission and all training/evaluation-gold masks remain false/zero.

Complete JUnit identities and fresh collection-cache identities are retained.
The separate full per-call diagnostic arrays exceeded their byte bound; the
receipt preserves the 594-success summary and that omission explicitly. Earlier
source-example suites omitted from this cohort remain historical evidence.
See the local workspace evidence package
`artifacts/legal-ir-structural-target-20261017T175615Z/README.md` for exact inputs,
raw outputs, installation history and readback limitations.

## Public interface

```python
prepare_relational_content_token_batch_evaluation_v1(
    population_raw, references_raw, predictions_raw, *,
    expected_population_sha256, expected_references_sha256,
    expected_predictions_sha256,
)

relational_content_token_batch_evaluation_sha256(report)

validate_relational_content_token_batch_evaluation_v1(
    report, population_raw, references_raw, predictions_raw, *,
    expected_evaluation_sha256, expected_population_sha256,
    expected_references_sha256, expected_predictions_sha256,
)
```

Population and reference envelopes are the unchanged
`legal-relational-batch-population/v1` and
`legal-relational-batch-references/v1`. Every independent expected hash commits
to the actual original transport bytes, including whitespace. The new
predictions envelope is closed to `schema`, `codec`, `codec_sha256`, `rows` and
an optional `generation` declaration. Its schema is
`legal-relational-content-token-batch-predictions/v1`. The codec must equal the
actual public `build_compact_content_token_codec_v1()` result, independently
committed by `codec_sha256`. Generation declarations retain the original
generation contract and never authenticate numerical execution.

Each observation has exactly these fields:

| Field | Contract |
| --- | --- |
| `id` | Selected occurrence identity; arrival order is retained separately. |
| `source_sha256` | Declared original source commitment, checked against its selected row. |
| `context_sha256` | Declared **source context** commitment, checked against its selected row. |
| `status` | `generated`, `abstained`, `unsupported`, `error`, `timeout`, `cancellation` or `not_started`. |
| `teacher_forcing`, `target_access` | Literal false for diagnostic comparison credit; these remain declarations. |
| `generated_ids`, `generated_ids_sha256` | Complete offered integer list and its canonical ordinary-JSON SHA256 for `generated`; otherwise both null. |
| `content_context_utf8`, `content_context_sha256` | Exact separately supplied signature/role context UTF-8 bytes and their SHA256 for `generated`; otherwise both null. |
| `content_context_origin` | `authored_fixture`, `target_derived_label` or `caller_supplied_unverified` for `generated`; otherwise null. |
| `reason` | Null for `generated`; bounded nonempty declaration for each non-output status. |

The signature/role context uses the existing closed
`legal-relational-compact-context/v1` schema, containing `signature` and
`argument_roles`. It is not the source-context commitment in `context_sha256`.
Identity sidecars, expected target expressions and original artifact identifiers
are never accepted as decode inputs. Supplied context is validated by the
actual public token/content owners. Context hash mismatch, invalid admitted
context, owner disagreement, source drift and interruption abort the complete
operation; they are not classified as model rejection.

Malformed observation types and missing/ill-typed observation fields remain
raw observations with no comparison credit. Missing or ill-typed context
commitments and unrecognized context-origin labels also skip mechanical decode;
their complete offered rows remain retained. A syntactically supplied context
string with a valid-shaped but incorrect commitment refuses the entire call,
including when that observation's IDs are malformed. A supplied ID list longer
than 512 also refuses the call, including a list containing malformed elements.
There is no truncation, byte fabrication or target-derived repair.

## Three separate commitments

The source/context commitments describe which selected occurrence an output
claims to address. The content-context commitment describes the ordered
signature and roles used to interpret predicate indices. Its origin label is
another caller declaration. None authenticates source exposure, permission,
independence or target withholding.

`target_derived_label` can support an explicitly conditional authored transport
diagnostic. It cannot establish source-only or held-out generation. The other
two origin labels do not establish permission either. Pairing
`generation.kind=decoder_declared` with `content_context_origin=target_derived_label`
contradicts the no-target-access declaration: the full raw and decoded evidence
remains, but its selected outcome is `unverifiable_generation` and receives no
comparison credit. `authored_control` fixtures may retain conditional diagnostic
comparisons. Relabelling origin is not evidence that context is independent.
The current compact
content owner requires **every declared predicate to appear**. Selecting only
the predicates that occur in a protected answer would leak information; a broad
independently supplied catalog is not automatically a supported alternative.
No vocabulary-selection policy is introduced here.

The existing compact decoder example retains its entire original source
example and keeps target-derived compact context in the label compartment.
This batch API does not alter that input boundary or promote that label context
into model input. The full-request byte and compact-byte codecs retain their
different archival transport roles.

## Raw evidence and population accounting

The versioned output schema is
`legal-relational-content-token-batch-evaluation/v1`, with profile
`full-selected-context-bound-content-token-output-diagnostics/v1`. It retains
the existing report fields plus `content_codec`,
`declared_operational_statuses_are_unverified=true`, and
`content_context_claims_are_declarations_only=true`.

Each ledger row retains the complete `raw_observation` as ordinary JSON. Where
mechanical intake is possible, `content_decoding` contains the **complete**
public token-owner report, including all offered IDs, framing, generated text
and hex where representable, owner pins, and the complete generated prediction
when valid. `content_decoding_sha256` commits to that full report. Missing values
stay null. Invalid token IDs cannot be converted into invented bytes; this fixed
lexical vocabulary cannot emit arbitrary invalid UTF-8 bytes. Such byte-output
evidence remains the full-request byte profile's separate contract.

Missing, duplicate, unexpected and unidentifiable observations remain visible.
Valid decoder reports can be retained for duplicate/unexpected/unidentifiable
observations, but none receives favorable comparison credit. Every selected
occurrence receives exactly one terminal disposition; every offered observation
has exactly one ledger entry. Missing references stay unavailable and do not
shrink the selected denominator.

The terminal categories are `missing`, `duplicate`, `malformed`,
`unverifiable_generation`, `abstained`, `unsupported`, `invalid_typed_output`,
`valid_without_reference`, `compared`, `incomplete`, `invalid_frame`,
`invalid_content_output`, `budget_exhausted`, `error`, `timeout`, `cancellation`
and `not_started`. Current successful content-owner validation followed by a
public relational replay refusal is an operational inconsistency, so it does
not increment `invalid_typed_output`. That inherited diagnostic category remains
explicitly present at zero when no such classified outputs exist.

Token-owner reasons `output_limit_without_eos` and
`no_admissible_next_token_within_total_limit` map to `budget_exhausted`; the full
original report retains its literal `rejected` status and reason. Other invalid
frames, invalid content and incomplete output remain distinct. Declared error,
timeout, cancellation and not_started are never inferred from absent effects
or from exceptions in this evaluator.

## Identity and structural comparisons

The public token decoder calls the existing compact-content prediction owner
with IDs and this observation's context only. It generates fresh content-bound
expression/signature/node identities and binder spellings. It receives neither
a metric reference nor an archival sidecar. The generated canonical request
then passes through the existing relational preparation, validation and paired
reconstruction owner.

Consequently an unchanged content tree can differ from an original authored
request in exact typed-expression equality and declared structure that includes
binder names. The existing `lexical_alpha_structure_equal`, signature and
ordered-role diagnostics remain distinct comparisons. References are consulted
only during metric comparison. The evaluator never restores archival IDs or
renames a candidate to make an exact-identity metric pass. Exact original request
reconstruction remains the separate `project_request_v1` /
`reconstruct_request_v1` archival contract.

All comparisons are conditional on supplied unverified context and authored
references. They are structural diagnostics, not reviewed statutory accuracy,
governing meaning, proof authority or learned model accuracy.

## Bounds, source custody and remaining gates

The existing token codec has 537 fixed vocabulary entries and a separate limit
of **512 total IDs including BOS and EOS**. Whole input and report bounds remain
unchanged: 64 selected rows, 256 observations, 524,288 bytes per content context,
16 MiB predictions, and **8 MiB complete batch output**, with the existing JSON
node/depth limits. Large collections of complete decoded predictions can exceed
the output bound; the call refuses atomically instead of dropping evidence.

Only actual canonical token/content owners and their fixed source dependencies
can contribute producer custody. A separate content snapshot cache preserves
both earlier source caches when all three APIs run in one process. Closing
fences check input snapshots, source bytes and physical source identities. No
path supplied by an observation is opened. These are engineering custody checks;
fresh admitted native execution supplies its own separate execution evidence.

All prior authority flags remain false. This profile explicitly adds false
`permitted_inference_context_verified`, `content_context_origin_verified`,
`content_context_independence_verified` and `checkpoint_compatibility_verified`.
Training and evaluation-gold masks remain zero. Matching special IDs or staying
within 512 positions does not qualify a checkpoint, tokenizer, output head,
conditioning width or optimizer state. No numerical model, training, provider,
GPU, solver or Lean build is executed by this owner. Native definition-owner
intake and wider legal syntax remain separate unsupported profiles.
