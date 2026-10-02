# Native codebase discovery catalog

`duckdb_control.intent_codebase_catalog.IntentCodebaseCatalog` implements the
bounded `intent-codebase-catalog@1` discovery profile. It references the complete
`codebase-ir-manifest@1` inventory and native immutable model/corpus versions.
It does not acquire a source head, model head, proof status, training lease or
admission decision.

## Why a derived projection is needed

The existing structural catalog retains source heads and publication receipts.
The existing model registry and source corpus catalog retain their own version
identities. The original `CodebaseVerificationCatalog` indexes conditional
verification/applicability artifacts and their native keys; it does not index
whole semantic manifests or model/corpus associations. It remains the owner to
reuse for that different verification-artifact domain.

A measured local fixture builds four semantic manifests over one exact source
head, with four distinct explicit integer contracts. Finding one contract by
reconstructing each manifest required four complete native reconstructions.
The new SQL selector reconstructs only the selected native manifest. Before
filtering it checks the bounded immutable discovery metadata against every SQL
selector row, so a missing matching selector cannot become a successful empty
answer. This is a reduction in expensive semantic reconstructions, not a claim
of general latency improvement. Live queries also pay for two independent
source/policy observations. It is not the scalable authenticated pagination or
consumed-record commitment protocol in RPI-032.

## Authority and persistence

| State | Sole owner | Discovery behavior |
| --- | --- | --- |
| Current source/AST generation | `CodebaseCatalog`, `RepositoryCodebaseIndex`, `DuckDBASTStore` | References and fences the complete existing head, including generation and publication receipt |
| Captured source and native semantic artifacts | Existing `ImmutableCAS` plus native semantic manifest loader | Reconstructs deterministic typed models and all unsupported inventory units |
| Model version/head/run/lease | `AutoencoderRegistry` | References immutable version and variant descriptors; recomputes version ID and verifies checkpoint bytes under the declared native artifact root |
| Source dataset/version/owned export | `SourceCorpusCatalog` | References existing immutable version; independently verifies owned package and materialized rows |
| Discovery association and selectors | `IntentCodebaseCatalog` | Owns only record CIDs, source-head/manifest selectors and idempotent operation IDs on the structural owner's serialized connection |
| Proof eligibility, task admission and completion | Existing independent verification/admission owners | No authority is acquired by this projection |

An associated model/corpus version is declared planning context. It does not
claim that the model generated the deterministic manifest or trained on that
corpus. A corpus reference can retain a native source-export profile unrelated
to the selected codebase; this is a checked identity association, not an inferred
training relationship. No model inference or training runs during discovery.
All returned records retain these distinctions explicitly.

The source, model and corpus database/artifact roots are immutable bindings of
the discovery domain. They are rechecked on access. Optional corpus code is
loaded only when a native corpus owner is supplied. No second writer connection
to the source database is opened by this module, and no closed owner schema is
altered. Model/corpus owners retain their own existing exclusive connections.
These independent immutable references do not imply a distributed atomic
snapshot across three databases.

## API

```python
from ipfs_datasets_py.duckdb_control.intent_codebase_catalog import IntentCodebaseCatalog

catalog = IntentCodebaseCatalog(index)  # optional model_registry, corpus_catalog
published = catalog.publish(
    repository, expected_head=head, manifest_cid=semantic_manifest_cid,
    operation_id="discovery:1", scheduler=scheduler,
)
historical = catalog.get(published["record_cid"])
current = catalog.lookup(
    repository, expected_head=head, policy_receipt_cid=policy_receipt_cid,
    path="main.py", contract_cid=contract.cid, limit=1, scheduler=scheduler,
)
```

`publish` and `lookup` call `verify_policy_current` at both successful boundaries.
That verifies the exact captured source, active AST generation, external ignore
configuration/bytes and repository ignore-rule population. Publication also
uses the existing native evidence owner's adjacent real-write/restore protocol
inside the SQL transaction to conflict with concurrent source writers. The
complete committed head is unchanged. No reads or callbacks run between the two
writes, and any interruption rolls back the transaction. Dirty source and ABA
republication refuse the old complete head. Historical `get` works from owned
artifacts after the source checkout disappears and explicitly makes no live
source claim.

Unknown references, CAS corruption, root replacement, schema drift, capacity
overflow, selector inconsistency and operation rebinding refuse. Failed final
observation can leave valid historical SQL rows; it cannot return them as a
current successful result. Reads do not execute target source, a solver, a model
or an artifact downloader.

## Physical migration and bounds

The logical schema remains `intent-codebase-catalog@1`. Physical version 1 is an
explicitly supported record-only format introduced by this module; it is not a
claim about a previously deployed production catalog. Physical version 2 adds
only the derived selectors and their query index. New catalogs default to
version 2. Creating version 1 is explicit:

```python
catalog = IntentCodebaseCatalog(index, create_storage_version=1)
# Publish immutable records using the same API, then migrate explicitly.
report = catalog.migrate(expected_storage_version=1)
```

Migration reconstructs the bounded native record closure before starting the
write transaction, checks the exact record population again in the transaction,
then creates and fills selectors atomically. It preserves record CIDs, operation
IDs, artifacts and all native source/model/corpus identities. Unknown versions
and stale migration fences refuse. A post-DDL failure rolls back actual DuckDB
tables and metadata. Restart never silently migrates a catalog. `catalog.storage_version` reads the
durable migration fence, including after an ambiguous migration response.

The default local profile admits at most 128 records, 256 operations, 32,768
selectors, 16 returned records, 512 KiB per discovery artifact and 8 MiB per
result. Counts use capped SQL subqueries. SQL row bodies, schema definitions and
CAS reads have independent preflight limits. The maximum referenced checkpoint
is 16 MiB. The native checkpoint descriptor/path is reused, with bounded
`O_NOFOLLOW`/nonblocking FD hashing because the older registry's generic hashing
method reads until EOF without its own read ceiling. Native corpus verification
requires an owner configured for at most 16 MiB per package and 256 total rows;
this preserves the package decoder's existing bounded profile.

Scope/source operations use the native shared resource admission. Deadlines are
cooperative observation boundaries, including the existing fixed Git process
limits. This qualification does not establish a hard overall deadline, generic
large-repository scaling, DuckLake delivery, proof-cache admission or benchmark
speedup.

## Qualification

`tests/integration/logic/software_contracts/test_intent_codebase_catalog.py`
uses actual file-backed DuckDB, Git, CAS and native model/corpus owners. It tests
nonempty migration and rollback, current/historical fresh-process replay,
source-head writer conflicts, explicit owner/root/reference validation, schema
and artifact corruption, complete selector misses, bounds and operation replay.
Model bytes are synthetic storage fixtures; source corpus packages are real
small Parquet exports. They establish storage contracts, not model quality or
proof correctness. The final run passed **42 tests in 111.58 seconds**, with zero skips.
[Qualification and exact source identities](evidence/intent-codebase-catalog-20261002/qualification.json),
[test output](evidence/intent-codebase-catalog-20261002/tests.log) and
[JUnit cases](evidence/intent-codebase-catalog-20261002/tests.xml) are retained.
With the same live fences, the four-manifest fixture measured 1.238 seconds
for linear selection versus 0.881 seconds through selectors (four versus one
native semantic reconstructions). These are local single-fixture observations.
The earlier transaction-nesting and no-op writer-fence failures are retained
as diagnostics; neither is counted as successful qualification.
