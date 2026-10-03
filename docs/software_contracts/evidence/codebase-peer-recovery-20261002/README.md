# Durable local peer completion recovery

The final producers passed **12 native recovery cases in 102.37 seconds** and
**13 native transport regression cases in 44.91 seconds**, with no skips. Five
bounded-manifest controls and 19 neighboring queue dispatcher controls also
passed: **49 distinct controls**. Both native runs used the default host
scheduler and sampler, without injected telemetry or relaxed admission limits.
These are qualification durations on a shared development host, not benchmark
scores or a matched throughput comparison. No model provider calls were made.

An intermediate repeat of the 19 dispatcher cases matched the repository's
mandatory AST-seal cache and skipped execution. Those diagnostics are retained
separately and do not count as passes. The final 19-case run used a fresh isolated
seal database with mandatory sealing still enabled and executed every case.

The owner now persists a closed transport-population manifest under the native
registry's existing operation transaction before completing a federated model
run. After an actual native completion commits and its reply is deliberately
lost, an identical retry recovers the same registered candidate without fitting
again, starting a peer or moving a model head. Separate controls lose the final
sidecar write and its committed reply, then reconstruct the identical CID. A
new Python process reopens the native owners and recovers that CID with fitting
and peer delivery explicitly forbidden. Prepared-only manifests do not establish
completion; missing references, changed digests/fences/bodies and resealed source
or delivery populations are rejected. The manifest reader checks one bounded
regular descriptor, exact size and SHA-256 before parsing. FIFO, oversized-file,
file-symlink, directory-symlink and changed-body controls pass.

The repeated transport matrix retains exact native 8D FedAvg and optimizer reset,
two distinct sequential subprocess peers, actual lost peer-response restart with
numerical invocation counts 1 then 0, native duplicate delivery, SIGKILL rejection,
stale queue completion rejection and source/model/binary binding refusals. It
checks that all observed peer processes and owned leases have been reaped.

Each native policy exactly matches the 25 retained production sources, including
the final canonical CID implementation. Before/after source checks found no
drift. The package independently verifies retained CAS objects and model artifacts;
four test files are identified separately from production code. Native databases,
private peer configuration/cache, scheduler state and lease tokens are excluded.
The prepared registry receipt is not exported as a live capability. This archive
records successful executions; it is not a replacement for reopening and checking
the authoritative native owners during recovery.

The profile covers five authored source files, existing structural feature
autoencoding, sequential local MCP++ framed stdio and a shared immutable CAS.
It does not qualify remote/libp2p deployment, cross-host artifact transfer,
parallel fleet/device accounting, distributed 384D training, gradient collectives,
holdout generalization, semantic formalization accuracy or proof authority.

The earlier transport-only 13+19 qualification remains in the separate
`codebase-peer-transport-20261002` package with its original producer snapshots.
Its completed retry contract predates the durable population reference introduced
here. After the reboot, those source bytes were reconstructed from selected literal
patch records and checked against the retained native source policy before the
recovery additions were restored. All new work and raw runs are retained under
persistent workspace artifacts.
