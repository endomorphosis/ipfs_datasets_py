"""Fail-closed Landlock confinement for HSSL-G240 child processes.

This module deliberately separates private enforcement inputs (filesystem
paths and TCP ports) from the public policy and receipt.  Public records
contain only canonical CIDv1/DAG-JSON identities, booleans, and counts; they
never serialize host paths.

Landlock authenticates filesystem objects by rules attached to opened inodes.
Its network rules authorize TCP destination *ports*, not peer IP addresses.
The receipt therefore always records ``tcp_address_authenticated=False``.
Endpoint identity and address validation remain separate G202/G203 duties.

The preferred integration point is a tiny, single-threaded bootstrap inside
the G240 child, before optional packages or benchmark inputs are opened.
``make_g240_landlock_preexec`` is also available for a carefully controlled
``subprocess`` launch, but callers must account for Python's general
``preexec_fn`` limitations in multi-threaded parents.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
import os
from pathlib import Path
import stat
import sys
from typing import Final, Mapping, Self, Sequence

from .content_addressing import cid_for_dag_json, validate_cid


G240_LANDLOCK_PATH_SET_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g240-landlock-path-set.v1"
)
G240_LANDLOCK_TCP_PORT_SET_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g240-landlock-tcp-port-set.v1"
)
G240_LANDLOCK_POLICY_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g240-landlock-policy.v1"
)
G240_LANDLOCK_RECEIPT_SCHEMA_V1: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g240-landlock-receipt.v1"
)

# ABI 6 is the first version that can enforce every isolation property frozen
# by this policy: TCP connect/bind controls, device-ioctl control, and abstract
# UNIX-socket/signal scoping.  ABI 7 adds audit-logging flags but no new access
# right.  Unknown future ABIs fail closed until their new rights and semantics
# have been reviewed and represented by a new policy schema.
G240_MINIMUM_LANDLOCK_ABI: Final = 6
G240_MAXIMUM_KNOWN_LANDLOCK_ABI: Final = 7

# Generic syscall numbers used by Linux architectures supported by this
# repository (including aarch64 and x86_64).
_NR_LANDLOCK_CREATE_RULESET: Final = 444
_NR_LANDLOCK_ADD_RULE: Final = 445
_NR_LANDLOCK_RESTRICT_SELF: Final = 446

_LANDLOCK_CREATE_RULESET_VERSION: Final = 1 << 0
_LANDLOCK_CREATE_RULESET_ERRATA: Final = 1 << 1
_LANDLOCK_RULE_PATH_BENEATH: Final = 1
_LANDLOCK_RULE_NET_PORT: Final = 2

_LANDLOCK_ACCESS_FS_EXECUTE: Final = 1 << 0
_LANDLOCK_ACCESS_FS_WRITE_FILE: Final = 1 << 1
_LANDLOCK_ACCESS_FS_READ_FILE: Final = 1 << 2
_LANDLOCK_ACCESS_FS_READ_DIR: Final = 1 << 3
_LANDLOCK_ACCESS_FS_REMOVE_DIR: Final = 1 << 4
_LANDLOCK_ACCESS_FS_REMOVE_FILE: Final = 1 << 5
_LANDLOCK_ACCESS_FS_MAKE_CHAR: Final = 1 << 6
_LANDLOCK_ACCESS_FS_MAKE_DIR: Final = 1 << 7
_LANDLOCK_ACCESS_FS_MAKE_REG: Final = 1 << 8
_LANDLOCK_ACCESS_FS_MAKE_SOCK: Final = 1 << 9
_LANDLOCK_ACCESS_FS_MAKE_FIFO: Final = 1 << 10
_LANDLOCK_ACCESS_FS_MAKE_BLOCK: Final = 1 << 11
_LANDLOCK_ACCESS_FS_MAKE_SYM: Final = 1 << 12
_LANDLOCK_ACCESS_FS_REFER: Final = 1 << 13
_LANDLOCK_ACCESS_FS_TRUNCATE: Final = 1 << 14
_LANDLOCK_ACCESS_FS_IOCTL_DEV: Final = 1 << 15

# Handle every filesystem right available through ABI 7.  Rights omitted from a
# Landlock ruleset are allowed for backward compatibility, so a partial mask
# would not provide a fail-closed write boundary.
G240_LANDLOCK_HANDLED_ACCESS_FS_V1: Final = (
    _LANDLOCK_ACCESS_FS_EXECUTE
    | _LANDLOCK_ACCESS_FS_WRITE_FILE
    | _LANDLOCK_ACCESS_FS_READ_FILE
    | _LANDLOCK_ACCESS_FS_READ_DIR
    | _LANDLOCK_ACCESS_FS_REMOVE_DIR
    | _LANDLOCK_ACCESS_FS_REMOVE_FILE
    | _LANDLOCK_ACCESS_FS_MAKE_CHAR
    | _LANDLOCK_ACCESS_FS_MAKE_DIR
    | _LANDLOCK_ACCESS_FS_MAKE_REG
    | _LANDLOCK_ACCESS_FS_MAKE_SOCK
    | _LANDLOCK_ACCESS_FS_MAKE_FIFO
    | _LANDLOCK_ACCESS_FS_MAKE_BLOCK
    | _LANDLOCK_ACCESS_FS_MAKE_SYM
    | _LANDLOCK_ACCESS_FS_REFER
    | _LANDLOCK_ACCESS_FS_TRUNCATE
    | _LANDLOCK_ACCESS_FS_IOCTL_DEV
)

_LANDLOCK_READ_ONLY_DIRECTORY_ACCESS: Final = (
    _LANDLOCK_ACCESS_FS_EXECUTE
    | _LANDLOCK_ACCESS_FS_READ_FILE
    | _LANDLOCK_ACCESS_FS_READ_DIR
)
_LANDLOCK_READ_ONLY_FILE_ACCESS: Final = (
    _LANDLOCK_ACCESS_FS_EXECUTE | _LANDLOCK_ACCESS_FS_READ_FILE
)
_LANDLOCK_READ_WRITE_DIRECTORY_ACCESS: Final = (
    _LANDLOCK_ACCESS_FS_WRITE_FILE
    | _LANDLOCK_ACCESS_FS_READ_FILE
    | _LANDLOCK_ACCESS_FS_READ_DIR
    | _LANDLOCK_ACCESS_FS_REMOVE_DIR
    | _LANDLOCK_ACCESS_FS_REMOVE_FILE
    | _LANDLOCK_ACCESS_FS_MAKE_DIR
    | _LANDLOCK_ACCESS_FS_MAKE_REG
    | _LANDLOCK_ACCESS_FS_REFER
    | _LANDLOCK_ACCESS_FS_TRUNCATE
)

_LANDLOCK_ACCESS_NET_BIND_TCP: Final = 1 << 0
_LANDLOCK_ACCESS_NET_CONNECT_TCP: Final = 1 << 1
G240_LANDLOCK_HANDLED_ACCESS_NET_V1: Final = (
    _LANDLOCK_ACCESS_NET_BIND_TCP | _LANDLOCK_ACCESS_NET_CONNECT_TCP
)

_LANDLOCK_SCOPE_ABSTRACT_UNIX_SOCKET: Final = 1 << 0
_LANDLOCK_SCOPE_SIGNAL: Final = 1 << 1
G240_LANDLOCK_SCOPED_V1: Final = (
    _LANDLOCK_SCOPE_ABSTRACT_UNIX_SOCKET | _LANDLOCK_SCOPE_SIGNAL
)

# ABI 7 introduces optional audit-logging controls rather than a new access
# right.  The frozen execution contract uses the kernel default logging policy
# (zero flags) and binds that exact choice into both policy and receipt.
G240_LANDLOCK_RESTRICT_SELF_FLAGS_V1: Final = 0

_PR_SET_NO_NEW_PRIVS: Final = 38
_PR_GET_NO_NEW_PRIVS: Final = 39


class G240LandlockConfinementError(RuntimeError):
    """Raised when the required confinement cannot be proved and applied."""


class _LandlockRulesetAttr(ctypes.Structure):
    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
        ("scoped", ctypes.c_uint64),
    ]


class _LandlockPathBeneathAttr(ctypes.Structure):
    # The Linux UAPI explicitly packs this structure to twelve bytes.
    _pack_ = 1
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


class _LandlockNetPortAttr(ctypes.Structure):
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("port", ctypes.c_uint64),
    ]


def _libc() -> ctypes.CDLL:
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    library.prctl.restype = ctypes.c_int
    return library


def _syscall(
    number: int,
    *arguments: object,
    operation: str,
) -> int:
    library = _libc()
    ctypes.set_errno(0)
    result = int(library.syscall(number, *arguments))
    if result < 0:
        error_number = ctypes.get_errno()
        raise G240LandlockConfinementError(
            f"{operation} failed closed with errno {error_number}"
        )
    return result


def _set_no_new_privileges() -> None:
    library = _libc()
    ctypes.set_errno(0)
    if int(library.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)) != 0:
        error_number = ctypes.get_errno()
        raise G240LandlockConfinementError(
            "PR_SET_NO_NEW_PRIVS failed closed with errno "
            f"{error_number}"
        )
    ctypes.set_errno(0)
    observed = int(library.prctl(_PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0))
    if observed != 1:
        error_number = ctypes.get_errno()
        raise G240LandlockConfinementError(
            "PR_GET_NO_NEW_PRIVS did not confirm enforcement"
            + (f" (errno {error_number})" if error_number else "")
        )


def probe_landlock_abi() -> int:
    """Return the kernel Landlock ABI or fail closed when unavailable."""

    if sys.platform != "linux":
        raise G240LandlockConfinementError(
            "Landlock confinement requires Linux"
        )
    abi = _syscall(
        _NR_LANDLOCK_CREATE_RULESET,
        ctypes.c_void_p(),
        0,
        _LANDLOCK_CREATE_RULESET_VERSION,
        operation="landlock ABI probe",
    )
    if abi < G240_MINIMUM_LANDLOCK_ABI:
        raise G240LandlockConfinementError(
            "Landlock ABI lacks required device-ioctl and IPC-scope "
            "enforcement"
        )
    if abi > G240_MAXIMUM_KNOWN_LANDLOCK_ABI:
        raise G240LandlockConfinementError(
            "Landlock ABI is newer than the reviewed fail-closed profile"
        )
    return abi


def probe_landlock_errata() -> int:
    """Return the running kernel's Landlock errata mask or fail closed."""

    # Validate the ABI first so an errata result from an unknown interface is
    # never interpreted under this frozen schema.
    probe_landlock_abi()
    errata = _syscall(
        _NR_LANDLOCK_CREATE_RULESET,
        ctypes.c_void_p(),
        0,
        _LANDLOCK_CREATE_RULESET_ERRATA,
        operation="landlock errata probe",
    )
    if errata < 0 or errata > (1 << 64) - 1:
        raise G240LandlockConfinementError(
            "Landlock errata mask is outside the reviewed representation"
        )
    return errata


def _canonical_cid(value: object, field_name: str) -> str:
    try:
        return validate_cid(value, codecs=("dag-json",))
    except (TypeError, ValueError) as exc:
        raise G240LandlockConfinementError(
            f"{field_name} must be a canonical DAG-JSON CID"
        ) from exc


def _normalized_path(value: str | os.PathLike[str], role: str) -> Path:
    try:
        raw = os.fspath(value)
    except TypeError as exc:
        raise G240LandlockConfinementError(
            f"{role} path must be path-like"
        ) from exc
    if (
        not isinstance(raw, str)
        or not raw
        or "\0" in raw
        or not Path(raw).is_absolute()
        or Path(raw) == Path("/")
        or Path(raw).as_posix() != raw
    ):
        raise G240LandlockConfinementError(
            f"{role} path must be normalized, absolute, and narrower than root"
        )
    path = Path(raw)
    try:
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
    except OSError as exc:
        raise G240LandlockConfinementError(
            f"{role} path cannot be authenticated"
        ) from exc
    if (
        resolved != path
        or stat.S_ISLNK(metadata.st_mode)
        or not (
            stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISREG(metadata.st_mode)
        )
    ):
        raise G240LandlockConfinementError(
            f"{role} path must name a real regular file or directory"
        )
    return path


def _path_object_cid(
    path: Path,
    role: str,
    *,
    metadata: os.stat_result | None = None,
) -> str:
    observed = path.lstat() if metadata is None else metadata
    if stat.S_ISDIR(observed.st_mode):
        kind = "directory"
    elif stat.S_ISREG(observed.st_mode):
        kind = "regular-file"
    else:
        raise G240LandlockConfinementError(
            f"{role} path object type changed"
        )
    return cid_for_dag_json(
        {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark."
                "g240-landlock-path-object.v1"
            ),
            # The path is a private CID preimage.  It never enters to_dict().
            "absolute_path": path.as_posix(),
            "role": role,
            "kind": kind,
            "device": int(observed.st_dev),
            "inode": int(observed.st_ino),
            "mode": int(stat.S_IMODE(observed.st_mode)),
            "uid": int(observed.st_uid),
        }
    )


def _path_set_cid(paths: Sequence[Path], role: str) -> str:
    return cid_for_dag_json(
        {
            "schema": G240_LANDLOCK_PATH_SET_SCHEMA_V1,
            "role": role,
            "path_object_cids": sorted(
                _path_object_cid(path, role) for path in paths
            ),
        }
    )


def _port_set_cid(ports: Sequence[int]) -> str:
    return cid_for_dag_json(
        {
            "schema": G240_LANDLOCK_TCP_PORT_SET_SCHEMA_V1,
            "transport": "tcp",
            "authority": "destination-port-only",
            "ports": list(ports),
        }
    )


def _normalize_ports(values: Sequence[int]) -> tuple[int, ...]:
    ports = tuple(values)
    if any(type(port) is not int or not 1 <= port <= 65535 for port in ports):
        raise G240LandlockConfinementError(
            "approved TCP ports must be integers from 1 through 65535"
        )
    normalized = tuple(sorted(ports))
    if len(normalized) != len(set(normalized)):
        raise G240LandlockConfinementError(
            "approved TCP ports must be unique"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class G240LandlockPolicyV1:
    """Path-free public projection of one exact private Landlock policy."""

    minimum_landlock_abi: int
    maximum_known_landlock_abi: int
    expected_landlock_abi: int
    expected_landlock_errata: int
    handled_access_fs: int
    handled_access_net: int
    scoped: int
    restrict_self_flags: int
    read_only_path_set_cid: str
    read_only_path_count: int
    read_write_path_set_cid: str
    read_write_path_count: int
    state_path_cid: str
    output_path_cid: str
    cache_path_set_cid: str
    cache_path_count: int
    approved_tcp_port_set_cid: str
    approved_tcp_port_count: int
    no_new_privs_required: bool
    device_ioctl_restricted: bool
    tcp_bind_restricted: bool
    tcp_connect_port_restricted: bool
    abstract_unix_socket_scoped: bool
    signal_scoped: bool
    tcp_address_authenticated: bool
    schema: str = G240_LANDLOCK_POLICY_SCHEMA_V1
    policy_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G240_LANDLOCK_POLICY_SCHEMA_V1:
            raise G240LandlockConfinementError(
                "unsupported G240 Landlock policy schema"
            )
        if (
            type(self.minimum_landlock_abi) is not int
            or self.minimum_landlock_abi != G240_MINIMUM_LANDLOCK_ABI
        ):
            raise G240LandlockConfinementError(
                "G240 Landlock minimum ABI changed"
            )
        if (
            type(self.maximum_known_landlock_abi) is not int
            or self.maximum_known_landlock_abi
            != G240_MAXIMUM_KNOWN_LANDLOCK_ABI
            or type(self.expected_landlock_abi) is not int
            or not (
                self.minimum_landlock_abi
                <= self.expected_landlock_abi
                <= self.maximum_known_landlock_abi
            )
        ):
            raise G240LandlockConfinementError(
                "G240 Landlock expected ABI is outside the reviewed profile"
            )
        if (
            type(self.expected_landlock_errata) is not int
            or not 0 <= self.expected_landlock_errata <= (1 << 64) - 1
        ):
            raise G240LandlockConfinementError(
                "G240 Landlock errata mask is invalid"
            )
        if (
            type(self.handled_access_fs) is not int
            or type(self.handled_access_net) is not int
            or type(self.scoped) is not int
            or type(self.restrict_self_flags) is not int
            or self.handled_access_fs
            != G240_LANDLOCK_HANDLED_ACCESS_FS_V1
            or self.handled_access_net
            != G240_LANDLOCK_HANDLED_ACCESS_NET_V1
            or self.scoped != G240_LANDLOCK_SCOPED_V1
            or self.restrict_self_flags
            != G240_LANDLOCK_RESTRICT_SELF_FLAGS_V1
        ):
            raise G240LandlockConfinementError(
                "G240 Landlock access, scope, or activation masks changed"
            )
        for name in (
            "read_only_path_set_cid",
            "read_write_path_set_cid",
            "state_path_cid",
            "output_path_cid",
            "cache_path_set_cid",
            "approved_tcp_port_set_cid",
        ):
            object.__setattr__(
                self,
                name,
                _canonical_cid(getattr(self, name), name),
            )
        for name, minimum in (
            ("read_only_path_count", 1),
            ("read_write_path_count", 1),
            ("cache_path_count", 1),
            ("approved_tcp_port_count", 0),
        ):
            value = getattr(self, name)
            if type(value) is not int or value < minimum:
                raise G240LandlockConfinementError(
                    f"{name} must be an observed count"
                )
        if (
            type(self.no_new_privs_required) is not bool
            or type(self.device_ioctl_restricted) is not bool
            or type(self.tcp_bind_restricted) is not bool
            or type(self.tcp_connect_port_restricted) is not bool
            or type(self.abstract_unix_socket_scoped) is not bool
            or type(self.signal_scoped) is not bool
            or type(self.tcp_address_authenticated) is not bool
            or not self.no_new_privs_required
            or not self.device_ioctl_restricted
            or not self.tcp_bind_restricted
            or not self.tcp_connect_port_restricted
            or not self.abstract_unix_socket_scoped
            or not self.signal_scoped
            or self.tcp_address_authenticated
        ):
            raise G240LandlockConfinementError(
                "G240 Landlock policy assurance booleans changed"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.policy_cid is None:
            object.__setattr__(self, "policy_cid", expected)
        elif (
            _canonical_cid(self.policy_cid, "policy_cid") != expected
        ):
            raise G240LandlockConfinementError(
                "G240 Landlock policy CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
            if field_name != "policy_cid"
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "policy_cid": self.policy_cid,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if not isinstance(value, Mapping) or not all(
            isinstance(key, str) for key in value
        ):
            raise G240LandlockConfinementError(
                "G240 Landlock policy must be an object"
            )
        if set(value) != set(cls.__dataclass_fields__):
            raise G240LandlockConfinementError(
                "G240 Landlock policy fields changed"
            )
        return cls(**value)  # type: ignore[arg-type]


def _public_policy_for_sources(
    read_only_paths: Sequence[Path],
    state_path: Path,
    output_path: Path,
    cache_paths: Sequence[Path],
    approved_tcp_ports: Sequence[int],
    *,
    expected_landlock_abi: int,
    expected_landlock_errata: int,
) -> G240LandlockPolicyV1:
    read_write_paths = (state_path, output_path, *cache_paths)
    return G240LandlockPolicyV1(
        minimum_landlock_abi=G240_MINIMUM_LANDLOCK_ABI,
        maximum_known_landlock_abi=G240_MAXIMUM_KNOWN_LANDLOCK_ABI,
        expected_landlock_abi=expected_landlock_abi,
        expected_landlock_errata=expected_landlock_errata,
        handled_access_fs=G240_LANDLOCK_HANDLED_ACCESS_FS_V1,
        handled_access_net=G240_LANDLOCK_HANDLED_ACCESS_NET_V1,
        scoped=G240_LANDLOCK_SCOPED_V1,
        restrict_self_flags=G240_LANDLOCK_RESTRICT_SELF_FLAGS_V1,
        read_only_path_set_cid=_path_set_cid(
            read_only_paths, "read-only"
        ),
        read_only_path_count=len(read_only_paths),
        read_write_path_set_cid=_path_set_cid(
            read_write_paths, "read-write"
        ),
        read_write_path_count=len(read_write_paths),
        state_path_cid=_path_object_cid(state_path, "state"),
        output_path_cid=_path_object_cid(output_path, "output"),
        cache_path_set_cid=_path_set_cid(cache_paths, "cache"),
        cache_path_count=len(cache_paths),
        approved_tcp_port_set_cid=_port_set_cid(approved_tcp_ports),
        approved_tcp_port_count=len(approved_tcp_ports),
        no_new_privs_required=True,
        device_ioctl_restricted=True,
        tcp_bind_restricted=True,
        tcp_connect_port_restricted=True,
        abstract_unix_socket_scoped=True,
        signal_scoped=True,
        tcp_address_authenticated=False,
    )


@dataclass(frozen=True, slots=True)
class G240LandlockPrivatePolicySourcesV1:
    """Private paths/ports that source-recompute one public policy."""

    policy: G240LandlockPolicyV1
    read_only_paths: tuple[Path, ...] = field(repr=False)
    state_path: Path = field(repr=False)
    output_path: Path = field(repr=False)
    cache_paths: tuple[Path, ...] = field(repr=False)
    approved_tcp_ports: tuple[int, ...] = field(repr=False)

    @property
    def read_write_paths(self) -> tuple[Path, ...]:
        return (self.state_path, self.output_path, *self.cache_paths)

    def __post_init__(self) -> None:
        if not isinstance(self.policy, G240LandlockPolicyV1):
            raise G240LandlockConfinementError(
                "private sources require a typed Landlock policy"
            )
        read_only = tuple(
            sorted(
                (
                    _normalized_path(path, "read-only")
                    for path in self.read_only_paths
                ),
                key=Path.as_posix,
            )
        )
        state_path = _normalized_path(self.state_path, "state")
        output_path = _normalized_path(self.output_path, "output")
        cache_paths = tuple(
            sorted(
                (
                    _normalized_path(path, "cache")
                    for path in self.cache_paths
                ),
                key=Path.as_posix,
            )
        )
        read_write = (state_path, output_path, *cache_paths)
        if not read_only or not cache_paths:
            raise G240LandlockConfinementError(
                "Landlock requires read-only, state, output, and cache paths"
            )
        if len(read_only) != len(set(read_only)) or len(read_write) != len(
            set(read_write)
        ):
            raise G240LandlockConfinementError(
                "Landlock policy paths must be unique"
            )
        if set(read_only) & set(read_write):
            raise G240LandlockConfinementError(
                "Landlock read-only and read-write paths overlap exactly"
            )
        # A read-write ancestor would silently make a nested read-only rule
        # writable because Landlock allow rules are additive.
        if any(
            read_write_root in read_only_member.parents
            for read_write_root in read_write
            for read_only_member in read_only
        ):
            raise G240LandlockConfinementError(
                "a read-write path may not contain a read-only path"
            )
        for path in read_write:
            metadata = path.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) & 0o077
            ):
                raise G240LandlockConfinementError(
                    "read-write roots must be private owned directories"
                )
        ports = _normalize_ports(self.approved_tcp_ports)
        object.__setattr__(self, "read_only_paths", read_only)
        object.__setattr__(self, "state_path", state_path)
        object.__setattr__(self, "output_path", output_path)
        object.__setattr__(self, "cache_paths", cache_paths)
        object.__setattr__(self, "approved_tcp_ports", ports)
        rebuilt = _public_policy_for_sources(
            read_only,
            state_path,
            output_path,
            cache_paths,
            ports,
            expected_landlock_abi=self.policy.expected_landlock_abi,
            expected_landlock_errata=self.policy.expected_landlock_errata,
        )
        if rebuilt.to_dict() != self.policy.to_dict():
            raise G240LandlockConfinementError(
                "private Landlock sources differ from the public policy"
            )

    def revalidate(self) -> G240LandlockPolicyV1:
        """Recompute the public policy from current private objects."""

        rebuilt = _public_policy_for_sources(
            self.read_only_paths,
            self.state_path,
            self.output_path,
            self.cache_paths,
            self.approved_tcp_ports,
            expected_landlock_abi=self.policy.expected_landlock_abi,
            expected_landlock_errata=self.policy.expected_landlock_errata,
        )
        if rebuilt.to_dict() != self.policy.to_dict():
            raise G240LandlockConfinementError(
                "private Landlock sources changed before enforcement"
            )
        return rebuilt


def build_g240_landlock_policy_v1(
    *,
    read_only_paths: Sequence[str | os.PathLike[str]],
    state_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    cache_paths: Sequence[str | os.PathLike[str]],
    approved_tcp_ports: Sequence[int],
) -> G240LandlockPrivatePolicySourcesV1:
    """Build private enforcement sources and their path-free public policy."""

    normalized_read_only = tuple(
        _normalized_path(path, "read-only") for path in read_only_paths
    )
    normalized_state = _normalized_path(state_path, "state")
    normalized_output = _normalized_path(output_path, "output")
    normalized_caches = tuple(
        _normalized_path(path, "cache") for path in cache_paths
    )
    ports = _normalize_ports(approved_tcp_ports)
    observed_abi = probe_landlock_abi()
    observed_errata = probe_landlock_errata()
    policy = _public_policy_for_sources(
        tuple(sorted(normalized_read_only, key=Path.as_posix)),
        normalized_state,
        normalized_output,
        tuple(sorted(normalized_caches, key=Path.as_posix)),
        ports,
        expected_landlock_abi=observed_abi,
        expected_landlock_errata=observed_errata,
    )
    return G240LandlockPrivatePolicySourcesV1(
        policy=policy,
        read_only_paths=normalized_read_only,
        state_path=normalized_state,
        output_path=normalized_output,
        cache_paths=normalized_caches,
        approved_tcp_ports=ports,
    )


@dataclass(frozen=True, slots=True)
class G240LandlockReceiptV1:
    """Path-free public observation emitted after confinement succeeds."""

    policy_cid: str
    observed_landlock_abi: int
    observed_landlock_errata: int
    handled_access_fs: int
    handled_access_net: int
    scoped: int
    restrict_self_flags: int
    read_only_path_set_cid: str
    read_only_rule_count: int
    read_write_path_set_cid: str
    read_write_rule_count: int
    state_path_cid: str
    output_path_cid: str
    cache_path_set_cid: str
    cache_rule_count: int
    approved_tcp_port_set_cid: str
    approved_tcp_port_rule_count: int
    no_new_privs_set: bool
    filesystem_rules_enforced: bool
    device_ioctl_restricted: bool
    tcp_bind_restricted: bool
    tcp_connect_port_rules_enforced: bool
    abstract_unix_socket_scoped: bool
    signal_scoped: bool
    tcp_address_authenticated: bool
    ruleset_applied: bool
    schema: str = G240_LANDLOCK_RECEIPT_SCHEMA_V1
    receipt_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G240_LANDLOCK_RECEIPT_SCHEMA_V1:
            raise G240LandlockConfinementError(
                "unsupported G240 Landlock receipt schema"
            )
        for name in (
            "policy_cid",
            "read_only_path_set_cid",
            "read_write_path_set_cid",
            "state_path_cid",
            "output_path_cid",
            "cache_path_set_cid",
            "approved_tcp_port_set_cid",
        ):
            object.__setattr__(
                self,
                name,
                _canonical_cid(getattr(self, name), name),
            )
        if (
            type(self.observed_landlock_abi) is not int
            or self.observed_landlock_abi < G240_MINIMUM_LANDLOCK_ABI
            or self.observed_landlock_abi
            > G240_MAXIMUM_KNOWN_LANDLOCK_ABI
        ):
            raise G240LandlockConfinementError(
                "Landlock receipt ABI is outside the reviewed profile"
            )
        if (
            type(self.observed_landlock_errata) is not int
            or not 0 <= self.observed_landlock_errata <= (1 << 64) - 1
        ):
            raise G240LandlockConfinementError(
                "Landlock receipt errata mask is invalid"
            )
        if (
            type(self.handled_access_fs) is not int
            or type(self.handled_access_net) is not int
            or type(self.scoped) is not int
            or type(self.restrict_self_flags) is not int
            or self.handled_access_fs
            != G240_LANDLOCK_HANDLED_ACCESS_FS_V1
            or self.handled_access_net
            != G240_LANDLOCK_HANDLED_ACCESS_NET_V1
            or self.scoped != G240_LANDLOCK_SCOPED_V1
            or self.restrict_self_flags
            != G240_LANDLOCK_RESTRICT_SELF_FLAGS_V1
        ):
            raise G240LandlockConfinementError(
                "Landlock receipt masks differ from the reviewed profile"
            )
        for name, minimum in (
            ("read_only_rule_count", 1),
            ("read_write_rule_count", 1),
            ("cache_rule_count", 1),
            ("approved_tcp_port_rule_count", 0),
        ):
            observed = getattr(self, name)
            if type(observed) is not int or observed < minimum:
                raise G240LandlockConfinementError(
                    f"{name} must be an observed count"
                )
        for name in (
            "no_new_privs_set",
            "filesystem_rules_enforced",
            "device_ioctl_restricted",
            "tcp_bind_restricted",
            "tcp_connect_port_rules_enforced",
            "abstract_unix_socket_scoped",
            "signal_scoped",
            "tcp_address_authenticated",
            "ruleset_applied",
        ):
            if type(getattr(self, name)) is not bool:
                raise G240LandlockConfinementError(
                    f"{name} must be boolean"
                )
        if (
            not self.no_new_privs_set
            or not self.filesystem_rules_enforced
            or not self.device_ioctl_restricted
            or not self.tcp_bind_restricted
            or not self.tcp_connect_port_rules_enforced
            or not self.abstract_unix_socket_scoped
            or not self.signal_scoped
            or self.tcp_address_authenticated
            or not self.ruleset_applied
        ):
            raise G240LandlockConfinementError(
                "Landlock receipt does not prove required enforcement"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.receipt_cid is None:
            object.__setattr__(self, "receipt_cid", expected)
        elif (
            _canonical_cid(self.receipt_cid, "receipt_cid") != expected
        ):
            raise G240LandlockConfinementError(
                "G240 Landlock receipt CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
            if field_name != "receipt_cid"
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "receipt_cid": self.receipt_cid,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if not isinstance(value, Mapping) or not all(
            isinstance(key, str) for key in value
        ):
            raise G240LandlockConfinementError(
                "G240 Landlock receipt must be an object"
            )
        if set(value) != set(cls.__dataclass_fields__):
            raise G240LandlockConfinementError(
                "G240 Landlock receipt fields changed"
            )
        return cls(**value)  # type: ignore[arg-type]


def _open_rule_path(path: Path, expected_cid: str, role: str) -> int:
    if not hasattr(os, "O_PATH"):
        raise G240LandlockConfinementError(
            "Linux O_PATH is required for Landlock"
        )
    flags = os.O_PATH | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
    except OSError as exc:
        raise G240LandlockConfinementError(
            f"{role} Landlock object cannot be opened"
        ) from exc
    try:
        if (
            stat.S_ISLNK(metadata.st_mode)
            or _path_object_cid(
                path,
                role,
                metadata=metadata,
            )
            != expected_cid
        ):
            raise G240LandlockConfinementError(
                f"{role} Landlock object changed before rule installation"
            )
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _add_path_rule(
    ruleset_fd: int,
    *,
    path: Path,
    expected_cid: str,
    role: str,
    allowed_access: int,
) -> None:
    descriptor = _open_rule_path(path, expected_cid, role)
    try:
        attributes = _LandlockPathBeneathAttr(
            allowed_access=allowed_access,
            parent_fd=descriptor,
        )
        _syscall(
            _NR_LANDLOCK_ADD_RULE,
            ruleset_fd,
            _LANDLOCK_RULE_PATH_BENEATH,
            ctypes.byref(attributes),
            0,
            operation=f"{role} Landlock rule installation",
        )
    finally:
        os.close(descriptor)


def _add_tcp_port_rule(ruleset_fd: int, port: int) -> None:
    attributes = _LandlockNetPortAttr(
        allowed_access=_LANDLOCK_ACCESS_NET_CONNECT_TCP,
        port=port,
    )
    _syscall(
        _NR_LANDLOCK_ADD_RULE,
        ruleset_fd,
        _LANDLOCK_RULE_NET_PORT,
        ctypes.byref(attributes),
        0,
        operation="TCP destination-port Landlock rule installation",
    )


def apply_g240_landlock_confinement(
    sources: G240LandlockPrivatePolicySourcesV1,
) -> G240LandlockReceiptV1:
    """Apply the exact private policy to the current process or fail closed."""

    if not isinstance(sources, G240LandlockPrivatePolicySourcesV1):
        raise G240LandlockConfinementError(
            "Landlock enforcement requires typed private policy sources"
        )
    policy = sources.revalidate()
    abi = probe_landlock_abi()
    errata = probe_landlock_errata()
    if (
        abi != policy.expected_landlock_abi
        or errata != policy.expected_landlock_errata
    ):
        raise G240LandlockConfinementError(
            "Landlock ABI or errata differs from the frozen policy"
        )
    attributes = _LandlockRulesetAttr(
        handled_access_fs=policy.handled_access_fs,
        handled_access_net=policy.handled_access_net,
        scoped=policy.scoped,
    )
    ruleset_fd = _syscall(
        _NR_LANDLOCK_CREATE_RULESET,
        ctypes.byref(attributes),
        ctypes.sizeof(attributes),
        0,
        operation="Landlock ruleset creation",
    )
    try:
        read_only_cids = sorted(
            _path_object_cid(path, "read-only")
            for path in sources.read_only_paths
        )
        for path, path_cid in zip(
            sources.read_only_paths,
            (
                _path_object_cid(path, "read-only")
                for path in sources.read_only_paths
            ),
            strict=True,
        ):
            metadata = path.lstat()
            allowed_access = (
                _LANDLOCK_READ_ONLY_DIRECTORY_ACCESS
                if stat.S_ISDIR(metadata.st_mode)
                else _LANDLOCK_READ_ONLY_FILE_ACCESS
            )
            _add_path_rule(
                ruleset_fd,
                path=path,
                expected_cid=path_cid,
                role="read-only",
                allowed_access=allowed_access,
            )
        read_write_cids = sorted(
            _path_object_cid(path, "read-write")
            for path in sources.read_write_paths
        )
        for path, path_cid in zip(
            sources.read_write_paths,
            (
                _path_object_cid(path, "read-write")
                for path in sources.read_write_paths
            ),
            strict=True,
        ):
            _add_path_rule(
                ruleset_fd,
                path=path,
                expected_cid=path_cid,
                role="read-write",
                allowed_access=_LANDLOCK_READ_WRITE_DIRECTORY_ACCESS,
            )
        if (
            cid_for_dag_json(
                {
                    "schema": G240_LANDLOCK_PATH_SET_SCHEMA_V1,
                    "role": "read-only",
                    "path_object_cids": read_only_cids,
                }
            )
            != policy.read_only_path_set_cid
            or cid_for_dag_json(
                {
                    "schema": G240_LANDLOCK_PATH_SET_SCHEMA_V1,
                    "role": "read-write",
                    "path_object_cids": read_write_cids,
                }
            )
            != policy.read_write_path_set_cid
        ):
            raise G240LandlockConfinementError(
                "Landlock path objects changed during rule installation"
            )
        for port in sources.approved_tcp_ports:
            _add_tcp_port_rule(ruleset_fd, port)
        _set_no_new_privileges()
        _syscall(
            _NR_LANDLOCK_RESTRICT_SELF,
            ruleset_fd,
            policy.restrict_self_flags,
            operation="Landlock ruleset activation",
        )
    finally:
        os.close(ruleset_fd)
    return G240LandlockReceiptV1(
        policy_cid=str(policy.policy_cid),
        observed_landlock_abi=abi,
        observed_landlock_errata=errata,
        handled_access_fs=policy.handled_access_fs,
        handled_access_net=policy.handled_access_net,
        scoped=policy.scoped,
        restrict_self_flags=policy.restrict_self_flags,
        read_only_path_set_cid=policy.read_only_path_set_cid,
        read_only_rule_count=policy.read_only_path_count,
        read_write_path_set_cid=policy.read_write_path_set_cid,
        read_write_rule_count=policy.read_write_path_count,
        state_path_cid=policy.state_path_cid,
        output_path_cid=policy.output_path_cid,
        cache_path_set_cid=policy.cache_path_set_cid,
        cache_rule_count=policy.cache_path_count,
        approved_tcp_port_set_cid=policy.approved_tcp_port_set_cid,
        approved_tcp_port_rule_count=policy.approved_tcp_port_count,
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


def make_g240_landlock_preexec(
    sources: G240LandlockPrivatePolicySourcesV1,
):
    """Return a no-argument confinement callback for a controlled child."""

    if not isinstance(sources, G240LandlockPrivatePolicySourcesV1):
        raise G240LandlockConfinementError(
            "Landlock preexec requires typed private policy sources"
        )

    def apply_before_exec() -> None:
        apply_g240_landlock_confinement(sources)

    return apply_before_exec


def validate_g240_landlock_policy_v1(
    value: object,
) -> G240LandlockPolicyV1:
    """Reparse one path-free public policy and verify its CID."""

    if isinstance(value, G240LandlockPolicyV1):
        value = value.to_dict()
    return G240LandlockPolicyV1.from_dict(value)


def validate_g240_landlock_receipt_v1(
    value: object,
    *,
    expected_policy: G240LandlockPolicyV1 | None = None,
) -> G240LandlockReceiptV1:
    """Reparse a public receipt and optionally join it to its policy."""

    if isinstance(value, G240LandlockReceiptV1):
        value = value.to_dict()
    receipt = G240LandlockReceiptV1.from_dict(value)
    if expected_policy is not None:
        policy = validate_g240_landlock_policy_v1(expected_policy)
        if (
            receipt.policy_cid != policy.policy_cid
            or receipt.observed_landlock_abi
            != policy.expected_landlock_abi
            or receipt.observed_landlock_errata
            != policy.expected_landlock_errata
            or receipt.handled_access_fs != policy.handled_access_fs
            or receipt.handled_access_net != policy.handled_access_net
            or receipt.scoped != policy.scoped
            or receipt.restrict_self_flags != policy.restrict_self_flags
            or receipt.read_only_path_set_cid
            != policy.read_only_path_set_cid
            or receipt.read_only_rule_count
            != policy.read_only_path_count
            or receipt.read_write_path_set_cid
            != policy.read_write_path_set_cid
            or receipt.read_write_rule_count
            != policy.read_write_path_count
            or receipt.state_path_cid != policy.state_path_cid
            or receipt.output_path_cid != policy.output_path_cid
            or receipt.cache_path_set_cid != policy.cache_path_set_cid
            or receipt.cache_rule_count != policy.cache_path_count
            or receipt.approved_tcp_port_set_cid
            != policy.approved_tcp_port_set_cid
            or receipt.approved_tcp_port_rule_count
            != policy.approved_tcp_port_count
        ):
            raise G240LandlockConfinementError(
                "Landlock receipt differs from its expected policy"
            )
    return receipt


__all__ = [
    "G240_LANDLOCK_HANDLED_ACCESS_FS_V1",
    "G240_LANDLOCK_HANDLED_ACCESS_NET_V1",
    "G240_LANDLOCK_RESTRICT_SELF_FLAGS_V1",
    "G240_LANDLOCK_SCOPED_V1",
    "G240_MAXIMUM_KNOWN_LANDLOCK_ABI",
    "G240_LANDLOCK_PATH_SET_SCHEMA_V1",
    "G240_LANDLOCK_POLICY_SCHEMA_V1",
    "G240_LANDLOCK_RECEIPT_SCHEMA_V1",
    "G240_LANDLOCK_TCP_PORT_SET_SCHEMA_V1",
    "G240_MINIMUM_LANDLOCK_ABI",
    "G240LandlockConfinementError",
    "G240LandlockPolicyV1",
    "G240LandlockPrivatePolicySourcesV1",
    "G240LandlockReceiptV1",
    "apply_g240_landlock_confinement",
    "build_g240_landlock_policy_v1",
    "make_g240_landlock_preexec",
    "probe_landlock_abi",
    "probe_landlock_errata",
    "validate_g240_landlock_policy_v1",
    "validate_g240_landlock_receipt_v1",
]
