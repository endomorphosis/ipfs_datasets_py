"""Read-only Isabelle diagnostics and explicit, lazy setup.

Run: python -m ipfs_datasets_py.logic.external_provers.isabelle_setup --smoke
Only --install can download. Installation, installed-runtime inspection and
smoke use shared admission and bounded workers. Explicit --build-hol rebuilds
persistent staged system heaps; without --install it requires a verified cache.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import sys
import json
import math
import time


def _preparation_report(evidence: dict, *, usable: bool, command_available: bool,
                        smoke_accepted: bool, readiness_level: str,
                        reason_code: str, smoke: bool) -> dict:
    """Map an owner's completed observation without promoting earlier phases."""
    runtime = evidence.get("native_runtime") or {}
    available = usable and command_available
    capability = {
        "itp": "isabelle", "available": available,
        "executables": {"isabelle": {"found": bool(runtime.get("executable")),
            "path": runtime.get("executable"), "version": runtime.get("version"),
            "version_probe_error": None if available else reason_code,
            "theory_processing_ready": available}},
        "unavailable_reason": None if available else reason_code,
        "notes": "Admitted bounded installed-runtime observation; the path is the actual inner executable probed.",
    }
    smoke_report = None
    if smoke:
        observation = next((probe.get("observation") for probe in evidence.get("probes", ())
                            if probe.get("phase") == "smoke"), None)
        smoke_report = {"accepted": usable and smoke_accepted, "result": observation}
    return {"installation": None, "capability": capability, "smoke": smoke_report,
            "ready": usable,
            "readiness_level": readiness_level if usable else (
                "smoke_failed" if smoke else "unavailable"),
            "bounded_preparation": evidence}


def _installed_report(*, smoke: bool = False, timeout: float = 120,
                      install_root=None, executable=None) -> dict:
    from ..backends.installers.isabelle_preparation import prepare_isabelle_runtime
    prepared = prepare_isabelle_runtime(mode="smoke" if smoke else "command",
        timeout_seconds=min(timeout, 300), install_root=install_root, executable=executable)
    return _preparation_report(prepared.to_dict(), usable=prepared.usable,
        command_available=prepared.command_available, smoke_accepted=prepared.smoke_accepted,
        readiness_level=prepared.readiness_level, reason_code=prepared.reason_code, smoke=smoke)


def inspect_isabelle(executable: str = "isabelle", *, timeout: float = 120) -> dict:
    """Inspect an installed runtime through default shared admission."""
    return _installed_report(timeout=timeout,
        executable=None if executable == "isabelle" else executable)["capability"]


def ensure_isabelle_ready(*, install: bool = False, build_hol: bool = False,
                          smoke: bool = False, timeout: float | None = None, install_root: str | None = None) -> dict:
    """Observe, install or rebuild within one admission-inclusive deadline.

    Installation owns staging, an optional persistent HOL rebuild, publication
    and final readiness. Only install=True permits downloading archive bytes;
    build_hol=True alone requires a verified retained archive. Required rollback
    or process cleanup can outlast the requested deadline. Omitted timeout uses
    3600 seconds for a build, 600 for installation, and 120 for observation.
    """
    if timeout is None:
        timeout = 3600 if build_hol else 600 if install else 120
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ValueError("timeout must be finite and between 0 and 3600 seconds")
    if not install and not build_hol:
        return _installed_report(smoke=smoke, timeout=timeout, install_root=install_root)
    deadline = time.monotonic() + timeout

    def remaining():
        return max(0.0, deadline - time.monotonic())

    def expired(report):
        report["ready"] = False
        report["readiness_level"] = "setup_deadline_exceeded"
        report["capability"]["available"] = False
        report["capability"]["unavailable_reason"] = "setup_deadline_exceeded"
        executable = report["capability"]["executables"]["isabelle"]
        executable.update(theory_processing_ready=False, version_probe_error="setup_deadline_exceeded")
        if report.get("smoke") is not None:
            report["smoke"]["accepted"] = False
        return report

    from ..backends.installers.isabelle_installation import ensure_isabelle_installation
    budget = remaining()
    if budget <= 0:
        return expired(_preparation_report({}, usable=False, command_available=False,
            smoke_accepted=False, readiness_level="unavailable",
            reason_code="setup_deadline_exceeded", smoke=smoke))
    # The build flag itself authorizes replacement, while only the install flag
    # authorizes obtaining new archive bytes. The worker enforces that policy.
    receipt = ensure_isabelle_installation(yes=True, strict=False,
        install_root=install_root, timeout_seconds=budget,
        build_hol=build_hol, allow_download=install)
    installation = receipt.to_dict()
    prepared = installation.get("preparation") or {}
    build = installation.get("hol_build") or {}
    usable = receipt.usable and prepared.get("usable") is True
    reasons = installation.get("reason_codes") or ["installation_failed"]
    if build_hol and not (build.get("build_succeeded") is True
                          and build.get("persistent_heap_published") is True):
        usable = False
        if receipt.usable:
            reasons = ["persistent_hol_build_not_published"]
    report = _preparation_report(prepared, usable=usable,
        command_available=prepared.get("command_available") is True,
        smoke_accepted=prepared.get("smoke_accepted") is True,
        readiness_level=prepared.get("readiness_level", "unavailable"),
        reason_code=prepared.get("reason_code") if usable else reasons[0], smoke=smoke)
    report["installation"] = {"successful": usable, "receipt": installation}
    if build_hol:
        observed = build.get("observation") or {}
        # Retain the existing returncode/error accessors without treating an
        # exit code alone as evidence that persistent heaps were published.
        report["hol_build"] = {"returncode": observed.get("returncode"),
            "error": observed.get("error") or (None if usable else reasons[0]), "build": build}
        report["hol_build_scope"] = ("Fixed HOL rebuild in unpublished staged system heaps, "
            "with shared admission and bounded execution; publication requires final native readiness.")
    report["timeout_scope"] = "One setup deadline including admission and phase execution; required cleanup may overrun."
    if remaining() <= 0:
        return expired(report)
    if not report["capability"]["available"]:
        report["ready"] = False
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--install-root", help="Explicit isolated user-local distribution directory")
    parser.add_argument("--build-hol", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--timeout", type=float, default=None,
                        help="Total seconds including admission (defaults: inspect 120, install 600, build 3600)")
    args = parser.parse_args()
    if args.timeout is not None and not 0 < args.timeout <= 3600:
        parser.error("timeout must be between 0 and 3600 seconds")
    # Installer progress belongs on stderr; stdout remains a single JSON report.
    with redirect_stdout(sys.stderr):
        report = ensure_isabelle_ready(install=args.install, build_hol=args.build_hol,
                                      smoke=args.smoke, timeout=args.timeout, install_root=args.install_root)
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
