#!/usr/bin/env python3
"""Plan, install, update, and verify optional theorem-prover solver lanes.

The default mode is read-only.  ``--install`` and ``--update`` call the
package's user-local installer with an explicit ``--yes`` acknowledgement and
record every emitted stage in the JSON report.  This keeps long downloads,
OPAM switch creation, and source builds visible to both terminals and UIs.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import inspect
import subprocess
from typing import Any, Callable, Mapping, Sequence


SCHEMA_VERSION = "optional-theorem-solver-install-report/v2"
TASK_ID = "PORTAL-CXTP-086"
DEFAULT_SOLVER_PROBE = Path("security_ir_artifacts/environment/solver-dependency-probe.json")
DEFAULT_OUT = Path("security_ir_artifacts/environment/optional-solver-install-report.json")
POLICY_DOCUMENT = "docs/security_verification/optional_solver_installation.md"
INSTALLER_MODULE = "ipfs_datasets_py.logic.integration.bridges.prover_installer"
DEFAULT_LEAN_REPORT = Path("security_ir_artifacts/environment/lean-solver-lane-report.json")
LEANSTRAL_APPROVED_ROUTES = ("labs-leanstral-1-5", "labs-leanstral-2603")
LEANSTRAL_MODEL_ENV_VARS = (
    "IPFS_DATASETS_PY_LEANSTRAL_MODEL",
    "IPFS_DATASETS_PY_OPENAI_MODEL",
    "IPFS_DATASETS_PY_OPENROUTER_MODEL",
    "IPFS_DATASETS_PY_LLM_MODEL",
    "IPFS_DATASETS_PY_HF_INFERENCE_MODEL",
)
LEANSTRAL_WEIGHTS_ENV_VAR = "IPFS_DATASETS_PY_LEANSTRAL_WEIGHTS"


# Each executable group requires one available command.  Tamarin deliberately
# has a separate Maude lane because merely finding tamarin-prover is not enough
# to establish a usable protocol-checking runtime.
SOLVER_LANES: dict[str, dict[str, Any]] = {
    "z3": {
        "python_modules": ["z3"],
        "proof_lane": "SMT constraint solving",
        "installer_steps": ["ensure_z3"],
        "managed_solver": "z3",
    },
    "cvc5": {
        "executable_groups": [("cvc5",)],
        "python_modules": ["cvc5"],
        "proof_lane": "SMT and SMT-LIB differential checking",
        "installer_steps": ["ensure_cvc5", "ensure_cvc5_cli"],
        "managed_solver": "cvc5",
    },
    "apalache": {
        "executable_groups": [("apalache-mc", "apalache")],
        "proof_lane": "TLA model checking",
        "installer_steps": ["ensure_apalache"],
        "managed_solver": "apalache",
    },
    "maude": {
        "executable_groups": [("maude",)],
        "proof_lane": "Tamarin rewriting runtime",
        "installer_steps": ["ensure_maude"],
        "managed_solver": "maude",
    },
    "tamarin": {
        "executable_groups": [("tamarin-prover",)],
        "proof_lane": "symbolic protocol model checking",
        "installer_steps": ["ensure_tamarin"],
        "managed_solver": "tamarin",
    },
    "proverif": {
        "executable_groups": [("proverif",)],
        "proof_lane": "symbolic reachability and secrecy verification",
        "installer_steps": ["ensure_proverif"],
        "managed_solver": "proverif",
    },
    "lean": {
        "executable_groups": [("lean",), ("lake",)],
        "proof_lane": "Lean proof-consumer kernel",
        "installer_steps": ["ensure_lean"],
        "managed_solver": "lean",
    },
    "rocq": {
        "executable_groups": [("coqc",), ("coqtop",)],
        "proof_lane": "independent Rocq proof-kernel cross-check",
        "installer_steps": ["ensure_coq"],
        "managed_solver": "rocq",
    },
    "symbolicai": {
        "python_modules": ["symai"],
        "proof_lane": "SymbolicAI-assisted proof proposal",
        "installer_steps": ["ensure_symbolicai"],
        "managed_solver": "symbolicai",
    },
    "ergoai": {
        "executable_groups": [("ergoai", "ergo", "runErgo.sh", "runergo")],
        "proof_lane": "ErgoAI logic-programming checks",
        "installer_steps": ["ensure_ergoai"],
        "managed_solver": "ergoai",
    },
    "leanstral": {
        "proof_lane": "Leanstral advisory model-proposing lane (not proof authority)",
        "supports_install": False,
        "managed_solver": "leanstral",
    },
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(payload: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _platform_key() -> str:
    system = platform.system().lower()
    if system in {"linux", "darwin"}:
        return system
    return "unsupported"


def _dependency_statuses(solver_probe: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    dependencies = solver_probe.get("dependencies") if isinstance(solver_probe, Mapping) else None
    if not isinstance(dependencies, list):
        return {}
    return {
        str(dependency.get("name")): dict(dependency)
        for dependency in dependencies
        if isinstance(dependency, Mapping) and isinstance(dependency.get("name"), str)
    }


def _executable_groups(config: Mapping[str, Any]) -> list[tuple[str, ...]]:
    raw_groups = config.get("executable_groups", [])
    return [tuple(str(name) for name in group) for group in raw_groups]


def _probe_python_module(name: str) -> dict[str, Any]:
    try:
        available = importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        available = False
    return {"name": name, "status": "present" if available else "missing"}


def _version_command(executable_name: str, executable: str) -> list[str]:
    if executable_name == "proverif":
        return [executable, "--version"]
    if executable_name == "apalache-mc":
        return [executable, "version"]
    return [executable, "--version"]


def _run_version(command: Sequence[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "command": list(command), "error": exc.__class__.__name__}
    output = "\n".join(value.strip() for value in (completed.stdout, completed.stderr) if value.strip())
    version = next((line.strip() for line in output.splitlines() if line.strip()), None)
    return {
        "status": "present" if completed.returncode == 0 else "error",
        "command": list(command),
        "exit_code": completed.returncode,
        "version_raw": version,
    }


def _managed_statuses(installer: Any | None) -> dict[str, dict[str, Any]]:
    if installer is None:
        return {}
    try:
        statuses = installer.managed_solver_version_status()
    except Exception:
        return {}
    return {
        str(status.get("solver")): dict(status)
        for status in statuses
        if isinstance(status, Mapping) and isinstance(status.get("solver"), str)
    }


def _managed_install_command(config: Mapping[str, Any]) -> list[str]:
    if config.get("supports_install", True) is False:
        return []
    steps = [str(step) for step in config.get("installer_steps", [])]
    options = " ".join("--" + step.removeprefix("ensure_").replace("_", "-") for step in steps)
    # The cvc5 Python and CLI installers intentionally use different options.
    options = options.replace("--cvc5-cli", "--cvc5-cli")
    command = f"python -m {INSTALLER_MODULE} --yes {options}".strip()
    return [command]


def _normalize_leanstral_config() -> dict[str, Any]:
    env = os.environ
    model_candidates: list[dict[str, Any]] = []
    for name in LEANSTRAL_MODEL_ENV_VARS:
        value = (env.get(name) or "").strip()
        if not value:
            continue
        normalized = value.lower()
        approved = any(route in normalized for route in LEANSTRAL_APPROVED_ROUTES)
        model_candidates.append(
            {
                "env_var": name,
                "value": value,
                "approved_route": approved,
                "detected_route": next((route for route in LEANSTRAL_APPROVED_ROUTES if route in normalized), None),
            }
        )

    weights_value = (env.get(LEANSTRAL_WEIGHTS_ENV_VAR) or "").strip()
    weights_path = Path(weights_value) if weights_value else None
    weights_exists = bool(weights_value and weights_path is not None and weights_path.exists())
    configured_by_route = any(candidate["approved_route"] for candidate in model_candidates)
    configured_by_weights = bool(weights_value and weights_exists)
    unapproved = [
        candidate
        for candidate in model_candidates
        if "leanstral" in candidate["value"].lower() and not candidate["approved_route"]
    ]
    if configured_by_route or configured_by_weights:
        status = "configured"
    elif unapproved:
        status = "blocked-unapproved-route"
    else:
        status = "unconfigured"
    return {
        "status": status,
        "model_candidates": model_candidates,
        "configured_by_route": configured_by_route,
        "configured_by_weights": configured_by_weights,
        "unapproved_candidates": unapproved,
    }


def _probe_leanstral_lane(
    config: Mapping[str, Any],
    *,
    root: Path,
    path_env: str | None,
    platform_key: str,
    managed_status: Mapping[str, Any] | None,
) -> dict[str, Any]:
    del path_env
    leanstral_config = _normalize_leanstral_config()
    lean_report = _load_json(root / DEFAULT_LEAN_REPORT) if (root / DEFAULT_LEAN_REPORT).is_file() else {}
    lean_ready = (
        bool(lean_report.get("overall_status") == "ready")
        if isinstance(lean_report, Mapping)
        else False
    )
    if lean_report.get("summary", {}).get("lean_present") is not True or lean_report.get("summary", {}).get("lake_present") is not True:
        lean_ready = False

    if leanstral_config["status"] == "blocked-unapproved-route":
        lane_status = "blocked_optional_lane"
        proof_acceptance = "do_not_accept_reports_for_missing_solver_lane"
    elif leanstral_config["status"] == "configured" and lean_ready:
        lane_status = "ready"
        proof_acceptance = "may_accept_reports_after_lane_specific_validation"
    elif leanstral_config["status"] == "configured":
        lane_status = "degraded_optional_lane"
        proof_acceptance = "do_not_accept_reports_until_all_required_tools_are_present"
    else:
        lane_status = "degraded_optional_lane"
        proof_acceptance = "do_not_accept_reports_until_leanstral_configuration_is_reviewed"

    managed_entry = {
        "solver": "leanstral",
        "managed_version": "|".join(LEANSTRAL_APPROVED_ROUTES),
        "executable": None,
        "installed_version": leanstral_config["status"],
        "present": leanstral_config["status"] != "unconfigured",
        "status": "managed" if lane_status == "ready" else "manual_update_required",
        "manual_update_required": lane_status != "ready",
    }
    if managed_status is not None:
        managed_status = dict(managed_status)
        managed_status["leanstral"] = managed_entry

    return {
        "name": "leanstral",
        "proof_lane": config["proof_lane"],
        "status": lane_status,
        "required_executables": [],
        "executables": [],
        "python_modules": [],
        "managed_version_status": managed_entry,
        "install_plan": {
            "mode": "advisory",
            "platform": platform_key,
            "commands": [],
            "requires_manual_review": True,
            "network_access_may_be_required": False,
        },
        "proof_acceptance_policy": proof_acceptance,
        "advisory_lane": {
            "proof_authority": False,
            "configuration": leanstral_config,
            "lean_kernel_ready": lean_ready,
        },
    }


def _managed_executable_for_group(
    managed_status: Mapping[str, Any] | None,
    executable_name: str,
) -> str | None:
    if not managed_status:
        return None
    managed_executable = str(managed_status.get("executable") or "").strip()
    if not managed_executable:
        return None
    executable_basename = Path(managed_executable).name.lower()
    if executable_basename == executable_name.lower():
        return managed_executable
    if executable_basename.lower() == "runergo" and executable_name.lower() in {"runergo", "runergo.sh"}:
        return managed_executable
    return None


def _probe_lane(
    name: str,
    config: Mapping[str, Any],
    *,
    root: Path,
    path_env: str | None,
    platform_key: str,
    managed_statuses: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if name == "leanstral":
        return _probe_leanstral_lane(
            config,
            root=root,
            path_env=path_env,
            platform_key=platform_key,
            managed_status=managed_statuses.get(str(config.get("managed_solver", name))),
        )

    executable_reports: list[dict[str, Any]] = []
    groups_ready = True
    required_executables: list[str] = []
    managed_solver = str(config.get("managed_solver", name))
    managed_status = dict(managed_statuses.get(managed_solver, {})) or None
    for group in _executable_groups(config):
        required_executables.append(" | ".join(group))
        group_present = False
        for executable_name in group:
            resolved = shutil.which(executable_name, path=path_env)
            if resolved is None:
                resolved = _managed_executable_for_group(managed_status, executable_name)
            version_report = _run_version(_version_command(executable_name, resolved)) if resolved else None
            executable_reports.append(
                {
                    "name": executable_name,
                    "path": resolved,
                    "status": "present" if resolved else "missing",
                    "version": version_report.get("version_raw") if version_report else None,
                    "version_probe": version_report,
                }
            )
            group_present = group_present or resolved is not None
        groups_ready = groups_ready and group_present

    module_reports = [_probe_python_module(str(module)) for module in config.get("python_modules", [])]
    modules_ready = all(item["status"] == "present" for item in module_reports)
    current = bool(groups_ready and modules_ready)
    any_executable = any(item["status"] == "present" for item in executable_reports)
    any_module = any(item["status"] == "present" for item in module_reports)
    version_drift = bool(managed_status and managed_status.get("manual_update_required"))
    if not current:
        if any_executable or any_module:
            lane_status = "degraded_optional_lane"
            proof_acceptance = "do_not_accept_reports_until_all_required_tools_are_present"
        else:
            lane_status = "blocked_optional_lane"
            proof_acceptance = "do_not_accept_reports_for_missing_solver_lane"
    elif version_drift:
        lane_status = "degraded_optional_lane"
        proof_acceptance = "do_not_accept_reports_until_managed_version_is_reviewed"
    else:
        lane_status = "ready"
        proof_acceptance = "may_accept_reports_after_lane_specific_validation"

    return {
        "name": name,
        "proof_lane": config["proof_lane"],
        "status": lane_status,
        "required_executables": required_executables,
        "executables": executable_reports,
        "python_modules": module_reports,
        "managed_version_status": managed_status,
        "install_plan": {
            "mode": "managed_user_local_installer",
            "platform": platform_key,
            "commands": _managed_install_command(config),
            "requires_manual_review": True,
            "network_access_may_be_required": True,
        },
        "proof_acceptance_policy": proof_acceptance,
    }


def _load_package_installer() -> Any:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    return prover_installer


def _run_installer_steps(
    selected: set[str],
    *,
    installer: Any,
    update: bool,
    strict: bool,
    allow_sudo: bool,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for lane_name in selected:
        config = SOLVER_LANES[lane_name]
        events: list[dict[str, str]] = []

        def on_progress(phase: str, message: str) -> None:
            event = {"phase": str(phase), "message": str(message)}
            events.append(event)
            print(f"[ipfs_datasets_py] {lane_name}: {phase}: {message}", flush=True)

        step_results: list[dict[str, Any]] = []
        steps = list(config.get("installer_steps", []))
        if not steps:
            if config.get("supports_install") is False:
                message = (
                    "This lane is advisory-only and is not installed locally; configure "
                    "Leanstral model credentials/weights and keep a verified Lean proof-kernel ready."
                )
                on_progress("blocked", message)
                step_results.append({"step": "non_installable_advisory_lane", "ok": False, "error": "not_installable"})
                results[lane_name] = {
                    "requested": True,
                    "operation": "update" if update else "install",
                    "ok": False,
                    "steps": step_results,
                    "events": events,
                }
                continue
        for step_name in config.get("installer_steps", []):
            ensure = getattr(installer, str(step_name), None)
            if ensure is None:
                step_results.append({"step": step_name, "ok": False, "error": "installer_function_missing"})
                continue
            kwargs: dict[str, Any] = {
                "yes": True,
                "strict": strict,
                "force": update,
                "on_progress": on_progress,
            }
            signature = inspect.signature(ensure)
            if "allow_sudo" in signature.parameters:
                kwargs["allow_sudo"] = allow_sudo
            try:
                ok = bool(ensure(**kwargs))
                step_results.append({"step": step_name, "ok": ok})
            except Exception as exc:
                step_results.append({"step": step_name, "ok": False, "error": f"{exc.__class__.__name__}: {exc}"})
        results[lane_name] = {
            "requested": True,
            "operation": "update" if update else "install",
            "ok": bool(step_results) and all(bool(item["ok"]) for item in step_results),
            "steps": step_results,
            "events": events,
        }
    return results


def build_report(
    *,
    repo_root: Path | str | None = None,
    solver_probe_path: Path | str = DEFAULT_SOLVER_PROBE,
    path_env: str | None = None,
    generated_at_utc: str | None = None,
    install: bool = False,
    update: bool = False,
    selected_solvers: Sequence[str] | None = None,
    strict: bool = False,
    allow_sudo: bool = False,
    installer: Any | None = None,
) -> dict[str, Any]:
    """Build a solver report and optionally run selected managed installers."""

    if update:
        install = True
    root = Path(repo_root) if repo_root is not None else _repo_root()
    solver_probe_abs = Path(solver_probe_path)
    if not solver_probe_abs.is_absolute():
        solver_probe_abs = root / solver_probe_abs
    solver_probe = _load_json(solver_probe_abs)
    dependencies = _dependency_statuses(solver_probe)
    platform_key = _platform_key()
    path_value = path_env if path_env is not None else os.environ.get("PATH")
    selected = set(selected_solvers or SOLVER_LANES)
    unknown = sorted(selected.difference(SOLVER_LANES))
    if unknown:
        raise ValueError("unknown solver lanes: " + ", ".join(unknown))

    active_installer = installer
    load_error: str | None = None
    if active_installer is None:
        try:
            active_installer = _load_package_installer()
        except Exception as exc:
            load_error = f"{exc.__class__.__name__}: {exc}"

    install_results: dict[str, dict[str, Any]] = {}
    if install:
        if active_installer is None:
            install_results = {
                lane: {
                    "requested": True,
                    "operation": "update" if update else "install",
                    "ok": False,
                    "steps": [],
                    "events": [],
                    "error": "package_installer_unavailable",
                }
                for lane in selected
            }
        else:
            install_results = _run_installer_steps(
                selected,
                installer=active_installer,
                update=update,
                strict=strict,
                allow_sudo=allow_sudo,
            )

    # A caller can supply ``path_env`` to probe an isolated fixture or a
    # staged toolchain.  Global installer status then refers to a different
    # executable set and must not downgrade those probe results.
    statuses = _managed_statuses(active_installer) if path_env is None else {}
    lanes = []
    for name, config in SOLVER_LANES.items():
        lane = _probe_lane(
            name,
            config,
            root=root,
            path_env=path_value,
            platform_key=platform_key,
            managed_statuses=statuses,
        )
        if name in install_results:
            lane["installation"] = install_results[name]
        lanes.append(lane)
    missing_or_degraded = [lane for lane in lanes if lane["status"] != "ready"]
    ready_lanes = [lane for lane in lanes if lane["status"] == "ready"]

    warnings: list[dict[str, Any]] = []
    if solver_probe is None:
        warnings.append({"code": "SOLVER_DEPENDENCY_PROBE_MISSING", "path": _relative(root, solver_probe_abs)})
    if load_error:
        warnings.append({"code": "PACKAGE_INSTALLER_UNAVAILABLE", "message": load_error})
    for lane in lanes:
        probe_status = dependencies.get(lane["name"], {}).get("status")
        if probe_status and probe_status != "present" and lane["status"] == "ready":
            warnings.append(
                {
                    "code": "OPTIONAL_LANE_READY_BUT_BASE_PROBE_STALE",
                    "solver": lane["name"],
                    "base_probe_status": probe_status,
                }
            )

    failed_installs = [result for result in install_results.values() if not result["ok"]]
    operation = "update" if update else "install" if install else "plan_only"
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "policy_document": POLICY_DOCUMENT,
        "solver_probe": {
            "path": _relative(root, solver_probe_abs),
            "exists": solver_probe_abs.is_file(),
            "overall_status": solver_probe.get("overall_status") if isinstance(solver_probe, Mapping) else None,
            "security_decision": solver_probe.get("security_decision") if isinstance(solver_probe, Mapping) else None,
        },
        "installer_mode": operation,
        "platform": platform_key,
        "selected_solvers": sorted(selected),
        "managed_solver_versions": list(statuses.values()),
        "lanes": lanes,
        "ready_lane_count": len(ready_lanes),
        "missing_or_degraded_lane_count": len(missing_or_degraded),
        "install_failure_count": len(failed_installs),
        "warnings": warnings,
        "warning_count": len(warnings),
        "overall_status": "ready_with_blocked_optional_lanes" if missing_or_degraded else "ready",
        "proof_acceptance_blocked": False,
        "security_decision": "OPTIONAL_SOLVER_LANES_EXPLICITLY_BLOCKED_OR_READY",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe or run managed optional theorem-prover installers.")
    parser.add_argument("--solver-probe", default=str(DEFAULT_SOLVER_PROBE))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--solver", action="append", choices=sorted(SOLVER_LANES), help="Solver lane to install or update; repeat as needed.")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--install", action="store_true", help="Install selected solvers into the user-local managed root.")
    operation.add_argument("--update", action="store_true", help="Refresh selected solvers to reviewed managed versions.")
    parser.add_argument("--yes", action="store_true", help="Acknowledge that install/update can download or build tools.")
    parser.add_argument("--allow-sudo", action="store_true", help="Allow an OPAM bootstrap through the platform package manager when needed.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when a requested install/update step fails.")
    args = parser.parse_args(argv)

    if (args.install or args.update) and not args.yes:
        parser.error("--install and --update require --yes because they can download, build, or replace user-local solvers")

    root = Path(args.repo_root).resolve()
    report = build_report(
        repo_root=root,
        solver_probe_path=args.solver_probe,
        install=bool(args.install or args.update),
        update=bool(args.update),
        selected_solvers=args.solver,
        strict=bool(args.strict),
        allow_sudo=bool(args.allow_sudo),
    )
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    _write_json(report, out_path)
    print(
        json.dumps(
            {
                "install_failure_count": report["install_failure_count"],
                "installer_mode": report["installer_mode"],
                "missing_or_degraded_lane_count": report["missing_or_degraded_lane_count"],
                "overall_status": report["overall_status"],
                "ready_lane_count": report["ready_lane_count"],
                "security_decision": report["security_decision"],
            },
            sort_keys=True,
        )
    )
    return 1 if args.strict and report["install_failure_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
