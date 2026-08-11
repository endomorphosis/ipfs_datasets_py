"""Lazy installer for optional external theorem prover dependencies.

The prover bridges import cleanly without installing anything.  When a bridge
is explicitly requested and its dependency is missing, this module can perform
a single best-effort install attempt. Normal bridge imports remain opt-in;
native execution paths can request automatic installation and always emit
progress events so a first-use download or build is not silent.

Public transactional facade (FVT-G216 / ``LogicVerificationLazyInstaller@1``)
---------------------------------------------------------------------------
``reviewed_installer_inventory``, ``plan_reviewed_install``, and
``execute_reviewed_install`` form the explicit, platform-aware lifecycle used by
``LogicVerificationAPI.install_provider``.  Inventory/plan/deny/dry-run/offline
paths never import a family plugin.  Live installs authorize one registry entry,
import exactly one reviewed callable, and return structured evidence
(platform, dependency, license, checksum, artifact, executable, rollback,
semantic probe).  Incomplete rollback or identity evidence cannot certify or
promote capability/semantic authority; failed publication keeps prior installs.

Environment variables:
- IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=1 enables the full optional portfolio.
  The reviewed first-use portfolio (Runtime MTL vendor, ATP/SMT, TLA, Tamarin,
  Soufflé/SecPAL, hyperproperty engines, ErgoAI) is default-on without this
  flag for package consumers; set LAZY_INSTALL_PROVERS=0 or per-prover
  LAZY_INSTALL_<PROVER>=0 to opt out.
- IPFS_DATASETS_PY_LAZY_INSTALL_<PROVER>=0/1 overrides a prover.
- IPFS_DATASETS_PY_LAZY_INSTALL_STRICT=1 raises on installer failure.
- IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS=1 permits interactive sudo for Coq.
- IPFS_DATASETS_PY_ERGOAI_GIT_URL overrides the ErgoAI/ErgoEngine source repo.
- IPFS_DATASETS_PY_ERGOAI_RELEASE_URL overrides the official ErgoAI .run URL.
- IPFS_DATASETS_PY_ERGOAI_INSTALL_DIR sets the user-local ErgoAI install dir.
- IPFS_DATASETS_PY_ERGOAI_INSTALL_COMMAND runs a custom ErgoAI installer command.
- IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT controls user-local native solver
  artifacts (default: ~/.local/share/ipfs_datasets_py/theorem-provers).
- IPFS_DATASETS_PY_<PROVER>_EXECUTABLE selects an explicit native executable
  or a launcher for a portable runtime such as a Node-hosted WebAssembly build.
- IPFS_DATASETS_PY_<SOLVER>_INSTALL_COMMAND overrides a native solver install
  on platforms without a packaged release artifact.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import logging
import os
import platform as platform_module
import shutil
import stat
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ipfs_datasets_py.logic.common.feature_detection import (
    clear_feature_detection_cache,
    minimal_imports_enabled,
)

logger = logging.getLogger(__name__)

_ATTEMPTED: set[str] = set()
_INSTALL_RESULTS: dict[str, bool] = {}
_INSTALL_LOCKS: dict[str, threading.Lock] = {}
_INSTALL_LOCKS_GUARD = threading.Lock()

_ALIASES = {
    "z3": "z3",
    "z3_solver": "z3",
    "z3prover": "z3",
    "cvc5": "cvc5",
    "cvc5_prover": "cvc5",
    "vampire": "vampire",
    "vampire_prover": "vampire",
    "e": "eprover",
    "e_prover": "eprover",
    "eprover": "eprover",
    "lean": "lean",
    "lean_prover": "lean",
    "lake": "lean",
    "coq": "coq",
    "coq_prover": "coq",
    "coqc": "coq",
    "coqtop": "coq",
    "rocq": "coq",
    "rocq_prover": "coq",
    "rocq-prover": "coq",
    "isabelle": "isabelle",
    "isabelle_prover": "isabelle",
    "apalache": "apalache",
    "apalache_mc": "apalache",
    "apalache-mc": "apalache",
    "tlc": "tlc",
    "tlc2": "tlc",
    "tla2tools": "tlc",
    "tamarin": "tamarin",
    "tamarin_prover": "tamarin",
    "tamarin-prover": "tamarin",
    "maude": "maude",
    "proverif": "proverif",
    "symbolicai": "symbolicai",
    "symbolic_ai": "symbolicai",
    "symbolicai_prover": "symbolicai",
    "symbolic_ai_prover": "symbolicai",
    "symai": "symbolicai",
    "ergo": "ergoai",
    "ergoai": "ergoai",
    "ergo_ai": "ergoai",
    "ergoengine": "ergoai",
    "ergo_engine": "ergoai",
    "runergo": "ergoai",
    "runergo.sh": "ergoai",
    "runergo_sh": "ergoai",
    "temurin_jdk": "temurin-jdk",
    "temurin": "temurin-jdk",
    "jdk": "temurin-jdk",
    "openjdk": "temurin-jdk",
    "eclipse_temurin": "temurin-jdk",
    "ergoai_java_api": "temurin-jdk",
    "ergoai_java": "temurin-jdk",
    "java_api": "temurin-jdk",
    "hyperltl": "hyperltl",
    "hyper_ltl": "hyperltl",
    "autohyper": "autohyper",
    "auto_hyper": "autohyper",
    "mchyper": "mchyper",
    "mc_hyper": "mchyper",
    "souffle": "souffle",
    "secpal": "secpal",
    "runtime_mtl_external": "runtime-mtl-external",
    "runtime_mtl": "runtime-mtl-external",
    "mtl_monitor": "runtime-mtl-external",
    "zkp_circuit": "zkp-circuit",
    "zkp": "zkp-circuit",
}

_ENV_NAMES = {
    "z3": "Z3",
    "cvc5": "CVC5",
    "vampire": "VAMPIRE",
    "eprover": "EPROVER",
    "lean": "LEAN",
    "coq": "COQ",
    "isabelle": "ISABELLE",
    "apalache": "APALACHE",
    "tlc": "TLC",
    "tamarin": "TAMARIN",
    "maude": "MAUDE",
    "proverif": "PROVERIF",
    "symbolicai": "SYMBOLICAI",
    "ergoai": "ERGOAI",
    "temurin-jdk": "TEMURIN_JDK",
    "hyperltl": "HYPERLTL",
    "autohyper": "AUTOHYPER",
    "mchyper": "MCHYPER",
    "souffle": "SOUFFLE",
    "secpal": "SECPAL",
    "runtime-mtl-external": "RUNTIME_MTL_EXTERNAL",
}

_PROVER_EXECUTABLES: dict[str, tuple[str, ...]] = {
    "apalache": ("apalache-mc", "apalache"),
    "tlc": ("tlc", "tlc2", "tla2tools"),
    "tamarin": ("tamarin-prover",),
    "maude": ("maude",),
    "proverif": ("proverif",),
    "lean": ("lean",),
    "coq": ("coqc",),
    "isabelle": ("isabelle",),
    "cvc5": ("cvc5",),
    "vampire": ("vampire",),
    "eprover": ("eprover",),
    "ergoai": ("ergoai", "ergo", "runErgo.sh", "runergo"),
    "temurin-jdk": ("java", "javac", "jar"),
    "hyperltl": ("hyperltl", "hyperltl-sat"),
    "autohyper": ("autohyper", "AutoHyper"),
    "mchyper": ("mchyper", "MCHyper"),
    "souffle": ("souffle",),
    "secpal": ("secpal",),
    "runtime-mtl-external": ("runtime-mtl", "runtime-mtl-external", "mtl-monitor"),
}

# These providers have reviewed family installers in
# FormalVerificationInstallerRegistry@1.  Explicit lazy-install requests
# always use the real vendor path (never hermetic shadow/shim substitutes).
_REVIEWED_EXTERNAL_INSTALLERS = frozenset(
    {
        "hyperltl",
        "autohyper",
        "mchyper",
        "souffle",
        "secpal",
        "runtime-mtl-external",
        "ergoai",
        "temurin-jdk",
    }
)

# First-use portfolio: install automatically when a package consumer needs the
# executable and it is missing (including reconstruction kernels so theorem
# provers run end-to-end after package install).
_DEFAULT_ON_FIRST_USE_INSTALLERS = frozenset(
    {
        "ergoai",
        "runtime-mtl-external",
        "z3",
        "cvc5",
        "vampire",
        "eprover",
        "tlc",
        "apalache",
        "proverif",
        "tamarin",
        "maude",
        "souffle",
        "secpal",
        "hyperltl",
        "autohyper",
        "mchyper",
        "temurin-jdk",
        "lean",
        "coq",
        "isabelle",
    }
)

LOGIC_VERIFICATION_LAZY_INSTALLER_INTERFACE = "LogicVerificationLazyInstaller@1"
LOGIC_VERIFICATION_INSTALL_RECEIPT_SCHEMA = "logic-verification-install-receipt/v1"
_PROVIDER_INSTALLER_OPTIONS: dict[str, frozenset[str]] = {
    "apalache": frozenset({"java_executable"}),
    "tlc": frozenset({"java_executable"}),
    "zkp-circuit": frozenset({"deployment_lock_path"}),
}
_FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "secret",
        "secrets",
        "password",
        "passwords",
        "credential",
        "credentials",
        "private_key",
        "private_key_bytes",
        "private_witness",
        "raw_witness",
        "hidden_witness",
        "witness_bytes",
        "proving_key",
        "proving_key_bytes",
        "verification_key_bytes",
        "trapdoor",
        "toxic_waste",
        "coordinator_seed",
        "authorization_token",
        "access_token",
        "refresh_token",
        "api_key",
        "bearer",
        "stdin",
        "private",
        "raw",
    }
)
_MAX_OPERATOR_BINDING_BYTES = 1024 * 1024
_PROCESS_LOCK_TIMEOUT_SECONDS = 30.0


def _platform_key() -> str:
    system = platform_module.system().lower()
    machine = platform_module.machine().lower()
    if machine in {"amd64", "x86_64"}:
        machine = "x86_64"
    elif machine in {"arm64", "aarch64"}:
        machine = "aarch64" if system == "linux" else "arm64"
    return f"{system}-{machine}"


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_exact_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be a boolean")
    return value


def _normalized_key(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _configured_user_install_root() -> Path:
    configured_values = {
        str(value).strip()
        for value in (
            os.environ.get("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT"),
            os.environ.get("IPFS_DATASETS_PY_THEOREM_PROVERS_ROOT"),
        )
        if str(value or "").strip()
    }
    if len(configured_values) > 1:
        raise ValueError("configured theorem-prover roots disagree")
    home = Path.home().expanduser().resolve()
    if configured_values:
        configured = Path(next(iter(configured_values))).expanduser()
        if not configured.is_absolute():
            raise ValueError("configured theorem-prover root must be absolute")
        root = configured.resolve()
    else:
        root = home / ".local" / "share" / "ipfs_datasets_py" / "theorem-provers"
    try:
        root.relative_to(home)
    except ValueError as exc:
        raise ValueError(
            "lazy installer root must be user-local; external sealed roots are read-only"
        ) from exc
    if root == home:
        raise ValueError("lazy installer root must not be the home directory")
    return root


def configured_user_install_root() -> Path:
    """Return the validated root used by reviewed lazy installers.

    This public, read-only resolver lets execution adapters bind the launcher
    they select to the same user-local root as the installer.  It deliberately
    performs no directory creation or installer import.
    """

    return _configured_user_install_root()


@contextmanager
def _cross_process_install_lock(provider: str) -> Iterator[dict[str, Any]]:
    """Serialize publication across CLI/MCP/supervisor processes.

    The lock itself lives inside the reviewed user-local prover root.  It is
    acquired only after explicit authorization and uses a bounded wait, so a
    dead or hung peer cannot block an API request indefinitely.
    """

    root = _configured_user_install_root()
    lock_dir = root / ".locks"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("lazy installer root must be a real directory")
    lock_dir.mkdir(mode=0o700, exist_ok=True)
    if lock_dir.is_symlink() or not lock_dir.is_dir():
        raise ValueError("lazy installer lock root must be a real directory")
    safe_provider = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in provider
    )
    path = lock_dir / f"facade-{safe_provider}.lock"
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError("lazy installer lease must be a regular file")
    handle = os.fdopen(descriptor, "a+b")
    deadline = time.monotonic() + _PROCESS_LOCK_TIMEOUT_SECONDS
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt  # pragma: no cover - Windows-only

            while time.monotonic() < deadline:
                try:
                    handle.seek(0)
                    if handle.tell() == 0:
                        handle.write(b"0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl

            while time.monotonic() < deadline:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError:
                    time.sleep(0.05)
        if not acquired:
            raise TimeoutError(f"timed out acquiring installer lease for {provider}")
        yield {
            "cross_process": True,
            "lock_name": path.name,
            "root_binding_sha256": hashlib.sha256(
                str(root).encode("utf-8")
            ).hexdigest(),
        }
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt  # pragma: no cover - Windows-only

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                logger.warning("could not release installer lease for %s", provider)
        handle.close()


def _normalize_installer_options(
    provider: str,
    options: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = dict(options or {})
    allowed = _PROVIDER_INSTALLER_OPTIONS.get(provider, frozenset())
    unsupported = sorted(str(key) for key in raw if key not in allowed)
    if unsupported:
        raise ValueError(
            "unsupported installer options for "
            f"{provider}: {', '.join(unsupported)}"
        )
    actual: dict[str, Any] = {}
    public: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValueError("installer option keys must be strings")
        if key not in {"deployment_lock_path", "java_executable"}:
            raise ValueError(f"installer option {key!r} has no reviewed translation")
        if not isinstance(value, (str, Path)):
            raise ValueError(f"installer option {key} must be a path string")
        text = str(value)
        if not text.strip() or text != text.strip() or "\x00" in text:
            raise ValueError(f"installer option {key} must be a trimmed path without NUL")
        supplied = Path(text).expanduser()
        if supplied.is_symlink():
            raise ValueError(f"installer option {key} must not be a symlink")
        try:
            path = supplied.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"installer option {key} does not exist") from exc
        if not path.is_file():
            raise ValueError(f"installer option {key} must name a regular file")
        if key == "java_executable" and not os.access(path, os.X_OK):
            raise ValueError("java_executable must be executable")
        size = path.stat().st_size
        if key == "deployment_lock_path" and size > _MAX_OPERATOR_BINDING_BYTES:
            raise ValueError("deployment_lock_path exceeds the 1 MiB public-lock limit")
        actual[key] = str(path)
        public[key] = {
            "basename": path.name,
            "size_bytes": size,
            "sha256": _sha256_file(path),
        }
    return actual, public


def reviewed_installer_inventory() -> tuple[dict[str, Any], ...]:
    """Return inert registry metadata without importing installer plugins."""

    from ipfs_datasets_py.logic.backends.installers.registry import (
        list_installer_entries,
    )

    return tuple(entry.to_dict() for entry in list_installer_entries())


def plan_reviewed_install(
    provider_id: str,
    *,
    force: bool = False,
    installer_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded, mutation-free plan for one reviewed provider."""

    from ipfs_datasets_py.logic.backends.installers.registry import (
        get_installer_entry,
    )

    _require_exact_bool(force, "force")
    provider = normalize_prover_name(provider_id)
    _, public_options = _normalize_installer_options(provider, installer_options)
    if provider == "temurin-jdk":
        plan = {
            "interface": LOGIC_VERIFICATION_LAZY_INSTALLER_INTERFACE,
            "provider_id": provider,
            "family": "advisors",
            "installer_module": (
                "ipfs_datasets_py.logic.backends.installers.advisors"
            ),
            "installer_callable": "ensure_temurin_jdk",
            "platform": _platform_key(),
            "license": "GPL-2.0-with-classpath-exception",
            "source": "https://adoptium.net/",
            "identity_kind": "immutable_release_archive",
            "requires_explicit_yes": True,
            "user_local_only": True,
            "requires_checksum_for_managed_artifacts": True,
            "force": force,
            "installer_options": public_options,
            "phases": [
                "authorize",
                "resolve_reviewed_plugin",
                "stage_or_validate",
                "publish",
                "semantic_probe",
            ],
            "mutation_boundary": "after_authorize_and_plugin_resolution",
            "discovery_imports_plugin": False,
            "support_only": True,
            "optional_capability": "ergoai-java-api",
            "never_trust_ambient_java_home": True,
            "core_ergoai_independent": True,
        }
        plan["plan_digest"] = _canonical_digest(plan)
        return plan
    entry = get_installer_entry(provider)
    plan: dict[str, Any] = {
        "interface": LOGIC_VERIFICATION_LAZY_INSTALLER_INTERFACE,
        "provider_id": provider,
        "family": entry.family.value,
        "installer_module": entry.module_path,
        "installer_callable": entry.ensure_name,
        "platform": _platform_key(),
        "license": entry.license,
        "source": entry.source,
        "identity_kind": entry.identity_kind,
        "requires_explicit_yes": entry.requires_explicit_yes,
        "user_local_only": entry.user_local_only,
        "requires_checksum_for_managed_artifacts": (
            entry.requires_checksum_for_managed_artifacts
        ),
        "force": force,
        "installer_options": public_options,
        "phases": [
            "authorize",
            "resolve_reviewed_plugin",
            "stage_or_validate",
            "publish",
            "semantic_probe",
        ],
        "mutation_boundary": "after_authorize_and_plugin_resolution",
        "discovery_imports_plugin": False,
    }
    plan["plan_digest"] = _canonical_digest(plan)
    return plan


def _receipt_payload(result: object) -> dict[str, Any]:
    if isinstance(result, dict):
        payload = dict(result)
    elif hasattr(result, "to_dict") and callable(result.to_dict):
        value = result.to_dict()
        payload = dict(value) if isinstance(value, dict) else {"value": str(value)}
    elif isinstance(result, bool):
        payload = {"status": "installed" if result else "failed", "installed": result}
    else:
        payload = {
            "status": str(getattr(result, "status", "") or "failed"),
            "installed": bool(getattr(result, "installed", False)),
        }
    def public_value(value: object, path: str) -> object:
        if isinstance(value, (bytes, bytearray, memoryview)):
            raise ValueError(f"binary/private material is forbidden at {path}")
        if isinstance(value, dict):
            cleaned: dict[str, object] = {}
            for key, item in value.items():
                key_text = str(key)
                normalized_key = _normalized_key(key_text)
                if normalized_key in _FORBIDDEN_PUBLIC_KEYS:
                    raise ValueError(f"private installer receipt field forbidden at {path}.{key_text}")
                cleaned[key_text] = public_value(item, f"{path}.{key_text}")
            return cleaned
        if isinstance(value, (list, tuple)):
            return [public_value(item, f"{path}[]") for item in value]
        if isinstance(value, Path):
            return str(value)
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        raise ValueError(f"unsupported installer receipt value at {path}")

    normalized = public_value(payload, "plugin_receipt")
    if not isinstance(normalized, dict):
        raise ValueError("installer receipt must normalize to a mapping")
    return normalized


def _real_provider_kwargs(provider: str) -> dict[str, object]:
    if provider in {"hyperltl", "autohyper", "mchyper"}:
        return {"vendor": True, "hermetic_engine": False}
    if provider in {"souffle", "secpal"}:
        return {"vendor": True, "hermetic_shadow": False}
    if provider == "runtime-mtl-external":
        return {"vendor": True, "hermetic_parity_engine": False}
    if provider == "ergoai":
        return {"hermetic_shim": False}
    return {}


def _post_install_capability_probe(provider: str) -> dict[str, Any]:
    """Refresh import/probe caches and report same-process availability."""

    importlib.invalidate_caches()
    clear_feature_detection_cache()
    if provider == "z3":
        available = importlib.util.find_spec("z3") is not None
        return {"available": available, "probe": "python_module:z3"}
    if provider == "symbolicai":
        available = importlib.util.find_spec("symai") is not None
        return {"available": available, "probe": "python_module:symai"}
    if provider == "zkp-circuit":
        return {"available": None, "probe": "deployment_binding_receipt"}
    candidates = _PROVER_EXECUTABLES.get(provider, (provider,))
    executable = next(
        (candidate for candidate in candidates if find_executable(candidate)),
        "",
    )
    return {
        "available": bool(executable),
        "probe": "managed_executable",
        "executable_name": executable,
    }


def _nonempty_mapping(value: object) -> bool:
    return isinstance(value, dict) and bool(value)


def execute_reviewed_install(
    provider_id: str,
    *,
    allow_install: bool = False,
    dry_run: bool = False,
    offline: bool = False,
    force: bool = False,
    strict: bool = False,
    installer_options: dict[str, Any] | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Execute one explicit registry-selected install behind a fail-closed gate.

    Planning, denied authorization, dry-run, and offline paths stop before the
    plugin module is imported.  Live execution imports exactly one reviewed
    callable and records its bounded receipt; generic object truthiness never
    becomes installation evidence.
    """

    allow_install = _require_exact_bool(allow_install, "allow_install")
    dry_run = _require_exact_bool(dry_run, "dry_run")
    offline = _require_exact_bool(offline, "offline")
    force = _require_exact_bool(force, "force")
    strict = _require_exact_bool(strict, "strict")
    if installer_options is not None and not isinstance(installer_options, dict):
        raise ValueError("installer_options must be a dictionary")
    provider = normalize_prover_name(provider_id)
    options, _ = _normalize_installer_options(provider, installer_options)
    plan = plan_reviewed_install(
        provider,
        force=force,
        installer_options=installer_options,
    )
    attempt_id = uuid.uuid4().hex
    base: dict[str, Any] = {
        "schema_version": LOGIC_VERIFICATION_INSTALL_RECEIPT_SCHEMA,
        "interface": LOGIC_VERIFICATION_LAZY_INSTALLER_INTERFACE,
        "provider_id": provider,
        "attempt_id": attempt_id,
        "transaction_id": f"install:{plan['plan_digest'][:24]}:{attempt_id}",
        "plan": plan,
        "dry_run": dry_run,
        "offline": offline,
        "install_attempted": False,
        "mutation_authorized": False,
        "installed": False,
        "certified": False,
        "authority": "none",
    }
    if dry_run:
        return {
            **base,
            "status": "planned",
            "evidence": {
                "authorization": {"allowed": False, "reason": "dry_run"},
                "network": {"allowed": False, "attempted": False},
                "rollback": {"required": True, "attempted": False},
            },
        }
    if not allow_install:
        return {
            **base,
            "status": "authorization_required",
            "evidence": {
                "authorization": {"allowed": False, "reason": "allow_install_required"},
                "network": {"allowed": False, "attempted": False},
            },
        }
    if offline:
        return {
            **base,
            "status": "blocked",
            "evidence": {
                "authorization": {"allowed": False, "reason": "offline_policy"},
                "network": {"allowed": False, "attempted": False},
                "rollback": {"required": True, "attempted": False},
            },
        }
    from ipfs_datasets_py.logic.backends.installers.registry import (
        authorize_installer_entry_install,
    )

    authorized = False
    plugin_resolved = False
    plugin_invoked = False
    mutation_observed = False
    process_lock_evidence: dict[str, Any] = {}
    try:
        if provider == "temurin-jdk":
            module = importlib.import_module(plan["installer_module"])
            ensure = getattr(module, plan["installer_callable"], None)
            if not callable(ensure):
                raise RuntimeError(
                    "reviewed installer "
                    f"{plan['installer_module']}:{plan['installer_callable']} "
                    "is not callable"
                )
            # Support-lifecycle gate (explicit allow already checked above).
            authorize = getattr(module, "authorize_temurin_jdk_install", None)
            if callable(authorize):
                authorize(
                    yes=True,
                    strict=strict,
                    import_context=False,
                    capability_discovery=False,
                    dry_run=False,
                    offline=False,
                    platform_key=plan["platform"],
                )
            authorized = True
            plugin_resolved = True
            entry = None
        else:
            entry = authorize_installer_entry_install(
                provider,
                yes=True,
                explicit_call=True,
                import_context=False,
                capability_discovery=False,
                platform=plan["platform"],
                system_package_mutation=False,
            )
            authorized = True
            module = importlib.import_module(entry.module_path)
            ensure = getattr(module, entry.ensure_name, None)
            if not callable(ensure):
                raise RuntimeError(
                    f"reviewed installer {entry.module_path}:{entry.ensure_name} is not callable"
                )
            plugin_resolved = True
        plugin_progress: Any = None
        if progress is not None:

            def plugin_progress(*progress_args: object) -> None:
                if len(progress_args) == 1:
                    phase = "installing"
                    message = str(progress_args[0])
                elif len(progress_args) == 2:
                    phase = str(progress_args[0])
                    message = str(progress_args[1])
                else:
                    raise TypeError("installer progress accepts message or phase/message")
                normalized = (
                    phase
                    if phase
                    in {
                        "checking",
                        "available",
                        "installing",
                        "installed",
                        "blocked",
                        "failed",
                    }
                    else "installing"
                )
                progress(ProverInstallEvent(provider, normalized, message))

        kwargs: dict[str, Any] = {
            **options,
            "yes": True,
            "strict": strict,
            "force": force,
            "on_progress": plugin_progress,
            **_real_provider_kwargs(provider),
        }
        signature = inspect.signature(ensure)
        accepts_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        user_local_only = True if entry is None else entry.user_local_only
        if user_local_only and (
            accepts_kwargs or "install_root" in signature.parameters
        ):
            # Bind the reviewed plugin to the same validated user-local root
            # that owns the cross-process publication lease.  This prevents a
            # plugin default or legacy environment variable from publishing
            # somewhere different from the path certified by the facade.
            kwargs["install_root"] = str(configured_user_install_root())
        unconsumed_options = sorted(
            key
            for key in options
            if not accepts_kwargs and key not in signature.parameters
        )
        if unconsumed_options:
            raise ValueError(
                "reviewed plugin does not consume options: "
                + ", ".join(unconsumed_options)
            )
        if not accepts_kwargs:
            kwargs = {
                key: value
                for key, value in kwargs.items()
                if key in signature.parameters
            }
        # Serialize publication for the selected provider only.  Independent
        # providers remain parallel.  The filesystem lease closes the
        # cross-process race between CLI, MCP, and supervisor workers.
        with _install_lock(provider):
            with _cross_process_install_lock(provider) as lease_evidence:
                process_lock_evidence = dict(lease_evidence)
                plugin_invoked = True
                result = ensure(**kwargs)
        payload = _receipt_payload(result)
        status = str(payload.get("status") or "").strip().lower()
        capability_available = _reviewed_installer_succeeds(result)
        installed_value = payload.get("installed")
        if installed_value is not None and type(installed_value) is not bool:
            raise ValueError("plugin receipt installed must be a boolean")
        installed = installed_value is True or status == "installed"
        mutation_observed = installed and status == "installed"
        bindings = (
            payload.get("bindings")
            if isinstance(payload.get("bindings"), dict)
            else {}
        )
        checksum_verified = payload.get("checksum_verified") is True
        artifact = payload.get("pin") or bindings.get("artifact") or {}
        executable_path = (
            payload.get("executable_path")
            or bindings.get("executable_path")
            or ""
        )
        semantic_probe = (
            bindings.get("semantic_checks")
            or bindings.get("semantic_probe")
            or {}
        )
        identity_bound = bool(
            executable_path
            or artifact
            or bindings.get("package_identity")
            or bindings.get("toolchain_identity")
            or bindings.get("deployment_lock_sha256")
            or bindings.get("identity_manifest_sha256")
        )
        rollback_verified = (
            bindings.get("previous_good_preserved") is True
            or bindings.get("transactional_publication") is True
        )
        checksum_required = bool(entry.requires_checksum_for_managed_artifacts)
        certified = bool(
            capability_available
            and (checksum_verified or not checksum_required)
            and identity_bound
            and _nonempty_mapping(semantic_probe)
            and (not mutation_observed or rollback_verified)
        )
        public_status = status or ("available" if capability_available else "failed")
        if capability_available and not certified:
            public_status = f"{public_status}_unverified"
        capability_probe = (
            _post_install_capability_probe(provider)
            if mutation_observed
            else {"available": capability_available, "probe": "plugin_receipt"}
        )
        return {
            **base,
            "status": public_status,
            "install_attempted": plugin_invoked,
            "mutation_authorized": authorized,
            "installed": installed,
            "available": capability_available,
            "certified": certified,
            "evidence": {
                "authorization": {
                    "allowed": authorized,
                    "explicit_yes": allow_install is True,
                },
                "platform_binding": {
                    "platform": plan["platform"],
                    "accepted_by_registry": authorized,
                },
                "dependency": {
                    "module": entry.module_path,
                    "callable": entry.ensure_name,
                    "resolved": plugin_resolved,
                    "capability_probe": capability_probe,
                },
                "license": {
                    "spdx": entry.license,
                    "source": entry.source,
                    "evidence_class": "registry_declared",
                },
                "checksum": {
                    "verified": checksum_verified,
                    "required": checksum_required,
                },
                "artifact": artifact,
                "identity_bound": identity_bound,
                "executable": {"path": executable_path},
                "rollback": {
                    "required": mutation_observed,
                    "verified": rollback_verified,
                },
                "semantic_probe": semantic_probe,
                "process_lock": process_lock_evidence,
                "network": {
                    "allowed_by_install_request": True,
                    "attempted": payload.get(
                        "network_attempted",
                        bindings.get("network_attempted", "plugin_not_reported"),
                    ),
                },
            },
            "plugin_receipt": payload,
        }
    except Exception as exc:
        logger.exception("Reviewed install transaction failed for %s", provider)
        return {
            **base,
            "status": "failed",
            "install_attempted": plugin_invoked,
            "mutation_authorized": authorized,
            "error": f"{type(exc).__name__}: {exc}",
            "evidence": {
                "authorization": {
                    "allowed": authorized,
                    "explicit_yes": allow_install is True,
                },
                "plugin_resolved": plugin_resolved,
                "plugin_invoked": plugin_invoked,
                "mutation_observed": (
                    mutation_observed
                    if not plugin_invoked
                    else "unknown_after_invocation"
                ),
                "process_lock": process_lock_evidence,
                "rollback": {
                    "required": plugin_invoked,
                    "verified": False,
                },
            },
        }


@dataclass(frozen=True)
class ProverInstallEvent:
    """A user-facing lazy-installer state transition.

    Callers can send these events to a progress bar, a desktop notification,
    or a log pane. The default reporter writes the same transition to stdout so
    a synchronous first-run install is visibly active rather than silent.
    """

    prover: str
    phase: Literal[
        "checking",
        "available",
        "installing",
        "installed",
        "disabled",
        "blocked",
        "failed",
    ]
    message: str


ProgressCallback = Callable[[ProverInstallEvent], None]


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_prover_name(prover_name: str) -> str:
    """Return the canonical lazy-installer name for a prover."""

    normalized = (
        str(prover_name or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(".", "_")
        .replace(" ", "_")
    )
    return _ALIASES.get(normalized, normalized)


def _common_bin_dirs() -> list[Path]:
    try:
        home = Path.home()
    except (OSError, RuntimeError):
        return []
    configured_root = os.environ.get("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT")
    prover_root = (
        Path(configured_root).expanduser()
        if configured_root
        else home / ".local" / "share" / "ipfs_datasets_py" / "theorem-provers"
    )
    return [
        home / ".local" / "bin",
        home / ".elan" / "bin",
        home / ".opam" / "default" / "bin",
        prover_root / "bin",
    ]


def _is_hermetic_shadow_path(path: Path) -> bool:
    """Return True when a path is under a hermetic-shadow probe tree."""

    try:
        parts = {part.lower() for part in path.resolve().parts}
    except OSError:
        parts = {part.lower() for part in path.parts}
    return (
        "hermetic-shadow-probe" in parts
        or "hermetic-only" in parts
        or "hermetic-parity" in parts
    )


def find_executable(command: str) -> str | None:
    """Find a usable prover executable, preferring managed vendor paths.

    Hermetic shadow / parity shims never outrank a managed vendor launcher.
    When only a hermetic path is visible, it is ignored so first-use install
    can materialize the real vendor tool.
    """

    command = str(command or "").strip()
    if not command:
        return None
    path = Path(command).expanduser()
    normalized_name = normalize_prover_name(path.name)
    env_name = _ENV_NAMES.get(
        normalized_name,
        normalized_name.upper().replace("-", "_"),
    )
    explicit = os.environ.get(f"IPFS_DATASETS_PY_{env_name}_EXECUTABLE")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if path.parent != Path("."):
        candidates.append(path)
    else:
        directories = _common_bin_dirs()
        # The managed launcher is pinned and checksummed; it must outrank PATH,
        # which can contain a stale binary for another CPU architecture.
        if directories:
            candidates.append(directories[-1] / command)
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))
        candidates.extend(directory / command for directory in directories[:-1])

    seen: set[str] = set()
    hermetic_fallback: str | None = None
    for candidate in candidates:
        try:
            resolved = str(candidate.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            if not candidate.is_file() or not os.access(str(candidate), os.X_OK):
                continue
            if normalize_prover_name(path.name) == "cvc5":
                try:
                    probe = subprocess.run(
                        [str(candidate), "--version"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                except (OSError, subprocess.SubprocessError):
                    continue
                if probe.returncode != 0 or "cvc5" not in (
                    f"{probe.stdout}\n{probe.stderr}".lower()
                ):
                    continue
            if _is_hermetic_shadow_path(candidate):
                # Keep as last-resort only for tools that are intentionally
                # hermetic; first-use install prefers real vendors.
                if hermetic_fallback is None:
                    hermetic_fallback = str(candidate)
                continue
            return str(candidate)
        except OSError:
            continue
    return hermetic_fallback


def import_time_install_forbidden() -> bool:
    """Return True: lazy installers must never run during import."""

    return True


def declared_install_gap_providers() -> frozenset[str]:
    """Return provider ids that are explicit install gaps in the toolchain registry.

    Lazy install must refuse these rather than invent an unmanaged download.
    Reviewed managed pins (including Runtime MTL vendor and hyperproperty
    engines) are **not** gaps and may install through the registry callable.
    """

    try:
        from ipfs_datasets_py.logic.backends.toolchains import (
            InstallAvailability,
            default_registry,
        )
    except Exception:
        # Registry unavailable: no static hard gaps (lock-aligned managed pins).
        return frozenset()
    gaps: set[str] = set()
    for descriptor in default_registry().descriptors:
        if descriptor.availability is InstallAvailability.DECLARED_GAP:
            gaps.add(descriptor.provider_id)
            gaps.add(descriptor.provider_id.replace("-", "_"))
    return frozenset(gaps)


def _resolve_reviewed_installer(prover: str) -> Callable[..., Any] | None:
    """Resolve a reviewed family installer without importing it on discovery.

    This function is called only after an explicit lazy-install execution
    request.  Registry metadata remains side-effect free and the selected
    plugin is imported narrowly rather than importing the complete matrix.
    """

    if prover not in _REVIEWED_EXTERNAL_INSTALLERS:
        return None
    # Optional ErgoAI Java API JDK is owned by the advisors plugin as a support
    # lifecycle and is intentionally outside FormalVerificationInstallerRegistry@1.
    if prover == "temurin-jdk":
        try:
            module = importlib.import_module(
                "ipfs_datasets_py.logic.backends.installers.advisors"
            )
            ensure = getattr(module, "ensure_temurin_jdk", None)
        except Exception:
            logger.exception("Could not resolve managed Temurin JDK installer")
            return None
        return ensure if callable(ensure) else None
    try:
        from ipfs_datasets_py.logic.backends.installers.registry import (
            get_installer_entry,
        )

        entry = get_installer_entry(prover)
        module = importlib.import_module(entry.module_path)
        ensure = getattr(module, entry.ensure_name, None)
    except Exception:
        logger.exception("Could not resolve reviewed installer for %s", prover)
        return None
    return ensure if callable(ensure) else None


def _reviewed_installer_succeeds(result: object) -> bool:
    """Interpret bool and typed installer receipts without truthiness leaks."""

    if isinstance(result, bool):
        return result
    status = str(getattr(result, "status", "") or "").strip().lower()
    if status in {"available", "already_present", "installed"}:
        return True
    if isinstance(result, dict):
        status = str(result.get("status") or "").strip().lower()
        return status in {"available", "already_present", "installed"}
    return False


def lazy_installs_enabled() -> bool:
    """Return True when lazy prover installs are globally enabled."""

    if minimal_imports_enabled():
        return False

    explicit = os.environ.get("IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS")
    if explicit is not None:
        return _truthy(explicit)

    return _truthy(os.environ.get("IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS"))


def _explicitly_disabled() -> bool:
    """Return whether the caller explicitly opted out of lazy installation."""

    for name in (
        "IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS",
        "IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS",
    ):
        value = os.environ.get(name)
        if value is not None and not _truthy(value):
            return True
    return False


def _emit(event: ProverInstallEvent, progress: ProgressCallback | None) -> None:
    logger.info("%s: %s", event.prover, event.message)
    print(f"[ipfs_datasets_py] {event.prover}: {event.message}", flush=True)
    if progress is not None:
        progress(event)


def prover_lazy_install_enabled(prover_name: str) -> bool:
    """Return True when lazy installation is enabled for a specific prover.

    The reviewed first-use portfolio (ErgoAI, Runtime MTL vendor, ATP/SMT,
    TLA, Tamarin stack, Soufflé/SecPAL, hyperproperty engines, and
    reconstruction kernels Lean/Coq/Isabelle) defaults on so package consumers
    get real managed tools without setting
    ``IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=1``. Global or per-prover ``=0``
    still opts out.
    """

    prover = normalize_prover_name(prover_name)
    if minimal_imports_enabled():
        return False

    env_name = _ENV_NAMES.get(prover, prover.upper())
    explicit = os.environ.get(f"IPFS_DATASETS_PY_LAZY_INSTALL_{env_name}")
    if explicit is not None:
        return _truthy(explicit)

    auto_install = os.environ.get(f"IPFS_DATASETS_PY_AUTO_INSTALL_{env_name}")
    if auto_install is not None:
        return _truthy(auto_install)

    # Explicit global opt-out always wins for every prover, including ErgoAI.
    if _explicitly_disabled():
        return False

    # Reviewed portfolio: default-on without the global flag so dependent
    # packages get real managed vendors on first use when missing.
    if prover in _DEFAULT_ON_FIRST_USE_INSTALLERS:
        return True

    if not lazy_installs_enabled():
        return False

    return True


def lazy_install_strict() -> bool:
    """Return True when lazy installer failures should raise."""

    return _truthy(os.environ.get("IPFS_DATASETS_PY_LAZY_INSTALL_STRICT")) or _truthy(
        os.environ.get("IPFS_DATASETS_PY_PROVER_INSTALL_STRICT")
    )


def _lazy_install_prover_once(
    prover_name: str,
    *,
    force: bool = False,
    strict: bool | None = None,
    reason: str | None = None,
    progress: ProgressCallback | None = None,
    allow_automatic: bool = False,
    java_executable: str | Path | None = None,
) -> bool:
    """Try to install a prover dependency once and emit visible progress.

    Normal bridge use remains opt-in through the lazy-install environment
    variables. Execution paths that are explicitly asking for a native solver
    can pass ``allow_automatic=True``; that still respects a caller's explicit
    ``...LAZY_INSTALL_PROVERS=0`` opt-out.
    """

    prover = normalize_prover_name(prover_name)
    if import_time_install_forbidden() and os.environ.get(
        "IPFS_DATASETS_PY_IMPORT_CONTEXT"
    ):
        _emit(
            ProverInstallEvent(
                prover,
                "blocked",
                "installation is forbidden during import",
            ),
            progress,
        )
        return False

    is_declared_gap = prover in declared_install_gap_providers()
    if is_declared_gap and prover not in _REVIEWED_EXTERNAL_INSTALLERS:
        _emit(
            ProverInstallEvent(
                prover,
                "blocked",
                "provider is a declared install gap; refusing unmanaged lazy install",
            ),
            progress,
        )
        return False

    if not prover_lazy_install_enabled(prover) and not (
        allow_automatic and not _explicitly_disabled() and not minimal_imports_enabled()
    ):
        _emit(
            ProverInstallEvent(
                prover,
                "disabled",
                (
                    "lazy installation is disabled for this prover "
                    "(set IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=1, or for "
                    "ErgoAI leave defaults and avoid "
                    "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI=0)"
                ),
            ),
            progress,
        )
        return False

    strict = lazy_install_strict() if strict is None else strict
    _emit(
        ProverInstallEvent(prover, "checking", f"checking whether {prover} is already available"),
        progress,
    )

    try:
        reviewed_ensure = _resolve_reviewed_installer(prover)
        if prover in _REVIEWED_EXTERNAL_INSTALLERS and reviewed_ensure is None:
            _emit(
                ProverInstallEvent(
                    prover,
                    "failed",
                    "reviewed installer registry entry is not callable",
                ),
                progress,
            )
            return False
        if reviewed_ensure is not None:
            ensure = reviewed_ensure
        else:
            from ipfs_datasets_py.logic.integration.bridges import prover_installer

            ensure_name = (
                "ensure_cvc5_cli"
                if prover == "cvc5" and allow_automatic
                else f"ensure_{prover}"
            )
            ensure = getattr(prover_installer, ensure_name, None)
        if ensure is None:
            logger.debug("No lazy installer is registered for prover %s", prover)
            _emit(
                ProverInstallEvent(prover, "failed", "no installer is registered for this prover"),
                progress,
            )
            return False

        kwargs = {"yes": True, "strict": strict}
        if force:
            kwargs["force"] = True
        if prover in {"tlc", "apalache"} and java_executable is not None:
            kwargs["java_executable"] = java_executable
        if prover == "coq":
            kwargs["allow_sudo"] = _truthy(
                os.environ.get("IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS")
            )
        # A lazy execution request must never silently substitute a hermetic
        # shadow/shim for the external prover it names.  Such shadows remain
        # available through their explicit certification entrypoints.
        if reviewed_ensure is not None:
            signature = inspect.signature(ensure)
            accepts_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
            if accepts_kwargs or "install_root" in signature.parameters:
                kwargs["install_root"] = str(configured_user_install_root())
            if prover in {"hyperltl", "autohyper", "mchyper"}:
                kwargs.update({"vendor": True, "hermetic_engine": False})
            elif prover in {"souffle", "secpal"}:
                kwargs.update({"vendor": True, "hermetic_shadow": False})
            elif prover == "runtime-mtl-external":
                kwargs.update({"vendor": True, "hermetic_parity_engine": False})
            elif prover == "ergoai":
                kwargs["hermetic_shim"] = False

        if progress is not None:
            def forward_progress(phase: str, message: str) -> None:
                normalized_phase = phase if phase in {
                    "checking", "available", "installing", "installed", "blocked", "failed"
                } else "installing"
                event = ProverInstallEvent(prover, normalized_phase, message)
                logger.info("%s: %s", prover, message)
                if progress is not None:
                    progress(event)

            kwargs["on_progress"] = forward_progress

        _emit(
            ProverInstallEvent(
                prover,
                "installing",
                "installation started" + (f" because {reason}" if reason else ""),
            ),
            progress,
        )
        # The ordinary first-use facade shares the same filesystem lease as
        # the explicit transactional API.  The in-process lock in
        # ``lazy_install_prover`` handles threads; this lease prevents two
        # Python processes from concurrently staging or publishing one tool.
        with _cross_process_install_lock(prover):
            result = ensure(**kwargs)
        ok = _reviewed_installer_succeeds(result)
        importlib.invalidate_caches()
        clear_feature_detection_cache()
        _emit(
            ProverInstallEvent(
                prover,
                "installed" if ok else "failed",
                "installation completed" if ok else "installation did not make the prover available",
            ),
            progress,
        )
        return ok
    except Exception as exc:
        logger.exception("Lazy install failed for prover %s", prover)
        _emit(ProverInstallEvent(prover, "failed", f"installation failed: {exc}"), progress)
        if strict:
            raise
        return False


def _install_lock(prover: str) -> threading.Lock:
    """Return a per-prover lock without serializing unrelated installations."""

    with _INSTALL_LOCKS_GUARD:
        lock = _INSTALL_LOCKS.get(prover)
        if lock is None:
            lock = threading.Lock()
            _INSTALL_LOCKS[prover] = lock
        return lock


def lazy_install_prover(
    prover_name: str,
    *,
    force: bool = False,
    strict: bool | None = None,
    reason: str | None = None,
    progress: ProgressCallback | None = None,
    allow_automatic: bool = False,
    java_executable: str | Path | None = None,
) -> bool:
    """Install a prover at most once per process, safely under parallel use."""

    prover = normalize_prover_name(prover_name)
    allowed = prover_lazy_install_enabled(prover) or (
        allow_automatic
        and not _explicitly_disabled()
        and not minimal_imports_enabled()
    )
    if not allowed:
        return _lazy_install_prover_once(
            prover,
            force=force,
            strict=strict,
            reason=reason,
            progress=progress,
            allow_automatic=allow_automatic,
            java_executable=java_executable,
        )

    with _install_lock(prover):
        attempt_key = (
            f"{prover}|java={Path(java_executable).expanduser().resolve()}"
            if java_executable is not None and prover in {"tlc", "apalache"}
            else prover
        )
        if attempt_key in _ATTEMPTED and not force:
            return bool(_INSTALL_RESULTS.get(attempt_key, False))
        _ATTEMPTED.add(attempt_key)
        try:
            installed = _lazy_install_prover_once(
                prover,
                force=force,
                strict=strict,
                reason=reason,
                progress=progress,
                allow_automatic=allow_automatic,
                java_executable=java_executable,
            )
        except Exception:
            _INSTALL_RESULTS[attempt_key] = False
            raise
        _INSTALL_RESULTS[attempt_key] = bool(installed)
        return bool(installed)


def _find_managed_vendor_ergoai_executable() -> str | None:
    """Return only a provenance-valid managed ErgoAI launcher, never a shim."""

    try:
        from ipfs_datasets_py.logic.backends.installers.advisors import (
            expand_user_local_root,
            probe_ergoai_identity,
            ergoai_offline_subprocess_env,
        )
    except Exception:
        return None

    root = expand_user_local_root(configured_user_install_root())
    for name in _PROVER_EXECUTABLES.get("ergoai", ("ergoai",)):
        candidate = root / "bin" / name
        try:
            if not candidate.is_file() or not os.access(str(candidate), os.X_OK):
                continue
            probe = probe_ergoai_identity(
                executable=str(candidate),
                install_root=root,
                require_managed_vendor=True,
                env=ergoai_offline_subprocess_env(),
                allow_path_fallback=False,
            )
        except Exception:
            continue
        if (
            probe.get("managed_vendor_provenance_verified") is True
            and probe.get("is_hermetic_advisor_shim") is not True
        ):
            return str(Path(str(probe.get("executable_path") or candidate)).resolve())
    return None


def ensure_prover_executable(
    prover_name: str,
    *,
    reason: str,
    progress: ProgressCallback | None = None,
    strict: bool | None = None,
    java_executable: str | Path | None = None,
) -> str | None:
    """Return a required executable, installing it when missing and allowed.

    For most solvers this is first-use only (not import). ErgoAI is default-on
    when a real managed vendor is missing so package consumers do not need a
    portfolio opt-in; hermetic advisor shims never count as installed. Callers
    can still opt out with ``IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0`` or
    ``IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI=0``.
    """

    prover = normalize_prover_name(prover_name)
    candidates = _PROVER_EXECUTABLES.get(prover, (prover,))
    if prover == "ergoai":
        explicit_ergoai = os.environ.get("ERGOAI_BINARY")
        if explicit_ergoai:
            path = Path(explicit_ergoai).expanduser()
            if path.is_file() and os.access(str(path), os.X_OK):
                _emit(
                    ProverInstallEvent(prover, "available", f"using {path}"),
                    progress,
                )
                return str(path)
        _emit(
            ProverInstallEvent(
                prover, "checking", f"resolving managed ErgoAI for {reason}"
            ),
            progress,
        )
        managed = _find_managed_vendor_ergoai_executable()
        if managed:
            _emit(
                ProverInstallEvent(prover, "available", f"using {managed}"),
                progress,
            )
            return managed
        # Missing real vendor: install without portfolio opt-in (unless opted out).
        lazy_install_prover(
            prover,
            strict=strict,
            reason=reason,
            progress=progress,
            allow_automatic=True,
            java_executable=java_executable,
        )
        managed = _find_managed_vendor_ergoai_executable()
        if managed:
            _emit(
                ProverInstallEvent(
                    prover, "installed", f"using installed executable {managed}"
                ),
                progress,
            )
            return managed
        explicit_ergoai = os.environ.get("ERGOAI_BINARY")
        if explicit_ergoai:
            path = Path(explicit_ergoai).expanduser()
            if path.is_file() and os.access(str(path), os.X_OK):
                _emit(
                    ProverInstallEvent(
                        prover, "installed", f"using installed executable {path}"
                    ),
                    progress,
                )
                return str(path)
        return None

    _emit(
        ProverInstallEvent(prover, "checking", f"resolving executable for {reason}"),
        progress,
    )
    for candidate in candidates:
        executable = find_executable(candidate)
        if executable:
            _emit(ProverInstallEvent(prover, "available", f"using {executable}"), progress)
            return executable

    lazy_install_prover(
        prover,
        strict=strict,
        reason=reason,
        progress=progress,
        allow_automatic=True,
        java_executable=java_executable,
    )
    for candidate in candidates:
        executable = find_executable(candidate)
        if executable:
            _emit(ProverInstallEvent(prover, "installed", f"using installed executable {executable}"), progress)
            return executable
    return None


def ensure_managed_ergoai_if_missing(
    *,
    reason: str = "package import ensure missing managed ErgoAI",
    progress: ProgressCallback | None = None,
    strict: bool | None = None,
) -> str | None:
    """Install real ErgoAI only when a managed vendor is not already present.

    Safe for package-import side effects: a provenance-valid managed install is
    a no-op; hermetic shims do not suppress install; explicit opt-out and
    minimal-import modes still block work. Never runs under
    ``IPFS_DATASETS_PY_IMPORT_CONTEXT=1`` (certification / pure-import probes).
    """

    if minimal_imports_enabled() or _explicitly_disabled():
        return _find_managed_vendor_ergoai_executable()
    if os.environ.get("IPFS_DATASETS_PY_IMPORT_CONTEXT"):
        return _find_managed_vendor_ergoai_executable()
    if not prover_lazy_install_enabled("ergoai"):
        return _find_managed_vendor_ergoai_executable()
    managed = _find_managed_vendor_ergoai_executable()
    if managed:
        return managed
    return ensure_prover_executable(
        "ergoai",
        reason=reason,
        progress=progress,
        strict=strict,
    )


def default_first_use_prover_portfolio() -> tuple[str, ...]:
    """Return prover ids that auto-install on first use when missing."""

    return tuple(sorted(_DEFAULT_ON_FIRST_USE_INSTALLERS))


def ensure_default_prover_portfolio(
    *,
    reason: str = "default theorem-prover portfolio for package consumers",
    progress: ProgressCallback | None = None,
    strict: bool | None = None,
    include_kernels: bool = True,
) -> dict[str, str | None]:
    """Ensure the default managed prover portfolio is installed when missing.

    Installs each default-on first-use tool (Runtime MTL vendor, ATP/SMT, TLA,
    Tamarin, Soufflé/SecPAL, hyperproperty engines, and reconstruction kernels).
    Pass ``include_kernels=False`` to skip Lean/Coq/Isabelle.

    Returns a mapping of prover id → absolute executable path or ``None`` when
    install/probe failed. Explicit ``LAZY_INSTALL_PROVERS=0`` still opts out.
    """

    portfolio = list(default_first_use_prover_portfolio())
    if not include_kernels:
        portfolio = [p for p in portfolio if p not in {"lean", "coq", "isabelle"}]
    results: dict[str, str | None] = {}
    for prover in portfolio:
        results[prover] = ensure_prover_executable(
            prover,
            reason=reason,
            progress=progress,
            strict=strict,
        )
    return results


def reset_lazy_install_attempts() -> None:
    """Clear the per-process lazy-install attempt cache."""

    with _INSTALL_LOCKS_GUARD:
        _ATTEMPTED.clear()
        _INSTALL_RESULTS.clear()


__all__ = [
    "configured_user_install_root",
    "find_executable",
    "ensure_prover_executable",
    "ensure_managed_ergoai_if_missing",
    "ensure_default_prover_portfolio",
    "default_first_use_prover_portfolio",
    "lazy_install_prover",
    "lazy_install_strict",
    "lazy_installs_enabled",
    "normalize_prover_name",
    "prover_lazy_install_enabled",
    "reset_lazy_install_attempts",
    "import_time_install_forbidden",
    "declared_install_gap_providers",
    "ProverInstallEvent",
    "ProgressCallback",
    "LOGIC_VERIFICATION_LAZY_INSTALLER_INTERFACE",
    "LOGIC_VERIFICATION_INSTALL_RECEIPT_SCHEMA",
    "reviewed_installer_inventory",
    "plan_reviewed_install",
    "execute_reviewed_install",
]
