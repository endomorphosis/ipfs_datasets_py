# Native source-bound 8D federation qualification

The local source-feature federation profile passes all 12 native integration
cases using the unchanged supervisor resource bridge and actual shared host
admission. The run took 155.00 seconds and retained 34 resource observations.
The [qualification record](evidence/codebase-federation-native-20261002/qualification.json)
contains exact source hashes, commands, worker/owner receipts, telemetry and the
preceding failed attempt. Existing implementation details remain in
[the source federation guide](CODEBASE_SOURCE_FEDERATION.md).

Five captured scalar Python files supply three training examples, one tuning
example and one fixed canary. Two local clients have one and two training rows.
Real numerical subprocesses produce binary parameter updates; the native owner
reconstructs the sample-weighted aggregate and resets its Adam moments. The
parallel run observes two subprocesses alive together and produces the exact
same aggregate state as the sequential run. Cancellation reaps both subprocesses
before parent release. Queue restart uses its exact request index without a full
queue scan or another fit.

Independent retention recomputes the candidate, parent and origin weights before
native expected-parent promotion. The fixed canary reconstruction MSE moves from
0.03312754 to 0.03167436; training replay MSE moves from 0.03284428 to 0.03143454.
Those are development retention observations, not unseen holdout performance.
Caller-supplied favorable metrics, missing parent artifacts, stale source and
stale parent head all refuse. A lost committed queue reply recovers without a
second local optimizer run.

The first admitted run exposed an execution-geometry mismatch: the worker
inferred the combined canary/replay population of four rows, while validation
recomputed the canary alone. CPU float64 GEMM rounded 38 values differently by
at most 4.16e-17. Exact comparison correctly refused them. The diagnostic now
replays the complete ordered batch derived from native lineage and checks the
exact selected target slice. Exact numerical equality, source/contract/state
bindings and authority checks remain intact; no tolerance was increased.
Forty additional component/protocol tests pass, including real joined inference,
wrong-slice refusal and self-consistent forged outputs. These component tests
use an explicitly injected scan resource sampler; the separate 12-case suite
uses actual default admission.

This qualification covers a local 8D structural-feature profile. It does not
qualify the 384D semantic decoders, remote machines, unavailable remote peers,
Hugging Face uploads, coordinate-sparsity savings or a throughput speedup.
Gradient synchronization remains unavailable and is refused before owner access.
Transport receipts do not grant proof authority. Prior pinned source bodies and
failed numerical evidence remain historical; the successful run creates a fresh
lineage under the corrected producer hashes.
