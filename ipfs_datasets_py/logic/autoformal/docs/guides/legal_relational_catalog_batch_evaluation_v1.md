# Original-bound catalog batch diagnostics

The additive `legal_relational_batch_core_v1` and
`legal_relational_catalog_batch_evaluation_v1` owners account for a complete
selected population using the existing compact catalog grammar. They preserve
raw supplied observations, original catalogs and independent transport hashes.
Every available reference is replayed before decoding, and a complete candidate
is reconstructed through the existing public content, relational and paired
owners. The resulting rates describe conditional syntax and structure. They do
not establish legal meaning, context permission, authentic model execution or
accuracy against reviewed statutory targets.

The historical `legal_relational_batch_evaluation_v1.py` source remains pinned
at `663af1184aeb73d10213e9953fee501303119de076886fa526dabff2b16d2138`.
Its existing public interfaces, source bytes and first-operation caches are not
changed or initialized by the new core's source guard. Existing consumers keep
using their original owner. The new content profile provides an explicit
successor for differential testing; the catalog facade has no second accounting
loop.

## Public interfaces

The core accepts exactly two literal profiles:

```python
from ipfs_datasets_py.logic.autoformal import legal_relational_batch_core_v1 as core

report = core.prepare_relational_batch_core_v1(
    population_raw, references_raw, predictions_raw,
    profile="content_tokens_v1",  # or "catalog_tokens_v1"
    expected_population_sha256=population_sha,
    expected_references_sha256=references_sha,
    expected_predictions_sha256=predictions_sha,
)
```

All three transports are original `bytes`, and all three hashes are independently
retained SHA-256 commitments over those exact bytes. Population and references
keep the existing closed `legal-relational-batch-population/v1` and
`legal-relational-batch-references/v1` contracts. The predictions envelope uses
one corresponding codec and prediction schema, without callbacks, supplied
owner modules, a context resolver or caller-created decoded records.

The catalog-only facade selects its profile internally:

```python
from ipfs_datasets_py.logic.autoformal import legal_relational_catalog_batch_evaluation_v1 as catalog

report = catalog.prepare_relational_catalog_batch_evaluation_v1(
    population_raw, references_raw, predictions_raw,
    expected_population_sha256=population_sha,
    expected_references_sha256=references_sha,
    expected_predictions_sha256=predictions_sha,
)
report_sha = catalog.relational_catalog_batch_evaluation_sha256(report)
checked = catalog.validate_relational_catalog_batch_evaluation_v1(
    report, population_raw, references_raw, predictions_raw,
    expected_evaluation_sha256=independently_retained_report_sha,
    expected_population_sha256=population_sha,
    expected_references_sha256=references_sha,
    expected_predictions_sha256=predictions_sha,
)
```

Computing `report_sha` supplies a self-address, not independent evidence. Full
validation checks the independently supplied output commitment and regenerates
the complete result from all original transports. The core also exposes
`relational_batch_core_sha256` and `validate_relational_batch_core_v1`, with the
same original-bound replay requirement and an explicit `profile` argument.
No public entry point accepts a decoded record or an effective request shortcut.

The core content report has schema
`legal-relational-content-token-batch-evaluation/v2`. Its profile, authority,
limitations, input records, observation ledger, references, comparisons and
metrics are preserved from the old content owner. The explicit differential
allowlist is only the new schema, added `accounting_core`, and added core source
pin. The catalog report uses
`legal-relational-catalog-token-batch-evaluation/v1` and
`full-selected-catalog-token-output-diagnostics/v1`. Its facade adds its own pin
at the outer boundary. Core and facade digests therefore differ deliberately.

## Catalog prediction transport

The predictions envelope has exactly `schema`, `rows`, `codec`, and
`codec_sha256`, optionally `generation`. Its schema is
`legal-relational-catalog-token-batch-predictions/v1`. The complete fixed codec
comes from `legal_compact_catalog_tokens_v1`; its public digest is checked even
when no observations were offered. Missing or malformed generation declarations
remain diagnostics under the original generation contract.

Each well-shaped row has exactly these fields:

```text
id, source_sha256, context_sha256, status, teacher_forcing, target_access,
generated_ids, generated_ids_sha256, reason,
catalog_context_utf8, catalog_context_sha256, catalog_context_origin
```

The row's `context_sha256` is the selected source-context declaration.
`catalog_context_sha256` binds the exact separately supplied UTF-8 catalog
wrapper. The decoder retains that raw hash and its canonical context hash;
these commitments are distinct. The wrapper contains the complete original
signature and argument-role catalog under the existing catalog context schema.
Unused declarations are retained and validated, including declarations that
are not selected by the generated expression.

For `generated` rows, IDs are a plain bounded integer list and their hash is the
canonical ordinary-JSON SHA-256. A malformed IDs/hash row is retained without
inventing decoded output. Independently well-shaped catalog bytes/hash must
agree even when the IDs themselves are malformed. More than 512 supplied IDs
is a whole-operation refusal, not truncation or a declared model budget event.
An invalid catalog origin makes the row malformed and prevents decoding.

Catalog origins are exactly `authored_fixture`, `target_derived_label` and
`caller_supplied_unverified`. None grants inference permission or independent
source provenance. `decoder_declared` combined with `target_derived_label`
receives the `decoder_declared_target_derived_context` provenance issue and no
comparison credit, even when it decodes successfully. Authored-control
transport exercises can retain target-derived contexts as explicit unreviewed
fixtures.

For `abstained`, `unsupported`, `error`, `timeout`, `cancellation`, and
`not_started`, generated IDs/hash and all catalog context fields must be null,
and the reason must be nonblank. These are caller-declared terminal outcomes.
Actual owner exceptions, interruption, source changes and complete-bound
failures abort the operation without a successful partial report.

## Decode and accounting order

The core parses all original transports under one shared node budget and binds
the fixed source closure. It replays every available reference, including those
whose predictions will be missing, duplicate or invalid. Invalid available
reference assets abort; their absence from a final comparison cannot hide them.

Next, every eligible observation is mechanically decoded in arrival order.
This includes duplicates, unexpected or unidentifiable rows and rows whose
provenance will deny comparison credit. The full fixed public catalog decode
report is retained. A catalog, source or expansion failure cannot be disguised
as an ordinary duplicate or unexpected result.

For a valid candidate the adapter independently recounts the subset and mapping
on the catalog owner's validated tree. This traversal is not another parser.
It verifies the original-index content, selected and unused indices, nullable
catalog-to-effective map, role-row indices, effective context/content and the
outer `catalog_prediction_id`. It then calls public
`legal_compact_content_v1.decode_prediction_v1` on only the effective content
and context and requires equality with the retained nested prediction. No
reference, target identity sidecar or repair map is supplied during decode.
Only that checked prediction supplies candidate request bytes.

The core creates a closed private `legal-relational-batch-decoded-observation/v1`
record containing the raw observation and hash, arrival index, identity,
association, declared status, ordered shape/provenance reasons, decode profile,
complete decoder report/hash/disposition, candidate request/hash and final
accounting outcome. It is detached and checked internally. It is neither a
serialized input contract nor a reusable permission token. Candidate request
fields are null unless the original public decoder returned a valid candidate.

Each selected occurrence is classified in this order:

1. Missing observation.
2. Multiple observations for that selected ID: duplicate, without choosing one.
3. Invalid row shape: malformed.
4. Invalid source/generation provenance: unverifiable generation.
5. Explicit well-shaped non-output declaration.
6. Incomplete or rejected public decode disposition.
7. Valid candidate replay, followed by `valid_without_reference` or `compared`.

A valid decoded candidate that unexpectedly fails relational replay causes
whole-operation refusal. It is not a fabricated `invalid_typed_output` result.
That key remains in the original 17-key count inventory and normally stays zero
for the two token profiles. The raw-request owner's distinct classification
policy is outside this successor's scope.

The reason mapping is fixed:

| Public decoder reason | Counted disposition |
| --- | --- |
| `missing_bos_and_eos`, `missing_eos` | `incomplete` |
| `invalid_token_ids`, `missing_bos`, `interior_special_tokens` | `invalid_frame` |
| `invalid_compact_prefix`, `invalid_compact_content` | `invalid_content_output` |
| `output_limit_without_eos`, `no_admissible_next_token_within_total_limit` | `budget_exhausted` |

Unknown decoder dispositions abort. Invalid UTF-8 is not representable by this
fixed lexical vocabulary and is not inferred from missing effects or output.
The first escaping operation exception remains primary if a closing source or
input fence also fails; a bounded generic note records the additional refusal.

## Denominators, evidence and bounds

The selected population is the denominator. Each selected occurrence appears
exactly once, while every submitted raw observation appears once in the ledger.
Selected duplicates are an ID-to-indices map. Repeated unexpected IDs retain
all indices in a separate map, and unidentifiable observations retain arrival
indices. They do not inflate the selected denominator. No favorable candidate
is chosen from a duplicate set.

All terminal counts sum to the selected count. Valid output is only
`compared + valid_without_reference`. Six structural booleans remain distinct:
exact typed identity, family/profile, signature declarations, ordered argument
roles, declared structure and lexical alpha structure. Each has a full-selected
rate and a comparable-pair rate. With no comparable pairs, the latter fraction
is null. Neither rate is reviewed legal accuracy.

The ledger retains complete original raw rows and, where decoding was attempted,
complete public reports. Catalog reports retain generated IDs, lexical bytes,
framing, full original context, unused declarations, subset and role mappings,
effective content/context, nested prediction, outer identity, source records
and false authority fields. Source-context commitments remain separate from
supplied catalog commitments. No payload is dropped to make a report fit.

Bounds are unchanged: 1–64 selected rows, population 128 KiB, references and
predictions each 16 MiB, at most 256 observations, 500,000 shared input JSON nodes
and depth 96, request/context 524,288 bytes, paired report 4 MiB and complete
batch output 8 MiB. The catalog owner's own 2 MiB operation report and 512 total
IDs including BOS/EOS also apply. Overflow refuses atomically. A 537-entry
lexical vocabulary and a sequence fitting 512 IDs do not establish numerical
head, checkpoint, training or provider-token compatibility.

## Extraction and source custody

The source graph is acyclic. The core pins the unchanged old helper, actual
relational/paired/route/syntax owners, and the chosen fixed token/content
owners. Only the trusted route owner can nominate its bounded additional
producer closure; artifact-supplied paths cannot add dependencies. The core
never imports the catalog facade. The facade pins the finalized core, snapshots
itself, and adds only its own source pin after successful core accounting.

The exact old helper source supplies bounded ordinary JSON operations,
reference-row and generation checks, content observation/decode behavior,
owned-report subset checks, pair diagnostics and fractions. The new core owns
separate `_preflight_assets`, `_validate_references`, `_decode_observations`,
`_index_observations`, `_classify_occurrence`, `_compare_candidate`, and
`_assemble_report` phases. Indexing, precedence and fraction assembly are data
operations. Reference replay, candidate replay and paired comparison are
actual existing owner calls. Catalog intake is its own explicit schema; no
renamed content rows, substituted decoder globals or user callbacks are used.

Physical source snapshots and exact module origins are checked before lazy
imports, around public owners and after complete serialization. Detached
original input hashes are fenced on success and exceptions. Existing batch
snapshot caches are neither populated nor cleared by the new core guard. File
snapshots and known owner anchors are not a general proof of arbitrary cached
Python execution; a separately admitted fresh native checked-source validation
provides execution provenance for its exact selected cohort.

All original authority fields remain false; catalog context origin,
independence, permission, checkpoint and numerical compatibility are also
explicitly false. Training and evaluation-gold masks are integer zero. This
owner runs no model, training job, external provider, native Lean build,
permission review or publication. Existing syntax owners can regenerate Lean
text, which is not a build receipt or an implementation proof.

The staged implementation requires its separate admitted native qualification
before any pass count is reported. The intended regression evidence includes
full old-content differential equality outside the explicit metadata allowlist,
a fictional 19-selected/22-observation catalog population covering all reachable
terminal states, original-bound replay, unused-catalog identity changes and
atomic failures. Such fixtures do not constitute statute-to-IR evaluation.
