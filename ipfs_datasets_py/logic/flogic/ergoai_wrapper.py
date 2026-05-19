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

Tutorial: https://sites.google.com/coherentknowledge.com/ergoai-tutorial/ergoai-tutorial
Submodule: ipfs_datasets_py/logic/ErgoAI  (git submodule ErgoAI/ErgoEngine)
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

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
_ERGO_BINARY_NAMES = ("ergo", "ergoai", "runErgo.sh", "runergo")


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


def _ergoai_release_binary_candidates() -> List[Path]:
    root = _ergoai_release_install_root()
    candidates = [root / "Coherent" / "ERGOAI_3.0" / "ErgoAI" / "runergo"]
    try:
        candidates.extend(sorted(root.glob("Coherent/ERGOAI_*/ErgoAI/runergo")))
    except OSError:
        pass
    return candidates


def _find_ergo_binary() -> Optional[Path]:
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


def _lazy_install_ergo_binary(reason: str) -> Optional[Path]:
    """Attempt an opt-in lazy ErgoAI install and return the resolved binary."""

    try:
        from ipfs_datasets_py.logic.external_provers.lazy_installer import (
            lazy_install_prover,
        )
    except Exception as exc:
        logger.debug("Could not import lazy prover installer for ErgoAI: %s", exc)
        return None

    if not lazy_install_prover("ergoai", reason=reason):
        return None
    return _find_ergo_binary()


def resolve_ergo_binary(
    binary: Optional[Path] = None,
    *,
    lazy_install: bool = True,
    reason: str = "ErgoAIWrapper requested",
) -> Optional[Path]:
    """Resolve an ErgoAI binary, optionally invoking the shared lazy installer."""

    if binary is not None:
        candidate = Path(binary)
        if _ergo_binary_is_configured(candidate):
            return candidate
        return None

    found = _find_ergo_binary()
    if found is not None:
        return found

    if lazy_install:
        return _lazy_install_ergo_binary(reason)
    return None


ERGOAI_AVAILABLE: bool = _find_ergo_binary() is not None


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
        binary: Optional[Path] = None,
        lazy_install: bool = True,
    ) -> None:
        self.ontology: FLogicOntology = FLogicOntology(name=ontology_name)
        self.binary: Optional[Path] = resolve_ergo_binary(
            binary,
            lazy_install=lazy_install,
        )
        self.simulation_mode: bool = self.binary is None
        if self.simulation_mode:
            logger.info(
                "ErgoAI binary not found — running in simulation mode. "
                "Install ErgoEngine and set ERGOAI_BINARY, or enable the opt-in "
                "lazy installer with IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=1 "
                "and IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI=1. "
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

    def query(self, goal: str) -> FLogicQuery:
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

        return self._run_ergo_query(goal)

    def batch_query(self, goals: Sequence[str]) -> List[FLogicQuery]:
        """Execute multiple goals and return one :class:`FLogicQuery` per goal."""
        return [self.query(g) for g in goals]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_ergo_program(self) -> str:
        """Build the current ontology as a loadable Ergo source program."""
        return self.ontology.to_ergo_program()

    def _run_ergo_query(self, goal: str) -> FLogicQuery:
        """Invoke the ErgoAI binary and parse its output."""
        assert self.binary is not None  # guaranteed by caller

        program = self._build_ergo_program()
        result = FLogicQuery(goal=goal)
        tmp_path: Optional[str] = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".ergo", delete=False
            ) as tmp:
                tmp.write(program)
                tmp_path = tmp.name

            query_goal = goal.rstrip().rstrip(".")
            commands = f"load{{'{tmp_path}'}}.\n{query_goal}.\n\\halt.\n"
            proc = subprocess.run(
                [str(self.binary)],
                input=commands,
                capture_output=True,
                text=True,
                timeout=30,
            )

            output = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
            if proc.returncode == 0 and "++Error" not in output:
                result.status = FLogicStatus.SUCCESS
                result.bindings = _parse_ergo_output(proc.stdout)
                if not result.bindings and "\nNo\n" in output:
                    result.status = FLogicStatus.FAILURE
            else:
                result.status = FLogicStatus.FAILURE
                result.error_message = output.strip()
        except subprocess.TimeoutExpired:
            result.status = FLogicStatus.ERROR
            result.error_message = "ErgoAI subprocess timed out after 30 s"
        except (OSError, ValueError) as exc:
            result.status = FLogicStatus.ERROR
            result.error_message = str(exc)
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        return result

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_program(self) -> str:
        """Return the current ontology as an Ergo source string."""
        return self.ontology.to_ergo_program()

    def get_statistics(self) -> Dict[str, Any]:
        """Return a summary of the current knowledge base."""
        return {
            "ontology_name": self.ontology.name,
            "frames": len(self.ontology.frames),
            "classes": len(self.ontology.classes),
            "rules": len(self.ontology.rules),
            "simulation_mode": self.simulation_mode,
            "ergoai_binary": str(self.binary) if self.binary else None,
        }


def _parse_ergo_output(output: str) -> List[Dict[str, Any]]:
    """
    Parse ErgoAI/XSB output into a list of variable binding dicts.

    ErgoAI prints query answers in the form::

        ?X = foo, ?Y = bar
        ?X = baz, ?Y = qux

    Each line becomes one binding dict.  Unparseable lines are silently
    skipped.
    """
    bindings: List[Dict[str, Any]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("%"):
            continue
        binding: Dict[str, Any] = {}
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
    "ERGOAI_SUBMODULE_PATH",
    "resolve_ergo_binary",
]
