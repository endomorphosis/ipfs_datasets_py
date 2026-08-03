"""Reviewed SMT installer adapters for the public transactional facade.

The adapters add typed dry-run/offline/authorization receipts around the
existing production installers.  No probe, import-time action, or dry run
invokes pip, downloads an archive, or imports an optional solver binding.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any, Final

from .registry import authorize_installer_entry_install

INTERFACE: Final = "SMTSolverInstaller@1"
SCHEMA_VERSION: Final = "smt-solver-install-receipt/v1"


@dataclass(slots=True)
class InstallReceipt:
    tool_id: str
    requested_version: str
    status: str = "blocked"
    phase: str = "init"
    installed: bool = False
    already_present: bool = False
    checksum_verified: bool = False
    executable_path: str = ""
    reason_codes: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    bindings: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _blocked(receipt: InstallReceipt, reason: str, message: str) -> InstallReceipt:
    receipt.status = "blocked"
    receipt.phase = reason
    receipt.reason_codes.append(reason)
    receipt.messages.append(message)
    return receipt


def _z3_semantic_probe() -> dict[str, Any]:
    try:
        import z3

        atom = z3.Bool("ipfs_datasets_py_lazy_installer_probe")
        solver = z3.Solver()
        solver.add(atom, z3.Not(atom))
        outcome = str(solver.check())
        return {"contradiction_is_unsat": outcome == "unsat", "outcome": outcome}
    except Exception as exc:
        return {"contradiction_is_unsat": False, "error_type": type(exc).__name__}


def _cvc5_semantic_probe(path: str) -> dict[str, Any]:
    try:
        version = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        semantic = subprocess.run(
            [path, "--lang", "smt2"],
            input="(set-logic QF_UF)\n(declare-fun p () Bool)\n(assert p)\n(check-sat)\n",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        banner = f"{version.stdout}\n{version.stderr}"
        outcome = semantic.stdout.strip().splitlines()
        return {
            "exact_version": version.returncode == 0 and "1.3.3" in banner,
            "positive_sat": semantic.returncode == 0 and outcome[-1:] == ["sat"],
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"exact_version": False, "positive_sat": False, "error_type": type(exc).__name__}


def ensure_z3(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    on_progress: Callable[[str, str], None] | None = None,
    dry_run: bool = False,
    offline: bool = False,
    **_: Any,
) -> InstallReceipt:
    receipt = InstallReceipt("z3", ">=4.12.0,<5.0.0")
    present = importlib.util.find_spec("z3") is not None
    if present and not force:
        try:
            package_version = metadata.version("z3-solver")
        except metadata.PackageNotFoundError:
            package_version = "unknown"
        semantic = _z3_semantic_probe()
        receipt.status = "available"
        receipt.phase = "available"
        receipt.installed = True
        receipt.already_present = True
        receipt.bindings.update(
            {
                "package_identity": f"z3-solver:{package_version}",
                "semantic_probe": semantic,
                "transactional_publication": False,
                "system_package_mutation": False,
            }
        )
        return receipt
    if dry_run:
        receipt.status = "planned"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        return receipt
    if offline:
        return _blocked(receipt, "offline_policy", "offline mode forbids pip installation")
    if not yes:
        return _blocked(receipt, "yes_required", "yes=True is required")
    del strict, on_progress
    authorize_installer_entry_install("z3", yes=True)
    return _blocked(
        receipt,
        "transactional_user_local_installer_unavailable",
        (
            "the legacy Z3 helper mutates the active Python environment; "
            "install the pinned theorem-prover extra into an isolated environment"
        ),
    )


def ensure_cvc5(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    on_progress: Callable[[str, str], None] | None = None,
    dry_run: bool = False,
    offline: bool = False,
    **_: Any,
) -> InstallReceipt:
    receipt = InstallReceipt("cvc5", "1.3.3")
    present = shutil.which("cvc5")
    if present and not force:
        semantic = _cvc5_semantic_probe(str(Path(present).resolve()))
        receipt.status = "available"
        receipt.phase = "available"
        receipt.installed = True
        receipt.already_present = True
        receipt.executable_path = str(Path(present).resolve())
        receipt.bindings["semantic_probe"] = semantic
        return receipt
    if dry_run:
        receipt.status = "planned"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        return receipt
    if offline:
        return _blocked(receipt, "offline_policy", "offline mode forbids archive installation")
    if not yes:
        return _blocked(receipt, "yes_required", "yes=True is required")
    authorize_installer_entry_install("cvc5", yes=True)
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    ok = prover_installer.ensure_cvc5_cli(
        yes=True, strict=strict, force=force, on_progress=on_progress
    )
    executable = shutil.which("cvc5") or ""
    semantic = _cvc5_semantic_probe(executable) if executable else {}
    semantic_ok = bool(
        semantic.get("exact_version") and semantic.get("positive_sat")
    )
    receipt.status = "installed" if ok and semantic_ok else "failed"
    receipt.phase = receipt.status
    receipt.installed = bool(ok and semantic_ok)
    receipt.executable_path = str(Path(executable).resolve()) if executable else ""
    receipt.bindings.update(
        {
            "managed_release": "cvc5-1.3.3",
            "checksum_verification_owned_by_delegate": True,
            "semantic_probe": semantic,
            "transactional_publication": False,
            "system_package_mutation": False,
        }
    )
    return receipt


__all__ = ["INTERFACE", "SCHEMA_VERSION", "InstallReceipt", "ensure_z3", "ensure_cvc5"]
