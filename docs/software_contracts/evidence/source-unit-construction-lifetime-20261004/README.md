# Release completed Source384 construction graphs

After the numerical worker returns, its caller releases the input payload and
checkpoint before validating output and requesting the next source fence.
Once the inference artifact is committed, output/receipt/construction graphs
are released before the independent saved-report load. Warm replay releases
its initial checkpoint and preparation too. Every source fence, output and
model binding check, publication order, resource reservation and deadline stays
in place. No garbage-collector or allocator-trim intervention is introduced.

Three authored weak-reference lifetime checks fail before the patch and pass
afterwards. All 17 lifetime/guard controls pass, including four source refusals,
invalid output, model drift, corrupt replay and cancellation. These controlled
object-lifetime assertions are not RSS measurements or a causal Docker diagnosis.

Seven actual checkpoint/source-unit tests pass with cached GTE and the unchanged
SecurityIR checkpoint. The test executes numerical inference once, defers the
overlength unit, reopens committed storage for model-free replay, and rejects
tampered bindings and changed source. There are no provider calls. The original
host invocation mixed parent package paths with an isolated child's site paths
and correctly failed runtime-version validation (six passes, one failure).
The corrected runner uses the same site packages on both sides; no runtime
version check was weakened. Both attempts are retained. Native host resource
sampling uses a fresh local scheduler ledger without modifying a foreign owner.

The 24 passing tests qualify the component change. A separate new archive and
ordinary Docker run are required for container qualification and any later task
score. Prior Docker failures and their admission observations remain separate.
