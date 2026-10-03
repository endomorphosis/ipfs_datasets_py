"""Private one-delivery local MCP++ peer. Not a remote listener or registry owner."""
from __future__ import annotations


def main():
    import asyncio
    from contextlib import redirect_stdout
    import json
    import os
    from pathlib import Path
    import sys
    import time
    # Bootstrap only explicit installed/released roots supplied by the owner.
    roots = json.loads(sys.argv[1])
    if type(roots) is not list or not 1 <= len(roots) <= 8 or any(type(p) is not str or not Path(p).is_absolute() or not Path(p).is_dir() for p in roots):
        raise ValueError("explicit installed module roots required")
    sys.path[:0] = roots
    output = sys.stdout.buffer
    with redirect_stdout(sys.stderr):
        from ipfs_accelerate_py.p2p_tasks import codebase_peer_transport as peer
        from ipfs_accelerate_py.p2p_tasks.mcp_p2p import handle_mcp_p2p_stream
        from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
        from ipfs_datasets_py.logic.software_contracts.codebase_federated_artifacts import CodebaseFederatedArtifactWorker, codebase_artifact_implementation
        from ipfs_datasets_py.logic.software_contracts.codebase_source_training import CodebaseFeatureTrainingLimits
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLeaseToken, ResourceLane, get_global_resource_scheduler
        raw = Path(sys.argv[2]).read_bytes()
        peer._require(len(raw) <= peer.MAX_FRAME, "bounded peer configuration required")
        config = json.loads(raw)
        peer._require(set(config) == {"schema", "profile_id", "nonce", "messages_sha256", "task_sha256", "implementation",
                      "artifact_implementation", "artifacts", "max_object_bytes", "receipt_root", "parent_token",
                      "deadline_unix_s", "memory_mb", "limits"}
                      and config["schema"] == peer.SCHEMA and config["implementation"] == peer.pins()
                      and config["artifact_implementation"] == codebase_artifact_implementation(), "peer producer pins differ")
        incoming = sys.stdin.buffer.read(2 * peer.MAX_FRAME + 9)
        requests = peer.frames(incoming)
        peer._require(len(requests) == 2 and peer._sha(requests) == config["messages_sha256"], "peer request stream differs")
        task = requests[1]["params"]["arguments"]["task"]
        peer._require(peer.messages(task, config["profile_id"], config["nonce"]) == requests
                      and peer._sha(task) == config["task_sha256"], "peer task/context differs")
        scheduler = get_global_resource_scheduler()
        token = ResourceLeaseToken(**config["parent_token"])
        peer._require(str(scheduler.state_path) == token.state_path, "peer may use only the inherited default host authority")
        def remaining():
            seconds = min(config["deadline_unix_s"], task["dispatch"]["deadline_unix_s"]) - time.time()
            peer._require(seconds > 0, "peer deadline exceeded")
            return seconds
        with scheduler.acquire(ResourceLane.TRAINER, cpu_slots=2, memory_mb=config["memory_mb"] + 512,
                child_process_slots=2, parent_lease=token, timeout=remaining(),
                request_id="codebase-peer-process:" + config["profile_id"]) as lease:
            signal = lease.combined_cancellation_signal(None)
            artifacts = ImmutableCAS(config["artifacts"], max_object_bytes=config["max_object_bytes"])
            bounds = CodebaseFeatureTrainingLimits(**config["limits"])
            worker = CodebaseFederatedArtifactWorker(artifacts, config["receipt_root"], limits=bounds)
            def call(*, task, nonce):
                peer._require(nonce == config["nonce"] and peer._sha(task) == config["task_sha256"], "peer tool custody mismatch")
                with worker.execution_context(parent_lease=lease, cancel_event=signal, remaining=remaining,
                        memory_mb=config["memory_mb"], limits=bounds):
                    try:
                        result = worker(task)
                    except Exception as error:
                        print(type(error).__name__ + ": " + str(error)[:1024], file=sys.stderr)
                        raise
                peer._require(peer.pins() == config["implementation"], "peer implementation changed")
                return {"schema": peer.SCHEMA, "profile_id": config["profile_id"], "nonce": nonce,
                    "task_sha256": peer._sha(task), "peer_pid": os.getpid(), "peer_lease_id": lease.lease_id,
                    "numerical_invocations": worker.numerical_invocations, "result": result,
                    "implementation": peer.pins(), "authority": dict(peer.FALSE)}
            class Registry:
                tools = {peer.TOOL: {"function": call}}
                _unified_supported_profiles = ["mcp++/p2p-transport"]
                @staticmethod
                def validate_p2p_message(message):
                    return message in requests
            class Stream:
                offset = 0
                async def read(self, size):
                    value = incoming[self.offset:self.offset + size]
                    self.offset += len(value)
                    return value
                async def write(self, value):
                    output.write(value)
                    output.flush()
                async def close(self):
                    pass
            asyncio.run(handle_mcp_p2p_stream(Stream(), local_peer_id=config["profile_id"], registry=Registry(),
                                            max_frame_bytes=peer.MAX_FRAME))


if __name__ == "__main__":
    main()
