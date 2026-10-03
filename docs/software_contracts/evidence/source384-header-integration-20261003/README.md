# Captured header adapter qualification

The actual on-disk new D adapter and integration test passed **22/22 controls in
33.29 seconds**, with no skips. The preceding off-tree run passed the same 22
cases in 32.60 seconds using a bootstrap for only the new module. These runs are
22 distinct controls, not 44. Both use the same final source and test bytes.

The exact public Bottle fixture and the authored module each produce two
modeled helpers, 12 deterministic formulas and six SMT obligations. Model loads,
learned formulas, provider calls, solver calls and training steps are zero. No
Lean compilation, solver discharge, source execution, whole-program proof,
checkpoint modification or benchmark score is claimed. The adapter is not yet
wired into Source384 or the supervisor.

Tests use real native DuckDB/CAS/catalog/source-observation owners with an
explicit isolated native scheduler and injected healthy/refusing telemetry.
This qualifies contract handling, not host-default resource admission. Tampering,
source drift, changed catalog head during publication, cancellation, deadline and
native resource failures retain refusal semantics. Unsupported modules remain
visible rather than being silently omitted.

See `qualification.json` for exact generation/claim boundaries and source pins.
`controls/actual-02-*` identifies the actual on-disk run; `controls/controls-01-*`
is the preceding off-tree generation. Control command paths and runner-relative
locations describe the original development machine; the copied runners are
provenance, not relocation-ready installers. A fresh checkout can run the test
normally with `python -m pytest tests/integration/logic/software_contracts/test_codebase_header_context.py`;
set `IPFS_DATASETS_PUBLIC_BOTTLE_FIXTURE` to the exact permitted public fixture to
include that optional case. Its expected SHA is pinned in the test and receipt.

The package contains only an explicit file allowlist: producer/test snapshots,
small commands/results/logs, bootstrap scripts and metadata. It contains no raw
benchmark source, model weights, database, CAS tree, authentication data or
runtime archive. The public Bottle source is represented only by its hash and
existing evidence provenance. See the maintained
[usage document](../../CAPTURED_HEADER_CONTEXT.md) for the three API contracts.
