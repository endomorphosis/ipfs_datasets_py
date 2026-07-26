"""Source-safe subprocess tests for the G240 Landlock boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from benchmarks.logic_pipeline import runtime_confinement
from benchmarks.logic_pipeline.runtime_confinement import (
    G240_LANDLOCK_HANDLED_ACCESS_FS_V1,
    G240_LANDLOCK_HANDLED_ACCESS_NET_V1,
    G240_LANDLOCK_RESTRICT_SELF_FLAGS_V1,
    G240_LANDLOCK_SCOPED_V1,
    G240_MAXIMUM_KNOWN_LANDLOCK_ABI,
    G240_MINIMUM_LANDLOCK_ABI,
    G240LandlockConfinementError,
    G240LandlockPolicyV1,
    G240LandlockReceiptV1,
    apply_g240_landlock_confinement,
    build_g240_landlock_policy_v1,
    make_g240_landlock_preexec,
    probe_landlock_abi,
    probe_landlock_errata,
    validate_g240_landlock_policy_v1,
    validate_g240_landlock_receipt_v1,
)


def _private_directory(path: Path) -> Path:
    path.mkdir()
    path.chmod(0o700)
    return path


def _listening_socket() -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    return listener


def test_public_policy_and_receipt_are_path_free_cid_records(
    tmp_path: Path,
) -> None:
    read_only = _private_directory(tmp_path / "read-only")
    (read_only / "allowed.txt").write_text("allowed", encoding="utf-8")
    state = _private_directory(tmp_path / "state")
    output = _private_directory(tmp_path / "output")
    cache = _private_directory(tmp_path / "cache")
    sources = build_g240_landlock_policy_v1(
        read_only_paths=(read_only,),
        state_path=state,
        output_path=output,
        cache_paths=(cache,),
        approved_tcp_ports=(8080, 19001),
    )

    restored = validate_g240_landlock_policy_v1(
        sources.policy.to_dict()
    )
    assert restored == sources.policy
    assert restored.read_only_path_count == 1
    assert restored.read_write_path_count == 3
    assert restored.approved_tcp_port_count == 2
    assert (
        G240_MINIMUM_LANDLOCK_ABI
        <= restored.expected_landlock_abi
        <= G240_MAXIMUM_KNOWN_LANDLOCK_ABI
    )
    assert restored.expected_landlock_errata == probe_landlock_errata()
    assert restored.device_ioctl_restricted is True
    assert restored.tcp_bind_restricted is True
    assert restored.tcp_connect_port_restricted is True
    assert restored.abstract_unix_socket_scoped is True
    assert restored.signal_scoped is True
    assert restored.tcp_address_authenticated is False
    serialized = json.dumps(restored.to_dict(), sort_keys=True)
    for path in (read_only, state, output, cache, tmp_path):
        assert path.as_posix() not in serialized
    assert "8080" not in serialized
    assert "19001" not in serialized
    assert "absolute_path" not in serialized
    assert "approved_tcp_ports" not in serialized
    assert "read_only_paths" not in serialized
    assert "read_write_paths" not in serialized
    assert read_only.as_posix() not in repr(sources)

    receipt = G240LandlockReceiptV1(
        policy_cid=str(restored.policy_cid),
        observed_landlock_abi=restored.expected_landlock_abi,
        observed_landlock_errata=restored.expected_landlock_errata,
        handled_access_fs=G240_LANDLOCK_HANDLED_ACCESS_FS_V1,
        handled_access_net=G240_LANDLOCK_HANDLED_ACCESS_NET_V1,
        scoped=G240_LANDLOCK_SCOPED_V1,
        restrict_self_flags=G240_LANDLOCK_RESTRICT_SELF_FLAGS_V1,
        read_only_path_set_cid=restored.read_only_path_set_cid,
        read_only_rule_count=restored.read_only_path_count,
        read_write_path_set_cid=restored.read_write_path_set_cid,
        read_write_rule_count=restored.read_write_path_count,
        state_path_cid=restored.state_path_cid,
        output_path_cid=restored.output_path_cid,
        cache_path_set_cid=restored.cache_path_set_cid,
        cache_rule_count=restored.cache_path_count,
        approved_tcp_port_set_cid=restored.approved_tcp_port_set_cid,
        approved_tcp_port_rule_count=(
            restored.approved_tcp_port_count
        ),
        no_new_privs_set=True,
        filesystem_rules_enforced=True,
        device_ioctl_restricted=True,
        tcp_bind_restricted=True,
        tcp_connect_port_rules_enforced=True,
        abstract_unix_socket_scoped=True,
        signal_scoped=True,
        tcp_address_authenticated=False,
        ruleset_applied=True,
    )
    replayed = validate_g240_landlock_receipt_v1(
        receipt.to_dict(),
        expected_policy=restored,
    )
    assert replayed == receipt
    receipt_json = json.dumps(replayed.to_dict(), sort_keys=True)
    assert tmp_path.as_posix() not in receipt_json
    assert "8080" not in receipt_json
    assert "19001" not in receipt_json
    with pytest.raises(
        G240LandlockConfinementError,
        match="does not prove required enforcement",
    ):
        G240LandlockReceiptV1(
            **{
                **receipt.identity_payload(),
                "ruleset_applied": False,
            }
        )


def test_policy_rejects_symlinks_and_write_ancestor_of_read_only(
    tmp_path: Path,
) -> None:
    real_read = _private_directory(tmp_path / "real-read")
    link = tmp_path / "read-link"
    link.symlink_to(real_read, target_is_directory=True)
    state = _private_directory(tmp_path / "state")
    output = _private_directory(tmp_path / "output")
    cache = _private_directory(tmp_path / "cache")
    with pytest.raises(
        G240LandlockConfinementError,
        match="real regular file or directory",
    ):
        build_g240_landlock_policy_v1(
            read_only_paths=(link,),
            state_path=state,
            output_path=output,
            cache_paths=(cache,),
            approved_tcp_ports=(),
        )

    broad_write = _private_directory(tmp_path / "broad-write")
    nested_read = _private_directory(broad_write / "nested-read")
    broad_output = _private_directory(tmp_path / "broad-output")
    broad_cache = _private_directory(tmp_path / "broad-cache")
    with pytest.raises(
        G240LandlockConfinementError,
        match="may not contain a read-only path",
    ):
        build_g240_landlock_policy_v1(
            read_only_paths=(nested_read,),
            state_path=broad_write,
            output_path=broad_output,
            cache_paths=(broad_cache,),
            approved_tcp_ports=(),
        )


def test_apply_fails_before_restriction_when_required_abi_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_only = _private_directory(tmp_path / "read-only")
    state = _private_directory(tmp_path / "state")
    output = _private_directory(tmp_path / "output")
    cache = _private_directory(tmp_path / "cache")
    outside = _private_directory(tmp_path / "outside")
    sources = build_g240_landlock_policy_v1(
        read_only_paths=(read_only,),
        state_path=state,
        output_path=output,
        cache_paths=(cache,),
        approved_tcp_ports=(),
    )
    monkeypatch.setattr(
        runtime_confinement,
        "probe_landlock_abi",
        lambda: G240_MINIMUM_LANDLOCK_ABI - 1,
    )
    with pytest.raises(
        G240LandlockConfinementError,
        match="ABI or errata differs",
    ):
        apply_g240_landlock_confinement(sources)
    # The ABI check occurs before ruleset creation or no_new_privs.  This
    # process remains unrestricted and can safely continue the test suite.
    (outside / "still-unrestricted.txt").write_text(
        "not partially confined",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("observed_abi", "message"),
    (
        (
            G240_MINIMUM_LANDLOCK_ABI - 1,
            "lacks required device-ioctl and IPC-scope enforcement",
        ),
        (
            G240_MAXIMUM_KNOWN_LANDLOCK_ABI + 1,
            "newer than the reviewed fail-closed profile",
        ),
    ),
)
def test_probe_rejects_unreviewed_landlock_abi(
    monkeypatch: pytest.MonkeyPatch,
    observed_abi: int,
    message: str,
) -> None:
    def fake_syscall(
        number: int,
        *arguments: object,
        operation: str,
    ) -> int:
        assert number == runtime_confinement._NR_LANDLOCK_CREATE_RULESET
        assert operation == "landlock ABI probe"
        return observed_abi

    monkeypatch.setattr(runtime_confinement, "_syscall", fake_syscall)
    with pytest.raises(G240LandlockConfinementError, match=message):
        probe_landlock_abi()


def test_preexec_factory_is_callable_but_does_not_expose_private_paths(
    tmp_path: Path,
) -> None:
    read_only = _private_directory(tmp_path / "read-only")
    state = _private_directory(tmp_path / "state")
    output = _private_directory(tmp_path / "output")
    cache = _private_directory(tmp_path / "cache")
    sources = build_g240_landlock_policy_v1(
        read_only_paths=(read_only,),
        state_path=state,
        output_path=output,
        cache_paths=(cache,),
        approved_tcp_ports=(),
    )
    callback = make_g240_landlock_preexec(sources)
    assert callable(callback)
    assert tmp_path.as_posix() not in repr(sources)
    # Never call the callback in the pytest process: Landlock is irreversible.


def test_private_path_replacement_fails_before_enforcement(
    tmp_path: Path,
) -> None:
    read_only = _private_directory(tmp_path / "read-only")
    state = _private_directory(tmp_path / "state")
    output = _private_directory(tmp_path / "output")
    cache = _private_directory(tmp_path / "cache")
    sources = build_g240_landlock_policy_v1(
        read_only_paths=(read_only,),
        state_path=state,
        output_path=output,
        cache_paths=(cache,),
        approved_tcp_ports=(),
    )

    displaced = tmp_path / "displaced-state"
    state.rename(displaced)
    replacement = _private_directory(state)
    assert replacement != displaced
    with pytest.raises(
        G240LandlockConfinementError,
        match="private Landlock sources changed",
    ):
        sources.revalidate()


def test_child_enforces_allowed_and_denied_filesystem_and_tcp_ports(
    tmp_path: Path,
) -> None:
    assert probe_landlock_abi() >= G240_MINIMUM_LANDLOCK_ABI
    read_only = _private_directory(tmp_path / "read-only")
    allowed_read = read_only / "allowed.txt"
    allowed_read.write_text("allowed", encoding="utf-8")
    state = _private_directory(tmp_path / "state")
    output = _private_directory(tmp_path / "output")
    cache = _private_directory(tmp_path / "cache")
    denied_read_root = _private_directory(tmp_path / "denied-read")
    denied_read = denied_read_root / "denied.txt"
    denied_read.write_text("denied", encoding="utf-8")
    denied_write_root = _private_directory(tmp_path / "denied-write")
    denied_write = denied_write_root / "blocked.txt"

    allowed_listener = _listening_socket()
    denied_listener = _listening_socket()
    abstract_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    abstract_name = (
        f"hssl-g240-{os.getpid()}-{tmp_path.name}"
    )[:90]
    abstract_listener.bind("\0" + abstract_name)
    abstract_listener.listen(1)
    allowed_port = int(allowed_listener.getsockname()[1])
    denied_port = int(denied_listener.getsockname()[1])
    assert allowed_port != denied_port

    child = r"""
import errno
import json
import os
from pathlib import Path
import socket
import sys

from benchmarks.logic_pipeline.runtime_confinement import (
    apply_g240_landlock_confinement,
    build_g240_landlock_policy_v1,
)

(
    allowed_read,
    state_root,
    output_root,
    cache_root,
    denied_read,
    denied_write,
    allowed_port,
    denied_port,
    abstract_name,
    parent_pid,
) = sys.argv[1:]
sources = build_g240_landlock_policy_v1(
    read_only_paths=(Path(allowed_read).parent,),
    state_path=Path(state_root),
    output_path=Path(output_root),
    cache_paths=(Path(cache_root),),
    approved_tcp_ports=(int(allowed_port),),
)
receipt = apply_g240_landlock_confinement(sources)

allowed_read_ok = Path(allowed_read).read_text(encoding="utf-8") == "allowed"
allowed_write_ok = True
for root, name in (
    (state_root, "state.txt"),
    (output_root, "output.txt"),
    (cache_root, "cache.txt"),
):
    target = Path(root) / name
    target.write_text("ok", encoding="utf-8")
    allowed_write_ok = allowed_write_ok and (
        target.read_text(encoding="utf-8") == "ok"
    )

try:
    Path(denied_read).read_text(encoding="utf-8")
except OSError as exc:
    denied_read_errno = exc.errno
else:
    denied_read_errno = 0

try:
    Path(denied_write).write_text("forbidden", encoding="utf-8")
except OSError as exc:
    denied_write_errno = exc.errno
else:
    denied_write_errno = 0

try:
    (Path(allowed_read).parent / "forbidden-write.txt").write_text(
        "forbidden",
        encoding="utf-8",
    )
except OSError as exc:
    read_only_write_errno = exc.errno
else:
    read_only_write_errno = 0

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as allowed_socket:
    allowed_socket.settimeout(2)
    allowed_socket.connect(("127.0.0.1", int(allowed_port)))
    allowed_tcp_ok = True

try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as denied_socket:
        denied_socket.settimeout(2)
        denied_socket.connect(("127.0.0.1", int(denied_port)))
except OSError as exc:
    denied_tcp_errno = exc.errno
else:
    denied_tcp_errno = 0

try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bind_socket:
        bind_socket.bind(("127.0.0.1", 0))
except OSError as exc:
    denied_bind_errno = exc.errno
else:
    denied_bind_errno = 0

try:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as unix_socket:
        unix_socket.connect("\0" + abstract_name)
except OSError as exc:
    denied_abstract_unix_errno = exc.errno
else:
    denied_abstract_unix_errno = 0

try:
    os.kill(int(parent_pid), 0)
except OSError as exc:
    denied_signal_errno = exc.errno
else:
    denied_signal_errno = 0

result = {
    "receipt": receipt.to_dict(),
    "policy": sources.policy.to_dict(),
    "allowed_read_ok": allowed_read_ok,
    "allowed_write_ok": allowed_write_ok,
    "allowed_tcp_ok": allowed_tcp_ok,
    "denied_read_errno": denied_read_errno,
    "denied_write_errno": denied_write_errno,
    "read_only_write_errno": read_only_write_errno,
    "denied_tcp_errno": denied_tcp_errno,
    "denied_bind_errno": denied_bind_errno,
    "denied_abstract_unix_errno": denied_abstract_unix_errno,
    "denied_signal_errno": denied_signal_errno,
    "expected_denial_errno": errno.EACCES,
    "expected_scope_errno": errno.EPERM,
}
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
"""
    repository = Path(__file__).resolve().parents[4]
    environment = {
        "PATH": os.defpath,
        "PYTHONPATH": repository.as_posix(),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONSAFEPATH": "1",
        "LC_ALL": "C",
    }
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                child,
                allowed_read.as_posix(),
                state.as_posix(),
                output.as_posix(),
                cache.as_posix(),
                denied_read.as_posix(),
                denied_write.as_posix(),
                str(allowed_port),
                str(denied_port),
                abstract_name,
                str(os.getpid()),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            cwd=repository,
            env=environment,
        )
    finally:
        allowed_listener.close()
        denied_listener.close()
        abstract_listener.close()
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["allowed_read_ok"] is True
    assert result["allowed_write_ok"] is True
    assert result["allowed_tcp_ok"] is True
    assert result["denied_read_errno"] == result["expected_denial_errno"]
    assert result["denied_write_errno"] == result["expected_denial_errno"]
    assert result["read_only_write_errno"] == result["expected_denial_errno"]
    assert result["denied_tcp_errno"] == result["expected_denial_errno"]
    assert result["denied_bind_errno"] == result["expected_denial_errno"]
    assert (
        result["denied_abstract_unix_errno"]
        == result["expected_scope_errno"]
    )
    assert result["denied_signal_errno"] == result["expected_scope_errno"]
    assert not denied_write.exists()
    assert not (read_only / "forbidden-write.txt").exists()

    policy = G240LandlockPolicyV1.from_dict(result["policy"])
    receipt = validate_g240_landlock_receipt_v1(
        result["receipt"],
        expected_policy=policy,
    )
    assert receipt.no_new_privs_set is True
    assert receipt.filesystem_rules_enforced is True
    assert receipt.device_ioctl_restricted is True
    assert receipt.tcp_bind_restricted is True
    assert receipt.tcp_connect_port_rules_enforced is True
    assert receipt.abstract_unix_socket_scoped is True
    assert receipt.signal_scoped is True
    assert receipt.tcp_address_authenticated is False
    public_json = json.dumps(result, sort_keys=True)
    for path in (
        read_only,
        state,
        output,
        cache,
        denied_read_root,
        denied_write_root,
        tmp_path,
    ):
        assert path.as_posix() not in public_json
    assert str(allowed_port) not in public_json
    assert str(denied_port) not in public_json


def test_public_receipt_rejects_policy_rebinding(
    tmp_path: Path,
) -> None:
    read_only = _private_directory(tmp_path / "read-only")
    state = _private_directory(tmp_path / "state")
    output = _private_directory(tmp_path / "output")
    cache = _private_directory(tmp_path / "cache")
    first = build_g240_landlock_policy_v1(
        read_only_paths=(read_only,),
        state_path=state,
        output_path=output,
        cache_paths=(cache,),
        approved_tcp_ports=(8080,),
    ).policy
    second = build_g240_landlock_policy_v1(
        read_only_paths=(read_only,),
        state_path=state,
        output_path=output,
        cache_paths=(cache,),
        approved_tcp_ports=(19001,),
    ).policy
    receipt = G240LandlockReceiptV1(
        policy_cid=str(first.policy_cid),
        observed_landlock_abi=first.expected_landlock_abi,
        observed_landlock_errata=first.expected_landlock_errata,
        handled_access_fs=G240_LANDLOCK_HANDLED_ACCESS_FS_V1,
        handled_access_net=G240_LANDLOCK_HANDLED_ACCESS_NET_V1,
        scoped=G240_LANDLOCK_SCOPED_V1,
        restrict_self_flags=G240_LANDLOCK_RESTRICT_SELF_FLAGS_V1,
        read_only_path_set_cid=first.read_only_path_set_cid,
        read_only_rule_count=first.read_only_path_count,
        read_write_path_set_cid=first.read_write_path_set_cid,
        read_write_rule_count=first.read_write_path_count,
        state_path_cid=first.state_path_cid,
        output_path_cid=first.output_path_cid,
        cache_path_set_cid=first.cache_path_set_cid,
        cache_rule_count=first.cache_path_count,
        approved_tcp_port_set_cid=first.approved_tcp_port_set_cid,
        approved_tcp_port_rule_count=first.approved_tcp_port_count,
        no_new_privs_set=True,
        filesystem_rules_enforced=True,
        device_ioctl_restricted=True,
        tcp_bind_restricted=True,
        tcp_connect_port_rules_enforced=True,
        abstract_unix_socket_scoped=True,
        signal_scoped=True,
        tcp_address_authenticated=False,
        ruleset_applied=True,
    )
    with pytest.raises(
        G240LandlockConfinementError,
        match="differs from its expected policy",
    ):
        validate_g240_landlock_receipt_v1(
            receipt,
            expected_policy=second,
        )
    foreign_errata_receipt = G240LandlockReceiptV1(
        **{
            **receipt.identity_payload(),
            "observed_landlock_errata": (
                receipt.observed_landlock_errata ^ 1
            ),
        }
    )
    with pytest.raises(
        G240LandlockConfinementError,
        match="differs from its expected policy",
    ):
        validate_g240_landlock_receipt_v1(
            foreign_errata_receipt,
            expected_policy=first,
        )
    with pytest.raises(
        G240LandlockConfinementError,
        match="receipt CID changed",
    ):
        tampered = receipt.to_dict()
        tampered["approved_tcp_port_rule_count"] = 2
        G240LandlockReceiptV1.from_dict(tampered)
