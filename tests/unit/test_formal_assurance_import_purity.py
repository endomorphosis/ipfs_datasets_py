"""FACP-021: Characterize Datasets cold-import effects.

Sandboxed probes reproduce every FACP-003 ``DS-IMPORT-*`` seed under empty
HOME / XDG / project-root equivalents with network, subprocess, and
out-of-sandbox writes denied. The purity oracle **fails** for each seeded
effect. Observations record exact legacy behavior and must never be labeled
``success`` or treated as formal purity / production proof.

This task does not repair package import (FACP-022 owns that).
"""

from __future__ import annotations

import json
import os
import resource
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

TASK_ID = "FACP-021"
GOAL_ID = "FACP-G210"
BUNDLE = "facp/migration/datasets-import"
EVIDENCE_ID = "facp/datasets-import-purity@1"

# test file -> unit -> tests -> ipfs_datasets package root -> external -> workspace
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
_CLAIMS_PATH = (
    _WORKSPACE_ROOT
    / "implementation_plan"
    / "formal_assurance_control_plane"
    / "baseline"
    / "datasets_claims.json"
)
_BASELINE_DOC = (
    _PACKAGE_ROOT / "docs" / "architecture" / "FORMAL_ASSURANCE_IMPORT_BASELINE.md"
)

# Forbidden observation labels: characterization must not normalize impurity.
FORBIDDEN_SUCCESS_LABELS = frozenset(
    {
        "success",
        "ok",
        "passed",
        "pure",
        "hermetic",
        "production_supported",
        "effect_successful",
        "purity_pass",
    }
)

# FCA import_effect family mapping (formal-claim-algebra-v1 §8.4).
FCA_IMPORT_EFFECT_MAPPING = {
    "family": "import_effect",
    "informs": ["discovery"],
    "forbidden_predicates": ["effect_successful", "production_supported"],
    "unsafe_promotion": False,
    "conservative_outcome": "discovery_of_impurity_only",
    "disposition": "reject_illegal_promotion",
}


def _load_import_effect_seeds() -> list[dict[str, Any]]:
    assert _CLAIMS_PATH.is_file(), f"missing FACP-003 inventory: {_CLAIMS_PATH}"
    claims = json.loads(_CLAIMS_PATH.read_text(encoding="utf-8"))
    traces = claims["import_effect_traces"]
    assert isinstance(traces, list) and traces
    seeds = []
    for item in traces:
        assert item["category"] == "import_effect"
        assert item["defect_id"].startswith("DS-IMPORT-")
        seed = item["counterexample_seed"]
        seeds.append(
            {
                "defect_id": item["defect_id"],
                "family": item["family"],
                "seed_id": seed["id"],
                "oracle": seed["oracle"],
                "path": item["path"],
                "symbol": item["symbol"],
                "quote": item["quote"],
                "effects": list(item.get("effects") or []),
                "call_flow": list(item.get("call_flow") or []),
                "production_reachability": item.get("production_reachability"),
                "repair_class": item.get("repair_class"),
            }
        )
    return seeds


SEEDS = _load_import_effect_seeds()
SEED_BY_ID = {s["defect_id"]: s for s in SEEDS}


def _sandbox_env(sandbox: Path, *, extra: dict[str, str] | None = None) -> dict[str, str]:
    home = sandbox / "home"
    proj = sandbox / "project"
    state = sandbox / "explicit_state"
    tmp = sandbox / "tmp"
    for path in (home, proj, state, tmp, home / ".config", home / ".cache", home / ".local" / "share"):
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    # Empty explicit state / home equivalents.
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_CACHE_HOME"] = str(home / ".cache")
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env["XDG_STATE_HOME"] = str(state)
    env["TMPDIR"] = str(tmp)
    env["TMP"] = str(tmp)
    env["TEMP"] = str(tmp)
    env["IPFS_DATASETS_PROJECT_ROOT"] = str(proj)
    env["IPFS_DATASETS_LOCAL_BIN"] = str(proj / "bin")
    env["IPFS_DATASETS_LOCAL_DEPS"] = str(proj / "bin" / ".deps")
    env["FACP021_SANDBOX"] = str(sandbox)
    env["FACP021_PROJ"] = str(proj)
    env["FACP021_STATE"] = str(state)
    env["FACP021_PACKAGE_ROOT"] = str(_PACKAGE_ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["NO_NETWORK"] = "1"
    env["PIP_NO_INDEX"] = "1"
    # Do not inherit ambient auto-install / ensure-installer / minimal flags.
    for key in (
        "IPFS_DATASETS_AUTO_INSTALL",
        "IPFS_KIT_AUTO_INSTALL_DEPS",
        "IPFS_AUTO_INSTALL",
        "IPFS_DATASETS_ENSURE_INSTALLER",
        "IPFS_DATASETS_PY_MINIMAL_IMPORTS",
        "IPFS_DATASETS_PY_BENCHMARK",
        "IPFS_DATASETS_PY_ENABLE_MCP_IMPORTS",
        "IPFS_DATASETS_PY_ENABLE_FASTAPI_IMPORTS",
        "IPFS_DATASETS_PY_ENABLE_LLM_IMPORTS",
        "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS",
    ):
        env.pop(key, None)

    pythonpath = os.pathsep.join(
        part for part in (str(_PACKAGE_ROOT), env.get("PYTHONPATH", "")) if part
    )
    env["PYTHONPATH"] = pythonpath
    if extra:
        env.update(extra)
    return env


_PROBE_PREAMBLE = r'''
import os, sys, json, socket, subprocess, time, resource, builtins
from pathlib import Path

effects = []
DENY_NETWORK = True
DENY_SUBPROCESS = True
SANDBOX = os.environ["FACP021_SANDBOX"]

def _record(kind, **fields):
    entry = {"kind": kind, **fields}
    effects.append(entry)
    return entry

# --- Network denial ---
def _deny_net(api, *a, **k):
    _record("network", api=api, args=repr(a)[:240])
    raise OSError(f"FACP-021 network denied: {api}")

socket.create_connection = lambda *a, **k: _deny_net("create_connection", *a, **k)
_orig_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **k: _deny_net("getaddrinfo", *a, **k)
_OrigSocket = socket.socket
class _GuardedSocket(_OrigSocket):
    def connect(self, *a, **k):
        _deny_net("socket.connect", *a, **k)
    def connect_ex(self, *a, **k):
        _deny_net("socket.connect_ex", *a, **k)
socket.socket = _GuardedSocket

# --- Subprocess denial ---
def _deny_run(*a, **k):
    cmd = a[0] if a else k.get("args")
    if isinstance(cmd, (list, tuple)):
        cmd_repr = [str(x) for x in cmd]
    else:
        cmd_repr = repr(cmd)[:300]
    _record("subprocess", api="run", cmd=cmd_repr)
    raise RuntimeError("FACP-021 subprocess denied")

subprocess.run = _deny_run
class _DenyPopen:
    def __init__(self, *a, **k):
        cmd = a[0] if a else k.get("args")
        if isinstance(cmd, (list, tuple)):
            cmd_repr = [str(x) for x in cmd]
        else:
            cmd_repr = repr(cmd)[:300]
        _record("subprocess", api="Popen", cmd=cmd_repr)
        raise RuntimeError("FACP-021 Popen denied")
subprocess.Popen = _DenyPopen
subprocess.call = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("FACP-021 call denied"))
subprocess.check_call = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("FACP-021 check_call denied"))
subprocess.check_output = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("FACP-021 check_output denied"))
os.system = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("FACP-021 os.system denied"))

# --- Filesystem write denial outside sandbox ---
_orig_mkdir = Path.mkdir
def _tracked_mkdir(self, *a, **k):
    path = str(self)
    _record("fs_mkdir", path=path)
    if path.startswith(SANDBOX):
        return _orig_mkdir(self, *a, **k)
    raise OSError(f"FACP-021 write denied: {path}")
Path.mkdir = _tracked_mkdir

_orig_write_text = Path.write_text
def _tracked_write_text(self, data, *a, **k):
    path = str(self)
    _record("fs_write", path=path, nbytes=(len(data) if isinstance(data, str) else None))
    if path.startswith(SANDBOX):
        return _orig_write_text(self, data, *a, **k)
    raise OSError(f"FACP-021 write denied: {path}")
Path.write_text = _tracked_write_text

_orig_makedirs = os.makedirs
def _tracked_makedirs(name, *a, **k):
    path = str(name)
    _record("fs_makedirs", path=path)
    if path.startswith(SANDBOX):
        return _orig_makedirs(name, *a, **k)
    raise OSError(f"FACP-021 write denied: {path}")
os.makedirs = _tracked_makedirs

# Track durable PATH helpers
_real_import = builtins.__import__
def _guarded_import(name, *a, **k):
    if name == "winreg" or (isinstance(name, str) and name.startswith("winreg.")):
        _record("persistent_path", api="winreg_import")
    return _real_import(name, *a, **k)
builtins.__import__ = _guarded_import

def _clear_package_modules():
    for n in list(sys.modules):
        if n == "ipfs_datasets_py" or n.startswith("ipfs_datasets_py."):
            del sys.modules[n]

def _clear_auto_env():
    for key in (
        "IPFS_DATASETS_AUTO_INSTALL",
        "IPFS_KIT_AUTO_INSTALL_DEPS",
        "IPFS_AUTO_INSTALL",
        "IPFS_DATASETS_ENSURE_INSTALLER",
        "IPFS_DATASETS_PY_MINIMAL_IMPORTS",
        "IPFS_DATASETS_PY_BENCHMARK",
    ):
        os.environ.pop(key, None)

def _emit(payload):
    payload["effects"] = effects
    payload["effect_kinds"] = sorted({e["kind"] for e in effects})
    payload["effect_count"] = len(effects)
    print("FACP021_OBSERVATION::" + json.dumps(payload, sort_keys=True))
'''


def _run_probe(script_body: str, *, extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    sandbox = Path(tempfile.mkdtemp(prefix="facp021-"))
    env = _sandbox_env(sandbox, extra=extra_env)
    script = _PROBE_PREAMBLE + "\n" + script_body
    started = time.perf_counter()
    rss_before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_WORKSPACE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    rss_after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss

    observation = None
    for line in (completed.stdout or "").splitlines():
        if line.startswith("FACP021_OBSERVATION::"):
            observation = json.loads(line[len("FACP021_OBSERVATION::") :])
    assert observation is not None, (
        f"probe emitted no observation\n"
        f"rc={completed.returncode}\nstdout={completed.stdout[-4000:]}\n"
        f"stderr={completed.stderr[-4000:]}"
    )
    observation["probe_returncode"] = completed.returncode
    observation["elapsed_ms"] = round(elapsed_ms, 3)
    observation["child_maxrss_kb_delta"] = int(rss_after - rss_before)
    observation["sandbox"] = str(sandbox)
    observation["stderr_tail"] = (completed.stderr or "")[-1500:]
    return observation


def _classify_observation(defect_id: str, observation: dict[str, Any]) -> dict[str, Any]:
    """Purity oracle: seeded legacy effects fail closed; never success."""
    effects = observation.get("effects") or []
    kinds = {e.get("kind") for e in effects}
    after_env = observation.get("after_env") or {}
    path_delta = observation.get("path_delta") or []

    matched: list[str] = []
    if defect_id == "DS-IMPORT-001":
        if after_env.get("IPFS_DATASETS_AUTO_INSTALL") == "true":
            matched.append("environment_write:IPFS_DATASETS_AUTO_INSTALL=true")
        if after_env.get("IPFS_KIT_AUTO_INSTALL_DEPS") in {"1", "true"}:
            matched.append("environment_write:IPFS_KIT_AUTO_INSTALL_DEPS")
    elif defect_id == "DS-IMPORT-002":
        if any(e.get("kind") == "fs_mkdir" and "/bin" in str(e.get("path", "")) for e in effects):
            matched.append("fs_mkdir:installer_bin_deps")
        if path_delta:
            matched.append(f"path_mutation:{path_delta[:2]}")
    elif defect_id == "DS-IMPORT-003":
        for e in effects:
            if e.get("kind") != "subprocess":
                continue
            cmd = e.get("cmd")
            cmd_l = [str(x).lower() for x in cmd] if isinstance(cmd, list) else [str(cmd).lower()]
            if any("pip" == x or x.endswith("/pip") for x in cmd_l) or "pip" in " ".join(cmd_l):
                matched.append("subprocess:pip_install")
                break
    elif defect_id == "DS-IMPORT-004":
        if any(e.get("kind") == "persistent_path" for e in effects):
            matched.append("persistent_path:winreg_or_setx_path")
        for e in effects:
            if e.get("kind") == "subprocess":
                cmd = e.get("cmd")
                head = str(cmd[0]).lower() if isinstance(cmd, list) and cmd else str(cmd).lower()
                if "setx" in head:
                    matched.append("subprocess:setx_PATH")
                    break
        if observation.get("path_mutated"):
            matched.append("process_path_mutation")
    elif defect_id == "DS-IMPORT-005":
        for e in effects:
            path = str(e.get("path", ""))
            if e.get("kind") in {"fs_mkdir", "fs_write", "fs_makedirs"} and (
                "runtime_installer_state" in path or path.rstrip("/").endswith("/state") or "/state/" in path
            ):
                matched.append(f"{e['kind']}:runtime_installer_state")
            if e.get("kind") == "subprocess":
                cmd = e.get("cmd")
                blob = " ".join(str(x) for x in cmd) if isinstance(cmd, list) else str(cmd)
                if "pip" in blob.lower() and (
                    "ipfs_accelerate" in blob.lower()
                    or "libp2p" in blob.lower()
                    or "ipfs_kit" in blob.lower()
                ):
                    matched.append("subprocess:companion_bootstrap")
    else:
        raise AssertionError(f"unknown defect_id: {defect_id}")

    purity_passed = len(matched) == 0
    disposition = (
        "legacy_impurity_observed"
        if not purity_passed
        else "unexpected_clean"  # still not success; characterization expects impurity
    )
    return {
        "defect_id": defect_id,
        "purity_passed": purity_passed,
        "matched_effects": matched,
        "disposition": disposition,
        "normalized_as_success": False,
        "fca": dict(FCA_IMPORT_EFFECT_MAPPING),
        "effect_kinds_observed": sorted(kinds),
    }


# ---------------------------------------------------------------------------
# Per-seed probe bodies
# ---------------------------------------------------------------------------

def _probe_ds_import_001() -> dict[str, Any]:
    body = textwrap.dedent(
        """
        _clear_package_modules()
        _clear_auto_env()
        os.environ["IPFS_DATASETS_PY_MINIMAL_IMPORTS"] = "1"
        before_env = {
            "IPFS_DATASETS_AUTO_INSTALL": os.environ.get("IPFS_DATASETS_AUTO_INSTALL"),
            "IPFS_KIT_AUTO_INSTALL_DEPS": os.environ.get("IPFS_KIT_AUTO_INSTALL_DEPS"),
        }
        t0 = time.perf_counter()
        import ipfs_datasets_py  # noqa: F401
        elapsed = (time.perf_counter() - t0) * 1000.0
        after_env = {
            "IPFS_DATASETS_AUTO_INSTALL": os.environ.get("IPFS_DATASETS_AUTO_INSTALL"),
            "IPFS_KIT_AUTO_INSTALL_DEPS": os.environ.get("IPFS_KIT_AUTO_INSTALL_DEPS"),
        }
        _emit({
            "defect_id": "DS-IMPORT-001",
            "mode": "minimal_cold_import",
            "before_env": before_env,
            "after_env": after_env,
            "import_elapsed_ms": round(elapsed, 3),
            "maxrss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        })
        """
    )
    return _run_probe(body)


def _probe_ds_import_002() -> dict[str, Any]:
    body = textwrap.dedent(
        """
        _clear_package_modules()
        _clear_auto_env()
        # Non-minimal: installer construction on import.
        os.environ.pop("IPFS_DATASETS_PY_MINIMAL_IMPORTS", None)
        os.environ["IPFS_DATASETS_ENSURE_INSTALLER"] = "0"
        os.environ["IPFS_DATASETS_PROJECT_ROOT"] = os.environ["FACP021_PROJ"]
        before_path = os.environ.get("PATH", "")
        t0 = time.perf_counter()
        import_error = None
        try:
            import ipfs_datasets_py  # noqa: F401
        except Exception as exc:
            import_error = f"{type(exc).__name__}: {exc}"
        elapsed = (time.perf_counter() - t0) * 1000.0
        after_path = os.environ.get("PATH", "")
        before_parts = before_path.split(os.pathsep) if before_path else []
        after_parts = after_path.split(os.pathsep) if after_path else []
        path_delta = [p for p in after_parts if p not in before_parts]
        after_env = {
            "IPFS_DATASETS_AUTO_INSTALL": os.environ.get("IPFS_DATASETS_AUTO_INSTALL"),
            "IPFS_KIT_AUTO_INSTALL_DEPS": os.environ.get("IPFS_KIT_AUTO_INSTALL_DEPS"),
        }
        _emit({
            "defect_id": "DS-IMPORT-002",
            "mode": "non_minimal_cold_import",
            "import_error": import_error,
            "after_env": after_env,
            "path_delta": path_delta,
            "import_elapsed_ms": round(elapsed, 3),
            "maxrss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        })
        """
    )
    return _run_probe(body)


def _probe_ds_import_003() -> dict[str, Any]:
    body = textwrap.dedent(
        """
        _clear_package_modules()
        _clear_auto_env()
        os.environ.pop("IPFS_DATASETS_PY_MINIMAL_IMPORTS", None)
        os.environ["IPFS_DATASETS_ENSURE_INSTALLER"] = "0"
        os.environ["IPFS_DATASETS_PROJECT_ROOT"] = os.environ["FACP021_PROJ"]
        import ipfs_datasets_py  # noqa: F401
        from ipfs_datasets_py.auto_installer import get_installer, ensure_module
        installer = get_installer()
        installer.auto_install = True
        pip_error = None
        pip_result = None
        try:
            pip_result = installer._pip_install("facp021-nonexistent-pkg-zzzz==0.0.0")
        except Exception as exc:
            pip_error = f"{type(exc).__name__}: {exc}"
        ensure_error = None
        ensure_result = None
        try:
            ensure_result = repr(
                ensure_module(
                    "facp021_totally_missing_module_xyz",
                    "facp021-nonexistent-pkg-zzzz",
                )
            )[:200]
        except Exception as exc:
            ensure_error = f"{type(exc).__name__}: {exc}"
        _emit({
            "defect_id": "DS-IMPORT-003",
            "mode": "pip_reachability_after_import",
            "pip_result": pip_result,
            "pip_error": pip_error,
            "ensure_result": ensure_result,
            "ensure_error": ensure_error,
            "auto_install": bool(installer.auto_install),
            "maxrss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        })
        """
    )
    return _run_probe(body)


def _probe_ds_import_004() -> dict[str, Any]:
    body = textwrap.dedent(
        """
        _clear_package_modules()
        _clear_auto_env()
        os.environ.pop("IPFS_DATASETS_PY_MINIMAL_IMPORTS", None)
        os.environ["IPFS_DATASETS_ENSURE_INSTALLER"] = "0"
        os.environ["IPFS_DATASETS_PROJECT_ROOT"] = os.environ["FACP021_PROJ"]
        from ipfs_datasets_py.auto_installer import get_installer
        installer = get_installer()
        before_path = os.environ.get("PATH")
        result = None
        err = None
        try:
            result = installer._add_to_user_path([str(Path(os.environ["FACP021_PROJ"]) / "bin")])
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
        after_path = os.environ.get("PATH")
        _emit({
            "defect_id": "DS-IMPORT-004",
            "mode": "persistent_user_path_helper",
            "result": result,
            "err": err,
            "path_mutated": before_path != after_path,
            "maxrss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        })
        """
    )
    return _run_probe(body)


def _probe_ds_import_005() -> dict[str, Any]:
    body = textwrap.dedent(
        """
        _clear_package_modules()
        _clear_auto_env()
        os.environ.pop("IPFS_DATASETS_PY_MINIMAL_IMPORTS", None)
        os.environ["IPFS_DATASETS_PROJECT_ROOT"] = os.environ["FACP021_PROJ"]
        # Seed reachability: bootstrap gated on (or force).
        os.environ["IPFS_DATASETS_ENSURE_INSTALLER"] = "1"
        import_error = None
        try:
            import ipfs_datasets_py  # noqa: F401
        except Exception as exc:
            import_error = f"{type(exc).__name__}: {exc}"
        from ipfs_datasets_py.auto_installer import ensure_repo_installer_current
        force_error = None
        force_result = None
        try:
            force_result = ensure_repo_installer_current(force=True)
        except Exception as exc:
            force_error = f"{type(exc).__name__}: {exc}"
        _emit({
            "defect_id": "DS-IMPORT-005",
            "mode": "runtime_installer_bootstrap",
            "import_error": import_error,
            "force_result": force_result,
            "force_error": force_error,
            "ensure_installer_env": os.environ.get("IPFS_DATASETS_ENSURE_INSTALLER"),
            "maxrss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        })
        """
    )
    return _run_probe(body)


PROBES = {
    "DS-IMPORT-001": _probe_ds_import_001,
    "DS-IMPORT-002": _probe_ds_import_002,
    "DS-IMPORT-003": _probe_ds_import_003,
    "DS-IMPORT-004": _probe_ds_import_004,
    "DS-IMPORT-005": _probe_ds_import_005,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_inventory_seeds_cover_evidence_subset() -> None:
    assert len(SEEDS) >= 5
    ids = {s["defect_id"] for s in SEEDS}
    assert ids >= set(PROBES)
    families = {s["family"] for s in SEEDS}
    assert "module_top_level_environment_write" in families
    assert "installer_construction_path_and_fs_mutation" in families
    assert "installer_reachability_pip_subprocess" in families
    assert "persistent_user_path_write" in families
    assert "runtime_installer_bootstrap_write" in families


@pytest.mark.parametrize("defect_id", sorted(PROBES), ids=sorted(PROBES))
def test_seeded_import_effect_fails_purity_oracle(defect_id: str) -> None:
    """Acceptance: purity fails on every seeded import effect."""
    seed = SEED_BY_ID[defect_id]
    observation = PROBES[defect_id]()
    verdict = _classify_observation(defect_id, observation)

    assert verdict["purity_passed"] is False, (
        f"{defect_id} purity unexpectedly passed; oracle={seed['oracle']!r}; "
        f"observation={json.dumps({k: observation.get(k) for k in ('after_env','path_delta','effects','force_error','pip_error')}, default=str)[:2000]}"
    )
    assert verdict["matched_effects"], f"{defect_id} recorded no matched legacy effects"
    assert verdict["disposition"] == "legacy_impurity_observed"
    assert verdict["normalized_as_success"] is False
    assert verdict["fca"]["unsafe_promotion"] is False
    assert "effect_successful" in verdict["fca"]["forbidden_predicates"]
    assert "production_supported" in verdict["fca"]["forbidden_predicates"]

    # Exact observed behavior must be present (not erased / not success-shaped).
    assert observation["defect_id"] == defect_id
    assert isinstance(observation["effects"], list)
    assert observation.get("elapsed_ms") is not None
    assert observation.get("sandbox")
    # Harness sandbox roots must be the empty explicit state/home equivalents.
    assert observation["sandbox"].startswith(tempfile.gettempdir()) or "facp021-" in observation["sandbox"]


@pytest.mark.parametrize("defect_id", sorted(PROBES), ids=sorted(PROBES))
def test_observation_never_normalized_as_success(defect_id: str) -> None:
    observation = PROBES[defect_id]()
    verdict = _classify_observation(defect_id, observation)
    blob = json.dumps({"observation": observation, "verdict": verdict}, default=str).lower()
    # Disposition and FCA labels must not claim success/purity.
    assert verdict["disposition"] not in FORBIDDEN_SUCCESS_LABELS
    assert verdict["normalized_as_success"] is False
    assert '"purity_passed": false' in json.dumps(verdict).lower() or verdict["purity_passed"] is False
    for label in ("production_supported", "effect_successful"):
        assert label in verdict["fca"]["forbidden_predicates"]
    # Do not treat observed impurity as a green hermetic import claim.
    assert "legacy_impurity" in verdict["disposition"]
    assert "success" not in verdict["disposition"]
    # Observation payload itself must not advertise success disposition.
    for key in ("disposition", "status", "result", "outcome"):
        value = observation.get(key)
        if isinstance(value, str):
            assert value.lower() not in FORBIDDEN_SUCCESS_LABELS, (defect_id, key, value)
    # Keep a cheap sanity check that we did not silently drop the seed id.
    assert seed_id_for(defect_id) in blob or defect_id.lower() in blob


def seed_id_for(defect_id: str) -> str:
    return SEED_BY_ID[defect_id]["seed_id"].lower()


def test_probes_run_from_empty_explicit_state_without_harness_network_process_writes() -> None:
    """Harness itself uses empty HOME/XDG/state/project and denies net/process/writes."""
    # Structural check of sandbox construction + one live probe.
    with tempfile.TemporaryDirectory(prefix="facp021-harness-") as raw:
        sandbox = Path(raw)
        env = _sandbox_env(sandbox)
        assert Path(env["HOME"]).is_dir()
        assert Path(env["XDG_STATE_HOME"]).is_dir()
        assert Path(env["IPFS_DATASETS_PROJECT_ROOT"]).is_dir()
        assert list(Path(env["HOME"]).iterdir())  # only the xdg dirs we created
        # No pre-seeded installer state under explicit state root.
        assert list(Path(env["XDG_STATE_HOME"]).rglob("*")) == [] or all(
            p.is_dir() for p in Path(env["XDG_STATE_HOME"]).rglob("*")
        )
        assert "IPFS_DATASETS_AUTO_INSTALL" not in env
        assert env["NO_NETWORK"] == "1"

    observation = _probe_ds_import_001()
    # Network/process denials are active; seed 001 should not need them, so kinds
    # should be empty or limited — but must not include successful network I/O.
    assert not any(e.get("kind") == "network" for e in observation["effects"])
    # Out-of-sandbox package state must remain absent after the probe.
    package_state = _PACKAGE_ROOT / "state" / "runtime_installer_state.json"
    assert not package_state.is_file()


def test_baseline_document_records_legacy_behavior_without_success_claim() -> None:
    assert _BASELINE_DOC.is_file(), f"missing baseline doc: {_BASELINE_DOC}"
    text = _BASELINE_DOC.read_text(encoding="utf-8")
    assert TASK_ID in text
    assert EVIDENCE_ID in text or "datasets-import-purity" in text
    assert "reject_illegal_promotion" in text or "legacy_impurity" in text
    for defect_id in PROBES:
        assert defect_id in text
        assert SEED_BY_ID[defect_id]["seed_id"] in text
    # Must not normalize characterization as purity success.
    lowered = text.lower()
    assert "production-success" in lowered
    assert "promoted" in lowered
    assert "unsafe_promotion" in lowered or "unsafe promotion" in lowered
    assert "legacy impurity" in lowered or "legacy_impurity" in lowered
    assert "facp-022" in lowered
    assert "normalized_as_success" in lowered
    # Evidence subset called out by the task.
    for needle in (
        "environment",
        "PATH",
        "installer",
        "network",
        "subprocess",
        "persistent",
        "time",
        "memory",
    ):
        assert needle.lower() in lowered


def test_all_seeds_fail_in_aggregate_characterization() -> None:
    """Aggregate gate: every seed fails purity; none are success."""
    results = []
    for defect_id, probe in sorted(PROBES.items()):
        observation = probe()
        verdict = _classify_observation(defect_id, observation)
        results.append(verdict)
        assert verdict["purity_passed"] is False
        assert verdict["normalized_as_success"] is False
    assert len(results) == len(PROBES)
    assert all(r["disposition"] == "legacy_impurity_observed" for r in results)
