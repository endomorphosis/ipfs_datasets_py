# Finite NDJSON field projection

[`finite_record_projection.py`](../../ipfs_datasets_py/logic/software_contracts/finite_record_projection.py)
provides a deterministic candidate generator and an independent native checker
for one explicit field copy or rename across a bounded NDJSON document. The
checker verifies every supplied record and field. It does not run a model,
autoencoder, solver, Lean compiler, or source program.

The declaration must come from the consumer's reviewed task contract. This
module does not infer a field mapping from prose or certify that a mapping
captures the user's intent. Its receipt carries `evidence_kind="finite_record_check"`,
with `kernel_checked`, `semantic_alignment_verified`, `proof_authority`,
`execution_authority`, `publication_authority`, and `completion_authority` all
false. A finite correspondence check is not a kernel theorem or a task-completion
decision.

## API

```python
from ipfs_datasets_py.logic.software_contracts.finite_record_projection import (
    FiniteRecordProjectionContract,
    check_finite_record_projection,
    synthesize_finite_record_projection,
    verify_finite_record_check,
)

contract = FiniteRecordProjectionContract(
    mode="rename", source_field="id", target_field="key",
)
source = b'{"id":1,"name":"Ada"}\n{"id":"two","name":"Lin"}\n'
candidate = synthesize_finite_record_projection(source, contract)
# b'{"key":1,"name":"Ada"}\n{"key":"two","name":"Lin"}\n'
receipt = check_finite_record_projection(source, candidate, contract)

# Before a consumer uses a persisted observation, check current bytes again.
current = verify_finite_record_check(
    receipt, input_bytes=source, output_bytes=candidate, contract=contract,
)
```

`FiniteRecordProjectionContract` is frozen. Its closed `to_dict()` representation
includes the operation, scalar policy, record semantics and fixed resource
bounds. `from_dict()` rejects additional fields or altered policies; `cid` binds
the complete declaration under the existing software-contract identity profile.
The native APIs require exact `bytes` and the typed contract, rather than
coercing caller objects.

`FiniteRecordProjectionError.reason_code` identifies unsupported input,
correspondence failure or stale receipt bindings without including source data.
Consumers should retain unsupported tasks as residual work. A disagreement
between the generator and checker is a producer failure, not successful repair.

## Supported semantics

| Operation | Required input in every record | Output |
| --- | --- | --- |
| `copy` | Source field present; target field absent | Add target with the exact source scalar; retain source and all other fields |
| `rename` | Source field present; target field absent | Remove source; add target with its exact scalar; retain all other fields |

Source and target must differ and match the ASCII identifier grammar
`[A-Za-z_][A-Za-z0-9_]{0,63}`. Existing targets are refused even when their value is
null. Null is a value, not a missing field. Booleans and integers remain distinct.
Unrelated field names may contain Unicode or be empty; their exact strings and
values are retained. Unicode is not normalized.

Record order, count and multiplicity are preserved. No field is implicitly
treated as a unique identifier, so repeated records remain repeated. Object-key
order and JSON whitespace do not affect correspondence. The generator emits
sorted keys, compact UTF-8 JSON and a final LF for each record; the checker also
accepts equivalent NDJSON formatting. Both original byte strings remain bound
in the receipt even when their formatting differs.

Each record must be a nonempty JSON object containing only null, boolean,
bounded integer or Unicode-string values. A nonrecursive lexical scan rejects
nested objects and arrays before the JSON decoder runs. The parser also refuses
duplicate keys, including duplicates expressed with Unicode escapes, floats,
exponent notation, nonfinite numbers, invalid UTF-8, unpaired Unicode surrogates,
blank lines and an empty document. LF and CRLF line endings are accepted, with
an optional final newline.

| Bound | Limit |
| --- | --- |
| Complete input and complete output | 1,000,000 bytes each |
| Records | 1–4,096 |
| Fields per input or output record | 1–128 |
| Key | 256 UTF-8 bytes |
| String value | 16,384 UTF-8 bytes |
| Physical line before LF | 131,072 bytes |
| Integer magnitude | At most `2**53 - 1` |

Copying a field in a record already containing 128 fields is refused. Candidate
generation checks the expanded line and document sizes before returning bytes.
The first version does not support filtering, sorting, aggregation, joins,
arithmetic, nested paths, target overwrites, or multiple field mappings.

## Evidence and consumer responsibilities

The checker parses the input and candidate independently and verifies exact
positional field correspondence. It does not call the generator or compare the
candidate to generated serialization. The receipt binds:

- Complete input and output SHA-256 hashes, raw CIDs and byte sizes.
- Complete contract, its CID and SHA-256 hash.
- Record and checked-scalar counts, correspondence policy and claim scope.
- Current checker and software-contract identity module source hashes and CIDs.
- A structured CID for the complete receipt body.

`verify_finite_record_check()` executes the checker again and requires the
supplied receipt to equal that fresh result, including scalar types and checker
provenance. A stored successful status, recomputed CID, or hydrated database
record does not bypass this check. Source or output formatting changes also
invalidate the previous receipt because the complete bytes differ.

The source provenance describes the two recorded module files. It is not a
transitive attestation of the Python runtime, standard library or `multiformats`,
and does not attest that modified files match already loaded Python code. The
consumer must pin its loaded runtime and retain its own source/currentness
checks.

The supervisor consumer is responsible for binding the declaration to signed
intent, immutable input paths, task revision and declared output permissions;
staging candidates in an allocated worktree; and applying ordinary validation,
publication and completion gates. This shared module writes no files and grants
none of those permissions. Persisted proof-index or DuckDB observations must
retain the finite-check evidence kind rather than become active kernel-proof
receipts.

## Verification

The focused suite uses authored copy/rename examples and adversarial mutations
of record order, cardinality, fields, scalar types, null handling, JSON keys,
Unicode, bounds, complete-byte hashes, contract identity, checker provenance and
receipt authority. It also prevents the checker from invoking the synthesizer
and ensures nested input is rejected before recursive JSON decoding.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/unit/logic/software_contracts/test_finite_record_projection.py \
  -q -o addopts=''
```

These checks establish the bounded operator behavior. Full supervisor lifecycle
qualification, benchmark rewards and comparisons with model-driven task runs
require their separate integration evidence.
