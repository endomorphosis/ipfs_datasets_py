from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.backends.installers import authorization as installer


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_historical_vendor_shim(install_root: Path) -> tuple[Path, Path]:
    pin = installer.pin_for_tool(installer.TOOL_SECPAL)
    executable = installer.executable_path(
        install_root,
        installer.TOOL_SECPAL,
        pin["version"],
        vendor=True,
    )
    manifest = installer.identity_manifest_path(
        install_root,
        installer.TOOL_SECPAL,
        pin["version"],
        vendor=True,
    )
    executable.parent.mkdir(parents=True)
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "print('secpal 1.0.0-reviewed (vendor-pin-bound sha256:unbound)')\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    manifest.write_text(
        json.dumps(
            {
                "artifact_sha256": _sha256(executable),
                "authority_ceiling": "none",
                "executable": str(executable),
                "identity_kind": pin["identity_kind"],
                "install_root": str(install_root),
                "interface": installer.VENDOR_INTERFACE,
                "is_hermetic_shadow": False,
                "is_vendor_build": True,
                "license": pin["license"],
                "platform_id": "linux-x86_64",
                "role": "shadow",
                "schema_version": installer.VENDOR_INSTALL_RECEIPT_SCHEMA,
                "source": pin["source"],
                "tool_id": installer.TOOL_SECPAL,
                "version": pin["version"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return executable, manifest


def test_secpal_python_engine_is_confined_to_shadow_lane(tmp_path: Path) -> None:
    install_root = (tmp_path / "managed").resolve()

    identity = installer.materialize_hermetic_shadow(
        installer.TOOL_SECPAL,
        install_root=install_root,
    )

    executable = Path(identity.executable)
    assert executable == (
        install_root
        / "authorization-shadows"
        / installer.TOOL_SECPAL
        / identity.version
        / "bin"
        / installer.TOOL_SECPAL
    )
    assert identity.is_hermetic_shadow is True
    assert identity.is_vendor_build is False
    assert not (install_root / "authorization-vendor").exists()

    completed = subprocess.run(
        [str(executable), "--version"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == (
        f"secpal {identity.version} (hermetic-authorization-shadow)"
    )
    assert "vendor" not in completed.stdout.casefold()


@pytest.mark.parametrize(
    "kwargs",
    (
        {"is_vendor_build": True},
        {"source_archive_sha256": "a" * 64},
    ),
)
def test_secpal_python_source_cannot_carry_vendor_evidence(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(
        installer.AuthorizationInstallerError,
        match="Python SecPAL shim",
    ):
        installer.build_shadow_shim_source(
            installer.TOOL_SECPAL,
            "1.0.0-reviewed",
            identity_file="/nonexistent/shadow/identity.json",
            **kwargs,
        )


def test_vendor_materializer_reports_arm64_unsupported_without_writes(
    tmp_path: Path,
) -> None:
    install_root = (tmp_path / "managed").resolve()

    with pytest.raises(
        installer.AuthorizationInstallerError,
        match=r"unsupported on 'linux-aarch64'",
    ):
        installer.materialize_vendor_secpal(
            install_root=install_root,
            platform_id="linux-aarch64",
        )

    assert not install_root.exists()


def test_vendor_materializer_reports_x86_unavailable_without_writes(
    tmp_path: Path,
) -> None:
    install_root = (tmp_path / "managed").resolve()

    with pytest.raises(
        installer.AuthorizationInstallerError,
        match=installer.SECPAL_VENDOR_UNAVAILABLE_REASON,
    ):
        installer.materialize_vendor_secpal(
            install_root=install_root,
            platform_id="linux-x86_64",
        )

    assert not install_root.exists()


def test_x86_vendor_request_rejects_historical_python_vendor_shim(
    tmp_path: Path,
) -> None:
    install_root = (tmp_path / "managed").resolve()
    executable, manifest = _seed_historical_vendor_shim(install_root)
    executable_digest = _sha256(executable)
    manifest_digest = _sha256(manifest)
    pin = installer.pin_for_tool(installer.TOOL_SECPAL)

    assert (
        installer._identity_from_disk(
            installer.TOOL_SECPAL,
            install_root,
            pin,
            vendor=True,
        )
        is None
    )

    receipt = installer.ensure_secpal(
        yes=True,
        strict=True,
        install_root=install_root,
        platform_id="linux-x86_64",
        hermetic_shadow=False,
        vendor=True,
        test_mode=True,
    )

    assert receipt.status == "unavailable"
    assert receipt.identity is None
    assert receipt.ok is False
    assert receipt.block_reasons == (
        installer.SECPAL_VENDOR_UNAVAILABLE_REASON,
    )
    assert receipt.is_vendor_path is True
    assert receipt.installed is False
    assert receipt.complete is False
    assert receipt.authoritative is False
    assert receipt.production_certified is False
    assert _sha256(executable) == executable_digest
    assert _sha256(manifest) == manifest_digest


def test_arm64_vendor_request_is_explicit_platform_exception(
    tmp_path: Path,
) -> None:
    receipt = installer.ensure_secpal(
        yes=True,
        strict=True,
        install_root=(tmp_path / "managed").resolve(),
        platform_id="linux-aarch64",
        hermetic_shadow=False,
        vendor=True,
        test_mode=True,
    )

    assert receipt.status == "unsupported_platform"
    assert receipt.identity is None
    assert receipt.platform_exception is True
    assert receipt.block_reasons == ("unsupported_platform_exception",)
    assert receipt.ok is False
    assert receipt.to_dict()["installed"] is False


def test_x86_vendor_bundle_propagates_explicit_secpal_unavailability(
    tmp_path: Path,
) -> None:
    bundle = installer.ensure_authorization_vendor(
        yes=True,
        strict=True,
        install_root=(tmp_path / "managed").resolve(),
        platform_id="linux-x86_64",
        tools=(installer.TOOL_SECPAL,),
        test_mode=True,
    )

    assert bundle.ok is False
    assert bundle.identities == {}
    assert len(bundle.receipts) == 1
    assert bundle.receipts[0].status == "unavailable"
    assert bundle.to_dict()["selected_engines"] == []


def test_installer_discovery_reports_shadow_and_vendor_scopes_separately() -> None:
    description = installer.describe_authorization_installer()
    by_tool = {item["tool_id"]: item for item in description["tools"]}

    assert by_tool[installer.TOOL_SECPAL]["shadow_materialization_status"] == "available"
    assert by_tool[installer.TOOL_SECPAL]["vendor_materialization_status"] == (
        "unavailable"
    )
    assert by_tool[installer.TOOL_SECPAL]["vendor_unavailable_reason"] == (
        installer.SECPAL_VENDOR_UNAVAILABLE_REASON
    )
    assert description["policy"]["secpal_python_engine_is_shadow_only"] is True


def test_secpal_vendor_identity_cannot_be_constructed() -> None:
    with pytest.raises(
        installer.AuthorizationInstallerError,
        match="cannot represent an authentic vendor SecPAL build",
    ):
        installer.ShadowEngineIdentity(
            tool_id=installer.TOOL_SECPAL,
            version="1.0.0-reviewed",
            executable="/tmp/secpal",
            license="MS-PL",
            source="https://example.invalid/secpal",
            identity_kind="operator_bound_artifact",
            is_hermetic_shadow=False,
            is_vendor_build=True,
        )
