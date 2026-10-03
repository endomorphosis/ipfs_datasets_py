# Local peer federation

`codebase_peer_dispatched_federation.train_current_peer_dispatched_codebase_round`
runs the existing 8D source feature federation through one or two explicitly
mapped local peer profiles. Each delivery starts a separate Python process and
uses the existing MCP++ `initialize` / `tools/call` framed protocol over stdio.
The peers share the admitted immutable CAS. No socket, remote discovery,
libp2p deployment, external model provider, or distributed 384D training is
qualified by this profile.

Create `CodebasePeerWorker(cas, absolute_private_receipt_root,
profile_id="local-one")` from
`ipfs_accelerate_py.p2p_tasks.codebase_peer_transport`. Supply an exact mapping
from every source client ID to a distinct peer profile and receipt directory,
along with the existing source index, model registry, native TaskQueue,
source head, parent checkpoint, explicit clients and operation ID. The public
training API returns `artifact_cid` and an immutable peer sidecar. Historical
replay uses `load_peer_dispatched_codebase_round(..., artifact_cid=...)`.
When the final response or sidecar CID is lost, use
`codebase_peer_recovery.recover_peer_dispatched_codebase_round(..., run_id=...)`.
An identical current-source training retry also takes this recovery path after
the native registry has completed the round.

The controller owns queue claims and native model run fences. It observes the
source before and after execution and checks every work binding, exact
checkpoint, update SHA-256/CID, local numerical result, fixed diagnostic batch
and native reduction. The new peer policy is committed in the native round ID.
The existing local worker identity contract, checkpoint schema, private Adam
state and deterministic FedAvg/reset behavior remain unchanged.

Peer receipts record queue attempt, worker, request, task and result hashes,
profile, actual PID, native lease identifiers and pinned producer files. The
private inherited lease token is never retained in the public receipt. These
records describe transport custody; they do not certify numerical work, proof
truth, model admission, promotion or task completion. Historical receipt replay
does not assert that its processes or leases are still live.

The source owner reserves three CPU/process slots and 2,560 MiB by default:
1,024 MiB for controller/source checks, and 1,536 MiB for the peer plus its
1,024 MiB numerical child. All allocations descend from the same default
datasets host scheduler. The subprocess runner retains cancellation, absolute
deadlines, process reaping, bounded streams, filesystem limits and sampled
process-tree RSS. This is a cooperative, sampled CPU profile; aggregate hard
memory enforcement, GPU/per-device control and remote capacity accounting
remain outside its qualification. Deliveries are sequential, one per profile
at a time; each adapter retains at most 128 delivery receipts in memory.

An actual lost response can retry through the native queue: the peer restarts
and validates its immutable request receipt without another fit. Duplicate
completed queue delivery also returns the retained result. Terminated peers,
stale queue claims and changed source/model/artifact bindings refuse completion.
Before native model completion, the owner stages a closed immutable transport
population manifest in the existing registry artifact store and binds it with
the existing registry operation transaction. The deterministic operation joins
the source-bound round, exact parent, attempt and fence; its prepared receipt
does not itself establish completion. Recovery requires the native completion,
verifies this reference and all retained queue, source and numerical artifacts,
then republishes the exact sidecar. It does not launch peers, fit weights,
create model versions or move heads. Missing or corrupted evidence refuses;
no process evidence is synthesized. Earlier rounds lacking this pre-completion
reference still require their originally retained sidecar and producer bytes.
Remote/libp2p operation, parallel remote peers and
gradient collectives remain open; unsupported training modes fail without a
fallback to federation.

The native fixture is five authored scalar source files, two source clients,
one local development fit and one peer round. Its metrics are not holdout
generalization, throughput improvements, benchmark scores or security proofs.
See the [49-control recovery qualification](evidence/codebase-peer-recovery-20261002/README.md):
12 native completion/recovery cases, 13 native transport cases, five bounded
manifest controls and 19 queue dispatcher controls. Recovery includes a separate
cold process, identical sidecar reconstruction, and rejection of a prepared
population without native completion. The manifest reader rejects nonregular
files, aliases, oversized bodies and changed bytes before parsing.
The [earlier 32-control qualification](evidence/codebase-peer-transport-20261002/README.md)
preserves the original transport-only implementation and its exact source pins.
