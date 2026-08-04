"""
ErgoAI / ErgoEngine wrapper for F-logic reasoning.

This module provides a Python interface to the ErgoAI/ErgoEngine theorem prover
(https://github.com/ErgoAI/ErgoEngine).  ErgoAI implements full F-logic on top
of an extended XSB Prolog engine and supports:

* Frame-based object-oriented knowledge representation
* Inheritance and class hierarchies
* Defeasible and classical reasoning
* Integration with external ontologies (OWL, RDF)

The wrapper follows the same "prefer native, fall back gracefully" pattern used
by the other CEC wrappers in this package.  When the ErgoAI binary is not
available it degrades to a pure-Python in-memory mode that still lets callers
construct and inspect F-logic structures.

FVT-G218 / ``ErgoAILiveToolchainContract@1`` adds a *bounded live semantic
adapter*: when a real binary is present, entailment, non-entailment,
contradiction, mutation, replay, malformed, timeout, and resource-bound cases
execute through ErgoAI.  Results remain **proposal / candidate evidence** until
reconstructed or checked by an independent proof authority.  Simulation-mode
or hermetic-shim fixtures never count as live vendor execution.

Tutorial: https://sites.google.com/coherentknowledge.com/ergoai-tutorial/ergoai-tutorial
Submodule: ipfs_datasets_py/logic/ErgoAI  (git submodule ErgoAI/ErgoEngine)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .flogic_types import (
    FLogicClass,
    FLogicFrame,
    FLogicOntology,
    FLogicQuery,
    FLogicStatus,
)

logger = logging.getLogger(__name__)

# Path to the ErgoAI submodule or lazy-installer checkout.
ERGOAI_SUBMODULE_PATH: Path = Path(__file__).parent.parent / "ErgoAI"

# Default binary name looked up on PATH or inside the submodule
_ERGO_BINARY_NAMES = ("runErgo.sh", "runergo")

# Live adapter contract identity (must match lock + certification surface).
LIVE_TOOLCHAIN_INTERFACE = "ErgoAILiveToolchainContract@1"
LIVE_ADAPTER_SCHEMA_VERSION = "ergoai-live-semantic-adapter/v1"
JAVA_API_TOOLCHAIN_INTERFACE = "ErgoAIJavaAPIToolchainContract@1"
JAVA_API_ADAPTER_SCHEMA_VERSION = "ergoai-java-api-adapter/v1"
JAVA_API_LIVE_INTERFACE = "ErgoAIJavaAPILiveCertification@1"
JAVA_API_LIVE_ADAPTER_SCHEMA_VERSION = "ergoai-java-api-live-adapter/v1"
AUTHORITY_CEILING = "advisory"
EVIDENCE_CLASS = "proposal_or_candidate_until_independent_reconstruction"
LIVE_CASE_KINDS = (
    "entailment",
    "non_entailment",
    "contradiction",
    "mutation",
    "replay",
    "malformed",
    "timeout",
    "resource_bound",
)
_SAFE_ERGO_PATH_RE = re.compile(r"^/[A-Za-z0-9_./-]+$")


def _ergo_path_literal(path: Path) -> str:
    """Render a generated absolute path as a non-escaping Ergo literal."""

    text = str(path)
    if not _SAFE_ERGO_PATH_RE.fullmatch(text) or ".." in path.parts:
        raise ValueError("unsafe generated Ergo source path")
    return f"'{text}'"


def _runner_requires_paths_file(path: Path) -> bool:
    return path.name.lower() in {"runergo", "runergo.sh"}


def _ergo_binary_is_configured(path: Path) -> bool:
    """Return true when *path* looks like a runnable ErgoAI entrypoint."""

    if not path.is_file():
        return False
    if _runner_requires_paths_file(path):
        return (path.parent / ".ergo_paths").is_file()
    return True


def _ergoai_release_install_root() -> Path:
    env_path = os.environ.get("IPFS_DATASETS_PY_ERGOAI_INSTALL_DIR")
    if env_path:
        return Path(env_path).expanduser()
    return Path.home() / ".local" / "share" / "ipfs_datasets_py" / "provers" / "ergoai"


def _ergoai_release_binary_candidates() -> list[Path]:
    root = _ergoai_release_install_root()
    candidates = [root / "Coherent" / "ERGOAI_3.0" / "ErgoAI" / "runergo"]
    try:
        candidates.extend(sorted(root.glob("Coherent/ERGOAI_*/ErgoAI/runergo")))
    except OSError:
        pass
    return candidates


def _configured_managed_install_root() -> Path | None:
    """Resolve the reviewed lazy-installer root without creating it."""

    try:
        from ipfs_datasets_py.logic.external_provers.lazy_installer import (
            configured_user_install_root,
        )

        return configured_user_install_root()
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        logger.debug("ErgoAI managed install root is unavailable: %s", exc)
        return None


def _find_provenance_valid_managed_binary(
    install_root: Path,
    *,
    platform_key: str | None = None,
) -> tuple[Path | None, dict[str, Any]]:
    """Return only a launcher certified by the root's identity manifest."""

    try:
        from ipfs_datasets_py.logic.backends.installers.advisors import (
            ergoai_offline_subprocess_env,
            probe_ergoai_identity,
        )
    except Exception as exc:  # pragma: no cover - packaging variance
        return None, {
            "managed_vendor_provenance_verified": False,
            "probe_error": f"managed_provenance_probe_unavailable:{exc}",
        }

    root = Path(install_root).expanduser().resolve()
    for name in ("ergoai", *_ERGO_BINARY_NAMES):
        candidate = root / "bin" / name
        try:
            if not candidate.is_file() or not os.access(candidate, os.X_OK):
                continue
            probe = probe_ergoai_identity(
                executable=str(candidate),
                install_root=root,
                require_managed_vendor=True,
                platform_key=platform_key,
                env=ergoai_offline_subprocess_env(),
                allow_path_fallback=False,
            )
        except Exception as exc:  # pragma: no cover - malformed local state
            probe = {
                "managed_vendor_provenance_verified": False,
                "probe_error": f"managed_provenance_probe_failed:{exc}",
            }
        if probe.get("managed_vendor_provenance_verified") is True:
            return candidate.resolve(), dict(probe)
    return None, {
        "managed_vendor_provenance_verified": False,
        "probe_error": "no_provenance_valid_managed_launcher",
    }


def _find_ergo_binary() -> Path | None:
    """
    Locate the ErgoAI binary.

    Search order:
    1. ``ERGOAI_BINARY`` environment variable.
    2. Well-known relative paths inside the submodule.
    3. System ``PATH``.

    Returns ``None`` when no binary is found (graceful degradation mode).
    """
    env_path = os.environ.get("ERGOAI_BINARY")
    if env_path:
        p = Path(env_path)
        if _ergo_binary_is_configured(p):
            return p

    for candidate in _ergoai_release_binary_candidates():
        if _ergo_binary_is_configured(candidate):
            return candidate

    # Check common locations inside the submodule
    for candidate in (
        ERGOAI_SUBMODULE_PATH / "ErgoAI" / "runErgo.sh",
        ERGOAI_SUBMODULE_PATH / "ErgoAI" / "runergo",
        ERGOAI_SUBMODULE_PATH / "runErgo.sh",
        ERGOAI_SUBMODULE_PATH / "runergo",
        ERGOAI_SUBMODULE_PATH / "ergo",
        ERGOAI_SUBMODULE_PATH / "ergoai",
    ):
        if _ergo_binary_is_configured(candidate):
            return candidate

    # Fall back to PATH
    import shutil
    for name in _ERGO_BINARY_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)

    return None


def _lazy_install_ergo_binary(reason: str) -> Path | None:
    """Request the shared managed ErgoAI installer on explicit execution."""

    try:
        from ipfs_datasets_py.logic.external_provers.lazy_installer import (
            ensure_prover_executable,
        )
    except Exception as exc:
        logger.debug("Could not import lazy prover installer for ErgoAI: %s", exc)
        return None

    executable = ensure_prover_executable("ergoai", reason=reason)
    return Path(executable) if executable else None


def resolve_ergo_binary(
    binary: Path | None = None,
    *,
    lazy_install: bool = True,
    reason: str = "ErgoAIWrapper requested",
) -> Path | None:
    """Resolve an ErgoAI binary, optionally invoking the shared lazy installer."""

    if binary is not None:
        candidate = Path(binary)
        if _ergo_binary_is_configured(candidate):
            return candidate
        return None

    managed_root = _configured_managed_install_root()
    if managed_root is not None:
        managed, _ = _find_provenance_valid_managed_binary(managed_root)
        if managed is not None:
            return managed

    found = _find_ergo_binary()
    if found is not None:
        return found

    if lazy_install:
        installed = _lazy_install_ergo_binary(reason)
        if managed_root is not None:
            managed, _ = _find_provenance_valid_managed_binary(managed_root)
            if managed is not None:
                return managed
        return installed
    return None


def ergoai_available(*, require_managed_vendor: bool = False) -> bool:
    """Return current ErgoAI availability without installing anything."""

    managed_root = _configured_managed_install_root()
    if managed_root is not None:
        managed, _ = _find_provenance_valid_managed_binary(managed_root)
        if managed is not None:
            return True
    if require_managed_vendor:
        return False
    return _find_ergo_binary() is not None


def _ensure_managed_ergoai_on_package_import() -> None:
    """If managed ErgoAI is missing, install it once during package import.

    No-op when a provenance-valid managed vendor is already present, when the
    caller opted out, under minimal-import mode, or under certification
    import-context probes. Hermetic advisor shims never suppress install.
    """

    try:
        from ipfs_datasets_py.logic.external_provers.lazy_installer import (
            ensure_managed_ergoai_if_missing,
        )
    except Exception as exc:  # pragma: no cover - packaging variance
        logger.debug("ErgoAI import-time ensure unavailable: %s", exc)
        return
    try:
        ensure_managed_ergoai_if_missing(
            reason="package import ensure missing managed ErgoAI",
        )
    except Exception as exc:  # pragma: no cover - best-effort install
        logger.debug("ErgoAI import-time ensure failed: %s", exc)


# Install real managed ErgoAI when this module is first imported by a consumer
# package *and* no managed vendor is present. Already-installed vendors are
# never reinstalled. Explicit opt-out still applies.
_ensure_managed_ergoai_on_package_import()

# Compatibility snapshot retained for callers that imported the historic
# constant.  New capability checks must use ``ergoai_available()`` so a
# same-process lazy install or removal is observed immediately.
ERGOAI_AVAILABLE: bool = ergoai_available(require_managed_vendor=True) or (
    _find_ergo_binary() is not None
)


class ErgoAIWrapper:
    """
    High-level Python wrapper for the ErgoAI/ErgoEngine F-logic prover.

    When the ErgoAI binary is present the wrapper spawns it as a subprocess and
    communicates via a temporary ``.ergo`` file.  When it is absent the wrapper
    operates in *simulation mode*: all structural operations (adding frames,
    classes, rules) still work and return meaningful results, but theorem
    proving always returns ``FLogicStatus.UNKNOWN``.

    Example::

        from ipfs_datasets_py.logic.flogic import ErgoAIWrapper

        ergo = ErgoAIWrapper()
        ergo.add_class(FLogicClass("Animal"))
        ergo.add_class(FLogicClass("Dog", superclasses=["Animal"]))
        rex = FLogicFrame("rex", scalar_methods={"name": '"Rex"'}, isa="Dog")
        ergo.add_frame(rex)
        result = ergo.query("?X[name -> ?N] : Dog")
        print(result.bindings)

    Attributes:
        ontology: The in-memory F-logic ontology.
        binary: Path to the ErgoAI binary, or ``None`` in simulation mode.
        simulation_mode: ``True`` when no binary was found.
    """

    def __init__(
        self,
        ontology_name: str = "default",
        binary: Path | None = None,
        lazy_install: bool = True,
        install_root: Path | None = None,
        platform_key: str | None = None,
    ) -> None:
        self.ontology: FLogicOntology = FLogicOntology(name=ontology_name)
        self.install_root: Path | None = (
            Path(install_root).expanduser().resolve()
            if install_root is not None
            else None
        )
        self.platform_key = platform_key
        self._managed_vendor_probe: dict[str, Any] = {}
        self._last_execution_evidence: dict[str, Any] = {}
        self._managed_jdk_probe: dict[str, Any] = {}
        self._managed_java_home: Path | None = None
        resolved_binary: Path | None = None

        # Automatic resolution prefers a provenance-valid launcher beneath the
        # reviewed user-local root and binds that root to the wrapper.  Merely
        # finding ``root/bin/ergoai`` is insufficient: an incomplete or stale
        # publication must never outrank a separately configured executable.
        configured_root = _configured_managed_install_root()
        managed_root = self.install_root or configured_root
        if binary is None and managed_root is not None:
            managed_candidate, managed_probe = (
                _find_provenance_valid_managed_binary(
                    managed_root,
                    platform_key=self.platform_key,
                )
            )
            if managed_candidate is not None:
                self.install_root = managed_root
                self._managed_vendor_probe = managed_probe
                resolved_binary = managed_candidate

        if binary is not None:
            candidate = Path(binary).expanduser()
            resolved_binary = resolve_ergo_binary(
                candidate,
                lazy_install=False,
            )
        elif (
            resolved_binary is None
            and self.install_root is not None
            and lazy_install
            and configured_root is not None
            and self.install_root == configured_root
        ):
            # An explicit root may be mutated only when it is exactly the
            # validated user-local root used by the shared installer.  Custom
            # or sealed roots remain read-only identity boundaries.
            _lazy_install_ergo_binary("ErgoAIWrapper requested")
            managed_candidate, managed_probe = (
                _find_provenance_valid_managed_binary(
                    self.install_root,
                    platform_key=self.platform_key,
                )
            )
            if managed_candidate is not None:
                self._managed_vendor_probe = managed_probe
                resolved_binary = managed_candidate
        elif resolved_binary is None and self.install_root is None:
            resolved_binary = resolve_ergo_binary(
                lazy_install=lazy_install,
                reason="ErgoAIWrapper requested",
            )
            # A successful lazy install publishes beneath the configured root.
            # Re-probe after installation and bind the wrapper to those exact
            # bytes, even if a stale legacy binary was also discoverable.
            if managed_root is not None:
                managed_candidate, managed_probe = (
                    _find_provenance_valid_managed_binary(
                        managed_root,
                        platform_key=self.platform_key,
                    )
                )
                if managed_candidate is not None:
                    self.install_root = managed_root
                    self._managed_vendor_probe = managed_probe
                    resolved_binary = managed_candidate

        # Managed launchers named ``runergo`` intentionally live outside the
        # vendor directory containing .ergo_paths.  Admit an explicit launcher
        # here only when a managed root was also supplied; the exact path and
        # digest are then checked by refresh_managed_vendor_provenance().
        if (
            resolved_binary is None
            and binary is not None
            and self.install_root is not None
        ):
            candidate = Path(binary).expanduser()
            if candidate.is_file() and os.access(candidate, os.X_OK):
                resolved_binary = candidate.resolve()
        self.binary: Path | None = resolved_binary
        self.simulation_mode: bool = self.binary is None
        if (
            self.binary is not None
            and self.install_root is not None
            and not self._managed_vendor_probe
        ):
            self.refresh_managed_vendor_provenance()
        if self.simulation_mode:
            logger.info(
                "ErgoAI managed vendor not found — running in simulation mode. "
                "On first import or first use the package installs checksummed "
                "ErgoAI 3.0 into the user-local theorem-prover root unless "
                "opted out (IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI=0 or "
                "IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0). You may also set "
                "ERGOAI_BINARY to an existing runergo. "
                "See: https://github.com/ErgoAI/ErgoEngine"
            )

    # ------------------------------------------------------------------
    # Knowledge base construction
    # ------------------------------------------------------------------

    def add_frame(self, frame: FLogicFrame) -> None:
        """Add an F-logic frame (object description) to the ontology."""
        self.ontology.frames.append(frame)

    def add_class(self, cls: FLogicClass) -> None:
        """Add an F-logic class definition to the ontology."""
        self.ontology.classes.append(cls)

    def add_rule(self, rule: str) -> None:
        """
        Add a raw Ergo rule string to the ontology.

        The rule must be valid Ergo/ErgoAI syntax, e.g.::

            ?X[mammal -> true] :- ?X : Animal[warm_blooded -> true].
        """
        self.ontology.rules.append(rule)

    def load_ontology(self, ontology: FLogicOntology) -> None:
        """Replace the current ontology with *ontology*."""
        self.ontology = ontology

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def query(
        self,
        goal: str,
        *,
        timeout_seconds: float = 30.0,
        max_output_bytes: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> FLogicQuery:
        """
        Execute a single F-logic goal against the current ontology.

        In simulation mode the query is stored but not evaluated.

        Args:
            goal: An Ergo goal string, e.g. ``"?X : Dog"``.

        Returns:
            A :class:`FLogicQuery` with populated ``bindings`` and ``status``.
        """
        result = FLogicQuery(goal=goal)
        if self.simulation_mode:
            result.status = FLogicStatus.UNKNOWN
            result.error_message = (
                "ErgoAI binary unavailable — install ErgoEngine for full reasoning"
            )
            return result

        return self._run_ergo_query(
            goal,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            env=env,
        )

    def batch_query(
        self,
        goals: Sequence[str],
        *,
        timeout_seconds: float = 30.0,
        max_output_bytes: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> list[FLogicQuery]:
        """Execute multiple goals and return one :class:`FLogicQuery` per goal."""
        return [
            self.query(
                g,
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
                env=env,
            )
            for g in goals
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_ergo_program(self) -> str:
        """Build the current ontology as a loadable Ergo source program."""
        return self.ontology.to_ergo_program()

    def _run_ergo_query(
        self,
        goal: str,
        *,
        timeout_seconds: float = 30.0,
        max_output_bytes: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> FLogicQuery:
        """Invoke the ErgoAI binary and parse its output."""
        result = FLogicQuery(goal=goal)
        if self.binary is None or self.simulation_mode:
            result.status = FLogicStatus.ERROR
            result.error_message = "ErgoAI execution requested without a live binary"
            self._last_execution_evidence = {
                "termination_reason": "wrapper_state_error",
                "error": result.error_message,
            }
            return result

        program = self._build_ergo_program()
        tmp_path: Path | None = None
        timeout = max(0.001, min(300.0, float(timeout_seconds)))
        provenance_before = False
        if self.install_root is not None:
            provenance_before = bool(
                self.refresh_managed_vendor_provenance().get(
                    "managed_vendor_provenance_verified"
                )
            )

        try:
            from ipfs_datasets_py.logic.backends.installers.advisors import (
                ergoai_managed_runtime_subprocess_env,
                ergoai_offline_subprocess_env,
                ergoai_safe_temporary_directory,
                run_bounded_ergoai_process,
            )

            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix="ipfs-datasets-ergo-query-",
                suffix=".ergo",
                dir=ergoai_safe_temporary_directory(),
                delete=False,
            ) as tmp:
                tmp.write(program)
                tmp_path = Path(tmp.name)

            query_goal = goal.rstrip().rstrip(".")
            commands = (
                f"load{{{_ergo_path_literal(tmp_path)}}}.\n"
                f"{query_goal}.\n\\halt.\n"
            )
            process_env = ergoai_offline_subprocess_env(env)
            managed_runtime_path_bound = bool(
                provenance_before and self.install_root is not None
            )
            if managed_runtime_path_bound:
                process_env = ergoai_managed_runtime_subprocess_env(
                    self.install_root,
                    base=env,
                )
            execution = run_bounded_ergoai_process(
                self.binary,
                input_text=commands,
                timeout=timeout,
                max_output_bytes=max_output_bytes,
                env=process_env,
            )
            execution["managed_runtime_path_bound"] = managed_runtime_path_bound
            output = str(execution.pop("output_text", ""))
            self._last_execution_evidence = dict(execution)
            termination_reason = execution.get("termination_reason")
            if termination_reason == "timeout":
                result.status = FLogicStatus.ERROR
                result.error_message = (
                    f"ErgoAI subprocess timed out after {timeout:g} s"
                )
            elif termination_reason == "output_limit":
                result.status = FLogicStatus.ERROR
                result.error_message = (
                    "ErgoAI subprocess exceeded the bounded output limit "
                    f"of {execution.get('max_output_bytes')} bytes"
                )
            elif termination_reason == "spawn_error":
                result.status = FLogicStatus.ERROR
                result.error_message = str(
                    execution.get("error") or "ErgoAI subprocess failed to start"
                )
            elif execution.get("returncode") == 0 and "++Error" not in output:
                result.status = FLogicStatus.SUCCESS
                result.bindings = _parse_ergo_output(output)
                if not result.bindings and "\nNo\n" in output:
                    result.status = FLogicStatus.FAILURE
            else:
                result.status = FLogicStatus.FAILURE
                result.error_message = output.strip()
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
            result.status = FLogicStatus.ERROR
            result.error_message = str(exc)
            self._last_execution_evidence = {
                "termination_reason": "wrapper_error",
                "error": str(exc)[:300],
            }
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            provenance_after = False
            if self.install_root is not None:
                provenance_after = bool(
                    self.refresh_managed_vendor_provenance().get(
                        "managed_vendor_provenance_verified"
                    )
                )
            self._last_execution_evidence[
                "managed_vendor_provenance_before_execution"
            ] = provenance_before
            self._last_execution_evidence[
                "managed_vendor_provenance_after_execution"
            ] = provenance_after

        return result

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_program(self) -> str:
        """Return the current ontology as an Ergo source string."""
        return self.ontology.to_ergo_program()

    def get_statistics(self) -> dict[str, Any]:
        """Return a summary of the current knowledge base."""
        return {
            "ontology_name": self.ontology.name,
            "frames": len(self.ontology.frames),
            "classes": len(self.ontology.classes),
            "rules": len(self.ontology.rules),
            "simulation_mode": self.simulation_mode,
            "ergoai_binary": str(self.binary) if self.binary else None,
            "external_process_execution": self.is_external_process_execution(),
            "managed_vendor_provenance_verified": self.is_live_vendor_execution(),
            "authority_ceiling": AUTHORITY_CEILING,
            "grants_proof_authority": False,
            "evidence_class": EVIDENCE_CLASS,
            "live_toolchain_interface": LIVE_TOOLCHAIN_INTERFACE,
        }

    # ------------------------------------------------------------------
    # Bounded live semantic adapter (FVT-G218)
    # ------------------------------------------------------------------

    def is_external_process_execution(self) -> bool:
        """Return whether any runnable external process is selected."""

        return not self.simulation_mode and self.binary is not None

    def refresh_managed_vendor_provenance(self) -> dict[str, Any]:
        """Revalidate that the selected bytes belong to a managed install.

        A path or successful ``--version`` response is insufficient provenance.
        The installer validates the exact selected launcher/vendor digest,
        identity receipt, artifact, XSB runtime, platform, and managed root.
        """

        if self.binary is None or self.install_root is None:
            self._managed_vendor_probe = {
                "managed_vendor_provenance_verified": False,
                "probe_error": "managed_install_root_not_bound",
            }
            return dict(self._managed_vendor_probe)
        try:
            from ipfs_datasets_py.logic.backends.installers.advisors import (
                ergoai_offline_subprocess_env,
                probe_ergoai_identity,
            )

            self._managed_vendor_probe = probe_ergoai_identity(
                executable=str(self.binary),
                install_root=self.install_root,
                require_managed_vendor=True,
                platform_key=self.platform_key,
                env=ergoai_offline_subprocess_env(),
            )
        except Exception as exc:  # pragma: no cover - packaging variance
            self._managed_vendor_probe = {
                "managed_vendor_provenance_verified": False,
                "probe_error": f"managed_provenance_probe_failed:{exc}",
            }
        return dict(self._managed_vendor_probe)

    def is_live_vendor_execution(self) -> bool:
        """True only for the exact executable bound by a managed manifest."""

        return bool(
            self.is_external_process_execution()
            and self._managed_vendor_probe.get(
                "managed_vendor_provenance_verified"
            )
            and not self._managed_vendor_probe.get("is_hermetic_advisor_shim")
        )

    def run_live_semantic_adapter(
        self,
        *,
        timeout_seconds: float = 30.0,
        bound_timeout_seconds: float = 2.0,
        max_output_bytes: int = 4096,
        require_live_binary: bool = True,
        require_managed_vendor: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute the full bounded live semantic matrix through ErgoAI.

        Simulation mode and missing binaries never produce
        ``live_vendor_execution=True``.  Every verdict is tagged as
        proposal/candidate evidence under the advisory authority ceiling.
        """

        external_execution = self.is_external_process_execution()
        if external_execution and self.install_root is not None:
            self.refresh_managed_vendor_provenance()
        managed_vendor_before = self.is_live_vendor_execution()
        if not external_execution:
            return {
                "interface": LIVE_TOOLCHAIN_INTERFACE,
                "schema_version": LIVE_ADAPTER_SCHEMA_VERSION,
                "live_vendor_execution": False,
                "external_process_execution": False,
                "simulation_mode": self.simulation_mode,
                "passed": False,
                "block_reasons": [
                    "ergoai_binary_unavailable_or_simulation"
                    if require_live_binary
                    else "simulation_cannot_produce_live_semantic_evidence"
                ],
                "case_kinds": list(LIVE_CASE_KINDS),
                "authority_ceiling": AUTHORITY_CEILING,
                "grants_proof_authority": False,
                "evidence_class": EVIDENCE_CLASS,
                "checks": {},
            }
        if require_managed_vendor and not managed_vendor_before:
            return {
                "interface": LIVE_TOOLCHAIN_INTERFACE,
                "schema_version": LIVE_ADAPTER_SCHEMA_VERSION,
                "live_vendor_execution": False,
                "external_process_execution": external_execution,
                "simulation_mode": self.simulation_mode,
                "passed": False,
                "block_reasons": ["managed_vendor_provenance_unverified"],
                "case_kinds": list(LIVE_CASE_KINDS),
                "authority_ceiling": AUTHORITY_CEILING,
                "grants_proof_authority": False,
                "evidence_class": EVIDENCE_CLASS,
                "checks": {},
            }

        try:
            from ipfs_datasets_py.logic.backends.installers.advisors import (
                ergoai_managed_runtime_subprocess_env,
                ergoai_offline_subprocess_env,
                run_ergoai_semantic_checks,
            )
        except Exception as exc:  # pragma: no cover - packaging variance
            return {
                "interface": LIVE_TOOLCHAIN_INTERFACE,
                "schema_version": LIVE_ADAPTER_SCHEMA_VERSION,
                "live_vendor_execution": False,
                "passed": False,
                "block_reasons": [f"semantic_runner_unavailable:{exc}"],
                "case_kinds": list(LIVE_CASE_KINDS),
                "authority_ceiling": AUTHORITY_CEILING,
                "grants_proof_authority": False,
                "evidence_class": EVIDENCE_CLASS,
                "checks": {},
            }

        selected_binary = self.binary
        if selected_binary is None:
            return {
                "interface": LIVE_TOOLCHAIN_INTERFACE,
                "schema_version": LIVE_ADAPTER_SCHEMA_VERSION,
                "live_vendor_execution": False,
                "external_process_execution": False,
                "simulation_mode": True,
                "passed": False,
                "block_reasons": ["ergoai_binary_unavailable_or_simulation"],
                "case_kinds": list(LIVE_CASE_KINDS),
                "authority_ceiling": AUTHORITY_CEILING,
                "grants_proof_authority": False,
                "evidence_class": EVIDENCE_CLASS,
                "checks": {},
            }
        try:
            process_env = ergoai_offline_subprocess_env(env)
            if managed_vendor_before and self.install_root is not None:
                process_env = ergoai_managed_runtime_subprocess_env(
                    self.install_root,
                    base=env,
                )
            semantics = run_ergoai_semantic_checks(
                selected_binary,
                timeout=timeout_seconds,
                include_extended=True,
                bound_timeout_seconds=bound_timeout_seconds,
                max_output_bytes=max_output_bytes,
                env=process_env,
            )
        except Exception as exc:
            return {
                "interface": LIVE_TOOLCHAIN_INTERFACE,
                "schema_version": LIVE_ADAPTER_SCHEMA_VERSION,
                "live_vendor_execution": False,
                "external_process_execution": external_execution,
                "simulation_mode": self.simulation_mode,
                "passed": False,
                "block_reasons": [f"semantic_runner_failed:{exc}"],
                "case_kinds": list(LIVE_CASE_KINDS),
                "authority_ceiling": AUTHORITY_CEILING,
                "grants_proof_authority": False,
                "evidence_class": EVIDENCE_CLASS,
                "checks": {},
            }
        if not isinstance(semantics, Mapping):
            return {
                "interface": LIVE_TOOLCHAIN_INTERFACE,
                "schema_version": LIVE_ADAPTER_SCHEMA_VERSION,
                "live_vendor_execution": False,
                "external_process_execution": external_execution,
                "simulation_mode": self.simulation_mode,
                "passed": False,
                "block_reasons": ["semantic_runner_returned_invalid_evidence"],
                "case_kinds": list(LIVE_CASE_KINDS),
                "authority_ceiling": AUTHORITY_CEILING,
                "grants_proof_authority": False,
                "evidence_class": EVIDENCE_CLASS,
                "checks": {},
            }
        if self.install_root is not None:
            self.refresh_managed_vendor_provenance()
        managed_vendor_after = self.is_live_vendor_execution()
        managed_vendor_execution = bool(
            managed_vendor_before and managed_vendor_after
        )
        block_reasons = [] if semantics.get("passed") else [
            "live_semantic_matrix_incomplete"
        ]
        if not managed_vendor_execution:
            block_reasons.append("managed_vendor_provenance_unverified")
        # This method is the *live vendor* semantic adapter.  An arbitrary
        # external executable may still yield useful diagnostic output, but it
        # cannot make this contract pass without before/after managed identity
        # validation, irrespective of the caller's compatibility flag.
        adapter_passed = bool(
            semantics.get("passed") and managed_vendor_execution
        )
        payload = {
            "interface": LIVE_TOOLCHAIN_INTERFACE,
            "schema_version": LIVE_ADAPTER_SCHEMA_VERSION,
            "live_vendor_execution": managed_vendor_execution,
            "external_process_execution": external_execution,
            "managed_vendor_provenance_verified": managed_vendor_execution,
            "simulation_mode": False,
            "executable": str(selected_binary),
            "case_kinds": list(LIVE_CASE_KINDS),
            "checks": semantics.get("checks") or {},
            "replay_bound": bool(semantics.get("replay_bound")),
            "core_passed": bool(semantics.get("core_passed")),
            "extended_passed": bool(semantics.get("extended_passed")),
            "passed": adapter_passed,
            "normalized_evidence_digest_sha256": semantics.get(
                "normalized_evidence_digest_sha256"
            ),
            "authority_ceiling": AUTHORITY_CEILING,
            "grants_proof_authority": False,
            "grants_theorem_authority": False,
            "evidence_class": EVIDENCE_CLASS,
            "network_used": False,
            "offline_subprocess_env_applied": True,
            "install_attempted": False,
            "managed_vendor_provenance_before_execution": managed_vendor_before,
            "managed_vendor_provenance_after_execution": managed_vendor_after,
            "block_reasons": block_reasons,
        }
        payload["adapter_digest_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    k: payload[k]
                    for k in (
                        "live_vendor_execution",
                        "passed",
                        "normalized_evidence_digest_sha256",
                        "authority_ceiling",
                        "evidence_class",
                    )
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return payload

    def evaluate_bounded_goal(
        self,
        goal: str,
        *,
        timeout_seconds: float = 30.0,
        max_output_bytes: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Run one bounded goal and tag the result as candidate evidence only."""

        query = self.query(
            goal,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            env=env,
        )
        execution = dict(self._last_execution_evidence)
        managed_vendor_execution = bool(
            execution.get("managed_vendor_provenance_before_execution")
            and execution.get("managed_vendor_provenance_after_execution")
            and self.is_live_vendor_execution()
        )
        status = (
            query.status.value
            if isinstance(query.status, FLogicStatus)
            else str(query.status)
        )
        if status == FLogicStatus.ERROR.value and query.error_message and (
            "timed out" in query.error_message.lower()
        ):
            status = "timeout"
        elif execution.get("termination_reason") == "output_limit":
            status = "resource_bound"
        return {
            "interface": LIVE_TOOLCHAIN_INTERFACE,
            "schema_version": LIVE_ADAPTER_SCHEMA_VERSION,
            "goal": goal,
            "status": status,
            "bindings": list(query.bindings or []),
            "error_message": query.error_message,
            "live_vendor_execution": managed_vendor_execution,
            "external_process_execution": self.is_external_process_execution(),
            "managed_vendor_provenance_verified": managed_vendor_execution,
            "simulation_mode": self.simulation_mode,
            "timeout_seconds": timeout_seconds,
            "max_output_bytes": execution.get(
                "max_output_bytes", max_output_bytes
            ),
            "resource_bound_enforced": execution.get(
                "resource_bound_enforced", False
            ),
            "timed_out": execution.get("timed_out", False),
            "termination_reason": execution.get("termination_reason"),
            "observed_output_digest_sha256": execution.get(
                "observed_output_digest_sha256"
            ),
            "output_digest_complete": execution.get("output_digest_complete"),
            "observed_output_bytes": execution.get("observed_output_bytes"),
            "offline_subprocess_env_applied": bool(execution),
            "authority_ceiling": AUTHORITY_CEILING,
            "grants_proof_authority": False,
            "evidence_class": EVIDENCE_CLASS,
        }



    # ------------------------------------------------------------------
    # Optional ErgoAI Java API (managed Temurin JDK / FVT-G222)
    # ------------------------------------------------------------------

    def refresh_managed_jdk_identity(self) -> dict[str, Any]:
        """Probe the managed Temurin JDK without trusting ambient JAVA_HOME."""

        try:
            from ipfs_datasets_py.logic.backends.installers.advisors import (
                probe_temurin_jdk_identity,
            )
        except Exception as exc:  # pragma: no cover - packaging variance
            self._managed_jdk_probe = {
                "satisfied": False,
                "probe_error": f"jdk_probe_unavailable:{exc}",
                "ambient_java_home_trusted": False,
            }
            self._managed_java_home = None
            return dict(self._managed_jdk_probe)

        root = self.install_root or _configured_managed_install_root()
        probe = probe_temurin_jdk_identity(
            install_root=root,
            require_managed=True,
        )
        self._managed_jdk_probe = dict(probe)
        if probe.get("satisfied"):
            self._managed_java_home = Path(str(probe["java_home"]))
        else:
            self._managed_java_home = None
        return dict(self._managed_jdk_probe)

    def java_api_available(self) -> bool:
        """Return True when the optional managed Java API JDK is satisfied."""

        if self._managed_jdk_probe.get("satisfied") is True:
            return True
        probe = self.refresh_managed_jdk_identity()
        return bool(probe.get("satisfied"))

    def managed_java_home(self) -> Path | None:
        """Return the exact managed JDK home bound for Java consumers."""

        if self._managed_java_home is not None:
            return self._managed_java_home
        self.refresh_managed_jdk_identity()
        return self._managed_java_home

    def java_api_runtime_env(
        self,
        base: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Environment for ErgoAI Java consumers bound to the managed JDK."""

        try:
            from ipfs_datasets_py.logic.backends.installers.advisors import (
                managed_temurin_runtime_env,
            )
        except Exception as exc:
            raise RuntimeError(
                f"managed Java API runtime environment unavailable: {exc}"
            ) from exc
        root = self.install_root or _configured_managed_install_root()
        return managed_temurin_runtime_env(install_root=root, base=base)

    def java_api_capability(self) -> dict[str, Any]:
        """Describe the optional Java API capability without installing."""

        probe = self.refresh_managed_jdk_identity()
        return {
            "interface": JAVA_API_TOOLCHAIN_INTERFACE,
            "schema_version": JAVA_API_ADAPTER_SCHEMA_VERSION,
            "available": bool(probe.get("satisfied")),
            "core_ergoai_available": ergoai_available(
                require_managed_vendor=False
            ),
            "core_ergoai_independent": True,
            "ambient_java_home_trusted": False,
            "managed_java_home": (
                str(self._managed_java_home)
                if self._managed_java_home is not None
                else None
            ),
            "authority_ceiling": AUTHORITY_CEILING,
            "probe": {
                key: probe.get(key)
                for key in (
                    "satisfied",
                    "managed",
                    "expected_version",
                    "reason_codes",
                    "tools",
                )
            },
        }

    def run_java_api_semantic_cases(self) -> dict[str, Any]:
        """Execute the reviewed Java API semantic case matrix when available."""

        try:
            from ipfs_datasets_py.logic.backends.installers.advisors import (
                run_ergoai_java_api_semantic_cases,
            )
        except Exception as exc:
            return {
                "interface": JAVA_API_TOOLCHAIN_INTERFACE,
                "all_passed": False,
                "error": f"java_api_semantics_unavailable:{exc}",
            }
        root = self.install_root or _configured_managed_install_root()
        return run_ergoai_java_api_semantic_cases(install_root=root)

    def run_java_api_vendor_consumer(
        self,
        *,
        allow_hermetic_ergoai: bool = False,
    ) -> dict[str, Any]:
        """Run the ErgoAI-bound Java vendor consumer under the managed JDK."""

        try:
            from ipfs_datasets_py.logic.backends.installers.advisors import (
                run_ergoai_java_vendor_consumer,
            )
        except Exception as exc:
            return {
                "interface": JAVA_API_LIVE_INTERFACE,
                "status": "failed",
                "error": f"java_api_vendor_consumer_unavailable:{exc}",
                "satisfies_vendor_java_consumer": False,
            }
        root = self.install_root or _configured_managed_install_root()
        return run_ergoai_java_vendor_consumer(
            install_root=root,
            allow_hermetic_ergoai=allow_hermetic_ergoai,
        )

    def build_java_api_live_certification(
        self,
        *,
        run_live_cases: bool = True,
        allow_hermetic_ergoai: bool = False,
        yes: bool = False,
    ) -> dict[str, Any]:
        """Build ``ErgoAIJavaAPILiveCertification@1`` evidence for this wrapper."""

        try:
            from ipfs_datasets_py.logic.backends.installers.advisors import (
                build_ergoai_java_api_live_certification,
            )
        except Exception as exc:
            return {
                "interface": JAVA_API_LIVE_INTERFACE,
                "schema_version": JAVA_API_LIVE_ADAPTER_SCHEMA_VERSION,
                "certified": False,
                "error": f"java_api_live_certification_unavailable:{exc}",
            }
        root = self.install_root or _configured_managed_install_root()
        return build_ergoai_java_api_live_certification(
            install_root=root,
            run_live_cases=run_live_cases,
            allow_hermetic_ergoai=allow_hermetic_ergoai,
            yes=yes,
        )

def _parse_ergo_output(output: str) -> list[dict[str, Any]]:
    """
    Parse ErgoAI/XSB output into a list of variable binding dicts.

    ErgoAI prints query answers in the form::

        ?X = foo, ?Y = bar
        ?X = baz, ?Y = qux

    Each line becomes one binding dict.  Unparseable lines are silently
    skipped.
    """
    bindings: list[dict[str, Any]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("%"):
            continue
        binding: dict[str, Any] = {}
        for part in line.split(","):
            part = part.strip()
            if "=" in part:
                var, _, val = part.partition("=")
                var = var.strip()
                if var.startswith("?"):
                    binding[var] = val.strip()
        if binding:
            bindings.append(binding)
    return bindings


__all__ = [
    "ErgoAIWrapper",
    "ERGOAI_AVAILABLE",
    "ergoai_available",
    "ERGOAI_SUBMODULE_PATH",
    "resolve_ergo_binary",
    "LIVE_TOOLCHAIN_INTERFACE",
    "LIVE_ADAPTER_SCHEMA_VERSION",
    "AUTHORITY_CEILING",
    "EVIDENCE_CLASS",
    "LIVE_CASE_KINDS",
]
