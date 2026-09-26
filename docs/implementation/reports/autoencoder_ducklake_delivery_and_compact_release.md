# Autoencoder DuckLake delivery and compact private release

Status, 2026-09-25: isolated native metadata delivery and offline compact
checkpoint packaging are implemented. Focused checks and the source-stable
558-test combined storage/packaging regression pass. The failed first combined
attempt remains retained below. Production DuckLake activation, remote Quack adaptation and HF
publication remain pending. Native **training** validation remains deferred at
the user's request; disposable native storage fixtures do not lift that deferral.

The registry's complete checkpoint remains authoritative. Neither a mirror
commit nor a local release package promotes a head, establishes learning or
admits a theorem. Only the existing qualified Lake admission path can do that.
There were no model-weight downloads or HACC work, and Constitution coverage is
unchanged.

## Isolated native metadata destination

[`IsolatedNativeDuckLakeHistory`](../../../ipfs_datasets_py/ducklake/autoencoder_history.py)
owns a fresh local catalog and its own `DATA_PATH`. It checks DuckDB 1.5.5 and
installed extension digests against the existing
[`capabilities.py`](../../../ipfs_datasets_py/ducklake/capabilities.py) pins, then
uses the explicit local extension load order. It performs no extension install
or autoload. Catalog specification/version remains 1.0; automatic migration
and data-path override are disabled. The constructor rejects production
activation.

This path writes real DuckLake tables and managed Parquet data. The existing
[`IngestService`](../../../ipfs_datasets_py/ducklake/ingest.py) defaults to a
hermetic catalog and in-memory idempotency state; those defaults are not claimed
as durable native ingestion. The new destination reuses the installed capability
pins and load policy while remaining explicitly isolated. Existing production
DQK gates are unchanged.

A batch contains at most ten immutable event records and at most 1 MiB of
canonical JSON. Sorted event IDs and complete source/event bytes determine its
identity. Source identity includes the explicit source ID, registry database
path and artifact root; this binds a namespace rather than authenticating
arbitrary issuers. Timestamps retain the registry's finite DOUBLE value. Only
immutable version and variant records enrich events; a historical `run_failed`
event keeps its original run ID and attempt rather than adopting a later result.

The destination inserts missing exact events and a batch marker in the same
DuckLake transaction. Native commit metadata binds that batch ID to one snapshot.
Lookup checks the marker, complete event contents and native snapshot before
issuing a receipt. Matching duplicate events reconcile; conflicting source or
event bindings fail. Regrouped batches can reuse matching rows without treating
a different batch marker as the original commit.

The default namespace cap is 256 MiB, with bounded file enumeration, checks
before and after operations, and a conservative append reserve. This is a
namespace policy, not a measured memory limit or filesystem quota guarantee.
Local owner locks, process identity and catalog/data path identities are checked.
Full checkpoints, Arrow sidecars and weights remain in owner CAS; they are not
transferred into `DATA_PATH` or relabeled as managed Parquet files.

## Owner delivery and recovery

[`deliver_ducklake_history`](../../../ipfs_datasets_py/duckdb_control/autoencoder_ducklake.py)
connects the real registry owner to the isolated native sink. Each output
directory binds one durable journal to its batch, source, destination and
delivery settings. A new batch requires a new directory. The journal is bounded
to 8 MiB and 128 operation intents, persisting exact operation IDs and payloads
before owner mutations.

[`autoencoder_registry.py`](../../../ipfs_datasets_py/duckdb_control/autoencoder_registry.py)
adds three methods without a database migration:

- `get_outbox_event(consumer, event_id)` returns the exact original payload,
  kind and timestamp plus current status, lease and receipt, including
  acknowledged events.
- `claim_outbox_event(operation_id, event_id, consumer, worker_id,
  lease_seconds=300)` claims only the requested available event, preserving
  batch membership during recovery.
- `renew_outbox(operation_id, event_id, consumer, lease, lease_seconds=300)`
  requires the exact live lease and retains its worker and fence while changing
  expiry. Owner restart fences old leases.

Exact mutation replay returns the historical receipt before checking current
liveness; that receipt does not grant a live lease. Closed identifiers, unknown
event/consumer pairs, stale leases and same-ID/different-payload retries fail.
The journal resolves uncertain owner operations first. Lost append responses
use exact native commit lookup; partial acknowledgements recover only remaining
original members through targeted claims. Matching prior acknowledgements are
retained, and the native commit is reverified before each new acknowledgement.
Registry transactions do not span lake I/O or artifact hashing. Registry and
DuckLake commits remain separate transactions reconciled by this protocol.

## Offline full compact packages

[`autoencoder_release.py`](../../../ipfs_datasets_py/huggingface/autoencoder_release.py)
now accepts an exact canonical native **full float64 compact checkpoint**.
The new release schema is `autoencoder-exact-resume-private-release/v2`; the
package uses `autoencoder-private-local-package/v2` and `state.compact`.
Existing legacy JSON profile and package hashes remain unchanged.

The native loader verifies the original artifact, complete state, revision and
logical identity before packaging. Canonical native reserialization must
reproduce the original bytes. The package copies those bytes and records format,
schema and identities without changing numeric representation. Sparse manifests,
delta checkpoints and noncanonical or non-float64 compact inputs remain rejected.

The actual historical owner candidate was packaged twice in separate local
directories. Both retain the original 1,664,643-byte checkpoint, SHA-256
`dc133884a94e6a10cbbab41a9b9293428f970f668b392ffaa144dfa8932a45f6`.
Both reload all 38 raw native components, preserve the exact revision and
identities, and reproduce the compact bytes. Both package manifests have SHA-256
`2864c86af52016f14bd7b6b8d9e553fb45345ef05c9821e20468374e3a91d7b8`
and the same publication-plan digest. Repository
`review-owner/private-autoencoder` is a fixture placeholder, not an authorized
remote destination.

The [historical packaging receipt](../../../workspace/test-logs/federal-corpus-audits/autoencoder-compact-release-20260925/historical-compact-r1-receipt.json)
has SHA-256 `29747491be20d246192f68468e2fb896298d60a97c191ee4fdbab4771eb156f3`.
Protected source files remained unchanged. The candidate came from the earlier
zero-update native owner qualification and had zero accepted projection epochs;
packaging performed no fresh training or evaluation. Both packages record
`remote_write_contacted=false` and `upload_ready=false`. No upload, proof or new
model-quality result follows from these packages.

## Validation and remaining gates

| Evidence | Result and scope |
|---|---|
| [Registry focused receipt](../../../workspace/test-logs/federal-corpus-audits/autoencoder-ducklake-outbox-20260925/registry-r2-receipt.json) | 69 passed in 6.31 s pytest / 7.186 s wrapper; disposable real DuckDB files, including 34 new cases for exact events, lease fencing, response loss and partial-ack recovery; schema and DDL unchanged |
| [HF package tests](../../../tests/unit/huggingface/test_autoencoder_release.py) and related focused checks | Initial focused run: 93 passed in 51.06 s; offline compact/legacy compatibility and package validation; later source-stable combined evidence below |
| [Historical compact package receipt](../../../workspace/test-logs/federal-corpus-audits/autoencoder-compact-release-20260925/historical-compact-r1-receipt.json) | Passed; two deterministic packages of the existing candidate, all 38 components/revision/bytes exact; no new training or publication |
| [Native sink tests](../../../tests/unit/ducklake/test_autoencoder_history.py) | 57 passed in 10.71 s; real isolated DuckLake close/reopen, exact snapshot/event/marker checks, and bounded SIGKILL before/after commit recovery |
| [Consumer tests](../../../tests/unit/duckdb_control/test_autoencoder_ducklake.py) | 18 passed in 13.90 s; real registry/native sink delivery, lost-response and partial-ack recovery, including bounded SIGKILL followed by recovery from persisted files |
| [Combined r1](../../../workspace/test-logs/federal-corpus-audits/autoencoder-delivery-release-20260925/combined-r1-receipt.json) | Retained failed qualification: 556 passed, 1 failed in 164.74 s pytest / 167.121635 s wrapper; two package source files changed, while protected artifacts and test files remained unchanged |
| [Combined r2](../../../workspace/test-logs/federal-corpus-audits/autoencoder-delivery-release-20260925/combined-r2-receipt.json) | 558 passed across 14 test files in 167.97 s pytest / 170.354915 s wrapper; all 7,739 package Python sources, selected tests and protected artifacts unchanged; no fresh native training |

The retained combined r1 receipt has SHA-256
`a7c386c8867a2ef9e1f0d1c23255ae3208dc7d7c8914dafe52aa805576b5f06d`.
The wrapper set `HF_HUB_OFFLINE=1`; the installed Hub client consequently
mounted its `OfflineAdapter`, which the production publisher's strict canonical
session check correctly rejected in the custom-adapter test. The test-only
correction explicitly installs the standard backend for that cached-session
fixture, denies socket connections and clears cached sessions at teardown.
A separate regression confirms that the offline adapter is rejected; nine
focused checks pass under `HF_HUB_OFFLINE=1`. The production publisher guard
remains unchanged. Separately, the r1 full source capture detected changes in
`ipfs_datasets_py/logic/autoformal/supervisor_todo.py` and
`ipfs_datasets_py/logic/autoformal/autoencoder_router.py`. The failed qualification
remains evidence of that attempted run, not a combined success.

The subsequent combined r2 receipt has SHA-256
`d11d5037be56bb7d1ec3b4d7d8964fb9a07d58b4aab8726f68506c16e368e326`.
It passes the bounded storage/packaging regression with no failures or skips
and unchanged full package, selected-test and protected-artifact captures.
This includes actual isolated native storage fixtures, not a new daemon cycle,
training benchmark or production activation. Native training validation remains
deferred.

The first registry run's new test incorrectly expected `variant_id` inside the
original `version_registered` event. Its failure log remains retained; only the
test expectation was corrected. No production event was enriched to pass it.

Production namespace authorization, DQK capability/activation evidence and remote
Quack owner adaptation remain separate gates. HF still needs its production
outbox consumer, approved destination/visibility and authorized remote
commit/reconciliation workflow. A local private package supplies none of those
approvals. These storage checks establish no speedup, production activation,
held-out improvement or new Lean admission.
