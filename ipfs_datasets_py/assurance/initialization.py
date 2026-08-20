"""FACP-022: Move Datasets installation behind explicit initialization.

Cold import of this module is hermetic: no installer construction, no network,
no environment mutation, and no implicit HOME/state bootstrap.

Installation and legacy auto-install opt-in require an explicit authorized
``initialize_datasets`` call with a concrete ``state_root``. Missing
dependencies return typed ``Unavailable`` / ``Failed`` outcomes rather than
false success. Legacy opt-in cannot silently default on.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, MutableMapping, Optional

TASK_ID = "FACP-022"
GOAL_ID = "FACP-G210"
BUNDLE = "facp/migration/datasets-init"
EVIDENCE_ID = "facp/datasets-explicit-initialization@1"
INTERFACE = "DatasetsExplicitInitialization@1"

ClosedOutcome = Literal["Unavailable", "Failed", "Attempted", "Observed"]

# Environment keys that legacy package-root code may mutate on import.
_LEGACY_AUTO_INSTALL_KEYS = (
    "IPFS_DATASETS_AUTO_INSTALL",
    "IPFS_KIT_AUTO_INSTALL_DEPS",
    "IPFS_AUTO_INSTALL",
)

_COMPAT_WARNING_CATEGORY = UserWarning
_COMPAT_WARNING_MESSAGE = (
    "FACP-022: legacy Datasets auto-install opt-in enabled explicitly; "
    "silent default-on is forbidden. Prefer authorize_install with an "
    "explicit state_root and typed Unavailable/Failed on missing deps."
)

_lock = threading.RLock()
_state: Optional["InitializationState"] = None
_fan_in_installed = False
_fan_in_finder: Optional["_HermeticImportPolicyFinder"] = None


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class InitializationOutcome:
    """Typed non-boolean initialization / install gate result."""

    outcome: ClosedOutcome
    code: str
    message: str
    state_root: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True only for an observed successful initialization boundary."""
        return self.outcome == "Observed" and self.code in {
            "initialized",
            "already_initialized",
            "fan_in_applied",
            "fan_in_already_applied",
            "dependency_present",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "code": self.code,
            "message": self.message,
            "state_root": self.state_root,
            "details": dict(self.details),
            "ok": self.ok,
            "task_id": TASK_ID,
            "evidence_id": EVIDENCE_ID,
        }


@dataclass
class InitializationState:
    """Process-wide explicit initialization record."""

    state_root: Path
    authorize_install: bool
    authorize_legacy_opt_in: bool
    initialized: bool = True
    dependency_probes: dict[str, str] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return {
            "state_root": str(self.state_root),
            "authorize_install": self.authorize_install,
            "authorize_legacy_opt_in": self.authorize_legacy_opt_in,
            "initialized": self.initialized,
            "dependency_probes": dict(self.dependency_probes),
        }


def get_initialization_state() -> Optional[InitializationState]:
    with _lock:
        return _state


def is_initialized() -> bool:
    with _lock:
        return _state is not None and _state.initialized


def is_install_authorized() -> bool:
    with _lock:
        return bool(_state is not None and _state.authorize_install)


def is_legacy_opt_in_authorized() -> bool:
    with _lock:
        return bool(_state is not None and _state.authorize_legacy_opt_in)


def reset_initialization_state(*, remove_fan_in: bool = False) -> None:
    """Test/helper hook: clear process initialization (and optionally fan-in)."""
    global _state, _fan_in_installed, _fan_in_finder
    with _lock:
        _state = None
        if remove_fan_in and _fan_in_finder is not None:
            try:
                sys.meta_path.remove(_fan_in_finder)
            except ValueError:
                pass
            _fan_in_finder = None
            _fan_in_installed = False


def _validate_state_root(state_root: Path | str | None) -> tuple[Path | None, InitializationOutcome | None]:
    if state_root is None:
        return None, InitializationOutcome(
            outcome="Failed",
            code="missing_state_root",
            message="initialize_datasets requires an explicit state_root; implicit HOME state is forbidden",
            details={"implicit_home_forbidden": True},
        )
    try:
        root = Path(state_root).expanduser()
    except TypeError:
        return None, InitializationOutcome(
            outcome="Failed",
            code="invalid_state_root",
            message=f"state_root is not a path: {state_root!r}",
        )
    if not str(root):
        return None, InitializationOutcome(
            outcome="Failed",
            code="empty_state_root",
            message="state_root must be a non-empty path",
        )
    # Refuse treating bare HOME as an implicit default when caller passes "~" alone
    # without resolve context — expanduser is allowed, but empty/missing is not.
    return root, None


def initialize_datasets(
    *,
    state_root: Path | str | None = None,
    authorize_install: bool = False,
    authorize_legacy_opt_in: bool = False,
    create_state_root: bool = True,
    dependencies: Mapping[str, bool] | None = None,
) -> InitializationOutcome:
    """Explicit Datasets initialization / install authorization boundary.

    Parameters
    ----------
    state_root:
        Required concrete state directory. Implicit HOME state is prohibited.
    authorize_install:
        When True, dependency installation attempts are authorized for this
        process after initialization. Default False (fail-closed).
    authorize_legacy_opt_in:
        When True, legacy ``IPFS_DATASETS_AUTO_INSTALL``-style opt-in may be
        enabled explicitly (never by silent default). Emits a compatibility
        warning. Default False.
    create_state_root:
        When True, create ``state_root`` if missing (under the caller-provided
        path only).
    dependencies:
        Optional mapping of import-name → required. Missing required deps yield
        typed ``Unavailable`` without false success.
    """
    global _state

    root, err = _validate_state_root(state_root)
    if err is not None:
        return err
    assert root is not None

    if authorize_legacy_opt_in and not authorize_install:
        return InitializationOutcome(
            outcome="Failed",
            code="legacy_opt_in_requires_authorize_install",
            message="legacy opt-in cannot be enabled without authorize_install=True",
            state_root=str(root),
            details={"authorize_legacy_opt_in": True, "authorize_install": False},
        )

    with _lock:
        if _state is not None and _state.initialized:
            try:
                existing = Path(_state.state_root).resolve()
                requested = root.resolve()
                same_root = existing == requested
            except OSError:
                same_root = str(_state.state_root) == str(root)
            if not same_root:
                return InitializationOutcome(
                    outcome="Failed",
                    code="state_root_conflict",
                    message=(
                        f"already initialized with state_root={_state.state_root}; "
                        f"cannot re-bind to {root}"
                    ),
                    state_root=str(_state.state_root),
                    details={"requested_state_root": str(root)},
                )
            # Strengthen authorization flags on idempotent recall if newly requested.
            if authorize_install:
                _state.authorize_install = True
            if authorize_legacy_opt_in:
                _state.authorize_legacy_opt_in = True
                warnings.warn(_COMPAT_WARNING_MESSAGE, _COMPAT_WARNING_CATEGORY, stacklevel=2)
                _apply_explicit_legacy_opt_in_env()
            return InitializationOutcome(
                outcome="Observed",
                code="already_initialized",
                message="initialization is idempotent; existing state retained",
                state_root=str(_state.state_root),
                details=_state.snapshot(),
            )

        if create_state_root:
            try:
                root.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return InitializationOutcome(
                    outcome="Failed",
                    code="state_root_create_failed",
                    message=f"could not create state_root {root}: {exc}",
                    state_root=str(root),
                    details={"error_type": type(exc).__name__},
                )
        elif not root.exists():
            return InitializationOutcome(
                outcome="Failed",
                code="state_root_missing",
                message=f"state_root does not exist: {root}",
                state_root=str(root),
            )

        probe_results: dict[str, str] = {}
        if dependencies:
            for name, required in dependencies.items():
                present = importlib.util.find_spec(str(name)) is not None
                probe_results[str(name)] = "present" if present else "missing"
                if required and not present:
                    # Do not mark process initialized as successful install.
                    return InitializationOutcome(
                        outcome="Unavailable",
                        code="dependency_unavailable",
                        message=f"required dependency {name!r} is not importable",
                        state_root=str(root),
                        details={
                            "dependency": str(name),
                            "authorize_install": bool(authorize_install),
                            "probes": probe_results,
                        },
                    )

        _state = InitializationState(
            state_root=root.resolve() if root.exists() else root,
            authorize_install=bool(authorize_install),
            authorize_legacy_opt_in=bool(authorize_legacy_opt_in),
            initialized=True,
            dependency_probes=probe_results,
        )

        if authorize_legacy_opt_in:
            warnings.warn(_COMPAT_WARNING_MESSAGE, _COMPAT_WARNING_CATEGORY, stacklevel=2)
            _apply_explicit_legacy_opt_in_env()
        else:
            # Fail-closed: never leave silent default-on semantics active for this gate.
            _clear_silent_legacy_defaults()

        return InitializationOutcome(
            outcome="Observed",
            code="initialized",
            message="datasets initialization recorded with explicit state_root",
            state_root=str(_state.state_root),
            details=_state.snapshot(),
        )


def _clear_silent_legacy_defaults() -> None:
    """Ensure legacy auto-install keys are not left as silent default-on."""
    # Only clear keys that were never explicitly authorized in this gate.
    # Unset or false-like values remain fail-closed; we do not write "true".
    for key in _LEGACY_AUTO_INSTALL_KEYS:
        current = os.environ.get(key)
        if current is None:
            continue
        if _truthy(current) and not is_legacy_opt_in_authorized():
            # Authorized path is the only way to keep these truthy under this gate.
            # When fan-in/init runs without legacy opt-in, force off.
            os.environ[key] = "0"


def _apply_explicit_legacy_opt_in_env() -> None:
    """Enable legacy env opt-in only after explicit authorization."""
    os.environ["IPFS_DATASETS_AUTO_INSTALL"] = "true"
    os.environ["IPFS_KIT_AUTO_INSTALL_DEPS"] = "1"


def ensure_dependency(
    module_name: str,
    *,
    package_name: str | None = None,
    allow_install: bool = False,
) -> InitializationOutcome:
    """Resolve a dependency under the explicit initialization gate.

    Never performs network installation from tests' default path. Missing
    modules return typed ``Unavailable``. Install attempts without prior
    ``authorize_install`` return ``Failed``.
    """
    name = str(module_name)
    with _lock:
        if _state is None or not _state.initialized:
            return InitializationOutcome(
                outcome="Unavailable",
                code="not_initialized",
                message="ensure_dependency requires prior initialize_datasets(...)",
                details={"module": name},
            )
        state_root = str(_state.state_root)
        authorized = _state.authorize_install

    spec = importlib.util.find_spec(name)
    if spec is not None:
        with _lock:
            if _state is not None:
                _state.dependency_probes[name] = "present"
        return InitializationOutcome(
            outcome="Observed",
            code="dependency_present",
            message=f"dependency {name!r} is importable",
            state_root=state_root,
            details={"module": name, "package_name": package_name},
        )

    if allow_install and not authorized:
        return InitializationOutcome(
            outcome="Failed",
            code="install_not_authorized",
            message=(
                f"install of {name!r} requested but authorize_install was not "
                "granted during initialize_datasets"
            ),
            state_root=state_root,
            details={"module": name, "package_name": package_name},
        )

    if allow_install and authorized:
        # Authorized but this module intentionally does not perform network
        # installs; callers must provision deps out-of-band. Return Attempted
        # only if we had an installer hook — here we stay Unavailable so
        # missing deps never look like success.
        return InitializationOutcome(
            outcome="Unavailable",
            code="dependency_missing_authorized_no_network_install",
            message=(
                f"dependency {name!r} missing; install authorized but this "
                "assurance gate does not perform network installation"
            ),
            state_root=state_root,
            details={
                "module": name,
                "package_name": package_name,
                "authorize_install": True,
            },
        )

    return InitializationOutcome(
        outcome="Unavailable",
        code="dependency_unavailable",
        message=f"dependency {name!r} is not importable",
        state_root=state_root,
        details={"module": name, "package_name": package_name},
    )


def hermetic_core_import_env(
    base: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Environment fragment that keeps package-root import fail-closed.

    Used by package-root fan-in and sandbox tests. Does not enable legacy
    auto-install. Forces minimal imports so installer construction is skipped.
    """
    env = dict(base or os.environ)
    # Fail-closed: explicit false, never silent default-on.
    env["IPFS_DATASETS_AUTO_INSTALL"] = "0"
    env["IPFS_KIT_AUTO_INSTALL_DEPS"] = "0"
    env["IPFS_AUTO_INSTALL"] = "0"
    env["IPFS_DATASETS_ENSURE_INSTALLER"] = "0"
    env["IPFS_DATASETS_PY_MINIMAL_IMPORTS"] = "1"
    return env


def apply_hermetic_import_env_to_process() -> None:
    """Apply :func:`hermetic_core_import_env` to the current process environ."""
    for key, value in hermetic_core_import_env().items():
        if key in _LEGACY_AUTO_INSTALL_KEYS or key in {
            "IPFS_DATASETS_ENSURE_INSTALLER",
            "IPFS_DATASETS_PY_MINIMAL_IMPORTS",
        }:
            os.environ[key] = value


class _HermeticImportPolicyFinder:
    """Meta-path finder that applies fail-closed env before package import.

    This is the runtime half of package-root fan-in when ``__init__.py`` has
    not yet been rewritten: legacy ``_enable_default_auto_install`` becomes a
    no-op because values are already set, and minimal imports skip installer
    construction.
    """

    def find_spec(self, fullname: str, path: Any = None, target: Any = None):
        if fullname == "ipfs_datasets_py":
            if is_legacy_opt_in_authorized():
                return None
            apply_hermetic_import_env_to_process()
        return None


def apply_package_root_fan_in(
    *,
    package_module: Any | None = None,
) -> InitializationOutcome:
    """Sole Datasets package-root fan-in (FACP-022).

    Installs the hermetic import policy hook and, when ``package_module`` is
    already loaded, replaces legacy silent default-on helpers with fail-closed
    no-ops while preserving unrelated exports.
    """
    global _fan_in_installed, _fan_in_finder

    with _lock:
        already = _fan_in_installed
        if not _fan_in_installed:
            finder = _HermeticImportPolicyFinder()
            # Insert ahead of default finders so policy runs first.
            sys.meta_path.insert(0, finder)
            _fan_in_finder = finder
            _fan_in_installed = True

        if not is_legacy_opt_in_authorized():
            apply_hermetic_import_env_to_process()

        patched: list[str] = []
        module = package_module
        if module is None:
            module = sys.modules.get("ipfs_datasets_py")
        if module is not None:
            if hasattr(module, "_enable_default_auto_install"):

                def _fail_closed_enable_default_auto_install() -> None:
                    if is_legacy_opt_in_authorized():
                        _apply_explicit_legacy_opt_in_env()
                        warnings.warn(
                            _COMPAT_WARNING_MESSAGE,
                            _COMPAT_WARNING_CATEGORY,
                            stacklevel=2,
                        )
                        return
                    # Never silently default on.
                    return None

                module._enable_default_auto_install = _fail_closed_enable_default_auto_install  # type: ignore[attr-defined]
                patched.append("_enable_default_auto_install")

        details = {
            "fan_in_installed": True,
            "patched": patched,
            "legacy_opt_in_authorized": is_legacy_opt_in_authorized(),
            "unrelated_exports_preserved": True,
        }
        code = "fan_in_already_applied" if already else "fan_in_applied"
        return InitializationOutcome(
            outcome="Observed",
            code=code,
            message="package-root fan-in applied (hermetic import policy)",
            state_root=str(_state.state_root) if _state is not None else None,
            details=details,
        )


def package_root_fan_in_active() -> bool:
    with _lock:
        return _fan_in_installed


def legacy_opt_in_cannot_silently_default_on() -> bool:
    """Contract predicate: unset legacy env must not imply install authorization."""
    # Within this assurance gate, authorization is only the explicit flag.
    if is_legacy_opt_in_authorized():
        return True
    # If env is unset or false, install is not authorized.
    if any(_truthy(os.environ.get(k)) for k in _LEGACY_AUTO_INSTALL_KEYS):
        # Truthy env without authorize_legacy_opt_in is rejected by the gate.
        return False
    return True


__all__ = [
    "BUNDLE",
    "EVIDENCE_ID",
    "GOAL_ID",
    "INTERFACE",
    "InitializationOutcome",
    "InitializationState",
    "TASK_ID",
    "apply_hermetic_import_env_to_process",
    "apply_package_root_fan_in",
    "ensure_dependency",
    "get_initialization_state",
    "hermetic_core_import_env",
    "initialize_datasets",
    "is_initialized",
    "is_install_authorized",
    "is_legacy_opt_in_authorized",
    "legacy_opt_in_cannot_silently_default_on",
    "package_root_fan_in_active",
    "reset_initialization_state",
]
