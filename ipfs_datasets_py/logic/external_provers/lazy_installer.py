"""Lazy installer for optional external theorem prover dependencies.

The prover bridges import cleanly without installing anything.  When a bridge
is explicitly requested and its dependency is missing, this module can perform
a single best-effort install attempt. Normal bridge imports remain opt-in;
native execution paths can request automatic installation and always emit
progress events so a first-use download or build is not silent.

Environment variables:
- IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=1 enables requested-prover installs.
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
    "hyperltl": ("hyperltl", "hyperltl-sat"),
    "autohyper": ("autohyper", "AutoHyper"),
    "mchyper": ("mchyper", "MCHyper"),
    "souffle": ("souffle",),
    "secpal": ("secpal",),
    "runtime-mtl-external": ("runtime-mtl", "runtime-mtl-external", "mtl-monitor"),
}

# These providers have reviewed family installers in
# FormalVerificationInstallerRegistry@1.  Their older toolchain descriptors
# still expose the historical DECLARED_GAP classification for compatibility;
# an explicit lazy-install request may cross that boundary only through the
# reviewed registry callable and always requests the real vendor path.
_REVIEWED_EXTERNAL_INSTALLERS = frozenset(
    {
        "hyperltl",
        "autohyper",
        "mchyper",
        "souffle",
        "secpal",
        "runtime-mtl-external",
        "ergoai",
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
    root = (
        Path(next(iter(configured_values))).expanduser().resolve()
        if configured_values
        else home / ".local" / "share" / "ipfs_datasets_py" / "theorem-provers"
    )
    try:
        root.relative_to(home)
    except ValueError as exc:
        raise ValueError(
            "lazy installer root must be user-local; external sealed roots are read-only"
        ) from exc
    if root == home:
        raise ValueError("lazy installer root must not be the home directory")
    return root


@contextmanager
def _cross_process_install_lock(provider: str) -> Iterator[dict[str, Any]]:
    """Serialize publication across CLI/MCP/supervisor processes.

    The lock itself lives inside the reviewed user-local prover root.  It is
    acquired only after explicit authorization and uses a bounded wait, so a
    dead or hung peer cannot block an API request indefinitely.
    """

    root = _configured_user_install_root()
    lock_dir = root / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    safe_provider = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in provider
    )
    path = lock_dir / f"facade-{safe_provider}.lock"
    handle = path.open("a+b")
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
    entry = get_installer_entry(provider)
    _, public_options = _normalize_installer_options(provider, installer_options)
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
        rollback_verified = bool(
            bindings.get("previous_good_preserved")
            or bindings.get("transactional_publication")
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


def find_executable(command: str) -> str | None:
    """Find a usable prover executable, preferring managed and explicit paths."""

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
            return str(candidate)
        except OSError:
            continue
    return None


def import_time_install_forbidden() -> bool:
    """Return True: lazy installers must never run during import."""

    return True


def declared_install_gap_providers() -> frozenset[str]:
    """Return provider ids that are explicit install gaps in the toolchain registry.

    Lazy install must refuse these rather than invent an unmanaged download.
    """

    try:
        from ipfs_datasets_py.logic.backends.toolchains import (
            InstallAvailability,
            default_registry,
        )
    except Exception:
        # Static fallback keeps the guard active if the registry is unavailable.
        return frozenset(
            {
                "tlc",
                "hyperltl",
                "autohyper",
                "mchyper",
                "souffle",
                "secpal",
                "runtime-mtl-external",
                "runtime_mtl_external",
                "zkp-circuit",
                "zkp_circuit",
            }
        )
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
    """Return True when lazy installation is enabled for a specific prover."""

    prover = normalize_prover_name(prover_name)
    if not lazy_installs_enabled():
        return False

    env_name = _ENV_NAMES.get(prover, prover.upper())
    explicit = os.environ.get(f"IPFS_DATASETS_PY_LAZY_INSTALL_{env_name}")
    if explicit is not None:
        return _truthy(explicit)

    auto_install = os.environ.get(f"IPFS_DATASETS_PY_AUTO_INSTALL_{env_name}")
    if auto_install is not None:
        return _truthy(auto_install)

    # Reconstruction kernels are large/slow, so ordinary optional bridge use
    # stays opt-in. An execution path that explicitly requests the kernel uses
    # allow_automatic=True and still receives visible progress.
    if prover in {"coq", "isabelle"}:
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
                "lazy installation is disabled; set IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=1 to enable it",
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


def ensure_prover_executable(
    prover_name: str,
    *,
    reason: str,
    progress: ProgressCallback | None = None,
    strict: bool | None = None,
    java_executable: str | Path | None = None,
) -> str | None:
    """Return a required executable, installing it lazily when explicitly used.

    This function is the integration point for real execution paths. It does
    not run at import time, but it does make first use visibly install the
    selected optional native solver unless the caller explicitly opted out
    through ``IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0``. This is deliberately
    separate from normal bridge imports, which never trigger a download or
    build.
    """

    prover = normalize_prover_name(prover_name)
    candidates = _PROVER_EXECUTABLES.get(prover, (prover,))
    explicit_ergoai = os.environ.get("ERGOAI_BINARY") if prover == "ergoai" else None
    if explicit_ergoai:
        path = Path(explicit_ergoai).expanduser()
        if path.is_file() and os.access(str(path), os.X_OK):
            _emit(ProverInstallEvent(prover, "available", f"using {path}"), progress)
            return str(path)
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
    if prover == "ergoai":
        explicit_ergoai = os.environ.get("ERGOAI_BINARY")
        if explicit_ergoai:
            path = Path(explicit_ergoai).expanduser()
            if path.is_file() and os.access(str(path), os.X_OK):
                _emit(ProverInstallEvent(prover, "installed", f"using installed executable {path}"), progress)
                return str(path)
    for candidate in candidates:
        executable = find_executable(candidate)
        if executable:
            _emit(ProverInstallEvent(prover, "installed", f"using installed executable {executable}"), progress)
            return executable
    return None


def reset_lazy_install_attempts() -> None:
    """Clear the per-process lazy-install attempt cache."""

    with _INSTALL_LOCKS_GUARD:
        _ATTEMPTED.clear()
        _INSTALL_RESULTS.clear()


__all__ = [
    "find_executable",
    "ensure_prover_executable",
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
