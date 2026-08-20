"""Hermetic unit tests for the DQK-084 DuckLake capability contract.

All probes use pure in-memory fixtures. The suite never imports optional
``duckdb``, never LOADs extensions, never ATTACHes a catalog, and never
opens network sockets. It covers:

* DuckLake v1.0 / Quack / httpfs digest attestation against DQK-082 pins
* explicit LOAD order before the configuration lock
* fail-closed DuckDB/platform/catalog mismatch before ATTACH
* automatic install, load, and catalog migration remaining off
* DuckLake disabled without affecting the authoritative control plane
* import-time inertness of the capabilities module
"""

from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path
from typing import Any

# Prefer the sealed validator's accelerator checkout in nested worktrees.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return

    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

import pytest

from ipfs_datasets_py.ducklake import capabilities as caps


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

_PLATFORM = "linux_amd64"


def _pins(platform: str = _PLATFORM) -> dict[str, caps.ExtensionArtifactPin]:
    return dict(caps.platform_extension_pins(platform))


def _ext(
    name: str,
    *,
    platform: str = _PLATFORM,
    loaded: bool = True,
    before_lock: bool = True,
    digests: bool = True,
    build: str | None = None,
    corrupt_digest: bool = False,
) -> caps.ObservedExtensionState:
    pin = _pins(platform)[name]
    gz = pin.gz_sha256
    bin_ = pin.bin_sha256
    if corrupt_digest:
        gz = "0" * 64
    return caps.ObservedExtensionState(
        name=name,
        version="1.5.5",
        build=build if build is not None else pin.build,
        platform=platform,
        gz_sha256=gz if digests else None,
        bin_sha256=bin_ if digests else None,
        loaded=loaded,
        loaded_before_configuration_lock=before_lock,
    )


def _locked_settings() -> dict[str, str]:
    return {
        "autoinstall_known_extensions": "false",
        "autoload_known_extensions": "false",
        "allow_unsigned_extensions": "false",
        "ducklake_auto_migration": "false",
    }


def _observed_ok(
    *,
    platform: str = _PLATFORM,
    duckdb_version: str = "1.5.5",
    load_order: tuple[str, ...] | None = None,
    **overrides: Any,
) -> caps.ObservedRuntimeState:
    order = load_order if load_order is not None else caps.EXPLICIT_LOAD_ORDER
    extensions = {
        "quack": _ext("quack", platform=platform),
        "ducklake": _ext("ducklake", platform=platform),
        "httpfs": _ext("httpfs", platform=platform),
    }
    payload: dict[str, Any] = {
        "duckdb_version": duckdb_version,
        "platform": platform,
        "extensions": extensions,
        "catalog": caps.ObservedCatalogState(
            specification_version=caps.REQUIRED_DUCKLAKE_SPECIFICATION_VERSION,
            catalog_version=caps.REQUIRED_DUCKLAKE_CATALOG_VERSION,
            automatic_migration_enabled=False,
        ),
        "settings": _locked_settings(),
        "load_order_observed": order,
        "configuration_locked": True,
    }
    payload.update(overrides)
    return caps.ObservedRuntimeState(**payload)


def _receipt(
    *,
    platform: str = _PLATFORM,
    duckdb_version: str = "1.5.5",
    schema: str | None = None,
    corrupt_digest: bool = False,
    enable_autoinstall: bool = False,
    load_order: list[str] | None = None,
    quack_build: str | None = None,
    ducklake_build: str | None = None,
) -> dict[str, Any]:
    pins = _pins(platform)
    extensions: dict[str, Any] = {}
    for name, pin in pins.items():
        gz = "0" * 64 if corrupt_digest and name == "ducklake" else pin.gz_sha256
        extensions[name] = {
            "name": name,
            "platform": platform,
            "gz_sha256": f"sha256:{gz}",
            "bin_sha256": pin.bin_digest,
            "build": pin.build,
        }
    settings = _locked_settings()
    if enable_autoinstall:
        settings["autoinstall_known_extensions"] = "true"
    return {
        "schema": schema or caps.ENVIRONMENT_RECEIPT_SCHEMA,
        "receipt_id": "receipt:sha256:test",
        "duckdb": {
            "version": duckdb_version,
            "required_version": "1.5.5",
            "exact": duckdb_version == "1.5.5",
        },
        "platform": {"system": "Linux", "machine": "x86_64"},
        "quack": {
            "build": quack_build or caps.PINNED_QUACK_EXTENSION_BUILD,
            "artifact": extensions["quack"],
            "checksums_pinned": True,
        },
        "ducklake": {
            "build": ducklake_build or caps.PINNED_DUCKLAKE_EXTENSION_BUILD,
            "artifact": extensions["ducklake"],
            "checksums_pinned": True,
            "catalog_migration_disabled": True,
        },
        "extension_profile": {
            "schema": "ipfs_datasets_py/duckdb-quack-extension-profile@1",
            "platform": platform,
            "settings": settings,
            "load_order": load_order or list(caps.EXPLICIT_LOAD_ORDER),
            "automatic_install_disabled": not enable_autoinstall,
            "automatic_load_disabled": True,
            "ducklake_catalog_migration_disabled": True,
            "extensions": extensions,
        },
        "settings_after_provisioning": settings,
        "automatic_extension_install_disabled": not enable_autoinstall,
        "automatic_extension_load_disabled": True,
    }


# ---------------------------------------------------------------------------
# Import-time safety
# ---------------------------------------------------------------------------


def test_capability_module_import_is_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing capabilities must not import duckdb or load extensions."""

    forbidden = {"duckdb", "duckdb.experimental"}
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".", 1)[0]
        if root in forbidden or name in forbidden:
            raise AssertionError(f"import of {name!r} is forbidden at module import")
        return real_import(name, globals, locals, fromlist, level)

    for mod in (
        "ipfs_datasets_py.ducklake.capabilities",
        "ipfs_datasets_py.ducklake",
    ):
        sys.modules.pop(mod, None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    reloaded = importlib.import_module("ipfs_datasets_py.ducklake.capabilities")
    assert reloaded.REQUIRED_DUCKDB_VERSION == (1, 5, 5)
    assert reloaded.REQUIRED_DUCKLAKE_SPECIFICATION_VERSION == "1.0"
    assert reloaded.AUTOMATIC_EXTENSION_INSTALL is False
    assert reloaded.AUTOMATIC_EXTENSION_LOAD is False
    assert reloaded.AUTOMATIC_CATALOG_MIGRATION is False
    sys.modules["ipfs_datasets_py.ducklake.capabilities"] = reloaded
    monkeypatch.setattr(builtins, "__import__", real_import)


def test_module_does_not_require_duckdb_at_import() -> None:
    assert caps.REQUIRED_DUCKDB_VERSION_TEXT == "1.5.5"
    assert caps.PINNED_QUACK_EXTENSION_BUILD == "quack@1.5.5+core"
    assert caps.PINNED_DUCKLAKE_EXTENSION_BUILD == "ducklake@1.5.5+core"
    assert caps.PINNED_HTTPFS_EXTENSION_BUILD == "httpfs@1.5.5+core"
    assert caps.DEFAULT_CAPABILITY_POLICY.duckdb_version == (1, 5, 5)


def test_package_exports_capability_contract() -> None:
    import ipfs_datasets_py.ducklake as ducklake_pkg

    assert ducklake_pkg.REQUIRED_DUCKLAKE_SPECIFICATION_VERSION == "1.0"
    assert ducklake_pkg.EXPLICIT_LOAD_ORDER == ("quack", "ducklake", "httpfs")
    assert callable(ducklake_pkg.probe_ducklake_capabilities)


# ---------------------------------------------------------------------------
# Policy pins and load order
# ---------------------------------------------------------------------------


def test_default_policy_pins_ducklake_v1_and_disables_automation() -> None:
    policy = caps.DEFAULT_CAPABILITY_POLICY
    mapping = dict(policy.as_mapping())
    assert mapping["duckdb_version"] == "1.5.5"
    assert mapping["ducklake_specification_version"] == "1.0"
    assert mapping["ducklake_catalog_version"] == "1.0"
    assert mapping["quack_extension_build"] == "quack@1.5.5+core"
    assert mapping["ducklake_extension_build"] == "ducklake@1.5.5+core"
    assert mapping["httpfs_extension_build"] == "httpfs@1.5.5+core"
    assert mapping["object_store_adapter"] == "httpfs"
    assert mapping["explicit_load_order"] == ["quack", "ducklake", "httpfs"]
    assert mapping["load_before_configuration_lock"] is True
    assert mapping["automatic_extension_install"] is False
    assert mapping["automatic_extension_load"] is False
    assert mapping["automatic_catalog_migration"] is False
    assert mapping["attach_safe_options"] == {
        "CREATE_IF_NOT_EXISTS": False,
        "OVERRIDE_DATA_PATH": False,
        "AUTOMATIC_MIGRATION": False,
    }
    assert "ducklake_merge_adjacent_files" in mapping["supported_maintenance_functions"]
    assert "ducklake_expire_snapshots" in mapping["supported_maintenance_functions"]
    assert "ducklake_cleanup_old_files" in mapping["supported_maintenance_functions"]
    assert "ducklake_delete_orphaned_files" in mapping["supported_maintenance_functions"]
    assert "ducklake_rewrite_data_files" in mapping["supported_maintenance_functions"]
    assert "ducklake_flush_inlined_data" in mapping["supported_maintenance_functions"]


def test_policy_refuses_automatic_behaviours() -> None:
    with pytest.raises(caps.CapabilityError, match="automatic extension install"):
        caps.DuckLakeCapabilityPolicy(automatic_extension_install=True)
    with pytest.raises(caps.CapabilityError, match="automatic extension load"):
        caps.DuckLakeCapabilityPolicy(automatic_extension_load=True)
    with pytest.raises(caps.CapabilityError, match="automatic catalog migration"):
        caps.DuckLakeCapabilityPolicy(automatic_catalog_migration=True)
    with pytest.raises(caps.CapabilityError, match="unsigned"):
        caps.DuckLakeCapabilityPolicy(allow_unsigned_extensions=True)
    with pytest.raises(caps.CapabilityError, match="before the configuration lock"):
        caps.DuckLakeCapabilityPolicy(load_before_configuration_lock=False)


def test_explicit_load_order_and_configuration_lock_plan() -> None:
    order = caps.explicit_load_order()
    assert order == ("quack", "ducklake", "httpfs")
    assert caps.LOAD_BEFORE_CONFIGURATION_LOCK is True
    plan = dict(caps.configuration_lock_plan())
    assert plan["phase"] == "load_then_lock"
    assert plan["load_before_configuration_lock"] is True
    assert plan["load_order"] == ["quack", "ducklake", "httpfs"]
    assert plan["automatic_extension_install"] is False
    assert plan["automatic_extension_load"] is False
    assert plan["automatic_catalog_migration"] is False
    assert plan["configuration_lock_settings"]["autoinstall_known_extensions"] == "false"
    assert plan["configuration_lock_settings"]["autoload_known_extensions"] == "false"
    assert plan["configuration_lock_settings"]["ducklake_auto_migration"] == "false"
    # Object-store adapter is the selected third LOAD entry.
    assert plan["load_order"][2] == caps.DEFAULT_OBJECT_STORE_ADAPTER.value


def test_platform_extension_pins_cover_both_linux_targets() -> None:
    for platform in sorted(caps.SUPPORTED_PLATFORMS):
        pins = caps.platform_extension_pins(platform)
        assert set(pins) == {"quack", "ducklake", "httpfs"}
        for name, pin in pins.items():
            assert pin.platform == platform
            assert pin.gz_sha256
            assert pin.bin_sha256
            assert pin.build.endswith("+core")
            assert name in pin.build


def test_unpinned_object_store_adapter_fails_closed() -> None:
    with pytest.raises(caps.CapabilityError, match="not digest-pinned"):
        caps.platform_extension_pins(_PLATFORM, object_store_adapter="azure")


def test_policy_pin_summary_is_stable() -> None:
    summary = dict(caps.policy_pin_summary())
    assert summary["duckdb"] == "1.5.5"
    assert summary["ducklake_specification"] == "1.0"
    assert summary["automatic_install"] is False
    assert summary["automatic_load"] is False
    assert summary["automatic_catalog_migration"] is False
    assert summary["load_order"] == ["quack", "ducklake", "httpfs"]


# ---------------------------------------------------------------------------
# Environment receipt binding and digest attestation
# ---------------------------------------------------------------------------


def test_bind_environment_receipt_attests_all_enabled_digests() -> None:
    binding = caps.bind_environment_receipt(_receipt())
    assert binding.schema == caps.ENVIRONMENT_RECEIPT_SCHEMA
    assert binding.duckdb_version == "1.5.5"
    assert binding.platform == _PLATFORM
    assert binding.quack_build == "quack@1.5.5+core"
    assert binding.ducklake_build == "ducklake@1.5.5+core"
    assert binding.load_order == ("quack", "ducklake", "httpfs")
    assert binding.automatic_extension_install_disabled is True
    assert binding.automatic_extension_load_disabled is True
    assert binding.ducklake_catalog_migration_disabled is True
    assert set(binding.extension_pins) == {"quack", "ducklake", "httpfs"}
    for pin in binding.extension_pins.values():
        assert pin.gz_digest.startswith("sha256:")
        assert pin.bin_digest.startswith("sha256:")


def test_bind_receipt_rejects_schema_mismatch() -> None:
    with pytest.raises(caps.VersionMismatchError, match="schema mismatch"):
        caps.bind_environment_receipt(_receipt(schema="other@1"))


def test_bind_receipt_rejects_duckdb_mismatch() -> None:
    with pytest.raises(caps.VersionMismatchError, match="DuckDB version mismatch"):
        caps.bind_environment_receipt(_receipt(duckdb_version="1.4.0"))


def test_bind_receipt_rejects_digest_mismatch() -> None:
    with pytest.raises(caps.ExtensionDigestMismatchError, match="digest mismatch"):
        caps.bind_environment_receipt(_receipt(corrupt_digest=True))


def test_bind_receipt_rejects_enabled_autoinstall() -> None:
    with pytest.raises(
        caps.VersionMismatchError,
        match="autoinstall_known_extensions|automatic extension install",
    ):
        caps.bind_environment_receipt(_receipt(enable_autoinstall=True))


def test_bind_receipt_rejects_load_order_drift() -> None:
    with pytest.raises(caps.VersionMismatchError, match="load order mismatch"):
        caps.bind_environment_receipt(
            _receipt(load_order=["ducklake", "quack", "httpfs"])
        )


def test_attest_extension_digests_for_enabled_catalog_owner_set() -> None:
    observed = _observed_ok()
    binding = caps.bind_environment_receipt(_receipt())
    attested = caps.attest_extension_digests(
        observed, platform=_PLATFORM, binding=binding
    )
    assert set(attested) == {"quack", "ducklake", "httpfs"}


def test_attest_extension_digests_fails_on_missing_digest() -> None:
    extensions = {
        "quack": _ext("quack", digests=False),
        "ducklake": _ext("ducklake"),
        "httpfs": _ext("httpfs"),
    }
    observed = _observed_ok(extensions=extensions)
    with pytest.raises(caps.ExtensionDigestMismatchError, match="not attested"):
        caps.attest_extension_digests(observed, platform=_PLATFORM)


def test_attest_extension_digests_fails_on_wrong_digest() -> None:
    extensions = {
        "quack": _ext("quack"),
        "ducklake": _ext("ducklake", corrupt_digest=True),
        "httpfs": _ext("httpfs"),
    }
    observed = _observed_ok(extensions=extensions)
    with pytest.raises(caps.ExtensionDigestMismatchError, match="digest mismatch"):
        caps.attest_extension_digests(observed, platform=_PLATFORM)


# ---------------------------------------------------------------------------
# Fail closed before ATTACH
# ---------------------------------------------------------------------------


def test_assert_compatible_before_attach_accepts_attested_state() -> None:
    observed = _observed_ok()
    binding = caps.bind_environment_receipt(_receipt())
    caps.assert_compatible_before_attach(observed, binding=binding)


def test_duckdb_mismatch_fails_before_attach() -> None:
    observed = _observed_ok(duckdb_version="1.5.4")
    with pytest.raises(caps.VersionMismatchError, match="before ATTACH"):
        caps.assert_compatible_before_attach(observed)


def test_platform_mismatch_fails_before_attach() -> None:
    # Build a fully attested linux_amd64 observation, then spoof the platform
    # identity so digests remain valid while the platform itself is refused.
    observed = _observed_ok(platform=_PLATFORM)
    spoofed = caps.ObservedRuntimeState(
        duckdb_version=observed.duckdb_version,
        platform="windows_amd64",
        extensions=observed.extensions,
        catalog=observed.catalog,
        settings=dict(observed.settings),
        load_order_observed=observed.load_order_observed,
        configuration_locked=observed.configuration_locked,
    )
    with pytest.raises(caps.VersionMismatchError, match="platform mismatch"):
        caps.assert_compatible_before_attach(spoofed)


def test_catalog_mismatch_fails_before_attach() -> None:
    observed = _observed_ok(
        catalog=caps.ObservedCatalogState(
            specification_version="0.3",
            catalog_version="0.3",
            automatic_migration_enabled=False,
        )
    )
    with pytest.raises(caps.CatalogMismatchError, match="before ATTACH"):
        caps.assert_compatible_before_attach(observed)


def test_load_after_configuration_lock_fails_before_attach() -> None:
    extensions = {
        "quack": _ext("quack", before_lock=True),
        "ducklake": _ext("ducklake", before_lock=False),
        "httpfs": _ext("httpfs", before_lock=True),
    }
    observed = _observed_ok(extensions=extensions)
    with pytest.raises(caps.VersionMismatchError, match="after the configuration lock"):
        caps.assert_compatible_before_attach(observed)


def test_wrong_load_order_fails_before_attach() -> None:
    observed = _observed_ok(load_order=("httpfs", "ducklake", "quack"))
    with pytest.raises(caps.VersionMismatchError, match="LOAD order mismatch"):
        caps.assert_compatible_before_attach(observed)


def test_automatic_migration_enabled_fails_before_attach() -> None:
    observed = _observed_ok(
        settings={
            **_locked_settings(),
            "ducklake_auto_migration": "true",
        },
        catalog=caps.ObservedCatalogState(
            specification_version="1.0",
            catalog_version="1.0",
            automatic_migration_enabled=True,
        ),
    )
    with pytest.raises(caps.VersionMismatchError, match="automatic catalog migration"):
        caps.assert_compatible_before_attach(observed)


def test_preflight_attach_allows_only_when_attested() -> None:
    observed = _observed_ok()
    binding = caps.bind_environment_receipt(_receipt())
    result = caps.preflight_attach(observed, binding=binding)
    assert result.allowed is True
    assert result.mismatches == ()
    assert result.load_order == ("quack", "ducklake", "httpfs")
    assert result.attach_options["CREATE_IF_NOT_EXISTS"] is False
    assert result.attach_options["OVERRIDE_DATA_PATH"] is False
    assert result.attach_options["AUTOMATIC_MIGRATION"] is False
    assert result.configuration_lock_settings["autoinstall_known_extensions"] == "false"


def test_preflight_attach_raises_on_mismatch_when_fail_closed() -> None:
    observed = _observed_ok(duckdb_version="1.4.1")
    with pytest.raises(caps.VersionMismatchError, match="before ATTACH"):
        caps.preflight_attach(observed, fail_closed=True)


def test_preflight_attach_can_return_denied_without_raise() -> None:
    observed = _observed_ok(duckdb_version="1.4.1")
    result = caps.preflight_attach(observed, fail_closed=False)
    assert result.allowed is False
    assert any("DuckDB version mismatch" in item for item in result.mismatches)


# ---------------------------------------------------------------------------
# Probe: disabled DuckLake leaves control plane independent
# ---------------------------------------------------------------------------


def test_ducklake_disabled_without_affecting_control_plane() -> None:
    result = caps.probe_ducklake_capabilities(
        caps.ProbeRequest(enable_ducklake=False),
        observed=caps.ObservedRuntimeState(),
    )
    assert result.ok is True
    assert result.control_plane_independent is True
    assert result.feature_gate.state is caps.DuckLakeFeatureState.DISABLED
    assert result.feature_gate.control_plane_affected is False
    assert result.feature_gate.enabled is False
    assert "control plane" in (result.feature_gate.reason or "").lower()
    assert result.preflight is None
    assert result.capabilities["ducklake_extension"].status is caps.CapabilityStatus.DISABLED
    assert result.capabilities["ducklake_catalog"].status is caps.CapabilityStatus.DISABLED
    assert result.mismatches == ()
    # Configuration plan still documents the safe defaults for later enablement.
    assert result.configuration_plan["automatic_extension_install"] is False
    assert result.configuration_plan["automatic_catalog_migration"] is False


def test_evaluate_feature_gate_disabled_is_control_plane_safe() -> None:
    gate = caps.evaluate_ducklake_feature_gate(requested=False)
    assert gate.state is caps.DuckLakeFeatureState.DISABLED
    assert gate.control_plane_affected is False
    assert gate.enabled is False


# ---------------------------------------------------------------------------
# Probe: happy path and fail-closed mismatches
# ---------------------------------------------------------------------------


def test_probe_enables_ducklake_when_fully_attested() -> None:
    observed = _observed_ok()
    receipt = _receipt()
    result = caps.probe_ducklake_capabilities(
        caps.ProbeRequest(
            enable_ducklake=True,
            platform=_PLATFORM,
            require_environment_receipt=True,
            require_extension_digests=True,
            require_catalog_version=True,
            perform_attach_preflight=True,
        ),
        observed=observed,
        environment_receipt=receipt,
    )
    assert result.ok is True
    assert result.schema == caps.CAPABILITY_PROBE_SCHEMA
    assert result.feature_gate.enabled is True
    assert result.feature_gate.control_plane_affected is False
    assert result.control_plane_independent is True
    assert result.environment_binding is not None
    assert result.preflight is not None
    assert result.preflight.allowed is True
    assert result.capabilities["duckdb_runtime"].status is caps.CapabilityStatus.AVAILABLE
    assert result.capabilities["ducklake_extension"].status is caps.CapabilityStatus.AVAILABLE
    assert result.capabilities["quack_extension"].status is caps.CapabilityStatus.AVAILABLE
    assert (
        result.capabilities["object_store_adapter"].status is caps.CapabilityStatus.AVAILABLE
    )
    assert result.capabilities["ducklake_catalog"].status is caps.CapabilityStatus.AVAILABLE
    assert result.capabilities["configuration_lock"].status is caps.CapabilityStatus.AVAILABLE
    assert result.capabilities["environment_receipt"].status is caps.CapabilityStatus.AVAILABLE
    assert result.capabilities["maintenance"].status is caps.CapabilityStatus.AVAILABLE
    maint = dict(result.capabilities["maintenance"].identity)
    assert maint["automatic"] is False
    assert "ducklake_merge_adjacent_files" in maint["supported_functions"]
    # Explicit LOAD before lock is recorded.
    assert result.configuration_plan["load_order"] == ["quack", "ducklake", "httpfs"]
    assert result.mismatches == ()


def test_probe_version_mismatch_fails_closed_and_refuses_attach() -> None:
    observed = _observed_ok(duckdb_version="1.4.0")
    result = caps.probe_ducklake_capabilities(
        caps.ProbeRequest(enable_ducklake=True, platform=_PLATFORM),
        observed=observed,
        environment_receipt=_receipt(),
        fail_closed=True,
    )
    assert result.ok is False
    assert result.fail_closed is True
    assert result.capabilities["duckdb_runtime"].status is caps.CapabilityStatus.MISMATCH
    assert result.preflight is not None
    assert result.preflight.allowed is False
    assert any("DuckDB" in item for item in result.mismatches)


def test_probe_catalog_mismatch_fails_closed() -> None:
    observed = _observed_ok(
        catalog=caps.ObservedCatalogState(
            specification_version="0.2",
            catalog_version="0.2",
            automatic_migration_enabled=False,
        )
    )
    result = caps.probe_ducklake_capabilities(
        caps.ProbeRequest(enable_ducklake=True, platform=_PLATFORM),
        observed=observed,
        environment_receipt=_receipt(),
    )
    assert result.ok is False
    assert result.capabilities["ducklake_catalog"].status is caps.CapabilityStatus.MISMATCH
    assert result.preflight is not None
    assert result.preflight.allowed is False


def test_probe_extension_digest_mismatch_fails_closed() -> None:
    extensions = {
        "quack": _ext("quack"),
        "ducklake": _ext("ducklake", corrupt_digest=True),
        "httpfs": _ext("httpfs"),
    }
    observed = _observed_ok(extensions=extensions)
    result = caps.probe_ducklake_capabilities(
        caps.ProbeRequest(enable_ducklake=True, platform=_PLATFORM),
        observed=observed,
        environment_receipt=_receipt(),
    )
    assert result.ok is False
    assert result.capabilities["ducklake_extension"].status is caps.CapabilityStatus.MISMATCH


def test_probe_missing_object_store_adapter_fails_closed() -> None:
    extensions = {
        "quack": _ext("quack"),
        "ducklake": _ext("ducklake"),
        # httpfs intentionally missing
    }
    observed = _observed_ok(extensions=extensions)
    result = caps.probe_ducklake_capabilities(
        caps.ProbeRequest(enable_ducklake=True, platform=_PLATFORM),
        observed=observed,
        environment_receipt=_receipt(),
    )
    assert result.ok is False
    assert (
        result.capabilities["object_store_adapter"].status
        is caps.CapabilityStatus.UNAVAILABLE
        or result.capabilities["object_store_adapter"].status
        is caps.CapabilityStatus.MISMATCH
    )


def test_probe_autoinstall_enabled_fails_closed() -> None:
    observed = _observed_ok(
        settings={
            **_locked_settings(),
            "autoinstall_known_extensions": "true",
        }
    )
    result = caps.probe_ducklake_capabilities(
        caps.ProbeRequest(enable_ducklake=True, platform=_PLATFORM),
        observed=observed,
        environment_receipt=_receipt(),
    )
    assert result.ok is False
    assert result.capabilities["configuration_lock"].status is caps.CapabilityStatus.MISMATCH


def test_require_capability_raises_when_unavailable() -> None:
    result = caps.probe_ducklake_capabilities(
        caps.ProbeRequest(enable_ducklake=True),
        observed=caps.ObservedRuntimeState(),
    )
    assert result.ok is False
    with pytest.raises(caps.CapabilityUnavailableError):
        caps.require_capability(result, caps.CapabilityKind.DUCKDB_RUNTIME)


def test_require_capability_returns_available_record() -> None:
    result = caps.probe_ducklake_capabilities(
        caps.ProbeRequest(enable_ducklake=True, platform=_PLATFORM),
        observed=_observed_ok(),
        environment_receipt=_receipt(),
    )
    record = caps.require_capability(result, caps.CapabilityKind.DUCKLAKE_EXTENSION)
    assert record.status is caps.CapabilityStatus.AVAILABLE


def test_probe_result_as_mapping_is_json_friendly() -> None:
    result = caps.probe_ducklake_capabilities(
        caps.ProbeRequest(enable_ducklake=True, platform=_PLATFORM),
        observed=_observed_ok(),
        environment_receipt=_receipt(),
    )
    mapping = dict(result.as_mapping())
    assert mapping["schema"] == caps.CAPABILITY_PROBE_SCHEMA
    assert mapping["ok"] is True
    assert mapping["control_plane_independent"] is True
    assert mapping["policy"]["automatic_extension_install"] is False
    assert mapping["policy"]["automatic_catalog_migration"] is False
    assert mapping["feature_gate"]["enabled"] is True
    assert mapping["preflight"]["allowed"] is True
    assert mapping["configuration_plan"]["load_order"] == [
        "quack",
        "ducklake",
        "httpfs",
    ]


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------


def test_parse_and_format_version_round_trip() -> None:
    assert caps.parse_version("1.5.5") == (1, 5, 5)
    assert caps.parse_version("1.5.5.dev0") == (1, 5, 5)
    assert caps.parse_version((1, 5, 5)) == (1, 5, 5)
    assert caps.parse_version(None) == ()
    assert caps.format_version((1, 5, 5)) == "1.5.5"
    assert caps.versions_match_exact("1.5.5.post1", "1.5.5")
    assert not caps.versions_match_exact("1.5.4", "1.5.5")


def test_supported_maintenance_functions_are_explicit_call_targets() -> None:
    assert caps.SUPPORTED_MAINTENANCE_FUNCTIONS == tuple(
        member.value for member in caps.MaintenanceFunction
    )
    for name in caps.SUPPORTED_MAINTENANCE_FUNCTIONS:
        assert name.startswith("ducklake_")
