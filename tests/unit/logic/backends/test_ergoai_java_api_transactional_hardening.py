"""Transactional hardening for managed ErgoAI Java/JDK (FVT-091 / FVT-G223).

Proves adversarial, fail-closed lifecycle properties without claiming live
vendor authority:

* HOME / install-root path boundaries
* single-flight install lock + abandoned lock recovery
* force=True replacement rolls back to previous-good
* publisher evidence binding
* tool byte-mutation rejection
* HelloWorld cannot satisfy vendor consumer semantics
* timeout terminates process tree and cleans workspaces
* core ErgoAI independence and advisor authority ceiling
"""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
import textwrap
import threading
import time
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.backends.installers import advisors


TOOL_ID = "temurin-jdk"
LOCKED_VERSION = advisors.TEMURIN_JDK_VERSION
PLATFORM = "linux-x86_64"


def _write_executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_jdk_home(root: Path, *, version: str = "17.0.20") -> Path:
    home = root / f"jdk-{version}+8"
    bin_dir = home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_executable(
        bin_dir / "java",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            if [[ "${{1:-}}" == "-version" || "${{1:-}}" == "--version" ]]; then
              echo 'openjdk version "{version}" 2026-01-01' >&2
              echo 'OpenJDK Runtime Environment Temurin-{version}+8' >&2
              exit 0
            fi
            # Support -cp ClassName for timeout/consumer fixtures.
            if [[ "${{1:-}}" == "-cp" ]]; then
              shift 2
              class="${{1:-}}"
              if [[ "$class" == "SleepForever" ]]; then
                while true; do sleep 1; done
              fi
              if [[ "$class" == "HelloWorld" ]]; then
                echo HelloWorld
                exit 0
              fi
              if [[ "$class" == "ErgoAIVendorConsumer" ]]; then
                launcher="${{2:-}}"
                out=$("$launcher" --version 2>&1) || exit $?
                printf '%s' "$out"
                if ! printf '%s' "$out" | grep -Eq 'ErgoAI|Ergo|3\\.0'; then
                  echo 'vendor identity banner missing' >&2
                  exit 3
                fi
                echo ERGOAI_JAVA_VENDOR_CONSUMER_OK
                exit 0
              fi
              exit 1
            fi
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
            # "Compile" by accepting any .java source without writing classes.
            for arg in "$@"; do
              if [[ "$arg" == *.java ]]; then
                if grep -q 'not java' "$arg" 2>/dev/null; then
                  echo 'error: malformed source' >&2
                  exit 1
                fi
              fi
            done
            exit 0
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


def _install_fixture_jdk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    root: Path | None = None,
    force: bool = False,
    publisher_checksum_text: str | None = None,
    publisher_signature_bytes: bytes | None = None,
    artifact_path: Path | None = None,
) -> tuple[Path, Path, advisors.InstallReceipt]:
    install_root = root or (tmp_path / "install")
    home = _fake_jdk_home(tmp_path / "src")
    pin = advisors.select_strict_pin(
        TOOL_ID,
        platform_key=PLATFORM,
        allow_source_fallback=False,
    )
    archive = artifact_path or (tmp_path / Path(pin.artifact_url).name)
    if not archive.is_file():
        digest, size = _tarball(archive, home)
    else:
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        size = archive.stat().st_size

    monkeypatch.setitem(
        advisors.TEMURIN_JDK_PINS,
        PLATFORM,
        {
            **advisors.TEMURIN_JDK_PINS[PLATFORM],
            "sha256": digest,
            "artifact_size_bytes": size,
        },
    )

    def fake_select(*_args, **_kwargs):
        return advisors.ToolPin(
            tool_id=pin.tool_id,
            version=pin.version,
            platform=PLATFORM,
            artifact_url=pin.artifact_url,
            sha256=digest,
            identity_kind=pin.identity_kind,
            license=pin.license,
            source=pin.source,
            is_checksummed=True,
            requires_checksum_at_install=True,
            release_tag=pin.release_tag,
            artifact_size_bytes=size,
        )

    monkeypatch.setattr(advisors, "select_strict_pin", fake_select)
    receipt = advisors.ensure_temurin_jdk(
        yes=True,
        strict=False,
        force=force,
        install_root=install_root,
        platform_key=PLATFORM,
        artifact_path=archive,
        publisher_checksum_text=publisher_checksum_text,
        publisher_signature_bytes=publisher_signature_bytes,
    )
    return install_root, archive, receipt


def test_home_and_install_root_boundaries(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    child = home / "child"
    child.mkdir()
    advisors.assert_strict_home_descendant(child, home=home)
    with pytest.raises(advisors.AdvisorInstallerError, match="HOME itself"):
        advisors.assert_strict_home_descendant(home, home=home)
    with pytest.raises(advisors.AdvisorInstallerError, match="escapes"):
        advisors.assert_strict_home_descendant(tmp_path / "sibling", home=home)

    root = tmp_path / "root"
    nested = root / "advisors" / TOOL_ID
    nested.mkdir(parents=True)
    advisors.assert_strict_install_root_descendant(root, nested)
    with pytest.raises(advisors.AdvisorInstallerError, match="strict install-root"):
        advisors.assert_strict_install_root_descendant(root, root)
    with pytest.raises(advisors.AdvisorInstallerError, match="escapes"):
        advisors.assert_strict_install_root_descendant(root, root.parent / "escape")


def test_single_flight_lock_and_abandoned_recovery(tmp_path: Path) -> None:
    root = tmp_path / "lock-root"
    root.mkdir()
    observed: list[str] = []

    def worker(name: str) -> None:
        with advisors.temurin_installation_lock(root, wait_timeout=5.0):
            observed.append(f"{name}:enter")
            time.sleep(0.05)
            observed.append(f"{name}:exit")

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert observed[0].endswith(":enter")
    assert observed[1].endswith(":exit")
    assert observed[2].endswith(":enter")
    assert observed[3].endswith(":exit")

    # Abandoned lock recovery: stale metadata with dead PID is reclaimable.
    lock_dir = root / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / advisors.TEMURIN_INSTALL_LOCK_NAME
    lock_path.write_text(
        json.dumps(
            {
                "schema_version": "temurin-jdk-install-lock/v1",
                "pid": 2**30,  # almost certainly not alive
                "created_at_unix": time.time() - advisors.TEMURIN_LOCK_STALE_SECONDS - 10,
                "hostname": "fixture",
            }
        ),
        encoding="utf-8",
    )
    with advisors.temurin_installation_lock(root, wait_timeout=2.0) as held:
        assert held.name == advisors.TEMURIN_INSTALL_LOCK_NAME


def test_force_replacement_rolls_back_to_previous_good(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_root, archive, first = _install_fixture_jdk(tmp_path, monkeypatch)
    assert first.ok
    identity_path = (
        install_root / "advisors" / TOOL_ID / LOCKED_VERSION / "identity.json"
    )
    before = identity_path.read_text(encoding="utf-8")
    probe_before = advisors.probe_temurin_jdk_identity(install_root=install_root)
    assert probe_before["satisfied"] is True

    # force=True with missing artifact must fail without destroying previous-good.
    failed = advisors.ensure_temurin_jdk(
        yes=True,
        strict=False,
        force=True,
        install_root=install_root,
        platform_key=PLATFORM,
        artifact_path=tmp_path / "missing-force-artifact.bin",
    )
    assert not failed.ok
    assert identity_path.is_file()
    assert identity_path.read_text(encoding="utf-8") == before
    probe_after = advisors.probe_temurin_jdk_identity(install_root=install_root)
    assert probe_after["satisfied"] is True


def test_publisher_evidence_and_mutation_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _fake_jdk_home(tmp_path / "publisher-src")
    archive = tmp_path / "publisher-OpenJDK17U-jdk_x64_linux_hotspot_17.0.20_8.tar.gz"
    digest, size = _tarball(archive, home)
    # Use a ToolPin whose URL basename matches the archive name for evidence binding.
    artifact_url = (
        "https://github.com/adoptium/temurin17-binaries/releases/download/"
        "jdk-17.0.20%2B8/" + archive.name
    )
    pin = advisors.ToolPin(
        tool_id=TOOL_ID,
        version=LOCKED_VERSION,
        platform=PLATFORM,
        artifact_url=artifact_url,
        sha256=digest,
        identity_kind=advisors.TEMURIN_JDK_IDENTITY_KIND,
        license=advisors.TEMURIN_JDK_LICENSE,
        source=advisors.TEMURIN_JDK_SOURCE,
        is_checksummed=True,
        requires_checksum_at_install=True,
        release_tag=advisors.TEMURIN_JDK_RELEASE_NAME,
        artifact_size_bytes=size,
    )
    meta = {
        **advisors.TEMURIN_JDK_PINS[PLATFORM],
        "sha256": digest,
        "artifact_size_bytes": size,
        "artifact_url": artifact_url,
    }
    checksum_text = f"{digest}  {archive.name}\n"
    evidence = advisors.verify_temurin_publisher_evidence(
        archive,
        pin=pin,
        meta=meta,
        checksum_text=checksum_text,
        signature_bytes=b"\x01\x02detached-sig-fixture",
    )
    assert evidence["checksum_text_bound"] is True
    assert evidence["signature_bytes_bound"] is True
    assert evidence["publisher_evidence_satisfied"] is True

    with pytest.raises(advisors.AdvisorInstallerError, match="checksum text"):
        advisors.verify_temurin_publisher_evidence(
            archive,
            pin=pin,
            meta=meta,
            checksum_text="0" * 64 + "  wrong-name.tar.gz\n",
        )

    install_root, _, receipt = _install_fixture_jdk(
        tmp_path,
        monkeypatch,
        root=tmp_path / "publisher-install",
        publisher_checksum_text=checksum_text,
        publisher_signature_bytes=b"\x01\x02detached-sig-fixture",
        artifact_path=archive,
    )
    assert receipt.ok
    accepted = advisors.reject_mutated_temurin_identity(install_root=install_root)
    assert accepted["accepted"] is True

    java = Path(str(advisors.probe_temurin_jdk_identity(install_root=install_root)["java_home"])) / "bin" / "java"
    original = java.read_bytes()
    java.write_bytes(original + b"\x00mut")
    try:
        rejected = advisors.reject_mutated_temurin_identity(install_root=install_root)
        assert rejected["accepted"] is False
        reasons = " ".join(str(code) for code in (rejected.get("reason_codes") or []))
        assert (
            "tool_byte_mutation" in reasons
            or "tool_identity_mismatch" in reasons
            or "managed_jdk_unsatisfied" in reasons
            or rejected.get("drift")
        )
    finally:
        java.write_bytes(original)


def test_hello_world_rejected_and_vendor_consumer_with_hermetic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_root, _, receipt = _install_fixture_jdk(tmp_path, monkeypatch)
    assert receipt.ok
    advisors.materialize_hermetic_ergoai(install_root=install_root)

    java_home = Path(
        str(advisors.probe_temurin_jdk_identity(install_root=install_root)["java_home"])
    )
    hello = advisors.run_hello_world_java_probe(
        java_home=java_home,
        workspace=tmp_path / "hello-ws",
    )
    assert hello["satisfies_vendor_java_consumer"] is False
    assert hello["compiled"] is True

    denied = advisors.run_ergoai_java_vendor_consumer(
        install_root=install_root,
        allow_hermetic_ergoai=False,
    )
    assert denied["satisfies_vendor_java_consumer"] is False
    assert "hermetic_shim_cannot_satisfy_live_vendor_consumer" in denied["reason_codes"]

    allowed = advisors.run_ergoai_java_vendor_consumer(
        install_root=install_root,
        allow_hermetic_ergoai=True,
    )
    assert allowed["satisfies_vendor_java_consumer"] is True
    assert allowed["status"] == "passed"
    assert allowed["cleanup"].get("removed") is True
    assert allowed["hello_world_probe"]["satisfies_vendor_java_consumer"] is False


def test_timeout_process_tree_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_root, _, receipt = _install_fixture_jdk(tmp_path, monkeypatch)
    assert receipt.ok
    result = advisors.run_java_api_timeout_process_tree(
        install_root=install_root,
        timeout=0.05,
    )
    assert result["process_tree_terminated"] is True
    assert result["status"] == "passed"
    assert result["cleanup"].get("removed") is True


def test_force_success_replaces_and_core_independence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_root, archive, first = _install_fixture_jdk(tmp_path, monkeypatch)
    assert first.ok
    second = advisors.ensure_temurin_jdk(
        yes=True,
        strict=False,
        force=True,
        install_root=install_root,
        platform_key=PLATFORM,
        artifact_path=archive,
    )
    assert second.ok
    probe = advisors.probe_temurin_jdk_identity(install_root=install_root)
    assert probe["satisfied"] is True
    assert probe["ambient_java_home_trusted"] is False

    empty = tmp_path / "no-jdk"
    empty.mkdir()
    empty_probe = advisors.probe_temurin_jdk_identity(install_root=empty)
    assert empty_probe["satisfied"] is False
    # Core ErgoAI hermetic path remains independent of Java.
    hermetic = advisors.materialize_hermetic_ergoai(install_root=empty)
    assert hermetic is not None
    ergo = advisors.probe_ergoai_identity(
        install_root=empty,
        allow_path_fallback=False,
    )
    assert ergo.get("path_present") is True
    assert ergo.get("version_match") is True

    # Provide hermetic ErgoAI under the JDK root for vendor-consumer case.
    advisors.materialize_hermetic_ergoai(install_root=install_root)
    # Avoid lock pin drift vs fixture digests: exercise live cases without the
    # lock re-assert path by calling case runners directly and checking the
    # offline certification shape separately.
    monkeypatch.setattr(
        advisors,
        "build_ergoai_java_api_toolchain_contract",
        lambda **_kwargs: {
            "interface": advisors.ERGOAI_JAVA_API_INTERFACE,
            "ok": True,
            "policy": {
                "never_trust_ambient_java_home": True,
                "missing_capability_does_not_block_core_ergoai": True,
            },
        },
    )
    receipt = advisors.build_ergoai_java_api_live_certification(
        install_root=install_root,
        run_live_cases=True,
        allow_hermetic_ergoai=True,
        yes=False,
    )
    assert receipt["interface"] == advisors.ERGOAI_JAVA_API_LIVE_INTERFACE
    assert receipt["goal_id"] == "FVT-G223"
    assert receipt["task_id"] == "FVT-091"
    assert receipt["grants_theorem_authority"] is False
    assert receipt["core_ergoai_independent"] is True
    assert receipt["authority_ceiling"] == "advisory"
    kinds = {case["kind"]: case["status"] for case in receipt["cases"]}
    for kind in advisors.ERGOAI_JAVA_API_LIVE_CASE_KINDS:
        assert kind in kinds
        assert kinds[kind] in {"passed", "skipped"}
