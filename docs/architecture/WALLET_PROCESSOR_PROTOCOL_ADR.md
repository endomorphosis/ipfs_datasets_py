# ADR: Wallet-domain protocols and the generic processor adapter

- Status: accepted
- Date: 2026-07-28
- Owners: wallet-processors/contracts
- Objectives: WALPROC-G030, enables WALPROC-G040 and WALPROC-G600

## Context

Wallet processing is a read-only data-ingestion domain. It needs explicit
wallet and ledger sources, normalization, finality, checkpoints, dataset sinks,
exports, transport, and secret-reference boundaries. Those boundaries must
remain importable without optional chain SDKs and must carry finite item, page,
request, byte, cancellation, and deadline budgets.

The repository currently exposes two incompatible generic processor APIs:

1. `ipfs_datasets_py/processors/protocol.py` defines
   `ProcessorProtocol.can_process(input_source)` and
   `process(input_source, **options)`. It is used by legacy generic adapters and
   models document/media-style results.
2. `ipfs_datasets_py/processors/core/protocol.py` defines
   `ProcessorProtocol.can_handle(ProcessingContext)` and
   `process(ProcessingContext)`. Its context-aware async API is paired with the
   core `ProcessorRegistry` and `UniversalProcessor`.

Neither generic API expresses wallet-domain pagination, checkpoints, finality,
transactional sinks, or normalized ledger records. Implementing either shape
directly in every chain package would couple domain behavior to a generic
registry and would make the existing ambiguity permanent.

## Decision

`ipfs_datasets_py.processors.wallets.protocols` is the authoritative domain
boundary. It contains structural protocols for:

- `WalletProvider` and `LedgerProvider`;
- `ChainNormalizer` and `FinalityPolicy`;
- `CheckpointStore`, `DatasetSink`, and `Exporter`; and
- injected `HttpTransport` and `SecretResolver` I/O boundaries.

Every source operation receives a `BoundedRequest` containing an
`OperationContext`. The context supplies `RequestLimits`, cooperative
`CancellationToken`, and an optional timezone-aware deadline. Providers
advertise immutable `Capabilities`; consumers fail before I/O when a required
capability is absent. Batches account for item and response-byte use. Ledger
scans use an explicit range or another finite scope; retries and polling remain
outside these protocols and must also consume the request budget.

The contracts use opaque record objects by design. WALPROC-G040 supplies the
immutable, versioned record and manifest models without forcing this module to
import them, and concrete implementations narrow the annotations.

Wallet processors are data readers and exporters. Custody, transaction
construction, approval, signing, submission, and broadcast authority are
outside this package. `HttpTransport` accepts only an explicit request and
budget; `SecretResolver` accepts only an explicit opaque reference and returns
a redacted wrapper. Importing the module performs no discovery, network access,
secret resolution, client construction, or optional dependency import.

## Generic compatibility decision

WALPROC-G600 may add exactly one compatibility adapter, at:

`ipfs_datasets_py/processors/wallets/adapters/processor_protocol.py`

That adapter will target the context-aware
`ipfs_datasets_py.processors.core.protocol.ProcessorProtocol` surface:
`can_handle(ProcessingContext)` plus `process(ProcessingContext)`.

The choice is based on its async, context-carrying dispatch and its existing
pairing with the core registry and `UniversalProcessor`. The adapter must
translate a bounded generic `ProcessingContext` into wallet-domain requests and
return a generic result; it must not move domain logic into the registry.

No adapter to the legacy `can_process(input_source)` surface is permitted.
There will be no second wallet adapter, dual registration, fallback between the
two generic registries, or edits to either generic registry as part of this
decision. Chain packages implement only the domain protocols.

## Consequences

- Chain implementations can be tested with fakes and without chain SDKs.
- Normalized G040 models can be introduced without a protocol import cycle.
- Cancellation, deadlines, capabilities, and bounded reads are visible at each
  I/O boundary rather than hidden in provider configuration.
- Generic routing is deliberately deferred to WALPROC-G600, where one reviewed
  adapter can be tested as an integration boundary.
- Existing generic processors retain their current behavior and ownership.

## Rejected alternatives

### Adapt both generic APIs

Rejected because dual registration makes routing order observable, permits
different behavior for the same wallet request, and fails the one-adapter
ownership rule.

### Make chain packages implement a generic protocol directly

Rejected because both generic result shapes are document-oriented and omit
wallet checkpoints, finality, bounded streaming, and transactional sink
semantics.

### Select the legacy `can_process` API

Rejected because its bare source dispatch cannot carry the wallet operation's
scope, deadline, cancellation token, and resource limits without an
out-of-band convention.

### Resolve dependencies or discover providers at import time

Rejected because it makes import behavior environment- and network-dependent,
prevents fixture-only tests, and risks ambient credential use.

## Verification

`tests/unit/processors/wallets/test_protocols.py` proves structural conformance
with fake implementations, validates bounds/cancellation/deadlines and redacted
secrets, checks the public protocol surface for prohibited transaction
authority, and imports the module in an isolated interpreter without optional
network libraries.
