#!/usr/bin/env python3
"""Inventory existing ITP/ATP/SMT/logic-format capability surfaces for the
ITP hammer pipeline (``## HAMMER-002`` in
``docs/logic/itp_hammer_taskboard.todo.md``).

This script answers a single question, deterministically and offline:
*"What Lean, Coq/Rocq, Isabelle, Z3, CVC5, Vampire, E, TPTP, SMT-LIB, TDFOL,
CEC, and prover-installer surfaces already exist in this environment and
this checkout, right now?"*

Design constraints (see the taskboard acceptance criteria):

- **No installation.** This script never downloads, builds, or invokes an
  installer. It only looks at what is already on ``PATH``, in a small set of
  well-known user-local install directories, and inside this repository.
- **No solver invocation by default.** Executable discovery uses
  ``shutil.which`` plus static directory checks — it never runs a solver's
  proof-search entry point. The *only* subprocess execution this script ever
  performs is a bounded (5 second timeout) ``--version``-style metadata
  query, and only for an executable that was already found on disk. That
  metadata probe can be disabled entirely with ``--no-version-probe`` for a
  fully hermetic run that performs zero subprocess calls.
- **No heavy imports.** This script intentionally does not import
  ``ipfs_datasets_py`` (or any of its submodules). Repository "parser
  support" / "native proof-trace support" / "installer support" evidence is
  gathered via static filesystem checks (a known relative path either exists
  in this checkout or it does not) so that running this probe never has the
  side effects of importing the package (e.g. optional dependency shims,
  lazy-installer state, or network-touching auto-installers).
- **Explicit unavailable states.** Every surface reports ``available`` plus,
  when ``False``, a machine-readable ``unavailable_reason`` — nothing is
  silently omitted.

Usage::

    PYTHONPATH=. python scripts/ops/logic/probe_itp_hammer_environment.py \\
        --out data/logic/itp_hammer/environment.json

    # Fully hermetic (zero subprocess calls, executable discovery only):
    PYTHONPATH=. python scripts/ops/logic/probe_itp_hammer_environment.py \\
        --no-version-probe --out /tmp/environment.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

#: Schema version for the JSON document this script produces. Bump this (and
#: keep the previous shape documented in
#: ``docs/logic/itp_hammer_capability_inventory.md``) on any breaking change.
SCHEMA_VERSION = "itp-hammer-environment-probe/v1"

#: Default output path for the generated inventory, relative to the repo
#: root. Matches the HAMMER-002 taskboard "Outputs" entry.
DEFAULT_OUT = Path("data/logic/itp_hammer/environment.json")

#: Bounded timeout (seconds) for the optional ``--version`` metadata probe.
VERSION_PROBE_TIMEOUT = 5


def _repo_root() -> Path:
    # scripts/ops/logic/probe_itp_hammer_environment.py -> repo root
    return Path(__file__).resolve().parents[3]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# ---------------------------------------------------------------------------
# Executable discovery (no install, no solve)
# ---------------------------------------------------------------------------


def _common_bin_dirs() -> List[Path]:
    """Well-known user-local install directories checked in addition to
    ``PATH``. Mirrors the directories consulted by
    ``ipfs_datasets_py.logic.external_provers.lazy_installer.find_executable``
    so this standalone probe agrees with the in-package lazy installer about
    what counts as "already installed", without importing that package.
    """

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


def find_executable(command: str) -> Optional[str]:
    """Find ``command`` on ``PATH`` or in a well-known user-local install
    directory. Never installs anything and never executes ``command``."""

    found = shutil.which(command)
    if found:
        return found
    for directory in _common_bin_dirs():
        candidate = directory / command
        try:
            if candidate.exists() and os.access(str(candidate), os.X_OK):
                return str(candidate)
        except OSError:
            continue
    return None


@dataclass
class ExecutableProbe:
    """Discovery result for a single named executable candidate."""

    candidates: List[str] = field(default_factory=list)
    resolved_name: Optional[str] = None
    resolved_path: Optional[str] = None
    found: bool = False
    version_probe_attempted: bool = False
    version_command: Optional[List[str]] = None
    version: Optional[str] = None
    version_probe_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def probe_executable(
    candidates: Sequence[str],
    *,
    version_args: Sequence[str] = ("--version",),
    probe_version: bool = True,
    timeout: int = VERSION_PROBE_TIMEOUT,
) -> ExecutableProbe:
    """Discover the first available executable among ``candidates`` and,
    when ``probe_version`` is true and it was found, run a single bounded
    ``--version``-style metadata query (never a proof-search invocation)."""

    report = ExecutableProbe(candidates=list(candidates))
    for name in candidates:
        path = find_executable(name)
        if path:
            report.resolved_name = name
            report.resolved_path = path
            report.found = True
            break

    if report.found and probe_version:
        command = [report.resolved_path, *version_args]
        report.version_probe_attempted = True
        report.version_command = command
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            report.version_probe_error = f"timed out after {timeout}s"
        except OSError as exc:
            report.version_probe_error = str(exc)
        else:
            output = (completed.stdout or completed.stderr or "").strip().splitlines()
            report.version = output[0].strip() if output else ""
            if completed.returncode not in (0, None) and not report.version:
                report.version_probe_error = (
                    f"exit code {completed.returncode} produced no usable output"
                )

    return report


# ---------------------------------------------------------------------------
# Static, import-free repository module presence checks
# ---------------------------------------------------------------------------


@dataclass
class ModuleProbe:
    """Static (import-free) presence check for a repository source file."""

    path: str
    kind: str
    exists: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def probe_modules(root: Path, entries: Sequence[tuple]) -> List[ModuleProbe]:
    """``entries`` is a sequence of ``(relative_path, kind)`` tuples."""

    results: List[ModuleProbe] = []
    for rel_path, kind in entries:
        exists = (root / rel_path).is_file()
        results.append(ModuleProbe(path=rel_path, kind=kind, exists=exists))
    return results


@dataclass
class CapabilityNote:
    """A single yes/no capability claim with the evidence backing it."""

    supported: bool
    mechanism: str
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SurfaceReport:
    """Full inventory record for one ITP/ATP/SMT/format/framework surface."""

    surface_id: str
    display_name: str
    category: str
    executables: Dict[str, Any] = field(default_factory=dict)
    repo_modules: List[Dict[str, Any]] = field(default_factory=list)
    native_proof_trace_support: Dict[str, Any] = field(default_factory=dict)
    parser_support: Dict[str, Any] = field(default_factory=dict)
    available: bool = False
    unavailable_reason: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _any_module_exists(modules: Sequence[ModuleProbe]) -> bool:
    return any(module.exists for module in modules)


def _module_paths(modules: Sequence[ModuleProbe]) -> List[str]:
    return [module.path for module in modules if module.exists]


# ---------------------------------------------------------------------------
# Surface builders
# ---------------------------------------------------------------------------


def _build_lean_surface(root: Path, *, probe_version: bool) -> SurfaceReport:
    lean = probe_executable(["lean"], probe_version=probe_version)
    lake = probe_executable(["lake"], probe_version=probe_version)
    modules = probe_modules(
        root,
        [
            (
                "ipfs_datasets_py/logic/external_provers/interactive/lean_prover_bridge.py",
                "bridge",
            ),
        ],
    )
    executables_ok = lean.found and lake.found
    modules_ok = _any_module_exists(modules)
    available = executables_ok and modules_ok
    unavailable_reason = None
    if not available:
        reasons = []
        if not lean.found:
            reasons.append("lean_executable_not_found_on_path_or_common_install_dirs")
        if not lake.found:
            reasons.append("lake_executable_not_found_on_path_or_common_install_dirs")
        if not modules_ok:
            reasons.append("no_lean_bridge_module_in_repo")
        unavailable_reason = ";".join(reasons)
    return SurfaceReport(
        surface_id="lean",
        display_name="Lean 4 / Lake",
        category="interactive_theorem_prover",
        executables={"lean": lean.to_dict(), "lake": lake.to_dict()},
        repo_modules=[m.to_dict() for m in modules],
        native_proof_trace_support=CapabilityNote(
            supported=executables_ok,
            mechanism=(
                "Lean 4 elaborates a term and the Lean *kernel* independently "
                "type-checks it; a reconstruction is only accepted if `lean`/"
                "`lake build` exits 0 on the target file. This is a native, "
                "trusted proof-trace mechanism (the kernel check itself), not "
                "a solver-produced certificate."
            ),
            evidence=(["lean", "lake"] if executables_ok else []),
        ).to_dict(),
        parser_support=CapabilityNote(
            supported=modules_ok,
            mechanism=(
                "ipfs_datasets_py.logic.external_provers.interactive."
                "lean_prover_bridge wraps `lean`/`lake` invocation and result "
                "parsing; it does not yet implement the HAMMER-006 native "
                "goal/hypothesis snapshot frontend."
            ),
            evidence=_module_paths(modules),
        ).to_dict(),
        available=available,
        unavailable_reason=unavailable_reason,
        notes=(
            "Elan-managed Lean toolchain. HAMMER-006 "
            "(ipfs_datasets_py/logic/hammers/frontends/lean.py) is still "
            "'waiting' on the taskboard, so there is no native goal-snapshot "
            "adapter yet — only the lower-level bridge above."
        ),
    )


def _build_coq_surface(root: Path, *, probe_version: bool) -> SurfaceReport:
    coqc = probe_executable(["coqc"], probe_version=probe_version)
    coqtop = probe_executable(["coqtop"], probe_version=probe_version)
    rocq = probe_executable(["rocq"], probe_version=probe_version)
    modules = probe_modules(
        root,
        [
            (
                "ipfs_datasets_py/logic/external_provers/interactive/coq_prover_bridge.py",
                "bridge",
            ),
        ],
    )
    executables_ok = coqc.found or coqtop.found or rocq.found
    modules_ok = _any_module_exists(modules)
    available = executables_ok and modules_ok
    unavailable_reason = None
    if not available:
        reasons = []
        if not executables_ok:
            reasons.append(
                "no_coqc_coqtop_or_rocq_executable_found_on_path_or_common_install_dirs"
            )
        if not modules_ok:
            reasons.append("no_coq_bridge_module_in_repo")
        unavailable_reason = ";".join(reasons)
    return SurfaceReport(
        surface_id="coq",
        display_name="Coq / Rocq Prover",
        category="interactive_theorem_prover",
        executables={
            "coqc": coqc.to_dict(),
            "coqtop": coqtop.to_dict(),
            "rocq": rocq.to_dict(),
        },
        repo_modules=[m.to_dict() for m in modules],
        native_proof_trace_support=CapabilityNote(
            supported=executables_ok,
            mechanism=(
                "The Coq/Rocq kernel independently re-checks compiled proof "
                "terms (`coqc` producing a `.vo`, or `coqtop`/`rocq` "
                "interactively); a reconstruction is only accepted on a "
                "successful, warning-free kernel check. Coq was rebranded "
                "'Rocq' starting with the 9.x series — `coqc`/`coqtop` remain "
                "compatibility wrapper names."
            ),
            evidence=(["coqc", "coqtop", "rocq"] if executables_ok else []),
        ).to_dict(),
        parser_support=CapabilityNote(
            supported=modules_ok,
            mechanism=(
                "ipfs_datasets_py.logic.external_provers.interactive."
                "coq_prover_bridge wraps `coqc`/`coqtop` invocation and "
                "result parsing; it does not yet implement the HAMMER-006 "
                "native goal/hypothesis snapshot frontend."
            ),
            evidence=_module_paths(modules),
        ).to_dict(),
        available=available,
        unavailable_reason=unavailable_reason,
        notes=(
            "HAMMER-006 (ipfs_datasets_py/logic/hammers/frontends/coq.py) is "
            "still 'waiting' on the taskboard, so there is no native "
            "goal-snapshot adapter yet — only the lower-level bridge above."
        ),
    )


def _build_isabelle_surface(root: Path, *, probe_version: bool) -> SurfaceReport:
    isabelle = probe_executable(["isabelle"], probe_version=probe_version)
    modules = probe_modules(root, [])  # No Isabelle bridge/adapter exists in this repo yet.
    available = False
    reasons = []
    if not isabelle.found:
        reasons.append("isabelle_executable_not_found_on_path_or_common_install_dirs")
    reasons.append("no_isabelle_bridge_or_frontend_module_in_repo")
    return SurfaceReport(
        surface_id="isabelle",
        display_name="Isabelle/HOL",
        category="interactive_theorem_prover",
        executables={"isabelle": isabelle.to_dict()},
        repo_modules=[m.to_dict() for m in modules],
        native_proof_trace_support=CapabilityNote(
            supported=False,
            mechanism=(
                "Isabelle/HOL's LCF-style kernel natively re-checks proof "
                "terms produced by its tactic language, in principle making "
                "kernel-checked reconstruction possible. No such reconstruction "
                "path exists in this repository yet."
            ),
            evidence=[],
        ).to_dict(),
        parser_support=CapabilityNote(
            supported=False,
            mechanism=(
                "No Isabelle bridge, frontend, or theory-file parser exists "
                "under ipfs_datasets_py/logic at this revision."
            ),
            evidence=[],
        ).to_dict(),
        available=available,
        unavailable_reason=";".join(reasons),
        notes=(
            "Isabelle is named in the HAMMER-006 taskboard entry "
            "(ipfs_datasets_py/logic/hammers/frontends/isabelle.py) but that "
            "entry is still 'waiting' and no code for it exists yet, unlike "
            "Lean and Coq which already have lower-level bridges."
        ),
    )


def _build_z3_surface(root: Path, *, probe_version: bool) -> SurfaceReport:
    z3 = probe_executable(["z3"], probe_version=probe_version)
    modules = probe_modules(
        root,
        [
            ("ipfs_datasets_py/logic/external_provers/smt/z3_prover_bridge.py", "bridge"),
            (
                "ipfs_datasets_py/logic/security_models/crypto_exchange/compilers/to_z3.py",
                "compiler",
            ),
        ],
    )
    python_binding = _probe_top_level_python_module("z3")
    executables_ok = z3.found or python_binding["found"]
    modules_ok = _any_module_exists(modules)
    available = executables_ok and modules_ok
    unavailable_reason = None
    if not available:
        reasons = []
        if not z3.found:
            reasons.append("z3_executable_not_found_on_path_or_common_install_dirs")
        if not python_binding["found"]:
            reasons.append("z3_python_binding_not_importable")
        if not modules_ok:
            reasons.append("no_z3_bridge_module_in_repo")
        unavailable_reason = ";".join(reasons)
    return SurfaceReport(
        surface_id="z3",
        display_name="Z3 SMT Solver",
        category="smt_solver",
        executables={"z3": z3.to_dict(), "z3_python_binding": python_binding},
        repo_modules=[m.to_dict() for m in modules],
        native_proof_trace_support=CapabilityNote(
            supported=executables_ok,
            mechanism=(
                "Z3 can emit unsat cores (`(get-unsat-core)`) and proof "
                "objects (`(set-option :produce-proofs true)` + "
                "`(get-proof)`), and satisfying models "
                "(`(get-model)`) for `sat`/counterexample results. These are "
                "untrusted candidates per the HAMMER-001 trust contract until "
                "independently reconstructed."
            ),
            evidence=(["z3"] if z3.found else []) + (["z3 (python)"] if python_binding["found"] else []),
        ).to_dict(),
        parser_support=CapabilityNote(
            supported=modules_ok,
            mechanism=(
                "ipfs_datasets_py.logic.external_provers.smt.z3_prover_bridge "
                "wraps the z3 solver; "
                "ipfs_datasets_py/logic/security_models/crypto_exchange/"
                "compilers/to_z3.py compiles security-model IR to Z3 "
                "expressions via the z3 python API."
            ),
            evidence=_module_paths(modules),
        ).to_dict(),
        available=available,
        unavailable_reason=unavailable_reason,
        notes="Neither the `z3` CLI nor the `z3` python package is present in this environment.",
    )


def _build_cvc5_surface(root: Path, *, probe_version: bool) -> SurfaceReport:
    cvc5 = probe_executable(["cvc5"], probe_version=probe_version)
    modules = probe_modules(
        root,
        [
            ("ipfs_datasets_py/logic/external_provers/smt/cvc5_prover_bridge.py", "bridge"),
            (
                "ipfs_datasets_py/logic/security_models/crypto_exchange/runners/cvc5_runner.py",
                "runner",
            ),
        ],
    )
    python_binding = _probe_top_level_python_module("cvc5")
    executables_ok = cvc5.found or python_binding["found"]
    modules_ok = _any_module_exists(modules)
    available = executables_ok and modules_ok
    unavailable_reason = None
    if not available:
        reasons = []
        if not cvc5.found:
            reasons.append("cvc5_executable_not_found_on_path_or_common_install_dirs")
        if not python_binding["found"]:
            reasons.append("cvc5_python_binding_not_importable")
        if not modules_ok:
            reasons.append("no_cvc5_bridge_module_in_repo")
        unavailable_reason = ";".join(reasons)
    return SurfaceReport(
        surface_id="cvc5",
        display_name="CVC5 SMT Solver",
        category="smt_solver",
        executables={"cvc5": cvc5.to_dict(), "cvc5_python_binding": python_binding},
        repo_modules=[m.to_dict() for m in modules],
        native_proof_trace_support=CapabilityNote(
            supported=executables_ok,
            mechanism=(
                "CVC5 supports `--produce-proofs --proof-format-mode="
                "{alethe,lfsc,cpc}` for proof certificates and "
                "`--produce-models`/`--produce-unsat-cores` for "
                "counterexamples and unsat cores. These remain untrusted "
                "candidates per the HAMMER-001 trust contract."
            ),
            evidence=(["cvc5"] if cvc5.found else []) + (["cvc5 (python)"] if python_binding["found"] else []),
        ).to_dict(),
        parser_support=CapabilityNote(
            supported=modules_ok,
            mechanism=(
                "ipfs_datasets_py.logic.external_provers.smt."
                "cvc5_prover_bridge wraps the cvc5 solver; "
                "ipfs_datasets_py/logic/security_models/crypto_exchange/"
                "runners/cvc5_runner.py drives batch SMT-LIB query execution."
            ),
            evidence=_module_paths(modules),
        ).to_dict(),
        available=available,
        unavailable_reason=unavailable_reason,
        notes="The `cvc5` CLI is present in this environment; the python `cvc5` package is not.",
    )


def _build_vampire_surface(root: Path, *, probe_version: bool) -> SurfaceReport:
    vampire = probe_executable(["vampire"], probe_version=probe_version)
    modules = probe_modules(
        root,
        [
            ("ipfs_datasets_py/logic/CEC/provers/vampire_adapter.py", "adapter"),
            ("ipfs_datasets_py/logic/integration/bridges/external_provers.py", "bridge"),
        ],
    )
    modules_ok = _any_module_exists(modules)
    available = vampire.found and modules_ok
    unavailable_reason = None
    if not available:
        reasons = []
        if not vampire.found:
            reasons.append("vampire_executable_not_found_on_path_or_common_install_dirs")
        if not modules_ok:
            reasons.append("no_vampire_adapter_module_in_repo")
        unavailable_reason = ";".join(reasons)
    return SurfaceReport(
        surface_id="vampire",
        display_name="Vampire ATP",
        category="automated_theorem_prover",
        executables={"vampire": vampire.to_dict()},
        repo_modules=[m.to_dict() for m in modules],
        native_proof_trace_support=CapabilityNote(
            supported=vampire.found,
            mechanism=(
                "Vampire can emit a TPTP/TSTP derivation with `--proof tptp` "
                "and `--output_axiom_names on`, which is the untrusted proof "
                "candidate normalized by HAMMER-009."
            ),
            evidence=(["vampire"] if vampire.found else []),
        ).to_dict(),
        parser_support=CapabilityNote(
            supported=modules_ok,
            mechanism=(
                "ipfs_datasets_py.logic.CEC.provers.vampire_adapter builds "
                "TPTP problems (via tptp_utils) and invokes `vampire` as a "
                "subprocess, parsing its stdout into a VampireProofResult."
            ),
            evidence=_module_paths(modules),
        ).to_dict(),
        available=available,
        unavailable_reason=unavailable_reason,
        notes="The `vampire` executable is not present in this environment (download: https://vprover.github.io/).",
    )


def _build_e_prover_surface(root: Path, *, probe_version: bool) -> SurfaceReport:
    eprover = probe_executable(["eprover", "eprover-ho", "E"], probe_version=probe_version)
    modules = probe_modules(
        root,
        [
            ("ipfs_datasets_py/logic/CEC/provers/e_prover_adapter.py", "adapter"),
            ("ipfs_datasets_py/logic/integration/bridges/external_provers.py", "bridge"),
        ],
    )
    modules_ok = _any_module_exists(modules)
    available = eprover.found and modules_ok
    unavailable_reason = None
    if not available:
        reasons = []
        if not eprover.found:
            reasons.append("eprover_executable_not_found_on_path_or_common_install_dirs")
        if not modules_ok:
            reasons.append("no_e_prover_adapter_module_in_repo")
        unavailable_reason = ";".join(reasons)
    return SurfaceReport(
        surface_id="e",
        display_name="E Theorem Prover",
        category="automated_theorem_prover",
        executables={"eprover": eprover.to_dict()},
        repo_modules=[m.to_dict() for m in modules],
        native_proof_trace_support=CapabilityNote(
            supported=eprover.found,
            mechanism=(
                "E can emit a TSTP proof object with `--tstp-out` / "
                "`--proof-object`, which is the untrusted proof candidate "
                "normalized by HAMMER-009."
            ),
            evidence=(["eprover"] if eprover.found else []),
        ).to_dict(),
        parser_support=CapabilityNote(
            supported=modules_ok,
            mechanism=(
                "ipfs_datasets_py.logic.CEC.provers.e_prover_adapter builds "
                "TPTP problems (via tptp_utils) and invokes `eprover` as a "
                "subprocess, parsing its stdout into an EProverProofResult."
            ),
            evidence=_module_paths(modules),
        ).to_dict(),
        available=available,
        unavailable_reason=unavailable_reason,
        notes="No `eprover`/`eprover-ho`/`E` executable is present in this environment.",
    )


def _build_tptp_surface(root: Path, *, probe_version: bool) -> SurfaceReport:
    # TPTP4X is an optional reference format-validation/conversion tool, not
    # required for the writer/parser support already present in this repo.
    tptp4x = probe_executable(["tptp4X"], probe_version=probe_version)
    writer_modules = probe_modules(
        root,
        [
            ("ipfs_datasets_py/logic/CEC/provers/tptp_utils.py", "writer"),
        ],
    )
    parser_modules = probe_modules(
        root,
        [
            ("ipfs_datasets_py/logic/CEC/native/problem_parser.py", "parser"),
        ],
    )
    writer_ok = _any_module_exists(writer_modules)
    parser_ok = _any_module_exists(parser_modules)
    available = writer_ok or parser_ok
    unavailable_reason = None if available else "no_tptp_reader_or_writer_module_in_repo"
    return SurfaceReport(
        surface_id="tptp",
        display_name="TPTP (Thousands of Problems for Theorem Provers)",
        category="translation_format",
        executables={"tptp4X": tptp4x.to_dict()},
        repo_modules=[m.to_dict() for m in writer_modules + parser_modules],
        native_proof_trace_support=CapabilityNote(
            supported=writer_ok,
            mechanism=(
                "TPTP's companion proof-trace format, TSTP (used by Vampire "
                "and E, see the `vampire`/`e` surfaces above), is what the "
                "hammer pipeline normalizes into candidate evidence — TPTP "
                "itself is the *input* problem format."
            ),
            evidence=_module_paths(writer_modules),
        ).to_dict(),
        parser_support=CapabilityNote(
            supported=parser_ok,
            mechanism=(
                "ipfs_datasets_py.logic.CEC.native.problem_parser parses "
                "TPTP-format problem files (axiom/conjecture roles) into "
                "TPTPFormula records for ShadowProver; "
                "ipfs_datasets_py.logic.CEC.provers.tptp_utils writes CEC "
                "formulas out as TPTP problems for Vampire/E."
            ),
            evidence=_module_paths(parser_modules),
        ).to_dict(),
        available=available,
        unavailable_reason=unavailable_reason,
        notes=(
            "The optional `tptp4X` reference tool is not present in this "
            "environment; it is not required for the repo's own TPTP "
            "reader/writer support."
        ),
    )


def _build_smtlib_surface(root: Path, *, probe_version: bool) -> SurfaceReport:
    writer_modules = probe_modules(
        root,
        [
            (
                "ipfs_datasets_py/logic/security_models/crypto_exchange/compilers/to_smtlib.py",
                "writer",
            ),
            ("ipfs_datasets_py/logic/types/translation_types.py", "types"),
            ("ipfs_datasets_py/logic/types/fol_types.py", "types"),
            (
                "ipfs_datasets_py/logic/integration/converters/logic_translation_core.py",
                "translator",
            ),
        ],
    )
    writer_ok = _any_module_exists(writer_modules)
    available = writer_ok
    unavailable_reason = None if available else "no_smtlib_writer_module_in_repo"
    return SurfaceReport(
        surface_id="smtlib",
        display_name="SMT-LIB(2)",
        category="translation_format",
        executables={},
        repo_modules=[m.to_dict() for m in writer_modules],
        native_proof_trace_support=CapabilityNote(
            supported=writer_ok,
            mechanism=(
                "SMT-LIB models/unsat-cores/proofs come from the invoking "
                "solver (see the `z3`/`cvc5` surfaces above); SMT-LIB itself "
                "is the *query* format."
            ),
            evidence=_module_paths(writer_modules),
        ).to_dict(),
        parser_support=CapabilityNote(
            supported=False,
            mechanism=(
                "This repository only *generates* SMT-LIB2 text (see "
                "to_smtlib.py, logic_translation_core.SMTTranslator) via "
                "Python-side term construction and the z3/cvc5 python APIs. "
                "There is no standalone SMT-LIB *reader/parser* for "
                "arbitrary external `.smt2` input in ipfs_datasets_py at "
                "this revision — text is only ever produced, never parsed "
                "back."
            ),
            evidence=[],
        ).to_dict(),
        available=available,
        unavailable_reason=unavailable_reason,
        notes=(
            "SMT-LIB writer support exists; a dedicated SMT-LIB2 *parser* "
            "is an explicit gap this inventory surfaces for HAMMER-007 "
            "(typed translation to TPTP and SMT-LIB)."
        ),
    )


def _build_tdfol_surface(root: Path, *, probe_version: bool) -> SurfaceReport:
    modules = probe_modules(
        root,
        [
            ("ipfs_datasets_py/logic/TDFOL/tdfol_core.py", "core"),
            ("ipfs_datasets_py/logic/TDFOL/tdfol_parser.py", "parser"),
            ("ipfs_datasets_py/logic/TDFOL/tdfol_dcec_parser.py", "parser"),
            ("ipfs_datasets_py/logic/TDFOL/tdfol_prover.py", "prover"),
            ("ipfs_datasets_py/logic/TDFOL/tdfol_converter.py", "converter"),
        ],
    )
    core_present = any(m.exists for m in modules if m.kind == "core")
    prover_present = any(m.exists for m in modules if m.kind == "prover")
    parser_present = any(m.exists for m in modules if m.kind == "parser")
    available = core_present and prover_present
    unavailable_reason = None
    if not available:
        reasons = []
        if not core_present:
            reasons.append("no_tdfol_core_module_in_repo")
        if not prover_present:
            reasons.append("no_tdfol_prover_module_in_repo")
        unavailable_reason = ";".join(reasons)
    return SurfaceReport(
        surface_id="tdfol",
        display_name="TDFOL (Temporal Deontic First-Order Logic)",
        category="native_logic_framework",
        executables={},
        repo_modules=[m.to_dict() for m in modules],
        native_proof_trace_support=CapabilityNote(
            supported=prover_present,
            mechanism=(
                "ipfs_datasets_py.logic.TDFOL.tdfol_prover implements "
                "forward/backward chaining, modal tableaux, and temporal/"
                "deontic reasoning, producing `ProofResult`/`ProofStep` "
                "records (defined in tdfol_core.py) — a native, in-process "
                "proof trace, not an external solver certificate."
            ),
            evidence=_module_paths([m for m in modules if m.kind in ("core", "prover")]),
        ).to_dict(),
        parser_support=CapabilityNote(
            supported=parser_present,
            mechanism=(
                "ipfs_datasets_py.logic.TDFOL.tdfol_parser parses symbolic, "
                "natural-language, and JSON/dict representations into TDFOL "
                "formulas; tdfol_dcec_parser bridges TDFOL and DCEC/CEC "
                "syntax; tdfol_converter round-trips TDFOL to string "
                "representations (TPTP, SMT-LIB, etc.)."
            ),
            evidence=_module_paths([m for m in modules if m.kind == "parser" or m.kind == "converter"]),
        ).to_dict(),
        available=available,
        unavailable_reason=unavailable_reason,
        notes=(
            "TDFOL is an in-repo, pure-Python logic framework — its "
            "'availability' is a static source-file presence check, not an "
            "external executable/install check."
        ),
    )


def _build_cec_surface(root: Path, *, probe_version: bool) -> SurfaceReport:
    modules = probe_modules(
        root,
        [
            ("ipfs_datasets_py/logic/CEC/native/dcec_core.py", "core"),
            ("ipfs_datasets_py/logic/CEC/native/prover_core.py", "prover"),
            ("ipfs_datasets_py/logic/CEC/native/shadow_prover.py", "prover"),
            ("ipfs_datasets_py/logic/CEC/native/problem_parser.py", "parser"),
            ("ipfs_datasets_py/logic/CEC/provers/prover_manager.py", "prover_manager"),
            ("ipfs_datasets_py/logic/CEC/provers/vampire_adapter.py", "adapter"),
            ("ipfs_datasets_py/logic/CEC/provers/e_prover_adapter.py", "adapter"),
        ],
    )
    core_present = any(m.exists for m in modules if m.kind == "core")
    prover_present = any(m.exists for m in modules if m.kind in ("prover", "prover_manager"))
    parser_present = any(m.exists for m in modules if m.kind == "parser")
    available = core_present and prover_present
    unavailable_reason = None
    if not available:
        reasons = []
        if not core_present:
            reasons.append("no_cec_dcec_core_module_in_repo")
        if not prover_present:
            reasons.append("no_cec_native_prover_module_in_repo")
        unavailable_reason = ";".join(reasons)
    return SurfaceReport(
        surface_id="cec",
        display_name="CEC (Cognitive Event Calculus / DCEC)",
        category="native_logic_framework",
        executables={},
        repo_modules=[m.to_dict() for m in modules],
        native_proof_trace_support=CapabilityNote(
            supported=prover_present,
            mechanism=(
                "ipfs_datasets_py.logic.CEC.native.prover_core implements a "
                "native inference-rule engine (documented as covering 87 "
                "rules) and ipfs_datasets_py.logic.CEC.native.shadow_prover "
                "provides ShadowProver-style modal proof search, both "
                "producing an in-process proof trace independent of any "
                "external solver. ipfs_datasets_py.logic.CEC.provers."
                "prover_manager additionally coordinates external Z3/"
                "Vampire/E attempts (see those surfaces) as untrusted "
                "candidates."
            ),
            evidence=_module_paths([m for m in modules if m.kind in ("core", "prover", "prover_manager")]),
        ).to_dict(),
        parser_support=CapabilityNote(
            supported=parser_present,
            mechanism=(
                "ipfs_datasets_py.logic.CEC.native.problem_parser parses "
                "TPTP-format and ShadowProver-native problem files into "
                "DCEC/CEC-compatible structures."
            ),
            evidence=_module_paths([m for m in modules if m.kind == "parser"]),
        ).to_dict(),
        available=available,
        unavailable_reason=unavailable_reason,
        notes=(
            "CEC is an in-repo, pure-Python logic framework (with vendored "
            "ShadowProver/Talos/DCEC_Library components) — its "
            "'availability' is a static source-file presence check. It also "
            "wires up the external vampire/e-prover adapters inventoried as "
            "their own surfaces above."
        ),
    )


def _build_prover_installer_surface(root: Path, *, probe_version: bool) -> SurfaceReport:
    modules = probe_modules(
        root,
        [
            ("ipfs_datasets_py/logic/external_provers/lazy_installer.py", "lazy_installer"),
            ("ipfs_datasets_py/logic/integration/bridges/prover_installer.py", "cli_installer"),
            ("ipfs_datasets_py/logic/external_provers/prover_router.py", "router"),
        ],
    )
    lazy_installer_present = any(m.exists for m in modules if m.kind == "lazy_installer")
    cli_installer_present = any(m.exists for m in modules if m.kind == "cli_installer")
    available = lazy_installer_present or cli_installer_present
    unavailable_reason = None if available else "no_prover_installer_module_in_repo"
    return SurfaceReport(
        surface_id="prover_installer",
        display_name="Prover installer surfaces",
        category="prover_installer",
        executables={},
        repo_modules=[m.to_dict() for m in modules],
        native_proof_trace_support=CapabilityNote(
            supported=False,
            mechanism=(
                "The installer surfaces do not themselves produce proof "
                "traces; they exist only to make an executable available "
                "for the surfaces above to invoke."
            ),
            evidence=[],
        ).to_dict(),
        parser_support=CapabilityNote(
            supported=False,
            mechanism="Not applicable — installers do not parse proof content.",
            evidence=[],
        ).to_dict(),
        available=available,
        unavailable_reason=unavailable_reason,
        notes=(
            "ipfs_datasets_py.logic.external_provers.lazy_installer performs "
            "an opt-in, single best-effort install for a requested prover "
            "(gated by IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS / per-prover "
            "IPFS_DATASETS_PY_LAZY_INSTALL_<PROVER> env vars — disabled "
            "unless explicitly enabled); "
            "ipfs_datasets_py.logic.integration.bridges.prover_installer "
            "exposes the same behavior as the `ipfs-datasets-install-provers` "
            "console script; ipfs_datasets_py.logic.external_provers."
            "prover_router discovers/selects among already-installed "
            "provers at runtime. This probe script never calls any of "
            "these — it only checks whether their source files exist in "
            "this checkout."
        ),
    )


def _probe_top_level_python_module(module_name: str) -> Dict[str, Any]:
    """Report whether a *top-level, independent* (non-``ipfs_datasets_py``)
    python module is importable, using ``importlib.util.find_spec`` so the
    module is only located, never executed. Restricted to modules with no
    ``ipfs_datasets_py`` parent package so this never triggers the package's
    own (heavier) import chain."""

    import importlib.util

    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ValueError, ModuleNotFoundError):
        spec = None
    return {"module": module_name, "found": spec is not None}


# ---------------------------------------------------------------------------
# Top-level report assembly
# ---------------------------------------------------------------------------

_SURFACE_BUILDERS = (
    _build_lean_surface,
    _build_coq_surface,
    _build_isabelle_surface,
    _build_z3_surface,
    _build_cvc5_surface,
    _build_vampire_surface,
    _build_e_prover_surface,
    _build_tptp_surface,
    _build_smtlib_surface,
    _build_tdfol_surface,
    _build_cec_surface,
    _build_prover_installer_surface,
)


def build_environment_report(
    *,
    repo_root: Optional[Path] = None,
    probe_version: bool = True,
) -> Dict[str, Any]:
    """Build the full ITP hammer environment/capability inventory.

    Args:
        repo_root: Repository root to resolve relative module paths
            against. Defaults to the checkout containing this script.
        probe_version: When true (the default), run a single bounded
            ``--version``-style subprocess call for each executable that was
            *already found* on disk. This never installs or invokes a
            solver's proof-search entry point. Pass ``False`` for a fully
            hermetic run that performs zero subprocess calls.
    """

    root = repo_root if repo_root is not None else _repo_root()
    surfaces = {}
    for builder in _SURFACE_BUILDERS:
        report = builder(root, probe_version=probe_version)
        surfaces[report.surface_id] = report.to_dict()

    available_count = sum(1 for surface in surfaces.values() if surface["available"])
    unavailable = sorted(
        surface_id for surface_id, surface in surfaces.items() if not surface["available"]
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "probe_options": {
            "version_probe_enabled": probe_version,
            "install_attempted": False,
            "solver_invoked": False,
        },
        "surfaces": surfaces,
        "summary": {
            "surface_count": len(surfaces),
            "available_count": available_count,
            "unavailable_count": len(surfaces) - available_count,
            "unavailable_surfaces": unavailable,
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output JSON path (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root to resolve relative module paths against (default: this checkout)",
    )
    parser.add_argument(
        "--no-version-probe",
        dest="probe_version",
        action="store_false",
        help=(
            "Skip all --version-style subprocess calls; only perform static "
            "executable-path and repo-module-presence discovery (zero "
            "subprocess calls)."
        ),
    )
    parser.set_defaults(probe_version=True)
    args = parser.parse_args(argv)

    report = build_environment_report(repo_root=args.repo_root, probe_version=args.probe_version)

    out_path = args.out
    if not out_path.is_absolute():
        out_path = (args.repo_root or _repo_root()) / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "out": out_path.as_posix(),
                "surface_count": report["summary"]["surface_count"],
                "available_count": report["summary"]["available_count"],
                "unavailable_surfaces": report["summary"]["unavailable_surfaces"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
