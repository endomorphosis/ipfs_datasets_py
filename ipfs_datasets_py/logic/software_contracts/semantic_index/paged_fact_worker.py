"""Source/import-bound entry point using the existing per-file analyzer."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import importlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import time

from ..content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured
from . import streaming_scanner as streaming
from .paged_fact_store import PagedFactError

SCHEMA = "ipfs-datasets.paged-raw-fact-worker@1"
DEPENDENCIES = ("multiformats", "multiformats_config", "bases", "typing_validation", "typing_extensions")


def _file_hash(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 32 * 1024 * 1024:
            raise PagedFactError("implementation_file_shape")
        digest, total = hashlib.sha256(), 0
        while data := os.read(fd, min(65536, before.st_size + 1 - total)):
            total += len(data)
            if total > before.st_size:
                raise PagedFactError("implementation_changed_during_read")
            digest.update(data)
        after, named = os.fstat(fd), path.lstat()
        if (total != before.st_size or not stat.S_ISREG(named.st_mode) or
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or
                (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino)):
            raise PagedFactError("implementation_changed_during_read")
        return digest.hexdigest(), total
    finally:
        os.close(fd)


def _bounded_tree(root, counter):
    """Refuse during enumeration, before materializing an unbounded tree."""
    pending, result = [root], []
    while pending:
        directory = pending.pop()
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(fd)
            with os.scandir(fd) as entries:
                for entry in entries:
                    counter[0] += 1
                    if counter[0] > 8192:
                        raise PagedFactError("implementation_enumeration_bound")
                    if entry.is_symlink():
                        raise PagedFactError("implementation_tree_symlink")
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name != "__pycache__":
                            pending.append(directory / entry.name)
                    elif entry.is_file(follow_symlinks=False):
                        result.append(directory / entry.name)
                    else:
                        raise PagedFactError("implementation_file_shape")
            after, named = os.fstat(fd), directory.lstat()
            if (not stat.S_ISDIR(named.st_mode) or (before.st_dev, before.st_ino, before.st_mtime_ns) !=
                    (after.st_dev, after.st_ino, after.st_mtime_ns) or
                    (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino)):
                raise PagedFactError("implementation_tree_changed")
        finally:
            os.close(fd)
    return sorted(result)


def implementation_profile():
    """Bind trusted source trees, dependency data, import origins and interpreter.

    Child and parent independently recompute this same bounded descriptor.
    Target repository paths are never added to import search paths.
    """
    cid_for_bytes(b"")  # load the exact CID backend before validating origins
    package = Path(__file__).resolve().parents[1]
    roots = {"software_contracts": package}
    for name in DEPENDENCIES:
        module = importlib.import_module(name)
        file = Path(module.__file__).resolve(strict=True)
        roots[name] = file if name == "typing_extensions" else file.parent
    files, total, enumerated = {}, 0, [0]
    for name, root in roots.items():
        entries = (root,) if root.is_file() else _bounded_tree(root, enumerated)
        for path in entries:
            if path.is_dir() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            if name == "software_contracts" and path.suffix != ".py":
                continue
            digest, size = _file_hash(path)
            total += size
            if len(files) >= 4096 or total > 64 * 1024 * 1024:
                raise PagedFactError("implementation_manifest_bound")
            files[name + "/" + (path.name if root.is_file() else str(path.relative_to(root)))] = digest
    # Package initializers outside software_contracts also execute on import.
    for file in (package.parent / "__init__.py", package.parent.parent / "__init__.py"):
        if file.exists():
            digest, size = _file_hash(file)
            files[str(file)] = digest
            total += size
        else:
            files[str(file)] = "namespace-package-no-initializer"
    if len(files) > 4096 or total > 64 * 1024 * 1024:
        raise PagedFactError("implementation_manifest_bound")
    for name, module in tuple(sys.modules.items()):
        prefix = "ipfs_datasets_py.logic.software_contracts"
        root_name = ("software_contracts" if name == prefix or name.startswith(prefix + ".") else
                     next((dep for dep in DEPENDENCIES if name == dep or name.startswith(dep + ".")), None))
        if root_name is None:
            continue
        actual = getattr(module, "__file__", None)
        if actual is None:
            raise PagedFactError("implementation_import_origin")
        actual = Path(actual).resolve(strict=True)
        root = roots[root_name]
        if (root.is_file() and actual != root) or (root.is_dir() and not actual.is_relative_to(root)):
            raise PagedFactError("implementation_import_origin")
        if actual.suffix != ".py":
            raise PagedFactError("implementation_import_type")
    executable = Path(sys.executable).resolve(strict=True)
    executable_hash, _ = _file_hash(executable)
    return {"schema": "ipfs-datasets.paged-raw-fact-implementation@1",
            "source_manifest_cid": cid_for_structured(files), "source_file_count": len(files),
            "source_bytes": total, "roots": {name: str(root) for name, root in roots.items()},
            "python_executable": str(executable), "python_sha256": executable_hash,
            "python_version": list(sys.version_info[:3]), "python_implementation": sys.implementation.name,
            "analysis_process": streaming.analysis_process_profile(),
            "target_imports": False, "source_execution": False}


def _command():
    import multiformats
    launcher = (
        "import resource,sys; "
        f"resource.setrlimit(resource.RLIMIT_AS,({streaming.WORKER_ADDRESS_BYTES},{streaming.WORKER_ADDRESS_BYTES})); "
        f"resource.setrlimit(resource.RLIMIT_CPU,({streaming.WORKER_CPU_SECONDS},{streaming.WORKER_CPU_SECONDS})); "
        "resource.setrlimit(resource.RLIMIT_CORE,(0,0)); "
        "sys.path.insert(0,sys.argv[2]); sys.path.insert(0,sys.argv[1]); "
        "from ipfs_datasets_py.logic.software_contracts.semantic_index.paged_fact_worker import _main; _main()"
    )
    return [sys.executable, "-I", "-B", "-c", launcher, str(Path(__file__).resolve().parents[4]),
            str(Path(multiformats.__file__).resolve().parents[1])]


def run_file_worker(header, raw, limits, profile):
    """Own bounded pipes, kernel-limited child, timeout, and exact profile reply."""
    header = {**header, "limits": asdict(limits), "size_bytes": len(raw),
              "implementation_cid": cid_for_structured(profile)}
    wire_header = canonical_dag_json_bytes(header)
    if len(wire_header) > 4096 or len(raw) > streaming.MAX_MATERIALIZED_FILE_BYTES:
        raise PagedFactError("worker_input_limit", stage="analysis")
    wire = wire_header + b"\n" + raw
    env = {key: value for key, value in os.environ.items() if not key.startswith(("PYTHON", "GIT_"))}
    env.update(IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS="0", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    child = subprocess.Popen(_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             start_new_session=True, env=env)
    deadline, offset = time.monotonic() + limits.worker_timeout_seconds, 0
    output, errors = bytearray(), bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            for stream, name, mode in ((child.stdin, "in", selectors.EVENT_WRITE),
                                       (child.stdout, "out", selectors.EVENT_READ),
                                       (child.stderr, "err", selectors.EVENT_READ)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, mode, name)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PagedFactError("worker_timeout", stage="analysis")
                for key, _ in selector.select(min(remaining, .1)):
                    stream = key.fileobj
                    if key.data == "in":
                        try:
                            offset += os.write(stream.fileno(), memoryview(wire)[offset:offset + 65536])
                        except BrokenPipeError:
                            offset = len(wire)
                        if offset == len(wire):
                            selector.unregister(stream)
                            stream.close()
                    else:
                        piece = os.read(stream.fileno(), 65536)
                        if not piece:
                            selector.unregister(stream)
                            continue
                        target, bound = (output, limits.max_file_fact_bytes + 4096) if key.data == "out" else (errors, 8192)
                        if len(target) + len(piece) > bound:
                            raise PagedFactError("worker_output_limit", stage="analysis", limit=bound)
                        target.extend(piece)
        try:
            child.wait(timeout=max(.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise PagedFactError("worker_timeout", stage="analysis") from exc
        if child.returncode or errors:
            raise PagedFactError("worker_process_refusal", stage="analysis", observed=child.returncode)
        try:
            result = json.loads(output)
            if canonical_dag_json_bytes(result) != output or result.get("schema") != SCHEMA:
                raise ValueError("invalid reply")
            if "error" in result:
                raise PagedFactError(result["error"], stage="analysis")
            if (set(result) != {"schema", "facts", "implementation_cid", "resources"} or
                    result["implementation_cid"] != header["implementation_cid"]):
                raise ValueError("changed reply")
            resources = result["resources"]
            if (resources["address_space_limit_bytes"] != streaming.WORKER_ADDRESS_BYTES or
                    resources["cpu_limit_seconds"] != streaming.WORKER_CPU_SECONDS):
                raise ValueError("changed worker limits")
        except (ValueError, TypeError, KeyError) as exc:
            if isinstance(exc, PagedFactError):
                raise
            raise PagedFactError("invalid_worker_reply", stage="analysis") from exc
        return result["facts"], resources
    finally:
        if child.returncode is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()


def _main():
    import resource
    try:
        header = json.loads(sys.stdin.buffer.readline(4097))
        profile = implementation_profile()
        if cid_for_structured(profile) != header["implementation_cid"]:
            raise PagedFactError("implementation_profile_changed")
        limits = streaming.StreamingScanLimits(**header["limits"])
        size = header["size_bytes"]
        if type(size) is not int or not 0 <= size <= streaming.MAX_MATERIALIZED_FILE_BYTES:
            raise PagedFactError("worker_input_limit")
        raw = sys.stdin.buffer.read(size + 1)
        if len(raw) != size:
            raise PagedFactError("worker_input_size")
        facts = streaming._analyze_one(raw, header, limits)
        if implementation_profile() != profile:
            raise PagedFactError("implementation_profile_changed")
        result = {"schema": SCHEMA, "facts": facts, "implementation_cid": header["implementation_cid"],
                  "resources": {"peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                                "address_space_limit_bytes": resource.getrlimit(resource.RLIMIT_AS)[0],
                                "cpu_limit_seconds": resource.getrlimit(resource.RLIMIT_CPU)[0]}}
    except (PagedFactError, streaming.StreamingAnalysisError) as exc:
        result = {"schema": SCHEMA, "error": exc.code}
    except Exception as exc:
        result = {"schema": SCHEMA, "error": "worker_failure_" + type(exc).__name__}
    sys.stdout.buffer.write(canonical_dag_json_bytes(result))
