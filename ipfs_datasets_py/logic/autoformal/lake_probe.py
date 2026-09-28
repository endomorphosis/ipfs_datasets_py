"""Probe ``lake build Legal`` on compiled autoformal norms.

A successful Lake build is not a legal admit. This module does not write the
project tree and refuses imports, sorry, admit, and axiom.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


MAX_SOURCE = 16_384
_MODALITY_CODE = {
    "obligation": 0,
    "permission": 1,
    "prohibition": 2,
    "O": 0,
    "P": 1,
    "F": 2,
}
# Stand-ins for operators that are not a duty of a named actor.
# These are definitional fixtures. The Lean keyword axiom stays refused.
_FIXTURE_CODE = {
    "B": 3,
    "belief": 3,
    "K": 4,
    "knowledge": 4,
    "actorless_F": 5,
    "Frame": 6,
    "frame": 6,
}
FIXTURE_BEARER = "fixture:bearer"


class LakeProbeError(RuntimeError):
    """Lake cannot be invoked without inventing a proof."""


def pattern_from_rule(rule: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Lock a duty's modality and a fingerprint of its text. Not a proof."""

    if not isinstance(rule, Mapping):
        return None
    modality = str(rule.get("modality") or "")
    if modality not in _MODALITY_CODE:
        return None
    actor = str(rule.get("actor") or "").strip()
    action = str(rule.get("action") or "").strip()
    if not actor or not action:
        return None
    payload = "\n".join((modality, actor, action, str(rule.get("object") or "").strip()))
    fingerprint = int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8], 16)
    return {"kind": "norm", "modality": _MODALITY_CODE[modality], "fingerprint": fingerprint}


def pattern_from_fixture(rule: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Lock a belief, knowledge, frame, or actorless prohibition fixture. Not a proof."""

    if not isinstance(rule, Mapping):
        return None
    modality = str(rule.get("modality") or "")
    action = str(rule.get("action") or "").strip()
    if not action:
        return None
    actor = str(rule.get("actor") or "").strip()
    if modality in {"B", "belief", "K", "knowledge"}:
        code_name = "B" if modality in {"B", "belief"} else "K"
        bearer = actor or FIXTURE_BEARER
    elif modality in {"F", "prohibition"} and not actor:
        code_name = "actorless_F"
        bearer = FIXTURE_BEARER
    elif modality in {"Frame", "frame"}:
        code_name = "Frame"
        bearer = actor or FIXTURE_BEARER
    else:
        return None
    payload = "\n".join(
        ("fixture", code_name, bearer, action, str(rule.get("object") or "").strip())
    )
    fingerprint = int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8], 16)
    return {
        "bearer": bearer,
        "fixture": code_name,
        "fingerprint": fingerprint,
        "kind": "fixture",
        "modality": _FIXTURE_CODE[code_name],
    }


def render_fixture(pattern: Mapping[str, Any], *, suffix: str = "") -> str:
    """Definitional stand-in. Does not emit a Lean axiom."""

    kind = int(pattern["modality"])
    fingerprint = int(pattern["fingerprint"])
    return (
        f"def fixtureKindCode{suffix} : Nat := {kind}\n"
        f"def fixtureFingerprint{suffix} : Nat := {fingerprint}\n"
        f"def fixtureLocked{suffix} (k f : Nat) : Bool := decide (k = fixtureKindCode{suffix} /\\ f = fixtureFingerprint{suffix})\n"
        f"theorem fixtureBoundary{suffix} : fixtureLocked{suffix} fixtureKindCode{suffix} fixtureFingerprint{suffix} = true := by\n"
        f"  unfold fixtureLocked{suffix} fixtureKindCode{suffix} fixtureFingerprint{suffix}\n"
        "  decide\n"
    )


def render_norm(pattern: Mapping[str, Any], *, suffix: str = "") -> str:
    modality = int(pattern["modality"])
    fingerprint = int(pattern["fingerprint"])
    return (
        f"def modalityCode{suffix} : Nat := {modality}\n"
        f"def normFingerprint{suffix} : Nat := {fingerprint}\n"
        f"def normLocked{suffix} (m f : Nat) : Bool := decide (m <= 2 /\\ f = normFingerprint{suffix})\n"
        f"theorem normBoundary{suffix} : normLocked{suffix} modalityCode{suffix} normFingerprint{suffix} = true := by\n"
        f"  unfold normLocked{suffix} modalityCode{suffix} normFingerprint{suffix}\n"
        "  decide\n"
    )


def render_logic_batch(rules: Sequence[Mapping[str, Any]]) -> tuple[str, int]:
    """Render norm fingerprints and stitch fixtures. A fixture is not a duty."""

    pieces: list[str] = []
    count = 0
    size = 0
    for rule in rules:
        norm = pattern_from_rule(rule)
        fixture = None if norm is not None else pattern_from_fixture(rule)
        if norm is not None:
            piece = render_norm(norm, suffix=str(count))
        elif fixture is not None:
            piece = render_fixture(fixture, suffix=str(count))
        else:
            continue
        encoded = len(piece.encode("utf-8"))
        if size + encoded > MAX_SOURCE:
            break
        pieces.append(piece)
        size += encoded
        count += 1
    return "".join(pieces), count


def render_norm_batch(rules: Sequence[Mapping[str, Any]]) -> tuple[str, int]:
    pieces: list[str] = []
    count = 0
    size = 0
    for rule in rules:
        pattern = pattern_from_rule(rule)
        if pattern is None:
            continue
        piece = render_norm(pattern, suffix=str(count))
        encoded = len(piece.encode("utf-8"))
        if size + encoded > MAX_SOURCE:
            break
        pieces.append(piece)
        size += encoded
        count += 1
    return "".join(pieces), count


def _lean_toolchain() -> str:
    lean = shutil.which("lean") or lake_executable()
    if lean:
        try:
            proc = subprocess.run(
                [lean, "--version"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            match = re.search(r"(\d+\.\d+\.\d+)", proc.stdout or proc.stderr or "")
            if match:
                return f"leanprover/lean4:v{match.group(1)}\n"
        except (OSError, subprocess.TimeoutExpired):
            pass
    return "leanprover/lean4:v4.26.0\n"


def lake_executable() -> str | None:
    extra = str(Path.home() / ".elan" / "bin")
    path = os.environ.get("PATH", "")
    if extra not in path.split(os.pathsep):
        os.environ["PATH"] = extra + os.pathsep + path
    found = shutil.which("lake")
    return found


def lake_check(source: str, *, timeout: int = 180) -> dict[str, Any]:
    """Compile one self-contained Lean file with ``lake build Legal``."""

    raw = str(source or "")
    if "import " in raw or raw.lstrip().startswith("import"):
        return {"lake_ok": False, "error": "imports_refused", "log": "", "admitted": False, "formalized": False}
    body = raw.strip()
    if not body:
        return {"lake_ok": False, "error": "empty", "log": "", "admitted": False, "formalized": False}
    if len(body.encode()) > MAX_SOURCE:
        return {"lake_ok": False, "error": "source_too_large", "log": "", "admitted": False, "formalized": False}
    words = set(body.split())
    if words & {"sorry", "admit", "axiom"}:
        return {"lake_ok": False, "error": "sorry_or_axiom", "log": "", "admitted": False, "formalized": False}
    lake = lake_executable()
    if not lake:
        return {"lake_ok": False, "error": "lake_not_on_path", "log": "", "admitted": False, "formalized": False}
    pkg = Path(tempfile.mkdtemp(prefix="autoformal-lake-"))
    (pkg / "lean-toolchain").write_text(_lean_toolchain(), encoding="utf-8")
    (pkg / "lakefile.lean").write_text(
        "import Lake\nopen Lake DSL\n\npackage «legal»\n\n@[default_target]\nlean_lib Legal\n",
        encoding="utf-8",
    )
    (pkg / "Legal.lean").write_text(body + "\n", encoding="utf-8")
    try:
        proc = subprocess.run(
            [lake, "build", "Legal"],
            cwd=pkg,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=dict(os.environ),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "lake_ok": False,
            "error": type(exc).__name__,
            "log": str(exc)[:2000],
            "admitted": False,
            "formalized": False,
        }
    output = ((proc.stdout or "") + (proc.stderr or ""))[-8000:]
    errors = "\n".join(line for line in output.splitlines() if line.startswith("error:"))[:2000]
    ok = proc.returncode == 0 and "error:" not in output and "Built Legal" in output
    return {
        "lake_ok": ok,
        "error": "" if ok else (errors or "build_failed"),
        "log": output,
        "returncode": proc.returncode,
        "admitted": False,
        "formalized": False,
    }


def probe_census_rules(
    rules: Sequence[Mapping[str, Any]],
    *,
    check: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """One ``lake build Legal`` for the compiled norms of a census round."""

    source, count = render_norm_batch(rules)
    receipt = {
        "admitted": False,
        "formalized": False,
        "lake_ok": False,
        "error": "no_renderable_norms",
        "log": "",
        "theorem_count": count,
        "target": "Legal",
    }
    if count < 1 or not source.strip():
        return receipt
    checked = dict((check or lake_check)(source))
    receipt.update(checked)
    receipt["theorem_count"] = count
    receipt["target"] = "Legal"
    receipt["admitted"] = False
    receipt["formalized"] = False
    return receipt
