"""Reviewed Lean kernel installer adapter with exact post-install identity."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final

from .registry import authorize_installer_entry_install

INTERFACE: Final = "LeanKernelInstaller@1"
SCHEMA_VERSION: Final = "lean-kernel-install-receipt/v1"
LEAN_TOOLCHAIN: Final = "leanprover/lean4:v4.31.0"
LEAN_VERSION: Final = "4.31.0"


@dataclass(slots=True)
class InstallReceipt:
    tool_id: str = "lean"
    requested_version: str = LEAN_TOOLCHAIN
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


def _lean_path() -> str:
    found = shutil.which("lean")
    if found:
        return found
    candidate = Path.home() / ".elan" / "bin" / "lean"
    return str(candidate) if candidate.is_file() else ""


def _exact_version(path: str) -> tuple[bool, str]:
    if not path:
        return False, ""
    try:
        completed = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    banner = f"{completed.stdout}\n{completed.stderr}".strip()
    return completed.returncode == 0 and LEAN_VERSION in banner, banner


def _kernel_semantic_probe(path: str) -> dict[str, Any]:
    try:
        with tempfile.TemporaryDirectory(prefix="lean-kernel-probe-") as directory:
            root = Path(directory)
            valid = root / "Valid.lean"
            invalid = root / "Invalid.lean"
            valid.write_text("example : True := by trivial\n", encoding="utf-8")
            invalid.write_text("example : False := by trivial\n", encoding="utf-8")
            accepted = subprocess.run(
                [path, str(valid)],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            rejected = subprocess.run(
                [path, str(invalid)],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        return {
            "valid_theorem_accepted": accepted.returncode == 0,
            "invalid_theorem_rejected": rejected.returncode != 0,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "valid_theorem_accepted": False,
            "invalid_theorem_rejected": False,
            "error_type": type(exc).__name__,
        }


def ensure_lean(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    on_progress: Callable[[str, str], None] | None = None,
    dry_run: bool = False,
    offline: bool = False,
    **_: Any,
) -> InstallReceipt:
    receipt = InstallReceipt()
    if dry_run:
        receipt.status = "planned"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        return receipt
    if offline:
        receipt.status = "blocked"
        receipt.phase = "offline_policy"
        receipt.reason_codes.append("offline_policy")
        receipt.messages.append("offline mode performs no executable command or install")
        return receipt
    path = _lean_path()
    version_ok, banner = _exact_version(path)
    if version_ok and not force:
        semantic = _kernel_semantic_probe(path)
        receipt.status = "available"
        receipt.phase = "available"
        receipt.installed = True
        receipt.already_present = True
        receipt.executable_path = str(Path(path).resolve())
        receipt.bindings.update(
            {
                "toolchain_identity": LEAN_TOOLCHAIN,
                "version_banner": banner,
                "semantic_probe": semantic,
                "transactional_publication": False,
            }
        )
        return receipt
    if not yes:
        receipt.status = "blocked"
        receipt.phase = "yes_required"
        receipt.reason_codes.append("yes_required")
        return receipt
    authorize_installer_entry_install("lean", yes=True)
    del strict, on_progress
    receipt.status = "blocked"
    receipt.phase = "checksummed_artifact_unavailable"
    receipt.reason_codes.append("checksummed_artifact_unavailable")
    receipt.messages.append(
        "the legacy Lean helper executes an unchecksummed elan/master bootstrap; "
        "provide the locked toolchain through reviewed deployment packaging"
    )
    return receipt


__all__ = ["INTERFACE", "SCHEMA_VERSION", "InstallReceipt", "ensure_lean"]
