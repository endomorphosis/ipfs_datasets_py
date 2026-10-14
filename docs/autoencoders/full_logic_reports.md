# Full legacy logic reports

The full-report publisher preserves an original legacy CUDA producer receipt
byte for byte using standard gzip. It does not rerun the model, reconstruct
missing targets, change weights, or admit legal statements.

Files live in `autoformal/uscode/reports/v1/` in
`justicedao/uscode-autoformal-span-cache`. Each report manifest records both the
compressed file hash and the exact original JSON byte hash, source identities,
checkpoint provenance, actual output counts, and unavailable-document reasons.
Only an exact-commit remote hash/size verification permits an uploaded receipt.
Original local files remain in place.

To read a downloaded report:

```python
import gzip, hashlib, json
from pathlib import Path
compressed = Path("report.json.gz").read_bytes()
raw = gzip.decompress(compressed)
# Verify both hashes and expected lengths against its manifest before use.
report = json.loads(raw)
for row in report["rows"]:
    target = row.get("logic_target_observation", {})
    document = target.get("document")
    print(row["source_span_id"], target.get("status"), target.get("reason"))
    if document is not None:
        print(document["views"].keys())
```

The September 30 retained archive has 32 decoder observations, two compiler
rules, and 22 complete captured bridge documents with 30 views each. Ten
other documents were excluded by the historical 4 MiB export bound; their
absence is retained explicitly. For these 22 historical documents, the
recorded inner hash uses `json.dumps(document, sort_keys=True,
allow_nan=False)` with default spacing. Compact JSON produces a different
byte hash even when the parsed object is the same.

The complete receipt retains raw vectors, projected vectors, direct compiler
outputs, original logic targets, loss values, timing and source provenance.
This historical batch predates the guided compiler comparison. No independent
learned formula decoder or guided output is invented during publication.
Source-derived bridge targets remain source-derived evidence.

These files can support later dataset curation and teacher-target experiments.
They are not automatically qualified training labels. Keep source splits,
producer identity, diagnostic vector provenance and compiler failures when
building next week's training inputs. Goals are imported separately after
review; this publisher never opens the agent supervisor database. Lake remains
the only Lean admission and every report publication remains unadmitted.

Verified publication: [report manifest](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/blob/4f7922a2188c111e30841a08769f0f989d0b7c61/autoformal/uscode/reports/v1/manifests/0f2431a7c4746625fdbf693b312447f138d7ff4b820774ed4990dc334caa84ed.json).
The archived report is 3,959,482 bytes compressed and reconstructs all
73,673,016 original bytes. The local original remains retained.

## Fenced owner completion and retained result evidence

The opt-in [SpanCache claim control](../../ipfs_datasets_py/logic/autoformal/span_cache_claims.py)
is obtained with `cache.fenced_claims()` on the original native catalog owner
thread. It uses that exact connection and one transaction for span outcomes,
term links, claim retirement, full result evidence and compact operation
receipts. The existing `claim_batch`, `complete_claimed` and `release_claims`
helpers retain their legacy unqualified contracts. Existing ingestion callers
are not automatically migrated by importing the new interface.

Call these APIs only through the owner:

| Operation | Inputs and meaning |
| --- | --- |
| `bind_sources_fenced(operation_id, bindings)` | Closed rows contain `source_span_id`, explicit `source_revision`, `source_sha256` and `expected_binding`. First binding requires `expected_binding=None`; a later revision requires the exact prior revision/hash. Rebinding atomically retires old claims and invalidates cached term links. |
| `claim_batch_fenced(operation_id, worker_id, span_ids, lease_seconds=300)` | Claims an explicit bounded set of previously source-bound spans and returns durable claim envelopes without copying full source text into the operation ledger. |
| `read_claim_source_fenced(claim)` | Returns exact stored source bytes represented as UTF-8 text through the live owner. An expired or superseded claim cannot fetch a new live response. |
| `complete_claimed_fenced(operation_id, rows, code_identity=..., path_hashes=...)` | Each closed row contains `claim`, `agrees`, `decompiled`, `rule`, `repair` and `reason`. Source text and legal IDs come from the verified owner row. Both the rule and repair/diagnostics are retained for agreement and disagreement. |
| `release_claims_fenced(operation_id, claims)` | Releases only exact currently live claims. Wrong source, worker, token, generation or deadline refuses the entire batch. |
| `resolve_operation(operation_id, command, payload)` | Looks up an exact committed command/payload after an ambiguous response. It does not rerun the operation or grant a present lease. |
| `read_completion_results_fenced(operation_id, rows, code_identity=..., path_hashes=...)` | Owner-local historical lookup requiring the exact original completion payload. Returns the full retained result ledger for later export, without duplicating full source text. Missing legacy history or an oversized reply is explicitly refused. |

Source revisions must be caller-supplied immutable identities: a 40-character
lowercase Git/Hub commit, optionally prefixed with `git:` or `hub:`, or an
explicit `sha256:` followed by 64 lowercase hexadecimal characters. A missing
revision is never derived from the span text. This binding checks identity;
it does not authenticate statutory currentness or legal interpretation.

A claim envelope contains `schema`, `source_span_id`, `source_revision`,
`source_sha256`, `legal_id`, `claim_worker`, `claim_token`, `owner_generation`,
`fence` and `expires_at`. Fenced APIs require the original process/thread and
native connection. A later owner incarnation advances its persisted generation
and fences older work. Owner transitions and new mutations both advance the
same persisted fence column, creating a real native MVCC conflict for an
overlapping owner transition. Exact retries do not advance it. New mutations verify
the original finite claim deadlines again after output work and immediately
before commit. A caught nested failure still poisons the whole transaction.

The fence uses a plain native `UPDATE`, checks its affected-row count and reads
back the generation/sequence in the same transaction. The installed DuckDB
1.5.5 allowed an overlapping generation update when the guard used
`UPDATE ... RETURNING`; actual private-owner overlap tests rejected the plain
update variant correctly. Keep this concurrency test when changing engines or
the guard SQL. Sequential stale-generation checks alone missed this failure.

Exact retries return the original committed receipt, including after source
rebinding, expiry or owner restart. That historical receipt does not assert
that its old claim is still live. Reusing its operation ID with changed output,
compiler bindings, span membership or command is rejected. Legacy writers are
not upgraded into fenced writers; their source/status changes can invalidate
subsequent fenced work.

Full results reside in the same catalog's `span_claim_results` ledger. Compact
receipts remain in `span_claim_operations`; they are not enlarged to contain
all model/compiler output. Owner commands and historical result responses keep
the 65,536-byte control bound. Larger evidence needs a separately designed
immutable data-plane export rather than truncation or a larger control limit.
No exporter or production ingestion switch is activated by this API.

Every new receipt and result lookup explicitly records `qualified=false`,
`admitted=false`, `formalized=false` and `roundtrip_ok=false`. A compile-cache
seal is engineering evidence. Constitution spans remain unformalized. Actual
scoped `lake build <Lib>` remains the sole Lean admission; transactional tests,
result rows, parser output and transport responses confer no such admission.

## Executable private-native T02 engineering checker

The [engineering checker CLI](../../scripts/ops/legal_ir/check_span_claim_acceptance.py)
and [pure report verifier](../../ipfs_datasets_py/logic/autoformal/span_claim_acceptance.py)
bind the complete 121-case native claim/Quack regression collection to an
explicit manifest. The manifest contains `criterion_key=OBLIGATION-F-T02`,
`task_cid`, `validation_key`, `repository_commit`, `declared_native_tree_id`,
ordered `source_pins`, `test_modules`, `expected_cases` and `scenarios`, with
schema `span-claim-engineering-manifest/v1`. The tree/task declarations are
not authenticated or converted into native IR roots by this checker.

The live command requires an existing validation reservation with at least
one CPU slot, 1536 MiB and two child-process slots for the outer pytest entry
and complete inner pytest collection.
The trusted launcher passes the granted lease ID using
`IPFS_DATASETS_T02_VALIDATION_LEASE_ID`, the existing state path through
`IPFS_DATASETS_T02_SCHEDULER_STATE` and its pinned policy through
`IPFS_DATASETS_T02_SCHEDULER_POLICY_SHA256`. The CLI checks the unchanged native
scheduler policy, original owner ancestry and request scope, and polls native
cancellation. It does not acquire, renew, reset or reconfigure the scheduler.

The unchanged native policy admits a closed pytest command. Its explicit
[entry adapter](../../scripts/ops/legal_ir/span_claim_acceptance_test.py) lies
outside default testpaths and delegates to the same checker. The trusted
launcher additionally supplies exact paths in `IPFS_DATASETS_T02_MANIFEST`
and `IPFS_DATASETS_T02_OUTPUT`. Missing either path fails, without a skip or
a fabricated lease. The validation argv is:

```sh
python3 -m pytest -c pytest.ini -o addopts= \
  -panyio.pytest_plugin -ppytest_asyncio.plugin \
  scripts/ops/legal_ir/span_claim_acceptance_test.py -q
```

Attached plugin options keep argv tokens unique, as required by the native
validation-record contract. The adapter supplies no subset, extra authority or
alternative policy. Direct
execution of the convenience CLI is outside this unchanged policy's allowed
command prefixes; do not widen that policy to admit it.

The selected existing reservation must have a request ID beginning with
`legal-ir-supervisor-start:gap-T02-`. The library runner instead requires an
explicit lease verifier supplied by a trusted owner; no unverified default or
boolean bypass exists. The output directory must be fresh.
Standalone callers may explicitly pass `--scheduler-state` and
`--expected-policy-sha256`; absent launcher environment and absent explicit
values refuse. No scheduler path or policy is synthesized. The native pytest
binding retains only the reviewed relative adapter path in argv; its trusted
launcher supplies manifest, output and native reservation context separately.

The runner keeps source hashes before/after, exact subprocess invocation,
JUnit bytes and an independent setup/call/teardown event stream. It checks
actual imported producer origins, native DuckDB/transport identity, complete
scenario coverage and zero missing, duplicated, failed or skipped cases.
The offline verifier additionally requires the independently retained launch
binding; a patched report or standalone pass count supplies no owner trust.
Temporary pytest inputs, bytecode and cache state remain isolated.
The native pytest cacheprovider remains enabled because repository conftest
uses its API; its cache directory is fixed to the fresh temporary runtime.
Collection/startup failure retains actual exit status, invocation, source and
lease observations in `failure-execution-report.json`. Missing JUnit or phase
evidence is recorded as unavailable and never replaced with synthetic passes.
External SIGTERM raises into the same bounded owned-child TERM/KILL cleanup
and temporary-runtime cleanup before emitting a refusal. The CLI restores the
previous signal handler afterward; repeated SIGTERM during that cleanup is
ignored until the bounded cleanup finishes.

Its `engineering_gate_passed` result covers private transactional/transport
regressions only. Native acceptance still requires a reviewed exact validator
binding, authenticated owner material and an explicitly selected production
caller migration. All legal/model/Lake/roundtrip authority flags remain false;
this command never opens a production SpanCache or supervisor goal database.
