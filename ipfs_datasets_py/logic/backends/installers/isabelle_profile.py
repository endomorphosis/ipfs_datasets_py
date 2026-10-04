"""Shared installed-Isabelle launch policy, without discovery subprocesses.

Installed executables, heaps and transitive libraries are owner-controlled trusted
tools. Selected file digests record identity, not authenticity. This module does
not install tools or confer proof authority; callers retain their own exact
command/source and semantic acceptance checks.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from dataclasses import replace

from ..process import ToolRunRequest
from ....optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLease

PROFILE = "isabelle-installed-native-profile@1"
CPU_SLOTS = 3
PROCESS_SLOTS = 12
OVERHEAD_MB = 256
ADDRESS_SPACE_BYTES = 32 * 1024**3
MAX_INPUT_BYTES = 1024**2
MAX_WORKSPACE_BYTES = 64 * 1024**2
BOOTSTRAP_JAVA_OPTIONS = (
    "-XX:ActiveProcessorCount=1 -XX:+UseSerialGC -Xms16m -Xmx256m -Xss2m "
    "-XX:MaxMetaspaceSize=256m -XX:ReservedCodeCacheSize=128m -XX:-UsePerfData"
)


def regular_bytes(path: Path, limit: int, checkpoint) -> bytes:
    """Bound regular-file reads, including a FIFO or growth after opening."""
    checkpoint()
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("native runtime input must be a regular file")
        if info.st_size > limit:
            raise ValueError("native runtime input exceeds byte bound")
        result = bytearray()
        while True:
            checkpoint()
            block = stream.read(min(64 * 1024, limit - len(result) + 1))
            checkpoint()
            if not block:
                return bytes(result)
            result.extend(block)
            if len(result) > limit:
                raise ValueError("native runtime input exceeds byte bound")


def resolve_runtime(*, checkpoint, install_root=None, executable=None):
    """Select a managed or explicitly selected distribution without a probe.

    An explicit root can be the distribution itself, its installer transaction
    directory, or the managed store. An outer ``bin/isabelle`` wrapper resolves
    to its pinned inner distribution, without executing or parsing the wrapper.
    A malformed explicit selection never falls back to the user's default store.
    """
    from . import isabelle

    if install_root is not None and executable is not None:
        raise ValueError("supply only install_root or executable")
    checkpoint()
    version = isabelle.ISABELLE_VERSION
    if executable is not None:
        selected = Path(executable).expanduser().absolute()
        # Reject special files before resolving links or interpreting a layout.
        if selected.is_symlink():
            selected = selected.resolve(strict=True)
        regular_bytes(selected, MAX_INPUT_BYTES, checkpoint)
        if selected.name != "isabelle" or selected.parent.name != "bin":
            raise ValueError("explicit Isabelle executable must belong to a distribution bin directory")
        base = selected.parent.parent
    elif install_root is not None:
        base = Path(install_root).expanduser().absolute()
    else:
        base = isabelle.expand_user_local_root()
    candidates = (base, base / version,
                  base / f"{version}-{isabelle.detect_platform_key()}" / version)
    root = next((candidate for candidate in candidates
                 if os.path.lexists(candidate / "etc/ISABELLE_IDENTIFIER")), None)
    if root is None:
        raise FileNotFoundError("supported installed Isabelle distribution is missing")
    root = root.resolve(strict=True)
    identifier = regular_bytes(root / "etc/ISABELLE_IDENTIFIER", 256, checkpoint).decode().strip()
    if identifier != version:
        raise ValueError("installed Isabelle identifier differs from supported release")
    launcher = root / "bin/isabelle"
    files = ("bin/isabelle", "etc/ISABELLE_IDENTIFIER", "etc/settings", "etc/components", "lib/scripts/getsettings")
    hashes = {name: hashlib.sha256(regular_bytes(root / name, MAX_INPUT_BYTES, checkpoint)).hexdigest()
              for name in files}
    if not os.access(launcher, os.X_OK):
        raise ValueError("installed Isabelle launcher is not executable")
    return str(launcher), {
        "version": version, "runtime_root": str(root), "executable": str(launcher),
        "selected_file_sha256": hashes,
        "dependency_scope": "Selected launcher/configuration identities only; the installed HOL/Pure heaps, components, JVM, Poly/ML and native libraries are trusted, not fully attested.",
    }


def private_settings(memory_mb: int) -> str:
    ml_heap = min(1024, memory_mb // 2)
    return ('ISABELLE_JAVA_SYSTEM_OPTIONS="-server -Dfile.encoding=UTF-8 '
            '-Disabelle.threads=1 -XX:+UseSerialGC -XX:ActiveProcessorCount=1"\n'
            'ISABELLE_TOOL_JAVA_OPTIONS="-Djava.awt.headless=true -Xms64m -Xmx256m -Xss2m"\n'
            f'ML_OPTIONS="--minheap 256 --maxheap {ml_heap} --gcthreads 1 --stackspace 256"\n'
            'ISABELLE_TMP_PREFIX="$TMPDIR/isabelle"\n')


def settings_files(version: str, memory_mb: int) -> dict[str, str]:
    settings = private_settings(memory_mb)
    return {".isabelle/etc/settings": settings, f".isabelle/{version}/etc/settings": settings}


def run_admitted_phase(request: ToolRunRequest, *, parent_lease: ResourceLease,
                       version: str, memory_mb: int, remaining, cancellation,
                       run, phase: str, environment=None):
    """Run one internal typed request under a fresh actual child reservation.

    ``run`` is the owning adapter's native runner, never a public readiness API
    input. The owner still validates exact commands, generated source and results.
    Every phase rechecks pressure and cancellation through native admission.
    """
    if not isinstance(parent_lease, ResourceLease):
        raise TypeError("actual datasets parent lease required")
    if (parent_lease.owner_pid != os.getpid() or parent_lease.released
            or parent_lease.cpu_slots < CPU_SLOTS or parent_lease.child_process_slots < PROCESS_SLOTS
            or parent_lease.memory_mb < memory_mb + OVERHEAD_MB):
        raise ValueError("Isabelle parent cannot contain the native profile")
    with parent_lease.acquire_child(
        lane="validation", cpu_slots=CPU_SLOTS, memory_mb=memory_mb,
        child_process_slots=PROCESS_SLOTS, timeout=remaining(), cancel_event=cancellation,
        request_id="isabelle:" + phase,
    ) as child:
        wall = min(request.limits.timeout_seconds, remaining())
        inputs = {**request.input_files, **settings_files(version, memory_mb)}
        bounded = replace(request, input_files=inputs,
            limits=replace(request.limits, timeout_seconds=wall, cpu_seconds=wall,
                memory_bytes=ADDRESS_SPACE_BYTES, resident_memory_bytes=memory_mb * 1024**2,
                max_input_bytes=MAX_INPUT_BYTES, max_workspace_bytes=MAX_WORKSPACE_BYTES),
            environment={**{key: value for key, value in (environment or {}).items()
                           if key not in {"JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"}},
                         "JDK_JAVA_OPTIONS": BOOTSTRAP_JAVA_OPTIONS})
        observed = run(bounded, cancellation=child.combined_cancellation_signal(cancellation))
        phase_record = {
            "phase": phase, "child_lease_id": child.lease_id,
            "command": list(bounded.argv), "timeout_seconds": wall,
            "input_sha256": {name: hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()
                             for name, value in bounded.input_files.items()},
            "observation": observed.to_dict(),
        }
    return observed, phase_record


__all__ = ["PROFILE", "CPU_SLOTS", "PROCESS_SLOTS", "OVERHEAD_MB", "ADDRESS_SPACE_BYTES",
           "BOOTSTRAP_JAVA_OPTIONS", "MAX_INPUT_BYTES", "MAX_WORKSPACE_BYTES",
           "regular_bytes", "resolve_runtime", "private_settings", "settings_files", "run_admitted_phase"]
