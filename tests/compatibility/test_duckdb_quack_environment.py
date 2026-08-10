"""Compatibility tests for the DQK-082 candidate DuckDB/Quack/DuckLake environment.

Acceptance criteria covered:

* Candidate environment is isolated from unrelated supervisors and reproducible
  from hashes.
* Completing DQK-082 does not change the current master, lane, daemon, or
  writer generation.
* DuckDB is exactly 1.5.5 and Quack / DuckLake extension/profile checksums are
  pinned.
* Automatic extension install/load and DuckLake catalog migration are disabled
  after explicit provisioning.
* Offline or incompatible extension installation fails before task dispatch.
* Preflight proves Docker socket access, digest-pinned image pull, disposable
  container run, and sufficient workspace/image/volume disk.
* The receipt binds Python, platform, lockfile, DuckDB, Quack, DuckLake,
  provider binaries, repository tree, and creation command.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CREATE_SCRIPT = REPO_ROOT / "scripts/ops/create_duckdb_quack_env.py"
LOCK_PATH = REPO_ROOT / "requirements/duckdb-quack.lock"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "create_duckdb_quack_env",
        CREATE_SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _write_bytes(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _synthetic_lock(
    path: Path,
    *,
    quack_arm: bytes = b"quack-arm64-artifact",
    quack_amd: bytes = b"quack-amd64-artifact",
    ducklake_arm: bytes = b"ducklake-arm64-artifact",
    ducklake_amd: bytes = b"ducklake-amd64-artifact",
    httpfs_arm: bytes = b"httpfs-arm64-artifact",
    httpfs_amd: bytes = b"httpfs-amd64-artifact",
    duckdb_hash_a: str = "a" * 64,
    duckdb_hash_b: str = "b" * 64,
    workspace_bytes: int = 1024,
    image_bytes: int = 1024,
    volume_bytes: int = 1024,
    docker_digest: str = "c" * 64,
) -> dict[str, str]:
    digests = {
        "quack_linux_arm64": f"sha256:{hashlib.sha256(quack_arm).hexdigest()}",
        "quack_linux_amd64": f"sha256:{hashlib.sha256(quack_amd).hexdigest()}",
        "ducklake_linux_arm64": f"sha256:{hashlib.sha256(ducklake_arm).hexdigest()}",
        "ducklake_linux_amd64": f"sha256:{hashlib.sha256(ducklake_amd).hexdigest()}",
        "httpfs_linux_arm64": f"sha256:{hashlib.sha256(httpfs_arm).hexdigest()}",
        "httpfs_linux_amd64": f"sha256:{hashlib.sha256(httpfs_amd).hexdigest()}",
    }
    body = textwrap.dedent(
        f"""\
        # ipfs_datasets_py/duckdb-quack-environment-lock@1
        #
        # POLICY
        # duckdb_version=1.5.5
        # python_package=duckdb
        # requires_hashes=true
        # binary_only=true
        # dependencies_disabled=true
        # autoinstall_known_extensions=false
        # autoload_known_extensions=false
        # ducklake_automatic_migration=false
        # attestation_scope=candidate-duckdb-quack-ducklake-runtime
        #
        # EXTENSION_PROFILE quack
        # name=quack
        # version=1.5.5
        # source=core
        # build=quack@1.5.5+core
        # load_order=2
        # repository=http://extensions.duckdb.org
        # artifact linux_arm64 {digests['quack_linux_arm64']} filename=quack.duckdb_extension
        # artifact linux_amd64 {digests['quack_linux_amd64']} filename=quack.duckdb_extension
        #
        # EXTENSION_PROFILE ducklake
        # name=ducklake
        # version=1.5.5
        # source=core
        # build=ducklake@1.5.5+core
        # load_order=3
        # repository=http://extensions.duckdb.org
        # artifact linux_arm64 {digests['ducklake_linux_arm64']} filename=ducklake.duckdb_extension
        # artifact linux_amd64 {digests['ducklake_linux_amd64']} filename=ducklake.duckdb_extension
        #
        # EXTENSION_PROFILE httpfs
        # name=httpfs
        # version=1.5.5
        # source=core
        # build=httpfs@1.5.5+core
        # load_order=1
        # repository=http://extensions.duckdb.org
        # artifact linux_arm64 {digests['httpfs_linux_arm64']} filename=httpfs.duckdb_extension
        # artifact linux_amd64 {digests['httpfs_linux_amd64']} filename=httpfs.duckdb_extension
        #
        # DOCKER_IMAGE probe alpine@sha256:{docker_digest}
        #
        # DISK_MINIMA
        # workspace_bytes={workspace_bytes}
        # image_bytes={image_bytes}
        # volume_bytes={volume_bytes}
        #
        # --- pip requirements ---
        duckdb==1.5.5 \\
            --hash=sha256:{duckdb_hash_a} \\
            --hash=sha256:{duckdb_hash_b}
        """
    )
    path.write_text(body, encoding="utf-8")
    digests["lock_sha256"] = mod.sha256_file(path)
    digests["payloads"] = {
        "quack_arm": quack_arm,
        "quack_amd": quack_amd,
        "ducklake_arm": ducklake_arm,
        "ducklake_amd": ducklake_amd,
        "httpfs_arm": httpfs_arm,
        "httpfs_amd": httpfs_amd,
    }
    return digests


def _stage_extensions(extension_root: Path, lock: Any, plat: str, digests: dict[str, Any]) -> None:
    version_dir = extension_root / "v1.5.5" / plat
    version_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        "quack": digests["payloads"]["quack_arm" if plat == "linux_arm64" else "quack_amd"],
        "ducklake": digests["payloads"][
            "ducklake_arm" if plat == "linux_arm64" else "ducklake_amd"
        ],
        "httpfs": digests["payloads"][
            "httpfs_arm" if plat == "linux_arm64" else "httpfs_amd"
        ],
    }
    for profile in lock.ordered_profiles():
        art = profile.artifact_for(plat)
        (version_dir / art.filename).write_bytes(mapping[profile.name])


def _fake_docker_preflight(images, **_kwargs):
    return {
        "ok": True,
        "socket": "/var/run/docker.sock",
        "server_version": "test",
        "images": [
            {"role": img.role, "reference": img.reference, "digest": img.digest}
            for img in images
        ],
        "probe": {
            "ran": True,
            "image": images[0].reference,
            "name": "dqk-082-probe-test",
            "command": ["true"],
            "exit_code": 0,
        },
    }


def _fake_disk_preflight(**kwargs):
    minima = kwargs["minima"]
    return {
        "ok": True,
        "checks": {
            "workspace": {
                "path": str(kwargs["workspace_path"]),
                "free_bytes": minima.workspace_bytes + 1,
                "required_bytes": minima.workspace_bytes,
                "ok": True,
            },
            "image": {
                "path": "/var/lib/docker/image",
                "free_bytes": minima.image_bytes + 1,
                "required_bytes": minima.image_bytes,
                "ok": True,
            },
            "volume": {
                "path": "/var/lib/docker/volumes",
                "free_bytes": minima.volume_bytes + 1,
                "required_bytes": minima.volume_bytes,
                "ok": True,
            },
        },
    }


# ---------------------------------------------------------------------------
# Checked-in lock policy
# ---------------------------------------------------------------------------


class TestCheckedInLockPolicy:
    def test_lock_file_exists_and_declares_schema(self) -> None:
        assert LOCK_PATH.is_file()
        text = LOCK_PATH.read_text(encoding="utf-8")
        assert text.splitlines()[0].endswith(
            "ipfs_datasets_py/duckdb-quack-environment-lock@1"
        )

    def test_lock_pins_duckdb_155_and_extension_checksums(self) -> None:
        lock = mod.load_lock_policy(LOCK_PATH)
        assert lock.duckdb_version == "1.5.5"
        assert "duckdb==1.5.5" in lock.pip_requirement_text
        assert len(lock.package_hashes) == 2
        quack = lock.profile("quack")
        ducklake = lock.profile("ducklake")
        httpfs = lock.profile("httpfs")
        assert quack.build == "quack@1.5.5+core"
        assert ducklake.build == "ducklake@1.5.5+core"
        assert httpfs.build == "httpfs@1.5.5+core"
        for profile in (quack, ducklake, httpfs):
            for plat in ("linux_arm64", "linux_amd64"):
                art = profile.artifact_for(plat)
                assert art.sha256.startswith("sha256:")
                assert len(art.sha256) == len("sha256:") + 64
        # Real measured aarch64 quack digest from DQK-082 provisioning research.
        assert (
            quack.artifact_for("linux_arm64").sha256
            == "sha256:41b2b9292bfb860c5ca8c5f818f9dd7a2c6bc24f9c750cffbc3169286fe59f08"
        )
        assert (
            ducklake.artifact_for("linux_arm64").sha256
            == "sha256:d0b57c8e261b89a1ae367c7224f0857cfde72ab6cf2609f188e0de9b897b1088"
        )

    def test_lock_disables_automatic_install_load_and_migration(self) -> None:
        lock = mod.load_lock_policy(LOCK_PATH)
        assert lock.autoinstall_known_extensions is False
        assert lock.autoload_known_extensions is False
        assert lock.ducklake_automatic_migration is False

    def test_lock_pins_digest_docker_image_and_disk_minima(self) -> None:
        lock = mod.load_lock_policy(LOCK_PATH)
        assert lock.docker_images
        for image in lock.docker_images:
            assert "@sha256:" in image.reference
            assert image.digest.startswith("sha256:")
        assert lock.disk_minima.workspace_bytes >= 1
        assert lock.disk_minima.image_bytes >= 1
        assert lock.disk_minima.volume_bytes >= 1

    def test_extension_load_order_is_explicit(self) -> None:
        lock = mod.load_lock_policy(LOCK_PATH)
        ordered = [p.name for p in lock.ordered_profiles()]
        assert ordered == ["httpfs", "quack", "ducklake"]


class TestLockParsingFailures:
    def test_rejects_missing_extension_profile(self, tmp_path: Path) -> None:
        digests = _synthetic_lock(tmp_path / "lock.lock")
        text = (tmp_path / "lock.lock").read_text(encoding="utf-8")
        # Drop ducklake profile block.
        lines = []
        skip = False
        for line in text.splitlines():
            if "EXTENSION_PROFILE ducklake" in line:
                skip = True
                continue
            if skip and line.startswith("# EXTENSION_PROFILE"):
                skip = False
            if skip and (
                line.startswith("# name=")
                or line.startswith("# version=")
                or line.startswith("# source=")
                or line.startswith("# build=")
                or line.startswith("# load_order=")
                or line.startswith("# repository=")
                or line.startswith("# artifact")
            ):
                continue
            if skip and line.strip() == "#":
                continue
            if skip and "EXTENSION_PROFILE" not in line and line.startswith("# DOCKER"):
                skip = False
            lines.append(line)
        broken = tmp_path / "broken.lock"
        broken.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(mod.LockfileError, match="ducklake"):
            mod.load_lock_policy(broken)
        del digests

    def test_rejects_mutable_docker_tag(self, tmp_path: Path) -> None:
        path = tmp_path / "lock.lock"
        _synthetic_lock(path)
        text = path.read_text(encoding="utf-8").replace(
            "alpine@sha256:" + "c" * 64,
            "alpine:latest",
        )
        path.write_text(text, encoding="utf-8")
        with pytest.raises(mod.LockfileError):
            mod.load_lock_policy(path)

    def test_rejects_wrong_duckdb_version_policy(self, tmp_path: Path) -> None:
        path = tmp_path / "lock.lock"
        _synthetic_lock(path)
        text = path.read_text(encoding="utf-8").replace(
            "duckdb_version=1.5.5",
            "duckdb_version=1.5.4",
        )
        path.write_text(text, encoding="utf-8")
        with pytest.raises(mod.LockfileError, match="duckdb_version"):
            mod.load_lock_policy(path)


# ---------------------------------------------------------------------------
# Isolation and non-mutation of supervisor generation
# ---------------------------------------------------------------------------


class TestIsolationAndNonMutation:
    def test_candidate_root_differs_from_supervisor_root(self, tmp_path: Path) -> None:
        supervisor = tmp_path / "supervisor"
        candidate = tmp_path / "candidate"
        supervisor.mkdir()
        candidate.mkdir()
        mod.assert_no_supervisor_generation_mutation(
            candidate_root=candidate,
            supervisor_root=supervisor,
        )
        with pytest.raises(mod.EnvironmentProvisionError, match="collides"):
            mod.assert_no_supervisor_generation_mutation(
                candidate_root=supervisor,
                supervisor_root=supervisor,
            )

    def test_refuses_nested_candidate_under_supervisor(self, tmp_path: Path) -> None:
        supervisor = tmp_path / "supervisor"
        nested = supervisor / "nested"
        supervisor.mkdir()
        nested.mkdir()
        with pytest.raises(mod.EnvironmentProvisionError, match="nested"):
            mod.assert_no_supervisor_generation_mutation(
                candidate_root=nested,
                supervisor_root=supervisor,
            )

    def test_refuses_generation_marker_paths(self, tmp_path: Path) -> None:
        supervisor = tmp_path / "supervisor"
        candidate = tmp_path / "candidate"
        supervisor.mkdir()
        candidate.mkdir()
        marker = tmp_path / "state" / "lane-0" / "control.duckdb"
        marker.parent.mkdir(parents=True)
        marker.write_text("x", encoding="utf-8")
        with pytest.raises(mod.EnvironmentProvisionError, match="generation path"):
            mod.assert_no_supervisor_generation_mutation(
                candidate_root=candidate,
                supervisor_root=supervisor,
                mutated_paths=(marker,),
            )

    def test_defaults_do_not_share_env_name(self) -> None:
        assert mod.CANDIDATE_ENV_NAME != mod.SUPERVISOR_ENV_NAME
        assert "candidate" in mod.CANDIDATE_ENV_NAME


# ---------------------------------------------------------------------------
# Extension provisioning fail-closed behaviour
# ---------------------------------------------------------------------------


class TestExtensionProvisioning:
    def test_offline_missing_artifact_fails_before_dispatch(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "lock.lock"
        digests = _synthetic_lock(lock_path)
        lock = mod.load_lock_policy(lock_path)
        extension_root = tmp_path / "extensions"
        with pytest.raises(mod.EnvironmentProvisionError, match="offline|missing"):
            mod.provision_extension_profiles(
                python=Path(sys.executable),
                lock=lock,
                extension_root=extension_root,
                platform_name="linux_arm64",
                allow_network_install=False,
                duckdb_module=object(),  # force offline staged-artifact path
            )
        del digests

    def test_incompatible_checksum_fails_before_dispatch(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "lock.lock"
        digests = _synthetic_lock(lock_path)
        lock = mod.load_lock_policy(lock_path)
        extension_root = tmp_path / "extensions"
        _stage_extensions(extension_root, lock, "linux_arm64", digests)
        # Corrupt quack artifact after staging.
        target = extension_root / "v1.5.5" / "linux_arm64" / "quack.duckdb_extension"
        target.write_bytes(b"tampered-bytes")
        with pytest.raises(mod.EnvironmentProvisionError, match="checksum|incompatible"):
            mod.provision_extension_profiles(
                python=Path(sys.executable),
                lock=lock,
                extension_root=extension_root,
                platform_name="linux_arm64",
                allow_network_install=False,
                duckdb_module=object(),
            )

    def test_staged_artifacts_verify_and_report_hardening(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "lock.lock"
        digests = _synthetic_lock(lock_path)
        lock = mod.load_lock_policy(lock_path)
        extension_root = tmp_path / "extensions"
        _stage_extensions(extension_root, lock, "linux_arm64", digests)
        result = mod.provision_extension_profiles(
            python=Path(sys.executable),
            lock=lock,
            extension_root=extension_root,
            platform_name="linux_arm64",
            allow_network_install=False,
            duckdb_module=object(),
        )
        assert result["duckdb_version"] == "1.5.5"
        assert result["autoinstall_known_extensions"] == "false"
        assert result["autoload_known_extensions"] == "false"
        assert result["ducklake_automatic_migration"] is False
        names = [row["name"] for row in result["extensions"]]
        assert names == ["httpfs", "quack", "ducklake"]
        for row in result["extensions"]:
            assert row["sha256"].startswith("sha256:")
            assert row["loaded"] is True


# ---------------------------------------------------------------------------
# Receipt binding
# ---------------------------------------------------------------------------


class TestCandidateReceipt:
    def _sample_receipt(self, tmp_path: Path) -> tuple[dict[str, Any], Any]:
        lock_path = tmp_path / "requirements" / "duckdb-quack.lock"
        lock_path.parent.mkdir(parents=True)
        digests = _synthetic_lock(lock_path)
        lock = mod.load_lock_policy(lock_path)
        env_root = tmp_path / "candidate"
        env_root.mkdir()
        supervisor = tmp_path / "supervisor"
        supervisor.mkdir()
        extension_root = env_root / "extension-profiles"
        _stage_extensions(extension_root, lock, "linux_arm64", digests)
        extensions = mod.provision_extension_profiles(
            python=Path(sys.executable),
            lock=lock,
            extension_root=extension_root,
            platform_name="linux_arm64",
            duckdb_module=object(),
        )
        host = {
            "python_version": "3.12.3",
            "python_implementation": "CPython",
            "system": "Linux",
            "machine": "aarch64",
            "platform_key": "linux_arm64",
            "sysconfig_platform": "linux-aarch64",
        }
        repository = {
            "repository_root": str(tmp_path),
            "commit": "1" * 40,
            "tree": "2" * 40,
            "lock_relative_path": "requirements/duckdb-quack.lock",
            "lock_sha256": lock.sha256,
        }
        docker = _fake_docker_preflight(lock.docker_images)
        disk = _fake_disk_preflight(
            workspace_path=env_root.parent,
            image_path=None,
            volume_path=None,
            minima=lock.disk_minima,
        )
        receipt = mod.build_candidate_receipt(
            lock=lock,
            env_root=env_root,
            host=host,
            repository=repository,
            docker=docker,
            disk=disk,
            pip_install={
                "wheel_path": str(env_root / "pip-artifacts" / "duckdb.whl"),
                "wheel_sha256": "sha256:" + "d" * 64,
            },
            extensions=extensions,
            providers=[
                {
                    "name": "python3",
                    "present": True,
                    "path": sys.executable,
                    "sha256": "sha256:" + "e" * 64,
                }
            ],
            creation_command=[
                sys.executable,
                str(CREATE_SCRIPT),
                "create",
                "--lock",
                str(lock_path),
            ],
            supervisor_env_root=supervisor,
            hardening={
                "autoinstall_known_extensions": "false",
                "autoload_known_extensions": "false",
                "duckdb_version": "1.5.5",
            },
        )
        return receipt, lock

    def test_receipt_is_content_bound_and_complete(self, tmp_path: Path) -> None:
        receipt, lock = self._sample_receipt(tmp_path)
        valid, detail = mod.validate_candidate_receipt(receipt, lock=lock)
        assert valid, detail
        assert receipt["receipt_id"].startswith("receipt:sha256:")
        # Required bindings.
        assert receipt["python"]["version"]
        assert receipt["platform"]["machine"]
        assert receipt["lockfile"]["sha256"] == lock.sha256
        assert receipt["duckdb"]["version"] == "1.5.5"
        assert receipt["quack"]["build"] == "quack@1.5.5+core"
        assert receipt["ducklake"]["build"] == "ducklake@1.5.5+core"
        assert receipt["provider_binaries"]
        assert receipt["repository"]["tree"] == "2" * 40
        assert receipt["creation_command"]
        assert receipt["isolated_from_supervisor"] is True
        assert receipt["generation_mutation"] == {
            "master_changed": False,
            "lane_changed": False,
            "daemon_changed": False,
            "writer_generation_changed": False,
        }
        assert receipt["hardening"]["autoinstall_known_extensions"] is False
        assert receipt["hardening"]["autoload_known_extensions"] is False
        assert receipt["hardening"]["ducklake_automatic_migration"] is False

    def test_receipt_rejects_forged_id(self, tmp_path: Path) -> None:
        receipt, lock = self._sample_receipt(tmp_path)
        receipt["receipt_id"] = "receipt:sha256:" + "0" * 64
        valid, detail = mod.validate_candidate_receipt(receipt, lock=lock)
        assert not valid
        assert "content-bound" in detail

    def test_receipt_rejects_generation_mutation_claim(self, tmp_path: Path) -> None:
        receipt, lock = self._sample_receipt(tmp_path)
        # Rebuild with mutation claim by patching then recomputing id incorrectly.
        receipt["generation_mutation"]["master_changed"] = True
        # Even with recomputed id, validation must reject mutation claims.
        receipt["receipt_id"] = mod.content_receipt_id(receipt)
        valid, detail = mod.validate_candidate_receipt(receipt, lock=lock)
        assert not valid
        assert "mutation" in detail


# ---------------------------------------------------------------------------
# Disk / docker preflight units
# ---------------------------------------------------------------------------


class TestPreflight:
    def test_disk_capacity_fails_when_insufficient(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        minima = mod.DiskMinima(workspace_bytes=10**18, image_bytes=1, volume_bytes=1)

        def tiny_free(_path: Path) -> int:
            return 100

        monkeypatch.setattr(mod, "_statvfs_free_bytes", tiny_free)
        with pytest.raises(mod.DockerPreflightError, match="insufficient disk"):
            mod.disk_capacity_preflight(
                workspace_path=tmp_path,
                image_path=tmp_path,
                volume_path=tmp_path,
                minima=minima,
            )

    def test_disk_capacity_passes_with_sufficient_space(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        minima = mod.DiskMinima(workspace_bytes=10, image_bytes=10, volume_bytes=10)
        monkeypatch.setattr(mod, "_statvfs_free_bytes", lambda _p: 1000)
        result = mod.disk_capacity_preflight(
            workspace_path=tmp_path,
            image_path=tmp_path,
            volume_path=tmp_path,
            minima=minima,
        )
        assert result["ok"] is True
        assert result["checks"]["workspace"]["ok"] is True

    def test_docker_preflight_requires_socket(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mod, "_docker_socket_accessible", lambda: (False, "missing"))
        with pytest.raises(mod.DockerPreflightError, match="missing"):
            mod.docker_preflight(
                [mod.DockerImagePin(role="probe", reference="alpine@sha256:" + "a" * 64)],
                pull=False,
                run_probe=False,
            )

    def test_docker_preflight_pull_and_probe(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, ...]] = []

        def fake_docker(*args, **kwargs):
            calls.append(args)
            if args[:1] == ("info",) or (args and args[0] == "info"):
                return SimpleNamespace(returncode=0, stdout="29.0\n", stderr="")
            if args[:1] == ("pull",) or (args and args[0] == "pull"):
                return SimpleNamespace(returncode=0, stdout="pulled\n", stderr="")
            if args[:2] == ("image", "inspect"):
                return SimpleNamespace(
                    returncode=0,
                    stdout='["alpine@sha256:' + "a" * 64 + '"]\n',
                    stderr="",
                )
            if args[:1] == ("rm",) or (args and args[0] == "rm"):
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if args[:1] == ("run",) or (args and args[0] == "run"):
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(mod, "_docker_socket_accessible", lambda: (True, "/var/run/docker.sock"))
        monkeypatch.setattr(mod, "_docker", fake_docker)
        image = mod.DockerImagePin(
            role="probe",
            reference="alpine@sha256:" + "a" * 64,
        )
        result = mod.docker_preflight([image], pull=True, run_probe=True)
        assert result["ok"] is True
        assert result["probe"]["ran"] is True
        assert any(call and call[0] == "pull" for call in calls)
        assert any(call and call[0] == "run" for call in calls)

    def test_docker_preflight_rejects_mutable_tag(self) -> None:
        # DockerImagePin.digest property requires @sha256.
        with pytest.raises(mod.EnvironmentProvisionError):
            mod.DockerImagePin(role="probe", reference="alpine:latest").digest


# ---------------------------------------------------------------------------
# Create path with heavy mocking (no real pip/docker)
# ---------------------------------------------------------------------------


class TestCreateCandidateEnvironment:
    def test_create_is_isolated_idempotent_and_receipted(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Candidate/supervisor roots must sit *outside* the repository root:
        # the provisioner refuses environments nested under the checkout.
        repo = tmp_path / "repo"
        repo.mkdir()
        lock_path = repo / "requirements" / "duckdb-quack.lock"
        lock_path.parent.mkdir(parents=True)
        digests = _synthetic_lock(lock_path)
        lock = mod.load_lock_policy(lock_path)
        env_root = tmp_path / "venvs" / "candidate"
        supervisor = tmp_path / "venvs" / "supervisor"
        supervisor.mkdir(parents=True)
        receipt_path = env_root / "candidate-environment-receipt.json"

        # Pretend we are on a supported host.
        monkeypatch.setattr(mod, "_assert_supported_host", lambda: {
            "python_version": "3.12.3",
            "python_implementation": "CPython",
            "system": "Linux",
            "machine": "aarch64",
            "platform_key": "linux_arm64",
            "sysconfig_platform": "linux-aarch64",
        })
        monkeypatch.setattr(mod, "repo_root", lambda: repo)

        def fake_install(*, env_root, lock, python):
            artifact = Path(env_root) / "pip-artifacts"
            artifact.mkdir(parents=True, exist_ok=True)
            wheel = artifact / "duckdb-1.5.5-fake.whl"
            wheel.write_bytes(b"fake-wheel")
            # Force admitted hash by writing a matching hash into a side channel:
            # the install function checks wheel digest against lock.package_hashes.
            # Patch package membership via monkeypatched install return instead.
            return {
                "artifact_root": str(artifact),
                "wheel_path": str(wheel),
                "wheel_sha256": sorted(lock.package_hashes)[0],
                "pip_install_report_path": "",
                "pip_install_report_sha256": "",
            }

        real_provision = mod.provision_extension_profiles

        def fake_provision(*, python, lock, extension_root, **kwargs):
            plat = "linux_arm64"
            root = Path(extension_root)
            _stage_extensions(root, lock, plat, digests)
            return real_provision(
                python=python,
                lock=lock,
                extension_root=root,
                platform_name=plat,
                duckdb_module=object(),
            )

        def fake_hardening(**_kwargs):
            return {
                "autoinstall_known_extensions": "false",
                "autoload_known_extensions": "false",
                "duckdb_version": "1.5.5",
            }

        def fake_repo_evidence(root, lock_file):
            return {
                "repository_root": str(root),
                "commit": "1" * 40,
                "tree": "2" * 40,
                "lock_relative_path": "requirements/duckdb-quack.lock",
                "lock_sha256": mod.sha256_file(lock_file),
            }

        # EnvBuilder.create should produce bin/python
        class FakeBuilder:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def create(self, path):
                root = Path(path)
                (root / "bin").mkdir(parents=True, exist_ok=True)
                (root / "bin" / "python").write_bytes(b"#!/fake\n")
                os.chmod(root / "bin" / "python", 0o755)

        monkeypatch.setattr(mod.venv, "EnvBuilder", FakeBuilder)
        monkeypatch.setattr(mod, "_install_duckdb_from_lock", fake_install)
        monkeypatch.setattr(mod, "provision_extension_profiles", fake_provision)
        monkeypatch.setattr(mod, "verify_post_provision_hardening", fake_hardening)
        monkeypatch.setattr(mod, "repository_evidence", fake_repo_evidence)
        monkeypatch.setattr(
            mod,
            "provider_binary_evidence",
            lambda: [
                {
                    "name": "python3",
                    "present": True,
                    "path": "/usr/bin/python3",
                    "sha256": "sha256:" + "f" * 64,
                }
            ],
        )

        result = mod.create_candidate_environment(
            lock_path=lock_path,
            env_root=env_root,
            receipt_path=receipt_path,
            supervisor_env_root=supervisor,
            repository_root=repo,
            docker_preflight_fn=_fake_docker_preflight,
            disk_preflight_fn=_fake_disk_preflight,
        )
        assert result["status"] == "created"
        assert result["dqk_082_completed"] is True
        assert result["generation_mutation"] == {
            "master_changed": False,
            "lane_changed": False,
            "daemon_changed": False,
            "writer_generation_changed": False,
        }
        assert receipt_path.is_file()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        valid, detail = mod.validate_candidate_receipt(receipt, lock=lock)
        assert valid, detail
        assert receipt["environment_root"] == str(env_root.resolve())
        assert receipt["supervisor_environment_root"] == str(supervisor.resolve())
        assert receipt["isolated_from_supervisor"] is True
        assert receipt["duckdb"]["version"] == "1.5.5"
        assert receipt["docker_preflight"]["probe"]["ran"] is True
        assert receipt["disk_preflight"]["ok"] is True
        assert "create" in receipt["creation_command"]

        # Idempotent re-entry must not recreate.
        def boom_builder(**_kwargs):
            raise AssertionError("must not recreate valid candidate env")

        monkeypatch.setattr(mod.venv, "EnvBuilder", boom_builder)
        again = mod.create_candidate_environment(
            lock_path=lock_path,
            env_root=env_root,
            receipt_path=receipt_path,
            supervisor_env_root=supervisor,
            repository_root=repo,
            docker_preflight_fn=_fake_docker_preflight,
            disk_preflight_fn=_fake_disk_preflight,
        )
        assert again["status"] == "already-valid"
        assert again["receipt_id"] == result["receipt_id"]

    def test_create_refuses_supervisor_root_collision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lock_path = tmp_path / "lock.lock"
        _synthetic_lock(lock_path)
        shared = tmp_path / "shared"
        shared.mkdir()
        monkeypatch.setattr(mod, "_assert_supported_host", lambda: {
            "python_version": "3.12.3",
            "python_implementation": "CPython",
            "system": "Linux",
            "machine": "aarch64",
            "platform_key": "linux_arm64",
            "sysconfig_platform": "linux-aarch64",
        })
        with pytest.raises(mod.EnvironmentProvisionError, match="collides|supervisor"):
            mod.create_candidate_environment(
                lock_path=lock_path,
                env_root=shared,
                supervisor_env_root=shared,
                repository_root=tmp_path,
                docker_preflight_fn=_fake_docker_preflight,
                disk_preflight_fn=_fake_disk_preflight,
            )


# ---------------------------------------------------------------------------
# Script surface
# ---------------------------------------------------------------------------


class TestScriptSurface:
    def test_module_is_import_side_effect_free(self) -> None:
        # Reloading should not create directories or touch docker.
        _load_module()

    def test_cli_show_lock_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = mod.main(["show-lock", "--lock", str(LOCK_PATH), "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["duckdb_version"] == "1.5.5"
        assert {p["name"] for p in payload["extension_profiles"]} >= {
            "quack",
            "ducklake",
            "httpfs",
        }

    def test_expected_outputs_exist(self) -> None:
        assert LOCK_PATH.is_file()
        assert CREATE_SCRIPT.is_file()
        assert Path(__file__).is_file()

    def test_create_script_documents_non_activation(self) -> None:
        text = CREATE_SCRIPT.read_text(encoding="utf-8")
        assert "DQK-103" in text
        assert "does not activate" in text.lower() or "not activate" in text.lower()
        assert "autoinstall" in text
        assert "AUTOMATIC_MIGRATION" in text or "automatic_migration" in text


# ---------------------------------------------------------------------------
# Optional live docker smoke (skipped when docker unavailable)
# ---------------------------------------------------------------------------


class TestLiveDockerSmoke:
    def test_live_docker_preflight_when_available(self) -> None:
        socket_ok, _detail = mod._docker_socket_accessible()
        if not socket_ok:
            pytest.skip("docker socket not available")
        lock = mod.load_lock_policy(LOCK_PATH)
        try:
            result = mod.docker_preflight(lock.docker_images, pull=True, run_probe=True)
        except mod.DockerPreflightError as exc:
            pytest.skip(f"docker preflight unavailable in this environment: {exc}")
        assert result["ok"] is True
        assert result["probe"]["ran"] is True
        assert result["images"]
        for image in result["images"]:
            assert "@sha256:" in image["reference"]
