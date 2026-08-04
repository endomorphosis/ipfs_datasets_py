"""Unit gates for optional ErgoAI Java API Temurin JDK lazy lifecycle (FVT-090)."""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
import textwrap
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.backends.installers import advisors
from ipfs_datasets_py.logic.external_provers import lazy_installer


TOOL_ID = "temurin-jdk"
LOCKED_VERSION = advisors.TEMURIN_JDK_VERSION


def _write_executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_jdk_home(root: Path, *, version: str = "17.0.20") -> Path:
    home = root / f"jdk-{version}+8"
    bin_dir = home / "bin"
    bin_dir.mkdir(parents=True)
    _write_executable(
        bin_dir / "java",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            echo 'openjdk version "{version}" 2026-01-01'
            exit 0
            """
        ),
    )
    _write_executable(
        bin_dir / "javac",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            if [[ "${{1:-}}" == "-version" || "${{1:-}}" == "--version" ]]; then
              echo 'javac {version}'
              exit 0
            fi
            echo 'error: malformed' >&2
            exit 1
            """
        ),
    )
    _write_executable(
        bin_dir / "jar",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            echo 'jar {version}'
            exit 0
            """
        ),
    )
    return home


def _tarball(archive: Path, jdk_home: Path) -> tuple[str, int]:
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(jdk_home, arcname=jdk_home.name)
    data = archive.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def test_aliases_normalize_to_temurin_jdk() -> None:
    for name in (
        "temurin-jdk",
        "temurin_jdk",
        "jdk",
        "openjdk",
        "ergoai-java-api",
        "ergoai_java_api",
        "java_api",
    ):
        assert lazy_installer.normalize_prover_name(name) == "temurin-jdk"


def test_plan_and_denial_never_mutate(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real_import = lazy_installer.importlib.import_module

    def guarded(name: str, *args, **kwargs):
        if "installers.advisors" in name:
            calls.append(name)
            raise AssertionError("planning must not import advisors")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(lazy_installer.importlib, "import_module", guarded)
    plan = lazy_installer.plan_reviewed_install("jdk")
    assert plan["provider_id"] == "temurin-jdk"
    assert plan["installer_callable"] == "ensure_temurin_jdk"
    assert plan["requires_explicit_yes"] is True
    assert plan["never_trust_ambient_java_home"] is True
    assert calls == []

    denied = lazy_installer.execute_reviewed_install("temurin-jdk")
    assert denied["status"] == "authorization_required"
    assert denied["install_attempted"] is False

    dry = lazy_installer.execute_reviewed_install("temurin-jdk", dry_run=True)
    assert dry["status"] == "planned"
    assert dry["install_attempted"] is False

    offline = lazy_installer.execute_reviewed_install(
        "temurin-jdk",
        allow_install=True,
        offline=True,
    )
    assert offline["status"] == "blocked"
    assert offline["install_attempted"] is False


def test_authorize_rejects_import_and_offline() -> None:
    with pytest.raises(advisors.AdvisorInstallerError, match="import"):
        advisors.authorize_temurin_jdk_install(
            yes=True,
            import_context=True,
            platform_key="linux-x86_64",
        )
    with pytest.raises(advisors.AdvisorInstallerError, match="capability"):
        advisors.authorize_temurin_jdk_install(
            yes=True,
            capability_discovery=True,
            platform_key="linux-x86_64",
        )
    with pytest.raises(advisors.AdvisorInstallerError, match="offline|forbidden"):
        advisors.authorize_temurin_jdk_install(
            yes=True,
            offline=True,
            platform_key="linux-x86_64",
        )
    with pytest.raises(advisors.AdvisorInstallerError, match="yes"):
        advisors.authorize_temurin_jdk_install(
            yes=False,
            platform_key="linux-x86_64",
        )


def test_archive_traversal_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        info = tarfile.TarInfo(name="../escape/bin/java")
        payload = b"#!/bin/sh\n"
        info.size = len(payload)
        handle.addfile(info, fileobj=__import__("io").BytesIO(payload))
    with pytest.raises(advisors.AdvisorInstallerError, match="traversal|escapes|unsafe"):
        advisors._safe_extract_temurin_archive(archive, tmp_path / "out")


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "link.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        info = tarfile.TarInfo(name="jdk/bin/java")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        handle.addfile(info)
    with pytest.raises(advisors.AdvisorInstallerError, match="symlink|escapes|unsupported"):
        advisors._safe_extract_temurin_archive(archive, tmp_path / "out")


def test_ensure_installs_from_artifact_and_rolls_back_on_probe_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform_key = "linux-x86_64"
    root = tmp_path / "install"
    home = _fake_jdk_home(tmp_path / "src")
    archive = tmp_path / "OpenJDK17U-jdk_x64_linux_hotspot_17.0.20_8.tar.gz"
    digest, size = _tarball(archive, home)

    pin = advisors.select_strict_pin(
        TOOL_ID,
        platform_key=platform_key,
        allow_source_fallback=False,
    )
    monkeypatch.setitem(
        advisors.TEMURIN_JDK_PINS,
        platform_key,
        {
            **advisors.TEMURIN_JDK_PINS[platform_key],
            "sha256": digest,
            "artifact_size_bytes": size,
        },
    )
    monkeypatch.setattr(
        advisors,
        "select_strict_pin",
        lambda *args, **kwargs: advisors.ToolPin(
            tool_id=pin.tool_id,
            version=pin.version,
            platform=platform_key,
            artifact_url=pin.artifact_url,
            sha256=digest,
            identity_kind=pin.identity_kind,
            license=pin.license,
            source=pin.source,
            is_checksummed=True,
            requires_checksum_at_install=True,
            release_tag=pin.release_tag,
            artifact_size_bytes=size,
        ),
    )

    receipt = advisors.ensure_temurin_jdk(
        yes=True,
        strict=False,
        install_root=root,
        platform_key=platform_key,
        artifact_path=archive,
    )
    assert receipt.ok, receipt.to_dict()
    assert receipt.checksum_verified is True
    java = Path(receipt.executable_path or "")
    assert java.is_file()
    identity = root / "advisors" / TOOL_ID / LOCKED_VERSION / "identity.json"
    assert identity.is_file()
    manifest = json.loads(identity.read_text(encoding="utf-8"))
    assert manifest["ambient_java_home_trusted"] is False
    assert manifest["version"] == LOCKED_VERSION
    assert set(manifest["required_tool_identities"]) == {"java", "javac", "jar"}

    probe = advisors.probe_temurin_jdk_identity(install_root=root)
    assert probe["satisfied"] is True

    # Replay path is available without re-download.
    monkeypatch.setattr(
        advisors,
        "_copy_or_download_ergoai_artifact",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no redownload")),
    )
    again = advisors.ensure_temurin_jdk(
        yes=True,
        strict=False,
        install_root=root,
        platform_key=platform_key,
    )
    assert again.status == "available"
    assert again.already_present is True


def test_post_install_probe_failure_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform_key = "linux-x86_64"
    root = tmp_path / "install"
    home = _fake_jdk_home(tmp_path / "src")
    # Remove jar so post-install probe fails.
    (home / "bin" / "jar").unlink()
    archive = tmp_path / "bad.tgz"
    digest, size = _tarball(archive, home)
    pin = advisors.select_strict_pin(
        TOOL_ID,
        platform_key=platform_key,
        allow_source_fallback=False,
    )
    monkeypatch.setitem(
        advisors.TEMURIN_JDK_PINS,
        platform_key,
        {
            **advisors.TEMURIN_JDK_PINS[platform_key],
            "sha256": digest,
            "artifact_size_bytes": size,
        },
    )
    monkeypatch.setattr(
        advisors,
        "select_strict_pin",
        lambda *args, **kwargs: advisors.ToolPin(
            tool_id=pin.tool_id,
            version=pin.version,
            platform=platform_key,
            artifact_url=pin.artifact_url,
            sha256=digest,
            identity_kind=pin.identity_kind,
            license=pin.license,
            source=pin.source,
            is_checksummed=True,
            requires_checksum_at_install=True,
            release_tag=pin.release_tag,
            artifact_size_bytes=size,
        ),
    )
    receipt = advisors.ensure_temurin_jdk(
        yes=True,
        strict=False,
        install_root=root,
        platform_key=platform_key,
        artifact_path=archive,
    )
    assert receipt.status == "failed"
    assert "post_install_probe_failed" in receipt.reason_codes or "install_failed" in receipt.reason_codes
    assert not (root / "advisors" / TOOL_ID / LOCKED_VERSION).exists()


def test_ambient_java_home_never_satisfies_managed_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambient = tmp_path / "ambient-jdk"
    _fake_jdk_home(ambient)
    monkeypatch.setenv("JAVA_HOME", str(ambient / "jdk-17.0.20+8"))
    probe = advisors.probe_temurin_jdk_identity(install_root=tmp_path / "empty")
    assert probe["satisfied"] is False
    assert probe["ambient_java_home_trusted"] is False
    assert probe.get("ambient_java_home_observed") is True


def test_semantic_cases_cover_required_kinds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform_key = "linux-x86_64"
    root = tmp_path / "install"
    home = _fake_jdk_home(tmp_path / "src")
    archive = tmp_path / "jdk.tgz"
    digest, size = _tarball(archive, home)
    pin = advisors.select_strict_pin(
        TOOL_ID,
        platform_key=platform_key,
        allow_source_fallback=False,
    )
    monkeypatch.setitem(
        advisors.TEMURIN_JDK_PINS,
        platform_key,
        {
            **advisors.TEMURIN_JDK_PINS[platform_key],
            "sha256": digest,
            "artifact_size_bytes": size,
        },
    )
    monkeypatch.setattr(
        advisors,
        "select_strict_pin",
        lambda *args, **kwargs: advisors.ToolPin(
            tool_id=pin.tool_id,
            version=pin.version,
            platform=platform_key,
            artifact_url=pin.artifact_url,
            sha256=digest,
            identity_kind=pin.identity_kind,
            license=pin.license,
            source=pin.source,
            is_checksummed=True,
            requires_checksum_at_install=True,
            release_tag=pin.release_tag,
            artifact_size_bytes=size,
        ),
    )
    receipt = advisors.ensure_temurin_jdk(
        yes=True,
        strict=False,
        install_root=root,
        platform_key=platform_key,
        artifact_path=archive,
    )
    assert receipt.ok
    cases = advisors.run_ergoai_java_api_semantic_cases(install_root=root)
    assert set(cases["case_kinds"]) == set(advisors.ERGOAI_JAVA_API_CASE_KINDS)
    assert cases["all_passed"] is True
    assert cases["probe"]["ambient_java_home_trusted"] is False


def test_resolve_reviewed_installer_points_at_ensure_temurin_jdk() -> None:
    ensure = lazy_installer._resolve_reviewed_installer("temurin-jdk")
    assert ensure is advisors.ensure_temurin_jdk


def test_managed_runtime_env_binds_exact_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform_key = "linux-x86_64"
    root = tmp_path / "install"
    home = _fake_jdk_home(tmp_path / "src")
    archive = tmp_path / "jdk.tgz"
    digest, size = _tarball(archive, home)
    pin = advisors.select_strict_pin(
        TOOL_ID,
        platform_key=platform_key,
        allow_source_fallback=False,
    )
    monkeypatch.setitem(
        advisors.TEMURIN_JDK_PINS,
        platform_key,
        {
            **advisors.TEMURIN_JDK_PINS[platform_key],
            "sha256": digest,
            "artifact_size_bytes": size,
        },
    )
    monkeypatch.setattr(
        advisors,
        "select_strict_pin",
        lambda *args, **kwargs: advisors.ToolPin(
            tool_id=pin.tool_id,
            version=pin.version,
            platform=platform_key,
            artifact_url=pin.artifact_url,
            sha256=digest,
            identity_kind=pin.identity_kind,
            license=pin.license,
            source=pin.source,
            is_checksummed=True,
            requires_checksum_at_install=True,
            release_tag=pin.release_tag,
            artifact_size_bytes=size,
        ),
    )
    receipt = advisors.ensure_temurin_jdk(
        yes=True,
        strict=False,
        install_root=root,
        platform_key=platform_key,
        artifact_path=archive,
    )
    assert receipt.ok
    env = advisors.managed_temurin_runtime_env(install_root=root)
    managed = advisors.managed_temurin_java_home(install_root=root)
    assert managed is not None
    assert env["JAVA_HOME"] == str(managed)
    assert str(managed / "bin") in env["PATH"].split(os.pathsep)
    # Ambient options are stripped.
    assert "JDK_JAVA_OPTIONS" not in env
    assert "JAVA_TOOL_OPTIONS" not in env
