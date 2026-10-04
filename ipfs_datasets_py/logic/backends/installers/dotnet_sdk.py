"""Explicit, bounded provisioning of the pinned AutoHyper .NET SDK dependency.

Planning is inert. Installation authenticates an official archive, stages its
complete inventory, probes only the selected host, and publishes transactionally.
This support dependency confers no solver or proof authority.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import stat
import struct
import tempfile
from types import MappingProxyType

SDK_VERSION = "8.0.300"
RUNTIME_VERSION = "8.0.5"
MANIFEST_NAME = ".ipfs-dotnet-sdk.json"
SCHEMA = "dotnet-sdk-setup@1"
_PINS = MappingProxyType({
    "linux-aarch64": MappingProxyType({
        "rid": "linux-arm64", "elf_machine": 183,
        "url": "https://builds.dotnet.microsoft.com/dotnet/Sdk/8.0.300/dotnet-sdk-8.0.300-linux-arm64.tar.gz",
        "sha512": "b38d34afe6d92f63a0e5b6fc37c88fbb5a1c73fba7d8df41d25432b64b2fbc31017198a02209b3d4343d384bc352834b9ee68306307a3f0fe486591dd2f70efd",
    }),
    "linux-x86_64": MappingProxyType({
        "rid": "linux-x64", "elf_machine": 62,
        "url": "https://builds.dotnet.microsoft.com/dotnet/Sdk/8.0.300/dotnet-sdk-8.0.300-linux-x64.tar.gz",
        "sha512": "6ba966801ad3869275469b0f7ee7af0b88b659d018a37b241962335bd95ef6e55cb6741ab77d96a93c68174d30d0c270b48b3cda21b493270b0d6038ee3fe79e",
    }),
})


def _blocked(detail, reason):
    from .hyperproperty import HyperpropertyInstallBlocked
    return HyperpropertyInstallBlocked(detail, reason)


def _platform_id():
    if platform.system() != "Linux":
        return "unsupported"
    machine = platform.machine().lower()
    if machine in {"aarch64", "arm64"}:
        return "linux-aarch64"
    if machine in {"x86_64", "amd64"}:
        return "linux-x86_64"
    return "unsupported"


def _paths(install_root, archive_cache_root):
    from .hyperproperty_setup import _absolute_path
    if install_root is None:
        from ...external_provers.lazy_installer import configured_user_install_root
        install_root = configured_user_install_root()
    root = _absolute_path(install_root)
    cache = root / "downloads" if archive_cache_root is None else _absolute_path(archive_cache_root)
    platform_id = _platform_id()
    if platform_id not in _PINS:
        raise _blocked("pinned .NET SDK supports Linux arm64/x64 only", "unsupported_dotnet_sdk_platform")
    pin = dict(_PINS[platform_id])
    name = f"dotnet-sdk-{SDK_VERSION}-{pin['rid']}"
    sdk, archive = root / name, cache / (name + ".tar.gz")
    if sdk == archive or sdk in archive.parents or archive in sdk.parents:
        raise _blocked("SDK payload and archive cache must be separate", "dotnet_sdk_path_conflict")
    return root, cache, sdk, archive, platform_id, pin


def _real_directories(path):
    """Refuse known symlink/non-directory ancestors before creating anything."""
    for candidate in (path, *path.parents):
        try:
            details = candidate.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(details.st_mode):
            raise _blocked("SDK directories must not contain links or non-directories", "dotnet_sdk_unsafe_path")


def _base_receipt(root, cache, sdk, archive, platform_id, pin, *, force=False):
    return {
        "schema": SCHEMA, "status": "planned", "sdk_version": SDK_VERSION,
        "runtime_version": RUNTIME_VERSION, "platform_id": platform_id, "rid": pin["rid"],
        "install_root": str(root), "archive_cache_root": str(cache), "sdk_root": str(sdk),
        "executable": str(sdk / "dotnet"), "archive_path": str(archive),
        "archive_url": pin["url"], "archive_sha512": pin["sha512"],
        "tree_sha256": "", "executable_sha256": "",
        "dependency_roots": {"dotnet-sdk": str(sdk)}, "support_only": True,
        "authorizes_proof": False, "installed": False, "archive_verified": False,
        "tree_verified": False, "version_probe": False, "version_probe_output": "",
        "force": force, "candidate_present": sdk.is_dir(), "validation_required": True,
        "notes": ["This SDK is a support dependency, not an installed Hyper engine.",
                  "Linux system loader and library prerequisites are not provisioned.",
                  "Archive/tree verification is a bounded observation, not future immutability."],
    }


def plan_dotnet_sdk_setup(*, install_root=None, archive_cache_root=None):
    """Describe fixed paths/pins without locks, writes, hashing or native probes.

    Supported pins target Linux glibc arm64/x64. Presence is merely a candidate;
    it does not establish provenance, version compatibility or loader support.
    """
    values = _paths(install_root, archive_cache_root)
    return _base_receipt(*values)


def _small_regular(path, limit):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        stream = os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise _blocked("SDK metadata must be a bounded regular file", "dotnet_sdk_invalid_layout")
        value = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        keys = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(value) > limit or len(value) != after.st_size or any(getattr(before, key) != getattr(after, key) for key in keys):
            raise _blocked("SDK metadata changed while reading", "dotnet_sdk_invalid_layout")
        return value


def _layout(sdk, pin):
    """Check fixed SDK/runtime layout and host architecture before execution."""
    from .install_control import installation_checkpoint
    installation_checkpoint("before .NET SDK layout validation")
    required = ("dotnet", f"sdk/{SDK_VERSION}/dotnet.dll", f"sdk/{SDK_VERSION}/.version",
                f"sdk/{SDK_VERSION}/dotnet.runtimeconfig.json", f"host/fxr/{RUNTIME_VERSION}/libhostfxr.so",
                f"shared/Microsoft.NETCore.App/{RUNTIME_VERSION}/libcoreclr.so",
                f"shared/Microsoft.NETCore.App/{RUNTIME_VERSION}/System.Private.CoreLib.dll")
    try:
        for relative in required:
            path = sdk / relative
            _real_directories(path.parent)
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError("required SDK file is not regular")
        executable = sdk / "dotnet"
        if not executable.stat().st_mode & 0o111:
            raise ValueError("SDK host is not executable")
        # The host is a small native ELF. Bound the read even for hostile local
        # replacement; full byte identity is separately authenticated by audit.
        host = _small_regular(executable, 16 * 1024**2)
        if (len(host) < 64 or host[:6] != b"\x7fELF\x02\x01"
                or struct.unpack_from("<H", host, 18)[0] != pin["elf_machine"]
                or struct.unpack_from("<H", host, 16)[0] not in {2, 3}):
            raise ValueError("SDK host architecture differs from selected pin")
        version = _small_regular(sdk / f"sdk/{SDK_VERSION}/.version", 4096).decode("utf-8").splitlines()
        if len(version) < 3 or version[1] != SDK_VERSION or version[2] != pin["rid"]:
            raise ValueError("SDK version metadata differs from selected pin")
        runtime = json.loads(_small_regular(sdk / f"sdk/{SDK_VERSION}/dotnet.runtimeconfig.json", 16_384))
        framework = runtime["runtimeOptions"]["framework"]
        if framework["name"] != "Microsoft.NETCore.App" or framework["version"] != RUNTIME_VERSION:
            raise ValueError("SDK framework metadata differs from selected pin")
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        from .hyperproperty import HyperpropertyInstallBlocked
        if isinstance(error, HyperpropertyInstallBlocked):
            raise
        raise _blocked("SDK archive layout or host architecture is incompatible", "dotnet_sdk_invalid_layout") from error
    installation_checkpoint("after .NET SDK layout validation")


def _manifest(pin, platform_id, inventory):
    return {"schema": "dotnet-sdk-installation@1", "sdk_version": SDK_VERSION,
            "runtime_version": RUNTIME_VERSION, "platform_id": platform_id, "rid": pin["rid"],
            "archive_url": pin["url"], "archive_sha512": pin["sha512"],
            "tree_sha256": inventory["tree_sha256"],
            "executable_sha256": inventory["entries"]["dotnet"]["sha256"],
            "support_only": True, "authorizes_proof": False}


def _read_manifest(sdk):
    try:
        result = json.loads(_small_regular(sdk / MANIFEST_NAME, 65_536))
        if not isinstance(result, dict):
            raise ValueError("manifest must be an object")
        return result
    except (OSError, UnicodeError, ValueError) as error:
        raise _blocked("existing SDK has no valid installation manifest", "dotnet_sdk_existing_mismatch") from error


def _probe(sdk, scratch):
    from . import hyperproperty as hp
    from .install_control import InstallControlError, installation_checkpoint, run_install_command
    scratch.mkdir()
    for name in ("home", "tmp", "nuget", "http"):
        (scratch / name).mkdir()
    # Pin SDK selection even when a caller's parent directory has global.json.
    (scratch / "global.json").write_text(json.dumps({"sdk": {"version": SDK_VERSION,
        "rollForward": "disable", "allowPrerelease": False}}) + "\n")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(scratch / "home"),
           "TMPDIR": str(scratch / "tmp"), "TMP": str(scratch / "tmp"), "TEMP": str(scratch / "tmp"),
           "DOTNET_ROOT": str(sdk), "DOTNET_CLI_HOME": str(scratch / "home"),
           "NUGET_PACKAGES": str(scratch / "nuget"), "NUGET_HTTP_CACHE_PATH": str(scratch / "http"),
           "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
           "DOTNET_MULTILEVEL_LOOKUP": "0", "DOTNET_NOLOGO": "1",
           "DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE": "true", "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false"}
    installation_checkpoint("before .NET SDK version probe")
    try:
        result = run_install_command((str(sdk / "dotnet"), "--version"), cwd=scratch,
            environment=env, inherit_environment=False, timeout_seconds=30)
    except (OSError, InstallControlError) as error:
        installation_checkpoint("after failed .NET SDK version probe")
        raise _blocked("SDK native loader/version probe failed", "dotnet_sdk_probe_failed") from error
    installation_checkpoint("after .NET SDK version probe cleanup")
    output = hp._install_process_text(result.stdout).strip()
    if hp._install_process_failed(result) or output != SDK_VERSION:
        raise _blocked("SDK did not produce a clean exact version response", "dotnet_sdk_probe_failed")
    return output


def ensure_dotnet_sdk(*, yes=False, install_root=None, archive_cache_root=None,
        force=False, limits=None, operation_timeout_ms=None, cancellation=None,
        scheduler=None, parent_lease=None):
    """Provision only SDK 8.0.300, with explicit authorization and finite bounds.

    Without ``yes=True`` this returns the inert plan. Existing trees are reused
    only after full comparison with a freshly authenticated archive inventory;
    this cached path needs no native probe. ``force=True`` permits replacement
    of a mismatched real directory, retaining it for rollback until all staged
    and published checks pass. It never permits symlink destinations. Ordinary
    failures raise ``HyperpropertyInstallBlocked``; operation stops propagate.
    """
    if type(yes) is not bool or type(force) is not bool:
        raise ValueError("yes and force must be bools")
    values = _paths(install_root, archive_cache_root)
    receipt = _base_receipt(*values, force=force)
    if not yes:
        return receipt
    from . import dotnet_sdk_archive as archives
    from .hyperproperty import HyperpropertyInstallBlocked
    from .hyperproperty_transaction import installation_transaction
    from .install_control import installation_scope, installation_checkpoint
    root, cache, sdk, archive, platform_id, pin = values
    with installation_scope(limits=limits, operation_timeout_ms=operation_timeout_ms,
            cancellation=cancellation, scheduler=scheduler, parent_lease=parent_lease):
        installation_checkpoint("before .NET SDK transaction")
        _real_directories(root)
        _real_directories(cache)
        _real_directories(sdk)
        with installation_transaction(root, "dotnet-sdk-" + pin["rid"]) as transaction:
            exists = sdk.is_dir()
            if exists and not force:
                _read_manifest(sdk)
            archives.download_sdk_archive(pin["url"], archive, pin["sha512"])
            with tempfile.TemporaryDirectory(prefix=".dotnet-sdk-staging-", dir=root) as temporary:
                stage = Path(temporary)
                payload = stage / "sdk"
                inventory = archives.extract_sdk_archive(archive, payload, pin["sha512"])
                _layout(payload, pin)
                expected = _manifest(pin, platform_id, inventory)
                if exists:
                    try:
                        actual = _read_manifest(sdk)
                        if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
                            raise _blocked("existing SDK provenance differs from reviewed archive", "dotnet_sdk_existing_mismatch")
                        archives.audit_sdk_tree(sdk, inventory)
                        _layout(sdk, pin)
                    except HyperpropertyInstallBlocked as error:
                        if not force:
                            raise _blocked("existing SDK differs from authenticated archive; explicit force required",
                                           "dotnet_sdk_existing_mismatch") from error
                    else:
                        receipt.update(status="already_present", installed=True, archive_verified=True,
                            tree_verified=True, tree_sha256=inventory["tree_sha256"],
                            executable_sha256=expected["executable_sha256"], validation_required=False)
                        installation_checkpoint("before authenticated .NET SDK reuse")
                        return receipt
                _probe(payload, stage / "staged-probe")
                archives.audit_sdk_tree(payload, inventory)
                (payload / MANIFEST_NAME).write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
                installation_checkpoint("before .NET SDK publication")
                transaction.replace_tree(payload, sdk)
                archives.audit_sdk_tree(sdk, inventory)
                version = _probe(sdk, stage / "published-probe")
                archives.audit_sdk_tree(sdk, inventory)
                if json.dumps(_read_manifest(sdk), sort_keys=True) != json.dumps(expected, sort_keys=True):
                    raise _blocked("SDK manifest changed after publication", "dotnet_sdk_existing_mismatch")
                receipt.update(status="installed", installed=True, archive_verified=True,
                    tree_verified=True, tree_sha256=inventory["tree_sha256"],
                    executable_sha256=expected["executable_sha256"], version_probe=True,
                    version_probe_output=version, validation_required=False)
                installation_checkpoint("before .NET SDK installation result")
        return receipt


__all__ = ["SDK_VERSION", "RUNTIME_VERSION", "plan_dotnet_sdk_setup", "ensure_dotnet_sdk"]
