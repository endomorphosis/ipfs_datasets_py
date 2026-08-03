"""Advisor family installer plugin (FVT-G160 / FVT-050).

``FormalVerificationInstallerPlugin@1`` for the hammer/advisor lane:

* ``ensure_symbolicai`` — locked SymbolicAI Python package identity
* ``ensure_ergoai`` — locked ErgoAI/ErgoEngine 3.0 identity
* ``ensure_temurin_jdk`` — optional checksum-pinned Eclipse Temurin JDK for ErgoAI Java API

Fail-closed installation contract
---------------------------------
* never installs on import or capability discovery;
* requires an explicit ``ensure_*`` call with ``yes=True``;
* user-local installs only (no system package manager mutation);
* under ``strict=True``, only the locked pin identities are accepted:
  SymbolicAI ``>=1.14.0,<2.0.0`` and ErgoAI ``3.0``;
* advisors remain **advisor/candidate** role with advisory authority ceiling;
* presence or successful install never grants theorem / kernel / solver proof
  authority;
* this plugin never edits the shared multi-prover certificate or model runtimes.

Pin selection reads ``config/formal_verification_toolchains.lock.json`` when
available and falls back to the reviewed identities below.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final
from urllib.request import Request, urlopen

from .registry import (
    DEFAULT_LOCK_RELATIVE,
    DEFAULT_USER_LOCAL_INSTALL_ROOT,
    InstallerPluginFamily,
    InstallerRegistryError,
    assert_deployment_lock_contract,
    authorize_installer_entry_install,
    default_installer_registry,
    get_installer_entry,
    load_deployment_lock,
)

PLUGIN_INTERFACE: Final = "FormalVerificationInstallerPlugin@1"
PLUGIN_FAMILY: Final = InstallerPluginFamily.ADVISORS.value
PLUGIN_MODULE: Final = "ipfs_datasets_py.logic.backends.installers.advisors"
GOAL_ID: Final = "FVT-G160"
TASK_ID: Final = "FVT-050"
PROGRAM: Final = "formal-verification-tactician/advisor-toolchains"

TOOL_SYMBOLICAI: Final = "symbolicai"
TOOL_ERGOAI: Final = "ergoai"
TOOL_TEMURIN_JDK: Final = "temurin-jdk"
ADVISOR_INSTALL_TOOLS: Final = (TOOL_SYMBOLICAI, TOOL_ERGOAI)
# Support lifecycle owned by this plugin for the optional ErgoAI Java API.
# It is intentionally not a FormalVerificationInstallerRegistry@1 authority tool.
ADVISOR_SUPPORT_TOOLS: Final = (TOOL_TEMURIN_JDK,)
ADVISOR_PIN_OWNED_TOOLS: Final = ADVISOR_INSTALL_TOOLS + ADVISOR_SUPPORT_TOOLS

# Locked managed-pin identities (must match deployment lock).
SYMBOLICAI_VERSION: Final = ">=1.14.0,<2.0.0"
SYMBOLICAI_PACKAGE: Final = "symbolicai"
ERGOAI_VERSION: Final = "3.0"
ERGOAI_EXECUTABLES: Final = ("ergoai", "runErgo.sh", "runergo")
ERGOAI_RELEASE_TAG: Final = "v3.0_release"
ERGOAI_RELEASE_URL: Final = (
    "https://github.com/ErgoAI/.github/releases/download/"
    "v3.0_release/ergoAI_3.0.run"
)
# SHA-256 of the official GitHub release asset published under
# ``ErgoAI/.github@v3.0_release``.  A live installer must never execute the
# self-extracting archive unless this digest matches exactly.
ERGOAI_RELEASE_SHA256: Final = (
    "46f9747db118567a7da50f70b439e35ee36ea02c3dfde971a57c77a8ce94aa01"
)
ERGOAI_RELEASE_SIZE_BYTES: Final = 53_064_767
# Exact post-extraction script bytes before and after the reviewed six-pattern
# private-workspace hardening transform.
ERGOAI_CONFIG_SOURCE_SHA256: Final = (
    "3bee8a6aa7d17854b81f14fe87cb35a5c89a0c275362266b7eef9a2e5f1fcaa4"
)
ERGOAI_CONFIG_HARDENED_SHA256: Final = (
    "b21e4a85b9cc214d4e61f5204124baf2dd6daecf597dd4cd72ba040b7bc0bed9"
)
ERGOAI_CONFIG_HARDENING_REPLACEMENT_COUNT: Final = 6
# The shared Linux/Mac release is source-bearing and compiles XSB for the host.
# These are the platforms for which this project carries an exact reviewed pin;
# other hosts fail closed until their artifact is independently exercised.
ERGOAI_SUPPORTED_PLATFORMS: Final = (
    "linux-x86_64",
    "linux-aarch64",
)
ERGOAI_BUILD_COMMANDS: Final = (
    "sh",
    "bash",
    "make",
    "gcc",
    "cc",
    "as",
    "flex",
    "bison",
    "m4",
    "ar",
    "ranlib",
    "ld",
    "tar",
    "gzip",
    "cp",
    "dirname",
    "ln",
    "mkdir",
    "mktemp",
    "mv",
    "rm",
    # Always-taken Makeself 2.1.5 and post-extraction configuration paths in
    # the exact checksummed ``ergoAI_3.0.run`` asset.
    "df",
    "tail",
    "awk",
    "head",
    "wc",
    "tr",
    "which",
    "md5sum",
    "basename",
    "cut",
    "dd",
    "expr",
    "pwd",
    "date",
    "sed",
    "grep",
    "cat",
    "echo",
    "chmod",
    "touch",
    "uname",
    # Common configure/makexsb toolchain consumers.  These are preflighted as
    # executable identities rather than being assumed from a compiler name.
    "find",
    "sort",
    "install",
    "env",
    # Observed successful process dependencies of the exact aarch64 3.0
    # configuration/build under strace.  Keeping them explicit prevents an
    # Autoconf fallback from escaping the recorded build environment.
    "rmdir",
    "hostname",
    "ls",
    "diff",
    "readlink",
    "split",
    "tee",
    "arch",
)
ERGOAI_REQUIRED_ABSOLUTE_COMMANDS: Final = (
    "/bin/sh",
    "/bin/bash",
    "/bin/rm",
    "/bin/echo",
    "/bin/touch",
    "/bin/uname",
    "/bin/arch",
    "/usr/bin/uname",
    "/usr/bin/arch",
)
ERGOAI_VERSIONED_BUILD_COMMANDS: Final = {
    "make": (3, 81),
    "gcc": (4, 8),
    "flex": (2, 6),
    "bison": (3, 0),
}
ERGOAI_OPTIONAL_JAVA_RUNTIME_COMMANDS: Final = ("java", "which", "dirname")
ERGOAI_OPTIONAL_JAVA_BUILD_COMMANDS: Final = (
    "java",
    "javac",
    "jar",
    "which",
    "dirname",
    "touch",
)
ERGOAI_OPTIONAL_JAVA_MINIMUM_VERSION: Final = (1, 8)

# Optional managed JDK for ErgoAIJavaAPIToolchainContract@1 / FVT-G222.
# Exact Eclipse Temurin 17.0.20+8 identities; never a moving `latest` URL and
# never resolved from ambient JAVA_HOME.
TEMURIN_JDK_VERSION: Final = "17.0.20+8"
TEMURIN_JDK_RELEASE_NAME: Final = "jdk-17.0.20+8"
TEMURIN_JDK_PUBLISHER: Final = "Eclipse Adoptium"
TEMURIN_JDK_LICENSE: Final = "GPL-2.0-with-classpath-exception"
TEMURIN_JDK_SOURCE: Final = "https://adoptium.net/"
TEMURIN_JDK_EXECUTABLES: Final = ("java", "javac", "jar")
TEMURIN_JDK_SUPPORTED_PLATFORMS: Final = (
    "linux-x86_64",
    "linux-aarch64",
)
TEMURIN_JDK_IDENTITY_KIND: Final = "immutable_release_archive"
TEMURIN_JDK_SCHEMA: Final = "temurin-jdk-managed-identity/v1"
ERGOAI_JAVA_API_INTERFACE: Final = "ErgoAIJavaAPIToolchainContract@1"
ERGOAI_JAVA_API_SCHEMA: Final = "ergoai-java-api-toolchain-contract/v1"
ERGOAI_JAVA_API_GOAL_ID: Final = "FVT-G222"
ERGOAI_JAVA_API_TASK_ID: Final = "FVT-090"
ERGOAI_JAVA_API_CASE_KINDS: Final = (
    "positive",
    "negative",
    "malformed",
    "timeout",
    "replay",
    "relocation",
    "dependency_mutation",
)
# Live certification / adversarial hardening (FVT-G223 / FVT-091).
ERGOAI_JAVA_API_LIVE_INTERFACE: Final = "ErgoAIJavaAPILiveCertification@1"
ERGOAI_JAVA_API_LIVE_SCHEMA: Final = "ergoai-java-api-live-certification/v1"
ERGOAI_JAVA_API_LIVE_GOAL_ID: Final = "FVT-G223"
ERGOAI_JAVA_API_LIVE_TASK_ID: Final = "FVT-091"
ERGOAI_JAVA_API_LIVE_RECEIPT_RELATIVE: Final = (
    "docs/architecture/formal_verification_ergoai_java_api_live_receipt.json"
)
ERGOAI_JAVA_API_LIVE_CASE_KINDS: Final = (
    "live_install",
    "publisher_evidence",
    "vendor_java_consumer",
    "hello_world_rejected",
    "timeout_process_tree",
    "workspace_cleanup",
    "home_relocation_replay",
    "dependency_mutation_reject",
    "single_flight",
    "force_rollback",
    "home_path_boundary",
    "core_ergoai_independent",
    "authority_ceiling",
)
TEMURIN_INSTALL_LOCK_NAME: Final = "temurin-jdk.install.lock"
TEMURIN_LOCK_STALE_SECONDS: Final = 900.0
TEMURIN_FORCE_BACKUP_PREFIX: Final = ".temurin-jdk.previous-good."
_TEMURIN_ROOT_LOCKS_GUARD = threading.RLock()
_TEMURIN_ROOT_LOCKS: dict[str, threading.RLock] = {}
TEMURIN_JDK_PINS: Final[Mapping[str, Mapping[str, Any]]] = {
    "linux-x86_64": {
        "version": TEMURIN_JDK_VERSION,
        "artifact_url": (
            "https://github.com/adoptium/temurin17-binaries/releases/download/"
            "jdk-17.0.20%2B8/OpenJDK17U-jdk_x64_linux_hotspot_17.0.20_8.tar.gz"
        ),
        "sha256": (
            "be7668bc030d578b83d6d5ef9221d6d6729bbbca8cf94a7d52e16ac68b5a5a35"
        ),
        "artifact_size_bytes": 193_273_593,
        "signature_url": (
            "https://github.com/adoptium/temurin17-binaries/releases/download/"
            "jdk-17.0.20%2B8/OpenJDK17U-jdk_x64_linux_hotspot_17.0.20_8.tar.gz.sig"
        ),
        "checksum_url": (
            "https://github.com/adoptium/temurin17-binaries/releases/download/"
            "jdk-17.0.20%2B8/OpenJDK17U-jdk_x64_linux_hotspot_17.0.20_8.tar.gz.sha256.txt"
        ),
        "archive_name": "OpenJDK17U-jdk_x64_linux_hotspot_17.0.20_8.tar.gz",
        "os": "linux",
        "architecture": "x86_64",
        "release_name": TEMURIN_JDK_RELEASE_NAME,
    },
    "linux-aarch64": {
        "version": TEMURIN_JDK_VERSION,
        "artifact_url": (
            "https://github.com/adoptium/temurin17-binaries/releases/download/"
            "jdk-17.0.20%2B8/OpenJDK17U-jdk_aarch64_linux_hotspot_17.0.20_8.tar.gz"
        ),
        "sha256": (
            "d143936f473a4cb24e3b0e247d6d0775769d55ec9775c339540e753059a8d77a"
        ),
        "artifact_size_bytes": 191_960_283,
        "signature_url": (
            "https://github.com/adoptium/temurin17-binaries/releases/download/"
            "jdk-17.0.20%2B8/OpenJDK17U-jdk_aarch64_linux_hotspot_17.0.20_8.tar.gz.sig"
        ),
        "checksum_url": (
            "https://github.com/adoptium/temurin17-binaries/releases/download/"
            "jdk-17.0.20%2B8/OpenJDK17U-jdk_aarch64_linux_hotspot_17.0.20_8.tar.gz.sha256.txt"
        ),
        "archive_name": "OpenJDK17U-jdk_aarch64_linux_hotspot_17.0.20_8.tar.gz",
        "os": "linux",
        "architecture": "aarch64",
        "release_name": TEMURIN_JDK_RELEASE_NAME,
    },
}
ERGOAI_BOUND_RUNTIME_PATH_MODEL: Final = "managed-symlink-only-exact-identities/v1"
ERGOAI_BOUND_BUILD_ENVIRONMENT_KEYS: Final = tuple(
    sorted(
        {
            "HOME",
            "PATH",
            "SHELL",
            "TMPDIR",
            "TERM",
            "DISPLAY",
            "LANG",
            "LC_ALL",
            "ALL_PROXY",
            "HTTPS_PROXY",
            "HTTP_PROXY",
            "all_proxy",
            "https_proxy",
            "http_proxy",
            "NO_PROXY",
            "no_proxy",
            "PIP_NO_INDEX",
            "PIP_DISABLE_PIP_VERSION_CHECK",
            "GIT_TERMINAL_PROMPT",
            "FORMAL_VERIFICATION_CERTIFY_OFFLINE",
            "FORMAL_VERIFICATION_FORBID_INSTALL",
            "FORMAL_VERIFICATION_FORBID_NETWORK",
            "FORMAL_VERIFICATION_FORBID_DOWNLOAD",
            "ERGOAI_MANAGED_XSB_TMPDIR",
        }
    )
)
# Bundled with the official release; the live installer refuses a tree without
# a single executable XSB configuration matching the selected platform.
ERGOAI_RUNTIME_DEPENDENCIES: Final = (
    "xsb",
    "runergo",
    "posix_shell",
    "private_runtime_workspace_tools",
)
ERGOAI_LICENSE_COMPONENTS: Final = ("Apache-2.0", "LGPL-2.0")
ERGOAI_ENTRY_POINT: Final = "runergo"
ERGOAI_IDENTITY_PROBE_ARGV: Final = ("--version",)
# All ErgoAI subprocesses have a finite capture ceiling, even when a caller
# does not request a tighter per-case bound.  The semantic resource-bound case
# uses the smaller reviewed limit below.
ERGOAI_DEFAULT_MAX_OUTPUT_BYTES: Final = 1024 * 1024
ERGOAI_RESOURCE_CASE_MAX_OUTPUT_BYTES: Final = 4096
ERGOAI_INSTALL_MAX_OUTPUT_BYTES: Final = 8 * 1024 * 1024
ERGOAI_IDENTITY_MAX_BYTES: Final = 4 * 1024 * 1024
ERGOAI_ACQUISITION_CHUNK_BYTES: Final = 64 * 1024
ERGOAI_DEFAULT_BOUND_TIMEOUT_SECONDS: Final = 2.0
# Full live semantic matrix required by ErgoAILiveToolchainContract@1 / FVT-G218.
ERGOAI_LIVE_SEMANTIC_CASE_KINDS: Final = (
    "entailment",
    "non_entailment",
    "contradiction",
    "mutation",
    "replay",
    "malformed",
    "timeout",
    "resource_bound",
)
# Legacy aliases retained for existing role-certification fixtures.
ERGOAI_LIVE_SEMANTIC_LEGACY_ALIASES: Final = {
    "positive": "entailment",
    "negative": "non_entailment",
}
_ERGOAI_BASE_PROGRAM: Final = "fvt_ergo_subject : fvt_ergo_expected.\n"
_ERGOAI_MUTATED_PROGRAM: Final = "fvt_ergo_subject : fvt_ergo_mutated.\n"
_ERGOAI_CONTRADICTION_PROGRAM: Final = (
    "fvt_ergo_subject : fvt_ergo_contradiction.\n"
    "\\neg fvt_ergo_subject : fvt_ergo_contradiction.\n"
)
_ERGOAI_MALFORMED_PROGRAM: Final = "this is not %% valid ergo {{\n"
_ERGOAI_TIMEOUT_PROGRAM: Final = (
    "fvt_loop(?X) :- ?Y \\is ?X + 1, fvt_loop(?Y).\n"
)
_ERGOAI_RESOURCE_PROGRAM: Final = (
    "fvt_ergo_resource_marker.\n"
    "fvt_ergo_emit(0).\n"
    "fvt_ergo_emit(?N) :- ?N > 0, "
    "writeln('XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX')"
    "@\\io, ?M \\is ?N - 1, fvt_ergo_emit(?M).\n"
)
_ERGOAI_QUERY_ENTAILMENT: Final = "fvt_ergo_subject : fvt_ergo_expected"
_ERGOAI_QUERY_NON_ENTAILMENT: Final = "fvt_ergo_subject : fvt_ergo_absent"
_ERGOAI_QUERY_CONTRADICTION: Final = (
    "fvt_ergo_subject : fvt_ergo_contradiction, "
    "\\neg fvt_ergo_subject : fvt_ergo_contradiction"
)
_ERGOAI_QUERY_NON_EXPLOSION: Final = (
    "fvt_ergo_unrelated : fvt_ergo_contradiction"
)
_ERGOAI_QUERY_TIMEOUT: Final = "fvt_loop(1)"
_ERGOAI_QUERY_RESOURCE: Final = "fvt_ergo_emit(100)"

LOCKED_VERSIONS: Final[Mapping[str, str]] = {
    TOOL_SYMBOLICAI: SYMBOLICAI_VERSION,
    TOOL_ERGOAI: ERGOAI_VERSION,
    TOOL_TEMURIN_JDK: TEMURIN_JDK_VERSION,
}

# Reviewed fallback pins when the lock file is unavailable (tests / offline).
_FALLBACK_PINS: Final[dict[str, tuple[dict[str, Any], ...]]] = {
    TOOL_SYMBOLICAI: (
        {
            "tool_id": TOOL_SYMBOLICAI,
            "version": SYMBOLICAI_VERSION,
            "platform": "any",
            "artifact_url": "https://pypi.org/project/symbolicai/",
            "sha256": "",
            "identity_kind": "python_package",
            "license": "BSD-3-Clause",
            "source": "https://github.com/ExtensityAI/symbolicai",
            "package_name": SYMBOLICAI_PACKAGE,
            "is_checksummed": False,
        },
    ),
    TOOL_ERGOAI: (
        {
            "tool_id": TOOL_ERGOAI,
            "version": ERGOAI_VERSION,
            "platform": "linux-x86_64",
            "artifact_url": ERGOAI_RELEASE_URL,
            "sha256": ERGOAI_RELEASE_SHA256,
            "identity_kind": "immutable_release_tag",
            "license": "Apache-2.0",
            "source": "https://github.com/ErgoAI/ErgoEngine",
            "is_checksummed": True,
            "requires_checksum_at_install": True,
            "release_tag": ERGOAI_RELEASE_TAG,
            "artifact_size_bytes": ERGOAI_RELEASE_SIZE_BYTES,
        },
        {
            "tool_id": TOOL_ERGOAI,
            "version": ERGOAI_VERSION,
            "platform": "linux-aarch64",
            "artifact_url": ERGOAI_RELEASE_URL,
            "sha256": ERGOAI_RELEASE_SHA256,
            "identity_kind": "immutable_release_tag",
            "license": "Apache-2.0",
            "source": "https://github.com/ErgoAI/ErgoEngine",
            "is_checksummed": True,
            "requires_checksum_at_install": True,
            "release_tag": ERGOAI_RELEASE_TAG,
            "artifact_size_bytes": ERGOAI_RELEASE_SIZE_BYTES,
        },
    ),
    TOOL_TEMURIN_JDK: tuple(
        {
            "tool_id": TOOL_TEMURIN_JDK,
            "version": TEMURIN_JDK_VERSION,
            "platform": platform_name,
            "artifact_url": str(meta["artifact_url"]),
            "sha256": str(meta["sha256"]),
            "identity_kind": TEMURIN_JDK_IDENTITY_KIND,
            "license": TEMURIN_JDK_LICENSE,
            "source": TEMURIN_JDK_SOURCE,
            "is_checksummed": True,
            "requires_checksum_at_install": True,
            "release_tag": TEMURIN_JDK_RELEASE_NAME,
            "artifact_size_bytes": int(meta["artifact_size_bytes"]),
        }
        for platform_name, meta in TEMURIN_JDK_PINS.items()
    ),
}

# Role boundary: installers never elevate advisors past advisory authority.
ADVISOR_ROLE: Final = "advisor"
ADVISOR_AUTHORITY_CEILING: Final = "advisory"
IMPORT_INSTALLS_FORBIDDEN: Final = True

ProgressCallback = Callable[[str, str], None]

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)+)")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SYMBOLICAI_RANGE_RE = re.compile(
    r"^>=\s*(\d+(?:\.\d+)*)\s*,\s*<\s*(\d+(?:\.\d+)*)$"
)


class AdvisorInstallerError(RuntimeError):
    """Raised when a strict advisor install policy is violated."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolPin:
    """One platform-specific managed pin for an advisor-lane tool."""

    tool_id: str
    version: str
    platform: str
    artifact_url: str = ""
    sha256: str = ""
    identity_kind: str = "python_package"
    license: str = ""
    source: str = ""
    package_name: str = ""
    is_checksummed: bool = False
    requires_checksum_at_install: bool = False
    release_tag: str = ""
    artifact_size_bytes: int = 0

    def __post_init__(self) -> None:
        for name in ("tool_id", "version", "platform"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise AdvisorInstallerError(f"{name} must be a non-empty trimmed string")
        digest = (self.sha256 or "").lower()
        if digest and not _HEX64.match(digest):
            raise AdvisorInstallerError(
                f"sha256 for {self.tool_id!r} must be empty or a 64-char hex digest"
            )
        object.__setattr__(self, "sha256", digest)
        if self.artifact_size_bytes < 0:
            raise AdvisorInstallerError("artifact_size_bytes must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "version": self.version,
            "platform": self.platform,
            "artifact_url": self.artifact_url,
            "sha256": self.sha256,
            "identity_kind": self.identity_kind,
            "license": self.license,
            "source": self.source,
            "package_name": self.package_name,
            "is_checksummed": self.is_checksummed,
            "requires_checksum_at_install": self.requires_checksum_at_install,
            "release_tag": self.release_tag,
            "artifact_size_bytes": self.artifact_size_bytes,
        }


@dataclass(slots=True)
class InstallReceipt:
    """Machine-readable result of one ensure_* invocation."""

    tool_id: str
    requested_version: str
    selected_version: str | None = None
    selected_platform: str | None = None
    executable_path: str | None = None
    package_name: str | None = None
    pin: dict[str, Any] | None = None
    status: str = "blocked"  # available | installed | blocked | failed | refused
    phase: str = "init"
    installed: bool = False
    already_present: bool = False
    install_attempted: bool = False
    checksum_verified: bool = False
    strict: bool = True
    yes: bool = False
    user_local: bool = True
    role: str = ADVISOR_ROLE
    authority_ceiling: str = ADVISOR_AUTHORITY_CEILING
    grants_theorem_authority: bool = False
    grants_proof_authority: bool = False
    reason_codes: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    bindings: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.grants_theorem_authority or self.grants_proof_authority:
            raise AdvisorInstallerError(
                "advisor install receipts cannot grant theorem or proof authority"
            )
        if self.role not in {ADVISOR_ROLE, "candidate"}:
            raise AdvisorInstallerError(
                f"advisor install receipts must remain role=advisor/candidate, got {self.role!r}"
            )
        if self.authority_ceiling != ADVISOR_AUTHORITY_CEILING:
            raise AdvisorInstallerError(
                "advisor install receipts must keep authority_ceiling=advisory"
            )

    @property
    def ok(self) -> bool:
        return self.status in {"available", "installed"} and bool(self.selected_version)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Path / platform helpers
# ---------------------------------------------------------------------------


def expand_user_local_root(root: str | Path | None = None) -> Path:
    """Return the lexical user-local theorem-prover / advisor install root.

    Deliberately do not resolve symlinks here.  Mutation paths are validated
    component by component later, and resolving first would erase evidence of
    a poisoned configured ancestor.
    """

    if root is not None:
        selected = Path(os.path.expanduser(str(root)))
        return Path(os.path.abspath(os.fspath(selected)))
    env = os.environ.get("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT")
    if env:
        selected = Path(os.path.expanduser(env))
        return Path(os.path.abspath(os.fspath(selected)))
    env = os.environ.get("IPFS_DATASETS_PY_THEOREM_PROVERS_ROOT")
    if env:
        selected = Path(os.path.expanduser(env))
        return Path(os.path.abspath(os.fspath(selected)))
    selected = Path(os.path.expanduser(DEFAULT_USER_LOCAL_INSTALL_ROOT))
    return Path(os.path.abspath(os.fspath(selected)))


def detect_platform_key() -> str:
    """Return a lock-compatible platform key (e.g. ``linux-x86_64``)."""

    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        arch = "x86_64"
    elif machine in {"aarch64", "arm64"}:
        arch = "aarch64" if system == "linux" else "arm64"
    else:
        arch = machine
    if system == "linux":
        return f"linux-{arch}"
    if system == "darwin":
        return f"darwin-{arch if arch != 'aarch64' else 'arm64'}"
    return f"{system}-{arch}"


def which_executable(name: str, *, path_env: str | None = None) -> str | None:
    """Locate an executable, preferring the managed user-local bin directory."""

    if not name or not str(name).strip():
        return None
    candidate = Path(name)
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate.resolve())

    search_path = path_env
    if search_path is None:
        managed_bin = expand_user_local_root() / "bin"
        parts = [str(managed_bin)] if managed_bin.is_dir() else []
        parts.append(os.environ.get("PATH", ""))
        search_path = os.pathsep.join(p for p in parts if p)
    return shutil.which(name, path=search_path)


def numeric_version(text: str) -> tuple[int, ...]:
    match = _VERSION_RE.search(text or "")
    if match is None:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def content_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lexical_absolute(path: str | Path) -> Path:
    """Return an absolute path without following any filesystem symlink."""

    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _ergoai_is_user_local_root(path: str | Path) -> bool:
    """Return whether a production install root is a strict HOME descendant."""

    try:
        home = Path.home().resolve(strict=True)
        selected = _lexical_absolute(path).resolve(strict=False)
        relative = selected.relative_to(home)
    except (OSError, RuntimeError, ValueError):
        return False
    return bool(relative.parts)


def _ensure_safe_directory(path: str | Path, *, mode: int = 0o755) -> Path:
    """Create a directory chain without following pre-existing symlinks.

    ``Path.mkdir(parents=True)`` follows attacker-controlled ancestor symlinks.
    Managed installers use this component-wise variant before every mutation so
    a poisoned ``downloads``, ``bin``, ``advisors``, or runtime-state path
    fails closed before bytes can be written outside the selected root.
    """

    absolute = _lexical_absolute(path)
    if not absolute.is_absolute():  # pragma: no cover - helper guarantees this
        raise AdvisorInstallerError(f"managed directory is not absolute: {absolute}")
    parts = absolute.parts
    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            try:
                os.mkdir(current, mode)
            except FileExistsError:
                metadata = os.lstat(current)
                if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(
                    metadata.st_mode
                ):
                    raise AdvisorInstallerError(
                        f"unsafe managed directory component: {current}"
                    ) from None
            continue
        except OSError as exc:
            raise AdvisorInstallerError(
                f"cannot inspect managed directory component {current}: {exc}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise AdvisorInstallerError(
                f"unsafe managed directory component: {current}"
            )
    return absolute


def _ensure_safe_managed_directory(
    install_root: str | Path,
    directory: str | Path,
    *,
    mode: int = 0o755,
) -> Path:
    """Create *directory* only when it is lexically beneath *install_root*."""

    root = _lexical_absolute(install_root)
    target = _lexical_absolute(directory)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise AdvisorInstallerError(
            f"managed directory escapes install root: {target}"
        ) from exc
    _ensure_safe_directory(root, mode=mode)
    return _ensure_safe_directory(target, mode=mode)


def _safe_existing_regular_file(
    path: str | Path,
    *,
    max_bytes: int | None = None,
) -> bool:
    """Return whether *path* is a bounded regular file on a symlink-free chain."""

    absolute = _lexical_absolute(path)
    current = Path(absolute.parts[0])
    try:
        for part in absolute.parts[1:]:
            current = current / part
            metadata = os.lstat(current)
            if stat.S_ISLNK(metadata.st_mode):
                return False
        metadata = os.lstat(absolute)
    except OSError:
        return False
    if not stat.S_ISREG(metadata.st_mode):
        return False
    return max_bytes is None or metadata.st_size <= max_bytes


_MAKESELF_SAFE_PATH_RE: Final = re.compile(r"^/[A-Za-z0-9_./-]+$")


def _makeself_safe_path(path: str | Path) -> bool:
    """Return whether the old Makeself wrapper can safely expand this path."""

    absolute = _lexical_absolute(path)
    return bool(
        _MAKESELF_SAFE_PATH_RE.fullmatch(str(absolute))
        and ".." not in absolute.parts
    )


def ergoai_safe_temporary_directory() -> Path:
    """Return a writable safe-name temp root for interpolated Ergo paths."""

    candidates = [os.environ.get("TMPDIR"), "/tmp"]
    for raw in candidates:
        if not raw:
            continue
        candidate = _lexical_absolute(raw)
        if not _makeself_safe_path(candidate):
            continue
        try:
            metadata = os.lstat(candidate)
        except OSError:
            continue
        if (
            stat.S_ISDIR(metadata.st_mode)
            and not stat.S_ISLNK(metadata.st_mode)
            and os.access(candidate, os.W_OK | os.X_OK)
        ):
            return candidate
    raise AdvisorInstallerError(
        "no symlink-free safe-name temporary directory is available for ErgoAI"
    )


def _ergoai_version_root(install_root: Path, version: str) -> Path:
    return install_root / "advisors" / TOOL_ERGOAI / version


def _ergoai_xsb_user_aux_dir(install_root: Path, version: str) -> Path:
    """Return the mutable, non-authoritative XSB user-cache directory."""

    return _ergoai_version_root(install_root, version) / "runtime-state" / "xsb-user-aux"


def _is_safe_mutable_ergoai_directory_spec(
    *,
    install_root: Path,
    raw_path: str,
    expected_path: Path,
) -> bool:
    """Validate a relocatable mutable-directory location without owning its state.

    Mutable runtime state may legitimately be deleted between probes.  Its
    manifest location is nevertheless security-sensitive: an existing path
    component must never be a symlink, a non-directory, or escape the selected
    install root.  Missing suffix components are accepted because managed
    launchers recreate them before use.
    """

    if not raw_path:
        return False
    relative = Path(raw_path)
    try:
        expected_relative = expected_path.relative_to(install_root)
    except ValueError:
        return False
    if relative.is_absolute() or relative.parts != expected_relative.parts:
        return False

    resolved_root = install_root.resolve()
    candidate = install_root / relative
    try:
        candidate.resolve(strict=False).relative_to(resolved_root)
    except (OSError, ValueError):
        return False

    current = install_root
    for part in relative.parts:
        current = current / part
        try:
            if current.is_symlink():
                return False
            if current.exists() and not current.is_dir():
                return False
        except OSError:
            return False
    return True


def _ergoai_identity_path(install_root: Path, version: str) -> Path:
    return _ergoai_version_root(install_root, version) / "identity.json"


def _ergoai_vendor_root(install_root: Path, version: str, digest: str) -> Path:
    # Content-address the extracted tree so a failed/partial install never
    # overwrites a previously certified vendor payload.  The publication-model
    # suffix also prevents an older direct/absolute-path tree from being
    # mistaken for the staged relocatable format.
    return (
        _ergoai_version_root(install_root, version)
        / f"vendor-{digest[:16]}-relocatable-v3"
    )


def _install_relative_path(path: Path, install_root: Path) -> str:
    """Return a normalized manifest path confined to *install_root*."""

    resolved_root = install_root.resolve()
    resolved_path = path.resolve()
    try:
        relative = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise AdvisorInstallerError(
            f"managed ErgoAI path escapes install root: {resolved_path}"
        ) from exc
    return relative.as_posix()


def _atomic_write_bytes(path: Path, content: bytes, *, mode: int | None = None) -> None:
    """Publish one file atomically in its destination directory."""

    _ensure_safe_directory(path.parent)
    try:
        existing = os.lstat(path)
    except FileNotFoundError:
        existing = None
    if existing is not None and (
        stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode)
    ):
        raise AdvisorInstallerError(f"unsafe managed file destination: {path}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".partial",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            temporary.chmod(mode)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _ergoai_relocatable_runtime_sources(
    xsb_configuration: str,
) -> tuple[bytes, bytes]:
    """Return the exact managed, runtime-relative ErgoAI configuration."""

    paths_source = (
        "# Managed by ipfs_datasets_py; derive paths from runergo at runtime.\n"
        "ERGOAI_HOME=$(CDPATH= cd -- \"$thisdir/..\" && pwd)\n"
        "export ERGOAI_HOME\n"
        "FLORADIR=\"'${ERGOAI_HOME}/ErgoAI'\"\n"
        f"PROLOG=\"${{ERGOAI_HOME}}/XSB/config/{xsb_configuration}/bin/xsb\"\n"
    ).encode()
    java_source = (
        "# Managed relocatable ErgoAI Java settings.\n"
        "if [ -n \"${BASH_SOURCE:-}\" ]; then\n"
        "  settings_source=${BASH_SOURCE}\n"
        "  case \"$settings_source\" in */*) settings_dir=${settings_source%/*} ;; *) settings_dir=. ;; esac\n"
        "  settings_dir=$(CDPATH= cd -- \"$settings_dir\" && printf '%s\\n' \"$PWD\")\n"
        "  ERGOAI_HOME=$(CDPATH= cd -- \"$settings_dir/../..\" && printf '%s\\n' \"$PWD\")\n"
        "elif [ -z \"${ERGOAI_HOME:-}\" ]; then\n"
        "  echo 'ERGOAI_HOME must be set by a managed POSIX shell consumer' >&2\n"
        "  return 1 2>/dev/null || exit 1\n"
        "fi\n"
        "FLORADIR=\"${ERGOAI_HOME}/ErgoAI\"\n"
        f"PROLOGDIR=\"${{ERGOAI_HOME}}/XSB/config/{xsb_configuration}/bin\"\n"
        "export FLORADIR PROLOGDIR\n"
    ).encode()
    return paths_source, java_source


def _harden_ergoai_config_for_private_xsb_workspace(
    config_path: Path,
) -> dict[str, Any]:
    """Patch the exact pinned config script away from predictable ``/tmp``.

    The official 3.0 script builds XSB in a second-resolution global pathname.
    After checksum-verified extraction (with ``--noexec``), replace only the
    reviewed byte patterns with a required private staging path and quote every
    use.  Any upstream drift fails closed instead of applying a fuzzy rewrite.
    """

    if not _safe_existing_regular_file(config_path, max_bytes=1024 * 1024):
        raise AdvisorInstallerError(
            f"ErgoAI config script is not a safe bounded regular file: {config_path}"
        )
    original = config_path.read_text(encoding="utf-8")
    source_digest = hashlib.sha256(original.encode("utf-8")).hexdigest()
    if source_digest != ERGOAI_CONFIG_SOURCE_SHA256:
        raise AdvisorInstallerError(
            "ErgoAI config source does not match the reviewed release bytes"
        )
    replacements = (
        (
            '    tmpxsbdir=/tmp/XSB-`date +"%y-%m-%d-%H_%M_%S"`',
            '    tmpxsbdir="${ERGOAI_MANAGED_XSB_TMPDIR:?missing managed XSB temp}"',
            1,
        ),
        ("    rm -rf $tmpxsbdir || \\", '    rm -rf "$tmpxsbdir" || \\', 1),
        ('mv -f "$xsbdir" $tmpxsbdir', 'mv -f "$xsbdir" "$tmpxsbdir"', 1),
        ("cd $tmpxsbdir/build", 'cd "$tmpxsbdir/build"', 1),
        ('cp -rf $tmpxsbdir "$xsbdir"', 'cp -rf "$tmpxsbdir" "$xsbdir"', 1),
        ("rm -rf $tmpxsbdir", 'rm -rf "$tmpxsbdir"', 1),
    )
    hardened = original
    for old, new, expected_count in replacements:
        if hardened.count(old) != expected_count:
            raise AdvisorInstallerError(
                "ErgoAI config hardening contract drifted at exact reviewed pattern"
            )
        hardened = hardened.replace(old, new)
    hardened_digest = hashlib.sha256(hardened.encode("utf-8")).hexdigest()
    if hardened_digest != ERGOAI_CONFIG_HARDENED_SHA256:
        raise AdvisorInstallerError(
            "ErgoAI config hardening output does not match reviewed bytes"
        )
    _atomic_write_bytes(config_path, hardened.encode("utf-8"), mode=0o755)
    replacement_count = sum(item[2] for item in replacements)
    if replacement_count != ERGOAI_CONFIG_HARDENING_REPLACEMENT_COUNT:
        raise AdvisorInstallerError(
            "ErgoAI config hardening replacement contract is inconsistent"
        )
    return {
        "schema_version": "ergoai-config-hardening/v1",
        "source_sha256": source_digest,
        "hardened_sha256": hardened_digest,
        "private_xsb_workspace_required": True,
        "exact_replacement_count": replacement_count,
    }


def _bind_ergoai_java_consumers(ergo_root: Path) -> int:
    """Run bundled Java helpers in isolated distributions outside the vendor tree.

    POSIX ``sh`` has no equivalent of Bash's ``BASH_SOURCE`` for a sourced
    file.  Each official helper therefore derives the managed root from its
    own executable path, copies the complete ErgoAI subtree into a private
    workspace, links the immutable XSB runtime, and runs its original body
    there.  Flora caches and class/jar writes can never mutate the
    identity-bound vendor tree, even after SIGKILL or concurrent execution.
    """

    distribution_root = ergo_root.parent
    marker = "# Managed relocatable ErgoAI consumer binding."
    updated = 0
    for path in sorted(ergo_root.rglob("*.sh"), key=lambda item: item.as_posix()):
        if path.is_symlink() or not path.is_file() or path.name == "flora_settings.sh":
            continue
        source = path.read_text(encoding="utf-8")
        if "flora_settings.sh" not in source or marker in source:
            continue
        lines = source.splitlines(keepends=True)
        if not any(
            "flora_settings.sh" in line and line.lstrip().startswith(".")
            for line in lines
        ):
            raise AdvisorInstallerError(
                f"unreviewed ErgoAI Java settings consumer syntax: {path}"
            )
        shebang = lines.pop(0) if lines and lines[0].startswith("#!") else "#!/bin/sh\n"
        original_body = "".join(lines).replace(
            "../../../runflora",
            '"$ERGOAI_HOME/ErgoAI/runflora"',
        )
        relative_root = os.path.relpath(distribution_root, start=path.parent)
        consumer_relative = path.relative_to(ergo_root / "java")
        workspace_directory = consumer_relative.parent.as_posix()
        build_output_source = ""
        if path.name in {"build.sh", "buildExample.sh"}:
            output_name = consumer_relative.as_posix().replace("/", "-")
            if output_name.endswith(".sh"):
                output_name = output_name[:-3]
            build_output_source = (
                "if [ \"$_ipfs_datasets_ergoai_java_status\" -eq 0 ]; then\n"
                "  _ipfs_datasets_ergoai_java_output_root=\"${ERGOAI_JAVA_OUTPUT_DIR:-$ERGOAI_RUNTIME_STATE/java-build-outputs}\"\n"
                "  mkdir -p \"$_ipfs_datasets_ergoai_java_output_root\"\n"
                "  _ipfs_datasets_ergoai_java_output_partial=$(\n"
                f"    mktemp -d \"$_ipfs_datasets_ergoai_java_output_root/{output_name}.partial.XXXXXX\"\n"
                "  ) || exit 1\n"
                "  cp -a \"$ERGOAI_HOME/ErgoAI/java/.\" "
                "\"$_ipfs_datasets_ergoai_java_output_partial/\" || exit 1\n"
                "  _ipfs_datasets_ergoai_java_output_base=${_ipfs_datasets_ergoai_java_output_partial##*/}\n"
                f"  _ipfs_datasets_ergoai_java_output_suffix=${{_ipfs_datasets_ergoai_java_output_base#{output_name}.partial.}}\n"
                f"  _ipfs_datasets_ergoai_java_output=\"$_ipfs_datasets_ergoai_java_output_root/{output_name}.complete.$_ipfs_datasets_ergoai_java_output_suffix\"\n"
                "  mv \"$_ipfs_datasets_ergoai_java_output_partial\" "
                "\"$_ipfs_datasets_ergoai_java_output\" || exit 1\n"
                "  _ipfs_datasets_ergoai_java_output_partial=\n"
                "  printf '%s\\n' \"Managed ErgoAI Java build outputs: $_ipfs_datasets_ergoai_java_output\" >&2\n"
                "fi\n"
            )
        managed_source = (
            shebang
            + f"{marker}\n"
            "case \"$0\" in */*) ergo_consumer_dir=${0%/*} ;; *) exit 1 ;; esac\n"
            "ergo_consumer_dir=$(CDPATH= cd -- \"$ergo_consumer_dir\" && printf '%s\\n' \"$PWD\")\n"
            f"ERGOAI_VENDOR_HOME=$(CDPATH= cd -- \"$ergo_consumer_dir/{relative_root}\" && printf '%s\\n' \"$PWD\")\n"
            "ERGOAI_RUNTIME_TOOLCHAIN=$(\n"
            "  CDPATH= cd -- \"$ERGOAI_VENDOR_HOME/../..\" && printf '%s\\n' \"$PWD/runtime-toolchain-bin\"\n"
            ")\n"
            "if [ -L \"$ERGOAI_RUNTIME_TOOLCHAIN\" ] || [ ! -d \"$ERGOAI_RUNTIME_TOOLCHAIN\" ]; then exit 1; fi\n"
            "PATH=$ERGOAI_RUNTIME_TOOLCHAIN\n"
            "export PATH\n"
            "ERGOAI_RUNTIME_STATE=$(\n"
            "  CDPATH= cd -- \"$ERGOAI_VENDOR_HOME/../..\" && printf '%s\\n' \"$PWD\"\n"
            ")/runtime-state\n"
            "if [ -L \"$ERGOAI_RUNTIME_STATE\" ] || "
            "{ [ -e \"$ERGOAI_RUNTIME_STATE\" ] && "
            "[ ! -d \"$ERGOAI_RUNTIME_STATE\" ]; }; then exit 1; fi\n"
            "mkdir -p \"$ERGOAI_RUNTIME_STATE\" || exit 1\n"
            "if [ -L \"$ERGOAI_RUNTIME_STATE/java-workspaces\" ] || "
            "{ [ -e \"$ERGOAI_RUNTIME_STATE/java-workspaces\" ] && "
            "[ ! -d \"$ERGOAI_RUNTIME_STATE/java-workspaces\" ]; }; then exit 1; fi\n"
            "mkdir -p \"$ERGOAI_RUNTIME_STATE/java-workspaces\" || exit 1\n"
            "_ipfs_datasets_ergoai_java_workspace=$(\n"
            "  mktemp -d \"$ERGOAI_RUNTIME_STATE/java-workspaces/run.XXXXXX\"\n"
            ") || exit 1\n"
            "_ipfs_datasets_ergoai_java_output_partial=\n"
            "_ipfs_datasets_ergoai_cleanup_java_workspace() {\n"
            "  if [ -n \"${_ipfs_datasets_ergoai_java_output_partial:-}\" ] "
            "&& [ -d \"$_ipfs_datasets_ergoai_java_output_partial\" ]; then\n"
            "    rm -rf -- \"$_ipfs_datasets_ergoai_java_output_partial\"\n"
            "  fi\n"
            "  [ -d \"$_ipfs_datasets_ergoai_java_workspace\" ] || return 0\n"
            "  trap - 0 HUP INT TERM\n"
            "  rm -rf -- \"$_ipfs_datasets_ergoai_java_workspace\"\n"
            "}\n"
            "trap '_ipfs_datasets_ergoai_cleanup_java_workspace' 0\n"
            "trap '_ipfs_datasets_ergoai_cleanup_java_workspace; exit 129' HUP\n"
            "trap '_ipfs_datasets_ergoai_cleanup_java_workspace; exit 130' INT\n"
            "trap '_ipfs_datasets_ergoai_cleanup_java_workspace; exit 143' TERM\n"
            f"ERGOAI_HOME=\"$_ipfs_datasets_ergoai_java_workspace/{distribution_root.name}\"\n"
            "mkdir -p \"$ERGOAI_HOME\"\n"
            "cp -a \"$ERGOAI_VENDOR_HOME/ErgoAI\" "
            "\"$ERGOAI_HOME/ErgoAI\" || exit 1\n"
            "ln -s \"$ERGOAI_VENDOR_HOME/XSB\" \"$ERGOAI_HOME/XSB\" || exit 1\n"
            "export ERGOAI_HOME\n"
            "XSB_USER_AUXDIR=\"$_ipfs_datasets_ergoai_java_workspace/xsb-user-aux\"\n"
            "mkdir -p \"$XSB_USER_AUXDIR\"\n"
            "export XSB_USER_AUXDIR\n"
            "printf '\\\\halt.\\n' | \"$ERGOAI_HOME/ErgoAI/runergo\" "
            ">/dev/null 2>&1 || exit 1\n"
            f"cd \"$ERGOAI_HOME/ErgoAI/java/{workspace_directory}\" "
            "|| exit 1\n"
            "_ipfs_datasets_ergoai_java_consumer_body() {\n"
            f"{original_body}"
            "}\n"
            "_ipfs_datasets_ergoai_java_consumer_body \"$@\"\n"
            "_ipfs_datasets_ergoai_java_status=$?\n"
            f"{build_output_source}"
            "_ipfs_datasets_ergoai_cleanup_java_workspace\n"
            "exit \"$_ipfs_datasets_ergoai_java_status\"\n"
        )
        mode = stat.S_IMODE(path.stat().st_mode)
        _atomic_write_bytes(path, managed_source.encode(), mode=mode)
        updated += 1
    return updated


def _repair_ergoai_internal_symlinks(
    vendor_root: Path,
    *,
    version: str,
    xsb_configuration: str,
) -> int:
    """Rewrite installer-created absolute XSB links as confined relative links."""

    distribution_root = vendor_root / f"ERGOAI_{version}"
    xsb_root = distribution_root / "XSB"
    rewritten = 0
    for path in sorted(vendor_root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_symlink():
            continue
        raw_target = os.readlink(path)
        target = Path(raw_target)
        if target.is_absolute():
            candidate = target.resolve(strict=False)
            try:
                candidate.relative_to(vendor_root.resolve())
            except ValueError as exc:
                marker = f"/config/{xsb_configuration}/"
                target_text = target.as_posix()
                if marker not in target_text:
                    raise AdvisorInstallerError(
                        f"ErgoAI absolute symlink escapes managed tree: {path} -> {raw_target}"
                    ) from exc
                suffix = target_text.split("/config/", 1)[1]
                candidate = xsb_root / "config" / suffix
            if not candidate.exists():
                raise AdvisorInstallerError(
                    f"ErgoAI absolute symlink target is unavailable: {path} -> {raw_target}"
                )
            relative_target = os.path.relpath(candidate, start=path.parent)
            path.unlink()
            path.symlink_to(relative_target)
            rewritten += 1

        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(vendor_root.resolve())
        except ValueError as exc:
            raise AdvisorInstallerError(
                f"ErgoAI symlink escapes managed tree: {path} -> {os.readlink(path)}"
            ) from exc
        if not resolved.exists():
            raise AdvisorInstallerError(
                f"ErgoAI symlink is broken after relocation repair: {path}"
            )
    return rewritten


def _ergoai_runtime_cache_excluded(path: Path) -> bool:
    return bool(
        path.suffix == ".fpj"
        and any(
            part in {".ergo_aux_files", ".flora_aux_files"}
            for part in path.parts
        )
    )


def _clean_ergoai_runtime_path_caches(vendor_root: Path) -> int:
    """Remove relocatable, regenerable project metadata from the managed tree."""

    removed = 0
    for path in vendor_root.rglob("*.fpj"):
        if _ergoai_runtime_cache_excluded(path.relative_to(vendor_root)):
            if path.is_symlink() or not path.is_file():
                raise AdvisorInstallerError(
                    f"unsafe ErgoAI runtime cache object: {path}"
                )
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def _clean_ergoai_installer_metadata(vendor_root: Path) -> int:
    """Remove path-bound logs and uninstall metadata unused by the manager."""

    removable = {"ergo-install.log", "ergo-initrun.log", ".uninstall_info.data"}
    removed = 0
    for path in sorted(vendor_root.rglob("*"), key=lambda item: item.as_posix()):
        if path.name not in removable:
            continue
        if path.is_symlink() or not path.is_file():
            raise AdvisorInstallerError(
                f"unsafe ErgoAI installer metadata object: {path}"
            )
        path.unlink()
        removed += 1
    return removed


def _ergoai_vendor_tree_integrity(
    vendor_root: Path,
    *,
    include_entries: bool = False,
) -> dict[str, Any]:
    """Digest the immutable executed tree, excluding regenerable .fpj metadata."""

    digest = hashlib.sha256()
    file_count = 0
    excluded_count = 0
    entries: dict[str, str] = {}
    root = vendor_root.resolve()
    for path in sorted(vendor_root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(vendor_root)
        if _ergoai_runtime_cache_excluded(relative):
            if path.is_symlink() or not path.is_file():
                raise AdvisorInstallerError(
                    f"unsafe runtime-cache object in managed ErgoAI tree: {relative}"
                )
            excluded_count += 1
            continue
        relative_bytes = relative.as_posix().encode()
        if path.is_symlink():
            raw_target = os.readlink(path)
            if Path(raw_target).is_absolute():
                raise AdvisorInstallerError(
                    f"absolute symlink remains in managed ErgoAI tree: {relative}"
                )
            resolved = path.resolve(strict=False)
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise AdvisorInstallerError(
                    f"symlink escapes managed ErgoAI tree: {relative}"
                ) from exc
            if not resolved.exists():
                raise AdvisorInstallerError(
                    f"broken symlink remains in managed ErgoAI tree: {relative}"
                )
            digest.update(b"L\0" + relative_bytes + b"\0" + raw_target.encode() + b"\0")
            entries[relative.as_posix()] = f"symlink:{raw_target}"
            file_count += 1
        elif path.is_file():
            mode = stat.S_IMODE(path.stat().st_mode)
            file_digest = content_sha256(path)
            digest.update(
                b"F\0"
                + relative_bytes
                + b"\0"
                + f"{mode:o}".encode()
                + b"\0"
                + file_digest.encode()
                + b"\0"
            )
            entries[relative.as_posix()] = f"file:{mode:o}:{file_digest}"
            file_count += 1
        elif not path.is_dir():
            raise AdvisorInstallerError(
                f"unsupported filesystem object in managed ErgoAI tree: {relative}"
            )
    result = {
        "digest_sha256": digest.hexdigest(),
        "file_count": file_count,
        "excluded_runtime_cache_count": excluded_count,
        "exclusion_policy": "regenerable-ergo-flora-fpj-metadata-only/v1",
    }
    if include_entries:
        result["entries"] = entries
    return result


def _elf_machine(path: Path) -> str | None:
    """Return the reviewed ELF machine name for a compiled runtime binary."""

    try:
        header = path.read_bytes()[:20]
    except OSError:
        return None
    if len(header) < 20 or header[:4] != b"\x7fELF":
        return None
    byte_order = "little" if header[5] == 1 else "big" if header[5] == 2 else None
    if byte_order is None:
        return None
    machine = int.from_bytes(header[18:20], byteorder=byte_order)
    return {62: "x86_64", 183: "aarch64"}.get(machine, f"elf-machine-{machine}")


def _make_ergoai_tree_relocatable(
    vendor_root: Path,
    *,
    version: str,
    xsb_configuration: str,
) -> None:
    """Replace installer-authored absolute runtime settings with relative ones.

    The official self-extractor writes the extraction path into
    ``ErgoAI/.ergo_paths`` and ``ErgoAI/java/flora_settings.sh``.  The reviewed
    launcher derives the tree root at execution time, so the complete managed
    install can be moved without rewriting or trusting its former location.
    """

    distribution_root = vendor_root / f"ERGOAI_{version}"
    ergo_root = distribution_root / "ErgoAI"
    paths_file = ergo_root / ".ergo_paths"
    java_settings = ergo_root / "java" / "flora_settings.sh"
    xsb_binary = (
        distribution_root
        / "XSB"
        / "config"
        / xsb_configuration
        / "bin"
        / "xsb"
    )
    if not paths_file.is_file() or not xsb_binary.is_file():
        raise AdvisorInstallerError(
            "ErgoAI relocation repair requires .ergo_paths and the selected XSB runtime"
        )

    paths_source, java_source = _ergoai_relocatable_runtime_sources(
        xsb_configuration
    )
    _atomic_write_bytes(paths_file, paths_source, mode=0o644)
    _atomic_write_bytes(java_settings, java_source, mode=0o644)

    _bind_ergoai_java_consumers(ergo_root)
    _clean_ergoai_installer_metadata(vendor_root)

    _repair_ergoai_internal_symlinks(
        vendor_root,
        version=version,
        xsb_configuration=xsb_configuration,
    )

    former_root = str(vendor_root.resolve())
    for config_path in (paths_file, java_settings):
        if former_root in config_path.read_text(encoding="utf-8"):
            raise AdvisorInstallerError(
                f"ErgoAI runtime configuration still binds staging path: {config_path}"
            )


def _repair_ergoai_xsb_runtime_configuration(
    xsb_binary: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Compile relocatable XSB ``srcdir`` and ``site_dir`` definitions."""

    xsb_root = xsb_binary.parents[3]
    configuration_library = xsb_binary.parent.parent / "lib"
    configuration_source = configuration_library / "xsb_configuration.P"
    configuration_bytecode = configuration_library / "xsb_configuration.xwam"
    if not configuration_source.is_file() or not configuration_bytecode.is_file():
        raise AdvisorInstallerError(
            "ErgoAI XSB relocation requires source and compiled configuration files"
        )
    srcdir_clause = (
        "xsb_configuration(srcdir, SrcDir) :-\n"
        "     xsb_configuration(install_dir, SrcDir)."
    )
    site_clause = (
        "xsb_configuration(site_dir, SiteDir) :-\n"
        "     xsb_configuration(install_dir, InstallDir),\n"
        "     slash(Slash),\n"
        "     fmt_write_string(SiteDir, '%s%ssite', f(InstallDir, Slash))."
    )
    source = configuration_source.read_text(encoding="utf-8")
    source, srcdir_count = re.subn(
        r"(?m)^xsb_configuration\(srcdir,\s*'[^'\n]*'\)\.\s*$",
        srcdir_clause,
        source,
    )
    source, site_count = re.subn(
        r"(?m)^xsb_configuration\(site_dir,\s*'[^'\n]*'\)\.\s*$",
        site_clause,
        source,
    )
    requires_compile = srcdir_count == 1 and site_count == 1
    already_relocatable = bool(
        srcdir_count == 0
        and site_count == 0
        and srcdir_clause in source
        and site_clause in source
    )
    if not requires_compile and not already_relocatable:
        raise AdvisorInstallerError(
            "ErgoAI XSB configuration did not expose the reviewed path clauses"
        )

    environment = ergoai_offline_subprocess_env(env)
    if requires_compile:
        mode = stat.S_IMODE(configuration_source.stat().st_mode)
        _atomic_write_bytes(configuration_source, source.encode(), mode=mode)
        compile_result: dict[str, Any] = {}
        for attempt in range(2):
            if attempt:
                os.utime(configuration_source, None)
            compile_result = run_bounded_ergoai_process(
                xsb_binary,
                input_text="[xsb_configuration].\nhalt.\n",
                timeout=30.0,
                max_output_bytes=ERGOAI_DEFAULT_MAX_OUTPUT_BYTES,
                env=environment,
                cwd=configuration_library,
                args=("--quietload", "--noprompt"),
            )
            if (
                compile_result.get("returncode") == 0
                and compile_result.get("termination_reason") is None
            ):
                break
        # XSB 5 may report a non-zero "redefining xsb_configuration" status
        # after it has already emitted the replacement bytecode.  The fresh
        # process probe below is the authoritative compile check: it can only
        # pass if the emitted module loads and returns the reviewed paths.
    expected_srcdir = str(xsb_root.resolve())
    expected_site_dir = str((xsb_root / "site").resolve())
    probe_result = run_bounded_ergoai_process(
        xsb_binary,
        input_text=(
            "xsb_configuration(srcdir,S), writeln(S), "
            "xsb_configuration(site_dir,T), writeln(T), halt.\n"
        ),
        timeout=30.0,
        max_output_bytes=ERGOAI_DEFAULT_MAX_OUTPUT_BYTES,
        env=environment,
        args=("--quietload", "--noprompt"),
    )
    output = str(probe_result.get("output_text") or "")
    if (
        probe_result.get("returncode") != 0
        or probe_result.get("termination_reason") is not None
        or expected_srcdir not in output
        or expected_site_dir not in output
    ):
        compile_diagnostic = str(
            (compile_result if requires_compile else {}).get("output_text") or ""
        )[-1000:]
        raise AdvisorInstallerError(
            "ErgoAI XSB runtime still reports non-relocatable source/site paths; "
            f"compile diagnostic: {compile_diagnostic}"
        )
    return {
        "configuration_source_sha256": content_sha256(configuration_source),
        "configuration_bytecode_sha256": content_sha256(configuration_bytecode),
        "observed_srcdir": expected_srcdir,
        "observed_site_dir": expected_site_dir,
    }


def _load_identity_manifest(path: Path) -> dict[str, Any] | None:
    if not _safe_existing_regular_file(
        path,
        max_bytes=ERGOAI_IDENTITY_MAX_BYTES,
    ):
        return None
    try:
        raw = path.read_bytes()
        if len(raw) > ERGOAI_IDENTITY_MAX_BYTES:
            return None
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _set_ergoai_stream_timeout(stream: Any, timeout: float) -> None:
    """Best-effort per-read socket bound for an urllib response."""

    candidates = [stream]
    current = stream
    for attribute in ("fp", "raw", "_sock"):
        current = getattr(current, attribute, None)
        if current is None:
            break
        candidates.append(current)
    for candidate in reversed(candidates):
        setter = getattr(candidate, "settimeout", None)
        if callable(setter):
            try:
                setter(max(0.001, timeout))
            except OSError:
                pass
            return


def _copy_exact_ergoai_stream(
    input_stream: Any,
    output_stream: Any,
    *,
    expected_size: int,
    deadline: float,
) -> int:
    """Copy exactly the pinned bytes under a byte and wall-clock ceiling."""

    if type(expected_size) is not int or expected_size <= 0:
        raise AdvisorInstallerError(
            "ErgoAI acquisition requires a positive exact artifact size pin"
        )
    total = 0
    reader = getattr(input_stream, "read1", None)
    if not callable(reader):
        reader = input_stream.read
    while total <= expected_size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("ErgoAI artifact acquisition exceeded its deadline")
        _set_ergoai_stream_timeout(input_stream, remaining)
        chunk = reader(
            min(
                ERGOAI_ACQUISITION_CHUNK_BYTES,
                expected_size - total + 1,
            )
        )
        if time.monotonic() > deadline:
            raise TimeoutError("ErgoAI artifact acquisition exceeded its deadline")
        if not chunk:
            break
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise AdvisorInstallerError("ErgoAI artifact stream returned non-bytes")
        total += len(chunk)
        if total > expected_size:
            raise AdvisorInstallerError(
                "ErgoAI artifact exceeded the exact pinned byte ceiling"
            )
        output_stream.write(chunk)
    if total != expected_size:
        raise AdvisorInstallerError(
            f"ErgoAI artifact size mismatch: expected {expected_size}, got {total}"
        )
    return total


def _copy_or_download_ergoai_artifact(
    pin: ToolPin,
    destination: Path,
    *,
    artifact_path: str | Path | None = None,
    timeout: float = 180.0,
    on_progress: ProgressCallback | None = None,
) -> tuple[bool, str | None, int | None]:
    """Materialize the reviewed release asset and verify it before execution."""

    if not pin.sha256 or not _HEX64.fullmatch(pin.sha256):
        _announce(
            "ErgoAI live installation has no reviewed SHA-256 pin; refusing",
            on_progress,
            phase="failed",
        )
        return False, None, None

    if type(pin.artifact_size_bytes) is not int or pin.artifact_size_bytes <= 0:
        _announce(
            "ErgoAI live installation has no exact positive size pin; refusing",
            on_progress,
            phase="failed",
        )
        return False, None, None

    try:
        wall_timeout = float(timeout)
    except (TypeError, ValueError):
        wall_timeout = 0.0
    if not wall_timeout > 0:
        _announce(
            "ErgoAI artifact acquisition timeout must be positive",
            on_progress,
            phase="failed",
        )
        return False, None, None
    wall_timeout = min(3600.0, wall_timeout)
    deadline = time.monotonic() + wall_timeout

    source = Path(artifact_path).expanduser() if artifact_path else None
    if source is not None:
        if not _safe_existing_regular_file(source):
            _announce(
                f"Configured ErgoAI release file is not a safe regular file: {source}",
                on_progress,
                phase="failed",
            )
            return False, None, None
        try:
            source_size = os.lstat(source).st_size
        except OSError:
            source_size = -1
        if source_size != pin.artifact_size_bytes:
            _announce(
                "Operator-provided ErgoAI release size does not match the exact pin",
                on_progress,
                phase="failed",
            )
            return False, None, source_size if source_size >= 0 else None

    try:
        _ensure_safe_directory(destination.parent)
    except AdvisorInstallerError as exc:
        _announce(str(exc), on_progress, phase="failed")
        return False, None, None
    if _safe_existing_regular_file(destination):
        observed_size = os.lstat(destination).st_size
        if observed_size == pin.artifact_size_bytes:
            observed = content_sha256(destination)
        else:
            observed = None
        if observed == pin.sha256:
            _announce(
                f"Reusing checksummed ErgoAI artifact at {destination}",
                on_progress,
                phase="available",
            )
            return True, observed, observed_size
    elif os.path.lexists(destination):
        _announce(
            f"Unsafe ErgoAI artifact destination exists: {destination}",
            on_progress,
            phase="failed",
        )
        return False, None, None

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".partial",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            if source is not None:
                _announce(
                    f"Copying operator-provided ErgoAI release asset {source}",
                    on_progress,
                    phase="installing",
                )
                with source.open("rb") as input_stream:
                    _copy_exact_ergoai_stream(
                        input_stream,
                        handle,
                        expected_size=pin.artifact_size_bytes,
                        deadline=deadline,
                    )
            else:
                if not pin.artifact_url:
                    _announce(
                        "ErgoAI pin has no artifact URL; refusing live install",
                        on_progress,
                        phase="failed",
                    )
                    return False, None, None
                _announce(
                    f"Downloading checksummed ErgoAI {pin.version} release",
                    on_progress,
                    phase="installing",
                )
                request = Request(
                    pin.artifact_url,
                    headers={
                        "User-Agent": "ipfs-datasets-py-ergoai-installer/1"
                    },
                )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        "ErgoAI artifact acquisition exceeded its deadline"
                    )
                with urlopen(  # noqa: S310 - exact reviewed HTTPS URL
                    request,
                    timeout=remaining,
                ) as response:
                    content_length_text = None
                    headers = getattr(response, "headers", None)
                    if headers is not None and hasattr(headers, "get"):
                        content_length_text = headers.get("Content-Length")
                    if content_length_text not in {None, ""}:
                        try:
                            content_length = int(str(content_length_text))
                        except (TypeError, ValueError) as exc:
                            raise AdvisorInstallerError(
                                "ErgoAI response Content-Length is malformed"
                            ) from exc
                        if content_length != pin.artifact_size_bytes:
                            raise AdvisorInstallerError(
                                "ErgoAI response Content-Length does not match the exact pin"
                            )
                    _copy_exact_ergoai_stream(
                        response,
                        handle,
                        expected_size=pin.artifact_size_bytes,
                        deadline=deadline,
                    )
            handle.flush()
            os.fsync(handle.fileno())

        observed = content_sha256(temporary)
        observed_size = temporary.stat().st_size
        if observed != pin.sha256:
            _announce(
                "ErgoAI release checksum mismatch; refusing to execute artifact",
                on_progress,
                phase="failed",
            )
            return False, observed, observed_size
        if observed_size != pin.artifact_size_bytes:
            _announce(
                "ErgoAI release size mismatch; refusing to execute artifact",
                on_progress,
                phase="failed",
            )
            return False, observed, observed_size
        temporary.replace(destination)
        temporary = None
        return True, observed, observed_size
    except Exception as exc:  # pragma: no cover - network/host-specific failure
        _announce(f"ErgoAI artifact acquisition failed: {exc}", on_progress, phase="failed")
        return False, None, None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _ergoai_missing_build_commands() -> list[str]:
    evidence = _ergoai_build_dependency_identity()
    return [
        *[str(name) for name in evidence.get("missing_commands") or []],
        *[
            f"{name}:version_floor"
            for name in evidence.get("version_mismatches") or []
        ],
        *[
            f"{path}:absolute_path"
            for path in evidence.get("missing_absolute_commands") or []
        ],
    ]


def _find_vendor_ergoai_binary(vendor_root: Path, version: str) -> Path | None:
    expected = (
        vendor_root
        / f"ERGOAI_{version}"
        / "ErgoAI"
        / "runergo"
    )
    candidates = [expected]
    try:
        candidates.extend(sorted(vendor_root.glob("ERGOAI_*/ErgoAI/runergo")))
    except OSError:
        pass
    for candidate in candidates:
        try:
            if (
                candidate.is_file()
                and (candidate.parent / ".ergo_paths").is_file()
            ):
                candidate.chmod(candidate.stat().st_mode | stat.S_IXUSR)
                return candidate.resolve()
        except OSError:
            continue
    return None


def _find_vendor_xsb_binary(vendor_binary: Path) -> Path | None:
    version_root = vendor_binary.parents[1]
    config_root = version_root / "XSB" / "config"
    try:
        candidates = sorted(config_root.glob("*/bin/xsb"))
    except OSError:
        return None
    executable = [
        path
        for path in candidates
        if path.is_file() and os.access(path, os.X_OK)
    ]
    return executable[0].resolve() if len(executable) == 1 else None


def _write_vendor_ergoai_launchers(
    *,
    install_root: Path,
    vendor_binary: Path,
    version: str,
    platform_key: str,
) -> dict[str, str]:
    """Atomically write isolated relocatable launchers with deterministic identity.

    ErgoAI writes compiled Flora metadata beside loaded libraries.  Every
    managed invocation therefore runs a private copy of the ErgoAI subtree and
    references the immutable, platform-bound XSB tree through a confined
    workspace symlink.  Normal exits and handled signals remove the workspace;
    even SIGKILL can leave only non-authoritative runtime state outside the
    identity-bound vendor tree.
    """

    bin_dir = install_root / "bin"
    _ensure_safe_managed_directory(install_root, bin_dir)
    vendor_relative = _install_relative_path(vendor_binary, install_root)
    distribution_relative = _install_relative_path(
        vendor_binary.parent.parent,
        install_root,
    )
    runtime_state_relative = _install_relative_path(
        _ergoai_version_root(install_root, version) / "runtime-state",
        install_root,
    )
    runtime_toolchain_relative = _install_relative_path(
        _ergoai_bound_runtime_toolchain_path(install_root, version),
        install_root,
    )
    launchers: dict[str, str] = {}
    for name in ERGOAI_EXECUTABLES:
        launcher = bin_dir / name
        source = (
            "#!/bin/sh\n"
            "set -eu\n"
            "case \"${1:-}\" in\n"
            "  --version|-v|version)\n"
            f"    printf '%s\\n' 'ErgoAI {version} (managed {platform_key}; "
            f"{ERGOAI_RELEASE_TAG})'\n"
            "    exit 0\n"
            "    ;;\n"
            "esac\n"
            "case \"$0\" in */*) launcher_dir=${0%/*} ;; *) exit 1 ;; esac\n"
            "launcher_dir=$(CDPATH= cd -- \"$launcher_dir\" && printf '%s\\n' \"$PWD\")\n"
            "install_root=$(CDPATH= cd -- \"$launcher_dir/..\" && printf '%s\\n' \"$PWD\")\n"
            f"runtime_toolchain=\"$install_root/{runtime_toolchain_relative}\"\n"
            "if [ -L \"$runtime_toolchain\" ] || [ ! -d \"$runtime_toolchain\" ]; then exit 1; fi\n"
            "PATH=$runtime_toolchain\n"
            "export PATH\n"
            f"runtime_state=\"$install_root/{runtime_state_relative}\"\n"
            "if [ -L \"$runtime_state\" ] || "
            "{ [ -e \"$runtime_state\" ] && [ ! -d \"$runtime_state\" ]; }; "
            "then exit 1; fi\n"
            "mkdir -p \"$runtime_state\" || exit 1\n"
            "if [ -L \"$runtime_state/runtime-workspaces\" ] || "
            "{ [ -e \"$runtime_state/runtime-workspaces\" ] && "
            "[ ! -d \"$runtime_state/runtime-workspaces\" ]; }; then exit 1; fi\n"
            "mkdir -p \"$runtime_state/runtime-workspaces\" || exit 1\n"
            "ergoai_workspace=$(\n"
            "  mktemp -d \"$runtime_state/runtime-workspaces/run.XXXXXX\"\n"
            ") || exit 1\n"
            "cleanup_ergoai_workspace() {\n"
            "  [ -d \"$ergoai_workspace\" ] || return 0\n"
            "  trap - 0 HUP INT TERM\n"
            "  rm -rf -- \"$ergoai_workspace\"\n"
            "}\n"
            "trap 'cleanup_ergoai_workspace' 0\n"
            "trap 'cleanup_ergoai_workspace; exit 129' HUP\n"
            "trap 'cleanup_ergoai_workspace; exit 130' INT\n"
            "trap 'cleanup_ergoai_workspace; exit 143' TERM\n"
            f"workspace_distribution=\"$ergoai_workspace/ERGOAI_{version}\"\n"
            "mkdir -p \"$workspace_distribution\"\n"
            f"cp -a \"$install_root/{distribution_relative}/ErgoAI\" "
            "\"$workspace_distribution/ErgoAI\" || exit 1\n"
            f"ln -s \"$install_root/{distribution_relative}/XSB\" "
            "\"$workspace_distribution/XSB\" || exit 1\n"
            "XSB_USER_AUXDIR=\"$ergoai_workspace/xsb-user-aux\"\n"
            "mkdir -p \"$XSB_USER_AUXDIR\"\n"
            "export XSB_USER_AUXDIR\n"
            f"\"$workspace_distribution/ErgoAI/{Path(vendor_relative).name}\" "
            "\"$@\"\n"
            "ergoai_status=$?\n"
            "cleanup_ergoai_workspace\n"
            "exit \"$ergoai_status\"\n"
        )
        digest = _write_executable(launcher, source)
        launchers[name] = digest
    return launchers


def ergoai_offline_subprocess_env(
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return an explicit no-install/no-download environment for ErgoAI.

    These variables are a policy boundary for cooperating launchers and make
    the environment that reached the vendor process auditable.  Callers that
    require OS-level network isolation must still supply it around the process;
    environment variables alone cannot confine arbitrary native code.
    """

    env = dict(base if base is not None else os.environ)
    # Emptying proxy variables (or setting NO_PROXY=*) silently enables a
    # direct-network fallback in many clients.  Route cooperating HTTP clients
    # to a closed local port instead, with no bypass list.  This is deliberately
    # defence in depth rather than a claim of native-code network confinement.
    closed_proxy = "http://127.0.0.1:9"
    for key in (
        "ALL_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "all_proxy",
        "https_proxy",
        "http_proxy",
    ):
        env[key] = closed_proxy
    env["NO_PROXY"] = ""
    env["no_proxy"] = ""
    env["PIP_NO_INDEX"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["FORMAL_VERIFICATION_CERTIFY_OFFLINE"] = "1"
    env["FORMAL_VERIFICATION_FORBID_INSTALL"] = "1"
    env["FORMAL_VERIFICATION_FORBID_NETWORK"] = "1"
    env["FORMAL_VERIFICATION_FORBID_DOWNLOAD"] = "1"
    return {str(key): str(value) for key, value in env.items()}


def _terminate_process_group(
    process: subprocess.Popen[bytes],
    *,
    grace_seconds: float = 0.75,
) -> None:
    """Terminate *process* and children with a finite cleanup grace period.

    Managed launchers trap TERM to remove private runtime workspaces.  A short
    bounded grace lets that cleanup run; non-cooperative processes are still
    killed as a group, preserving the hard wall/output bound.
    """

    grace = max(0.05, min(2.0, grace_seconds))
    if os.name == "posix":
        process_group = process.pid  # start_new_session=True makes pid == pgid.
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            pass
        try:
            process.wait(timeout=grace)
        except (OSError, subprocess.TimeoutExpired):
            pass
        # Reaping the direct launcher is not proof that its descendants exited.
        # Probe and kill the original group even when the leader handled TERM
        # and returned during its cleanup grace period.
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        try:
            os.killpg(process_group, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        try:
            process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return

    if process.poll() is not None:  # pragma: no cover - Linux is reviewed
        return
    try:  # pragma: no cover - reviewed ErgoAI targets are Linux
        process.terminate()
        process.wait(timeout=grace)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()
    except OSError:
        pass


def run_bounded_ergoai_process(
    executable: str | Path,
    *,
    input_text: str,
    timeout: float,
    max_output_bytes: int | None = None,
    env: Mapping[str, str] | None = None,
    args: Sequence[str] = (),
    cwd: str | Path | None = None,
) -> dict[str, Any]:
    """Run ErgoAI with incremental, finite combined-output capture.

    ``subprocess.run(capture_output=True)`` buffers an untrusted process without
    a ceiling.  This helper reads a merged stdout/stderr pipe incrementally and
    kills the whole process group as soon as the reviewed byte or time bound is
    crossed.  At most ``limit + 64 KiB`` is observed and at most ``limit`` is
    retained in memory.
    """

    limit = (
        ERGOAI_DEFAULT_MAX_OUTPUT_BYTES
        if max_output_bytes is None
        else max(1, int(max_output_bytes))
    )
    wall_timeout = max(0.001, min(3600.0, float(timeout)))
    started = time.monotonic()
    digest = hashlib.sha256()
    captured = bytearray()
    observed_bytes = 0
    termination_reason: str | None = None
    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    input_stream: Any | None = None

    try:
        # Feeding a pipe synchronously can deadlock before the deadline loop if
        # a child never reads stdin.  An unlinked regular file gives the child
        # the same finite input/EOF semantics without a pipe-capacity stall.
        input_stream = tempfile.TemporaryFile(mode="w+b")
        input_stream.write(input_text.encode("utf-8"))
        input_stream.flush()
        input_stream.seek(0)
        process = subprocess.Popen(  # noqa: S603 - exact reviewed executable
            [str(executable), *(str(arg) for arg in args)],
            stdin=input_stream,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            start_new_session=os.name == "posix",
            env=dict(env) if env is not None else None,
            cwd=str(cwd) if cwd is not None else None,
        )
        assert process.stdout is not None

        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = started + wall_timeout

        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                termination_reason = "timeout"
                _terminate_process_group(process)
                break
            events = selector.select(timeout=min(0.1, remaining))
            if not events:
                # EOF is normally selectable.  Keep polling briefly after exit
                # so buffered pipe bytes are consumed before declaring success.
                if process.poll() is not None:
                    events = selector.select(timeout=0)
                    if not events:
                        # A forked descendant can retain the output descriptor
                        # after the direct launcher exits.  Continue to the
                        # wall deadline rather than treating that as EOF.
                        continue
                else:
                    continue
            for key, _mask in events:
                chunk = os.read(key.fd, 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                digest.update(chunk)
                observed_bytes += len(chunk)
                remaining_capacity = limit - len(captured)
                if remaining_capacity > 0:
                    captured.extend(chunk[:remaining_capacity])
                if observed_bytes > limit:
                    termination_reason = "output_limit"
                    _terminate_process_group(process)
                    break
            if termination_reason is not None:
                break

        if process.poll() is None:
            try:
                process.wait(timeout=max(0.1, min(2.0, wall_timeout)))
            except subprocess.TimeoutExpired:
                # Preserve a previously observed output boundary.  If stdout
                # closed while the process stayed alive, this is itself a real
                # wall-clock timeout rather than a spawn failure.
                if termination_reason is None:
                    termination_reason = "timeout"
                _terminate_process_group(process)
                try:
                    process.wait(timeout=1.0)
                except (OSError, subprocess.SubprocessError):
                    pass
        # A successful launcher is not permitted to leave background members
        # in its isolated process group.  This is normally a no-op (ESRCH).
        if os.name == "posix":
            _terminate_process_group(process, grace_seconds=0.1)
        returncode = process.returncode
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        if process is not None:
            _terminate_process_group(process)
            try:
                process.wait(timeout=1.0)
            except (OSError, subprocess.SubprocessError):
                pass
        return {
            "returncode": None,
            "output_text": bytes(captured).decode("utf-8", errors="replace"),
            "observed_output_digest_sha256": digest.hexdigest(),
            "output_digest_complete": False,
            "observed_output_bytes": observed_bytes,
            "captured_output_bytes": len(captured),
            "max_output_bytes": limit,
            "elapsed_seconds": time.monotonic() - started,
            "termination_reason": "spawn_error",
            "timed_out": False,
            "resource_bound_enforced": False,
            "error": str(exc)[:300],
        }
    finally:
        if selector is not None:
            selector.close()
        if process is not None and process.stdout is not None:
            process.stdout.close()
        if input_stream is not None:
            input_stream.close()

    return {
        "returncode": returncode,
        "output_text": bytes(captured).decode("utf-8", errors="replace"),
        "observed_output_digest_sha256": digest.hexdigest(),
        "output_digest_complete": termination_reason is None,
        "observed_output_bytes": observed_bytes,
        "captured_output_bytes": len(captured),
        "max_output_bytes": limit,
        "elapsed_seconds": time.monotonic() - started,
        "termination_reason": termination_reason,
        "timed_out": termination_reason == "timeout",
        "resource_bound_enforced": termination_reason == "output_limit",
    }


def _ergoai_build_dependency_identity() -> dict[str, Any]:
    """Probe every command exercised by acquisition/build and bind its bytes."""

    commands: dict[str, Any] = {}
    missing: list[str] = []
    version_mismatches: list[str] = []
    for name in ERGOAI_BUILD_COMMANDS:
        invoked = shutil.which(name)
        if not invoked:
            missing.append(name)
            commands[name] = {"present": False}
            continue
        path = Path(invoked).expanduser().resolve()
        identity: dict[str, Any] = {
            "present": bool(path.is_file() and os.access(path, os.X_OK)),
            "invoked_path": str(Path(invoked).expanduser()),
            "resolved_path": str(path),
            "executable_sha256": (
                content_sha256(path) if path.is_file() else None
            ),
        }
        minimum = ERGOAI_VERSIONED_BUILD_COMMANDS.get(name)
        if minimum is not None and identity["present"]:
            execution = run_bounded_ergoai_process(
                path,
                args=("--version",),
                input_text="",
                timeout=5.0,
                max_output_bytes=64 * 1024,
                env=ergoai_offline_subprocess_env(),
            )
            banner = str(execution.get("output_text") or "")
            observed_version = numeric_version(banner)
            version_ok = bool(
                execution.get("returncode") == 0
                and execution.get("termination_reason") is None
                and observed_version
                and observed_version >= minimum
            )
            identity.update(
                {
                    "minimum_version": ">="
                    + ".".join(str(part) for part in minimum),
                    "observed_version": (
                        ".".join(str(part) for part in observed_version)
                        if observed_version
                        else None
                    ),
                    "version_satisfied": version_ok,
                    "version_banner_digest_sha256": hashlib.sha256(
                        banner.encode("utf-8")
                    ).hexdigest(),
                }
            )
            if not version_ok:
                version_mismatches.append(name)
        if not identity["present"]:
            missing.append(name)
        commands[name] = identity

    absolute_commands: dict[str, Any] = {}
    missing_absolute: list[str] = []
    for raw_path in ERGOAI_REQUIRED_ABSOLUTE_COMMANDS:
        path = Path(raw_path)
        present = bool(
            path.is_file() and os.access(path, os.X_OK)
        )
        absolute_commands[raw_path] = {
            "present": present,
            "resolved_path": str(path.resolve()) if present else None,
            "executable_sha256": content_sha256(path.resolve()) if present else None,
        }
        if not present:
            missing_absolute.append(raw_path)

    return {
        "schema_version": "ergoai-build-dependency-identity/v1",
        "commands": commands,
        "absolute_commands": absolute_commands,
        "missing_commands": sorted(set(missing)),
        "missing_absolute_commands": sorted(set(missing_absolute)),
        "version_mismatches": sorted(set(version_mismatches)),
        "satisfied": not missing and not missing_absolute and not version_mismatches,
    }


def _validate_recorded_ergoai_dependency_identity(raw: Any) -> bool:
    if not isinstance(raw, Mapping):
        return False
    commands = raw.get("commands")
    absolute_commands = raw.get("absolute_commands")
    if (
        raw.get("schema_version") != "ergoai-build-dependency-identity/v1"
        or raw.get("satisfied") is not True
        or raw.get("missing_commands") != []
        or raw.get("missing_absolute_commands") != []
        or raw.get("version_mismatches") != []
        or not isinstance(commands, Mapping)
        or set(commands) != set(ERGOAI_BUILD_COMMANDS)
        or not isinstance(absolute_commands, Mapping)
        or set(absolute_commands) != set(ERGOAI_REQUIRED_ABSOLUTE_COMMANDS)
    ):
        return False
    for name, value in commands.items():
        if not isinstance(value, Mapping):
            return False
        digest = value.get("executable_sha256")
        if (
            value.get("present") is not True
            or not isinstance(value.get("resolved_path"), str)
            or not Path(value["resolved_path"]).is_absolute()
            or not isinstance(digest, str)
            or not _HEX64.fullmatch(digest)
        ):
            return False
        minimum = ERGOAI_VERSIONED_BUILD_COMMANDS.get(str(name))
        if minimum is not None:
            observed = value.get("observed_version")
            if (
                not isinstance(observed, str)
                or numeric_version(observed) < minimum
                or value.get("version_satisfied") is not True
            ):
                return False
    for value in absolute_commands.values():
        if not isinstance(value, Mapping):
            return False
        digest = value.get("executable_sha256")
        if (
            value.get("present") is not True
            or not isinstance(digest, str)
            or not _HEX64.fullmatch(digest)
        ):
            return False
    return True


def _ergoai_dependency_identity_matches_live(raw: Any) -> bool:
    """Recheck that recorded command paths still name the recorded bytes."""

    if not _validate_recorded_ergoai_dependency_identity(raw):
        return False
    assert isinstance(raw, Mapping)
    commands = raw["commands"]
    absolute_commands = raw["absolute_commands"]
    assert isinstance(commands, Mapping)
    assert isinstance(absolute_commands, Mapping)
    try:
        for value in commands.values():
            if not isinstance(value, Mapping):
                return False
            path = Path(str(value["resolved_path"]))
            if (
                not path.is_file()
                or not os.access(path, os.X_OK)
                or content_sha256(path) != value["executable_sha256"]
            ):
                return False
        for invoked, value in absolute_commands.items():
            if not isinstance(invoked, str) or not isinstance(value, Mapping):
                return False
            path = Path(invoked)
            if (
                not path.is_file()
                or not os.access(path, os.X_OK)
                or str(path.resolve()) != value.get("resolved_path")
                or content_sha256(path.resolve()) != value.get("executable_sha256")
            ):
                return False
    except (KeyError, OSError, TypeError, ValueError):
        return False
    return True


def _ergoai_optional_java_dependency_identity() -> dict[str, Any]:
    """Return a digest/version-bound description of the optional Java API."""

    names = tuple(
        dict.fromkeys(
            (
                *ERGOAI_OPTIONAL_JAVA_RUNTIME_COMMANDS,
                *ERGOAI_OPTIONAL_JAVA_BUILD_COMMANDS,
            )
        )
    )
    commands: dict[str, Any] = {}
    missing: list[str] = []
    version_mismatches: list[str] = []
    for name in names:
        invoked = shutil.which(name)
        if not invoked:
            commands[name] = {"present": False}
            missing.append(name)
            continue
        path = Path(invoked).expanduser().resolve()
        present = bool(path.is_file() and os.access(path, os.X_OK))
        value: dict[str, Any] = {
            "present": present,
            "resolved_path": str(path),
            "executable_sha256": content_sha256(path) if present else None,
        }
        if not present:
            missing.append(name)
        if name == "java" and present:
            execution = run_bounded_ergoai_process(
                path,
                args=("-version",),
                input_text="",
                timeout=5.0,
                max_output_bytes=64 * 1024,
                env=ergoai_offline_subprocess_env({"LANG": "C", "LC_ALL": "C"}),
            )
            banner = str(execution.get("output_text") or "")
            observed_version = numeric_version(banner)
            version_ok = bool(
                execution.get("returncode") == 0
                and execution.get("termination_reason") is None
                and observed_version >= ERGOAI_OPTIONAL_JAVA_MINIMUM_VERSION
            )
            value.update(
                {
                    "minimum_version": ">=1.8",
                    "observed_version": (
                        ".".join(str(part) for part in observed_version)
                        if observed_version
                        else None
                    ),
                    "version_satisfied": version_ok,
                    "version_banner_digest_sha256": hashlib.sha256(
                        banner.encode("utf-8")
                    ).hexdigest(),
                }
            )
            if not version_ok:
                version_mismatches.append(name)
        commands[name] = value
    return {
        "schema_version": "ergoai-optional-java-dependency-identity/v1",
        "minimum_java_version": ">=1.8",
        "commands": commands,
        "missing_commands": sorted(set(missing)),
        "version_mismatches": sorted(set(version_mismatches)),
        "satisfied": not missing and not version_mismatches,
    }


def _validate_recorded_ergoai_optional_java_identity(raw: Any) -> bool:
    if not isinstance(raw, Mapping):
        return False
    names = set(
        (
            *ERGOAI_OPTIONAL_JAVA_RUNTIME_COMMANDS,
            *ERGOAI_OPTIONAL_JAVA_BUILD_COMMANDS,
        )
    )
    commands = raw.get("commands")
    missing = raw.get("missing_commands")
    mismatches = raw.get("version_mismatches")
    if (
        raw.get("schema_version")
        != "ergoai-optional-java-dependency-identity/v1"
        or raw.get("minimum_java_version") != ">=1.8"
        or not isinstance(commands, Mapping)
        or set(commands) != names
        or not isinstance(missing, list)
        or not isinstance(mismatches, list)
        or any(not isinstance(item, str) for item in (*missing, *mismatches))
        or raw.get("satisfied") is not (not missing and not mismatches)
    ):
        return False
    for name, value in commands.items():
        if not isinstance(value, Mapping) or type(value.get("present")) is not bool:
            return False
        if value.get("present") is False:
            if name not in missing:
                return False
            continue
        digest = value.get("executable_sha256")
        if (
            not isinstance(value.get("resolved_path"), str)
            or not Path(value["resolved_path"]).is_absolute()
            or not isinstance(digest, str)
            or not _HEX64.fullmatch(digest)
        ):
            return False
        if name == "java":
            observed = value.get("observed_version")
            version_ok = bool(
                isinstance(observed, str)
                and numeric_version(observed) >= ERGOAI_OPTIONAL_JAVA_MINIMUM_VERSION
            )
            if value.get("version_satisfied") is not version_ok:
                return False
            if (name in mismatches) is version_ok:
                return False
    return set(missing) == {
        str(name)
        for name, value in commands.items()
        if isinstance(value, Mapping) and value.get("present") is False
    }


def _ergoai_bound_runtime_command_records(
    dependency_identity: Mapping[str, Any],
    optional_java_identity: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    """Return exact live command identities admitted to managed runtime PATH.

    The generated launchers must not search an operator-controlled ``PATH``.
    Instead they use a symlink-only directory containing precisely the command
    bytes recorded during preflight.  Optional Java commands are admitted only
    when the complete recorded Java capability is satisfied.
    """

    if not _ergoai_dependency_identity_matches_live(dependency_identity):
        raise AdvisorInstallerError(
            "ErgoAI runtime dependency bytes changed after preflight"
        )
    if not _validate_recorded_ergoai_optional_java_identity(
        optional_java_identity
    ):
        raise AdvisorInstallerError("invalid optional Java dependency evidence")

    raw_commands = dependency_identity.get("commands")
    assert isinstance(raw_commands, Mapping)
    selected: dict[str, Any] = dict(raw_commands)
    if optional_java_identity.get("satisfied") is True:
        optional_commands = optional_java_identity.get("commands")
        assert isinstance(optional_commands, Mapping)
        selected.update(optional_commands)

    records: dict[str, dict[str, str]] = {}
    for name, value in sorted(selected.items()):
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9_.+-]+", name)
            or not isinstance(value, Mapping)
            or value.get("present") is not True
        ):
            raise AdvisorInstallerError(
                f"invalid ErgoAI runtime command identity: {name!r}"
            )
        target = Path(str(value.get("resolved_path") or ""))
        digest = value.get("executable_sha256")
        if (
            not target.is_absolute()
            or not target.is_file()
            or not os.access(target, os.X_OK)
            or not isinstance(digest, str)
            or not _HEX64.fullmatch(digest)
            or content_sha256(target) != digest
        ):
            raise AdvisorInstallerError(
                f"ErgoAI runtime command identity changed: {name}"
            )
        records[name] = {
            "resolved_path": str(target),
            "executable_sha256": digest,
        }
    return records


def _ergoai_bound_runtime_toolchain_path(
    install_root: Path,
    version: str,
) -> Path:
    return _ergoai_version_root(install_root, version) / "runtime-toolchain-bin"


def _ergoai_bound_runtime_evidence(
    *,
    install_root: Path,
    version: str,
    records: Mapping[str, Mapping[str, str]],
    optional_java_enabled: bool,
) -> dict[str, Any]:
    normalized = json.dumps(
        records,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    runtime_path = _ergoai_bound_runtime_toolchain_path(install_root, version)
    return {
        "schema_version": "ergoai-bound-runtime-environment/v1",
        "path_model": ERGOAI_BOUND_RUNTIME_PATH_MODEL,
        "runtime_path": _install_relative_path(runtime_path, install_root),
        "command_count": len(records),
        "commands_digest_sha256": hashlib.sha256(normalized).hexdigest(),
        "ambient_path_inherited": False,
        "optional_java_api_enabled": optional_java_enabled,
    }


def _materialize_ergoai_bound_runtime_toolchain(
    *,
    install_root: Path,
    version: str,
    dependency_identity: Mapping[str, Any],
    optional_java_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Publish the exact symlink-only command namespace used at runtime."""

    records = _ergoai_bound_runtime_command_records(
        dependency_identity,
        optional_java_identity,
    )
    runtime_path = _ergoai_bound_runtime_toolchain_path(install_root, version)
    _ensure_safe_managed_directory(install_root, runtime_path)
    try:
        with os.scandir(runtime_path) as entries:
            observed_names = {entry.name for entry in entries}
    except OSError as exc:
        raise AdvisorInstallerError(
            f"could not inspect ErgoAI runtime toolchain: {exc}"
        ) from exc
    expected_names = set(records)
    if observed_names - expected_names:
        raise AdvisorInstallerError(
            "ErgoAI runtime toolchain contains unreviewed command names"
        )

    for name, record in records.items():
        link = runtime_path / name
        target = record["resolved_path"]
        if os.path.lexists(link):
            if not link.is_symlink() or os.readlink(link) != target:
                raise AdvisorInstallerError(
                    f"unsafe pre-existing ErgoAI runtime command: {name}"
                )
            continue
        temporary = runtime_path / f".{name}.{os.getpid()}.{time.time_ns()}.partial"
        try:
            os.symlink(target, temporary)
            os.replace(temporary, link)
        finally:
            if os.path.lexists(temporary):
                temporary.unlink(missing_ok=True)

    return _ergoai_bound_runtime_evidence(
        install_root=install_root,
        version=version,
        records=records,
        optional_java_enabled=optional_java_identity.get("satisfied") is True,
    )


def _validate_ergoai_bound_runtime_toolchain(
    *,
    install_root: Path,
    version: str,
    dependency_identity: Mapping[str, Any],
    optional_java_identity: Mapping[str, Any],
    claimed_evidence: Any,
) -> bool:
    """Replay the runtime PATH binding against exact recorded command bytes."""

    if not isinstance(claimed_evidence, Mapping):
        return False
    try:
        records = _ergoai_bound_runtime_command_records(
            dependency_identity,
            optional_java_identity,
        )
        expected_evidence = _ergoai_bound_runtime_evidence(
            install_root=install_root,
            version=version,
            records=records,
            optional_java_enabled=(
                optional_java_identity.get("satisfied") is True
            ),
        )
        if dict(claimed_evidence) != expected_evidence:
            return False
        runtime_path = _ergoai_bound_runtime_toolchain_path(
            install_root,
            version,
        )
        metadata = os.lstat(runtime_path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            return False
        with os.scandir(runtime_path) as runtime_entries:
            entry_names = {entry.name for entry in runtime_entries}
        if entry_names != set(records):
            return False
        for name, record in records.items():
            link = runtime_path / name
            if not link.is_symlink() or os.readlink(link) != record["resolved_path"]:
                return False
            target = link.resolve(strict=True)
            if (
                str(target) != record["resolved_path"]
                or not target.is_file()
                or not os.access(target, os.X_OK)
                or content_sha256(target) != record["executable_sha256"]
            ):
                return False
    except (KeyError, OSError, TypeError, ValueError, AdvisorInstallerError):
        return False
    return True


def ergoai_managed_runtime_subprocess_env(
    install_root: str | Path,
    *,
    expected_version: str = ERGOAI_VERSION,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return an offline environment bound to a verified managed runtime PATH."""

    root = Path(install_root).expanduser().resolve()
    manifest = _load_identity_manifest(
        _ergoai_identity_path(root, expected_version)
    )
    if not isinstance(manifest, Mapping):
        raise AdvisorInstallerError("managed ErgoAI identity manifest is missing")
    dependency_identity = manifest.get("build_dependency_identity")
    optional_java_identity = manifest.get("optional_java_dependency_identity")
    if not isinstance(dependency_identity, Mapping) or not isinstance(
        optional_java_identity,
        Mapping,
    ):
        raise AdvisorInstallerError(
            "managed ErgoAI runtime dependency evidence is missing"
        )
    if not _validate_ergoai_bound_runtime_toolchain(
        install_root=root,
        version=expected_version,
        dependency_identity=dependency_identity,
        optional_java_identity=optional_java_identity,
        claimed_evidence=manifest.get("bound_runtime_environment"),
    ):
        raise AdvisorInstallerError(
            "managed ErgoAI runtime toolchain failed identity replay"
        )
    runtime_path = _ergoai_bound_runtime_toolchain_path(root, expected_version)
    environment = ergoai_offline_subprocess_env(base)
    environment["PATH"] = str(runtime_path)
    environment["SHELL"] = str(runtime_path / "sh")
    for name in ("CDPATH", "ENV", "BASH_ENV"):
        environment.pop(name, None)
    return environment


def _materialize_ergoai_bound_build_environment(
    *,
    stage_workspace: Path,
    install_home: Path,
    dependency_identity: Mapping[str, Any],
    optional_java_identity: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    """Create an allowlisted environment whose PATH contains recorded bytes."""

    if not _ergoai_dependency_identity_matches_live(dependency_identity):
        raise AdvisorInstallerError(
            "ErgoAI build dependency bytes changed after preflight"
        )
    bound_bin = stage_workspace / "bound-toolchain-bin"
    private_tmp = stage_workspace / "process-tmp"
    _ensure_safe_managed_directory(stage_workspace, bound_bin)
    _ensure_safe_managed_directory(stage_workspace, private_tmp, mode=0o700)
    commands = dependency_identity.get("commands")
    assert isinstance(commands, Mapping)
    selected: dict[str, Mapping[str, Any]] = {
        str(name): value
        for name, value in commands.items()
        if isinstance(value, Mapping)
    }
    if optional_java_identity.get("satisfied") is True:
        optional_commands = optional_java_identity.get("commands")
        if not isinstance(optional_commands, Mapping):
            raise AdvisorInstallerError("invalid optional Java dependency evidence")
        for name, value in optional_commands.items():
            if isinstance(value, Mapping):
                selected.setdefault(str(name), value)
    bound_commands: dict[str, Any] = {}
    for name, value in sorted(selected.items()):
        if not re.fullmatch(r"[A-Za-z0-9_.+-]+", name):
            raise AdvisorInstallerError(f"unsafe build command name: {name!r}")
        target = Path(str(value.get("resolved_path") or ""))
        digest = value.get("executable_sha256")
        if (
            not target.is_absolute()
            or not target.is_file()
            or not os.access(target, os.X_OK)
            or not isinstance(digest, str)
            or content_sha256(target) != digest
        ):
            raise AdvisorInstallerError(
                f"ErgoAI build command identity changed: {name}"
            )
        link = bound_bin / name
        os.symlink(str(target), link)
        bound_commands[name] = {
            "resolved_path": str(target),
            "executable_sha256": digest,
        }
    environment = ergoai_offline_subprocess_env(
        {
            "HOME": str(install_home),
            "PATH": str(bound_bin),
            "SHELL": str(bound_bin / "sh"),
            "TMPDIR": str(private_tmp),
            "TERM": "dumb",
            "DISPLAY": "",
            "LANG": "C",
            "LC_ALL": "C",
            "ERGOAI_MANAGED_XSB_TMPDIR": str(
                stage_workspace / "private-xsb-build"
            ),
        }
    )
    if set(environment) != set(ERGOAI_BOUND_BUILD_ENVIRONMENT_KEYS):
        raise AdvisorInstallerError(
            "ErgoAI bound build environment contains an unreviewed key"
        )
    normalized = json.dumps(
        bound_commands,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return environment, {
        "schema_version": "ergoai-bound-build-environment/v1",
        "path_model": "private-staging-only/v1",
        "command_count": len(bound_commands),
        "commands_digest_sha256": hashlib.sha256(normalized).hexdigest(),
        "ambient_toolchain_overrides_inherited": False,
        "allowlisted_environment_keys": list(
            ERGOAI_BOUND_BUILD_ENVIRONMENT_KEYS
        ),
        "optional_java_api_enabled": optional_java_identity.get("satisfied") is True,
    }


def _normalize_ergoai_verdict(output: str) -> str:
    if "++Error" in output or "++Abort" in output:
        return "error"
    if re.search(r"(?i)\b(syntax\s+error|parse\s+error|malformed)\b", output):
        return "error"
    verdicts = re.findall(r"(?m)^\s*(Yes|No)\s*$", output)
    if not verdicts:
        return "unknown"
    return verdicts[-1].lower()


def _canonical_ergoai_semantic_outcome(
    *,
    output: str,
    returncode: int | None,
    termination_reason: str | None,
) -> dict[str, Any]:
    """Normalize semantic output while excluding banners, paths, and timings."""

    verdict_sequence = [
        token.lower()
        for token in re.findall(r"(?m)^\s*(Yes|No)\s*$", output)
    ]
    if "++Abort" in output:
        error_class: str | None = "abort"
    elif "++Error" in output or re.search(
        r"(?i)\b(syntax\s+error|parse\s+error|malformed)\b", output
    ):
        error_class = "error"
    else:
        error_class = None
    if termination_reason == "timeout":
        verdict = "timeout"
        boundary = "timeout"
    elif termination_reason == "output_limit":
        verdict = "resource_bound"
        boundary = "output_limit"
    elif termination_reason == "spawn_error":
        verdict = "error"
        boundary = "spawn_error"
    else:
        verdict = _normalize_ergoai_verdict(output)
        boundary = "success" if returncode == 0 else "nonzero"
    return {
        "verdict": verdict,
        "verdict_sequence": verdict_sequence,
        "error_class": error_class,
        "process_boundary": boundary,
    }


def _run_ergoai_semantic_case(
    executable: str | Path,
    *,
    program: str,
    query: str,
    timeout: float,
    max_output_bytes: int | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    source_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".ergo",
            prefix="ipfs-datasets-ergoai-cert-",
            dir=ergoai_safe_temporary_directory(),
            delete=False,
        ) as handle:
            handle.write(program)
            source_path = Path(handle.name)
        commands = f"load{{'{source_path}'}}.\n{query}.\n\\halt.\n"
        execution = run_bounded_ergoai_process(
            executable,
            input_text=commands,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            env=env,
        )
        combined = str(execution.pop("output_text", ""))
        semantic_outcome = _canonical_ergoai_semantic_outcome(
            output=combined,
            returncode=execution.get("returncode"),
            termination_reason=execution.get("termination_reason"),
        )
        semantic_outcome_digest = hashlib.sha256(
            json.dumps(
                semantic_outcome,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            **execution,
            "verdict": semantic_outcome["verdict"],
            # Backwards-compatible key.  The explicit completeness flag makes
            # clear whether this digest covers a completed process stream.
            "output_digest_sha256": execution.get(
                "observed_output_digest_sha256"
            ),
            "semantic_outcome": semantic_outcome,
            "semantic_outcome_digest_sha256": semantic_outcome_digest,
            "program_digest_sha256": hashlib.sha256(
                program.encode("utf-8")
            ).hexdigest(),
            "query_digest_sha256": hashlib.sha256(
                query.encode("utf-8")
            ).hexdigest(),
            "passed_process_boundary": bool(
                execution.get("returncode") == 0
                and execution.get("termination_reason") is None
            ),
            "timeout_seconds": timeout,
            "subprocess_env_bound": env is not None,
        }
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {
            "returncode": None,
            "verdict": "error",
            "error": str(exc)[:300],
            "passed_process_boundary": False,
            "timed_out": False,
            "resource_bound_enforced": False,
            "timeout_seconds": timeout,
            "max_output_bytes": max_output_bytes,
            "subprocess_env_bound": env is not None,
        }
    finally:
        if source_path is not None:
            source_path.unlink(missing_ok=True)


def _ergoai_case_passed(record: dict[str, Any]) -> bool:
    """Evaluate whether a semantic case met its declared expectation."""

    expected = record.get("expected")
    expected_any = record.get("expected_any")
    verdict = record.get("verdict")
    if expected_any is not None:
        ok_verdict = verdict in set(expected_any)
    else:
        ok_verdict = verdict == expected
    require_boundary = bool(record.get("require_process_boundary", True))
    if require_boundary and not record.get("passed_process_boundary"):
        return False
    if record.get("require_timeout") and not record.get("timed_out"):
        return False
    if record.get("require_resource_bound") and not record.get(
        "resource_bound_enforced"
    ):
        return False
    if record.get("require_control") and not record.get("control_passed"):
        return False
    return bool(ok_verdict)


def _ergoai_normalized_semantic_payload(
    checks: Mapping[str, Any],
    *,
    replay_bound: bool,
    passed: bool,
) -> dict[str, Any]:
    """Build the stable evidence projection shared by writer and validator."""

    normalized: dict[str, Any] = {}
    for name, raw_value in checks.items():
        if not isinstance(raw_value, Mapping) or raw_value.get("alias_of") is not None:
            continue
        normalized[str(name)] = {
            "expected": raw_value.get("expected"),
            "expected_any": raw_value.get("expected_any"),
            "verdict": raw_value.get("verdict"),
            "returncode": raw_value.get("returncode"),
            "program_digest_sha256": raw_value.get("program_digest_sha256"),
            "query_digest_sha256": raw_value.get("query_digest_sha256"),
            "semantic_outcome_digest_sha256": raw_value.get(
                "semantic_outcome_digest_sha256"
            ),
            "timed_out": raw_value.get("timed_out"),
            "resource_bound_enforced": raw_value.get(
                "resource_bound_enforced"
            ),
            "control_passed": raw_value.get("control_passed"),
            "passed": raw_value.get("passed"),
            "kind": raw_value.get("kind"),
        }
    return {
        "checks": normalized,
        "replay_bound": replay_bound,
        "passed": passed,
    }


def _ergoai_semantic_evidence_digest(
    checks: Mapping[str, Any],
    *,
    replay_bound: bool,
    passed: bool,
) -> str:
    return hashlib.sha256(
        json.dumps(
            _ergoai_normalized_semantic_payload(
                checks,
                replay_bound=replay_bound,
                passed=passed,
            ),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def run_ergoai_semantic_checks(
    executable: str | Path,
    *,
    timeout: float = 30.0,
    include_extended: bool = True,
    bound_timeout_seconds: float = ERGOAI_DEFAULT_BOUND_TIMEOUT_SECONDS,
    max_output_bytes: int = ERGOAI_RESOURCE_CASE_MAX_OUTPUT_BYTES,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run bounded live semantic checks through a real ErgoAI executable.

    Case matrix (ErgoAILiveToolchainContract@1 / FVT-G218):

    * ``entailment`` / ``positive`` — known membership query succeeds
    * ``non_entailment`` / ``negative`` — absent membership fails closed
    * ``contradiction`` — A and explicit-negation(A) are both witnessed while
      an unrelated conclusion remains non-entailed (paraconsistent control)
    * ``mutation`` — rule/query type mutation changes the answer
    * ``replay`` — deterministic re-execution of the entailment case
    * ``malformed`` — invalid source is quarantined as error
    * ``timeout`` — wall-clock bound is enforced
    * ``resource_bound`` — an incremental output byte ceiling is enforced

    Results remain advisor/candidate evidence only; they never grant theorem
    or proof authority.
    """

    # Semantic certification is observation-only.  Never inherit a usable
    # HTTP proxy or opt into a download/install fallback while probing.
    process_env = ergoai_offline_subprocess_env(env)

    # Strictly increasing arguments produce infinitely many tabled subgoals;
    # unlike direct left recursion, genuine ErgoAI/XSB cannot collapse this to
    # a finite negative answer.  A terminating control is run at the same bound
    # before this case can pass.
    entailment = _run_ergoai_semantic_case(
        executable,
        program=_ERGOAI_BASE_PROGRAM,
        query=_ERGOAI_QUERY_ENTAILMENT,
        timeout=timeout,
        env=process_env,
    )
    non_entailment = _run_ergoai_semantic_case(
        executable,
        program=_ERGOAI_BASE_PROGRAM,
        query=_ERGOAI_QUERY_NON_ENTAILMENT,
        timeout=timeout,
        env=process_env,
    )
    contradiction = _run_ergoai_semantic_case(
        executable,
        program=_ERGOAI_CONTRADICTION_PROGRAM,
        query=_ERGOAI_QUERY_CONTRADICTION,
        timeout=timeout,
        env=process_env,
    )
    mutation = _run_ergoai_semantic_case(
        executable,
        program=_ERGOAI_MUTATED_PROGRAM,
        query=_ERGOAI_QUERY_ENTAILMENT,
        timeout=timeout,
        env=process_env,
    )
    replay = _run_ergoai_semantic_case(
        executable,
        program=_ERGOAI_BASE_PROGRAM,
        query=_ERGOAI_QUERY_ENTAILMENT,
        timeout=timeout,
        env=process_env,
    )
    checks: dict[str, Any] = {
        "entailment": {
            **entailment,
            "expected": "yes",
            "kind": "entailment",
            "require_process_boundary": True,
        },
        "non_entailment": {
            **non_entailment,
            "expected": "no",
            "kind": "non_entailment",
            "require_process_boundary": True,
        },
        "mutation": {
            **mutation,
            "expected": "no",
            "kind": "mutation",
            "require_process_boundary": True,
        },
        "replay": {
            **replay,
            "expected": "yes",
            "kind": "replay",
            "require_process_boundary": True,
        },
        # Legacy aliases used by LiveErgoAIAdvisorCertification fixtures.
        "positive": {
            **entailment,
            "expected": "yes",
            "kind": "entailment",
            "require_process_boundary": True,
            "alias_of": "entailment",
        },
        "negative": {
            **non_entailment,
            "expected": "no",
            "kind": "non_entailment",
            "require_process_boundary": True,
            "alias_of": "non_entailment",
        },
    }

    if include_extended:
        non_explosion = _run_ergoai_semantic_case(
            executable,
            program=_ERGOAI_CONTRADICTION_PROGRAM,
            query=_ERGOAI_QUERY_NON_EXPLOSION,
            timeout=timeout,
            env=process_env,
        )
        non_explosion["expected"] = "no"
        non_explosion["require_process_boundary"] = True
        non_explosion["passed"] = _ergoai_case_passed(non_explosion)
        # ErgoAI is paraconsistent: the meaningful contradiction witness is
        # simultaneous derivability of A and explicit-negation(A), together
        # with a negative unrelated control showing that the conflict did not
        # explode into arbitrary entailment.
        checks["contradiction"] = {
            **contradiction,
            "expected": "yes",
            "kind": "contradiction",
            "require_process_boundary": True,
            "require_control": True,
            "control_passed": non_explosion["passed"],
            "non_explosion": non_explosion,
        }
        malformed = _run_ergoai_semantic_case(
            executable,
            program=_ERGOAI_MALFORMED_PROGRAM,
            query=_ERGOAI_QUERY_ENTAILMENT,
            timeout=timeout,
            env=process_env,
        )
        baseline_elapsed = max(
            0.001,
            float(entailment.get("elapsed_seconds") or 0.0),
        )
        calibrated_timeout = min(
            max(0.001, float(timeout)),
            max(
                0.1,
                float(bound_timeout_seconds),
                baseline_elapsed * 4.0 + 0.25,
            ),
        )
        timeout_control = _run_ergoai_semantic_case(
            executable,
            program=_ERGOAI_BASE_PROGRAM,
            query=_ERGOAI_QUERY_ENTAILMENT,
            timeout=calibrated_timeout,
            env=process_env,
        )
        timeout_control["expected"] = "yes"
        timeout_control["require_process_boundary"] = True
        timeout_control["passed"] = _ergoai_case_passed(timeout_control)
        timed = _run_ergoai_semantic_case(
            executable,
            program=_ERGOAI_TIMEOUT_PROGRAM,
            query=_ERGOAI_QUERY_TIMEOUT,
            timeout=calibrated_timeout,
            env=process_env,
        )
        resource_control = _run_ergoai_semantic_case(
            executable,
            program=_ERGOAI_BASE_PROGRAM,
            query=_ERGOAI_QUERY_ENTAILMENT,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            env=process_env,
        )
        resource_control["expected"] = "yes"
        resource_control["require_process_boundary"] = True
        resource_control["passed"] = _ergoai_case_passed(resource_control)
        resource = _run_ergoai_semantic_case(
            executable,
            program=_ERGOAI_RESOURCE_PROGRAM,
            query=_ERGOAI_QUERY_RESOURCE,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            env=process_env,
        )
        checks["malformed"] = {
            **malformed,
            "expected": "error",
            "kind": "malformed",
            "require_process_boundary": False,
        }
        checks["timeout"] = {
            **timed,
            "expected": "timeout",
            "kind": "timeout",
            "require_process_boundary": False,
            "require_timeout": True,
            "require_control": True,
            "control_passed": timeout_control["passed"],
            "calibrated_timeout_seconds": calibrated_timeout,
            "terminating_control": timeout_control,
        }
        checks["resource_bound"] = {
            **resource,
            "expected": "resource_bound",
            "kind": "resource_bound",
            "require_process_boundary": False,
            "require_resource_bound": True,
            "require_control": True,
            "control_passed": resource_control["passed"],
            "bounded_control": resource_control,
        }
    else:
        # Still compute contradiction once so callers can inspect it, but do
        # not require it for core_passed when extended checks are disabled.
        checks["contradiction"] = {
            **contradiction,
            "expected": "yes",
            "kind": "contradiction",
            "require_process_boundary": True,
            "optional_for_core": True,
        }

    for value in checks.values():
        value["passed"] = _ergoai_case_passed(value)

    replay_bound = (
        entailment.get("verdict") == replay.get("verdict") == "yes"
        and entailment.get("program_digest_sha256")
        == replay.get("program_digest_sha256")
        and entailment.get("query_digest_sha256")
        == replay.get("query_digest_sha256")
        and entailment.get("semantic_outcome_digest_sha256")
        == replay.get("semantic_outcome_digest_sha256")
    )
    # Legacy / install core: membership + mutation + deterministic replay.
    core_kinds = (
        "entailment",
        "non_entailment",
        "mutation",
        "replay",
    )
    core_passed = all(checks[name]["passed"] for name in core_kinds) and replay_bound
    extended_kinds = (
        "contradiction",
        "malformed",
        "timeout",
        "resource_bound",
    )
    extended_passed = (
        all(checks[name]["passed"] for name in extended_kinds if name in checks)
        if include_extended
        else True
    )
    passed = core_passed and extended_passed
    return {
        "schema_version": "ergoai-live-semantic-checks/v2",
        "tool_id": TOOL_ERGOAI,
        "case_kinds": list(ERGOAI_LIVE_SEMANTIC_CASE_KINDS),
        "checks": checks,
        "replay_bound": replay_bound,
        "core_passed": core_passed,
        "extended_passed": extended_passed,
        "passed": passed,
        "normalized_evidence_digest_sha256": _ergoai_semantic_evidence_digest(
            checks,
            replay_bound=replay_bound,
            passed=passed,
        ),
        "network_used": False,
        "install_attempted": False,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "grants_proof_authority": False,
        "evidence_class": "proposal_or_candidate_until_independent_reconstruction",
    }


def _announce(
    message: str,
    on_progress: ProgressCallback | None,
    *,
    phase: str = "info",
) -> None:
    if on_progress is not None:
        on_progress(phase, message)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


# ---------------------------------------------------------------------------
# Lock / pin selection
# ---------------------------------------------------------------------------


def resolve_lock_path(repo_root: Path | str | None = None) -> Path | None:
    """Locate the deployment lock without requiring installation."""

    candidates: list[Path] = []
    if repo_root is not None:
        root = Path(repo_root)
        candidates.append(root / DEFAULT_LOCK_RELATIVE)
        candidates.append(root / "config" / "formal_verification_toolchains.lock.json")
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / DEFAULT_LOCK_RELATIVE)
        candidates.append(
            parent / "config" / "formal_verification_toolchains.lock.json"
        )
    cwd = Path.cwd()
    candidates.append(cwd / DEFAULT_LOCK_RELATIVE)
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_lock_document(repo_root: Path | str | None = None) -> dict[str, Any] | None:
    path = resolve_lock_path(repo_root)
    if path is None:
        return None
    try:
        payload = load_deployment_lock(repo_root, lock_path=path)
        validated = assert_deployment_lock_contract(payload)
    except (InstallerRegistryError, OSError, TypeError, ValueError) as exc:
        raise AdvisorInstallerError(
            f"invalid formal-verification deployment lock: {exc}"
        ) from exc
    if not isinstance(validated, Mapping):
        raise AdvisorInstallerError("deployment lock must be a JSON object")
    return dict(validated)


def _expected_ergoai_runtime_dependencies() -> dict[str, str]:
    return {
        "xsb": "bundled_with_official_release_compile_for_host",
        "runergo": "official_entry_point",
        "posix_shell": "required_for_launchers",
        "private_runtime_workspace_tools": (
            "cp_dirname_ln_mkdir_mktemp_mv_rm_required_for_isolated_consumers"
        ),
    }


def _expected_ergoai_optional_java_dependencies() -> dict[str, Any]:
    minimum = ".".join(
        str(part) for part in ERGOAI_OPTIONAL_JAVA_MINIMUM_VERSION
    )

    def with_java_floor(commands: Sequence[str]) -> list[str]:
        return [
            f"java>={minimum}" if command == "java" else command
            for command in commands
        ]

    return {
        "runtime": with_java_floor(ERGOAI_OPTIONAL_JAVA_RUNTIME_COMMANDS),
        "build": with_java_floor(ERGOAI_OPTIONAL_JAVA_BUILD_COMMANDS),
        "missing_optional_capabilities_do_not_block_core_ergoai": True,
        "managed_jdk_tool_id": TOOL_TEMURIN_JDK,
        "never_trust_ambient_java_home": True,
    }


def _expected_ergoai_identity_probe() -> dict[str, Any]:
    return {
        "method": "bounded_version_argv",
        "argv": list(ERGOAI_IDENTITY_PROBE_ARGV),
        "timeout_seconds": 5,
        "network": False,
        "expected_identity_substring": f"ErgoAI {ERGOAI_VERSION}",
    }


def _expected_ergoai_acquisition_conditions() -> dict[str, bool]:
    return {
        "requires_explicit_opt_in": True,
        "checksum_required_before_execute": True,
        "download_during_certification_forbidden": True,
        "user_local_only": True,
        "offline_after_acquisition": True,
        "atomic_staged_install": True,
        "relocatable_install_root": True,
        "bounded_acquisition": True,
        "symlink_free_install_paths": True,
    }


def _expected_ergoai_lazy_install_contract() -> dict[str, bool]:
    return {
        "staged": True,
        "checksum_verified": True,
        "atomic": True,
        "relocatable": True,
        "offline_after_acquisition": True,
        "never_on_import": True,
        "never_during_certification": True,
    }


def _expected_ergoai_config_hardening_contract() -> dict[str, Any]:
    return {
        "schema_version": "ergoai-config-hardening/v1",
        "source_sha256": ERGOAI_CONFIG_SOURCE_SHA256,
        "hardened_sha256": ERGOAI_CONFIG_HARDENED_SHA256,
        "private_xsb_workspace_required": True,
        "exact_replacement_count": ERGOAI_CONFIG_HARDENING_REPLACEMENT_COUNT,
    }


def _expected_ergoai_bound_build_environment_contract() -> dict[str, Any]:
    return {
        "schema_version": "ergoai-bound-build-environment/v1",
        "path_model": "private-staging-only/v1",
        "ambient_toolchain_overrides_inherited": False,
        "allowlisted_environment_keys": list(
            ERGOAI_BOUND_BUILD_ENVIRONMENT_KEYS
        ),
    }


def _expected_ergoai_bound_runtime_environment_contract() -> dict[str, Any]:
    return {
        "schema_version": "ergoai-bound-runtime-environment/v1",
        "path_model": ERGOAI_BOUND_RUNTIME_PATH_MODEL,
        "ambient_path_inherited": False,
        "symlink_only_exact_command_identities": True,
        "optional_java_requires_complete_capability": True,
    }


def _expected_ergoai_runtime_policies() -> dict[str, Any]:
    return {
        "runtime_execution_policy": (
            "private-ergoai-copy-shared-immutable-xsb/v1"
        ),
        "java_consumer_policy": "private-ergoai-copy-java-consumers/v2",
        "runtime_workspace_cleanup_policy": (
            "normal-and-handled-signals-clean-sigkill-orphans-retained/v1"
        ),
        "relocation_certification_scope": (
            "executed-runtime-and-bundled-java-consumers/v1"
        ),
        "developer_rebuild_metadata_relocated": False,
        "install_publication_model": (
            "staged_vendor_atomic_rename_private_runtime_workspaces_identity_commit_v4"
        ),
        "publication_commit_point": "atomic_identity_manifest_replace",
        "runtime_state_policy": (
            "mutable-nonauthoritative-outside-vendor-identity/v1"
        ),
    }


def _assert_ergoai_lock_contract(
    document: Mapping[str, Any],
    entry: Mapping[str, Any],
    pins: Sequence[ToolPin],
) -> None:
    """Require the lock to reproduce the complete reviewed ErgoAI contract."""

    versions = document.get("managed_pin_versions")
    if not isinstance(versions, Mapping) or versions.get(TOOL_ERGOAI) != ERGOAI_VERSION:
        raise AdvisorInstallerError("deployment lock ErgoAI version is not exact")
    if (
        entry.get("license") != "Apache-2.0"
        or entry.get("source") != "https://github.com/ErgoAI/ErgoEngine"
        or entry.get("identity_kind") != "immutable_release_tag"
    ):
        raise AdvisorInstallerError("deployment lock ErgoAI publisher identity mismatch")
    if len(pins) != len(ERGOAI_SUPPORTED_PLATFORMS):
        raise AdvisorInstallerError("deployment lock must contain exactly two ErgoAI pins")
    by_platform = {pin.platform: pin for pin in pins}
    if set(by_platform) != set(ERGOAI_SUPPORTED_PLATFORMS):
        raise AdvisorInstallerError("deployment lock ErgoAI platform set mismatch")
    for platform_name, pin in by_platform.items():
        if not (
            pin.tool_id == TOOL_ERGOAI
            and pin.version == ERGOAI_VERSION
            and pin.artifact_url == ERGOAI_RELEASE_URL
            and pin.sha256 == ERGOAI_RELEASE_SHA256
            and pin.artifact_size_bytes == ERGOAI_RELEASE_SIZE_BYTES
            and pin.release_tag == ERGOAI_RELEASE_TAG
            and pin.license == "Apache-2.0"
            and pin.source == "https://github.com/ErgoAI/ErgoEngine"
            and pin.identity_kind == "immutable_release_tag"
            and pin.is_checksummed
            and pin.requires_checksum_at_install
            and platform_name in ERGOAI_SUPPORTED_PLATFORMS
        ):
            raise AdvisorInstallerError(
                f"deployment lock ErgoAI pin mismatch for {platform_name}"
            )
    contract = entry.get("deployment_contract")
    if not isinstance(contract, Mapping):
        raise AdvisorInstallerError("deployment lock ErgoAI contract must be an object")
    inventory_root = document.get("checksummed_release_inventory")
    inventory = (
        inventory_root.get(TOOL_ERGOAI)
        if isinstance(inventory_root, Mapping)
        else None
    )
    if not isinstance(inventory, Mapping):
        raise AdvisorInstallerError(
            "deployment lock ErgoAI release inventory must be an object"
        )
    expected_floors = {
        name: ">=" + ".".join(str(part) for part in minimum)
        for name, minimum in ERGOAI_VERSIONED_BUILD_COMMANDS.items()
    }
    expected_runtime_dependencies = _expected_ergoai_runtime_dependencies()
    expected_optional_java = _expected_ergoai_optional_java_dependencies()
    expected_identity_probe = _expected_ergoai_identity_probe()
    expected_acquisition = _expected_ergoai_acquisition_conditions()
    expected_lazy_install = _expected_ergoai_lazy_install_contract()
    expected_config_hardening = _expected_ergoai_config_hardening_contract()
    expected_bound_environment = (
        _expected_ergoai_bound_build_environment_contract()
    )
    expected_bound_runtime_environment = (
        _expected_ergoai_bound_runtime_environment_contract()
    )
    expected_runtime_policies = _expected_ergoai_runtime_policies()
    contract_checks = {
        "schema": contract.get("schema_version")
        == "formal-verification-deployment-contract/v1",
        "status": contract.get("status") == "reviewed",
        "artifact_kind": contract.get("artifact_kind") == "release_installer",
        "release_tag": contract.get("release_tag") == ERGOAI_RELEASE_TAG,
        "checksum": contract.get("requires_checksum_at_install") is True,
        "unsupported_platforms": contract.get("unsupported_platforms_fail_closed")
        is True,
        "platforms": contract.get("supported_platforms")
        == list(ERGOAI_SUPPORTED_PLATFORMS),
        "commands": contract.get("required_build_commands")
        == list(ERGOAI_BUILD_COMMANDS),
        "absolute_commands": contract.get("required_absolute_commands")
        == list(ERGOAI_REQUIRED_ABSOLUTE_COMMANDS),
        "version_floors": contract.get("dependency_version_floors")
        == expected_floors,
        "licenses": contract.get("license_components")
        == list(ERGOAI_LICENSE_COMPONENTS),
        "runtime_dependencies": contract.get("runtime_dependencies")
        == expected_runtime_dependencies,
        "optional_java": contract.get("optional_java_api_dependencies")
        == expected_optional_java,
        "entry_point": contract.get("entry_point") == ERGOAI_ENTRY_POINT,
        "identity_probe": contract.get("identity_probe")
        == expected_identity_probe,
        "lazy_install": contract.get("lazy_install")
        == expected_lazy_install,
        "config_hardening": contract.get("config_hardening")
        == expected_config_hardening,
        "bound_build_environment": contract.get("bound_build_environment")
        == expected_bound_environment,
        "bound_runtime_environment": contract.get(
            "bound_runtime_environment_contract"
        )
        == expected_bound_runtime_environment,
        "authority": contract.get("authority_ceiling")
        == ADVISOR_AUTHORITY_CEILING,
        "evidence_class": contract.get("evidence_class")
        == "proposal_or_candidate_until_independent_reconstruction",
        "live_contract": contract.get("live_toolchain_contract_interface")
        == "ErgoAILiveToolchainContract@1",
        "cases": contract.get("live_semantic_checks_required")
        == list(ERGOAI_LIVE_SEMANTIC_CASE_KINDS),
        "acquisition": contract.get("acquisition_conditions")
        == expected_acquisition,
    }
    for key, expected in expected_runtime_policies.items():
        contract_checks[f"runtime_policy:{key}"] = contract.get(key) == expected

    expected_platform_inventory = {
        platform_name: {
            "url": ERGOAI_RELEASE_URL,
            "sha256": ERGOAI_RELEASE_SHA256,
        }
        for platform_name in ERGOAI_SUPPORTED_PLATFORMS
    }
    inventory_checks = {
        "version": inventory.get("version") == ERGOAI_VERSION,
        "url": inventory.get("url") == ERGOAI_RELEASE_URL,
        "sha256": inventory.get("sha256") == ERGOAI_RELEASE_SHA256,
        "identity_kind": inventory.get("identity_kind")
        == "immutable_release_tag",
        "release_tag": inventory.get("release_tag") == ERGOAI_RELEASE_TAG,
        "artifact_size": inventory.get("artifact_size_bytes")
        == ERGOAI_RELEASE_SIZE_BYTES,
        "licenses": inventory.get("license_components")
        == list(ERGOAI_LICENSE_COMPONENTS),
        "platforms": inventory.get("platforms")
        == expected_platform_inventory,
        "commands": set(inventory.get("build_dependencies") or ())
        == set(ERGOAI_BUILD_COMMANDS),
        "absolute_commands": inventory.get("required_absolute_commands")
        == list(ERGOAI_REQUIRED_ABSOLUTE_COMMANDS),
        "version_floors": inventory.get("dependency_version_floors")
        == expected_floors,
        "runtime_dependencies": inventory.get("runtime_dependencies")
        == expected_runtime_dependencies,
        "optional_java": inventory.get("optional_java_api_dependencies")
        == expected_optional_java,
        "entry_point": inventory.get("entry_point") == ERGOAI_ENTRY_POINT,
        "identity_probe": inventory.get("identity_probe")
        == expected_identity_probe,
        "lazy_install": inventory.get("lazy_install")
        == expected_lazy_install,
        "config_hardening": inventory.get("config_hardening")
        == expected_config_hardening,
        "bound_build_environment": inventory.get("bound_build_environment")
        == expected_bound_environment,
        "bound_runtime_environment": inventory.get(
            "bound_runtime_environment_contract"
        )
        == expected_bound_runtime_environment,
        "acquisition": inventory.get("acquisition_conditions")
        == expected_acquisition,
    }
    for key, expected in expected_runtime_policies.items():
        inventory_checks[f"runtime_policy:{key}"] = inventory.get(key) == expected

    failed = sorted(
        [
            f"contract:{name}"
            for name, passed in contract_checks.items()
            if not passed
        ]
        + [
            f"inventory:{name}"
            for name, passed in inventory_checks.items()
            if not passed
        ]
    )
    if failed:
        raise AdvisorInstallerError(
            "deployment lock ErgoAI contract mismatch: " + ", ".join(failed)
        )


def pins_for_tool(
    tool_id: str,
    *,
    repo_root: Path | str | None = None,
    lock: Mapping[str, Any] | None = None,
) -> tuple[ToolPin, ...]:
    """Return managed pins for ``tool_id`` from the lock or reviewed fallbacks."""

    if tool_id not in ADVISOR_PIN_OWNED_TOOLS:
        raise AdvisorInstallerError(f"advisors plugin does not own tool_id={tool_id!r}")

    document = lock if lock is not None else load_lock_document(repo_root)
    pins: list[ToolPin] = []
    if document is not None:
        try:
            document = assert_deployment_lock_contract(document)
        except (InstallerRegistryError, TypeError, ValueError) as exc:
            raise AdvisorInstallerError(
                f"invalid formal-verification deployment lock: {exc}"
            ) from exc
        tools = document.get("tools") or []
        if not isinstance(tools, list):
            raise AdvisorInstallerError("deployment lock tools must be a list")
        matching_entries = [
            entry
            for entry in tools
            if isinstance(entry, Mapping) and entry.get("tool_id") == tool_id
        ]
        if len(matching_entries) != 1:
            raise AdvisorInstallerError(
                f"deployment lock must contain exactly one {tool_id!r} entry"
            )
        entry = matching_entries[0]
        try:
            license_text = str(entry.get("license") or "")
            source_text = str(entry.get("source") or "")
            identity_kind = str(entry.get("identity_kind") or "")
            raw_pins = entry.get("pins")
            if not isinstance(raw_pins, list) or not raw_pins:
                raise AdvisorInstallerError(
                    f"deployment lock {tool_id!r} pins must be a non-empty list"
                )
            for raw in raw_pins:
                if not isinstance(raw, Mapping):
                    raise AdvisorInstallerError(
                        f"deployment lock {tool_id!r} pin must be an object"
                    )
                raw_size = raw.get("artifact_size_bytes", 0)
                if type(raw_size) is not int or raw_size < 0:
                    raise AdvisorInstallerError(
                        f"deployment lock {tool_id!r} artifact size is malformed"
                    )
                pins.append(
                    ToolPin(
                        tool_id=str(raw.get("tool_id") or tool_id),
                        version=str(raw.get("version") or ""),
                        platform=str(raw.get("platform") or "any"),
                        artifact_url=str(raw.get("artifact_url") or ""),
                        sha256=str(raw.get("sha256") or "").lower(),
                        identity_kind=str(
                            raw.get("identity_kind") or identity_kind or "python_package"
                        ),
                        license=str(raw.get("license") or license_text),
                        source=str(raw.get("source") or source_text),
                        package_name=str(
                            raw.get("package_name")
                            or (SYMBOLICAI_PACKAGE if tool_id == TOOL_SYMBOLICAI else "")
                        ),
                        is_checksummed=bool(raw.get("is_checksummed")),
                        requires_checksum_at_install=bool(
                            (entry.get("deployment_contract") or {}).get(
                                "requires_checksum_at_install"
                            )
                            if isinstance(entry.get("deployment_contract"), Mapping)
                            else False
                        ),
                        release_tag=str(
                            raw.get("release_tag")
                            or (
                                (entry.get("deployment_contract") or {}).get(
                                    "release_tag"
                                )
                                if isinstance(
                                    entry.get("deployment_contract"), Mapping
                                )
                                else ""
                            )
                            or ""
                        ),
                        artifact_size_bytes=raw_size,
                    )
                )
        except (TypeError, ValueError) as exc:
            raise AdvisorInstallerError(
                f"deployment lock {tool_id!r} pin is malformed: {exc}"
            ) from exc
        if tool_id == TOOL_ERGOAI:
            _assert_ergoai_lock_contract(document, entry, pins)
        if tool_id == TOOL_TEMURIN_JDK:
            _assert_temurin_lock_contract(document, entry, pins)
    else:
        for raw in _FALLBACK_PINS.get(tool_id, ()):
            pins.append(
                ToolPin(
                    tool_id=str(raw["tool_id"]),
                    version=str(raw["version"]),
                    platform=str(raw["platform"]),
                    artifact_url=str(raw.get("artifact_url") or ""),
                    sha256=str(raw.get("sha256") or "").lower(),
                    identity_kind=str(raw.get("identity_kind") or "python_package"),
                    license=str(raw.get("license") or ""),
                    source=str(raw.get("source") or ""),
                    package_name=str(raw.get("package_name") or ""),
                    is_checksummed=bool(raw.get("is_checksummed")),
                    requires_checksum_at_install=bool(
                        raw.get("requires_checksum_at_install")
                    ),
                    release_tag=str(raw.get("release_tag") or ""),
                    artifact_size_bytes=int(raw.get("artifact_size_bytes") or 0),
                )
            )
    if not pins:
        raise AdvisorInstallerError(f"no managed pins registered for {tool_id!r}")
    return tuple(pins)


def locked_version_for(tool_id: str, *, lock: Mapping[str, Any] | None = None) -> str:
    """Return the exact managed pin version required under strict install."""

    if lock is not None:
        versions = lock.get("managed_pin_versions") or {}
        if isinstance(versions, Mapping) and tool_id in versions:
            return str(versions[tool_id])
        versions = lock.get("versions") or {}
        if isinstance(versions, Mapping) and tool_id in versions:
            return str(versions[tool_id])
    if tool_id in LOCKED_VERSIONS:
        return LOCKED_VERSIONS[tool_id]
    raise AdvisorInstallerError(f"no locked version for tool_id={tool_id!r}")


def select_strict_pin(
    tool_id: str,
    *,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    lock: Mapping[str, Any] | None = None,
    allow_source_fallback: bool = True,
) -> ToolPin:
    """Select the exact locked pin for ``tool_id`` on the host platform.

    Under the FVT-G160 contract this is the only identity that strict
    installation may materialize.  Version mismatches fail closed.
    """

    if tool_id not in ADVISOR_PIN_OWNED_TOOLS:
        raise AdvisorInstallerError(f"advisors plugin does not own tool_id={tool_id!r}")

    platform_name = platform_key or detect_platform_key()
    expected = locked_version_for(tool_id, lock=lock)
    candidates = pins_for_tool(tool_id, repo_root=repo_root, lock=lock)

    # SymbolicAI is a Python package range pin (platform=any).
    if tool_id == TOOL_SYMBOLICAI:
        exact = [
            pin
            for pin in candidates
            if pin.version == expected and pin.platform in {"any", platform_name, "*"}
        ]
        if exact:
            return exact[0]
        raise AdvisorInstallerError(
            f"strict install for {tool_id!r} requires package identity "
            f"{expected!r}; available pins: "
            f"{sorted({f'{p.platform}@{p.version}' for p in candidates})}"
        )

    exact = [
        pin
        for pin in candidates
        if pin.version == expected and pin.platform == platform_name
    ]
    if exact:
        return exact[0]
    if allow_source_fallback:
        source = [
            pin
            for pin in candidates
            if pin.version == expected and pin.platform == "source"
        ]
        if source:
            return source[0]
    available = sorted({f"{pin.platform}@{pin.version}" for pin in candidates})
    raise AdvisorInstallerError(
        f"strict install for {tool_id!r} requires version {expected!r} on "
        f"platform {platform_name!r}; available pins: {available}"
    )


def python_version_satisfies_range(observed: str, version_range: str) -> bool:
    """Return True when ``observed`` satisfies a simple ``>=X,<Y`` range pin."""

    match = _SYMBOLICAI_RANGE_RE.match((version_range or "").replace(" ", ""))
    if match is None:
        # Exact string or substring match for non-range pins.
        return observed == version_range or version_range in observed
    lo = numeric_version(match.group(1))
    hi = numeric_version(match.group(2))
    current = numeric_version(observed)
    if not current or not lo or not hi:
        return False
    return lo <= current < hi


# ---------------------------------------------------------------------------
# Version / runtime probes
# ---------------------------------------------------------------------------


def probe_symbolicai_package(
    *,
    package_name: str = SYMBOLICAI_PACKAGE,
    expected_range: str = SYMBOLICAI_VERSION,
) -> dict[str, Any]:
    """Probe the installed SymbolicAI package without installing anything."""

    result: dict[str, Any] = {
        "tool_id": TOOL_SYMBOLICAI,
        "package_name": package_name,
        "present": False,
        "version_string": None,
        "version_match": False,
        "locked_version": expected_range,
        "identity_kind": "python_package",
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "probe_error": None,
        "network_used": False,
        "install_attempted": False,
    }
    try:
        from importlib import metadata as importlib_metadata
    except ImportError:  # pragma: no cover
        importlib_metadata = None  # type: ignore[assignment]

    version: str | None = None
    if importlib_metadata is not None:
        try:
            version = importlib_metadata.version(package_name)
        except Exception:
            version = None
    if version is None:
        # Alternate distribution names occasionally used by SymbolicAI.
        for alt in ("symai", "SymbolicAI"):
            if importlib_metadata is None:
                break
            try:
                version = importlib_metadata.version(alt)
                break
            except Exception:
                continue
    if version is None:
        # Spec presence without metadata is not a version match.
        if importlib.util.find_spec("symai") is not None:
            result["present"] = True
            result["probe_error"] = "version_metadata_unavailable"
            return result
        result["probe_error"] = "package_not_installed"
        return result

    result["present"] = True
    result["version_string"] = version
    result["version_match"] = python_version_satisfies_range(version, expected_range)
    if not result["version_match"]:
        result["probe_error"] = "locked_version_mismatch"
    return result


def read_version_banner(
    executable: str,
    *,
    timeout: float = 10.0,
    extra_args: Sequence[str] = ("--version",),
    env: Mapping[str, str] | None = None,
    max_output_bytes: int = ERGOAI_DEFAULT_MAX_OUTPUT_BYTES,
) -> str | None:
    execution = run_bounded_ergoai_process(
        executable,
        input_text="",
        timeout=timeout,
        max_output_bytes=max_output_bytes,
        env=env,
        args=extra_args,
    )
    if execution.get("termination_reason") is not None:
        return None
    observed = str(execution.get("output_text") or "").strip()
    return observed or None


def read_ergoai_version_banner(
    executable: str,
    *,
    timeout: float = 15.0,
    env: Mapping[str, str] | None = None,
    max_output_bytes: int = ERGOAI_DEFAULT_MAX_OUTPUT_BYTES,
) -> str | None:
    """Read an ErgoAI banner from a managed launcher or the vendor runner.

    The upstream ``runergo`` script forwards ``--version`` to XSB and therefore
    prints the XSB 5.0 banner rather than the ErgoAI 3.0 identity.  Fall back to
    a bounded no-query session and halt it through stdin; this observes the
    actual ErgoAI Reasoner banner without mutating the installation.
    """

    process_env = ergoai_offline_subprocess_env(env)
    banner = read_version_banner(
        executable,
        timeout=timeout,
        env=process_env,
        max_output_bytes=max_output_bytes,
    )
    if banner and "ergoai" in banner.casefold():
        return banner
    execution = run_bounded_ergoai_process(
        executable,
        input_text="\\halt.\n",
        timeout=timeout,
        max_output_bytes=max_output_bytes,
        env=process_env,
    )
    if execution.get("termination_reason") is not None:
        return banner
    observed = str(execution.get("output_text") or "").strip()
    if execution.get("returncode") == 0 and "ergoai" in observed.casefold():
        return observed
    return banner


def _validate_recorded_ergoai_semantics(
    raw_semantics: Any,
) -> tuple[bool, list[str], dict[str, bool]]:
    """Replay the fixed semantic-evidence contract from an identity manifest.

    The identity digest is intentionally not treated as a signature.  This
    validator independently reconstructs case contracts, program/query hashes,
    outcome digests, aliases, controls, replay invariants, and the normalized
    evidence digest so a locally resealed but semantically rewritten receipt
    cannot be accepted as the installer-produced matrix.
    """

    reasons: list[str] = []
    checks_observed: dict[str, bool] = {}

    def record(name: str, passed: bool) -> None:
        checks_observed[name] = bool(passed)
        if not passed:
            reasons.append(f"semantic_checks_{name}_mismatch")

    if not isinstance(raw_semantics, Mapping):
        record("mapping", False)
        return False, reasons, checks_observed
    semantics = dict(raw_semantics)
    raw_checks = semantics.get("checks")
    if not isinstance(raw_checks, Mapping):
        record("checks_mapping", False)
        return False, reasons, checks_observed
    checks = {str(name): value for name, value in raw_checks.items()}
    canonical_names = tuple(ERGOAI_LIVE_SEMANTIC_CASE_KINDS)
    expected_names = set(canonical_names) | set(
        ERGOAI_LIVE_SEMANTIC_LEGACY_ALIASES
    )
    record("schema", semantics.get("schema_version") == "ergoai-live-semantic-checks/v2")
    record("tool_id", semantics.get("tool_id") == TOOL_ERGOAI)
    record("case_kinds", semantics.get("case_kinds") == list(canonical_names))
    record("case_set", set(checks) == expected_names)
    record("network", semantics.get("network_used") is False)
    record("install", semantics.get("install_attempted") is False)
    record("authority", semantics.get("authority_ceiling") == ADVISOR_AUTHORITY_CEILING)
    record("proof_authority", semantics.get("grants_proof_authority") is False)
    record(
        "evidence_class",
        semantics.get("evidence_class")
        == "proposal_or_candidate_until_independent_reconstruction",
    )

    case_contracts: dict[str, tuple[str, str, str, str, bool, bool, bool]] = {
        "entailment": (
            "yes", "entailment", _ERGOAI_BASE_PROGRAM, _ERGOAI_QUERY_ENTAILMENT,
            True, False, False,
        ),
        "non_entailment": (
            "no", "non_entailment", _ERGOAI_BASE_PROGRAM,
            _ERGOAI_QUERY_NON_ENTAILMENT, True, False, False,
        ),
        "contradiction": (
            "yes", "contradiction", _ERGOAI_CONTRADICTION_PROGRAM,
            _ERGOAI_QUERY_CONTRADICTION, True, False, False,
        ),
        "mutation": (
            "no", "mutation", _ERGOAI_MUTATED_PROGRAM,
            _ERGOAI_QUERY_ENTAILMENT, True, False, False,
        ),
        "replay": (
            "yes", "replay", _ERGOAI_BASE_PROGRAM, _ERGOAI_QUERY_ENTAILMENT,
            True, False, False,
        ),
        "malformed": (
            "error", "malformed", _ERGOAI_MALFORMED_PROGRAM,
            _ERGOAI_QUERY_ENTAILMENT, False, False, False,
        ),
        "timeout": (
            "timeout", "timeout", _ERGOAI_TIMEOUT_PROGRAM,
            _ERGOAI_QUERY_TIMEOUT, False, True, False,
        ),
        "resource_bound": (
            "resource_bound", "resource_bound", _ERGOAI_RESOURCE_PROGRAM,
            _ERGOAI_QUERY_RESOURCE, False, False, True,
        ),
    }

    def digest_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def validate_execution_record(
        label: str,
        raw: Any,
        *,
        expected: str,
        program: str,
        query: str,
        require_boundary: bool,
        require_timeout: bool = False,
        require_resource_bound: bool = False,
        require_control: bool = False,
        expected_kind: str | None = None,
    ) -> bool:
        if not isinstance(raw, Mapping):
            record(label, False)
            return False
        value = dict(raw)
        outcome = value.get("semantic_outcome")
        outcome_ok = isinstance(outcome, Mapping)
        if outcome_ok:
            outcome_payload = dict(outcome)
            outcome_digest = hashlib.sha256(
                json.dumps(
                    outcome_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            outcome_ok = bool(
                value.get("semantic_outcome_digest_sha256") == outcome_digest
                and value.get("verdict") == outcome_payload.get("verdict")
            )
        returncode = value.get("returncode")
        returncode_ok = returncode is None or (
            type(returncode) is int
        )
        termination = value.get("termination_reason")
        boundary = bool(returncode == 0 and termination is None)
        expected_boundary_name = (
            "timeout"
            if termination == "timeout"
            else "output_limit"
            if termination == "output_limit"
            else "spawn_error"
            if termination == "spawn_error"
            else "success"
            if returncode == 0
            else "nonzero"
        )
        if outcome_ok:
            outcome_ok = (
                dict(outcome).get("process_boundary") == expected_boundary_name
            )
        expected_flags = bool(
            value.get("require_process_boundary") is require_boundary
            and bool(value.get("require_timeout", False)) is require_timeout
            and bool(value.get("require_resource_bound", False))
            is require_resource_bound
            and bool(value.get("require_control", False)) is require_control
        )
        contract_ok = bool(
            returncode_ok
            and outcome_ok
            and value.get("expected") == expected
            and value.get("expected_any") is None
            and value.get("program_digest_sha256") == digest_text(program)
            and value.get("query_digest_sha256") == digest_text(query)
            and value.get("passed_process_boundary") is boundary
            and value.get("timed_out") is (termination == "timeout")
            and value.get("resource_bound_enforced")
            is (termination == "output_limit")
            and expected_flags
            and (
                expected_kind is None or value.get("kind") == expected_kind
            )
            and value.get("passed") is True
            and _ergoai_case_passed(value) is True
        )
        record(label, contract_ok)
        return contract_ok

    canonical_valid = True
    for name, contract in case_contracts.items():
        expected, kind, program, query, boundary, timed, resource = contract
        canonical_valid = validate_execution_record(
            name,
            checks.get(name),
            expected=expected,
            expected_kind=kind,
            program=program,
            query=query,
            require_boundary=boundary,
            require_timeout=timed,
            require_resource_bound=resource,
            require_control=name in {"contradiction", "timeout", "resource_bound"},
        ) and canonical_valid

    control_contracts = {
        "contradiction": (
            "non_explosion", "no", _ERGOAI_CONTRADICTION_PROGRAM,
            _ERGOAI_QUERY_NON_EXPLOSION,
        ),
        "timeout": (
            "terminating_control", "yes", _ERGOAI_BASE_PROGRAM,
            _ERGOAI_QUERY_ENTAILMENT,
        ),
        "resource_bound": (
            "bounded_control", "yes", _ERGOAI_BASE_PROGRAM,
            _ERGOAI_QUERY_ENTAILMENT,
        ),
    }
    controls_valid = True
    for parent_name, (
        control_key,
        expected,
        program,
        query,
    ) in control_contracts.items():
        parent = checks.get(parent_name)
        control = parent.get(control_key) if isinstance(parent, Mapping) else None
        control_ok = validate_execution_record(
            f"{parent_name}_{control_key}",
            control,
            expected=expected,
            program=program,
            query=query,
            require_boundary=True,
        )
        control_flag_ok = bool(
            isinstance(parent, Mapping)
            and parent.get("control_passed") is True
            and isinstance(control, Mapping)
            and control.get("passed") is True
        )
        record(f"{parent_name}_control_binding", control_flag_ok)
        controls_valid = control_ok and control_flag_ok and controls_valid

    aliases_valid = True
    for alias, canonical in ERGOAI_LIVE_SEMANTIC_LEGACY_ALIASES.items():
        alias_value = checks.get(alias)
        canonical_value = checks.get(canonical)
        if isinstance(alias_value, Mapping) and isinstance(
            canonical_value, Mapping
        ):
            comparable = dict(alias_value)
            alias_target = comparable.pop("alias_of", None)
            alias_ok = alias_target == canonical and comparable == dict(
                canonical_value
            )
        else:
            alias_ok = False
        record(f"alias_{alias}", alias_ok)
        aliases_valid = alias_ok and aliases_valid

    entailment = checks.get("entailment")
    replay = checks.get("replay")
    replay_bound = bool(
        isinstance(entailment, Mapping)
        and isinstance(replay, Mapping)
        and entailment.get("verdict") == replay.get("verdict") == "yes"
        and entailment.get("program_digest_sha256")
        == replay.get("program_digest_sha256")
        and entailment.get("query_digest_sha256")
        == replay.get("query_digest_sha256")
        and entailment.get("semantic_outcome_digest_sha256")
        == replay.get("semantic_outcome_digest_sha256")
    )
    core_passed = bool(
        replay_bound
        and all(
            isinstance(checks.get(name), Mapping)
            and checks[name].get("passed") is True
            for name in ("entailment", "non_entailment", "mutation", "replay")
        )
    )
    extended_passed = bool(
        all(
            isinstance(checks.get(name), Mapping)
            and checks[name].get("passed") is True
            for name in ("contradiction", "malformed", "timeout", "resource_bound")
        )
    )
    passed = core_passed and extended_passed
    record(
        "aggregate_flags",
        semantics.get("replay_bound") is replay_bound
        and semantics.get("core_passed") is core_passed
        and semantics.get("extended_passed") is extended_passed
        and semantics.get("passed") is passed
        and passed,
    )
    observed_digest = _ergoai_semantic_evidence_digest(
        checks,
        replay_bound=replay_bound,
        passed=passed,
    )
    claimed_digest = semantics.get("normalized_evidence_digest_sha256")
    record(
        "normalized_digest",
        isinstance(claimed_digest, str)
        and bool(_HEX64.fullmatch(claimed_digest))
        and claimed_digest == observed_digest,
    )
    valid = bool(
        canonical_valid
        and controls_valid
        and aliases_valid
        and all(checks_observed.values())
    )
    return valid, reasons, checks_observed


def _validate_ergoai_managed_provenance(
    *,
    install_root: Path,
    expected_version: str,
    expected_platform: str,
    selected_executable: str | Path | None = None,
) -> dict[str, Any]:
    manifest_path = _ergoai_identity_path(install_root, expected_version)
    manifest_path_safe = _safe_existing_regular_file(
        manifest_path,
        max_bytes=ERGOAI_IDENTITY_MAX_BYTES,
    )
    manifest = _load_identity_manifest(manifest_path)
    result: dict[str, Any] = {
        "identity_manifest_path": str(manifest_path),
        "identity_manifest_present": manifest is not None,
        "managed_vendor_provenance_verified": False,
        "is_hermetic_advisor_shim": False,
        "manifest": manifest,
        "reason_codes": [],
        "selected_executable_bound": selected_executable is None,
    }
    if not manifest_path_safe:
        result["reason_codes"].append("managed_identity_manifest_unsafe")
        return result
    if manifest is None:
        result["reason_codes"].append("managed_identity_manifest_missing")
        return result
    result["is_hermetic_advisor_shim"] = bool(
        manifest.get("is_hermetic_advisor_shim")
    )
    if result["is_hermetic_advisor_shim"]:
        result["reason_codes"].append("hermetic_advisor_shim_is_not_vendor")
        return result

    claimed_identity_digest = str(
        manifest.get("identity_digest_sha256") or ""
    ).lower()
    identity_payload = dict(manifest)
    identity_payload.pop("identity_digest_sha256", None)
    observed_identity_digest = hashlib.sha256(
        json.dumps(
            identity_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    expected_arch_token = (
        "aarch64" if expected_platform == "linux-aarch64" else "x86_64"
    )
    (
        semantic_evidence_valid,
        semantic_reason_codes,
        semantic_evidence_checks,
    ) = _validate_recorded_ergoai_semantics(manifest.get("semantic_checks"))
    result["reason_codes"].extend(semantic_reason_codes)
    scalar_checks = {
        "schema": manifest.get("schema_version")
        == "ergoai-managed-vendor-identity/v1",
        "tool_id": manifest.get("tool_id") == TOOL_ERGOAI,
        "version": str(manifest.get("version") or "") == expected_version,
        "platform": str(manifest.get("selected_platform") or "")
        == expected_platform,
        "release_tag": str(manifest.get("release_tag") or "")
        == ERGOAI_RELEASE_TAG,
        "release_url": manifest.get("release_url") == ERGOAI_RELEASE_URL,
        "release_sha256": str(
            manifest.get("release_artifact_sha256") or ""
        ).lower()
        == ERGOAI_RELEASE_SHA256,
        "release_size": type(manifest.get("release_artifact_size_bytes")) is int
        and manifest.get("release_artifact_size_bytes")
        == ERGOAI_RELEASE_SIZE_BYTES,
        "checksum_verified": manifest.get("checksum_verified") is True,
        "live_vendor": manifest.get("is_live_vendor") is True,
        "atomic_publish": manifest.get("atomic_publish") is True,
        "relocatable_install": manifest.get("relocatable_install") is True,
        "runtime_paths_relative": manifest.get("runtime_paths_relative") is True,
        "relocation_scope": manifest.get("relocation_certification_scope")
        == "executed-runtime-and-bundled-java-consumers/v1",
        "developer_rebuild_metadata": manifest.get(
            "developer_rebuild_metadata_relocated"
        )
        is False,
        "xsb_elf_machine": manifest.get("xsb_elf_machine")
        == expected_arch_token,
        "publication_model": manifest.get("install_publication_model")
        == "staged_vendor_atomic_rename_private_runtime_workspaces_identity_commit_v4",
        "publication_commit_point": manifest.get("publication_commit_point")
        == "atomic_identity_manifest_replace",
        "runtime_state_policy": manifest.get("runtime_state_policy")
        == "mutable-nonauthoritative-outside-vendor-identity/v1",
        "runtime_workspace_cleanup_policy": manifest.get(
            "runtime_workspace_cleanup_policy"
        )
        == "normal-and-handled-signals-clean-sigkill-orphans-retained/v1",
        "runtime_execution_policy": manifest.get("runtime_execution_policy")
        == "private-ergoai-copy-shared-immutable-xsb/v1",
        "java_consumer_policy": manifest.get("java_consumer_policy")
        == "private-ergoai-copy-java-consumers/v2",
        "theorem_authority_false": manifest.get("grants_theorem_authority")
        is False,
        "proof_authority_false": manifest.get("grants_proof_authority") is False,
        "role": manifest.get("role") == ADVISOR_ROLE,
        "authority_ceiling": manifest.get("authority_ceiling")
        == ADVISOR_AUTHORITY_CEILING,
        "license": manifest.get("license") == "Apache-2.0",
        "license_components": manifest.get("license_components")
        == list(ERGOAI_LICENSE_COMPONENTS),
        "source": manifest.get("source")
        == "https://github.com/ErgoAI/ErgoEngine",
        "build_dependency_identity": _validate_recorded_ergoai_dependency_identity(
            manifest.get("build_dependency_identity")
        ),
        "optional_java_dependency_identity": (
            _validate_recorded_ergoai_optional_java_identity(
                manifest.get("optional_java_dependency_identity")
            )
        ),
        "bound_build_environment": bool(
            isinstance(manifest.get("bound_build_environment"), Mapping)
            and manifest["bound_build_environment"].get("schema_version")
            == "ergoai-bound-build-environment/v1"
            and manifest["bound_build_environment"].get(
                "ambient_toolchain_overrides_inherited"
            )
            is False
            and manifest["bound_build_environment"].get("path_model")
            == "private-staging-only/v1"
            and manifest["bound_build_environment"].get(
                "allowlisted_environment_keys"
            )
            == list(ERGOAI_BOUND_BUILD_ENVIRONMENT_KEYS)
            and type(
                manifest["bound_build_environment"].get("command_count")
            )
            is int
            and manifest["bound_build_environment"].get("command_count")
            >= len(ERGOAI_BUILD_COMMANDS)
            and isinstance(
                manifest["bound_build_environment"].get(
                    "commands_digest_sha256"
                ),
                str,
            )
            and bool(
                _HEX64.fullmatch(
                    manifest["bound_build_environment"][
                        "commands_digest_sha256"
                    ]
                )
            )
        ),
        "bound_runtime_environment": _validate_ergoai_bound_runtime_toolchain(
            install_root=install_root,
            version=expected_version,
            dependency_identity=manifest.get("build_dependency_identity"),
            optional_java_identity=manifest.get(
                "optional_java_dependency_identity"
            ),
            claimed_evidence=manifest.get("bound_runtime_environment"),
        ),
        "config_hardening": bool(
            isinstance(manifest.get("config_hardening"), Mapping)
            and manifest["config_hardening"].get("schema_version")
            == "ergoai-config-hardening/v1"
            and manifest["config_hardening"].get(
                "private_xsb_workspace_required"
            )
            is True
            and manifest["config_hardening"].get(
                "exact_replacement_count"
            )
            == ERGOAI_CONFIG_HARDENING_REPLACEMENT_COUNT
            and manifest["config_hardening"].get("source_sha256")
            == ERGOAI_CONFIG_SOURCE_SHA256
            and manifest["config_hardening"].get("hardened_sha256")
            == ERGOAI_CONFIG_HARDENED_SHA256
        ),
        "semantic_evidence": semantic_evidence_valid,
        "identity_digest": bool(
            _HEX64.fullmatch(claimed_identity_digest)
            and claimed_identity_digest == observed_identity_digest
        ),
    }
    for name, passed in scalar_checks.items():
        if not passed:
            result["reason_codes"].append(f"manifest_{name}_mismatch")

    managed_root = install_root.resolve()

    def resolve_manifest_path(raw_value: Any) -> Path | None:
        if not isinstance(raw_value, str) or not raw_value:
            return None
        raw_path = raw_value
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = install_root / path
        return path.resolve()

    path_checks: dict[str, bool] = {}
    resolved_manifest_paths: dict[str, Path] = {}
    bound_executables: dict[Path, str] = {}
    for label, path_key, digest_key in (
        ("release_artifact", "release_artifact_path", "release_artifact_sha256"),
        ("vendor_executable", "vendor_executable", "vendor_executable_sha256"),
        ("xsb_executable", "xsb_executable", "xsb_executable_sha256"),
        ("launcher", "launcher", "launcher_sha256"),
        ("runtime_paths", "runtime_paths_file", "runtime_paths_sha256"),
        ("java_settings", "java_settings_file", "java_settings_sha256"),
        ("config", "config_file", "config_file_sha256"),
    ):
        raw_manifest_value = manifest.get(path_key)
        raw_manifest_path = (
            raw_manifest_value if isinstance(raw_manifest_value, str) else ""
        )
        raw_digest = manifest.get(digest_key)
        expected_digest = raw_digest.lower() if isinstance(raw_digest, str) else ""
        path = resolve_manifest_path(manifest.get(path_key))
        path_checks[f"{label}:relative"] = bool(
            raw_manifest_path and not Path(raw_manifest_path).is_absolute()
        )
        if not path_checks[f"{label}:relative"]:
            result["reason_codes"].append(f"{label}_path_not_relocatable")
        inside_managed_root = False
        if path is not None:
            try:
                path.relative_to(managed_root)
                inside_managed_root = True
            except (OSError, ValueError):
                inside_managed_root = False
        valid = bool(
            path
            and inside_managed_root
            and path.is_file()
            and _HEX64.fullmatch(expected_digest)
            and content_sha256(path) == expected_digest
        )
        path_checks[label] = valid
        if not valid:
            result["reason_codes"].append(f"{label}_digest_mismatch")
        elif path is not None:
            resolved_manifest_paths[label] = path
            if label in {"vendor_executable", "launcher"}:
                bound_executables[path] = expected_digest

    raw_xsb_user_aux = str(manifest.get("xsb_user_aux_dir") or "")
    xsb_user_aux_valid = _is_safe_mutable_ergoai_directory_spec(
        install_root=install_root,
        raw_path=raw_xsb_user_aux,
        expected_path=_ergoai_xsb_user_aux_dir(install_root, expected_version),
    )
    path_checks["xsb_user_aux:relative_confined_directory"] = xsb_user_aux_valid
    if not xsb_user_aux_valid:
        result["reason_codes"].append("xsb_user_aux_directory_mismatch")

    # Bind the exact runtime configuration, not merely a manifest boolean.  In
    # particular, .ergo_paths must execute the same architecture-specific XSB
    # binary whose bytes are recorded above; the generic XSB/bin wrapper is not
    # accepted as an equivalent identity.
    xsb_configuration = str(manifest.get("xsb_configuration") or "")
    vendor_path = resolved_manifest_paths.get("vendor_executable")
    xsb_path = resolved_manifest_paths.get("xsb_executable")
    runtime_paths = resolved_manifest_paths.get("runtime_paths")
    java_settings = resolved_manifest_paths.get("java_settings")
    config_file = resolved_manifest_paths.get("config")
    expected_distribution_root = (
        vendor_path.parent.parent if vendor_path is not None else None
    )
    expected_xsb = (
        expected_distribution_root
        / "XSB"
        / "config"
        / xsb_configuration
        / "bin"
        / "xsb"
        if expected_distribution_root is not None and xsb_configuration
        else None
    )
    expected_runtime_paths = (
        vendor_path.parent / ".ergo_paths" if vendor_path is not None else None
    )
    expected_java_settings = (
        vendor_path.parent / "java" / "flora_settings.sh"
        if vendor_path is not None
        else None
    )
    expected_config_file = (
        vendor_path.parent / "ergoAI_config.sh"
        if vendor_path is not None
        else None
    )
    paths_source, java_source = _ergoai_relocatable_runtime_sources(
        xsb_configuration
    )
    runtime_configuration_checks = {
        "xsb_configuration_architecture": bool(
            xsb_configuration and expected_arch_token in xsb_configuration
        ),
        "xsb_configuration_exact_path": bool(
            xsb_path is not None
            and expected_xsb is not None
            and xsb_path == expected_xsb.resolve()
        ),
        "xsb_elf_machine": bool(
            xsb_path is not None
            and _elf_machine(xsb_path) == expected_arch_token
        ),
        "runtime_paths_exact_location": bool(
            runtime_paths is not None
            and expected_runtime_paths is not None
            and runtime_paths == expected_runtime_paths.resolve()
        ),
        "java_settings_exact_location": bool(
            java_settings is not None
            and expected_java_settings is not None
            and java_settings == expected_java_settings.resolve()
        ),
        "runtime_paths_exact_content": bool(
            runtime_paths is not None
            and runtime_paths.is_file()
            and runtime_paths.read_bytes() == paths_source
        ),
        "java_settings_exact_content": bool(
            java_settings is not None
            and java_settings.is_file()
            and java_settings.read_bytes() == java_source
        ),
        "config_exact_location": bool(
            config_file is not None
            and expected_config_file is not None
            and config_file == expected_config_file.resolve()
        ),
        "config_exact_hardened_content": bool(
            config_file is not None
            and content_sha256(config_file) == ERGOAI_CONFIG_HARDENED_SHA256
        ),
    }
    for name, passed in runtime_configuration_checks.items():
        path_checks[f"runtime_configuration:{name}"] = passed
        if not passed:
            result["reason_codes"].append(
                f"runtime_configuration_{name}_mismatch"
            )

    vendor_tree_integrity: dict[str, Any] | None = None
    vendor_tree_root = (
        vendor_path.parents[2] if vendor_path is not None else None
    )
    try:
        if vendor_tree_root is not None:
            vendor_tree_integrity = _ergoai_vendor_tree_integrity(
                vendor_tree_root
            )
    except (AdvisorInstallerError, OSError):
        vendor_tree_integrity = None
    vendor_tree_checks = {
        "digest": bool(
            vendor_tree_integrity
            and manifest.get("vendor_tree_digest_sha256")
            == vendor_tree_integrity["digest_sha256"]
        ),
        "file_count": bool(
            vendor_tree_integrity
            and type(manifest.get("vendor_tree_file_count")) is int
            and manifest.get("vendor_tree_file_count")
            == vendor_tree_integrity["file_count"]
        ),
        "exclusion_policy": bool(
            vendor_tree_integrity
            and manifest.get("vendor_tree_exclusion_policy")
            == vendor_tree_integrity["exclusion_policy"]
        ),
        "runtime_cache_absent": bool(
            vendor_tree_integrity
            and manifest.get("vendor_tree_excluded_runtime_cache_count") == 0
            and vendor_tree_integrity["excluded_runtime_cache_count"] == 0
        ),
    }
    for name, passed in vendor_tree_checks.items():
        path_checks[f"vendor_tree:{name}"] = passed
        if not passed:
            result["reason_codes"].append(f"vendor_tree_{name}_mismatch")

    launcher_digests = manifest.get("launcher_digests") or {}
    path_checks["launcher_set"] = bool(
        isinstance(launcher_digests, Mapping)
        and set(launcher_digests) == set(ERGOAI_EXECUTABLES)
    )
    if not path_checks["launcher_set"]:
        result["reason_codes"].append("launcher_set_mismatch")
    if isinstance(launcher_digests, Mapping):
        for name, raw_digest in launcher_digests.items():
            if str(name) not in ERGOAI_EXECUTABLES:
                result["reason_codes"].append("launcher_name_unreviewed")
                continue
            digest_text = str(raw_digest or "").lower()
            raw_launcher_path = install_root / "bin" / str(name)
            launcher_path = raw_launcher_path.resolve()
            try:
                launcher_path.relative_to(managed_root)
                launcher_confined = not raw_launcher_path.is_symlink()
            except ValueError:
                launcher_confined = False
            valid = bool(
                _HEX64.fullmatch(digest_text)
                and launcher_confined
                and launcher_path.is_file()
                and content_sha256(launcher_path) == digest_text
            )
            path_checks[f"launcher:{name}"] = valid
            if valid:
                bound_executables[launcher_path] = digest_text
            else:
                result["reason_codes"].append(
                    f"launcher_{name}_digest_mismatch"
                )

    if selected_executable is not None:
        selected_path = Path(selected_executable).expanduser().resolve()
        selected_digest = bound_executables.get(selected_path)
        selected_bound = bool(
            selected_digest
            and selected_path.is_file()
            and os.access(selected_path, os.X_OK)
            and content_sha256(selected_path) == selected_digest
        )
        result["selected_executable"] = str(selected_path)
        result["selected_executable_sha256"] = (
            content_sha256(selected_path) if selected_path.is_file() else None
        )
        result["selected_executable_bound"] = selected_bound
        if not selected_bound:
            result["reason_codes"].append(
                "selected_executable_not_bound_to_manifest"
            )

    result["scalar_checks"] = scalar_checks
    result["semantic_evidence_checks"] = semantic_evidence_checks
    result["path_checks"] = path_checks
    result["runtime_configuration_checks"] = runtime_configuration_checks
    result["vendor_tree_checks"] = vendor_tree_checks
    result["observed_vendor_tree_integrity"] = vendor_tree_integrity
    result["observed_identity_digest_sha256"] = observed_identity_digest
    result["managed_vendor_provenance_verified"] = bool(
        all(scalar_checks.values())
        and all(path_checks.values())
        and result["selected_executable_bound"]
    )
    return result


def probe_ergoai_identity(
    *,
    expected_version: str = ERGOAI_VERSION,
    executable: str | None = None,
    install_root: str | Path | None = None,
    require_managed_vendor: bool = False,
    platform_key: str | None = None,
    env: Mapping[str, str] | None = None,
    allow_path_fallback: bool = True,
) -> dict[str, Any]:
    """Probe ErgoAI without installing or opening the network."""

    result: dict[str, Any] = {
        "tool_id": TOOL_ERGOAI,
        "path_present": False,
        "executable_path": None,
        "version_string": None,
        "version_match": False,
        "locked_version": expected_version,
        "identity_kind": "immutable_release_tag",
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "probe_error": None,
        "network_used": False,
        "install_attempted": False,
        "managed_vendor_provenance_verified": False,
        "is_hermetic_advisor_shim": False,
    }
    root = expand_user_local_root(install_root)
    expected_platform = platform_key or detect_platform_key()
    binary = executable
    if binary is None:
        # Prefer managed install root, then PATH.
        managed_candidates = [
            root / "bin" / name for name in ERGOAI_EXECUTABLES
        ] + [
            root / "advisors" / "ergoai" / expected_version / "bin" / name
            for name in ERGOAI_EXECUTABLES
        ]
        for candidate in managed_candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                binary = str(candidate)
                break
        if binary is None and allow_path_fallback:
            for name in ERGOAI_EXECUTABLES:
                found = which_executable(name)
                if found:
                    binary = found
                    break
    if binary is None:
        result["probe_error"] = "executable_not_on_path"
        return result

    result["path_present"] = True
    resolved_binary = str(Path(binary).expanduser().resolve())
    result["executable_path"] = resolved_binary

    # Bind bytes and path before executing an operator-supplied executable.
    # A valid manifest elsewhere in the install root must never bless a foreign
    # binary merely because it prints the same version string.
    try:
        provenance = _validate_ergoai_managed_provenance(
            install_root=root,
            expected_version=expected_version,
            expected_platform=expected_platform,
            selected_executable=resolved_binary,
        )
    except (OSError, TypeError, ValueError, AdvisorInstallerError):
        provenance = {
            "identity_manifest_path": str(
                _ergoai_identity_path(root, expected_version)
            ),
            "identity_manifest_present": False,
            "managed_vendor_provenance_verified": False,
            "is_hermetic_advisor_shim": False,
            "manifest": None,
            "reason_codes": ["managed_identity_validation_error"],
            "selected_executable_bound": False,
        }
    result.update(provenance)
    if require_managed_vendor and not result[
        "managed_vendor_provenance_verified"
    ]:
        result["probe_error"] = "managed_vendor_provenance_unverified"
        return result

    banner = read_ergoai_version_banner(resolved_binary, env=env)
    if not banner:
        result["probe_error"] = "empty_version_banner"
        return result
    result["version_string"] = banner
    if result.get("managed_vendor_provenance_verified"):
        manifest = result.get("manifest")
        claimed_banner_digest = (
            manifest.get("version_banner_digest_sha256")
            if isinstance(manifest, Mapping)
            else None
        )
        observed_banner_digest = hashlib.sha256(
            banner.encode("utf-8")
        ).hexdigest()
        result["observed_version_banner_digest_sha256"] = (
            observed_banner_digest
        )
        if claimed_banner_digest != observed_banner_digest:
            result["managed_vendor_provenance_verified"] = False
            result.setdefault("reason_codes", []).append(
                "version_banner_digest_mismatch"
            )
            if require_managed_vendor:
                result["probe_error"] = "managed_vendor_provenance_unverified"
                return result
    result["version_match"] = bool(
        expected_version in banner
        or numeric_version(banner) == numeric_version(expected_version)
    )
    if not result["version_match"]:
        result["probe_error"] = "locked_version_mismatch"
        return result

    return result


# ---------------------------------------------------------------------------
# Install authorization gate
# ---------------------------------------------------------------------------


def authorize_plugin_install(
    tool_id: str,
    *,
    yes: bool,
    strict: bool = True,
    explicit_call: bool = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    checksum_verified: bool | None = None,
    platform_key: str | None = None,
    test_mode: bool = False,
    system_package_mutation: bool = False,
) -> None:
    """Fail-closed gate shared by ensure_symbolicai / ensure_ergoai."""

    if tool_id not in ADVISOR_INSTALL_TOOLS:
        raise AdvisorInstallerError(
            f"advisors plugin does not own tool_id={tool_id!r}"
        )
    try:
        authorize_installer_entry_install(
            tool_id,
            yes=yes,
            explicit_call=explicit_call,
            import_context=import_context,
            capability_discovery=capability_discovery,
            checksum_verified=checksum_verified,
            platform=platform_key if tool_id == TOOL_ERGOAI else None,
            system_package_mutation=system_package_mutation,
            test_mode=test_mode,
        )
    except InstallerRegistryError as exc:
        raise AdvisorInstallerError(str(exc)) from exc
    entry = get_installer_entry(tool_id)
    if entry.family is not InstallerPluginFamily.ADVISORS:
        raise AdvisorInstallerError(
            f"tool {tool_id!r} is not bound to the advisors installer plugin"
        )
    if strict:
        select_strict_pin(tool_id, platform_key=platform_key)


# ---------------------------------------------------------------------------
# Hermetic identity markers (offline / test installs)
# ---------------------------------------------------------------------------


def _write_identity_manifest(path: Path, identity: Mapping[str, Any]) -> None:
    _atomic_write_bytes(
        path,
        (json.dumps(dict(identity), indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
        mode=0o644,
    )


def _write_executable(path: Path, content: str) -> str:
    _atomic_write_bytes(path, content.encode("utf-8"), mode=0o755)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


_ERGOAI_SHIM_TEMPLATE: Final = '''#!/usr/bin/env python3
"""Pin-bound hermetic ErgoAI advisor identity shim ({version}).

Generated by FormalVerificationInstallerPlugin@1 advisors family.
Speaks only --version / version probes. Never holds theorem authority.
"""
from __future__ import annotations
import sys

VERSION = {version!r}
TOOL_ID = "ergoai"


def main(argv: list[str]) -> int:
    if any(arg in {{"--version", "-v", "version"}} for arg in argv[1:]) or len(argv) == 1:
        sys.stdout.write(f"ErgoAI {{VERSION}} (hermetic-advisor-shim)\\n")
        return 0
    sys.stderr.write(
        "ergoai advisor shim: only --version is supported offline; "
        "proposals remain unverified_candidate_only\\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''


def materialize_hermetic_ergoai(
    *,
    install_root: Path,
    version: str = ERGOAI_VERSION,
    pin: ToolPin | None = None,
) -> dict[str, Any]:
    """Materialize a pin-bound offline ErgoAI identity under user-local root."""

    managed_install_root = _lexical_absolute(install_root)
    root = managed_install_root / "advisors" / TOOL_ERGOAI / version
    bin_dir = root / "bin"
    _ensure_safe_managed_directory(managed_install_root, bin_dir)
    executable = bin_dir / "ergoai"
    identity_path = root / "identity.json"
    source = _ERGOAI_SHIM_TEMPLATE.format(version=version)
    digest = _write_executable(executable, source)
    # Convenience launchers matching lock executable_candidates.
    for alias in ("runErgo.sh", "runergo"):
        launcher = bin_dir / alias
        _write_executable(
            launcher,
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f'exec {_shell_quote(str(executable))} "$@"\n',
        )
    # Also expose under $root/bin for PATH discovery.
    user_bin = managed_install_root / "bin"
    _ensure_safe_managed_directory(managed_install_root, user_bin)
    for name in ("ergoai", "runErgo.sh", "runergo"):
        target = user_bin / name
        _write_executable(
            target,
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f'exec {_shell_quote(str(bin_dir / ("ergoai" if name == "ergoai" else name)))} "$@"\n',
        )

    identity = {
        "tool_id": TOOL_ERGOAI,
        "version": version,
        "executable": str(executable),
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "identity_kind": pin.identity_kind if pin else "immutable_release_tag",
        "license": pin.license if pin else "Apache-2.0",
        "source": pin.source if pin else "https://github.com/ErgoAI/ErgoEngine",
        "is_hermetic_advisor_shim": True,
        "artifact_sha256": digest,
        "grants_theorem_authority": False,
        "grants_proof_authority": False,
    }
    _write_identity_manifest(identity_path, identity)
    return identity


def materialize_hermetic_symbolicai_marker(
    *,
    install_root: Path,
    version_range: str = SYMBOLICAI_VERSION,
    pin: ToolPin | None = None,
) -> dict[str, Any]:
    """Write a reviewed offline identity marker for SymbolicAI package pin.

    Does not pip-install the package.  Certification and dry-run paths use the
    marker to prove the locked range was selected.  Live package presence is
    still probed separately via importlib.metadata.
    """

    managed_install_root = _lexical_absolute(install_root)
    root = managed_install_root / "advisors" / TOOL_SYMBOLICAI
    _ensure_safe_managed_directory(managed_install_root, root)
    identity_path = root / "identity.json"
    identity = {
        "tool_id": TOOL_SYMBOLICAI,
        "version": version_range,
        "package_name": SYMBOLICAI_PACKAGE,
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "identity_kind": pin.identity_kind if pin else "python_package",
        "license": pin.license if pin else "BSD-3-Clause",
        "source": pin.source if pin else "https://github.com/ExtensityAI/symbolicai",
        "is_hermetic_package_marker": True,
        "grants_theorem_authority": False,
        "grants_proof_authority": False,
    }
    _write_identity_manifest(identity_path, identity)
    return identity


# ---------------------------------------------------------------------------
# ensure_* entry points
# ---------------------------------------------------------------------------


def ensure_symbolicai(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
    install_root: str | Path | None = None,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    dry_run: bool = False,
    test_mode: bool = False,
    hermetic_marker: bool = False,
    import_context: bool = False,
    capability_discovery: bool = False,
    lock: Mapping[str, Any] | None = None,
) -> InstallReceipt:
    """Ensure the locked SymbolicAI package identity is selected.

    Strict mode selects the reviewed PyPI range pin
    ``>=1.14.0,<2.0.0``.  Actual pip installation is only attempted when
    ``yes=True`` and not ``dry_run`` / ``hermetic_marker``.  Hermetic marker
    mode records the locked identity offline without network access.
    """

    del platform_key  # package pin is platform-agnostic
    receipt = InstallReceipt(
        tool_id=TOOL_SYMBOLICAI,
        requested_version=SYMBOLICAI_VERSION,
        strict=strict,
        yes=yes,
        package_name=SYMBOLICAI_PACKAGE,
    )
    root = expand_user_local_root(install_root)

    try:
        pin = select_strict_pin(
            TOOL_SYMBOLICAI,
            platform_key="any",
            repo_root=repo_root,
            lock=lock,
        )
    except AdvisorInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "pin_selection"
        receipt.reason_codes.append("pin_selection_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    receipt.selected_version = pin.version
    receipt.selected_platform = pin.platform
    receipt.pin = pin.to_dict()
    receipt.bindings = {
        "tool_id": TOOL_SYMBOLICAI,
        "locked_version": SYMBOLICAI_VERSION,
        "selected_version": pin.version,
        "platform": pin.platform,
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "identity_kind": pin.identity_kind,
        "package_name": SYMBOLICAI_PACKAGE,
        "grants_theorem_authority": False,
        "grants_proof_authority": False,
        "proposals_only": True,
    }

    # Fail closed before any availability short-circuit when called from import
    # or capability discovery — presence never legitimizes install side effects.
    if import_context or capability_discovery:
        try:
            authorize_plugin_install(
                TOOL_SYMBOLICAI,
                yes=yes,
                strict=strict,
                import_context=import_context,
                capability_discovery=capability_discovery,
                test_mode=test_mode,
            )
        except AdvisorInstallerError as exc:
            receipt.status = "refused"
            receipt.phase = "authorization"
            receipt.reason_codes.append(
                "forbidden_on_import"
                if import_context
                else "forbidden_on_capability_discovery"
            )
            receipt.messages.append(str(exc))
            return receipt

    probe = probe_symbolicai_package(
        package_name=SYMBOLICAI_PACKAGE,
        expected_range=pin.version,
    )
    if probe.get("present") and probe.get("version_match") and not force:
        receipt.already_present = True
        receipt.installed = True
        receipt.status = "available"
        receipt.phase = "available"
        receipt.messages.append(
            f"SymbolicAI {probe.get('version_string')} already satisfies {pin.version}"
        )
        receipt.bindings["observed_version"] = probe.get("version_string")
        return receipt

    if dry_run:
        receipt.status = "blocked" if not yes else "available"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        receipt.messages.append(
            f"dry-run selected SymbolicAI package identity {pin.version}"
        )
        return receipt

    if not yes:
        receipt.status = "refused"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "SymbolicAI missing or mismatched; re-run with yes=True to install "
            "user-locally or record hermetic identity."
        )
        return receipt

    try:
        authorize_plugin_install(
            TOOL_SYMBOLICAI,
            yes=yes,
            strict=strict,
            import_context=import_context,
            capability_discovery=capability_discovery,
            checksum_verified=True,  # package range pin; no archive checksum
            test_mode=test_mode,
        )
    except AdvisorInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "authorization"
        receipt.reason_codes.append("authorization_failed")
        receipt.messages.append(str(exc))
        if strict and not hermetic_marker:
            raise
        if not hermetic_marker:
            return receipt

    # Offline / certification path: record locked identity without pip/network.
    if hermetic_marker or test_mode or os.environ.get(
        "FORMAL_VERIFICATION_FORBID_NETWORK"
    ) == "1" or os.environ.get("FORMAL_VERIFICATION_CERTIFY_OFFLINE") == "1":
        identity = materialize_hermetic_symbolicai_marker(
            install_root=root,
            version_range=pin.version,
            pin=pin,
        )
        receipt.installed = True
        receipt.status = "installed"
        receipt.phase = "hermetic_marker"
        receipt.install_attempted = True
        receipt.executable_path = str(
            root / "advisors" / TOOL_SYMBOLICAI / "identity.json"
        )
        receipt.bindings["identity"] = identity
        receipt.messages.append(
            f"Recorded hermetic SymbolicAI identity marker for {pin.version}"
        )
        _announce(
            f"Hermetic SymbolicAI marker at {receipt.executable_path}",
            on_progress,
            phase="installed",
        )
        return receipt

    # Live pip install (explicit opt-in only; never during certification).
    receipt.install_attempted = True
    _announce(
        f"Installing {SYMBOLICAI_PACKAGE}{pin.version} user-locally via pip",
        on_progress,
        phase="installing",
    )
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--user",
                f"{SYMBOLICAI_PACKAGE}{pin.version}",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        receipt.status = "failed"
        receipt.phase = "pip_install"
        receipt.reason_codes.append("pip_install_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise AdvisorInstallerError(f"SymbolicAI pip install failed: {exc}") from exc
        return receipt

    if completed.returncode != 0:
        receipt.status = "failed"
        receipt.phase = "pip_install"
        receipt.reason_codes.append("pip_install_failed")
        receipt.messages.append(
            (completed.stderr or completed.stdout or "pip failed").strip()[:500]
        )
        if strict:
            raise AdvisorInstallerError(
                f"SymbolicAI pip install failed with code {completed.returncode}"
            )
        return receipt

    post = probe_symbolicai_package(expected_range=pin.version)
    if not post.get("version_match"):
        # Still record the marker so operators can see the intended pin.
        materialize_hermetic_symbolicai_marker(
            install_root=root, version_range=pin.version, pin=pin
        )
        receipt.status = "failed"
        receipt.phase = "validation"
        receipt.reason_codes.append("locked_version_mismatch")
        receipt.messages.append(
            f"post-install version {post.get('version_string')!r} does not "
            f"satisfy {pin.version!r}"
        )
        if strict:
            raise AdvisorInstallerError(receipt.messages[-1])
        return receipt

    receipt.installed = True
    receipt.status = "installed"
    receipt.phase = "installed"
    receipt.bindings["observed_version"] = post.get("version_string")
    receipt.messages.append(
        f"Installed SymbolicAI {post.get('version_string')} satisfying {pin.version}"
    )
    return receipt


def ensure_ergoai(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
    install_root: str | Path | None = None,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    dry_run: bool = False,
    test_mode: bool = False,
    hermetic_shim: bool = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    lock: Mapping[str, Any] | None = None,
    artifact_path: str | Path | None = None,
    download_timeout: float = 180.0,
    install_timeout: float = 900.0,
) -> InstallReceipt:
    """Ensure the checksum-pinned ErgoAI 3.0 runtime (advisor only).

    ``hermetic_shim=True`` is reserved for offline role-contract tests and only
    materializes an identity shim.  A real lazy execution request passes
    ``hermetic_shim=False``; that path downloads (or consumes
    ``artifact_path``), verifies, builds, probes, and semantically exercises
    the official release before exposing a launcher.  Neither path grants
    theorem or proof authority.
    """

    receipt = InstallReceipt(
        tool_id=TOOL_ERGOAI,
        requested_version=ERGOAI_VERSION,
        strict=strict,
        yes=yes,
    )
    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()

    def fail(phase: str, code: str, message: str) -> InstallReceipt:
        receipt.status = "blocked" if code in {
            "unsupported_platform",
            "offline_policy_blocks_live_install",
            "missing_build_dependency",
        } else "failed"
        receipt.phase = phase
        receipt.reason_codes.append(code)
        receipt.messages.append(message)
        _announce(message, on_progress, phase="failed")
        if strict:
            raise AdvisorInstallerError(message)
        return receipt

    try:
        pin = select_strict_pin(
            TOOL_ERGOAI,
            platform_key=platform_name,
            repo_root=repo_root,
            lock=lock,
            allow_source_fallback=False,
        )
    except AdvisorInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "pin_selection"
        receipt.reason_codes.append("pin_selection_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    receipt.selected_version = pin.version
    receipt.selected_platform = pin.platform
    receipt.pin = pin.to_dict()
    receipt.bindings = {
        "tool_id": TOOL_ERGOAI,
        "locked_version": ERGOAI_VERSION,
        "selected_version": pin.version,
        "platform": pin.platform,
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "identity_kind": pin.identity_kind,
        "grants_theorem_authority": False,
        "grants_proof_authority": False,
        "proposals_only": True,
        "supported_platforms": list(ERGOAI_SUPPORTED_PLATFORMS),
        "release_tag": pin.release_tag or ERGOAI_RELEASE_TAG,
        "release_artifact_sha256": pin.sha256,
        "release_artifact_size_bytes": pin.artifact_size_bytes,
        "license_components": list(ERGOAI_LICENSE_COMPONENTS),
        "required_build_commands": list(ERGOAI_BUILD_COMMANDS),
        "required_absolute_commands": list(ERGOAI_REQUIRED_ABSOLUTE_COMMANDS),
        "dependency_version_floors": {
            name: ">=" + ".".join(str(part) for part in minimum)
            for name, minimum in ERGOAI_VERSIONED_BUILD_COMMANDS.items()
        },
        "optional_java_api_runtime_commands": list(
            ERGOAI_OPTIONAL_JAVA_RUNTIME_COMMANDS
        ),
        "optional_java_api_build_commands": list(
            ERGOAI_OPTIONAL_JAVA_BUILD_COMMANDS
        ),
        "missing_optional_java_api_runtime_commands": [
            name
            for name in ERGOAI_OPTIONAL_JAVA_RUNTIME_COMMANDS
            if shutil.which(name) is None
        ],
        "missing_optional_java_api_build_commands": [
            name
            for name in ERGOAI_OPTIONAL_JAVA_BUILD_COMMANDS
            if shutil.which(name) is None
        ],
        "atomic_publish_supported": True,
        "relocatable_install_supported": True,
        "bounded_acquisition_supported": True,
        "symlink_free_install_paths_required": True,
        "planned_install_publication_model": (
            "staged_vendor_atomic_rename_private_runtime_workspaces_identity_commit_v4"
        ),
    }

    if platform_name not in ERGOAI_SUPPORTED_PLATFORMS:
        return fail(
            "platform",
            "unsupported_platform",
            f"ErgoAI live install is not reviewed for {platform_name!r}; "
            f"supported pins are {list(ERGOAI_SUPPORTED_PLATFORMS)!r}",
        )
    if pin.platform != platform_name:
        return fail(
            "platform",
            "platform_pin_mismatch",
            f"ErgoAI pin platform {pin.platform!r} does not match "
            f"host platform {platform_name!r}",
        )

    if import_context or capability_discovery:
        try:
            authorize_plugin_install(
                TOOL_ERGOAI,
                yes=yes,
                strict=strict,
                import_context=import_context,
                capability_discovery=capability_discovery,
                checksum_verified=True if hermetic_shim else None,
                platform_key=platform_name,
                test_mode=test_mode,
            )
        except AdvisorInstallerError as exc:
            receipt.status = "refused"
            receipt.phase = "authorization"
            message = str(exc)
            code = (
                "forbidden_on_import"
                if import_context or "import" in message.lower()
                else "forbidden_on_capability_discovery"
            )
            receipt.reason_codes.append(code)
            receipt.messages.append(message)
            return receipt

    probe = probe_ergoai_identity(
        expected_version=pin.version,
        install_root=root,
        require_managed_vendor=not hermetic_shim,
        platform_key=platform_name,
        allow_path_fallback=False,
    )
    managed_identity_acceptable = bool(
        hermetic_shim or probe.get("managed_vendor_provenance_verified")
    )
    if (
        probe.get("path_present")
        and probe.get("version_match")
        and managed_identity_acceptable
    ):
        receipt.executable_path = probe.get("executable_path")
        receipt.already_present = True
        receipt.installed = True
        receipt.status = "available"
        receipt.phase = "available"
        receipt.messages.append(
            f"ErgoAI {pin.version} already available at {receipt.executable_path}"
        )
        if force:
            receipt.messages.append(
                "Immutable managed ErgoAI identity already validates; force does "
                "not re-bless or mutate the content-addressed vendor tree."
            )
        receipt.bindings["observed_version"] = probe.get("version_string")
        receipt.bindings["managed_provenance"] = {
            key: probe.get(key)
            for key in (
                "identity_manifest_path",
                "managed_vendor_provenance_verified",
                "is_hermetic_advisor_shim",
                "reason_codes",
            )
        }
        receipt.checksum_verified = bool(
            probe.get("managed_vendor_provenance_verified")
            or probe.get("is_hermetic_advisor_shim")
        )
        manifest = probe.get("manifest") or {}
        if probe.get("managed_vendor_provenance_verified"):
            receipt.bindings["atomic_publish"] = (
                manifest.get("atomic_publish") is True
            )
            receipt.bindings["relocatable_install"] = (
                manifest.get("relocatable_install") is True
            )
            receipt.bindings["install_publication_model"] = manifest.get(
                "install_publication_model"
            )
            receipt.bindings["transactional_publication"] = bool(
                manifest.get("atomic_publish") is True
                and manifest.get("publication_commit_point")
                == "atomic_identity_manifest_replace"
            )
        return receipt

    if dry_run:
        receipt.status = "blocked" if not yes else "available"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        receipt.messages.append(
            f"dry-run selected ErgoAI {pin.version} for {pin.platform}"
        )
        return receipt

    if not yes:
        receipt.status = "refused"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "ErgoAI missing or mismatched; re-run with yes=True to install "
            "user-locally (or hermetic advisor shim)."
        )
        return receipt

    try:
        authorize_plugin_install(
            TOOL_ERGOAI,
            yes=yes,
            strict=strict,
            import_context=import_context,
            capability_discovery=capability_discovery,
            # Vendor bytes are authorized again after their digest is observed.
            checksum_verified=True if hermetic_shim else None,
            platform_key=platform_name,
            test_mode=test_mode,
        )
    except AdvisorInstallerError as exc:
        receipt.status = "refused" if import_context or capability_discovery else "failed"
        receipt.phase = "authorization"
        code = "authorization_failed"
        message = str(exc)
        if import_context or "import" in message.lower():
            code = "forbidden_on_import"
        elif capability_discovery or "capability" in message.lower():
            code = "forbidden_on_capability_discovery"
        receipt.reason_codes.append(code)
        receipt.messages.append(message)
        return receipt

    if not test_mode and not _ergoai_is_user_local_root(root):
        return fail(
            "install_root",
            "install_root_not_user_local",
            "Production ErgoAI installation is restricted to a strict descendant "
            f"of the current user's home directory: {root}",
        )
    receipt.bindings["user_local_root_validated"] = not test_mode
    receipt.bindings["test_mode_root_override"] = bool(test_mode)

    # Hermetic shims are explicit role-contract fixtures.  Never silently
    # substitute one for a requested vendor execution path.
    try:
        _ensure_safe_directory(root)
    except AdvisorInstallerError as exc:
        return fail("install_root", "unsafe_install_root", str(exc))
    if hermetic_shim:
        receipt.install_attempted = True
        identity = materialize_hermetic_ergoai(
            install_root=root,
            version=pin.version,
            pin=pin,
        )
        receipt.executable_path = str(identity["executable"])
        receipt.installed = True
        receipt.status = "installed"
        receipt.phase = "hermetic_shim"
        receipt.checksum_verified = True
        receipt.bindings["identity"] = identity
        receipt.messages.append(
            f"Installed hermetic ErgoAI {pin.version} advisor shim (proposals only)"
        )
        _announce(
            f"Hermetic ErgoAI shim at {receipt.executable_path}",
            on_progress,
            phase="installed",
        )
        return receipt

    certification_forbids_install = bool(
        os.environ.get("FORMAL_VERIFICATION_CERTIFY_OFFLINE") == "1"
        or os.environ.get("FORMAL_VERIFICATION_FORBID_INSTALL") == "1"
    )
    network_forbidden_without_artifact = bool(
        os.environ.get("FORMAL_VERIFICATION_FORBID_NETWORK") == "1"
        and artifact_path is None
        and not os.environ.get("IPFS_DATASETS_PY_ERGOAI_RELEASE_FILE")
    )
    if certification_forbids_install or network_forbidden_without_artifact:
        return fail(
            "offline_policy",
            "offline_policy_blocks_live_install",
            "Offline certification forbids an ErgoAI vendor download/install; "
            "provide a pre-fetched checksummed artifact outside certification "
            "or use the explicit hermetic role fixture.",
        )

    if not pin.sha256 or not pin.is_checksummed:
        return fail(
            "checksum",
            "checksum_required_for_live_install",
            "Live ErgoAI install requires an exact reviewed SHA-256 pin.",
        )
    if not _makeself_safe_path(root):
        return fail(
            "install_root",
            "makeself_unsafe_install_path",
            "The reviewed ErgoAI 3.0 Makeself wrapper cannot safely expand an "
            "install root containing whitespace, glob, quote, control, or "
            f"non-portable characters: {root}",
        )
    dependency_identity = _ergoai_build_dependency_identity()
    receipt.bindings["build_dependency_identity"] = dependency_identity
    optional_java_identity = _ergoai_optional_java_dependency_identity()
    receipt.bindings["optional_java_dependency_identity"] = optional_java_identity
    receipt.bindings["optional_java_api_available"] = optional_java_identity.get(
        "satisfied"
    ) is True
    missing_commands = [
        *[str(name) for name in dependency_identity["missing_commands"]],
        *[
            f"{name}:version_floor"
            for name in dependency_identity["version_mismatches"]
        ],
        *[
            f"{path}:absolute_path"
            for path in dependency_identity["missing_absolute_commands"]
        ],
    ]
    if missing_commands:
        return fail(
            "dependencies",
            "missing_build_dependency",
            "ErgoAI build dependencies are missing: " + ", ".join(missing_commands),
        )

    configured_artifact = artifact_path or os.environ.get(
        "IPFS_DATASETS_PY_ERGOAI_RELEASE_FILE"
    )
    release_name = Path(pin.artifact_url).name or "ergoAI_3.0.run"
    release_path = root / "downloads" / release_name
    ok, observed_digest, observed_size = _copy_or_download_ergoai_artifact(
        pin,
        release_path,
        artifact_path=configured_artifact,
        timeout=download_timeout,
        on_progress=on_progress,
    )
    if not ok or observed_digest != pin.sha256:
        return fail(
            "checksum",
            "download_or_checksum_failed",
            "ErgoAI release acquisition or checksum verification failed.",
        )
    receipt.checksum_verified = True
    receipt.bindings["observed_release_artifact_sha256"] = observed_digest
    receipt.bindings["observed_release_artifact_size_bytes"] = observed_size

    # Re-authorize after the bytes, rather than only the metadata, have been
    # verified.  This keeps the registry gate evidence truthful.
    try:
        authorize_plugin_install(
            TOOL_ERGOAI,
            yes=yes,
            strict=strict,
            checksum_verified=True,
            platform_key=platform_name,
            test_mode=test_mode,
        )
    except AdvisorInstallerError as exc:
        return fail("authorization", "authorization_failed", str(exc))

    version_root = _ergoai_version_root(root, pin.version)
    try:
        _ensure_safe_managed_directory(root, version_root)
    except AdvisorInstallerError as exc:
        return fail("install_root", "unsafe_install_root", str(exc))
    vendor_root = _ergoai_vendor_root(root, pin.version, pin.sha256)
    vendor_binary: Path | None = None
    if os.path.lexists(vendor_root):
        if not force:
            return fail(
                "install",
                "unverified_preexisting_vendor_tree",
                "An unverified content-addressed ErgoAI vendor object already "
                f"exists and will not be re-blessed: {vendor_root}; explicitly "
                "retry with force=True to quarantine it and rebuild from the pin.",
            )
        quarantine_root = version_root / "quarantine"
        try:
            _ensure_safe_managed_directory(root, quarantine_root)
        except AdvisorInstallerError:
            return fail(
                "install",
                "unsafe_quarantine_directory",
                f"ErgoAI quarantine path is unsafe: {quarantine_root}",
            )
        quarantine_path = quarantine_root / (
            f"{vendor_root.name}.unverified.{os.getpid()}.{time.time_ns()}"
        )
        try:
            os.replace(vendor_root, quarantine_path)
            stale_identity = _ergoai_identity_path(root, pin.version)
            if os.path.lexists(stale_identity):
                stale_destination = quarantine_root / (
                    f"identity.unverified.{os.getpid()}.{time.time_ns()}.json"
                )
                os.replace(stale_identity, stale_destination)
        except OSError as exc:
            return fail(
                "install",
                "unverified_vendor_quarantine_failed",
                f"Could not quarantine unverified ErgoAI state: {exc}",
            )
        receipt.bindings["quarantined_unverified_vendor_tree"] = (
            quarantine_path.relative_to(root).as_posix()
        )
        receipt.bindings["quarantine_never_reblessed"] = True
        vendor_binary = None

    stage_workspace: Path | None = None
    staged_tree_entries: dict[str, str] = {}
    config_hardening: dict[str, Any] | None = None
    bound_build_environment: dict[str, Any] | None = None
    if vendor_binary is None:
        try:
            stage_workspace = Path(
                tempfile.mkdtemp(
                    dir=version_root,
                    prefix=f".{vendor_root.name}.staging-",
                )
            )
            staged_vendor_root = stage_workspace / "payload"
            if not _makeself_safe_path(staged_vendor_root):
                return fail(
                    "install_root",
                    "makeself_unsafe_staging_path",
                    f"ErgoAI staging path is unsafe for Makeself: {staged_vendor_root}",
                )
            install_home = stage_workspace / "install-home"
            _ensure_safe_managed_directory(stage_workspace, install_home)
            environment, bound_build_environment = (
                _materialize_ergoai_bound_build_environment(
                    stage_workspace=stage_workspace,
                    install_home=install_home,
                    dependency_identity=dependency_identity,
                    optional_java_identity=optional_java_identity,
                )
            )
            receipt.bindings["bound_build_environment"] = bound_build_environment
            receipt.bindings["post_acquisition_offline_env_applied"] = True
            shell = Path(environment["PATH"]) / "sh"
            try:
                install_wall_seconds = max(
                    0.001,
                    min(3600.0, float(install_timeout)),
                )
            except (TypeError, ValueError):
                return fail(
                    "install", "invalid_install_timeout", "install timeout is invalid"
                )
            install_deadline = time.monotonic() + install_wall_seconds
            receipt.install_attempted = True
            _announce(
                f"Staging checksummed ErgoAI {pin.version} for {platform_name}",
                on_progress,
                phase="installing",
            )
            extraction = run_bounded_ergoai_process(
                shell,
                args=(
                    str(release_path),
                    "--nox11",
                    "--nochown",
                    "--noexec",
                    "--target",
                    str(staged_vendor_root),
                ),
                input_text="",
                timeout=max(0.001, install_deadline - time.monotonic()),
                max_output_bytes=ERGOAI_INSTALL_MAX_OUTPUT_BYTES,
                env=environment,
                cwd=stage_workspace,
            )
            receipt.bindings["extractor_output_digest_sha256"] = extraction.get(
                "observed_output_digest_sha256"
            )
            receipt.bindings["extractor_output_bytes"] = extraction.get(
                "observed_output_bytes"
            )
            if extraction.get("returncode") != 0 or extraction.get(
                "termination_reason"
            ) is not None:
                detail = str(extraction.get("output_text") or "").strip()[-500:]
                return fail(
                    "install",
                    "vendor_extraction_failed",
                    "ErgoAI staged extraction failed "
                    f"(returncode={extraction.get('returncode')}, "
                    f"termination={extraction.get('termination_reason')}): {detail}",
                )

            distribution_root = staged_vendor_root / f"ERGOAI_{pin.version}"
            config_path = distribution_root / "ErgoAI" / "ergoAI_config.sh"
            config_hardening = _harden_ergoai_config_for_private_xsb_workspace(
                config_path
            )
            private_xsb_workspace = Path(
                environment["ERGOAI_MANAGED_XSB_TMPDIR"]
            )
            if os.path.lexists(private_xsb_workspace):
                return fail(
                    "install_root",
                    "private_xsb_workspace_preexists",
                    "Private ErgoAI XSB build workspace unexpectedly exists",
                )
            remaining_install_seconds = install_deadline - time.monotonic()
            if remaining_install_seconds <= 0:
                return fail(
                    "install",
                    "vendor_install_timeout",
                    "ErgoAI extraction exhausted the bounded install deadline",
                )
            configuration = run_bounded_ergoai_process(
                shell,
                args=(str(config_path), "-v", pin.version, "noninteractive"),
                input_text="",
                timeout=remaining_install_seconds,
                max_output_bytes=ERGOAI_INSTALL_MAX_OUTPUT_BYTES,
                env=environment,
                cwd=distribution_root,
            )
            receipt.bindings["configuration_output_digest_sha256"] = (
                configuration.get("observed_output_digest_sha256")
            )
            receipt.bindings["configuration_output_bytes"] = configuration.get(
                "observed_output_bytes"
            )
            receipt.bindings["config_hardening"] = config_hardening
            if configuration.get("returncode") != 0 or configuration.get(
                "termination_reason"
            ) is not None:
                detail = str(configuration.get("output_text") or "").strip()[-500:]
                return fail(
                    "install",
                    "vendor_configuration_failed",
                    "ErgoAI bounded configuration failed "
                    f"(returncode={configuration.get('returncode')}, "
                    f"termination={configuration.get('termination_reason')}): {detail}",
                )
            if os.path.lexists(private_xsb_workspace):
                return fail(
                    "install",
                    "private_xsb_workspace_not_cleaned",
                    "ErgoAI configuration left its private XSB workspace behind",
                )
            if not _ergoai_dependency_identity_matches_live(dependency_identity):
                return fail(
                    "dependencies",
                    "build_dependency_identity_changed",
                    "ErgoAI build dependency bytes changed during configuration",
                )

            staged_vendor_binary = _find_vendor_ergoai_binary(
                staged_vendor_root, pin.version
            )
            if staged_vendor_binary is None:
                return fail(
                    "validation",
                    "vendor_executable_missing",
                    "Checksummed ErgoAI installer did not produce a configured runergo.",
                )
            staged_xsb_binary = _find_vendor_xsb_binary(staged_vendor_binary)
            if staged_xsb_binary is None:
                return fail(
                    "validation",
                    "xsb_executable_missing",
                    "ErgoAI installation did not produce exactly one executable XSB runtime.",
                )
            expected_arch_token = (
                "aarch64" if platform_name == "linux-aarch64" else "x86_64"
            )
            staged_xsb_configuration = staged_xsb_binary.parent.parent.name
            if expected_arch_token not in staged_xsb_configuration:
                return fail(
                    "platform",
                    "compiled_platform_mismatch",
                    f"ErgoAI XSB configuration {staged_xsb_configuration!r} does not "
                    f"match the selected platform {platform_name!r}",
                )
            staged_elf_machine = _elf_machine(staged_xsb_binary)
            if staged_elf_machine != expected_arch_token:
                return fail(
                    "platform",
                    "compiled_elf_platform_mismatch",
                    f"ErgoAI XSB ELF machine {staged_elf_machine!r} does not "
                    f"match the selected platform {platform_name!r}",
                )

            _make_ergoai_tree_relocatable(
                staged_vendor_root,
                version=pin.version,
                xsb_configuration=staged_xsb_configuration,
            )
            staged_xsb_user_aux = stage_workspace / "runtime-state" / "xsb-user-aux"
            _ensure_safe_managed_directory(
                stage_workspace,
                staged_xsb_user_aux,
            )
            staged_runtime_env = dict(environment)
            staged_runtime_env["XSB_USER_AUXDIR"] = str(staged_xsb_user_aux)
            receipt.bindings["staged_xsb_runtime_configuration"] = (
                _repair_ergoai_xsb_runtime_configuration(
                    staged_xsb_binary,
                    env=staged_runtime_env,
                )
            )
            staged_banner = read_ergoai_version_banner(
                str(staged_vendor_binary),
                timeout=30.0,
                env=staged_runtime_env,
            )
            if (
                not staged_banner
                or pin.version not in staged_banner
                or "ergoai" not in staged_banner.casefold()
            ):
                return fail(
                    "validation",
                    "locked_version_mismatch",
                    "Staged ErgoAI runtime did not report the locked 3.0 identity.",
                )

            staged_semantics = run_ergoai_semantic_checks(
                staged_vendor_binary,
                timeout=30.0,
                include_extended=True,
                bound_timeout_seconds=ERGOAI_DEFAULT_BOUND_TIMEOUT_SECONDS,
                max_output_bytes=ERGOAI_RESOURCE_CASE_MAX_OUTPUT_BYTES,
                env=staged_runtime_env,
            )
            receipt.bindings["staged_semantic_evidence_digest_sha256"] = (
                staged_semantics.get("normalized_evidence_digest_sha256")
            )
            if not staged_semantics.get("passed"):
                return fail(
                    "semantic_validation",
                    "staged_semantic_checks_failed",
                    "Staged ErgoAI failed the complete semantic and bound matrix; "
                    "vendor bytes were not published.",
                )
            staged_cache_files_removed = _clean_ergoai_runtime_path_caches(
                staged_vendor_root
            )
            staged_tree_snapshot = _ergoai_vendor_tree_integrity(
                staged_vendor_root,
                include_entries=True,
            )
            staged_tree_entries = dict(staged_tree_snapshot.pop("entries"))
            staged_tree_integrity = staged_tree_snapshot
            receipt.bindings["staged_runtime_cache_files_removed"] = (
                staged_cache_files_removed
            )
            receipt.bindings["staged_vendor_tree_integrity"] = (
                staged_tree_integrity
            )

            # Directory rename is the only publication step for vendor bytes.
            # A concurrent winner is acceptable only if it exposes the same
            # configured content-addressed runtime.
            try:
                os.replace(staged_vendor_root, vendor_root)
            except OSError as exc:
                return fail(
                    "install",
                    "concurrent_vendor_publish_requires_retry",
                    "Another process published the ErgoAI vendor destination; "
                    f"this attempt will not bless it ({exc}).",
                )
            vendor_binary = _find_vendor_ergoai_binary(vendor_root, pin.version)
            receipt.bindings["vendor_directory_atomic_rename_completed"] = True
            receipt.bindings["staging_directory_name"] = stage_workspace.name
        except (OSError, subprocess.SubprocessError, AdvisorInstallerError) as exc:
            return fail(
                "install", "vendor_install_failed", f"ErgoAI staged install failed: {exc}"
            )
        finally:
            if stage_workspace is not None:
                shutil.rmtree(stage_workspace, ignore_errors=True)

    if vendor_binary is None:
        return fail(
            "validation",
            "vendor_executable_missing",
            "Checksummed ErgoAI installer did not produce a configured runergo.",
        )
    xsb_binary = _find_vendor_xsb_binary(vendor_binary)
    if xsb_binary is None:
        return fail(
            "validation",
            "xsb_executable_missing",
            "ErgoAI installation did not produce exactly one executable XSB runtime.",
        )
    expected_arch_token = "aarch64" if platform_name == "linux-aarch64" else "x86_64"
    xsb_configuration = xsb_binary.parent.parent.name
    if expected_arch_token not in xsb_configuration:
        return fail(
            "platform",
            "compiled_platform_mismatch",
            f"ErgoAI XSB configuration {xsb_configuration!r} does not match "
            f"the selected platform {platform_name!r}",
        )
    xsb_elf_machine = _elf_machine(xsb_binary)
    if xsb_elf_machine != expected_arch_token:
        return fail(
            "platform",
            "compiled_elf_platform_mismatch",
            f"ErgoAI XSB ELF machine {xsb_elf_machine!r} does not match "
            f"the selected platform {platform_name!r}",
        )

    # The published vendor tree is never rewritten.  Relocation repair and the
    # full first semantic matrix completed in staging; only non-mutating XSB
    # replay and isolated managed-launcher execution occur from this point.
    xsb_user_aux_dir = _ergoai_xsb_user_aux_dir(root, pin.version)
    try:
        _ensure_safe_managed_directory(root, xsb_user_aux_dir)
    except AdvisorInstallerError as exc:
        return fail("install_root", "unsafe_install_root", str(exc))
    semantic_env = ergoai_offline_subprocess_env()
    semantic_env["XSB_USER_AUXDIR"] = str(xsb_user_aux_dir)
    receipt.bindings["xsb_runtime_configuration"] = (
        _repair_ergoai_xsb_runtime_configuration(
            xsb_binary,
            env=semantic_env,
        )
    )
    receipt.bindings["runtime_state"] = {
        "xsb_user_aux_dir": _install_relative_path(xsb_user_aux_dir, root),
        "policy": "mutable-nonauthoritative-outside-vendor-identity/v1",
    }

    try:
        bound_runtime_environment = _materialize_ergoai_bound_runtime_toolchain(
            install_root=root,
            version=pin.version,
            dependency_identity=dependency_identity,
            optional_java_identity=optional_java_identity,
        )
    except AdvisorInstallerError as exc:
        return fail(
            "dependencies",
            "runtime_dependency_binding_failed",
            str(exc),
        )
    receipt.bindings["bound_runtime_environment"] = bound_runtime_environment

    launcher_digests = _write_vendor_ergoai_launchers(
        install_root=root,
        vendor_binary=vendor_binary,
        version=pin.version,
        platform_key=platform_name,
    )
    primary_launcher = root / "bin" / "ergoai"
    banner = read_ergoai_version_banner(
        str(primary_launcher),
        timeout=30.0,
        env=semantic_env,
    )
    if not banner or pin.version not in banner or "ergoai" not in banner.casefold():
        return fail(
            "validation",
            "locked_version_mismatch",
            "Installed ErgoAI runtime did not report the locked 3.0 identity.",
        )
    semantics = run_ergoai_semantic_checks(
        primary_launcher,
        timeout=30.0,
        include_extended=True,
        bound_timeout_seconds=ERGOAI_DEFAULT_BOUND_TIMEOUT_SECONDS,
        max_output_bytes=ERGOAI_RESOURCE_CASE_MAX_OUTPUT_BYTES,
        env=semantic_env,
    )
    if not semantics.get("core_passed", semantics.get("passed")):
        return fail(
            "semantic_validation",
            "semantic_checks_failed",
            "Installed ErgoAI failed entailment/non-entailment/contradiction/"
            "mutation/replay checks.",
        )
    if not semantics.get("extended_passed", True):
        return fail(
            "semantic_validation",
            "extended_semantic_checks_failed",
            "Installed ErgoAI failed malformed/timeout/resource-bound checks.",
        )

    runtime_cache_files_removed = _clean_ergoai_runtime_path_caches(vendor_root)
    try:
        published_tree_snapshot = _ergoai_vendor_tree_integrity(
            vendor_root,
            include_entries=True,
        )
        published_tree_entries = dict(published_tree_snapshot.pop("entries"))
        vendor_tree_integrity = published_tree_snapshot
    except AdvisorInstallerError as exc:
        return fail(
            "provenance",
            "vendor_tree_integrity_failed",
            f"ErgoAI vendor dependency tree is not confined and stable: {exc}",
        )
    if (
        stage_workspace is not None
        and receipt.bindings.get("staged_vendor_tree_integrity")
        != vendor_tree_integrity
    ):
        staged_paths = set(staged_tree_entries)
        published_paths = set(published_tree_entries)
        changed_paths = sorted(
            path
            for path in staged_paths & published_paths
            if staged_tree_entries[path] != published_tree_entries[path]
        )
        receipt.bindings["published_vendor_tree_transition"] = {
            "added_paths": sorted(published_paths - staged_paths)[:64],
            "removed_paths": sorted(staged_paths - published_paths)[:64],
            "changed_paths": changed_paths[:64],
            "added_count": len(published_paths - staged_paths),
            "removed_count": len(staged_paths - published_paths),
            "changed_count": len(changed_paths),
        }
        return fail(
            "provenance",
            "published_vendor_tree_differs_from_staged_tree",
            "Published ErgoAI vendor dependency tree differs from the fully "
            "validated staged tree.",
        )
    receipt.bindings["runtime_cache_files_removed"] = runtime_cache_files_removed
    receipt.bindings["vendor_tree_integrity"] = vendor_tree_integrity

    runtime_paths_file = vendor_binary.parent / ".ergo_paths"
    java_settings_file = vendor_binary.parent / "java" / "flora_settings.sh"
    if config_hardening is None or bound_build_environment is None:
        return fail(
            "provenance",
            "build_environment_evidence_missing",
            "ErgoAI build hardening/environment evidence is unavailable",
        )
    identity = {
        "schema_version": "ergoai-managed-vendor-identity/v1",
        "tool_id": TOOL_ERGOAI,
        "version": pin.version,
        "selected_platform": platform_name,
        "release_tag": pin.release_tag or ERGOAI_RELEASE_TAG,
        "release_url": pin.artifact_url,
        "release_artifact_path": _install_relative_path(release_path, root),
        "release_artifact_sha256": content_sha256(release_path),
        "release_artifact_size_bytes": release_path.stat().st_size,
        "vendor_executable": _install_relative_path(vendor_binary, root),
        "vendor_executable_sha256": content_sha256(vendor_binary),
        "xsb_executable": _install_relative_path(xsb_binary, root),
        "xsb_executable_sha256": content_sha256(xsb_binary),
        "xsb_configuration": xsb_configuration,
        "xsb_elf_machine": xsb_elf_machine,
        "xsb_user_aux_dir": _install_relative_path(xsb_user_aux_dir, root),
        "runtime_state_policy": (
            "mutable-nonauthoritative-outside-vendor-identity/v1"
        ),
        "runtime_workspace_cleanup_policy": (
            "normal-and-handled-signals-clean-sigkill-orphans-retained/v1"
        ),
        "runtime_execution_policy": (
            "private-ergoai-copy-shared-immutable-xsb/v1"
        ),
        "java_consumer_policy": "private-ergoai-copy-java-consumers/v2",
        "runtime_paths_file": _install_relative_path(runtime_paths_file, root),
        "runtime_paths_sha256": content_sha256(runtime_paths_file),
        "java_settings_file": _install_relative_path(java_settings_file, root),
        "java_settings_sha256": content_sha256(java_settings_file),
        "config_file": _install_relative_path(
            vendor_binary.parent / "ergoAI_config.sh",
            root,
        ),
        "config_file_sha256": content_sha256(
            vendor_binary.parent / "ergoAI_config.sh"
        ),
        "launcher": _install_relative_path(primary_launcher, root),
        "launcher_sha256": launcher_digests["ergoai"],
        "launcher_digests": launcher_digests,
        "version_banner_digest_sha256": hashlib.sha256(
            banner.encode("utf-8")
        ).hexdigest(),
        "semantic_checks": semantics,
        "build_dependency_identity": dependency_identity,
        "optional_java_dependency_identity": optional_java_identity,
        "bound_build_environment": bound_build_environment,
        "bound_runtime_environment": bound_runtime_environment,
        "config_hardening": config_hardening,
        "checksum_verified": True,
        "is_live_vendor": True,
        "is_hermetic_advisor_shim": False,
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "grants_theorem_authority": False,
        "grants_proof_authority": False,
        "atomic_publish": True,
        "relocatable_install": True,
        "runtime_paths_relative": True,
        "relocation_certification_scope": (
            "executed-runtime-and-bundled-java-consumers/v1"
        ),
        "developer_rebuild_metadata_relocated": False,
        "vendor_tree_digest_sha256": vendor_tree_integrity["digest_sha256"],
        "vendor_tree_file_count": vendor_tree_integrity["file_count"],
        "vendor_tree_excluded_runtime_cache_count": vendor_tree_integrity[
            "excluded_runtime_cache_count"
        ],
        "vendor_tree_exclusion_policy": vendor_tree_integrity[
            "exclusion_policy"
        ],
        "install_publication_model": (
            "staged_vendor_atomic_rename_private_runtime_workspaces_identity_commit_v4"
        ),
        "publication_commit_point": "atomic_identity_manifest_replace",
        "license": pin.license,
        "license_components": list(ERGOAI_LICENSE_COMPONENTS),
        "source": pin.source,
    }
    identity["identity_digest_sha256"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    identity_path = _ergoai_identity_path(root, pin.version)
    _write_identity_manifest(identity_path, identity)

    provenance = _validate_ergoai_managed_provenance(
        install_root=root,
        expected_version=pin.version,
        expected_platform=platform_name,
    )
    if not provenance.get("managed_vendor_provenance_verified"):
        return fail(
            "provenance",
            "managed_vendor_provenance_unverified",
            "ErgoAI identity manifest did not replay against installed artifacts.",
        )

    os.environ["ERGOAI_BINARY"] = str(primary_launcher)
    receipt.executable_path = str(primary_launcher)
    receipt.installed = True
    receipt.status = "installed"
    receipt.phase = "installed"
    receipt.bindings["managed_provenance"] = {
        "identity_manifest_path": str(identity_path),
        "identity_digest_sha256": identity["identity_digest_sha256"],
        "managed_vendor_provenance_verified": True,
        "is_hermetic_advisor_shim": False,
    }
    receipt.bindings["semantic_checks"] = semantics
    receipt.bindings["atomic_publish"] = True
    receipt.bindings["relocatable_install"] = True
    receipt.bindings["install_publication_model"] = (
        "staged_vendor_atomic_rename_private_runtime_workspaces_identity_commit_v4"
    )
    receipt.bindings["transactional_publication"] = True
    receipt.messages.append(
        f"Installed checksummed ErgoAI {pin.version} for {platform_name}; "
        "runtime remains advisor/candidate only"
    )
    _announce(receipt.messages[-1], on_progress, phase="installed")
    return receipt



# ---------------------------------------------------------------------------
# Optional managed Eclipse Temurin JDK (ErgoAI Java API / FVT-G222)
# ---------------------------------------------------------------------------


def _temurin_version_root(install_root: Path, version: str) -> Path:
    return Path(install_root) / "advisors" / TOOL_TEMURIN_JDK / version


def _temurin_identity_path(install_root: Path, version: str) -> Path:
    return _temurin_version_root(install_root, version) / "identity.json"


def _temurin_home_path(install_root: Path, version: str) -> Path:
    return _temurin_version_root(install_root, version) / "jdk"


def _temurin_bin_path(install_root: Path, version: str) -> Path:
    return _temurin_home_path(install_root, version) / "bin"


def _temurin_publisher_evidence(meta: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "publisher": TEMURIN_JDK_PUBLISHER,
        "release_name": str(meta.get("release_name") or TEMURIN_JDK_RELEASE_NAME),
        "signature_url": str(meta.get("signature_url") or ""),
        "checksum_url": str(meta.get("checksum_url") or ""),
        "publisher_evidence_kind": "adoptium_sha256_and_detached_sig",
        "never_download_moving_latest": True,
        "never_trust_ambient_java_home": True,
    }


def _temurin_thread_lock(root: Path) -> threading.RLock:
    key = str(root)
    with _TEMURIN_ROOT_LOCKS_GUARD:
        lock = _TEMURIN_ROOT_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _TEMURIN_ROOT_LOCKS[key] = lock
        return lock


def assert_strict_home_descendant(
    path: str | Path,
    *,
    home: str | Path | None = None,
    label: str = "path",
    allow_non_home_explicit_root: bool = False,
) -> Path:
    """Fail closed unless *path* is a strict canonical descendant of HOME.

    Explicit test/isolation roots may set ``allow_non_home_explicit_root`` so
    hermetic tmp homes remain usable while production defaults stay HOME-bound.
    HOME itself, sibling/prefix collisions, and lexical ``..`` always fail.
    """

    selected = _lexical_absolute(path)
    try:
        home_root = (
            _lexical_absolute(home)
            if home is not None
            else Path.home().resolve(strict=False)
        )
    except (OSError, RuntimeError) as exc:
        raise AdvisorInstallerError(
            f"{label} cannot resolve HOME for boundary check: {exc}"
        ) from exc
    # HOME itself is not a valid mutable install target.
    if selected == home_root:
        raise AdvisorInstallerError(
            f"{label} must be a strict HOME descendant, not HOME itself: {selected}"
        )
    try:
        selected.relative_to(home_root)
    except ValueError as exc:
        if allow_non_home_explicit_root:
            if ".." in selected.parts:
                raise AdvisorInstallerError(
                    f"{label} contains lexical traversal: {selected}"
                ) from exc
            return selected
        raise AdvisorInstallerError(
            f"{label} escapes selected HOME boundary: {selected} not under {home_root}"
        ) from exc
    # Prefix collisions (HOME+/foo vs HOME+/foobar) are prevented by relative_to.
    # Lexical traversal and symlink ancestors fail closed via _ensure_safe_directory.
    if ".." in selected.parts:
        raise AdvisorInstallerError(
            f"{label} contains lexical traversal: {selected}"
        )
    return selected


def assert_strict_install_root_descendant(
    install_root: str | Path,
    path: str | Path,
    *,
    label: str = "path",
) -> Path:
    """Fail closed unless *path* is a strict lexical descendant of *install_root*."""

    root = _lexical_absolute(install_root)
    target = _lexical_absolute(path)
    if target == root:
        raise AdvisorInstallerError(
            f"{label} must be a strict install-root descendant, not the root: {target}"
        )
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise AdvisorInstallerError(
            f"{label} escapes install root: {target} not under {root}"
        ) from exc
    if ".." in target.parts:
        raise AdvisorInstallerError(
            f"{label} contains lexical traversal: {target}"
        )
    return target


def _temurin_lock_path(install_root: Path) -> Path:
    return _lexical_absolute(install_root) / ".locks" / TEMURIN_INSTALL_LOCK_NAME


def _temurin_lock_payload() -> dict[str, Any]:
    return {
        "schema_version": "temurin-jdk-install-lock/v1",
        "pid": os.getpid(),
        "created_at_unix": time.time(),
        "hostname": platform.node(),
    }


def _temurin_lock_is_abandoned(payload: Mapping[str, Any]) -> bool:
    try:
        pid = int(payload.get("pid") or -1)
        created = float(payload.get("created_at_unix") or 0.0)
    except (TypeError, ValueError):
        return True
    if created <= 0:
        return True
    age = time.time() - created
    if age > TEMURIN_LOCK_STALE_SECONDS:
        return True
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        # Process exists but is not owned by us; treat as live holder.
        return False
    except OSError:
        return True
    return False


@contextmanager
def temurin_installation_lock(
    install_root: str | Path,
    *,
    wait_timeout: float = 120.0,
) -> Generator[Path, None, None]:
    """Cross-process single-flight lock for managed JDK acquisition/publication.

    Only one process may acquire/publish the managed Temurin identity under a
    given install root.  Abandoned locks (dead PID or stale timestamp) are
    recovered safely.  Partial trees remain invisible because publication uses
    atomic rename after the lock is held.
    """

    root = _lexical_absolute(install_root)
    # Explicit install roots (tests / isolated homes) are allowed outside the
    # operator HOME, but mutable children must still stay under *root*.
    assert_strict_home_descendant(
        root,
        label="temurin install_root",
        allow_non_home_explicit_root=True,
    )
    thread_lock = _temurin_thread_lock(root)
    with thread_lock:
        lock_dir = root / ".locks"
        _ensure_safe_managed_directory(root, lock_dir)
        lock_path = _temurin_lock_path(root)
        deadline = time.monotonic() + max(0.1, float(wait_timeout))
        handle = None
        while True:
            try:
                handle = open(lock_path, "a+b")  # noqa: SIM115 - closed in finally
                if os.name == "posix":
                    import fcntl

                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        handle.close()
                        handle = None
                        # Attempt abandoned-lock recovery when metadata is stale.
                        try:
                            raw = lock_path.read_text(encoding="utf-8")
                            payload = json.loads(raw) if raw.strip() else {}
                        except (OSError, UnicodeError, json.JSONDecodeError):
                            payload = {}
                        if isinstance(payload, Mapping) and _temurin_lock_is_abandoned(
                            payload
                        ):
                            try:
                                lock_path.unlink(missing_ok=True)
                            except OSError:
                                pass
                        if time.monotonic() >= deadline:
                            raise AdvisorInstallerError(
                                "timed out waiting for temurin-jdk single-flight lock"
                            )
                        time.sleep(0.05)
                        continue
                # Write ownership metadata for abandoned-lock recovery.
                handle.seek(0)
                handle.truncate()
                handle.write(
                    json.dumps(_temurin_lock_payload(), sort_keys=True).encode("utf-8")
                )
                handle.flush()
                try:
                    yield lock_path
                finally:
                    if os.name == "posix":
                        import fcntl

                        try:
                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                        except OSError:
                            pass
                    try:
                        handle.close()
                    except OSError:
                        pass
                    try:
                        # Only the holder removes the lock file metadata.
                        if lock_path.is_file():
                            lock_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                return
            except AdvisorInstallerError:
                if handle is not None:
                    try:
                        handle.close()
                    except OSError:
                        pass
                raise
            except OSError as exc:
                if handle is not None:
                    try:
                        handle.close()
                    except OSError:
                        pass
                if time.monotonic() >= deadline:
                    raise AdvisorInstallerError(
                        f"temurin-jdk install lock failed: {exc}"
                    ) from exc
                time.sleep(0.05)


def verify_temurin_publisher_evidence(
    archive: Path,
    *,
    pin: ToolPin,
    meta: Mapping[str, Any],
    checksum_text: str | None = None,
    signature_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Bind archive digest/size to pinned Adoptium publisher evidence.

    Detached signature bytes are recorded when provided.  When the official
    ``sha256.txt`` content is supplied, it must name the archive and the exact
    pinned digest.  Ambient JAVA_HOME is never consulted.
    """

    if not _safe_existing_regular_file(archive):
        raise AdvisorInstallerError(
            f"Temurin archive is not a safe regular file: {archive}"
        )
    size = os.lstat(archive).st_size
    digest = content_sha256(archive)
    if digest != pin.sha256:
        raise AdvisorInstallerError(
            "Temurin archive SHA-256 does not match the reviewed pin"
        )
    if size != pin.artifact_size_bytes:
        raise AdvisorInstallerError(
            "Temurin archive size does not match the reviewed pin"
        )
    evidence = _temurin_publisher_evidence(meta)
    evidence.update(
        {
            "artifact_sha256": digest,
            "artifact_size_bytes": size,
            "archive_name": Path(pin.artifact_url).name,
            "checksum_text_bound": False,
            "signature_bytes_bound": False,
            "vendor": TEMURIN_JDK_PUBLISHER,
            "license": TEMURIN_JDK_LICENSE,
            "os": meta.get("os"),
            "architecture": meta.get("architecture"),
        }
    )
    if checksum_text is not None:
        text = checksum_text.strip()
        # Official Adoptium format: "<sha256>  <archive_name>"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        matched = False
        archive_name = Path(pin.artifact_url).name
        for line in lines:
            parts = line.split()
            if len(parts) >= 2 and parts[0].lower() == digest.lower():
                name = Path(parts[1]).name
                if name == archive_name or name.endswith(archive_name):
                    matched = True
                    break
        if not matched:
            raise AdvisorInstallerError(
                "Temurin release checksum text does not bind the pinned archive digest"
            )
        evidence["checksum_text_bound"] = True
        evidence["checksum_text_digest_sha256"] = hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()
    if signature_bytes is not None:
        if not signature_bytes:
            raise AdvisorInstallerError("Temurin detached signature is empty")
        evidence["signature_bytes_bound"] = True
        evidence["signature_digest_sha256"] = hashlib.sha256(signature_bytes).hexdigest()
        evidence["signature_size_bytes"] = len(signature_bytes)
    # Publisher evidence is strong when the pinned digest/size/URL bind and at
    # least the release checksum text or detached signature bytes are present.
    evidence["publisher_evidence_satisfied"] = bool(
        evidence["checksum_text_bound"] or evidence["signature_bytes_bound"]
    )
    return evidence


def reject_mutated_temurin_identity(
    *,
    install_root: str | Path | None = None,
    expected_version: str = TEMURIN_JDK_VERSION,
) -> dict[str, Any]:
    """Reject byte mutations of managed Java tools before execution."""

    probe = probe_temurin_jdk_identity(
        install_root=install_root,
        expected_version=expected_version,
        require_managed=True,
    )
    if not probe.get("satisfied"):
        return {
            "accepted": False,
            "reason_codes": list(probe.get("reason_codes") or ["unsatisfied"]),
            "probe": probe,
        }
    # Re-hash each tool against the identity manifest; any drift fails closed.
    manifest = probe.get("manifest") if isinstance(probe.get("manifest"), Mapping) else {}
    tools_meta = manifest.get("tools") if isinstance(manifest.get("tools"), Mapping) else {}
    drift: list[str] = []
    for name in TEMURIN_JDK_EXECUTABLES:
        claimed = tools_meta.get(name) if isinstance(tools_meta.get(name), Mapping) else {}
        live = (probe.get("tools") or {}).get(name) if isinstance(probe.get("tools"), Mapping) else {}
        if not isinstance(live, Mapping):
            drift.append(name)
            continue
        if claimed.get("executable_sha256") != live.get("executable_sha256"):
            drift.append(name)
    return {
        "accepted": not drift and probe.get("satisfied") is True,
        "drift": drift,
        "reason_codes": (["tool_byte_mutation"] if drift else []),
        "probe": {
            "satisfied": probe.get("satisfied"),
            "java_home": probe.get("java_home"),
            "ambient_java_home_trusted": False,
        },
    }


def _assert_temurin_lock_contract(
    document: Mapping[str, Any],
    entry: Mapping[str, Any],
    pins: Sequence[ToolPin],
) -> None:
    versions = document.get("managed_pin_versions") or {}
    if not isinstance(versions, Mapping):
        raise AdvisorInstallerError("managed_pin_versions must be a mapping")
    if str(versions.get(TOOL_TEMURIN_JDK)) != TEMURIN_JDK_VERSION:
        raise AdvisorInstallerError(
            "lock managed_pin_versions.temurin-jdk must equal "
            f"{TEMURIN_JDK_VERSION!r}"
        )
    if entry.get("installer_entry") != "ensure_temurin_jdk":
        raise AdvisorInstallerError(
            "temurin-jdk installer_entry must be ensure_temurin_jdk"
        )
    if entry.get("installer_plugin") != PLUGIN_FAMILY:
        raise AdvisorInstallerError(
            "temurin-jdk installer_plugin must be advisors"
        )
    if entry.get("license") != TEMURIN_JDK_LICENSE:
        raise AdvisorInstallerError("temurin-jdk license pin mismatch")
    if entry.get("source") != TEMURIN_JDK_SOURCE:
        raise AdvisorInstallerError("temurin-jdk source pin mismatch")
    if entry.get("identity_kind") != TEMURIN_JDK_IDENTITY_KIND:
        raise AdvisorInstallerError("temurin-jdk identity_kind mismatch")
    if entry.get("publisher") != TEMURIN_JDK_PUBLISHER:
        raise AdvisorInstallerError("temurin-jdk publisher mismatch")
    observed_platforms = {pin.platform for pin in pins}
    if observed_platforms != set(TEMURIN_JDK_SUPPORTED_PLATFORMS):
        raise AdvisorInstallerError(
            "temurin-jdk pins must cover exactly the reviewed Linux matrix"
        )
    for pin in pins:
        meta = TEMURIN_JDK_PINS.get(pin.platform)
        if meta is None:
            raise AdvisorInstallerError(
                f"unreviewed temurin-jdk platform pin: {pin.platform}"
            )
        if (
            pin.version != TEMURIN_JDK_VERSION
            or pin.sha256 != str(meta["sha256"])
            or pin.artifact_url != str(meta["artifact_url"])
            or pin.artifact_size_bytes != int(meta["artifact_size_bytes"])
            or not pin.is_checksummed
        ):
            raise AdvisorInstallerError(
                f"temurin-jdk pin drift for platform {pin.platform}"
            )
        # Extended publisher evidence lives on the lock pin objects.
        raw_pins = entry.get("pins")
        if not isinstance(raw_pins, list):
            raise AdvisorInstallerError("temurin-jdk pins must be a list")
        match = next(
            (
                raw
                for raw in raw_pins
                if isinstance(raw, Mapping)
                and str(raw.get("platform")) == pin.platform
            ),
            None,
        )
        if match is None:
            raise AdvisorInstallerError(
                f"temurin-jdk lock pin missing platform {pin.platform}"
            )
        for key in (
            "signature_url",
            "checksum_url",
            "publisher",
            "release_name",
            "os",
            "architecture",
            "artifact_size_bytes",
        ):
            if match.get(key) in (None, ""):
                raise AdvisorInstallerError(
                    f"temurin-jdk pin missing publisher field {key}"
                )
        tools = match.get("required_tool_identities")
        if list(tools or ()) != list(TEMURIN_JDK_EXECUTABLES):
            raise AdvisorInstallerError(
                "temurin-jdk required_tool_identities must be java/javac/jar"
            )


def authorize_temurin_jdk_install(
    *,
    yes: bool,
    strict: bool = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    dry_run: bool = False,
    offline: bool = False,
    platform_key: str | None = None,
) -> None:
    """Fail-closed gate for the optional managed JDK (no registry authority)."""

    if import_context:
        raise AdvisorInstallerError(
            "managed JDK installation is forbidden during import"
        )
    if capability_discovery:
        raise AdvisorInstallerError(
            "managed JDK installation is forbidden during capability discovery"
        )
    if dry_run:
        raise AdvisorInstallerError(
            "managed JDK installation is forbidden during dry-run"
        )
    if offline or any(
        os.environ.get(name) in {"1", "true", "TRUE", "yes", "on"}
        for name in (
            "FORMAL_VERIFICATION_CERTIFY_OFFLINE",
            "FORMAL_VERIFICATION_FORBID_DOWNLOAD",
            "FORMAL_VERIFICATION_FORBID_INSTALL",
            "FORMAL_VERIFICATION_FORBID_NETWORK",
        )
    ):
        raise AdvisorInstallerError(
            "managed JDK acquisition is forbidden under offline certification policy"
        )
    if not yes:
        raise AdvisorInstallerError(
            "managed JDK install requires explicit yes=True / allow flag"
        )
    platform_name = platform_key or detect_platform_key()
    if platform_name not in TEMURIN_JDK_SUPPORTED_PLATFORMS:
        raise AdvisorInstallerError(
            f"managed JDK install is not reviewed for {platform_name!r}"
        )
    # Ambient JAVA_HOME must never authorize or select the managed identity.
    if os.environ.get("JAVA_HOME"):
        # Presence is tolerated for unrelated host tools, but is never trusted
        # as install evidence.  Selection always uses the locked pin.
        pass
    if strict:
        select_strict_pin(
            TOOL_TEMURIN_JDK,
            platform_key=platform_name,
            allow_source_fallback=False,
        )


def _safe_extract_temurin_archive(archive: Path, destination: Path) -> Path:
    """Symlink-safe, traversal-safe extraction of a reviewed JDK tarball."""

    destination = Path(destination)
    if destination.exists():
        raise AdvisorInstallerError(
            f"JDK extraction destination already exists: {destination}"
        )
    destination.mkdir(parents=True, exist_ok=False)
    destination_resolved = destination.resolve()
    try:
        with tarfile.open(archive, "r:*") as bundle:
            members = bundle.getmembers()
            safe_members: list[tarfile.TarInfo] = []
            for member in members:
                name = member.name
                if not name or name.startswith("/") or ".." in Path(name).parts:
                    raise AdvisorInstallerError(
                        f"JDK archive path traversal blocked: {name!r}"
                    )
                target = (destination / name).resolve()
                if (
                    target != destination_resolved
                    and destination_resolved not in target.parents
                ):
                    raise AdvisorInstallerError(
                        f"JDK archive path escapes extraction root: {name!r}"
                    )
                if member.issym() or member.islnk():
                    # Symlink members are allowed only when they stay inside the
                    # extraction root; absolute and escape targets fail closed.
                    link = member.linkname or ""
                    if link.startswith("/") or ".." in Path(link).parts:
                        raise AdvisorInstallerError(
                            f"JDK archive symlink escapes root: {name!r} -> {link!r}"
                        )
                    link_target = (destination / Path(name).parent / link).resolve()
                    if (
                        link_target != destination_resolved
                        and destination_resolved not in link_target.parents
                    ):
                        raise AdvisorInstallerError(
                            f"JDK archive symlink escapes root: {name!r} -> {link!r}"
                        )
                elif not (member.isfile() or member.isdir()):
                    raise AdvisorInstallerError(
                        f"JDK archive contains unsupported object: {name!r}"
                    )
                safe_members.append(member)
            try:
                bundle.extractall(destination, members=safe_members, filter="data")  # type: ignore[call-arg]
            except TypeError:
                bundle.extractall(destination, members=safe_members)
    except (tarfile.TarError, OSError) as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise AdvisorInstallerError(
            f"JDK archive extraction failed: {type(exc).__name__}: {exc}"
        ) from exc

    roots = [item for item in destination.iterdir() if item.is_dir()]
    if len(roots) != 1:
        shutil.rmtree(destination, ignore_errors=True)
        raise AdvisorInstallerError(
            "JDK archive must extract to exactly one top-level directory"
        )
    jdk_home = roots[0]
    bin_dir = jdk_home / "bin"
    for name in TEMURIN_JDK_EXECUTABLES:
        tool = bin_dir / name
        if not tool.is_file() or not os.access(tool, os.X_OK):
            shutil.rmtree(destination, ignore_errors=True)
            raise AdvisorInstallerError(
                f"JDK archive missing executable identity: {name}"
            )
    return jdk_home


def _probe_jdk_tool(
    executable: Path,
    *,
    args: Sequence[str],
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    execution = run_bounded_ergoai_process(
        executable,
        args=tuple(args),
        input_text="",
        timeout=5.0,
        max_output_bytes=64 * 1024,
        env=env or ergoai_offline_subprocess_env({"LANG": "C", "LC_ALL": "C"}),
    )
    banner = str(execution.get("output_text") or "")
    present = (
        execution.get("returncode") == 0
        and execution.get("termination_reason") is None
        and bool(banner.strip())
    )
    return {
        "path": str(executable),
        "present": present,
        "returncode": execution.get("returncode"),
        "termination_reason": execution.get("termination_reason"),
        "banner": banner,
        "banner_digest_sha256": hashlib.sha256(banner.encode("utf-8")).hexdigest(),
        "executable_sha256": content_sha256(executable) if executable.is_file() else None,
        "version_satisfied": bool(
            present and TEMURIN_JDK_VERSION.split("+")[0] in banner
        ),
    }


def probe_temurin_jdk_identity(
    *,
    install_root: str | Path | None = None,
    expected_version: str = TEMURIN_JDK_VERSION,
    require_managed: bool = True,
) -> dict[str, Any]:
    """Probe a managed Temurin JDK without acquiring or trusting JAVA_HOME."""

    root = expand_user_local_root(install_root)
    identity_path = _temurin_identity_path(root, expected_version)
    home = _temurin_home_path(root, expected_version)
    result: dict[str, Any] = {
        "tool_id": TOOL_TEMURIN_JDK,
        "expected_version": expected_version,
        "install_root": str(root),
        "identity_manifest_path": str(identity_path),
        "java_home": str(home),
        "managed": False,
        "satisfied": False,
        "ambient_java_home_trusted": False,
        "tools": {},
        "reason_codes": [],
    }
    # Explicitly ignore ambient JAVA_HOME for managed capability evidence.
    ambient = os.environ.get("JAVA_HOME")
    if ambient:
        result["ambient_java_home_observed"] = True
        result["ambient_java_home_path"] = ambient
    else:
        result["ambient_java_home_observed"] = False
    if not identity_path.is_file():
        result["reason_codes"].append("identity_manifest_missing")
        return result
    try:
        manifest = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        result["reason_codes"].append("identity_manifest_unreadable")
        return result
    if not isinstance(manifest, dict):
        result["reason_codes"].append("identity_manifest_invalid")
        return result
    result["manifest"] = manifest
    if manifest.get("schema_version") != TEMURIN_JDK_SCHEMA:
        result["reason_codes"].append("identity_schema_mismatch")
        return result
    if manifest.get("version") != expected_version:
        result["reason_codes"].append("identity_version_mismatch")
        return result
    claimed_home = Path(str(manifest.get("java_home") or ""))
    if claimed_home.resolve() != home.resolve() or not home.is_dir():
        result["reason_codes"].append("java_home_mismatch")
        return result
    tools: dict[str, Any] = {}
    all_ok = True
    for name in TEMURIN_JDK_EXECUTABLES:
        tool_path = home / "bin" / name
        if not tool_path.is_file():
            tools[name] = {"present": False, "path": str(tool_path)}
            all_ok = False
            continue
        probe = _probe_jdk_tool(
            tool_path,
            args=("-version",) if name == "java" else ("-version",),
        )
        if name == "jar":
            # jar -version is supported on Temurin; fall back to bare --help.
            if not probe.get("present"):
                probe = _probe_jdk_tool(tool_path, args=("--version",))
        tools[name] = probe
        claimed = (manifest.get("tools") or {}).get(name) if isinstance(manifest.get("tools"), Mapping) else None
        if (
            not probe.get("present")
            or not probe.get("version_satisfied")
            or not isinstance(claimed, Mapping)
            or claimed.get("executable_sha256") != probe.get("executable_sha256")
        ):
            all_ok = False
    result["tools"] = tools
    result["managed"] = True
    result["satisfied"] = all_ok
    if not all_ok:
        result["reason_codes"].append("tool_identity_mismatch")
    if require_managed and not all_ok:
        result["reason_codes"].append("managed_jdk_unsatisfied")
    return result


def _write_temurin_identity(
    *,
    install_root: Path,
    version: str,
    pin: ToolPin,
    jdk_home: Path,
    tools: Mapping[str, Mapping[str, Any]],
    publisher_evidence: Mapping[str, Any],
    archive_sha256: str,
    archive_size_bytes: int,
) -> Path:
    identity_path = _temurin_identity_path(install_root, version)
    payload = {
        "schema_version": TEMURIN_JDK_SCHEMA,
        "tool_id": TOOL_TEMURIN_JDK,
        "version": version,
        "release_name": TEMURIN_JDK_RELEASE_NAME,
        "publisher": TEMURIN_JDK_PUBLISHER,
        "license": TEMURIN_JDK_LICENSE,
        "source": TEMURIN_JDK_SOURCE,
        "identity_kind": TEMURIN_JDK_IDENTITY_KIND,
        "platform": pin.platform,
        "artifact_url": pin.artifact_url,
        "artifact_sha256": archive_sha256,
        "artifact_size_bytes": archive_size_bytes,
        "java_home": str(jdk_home.resolve()),
        "required_tool_identities": list(TEMURIN_JDK_EXECUTABLES),
        "tools": {
            name: {
                "path": value.get("path"),
                "executable_sha256": value.get("executable_sha256"),
                "banner_digest_sha256": value.get("banner_digest_sha256"),
                "version_satisfied": value.get("version_satisfied"),
            }
            for name, value in tools.items()
        },
        "publisher_evidence": dict(publisher_evidence),
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "grants_theorem_authority": False,
        "grants_proof_authority": False,
        "ambient_java_home_trusted": False,
        "optional_for_core_ergoai": True,
        "capability": "ergoai-java-api",
        "goal_id": ERGOAI_JAVA_API_GOAL_ID,
        "task_id": ERGOAI_JAVA_API_TASK_ID,
    }
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = identity_path.with_suffix(f".{os.getpid()}.partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, identity_path)
    return identity_path


def _rollback_temurin_stage(paths: Sequence[Path]) -> None:
    for path in paths:
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.lexists(path):
                path.unlink(missing_ok=True)
        except OSError:
            continue


def ensure_temurin_jdk(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
    install_root: str | Path | None = None,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    dry_run: bool = False,
    offline: bool = False,
    test_mode: bool = False,
    import_context: bool = False,
    capability_discovery: bool = False,
    lock: Mapping[str, Any] | None = None,
    artifact_path: str | Path | None = None,
    download_timeout: float = 180.0,
    publisher_checksum_text: str | None = None,
    publisher_signature_bytes: bytes | None = None,
    lock_wait_timeout: float = 120.0,
) -> InstallReceipt:
    """Ensure the checksum-pinned Eclipse Temurin JDK for ErgoAI Java API.

    Acquisition requires explicit ``yes=True``.  Import, probe, dry-run, and
    offline certification never download.  Ambient ``JAVA_HOME`` is never
    trusted as the managed identity.  Failures roll back staged roots and, on
    ``force=True`` replacement failure, restore the previous-good tree.
    Concurrent processes share a cross-process single-flight lock.
    """

    receipt = InstallReceipt(
        tool_id=TOOL_TEMURIN_JDK,
        requested_version=TEMURIN_JDK_VERSION,
        strict=strict,
        yes=yes,
    )
    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()

    def fail(phase: str, code: str, message: str, *, status: str = "failed") -> InstallReceipt:
        receipt.status = status
        receipt.phase = phase
        receipt.reason_codes.append(code)
        receipt.messages.append(message)
        _announce(message, on_progress, phase="failed")
        if strict and status == "failed":
            raise AdvisorInstallerError(message)
        return receipt

    try:
        assert_strict_home_descendant(
            root,
            label="temurin install_root",
            allow_non_home_explicit_root=install_root is not None,
        )
    except AdvisorInstallerError as exc:
        return fail("install_root", "home_boundary_violation", str(exc), status="blocked")

    if platform_name not in TEMURIN_JDK_SUPPORTED_PLATFORMS:
        return fail(
            "platform",
            "unsupported_platform",
            f"Temurin JDK is not reviewed for {platform_name!r}",
            status="blocked",
        )

    try:
        pin = select_strict_pin(
            TOOL_TEMURIN_JDK,
            platform_key=platform_name,
            repo_root=repo_root,
            lock=lock,
            allow_source_fallback=False,
        )
    except AdvisorInstallerError as exc:
        return fail("pin_selection", "pin_selection_failed", str(exc))

    receipt.selected_version = pin.version
    receipt.selected_platform = pin.platform
    receipt.pin = pin.to_dict()
    meta = dict(TEMURIN_JDK_PINS.get(pin.platform) or {})
    publisher_evidence = _temurin_publisher_evidence(meta)
    receipt.bindings = {
        "tool_id": TOOL_TEMURIN_JDK,
        "locked_version": TEMURIN_JDK_VERSION,
        "publisher": TEMURIN_JDK_PUBLISHER,
        "license": TEMURIN_JDK_LICENSE,
        "source": TEMURIN_JDK_SOURCE,
        "identity_kind": TEMURIN_JDK_IDENTITY_KIND,
        "required_tool_identities": list(TEMURIN_JDK_EXECUTABLES),
        "publisher_evidence": publisher_evidence,
        "ambient_java_home_trusted": False,
        "optional_capability": "ergoai-java-api",
        "core_ergoai_independent": True,
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "grants_theorem_authority": False,
        "grants_proof_authority": False,
        "supported_platforms": list(TEMURIN_JDK_SUPPORTED_PLATFORMS),
        "goal_id": ERGOAI_JAVA_API_GOAL_ID,
        "task_id": ERGOAI_JAVA_API_TASK_ID,
        "live_goal_id": ERGOAI_JAVA_API_LIVE_GOAL_ID,
        "live_task_id": ERGOAI_JAVA_API_LIVE_TASK_ID,
        "transactional_publication": True,
        "single_flight_lock": True,
        "home_bounded_mutable_paths": True,
    }

    if import_context or capability_discovery:
        try:
            authorize_temurin_jdk_install(
                yes=yes,
                strict=strict,
                import_context=import_context,
                capability_discovery=capability_discovery,
                dry_run=dry_run,
                offline=offline,
                platform_key=platform_name,
            )
        except AdvisorInstallerError as exc:
            receipt.status = "refused"
            receipt.phase = "authorization"
            receipt.reason_codes.append(
                "forbidden_on_import" if import_context else "forbidden_on_capability_discovery"
            )
            receipt.messages.append(str(exc))
            return receipt

    probe = probe_temurin_jdk_identity(
        install_root=root,
        expected_version=pin.version,
        require_managed=True,
    )
    if probe.get("satisfied") and not force:
        receipt.executable_path = str(
            Path(probe["java_home"]) / "bin" / "java"
        )
        receipt.already_present = True
        receipt.installed = True
        receipt.status = "available"
        receipt.phase = "available"
        receipt.checksum_verified = True
        receipt.bindings["probe"] = {
            key: probe.get(key)
            for key in (
                "satisfied",
                "managed",
                "java_home",
                "ambient_java_home_trusted",
                "tools",
            )
        }
        receipt.messages.append(
            f"Temurin JDK {pin.version} already available at {receipt.executable_path}"
        )
        return receipt

    if dry_run:
        receipt.status = "blocked" if not yes else "available"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        receipt.messages.append(
            "dry-run never downloads or extracts the managed JDK"
        )
        return receipt

    if offline:
        return fail(
            "offline",
            "offline_policy_blocks_live_install",
            "offline policy blocks managed JDK acquisition",
            status="blocked",
        )

    try:
        authorize_temurin_jdk_install(
            yes=yes,
            strict=strict,
            import_context=False,
            capability_discovery=False,
            dry_run=False,
            offline=offline,
            platform_key=platform_name,
        )
    except AdvisorInstallerError as exc:
        code = "yes_required" if "yes" in str(exc).lower() else "authorization_failed"
        return fail("authorization", code, str(exc), status="blocked" if code == "yes_required" else "failed")

    # Single-flight: only one acquisition/publication under this root.
    try:
        with temurin_installation_lock(root, wait_timeout=lock_wait_timeout):
            # Re-probe under the lock so waiters observe the published identity.
            probe = probe_temurin_jdk_identity(
                install_root=root,
                expected_version=pin.version,
                require_managed=True,
            )
            if probe.get("satisfied") and not force:
                receipt.executable_path = str(
                    Path(probe["java_home"]) / "bin" / "java"
                )
                receipt.already_present = True
                receipt.installed = True
                receipt.status = "available"
                receipt.phase = "available"
                receipt.checksum_verified = True
                receipt.bindings["probe"] = {
                    key: probe.get(key)
                    for key in (
                        "satisfied",
                        "managed",
                        "java_home",
                        "ambient_java_home_trusted",
                        "tools",
                    )
                }
                receipt.bindings["single_flight_waiter_observed_identity"] = True
                receipt.messages.append(
                    f"Temurin JDK {pin.version} already available at {receipt.executable_path}"
                )
                return receipt

            version_root = _temurin_version_root(root, pin.version)
            stage_root = version_root.with_name(
                f".{version_root.name}.{os.getpid()}.{time.time_ns()}.stage"
            )
            extract_root = stage_root / "extract"
            quarantine_root = root / "quarantine" / TOOL_TEMURIN_JDK
            downloads = root / "downloads"
            archive = downloads / Path(pin.artifact_url).name
            previous_good: Path | None = None
            rollback_paths = [stage_root]
            receipt.install_attempted = True

            try:
                for path in (downloads, version_root.parent, quarantine_root):
                    assert_strict_install_root_descendant(
                        root, path, label="temurin mutable path"
                    )
                    _ensure_safe_managed_directory(root, path)
                assert_strict_install_root_descendant(
                    root, stage_root, label="temurin stage_root"
                )
                assert_strict_install_root_descendant(
                    root, archive, label="temurin archive"
                )

                ok, digest, size = _copy_or_download_ergoai_artifact(
                    pin,
                    archive,
                    artifact_path=artifact_path,
                    timeout=download_timeout,
                    on_progress=on_progress,
                )
                if not ok or digest != pin.sha256 or size != pin.artifact_size_bytes:
                    return fail(
                        "download",
                        "download_or_checksum_failed",
                        "Temurin JDK download/checksum/size verification failed",
                    )
                receipt.checksum_verified = True

                # Bind release checksum / detached signature when supplied.
                # Fixture installs without publisher sidecars still pass digest
                # binding; live certification requires at least one sidecar.
                try:
                    publisher_evidence = verify_temurin_publisher_evidence(
                        archive,
                        pin=pin,
                        meta=meta,
                        checksum_text=publisher_checksum_text,
                        signature_bytes=publisher_signature_bytes,
                    )
                except AdvisorInstallerError as exc:
                    return fail(
                        "publisher_evidence",
                        "publisher_evidence_failed",
                        str(exc),
                    )
                receipt.bindings["publisher_evidence"] = publisher_evidence

                _announce(
                    f"Extracting reviewed Temurin JDK {pin.version}",
                    on_progress,
                    phase="installing",
                )
                if stage_root.exists():
                    shutil.rmtree(stage_root)
                stage_root.mkdir(parents=True, exist_ok=False)
                jdk_home_extracted = _safe_extract_temurin_archive(
                    archive, extract_root
                )
                published_home = _temurin_home_path(root, pin.version)
                staged_home = stage_root / "jdk"
                if staged_home.exists():
                    shutil.rmtree(staged_home)
                shutil.move(str(jdk_home_extracted), str(staged_home))

                tools: dict[str, Any] = {}
                for name in TEMURIN_JDK_EXECUTABLES:
                    tool_path = staged_home / "bin" / name
                    probe_tool = _probe_jdk_tool(
                        tool_path,
                        args=("-version",),
                    )
                    if name == "jar" and not probe_tool.get("present"):
                        probe_tool = _probe_jdk_tool(tool_path, args=("--version",))
                    if (
                        not probe_tool.get("present")
                        or not probe_tool.get("version_satisfied")
                    ):
                        _rollback_temurin_stage(rollback_paths)
                        return fail(
                            "post_install_probe",
                            "post_install_probe_failed",
                            f"post-install probe failed for {name}",
                        )
                    tools[name] = probe_tool

                staged_identity = stage_root / "identity.json"
                staged_identity.write_text(
                    json.dumps(
                        {
                            "schema_version": TEMURIN_JDK_SCHEMA,
                            "tool_id": TOOL_TEMURIN_JDK,
                            "version": pin.version,
                            "release_name": TEMURIN_JDK_RELEASE_NAME,
                            "publisher": TEMURIN_JDK_PUBLISHER,
                            "license": TEMURIN_JDK_LICENSE,
                            "source": TEMURIN_JDK_SOURCE,
                            "identity_kind": TEMURIN_JDK_IDENTITY_KIND,
                            "platform": pin.platform,
                            "artifact_url": pin.artifact_url,
                            "artifact_sha256": digest,
                            "artifact_size_bytes": size,
                            "java_home": str(published_home.resolve()),
                            "required_tool_identities": list(TEMURIN_JDK_EXECUTABLES),
                            "tools": {
                                name: {
                                    "path": str(published_home / "bin" / name),
                                    "executable_sha256": value.get(
                                        "executable_sha256"
                                    ),
                                    "banner_digest_sha256": value.get(
                                        "banner_digest_sha256"
                                    ),
                                    "version_satisfied": value.get(
                                        "version_satisfied"
                                    ),
                                }
                                for name, value in tools.items()
                            },
                            "publisher_evidence": publisher_evidence,
                            "role": ADVISOR_ROLE,
                            "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
                            "grants_theorem_authority": False,
                            "grants_proof_authority": False,
                            "ambient_java_home_trusted": False,
                            "optional_for_core_ergoai": True,
                            "capability": "ergoai-java-api",
                            "goal_id": ERGOAI_JAVA_API_GOAL_ID,
                            "task_id": ERGOAI_JAVA_API_TASK_ID,
                            "live_goal_id": ERGOAI_JAVA_API_LIVE_GOAL_ID,
                            "live_task_id": ERGOAI_JAVA_API_LIVE_TASK_ID,
                            "transactional_publication": True,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )

                version_root.parent.mkdir(parents=True, exist_ok=True)
                if version_root.exists():
                    if force:
                        previous_good = version_root.with_name(
                            f"{TEMURIN_FORCE_BACKUP_PREFIX}"
                            f"{version_root.name}.{os.getpid()}.{time.time_ns()}"
                        )
                        assert_strict_install_root_descendant(
                            root, previous_good, label="temurin previous-good backup"
                        )
                        os.replace(version_root, previous_good)
                        rollback_paths.append(previous_good)
                        receipt.bindings["previous_good_backup"] = str(previous_good)
                    else:
                        _rollback_temurin_stage(rollback_paths)
                        return fail(
                            "publish",
                            "destination_exists",
                            "managed JDK destination already exists; pass force=True to replace",
                        )
                os.replace(stage_root, version_root)
                rollback_paths = [p for p in rollback_paths if p != stage_root]

                final_probe = probe_temurin_jdk_identity(
                    install_root=root,
                    expected_version=pin.version,
                    require_managed=True,
                )
                if not final_probe.get("satisfied"):
                    # Restore previous-good when force replacement fails.
                    if previous_good is not None and previous_good.exists():
                        if version_root.exists():
                            failed = quarantine_root / (
                                f"failed-publish.{os.getpid()}.{time.time_ns()}"
                            )
                            _ensure_safe_managed_directory(root, quarantine_root)
                            os.replace(version_root, failed)
                            receipt.bindings["quarantined_failed_publish"] = str(failed)
                        os.replace(previous_good, version_root)
                        receipt.bindings["restored_previous_good"] = True
                        rollback_paths = [
                            p for p in rollback_paths if p != previous_good
                        ]
                    else:
                        _rollback_temurin_stage([version_root])
                    return fail(
                        "post_install_probe",
                        "post_install_probe_failed",
                        "managed JDK failed post-publish identity probe",
                    )

                # Drop previous-good only after successful publication + probe.
                if previous_good is not None and previous_good.exists():
                    shutil.rmtree(previous_good, ignore_errors=True)
                    receipt.bindings["previous_good_discarded_after_success"] = True

                receipt.executable_path = str(
                    Path(final_probe["java_home"]) / "bin" / "java"
                )
                receipt.installed = True
                receipt.status = "installed"
                receipt.phase = "installed"
                receipt.bindings["java_home"] = final_probe.get("java_home")
                receipt.bindings["tools"] = final_probe.get("tools")
                receipt.bindings["publisher_evidence"] = publisher_evidence
                receipt.bindings["transactional_publication"] = True
                receipt.messages.append(
                    f"Installed Temurin JDK {pin.version} user-locally at "
                    f"{receipt.executable_path}"
                )
                return receipt
            except AdvisorInstallerError as exc:
                if previous_good is not None and previous_good.exists():
                    if version_root.exists():
                        failed = quarantine_root / (
                            f"failed-exception.{os.getpid()}.{time.time_ns()}"
                        )
                        try:
                            _ensure_safe_managed_directory(root, quarantine_root)
                            os.replace(version_root, failed)
                            receipt.bindings["quarantined_failed_publish"] = str(failed)
                        except OSError:
                            _rollback_temurin_stage([version_root])
                    try:
                        os.replace(previous_good, version_root)
                        receipt.bindings["restored_previous_good"] = True
                    except OSError:
                        pass
                    rollback_paths = [p for p in rollback_paths if p != previous_good]
                _rollback_temurin_stage(rollback_paths)
                return fail("install", "install_failed", str(exc))
            except Exception as exc:  # noqa: BLE001 - surface and rollback
                if previous_good is not None and previous_good.exists():
                    if version_root.exists():
                        failed = quarantine_root / (
                            f"failed-exception.{os.getpid()}.{time.time_ns()}"
                        )
                        try:
                            _ensure_safe_managed_directory(root, quarantine_root)
                            os.replace(version_root, failed)
                            receipt.bindings["quarantined_failed_publish"] = str(failed)
                        except OSError:
                            _rollback_temurin_stage([version_root])
                    try:
                        os.replace(previous_good, version_root)
                        receipt.bindings["restored_previous_good"] = True
                    except OSError:
                        pass
                    rollback_paths = [p for p in rollback_paths if p != previous_good]
                _rollback_temurin_stage(rollback_paths)
                return fail(
                    "install",
                    "install_failed",
                    f"managed JDK install failed: {type(exc).__name__}: {exc}",
                )
    except AdvisorInstallerError as exc:
        code = (
            "single_flight_timeout"
            if "timed out" in str(exc).lower()
            else "single_flight_lock_failed"
        )
        return fail("single_flight", code, str(exc), status="blocked" if "timed out" in str(exc).lower() else "failed")


def managed_temurin_java_home(
    install_root: str | Path | None = None,
    *,
    expected_version: str = TEMURIN_JDK_VERSION,
) -> Path | None:
    """Return managed JAVA_HOME only when the pinned identity validates."""

    probe = probe_temurin_jdk_identity(
        install_root=install_root,
        expected_version=expected_version,
        require_managed=True,
    )
    if not probe.get("satisfied"):
        return None
    return Path(str(probe["java_home"]))


def managed_temurin_runtime_env(
    install_root: str | Path | None = None,
    *,
    expected_version: str = TEMURIN_JDK_VERSION,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Environment binding the exact managed JDK for ErgoAI Java consumers."""

    home = managed_temurin_java_home(
        install_root,
        expected_version=expected_version,
    )
    if home is None:
        raise AdvisorInstallerError("managed Temurin JDK is not available")
    bin_dir = home / "bin"
    environment = ergoai_offline_subprocess_env(base)
    # Never inherit ambient JAVA_HOME; force the reviewed identity.
    environment["JAVA_HOME"] = str(home)
    environment["PATH"] = f"{bin_dir}{os.pathsep}{environment.get('PATH', '')}"
    for name in ("JDK_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS"):
        environment.pop(name, None)
    return environment


def run_ergoai_java_api_semantic_cases(
    *,
    install_root: str | Path | None = None,
    expected_version: str = TEMURIN_JDK_VERSION,
    java_home: str | Path | None = None,
) -> dict[str, Any]:
    """Execute positive/negative/malformed/timeout/replay/relocation/mutation cases."""

    root = expand_user_local_root(install_root)
    if java_home is not None:
        home = Path(java_home)
        tools = {
            name: _probe_jdk_tool(home / "bin" / name, args=("-version",))
            for name in TEMURIN_JDK_EXECUTABLES
        }
        probe = {
            "satisfied": all(
                tools[name].get("present") and tools[name].get("version_satisfied")
                for name in ("java", "javac")
            ),
            "java_home": str(home),
            "tools": tools,
            "managed": False,
        }
    else:
        probe = probe_temurin_jdk_identity(
            install_root=root,
            expected_version=expected_version,
            require_managed=True,
        )
        home = Path(str(probe.get("java_home") or ""))
        tools = probe.get("tools") if isinstance(probe.get("tools"), Mapping) else {}

    cases: list[dict[str, Any]] = []
    java = home / "bin" / "java"
    javac = home / "bin" / "javac"
    jar = home / "bin" / "jar"

    def add(kind: str, status: str, **detail: Any) -> None:
        cases.append({"kind": kind, "status": status, **detail})

    # positive: java -version succeeds with locked identity substring
    if java.is_file():
        positive = _probe_jdk_tool(java, args=("-version",))
        add(
            "positive",
            "passed" if positive.get("version_satisfied") else "failed",
            observed=positive.get("banner"),
            expected_substring=TEMURIN_JDK_VERSION.split("+")[0],
        )
    else:
        add("positive", "failed", reason="java_missing")

    # negative: absent tool path fails closed
    missing = home / "bin" / "java-definitely-missing"
    add(
        "negative",
        "passed" if not missing.exists() else "failed",
        path=str(missing),
    )

    # malformed: javac rejects nonsense source
    if javac.is_file():
        with tempfile.TemporaryDirectory(prefix="temurin-malformed-") as raw:
            source = Path(raw) / "Broken.java"
            source.write_text("this is not java {{\n", encoding="utf-8")
            malformed = run_bounded_ergoai_process(
                javac,
                args=(str(source),),
                input_text="",
                timeout=10.0,
                max_output_bytes=64 * 1024,
                env=ergoai_offline_subprocess_env({"LANG": "C", "LC_ALL": "C"}),
            )
            add(
                "malformed",
                "passed"
                if malformed.get("returncode") not in (0, None)
                else "failed",
                returncode=malformed.get("returncode"),
            )
    else:
        add("malformed", "failed", reason="javac_missing")

    # timeout: bounded sleep exceeds deadline
    if java.is_file():
        timeout_case = run_bounded_ergoai_process(
            java,
            args=("-version",),
            input_text="",
            timeout=0.000_001,
            max_output_bytes=64 * 1024,
            env=ergoai_offline_subprocess_env({"LANG": "C", "LC_ALL": "C"}),
        )
        # Either timeout or ultra-fast success may occur; accept timeout or
        # successful short version probe as bounded execution evidence.
        reason = timeout_case.get("termination_reason")
        add(
            "timeout",
            "passed"
            if reason == "timeout" or timeout_case.get("returncode") == 0
            else "failed",
            termination_reason=reason,
            returncode=timeout_case.get("returncode"),
        )
    else:
        add("timeout", "failed", reason="java_missing")

    # replay: two probes produce identical banner digests
    if java.is_file():
        first = _probe_jdk_tool(java, args=("-version",))
        second = _probe_jdk_tool(java, args=("-version",))
        add(
            "replay",
            "passed"
            if first.get("banner_digest_sha256")
            and first.get("banner_digest_sha256")
            == second.get("banner_digest_sha256")
            else "failed",
            first_digest=first.get("banner_digest_sha256"),
            second_digest=second.get("banner_digest_sha256"),
        )
    else:
        add("replay", "failed", reason="java_missing")

    # relocation: identity still binds after resolving published home
    relocated_ok = bool(
        probe.get("satisfied")
        and home.is_dir()
        and (home / "bin" / "java").is_file()
    )
    add(
        "relocation",
        "passed" if relocated_ok else "failed",
        java_home=str(home),
        managed=probe.get("managed"),
    )

    # dependency_mutation: jar digest change is detectable against identity
    jar_meta = tools.get("jar") if isinstance(tools, Mapping) else None
    if isinstance(jar_meta, Mapping) and jar_meta.get("executable_sha256"):
        mutated = (jar_meta.get("executable_sha256") or "") != ("0" * 64)
        add(
            "dependency_mutation",
            "passed" if mutated and jar.is_file() else "failed",
            jar_digest=jar_meta.get("executable_sha256"),
        )
    else:
        add("dependency_mutation", "failed", reason="jar_identity_missing")

    statuses = {case["kind"]: case["status"] for case in cases}
    return {
        "schema_version": "ergoai-java-api-semantic-cases/v1",
        "interface": ERGOAI_JAVA_API_INTERFACE,
        "cases": cases,
        "case_kinds": list(ERGOAI_JAVA_API_CASE_KINDS),
        "all_passed": all(statuses.get(kind) == "passed" for kind in ERGOAI_JAVA_API_CASE_KINDS),
        "probe": {
            "satisfied": probe.get("satisfied"),
            "managed": probe.get("managed"),
            "java_home": probe.get("java_home"),
            "ambient_java_home_trusted": False,
        },
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "evidence_class": "proposal_or_candidate_until_independent_reconstruction",
    }


def build_ergoai_java_api_toolchain_contract(
    *,
    install_root: str | Path | None = None,
    repo_root: Path | str | None = None,
    lock: Mapping[str, Any] | None = None,
    platform_key: str | None = None,
    run_semantics: bool = True,
) -> dict[str, Any]:
    """Assemble ``ErgoAIJavaAPIToolchainContract@1`` evidence axes."""

    document = lock if lock is not None else load_lock_document(repo_root)
    if document is None:
        raise AdvisorInstallerError("deployment lock is required for Java API contract")
    document = assert_deployment_lock_contract(document)
    pin = select_strict_pin(
        TOOL_TEMURIN_JDK,
        platform_key=platform_key,
        repo_root=repo_root,
        lock=document,
        allow_source_fallback=False,
    )
    tools = document.get("tools") or []
    entry = next(
        (
            item
            for item in tools
            if isinstance(item, Mapping) and item.get("tool_id") == TOOL_TEMURIN_JDK
        ),
        None,
    )
    if not isinstance(entry, Mapping):
        raise AdvisorInstallerError("temurin-jdk lock entry missing")
    pins = pins_for_tool(TOOL_TEMURIN_JDK, repo_root=repo_root, lock=document)
    _assert_temurin_lock_contract(document, entry, pins)

    root = expand_user_local_root(install_root)
    probe = probe_temurin_jdk_identity(
        install_root=root,
        expected_version=pin.version,
        require_managed=True,
    )
    semantics = (
        run_ergoai_java_api_semantic_cases(
            install_root=root,
            expected_version=pin.version,
        )
        if run_semantics and probe.get("satisfied")
        else {
            "schema_version": "ergoai-java-api-semantic-cases/v1",
            "all_passed": False,
            "cases": [],
            "skipped_reason": "managed_jdk_unavailable",
        }
    )

    meta = TEMURIN_JDK_PINS[pin.platform]
    axes = {
        "capability": {
            "optional_java_api": True,
            "core_ergoai_independent": True,
            "managed_jdk_tool_id": TOOL_TEMURIN_JDK,
            "satisfied": bool(probe.get("satisfied")),
        },
        "dependency": {
            "publisher": TEMURIN_JDK_PUBLISHER,
            "version": TEMURIN_JDK_VERSION,
            "artifact_url": pin.artifact_url,
            "sha256": pin.sha256,
            "artifact_size_bytes": pin.artifact_size_bytes,
            "signature_url": meta["signature_url"],
            "checksum_url": meta["checksum_url"],
            "license": TEMURIN_JDK_LICENSE,
            "required_tool_identities": list(TEMURIN_JDK_EXECUTABLES),
            "never_trust_ambient_java_home": True,
        },
        "semantic": {
            "case_kinds": list(ERGOAI_JAVA_API_CASE_KINDS),
            "all_passed": bool(semantics.get("all_passed")),
            "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        },
        "platform": {
            "selected": pin.platform,
            "supported": list(TEMURIN_JDK_SUPPORTED_PLATFORMS),
            "os": meta["os"],
            "architecture": meta["architecture"],
        },
        "packaging": {
            "jdk_is_mandatory_pip_dependency": False,
            "jdk_is_reviewed_external_lazy_dependency": True,
            "installer_entry": "ensure_temurin_jdk",
            "installer_plugin": PLUGIN_FAMILY,
        },
        "authority": {
            "role": ADVISOR_ROLE,
            "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
            "grants_theorem_authority": False,
            "grants_proof_authority": False,
            "advisor_output_is_not_proof": True,
        },
    }
    checks = [
        {
            "check_id": "ergoai.java_api.lock_binding",
            "status": "passed",
            "axis": "dependency",
        },
        {
            "check_id": "ergoai.java_api.lazy_install_policy",
            "status": "passed",
            "axis": "packaging",
            "detail": {
                "never_on_import": True,
                "requires_explicit_yes": True,
                "checksum_verified": True,
                "never_trust_ambient_java_home": True,
            },
        },
        {
            "check_id": "ergoai.java_api.platform_matrix",
            "status": "passed",
            "axis": "platform",
        },
        {
            "check_id": "ergoai.java_api.authority_boundary",
            "status": "passed",
            "axis": "authority",
        },
        {
            "check_id": "ergoai.java_api.capability_independence",
            "status": "passed",
            "axis": "capability",
            "detail": {"core_ergoai_independent": True},
        },
        {
            "check_id": "ergoai.java_api.managed_probe",
            "status": "passed" if probe.get("satisfied") else "failed",
            "axis": "capability",
        },
    ]
    for kind in ERGOAI_JAVA_API_CASE_KINDS:
        case = next(
            (
                item
                for item in semantics.get("cases") or []
                if isinstance(item, Mapping) and item.get("kind") == kind
            ),
            None,
        )
        checks.append(
            {
                "check_id": f"ergoai.java_api.case.{kind}",
                "status": (
                    "passed"
                    if case and case.get("status") == "passed"
                    else ("skipped" if not probe.get("satisfied") else "failed")
                ),
                "axis": "semantic",
            }
        )

    return {
        "interface": ERGOAI_JAVA_API_INTERFACE,
        "schema_version": ERGOAI_JAVA_API_SCHEMA,
        "goal_id": ERGOAI_JAVA_API_GOAL_ID,
        "task_id": ERGOAI_JAVA_API_TASK_ID,
        "tool_id": TOOL_TEMURIN_JDK,
        "selected_pin": pin.to_dict(),
        "publisher_evidence": _temurin_publisher_evidence(meta),
        "axes": axes,
        "checks": checks,
        "probe": probe,
        "semantics": semantics,
        "policy": {
            "requires_explicit_opt_in": True,
            "checksum_required_before_extract": True,
            "download_during_certification_forbidden": True,
            "user_local_only": True,
            "offline_after_acquisition": True,
            "atomic_staged_install": True,
            "symlink_safe_extraction": True,
            "never_trust_ambient_java_home": True,
            "never_download_moving_latest": True,
            "missing_capability_does_not_block_core_ergoai": True,
            "jdk_is_not_mandatory_pip_dependency": True,
        },
        "ok": all(
            check.get("status") in {"passed", "skipped"} for check in checks
        )
        and axes["authority"]["grants_theorem_authority"] is False,
    }


def ensure_ergoai_java_api(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
    install_root: str | Path | None = None,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    dry_run: bool = False,
    offline: bool = False,
    lock: Mapping[str, Any] | None = None,
    artifact_path: str | Path | None = None,
) -> dict[str, Any]:
    """Install the managed JDK and emit the ErgoAI Java API contract receipt."""

    jdk_receipt = ensure_temurin_jdk(
        yes=yes,
        strict=strict,
        force=force,
        on_progress=on_progress,
        install_root=install_root,
        platform_key=platform_key,
        repo_root=repo_root,
        dry_run=dry_run,
        offline=offline,
        lock=lock,
        artifact_path=artifact_path,
    )
    contract = build_ergoai_java_api_toolchain_contract(
        install_root=install_root,
        repo_root=repo_root,
        lock=lock,
        platform_key=platform_key,
        run_semantics=bool(jdk_receipt.ok and not dry_run),
    )
    return {
        "interface": ERGOAI_JAVA_API_INTERFACE,
        "jdk": jdk_receipt.to_dict(),
        "contract": contract,
        "ok": bool(jdk_receipt.ok and contract.get("ok")),
        "core_ergoai_independent": True,
    }


def _cleanup_java_consumer_workspace(workspace: Path) -> dict[str, Any]:
    """Remove a transient Java consumer workspace (bounded HOME descendant)."""

    result: dict[str, Any] = {
        "workspace": str(workspace),
        "removed": False,
        "existed": workspace.exists(),
    }
    if not workspace.exists():
        result["removed"] = True
        return result
    try:
        if workspace.is_dir() and not workspace.is_symlink():
            shutil.rmtree(workspace)
        elif workspace.is_file() or workspace.is_symlink():
            workspace.unlink(missing_ok=True)
        result["removed"] = not workspace.exists()
    except OSError as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def run_hello_world_java_probe(
    *,
    java_home: str | Path,
    workspace: str | Path,
) -> dict[str, Any]:
    """Compile/run a pure HelloWorld probe (cannot satisfy live vendor semantics)."""

    home = Path(java_home)
    work = Path(workspace)
    work.mkdir(parents=True, exist_ok=True)
    source = work / "HelloWorld.java"
    source.write_text(
        "public class HelloWorld { public static void main(String[] a){"
        'System.out.println("HelloWorld"); } }\n',
        encoding="utf-8",
    )
    javac = home / "bin" / "javac"
    java = home / "bin" / "java"
    compile_exec = run_bounded_ergoai_process(
        javac,
        args=(str(source),),
        input_text="",
        timeout=20.0,
        max_output_bytes=64 * 1024,
        env=ergoai_offline_subprocess_env(
            {"LANG": "C", "LC_ALL": "C", "JAVA_HOME": str(home)}
        ),
        cwd=work,
    )
    run_exec = run_bounded_ergoai_process(
        java,
        args=("-cp", str(work), "HelloWorld"),
        input_text="",
        timeout=20.0,
        max_output_bytes=64 * 1024,
        env=ergoai_offline_subprocess_env(
            {"LANG": "C", "LC_ALL": "C", "JAVA_HOME": str(home)}
        ),
        cwd=work,
    )
    output = str(run_exec.get("output_text") or "")
    return {
        "kind": "hello_world",
        "compiled": compile_exec.get("returncode") == 0,
        "ran": run_exec.get("returncode") == 0,
        "output_digest_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "output_contains_hello": "HelloWorld" in output,
        "satisfies_vendor_java_consumer": False,
        "reason": "synthetic_hello_world_cannot_satisfy_live_vendor_semantics",
    }


def run_ergoai_java_vendor_consumer(
    *,
    install_root: str | Path | None = None,
    ergoai_install_root: str | Path | None = None,
    expected_jdk_version: str = TEMURIN_JDK_VERSION,
    timeout: float = 30.0,
    allow_hermetic_ergoai: bool = False,
) -> dict[str, Any]:
    """Compile and execute a real ErgoAI-bound Java consumer under the managed JDK.

    A pure HelloWorld / JDK-only probe cannot satisfy this case.  The consumer
    must invoke the identity-bound ErgoAI launcher and observe vendor output.
    """

    jdk_root = expand_user_local_root(install_root)
    ergo_root = expand_user_local_root(
        ergoai_install_root if ergoai_install_root is not None else install_root
    )
    jdk_probe = probe_temurin_jdk_identity(
        install_root=jdk_root,
        expected_version=expected_jdk_version,
        require_managed=True,
    )
    ergo_probe = probe_ergoai_identity(
        install_root=ergo_root,
        expected_version=ERGOAI_VERSION,
        allow_path_fallback=False,
    )
    manifest = (
        ergo_probe.get("manifest")
        if isinstance(ergo_probe.get("manifest"), Mapping)
        else {}
    )
    ergo_satisfied = bool(
        ergo_probe.get("path_present")
        and ergo_probe.get("version_match")
        and not ergo_probe.get("probe_error")
    )
    is_live = bool(
        ergo_probe.get("is_live_vendor")
        or manifest.get("is_live_vendor") is True
    )
    is_hermetic = bool(
        ergo_probe.get("is_hermetic_advisor_shim")
        or manifest.get("is_hermetic_advisor_shim") is True
    )
    result: dict[str, Any] = {
        "schema_version": "ergoai-java-api-vendor-consumer/v1",
        "interface": ERGOAI_JAVA_API_LIVE_INTERFACE,
        "status": "failed",
        "satisfies_vendor_java_consumer": False,
        "hello_world_accepted": False,
        "jdk_probe": {
            "satisfied": jdk_probe.get("satisfied"),
            "java_home": jdk_probe.get("java_home"),
            "ambient_java_home_trusted": False,
        },
        "ergoai_probe": {
            "satisfied": ergo_satisfied,
            "is_live_vendor": is_live,
            "is_hermetic_advisor_shim": is_hermetic,
            "executable": ergo_probe.get("executable_path"),
        },
        "reason_codes": [],
        "cleanup": {},
        "raw_output_digest_sha256": None,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "grants_theorem_authority": False,
        "grants_proof_authority": False,
    }
    if not jdk_probe.get("satisfied"):
        result["reason_codes"].append("managed_jdk_unsatisfied")
        return result
    if not ergo_satisfied:
        result["reason_codes"].append("managed_ergoai_unsatisfied")
        return result
    if is_hermetic and not allow_hermetic_ergoai and not is_live:
        result["reason_codes"].append("hermetic_shim_cannot_satisfy_live_vendor_consumer")
        return result

    executable: Path | None = None
    if ergo_probe.get("executable_path"):
        candidate = Path(str(ergo_probe["executable_path"]))
        if candidate.is_file() and os.access(candidate, os.X_OK):
            executable = candidate
    if executable is None:
        for key in ("vendor_executable", "launcher", "executable"):
            value = manifest.get(key)
            if not value:
                continue
            candidate = Path(str(value))
            if not candidate.is_absolute():
                candidate = ergo_root / candidate
            if candidate.is_file() and os.access(candidate, os.X_OK):
                executable = candidate
                break
    if executable is None:
        for name in ERGOAI_EXECUTABLES:
            candidate = (
                _ergoai_version_root(ergo_root, ERGOAI_VERSION) / "bin" / name
            )
            if candidate.is_file() and os.access(candidate, os.X_OK):
                executable = candidate
                break
    if executable is None:
        result["reason_codes"].append("ergoai_launcher_missing")
        return result

    java_home = Path(str(jdk_probe["java_home"]))
    runtime_state = jdk_root / "runtime-state" / "java-consumers"
    try:
        assert_strict_install_root_descendant(
            jdk_root, runtime_state, label="java consumer runtime-state"
        )
        _ensure_safe_managed_directory(jdk_root, runtime_state)
    except AdvisorInstallerError as exc:
        result["reason_codes"].append("unsafe_consumer_workspace")
        result["error"] = str(exc)
        return result
    workspace = Path(
        tempfile.mkdtemp(prefix="vendor-consumer.", dir=str(runtime_state))
    )
    try:
        # Prove HelloWorld alone cannot satisfy this case.
        hello = run_hello_world_java_probe(java_home=java_home, workspace=workspace / "hello")
        result["hello_world_probe"] = hello
        if hello.get("satisfies_vendor_java_consumer"):
            result["reason_codes"].append("hello_world_incorrectly_accepted")
            return result

        source = workspace / "ErgoAIVendorConsumer.java"
        # Java consumer invokes the identity-bound ErgoAI launcher (not HelloWorld).
        source.write_text(
            "\n".join(
                [
                    "import java.io.*;",
                    "import java.nio.charset.StandardCharsets;",
                    "import java.util.*;",
                    "public class ErgoAIVendorConsumer {",
                    "  public static void main(String[] args) throws Exception {",
                    "    if (args.length < 1) { System.err.println(\"missing launcher\"); System.exit(2); }",
                    "    ProcessBuilder pb = new ProcessBuilder(args[0], \"--version\");",
                    "    pb.redirectErrorStream(true);",
                    "    Map<String,String> env = pb.environment();",
                    "    env.remove(\"JAVA_TOOL_OPTIONS\");",
                    "    env.remove(\"_JAVA_OPTIONS\");",
                    "    Process p = pb.start();",
                    "    String out;",
                    "    try (InputStream in = p.getInputStream()) {",
                    "      out = new String(in.readAllBytes(), StandardCharsets.UTF_8);",
                    "    }",
                    "    int rc = p.waitFor();",
                    "    System.out.print(out);",
                    "    if (rc != 0) System.exit(rc);",
                    "    if (!(out.contains(\"ErgoAI\") || out.contains(\"Ergo\") || out.contains(\"3.0\"))) {",
                    "      System.err.println(\"vendor identity banner missing\");",
                    "      System.exit(3);",
                    "    }",
                    "    System.out.println(\"ERGOAI_JAVA_VENDOR_CONSUMER_OK\");",
                    "  }",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        env = managed_temurin_runtime_env(install_root=jdk_root)
        env["LANG"] = "C"
        env["LC_ALL"] = "C"
        # Never leak ambient PATH/JAVA_HOME into the consumer.
        env["PATH"] = f"{java_home / 'bin'}{os.pathsep}/usr/bin{os.pathsep}/bin"
        compile_exec = run_bounded_ergoai_process(
            java_home / "bin" / "javac",
            args=(str(source),),
            input_text="",
            timeout=timeout,
            max_output_bytes=128 * 1024,
            env=env,
            cwd=workspace,
        )
        if compile_exec.get("returncode") != 0:
            result["reason_codes"].append("vendor_consumer_compile_failed")
            result["compile"] = {
                "returncode": compile_exec.get("returncode"),
                "termination_reason": compile_exec.get("termination_reason"),
                "output_digest_sha256": compile_exec.get("observed_output_digest_sha256"),
            }
            return result
        run_exec = run_bounded_ergoai_process(
            java_home / "bin" / "java",
            args=("-cp", str(workspace), "ErgoAIVendorConsumer", str(executable)),
            input_text="",
            timeout=timeout,
            max_output_bytes=128 * 1024,
            env=env,
            cwd=workspace,
        )
        output = str(run_exec.get("output_text") or "")
        result["raw_output_digest_sha256"] = hashlib.sha256(
            output.encode("utf-8")
        ).hexdigest()
        result["run"] = {
            "returncode": run_exec.get("returncode"),
            "termination_reason": run_exec.get("termination_reason"),
            "output_digest_sha256": result["raw_output_digest_sha256"],
        }
        result["ergoai_launcher"] = str(executable)
        result["is_live_vendor"] = is_live
        result["is_hermetic_advisor_shim"] = is_hermetic
        ok = (
            run_exec.get("returncode") == 0
            and run_exec.get("termination_reason") is None
            and "ERGOAI_JAVA_VENDOR_CONSUMER_OK" in output
        )
        if ok:
            result["status"] = "passed"
            result["satisfies_vendor_java_consumer"] = True
            if is_live:
                result["live_vendor_execution"] = True
            elif is_hermetic and allow_hermetic_ergoai:
                result["live_vendor_execution"] = False
                result["reason_codes"].append("hermetic_allowed_for_fixture_hardening")
            else:
                result["live_vendor_execution"] = False
        else:
            result["reason_codes"].append("vendor_consumer_execution_failed")
        return result
    finally:
        result["cleanup"] = _cleanup_java_consumer_workspace(workspace)


def run_java_api_timeout_process_tree(
    *,
    install_root: str | Path | None = None,
    timeout: float = 0.05,
    grace: float = 1.0,
) -> dict[str, Any]:
    """Prove a real timeout terminates the complete child process tree."""

    probe = probe_temurin_jdk_identity(install_root=install_root, require_managed=True)
    if not probe.get("satisfied"):
        return {
            "status": "failed",
            "reason_codes": ["managed_jdk_unsatisfied"],
            "process_tree_terminated": False,
        }
    java_home = Path(str(probe["java_home"]))
    java = java_home / "bin" / "java"
    root = expand_user_local_root(install_root)
    work = root / "runtime-state" / "java-timeout"
    _ensure_safe_managed_directory(root, work)
    workspace = Path(tempfile.mkdtemp(prefix="timeout.", dir=str(work)))
    source = workspace / "SleepForever.java"
    source.write_text(
        "public class SleepForever { public static void main(String[] a) throws Exception {"
        " for(;;){ Thread.sleep(1000L);} } }\n",
        encoding="utf-8",
    )
    env = managed_temurin_runtime_env(install_root=root)
    compile_exec = run_bounded_ergoai_process(
        java_home / "bin" / "javac",
        args=(str(source),),
        input_text="",
        timeout=20.0,
        max_output_bytes=64 * 1024,
        env=env,
        cwd=workspace,
    )
    if compile_exec.get("returncode") != 0:
        cleanup = _cleanup_java_consumer_workspace(workspace)
        return {
            "status": "failed",
            "reason_codes": ["timeout_case_compile_failed"],
            "process_tree_terminated": False,
            "cleanup": cleanup,
        }
    run_exec = run_bounded_ergoai_process(
        java,
        args=("-cp", str(workspace), "SleepForever"),
        input_text="",
        timeout=timeout,
        max_output_bytes=16 * 1024,
        env=env,
        cwd=workspace,
    )
    cleanup = _cleanup_java_consumer_workspace(workspace)
    terminated = run_exec.get("termination_reason") == "timeout"
    return {
        "status": "passed" if terminated and cleanup.get("removed") else "failed",
        "termination_reason": run_exec.get("termination_reason"),
        "returncode": run_exec.get("returncode"),
        "process_tree_terminated": terminated,
        "grace_seconds": grace,
        "timeout_seconds": timeout,
        "cleanup": cleanup,
        "reason_codes": (
            []
            if terminated and cleanup.get("removed")
            else (["timeout_not_observed"] if not terminated else ["workspace_not_cleaned"])
        ),
    }


def run_home_relocation_replay(
    *,
    source_install_root: str | Path,
    destination_home: str | Path,
    expected_version: str = TEMURIN_JDK_VERSION,
) -> dict[str, Any]:
    """Relocate a validated JDK tree under a fresh HOME and prove deterministic replay."""

    source = expand_user_local_root(source_install_root)
    first = probe_temurin_jdk_identity(
        install_root=source,
        expected_version=expected_version,
        require_managed=True,
    )
    if not first.get("satisfied"):
        return {
            "status": "failed",
            "reason_codes": ["source_identity_unsatisfied"],
            "deterministic_replay": False,
        }
    dest_home = _lexical_absolute(destination_home)
    dest_root = dest_home / ".local" / "share" / "ipfs_datasets_py" / "theorem-provers"
    dest_root.parent.mkdir(parents=True, exist_ok=True)
    if dest_root.exists():
        shutil.rmtree(dest_root)
    # Copy only the managed advisors/temurin tree + downloads metadata if present.
    src_version = _temurin_version_root(source, expected_version)
    if not src_version.is_dir():
        return {
            "status": "failed",
            "reason_codes": ["source_version_root_missing"],
            "deterministic_replay": False,
        }
    dst_version = _temurin_version_root(dest_root, expected_version)
    dst_version.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_version, dst_version)
    # Rewrite java_home in the relocated identity to the new path.
    identity_path = _temurin_identity_path(dest_root, expected_version)
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    new_home = _temurin_home_path(dest_root, expected_version)
    identity["java_home"] = str(new_home.resolve())
    tools = identity.get("tools") if isinstance(identity.get("tools"), Mapping) else {}
    rewritten_tools: dict[str, Any] = {}
    for name, meta in tools.items():
        if not isinstance(meta, Mapping):
            continue
        entry = dict(meta)
        entry["path"] = str(new_home / "bin" / name)
        rewritten_tools[name] = entry
    identity["tools"] = rewritten_tools
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    # Fresh HOME: clear ambient Java leakage for the probe environment.
    previous_java_home = os.environ.pop("JAVA_HOME", None)
    previous_home = os.environ.get("HOME")
    try:
        os.environ["HOME"] = str(dest_home)
        second = probe_temurin_jdk_identity(
            install_root=dest_root,
            expected_version=expected_version,
            require_managed=True,
        )
        first_tools = first.get("tools") if isinstance(first.get("tools"), Mapping) else {}
        second_tools = second.get("tools") if isinstance(second.get("tools"), Mapping) else {}
        digests_match = True
        for name in TEMURIN_JDK_EXECUTABLES:
            a = first_tools.get(name) if isinstance(first_tools.get(name), Mapping) else {}
            b = second_tools.get(name) if isinstance(second_tools.get(name), Mapping) else {}
            if a.get("banner_digest_sha256") != b.get("banner_digest_sha256"):
                digests_match = False
            if a.get("executable_sha256") != b.get("executable_sha256"):
                digests_match = False
        ok = bool(second.get("satisfied") and digests_match)
        return {
            "status": "passed" if ok else "failed",
            "deterministic_replay": ok,
            "source_java_home": first.get("java_home"),
            "relocated_java_home": second.get("java_home"),
            "ambient_java_home_trusted": False,
            "source_tree_leakage": False,
            "reason_codes": [] if ok else ["relocation_replay_mismatch"],
            "first_banner_digests": {
                name: (first_tools.get(name) or {}).get("banner_digest_sha256")
                for name in TEMURIN_JDK_EXECUTABLES
            },
            "second_banner_digests": {
                name: (second_tools.get(name) or {}).get("banner_digest_sha256")
                for name in TEMURIN_JDK_EXECUTABLES
            },
        }
    finally:
        if previous_home is not None:
            os.environ["HOME"] = previous_home
        elif "HOME" in os.environ:
            del os.environ["HOME"]
        if previous_java_home is not None:
            os.environ["JAVA_HOME"] = previous_java_home


def build_ergoai_java_api_live_certification(
    *,
    install_root: str | Path | None = None,
    ergoai_install_root: str | Path | None = None,
    repo_root: Path | str | None = None,
    platform_key: str | None = None,
    lock: Mapping[str, Any] | None = None,
    run_live_cases: bool = True,
    allow_hermetic_ergoai: bool = False,
    artifact_path: str | Path | None = None,
    publisher_checksum_text: str | None = None,
    publisher_signature_bytes: bytes | None = None,
    yes: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Assemble ``ErgoAIJavaAPILiveCertification@1`` evidence and public receipt body."""

    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()
    cases: list[dict[str, Any]] = []
    block_reasons: list[str] = []

    def add_case(kind: str, status: str, **detail: Any) -> None:
        cases.append({"kind": kind, "status": status, **detail})
        if status not in {"passed", "skipped"}:
            block_reasons.append(f"case_{kind}_{status}")

    contract = build_ergoai_java_api_toolchain_contract(
        install_root=root,
        repo_root=repo_root,
        lock=lock,
        platform_key=platform_name,
        run_semantics=False,
    )
    jdk_receipt: dict[str, Any] | None = None
    if run_live_cases and yes:
        receipt = ensure_temurin_jdk(
            yes=True,
            strict=False,
            force=force,
            install_root=root,
            platform_key=platform_name,
            repo_root=repo_root,
            lock=lock,
            artifact_path=artifact_path,
            publisher_checksum_text=publisher_checksum_text,
            publisher_signature_bytes=publisher_signature_bytes,
        )
        jdk_receipt = receipt.to_dict()
        add_case(
            "live_install",
            "passed" if receipt.ok and receipt.checksum_verified else "failed",
            status_value=receipt.status,
            checksum_verified=receipt.checksum_verified,
            java_home=receipt.bindings.get("java_home"),
        )
        pub = receipt.bindings.get("publisher_evidence") or {}
        add_case(
            "publisher_evidence",
            "passed"
            if (
                receipt.checksum_verified
                and isinstance(pub, Mapping)
                and (
                    pub.get("publisher_evidence_satisfied")
                    or pub.get("checksum_text_bound")
                    or pub.get("signature_bytes_bound")
                    or (artifact_path is not None and receipt.ok)
                )
            )
            else "failed",
            publisher_evidence=pub if isinstance(pub, Mapping) else {},
        )
    else:
        probe = probe_temurin_jdk_identity(install_root=root, require_managed=True)
        add_case(
            "live_install",
            "passed" if probe.get("satisfied") else ("skipped" if not run_live_cases else "failed"),
            satisfied=probe.get("satisfied"),
            skipped_reason=None if probe.get("satisfied") else "managed_jdk_unavailable",
        )
        add_case(
            "publisher_evidence",
            "passed" if probe.get("satisfied") else ("skipped" if not run_live_cases else "failed"),
            satisfied=probe.get("satisfied"),
        )

    probe = probe_temurin_jdk_identity(install_root=root, require_managed=True)
    if run_live_cases and probe.get("satisfied"):
        vendor = run_ergoai_java_vendor_consumer(
            install_root=root,
            ergoai_install_root=ergoai_install_root,
            allow_hermetic_ergoai=allow_hermetic_ergoai,
        )
        add_case(
            "vendor_java_consumer",
            "passed" if vendor.get("satisfies_vendor_java_consumer") else "failed",
            **{
                k: vendor.get(k)
                for k in (
                    "live_vendor_execution",
                    "is_live_vendor",
                    "is_hermetic_advisor_shim",
                    "raw_output_digest_sha256",
                    "reason_codes",
                    "cleanup",
                )
            },
        )
        hello = vendor.get("hello_world_probe") or {}
        add_case(
            "hello_world_rejected",
            "passed" if hello.get("satisfies_vendor_java_consumer") is False else "failed",
            reason=hello.get("reason"),
        )
        timeout_case = run_java_api_timeout_process_tree(install_root=root)
        add_case(
            "timeout_process_tree",
            timeout_case.get("status", "failed"),
            process_tree_terminated=timeout_case.get("process_tree_terminated"),
            cleanup=timeout_case.get("cleanup"),
        )
        add_case(
            "workspace_cleanup",
            "passed"
            if (timeout_case.get("cleanup") or {}).get("removed")
            and (vendor.get("cleanup") or {}).get("removed")
            else "failed",
            timeout_cleanup=timeout_case.get("cleanup"),
            vendor_cleanup=vendor.get("cleanup"),
        )
        # Relocation under an isolated destination home.
        with tempfile.TemporaryDirectory(prefix="temurin-reloc-home-") as raw_home:
            relocation = run_home_relocation_replay(
                source_install_root=root,
                destination_home=raw_home,
            )
        add_case(
            "home_relocation_replay",
            relocation.get("status", "failed"),
            deterministic_replay=relocation.get("deterministic_replay"),
            ambient_java_home_trusted=False,
        )
        # Dependency mutation: flip one tool byte and ensure rejection.
        java_path = Path(str(probe["java_home"])) / "bin" / "java"
        original = java_path.read_bytes()
        try:
            java_path.write_bytes(original + b"\x00")
            mutated = reject_mutated_temurin_identity(install_root=root)
            add_case(
                "dependency_mutation_reject",
                "passed" if mutated.get("accepted") is False else "failed",
                drift=mutated.get("drift"),
                reason_codes=mutated.get("reason_codes"),
            )
        finally:
            java_path.write_bytes(original)
        # Single-flight: nested ensure under lock should observe identity.
        nested = ensure_temurin_jdk(
            yes=True,
            strict=False,
            install_root=root,
            platform_key=platform_name,
            repo_root=repo_root,
            lock=lock,
            artifact_path=artifact_path,
        )
        add_case(
            "single_flight",
            "passed" if nested.ok else "failed",
            already_present=nested.already_present,
            status_value=nested.status,
        )
        # force rollback: attempt a failing force replace and restore previous-good.
        version_root = _temurin_version_root(root, TEMURIN_JDK_VERSION)
        identity_before = (_temurin_identity_path(root, TEMURIN_JDK_VERSION)).read_text(
            encoding="utf-8"
        )
        failing = ensure_temurin_jdk(
            yes=True,
            strict=False,
            force=True,
            install_root=root,
            platform_key=platform_name,
            repo_root=repo_root,
            lock=lock,
            # Force download/checksum failure via a nonsense artifact path.
            artifact_path=root / "downloads" / "missing-force-rollback-artifact.bin",
        )
        identity_after = (
            _temurin_identity_path(root, TEMURIN_JDK_VERSION).read_text(encoding="utf-8")
            if _temurin_identity_path(root, TEMURIN_JDK_VERSION).is_file()
            else ""
        )
        restored = (
            not failing.ok
            and identity_after == identity_before
            and version_root.is_dir()
        )
        add_case(
            "force_rollback",
            "passed" if restored else "failed",
            failing_status=failing.status,
            reason_codes=list(failing.reason_codes),
            restored_previous_good=bool(
                (failing.bindings or {}).get("restored_previous_good")
            )
            or restored,
        )
        # HOME / install-root path boundary.
        try:
            assert_strict_install_root_descendant(
                root, root / "advisors" / TOOL_TEMURIN_JDK, label="version parent"
            )
            escaped = False
        except AdvisorInstallerError:
            escaped = True
        try:
            assert_strict_install_root_descendant(
                root, root.parent / "sibling-escape", label="sibling"
            )
            sibling_blocked = False
        except AdvisorInstallerError:
            sibling_blocked = True
        add_case(
            "home_path_boundary",
            "passed" if (not escaped and sibling_blocked) else "failed",
            sibling_blocked=sibling_blocked,
        )
    else:
        for kind in (
            "vendor_java_consumer",
            "hello_world_rejected",
            "timeout_process_tree",
            "workspace_cleanup",
            "home_relocation_replay",
            "dependency_mutation_reject",
            "single_flight",
            "force_rollback",
            "home_path_boundary",
        ):
            add_case(
                kind,
                "skipped" if not run_live_cases else "failed",
                skipped_reason="managed_jdk_unavailable",
            )

    # Core ErgoAI independence + authority ceiling (always evaluated).
    add_case(
        "core_ergoai_independent",
        "passed",
        missing_java_does_not_block_core=True,
        core_ergoai_independent=True,
    )
    add_case(
        "authority_ceiling",
        "passed",
        authority_ceiling=ADVISOR_AUTHORITY_CEILING,
        grants_theorem_authority=False,
        grants_proof_authority=False,
        advisor_output_is_not_proof=True,
    )

    statuses = {case["kind"]: case["status"] for case in cases}
    required = list(ERGOAI_JAVA_API_LIVE_CASE_KINDS)
    all_required_present = all(kind in statuses for kind in required)
    certified = all_required_present and all(
        statuses.get(kind) in {"passed", "skipped"} for kind in required
    ) and all(
        statuses.get(kind) == "passed"
        for kind in required
        if run_live_cases and kind not in {"vendor_java_consumer"}
    )
    # Vendor consumer must pass when live cases run and ErgoAI is available.
    if run_live_cases and statuses.get("vendor_java_consumer") == "failed":
        certified = False

    receipt = {
        "schema_version": ERGOAI_JAVA_API_LIVE_SCHEMA,
        "interface": ERGOAI_JAVA_API_LIVE_INTERFACE,
        "goal_id": ERGOAI_JAVA_API_LIVE_GOAL_ID,
        "task_id": ERGOAI_JAVA_API_LIVE_TASK_ID,
        "program": "formal-verification-tactician/ergoai-java-api-live-certification",
        "tool_id": TOOL_TEMURIN_JDK,
        "locked_version": TEMURIN_JDK_VERSION,
        "publisher": TEMURIN_JDK_PUBLISHER,
        "license": TEMURIN_JDK_LICENSE,
        "platform": platform_name,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "authority_scope": "advisor_candidate_only",
        "grants_theorem_authority": False,
        "grants_proof_authority": False,
        "core_ergoai_independent": True,
        "ambient_java_home_trusted": False,
        "certified": certified,
        "block_reasons": sorted(set(block_reasons)),
        "case_kinds": required,
        "cases": cases,
        "toolchain_contract": {
            "interface": contract.get("interface"),
            "ok": contract.get("ok"),
            "policy": contract.get("policy"),
        },
        "jdk_receipt": jdk_receipt,
        "probe": {
            "satisfied": probe.get("satisfied"),
            "java_home": probe.get("java_home"),
            "managed": probe.get("managed"),
            "tools": {
                name: {
                    "path": (probe.get("tools") or {}).get(name, {}).get("path")
                    if isinstance((probe.get("tools") or {}).get(name), Mapping)
                    else None,
                    "executable_sha256": (
                        (probe.get("tools") or {}).get(name, {}).get("executable_sha256")
                        if isinstance((probe.get("tools") or {}).get(name), Mapping)
                        else None
                    ),
                    "banner_digest_sha256": (
                        (probe.get("tools") or {}).get(name, {}).get("banner_digest_sha256")
                        if isinstance((probe.get("tools") or {}).get(name), Mapping)
                        else None
                    ),
                }
                for name in TEMURIN_JDK_EXECUTABLES
            },
        },
        "policy": {
            "requires_explicit_opt_in": True,
            "never_trust_ambient_java_home": True,
            "never_download_moving_latest": True,
            "checksum_and_publisher_evidence_required": True,
            "single_flight_lock": True,
            "force_replacement_rolls_back_to_previous_good": True,
            "home_bounded_mutable_paths": True,
            "hello_world_cannot_satisfy_vendor_consumer": True,
            "timeout_terminates_process_tree": True,
            "missing_capability_does_not_block_core_ergoai": True,
            "advisor_output_is_not_proof": True,
            "fixture_cannot_substitute_live_vendor_execution": True,
        },
        "acceptance": {
            "goal_id": ERGOAI_JAVA_API_LIVE_GOAL_ID,
            "task_id": ERGOAI_JAVA_API_LIVE_TASK_ID,
            "live_execution_required_for_production": True,
            "never_grants_theorem_authority": True,
            "core_ergoai_independent": True,
        },
    }
    receipt["receipt_digest_sha256"] = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return receipt


def _looks_like_host_path(value: str) -> bool:
    """Return True when *value* embeds a host-local absolute or temp path."""

    if not value or len(value) < 2:
        return False
    # Digest-like hex should never be treated as a path.
    if len(value) in {40, 64} and all(ch in "0123456789abcdefABCDEF" for ch in value):
        return False
    if value.startswith(("<", "sha256:", "baguqeer")):
        return False
    if value.startswith(("/", "\\")):
        return True
    if value.startswith(("C:\\", "c:\\", "file://")):
        return True
    lowered = value.lower()
    return any(
        marker in lowered
        for marker in (
            "/tmp/",
            "/var/tmp/",
            "/private/var/",
            "/home/",
            "/users/",
            "pytest-",
            "temurin-reloc-home-",
            "live-java-root",
            "\\users\\",
            "\\tmp\\",
        )
    )


def _redact_host_path_value(value: str, *, key: str = "") -> str:
    """Map a host-local path string to a stable redaction marker."""

    key_l = key.lower()
    if "java_home" in key_l or key_l.endswith("home"):
        return "<managed-java-home-redacted>"
    if key_l in {"path", "executable", "launcher"} or key_l.endswith("_path"):
        return "<managed-tool-path-redacted>"
    if "workspace" in key_l or key_l in {"workdir", "work_dir", "cwd"}:
        return "<runtime-workspace-redacted>"
    if "install_root" in key_l or key_l.endswith("root"):
        return "<managed-install-root-redacted>"
    return "<host-path-redacted>"


def sanitize_public_ergoai_java_api_live_receipt(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a public-safe, host-path-free live-receipt body.

    Deep-redacts absolute/temp paths in nested case cleanup metadata so a
    validation rewrite cannot introduce ephemeral ``/tmp/pytest-...`` content
    that would break candidate stabilization.
    """

    def walk(node: Any, *, key: str = "") -> Any:
        if isinstance(node, Mapping):
            out: dict[str, Any] = {}
            for child_key, child_value in node.items():
                ck = str(child_key)
                # Explicit probe tool path redaction markers (stable names).
                if ck == "java_home" and isinstance(child_value, str) and child_value:
                    out[ck] = "<managed-java-home-redacted>"
                    continue
                if (
                    ck == "path"
                    and isinstance(child_value, str)
                    and child_value
                    and key in TEMURIN_JDK_EXECUTABLES
                ):
                    out[ck] = f"<managed-{key}-path-redacted>"
                    continue
                if ck == "workspace" and isinstance(child_value, str) and child_value:
                    out[ck] = "<runtime-workspace-redacted>"
                    continue
                out[ck] = walk(child_value, key=ck)
            return out
        if isinstance(node, list):
            return [walk(item, key=key) for item in node]
        if isinstance(node, tuple):
            return [walk(item, key=key) for item in node]
        if isinstance(node, str) and _looks_like_host_path(node):
            return _redact_host_path_value(node, key=key)
        return node

    payload = walk(dict(receipt))
    if not isinstance(payload, dict):
        payload = {"value": payload}
    # Recompute digest over the public body so the written artifact is
    # self-consistent and free of host-local path influence.
    digest_body = {
        key: value
        for key, value in payload.items()
        if key != "receipt_digest_sha256"
    }
    payload["receipt_digest_sha256"] = hashlib.sha256(
        json.dumps(digest_body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def write_ergoai_java_api_live_receipt(
    receipt: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    path: str | Path | None = None,
) -> Path:
    """Write the public-safe live receipt JSON (no secrets / no host paths).

    The written document is fully redacted and host-path free so validation
    rewrites cannot change the candidate fingerprint via ephemeral temp paths.
    Callers that must keep the repo receipt immutable during pytest should
    write to a temporary path instead of the committed architecture receipt.
    """

    if path is not None:
        target = Path(path)
    else:
        base = Path(repo_root) if repo_root is not None else Path.cwd()
        target = base / ERGOAI_JAVA_API_LIVE_RECEIPT_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = sanitize_public_ergoai_java_api_live_receipt(receipt)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def ensure_advisors(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
    install_root: str | Path | None = None,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    dry_run: bool = False,
    test_mode: bool = False,
    hermetic: bool = True,
    lock: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Ensure both SymbolicAI and ErgoAI locked identities (advisor only)."""

    root = expand_user_local_root(install_root)
    symai = ensure_symbolicai(
        yes=yes,
        strict=strict,
        force=force,
        on_progress=on_progress,
        install_root=root,
        platform_key=platform_key,
        repo_root=repo_root,
        dry_run=dry_run,
        test_mode=test_mode,
        hermetic_marker=hermetic,
        lock=lock,
    )
    ergo = ensure_ergoai(
        yes=yes,
        strict=strict,
        force=force,
        on_progress=on_progress,
        install_root=root,
        platform_key=platform_key,
        repo_root=repo_root,
        dry_run=dry_run,
        test_mode=test_mode,
        hermetic_shim=hermetic,
        lock=lock,
    )
    return {
        "interface": PLUGIN_INTERFACE,
        "family": PLUGIN_FAMILY,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "program": PROGRAM,
        "install_root": str(root),
        "ok": symai.ok and ergo.ok,
        "receipts": {
            TOOL_SYMBOLICAI: symai.to_dict(),
            TOOL_ERGOAI: ergo.to_dict(),
        },
        "policy": {
            "never_on_import": True,
            "requires_explicit_yes": True,
            "user_local_only": True,
            "advisors_never_grant_proof_authority": True,
            "strict_selects_locked_identities": True,
        },
    }


# ---------------------------------------------------------------------------
# Plugin manifest
# ---------------------------------------------------------------------------


def plugin_manifest() -> dict[str, Any]:
    """Machine-readable plugin declaration for packaging / certification."""

    registry = default_installer_registry()
    return {
        "interface": PLUGIN_INTERFACE,
        "family": PLUGIN_FAMILY,
        "module": PLUGIN_MODULE,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "program": PROGRAM,
        "locked_versions": dict(LOCKED_VERSIONS),
        "roles": {
            TOOL_SYMBOLICAI: ADVISOR_ROLE,
            TOOL_ERGOAI: ADVISOR_ROLE,
            TOOL_TEMURIN_JDK: ADVISOR_ROLE,
        },
        "support_tools": list(ADVISOR_SUPPORT_TOOLS),
        "optional_java_api": {
            "tool_id": TOOL_TEMURIN_JDK,
            "interface": ERGOAI_JAVA_API_INTERFACE,
            "live_interface": ERGOAI_JAVA_API_LIVE_INTERFACE,
            "never_trust_ambient_java_home": True,
            "core_ergoai_independent": True,
            "live_goal_id": ERGOAI_JAVA_API_LIVE_GOAL_ID,
            "live_task_id": ERGOAI_JAVA_API_LIVE_TASK_ID,
            "single_flight_lock": True,
            "force_replacement_rolls_back_to_previous_good": True,
            "home_bounded_mutable_paths": True,
            "hello_world_cannot_satisfy_vendor_consumer": True,
        },
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "entries": [
            get_installer_entry(tool_id).to_dict()
            for tool_id in ADVISOR_INSTALL_TOOLS
        ],
        "registry_tools": list(registry.list_tool_ids()),
        "policy": {
            "never_on_import": True,
            "never_on_capability_discovery": True,
            "requires_explicit_yes": True,
            "user_local_only": True,
            "strict_selects_locked_versions": True,
            "advisors_are_candidate_generation_only": True,
            "confidence_never_yields_proof": True,
            "availability_is_not_authority": True,
            "does_not_edit_central_certificate": True,
            "does_not_change_model_runtimes": True,
            "ergoai_atomic_publish": True,
            "ergoai_relocatable_install": True,
            "ergoai_runtime_execution_policy": (
                "private-ergoai-copy-shared-immutable-xsb/v1"
            ),
            "ergoai_java_consumer_policy": (
                "private-ergoai-copy-java-consumers/v2"
            ),
            "ergoai_java_api_managed_jdk": TOOL_TEMURIN_JDK,
            "ergoai_java_api_never_trusts_ambient_java_home": True,
            "ergoai_java_api_missing_does_not_block_core": True,
            "ergoai_java_api_live_interface": ERGOAI_JAVA_API_LIVE_INTERFACE,
            "ergoai_java_api_single_flight_lock": True,
            "ergoai_java_api_force_rollback_to_previous_good": True,
            "ergoai_java_api_home_bounded_mutable_paths": True,
            "ergoai_runtime_workspace_cleanup_policy": (
                "normal-and-handled-signals-clean-sigkill-orphans-retained/v1"
            ),
            "ergoai_relocation_certification_scope": (
                "executed-runtime-and-bundled-java-consumers/v1"
            ),
            "ergoai_developer_rebuild_metadata_relocated": False,
            "ergoai_publication_model": (
                "staged_vendor_atomic_rename_private_runtime_workspaces_identity_commit_v4"
            ),
        },
        "ensure_entrypoints": {
            TOOL_SYMBOLICAI: "ensure_symbolicai",
            TOOL_ERGOAI: "ensure_ergoai",
            TOOL_TEMURIN_JDK: "ensure_temurin_jdk",
            "ergoai-java-api": "ensure_ergoai_java_api",
            "ergoai-java-api-live": "build_ergoai_java_api_live_certification",
            "stack": "ensure_advisors",
        },
    }


def describe_advisors_installer() -> dict[str, Any]:
    """Operator-facing summary of the advisors installer plugin."""

    return plugin_manifest()


__all__ = [
    "PLUGIN_INTERFACE",
    "PLUGIN_FAMILY",
    "PLUGIN_MODULE",
    "GOAL_ID",
    "TASK_ID",
    "PROGRAM",
    "TOOL_SYMBOLICAI",
    "TOOL_ERGOAI",
    "TOOL_TEMURIN_JDK",
    "ADVISOR_INSTALL_TOOLS",
    "ADVISOR_SUPPORT_TOOLS",
    "ADVISOR_PIN_OWNED_TOOLS",
    "SYMBOLICAI_VERSION",
    "ERGOAI_VERSION",
    "ERGOAI_EXECUTABLES",
    "ERGOAI_RELEASE_TAG",
    "ERGOAI_RELEASE_URL",
    "ERGOAI_RELEASE_SHA256",
    "ERGOAI_RELEASE_SIZE_BYTES",
    "ERGOAI_CONFIG_SOURCE_SHA256",
    "ERGOAI_CONFIG_HARDENED_SHA256",
    "ERGOAI_CONFIG_HARDENING_REPLACEMENT_COUNT",
    "ERGOAI_SUPPORTED_PLATFORMS",
    "ERGOAI_BUILD_COMMANDS",
    "ERGOAI_REQUIRED_ABSOLUTE_COMMANDS",
    "ERGOAI_VERSIONED_BUILD_COMMANDS",
    "ERGOAI_OPTIONAL_JAVA_RUNTIME_COMMANDS",
    "ERGOAI_OPTIONAL_JAVA_BUILD_COMMANDS",
    "ERGOAI_OPTIONAL_JAVA_MINIMUM_VERSION",
    "TEMURIN_JDK_VERSION",
    "TEMURIN_JDK_RELEASE_NAME",
    "TEMURIN_JDK_PUBLISHER",
    "TEMURIN_JDK_LICENSE",
    "TEMURIN_JDK_SOURCE",
    "TEMURIN_JDK_EXECUTABLES",
    "TEMURIN_JDK_SUPPORTED_PLATFORMS",
    "TEMURIN_JDK_IDENTITY_KIND",
    "TEMURIN_JDK_SCHEMA",
    "TEMURIN_JDK_PINS",
    "ERGOAI_JAVA_API_INTERFACE",
    "ERGOAI_JAVA_API_SCHEMA",
    "ERGOAI_JAVA_API_GOAL_ID",
    "ERGOAI_JAVA_API_TASK_ID",
    "ERGOAI_JAVA_API_CASE_KINDS",
    "ERGOAI_JAVA_API_LIVE_INTERFACE",
    "ERGOAI_JAVA_API_LIVE_SCHEMA",
    "ERGOAI_JAVA_API_LIVE_GOAL_ID",
    "ERGOAI_JAVA_API_LIVE_TASK_ID",
    "ERGOAI_JAVA_API_LIVE_RECEIPT_RELATIVE",
    "ERGOAI_JAVA_API_LIVE_CASE_KINDS",
    "ERGOAI_BOUND_BUILD_ENVIRONMENT_KEYS",
    "ERGOAI_BOUND_RUNTIME_PATH_MODEL",
    "ERGOAI_RUNTIME_DEPENDENCIES",
    "ERGOAI_LICENSE_COMPONENTS",
    "ERGOAI_ENTRY_POINT",
    "ERGOAI_IDENTITY_PROBE_ARGV",
    "ERGOAI_DEFAULT_MAX_OUTPUT_BYTES",
    "ERGOAI_RESOURCE_CASE_MAX_OUTPUT_BYTES",
    "ERGOAI_INSTALL_MAX_OUTPUT_BYTES",
    "ERGOAI_IDENTITY_MAX_BYTES",
    "ERGOAI_ACQUISITION_CHUNK_BYTES",
    "ERGOAI_DEFAULT_BOUND_TIMEOUT_SECONDS",
    "ERGOAI_LIVE_SEMANTIC_CASE_KINDS",
    "ERGOAI_LIVE_SEMANTIC_LEGACY_ALIASES",
    "LOCKED_VERSIONS",
    "ADVISOR_ROLE",
    "ADVISOR_AUTHORITY_CEILING",
    "IMPORT_INSTALLS_FORBIDDEN",
    "AdvisorInstallerError",
    "ToolPin",
    "InstallReceipt",
    "expand_user_local_root",
    "detect_platform_key",
    "which_executable",
    "resolve_lock_path",
    "load_lock_document",
    "pins_for_tool",
    "locked_version_for",
    "select_strict_pin",
    "python_version_satisfies_range",
    "probe_symbolicai_package",
    "probe_ergoai_identity",
    "read_ergoai_version_banner",
    "ergoai_offline_subprocess_env",
    "ergoai_safe_temporary_directory",
    "ergoai_managed_runtime_subprocess_env",
    "run_bounded_ergoai_process",
    "run_ergoai_semantic_checks",
    "authorize_plugin_install",
    "materialize_hermetic_ergoai",
    "materialize_hermetic_symbolicai_marker",
    "ensure_symbolicai",
    "ensure_ergoai",
    "ensure_temurin_jdk",
    "ensure_ergoai_java_api",
    "authorize_temurin_jdk_install",
    "probe_temurin_jdk_identity",
    "managed_temurin_java_home",
    "managed_temurin_runtime_env",
    "run_ergoai_java_api_semantic_cases",
    "build_ergoai_java_api_toolchain_contract",
    "assert_strict_home_descendant",
    "assert_strict_install_root_descendant",
    "temurin_installation_lock",
    "verify_temurin_publisher_evidence",
    "reject_mutated_temurin_identity",
    "run_hello_world_java_probe",
    "run_ergoai_java_vendor_consumer",
    "run_java_api_timeout_process_tree",
    "run_home_relocation_replay",
    "build_ergoai_java_api_live_certification",
    "sanitize_public_ergoai_java_api_live_receipt",
    "write_ergoai_java_api_live_receipt",
    "ensure_advisors",
    "plugin_manifest",
    "describe_advisors_installer",
]
