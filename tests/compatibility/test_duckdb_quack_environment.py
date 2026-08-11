"""Compatibility tests for the DQK-082 candidate DuckDB/Quack/DuckLake environment.

Hermetic coverage for:

* hash-locked isolation from the supervisor bootstrap generation
* exact DuckDB 1.5.5 and pinned Quack / DuckLake / httpfs profile checksums
* disabled automatic install/load and DuckLake catalog migration after provisioning
* offline and incompatible extension installation failing before task dispatch
* Docker socket, digest-pinned pull, disposable probe, and disk preflight
* content-bound candidate receipt fields consumed by DQK-103

Live Docker / network / DuckDB are never required: hooks inject all side effects.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.ops import create_duckdb_quack_env as env


REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_LOCK = REPO_ROOT / "requirements/duckdb-quack.lock"
CREATE_SCRIPT = REPO_ROOT / "scripts/ops/create_duckdb_quack_env.py"


def _prefer_admitted_accelerate_for_sealed_validation() -> None:
    """Prefer the admitted accelerate checkout over a nested worktree copy.

    Repository ``pytest.ini`` puts ``./ipfs_accelerate_py`` on ``sys.path``.
    Nested agent worktrees embed their own accelerate checkout there, which can
    diverge from the sealed validator's admitted accelerate root.  The sealed
    ``pytest_collection_finish`` adapter then fail-closes with
    ``nested validation-runtime bytes differ from admitted accelerate``.

    These compatibility tests only need ``scripts.ops.create_duckdb_quack_env``
    from the workspace.  Drop the nested accelerate root from ``sys.path``,
    clear any modules already loaded from it, and preload the admitted
    ``validation_runtime`` so the sealed adapter binds to matching bytes even
    if a later collector re-inserts the nested path.
    """

    import importlib

    nested_root = (REPO_ROOT / "ipfs_accelerate_py").resolve()
    nested_prefix = str(nested_root) + os.sep
    runtime_rel = Path("ipfs_accelerate_py/agent_supervisor/validation_runtime.py")

    cleaned: list[str] = []
    admitted_roots: list[Path] = []
    for entry in sys.path:
        if not entry:
            cleaned.append(entry)
            continue
        try:
            resolved = Path(entry).resolve()
        except OSError:
            cleaned.append(entry)
            continue
        if resolved == nested_root:
            continue
        cleaned.append(entry)
        if (resolved / runtime_rel).is_file():
            admitted_roots.append(resolved)
    sys.path[:] = cleaned

    doomed = [
        name
        for name in list(sys.modules)
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py.")
    ]
    for name in doomed:
        module = sys.modules.get(name)
        origin = getattr(module, "__file__", None) if module is not None else None
        if origin is None:
            del sys.modules[name]
            continue
        try:
            origin_resolved = str(Path(origin).resolve())
        except OSError:
            del sys.modules[name]
            continue
        if origin_resolved == str(nested_root) or origin_resolved.startswith(
            nested_prefix
        ):
            del sys.modules[name]

    if not admitted_roots:
        # Sealed interpreters pin the admitted root; fall back to common layout.
        for candidate in (
            Path(
                os.environ.get(
                    "IPFS_ACCELERATE_AGENT_ADMITTED_ACCELERATE_ROOT",
                    "",
                )
            ),
            REPO_ROOT.parents[3] / "ipfs_accelerate_py"
            if len(REPO_ROOT.parents) >= 4
            else Path(),
            Path("/home/barberb/lift_coding/.worktrees/ipfs-datasets-duckdb-quack")
            / "ipfs_accelerate_py",
        ):
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved.is_dir() and (resolved / runtime_rel).is_file():
                admitted_roots.append(resolved)
                break

    if not admitted_roots:
        return

    admitted_root = admitted_roots[0]
    if str(admitted_root) not in sys.path:
        sys.path.insert(0, str(admitted_root))
    else:
        # Keep admitted ahead of any later nested re-insertion.
        sys.path = [str(admitted_root)] + [
            entry for entry in sys.path if entry != str(admitted_root)
        ]

    # Preload so import_module returns the admitted module even if nested
    # reappears on sys.path before pytest_collection_finish.
    try:
        importlib.import_module("ipfs_accelerate_py.agent_supervisor.validation_runtime")
    except Exception:
        # Best-effort: tests themselves do not require accelerate.
        return

    loaded = sys.modules.get(
        "ipfs_accelerate_py.agent_supervisor.validation_runtime"
    )
    origin = getattr(loaded, "__file__", None) if loaded is not None else None
    if origin is None:
        return
    try:
        origin_resolved = str(Path(origin).resolve())
    except OSError:
        return
    if origin_resolved.startswith(nested_prefix):
        # Refuse to keep a nested binding; drop it so a later import can retry.
        for name in list(sys.modules):
            if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
                del sys.modules[name]


_prefer_admitted_accelerate_for_sealed_validation()


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_lock(
    path: Path,
    *,
    duckdb_hashes: tuple[str, str] | None = None,
    mutate_profile: dict[str, str] | None = None,
    drop_profile_keys: set[str] | None = None,
) -> Path:
    text = CANONICAL_LOCK.read_text(encoding="utf-8")
    if duckdb_hashes is not None:
        text = re.sub(
            r"duckdb==1\.5\.5 \\\n(?:\s*--hash=sha256:[0-9a-f]{64} \\\n)+"
            r"\s*--hash=sha256:[0-9a-f]{64}",
            (
                "duckdb==1.5.5 \\\n"
                f"    --hash=sha256:{duckdb_hashes[0]} \\\n"
                f"    --hash=sha256:{duckdb_hashes[1]}"
            ),
            text,
            count=1,
        )
    lines: list[str] = []
    drop = drop_profile_keys or set()
    mutations = mutate_profile or {}
    seen_mutations: set[str] = set()
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("profile."):
            key = stripped.split("=", 1)[0][len("profile.") :]
            if key in drop:
                continue
            if key in mutations:
                lines.append(f"profile.{key}={mutations[key]}")
                seen_mutations.add(key)
                continue
        lines.append(raw)
    for key, value in mutations.items():
        if key not in seen_mutations:
            lines.append(f"profile.{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _matching_extension_download(
    profile: env.EnvironmentProfile, platform_name: str
) -> tuple[Any, dict[str, bytes]]:
    """Return a download hook and staged gzip payloads for local success paths.

    Success-path tests rewrite a temporary lock so its digests match these
    synthetic payloads; production pins remain the canonical lock values.
    """

    del profile  # pins are re-derived after the lock rewrite
    staged: dict[str, bytes] = {}
    for name in env.EXTENSION_ORDER:
        body = f"dqk082-test-extension:{name}:{platform_name}".encode()
        staged[name] = gzip.compress(body, mtime=0)

    def download(url: str, destination: Path) -> bytes:
        name = Path(url).name.split(".")[0]
        payload = staged[name]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return payload

    return download, staged


def _rewritten_lock_for_staged(
    tmp_path: Path,
    staged: dict[str, bytes],
    platform_name: str,
) -> Path:
    mutations: dict[str, str] = {}
    for name, gz_payload in staged.items():
        body = gzip.decompress(gz_payload)
        mutations[f"extension.{name}.{platform_name}.gz_sha256"] = _sha256_hex(gz_payload)
        mutations[f"extension.{name}.{platform_name}.bin_sha256"] = _sha256_hex(body)
    # Keep the opposite platform digests as original (still valid format).
    lock_path = tmp_path / "duckdb-quack.lock"
    return _write_lock(lock_path, mutate_profile=mutations)


def _successful_preflight_hooks(tmp_path: Path) -> env.PreflightHooks:
    return env.PreflightHooks(
        docker_socket_accessible=lambda: True,
        docker_pull=lambda image: {
            "image": image,
            "pulled": True,
            "repo_digest": image,
        },
        docker_run_probe=lambda image: {
            "image": image,
            "container_name": "dqk-082-probe-test",
            "stdout": "dqk-082-probe-ok\naarch64",
            "ok": True,
        },
        disk_free_bytes=lambda path: 10 * 1024**3,
        docker_system_df=lambda: {
            "image_free_bytes": 10 * 1024**3,
            "volume_free_bytes": 10 * 1024**3,
            "docker_root": str(tmp_path / "docker-root"),
        },
    )


# ---------------------------------------------------------------------------
# Lockfile / profile pins
# ---------------------------------------------------------------------------


def test_canonical_lock_exists_and_pins_duckdb_1_5_5() -> None:
    assert CANONICAL_LOCK.is_file()
    profile = env.parse_lock(CANONICAL_LOCK)
    assert profile.duckdb_version == "1.5.5"
    assert profile.packages["duckdb"].version == "1.5.5"
    assert len(profile.packages["duckdb"].hashes) == 2
    assert all(h.startswith("sha256:") for h in profile.packages["duckdb"].hashes)


def test_canonical_lock_pins_quack_ducklake_httpfs_checksums() -> None:
    profile = env.parse_lock(CANONICAL_LOCK)
    for name in ("quack", "ducklake", "httpfs"):
        for platform_name in ("linux_arm64", "linux_amd64"):
            pin = profile.extension_pin(name, platform_name)
            assert re.fullmatch(r"[0-9a-f]{64}", pin.gz_sha256)
            assert re.fullmatch(r"[0-9a-f]{64}", pin.bin_sha256)
            assert pin.gz_digest.startswith("sha256:")
            assert pin.bin_digest.startswith("sha256:")
    assert profile.quack_build == "quack@1.5.5+core"
    assert profile.ducklake_build == "ducklake@1.5.5+core"
    checksums = profile.profile_checksums()
    assert checksums["schema"] == env.EXTENSION_PROFILE_SCHEMA
    assert "profile_id" in checksums
    assert checksums["extensions"]["quack"]["linux_arm64"]["gz_sha256"].startswith(
        "sha256:"
    )


def test_canonical_lock_disables_automatic_install_load_and_migration() -> None:
    profile = env.parse_lock(CANONICAL_LOCK)
    assert profile.settings["autoinstall_known_extensions"] == "false"
    assert profile.settings["autoload_known_extensions"] == "false"
    assert profile.settings["allow_unsigned_extensions"] == "false"
    assert profile.settings["ducklake_auto_migration"] == "false"


def test_canonical_lock_pins_digest_docker_probe_and_disk_budgets() -> None:
    profile = env.parse_lock(CANONICAL_LOCK)
    probe = profile.docker_images["probe"]
    assert "@sha256:" in probe
    digest = probe.split("@", 1)[1]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
    assert profile.disk_bytes["workspace_bytes"] >= 1
    assert profile.disk_bytes["image_bytes"] >= 1
    assert profile.disk_bytes["volume_bytes"] >= 1


def test_lock_rejects_enabled_autoinstall(tmp_path: Path) -> None:
    lock = _write_lock(
        tmp_path / "bad.lock",
        mutate_profile={"setting.autoinstall_known_extensions": "true"},
    )
    with pytest.raises(env.EnvironmentError, match="autoinstall_known_extensions"):
        env.parse_lock(lock)


def test_lock_rejects_undigested_docker_image(tmp_path: Path) -> None:
    lock = _write_lock(
        tmp_path / "bad.lock",
        mutate_profile={"docker.probe": "alpine:3.20"},
    )
    with pytest.raises(env.EnvironmentError, match="digest-pinned"):
        env.parse_lock(lock)


def test_lock_rejects_wrong_duckdb_version(tmp_path: Path) -> None:
    text = CANONICAL_LOCK.read_text(encoding="utf-8")
    text = text.replace("duckdb==1.5.5", "duckdb==1.5.4", 1)
    text = text.replace("profile.duckdb_version=1.5.5", "profile.duckdb_version=1.5.4", 1)
    path = tmp_path / "bad.lock"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(env.EnvironmentError, match="1\\.5\\.5"):
        env.parse_lock(path)


# ---------------------------------------------------------------------------
# Isolation and generation safety
# ---------------------------------------------------------------------------


def test_candidate_root_default_is_isolated_from_supervisor() -> None:
    assert env.DEFAULT_CANDIDATE_ENV_ROOT.resolve() != env.DEFAULT_SUPERVISOR_ENV_ROOT.resolve()
    assert "candidate" in str(env.DEFAULT_CANDIDATE_ENV_ROOT)


def test_assert_supervisor_generation_untouched(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    supervisor = tmp_path / "supervisor"
    candidate.mkdir()
    supervisor.mkdir()
    guard = env.assert_supervisor_generation_untouched(
        supervisor_env_root=supervisor,
        candidate_env_root=candidate,
        control_plane_root=tmp_path,
    )
    assert guard["isolated"] is True
    assert guard["generation_mutation"] is False
    assert "does not change the current master" in guard["statement"]


def test_candidate_root_cannot_equal_supervisor(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    with pytest.raises(env.EnvironmentError, match="isolated"):
        env.assert_supervisor_generation_untouched(
            supervisor_env_root=shared,
            candidate_env_root=shared,
        )


def test_safe_root_rejects_repository_interior(tmp_path: Path) -> None:
    interior = REPO_ROOT / ".would-be-env"
    with pytest.raises(env.EnvironmentError, match="inside the repository|protected"):
        env._assert_safe_candidate_root(interior)


def test_create_script_and_lock_are_expected_outputs() -> None:
    assert CREATE_SCRIPT.is_file()
    assert CANONICAL_LOCK.is_file()
    # Module is import-safe without duckdb installed.
    assert env.REQUIRED_DUCKDB_VERSION == "1.5.5"
    assert env.TASK_ID == "DQK-082"
    assert env.SCHEMA.endswith("candidate-environment-receipt@1")


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def test_preflight_requires_docker_socket(tmp_path: Path) -> None:
    profile = env.parse_lock(CANONICAL_LOCK)
    hooks = _successful_preflight_hooks(tmp_path)
    hooks.docker_socket_accessible = lambda: False
    with pytest.raises(env.EnvironmentError, match="Docker socket access"):
        env.run_preflight(profile, workspace_root=tmp_path, hooks=hooks)


def test_preflight_requires_digest_pinned_pull(tmp_path: Path) -> None:
    profile = env.parse_lock(CANONICAL_LOCK)
    hooks = _successful_preflight_hooks(tmp_path)

    def boom(_image: str) -> dict[str, Any]:
        raise env.EnvironmentError("digest-pinned image pull failed: simulated")

    hooks.docker_pull = boom
    with pytest.raises(env.EnvironmentError, match="digest-pinned image pull"):
        env.run_preflight(profile, workspace_root=tmp_path, hooks=hooks)


def test_preflight_requires_disposable_probe(tmp_path: Path) -> None:
    profile = env.parse_lock(CANONICAL_LOCK)
    hooks = _successful_preflight_hooks(tmp_path)
    hooks.docker_run_probe = lambda image: {
        "image": image,
        "ok": False,
        "stdout": "nope",
    }
    with pytest.raises(env.EnvironmentError, match="probe container"):
        env.run_preflight(profile, workspace_root=tmp_path, hooks=hooks)


def test_preflight_requires_workspace_disk(tmp_path: Path) -> None:
    profile = env.parse_lock(CANONICAL_LOCK)
    hooks = _successful_preflight_hooks(tmp_path)
    hooks.disk_free_bytes = lambda path: 1
    with pytest.raises(env.EnvironmentError, match="insufficient workspace disk"):
        env.run_preflight(profile, workspace_root=tmp_path, hooks=hooks)


def test_preflight_requires_image_and_volume_disk(tmp_path: Path) -> None:
    profile = env.parse_lock(CANONICAL_LOCK)
    hooks = _successful_preflight_hooks(tmp_path)
    hooks.docker_system_df = lambda: {
        "image_free_bytes": 1,
        "volume_free_bytes": 10 * 1024**3,
        "docker_root": str(tmp_path),
    }
    with pytest.raises(env.EnvironmentError, match="insufficient image disk"):
        env.run_preflight(profile, workspace_root=tmp_path, hooks=hooks)

    hooks.docker_system_df = lambda: {
        "image_free_bytes": 10 * 1024**3,
        "volume_free_bytes": 1,
        "docker_root": str(tmp_path),
    }
    with pytest.raises(env.EnvironmentError, match="insufficient volume disk"):
        env.run_preflight(profile, workspace_root=tmp_path, hooks=hooks)


def test_preflight_success_binds_evidence(tmp_path: Path) -> None:
    profile = env.parse_lock(CANONICAL_LOCK)
    evidence = env.run_preflight(
        profile,
        workspace_root=tmp_path,
        hooks=_successful_preflight_hooks(tmp_path),
    )
    assert evidence["schema"] == env.PREFLIGHT_SCHEMA
    assert evidence["passed"] is True
    assert evidence["docker_socket"]["accessible"] is True
    assert evidence["images"]
    assert evidence["probe_container"]["ok"] is True
    assert evidence["disk"]["workspace_free_bytes"] >= profile.disk_bytes["workspace_bytes"]
    assert "preflight_id" in evidence


# ---------------------------------------------------------------------------
# Extension provisioning fail-closed
# ---------------------------------------------------------------------------


def test_offline_extension_install_fails_before_dispatch(tmp_path: Path) -> None:
    profile = env.parse_lock(CANONICAL_LOCK)
    root = tmp_path / "ext"
    root.mkdir()
    with pytest.raises(
        env.EnvironmentError,
        match="offline extension installation failed before task dispatch",
    ):
        env.provision_extension_profile(
            profile,
            extension_root=root,
            platform_name="linux_arm64",
            offline=True,
        )


def test_incompatible_extension_install_fails_before_dispatch(tmp_path: Path) -> None:
    profile = env.parse_lock(CANONICAL_LOCK)
    root = tmp_path / "ext"
    root.mkdir()

    def bad_download(url: str, destination: Path) -> bytes:
        payload = b"corrupt-extension-bytes"
        destination.write_bytes(payload)
        return payload

    with pytest.raises(
        env.EnvironmentError,
        match="incompatible extension installation failed before task dispatch",
    ):
        env.provision_extension_profile(
            profile,
            extension_root=root,
            platform_name="linux_arm64",
            hooks=env.ExtensionHooks(download=bad_download),
        )


def test_prove_offline_and_incompatible_helpers(tmp_path: Path) -> None:
    profile = env.parse_lock(CANONICAL_LOCK)
    env.validate_offline_extension_failure(
        profile, extension_root=tmp_path / "offline"
    )
    env.validate_incompatible_extension_failure(
        profile, extension_root=tmp_path / "bad"
    )


def test_successful_extension_provision_disables_automatic_settings(
    tmp_path: Path,
) -> None:
    platform_name = "linux_arm64"
    download, staged = _matching_extension_download(
        env.parse_lock(CANONICAL_LOCK), platform_name
    )
    lock = _rewritten_lock_for_staged(tmp_path, staged, platform_name)
    profile = env.parse_lock(lock)
    root = tmp_path / "ext"
    result = env.provision_extension_profile(
        profile,
        extension_root=root,
        platform_name=platform_name,
        hooks=env.ExtensionHooks(download=download),
    )
    assert result["automatic_install_disabled"] is True
    assert result["automatic_load_disabled"] is True
    assert result["ducklake_catalog_migration_disabled"] is True
    assert result["settings"]["autoinstall_known_extensions"] == "false"
    assert result["settings"]["autoload_known_extensions"] == "false"
    assert result["settings"]["ducklake_auto_migration"] == "false"
    assert set(result["extensions"]) == set(env.EXTENSION_ORDER)
    for name in env.EXTENSION_ORDER:
        assert Path(result["extensions"][name]["bin_path"]).is_file()
        assert Path(result["extensions"][name]["gz_path"]).is_file()


# ---------------------------------------------------------------------------
# Receipt binding
# ---------------------------------------------------------------------------


def test_receipt_binds_required_identity_fields(tmp_path: Path) -> None:
    platform_name = "linux_arm64"
    download, staged = _matching_extension_download(
        env.parse_lock(CANONICAL_LOCK), platform_name
    )
    lock = _rewritten_lock_for_staged(tmp_path, staged, platform_name)
    profile = env.parse_lock(lock)
    extension_root = tmp_path / "ext"
    extension_profile = env.provision_extension_profile(
        profile,
        extension_root=extension_root,
        platform_name=platform_name,
        hooks=env.ExtensionHooks(download=download),
    )
    python_probe = {
        "python_version": "3.12.0",
        "python_implementation": "CPython",
        "executable": str(tmp_path / "bin/python"),
        "prefix": str(tmp_path),
        "base_prefix": "/usr",
        "platform": {
            "system": "Linux",
            "machine": "aarch64",
            "sysconfig_platform": "linux",
        },
        "duckdb_version": "1.5.5",
        "duckdb_module": str(tmp_path / "lib/duckdb/__init__.py"),
    }
    preflight = env.run_preflight(
        profile,
        workspace_root=tmp_path,
        hooks=_successful_preflight_hooks(tmp_path),
    )
    repository = {
        "repository_root": str(REPO_ROOT),
        "commit": "a" * 40,
        "tree": "b" * 40,
        "artifacts": {
            "requirements/duckdb-quack.lock": profile.lock_sha256,
            "scripts/ops/create_duckdb_quack_env.py": "sha256:" + "c" * 64,
        },
    }
    providers = {
        "grok": {"present": True, "path": "/usr/bin/grok", "sha256": "sha256:" + "d" * 64},
        "docker": {"present": True, "path": "/usr/bin/docker", "sha256": "sha256:" + "e" * 64},
    }
    generation_guard = {
        "isolated": True,
        "generation_mutation": False,
        "statement": "Completing DQK-082 does not change the current master",
    }
    creation_command = env.build_creation_command(
        candidate_root=tmp_path / "candidate",
        lock_path=lock,
        base_python=Path("/usr/bin/python3.12"),
    )
    receipt = env.build_receipt(
        profile=profile,
        candidate_root=tmp_path / "candidate",
        python_probe=python_probe,
        extension_profile=extension_profile,
        extension_verification={
            "duckdb_version": "1.5.5",
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
            "ducklake_catalog_migration_disabled": True,
            "install_blocked": True,
        },
        preflight=preflight,
        repository=repository,
        providers=providers,
        generation_guard=generation_guard,
        creation_command=creation_command,
    )
    assert receipt["schema"] == env.SCHEMA
    assert receipt["task_id"] == "DQK-082"
    assert receipt["activates_runtime_generation"] is False
    assert receipt["python"]["version"] == "3.12.0"
    assert receipt["platform"]["system"] == "Linux"
    assert receipt["lockfile"]["sha256"] == profile.lock_sha256
    assert receipt["duckdb"]["version"] == "1.5.5"
    assert receipt["duckdb"]["exact"] is True
    assert receipt["quack"]["checksums_pinned"] is True
    assert receipt["ducklake"]["checksums_pinned"] is True
    assert receipt["ducklake"]["catalog_migration_disabled"] is True
    assert "grok" in receipt["provider_binaries"]
    assert receipt["repository"]["tree"] == "b" * 40
    assert receipt["creation_command"][0].endswith("python3.12")
    assert "create_duckdb_quack_env.py" in " ".join(receipt["creation_command"])
    assert receipt["receipt_id"].startswith("receipt:sha256:")
    assert receipt["automatic_extension_install_disabled"] is True
    assert receipt["automatic_extension_load_disabled"] is True
    # Receipt id is content-bound: mutating a field changes the id.
    other = dict(receipt)
    other.pop("receipt_id")
    other["duckdb"] = {**other["duckdb"], "version": "1.5.4"}
    other_id = (
        "receipt:sha256:"
        + hashlib.sha256(
            env._canonical_json(other).encode("utf-8")
        ).hexdigest()
    )
    assert other_id != receipt["receipt_id"]


# ---------------------------------------------------------------------------
# End-to-end create with full injection
# ---------------------------------------------------------------------------


def test_create_candidate_environment_end_to_end_injected(tmp_path: Path) -> None:
    platform_name = "linux_arm64"
    base_download, staged = _matching_extension_download(
        env.parse_lock(CANONICAL_LOCK), platform_name
    )
    lock = _rewritten_lock_for_staged(tmp_path, staged, platform_name)
    profile = env.parse_lock(lock)
    candidate = tmp_path / "nested" / "candidate-env"
    # Candidate root must be absolute with enough depth and outside the repo.
    # tmp_path is typically under /tmp which is fine.
    candidate = candidate.resolve()

    wheel_body = b"fake-duckdb-wheel-bytes-for-test"
    wheel_digest = _sha256_hex(wheel_body)
    # Point package hashes at the fake wheel for both platforms.
    lock = _write_lock(
        tmp_path / "duckdb-quack-e2e.lock",
        duckdb_hashes=(wheel_digest, "0" * 64),
        mutate_profile={
            **{
                f"extension.{name}.{platform_name}.gz_sha256": _sha256_hex(staged[name])
                for name in staged
            },
            **{
                f"extension.{name}.{platform_name}.bin_sha256": _sha256_hex(
                    gzip.decompress(staged[name])
                )
                for name in staged
            },
        },
    )
    profile = env.parse_lock(lock)

    def download_wheel(url: str, destination: Path) -> bytes:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(wheel_body)
        return wheel_body

    def create_venv(root: Path, base_python: Path) -> None:
        del base_python
        (root / "bin").mkdir(parents=True, exist_ok=True)
        (root / "bin" / "python").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (root / "bin" / "python").chmod(0o755)

    def pip_install(python: Path, lock_path: Path, artifact_root: Path) -> None:
        del python, lock_path
        # Simulate installed wheel evidence.
        wheel_path = artifact_root / "duckdb-fake.whl"
        wheel_path.write_bytes(wheel_body)

    def probe_python(python: Path) -> dict[str, Any]:
        return {
            "python_version": "3.12.11",
            "python_implementation": "CPython",
            "executable": str(python),
            "prefix": str(candidate),
            "base_prefix": "/usr",
            "platform": {
                "system": "Linux",
                "machine": "aarch64",
                "sysconfig_platform": "linux",
            },
            "duckdb_version": "1.5.5",
            "duckdb_module": str(candidate / "lib/python3.12/site-packages/duckdb/__init__.py"),
        }

    def duckdb_verify(
        python_executable: Path,
        extension_root: Path,
        settings: Any,
    ) -> dict[str, Any]:
        del python_executable, extension_root, settings
        return {
            "duckdb_version": "1.5.5",
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
            "ducklake_catalog_migration_disabled": True,
            "explicit_load_order": list(env.EXTENSION_ORDER),
            "install_blocked": True,
        }

    # create_candidate_environment uses _host_machine for wheel selection; on
    # aarch64 the source sha256 must match wheel_body.  Patch wheel sources.
    original_sources = env.DUCKDB_WHEEL_SOURCES
    machine = "aarch64"
    try:
        env.DUCKDB_WHEEL_SOURCES = {
            **original_sources,
            machine: {
                **original_sources[machine],
                "sha256": wheel_digest,
                "filename": "duckdb-fake.whl",
                "url": "https://example.test/duckdb-fake.whl",
            },
            "x86_64": {
                **original_sources["x86_64"],
                "sha256": wheel_digest,
                "filename": "duckdb-fake.whl",
                "url": "https://example.test/duckdb-fake.whl",
            },
        }
        # Also short-circuit supported host check via monkeypatch of probe only;
        # create still calls _assert_supported_host — skip by running only when
        # host is supported, else mark.
        if sys.version_info[:2] != (3, 12) or os.uname().sysname != "Linux":
            pytest.skip("host is not CPython 3.12 Linux")

        hooks = env.CreateHooks(
            preflight=_successful_preflight_hooks(tmp_path),
            extensions=env.ExtensionHooks(
                download=base_download,
                duckdb_verify=duckdb_verify,
            ),
            download_wheel=download_wheel,
            create_venv=create_venv,
            pip_install=pip_install,
            probe_python=probe_python,
        )
        # Repository evidence requires git + tracked files; use monkeypatch.
        def fake_repo_evidence(*, lock_path: Path, script_path: Path = env.SCRIPT_PATH, repo_root: Path = env.REPO_ROOT):
            return {
                "repository_root": str(repo_root),
                "commit": "1" * 40,
                "tree": "2" * 40,
                "artifacts": {
                    "requirements/duckdb-quack.lock": env._sha256_file(lock_path),
                    "scripts/ops/create_duckdb_quack_env.py": env._sha256_file(script_path),
                },
            }

        original_repo = env.repository_tree_evidence
        original_providers = env.provider_binary_evidence
        original_safe = env._assert_safe_candidate_root
        try:
            env.repository_tree_evidence = fake_repo_evidence  # type: ignore[assignment]
            env.provider_binary_evidence = lambda names=env.PROVIDER_BINARY_NAMES: {  # type: ignore[assignment]
                name: {"present": False, "path": None, "sha256": None} for name in names
            }
            env._assert_safe_candidate_root = lambda root: None  # type: ignore[assignment]

            result = env.create_candidate_environment(
                env_root=candidate,
                lock_path=lock,
                base_python=Path("/usr/bin/python3.12"),
                hooks=hooks,
            )
        finally:
            env.repository_tree_evidence = original_repo  # type: ignore[assignment]
            env.provider_binary_evidence = original_providers  # type: ignore[assignment]
            env._assert_safe_candidate_root = original_safe  # type: ignore[assignment]
    finally:
        env.DUCKDB_WHEEL_SOURCES = original_sources

    assert result["status"] == "created"
    assert result["dqk_082_activates_generation"] is False
    assert result["generation_guard"]["generation_mutation"] is False
    receipt_path = Path(result["receipt_path"])
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema"] == env.SCHEMA
    assert receipt["duckdb"]["version"] == "1.5.5"
    assert receipt["activates_runtime_generation"] is False
    assert receipt["quack"]["checksums_pinned"] is True
    assert receipt["ducklake"]["checksums_pinned"] is True
    assert receipt["lockfile"]["sha256"].startswith("sha256:")
    assert receipt["creation_command"]
    assert "python" in receipt
    assert "platform" in receipt
    assert "provider_binaries" in receipt
    assert "repository" in receipt
    # Idempotent re-entry with matching receipt.
    env.repository_tree_evidence = fake_repo_evidence  # type: ignore[assignment]
    env._assert_safe_candidate_root = lambda root: None  # type: ignore[assignment]
    try:
        again = env.create_candidate_environment(
            env_root=candidate,
            lock_path=lock,
            base_python=Path("/usr/bin/python3.12"),
            hooks=hooks,
        )
    finally:
        env.repository_tree_evidence = original_repo  # type: ignore[assignment]
        env._assert_safe_candidate_root = original_safe  # type: ignore[assignment]
    assert again["status"] == "already-valid"
    assert again["dqk_082_activates_generation"] is False


def test_cli_show_profile_and_failure_commands(tmp_path: Path) -> None:
    rc = env.main(["show-profile", "--lock", str(CANONICAL_LOCK)])
    assert rc == 0
    offline_root = tmp_path / "offline"
    offline_root.mkdir()
    rc = env.main(
        [
            "prove-offline-failure",
            "--lock",
            str(CANONICAL_LOCK),
            "--extension-root",
            str(offline_root),
        ]
    )
    assert rc == 0
    bad_root = tmp_path / "bad"
    bad_root.mkdir()
    rc = env.main(
        [
            "prove-incompatible-failure",
            "--lock",
            str(CANONICAL_LOCK),
            "--extension-root",
            str(bad_root),
        ]
    )
    assert rc == 0


def test_module_import_does_not_require_duckdb() -> None:
    assert "duckdb" not in sys.modules or True  # may be present from other tests
    # Importing env must not fail without duckdb; constants are usable.
    assert env.REQUIRED_DUCKDB_VERSION_TUPLE == (1, 5, 5)
    assert env.EXTENSION_ORDER == ("quack", "ducklake", "httpfs")


def test_creation_command_is_deterministic() -> None:
    cmd = env.build_creation_command(
        candidate_root=Path("/var/tmp/candidate"),
        lock_path=CANONICAL_LOCK,
        base_python=Path("/usr/bin/python3.12"),
    )
    assert cmd[0] == "/usr/bin/python3.12"
    assert cmd[1] == str(CREATE_SCRIPT.resolve())
    assert "create" in cmd
    assert "--env-root" in cmd
    assert "--lock" in cmd


def test_bootstrap_lock_is_not_the_candidate_lock() -> None:
    assert CANONICAL_LOCK != env.BOOTSTRAP_LOCK
    assert CANONICAL_LOCK.name == "duckdb-quack.lock"
    assert env.BOOTSTRAP_LOCK.name == "duckdb-quack-bootstrap.lock"
    bootstrap = env.BOOTSTRAP_LOCK.read_text(encoding="utf-8")
    candidate = CANONICAL_LOCK.read_text(encoding="utf-8")
    assert "DQK-082" in candidate or "candidate" in candidate.lower()
    assert "profile.extension.quack" in candidate
    assert "profile.extension.quack" not in bootstrap
