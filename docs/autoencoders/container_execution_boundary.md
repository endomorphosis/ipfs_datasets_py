# Exact container execution observations

`autoencoder_container_boundary` connects a known container to two actual held
`BoundCgroup` objects and the existing `ipfs_accelerate_py` Linux process-scope
helpers. It performs no Docker mutation, resource admission, native release,
training, logic qualification or Lean admission. Its labels are exact caller
pins; they do not prove OCI confinement, a source capsule, or formal semantics.

The caller must already hold actual native authority, the source read lease,
and any surviving guardian/fence. Guard actual native authority immediately
before and after attestation and before releasing a productive worker barrier.
Retain native capacity until explicit drain, process reaping, namespace
quiescence and claim closeout complete. A dictionary or budget number cannot
replace those capabilities.

## Supported daemon and PID mapping

`DirectDockerPeer` retains a live caller-owned AF_UNIX stream connection to a
same-UID, non-world-writable daemon socket. Fresh SO_PEERCRED, process birth,
socket identity, executable identity and PID namespace observations must match
the original peer. The executable must be the exact caller-pinned absolute
`dockerd` path, root owned, regular, single link, and not group/world writable.
It is SHA256 checked with a 256 MiB byte bound; unchanged executable metadata
allows reuse of that digest, while live identity is checked again every time.

The direct daemon PID namespace must equal the scanner's `/proc/self/ns/pid`.
This is the supported mapping of Docker `State.Pid` into the scanner's `/proc`.
A proxy peer, another daemon PID namespace, PID reuse, a closed connection or
unknown identity fails closed. There is no guessed PID translation. A separate
mapping protocol would be required before supporting a daemon in another PID
namespace.

Use a dedicated idle peer connection, separate from Docker HTTP inspection.
A zero-timeout readiness check precedes any non-consuming peek, preserving
healthy idle sockets even when Python has a positive socket timeout. EOF or
unexpected queued response data refuses the dedicated-channel profile.

`ProcessSecurityAdapter` receives the actual imported `process_security`
module, its exact normalized absolute source path and SHA256. The source path
must have no symlink component; its single-link regular file is streamed with
a 2 MiB bound and checked for stable file and reopened path identity. Module
origin and all three helper function source filenames must match. Source checks
surround each helper call. The adapter performs no bare import or provider
identity substitution. Preserve the existing canonical-tree import pin and
full producer provenance checks in the caller.

## Attestation sequence

Construct the inert or paused container topology before binding the frozen
controller/worker trees; `BoundCgroup` never adopts new children implicitly.
Do not use Docker auto-remove: the original held worker must remain
addressable through quiescence. Docker/systemd can still remove a generated
container cgroup immediately after init exit; use a durable held worker parent
for that generated descendant. The native owner remains outside the worker.

```python
adapter = ProcessSecurityAdapter(
    actual_process_security_module,
    expected_path=exact_helper_source_path,
    expected_sha256=exact_helper_source_sha256,
)
peer = DirectDockerPeer(
    connected_daemon_socket,
    socket_path="/run/user/1000/docker.sock",
    expected_pid=observed_peer_pid,
    expected_start_time_ticks=observed_peer_birth,
    expected_executable="/usr/bin/dockerd",
    expected_executable_sha256=verified_dockerd_sha256,
)
bound = attest_container_execution(
    controller_scope, worker_scope,
    container_id=exact_64_hex_cid,
    container_name=exact_container_name,
    image_id=exact_sha256_image_id,
    source_sha256=source_digest,
    request_sha256=request_digest,
    nonce=unique_64_hex_nonce,
    docker_inspect=bounded_exact_cid_inspection,
    process_security=adapter,
    daemon_peer=peer,
    owner_pid=actual_native_owner_pid,
    native_memory_bytes=actual_native_budget_bytes,
    native_child_process_slots=actual_native_child_budget,
)
```

The inspection callable must use the same daemon as `peer`, a bounded timeout
and output size, and exact CID lookup. It returns a singleton Docker inspect
list. The module checks:

1. Fresh stable-controller/worker ancestry and aggregate usage constraints.
2. Exact CID, name, image ID and labels `ipfs_datasets.source_sha256`,
   `ipfs_datasets.request_sha256`, and `ipfs_datasets.nonce` (each 64 hex digits).
3. A live running or paused container with private PID mode. A zero PID,
   including after an executed container exits, cannot mint a binding.
4. Inspect → Linux scope capture → inspect → capture, with unchanged init PID,
   birth, boot, start timestamp, namespace, cgroup and state.
5. A private container PID namespace distinct from the scanner namespace, plus
   exact init membership in the original frozen worker subtree. Cgroup mount,
   directory and events device/inode pairs must match held identities.
6. Fresh daemon identity and controller/worker observations after capture.

These are sequential observations, not an atomic exclusion against hostile
same-UID migration. Runtime source custody, barriers, guardian lifetime,
container privilege/capability/network/mount policy, and any source capsule
validation remain explicit caller requirements.

## Cleanup and qualification

`bound.receipt()` returns a copy of historical evidence. It is not a fresh
admission decision or a constructor for live custody. `bound.quiescent()` is
true only when the existing helper establishes the original init is gone,
the original PID namespace and container cgroup are empty, and repeated held
worker observations establish the entire worker is empty. Unknown namespace
scans, changed ancestry, a closed binding, or worker repopulation return false.
The cleanup observation does not require the original root owner to survive;
the actual native guardian still controls release.

Cleanup uses `BoundCgroup.observe_cleanup()`, which revalidates the original
boot, mount, root, leaf and leaf control identities and reads original
hierarchical `cgroup.events` population twice. It intentionally makes no
process-inventory, resource-budget or productive-work decision. Deleted or new
descendants are not adopted for work: ordinary `observe()` still rejects any
changed frozen tree. A vanished generated container descendant can be closed
only when the existing helper establishes the original init is gone and its
private PID namespace is empty, and the durable worker parent is empty. A
new populated descendant keeps cleanup unresolved. A vanished/replaced worker,
root, mount or original control cannot produce a successful cleanup observation.

There is no release, destructor, context-manager cleanup, Docker remove or
implicit drain API. Even a true quiescence result releases no native resources
and reconciles no disk claim. Keep the original bindings until the guardian's
final stopped checks and explicit native release are complete; remove the
exact container only in the caller's positively bound cleanup protocol.

Private backend seams require explicit `simulation=True` and cannot be mixed
with real cgroup bindings. Simulated contract tests do not qualify Docker,
CUDA, an autoencoder, model semantics or Lean. A finite real-container probe
and its actual native evidence are separate acceptance materials. Only an
actual `lake build <Lib>` is a Lean admit; the Constitution remains unformalized.

The socket-timeout regression uses real anonymous socket pairs; FIFO descriptor
rejection uses an anonymous pipe. These checks create no filesystem socket or
FIFO and establish no daemon, container or native-resource qualification.
